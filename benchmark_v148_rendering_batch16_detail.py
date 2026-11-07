"""Compare detail-preview scratch use against the complete recorded module.

Use --verify-only during development. Coordinate a quiet source/CPU window
before the default six balanced AB/BA timing pairs and separate allocation
probes. All other public-planner dependencies remain current on both sides.
"""
import argparse
from contextlib import closing
import copy
import gc
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tracemalloc
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, __version__ as pillow_version

import DrawBot
import PreviewDetailEngine as detail
from benchmark_v148_image_workflow import fingerprint, old_module
from benchmark_v148_stroke_optimizer import paired
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_prepare import image_state
from test_v148_rendering_batch15_sketch_memory import (
    VOLATILE_PATHS, comparable_plan, graphic_source,
)
from test_v148_rendering_batch16_detail_memory import preview_settings


ROOT = Path(__file__).resolve().parent
BASELINE = 'd1a5e3a709745ee64263b5801cf1b9089cd6b707'


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def full_historical_parity(before):
    cases = 0
    for seed in (1481602, 1481603):
        rng = np.random.default_rng(seed)
        for source_size, target in (((1, 19), (1, 9)), ((17, 1), (7, 1)), ((53, 37), (19, 13))):
            pixels = rng.integers(0, 256, (source_size[1], source_size[0], 4), dtype=np.uint8)
            pixels[::3, :, 3] = 0
            pixels[1::3, :, 3] = 255
            pixels.flags.writeable = False
            with closing(Image.fromarray(pixels)) as original:
                for image_mode in ('RGBA', 'RGB', 'L', 'LA', 'P', 'RGBa'):
                    for orientation in (1, 6, 8):
                        with closing(original.convert(image_mode)) as source:
                            if image_mode == 'P':
                                source.info['transparency'] = bytes(range(256))
                            elif image_mode in ('RGB', 'L'):
                                source.info['transparency'] = source.getpixel((0, 0))
                            source.getexif()[274] = orientation
                            source.info['exif'] = source.getexif().tobytes()
                            source.info['fixture_marker'] = 'caller-owned metadata'
                            original_state = image_state(source)
                            for mode in detail.PREVIEW_DETAIL_MODES:
                                old_meta = {'retained': 7}; new_meta = dict(old_meta)
                                with closing(before.detail_aware_resize(source, target, mode, metadata=old_meta)) as expected, \
                                        closing(detail.detail_aware_resize(source, target, mode, metadata=new_meta)) as actual:
                                    if image_state(actual) != image_state(expected) or new_meta != old_meta:
                                        raise AssertionError('Complete historical RGBA/metadata parity failed.')
                                if image_state(source) != original_state:
                                    raise AssertionError('Caller source was mutated.')
                                cases += 1
                for mode in detail.PREVIEW_DETAIL_MODES:
                    old_meta = {}; new_meta = {}
                    with closing(before.detail_aware_resize_gray(original, target, mode, metadata=old_meta)) as expected, \
                            closing(detail.detail_aware_resize_gray(original, target, mode, metadata=new_meta)) as actual:
                        if image_state(actual) != image_state(expected) or new_meta != old_meta:
                            raise AssertionError('Complete historical grayscale/metadata parity failed.')
                    cases += 1
    with closing(graphic_source((30, 22))) as source:
        for cap, factor in ((25, 1), (100, 2), (225, 3)):
            with patch.object(before, '_MAX_OVERSAMPLED_PIXELS', cap), \
                    patch.object(detail, '_MAX_OVERSAMPLED_PIXELS', cap):
                old_meta = {}; new_meta = {}
                with closing(before.detail_aware_resize(source, (5, 5), 'Micro detail', metadata=old_meta)) as expected, \
                        closing(detail.detail_aware_resize(source, (5, 5), 'Micro detail', metadata=new_meta)) as actual:
                    if image_state(actual) != image_state(expected) or new_meta != old_meta:
                        raise AssertionError('Historical bounded-factor parity failed.')
                    if new_meta['preview_detail_oversample'] != factor:
                        raise AssertionError('The bounded factor was not exercised.')
            cases += 1
    return cases


def resized_signature(function, source, target, mode):
    metadata = {}
    with closing(function(source, target, mode, metadata=metadata)) as result:
        return {'image': fingerprint(result), 'metadata': metadata,
                'image_info': dict(result.info), 'exif_hex': result.getexif().tobytes().hex()}


