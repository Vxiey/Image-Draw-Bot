import math
import random
import tracemalloc
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import AdaptiveBrushEngine as brushes
import PreviewDetailEngine as detail
import PreviewDiagnostics as diagnostics
import SafetyDebugOverlay as debug
from CanvasGuard import CanvasGuard
from EdgeBehavior import apply_edge_behavior


def brush_plan(**changes):
    return {**{'profile_key': 'gartic-phone', 'nominal_sizes': [2, 4, 8, 16],
               'control_positions': [[10, 10], [20, 10], [30, 10], [40, 10]],
               'target_position': [20, 10], 'confidence': .95, 'safe_guard_px': 8,
               'verified_sizes': [2, 4, 8, 16]}, **changes}


class BrushEvidenceBatch02Tests(unittest.TestCase):
    def test_foreign_profile_plan_cannot_enable_brush_switches(self):
        self.assertEqual(brushes.verified_brush_sizes('skribbl', brush_plan(), 4), ((4,), False))

    def test_invalid_coordinates_or_confidence_disable_dynamic_brushes(self):
        for changes in ({'confidence': math.inf}, {'confidence': math.nan}, {'confidence': 1.1},
                        {'target_position': [math.nan, 10]}, {'target_position': [99, 99]},
                        {'control_positions': [None]*4}, {'control_positions': [[10, 10]]*4},
                        {'nominal_sizes': [2, 4, 8, math.inf]}, {'confidence': True},
                        {'nominal_sizes': [2, 4, 8, -16]}, {'nominal_sizes': [2, 4, 8, 16.5]},
                        {'target_position': '12'}, {'target_position': ['20', 10]},
                        {'target_position': [20.0, 10]},
                        {'control_positions': [[10.5, 10], [20, 10], [30, 10], [40, 10]]}):
            with self.subTest(changes=changes):
                self.assertEqual(brushes.verified_brush_sizes('gartic-phone', brush_plan(**changes), 4), ((4,), False))
        negative=brush_plan(control_positions=[[-40, -10], [-30, -10], [-20, -10], [-10, -10]],
                            target_position=[-30, -10])
        self.assertEqual(brushes.verified_brush_sizes('gartic-phone', negative, 4), ((2, 4, 8, 16), True))

    def test_explicit_verified_subset_and_empty_evidence_are_authoritative(self):
        for changes, expected in (({'verified_sizes': []}, ((4,), False)),
                                  ({'verified_sizes': [4]}, ((4,), False)),
                                  ({'verified_sizes': [2, 8], 'verified_indices': [0, 2]}, ((2, 8), True)),
                                  ({'verified_sizes': [2, 4, 8], 'verified_indices': [1]}, ((4,), False))):
            self.assertEqual(brushes.verified_brush_sizes('gartic-phone', brush_plan(**changes), 4), expected)
        legacy = brush_plan(); legacy.pop('verified_sizes'); legacy['safe_guard_px'] = 1
        self.assertEqual(brushes.verified_brush_sizes('gartic-phone', legacy, 1), ((1,), False))


