"""Regression coverage for the 100-fix maintenance release.

Uses isolated files, synthetic images and a fake clock; never sends input.
"""
import copy
import json
import math
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
import ColorCache as cache
import ProfilePortability as portability
import ProfileStorage as storage
import RenderResume as resume
from ColorPreviewDiagnostics import fidelity_rating, should_auto_remap
from DeadlineScheduler import DeadlineScheduler
from HybridCostModel import build_cost_model
from PlanningWatchdog import build_planning_attempts
from Precision import CanvasTransform, effective_step, map_pixel_center, profile
from PreviewLayers import build_auxiliary_previews
from PreviewQuality import full_preview_options, viewport_image
from PreviewSafety import PreviewSafetyPlan, draw_safe_paths, render_preview_safety_map, _preview_polygon_options
from RuntimePaths import atomic_write_text
from TimeBudget import resolve_target_stroke_count, apply_target_path_cap
from TimeBudgetEngine import resolve_budget, automatic_reserve, classify_budget
from UIState import classify_error, compute_workspace_state


class VerifiedCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'cache.json'
        self.patcher = patch.object(cache, 'cache_path', return_value=self.path)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.context = dict(context_fingerprint='ctx', workflow='numeric')

    def put(self, rgb=(1,2,3), **extra):
        return cache.put_verified('test', rgb, rgb, delta_e2000=0, method='numeric', **self.context, **extra)

    def load(self):
        return cache.load_cache('test', **self.context)

    def test_malformed_schema_and_bom(self):
        self.put(); data=json.loads(self.path.read_text())
        for version in ('bad', 2.0, True, {}, None):
            data['version']=version; self.path.write_text(json.dumps(data))
            self.assertEqual(self.load(), {})
        data['version']=2;self.path.write_text('\ufeff'+json.dumps(data),encoding='utf-8')
        self.assertIn('010203', self.load())

    def test_oversize_file_is_not_loaded(self):
        self.path.write_bytes(b' '*(cache.MAX_CACHE_BYTES+1))
        self.assertEqual(self.load(), {})

    def test_rgb_validation_before_write(self):
        for rgb in ((1,2), (1,2,3,4), (-1,2,3), (256,2,3), (1.5,2,3), (True,2,3)):
            with self.subTest(rgb=rgb), self.assertRaises(ValueError): self.put(rgb)
        self.assertFalse(self.path.exists())

    def test_quality_validation_before_write(self):
        for confidence in (-1,101,float('nan'),float('inf')):
            with self.subTest(confidence=confidence), self.assertRaises(ValueError): self.put(confidence=confidence)
        for de in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                cache.put_verified('test',(1,2,3),(1,2,3),delta_e2000=de,method='numeric',**self.context)
        self.assertFalse(self.path.exists())

    def test_tampered_entries_are_filtered_independently(self):
        self.put();data=json.loads(self.path.read_text());original=copy.deepcopy(data)
        for field, value in [('requested_rgb',[9,8,7]),('created_rgb',[]),('verified','true'),
                             ('context_fingerprint','old'),('workflow','other'),('confidence',101),('delta_e2000',-1)]:
            with self.subTest(field=field):
                data=copy.deepcopy(original);data['colors']['010203'][field]=value
                self.path.write_text(json.dumps(data));self.assertEqual(self.load(),{})

    def test_concurrent_updates_are_retained(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i:self.put((i,0,0)), range(24)))
        self.assertEqual(len(self.load()),24)

    def test_eviction_refresh_and_direct_save_cap(self):
        with patch.object(cache,'MAX_COLORS',3):
            for i in range(3):self.put((i,0,0))
            self.put((0,0,0));self.put((3,0,0))
            self.assertEqual(set(self.load()), {'000000','020000','030000'})
        colors=self.load()
        with patch.object(cache,'MAX_COLORS',2):
            cache.save_cache('test',colors,**self.context)
            self.assertEqual(len(self.load()),2)

    def test_atomic_cache_uses_shared_writer(self):
        with patch.object(cache,'atomic_write_text',wraps=atomic_write_text) as writer:
            self.put();self.assertEqual(writer.call_count,1)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()],['cache.json'])


