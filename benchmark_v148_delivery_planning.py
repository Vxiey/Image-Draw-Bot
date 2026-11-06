"""Reproduce paired batch02 delivery/planning CPU microbenchmarks.

Uses an existing local Git baseline and synthetic inputs only. Does not fetch
artifacts, capture the screen or exercise native input. All raw timing samples
are retained. Tracemalloc peaks do not include all native Pillow allocations.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tracemalloc
import types

import numpy as np
from PIL import Image, __version__ as pillow_version

import CanvasGuard
import PostDrawCorrectionPass
import PreviewDetailEngine
import SafetyDebugOverlay
import VisualVerification


ROOT = Path(__file__).resolve().parent
BASELINE = '1c09774ad22088c5c30a8f8220b6b451fdee9659'
MODULES = (CanvasGuard, PostDrawCorrectionPass, PreviewDetailEngine, SafetyDebugOverlay, VisualVerification)


def baseline_module(name, revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:{name}.py'], cwd=ROOT)
    module = types.ModuleType('_delivery_before_' + name)
    module.__file__ = str(ROOT / (name + '.py'))
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def _invoke(function):
    result = function()
    if isinstance(result, Image.Image):
        result.close()


def paired_measurement(before, after, repeats):
    _invoke(before); _invoke(after)
    samples = [[], []]
    for _ in range(repeats):
        for index, function in enumerate((before, after)):
            started = time.perf_counter()
            _invoke(function)
            samples[index].append((time.perf_counter() - started) * 1000)
    peaks = []
    for function in (before, after):
        gc.collect()
        tracemalloc.start()
        try:
            _invoke(function)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    return {
        'before_samples_ms': samples[0], 'after_samples_ms': samples[1],
        'before_median_ms': statistics.median(samples[0]),
        'after_median_ms': statistics.median(samples[1]),
        'before_peak_python_bytes': peaks[0], 'after_peak_python_bytes': peaks[1],
    }


def measure(revision=BASELINE, repeats=7, detail_repeats=3):
    if type(repeats) is not int or repeats <= 0 or type(detail_repeats) is not int or detail_repeats <= 0:
        raise ValueError('Repeat counts must be positive integers.')
    if tracemalloc.is_tracing():
        raise RuntimeError('Run in a fresh process so caller tracing is not disturbed.')
    old = {module.__name__: baseline_module(module.__name__, revision) for module in MODULES}
    result = {
        'baseline': revision, 'python': sys.version.split()[0], 'platform': sys.platform,
        'numpy': np.__version__, 'pillow': pillow_version,
        'repeats': repeats, 'detail_repeats': detail_repeats,
        'method': 'One warm call, alternating before/after timed calls, then separate traced-peak calls after gc.collect. Owned returned image disposal is included on both sides.',
        'scope': 'Changed modules with current shared dependencies; synthetic CPU fixtures, not Windows input time or physical GPU throughput. Tracemalloc does not include all native image memory.',
        'after_source_sha256': {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in MODULES},
        'measurements': {}, 'parity': {},
    }
    measurements = result['measurements']

    paths = [((i, 0), (i, 20)) for i in range(10_000)]
    probe_functions = [lambda m=m: m.planned_batch_points(paths, smart_group=True, transform=lambda x, y: (x, y))
                       for m in (old['VisualVerification'], VisualVerification)]
    samples = [function() for function in probe_functions]
    measurements['visual_samples_10000_paths_limit130'] = {
        **paired_measurement(*probe_functions, repeats),
        'parameters': {'paths': 10_000, 'path': '((i,0),(i,20))', 'sample_limit': 130},
        'before_sample_count': len(samples[0]), 'after_sample_count': len(samples[1]),
        'before_last_sample': samples[0][-1], 'after_last_sample': samples[1][-1],
        'output_contract': 'Bounded representative evidence; current sampling intentionally includes the batch tail.',
    }

    points = [(i, i % 61) for i in range(100_000)]
    functions = [lambda m=m: m._limit_path(points) for m in (old['SafetyDebugOverlay'], SafetyDebugOverlay)]
    if functions[0]() != functions[1]():raise AssertionError('Debug samples changed')
    measurements['debug_sample_100000_points_limit80'] = {
        **paired_measurement(*functions, repeats), 'parameters': {'points': 100_000, 'point': '(i,i%61)', 'limit': 80},
        'exact_sample_parity': True,
    }

    guards = [m.CanvasGuard.from_area((100, 200, 1000, 700)) for m in (old['CanvasGuard'], CanvasGuard)]
    probes = [(100 + i % 1000, 200 + i % 700) for i in range(20_000)]
    functions = [lambda guard=guard: [guard.safe.contains_safe(p) for p in probes] for guard in guards]
    if functions[0]() != functions[1]():raise AssertionError('Containment results changed')
    measurements['rectangle_contains_20000_probes'] = {
        **paired_measurement(*functions, repeats), 'parameters': {'area': [100, 200, 1000, 700], 'probes': 20_000,
                                                               'probe': '(100+i%1000,200+i%700)'},
        'exact_membership_parity': True,
    }

    source = Image.new('RGB', (64, 64), 'black'); actual = Image.new('RGB', source.size, 'white')
    args = dict(original_source=source, actual_canvas=actual,
                palette_rgb=[(0, 0, 0)] + [(255, 255, 255)]*255,
                post_draw_meta={'available': True, 'trusted': True, 'feedback_trust': 'high',
                                'visual_accuracy_percent': 60., 'actual_coverage_percent': 0.},
                options={'gpu_mode': 'CPU', 'brush_px': 1}, max_area_fraction=1, max_pixels=4096, max_paths=10000)
    functions = [lambda m=m: m.build_post_draw_correction_plan(**args)
                 for m in (old['PostDrawCorrectionPass'], PostDrawCorrectionPass)]
    try:
        a, b = (fn() for fn in functions)
        if a['execution_groups'] != b['execution_groups']:raise AssertionError('Correction geometry changed')
        measurements['correction64x64_palette256_one_active'] = {
            **paired_measurement(*functions, repeats),
            'parameters': {'source': '64x64 RGB black', 'actual': '64x64 RGB white',
                           'palette': 'black then 255 white entries', 'post_draw_meta': args['post_draw_meta'],
                           'options': args['options'], 'max_area_fraction': 1, 'max_pixels': 4096, 'max_paths': 10000},
            'exact_execution_group_parity': True,
            'selected_pixels_before': a['selected_correction_pixels'], 'selected_pixels_after': b['selected_correction_pixels'],
        }
    finally:
        source.close(); actual.close()

    rng = np.random.default_rng(14802)
    small = Image.fromarray(rng.integers(0, 256, (67, 91, 4), dtype=np.uint8))
    parity = []
    try:
        for source_mode in ('RGB', 'RGBA', 'L', 'LA', 'P'):
            image = small.convert(source_mode)
            try:
                for detail_mode in ('Fast', 'Balanced', 'Detailed', 'Micro detail'):
                    before = old['PreviewDetailEngine'].detail_aware_resize(image, (31, 23), detail_mode)
                    after = PreviewDetailEngine.detail_aware_resize(image, (31, 23), detail_mode)
                    try:
                        delta = np.abs(np.asarray(before, dtype=np.int16) - np.asarray(after, dtype=np.int16))
                        changed = int(np.count_nonzero(delta)); maximum = int(delta.max())
                        if changed:raise AssertionError(f'Preview raster changed: {source_mode}/{detail_mode}')
                        parity.append({'source_mode': source_mode, 'detail_mode': detail_mode,
                                       'changed_channels': changed, 'maximum_delta': maximum})
                    finally:
                        before.close(); after.close()
            finally:
                image.close()
    finally:
        small.close()
    result['parity']['preview_detail_seed14802_67x91_to31x23'] = parity

    large = Image.fromarray(np.random.default_rng(14802).integers(0, 256, (2000, 4000, 4), dtype=np.uint8))
    functions = [lambda m=m: m.detail_aware_resize(large, (240, 120), 'Detailed')
                 for m in (old['PreviewDetailEngine'], PreviewDetailEngine)]
    try:
        measurements['detail_rgba4000x2000_to240x120'] = {
            **paired_measurement(*functions, detail_repeats),
            'parameters': {'seed': 14802, 'source': 'uint8 random RGBA 4000x2000', 'output': [240, 120], 'mode': 'Detailed'},
        }
    finally:
        large.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--detail-repeats', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats, args.detail_repeats)
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
