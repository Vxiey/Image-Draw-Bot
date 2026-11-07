"""Replay the original operation-local source-score comparison.

The common DrawBot/SubjectFocus/PixelStrokeEngine/PixelAccuracyEngine graph is
pinned to the published batch12 after checkpoint. Only the originally compared
accuracy module changes between sides, so later topology reuse cannot enter
either measurement. The before adapter still discards score_context and uses
a no-op context factory. Shared dependencies are identical between sides.
An explicit unused output path is required; archived reports are never replaced.
No capture, network or native input is used.
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

from benchmark_v148_image_workflow import old_module,measured_pair
from benchmark_v148_rendering_batch26_topology import historical_graph,linked_graph,source_hashes
from test_v148_accuracy_batch12_context import source_fixture,public_options,comparable_plan
from test_v148_rendering_batch06_canvas import close_plan


ROOT=Path(__file__).resolve().parent
BASELINE='b0eedca7d8d63fde5c9da6a1cffb394613ff95bf'
AFTER='4704a94df364df9ceeefb113f5273f26ec4ee988'


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


def measure(revision=BASELINE,repeats=5,verify_only=False):
    if type(repeats) is not int or repeats<1:raise ValueError('repeats must be a positive integer')
    common,common_hashes=historical_graph(AFTER)
    current=common['PixelAccuracyEngine']
    make_plan=common['DrawBot'].make_plan
    legacy=baseline_module(revision)
    baseline_source=subprocess.check_output(['git','show',f'{revision}:PixelAccuracyEngine.py'],cwd=ROOT)
    hashes=source_hashes
    sources=hashes()
    result={'baseline':revision,'baseline_accuracy_module_sha256':hashlib.sha256(baseline_source).hexdigest(),
        'after_checkpoint':AFTER,'common_historical_module_sha256':common_hashes,
        'python':sys.version.split()[0],'platform':platform.platform(),'numpy':np.__version__,
        'pillow':pillow_version,'repeats':0 if verify_only else repeats,'verify_only':verify_only,'source_sha256':sources,
        'method':('Only untimed complete-result parity and preparation counters; no timing or allocation probes.' if verify_only else 'Original method retained: one warm/parity pair, five interleaved timing pairs in fixed before-then-after order by default, separate Python/NumPy traced peaks after garbage collection. Every timed/traced result is checked against the first reference.'),
        'isolation':'Both sides link the complete published batch12 after-checkpoint caller graph. Before substitutes only the complete baseline PixelAccuracyEngine, with the original no-op PixelScoreContext and adapters dropping only score_context. After uses its published batch12 accuracy module. Neither side creates the later region-topology owner. Other current dependencies are shared identically; this is an isolated historical comparison, not the entire historical application.',
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
                    with linked_graph(common,{'PixelAccuracyEngine':module}):
                        plan=make_plan(source,source.size,dict(settings))
                    try:
                        visible=comparable_plan(plan)
                        if expected is None:expected=visible
                        elif visible!=expected:raise AssertionError('Public Pixel Accurate result changed')
                        return visible
                    finally:close_plan(plan,source)
                before_counts=preparation_counts(legacy,lambda:plan_call(legacy))
                after_counts=preparation_counts(current,lambda:plan_call(current))
                measurements=({'exact_output_parity':True} if verify_only else
                    measured_pair(lambda:plan_call(legacy),lambda:plan_call(current),repeats))
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
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--output',type=Path,required=True,help='New report path; existing historical reports are never overwritten.')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    if args.output.exists():parser.error('--output must be a new path; existing reports are preserved.')
    result=measure(args.baseline,args.repeats,args.verify_only)
    with args.output.open('x',encoding='utf-8') as output:
        output.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({name:{key:row[key] for key in ('before_median_ms','after_median_ms',
        'before_peak_python_bytes','after_peak_python_bytes','exact_output_parity','before_preparations','after_preparations') if key in row}
        for name,row in result['measurements'].items()},indent=2))
