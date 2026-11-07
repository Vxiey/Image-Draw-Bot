from __future__ import annotations

import unittest
from unittest.mock import patch

from PIL import Image

import GarticEngineV2 as gartic


class GarticCandidateTests(unittest.TestCase):
    def detect(self, image, **kwargs):
        white = ((20, 40, 340, 219), 320 * 179)
        unframed = ((90, 60, 448, 260), 358 * 200)
        with patch.object(gartic, '_flood_components', side_effect=[[white], [unframed]]), \
                patch.object(gartic, '_sample_white_fraction', return_value=.5), \
                patch.object(gartic, '_frame_score', return_value=.017):
            return gartic.detect_gartic_canvas(image, downsample=1, **kwargs)

    def test_unqualified_high_score_does_not_hide_an_eligible_canvas(self):
        with Image.new('RGB', (500, 300), 'black') as image:
            result = self.detect(image)
        self.assertTrue(result.found)
        self.assertEqual(result.box, (20, 40, 340, 219))
        self.assertEqual(result.reason, 'gartic canvas matched')

    def test_requested_minimum_area_is_part_of_the_acceptance_gate(self):
        with Image.new('RGB', (500, 300), 'black') as image:
            result = self.detect(image, min_canvas_area_ratio=.5)
        self.assertFalse(result.found)
        self.assertIsNone(result.box)
        for value in (float('nan'), float('inf'), -1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gartic.detect_gartic_canvas(None, min_canvas_area_ratio=value)

    def test_candidate_sampling_borrows_an_already_rgb_screenshot(self):
        image = Image.new('RGB', (300, 200), 'white')
        try:
            with patch.object(Image.Image, 'convert', side_effect=AssertionError('full screenshot copy')):
                self.assertEqual(gartic._sample_white_fraction(image, (20, 20, 240, 160)), 1)
                self.assertEqual(gartic._frame_score(image, (20, 20, 240, 160)), 0)
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        finally:
            image.close()

    def test_canvas_analysis_can_cancel_during_masks_and_inside_a_large_component(self):
        with Image.new('RGB', (300, 200), 'white') as image:
            checks = 0
            def cancelled():
                nonlocal checks
                checks += 1
                return checks >= 3
            with self.assertRaises(InterruptedError):
                gartic.detect_gartic_canvas(image, cancelled=cancelled)
        checks = 0
        def cancelled_flood():
            nonlocal checks
            checks += 1
            return checks >= 2
        with self.assertRaises(InterruptedError):
            gartic._flood_components([bytearray([1] * 80) for _ in range(80)], min_area=1, cancelled=cancelled_flood)
        self.assertEqual(checks, 2)


if __name__ == '__main__':
    unittest.main()
