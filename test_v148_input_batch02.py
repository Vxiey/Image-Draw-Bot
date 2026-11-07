"""Native input boundary and asynchronous focus regression fixtures; no real input."""
import ctypes
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from ScreenGuard import GuardedMouse, WindowMonitor, _grab_rgb
from WindowsMouse import WindowsMouse


TARGET = (10, (0, 0, 500, 500))


class Mouse:
    def __init__(self):
        self.position = (20, 20)
        self.actions = []

    def get_position(self):
        return self.position

    def move(self, x, y):
        self.position = (x, y)
        self.actions.append(('move', x, y))

    def press(self):
        self.actions.append(('press',))

    def release(self):
        self.actions.append(('release',))


class Monitor:
    def rectangle(self, handle):
        return TARGET[1]

    def client_rectangle(self, handle):
        return (0, 0, 500, 500)

    def verify(self, target, point):
        if not (0 <= point[0] < 500 and 0 <= point[1] < 500):
            raise InterruptedError('Outside target')

    verify_modal = verify

    def color(self, point):
        return (20, 30, 40)


class GuardRaceTests(unittest.TestCase):
    def test_overlay_retry_refreshes_actual_pointer_before_click(self):
        mouse = Mouse()
        monitor = Monitor()
        calls = []
        def verify(target, point):
            calls.append(point)
            if len(calls) == 1:
                raise InterruptedError('Stopped: another window covers the click position.')
            Monitor.verify(monitor, target, point)
        monitor.verify = verify
        with patch('ScreenGuard.time.sleep', side_effect=lambda _: setattr(mouse, 'position', (900, 900))):
            with self.assertRaises(InterruptedError):
                GuardedMouse(mouse, monitor, TARGET).click()
        self.assertEqual(calls[-1], (900, 900))
        self.assertEqual(mouse.actions, [])

    def test_live_target_callback_cannot_leave_a_stale_pointer(self):
        mouse = Mouse()
        def callback(*_):
            mouse.position = (900, 900)
        with self.assertRaises(InterruptedError):
            GuardedMouse(mouse, Monitor(), TARGET, live_target_check=callback).click()
        self.assertEqual(mouse.actions, [])

    def test_palette_sampling_rechecks_foreground_before_press(self):
        mouse = Mouse()
        monitor = Monitor()
        monitor.focus = True
        def colors(points):
            monitor.focus = False
            return [(20, 30, 40)]
        def verify(*_):
            if not monitor.focus:
                raise InterruptedError('wrong window')
        monitor.colors, monitor.verify = colors, verify
        with self.assertRaises(InterruptedError):
            GuardedMouse(mouse, monitor, TARGET, {(2, 2): (20, 30, 40)}).click()
        self.assertEqual(mouse.actions, [])

    def test_cancellation_during_foreground_probe_does_not_arm(self):
        stop = threading.Event()
        mouse = SimpleNamespace(arm_input=Mock())
        def active(_):
            stop.set()
            return True
        monitor = SimpleNamespace(activate=lambda _: None, active=active)
        with self.assertRaises(InterruptedError):
            GuardedMouse(mouse, monitor, TARGET).prepare_target(stop, lambda _: None, lambda *_: None)
        mouse.arm_input.assert_not_called()

    def test_failed_rearm_revokes_prior_arming(self):
        mouse = WindowsMouse.__new__(WindowsMouse)
        mouse._input_armed = True
        mouse.buttons_down = lambda: ('left',)
        with self.assertRaises(InterruptedError):
            mouse.arm_input()
        self.assertFalse(mouse.input_armed)

    def test_palette_is_sampled_as_one_batch(self):
        monitor = Monitor()
        monitor.colors = Mock(return_value=[(20, 30, 40)] * 20)
        monitor.color = Mock(side_effect=AssertionError('per-pixel capture'))
        palette = {(i, 10): (20, 30, 40) for i in range(20)}
        guard = GuardedMouse(Mouse(), monitor, TARGET, palette)
        guard.verify_palette_layout()
        monitor.colors.assert_called_once_with(list(palette))
        self.assertTrue(guard.palette_verified)

    def test_partial_palette_sample_cannot_be_marked_verified(self):
        monitor = Monitor()
        monitor.colors = lambda _: []
        guard = GuardedMouse(Mouse(), monitor, TARGET, {(5, 5): (20, 30, 40)})
        with self.assertRaises(InterruptedError):
            guard.verify_palette_layout()
        self.assertFalse(guard.palette_verified)


