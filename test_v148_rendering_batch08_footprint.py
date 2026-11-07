from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import AdaptiveRegionHybrid as hybrid
from test_v148_rendering_batch07_transparency import standard_options
from test_v148_rendering_batch06_canvas import close_plan


def reference(mask, brush, every):
    h, w = mask.shape
    before, after = (brush - 1) // 2, brush // 2
    out = np.zeros((h, w), bool)
    operation = all if every else any
    for y in range(h):
        for x in range(w):
            out[y, x] = operation(0 <= yy < h and 0 <= xx < w and bool(mask[yy, xx])
                for yy in range(y - before, y + after + 1)
                for xx in range(x - before, x + after + 1))
    return out


def browser_settings():
    return standard_options(extra_fast=True, extra_fast_v2=True,
        profile_name='Gartic Phone', profile_key='gartic-phone', skip_white=True, brush_px=1,
        browser_brush_plan={'target_position': (1, 1), 'confidence': .99,
            'nominal_sizes': [1, 4, 16, 28], 'verified_sizes': [1, 4, 16, 28],
            'control_positions': [(1, 1), (2, 1), (3, 1), (4, 1)], 'safe_guard_px': 4})


class SquareFootprintTests(unittest.TestCase):
    def test_both_operators_match_independent_pixel_footprints(self):
        rng = np.random.default_rng(1480803)
        for shape in ((1, 1), (1, 11), (12, 1), (13, 17)):
            masks = [np.zeros(shape, bool), np.ones(shape, bool), rng.random(shape) > .25]
            for mask in masks:
                for brush in (1, 2, 3, 4, 7, 16):
                    for every, operation in ((True, hybrid._eroded_centers), (False, hybrid._centers_touching_mask)):
                        with self.subTest(shape=shape, brush=brush, every=every):
                            original = mask.copy()
                            mask.flags.writeable = False
                            actual = operation(mask, brush)
                            np.testing.assert_array_equal(actual, reference(mask, brush, every))
                            np.testing.assert_array_equal(mask, original)
                            self.assertFalse(np.shares_memory(actual, mask))

    def test_chunk_boundaries_and_noncontiguous_input_keep_exact_edges(self):
        for shape in ((65, 1027), (1027, 65)):
            mask = np.ones(shape, bool)
            mask[::7, ::11] = False
            for source in (mask, mask[::-1, ::-1], mask.T):
                for brush in (2, 7, 28):
                    for every, operation in ((True, hybrid._eroded_centers), (False, hybrid._centers_touching_mask)):
                        actual = operation(source, brush)
                        # A separate padded sliding-window reduction tests the
                        # complete raster across both 16-row/1024-column cuts.
                        before, after = (brush - 1) // 2, brush // 2
                        padded = np.pad(source, ((before, after), (before, after)), constant_values=False)
                        view = np.lib.stride_tricks.sliding_window_view(padded, (brush, brush))
                        expected = (np.all if every else np.any)(view, axis=(-2, -1))
                        np.testing.assert_array_equal(actual, expected)

    def test_temporary_numeric_work_is_bounded_and_stop_is_polled_inside_passes(self):
        shapes = []
        zeros = hybrid.np.zeros
        def observed(shape, *args, **kwargs):
            if kwargs.get('dtype') == np.int64:
                shapes.append(shape)
            return zeros(shape, *args, **kwargs)
        source = np.ones((67, 5001), bool)
        with patch.object(hybrid.np, 'zeros', side_effect=observed):
            result = hybrid._eroded_centers(source, 28)
        self.assertTrue(shapes)
        self.assertTrue(all(rows <= 16 and columns <= 1024 for rows, columns in shapes))
        self.assertTrue(result[20, 20])
        polls = []
        with self.assertRaises(InterruptedError):
            hybrid._centers_touching_mask(source, 28, cancelled=lambda: (polls.append(1) or len(polls) == 5))
        self.assertEqual(len(polls), 5)
        np.testing.assert_array_equal(source, np.ones(source.shape, bool))

    def test_actual_verified_multibrush_plan_is_identical_to_scalar_morphology(self):
        import DrawBot
        with closing(Image.new('RGBA', (64, 48), 'white')) as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((12, 10, 51, 37), fill=(0, 80, 205, 255))
            draw.rectangle((24, 18, 29, 23), fill='white')
            options = browser_settings()
            def run(reference_operators=False):
                if reference_operators:
                    with patch.object(hybrid, '_eroded_centers', side_effect=lambda m,b,**kw: reference(m,b,True)), \
                            patch.object(hybrid, '_centers_touching_mask', side_effect=lambda m,b,**kw: reference(m,b,False)):
                        plan = DrawBot.make_plan(image, image.size, options)
                else:
                    plan = DrawBot.make_plan(image, image.size, options)
                try:
                    self.assertTrue(plan['options']['adaptive_hybrid_meta']['enabled'])
                    return (plan['groups'], plan['execution_groups'], plan['execution_sequence'],
                            plan['preview'].tobytes(), plan['options']['adaptive_hybrid_meta']['quality'],
                            plan['options']['adaptive_hybrid_meta']['candidate_diagnostics'])
                finally:
                    close_plan(plan, image)
            self.assertEqual(run(), run(True))


if __name__ == '__main__':
    unittest.main()
