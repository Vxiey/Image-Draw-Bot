"""Exact historical Pixel scheduling/public plans and bounded queue work.

Use --verify-only before the coordinated measurement window. Final timings
compare the complete bb6dfa6 PixelStrokeEngine module with the current module,
using balanced AB/BA pairs and separately measured traced allocations.
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
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

import DrawBot
import ExecutionCostModel as costs
import PixelStrokeEngine as strokes
from benchmark_v148_image_workflow import fingerprint, old_module
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated
from test_v148_rendering_batch24_component_queue import (
    PALETTE, checker_source, components_fixture, observed_queue_work, public_options)


ROOT = Path(__file__).resolve().parent
BASELINE = 'bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c'


def comparable(value, path=()):
    if is_dataclass(value):
        return comparable(asdict(value), path)
    if isinstance(value, dict):
        return {key: comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def linked(module):
    # DrawBot and PixelAccuracyEngine import the public builder/component helper
    # inside their real calls. Both therefore receive the complete old module.
    with patch.dict(sys.modules, {'PixelStrokeEngine': module}):
        yield


def rgba_source(size=(96, 72)):
    image = Image.new('RGBA', size, 'white')
    draw = ImageDraw.Draw(image)
    for y in range(5, size[1] - 5, 4):
        for x in range(5, size[0] - 5, 4):
            index = (x // 4 + y // 4) % 3
            draw.point((x, y), fill=(*PALETTE[(0, 2, 3)[index]], (255, 128, 0)[index]))
    draw.rectangle((size[0] // 3, size[1] // 3, size[0] // 2, size[1] * 2 // 3), fill=(239, 19, 11, 255))
    return image


def flat_source(size=(192, 128)):
    image = Image.new('RGB', size, 'white')
    ImageDraw.Draw(image).rectangle((4, 4, size[0] - 5, size[1] - 5), fill='black')
    return image


def independent_raster(plan):
    """Pillow native centerlines for these brush-one, source-sized fixtures.

    Fixtures leave a four-pixel white border. No line reaches a native clipping
    boundary, so this oracle does not call production geometry/raster helpers.
    The regression suite additionally replays actual execute_plan mouse input.
    """
    assert tuple(plan['fitted']) == tuple(plan['image'].size)
    with Image.new('RGB', plan['preview'].size, 'white') as raster:
        draw = ImageDraw.Draw(raster)
        for entry in plan['execution_sequence']:
            path = entry['path']
            assert int(entry.get('brush_px', 1)) == 1
            rgb = tuple(plan['colors'][entry['color_index']])
            if len(path) == 1:
                draw.point(path[0], fill=rgb)
            elif path:
                draw.line(path, fill=rgb, width=1)
        if raster.tobytes() != plan['preview'].tobytes():
            raise AssertionError('Independent raster differs from the public preview.')
        return hashlib.sha256(raster.tobytes()).hexdigest()


class Operation:
    def __init__(self, name, *, components=None, model=None, source=None, settings=None):
        self.name, self.components, self.model = name, components, model
        self.source, self.settings = source, settings

    def build(self, module):
        if self.source is None:
            return module.schedule_components(self.components, len(PALETTE), cost_model=self.model)
        return DrawBot.make_plan(self.source, self.source.size, dict(self.settings))

    def close(self, result):
        if result is not None and self.source is not None:
            close_plan(result, self.source)

    def run(self, module, *, elapsed=False, trace=False, observe=False, raster=False):
        if trace and tracemalloc.is_tracing():
            raise RuntimeError('An external allocation trace is already active.')
        result = None
        evidence = {}
        if trace:
            gc.collect()
        with linked(module), ExitStack() as stack:
            counts = Counter()
            if observe:
                work, _refs = stack.enter_context(observed_queue_work(module))
                for name in ('paths_seconds', 'prepare_path_cost', 'path_seconds',
                             'color_selection_cost', 'sequence_cost'):
                    original = getattr(costs.ExecutionCostModel, name)
                    def counted(*args, _name=name, _original=original, **kwargs):
                        counts[_name] += 1
                        return _original(*args, **kwargs)
                    stack.enter_context(patch.object(costs.ExecutionCostModel, name, new=counted))
            try:
                if trace:
                    tracemalloc.start()
                try:
                    started = time.perf_counter() if elapsed else None
                    result = self.build(module)
                    if elapsed:
                        evidence['milliseconds'] = 1000 * (time.perf_counter() - started)
                    if trace:
                        retained, peak = tracemalloc.get_traced_memory()
                        evidence.update(peak_python_bytes=peak, retained_with_result_bytes=retained)
                finally:
                    if trace:
                        tracemalloc.stop()
                # Equality/raster work and image disposal are outside both the
                # timer and allocator trace. The returned plan itself is traced.
                output = comparable(result)
                if observe:
                    evidence['queue_work'] = dict(work)
                    evidence['cost_calls'] = dict(counts)
                    evidence['components'] = (result['options']['pixel_stroke_meta']['component_count']
                        if self.source is not None else len(self.components))
                    evidence['paths'] = (result['count'] if self.source is not None else len(result[1]))
                if raster and self.source is not None:
                    evidence['independent_raster_sha256'] = independent_raster(result)
                return output, evidence
            finally:
                self.close(result)


def helper_model(calibration=None):
    return costs.ExecutionCostModel(dict(precision='Ultra', brush_px=1,
        _execution_cost_calibration_override=calibration or {}), (100, 100), (100, 100))


def parity_cases(before):
    hashes = []
    for count in (0, 1, 2, 71, 72, 73, 145, 389):
        for seed in (0, 7, 24):
            components = components_fixture(count, seed=seed, single_phase=seed != 7)
            source_state = comparable(components)
            for model in (None, helper_model(), helper_model({'samples': 5, 'ratio': 1.7,
                    'operation_runtime': {'dot': {'average_seconds': .05}}})):
                expected = comparable(before.schedule_components(components, len(PALETTE), cost_model=model))
                actual = comparable(strokes.schedule_components(components, len(PALETTE), cost_model=model))
                if actual != expected or comparable(components) != source_state:
                    raise AssertionError('Complete historical scheduler output/input parity failed.')
                hashes.append(digest(actual))
    raster_hashes = []
    with calibrated(PALETTE), ExitStack() as stack:
        sources = (stack.enter_context(closing(checker_source((32, 24), margin=4))),
                   stack.enter_context(closing(rgba_source((48, 40)))),
                   stack.enter_context(closing(flat_source((64, 48)))))
        for source in sources:
            original = fingerprint(source)
            for policy in ('Off', 'Auto'):
                for lines in (False, True):
                    for workers in (1, 2):
                        settings = public_options(adaptive_hybrid_cost=policy, lines=lines,
                            cpu_workers=str(workers), cpu_workers_resolved=workers)
                        operation = Operation('historical_public', source=source, settings=settings)
                        expected, old_evidence = operation.run(before, raster=True)
                        actual, new_evidence = operation.run(strokes, raster=True)
                        if actual != expected or new_evidence != old_evidence or fingerprint(source) != original:
                            raise AssertionError('Complete historical public plan/raster/input parity failed.')
                        hashes.append(digest(actual))
                        raster_hashes.append(new_evidence['independent_raster_sha256'])
    return dict(scheduler_pairs=72, public_plan_pairs=24, independent_public_raster_pairs=24,
                complete_output_sha256=digest(hashes), independent_raster_sha256=digest(raster_hashes))


def workloads(stack):
    specs = [
        Operation('scheduler_72_calibrated', components=components_fixture(72, single_phase=True), model=helper_model()),
        Operation('scheduler_8192_calibrated', components=components_fixture(8192, single_phase=True), model=helper_model()),
        Operation('scheduler_32768_geometry', components=components_fixture(32768, single_phase=True)),
    ]
    for name, source, settings in (
        ('public_pixel_checker_64', checker_source((64, 64), margin=4), public_options()),
        ('public_pixel_checker_128', checker_source((128, 128), margin=4), public_options()),
        ('public_pixel_checker_192_geometry', checker_source((192, 192), margin=4),
            public_options(adaptive_hybrid_cost='Off')),
        ('public_pixel_rgba_96', rgba_source(), public_options()),
        ('public_pixel_flat_192', flat_source(), public_options()),
        ('public_pixel_dots_128', checker_source((128, 128), margin=4), public_options(lines=False)),
    ):
        stack.callback(source.close)
        specs.append(Operation(name, source=source, settings=settings))
    return specs


def measure(revision=BASELINE, repeats=6, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA pairs.')
    historical_source = subprocess.check_output(['git', 'show', f'{revision}:PixelStrokeEngine.py'], cwd=ROOT)
    before = old_module('PixelStrokeEngine', revision)
    source_before = source_hashes()
    report = dict(baseline=revision, baseline_module_sha256=hashlib.sha256(historical_source).hexdigest(),
        python=sys.version.split()[0], platform=platform.platform(), numpy=np.__version__, pillow=pillow_version,
        verify_only=verify_only, repeats=0 if verify_only else repeats, source_sha256=source_before,
        method=('Complete historical parity, one untimed workload pair and separate work-count calls; '
                'no elapsed or traced-allocation measurements.' if verify_only else
                f'One warm pair, {repeats} balanced AB/BA pairs, then separate before/after tracemalloc probes. '
                'Complete outputs checked on every warm, counted, timed and traced invocation.'),
        timing_scope='Entire scheduler or entire public make_plan call; inputs prepared before timing. '
            'No cached plan. Fingerprinting, independent raster verification and owned-image cleanup are outside timing.',
        allocation_scope='Python/NumPy allocations during the same build only, including retained returned outputs; '
            'not total process RSS or all Pillow/native allocations. The borrowed input components/images are prepared before tracing.',
        historical_linkage='Complete historical PixelStrokeEngine is installed under its public module name for the actual '
            'DrawBot and PixelAccuracyEngine nested imports. Other modules are shared unchanged between both sides.',
        comparison_exclusions=[list(path) for path in sorted(VOLATILE_PATHS)],
        work_scope='Actual sorted-list pop shifts and actual bounded-list C-pop shifts; profiling/cost-call counting is outside all timing/tracing.',
        parity=parity_cases(before), workloads=[])
    with calibrated(PALETTE), ExitStack() as stack:
        for operation in workloads(stack):
            print('Verifying ' + operation.name, flush=True)
            input_before = fingerprint(operation.source) if operation.source is not None else comparable(operation.components)
            expected, _ = operation.run(before, raster=True)
            actual, raster_evidence = operation.run(strokes, raster=True)
            if actual != expected:
                raise AssertionError('Warm complete output parity failed: ' + operation.name)
            row = dict(name=operation.name, exact_output_parity=True, output_sha256=digest(actual),
                       **raster_evidence)
            for label, module in (('before', before), ('after', strokes)):
                output, evidence = operation.run(module, observe=True)
                if output != expected:
                    raise AssertionError('Counted complete output parity failed: ' + operation.name)
                row[label + '_work'] = evidence
            if row['before_work']['cost_calls'] != row['after_work']['cost_calls']:
                raise AssertionError('Queue change altered actual pricing calls: ' + operation.name)
            if not verify_only:
                samples = {'before': [], 'after': []}
                orders = []
                for pair in range(repeats):
                    order = ('before', 'after') if pair % 2 == 0 else ('after', 'before')
                    orders.append(list(order))
                    for label in order:
                        gc.collect()
                        output, evidence = operation.run(before if label == 'before' else strokes, elapsed=True)
                        if output != expected:
                            raise AssertionError('Timed complete output parity failed: ' + operation.name)
                        samples[label].append(evidence['milliseconds'])
                row['pair_order'] = orders
                for label, module in (('before', before), ('after', strokes)):
                    output, evidence = operation.run(module, trace=True)
                    if output != expected:
                        raise AssertionError('Traced complete output parity failed: ' + operation.name)
                    row[label + '_samples_ms'] = samples[label]
                    row[label + '_median_ms'] = statistics.median(samples[label])
                    row[label + '_allocation'] = evidence
                row['median_change_percent'] = (row['after_median_ms'] / row['before_median_ms'] - 1) * 100
                row['faster_pairs'] = sum(new < old for old, new in zip(samples['before'], samples['after']))
                print(json.dumps({key: row[key] for key in ('name', 'before_median_ms', 'after_median_ms',
                                                          'median_change_percent', 'faster_pairs')}), flush=True)
            input_after = fingerprint(operation.source) if operation.source is not None else comparable(operation.components)
            if input_after != input_before:
                raise AssertionError('A borrowed workload input was modified: ' + operation.name)
            report['workloads'].append(row)
    report['source_sha256_after'] = source_hashes()
    report['sources_unchanged'] = report['source_sha256_after'] == source_before
    if not verify_only and not report['sources_unchanged']:
        raise AssertionError('Source changed during final paired measurement.')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch24-component-queue-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.revision, args.repeats, args.verify_only)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(str(args.output), flush=True)
