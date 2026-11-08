"""Whole historical palette parity and balanced cold/warm CPU observations.

Only PicturePaletteRefinement is historical; every other current dependency is
shared and hashed. Real cache reads/writes, public builders and plans are used.
Elapsed samples, assignment counters and traced allocations are separate runs.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
import copy
from dataclasses import asdict, is_dataclass
import gc
import hashlib
import json
from pathlib import Path
import platform
import shutil
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
BASELINE = '4b90b715a9128a022774f411e14e8a1b45676339'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def sources():
    return {path.name: sha(path.read_bytes()) for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def selected(module):
    with patch.dict(sys.modules, {'PicturePaletteRefinement': module}):
        yield


def clear_cache(directory):
    # This directory belongs solely to this experiment. Deletion is outside
    # every timer and allocation probe, before each real cold invocation.
    path = directory / 'picture-palettes'
    if path.exists():
        shutil.rmtree(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=6)
    parser.add_argument('--parity-only', action='store_true')
    args = parser.parse_args()
    if args.pairs < 2 or args.pairs % 2:
        parser.error('--pairs must be a positive even number of at least two')
    if tracemalloc.is_tracing():
        parser.error('An external allocation tracer would invalidate elapsed observations')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve exclusively before work. Even failures retain their partial raw data.
    handle = output.open('x', encoding='utf-8')
    source_before = sources()
    report = dict(baseline=BASELINE, source_before=source_before,
        source_before_digest=digest(source_before), parity=[], workloads=[],
        pairs=args.pairs, parity_only=args.parity_only,
        method={
            'historical_graph': 'Whole PicturePaletteRefinement at baseline; all other current dependencies shared.',
            'real_cache': 'Actual private cache; cold removal or warm priming happens outside timers/tracing.',
            'pair_order': 'Six balanced AB/BA pairs by default; no sample rejection.',
            'separate_observers': 'Work counts and Python peak/retained probes run separately from elapsed pairs.',
            'timed_scope': 'Whole public cold/warm build_picture_palette or explicit direct refinement, with the same local module-binding context overhead on both sides. Public make_plan parity is untimed.',
            'limits': 'No native Paint, GPU, total process memory/RSS or universal performance claim.'})
    try:
        import RuntimePaths
        with tempfile.TemporaryDirectory(prefix='palette-growth-state-') as temp, ExitStack() as stack:
            state = Path(temp)
            for name in ('source_dir', 'data_dir'):
                stack.enter_context(patch.object(RuntimePaths, name, return_value=state))
            stack.enter_context(patch.object(RuntimePaths, 'resource_dir', return_value=ROOT))
            import numpy as np
            from PIL import Image, __version__ as pillow_version
            import DrawBot
            import PictureCustomPalette as picture
            import PicturePaletteRefinement as current
            from test_v148_colour_batch30_palette_growth import PALETTE, palette_source
            from test_v148_colour_batch19_regions import region_graphic, public_settings
            from test_v148_rendering_batch06_canvas import close_plan
            from test_v148_rendering_batch17_layered_diagnostics import calibrated
            from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
            # Restore both aliases when this experiment leaves its private state.
            stack.enter_context(patch.object(picture._legacy, 'data_dir', return_value=state))
            stack.enter_context(patch.object(picture, 'data_dir', return_value=state))
            raw = subprocess.check_output(['git', 'show', BASELINE + ':PicturePaletteRefinement.py'], cwd=ROOT)
            old = types.ModuleType('PicturePaletteRefinement')
            old.__file__ = '<published ' + BASELINE + ':PicturePaletteRefinement.py>'
            exec(compile(raw, old.__file__, 'exec'), old.__dict__)
            report.update(historical_module_sha256=sha(raw), current_module_sha256=source_before['PicturePaletteRefinement.py'],
                environment=dict(python=sys.version, platform=platform.platform(), numpy=np.__version__, pillow=pillow_version),
                volatile_public_paths=sorted([list(path) for path in VOLATILE_PATHS]))

            def comparable(value, path=()):
                if is_dataclass(value):
                    return comparable(asdict(value), path)
                if isinstance(value, Image.Image):
                    return dict(image=dict(mode=value.mode, size=list(value.size), sha256=sha(value.tobytes()),
                        info=comparable(dict(value.info), path), exif_sha256=sha(value.getexif().tobytes())))
                if isinstance(value, np.ndarray):
                    return dict(array=dict(dtype=str(value.dtype), shape=list(value.shape), sha256=sha(value.tobytes())))
                if isinstance(value, dict):
                    return {key if isinstance(key, str) else repr((type(key).__name__, key)): comparable(item, (*path, key))
                            for key, item in value.items() if (*path, key) not in VOLATILE_PATHS}
                if isinstance(value, (tuple, list)):
                    return [comparable(item, path) for item in value]
                if isinstance(value, np.generic):
                    return value.item()
                if isinstance(value, bytes):
                    return dict(bytes=len(value), sha256=sha(value))
                if value is None or isinstance(value, (str, int, float, bool)):
                    return value
                raise TypeError(('Unaccounted complete output', path, type(value).__name__))

            def make_source(kind, size=(128, 96)):
                return region_graphic(size) if kind == 'regions' else palette_source(kind, size)

            def invoke(module, source, *, direct=False, limit=24):
                with selected(module):
                    if direct:
                        return module.refine_picture_palette(source, PALETTE[:4], limit)
                    return picture.build_picture_palette(source, PALETTE, max_colors=limit,
                                                         calibration_fingerprint='batch30-paired')

            def counted(module, source, *, direct=False, limit=24, warm=False):
                calls = []
                original = module._assign
                def observed(points, centers, cancelled):
                    calls.append(dict(points=len(points), centers=len(centers)))
                    return original(points, centers, cancelled)
                clear_cache(state)
                if warm:
                    invoke(module, source, direct=direct, limit=limit)
                with patch.object(module, '_assign', new=observed):
                    result = invoke(module, source, direct=direct, limit=limit)
                return comparable(result), dict(assignments=calls,
                    point_center_pairs=sum(row['points'] * row['centers'] for row in calls))

            # Actual cold builders match every field, and warm reads match the
            # complete persisted palette after the changed computation.
            for kind in ('near-grey', 'red-shades', 'gradient', 'regions'):
                for limit in (8, 24):
                    with closing(make_source(kind)) as source:
                        original = source.tobytes(), dict(source.info)
                        for warm in (False, True):
                            outputs, counts = [], []
                            for module in (old, current):
                                value, work = counted(module, source, limit=limit, warm=warm)
                                outputs.append(value); counts.append(work)
                            assert outputs[0] == outputs[1], ('public palette mismatch', kind, limit, warm)
                            assert (source.tobytes(), dict(source.info)) == original
                            report['parity'].append(dict(kind='picture-builder', source=kind, limit=limit,
                                warm=warm, complete_output_equal=True, output=outputs[1], counts=counts))

            # Direct mode/size/sample controls include the >MAX_SAMPLES path.
            for size in ((1, 41), (41, 1), (37, 29), (160, 128)):
                for mode in ('RGB', 'RGBA', 'P'):
                    with closing(make_source('red-shades', size)) as original, closing(original.convert(mode)) as source:
                        if mode == 'RGBA':
                            with closing(Image.fromarray(np.array([0, 128, 255], np.uint8)[np.indices(size[::-1]).sum(axis=0) % 3])) as alpha:
                                source.putalpha(alpha)
                        elif mode == 'P':
                            source.info['transparency'] = bytes(range(256))
                        initial = source.tobytes(), dict(source.info)
                        outputs = [module.refine_picture_palette(source, PALETTE[:4], 16) for module in (old, current)]
                        assert outputs[0] == outputs[1], ('direct mismatch', size, mode)
                        assert (source.tobytes(), dict(source.info)) == initial
                        report['parity'].append(dict(kind='direct', size=list(size), mode=mode,
                            complete_output_equal=True, colors=outputs[1]))

            # Hold the actual calibration and storage paths constant across each
            # pair. Only the seven pre-existing profiler-clock paths are omitted.
            for kind in ('near-grey', 'red-shades'):
                for quality in ('Balanced', 'Pixel Accurate'):
                    with closing(make_source(kind, (64, 48))) as source, calibrated(PALETTE):
                        options = public_settings()
                        options.update(draw_quality=quality, color_rendering='Perceptual match',
                                       exact_color_limit='24', ram_available_mb=8192)
                        before_source = source.tobytes(), dict(source.info)
                        outputs, counts = [], []
                        for module in (old, current):
                            clear_cache(state)
                            calls = []
                            real = module.refine_picture_palette
                            def observed(*values, **kwargs):
                                calls.append(dict(size=list(values[0].size), initial_colors=len(values[1]), limit=values[2]))
                                return real(*values, **kwargs)
                            plan = None
                            try:
                                with selected(module), patch.object(module, 'refine_picture_palette', new=observed):
                                    plan = DrawBot.make_plan(source, source.size, copy.deepcopy(options))
                                outputs.append(comparable(plan)); counts.append(calls)
                                assert bool(calls) == (quality == 'Pixel Accurate'), 'Unexpected real public palette route'
                            finally:
                                close_plan(plan, source)
                        assert outputs[0] == outputs[1], ('complete public plan mismatch', kind, quality)
                        assert (source.tobytes(), dict(source.info)) == before_source
                        report['parity'].append(dict(kind='public-plan', source=kind, quality=quality,
                            complete_output_equal=True, output_digest=digest(outputs[1]), calls=counts))

            workloads = (
                ('cold-grey-24', 'near-grey', False, False),
                ('cold-red-24', 'red-shades', False, False),
                ('cold-full-palette-control', 'gradient', False, False),
                ('cold-region-control', 'regions', False, False),
                ('warm-cache-control', 'red-shades', False, True),
                ('direct-red-refinement', 'red-shades', True, False),
            )
            if not args.parity_only:
                for name, kind, direct, warm in workloads:
                    row = dict(name=name, source=kind, direct=direct, warm=warm, pairs=[], allocations=[])
                    report['workloads'].append(row)
                    with closing(make_source(kind)) as source:
                        expected, old_work = counted(old, source, direct=direct, warm=warm)
                        new_value, new_work = counted(current, source, direct=direct, warm=warm)
                        assert expected == new_value
                        row.update(work_before=old_work, work_after=new_work, output_digest=digest(expected))
                        def prepare(module):
                            clear_cache(state)
                            if warm:
                                invoke(module, source, direct=direct)
                        # Warm both code paths; these calls are never samples.
                        for module in (old, current):
                            prepare(module)
                            assert comparable(invoke(module, source, direct=direct)) == expected
                        for pair in range(args.pairs):
                            order = (('before', old), ('after', current)) if pair % 2 == 0 else (('after', current), ('before', old))
                            sample = dict(index=pair, order=[label for label, _ in order])
                            row['pairs'].append(sample)
                            for label, module in order:
                                prepare(module)
                                gc.collect()
                                started = time.perf_counter_ns()
                                result = invoke(module, source, direct=direct)
                                sample[label + '_ns'] = time.perf_counter_ns() - started
                                assert comparable(result) == expected
                                del result
                        # Explicit separate Python-allocation probes. Pillow or
                        # other native allocations are not total process memory.
                        for label, module in (('before', old), ('after', current)):
                            prepare(module)
                            gc.collect()
                            tracemalloc.start()
                            try:
                                result = invoke(module, source, direct=direct)
                                retained, peak = tracemalloc.get_traced_memory()
                            finally:
                                tracemalloc.stop()
                            assert comparable(result) == expected
                            row['allocations'].append(dict(side=label, retained_bytes=retained, peak_bytes=peak))
                            del result
                        a = [sample['before_ns'] for sample in row['pairs']]
                        b = [sample['after_ns'] for sample in row['pairs']]
                        row.update(before_median_ns=statistics.median(a), after_median_ns=statistics.median(b),
                            change_percent=(statistics.median(b) / statistics.median(a) - 1) * 100,
                            faster_pairs=sum(y < x for x, y in zip(a, b)))
            report['passed'] = True
    except BaseException as error:
        report.update(passed=False, failure=dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
        raise
    finally:
        source_after = sources()
        report.update(source_after=source_after, source_after_digest=digest(source_after), sources_unchanged=source_before == source_after)
        json.dump(report, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write('\n'); handle.close()
        print(json.dumps(dict(passed=report.get('passed', False), parity_cases=len(report['parity']),
            workloads=[{key: value for key, value in row.items() if key in ('name', 'before_median_ns', 'after_median_ns', 'change_percent', 'faster_pairs')}
                       for row in report['workloads']], sources_unchanged=report['sources_unchanged'],
            source_digest=report['source_before_digest'], output=str(output))))


if __name__ == '__main__':
    main()
