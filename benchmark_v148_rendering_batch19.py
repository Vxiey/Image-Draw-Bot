"""Compare bounded native-footprint preparation against the published module.

Use --verify-only while sources are changing. Coordinate a quiet source/CPU
window for six balanced AB/BA pairs and separate traced-allocation probes.
"""
import argparse
from collections import Counter
from contextlib import closing, contextmanager
import hashlib
import itertools
import json
from pathlib import Path
import platform
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

import AdaptiveRegionHybrid as regional
import DrawBot
from NativeBrushProjection import NativeBrushProjection
from benchmark_v148_image_workflow import fingerprint, old_module
from benchmark_v148_stroke_optimizer import paired
from test_v148_rendering_batch06_canvas import close_plan
import test_v148_rendering_batch10_physical as physical
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch19_native_tiles import independent_ink, mixed_sequence, sample_map


ROOT = Path(__file__).resolve().parent
BASELINE = '7f41c7ee8c4b69f750008bd2d83349d186396fd1'
EXCLUDED = VOLATILE_PATHS | {
    ('options', 'adaptive_hybrid_meta', 'timings'), ('adaptive_hybrid_meta', 'timings')}


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def comparable(value, path=()):
    if isinstance(value, dict):
        return {key: comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in EXCLUDED}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def simulate(module, source, sequence, projection, fills=(), default_brush=1):
    metrics, coverage, error = module.simulate_native_plan(source, sequence, projection,
        fills, default_brush=default_brush)
    with closing(coverage), closing(error):
        return fingerprint((metrics, coverage, error))


def historical_parity(before):
    counts, hashes = Counter(), []
    for seed, size, (area, fitted, limit), kind, use_fill in itertools.product(
            (1481901, 1481902), ((17, 13), (31, 29)),
            (((71, 53), (67.5, 48.5), 73), ((191, 257), (191., 257.), 75000),
             ((80, 60), (79.5, 59.5), 75000)), ('empty', 'axis', 'mixed'), (False, True)):
        source = sample_map(size, seed)
        saved = fingerprint(vars(source))
        for value in vars(source).values():
            if isinstance(value, np.ndarray):
                value.flags.writeable = False
        if kind == 'empty':
            sequence = []
        elif kind == 'axis':
            sequence = [{'color_index': 1, 'brush_px': 4, 'path': ((-2, 4), (size[0]+1, 4))},
                        {'color_index': 2, 'brush_px': 1, 'path': ()},
                        {'color_index': 0, 'path': ((8, -2), (8, size[1]+1))}]
        else:
            sequence = mixed_sequence(size, seed)
        fills = [{'color_index': 2, 'row_spans': [(2, 2, size[0]-2), (7, size[0]-3, 3)]}] if use_fill else []
        projection = NativeBrushProjection(size, fitted, {'_planning_canvas_size': area,
            'planner_max_pixels': limit, 'corners': ((-33, -17), (-33+area[0], -17+area[1]))})
        arguments = source, sequence, projection, fills, 3
        expected, actual = simulate(before, *arguments), simulate(regional, *arguments)
        if actual != expected:
            raise AssertionError(('Complete historical native result mismatch', seed, size, area, kind, use_fill))
        if fingerprint(vars(source)) != saved:
            raise AssertionError('A native simulator mutated borrowed map data.')
        hashes.append(digest(actual)); counts['complete_native_pairs'] += 1
    return dict(counts, complete_output_sha256=digest(hashes))


