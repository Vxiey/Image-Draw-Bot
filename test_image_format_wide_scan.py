"""Colour-key metadata scanning bounds every owned tile, including wide rows."""
from contextlib import closing
import unittest
from unittest.mock import patch

from PIL import Image
import ImageFormatInfo as info


class WideTransparencyScanTests(unittest.TestCase):
    def scan(self, source, cap=8, fail=False):
        crops, conversions, sizes = [], [], []
        crop, convert = Image.Image.crop, Image.Image.convert
        def traced_crop(image, box):
            result = crop(image, box)
            crops.append(result)
            sizes.append(result.width * result.height)
            return result
        def traced_convert(image, mode, *args, **kwargs):
            if fail:
                raise OSError('conversion failed')
            result = convert(image, mode, *args, **kwargs)
            conversions.append(result)
            return result
        try:
            with patch.object(info, '_ALPHA_SCAN_PIXELS', cap), \
                 patch.object(Image.Image, 'crop', traced_crop), \
                 patch.object(Image.Image, 'convert', traced_convert):
                return info._has_transparency(source), len(crops)
        finally:
            for owned in crops + conversions:
                with self.assertRaises(ValueError):
                    owned.getpixel((0, 0))
            source.getpixel((0, 0))
            self.assertTrue(all(size <= cap for size in sizes), sizes)

    def test_wide_rgb_and_greyscale_tail_is_scanned_exactly(self):
        for mode, opaque, key in [('RGB', (10, 20, 30), (1, 2, 3)), ('L', 90, 17)]:
            for size in [(19, 1), (19, 3), (4, 5)]:
                with self.subTest(mode=mode, size=size), closing(Image.new(mode, size, opaque)) as source:
                    source.info['transparency'] = key
                    source.putpixel((size[0]-1, size[1]-1), key)
                    expected = source.tobytes()
                    visible, count = self.scan(source)
                    self.assertTrue(visible)
                    self.assertGreater(count, 1)
                    self.assertEqual(source.tobytes(), expected)

    def test_real_budget_bounds_a_million_pixel_row(self):
        with closing(Image.new('L', (1_000_000, 1), 90)) as source:
            source.info['transparency'] = 17
            source.putpixel((999_999, 0), 17)
            self.assertEqual(self.scan(source, info._ALPHA_SCAN_PIXELS), (True, 4))

    def test_wide_opaque_keyed_image_remains_opaque(self):
        with closing(Image.new('RGB', (19, 3), (10, 20, 30))) as source:
            source.info['transparency'] = (1, 2, 3)
            self.assertEqual(self.scan(source), (False, 9))

    def test_first_tile_transparency_stops_scan(self):
        with closing(Image.new('L', (19, 3), 0)) as source:
            source.info['transparency'] = 0
            self.assertEqual(self.scan(source), (True, 1))

    def test_conversion_failure_releases_tile_not_source(self):
        with closing(Image.new('RGB', (19, 3), (10, 20, 30))) as source:
            source.info['transparency'] = (1, 2, 3)
            with self.assertRaisesRegex(OSError, 'conversion failed'):
                self.scan(source, fail=True)


if __name__ == '__main__':
    unittest.main()
