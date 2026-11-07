"""Portable browser calibration regressions; captures and input are always mocked."""
import copy
import ctypes
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import BrowserAutoCalibration as auto
import BrowserAutoRecalibration as retry
import BrowserBrushSize as brushes
import BrowserOneClick as one_click
import BrowserToolLayout as tools
import BrowserVisualPreflight as visual
import GarticOpacity as opacity
import LayoutFingerprintV2 as cache
from CalibrationValidation import calibration_screenshot, finite_confidence, screen_rect
import test_browser_brush_size_v1074 as brush_fixture


class BrowserBoundaryTests(unittest.TestCase):
    def test_nonfinite_confidence_cannot_reuse_previous_calibration(self):
        for value in (float('nan'),float('inf'),True,'0.99'):
            with self.subTest(value=value):
                decision=retry.plan_recalibration(None,palette_confidence=value,canvas_confidence=value)
                self.assertFalse(decision.safe_to_reuse_palette)
                self.assertFalse(decision.safe_to_reuse_canvas)
                self.assertEqual(finite_confidence(value),0)

    def test_tolerated_drift_does_not_force_recalibration(self):
        old=retry.make_layout_state((0,0,800,600),96,(100,100,700,500),[(50,550)])
        new=retry.make_layout_state((0,0,800,600),96,(101,100,701,500),[(51,550)])
        delta=retry.compare_layout_states(old,new,tolerance_px=4)
        self.assertFalse(delta.changed)
        self.assertEqual(retry.plan_recalibration(delta).action,'none')

    def test_unchanged_palette_is_reused_during_canvas_only_reflow(self):
        old=retry.make_layout_state((0,0,800,600),96,(100,100,700,500),[(50,550)])
        new=retry.make_layout_state((0,0,800,600),96,(110,100,710,500),[(51,550)])
        plan=retry.plan_recalibration(retry.compare_layout_states(old,new,tolerance_px=4))
        self.assertEqual(plan.action,'canvas-only')
        self.assertTrue(plan.safe_to_reuse_palette)

    def test_initial_layout_requires_full_calibration(self):
        state=retry.make_layout_state((0,0,800,600),96,(100,100,700,500),[(50,550)])
        self.assertEqual(retry.plan_recalibration(retry.compare_layout_states(None,state)).action,'full')

    def test_native_geometry_rejects_fraction_bool_and_overflow(self):
        for rect in ((True,0,800,600),(0.5,0,800,600),(0,0,2**40,600),(0,0,800,float('inf'))):
            with self.subTest(rect=rect),self.assertRaises(ValueError):screen_rect(rect)

    def test_single_sample_count_is_defined(self):
        self.assertEqual(visual._sample_indices(6,1),(0,))
        self.assertEqual(cache._sample_indices(7,1),(0,))

    def test_visual_preflight_validates_even_unsampled_points(self):
        image=Image.new('RGB',(800,600),'white')
        entries=[((20+i*30,550),(255,255,255)) for i in range(7)]
        entries[3]=((9000,9000),(255,255,255))
        found={'canvas_box':(100,100,700,500),'canvas_confidence':.95}
        with patch.object(visual,'detect_browser_setup',return_value=found),self.assertRaises(ValueError):
            visual.verify_browser_visual_preflight('skribbl',{'client_rect':(0,0,800,600)},(100,100,700,500),entries,screenshot=image)

    def test_visual_preflight_propagates_cancellation(self):
        image=Image.new('RGB',(800,600),'white')
        with patch.object(visual,'detect_browser_setup',side_effect=InterruptedError('cancelled')),self.assertRaises(InterruptedError):
            visual.verify_browser_visual_preflight('skribbl',{'client_rect':(0,0,800,600)},(100,100,700,500),[],screenshot=image)

    def test_retry_cannot_publish_success_after_cancellation(self):
        cancelled=[False]
        def detect(*args,**kwargs):cancelled[0]=True;return object()
        with patch.object(auto,'auto_calibrate_browser',side_effect=detect),self.assertRaises(InterruptedError):
            retry.calibrate_browser_with_retry('skribbl',{},Path('unused'),cancelled=lambda:cancelled[0])

    def test_retry_closes_owned_recaptures_but_not_callers_image(self):
        original=Image.new('RGB',(4,4),'white');captured=Image.new('RGB',(4,4),'black')
        with patch.object(auto,'auto_calibrate_browser',side_effect=[ValueError('palette confidence is too low'),SimpleNamespace()]):
            retry.calibrate_browser_with_retry('skribbl',{},Path('unused'),screenshot=original,recapture=lambda:captured,sleep_fn=lambda _:None)
        self.assertEqual(original.getpixel((0,0)),(255,255,255))
        with self.assertRaises(ValueError):captured.getpixel((0,0))

    def test_capture_context_owns_only_its_capture_and_conversions(self):
        caller=Image.new('RGBA',(20,10),'red')
        with calibration_screenshot(caller,(0,0,20,10)) as converted:
            self.assertEqual(converted.mode,'RGB')
        self.assertEqual(caller.getpixel((0,0)),(255,0,0,255))
        with self.assertRaises(ValueError):converted.getpixel((0,0))
        captured=Image.new('RGB',(20,10),'red')
        with patch('PIL.ImageGrab.grab',return_value=captured):
            with calibration_screenshot(None,(0,0,20,10)) as got:self.assertIs(got,captured)
        with self.assertRaises(ValueError):captured.getpixel((0,0))

    def test_capture_budget_rejects_before_capture(self):
        with patch('PIL.ImageGrab.grab') as grab,self.assertRaises(ValueError):
            with calibration_screenshot(None,(0,0,20000,20000)):pass
        grab.assert_not_called()

    def test_invalid_candidate_never_wins_from_context(self):
        good=SimpleNamespace(handle=1,confidence=.90,palette_count=18,canvas_box=(1,1,10,10),area=100)
        weak=SimpleNamespace(handle=2,confidence=.69,palette_count=72,canvas_box=(1,1,10,10),area=100)
        self.assertIs(one_click.choose_unique_candidate([weak,good],preferred_handle=2),good)
        for invalid in (float('nan'),float('inf'),True,2.0):
            weak.confidence=invalid
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                one_click.choose_unique_candidate([weak],min_confidence=0)

    def test_foreground_handle_keeps_pointer_width_and_uses_system_loader(self):
        function=Mock(return_value=0x100000123)
        library=SimpleNamespace(GetForegroundWindow=function)
        with patch.object(one_click.os,'name','nt'),patch.object(one_click,'load_system_library',return_value=library) as load:
            self.assertEqual(one_click._foreground_window_handle(),0x100000123)
        self.assertIs(function.restype,ctypes.c_void_p)
        self.assertEqual(function.argtypes,[])
        load.assert_called_once_with('user32.dll')

    def native_window_api(self,*,process_ok=True):
        def rect(_handle,pointer):
            box=pointer._obj;box.left=0;box.top=0;box.right=800;box.bottom=600;return 1
        def pid(_handle,pointer):pointer._obj.value=123;return int(process_ok)
        def title(_handle,buffer,length):buffer.value='Game';return 4
        return SimpleNamespace(EnumWindows=Mock(side_effect=lambda callback,value:callback(0x100000123,value)),
            IsWindowVisible=Mock(return_value=1),IsIconic=Mock(return_value=0),GetWindowRect=Mock(side_effect=rect),
            GetClientRect=Mock(side_effect=rect),ClientToScreen=Mock(return_value=1),GetWindowThreadProcessId=Mock(side_effect=pid),
            GetWindowTextLengthW=Mock(return_value=2**30),GetWindowTextW=Mock(side_effect=title),GetDpiForWindow=Mock(return_value=96))

    def test_native_enumeration_bounds_title_and_declares_callback_abi(self):
        api=self.native_window_api();dpi=SimpleNamespace(dpi=96,source='test',scale=1,monitor_rect=(0,0,1920,1080))
        with patch.object(one_click,'load_system_library',return_value=api),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True),patch.object(one_click,'get_window_dpi_info',return_value=dpi):
            results=one_click._enumerate_windows(exclude_pid=77)
        self.assertEqual(results[0]['handle'],0x100000123)
        self.assertEqual(api.GetWindowTextW.call_args.args[2],32768)
        self.assertEqual(len(api.EnumWindows.argtypes),2)

    def test_native_failed_process_lookup_never_accepts_a_window(self):
        api=self.native_window_api(process_ok=False)
        with patch.object(one_click,'load_system_library',return_value=api),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True):
            self.assertEqual(one_click._enumerate_windows(exclude_pid=77),[])
        api.GetWindowRect.assert_not_called()