@contextmanager
def observed_simulation(module):
    """Count real work outside timer/tracemalloc probes; never retain images."""
    records = []
    real = module.simulate_native_plan
    def observed(source, sequence, projection, *args, **kwargs):
        row = {'tiles': sum(1 for _ in projection.tiles()),
               'nonempty_paths': sum(bool(entry.get('path')) for entry in sequence),
               'native_path_calls': 0, 'rectangle_streams': 0, 'rectangles_prepared': 0,
               'index_capacity_bytes': 0, 'index_retained_bytes': 0, 'index_used': False}
        native, rectangles, allocate = projection.native_path, module._native_rectangles, np.empty
        prepare = getattr(module, '_native_footprint_index', None)
        def counted_native(*a, **k):
            row['native_path_calls'] += 1
            return native(*a, **k)
        def counted_rectangles(*a, **k):
            row['rectangle_streams'] += 1
            for value in rectangles(*a, **k):
                row['rectangles_prepared'] += 1
                yield value
        def allocated(shape, *a, **k):
            value = allocate(shape, *a, **k)
            if value.ndim == 2 and value.shape[1] == 5 and value.dtype == np.int64:
                row['index_capacity_bytes'] = max(row['index_capacity_bytes'], value.nbytes)
            return value
        def prepared(*a, **k):
            with patch.object(module.np, 'empty', new=allocated):
                value = prepare(*a, **k)
            row['index_used'] = value is not None
            row['index_retained_bytes'] = 0 if value is None else value.nbytes
            return value
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(projection, 'native_path', new=counted_native))
            stack.enter_context(patch.object(module, '_native_rectangles', new=counted_rectangles))
            if prepare is not None:
                stack.enter_context(patch.object(module, '_native_footprint_index', new=prepared))
            result = real(source, sequence, projection, *args, **kwargs)
        records.append(row)
        return result
    with patch.object(module, 'simulate_native_plan', new=observed):
        yield records


