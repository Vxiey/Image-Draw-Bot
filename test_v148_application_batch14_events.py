"""Display backlogs stay bounded while actual worker results keep FIFO order."""
from contextlib import ExitStack
import queue
import threading
import unittest
from unittest.mock import patch

from DrawBot import DrawBotApp, execute_plan
from WorkerEventQueue import WorkerEventQueue
from test_drawbot import Mouse, NoWait
from test_visual_verification_v1043 import simple_visual_plan
from test_v148_application_batch04_recovery import app_state
from test_v148_application_batch04_settings import Value


def drain(events):
    result = []
    while True:
        try:
            result.append(events.get_nowait())
        except queue.Empty:
            return result
        events.task_done()


class DisplayQueueTests(unittest.TestCase):
    def test_long_mixed_display_stream_keeps_only_latest_values_in_actual_order(self):
        events = WorkerEventQueue()
        for number in range(10000):
            events.put(('status', str(number)))
            events.put(('progress', (number, 10000)))
            events.put(('draw_timer', {'elapsed_seconds': number}))
            events.put(('deadline_telemetry', {'mode': str(number)}))
            events.put(('update_progress', str(number)))
        events.put(('status', 'newest'))
        self.assertEqual(events.qsize(), 5)
        self.assertEqual(drain(events), [
            ('progress', (9999, 10000)),
            ('draw_timer', {'elapsed_seconds': 9999}),
            ('deadline_telemetry', {'mode': '9999'}),
            ('update_progress', '9999'),
            ('status', 'newest'),
        ])
        self.assertEqual(events.unfinished_tasks, 0)
        events.join()

    def test_results_commands_errors_and_completion_form_lossless_barriers(self):
        events = WorkerEventQueue()
        payload = object()
        barriers = [('planned', payload), ('quick_start', None), ('toggle_pause', None),
                    ('terminal_status', ('draw', 'failure')),
                    ('render_checkpoint', payload), ('done', 'draw')]
        expected = []
        for number, barrier in enumerate(barriers):
            events.put(('progress', (0, 5)))
            events.put(('status', 'older'))
            events.put(('progress', (number, 5)))
            events.put(barrier)
            expected.extend([('status', 'older'), ('progress', (number, 5)), barrier])
        self.assertEqual(drain(events), expected)
        self.assertEqual(events.unfinished_tasks, 0)

    def test_consumed_values_cannot_be_replaced_and_unknown_events_are_retained(self):
        events = WorkerEventQueue()
        events.put(('status', 'first'))
        self.assertEqual(events.get_nowait(), ('status', 'first'))
        events.put_nowait(('status', 'second'))
        events.task_done()
        malformed = (['not-a-kind'], object())
        events.put(malformed)
        events.put(('status', 'third'))
        self.assertEqual(drain(events), [('status', 'second'), malformed, ('status', 'third')])
        self.assertEqual(events.unfinished_tasks, 0)
        with self.assertRaises(queue.Empty):
            events.get(timeout=.001)

    def test_concurrent_producers_retain_every_completion_and_task_accounting(self):
        events = WorkerEventQueue()
        start = threading.Barrier(5)
        def produce(worker):
            start.wait(timeout=5)
            for number in range(1000):
                events.put(('progress', (worker, number)))
                events.put(('status', f'{worker}:{number}'))
            events.put(('done', worker))
        workers = [threading.Thread(target=produce, args=(index,)) for index in range(4)]
        for worker in workers:
            worker.start()
            self.addCleanup(worker.join, 5)
        start.wait(timeout=5)
        completed = []
        while len(completed) != 4:
            kind, value = events.get(timeout=5)
            if kind == 'done':
                completed.append(value)
            events.task_done()
        for worker in workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(completed), [0, 1, 2, 3])
        self.assertTrue(events.empty())
        self.assertEqual(events.unfinished_tasks, 0)


class ApplicationEventTests(unittest.TestCase):
    def app(self, events):
        app = app_state()
        app.events = events
        app.activity = 'preview'
        app.needs_plan = False
        app.paused = threading.Event()
        app.progress = {'value': 0}
        app.status = Value('Working')
        app.drop_action_pending = None
        app._handle_event = lambda kind, value: (
            DrawBotApp._handle_event(app, kind, value)
            if kind in ('status', 'progress', 'done') else None)
        return app

    def test_actual_executor_notifications_no_longer_delay_completed_worker_by_many_polls(self):
        plan = simple_visual_plan()
        self.addCleanup(plan['image'].close)
        plan['groups'] = [[(0, 0, 1, 0)] * 6000, []]
        plan['count'] = 6000
        plan['options'].update(speed='Safe', color_order=[0], unlimited_time=True,
                               test_run=True, visual_verification_enabled=False)
        trace = []
        with ExitStack() as stack:
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.save_runtime_safety_report',
                                      side_effect=lambda report: report.as_dict()))
            for target in ('RealSpeedBudget.record_runtime_sample',
                           'DrawTimeEstimate.record_completed_draw',
                           'CompletedDrawingAnalysis.record_completed_drawing',
                           'AutoTunerFeedback.record_completed_feedback',
                           'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(target, return_value={}))
            execute_plan(plan, (100, 100, 20, 20), [(10, 10), (20, 10)],
                         Mouse(), NoWait(), threading.Event(), lambda *event: trace.append(event))
        self.assertIn(('progress', (6000, 6000)), trace)
        trace.append(('done', 'preview'))
        old = self.app(queue.Queue())
        current = self.app(WorkerEventQueue())
        for event in trace:
            old.events.put(event)
            current.events.put(event)
        self.assertGreater(old.events.qsize(), 250)
        self.assertLess(current.events.qsize(), 25)
        with patch.object(DrawBotApp, '_schedule_poll'), patch('DrawBot.time.monotonic', return_value=0):
            DrawBotApp.poll(old)
            DrawBotApp.poll(current)
        self.assertEqual(old.activity, 'preview')
        self.assertIsNone(current.activity)
        self.assertEqual(current.progress['value'], 100)
        self.assertIn('Finished locally: 6,000', current.status.get())
        self.assertTrue(current.events.empty())

    def test_late_deadline_telemetry_cannot_overwrite_explicit_stop(self):
        app = self.app(WorkerEventQueue())
        app.stop.set()
        app.status.set('Stopping…')
        DrawBotApp._handle_event(app, 'deadline_telemetry', {'mode': 'PANIC'})
        self.assertEqual(app.status.get(), 'Stopping…')


if __name__ == '__main__':
    unittest.main()
