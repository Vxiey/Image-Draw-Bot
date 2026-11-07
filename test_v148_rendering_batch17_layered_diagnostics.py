"""Layered mapping evidence measures actual ordered-Bayer palette pixels."""
import ast
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import customtkinter as ctk

import AdvancedColor as color
import Colors
import DrawBot
import StudioUI
from ColorFidelity import finalize_mapping_stats, mapping_pair_metrics
from PixelData import closest_color
from PreviewQuality import full_preview_options
from test_advanced_color_v108 import opts
import test_v148_ui_batch16_plan_status as status_fixture


BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
BLACK_WHITE = ((0, 0, 0), (255, 255, 255))
SUM_FIELDS = {
    'source_lightness_sum': 'source_lightness', 'mapped_lightness_sum': 'mapped_lightness',
    'source_saturation_sum': 'source_saturation', 'mapped_saturation_sum': 'mapped_saturation',
    'source_luminance_sum': 'source_luminance', 'mapped_luminance_sum': 'mapped_luminance',
    'delta_e_sum': 'delta_e76', 'delta_e2000_sum': 'delta_e2000',
    'delta_e_oklab_sum': 'delta_e_oklab', 'hue_error_sum': 'hue_error',
}
MAX_FIELDS = {'delta_e_max': 'delta_e76', 'delta_e2000_max': 'delta_e2000',
              'delta_e_oklab_max': 'delta_e_oklab'}


@contextmanager
def calibrated(palette=BLACK_WHITE, *, names=None):
    """Use the real palette loader so every imported palette sees one state."""
    previous = list(Colors.allColors)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        directory = Path(temporary)
        path = directory / 'palette.json'
        path.write_text(json.dumps({'version': 4, 'profile': 'microsoft-paint',
            'state': 'calibrated', 'colors': [
                {'name': names[index] if names is not None else ('Black' if rgb == (0, 0, 0) else 'White'),
                 'position': [-400 + 10 * index, -100], 'rgb': list(rgb)}
                for index, rgb in enumerate(palette)]}), encoding='utf-8')
        try:
            Colors.load_calibration(path, profile_key='microsoft-paint')
            stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
            stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            stack.enter_context(patch('DrawBot.log_event'))
            yield palette
        finally:
            Colors.allColors[:] = previous
            closest_color.cache_clear()


