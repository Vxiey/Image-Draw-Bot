"""Compare complete scoring operations with fresh, validated profile files.

Run --verify-only during correctness work. Coordinate an idle CPU/source window
for the six balanced AB/BA pairs and separate peak/retained allocation probes.
All three complete historical modules are installed together during each old
operation; a historical evaluator never receives a new private keyword.
"""
import argparse
from contextlib import contextmanager
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
import types
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import AccuracyEvaluator
import SafeCanvasSnapshotScoring
import UniversalGpuAcceleration
import UniversalHardwareBenchmark as hardware


ROOT = Path(__file__).resolve().parent
BASELINE = '7f41c7ee8c4b69f750008bd2d83349d186396fd1'
MODULE_NAMES = ('UniversalGpuAcceleration', 'AccuracyEvaluator', 'SafeCanvasSnapshotScoring')
CURRENT = {name: globals()[name] for name in MODULE_NAMES}


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def historical_modules(revision):
    modules, hashes = {}, {}
    for name in MODULE_NAMES:
        source = subprocess.check_output(['git', 'show', f'{revision}:{name}.py'], cwd=ROOT)
        module = types.ModuleType('_profile_before_' + name)
        module.__file__ = str(ROOT / (name + '.py'))
        sys.modules[module.__name__] = module
        # In particular, the old final scorer binds the old public evaluator.
        with patch.dict(sys.modules, modules):
            exec(compile(source, module.__file__, 'exec'), module.__dict__)
        modules[name] = module
        hashes[name] = hashlib.sha256(source).hexdigest()
    return modules, hashes


