from contextlib import closing
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageEnhance

from VisibleContrast import enhance_contrast
from test_v148_rendering_batch07_transparency import standard_options
from test_v148_rendering_batch06_canvas import close_plan


class VisibleContrastTests(unittest.TestCase):
    def test_opaque_rgb_remains_byte_exact_to_existing_pillow_behavior(self):
        with closing(Image.new('RGBA', (31, 17))) as image:
            image.putdata([((x * 47) % 256, (x * 71) % 256, (x * 19) % 256, 255)
                           for x in range(31 * 17)])
            original = image.tobytes()
            for factor in (0., .5, 1., 1.3, 2., 4.):
                with self.subTest(factor=factor), closing(image.convert('RGB')) as rgb, \
                        closing(ImageEnhance.Contrast(rgb).enhance(factor)) as expected, \
                        closing(enhance_contrast(image, factor)) as result, closing(result.convert('RGB')) as actual:
                    self.assertEqual(actual.tobytes(), expected.tobytes())
                    self.assertEqual(result.getextrema()[3], (255, 255))
            self.assertEqual(image.tobytes(), original)

    def test_partial_alpha_matches_independent_integer_visible_delta_oracle(self):
        values = [(24, 72, 160, alpha) for alpha in (0, 1, 64, 128, 254, 255)]
        with closing(Image.new('RGBA', (6, 1))) as image:
            image.putdata(values)
            visible = [tuple((channel * alpha + 255 * (255 - alpha) + 127) // 255
                             for channel in (r, g, b)) for r, g, b, alpha in values]
            with closing(Image.new('RGB', image.size)) as flattened:
                flattened.putdata(visible)
                for factor in (0., .75, 1., 1.5, 3.):
                    with self.subTest(factor=factor), closing(ImageEnhance.Contrast(flattened).enhance(factor)) as filtered, \
                            closing(enhance_contrast(image, factor)) as actual:
                        expected = []
                        for source, before, after in zip(values, visible, filtered.get_flattened_data()):
                            alpha = source[3]
                            channels = []
                            for channel, old, new in zip(source[:3], before, after):
                                numerator = (new - old) * 255
                                delta = (1 if numerator >= 0 else -1) * ((abs(numerator) + alpha // 2) // max(1, alpha)) if alpha else 0
                                channels.append(max(0, min(255, channel + delta)))
                            expected.append((*channels, alpha))
                        self.assertEqual(list(actual.get_flattened_data()), expected)

    def test_factor_one_preserves_every_original_rgba_byte(self):
        with closing(Image.new('RGBA', (17, 9))) as image:
            image.putdata([((x * 47) % 256, (x * 71) % 256, (x * 19) % 256, x % 256)
                           for x in range(17 * 9)])
            with closing(enhance_contrast(image, 1)) as result:
                self.assertEqual(result.tobytes(), image.tobytes())
                self.assertIsNot(result, image)

    def test_actual_standard_pixel_and_extra_fast_plans_ignore_hidden_rgb(self):
        import DrawBot
        cases = ({}, {'draw_quality': 'Pixel Accurate'}, {'extra_fast': True, 'extra_fast_v2': True})
        for changes in cases:
            compared = []
            for hidden in ((0, 0, 0), (255, 255, 255)):
                with closing(Image.new('RGBA', (24, 24), (*hidden, 0))) as image:
                    ImageDraw.Draw(image).rectangle((8, 8, 15, 15), fill=(128, 128, 128, 255))
                    original = image.tobytes()
                    plan = DrawBot.make_plan(image, image.size, standard_options(contrast=2., **changes))
                    try:
                        compared.append((plan['image'].getpixel((10, 10)), plan['groups'],
                                         plan['execution_groups'], plan['preview'].tobytes()))
                        self.assertEqual(image.tobytes(), original)
                    finally:
                        close_plan(plan, image)
            with self.subTest(changes=changes):
                self.assertEqual(compared[0], compared[1])
                self.assertEqual(compared[0][0], (15, 15, 15, 255))

    def test_owned_intermediates_and_interrupted_output_close_without_touching_source(self):
        created = []
        convert = Image.Image.convert
        def observed(source, *args, **kwargs):
            image = convert(source, *args, **kwargs)
            created.append(image)
            return image
        with closing(Image.new('RGBA', (8, 8), (20, 80, 160, 255))) as image:
            with patch.object(Image.Image, 'convert', observed):
                with self.assertRaises(InterruptedError):
                    enhance_contrast(image, 2, cancelled=lambda: len(created) >= 3)
            self.assertEqual(len(created), 4)  # includes Pillow's luminance conversion
            for owned in created:
                with self.assertRaises(ValueError):
                    owned.getpixel((0, 0))
            self.assertEqual(image.getpixel((0, 0)), (20, 80, 160, 255))
            with patch.object(Image.Image, 'convert', side_effect=AssertionError('no allocation after Stop')):
                with self.assertRaises(InterruptedError):
                    enhance_contrast(image, 2, cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
