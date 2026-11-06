import math
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from CorrectionReviewRecovery import build_correction_review_state
from PostDrawCorrectionPass import _limit_mask, _runs_from_mask, build_post_draw_correction_plan, correction_needed
from SafeCanvasSnapshotScoring import (crop_fitted_canvas, score_final_canvas_snapshot,
                                      trusted_snapshot_evidence, validated_comparison_size)


def evidence(**overrides):
    return {**dict(available=True, trusted=True, feedback_trust='high', actual_coverage_percent=80.,
                  visual_accuracy_percent=85., unexpected_ink_percent=0.), **overrides}


class SnapshotEvidenceBatch02Tests(unittest.TestCase):
    def test_explicit_negative_or_malformed_evidence_cannot_be_promoted_by_label(self):
        base = evidence()
        for changes in ({'available': False}, {'trusted': False}, {'trusted': 'false'},
                        {'geometry_ok': False}, {'visual_accuracy_percent': math.nan},
                        {'actual_coverage_percent': 101}, {'unexpected_ink_percent': '0'}):
            with self.subTest(changes=changes):
                meta = {**base, **changes}
                self.assertFalse(trusted_snapshot_evidence(meta))
                self.assertFalse(correction_needed(meta)[0])
        self.assertTrue(trusted_snapshot_evidence({'feedback_trust': 'high', 'actual_coverage_percent': 90}))

    def test_crop_rejects_nonfinite_negative_and_overlarge_fitted_geometry(self):
        with Image.new('RGB', (12, 12), 'black') as image:
            for area, fitted in (((0, 0, -12, -12), (12, 12)), ((0, 0, 12, 12), (math.nan, 12)),
                                 ((0, 0, 12, 12), (13, 12)), ((math.inf, 0, 12, 12), (12, 12))):
                with self.subTest(area=area, fitted=fitted), self.assertRaises(ValueError):
                    crop_fitted_canvas(image, area=area, fitted=fitted)
            result = score_final_canvas_snapshot(snapshot=image, original_source=image,
                area=(0, 0, -12, -12), fitted=(math.nan, math.nan))
            self.assertFalse(result['available'])
            self.assertFalse(result['trusted'])

    def test_comparison_budget_is_validated_before_crop_allocation(self):
        with Image.new('RGB', (12, 12), 'black') as image:
            with patch('SafeCanvasSnapshotScoring.crop_fitted_canvas', side_effect=AssertionError('allocation')):
                result = score_final_canvas_snapshot(snapshot=image, original_source=image,
                    area=(0, 0, 12, 12), fitted=(12, 12), comparison_size=(100_000, 100_000))
            self.assertFalse(result['available'])
            self.assertIn('bounded', result['reason'])
        self.assertEqual(validated_comparison_size((np.int64(12), 12)), (12, 12))
        for size in ((True, 12), (12.5, 12), (0, 12)):
            with self.assertRaises(ValueError):
                validated_comparison_size(size)

    def test_transparent_simulation_is_compared_as_visible_white(self):
        with Image.new('RGBA', (12, 12), (0, 0, 0, 0)) as source, Image.new('RGB', (12, 12), 'white') as snapshot:
            result = score_final_canvas_snapshot(snapshot=snapshot, original_source=source,
                area=(0, 0, 12, 12), fitted=(12, 12), simulated_final=source, quantized_target=source)
            self.assertTrue(result['trusted'])
            self.assertEqual(result['expected_foreground_pixels'], 0)
            self.assertEqual(result['actual_vs_simulated_visual_percent'], 100)

    def test_missing_visual_measurement_cannot_be_reported_as_verified(self):
        with Image.new('RGB', (12, 12), 'black') as image:
            with patch('SafeCanvasSnapshotScoring.evaluate_preview', return_value={}):
                result = score_final_canvas_snapshot(snapshot=image, original_source=image,
                    area=(0, 0, 12, 12), fitted=(12, 12))
            self.assertFalse(result['available'])
            self.assertFalse(result['trusted'])

    def test_scoring_preserves_cancellation_and_releases_private_crop(self):
        with Image.new('RGB', (12, 12), 'black') as source:
            crop = source.copy()
            with patch('SafeCanvasSnapshotScoring.crop_fitted_canvas', return_value=(crop, {'geometry_ok': True})), \
                 patch('SafeCanvasSnapshotScoring.evaluate_preview', side_effect=InterruptedError('cancelled')):
                with self.assertRaises(InterruptedError):
                    score_final_canvas_snapshot(snapshot=source, original_source=source,
                        area=(0, 0, 12, 12), fitted=(12, 12))
            with self.assertRaises(ValueError):
                crop.getpixel((0, 0))
            self.assertEqual(source.getpixel((0, 0)), (0, 0, 0))


