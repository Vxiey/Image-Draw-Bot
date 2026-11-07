"""Whole sequence execution: repeated legacy proof versus one per-run proof.

The recorded baseline execute_plan and RenderResume run with the same current
unchanged dependencies. A deterministic input boundary records every command;
checkpoint/event streams, runtime counts and final state must match exactly.
Timing uses balanced AB/BA pairs. Separate traced runs sample both peak Python
allocation and live retained allocation at the same checkpoint boundaries.
"""
from collections import Counter
from contextlib import ExitStack, closing
import argparse
import ast
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import threading
import time
import tracemalloc
import types
from unittest.mock import patch

from PIL import Image, __version__ as pillow_version

import DrawBot
import RenderResume as current


ROOT = Path(__file__).resolve().parent
BASELINE = '43a1c968eb56a63224827f1567e4ccc354acdadb'


class NoWait:
    def is_set(self):
        return False

    def wait(self, seconds):
        return False


class TraceMouse:
    """Hash every actual input call without retaining an expanding action log."""
    def __init__(self):
        self.position = (0, 0)
        self.held = False
        self.counts = Counter()
        self.trace = hashlib.sha256()

    def record(self, kind, *values):
        self.counts[kind] += 1
        self.trace.update((repr((kind, *values)) + '\n').encode('ascii'))

    def get_position(self):
        return self.position

    def move(self, x, y):
        self.position = (x, y)
        self.record('move', x, y)

    def click(self):
        self.record('click')

    def press(self):
        self.held = True
        self.record('press')

    def release(self):
        self.held = False
        self.record('release')


def recorded_sources(revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:RenderResume.py'], cwd=ROOT).decode('utf-8')
    module = types.ModuleType('_checkpoint_session_baseline')
    exec(compile(source, f'{revision}:RenderResume.py', 'exec'), vars(module))
    resume_hash = hashlib.sha256(source.encode()).hexdigest()
    source = subprocess.check_output(['git', 'show', f'{revision}:DrawBot.py'], cwd=ROOT).decode('utf-8')
    node = next(item for item in ast.parse(source).body
                if isinstance(item, ast.FunctionDef) and item.name == 'execute_plan')
    scope = dict(vars(DrawBot))
    exec(compile(ast.Module(body=[node], type_ignores=[]), f'{revision}:DrawBot.execute_plan', 'exec'), scope)
    return scope['execute_plan'], module, {
        'RenderResume.py': resume_hash,
        'DrawBot.execute_plan': hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest(),
    }


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))
            if not path.name.startswith(('test_', 'benchmark_')) or path.name == Path(__file__).name}


