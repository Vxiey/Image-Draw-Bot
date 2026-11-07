"""Complete RT12 at capture, brush-patch and independent setup-check callers."""
from contextlib import ExitStack
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from BrowserBrushSize import capture_control_patch
from DrawBot import DrawBotApp, grab_area
from test_v148_application_batch14_browser_start import NoWaitEvent
from test_v148_ui_lifecycle_batch02 import ui_app


class CaptureOwnershipCompletionTests(unittest.TestCase):
    def test_rgb_capture_ownership_is_transferred_without_a_second_image(self):
        for capture, size in ((lambda: grab_area((5, 7, 20, 30)), (20, 30)),
                              (lambda: capture_control_patch((40, 50)), (37, 37))):
            with self.subTest(size=size):
                raw = Image.new('RGB', size, (12, 23, 34))
                with patch('PIL.ImageGrab.grab', return_value=raw), \
                        patch.object(raw, 'convert', wraps=raw.convert) as convert:
                    owned = capture()
                self.assertIs(owned, raw)
                convert.assert_not_called()
                self.assertEqual(owned.getpixel((0, 0)), (12, 23, 34))
                owned.close()

    def test_conversion_failure_closes_the_capture_even_with_retained_traceback(self):
        for capture, size in ((lambda: grab_area((5, 7, 20, 30)), (20, 30)),
                              (lambda: capture_control_patch((40, 50)), (37, 37))):
            with self.subTest(size=size):
                raw = Image.new('RGBA', size)
                failure = ValueError('injected RGB conversion failure')
                with patch('PIL.ImageGrab.grab', return_value=raw), \
                        patch.object(raw, 'convert', side_effect=failure):
                    try:
                        capture()
                    except ValueError as error:
                        self.assertIs(error, failure)
                    else:
                        self.fail('Conversion failure did not propagate.')
                self.assertIsNotNone(failure.__traceback__)
                with self.assertRaises(ValueError):
                    raw.getpixel((0, 0))

    def test_setup_verification_closes_captures_on_success_failure_and_stop(self):
        for outcome in ('success', 'failure', 'stop'):
            with self.subTest(outcome=outcome), ExitStack() as stack:
                app = ui_app()
                stack.callback(app.original.close)
                app.stop = NoWaitEvent()
                app.events = queue.Queue()
                app.calibration_path = Path('unused-verification.json')
                app.one_click_setup_verify_pending = {
                    'profile_name': 'Gartic Phone', 'profile_key': 'gartic-phone', 'mode': 'browser'}
                app.one_click_setup_verify_payload = {
                    'target_meta': {'handle': 1, 'rect': (0, 0, 100, 100),
                                    'client_rect': (0, 0, 100, 100)},
                    'canvas_box': (10, 10, 80, 80)}
                app.begin_worker = lambda activity, work: work() or True
                monitor = stack.enter_context(patch('ScreenGuard.WindowMonitor')).return_value
                monitor.activate.return_value = True
                monitor.rectangle.return_value = (0, 0, 100, 100)
                monitor.client_rectangle.return_value = (0, 0, 100, 100)
                monitor.dpi.return_value = 96
                raw = Image.new('RGBA', (100, 100), (12, 23, 34, 255))
                stack.enter_context(patch('PIL.ImageGrab.grab', return_value=raw))
                result = Mock()
                result.as_dict.return_value = {'passed': True}
                seen = []
                failure = ValueError('injected verifier failure')
                def verify(*args, screenshot, **kwargs):
                    seen.append(screenshot)
                    self.assertEqual(screenshot.getpixel((0, 0)), (12, 23, 34))
                    if outcome == 'failure':
                        raise failure
                    if outcome == 'stop':
                        app.stop.set()
                    return result
                stack.enter_context(patch('OneClickSetupVerification.verify_browser_live', side_effect=verify))
                if outcome == 'stop':
                    with self.assertRaises(InterruptedError):
                        DrawBotApp._start_one_click_setup_verification(app)
                    self.assertTrue(app.events.empty())
                else:
                    self.assertTrue(DrawBotApp._start_one_click_setup_verification(app))
                    event, payload = app.events.get_nowait()
                    self.assertEqual(event, 'one_click_setup_verification_complete')
                    self.assertEqual(payload['passed'], outcome == 'success')
                for image in (raw, *seen):
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))
                self.assertEqual(app.original.getpixel((0, 0)), (255, 0, 0, 255))


if __name__ == '__main__':
    unittest.main()
