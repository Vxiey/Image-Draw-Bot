"""Paired public renderer dispatch and exact brush-candidate retention measurements."""
import argparse
import ast
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image,ImageDraw,__version__ as pillow_version

from benchmark_v148_image_workflow import fingerprint,measured_pair
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_candidates import component
from test_v148_rendering_batch10_dispatch import pixel_options
from test_v148_rendering_batch10_single_brush import options as multibrush_options


ROOT=Path(__file__).resolve().parent
BASELINE='3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973'


def previous_function(module,name,revision):
    """Replace only this function; every other dependency remains current."""
    source=subprocess.check_output(['git','show',f'{revision}:{module.__name__}.py'],cwd=ROOT).decode('utf-8')
    node=next(item for item in ast.parse(source).body if isinstance(item,ast.FunctionDef) and item.name==name)
    scope=dict(vars(module))
    exec(compile(ast.Module(body=[node],type_ignores=[]),f'{revision}:{module.__name__}.{name}','exec'),scope)
    return scope[name],hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest()


def core_plan(value):
    return {'image':value['image'],'preview':value['preview'],'colors':value['colors'],
        'fitted':value['fitted'],'groups':value['groups'],'execution_groups':value['execution_groups'],
        'execution_sequence':value['execution_sequence'],'count':value['count'],
        'source_count':value['source_count'],'estimate':value['estimate'],
        'operation_timing_meta':value['options']['operation_timing_meta']}


def plane_retention(helper,target,residual,model,comp):
    refs=[];peaks=[];real=np.zeros_like
    def allocate(*args,**kwargs):
        result=real(*args,**kwargs)
        if result.shape==target.shape and result.dtype==np.bool_:
            refs.append(weakref.ref(result));peaks.append(sum(ref() is not None for ref in refs))
        return result
    with patch.object(np,'zeros_like',side_effect=allocate):
        paths,painted,cost=helper(target,residual,16,model=model,comp=comp,phase='foundation',final_size=False)
    return {'allocated_trial_planes':len(refs),'maximum_live_trial_planes':max(peaks),
        'bytes_per_plane':target.nbytes,'live_trial_payload_peak_bytes':max(peaks)*target.nbytes,
        'retained_result_planes':sum(ref() is not None for ref in refs)}