class BrowserControlTests(unittest.TestCase):
    def fixture(self):return brush_fixture.AutomaticBrushSizeV1074Tests()._gartic_image()

    def test_uniform_dark_toolbar_cannot_authorize_clear_or_tools(self):
        image=Image.new('RGB',(1200,900),(40,40,40))
        plan=tools.plan_browser_tools('gartic-phone',image,(0,0,1200,900),canvas_box=(200,160,900,630))
        self.assertFalse(plan.tools)
        with self.assertRaises(ValueError):tools.build_browser_tool_action(plan.as_dict(),'Clear')

    def test_tool_action_rejects_nan_and_unknown_tool(self):
        plan={'confidence':float('nan'),'tools':{'Brush':(50,50)},'client_rect':(0,0,100,100)}
        with self.assertRaises(ValueError):tools.build_browser_tool_action(plan,'Brush')
        plan['confidence']=1
        with self.assertRaises(ValueError):tools.build_browser_tool_action(plan,'Launch')

    def test_off_client_tool_candidates_are_dropped_instead_of_edge_clamped(self):
        candidates=tools._candidates('gartic-phone',(0,0,1000,700),canvas_box=(200,0,990,600))
        self.assertEqual(candidates,{})

    def test_unverified_requested_brush_cannot_borrow_other_controls_confidence(self):
        image,client,canvas=self.fixture()
        p=brushes.plan_browser_brush_size('gartic-phone',image,client,canvas_box=canvas,requested_px=1)
        x,y=p.control_positions[0]
        ImageDraw.Draw(image).rectangle((x-16,y-16,x+16,y+16),fill=image.getpixel((x-17,y)))
        plan=brushes.plan_browser_brush_size('gartic-phone',image,client,canvas_box=canvas,requested_px=1)
        self.assertIsNone(plan.target_position)
        self.assertNotIn(0,plan.as_dict()['verified_indices'])
        self.assertNotIn(plan.nominal_sizes[0],plan.as_dict()['verified_sizes'])
        self.assertGreaterEqual(plan.safe_guard_px,max(plan.nominal_sizes))

    def test_missing_brush_evidence_reserves_largest_profile_brush(self):
        for key in ('gartic-phone','gartic-io','skribbl','sketchheads'):
            with self.subTest(key=key):
                policy=brushes.POLICIES[key]
                self.assertGreaterEqual(brushes.conservative_brush_guard(key),max(policy['sizes']))

    def test_verified_size_subset_preserves_original_control_indices(self):
        image,client,canvas=self.fixture()
        initial=brushes.plan_browser_brush_size('gartic-phone',image,client,canvas_box=canvas,requested_px=2)
        x,y=initial.control_positions[0]
        ImageDraw.Draw(image).rectangle((x-16,y-16,x+16,y+16),fill=image.getpixel((x-17,y)))
        metadata=brushes.plan_browser_brush_size('gartic-phone',image,client,canvas_box=canvas,requested_px=2).as_dict()
        self.assertEqual(metadata['verified_indices'],[1,2,3,4])
        self.assertEqual(metadata['verified_sizes'],[4,8,16,28])
        self.assertEqual(metadata['target_index'],1)

    def test_cropped_controls_are_not_recentered_into_valid_evidence(self):
        image=Image.new('RGB',(100,100),'white')
        self.assertIsNone(brushes._patch(image,(0,0,100,100),(3,40)))
        self.assertIsNone(tools._patch(image,(0,0,100,100),(3,40)))

    def test_fresh_selection_requires_the_requested_unique_control(self):
        image,client,canvas=self.fixture()
        plan=brushes.plan_browser_brush_size('gartic-phone',image,client,canvas_box=canvas,requested_px=1).as_dict()
        captures=[]
        def capture(*,bbox,all_screens):
            result=image.crop(bbox);captures.append(result);return result
        with patch('PIL.ImageGrab.grab',side_effect=capture):
            self.assertTrue(brushes.verify_brush_selection(plan,1))
            self.assertFalse(brushes.verify_brush_selection(plan,0))
        for captured in captures:
            with self.assertRaises(ValueError):captured.getpixel((0,0))

    def test_fresh_selection_rejects_malformed_metadata_without_capture(self):
        image,client,canvas=self.fixture()
        good=brushes.plan_browser_brush_size('gartic-phone',image,client,canvas_box=canvas,requested_px=1).as_dict()
        cases=[dict(good,confidence=float('nan')),dict(good,verified_indices=[True]),dict(good,verified_indices=2),dict(good,nominal_sizes=[True,*good['nominal_sizes'][1:]]),dict(good,control_positions=[(float('inf'),0)]*5)]
        with patch('PIL.ImageGrab.grab') as capture:
            for case in cases:self.assertFalse(brushes.verify_brush_selection(case,0))
        capture.assert_not_called()


