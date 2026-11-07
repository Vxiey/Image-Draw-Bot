"""Paired synthetic CPU benchmarks for the batch03 rendering/planning changes.

Reads the existing local Git baseline only. Does not download files, capture
screens or send input. Tracemalloc excludes some native Pillow allocations.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib
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
from PixelAccuratePlanner import PixelMap
from PixelAccuracyEngine import SimulationResult


ROOT = Path(__file__).resolve().parent
BASELINE = '2fb7abf470a4ef498df9c53f42cddda62d8b652b'
MODULES = ('AutoBrushWidth', 'PixelAccuracyEngine', 'AdaptiveRegionHybrid', 'HybridRenderer3',
           'AdaptiveDeadlineRenderer', 'RegionFillEngine', 'GarticEngineV2')


def baseline_module(name, revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:{name}.py'], cwd=ROOT)
    module = types.ModuleType('_rendering_before_' + name)
    module.__file__ = str(ROOT / (name + '.py'))
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def fingerprint(value):
    if isinstance(value, np.ndarray):
        return {'shape': value.shape, 'dtype': str(value.dtype),
                'sha256': hashlib.sha256(value.tobytes()).hexdigest()}
    if hasattr(value, 'as_dict'):
        return fingerprint(value.as_dict())
    if isinstance(value, dict):
        return {key: fingerprint(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [fingerprint(item) for item in value]
    return value


def measure_pair(before, after, repeats):
    expected, actual = fingerprint(before()), fingerprint(after())
    if expected != actual:
        raise AssertionError('Benchmark changes the compared raster/statistics')
    samples = [[], []]
    for _ in range(repeats):
        for index, function in enumerate((before, after)):
            started = time.perf_counter()
            function()
            samples[index].append((time.perf_counter() - started) * 1000)
    peaks = []
    for function in (before, after):
        gc.collect()
        tracemalloc.start()
        try:
            function()
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    return {'before_samples_ms': samples[0], 'after_samples_ms': samples[1],
            'before_median_ms': statistics.median(samples[0]), 'after_median_ms': statistics.median(samples[1]),
            'before_peak_python_bytes': peaks[0], 'after_peak_python_bytes': peaks[1],
            'exact_output_parity': True,
            'output_sha256': hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()}


def pixel_map(indices, *, feature_value=1):
    idx = np.asarray(indices, dtype=np.int16)
    h, w = idx.shape
    return PixelMap(w, h, np.zeros((h, w, 3), np.uint8), idx, np.ones((h, w), bool),
                    np.full((h, w), feature_value, np.float32), np.ones((h, w), np.float32),
                    np.full((h, w), bool(feature_value), bool), {})


def measure(revision=BASELINE, repeats=5):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('Repeats must be a positive integer')
    current = {name: importlib.import_module(name) for name in MODULES}
    old = {name: baseline_module(name, revision) for name in MODULES}
    result = {'baseline': revision, 'python': sys.version.split()[0], 'platform': sys.platform,
              'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
              'method': 'One parity/warm call, alternating before/after elapsed samples, separate traced peaks after garbage collection.',
              'scope': 'Synthetic CPU work only. Baseline changed modules import current shared dependencies. Python tracing does not capture all native Pillow memory.',
              'after_source_sha256': {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                      for name, module in current.items()}, 'measurements': {}}
    measurements = result['measurements']
    rng = np.random.default_rng(14803)
    tile = Image.fromarray(rng.integers(0, 256, (64, 64, 3), dtype=np.uint8))
    large = tile.resize((4096, 4096), Image.Resampling.NEAREST)
    tile.close()
    try:
        for key, name, function in (('auto_brush_4096_rgb', 'AutoBrushWidth', '_metrics'),
                                    ('hybrid_analysis_4096_rgb', 'HybridRenderer3', 'analyze_source')):
            calls = [lambda module=module, function=function: getattr(module, function)(large)
                     for module in (old[name], current[name])]
            measurements[key] = {**measure_pair(*calls, repeats),
                                 'parameters': {'source_size': [4096, 4096], 'seed': 14803,
                                                'source': '64x64 uniform random RGB tile enlarged with NEAREST'}}
        boxes=[(100+index*20,100,500+index*20,300) for index in range(20)]
        calls=[lambda module=module:[(module._frame_score(large,box),module._sample_white_fraction(large,box)) for box in boxes]
               for module in (old['GarticEngineV2'],current['GarticEngineV2'])]
        measurements['gartic_candidate_sampling_20_boxes_4096_rgb']={**measure_pair(*calls,repeats),
            'parameters':{'source_size':[4096,4096],'seed':14803,'boxes':boxes},
            'scope':'Frame/white evidence sampling after candidate discovery, not the full detector.'}
    finally:
        large.close()

    size = 128
    target = pixel_map(np.indices((size, size)).sum(axis=0) % 2)
    simulated = target.palette_index.copy()
    simulated[::3, ::3] ^= 1
    counts = np.ones((size, size), np.uint16)
    counts[::5, ::5] = 0
    simulation = SimulationResult(simulated, counts, counts > 0, np.zeros_like(counts, dtype=np.uint8), {})
    calls = [lambda module=module: module.region_accuracy_scores(target, simulation)
             for module in (old['PixelAccuracyEngine'], current['PixelAccuracyEngine'])]
    measurements['region_scores_128_checkerboard'] = {**measure_pair(*calls, repeats),
        'parameters': {'size': [128, 128], 'target': '(x+y)%2', 'wrong_color': 'x%3==y%3==0',
                       'uncovered': 'x%5==y%5==0', 'edge_and_protected': 'all pixels', 'max_regions': 64}}

    target = pixel_map(np.ones((512, 512), np.int16))
    sequence = [{'color_index': index % 2, 'brush_px': index % 3 + 1,
                 'path': ((index % 500, (index * 13) % 500),
                          (index % 500 + 8, (index * 13) % 500))} for index in range(1000)]
    calls = [lambda module=module: module.simulate_quantized_plan(target, sequence)
             for module in (old['AdaptiveRegionHybrid'], current['AdaptiveRegionHybrid'])]
    measurements['hybrid_simulation_1000_paths_512'] = {**measure_pair(*calls, repeats),
        'parameters': {'size': [512, 512], 'paths': 1000, 'path': '((i%500,(i*13)%500),(i%500+8,(i*13)%500))',
                       'brush': 'i%3+1', 'color': 'i%2', 'edge_and_protected': 'all pixels'}}

    from Precision import CanvasTransform
    transform=CanvasTransform(300,300,(600,600))
    options={'profile_key':'gartic-phone','speed':'Balanced','delay':.003,'precision':'High'}
    paths=[((i%299,(i*13)%300),(i%299+1,(i*13)%300)) for i in range(6000)]
    def old_path_costs():
        return [old['AdaptiveDeadlineRenderer']._path_cost(path,transform,options) for path in paths]
    def new_path_costs():
        module=current['AdaptiveDeadlineRenderer'];timing=module._path_timing(options)
        return [module._path_cost(path,transform,options,timing=timing) for path in paths]
    measurements['deadline_path_costs_6000_cached_context']={**measure_pair(old_path_costs,new_path_costs,repeats),
        'parameters':{'paths':6000,'path':'((i%299,(i*13)%300),(i%299+1,(i*13)%300))',
                      'source_size':[300,300],'fitted_size':[600,600],'options':options},
        'scope':'The candidate-cost loop used by adapt_execution_plan; one timing context per batch.'}

    candidate={'color_index':1,'row_spans':[(y,2,10) for y in range(6)],
               'contour':[(2,0),(10,0),(10,5),(2,5),(2,0)],'seed_pixel':(5,2),
               'area_pixels':54,'perimeter_pixels':28,'safety_score':.99,'bbox_density':1.0}
    candidates=[dict(candidate) for _ in range(100)]
    options={'brush_px':1,'_execution_cost_calibration_override':{}}
    calls=[lambda module=module:module.evaluate_region_candidates(candidates,(20,20),(200,200),options)
           for module in (old['RegionFillEngine'],current['RegionFillEngine'])]
    measurements['fill_candidate_costs_100_model_snapshot']={**measure_pair(*calls,repeats),
        'parameters':{'regions':100,'region':candidate,'image_size':[20,20],
                      'fitted_size':[200,200],'options':options},
        'scope':'Includes real cost-model construction with a deterministic empty calibration override; excludes disk latency.'}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    data = measure(args.baseline, args.repeats)
    text = json.dumps(data, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text, end='')
