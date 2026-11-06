import unittest
import numpy as np
from PIL import Image,ImageDraw
from AdaptiveBrushEngine import assign_adaptive_brushes
from PixelAccuracyGpu import compile_swept_rectangles
from PixelAccuracyEngine import progressive_time_budget
from DrawBot import make_plan
from test_draw_motor_v1090 import brush_plan,entry
from test_pixel_accurate_v1086 import opts

class MergeTests(unittest.TestCase):
    def test_subject_phase_prefix_keeps_detail_brush_policy(self):
        plan=assign_adaptive_brushes([entry('subject/fine_detail'),entry('background/fill')],profile_key='gartic-phone',default_brush_px=4,browser_brush_plan=brush_plan())
        self.assertEqual([e['brush_px'] for e in plan['execution_sequence']],[2,4])
        self.assertEqual(plan['execution_sequence'][0]['phase'],'subject/fine_detail')

    def test_per_path_brush_and_outside_clipping_coexist(self):
        sequence=[dict(entry(path=((-10,2),)),brush_px=3),dict(entry(path=((2,2),)),brush_px=1)]
        rectangles=compile_swept_rectangles(sequence,5,6,6)
        np.testing.assert_array_equal(rectangles,[[2,2,2,2,2]])

    def test_subject_only_integrates_motor_without_repainting_background(self):
        image=Image.new('RGBA',(30,20),'white');ImageDraw.Draw(image).rectangle((10,5,19,14),fill='red')
        plan=make_plan(image,(30,20),opts(subject_focus='Subject only',browser_brush_plan=brush_plan()))
        self.assertEqual(plan['options']['pixel_accuracy_meta']['draw_motor'],'Adaptive Brush Draw Motor v2')
        self.assertFalse(plan['options']['pixel_accuracy_meta']['automatic_corrections'])
        self.assertTrue(plan['execution_sequence'])
        for e in plan['execution_sequence']:
            self.assertEqual(e['brush_px'],1)
            for x,y in e['path']: self.assertTrue(10<=x<20 and 5<=y<15)

    def test_timer_keeps_subject_order_and_per_path_widths(self):
        seq=[dict(entry('subject/fine_detail'),brush_px=2) for _ in range(100)]+[dict(entry('background/fill'),brush_px=4) for _ in range(100)]
        budget=progressive_time_budget(seq,active=True,seconds=5,correction_reserve_ratio=0)
        self.assertTrue(budget['execution_sequence'])
        self.assertTrue(all(e['phase'].startswith('subject/') and e['brush_px']==2 for e in budget['execution_sequence']))
