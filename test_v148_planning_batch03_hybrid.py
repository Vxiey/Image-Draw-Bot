from __future__ import annotations

import json
import random
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveRegionHybrid as hybrid
import AutoBrushWidth
import HybridRenderer3 as policies
from SketchFillRenderer import build_phase_previews, render_sequence_preview
from ColorMatchingEngine import visible_rgb_image
from ExecutionCostModel import build_cost_model
from PixelAccuratePlanner import PixelMap
from RasterGeometry import nearest_axis_samples, project_pixel_interval


def target(size=(12, 10), *, features=True):
    w, h = size
    return PixelMap(w, h, np.zeros((h, w, 3), np.uint8), np.ones((h, w), np.int16),
                    np.ones((h, w), bool), np.full((h, w), float(features), np.float32),
                    np.ones((h, w), np.float32), np.full((h, w), features, bool), {})


class VisibleBrushTests(unittest.TestCase):
    def test_fully_transparent_rgb_noise_is_not_classified_as_visible_detail(self):
        values = np.random.default_rng(14803).integers(0, 256, (144, 144, 4), dtype=np.uint8)
        values[..., 3] = 0
        source = Image.fromarray(values)
        white = Image.new('RGB', source.size, 'white')
        try:
            actual = AutoBrushWidth.resolve_brush_width(source, target_size=(1600, 1600))
            expected = AutoBrushWidth.resolve_brush_width(white, target_size=(1600, 1600))
            self.assertEqual(actual, expected)
            self.assertEqual(actual.classification, 'flat-shape')
        finally:
            source.close(); white.close()

    def test_key_and_palette_transparency_match_visible_rgb(self):
        rgb = Image.new('RGB', (32, 32), (30, 70, 110))
        rgb.info['transparency'] = (30, 70, 110)
        indexed = Image.new('P', (32, 32), 0)
        indexed.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        indexed.info['transparency'] = 0
        for source in (rgb, indexed):
            expected = visible_rgb_image(source)
            try:
                self.assertEqual(AutoBrushWidth._metrics(source), AutoBrushWidth._metrics(expected))
                source.getpixel((0, 0))
            finally:
                expected.close(); source.close()

    def test_opaque_source_is_borrowed_and_intermediates_close_on_failure(self):
        source = Image.new('RGB', (256, 256), 'black')
        resized = []
        real_resize = Image.Image.resize
        def resize(image, *args, **kwargs):
            owned = real_resize(image, *args, **kwargs)
            resized.append(owned)
            return owned
        try:
            with patch.object(Image.Image, 'resize', new=resize), \
                    patch.object(Image.Image, 'quantize', side_effect=RuntimeError('quantize failed')), \
                    patch.object(AutoBrushWidth, 'visible_rgb_image', side_effect=AssertionError('full copy')):
                with self.assertRaisesRegex(RuntimeError, 'quantize failed'):
                    AutoBrushWidth._metrics(source)
            self.assertEqual(len(resized), 2)
            for owned in resized:
                with self.assertRaises(ValueError):owned.getpixel((0, 0))
            self.assertEqual(source.getpixel((0, 0)), (0, 0, 0))
        finally:
            source.close()


