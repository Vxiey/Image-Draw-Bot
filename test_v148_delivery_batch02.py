import math
import tracemalloc
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from CanvasGuard import (CanvasAnchor, CanvasGuard, CanvasSafetyStop, SafePolygon, _safe_projection,
                         clip_segment_to_polygon, normalize_canvas_anchors,
                         normalize_canvas_polygon, point_in_polygon)
from SmartRecovery import classify_interruption
from StrokeDelivery import resolve_stroke_delivery
from StrokeDeliveryVerification import inspect_delivery, resolve_policy, retry_parameters
from TimeAwareColorBudget import _marginal_costs, _runtime_average
from VisualVerification import (compare_batch_snapshot, merge_boxes, planned_batch_boxes,
                                planned_batch_points, _contains)


class CanvasGeometryBatch02Tests(unittest.TestCase):
    def test_normalized_subrectangle_is_validated_after_screen_scaling(self):
        result = normalize_canvas_polygon(((.1, .1), (.9, .1), (.9, .6), (.1, .6)),
                                          (100, 200, 1001, 1001), 'normalized')
        self.assertEqual(result, ((200, 300), (1000, 300), (1000, 800), (200, 800)))

    def test_normalized_thin_vertices_are_not_deduplicated_in_fraction_units(self):
        result = normalize_canvas_polygon(((0, 0), (.005, 0), (.005, 1), (0, 1)),
                                          (0, 0, 1001, 1001), 'normalized')
        self.assertEqual(result, ((0, 0), (5, 0), (5, 1000), (0, 1000)))

    def test_polygon_cannot_enlarge_selected_area(self):
        with self.assertRaises(CanvasSafetyStop):
            CanvasGuard.from_area_or_polygon((100, 100, 20, 20),
                polygon=((0, 0), (40, 0), (40, 40), (0, 40)), coordinate_space='area')
        with self.assertRaises(ValueError):
            CanvasGuard.from_polygon(((0, 0), (20, 0), (20, 20), (0, 20)), area=(0, 0, 0, 0))

    def test_auto_anchor_space_is_inferred_for_the_whole_group(self):
        anchors = [{'kind': 'corner', 'center': p} for p in ((0, 1), (99, 1), (99, 99), (1, 99))]
        result = normalize_canvas_anchors(anchors, (100, 200, 100, 100), 'auto')
        self.assertEqual(tuple(a.center for a in result), ((100, 201), (199, 201), (199, 299), (101, 299)))

    def test_nonfinite_and_invalid_anchor_evidence_is_rejected(self):
        for value in (math.nan, math.inf, -math.inf, -1, 2):
            with self.subTest(confidence=value), self.assertRaises(ValueError):
                normalize_canvas_anchors([CanvasAnchor('corner', (10, 10), confidence=value)], coordinate_space='screen')
        with self.assertRaises(ValueError):
            normalize_canvas_anchors([{'kind': 'triangle', 'center': (10, 10), 'orientation': math.nan}], coordinate_space='screen')

    def test_unknown_coordinate_space_is_rejected_without_area(self):
        with self.assertRaises(ValueError):
            normalize_canvas_polygon(((0, 0), (10, 0), (10, 10)), coordinate_space='scren')
        with self.assertRaises(ValueError):
            normalize_canvas_anchors([CanvasAnchor('corner', (10, 10))], coordinate_space='scren')

    def test_fractional_boundary_projection_keeps_valid_integer_dot(self):
        polygon = ((0, 0), (10, 0), (0, 3))
        self.assertEqual(_safe_projection((8, .6), polygon), (8, 0))
        self.assertEqual(clip_segment_to_polygon((8, -5), (8, 5), polygon), (((8, 0), (8, 0)),))

    def test_prepared_membership_matches_reference_at_edges_and_negative_origins(self):
        polygon = [[0, 0], [20, 0], [20, 20], [0, 20]]
        safe = SafePolygon(polygon, polygon, [0, 0, 20, 20], [0, 0, 20, 20])
        polygon[0][0] = 100; polygon.clear()
        self.assertEqual(safe.polygon, ((0, 0), (20, 0), (20, 20), (0, 20)))
        self.assertEqual(safe.safe_polygon, safe.polygon)
        self.assertTrue(safe.contains_safe((10, 10)))
        self.assertEqual(safe.clamp_to_safe((25, 10)), (20, 10))
        for guard in (CanvasGuard.from_area((-30, -50, 50, 70)),
                      CanvasGuard.from_polygon(((0, 20), (20, 0), (40, 20), (20, 40)))):
            for y in range(-55, 55):
                for x in range(-35, 55):
                    self.assertEqual(guard.safe.contains_safe((x, y)), point_in_polygon((x, y), guard.model.safe_polygon))
            for x, y in guard.model.safe_polygon:
                for dx, dy in ((1e-8, 0), (-1e-8, 0), (0, 1e-8), (0, -1e-8)):
                    p = (x+dx, y+dy)
                    self.assertEqual(guard.safe.contains_safe(p), point_in_polygon(p, guard.model.safe_polygon))


