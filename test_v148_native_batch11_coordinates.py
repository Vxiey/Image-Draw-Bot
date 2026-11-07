"""Canvas pixel centers keep one raster across signed desktop translations."""
from contextlib import ExitStack, closing
from fractions import Fraction
import math
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from Precision import CanvasTransform, round_screen
import test_v148_rendering_batch10_physical as physical_fixtures


def nearest_canvas_integer(value):
    """Exact independent oracle for a supplied continuous pixel center."""
    return math.floor(Fraction(value) + Fraction(1, 2))


class CanvasCenterRoundingTests(unittest.TestCase):
    def test_exact_half_ties_choose_the_same_neighbor_on_both_sides_of_zero(self):
        for origin in (-1025, -3, -1, 0, 2, 1024):
            with self.subTest(origin=origin):
                transform = CanvasTransform(1, 1, (2, 2), origin, -origin)
                self.assertEqual(transform.float_point(0, 0), (origin + .5, -origin + .5))
                self.assertEqual(transform.point(0, 0), (origin + 1, -origin + 1))

    def test_adjacent_fitted_values_do_not_use_an_epsilon_to_move_a_boundary(self):
        for fitted in (math.nextafter(2., -math.inf), 2., math.nextafter(2., math.inf)):
            for origin in (-3, -1, 0, 2):
                with self.subTest(fitted=fitted, origin=origin):
                    transform = CanvasTransform(1, 1, (fitted, fitted), origin, -origin)
                    centers = transform.float_point(0, 0)
                    expected = tuple(nearest_canvas_integer(value) for value in centers)
                    self.assertEqual(transform.point(0, 0), expected)
        # The public generic screen-rounding policy has separate callers and
        # intentionally retains its existing signed tie convention.
        self.assertEqual(tuple(round_screen(value) for value in (-2.5, -.5, .5, 2.5)),
                         (-3, -1, 1, 3))

    def test_integer_translation_preserves_each_mapped_source_center(self):
        source = (13, 9)
        for fitted in ((13, 9), (26, 18), (31, 25), (13, 18)):
            for phase in ((0., 0.), (.5, .5), (.25, .75)):
                base = CanvasTransform(*source, fitted, *phase)
                expected = {(x, y): base.point(x, y)
                            for y in range(source[1]) for x in range(source[0])}
                for delta in ((-4096, -2048), (-7, -5), (23, 37)):
                    translated = CanvasTransform(*source, fitted,
                                                 phase[0] + delta[0], phase[1] + delta[1])
                    with self.subTest(fitted=fitted, phase=phase, delta=delta):
                        for point, value in expected.items():
                            self.assertEqual(translated.point(*point),
                                             (value[0] + delta[0], value[1] + delta[1]))

    def test_identity_and_ordinary_positive_mapping_keep_their_existing_pixels(self):
        identity = CanvasTransform(7, 5, (7, 5), -25, 100)
        for y in range(5):
            for x in range(7):
                self.assertEqual(identity.point(x, y), (x - 25, y + 100))
        positive = CanvasTransform(7, 5, (17, 11), 100.5, 200.5)
        for y in range(5):
            for x in range(7):
                centers = positive.float_point(x, y)
                self.assertEqual(positive.point(x, y), tuple(round_screen(v) for v in centers))


class ActualSignedCanvasDeliveryTests(unittest.TestCase):
    def check_axis(self, axis):
        # These rectangles make the regional planner choose horizontal or
        # vertical connected paths respectively. Every point is well inside
        # the unchanged CanvasGuard, including after a signed translation.
        box = (50, 60, 80, 69) if axis == 'y' else (60, 50, 69, 80)
        helper = physical_fixtures.PhysicalBrushProjectionTests()
        for margin in (0, 1, 2):
            area = (130, 130 + margin) if axis == 'y' else (130 + margin, 130)
            previous = None
            for origin in ((100, 100), (-200, -200), (-65, -65)):
                with self.subTest(axis=axis, margin=margin, origin=origin), ExitStack() as stack:
                    stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
                    source = stack.enter_context(closing(Image.new('RGB', (130, 130), 'white')))
                    ImageDraw.Draw(source).rectangle(box, fill=(0, 80, 205))
                    plan, reference = helper.public_plan(stack, source, area, origin,
                        browser_brush_plan=None, brush_px=1, canvas_guard_brush_px=1)
                    self.assertEqual(plan['image'].size, (130, 130))
                    self.assertEqual(plan['fitted'], (130., 130.))
                    actual, _selected = physical_fixtures.replay_executor(plan, origin, area)
                    shift = (margin + 1) // 2
                    x0, y0, x1, y1 = box
                    if axis == 'y': y0 += shift; y1 += shift
                    else: x0 += shift; x1 += shift
                    expected = np.zeros((area[1], area[0]), dtype=np.bool_)
                    expected[y0:y1 + 1, x0:x1 + 1] = True
                    np.testing.assert_array_equal(actual >= 0, expected)
                    if previous is not None:
                        np.testing.assert_array_equal(actual, previous)
                    previous = actual
                    self.assertEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'], 1)
                    self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)
                    self.assertEqual(plan['options']['runtime_path_counts']['sent'], plan['count'])
                    self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']}, {1})
                    if margin:
                        # R1004's complete native score, public Coverage and
                        # fitted preview still match the newly delivered pixels.
                        helper.assert_report_matches_native_actions(plan, reference, actual, area)
                    else:
                        quality = plan['options']['adaptive_hybrid_meta']['quality']
                        self.assertEqual(quality['missing_pixels'], 0)
                        self.assertEqual(quality['spill_pixels'], 0)

    def test_horizontal_rows_remain_contiguous_at_positive_negative_and_crossing_origins(self):
        self.check_axis('y')

    def test_vertical_columns_remain_contiguous_at_positive_negative_and_crossing_origins(self):
        self.check_axis('x')


if __name__ == '__main__':
    unittest.main()
