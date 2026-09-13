\
import unittest
import numpy as np
from PIL import Image,ImageDraw

from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan
from PixelAccuracyEngine import simulate_strokes
from ExecutionCostModel import build_cost_model
from Version import APP_VERSION

PALETTE=((255,255,255),(0,0,0),(255,0,0),(0,0,255))


def opts(**kw):
    out={'profile_key':'microsoft-paint','profile_name':'Microsoft Paint','speed':'Balanced',
         'precision':'High','brush_px':1,'delay':.006,'paint_tool':'Pencil',
         'effective_paint_tool':'Pencil','custom_color_workflow':'calibrated-palette',
         'paint_current_color':False,'adaptive_hybrid_cost':'Auto',
         '_hybrid_scale_x':4.0,'_hybrid_scale_y':3.0}
    out.update(kw);return out


class Rc20PixelExecutionCostTests(unittest.TestCase):
    def image(self):
        im=Image.new('RGBA',(32,24),'white');d=ImageDraw.Draw(im)
        d.rectangle((2,3,22,14),fill='red');d.line((27,2,27,20),fill='blue',width=1)
        d.rectangle((8,7,10,9),fill='white')
        return im

    def test_pixel_plan_reports_shared_execution_model_and_scale(self):
        im=self.image();pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=True)
        plan=build_pixel_stroke_plan(pm,len(PALETTE),options=opts())
        meta=plan['metadata'];self.assertTrue(meta['cost_aware'])
        self.assertEqual(meta['cost_policy'],'ExecutionCostModel stateful v3')
        self.assertEqual(meta['cost_model']['model'],'ExecutionCostModel')
        self.assertAlmostEqual(meta['cost_model']['scale_x'],4.0);self.assertAlmostEqual(meta['cost_model']['scale_y'],3.0)

    def test_scheduler_eta_matches_final_base_sequence_cost(self):
        im=self.image();pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=True)
        plan=build_pixel_stroke_plan(pm,len(PALETTE),options=opts())
        model=build_cost_model(opts(),pm.width and (pm.width,pm.height),(pm.width,pm.height))
        expected=model.sequence_cost(plan['execution_sequence'],initial_brush=1).total_seconds
        self.assertAlmostEqual(plan['metadata']['estimated_execution_seconds'],round(expected,4),places=4)

    def test_shared_cost_never_breaks_exact_brush1_coverage(self):
        im=self.image();pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=True)
        plan=build_pixel_stroke_plan(pm,len(PALETTE),options=opts())
        result=simulate_strokes(pm,plan['execution_sequence'],PALETTE,brush_px=1,gpu_mode='CPU')
        target=np.asarray(pm.drawable_mask,dtype=bool)
        self.assertTrue(np.array_equal(result.coverage_count>0,target))
        self.assertEqual(int(result.metrics['error_pixels']),0)

    def test_cost_model_off_keeps_legacy_fallback(self):
        im=self.image();pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=True)
        plan=build_pixel_stroke_plan(pm,len(PALETTE),options=opts(adaptive_hybrid_cost='Off'))
        self.assertFalse(plan['metadata']['cost_aware'])
        self.assertEqual(plan['metadata']['cost_policy'],'legacy geometry scheduler')

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc2')


if __name__=='__main__':unittest.main()
