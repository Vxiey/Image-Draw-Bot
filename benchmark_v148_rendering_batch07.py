"""Compare batch07 shadow/background storage with the published checkpoint.

Synthetic CPU source images only: no captures, downloads, native input or GPU
claim. Each changed helper is loaded from the exact Git baseline, with shared
current production callers/dependencies identified by source hashes.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import fields
import hashlib
import importlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

from benchmark_v148_image_workflow import fingerprint, measured_pair, old_module


ROOT = Path(__file__).resolve().parent
BASELINE = '8a9c848b9dd0f2c4738aee729dace75be2a5778d'


def _close_plan(plan, source):
    for value in (*plan.values(), *plan.get('options', {}).values(), *plan.get('ui_previews', {}).values()):
        if isinstance(value, Image.Image) and value is not source:
            value.close()


def _paths(value):
    return {'paths': value, 'phase_hints': getattr(value, 'phase_hints', None),
            'protected_prefix_counts': getattr(value, 'protected_prefix_counts', None),
            'semantic_meta': getattr(value, 'semantic_meta', None)}


def measure(revision=BASELINE, repeats=5):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('Repeats must be a positive integer')
    names = ('ShadowDetailEngine', 'FillOptimizer')
    before = {name: old_module(name, revision) for name in names}
    after = {name: importlib.import_module(name) for name in names}
    dependencies = ('DrawBot', 'PixelAccuratePlanner', 'ImageGradients', 'PixelData',
        'PixelMapValidation', 'UniversalGpuAcceleration', 'SafeFillMask', 'Colors', 'ColorCache',
        'ColorMatchingEngine', 'ColorFidelity', 'AdvancedColor', 'ColorGrouping',
        'PreviewSafety', 'ContinuousPaths', 'ExecutionCostModel', 'StrokeOptimizer',
        'TimeBudget', 'AdaptiveDetail', 'ImageSampling', 'DrawingStyleProfiles',
        'benchmark_v148_image_workflow', 'benchmark_v148_rendering_batch07')
    result = {
        'baseline': revision, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'repeats': repeats,
        'method': 'One exact-parity/warm pair, five alternating before/after elapsed pairs by default, separate traced-memory peaks after garbage collection.',
        'scope': 'CPU shadow analysis, actual PixelAccuratePlanner.build_pixel_map, background simplification and actual DrawBot.make_plan. No input, UI, network or GPU throughput claim. Only the measured changed helper is substituted; both sides share the current caller and other dependencies.',
        'parity': 'No fields are excluded from helper results or PixelMap. Application comparison includes source/preview pixels, complete source/execution paths, sequence, counts, estimate, path statistics, simplification and transparency metadata. Volatile application profiling/timer metadata is outside that explicitly listed comparison.',
        'lifetime': 'Owned returned images are fingerprinted and closed within each measured helper/application call. Fingerprinting cost is included equally on both sides. Array results are fingerprinted only by the warm/parity comparison; timed array calls return and release their original arrays.',
        'memory_scope': 'tracemalloc peak includes Python/NumPy allocations tracked by Python; most Pillow pixel-core allocation and process RSS are not measured. Separate ownership regression proves removal of the second full RGB copy.',
        'baseline_source_sha256': {name: hashlib.sha256(subprocess.check_output(
            ['git', 'show', f'{revision}:{name}.py'], cwd=ROOT)).hexdigest() for name in names},
        'after_source_sha256': {name: hashlib.sha256((ROOT / (name + '.py')).read_bytes()).hexdigest() for name in names},
        'shared_dependency_sha256': {name: hashlib.sha256((ROOT / (name + '.py')).read_bytes()).hexdigest() for name in dependencies},
        'measurements': {},
    }
    output = result['measurements']
    rng = np.random.default_rng(1480702)
    rgb = rng.integers(0, 256, (512, 512, 3), dtype=np.uint8)
    index = rng.integers(0, 4, (512, 512), dtype=np.int16)
    drawable = rng.random((512, 512)) > .15
    edges = rng.random((512, 512), dtype=np.float32)
    calls = [lambda module=module: module.analyze_shadow_contours(rgb, index, drawable, edges)
             for module in (before['ShadowDetailEngine'], after['ShadowDetailEngine'])]
    output['shadow_guidance_512x512'] = {
        **measured_pair(*calls, repeats),
        'parameters': {'size': [512, 512], 'seed': 1480702, 'palette_size': 4, 'drawable_probability': .85},
        'comparison': 'All five float32 maps, three boolean masks and complete metadata.',
    }

    from PixelAccuratePlanner import build_pixel_map
    palette = ((0, 0, 0), (255, 255, 255), (0, 80, 205), (255, 120, 41))
    with closing(Image.fromarray(rgb)) as source:
        def pixel_map(module):
            with patch.dict(sys.modules, {'ShadowDetailEngine': module}):
                value = build_pixel_map(source, palette, gpu_mode='CPU', skip_white=False,
                                        color_rendering='RGB nearest', color_fidelity='Fast')
            return {field.name: getattr(value, field.name) for field in fields(value)}
        output['actual_pixel_map_512x512'] = {
            **measured_pair(lambda: pixel_map(before['ShadowDetailEngine']),
                            lambda: pixel_map(after['ShadowDetailEngine']), repeats),
            'parameters': {'size': [512, 512], 'seed': 1480702, 'palette': palette,
                           'gpu_mode': 'CPU', 'skip_white': False, 'color_rendering': 'RGB nearest', 'color_fidelity': 'Fast'},
            'comparison': 'Every PixelMap field: complete source RGB, palette indices, drawable/edge/importance/protected/contour/shadow/shadow-detail/micro-detail arrays and metadata.',
        }

    for scene, size in (('connected_with_enclosed_island', (384, 384)), ('coverage_rejected', (128, 128))):
        with closing(Image.new('RGB', size, (240, 240, 240))) as source:
            draw = ImageDraw.Draw(source)
            if scene == 'connected_with_enclosed_island':
                draw.rectangle((128, 128, 255, 255), outline='black', width=1)
                draw.rectangle((129, 129, 254, 254), fill=(245, 245, 245))
            else:
                draw.rectangle((1, 1, 126, 126), fill='black')
            def simplify(module):
                image, metadata = module.simplify_background(source, 'Balanced')
                with closing(image):
                    return {'image': fingerprint(image), 'metadata': metadata.as_dict()}
            output['background_' + scene] = {
                **measured_pair(lambda: simplify(before['FillOptimizer']),
                                lambda: simplify(after['FillOptimizer']), repeats),
                'parameters': {'size': list(size), 'mode': 'Balanced', 'scene': scene},
                'comparison': 'Complete output RGB and all simplification metadata, including coverage/changed pixels/rejection reason.',
            }

    import DrawBot
    settings = {
        'detail': 10, 'delay': .001, 'speed': 'Balanced', 'precision': 'Ultra', 'lines': True,
        'drawing_mode': 'Smart paths (recommended)', 'smart_paths': True,
        'render_preset': 'Manual', 'render_style': 'Standard / pixel', 'draw_quality': 'High likeness',
        'human_mode': 'Off', 'gpu_mode': 'CPU', 'gpu_vram': 'Auto', 'gpu_performance': 'High throughput',
        'cpu_workers': '4', 'cpu_engine': 'Threads', 'ram_budget': '2 GB', 'ram_custom_mb': '2048',
        'planning_resolution': 'Standard', 'resource_scheduler': 'Off', 'background_fill': 'Off',
        'background_simplification': 'Balanced', 'use_region_fill_engine': False,
        'color_grouping': 'Accurate', 'color_workflow': 'Finish color first', 'stroke_optimizer': 'Travel only',
        'adaptive_detail': 'Off', 'detail_zoom': 'Off', 'visual_verification': 'Off',
        'color_rendering': 'RGB nearest', 'color_fidelity': 'Fast', 'color_layers': 'Off',
        'custom_color_workflow': 'Calibrated palette', 'exact_color_limit': 'Auto',
        'portrait_focus': False, 'skip_white': False, 'contrast': 1., 'outline': False, 'brush_px': 1,
        'max_seconds': 600, 'manual_max_seconds': 600, 'time_budget_mode': 'Unlimited', 'unlimited_time': True,
        'target_stroke_count': 'Auto', 'target_stroke_custom': '2500',
        'paint_current_color': False, 'erase_mode': False, 'paint_tool': 'Use current tool',
        'effective_paint_tool': 'Use current tool', 'tool_actions': [], 'fill_tool_available': False,
        'fill_tool_actions': [], 'fill_restore_actions': [], '_execution_cost_calibration_override': {},
    }
    with closing(Image.new('RGBA', (256, 192), (240, 240, 240, 255))) as source:
        draw = ImageDraw.Draw(source)
        draw.rectangle((70, 40, 185, 151), outline='black', width=2)
        draw.rectangle((90, 60, 165, 131), fill=(0, 80, 205, 128))
        draw.rectangle((120, 85, 135, 106), fill=(220, 10, 50, 0))
        def plan_with_simplifier(module):
            # The pre-change helper did not yet have the cancellation keyword.
            # Both timed calls run with no cancellation; this adapter changes
            # only the signature, preserving the exact baseline implementation.
            def compatible(image, mode, *, cancelled=lambda: False):
                return module.simplify_background(image, mode)
            operation = compatible if module is before['FillOptimizer'] else module.simplify_background
            with patch.object(DrawBot, 'simplify_background', operation):
                plan = DrawBot.make_plan(source, source.size, settings)
            try:
                return fingerprint({
                    'image': plan['image'], 'preview': plan['preview'], 'groups': plan['groups'],
                    'execution_groups': _paths(plan['execution_groups']), 'execution_sequence': plan['execution_sequence'],
                    'count': plan['count'], 'source_count': plan['source_count'], 'estimate': plan['estimate'],
                    'path_stats': plan['path_stats'],
                    'background_simplification': plan['options']['background_simplification_meta'],
                    'source_transparency': plan['options']['source_transparency_meta'],
                })
            finally:
                _close_plan(plan, source)
        output['actual_make_plan_partial_and_zero_alpha'] = {
            **measured_pair(lambda: plan_with_simplifier(before['FillOptimizer']),
                            lambda: plan_with_simplifier(after['FillOptimizer']), repeats),
            'parameters': {'size': [256, 192], 'source': 'Gray connected background, closed black rectangle, half-alpha blue interior and zero-alpha central hole', 'options': settings},
            'comparison': result['parity'],
            'baseline_adapter': 'Accept current cancelled keyword and call unchanged baseline simplify_background(image, mode); benchmark cancellation remains false.',
        }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch07-rendering-benchmarks.json')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    result = measure(args.baseline, args.repeats)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: {name: value[name] for name in (
        'before_median_ms', 'after_median_ms', 'before_peak_python_bytes',
        'after_peak_python_bytes', 'exact_output_parity') if name in value}
        for key, value in result['measurements'].items()}, indent=2))