def verify_literal_native(module, source, sequence, projection, fills):
    expected, pixels, size = independent_ink(source, sequence, projection.fitted,
        projection.canvas_size, origin=projection.origin, fill_regions=fills)
    actual = simulate(module, source, sequence, projection, fills)
    if {key: actual[0][key] for key in expected} != expected:
        raise AssertionError('Independent native count/score oracle failed.')
    image = {'mode': 'RGB', 'size': list(size), 'sha256': hashlib.sha256(pixels).hexdigest()}
    if actual[1:] != [image, image]:
        raise AssertionError('Independent native overpaint/preview oracle failed.')
    return digest(actual)


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA pairs.')
    before = old_module('AdaptiveRegionHybrid', revision)
    sources = source_hashes()
    report = {'baseline': revision, 'historical_module_sha256': hashlib.sha256(
        subprocess.check_output(['git', 'show', revision+':AdaptiveRegionHybrid.py'], cwd=ROOT)).hexdigest(),
        'source_sha256': sources, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'verify_only': verify_only,
        'repeats': None if verify_only else repeats,
        'isolation': 'Complete historical AdaptiveRegionHybrid module with shared current public make_plan, projection and all unrelated dependencies on both sides.',
        'method': 'One warm/parity pair, six balanced AB/BA timing pairs, then separate tracemalloc peaks after garbage collection. Every invocation compares complete outputs. Work counters and independent native replay run outside timing.',
        'timing_scope': 'CPU planning/simulation, complete-output fingerprinting and owned-image cleanup. No physical input, GPU, GUI or network timings.',
        'memory_scope': 'Python/NumPy traced peaks, excluding process RSS and most native Pillow cores. Index construction capacity and retained payload bytes are separately observed outside timing.',
        'fallback': 'One tile stays streamed. Non-list/tuple input containers, more than the bounded point/span budget, more than min(8192,pixel_allowance) rectangles, or optional table allocation/shrink MemoryError retain per-tile streaming. Overflow may add one bounded preparation attempt; no partial cache survives.',
        'public_plan_exclusions': ['.'.join(path) for path in sorted(EXCLUDED)],
        'resource_probe_controls': {'available_ram_mb': 8192, 'logical_cpu_count': 8},
        'historical_parity': historical_parity(before), 'measurements': {}}

    def compare(left, right):
        if not verify_only:
            return paired(left, right, repeats)
        expected = left()
        if right() != expected:
            raise AssertionError('Complete output parity failed.')
        return {'exact_output_parity': True, 'output_sha256': digest(expected)}

    native = [
        {'color_index': 1, 'brush_px': 4, 'path': ((-2, 4), (18, 4))},
        {'color_index': 2, 'brush_px': 1, 'path': ()},
        {'color_index': 0, 'path': ((8, -2), (8, 14))},
        {'color_index': 2, 'brush_px': 3, 'path': ((1, 1), (15, 11))},
        {'color_index': 1, 'brush_px': 2, 'path': ((12, 5),)},
        {'color_index': 0, 'brush_px': 1, 'path': ((15, 2), (2, 10))}]
    fills = [{'color_index': 2, 'row_spans': [(2, 2, 14), (7, 11, 3)]}]
    overflow = [{'color_index': index % 3, 'brush_px': 1+index % 5,
                 'path': ((0, 0), (16, 12)) if index % 2 else ((16, 0), (0, 12))}
                for index in range(22)]
    source = sample_map()
    for name, area, fitted, sequence, regions in (
            ('single_tile', (64, 48), (63.5, 47.5), native, fills),
            ('native_2200x1300', (2200, 1300), (2199., 1299.), native, fills),
            ('overflow_stream', (512, 384), (512., 384.), overflow, [])):
        projection = NativeBrushProjection((17, 13), fitted, {'_planning_canvas_size': area,
            'planner_max_pixels': 75000, 'corners': ((-33, -17), (-33+area[0], -17+area[1]))})
        left = lambda: simulate(before, source, sequence, projection, regions)
        right = lambda: simulate(regional, source, sequence, projection, regions)
        row = compare(left, right)
        if verify_literal_native(regional, source, sequence, projection, regions) != row['output_sha256']:
            raise AssertionError('Independent direct native proof changed compared output.')
        for side, module, operation in (('before', before, left), ('after', regional, right)):
            with observed_simulation(module) as observed:
                result = operation()
            if digest(result) != row['output_sha256']:
                raise AssertionError('Observed native work changed output.')
            row[side+'_work'] = observed
        row.update(parameters={'source_size': [17, 13], 'canvas_size': area, 'fitted': fitted,
                               'sequence': sequence, 'fills': regions, 'seed': 1481901},
                   independent_native_raster_parity=True)
        report['measurements']['R1901_'+name] = row

    with patch('DrawTimeCalibration.load_profile', return_value=None), \
            patch('ResourceAllocation.available_ram_mb', return_value=8192), \
            patch('ResourceAllocation.logical_cpu_count', return_value=8):
        for name, size, area, box in (
                ('packed_400x300', (200, 150), (400, 300), (48, 40, 143, 103)),
                ('fallback_1200x900', (200, 150), (1200, 900), (48, 40, 143, 103)),
                ('fractional_431x321', (197, 151), (431, 321), (30, 30, 165, 120))):
            with closing(Image.new('RGB', size, 'white')) as original:
                drawing = ImageDraw.Draw(original)
                drawing.rectangle(box, fill=(0, 80, 205))
                del drawing
                settings = physical.physical_options((100, 100), area)
                def public(module, *, prove_native=False):
                    references = []
                    simulate_native = module.simulate_native_plan
                    def capture(pixel_map, *args, **kwargs):
                        references.append(pixel_map)
                        return simulate_native(pixel_map, *args, **kwargs)
                    with patch.object(regional, 'build_adaptive_hybrid_plan', new=module.build_adaptive_hybrid_plan), \
                            patch.object(module, 'simulate_native_plan', new=capture):
                        plan = DrawBot.make_plan(original, area, dict(settings))
                    try:
                        result = comparable(plan)
                        if prove_native:
                            if len(references) != 1:
                                raise AssertionError('Real plan did not use one physical simulation.')
                            pixels, _selected = physical.replay_executor(plan, (100, 100), area)
                            physical.PhysicalBrushProjectionTests.assert_report_matches_native_actions(
                                unittest.TestCase(), plan, references[0], pixels, area)
                        return result
                    finally:
                        close_plan(plan, original)
                left, right = lambda: public(before), lambda: public(regional)
                if public(before, prove_native=True) != public(regional, prove_native=True):
                    raise AssertionError('Native-verified public plan changed complete output.')
                row = compare(left, right)
                for side, module, operation in (('before', before, left), ('after', regional, right)):
                    with observed_simulation(module) as observed:
                        result = operation()
                    if digest(result) != row['output_sha256']:
                        raise AssertionError('Observed public native work changed output.')
                    row[side+'_work'] = observed
                row.update(parameters={'source_size': size, 'canvas_size': area, 'box': box,
                                       'options': settings}, independent_native_raster_parity=True)
                report['measurements']['R1901_make_plan_'+name] = row

    if source_hashes() != sources:
        raise AssertionError('Source changed during the comparison; coordinate and rerun.')
    report['source_unchanged_during_measurement'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch19-rendering-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'historical_parity': result['historical_parity'],
                      'measurement_pairs': len(result['measurements']), 'output': str(args.output),
                      'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}, indent=2))