class PreviewDiagnosticsBatch02Tests(unittest.TestCase):
    def test_segment_clipping_matches_independent_pillow_raster(self):
        rng = random.Random(4218)
        lines = [(-100, -1, 100, 19)] + [tuple(rng.randint(-100, 100) for _ in range(4)) for _ in range(300)]
        for line in lines:
            with Image.new('RGB', (19, 13), 'white') as expected:
                ImageDraw.Draw(expected).line(line, fill='black', width=1)
                with diagnostics.render_quantized_target((19, 13), [[line]], [(0, 0, 0)]) as actual:
                    np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected), err_msg=str(line))

    def test_huge_off_canvas_diagonal_is_clipped_without_rewriting_slope(self):
        huge = 10**100
        with diagnostics.render_quantized_target((17, 13), [[(-huge, -huge, huge, huge)]], [(0, 0, 0)]) as actual:
            expected = np.full((13, 17, 3), 255, dtype=np.uint8)
            expected[np.arange(13), np.arange(13)] = 0
            np.testing.assert_array_equal(np.asarray(actual), expected)

    def test_offscreen_or_inverted_fill_spans_do_not_paint_border(self):
        regions = [{'color_index': 0, 'row_spans': [(5, 30, 40), (6, -20, -10), (7, 10, 5)]},
                   {'color_index': 0, 'bbox': (30, 5, 40, 8)}]
        with diagnostics.render_quantized_target((20, 20), [], [(0, 0, 0)], fill_regions=regions) as actual:
            self.assertEqual(actual.getextrema(), ((255, 255),)*3)

    def test_transparent_targets_and_heatmaps_use_visible_pixels(self):
        with Image.new('RGBA', (12, 12), (1, 2, 3, 0)) as transparent, Image.new('RGB', (12, 12), 'white') as white:
            with diagnostics.render_quantized_target((6, 6), [], [], explicit_target=transparent) as target:
                self.assertEqual(target.getextrema(), ((255, 255),)*3)
            heat, meta = diagnostics.render_delta_e_heatmap(transparent, white, normalized_source=transparent, gpu_mode='CPU')
            heat.close()
            self.assertEqual(meta['max_delta_e_oklab'], 0)
            heat, meta = diagnostics.render_delta_e_heatmap(white, transparent, gpu_mode='CPU')
            heat.close()
            self.assertEqual(meta['max_delta_e_oklab'], 0)
            self.assertEqual(transparent.getpixel((0, 0)), (1, 2, 3, 0))

    def test_heatmap_requires_finite_positive_scale(self):
        with Image.new('RGB', (2, 2)) as source:
            for scale in (0, -1, math.nan, math.inf, True):
                with self.subTest(scale=scale), self.assertRaises(ValueError):
                    diagnostics.render_delta_e_heatmap(source, source, full_error=scale, gpu_mode='CPU')

    def test_diagnostics_handle_unknown_eta_and_invalid_timing_samples(self):
        from PerformanceProfiler import PHASES
        timings = {PHASES[0]: math.nan, PHASES[1]: -2, PHASES[2]: 3.5, 'unknown': 99}
        result = diagnostics.build_preview_diagnostics(None, draw_time={'projected_seconds': math.nan},
                                                       performance_profile={'timings': timings})
        self.assertIsNone(result['performance']['projected_draw_seconds'])
        self.assertEqual(result['performance']['slowest_planning_phase'], PHASES[2])
        result = diagnostics.build_preview_diagnostics({}, performance_profile={'timings': [1]})
        self.assertIsNone(result['performance']['slowest_planning_phase'])

    def test_fresh_correction_history_is_shared_with_review_without_mutating_options(self):
        old = {'summary': {'latest_state': 'old'}}; fresh = {'summary': {'latest_state': 'new'}}
        options = {'correction_history_meta': old}
        seen = []
        def review(opts, **kw):
            seen.append(opts['correction_history_meta']); return {}
        with patch('CorrectionHistory.load_correction_history', return_value=fresh), \
             patch('CorrectionReviewRecovery.build_correction_review_state', side_effect=review):
            result = diagnostics.build_preview_diagnostics(options)
        self.assertEqual(result['correction_history'], fresh)
        self.assertEqual(seen, [fresh])
        self.assertIs(options['correction_history_meta'], old)

    def test_target_cancellation_before_allocation_and_inside_long_fill(self):
        with patch.object(diagnostics.Image, 'new', side_effect=AssertionError('allocated')):
            with self.assertRaises(InterruptedError):
                diagnostics.render_quantized_target((10, 10), [], [], cancelled=lambda: True)
        target = Image.new('RGB', (10, 10), 'white'); calls = [0]
        def cancelled():
            calls[0] += 1; return calls[0] >= 4
        with patch.object(diagnostics.Image, 'new', return_value=target):
            with self.assertRaises(InterruptedError):
                diagnostics.render_quantized_target((10, 10), [], [(0, 0, 0)],
                    fill_regions=[{'color_index': 0, 'row_spans': [(5, 0, 9)]*2048}], cancelled=cancelled)
        with self.assertRaises(ValueError): target.getpixel((0, 0))