class DeliveryPolicyBatch02Tests(unittest.TestCase):
    def test_invalid_delivery_spacing_falls_back_to_finite_profile_policy(self):
        for value in (math.nan, math.inf, -math.inf, 'bad', 10**400):
            for key in ('microsoft-paint', 'skribbl', 'generic'):
                with self.subTest(value=str(value)[:12], key=key):
                    policy = resolve_stroke_delivery({'profile_key': key, 'stroke_step_px': value})
                    self.assertTrue(math.isfinite(policy.step_px))
                    self.assertGreater(policy.step_px, 0)

    def test_retry_never_makes_a_small_step_coarser(self):
        policy = resolve_policy({'profile_key': 'skribbl'})
        for step in (.5, 1, 2, 8):
            retry = retry_parameters(policy, step, .001)
            self.assertGreater(retry['step_px'], 0)
            self.assertLessEqual(retry['step_px'], step)
        for step, delay in ((math.nan, 0), (1, math.inf), (0, 0), (1, -.1)):
            with self.assertRaises(ValueError):
                retry_parameters(policy, step, delay)

    def test_verifier_requires_literal_boolean_match(self):
        class Backend:
            def inspect_ink_segment(self, *args):
                return {'matched': 'false'}
        result = inspect_delivery(Backend(), (0, 0), (20, 0), (0, 0, 0), 1,
                                  resolve_policy({'profile_key': 'skribbl'}))
        self.assertFalse(result['matched'])
        self.assertIn('boolean', result['reason'])

    def test_explicit_stop_and_canvas_exception_override_transient_text(self):
        for error in (KeyboardInterrupt('wrong window is active'), SystemExit('foreground window'),
                      InterruptedError('time limit reached: wrong window is active')):
            self.assertFalse(classify_interruption(error, 'skribbl').recoverable)
        result = classify_interruption(CanvasSafetyStop('mouse was moved manually'), 'skribbl')
        self.assertFalse(result.recoverable)
        self.assertTrue(result.full_stop)

    def test_color_budget_consumes_persisted_ema_format(self):
        item = {'average_seconds': 2.5, 'count': 5, 'observations': 20, 'total_seconds': 0}
        self.assertEqual(_runtime_average(item), 2.5)
        costs = _marginal_costs({'profile_key': 'skribbl', '_time_color_calibration_override': {
            'samples': 20, 'operation_runtime': {'palette_change': item}}}, {})
        self.assertEqual(costs['direct_color_change_seconds'], 2.5)
        self.assertEqual(costs['direct_color_change_source'], 'measured palette_change')
        self.assertEqual(_runtime_average({'count': 4, 'total_seconds': 2}), .5)


