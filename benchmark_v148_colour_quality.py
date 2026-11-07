"""Reproduce CPU color-quality measurements against the batch03 Git baseline.

Run with the repository's Python environment. This script generates inputs in
memory, never drives input devices and never imports a physical GPU backend.
Peak values are Python/NumPy allocations visible to tracemalloc, not process
RSS or GPU memory. Timing is diagnostic; no timing assertions run in CI.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import gc
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import types

import numpy as np
from PIL import Image
import PIL


BASELINE = '2fb7abf470a4ef498df9c53f42cddda62d8b652b'


def baseline_module(filename, revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:{filename}'], text=True)
    name = '_colour_benchmark_baseline_' + Path(filename).stem
    module = types.ModuleType(name)
    module.__file__ = f'{revision}:{filename}'
    sys.modules[name] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def measure(function, repeats):
    function()  # warm imports/conversion caches before measuring steady work
    samples = []
    for _ in range(repeats):
        gc.collect()
        started = time.perf_counter()
        function()
        samples.append((time.perf_counter()-started)*1000.0)
    gc.collect()
    tracemalloc.start()
    function()
    _retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {'samples_ms': samples, 'median_ms': statistics.median(samples),
            'tracemalloc_peak_bytes': peak}


def comparison(name, before, after, repeats, **details):
    first = measure(before, repeats)
    second = measure(after, repeats)
    return dict(name=name, before=first, after=second,
                time_ratio=second['median_ms']/first['median_ms'],
                traced_peak_ratio=second['tracemalloc_peak_bytes']/first['tracemalloc_peak_bytes'],
                **details)


def scalar_runs(labels, drawable, mapping, count):
    groups = [[] for _ in range(count)]
    height, width = labels.shape
    for y in range(height):
        last = start = None
        for x in range(width+1):
            index = mapping[int(labels[y, x])] if x < width and drawable[y, x] else None
            if index != last:
                if last is not None:
                    groups[last].append((start, y, x-1, y))
                last, start = index, x if index is not None else None
    return groups


def run(revision=BASELINE, repeats=5):
    import AdaptivePaletteFidelity as adaptive
    import DynamicColors as dynamic
    import ExactColorEngine as exact
    import NamedColorIntelligence as named
    import PictureCustomPaletteLegacy as picture
    import SmartColorEngine as smart
    import VisualImportanceMap as importance

    baseline_importance = baseline_module('VisualImportanceMap.py', revision)
    baseline_picture = baseline_module('PictureCustomPaletteLegacy.py', revision)
    baseline_adaptive = baseline_module('AdaptivePaletteFidelity.py', revision)
    baseline_smart = baseline_module('SmartColorEngine.py', revision)
    baseline_named = baseline_module('NamedColorIntelligence.py', revision)
    baseline_exact = baseline_module('ExactColorEngine.py', revision)
    rng = np.random.default_rng(14803)
    results = []

    # A repeated horizontal profile with flat outer neighbors isolates the
    # working-set optimization from the separately fixed gradient border rules.
    profile = rng.integers(0, 256, (768, 3), dtype=np.uint8)
    profile[:2] = profile[2]
    profile[-2:] = profile[-3]
    rgb = np.tile(profile[None], (512, 1, 1))
    old_map, old_metadata = baseline_importance._cpu_map(rgb)
    new_map, new_metadata = importance._cpu_map(rgb)
    np.testing.assert_array_equal(new_map, old_map)
    assert new_metadata == old_metadata
    results.append(comparison('importance_cpu_working_set',
        lambda: baseline_importance._cpu_map(rgb), lambda: importance._cpu_map(rgb), repeats,
        shape=list(rgb.shape), parity='bit-identical map and all metadata'))

    with closing(Image.fromarray(rng.integers(0, 256, (512, 640, 3), dtype=np.uint8))) as image:
        assert baseline_picture._edge_detail_colors(image, 6) == picture._edge_detail_colors(image, 6)
        results.append(comparison('edge_rgb_sampling',
            lambda: baseline_picture._edge_detail_colors(image, 6),
            lambda: picture._edge_detail_colors(image, 6), repeats,
            size=list(image.size), parity='identical ranked edge colors'))

    palette = [tuple(map(int, row)) for row in rng.integers(0, 256, (32, 3))]
    groups = [[tuple(map(int, row)) for row in rng.integers(0, 2048, (1024, 4))]
              for _ in palette]
    weights = adaptive.group_weights(groups)
    active = list(range(len(groups)))
    assert (baseline_adaptive._spatial_anchor_candidates(groups, active, weights) ==
            adaptive._spatial_anchor_candidates(groups, active, weights))
    results.append(comparison('spatial_palette_anchor_working_set',
        lambda: baseline_adaptive._spatial_anchor_candidates(groups, active, weights),
        lambda: adaptive._spatial_anchor_candidates(groups, active, weights), repeats,
        strokes=sum(map(len, groups)), parity='identical anchor indexes'))
    assert (baseline_smart.smart_color_weights(groups, palette, weights) ==
            smart.smart_color_weights(groups, palette, weights))
    results.append(comparison('smart_color_working_set',
        lambda: baseline_smart.smart_color_weights(groups, palette, weights),
        lambda: smart.smart_color_weights(groups, palette, weights), repeats,
        strokes=sum(map(len, groups)), parity='identical adjusted weights and all metadata'))

    samples = [tuple(map(int, row)) for row in rng.integers(0, 256, (256, 3))]
    def old_names():
        return [baseline_named._nearest_cached.__wrapped__(rgb, True) for rgb in samples]
    def new_names():
        return [named._nearest_cached.__wrapped__(rgb, True) for rgb in samples]
    old_results, new_results = old_names(), new_names()
    assert [(n, rgb) for n, rgb, _d in old_results] == [(n, rgb) for n, rgb, _d in new_results]
    np.testing.assert_allclose([r[2] for r in new_results], [r[2] for r in old_results], rtol=1e-14)
    results.append(comparison('uncached_named_color_queries', old_names, new_names, repeats,
        queries=len(samples), vocabulary='extended', parity='identical names/RGB; distances within 1e-14 relative'))

    pairs = [(source, candidate) for source in samples[:32] for candidate in palette[:16]]
    def old_costs():
        return [baseline_exact.score_candidate(a, b, fidelity='Faithful').total_cost for a, b in pairs]
    def new_costs():
        return [exact.candidate_cost(a, b, fidelity='Faithful') for a, b in pairs]
    assert old_costs() == new_costs()
    results.append(comparison('candidate_cost_without_unused_ciede2000', old_costs, new_costs, repeats,
        pairs=len(pairs), parity='identical candidate costs'))

    labels = np.repeat(np.repeat(rng.integers(0, 4, (96, 128), dtype=np.uint8), 4, axis=0), 4, axis=1)
    drawable = rng.random(labels.shape) >= .05
    mapping = {0: 0, 1: 1, 2: 2, 3: 1}
    before_runs = lambda: scalar_runs(labels, drawable, mapping, 3)
    after_runs = lambda: dynamic._groups_from_labels(labels, drawable, mapping, 3, True, lambda: False)
    assert before_runs() == after_runs()
    results.append(comparison('dynamic_horizontal_runs', before_runs, after_runs, repeats,
        shape=list(labels.shape), parity='identical complete stroke groups',
        baseline='independent scalar row walk with the previous per-pixel state machine'))

    with closing(Image.fromarray(np.asarray(palette[:8], dtype=np.uint8)[rng.integers(0, 8, (256, 384))])) as image:
        options = dict(max_colors=8, skip_white=False, exact_available=True, source_palette=True)
        full = lambda: dynamic.build_dynamic_color_strokes(image, palette, **options)
        palette_only = lambda: dynamic.build_dynamic_color_palette(image, palette, **options)
        assert full()[1:] == palette_only()
        results.append(comparison('picture_analysis_without_unused_strokes', full, palette_only, repeats,
            size=list(image.size), parity='identical colors, selectors and metadata',
            baseline='same current color analysis with full stroke construction enabled'))

    return {'baseline_commit': revision, 'python': platform.python_version(),
            'numpy': np.__version__, 'pillow': PIL.__version__, 'platform': platform.platform(),
            'repetitions': repeats, 'physical_gpu_used': False,
            'memory_metric': 'tracemalloc peak bytes; excludes untracked native/Pillow allocations and process RSS',
            'comparisons': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 25:
        parser.error('--repeats must be from 1 to 25')
    report = run(args.baseline, args.repeats)
    text = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)
