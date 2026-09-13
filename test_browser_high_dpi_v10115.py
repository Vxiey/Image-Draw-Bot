import unittest
from PIL import Image, ImageDraw
from BrowserAutoCalibration import detect_browser_setup
from PaletteMaps import GARTIC_PHONE
from Version import APP_VERSION, FILE_VERSION

class BrowserHighDpiTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_gartic_large_144dpi_style_client_does_not_hit_one_million_guard(self):
        # Reproduces the field-log scale closely: 3862x2110 target client.
        w, h = 3862, 2110
        im = Image.new('RGB', (w, h), (190,45,80))
        d = ImageDraw.Draw(im)
        # Canvas geometry ~1.79 ratio on the right side.
        d.rectangle((1000, 620, 2885, 1680), fill=(90,36,164))
        d.rectangle((1010, 630, 2875, 1670), fill=(255,255,255))
        # 6x12 palette inside Gartic left-side ROI, scaled for a 144-DPI layout.
        x0, y0 = 430, 590
        for i, rgb in enumerate(GARTIC_PHONE.colors):
            row, col = divmod(i, 6)
            x = x0 + col*44
            y = y0 + row*44
            d.rectangle((x, y, x+30, y+30), fill=rgb)
        result = detect_browser_setup('gartic-phone', im, screen_origin=(-11,-11))
        self.assertGreaterEqual(len(result['positions']), 36)
        self.assertTrue(result['stats'].get('bounded_scan'))
        self.assertLessEqual(result['stats'].get('max_tile_pixels', 1_000_001), 900_000)
        self.assertIsNotNone(result['canvas_box'])

if __name__ == '__main__':
    unittest.main()
