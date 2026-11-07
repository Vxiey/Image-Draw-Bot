"""Verify shared color-source analysis against four complete historical modules.

Use --verify-only while reviewing correctness. Timing requires a coordinated
quiet window: six balanced AB/BA pairs, followed by separate traced peaks.
Pillow operation/lifetime observations run outside the timing/allocation probes.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
from dataclasses import asdict, is_dataclass
import hashlib
import itertools
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import ColorMatchingEngine as measurement
import DrawBot
import DynamicColors as dynamic
import PictureCustomPalette as picture_frontend
import PictureCustomPaletteLegacy as picture
import RegionAwareQuantization as regions
from benchmark_v148_image_workflow import fingerprint, old_module
from benchmark_v148_stroke_optimizer import paired
from test_v148_colour_batch19_regions import PALETTE, dynamic_settings, public_settings, region_graphic
from test_v148_colour_batch20_source_analysis import (SOURCE_VARIANTS, image_is_open,
    image_operations, operation_summary, source_variant)
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated, drawn_labels


ROOT = Path(__file__).resolve().parent
BASELINE = '47777158e5b1daf759993190e638fe507e7691da'
NAMES = ('ColorMatchingEngine', 'RegionAwareQuantization', 'DynamicColors', 'PictureCustomPaletteLegacy')
CURRENT = dict(zip(NAMES, (measurement, regions, dynamic, picture)))


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def comparable(value, path=()):
    if is_dataclass(value):
        return comparable(asdict(value), path)
    if isinstance(value, dict):
        return {key if isinstance(key, str) else repr((type(key).__name__, key)):
                comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


def historical_modules(revision):
    old = {}
    # Import each whole historical module with its earlier historical
    # dependencies already installed. DynamicColors therefore binds all four
    # old region helpers and both old source-measurement helpers at import time.
    for name in NAMES:
        with patch.dict(sys.modules, old):
            old[name] = old_module(name, revision)
    return old


@contextmanager
def linked(modules):
    # The legacy picture planner imports the source and dynamic helpers locally;
    # the stable frontend retains a module reference. Bind both paths, not just
    # the direct reducer, so baseline picture/public plans cannot mix versions.
    with patch.dict(sys.modules, modules), \
            patch.object(picture_frontend, '_legacy', modules['PictureCustomPaletteLegacy']), \
            patch.object(modules['PictureCustomPaletteLegacy'], 'load_cached_palette', return_value=None), \
            patch.object(modules['PictureCustomPaletteLegacy'], 'save_palette'):
        yield


def historical_parity(old):
    counts, hashes = Counter(), []
    cases = itertools.product(((1, 17), (19, 1), (23, 17)), SOURCE_VARIANTS, (False, True), (False, True))
    for serial, (size, variant, skip, lines) in enumerate(cases):
        with closing(region_graphic(size)) as original, source_variant(original, variant) as source, \
                closing(Image.new('L', size, 0)) as protected:
            protected.paste(255, (0, 0, max(1, size[0]//3), max(1, size[1]//3)))
            state = source.tobytes(), dict(source.info)
            settings = dict(max_colors=1 if serial % 3 == 0 else 8, skip_white=skip,
                lines=lines, exact_available=bool(serial % 3), source_palette=bool(serial % 4),
                color_fidelity=('Fast', 'Balanced', 'Faithful', 'Exact')[(serial//2) % 4],
                profile_name='Microsoft Paint' if serial % 2 else 'Skribbl',
                protected_mask=protected if serial % 3 else None)
            outputs = []
            for modules in (old, CURRENT):
                with linked(modules):
                    outputs.append(comparable(modules['DynamicColors'].build_dynamic_color_strokes(
                        source, PALETTE, **settings)))
            if outputs[0] != outputs[1]:
                raise AssertionError(('Complete historical color mismatch', size, variant, skip, lines))
            if (source.tobytes(), source.info) != state:
                raise AssertionError('A planner modified borrowed source pixels or metadata.')
            hashes.append(digest(outputs[1])); counts['complete_dynamic_pairs'] += 1
            if variant == 'RGBA':
                drawn_labels(source, outputs[1][0], skip_white=skip)
                counts['independent_drawable_rasters'] += 1

    with closing(region_graphic((23, 17))) as original:
        for variant in SOURCE_VARIANTS:
            with source_variant(original, variant) as source, \
                    closing(Image.fromarray((np.arange(23*17).reshape(17, 23) % 5).astype(np.uint8))) as labels:
                entries = [dict(qindex=i, rgb=PALETTE[i], count=70+i) for i in range(5)]
                for kind in ('palette', 'measurement', 'region'):
                    outputs = []
                    for modules in (old, CURRENT):
                        with linked(modules):
                            if kind == 'palette':
                                result = modules['DynamicColors'].build_dynamic_color_palette(
                                    source, PALETTE, **dynamic_settings())
                            elif kind == 'measurement':
                                result = modules['ColorMatchingEngine'].measure_quantized_regions(source, labels)
                            else:
                                # A direct RGBA region caller keeps its historical
                                # convert('RGB') semantics, without compositing.
                                result = modules['RegionAwareQuantization'].build_region_context(source, labels, entries)
                            outputs.append(comparable(result))
                    if outputs[0] != outputs[1]:
                        raise AssertionError(('Complete historical helper mismatch', variant, kind))
                    hashes.append(digest(outputs[1])); counts['complete_'+kind+'_pairs'] += 1
    return dict(counts, complete_output_sha256=digest(hashes))


def observe_work(modules, operation):
    observations = []
    module = modules['DynamicColors']
    real = module.build_dynamic_color_strokes
    def observed(image, *args, **kwargs):
        with image_operations((image,)) as events:
            result = real(image, *args, **kwargs)
            unique = {id(row['image']): row['image'] for row in events}
            observations.append({'source_mode': image.mode, 'source_size': list(image.size),
                'fullsize_pillow_operations': operation_summary(events, image.size),
                'unique_private_image_results': len(unique),
                'private_results_open_at_return': sum(image_is_open(value) for value in unique.values()),
                'created_logical_pixel_bytes': sum(value.width*value.height*len(value.getbands())
                    for value in unique.values())})
            return result
    with patch.object(module, 'build_dynamic_color_strokes', new=observed):
        output = operation()
    if not observations:
        raise AssertionError('The workload did not enter the real dynamic source planner.')
    return {'dynamic_source_calls': observations, 'output_sha256': digest(output)}


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two.')
    old = historical_modules(revision)
    sources = source_hashes()
    report = {'baseline': revision, 'historical_module_sha256': {
        name: hashlib.sha256(subprocess.check_output(['git', 'show', revision+':'+name+'.py'], cwd=ROOT)).hexdigest()
        for name in NAMES}, 'source_sha256': sources, 'python': sys.version.split()[0],
        'platform': platform.platform(), 'numpy': np.__version__, 'pillow': pillow_version,
        'verify_only': verify_only, 'repeats': None if verify_only else repeats,
        'method': 'One warm/parity pair, six balanced AB/BA timing pairs, then separate tracemalloc probes after garbage collection. Pillow work/lifetime observations run separately.',
        'isolation': 'Four complete historical source/color/region/picture modules are linked together, including local imports and the stable picture frontend. Current public planners and unrelated dependencies are identical on both sides. Palette-cache reads/writes and hardware probes are controlled.',
        'timing_scope': 'CPU source/color planning, complete result fingerprinting and plan cleanup. No physical drawing, native GPU, GUI, network or application-throughput timing.',
        'memory_scope': 'Python/NumPy traced peaks, excluding process RSS and most native Pillow cores. created_logical_pixel_bytes is the cumulative pixel payload of unique observed image results, not a native allocation or peak estimate. Work observers deliberately retain wrappers and never run during timing/tracing.',
        'public_plan_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
        'resource_probe_controls': {'available_ram_mb': 8192, 'logical_cpu_count': 8},
        'historical_parity': historical_parity(old), 'measurements': {}}

    def compare(left, right):
        if not verify_only:
            return paired(left, right, repeats)
        expected = left()
        if right() != expected:
            raise AssertionError('Complete caller output parity failed.')
        return {'exact_output_parity': True, 'output_sha256': digest(expected)}

    workloads = (('dynamic_strokes_small', 'strokes', (96, 72), None),
                 ('dynamic_strokes_large', 'strokes', (640, 480), None),
                 ('dynamic_palette_large', 'palette', (640, 480), None),
                 ('make_plan_standard', 'plan', (96, 72), 'Standard'),
                 ('make_plan_high', 'plan', (96, 72), 'High'),
                 ('make_plan_ultra', 'plan', (96, 72), 'Ultra'),
                 ('picture_palette', 'picture', (192, 144), None),
                 ('make_plan_pixel_picture', 'pixel', (96, 72), 'Standard'))
    with calibrated(PALETTE), patch('ResourceAllocation.available_ram_mb', return_value=8192), \
            patch('ResourceAllocation.logical_cpu_count', return_value=8):
        for name, kind, size, resolution in workloads:
            with closing(region_graphic(size)) as source:
                state = source.tobytes(), dict(source.info)
                settings = public_settings() if kind in ('plan', 'pixel') else dynamic_settings()
                area = (600, 450) if kind == 'plan' else source.size
                if resolution:
                    settings.update(planning_resolution=resolution, cpu_workers='4', cpu_workers_resolved=4)
                if kind == 'pixel':
                    settings.update(draw_quality='Pixel Accurate', color_rendering='Perceptual match')
                def operation(modules):
                    with linked(modules):
                        if kind in ('plan', 'pixel'):
                            with patch.object(DrawBot, 'build_dynamic_color_strokes',
                                    new=modules['DynamicColors'].build_dynamic_color_strokes):
                                result = DrawBot.make_plan(source, area, dict(settings))
                            try:
                                effective = 'Pixel Accurate / full target' if kind == 'pixel' else resolution
                                if result['options']['planning_resolution_effective'] != effective:
                                    raise AssertionError(('Unexpected public planning resolution', name, effective,
                                        result['options']['planning_resolution_effective']))
                                if kind == 'pixel' and result['options']['picture_palette_meta']['source'] != 'image-rgb-palette':
                                    raise AssertionError('The public Pixel plan did not build a picture palette.')
                                return comparable(result)
                            finally:
                                close_plan(result, source)
                        if kind == 'picture':
                            return comparable(picture_frontend.build_picture_palette(source, PALETTE,
                                max_colors=8, fidelity='Faithful', calibration_fingerprint='batch20-benchmark'))
                        builder = (modules['DynamicColors'].build_dynamic_color_palette if kind == 'palette'
                            else modules['DynamicColors'].build_dynamic_color_strokes)
                        return comparable(builder(source, PALETTE, **settings))
                left, right = lambda: operation(old), lambda: operation(CURRENT)
                row = compare(left, right)
                row['before_work'] = observe_work(old, left)
                row['after_work'] = observe_work(CURRENT, right)
                if any(row[side+'_work']['output_sha256'] != row['output_sha256'] for side in ('before', 'after')):
                    raise AssertionError('Pillow observations changed the complete result.')
                if (source.tobytes(), source.info) != state:
                    raise AssertionError('A public caller changed its borrowed source.')
                row['parameters'] = {'source_size': list(size), 'canvas_size': list(area),
                    'kind': kind, 'palette': PALETTE, 'options': settings,
                    'fixture': 'Seeded tiled RGB with transparent/partial alpha and a white corner'}
                report['measurements'][name] = row
    if source_hashes() != sources:
        raise AssertionError('Root Python sources changed during verification/measurement.')
    report['source_manifest_sha256'] = digest(sources)
    report['source_unchanged'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch20-colour-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'historical_parity': result['historical_parity'],
        'source_manifest_sha256': result['source_manifest_sha256'], 'source_unchanged': result['source_unchanged'],
        'measurements': {name: {key: row[key] for key in ('exact_output_parity', 'output_sha256',
            'before_median_ms', 'after_median_ms', 'before_peak_python_bytes', 'after_peak_python_bytes') if key in row}
            for name, row in result['measurements'].items()}}, indent=2))
