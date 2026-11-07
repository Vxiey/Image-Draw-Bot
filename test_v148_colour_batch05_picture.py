"""Contrast-selected picture colors use visible, symmetric source evidence."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import PictureCustomPalette as picture
import PictureCustomPaletteLegacy as legacy


class PictureDetailColorTests(unittest.TestCase):
    def test_dark_and_bright_accents_are_both_available(self):
        for background, detail in (((255,255,255), (160,15,35)),
                                   ((240,230,220), (30,45,80)),
                                   ((30,45,80), (240,230,220))):
            with self.subTest(background=background, detail=detail), Image.new('RGB', (64,64), background) as source:
                ImageDraw.Draw(source).rectangle((31,31,32,32), fill=detail)
                colors = legacy._edge_detail_colors(source, 2)
                self.assertEqual(set(colors), {background, detail})

    def test_uniform_images_have_no_filter_border_edges(self):
        for size in ((1,1), (1,17), (19,1), (21,13)):
            for color in ((0,0,0), (240,230,220), (255,255,255)):
                with self.subTest(size=size, color=color), Image.new('RGB', size, color) as source:
                    self.assertEqual(legacy._edge_detail_colors(source, 4), [])

    def test_equal_luminance_chromatic_details_are_still_visible_edges(self):
        # Equal rounded Pillow luminance does not make this RGB edge invisible.
        left, right = (255,0,0), (0,130,0)
        with Image.new('RGB', (12,8), left) as source:
            ImageDraw.Draw(source).rectangle((6,0,11,7), fill=right)
            self.assertEqual(set(legacy._edge_detail_colors(source, 2)), {left, right})

    def test_hidden_transparent_rgb_is_not_an_edge_candidate(self):
        with Image.new('RGBA', (20,20), (255,0,0,0)) as source:
            ImageDraw.Draw(source).rectangle((5,5,10,10), fill=(0,0,255,0))
            self.assertEqual(legacy._edge_detail_colors(source, 4), [])

    def test_production_palette_builder_executes_corrected_detail_sampler(self):
        captured = []
        actual = legacy._edge_detail_colors
        def sample(*args, **kwargs):
            result = actual(*args, **kwargs)
            captured.append(result)
            return result
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(picture, 'data_dir', return_value=Path(tmp)), \
             patch.object(legacy, '_edge_detail_colors', side_effect=sample), \
             Image.new('RGB', (64,64), 'white') as source:
            detail = (160,15,35)
            ImageDraw.Draw(source).rectangle((31,31,32,32), fill=detail)
            result = picture.build_picture_palette(source, ((255,255,255), (0,0,0)), max_colors=4)
        self.assertTrue(captured)
        self.assertIn(detail, captured[0])
        self.assertIn(detail, result.colors)

    def test_old_edge_palette_cache_is_not_reused_after_algorithm_change(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(picture, 'data_dir', return_value=Path(tmp)), \
             Image.new('RGB', (4,4), (30,45,80)) as source:
            result = picture.build_picture_palette(source, ((255,255,255), (0,0,0)), max_colors=4)
            payload = result.as_dict()
            payload['version'] = 3
            with self.assertRaises(ValueError):
                legacy._validate_payload(payload)


if __name__ == '__main__':
    unittest.main()