def make_fixture(source, operations):
    width, height = source.size
    columns = min(32, operations)
    rows = (operations + columns - 1) // columns
    cell_x = max(2, (width - 20) // columns)
    cell_y = max(1, (height - 20) // rows)
    sequence = []
    for number in range(operations):
        x, y = 10 + (number % columns) * cell_x, 10 + (number // columns) * cell_y
        sequence.append(dict(color_index=number % 2,
                             path=((x, y), (min(width - 10, x + cell_x // 2), y)),
                             phase='details', brush_px=1))
    paths = [[entry['path'] for entry in sequence if entry['color_index'] == color] for color in (0, 1)]
    return {
        'image': source, 'fitted': (600, 400), 'count': operations,
        'groups': [[(*path[0], *path[-1]) for path in group] for group in paths],
        'execution_groups': paths, 'execution_sequence': sequence,
        'colors': ((0, 0, 0), (0, 80, 205)),
        'color_selectors': ({'kind': 'palette', 'palette_index': 0}, {'kind': 'palette', 'palette_index': 1}),
        'path_stats': {'stroke_optimizer_effective': 'Nearest'},
        'options': dict(delay=0., speed='Fast', precision='Normal', human_mode='Off',
                        paint_current_color=False, strict_color_verification=False,
                        adaptive_color_verification=False, visual_verification_enabled=False,
                        visual_verification_resolved='Off', brush_px=1, color_order=[0, 1],
                        profile_key='generic', profile_name='Generic', unlimited_time=True,
                        time_budget_mode='Unlimited', test_run=True, _execution_cost_calibration_override={}),
    }


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')


def execute(function, module, operations, size, *, allocation_samples=None):
    checkpoints = hashlib.sha256()
    checkpoint_counts = []
    events = hashlib.sha256()
    last_checkpoint = None
    mouse = TraceMouse()
    with ExitStack() as stack:
        source = stack.enter_context(closing(Image.new('RGB', size, 'white')))
        plan = make_fixture(source, operations)
        stack.enter_context(patch.dict(sys.modules, {'RenderResume': module}))
        # Bindaries are shared on both sides; none sends real input, writes
        # learned data, captures the screen or includes disk latency.
        quiet = lambda *args, **kwargs: None
        ignored = lambda *args, **kwargs: {}
        safety = lambda session: {'counts': session.summary_counts()}
        stack.enter_context(patch.dict(function.__globals__, {'log_event': quiet, 'save_runtime_safety_report': safety}))
        for target in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                       'CorrectionHistory.record_correction_history'):
            stack.enter_context(patch(target, new=ignored))
        stack.enter_context(patch('DrawTimeCalibration.load_profile', new=lambda *args, **kwargs: None))
        allocation_base = tracemalloc.get_traced_memory()[0] if allocation_samples is not None else None
        def checkpoint(state):
            nonlocal last_checkpoint
            if allocation_samples is not None:
                current_bytes = tracemalloc.get_traced_memory()[0]
                allocation_samples.append({'completed': state['sequence_completed_count'],
                    'current_bytes': current_bytes, 'above_pre_execution_bytes': current_bytes - allocation_base})
            checkpoint_counts.append(state['sequence_completed_count'])
            checkpoints.update(_encoded(state) + b'\n')
            last_checkpoint = state
        def report(kind, value):
            events.update(_encoded((kind, value)) + b'\n')
        function(plan, (1000, 1000, 600, 400), [(10, 10), (20, 10)], mouse,
                 NoWait(), threading.Event(), report, clock=lambda: 0., checkpoint=checkpoint)
        if mouse.held:
            raise AssertionError('Execution left the native input boundary held.')
        return {'native_trace_sha256': mouse.trace.hexdigest(), 'native_calls': dict(mouse.counts),
                'checkpoint_stream_sha256': checkpoints.hexdigest(), 'checkpoint_completed_counts': checkpoint_counts,
                'final_checkpoint': last_checkpoint, 'event_stream_sha256': events.hexdigest(),
                'runtime_path_counts': plan['options']['runtime_path_counts'],
                'runtime_operation_timing': plan['options']['runtime_operation_timing'],
                'actual_draw_seconds': plan['options']['actual_draw_seconds']}


def operation_counts(function, module, operations, size):
    counts = Counter()
    key, fingerprint = module.sequence_entry_key, module.plan_fingerprint
    def count_key(*args, **kwargs):
        counts['sequence_entry_key_calls'] += 1
        return key(*args, **kwargs)
    def count_fingerprint(*args, **kwargs):
        counts['full_context_fingerprint_calls'] += 1
        return fingerprint(*args, **kwargs)
    with patch.object(module, 'sequence_entry_key', new=count_key), \
         patch.object(module, 'plan_fingerprint', new=count_fingerprint):
        output = execute(function, module, operations, size)
    return dict(counts), output


def measure(revision=BASELINE, repeats=6, operations=1001, size=(1500, 1000)):
    if repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two.')
    if operations < 26 or min(size) < 128:
        raise ValueError('Use at least 26 operations and source dimensions of at least 128.')
    before_function, before_module, baseline_hashes = recorded_sources(revision)
    sources = source_hashes()
    calls = {'before': (before_function, before_module), 'after': (DrawBot.execute_plan, current)}
    counts = {}
    expected = None
    for name, (function, module) in calls.items():
        counts[name], actual = operation_counts(function, module, operations, size)
        if expected is None:
            expected = actual
        elif actual != expected:
            raise AssertionError('Counted warm execution/checkpoint parity failed.')
    samples = {name: [] for name in calls}
    orders = []
    for number in range(repeats):
        order = ('before', 'after') if number % 2 == 0 else ('after', 'before')
        orders.append(list(order))
        for name in order:
            function, module = calls[name]
            started = time.perf_counter()
            actual = execute(function, module, operations, size)
            samples[name].append((time.perf_counter() - started) * 1000.)
            if actual != expected:
                raise AssertionError('Timed execution/checkpoint parity failed.')
            del actual
    result = {'baseline': revision, 'baseline_source_sha256': baseline_hashes,
        'python': sys.version.split()[0], 'platform': platform.platform(), 'pillow': pillow_version,
        'source_sha256': sources, 'parameters': {'operations': operations, 'source_size': list(size),
            'native_canvas_size': [600, 400], 'repeats': repeats, 'checkpoint_interval': 25},
        'orders': orders, 'operation_counts': counts, 'exact_output_parity': True,
        'output_sha256': hashlib.sha256(_encoded(expected)).hexdigest(),
        'checkpoint_completed_counts': expected['checkpoint_completed_counts'],
        'native_calls': expected['native_calls'], 'runtime_path_counts': expected['runtime_path_counts'],
        'timing_scope': 'Whole execute_plan with fixture construction, deterministic input/checkpoint/event hashing and cleanup. Logical clock and waits are fixed; no native device, disk, GUI or real-time throughput claim.',
        'isolation': 'Recorded baseline execute_plan plus its complete RenderResume; all other dependencies are identical current modules on both sides.',
        'memory_scope': 'Separate tracemalloc runs after garbage collection. Peak includes fixture, proof, runtime and comparison allocations. Live checkpoint samples are taken after checkpoint creation returns; deltas subtract the traced allocation immediately before execute_plan. This is Python allocation, not RSS or most native Pillow pixels.'}
    for name, (function, module) in calls.items():
        result[name + '_samples_ms'] = samples[name]
        result[name + '_median_ms'] = statistics.median(samples[name])
        gc.collect()
        retained = []
        tracemalloc.start()
        try:
            actual = execute(function, module, operations, size, allocation_samples=retained)
            current_bytes, peak = tracemalloc.get_traced_memory()
            if actual != expected:
                raise AssertionError('Traced execution/checkpoint parity failed.')
            result[name + '_peak_python_bytes'] = peak
            result[name + '_post_return_python_bytes'] = current_bytes
            result[name + '_checkpoint_retained_samples'] = retained
            result[name + '_max_checkpoint_retained_above_pre_execution_bytes'] = max(
                sample['above_pre_execution_bytes'] for sample in retained)
        finally:
            tracemalloc.stop()
        del actual
    if source_hashes() != sources:
        raise AssertionError('Root Python sources changed during measurement; coordinate and repeat.')
    result['source_unchanged_during_measurement'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--operations', type=int, default=1001)
    parser.add_argument('--width', type=int, default=1500)
    parser.add_argument('--height', type=int, default=1000)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch15-platform-benchmarks.json')
    arguments = parser.parse_args()
    result = measure(arguments.baseline, arguments.repeats, arguments.operations, (arguments.width, arguments.height))
    arguments.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('before_median_ms', 'after_median_ms',
        'before_peak_python_bytes', 'after_peak_python_bytes',
        'before_max_checkpoint_retained_above_pre_execution_bytes',
        'after_max_checkpoint_retained_above_pre_execution_bytes', 'exact_output_parity')}, indent=2))
