"""Measure real preview publication/adoption with the historical controller.

Correctness and work observations run separately from wall-time measurements.
Use --verify-only while sources are being edited; measure only in a quiet window.
Tk scheduling/native windows are fixture boundaries. Tcl variables, controller
handlers, the planning thread, public make_plan and estimate arithmetic are real.
"""
import argparse
from contextlib import nullcontext
import gc
import hashlib
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
from types import MethodType
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import DrawBot
from benchmark_v148_image_workflow import fingerprint, old_module
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_ui_batch20_preview_estimate import PreviewEstimateFixture, observe_estimates


ROOT = Path(__file__).resolve().parent
BASELINE = '47777158e5b1daf759993190e638fe507e7691da'
EXCLUDED = VOLATILE_PATHS | {('preview_elapsed_seconds',)}


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def comparable(value, path=()):
    if isinstance(value, dict):
        return {key: comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in EXCLUDED}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


def mismatches(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        if before.keys() != after.keys():
            yield path, sorted(before.keys() - after.keys()), sorted(after.keys() - before.keys())
        for key in before.keys() & after.keys():
            yield from mismatches(before[key], after[key], (*path, key))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            yield path, len(before), len(after)
        else:
            for index, (left, right) in enumerate(zip(before, after)):
                yield from mismatches(left, right, (*path, str(index)))
    elif before != after:
        yield path, before, after


class Operation:
    def __init__(self, module, *, area, phase, dense=False, legacy=False, full_detail=False):
        self.module = module
        self.phase = phase
        self.full_detail = full_detail
        self.case = PreviewEstimateFixture()
        self.case.setUp()
        # Keep the real resource scheduler deterministic at its OS probe edge.
        self.case.stack.enter_context(patch('ResourceAllocation.available_ram_mb', return_value=8192))
        self.app = self.case.app(tuple(area))
        self.plan = self.done = None
        self.closed = False
        try:
            if dense:
                yy, xx = np.indices((72, 96))
                palette = np.array(((255, 255, 255, 255), (40, 70, 170, 255),
                                    (210, 35, 50, 255), (40, 140, 60, 255)), np.uint8)
                source = Image.fromarray(palette[((xx // 4) + (yy // 3)) % 4])
                self.case.images.append(source)
                self.app.original = source
            for name in ('begin_worker', '_handle_event', 'update_plan'):
                setattr(self.app, name, MethodType(getattr(module.DrawBotApp, name), self.app))
            if legacy:
                self.plan = module.make_plan(self.app.original, tuple(area), self.app.options())
                self.case.plans.append(self.plan)
                self.plan['preview_generation'] = self.app.preview_generation
                self.app.activity = 'preview'
                self.done = ('done', 'preview')
            elif phase == 'adoption':
                self.prepare()
        except BaseException:
            self.close()
            raise

    def prepare(self):
        # Allocation tracing substantially slows the dense historical planner.
        # Keep its bounded wait separate from the ordinary ten-second tests.
        self.plan, self.done = self.case.build(self.app, full_detail=self.full_detail,
                                             worker_timeout=60)

    def run(self):
        if self.phase == 'pipeline':
            self.prepare()
        self.app.events.put(('planned', self.plan))
        self.app.events.put(self.done)
        self.module.DrawBotApp.poll(self.app)
        if self.app.plan is not self.plan:
            raise AssertionError('The actual controller did not adopt its own plan.')

    def snapshot(self):
        summary = self.app.summary.get().split('\nProfiler:', 1)[0]
        summary = re.sub(r' Preview planned in [0-9.]+s\.', ' Preview planned in <clock>s.', summary)
        return {'plan': comparable(self.plan), 'draw_time_text': self.app.draw_time_text.get(),
                'summary_without_clocks': summary, 'status': self.app.status.get(),
                'diagnostics_text': self.app.preview_diagnostics_text.get(),
                'source': fingerprint(self.app.original)}

    def close(self):
        if not self.closed:
            self.closed = True
            if not self.case.doCleanups():
                raise AssertionError('The real controller fixture failed to release its owners.')


def call(module, spec, *, trace=False, observe=False):
    operation = Operation(module, **spec)
    try:
        gc.collect()
        if trace:
            tracemalloc.start()
        try:
            with observe_estimates() if observe else nullcontext([]) as records:
                started = time.perf_counter()
                operation.run()
                elapsed = (time.perf_counter() - started) * 1000
                retained, peak = tracemalloc.get_traced_memory() if trace else (None, None)
        finally:
            if trace:
                tracemalloc.stop()
        snapshot = operation.snapshot()
        owner = __import__('threading').get_ident()
        work = {'worker_estimates': 0, 'ui_estimates': 0, 'worker_sequence_calls': 0,
                'ui_sequence_calls': 0, 'worker_path_calls': 0, 'ui_path_calls': 0}
        for record in records:
            prefix = 'ui' if record['thread'] == owner else 'worker'
            work[prefix + '_estimates'] += 1
            work[prefix + '_sequence_calls'] += record['sequence_calls']
            work[prefix + '_path_calls'] += record['path_calls']
        return dict(snapshot=snapshot, elapsed_ms=elapsed, peak_python_bytes=peak,
                    retained_python_bytes=retained, work=work)
    finally:
        operation.close()


WORKLOADS = {
    'adopt-native-84x64': dict(area=(84, 64), phase='adoption'),
    'adopt-dense-320x240': dict(area=(320, 240), phase='adoption', dense=True),
    'adopt-projected-1100x600': dict(area=(1100, 600), phase='adoption'),
    'adopt-legacy-84x64-control': dict(area=(84, 64), phase='adoption', legacy=True),
    'pipeline-native-84x64': dict(area=(84, 64), phase='pipeline'),
    'pipeline-dense-source-96x72': dict(area=(96, 72), phase='pipeline', dense=True),
}


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if repeats < 2 or repeats % 2:
        raise ValueError('Use an even number of at least two balanced AB/BA pairs.')
    sources = source_hashes()
    before = old_module('DrawBot', revision)
    historical_source = subprocess.check_output(['git', 'show', revision + ':DrawBot.py'], cwd=ROOT)
    modules = {'before': before, 'after': DrawBot}
    report = {'baseline': revision, 'historical_controller_sha256': hashlib.sha256(historical_source).hexdigest(),
        'python': sys.version.split()[0], 'platform': platform.platform(), 'numpy': np.__version__,
        'pillow': pillow_version, 'verify_only': verify_only, 'repeats': repeats,
        'method': (f'One complete-output warm parity pair; {repeats} balanced AB/BA timing pairs with counters disabled; '
                   'separate tracemalloc peaks/retention and actual estimate/sequence/path observations. '
                   'Fixture setup and source/plan hashing are outside timers and tracemalloc.'),
        'scope': ('Historical complete DrawBot controller versus current controller, sharing current dependencies. '
                  'Adoption measures real queued planned/done consumption and real Tcl-bound labels. '
                  'Pipeline also measures real preview worker/public make_plan. Native GUI painting, actual mouse '
                  'drawing, Windows/CUDA timing and native Pillow allocations are not measured. '
                  'The available-RAM OS probe is fixed at 8,192 MB; all scheduling decisions remain real. '
                  'The benchmark worker has a 60-second wait bound for dense allocation tracing; '
                  'ordinary preview regressions retain their 10-second bound. '
                  'The pipeline includes the accompanying zero-count preview-snapshot cleanup.'),
        'public_plan_exclusions': ['.'.join(path) for path in sorted(EXCLUDED)],
        'allocation_fixture_note': ('Earlier 320x240 and 192x144 complete-pipeline tracing preflights activated the unchanged '
            '14-second product preview watchdog and produced different fallback plans. Those rejected preflights '
            'are not timing/allocation samples. The complete dense pipeline uses its source size, 96x72, for both timing and '
            'allocation parity; the separate adoption workload still uses 320x240.'),
        'label_exclusions': ['Only actual planning wall-clock text and the wall-clock profiler suffix.'],
        'after_source_sha256': sources, 'source_manifest_sha256': digest(sources), 'measurements': {}}
    for name, spec in WORKLOADS.items():
        observed = {label: call(module, spec, observe=True) for label, module in modules.items()}
        expected = observed['before']['snapshot']
        if expected != observed['after']['snapshot']:
            raise AssertionError((name, list(mismatches(expected, observed['after']['snapshot']))[:12]))
        row = {'workload': spec, 'exact_output_parity': True, 'output_sha256': digest(expected),
               'before_work': observed['before']['work'], 'after_work': observed['after']['work']}
        if not verify_only:
            samples = {'before': [], 'after': []}
            row['pair_order'] = []
            for pair in range(repeats):
                order = ('before', 'after') if pair % 2 == 0 else ('after', 'before')
                row['pair_order'].append(list(order))
                for label in order:
                    result = call(modules[label], spec)
                    if result['snapshot'] != expected:
                        raise AssertionError((name, label, 'timing output parity'))
                    samples[label].append(result['elapsed_ms'])
            for label in modules:
                memory = call(modules[label], spec, trace=True)
                if memory['snapshot'] != expected:
                    raise AssertionError((name, label, 'allocation output parity'))
                row[label + '_samples_ms'] = samples[label]
                row[label + '_median_ms'] = statistics.median(samples[label])
                row[label + '_peak_python_bytes'] = memory['peak_python_bytes']
                row[label + '_retained_python_bytes'] = memory['retained_python_bytes']
        report['measurements'][name] = row
    final = source_hashes()
    report['source_unchanged'] = final == sources
    report['source_changed_paths'] = sorted(name for name in set(sources) | set(final)
                                          if sources.get(name) != final.get(name))
    if not report['source_unchanged'] and (not verify_only or 'DrawBot.py' in report['source_changed_paths']):
        raise AssertionError(('Source changed during the comparison', report['source_changed_paths']))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', default=6, type=int)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch20-ui-estimate-benchmarks.json')
    args = parser.parse_args()
    report = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'workloads': len(report['measurements']),
                      'verify_only': args.verify_only, 'source_unchanged': report['source_unchanged']}))


if __name__ == '__main__':
    main()