class HybridSimulationTests(unittest.TestCase):
    def test_direct_paint_matches_independent_square_sample_sets_and_overpainting(self):
        randomizer = random.Random(14803)
        sequence = []
        expected = np.full((10, 12), -1, np.int16)
        for i in range(100):
            path = tuple((randomizer.randrange(-4, 16), randomizer.randrange(-4, 14))
                         for _ in range(randomizer.randrange(1, 4)))
            brush, color = i % 4 + 1, i % 3
            sequence.append({'color_index': color, 'brush_px': brush, 'path': path})
            lo, hi = (brush - 1) // 2, brush // 2
            centres = set(path if len(path) == 1 else ())
            for (x0, y0), (x1, y1) in zip(path, path[1:]):
                steps = max(abs(x1 - x0), abs(y1 - y0), 1)
                centres.update((round(x0 + (x1 - x0) * (k / steps)),
                                round(y0 + (y1 - y0) * (k / steps))) for k in range(steps + 1))
            for x, y in centres:
                for yy in range(y - lo, y + hi + 1):
                    for xx in range(x - lo, x + hi + 1):
                        if 0 <= xx < 12 and 0 <= yy < 10:expected[yy, xx] = color
        _, actual = hybrid.simulate_quantized_plan(target(), sequence)
        np.testing.assert_array_equal(actual, expected)

    def test_absent_edge_or_protected_features_do_not_penalize_a_perfect_plan(self):
        pm = target(features=False)
        sequence = [{'color_index': 1, 'path': ((0, y), (11, y))} for y in range(10)]
        metrics, _ = hybrid.simulate_quantized_plan(pm, sequence)
        self.assertEqual(metrics['pixel_accuracy_score'], 100)
        self.assertEqual(metrics['edge_preservation_percent'], 100)
        self.assertEqual(metrics['protected_detail_percent'], 100)

    def test_simulation_checks_cancellation_inside_one_path_and_before_empty_work(self):
        pm = target()
        with self.assertRaises(InterruptedError):
            hybrid.simulate_quantized_plan(pm, [], cancelled=lambda: True)
        checks = 0
        def cancel():
            nonlocal checks
            checks += 1
            return checks >= 3
        with self.assertRaises(InterruptedError):
            hybrid._paint_path(np.zeros((1000, 1000), bool), ((0, 0), (999, 998)), 1, cancelled=cancel)
        self.assertEqual(checks, 3)

    def test_initial_pixel_map_cancellation_and_backend_cancellation_propagate(self):
        with Image.new('RGB', (8, 8)) as image:
            with patch.object(hybrid.np, 'full', side_effect=AssertionError('allocated')):
                with self.assertRaises(InterruptedError):
                    hybrid.pixel_map_from_groups(image, [[]], [(0, 0, 0)], cancelled=lambda: True)
            with patch('UniversalGpuAcceleration.edge_magnitude', side_effect=InterruptedError()):
                with self.assertRaises(InterruptedError):
                    hybrid.pixel_map_from_groups(image, [[(0, 0, 7, 0)]], [(0, 0, 0)])

    def test_source_edge_analysis_uses_visible_pixels(self):
        values = np.random.default_rng(14803).integers(0, 256, (12, 12, 4), dtype=np.uint8)
        values[..., 3] = 0
        observed = []
        def edges(luminance, **kwargs):
            observed.append(luminance.copy())
            return np.zeros(luminance.shape, np.float32), {}
        source = Image.fromarray(values)
        try:
            with patch('UniversalGpuAcceleration.edge_magnitude', side_effect=edges):
                hybrid.pixel_map_from_groups(source, [[(1, 1, 8, 1)]], [(0, 0, 0)])
            np.testing.assert_allclose(observed[0], np.ones((12, 12)), atol=1e-6)
            source.getpixel((0, 0))
        finally:
            source.close()

    def test_scheduler_can_cancel_and_unlimited_report_is_strict_json(self):
        model = build_cost_model({'_execution_cost_calibration_override': {}}, (10, 10), (10, 10))
        with self.assertRaises(InterruptedError):
            hybrid._schedule([], {}, (10, 10), model, {}, [], cancelled=lambda: True)
        _, _, metadata = hybrid._schedule([], {}, (10, 10), model, {}, [])
        json.dumps(metadata, allow_nan=False)
        self.assertIsNone(metadata['usable_path_seconds'])

    def test_no_fill_reuses_reference_pixel_map(self):
        image = Image.new('RGB', (3, 2), 'black')
        base = {'image': image, 'groups': [[(0, 0, 2, 0)]], 'colors': [(0, 0, 0)],
                'fitted': (3, 2), 'options': {}}
        pm = target((3, 2))
        result = {'execution_groups': [[((0, 0), (2, 0))]], 'execution_sequence': [],
                  'coverage_preview': None, 'error_preview': None, 'metadata': {}}
        def finish(image, fitted, groups, options, cancelled):
            options['_accuracy_original_source'].close()
            return {'options': options}
        try:
            with patch.object(hybrid, '_build_fill_regions', return_value=([], {})), \
                    patch.object(hybrid, 'pixel_map_from_groups', return_value=pm) as maps, \
                    patch.object(hybrid, 'build_adaptive_execution', return_value=result) as execute:
                hybrid.build_adaptive_hybrid_plan(image, image.size, {}, lambda *args: base, finish)
            maps.assert_called_once()
            self.assertIs(execute.call_args.args[0], execute.call_args.kwargs['reference_pixel_map'])
        finally:
            image.close()