class WindowBoundaryTests(unittest.TestCase):
    def monitor(self):
        monitor = WindowMonitor.__new__(WindowMonitor)
        monitor.rectangle = lambda _: TARGET[1]
        monitor.client_rectangle = lambda _: (0, 0, 500, 500)
        def process(handle, pid):
            pid._obj.value = 7654321
            return 123
        monitor.api = SimpleNamespace(GetWindowThreadProcessId=process)
        monitor.at = lambda _: 10
        return monitor

    def test_window_capture_detects_cover_on_other_diagonal(self):
        monitor = self.monitor()
        monitor.at = lambda p: 99 if p == (97, 2) else 10
        with self.assertRaisesRegex(ValueError, 'covered'):
            monitor.capture((0, 0, 100, 100))

    def test_capture_does_not_accept_missing_process_identity(self):
        monitor = self.monitor()
        monitor.api.GetWindowThreadProcessId = lambda *_: 0
        with self.assertRaisesRegex(ValueError, 'process'):
            monitor.capture((0, 0, 100, 100))

    def test_capture_uses_one_client_rectangle_snapshot(self):
        monitor = self.monitor()
        monitor.client_rectangle = Mock(return_value=(0, 0, 500, 500))
        self.assertEqual(monitor.capture((0, 0, 100, 100)), TARGET)
        monitor.client_rectangle.assert_called_once_with(10)

    def test_native_window_probe_rejects_wrapping_coordinates(self):
        monitor = WindowMonitor.__new__(WindowMonitor)
        monitor.api = SimpleNamespace(WindowFromPoint=Mock(), GetAncestor=Mock())
        for point in ((2**32 + 5, 5), (5, float('inf')), (-2**31 - 1, 0)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                monitor.at(point)
        monitor.api.WindowFromPoint.assert_not_called()

    def test_negative_monitor_coordinates_remain_valid(self):
        monitor = WindowMonitor.__new__(WindowMonitor)
        seen = []
        monitor.api = SimpleNamespace(WindowFromPoint=lambda p: seen.append((p.x, p.y)) or 12,
                                      GetAncestor=lambda h, flag: h)
        self.assertEqual(monitor.at((-1920, -100)), 12)
        self.assertEqual(seen, [(-1920, -100)])


class ModalOwnershipTests(unittest.TestCase):
    def monitor(self, foreground=20, owner=10):
        monitor = WindowMonitor.__new__(WindowMonitor)
        monitor.rectangle = lambda _: TARGET[1]
        monitor.in_client_area = lambda *_: True
        monitor.at = lambda _: foreground
        monitor.api = SimpleNamespace(GetForegroundWindow=lambda: foreground,
                                      IsWindow=lambda _: True, IsWindowVisible=lambda _: True,
                                      IsIconic=lambda _: False, GetWindow=lambda *_: owner)
        return monitor

    def test_owned_dialog_is_accepted(self):
        self.monitor().verify_modal(TARGET, (30, 30))

    def test_unrelated_foreground_is_rejected(self):
        with self.assertRaisesRegex(InterruptedError, 'does not belong'):
            self.monitor(owner=0).verify_modal(TARGET, (30, 30))

    def test_ownership_cycle_terminates_safely(self):
        with self.assertRaises(InterruptedError):
            self.monitor(owner=20).verify_modal(TARGET, (30, 30))

    def test_foreign_overlay_cannot_receive_modal_click(self):
        mouse = Mouse()
        monitor = self.monitor()
        monitor.at = lambda _: 99
        with self.assertRaises(InterruptedError):
            GuardedMouse(mouse, monitor, TARGET).calibrated_modal_click((30, 30))
        self.assertEqual(mouse.actions, [])

    def test_focus_change_during_modal_move_prevents_press(self):
        mouse = Mouse()
        monitor = self.monitor()
        def move(x, y):
            mouse.position = (x, y)
            monitor.api.GetForegroundWindow = lambda: 99
            monitor.api.GetWindow = lambda *_: 0
        mouse.move = move
        with self.assertRaises(InterruptedError):
            GuardedMouse(mouse, monitor, TARGET).calibrated_modal_click((30, 30))
        self.assertEqual(mouse.actions, [])

    def test_legacy_monitor_without_verifier_fails_closed(self):
        monitor = SimpleNamespace(rectangle=lambda _: TARGET[1])
        mouse = Mouse()
        with self.assertRaisesRegex(InterruptedError, 'cannot verify'):
            GuardedMouse(mouse, monitor, TARGET).calibrated_modal_click((30, 30))
        self.assertEqual(mouse.actions, [])


class CaptureTests(unittest.TestCase):
    def test_brightness_scale_rejects_huge_capture_before_grab(self):
        with patch('PIL.ImageGrab.grab') as grab:
            with self.assertRaises(ValueError):
                GuardedMouse(Mouse(), Monitor(), TARGET).calibrated_modal_nearest_color_line(
                    (-100000, -100000), (100000, 100000), (20, 30, 40))
        grab.assert_not_called()

    def test_capture_size_mismatch_is_rejected_and_released(self):
        image = Image.new('RGB', (2, 2))
        with patch('PIL.ImageGrab.grab', return_value=image):
            with self.assertRaises(InterruptedError):
                _grab_rgb((0, 0, 5, 5))
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_capture_conversion_releases_raw_image(self):
        image = Image.new('RGBA', (5, 5), (20, 30, 40, 255))
        with patch('PIL.ImageGrab.grab', return_value=image):
            result = _grab_rgb((0, 0, 5, 5))
        self.assertEqual(result.getpixel((0, 0)), (20, 30, 40))
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))
        result.close()

    def test_sample_releases_rgb_image(self):
        image = Image.new('RGB', (5, 5), (20, 30, 40))
        with patch('PIL.ImageGrab.grab', return_value=image):
            value = GuardedMouse(Mouse(), Monitor(), TARGET).calibrated_modal_color((20, 20))
        self.assertEqual(value, (20, 30, 40))
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_snapshot_rejects_focus_change_during_capture(self):
        image = Image.new('RGB', (20, 20))
        monitor = Monitor()
        def grab(**_):
            monitor.verify = Mock(side_effect=InterruptedError('focus changed'))
            return image
        with patch('PIL.ImageGrab.grab', side_effect=grab):
            with self.assertRaises(InterruptedError):
                GuardedMouse(Mouse(), monitor, TARGET).snapshot_canvas((10, 10, 20, 20))
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_margin_capture_rejects_partially_outside_canvas(self):
        with patch('PIL.ImageGrab.grab') as grab:
            with self.assertRaises(InterruptedError):
                GuardedMouse(Mouse(), Monitor(), TARGET).snapshot_canvas_with_margin((-10, 10, 100, 100))
        grab.assert_not_called()

    def test_canvas_capture_has_a_pixel_budget(self):
        with patch('PIL.ImageGrab.grab') as grab:
            with self.assertRaises(ValueError):
                GuardedMouse(Mouse(), Monitor(), TARGET).snapshot_canvas((0, 0, 100000, 100000))
        grab.assert_not_called()

    def test_empty_neighborhood_uses_measured_fallback_error(self):
        monitor = Monitor()
        monitor.colors_near = lambda *_: []
        guard = GuardedMouse(Mouse(), monitor, TARGET)
        with patch('ScreenGuard.time.sleep'):
            result = guard.inspect_ink_segment((10, 10), (10, 10), (20, 30, 40))
            guard.verify_fill((10, 10), (20, 30, 40))
        self.assertTrue(result['matched'])
        self.assertEqual(result['error'], 0)
        self.assertEqual(result['sample_count'], 1)
        self.assertEqual(result['confidence'], 100)

    def test_settle_rechecks_target_before_accepting_a_sample(self):
        monitor = Monitor()
        monitor.colors_near = Mock(return_value=[(255, 255, 255)])
        def sleep(_):
            monitor.verify = Mock(side_effect=InterruptedError('focus changed'))
            monitor.colors_near.return_value = [(20, 30, 40)]
        with patch('ScreenGuard.time.sleep', side_effect=sleep):
            with self.assertRaises(InterruptedError):
                GuardedMouse(Mouse(), monitor, TARGET).inspect_ink_segment((10, 10), (10, 10), (20, 30, 40))
        self.assertEqual(monitor.colors_near.call_count, 1)


if __name__ == '__main__':
    unittest.main()
