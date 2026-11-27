"""A correction-only retry preserves the canvas and uses fresh attempt evidence."""
from contextlib import ExitStack
import copy
import threading
import unittest
from unittest.mock import patch

import DrawBot as app
from CorrectionReviewRecovery import build_correction_retry_plan
from test_drawbot import NoWait
from test_step15_correction_review_recovery_v10139 import trusted_post
from test_visual_verification_v1043 import simple_visual_plan, SnapshotMouse


class CorrectionRetryTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(app,'log_event'))
        self.stack.enter_context(patch.object(app,'save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
        for target in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                       'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(target,return_value={}))
        self.fresh=trusted_post(visual_accuracy_percent=80,actual_coverage_percent=97)
        self.score=self.stack.enter_context(patch('SafeCanvasSnapshotScoring.score_final_canvas_snapshot',return_value=self.fresh))
        self.correction=self.stack.enter_context(patch('PostDrawCorrectionPass.build_post_draw_correction_plan',
            return_value={'enabled':False,'safe':True,'reason':'fixture does not request patch input'}))

    def base(self):
        plan=simple_visual_plan();self.addCleanup(plan['image'].close)
        plan['count']=6000;plan['estimate']=60.;plan['draw_time_estimate']={'projected_seconds':60.}
        plan['options'].update(
            unlimited_time=True,visual_verification_enabled=False,_accuracy_original_source=plan['image'],
            background_fill_plan={'enabled':True,'color_index':0,'seed_pixel':(0,0)},
            fill_tool_actions=[('fill',(30,10))],fill_restore_actions=[('tool',(40,10))],
            fill_regions=[{'color_index':0,'bbox':(0,0,1,1),'seed_pixel':(0,0)}],
            post_draw_before_correction_accuracy_meta={'visual_accuracy_percent':12},
            post_draw_accuracy_meta=trusted_post(visual_accuracy_percent=60),
            post_draw_correction_meta={'enabled':True,'executed_paths':5},
        )
        return plan

    def execute(self,plan,mouse=None):
        mouse=SnapshotMouse([]) if mouse is None else mouse
        app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,
                         NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)
        return mouse

    def test_retry_never_replays_background_or_region_fill_before_fresh_scoring(self):
        base=self.base();original_options=dict(base['options']);retry=build_correction_retry_plan(base)
        with patch.object(app,'filter_fill_regions_by_runtime_mask',side_effect=AssertionError('fill replay')):
            mouse=self.execute(retry)
        self.assertEqual(mouse.actions,[('release',)])
        self.assertEqual(mouse.snapshot_calls,2,'fresh result score followed by correction analysis')
        self.assertEqual(base['options'],original_options)
        self.assertIs(retry['options']['background_fill_plan'],base['options']['background_fill_plan'])
        self.assertIs(retry['options']['fill_regions'],base['options']['fill_regions'])
        self.correction.assert_called_once()

    def test_retry_path_cost_uses_completed_plan_count_before_groups_are_emptied(self):
        retry=build_correction_retry_plan(self.base())
        self.assertEqual(retry['count'],0)
        self.execute(retry)
        self.assertEqual(self.correction.call_args.kwargs['estimated_seconds_per_path'],.01)

    def test_unlimited_retry_with_explicit_budget_uses_valid_evidence_and_local_verification(self):
        retry = build_correction_retry_plan(self.base())
        retry['options'].update(post_draw_correction_budget_seconds=10,
                                post_draw_correction_verified_colors=(0,1))
        self.execute(retry)
        request = self.correction.call_args.kwargs
        self.assertIsNone(request['usable_deadline_seconds'])
        self.assertIsNone(request['elapsed_seconds'])
        self.assertEqual(request['options']['post_draw_correction_budget_seconds'], 10)
        self.assertEqual(request['options']['post_draw_correction_verified_colors'], ())

    def test_disabled_retry_never_starts_target_preflight_capture_or_input(self):
        retry = build_correction_retry_plan(self.base())
        retry['options']['post_draw_correction_budget_seconds'] = 0
        mouse = self.execute(retry)
        self.assertEqual(mouse.snapshot_calls, 0)
        self.assertEqual(mouse.actions, [])
        self.score.assert_not_called()
        self.correction.assert_not_called()

    def test_correction_budget_expiring_in_native_move_cannot_click_or_start_next_color(self):
        retry = build_correction_retry_plan(self.base())
        retry['options']['post_draw_correction_budget_seconds'] = 5
        self.correction.return_value = {'enabled': True, 'safe': True,
            'execution_groups': [[((0,0),(1,0))], [((1,1),(1,2))]], 'color_order': [0,1],
            'correction_paths': 2, 'selected_correction_pixels': 4}
        now = [0.0]
        mouse = SnapshotMouse([])
        def slow_palette_move(x, y):
            mouse.actions.append(('move', x, y))
            now[0] += 5
        mouse.move = slow_palette_move
        app.execute_plan(retry, (100,100,20,20), [(10,10),(20,10)], mouse,
                         NoWait(), threading.Event(), lambda *args: None, clock=lambda: now[0])
        result = retry['options']['post_draw_correction_meta']
        self.assertTrue(result['stopped_early'])
        self.assertEqual(result['execution_seconds'], 5)
        self.assertEqual(result['executed_paths'], 0)
        self.assertEqual(mouse.actions, [('move', 10, 10), ('release',)])

    def test_expired_budget_releases_partial_stroke_and_does_not_relocate_edge_paths(self):
        retry = build_correction_retry_plan(self.base())
        retry['options'].update(post_draw_correction_budget_seconds=10, edge_behavior='Adaptive Clip')
        self.correction.return_value = {'enabled': True, 'safe': True,
            'execution_groups': [[((0,0),(1,0)), ((0,1),(1,1))], []], 'color_order': [0],
            'correction_paths': 2, 'selected_correction_pixels': 4}
        now = [0.0]
        mouse = SnapshotMouse([])
        press = mouse.press
        def slow_press():
            press()
            now[0] = 10.0
        mouse.press = slow_press
        with patch.object(app, 'apply_edge_behavior', wraps=app.apply_edge_behavior) as edges:
            app.execute_plan(retry, (100,100,20,20), [(10,10),(20,10)], mouse,
                             NoWait(), threading.Event(), lambda *args: None, clock=lambda: now[0])
        self.assertTrue(retry['options']['post_draw_correction_meta']['stopped_early'])
        self.assertEqual(sum(action[0] == 'press' for action in mouse.actions), 1)
        self.assertFalse(mouse.held)
        self.assertEqual({call.kwargs['behavior'] for call in edges.call_args_list}, {'Hard Clip'})

    def test_each_retry_records_its_own_fresh_before_result(self):
        base=self.base();retry=build_correction_retry_plan(base)
        self.execute(retry)
        self.assertEqual(retry['options']['post_draw_before_correction_accuracy_meta']['visual_accuracy_percent'],80)
        self.assertEqual(base['options']['post_draw_before_correction_accuracy_meta']['visual_accuracy_percent'],12)
        self.assertEqual(base['options']['post_draw_accuracy_meta']['visual_accuracy_percent'],60)
        self.assertEqual(self.correction.call_args.kwargs['post_draw_meta']['visual_accuracy_percent'],80)
        from CorrectionHistory import build_history_entry
        history=build_history_entry(retry,actual_seconds=1,created_at=1)
        self.assertEqual(history['delta']['visual_accuracy_delta'],0,
                         'a skipped retry must not claim the original drawing improved by 68 points')

    def test_failed_fresh_capture_cannot_reuse_previous_verified_result(self):
        retry=build_correction_retry_plan(self.base())
        self.score.return_value=None
        # A missing metric mapping is contained by capture_post_draw_accuracy;
        # the replacement metadata must remain explicitly unavailable.
        self.execute(retry)
        evidence=self.correction.call_args.kwargs['post_draw_meta']
        self.assertFalse(evidence['available'])
        self.assertNotIn('visual_accuracy_percent',evidence)

    def test_retry_counters_start_fresh_and_cannot_mutate_completed_plan(self):
        base=self.base()
        prior={'stroke_delivery_verification_meta':{'checked':40,'failed':2},
               'edge_behavior_meta':{'hard_clip':20},
               'visual_verification_runtime_meta':{'batches':6},
               'adaptive_brush_runtime_meta':{'switches':8,'sizes':[1,4]}}
        base['options'].update(copy.deepcopy(prior))
        retry=build_correction_retry_plan(base);self.execute(retry)
        for key,value in prior.items():self.assertEqual(base['options'][key],value)
        self.assertEqual(retry['options']['stroke_delivery_verification_meta']['checked'],0)
        self.assertEqual(retry['options']['edge_behavior_meta']['hard_clip'],0)
        self.assertNotIn('visual_verification_runtime_meta',retry['options'])
        self.assertNotIn('adaptive_brush_runtime_meta',retry['options'])

    def test_fill_only_original_has_no_fabricated_per_path_cost(self):
        base=self.base();base['count']=0
        retry=build_correction_retry_plan(base);self.execute(retry)
        self.assertIsNone(self.correction.call_args.kwargs['estimated_seconds_per_path'])

    def test_correction_uses_each_colors_own_selector_and_prices_the_actual_plan(self):
        from test_paint_color_recovery_v10124 import Keyboard

        for order in ([0, 1], [1, 0]):
            with self.subTest(order=order):
                retry = build_correction_retry_plan(self.base())
                selectors = (retry['color_selectors'][0], {
                    'kind':'custom', 'rgb':(0,180,0), 'prefer_numeric':True, 'require_exact':True})
                retry['color_selectors'] = selectors
                retry['options'].update(
                    profile_name='Microsoft Paint', color_selectors=(),
                    exact_color_actions={'OpenCustomColor':(1,1), 'ConfirmColor':(2,2),
                                         'RedField':(3,3), 'GreenField':(4,4), 'BlueField':(5,5)})
                self.correction.return_value = {'enabled':True, 'safe':True, 'correction_paths':2,
                    'execution_groups':[[((0,0),(1,0))], [((0,1),(1,1))]], 'color_order':order}
                mouse = SnapshotMouse([])
                mouse.calibrated_modal_click = lambda point: mouse.actions.append(('modal', *point))
                keyboard = Keyboard()
                app.execute_plan(retry, (100,100,20,20), [(10,10),(20,10)], mouse,
                                 NoWait(), threading.Event(), lambda *args: None,
                                 clock=lambda: 0, keyboard=keyboard)
                self.assertEqual([value for kind, value in keyboard.actions if kind == 'write'],
                                 ['0', '180', '0'])
                self.assertEqual(mouse.actions.count(('modal', 2, 2)), 1)
                self.assertEqual(mouse.actions.count(('move', 10, 10)), 1)
                self.assertEqual(retry['options']['post_draw_correction_meta']['executed_paths'], 2)
                self.assertEqual(self.correction.call_args.kwargs['options']['color_selectors'], selectors)

    def test_enabled_retry_verifies_fresh_color_before_painting_corrections(self):
        for adaptive in (False,True):
            for matches in (False,True):
                with self.subTest(adaptive=adaptive,matches=matches):
                    retry=build_correction_retry_plan(self.base())
                    retry['options'].update(adaptive_color_verification=adaptive,
                                            strict_color_verification=not adaptive)
                    self.correction.return_value={'enabled':True,'safe':True,
                        'execution_groups':[[((0,0),(1,0))],[]], 'color_order':[0],
                        'correction_paths':1,'selected_correction_pixels':2}
                    mouse=SnapshotMouse([]);checks=[]
                    def inspect(*args):
                        checks.append(args)
                        return {'matched':matches,'actual':args[2] if matches else (0,0,255),
                                'confidence':100 if matches else 0,'error':0 if matches else 100}
                    def strict(*args):
                        checks.append(args)
                        if not matches:raise InterruptedError('wrong rendered ink')
                    mouse.inspect_ink_segment=inspect;mouse.verify_ink_segment=strict
                    if matches:
                        self.execute(retry,mouse)
                        self.assertEqual(retry['options']['post_draw_correction_meta']['executed_paths'],1)
                    else:
                        with self.assertRaises(InterruptedError):self.execute(retry,mouse)
                    self.assertEqual(len(checks),1)
                    self.assertEqual(sum(action[0]=='press' for action in mouse.actions),
                                     2 if adaptive and matches else 1)
                    self.assertFalse(mouse.held)

    def test_ordinary_full_drawing_keeps_its_background_fill_prelude(self):
        plan=self.base();plan['count']=2;plan['options']['fill_regions']=[]
        mouse=self.execute(plan)
        self.assertIn(('move',30,10),mouse.actions)
        self.assertGreaterEqual(sum(item[0]=='click' for item in mouse.actions),3)


if __name__=='__main__':unittest.main()
