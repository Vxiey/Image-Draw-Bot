import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import BackgroundRemoval as BR
from ImageUpscale import suggested_factor, upscale_image, upscale_size


class ImageProcessingIntegrityTests(unittest.TestCase):
    def test_integral_floating_upscale_factor_produces_integer_dimensions(self):
        for factor in (2.0, 4.0, np.float32(2), np.int64(4)):
            size = upscale_size((8, 6), factor)
            self.assertTrue(all(type(value) is int for value in size))
            output = upscale_image(Image.new('RGBA', (8, 6), 'red'), factor, method='Pixel art')
            self.assertEqual(output.size, size)
            self.assertIs(type(output.info['draw_studio_upscale']['factor']), int)

    def test_size_validation_is_consistent_for_estimates_and_actual_upscales(self):
        for size in ((0, 1), (-1, 1), (True, 3), (1.5, 2), ('2', '3'), (1,), (1, 2, 3), None,
                     (float('nan'), 1), (float('inf'), 1)):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    suggested_factor(size)
                with self.assertRaises(ValueError):
                    upscale_size(size, 2)
        self.assertEqual(upscale_size((np.int64(4), np.int32(3)), 2), (8, 6))

    def test_invalid_factors_fail_before_image_conversion(self):
        for factor in (True, False, 0, -2, 2.2, '2', None, float('inf'), float('nan'), 10**1000):
            with self.subTest(factor=str(factor)[:40]), patch('ImageUpscale.ImageOps.exif_transpose') as transpose:
                with self.assertRaises(ValueError):
                    upscale_image(Image.new('RGB', (2, 2)), factor)
                transpose.assert_not_called()

    def subject(self):
        image = Image.new('RGB', (120, 100), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 25, 80, 75), fill=(90, 100, 110))
        draw.rectangle((45, 30, 95, 80), fill=(200, 30, 30))
        return image

    def test_corner_color_samples_actual_corners_and_preserves_side_subject(self):
        image = self.subject()
        automatic = BR.remove_background(image, mode='Auto', feather_px=0)
        corners = BR.remove_background(image, mode='Corner color', feather_px=0)
        self.assertEqual(automatic.image.getpixel((10, 50))[3], 0)
        self.assertEqual(corners.image.getpixel((10, 50))[3], 255)
        self.assertEqual(corners.image.getpixel((0, 0))[3], 0)
        self.assertEqual(corners.image.getpixel((70, 50))[3], 255)
        self.assertEqual(corners.metadata['background_clusters'], [[255.0, 255.0, 255.0]])
        self.assertIsNone(corners.metadata['no_op_reason'])
        self.assertEqual(image.mode, 'RGB')

    def test_corner_mode_retains_uniform_and_existing_transparency_guards(self):
        uniform = BR.remove_background(Image.new('RGBA', (20, 20), 'white'), mode='Corner color')
        self.assertIsNotNone(uniform.metadata['no_op_reason'])
        self.assertEqual(uniform.image.getpixel((0, 0))[3], 255)
        transparent = Image.new('RGBA', (20, 20), (0, 0, 0, 0))
        ImageDraw.Draw(transparent).rectangle((5, 5, 15, 15), fill='red')
        result = BR.remove_background(transparent, mode='Corner color')
        self.assertEqual(result.image.tobytes(), transparent.tobytes())
        self.assertEqual(result.metadata['method'], 'existing alpha preserved')

    def test_pre_cancelled_background_request_does_not_allocate_or_transpose(self):
        with patch.object(BR.ImageOps, 'exif_transpose') as transpose:
            with self.assertRaises(InterruptedError):
                BR.remove_background(self.subject(), cancelled=lambda: True)
            transpose.assert_not_called()

    def test_background_cancellation_after_alpha_work_never_returns_result(self):
        stopped = False
        alpha = BR._alpha
        def stop_during_alpha(*args, **kwargs):
            nonlocal stopped
            result = alpha(*args, **kwargs)
            stopped = True
            return result
        with patch.object(BR, '_alpha', side_effect=stop_during_alpha):
            with self.assertRaises(InterruptedError):
                BR.remove_background(self.subject(), cancelled=lambda: stopped)

    def test_preserve_branch_also_honors_late_cancellation(self):
        stopped = False
        preserve = BR._preserve
        def stop_during_preserve(*args, **kwargs):
            nonlocal stopped
            result = preserve(*args, **kwargs)
            stopped = True
            return result
        with patch.object(BR, '_preserve', side_effect=stop_during_preserve):
            with self.assertRaises(InterruptedError):
                BR.remove_background(Image.new('RGBA', (20, 20), (0, 0, 0, 0)), cancelled=lambda: stopped)


if __name__ == '__main__':
    unittest.main()
