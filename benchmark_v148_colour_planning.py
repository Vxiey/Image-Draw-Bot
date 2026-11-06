"""Reproduce batch05 component and preview-memory comparisons locally."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

from benchmark_v148_image_workflow import old_module, measured_pair, fingerprint
from PixelAccuratePlanner import build_pixel_map


ROOT = Path(__file__).resolve().parent
BASELINE = '5f3fcfb5c4519e5ed1b9b770ba951918819d725d'
MODULES = ('PixelStrokeEngine', 'AccuracyEvaluator', 'UniversalGpuAcceleration')


def measure(revision=BASELINE, repeats=5):
    before = {name: old_module(name, revision) for name in MODULES}
    after = {name: importlib.import_module(name) for name in MODULES}
    result = {
        'baseline': revision, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
        'method': 'One exact-parity/warm pair, alternating before/after elapsed samples, separate Python/NumPy-traced peaks after garbage collection.',
        'scope': 'CPU synthetic component extraction and complete preview evaluation; no drawing, UI, native input or GPU performance claim. Component inputs are built once outside both timings. The baseline evaluator uses its baseline UniversalGpuAcceleration module too; other shared dependencies use the current checkout. Most native Pillow buffers are not traced.',
        'after_source_sha256': {name: hashlib.sha256((ROOT / (name + '.py')).read_bytes()).hexdigest()
                               for name in MODULES},
        'measurements': {},
    }
    output = result['measurements']
    rng = np.random.default_rng(148055)

    for name, size, pattern in (
        ('checker160x160', (160,160), 'checker'),
        ('solid1024x768', (1024,768), 'solid'),
        ('sparse1024x768', (1024,768), 'sparse'),
    ):
        with Image.new('RGB', size, 'white') as source:
            if pattern == 'checker':
                pixels = np.indices(size[::-1]).sum(axis=0) % 2 * 255
                source.paste(Image.fromarray(pixels.astype(np.uint8), 'L').convert('RGB'))
            elif pattern == 'solid':
                ImageDraw.Draw(source).rectangle((0,0,size[0]-1,size[1]-1), fill='black')
            else:
                draw = ImageDraw.Draw(source)
                for x,y in zip(rng.integers(0,size[0],32),rng.integers(0,size[1],32)):
                    draw.rectangle((int(x),int(y),int(x)+2,int(y)+1), fill='black')
            pm = build_pixel_map(source, ((255,255,255),(0,0,0)),
                skip_white=pattern != 'checker', gpu_mode='CPU')
        def components(module):
            values, labels, metadata = module.connected_components(pm)
            return {'components': [vars(value) for value in values],
                    'labels': labels, 'metadata': metadata}
        output['components_'+name] = {
            **measured_pair(lambda: components(before['PixelStrokeEngine']),
                            lambda: components(after['PixelStrokeEngine']), repeats),
            'parameters': {'size': list(size), 'pattern': pattern, 'vertical_runs': True,
                           'seed': 148055 if pattern == 'sparse' else None},
            'comparison': 'Every component field, ordered horizontal/vertical run, label pixel and metadata value.',
        }

    for size, alpha, heatmaps in (((768,512),False,False), ((1536,1024),False,False),
                                  ((640,384),True,True)):
        pixels = rng.integers(0,256,(*size[::-1],4 if alpha else 3),dtype=np.uint8)
        with Image.fromarray(pixels) as source, Image.fromarray(np.roll(pixels,1,axis=1)) as preview:
            importance = rng.random((96,128),dtype=np.float32) if alpha else None
            def evaluate(module, backend):
                with patch.dict(sys.modules, {'UniversalGpuAcceleration': backend}):
                    value = module.evaluate_preview(source, preview, importance, gpu_mode='CPU',
                        coverage_percent=93.75, plan_execution_accuracy_percent=98.125,
                        return_error_map=heatmaps, return_delta_e_heatmap=heatmaps)
                try:
                    return fingerprint(value)
                finally:
                    for key in ('_error_map_image','_delta_e_heatmap_image'):
                        if key in value:value[key].close()
            key = f"preview_{size[0]}x{size[1]}_{'rgba_heatmaps' if alpha else 'rgb_metrics'}"
            output[key] = {
                **measured_pair(lambda: evaluate(before['AccuracyEvaluator'], before['UniversalGpuAcceleration']),
                                lambda: evaluate(after['AccuracyEvaluator'], after['UniversalGpuAcceleration']), repeats),
                'parameters': {'size': list(size), 'seed': 148055, 'source': 'generated RGB/RGBA bytes',
                               'preview': 'one-column cyclic source shift', 'heatmaps': heatmaps,
                               'importance_size': [128,96] if alpha else None},
                'comparison': 'Complete returned metrics, routes, percentiles, and optional diagnostic image bytes.',
            }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch05-colour-planning-benchmarks.json')
    args = parser.parse_args()
    if args.repeats < 1:parser.error('--repeats must be positive')
    result = measure(args.baseline, args.repeats)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: {name: value[name] for name in (
        'before_median_ms','after_median_ms','before_peak_python_bytes','after_peak_python_bytes','exact_output_parity')}
        for key,value in result['measurements'].items()}, indent=2))
