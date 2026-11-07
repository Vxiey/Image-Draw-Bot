"""The actual drawing loop publishes live time, including inside long strokes."""
from contextlib import ExitStack
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from DrawBot import DrawBotApp, execute_plan
from test_drawbot import Mouse
from test_visual_verification_v1043 import simple_visual_plan
from test_v148_application_batch04_settings import Value
from test_v148_application_batch06_learning import Clock, AdvancingWait


class LiveDrawingTimerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda s: s.as_dict()))
        for target in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                       'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(target, return_value={}))

    def run_plan(self, *, pause=False, dry_run=False, stop_from_timer=False,
                 expire_from_timer=False, direct_tick=None):
        plan = simple_visual_plan()
        self.addCleanup(plan['image'].close)
        plan['groups'] = [[(0, 0, 1, 0)] * 8, []]
        plan['count'] = 8
        plan['estimate'] = 12.
        plan['options'].update(delay=.3, speed='Safe', color_order=[0],
                               unlimited_time=not expire_from_timer, max_seconds=100,
                               visual_verification_enabled=False, test_run=True)
        clock = Clock()
        stop = AdvancingWait(clock)
        paused = threading.Event()
        mouse = Mouse()
        events = []
        timers = []
        stopped_actions = []
        if pause:
            release = mouse.release
            def pause_once():
                held = mouse.held
                release()
                if held and not getattr(mouse, 'pause_sent', False):
                    mouse.pause_sent = True
                    paused.set()
            mouse.release = pause_once
        def report(kind, value):
            events.append((kind, value))
            if kind == 'status' and str(value).startswith('Paused'):
                clock.now += 120.
                paused.clear()
            if direct_tick == 'post-path' and kind == 'progress' and value[0] == plan['count']:
                # Make the direct final post-path call due after the last wait.
                # This represents time spent reporting/verifying that stroke.
                clock.now += .6
            if kind == 'draw_timer':
                timers.append((dict(value), mouse.held))
                due = (value['elapsed_seconds'] == 0. if direct_tick == 'initial' else
                       value['done'] == plan['count'] if direct_tick == 'post-path' else
                       value['elapsed_seconds'] > .5)
                if value['state'] == 'running' and due:
                    if stop_from_timer:
                        stop.stopped = True
                        stopped_actions[:] = mouse.actions
                    if expire_from_timer:
                        clock.now = 101.
                        stopped_actions[:] = mouse.actions
        if stop_from_timer or expire_from_timer:
            with self.assertRaises(InterruptedError):
                execute_plan(plan, (100, 100, 20, 20), [(10, 10), (20, 10)],
                             mouse, stop, paused, report, clock=clock)
        else:
            execute_plan(plan, (100, 100, 20, 20), [(10, 10), (20, 10)],
                         mouse, stop, paused, report, clock=clock, dry_run=dry_run)
        self.assertFalse(mouse.held)
        return plan, timers, mouse, stopped_actions

    def test_ordinary_strokes_update_before_completion_and_while_mouse_is_held(self):
        plan, timers, mouse, _ = self.run_plan()
        running = [(row, held) for row, held in timers if row['state'] == 'running' and row['elapsed_seconds'] > 0]
        self.assertGreater(len(running), 2)
        self.assertTrue(any(held and row['done'] == 0 for row, held in running))
        ticks = [row['elapsed_seconds'] for row, _ in timers[:-1]]
        self.assertTrue(all(right - left >= .5 - 1e-9 for left, right in zip(ticks, ticks[1:])))
        self.assertEqual(timers[-1][0]['state'], 'completed')
        self.assertEqual(timers[-1][0]['remaining_seconds'], 0)
        self.assertAlmostEqual(timers[-1][0]['elapsed_seconds'], plan['options']['actual_draw_seconds'], places=4)
        self.assertEqual(sum(action[0] == 'press' for action in mouse.actions), 8)

    def test_pause_keeps_wall_clock_elapsed_without_teaching_idle_as_slow_throughput(self):
        plain, plain_timers, _, _ = self.run_plan()
        paused, paused_timers, _, _ = self.run_plan(pause=True)
        wall_delta=paused['options']['actual_draw_seconds'] - plain['options']['actual_draw_seconds']
        self.assertGreaterEqual(wall_delta, 123.)
        self.assertLess(wall_delta, 128., 'resume also legitimately reselects and verifies the drawing tool')
        paused_rows = [row for row, _ in paused_timers if row['state'] == 'paused']
        self.assertTrue(paused_rows)
        self.assertGreater(min(row['elapsed_seconds'] for row in paused_rows), 120.)
        self.assertEqual(len({round(row['remaining_seconds'], 8) for row in paused_rows}), 1)
        resumed = [row for row, _ in paused_timers if row['state'] == 'running' and row['paused_seconds'] >= 123.]
        self.assertTrue(resumed)
        self.assertLess(max(row['remaining_seconds'] for row in resumed), 30.,
                        'a two-minute pause must not inflate a short remaining drawing into minutes')
        self.assertAlmostEqual(paused_timers[-1][0]['active_elapsed_seconds']-
                               plain_timers[-1][0]['active_elapsed_seconds'], wall_delta-123., places=4)
        self.assertAlmostEqual(paused_timers[-1][0]['paused_seconds'], 123.)

    def test_timer_callback_cannot_bypass_stop_or_the_hard_wall_clock_deadline(self):
        for argument in ('stop_from_timer', 'expire_from_timer'):
            with self.subTest(argument=argument):
                _, timers, mouse, stopped_actions = self.run_plan(**{argument: True})
                self.assertTrue(stopped_actions)
                self.assertTrue(all(action[0] == 'release' for action in mouse.actions[len(stopped_actions):]))
                self.assertFalse(any(row['state'] == 'completed' for row, _ in timers))

    def test_direct_initial_and_final_stroke_ticks_recheck_stop_and_deadline(self):
        for direct_tick in ('initial', 'post-path'):
            for argument in ('stop_from_timer', 'expire_from_timer'):
                with self.subTest(tick=direct_tick, argument=argument):
                    plan, timers, mouse, stopped_actions = self.run_plan(
                        direct_tick=direct_tick, **{argument: True})
                    self.assertTrue(timers)
                    final_running = timers[-1][0]
                    self.assertEqual(final_running['state'], 'running')
                    self.assertEqual(final_running['done'], 0 if direct_tick == 'initial' else plan['count'])
                    self.assertTrue(all(action[0] == 'release' for action in mouse.actions[len(stopped_actions):]))
                    self.assertNotIn('actual_draw_seconds', plan['options'])
                    self.assertFalse(any(row['state'] == 'completed' for row, _ in timers))

    def test_dry_run_does_not_publish_a_real_drawing_timer(self):
        _, timers, mouse, _ = self.run_plan(dry_run=True)
        self.assertFalse(timers)
        self.assertFalse(any(action[0] in ('press', 'click', 'release') for action in mouse.actions))

    def test_ui_reports_pause_and_ignores_late_running_ticks_after_stop(self):
        app = SimpleNamespace(stop=threading.Event(), draw_live_time_text=Value(''),
                              total_draw_time_text=Value(''))
        row = dict(state='paused', elapsed_seconds=125., remaining_seconds=3., predicted_total_seconds=128.)
        DrawBotApp._handle_event(app, 'draw_timer', row)
        self.assertIn('paused', app.draw_live_time_text.get())
        self.assertEqual(app.total_draw_time_text.get(), 'Total draw time: paused…')
        app.stop.set()
        before = app.draw_live_time_text.get()
        DrawBotApp._handle_event(app, 'draw_timer', dict(row, state='running'))
        self.assertEqual(app.draw_live_time_text.get(), before)
        DrawBotApp._handle_event(app, 'draw_timer', dict(row, state='completed'))
        self.assertIn('complete', app.draw_live_time_text.get())


if __name__ == '__main__':
    unittest.main()
