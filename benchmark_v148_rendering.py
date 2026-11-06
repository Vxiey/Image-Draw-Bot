"""Reproduce batch06 plan reuse and Fill storage against the published baseline."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
from unittest.mock import patch

from PIL import Image, ImageDraw, __version__ as pillow_version

from benchmark_v148_image_workflow import old_module, measured_pair, fingerprint


ROOT = Path(__file__).resolve().parent
BASELINE = 'f59a57c6fc1eef1ace07e872ba50ed834e1bb924'


def _metadata(meta):
    result = dict(meta)
    # RP02 completion: the old diagnostic hard-coded v3 while both timings use
    # the same current v5 execution model. No planning value is excluded.
    result.pop('execution_cost_model', None)
    return result


def _groups(value):
    return {'paths': value, 'phase_hints': getattr(value, 'phase_hints', None),
            'protected_prefix_counts': getattr(value, 'protected_prefix_counts', None),
            'semantic_meta': getattr(value, 'semantic_meta', None)}


def measure(revision=BASELINE, repeats=5):
    before = old_module('ExtraFast2', revision)
    after = importlib.import_module('ExtraFast2')
    fill_before = old_module('FillOptimizer', revision)
    fill_after = importlib.import_module('FillOptimizer')
    dependency_names = ('DrawBot', 'ContinuousPaths', 'ExecutionCostModel', 'StrokeOptimizer',
                        'TimeBudget', 'AxisRegionPlanner', 'Sketch2Planner', 'Colors', 'ColorCache',
                        'ColorFidelity', 'PreviewSafety', 'PreviewLayers', 'SafetyDebugOverlay')
    result = {
        'baseline': revision, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'pillow': pillow_version, 'repeats': repeats,
        'method': 'One exact-parity/warm pair, alternating before/after elapsed samples, separate traced peaks after garbage collection.',
        'scope': 'CPU generated path plans, actual make_plan Line Art and both production Fill detectors; no native input or GPU performance claim. ExtraFast2 and FillOptimizer are loaded separately from the baseline. Both sides use the same current downstream cap, optimizer, execution model, palette and application caller.',
        'parity_exclusion': 'Only execution_cost_model label: RP02 completion replaces hard-coded v3 with actual model version5. All remaining ExtraFast metadata, paths, semantic hints and protected prefixes must match exactly.',
        'after_source_sha256': {name: hashlib.sha256((ROOT / (name + '.py')).read_bytes()).hexdigest()
                                for name in ('ExtraFast2', 'FillOptimizer')},
        'shared_dependency_sha256': {name: hashlib.sha256((ROOT / (name + '.py')).read_bytes()).hexdigest()
                                     for name in dependency_names},
        'measurements': {},
    }
    output = result['measurements']
    options = {'stroke_optimizer': 'Travel only', 'drawing_mode': 'Smart paths (recommended)',
               'speed': 'Balanced', '_hybrid_cost_calibration_override': {}}
    fixtures = (
        ('unchanged_disconnected_240', [[(x * 3, y * 3, x * 3, y * 3)
                                        for y in range(12) for x in range(20)]], None, None),
        ('unchanged_portrait_480_capped', [[(x * 3, y * 3, x * 3, y * 3)
                                           for y in range(20) for x in range(24)], []], 16, 120),
        ('changed_vertical_160', [[(x, 2, x, 180) for x in range(2, 162)]], None, None),
    )
    for name, groups, prefix, cap in fixtures:
        settings = dict(options, target_stroke_count_resolved=cap)
        def run(module):
            paths, metadata = module.build_fast_paths(groups, settings, portrait_edge_count=prefix)
            return {'groups': _groups(paths), 'metadata': _metadata(metadata)}
        calls = {}
        for label, module in (('before', before), ('after', after)):
            with patch.object(module, '_downstream_plan_cost', wraps=module._downstream_plan_cost) as counter:
                run(module)
                calls[label] = counter.call_count
        output[name] = {
            **measured_pair(lambda: run(before), lambda: run(after), repeats),
            'parameters': {'source_runs': sum(map(len, groups)), 'portrait_prefix': prefix,
                           'target_cap': cap, 'options': settings},
            'complete_final_cost_evaluations': calls,
        }

    from DrawBot import make_plan
    settings = {
        'render_preset': 'Extra fast', 'drawing_style': 'Line Art',
        'profile_name': 'Microsoft Paint', 'profile_key': 'microsoft-paint',
        'fill_tool_available': False, 'detail': 8, 'delay': .01, 'speed': 'Fast',
        'precision': 'High', 'lines': True, 'skip_white': True, 'contrast': 1.,
        'outline': False, 'paint_current_color': False, 'brush_px': 1,
        'time_budget_mode': 'Unlimited', 'unlimited_time': True, 'max_seconds': 80,
        'gpu_mode': 'CPU', 'planning_resolution': 'Standard',
        'custom_color_workflow': 'Calibrated palette', 'exact_color_available': False,
        'color_rendering': 'Perceptual match', 'color_fidelity': 'Faithful',
        'detail_zoom': 'Off', 'adaptive_detail': 'Off', 'preview_plan': True,
        '_hybrid_cost_calibration_override': {},
    }
    with closing(Image.new('RGB', (160, 120), 'white')) as image:
        draw = ImageDraw.Draw(image)
        for y in range(10, 105, 20):
            for x in range(10, 150, 20):
                draw.rectangle((x, y, x + 10, y + 10), outline='black', width=1)
        def run_plan(module):
            with patch.dict(sys.modules, {'ExtraFast2': module}):
                plan = make_plan(image, image.size, settings)
            try:
                return fingerprint({
                    'image': plan['image'], 'preview': plan['preview'], 'groups': plan['groups'],
                    'execution_groups': _groups(plan['execution_groups']),
                    'execution_sequence': plan['execution_sequence'], 'count': plan['count'],
                    'source_count': plan['source_count'], 'estimate': plan['estimate'],
                    'path_stats': plan['path_stats'], 'extra_fast': _metadata(plan['options']['extra_fast_v2_meta']),
                })
            finally:
                for value in (*plan.values(), *plan['options'].values()):
                    if isinstance(value, Image.Image):
                        value.close()
        calls = {}
        for label, module in (('before', before), ('after', after)):
            with patch.object(module, '_downstream_plan_cost', wraps=module._downstream_plan_cost) as counter:
                run_plan(module)
                calls[label] = counter.call_count
        output['actual_make_plan_paint_line_art'] = {
            **measured_pair(lambda: run_plan(before), lambda: run_plan(after), repeats),
            'parameters': {'size': [160, 120], 'source': '35 separated black rectangle outlines',
                           'options': settings},
            'complete_final_cost_evaluations': calls,
            'comparison': 'Full source/planned preview bytes, source/execution paths and sequence, counts, estimate, path statistics and all ExtraFast metadata except corrected model-version label.',
        }

    from Colors import allColors
    palette=tuple(c.RGB for c in allColors)
    for scene,size in (('border',(384,384)),('mixed',(256,192))):
        width,height=size
        with closing(Image.new('RGB',size,palette[1])) as image:
            if scene=='mixed':
                draw=ImageDraw.Draw(image)
                draw.rectangle((20,20,89,120),fill=palette[0])
                draw.rectangle((160,16,220,160),fill=palette[2])
                draw.line((190,150,190,height-1),fill=palette[2],width=1)
            color_lookup={tuple(rgb):index for index,rgb in enumerate(palette)}
            groups=[[] for _ in palette]
            for y in range(height):
                left=0;last=image.getpixel((0,y))
                for x in range(1,width+1):
                    current=image.getpixel((x,y)) if x<width else None
                    if current!=last:
                        groups[color_lookup[tuple(last)]].append((left,y,x-1,y));left=x;last=current
            for kind in ('image','groups'):
                def run_fill(module):
                    if kind=='image':
                        regions,metadata=module.detect_fill_regions(image,'Balanced',return_meta=True)
                    else:
                        regions,metadata=module.detect_fill_regions_from_groups(groups,palette,size,'Balanced',return_meta=True)
                    return {'regions':[region.as_dict() for region in regions],'metadata':metadata}
                output[f'fill_{kind}_{scene}']={
                    **measured_pair(lambda:run_fill(fill_before),lambda:run_fill(fill_after),repeats),
                    'parameters':{'size':list(size),'scene':scene,'source_runs':sum(map(len,groups))},
                    'comparison':'Every accepted region field, source row span, seed, contour, guard sample and component/rejection/selection counter.',
                }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch06-rendering-benchmarks.json')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    result = measure(args.baseline, args.repeats)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: {name: value[name] for name in (
        'before_median_ms', 'after_median_ms', 'before_peak_python_bytes',
        'after_peak_python_bytes', 'exact_output_parity', 'complete_final_cost_evaluations') if name in value}
        for key, value in result['measurements'].items()}, indent=2))
