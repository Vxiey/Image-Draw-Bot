"""Automatic planning policies preserve the user's quality and time choices."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


class PortraitBudgetTests(unittest.TestCase):
    def plan(self, **overrides):
        import DrawBot as app
        from test_portrait_integration import opts
        strokes=[(0,index,20,index) for index in range(100)]
        stats=SimpleNamespace(tone_strokes=80,edge_strokes=20,levels=5,sample_size=(20,100),
            priority_strokes=5,draw_quality='High likeness',acceleration_backend='CPU',
            acceleration_device='',gpu_accelerated=False)
        images=[]
        def finish(image,fitted,groups,options,cancelled):
            images.append(image)
            return {'image':image,'groups':groups,'options':options,'count':sum(map(len,groups)),
                    'estimate':sum(map(len,groups))*100.0}
        with ExitStack() as context:
            original=context.enter_context(Image.new('RGB',(20,100)))
            gray=context.enter_context(Image.new('L',(20,100)))
            context.enter_context(patch.object(app,'prepare_portrait_image',return_value=(gray,(20,100))))
            renderer=context.enter_context(patch.object(app,'portrait_strokes',return_value=([strokes],stats)))
            context.enter_context(patch.object(app,'finish_plan',side_effect=finish))
            context.enter_context(patch.object(app,'_finalize_auto_tuned_plan',side_effect=lambda plan,*args:plan))
            result=app.make_plan(original,(20,100),opts(resource_scheduler='Off',gpu_mode='CPU',**overrides))
            for image in images:image.close()
            result['options']['_accuracy_original_source'].close()
            return result,renderer.call_args.kwargs['max_strokes'],len(images)

    def test_unlimited_portrait_keeps_quality_strokes_despite_large_time_estimate(self):
        result,cap,attempts=self.plan(time_budget_mode='Unlimited')
        self.assertIsNone(cap)
        self.assertEqual(result['count'],100)
        self.assertEqual(attempts,1)
        self.assertGreater(result['estimate'],3600)

    def test_short_portrait_budget_can_reduce_below_old_minimum_of_120_strokes(self):
        result,cap,attempts=self.plan(max_seconds=5)
        self.assertLess(cap,120)
        self.assertLess(result['count'],24+48)
        self.assertGreater(attempts,1)


class TunerQualityTests(unittest.TestCase):
    @staticmethod
    def rescue_case(**overrides):
        options={'auto_tuner_meta':{'active':True,'profile_group':'browser',
                   'source_features':{'source_kind':'photo / texture'}},
                 'draw_quality':'Maximum likeness','planning_resolution':'Extreme'}
        options.update(overrides)
        acceptance={'status':'BELOW_QUALITY_GATE','deadline_gate_passed':True,'quality_gate_passed':False,
                    'usable_deadline_seconds':None,'projected_draw_seconds':20,'schedule_headroom_seconds':None}
        return {'options':options,'plan_area':(300,200)},acceptance

    def test_transparent_statistics_use_visible_white_canvas(self):
        from EndToEndAutoTuner import _bounded_stats
        from ColorMatchingEngine import visible_rgb_image
        with Image.new('RGBA',(160,120),(255,0,0,0)) as source:
            self.assertEqual(_bounded_stats(source),(1.0,0.0))
            source.paste((30,60,200,180),(50,20,90,100))
            with visible_rgb_image(source) as visible:
                self.assertEqual(_bounded_stats(source),_bounded_stats(visible))
        with Image.new('RGB',(8,8),'red') as keyed:
            keyed.info['transparency']=(255,0,0)
            self.assertEqual(_bounded_stats(keyed),(1.0,0.0))

    def test_unlimited_photo_can_use_bounded_pixel_accuracy_rescue(self):
        from EndToEndAutoTuner import propose_rescue_options
        plan,acceptance=self.rescue_case()
        result=propose_rescue_options(plan,acceptance)
        self.assertEqual(result['draw_quality'],'Pixel Accurate')
        self.assertEqual(result['auto_tuner_meta']['selected_strategy'],'quality-rescue-pixel-accurate')
        plan['plan_area']=(1000,1000)
        self.assertNotEqual(propose_rescue_options(plan,acceptance)['draw_quality'],'Pixel Accurate')

    def test_quality_rescue_never_downgrades_extreme_resolution(self):
        from EndToEndAutoTuner import propose_rescue_options
        for resolution,expected in (('Standard','High'),('High','Ultra'),('Ultra','Extreme'),('Extreme','Extreme')):
            with self.subTest(resolution=resolution):
                plan,acceptance=self.rescue_case(planning_resolution=resolution)
                plan['plan_area']=(1000,1000)
                self.assertEqual(propose_rescue_options(plan,acceptance)['planning_resolution'],expected)

    def test_old_quick_sketch_policy_cannot_override_rescue_on_next_plan(self):
        from EndToEndAutoTuner import propose_rescue_options
        from QuickSketchFillContour import is_quick_sketch
        plan,acceptance=self.rescue_case(render_style='Quick Sketch Fill + Contour',quick_sketch_auto=True)
        result=propose_rescue_options(plan,acceptance)
        self.assertFalse(is_quick_sketch(result))
        self.assertEqual(result['draw_quality'],'Pixel Accurate')
        self.assertFalse(result['auto_tuner_meta']['quick_sketch'])


class WatchdogPolicyTests(unittest.TestCase):
    def test_actual_draw_worker_has_no_off_deadline_but_still_observes_stop_and_shutdown(self):
        import queue
        import threading
        from unittest.mock import Mock
        import DrawBot as module
        from test_v148_application_batch04_settings import Value
        clock=[0.0];jobs=[];owned=[]
        options={'planning_watchdog':'Off','planning_timeout_seconds':15,
                 'paint_tool':'Use current tool','custom_color_workflow':'Calibrated palette',
                 'background_fill':'Off','max_seconds':3600,'unlimited_time':True}
        with Image.new('RGB',(20,20),'white') as original:
            app=SimpleNamespace(activity=None,closing=False,original=original,
                game=Value('Microsoft Paint'),corners=[(0,0),(20,20)],
                preview_after=None,preview_render_after=None,status=Mock(),summary=Mock(),root=Mock(),
                area=lambda:(0,0,20,20),options=lambda:dict(options),mouse=Mock(),
                target_window=(1,(0,0,100,100)),_refresh_target_for_draw=lambda:(0,0,100,100),
                stop=threading.Event(),paused=threading.Event(),events=queue.Queue(),
                progress={},save_settings=lambda:True,keyboard=None,
                begin_worker=lambda kind,work,**_worker_options:jobs.append(work) or True)
            def plan(image,area,resolved,cancelled):
                owned.append(image)
                clock[0]=100000.0
                self.assertFalse(cancelled(), 'Off must not expire after the configured 15 seconds')
                app.closing=True;self.assertTrue(cancelled());app.closing=False
                app.stop.set();self.assertTrue(cancelled());app.stop.clear()
                return {'options':resolved,'count':1,'estimate':1,'groups':[[(1,1,2,1)]]}
            with ExitStack() as context:
                context.enter_context(patch.object(module.time,'monotonic',side_effect=lambda:clock[0]))
                context.enter_context(patch.object(module,'log_event'))
                context.enter_context(patch.object(module,'bypasses_palette',return_value=True))
                context.enter_context(patch.object(module,'resolve_image_custom_color_workflow',return_value={}))
                context.enter_context(patch.object(module.DrawBotApp,'_disarm_full_draw'))
                context.enter_context(patch.object(module.DrawBotApp,'_strict_safety_required',return_value=False))
                context.enter_context(patch.object(module.DrawBotApp,'_run_browser_visual_preflight',return_value=(0,0,100,100)))
                context.enter_context(patch('ScreenGuard.GuardedMouse'))
                context.enter_context(patch('ScreenGuard.WindowMonitor'))
                context.enter_context(patch.object(module,'make_plan',side_effect=plan))
                execute=context.enter_context(patch.object(module,'execute_plan'))
                context.enter_context(patch('SessionRecovery.clear_render_progress'))
                try:
                    module.DrawBotApp.draw(app,user_initiated=True,paint_prepared=True)
                    self.assertEqual(len(jobs),1)
                    jobs[0]()
                    execute.assert_called_once()
                    self.assertEqual(app.start_state_machine.state,'COMPLETED')
                finally:
                    for image in owned:image.close()

    def test_off_removes_automatic_timeout_but_dry_run_keeps_its_explicit_bound(self):
        from PlanningWatchdog import build_planning_attempts
        attempt,=build_planning_attempts({'planning_watchdog':'Off','planning_timeout_seconds':15})
        self.assertIsNone(attempt.timeout_seconds)
        self.assertIsNone(attempt.options['planning_watchdog_attempt_timeout_seconds'])
        self.assertGreater(build_planning_attempts({'planning_watchdog':'Off'},dry_run=True)[0].timeout_seconds,0)

    def test_fallbacks_preserve_explicit_pixel_accuracy_and_unlimited_quality(self):
        from PlanningWatchdog import build_planning_attempts
        quality={'planning_resolution':'Extreme','color_layers':'Full color mix',
                 'background_fill':'Balanced','use_region_fill_engine':True,'background_simplification':'Off',
                 'color_rendering':'Perceptual match','custom_color_workflow':'Adaptive exact (recommended)',
                 'target_stroke_count':'Unlimited','target_stroke_count_resolved':None,'max_stroke_cap':'Unlimited'}
        for mode in ({'draw_quality':'Pixel Accurate'},{'unlimited_time':True},{'time_budget_mode':'Unlimited'}):
            with self.subTest(mode=mode):
                attempts=build_planning_attempts(dict(quality,planning_watchdog='On',**mode))
                self.assertEqual(len(attempts),3)
                for attempt in attempts:
                    for key,value in quality.items():self.assertEqual(attempt.options[key],value,key)
                self.assertEqual(attempts[-1].options['cpu_engine'],'Threads')
                self.assertEqual(attempts[-1].options['gpu_mode'],'CPU')


class AutomaticToolReadinessTests(unittest.TestCase):
    def test_invalid_optional_calibration_is_absent_evidence_not_an_auto_tool(self):
        from SmartTools import choose_paint_tool
        for data in ([1],{'tools':[]},{'tools':{'Pencil':False}},
                     {'tools':{'Pencil':(1.5,3)}},
                     {'opacity_100':False,'brush_menu':[],'brush_preset':'bad'}):
            with self.subTest(data=data):
                self.assertEqual(choose_paint_tool('Auto (recommended)','Auto',data,portrait=True,brush_px=1),
                                 'Auto (recommended)')
        self.assertEqual(choose_paint_tool('Auto (recommended)','Auto',{'tools':{'Pencil':(-30,0)}},
                                         portrait=True,brush_px=1),'Pencil')


class DetailSequencePreviewTests(unittest.TestCase):
    def test_one_pixel_detail_uses_its_own_guard_in_report_map_and_actual_preview(self):
        from PIL import ImageDraw
        from PreviewSafety import build_preview_safety_plan,draw_safe_paths,render_preview_safety_map
        options={'brush_px':9,'edge_behavior':'Hard Clip'}
        sequence=[{'color_index':0,'path':((3,8),),'brush_px':1,'detail_zoom':True}]
        safety=build_preview_safety_plan((16,16),(16,16),[[(3,8,3,8)]],None,options,
                                         execution_sequence=sequence)
        self.assertEqual(safety.meta['drawable_subpaths'],1)
        self.assertEqual(safety.meta['skipped_total'],0)
        self.assertEqual(safety.meta['safety_debug']['drawn'],1)
        self.assertEqual(safety.meta['source'],'execution_sequence')
        self.assertIn('1',safety.meta['canvas_guards_by_brush'])
        with Image.new('RGB',(16,16),'white') as preview:
            self.assertEqual(draw_safe_paths(ImageDraw.Draw(preview),safety,(16,16),(16,16),[(0,0,0)],9),(1,1))
            self.assertEqual(preview.getpixel((3,8)),(0,0,0))
            self.assertEqual(sum(pixel!=(255,255,255) for pixel in preview.get_flattened_data()),1)
            with render_preview_safety_map(preview,(16,16),safety,[(0,0,0)],9) as overlay:
                self.assertEqual(overlay.getpixel((3,8)),(95,95,95))

    def test_late_black_detail_survives_white_base_in_target_and_guarded_preview(self):
        from PreviewDiagnostics import render_quantized_target
        from PreviewSafety import draw_safe_sequence
        from PIL import ImageDraw
        palette=((0,0,0),(255,255,255),(255,0,0))
        sequence=[{'color_index':1,'path':((4,8),(12,8)),'brush_px':5},
                  {'color_index':0,'path':((8,8),),'brush_px':1,'detail_zoom':True}]
        fill=[{'color_index':2,'row_spans':[(3,3,12)]}]
        with render_quantized_target((16,16),[[(8,8,8,8)],[(4,8,12,8)]],palette,
                fill_regions=fill,background_fill_plan={'enabled':True,'color_index':2},
                execution_sequence=sequence) as target:
            self.assertEqual(target.getpixel((8,8)),(0,0,0))
            self.assertEqual(target.getpixel((4,8)),(255,255,255))
            self.assertEqual(target.getpixel((7,3)),(255,0,0))
            self.assertEqual(target.getpixel((0,0)),(255,0,0))
        with Image.new('RGB',(16,16),'red') as preview:
            draw_safe_sequence(ImageDraw.Draw(preview),(16,16),(16,16),(16,16),sequence,palette,
                               {'brush_px':5,'edge_behavior':'Hard Clip'})
            self.assertEqual(preview.getpixel((8,8)),(0,0,0))
            self.assertEqual(preview.getpixel((8,6)),(255,255,255))
            self.assertEqual(preview.getpixel((0,0)),(255,0,0))

    def test_target_sequence_observes_stop_inside_one_long_path(self):
        from PreviewDiagnostics import render_quantized_target
        calls=0
        def stop():
            nonlocal calls
            calls+=1;return calls>=4
        sequence=[{'color_index':0,'path':[(i%16,8) for i in range(5000)]}]
        with self.assertRaises(InterruptedError):
            render_quantized_target((16,16),[],[(0,0,0)],execution_sequence=sequence,cancelled=stop)


if __name__=='__main__':unittest.main()
