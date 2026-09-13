import unittest
from PIL import Image, ImageDraw
import BackgroundRemoval as br


class BackgroundRemovalAITests(unittest.TestCase):
    def test_simple_background_uses_fast_path_without_ai(self):
        old = br._run_birefnet_mask
        br._run_birefnet_mask = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('AI must not run'))
        try:
            image = Image.new('RGBA', (100, 100), 'white')
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 80, 80), fill=(20, 20, 20, 255))
            draw.rectangle((40, 40, 60, 60), fill='white')
            result = br.remove_background(image)
            self.assertEqual(result.image.getpixel((0, 0))[3], 0)
            self.assertGreater(result.image.getpixel((50, 50))[3], 200)
            self.assertEqual(result.metadata['auto_strategy'], 'fast plain-background')
        finally:
            br._run_birefnet_mask = old

    @staticmethod
    def _complex_image():
        image = Image.new('RGB', (96, 96))
        pixels = image.load()
        for y in range(96):
            for x in range(96):
                pixels[x, y] = ((x * 5 + y * 3) % 256, (y * 7 + x) % 256, (x * 2 + y * 11) % 256)
        return image

    def test_complex_background_routes_to_ai_soft_mask(self):
        old = br._run_birefnet_mask
        mask = Image.new('L', (96, 96), 0)
        ImageDraw.Draw(mask).ellipse((20, 8, 76, 92), fill=255)
        br._run_birefnet_mask = lambda *_a, **_k: (
            mask,
            {'model': 'fake', 'provider': 'test', 'model_downloaded': False},
        )
        try:
            result = br.remove_background(self._complex_image())
            self.assertEqual(result.metadata['auto_strategy'], 'AI')
            self.assertTrue(result.metadata['method'].startswith('BiRefNet'))
            self.assertEqual(result.image.getpixel((0, 0))[3], 0)
            self.assertGreater(result.image.getpixel((48, 48))[3], 245)
        finally:
            br._run_birefnet_mask = old

    def test_complex_ai_failure_preserves_original(self):
        old = br._run_birefnet_mask
        br._run_birefnet_mask = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('offline'))
        try:
            result = br.remove_background(self._complex_image())
            self.assertEqual(result.image.getpixel((0, 0))[3], 255)
            self.assertEqual(result.metadata['method'], 'fail-closed original preserved')
            self.assertIn('AI was unavailable', result.metadata['no_op_reason'])
        finally:
            br._run_birefnet_mask = old

    def test_existing_transparency_is_not_destroyed(self):
        image = Image.new('RGBA', (32, 32), (10, 20, 30, 0))
        ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill=(50, 60, 70, 255))
        result = br.remove_background(image)
        self.assertEqual(result.metadata['method'], 'existing alpha preserved')
        self.assertEqual(result.image.getpixel((0, 0))[3], 0)
        self.assertEqual(result.image.getpixel((16, 16))[3], 255)

    def test_ai_safety_guard_rejects_empty_mask(self):
        old = br._run_birefnet_mask
        empty = Image.new('L', (96, 96), 0)
        br._run_birefnet_mask = lambda *_a, **_k: (
            empty,
            {'model': 'fake', 'provider': 'test', 'model_downloaded': False},
        )
        try:
            result = br.remove_background(self._complex_image())
            self.assertEqual(result.image.getpixel((0, 0))[3], 255)
            self.assertEqual(result.metadata['method'], 'AI safety guard preserved original')
        finally:
            br._run_birefnet_mask = old


if __name__ == '__main__':
    unittest.main()