def comparable(value):
    if isinstance(value, Image.Image):
        return {'mode': value.mode, 'size': list(value.size),
                'pixels_sha256': hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [comparable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def profile(snapshot, *, backend='cpu:numpy', minimum=0):
    preferences = {name: {
        'backend_id': backend, 'backend': backend, 'vendor': 'Controlled',
        'device': 'Controlled benchmark preference', 'min_pixels': minimum,
        'reason': 'controlled current-machine scoring preference'}
        for name in hardware.WORKLOADS}
    return {'version': hardware.PROFILE_VERSION,
            'hardware_signature': snapshot['hardware_signature'],
            'hardware': snapshot, 'workload_preferences': preferences,
            'scores_small': [],
            'scores_large': [dict(backend_id='cuda:0', workload=workload,
                throughput_mp_s=100., elapsed_ms=1., device='Controlled CUDA')
                for workload in hardware.WORKLOADS]}


@contextmanager
def images(size, seed=1481901, mode='RGB'):
    width, height = size
    rng = np.random.default_rng(seed)
    yy, xx = np.indices((height, width))
    rgb = np.stack(((xx * 7 + yy * 3) % 256, (yy * 11 + xx) % 256,
                    ((xx + yy) * 5) % 256), axis=-1).astype(np.uint8)
    rgb[::9, ::7] = rng.integers(0, 256, rgb[::9, ::7].shape, dtype=np.uint8)
    owned = [Image.fromarray(data) for data in (
        rgb, np.roll(rgb, 2, axis=1), np.roll(rgb, 1, axis=0), (rgb // 32 * 32).astype(np.uint8))]
    try:
        if mode == 'RGBA':
            alpha = ((xx + yy) % 3 * 127).astype(np.uint8)
            rgba = np.dstack((rgb, alpha))
            converted = Image.fromarray(rgba)
            owned.append(converted)
            source = converted
        else:
            source = owned[0]
        yield source, owned[1], owned[2], owned[3]
    finally:
        for image in reversed(owned):
            image.close()


def operation(modules, kind, frames, policy='Auto', *, diagnostics=False):
    source, actual, simulated, target = frames
    gpu = modules['UniversalGpuAcceleration']
    gpu.reset_runtime_backend_health()
    result = None
    with patch.dict(sys.modules, modules), \
            patch.object(gpu, '_opencl_context', side_effect=RuntimeError('controlled unavailable device')), \
            patch.dict(sys.modules, {'cupy': None}):
        try:
            if kind == 'evaluator':
                result = modules['AccuracyEvaluator'].evaluate_preview(source, actual,
                    coverage_percent=93.25, plan_execution_accuracy_percent=88.5,
                    return_error_map=diagnostics, return_delta_e_heatmap=diagnostics,
                    gpu_mode=policy)
            else:
                result = modules['SafeCanvasSnapshotScoring'].score_final_canvas_snapshot(
                    snapshot=actual, original_source=source, simulated_final=simulated,
                    quantized_target=target, area=(11, 17, *actual.size), fitted=actual.size,
                    comparison_size=actual.size, actual_elapsed_seconds=7.125,
                    usable_deadline_seconds=15.5, visual_gate_percent=90., gpu_mode=policy)
                if not result.get('available'):
                    raise AssertionError(('Scoring became unavailable', result))
            return comparable(result)
        finally:
            if result is not None:
                for value in result.values():
                    if isinstance(value, Image.Image):
                        value.close()


def observe(operation_call):
    with patch.object(hardware, 'load_hardware_profile', wraps=hardware.load_hardware_profile) as loaded, \
            patch.object(hardware, 'read_json', wraps=hardware.read_json) as read, \
            patch.object(hardware, 'hardware_snapshot', wraps=hardware.hardware_snapshot) as probed:
        result = operation_call()
    return {'profile_loads': loaded.call_count, 'json_reads': read.call_count,
            'current_hardware_observations': probed.call_count,
            'output_sha256': digest(result)}


def paired(before, after, repeats):
    expected = before()
    if after() != expected:
        raise AssertionError('Warm complete-output parity failed.')
    calls = {'before': before, 'after': after}
    samples = {name: [] for name in calls}
    orders = []
    for index in range(repeats):
        order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
        orders.append(list(order))
        for name in order:
            started = time.perf_counter()
            result = calls[name]()
            samples[name].append((time.perf_counter() - started) * 1000.)
            if result != expected:
                raise AssertionError('Timed complete-output parity failed.')
            del result
    report = {'orders': orders, 'exact_output_parity': True, 'output_sha256': digest(expected)}
    for name, call in calls.items():
        report[name + '_samples_ms'] = samples[name]
        report[name + '_median_ms'] = statistics.median(samples[name])
        gc.collect()
        tracemalloc.start()
        try:
            result = call()
            retained, peak = tracemalloc.get_traced_memory()
            if result != expected:
                raise AssertionError('Traced complete-output parity failed.')
            report[name + '_peak_python_bytes'] = peak
            report[name + '_retained_with_result_bytes'] = retained
            del result
            gc.collect()
            report[name + '_retained_after_result_release_bytes'] = tracemalloc.get_traced_memory()[0]
        finally:
            tracemalloc.stop()
    return report


def historical_parity(before, snapshot, path):
    hashes = []
    cases = (
        ('CPU', 'opencl:0:0', 0), ('Auto', 'cpu:numpy', 0),
        ('Auto', 'opencl:0:0', 0), ('Auto', 'opencl:0:0', 10_000_000),
        ('NVIDIA CUDA', 'opencl:0:0', 10_000_000), ('Auto', None, 0))
    for size, mode, seed in (((1, 11), 'RGBA', 1481901), ((13, 1), 'RGB', 1481902),
                              ((37, 29), 'RGB', 1481901), ((37, 29), 'RGBA', 1481902)):
        with images(size, seed, mode) as frames:
            original = [(image.mode, image.size, image.tobytes()) for image in frames]
            for policy, backend, minimum in cases:
                if backend is None:
                    path.unlink(missing_ok=True)
                else:
                    hardware.save_hardware_profile(profile(snapshot, backend=backend, minimum=minimum))
                for kind in (('evaluator', 'snapshot') if min(size) >= 2 else ('evaluator',)):
                    expected = operation(before, kind, frames, policy, diagnostics=kind == 'evaluator')
                    actual = operation(CURRENT, kind, frames, policy, diagnostics=kind == 'evaluator')
                    if actual != expected:
                        raise AssertionError(('Historical complete-output mismatch', size, mode, policy, backend, kind))
                    if original != [(image.mode, image.size, image.tobytes()) for image in frames]:
                        raise AssertionError('Scoring mutated a borrowed input.')
                    hashes.append(digest(actual))
    return {'complete_pairs': len(hashes), 'complete_output_sha256': digest(hashes),
            'coverage': 'CPU/Auto/forced CUDA, current/missing profiles, measured crossover, native-device failure and live quarantine; thin and ordinary RGB/RGBA inputs, every score/route field and diagnostic image byte.'}


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA pairs.')
    before, historical_hashes = historical_modules(revision)
    sources = source_hashes()
    snapshot = hardware.hardware_snapshot()
    report = {'baseline': revision, 'historical_module_sha256': historical_hashes,
        'source_sha256': sources, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'verify_only': verify_only,
        'repeats': None if verify_only else repeats,
        'isolation': 'All three complete historical modules run together; all unrelated dependencies are current on both sides. No old module receives a new private argument.',
        'method': 'Complete-output parity first; six alternating AB/BA pairs only in a coordinated quiet window, with separate tracemalloc peak/retained probes. Work counters run outside timing.',
        'timing_scope': 'Complete public evaluator/final-canvas scorer, fresh local profile JSON/schema/current-hardware validation, full output fingerprint and owned diagnostic-image cleanup. Input images already exist. No GPU, screen capture, drawing input, GUI or network timing.',
        'memory_scope': 'Python/NumPy traced allocations, excluding process RSS, most native Pillow cores and other processes. Retained-with-result and retained-after-result-release are reported separately from peak.',
        'hardware_profile_scope': 'Temporary profile with the current real machine signature and controlled CPU workload preferences. Hardware signature/runtime probes execute normally on each read; backend health is reset equally before each operation. Controlled GPU preferences are used only in untimed parity checks and fail at the native creation/import boundary.',
        'excluded_output_fields': [], 'measurements': {}}
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(hardware, 'PROFILE_FILE', Path(directory) / 'hardware-profile.json'):
        path = hardware.PROFILE_FILE
        report['historical_parity'] = historical_parity(before, snapshot, path)
        measured = profile(snapshot)
        for kind, size, policy, available in (
                ('evaluator', (96, 72), 'Auto', True),
                ('snapshot', (96, 72), 'Auto', True),
                ('evaluator', (640, 480), 'Auto', True),
                ('snapshot', (640, 480), 'Auto', True),
                ('snapshot', (640, 480), 'CPU', True),
                ('snapshot', (96, 72), 'Auto', False)):
            if available:
                hardware.save_hardware_profile(measured)
                if hardware.load_hardware_profile() is None:
                    raise AssertionError('The current-machine fixture profile did not validate.')
            else:
                path.unlink(missing_ok=True)
            with images(size) as frames:
                left = lambda: operation(before, kind, frames, policy)
                right = lambda: operation(CURRENT, kind, frames, policy)
                if verify_only:
                    expected = left()
                    if right() != expected:
                        raise AssertionError('Complete-output parity failed.')
                    row = {'exact_output_parity': True, 'output_sha256': digest(expected)}
                else:
                    row = paired(left, right, repeats)
                row['before_work'] = observe(left)
                row['after_work'] = observe(right)
                expected_old = 0 if policy == 'CPU' else 4 if kind == 'evaluator' else 12
                expected_new = 0 if policy == 'CPU' else 1
                for side, count in (('before', expected_old), ('after', expected_new)):
                    work = row[side + '_work']
                    expected_probes = count if available else 0
                    if (work['profile_loads'], work['json_reads'], work['current_hardware_observations']) != (count, count, expected_probes):
                        raise AssertionError(('Unexpected real profile observation count', side, work))
                    if work['output_sha256'] != row['output_sha256']:
                        raise AssertionError('Instrumentation changed complete results.')
                row['parameters'] = {'kind': kind, 'source_size': list(size), 'gpu_mode': policy,
                    'profile_available': available,
                    'profile_file_bytes': path.stat().st_size if available else 0,
                    'profile_file_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if available else None}
                report['measurements'][f'{kind}_{size[0]}x{size[1]}_{policy}_{"current" if available else "missing"}'] = row
    final_hashes = source_hashes()
    report['source_unchanged'] = sources == final_hashes
    if not report['source_unchanged']:
        report['source_changed_paths'] = sorted(name for name in sources.keys() | final_hashes.keys()
                                                if sources.get(name) != final_hashes.get(name))
        if not verify_only or any(name + '.py' in report['source_changed_paths'] for name in MODULE_NAMES):
            raise AssertionError('Source changed during verification/measurement.')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'docs/v148-batch19-platform-profile-benchmarks.json')
    args = parser.parse_args()
    report = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'verify_only': args.verify_only,
                      'historical_pairs': report['historical_parity']['complete_pairs'],
                      'workloads': len(report['measurements']), 'source_unchanged': report['source_unchanged']}))


if __name__ == '__main__':
    main()
