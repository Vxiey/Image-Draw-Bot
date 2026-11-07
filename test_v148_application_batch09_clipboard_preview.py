"""Clipboard completion preserves idle preview and explicit-start ordering."""
from contextlib import ExitStack
import queue
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp
from DropInStart import DROP_IN_ACTION


class ScheduledRoot:
    def __init__(self):
        self.jobs = {}
        self.serial = 0

    def after(self, delay, callback):
        self.serial += 1
        self.jobs[self.serial] = (delay, callback)
        return self.serial

    def after_cancel(self, token):
        self.jobs.pop(token, None)

    def run_next(self):
        token = min(self.jobs, key=lambda value: (self.jobs[value][0], value))
        _, callback = self.jobs.pop(token)
        return callback()


class ClipboardCompletionPreviewTests(unittest.TestCase):
    def app(self, mode='Automatic', *, armed=False):
        stack = self.enterContext(ExitStack())
        for name in ('_clear_render_resume', '_invalidate_target_lock',
                     '_sync_mobile_preview', '_schedule_poll',
                     '_close_smart_drop_overlay', '_disarm_full_draw',
                     '_disarm_manual_drop_in'):
            stack.enter_context(patch.object(DrawBotApp, name))
        stack.enter_context(patch.object(DrawBotApp, '_manual_drop_in_armed', return_value=armed))
        stack.enter_context(patch.object(DrawBotApp, '_queue_browser_one_click_after_import', return_value=False))
        stack.enter_context(patch.object(DrawBotApp, '_drop_in_fingerprint', return_value=('Gartic Phone', 42)))
        app = SimpleNamespace(
            activity='load', closing=False, pending_clear_drawing=None,
            stop=threading.Event(), paused=threading.Event(), events=queue.Queue(),
            root=ScheduledRoot(), original=None, plan=None, worker=Mock(),
            screen_task_window=None, file_label=Mock(), status=Mock(),
            subject_hint=Mock(), summary=Mock(), show_previews=Mock(),
            _schedule_recovery_checkpoint=Mock(), preview_generation=0,
            preview_after=None, preview_render_after=None, needs_plan=False,
            preview_mode=SimpleNamespace(get=lambda: mode), update_plan=Mock(),
            _refresh_target_for_draw=Mock(), drop_action_pending=None,
        )
        app.set_busy = lambda activity: setattr(app, 'activity', activity)
        for name in ('_handle_event', '_mark_plan_stale', '_maybe_auto_preview',
                     '_auto_preview_enabled', '_run_pending_drop_in_start'):
            setattr(app, name, MethodType(getattr(DrawBotApp, name), app))
        image = Image.new('RGBA', (3, 2), (12, 34, 56, 78))
        self.addCleanup(image.close)
        return app, image

    def accept_result(self, app, image, action=None):
        app.events.put(('pasted', (image, action)))
        DrawBotApp.poll(app)

    def finish_load(self, app):
        app.events.put(('done', 'load'))
        DrawBotApp.poll(app)

    def test_automatic_preview_waits_for_load_completion_and_then_runs_once(self):
        app, image = self.app()
        self.accept_result(app, image)
        self.assertIs(app.original, image)
        self.assertEqual(app.activity, 'load')
        self.assertTrue(app.needs_plan)
        self.assertEqual(app.root.jobs, {})
        self.finish_load(app)
        self.assertIsNone(app.activity)
        self.assertFalse(app.needs_plan)
        self.assertEqual([delay for delay, _ in app.root.jobs.values()], [900])
        app.root.run_next()
        app.update_plan.assert_called_once_with(user_initiated=False, reason='queued-plan')
        DrawBotApp.poll(app)
        self.assertEqual(app.root.jobs, {})

    def test_manual_mode_never_schedules_preview_after_accepting_bitmap(self):
        app, image = self.app('Manual')
        self.accept_result(app, image)
        self.finish_load(app)
        self.assertIs(app.original, image)
        self.assertFalse(app.needs_plan)
        self.assertEqual(app.root.jobs, {})
        app.update_plan.assert_not_called()

    def test_stop_before_or_after_bitmap_acceptance_never_restarts_preview(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                app, image = self.app()
                if accepted:
                    self.accept_result(app, image)
                DrawBotApp.cancel(app)
                if not accepted:
                    self.accept_result(app, image)
                self.finish_load(app)
                self.assertTrue(app.stop.is_set())
                self.assertFalse(app.needs_plan)
                self.assertEqual(app.root.jobs, {})
                app.update_plan.assert_not_called()
                if accepted:
                    self.assertIs(app.original, image)
                    self.assertEqual(image.getpixel((0, 0)), (12, 34, 56, 78))
                else:
                    self.assertIsNone(app.original)
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))

    def test_explicit_drop_in_waits_until_idle_and_precedes_automatic_preview(self):
        app, image = self.app(armed=True)
        self.accept_result(app, image, DROP_IN_ACTION)
        # A callback scheduled here could run while worker-finally still owns
        # 'load', causing the start guard to revoke the user's valid request.
        self.assertEqual(app.root.jobs, {})
        self.assertEqual(app.drop_action_pending, DROP_IN_ACTION)
        self.finish_load(app)
        self.assertEqual(sorted(delay for delay, _ in app.root.jobs.values()), [60, 900])

        def draw(application, *, user_initiated):
            self.assertTrue(user_initiated)
            self.assertIsNone(application.activity)
            return DrawBotApp.begin_worker(application, 'draw', Mock())

        with patch.object(DrawBotApp, '_strict_safety_required', return_value=False), \
             patch.object(DrawBotApp, '_start_guard_ready', return_value=(True, 'ready')), \
             patch.object(DrawBotApp, 'draw', side_effect=draw) as draw_call, \
             patch('ScreenTaskWindow.ScreenTaskWindow'), patch('DrawBot.threading.Thread'):
            self.assertTrue(app.root.run_next())
        draw_call.assert_called_once_with(app, user_initiated=True)
        self.assertEqual(app.activity, 'draw')
        self.assertIsNone(app.drop_action_pending)
        self.assertEqual(app.root.jobs, {})
        app.update_plan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
