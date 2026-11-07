from contextlib import ExitStack
import copy
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot as app
import DetailZoomPass as zoom
import test_visual_verification_v1043 as fixtures
from test_drawbot import NoWait


class DetailSequenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(app, 'save_runtime_safety_report', side_effect=lambda value: value.as_dict()))
        self.stack.enter_context(patch.object(app, 'log_event'))
        for target in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                       'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(target, return_value={}))

    def plan(self, *, brush=1, paths_in_first_batch=2):
        plan = fixtures.simple_visual_plan()
        plan['image'].close()
        plan['image'] = Image.new('RGB', (4, 4), 'white')
        self.addCleanup(plan['image'].close)
        plan['fitted'] = (40, 40)
        base = [[((0, number % 2), (3, number % 2)) for number in range(paths_in_first_batch)],
                [((0, 2), (3, 2))]]
        details = [((1, 3), (2, 3)), ((2, 3),)]
        plan['execution_groups'] = [base[0], base[1] + details]
        plan['groups'] = [[(*path[0], *path[-1]) for path in paths] for paths in plan['execution_groups']]
        plan['execution_sequence'] = zoom._base_color_sequence(base, plan['options'], lambda: False)
        plan['execution_sequence'].extend({'color_index': 1, 'path': path, 'phase': 'details',
            'brush_px': 1, 'detail_zoom': True, 'optional': True, 'operation_type': 'zoom_detail_stroke'}
            for path in details)
        plan['count'] = len(plan['execution_sequence'])
        plan['options'].update(brush_px=brush, max_seconds=100,
                              detail_zoom_meta={'sequence_created_for_detail_pass': True})
        if brush != 1:
            plan['options']['browser_brush_plan'] = {
                'target_position': (25, 10), 'target_index': 1, 'effective_px': brush,
                'control_positions': [(15, 10), (25, 10)], 'nominal_sizes': [1, brush],
                'verified_sizes': [1, brush], 'confidence': .95, 'safe_guard_px': brush,
            }
        return plan

    def snapshots(self, *, bad_first=False, bad_detail=False):
        baseline = Image.new('RGB', (40, 40), 'white')
        red = baseline.copy()
        for y in (5, 15):
            ImageDraw.Draw(red).line((5, y, 35, y), fill=(220, 0, 0), width=4)
        green = red.copy()
        ImageDraw.Draw(green).line((5, 25, 35, 25), fill=(0, 180, 0), width=4)
        detail = green.copy()
        ImageDraw.Draw(detail).line((15, 35, 25, 35), fill=(0, 180, 0), width=1)
        snapshots = [baseline, red, green, detail]
        if bad_first:
            red.paste('white', (0, 0, 40, 40))
        if bad_detail:
            detail.paste(green, (0, 0))
        for snapshot in snapshots:
            self.addCleanup(snapshot.close)
        return snapshots

    def execute(self, plan, snapshots, *, stop=None, dry_run=False, report=None):
        mouse = fixtures.SnapshotMouse(snapshots)
        events, checkpoints = [], []
        def collect(kind, value):
            events.append((kind, value))
            if report is not None:
                report(kind, value)
        self.mouse, self.events, self.checkpoints = mouse, events, checkpoints
        app.execute_plan(plan, (100, 100, 40, 40), [(10, 10), (20, 10)], mouse,
            stop or NoWait(), threading.Event(), collect, dry_run=dry_run,
            checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        return mouse, events, checkpoints

    def test_materialized_base_and_late_details_keep_contiguous_batch_verification(self):
        for brush in (1, 4):
            with self.subTest(brush=brush):
                plan = self.plan(brush=brush)
                compare = app.compare_batch_snapshot
                points = app.planned_batch_points
                with patch.object(app, 'compare_batch_snapshot', wraps=compare) as comparisons, \
                     patch.object(app, 'planned_batch_points', wraps=points) as sampled, \
                     patch('BrowserBrushSize.verify_brush_selection', return_value=True):
                    mouse, events, checkpoints = self.execute(plan, self.snapshots())
                self.assertEqual(mouse.snapshot_calls, 4, 'baseline plus three actual batches')
                self.assertEqual([call.kwargs['brush_px'] for call in comparisons.call_args_list], [brush, brush, 1])
                self.assertEqual([call.args[3] for call in comparisons.call_args_list],
                                 [(220, 0, 0), (0, 180, 0), (0, 180, 0)])
                expected_batches = [plan['execution_sequence'][:2], plan['execution_sequence'][2:3],
                                    plan['execution_sequence'][3:]]
                self.assertEqual([call.args[0] for call in sampled.call_args_list],
                                 [[tuple(entry['path']) for entry in batch] for batch in expected_batches])
                visual = [value for kind, value in events if kind == 'visual_verification']
                self.assertEqual([(item['current'], item['total']) for item in visual], [(0, 3), (1, 3), (2, 3), (3, 3)])
                self.assertTrue(all(item['ok'] for item in visual))
                self.assertEqual(plan['options']['visual_verification_runtime_meta']['passed_batches'], 3)
                self.assertEqual(checkpoints[-1]['sequence_completed_count'], 5)
                self.assertFalse(mouse.held)

    def test_failed_first_batch_stops_before_next_color_and_is_not_checkpointed(self):
        plan = self.plan(paths_in_first_batch=30)
        with self.assertRaisesRegex(InterruptedError, 'Visual verification stopped'):
            self.execute(plan, self.snapshots(bad_first=True))
        self.assertEqual(self.mouse.snapshot_calls, 2)
        self.assertEqual(sum(action[0] == 'click' for action in self.mouse.actions), 1)
        self.assertEqual(self.checkpoints, [], 'the old periodic 25-path checkpoint must not commit unverified work')
        self.assertEqual(plan['options']['visual_verification_runtime_meta']['failed_batches'], 1)
        self.assertFalse(self.mouse.held)

    def test_failed_late_detail_retains_only_verified_base_checkpoints(self):
        plan = self.plan()
        with self.assertRaisesRegex(InterruptedError, 'Visual verification stopped'):
            self.execute(plan, self.snapshots(bad_detail=True))
        self.assertEqual(self.mouse.snapshot_calls, 4)
        self.assertEqual(self.checkpoints[-1]['sequence_completed_count'], 3)
        self.assertEqual(plan['options']['visual_verification_runtime_meta']['passed_batches'], 2)
        self.assertEqual(plan['options']['visual_verification_runtime_meta']['failed_batches'], 1)
        self.assertFalse(self.mouse.held)

    def test_stop_from_batch_report_prevents_the_next_brush_or_palette_command(self):
        plan = self.plan()
        stop = NoWait()
        def report(kind, value):
            if kind == 'visual_verification' and value.get('current') == 1:
                stop.stopped = True
        with self.assertRaises(InterruptedError):
            self.execute(plan, self.snapshots(), stop=stop, report=report)
        self.assertEqual(self.mouse.snapshot_calls, 2)
        self.assertEqual(sum(action[0] == 'click' for action in self.mouse.actions), 1)
        self.assertFalse(self.mouse.held)

    def test_explicit_off_and_dry_run_do_not_add_snapshot_or_input_work(self):
        for dry_run in (False, True):
            plan = self.plan()
            if not dry_run:
                plan['options']['visual_verification_resolved'] = 'Off'
            mouse, _, _ = self.execute(plan, self.snapshots(), dry_run=dry_run)
            self.assertEqual(mouse.snapshot_calls, 0)
            if dry_run:
                self.assertFalse(any(action[0] in ('click', 'press', 'release') for action in mouse.actions))

    def test_existing_progressive_sequence_without_the_zoom_conversion_keeps_its_policy(self):
        plan = self.plan()
        plan['options'].pop('detail_zoom_meta')
        mouse, events, checkpoints = self.execute(plan, self.snapshots())
        self.assertEqual(mouse.snapshot_calls, 0)
        visual = [value for kind, value in events if kind == 'visual_verification']
        self.assertEqual(len(visual), 1)
        self.assertEqual(visual[0]['summary'], 'skipped for progressive passes')
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 5)


if __name__ == '__main__':
    unittest.main()
