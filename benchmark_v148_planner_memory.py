"""Reproduce batch04 planner working-set comparisons on local synthetic inputs.

Changed modules are loaded from an existing Git revision with current shared
dependencies. No target capture, native input, downloads or release assets run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

from benchmark_v148_image_workflow import old_module, measured_pair, fingerprint

ROOT = Path(__file__).resolve().parent
BASELINE = '1d48eabaf349a5fd8049a2c96ef5426745c3078c'
MODULES = ('SketchPlanner', 'Sketch2Planner', 'AxisRegionPlanner', 'TimeBudget',
           'QuickSketchFillContour')


def measure(revision=BASELINE, repeats=5):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('Repeats must be a positive integer.')
    before = {name: old_module(name, revision) for name in MODULES}
    after = {name: importlib.import_module(name) for name in MODULES}
    result = {
        'baseline': revision, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
        'method': 'One warm/parity pair, five alternating before/after elapsed pairs by default, separate Python-traced peaks after garbage collection.',
        'scope': 'Synthetic CPU helpers and one complete contour extraction. Baseline modules import current shared dependencies. Python tracing excludes most native Pillow buffers; these are not whole-drawing or Windows-input timings.',
        'after_source_sha256': {name: hashlib.sha256((ROOT / (name + '.py')).read_bytes()).hexdigest()
                               for name in MODULES},
        'measurements': {},
    }
    output = result['measurements']

    with Image.new('RGB', (512, 384), 'white') as source:
        draw = ImageDraw.Draw(source)
        for x in range(4, source.width, 9):
            draw.line((x, 4, x, source.height - 5), fill='black', width=2)
        for y in range(4, source.height, 13):
            draw.line((4, y, source.width - 5, y), fill='black', width=2)
        def contour(module):
            with module.contour_image(source, detail='Detailed') as image:
                return fingerprint(image)
        calls = [lambda module=module: contour(module)
                 for module in (before['SketchPlanner'], after['SketchPlanner'])]
        output['legacy_contour512x384_connected_grid'] = {
            **measured_pair(*calls, repeats),
            'parameters': {'size': [512, 384], 'background': 'white', 'line_width': 2,
                           'vertical_step': 9, 'horizontal_step': 13, 'detail': 'Detailed'},
            'comparison': 'Complete output raster, dimensions and mode; source remains open.',
        }

    mask = np.ones((220, 300), bool)
    strength = np.full(mask.shape, 20, np.float32)
    calls = [lambda module=module: module._filter_components(mask, strength, 10,
        min_component=6, protect_factor=1.6, cancelled=lambda: False)
        for module in (before['Sketch2Planner'], after['Sketch2Planner'])]
    output['sketch2_component300x220_full'] = {
        **measured_pair(*calls, repeats),
        'parameters': {'size': [300, 220], 'mask': 'all true', 'strength': 20,
                       'threshold': 10, 'min_component': 6, 'protect_factor': 1.6},
        'comparison': 'Complete output mask and removed/protected component counts.',
    }

    strokes = [(0, y, 1023, y) for y in range(768)]
    calls = [lambda module=module: module.verticalize_horizontal_runs(strokes)
             for module in (before['AxisRegionPlanner'], after['AxisRegionPlanner'])]
    output['vertical_runs1024x768_solid'] = {
        **measured_pair(*calls, repeats),
        'parameters': {'size': [1024, 768], 'horizontal_runs': 768},
        'comparison': 'Exact ordered vertical runs.',
    }

    groups = [[((i % 200, i // 200), (i % 200 + i % 13, i // 200))
               for i in range(20000)] for _ in range(3)]
    calls = [lambda module=module: module.apply_target_path_cap(groups, 500)
             for module in (before['TimeBudget'], after['TimeBudget'])]
    output['target_cap60000_paths_to500'] = {
        **measured_pair(*calls, repeats),
        'parameters': {'groups': 3, 'paths_per_group': 20000, 'cap': 500,
                       'path': '((i%200,i//200),(i%200+i%13,i//200))'},
        'comparison': 'Exact kept paths, source order and complete returned metadata.',
    }

    groups = [[(i, color, i + i % 2, color) for i in range(12500)] for color in range(8)]
    calls = [lambda module=module: module._trim_micro_texture(groups, 500)
             for module in (before['QuickSketchFillContour'], after['QuickSketchFillContour'])]
    output['quick_micro100000_to500'] = {
        **measured_pair(*calls, repeats),
        'parameters': {'groups': 8, 'strokes_per_group': 12500, 'cap': 500,
                       'stroke': '(i,color,i+i%2,color)'},
        'comparison': 'Exact retained strokes/order and removed, micro and long counts.',
    }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch04-planner-benchmarks.json')
    args = parser.parse_args()
    result = measure(args.baseline, args.repeats)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: {name: value[name] for name in (
        'before_median_ms', 'after_median_ms', 'before_peak_python_bytes',
        'after_peak_python_bytes', 'exact_output_parity')}
        for key, value in result['measurements'].items()}, indent=2))
