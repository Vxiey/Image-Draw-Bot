"""Resume presentation follows verified work without changing native counters."""
from collections import Counter
from contextlib import ExitStack
import threading
import unittest
from unittest.mock import patch

from DrawBot import execute_plan
from RenderResume import checkpoint_after_batch, checkpoint_before_path, checkpoint_sequence_progress, sequence_entry_key
from test_drawbot import Mouse
from test_visual_verification_v1043 import simple_visual_plan
from test_v148_application_batch06_learning import Clock, AdvancingWait


class ResumeProgressTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
        for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(name, return_value={}))

    def plan(self, *, sequence=False, repeated=False):
        plan = simple_visual_plan()
        self.addCleanup(plan['image'].close)
        paths = [[((0, 0), (1, 0))] * 4, [((0, 1), (1, 1))] * 4]
        plan.update(groups=[[(*path[0], *path[-1]) for path in group] for group in paths],
                    execution_groups=paths, count=8, estimate=12.,
                    path_stats={'stroke_optimizer_effective': 'Nearest'})
        if sequence:
            plan['execution_sequence'] = [dict(color_index=index, path=path, brush_px=1)
                                          for index, group in enumerate(paths) for path in group]
        plan['options'].update(delay=.3, speed='Safe', color_order=[0, 1, 0] if repeated else [0, 1],
                               unlimited_time=True, visual_verification_enabled=False, test_run=True,
                               brush_px=1, human_mode='Off')
        return plan

    def execute(self, plan, *, stop_on_initial_progress=False):
        clock = Clock()
        stop = AdvancingWait(clock)
        events = []
        mouse = Mouse()
        def report(kind, value):
            events.append((kind, value))
            if kind == 'progress' and stop_on_initial_progress:
                stop.stopped = True
        if stop_on_initial_progress:
            with self.assertRaises(InterruptedError):
                execute_plan(plan, (100, 100, 20, 20), [(10, 10), (20, 10)], mouse,
                             stop, threading.Event(), report, clock=clock)
        else:
            execute_plan(plan, (100, 100, 20, 20), [(10, 10), (20, 10)], mouse,
                         stop, threading.Event(), report, clock=clock)
        self.assertFalse(mouse.held)
        return mouse, events

    def assert_counters(self, plan, mouse, events, sent, total):
        self.assertEqual(sum(action[0] == 'press' for action in mouse.actions), sent)
        self.assertEqual(plan['options']['runtime_path_counts']['processed'], sent)
        self.assertEqual(plan['options']['runtime_path_counts']['sent'], sent)
        self.assertEqual([value for kind, value in events if kind == 'progress'][-1], (total, total))
        completed = [value for kind, value in events if kind == 'draw_timer'][-1]
        self.assertEqual(completed['state'], 'completed')
        self.assertEqual((completed['done'], completed['total']), (total, total))
        self.assertEqual((completed['session_done'], completed['session_total']), (sent, sent))
        actual = [value for kind, value in events if kind == 'draw_time_actual'][-1]
        self.assertEqual(actual['processed_paths'], sent)
        self.assertEqual(plan['count'], 8, 'presentation must not rewrite the saved plan or learning counters')

    def test_batch_resume_starts_at_verified_work_and_estimates_only_remaining_paths(self):
        plan = self.plan()
        plan['options']['render_resume_state'] = checkpoint_after_batch(plan, 1)
        mouse, events = self.execute(plan)
        self.assert_counters(plan, mouse, events, 4, 8)
        self.assertEqual([value for kind, value in events if kind == 'progress'][0], (4, 8))
        timers = [value for kind, value in events if kind == 'draw_timer']
        self.assertEqual(timers[0]['remaining_seconds'], 6.)
        self.assertEqual(timers[0]['resumed_paths'], 4)
        self.assertLess(next(value for value in reversed(timers) if value['state'] == 'running')['remaining_seconds'], 3.)
        self.assertAlmostEqual(plan['options']['actual_draw_seconds'], 4.74)

    def test_path_resume_only_counts_a_verified_ordered_prefix(self):
        for valid_order in (True, False):
            with self.subTest(valid_order=valid_order):
                plan = self.plan()
                paths = plan['execution_groups'][1]
                state = checkpoint_before_path(plan, 2, 2, len(paths), ordered_items=paths)
                if not valid_order:
                    state['active_items_fingerprint'] = '0' * 64
                plan['options']['render_resume_state'] = state
                mouse, events = self.execute(plan)
                self.assert_counters(plan, mouse, events, 2 if valid_order else 4, 8)
                progress = [value for kind, value in events if kind == 'progress']
                self.assertEqual(progress[0], (4, 8))
                self.assertEqual((6, 8) in progress, valid_order)
                timers = [value for kind, value in events if kind == 'draw_timer']
                self.assertEqual(timers[-1]['resumed_paths'], 6 if valid_order else 4)

    def test_sequence_resume_uses_verified_operations_and_new_session_counts(self):
        plan = self.plan(sequence=True)
        entries = plan['execution_sequence']
        plan['options']['render_resume_state'] = checkpoint_sequence_progress(
            plan, Counter(sequence_entry_key(entry) for entry in entries[:6]))
        mouse, events = self.execute(plan)
        self.assert_counters(plan, mouse, events, 2, 8)
        self.assertEqual([value for kind, value in events if kind == 'progress'][0], (6, 8))
        self.assertEqual([value for kind, value in events if kind == 'draw_timer'][0]['remaining_seconds'], 3.)

    def test_repeated_batches_count_each_real_visit_in_both_fresh_and_resumed_runs(self):
        for resumed in (False, True):
            with self.subTest(resumed=resumed):
                plan = self.plan(repeated=True)
                if resumed:
                    plan['options']['render_resume_state'] = checkpoint_after_batch(plan, 2)
                mouse, events = self.execute(plan)
                self.assert_counters(plan, mouse, events, 4 if resumed else 12, 12)
                if resumed:
                    self.assertEqual([value for kind, value in events if kind == 'progress'][0], (8, 12))

    def test_complete_sequence_publishes_completion_without_new_input_or_timing(self):
        plan = self.plan(sequence=True)
        plan['options']['render_resume_state'] = checkpoint_sequence_progress(
            plan, Counter(sequence_entry_key(entry) for entry in plan['execution_sequence']))
        mouse, events = self.execute(plan)
        self.assertEqual(mouse.actions, [('release',)])
        self.assertEqual([value for kind, value in events if kind == 'progress'], [(8, 8)])
        self.assertFalse(any(kind in ('draw_timer', 'draw_time_actual') for kind, value in events))
        self.assertNotIn('actual_draw_seconds', plan['options'])

    def test_stop_from_initial_resume_progress_precedes_any_target_input(self):
        plan = self.plan()
        plan['options']['render_resume_state'] = checkpoint_after_batch(plan, 1)
        mouse, events = self.execute(plan, stop_on_initial_progress=True)
        self.assertEqual(mouse.actions, [('release',)])
        self.assertFalse(any(kind == 'draw_time_actual' for kind, value in events))


if __name__ == '__main__':
    unittest.main()