class CorrectionPlanningBatch02Tests(unittest.TestCase):
    def setUp(self):
        self.source = Image.new('RGB', (12, 12), 'black')
        self.actual = Image.new('RGB', (12, 12), 'white')
        self.base = dict(original_source=self.source, actual_canvas=self.actual, palette_rgb=[(0, 0, 0)],
                         post_draw_meta=evidence(), options={'gpu_mode': 'CPU', 'brush_px': 1},
                         max_area_fraction=1, max_pixels=144)

    def tearDown(self):
        self.source.close(); self.actual.close()

    def test_tied_cutoff_keeps_strictly_higher_error_pixels(self):
        mask, count, _ = _limit_mask(np.ones((1, 3), bool), np.array([[1, 1, 2]], np.float32),
                                     max_pixels=2, max_fraction=1)
        np.testing.assert_array_equal(mask, [[True, False, True]])
        self.assertEqual(count, 2)

    def test_zero_caps_disable_correction_and_fraction_never_rounds_up(self):
        for changes in ({'max_pixels': 0}, {'max_paths': 0}, {'max_area_fraction': 0}):
            result = build_post_draw_correction_plan(**{**self.base, **changes})
            self.assertFalse(result['enabled'])
        _, count, _ = _limit_mask(np.ones((1, 5), bool), np.ones((1, 5)), max_pixels=5, max_fraction=.3)
        self.assertEqual(count, 1)

    def test_invalid_palette_or_caps_do_not_create_corrections(self):
        for changes in ({'palette_rgb': [(math.nan, 0, 0)]}, {'palette_rgb': [(0, 0)]},
                        {'palette_rgb': [(300, 0, 0)]}, {'max_paths': -1}, {'max_pixels': True},
                        {'max_area_fraction': math.inf}):
            result = build_post_draw_correction_plan(**{**self.base, **changes})
            self.assertFalse(result['enabled'])
            self.assertFalse(result['safe'])

    def test_uncertain_snapshot_geometry_blocks_corrections(self):
        with Image.new('RGB', (120, 4), 'white') as snapshot:
            result = build_post_draw_correction_plan(**{**self.base, 'actual_canvas': None,
                'snapshot': snapshot, 'area': (0, 0, 12, 12), 'fitted': (12, 12)})
        self.assertFalse(result['enabled'])
        self.assertFalse(result['safe'])

    def test_single_path_must_fit_budget_and_invalid_timing_is_rejected(self):
        result = build_post_draw_correction_plan(**self.base, usable_deadline_seconds=4,
            elapsed_seconds=1, estimated_seconds_per_path=100)
        self.assertFalse(result['enabled'])
        for seconds in (-5, 0, math.nan, math.inf):
            with self.subTest(seconds=seconds):
                result = build_post_draw_correction_plan(**self.base, estimated_seconds_per_path=seconds)
                self.assertFalse(result['enabled'])
                self.assertFalse(result['safe'])

    def test_exact_path_budget_has_no_minimum_five_percent_overrun(self):
        arr = np.full((20, 20, 3), 255, np.uint8); arr[::2, ::2] = 0
        with Image.fromarray(arr) as source, Image.new('RGB', (20, 20), 'white') as actual:
            with patch('PostDrawCorrectionPass.monotonic', return_value=0):
                result = build_post_draw_correction_plan(**{**self.base, 'original_source': source,
                    'actual_canvas': actual, 'max_pixels': 400}, usable_deadline_seconds=3,
                    elapsed_seconds=0, estimated_seconds_per_path=1)
            self.assertTrue(result['enabled'])
            self.assertEqual(result['correction_paths'], 2)
            self.assertEqual(result['estimated_seconds'], 2)
            self.assertEqual(result['selected_correction_pixels'], 2)

    def test_analysis_time_is_deducted_from_verified_headroom(self):
        with patch('PostDrawCorrectionPass.monotonic', side_effect=(0, 2.5)):
            result = build_post_draw_correction_plan(**self.base, usable_deadline_seconds=3,
                elapsed_seconds=0, estimated_seconds_per_path=.1)
        self.assertFalse(result['enabled'])

    def test_path_cap_metadata_counts_only_remaining_geometry(self):
        arr = np.full((20, 20, 3), 255, np.uint8); arr[::2, ::2] = 0
        with Image.fromarray(arr) as source, Image.new('RGB', (20, 20), 'white') as actual:
            result = build_post_draw_correction_plan(**{**self.base, 'original_source': source,
                'actual_canvas': actual, 'max_pixels': 400, 'max_paths': 1})
        self.assertEqual(result['selected_correction_pixels'], 1)
        self.assertEqual(result['missing_pixels'], 1)
        self.assertEqual(result['selected_candidate_percent'], 1)

    def test_wide_palette_index_does_not_overflow_int16(self):
        palette = [(255, 255, 255)]*32768 + [(0, 0, 0)]
        result = build_post_draw_correction_plan(**{**self.base, 'palette_rgb': palette})
        self.assertTrue(result['enabled'])
        self.assertEqual(result['color_order'], (32768,))

    def test_palette_distance_tiles_bound_pairs_and_keep_first_equal_color(self):
        sizes = []; original_sum = np.sum
        def sum_spy(values, *args, **kwargs):
            if isinstance(values, np.ndarray) and values.ndim == 3 and values.shape[-1] == 3:
                sizes.append(values.shape[0]*values.shape[1])
            return original_sum(values, *args, **kwargs)
        with patch('PostDrawCorrectionPass.np.sum', side_effect=sum_spy):
            result = build_post_draw_correction_plan(**{**self.base, 'palette_rgb': [(0, 0, 0)]*4096})
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), 262_144)
        self.assertEqual(result['color_order'], (0,))

    def test_unused_palette_colors_do_not_each_scan_the_entire_correction_mask(self):
        count = [0]; original_count = np.count_nonzero
        def count_spy(values, *args, **kwargs):
            if isinstance(values, np.ndarray) and values.shape == (12, 12) and values.dtype == np.bool_:
                count[0] += 1
            return original_count(values, *args, **kwargs)
        with patch('PostDrawCorrectionPass.np.count_nonzero', side_effect=count_spy):
            result = build_post_draw_correction_plan(**{**self.base, 'palette_rgb': [(0, 0, 0)] + [(255, 255, 255)]*511})
        self.assertLess(count[0], 64)
        self.assertEqual(result['selected_correction_pixels'], 144)

    def test_nonfinite_brush_or_one_fitted_axis_cannot_be_clamped_into_valid_geometry(self):
        for changes in ({'options': {'gpu_mode': 'CPU', 'brush_px': math.nan}},
                        {'options': {'gpu_mode': 'CPU', 'brush_px': -1}},
                        {'fitted': (12, math.nan)}, {'fitted': (math.nan, 12)}):
            result = build_post_draw_correction_plan(**{**self.base, **changes})
            self.assertFalse(result['enabled']); self.assertFalse(result['safe'])

    def test_private_canvas_is_closed_on_early_rejection(self):
        owned = self.actual.copy()
        with patch('PostDrawCorrectionPass._extract_actual_canvas', return_value=(owned, {'geometry_ok': False})):
            result = build_post_draw_correction_plan(**self.base)
        self.assertFalse(result['enabled'])
        with self.assertRaises(ValueError):
            owned.getpixel((0, 0))
        self.assertEqual(self.actual.getpixel((0, 0)), (255, 255, 255))

    def test_row_run_scan_checks_cancellation_inside_long_row(self):
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] >= 2
        with self.assertRaises(InterruptedError):
            _runs_from_mask(np.ones((1, 20_000), bool), cancelled)