class OpacityRegressionTests(unittest.TestCase):
    def test_outline_and_pixel_accuracy_override_light_sketch(self):
        image=Image.new('RGB',(128,128),'white');ImageDraw.Draw(image).rectangle((0,0,63,127),fill='black')
        for kwargs in ({'outline':True},{'draw_quality':'Pixel Accurate'}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(opacity.choose_opacity_percent(image,render_style='Quick Sketch',**kwargs)['selected_percent'],100)

    def test_hidden_transparent_pixels_do_not_change_opacity(self):
        hidden=Image.new('RGBA',(128,128),(0,0,0,0))
        for x in range(128):ImageDraw.Draw(hidden).line((x,0,x,127),fill=(x*2,x*2,x*2,0))
        white=Image.new('RGB',hidden.size,'white')
        self.assertEqual(opacity.choose_opacity_percent(hidden),opacity.choose_opacity_percent(white))

    def test_uniform_white_has_no_false_border_edges(self):
        self.assertEqual(opacity._metrics(Image.new('RGB',(80,50),'white'))[0],0)

    def test_metric_sampling_preserves_aspect_and_does_not_upscale(self):
        original=Image.Image.resize;calls=[]
        def resize(image,size,*args,**kwargs):calls.append(size);return original(image,size,*args,**kwargs)
        with patch.object(Image.Image,'resize',new=resize):opacity._metrics(Image.new('RGB',(320,8),'white'))
        self.assertTrue(calls)
        self.assertTrue(all(size==(160,4) for size in calls))

    def test_opaque_plan_still_requires_verified_slider_target(self):
        image=Image.new('RGB',(1000,700),'white');client=(0,0,1000,700);canvas=(200,140,800,500)
        with patch.object(opacity,'_slider_confidence',return_value=.9):
            plan=opacity.plan_gartic_opacity('gartic-phone',image,client,canvas_box=canvas,requested='100%')
        self.assertEqual(plan.target_position,plan.track_end)
        self.assertFalse(plan.as_dict()['opacity_state_verified'])
        with patch.object(opacity,'_slider_confidence',return_value=0):
            unknown=opacity.plan_gartic_opacity('gartic-phone',image,client,canvas_box=canvas,requested='100%')
        self.assertIsNone(unknown.target_position)
        self.assertFalse(unknown.as_dict()['control_verified'])

    def test_small_control_crop_does_not_convert_full_screenshot(self):
        image=Image.new('RGBA',(1920,1080),'white');original=Image.Image.convert;sizes=[]
        def convert(value,*args,**kwargs):sizes.append(value.size);return original(value,*args,**kwargs)
        with patch.object(Image.Image,'convert',new=convert):
            crop=opacity._screen_crop(image,(0,0,1920,1080),(50,50,150,80))
        self.assertEqual(crop.size,(100,30))
        self.assertEqual(sizes,[(100,30)])


class LayoutCacheRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'cache.json';self.palette_path=Path(self.tmp.name)/'palette.json'
        self.meta={'client_rect':(0,0,800,600),'dpi':96}
        self.canvas=(100,100,700,500)
        self.palette=[{'name':str(i),'position':[30+i*30,550],'rgb':[255,255,255]} for i in range(7)]
        self.image=Image.new('RGB',(800,600),'white')

    def record(self,**kwargs):return cache.record_layout('skribbl',self.meta,self.canvas,kwargs.get('palette',self.palette),path=self.path)

    def test_malformed_optional_cache_is_a_miss(self):
        self.record();original=json.loads(self.path.read_text())
        for field,value in [('dpi','bad'),('palette',[None]),('browser_zoom_hint',float('nan')),('canvas_rel',[0,0,900,900])]:
            raw=copy.deepcopy(original);raw['entries'][0][field]=value
            self.path.write_text(json.dumps(raw))
            with self.subTest(field=field):
                self.assertFalse(cache.try_restore('skribbl',self.meta,self.palette_path,screenshot=self.image,path=self.path).hit)
        self.assertFalse(self.palette_path.exists())

    def test_unsampled_cached_point_must_be_inside_client_and_outside_canvas(self):
        for point in ([9000,9000],[400,400],[30,550]):
            self.record();raw=json.loads(self.path.read_text());raw['entries'][0]['palette'][3]['rel']=point
            self.path.write_text(json.dumps(raw))
            with self.subTest(point=point):
                self.assertFalse(cache.try_restore('skribbl',self.meta,self.palette_path,screenshot=self.image,path=self.path).hit)
        self.assertFalse(self.palette_path.exists())

    def test_optional_last_used_failure_does_not_undo_success(self):
        self.record()
        with patch.object(cache,'save_cache',side_effect=PermissionError('read-only cache')):
            result=cache.try_restore('skribbl',self.meta,self.palette_path,screenshot=self.image,path=self.path)
        self.assertTrue(result.hit)
        self.assertTrue(self.palette_path.exists())

    def test_signature_includes_exact_palette_location(self):
        a=[(30+i*30,550) for i in range(7)];b=[(40+i*30,550) for i in range(7)]
        self.assertNotEqual(cache.zoom_signature(self.meta['client_rect'],self.canvas,a)[0],cache.zoom_signature(self.meta['client_rect'],self.canvas,b)[0])

    def test_cache_writer_drops_unvalidated_extras_before_reader_budget(self):
        self.record();data=cache.load_cache(self.path)
        data['entries'][0]['unknown_extra']=[0]*80000
        cache.save_cache(data,self.path)
        restored=cache.load_cache(self.path)
        self.assertEqual(len(restored['entries']),1)
        self.assertNotIn('unknown_extra',restored['entries'][0])

    def test_concurrent_records_preserve_both_layouts(self):
        def record(offset):
            palette=[dict(row,position=[row['position'][0]+offset,550]) for row in self.palette]
            self.record(palette=palette)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(record,(0,5)))
        self.assertEqual(len(cache.load_cache(self.path)['entries']),2)

    def test_cache_seed_requires_verified_owner_and_resolves_translation(self):
        from Colors import save_calibration
        source=Path(self.tmp.name)/'source.json'
        points=[row['position'] for row in self.palette];rgb=[(10*i,20,30) for i in range(7)]
        save_calibration(points,rgb,source,profile_key='skribbl',state='calibrated')
        with self.assertRaises(ValueError):cache.record_from_calibration_file('skribbl',self.meta,self.canvas,source,path=self.path)
        save_calibration(points,rgb,source,profile_key='skribbl',state='verified',anchor={'version':1,'client_rect':[0,0,800,600]})
        moved={'client_rect':(100,100,900,700),'dpi':96}
        result=cache.record_from_calibration_file('skribbl',moved,(200,200,800,600),source,path=self.path)
        self.assertEqual(result['palette'][0]['rel'],[30,550])


if __name__=='__main__':unittest.main()
