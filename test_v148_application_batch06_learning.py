"""Exercise real execution producers and the persisted learning boundary."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
import DrawBot as app
from DrawTimeEstimate import record_completed_draw
from CompletedDrawLearning import timing_sample_gate
from AutoTunerFeedback import record_completed_feedback
from RuntimeSafetyReport import RuntimeSafetySession
from EdgeBehavior import EdgeBehaviorResult
from test_v148_storage_security import feedback_plan
from test_drawbot import Mouse, NoWait
from test_visual_verification_v1043 import simple_visual_plan


class Clock:
    def __init__(self):self.now=0.0
    def __call__(self):return self.now


class AdvancingWait(NoWait):
    def __init__(self,clock):super().__init__();self.clock=clock
    def wait(self,seconds):self.clock.now+=seconds;return self.stopped


class LearningExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(app,'log_event'))
        self.stack.enter_context(patch.object(app,'save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
        self.eta=self.stack.enter_context(patch('DrawTimeEstimate.record_completed_draw',wraps=record_completed_draw))
        self.sample=self.stack.enter_context(patch('DrawTimeCalibration.record_sample',return_value={'recorded':True}))
        self.speed=self.stack.enter_context(patch('RealSpeedBudget.record_runtime_sample',return_value={'recorded':False}))
        self.analysis=self.stack.enter_context(patch('CompletedDrawingAnalysis.record_completed_drawing',return_value={}))
        self.feedback=self.stack.enter_context(patch('AutoTunerFeedback.record_completed_feedback',return_value={}))
        self.stack.enter_context(patch('CorrectionHistory.record_correction_history',return_value={}))

    def plan(self,paths,*,sequence=False):
        plan=simple_visual_plan();plan['image'].close()
        plan['image']=Image.new('RGB',(20,20));self.addCleanup(plan['image'].close)
        plan['groups']=[paths,[]];plan['count']=len(paths)
        plan['estimate']=10.;plan['draw_time_estimate']={'preview_seconds':10.,'projected_seconds':10.}
        plan['options'].update(visual_verification_enabled=False,visual_verification_resolved='Off',
            strict_color_verification=False,adaptive_color_verification=False,unlimited_time=True,
            brush_px=1,canvas_guard_brush_px=1,edge_behavior='Hard Clip')
        if sequence:
            plan['execution_sequence']=[{'color_index':0,'path':(p[:2],p[2:]),
                'operation_type':'stroke','phase':'major_coverage','estimated_cost_seconds':.01,
                'importance':1.,'structural_score':1.} for p in paths]
        return plan

    def run_plan(self,plan,*,pause=False,dry_run=False):
        clock=Clock();paused=threading.Event();mouse=Mouse();events=[]
        if pause:
            original_release=mouse.release
            def release():
                held=mouse.held;original_release()
                if held and not getattr(mouse,'pause_sent',False):
                    mouse.pause_sent=True;paused.set()
            mouse.release=release
        def report(kind,value):
            events.append((kind,value))
            if kind=='status' and str(value).startswith('Paused'):
                clock.now+=120.;paused.clear()
        app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,
                         AdvancingWait(clock),paused,report,clock=clock,dry_run=dry_run)
        return mouse,events

    def test_guard_skips_finish_progress_but_do_not_become_sent_or_learned_paths(self):
        for sequence in (False,True):
            with self.subTest(sequence=sequence):
                self.sample.reset_mock()
                plan=self.plan([(0,0,19,0),(1,10,18,10)],sequence=sequence)
                mouse,events=self.run_plan(plan)
                self.assertEqual(sum(a[0]=='press' for a in mouse.actions),1)
                self.assertIn(('progress',(2,2)),events)
                self.assertEqual(plan['options']['runtime_path_counts'],{'processed':2,'sent':1,'guard_skipped':1})
                actual=[v for k,v in events if k=='draw_time_actual'][-1]
                self.assertEqual((actual['paths'],actual['processed_paths'],actual['guard_skipped_paths']),(1,2,1))
                self.assertIn('1 brush strokes sent',events[-1][1])
                self.assertEqual(self.eta.call_args.kwargs['completed_paths'],1)
                self.assertEqual(self.speed.call_args.args[1],1)
                self.assertEqual(self.analysis.call_args.kwargs['completed_paths'],1)
                self.assertEqual(self.feedback.call_args.kwargs['completed_paths'],1)
                self.assertFalse(plan['options']['draw_time_runtime_calibration']['recorded'])
                self.sample.assert_not_called()
                if sequence:self.assertEqual(plan['options']['runtime_operation_timing']['stroke']['count'],1)

    def test_entirely_clipped_sequence_discards_old_operation_timing(self):
        plan=self.plan([(0,0,19,0)],sequence=True)
        plan['options']['runtime_operation_timing']={'stroke':{'count':100,'total_seconds':50}}
        mouse,_=self.run_plan(plan)
        self.assertFalse(any(a[0]=='press' for a in mouse.actions))
        self.assertNotIn('stroke',plan['options']['runtime_operation_timing'])
        self.assertEqual(self.eta.call_args.kwargs['completed_paths'],0)
        self.sample.assert_not_called()

    def test_dry_run_reports_zero_native_paths(self):
        plan=self.plan([(2,10,17,10)])
        mouse,_=self.run_plan(plan,dry_run=True)
        self.assertFalse(any(a[0] in ('press','click','release') for a in mouse.actions))
        self.assertEqual(plan['options']['runtime_path_counts']['sent'],0)
        self.sample.assert_not_called();self.speed.assert_not_called()

    def test_manual_pause_retains_wall_time_and_analysis_but_excludes_timing_learning(self):
        plan=self.plan([(2,8,17,8),(2,10,17,10)])
        _,events=self.run_plan(plan,pause=True)
        self.assertGreaterEqual(plan['options']['actual_draw_seconds'],123.)
        self.assertEqual(plan['options']['execution_pause_count'],1)
        self.assertGreaterEqual(plan['options']['execution_pause_seconds'],123.)
        self.assertGreaterEqual(self.analysis.call_args.args[1],123.)
        self.speed.assert_not_called();self.sample.assert_not_called()
        self.assertFalse(plan['options']['draw_time_runtime_calibration']['recorded'])
        self.assertIn('paused',plan['options']['draw_time_runtime_calibration']['reason'])
        self.assertEqual([v for k,v in events if k=='draw_time_actual'][-1]['paths'],2)

    def test_unpaused_complete_execution_remains_eligible_and_resets_old_pause_metadata(self):
        plan=self.plan([(2,8,17,8),(2,10,17,10)])
        plan['options'].update(execution_pause_count=3,execution_pause_seconds=600.)
        self.run_plan(plan)
        self.assertEqual(plan['options']['execution_pause_count'],0)
        self.assertEqual(plan['options']['execution_pause_seconds'],0)
        self.sample.assert_called_once();self.speed.assert_called_once()


class PublicLearningTests(unittest.TestCase):
    def test_paused_analysis_preserves_quality_and_wall_time_without_false_eta_advice(self):
        from CompletedDrawingAnalysis import build_completed_drawing_report
        from test_step15_correction_review_recovery_v10139 import trusted_post
        plan=feedback_plan(post=trusted_post(visual_accuracy_percent=95.,actual_coverage_percent=98.))
        plan['options'].update(execution_pause_count=1,execution_pause_seconds=123.,
            runtime_operation_timing={'stroke':{'count':10,'total_seconds':.8}})
        result=build_completed_drawing_report(plan,124.,completed_paths=10)
        self.assertEqual(result['actual_seconds'],124.)
        self.assertEqual(result['execution_pause_seconds'],123.)
        self.assertAlmostEqual(result['operations']['unclassified_seconds'],.2)
        self.assertEqual(result['drawing_accuracy_score_0_100'],95.)
        self.assertIsNone(result['eta_error_seconds']);self.assertIsNone(result['efficiency_score_0_100'])
        codes={row['code'] for row in result['recommendations']}
        self.assertIn('paused_timing',codes)
        self.assertFalse({'eta_model','telemetry_gap','safe_speed_headroom'} & codes)

    def test_paused_feedback_cannot_create_or_change_a_strategy_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'feedback.json'
            plan=feedback_plan()
            self.assertTrue(record_completed_feedback(plan,11,completed_paths=10,path=path)['recorded'])
            before=path.read_bytes()
            for meta in ({'execution_pause_count':1,'execution_pause_seconds':123.},
                         {'execution_pause_count':1,'execution_pause_seconds':0.},
                         {'execution_pause_seconds':.5},
                         {'execution_pause_count':True},{'execution_pause_seconds':float('nan')}):
                with self.subTest(meta=meta):
                    plan=feedback_plan();plan['options'].update(meta)
                    result=record_completed_feedback(plan,130,completed_paths=10,path=path)
                    self.assertFalse(result['recorded'])
                    self.assertFalse(timing_sample_gate(plan['options'],completed_paths=10,planned_paths=10)['allowed'])
                    self.assertEqual(path.read_bytes(),before)

    def test_delivered_edge_categories_have_the_same_strategy_quality_as_interior_paths(self):
        # Use the actual report producer, not invented overlapping counters.
        originals=((0,0),(19,0))
        results=(EdgeBehaviorResult((originals,), 'Hard Clip','hard_clip',2,2),
                 EdgeBehaviorResult((((1,1),(18,1)),), 'Hard Clip','hard_clip',2,2),
                 EdgeBehaviorResult((((1,1),(18,1)),), 'Preserve Outline','preserve_outline_boundary',2,2))
        recorded=[];categories=[]
        with tempfile.TemporaryDirectory() as temporary:
            for i,result in enumerate(results):
                session=RuntimeSafetySession(planned_paths=101)
                for _ in range(100):categories.append(session.note_edge_result(result,originals))
                session.note_edge_result(EdgeBehaviorResult((),'Hard Clip','hard_skip',2,0),originals)
                session.mark_completed()
                plan=feedback_plan();plan['count']=101
                plan['options']['runtime_safety_report']=session.as_dict()
                recorded.append(record_completed_feedback(plan,11,completed_paths=100,
                    path=Path(temporary)/f'feedback-{i}.json'))
        self.assertEqual(set(categories),{'drawn','clipped','edge-follow'})
        self.assertTrue(all(item['accepted'] for item in recorded))
        self.assertEqual(len({item['result_visual_percent'] for item in recorded}),1)
        self.assertTrue(all(item['result_source']=='runtime delivery proxy' for item in recorded))


if __name__=='__main__':unittest.main()
