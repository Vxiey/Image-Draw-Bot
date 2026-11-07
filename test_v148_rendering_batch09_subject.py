"""Subject-only drawing constrains the verified brush footprint, not just its center."""
from contextlib import ExitStack, closing
import copy
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from SubjectFocus import clip_subject_brush_sequence
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan


BLUE=(0,80,205)


def settings(**changes):
    base=opts(render_preset='Manual',draw_quality='Pixel Accurate',time_budget_mode='Unlimited',
        unlimited_time=True,subject_focus='Subject only',subject_region=(.25,.25,.75,.75),
        skip_white=False,profile_key='gartic-phone',profile_name='Gartic Phone',brush_px=4,
        canvas_guard_brush_px=4,detail_zoom='Off',color_fidelity='Exact',
        browser_brush_plan={'profile_key':'gartic-phone','target_position':(20,10),
            'target_index':1,'effective_px':4,'confidence':.95,'nominal_sizes':[2,4,8],
            'verified_sizes':[2,4,8],'control_positions':[(10,10),(20,10),(30,10)],'safe_guard_px':8},
        strict_color_verification=False,adaptive_color_verification=False,
        visual_verification_enabled=False,visual_verification_resolved='Off',
        _execution_cost_calibration_override={})
    base.update(changes)
    return base


def line_pixels(path,size):
    with closing(Image.new('1',size)) as image:
        draw=ImageDraw.Draw(image)
        if len(path)==1:draw.point(path[0],fill=1)
        elif path:draw.line(path,fill=1,width=1)
        return np.asarray(image).copy()


def paint_centers(centers,brush):
    height,width=centers.shape
    before,after=(brush-1)//2,brush//2
    with closing(Image.new('1',(width,height))) as image:
        draw=ImageDraw.Draw(image)
        for y,x in np.argwhere(centers):
            draw.rectangle((int(x)-before,int(y)-before,int(x)+after,int(y)+after),fill=1)
        return np.asarray(image).copy()


def sequence_raster(sequence,size):
    result=np.zeros((size[1],size[0]),bool)
    brush=1
    for entry in sequence:
        brush=int(entry.get('brush_px',brush))
        result|=paint_centers(line_pixels(entry['path'],size),brush)
    return result