class StorageTests(unittest.TestCase):
    def test_failed_encoding_removes_temporary_and_preserves_destination(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'settings.json';path.write_text('original')
            with self.assertRaises(UnicodeEncodeError):atomic_write_text(path,'é',encoding='ascii')
            self.assertEqual(path.read_text(),'original');self.assertEqual(list(Path(td).iterdir()),[path])

    def test_empty_appdata_fallback(self):
        import RuntimePaths
        with tempfile.TemporaryDirectory() as td, patch.object(RuntimePaths,'is_frozen',return_value=True), \
                patch.dict('os.environ',{'LOCALAPPDATA':''}), patch.object(RuntimePaths.Path,'home',return_value=Path(td)):
            self.assertEqual(RuntimePaths.data_dir(),Path(td)/'ImageDrawBot')

    def test_profile_names_are_isolated_and_idempotent(self):
        for a,b in [('a/b','a-b'),('a'*81+'x','a'*81+'y')]:
            self.assertNotEqual(storage.safe_profile_key(a),storage.safe_profile_key(b))
        for name in ('microsoft-paint','custom-'+'a'*32,'a/b','a'*99):
            key=storage.safe_profile_key(name)
            self.assertEqual(storage.safe_profile_key(key),key);self.assertLessEqual(len(key),80)

    def test_fingerprints_frame_extras_and_detect_file_change(self):
        with tempfile.TemporaryDirectory() as td, patch.object(storage,'data_dir',return_value=Path(td)):
            first=storage.calibration_context_fingerprint('test',extras=['a\nextra:b'])
            second=storage.calibration_context_fingerprint('test',extras=['a','b'])
            self.assertNotEqual(first,second)
            path=storage.profile_palette_file('test');path.write_bytes(b'a'*140000)
            before=storage.calibration_context_fingerprint('test')
            path.write_bytes(b'a'*139999+b'b')
            self.assertNotEqual(before,storage.calibration_context_fingerprint('test'))


class BudgetTests(unittest.TestCase):
    def test_unrelated_manual_limit_does_not_block_fixed_modes(self):
        for value in (1,99999,float('nan'),float('inf')):
            self.assertTrue(resolve_budget('Unlimited / Accuracy',value)['unlimited'])
            self.assertEqual(resolve_budget('Skribbl 60',value)['total_seconds'],60)
            with self.assertRaises(ValueError):resolve_budget('Custom',value)

    def test_explicit_zero_reserve_and_trimmed_mode(self):
        self.assertEqual(resolve_budget(' Skribbl 60 ',reserve=0)['reserve_seconds'],0)
        self.assertGreater(resolve_budget('Skribbl 60')['reserve_seconds'],0)

    def test_invalid_estimates_and_budgets_fail_closed(self):
        for value in (None,'bad',-1,float('nan'),float('inf')):
            self.assertEqual(classify_budget(value,30),'PANIC')
            self.assertEqual(classify_budget(1,value),'SAFE' if value is None else 'PANIC')
        for value in (-1,0,float('nan'),float('inf')):
            with self.assertRaises(ValueError):automatic_reserve(value)

    def test_accuracy_auto_is_unlimited_in_metadata(self):
        cap,meta=resolve_target_stroke_count('Auto',time_budget_mode='Unlimited / Accuracy')
        self.assertIsNone(cap);self.assertFalse(meta['time_budget_active'])

    def test_partial_selection_preserves_importance_and_color_order(self):
        groups=[[((0,0),(10,0)),((0,0),(2,0))],[((0,0),(20,0)),((1,1),)]]
        actual,meta=apply_target_path_cap(groups,2)
        self.assertEqual(actual,[[groups[0][0]],[groups[1][0]]]);self.assertEqual(meta['target_skipped_paths'],2)


class PreviewTests(unittest.TestCase):
    def test_transparency_and_tiny_fill_layers(self):
        for size in ((1,1),(2,2),(3,3)):
            maps=build_auxiliary_previews(Image.new('RGBA',(8,8),(200,10,20,0)),size,[],[],lambda x,y:(x,y),1,
                                           {'background_fill_plan':{'enabled':True}})
            self.assertEqual(maps['color'].getpixel((0,0)),(255,255,255))
            self.assertEqual(maps['fill'].size,size)

    def test_dot_sampling_is_bounded(self):
        paths=[[(i%20,i//20)] for i in range(101)]
        opts={'_preview_plan':True,'_preview_stroke_map_limit':10,'_preview_safety_groups':[paths]}
        with patch.object(ImageDraw.ImageDraw,'ellipse') as dot:
            build_auxiliary_previews(Image.new('RGB',(20,20)),(20,20),[],[(255,0,0)],lambda x,y:(x,y),1,opts)
            self.assertLessEqual(dot.call_count,10);self.assertGreater(dot.call_count,0)

    def test_segment_sampling_is_bounded(self):
        strokes=[(0,0,5,5)]*19
        with patch.object(ImageDraw.ImageDraw,'line') as line:
            build_auxiliary_previews(Image.new('RGB',(20,20)),(20,20),[strokes],[(255,0,0)],lambda x,y:(x,y),1,
                                     {'_preview_plan':True,'_preview_stroke_map_limit':10})
            self.assertLessEqual(line.call_count,10)

    def test_cancellation_reaches_fill_regions(self):
        calls=[0]
        def cancel():calls[0]+=1;return calls[0]>1
        with self.assertRaises(InterruptedError):
            build_auxiliary_previews(Image.new('RGB',(20,20)),(20,20),[],[],lambda x,y:(x,y),1,
                                     {'fill_regions':[{'bbox':(1,1,5,5)}]},cancelled=cancel)

    def test_empty_safe_paths_and_small_labels(self):
        plan=PreviewSafetyPlan([[(),((0,0),)]],'Hard Clip',{'stopped':True})
        draw=ImageDraw.Draw(Image.new('RGB',(5,5)))
        self.assertEqual(draw_safe_paths(draw,plan,(5,5),(5,5),[(0,0,0)],1),(1,1))
        for size in ((1,1),(16,16),(32,32)):
            self.assertEqual(render_preview_safety_map(None,size,plan,[(0,0,0)],1).size,size)

    def test_safe_path_cancel_in_long_path(self):
        calls=[0]
        def cancel():calls[0]+=1;return calls[0]>=3
        plan=PreviewSafetyPlan([[tuple((i,0) for i in range(2000))]],'Hard Clip')
        with self.assertRaises(InterruptedError):
            draw_safe_paths(ImageDraw.Draw(Image.new('RGB',(5,5))),plan,(2000,5),(5,5),[],1,cancelled=cancel)

    def test_safety_map_propagates_cancellation(self):
        plan=PreviewSafetyPlan([[((0,0),)]],'Hard Clip')
        with self.assertRaises(InterruptedError):render_preview_safety_map(None,(50,50),plan,[],1,cancelled=lambda:True)

    def test_preview_metadata_is_detached(self):
        plan=PreviewSafetyPlan([],'Hard Clip',{'canvas_guard':{'area':[0,0,10,10]}})
        meta=plan.as_dict();meta['canvas_guard']['area'][0]=999
        self.assertEqual(plan.meta['canvas_guard']['area'][0],0)

    def test_absolute_polygon_survives_full_preview(self):
        opts=full_preview_options({'target_area':(100,200,300,400),'canvas_polygon_space':'screen',
                                  'canvas_polygon':[(100,200),(400,200),(400,600),(100,600)]},(300,400))
        polygon,space,_=_preview_polygon_options(opts,(300,400))
        self.assertEqual(polygon,((0,0),(300,0),(300,400),(0,400)));self.assertEqual(space,'area')
        self.assertEqual(opts['_preview_area'],(300,400))

    def test_invalid_view_settings_have_safe_defaults(self):
        source=Image.new('RGB',(30,20),'red')
        baseline,scale=viewport_image(source,(60,60))
        for zoom,pan in [('bad',None),(float('nan'),(1,)),(float('inf'),(float('inf'),0))]:
            actual,actual_scale=viewport_image(source,(60,60),zoom=zoom,pan=pan)
            self.assertEqual(actual.tobytes(),baseline.tobytes());self.assertEqual(actual_scale,scale)
        # Viewport preferences may fall back, but an invalid resource limit
        # cannot silently authorize native-resolution planning.
        with self.assertRaises(ValueError):
            full_preview_options({'ram_budget_mb':'bad'},(100,100))
        with self.assertRaises(ValueError):viewport_image(Image.new('RGB',(0,0)),(20,20))

    def test_image_label_does_not_convert_opaque_or_alpha_sources(self):
        from ImageFormatInfo import image_label
        for mode in ('RGB','RGBA','L'):
            source=Image.new(mode,(20,20))
            with patch.object(source,'convert',side_effect=AssertionError('full conversion')):
                label=image_label(source,'example');self.assertIn('20 × 20',label)

    def test_bad_color_diagnostics_are_not_quality_claims(self):
        for value in ('bad',float('nan'),float('inf'),-1):
            self.assertEqual(fidelity_rating(average_delta_e2000=value,luminance_drift_percent=0),'Unavailable')
        for diag in (None,[],{'average_delta_e2000':'bad'},{'dark_bias_detected':'false'}):
            self.assertFalse(should_auto_remap(diag))
        self.assertTrue(should_auto_remap({'average_delta_e2000':9}))


class ResumeTests(unittest.TestCase):
    def plan(self):
        return dict(options={'color_order':[0,0,1,float('inf')]},image=Image.new('RGBA',(2,2),(0,0,0,255)),
                    groups=[[(0,0,1,0)],[(0,1,1,1)]],execution_groups=[[((0,0),(1,0))],[((0,1),(1,1))]],
                    colors=[(0,0,0),(255,0,0)],fitted=(2,2),count=2)

    def test_color_order_preserves_visits_and_supports_execution_only(self):
        plan=self.plan();self.assertEqual(resume.active_color_order(plan),[0,0,1])
        plan.pop('groups');self.assertEqual(resume.active_color_order(plan),[0,0,1])
        with self.assertRaises(ValueError):resume.batch_key(plan,-1)

    def test_alpha_changes_invalidate_checkpoint(self):
        plan=self.plan();state=resume.checkpoint_after_batch(plan,1)
        plan['image'].putpixel((0,0),(0,0,0,0))
        self.assertFalse(resume.resolve_resume(plan,state)['compatible'])

    def test_corrupt_checkpoint_fields_are_rejected(self):
        plan=self.plan();state=resume.checkpoint_before_path(plan,2,0,1,ordered_items=plan['execution_groups'][0])
        self.assertIsNotNone(resume.validate_progress(state))
        invalid=[('schema',True),('plan_fingerprint','z'*64),('total_colors',-1),('completed_count',3),
                 ('completed_count',1.0),('prelude_complete','false'),('path_level','false'),
                 ('completed_keys',['bad']),('completed_keys',state['completed_keys']*2),
                 ('active_color_index',-1),('next_path_index',-1),('active_path_count',-1),
                 ('active_items_fingerprint','x'*64),('active_batch_key','g'*20)]
        for key,value in invalid:
            with self.subTest(key=key):
                corrupt=dict(state);corrupt[key]=value;self.assertIsNone(resume.validate_progress(corrupt))

    def test_checkpoint_creation_rejects_bad_indices_and_count(self):
        plan=self.plan();items=plan['execution_groups'][0]
        for index,count in [(-1,1),(2,1),(0,2),(True,1)]:
            with self.assertRaises(ValueError):resume.checkpoint_before_path(plan,1,index,count,ordered_items=items)

    def test_streamed_fingerprint_matches_compact_json_reference(self):
        # Tuple/list representations remain interchangeable for serialized geometry.
        plan=self.plan();first=resume.plan_fingerprint(plan)
        plan['execution_groups']=json.loads(json.dumps(plan['execution_groups']))
        self.assertEqual(first,resume.plan_fingerprint(plan))


class CostAndPrecisionTests(unittest.TestCase):
    def test_bad_calibration_falls_back(self):
        for cal in (None,[],{'samples':'bad','operation_runtime':{'path':{'count':'bad'}}}):
            with patch('DrawTimeCalibration.correction_for',return_value=cal):
                model=build_cost_model({});self.assertEqual(model.samples,0)
                self.assertTrue(math.isfinite(model.path_seconds(((0,0),(100,0)))))

    def test_typed_dot_cost_and_distance_floor(self):
        with patch('DrawTimeCalibration.correction_for',return_value={'samples':3,'operation_runtime':{'dot':{'average_seconds':2}}}):
            model=build_cost_model({})
        self.assertGreaterEqual(model.path_seconds(((0,0),)),2)
        model=replace(model,learned_path_floor_seconds=5,travel_seconds_per_px=.1)
        self.assertGreaterEqual(model.distance_path_seconds(1,travel_px=10),6)
        for distance in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):model.distance_path_seconds(distance)

    def test_precision_data_and_geometry_are_validated(self):
        original=profile('High');modified=profile('High');modified['max_step_px']=999
        self.assertEqual(profile('High'),original)
        for value in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):CanvasTransform(10,10,(value,10))
            with self.assertRaises(ValueError):CanvasTransform(10,10,(10,10),left=value)
            with self.assertRaises(ValueError):map_pixel_center(value,10,10)
            with self.assertRaises(ValueError):map_pixel_center(1,10,10,origin=value)
        self.assertEqual(effective_step('High','bad'),4)


class ProfileImportTests(unittest.TestCase):
    def package(self):return portability.build_package('Microsoft Paint',{'quality':'Balanced'})

    def test_nonfinite_numbers_and_wrong_sections_rejected(self):
        for value in (float('nan'),float('inf')):
            package=self.package();package['settings']['renderer']['contrast']=value
            with self.assertRaises(portability.ProfilePortabilityError):portability.validate_package(package)
        for section in ('canvas','settings','calibration','safety'):
            package=self.package();package[section]=[]
            with self.assertRaises(portability.ProfilePortabilityError):portability.validate_package(package)
        package=self.package();package['settings']['typo']={}
        with self.assertRaises(portability.ProfilePortabilityError):portability.validate_package(package)

    def test_bom_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'profile.drawprofile';path.write_text('\ufeff'+json.dumps(self.package()),encoding='utf-8')
            self.assertEqual(portability.read_profile_file(path)['profile']['name'],'Microsoft Paint')
            path.write_text('{"schema_version":0,"schema_version":1}')
            with self.assertRaises(portability.ProfilePortabilityError):portability.read_profile_file(path)

    def test_large_and_deep_profiles_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'profile.json'
            path.write_text('['*1500+'0'+']'*1500)
            with self.assertRaises(portability.ProfilePortabilityError):portability.read_profile_file(path)
            path.write_text(' '*(portability.MAX_PROFILE_BYTES+1))
            with self.assertRaises(portability.ProfilePortabilityError):portability.read_profile_file(path)
        nested={};root=nested
        for _ in range(30):nested['next']={};nested=nested['next']
        with self.assertRaises(portability.ProfilePortabilityError):portability.validate_package(root)

    def test_zero_area_canvas_rejected(self):
        for corners in ([[1,2],[1,20]],[[1,2],[20,2]]):
            package=self.package();package['canvas']['corners']=corners
            with self.assertRaises(portability.ProfilePortabilityError):portability.validate_package(package)

    def test_copy_names_fit_and_avoid_case_collision(self):
        first=portability.unique_copy_name('X'*50,[]);self.assertLessEqual(len(first),50)
        self.assertTrue(first.endswith('(Imported)'))
        second=portability.unique_copy_name('X'*50,[first.lower()])
        self.assertNotEqual(first.casefold(),second.casefold());self.assertLessEqual(len(second),50)

    def test_import_does_not_mutate_during_activity_or_failed_save(self):
        for activity in ('draw',None):
            app=SimpleNamespace(activity=activity,save_settings=Mock(side_effect=OSError('disk full')))
            with patch.object(portability,'apply_package_to_paths') as apply:
                with self.assertRaises(portability.ProfilePortabilityError):portability.import_package_into_app(app,self.package())
                apply.assert_not_called()
            self.assertEqual(app.save_settings.call_count,0 if activity else 1)


class RuntimeAndUITests(unittest.TestCase):
    def test_watchdog_values_and_disabled_fills(self):
        for value in (float('nan'),float('inf'),'bad'):
            attempts=build_planning_attempts({'planning_timeout_seconds':value,'cpu_workers_resolved':float('inf')})
            self.assertTrue(all(math.isfinite(a.timeout_seconds) for a in attempts))
        source={'use_region_fill_engine':True}
        self.assertFalse(build_planning_attempts(source,dry_run=True)[0].options['use_region_fill_engine'])
        self.assertFalse(build_planning_attempts(source)[-1].options['use_region_fill_engine'])

    def test_unlimited_fallback_keeps_quality_choices(self):
        opts={'time_budget_mode':'Unlimited / Accuracy','target_stroke_count':'Unlimited','target_stroke_count_resolved':None,
              'max_stroke_cap':'Unlimited','color_rendering':'Perceptual match','custom_color_workflow':'Exact custom',
              'background_simplification':'Off'}
        for attempt in build_planning_attempts(opts):
            for key,value in opts.items():self.assertEqual(attempt.options[key],value)

    def scheduler(self,entry=None,budget=10):
        self.now=0
        entry=entry or {'estimated_cost_seconds':1,'phase':'structure'}
        return DeadlineScheduler([entry],start_time=0,budget_seconds=budget,clock=lambda:self.now),entry

    def test_invalid_scheduler_inputs_rejected(self):
        for value in (-1,0,float('nan'),float('inf')):
            with self.assertRaises(ValueError):self.scheduler(budget=value)
        for value in (-1,float('nan'),float('inf'),'bad'):
            with self.assertRaises(ValueError):self.scheduler({'estimated_cost_seconds':value})
        sched,_=self.scheduler();self.now=float('nan')
        with self.assertRaises(ValueError):sched.remaining_time()

    def test_scheduler_snapshot_and_score_normalization(self):
        entry={'estimated_cost_seconds':1,'phase':'structure','importance':0,'structural_score':float('nan')}
        sched,_=self.scheduler(entry);entry['importance']=1
        self.assertEqual(sched.sequence[0]['importance'],0)
        self.assertTrue(math.isfinite(sched.structural_total))
        self.assertEqual(sched._score({'importance':0},'importance',.5),0)
        self.assertEqual(sched._score({'importance':5},'importance',.5),1)

    def test_no_reused_measurement_and_no_unstarted_sample(self):
        sched,entry=self.scheduler();sched.before(entry);self.now=1;sched.after(entry)
        self.now=100;sched.after(entry)
        self.assertEqual(sched.telemetry()['runtime_samples'],1)
        self.assertEqual(sched._actual_active_seconds,1)
        sched,entry=self.scheduler();sched.after(entry)
        self.assertEqual(sched.telemetry()['runtime_samples'],0)

    def test_skip_reasons_distinguish_budget_from_low_value(self):
        sched,entry=self.scheduler(budget=.5)
        self.assertFalse(sched.before(entry).execute)
        self.assertEqual(sched.skipped,1);self.assertEqual(sched.skipped_low_value,0)
        self.assertEqual(sum(sched.telemetry()['skip_reasons'].values()),1)

    def test_workspace_requires_target_and_prioritizes_activity(self):
        opts=dict(image_loaded=True,target_name='',paint_tools_ready=True,area_ready=True,palette_ready=True,
                  test_passed=True,target_locked=True)
        self.assertFalse(compute_workspace_state(**opts).ready)
        state=compute_workspace_state(**opts,activity='draw',status='Error: old problem')
        self.assertEqual(state.label,'Drawing')

    def test_actionable_error_categories(self):
        cases={'preview timeout':'Preview planning was too heavy','Start locked':'Start is still safely locked',
               'Error: GPU color mapping':'GPU acceleration issue','No space left on device':'Storage is full',
               'Permission denied':'File cannot be written','Cannot identify image file':'Image could not be opened',
               'No module named numpy':'A required component is missing','Out of memory':'Not enough memory'}
        for message,title in cases.items():
            with self.subTest(message=message):self.assertEqual(classify_error(message)['title'],title)
        self.assertIsNone(classify_error('Stopped.'))


if __name__ == '__main__':unittest.main()
