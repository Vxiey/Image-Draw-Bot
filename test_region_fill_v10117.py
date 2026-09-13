import unittest
from PIL import Image, ImageDraw

from RegionFillEngine import build_region_fill_plan, estimate_fill_execution_seconds
from Version import APP_VERSION, FILE_VERSION


class RegionFillEngineV10117Tests(unittest.TestCase):
    def base_options(self, **extra):
        out = {
            'draw_quality': 'Balanced', 'render_preset': 'Manual', 'speed': 'Balanced',
            'delay': .003, 'precision': 'High', 'brush_px': 2,
            'fill_engine': 'Closed regions v2', 'fill_aggressiveness': 'Balanced',
            'profile_key': 'gartic-phone', 'fill_tool_available': True,
            'fill_tool_actions': [('fill', (10, 10))],
            'fill_restore_actions': [('brush', (12, 10))],
            'ram_budget_mb': 1024,
        }
        out.update(extra)
        return out

    def test_large_closed_rectangle_prefers_outline_fill(self):
        im = Image.new('RGB', (120, 90), 'white')
        d = ImageDraw.Draw(im)
        d.rectangle((20, 15, 95, 72), fill=(0, 0, 0))
        regions, meta = build_region_fill_plan(im, (120, 90), self.base_options(), safe_margin_px=2)
        self.assertGreaterEqual(meta['total_regions'], 2)
        self.assertGreaterEqual(meta['fill_safe_regions'], 1)
        self.assertTrue(regions)
        self.assertTrue(all(r['render_method'] == 'OUTLINE_FILL' for r in regions))
        self.assertGreater(meta['fill_coverage_percent'], 10)
        timing = estimate_fill_execution_seconds(regions, im.size, im.size, self.base_options())
        self.assertGreater(timing['total_seconds'], 0)

    def test_thin_or_small_detail_falls_back(self):
        im = Image.new('RGB', (100, 80), 'white')
        d = ImageDraw.Draw(im)
        d.rectangle((20, 20, 22, 55), fill=(0, 0, 0))
        regions, meta = build_region_fill_plan(im, im.size, self.base_options(fill_aggressiveness='Safe'), safe_margin_px=2)
        self.assertEqual(regions, [])
        self.assertEqual(meta['fill_safe_regions'], 0)

    def test_pixel_accurate_is_protected(self):
        im = Image.new('RGB', (80, 60), 'white')
        regions, meta = build_region_fill_plan(im, im.size, self.base_options(draw_quality='Pixel Accurate'))
        self.assertEqual(regions, [])
        self.assertTrue(meta['pixel_accurate_protected'])

    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')


if __name__ == '__main__':
    unittest.main()
