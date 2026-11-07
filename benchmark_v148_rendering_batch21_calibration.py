"""Compare complete public planning with operation-local timing observations.

--verify-only performs work counts and full historical parity without timings.
Final measurements require a coordinated quiet source/CPU window. The historical
DrawBot and DrawTimeCalibration modules and the imported execution-cost alias
are linked together; old planning never uses the new shared-row copier.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
from dataclasses import asdict, is_dataclass
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
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import DrawBot
import AutoSketchBudget
import DrawTimeCalibration as timing
import ExecutionCostModel as execution
from benchmark_v148_colour_batch20 import digest
from benchmark_v148_image_workflow import fingerprint, old_module
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch21_calibration_scope import (
    observed, public_environment, public_options, public_source)


ROOT = Path(__file__).resolve().parent
BASELINE = 'ec22fd8739573adc2df1b3e33dbe1a98a09b9c99'
NAMES = ('DrawTimeCalibration', 'DrawBot')
CURRENT = {'DrawTimeCalibration': timing, 'DrawBot': DrawBot}
CALLERS = ('paint_pixel', 'paint_fill', 'gartic_hybrid', 'gartic_hybrid_fill',
           'paint_dynamic', 'gartic_sketch_auto')
KEY_FIELDS = ('profile_key', 'profile_name', 'speed', 'precision', 'use_region_fill_engine',
    'effective_paint_tool', 'paint_tool', 'tool_strategy', 'brush_px', 'custom_color_workflow',
    'drawing_mode', 'mode', 'render_preset', 'draw_quality', 'render_style',
    'drawing_style_resolved', 'drawing_style')
EXCLUDED = VOLATILE_PATHS | {
    (*prefix, field)
    for prefix in (('options', 'adaptive_hybrid_meta', 'timings'), ('adaptive_hybrid_meta', 'timings'))
    for field in ('region_analysis_seconds', 'candidate_scoring_seconds',
                  'plan_simulation_seconds', 'adaptive_hybrid_total_seconds')}


def comparable(value, path=()):
    if is_dataclass(value):
        return comparable(asdict(value), path)
    if isinstance(value, dict):
        return {key if isinstance(key, str) else repr((type(key).__name__, key)):
                comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in EXCLUDED}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def historical_modules(revision):
    modules, hashes = {}, {}
    for name in NAMES:
        with patch.dict(sys.modules, modules):
            modules[name] = old_module(name, revision)
        source = subprocess.check_output(['git', 'show', f'{revision}:{name}.py'], cwd=ROOT)
        hashes[name] = hashlib.sha256(source).hexdigest()
    return modules, hashes


@contextmanager
def linked(modules):
    with patch.dict(sys.modules, modules), \
            patch.object(execution, 'correction_for', new=modules['DrawTimeCalibration'].correction_for):
        yield


@contextmanager
def environment(directory, old):
    # One common palette/storage fixture stays outside all measured intervals.
    # The old reader is real and independent, not a patched current load_profile.
    with public_environment(directory), ExitStack() as stack:
        legacy = old['DrawTimeCalibration']
        stack.enter_context(patch.object(legacy, 'profile_timing_file',
            side_effect=lambda key: Path(directory) / (key + '.json')))
        stack.enter_context(patch.object(legacy, 'FILE', Path(directory) / 'legacy.json'))
        stack.enter_context(patch.object(old['DrawBot'], 'custom_rgb_available', return_value=False))
        stack.enter_context(patch.object(old['DrawBot'], 'log_event'))
        yield


class Operation:
    def __init__(self, modules, source, name, *, direct=False, manual_sketch=False):
        self.modules, self.source, self.name, self.direct = modules, source, name, direct
        self.options = public_options(name, source.size)
        if name == 'gartic_sketch_auto' and not manual_sketch:
            # The real Unlimited Auto branch still recursively plans Detailed,
            # but has no wall-clock-derived remaining budget in its output.
            self.options.update(time_budget_mode='Unlimited', unlimited_time=True)

    def build(self):
        if self.direct:
            return self.modules['DrawTimeCalibration'].correction_for(self.options)
        return self.modules['DrawBot'].make_plan(self.source, self.source.size, dict(self.options))

    def close(self, result):
        if result is not None and not self.direct:
            close_plan(result, self.source)

    def run(self, *, elapsed=False, trace=False):
        result = None
        evidence = {}
        with linked(self.modules):
            if trace:
                gc.collect()
                tracemalloc.start()
            try:
                started = time.perf_counter() if elapsed else None
                result = self.build()
                if elapsed:
                    evidence['elapsed_ms'] = (time.perf_counter() - started) * 1000.
                if trace:
                    retained, peak = tracemalloc.get_traced_memory()
                    evidence.update(peak_python_bytes=peak, retained_with_result_bytes=retained)
                    tracemalloc.stop()
                # Fingerprinting and image disposal are outside the public
                # planner's elapsed/allocation interval on both sides.
                return comparable(result), evidence
            finally:
                if trace and tracemalloc.is_tracing():
                    tracemalloc.stop()
                self.close(result)

    def work(self):
        result = None
        with linked(self.modules), observed(self.modules['DrawTimeCalibration']) as (
                calls, ensured, read, validated):
            try:
                result = self.build()
                output = comparable(result)
                return {'correction_calls': len(calls), 'database_loads': ensured.call_count,
                    'json_reads': read.call_count, 'validated_rows': validated.call_count,
                    'context_keys': dict(Counter(row['key'] for _options, row in calls)),
                    'context_corrections': [row for _options, row in calls],
                    'output_sha256': digest(output)}
            finally:
                self.close(result)


def prepare_bank(directory, old):
    contexts = {}
    with closing(public_source()) as source, linked(old), observed(old['DrawTimeCalibration']) as (
            calls, _ensured, _read, _valid):
        for name in CALLERS:
            plan = Operation(old, source, name).build()
            close_plan(plan, source)
        for options, _row in calls:
            settings = {key: options[key] for key in KEY_FIELDS if key in options}
            contexts[timing._key(settings)] = settings
    # Only contexts actually requested by these public plans are learned.
    # Different contexts deliberately have different correction/runtime values.
    legacy = old['DrawTimeCalibration']
    with patch.object(legacy.time, 'time', return_value=1_700_000_000.):
        for index, (key, options) in enumerate(sorted(contexts.items())):
            for _ in range(3):
                result = legacy.record_sample(options, 10, 11.0 + index * .6,
                    completed_paths=20, operation_counts={'short_stroke': 20},
                    operation_runtime={'short_stroke': dict(average_seconds=.04 + index * .005,
                        count=20, samples=1, observations=20)})
                if not result.get('recorded'):
                    raise AssertionError(('Could not seed a real calibration record', key, result))
    files = {path.name: json.loads(path.read_text(encoding='utf-8'))
             for path in Path(directory).glob('*.json')}
    return contexts, files


def install_bank(directory, contexts, files, kind):
    for path in Path(directory).glob('*.json'):
        path.unlink()
    if kind == 'missing':
        return
    if kind == 'invalid':
        for filename in files:
            (Path(directory) / filename).write_text('{broken json', encoding='utf-8')
        return
    combined = {}
    for filename, database in files.items():
        profiles = {}
        for key, row in database['profiles'].items():
            settings = contexts[key]
            target = timing._v2_key(settings) if kind == 'v2' else (
                timing._legacy_key(settings) if kind in ('v1', 'migration') else key)
            profiles.setdefault(target, row)
        combined.update(profiles)
        if kind != 'migration':
            version = {'v2': 2, 'v1': 1}.get(kind, 4)
            (Path(directory) / filename).write_text(json.dumps(dict(version=version, profiles=profiles),
                ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    if kind == 'migration':
        (Path(directory) / 'legacy.json').write_text(json.dumps(dict(version=1, profiles=combined),
            ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def files_snapshot(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(directory).glob('*.json'))}


def historical_parity(old, directory, contexts, files):
    fingerprints = []
    manual_pairs = 0
    for size, variant in (((48, 36), 'RGB'), ((128, 96), 'RGBA-alpha')):
        with closing(public_source(size)) as graphic:
            if variant == 'RGB':
                source = graphic.convert('RGB')
            else:
                data = np.asarray(graphic).copy()
                data[::5, ::3, 3] = 96
                data[1::7, 1::4, 3] = 0
                source = Image.fromarray(data)
            with closing(source):
                source_state = source.tobytes(), dict(source.info)
                for kind in ('missing', 'invalid', 'v4', 'v2', 'v1', 'migration'):
                    for name in CALLERS:
                        outputs, final_files = [], []
                        for modules in (old, CURRENT):
                            install_bank(directory, contexts, files, kind)
                            output, _ = Operation(modules, source, name).run()
                            outputs.append(output)
                            final_files.append(files_snapshot(directory))
                        if outputs[0] != outputs[1]:
                            raise AssertionError(('Complete historical plan mismatch', size, variant, kind, name))
                        if final_files[0] != final_files[1]:
                            raise AssertionError(('Historical file/migration parity failed', kind, name))
                        if (source.tobytes(), source.info) != source_state:
                            raise AssertionError('Planning mutated the borrowed image.')
                        fingerprints.append(digest(outputs[1]))
                    # Manual Auto spends actual elapsed planning time from its
                    # deadline. Compare that complete arithmetic under equal
                    # clock input only in this untimed historical oracle.
                    outputs, final_files = [], []
                    for modules in (old, CURRENT):
                        install_bank(directory, contexts, files, kind)
                        with patch.object(AutoSketchBudget, 'time',
                                SimpleNamespace(monotonic=lambda: 123.0)):
                            output, _ = Operation(modules, source, 'gartic_sketch_auto',
                                                  manual_sketch=True).run()
                        outputs.append(output)
                        final_files.append(files_snapshot(directory))
                    if outputs[0] != outputs[1] or final_files[0] != final_files[1]:
                        raise AssertionError(('Manual Auto complete budget/file parity failed', size, kind))
                    if (source.tobytes(), source.info) != source_state:
                        raise AssertionError('Manual Auto changed the borrowed source.')
                    fingerprints.append(digest(outputs[1]))
                    manual_pairs += 1
    return {'complete_public_pairs': len(fingerprints), 'outputs_sha256': digest(fingerprints),
        'manual_auto_controlled_clock_pairs': manual_pairs,
        'coverage': 'Six actual public callers plus manual Auto Sketch; small RGB and RGBA with partial/zero alpha; missing, malformed, distinct learned v4, v2, v1 and one-time legacy migration. All image bytes, paths, colors, selectors, estimates, calibration keys and nonclock metadata; post-operation file bytes also match. Only the additional untimed manual Auto oracle supplies equal monotonic clock input, retaining all remaining-budget arithmetic; measured Auto uses the real Unlimited recursive route without clock patches.'}


def paired(before, after, repeats):
    expected, _ = before.run()
    actual, _ = after.run()
    if expected != actual:
        raise AssertionError('Warm public-output parity failed.')
    operations = {'before': before, 'after': after}
    samples = {side: [] for side in operations}
    orders = []
    for index in range(repeats):
        order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
        orders.append(list(order))
        for side in order:
            actual, evidence = operations[side].run(elapsed=True)
            if actual != expected:
                raise AssertionError(('Timed full-output parity failed', side))
            samples[side].append(evidence['elapsed_ms'])
    result = {'orders': orders, 'exact_output_parity': True, 'output_sha256': digest(expected)}
    for side, operation in operations.items():
        result[side + '_samples_ms'] = samples[side]
        result[side + '_median_ms'] = statistics.median(samples[side])
        actual, evidence = operation.run(trace=True)
        if actual != expected:
            raise AssertionError(('Traced full-output parity failed', side))
        for key, value in evidence.items():
            result[side + '_' + key] = value
    return result


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA samples.')
    old, old_hashes = historical_modules(revision)
    hashes = source_hashes()
    report = {'baseline': revision, 'historical_module_sha256': old_hashes,
        'source_sha256': hashes, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'verify_only': verify_only,
        'repeats': None if verify_only else repeats,
        'historical_linkage': 'Complete historical DrawBot and DrawTimeCalibration modules are installed together, including ExecutionCostModel.correction_for. Local imports therefore use the selected complete reader; no historical controller uses new nested-row isolation. Other dependencies are the same current modules on both sides.',
        'method': 'Full historical output/file parity and separate work observations; six balanced AB/BA elapsed pairs and separate traced allocations only in a coordinated quiet window.',
        'timing_scope': 'The actual public make_plan call (or one unscoped correction_for control), including local database read/schema validation and planner output construction. Source/palette/file fixture preparation, module linking, output fingerprinting and owned image cleanup are outside elapsed intervals. No native input, UI rendering, network, GPU or whole-application speed claim.',
        'memory_scope': 'Separate tracemalloc peak and retained-with-result for the same public call. Python/NumPy tracked allocations, not total RSS or most native Pillow cores. At most one existing reader-bounded database remains live inside a nested planning operation; it is released before the public plan returns.',
        'calibration_source': 'Only the eight full contexts actually requested by the six recorded public workloads are seeded through the historical production record_sample, three samples each. Context ratios and operation timings differ. No filler history is added to make parsing artificially expensive.',
        'manual_auto_scope': 'The original work-count audit used Manual Auto Sketch. Its remaining drawing budget includes actual elapsed planning time. Final timed Sketch uses explicitly Unlimited Auto; Manual Auto is retained separately as an untimed equal-clock complete-output/work-count oracle. No Manual-Auto elapsed speed claim is made.',
        'excluded_output_fields': sorted('/'.join(path) for path in EXCLUDED),
        'measurements': {}}
    with tempfile.TemporaryDirectory(prefix='batch21-calibration-benchmark-') as directory, \
            environment(directory, old):
        contexts, files = prepare_bank(directory, old)
        report['seeded_contexts'] = sorted(contexts)
        report['historical_parity'] = historical_parity(old, directory, contexts, files)
        with closing(public_source()) as source:
            install_bank(directory, contexts, files, 'v4')
            with patch.object(AutoSketchBudget, 'time', SimpleNamespace(monotonic=lambda: 123.0)):
                manual = {side: Operation(modules, source, 'gartic_sketch_auto', manual_sketch=True).work()
                          for side, modules in (('before', old), ('after', CURRENT))}
            if manual['before']['output_sha256'] != manual['after']['output_sha256']:
                raise AssertionError('Untimed Manual Auto work-count output parity failed.')
            report['untimed_manual_auto_work'] = manual
            scenarios = [(name, 'v4', False) for name in CALLERS]
            scenarios += [('paint_pixel', 'missing', False), ('paint_pixel', 'v4', True)]
            for name, kind, direct in scenarios:
                install_bank(directory, contexts, files, kind)
                before_files = files_snapshot(directory)
                operations = [Operation(modules, source, name, direct=direct) for modules in (old, CURRENT)]
                if direct:
                    # Use an actual normalized Pixel-plan context for the public
                    # unscoped control, rather than raw UI options with another key.
                    selected = next(settings for key, settings in contexts.items()
                                    if settings.get('draw_quality') == 'Pixel Accurate')
                    for operation in operations:
                        operation.options = dict(selected)
                if verify_only:
                    expected, _ = operations[0].run()
                    actual, _ = operations[1].run()
                    if actual != expected:
                        raise AssertionError(('Full workload parity failed', name, kind, direct))
                    row = {'exact_output_parity': True, 'output_sha256': digest(expected)}
                else:
                    row = paired(*operations, repeats)
                for side, operation in zip(('before', 'after'), operations):
                    row[side + '_work'] = operation.work()
                    if row[side + '_work']['output_sha256'] != row['output_sha256']:
                        raise AssertionError(('Work observation changed output', side, name))
                old_work, new_work = row['before_work'], row['after_work']
                if old_work['context_keys'] != new_work['context_keys'] or old_work['context_corrections'] != new_work['context_corrections']:
                    raise AssertionError(('Distinct correction lookups changed', name))
                if new_work['database_loads'] != 1 or new_work['json_reads'] != (0 if kind == 'missing' else 1):
                    raise AssertionError(('Unexpected operation database count', name, new_work))
                if old_work['database_loads'] != old_work['correction_calls']:
                    raise AssertionError(('Historical reader was not fully linked', name, old_work))
                if files_snapshot(directory) != before_files:
                    raise AssertionError('Read-only planning changed the seeded database.')
                caller_name = name + ('_unlimited' if name == 'gartic_sketch_auto' else '')
                row['parameters'] = {'public_caller': caller_name, 'source_size': list(source.size),
                    'source_mode': source.mode, 'database_kind': kind, 'direct_unscoped_control': direct,
                    'time_budget_mode': operations[0].options.get('time_budget_mode'),
                    'database_files': {path.name: dict(bytes=path.stat().st_size,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        rows=len(json.loads(path.read_text())['profiles']))
                        for path in sorted(Path(directory).glob('*.json'))}}
                report['measurements'][caller_name + ('_unscoped' if direct else '_' + kind)] = row
    final_hashes = source_hashes()
    report['source_unchanged'] = hashes == final_hashes
    if not report['source_unchanged']:
        report['source_changed_paths'] = sorted(name for name in hashes.keys() | final_hashes.keys()
            if hashes.get(name) != final_hashes.get(name))
        if not verify_only or any(name + '.py' in report['source_changed_paths'] for name in NAMES):
            raise AssertionError('Source changed during historical comparison or timing.')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch21-calibration-benchmarks.json')
    args = parser.parse_args()
    report = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'verify_only': args.verify_only,
        'historical_public_pairs': report['historical_parity']['complete_public_pairs'],
        'workloads': len(report['measurements']), 'source_unchanged': report['source_unchanged']}))


if __name__ == '__main__':
    main()
