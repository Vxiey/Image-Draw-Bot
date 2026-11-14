import unittest
from PIL import Image
from ExtraFastProfilePolicy import ensure_physical_sampling
from PixelData import prepare_image

class PhysicalSamplingTests(unittest.TestCase):
    def test_scaled_photo_grid_respects_brush(self):
        for size, area, brush in [((154,180),(480,480),2),((31,19),(173,101),3),((20,31),(121,181),2),((8,8),(8,8),1)]:
            with self.subTest(size=size, area=area, brush=brush):
                o=ensure_physical_sampling(size,area,{'brush_px':brush,'planner_max_pixels':75000,'planner_sample_limit':67})
                with Image.new('RGB',size) as source:
                    image,fitted=prepare_image(source,area,8,sample_limit=o['planner_sample_limit'],max_pixels=o['planner_max_pixels'])
                    with image:
                        self.assertLessEqual(fitted[0]/image.width,brush)
                        self.assertLessEqual(fitted[1]/image.height,brush)
                        self.assertLessEqual(image.width*image.height,75000)
    def test_verified_multi_brush_retains_native_packing_grid(self):
        from unittest.mock import patch
        settings={'brush_px':100,'planner_max_pixels':75000,'planner_sample_limit':4}
        with patch('AdaptiveBrushEngine.verified_brush_sizes',return_value=((1,100),True)):
            out=ensure_physical_sampling((4,4),(400,400),settings)
        self.assertEqual(out,settings)
    def test_exact_native_pack_wins_over_cheaper_inexact_centerlines(self):
        from unittest.mock import patch
        from test_rc6_region_brush_packing import rectangle_component, options
        from AdaptiveRegionHybrid import _brush_pack_candidate, _choose_component
        from ExecutionCostModel import build_cost_model
        comp,cmap=rectangle_component()
        settings=dict(options(),render_preset="Extra fast");model=build_cost_model(settings,(120,80),(120,80))
        packed,reason=_brush_pack_candidate(comp,cmap,settings,model)
        self.assertIsNotNone(packed,reason)
        packed=dict(packed,cost=100000.)
        with patch('AdaptiveRegionHybrid._brush_pack_candidate',return_value=(packed,'test exact pack')):
            choice,sequence,meta=_choose_component(comp,cmap,comp.area,model,settings)
        self.assertEqual(choice.method,'region-brush-pack')
        self.assertTrue(choice.exact)
    def test_thin_aspect_rounding_cannot_silently_drop_a_required_row(self):
        with self.assertRaisesRegex(ValueError,'cannot cover'):
            ensure_physical_sampling((10000,21),(1000,1000),{'brush_px':2,'planner_max_pixels':1000})
    def test_cap_failure_does_not_raise_memory_limit(self):
        with self.assertRaisesRegex(ValueError,'cannot cover'):
            ensure_physical_sampling((100,100),(1000,1000),{'brush_px':1,'planner_max_pixels':75000})
    def test_does_not_reduce_existing_sample_limit_or_change_brush(self):
        original={'brush_px':2,'planner_sample_limit':400,'planner_max_pixels':75000}
        out=ensure_physical_sampling((40,40),(100,100),original)
        self.assertEqual(out['planner_sample_limit'],400)
        self.assertEqual(out['brush_px'],2)
        self.assertEqual(original,{'brush_px':2,'planner_sample_limit':400,'planner_max_pixels':75000})
    def test_large_alpha_source_cap_fails_before_expansion(self):
        with self.assertRaises(ValueError):
            ensure_physical_sampling((20000,20000),(1200,1200),{'brush_px':2,'planner_max_pixels':75000})
if __name__=='__main__':unittest.main()
