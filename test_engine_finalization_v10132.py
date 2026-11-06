"""Behavioural regressions for the final engine integration (no native input)."""
import copy
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw
from ContinuousPaths import _compress, build_execution_paths
from PixelAccuratePlanner import build_pixel_map, groups_from_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan, _bounded_axis_paths
from HybridCostModel import build_cost_model
from DeadlineScheduler import DeadlineScheduler
from RenderResume import checkpoint_after_batch, resolve_resume
from PostDrawCorrectionPass import build_post_draw_correction_plan
from test_step14_post_draw_correction_v10138 import trusted_meta
from test_render_resume_v1042 import simple_plan
from test_drawbot import Mouse, NoWait

PALETTE=((255,255,255),(0,0,0),(255,0,0),(0,0,255))


def raster(paths, size):
    im=Image.new('1',size)
    draw=ImageDraw.Draw(im)
    for path in paths:
        if len(path)==1:draw.point(path[0],fill=1)
        else:draw.line(path,fill=1,width=1)
    return np.asarray(im)


class FinalEngineTests(unittest.TestCase):
    def test_compress_preserves_collinear_reversal(self):
        path=((0,0),(5,0),(2,0),(2,1))
        self.assertTrue(np.array_equal(raster([path],(7,3)),raster([_compress(path)],(7,3))))
        self.assertEqual(_compress(((0,0),(2,0),(5,0))),((0,0),(5,0)))

    def test_continuous_widening_rows_preserve_all_pixels(self):
        groups=[[(3,0,5,0),(0,1,9,1),(2,2,4,2),(0,3,9,3)]]
        paths=build_execution_paths(groups,enabled=True)
        raw=[((x,y),(xx,yy)) for x,y,xx,yy in groups[0]]
        self.assertTrue(np.array_equal(raster(raw,(10,4)),raster(paths[0],(10,4))))

    def test_random_masks_serial_parallel_and_deadline_are_exact(self):
        rng=np.random.default_rng(8132)
        for n in range(5):
            indices=rng.integers(0,4,(14,19))
            rgba=np.empty((14,19,4),dtype=np.uint8)
            rgba[:,:,:3]=np.asarray(PALETTE)[indices];rgba[:,:,3]=255
            rgba[rng.random((14,19))<.1,3]=0
            pm=build_pixel_map(Image.fromarray(rgba),PALETTE,gpu_mode='CPU')
            for workers in (1,2):
                for timed in (False,True):
                    plan=build_pixel_stroke_plan(pm,4,cpu_workers=workers,options={
                        'gpu_mode':'CPU','time_budget_active':timed,'max_seconds':20})
                    for ci,paths in enumerate(plan['execution_groups']):
                        expected=(pm.palette_index==ci)&pm.drawable_mask
                        self.assertTrue(np.array_equal(raster(paths,(19,14)),expected),(n,workers,timed,ci))

    def test_vectorized_runs_keep_transparent_gaps_and_single_pixel(self):
        im=Image.new('RGBA',(9,1),(0,0,0,0))
        for x in (0,1,3,8):im.putpixel((x,0),(0,0,0,255))
        pm=build_pixel_map(im,PALETTE,gpu_mode='CPU')
        self.assertEqual(groups_from_pixel_map(pm,4)[1],[(0,0,1,0),(3,0,3,0),(8,0,8,0)])
        self.assertEqual(len(groups_from_pixel_map(pm,4,lines=False)[1]),4)

    def test_split_long_path_preserves_geometry_and_cost_limit(self):
        model=replace(build_cost_model({}),path_fixed_seconds=.02,draw_seconds_per_px=.01,
                      learned_path_floor_seconds=0,scale_x=2,scale_y=1)
        paths=[((0,0),(100,0),(100,3),(0,3))]
        result=_bounded_axis_paths(paths,model,.3)
        self.assertGreater(len(result),2)
        self.assertTrue(np.array_equal(raster(paths,(101,4)),raster(result,(101,4))))
        self.assertTrue(all(model.path_seconds(p)<=.300001 for p in result))

    def test_cancel_reaches_split_loop(self):
        with self.assertRaises(InterruptedError):
            _bounded_axis_paths([((0,0),(200,0))],build_cost_model({}),.1,cancelled=lambda:True)

    def test_scaled_cost_and_learned_floor_do_not_hide_travel(self):
        model=replace(build_cost_model({}),learned_path_floor_seconds=5,travel_seconds_per_px=.1)
        self.assertAlmostEqual(model.path_seconds(((10,0),(11,0)),cursor=(0,0)),6)
        base=replace(model,learned_path_floor_seconds=0)
        scaled=replace(base,scale_x=3)
        self.assertGreater(scaled.path_seconds(((0,0),(10,0))),base.path_seconds(((0,0),(10,0))))

    def test_sequence_estimate_includes_color_and_travel(self):
        from ExecutionCostModel import build_cost_model as build_execution_cost_model
        im=Image.new('RGBA',(32,20),'white');d=ImageDraw.Draw(im)
        d.rectangle((2,2,6,6),fill='black');d.rectangle((22,12,28,18),fill='red')
        pm=build_pixel_map(im,PALETTE,gpu_mode='CPU')
        opts={'profile_key':'engine-test','_execution_cost_calibration_override':{}}
        model=build_execution_cost_model(opts,im.size,im.size)
        plan=build_pixel_stroke_plan(pm,4,options=opts)
        total=0;cur=None;color=None
        for e in plan['execution_sequence']:
            if e['color_index']!=color:total+=model.color_change_seconds
            total+=model.path_seconds(e['path'],cursor=cur)
            cur=e['path'][-1];color=e['color_index']
        self.assertAlmostEqual(plan['metadata']['estimated_execution_seconds'],total,places=4)

    def test_resume_rejects_geometry_brush_and_profile_changes(self):
        plan=simple_plan();state=checkpoint_after_batch(plan,1)
        for key,value in [('brush_px',5),('profile_key','another-target'),('target_dpi',144)]:
            changed=copy.deepcopy(plan);changed['options'][key]=value
            self.assertFalse(resolve_resume(changed,state)['compatible'])
        changed=copy.deepcopy(plan);changed['groups'][0]=[(0,0,5,0)]
        self.assertFalse(resolve_resume(changed,state)['compatible'])

    def test_pause_is_not_learned_as_slow_drawing(self):
        now=[0.0];entry={'estimated_cost_seconds':1,'phase':'structure'}
        sched=DeadlineScheduler([entry,entry],start_time=0,budget_seconds=20,clock=lambda:now[0])
        sched.before(entry);now[0]=6;sched.after(entry,excluded_seconds=5)
        self.assertAlmostEqual(sched.telemetry()['runtime_cost_multiplier'],1)
        self.assertEqual(sched.remaining_time(),14)

    def test_unfittable_operation_skipped_before_mouse_down(self):
        entry={'estimated_cost_seconds':10,'phase':'structure'}
        sched=DeadlineScheduler([entry],start_time=0,budget_seconds=1,clock=lambda:0)
        self.assertFalse(sched.before(entry).execute)

    def test_one_outlier_is_bounded_and_interval_is_labeled(self):
        now=[0.0];entry={'estimated_cost_seconds':1,'phase':'structure'}
        sched=DeadlineScheduler([entry]*3,start_time=0,budget_seconds=None,clock=lambda:now[0])
        sched.before(entry);now[0]=20;sched.after(entry)
        self.assertLessEqual(sched.telemetry()['runtime_cost_multiplier'],2.5)
        self.assertIn('heuristic',sched.telemetry()['prediction_interval']['source'])

    def test_correction_rejects_palette_that_is_worse_than_actual(self):
        source=Image.new('RGB',(20,20),(128,128,128))
        actual=Image.new('RGB',source.size,(200,200,200))
        corr=build_post_draw_correction_plan(original_source=source,actual_canvas=actual,
            palette_rgb=((0,0,0),),post_draw_meta=trusted_meta(),options={'gpu_mode':'CPU'},
            max_area_fraction=1)
        self.assertFalse(corr['enabled'])
        self.assertGreater(corr.get('rejected_non_improving_pixels',0),0)

    def test_wide_correction_brush_cannot_damage_adjacent_white(self):
        source=Image.new('RGB',(20,20),'white');ImageDraw.Draw(source).line((10,2,10,17),fill='black')
        corr=build_post_draw_correction_plan(original_source=source,actual_canvas=Image.new('RGB',source.size,'white'),
            palette_rgb=((0,0,0),),post_draw_meta=trusted_meta(),options={'gpu_mode':'CPU','brush_px':5},
            max_area_fraction=1)
        self.assertFalse(corr['enabled'])
        self.assertGreater(corr.get('rejected_brush_footprint_pixels',0),0)

    def test_input_released_before_diagnostic_disk_failure(self):
        from DrawBot import execute_plan
        mouse=Mouse();mouse.held=True;stop=NoWait();stop.stopped=True
        def fail(_):
            self.assertFalse(mouse.held)
            raise OSError('diagnostic disk full')
        with patch('DrawBot.save_runtime_safety_report',side_effect=fail):
            with self.assertRaises((InterruptedError,OSError)):
                execute_plan(simple_plan(),(0,0,60,30),[(0,0)]*3,mouse,stop,threading.Event(),lambda *e:None)
        self.assertFalse(mouse.held)

if __name__=='__main__':unittest.main()
