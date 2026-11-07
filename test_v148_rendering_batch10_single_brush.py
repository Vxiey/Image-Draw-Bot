"""An exact region pack remains valid when it needs one verified brush size."""
from contextlib import ExitStack,closing
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw

from DrawBot import execute_plan,make_plan
from test_drawbot import Mouse,NoWait
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_transparency import standard_options
from test_v148_rendering_batch09_subject import BLUE,sequence_raster


def options(**changes):
    controls={'profile_key':'gartic-phone','target_position':(10,10),'target_index':0,
        'effective_px':2,'confidence':.99,'nominal_sizes':[2,4,8,16],
        'verified_sizes':[2,4,8,16],'control_positions':[(10,10),(20,10),(30,10),(40,10)],
        'safe_guard_px':16}
    result=standard_options(extra_fast=True,extra_fast_v2=True,brush_px=2,skip_white=True,
        profile_key='gartic-phone',profile_name='Gartic Phone',browser_brush_plan=controls,
        delay=.02,_execution_cost_calibration_override={},adaptive_color_verification=False,
        strict_color_verification=False,visual_verification_enabled=False,visual_verification_resolved='Off')
    result.update(changes)
    return result


def rectangle_source():
    source=Image.new('RGB',(64,48),'white')
    ImageDraw.Draw(source).rectangle((8,8,55,39),fill=BLUE)
    return source


class SingleBrushAdmissionTests(unittest.TestCase):
    def test_actual_plan_admits_exact_single_verified_width_with_zero_spill(self):
        with closing(rectangle_source()) as source,patch('DrawTimeCalibration.load_profile',return_value=None):
            plan=make_plan(source,source.size,options())
            try:
                metadata=plan['options']['adaptive_hybrid_meta']
                self.assertEqual(metadata['methods'],{'region-brush-pack':1})
                self.assertTrue(metadata['region_choices'][0]['exact'])
                self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']},{16})
                packing=metadata['candidate_diagnostics'][0]['brush_packing']
                self.assertEqual(packing['used_brush_sizes'],[16])
                expected=np.zeros((48,64),bool);expected[8:40,8:56]=True
                np.testing.assert_array_equal(sequence_raster(plan['execution_sequence'],source.size),expected)
                self.assertEqual((metadata['quality']['spill_pixels'],metadata['quality']['missing_pixels']),(0,0))
                self.assertEqual(metadata['quality']['coverage_percent'],100.)
                candidates=metadata['candidate_diagnostics'][0]['candidates']
                packed=next(row for row in candidates if row['method']=='region-brush-pack')
                self.assertLess(packed['estimated_seconds'],min(row['estimated_seconds'] for row in candidates if row['method']!='region-brush-pack'))
            finally:close_plan(plan,source)

    def test_admitted_single_size_still_competes_on_calibrated_switch_cost(self):
        calibration={'samples':5,'ratio':1.,'operation_runtime':{'brush_change':{'average_seconds':1000.,'count':5}}}
        with closing(rectangle_source()) as source,patch('DrawTimeCalibration.load_profile',return_value=None):
            plan=make_plan(source,source.size,options(_execution_cost_calibration_override=calibration))
            try:
                metadata=plan['options']['adaptive_hybrid_meta']
                self.assertNotIn('region-brush-pack',metadata['methods'])
                self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']},{2})
                choice=metadata['region_choices'][0]
                self.assertEqual(choice['method'],'horizontal')
                self.assertFalse(choice['exact'])
                self.assertIn('native exact packing=False',choice['reason'])
                self.assertEqual((metadata['quality']['coverage_percent'],metadata['quality']['missing_pixels'],
                                  metadata['quality']['spill_pixels']),(100.,0,81))
                target=np.zeros((48,64),bool);target[8:40,8:56]=True
                actual=sequence_raster(plan['execution_sequence'],source.size)
                self.assertEqual(np.count_nonzero(actual&~target),81)
                self.assertFalse(np.any(target&~actual))
                candidates=metadata['candidate_diagnostics'][0]['candidates']
                packed=next(row for row in candidates if row['method']=='region-brush-pack')
                self.assertGreater(packed['estimated_seconds'],min(row['estimated_seconds'] for row in candidates))
            finally:close_plan(plan,source)

    def test_real_executor_selects_verified_sixteen_pixel_control_and_paints_exact_region(self):
        origin=(100,100)
        with ExitStack() as stack:
            source=stack.enter_context(closing(rectangle_source()))
            surface=stack.enter_context(closing(Image.new('1',source.size)))
            stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
            stack.enter_context(patch('BrowserBrushSize.verify_brush_selection',return_value=True))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.save_runtime_safety_report',side_effect=lambda state:state.as_dict()))
            for name in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name,return_value={}))
            plan=make_plan(source,source.size,options(corners=(origin,(164,148))))
            stack.callback(close_plan,plan,source)
            mouse=Mouse()
            execute_plan(plan,(*origin,64,48),[(50+i*5,10) for i in range(len(plan['colors']))],
                mouse,NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)

            # Replay actual native actions with a square physical brush whose
            # width changes only when its verified external control is clicked.
            physical=2;position=(0,0);held=False;selected=[]
            draw=ImageDraw.Draw(surface)
            controls={(10,10):2,(20,10):4,(30,10):8,(40,10):16}
            def paint(a,b):
                self.assertTrue(a[0]==b[0] or a[1]==b[1])
                before,after=(physical-1)//2,physical//2
                draw.rectangle((min(a[0],b[0])-origin[0]-before,min(a[1],b[1])-origin[1]-before,
                                max(a[0],b[0])-origin[0]+after,max(a[1],b[1])-origin[1]+after),fill=1)
            for action in mouse.actions:
                if action[0]=='move':
                    next_position=action[1:]
                    if held:paint(position,next_position)
                    position=next_position
                elif action[0]=='press':
                    held=True;paint(position,position)
                elif action[0]=='release':held=False
                elif action[0]=='click':
                    if position in controls:
                        physical=controls[position];selected.append(physical)
                    elif origin[0]<=position[0]<164 and origin[1]<=position[1]<148:
                        paint(position,position)
            self.assertIn(16,selected);self.assertEqual(physical,16)
            expected=np.zeros((48,64),bool);expected[8:40,8:56]=True
            np.testing.assert_array_equal(np.asarray(surface),expected)
            self.assertFalse(held);self.assertFalse(mouse.held)
            self.assertEqual(plan['options']['runtime_path_counts']['sent'],plan['count'])


if __name__=='__main__':unittest.main()
