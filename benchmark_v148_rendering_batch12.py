"""Paired public Pixel Accurate planning with operation-local source-score reuse.

The before variant exposes the complete baseline accuracy module through the
current public caller's local import. Its adapter discards the newly added
context keyword and uses a no-op context factory, so no new source preparation
or context storage is charged to the historical flow. Every other dependency
and the caller remain current. No capture, network or native input is used.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from PIL import __version__ as pillow_version

import PixelAccuracyEngine as current
from DrawBot import make_plan
from benchmark_v148_image_workflow import old_module,measured_pair
from test_v148_accuracy_batch12_context import source_fixture,public_options,comparable_plan
from test_v148_rendering_batch06_canvas import close_plan


ROOT=Path(__file__).resolve().parent
BASELINE='b0eedca7d8d63fde5c9da6a1cffb394613ff95bf'


def baseline_module(revision):
    legacy=old_module('PixelAccuracyEngine',revision)
    old_refine=legacy.refine_with_corrections
    old_checkpoints=legacy.progressive_accuracy_checkpoints
    def refine(*args,score_context=None,**kwargs):return old_refine(*args,**kwargs)
    def checkpoints(*args,score_context=None,**kwargs):return old_checkpoints(*args,**kwargs)
    legacy.refine_with_corrections=refine
    legacy.progressive_accuracy_checkpoints=checkpoints
    # The new caller has an explicit operation-local handoff. Before uses no
    # context at all; every old helper and source preparation stays historical.
    legacy.PixelScoreContext=lambda pixel_map:None
    return legacy


def preparation_counts(module,operation):
    """Untimed instrumentation of source preparation in the real public call."""
    counts={'scores':0,'target_builds':0,'source_edge_percentiles':0}
    maps=set();score=module._score;target=module._desired_index;percentile=np.percentile
    def counted_target(pixel_map,*args):
        counts['target_builds']+=1;maps.add(id(pixel_map))
        return target(pixel_map,*args)
    def counted_percentile(*args,**kwargs):
        counts['source_edge_percentiles']+=1
        return percentile(*args,**kwargs)
    def counted_score(pixel_map,*args,**kwargs):
        counts['scores']+=1;maps.add(id(pixel_map))
        # Limit the percentile counter to scoring. Palette, shadow and final
        # preview analysis have their own unrelated percentile operations.
        with patch.object(np,'percentile',new=counted_percentile):
            return score(pixel_map,*args,**kwargs)
    with patch.object(module,'_desired_index',new=counted_target),patch.object(module,'_score',new=counted_score):
        operation()
    counts['distinct_pixel_maps']=len(maps)
    return counts


def measure(revision=BASELINE,repeats=5):
    if type(repeats) is not int or repeats<1:raise ValueError('repeats must be a positive integer')
    legacy=baseline_module(revision)
    baseline_source=subprocess.check_output(['git','show',f'{revision}:PixelAccuracyEngine.py'],cwd=ROOT)
    names=('DrawBot','PixelAccuracyEngine','PixelAccuracyGpu','PixelAccuratePlanner','PixelStrokeEngine',
        'PixelMapValidation','AdaptiveBrushEngine','SubjectFocus','AccuracyEvaluator','ShadowDetailEngine',
        'ColorMatchingEngine','UniversalGpuAcceleration','NativeBrushProjection','Precision',
        'AutoDrawing','EndToEndAutoTuner','ExecutionCostModel','DrawTimeEstimate','DrawTimeCalibration',
        'PreviewSafety','PreviewDiagnostics','ResourceAllocation',
        'benchmark_v148_image_workflow','benchmark_v148_rendering_batch12',
        'test_v148_accuracy_batch12_context','test_pixel_accuracy_engine_v1088','test_v148_rendering_batch06_canvas')
    def hashes():return {name:hashlib.sha256((ROOT/(name+'.py')).read_bytes()).hexdigest() for name in names}
    sources=hashes()
    result={'baseline':revision,'baseline_accuracy_module_sha256':hashlib.sha256(baseline_source).hexdigest(),
        'python':sys.version.split()[0],'platform':platform.platform(),'numpy':np.__version__,
        'pillow':pillow_version,'repeats':repeats,'source_sha256':sources,
        'method':'One warm/parity pair, five interleaved timing pairs in fixed before-then-after order by default, separate Python/NumPy traced peaks after garbage collection. Every timed/traced result is checked against the first reference.',
        'isolation':'Before loads the entire historical PixelAccuracyEngine module into the current caller local import. A no-op PixelScoreContext factory and adapters dropping only score_context bridge the new caller without preparing or retaining any new source context. After uses the current module. All other code is shared.',
        'timing_scope':'Whole public make_plan plus identical complete-result fingerprinting and owned-image cleanup; no native drawing or physical GPU timing.',
        'memory_scope':'Tracemalloc allocations, not process RSS or most Pillow native pixel storage. Source contexts are released before final floating-point preview analysis.',
        'parity_scope':'Complete source/fitted geometry, colors, source/execution groups, execution sequence, every UI preview, counts, path statistics, estimate, all Pixel Accuracy metadata including correction decisions/checkpoints, and operation timing metadata. Volatile profiler duration is excluded.',
        'measurements':{}}
    with patch('DrawTimeCalibration.load_profile',return_value=None):
        for size in ((160,112),(640,448)):
            with closing(source_fixture(size)) as source:
                settings=public_options(4);expected=None
                def plan_call(module):
                    nonlocal expected
                    with patch.dict(sys.modules,{'PixelAccuracyEngine':module}):
                        plan=make_plan(source,source.size,dict(settings))
                    try:
                        visible=comparable_plan(plan)
                        if expected is None:expected=visible
                        elif visible!=expected:raise AssertionError('Public Pixel Accurate result changed')
                        return visible
                    finally:close_plan(plan,source)
                before_counts=preparation_counts(legacy,lambda:plan_call(legacy))
                after_counts=preparation_counts(current,lambda:plan_call(current))
                measurements=measured_pair(lambda:plan_call(legacy),lambda:plan_call(current),repeats)
                metadata=expected['pixel_accuracy_meta']
                result['measurements'][f'public_pixel_accuracy_{size[0]}x{size[1]}_fixed4']={
                    **measurements,'parameters':{'size':size,'options':settings,
                        'source':'160x112 white, blue rectangle9,11..74,74; red rectangle86,19..149,92; black line7,102..152,102 and black dots13..148 step11 at y5; NEAREST enlargement'},
                    'before_preparations':before_counts,'after_preparations':after_counts,
                    'paths':expected['count'],'correction_passes':metadata['passes'],
                    'checkpoints':metadata['accuracy_checkpoints'],
                    'final_plan_execution_accuracy_percent':metadata['final_plan_execution_accuracy_percent']}
    if hashes()!=sources:raise AssertionError('Measured source changed during paired benchmark.')
    result['source_unchanged_during_measurement']=True
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch12-rendering-benchmarks.json')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    result=measure(args.baseline,args.repeats)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name:{key:row[key] for key in ('before_median_ms','after_median_ms',
        'before_peak_python_bytes','after_peak_python_bytes','exact_output_parity','before_preparations','after_preparations')}
        for name,row in result['measurements'].items()},indent=2))
