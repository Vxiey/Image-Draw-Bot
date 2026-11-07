"""Repeated accuracy scores share source preparation only within one operation."""
from contextlib import ExitStack,closing
import copy
import math
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image,ImageDraw

import AccuracyEvaluator
import PixelAccuracyEngine as engine
from DrawBot import make_plan
from test_pixel_accuracy_engine_v1088 import options,pm_from_index,entry
from test_v148_rendering_batch06_canvas import close_plan


PALETTE=((255,255,255),(0,0,0),(239,19,11))


def source_fixture(size=(160,112)):
    """Flat regions plus thin features produce real phases and brush corrections."""
    with closing(Image.new('RGB',(160,112),'white')) as base:
        draw=ImageDraw.Draw(base)
        draw.rectangle((9,11,74,74),fill=(0,80,205))
        draw.rectangle((86,19,149,92),fill=(239,19,11))
        draw.line((7,102,152,102),fill='black',width=1)
        for x in range(13,149,11):draw.point((x,5),fill='black')
        return base.resize(size,Image.Resampling.NEAREST)


def public_options(brush=4):
    return options(render_preset='Manual',auto_engine_resolved=True,time_budget_mode='Unlimited',
        unlimited_time=True,manual_max_seconds=0,brush_px=brush,_execution_cost_calibration_override={})


def scalar_score(pixel_map,simulated,counts,background_index,**unused):
    """Independent per-pixel categorical oracle, without production score masks."""
    drawable=np.asarray(pixel_map.drawable_mask,dtype=bool)
    edges=np.asarray(pixel_map.edge_map,dtype=np.float32)
    values=sorted(float(edges[y,x]) for y,x in np.ndindex(drawable.shape) if drawable[y,x])
    if values:
        position=(len(values)-1)*.7;lo=math.floor(position);hi=math.ceil(position)
        threshold=max(.32,values[lo]+(values[hi]-values[lo])*(position-lo))
    else:threshold=.32
    totals={key:0 for key in ('evaluation','drawable','correct','covered','target_correct','edge',
        'edge_correct','protected','protected_correct','overdraw','touched','hits','missing','wrong','spill','errors')}
    error=np.zeros(drawable.shape,np.uint8)
    for y,x in np.ndindex(drawable.shape):
        active=bool(drawable[y,x]);hits=int(counts[y,x]);painted=hits>0
        desired=int(pixel_map.palette_index[y,x]) if active else background_index
        correct=int(simulated[y,x])==desired
        missing=active and not painted
        wrong=active and painted and not correct
        spill=not active and painted and int(simulated[y,x])!=background_index
        edge=active and float(edges[y,x])>=threshold
        protected=active and bool(pixel_map.protected_mask[y,x])
        error[y,x]=1 if missing else 2 if wrong else 3 if spill else 0
        for key,value in (('evaluation',active or painted),('drawable',active),
                ('correct',(active or painted) and correct),('covered',active and painted),
                ('target_correct',active and correct),('edge',edge),('edge_correct',edge and correct),
                ('protected',protected),('protected_correct',protected and correct),
                ('overdraw',hits>1),('touched',painted),('hits',hits),('missing',missing),
                ('wrong',wrong),('spill',spill),('errors',error[y,x]!=0)):
            totals[key]+=int(value)
    accuracy=100.*totals['correct']/max(1,totals['evaluation'])
    target=100.*totals['target_correct']/max(1,totals['drawable'])
    metrics={'plan_execution_accuracy_percent':round(accuracy,4),'pixel_accuracy_percent':round(accuracy,4),
        'target_color_accuracy_percent':round(target,4),
        'coverage_percent':round(100.*totals['covered']/max(1,totals['drawable']),4),
        'edge_accuracy_percent':round(100.*totals['edge_correct']/totals['edge'] if totals['edge'] else target,4),
        'protected_accuracy_percent':round(100.*totals['protected_correct']/totals['protected'] if totals['protected'] else target,4),
        'evaluation_pixels':totals['evaluation'],'drawable_pixels':totals['drawable'],'correct_pixels':totals['correct'],
        'missing_pixels':totals['missing'],'wrong_color_pixels':totals['wrong'],'spill_pixels':totals['spill'],
        'error_pixels':totals['errors'],'covered_target_pixels':totals['covered'],'edge_pixels':totals['edge'],
        'protected_pixels':totals['protected'],'touched_pixels':totals['touched'],'overdraw_pixels':totals['overdraw'],
        'total_brush_hits':totals['hits'],'mean_hits_per_touched_pixel':round(totals['hits']/max(1,totals['touched']),5),
        'edge_threshold':round(threshold,5),'background_index':background_index,
        'background_repaint_available':background_index!=-1,
        'unrepairable_background_pixels':totals['spill'] if background_index==-1 else 0}
    return error,metrics


