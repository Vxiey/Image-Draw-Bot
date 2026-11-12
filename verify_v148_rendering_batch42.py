"""Compare the actual batch-41 code with the three batch-42 fidelity changes.

Only existing source pixels and their palette derivatives are read. This script
writes numeric JSON evidence, never images, and makes no timing/GPU claims.
"""
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

import numpy as np

import AdaptiveDetail
import DrawBot
import PixelAccuratePlanner as pixel
from PixelStrokeEngine import build_pixel_stroke_plan
from test_v148_rendering_batch38_prepared_paths import close_plan
from test_v148_rendering_batch39_pixel_runs import public_options, stable
from test_v148_rendering_batch41_mask_runs import controls
from test_v148_rendering_batch42_fidelity import (ASSET, ISOLUMINANT, LOW_CONTRAST,
    calibrated_palette, source_labels, standard_options)


ROOT = Path(__file__).resolve().parent
BASE = 'e33fa67d17e3c33ccda8e736e7e16c2582d9fc06'


def historical(filename):
    source = subprocess.check_output(['git', 'show', f'{BASE}:{filename}'], cwd=ROOT, text=True)
    module = types.ModuleType('batch42_reference_' + filename[:-3])
    sys.modules[module.__name__] = module
    exec(compile(source, filename, 'exec'), module.__dict__)
    return module


