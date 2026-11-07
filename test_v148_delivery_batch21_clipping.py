"""Clipping reuses validated geometry without changing delivered subpaths."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import math
import unittest
from unittest.mock import patch

import CanvasGuard as geometry
import DrawBot
from benchmark_v148_probe_geometry import execution_workload


@contextmanager
def no_execution_persistence():
    """Keep the real executor and guards; replace only external write sinks."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(DrawBot, 'log_event'))
        stack.enter_context(patch.object(DrawBot, 'save_runtime_safety_report',
                                        side_effect=lambda session: session.as_dict()))
        for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            stack.enter_context(patch(name, return_value={}))
        yield


class PreparedClippingTests(unittest.TestCase):
    def test_axis_aligned_rectangle_intersections_match_independent_intervals(self):
        rectangle = ((-20, -10), (30, -10), (30, 40), (-20, 40))
        # Axis-aligned integer intervals have exact independently known ends;
        # no production intersection or membership helper supplies this oracle.
        for axis, fixed_values, low, high, orth_low, orth_high in (
                (0, range(-15, 46), -20, 30, -10, 40),
                (1, range(-25, 36), -10, 40, -20, 30)):
            for fixed in fixed_values:
                def point(value):
                    return (value, fixed) if axis == 0 else (fixed, value)
                expected = ((point(low), point(high)),) if orth_low <= fixed <= orth_high else ()
                self.assertEqual(geometry.clip_segment_to_polygon(point(low-7), point(high+9), rectangle), expected)
                reversed_expected = tuple((b, a) for a, b in reversed(expected))
                self.assertEqual(geometry.clip_segment_to_polygon(point(high+9), point(low-7), rectangle), reversed_expected)

    def test_concave_gap_duplicate_point_and_corner_touch_have_explicit_outputs(self):
        u_shape = ((0, 0), (12, 0), (12, 12), (8, 12), (8, 4), (4, 4), (4, 12), (0, 12))
        for polygon in (u_shape, tuple(reversed(u_shape)), u_shape[3:]+u_shape[:3]):
            self.assertEqual(geometry.clip_path_to_polygon(((-2, 6), (14, 6)), polygon),
                             (((0, 6), (4, 6)), ((8, 6), (12, 6))))
            self.assertEqual(geometry.clip_path_to_polygon(((2, 6), (2, 6), (14, 6)), polygon),
                             (((2, 6), (4, 6)), ((8, 6), (12, 6))))
            self.assertEqual(geometry.clip_path_to_polygon(((5, 6),), polygon), ())
            self.assertEqual(geometry.clip_path_to_polygon(((4, 6),), polygon), (((4, 6),),))
        triangle = ((0, 0), (10, 0), (0, 3))
        self.assertEqual(geometry.clip_segment_to_polygon((8, -5), (8, 5), triangle), (((8, 0), (8, 0)),))
        self.assertEqual(geometry.clip_path_to_polygon(((8, .6),), triangle), (((8, 0),),))

    def test_finite_validation_and_unprojectable_integer_polygon_remain_errors(self):
        polygon = ((0, 0), (10, 0), (10, 10), (0, 10))
        for bad in (math.nan, math.inf, -math.inf, 10**400, 'invalid'):
            for operation in (
                    lambda: geometry.clip_path_to_polygon(((bad, 0), (1, 1)), polygon),
                    lambda: geometry.clip_segment_to_polygon((0, 0), (bad, 1), polygon),
                    lambda: geometry.clip_path_to_polygon(((1, 1),), ((0, 0), (bad, 0), (0, 2))),
                    lambda: geometry._safe_projection((bad, 1), polygon)):
                with self.subTest(bad=str(bad)[:20]), self.assertRaises(ValueError):
                    operation()
        tiny = ((.1, .1), (.2, .1), (.2, .2), (.1, .2))
        with self.assertRaises(geometry.CanvasSafetyStop):
            geometry.clip_path_to_polygon(((.15, .15),), tiny)
        with self.assertRaises(geometry.CanvasSafetyStop):
            geometry._safe_projection((.15, .15), tiny)

    def test_stop_retains_input_and_segment_loop_poll_boundaries(self):
        points = tuple((10+(index % 50), 30) for index in range(2048))
        polygon = ((0, 0), (100, 0), (100, 100), (0, 100))
        for stop_at in (1, 2, 4, 6, 8):
            calls = 0
            def cancelled():
                nonlocal calls
                calls += 1
                return calls == stop_at
            with self.subTest(stop_at=stop_at), self.assertRaises(InterruptedError):
                geometry.clip_path_to_polygon(iter(points), polygon, cancelled=cancelled)
            self.assertEqual(calls, stop_at)

    def test_each_operation_observes_new_caller_geometry_without_retained_cache(self):
        polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
        points = ((-2, 5), (20, 5))
        self.assertEqual(geometry.clip_path_to_polygon(points, polygon), (((0, 5), (10, 5)),))
        polygon[1][0] = polygon[2][0] = 15
        self.assertEqual(geometry.clip_path_to_polygon(points, polygon), (((0, 5), (15, 5)),))
        self.assertEqual(points, ((-2, 5), (20, 5)))
        self.assertEqual(polygon, [[0, 0], [15, 0], [15, 10], [0, 10]])

    def test_actual_executor_keeps_all_recorded_actions_and_reduces_validation_work(self):
        # This digest is the complete action/probe list recorded by the actual
        # ec22 executor with these same eight compound paths and fake device.
        # It covers final delivery, not merely a substitute clipping function.
        calls = 0
        original = geometry._float_point
        def counted(point):
            nonlocal calls
            calls += 1
            return original(point)
        with no_execution_persistence(), patch.object(geometry, '_float_point', counted):
            actual = execution_workload(DrawBot.execute_plan)
        self.assertEqual(hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest(),
                         '83bf5da4bda148f6af682881af5682b9e591b6991395e4c8f5080413644148f9')
        self.assertLess(calls, 60000)  # Baseline: 185,152 validations.

    def test_source_outside_canvas_and_moved_cursor_still_block_native_input(self):
        guard = geometry.CanvasGuard.from_area((0, 0, 100, 100), brush_px=3)
        with self.assertRaises(geometry.CanvasSafetyStop):
            guard.clip_path_to_safe_subpaths(((-1, 20), (30, 20)))
        class MovedMouse:
            pressed = False
            def get_position(self): return (-1, 20)
            def press(self): self.pressed = True
        mouse = MovedMouse()
        final = geometry.FinalMouseGuard(mouse, guard)
        with self.assertRaises(geometry.CanvasSafetyStop):
            final.press()
        self.assertFalse(mouse.pressed)


if __name__ == '__main__':
    unittest.main()
