"""Complete historical layer-search parity and source-bound CPU measurements.

The whole old AdvancedColor module comes from the recorded Git revision. Both
sides use the current shared dependencies, source, calibrated palette and real
public DrawBot planner. No native input, screen capture or network is used.
"""
from contextlib import closing, contextmanager
from dataclasses import dataclass
import argparse
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

import AdvancedColor as current
import DrawBot
from benchmark_v148_image_workflow import old_module
from benchmark_v148_colour_batch20 import comparable
from test_v148_colour_batch23_mixed_costs import (
    PALETTE, NAMES, SOURCE_RGB, LAYER_MODES, block_source, clear_layer_caches, scoring_work,
    layer_plan_options)
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated, drawn_labels
from PreviewQuality import full_preview_options


ROOT = Path(__file__).resolve().parent
BASELINE = '5c32b6883c454268e06e199a8f15264ca9ec26e9'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sources():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def selected(module):
    with patch.dict(sys.modules, {'AdvancedColor': module}), \
            patch.object(DrawBot, 'build_color_strokes', module.build_color_strokes):
        yield


def rgba_source(size=(96, 64)):
    image = block_source(size)
    data = np.array(image)
    data[:size[1] // 4, :, 3] = 128
    data[-2:, :, 3] = 0
    image.close()
    return Image.fromarray(data)


@dataclass(frozen=True)
class Workload:
    name: str
    public: bool
    mode: str
    size: tuple[int, int] = (48, 32)
    alpha: bool = False
    warm: bool = False


def invoke(module, source, workload, *, lines=True, full_preview=False):
    if workload.public:
        settings = layer_plan_options(workload.mode)
        settings.update(color_layers=workload.mode, lines=lines,
                        color_rendering='Perceptual match' if workload.mode == 'Off' else 'Layered color mix')
        if full_preview:
            settings = full_preview_options(settings, source.size)
        return DrawBot.make_plan(source, source.size, settings)
    return module.build_color_strokes(source, lines=lines, skip_white=False,
        color_rendering='Perceptual match' if workload.mode == 'Off' else 'Layered color mix',
        color_layers=workload.mode, color_fidelity='Balanced', gpu_mode='CPU')


def dispose(value, source, public):
    if public:
        close_plan(value, source)


def checked_pair(before, source, workload, *, lines=True, full_preview=False):
    outputs = []
    for module in (before, current):
        clear_layer_caches(module)
        with selected(module):
            result = invoke(module, source, workload, lines=lines, full_preview=full_preview)
        try:
            if not workload.public:
                drawn_labels(source, result[0], skip_white=False)
            outputs.append(comparable(result))
        finally:
            dispose(result, source, workload.public)
    if outputs[0] != outputs[1]:
        raise AssertionError(f'Complete historical output differs: {workload.name}, lines={lines}, full_preview={full_preview}')
    return digest(outputs[0])


def historical_parity(before):
    records = []
    query_palettes = (
        (((0, 0, 0), (255, 255, 255)), ('Black', 'White')),
        (((0, 0, 0), (255, 255, 255), (0, 0, 0), (255, 255, 255)),
         ('Black', 'White', 'Custom black', 'Custom white')),
        (PALETTE, NAMES),
        (tuple((i * 47 % 256, i * 71 % 256, i * 113 % 256) for i in range(30)),
         tuple('Custom ' + str(i) for i in range(30))),
    )
    for palette, names in query_palettes:
        with calibrated(palette, names=names):
            clear_layer_caches(before); clear_layer_caches(current)
            for mode in LAYER_MODES:
                for fidelity in current.COLOR_FIDELITY_MODES:
                    for workflow in current.CUSTOM_COLOR_WORKFLOWS:
                        for rgb in ((128, 128, 128), SOURCE_RGB[0]):
                            kwargs = dict(color_layers=mode, color_fidelity=fidelity, custom_mode=workflow)
                            expected = before.best_layer_for_rgb(rgb, **kwargs)
                            actual = current.best_layer_for_rgb(rgb, **kwargs)
                            if actual != expected:
                                raise AssertionError(('query parity', len(palette), mode, fidelity, workflow, rgb, expected, actual))
                            records.append(('query', len(palette), mode, fidelity, workflow, rgb, actual))
    for palette, names in ((((128, 128, 128),), ('Exact gray',)), (PALETTE, NAMES)):
        with calibrated(palette, names=names):
            for rendering in current.COLOR_RENDERING_MODES:
                for mode in current.COLOR_LAYER_MODES:
                    for rgb in ((0, 0, 0), (128, 128, 128), (255, 255, 255)):
                        kwargs = dict(color_rendering=rendering, color_layers=mode)
                        expected = before.best_layer_for_rgb(rgb, **kwargs)
                        actual = current.best_layer_for_rgb(rgb, **kwargs)
                        if actual != expected:
                            raise AssertionError(('control parity', len(palette), rendering, mode, rgb))
                        records.append(('control', len(palette), rendering, mode, rgb, actual))
    with calibrated(PALETTE, names=NAMES):
        for alpha in (False, True):
            with closing(rgba_source((48, 32)) if alpha else block_source()) as source:
                source_bytes = source.tobytes()
                for public in (False, True):
                    for mode in LAYER_MODES:
                        for lines in (False, True):
                            workload = Workload('parity', public, mode, alpha=alpha)
                            outcome = checked_pair(before, source, workload, lines=lines)
                            records.append(('complete', alpha, public, mode, lines, outcome))
                for public in (False, True):
                    outcome = checked_pair(before, source, Workload('off control', public, 'Off'))
                    records.append(('complete-off', alpha, public, outcome))
                outcome = checked_pair(before, source, Workload('full preview', True, 'Full color mix'), full_preview=True)
                records.append(('complete-full-preview', alpha, outcome))
                if source.tobytes() != source_bytes:
                    raise AssertionError('Source mutated')
    return {'cases': len(records), 'single_color_queries': sum(row[0] in ('query', 'control') for row in records),
            'complete_builder_and_public_plan_pairs': sum(row[0].startswith('complete') for row in records),
            'all_exact': True, 'sha256': digest(records)}


def measure_workload(before, source, workload, pairs):
    modules = (before, current)
    expected = None
    work_counts = []
    for module in modules:
        clear_layer_caches(module)
        with selected(module), scoring_work(module) as (costs, mixes):
            result = invoke(module, source, workload)
        try:
            value = comparable(result)
            if expected is None:
                expected = value
            elif value != expected:
                raise AssertionError('Counted output differs: ' + workload.name)
            work_counts.append({'palette_match_cost_calls': sum(costs.values()),
                'unique_cost_keys': len(costs), 'mix_calls': sum(mixes.values()),
                'unique_mixture_RGBs_across_sources': len(mixes),
                'layer_cache': module._best_layer_cached.cache_info()._asdict()})
        finally:
            dispose(result, source, workload.public)
    samples = [[], []]
    order = []
    # Both modules have one complete warm call, warming shared color-space
    # caches before any sample. Cold layer/nearest LRUs alone are cleared below.
    for pair in range(pairs):
        indices = (0, 1) if pair % 2 == 0 else (1, 0)
        order.append(['before' if index == 0 else 'after' for index in indices])
        for index in indices:
            module = modules[index]
            if not workload.warm:
                clear_layer_caches(module)
            gc.collect()
            with selected(module):
                start = time.perf_counter_ns()
                result = invoke(module, source, workload)
                elapsed = (time.perf_counter_ns() - start) / 1_000_000
            try:
                if comparable(result) != expected:
                    raise AssertionError('Timed output differs: ' + workload.name)
                samples[index].append(elapsed)
            finally:
                dispose(result, source, workload.public)
    memory = {}
    if tracemalloc.is_tracing():
        raise RuntimeError('This benchmark must own its allocation tracer')
    for name, module in zip(('before', 'after'), modules):
        if not workload.warm:
            clear_layer_caches(module)
        gc.collect()
        with selected(module):
            tracemalloc.start()
            try:
                result = invoke(module, source, workload)
                retained, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
        try:
            if comparable(result) != expected:
                raise AssertionError('Traced output differs: ' + workload.name)
            memory[name] = {'retained_with_result_bytes': retained, 'peak_python_bytes': peak}
        finally:
            dispose(result, source, workload.public)
    medians = list(map(statistics.median, samples))
    return {'workload': workload.__dict__, 'output_sha256': digest(expected), 'all_outputs_exact': True,
            'cold_work_counts': dict(zip(('before', 'after'), work_counts)), 'pair_order': order,
            'before_samples_ms': samples[0], 'after_samples_ms': samples[1],
            'before_median_ms': medians[0], 'after_median_ms': medians[1],
            'median_change_percent': (medians[1] / medians[0] - 1) * 100,
            'faster_pairs': sum(a < b for b, a in zip(*samples)), 'traced_allocations': memory}


def run(baseline=BASELINE, pairs=6, *, parity_only=False):
    if type(pairs) is not int or pairs < 2 or pairs % 2:
        raise ValueError('Use an even number of at least two balanced pairs')
    snapshot = sources()
    before = old_module('AdvancedColor', baseline)
    report = {'schema': 1, 'baseline': baseline, 'python': sys.version.split()[0],
        'platform': platform.platform(), 'numpy': np.__version__, 'pillow': pillow_version,
        'historical_module_sha256': hashlib.sha256(subprocess.check_output(
            ['git', 'show', baseline + ':AdvancedColor.py'], cwd=ROOT)).hexdigest(),
        'source_hashes_before': snapshot,
        'pairs_per_workload': pairs,
        'method': f'One complete counted/warm call each, {pairs} balanced AB/BA pairs, then separate owned Python allocation tracing. Each full result is compared after the timer; aliases, cache preparation, GC, fingerprinting and cleanup are outside timing. Shared color-space LRUs are warmed on both sides. Cold layer and nearest LRUs are cleared before each sample; the explicitly warm control retains them.',
        'timing_scope': 'Actual CPU build_color_strokes or complete public make_plan only. Synthetic calibrated fixtures; no native drawing/input, GPU performance, GUI adoption, network or target-application throughput claim.',
        'memory_scope': 'One traced invocation per side, including retained result and existing scalar winner caches. Python tracing is not process RSS or most native Pillow/GPU memory.',
        'resolved_resource_input': {'cpu_workers': '1', 'cpu_workers_resolved': 1, 'cpu_engine': 'Threads',
            'ram_budget': '512 MB', 'ram_budget_mb': 512, 'logical_cpus': 4, 'available_ram_mb': 8192},
        'public_plan_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
        'historical_parity': historical_parity(before), 'measurements': {}}
    if not parity_only:
        workloads = [Workload('builder_' + mode.lower().replace(' ', '_'), False, mode) for mode in LAYER_MODES]
        workloads += [Workload('builder_rgba_full', False, 'Full color mix', (96, 64), True),
                      Workload('public_dual', True, 'Dual-color mix'),
                      Workload('public_full', True, 'Full color mix'),
                      Workload('public_light', True, 'Light shading'),
                      Workload('public_rgba_full', True, 'Full color mix', (96, 64), True),
                      Workload('public_full_warm_layer_cache', True, 'Full color mix', warm=True),
                      Workload('public_layers_off_control', True, 'Off')]
        with calibrated(PALETTE, names=NAMES):
            for workload in workloads:
                with closing(rgba_source(workload.size) if workload.alpha else block_source(workload.size)) as source:
                    pixels = source.tobytes()
                    report['measurements'][workload.name] = measure_workload(before, source, workload, pairs)
                    if source.tobytes() != pixels:
                        raise AssertionError('Measured source mutated')
                    print(workload.name, flush=True)
    report['source_hashes_after'] = sources()
    report['source_unchanged'] = report['source_hashes_after'] == snapshot
    if not report['source_unchanged']:
        raise RuntimeError('Source changed during the run')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--pairs', type=int, default=6)
    parser.add_argument('--parity-only', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    output = run(arguments.baseline, arguments.pairs, parity_only=arguments.parity_only)
    arguments.output.write_text(json.dumps(output, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'historical_parity': output['historical_parity'],
                      'source_files': len(output['source_hashes_before']),
                      'source_unchanged': output['source_unchanged']}, indent=2))
