"""Complete historical ETA/controller parity and bounded local CPU measurements.

Use --verify-only during development. Time only after the shared source/CPU
freeze. This compares full historical DrawBot/DrawTimeEstimate modules with
current modules and identical current dependencies, not an entire old checkout.
"""
import argparse
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from types import MethodType
import tracemalloc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
BASELINE = 'bfa43deb090c9ef858b04313fad9559ec4acfab1'
WORKLOADS = {
    'pipeline-native': dict(area=(84, 64), phase='pipeline'),
    'pipeline-projected': dict(area=(1100, 600), phase='pipeline'),
    'pipeline-full-detail': dict(area=(84, 64), phase='pipeline', full_detail=True),
    'pipeline-dense': dict(area=(96, 72), phase='pipeline', dense=True),
    'pipeline-mutated-delay-control': dict(area=(84, 64), phase='pipeline', mutate_delay=True),
    'standalone-public-plan-control': dict(area=(84, 64), phase='standalone'),
    'late-estimate-dense': dict(area=(96, 72), phase='late-estimate', dense=True),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def sources():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def observed(module, execution):
    records = []
    local = threading.local()
    owner_thread = threading.get_ident()
    estimate, cold = module.estimate_from_plan, module._sequence_operation_estimate
    sequence, path = execution.ExecutionCostModel.sequence_cost, execution.ExecutionCostModel.path_cost
    primary = getattr(module, '_cost_final_sequence', None)

    def estimate_call(plan):
        record = {'thread': 'main' if threading.get_ident() == owner_thread else 'worker',
                  'path_calls': 0, 'sequence_calls': 0, 'primary_full_precision': None}
        records.append(record)
        previous = getattr(local, 'record', None)
        local.record = record
        try:
            result = estimate(plan)
            record['metadata'] = deepcopy(result)
            return result
        finally:
            local.record = previous

    def cold_call(plan):
        result = cold(plan)
        record = getattr(local, 'record', None)
        if record is not None:
            record['cold_full_precision_seconds'] = result[0]
            record['cold_metadata'] = deepcopy(result[1])
        return result

    def sequence_call(model, rows, **kwargs):
        record = getattr(local, 'record', None)
        if record is not None:
            record['sequence_calls'] += 1
        result = sequence(model, rows, **kwargs)
        if record is not None and primary is None and record['primary_full_precision'] is None:
            record['primary_full_precision'] = asdict(result)
        return result

    def primary_call(*args, **kwargs):
        result = primary(*args, **kwargs)
        record = getattr(local, 'record', None)
        if record is not None:
            record['primary_full_precision'] = asdict(result)
        return result

    def path_call(model, points, **kwargs):
        record = getattr(local, 'record', None)
        if record is not None:
            record['path_calls'] += 1
        return path(model, points, **kwargs)

    with ExitStack() as stack:
        for obj, name, value in ((module, 'estimate_from_plan', estimate_call),
                (module, '_sequence_operation_estimate', cold_call),
                (execution.ExecutionCostModel, 'sequence_cost', sequence_call),
                (execution.ExecutionCostModel, 'path_cost', path_call)):
            stack.enter_context(patch.object(obj, name, new=value))
        if primary is not None:
            stack.enter_context(patch.object(module, '_cost_final_sequence', new=primary_call))
        yield records


@contextmanager
def timed_estimates(module):
    """Measure both real pipeline ETA passes, including the first input seal."""
    records = []
    actual = module.estimate_from_plan
    owner_thread = threading.get_ident()

    def estimate(plan):
        row = {'thread': 'main' if threading.get_ident() == owner_thread else 'worker'}
        records.append(row)
        started = time.perf_counter()
        try:
            return actual(plan)
        finally:
            row['elapsed_ms'] = (time.perf_counter() - started) * 1000

    with patch.object(module, 'estimate_from_plan', new=estimate):
        yield records


class Operation:
    def __init__(self, controller, eta, spec, state, shared):
        self.controller, self.eta, self.spec = controller, eta, spec
        self.base = None
        self.scope = ExitStack()
        self.plan = None
        try:
            self.scope.enter_context(patch.dict(sys.modules, DrawTimeEstimate=eta))
            base_type, timing, speed = shared
            real_speed = speed.load_profile
            self.base = base_type(controller, area=spec['area'], phase='pipeline',
                                  dense=spec.get('dense', False), full_detail=spec.get('full_detail', False))
            self.case, self.app = self.base.case, self.base.app
            self.scope.enter_context(patch.object(timing, 'profile_timing_file', new=lambda key: state / (key + '.json')))
            self.scope.enter_context(patch.object(timing, 'FILE', state / 'legacy.json'))
            self.scope.enter_context(patch.object(speed, 'load_profile', new=lambda key: real_speed(key, state / 'speed.json')))
            self.scope.enter_context(patch.object(controller, 'log_event', new=lambda *_args, **_kwargs: None))
            self.scope.enter_context(patch.object(controller.DrawBotApp, '_schedule_poll', new=lambda *_args: None))
            # Bind the whole actual fixture controller to the selected complete
            # module; no historical event consumer falls through to a new one.
            for name, value in tuple(vars(self.app).items()):
                if isinstance(value, MethodType) and hasattr(controller.DrawBotApp, name):
                    setattr(self.app, name, MethodType(getattr(controller.DrawBotApp, name), self.app))
            if spec.get('mutate_delay'):
                actual = controller.make_plan
                def changed(*args, **kwargs):
                    plan = actual(*args, **kwargs)
                    plan['options']['delay'] = .023
                    return plan
                self.scope.enter_context(patch.object(controller, 'make_plan', new=changed))
            if spec['phase'] == 'late-estimate':
                if hasattr(eta, 'preview_estimate_scope'):
                    self.scope.enter_context(eta.preview_estimate_scope())
                self.plan = controller.make_plan(self.app.original, spec['area'], self.app.options())
                self.case.plans.append(self.plan)
                self.plan.update(target_area=tuple(spec['area']), preview_area=tuple(spec['area']),
                                 full_detail_preview=False)
                if not self.plan['draw_time_estimate']['sequence_model_used']:
                    raise AssertionError('Late-estimate fixture has no actual final execution sequence.')
        except BaseException:
            self.close()
            raise

    def run(self):
        phase = self.spec['phase']
        if phase == 'pipeline':
            self.base.run()
            self.plan = self.base.plan
        elif phase == 'standalone':
            self.plan = self.controller.make_plan(self.app.original, self.spec['area'], self.app.options())
            self.case.plans.append(self.plan)
        else:
            attach = getattr(self.eta, 'attach_preview_draw_time_estimate', self.eta.attach_draw_time_estimate)
            attach(self.plan)

    def snapshot(self):
        self.base.plan = self.plan
        return self.base.snapshot()

    def close(self):
        try:
            self.scope.close()
        finally:
            if self.base is not None:
                self.base.close()


def call(controller, eta, spec, state, shared, execution, *, observe=False, trace=False, timed=False):
    if tracemalloc.is_tracing():
        raise RuntimeError('An external allocation trace is already active.')
    if trace and timed:
        raise ValueError('Elapsed and allocation observations require separate calls.')
    operation = Operation(controller, eta, spec, state, shared)
    try:
        gc.collect()
        with (observed(eta, execution) if observe else nullcontext([])) as records, \
                (timed_estimates(eta) if timed and spec['phase'] == 'pipeline'
                 else nullcontext([])) as estimate_passes:
            if trace:
                tracemalloc.start()
            try:
                started = time.perf_counter() if timed else None
                operation.run()
                elapsed = (time.perf_counter() - started) * 1000 if started is not None else None
                retained, peak = tracemalloc.get_traced_memory() if trace else (None, None)
            finally:
                if trace:
                    tracemalloc.stop()
        # Raw plan/result remains alive at the trace sample; comparisons and
        # image/fixture cleanup are outside both trace and elapsed intervals.
        snapshot = operation.snapshot()
        return dict(snapshot=snapshot, records=records, elapsed_ms=elapsed,
                    estimate_passes=estimate_passes,
                    estimate_total_ms=sum(row['elapsed_ms'] for row in estimate_passes)
                                      if estimate_passes else None,
                    peak_python_bytes=peak, retained_python_bytes=retained)
    finally:
        operation.close()


def measure(revision, repeats, verify_only, runtime):
    import DrawBot, DrawTimeEstimate, DrawTimeCalibration, RealSpeedBudget, ExecutionCostModel
    import numpy as np
    from PIL import __version__ as pillow_version
    from benchmark_v148_image_workflow import old_module
    from benchmark_v148_ui_batch20_estimate import Operation as BaseOperation, EXCLUDED, mismatches
    old_eta = old_module('DrawTimeEstimate', revision)
    with patch.dict(sys.modules, DrawTimeEstimate=old_eta):
        old_controller = old_module('DrawBot', revision)
    modules = {'before': (old_controller, old_eta), 'after': (DrawBot, DrawTimeEstimate)}
    shared = (BaseOperation, DrawTimeCalibration, RealSpeedBudget)
    initial_sources = sources()
    report = {'schema': 1, 'baseline_commit': revision, 'verify_only': verify_only,
              'repeats': 0 if verify_only else repeats, 'measurements': {},
              'historical_sha256': {name: hashlib.sha256(subprocess.check_output(
                  ['git', 'show', revision + ':' + name + '.py'], cwd=ROOT)).hexdigest()
                  for name in ('DrawBot', 'DrawTimeEstimate')},
              'source_sha256': initial_sources, 'source_manifest_sha256': digest(initial_sources),
              'python': sys.version.split()[0], 'platform': platform.platform(),
              'numpy': np.__version__, 'pillow': pillow_version,
              'method': ('Untimed actual work/full-output comparison only.' if verify_only else
                  f'One observed parity pair, one unobserved warm parity pair, {repeats} balanced AB/BA pairs per workload; separate live-result tracemalloc probes. '
                  'Timed pipeline calls also wrap and delegate both real estimate_from_plan passes, recording each elapsed interval and their sum. '
                  'The first pass includes creation of the local input seal. Wrapper setup is outside the complete pipeline timer; both sides have identical instrumentation. '
                  'No extra timers run during observed, warm, standalone, allocation or verify-only ETA passes.'),
              'scope': 'Complete historical DrawBot and DrawTimeEstimate, with identical current other dependencies. Pipeline is real update_plan/worker/make_plan/queue/poll/Tcl labels. Standalone is real public make_plan; late-estimate is the actual late estimator with its plan and possible private observation prepared before measurement. Setup, source construction, calibration directory routing, normalization, hashing and cleanup are outside intervals. RAM OS probe is fixed to8192MB on both sides; product clocks/watchdogs remain real. No native widget painting, physical mouse, Windows, GPU, RSS or general speed claim.',
              'excluded_clock_paths': ['.'.join(path) for path in sorted(EXCLUDED)],
              'label_exclusions': ['Existing planning elapsed text and profiler suffix only.']}
    try:
        for name, spec in WORKLOADS.items():
            report['active_observation'] = {'workload': name, 'stage': 'observed parity'}
            state = runtime / name
            state.mkdir()
            row = {'workload': spec, 'full_output_parity': False, 'full_precision_parity': False,
                   'work': {}}
            report['measurements'][name] = row
            results = {}
            for label, pair in modules.items():
                report['active_observation']['side'] = label
                results[label] = call(*pair, spec, state, shared, ExecutionCostModel, observe=True)
                row['work'][label] = results[label]['records']
                row[label + '_output_sha256'] = digest(results[label]['snapshot'])
            expected = results['before']['snapshot']
            if results['after']['snapshot'] != expected:
                raise AssertionError((name, list(mismatches(expected, results['after']['snapshot']))[:12]))
            def numeric(rows):
                return [{key: row.get(key) for key in
                         ('metadata', 'primary_full_precision', 'cold_full_precision_seconds', 'cold_metadata')}
                        for row in rows]
            if numeric(results['before']['records']) != numeric(results['after']['records']):
                raise AssertionError((name, 'Full-precision estimator output differs'))
            row.update(full_output_parity=True, full_precision_parity=True,
                       output_sha256=digest(expected))
            if not verify_only:
                for label, pair in modules.items():
                    report['active_observation'] = {'workload': name, 'stage': 'warm parity', 'side': label}
                    if call(*pair, spec, state, shared, ExecutionCostModel)['snapshot'] != expected:
                        raise AssertionError((name, 'Unobserved warm output differs'))
                samples = {'before': [], 'after': []}
                for label, values in samples.items():
                    row[label + '_samples_ms'] = values
                    if spec['phase'] == 'pipeline':
                        row[label + '_estimate_pass_samples'] = []
                        row[label + '_estimate_total_samples_ms'] = []
                row['pair_order'] = []
                for index in range(repeats):
                    order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
                    row['pair_order'].append(order)
                    for label in order:
                        report['active_observation'] = {'workload': name, 'stage': 'timed pair',
                                                        'pair': index, 'side': label}
                        result = call(*modules[label], spec, state, shared, ExecutionCostModel, timed=True)
                        samples[label].append(result['elapsed_ms'])
                        if spec['phase'] == 'pipeline':
                            row[label + '_estimate_pass_samples'].append(result['estimate_passes'])
                            row[label + '_estimate_total_samples_ms'].append(result['estimate_total_ms'])
                            if [item['thread'] for item in result['estimate_passes']] != [
                                    item['thread'] for item in results[label]['records']]:
                                raise AssertionError((name, label, 'Timed ETA pass/thread structure differs'))
                        if result['snapshot'] != expected:
                            raise AssertionError((name, label, 'Timed output differs'))
                for label, pair in modules.items():
                    report['active_observation'] = {'workload': name, 'stage': 'allocation parity', 'side': label}
                    memory = call(*pair, spec, state, shared, ExecutionCostModel, trace=True)
                    row[label + '_peak_python_bytes'] = memory['peak_python_bytes']
                    row[label + '_retained_python_bytes'] = memory['retained_python_bytes']
                    if memory['snapshot'] != expected:
                        raise AssertionError((name, label, 'Traced output differs'))
                    row[label + '_median_ms'] = statistics.median(samples[label])
                    if spec['phase'] == 'pipeline':
                        row[label + '_estimate_total_median_ms'] = statistics.median(
                            row[label + '_estimate_total_samples_ms'])
            print(json.dumps({'workload': name, 'parity': True, 'measured': not verify_only}), flush=True)
        report['passed'] = True
        report.pop('active_observation', None)
    except BaseException as error:
        report['passed'] = False
        report['failure'] = {'type': type(error).__name__, 'message': str(error),
                             'traceback': traceback.format_exc()}
    finally:
        after_sources = sources()
        report['source_unchanged'] = after_sources == initial_sources
        report['source_after_manifest_sha256'] = digest(after_sources)
        report['source_changed_paths'] = sorted(key for key in set(initial_sources) | set(after_sources)
                                              if initial_sources.get(key) != after_sources.get(key))
        if not report['source_unchanged']:
            report['passed'] = False
            report['source_failure'] = 'Source changed during the observation.'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch29-estimate-benchmarks.json')
    args = parser.parse_args()
    if args.repeats < 2 or args.repeats % 2:
        parser.error('Use an even count of at least two balanced pairs.')
    # Reserve a new artifact before imports/work; never replace a prior raw run.
    with args.output.open('x', encoding='utf-8') as stream:
        result = {'passed': False, 'baseline_commit': args.baseline, 'verify_only': args.verify_only}
        try:
            if tracemalloc.is_tracing():
                raise RuntimeError('An external allocation trace is already active.')
            with tempfile.TemporaryDirectory(prefix='eta-benchmark-') as directory, ExitStack() as stack:
                import RuntimePaths
                runtime = Path(directory)
                stack.enter_context(patch.object(RuntimePaths, 'source_dir', return_value=runtime))
                stack.enter_context(patch.object(RuntimePaths, 'data_dir', return_value=runtime))
                stack.enter_context(patch.object(RuntimePaths, 'resource_dir', return_value=ROOT))
                result = measure(args.baseline, args.repeats, args.verify_only, runtime)
        except BaseException as error:
            result['passed'] = False
            result['failure'] = {'type': type(error).__name__, 'message': str(error),
                                 'traceback': traceback.format_exc()}
        finally:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n'); stream.flush()
    print(json.dumps({'passed': result['passed'], 'workloads': len(result.get('measurements', {})),
                      'source_files': len(result.get('source_sha256', {})),
                      'source_manifest_sha256': result.get('source_manifest_sha256')}), flush=True)
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