def measure(revision=BASELINE,repeats=5):
    import DrawBot
    import AdaptiveRegionHybrid as regional
    from ExecutionCostModel import build_cost_model
    old_plan,old_plan_hash=previous_function(DrawBot,'make_plan',revision)
    old_candidates,old_candidates_hash=previous_function(regional,'_candidate_paths_for_brush',revision)
    new_candidates=regional._candidate_paths_for_brush
    names=('DrawBot','AdaptiveRegionHybrid','AutoDrawing','ExtraFastProfilePolicy','PixelStrokeEngine',
        'PixelAccuracyEngine','PixelAccuratePlanner','AdaptiveBrushEngine','ExecutionCostModel','StrokeDelivery',
        'PreviewSafety','SubjectFocus','ResourceAllocation','ColorFidelity','ColorMatchingEngine','NativeBrushProjection',
        'benchmark_v148_image_workflow','benchmark_v148_rendering_batch10',
        'test_v148_rendering_batch10_candidates','test_v148_rendering_batch10_dispatch',
        'test_v148_rendering_batch10_single_brush','test_v148_rendering_batch06_canvas',
        'test_v148_rendering_batch07_transparency','test_v148_rendering_batch09_subject',
        'test_pixel_accurate_v1086','test_rc6_region_brush_packing')
    def hashes():return {name:hashlib.sha256((ROOT/(name+'.py')).read_bytes()).hexdigest() for name in names}
    sources=hashes()
    result={'baseline':revision,'python':sys.version.split()[0],'platform':platform.platform(),
        'numpy':np.__version__,'pillow':pillow_version,'repeats':repeats,
        'method':'One warm/parity pair, five interleaved before/after timing pairs by default, separate traced peaks after garbage collection.',
        'memory_scope':'Python/NumPy traced allocations, not process RSS or most native Pillow pixel-core storage. Separate weak-reference instrumentation measures candidate Boolean-plane liveness directly.',
        'baseline_function_sha256':{'DrawBot.make_plan':old_plan_hash,
            'AdaptiveRegionHybrid._candidate_paths_for_brush':old_candidates_hash},
        'source_sha256':sources,'measurements':{}}
    output=result['measurements']
    with patch('DrawTimeCalibration.load_profile',return_value=None):
        with closing(Image.new('RGB',(64,48),'white')) as source:
            draw=ImageDraw.Draw(source)
            draw.rectangle((4,4,59,43),fill=(0,80,205))
            draw.rectangle((21,14,42,33),fill=(239,19,11));draw.point((12,12),fill='black')
            options=pixel_options(time_budget_mode='Unlimited',unlimited_time=True)
            def plan_call(planner):
                value=planner(source,source.size,options)
                try:
                    comparison=core_plan(value)
                    # The obsolete wrapper reconstructed source runs from its
                    # alternative geometry. Their representation/count is part
                    # of the ownership correction, not executable parity.
                    comparison.pop('groups');comparison.pop('source_count')
                    return fingerprint(comparison)
                finally:close_plan(value,source)
            output['R1001_actual_extra_fast_pixel_art_make_plan']={
                **measured_pair(lambda:plan_call(old_plan),lambda:plan_call(DrawBot.make_plan),repeats),
                'parameters':{'size':[64,48],'source':'blue rectangle4,4..59,43; red rectangle21,14..42,33; black dot12,12; white background','options':options},
                'isolation':'Only make_plan dispatch is taken from the baseline. Both calls share all current downstream engines, including R1002/R1003, finish_plan, cost/calibration and UI previews.',
                'comparison':'Complete executable sequence/groups, source image, colors, fitted geometry, actual main preview, executable count, estimate and operation timing. Source-run representation/count, Coverage images and regional metadata intentionally change with R1001 ownership; no whole-plan metadata parity claim. This interior fixture avoids the obsolete hybrid-preview override at canvas edges.',
                'timing_scope':'Whole public planning call plus identical result fingerprinting and owned-image cleanup.'}

        target=np.ones((96,128),bool);residual=target.copy();comp=component(target.shape)
        model=build_cost_model(multibrush_options(),(128,96),(128,96))
        def helper_call(helper):
            return helper(target,residual,16,model=model,comp=comp,phase='foundation',final_size=False)
        output['R1002_candidate_selection_128x96_16px']={
            **measured_pair(lambda:helper_call(old_candidates),lambda:helper_call(new_candidates),repeats),
            'parameters':{'size':[128,96],'brush_px':16,'target':'solid Boolean ROI','residual':'whole ROI'},
            'comparison':'Every winning path coordinate, every painted Boolean pixel and exact calibrated cost.',
            'before_plane_retention':plane_retention(old_candidates,target,residual,model,comp),
            'after_plane_retention':plane_retention(new_candidates,target,residual,model,comp)}

        with closing(Image.new('RGB',(128,96),'white')) as source:
            ImageDraw.Draw(source).rectangle((8,8,118,86),fill=(0,80,205))
            options=multibrush_options()
            def regional_call(helper):
                with patch.object(regional,'_candidate_paths_for_brush',helper):
                    value=DrawBot.make_plan(source,source.size,options)
                try:
                    metadata=value['options']['adaptive_hybrid_meta']
                    comparison=core_plan(value)
                    comparison.update(path_stats=value['path_stats'],quality=metadata['quality'],
                        region_choices=metadata['region_choices'],candidate_diagnostics=metadata['candidate_diagnostics'],
                        schedule=metadata['schedule'],coverage=value['ui_previews'].get('coverage'))
                    return fingerprint(comparison)
                finally:close_plan(value,source)
            output['R1002_actual_verified_multibrush_make_plan']={
                **measured_pair(lambda:regional_call(old_candidates),lambda:regional_call(new_candidates),repeats),
                'parameters':{'size':[128,96],'region_bbox':[8,8,118,86],'options':options},
                'isolation':'Only _candidate_paths_for_brush is substituted. R1001 dispatch, R1003 candidate admission, every other helper and the full public planner are the same on both sides.',
                'comparison':'Complete source/main/Coverage preview pixels, colors, source/execution groups and sequence, counts/estimate/path statistics/operation timing, quality, region choices, every candidate diagnostic and full schedule. Volatile timing/profiling fields are excluded.',
                'timing_scope':'Whole public planning call plus identical result fingerprinting and owned-image cleanup.'}
    if hashes()!=sources:raise AssertionError('Measured source changed during paired benchmark.')
    result['source_unchanged_during_measurement']=True
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch10-rendering-benchmarks.json')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    result=measure(args.baseline,args.repeats)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name:{key:row[key] for key in ('before_median_ms','after_median_ms',
        'before_peak_python_bytes','after_peak_python_bytes','exact_output_parity')}
        for name,row in result['measurements'].items()},indent=2))
