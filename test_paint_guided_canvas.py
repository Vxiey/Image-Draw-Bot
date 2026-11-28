from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import PaintFullCalibration as paint
import PaintCanvasGrips as grips


class GuidedPaintCanvasTests(unittest.TestCase):
    def test_measured_paint_resize_grips_on_two_edges_and_corner(self):
        # Contrast counts from a real 1039x775 Paint window. Its status bar
        # reports 597x311, matching the measured document rectangle exactly.
        along = [0] * 87 + [6, 6, 2, 2, 2, 6, 6] + [0] * 87
        across = [0] * 24 + [7, 4, 4, 4, 4, 7] + [0] * 19
        right = grips._grip_dimensions(along, across, 90, 24)
        bottom = grips._grip_dimensions(along, across, 90, 24)
        self.assertEqual(right, (7, 6))
        self.assertTrue(grips._matching_grips(right, bottom))
        corner = [6, 2, 2, 2, 2, 6] + [0] * 14
        self.assertTrue(grips._square_corner(corner, corner, 6))
        self.assertTrue(grips._neutral_workspace([(247, 241, 243), (247, 243, 235),
                                                  (245, 243, 241), (247, 243, 239)]))

    def test_grid_or_scrollbar_signals_are_insufficient_for_guided_geometry(self):
        self.assertIsNone(grips._grip_dimensions([0] * 80, [0] * 25, 40, 12))
        self.assertIsNone(grips._grip_dimensions([0] * 15 + [2] * 5 + [0] * 61,
                                                  [0] * 12 + [5] * 3, 40, 12))
        self.assertFalse(grips._matching_grips((25, 5), (7, 6)))
        self.assertFalse(grips._matching_grips(None, (7, 6)))
        self.assertFalse(grips._square_corner([0] * 20, [0] * 20, 6))
        self.assertFalse(grips._square_corner([2] * 6, [2] * 6, 6))
        self.assertFalse(grips._neutral_workspace([(255, 255, 255)] * 4))
        self.assertFalse(grips._neutral_workspace([(242, 240, 243), (53, 53, 53)]))

    def test_toolbar_without_document_does_not_publish_geometry(self):
        path = Path(__file__).parent / 'tests/fixtures/paint-light-ribbon.png'
        with Image.open(path) as ribbon:
            original = ribbon.getpixel((300, 40))
            with self.assertRaisesRegex(ValueError, 'mark the canvas manually'):
                paint.detect_canvas_area(ribbon)
            self.assertEqual(ribbon.getpixel((300, 40)), original)

    def test_geometry_checks_screenshot_bounds_before_converting_pixels(self):
        class OversizedFrame:
            width, height = 9000, 8000
            size = (width, height)

        with self.assertRaisesRegex(ValueError, 'too large'):
            paint.detect_canvas_area(OversizedFrame())

    def test_original_ribbon_pixels_survive_independent_viewport_scaling(self):
        # A 4K window at 100% retains these exact native swatches. Reducing
        # the entire screenshot to 1920 first makes their pitch too small.
        path = Path(__file__).parent / 'tests/fixtures/paint-light-ribbon.png'
        with Image.open(path) as source, source.convert('RGB') as ribbon:
            search = paint._palette_search_box(ribbon, lambda: False)
            self.assertIsNotNone(search)
            tools, points, colors, _, scale = paint._ribbon_controls(
                ribbon, (-3800, 60), 1.0, lambda: False, search)
            self.assertEqual(tuple(colors), paint.ROW1 + paint.ROW2)
            self.assertEqual(len(set(points)), 20)
            self.assertEqual(tools['Fill'], (-3492, 88))
            self.assertAlmostEqual(scale, 1., places=2)
            with ribbon.resize((600, 56)) as half:
                with self.assertRaises(ValueError):
                    paint._ribbon_controls(half, (0,0), .5, lambda: False)

    def test_canvas_only_preserves_origin_box_and_returns_geometry_only(self):
        from test_paint_full_v106 import PaintFullTests
        with PaintFullTests().screenshot() as shot:
            result = paint.detect_canvas_area(shot, (-1920,40))
            self.assertEqual(result['canvas_box'], (-1835, 275, -85, 1026))
            self.assertEqual(result['canvas_confidence'], .90)
            self.assertEqual(result['canvas_visibility'], 'full')
            self.assertNotIn('tools', result)
            self.assertNotIn('rgbs', result)
            with patch.object(paint, '_blank_canvas_mask', side_effect=InterruptedError):
                with self.assertRaises(InterruptedError):
                    paint.detect_canvas_area(shot)

    def test_ambiguous_vertical_document_candidates_require_manual_selection(self):
        mask = np.zeros((600, 800), dtype=bool)
        mask[100:265, 100:700] = True
        mask[300:480, 100:700] = True
        with self.assertRaisesRegex(ValueError, 'More than one'):
            paint._detect_visible_canvas(mask, toolbar_end=80, w=800, h=600, scale=1.,
                                         screen_origin=(-800, 20), ratio=1.)

    def test_actual_application_screenshot_does_not_pass_as_paint(self):
        path = Path(__file__).parent / 'assets/image-draw-bot-app-screenshot.png'
        with Image.open(path) as shot, self.assertRaises(ValueError):
            paint.detect_canvas_area(shot)
