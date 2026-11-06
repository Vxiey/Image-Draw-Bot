"""Independent visible-pixel checks for the classic colour planners."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import AdaptiveDetail as detail
import AdvancedColor as color
from TimeBudget import resolve_target_stroke_count


def visible(image):
    with Image.new('RGBA', image.size, 'white') as canvas:
        canvas.alpha_composite(image)
        return np.asarray(canvas.convert('RGB')).copy()


def raster(groups, palette, size, order=None):
    result = Image.new('RGB', size, (255, 0, 255))
    draw = ImageDraw.Draw(result)
    for index in (range(len(groups)) if order is None else order):
        for stroke in groups[index]:
            draw.line(stroke, fill=palette[index])
    return result


class AdaptiveAlphaTests(unittest.TestCase):
    def test_uniform_partial_alpha_is_not_whitened_twice(self):
        for alpha in (0, 1, 32, 128, 254, 255):
            with self.subTest(alpha=alpha), Image.new('RGBA', (12, 12), (17, 60, 90, alpha)) as source:
                for mode in ('Preserve detail', 'Balanced', 'Strong simplify'):
                    out, mask, _ = detail.apply_adaptive_detail(source, mode)
                    try:
                        np.testing.assert_array_equal(visible(out), visible(source))
                        np.testing.assert_array_equal(np.asarray(out), np.asarray(source))
                    finally:
                        out.close(); mask.close()

    def test_hard_protected_translucent_edge_stays_exact(self):
        with Image.new('RGBA', (24, 24), (240, 250, 255, 180)) as source:
            ImageDraw.Draw(source).line((12, 2, 12, 21), fill=(5, 10, 15, 200), width=2)
            out, mask, _ = detail.apply_adaptive_detail(source, 'Balanced')
            try:
                protected = np.asarray(mask) == 255
                self.assertTrue(protected.any())
                np.testing.assert_array_equal(np.asarray(out)[protected], np.asarray(source)[protected])
                np.testing.assert_array_equal(np.asarray(out)[..., 3], np.asarray(source)[..., 3])
            finally:
                out.close(); mask.close()

    def test_transparent_hidden_colour_does_not_affect_visible_smoothing(self):
        rgba = np.full((16, 16, 4), (30, 50, 70, 128), np.uint8)
        rgba[::3, ::3, 3] = 0
        variant = rgba.copy(); variant[::3, ::3, :3] = (250, 0, 130)
        outputs = []
        for data in (rgba, variant):
            with Image.fromarray(data) as source:
                out, mask, _ = detail.apply_adaptive_detail(source, 'Strong simplify')
                outputs.append(visible(out)); out.close(); mask.close()
        np.testing.assert_array_equal(*outputs)

    def test_visible_delta_is_unassociated_and_stop_is_propagated(self):
        with Image.new('RGBA', (3, 2), (40, 80, 120, 128)) as source:
            with Image.fromarray(visible(source)) as before, Image.new('RGB', (3, 2), (175, 185, 205)) as after:
                out = detail._restore_source_alpha(source, before, after, lambda: False)
                try:
                    self.assertLessEqual(np.max(np.abs(visible(out).astype(int) - np.asarray(after))), 1)
                    self.assertEqual(out.getpixel((0, 0))[3], 128)
                finally:
                    out.close()
                with self.assertRaises(InterruptedError):
                    detail._restore_source_alpha(source, before, after, lambda: True)


class LayeredRasterTests(unittest.TestCase):
    # The explicit Bayer matrix is the public ordered-stipple contract, independent
    # of the implementation's run splitting and colour-batch execution order.
    bayer = np.array(((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5)))

    def test_secondary_pixels_survive_both_palette_execution_orders(self):
        for lines in (False, True):
            for palette in (((0, 0, 0), (255, 255, 255)), ((255, 255, 255), (0, 0, 0))):
                names = tuple('Black' if p[0] == 0 else 'White' for p in palette)
                swatches = [SimpleNamespace(RGB=p, name=n) for p, n in zip(palette, names)]
                with self.subTest(lines=lines, palette=palette), Image.new('RGBA', (8, 8), (90, 90, 90, 255)) as source:
                    primary, secondary, ratio, _ = color._best_layer_cached(
                        (90, 90, 90), palette, names, 'Layered color mix', 'Calibrated palette', 'Full color mix')
                    self.assertIsNotNone(secondary)
                    threshold = max(1, min(15, round(ratio * 16)))
                    mask = np.tile(self.bayer < threshold, (2, 2))
                    expected = np.empty((8, 8, 3), np.uint8)
                    expected[:] = palette[primary]; expected[mask] = palette[secondary]
                    with patch.object(color, 'allColors', swatches):
                        groups, meta = color.build_color_strokes(source, lines=lines, skip_white=False,
                            color_rendering='Layered color mix', color_layers='Full color mix')
                    self.assertEqual(meta['layered_pixels'], int(mask.sum()))
                    coverage = np.zeros((8, 8), np.int32)
                    for group in groups:
                        for x0, y, x1, _ in group:
                            coverage[y, x0:x1 + 1] += 1
                    np.testing.assert_array_equal(coverage, np.ones_like(coverage))
                    for order in ((0, 1), (1, 0)):
                        with raster(groups, palette, source.size, order) as result:
                            np.testing.assert_array_equal(np.asarray(result), expected)
                    worker = color._color_rows_worker((0, 8, source.tobytes(), lines, False,
                        'Layered color mix', 'Full color mix', 'Calibrated palette', 'Balanced', palette, names))
                    combined = [list(a) + list(b) for a, b in zip(worker[0], worker[1])]
                    self.assertEqual(groups, combined)


class BudgetSpeedAliasTests(unittest.TestCase):
    def test_all_supported_speed_aliases_have_canonical_budget(self):
        from SpeedOptimizer import LEGACY_SPEED_NAMES
        for alias, canonical in LEGACY_SPEED_NAMES.items():
            for drawing_mode in ('Dots', 'Shape paths', 'Smart paths (recommended)'):
                kwargs = dict(time_budget_mode='60 sec', effective_time_seconds=60, drawing_mode=drawing_mode)
                self.assertEqual(resolve_target_stroke_count('Auto', speed=alias, **kwargs),
                                 resolve_target_stroke_count('Auto', speed=canonical, **kwargs))


if __name__ == '__main__':
    unittest.main()
