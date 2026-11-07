"""Background editing transfers private pixels without another full copy."""
from contextlib import closing
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageOps

import BackgroundRemoval as background


class BackgroundOutputOwnershipTests(unittest.TestCase):
    def fixture(self, mode='RGBA'):
        image = Image.new(mode, (80, 60), 'white')
        ImageDraw.Draw(image).rectangle((20, 15, 59, 44), fill=(30, 80, 160))
        if mode == 'RGBA':
            image.putpixel((1, 1), (180, 40, 200, 0))
            image.putpixel((30, 30), (30, 80, 160, 128))
        return image

    def test_result_preserves_exact_pixels_and_source_without_a_second_rgba_copy(self):
        for mode in ('RGB', 'RGBA'):
            with self.subTest(mode=mode), closing(self.fixture(mode)) as source:
                original = source.tobytes()
                copies = []
                copy = Image.Image.copy
                def observed(image):
                    result = copy(image)
                    if image.size == source.size and image.mode == 'RGBA':
                        copies.append(result)
                    return result
                with patch.object(Image.Image, 'copy', new=observed):
                    result = background.remove_background(source, feather_px=0)
                with closing(result.image) as image:
                    self.assertIsNone(result.metadata['no_op_reason'])
                    self.assertEqual(source.tobytes(), original)
                    self.assertIsNot(image, source)
                    # Independent rectangle/background oracle, including source
                    # partial alpha. No production mask helper is used here.
                    for y in range(source.height):
                        for x in range(source.width):
                            pixel = source.getpixel((x, y))
                            alpha = pixel[3] if mode == 'RGBA' else 255
                            expected_alpha = alpha if 20 <= x < 60 and 15 <= y < 45 else 0
                            self.assertEqual(image.getpixel((x, y)), (*pixel[:3], expected_alpha))
                    self.assertLessEqual(len(copies), 1)
                    image.putpixel((25, 20), (0, 0, 0, 0))
                    self.assertEqual(source.tobytes(), original)

    def test_oriented_image_stays_owned_and_the_safety_noop_remains_exact(self):
        with closing(self.fixture()) as source:
            source.getexif()[274] = 6
            original = source.tobytes()
            result = background.remove_background(source, feather_px=0)
            with closing(result.image) as image:
                self.assertEqual(image.size, (60, 80))
                self.assertEqual(image.getpixel((44, 20)), (30, 80, 160, 255))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                self.assertEqual(image.getexif().get(274), None)
            self.assertEqual(source.tobytes(), original)
            self.assertEqual(source.getexif()[274], 6)
        with closing(Image.new('RGBA', (40, 30), (20, 40, 60, 0))) as transparent:
            result = background.remove_background(transparent)
            with closing(result.image):
                self.assertTrue(result.metadata['no_op_reason'])
                self.assertIsNot(result.image, transparent)
                self.assertEqual(result.image.tobytes(), transparent.tobytes())

    def test_cancel_after_alpha_publication_closes_private_output_only(self):
        with closing(self.fixture()) as source:
            original = source.tobytes()
            stopped = [False]
            private = []
            prepare = background._oriented_rgba
            putalpha = Image.Image.putalpha
            def prepared(image):
                result = prepare(image); private.append(result); return result
            def publish(image, alpha):
                putalpha(image, alpha)
                if image in private: stopped[0] = True
            with patch.object(background, '_oriented_rgba', side_effect=prepared), \
                    patch.object(Image.Image, 'putalpha', new=publish):
                with self.assertRaises(InterruptedError):
                    background.remove_background(source, feather_px=0, cancelled=lambda: stopped[0])
            self.assertEqual(source.tobytes(), original)
            for image in private:
                with self.assertRaises(ValueError): image.getpixel((0, 0))

    def test_alpha_write_failure_closes_owned_result_and_preserves_borrowed_pixels(self):
        with closing(self.fixture()) as source:
            original = source.tobytes()
            private = []
            prepare = background._oriented_rgba
            def prepared(image):
                result = prepare(image); private.append(result); return result
            with patch.object(background, '_oriented_rgba', side_effect=prepared), \
                    patch.object(Image.Image, 'putalpha', side_effect=OSError('alpha write failed')):
                with self.assertRaisesRegex(OSError, 'alpha write failed'):
                    background.remove_background(source, feather_px=0)
            self.assertEqual(source.tobytes(), original)
            for image in private:
                with self.assertRaises(ValueError): image.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
