"""Paint spectrum search against shipped screenshots and the scalar oracle.

Only the read-only desktop capture boundary is substituted. No image is drawn
or saved: the controller searches pixels already shipped with the application.
"""
from contextlib import closing
import gc
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import ScreenGuard as guard_module


ROOT = Path(__file__).resolve().parent
SCREENSHOT = ROOT / 'assets' / 'image-draw-bot-app-screenshot.webp'


def scalar_spectrum(image, expected, max_samples=70000):
    """Historical row-major coarse/refinement oracle, independent of tiling."""
    width, height = image.size
    stride = max(1, math.ceil(math.sqrt(width * height / max(1, int(max_samples)))))
    best = None
    for y in range(0, height, stride):
        for x in range(0, width, stride):
            rgb = image.getpixel((x, y))
            error = guard_module.GuardedMouse._rgb_error(rgb, expected)
            if best is None or error < best[0]:
                best = (error, x, y, rgb)
    radius = max(2, stride + 1)
    _, bx, by, _ = best
    for y in range(max(0, by-radius), min(height, by+radius+1)):
        for x in range(max(0, bx-radius), min(width, bx+radius+1)):
            rgb = image.getpixel((x, y))
            error = guard_module.GuardedMouse._rgb_error(rgb, expected)
            if error < best[0]:
                best = (error, x, y, rgb)
    error, x, y, rgb = best
    return (x, y), rgb, error


class SpectrumSearchTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.open(SCREENSHOT)
        self.image.load()
        self.addCleanup(self.image.close)
        self.target = (123, (-2000, -2000, 2000, 2000))
        self.checked = []
        monitor = SimpleNamespace(rectangle=lambda _handle: self.target[1],
            verify_modal=lambda target, point: self.checked.append((target, point)))
        self.mouse = SimpleNamespace(get_position=lambda: (0, 0))
        self.guard = guard_module.GuardedMouse(self.mouse, monitor, self.target)

    def scan(self, expected, max_samples=70000, origin=(-350, 45), reverse=False):
        first = origin
        last = (origin[0] + self.image.width - 1, origin[1] + self.image.height - 1)
        if reverse:
            first, last = last, first
        capture = self.image.copy()
        with patch('PIL.ImageGrab.grab', return_value=capture):
            result = self.guard.calibrated_modal_nearest_color_rect(
                first, last, expected, max_samples=max_samples)
        with self.assertRaises(ValueError):
            capture.getpixel((0, 0))
        return result

    def test_public_search_retains_exact_historical_coordinates_rgb_and_error(self):
        for expected, budget, reverse in (
                ((121, 79, 201), 70000, False),
                ((0, 0, 0), 70000, True),
                ((255, 255, 255), 10000, False),
                ((240, 15, 24), 2500, True),
                ((51, 131, 78), 1, False),
                ((-10, 300, 40), 70000, False)):
            with self.subTest(rgb=expected, budget=budget, reverse=reverse):
                point, rgb, error = scalar_spectrum(self.image, expected, budget)
                self.assertEqual(self.scan(expected, budget, reverse=reverse),
                    ((point[0] - 350, point[1] + 45), rgb, error))
        self.assertEqual(len(self.checked), 30)
        self.assertTrue(all(target == self.target for target, _point in self.checked))

    def test_large_real_capture_avoids_pixelwise_python_reads_with_same_result(self):
        expected = (121, 79, 201)
        reference = scalar_spectrum(self.image, expected)
        getpixel = Image.Image.getpixel
        calls = []
        def read(image, point):
            calls.append(point)
            return getpixel(image, point)
        with patch.object(Image.Image, 'getpixel', new=read):
            actual = self.scan(expected, origin=(0, 0))
        self.assertEqual(actual, reference)
        self.assertLess(len(calls), 256,
            'The 31,440-point field should use bounded numeric strips, not per-pixel calls.')

    def test_tiny_existing_crop_keeps_scalar_path_without_array_exports(self):
        with closing(self.image.crop((10, 10, 18, 18))) as small:
            expected = scalar_spectrum(small, (80, 120, 160))
            with patch.object(guard_module, '_sample_rgb') as sample, \
                    patch.object(np, 'asarray', side_effect=AssertionError('unnecessary export')):
                sample.return_value.__enter__.return_value = small
                actual = self.guard.calibrated_modal_nearest_color_rect(
                    (20, 30), (27, 37), (80, 120, 160))
            self.assertEqual(actual, ((expected[0][0] + 20, expected[0][1] + 30),
                                     expected[1], expected[2]))

    def test_strip_exports_are_bounded_and_released_with_retained_failure(self):
        asarray = np.asarray
        exports = []
        sizes = []
        def export(value, *args, **kwargs):
            result = asarray(value, *args, **kwargs)
            if isinstance(value, Image.Image):
                exports.append(weakref.ref(result))
                sizes.append(value.size)
            return result
        capture = self.image.copy()
        retained = None
        with patch('PIL.ImageGrab.grab', return_value=capture), \
                patch.object(np, 'asarray', new=export), \
                patch.object(self.guard, '_rgb_error', side_effect=RuntimeError('retained scan error')):
            try:
                self.guard.calibrated_modal_nearest_color_rect(
                    (0, 0), (self.image.width-1, self.image.height-1), (30, 50, 90))
            except RuntimeError as error:
                retained = error
        self.assertIsNotNone(retained)
        self.assertTrue(exports)
        self.assertTrue(all(height <= 64 for _width, height in sizes))
        gc.collect()
        self.assertTrue(all(ref() is None for ref in exports))
        with self.assertRaises(ValueError):
            capture.getpixel((0, 0))

    def test_equal_integer_scores_keep_scalar_rounding_and_prior_coarse_winner(self):
        # Numeric RGB records only; this adapter creates no Pillow image and
        # never renders, displays or saves a raster. These distinct colours
        # have equal mathematical scores but different scalar float results.
        class NumericRgbRecords:
            def __init__(self, values):
                self.values = values
            def getpixel(self, point):
                x, y = point
                return tuple(map(int, self.values[y, x]))
            def crop(self, bounds):
                left, top, right, bottom = bounds
                return NumericRgbRecords(self.values[top:bottom, left:right])
            def __array__(self, dtype=None, copy=None):
                return np.asarray(self.values, dtype=dtype)
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass

        expected = (100, 100, 100)
        higher = (100, 101, 136)
        lower = (100, 112, 123)
        metric = guard_module.GuardedMouse._rgb_error
        score = lambda rgb: sum((channel-target)**2*weight for channel, target, weight
                                in zip(rgb, expected, (30, 59, 11)))
        self.assertEqual(score(higher), 14315)
        self.assertEqual(score(lower), 14315)
        self.assertLess(metric(lower, expected), metric(higher, expected))
        bounds = (2, 3, 29, 139)  # 3,672 samples: offset, non-scalar search.
        for second_y in (50, 109):  # Same strip, then different strips.
            for order in ((higher, lower), (lower, higher)):
                with self.subTest(second_y=second_y, order=order):
                    values = np.full((140, 30, 3), 255, dtype=np.uint8)
                    points = ((3, 5), (12, second_y))
                    for point, rgb in zip(points, order):
                        values[point[1], point[0]] = rgb
                    grid = NumericRgbRecords(values)
                    point = points[order.index(lower)]
                    winner = (metric(lower, expected), *point, lower)
                    self.assertEqual(guard_module._nearest_rgb_grid(
                        grid, bounds, 1, expected, metric), winner)
                    coarse_point = (20, 120)
                    for coarse_rgb in (higher, lower):
                        values[coarse_point[1], coarse_point[0]] = coarse_rgb
                        coarse = (metric(coarse_rgb, expected), *coarse_point, coarse_rgb)
                        # A strictly better scalar result replaces the coarse
                        # winner; an equal earlier refinement point cannot.
                        self.assertEqual(guard_module._nearest_rgb_grid(
                            grid, bounds, 1, expected, metric, coarse),
                            coarse if coarse_rgb == lower else winner)

    def test_modal_ownership_failure_prevents_screen_capture(self):
        self.guard.monitor.verify_modal = lambda *_: (_ for _ in ()).throw(
            InterruptedError('wrong foreground owner'))
        with patch('PIL.ImageGrab.grab') as grab, self.assertRaises(InterruptedError):
            self.guard.calibrated_modal_nearest_color_rect((10, 20), (600, 300), (20, 40, 60))
        grab.assert_not_called()

    def test_numeric_allocation_failure_retains_exact_scalar_search_and_ownership(self):
        expected = (121, 79, 201)
        reference = scalar_spectrum(self.image, expected)
        asarray = np.asarray
        for failed_strip in (1, 3):
            with self.subTest(failed_strip=failed_strip):
                calls = [0]
                def export(value, *args, **kwargs):
                    if isinstance(value, Image.Image):
                        calls[0] += 1
                        if calls[0] == failed_strip:
                            raise MemoryError('No room for optional spectrum export')
                    return asarray(value, *args, **kwargs)
                with patch.object(np, 'asarray', new=export):
                    actual = self.scan(expected, origin=(0, 0))
                self.assertEqual(actual, reference)
                self.assertEqual(calls[0], failed_strip)


if __name__ == '__main__':
    unittest.main()