class ExactPreviewFootprintTests(unittest.TestCase):
    def test_interval_projection_matches_pillow_floating_sampling_boundaries(self):
        cases=[(65,73,90,153)]
        rng=random.Random(14803)
        for _ in range(3000):
            source_size=rng.randint(1,300);preview_size=rng.randint(1,400)
            first,last=sorted((rng.randrange(source_size),rng.randrange(source_size)))
            cases.append((first,last,source_size,preview_size))
        for first,last,source_size,preview_size in cases:
            raw=np.zeros((1,source_size),np.uint8);raw[0,first:last+1]=255
            with Image.fromarray(raw) as source:
                with source.resize((preview_size,1),Image.Resampling.NEAREST) as expected:
                    left,right=project_pixel_interval(first,last,source_size,preview_size)
                    actual=np.zeros((1,preview_size),np.uint8)
                    actual[0,left:right+1]=255
                    np.testing.assert_array_equal(actual,np.asarray(expected))
        self.assertEqual(project_pixel_interval(65,73,90,153),(111,125))

    def test_preview_axis_sampling_is_bounded_by_destination_and_reused(self):
        source_size=10**9
        samples=nearest_axis_samples(source_size,7)
        self.assertEqual(len(samples),7)
        with patch('RasterGeometry.nearest_axis_samples',side_effect=AssertionError('do not rebuild')):
            self.assertEqual(project_pixel_interval(0,source_size-1,source_size,7,samples=samples),(0,6))
        with patch('AdaptiveRegionHybrid.nearest_axis_samples',wraps=nearest_axis_samples) as sample:
            image=hybrid.render_adaptive_preview((90,1),(153,1),
                [{'color_index':0,'path':((65,0),(73,0))}],[(0,0,0)])
        try:
            self.assertEqual(sample.call_count,2)
            actual=np.flatnonzero(np.any(np.asarray(image)[0]!=255,axis=1))
            np.testing.assert_array_equal(actual,np.arange(111,126))
        finally:image.close()

    def test_one_source_pixel_stays_one_pixel_at_identity_scale(self):
        sequence=[{'color_index':0,'path':((2,2),)}]
        for renderer in (hybrid.render_adaptive_preview,render_sequence_preview):
            image=renderer((5,5),(5,5),sequence,[(0,0,0)])
            try:
                actual=np.any(np.asarray(image)!=255,axis=2)
                expected=np.zeros((5,5),bool);expected[2,2]=True
                np.testing.assert_array_equal(actual,expected)
            finally:image.close()

    def test_fill_span_is_inclusive_without_an_extra_row_or_column(self):
        image=hybrid.render_adaptive_preview((6,5),(6,5),[],[(0,0,0)],
                                             [{'color_index':0,'row_spans':[(2,1,3)]}])
        try:
            expected=np.zeros((5,6),bool);expected[2,1:4]=True
            np.testing.assert_array_equal(np.any(np.asarray(image)!=255,axis=2),expected)
        finally:image.close()

    def test_preview_matches_nearest_scaled_simulated_raster_with_mixed_brushes(self):
        palette=[(0,0,0),(240,20,30),(30,70,210)]
        sequence=[{'color_index':0,'brush_px':1,'path':((0,0),(11,7))},
                  {'color_index':1,'brush_px':2,'path':((2,4),(8,4))},
                  {'color_index':2,'brush_px':3,'path':((9,8),)}]
        fills=[{'color_index':1,'row_spans':[(1,3,6),(2,3,6)]}]
        _,canvas=hybrid.simulate_quantized_plan(target(),sequence,fills)
        rgb=np.full((10,12,3),255,np.uint8)
        for color,index in enumerate(palette):rgb[canvas==color]=index
        source=Image.fromarray(rgb)
        try:
            for size in ((12,10),(24,20),(7,3),(3,8),(1,1),(17,13)):
                actual=hybrid.render_adaptive_preview((12,10),size,sequence,palette,fills)
                expected=source.resize(size,Image.Resampling.NEAREST)
                try:np.testing.assert_array_equal(np.asarray(actual),np.asarray(expected))
                finally:actual.close();expected.close()
            actual=render_sequence_preview((12,10),(12,10),sequence,palette,brush_px=1)
            _,without_fills=hybrid.simulate_quantized_plan(target(),sequence)
            expected=np.full((10,12,3),255,np.uint8)
            for color,index in enumerate(palette):expected[without_fills==color]=index
            try:np.testing.assert_array_equal(np.asarray(actual),expected)
            finally:actual.close()
        finally:source.close()

    def test_phase_filter_keeps_entry_brush_and_does_not_mutate_sequence(self):
        sequence=[{'color_index':0,'path':((2,2),),'brush_px':2,'phase':'sketch'},
                  {'color_index':1,'path':((4,4),),'phase':'color_fill'}]
        image=render_sequence_preview((6,6),(6,6),sequence,[(0,0,0),(255,0,0)],phases=('sketch',))
        try:
            expected=np.zeros((6,6),bool);expected[2:4,2:4]=True
            np.testing.assert_array_equal(np.any(np.asarray(image)!=255,axis=2),expected)
            self.assertNotIn('brush_px',sequence[1])
        finally:image.close()

    def test_phase_failure_closes_already_created_previews(self):
        for failure in (OSError('preview failed'),InterruptedError()):
            with self.subTest(failure=type(failure).__name__):
                first=Image.new('RGB',(3,3),'black')
                with patch('SketchFillRenderer.render_sequence_preview',side_effect=[first,failure]):
                    with self.assertRaises(type(failure)):
                        build_phase_previews((3,3),(3,3),[],[(0,0,0)])
                with self.assertRaises(ValueError):first.getpixel((0,0))

    def test_phase_late_cancellation_closes_every_generated_layer(self):
        layers=[]
        def render(*args,**kwargs):
            layers.append(Image.new('RGB',(3,3),'black'))
            return layers[-1]
        with patch('SketchFillRenderer.render_sequence_preview',side_effect=render):
            with self.assertRaises(InterruptedError):
                build_phase_previews((3,3),(3,3),[],[(0,0,0)],cancelled=lambda:len(layers)==3)
        self.assertEqual(len(layers),3)
        for layer in layers:
            with self.assertRaises(ValueError):layer.getpixel((0,0))

    def test_phase_success_forwards_callback_and_transfers_open_layers(self):
        callback=lambda:False
        with patch('SketchFillRenderer.render_sequence_preview',wraps=render_sequence_preview) as render:
            layers=build_phase_previews((3,3),(3,3),[],[(0,0,0)],cancelled=callback)
        try:
            self.assertEqual(len(layers),3)
            self.assertTrue(all(call.kwargs['cancelled'] is callback for call in render.call_args_list))
            for layer in layers.values():self.assertEqual(layer.getpixel((0,0)),(255,255,255))
        finally:
            for layer in layers.values():layer.close()


