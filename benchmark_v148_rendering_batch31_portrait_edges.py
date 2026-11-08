"""Whole-module Portrait contour parity and separate CPU/allocation observations.

Run only in a coordinated quiet source/CPU window. The before side is the whole
published PortraitPlanner; the current controller and other dependencies are
shared. A verify-only run performs the same parity/work checks without timing or
tracing. An explicit, previously unused output file is always required.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
import copy
from dataclasses import asdict, is_dataclass
import gc
import hashlib
import heapq
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import tracemalloc
import types
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
BASELINE = 'e49e2535c5f8edea80e47824fe56cae58781b971'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def sources():
    return {path.name: sha(path.read_bytes()) for path in sorted(ROOT.glob('*.py'))}


def comparable(value, path=()):
    """Compare every result field except the seven existing profiler paths."""
    if is_dataclass(value):
        return comparable(asdict(value), path)
    if isinstance(value, Image.Image):
        return dict(image=dict(mode=value.mode, size=list(value.size), sha256=sha(value.tobytes()),
            info=comparable(dict(value.info), path), exif_sha256=sha(value.getexif().tobytes())))
    if isinstance(value, np.ndarray):
        return dict(array=dict(dtype=str(value.dtype), shape=list(value.shape), sha256=sha(value.tobytes())))
    if isinstance(value, dict):
        return {key if isinstance(key, str) else repr((type(key).__name__, key)):
            comparable(item, (*path, key)) for key, item in value.items()
            if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (list, tuple)):
        return [comparable(item, path) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, bytes):
        return dict(bytes=len(value), sha256=sha(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(('Unaccounted complete result', path, type(value).__name__))


def first_difference(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        if before.keys() != after.keys():
            return repr((path, 'keys', before.keys() ^ after.keys()))
        for key in before:
            if before[key] != after[key]:
                return first_difference(before[key], after[key], (*path, key))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return repr((path, 'lengths', len(before), len(after)))
        for index, (left, right) in enumerate(zip(before, after)):
            if left != right:
                return first_difference(left, right, (*path, index))
    return repr((path, before, after))[:1200]


def require_equal(before, after, name):
    if before != after:
        raise AssertionError(name + ': ' + first_difference(before, after))


@contextmanager
def linked(module):
    # These are the only production from-import aliases of PortraitPlanner.
    # Binding occurs before every timer/tracer, identically on both sides.
    with patch.dict(sys.modules, {'PortraitPlanner': module}), \
            patch.object(DrawBot, 'prepare_portrait_image', new=module.prepare_portrait_image), \
            patch.object(DrawBot, 'portrait_strokes', new=module.portrait_strokes):
        yield


class WorkObservation:
    """Read real return/C-call frames; never replace a numeric helper or sorter."""
    def __init__(self, module):
        self.edge_code = module._edge_strokes.__code__
        self.prepare_code = module.prepare_portrait_image.__code__
        self.calls = []
        self.finishes = []
        self.preparations = []
        self.active = {}

    def observe(self, frame, event, result):
        if frame.f_code is self.edge_code:
            if event == 'call':
                row = dict(gray_size=list(frame.f_locals['gray'].size),
                    requested_limit=frame.f_locals.get('max_strokes'),
                    caller_edge_budget=frame.f_back.f_locals.get('edge_budget'),
                    gpu_vram=frame.f_locals['gpu_vram'], gpu_performance=frame.f_locals['gpu_performance'],
                    full_sort_inputs=[], heap_calls=[])
                self.calls.append(row)
                self.active[id(frame)] = row
            elif event == 'c_call' and getattr(result, '__name__', None) == 'sort':
                self.active[id(frame)]['full_sort_inputs'].append(len(result.__self__))
            elif event == 'return':
                row = self.active.pop(id(frame))
                if isinstance(result, list):
                    occupied = frame.f_locals['occupied']
                    row.update(occupied=len(occupied), returned=len(result),
                        duplicate_score_winners=len(occupied) - len({item[0] for item in occupied.values()}))
        elif frame.f_code is heapq.nlargest.__code__ and frame.f_back.f_code is self.edge_code:
            row = self.active[id(frame.f_back)]
            if event == 'call':
                row['heap_calls'].append(dict(requested=frame.f_locals['n'],
                    input=len(frame.f_locals['iterable']), final_sort_inputs=[]))
            elif event == 'c_call' and getattr(result, '__name__', None) == 'sort':
                row['heap_calls'][-1]['final_sort_inputs'].append(len(result.__self__))
            elif event == 'return' and isinstance(result, list):
                row['heap_calls'][-1]['returned'] = len(result)
        elif frame.f_code is self.prepare_code and event == 'return' and isinstance(result, tuple):
            self.preparations.append(dict(arguments=comparable({name: frame.f_locals[name] for name in
                ('area', 'detail', 'contrast', 'subject_focus', 'draw_quality', 'gpu_mode',
                 'gpu_vram', 'gpu_performance', 'preview_detail_mode')}),
                output=comparable(dict(gray=result[0], fitted=result[1],
                    acceleration_meta=frame.f_locals['acceleration_meta']))))
        elif frame.f_code is DrawBot.finish_plan.__code__ and event == 'return' and isinstance(result, dict):
            self.finishes.append(dict(count=result['count'], estimate=result['estimate'],
                portrait_stats=copy.deepcopy(result['options'].get('portrait_stats'))))

    @contextmanager
    def installed(self):
        previous = sys.getprofile()
        if previous is not None:
            raise RuntimeError('An external profiler is already active.')
        try:
            sys.setprofile(self.observe)
            yield
        finally:
            sys.setprofile(previous)
            self.active.clear()

    def result(self):
        heaps = [item for row in self.calls for item in row['heap_calls']]
        return dict(calls=self.calls, finishes=self.finishes, preparations=self.preparations, totals=dict(
            edge_calls=len(self.calls), occupied=sum(row['occupied'] for row in self.calls),
            returned=sum(row['returned'] for row in self.calls),
            full_sort_input=sum(sum(row['full_sort_inputs']) for row in self.calls),
            heap_calls=len(heaps), heap_input=sum(row['input'] for row in heaps),
            heap_returned=sum(row['returned'] for row in heaps),
            heap_final_sort_input=sum(sum(row['final_sort_inputs']) for row in heaps)))


class Operation:
    def __init__(self, name, image, *, limit=None, quality='High likeness', focus=True,
                 settings=None, area=None, helper_settings=None, acceleration_meta=None,
                 expected_preparation=None):
        self.name, self.image, self.limit = name, image, limit
        self.quality, self.focus, self.settings, self.area = quality, focus, settings, area
        self.helper_settings = helper_settings or {}
        self.acceleration_meta = acceleration_meta or {}
        self.expected_preparation = expected_preparation
        self.kind = 'public_make_plan' if settings is not None else 'edge_helper_and_used_prefix'

    def run(self, module, *, before=False, mode='plain'):
        if mode not in ('plain', 'work', 'elapsed', 'allocation'):
            raise ValueError(mode)
        if tracemalloc.is_tracing() or sys.getprofile() is not None:
            raise RuntimeError('External tracing/profiling would contaminate this observation.')
        image, limit = self.image, self.limit
        initial = comparable(image)
        metadata, evidence, result = copy.deepcopy(self.acceleration_meta), {}, None
        observer = WorkObservation(module)
        if self.kind == 'public_make_plan':
            settings, area = copy.deepcopy(self.settings), tuple(self.area)
            def call():
                return DrawBot.make_plan(image, area, settings)
        else:
            function = module._edge_strokes
            kwargs = dict(draw_quality=self.quality, subject_focus=self.focus,
                gpu_mode='CPU', acceleration_meta=metadata,
                gpu_vram=self.helper_settings.get('gpu_vram', 'Auto'),
                gpu_performance=self.helper_settings.get('gpu_performance', 'Balanced'))
            if before and limit is not None:
                # Exactly the old caller boundary: complete helper, then prefix.
                def call():
                    return function(image, 10, lambda: False, **kwargs)[:limit]
            else:
                if limit is not None:
                    kwargs['max_strokes'] = limit
                def call():
                    return function(image, 10, lambda: False, **kwargs)
        with linked(module), ExitStack() as stack:
            if mode == 'work':
                stack.enter_context(observer.installed())
            try:
                if mode in ('elapsed', 'allocation'):
                    gc.collect()
                if mode == 'allocation':
                    tracemalloc.start()
                try:
                    started = time.perf_counter_ns() if mode == 'elapsed' else None
                    result = call()
                    if mode == 'elapsed':
                        evidence['elapsed_ns'] = time.perf_counter_ns() - started
                    if mode == 'allocation':
                        retained, peak = tracemalloc.get_traced_memory()
                        evidence.update(peak_python_bytes=peak, retained_with_result_bytes=retained)
                finally:
                    if mode == 'allocation':
                        tracemalloc.stop()
                if self.kind == 'public_make_plan':
                    output = comparable(result)
                    evidence['plan_summary'] = dict(count=result['count'], estimate=result['estimate'],
                        fitted=list(result['fitted']), portrait_stats=comparable(result['options']['portrait_stats']))
                else:
                    output = comparable(dict(strokes=result, acceleration_meta=metadata))
                if mode == 'work':
                    evidence['work'] = observer.result()
                    if self.expected_preparation is not None:
                        require_equal([self.expected_preparation], evidence['work']['preparations'],
                                      self.name + ' actual public preparation differs from helper input')
                require_equal(initial, comparable(image), self.name + ' borrowed input changed')
                return output, evidence
            finally:
                fixtures.close_images(result, (image,))


def parity_case(report, operation, old, current, *, observed=False):
    mode = 'work' if observed else 'plain'
    before, before_evidence = operation.run(old, before=True, mode=mode)
    after, after_evidence = operation.run(current, mode=mode)
    require_equal(before, after, operation.name)
    row = dict(name=operation.name, kind=operation.kind, complete_output_equal=True,
        output_sha256=digest(after), borrowed_input_unchanged=True,
        source=comparable(operation.image), limit=operation.limit,
        quality=operation.quality, subject_focus=operation.focus)
    if observed:
        row.update(before_work=before_evidence['work'], after_work=after_evidence['work'])
    if operation.settings is not None:
        row.update(settings=comparable(operation.settings), area=list(operation.area),
                   plan_summary=after_evidence['plan_summary'])
    report['parity'].append(row)
    return before, before_evidence, after_evidence


def preparation(report, old, current, source, area, settings):
    """Real complete preparations match before sharing the borrowed L input."""
    outputs = []
    initial = comparable(source)
    arguments = dict(area=area, detail=settings['detail'], contrast=settings['contrast'],
        subject_focus=settings.get('portrait_focus', True), draw_quality=settings['draw_quality'],
        gpu_mode='CPU', gpu_vram=settings.get('gpu_vram', 'Auto'),
        gpu_performance=settings.get('gpu_performance', 'Balanced'), preview_detail_mode=None)
    for module in (old, current):
        metadata = {}
        gray = None
        try:
            gray, fitted = module.prepare_portrait_image(source, acceleration_meta=metadata, **arguments)
            outputs.append(comparable(dict(gray=gray, fitted=fitted, acceleration_meta=metadata)))
            if module is current:
                result = gray
                gray = None
        finally:
            if gray is not None:
                gray.close()
    try:
        require_equal(outputs[0], outputs[1], 'whole published preparation')
        require_equal(initial, comparable(source), 'preparation borrowed input')
        report['preparation'].append(dict(source=initial, area=list(area),
            arguments=comparable(arguments), complete_output_equal=True,
            output=outputs[1], output_sha256=digest(outputs[1])))
        return result, copy.deepcopy(metadata), dict(arguments=comparable(arguments), output=outputs[1])
    except BaseException:
        result.close()
        raise


def workload(report, operation, old, current, repeats, verify_only):
    print('Starting ' + operation.name, flush=True)
    expected, before_work = operation.run(old, before=True, mode='work')
    actual, after_work = operation.run(current, mode='work')
    require_equal(expected, actual, operation.name + ' work observation')
    old_counts, new_counts = before_work['work']['totals'], after_work['work']['totals']
    require_equal(old_counts['occupied'], new_counts['occupied'], operation.name + ' occupied winners')
    if operation.name in ('edge-prepared-cap6', 'edge-prepared-cap65'):
        if not (old_counts['returned'] > operation.limit == new_counts['returned']
                and new_counts['heap_returned'] == operation.limit and new_counts['full_sort_input'] == 0):
            raise AssertionError('Small-prefix workload did not exercise bounded selection: ' + operation.name)
    if operation.name in ('public-3s', 'public-30s', 'public-unlimited'):
        intended = {'public-3s': 6, 'public-30s': 65, 'public-unlimited': 3690}[operation.name]
        for observed in (before_work, after_work):
            if [item['caller_edge_budget'] for item in observed['work']['calls']] != [intended]:
                raise AssertionError('Public fixture did not reach its actual initial edge budget.')
    row = dict(name=operation.name, kind=operation.kind, source=comparable(operation.image),
        limit=operation.limit, quality=operation.quality, subject_focus=operation.focus,
        settings=comparable(operation.settings), area=operation.area,
        helper_settings=comparable(operation.helper_settings),
        initial_acceleration_meta=comparable(operation.acceleration_meta),
        complete_output_equal=True, output_sha256=digest(actual),
        before_work=before_work['work'], after_work=after_work['work'], pairs=[], allocations=[])
    if operation.settings is not None:
        row['plan_summary'] = after_work['plan_summary']
    report['workloads'].append(row)
    if not verify_only:
        # Warm both real call paths; no observed/profiled call is a timed sample.
        for label, module in (('before', old), ('after', current)):
            value, _ = operation.run(module, before=label == 'before')
            require_equal(expected, value, operation.name + ' warm ' + label)
        for index in range(repeats):
            order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
            pair = dict(index=index, order=list(order))
            row['pairs'].append(pair)
            for label in order:
                value, measured = operation.run(old if label == 'before' else current,
                    before=label == 'before', mode='elapsed')
                pair[label + '_ns'] = measured['elapsed_ns']
                require_equal(expected, value, operation.name + ' timed ' + label)
            print(operation.name + f' pair {index + 1}/{repeats} complete', flush=True)
        for label, module in (('before', old), ('after', current)):
            value, allocation = operation.run(module, before=label == 'before', mode='allocation')
            row['allocations'].append(dict(side=label, **allocation))
            require_equal(expected, value, operation.name + ' traced ' + label)
        before_ns = [row['before_ns'] for row in row['pairs']]
        after_ns = [row['after_ns'] for row in row['pairs']]
        row.update(before_median_ns=statistics.median(before_ns), after_median_ns=statistics.median(after_ns),
            median_change_percent=(statistics.median(after_ns) / statistics.median(before_ns) - 1) * 100,
            faster_pairs=sum(right < left for left, right in zip(before_ns, after_ns)))
    print('Completed ' + operation.name, flush=True)


def run(report, repeats, verify_only):
    global DrawBot, Image, np, fixtures, VOLATILE_PATHS
    import RuntimePaths
    with tempfile.TemporaryDirectory(prefix='portrait-edge-benchmark-') as private, ExitStack() as stack:
        for name in ('source_dir', 'data_dir'):
            stack.enter_context(patch.object(RuntimePaths, name, return_value=Path(private)))
        stack.enter_context(patch.object(RuntimePaths, 'resource_dir', return_value=ROOT))
        import numpy as np
        from PIL import Image, __version__ as pillow_version
        import DrawBot
        import PortraitPlanner as current
        import test_v148_rendering_batch29_portrait_preparation as fixtures
        from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
        from test_v148_rendering_batch31_portrait_edges import plan_options

        raw = subprocess.check_output(['git', 'show', BASELINE + ':PortraitPlanner.py'], cwd=ROOT)
        alias = '_portrait_edge_history_' + BASELINE[:12]
        old = types.ModuleType(alias)
        old.__file__ = '<published ' + BASELINE + ':PortraitPlanner.py>'
        old.__package__ = ''
        stack.enter_context(patch.dict(sys.modules, {alias: old}))
        exec(compile(raw, old.__file__, 'exec'), old.__dict__)
        report.update(historical_module_sha256=sha(raw),
            current_module_sha256=report['source_before']['PortraitPlanner.py'],
            environment=dict(python=sys.version, platform=platform.platform(), numpy=np.__version__,
                pillow=pillow_version, gpu_mode='CPU', available_ram_mb=8192),
            comparison_exclusions=[list(path) for path in sorted(VOLATILE_PATHS)])

        # One actual calibration/options context spans every before/after pair;
        # private absolute storage paths remain in the complete comparisons.
        with fixtures.planner_fixture(quality='High likeness') as (directory, settings), ExitStack() as images:
            source = images.enter_context(closing(fixtures.source_image(size=(320, 240), opaque=True)))
            flat = images.enter_context(closing(Image.new('RGBA', source.size, 'white')))
            actual_settings = plan_options(settings)
            gray, gray_meta, gray_preparation = preparation(report, old, current, source, (1200, 900), actual_settings)
            images.enter_context(closing(gray))
            flat_gray, flat_meta, _ = preparation(report, old, current, flat, (1200, 900), actual_settings)
            images.enter_context(closing(flat_gray))
            small, _, _ = preparation(report, old, current, source, (96, 72), actual_settings)
            images.enter_context(closing(small))
            if gray.mode != 'L' or gray.size != (321, 241):
                raise AssertionError(('Unexpected actual prepared input', gray.mode, gray.size))
            y, x = np.indices((47, 63))
            ties = images.enter_context(closing(Image.fromarray((15 + (x // 3 % 2) * 220).astype(np.uint8))))
            ties.info['fixture_marker'] = 'equal-score stripes, borrowed input'
            file_map = lambda: {str(path.relative_to(directory)): sha(path.read_bytes())
                                for path in sorted(directory.rglob('*')) if path.is_file()}
            report['private_state_before'] = file_map()

            for quality in current.DRAW_QUALITY:
                for focus in (False, True):
                    for cap in (6, None):
                        operation = Operation(f'prepared/{quality}/focus{focus}/cap{cap}', small,
                                              limit=cap, quality=quality, focus=focus)
                        parity_case(report, operation, old, current)
                for cap in (6, None):
                    operation = Operation(f'ties/{quality}/cap{cap}', ties, limit=cap, quality=quality, focus=False)
                    _, observed, _ = parity_case(report, operation, old, current, observed=True)
                    if not observed['work']['calls'][0]['duplicate_score_winners']:
                        raise AssertionError('Tie fixture must contain actual equal-score winners.')
            for name, image in (('prepared', small), ('ties', ties)):
                full, _ = Operation(name, image).run(old, before=True)
                for cap in (0, max(0, len(full['strokes']) - 1)):
                    parity_case(report, Operation(f'{name}/boundary{cap}', image, limit=cap), old, current)

            for name, limit, dots, image in (
                ('public-small-3s', 3, False, source), ('public-small-30s', 30, False, source),
                ('public-small-unlimited', None, False, source), ('public-flat-control', 3, False, flat),
                ('public-dots-control', 3, True, source),
            ):
                operation = Operation(name, image, settings=plan_options(settings, limit, dots), area=(128, 96))
                _, before_evidence, after_evidence = parity_case(report, operation, old, current, observed=True)
                if dots and (before_evidence['work']['calls'] or after_evidence['work']['calls']):
                    raise AssertionError('Dots control unexpectedly entered the edge helper.')

            helper_args = dict(helper_settings=actual_settings, acceleration_meta=gray_meta)
            full, _ = Operation('prepared-full-boundary', gray, **helper_args).run(old, before=True)
            near_full = max(0, len(full['strokes']) - 1)
            operations = [Operation(f'edge-prepared-cap{cap}', gray, limit=cap, **helper_args) for cap in (6, 65, 3690)]
            operations += [Operation('edge-near-full-control', gray, limit=near_full, **helper_args),
                Operation('edge-unbounded-control', gray, **helper_args),
                Operation('edge-flat-control', flat_gray, limit=65,
                    helper_settings=actual_settings, acceleration_meta=flat_meta)]
            operations += [Operation('public-' + ('unlimited' if limit is None else str(limit) + 's'), source,
                settings=plan_options(settings, limit), area=(1200, 900),
                expected_preparation=gray_preparation) for limit in (3, 30, None)]
            for operation in operations:
                workload(report, operation, old, current, repeats, verify_only)
            report['private_state_after'] = file_map()
            require_equal(report['private_state_before'], report['private_state_after'], 'private calibration state')
    report['parity_count'] = len(report['parity'])
    report['preparation_count'] = len(report['preparation'])
    report['workload_count'] = len(report['workloads'])
    report['complete_output_digest'] = digest([row['output_sha256'] for row in report['parity'] + report['workloads']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.repeats < 2 or args.repeats % 2:
        parser.error('--repeats must be an even number of at least two')
    if tracemalloc.is_tracing() or sys.getprofile() is not None:
        parser.error('External tracing/profiling is incompatible with this experiment')
    sys.dont_write_bytecode = True
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = output.open('x', encoding='utf-8')
    source_before = sources()
    report = dict(schema_version=1, baseline=BASELINE, passed=False, verify_only=args.verify_only,
        repeats=0 if args.verify_only else args.repeats, source_before=source_before,
        source_before_digest=digest(source_before), preparation=[], parity=[], workloads=[],
        method=dict(
            historical_linkage='Whole published PortraitPlanner at e49 is compared with current PortraitPlanner. Both real DrawBot imports and sys.modules are rebound outside clocks. Current DrawBot (including Portrait plan ownership) and all other recorded dependencies are shared; this is not a replay of the whole old application.',
            helper_scope='Whole actual _edge_strokes; before additionally takes the exact prefix discarded by its historical caller. Unbounded control omits the new max_strokes keyword on both sides. Preparation uses the real UI-derived options, including High throughput even in CPU mode, and is compared byte-for-byte outside helper clocks; actual public prepare arguments/gray/fitted/metadata must match that input. Initial edge budgets6/65/3690 are not final post-time-fit counts or delivered physical strokes.',
            public_scope='Whole real make_plan, including preparation, tone selection, contour selection, actual budget/time-fit, diagnostics and internal cleanup. Inputs/options, module binding, GC, output comparison and caller-owned result cleanup are outside each clock.',
            work_scope='Separate sys.setprofile observations of real helper returns, list.sort inputs, heapq.nlargest input/return and its final sort, plus actual finish_plan returns. No numerical function, sort, heap or clock is replaced.',
            allocation_scope='Separate same-call tracemalloc peak and retained-with-result; prepared borrowed sources and setup are excluded. Native Pillow buffers are not necessarily traced. This is not RSS or hardware/GPU performance.',
            samples=('Exact historical comparisons and work observations only; no timings or allocation probes.' if args.verify_only else
                     f'One warm before/after pair per workload, then {args.repeats} balanced AB/BA elapsed pairs without sample removal, then separate before/after tracemalloc probes.'),
            limits='CPU-only synthetic image fixtures through actual public planners. Flat, near-full, full-budget, unbounded and Dots controls are retained. Helper improvements do not imply a whole-application speedup; every slower/noisy timing and higher allocation is retained.'))
    failure = None
    try:
        run(report, args.repeats, args.verify_only)
        report['passed'] = True
    except BaseException as error:
        failure = error
        report['failure'] = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
    finally:
        source_after = sources()
        report.update(source_after=source_after, source_after_digest=digest(source_after),
                      sources_unchanged=source_before == source_after)
        if source_before != source_after:
            report['passed'] = False
        json.dump(report, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write('\n')
        handle.close()
        print(json.dumps(dict(passed=report['passed'], parity_cases=len(report['parity']),
            preparation_cases=len(report['preparation']), workloads=len(report['workloads']),
            sources_unchanged=report['sources_unchanged'], source_digest=report['source_before_digest'],
            output=str(output))), flush=True)
    if failure is not None:
        raise failure
    if not report['passed']:
        raise SystemExit('Source files changed during this run; the raw report is invalid.')


if __name__ == '__main__':
    main()
