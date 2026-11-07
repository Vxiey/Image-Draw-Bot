"""Measure timed paint ordering and exact native Fill on existing shipped rasters.

The quality changes intentionally alter selected order or diagnostics. Each
variant must repeat its complete selected-output fingerprint. The no-Fill
control must match across versions, and Fill execution geometry must match.
No image assets are generated and no native input is sent.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, closing
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import AdaptiveRegionHybrid
import PixelAccuracyEngine
from AdaptiveBrushEngine import assign_adaptive_brushes
from DrawBot import make_plan
from PixelStrokeEngine import build_pixel_stroke_plan
from benchmark_v148_image_workflow import fingerprint, old_module
from test_v148_accuracy_batch12_context import public_options
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch08_fill import fill_options
from test_v148_rendering_batch25_progressive_order import detail_pairs, PALETTE


ROOT = Path(__file__).resolve().parent
BASELINE = '586e12db5ea5142951c844f60dc2364f07a01c37'
ORIGINAL_REPRODUCTION = 'bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c'
ASSETS = {'detail': ROOT/'golden-regression/small-detail-preservation.png',
          'fill': ROOT/'golden-regression/dominant-hue-four-color.png'}
CROP = (155,102,174,121)
MODULES = ('PixelAccuracyEngine', 'AdaptiveRegionHybrid')
CURRENT = dict(zip(MODULES, (PixelAccuracyEngine, AdaptiveRegionHybrid)))
PLAN_FIELDS = ('image','fitted','groups','execution_groups','execution_sequence',
    'preview','ui_previews','count','source_count','path_stats','estimate','colors',
    'color_selectors','draw_time_estimate')
OPTION_FIELDS = ('pixel_accuracy_meta','adaptive_hybrid_meta','region_fill_meta',
    'fill_regions','operation_timing_meta')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def public_result(modules, source, size, settings):
    with patch.dict(sys.modules, modules):
        plan = make_plan(source, size, settings)
    try:
        payload = {key: plan.get(key) for key in PLAN_FIELDS}
        payload['options'] = {key: plan['options'].get(key) for key in OPTION_FIELDS}
        regional = payload['options'].get('adaptive_hybrid_meta')
        if regional:
            payload['options']['adaptive_hybrid_meta'] = {
                key: value for key, value in regional.items() if key != 'timings'}
        geometry = {key: plan.get(key) for key in ('fitted','groups','execution_groups',
            'execution_sequence','colors','color_selectors','count','source_count')}
        geometry['fill_regions'] = plan['options'].get('fill_regions')
        quality = ((regional or {}).get('quality') or plan['options'].get('pixel_accuracy_meta') or {})
        return {'result_sha256': digest(fingerprint(payload)),
            'geometry_sha256': digest(fingerprint(geometry)),
            'quality': fingerprint(quality),
            'fills': len(plan['options'].get('fill_regions') or ()),
            'paths': plan['count'], 'estimated_seconds': plan['estimate']}
    finally:
        close_plan(plan, source)


def order_observation(module):
    pixel_map = detail_pairs()
    plan = build_pixel_stroke_plan(pixel_map, len(PALETTE))
    sequence = assign_adaptive_brushes(plan['execution_sequence'],
        default_brush_px=3)['execution_sequence']
    result = module.progressive_time_budget(sequence, active=True, seconds=10,
        correction_reserve_ratio=0)
    selected = result['execution_sequence']
    simulation = module.simulate_strokes(pixel_map, selected, PALETTE, brush_px=3, gpu_mode='CPU')
    return {'protected_accuracy_percent': simulation.metrics['protected_accuracy_percent'],
        'path_budget': result['path_budget'],
        'phase_counts': dict(Counter(row['phase'] for row in selected)),
        'selected_serials': sorted(row['serial'] for row in selected),
        'brush_sizes': sorted({row['brush_px'] for row in selected})}


def measure(*, repeats=6, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even number of balanced timing pairs, at least two.')
    if tracemalloc.is_tracing():
        raise RuntimeError('This benchmark owns its separate allocation observations.')
    previous = {name: old_module(name, BASELINE) for name in MODULES}
    hashes = source_hashes()
    report = {'baseline': BASELINE, 'original_reproduction': ORIGINAL_REPRODUCTION,
        'baseline_module_sha256': {name: hashlib.sha256(subprocess.check_output(
            ['git','show',f'{BASELINE}:{name}.py'], cwd=ROOT)).hexdigest() for name in MODULES},
        'source_sha256': hashes, 'python': sys.version, 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version,
        'assets': {key: {'path': path.relative_to(ROOT).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for key,path in ASSETS.items()},
        'detail_crop': CROP, 'verify_only': verify_only,
        'repeats': None if verify_only else repeats,
        'method': ('Complete historical PixelAccuracyEngine and AdaptiveRegionHybrid modules versus current '
            'inside the same public make_plan caller. All unrelated dependencies are current on both sides. '
            'One warm call per variant, balanced AB/BA pairs, separate traced peaks after garbage collection. '
            'Every call checks its complete selected-output fingerprint.'),
        'integration': ('The selected baseline module bodies are unchanged from the original reproduction. '
            'The integrated PixelStrokeEngine bounded queue is shared by both variants; the complete '
            'current root Python manifest binds this rerun rather than reusing pre-integration timings.'),
        'timing_scope': 'CPU public planning, selected-output fingerprinting and owned-image cleanup; no GUI, native drawing or GPU timing.',
        'allocation_scope': 'Traced Python/NumPy peak; not process RSS and not most native Pillow storage.',
        'compared_plan_fields': PLAN_FIELDS, 'compared_option_fields': OPTION_FIELDS,
        'excluded_fields': 'Volatile regional planning durations; no geometry, score or selected preview fields excluded.',
        'resource_probe_controls': {'available_ram_mb': 8192, 'logical_cpu_count': 8},
        'model_scope': 'Categorical palette-index canvas, initially blank=-1, physical square brush and four-neighbor bucket before CanvasGuard; no RGB alias, antialiasing or physical Windows equivalence claim.',
        'workloads': {}}
    with ExitStack() as stack:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch('ProfileStorage.data_dir', return_value=directory))
        stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        stack.enter_context(patch('RealSpeedBudget.load_profile', return_value=None))
        stack.enter_context(patch('ResourceAllocation.available_ram_mb', return_value=8192))
        stack.enter_context(patch('ResourceAllocation.logical_cpu_count', return_value=8))
        detail_asset = stack.enter_context(closing(Image.open(ASSETS['detail'])))
        detail = stack.enter_context(closing(detail_asset.crop(CROP)))
        fill = stack.enter_context(closing(Image.open(ASSETS['fill'])))
        inputs = [(source, source.tobytes()) for source in (detail_asset, detail, fill)]
        order = [order_observation(variant['PixelAccuracyEngine']) for variant in (previous, CURRENT)]
        if [row['protected_accuracy_percent'] for row in order] != [80., 100.]:
            raise AssertionError('Actual component-plan paint-order counterexample did not reproduce.')
        for key in ('selected_serials','path_budget','phase_counts','brush_sizes'):
            if order[0][key] != order[1][key]:
                raise AssertionError('The paint-order fix changed admitted work or physical brushes.')
        report['component_order_quality'] = {'before': order[0], 'after': order[1]}
        timed = dict(public_options(3), time_budget_mode='30 sec', unlimited_time=False)
        fill_settings = fill_options(skip_white=True, paint_profile=True,
            profile_name='Microsoft Paint', profile_key='microsoft-paint',
            corners=((100,100),(820,580)))
        control = dict(fill_settings, fill_tool_available=False, use_region_fill_engine=False,
            fill_tool_actions=[], fill_restore_actions=[])
        for name, source, size, settings in (
                ('timed_pixel_fixed_3', detail, (100,100), timed),
                ('accepted_native_fill', fill, (720,480), fill_settings),
                ('no_fill_control', fill, (720,480), control)):
            variants = previous, CURRENT
            warm = [public_result(module, source, size, settings) for module in variants]
            if name == 'accepted_native_fill':
                if [row['fills'] for row in warm] != [2,2]:
                    raise AssertionError('The measured public plan must keep its two accepted Fill regions.')
                if warm[0]['geometry_sha256'] != warm[1]['geometry_sha256']:
                    raise AssertionError('Physical Fill diagnostics must not change executable geometry.')
                if warm[1]['quality']['missing_pixels'] - warm[0]['quality']['missing_pixels'] != 666:
                    raise AssertionError('The public native Fill coverage counterexample did not reproduce.')
            if name == 'no_fill_control' and warm[0]['result_sha256'] != warm[1]['result_sha256']:
                raise AssertionError('The complete no-Fill control changed.')
            row = {'canvas': size, 'before': warm[0], 'after': warm[1],
                'cross_variant_output_parity': warm[0]['result_sha256'] == warm[1]['result_sha256'],
                'cross_variant_geometry_parity': warm[0]['geometry_sha256'] == warm[1]['geometry_sha256']}
            def operation(index):
                actual = public_result(variants[index], source, size, settings)
                if actual != warm[index]:
                    raise AssertionError(f'{name}: variant {index} changed its selected output.')
            if not verify_only:
                samples = [[], []]
                row['pair_orders'] = []
                for pair in range(repeats):
                    indices = (0,1) if pair % 2 == 0 else (1,0)
                    row['pair_orders'].append('AB' if pair % 2 == 0 else 'BA')
                    for index in indices:
                        started = time.perf_counter()
                        operation(index)
                        samples[index].append(1000*(time.perf_counter()-started))
                for index, label in enumerate(('before','after')):
                    row[label+'_samples_ms'] = samples[index]
                    row[label+'_median_ms'] = statistics.median(samples[index])
                    gc.collect()
                    tracemalloc.start()
                    try:
                        operation(index)
                        row[label+'_traced_peak_bytes'] = tracemalloc.get_traced_memory()[1]
                    finally:
                        tracemalloc.stop()
            report['workloads'][name] = row
        if any(source.tobytes() != before for source,before in inputs):
            raise AssertionError('A benchmark operation changed its borrowed raster.')
    if source_hashes() != hashes:
        raise AssertionError('Root Python source changed during measurement; discard the observations.')
    report['source_unchanged_during_measurement'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch25-rendering-quality.json')
    args = parser.parse_args()
    report = measure(repeats=args.repeats, verify_only=args.verify_only)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({name: {key: value for key,value in row.items()
        if key.endswith(('median_ms','peak_bytes','parity'))}
        for name,row in report['workloads'].items()}, indent=2))
