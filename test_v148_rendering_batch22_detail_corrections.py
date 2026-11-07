"""Pixel corrections preserve already correct detail with the available brush."""
from contextlib import ExitStack, closing
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

from AdaptiveBrushEngine import assign_adaptive_brushes
import PixelAccuracyEngine as accuracy
from PixelStrokeEngine import build_pixel_stroke_plan
from test_pixel_accuracy_engine_v1088 import entry, pm_from_index
from test_v148_accuracy_batch12_context import public_options
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_physical import replay_executor


PALETTE = ((255, 255, 255), (0, 0, 0), (255, 0, 0))
ASSET = Path(__file__).parent / 'golden-regression/small-detail-preservation.png'


def detail_map(size=(7, 7)):
    width, height = size
    labels = np.full((height, width), 2, np.int16)
    labels[height // 2, width // 2] = 1
    protected = labels == 1
    return pm_from_index(labels, protected=protected,
                         edges=protected.astype(np.float32),
                         importance=np.where(protected, 1., .1))


def protected_losses(pixel_map, before, after):
    desired = pixel_map.palette_index
    return int(np.count_nonzero(np.asarray(pixel_map.protected_mask, bool) &
        np.asarray(pixel_map.drawable_mask, bool) & (before == desired) & (after != desired)))


class ProtectedCorrectionTests(unittest.TestCase):
    def test_component_planner_corrections_keep_the_correct_protected_center(self):
        pixel_map = detail_map()
        component_plan = build_pixel_stroke_plan(pixel_map, len(PALETTE))
        sequence = assign_adaptive_brushes(component_plan['execution_sequence'],
            default_brush_px=3)['execution_sequence']
        before = accuracy.simulate_strokes(pixel_map, sequence, PALETTE, brush_px=3)
        result = accuracy.refine_with_corrections(pixel_map, sequence, PALETTE, brush_px=3)
        self.assertEqual(before.metrics['pixel_accuracy_percent'], 83.6735)
        self.assertEqual(protected_losses(pixel_map, before.simulated_index,
                                        result['simulation'].simulated_index), 0)
        self.assertEqual(result['simulation'].simulated_index[3, 3], 1)
        self.assertGreaterEqual(result['metadata']['final_accuracy_percent'],
                                before.metrics['pixel_accuracy_percent'])
        self.assertTrue(all(row['brush_px'] == 3 for row in result['execution_sequence']))
        self.assertEqual(result['metadata']['passes'][0]['attempted_protected_pixels_lost'], 1)
        self.assertEqual(result['metadata']['passes'][0]['detail_preserving_retry_paths'], 0)
        self.assertEqual(result['metadata']['passes'][0]['stop_reason'],
                         'no safe protected-detail correction')

    def test_safe_parts_can_repair_missing_pixels_without_erasing_the_detail(self):
        pixel_map = detail_map((13, 9))
        sequence = [dict(entry(1, ((6, 4),), 'cleanup'), brush_px=3)]
        before = accuracy.simulate_strokes(pixel_map, sequence, PALETTE, brush_px=3)
        saved = copy.deepcopy(sequence)
        arrays = [value for value in vars(pixel_map).values() if isinstance(value, np.ndarray)]
        originals = [value.tobytes() for value in arrays]
        for value in arrays:
            value.flags.writeable = False
        result = accuracy.refine_with_corrections(pixel_map, sequence, PALETTE, brush_px=3)
        self.assertEqual(protected_losses(pixel_map, before.simulated_index,
                                        result['simulation'].simulated_index), 0)
        self.assertGreater(result['metadata']['final_accuracy_percent'],
                           before.metrics['pixel_accuracy_percent'])
        self.assertGreater(result['metadata']['correction_paths_added'], 0)
        self.assertEqual(sequence, saved)
        self.assertEqual([value.tobytes() for value in arrays], originals)

    def test_unprotected_and_incorrect_protected_pixels_remain_eligible_for_repair(self):
        for brush in (1, 3):
            for protected in (False, True):
                with self.subTest(brush=brush, protected=protected):
                    pixel_map = pm_from_index([[2] * 9 for _ in range(7)],
                        protected=np.full((7, 9), protected, bool))
                    result = accuracy.refine_with_corrections(pixel_map, [], PALETTE, brush_px=brush)
                    self.assertEqual(result['metadata']['final_accuracy_percent'], 100.)
                    self.assertEqual(result['metadata']['protected_accuracy_percent'], 100.)
                    self.assertEqual(result['metadata']['correction_passes_accepted'], 1)
                    self.assertIsNone(result['metadata']['passes'][0]['detail_preserving_retry_paths'])

    def test_safe_retry_respects_the_remaining_path_budget(self):
        pixel_map = detail_map((17, 13))
        sequence = [dict(entry(1, ((8, 6),), 'cleanup'), brush_px=3)]
        before = accuracy.simulate_strokes(pixel_map, sequence, PALETTE, brush_px=3)
        for remaining in (1, 3, 8, 20):
            with self.subTest(remaining=remaining):
                result = accuracy.refine_with_corrections(pixel_map, sequence, PALETTE,
                    brush_px=3, max_total_paths=len(sequence) + remaining)
                self.assertLessEqual(len(result['execution_sequence']), len(sequence) + remaining)
                self.assertEqual(protected_losses(pixel_map, before.simulated_index,
                                                result['simulation'].simulated_index), 0)

    def test_retry_spans_match_a_literal_stamp_oracle_with_numeric_masks_and_canvas_edges(self):
        rng = np.random.default_rng(1482101)
        for shape in ((1, 13), (11, 1), (9, 17)):
            height, width = shape
            labels = rng.integers(-1, 3, shape, dtype=np.int16)
            pixel_map = pm_from_index(labels, protected=rng.random(shape) > .3)
            pixel_map.protected_mask = pixel_map.protected_mask.astype(np.uint8) * 255
            sequence = [entry(y % 3, ((0, y), (width - 1, y))) for y in range(height)]
            current = accuracy.simulate_strokes(pixel_map, sequence, PALETTE)
            desired = np.where(pixel_map.drawable_mask, pixel_map.palette_index, 0)
            for brush in (1, 2, 3, 4, 17, 20000):
                for color in range(3):
                    for y in (0, height // 2, height - 1):
                        with self.subTest(shape=shape, brush=brush, color=color, y=y):
                            source = [dict(entry(color, ((0, y), (width - 1, y))), brush_px=brush)]
                            actual = accuracy._detail_safe_corrections(pixel_map, current, source, desired,
                                max_paths=None, cancelled=lambda: False)
                            centers = {x for row in actual
                                       for x in range(row['path'][0][0], row['path'][-1][0] + 1)}
                            expected = set()
                            for center in range(width):
                                safe = True
                                for sy in range(max(0, y - (brush - 1) // 2),
                                                min(height, y + brush // 2 + 1)):
                                    for sx in range(max(0, center - (brush - 1) // 2),
                                                    min(width, center + brush // 2 + 1)):
                                        if (pixel_map.drawable_mask[sy, sx] and
                                                pixel_map.protected_mask[sy, sx] and
                                                current.simulated_index[sy, sx] == desired[sy, sx] and
                                                desired[sy, sx] != color):
                                            safe = False
                                if safe:expected.add(center)
                            self.assertEqual(centers, expected)
                            self.assertTrue(all(row['brush_px'] == brush for row in actual))

    def test_wide_retry_joins_safe_runs_across_tiles_and_stays_cancellable(self):
        width = 8207
        pixel_map = pm_from_index([[2] * width for _ in range(3)])
        current = accuracy.simulate_strokes(pixel_map, [], PALETTE)
        desired = pixel_map.palette_index
        corrections = [dict(entry(2, ((0, 1), (width - 1, 1))), brush_px=4)]
        actual = accuracy._detail_safe_corrections(pixel_map, current, corrections, desired,
                                                   max_paths=None, cancelled=lambda: False)
        self.assertEqual(actual, corrections)
        pixel_map.palette_index[1, 4096] = 1
        pixel_map.protected_mask[1, 4096] = True
        current = accuracy.simulate_strokes(pixel_map, [entry(1, ((4096, 1),))], PALETTE)
        actual = accuracy._detail_safe_corrections(pixel_map, current, corrections, desired,
                                                   max_paths=None, cancelled=lambda: False)
        self.assertEqual([row['path'] for row in actual],
                         [((0, 1), (4093, 1)), ((4098, 1), (8206, 1))])
        original = current.simulated_index.copy()
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls == 4
        with self.assertRaises(InterruptedError):
            accuracy._detail_safe_corrections(pixel_map, current, corrections, desired,
                                              max_paths=None, cancelled=cancelled)
        self.assertEqual(calls, 4)
        np.testing.assert_array_equal(current.simulated_index, original)

    def test_stop_during_retry_never_publishes_partial_corrections(self):
        pixel_map = detail_map((13, 9))
        sequence = [dict(entry(1, ((6, 4),), 'cleanup'), brush_px=3)]
        saved = copy.deepcopy(sequence)
        original = pixel_map.palette_index.copy()
        real_filter = accuracy._detail_safe_corrections
        in_retry = False
        def observe(*args, **kwargs):
            nonlocal in_retry
            in_retry = True
            return real_filter(*args, **kwargs)
        with patch.object(accuracy, '_detail_safe_corrections', new=observe), \
                self.assertRaises(InterruptedError):
            accuracy.refine_with_corrections(pixel_map, sequence, PALETTE,
                                            brush_px=3, cancelled=lambda: in_retry)
        self.assertTrue(in_retry)
        self.assertEqual(sequence, saved)
        np.testing.assert_array_equal(pixel_map.palette_index, original)
        # A later call owns a fresh retry and can still accept the safe repairs.
        result = accuracy.refine_with_corrections(pixel_map, sequence, PALETTE, brush_px=3)
        self.assertGreater(result['metadata']['correction_paths_added'], 0)

    def test_comparison_memory_error_retains_the_complete_accepted_plan_and_reports_it(self):
        pixel_map = detail_map()
        component_plan = build_pixel_stroke_plan(pixel_map, len(PALETTE))
        sequence = assign_adaptive_brushes(component_plan['execution_sequence'],
            default_brush_px=3)['execution_sequence']
        expected = accuracy.simulate_strokes(pixel_map, sequence, PALETTE, brush_px=3)
        accepted = []
        rejected = []
        def fail_comparison(_map, current, candidate, _desired, **kwargs):
            accepted.append(current)
            rejected.append(weakref.ref(candidate.simulated_index))
            raise MemoryError('protected comparison workspace')
        with patch.object(accuracy, '_protected_correction_losses', new=fail_comparison):
            result = accuracy.refine_with_corrections(pixel_map, sequence, PALETTE, brush_px=3)
        self.assertIs(result['simulation'], accepted[0])
        self.assertEqual(result['simulation'].metrics, expected.metrics)
        self.assertEqual(result['execution_sequence'], sequence)
        self.assertEqual(result['correction_entries'], [])
        self.assertEqual(result['metadata']['correction_paths_added'], 0)
        self.assertEqual(result['metadata']['final_accuracy_percent'], 83.6735)
        np.testing.assert_array_equal(result['simulation'].simulated_index, expected.simulated_index)
        self.assertTrue(all(reference() is None for reference in rejected))
        attempt, = result['metadata']['passes']
        self.assertFalse(attempt['accepted'])
        self.assertIsNone(attempt['attempted_protected_pixels_lost'])
        self.assertEqual(attempt['correction_resource_stop'],
                         'MemoryError during protected-pixel comparison; kept accepted plan')
        self.assertEqual(attempt['stop_reason'], attempt['correction_resource_stop'])
        # This narrowly optional resource fallback must not hide Stop or defects.
        for error in (InterruptedError('Stop'), ValueError('invalid analysis')):
            with self.subTest(error=type(error).__name__), \
                    patch.object(accuracy, '_protected_correction_losses', side_effect=error), \
                    self.assertRaises(type(error)):
                accuracy.refine_with_corrections(pixel_map, sequence, PALETTE, brush_px=3)

    def test_filter_and_retry_allocation_failures_release_candidates_and_keep_existing_ink(self):
        pixel_map = detail_map((13, 9))
        sequence = [dict(entry(1, ((6, 4),), 'cleanup'), brush_px=3)]
        expected = accuracy.simulate_strokes(pixel_map, sequence, PALETTE, brush_px=3)
        real_comparison = accuracy._protected_correction_losses
        real_filter = accuracy._detail_safe_corrections
        real_score = accuracy._score
        for stage in ('span filtering', 'retry simulation'):
            with self.subTest(stage=stage):
                accepted, rejected, allocations = [], [], []
                scores = 0
                def comparison(_map, current, candidate, desired, **kwargs):
                    accepted.append(current)
                    rejected.append(weakref.ref(candidate.simulated_index))
                    return real_comparison(_map, current, candidate, desired, **kwargs)
                def fail_zeros(shape, *args, **kwargs):
                    allocations.append(shape)
                    raise MemoryError('optional correction workspace')
                def filter_spans(*args, **kwargs):
                    if stage == 'span filtering':
                        with patch.object(accuracy.np, 'zeros', new=fail_zeros):
                            return real_filter(*args, **kwargs)
                    return real_filter(*args, **kwargs)
                def score(_map, simulated, *args, **kwargs):
                    nonlocal scores
                    scores += 1
                    if stage == 'retry simulation' and scores == 3:
                        rejected.append(weakref.ref(simulated))
                        with patch.object(accuracy.np, 'zeros', new=fail_zeros):
                            return real_score(_map, simulated, *args, **kwargs)
                    return real_score(_map, simulated, *args, **kwargs)
                with patch.object(accuracy, '_protected_correction_losses', new=comparison), \
                        patch.object(accuracy, '_detail_safe_corrections', new=filter_spans), \
                        patch.object(accuracy, '_score', new=score):
                    result = accuracy.refine_with_corrections(pixel_map, sequence, PALETTE, brush_px=3)
                self.assertEqual(len(allocations), 1)
                self.assertIs(result['simulation'], accepted[0])
                self.assertEqual(result['simulation'].metrics, expected.metrics)
                self.assertEqual(result['execution_sequence'], sequence)
                self.assertEqual(result['metadata']['correction_paths_added'], 0)
                np.testing.assert_array_equal(result['simulation'].simulated_index, expected.simulated_index)
                np.testing.assert_array_equal(result['simulation'].coverage_count, expected.coverage_count)
                self.assertTrue(all(reference() is None for reference in rejected))
                attempt, = result['metadata']['passes']
                self.assertFalse(attempt['accepted'])
                self.assertGreater(attempt['attempted_protected_pixels_lost'], 0)
                self.assertEqual(attempt['protected_pixels_lost'], 0)
                self.assertEqual(attempt['stop_reason'],
                    f'MemoryError during protected-detail {stage}; kept accepted plan')
                self.assertEqual(attempt['correction_resource_stop'], attempt['stop_reason'])

    def test_existing_asset_public_plan_preserves_detail_in_actual_executor_actions(self):
        from DrawBot import make_plan
        real_refine = accuracy.refine_with_corrections
        for brush in (3, 4):
            with self.subTest(brush=brush), ExitStack() as stack:
                asset = stack.enter_context(closing(Image.open(ASSET)))
                source = stack.enter_context(closing(asset.crop((155, 102, 174, 121))))
                stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
                reference = []
                def without_corrections(pixel_map, *args, **kwargs):
                    reference.append(pixel_map)
                    return real_refine(pixel_map, *args, **dict(kwargs, max_passes=0))
                settings = public_options(brush)
                settings.update(corners=((100, 100), (200, 200)))
                with patch.object(accuracy, 'refine_with_corrections', new=without_corrections):
                    before_plan = make_plan(source, (100, 100), dict(settings))
                stack.callback(close_plan, before_plan, source)
                after_plan = make_plan(source, (100, 100), dict(settings))
                stack.callback(close_plan, after_plan, source)
                self.assertEqual(before_plan['image'].size, (100, 100))
                self.assertEqual(after_plan['image'].size, (100, 100))
                self.assertEqual(before_plan['colors'], after_plan['colors'])
                before, _ = replay_executor(before_plan, (100, 100), (100, 100))
                after, _ = replay_executor(after_plan, (100, 100), (100, 100))
                pixel_map, = reference
                self.assertEqual(protected_losses(pixel_map, before, after), 0)
                self.assertGreater(after_plan['options']['pixel_accuracy_meta']['final_accuracy_percent'],
                                   before_plan['options']['pixel_accuracy_meta']['final_accuracy_percent'])
                self.assertEqual({row['brush_px'] for row in after_plan['execution_sequence']}, {brush})
                attempted = after_plan['options']['pixel_accuracy_meta']['passes']
                self.assertGreater(attempted[0]['attempted_protected_pixels_lost'], 0)
                self.assertEqual(attempted[0]['protected_pixels_lost'], 0)
                self.assertGreater(attempted[0]['detail_preserving_retry_paths'], 0)


if __name__ == '__main__':
    unittest.main()