def comparable_plan(plan):
    from benchmark_v148_image_workflow import fingerprint
    return fingerprint({key:plan[key] for key in ('image','fitted','groups','execution_groups',
        'execution_sequence','preview','ui_previews','count','source_count','path_stats','estimate','colors')}|{
        'pixel_accuracy_meta':plan['options']['pixel_accuracy_meta'],
        'operation_timing_meta':plan['options']['operation_timing_meta']})


class SourceScoreContextTests(unittest.TestCase):
    def test_all_metrics_and_maps_match_scalar_oracle_with_holes_numeric_masks_and_backgrounds(self):
        rng=np.random.default_rng(1481201)
        for background in (-1,0,2):
            indices=rng.integers(-1,3,(11,17),dtype=np.int16)
            pm=pm_from_index(indices,edges=rng.random(indices.shape),protected=rng.random(indices.shape)>.6)
            pm.protected_mask=pm.protected_mask.astype(np.uint8)*255
            pm.drawable_mask=pm.drawable_mask.astype(np.uint8)
            context=engine.PixelScoreContext(pm)
            for field in ('palette_index','drawable_mask','edge_map','protected_mask'):
                getattr(pm,field).flags.writeable=False
            for _ in range(3):
                with self.subTest(background=background):
                    simulated=rng.integers(-1,3,indices.shape,dtype=np.int16)
                    counts=rng.integers(0,5,indices.shape,dtype=np.uint16)
                    expected=scalar_score(pm,simulated,counts,background)
                    actual=engine._score(pm,simulated,counts,background,score_context=context)
                    np.testing.assert_array_equal(actual[0],expected[0]);self.assertEqual(actual[1],expected[1])

    def test_actual_public_pipeline_shares_one_context_and_matches_full_scalar_reference(self):
        for brush,accepted in ((2,[True]),(4,[True,False])):
            with self.subTest(brush=brush),ExitStack() as stack:
                source=stack.enter_context(closing(source_fixture()))
                stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
                with patch.object(engine,'_score',new=scalar_score):
                    expected=make_plan(source,source.size,public_options(brush))
                stack.callback(close_plan,expected,source)
                contexts=[];target_calls=[];feature_builds=[];score_calls=[];checked_release=[]
                base_context=engine.PixelScoreContext;real_desired=engine._desired_index
                real_score=engine._score;real_evaluate=AccuracyEvaluator.evaluate_preview
                class TrackedContext(base_context):
                    def __init__(self,pixel_map):
                        super().__init__(pixel_map);contexts.append(weakref.ref(self))
                    def features(self,cancelled):
                        preparing=self._features is None
                        value=super().features(cancelled)
                        if preparing:feature_builds.append(id(self.pixel_map))
                        return value
                def desired(pixel_map,*args):
                    target_calls.append(id(pixel_map));return real_desired(pixel_map,*args)
                def score(pixel_map,*args,**kwargs):
                    score_calls.append(id(pixel_map));return real_score(pixel_map,*args,**kwargs)
                def evaluate(*args,**kwargs):
                    self.assertTrue(contexts)
                    self.assertTrue(all(ref() is None for ref in contexts))
                    checked_release.append(True)
                    return real_evaluate(*args,**kwargs)
                with patch.object(engine,'PixelScoreContext',TrackedContext), \
                        patch.object(engine,'_desired_index',new=desired),patch.object(engine,'_score',new=score), \
                        patch.object(AccuracyEvaluator,'evaluate_preview',new=evaluate):
                    actual=make_plan(source,source.size,public_options(brush))
                stack.callback(close_plan,actual,source)
                self.assertEqual(comparable_plan(actual),comparable_plan(expected))
                self.assertEqual(len(contexts),1);self.assertEqual(len(target_calls),1)
                self.assertEqual(len(feature_builds),1)
                self.assertGreaterEqual(len(score_calls),5);self.assertEqual(len(set(score_calls)),1)
                self.assertTrue(checked_release)
                metadata=actual['options']['pixel_accuracy_meta']
                self.assertEqual([row['accepted'] for row in metadata['passes']],accepted)
                self.assertEqual([row['phase'] for row in metadata['accuracy_checkpoints']],
                                 ['mid_detail','cleanup','correction_1'])

    def test_background_change_rebuilds_target_but_never_reuses_another_maps_context(self):
        pm=pm_from_index([[1,-1,1],[-1,2,-1]])
        sequence=[entry(1,((0,0),(2,0)))];context=engine.PixelScoreContext(pm)
        real=engine._desired_index
        with patch.object(engine,'_desired_index',wraps=real) as desired:
            for background in (0,2,2):
                result=engine.simulate_strokes(pm,sequence,PALETTE,background_index=background,score_context=context)
                expected=scalar_score(pm,result.simulated_index,result.coverage_count,background)
                np.testing.assert_array_equal(result.error_map,expected[0])
                for key,value in expected[1].items():self.assertEqual(result.metrics[key],value)
            self.assertEqual(desired.call_count,2)
        for wrong_context in (context,object()):
            with self.assertRaisesRegex(ValueError,'one unchanged PixelMap'):
                engine.simulate_strokes(copy.deepcopy(pm),sequence,PALETTE,score_context=wrong_context)

    def test_separate_public_simulations_observe_mutated_pixel_map_arrays(self):
        pm=pm_from_index([[1,-1],[1,1]])
        sequence=[entry(1,((0,0),(1,0)))];before=engine.simulate_strokes(pm,sequence,PALETTE)
        pm.palette_index[:]=2;pm.drawable_mask[:]=True;pm.edge_map[:]=.9;pm.protected_mask[:]=True
        after=engine.simulate_strokes(pm,sequence,PALETTE)
        expected=scalar_score(pm,after.simulated_index,after.coverage_count,0)
        self.assertNotEqual(before.metrics,after.metrics)
        np.testing.assert_array_equal(after.error_map,expected[0])
        for key,value in expected[1].items():self.assertEqual(after.metrics[key],value)
        self.assertFalse(any(isinstance(value,engine.PixelScoreContext) for value in vars(pm).values()))

    def test_stop_during_feature_preparation_does_not_publish_half_a_cache(self):
        pm=pm_from_index([[1,1],[1,-1]],edges=[[.1,.3],[.9,0]])
        context=engine.PixelScoreContext(pm);stop=[];real=np.percentile
        def stop_after_percentile(*args,**kwargs):
            value=real(*args,**kwargs);stop.append(True);return value
        with patch.object(engine.np,'percentile',side_effect=stop_after_percentile),self.assertRaises(InterruptedError):
            engine.simulate_strokes(pm,[entry(1,((0,0),(1,0)))],PALETTE,
                score_context=context,cancelled=lambda:bool(stop))
        self.assertIsNone(context._features)
        result=engine.simulate_strokes(pm,[entry(1,((0,0),(1,0)))],PALETTE,score_context=context)
        expected=scalar_score(pm,result.simulated_index,result.coverage_count,0)
        np.testing.assert_array_equal(result.error_map,expected[0])
        for key,value in expected[1].items():self.assertEqual(result.metrics[key],value)

    def test_cpu_policy_gpu_success_fallback_and_interrupt_keep_the_existing_routes(self):
        pm=pm_from_index([[1,1],[1,-1]])
        sequence=[entry(1,((0,0),(1,0)))];cpu=engine.simulate_strokes(pm,sequence,PALETTE)
        import PixelAccuracyGpu as gpu
        with patch.object(gpu,'simulate_cuda',side_effect=AssertionError('CPU must not dispatch')):
            actual=engine.simulate_strokes(pm,sequence,PALETTE,gpu_mode='CPU')
        np.testing.assert_array_equal(actual.error_map,cpu.error_map)
        native=(cpu.simulated_index.copy(),cpu.coverage_count.copy(),{'simulation_backend':'test-cuda-raster'})
        score=scalar_score(pm,native[0],native[1],0)
        context=engine.PixelScoreContext(pm)
        with patch.object(gpu,'simulate_cuda',return_value=native) as raster, \
                patch.object(gpu,'score_cuda_host',side_effect=lambda *a,**k:(score[0].copy(),dict(score[1]))) as score_call, \
                patch.object(engine,'_desired_index',side_effect=AssertionError('successful GPU score stays lazy')):
            actual=engine.simulate_strokes(pm,sequence,PALETTE,gpu_mode='CUDA',score_context=context)
        self.assertEqual(raster.call_args.kwargs['gpu_mode'],'CUDA')
        self.assertEqual(score_call.call_args.kwargs['gpu_mode'],'CUDA')
        np.testing.assert_array_equal(actual.error_map,cpu.error_map)
        with patch.object(gpu,'simulate_cuda',return_value=native),patch.object(gpu,'score_cuda_host',return_value=None), \
                patch.object(engine,'_desired_index',wraps=engine._desired_index) as prepared:
            for _ in range(2):
                actual=engine.simulate_strokes(pm,sequence,PALETTE,gpu_mode='Auto',score_context=context)
                np.testing.assert_array_equal(actual.error_map,cpu.error_map)
                for key,value in score[1].items():self.assertEqual(actual.metrics[key],value)
            self.assertEqual(prepared.call_count,1)
        with patch.object(gpu,'simulate_cuda',return_value=None) as raster:
            actual=engine.simulate_strokes(pm,sequence,PALETTE,gpu_mode='OpenCL')
        self.assertEqual(raster.call_args.kwargs['gpu_mode'],'OpenCL')
        self.assertEqual(actual.metrics,cpu.metrics)
        with patch.object(gpu,'simulate_cuda',return_value=native), \
                patch.object(gpu,'score_cuda_host',side_effect=InterruptedError()), \
                patch.object(engine,'_score',side_effect=AssertionError('Stop must not start CPU fallback')), \
                self.assertRaises(InterruptedError):
            engine.simulate_strokes(pm,sequence,PALETTE,gpu_mode='CUDA')


if __name__=='__main__':unittest.main()
