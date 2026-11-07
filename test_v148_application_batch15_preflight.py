"""An emergency Stop during real draw preflight survives worker handoff."""
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
from test_v148_application_batch14_browser_start import DeferredThread, NoWaitEvent, ScheduledRoot
from test_v148_ui_lifecycle_batch02 import ui_app


class DrawPreflightStopTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.app = app = ui_app()
        self.addCleanup(app.original.close)
        app.root = ScheduledRoot()
        app.stop = NoWaitEvent()
        app.paused = threading.Event()
        app.events = queue.Queue()
        app.game = Value('Gartic Phone')
        app._active_profile_name = 'Gartic Phone'
        app.paint_simple = Value(False)
        app.outline = Value(False)
        app.calibration_path = Path('unused-preflight-calibration.json')
        app.status = Value('')
        app.summary = Value('')
        app.progress = {'value': 0}
        app.mouse = Mock()
        app.worker = None
        app._refresh_target_for_draw = lambda: app.target_client_rect
        app.area = lambda: (10, 10, 80, 80)
        app.set_busy = lambda value: setattr(app, 'activity', value)
        app.begin_worker = MethodType(DrawBotApp.begin_worker, app)
        app.options = lambda: {
            'brush_px': 3, 'background_fill': 'Off', 'use_region_fill_engine': False,
            'auto_clear_canvas': False, 'unlimited_time': True, 'max_seconds': 180,
        }
        for name in ('log_event', 'log_error', 'load_calibration'):
            self.stack.enter_context(patch('DrawBot.' + name))
        self.stack.enter_context(patch('DrawBot.threading.Thread', DeferredThread))
        self.stack.enter_context(patch('DrawBot.allColors', []))
        self.screen_window = self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.guarded = self.stack.enter_context(patch('ScreenGuard.GuardedMouse'))
        self.stack.enter_context(patch('ScreenGuard.WindowMonitor'))
        self.stack.enter_context(patch.object(DrawBotApp, '_disarm_full_draw'))
        self.visual = self.stack.enter_context(patch.object(
            DrawBotApp, '_run_browser_visual_preflight', return_value=app.target_client_rect))
        self.stack.enter_context(patch('BrowserBrushSize.SUPPORTED', set()))
        self.stack.enter_context(patch('BrowserToolLayout.SUPPORTED', set()))
        self.planning = self.stack.enter_context(patch('DrawBot.build_planning_attempts',
            side_effect=InterruptedError('test stops at the planning boundary')))

    def run_draw(self, **kwargs):
        DrawBotApp.draw(self.app, user_initiated=True, **kwargs)
        if self.app.worker is not None:
            self.app.worker.run()

    def assert_stopped_before_planning(self):
        self.assertTrue(self.app.stop.is_set())
        self.planning.assert_not_called()
        self.assertFalse(self.app.mouse.method_calls)
        self.assertFalse(self.guarded.return_value.method_calls)

    def test_escape_during_visual_preflight_is_not_cleared_at_worker_start(self):
        def stop_and_return(*args, **kwargs):
            self.app.stop.set()  # The real global Esc hotkey calls Event.set directly.
            return self.app.target_client_rect
        self.visual.side_effect = stop_and_return
        self.run_draw()
        self.assert_stopped_before_planning()
        self.assertIsNone(self.app.worker)
        self.assertEqual(self.app.start_state_machine.state, 'ABORTED')

    def test_stop_during_late_settings_save_survives_handoff(self):
        self.app.save_settings.side_effect = self.app.stop.set
        self.run_draw()
        self.assert_stopped_before_planning()

    def test_new_explicit_start_can_follow_a_previous_stop(self):
        self.app.stop.set()
        self.run_draw()
        self.planning.assert_called_once()

    def test_escape_during_worker_construction_survives_the_last_handoff(self):
        def stop_during_handoff(*args, **kwargs):
            self.app.stop.set()
            return Mock()
        self.screen_window.side_effect = stop_during_handoff
        self.run_draw()
        self.assert_stopped_before_planning()
        self.assertEqual(self.app.start_state_machine.state, 'ABORTED')

    def test_dry_run_does_not_clear_stop_from_its_preflight(self):
        self.visual.side_effect = lambda *a, **k: self.app.stop.set() or self.app.target_client_rect
        self.run_draw(dry_run=True)
        self.assert_stopped_before_planning()
        self.assertIsNone(self.app.worker)

    def test_small_test_confirmation_cannot_clear_a_new_stop(self):
        with patch('DrawBot.messagebox.askokcancel',
                   side_effect=lambda *a: self.app.stop.set() or True):
            self.run_draw(test=True)
        self.assert_stopped_before_planning()

    def test_detector_interruption_aborts_and_releases_its_owned_capture(self):
        for detector, supported in (
                ('BrowserBrushSize.plan_browser_brush_size', 'BrowserBrushSize.SUPPORTED'),
                ('BrowserToolLayout.plan_browser_tools', 'BrowserToolLayout.SUPPORTED')):
            with self.subTest(detector=detector), ExitStack() as local:
                captured = Image.new('RGB', (100, 100), 'white')
                local.enter_context(patch(supported, {'gartic-phone'}))
                local.enter_context(patch('PIL.ImageGrab.grab', return_value=captured))
                local.enter_context(patch(detector, side_effect=InterruptedError('capture cancelled')))
                self.run_draw()
                self.planning.assert_not_called()
                self.assertIsNone(self.app.worker)
                self.assertEqual(self.app.start_state_machine.state, 'ABORTED')
                with self.assertRaises(ValueError):
                    captured.getpixel((0, 0))
                self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))

    def test_shared_capture_closes_after_both_fallback_detectors_before_planning(self):
        captured = Image.new('RGBA', (100, 100), (18, 27, 36, 255))
        seen = []
        def fail_detector(profile, image, *args, **kwargs):
            self.assertEqual(image.getpixel((0, 0)), (18, 27, 36))
            seen.append(image)
            raise ValueError('normal low-confidence fallback')
        with patch('BrowserBrushSize.SUPPORTED', {'gartic-phone'}), \
                patch('BrowserToolLayout.SUPPORTED', {'gartic-phone'}), \
                patch('PIL.ImageGrab.grab', return_value=captured) as grab, \
                patch('BrowserBrushSize.plan_browser_brush_size', side_effect=fail_detector), \
                patch('BrowserToolLayout.plan_browser_tools', side_effect=fail_detector):
            self.run_draw()
        grab.assert_called_once()
        self.planning.assert_called_once()
        self.assertEqual(len(seen), 2)
        self.assertIs(seen[0], seen[1])
        for image in (captured, seen[0]):
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
