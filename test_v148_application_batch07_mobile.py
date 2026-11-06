"""Exercise real UI publication paths without a desktop or network listener."""
from contextlib import ExitStack
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp


class IdleQueue:
    def __init__(self):
        self.jobs = {}
        self.next_id = 0

    def after_idle(self, callback):
        self.next_id += 1
        self.jobs[self.next_id] = callback
        return self.next_id

    def after_cancel(self, token):
        self.jobs.pop(token, None)

    def drain(self):
        jobs, self.jobs = self.jobs, {}
        for callback in jobs.values():
            callback()


class MobileUiPublicationTests(unittest.TestCase):
    def image(self, color, mode='RGBA'):
        image = Image.new(mode, (8, 6), color)
        self.addCleanup(image.close)
        return image

    def app(self):
        server = SimpleNamespace(running=True, queue_images=Mock(return_value=True))
        server.stop = Mock(side_effect=lambda: setattr(server, 'running', False))
        app = SimpleNamespace(root=IdleQueue(), closing=False, activity=None,
            stop=threading.Event(), mobile_preview_server=server,
            mobile_preview_after=None, mobile_preview_ticket=None,
            original=self.image('red'), plan={'preview': self.image('blue')},
            preview_generation=0, preview_rendering=False, color_session_cache={},
            background_removal_original=None, background_removal_meta=None,
            mobile_preview_status=Mock(), mobile_preview_url=Mock(),
            status=Mock(), summary=Mock(), file_label=Mock(), photos=[])
        for name in ('_schedule_recovery_checkpoint', '_maybe_auto_preview'):
            setattr(app, name, Mock())
        app.show_previews = lambda: DrawBotApp.show_previews(app)
        app._sync_mobile_preview = lambda: DrawBotApp._sync_mobile_preview(app)
        app._mark_plan_stale = lambda message='changed': DrawBotApp._mark_plan_stale(app, message)
        return app, server

    def test_many_changes_publish_once_and_capture_latest_accepted_state(self):
        app, server = self.app()
        for _ in range(20):
            app.show_previews()
        app.original = self.image('green')
        app.plan = {'preview': self.image('yellow'), 'ui_previews': {'safety': self.image('black')}}
        app.show_previews()
        self.assertEqual(len(app.root.jobs), 1)
        server.queue_images.assert_not_called()
        app.root.drain()
        server.queue_images.assert_called_once_with(original=app.original,
            preview=app.plan['preview'], safety=app.plan['ui_previews']['safety'])
        self.assertIsNone(app.mobile_preview_after)

    def test_mobile_uses_the_same_full_final_layer_and_background_toggle(self):
        app, server = self.app()
        final, strokes = self.image('yellow'), self.image('white')
        app.plan['ui_previews'] = {'simulated_final': final, 'stroke': strokes}
        app.preview_show_background = Mock()
        for enabled, expected in ((True, final), (False, strokes)):
            app.preview_show_background.get.return_value = enabled
            app.show_previews(); app.root.drain()
            self.assertIs(server.queue_images.call_args.kwargs['preview'], expected)

    def test_manual_plan_invalidation_clears_mobile_plan_without_auto_preview(self):
        app, server = self.app()
        with patch.object(DrawBotApp, '_invalidate_target_lock'):
            app._mark_plan_stale('Settings changed')
        app.root.drain()
        server.queue_images.assert_called_once_with(original=app.original, preview=None, safety=None)
        app._maybe_auto_preview.assert_not_called()

    def test_actual_undo_adopts_restored_source_and_clears_old_final(self):
        app, server = self.app()
        previous = self.image('green')
        app.background_removal_original = previous
        with patch.object(DrawBotApp, '_invalidate_target_lock'), \
                patch.object(DrawBotApp, '_clear_render_resume'):
            self.assertTrue(DrawBotApp.undo_background_removal(app))
        self.addCleanup(app.original.close)
        app.root.drain()
        published = server.queue_images.call_args.kwargs
        self.assertEqual(published['original'].tobytes(), previous.tobytes())
        self.assertIsNone(published['preview'])
        self.assertIsNone(published['safety'])
        self.assertEqual(server.queue_images.call_count, 1)

    def test_actual_loaded_event_updates_mobile_in_manual_mode(self):
        app, server = self.app()
        new_source = self.image('green')
        with ExitStack() as stack:
            for name in ('_invalidate_target_lock', '_clear_render_resume',
                         '_queue_drop_in_start', '_queue_browser_one_click_after_import'):
                stack.enter_context(patch.object(DrawBotApp, name))
            DrawBotApp._handle_event(app, 'loaded', (new_source, 'fixture.png', 'Load image', False))
        app.root.drain()
        server.queue_images.assert_called_once_with(original=new_source, preview=None, safety=None)

    def test_stop_reuses_server_and_old_callback_cannot_erase_restart_request(self):
        app, server = self.app()
        app._sync_mobile_preview()
        old_callback = next(iter(app.root.jobs.values()))
        DrawBotApp.stop_mobile_preview(app, quiet=True)
        self.assertIs(app.mobile_preview_server, server)
        self.assertFalse(app.root.jobs)
        self.assertFalse(server.running)
        server.running = True
        app.original = self.image('yellow')
        app._sync_mobile_preview()
        new_ticket, new_job = app.mobile_preview_ticket, app.mobile_preview_after
        old_callback()
        self.assertIs(app.mobile_preview_ticket, new_ticket)
        self.assertEqual(app.mobile_preview_after, new_job)
        server.queue_images.assert_not_called()
        app.root.drain()
        self.assertIs(server.queue_images.call_args.kwargs['original'], app.original)

    def test_ordinary_drawing_stop_preserves_accepted_source_publication(self):
        app, server = self.app()
        app._sync_mobile_preview()
        app.stop.set()
        app.root.drain()
        server.queue_images.assert_called_once()

    def test_disabled_closing_and_replaced_sessions_do_not_publish(self):
        for state in ('disabled', 'closing', 'replaced'):
            app, server = self.app()
            app._sync_mobile_preview()
            if state == 'disabled': server.running = False
            elif state == 'closing': app.closing = True
            else: app.mobile_preview_server = SimpleNamespace(running=True)
            app.root.drain()
            server.queue_images.assert_not_called()

    def test_capture_failure_can_be_retried_without_exposing_its_message(self):
        app, server = self.app()
        server.queue_images.side_effect = [ValueError('private-token-image-path'), True]
        with patch('DrawBot.log_event') as log:
            app._sync_mobile_preview(); app.root.drain()
        self.assertIn('ValueError', log.call_args.args[0])
        self.assertNotIn('private-token-image-path', log.call_args.args[0])
        app._sync_mobile_preview(); app.root.drain()
        self.assertEqual(server.queue_images.call_count, 2)


if __name__ == '__main__':
    unittest.main()
