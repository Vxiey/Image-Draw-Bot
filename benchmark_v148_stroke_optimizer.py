"""Paired legacy route optimization and public planning from identical inputs.

Only StrokeOptimizer is substituted with its complete recorded Git baseline.
All other dependencies are shared. Samples alternate AB/BA order; complete
outputs are checked on every invocation, including separate allocation probes.
No network, screenshots, native drawing or physical GPU work is performed.
"""
from collections import Counter
from contextlib import closing
import argparse
import copy
import gc
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

import DrawBot
import StrokeOptimizer as current
from benchmark_v148_image_workflow import fingerprint, old_module
from test_pixel_accuracy_engine_v1088 import options
from test_v148_rendering_batch06_canvas import close_plan


ROOT = Path(__file__).resolve().parent
BASELINE = '4704a94df364df9ceeefb113f5273f26ec4ee988'


def path_fixture(seed, count):
    rng = random.Random(seed)
    return [((x, y), (x + rng.randrange(1, 20), y + rng.randrange(-12, 13)))
            for x, y in ((rng.randrange(-2000, 2001), rng.randrange(-2000, 2001))
                         for _ in range(count))]


def ink_signature(paths):
    segments = Counter((a, b) if a <= b else (b, a)
                       for path in paths for a, b in zip(path, path[1:]) if a != b)
    return segments, {point for path in paths for point in path}


