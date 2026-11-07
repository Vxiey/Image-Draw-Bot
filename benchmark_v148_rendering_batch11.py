"""Measure complete-pack policy tradeoffs with the same native pixels on both sides.

Only the historical _brush_pack_candidate function is substituted. Its calls
still use the current default gain-per-cost layout helper, current coordinate
transform and native footprint proof. The current side additionally evaluates
maximum-gain packs and retains the cheapest complete exact result.

No captures, downloads, real native input or flagged executables are used.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw,__version__ as pillow_version

import AdaptiveRegionHybrid as regional
from DrawBot import make_plan
from benchmark_v148_image_workflow import fingerprint,measured_pair
from benchmark_v148_rendering_batch10 import previous_function
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_physical import physical_options,replay_executor
from test_v148_rendering_batch11_pack_choice import BLUE,FIXTURES,packing_metadata


ROOT=Path(__file__).resolve().parent
BASELINE='a8fabbc811029a8bfcbe8a5af2a848b034e5cd89'


def visible_output(plan):
    """Changed paths, cost, counts and decision diagnostics are not parity fields."""
    return fingerprint({'source':plan['image'],'colors':plan['colors'],'fitted':plan['fitted'],
        'preview':plan['preview'],'coverage':plan['ui_previews']['coverage']})


def execution_evidence(plan,origin,area):
    """Untimed native-action replay, separate from the planning measurements."""
    pixels,selected=replay_executor(plan,origin,area)
    metadata=plan['options']['adaptive_hybrid_meta']
    packing=packing_metadata(plan)
    return {'paths':len(plan['execution_sequence']),
        'used_brush_sizes':sorted({entry['brush_px'] for entry in plan['execution_sequence']}),
        'executed_brush_selections':selected,
        'component_estimated_seconds':metadata['region_choices'][0]['estimated_seconds'],
        'policy':packing.get('packing_policy') or 'gain-per-cost (historical)',
        'policy_candidates':packing.get('policy_candidates') or {},
        'coverage_percent':metadata['quality']['coverage_percent'],
        'missing_pixels':metadata['quality']['missing_pixels'],
        'spill_pixels':metadata['quality']['spill_pixels'],
        'native_raster':fingerprint(pixels),'native_painted_pixels':int(np.count_nonzero(pixels>=0)),
        'runtime_path_counts':plan['options']['runtime_path_counts']}


def measure(revision=BASELINE,repeats=5):
    if type(repeats) is not int or repeats<1:raise ValueError('repeats must be a positive integer')
    old_pack,old_hash=previous_function(regional,'_brush_pack_candidate',revision)
    new_pack=regional._brush_pack_candidate
    names=('DrawBot','AdaptiveRegionHybrid','NativeBrushProjection','Precision','AutoDrawing',
        'EndToEndAutoTuner','ExtraFastProfilePolicy','AdaptiveBrushEngine','ExecutionCostModel',
        'StrokeDelivery','PreviewSafety','PixelAccuracyEngine','PixelStrokeEngine','ColorFidelity',
        'ColorMatchingEngine','ResourceAllocation','DrawTimeEstimate','DrawTimeCalibration',
        'benchmark_v148_image_workflow','benchmark_v148_rendering_batch10','benchmark_v148_rendering_batch11',
        'test_v148_rendering_batch06_canvas','test_v148_rendering_batch07_transparency',
        'test_v148_rendering_batch09_subject','test_v148_rendering_batch10_candidates',
        'test_v148_rendering_batch10_single_brush','test_v148_rendering_batch10_physical',
        'test_v148_rendering_batch11_pack_choice','test_rc6_region_brush_packing','test_drawbot')
    def hashes():return {name:hashlib.sha256((ROOT/(name+'.py')).read_bytes()).hexdigest() for name in names}
    sources=hashes()
    result={'baseline':revision,'python':sys.version.split()[0],'platform':platform.platform(),
        'numpy':np.__version__,'pillow':pillow_version,'repeats':repeats,
        'method':'One warm/parity pair, interleaved timing pairs in fixed before-then-after order, and separate traced peaks after garbage collection. Every timed/traced result is compared to the first warm result. Native-action replay is checked separately and is not timed.',
        'timing_scope':'Whole public make_plan, visual-result fingerprinting and owned-image cleanup. This measures planning overhead, not physical drawing speed.',
        'memory_scope':'Python/NumPy traced allocations, not process RSS or most native Pillow pixel-core storage.',
        'isolation':'Only _brush_pack_candidate is loaded from the baseline into a copy of current module globals. Both variants use the same current layout helper, cost model, native coordinate transform, projection and public caller. The old function always uses the unchanged default 90%-gain local policy.',
        'parity_scope':'Identical source/main/Coverage pixels, palette and fitted geometry on every measured call. Separately recorded native-action rasters are also identical. Complete paths, decision diagnostics and component costs intentionally differ where the new pack wins.',
        'baseline_function_sha256':old_hash,'source_sha256':sources,'measurements':{}}
    with patch('DrawTimeCalibration.load_profile',return_value=None):
        for name,(size,area,box) in FIXTURES.items():
            origin=(100,100)
            with closing(Image.new('RGB',size,'white')) as source:
                ImageDraw.Draw(source).rectangle(box,fill=BLUE)
                settings=physical_options(origin,area)
                expected_visible=None
                def plan_call(packer,*,replay=False):
                    nonlocal expected_visible
                    with patch.object(regional,'_brush_pack_candidate',packer):
                        plan=make_plan(source,area,dict(settings))
                    try:
                        if replay:return execution_evidence(plan,origin,area)
                        visible=visible_output(plan)
                        if expected_visible is None:expected_visible=visible
                        elif visible!=expected_visible:
                            raise AssertionError('Measured planning call changed its visible output')
                        return visible
                    finally:close_plan(plan,source)
                before=plan_call(old_pack,replay=True);after=plan_call(new_pack,replay=True)
                if before['native_raster']!=after['native_raster']:
                    raise AssertionError('Recorded native-action raster changed')
                for evidence in (before,after):
                    if (evidence['coverage_percent'],evidence['missing_pixels'],evidence['spill_pixels'])!=(100.,0,0):
                        raise AssertionError('Exact fixture lost native coverage or introduced spill')
                    if evidence['runtime_path_counts']['guard_skipped']:
                        raise AssertionError('Fixture was altered by CanvasGuard clipping')
                result['measurements'][name]={
                    **measured_pair(lambda:plan_call(old_pack),lambda:plan_call(new_pack),repeats),
                    'parameters':{'source_size':size,'canvas_size':area,'source_rectangle':box,
                                  'origin':origin,'options':settings},
                    'before_execution':before,'after_execution':after,'exact_native_raster_parity':True}
    if hashes()!=sources:raise AssertionError('Measured source changed during paired benchmark.')
    result['source_unchanged_during_measurement']=True
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/v148-batch11-rendering-benchmarks.json')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    result=measure(args.baseline,args.repeats)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name:{key:row[key] for key in ('before_median_ms','after_median_ms',
        'before_peak_python_bytes','after_peak_python_bytes','exact_output_parity','exact_native_raster_parity')}
        for name,row in result['measurements'].items()},indent=2))