class CorrectionReviewBatch02Tests(unittest.TestCase):
    def test_negative_reason_text_does_not_turn_failure_into_success(self):
        result = build_correction_review_state({'post_draw_accuracy_meta': evidence(),
            'post_draw_correction_meta': {'enabled': False, 'safe': True, 'reason': 'result is not within correction gates'}})
        self.assertEqual(result['state'], 'correction_skipped')

    def test_latest_untrusted_post_correction_result_requires_review(self):
        result = build_correction_review_state({'post_draw_accuracy_meta': evidence(),
            'post_draw_correction_meta': {'enabled': True, 'safe': True, 'executed_paths': 1,
                'correction_paths': 1, 'post_correction_trust': 'none',
                'post_correction_visual_accuracy_percent': 99., 'post_correction_actual_coverage_percent': 99.}},
            can_snapshot=True, strict_safety_ready=True, full_start_unlocked=True)
        self.assertEqual(result['state'], 'manual_review_required')
        self.assertFalse(result['actions']['retry_correction_only']['enabled'])

    def test_retry_hints_require_booleans_and_consistent_trust(self):
        opts = {'post_draw_accuracy_meta': evidence()}
        for args in ({'can_snapshot': 'false', 'strict_safety_ready': True, 'full_start_unlocked': True},
                     {'can_snapshot': True, 'strict_safety_ready': 'false', 'full_start_unlocked': True},
                     {'can_snapshot': True, 'strict_safety_ready': True, 'full_start_unlocked': 'false'}):
            result = build_correction_review_state(opts, **args)
            self.assertFalse(result['actions']['retry_correction_only']['enabled'])
        opts['post_draw_accuracy_meta']['trusted'] = False
        result = build_correction_review_state(opts, can_snapshot=True, strict_safety_ready=True, full_start_unlocked=True)
        self.assertFalse(result['actions']['retry_correction_only']['enabled'])


if __name__ == '__main__':
    unittest.main()
