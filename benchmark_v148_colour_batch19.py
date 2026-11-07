"""Compare complete historical region/color modules through actual callers.

Use --verify-only during review. Timings require a coordinated quiet window;
six balanced AB/BA pairs and separate traced peaks keep the evidence bounded.
"""
import argparse
from collections import Counter
from contextlib import closing
from dataclasses import asdict
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

import DrawBot
import DynamicColors as dynamic
import PictureCustomPaletteLegacy as picture
import RegionAwareQuantization as regions
from benchmark_v148_image_workflow import fingerprint, old_module
from benchmark_v148_stroke_optimizer import paired
from test_v148_colour_batch19_regions import (PALETTE, dynamic_settings,
    membership_fixture, public_settings, region_graphic)
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated, drawn_labels


ROOT = Path(__file__).resolve().parent
BASELINE = '7f41c7ee8c4b69f750008bd2d83349d186396fd1'


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def comparable(value, path=()):
    if isinstance(value, dict):
        return {key: comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


def historical_modules(revision):
    old_regions = old_module('RegionAwareQuantization', revision)
    old_dynamic = old_module('DynamicColors', revision)
    # The whole old reducer must use its own whole old region implementation.
    # No new prepared keyword or current arithmetic enters the baseline.
    for name in ('build_region_context', 'cluster_region_relation', 'merge_threshold_multiplier'):
        setattr(old_dynamic, name, getattr(old_regions, name))
    return old_dynamic, old_regions


def historical_parity(old):
    counts = Counter()
    hashes = []
    for serial, (size, mode, fidelity, limit) in enumerate(itertools.product(
            ((1, 17), (19, 1), (23, 17)), ('RGBA', 'RGB', 'P'),
            ('Fast', 'Balanced', 'Faithful', 'Exact'), (1, 8))):
        with closing(region_graphic(size)) as original, closing(original.convert(mode)) as source, \
                closing(Image.new('L', size, 0)) as protected:
            protected.paste(255, (0, 0, max(1, size[0]//3), max(1, size[1]//3)))
            if mode == 'P':
                source.info['transparency'] = bytes(range(256))
            source.info['fixture'] = 'borrowed batch19 source'
            state = source.tobytes(), dict(source.info)
            settings = dict(max_colors=limit, skip_white=bool(serial % 2),
                lines=bool((serial//2) % 2), exact_available=bool(serial % 3),
                source_palette=bool(serial % 4), color_fidelity=fidelity,
                profile_name='Microsoft Paint' if serial % 2 else 'Skribbl',
                protected_mask=protected if serial % 3 else None)
            expected = old.build_dynamic_color_strokes(source, PALETTE, **settings)
            actual = dynamic.build_dynamic_color_strokes(source, PALETTE, **settings)
            if expected != actual:
                raise AssertionError(('Complete historical color mismatch', size, mode, fidelity, limit))
            if (source.tobytes(), source.info) != state:
                raise AssertionError('A reducer modified its borrowed source.')
            hashes.append(digest(actual)); counts['complete_dynamic_pairs'] += 1
            if mode == 'RGBA':
                drawn_labels(source, actual[0], skip_white=settings['skip_white'])
                counts['independent_drawable_rasters'] += 1

    for seed, limit, context_kind in itertools.product((1481901, 1481902), (1, 2, 5, 8),
                                                      ('full', 'partial', 'absent')):
        entries, context = membership_fixture()
        rng = np.random.default_rng(seed)
        rng.shuffle(entries)
        for entry in entries:
            entry['count'] += int(rng.integers(0, 31))
        if context_kind == 'partial':
            context['stats'] = {key: row for key, row in context['stats'].items() if key % 2}
        elif context_kind == 'absent':
            context = None
        old_diagnostics, diagnostics = {}, {}
        expected = old._merge_quantized(entries, limit, region_context=context,
                                        diagnostics=old_diagnostics)
        actual = dynamic._merge_quantized(entries, limit, region_context=context,
                                           diagnostics=diagnostics)
        if actual != expected or diagnostics != old_diagnostics:
            raise AssertionError(('Complete historical merge mismatch', seed, limit, context_kind))
        hashes.append(digest((actual, diagnostics))); counts['complete_merge_pairs'] += 1
    return dict(counts, complete_output_sha256=digest(hashes))


def observe_work(region_module, operation):
    counts = Counter()
    weighted = region_module._weighted_stats
    def observed(items, context):
        key = tuple((int(item.get('qindex', -1)), float(item.get('count', 0))) for item in items)
        counts[key] += 1
        return weighted(items, context)
    with patch.object(region_module, '_weighted_stats', new=observed):
        result = operation()
    return {'weighted_stat_calculations': sum(counts.values()),
            'distinct_ordered_membership_states': len(counts),
            'maximum_rebuilds_of_one_state': max(counts.values(), default=0),
            'output_sha256': digest(result)}


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two.')
    old, old_regions = historical_modules(revision)
    sources = source_hashes()
    report = {'baseline': revision, 'historical_module_sha256': {
        name: hashlib.sha256(subprocess.check_output(['git', 'show', revision+':'+name+'.py'], cwd=ROOT)).hexdigest()
        for name in ('DynamicColors', 'RegionAwareQuantization')},
        'source_sha256': sources, 'python': sys.version.split()[0],
        'platform': platform.platform(), 'numpy': np.__version__, 'pillow': pillow_version,
        'verify_only': verify_only, 'repeats': None if verify_only else repeats,
        'method': 'One warm/parity pair, six balanced AB/BA timing pairs, then independent tracemalloc probes after garbage collection. Work counts run separately.',
        'isolation': 'Complete historical DynamicColors and RegionAwareQuantization modules, linked together. Public planners and all unrelated dependencies are current on both sides. Picture cache load/save and hardware probes are controlled identically.',
        'timing_scope': 'CPU region/color planning, complete result fingerprinting and owned-plan cleanup. No physical input, target-app drawing, native GPU, network or GUI timing.',
        'memory_scope': 'Python/NumPy traced peaks. This excludes process RSS and most native Pillow cores. Private region snapshots are bounded by the temporary quantizer palette and explicitly cleared.',
        'public_plan_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
        'historical_parity': historical_parity(old), 'measurements': {}}

    def compare(left, right):
        if not verify_only:
            return paired(left, right, repeats)
        expected = left()
        if right() != expected:
            raise AssertionError('Complete caller output parity failed.')
        return {'exact_output_parity': True, 'output_sha256': digest(expected)}

    workloads = (('dynamic_strokes_small', 'strokes', (96, 72), None),
                 ('dynamic_strokes_large', 'strokes', (384, 288), None),
                 ('dynamic_palette_large', 'palette', (384, 288), None),
                 ('make_plan_standard', 'plan', (384, 288), 'Standard'),
                 ('make_plan_high', 'plan', (384, 288), 'High'),
                 ('picture_palette', 'picture', (192, 144), None))
    with calibrated(PALETTE), patch('ResourceAllocation.available_ram_mb', return_value=8192), \
            patch('ResourceAllocation.logical_cpu_count', return_value=8), \
            patch.object(picture, 'load_cached_palette', return_value=None), \
            patch.object(picture, 'save_palette'):
        for name, kind, size, resolution in workloads:
            with closing(region_graphic(size)) as source:
                source_state = source.tobytes(), dict(source.info)
                settings = public_settings() if kind == 'plan' else dynamic_settings()
                if resolution:
                    settings['planning_resolution'] = resolution
                def operation(module):
                    if kind == 'plan':
                        with patch.object(DrawBot, 'build_dynamic_color_strokes',
                                          new=module.build_dynamic_color_strokes):
                            result = DrawBot.make_plan(source, source.size, dict(settings))
                        try:
                            if result['options']['planning_resolution_effective'] != resolution:
                                raise AssertionError('The public planner did not enter the requested resolution.')
                            return comparable(result)
                        finally:
                            close_plan(result, source)
                    if kind == 'picture':
                        with patch.object(dynamic, 'build_dynamic_color_palette',
                                          new=module.build_dynamic_color_palette):
                            return fingerprint(asdict(picture.build_picture_palette(source, PALETTE,
                                max_colors=8, fidelity='Faithful', calibration_fingerprint='batch19-benchmark')))
                    builder = module.build_dynamic_color_palette if kind == 'palette' else module.build_dynamic_color_strokes
                    return fingerprint(builder(source, PALETTE, **settings))
                left, right = lambda: operation(old), lambda: operation(dynamic)
                row = compare(left, right)
                row['before_work'] = observe_work(old_regions, left)
                row['after_work'] = observe_work(regions, right)
                if any(row[side+'_work']['output_sha256'] != row['output_sha256'] for side in ('before', 'after')):
                    raise AssertionError('Work observations changed the complete result.')
                if (source.tobytes(), source.info) != source_state:
                    raise AssertionError('A public caller modified its borrowed source.')
                row['parameters'] = {'source_size': list(size), 'kind': kind,
                    'palette': PALETTE, 'options': settings,
                    'fixture': 'Seeded tiled RGB with transparent/partial alpha and white corner'}
                report['measurements'][name] = row
    if source_hashes() != sources:
        raise AssertionError('Source changed during comparison; coordinate and rerun.')
    report['source_unchanged_during_measurement'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch19-colour-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'historical_parity': result['historical_parity'],
        'workloads': len(result['measurements']), 'output': str(args.output),
        'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}, indent=2))
