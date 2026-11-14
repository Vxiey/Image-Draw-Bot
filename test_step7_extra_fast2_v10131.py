import unittest
from PIL import Image, ImageDraw

from AutoDrawing import resolve_drawing
from ContinuousPaths import build_execution_paths
from DrawBot import make_plan, finish_plan
from ExtraFast2 import path_limits


class Step7ExtraFast2Tests(unittest.TestCase):
    def _image(self):
        im=Image.new('RGB',(180,160),'white')
        d=ImageDraw.Draw(im)
        d.rectangle((30,25,145,130),fill=(248,205,28))
        d.rectangle((72,55,104,82),fill=(213,45,38))
        return im

    def _options(self, fill=True, dynamic=True):
        return {
            'render_preset':'Extra fast','fill_tool_available':fill,
            'detail':8,'delay':.01,'speed':'Fast','precision':'High','lines':True,
            'skip_white':True,'contrast':1.,'outline':False,'paint_current_color':False,
            'brush_px':1,'max_seconds':80,'time_budget_mode':'Custom','time_budget_active':True,
            'gpu_mode':'CPU','planning_resolution':'Standard','fill_aggressiveness':'Balanced',
            'custom_color_workflow':'Adaptive exact (recommended)' if dynamic else 'Calibrated palette',
            'exact_color_limit':'Auto','exact_color_available':dynamic,
            'color_rendering':'Perceptual match','color_fidelity':'Faithful','adaptive_detail':'Auto',
        }

    def test_preset_preserves_step1_to_6_color_policy(self):
        opts=self._options()
        out=resolve_drawing(self._image(),opts)
        self.assertTrue(out['extra_fast_v2'])
        self.assertEqual(out['color_rendering'],'Perceptual match')
        self.assertEqual(out['color_fidelity'],'Faithful')
        self.assertEqual(out['custom_color_workflow'],'Adaptive exact (recommended)')
        self.assertEqual(out['exact_color_limit'],'Auto')
        self.assertEqual(out['adaptive_detail'],'Auto')

    def test_critical_deadline_uses_long_connected_scanlines(self):
        rows=[(10,y,90,y) for y in range(10,170)]
        default=build_execution_paths([rows],enabled=True)
        fast=build_execution_paths([rows],enabled=True,max_rows_per_path=220,max_points_per_path=900)
        self.assertGreater(len(default[0]),len(fast[0]))
        self.assertEqual(len(fast[0]),1)
        r,p,policy=path_limits({'time_budget_active':True,'max_seconds':75})
        self.assertGreaterEqual(r,200);self.assertGreaterEqual(p,800);self.assertEqual(policy,'critical-deadline')

    def test_scanline_connectors_never_jump_across_a_gap(self):
        rows=[]
        for y in range(10,30):rows.append((10,y,40,y))
        for y in range(31,50):rows.append((10,y,40,y))  # one blank row separates components
        fast=build_execution_paths([rows],enabled=True,max_rows_per_path=220,max_points_per_path=900)
        self.assertEqual(len(fast[0]),2)
        self.assertTrue(all(not any(a[1]==30 or b[1]==30 for a,b in zip(path,path[1:])) for path in fast[0]))

    def test_dynamic_exact_can_use_plan_local_outline_fill(self):
        im=Image.new('RGB',(240,180),'white');d=ImageDraw.Draw(im)
        d.rectangle((20,20,105,155),fill=(248,205,28))
        d.rectangle((130,20,220,155),fill=(213,45,38))
        plan=make_plan(im,(900,800),self._options(fill=True,dynamic=True))
        regions=plan['options'].get('fill_regions') or []
        self.assertTrue(regions)
        self.assertTrue(plan['options'].get('extra_fast_v2_meta',{}).get('color_pipeline_preserved'))
        self.assertTrue(plan['options'].get('region_fill_meta',{}).get('dynamic_exact_supported'))
        selectors=plan.get('color_selectors') or ()
        for region in regions:
            idx=int(region['color_index'])
            self.assertGreaterEqual(idx,0);self.assertLess(idx,len(plan['colors']))
            self.assertLess(idx,len(selectors))
        self.assertEqual(plan['options']['region_fill_meta'].get('fallback_render_method'),'CONNECTED_SCANLINES')

    def test_no_fill_calibration_falls_back_to_connected_scanlines(self):
        with self.assertRaisesRegex(ValueError,'cannot cover'):
            make_plan(self._image(),(900,800),self._options(fill=False,dynamic=False))
        plan=make_plan(self._image(),(240,200),self._options(fill=False,dynamic=False))
        self.assertFalse(plan['options'].get('fill_regions'))
        meta=plan['options'].get('extra_fast_v2_meta') or {}
        self.assertTrue(meta.get('enabled'))
        self.assertTrue(meta.get('color_pipeline_preserved'))
        self.assertGreaterEqual(int(meta.get('scanline_boundaries_removed',0)),1)
        self.assertGreater(plan['source_count'],plan['count'])

    def test_fill_preview_uses_region_spans_not_whole_bbox(self):
        # L-shaped fill: a bbox-only preview would incorrectly color (7,7).
        image=Image.new('RGBA',(10,10),'white')
        groups=[[]]
        region={'color_index':0,'bbox':(1,1,8,8),'row_spans':tuple(
            [(y,1,3) for y in range(1,9)]+[(y,4,8) for y in range(1,4)]),
            'area_pixels':36,'contour':((1,1),(9,1),(9,4),(4,4),(4,9),(1,9),(1,1)),
            'seed_pixel':(2,2),'guard_pixels':()}
        opts={'delay':.01,'paint_current_color':False,'brush_px':1,'human_mode':'Off','speed':'Balanced',
              'precision':'High','lines':True,'drawing_mode':'Smart paths (recommended)','smart_paths':True,
              'fill_regions':[region],'plan_palette_rgb':((240,200,20),),'skip_white':True,
              'color_selectors':({'kind':'custom','source_rgb':(240,200,20),'fallback_palette_index':0},)}
        plan=finish_plan(image,(10,10),groups,opts)
        self.assertEqual(plan['preview'].getpixel((2,7)),(240,200,20))
        self.assertEqual(plan['preview'].getpixel((7,7)),(255,255,255))


if __name__=='__main__':unittest.main()