def verify_parity(legacy):
    """Full returned objects, independent ink geometry and unchanged inputs."""
    checked = 0
    for seed in (13, 148, 1301):
        for count in (0, 1, 2, 3, 4, 9, 25):
            paths = path_fixture(seed, count)
            original = copy.deepcopy(paths)
            for speed in ('Safe', 'Balanced', 'Fast', 'Snabb'):
                for reversible in (False, True):
                    kwargs = dict(speed=speed, allow_reverse=reversible)
                    expected = legacy._bounded_two_opt(paths, **kwargs)
                    actual = current._bounded_two_opt(paths, **kwargs)
                    if actual != expected:
                        raise AssertionError('Complete two-opt route/metadata parity failed.')
                    if ink_signature(actual[0]) != ink_signature(paths) or paths != original:
                        raise AssertionError('Two-opt changed drawn geometry or caller input.')
                    checked += 1
        groups = [[], path_fixture(seed, 18), path_fixture(seed + 1, 31)]
        # Include exact endpoints, isolated dots, ties, duplicate points and an
        # empty input path alongside the disjoint random components.
        groups[1] += [(), ((0, 0),), ((0, 0), (3, 0)),
                      ((6, 0), (3, 0)), ((0, 0), (0, 0), (-3, 0))]
        original = copy.deepcopy(groups)
        hints = [[('foundation', 'details', 'cleanup')[(i // 7) % 3]
                  for i in range(len(group))] for group in groups]
        for mode in current.STROKE_OPTIMIZER_MODES:
            for speed in ('Safe', 'Balanced', 'Fast'):
                for phases in (None, hints):
                    kwargs = dict(mode=mode, speed=speed, drawing_mode='Shape paths', phase_hints=phases)
                    expected = legacy.optimize_execution_groups(groups, **kwargs)
                    actual = current.optimize_execution_groups(groups, **kwargs)
                    if actual != expected:
                        raise AssertionError('Complete public group/phase/metadata parity failed.')
                    if groups != original:
                        raise AssertionError('Public optimization changed caller-owned paths.')
                    for before, after in zip(groups, actual[0]):
                        if ink_signature(before) != ink_signature(after):
                            raise AssertionError('Public optimization changed drawn geometry.')
                    checked += 1
    return checked


def paired(before, after, repeats):
    expected = before()
    if after() != expected:
        raise AssertionError('Warm result parity failed.')
    calls = {'before': before, 'after': after}
    samples = {name: [] for name in calls}
    orders = []
    for index in range(repeats):
        order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
        orders.append(list(order))
        for name in order:
            started = time.perf_counter()
            actual = calls[name]()
            samples[name].append((time.perf_counter() - started) * 1000)
            if actual != expected:
                raise AssertionError('Timed result parity failed.')
            del actual
    result = {
        'orders': orders, 'exact_output_parity': True,
        'output_sha256': hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(),
    }
    for name, operation in calls.items():
        result[name + '_samples_ms'] = samples[name]
        result[name + '_median_ms'] = statistics.median(samples[name])
        gc.collect()
        tracemalloc.start()
        try:
            actual = operation()
            result[name + '_peak_python_bytes'] = tracemalloc.get_traced_memory()[1]
            if actual != expected:
                raise AssertionError('Traced result parity failed.')
        finally:
            tracemalloc.stop()
        del actual
    return result


def distance_calls(module, operation):
    calls = 0
    distance = module._distance
    def counted(*args):
        nonlocal calls
        calls += 1
        return distance(*args)
    with patch.object(module, '_distance', new=counted):
        operation()
    return calls


def source_fixture(size):
    source = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(source)
    colors = ((0, 0, 0), (0, 80, 205), (239, 19, 11))
    for y in range(4, size[1] - 5, 9):
        for x in range(4, size[0] - 7, 11):
            draw.line((x, y, x + 4, y + (x // 11) % 3),
                      fill=colors[(x // 11 + y // 9) % 3], width=1)
    return source


def public_options():
    return options(draw_quality='High likeness', render_preset='Manual', drawing_style='Auto',
        auto_engine_resolved=True, time_budget_mode='Unlimited', unlimited_time=True,
        stroke_optimizer='Smart merge + 2-opt', adaptive_deadline_renderer=False,
        detail_zoom='Off', color_workflow='Finish color first', progressive_rendering='Off',
        _execution_cost_calibration_override={}, cpu_workers_resolved=1, ram_budget_mb=2048,
        available_ram_mb=8192, logical_cpus=4)


def comparable_plan(value, path=()):
    """Keep every returned field except explicitly identified elapsed timers."""
    if isinstance(value, dict):
        return {key: comparable_plan(item, (*path, key)) for key, item in value.items()
                if key not in ('performance_profile', '_performance_profile')
                and not (key == 'planning_seconds' and path in (
                    ('preview_diagnostics', 'performance'),
                    ('options', 'preview_diagnostics_meta', 'performance')))}
    if isinstance(value, (tuple, list)):
        return [comparable_plan(item, path) for item in value]
    return fingerprint(value)


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))
            if not path.name.startswith(('test_', 'benchmark_')) or path.name in (
                Path(__file__).name, 'benchmark_v148_image_workflow.py',
                'test_pixel_accuracy_engine_v1088.py', 'test_v148_rendering_batch06_canvas.py')}


def measure(revision=BASELINE, repeats=6):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use a positive even number of repeats, at least two, for balanced AB/BA samples.')
    legacy = old_module('StrokeOptimizer', revision)
    baseline_source = subprocess.check_output(['git', 'show', f'{revision}:StrokeOptimizer.py'], cwd=ROOT)
    sources = source_hashes()
    result = {
        'baseline': revision, 'baseline_optimizer_sha256': hashlib.sha256(baseline_source).hexdigest(),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
        'source_sha256': sources, 'full_result_parity_cases': verify_parity(legacy),
        'method': 'One warm pair, balanced interleaved AB/BA timing, separate traced peaks after garbage collection; every warm, counted, timed and traced call requires complete result parity.',
        'scope': 'Whole public optimize_execution_groups and whole public make_plan plus identical output fingerprinting and owned-image cleanup. Only the complete historical StrokeOptimizer module is substituted; all other dependencies are shared.',
        'memory_scope': 'Tracemalloc allocation peaks, not RSS, most Pillow native memory, GPU memory or native drawing.',
        'public_plan_exclusions': ['performance_profile', 'options._performance_profile',
            'preview_diagnostics.performance.planning_seconds',
            'options.preview_diagnostics_meta.performance.planning_seconds'],
        'measurements': {},
    }
    for per_color, phases in ((250, False), (750, True)):
        groups = [path_fixture(1481301 + index, per_color) for index in range(3)]
        hints = [[('foundation', 'details', 'cleanup')[(i // 125) % 3]
                  for i in range(per_color)] for _ in groups] if phases else None
        kwargs = dict(mode='Smart merge + 2-opt', speed='Balanced', drawing_mode='Shape paths', phase_hints=hints)
        expected = legacy.optimize_execution_groups(groups, **kwargs)
        def group_call(module):
            actual = module.optimize_execution_groups(groups, **kwargs)
            if actual != expected:
                raise AssertionError('Complete large public optimizer result changed.')
            return fingerprint(actual)
        before = lambda: group_call(legacy)
        after = lambda: group_call(current)
        result['measurements'][f'public_optimizer_{3 * per_color}_paths'] = {
            **paired(before, after, repeats), 'input_paths': 3 * per_color,
            'phase_blocks': phases, 'seed': 1481301, 'options': kwargs,
            'before_distance_calls': distance_calls(legacy, before),
            'after_distance_calls': distance_calls(current, after),
            'optimizer_metadata': expected[2],
        }
    with patch('DrawTimeCalibration.load_profile', return_value=None):
        for size in ((128, 96), (192, 144)):
            with closing(source_fixture(size)) as source:
                settings = public_options()
                expected = None
                def plan_call(module):
                    nonlocal expected
                    with patch.object(DrawBot, 'optimize_execution_groups', module.optimize_execution_groups):
                        plan = DrawBot.make_plan(source, size, dict(settings))
                    try:
                        actual = comparable_plan(plan)
                        if expected is None:
                            expected = actual
                        elif actual != expected:
                            raise AssertionError('Complete public planner result changed.')
                        if actual['path_stats']['optimizer_two_opt_evaluations'] <= 0:
                            raise AssertionError('Public fixture did not reach two-opt.')
                        return actual
                    finally:
                        close_plan(plan, source)
                before = lambda: plan_call(legacy)
                after = lambda: plan_call(current)
                row = paired(before, after, repeats)
                result['measurements'][f'public_make_plan_{size[0]}x{size[1]}'] = {
                    **row, 'size': size, 'options': settings,
                    'source': 'Deterministic isolated colored linelets from source_fixture; fixture construction is outside timing.',
                    'before_distance_calls': distance_calls(legacy, before),
                    'after_distance_calls': distance_calls(current, after),
                    'paths': expected['count'], 'path_stats': expected['path_stats'],
                }
    if source_hashes() != sources:
        raise AssertionError('Source changed during benchmark; rerun on a stable checkpoint.')
    result['source_unchanged_during_measurement'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = measure(args.baseline, args.repeats)
    serialized = json.dumps(report, indent=2) + '\n'
    if args.output is not None:
        args.output.write_text(serialized, encoding='utf-8')
        print(json.dumps({key: {field: row[field] for field in (
            'before_median_ms', 'after_median_ms', 'before_peak_python_bytes',
            'after_peak_python_bytes', 'before_distance_calls', 'after_distance_calls')}
            for key, row in report['measurements'].items()}, indent=2))
    else:
        print(serialized)
