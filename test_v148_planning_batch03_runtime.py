from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from DeadlineScheduler import DeadlineScheduler, PANIC
from ExecutionCostModel import ExecutionCostModel
from Precision import precision_path, round_screen
from Precision import CanvasTransform
import AdaptiveDeadlineRenderer as adaptive


class TypedDeadlineOperationsTests(unittest.TestCase):
    @staticmethod
    def row(serial, importance, operation="long_stroke", color=0, phase="structure"):
        return {"serial": serial, "importance": importance, "structural_score": importance,
                "operation_type": operation, "color_index": color, "brush_px": 1,
                "deadline_phase": phase, "path": ((0, serial), (20, serial)),
                "estimated_cost_seconds": .2}

    def replan(self, rows):
        scheduler = DeadlineScheduler(rows, start_time=0, budget_seconds=30, clock=lambda: 0)
        scheduler._set_mode(PANIC)
        return scheduler, scheduler.replan_remaining(rows, force=True)

    def test_real_adaptive_operation_types_can_prioritize_structure(self):
        for operation in ("dot", "short_stroke", "long_stroke", "outline", "stroke"):
            with self.subTest(operation=operation):
                _, result = self.replan([self.row(0, .2, operation), self.row(1, .95, operation)])
                self.assertEqual([row["serial"] for row in result], [1, 0])

    def test_ui_barriers_and_adjacent_typed_colour_transitions_are_preserved(self):
        barrier = {"operation_type": "verification", "estimated_cost_seconds": .1}
        rows = [self.row(0, .5, "dot", color=0, phase="major_coverage"), barrier,
                self.row(1, .2, "outline", color=0), self.row(2, .95, "long_stroke", color=1),
                self.row(3, .5, "short_stroke", color=1, phase="accuracy")]
        scheduler, result = self.replan(rows)
        self.assertEqual(result, rows)
        self.assertEqual(scheduler.replan_rejected_switch_cost, 1)
        self.assertEqual(scheduler._transition_count(result), 1)


class NativePrecisionCostTests(unittest.TestCase):
    def model(self, precision="Ultra", **extra):
        return ExecutionCostModel({"profile_key": "gartic-phone", "precision": precision,
                                   "delay": .006, "speed": "Balanced",
                                   "_execution_cost_calibration_override": {}, **extra},
                                  (101, 101), (101, 101))

    def test_precision_caps_are_counted_like_native_delivery(self):
        expected = {"Normal": 9, "High": 25, "Ultra": 50}
        for precision, moves in expected.items():
            model = self.model(precision)
            self.assertEqual(model.path_cost(((0, 0), (100, 0))).moves, moves)
        self.assertGreater(self.model("Ultra").draw_seconds_per_px,
                           self.model("Normal").draw_seconds_per_px)

    def test_scaled_pixel_centres_and_duplicate_positions_match_execution(self):
        path = ((0, 0), (1, 0), (2, 1), (100, 50), (99, 49))
        for scale_x, scale_y in ((.25, .4), (2.5, 1.3), (.01, .01)):
            model = self.model(_execution_scale_x=scale_x, _execution_scale_y=scale_y)
            points = [(round_screen((x + .5) * scale_x - .5),
                       round_screen((y + .5) * scale_y - .5)) for x, y in path]
            expected = sum(len(precision_path(a, b, "Ultra", model.delivery.step_px))
                           for a, b in zip(points, points[1:]))
            self.assertEqual(model.path_cost(path).moves, expected)

    def test_measured_switch_equal_to_default_is_not_scaled_again(self):
        cold = self.model()
        base = cold.switch_cost("palette_change")
        model = self.model(_execution_cost_calibration_override={
            "samples": 3, "ratio": 2.0,
            "operation_runtime": {"palette_change": {"average_seconds": base, "observations": 3}}})
        self.assertEqual(model.switch_cost("palette_change"), base)
        self.assertEqual(model.switch_cost("verification"), cold.switch_cost("verification") * 2)


class OrderedDeadlineDeliveryTests(unittest.TestCase):
    def test_each_custom_colour_revisit_includes_dialog_but_verifies_colour_once(self):
        entries=[adaptive.DeadlineEntry(color,((index,0),),index,.1,.8,.8,.8,
                                       'structure',False,(index,0),'dot')
                 for index,color in enumerate((0,1,0))]
        kept,metadata=adaptive._fit_ordered_delivery(entries,CanvasTransform(3,1,(3,1)),
            palette_seconds=.2,multiplier=1,fixed_seconds=0,reserve_seconds=0,budget_seconds=10,
            color_extras={0:(.78,.3),1:(0,.3)})
        self.assertEqual(len(kept),3)
        self.assertAlmostEqual(metadata['ordered_custom_color_seconds'],1.56)
        self.assertAlmostEqual(metadata['ordered_verification_seconds'],.6)
        self.assertAlmostEqual(sum(row.estimated_cost_seconds for row in kept),.3+.6+1.56+.6+.00009)

    def test_repeated_colour_switches_are_budgeted_before_returning_the_plan(self):
        entries = [adaptive.DeadlineEntry(index % 2, ((index * 100, 0),), index, .2,
                   .9 if index % 2 == 0 else .1, .9, .9 if index % 2 == 0 else .1,
                   'structure' if index % 2 == 0 else 'correction', bool(index % 2), (index * 100, 0), 'dot')
                   for index in range(4)]
        # Counting just two distinct swatches says this fits exactly:
        self.assertAlmostEqual(1 + .8 + 2 * .5 + .2, 3)
        kept, metadata = adaptive._fit_ordered_delivery(entries, CanvasTransform(400, 1, (400, 1)),
            palette_seconds=.5, multiplier=1, fixed_seconds=1, reserve_seconds=.2, budget_seconds=3)
        self.assertEqual([entry.source_index for entry in kept], [0, 2])
        self.assertEqual(metadata['trimmed_for_delivery_cost'], 2)
        self.assertEqual(metadata['ordered_palette_changes'], 1)
        expected = .2 + .5 + .2 + 200 * .000045
        self.assertAlmostEqual(sum(entry.estimated_cost_seconds for entry in kept), expected)
        self.assertLessEqual(1 + expected + .2, 3)

    def test_deadline_planning_reuses_one_timing_context(self):
        options = {'time_budget_mode': 'Detailed 120 s', 'gpu_mode': 'CPU',
                   'paint_current_color': True, 'delay': .001}
        with Image.new('RGB', (20, 20), 'black') as image:
            groups = [[((i % 20, i // 20),) for i in range(100)]]
            with patch.object(adaptive, '_path_timing', wraps=adaptive._path_timing) as timing, \
                    patch.object(adaptive, 'build_importance_map', return_value=(np.ones((20, 20), np.float32), {})), \
                    patch.object(adaptive, '_calibration_guard', return_value=(0, {'cost_multiplier': 1})):
                _, sequence, meta, _ = adaptive.adapt_execution_plan(image, image.size, groups, options)
            timing.assert_called_once()
            self.assertEqual(len(sequence), 100)
            self.assertEqual(meta['operation_counts']['palette_change'], 0)

    def test_cancellation_during_local_batching_is_not_ignored(self):
        entries = [adaptive.DeadlineEntry(0, ((i, 0),), i, .1, .5, .5, .5,
                                         'structure', False, (i, 0)) for i in range(100)]
        with self.assertRaises(InterruptedError):
            adaptive._local_batch(entries, cancelled=lambda: True)


if __name__ == "__main__":
    unittest.main()
