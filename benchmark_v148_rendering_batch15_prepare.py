"""Compare owned image preparation against the complete recorded PixelData.

Run during a coordinated quiet CPU window. Copy counters report nominal RGBA
payload work, not native peak memory or RSS; Python tracing is separate.
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
import PixelData
from benchmark_v148_image_workflow import fingerprint, old_module
from benchmark_v148_stroke_optimizer import paired
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_prepare import image_state, source_copy_count
from test_v148_rendering_batch15_sketch_memory import (
    VOLATILE_PATHS, comparable_plan, graphic_source, planner_options, sequence_raster,
)


ROOT = Path(__file__).resolve().parent
BASELINE = '43a1c968eb56a63224827f1567e4ccc354acdadb'


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


def preparation_cases(before):
    count = 0
    with closing(graphic_source((48, 32))) as graphic:
        for mode in ('RGBA', 'RGB', 'L', 'LA', 'P', 'RGBa'):
            for orientation in (None, 1, 6, 8):
                with closing(graphic.convert(mode)) as source:
                    if mode == 'P':
                        source.info['transparency'] = bytes(range(256))
                    if orientation is not None:
                        source.getexif()[274] = orientation
                        source.info['exif'] = source.getexif().tobytes()
                    original = image_state(source)
                    for preview in (None, 'Fast', 'Detailed'):
                        outputs = []
                        for function in (before.prepare_image, PixelData.prepare_image):
                            meta = {}
                            output, fitted = function(source, (40, 80), 8, sample_limit=23,
                                max_pixels=253, preview_detail_mode=preview, preview_detail_meta=meta)
                            with closing(output):
                                outputs.append((image_state(output), fitted, meta))
                        if outputs[0] != outputs[1] or image_state(source) != original:
                            raise AssertionError('Complete historical preparation/source parity failed.')
                        count += 1
    return count


def measure(revision=BASELINE, repeats=6):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even repeat count of at least two for balanced AB/BA samples.')
    before = old_module('PixelData', revision)
    baseline_source = subprocess.check_output(['git', 'show', revision + ':PixelData.py'], cwd=ROOT)
    sources = source_hashes()
    result = {
        'baseline': revision, 'baseline_pixeldata_sha256': hashlib.sha256(baseline_source).hexdigest(),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
        'source_sha256': sources, 'complete_preparation_parity_cases': preparation_cases(before),
        'method': 'One warm pair, balanced AB/BA timing pairs, separate tracemalloc probes after garbage collection; complete outputs compared on every call.',
        'isolation': 'The complete historical PixelData module supplies prepare_image. Public make_plan callers and all unrelated dependencies, including Sketch2Planner, remain current on both sides.',
        'timing_scope': 'Entire prepare_image or make_plan with identical output fingerprinting and image cleanup. No native drawing, GUI or GPU timing.',
        'memory_scope': 'Copy counters observe actual Image.copy calls at the source RGBA size and sum width*height*4 nominal pixel bytes. This is avoided allocation/copy work, not a measured native peak or RSS saving. Tracemalloc covers Python/NumPy allocations separately and excludes most Pillow native image storage.',
        'public_plan_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
        'measurements': {},
    }
    for source_size, target, preview in (
            ((1536, 1152), (256, 192), None),
            ((3072, 2304), (384, 288), None),
            ((3072, 2304), (384, 288), 'Detailed')):
        with closing(graphic_source(source_size)) as source:
            def operation(function):
                metadata = {}
                image, fitted = function(source, target, 10, sample_limit=max(target),
                    preview_detail_mode=preview, preview_detail_meta=metadata)
                with closing(image):
                    return fingerprint(image), fitted, metadata
            row = paired(lambda: operation(before.prepare_image),
                         lambda: operation(PixelData.prepare_image), repeats)
            old_count, expected = source_copy_count(lambda: operation(before.prepare_image), source.size)
            new_count, actual = source_copy_count(lambda: operation(PixelData.prepare_image), source.size)
            if actual != expected:
                raise AssertionError('Instrumented preparation parity failed.')
            row.update(before_copy_work=old_count, after_copy_work=new_count,
                parameters={'source_size': list(source_size), 'target': list(target),
                            'mode': 'RGBA', 'preview_detail_mode': preview, 'fixture': 'graphic_source'})
            key = f'R1502_prepare_{source_size[0]}x{source_size[1]}_' + (preview or 'Lanczos')
            result['measurements'][key] = row

    with patch('DrawTimeCalibration.load_profile', return_value=None), \
            patch('DrawBot.custom_rgb_available', return_value=False):
        for source_size, target in (((1536, 1152), (256, 192)), ((3072, 2304), (384, 288))):
            with closing(graphic_source(source_size)) as source:
                settings = planner_options('Standard / pixel'); settings['outline'] = False
                def public_call(prepare, prove_ink=False):
                    with patch('DrawBot.prepare_image', new=prepare):
                        plan = DrawBot.make_plan(source, target, dict(settings))
                    try:
                        if prove_ink:
                            with closing(sequence_raster(plan)) as raster:
                                np.testing.assert_array_equal(np.asarray(raster), np.asarray(plan['preview']))
                        return comparable_plan(plan)
                    finally:
                        close_plan(plan, source)
                expected = public_call(before.prepare_image, True)
                if public_call(PixelData.prepare_image, True) != expected:
                    raise AssertionError('Historical complete public-plan parity failed.')
                row = paired(lambda: public_call(before.prepare_image),
                             lambda: public_call(PixelData.prepare_image), repeats)
                old_count, old_output = source_copy_count(lambda: public_call(before.prepare_image), source.size)
                new_count, new_output = source_copy_count(lambda: public_call(PixelData.prepare_image), source.size)
                if old_output != new_output or old_output != expected:
                    raise AssertionError('Instrumented public plan parity failed.')
                row.update(before_copy_work=old_count, after_copy_work=new_count,
                    parameters={'source_size': list(source_size), 'target': list(target),
                                'mode': 'RGBA', 'fixture': 'graphic_source', 'options': settings},
                    paths=expected['count'], independent_ink_parity=True)
                result['measurements'][f'R1502_public_make_plan_{source_size[0]}x{source_size[1]}'] = row
    if source_hashes() != sources:
        raise AssertionError('Python sources changed during benchmark; coordinate and rerun.')
    result['source_unchanged_during_measurement'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/v148-batch15-prepare-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({name: {key: value[key] for key in (
        'before_median_ms', 'after_median_ms', 'before_copy_work', 'after_copy_work',
        'exact_output_parity')}
        for name, value in result['measurements'].items()}, indent=2))
