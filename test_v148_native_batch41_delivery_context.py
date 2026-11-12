"""Measured input timings belong to the actual resolved native policy."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import DrawTimeCalibration as timing
from ExecutionCostModel import ExecutionCostModel


class DeliveryTimingContextTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'timing.json'
        self.options = dict(profile_key='microsoft-paint', paint_profile=True,
            precision='High', speed='Fast', brush_px=1, draw_quality='Pixel Accurate',
            pixel_accurate=True, delay=0)

    def record(self, options, ratio):
        result = timing.record_sample(options, 10, 10 * ratio, completed_paths=50,
            operation_runtime={'short_stroke': {'count': 50, 'total_seconds': 10 * ratio}},
            path=self.path)
        self.assertTrue(result['recorded'])
        return result

    def test_distinct_actual_paint_schedules_learn_and_resume_independently(self):
        variants = [dict(self.options, paint_stroke_delivery=mode)
                    for mode in ('Auto', 'Reliable', 'Compatible')]
        cold_costs = [ExecutionCostModel(dict(options,
            _execution_cost_calibration_override={'samples': 0, 'ratio': 1}),
            (100, 100), (100, 100)).path_seconds(((1, 1), (98, 1))) for options in variants]
        self.assertEqual(len(set(cold_costs)), 3)
        self.record(variants[0], 1.2)
        for options in variants[1:]:
            self.assertFalse(timing.correction_for(options, path=self.path)['learned'])
        self.record(variants[1], 1.8)
        self.record(variants[2], .8)
        self.assertEqual(len(timing.load_all(self.path)['profiles']), 3)
        for options, expected in zip(variants, (1.2, 1.8, .8)):
            result = timing.correction_for(options, path=self.path)
            self.assertEqual(result['samples'], 1)
            self.assertAlmostEqual(result['ratio'], expected)
        timing.reset_profile(variants[1], path=self.path)
        self.assertFalse(timing.correction_for(variants[1], path=self.path)['learned'])
        self.assertEqual(timing.correction_for(variants[0], path=self.path)['ratio'], 1.2)
        self.assertEqual(timing.correction_for(variants[2], path=self.path)['ratio'], .8)

    def test_effective_aliases_share_history_but_wait_and_density_changes_do_not(self):
        reliable = dict(self.options, paint_stroke_delivery='Reliable')
        self.record(reliable, 1.4)
        self.assertEqual(timing.correction_for(dict(reliable, paint_stroke_delivery='Dense'),
                                             path=self.path)['ratio'], 1.4)
        self.assertFalse(timing.correction_for(dict(reliable, delay=.2), path=self.path)['learned'])
        generic = dict(self.options, profile_key='generic', paint_profile=False,
                       pixel_accurate=False, draw_quality='Balanced', precision='Normal',
                       stroke_step_px=2)
        self.record(generic, 1.6)
        self.assertFalse(timing.correction_for(dict(generic, stroke_step_px=6), path=self.path)['learned'])
        # Requests above the precision cap produce the same native density.
        capped = dict(generic, stroke_step_px=60)
        self.record(capped, 1.7)
        self.assertEqual(timing.correction_for(dict(capped, stroke_step_px=80), path=self.path)['ratio'], 1.7)

    def test_unbound_history_is_retained_but_cannot_seed_an_unknown_delivery(self):
        old_key = timing._v4_key(self.options)
        old_row = dict(samples=4, ratio_ema=2.5, mape_ema=.3)
        self.path.write_text(json.dumps(dict(version=4, profiles={old_key: old_row})))
        before = self.path.read_bytes()
        with timing.planning_calibration_scope():
            result = timing.correction_for(self.options, path=self.path)
            self.assertFalse(result['learned'])
            self.assertEqual(result['ratio'], 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.record(self.options, 1.1)
        history = timing.load_all(self.path)['profiles']
        self.assertEqual(history[old_key], old_row)
        self.assertEqual(len(history), 2)
        self.assertEqual(timing.correction_for(self.options, path=self.path)['samples'], 1)

    def test_same_scope_observes_different_delivery_rows_without_extra_disk_reads(self):
        auto = dict(self.options, paint_stroke_delivery='Auto')
        reliable = dict(self.options, paint_stroke_delivery='Reliable')
        self.record(auto, 1.1)
        self.record(reliable, 1.9)
        with patch.object(timing, 'read_json', wraps=timing.read_json) as read:
            with timing.planning_calibration_scope():
                self.assertEqual(timing.correction_for(auto, path=self.path)['ratio'], 1.1)
                self.assertEqual(timing.correction_for(reliable, path=self.path)['ratio'], 1.9)
                self.assertEqual(timing.correction_for(auto, path=self.path)['ratio'], 1.1)
            self.assertEqual(read.call_count, 1)


if __name__ == '__main__':
    unittest.main()
