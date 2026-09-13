import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from BackgroundRemoval import remove_background


class ClassicalBackgroundRemovalTests(unittest.TestCase):
    def test_plain_background_keeps_internal_matching_detail(self):
        image = Image.new('RGBA', (120, 120), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((18, 18, 102, 102), fill=(24, 24, 24, 255))
        draw.rectangle((48, 48, 72, 72), fill='white')
        result = remove_background(image)
        self.assertEqual(result.image.getpixel((0, 0))[3], 0)
        self.assertGreater(result.image.getpixel((60, 60))[3], 220)
        self.assertEqual(result.metadata['method'], 'classical edge-aware multi-colour border segmentation')
        self.assertFalse(result.metadata['ai_used'])

    def test_multicolour_background_uses_edge_aware_region_segmentation(self):
        image = Image.new('RGB', (180, 140), (220, 220, 220))
        draw = ImageDraw.Draw(image)
        # Four connected background tones imitate tiles / uneven room colours.
        draw.rectangle((0, 0, 89, 69), fill=(220, 224, 228))
        draw.rectangle((90, 0, 179, 69), fill=(196, 206, 214))
        draw.rectangle((0, 70, 89, 139), fill=(232, 218, 205))
        draw.rectangle((90, 70, 179, 139), fill=(187, 199, 184))
        for x in range(15, 180, 30):
            draw.line((x, 0, x, 139), fill=(128, 132, 136), width=2)
        for y in range(15, 140, 28):
            draw.line((0, y, 179, y), fill=(132, 136, 140), width=2)
        # Strong subject contour and skin-like interior colour.
        draw.ellipse((55, 18, 130, 132), fill=(55, 25, 20), outline=(8, 8, 8), width=4)
        draw.ellipse((62, 25, 123, 126), fill=(208, 132, 101))

        result = remove_background(image, strength='Balanced')
        self.assertEqual(result.metadata['method'], 'classical edge-aware multi-colour border segmentation')
        self.assertFalse(result.metadata['ai_used'])
        self.assertLess(result.image.getpixel((3, 3))[3], 30)
        self.assertGreater(result.image.getpixel((92, 75))[3], 220)
        self.assertGreater(result.metadata['removed_percent'], 20.0)
        self.assertIn('uncertain_percent', result.metadata)
        self.assertIn('largest_foreground_component_percent', result.metadata)

    def test_chromatic_edge_protects_subject_even_when_luma_is_similar(self):
        image = Image.new('RGB', (120, 100), (120, 170, 120))
        ImageDraw.Draw(image).rectangle((30, 20, 90, 85), fill=(200, 100, 105))
        result = remove_background(image)
        self.assertLess(result.image.getpixel((0, 0))[3], 30)
        self.assertGreater(result.image.getpixel((60, 50))[3], 220)
        self.assertIn('chromatic contour barrier', result.metadata['edge_policy'])

    def test_complex_background_does_not_require_model_or_service_dependency(self):
        requirements = Path('requirements.txt').read_text(encoding='utf-8').lower()
        self.assertNotIn('onnxruntime', requirements)
        self.assertNotIn('rembg', requirements)
        self.assertNotIn('opencv', requirements)
        self.assertNotIn('tensorflow', requirements)
        self.assertNotIn('torch', requirements)

    def test_existing_transparency_is_preserved(self):
        image = Image.new('RGBA', (40, 40), (10, 20, 30, 0))
        ImageDraw.Draw(image).rectangle((10, 10, 29, 29), fill=(80, 90, 100, 255))
        result = remove_background(image)
        self.assertEqual(result.metadata['method'], 'existing alpha preserved')
        self.assertEqual(result.image.getpixel((0, 0))[3], 0)
        self.assertEqual(result.image.getpixel((20, 20))[3], 255)
        self.assertFalse(result.metadata['ai_used'])

    def test_uniform_image_fails_closed(self):
        image = Image.new('RGBA', (80, 80), 'white')
        result = remove_background(image)
        self.assertEqual(result.image.getpixel((0, 0))[3], 255)
        self.assertIsNotNone(result.metadata['no_op_reason'])
        self.assertEqual(result.metadata['removed_percent'], 0.0)

    def test_cancel_is_honoured_before_segmentation(self):
        image = Image.new('RGB', (100, 100), 'white')
        with self.assertRaises(InterruptedError):
            remove_background(image, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