def visible_rgb(pixel):
    r, g, b, alpha = map(int, pixel)
    return tuple((value * alpha + 255 * (255 - alpha) + 127) // 255 for value in (r, g, b))


def drawn_labels(source, groups, *, skip_white):
    """Independent raster of real horizontal runs/dots, with exact ownership."""
    labels = np.full((source.height, source.width), -1, dtype=np.int32)
    covered = np.zeros(labels.shape, dtype=np.int32)
    for index, group in enumerate(groups):
        for x0, y0, x1, y1 in group:
            assert y0 == y1 and 0 <= x0 <= x1 < source.width
            covered[y0, x0:x1 + 1] += 1
            labels[y0, x0:x1 + 1] = index
    drawable = np.array([[pixel[3] > 0 and (not skip_white or min(visible_rgb(pixel)) < 245)
                          for pixel in row] for row in np.asarray(source)], dtype=bool)
    np.testing.assert_array_equal(covered, drawable.astype(np.int32))
    return labels


def pair_statistics(pairs):
    """Aggregate the unchanged color metrics from independently rasterized RGB."""
    counts = Counter(pairs)
    stats = {'mapped_pixels': sum(counts.values())}
    for field in (*SUM_FIELDS, *MAX_FIELDS):
        stats[field] = 0.
    for (source, mapped), count in counts.items():
        pair = mapping_pair_metrics(source, mapped)
        for field, metric in SUM_FIELDS.items():
            stats[field] += count * pair[metric]
        for field, metric in MAX_FIELDS.items():
            stats[field] = max(stats[field], pair[metric])
    return finalize_mapping_stats(stats)


def raster_statistics(source, labels, palette, coordinates=None):
    data = np.asarray(source)
    if coordinates is None:
        coordinates = ((x, y) for y in range(source.height) for x in range(source.width))
    pairs = ((visible_rgb(data[y, x]), tuple(palette[int(labels[y, x])]))
             for x, y in coordinates if labels[y, x] >= 0)
    return pair_statistics(pairs)


def legacy_nearest_statistics(source, *, skip_white, color_rendering='Perceptual match',
                              color_fidelity='Balanced', sample_limit=768):
    """Preserve the existing nonlayered coordinate/sample contract independently."""
    palette = tuple(tuple(swatch.RGB) for swatch in Colors.allColors)
    stride = max(1, int((source.width * source.height / max(1, sample_limit)) ** .5))
    pairs = []
    for y in range(0, source.height, stride):
        for x in range(0, source.width, stride):
            pixel = source.getpixel((x, y)); rgb = visible_rgb(pixel)
            if pixel[3] <= 0 or skip_white and min(rgb) >= 245:
                continue
            index = color.closest_palette_index(rgb, color_rendering=color_rendering,
                color_fidelity=color_fidelity)
            pairs.append((rgb, palette[index]))
            if len(pairs) >= sample_limit:
                return pair_statistics(pairs)
    return pair_statistics(pairs)


def build(source, **changes):
    options = dict(lines=True, skip_white=False, color_rendering='Layered color mix',
                   color_layers='Full color mix', color_fidelity='Balanced', gpu_mode='CPU')
    options.update(changes)
    return color.build_color_strokes(source, **options)


def plan_options():
    return opts(detail=10, human_mode='Off', color_rendering='Layered color mix',
        color_layers='Full color mix', color_fidelity='Balanced',
        profile_name='Microsoft Paint', profile_key='microsoft-paint', render_preset='Manual',
        draw_quality='Balanced', color_grouping='Accurate', adaptive_detail='Off',
        stroke_optimizer='Travel only', detail_zoom='Off', time_budget_mode='Unlimited',
        unlimited_time=True, _execution_cost_calibration_override={})


def actual_summary_label(app):
    tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf-8'))
    builder = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build_ui')
    factory = next(node for node in builder.body if isinstance(node, ast.FunctionDef) and node.name == 'label')
    call = next(node for node in ast.walk(builder) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == 'label'
        and any(keyword.arg == 'var' and isinstance(keyword.value, ast.Attribute)
                and keyword.value.attr == 'summary' for keyword in node.keywords))
    assignment = ast.Assign(targets=[ast.Name(id='readout', ctx=ast.Store())], value=call)
    module = ast.fix_missing_locations(ast.Module(body=[factory, assignment], type_ignores=[]))
    scope = dict(vars(StudioUI), a=app, workspace_center=object())
    with patch.object(ctk, 'CTkLabel', status_fixture.BoundReadout):
        exec(compile(module, StudioUI.__file__, 'exec'), scope)
    return scope['readout']


class LayeredMappingDiagnosticsTests(unittest.TestCase):
    def test_layered_sampling_is_bounded_unique_and_keeps_complete_bayer_phases(self):
        for width, height in ((0, 0), (1, 1), (1, 3000), (3000, 1), (127, 95),
                              (128, 96), (257, 5), (5, 257)):
            for budget in (0, 1, 15, 16, 17, 767, 768, 769):
                with self.subTest(size=(width, height), budget=budget):
                    samples = list(color._layered_sample_coordinates(width, height, budget))
                    self.assertLessEqual(len(samples), budget)
                    self.assertEqual(len(samples), len(set(samples)))
                    self.assertTrue(all(0 <= x < width and 0 <= y < height for x, y in samples))
                    if width * height <= budget:
                        self.assertEqual(set(samples), {(x, y) for y in range(height) for x in range(width)})
                    elif width % 4 == height % 4 == 0 and budget and budget % 16 == 0:
                        phases = Counter((x % 4, y % 4) for x, y in samples)
                        self.assertEqual(phases, {(x, y): budget // 16 for y in range(4) for x in range(4)})

    def test_small_actual_rasters_and_every_layer_mode_define_the_mapping_metrics(self):
        data = np.full((8, 12, 4), (90, 90, 90, 255), dtype=np.uint8)
        data[0, :4] = (250, 20, 160, 0)
        data[1, :4] = (255, 255, 255, 255)
        data[2:4, 4:8] = (0, 0, 0, 128)
        for palette in (BLACK_WHITE, BLACK_WHITE[::-1]):
            with calibrated(palette), closing(Image.fromarray(data)) as source:
                original = source.tobytes()
                for rendering, mode in (('Layered color mix', 'Off'),
                                        ('Layered color mix', 'Light shading'),
                                        ('Layered color mix', 'Dual-color mix'),
                                        ('Layered color mix', 'Full color mix'),
                                        ('Perceptual match', 'Full color mix')):
                    for lines in (False, True):
                        for skip_white in (False, True):
                            with self.subTest(palette=palette, rendering=rendering, mode=mode,
                                              lines=lines, skip_white=skip_white):
                                groups, metadata = build(source, color_rendering=rendering, color_layers=mode,
                                                         lines=lines, skip_white=skip_white)
                                labels = drawn_labels(source, groups, skip_white=skip_white)
                                self.assertEqual(metadata['color_fidelity_diagnostics'],
                                                 raster_statistics(source, labels, palette))
                                self.assertEqual(source.tobytes(), original)

    def test_large_uniform_raster_does_not_alias_one_bayer_phase_at_stride_four(self):
        with calibrated(), closing(Image.new('RGBA', (128, 96), (90, 90, 90, 255))) as source:
            observed = []
            def metric(src, mapped):
                observed.append((src, mapped))
                return mapping_pair_metrics(src, mapped)
            with patch.object(color, 'mapping_pair_metrics', side_effect=metric):
                groups, metadata = build(source)
            labels = drawn_labels(source, groups, skip_white=False)
            # Literal Bayer output: the current policy chooses white first,
            # black second at 65%, quantized to 10 of the 16 actual sites.
            expected = np.array([[0 if BAYER[y % 4][x % 4] < 10 else 1
                                  for x in range(128)] for y in range(96)], np.int32)
            np.testing.assert_array_equal(labels, expected)
            reference = raster_statistics(source, labels, BLACK_WHITE)
            reference['mapped_pixels'] = 768
            self.assertEqual(metadata['color_fidelity_diagnostics'], reference)
            self.assertEqual(len(observed), 768)
            self.assertEqual(Counter(mapped for _source, mapped in observed),
                             {(0, 0, 0): 480, (255, 255, 255): 288})

    def test_actual_thread_workers_preserve_raster_and_published_diagnostics(self):
        with calibrated(), closing(Image.new('RGBA', (256, 196), (90, 90, 90, 255))) as source:
            serial, serial_meta = build(source, cpu_workers=1)
            worker = color._color_rows_worker
            calls = []
            def observed(task):
                calls.append((task[0], threading.get_ident()))
                return worker(task)
            with patch.object(color, '_color_rows_worker', side_effect=observed):
                parallel, parallel_meta = build(source, cpu_workers=2, cpu_engine='Threads')
            self.assertEqual(parallel_meta['cpu_backend'], 'threads')
            self.assertGreater(parallel_meta['cpu_chunks'], 1)
            self.assertTrue(any(y % 4 for y, _thread in calls))
            self.assertTrue(all(thread != threading.get_ident() for _y, thread in calls))
            self.assertEqual(serial, parallel)
            self.assertEqual(serial_meta['color_fidelity_diagnostics'], parallel_meta['color_fidelity_diagnostics'])
            labels = drawn_labels(source, serial, skip_white=False)
            reference = raster_statistics(source, labels, BLACK_WHITE)
            reference['mapped_pixels'] = 768
            self.assertEqual(serial_meta['color_fidelity_diagnostics'], reference)

    def test_nonlayered_modes_keep_the_existing_sample_and_nearest_metrics(self):
        rng = np.random.default_rng(1481701)
        data = rng.integers(0, 256, (59, 73, 4), dtype=np.uint8)
        data[::5, ::3, 3] = 0
        data[::7, ::4] = (255, 255, 255, 255)
        with calibrated(), closing(Image.fromarray(data)) as source:
            for rendering, mode in (('Perceptual match', 'Off'), ('RGB nearest', 'Off'),
                                    ('RGB nearest', 'Full color mix')):
                for skip_white in (False, True):
                    with self.subTest(rendering=rendering, mode=mode, skip_white=skip_white):
                        _groups, metadata = build(source, color_rendering=rendering,
                                                   color_layers=mode, skip_white=skip_white)
                        expected = legacy_nearest_statistics(source, skip_white=skip_white,
                                                            color_rendering=rendering)
                        self.assertEqual(metadata['color_fidelity_diagnostics'], expected)

    def test_partial_cells_transparency_and_white_skip_use_only_drawable_sample_pixels(self):
        # A partial right/bottom Bayer cell and skipped sites must never turn
        # into invented mixed colors or be included in the metric denominator.
        data = np.full((95, 127, 4), (90, 90, 90, 255), np.uint8)
        data[::3, ::5] = (10, 250, 20, 0)
        data[::7, ::4] = (0, 0, 0, 128)
        data[::5, ::3] = (255, 255, 255, 255)
        with calibrated(), closing(Image.fromarray(data)) as source:
            original = source.tobytes()
            for skip_white in (False, True):
                with self.subTest(skip_white=skip_white):
                    observed = []
                    def metric(src, mapped):
                        observed.append((src, mapped))
                        return mapping_pair_metrics(src, mapped)
                    with patch.object(color, 'mapping_pair_metrics', side_effect=metric):
                        groups, metadata = build(source, skip_white=skip_white)
                    labels = drawn_labels(source, groups, skip_white=skip_white)
                    coordinates = color._layered_sample_coordinates(source.width, source.height, 768)
                    self.assertEqual(metadata['color_fidelity_diagnostics'],
                                     raster_statistics(source, labels, BLACK_WHITE, coordinates))
                    self.assertLessEqual(len(observed), 768)
                    self.assertTrue(all(mapped in BLACK_WHITE for _source, mapped in observed))
                    self.assertEqual(source.tobytes(), original)

    def test_calibrated_custom_workflows_report_real_colored_and_semitransparent_pixels(self):
        palette = BLACK_WHITE + ((230, 100, 20), (20, 150, 230))
        names = ('Black', 'White', 'Custom orange', 'Custom blue')
        data = np.full((8, 12, 4), (120, 120, 90, 255), np.uint8)
        data[:, 4:8] = (110, 0, 160, 128)
        data[:, 8:] = (205, 68, 35, 255)
        with calibrated(palette, names=names), closing(Image.fromarray(data)) as source:
            for workflow in color.CUSTOM_COLOR_WORKFLOWS:
                with self.subTest(workflow=workflow):
                    groups, metadata = build(source, custom_color_workflow=workflow)
                    labels = drawn_labels(source, groups, skip_white=False)
                    self.assertEqual(metadata['color_fidelity_diagnostics'],
                                     raster_statistics(source, labels, palette))
                    if workflow == 'Custom colors only':
                        self.assertEqual(groups[:2], [[], []])

    def test_no_evidence_stays_unavailable_and_stop_after_sampling_discards_the_result(self):
        with calibrated():
            for rgba, skip_white in (((17, 80, 240, 0), False), ((255, 255, 255, 255), True)):
                with self.subTest(rgba=rgba), closing(Image.new('RGBA', (13, 9), rgba)) as source:
                    groups, metadata = build(source, skip_white=skip_white)
                    self.assertFalse(any(groups))
                    self.assertEqual(metadata['color_fidelity_diagnostics'],
                                     finalize_mapping_stats({'mapped_pixels': 0}))
            with closing(Image.new('RGBA', (13, 9), (90, 90, 90, 255))) as source:
                stopped = threading.Event()
                def metric(src, mapped):
                    stopped.set()
                    return mapping_pair_metrics(src, mapped)
                with patch.object(color, 'mapping_pair_metrics', side_effect=metric):
                    result = build(source, cancelled=stopped.is_set)
                self.assertEqual(result, (None, {'cancelled': True}))
                self.assertEqual(source.getpixel((0, 0)), (90, 90, 90, 255))


class PublicLayeredMappingTests(status_fixture.PlanStatusFixture):
    def test_real_final_and_full_preview_plans_publish_raster_metrics_in_the_workspace_label(self):
        with calibrated(), closing(Image.new('RGBA', (8, 8), (90, 90, 90, 255))) as source:
            for full_preview in (False, True):
                with self.subTest(full_preview=full_preview):
                    settings = plan_options()
                    if full_preview:
                        settings = full_preview_options(settings, source.size)
                    plan = DrawBot.make_plan(source, source.size, settings)
                    self.plans.append(plan)
                    app = self.app()
                    app.original = source
                    widget = actual_summary_label(app)
                    plan['preview_generation'] = app.preview_generation
                    DrawBot.DrawBotApp._handle_event(app, 'planned', plan)
                    self.assertIs(app.plan, plan)
                    metadata = plan['options']['advanced_color_meta']
                    self.assertEqual(metadata['layered_pixels'], 40)
                    target = plan['ui_previews']['quantized_target']
                    self.assertEqual(sorted(target.getcolors()), [(24, (255, 255, 255)), (40, (0, 0, 0))])
                    rgb = np.asarray(target)
                    labels = np.where(rgb[:, :, 0] == 0, 0, 1)
                    expected = raster_statistics(source, labels, BLACK_WHITE)
                    color_text = (f" · {expected['color_fidelity_rating']}"
                                  f" · ΔE00 {expected['average_delta_e2000']:.1f}"
                                  f" · luminance {expected['luminance_drift_percent']:+.0f}%")
                    self.assertIn(color_text, widget.visible_text())
                    self.assertEqual(metadata['color_fidelity_diagnostics'], expected)
                    self.assertIn('40 layered px', widget.visible_text())
                    self.assertEqual(source.getpixel((0, 0)), (90, 90, 90, 255))


if __name__ == '__main__':
    unittest.main()
