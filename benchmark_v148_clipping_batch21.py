"""Compare complete historical clipping with current real caller pipelines.

Only CanvasGuard is substituted. Its imported aliases in DrawBot, EdgeBehavior
and PreviewSafety are linked to the same revision. All other caller bodies and
dependencies are identical. No native input, screen capture or persistence is
performed; the executor uses the existing recorded-action device fixture.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager, closing
import hashlib
import inspect
import json
from pathlib import Path
import platform
import random
import subprocess
import sys
from unittest.mock import patch

from PIL import Image, ImageDraw
import CanvasGuard as current
import DrawBot
import EdgeBehavior
import PreviewSafety
from benchmark_v148_image_workflow import old_module
from benchmark_v148_probe_geometry import execution_workload
from benchmark_v148_stroke_optimizer import paired
from benchmark_v148_colour_batch20 import comparable as comparable_plan
from test_pixel_accuracy_engine_v1088 import options
from test_v148_delivery_batch21_clipping import no_execution_persistence
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated


ROOT = Path(__file__).resolve().parent
BASELINE = 'ec22fd8739573adc2df1b3e33dbe1a98a09b9c99'
RECTANGLE = ((0, 0), (100, 0), (100, 100), (0, 100))
CONCAVE = ((0, 0), (100, 0), (100, 25), (25, 25), (25, 100), (0, 100))
LONG_PATH = tuple((-8+(i % 41)*3, 10+((i//41) % 27)*3) for i in range(2048))
SAFE_PATH = tuple((102+(i % 90), 102+((i//90) % 90)) for i in range(2048))
THIN_PATH = tuple((8+(i % 2)*.05, .6-(i % 2)*.02) for i in range(512))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def linked_geometry(module):
    aliases = (
        (DrawBot, ('CanvasGuard', 'FinalMouseGuard', 'normalize_canvas_anchors', 'CanvasSafetyStop')),
        (EdgeBehavior, ('CanvasGuard', 'CanvasSafetyStop', '_float_point', '_round_point',
                        '_safe_projection', '_nearest_boundary_point', 'point_in_polygon')),
        (PreviewSafety, ('CanvasGuard', 'CanvasSafetyStop', 'normalize_canvas_anchors', 'normalize_canvas_polygon')),
    )
    with ExitStack() as stack:
        for consumer, names in aliases:
            for name in names:
                stack.enter_context(patch.object(consumer, name, getattr(module, name)))
        yield


def result_or_error(operation):
    try:
        return {'result': operation()}
    except (ValueError, OverflowError, InterruptedError) as error:
        return {'exception': type(error).__name__, 'message': str(error)}


def historical_parity(before):
    rng = random.Random(1482102)
    signatures = []
    cases = Counter()
    polygons = (RECTANGLE, CONCAVE,
        ((-30, -20), (50, -20), (50, 60), (-30, 60)),
        ((0, 20), (20, 0), (40, 20), (20, 40)),
        ((0, 0), (10, 0), (0, 3)),
        ((.1, .1), (.2, .1), (.2, .2), (.1, .2)),
        ((0, 0), (12, 0), (12, 12), (8, 12), (8, 4), (4, 4), (4, 12), (0, 12)))
    for polygon in polygons:
        for variant in (polygon, tuple(reversed(polygon)), polygon[1:]+polygon[:1]):
            for index in range(40):
                a = (rng.randrange(-50, 151)/2, rng.randrange(-50, 151)/2)
                b = a if index % 5 == 0 else (rng.randrange(-50, 151)/2, rng.randrange(-50, 151)/2)
                path = (a, b, (rng.randrange(-30, 121), rng.randrange(-30, 121)))
                for name, args in (('clip_segment_to_polygon', (a, b, variant)),
                                   ('clip_path_to_polygon', (path, variant)),
                                   ('_safe_projection', (a, variant)),
                                   ('_nearest_boundary_point', (a, variant))):
                    expected = result_or_error(lambda: getattr(before, name)(*args))
                    actual = result_or_error(lambda: getattr(current, name)(*args))
                    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                        raise AssertionError((name, args, expected, actual))
                    signatures.append(digest(actual)); cases[name] += 1
    for point in ((float('nan'), 1), (float('inf'), 1), (10**400, 1), ('bad', 1), (1e308, -1e308)):
        for name, args in (('clip_segment_to_polygon', (point, (1, 1), RECTANGLE)),
                           ('clip_path_to_polygon', ((point, (1, 1)), RECTANGLE)),
                           ('_safe_projection', (point, RECTANGLE)),
                           ('_nearest_boundary_point', (point, RECTANGLE))):
            expected = result_or_error(lambda: getattr(before, name)(*args))
            actual = result_or_error(lambda: getattr(current, name)(*args))
            if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                raise AssertionError((name, expected, actual))
            signatures.append(digest(actual)); cases['invalid_or_extreme'] += 1
    for stop_at in (1, 2, 4, 6, 8, 10):
        values = []
        for module in (before, current):
            calls = 0
            def cancelled():
                nonlocal calls
                calls += 1
                return calls == stop_at
            values.append((result_or_error(lambda: module.clip_path_to_polygon(LONG_PATH, RECTANGLE, cancelled=cancelled)), calls))
        if values[0] != values[1]:
            raise AssertionError(('cancellation', stop_at, values))
        signatures.append(digest(values[0])); cases['cancellation'] += 1
    return {'counts': dict(cases), 'total': sum(cases.values()), 'output_sha256': digest(signatures)}


def caller_work(module, operation):
    counts = Counter()
    original = module._float_point
    def observed(point):
        frame = inspect.currentframe().f_back
        name = frame.f_code.co_name
        if name in ('<genexpr>', '<listcomp>'):
            name = frame.f_back.f_code.co_name+'/'+name
        del frame
        counts[name] += 1
        return original(point)
    with patch.object(module, '_float_point', observed):
        result = operation()
    return result, {'float_point_calls': dict(sorted(counts.items())), 'total': sum(counts.values())}


def preview_workload():
    paths = [tuple((2+(i % 90), 2+((i//90+j*3) % 90)) for i in range(640)) for j in range(8)]
    result = PreviewSafety.build_preview_safety_plan((96, 96), (96, 96), [[]], [paths],
        {'brush_px': 2, 'edge_behavior': 'Hard Clip', '_planning_canvas_size': (96, 96)})
    return {'groups': result.groups, 'sequence': result.sequence, 'mode': result.mode, 'meta': result.meta}


def public_plan(source):
    opts = options(profile_name='Microsoft Paint', profile_key='microsoft-paint',
        render_preset='Manual', drawing_style='Auto', auto_engine_resolved=True,
        time_budget_mode='Unlimited', unlimited_time=True, adaptive_deadline_renderer=False,
        detail_zoom='Off', progressive_rendering='Off', color_workflow='Finish color first',
        _execution_cost_calibration_override={}, cpu_workers_resolved=1, edge_behavior='Hard Clip',
        ram_budget_mb=2048, available_ram_mb=8192, logical_cpus=4, preview_plan=True)
    plan = DrawBot.make_plan(source, (96, 72), opts)
    try:
        return comparable_plan(plan)
    finally:
        close_plan(plan, source)


def measure(repeats, *, verify_only):
    before = old_module('CanvasGuard', BASELINE)
    baseline_bytes = subprocess.check_output(['git', 'show', BASELINE+':CanvasGuard.py'], cwd=ROOT)
    hashes = source_hashes()
    report = {'baseline_commit': BASELINE, 'baseline_CanvasGuard_sha256': hashlib.sha256(baseline_bytes).hexdigest(),
              'python': sys.version.split()[0], 'platform': platform.platform(),
              'source_sha256': hashes, 'historical_parity': historical_parity(before),
              'scope': __doc__, 'repeats': 0 if verify_only else repeats,
              'public_plan_parity_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
              'method': 'Full historical CanvasGuard with all imported caller aliases linked. One warm pair, balanced AB/BA samples, separate traced Python peaks, and complete parity in counted/timed/traced calls. Current shared DrawBot and other caller bodies run identically on both sides. No native mouse, actual painting, GPU speed, process RSS or Pillow-native allocation claim.',
              'results': []}
    with no_execution_persistence(), calibrated(), closing(Image.new('RGB', (96, 72), 'white')) as source:
        paint = ImageDraw.Draw(source)
        for y in range(1, 71, 6):
            paint.line((0, y, 95, y), fill='black', width=1)
            paint.rectangle((7+(y % 11), y, 18+(y % 11), min(71, y+3)), fill='black')
        workloads = (
            ('clip-path-rectangle-2048', lambda module: module.clip_path_to_polygon(LONG_PATH, RECTANGLE)),
            ('clip-path-concave-2048', lambda module: module.clip_path_to_polygon(LONG_PATH, CONCAVE)),
            ('clip-path-thin-projection-512', lambda module: module.clip_path_to_polygon(THIN_PATH, ((0, 0), (10, 0), (0, 3)))),
            ('clip-path-short-1000', lambda module: tuple(module.clip_path_to_polygon(((10, 20), (90, 20)), RECTANGLE) for _ in range(1000))),
            ('validated-guard-path-2048', lambda module: module.CanvasGuard.from_area((100, 100, 96, 96), brush_px=2).clip_path_to_safe_subpaths(SAFE_PATH)),
            ('actual-preview-safety-8-compound-paths', lambda module: preview_workload()),
            ('actual-execute-plan-8-compound-paths', lambda module: execution_workload(DrawBot.execute_plan)),
            ('public-pixel-plan-96x72', lambda module: public_plan(source)),
        )
        for name, operation in workloads:
            def run(module):
                with linked_geometry(module):
                    return operation(module)
            old_result, old_work = caller_work(before, lambda: run(before))
            new_result, new_work = caller_work(current, lambda: run(current))
            if new_result != old_result:
                raise AssertionError('Actual caller parity failed: '+name)
            row = {'case': name, 'before_work': old_work, 'after_work': new_work,
                   'exact_output_parity': True, 'output_sha256': digest(old_result)}
            del old_result, new_result
            if not verify_only:
                row.update(paired(lambda: run(before), lambda: run(current), repeats))
            report['results'].append(row)
            print(name, old_work['total'], '->', new_work['total'], 'point validations', flush=True)
    if not verify_only and hashes != source_hashes():
        raise AssertionError('Source files changed during measurement.')
    report['sources_unchanged'] = hashes == source_hashes()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch21-clipping-benchmarks.json')
    args = parser.parse_args()
    if args.repeats < 2 or args.repeats % 2:
        parser.error('Use an even number of paired samples, at least two.')
    report = measure(args.repeats, verify_only=args.verify_only)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print('Historical comparisons:', report['historical_parity']['total'])


if __name__ == '__main__':
    main()
