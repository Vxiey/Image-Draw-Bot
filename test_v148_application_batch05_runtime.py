"""Runtime planning avoids inactive work and revalidates state after a pause."""
from contextlib import ExitStack
import copy
import random
import threading
import unittest
from unittest.mock import patch
from PIL import Image

import DrawBot as app
from DeadlineScheduler import DeadlineScheduler, NORMAL, CATCH_UP, PANIC
from test_drawbot import Mouse, NoWait
from test_visual_verification_v1043 import simple_visual_plan


class NoTailAccess(list):
    def __getitem__(self,index):
        if isinstance(index,slice):raise AssertionError('inactive policy copied the remaining tail')
        return super().__getitem__(index)


class ReplanAllocationTests(unittest.TestCase):
    def test_inactive_and_throttled_replans_never_read_future_paths(self):
        for mode,budget,samples,last_sample in ((NORMAL,60,20,-1),(PANIC,None,20,-1),
                                               (CATCH_UP,60,1,-1),(CATCH_UP,60,8,7)):
            scheduler=DeadlineScheduler([],start_time=0,budget_seconds=budget,clock=lambda:0)
            scheduler.mode=mode;scheduler._last_replan_mode=mode
            scheduler._global_samples=samples;scheduler._last_replan_sample=last_sample
            rows=NoTailAccess([{}]*10000)
            with patch.object(scheduler,'replan_remaining',side_effect=AssertionError('not eligible')):
                for start in (0,1,500,9999,10000):
                    self.assertFalse(scheduler.replan_in_place(rows,start))

    def test_eligible_adapter_preserves_old_ordering_barriers_and_complete_metadata(self):
        rng=random.Random(14805)
        for mode in (CATCH_UP,PANIC):
            for _ in range(20):
                entries=[{'path':((i,0),(i,1)),'color_index':rng.randrange(4),
                          'brush_px':rng.choice((1,3)), 'phase':rng.choice(('structure','accuracy')),
                          'operation_type':rng.choice(('stroke','long_stroke','palette_change')),
                          'importance':rng.random(),'structural_score':rng.random(),
                          'estimated_cost_seconds':rng.random()/10,'optional':False} for i in range(30)]
                actual=DeadlineScheduler(entries,start_time=0,budget_seconds=60,clock=lambda:0)
                expected=DeadlineScheduler(entries,start_time=0,budget_seconds=60,clock=lambda:0)
                actual.mode=expected.mode=mode
                rows=copy.deepcopy(entries);prefix=rows[:4]
                reference=expected.replan_remaining(rows[4:],force=True)
                changed=actual.replan_in_place(rows,4,force=True)
                self.assertEqual(rows,prefix+reference)
                self.assertEqual(changed,reference!=entries[4:])
                self.assertEqual(actual.meta(),expected.meta())
                self.assertEqual(rows[:4],entries[:4])

    def test_preview_inherits_last_brush_across_nonempty_sequence_paths(self):
        from PreviewSafety import build_preview_safety_plan
        sequence=[{'color_index':0,'path':((1,1),),'brush_px':1},
                  {'color_index':0,'path':(),'brush_px':9},
                  {'color_index':0,'path':((3,3),)}]
        safe=build_preview_safety_plan((5,5),(100,100),[[]],None,{'brush_px':5},
                                       execution_sequence=sequence)
        self.assertEqual([entry['brush_px'] for entry in safe.sequence],[1,1])
        self.assertEqual(safe.meta['paths_in'],2)


class PauseMouse(Mouse):
    def __init__(self,paused):
        super().__init__();self.paused=paused;self.pause_sent=False
        self.color='red';self.brush=4;self.drawn=[];self.checked=[]
    def click(self):
        super().click()
        if self.position==(10,10):self.color='red'
        if self.position==(20,10):self.color='green'
        if self.position==(25,10):self.brush=4
    def press(self):
        super().press();self.drawn.append((self.color,self.brush))
    def release(self):
        was_held=self.held;super().release()
        if was_held and not self.pause_sent:
            self.pause_sent=True;self.paused.set()
    def verify_ink_segment(self,*args):self.checked.append(args)


class RuntimePauseTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(app,'log_event'))
        self.stack.enter_context(patch.object(app,'save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
        for target in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                       'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(target,return_value={}))

    def plan(self,sequence=True,brush=False):
        plan=simple_visual_plan();self.addCleanup(plan['image'].close)
        plan['groups']=[[(0,0,1,0)]*3,[]];plan['count']=3
        plan['options'].update(visual_verification_enabled=False,strict_color_verification=True,
                               unlimited_time=True,brush_px=4,canvas_guard_brush_px=4)
        plan['execution_sequence']=([
            {'color_index':0,'path':((0,0),(1,0)),'phase':'major_coverage','brush_px':4,
             'estimated_cost_seconds':.01,'importance':1.,'structural_score':1.} for _ in range(3)
        ] if sequence else [])
        if brush:
            plan['options']['browser_brush_plan']={
                'target_position':(25,10),'target_index':1,'effective_px':4,
                'control_positions':[(15,10),(25,10)],'nominal_sizes':[1,4],
                'verified_sizes':[1,4],'confidence':.95,'safe_guard_px':4,
            }
        return plan

    def execute(self,plan,*,stop_at_resume=False):
        paused=threading.Event();mouse=PauseMouse(paused);stop=NoWait();self.mouse=mouse
        def report(kind,value):
            if kind=='status' and str(value).startswith('Paused'):
                mouse.color='user selected blue';mouse.brush=12;paused.clear()
            if stop_at_resume and kind=='status' and str(value).startswith('Resuming in'):
                stop.stopped=True
        with patch('BrowserBrushSize.verify_brush_selection',return_value=True):
            app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,stop,paused,report,clock=lambda:0)
        return mouse

    def test_sequence_reselects_the_same_color_and_rechecks_ink_after_pause(self):
        mouse=self.execute(self.plan())
        self.assertEqual([color for color,_ in mouse.drawn],['red']*3)
        self.assertEqual(len(mouse.checked),2,'first stroke and first resumed stroke must both be checked')
        self.assertFalse(mouse.held)

    def test_calibrated_brush_is_restored_before_the_first_resumed_stroke(self):
        for sequence in (False,True):
            with self.subTest(sequence=sequence):
                mouse=self.execute(self.plan(sequence=sequence,brush=True))
                self.assertEqual(mouse.drawn,[('red',4)]*3)
                self.assertIn(('move',25,10),mouse.actions)

    def test_stop_during_resume_does_not_restore_controls_or_draw_again(self):
        with self.assertRaises(InterruptedError):self.execute(self.plan(brush=True),stop_at_resume=True)
        self.assertEqual(self.mouse.drawn,[('red',4)])
        self.assertFalse(self.mouse.held)

    def test_actual_unlimited_deadline_sequence_does_not_call_copying_replanner(self):
        plan=self.plan()
        with patch.object(DeadlineScheduler,'replan_remaining',side_effect=AssertionError('unlimited replan')):
            mouse=self.execute(plan)
        self.assertEqual(len(mouse.drawn),3)

    def test_strict_and_adaptive_ink_checks_use_selected_per_entry_brush(self):
        for adaptive in (False,True):
            with self.subTest(adaptive=adaptive):
                plan=self.plan(brush=True)
                plan['execution_sequence']=plan['execution_sequence'][:2]
                plan['execution_sequence'][1]=dict(plan['execution_sequence'][1],color_index=1,brush_px=1)
                plan['groups']=[[(0,0,1,0)],[(0,1,1,1)]];plan['count']=2
                plan['options']['adaptive_color_verification']=adaptive
                mouse=Mouse();widths=[]
                def verify(start,end,rgb,width,*args):
                    widths.append(width)
                    return {'matched':True,'actual':rgb,'confidence':100,'error':0}
                mouse.verify_ink_segment=verify;mouse.inspect_ink_segment=verify
                with patch('BrowserBrushSize.verify_brush_selection',return_value=True):
                    app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,
                                     NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)
                self.assertEqual(widths,[4,1])

    def test_delivery_retry_checks_the_same_current_brush_as_its_first_attempt(self):
        plan=self.plan(brush=True);plan['options']['profile_key']='gartic-phone'
        plan['fitted']=(100,100)
        plan['options']['strict_color_verification']=False
        plan['execution_sequence']=plan['execution_sequence'][:2]
        plan['execution_sequence'][1]=dict(plan['execution_sequence'][1],color_index=1,brush_px=1)
        plan['groups']=[[(0,0,1,0)],[(0,1,1,1)]];plan['count']=2
        replies=[{'checked':True,'matched':True},{'checked':True,'matched':False},
                 {'checked':True,'matched':True}]
        with patch('BrowserBrushSize.verify_brush_selection',return_value=True),\
             patch('StrokeDeliveryVerification.inspect_delivery',side_effect=replies) as verify:
            app.execute_plan(plan,(100,100,100,100),[(10,10),(20,10)],Mouse(),
                             NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)
        self.assertEqual([call.args[4] for call in verify.call_args_list],[4,1,1])

    def clipped_probe_plan(self,sequence=True):
        plan=self.plan(sequence=sequence)
        plan['image'].close();plan['image']=Image.new('RGB',(4,4),'white')
        self.addCleanup(plan['image'].close)
        plan['groups']=[[(0,0,3,0),(1,1,2,1)],[]];plan['count']=2
        plan['execution_sequence']=([
            {'color_index':0,'path':((0,0),(3,0)),'phase':'foundation','brush_px':6},
            {'color_index':0,'path':((1,1),(2,1)),'phase':'foundation','brush_px':6},
        ] if sequence else [])
        plan['options'].update(adaptive_color_verification=True,strict_color_verification=False,
                               brush_px=6,canvas_guard_brush_px=6,edge_behavior='Hard Clip')
        return plan

    def test_clipped_probe_waits_for_real_ink_before_approving_a_color(self):
        for sequence in (False,True):
            for matches in (False,True):
                with self.subTest(sequence=sequence,matches=matches):
                    plan=self.clipped_probe_plan(sequence);mouse=Mouse();checks=[];events=[]
                    def inspect(*args):
                        checks.append(args)
                        return {'matched':matches,'actual':args[2] if matches else (0,0,255),
                                'confidence':100 if matches else 0,'error':0 if matches else 100}
                    mouse.inspect_ink_segment=inspect
                    def execute():
                        app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,
                            NoWait(),threading.Event(),lambda *event:events.append(event),clock=lambda:0)
                    if matches:execute()
                    else:
                        with self.assertRaisesRegex(InterruptedError,'could not be verified'):execute()
                    self.assertEqual(len(checks),1)
                    self.assertEqual(sum(action[0]=='press' for action in mouse.actions),2 if matches else 1)
                    self.assertFalse(mouse.held)
                    cached=plan['options']['color_session_cache']
                    if matches:
                        self.assertEqual(next(iter(cached.values()))['actual'],tuple(plan['colors'][0]))
                    else:self.assertEqual(cached,{})
                    self.assertTrue(any(kind=='color_plan' and value.get('available') is False
                                        for kind,value in events))

    def test_all_clipped_legacy_paths_never_publish_verified_color_evidence(self):
        plan=self.clipped_probe_plan(False);plan['groups'][0]=plan['groups'][0][:1];plan['count']=1
        mouse=Mouse();events=[]
        app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,
            NoWait(),threading.Event(),lambda *event:events.append(event),clock=lambda:0)
        self.assertFalse(any(action[0]=='press' for action in mouse.actions))
        self.assertFalse(any(value.get('matched') for kind,value in events if kind=='color_plan'))
        self.assertEqual(plan['options']['color_session_cache'],{})

    def test_probe_uses_the_guarded_interior_of_a_boundary_spanning_scanline(self):
        plan=self.clipped_probe_plan();plan['image'].close()
        plan['image']=Image.new('RGB',(20,20),'white');self.addCleanup(plan['image'].close)
        plan['groups']=[[(0,7,19,7)],[]];plan['count']=1
        plan['execution_sequence']=[dict(plan['execution_sequence'][0],path=((0,7),(19,7)))]
        mouse=Mouse();checks=[]
        def inspect(*args):
            checks.append(args)
            return {'matched':True,'actual':args[2],'confidence':100,'error':0}
        mouse.inspect_ink_segment=inspect
        app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,
            NoWait(),threading.Event(),lambda *event:None,clock=lambda:0)
        self.assertEqual(len(checks),1)
        start,end=checks[0][:2]
        self.assertGreaterEqual(start[0],105);self.assertLessEqual(end[0],114)
        self.assertEqual(start[1],end[1]);self.assertLessEqual(end[0]-start[0],4)
        self.assertEqual(sum(action[0]=='press' for action in mouse.actions),2)
        self.assertFalse(mouse.held)


if __name__=='__main__':unittest.main()
