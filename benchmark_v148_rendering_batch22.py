"""Measure detail-preserving corrections using an existing tracked image.

The quality correction intentionally changes harmed plans. Each variant must
repeat its own complete fingerprint; the one-pixel control must also retain
cross-version parity. CPU planning cost and allocations are reported as costs,
not as a claim that protecting detail makes planning or drawing faster.
"""
import argparse
from contextlib import closing
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import PixelAccuracyEngine as current
from DrawBot import make_plan
from benchmark_v148_image_workflow import old_module
from test_v148_accuracy_batch12_context import comparable_plan, public_options
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch22_detail_corrections import protected_losses


ROOT = Path(__file__).resolve().parent
BASELINE = 'be30fa54a0c58a8d2b6535d31cb6672727f4e6cc'
ASSET = ROOT / 'golden-regression/small-detail-preservation.png'
CROP = (155, 102, 174, 121)


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def public_result(module, source, brush):
    with patch.dict(sys.modules, {'PixelAccuracyEngine': module}):
        plan = make_plan(source, (100, 100), public_options(brush))
    try:
        return comparable_plan(plan)
    finally:
        close_plan(plan, source)


def quality_observation(module, source, brush):
    observations = []
    real = module.refine_with_corrections
    def observe(pixel_map, sequence, palette, **kwargs):
        initial = module.simulate_strokes(pixel_map, sequence, palette,
            brush_px=brush, gpu_mode='CPU')
        result = real(pixel_map, sequence, palette, **kwargs)
        observations.append({
            'initial_overall_accuracy': initial.metrics['pixel_accuracy_percent'],
            'initial_protected_accuracy': initial.metrics['protected_accuracy_percent'],
            'final_overall_accuracy': result['metadata']['final_accuracy_percent'],
            'final_protected_accuracy': result['metadata']['protected_accuracy_percent'],
            'previously_correct_protected_pixels_lost': protected_losses(pixel_map,
                initial.simulated_index, result['simulation'].simulated_index),
            'correction_paths_added': result['metadata']['correction_paths_added'],
            'passes': result['metadata']['passes'],
        })
        return result
    with patch.object(module, 'refine_with_corrections', new=observe):
        public_result(module, source, brush)
    if len(observations) != 1:
        raise AssertionError('Expected one actual public Pixel refinement operation')
    return observations[0]


def measure(*, repeats=6):
    if repeats < 2 or repeats % 2:
        raise ValueError('Use a positive even number of balanced timing pairs, at least two.')
    if tracemalloc.is_tracing():
        raise RuntimeError('This benchmark owns its separate allocation observations.')
    legacy = old_module('PixelAccuracyEngine', BASELINE)
    old_source = subprocess.check_output(['git', 'show', f'{BASELINE}:PixelAccuracyEngine.py'], cwd=ROOT)
    hashes = source_hashes()
    result = {
        'baseline': BASELINE,
        'baseline_accuracy_module_sha256': hashlib.sha256(old_source).hexdigest(),
        'python': sys.version, 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version,
        'asset': ASSET.relative_to(ROOT).as_posix(),
        'asset_sha256': hashlib.sha256(ASSET.read_bytes()).hexdigest(),
        'crop': CROP, 'canvas': (100, 100), 'repeats': repeats,
        'method': ('Complete historical PixelAccuracyEngine versus current in the same actual make_plan caller; '
                   'shared dependencies remain current. One warm call each, balanced AB/BA timing pairs and '
                   'separate tracemalloc observations after collection. Every call checks its variant fingerprint.'),
        'timing_scope': 'Complete public CPU plan, complete selected-output fingerprint and owned-image cleanup; no native drawing or GPU timing.',
        'allocation_scope': 'Traced Python/NumPy peak; excludes process RSS and most native Pillow pixel storage.',
        'parity_scope': ('Complete source/fitted geometry, source/execution groups, sequence, colors, previews, counts, '
                         'path statistics, estimate, Pixel Accuracy and operation-cost metadata. Volatile profiler '
                         'durations are excluded. Harmed cases intentionally differ; the one-pixel control must match.'),
        'source_sha256': hashes,
        'workloads': {},
    }
    with closing(Image.open(ASSET)) as asset, closing(asset.crop(CROP)) as source, \
            patch('DrawTimeCalibration.load_profile', return_value=None):
        for brush in (1, 3, 4):
            modules = (legacy, current)
            expected = [digest(public_result(module, source, brush)) for module in modules]
            if brush == 1 and expected[0] != expected[1]:
                raise AssertionError('The safe single-pixel control changed')
            observations = [quality_observation(module, source, brush) for module in modules]
            if observations[1]['previously_correct_protected_pixels_lost']:
                raise AssertionError('The corrected operation still loses protected pixels')
            if brush != 1 and not observations[0]['previously_correct_protected_pixels_lost']:
                raise AssertionError('The baseline quality counterexample no longer reproduces')
            def operation(index):
                actual = digest(public_result(modules[index], source, brush))
                if actual != expected[index]:
                    raise AssertionError('One benchmark variant changed its complete result')
            samples = [[], []]
            pair_orders = []
            for pair in range(repeats):
                order = (0, 1) if pair % 2 == 0 else (1, 0)
                pair_orders.append('AB' if pair % 2 == 0 else 'BA')
                for index in order:
                    started = time.perf_counter()
                    operation(index)
                    samples[index].append(1000 * (time.perf_counter() - started))
            row = {
                'brush_px': brush, 'pair_orders': pair_orders,
                'before_quality': observations[0], 'after_quality': observations[1],
                'before_result_sha256': expected[0], 'after_result_sha256': expected[1],
                'cross_variant_output_parity': expected[0] == expected[1],
                'before_samples_ms': samples[0], 'after_samples_ms': samples[1],
                'before_median_ms': statistics.median(samples[0]),
                'after_median_ms': statistics.median(samples[1]),
            }
            for index, label in enumerate(('before', 'after')):
                gc.collect()
                tracemalloc.start()
                try:
                    operation(index)
                    row[label + '_traced_peak_bytes'] = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
            result['workloads'][f'public_pixel_fixed_{brush}'] = row
    if hashes != source_hashes():
        raise AssertionError('Source changed during the benchmark; discard the measurements.')
    result['source_unchanged_during_measurement'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'docs/v148-batch22-rendering-quality.json')
    args = parser.parse_args()
    report = measure(repeats=args.repeats)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({name: {key: row[key] for key in ('before_median_ms', 'after_median_ms',
        'before_traced_peak_bytes', 'after_traced_peak_bytes', 'before_quality', 'after_quality')}
        for name, row in report['workloads'].items()}, indent=2))
