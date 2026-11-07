"""Measure bounded row payloads and repeated initial brush scoring.

Use --verify-only during correctness work. Coordinate a quiet source/CPU window
for six balanced AB/BA pairs, then separate traced allocation probes. Complete
historical modules run through the same current public planner dependencies.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import itertools
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

import AdaptiveRegionHybrid as regional
import AdvancedColor
import DrawBot
import PixelData
from ExecutionCostModel import build_cost_model
from NativeBrushProjection import NativeBrushProjection
from benchmark_v148_image_workflow import fingerprint, old_module
from benchmark_v148_stroke_optimizer import paired
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_candidates import component
from test_v148_rendering_batch10_physical import physical_options, replay_executor
from test_v148_rendering_batch11_pack_choice import BLUE, FIXTURES
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated
from test_v148_rendering_batch18_pack_scores import CountedLabels
from test_v148_rendering_batch18_row_payloads import graphic, public_options, dispatch_observations, copied_images


ROOT = Path(__file__).resolve().parent
BASELINE = 'd7721a36975a36137b583beda9ff3c47c05208fd'
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


def color_call(module, kind, source, *, lines=True, skip=False, workers=1,
               rendering='Layered color mix', layers='Full color mix'):
    common = dict(lines=lines, skip_white=skip, cpu_workers=workers,
                  cpu_engine='Threads')
    if kind == 'basic':
        return module.build_strokes(source, **common)
    return module.build_color_strokes(source, color_rendering=rendering,
        color_layers=layers, color_fidelity='Balanced', gpu_mode='CPU', **common)


def historical_parity(before):
    counts = Counter()
    hashes = []
    modules = {'basic': ('PixelData', PixelData), 'advanced': ('AdvancedColor', AdvancedColor)}
    with calibrated():
        for seed, size in itertools.product((1481801, 1481802), ((1, 17), (19, 1), (23, 17))):
            rng = np.random.default_rng(seed)
            data = rng.integers(0, 256, (size[1], size[0], 4), np.uint8)
            data[::3, :, 3] = 0
            data[1::3, :, 3] = 255
            with closing(Image.fromarray(data)) as original:
                for mode in ('RGBA', 'RGB', 'L', 'LA', 'P', 'RGBa'):
                    with closing(original.convert(mode)) as source:
                        if mode == 'P':
                            source.info['transparency'] = bytes(range(256))
                        source.info['fixture_marker'] = 'borrowed metadata'
                        state = source.tobytes(), dict(source.info)
                        for kind, lines, skip in itertools.product(modules, (False, True), (False, True)):
                            name, current = modules[kind]
                            expected = color_call(before[name], kind, source, lines=lines, skip=skip)
                            actual = color_call(current, kind, source, lines=lines, skip=skip)
                            if actual != expected:
                                raise AssertionError(('Historical reader mismatch', kind, seed, size, mode, lines, skip))
                            if state != (source.tobytes(), source.info):
                                raise AssertionError('A color reader mutated borrowed source state.')
                            hashes.append(digest(actual)); counts['serial_reader_pairs'] += 1
        with closing(graphic()) as source:
            for kind, workers in itertools.product(modules, (1, 2)):
                name, current = modules[kind]
                expected = color_call(before[name], kind, source, workers=workers)
                actual = color_call(current, kind, source, workers=workers)
                if actual != expected:
                    raise AssertionError('Historical serial/real-thread result mismatch.')
                hashes.append(digest(actual)); counts['large_reader_pairs'] += 1
            for rendering, layers in (('RGB nearest', 'Off'), ('Perceptual match', 'Off'),
                    ('Layered color mix', 'Off'), ('Layered color mix', 'Light shading'),
                    ('Layered color mix', 'Dual-color mix')):
                expected = color_call(before['AdvancedColor'], 'advanced', source, workers=2,
                                      rendering=rendering, layers=layers)
                actual = color_call(AdvancedColor, 'advanced', source, workers=2,
                                    rendering=rendering, layers=layers)
                if actual != expected:
                    raise AssertionError('Historical nonlayered/layered thread metadata mismatch.')
                hashes.append(digest(actual)); counts['large_reader_pairs'] += 1

    for seed, shape, pattern, scale in itertools.product((1481802, 1481803),
            ((24, 32), (32, 48)), ('rectangle', 'hole', 'ragged'), (1, 2)):
        height, width = shape
        labels = np.ones(shape, np.int32)
        if pattern == 'hole':
            labels[height//3:2*height//3, width//3:2*width//3] = -1
        elif pattern == 'ragged':
            cuts = np.random.default_rng(seed).integers(0, 5, height)
            for y, length in enumerate(cuts):
                labels[y, :length] = -1
        labels.flags.writeable = False
        comp = component(shape); comp.area = int(np.count_nonzero(labels == 1))
        size, area = (width, height), (width*scale, height*scale)
        options = physical_options((100, 100), area, delay=.02 if seed % 2 else .005)
        model = build_cost_model(options, size, area)
        projection = NativeBrushProjection(size, area, options) if scale != 1 else None
        expected = before['AdaptiveRegionHybrid']._brush_pack_candidate(comp, labels, options, model,
                                                                       projection=projection)
        actual = regional._brush_pack_candidate(comp, labels, options, model, projection=projection)
        if actual != expected:
            raise AssertionError(('Historical complete pack mismatch', seed, shape, pattern, scale))
        hashes.append(digest(fingerprint(actual))); counts['complete_pack_pairs'] += 1
    return dict(counts, complete_output_sha256=digest(hashes))


def observed_pack(module, operation):
    erode, components = module._eroded_centers, module.connected_components
    calls, scans = Counter(), []
    def erosion(target, brush, **kwargs):
        calls[str(brush)] += 1
        return erode(target, brush, **kwargs)
    def labels(*args, **kwargs):
        comps, cmap, meta = components(*args, **kwargs)
        counted = cmap.view(CountedLabels)
        counted.full_scans = scans
        return comps, counted, meta
    with patch.object(module, '_eroded_centers', new=erosion), \
            patch.object(module, 'connected_components', new=labels):
        output = operation()
    return {'erosions_by_brush': dict(calls), 'full_canvas_drawable_scans': len(scans),
            'full_canvas_scan_shapes': scans, 'output_sha256': digest(output)}


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA pairs.')
    names = ('AdvancedColor', 'PixelData', 'AdaptiveRegionHybrid')
    before = {name: old_module(name, revision) for name in names}
    sources = source_hashes()
    report = {'baseline': revision, 'historical_module_sha256': {
        name: hashlib.sha256(subprocess.check_output(['git', 'show', revision+':'+name+'.py'], cwd=ROOT)).hexdigest()
        for name in names}, 'source_sha256': sources, 'python': sys.version.split()[0],
        'platform': platform.platform(), 'numpy': np.__version__, 'pillow': pillow_version,
        'verify_only': verify_only, 'repeats': None if verify_only else repeats,
        'isolation': 'Complete historical reader/packing modules are substituted separately. Public make_plan and all unrelated dependencies are current on both sides. No historical helper runs with new private keyword arguments.',
        'method': 'One warm/parity pair, balanced AB/BA timing pairs, and separate tracemalloc peaks after garbage collection; every result has exact complete-output parity. Work observations and native-input replay run separately from timing.',
        'timing_scope': 'CPU planning, complete-output fingerprinting and owned-image cleanup. No physical drawing, GPU, GUI or network timing.',
        'memory_scope': 'Python/NumPy traced peaks, excluding process RSS, most native Pillow cores and child-process heaps. Eager producer payload bytes and fullsize conversion counts are separate lifetime observations.',
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

    with calibrated(), patch('ResourceAllocation.available_ram_mb', return_value=8192), \
            patch('ResourceAllocation.logical_cpu_count', return_value=8):
        for kind, name, current in (('basic', 'PixelData', PixelData), ('advanced', 'AdvancedColor', AdvancedColor)):
            with closing(graphic((768, 512))) as source:
                def reader(module):
                    return fingerprint(color_call(module, kind, source, workers=4))
                left, right = lambda: reader(before[name]), lambda: reader(current)
                row = compare(left, right)
                for side, operation in (('before', left), ('after', right)):
                    with dispatch_observations() as dispatch, copied_images(source.size) as copies:
                        actual = operation()
                    row[side+'_work'] = {'dispatch': dispatch, 'fullsize_private_images': len(copies),
                                        'nominal_private_rgba_bytes': len(copies)*source.width*source.height*4}
                    if digest(actual) != row['output_sha256']:
                        raise AssertionError('Observed reader output changed.')
                    for image in copies:
                        image.close()
                row['parameters'] = {'source_size': list(source.size), 'workers': 4, 'engine': 'Threads',
                                     'fixture': 'graphic RGBA with hidden and partial alpha'}
                report['measurements']['R1801_'+kind+'_reader'] = row

                for resolution in ('High', 'Ultra'):
                    settings = public_options(kind, resolution)
                    attribute = 'build_strokes' if kind == 'basic' else 'build_color_strokes'
                    def public(module):
                        with patch.object(DrawBot, attribute, new=getattr(module, attribute)):
                            plan = DrawBot.make_plan(source, source.size, dict(settings))
                        try:
                            return comparable(plan)
                        finally:
                            close_plan(plan, source)
                    left, right = lambda: public(before[name]), lambda: public(current)
                    row = compare(left, right)
                    for side, operation in (('before', left), ('after', right)):
                        with dispatch_observations() as dispatch:
                            actual = operation()
                        row[side+'_dispatch'] = dispatch
                        if digest(actual) != row['output_sha256']:
                            raise AssertionError('Observed public reader plan changed.')
                    row['parameters'] = {'source_size': list(source.size), 'canvas_size': list(source.size),
                                         'options': settings}
                    report['measurements']['R1801_'+kind+'_make_plan_'+resolution.lower()] = row

    fixtures = [(name, size, area, [box]) for name, (size, area, box) in FIXTURES.items()]
    with patch('DrawTimeCalibration.load_profile', return_value=None), \
            patch('ResourceAllocation.available_ram_mb', return_value=8192), \
            patch('ResourceAllocation.logical_cpu_count', return_value=8):
        for name, size, area, boxes in fixtures:
            with closing(Image.new('RGB', size, 'white')) as source:
                draw = ImageDraw.Draw(source)
                for box in boxes:
                    draw.rectangle(box, fill=BLUE)
                del draw
                settings = physical_options((100, 100), area)
                def public(module, prove_native=False):
                    with patch.object(regional, 'build_adaptive_hybrid_plan', new=module.build_adaptive_hybrid_plan):
                        plan = DrawBot.make_plan(source, area, dict(settings))
                    try:
                        result = comparable(plan)
                        if prove_native:
                            pixels, selected = replay_executor(plan, (100, 100), area)
                            expected = np.full((area[1], area[0]), -1, np.int32)
                            sx, sy = area[0]//size[0], area[1]//size[1]
                            for x0, y0, x1, y1 in boxes:
                                expected[y0*sy:(y1+1)*sy, x0*sx:(x1+1)*sx] = plan['colors'].index(BLUE)
                            np.testing.assert_array_equal(pixels, expected)
                            if not set(selected) <= {2, 4, 8, 16}:
                                raise AssertionError('Unexpected native brush selection.')
                        return result
                    finally:
                        close_plan(plan, source)
                old = before['AdaptiveRegionHybrid']
                current_public = regional.build_adaptive_hybrid_plan
                # The current function is saved because patch.object changes the
                # module attribute while historical calls execute.
                left = lambda: public(old)
                right = lambda: public(regional)
                if public(old, True) != public(regional, True):
                    raise AssertionError('Native-verified public pack changed complete output.')
                row = compare(left, right)
                row['before_work'] = observed_pack(old, left)
                row['after_work'] = observed_pack(regional, right)
                if row['before_work']['output_sha256'] != row['output_sha256'] or \
                        row['after_work']['output_sha256'] != row['output_sha256']:
                    raise AssertionError('Observed pack changed complete output.')
                if regional.build_adaptive_hybrid_plan is not current_public:
                    raise AssertionError('Public substitution was not restored.')
                row.update(parameters={'source_size': size, 'canvas_size': area, 'boxes': boxes,
                                       'options': settings}, independent_native_raster_parity=True)
                report['measurements']['R1802_make_plan_'+name] = row

    if source_hashes() != sources:
        raise AssertionError('Source changed during the comparison; coordinate and rerun.')
    report['source_unchanged_during_measurement'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch18-rendering-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'historical_parity': result['historical_parity'],
                      'measurement_pairs': len(result['measurements']), 'output': str(args.output),
                      'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}, indent=2))
