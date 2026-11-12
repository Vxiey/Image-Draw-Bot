"""Brush detection uses bounded patches of existing screenshots."""
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image
import BrowserBrushSize as brush


class BrushPatchPreparationTests(unittest.TestCase):
    def source(self, mode):
        with Image.open(Path(__file__).with_name('assets') / 'image-draw-bot-app-screenshot.png') as source:
            picture = source.convert(mode)
        self.addCleanup(picture.close)
        return picture

    def plan(self, picture):
        w, h = picture.size
        return brush.plan_browser_brush_size('skribbl', picture, (-200, -100, w-200, h-100),
            canvas_box=(-180, -80, w-220, h-200), requested_px=8).as_dict()

    def test_existing_screenshot_modes_match_rgb_without_full_window_conversion(self):
        for mode in ('RGB', 'RGBA', 'L', 'P'):
            with self.subTest(mode=mode):
                picture = self.source(mode)
                before = picture.tobytes()
                with picture.convert('RGB') as rgb:
                    expected = self.plan(rgb)
                self.assertEqual(len(expected['control_positions']), 4)
                conversions = []
                convert = Image.Image.convert

                def observe(image, *args, **kwargs):
                    conversions.append(image.size)
                    return convert(image, *args, **kwargs)

                with patch.object(Image.Image, 'convert', new=observe):
                    result = self.plan(picture)
                self.assertEqual(result, expected)
                self.assertEqual(picture.tobytes(), before)
                self.assertNotIn(picture.size, conversions)
                self.assertTrue(all(w <= 31 and h <= 31 for w, h in conversions))

    def test_patch_and_scoring_failures_close_already_owned_patches(self):
        for failing_stage in ('crop', 'score'):
            with self.subTest(stage=failing_stage):
                picture = self.source('RGBA')
                owned = []
                original = brush._patch

                def capture(*args, **kwargs):
                    if failing_stage == 'crop' and owned:
                        raise RuntimeError('next patch failed')
                    result = original(*args, **kwargs)
                    if result is not None:
                        owned.append(result)
                        self.addCleanup(result.close)
                    return result

                with patch.object(brush, '_patch', side_effect=capture):
                    if failing_stage == 'score':
                        with patch.object(brush, '_control_score', side_effect=RuntimeError('score failed')):
                            with self.assertRaisesRegex(RuntimeError, 'score failed'):
                                self.plan(picture)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'next patch failed'):
                            self.plan(picture)
                self.assertGreater(len(owned), 0)
                for image in owned:
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))
                picture.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