def digest(value):
    return hashlib.sha256(json.dumps(stable(value), sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def pixel_components(module, source, palette):
    mapped = module.build_pixel_map(source, palette, gpu_mode='CPU', skip_white=False)
    plan = build_pixel_stroke_plan(mapped, len(palette), options=public_options())
    sequence = plan['execution_sequence']
    return dict(edge_pixels=int(np.count_nonzero(mapped.edge_map)),
        protected_pixels=int(np.count_nonzero(mapped.protected_mask)),
        contour_pixels=int(np.count_nonzero(mapped.contour_map)),
        phase_counts=dict(Counter(row['phase'] for row in sequence)),
        protected_paths=sum(bool(row['protected']) for row in sequence),
        source_palette_sha256=digest(mapped.palette_index.tolist()),
        geometry_sha256=digest(sequence))


def public_record(source, options, *, bot=DrawBot, edge=None, adaptive=None):
    with ExitStack() as owned:
        if edge is not None:
            owned.enter_context(patch.object(pixel, 'edge_map', new=edge))
        if adaptive is not None:
            owned.enter_context(patch.object(bot, 'apply_adaptive_detail', new=adaptive))
        before = source.tobytes()
        plan = bot.make_plan(source, source.size, options)
        owned.callback(close_plan, plan, source)
        sequence = plan.get('execution_sequence') or ()
        result = dict(size=list(plan['image'].size), paths=plan['count'],
            groups=[len(group) for group in plan['groups']],
            phase_counts=dict(Counter(row['phase'] for row in sequence)),
            brush_counts=dict(Counter(str(row.get('brush_px')) for row in sequence)),
            protected_paths=sum(bool(row.get('protected')) for row in sequence),
            image_sha256=hashlib.sha256(plan['image'].tobytes()).hexdigest(),
            preview_sha256=hashlib.sha256(plan['preview'].tobytes()).hexdigest(),
            geometry_sha256=digest((plan['groups'], plan['execution_groups'], sequence)),
            source_pixels_preserved=plan['image'].tobytes() == before,
            estimated_seconds=plan['estimate'])
        result['adaptive'] = plan['options'].get('adaptive_detail_meta')
        result['background'] = plan['options'].get('background_simplification_meta')
        accuracy = plan['options'].get('pixel_accuracy_meta', {})
        result['pixel_accuracy'] = {key: accuracy.get(key) for key in (
            'initial_accuracy_percent', 'initial_error_pixels', 'final_accuracy_percent',
            'error_pixels', 'protected_pixels', 'protected_accuracy_percent', 'passes')}
        mapped = plan['options'].get('pixel_map_meta', {})
        result['pixel_map'] = {key: mapped.get(key) for key in ('edge_mean', 'protected_pixels',
            'contour_mean', 'micro_detail_mean')}
        result['source_unchanged'] = source.tobytes() == before
        assert result['source_unchanged']
        return result


def main():
    old_pixel = historical('PixelAccuratePlanner.py')
    old_detail = historical('AdaptiveDetail.py')
    old_bot = historical('DrawBot.py')
    report = dict(baseline=subprocess.check_output(['git', 'rev-parse', BASE], cwd=ROOT,
        text=True).strip(), python=sys.version, numpy=np.__version__,
        source='golden-regression/small-detail-preservation.png',
        source_sha256=hashlib.sha256(ASSET.read_bytes()).hexdigest(),
        method='Actual historical functions in the same CPU public planner; only the named change differs.',
        limits=['Linux CPU model observations; no physical Windows/browser/GPU result is claimed.',
                'Palette derivatives retain existing source label geometry.',
                'No wall-clock speed or memory measurements are made.'], cases=[])

    with source_labels(ISOLUMINANT) as source, calibrated_palette(ISOLUMINANT):
        old = pixel_components(old_pixel, source, ISOLUMINANT)
        new = pixel_components(pixel, source, ISOLUMINANT)
        assert old['edge_pixels'] == old['protected_pixels'] == 0
        assert new['edge_pixels'] > 0 and new['protected_pixels'] > 0
        assert old['source_palette_sha256'] == new['source_palette_sha256']
        report['cases'].append(dict(group='R4201', case='actual-pixel-component-priority',
            size=list(source.size), palette=ISOLUMINANT, before=old, after=new))
        options = public_options(portrait_focus=False, brush_px=4, profile_key='gartic-phone',
            browser_brush_plan=controls(), adaptive_color_verification=False)
        old = public_record(source, options, edge=old_pixel.edge_map)
        new = public_record(source, options)
        assert new['pixel_map']['protected_pixels'] > old['pixel_map']['protected_pixels']
        assert new['pixel_accuracy']['error_pixels'] == 0
        report['cases'].append(dict(group='R4201', case='public-pixel-adaptive-brush-plan',
            size=list(source.size), palette=ISOLUMINANT, before=old, after=new))

    grayscale = ((220, 220, 220), (20, 20, 20))
    with source_labels(grayscale, (96, 64)) as source, calibrated_palette(grayscale):
        options = public_options(portrait_focus=False)
        old = public_record(source, options, edge=old_pixel.edge_map)
        new = public_record(source, options)
        for key in ('geometry_sha256', 'image_sha256', 'preview_sha256', 'estimated_seconds', 'pixel_accuracy'):
            assert old[key] == new[key], key
        report['cases'].append(dict(group='R4201', case='public-grayscale-parity',
            size=list(source.size), palette=grayscale, before=old, after=new))

    with source_labels(LOW_CONTRAST, (96, 64)) as source, calibrated_palette(LOW_CONTRAST):
        options = standard_options(background_simplification='Strong')
        old = public_record(source, options, bot=old_bot)
        new = public_record(source, options)
        assert not old['source_pixels_preserved'] and new['source_pixels_preserved']
        assert old['groups'][1] == 0 and new['groups'][1] > 0
        report['cases'].append(dict(group='R4202', case='public-protected-background',
            size=list(source.size), palette=LOW_CONTRAST, before=old, after=new))
        before, after = {}, {}
        for preview in (True, False):
            options = standard_options(adaptive_detail='Auto', background_simplification='Off',
                _preview_plan=preview)
            key = 'preview' if preview else 'draw'
            before[key] = public_record(source, options, adaptive=old_detail.apply_adaptive_detail)
            after[key] = public_record(source, options)
        assert before['preview']['geometry_sha256'] != before['draw']['geometry_sha256']
        assert after['preview']['geometry_sha256'] == after['draw']['geometry_sha256']
        assert all(value['source_pixels_preserved'] for value in after.values())
        report['cases'].append(dict(group='R4203', case='public-auto-preview-draw',
            size=list(source.size), palette=LOW_CONTRAST, before=before, after=after))
    report['source_files_sha256'] = {filename: hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        for filename in ('PixelAccuratePlanner.py', 'FillOptimizer.py', 'AdaptiveDetail.py',
                         'DrawBot.py', 'test_v148_rendering_batch42_fidelity.py')}
    output = ROOT / 'docs/v148-batch42-rendering-validation.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output':str(output), 'cases':len(report['cases']),
        'groups':['R4201', 'R4202', 'R4203'], 'assertions':'passed'}, indent=2))


if __name__ == '__main__':
    main()