class SubjectBrushMaskTests(unittest.TestCase):
    def test_retained_paths_match_independent_allowed_center_and_footprint_oracles(self):
        target=np.zeros((24,28),bool);target[3:22,2:26]=True;target[8:13,10:15]=False
        original=target.copy();target.flags.writeable=False
        paths=(((0,5),(27,5)),((5,0),(5,23)),((0,0),(23,23)),
               ((-100,17),(27,17),(27,18),(-100,18)),((7,7),))
        for brush in (1,2,3,4):
            with self.subTest(brush=brush):
                sequence=[{'color_index':1,'brush_px':brush,'phase':'subject/fill','path':path,
                           'serial':i,'protected':bool(i%2)} for i,path in enumerate(paths)]
                source=copy.deepcopy(sequence)
                actual,meta=clip_subject_brush_sequence(sequence,target)
                valid=np.zeros(target.shape,bool);before,after=(brush-1)//2,brush//2
                for y in range(target.shape[0]):
                    for x in range(target.shape[1]):
                        valid[y,x]=(x>=before and y>=before and x+after<target.shape[1]
                            and y+after<target.shape[0]
                            and bool(np.all(target[y-before:y+after+1,x-before:x+after+1])))
                expected=np.zeros(target.shape,bool)
                for path in paths:expected|=paint_centers(line_pixels(path,(28,24))&valid,brush)
                raster=sequence_raster(actual,(28,24))
                np.testing.assert_array_equal(raster,expected)
                self.assertFalse(np.any(raster&~target))
                self.assertEqual(sequence,source)
                np.testing.assert_array_equal(target,original)
                self.assertEqual(meta['retained_paths'],len(actual))
                self.assertEqual(set(e['brush_px'] for e in actual),{brush})
                for entry in actual:
                    self.assertEqual(entry['phase'],'subject/fill')
                    self.assertEqual(entry['protected'],bool(entry['serial']%2))

    def test_safe_one_pixel_geometry_and_entry_metadata_remain_identical(self):
        target=np.zeros((12,12),bool);target[2:10,2:10]=True
        sequence=[{'color_index':0,'brush_px':1,'path':((2,2),(5,2),(9,2),(9,9),(9,4)),
                   'phase':'subject/cleanup','serial':7,'importance':.9}]
        actual,meta=clip_subject_brush_sequence(sequence,target)
        self.assertEqual(actual,sequence)
        self.assertEqual(meta['trimmed_source_paths'],0)

    def test_actual_public_plan_keeps_two_pixel_brush_inside_subject_with_full_coverage(self):
        from DrawBot import make_plan
        with closing(Image.new('RGB',(64,64),BLUE)) as source, \
                patch('DrawTimeCalibration.load_profile',return_value=None):
            plan=make_plan(source,source.size,settings(brush_px=1))
            try:
                expected=np.zeros((64,64),bool);expected[16:48,16:48]=True
                np.testing.assert_array_equal(sequence_raster(plan['execution_sequence'],source.size),expected)
                self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']},{2})
                meta=plan['options']['pixel_accuracy_meta']
                self.assertEqual((meta['spill_pixels'],meta['missing_pixels']),(0,0))
                self.assertEqual(meta['subject_brush_mask']['subject_coverage_percent'],100.)
                self.assertGreater(meta['subject_brush_mask']['trimmed_source_paths'],0)
                self.assertEqual(meta['adaptive_brush']['brush_path_counts'],{'2':plan['count']})
                self.assertEqual(plan['options']['pixel_stroke_meta']['execution_paths'],plan['count'])
            finally:close_plan(plan,source)

    def test_actual_narrow_subject_reports_missing_pixels_without_inventing_brush_one(self):
        from DrawBot import make_plan
        cases=((settings(brush_px=1),(2,4,8)),(settings(browser_brush_plan=None),(4,)))
        for options,available_brushes in cases:
            with self.subTest(available_brushes=available_brushes),closing(Image.new('RGB',(64,64),BLUE)) as source:
                plan=make_plan(source,source.size,dict(options,subject_region=(15/64,8/64,16/64,24/64)))
                try:
                    self.assertEqual(plan['execution_sequence'],[])
                    self.assertEqual(plan['count'],0)
                    meta=plan['options']['pixel_accuracy_meta']
                    self.assertEqual(meta['drawable_pixels'],16)
                    self.assertEqual((meta['missing_pixels'],meta['spill_pixels']),(16,0))
                    self.assertEqual(meta['subject_brush_mask']['missing_subject_pixels'],16)
                    self.assertEqual(meta['subject_brush_mask']['subject_coverage_percent'],0.)
                    self.assertEqual(meta['adaptive_brush']['available_brush_sizes'],available_brushes)
                    self.assertEqual(meta['adaptive_brush']['used_brush_sizes'],())
                    self.assertEqual(plan['options']['adaptive_accuracy_meta']['coverage_percent'],0.)
                finally:close_plan(plan,source)

    def test_stop_inside_long_path_does_not_publish_partial_geometry(self):
        target=np.ones((1,5001),bool);original=target.copy();calls=[]
        sequence=[{'color_index':0,'brush_px':1,'path':((0,0),(5000,0))}]
        with self.assertRaises(InterruptedError):
            clip_subject_brush_sequence(sequence,target,cancelled=lambda:(calls.append(1) or len(calls)==5))
        self.assertEqual(len(calls),5)
        np.testing.assert_array_equal(target,original)
        self.assertEqual(sequence[0]['path'],((0,0),(5000,0)))

    def test_fake_native_execution_uses_real_width_inside_centered_subject(self):
        from DrawBot import DrawBotApp,execute_plan,make_plan
        from test_drawbot import Mouse,NoWait

        class RasterMouse(Mouse):
            def __init__(self,surface,origin):
                super().__init__();self.surface=surface;self.origin=origin;self.brush=4
            def paint(self,a,b):
                before,after=(self.brush-1)//2,self.brush//2
                # Public Pixel Stroke geometry is orthogonal. Each native move
                # sweeps the actual verified square through these centers.
                self.assert_axis(a,b)
                ImageDraw.Draw(self.surface).rectangle((min(a[0],b[0])-self.origin[0]-before,
                    min(a[1],b[1])-self.origin[1]-before,max(a[0],b[0])-self.origin[0]+after,
                    max(a[1],b[1])-self.origin[1]+after),fill=1)
            @staticmethod
            def assert_axis(a,b):
                if a[0]!=b[0] and a[1]!=b[1]:raise AssertionError('Expected an orthogonal native subject stroke.')
            def move(self,x,y):
                old=self.position;super().move(x,y)
                if self.held:self.paint(old,self.position)
            def press(self):
                super().press();self.paint(self.position,self.position)
            def click(self):
                super().click()
                if self.position in ((10,10),(20,10),(30,10)):
                    self.brush={(10,10):2,(20,10):4,(30,10):8}[self.position]
                elif self.origin[0]<=self.position[0]<self.origin[0]+80 and self.origin[1]<=self.position[1]<self.origin[1]+64:
                    self.paint(self.position,self.position)

        class Value:
            def __init__(self,value):self.value=value
            def get(self):return self.value
            def set(self,value):self.value=value

        cases=((1,settings(brush_px=1),2),(4,settings(browser_brush_plan=None),4))
        for origin,case in ((origin,case) for origin in ((100,100),(-200,-100)) for case in cases):
            requested,base_options,actual_brush=case
            with self.subTest(origin=origin,requested_brush=requested,actual_brush=actual_brush),ExitStack() as stack:
                source=stack.enter_context(closing(Image.new('RGB',(64,64),BLUE)))
                surface=stack.enter_context(closing(Image.new('1',(80,64))))
                stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
                stack.enter_context(patch('DrawBot.log_event'))
                stack.enter_context(patch('DrawBot.save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
                stack.enter_context(patch('BrowserBrushSize.verify_brush_selection',return_value=True))
                for name in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                             'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                             'CorrectionHistory.record_correction_history'):
                    stack.enter_context(patch(name,return_value={}))
                options=dict(base_options,corners=(origin,(origin[0]+80,origin[1]+64)))
                if actual_brush==4:
                    app=SimpleNamespace(outline=Value(False),subject_focus=Value('Subject only'),
                        draw_quality=Value('Balanced'),brush_px=Value('4'),status=Value(''),
                        options_changed=lambda:None)
                    DrawBotApp.subject_focus_changed(app)
                    self.assertEqual(app.brush_px.get(),'4')
                    options.update(brush_px=int(app.brush_px.get()),draw_quality=app.draw_quality.get())
                plan=make_plan(source,(80,64),options);stack.callback(close_plan,plan,source)
                mouse=RasterMouse(surface,origin)
                execute_plan(plan,(*origin,80,64),[(50+i*5,10) for i in range(len(plan['colors']))],
                    mouse,NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)
                expected=np.zeros((64,80),bool);expected[16:48,24:56]=True
                np.testing.assert_array_equal(np.asarray(surface),expected)
                self.assertEqual(mouse.brush,actual_brush)
                self.assertEqual(plan['options']['brush_px'],requested)
                self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']},{actual_brush})
                self.assertEqual(plan['options']['runtime_path_counts']['sent'],plan['count'])
                self.assertFalse(mouse.held)


if __name__=='__main__':unittest.main()
