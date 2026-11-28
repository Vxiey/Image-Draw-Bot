import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock, patch

from GuidedCanvasOutline import CanvasOutline, border_strips, outline_supported


class CanvasOutlineTests(unittest.TestCase):
    def test_borders_follow_signed_coordinates_at_100_to_200_percent(self):
        box = (-1200, -22, -1160, 8)
        for dpi in (96, 120, 144, 168, 192):
            with self.subTest(dpi=dpi):
                strips = list(border_strips(box, dpi))
                self.assertEqual(len(strips), 8)
                points = set()
                for style, (l, t, r, b) in strips:
                    self.assertIn(style, (4, 6))
                    area = {(x, y) for x in range(l, r) for y in range(t, b)}
                    self.assertFalse(points & area)
                    points.update(area)
                l, t, r, b = box
                edge = round(2*dpi/96) * 2
                expected = {(x, y) for x in range(l, r) for y in range(t, b)
                            if min(x-l, r-1-x, y-t, b-1-y) < edge}
                self.assertEqual(points, expected)

    def test_partial_native_failure_releases_every_created_strip(self):
        api = Mock()
        api.CreateWindowExW.side_effect = [201, 202, None]
        with patch('GuidedCanvasOutline.WindowMonitor'), patch.object(CanvasOutline, 'check_target'), \
                patch('GuidedCanvasOutline.private_system_library', return_value=api), \
                patch('GuidedCanvasOutline.position_verified_overlay'), self.assertRaises(OSError):
            CanvasOutline((-100, 20, -40, 70), {'dpi': 144})
        self.assertEqual([call.args[0] for call in api.DestroyWindow.call_args_list], [202, 201])

    def test_changed_target_is_rejected_by_the_native_validation(self):
        outline = CanvasOutline.__new__(CanvasOutline)
        monitor = outline.monitor = Mock()
        outline.box = (30, 30, 200, 160)
        outline.meta = {'handle': 11, 'target_pid': 12, 'target_thread': 13, 'rect': (0, 0, 400, 200),
                        'client_rect': (0, 12, 400, 200), 'dpi': 144}
        monitor._process_identity.return_value = (12, 13)
        monitor.client_rectangle.return_value = (0, 12, 400, 200)
        monitor.dpi.return_value = 144
        monitor.api.IsIconic.return_value = False
        monitor.capture.return_value = (11, (0, 0, 400, 200))
        outline.check_target()
        monitor.capture.return_value = (18, (0, 0, 400, 200))
        with self.assertRaisesRegex(ValueError, 'covering'):
            outline.check_target()
        monitor._process_identity.return_value = (12, 20)
        with self.assertRaisesRegex(ValueError, 'changed'):
            outline.check_target()
        monitor.activate.assert_not_called()

    @unittest.skipUnless(outline_supported(), 'native Windows desktop required')
    def test_native_windows_leave_foreground_unchanged_and_teardown(self):
        from WindowsSystem import private_system_library
        api = private_system_library('user32.dll')
        api.GetForegroundWindow.argtypes, api.GetForegroundWindow.restype = [], wintypes.HWND
        api.IsWindow.argtypes, api.IsWindow.restype = [wintypes.HWND], wintypes.BOOL
        api.GetWindowLongW.argtypes, api.GetWindowLongW.restype = [wintypes.HWND, ctypes.c_int], wintypes.LONG
        foreground = api.GetForegroundWindow()
        with patch.object(CanvasOutline, 'check_target'):
            outline = CanvasOutline((24, 40, 300, 180), {'dpi': 144})
        handles = list(outline.handles)
        try:
            self.assertEqual(len(handles), 8)
            self.assertEqual(api.GetForegroundWindow(), foreground)
            for handle in handles:
                self.assertTrue(api.IsWindow(handle))
                required = 0x08000000 | 0x00080000 | 0x00000020 | 0x00000080
                self.assertEqual(api.GetWindowLongW(handle, -20) & required, required)
                self.assertTrue(api.GetWindowLongW(handle, -16) & 0x08000000)  # WS_DISABLED
        finally:
            outline.close()
        self.assertTrue(all(not api.IsWindow(handle) for handle in handles))


if __name__ == '__main__':
    unittest.main()
