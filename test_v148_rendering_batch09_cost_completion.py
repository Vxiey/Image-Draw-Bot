"""RP28 caller completion: Pixel component costing sees resolved custom selectors."""
from contextlib import closing
import unittest
from unittest.mock import patch

from PIL import Image,ImageDraw

from DrawBot import make_plan
from ExecutionCostModel import build_cost_model
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan


class PixelSelectorCostTests(unittest.TestCase):
    def test_actual_prepared_palette_is_available_when_block_b_prices_components(self):
        colors=((73,117,181),(181,73,117))
        settings=opts(render_preset='Manual',draw_quality='Pixel Accurate',time_budget_mode='Unlimited',
            unlimited_time=True,profile_name='Microsoft Paint',profile_key='microsoft-paint',
            paint_profile=True,exact_color_available=True,picture_palette_rgb=colors,
            custom_color_workflow='Exact custom + palette fallback',detail_zoom='Off',
            _execution_cost_calibration_override={})
        with closing(Image.new('RGB',(64,32),'white')) as source, \
                patch('DrawTimeCalibration.load_profile',return_value=None):
            draw=ImageDraw.Draw(source)
            draw.rectangle((4,4,28,27),fill=colors[0]);draw.rectangle((34,7,58,24),fill=colors[1])
            plan=make_plan(source,source.size,settings)
            try:
                sequence=plan['execution_sequence']
                model=build_cost_model(plan['options'],plan['image'].size,plan['fitted'])
                # Each of the two actual retained colors requires one custom
                # selection; neither correction nor brush changes are needed.
                selected=[];previous=None
                for entry in sequence:
                    key=entry['color_index'],entry['phase']
                    if key!=previous:selected.append(key[0])
                    previous=key
                self.assertEqual(len(selected),2)
                self.assertEqual(plan['options']['pixel_accuracy_meta']['correction_paths_added'],0)
                self.assertTrue(all(plan['color_selectors'][i]['kind']=='custom' for i in selected))
                geometry=model.paths_seconds([entry['path'] for entry in sequence])
                expected=geometry+len(selected)*(model.delivery.palette_click_delay+.78)
                self.assertAlmostEqual(plan['options']['pixel_stroke_meta']['estimated_execution_seconds'],expected,places=4)
            finally:close_plan(plan,source)


if __name__=='__main__':unittest.main()
