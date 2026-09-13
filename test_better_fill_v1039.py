import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from FillOptimizer import detect_fill_regions, remove_filled_region_strokes, resolve_fill_engine


class BetterFillV1039Tests(unittest.TestCase):
    def _l_shape(self):
        image=Image.new('RGB',(90,70),'white'); draw=ImageDraw.Draw(image)
        draw.rectangle((15,10,65,19),fill=(255,120,41))
        draw.rectangle((15,19,26,56),fill=(255,120,41))
        return image

    def test_auto_resolves_to_closed_regions_v2(self):
        self.assertEqual(resolve_fill_engine('Auto','Balanced'),'Closed regions v2')
        self.assertEqual(resolve_fill_engine('Auto','Off'),'Off')

    def test_irregular_hole_free_region_is_accepted(self):
        regions,meta=detect_fill_regions(self._l_shape(),'Balanced',engine='Closed regions v2',return_meta=True)
        self.assertEqual(len(regions),1)
        region=regions[0]
        self.assertEqual(region.strategy,'closed-contour')
        self.assertEqual(region.contour[0],region.contour[-1])
        self.assertGreater(region.estimated_saved_strokes,0)
        self.assertGreater(len(region.row_spans),1)
        self.assertTrue(region.guard_pixels)
        self.assertEqual(meta['contour_regions'],1)

    def test_legacy_safe_rectangles_rejects_irregular_region(self):
        self.assertEqual(detect_fill_regions(self._l_shape(),'Balanced',engine='Safe rectangles'),[])

    def test_hole_region_falls_back_to_scanlines(self):
        image=Image.new('RGB',(90,70),'white'); draw=ImageDraw.Draw(image)
        draw.rectangle((15,10,70,58),fill=(255,120,41))
        draw.rectangle((32,25,52,44),fill='white')
        regions,meta=detect_fill_regions(image,'Balanced',engine='Closed regions v2',return_meta=True)
        from PixelData import closest_color
        orange=int(closest_color((255,120,41)))
        self.assertFalse(any(r.color_index==orange for r in regions))
        self.assertGreaterEqual(meta['fallback_scanline_regions'],1)
        self.assertIn('holes',meta['rejected'])

    def test_exact_row_spans_do_not_remove_bbox_hole_space(self):
        regions=detect_fill_regions(self._l_shape(),'Balanced',engine='Closed regions v2')
        region=regions[0]
        # Same color group has a long row through the bbox at y=40. Only the
        # vertical L leg (x=15..26) is filled there, so x>=27 must survive.
        groups=[[] for _ in range(region.color_index+1)]
        groups[region.color_index]=[(0,40,80,40)]
        out=remove_filled_region_strokes(groups,[region])
        self.assertIn((0,40,14,40),out[region.color_index])
        self.assertIn((27,40,80,40),out[region.color_index])

    def test_ui_exposes_fill_engine(self):
        text=(Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        self.assertIn('Fill engine',text)
        self.assertIn('Closed regions v2',text)

    def test_execution_uses_traced_contour_and_guard_pixels(self):
        text=(Path(__file__).resolve().parent/'DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('draw_closed_contour',text)
        self.assertIn("region.get('guard_pixels'",text)
        self.assertIn('Better Fill detected color outside the protected region',text)

    def test_version(self):
        from Version import APP_VERSION
        self.assertEqual(APP_VERSION,'1.0.145-rc29')

if __name__=='__main__': unittest.main()
