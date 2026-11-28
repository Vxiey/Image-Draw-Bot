import queue
import threading
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DrawBot import DrawBotApp
from GameProfiles import PROFILES
from GuidedSetupController import GuidedSetupController


class Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class TkQueue:
    def __init__(self):
        self.callbacks = {}
        self.visibility = 'zoomed'
        self.last_token = 0

    def state(self, state=None):
        if state:
            self.visibility = state
        return self.visibility

    def iconify(self):
        self.visibility = 'iconic'

    def deiconify(self):
        self.visibility = 'normal'

    def after(self, delay, callback):
        self.last_token += 1
        self.callbacks[self.last_token] = callback
        return self.last_token

    def after_cancel(self, token):
        self.callbacks.pop(token, None)

    def fire(self, token):
        self.callbacks.pop(token)()


def observation(profile='skribbl'):
    return {'profile_key': profile, 'canvas_confidence': .93, 'canvas_box': (100, 150, 700, 550),
            'target_meta': {'handle': 25, 'rect': (0, 0, 900, 750), 'client_rect': (4, 30, 896, 746),
                            'target_pid': 123, 'target_thread': 42, 'dpi': 144}}


class GuidedControllerTests(unittest.TestCase):
    def setUp(self):
        a = DrawBotApp.__new__(DrawBotApp)
        a.original = object()
        a.activity = a.target_window = a.target_client_rect = a.target_dpi = None
        a.corners = []
        a.closing = False
        a.game, a.ui_mode = Var('Skribbl.io'), Var('Simple')
        a.area_text, a.status = Var(''), Var('')
        a.color_session_cache = {1: 'old color'}
        a.palette_ready = False
        a._palette_preflight_ready = lambda: a.palette_ready
        a._paint_tool_preflight_ready = lambda: True
        a.root, a.events = TkQueue(), queue.Queue()
        a.refresh_guided_setup = Mock()
        a._mark_plan_stale, a._schedule_recovery_checkpoint = Mock(), Mock()
        a.save_settings, a.show_previews, a.set_busy = Mock(), Mock(), Mock()
        a.run_one_click_setup_verify, a.start_full_drawing = Mock(), Mock()
        a.unlock_full_drawing = Mock()
        self.a = a
        self.guide = a._guided_setup_controller = GuidedSetupController(a, PROFILES)

    def complete(self, returned):
        a, guide = self.a, self.guide
        with patch('GuidedCanvasDiscovery.discover_guided_canvas', return_value=returned) as discover:
            a.root.fire(guide.after)
            event, payload = a.events.get(timeout=2)
            self.assertEqual(event, 'guided_canvas_complete')
            outcome = a._handle_event(event, payload)
        return outcome, discover

    def offer(self):
        self.assertTrue(self.a._queue_guided_canvas_discovery())
        self.assertEqual(self.a.root.visibility, 'zoomed')
        payload = observation()
        self.assertTrue(self.complete(payload)[0])
        self.assertEqual(self.a.guided_setup_state()['stage'], 'confirm_canvas')
        self.assertEqual(self.a.corners, [])
        self.a.save_settings.assert_not_called()
        return payload

    def test_outline_is_optional_and_closes_before_confirmation_checks(self):
        self.offer()
        with patch('GuidedSetupController.outline_supported', return_value=True), \
                patch('GuidedSetupController.CanvasOutline') as native:
            self.assertTrue(self.a.guided_setup_state()['show_canvas_enabled'])
            self.assertTrue(self.a.show_guided_canvas())
            self.assertEqual(self.a.root.visibility, 'zoomed')
            self.assertEqual(self.a.corners, [])
            stale_callback = self.a.root.callbacks[self.guide.outline_after]
            self.assertTrue(self.a.run_guided_action())
            native.return_value.close.assert_called_once()
            self.assertIsNone(self.guide.outline_after)
            stale_callback()
            self.assertIsNotNone(self.guide.request)
            native.return_value.check_target.assert_not_called()

    def test_outline_disappears_on_stop_context_change_native_move_and_timeout(self):
        self.offer()
        for reason in ('stop', 'context', 'moved', 'timeout'):
            with self.subTest(reason=reason), patch('GuidedSetupController.outline_supported', return_value=True), \
                    patch('GuidedSetupController.CanvasOutline') as native:
                if reason == 'timeout':
                    self.guide.OUTLINE_SECONDS = 0
                self.assertTrue(self.a.show_guided_canvas())
                if reason == 'stop':
                    self.guide.signal_stop()
                elif reason == 'context':
                    self.a.original = object()
                elif reason == 'moved':
                    native.return_value.check_target.side_effect = ValueError('target moved')
                self.a.root.fire(self.guide.outline_after)
                native.return_value.close.assert_called_once()
                self.assertIsNone(self.guide.outline)
                if reason == 'context':
                    self.offer()
        self.a.save_settings.assert_not_called()
        self.a.start_full_drawing.assert_not_called()

    def test_explicit_confirmation_rechecks_then_applies_without_calibrating_or_drawing(self):
        candidate = self.offer()
        self.assertTrue(self.a._queue_guided_canvas_discovery())  # unexpired candidate reused
        self.assertIsNone(self.guide.request)
        self.a.run_guided_action()
        self.assertEqual(self.a.root.visibility, 'iconic')
        ok, discover = self.complete(deepcopy(candidate))
        self.assertTrue(ok)
        self.assertEqual(self.a.root.visibility, 'zoomed')
        self.assertIs(discover.call_args.kwargs['previous'], candidate)
        self.assertEqual(discover.call_args.kwargs['preferred_handle'], 25)
        self.assertEqual(self.a.corners, [(100, 150), (700, 550)])
        self.a._browser_drawing_region(require_verified=True)
        self.assertEqual(self.a.color_session_cache, {})
        self.a.save_settings.assert_called_once()
        self.a.start_full_drawing.assert_not_called()
        self.a.run_one_click_setup_verify.assert_not_called()
        self.assertEqual(self.a.guided_setup_state()['stage'], 'calibration')
        self.a.run_guided_action()
        self.a.run_one_click_setup_verify.assert_called_once()

    def test_different_process_or_changed_box_cannot_replace_proposal(self):
        for mutate in (lambda r: r['target_meta'].update(target_pid=124),
                       lambda r: r.update(canvas_box=(101, 150, 700, 550))):
            with self.subTest(mutate=mutate):
                self.setUp()
                revised = deepcopy(self.offer())
                mutate(revised)
                self.a.run_guided_action()
                self.assertFalse(self.complete(revised)[0])
                self.assertEqual(self.a.corners, [])
                self.a.save_settings.assert_not_called()
                self.assertEqual(self.a.guided_setup_state()['stage'], 'canvas')

    def test_pending_old_worker_does_not_replace_new_profile_or_clear_new_request(self):
        a, g = self.a, self.guide
        a._queue_guided_canvas_discovery()
        previous = g.request
        g.worker = previous
        a._cancel_guided_canvas_discovery()
        a.game.set('Microsoft Paint')
        a._queue_guided_canvas_discovery()
        latest = g.request
        a.root.fire(g.after)
        self.assertIs(g.worker, previous)
        self.assertFalse(a._handle_event('guided_canvas_complete', (previous, observation(), None)))
        self.assertIs(g.request, latest)
        self.assertIsNone(g.worker)
        self.assertTrue(self.complete(observation('microsoft-paint'))[0])
        self.assertIn('Microsoft Paint', a.guided_setup_state()['target_text'])

    def test_stop_and_timeout_restore_window_and_reject_already_queued_result(self):
        for abort in ('stop', 'timeout', 'source replaced', 'manual area'):
            with self.subTest(abort=abort):
                self.setUp()
                candidate = self.offer()
                self.a.run_guided_action()
                r = self.guide.request
                if abort == 'stop':
                    self.guide.signal_stop()
                elif abort == 'timeout':
                    self.a.root.fire(self.guide.timeout_after)
                elif abort == 'source replaced':
                    self.a.original = object()
                else:
                    self.a.corners = [(2, 3), (20, 30)]
                self.assertFalse(self.a._finish_guided_canvas_discovery(r, candidate, None))
                self.assertEqual(self.a.root.visibility, 'zoomed')
                self.a.save_settings.assert_not_called()
                self.a.start_full_drawing.assert_not_called()

    def test_keyboard_stop_reopens_guide_without_waiting_for_a_native_capture(self):
        self.a.run_guided_action()
        pending = self.guide.request
        self.guide.worker = pending
        self.guide.signal_stop()
        self.assertEqual(self.a.root.visibility, 'iconic')
        self.guide.consume_stop()
        self.assertEqual(self.a.root.visibility, 'zoomed')
        self.assertIsNone(self.guide.request)
        self.assertTrue(pending.cancelled())
        self.assertFalse(self.a._finish_guided_canvas_discovery(pending, observation(), None))
        self.assertIsNone(self.guide.worker)

    def test_target_owner_and_scale_required_before_offering_a_canvas(self):
        for field, value in (('target_pid', 0), ('target_thread', None), ('dpi', 8192)):
            with self.subTest(field=field):
                self.a._queue_guided_canvas_discovery()
                payload = observation()
                payload['target_meta'][field] = value
                self.assertFalse(self.complete(payload)[0])
                self.assertEqual(self.a.guided_setup_state()['stage'], 'canvas')

    def test_draw_preflight_rejects_recycled_handle_before_browser_palette_setup(self):
        candidate = self.offer()
        self.a.run_guided_action()
        self.complete(candidate)
        changed = dict(candidate['target_meta'], target_pid=999)
        with patch('TargetCapture.probe_handle_isolated', return_value=changed), \
                patch.object(DrawBotApp, '_auto_recalibrate_browser_from_meta') as recalibrate:
            with self.assertRaisesRegex(ValueError, 'confirmed drawing window changed'):
                self.a._refresh_target_for_draw()
        recalibrate.assert_not_called()

    def test_final_action_keeps_separate_confirmation_and_refreshes_after_modal(self):
        a = self.a
        payload = self.offer()
        a.run_guided_action()
        self.complete(payload)
        a.palette_ready = True
        self.assertEqual(a.guided_setup_state()['stage'], 'unlock')
        a.run_guided_action()
        a.unlock_full_drawing.assert_called_once()
        a.start_full_drawing.assert_not_called()
        a._full_draw_unlocked = lambda: True
        self.assertEqual(a.guided_setup_state()['stage'], 'ready')
        for callback in (lambda *args, **kwargs: False,
                         lambda *args, **kwargs: (self.guide.signal_stop() or True)):
            with patch('GuidedSetupController.messagebox.askyesno', side_effect=callback):
                a.run_guided_action()
            a.start_full_drawing.assert_not_called()
        with patch('GuidedSetupController.messagebox.askyesno', return_value=True):
            a.run_guided_action()
        a.start_full_drawing.assert_called_once()

    def test_manual_profile_and_advanced_never_queue_background_scan(self):
        self.a.game.set('Other drawing app')
        self.assertFalse(self.a._queue_guided_canvas_discovery())
        self.a.set_boundary = Mock()
        self.a.run_guided_action()
        self.a.set_boundary.assert_called_once()
        self.a.game.set('Skribbl.io')
        self.a.ui_mode.set('Advanced')
        self.assertFalse(self.a._queue_guided_canvas_discovery())
        self.assertFalse(self.a.run_guided_action())

    def test_changed_browser_title_stops_before_arming_and_before_next_guarded_operation(self):
        from GuidedCanvasDiscovery import _title_fingerprint
        from ScreenGuard import GuardedMouse
        a = self.a
        a.stop = threading.Event()
        candidate = observation()
        candidate['_window_title_fingerprint'] = _title_fingerprint('Round A - skribbl.io')
        a._queue_guided_canvas_discovery()
        self.complete(candidate)
        a.run_guided_action()
        self.complete(candidate)
        meta = candidate['target_meta']
        monitor = Mock()
        monitor.active.return_value = True
        monitor.rectangle.return_value = meta['rect']
        monitor.client_rectangle.return_value = meta['client_rect']
        monitor.dpi.return_value = meta['dpi']
        monitor._process_identity.return_value = (meta['target_pid'], meta['target_thread'])
        mouse = Mock()
        with patch('GuidedCanvasDiscovery._window_title', return_value='Round B - skribbl.io') as read, \
                patch('GuidedSetupController.time.monotonic', return_value=100) as clock:
            guarded = GuardedMouse(mouse, monitor, a.target_window, identity_check=self.guide.browser_identity_check())
            with self.assertRaisesRegex(InterruptedError, 'document or tab changed'):
                guarded.prepare_target(a.stop, lambda _: None, lambda *args: None)
            monitor.activate.assert_not_called()
            mouse.arm_input.assert_not_called()
            read.return_value = 'Round A - skribbl.io'
            guarded.prepare_target(a.stop, lambda _: None, lambda *args: None)
            mouse.arm_input.assert_called_once()
            checks = read.call_count
            for _ in range(20):
                guarded.check()
            self.assertEqual(read.call_count, checks)
            clock.return_value = 100.36
            read.return_value = 'Round B - skribbl.io'
            with self.assertRaisesRegex(InterruptedError, 'document or tab changed'):
                guarded.move(120, 160)
            mouse.move.assert_not_called()
        self.assertNotIn('fingerprint', str(a.saved_area))

    def test_guided_paint_preparation_cannot_open_or_prepare_replacement_window(self):
        a = self.a
        a.game.set('Microsoft Paint')
        a.calibration_path = 'paint-colors.json'
        a.stop = SimpleNamespace(is_set=lambda: False, wait=lambda delay: False)
        a.paint_tool = Var('Auto (recommended)')
        a.brush_px = Var('1')
        self.assertTrue(a._queue_guided_canvas_discovery())
        candidate = observation('microsoft-paint')
        self.complete(candidate)
        a.run_guided_action()
        self.complete(candidate)
        a.begin_worker = lambda label, work: work()
        with patch('GuidedCanvasDiscovery.discover_guided_canvas', side_effect=ValueError('window changed')), \
                patch('PaintPreparation.ensure_paint') as launch, \
                patch('PaintPreparation.prepare_tool_controls') as prepare:
            with self.assertRaisesRegex(ValueError, 'window changed'):
                DrawBotApp.auto_calibrate_paint_tools(a, start_after=True)
        launch.assert_not_called()
        prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
