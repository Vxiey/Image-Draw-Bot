"""Complete historical Pixel callers and bounded operation-local topology.

Verify-only performs no timing/allocation probes. Final runs need root's quiet
window and six balanced AB/BA pairs. Historical replay helpers below are also
used by the older batch12/24 harnesses to keep their original causal scope.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from dataclasses import asdict, is_dataclass
import gc
import hashlib
import importlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import types
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

import DrawBot
import PixelRegionTopology
from benchmark_v148_image_workflow import fingerprint
from test_pixel_accuracy_engine_v1088 import pm_from_index
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated
from test_v148_rendering_batch24_component_queue import PALETTE, checker_source, public_options
from test_v148_rendering_batch26_topology import (
    alpha_source, block_source, observe_topology, timed_source, timed_options,
    TIMED_ASSET, TIMED_CROP, TIMED_PALETTE, TIMED_PALETTE_NAMES)


ROOT = Path(__file__).resolve().parent
BASELINE = '5b0c22ac5dc620a911fa2a1f6216e272f644f7db'
GRAPH_NAMES = ('PixelStrokeEngine', 'PixelAccuracyEngine', 'SubjectFocus', 'DrawBot')
COMPARISON_EXCLUSIONS = VOLATILE_PATHS | {
    ('options', 'pixel_stroke_meta', 'sections', 'subject', 'planning_stage_seconds'),
    ('options', 'pixel_stroke_meta', 'sections', 'background', 'planning_stage_seconds'),
}


def comparable(value, path=()):
    if is_dataclass(value):
        return comparable(asdict(value), path)
    if isinstance(value, dict):
        return {key: comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in COMPARISON_EXCLUSIONS}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def first_difference(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        if before.keys() != after.keys():
            return f'{path}: dictionary keys differ {before.keys() ^ after.keys()}'
        for key in before:
            if before[key] != after[key]:
                return first_difference(before[key], after[key], (*path, key))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return f'{path}: lengths {len(before)} != {len(after)}'
        for index, (left, right) in enumerate(zip(before, after)):
            if left != right:
                return first_difference(left, right, (*path, index))
    return f'{path}: {before!r} != {after!r}'


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def current_graph():
    return {name: importlib.import_module(name) for name in GRAPH_NAMES}


def historical_graph(revision):
    """Compile the four complete modules with matching public import names.

    Current modules are loaded first, so loading historical callers cannot
    initialize a shared dependency with a half-constructed historical graph.
    Module aliases stay registered for dataclass type resolution; no plan or
    image data is retained there. This is benchmark-only module linkage.
    """
    current_graph()
    sources = {name: subprocess.check_output(['git', 'show', f'{revision}:{name}.py'], cwd=ROOT)
               for name in GRAPH_NAMES}
    modules = {}
    for name in GRAPH_NAMES:
        alias = '_pixel_history_' + revision[:12] + '_' + name
        module = types.ModuleType(alias)
        module.__file__ = str(ROOT / (name + '.py'))
        module.__package__ = ''
        sys.modules[alias] = module
        modules[name] = module
    with patch.dict(sys.modules, modules):
        for name in GRAPH_NAMES:
            exec(compile(sources[name], modules[name].__file__, 'exec'), modules[name].__dict__)
    return modules, {name: hashlib.sha256(source).hexdigest() for name, source in sources.items()}


@contextmanager
def linked_graph(graph, overrides=None):
    with patch.dict(sys.modules, dict(graph, **(overrides or {}))):
        yield


@contextmanager
def controlled_environment(*graphs):
    """The same real calibration file and deterministic external inputs."""
    with calibrated(PALETTE), ExitStack() as stack:
        stack.enter_context(patch('ResourceAllocation.available_ram_mb', return_value=8192))
        for graph in graphs:
            controller = graph['DrawBot']
            stack.enter_context(patch.object(controller, 'custom_rgb_available', return_value=False))
            stack.enter_context(patch.object(controller, 'log_event'))
        yield


def independent_raster(plan):
    """Independent source-sized brush-one Pillow centerlines of final delivery."""
    if tuple(plan['fitted']) != tuple(plan['image'].size):
        raise AssertionError('This native raster oracle requires source-sized placement.')
    with closing(Image.new('RGB', plan['preview'].size, 'white')) as raster:
        pen = ImageDraw.Draw(raster)
        for entry in plan['execution_sequence']:
            if int(entry.get('brush_px', 1)) != 1:
                raise AssertionError('This native raster oracle requires brush one.')
            path = entry['path']
            rgb = tuple(plan['colors'][entry['color_index']])
            if len(path) == 1:
                pen.point(path[0], fill=rgb)
            elif path:
                pen.line(path, fill=rgb, width=1)
        if raster.tobytes() != plan['preview'].tobytes():
            raise AssertionError('Independent native raster does not match public preview.')
        return hashlib.sha256(raster.tobytes()).hexdigest()


class Operation:
    def __init__(self, name, source, settings, *, area=None, timed_case=False):
        self.name, self.source, self.settings = name, source, settings
        self.area = tuple(area) if area is not None else None
        self.timed_case = timed_case

    @contextmanager
    def fixture_scope(self):
        # A whole comparison/workload shares one actual calibration directory,
        # including returned history paths. Never normalize those output fields.
        with ExitStack() as stack:
            if self.timed_case:
                stack.enter_context(calibrated(TIMED_PALETTE, names=TIMED_PALETTE_NAMES))
                stack.enter_context(patch('RealSpeedBudget.load_profile', return_value=None))
            yield

    def run(self, graph, *, elapsed=False, trace=False, observe=False, raster=False):
        if trace and tracemalloc.is_tracing():
            raise RuntimeError('An external allocation trace is already active.')
        controller, strokes = graph['DrawBot'], graph['PixelStrokeEngine']
        source, size, settings = self.source, self.area or self.source.size, dict(self.settings)
        result = None
        evidence = {}
        if trace:
            gc.collect()
        with linked_graph(graph), ExitStack() as stack:
            if observe:
                calls, rows, boundaries, refs = stack.enter_context(
                    observe_topology(strokes, controller, check_scalar=False))
            try:
                if trace:
                    tracemalloc.start()
                try:
                    started = time.perf_counter() if elapsed else None
                    result = controller.make_plan(source, size, settings)
                    if elapsed:
                        evidence['milliseconds'] = (time.perf_counter() - started) * 1000
                    if trace:
                        retained, peak = tracemalloc.get_traced_memory()
                        evidence.update(peak_python_bytes=peak, retained_with_result_bytes=retained)
                finally:
                    if trace:
                        tracemalloc.stop()
                output = comparable(result)
                if self.timed_case:
                    budget = result['options']['pixel_accuracy_meta']['progressive_time_budget']
                    if not budget['active'] or budget['paths_omitted'] <= 0:
                        raise AssertionError('The actual timer fixture must omit work under its unchanged budget.')
                    if (budget['phase_order'] != 'original execution order' or
                            budget['admission_priority'] != 'fill -> mid detail -> protected cleanup -> fine detail'):
                        raise AssertionError('The incoming ordered-admission contract changed.')
                    evidence['progressive_time_budget'] = dict(budget)
                if observe:
                    if any(ref() is not None for _, ref in refs):
                        raise AssertionError('A private label map reached the returned plan boundary.')
                    if any(row['label_owners_still_alive'] for row in boundaries):
                        raise AssertionError('A private label map reached finish_plan/export.')
                    evidence.update(connected_component_calls=len(calls),
                        row_statistic_calls=len(rows), topology_calls=calls,
                        path_count=result['count'], finish_boundaries=boundaries,
                        private_labels_alive_with_result=False)
                if raster:
                    evidence['independent_native_raster_sha256'] = independent_raster(result)
                return output, evidence
            finally:
                if result is not None:
                    close_plan(result, self.source)


def parity_cases(before, after):
    helper_hashes, public_hashes, raster_hashes = [], [], []
    timed_observations = []
    # Full old scorer outputs, including rank/rounding, against compact records.
    for seed in range(6):
        rng = np.random.default_rng(250100 + seed)
        for shape in ((1, 1), (11, 17), (18, 7)):
            pm = pm_from_index(rng.integers(-1, 4, shape, dtype=np.int16),
                edges=rng.random(shape), protected=rng.random(shape) > .6,
                importance=rng.random(shape))
            simulated = rng.integers(-1, 4, shape, dtype=np.int16)
            counts = rng.integers(0, 5, shape, dtype=np.uint16)
            for limit in (1, 64):
                outputs = []
                for graph in (before, after):
                    engine, strokes = graph['PixelAccuracyEngine'], graph['PixelStrokeEngine']
                    result = engine.SimulationResult(simulated, counts, counts > 0,
                                                     np.zeros(shape, np.uint8), {})
                    with linked_graph(graph):
                        if graph is before:
                            output = engine.region_accuracy_scores(pm, result, max_regions=limit)
                        else:
                            with PixelRegionTopology.PixelRegionTopology(pm) as owner:
                                components, labels, _ = strokes.connected_components(pm, include_vertical_runs=False)
                                if not owner.offer(pm, components, labels):
                                    raise AssertionError('Historical helper fixture failed to offer topology.')
                                output = engine.region_accuracy_scores(pm, result, max_regions=limit,
                                                                         _region_topology=owner)
                    outputs.append(comparable(output))
                if outputs[0] != outputs[1]:
                    raise AssertionError('Complete historical regional score changed.')
                helper_hashes.append(digest(outputs[1]))

    with ExitStack() as stack:
        sources = (stack.enter_context(closing(checker_source((32, 24), margin=4))),
                   stack.enter_context(closing(block_source((64, 48)))),
                   stack.enter_context(closing(alpha_source((48, 40)))))
        cases = []
        for source in sources:
            for workers in (1, 2):
                for brush in (1, 4):
                    for skip in (False, True):
                        cases.append((source, public_options(subject_focus='Off', brush_px=brush,
                            skip_white=skip, cpu_workers=str(workers), cpu_workers_resolved=workers)))
        for source in sources[:2]:
            for subject in ('Subject first', 'Subject only'):
                for workers in (1, 2):
                    cases.append((source, public_options(subject_focus=subject,
                        subject_region=(.2, .2, .75, .8), cpu_workers=str(workers), cpu_workers_resolved=workers)))
        for workers in (1, 2):
            for skip in (False, True):
                cases.append((sources[0], public_options(lines=False, subject_focus='Off',
                    skip_white=skip, cpu_workers=str(workers), cpu_workers_resolved=workers)))
        for source, settings in cases:
            input_before = fingerprint(source)
            operation = Operation('historical_public', source, settings)
            raster = settings['brush_px'] == 1
            expected, old_evidence = operation.run(before, raster=raster)
            actual, new_evidence = operation.run(after, raster=raster)
            if expected != actual or old_evidence != new_evidence or fingerprint(source) != input_before:
                raise AssertionError('Complete historical public plan/native raster/input parity failed: '
                    + first_difference(expected, actual) + f'; options={settings}')
            public_hashes.append(digest(actual))
            if raster:
                raster_hashes.append(new_evidence['independent_native_raster_sha256'])
        source = stack.enter_context(closing(timed_source()))
        for workers in (1, 2):
            operation = Operation('historical_active_timer', source,
                timed_options(cpu_workers=str(workers), cpu_workers_resolved=workers),
                area=(100, 100), timed_case=True)
            input_before = fingerprint(source)
            with operation.fixture_scope():
                expected, old_work = operation.run(before, observe=True)
                actual, new_work = operation.run(after, observe=True)
            if expected != actual or fingerprint(source) != input_before:
                raise AssertionError('Active-budget complete historical parity failed: '
                                     + first_difference(expected, actual))
            if (old_work['connected_component_calls'], new_work['connected_component_calls']) != (2, 1):
                raise AssertionError('Active-budget topology must preserve the actual 2 to 1 reduction.')
            if old_work['progressive_time_budget'] != new_work['progressive_time_budget']:
                raise AssertionError('Active-budget admission/metadata changed across the topology handoff.')
            timed_observations.append(dict(workers=workers, before_work=old_work, after_work=new_work))
            public_hashes.append(digest(actual))
    return dict(complete_region_score_pairs=len(helper_hashes), complete_public_plan_pairs=len(public_hashes),
        independent_native_raster_pairs=len(raster_hashes), region_score_sha256=digest(helper_hashes),
        complete_public_output_sha256=digest(public_hashes), independent_native_raster_sha256=digest(raster_hashes),
        active_timed_public_pairs=len(timed_observations), active_timed_work=timed_observations)


def workloads(stack):
    flat = Image.new('RGB', (384, 256), 'white')
    ImageDraw.Draw(flat).rectangle((8, 8, 375, 247), fill='black')
    specs = (
        ('public_checker64', checker_source((64, 64), margin=4), {}),
        ('public_checker128', checker_source((128, 128), margin=4), {}),
        ('public_checker256_geometry', checker_source((256, 192), margin=4), {'adaptive_hybrid_cost': 'Off'}),
        ('public_blocks384', block_source((384, 256)), {}),
        ('public_rgba128', alpha_source((128, 96)), {}),
        ('public_flat384', flat, {}),
        ('public_empty128', Image.new('RGBA', (128, 96), (19, 31, 77, 0)), {}),
        ('public_dots128_control', checker_source((128, 128), margin=4), {'lines': False}),
        ('public_subject_first_control', block_source(),
         {'subject_focus': 'Subject first', 'subject_region': (.2, .2, .75, .8)}),
        ('public_subject_only_control', block_source(),
         {'subject_focus': 'Subject only', 'subject_region': (.2, .2, .75, .8)}),
    )
    result = []
    for name, source, changes in specs:
        stack.callback(source.close)
        settings = public_options(subject_focus='Off')
        settings.update(changes)
        result.append(Operation(name, source, settings))
    source = stack.enter_context(closing(timed_source()))
    result.append(Operation('public_existing_asset_active_timer', source, timed_options(),
                            area=(100, 100), timed_case=True))
    return result


def measure(revision=BASELINE, repeats=6, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even number of balanced AB/BA pairs, at least two.')
    after = current_graph()
    before, historical_hashes = historical_graph(revision)
    source_before = source_hashes()
    report = dict(baseline=revision, historical_module_sha256=historical_hashes,
        python=sys.version.split()[0], platform=platform.platform(), numpy=np.__version__, pillow=pillow_version,
        verify_only=verify_only, repeats=0 if verify_only else repeats, source_sha256=source_before,
        method=('Complete historical parity, one untimed warm pair and separate work observations; no elapsed or traced probes.'
            if verify_only else f'Complete historical parity, one warm pair, {repeats} balanced AB/BA pairs, then separate before/after tracemalloc probes.'),
        historical_linkage='Complete historical DrawBot, SubjectFocus, PixelStrokeEngine and PixelAccuracyEngine are linked together under public import names. Shared dependencies are identical between both sides.',
        timing_scope='Entire actual public make_plan, including compact record construction and semantic target validation. Source construction, linkage, calibration, fingerprints, raster verification and image cleanup are outside the timer.',
        allocation_scope='Separate same-call Python/NumPy tracemalloc probes including returned results; prepared borrowed input images excluded. Not total RSS or every native Pillow allocation.',
        retention_tradeoff='Existing first labels previously died before scoring. Reuse may retain up to 8MiB labels plus 65536*56 bytes of scalar records until the regional score; full planner peaks can increase. Full Component graphs are not retained.',
        environment=dict(gpu_mode='CPU', available_ram_mb=8192, real_temporary_palette_file=True,
                         active_timer_missing_speed_history=True),
        active_timer_asset=dict(path=TIMED_ASSET.relative_to(ROOT).as_posix(), crop=TIMED_CROP,
            sha256=hashlib.sha256(TIMED_ASSET.read_bytes()).hexdigest(), area=(100, 100), brush_px=3,
            requested_budget='30 sec', palette='18 shipped DEFAULT_COLORS, actually calibrated'),
        comparison_exclusions=[list(path) for path in sorted(COMPARISON_EXCLUSIONS)], workloads=[])
    with controlled_environment(before, after), ExitStack() as stack:
        report['parity'] = parity_cases(before, after)
        for operation in workloads(stack):
            with operation.fixture_scope():
                print('Verifying ' + operation.name, flush=True)
                input_before = fingerprint(operation.source)
                raster = not operation.timed_case
                expected, old_raster = operation.run(before, raster=raster)
                actual, new_raster = operation.run(after, raster=raster)
                if actual != expected or new_raster != old_raster:
                    raise AssertionError('Warm complete public parity failed: ' + operation.name)
                row = dict(name=operation.name, exact_output_parity=True, output_sha256=digest(actual),
                           independent_brush_one_raster=raster, **new_raster)
                for label, graph in (('before', before), ('after', after)):
                    output, work = operation.run(graph, observe=True)
                    if output != expected:
                        raise AssertionError('Counted complete public parity failed: ' + operation.name)
                    row[label + '_work'] = work
                if not verify_only:
                    samples = {'before': [], 'after': []}
                    row['pair_order'] = []
                    for pair in range(repeats):
                        order = ('before', 'after') if pair % 2 == 0 else ('after', 'before')
                        row['pair_order'].append(list(order))
                        for label in order:
                            gc.collect()
                            output, evidence = operation.run(before if label == 'before' else after, elapsed=True)
                            if output != expected:
                                raise AssertionError('Timed complete parity failed: ' + operation.name)
                            samples[label].append(evidence['milliseconds'])
                    for label, graph in (('before', before), ('after', after)):
                        output, evidence = operation.run(graph, trace=True)
                        if output != expected:
                            raise AssertionError('Traced complete parity failed: ' + operation.name)
                        row[label + '_samples_ms'] = samples[label]
                        row[label + '_median_ms'] = statistics.median(samples[label])
                        row[label + '_allocation'] = evidence
                    row['median_change_percent'] = (row['after_median_ms'] / row['before_median_ms'] - 1) * 100
                    row['faster_pairs'] = sum(new < old for old, new in zip(samples['before'], samples['after']))
                    print(json.dumps({key: row[key] for key in ('name', 'before_median_ms', 'after_median_ms',
                                                              'median_change_percent', 'faster_pairs')}), flush=True)
                if fingerprint(operation.source) != input_before:
                    raise AssertionError('A borrowed public source was modified: ' + operation.name)
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
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch26-topology-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.revision, args.repeats, args.verify_only)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(str(args.output), flush=True)