class PreviewAllocationBatch02Tests(unittest.TestCase):
    def test_debug_sampling_has_bounded_allocations_and_retains_endpoints(self):
        points = [(i, i % 13) for i in range(100_000)]
        tracemalloc.start()
        try:
            sampled = debug._limit_path(points)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 50_000)
        self.assertEqual(sampled[0], points[0]); self.assertEqual(sampled[-1], points[-1])
        self.assertLessEqual(len(sampled), 80)

    def test_debug_event_total_subpath_sample_is_bounded_but_metadata_is_complete(self):
        paths = tuple(((i, 0), (i, 1), (i, 2)) for i in range(100))
        event = debug.make_debug_event(0, 0, ((0, 0), (0, 1)), SimpleNamespace(strategy='adaptive_boundary', subpaths=paths))
        self.assertLessEqual(sum(len(p) for p in event.output_subpaths), 80)
        self.assertEqual(event.output_points, 300)
        self.assertEqual(event.output_subpaths[0][0], (0, 0))
        self.assertEqual(event.output_subpaths[-1][-1], (99, 2))

    def test_saturated_debug_log_keeps_counts_without_building_discarded_events(self):
        meta = {'debug_events': [None]*debug.MAX_DEBUG_EVENTS}
        result = SimpleNamespace(strategy='safe_skip')
        with patch.object(debug, 'make_debug_event', side_effect=AssertionError('unused sample')):
            debug.record_debug_event(meta, 200, 0, ((0, 0),), result)
        self.assertEqual(meta['debug_counts']['skipped'], 1)
        self.assertEqual(meta['debug_events_truncated'], 1)

    def test_edge_clipping_observes_cancellation_during_large_path(self):
        guard = CanvasGuard.from_area((0, 0, 100, 100))
        points = [(10, 10)]*10_000; calls = [0]
        def cancelled():
            calls[0] += 1; return calls[0] >= 3
        with self.assertRaises(InterruptedError):
            apply_edge_behavior(guard, points, cancelled=cancelled)
        self.assertEqual(calls[0], 3)

    def test_preview_resampling_preserves_legacy_rgba_raster_in_all_supported_modes(self):
        rng = np.random.default_rng(713)
        with Image.fromarray(rng.integers(0, 256, (43, 61, 4), dtype=np.uint8)) as rgba:
            for mode in ('RGB', 'RGBA', 'L', 'LA', 'P'):
                with rgba.convert(mode) as image, image.convert('RGBA') as expanded:
                    with expanded.resize((19, 13), Image.Resampling.LANCZOS) as expected, detail._resize_rgba(image, (19, 13)) as actual:
                        np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected), err_msg=mode)

    def test_gray_preview_ignores_hidden_rgb(self):
        with Image.new('RGBA', (30, 20), (0, 0, 0, 0)) as source:
            with detail.detail_aware_resize_gray(source, (12, 8)) as gray:
                self.assertEqual(gray.getextrema(), (255, 255))

    def test_detail_cancellation_closes_private_resizes_without_closing_source(self):
        images = []; stop = [False]
        original = detail._resize_rgba
        def resize(image, size):
            result = original(image, size); images.append(result); return result
        def extreme(*args):
            stop[0] = True
            return np.zeros((8, 12, 3), np.float32), np.zeros((8, 12), np.float32)
        with Image.new('RGBA', (30, 20), 'black') as source:
            with patch.object(detail, '_resize_rgba', side_effect=resize), patch.object(detail, '_cell_extreme', side_effect=extreme):
                with self.assertRaises(InterruptedError):
                    detail.detail_aware_resize(source, (12, 8), cancelled=lambda: stop[0])
            for private in images:
                with self.assertRaises(ValueError): private.getpixel((0, 0))
            self.assertEqual(source.getpixel((0, 0)), (0, 0, 0, 255))


if __name__ == '__main__':
    unittest.main()
