"""Existing-source cost decisions and exact host-staging A/B evidence.

Historical functions are read from the public checkpoint. No image is written;
JSON distinguishes modeled delivery seconds from measured CPU host work.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image

import Colors
import DetailZoomPass as zoom
import DrawBot
from ExecutionCostModel import build_cost_model
import PixelAccuracyGpu as rectangles
from test_v148_rendering_batch38_prepared_paths import close_plan
from test_v148_rendering_batch39_pixel_runs import public_options
from test_v148_rendering_batch42_costs import calibrated_fill_options, fill_source, zoom_options
from verify_v148_rendering_batch42 import BASE, ROOT, digest, historical


@contextmanager
def default_palette():
    previous = list(Colors.allColors)
    try:
        Colors.reset_palette()
        yield
    finally:
        Colors.allColors[:] = previous
        from PixelData import closest_color
        closest_color.cache_clear()


def plan_record(source, size, options, *, bot=DrawBot, modules=None):
    with ExitStack() as owned:
        if modules:
            owned.enter_context(patch.dict(sys.modules, modules))
        before = source.tobytes()
        plan = bot.make_plan(source, size, options)
        owned.callback(close_plan, plan, source)
        sequence = plan['execution_sequence']
        settings = plan['options']
        model = build_cost_model(settings, plan['image'].size, plan['fitted'])
        strokes = model.sequence_cost(sequence, initial_brush=1, include_color_verification=True)
        fixed = float(model.fixed_overhead(active_colors=0).total_seconds)
        regions = settings.get('fill_regions') or ()
        batches = {}
        for region in regions:
            color = int(region['color_index'])
            batch = batches.setdefault(str(color), dict(regions=0, areas=[], scanline_seconds=0., core_seconds=0.))
            batch['regions'] += 1
            batch['areas'].append(int(region['area_pixels']))
            batch['scanline_seconds'] += float(region['stroke_cost_seconds'])
            # Price the known real contour/click/verification cost independently
            # of the old selector's undercounted per-batch UI formula.
            batch['core_seconds'] += max(.001, float(region['fill_cost_seconds']) - model.switch_cost('tool_change'))
        controls = len(settings.get('fill_tool_actions') or ()) + len(settings.get('fill_restore_actions') or ())
        fill_seconds = 0.
        for color, batch in batches.items():
            batch['tool_seconds'] = controls * model.switch_cost('tool_change')
            batch['complete_seconds'] = batch['core_seconds'] + batch['tool_seconds']
            batch['color_selection_seconds'] = sum(model.color_selection_cost(int(color)))
            fill_seconds += batch['complete_seconds'] + batch['color_selection_seconds']
        base = [row for row in sequence if not row.get('detail_zoom')]
        # Hybrid's public scheduler applies the risk allowance only when a
        # deadline is active. Unlimited comparisons use its ordinary model.
        budgeted_strokes = (model.risk_adjusted_seconds(strokes.total_seconds)
                            if settings.get('time_budget_active') else strokes.total_seconds)
        result = dict(source_size=list(source.size), working_size=list(plan['image'].size),
            fitted=list(plan['fitted']), paths=len(sequence),
            detail_paths=len(sequence)-len(base), base_geometry_sha256=digest(base),
            geometry_sha256=digest(sequence),
            preview_sha256=hashlib.sha256(plan['preview'].tobytes()).hexdigest(),
            image_sha256=hashlib.sha256(plan['image'].tobytes()).hexdigest(),
            source_unchanged=source.tobytes() == before,
            modeled_sequence_seconds=strokes.total_seconds,
            modeled_fixed_seconds=fixed, modeled_fill_seconds=fill_seconds,
            time_budget_active=bool(settings.get('time_budget_active')),
            modeled_complete_seconds=budgeted_strokes+fixed+fill_seconds,
            render_budget_seconds=settings.get('deadline_render_budget_seconds'),
            fill_batches=batches,
            fill_batch_admission=(settings.get('region_fill_meta') or {}).get('fill_batch_admission'),
            fill_revalidation=(settings.get('region_fill_meta') or {}).get('stateful_fill_simulation'),
            hybrid_quality=(settings.get('adaptive_hybrid_meta') or {}).get('quality'),
            detail_zoom=settings.get('detail_zoom_meta'))
        assert result['source_unchanged']
        return result


def measured_pair(before, after, *, iterations=7):
    expected = before()
    actual = after()
    np.testing.assert_array_equal(expected, actual)
    expected_shape, expected_dtype = list(expected.shape), str(expected.dtype)
    output_bytes = int(expected.nbytes)
    output_hash = hashlib.sha256(expected.tobytes()).hexdigest()
    del expected, actual
    samples = {'before': [], 'after': []}
    for index in range(iterations):
        order = (('before', before), ('after', after))
        if index % 2:
            order = tuple(reversed(order))
        for label, function in order:
            started = time.perf_counter()
            value = function()
            elapsed = time.perf_counter() - started
            samples[label].append(elapsed)
            assert hashlib.sha256(value.tobytes()).hexdigest() == output_hash
            del value
    memory = {}
    for label, function in (('before', before), ('after', after)):
        gc.collect()
        tracemalloc.start()
        try:
            value = function()
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert hashlib.sha256(value.tobytes()).hexdigest() == output_hash
        memory[label] = dict(traced_current_bytes=current, traced_peak_bytes=peak)
        del value
    return dict(shape=expected_shape, dtype=expected_dtype, output_bytes=output_bytes,
        output_sha256=output_hash, exact_output_parity=True, samples_seconds=samples,
        median_seconds={label:statistics.median(values) for label,values in samples.items()},
        memory=memory)


def main():
    old_bot = historical('DrawBot.py')
    old_zoom = historical('DetailZoomPass.py')
    old_rectangles = historical('PixelAccuracyGpu.py')
    fill_modules = {name:historical(name + '.py') for name in
        ('AdaptiveRegionHybrid', 'RegionFillEngine', 'ExtraFast')}
    report = dict(baseline=BASE, python=sys.version, numpy=np.__version__,
        method='Real public historical/current planners, followed by alternating CPU host-function pairs and separate tracemalloc runs.',
        limits=['Delivery costs are modeled seconds, not native Windows/browser timing.',
                'tracemalloc measures tracked Python/NumPy allocations; it does not measure complete process RSS or GPU VRAM.',
                'No CUDA hardware is used. Ordered host rectangle equality is proven before the unchanged GPU boundary.',
                'The physical Fill regression models the real three-pixel CanvasGuard inset explicitly.'],
        cases=[], source_files_sha256={})
    with default_palette(), fill_source() as source:
        options = calibrated_fill_options()
        before = plan_record(source, source.size, options, bot=old_bot, modules=fill_modules)
        after = plan_record(source, source.size, options)
        assert set(before['fill_batches']) == {'0','3'}
        assert set(after['fill_batches']) == {'0'}
        bad = before['fill_batches']['3']
        assert bad['complete_seconds'] > bad['scanline_seconds']
        assert before['hybrid_quality'] == after['hybrid_quality']
        assert before['preview_sha256'] == after['preview_sha256']
        assert after['modeled_complete_seconds'] < before['modeled_complete_seconds']
        report['cases'].append(dict(group='R4204', case='actual-public-Fill-admission',
            source='golden-regression/dominant-hue-four-color.png', before=before, after=after))
    with default_palette(), Image.open(ROOT / 'golden-regression/small-detail-preservation.png') as source:
        off = plan_record(source, (96,64), zoom_options('Off'))
        before = plan_record(source, (96,64), zoom_options('4x'), bot=old_bot,
            modules={'DetailZoomPass':old_zoom})
        after = plan_record(source, (96,64), zoom_options('4x'))
        assert off['base_geometry_sha256'] == before['base_geometry_sha256'] == after['base_geometry_sha256']
        assert off['modeled_complete_seconds'] < before['render_budget_seconds'] < before['modeled_complete_seconds']
        assert after['modeled_complete_seconds'] <= after['render_budget_seconds']
        assert 0 < after['detail_paths'] < before['detail_paths']
        report['cases'].append(dict(group='R4205', case='late-Detail-Zoom-real-budget',
            source='golden-regression/small-detail-preservation.png', base_without_zoom=off, before=before, after=after))
        settings = zoom_options('4x', time_budget_mode='Unlimited', unlimited_time=True)
        before = plan_record(source, (96,64), settings, bot=old_bot, modules={'DetailZoomPass':old_zoom})
        after = plan_record(source, (96,64), settings)
        for key in ('geometry_sha256','preview_sha256','image_sha256','detail_paths','modeled_complete_seconds','detail_zoom'):
            assert before[key] == after[key], key
        report['cases'].append(dict(group='R4205', case='Unlimited-complete-plan-parity',
            source='golden-regression/small-detail-preservation.png', before=before, after=after))
    with Image.open(ROOT / 'assets/image-draw-bot-icon.png') as icon:
        before_bytes = icon.tobytes()
        for label, box in (('original',None), ('small-square',(32,32,160,160)),
                           ('horizontal-panorama',(0,250,512,252)), ('vertical-panorama',(250,0,252,512))):
            with ExitStack() as owned:
                source = icon if box is None else owned.enter_context(icon.crop(box))
                result = measured_pair(lambda:old_zoom._visible_rgb(source), lambda:zoom._visible_rgb(source))
                report['cases'].append(dict(group='R4206', case=label, mode=source.mode,
                    source='assets/image-draw-bot-icon.png', source_size=list(source.size), **result))
        assert icon.tobytes() == before_bytes
    with default_palette(), Image.open(ROOT / 'golden-regression/red-bananas-texture.png') as source, ExitStack() as owned:
        plan = DrawBot.make_plan(source, (192,128), public_options(portrait_focus=False))
        owned.callback(close_plan, plan, source)
        sequence = plan['execution_sequence']
        old_geometry = digest(sequence)
        size = plan['image'].size
        result = measured_pair(lambda:old_rectangles.compile_swept_rectangles(sequence,1,*size),
            lambda:rectangles.compile_swept_rectangles(sequence,1,*size))
        assert digest(sequence) == old_geometry
        report['cases'].append(dict(group='R4207', case='actual-public-Pixel-rectangle-catalogue',
            source='golden-regression/red-bananas-texture.png', paths=len(sequence),
            phases=dict(Counter(row['phase'] for row in sequence)), **result))
    files = ('DetailZoomPass.py','PixelAccuracyGpu.py','AdaptiveRegionHybrid.py','RegionFillEngine.py',
             'ExtraFast.py','DrawBot.py','test_v148_rendering_batch42_costs.py',
             'test_v148_rendering_batch42_staging.py','benchmark_v148_rendering_batch42_costs.py')
    report['source_files_sha256'] = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}
    report['assets_sha256'] = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
        ('golden-regression/dominant-hue-four-color.png','golden-regression/small-detail-preservation.png',
         'golden-regression/red-bananas-texture.png','assets/image-draw-bot-icon.png')}
    output = ROOT / 'docs/v148-batch42-rendering-costs.json'
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(output=str(output), cases=len(report['cases']), assertions='passed'), indent=2))


if __name__ == '__main__':
    main()
