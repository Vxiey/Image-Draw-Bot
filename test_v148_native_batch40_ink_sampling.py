"""Real sampling consumers retain exact verdicts and fresh target evidence."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ScreenPixelSampling as sampling
from ScreenGuard import GuardedMouse, WindowMonitor
from test_v148_native_batch25_screen_sampling import _NativeBoundary, _Library


class GroupedInkTests(unittest.TestCase):
    def boundary(self):
        native = _NativeBoundary()
        boundary = patch('ScreenPixelSampling.load_system_library', return_value=_Library(native))
        boundary.start()
        self.addCleanup(boundary.stop)
        return native

    def check_groups(self, centers, expected_transfers):
        native = self.boundary()
        groups = [[(x + dx, 20 + dy) for dy in range(-2, 3) for dx in range(-2, 3)]
                  for x in centers]
        expected = [native.rgb(*point) for group in groups for point in group]
        result = sampling.sample_screen_color_groups(groups)
        self.assertEqual(result, expected)
        names = [name for name, args in native.calls]
        self.assertEqual(names.count('BitBlt'), expected_transfers)
        self.assertEqual(names.count('GetPixel'), 0)
        self.assertEqual(names.count('GetDC'), names.count('ReleaseDC'))
        self.assertEqual(native.buffers, {})

    def test_nearby_patches_share_one_transfer_and_keep_duplicate_pixels(self):
        self.check_groups((-20, -15, -10, -10, 0), 1)

    def test_distant_patches_keep_bulk_reads_instead_of_becoming_scalar(self):
        self.check_groups((-1600, -800, 0, 800, 1600), 5)

    def test_cross_monitor_union_falls_back_to_original_individual_patches(self):
        native = self.boundary()

        def monitor_info(handle, pointer):
            pointer._obj.monitor = sampling._Rect(-1920, -200, 0, 1080)
            return 1

        native.GetMonitorInfoW = monitor_info
        centers = (-30, -20, -10, 10, 20)
        groups = [[(x + dx, 20 + dy) for dy in range(-2, 3) for dx in range(-2, 3)]
                  for x in centers]
        result = sampling.sample_screen_color_groups(groups)
        self.assertEqual(result, [native.rgb(*point) for group in groups for point in group])
        names = [name for name, args in native.calls]
        self.assertEqual(names.count('BitBlt'), 3)
        self.assertEqual(names.count('GetPixel'), 50)
        self.assertEqual(names.count('GetDC'), names.count('ReleaseDC'))
        self.assertEqual(native.buffers, {})

    def test_optional_union_failure_preserves_each_usable_patch(self):
        native = self.boundary()
        groups = [[(x + dx, 20 + dy) for dy in range(-2, 3) for dx in range(-2, 3)]
                  for x in (-30, -20, -10)]
        original = sampling._compact_bounds
        calls = [0]

        def bounds(*args):
            calls[0] += 1
            if calls[0] == 1:
                raise MemoryError('optional union')
            return original(*args)

        with patch('ScreenPixelSampling._compact_bounds', side_effect=bounds):
            result = sampling.sample_screen_color_groups(groups)
        self.assertEqual(result, [native.rgb(*point) for group in groups for point in group])
        self.assertEqual(sum(name == 'BitBlt' for name, args in native.calls), 3)
        self.assertEqual(native.buffers, {})

    def test_ink_and_fill_reject_focus_loss_during_matching_sample(self):
        for kind in ('ink', 'fill'):
            with self.subTest(kind=kind):
                focused = [True]

                def verify(*args):
                    if not focused[0]:
                        raise InterruptedError('target lost focus during capture')

                def sample(*args):
                    focused[0] = False
                    return [(20, 30, 40)]

                monitor = SimpleNamespace(verify=verify, colors_near=sample)
                guard = GuardedMouse(SimpleNamespace(get_position=lambda: (20, 20)),
                                     monitor, (10, (0, 0, 500, 500)))
                with self.assertRaisesRegex(InterruptedError, 'lost focus'):
                    if kind == 'ink':
                        guard.inspect_ink_segment((20, 20), (20, 20), (20, 30, 40))
                    else:
                        guard.verify_fill((20, 20), (20, 30, 40))


if __name__ == '__main__':
    unittest.main()