def public_plan(function, source, area, mode, outline, *, observe=None):
    settings = preview_settings(mode, outline=outline)
    def resize(*args, **kwargs):
        if observe is not None:
            observe.append({'source_size': list(args[0].size), 'target_size': list(args[1]),
                            'mode': args[2]})
        return function(*args, **kwargs)
    with patch.object(detail, 'detail_aware_resize', new=resize):
        plan = DrawBot.make_plan(source, area, copy.deepcopy(settings))
    try:
        return comparable_plan(plan)
    finally:
        close_plan(plan, source)


def public_historical_parity(before):
    rows = []
    with closing(graphic_source((96, 72))) as source, \
            patch('DrawTimeCalibration.load_profile', return_value=None), \
            patch('DrawBot.custom_rgb_available', return_value=False):
        original = image_state(source)
        current_resize = detail.detail_aware_resize
        for mode in ('Detailed', 'Micro detail'):
            for outline in (False, True):
                calls = []
                expected = public_plan(before.detail_aware_resize, source, (64, 48), mode, outline)
                actual = public_plan(current_resize, source, (64, 48), mode, outline, observe=calls)
                if actual != expected or len(calls) != 1:
                    raise AssertionError('Complete historical public preview plan parity failed.')
                rows.append({'mode': mode, 'outline': outline, 'paths': actual['count'], 'resize_calls': calls,
                             'complete_output_parity': True})
        if image_state(source) != original:
            raise AssertionError('Public planner mutated source.')
    return rows


def numeric_observation(module, source, target, mode):
    """Observe named arrays separately; never retain their storage in a result."""
    argmax = np.argmax; where = np.where
    extreme = module._cell_extreme
    references = []; selection = []; output = []
    def record(rgb, base_rgb, *args):
        references.extend((weakref.ref(rgb), weakref.ref(base_rgb)))
        result = extreme(rgb, base_rgb, *args)
        references.extend(weakref.ref(value) for value in result)
        return result
    def inspect_argmax(*args, **kwargs):
        frame = sys._getframe(1)
        if frame.f_code is extreme.__code__:
            arrays = {name: value for name, value in frame.f_locals.items() if isinstance(value, np.ndarray)}
            rgb = frame.f_locals['rgb']
            copies = [value.nbytes for value in arrays.values() if value.ndim == 4 and value.shape[-1] == 3
                      and value.size == rgb.size and not np.shares_memory(value, rgb)]
            selection.append({'factor': frame.f_locals['factor'], 'oversampled_rgb_shape': list(rgb.shape),
                              'copied_rgb_cell_bytes': sum(copies),
                              'named_arrays': {name: {'shape': list(value.shape), 'dtype': str(value.dtype),
                                                     'bytes': value.nbytes} for name, value in arrays.items()}})
        return argmax(*args, **kwargs)
    def inspect_where(*args, **kwargs):
        frame = sys._getframe(1)
        if frame.f_code is module._detail_aware_resize.__code__:
            arrays = {name: value for name, value in frame.f_locals.items() if isinstance(value, np.ndarray)}
            output.append({'live_selection_arrays': sum(reference() is not None for reference in references),
                           'named_arrays': {name: {'shape': list(value.shape), 'dtype': str(value.dtype),
                                                  'bytes': value.nbytes} for name, value in arrays.items()}})
        return where(*args, **kwargs)
    with patch.object(module, '_cell_extreme', new=record), \
            patch.object(np, 'argmax', new=inspect_argmax), patch.object(np, 'where', new=inspect_where):
        signature = resized_signature(module.detail_aware_resize, source, target, mode)
    return {'selection': selection, 'straight_alpha_output': output}, signature


def allocation_only(before):
    """A separate, untimed allocation check for development/review."""
    with closing(graphic_source((960, 720))) as source:
        rows = {}; expected = None
        for name, module in (('before', before), ('after', detail)):
            observations, signature = numeric_observation(module, source, (320, 240), 'Micro detail')
            if expected is None:
                expected = signature
            elif signature != expected:
                raise AssertionError('Observed output changed.')
            gc.collect(); tracemalloc.start()
            try:
                actual = resized_signature(module.detail_aware_resize, source, (320, 240), 'Micro detail')
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            if actual != expected:
                raise AssertionError('Allocation-probe output changed.')
            rows[name] = {'peak_python_bytes': peak, 'observation': observations}
        return rows


