"""Full Sketch Fill caller parity and isolated presentation-work measurements.

No final timing run is valid without a coordinated quiet CPU/source window.
Verify-only performs full historical/public/raster comparisons, without timers
or allocation tracing. Historical artifacts are never modified by this script.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
import copy
from dataclasses import asdict, is_dataclass
import gc
import hashlib
import importlib
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
import tracemalloc
import types
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, __version__ as pillow_version

import AccuracyEvaluator
import AutoSketchBudget
import DrawBot
import EndToEndAutoTuner
import FillOptimizer
import PixelAccuracyEngine
import PreviewDiagnostics
import PreviewLayers
from test_drawbot import NoWait
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch16_selector import PaletteInkMouse, ORIGIN
from test_v148_rendering_batch27_sketch_finalization import (
    PALETTE, close_plan, is_open, plan_images, planner_fixture, source_image)


ROOT = Path(__file__).resolve().parent
BASELINE = '8e0a0e4c61ca0742dfb7857649103477cd307516'
GRAPH_NAMES = ('PixelData', 'SketchFillRenderer', 'DrawBot')
EVIDENCE_ROOT = None


def comparable(value, path=()):
    if is_dataclass(value):
        return comparable(asdict(value), path)
    if isinstance(value, Image.Image):
        return {'image': {'mode': value.mode, 'size': list(value.size),
            'sha256': hashlib.sha256(value.tobytes()).hexdigest(),
            'info': comparable(dict(value.info), path)}}
    if isinstance(value, np.ndarray):
        return {'array': {'shape': list(value.shape), 'dtype': str(value.dtype),
            'sha256': hashlib.sha256(value.tobytes()).hexdigest()}}
    if isinstance(value, dict):
        return {key if isinstance(key, str) else repr((type(key).__name__, key)):
                comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (list, tuple)):
        return [comparable(item, path) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, bytes):
        return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f'Unaccounted full-plan value at {path}: {type(value).__name__}')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def first_difference(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        if before.keys() != after.keys():
            return f'{path}: keys {before.keys() ^ after.keys()}'
        for key in before:
            if before[key] != after[key]:
                return first_difference(before[key], after[key], (*path, key))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return f'{path}: lengths {len(before)} != {len(after)}'
        for index, (old, new) in enumerate(zip(before, after)):
            if old != new:
                return first_difference(old, new, (*path, index))
    return f'{path}: {before!r} != {after!r}'


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def current_graph():
    return {name: importlib.import_module(name) for name in GRAPH_NAMES}


def historical_graph(revision, *, shared_pixel_data=None):
    """Compile complete modules under matching public import names.

    The full historical graph includes old PixelData. The isolated presentation
    graph instead holds today's complete PixelData module on BOTH timed sides,
    so the separately reviewed monochrome/white changes are not credited here.
    """
    current = current_graph()
    sources = {name: subprocess.check_output(['git', 'show', f'{revision}:{name}.py'], cwd=ROOT)
               for name in GRAPH_NAMES}
    modules = {}
    for name in GRAPH_NAMES:
        if name == 'PixelData' and shared_pixel_data is not None:
            modules[name] = shared_pixel_data
            continue
        alias = '_sketch_history_' + revision[:12] + ('_shared_' if shared_pixel_data else '_full_') + name
        module = types.ModuleType(alias)
        module.__file__ = str(ROOT / (name + '.py'))
        module.__package__ = ''
        sys.modules[alias] = module
        modules[name] = module
    with patch.dict(sys.modules, modules):
        for name in GRAPH_NAMES:
            if name == 'PixelData' and shared_pixel_data is not None:
                continue
            exec(compile(sources[name], modules[name].__file__, 'exec'), modules[name].__dict__)
    return modules, {name: hashlib.sha256(source).hexdigest() for name, source in sources.items()}


@contextmanager
def linked(graph):
    with patch.dict(sys.modules, graph), \
            patch.object(AutoSketchBudget, 'monochrome_strokes', graph['PixelData'].monochrome_strokes), \
            patch.object(FillOptimizer, 'closest_color', graph['PixelData'].closest_color):
        yield


@contextmanager
def observed_work(controller):
    calls = Counter(); stage = []; inner = []; refinements = []
    actual_finish = controller.finish_plan
    actual_refine = PixelAccuracyEngine.refine_with_corrections

    def count(label, function):
        def call(*args, **kwargs):
            calls[(stage[-1] if stage else 'planning') + ':' + label] += 1
            try:
                return function(*args, **kwargs)
            finally:
                args = (); kwargs = {}
        return call

    def finish(image, fitted, groups, options, cancelled=lambda: False):
        kind = 'final' if options.get('sketch_fill_active') else 'inner'
        calls['finish:' + kind] += 1
        if kind == 'final':
            for row in inner:
                row['open_images_at_outer_finish'] = sum(
                    ref() is not None and is_open(ref()) for ref in row['image_refs'])
        stage.append(kind)
        result = None
        try:
            result = actual_finish(image, fitted, groups, options, cancelled)
            if kind == 'inner':
                geometry = {key: result[key] for key in
                    ('image', 'fitted', 'groups', 'execution_groups', 'execution_sequence',
                     'count', 'colors', 'color_selectors', 'path_stats')}
                inner.append({'image_refs': [weakref.ref(v) for v in plan_images(result)],
                    'geometry_sha256': digest(comparable(geometry)),
                    'pixel_time_budget': comparable((result['options'].get('pixel_accuracy_meta') or {}).get('progressive_time_budget')),
                    'target_counts': {key: result['path_stats'].get(key) for key in
                        ('target_before_paths', 'target_after_paths', 'target_skipped_paths')},
                    'source_accuracy_present': 'adaptive_accuracy_meta' in result['options']})
            return result
        finally:
            stage.pop()
            image = groups = options = result = None

    def refine(*args, **kwargs):
        result = None
        try:
            result = actual_refine(*args, **kwargs)
            refinements.append(digest(comparable(result['metadata'])))
            return result
        finally:
            args = (); kwargs = {}; result = None

    with ExitStack() as stack:
        stack.enter_context(patch.object(controller, 'finish_plan', new=finish))
        stack.enter_context(patch.object(PixelAccuracyEngine, 'refine_with_corrections', new=refine))
        for module, name, label in (
            (AccuracyEvaluator, 'evaluate_preview', 'source_accuracy'),
            (PreviewLayers, 'build_auxiliary_previews', 'auxiliary'),
            (PreviewDiagnostics, 'render_quantized_target', 'quantized_target'),
            (PreviewDiagnostics, 'build_preview_diagnostics', 'diagnostics'),
            (controller, 'build_preview_safety_plan', 'safety'),
            (controller, 'optimize_execution_groups', 'optimizer'),
            (EndToEndAutoTuner, 'evaluate_plan_acceptance', 'tuner_acceptance'),
            (EndToEndAutoTuner, 'propose_rescue_options', 'tuner_rescue'),
        ):
            stack.enter_context(patch.object(module, name, new=count(label, getattr(module, name))))
        yield calls, inner, refinements


def native_ink(controller, source, plan, evidence_prefix=None):
    """Actual executor, independent physical ink from clicked native swatches."""
    if tuple(plan['fitted']) != tuple(source.size):
        raise AssertionError('Native oracle requires identity-sized fixture placement.')
    with closing(Image.new('RGB', source.size, 'white')) as surface, ExitStack() as stack:
        positions = [(-400 + 10*i, -100) for i in range(len(PALETTE))]
        mouse = PaletteInkMouse(surface, positions, PALETTE, int(plan['options']['brush_px']))
        stack.callback(mouse.close)
        stack.enter_context(patch.object(controller, 'save_runtime_safety_report',
            side_effect=lambda state: state.as_dict()))
        for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            stack.enter_context(patch(name, return_value={}))
        import threading
        before_execution = comparable(plan) if evidence_prefix is not None else None
        controller.execute_plan(plan, (*ORIGIN, *source.size), positions, mouse,
                                NoWait(), threading.Event(), mouse.report, clock=lambda: 0)
        if mouse.held:
            raise AssertionError('The native oracle retained a pressed button.')
        difference = int(np.count_nonzero(np.asarray(surface) != np.asarray(plan['preview'])))
        if difference and evidence_prefix is not None:
            evidence_prefix.parent.mkdir(parents=True, exist_ok=True)
            source.save(str(evidence_prefix) + '-source.png')
            surface.save(str(evidence_prefix) + '-delivered.png')
            plan['preview'].save(str(evidence_prefix) + '-preview.png')
            raw = dict(source=comparable(source), plan_before_execution=before_execution,
                delivered=comparable(surface), preview=comparable(plan['preview']),
                different_rgb_values=difference, palette=PALETTE, origin=ORIGIN,
                selected_palette_actions=mouse.selections, delivered_ink_colors=mouse.ink_colors,
                verifications=mouse.verifications, runtime_path_counts=plan['options'].get('runtime_path_counts'),
                model='Real execute_plan sends native coordinates into PaletteInkMouse. Each cursor segment is a Pillow centerline expanded by a fixed square physical brush. This is an emulator, not a physical Paint capture.')
            Path(str(evidence_prefix) + '.json').write_text(json.dumps(raw, indent=2, sort_keys=True)+'\n')
        return dict(raster_sha256=hashlib.sha256(surface.tobytes()).hexdigest(),
                    native_paths=len(mouse.ink_colors), color_verifications=len(mouse.verifications),
                    runtime_path_counts=plan['options'].get('runtime_path_counts'),
                    ink_color_sequence_sha256=digest(mouse.ink_colors),
                    palette_selections_sha256=digest(mouse.selections),
                    preview_sha256=hashlib.sha256(plan['preview'].tobytes()).hexdigest(),
                    preview_equal_to_emulated_native_ink=difference == 0,
                    differing_preview_rgb_values=difference)


class Operation:
    def __init__(self, name, source, settings, *, active=False, raster=False):
        self.name, self.source, self.settings = name, source, settings
        self.active, self.raster = active, raster

    def run(self, graph, *, elapsed=False, trace=False, observe=False, raster=False):
        if trace and tracemalloc.is_tracing():
            raise RuntimeError('An external allocation trace is already active.')
        controller = graph['DrawBot']
        source, area, settings = self.source, tuple(self.source.size), copy.deepcopy(self.settings)
        plan = None; evidence = {}
        if trace:
            gc.collect()
        with linked(graph), ExitStack() as stack:
            if observe:
                calls, inner, refinements = stack.enter_context(observed_work(controller))
            try:
                if trace:
                    tracemalloc.start()
                try:
                    started = time.perf_counter() if elapsed else None
                    plan = controller.make_plan(source, area, settings)
                    if elapsed:
                        evidence['milliseconds'] = (time.perf_counter() - started) * 1000
                    if trace:
                        retained, peak = tracemalloc.get_traced_memory()
                        evidence.update(peak_python_bytes=peak, retained_with_result_bytes=retained)
                finally:
                    if trace:
                        tracemalloc.stop()
                output = comparable(plan)
                if observe:
                    rows = [{key: value for key, value in row.items() if key != 'image_refs'} for row in inner]
                    evidence.update(calls=dict(calls), inner=rows, pixel_refinement_sha256=refinements,
                                    final_paths=plan['count'])
                    if self.active:
                        if settings['draw_quality'] == 'Balanced':
                            target = rows[0]['target_counts']
                            if not target['target_skipped_paths'] or target['target_after_paths'] > 50:
                                raise AssertionError('The active fixture must actually apply its explicit target cap.')
                        else:
                            budget = rows[0]['pixel_time_budget']
                            if not budget['active'] or budget['paths_omitted'] <= 0:
                                raise AssertionError('The actual Pixel timer must omit work.')
                if raster:
                    prefix = (EVIDENCE_ROOT/re.sub(r'[^A-Za-z0-9_-]', '_', self.name)/controller.__name__
                              if EVIDENCE_ROOT is not None else None)
                    evidence['native_ink'] = native_ink(controller, source, plan, prefix)
                return output, evidence
            finally:
                close_plan(plan)


def active_changes():
    return dict(time_budget_mode='30 sec', target_stroke_count='Custom', target_stroke_custom='50',
                adaptive_detail='Off', background_simplification='Off', adaptive_deadline_renderer=True)


def verify_public(full_before, isolated_before, after, stack):
    hashes = []; rasters = []; work = []
    # Each actual UI/calibration fixture encloses all three complete public
    # callers. File-backed history paths remain part of the full comparison.
    for quality in ('Balanced', 'Pixel Accurate'):
        for kind in ('rgb', 'rgba'):
            for brush in (1, 4):
                for preview in (False, True):
                    with planner_fixture(quality, brush, kind) as (source, options):
                        options = dict(options, _preview_plan=preview)
                        name = f'{quality}/{kind}/brush{brush}/preview{preview}'
                        operation = Operation(name, source, options)
                        results = []
                        for graph in (full_before, isolated_before, after):
                            results.append(operation.run(graph, observe=True, raster=not preview))
                        reference = results[0][0]
                        if any(result[0] != reference for result in results[1:]):
                            raise AssertionError(name + ': ' + first_difference(reference, results[-1][0]))
                        if any(result[1]['pixel_refinement_sha256'] != results[0][1]['pixel_refinement_sha256']
                               for result in results[1:]):
                            raise AssertionError('Pixel correction choices changed: ' + name)
                        if any([row['geometry_sha256'] for row in result[1]['inner']]
                               != [row['geometry_sha256'] for row in results[0][1]['inner']] for result in results[1:]):
                            raise AssertionError('Finalized colour geometry changed: ' + name)
                        hashes.append(digest(reference))
                        work.append(dict(name=name, before=results[0][1], after=results[2][1]))
                        if not preview:
                            if any(result[1]['native_ink'] != results[0][1]['native_ink'] for result in results[1:]):
                                raise AssertionError('Native raster/execution count changed: ' + name)
                            rasters.append(results[0][1]['native_ink'])
    controls = (
        ('active_balanced_cap', 'Balanced', 1, 'islands', 'active'),
        ('active_pixel_budget', 'Pixel Accurate', 1, 'islands', 'active'),
        ('real_tuner_inner_rescue', 'Pixel Accurate', 4, 'rgb', 'tuner'),
        ('real_tuner_outer_rescue', 'Balanced', 1, 'rgb', 'outer_tuner'),
        ('nested_hybrid_full_control', 'Balanced', 1, 'rgb', 'hybrid'),
        ('standalone_full_control', 'Balanced', 1, 'rgba', 'standalone'),
    )
    for name, quality, brush, kind, mode in controls:
        with planner_fixture(quality, brush, kind,
                ui_changes=active_changes() if mode == 'active' else None) as (source, options):
            if mode in ('tuner', 'outer_tuner'):
                options = EndToEndAutoTuner.tune_options(source, dict(options, render_preset='Auto'))
                options.update(render_style='Sketch + Auto Fill', draw_quality=quality)
                if mode == 'outer_tuner':
                    options.update(extra_fast=False, extra_fast_v2=False)
            elif mode == 'hybrid':
                options = dict(options, extra_fast=True, extra_fast_v2=True)
            elif mode == 'standalone':
                options = dict(options, render_style='Standard / pixel')
            operation = Operation(name, source, options, active=mode == 'active')
            results = [operation.run(graph, observe=True) for graph in (full_before, isolated_before, after)]
            if any(result[0] != results[0][0] for result in results[1:]):
                raise AssertionError(name + ': ' + first_difference(results[0][0], results[-1][0]))
            hashes.append(digest(results[0][0]))
            work.append(dict(name=name, before=results[0][1], after=results[2][1]))
    return dict(complete_public_three_graph_cases=len(hashes),
        complete_historical_public_pairs=len(hashes), isolated_public_pairs=len(hashes),
        independent_native_three_graph_cases=len(rasters), complete_output_sha256=digest(hashes),
        independent_native_ink_sha256=digest(rasters), observed_cases=work)


def workload_specs():
    return (
        ('public_balanced_rgb320', 'Balanced', 1, 'rgb', (320, 256), 'normal'),
        ('public_balanced_rgba384', 'Balanced', 3, 'rgba', (384, 288), 'normal'),
        ('public_pixel_rgb192', 'Pixel Accurate', 4, 'rgb', (192, 160), 'normal'),
        ('public_pixel_rgba192', 'Pixel Accurate', 3, 'rgba', (192, 144), 'normal'),
        ('public_balanced_full_preview256', 'Balanced', 1, 'rgb', (256, 192), 'preview'),
        ('public_active_cap96', 'Balanced', 1, 'islands', None, 'active'),
        ('public_active_tuner40_control', 'Pixel Accurate', 4, 'rgb', None, 'tuner'),
        ('public_standalone192_control', 'Balanced', 1, 'rgba', (192, 144), 'standalone'),
    )


def measure(revision=BASELINE, repeats=6, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even number of balanced AB/BA pairs, at least two.')
    after = current_graph()
    full_before, historical_hashes = historical_graph(revision)
    before, isolated_hashes = historical_graph(revision, shared_pixel_data=after['PixelData'])
    source_before = source_hashes()
    report = dict(baseline=revision, historical_module_sha256=historical_hashes,
        isolated_historical_module_sha256=isolated_hashes,
        isolated_shared_pixel_data_sha256=source_before['PixelData.py'],
        python=sys.version.split()[0], platform=platform.platform(), numpy=np.__version__, pillow=pillow_version,
        source_sha256=source_before, verify_only=verify_only, repeats=0 if verify_only else repeats,
        method=('Complete historical three-graph output/native parity and separate untimed work observations; no elapsed or allocation probes.'
                if verify_only else f'Complete historical parity, one warm pair, {repeats} balanced AB/BA pairs, then separate before/after tracemalloc probes.'),
        historical_linkage='Full published DrawBot, SketchFillRenderer and PixelData are linked together, including AutoSketchBudget.monochrome_strokes and FillOptimizer.closest_color aliases. Every public case is also compared with the isolated baseline and current graph.',
        causal_timing_linkage='Timed before uses complete historical DrawBot and SketchFillRenderer with the SAME CURRENT PixelData as after. This holds the separately reviewed monochrome lifetime and CPU white-mask completions constant. All other dependencies are shared; real UI options are prepared identically outside timing.',
        timing_scope='Only actual public make_plan, including required geometry/safety, Pixel correction selection, internal cleanup, active tuner/rescue and outer diagnostics. Source/settings construction, import linkage, fingerprints, calibration, raster replay and caller-owned result cleanup occur outside timing.',
        allocation_scope='Separate same-call tracemalloc peak and retained-with-result including Python/NumPy allocations, excluding prepared borrowed sources. Not every native Pillow allocation and not total RSS.',
        limits='CPU-only real public planners. Native ink verification compares exact delivered rasters/counts/colour actions across all three graphs using a controlled mouse/Pillow surface, never physical Paint input. Some RGBA fixtures already differ between the historical preview and emulated native ink; these exact pre-existing deltas are retained in every graph and reported rather than asserted correct. The older strict native goldens remain unchanged. Active tuner and nested AdaptiveHybrid retain full inner presentation. Ordinary inner PreviewSafety and physical base simulation are deliberately retained.',
        comparison_exclusions=[list(path) for path in sorted(VOLATILE_PATHS)],
        environment=dict(gpu_mode='CPU', available_ram_mb=8192, real_temporary_palette_file=True,
                         palette=PALETTE, native_input=False), workloads=[])
    with ExitStack() as stack:
        for graph in (full_before, before, after):
            stack.enter_context(patch.object(graph['DrawBot'], 'custom_rgb_available', return_value=False))
            stack.enter_context(patch.object(graph['DrawBot'], 'log_event', new=lambda *_a, **_k: None))
        report['parity'] = verify_public(full_before, before, after, stack)
        for name, quality, brush, kind, size, mode in workload_specs():
            with planner_fixture(quality, brush, kind,
                    ui_changes=active_changes() if mode == 'active' else None) as (base_source, settings), ExitStack() as fixture:
                source = base_source if size is None else fixture.enter_context(closing(base_source.resize(size, Image.Resampling.NEAREST)))
                if mode == 'tuner':
                    settings = EndToEndAutoTuner.tune_options(source, dict(settings, render_preset='Auto'))
                    settings.update(render_style='Sketch + Auto Fill', draw_quality=quality)
                elif mode == 'standalone':
                    settings = dict(settings, render_style='Standard / pixel')
                elif mode == 'preview':
                    settings = dict(settings, _preview_plan=True, _full_detail_preview=True)
                operation = Operation(name, source, settings, active=mode == 'active')
                print('Verifying ' + name, flush=True)
                input_before = comparable(source)
                full_expected, _ = operation.run(full_before)
                expected, _ = operation.run(before)
                actual, _ = operation.run(after)
                if full_expected != expected or actual != expected:
                    raise AssertionError(name + ': ' + first_difference(full_expected, actual))
                row = dict(name=name, source_size=source.size, settings=comparable(settings),
                    exact_full_historical_output_parity=True, exact_isolated_output_parity=True,
                    output_sha256=digest(actual))
                for label, graph in (('before', before), ('after', after)):
                    output, work = operation.run(graph, observe=True)
                    if output != expected:
                        raise AssertionError('Observed output parity failed: ' + name)
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
                                raise AssertionError('Timed full output parity failed: ' + name)
                            samples[label].append(evidence['milliseconds'])
                    for label, graph in (('before', before), ('after', after)):
                        output, allocation = operation.run(graph, trace=True)
                        if output != expected:
                            raise AssertionError('Traced full output parity failed: ' + name)
                        row[label + '_samples_ms'] = samples[label]
                        row[label + '_median_ms'] = statistics.median(samples[label])
                        row[label + '_allocation'] = allocation
                    row['median_change_percent'] = (row['after_median_ms']/row['before_median_ms']-1)*100
                    row['faster_pairs'] = sum(new < old for old,new in zip(samples['before'],samples['after']))
                    print(json.dumps({key:row[key] for key in ('name','before_median_ms','after_median_ms',
                        'median_change_percent','faster_pairs')}), flush=True)
                if comparable(source) != input_before:
                    raise AssertionError('Borrowed input mutated: ' + name)
                report['workloads'].append(row)
    report['source_sha256_after'] = source_hashes()
    report['sources_unchanged'] = report['source_sha256_after'] == source_before
    if not report['sources_unchanged']:
        raise AssertionError('Source changed during the public-plan comparison.')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--evidence-dir', type=Path, help='Optional scratch directory for pre-existing native/preview-difference PNGs and full raw plans.')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch27-sketch-finalization-benchmarks.json')
    args = parser.parse_args()
    EVIDENCE_ROOT = args.evidence_dir
    result = measure(args.revision, args.repeats, args.verify_only)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')
    print(str(args.output), flush=True)
