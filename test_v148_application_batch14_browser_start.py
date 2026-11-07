"""Browser deferred starts belong to one source/profile/request through Stop."""
from contextlib import ExitStack
from pathlib import Path
import queue
import threading
from types import MethodType
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp
from test_v148_application_batch04_settings import Value
from test_v148_ui_lifecycle_batch02 import ui_app

REAL_THREAD = threading.Thread


class ScheduledRoot:
    def __init__(self):
        self.jobs = {}
        self.history = {}
        self.number = 0

    def after(self, delay, callback):
        self.number += 1
        token = f'job-{self.number}'
        self.jobs[token] = callback
        self.history[token] = callback
        return token

    def after_idle(self, callback):
        return self.after(0, callback)

    def after_cancel(self, token):
        self.jobs.pop(token, None)

    def run(self, token):
        return self.jobs.pop(token)()

    def iconify(self):
        pass


class NoWaitEvent(threading.Event):
    def wait(self, timeout=None):
        return self.is_set()


class DeferredThread:
    """Keep the real begin_worker wrapper, but advance it deterministically."""
    def __init__(self, *, target, **kwargs):
        self.target = target
        self.alive = False

    def start(self):
        self.alive = True

    def run(self):
        try:
            return self.target()
        finally:
            self.alive = False

    def is_alive(self):
        return self.alive


def setup_payload(handle=2):
    return {
        'profile_name': 'Gartic Phone', 'palette_count': 18, 'confidence': .96,
        'canvas_confidence': .97, 'canvas_box': (120, 50, 300, 180),
        'target_meta': {'handle': handle, 'rect': (100, 0, 400, 220),
                        'client_rect': (110, 30, 390, 210), 'dpi': 96},
    }


class BrowserStartOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('DrawBot.log_event', 'DrawBot.log_error',
                       'ScreenTaskWindow.ScreenTaskWindow'):
            self.stack.enter_context(patch(target))
        self.stack.enter_context(patch('DrawBot.threading.Thread', DeferredThread))
        for name in ('_close_smart_drop_overlay', '_disarm_manual_drop_in',
                     '_disarm_full_draw', '_clear_render_resume'):
            self.stack.enter_context(patch.object(DrawBotApp, name))
        self.setup = self.stack.enter_context(patch(
            'BrowserOneClick.one_click_setup', side_effect=lambda *a, **kw: setup_payload()))
        self.app = self.make_app()

    def make_app(self):
        app = ui_app()
        self.addCleanup(app.original.close)
        app.root = ScheduledRoot()
        app.stop = NoWaitEvent()
        app.paused = threading.Event()
        app.game = Value('Gartic Phone')
        app._active_profile_name = 'Gartic Phone'
        app.profile_change_after = None
        app.profile_change_in_progress = False
        app.calibration_path = Path('unused-browser-calibration.json')
        app.events = queue.Queue()
        app.worker = None
        app.browser_one_click_enabled = Value(True)
        app.browser_one_click_force = False
        app.browser_one_click_pending = False
        app.browser_one_click_after = None
        app.browser_one_click_request = None
        app.browser_one_click_worker_request = None
        app.one_click_setup_verify_pending = None
        app.one_click_setup_verify_payload = None
        app.one_click_setup_after = None
        app.mouse = Mock()
        app.progress = {'value': 0}
        app.paint_simple = Value(False)
        app.outline = Value(False)
        app._palette_preflight_ready = lambda: True
        app._paint_tool_preflight_ready = lambda: True
        app._refresh_target_for_draw = lambda: app.target_client_rect
        app.area = lambda: (120, 50, 180, 130)
        app._sync_mobile_preview = Mock()
        app.set_busy = lambda value: setattr(app, 'activity', value)
        app.begin_worker = MethodType(DrawBotApp.begin_worker, app)
        app.load_source = MethodType(DrawBotApp.load_source, app)
        for name in ('status', 'summary', 'browser_one_click_text', 'browser_auto_text',
                     'one_click_setup_text', 'area_text', 'file_label'):
            setattr(app, name, Value(''))
        return app

    def drain(self):
        events = []
        while not self.app.events.empty():
            event = self.app.events.get_nowait()
            events.append(event)
            DrawBotApp._handle_event(self.app, *event)
        return events

    def queued(self, *, force=False):
        self.assertTrue(DrawBotApp._queue_browser_one_click_after_import(
            self.app, 'test image', force=force))
        return self.app.browser_one_click_request, self.app.browser_one_click_after

    def ready(self, *, force=False):
        request, token = self.queued(force=force)
        self.assertTrue(self.app.root.run(token))
        self.assertEqual(self.app.activity, 'browser-one-click-setup')
        self.app.worker.run()
        events = self.drain()
        self.assertEqual(request['phase'], 'finish')
        self.assertIsNone(self.app.activity)
        return request, self.app.browser_one_click_after, events

    def test_import_to_owned_finish_enters_real_draw_preflight_and_planning(self):
        for force in (False, True):
            with self.subTest(force=force), ExitStack() as local:
                self.app = self.make_app()
                self.app.browser_one_click_enabled.set(not force)
                source = Image.new('RGB', (10, 8), 'blue')
                self.addCleanup(source.close)
                local.enter_context(patch('DrawBot.load_image', return_value=source))
                self.assertTrue(self.app.load_source('fixture.png', 'fixture', one_click_force=force))
                self.app.worker.run()
                self.drain()
                request = self.app.browser_one_click_request
                self.assertIs(request['image'], source)
                self.app.root.run(self.app.browser_one_click_after)
                self.app.worker.run()
                self.drain()
                callback = self.app.root.history[self.app.browser_one_click_after]
                self.app.options = lambda: {
                    'brush_px': 3, 'background_fill': 'Off', 'use_region_fill_engine': False,
                    'auto_clear_canvas': False, 'unlimited_time': True, 'max_seconds': 180,
                }
                local.enter_context(patch('DrawBot.allColors', []))
                calibration = local.enter_context(patch('DrawBot.load_calibration'))
                visual = local.enter_context(patch.object(DrawBotApp, '_run_browser_visual_preflight',
                                                          return_value=self.app.target_client_rect))
                local.enter_context(patch('BrowserBrushSize.SUPPORTED', set()))
                local.enter_context(patch('BrowserToolLayout.SUPPORTED', set()))
                local.enter_context(patch('ScreenGuard.GuardedMouse'))
                local.enter_context(patch('ScreenGuard.WindowMonitor'))
                planning = local.enter_context(patch('DrawBot.build_planning_attempts',
                    side_effect=InterruptedError('test stops at the planning boundary')))
                self.app.root.run(self.app.browser_one_click_after)
                self.assertEqual(self.app.activity, 'draw')
                self.assertIsNone(self.app.browser_one_click_request)
                self.assertFalse(self.app.browser_one_click_force)
                calibration.assert_called_once()
                visual.assert_called_once_with(self.app, self.app.target_client_rect, reason='drawing')
                self.app.worker.run()
                planning.assert_called_once()
                self.assertFalse(callback())
                self.assertEqual(planning.call_count, 1)
                self.assertEqual(self.app.start_state_machine.state, 'ABORTED')

    def test_stop_then_new_loader_clears_stop_but_cannot_revive_old_finish(self):
        old, token, _ = self.ready()
        late_finish = self.app.root.history[token]
        DrawBotApp.cancel(self.app)
        self.assertTrue(old['cancelled'].is_set())
        self.assertNotIn(token, self.app.root.jobs)
        source = Image.new('RGB', (6, 5), 'green')
        self.addCleanup(source.close)
        with patch('DrawBot.load_image', return_value=source), patch.object(DrawBotApp, 'draw', return_value=True) as draw:
            self.assertTrue(self.app.load_source('new.png', 'new image'))
            self.assertFalse(self.app.stop.is_set())
            status = self.app.status.get()
            self.assertFalse(late_finish())
            self.assertEqual(self.app.status.get(), status)
            draw.assert_not_called()
            self.app.worker.run()
            self.drain()
            new = self.app.browser_one_click_request
            self.app.root.run(self.app.browser_one_click_after)
            self.app.worker.run()
            self.drain()
            newest_token = self.app.browser_one_click_after
            self.assertFalse(late_finish())
            self.assertIs(self.app.browser_one_click_request, new)
            self.assertEqual(self.app.browser_one_click_after, newest_token)
            self.assertTrue(self.app.root.run(newest_token))
        draw.assert_called_once_with(self.app, user_initiated=True)

    def test_replaced_queue_callback_cannot_clear_or_run_the_new_request(self):
        old, token = self.queued(force=True)
        callback = self.app.root.history[token]
        new, new_token = self.queued(force=False)
        self.assertTrue(old['cancelled'].is_set())
        self.assertFalse(callback())
        self.assertIs(self.app.browser_one_click_request, new)
        self.assertEqual(self.app.browser_one_click_after, new_token)
        self.assertFalse(self.app.browser_one_click_force)
        self.assertEqual(self.setup.call_count, 0)
        self.assertTrue(self.app.root.run(new_token))
        self.app.worker.run()
        self.drain()
        self.assertEqual(self.setup.call_count, 1)

    def test_old_result_and_done_cannot_publish_or_finish_a_replacement(self):
        old, token = self.queued(force=True)
        self.app.root.run(token)
        self.app.worker.run()
        old_result = self.app.events.get_nowait()
        old_done = self.app.events.get_nowait()
        new, new_token = self.queued()
        before = (list(self.app.corners), self.app.target_window)
        DrawBotApp._handle_event(self.app, *old_result)
        self.assertEqual((self.app.corners, self.app.target_window), before)
        self.assertFalse(self.app.browser_one_click_force)
        DrawBotApp._handle_event(self.app, *old_done)
        self.assertIsNone(self.app.activity)
        self.assertEqual(self.app.browser_one_click_after, new_token)
        self.app.root.run(new_token)
        new_worker = self.app.worker
        DrawBotApp._handle_event(self.app, 'done', 'browser-one-click-setup')
        self.assertIs(self.app.worker, new_worker)
        DrawBotApp._handle_event(self.app, *old_done)
        self.assertEqual(self.app.activity, 'browser-one-click-setup')
        self.assertIs(self.app.worker, new_worker)
        new_worker.run()
        self.drain()
        with patch.object(DrawBotApp, 'draw', return_value=True) as draw:
            self.assertTrue(self.app.root.run(self.app.browser_one_click_after))
        draw.assert_called_once()
        self.assertIsNot(old, new)

    def test_source_profile_and_switch_changes_revoke_a_ready_callback(self):
        for change in ('source', 'profile', 'switch', 'settings'):
            with self.subTest(change=change):
                self.app = self.make_app()
                request, token, _ = self.ready()
                callback = self.app.root.history[token]
                if change == 'source':
                    source = Image.new('RGB', (2, 2), 'black')
                    self.addCleanup(source.close)
                    self.app.original = source
                elif change == 'profile':
                    self.app.game.set('Skribbl.io')
                elif change == 'switch':
                    self.app.browser_one_click_enabled.set(False)
                else:
                    DrawBotApp.options_changed(self.app)
                with patch.object(DrawBotApp, 'draw') as draw:
                    self.assertFalse(callback())
                draw.assert_not_called()
                self.assertTrue(request['cancelled'].is_set())
                self.assertIsNone(self.app.browser_one_click_request)

    def test_accepted_profile_change_stays_revoked_after_changing_back(self):
        request, token, _ = self.ready(force=True)
        callback = self.app.root.history[token]
        self.app.game.set('Skribbl.io')
        DrawBotApp.change_profile(self.app)
        self.app.game.set('Gartic Phone')
        DrawBotApp.change_profile(self.app)
        with patch.object(DrawBotApp, 'draw') as draw:
            self.assertFalse(callback())
        self.assertTrue(request['cancelled'].is_set())
        self.assertIsNone(self.app.profile_change_after)
        draw.assert_not_called()

    def test_source_adoption_revokes_even_if_the_old_image_is_later_restored(self):
        request, token, _ = self.ready(force=True)
        callback = self.app.root.history[token]
        old_source = self.app.original
        resized = Image.new('RGBA', (6, 4), 'red')
        self.addCleanup(resized.close)
        DrawBotApp._handle_event(self.app, 'upscaled', (resized, old_source))
        self.app.original = old_source
        with patch.object(DrawBotApp, 'draw') as draw:
            self.assertFalse(callback())
        draw.assert_not_called()
        self.assertTrue(request['cancelled'].is_set())

    def test_stop_during_setup_uses_request_cancel_after_global_stop_is_cleared(self):
        request, token = self.queued(force=True)
        self.app.root.run(token)
        old_worker = self.app.worker
        def cancelled_setup(*args, cancelled, **kwargs):
            DrawBotApp.cancel(self.app)
            self.app.stop.clear()
            self.assertTrue(cancelled())
            return setup_payload()
        self.setup.side_effect = cancelled_setup
        before = self.app.target_window
        old_worker.run()
        events = self.drain()
        self.assertNotIn('browser_one_click_setup_complete', [kind for kind, value in events])
        self.assertTrue(request['cancelled'].is_set())
        self.assertEqual(self.app.target_window, before)
        self.assertIsNone(self.app.browser_one_click_after)

    def test_incomplete_or_rejected_setup_cannot_reuse_prior_success(self):
        for outcome in ('failure', 'bad-canvas', 'missing-owner', 'refused-worker', 'schedule-failure'):
            with self.subTest(outcome=outcome), ExitStack() as local:
                self.app = self.make_app()
                if outcome == 'failure':
                    local.enter_context(patch('BrowserOneClick.one_click_setup', side_effect=ValueError('no game')))
                elif outcome == 'bad-canvas':
                    payload = setup_payload(); payload['canvas_box'] = (0, 0, 300, 180)
                    local.enter_context(patch('BrowserOneClick.one_click_setup', return_value=payload))
                elif outcome == 'refused-worker':
                    self.app.begin_worker = Mock(return_value=False)
                elif outcome == 'schedule-failure':
                    self.app.root.after = Mock(side_effect=RuntimeError('window gone'))
                    self.assertFalse(DrawBotApp._queue_browser_one_click_after_import(self.app, force=True))
                    self.assertIsNone(self.app.browser_one_click_request)
                    continue
                request, token = self.queued(force=True)
                self.app.root.run(token)
                if outcome == 'refused-worker':
                    self.assertIsNone(self.app.browser_one_click_request)
                    continue
                self.app.worker.run()
                result = self.app.events.get_nowait()
                if outcome == 'missing-owner': result[1].pop('_browser_request')
                if outcome == 'bad-canvas':
                    with self.assertRaises(ValueError): DrawBotApp._handle_event(self.app, *result)
                else:
                    DrawBotApp._handle_event(self.app, *result)
                self.drain()
                self.assertIsNone(self.app.browser_one_click_request)
                self.assertIsNone(self.app.browser_one_click_after)
                self.assertFalse(self.app.browser_one_click_force)
                self.assertTrue(request['cancelled'].is_set())

    def test_setup_verify_is_read_only_with_persistent_one_click_enabled(self):
        old, token, _ = self.ready(force=True)
        old_finish = self.app.root.history[token]
        self.assertTrue(DrawBotApp.run_one_click_setup_verify(self.app))
        request = self.app.browser_one_click_request
        self.assertFalse(request['auto_start'])
        self.assertTrue(old['cancelled'].is_set())
        self.app.worker.run()
        self.drain()
        self.assertIsNone(self.app.browser_one_click_after)
        self.assertFalse(old_finish())
        with patch.object(DrawBotApp, 'draw') as draw, \
                patch('ScreenGuard.WindowMonitor') as monitor_type, \
                patch('PIL.ImageGrab.grab') as capture, \
                patch('OneClickSetupVerification.verify_browser_live') as verify:
            monitor = monitor_type.return_value
            monitor.activate.return_value = True
            monitor.rectangle.return_value = self.app.target_window[1]
            monitor.client_rectangle.return_value = self.app.target_client_rect
            monitor.dpi.return_value = 96
            screenshot = Image.new('RGB', (280, 180), 'white')
            self.addCleanup(screenshot.close)
            capture.return_value = screenshot
            verify.return_value.as_dict.return_value = {
                'passed': True, 'profile_key': 'gartic-phone', 'mode': 'browser',
                'confidence': .96, 'canvas_ok': True, 'palette_ok': True,
                'palette_verified': 18, 'palette_tested': 18, 'tool_ok': True,
            }
            self.assertTrue(self.app.root.run(self.app.one_click_setup_after))
            self.assertEqual(self.app.activity, 'one-click-verify')
            self.app.worker.run()
            self.drain()
            verify.assert_called_once()
            draw.assert_not_called()
        self.assertIn('No drawing input was sent', self.app.status.get())
        self.assertIsNone(self.app.browser_one_click_request)
        self.assertIsNone(self.app.one_click_setup_verify_pending)

    def test_read_only_verification_callback_is_cancelled_without_reviving_after_stop(self):
        self.assertTrue(DrawBotApp.run_one_click_setup_verify(self.app))
        self.app.worker.run()
        self.drain()
        callback = self.app.root.history[self.app.one_click_setup_after]
        DrawBotApp.cancel(self.app)
        self.assertTrue(self.app.begin_worker('preview', lambda: None))
        self.assertFalse(self.app.stop.is_set())
        self.assertFalse(callback())
        self.assertEqual(self.app.activity, 'preview')
        self.assertIsNone(self.app.one_click_setup_verify_pending)

    def test_finish_scheduling_failure_never_runs_draw_synchronously(self):
        request, token = self.queued(force=True)
        self.app.root.run(token)
        self.app.worker.run()
        DrawBotApp._handle_event(self.app, *self.app.events.get_nowait())
        self.app.root.after = Mock(side_effect=RuntimeError('window gone'))
        with patch.object(DrawBotApp, 'draw') as draw:
            self.drain()
        draw.assert_not_called()
        self.assertTrue(request['cancelled'].is_set())
        self.assertIsNone(self.app.browser_one_click_request)

    def test_changed_preflight_or_shutdown_blocks_the_owned_finish(self):
        for change in ('palette', 'target', 'closing'):
            with self.subTest(change=change):
                self.app = self.make_app()
                request, token, _ = self.ready(force=True)
                if change == 'palette': self.app._palette_preflight_ready = lambda: False
                elif change == 'target': self.app.target_window = None
                else: self.app.closing = True
                with patch.object(DrawBotApp, 'draw') as draw:
                    self.assertFalse(self.app.root.run(token))
                draw.assert_not_called()
                self.assertTrue(request['cancelled'].is_set())

    def test_real_worker_reads_no_tk_values_and_observes_request_revocation(self):
        owner = threading.get_ident()
        class ThreadBoundValue(Value):
            def get(self):
                if threading.get_ident() != owner:
                    raise AssertionError('Tk value read from worker')
                return super().get()
        for cancel in (False, True):
            with self.subTest(cancel=cancel), ExitStack() as local:
                self.app = self.make_app()
                self.app.game = ThreadBoundValue('Gartic Phone')
                self.app.browser_one_click_enabled = ThreadBoundValue(True)
                entered = threading.Event()
                released = threading.Event()
                observed = []
                def setup(*args, cancelled, **kwargs):
                    entered.set()
                    if not released.wait(2): raise AssertionError('worker was not released')
                    observed.append(cancelled())
                    return setup_payload()
                local.enter_context(patch('DrawBot.threading.Thread', REAL_THREAD))
                local.enter_context(patch('BrowserOneClick.one_click_setup', side_effect=setup))
                request, token = self.queued()
                self.app.root.run(token)
                worker = self.app.worker
                self.assertTrue(entered.wait(2))
                try:
                    if cancel:
                        DrawBotApp.cancel(self.app)
                        self.app.stop.clear()
                finally:
                    released.set()
                    worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                events = self.drain()
                self.assertEqual(observed, [cancel])
                self.assertNotIn('terminal_status', [kind for kind, value in events])
                self.assertEqual(any(kind == 'browser_one_click_setup_complete' for kind, value in events), not cancel)
                if cancel:
                    self.assertTrue(request['cancelled'].is_set())
                    self.assertIsNone(self.app.browser_one_click_after)


if __name__ == '__main__':
    unittest.main()
