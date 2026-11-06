"""Paired exact brush-footprint and actual hybrid-plan measurements."""
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

from benchmark_v148_image_workflow import fingerprint, measured_pair, old_module
from test_v148_rendering_batch08_footprint import browser_settings
from test_v148_rendering_batch06_canvas import close_plan


ROOT = Path(__file__).resolve().parent
BASELINE = '73788a51c1a3502f03f007e4d2ffe0152f56b7e6'


def measure(revision=BASELINE, repeats=5):
    import AdaptiveRegionHybrid as after
    import DrawBot
    before = old_module('AdaptiveRegionHybrid', revision)
    sources = ('AdaptiveRegionHybrid', 'DrawBot', 'PixelAccuratePlanner', 'PixelStrokeEngine',
        'RasterGeometry', 'ExecutionCostModel', 'AdaptiveBrushEngine', 'VisibleContrast',
        'AdaptiveDetail', 'SafeFillMask', 'FillOptimizer', 'PreviewSafety',
        'UniversalGpuAcceleration', 'ColorMatchingEngine', 'ColorFidelity',
        'benchmark_v148_image_workflow', 'benchmark_v148_rendering_batch08',
        'test_v148_rendering_batch08_footprint', 'test_v148_rendering_batch07_transparency',
        'test_pixel_accurate_v1086', 'test_v148_rendering_batch06_canvas')
    result = {'baseline': revision, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
        'method': 'One exact-parity/warm pair, alternating before/after elapsed pairs, separate traced peaks after garbage collection.',
        'scope': 'Only the two square-footprint operators are substituted from the baseline. Both sides of the actual public make_plan call share current color/contrast/GPU policy, candidate generation, sequence cost, scheduling, previews and all other dependencies. Generated CPU images only; no native input or hardware GPU test.',
        'memory_scope': 'Python/NumPy traced peak; not process RSS or most native Pillow pixel-core storage. Returned maps/images and full plan structures remain included as described per fixture.',
        'baseline_adaptation': 'The old helpers predate the optional cancelled keyword. The public caller adapters accept it and invoke the unchanged baseline helper; all benchmark callbacks remain false.',
        'baseline_source_sha256': hashlib.sha256(subprocess.check_output(
            ['git', 'show', f'{revision}:AdaptiveRegionHybrid.py'], cwd=ROOT)).hexdigest(),
        'source_sha256': {name: hashlib.sha256((ROOT / (name + '.py')).read_bytes()).hexdigest() for name in sources},
        'measurements': {}}
    measurements = result['measurements']
    for size in ((128, 128), (768, 512)):
        width, height = size
        target = np.ones((height, width), bool)
        target[height // 3:height // 2, width // 3:width // 2] = False
        residual = target.copy()
        residual[::3] = False
        def run(module):
            return {'eroded': module._eroded_centers(target, 28),
                    'touching': module._centers_touching_mask(residual, 28)}
        measurements[f'both_footprints_{width}x{height}_28px'] = {
            **measured_pair(lambda: run(before), lambda: run(after), repeats),
            'parameters': {'size': list(size), 'brush_px': 28,
                'target': 'Solid region with central rectangular hole', 'residual': 'Target excluding every third row'},
            'comparison': 'Every Boolean pixel of both footprint maps.',
            'baseline_full_roi_shift_buffers': 2 * 28 * 28,
            'current_full_roi_shift_buffers': 0,
            'largest_explicit_numeric_work_array_bytes': 16 * 1024 * 8,
        }

    settings = browser_settings()
    settings['_execution_cost_calibration_override'] = {}
    with closing(Image.new('RGBA', (128, 96), 'white')) as source:
        ImageDraw.Draw(source).rectangle((20, 16, 107, 79), fill=(0, 80, 205, 255))
        old_erode, old_touch = before._eroded_centers, before._centers_touching_mask
        new_erode, new_touch = after._eroded_centers, after._centers_touching_mask
        def plan(old):
            def erode(mask, brush, *, cancelled=lambda: False):
                return old_erode(mask, brush) if old else new_erode(mask, brush, cancelled=cancelled)
            def touching(mask, brush, *, cancelled=lambda: False):
                return old_touch(mask, brush) if old else new_touch(mask, brush, cancelled=cancelled)
            with patch.object(after, '_eroded_centers', side_effect=erode), \
                    patch.object(after, '_centers_touching_mask', side_effect=touching):
                value = DrawBot.make_plan(source, source.size, settings)
            try:
                metadata = value['options']['adaptive_hybrid_meta']
                return fingerprint({'image': value['image'], 'preview': value['preview'],
                    'groups': value['groups'], 'execution_groups': value['execution_groups'],
                    'execution_sequence': value['execution_sequence'], 'count': value['count'],
                    'estimate': value['estimate'], 'source_count': value['source_count'],
                    'path_stats': value['path_stats'], 'quality': metadata['quality'],
                    'region_choices': metadata['region_choices'], 'candidate_diagnostics': metadata['candidate_diagnostics'],
                    'schedule': metadata['schedule']})
            finally:
                close_plan(value, source)
        measurements['actual_verified_multibrush_make_plan'] = {
            **measured_pair(lambda: plan(True), lambda: plan(False), repeats),
            'parameters': {'size': [128, 96], 'region_bbox': [20, 16, 107, 79], 'options': settings},
            'comparison': 'Complete source/preview pixels, source/execution groups and ordered sequence, counts/estimate/path statistics, regional choices, all candidate diagnostics, complete schedule and quality. Only unrelated volatile timing/profiling fields are outside this explicitly listed comparison.',
            'timing_scope': 'Whole actual make_plan call plus identical result fingerprinting/owned-image cleanup on both sides.',
        }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch08-rendering-benchmarks.json')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    data = measure(args.baseline, args.repeats)
    args.output.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: {field: row[field] for field in ('before_median_ms', 'after_median_ms',
        'before_peak_python_bytes', 'after_peak_python_bytes', 'exact_output_parity')}
        for key, row in data['measurements'].items()}, indent=2))