class HybridPolicyTests(unittest.TestCase):
    def test_unlimited_alias_and_nonfinite_fields_cannot_force_a_short_deadline(self):
        for mode in ('Unlimited', 'Unlimited / Accuracy', 'Off'):
            self.assertIsNone(policies._deadline_seconds({'time_budget_mode': mode, 'time_budget_active': True,
                                                         'deadline_render_budget_seconds': 30}))
        self.assertEqual(policies._deadline_seconds({'time_budget_active': True,
                                                    'deadline_render_budget_seconds': float('inf'),
                                                    'time_budget_seconds': float('nan'), 'max_seconds': 80}), 80)

    def test_explicit_pixel_art_clears_stale_outline_and_cap_without_touching_safety(self):
        with Image.new('RGB', (20, 20), 'red') as source:
            options = {'render_style': policies.HYBRID_RENDER_STYLE, 'hybrid_mode': 'Pixel Art',
                       'outline': True, 'target_stroke_count_resolved': 3, 'armed': False, 'target_lock_passed': False}
            out = policies.apply_hybrid_policy(source, options)
            self.assertFalse(out['outline'])
            self.assertIsNone(out['target_stroke_count_resolved'])
            self.assertFalse(out['armed'])
            self.assertFalse(out['target_lock_passed'])
            self.assertTrue(options['outline'])

    def test_bounded_analysis_converts_only_the_thumbnail_and_keeps_caller_open(self):
        source = Image.new('RGB', (2000, 1000), 'red')
        conversions = []
        real = Image.Image.convert
        def convert(image, *args, **kwargs):
            conversions.append(image.size)
            return real(image, *args, **kwargs)
        try:
            with patch.object(Image.Image, 'convert', new=convert):
                result = policies.analyze_source(source)
            self.assertEqual((result.sampled_width, result.sampled_height), (160, 80))
            self.assertTrue(conversions)
            self.assertTrue(all(max(size) <= 160 for size in conversions))
            self.assertEqual(source.getpixel((0, 0)), (255, 0, 0))
        finally:
            source.close()


if __name__ == '__main__':
    unittest.main()
