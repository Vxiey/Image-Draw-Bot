from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import PaintFullCalibration as paint


class GuidedPaintCanvasTests(unittest.TestCase):
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
