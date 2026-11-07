"""Explicit preview requests preserve a new Esc through preparation and handoff."""
from pathlib import Path
import queue
import threading
from types import MethodType
from unittest.mock import Mock, patch

from PIL import Image

import DrawBot
from test_pixel_accurate_v1086 import opts
from test_v148_ui_batch16_plan_status import PlanStatusFixture
from test_v148_ui_batch20_auto_preview import ScheduledRoot


class ExplicitPreviewStopTests(PlanStatusFixture):
    def setUp(self):
        super().setUp()
        self.screen = self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_schedule_poll'))
        self.planner = self.stack.enter_context(patch('DrawBot.make_plan', wraps=DrawBot.make_plan))

    def image(self, _color):
        # Reuse shipped artwork; no test picture or image file is generated.
        with Image.open(Path(__file__).with_name('assets') / 'image-draw-bot-icon.png') as image:
            source = image.convert('RGBA')
        self.images.append(source)
        return source

    def app(self, mode='Manual'):
        app = super().app()
        app.root = ScheduledRoot()
        app.events = queue.Queue()
        app.mouse = Mock()
        app.preview_mode.set(mode)
        app.preview_after = None
        app.needs_plan = False
        app.drop_action_pending = None
        for name in ('begin_worker', '_handle_event', 'update_plan', 'request_preview',
                     'request_full_preview'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        app.options = lambda: opts(
            profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_current_color=True, draw_quality='High likeness',
            render_preset='Manual', unlimited_time=True, time_budget_mode='Unlimited',
            cpu_workers='1', detail_zoom='Off', _execution_cost_calibration_override={})
        return app

    def finish(self, app):
        worker = app.worker
        if worker is not None:
            self.assertIsInstance(worker, threading.Thread)
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive(), 'The actual preview worker must terminate')
        events = []
        while not app.events.empty():
            event = app.events.get_nowait()
            events.append(event)
            if event[0] == 'planned':
                self.plans.append(event[1])
            app._handle_event(*event)
        self.assertIsNone(app.activity)
        return events

    def assert_no_work(self, app):
        events = self.finish(app)
        self.assertFalse(any(kind == 'planned' for kind, _ in events))
        self.assertTrue(app.stop.is_set())
        self.assertIsNone(app.plan)
        self.assertEqual(app.status.get(), 'Stopped.')
        self.assertFalse(app.root.jobs)
        self.assertFalse(app.mouse.method_calls)

    def test_new_explicit_request_after_old_stop_still_builds_actual_plan(self):
        for mode, method in (('Manual', 'request_preview'), ('Auto light', 'request_preview'),
                             ('Auto full', 'request_preview'), ('Manual', 'request_full_preview')):
            with self.subTest(mode=mode, method=method):
                app = self.app(mode)
                original = app.original
                before = self.planner.call_count
                DrawBot.DrawBotApp._request_stop(app)
                getattr(app, method)()
                events = self.finish(app)
                self.assertFalse(app.stop.is_set())
                self.assertEqual([kind for kind, _ in events], ['planned', 'done'])
                self.assertIs(app.plan, events[0][1])
                self.assertGreater(app.plan['count'], 0)
                self.assertEqual(app.plan['target_area'], app.area()[2:])
                self.assertEqual(self.planner.call_count, before + 1)
                self.assertIs(app.original, original)
                self.assertFalse(app.mouse.method_calls)

    def test_escape_during_explicit_options_is_not_erased_by_worker_handoff(self):
        for mode, method in (('Manual', 'request_preview'), ('Auto light', 'request_preview'),
                             ('Auto full', 'request_preview'), ('Manual', 'request_full_preview')):
            with self.subTest(mode=mode, method=method):
                app = self.app(mode)
                options = app.options
                before = self.planner.call_count
                def stop_in_options():
                    result = options()
                    DrawBot.DrawBotApp._request_stop(app)
                    return result
                app.options = stop_in_options
                getattr(app, method)()
                self.assert_no_work(app)
                self.assertEqual(self.planner.call_count, before)

    def test_escape_after_real_source_snapshot_closes_private_pixels_without_starting(self):
        app = self.app()
        source = app.original
        original_pixels = source.tobytes()
        copies = []
        copy = source.copy
        def snapshot():
            copied = copy()
            copies.append(copied)
            self.images.append(copied)
            DrawBot.DrawBotApp._request_stop(app)
            return copied
        with patch.object(source, 'copy', side_effect=snapshot):
            app.request_preview()
        self.assert_no_work(app)
        self.assertEqual(len(copies), 1)
        with self.assertRaises(ValueError):
            copies[0].getpixel((0, 0))
        self.assertEqual(source.tobytes(), original_pixels)
        self.planner.assert_not_called()

    def test_escape_during_actual_worker_preparation_keeps_cancelled_task_empty(self):
        app = self.app()
        self.screen.side_effect = lambda *_args: DrawBot.DrawBotApp._request_stop(app) or Mock()
        app.request_preview()
        self.assert_no_work(app)
        self.planner.assert_not_called()

    def test_unready_requests_do_not_clear_stop_or_read_settings_or_copy_source(self):
        for field, value in (('activity', 'draw'), ('closing', True),
                             ('profile_change_after', 'pending-profile'),
                             ('profile_change_in_progress', True),
                             ('pending_clear_drawing', {'remove_image': True})):
            with self.subTest(field=field):
                app = self.app()
                setattr(app, field, value)
                DrawBot.DrawBotApp._request_stop(app)
                app.options = Mock(side_effect=AssertionError('Read an incomplete UI context'))
                with patch.object(app.original, 'copy', side_effect=AssertionError('Copied an incomplete context')):
                    app.request_preview()
                self.assertTrue(app.stop.is_set())
                app.options.assert_not_called()
                self.assertIsNone(app.worker)
                self.assertFalse(app.mouse.method_calls)
        self.planner.assert_not_called()


if __name__ == '__main__':
    import unittest
    unittest.main()