class VisualVerificationBatch02Tests(unittest.TestCase):
    def test_empty_outside_or_single_wrong_probe_never_reports_success(self):
        with Image.new('RGB', (20, 20), 'white') as after:
            for points in ([], [(100, 100)], [(10, 10)]):
                result = compare_batch_snapshot(after, None, (0, 0, 20, 20), (0, 0, 0), points, [])
                self.assertFalse(result['ok'])
                self.assertEqual(result['confidence'], 0)

    def test_scaled_snapshot_uses_screen_to_capture_coordinates(self):
        with Image.new('RGB', (20, 20), 'white') as after:
            draw = ImageDraw.Draw(after)
            draw.point((4, 4), fill='black'); draw.point((16, 16), fill='black')
            result = compare_batch_snapshot(after, None, (100, 100, 10, 10), (0, 0, 0),
                                            [(102, 102), (108, 108)], [(100, 100, 109, 109)], brush_px=1)
            self.assertTrue(result['ok'])
            self.assertEqual(result['matched_points'], 2)

    def test_mismatched_baseline_and_invalid_area_are_unavailable(self):
        with Image.new('RGB', (20, 20), 'white') as after, Image.new('RGB', (10, 10), 'white') as before:
            result = compare_batch_snapshot(after, before, (0, 0, 20, 20), (255, 255, 255), [(5, 5)], [])
            self.assertFalse(result['ok'])
            self.assertFalse(result['available'])
            result = compare_batch_snapshot(after, None, (0, 0, math.nan, 20), (255, 255, 255), [(5, 5)], [])
            self.assertFalse(result['ok'])

    def test_sampling_zero_is_empty_and_long_batch_includes_tail(self):
        items = [((i, 0),) for i in range(259)]
        self.assertEqual(planned_batch_points(items, smart_group=True, transform=lambda x, y: (x, y), sample_limit=0), [])
        result = planned_batch_points(items, smart_group=True, transform=lambda x, y: (x, y), sample_limit=130)
        self.assertLessEqual(len(result), 130)
        self.assertEqual(result[0], (0, 0))
        self.assertEqual(result[-1], (258, 0))

    def test_sampler_allocations_remain_bounded_for_large_batch(self):
        items = [((i, 0), (i, 20)) for i in range(10_000)]
        tracemalloc.start()
        try:
            result = planned_batch_points(items, smart_group=True, transform=lambda x, y: (x, y))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLessEqual(len(result), 130)
        self.assertLess(peak, 1_000_000)

    def test_box_union_does_not_hide_l_shaped_or_many_disjoint_gaps(self):
        result = merge_boxes([(0, 0, 10, 2), (0, 0, 2, 10)], max_boxes=1)
        self.assertFalse(_contains((8, 8), result))
        self.assertTrue(_contains((1, 8), result))
        result = merge_boxes([(i*10, 0, i*10+1, 2) for i in range(100)], max_boxes=2)
        self.assertFalse(_contains((5, 1), result))

    def test_outside_change_in_l_shaped_gap_is_detected(self):
        with Image.new('RGB', (20, 20), 'white') as before:
            after = before.copy()
            try:
                draw = ImageDraw.Draw(after)
                draw.rectangle((0, 0, 19, 2), fill='black')
                draw.rectangle((0, 0, 2, 19), fill='black')
                draw.rectangle((8, 8, 18, 18), fill='black')
                result = compare_batch_snapshot(after, before, (0, 0, 20, 20), (0, 0, 0),
                    [(10, 1), (1, 10)], [(0, 0, 19, 2), (0, 0, 2, 19)])
                self.assertIn('outside-change-possible-fill-leak-or-wrong-place', result['issues'])
            finally:
                after.close()

    def test_skinny_capture_grid_has_a_real_sample_bound(self):
        with Image.new('RGB', (10_000, 2), 'white') as image:
            result = compare_batch_snapshot(image, image, (0, 0, 10_000, 2), (255, 255, 255),
                                            [(0, 0), (9999, 1)], [], mode='Fast')
            self.assertLessEqual(result['outside_grid_samples'], 220*9)

    def test_cancellation_is_checked_within_long_sampling_and_before_conversion(self):
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] >= 3
        with self.assertRaises(InterruptedError):
            planned_batch_points([tuple((i, 0) for i in range(10_000))], smart_group=True,
                                 transform=lambda x, y: (x, y), cancelled=cancelled)
        for items in ([((1, 1),)*10_000], [None]*10_000):
            calls[0] = 0
            def later_cancelled():
                calls[0] += 1
                return calls[0] >= 4
            with self.assertRaises(InterruptedError):
                planned_batch_points(items, smart_group=True, transform=lambda x, y: (x, y), cancelled=later_cancelled)
        with Image.new('RGB', (10, 10), 'white') as image:
            with patch.object(image, 'convert', side_effect=AssertionError('allocation before cancellation')):
                with self.assertRaises(InterruptedError):
                    compare_batch_snapshot(image, None, (0, 0, 10, 10), (0, 0, 0), [], [], cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
