"""One renderer owns the executable sequence and its public diagnostic maps."""
from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw

import AdaptiveRegionHybrid as regional
from AutoDrawing import resolve_drawing
from DrawBot import make_plan
from ExecutionCostModel import build_cost_model
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch09_subject import BLUE,sequence_raster,settings


def pixel_options(**changes):
    result=opts(render_preset='Extra fast',drawing_style='Pixel Art',
        profile_name='Gartic Phone',profile_key='gartic-phone',
        time_budget_mode='Custom',unlimited_time=False,max_seconds=10,manual_max_seconds=10,
        delay=.02,skip_white=True,detail_zoom='Off',_execution_cost_calibration_override={})
    result.update(changes)
    return result


def tiles():
    image=Image.new('RGB',(96,72),'white')
    draw=ImageDraw.Draw(image)
    colors=(BLUE,(239,19,11),(0,0,0))
    for y in range(4,68,12):
        for x in range(4,92,12):
            draw.rectangle((x,y,x+7,y+7),fill=colors[(x//12+y//12)%3])
    return image


def coverage_rgb(target,painted):
    result=np.empty((*target.shape,3),dtype=np.uint8);result[:]=(20,25,32)
    result[target&painted]=(45,180,120)
    result[target&~painted]=(240,175,55)
    result[~target&painted]=(220,70,75)
    return result


class SpecializedDispatchTests(unittest.TestCase):
    def assert_pixel_owner(self,plan):
        options=plan['options']
        self.assertEqual(plan['execution_sequence'],options['_pixel_execution_sequence'])
        self.assertEqual(plan['execution_groups'],options['_pixel_execution_groups'])
        self.assertTrue(plan['path_stats']['pixel_component_engine'])
        self.assertFalse(options.get('adaptive_hybrid_active'))
        self.assertNotIn('_adaptive_hybrid_execution_sequence',options)
        self.assertNotIn('adaptive_hybrid_meta',options)
        self.assertNotIn('adaptive_hybrid_meta',plan)

    def test_extra_fast_pixel_art_budget_coverage_and_cost_describe_actual_pixel_sequence(self):
        for seconds in (5,10):
            with self.subTest(seconds=seconds),closing(tiles()) as image, \
                    patch('DrawTimeCalibration.load_profile',return_value=None), \
                    patch.object(regional,'build_adaptive_hybrid_plan',side_effect=AssertionError('Pixel policy must own planning.')) as wrapper:
                options=pixel_options(max_seconds=seconds,manual_max_seconds=seconds)
                policy=resolve_drawing(image,options)
                self.assertEqual(policy['extra_fast_strategy_meta']['engine_kind'],'pixel-components')
                self.assertEqual(policy['draw_quality'],'Pixel Accurate')
                plan=make_plan(image,image.size,options)
                try:
                    wrapper.assert_not_called();self.assert_pixel_owner(plan)
                    target=np.any(np.asarray(image)!=255,axis=2)
                    painted=sequence_raster(plan['execution_sequence'],image.size)
                    self.assertTrue(painted.any())
                    self.assertTrue(np.any(target&~painted))
                    self.assertFalse(np.any(painted&~target))
                    np.testing.assert_array_equal(np.asarray(plan['ui_previews']['coverage']),coverage_rgb(target,painted))
                    meta=plan['options']['pixel_accuracy_meta']
                    self.assertEqual(meta['missing_pixels'],int(np.count_nonzero(target&~painted)))
                    self.assertAlmostEqual(meta['coverage_percent'],100*np.count_nonzero(target&painted)/np.count_nonzero(target),places=3)
                    # The public summary prices the same actual color/phase
                    # transitions as the selected component sequence.
                    previous=None;selections=0
                    for entry in plan['execution_sequence']:
                        state=entry['color_index'],entry['phase']
                        selections+=state!=previous;previous=state
                    model=build_cost_model(plan['options'],plan['image'].size,plan['fitted'])
                    self.assertAlmostEqual(plan['options']['operation_timing_meta']['palette_seconds'],
                                           selections*model.delivery.palette_click_delay,places=4)
                    self.assertEqual(plan['options']['operation_timing_meta']['custom_color_seconds'],0)
                finally:close_plan(plan,image)

    def test_subject_only_keeps_clipped_geometry_and_its_own_coverage_with_extra_fast_flags(self):
        with closing(Image.new('RGB',(64,64),BLUE)) as image, \
                patch('DrawTimeCalibration.load_profile',return_value=None), \
                patch.object(regional,'build_adaptive_hybrid_plan',side_effect=AssertionError('Subject policy must own planning.')) as wrapper:
            plan=make_plan(image,image.size,settings(brush_px=1,draw_quality='Balanced',extra_fast=True,extra_fast_v2=True))
            try:
                wrapper.assert_not_called();self.assert_pixel_owner(plan)
                target=np.zeros((64,64),bool);target[16:48,16:48]=True
                actual=sequence_raster(plan['execution_sequence'],image.size)
                np.testing.assert_array_equal(actual,target)
                np.testing.assert_array_equal(np.asarray(plan['ui_previews']['coverage']),coverage_rgb(target,actual))
                self.assertEqual(plan['options']['pixel_accuracy_meta']['spill_pixels'],0)
                self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']},{2})
            finally:close_plan(plan,image)

    def test_subject_first_keeps_subject_order_before_background_with_extra_fast_flags(self):
        with closing(Image.new('RGB',(64,64),BLUE)) as image, \
                patch('DrawTimeCalibration.load_profile',return_value=None), \
                patch.object(regional,'build_adaptive_hybrid_plan',side_effect=AssertionError('Subject policy must own planning.')) as wrapper:
            ImageDraw.Draw(image).rectangle((16,16,47,47),fill=(239,19,11))
            plan=make_plan(image,image.size,settings(brush_px=1,browser_brush_plan=None,draw_quality='Balanced',
                                                   subject_focus='Subject first',extra_fast=True,extra_fast_v2=True))
            try:
                wrapper.assert_not_called();self.assert_pixel_owner(plan)
                sections=[entry['subject_section'] for entry in plan['execution_sequence']]
                self.assertEqual(set(sections),{'subject','background'})
                self.assertEqual(sections,sorted(sections,reverse=True))
                np.testing.assert_array_equal(sequence_raster(plan['execution_sequence'],image.size),np.ones((64,64),bool))
            finally:close_plan(plan,image)

    def test_nonpixel_extra_fast_keeps_its_regional_execution_owner(self):
        with closing(tiles()) as image,patch('DrawTimeCalibration.load_profile',return_value=None), \
                patch.object(regional,'build_adaptive_execution',wraps=regional.build_adaptive_execution) as built:
            plan=make_plan(image,image.size,pixel_options(drawing_style='Logo / Flat Graphic',
                time_budget_mode='Unlimited',unlimited_time=True,delay=.001))
            try:
                built.assert_called_once()
                self.assertTrue(plan['options']['adaptive_hybrid_active'])
                self.assertEqual(plan['execution_sequence'],plan['options']['_adaptive_hybrid_execution_sequence'])
                self.assertNotIn('_pixel_execution_sequence',plan['options'])
                self.assertEqual(plan['options']['extra_fast_strategy_meta']['engine_kind'],'regional-hybrid')
            finally:close_plan(plan,image)


if __name__=='__main__':unittest.main()