def measure(revision=BASELINE, repeats=6, *, verify_only=False):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use a positive even pair count for balanced AB/BA order.')
    sources = source_hashes()
    before = old_module('PreviewDetailEngine', revision)
    baseline_source = subprocess.check_output(['git', 'show', f'{revision}:PreviewDetailEngine.py'], cwd=ROOT)
    result = {
        'baseline': revision, 'before_source_sha256': hashlib.sha256(baseline_source).hexdigest(),
        'python': sys.version.split()[0], 'platform': platform.platform(), 'numpy': np.__version__,
        'pillow': pillow_version, 'verify_only': verify_only, 'source_sha256': sources,
        'complete_historical_resize_cases': full_historical_parity(before),
        'public_plan_parity': public_historical_parity(before),
        'method': 'One warm pair, six balanced AB/BA pairs by default, separate tracemalloc probes after garbage collection. Identical complete signatures and owned-image cleanup are included in every measured operation.',
        'isolation': 'Only PreviewDetailEngine is replaced by its complete historical module. Public make_plan and every other dependency remain current on both sides.',
        'timing_scope': 'CPU planning helpers and complete bounded-preview make_plan calls; no GUI, native input, GPU or real-time responsiveness measurement.',
        'memory_scope': 'Tracemalloc covers Python/NumPy allocations, not RSS or most native Pillow storage. Named-array and weak-reference observations are separate, untimed proofs of copied payload and scratch lifetime.',
        'public_plan_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
        'measurements': {},
    }
    if verify_only:
        result['untimed_allocation_probe'] = allocation_only(before)
        owned = ('PreviewDetailEngine.py', Path(__file__).name, 'test_v148_rendering_batch16_detail_memory.py')
        current = source_hashes()
        if any(current[name] != sources[name] for name in owned):
            raise AssertionError('Owned source changed during validation.')
        result['owned_source_unchanged_during_validation'] = True
        result['all_python_sources_frozen'] = False
        return result
    result['repeats'] = repeats
    for target in ((320, 240), (512, 384)):
        with closing(graphic_source((target[0]*3, target[1]*3))) as source:
            for mode in ('Detailed', 'Micro detail'):
                key = f'R1602_resize_{target[0]}x{target[1]}_{mode.replace(" ", "_")}'
                print(f'Measuring {key}', flush=True)
                row = paired(lambda: resized_signature(before.detail_aware_resize, source, target, mode),
                             lambda: resized_signature(detail.detail_aware_resize, source, target, mode), repeats)
                old_observation, expected = numeric_observation(before, source, target, mode)
                new_observation, actual = numeric_observation(detail, source, target, mode)
                if actual != expected:
                    raise AssertionError('Numeric observations changed complete output.')
                row.update(parameters={'source_size': list(source.size), 'target_size': list(target),
                                       'source_mode': source.mode, 'detail_mode': mode, 'fixture': 'graphic_source'},
                           before_numeric_observation=old_observation, after_numeric_observation=new_observation)
                result['measurements'][key] = row
    with patch('DrawTimeCalibration.load_profile', return_value=None), \
            patch('DrawBot.custom_rgb_available', return_value=False), closing(graphic_source((960, 720))) as source:
        current_resize = detail.detail_aware_resize
        area = DrawBot.preview_area_for((512, 384))
        for outline in (False, True):
            for mode in ('Detailed', 'Micro detail'):
                key = f'R1602_make_plan_{"outline" if outline else "color"}_{mode.replace(" ", "_")}'
                print(f'Measuring {key}', flush=True)
                row = paired(lambda: public_plan(before.detail_aware_resize, source, area, mode, outline),
                             lambda: public_plan(current_resize, source, area, mode, outline), repeats)
                calls = []
                plan = public_plan(current_resize, source, area, mode, outline, observe=calls)
                if len(calls) != 1:
                    raise AssertionError('Expected one actual preview resize call.')
                row.update(parameters={'source_size': list(source.size), 'preview_canvas': list(area),
                                       'fixture': 'graphic_source', 'options': preview_settings(mode, outline=outline)},
                           actual_resize_calls=calls, paths=plan['count'])
                result['measurements'][key] = row
    if source_hashes() != sources:
        raise AssertionError('Python sources changed during benchmark; coordinate and rerun.')
    result['source_unchanged_during_measurement'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats, verify_only=args.verify_only)
    destination = args.output or ROOT/('docs/v148-batch16-detail-validation.json' if args.verify_only
                                       else 'docs/v148-batch16-detail-benchmarks.json')
    destination.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    summary = {'complete_historical_resize_cases': result['complete_historical_resize_cases'],
               'public_plan_cases': len(result['public_plan_parity']), 'output': str(destination)}
    if args.verify_only:
        summary['untimed_peak_python_bytes'] = {name: row['peak_python_bytes']
                                               for name, row in result['untimed_allocation_probe'].items()}
    else:
        summary['measurements'] = {name: {key: row[key] for key in ('before_median_ms', 'after_median_ms',
            'before_peak_python_bytes', 'after_peak_python_bytes', 'exact_output_parity')}
            for name, row in result['measurements'].items()}
    print(json.dumps(summary, indent=2))
