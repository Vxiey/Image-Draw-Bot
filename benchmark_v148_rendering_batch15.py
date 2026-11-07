"""Measure Sketch 2.0 scratch lifetimes against the complete Git baseline.

Run after coordinating a quiet CPU window. Six balanced AB/BA pairs include
identical complete-output fingerprints and cleanup; allocation probes run
separately. Real Paint outline and Sketch Fill plans share all other callers.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import DrawBot
import Sketch2Planner as sketch
from benchmark_v148_image_workflow import fingerprint, old_module
from benchmark_v148_stroke_optimizer import paired
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import (
    PROFILES, VOLATILE_PATHS, comparable_plan, graphic_source, planner_options,
    sequence_raster,
)


ROOT = Path(__file__).resolve().parent
BASELINE = '43a1c968eb56a63224827f1567e4ccc354acdadb'


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def exact_numerical_cases(before):
    count = 0
    for seed in (1481501, 1481502, 1481503, 1481504, 1481505):
        rng = np.random.default_rng(seed)
        for size in ((1, 17), (19, 1), (2, 5), (31, 23), (64, 48)):
            rgba = rng.integers(0, 256, (size[1], size[0], 4), dtype=np.uint8)
            rgba.flags.writeable = False
            with closing(Image.fromarray(rgba)) as source:
                for mode in ('RGBA', 'RGB', 'L', 'LA', 'P'):
                    with closing(source.convert(mode)) as image:
                        if mode == 'P':
                            image.info['transparency'] = bytes(range(256))
                        original = image.tobytes(), dict(image.info)
                        for detail in PROFILES:
                            expected, meta = before.structure_map(image, detail=detail)
                            actual, actual_meta = sketch.structure_map(image, detail=detail)
                            if not np.array_equal(actual, expected) or actual_meta != meta:
                                raise AssertionError('Historical mask/metadata parity failed.')
                            if (image.tobytes(), image.info) != original:
                                raise AssertionError('Caller source was mutated.')
                            count += 1
    return count


def retained_fields(module, source):
    observed = {}
    original = module._filter_components
    def inspect(*args, **kwargs):
        fields = sys._getframe(1).f_locals
        arrays = {name: value for name, value in fields.items() if isinstance(value, np.ndarray)}
        observed['fields'] = {name: {'shape': list(value.shape), 'dtype': str(value.dtype),
                                    'bytes': value.nbytes} for name, value in arrays.items()}
        observed['distinct_array_bytes'] = sum({id(value): value.nbytes for value in arrays.values()}.values())
        return original(*args, **kwargs)
    with patch.object(module, '_filter_components', new=inspect):
        result = fingerprint(module.structure_map(source))
    return observed, result


def verify_public_ink(plan, style):
    with closing(sequence_raster(plan)) as raster:
        np.testing.assert_array_equal(np.asarray(raster), np.asarray(plan['preview']))
        if style == 'Standard / pixel':
            np.testing.assert_array_equal(np.asarray(raster)[:, :, 0] == 0,
                                          np.asarray(plan['image'])[:, :, 0] == 0)
    if style == 'Sketch + Auto Fill':
        with closing(sequence_raster(plan, 'sketch')) as raster:
            np.testing.assert_array_equal(np.asarray(raster), np.asarray(plan['ui_previews']['sketch2']))


def measure(revision=BASELINE, repeats=6):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA samples.')
    before = old_module('Sketch2Planner', revision)
    baseline_source = subprocess.check_output(['git', 'show', revision + ':Sketch2Planner.py'], cwd=ROOT)
    sources = source_hashes()
    result = {
        'baseline': revision, 'baseline_sketch2_sha256': hashlib.sha256(baseline_source).hexdigest(),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
        'source_sha256': sources, 'complete_numerical_parity_cases': exact_numerical_cases(before),
        'method': 'One warm pair, six balanced AB/BA pairs by default, separate tracemalloc peaks after garbage collection; complete outputs compared on every warm, timed, traced and observation call.',
        'isolation': 'The complete historical Sketch2Planner module supplies structure_map/contour_image_v2; all public make_plan callers and unrelated dependencies remain current on both sides.',
        'timing_scope': 'Entire structure_map or public make_plan, including identical complete-output fingerprints and owned-image cleanup. CPU planning only, no native input, GUI or GPU timing.',
        'memory_scope': 'Tracemalloc peaks include Python/NumPy allocations, not RSS or most native Pillow pixel storage. Retained fields separately observe the caller immediately before the unchanged component filter.',
        'public_plan_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
        'measurements': {},
    }
    for size in ((512, 384), (1024, 768)):
        with closing(graphic_source(size)) as source:
            def operation(module):
                return fingerprint(module.structure_map(source, detail='Detailed'))
            row = paired(lambda: operation(before), lambda: operation(sketch), repeats)
            old_fields, expected = retained_fields(before, source)
            new_fields, actual = retained_fields(sketch, source)
            if actual != expected:
                raise AssertionError('Observed lifetime calls changed the complete result.')
            row.update(parameters={'size': list(size), 'mode': 'RGBA', 'detail': 'Detailed',
                                   'fixture': 'graphic_source'},
                       before_component_filter=old_fields, after_component_filter=new_fields)
            result['measurements'][f'R1501_structure_map_{size[0]}x{size[1]}'] = row

    with patch('DrawTimeCalibration.load_profile', return_value=None), \
            patch('DrawBot.custom_rgb_available', return_value=False):
        for style, name in (('Standard / pixel', 'paint_outline'), ('Sketch + Auto Fill', 'sketch_fill')):
            for size in ((256, 192), (512, 384)):
                with closing(graphic_source(size)) as source:
                    settings = planner_options(style)
                    def public_call(contour, prove_ink=False):
                        with patch.object(sketch, 'contour_image_v2', new=contour):
                            plan = DrawBot.make_plan(source, size, dict(settings))
                        try:
                            if prove_ink:
                                verify_public_ink(plan, style)
                            return comparable_plan(plan)
                        finally:
                            close_plan(plan, source)
                    expected = public_call(before.contour_image_v2, True)
                    current_contour = sketch.contour_image_v2
                    if public_call(current_contour, True) != expected:
                        raise AssertionError('Complete public plan parity failed.')
                    row = paired(lambda: public_call(before.contour_image_v2),
                                 lambda: public_call(current_contour), repeats)
                    row.update(parameters={'size': list(size), 'mode': 'RGBA',
                                           'fixture': 'graphic_source', 'options': settings},
                               paths=expected['count'], independent_ink_parity=True)
                    result['measurements'][f'R1501_{name}_make_plan_{size[0]}x{size[1]}'] = row
    if source_hashes() != sources:
        raise AssertionError('Python sources changed during benchmark; coordinate and rerun.')
    result['source_unchanged_during_measurement'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch15-rendering-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({name: {key: value[key] for key in (
        'before_median_ms', 'after_median_ms', 'before_peak_python_bytes',
        'after_peak_python_bytes', 'exact_output_parity')}
        for name, value in result['measurements'].items()}, indent=2))
