from collections import Counter
from contextlib import ExitStack
import copy
import json
import threading
import unittest
from unittest.mock import Mock, patch

import DrawBot as app
from RenderResume import checkpoint_sequence_progress, resolve_resume, sequence_entry_key
from test_drawbot import NoWait
from test_visual_verification_v1043 import SnapshotMouse, simple_visual_plan


class SequenceResumeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(app, 'log_event'))
        self.stack.enter_context(patch.object(app, 'save_runtime_safety_report', side_effect=lambda value: value.as_dict()))
        self.recorders = [self.stack.enter_context(patch(target, return_value={})) for target in (
            'RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
            'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
            'CorrectionHistory.record_correction_history')]
        self.score = self.stack.enter_context(patch('SafeCanvasSnapshotScoring.score_final_canvas_snapshot',
                                                  return_value={'available': False, 'feedback_trust': 'none'}))
        self.correction = self.stack.enter_context(patch('PostDrawCorrectionPass.build_post_draw_correction_plan',
                                                       return_value={'enabled': False, 'safe': True}))

    def plan(self):
        plan = simple_visual_plan()
        self.addCleanup(plan['image'].close)
        # Duplicate operations prove that completion tracks occurrences, not
        # only a set of path hashes. Legacy groups deliberately remain present.
        red = {'color_index': 0, 'path': ((0, 0), (1, 0)), 'phase': 'base', 'brush_px': 2}
        green = {'color_index': 1, 'path': ((0, 1), (1, 1)), 'phase': 'details', 'brush_px': 2}
        plan['execution_sequence'] = [red, dict(red), green]
        plan['groups'][0].append(plan['groups'][0][0])
        plan['count'] = 3
        plan['options'].update(visual_verification_enabled=False, max_seconds=100,
                              _accuracy_original_source=plan['image'])
        return plan

    def execute(self, plan, *, stop=None):
        mouse = SnapshotMouse([])
        for name in ('configure_precision', 'configure_drag_backend', 'prepare_target', 'verify_palette_layout'):
            setattr(mouse, name, Mock())
        checkpoints, events = [], []
        self.mouse = mouse
        app.execute_plan(plan, (100, 100, 20, 20), [(10, 10), (20, 10)], mouse,
                         stop or NoWait(), threading.Event(), lambda *event: events.append(event),
                         checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        return mouse, checkpoints, events

    def test_actual_completed_checkpoint_is_no_input_no_correction_and_no_learning(self):
        plan = self.plan()
        first_mouse, checkpoints, _ = self.execute(plan)
        self.assertEqual(sum(action[0] == 'press' for action in first_mouse.actions), 3)
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 3)
        self.correction.assert_called_once()
        # Round-trip the genuine execution checkpoint as persisted JSON.
        state = json.loads(json.dumps(checkpoints[-1]))
        plan['options']['render_resume_state'] = state
        resolved = resolve_resume(plan, state)
        self.assertTrue(resolved['compatible'])
        self.assertEqual(resolved['sequence_remaining_count'], 0)
        self.score.reset_mock()
        self.correction.reset_mock()
        for recorder in self.recorders:
            recorder.reset_mock()

        mouse, new_checkpoints, events = self.execute(plan)
        self.assertEqual(mouse.actions, [('release',)], 'cleanup remains mandatory; no move/click/press is repeated')
        for name in ('configure_precision', 'configure_drag_backend', 'prepare_target', 'verify_palette_layout'):
            getattr(mouse, name).assert_not_called()
        self.assertEqual(mouse.snapshot_calls, 0)
        self.assertEqual(new_checkpoints, [])
        self.assertEqual(plan['options']['render_resume_state'], state)
        self.score.assert_not_called()
        self.correction.assert_not_called()
        for recorder in self.recorders:
            recorder.assert_not_called()
        self.assertIn('already complete', events[-1][1])
        self.assertFalse(mouse.held)

    def test_partial_sequence_resume_sends_only_the_remaining_operation(self):
        plan = self.plan()
        completed = plan['execution_sequence'][:2]
        state = checkpoint_sequence_progress(plan, Counter(map(sequence_entry_key, completed)), last_entry=completed[-1])
        plan['options']['render_resume_state'] = json.loads(json.dumps(state))
        self.assertEqual(resolve_resume(plan, state)['sequence_remaining_count'], 1)

        mouse, checkpoints, events = self.execute(plan)
        self.assertEqual(sum(action[0] == 'press' for action in mouse.actions), 1)
        self.assertEqual(sum(action[0] == 'click' for action in mouse.actions), 1)
        self.assertIn(('move', 20, 10), mouse.actions)
        self.assertNotIn(('move', 10, 10), mouse.actions)
        mouse.prepare_target.assert_called_once()
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 3)
        self.correction.assert_called_once()
        self.assertEqual([value['paths'] for kind, value in events if kind == 'draw_time_actual'], [1])
        self.assertFalse(mouse.held)

    def test_stop_on_completed_resume_is_still_honored_and_releases_input(self):
        plan = self.plan()
        state = checkpoint_sequence_progress(plan, Counter(map(sequence_entry_key, plan['execution_sequence'])))
        plan['options']['render_resume_state'] = state
        stop = NoWait()
        stop.stopped = True
        with self.assertRaises(InterruptedError):
            self.execute(plan, stop=stop)
        self.assertEqual(self.mouse.actions, [('release',)])
        self.mouse.prepare_target.assert_not_called()
        self.correction.assert_not_called()


if __name__ == '__main__':
    unittest.main()
