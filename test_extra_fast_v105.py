import unittest
from PIL import Image,ImageDraw
from AutoDrawing import resolve_drawing
from ExtraFast import select_fast_regions
from FillOptimizer import detect_fill_regions

class ExtraFastTests(unittest.TestCase):
    def image(self):
        im=Image.new('RGB',(180,160),'white')
        ImageDraw.Draw(im).rectangle((30,25,145,130),fill=(255,120,41))
        return im

    def test_preset_and_missing_calibration(self):
        original={'render_preset':'Extra fast','fill_tool_available':True,'max_seconds':60}
        out=resolve_drawing(self.image(),original)
        self.assertEqual(out['fill_engine'],'Closed regions v2')
        self.assertTrue(out['extra_fast']);self.assertEqual(out['max_seconds'],60)
        self.assertNotIn('extra_fast',original)
        fallback=resolve_drawing(self.image(),dict(original,fill_tool_available=False))
        self.assertEqual(fallback['background_fill'],'Off')
        self.assertIn('calibrate Fill',fallback['auto_drawing_meta']['engine'])

    def test_single_colour_and_eraser(self):
        out=resolve_drawing(self.image(),{'render_preset':'Extra fast','paint_current_color':True})
        self.assertTrue(out['outline']);self.assertEqual(out['background_fill'],'Off')
        with self.assertRaises(ValueError):resolve_drawing(self.image(),{'render_preset':'Extra fast','erase_mode':True})

    def test_cost_selection_and_closed_contours(self):
        im=self.image();regions=[r.as_dict() for r in detect_fill_regions(im)]
        out,meta=select_fast_regions(regions,im.size,(900,800),{'delay':.01})
        self.assertTrue(out);self.assertGreater(meta['estimated_seconds_saved_vs_scanlines'],0)
        bad=dict(regions[0],contour=[(0,0),(1,0),(1,1),(0,1)])
        self.assertFalse(select_fast_regions([bad],im.size,im.size,{} )[0])
        costly=dict(regions[0],row_spans=[(50,50,51)])
        self.assertFalse(select_fast_regions([costly],im.size,im.size,{})[0])

    def test_cancel_during_large_component(self):
        calls=[]
        def cancel():calls.append(1);return len(calls)>2
        with self.assertRaises(InterruptedError):detect_fill_regions(Image.new('RGB',(200,200),'white'),cancelled=cancel)

    def test_full_plan_keeps_fallback_and_has_no_background_bucket(self):
        from DrawBot import make_plan
        options={'render_preset':'Extra fast','fill_tool_available':True,
                 'detail':8,'delay':.01,'speed':'Balanced','precision':'High','lines':True,
                 'skip_white':True,'contrast':1.,'outline':False,'paint_current_color':False,
                 'brush_px':1,'max_seconds':180,'gpu_mode':'CPU','planning_resolution':'Standard'}
        plan=make_plan(self.image(),(900,800),options)
        self.assertTrue(plan['options']['extra_fast'])
        self.assertFalse(plan['options'].get('background_fill_plan'))
        self.assertTrue(plan['options'].get('fill_regions'))
        self.assertGreater(plan['options']['extra_fast_meta']['fill_estimated_seconds'],0)
        with self.assertRaisesRegex(ValueError,'cannot cover'):
            make_plan(self.image(),(900,800),dict(options,fill_tool_available=False))
        no_bucket=make_plan(self.image(),(240,200),dict(options,fill_tool_available=False))
        self.assertFalse(no_bucket['options'].get('fill_regions'))
        self.assertGreater(no_bucket['count'],0)
