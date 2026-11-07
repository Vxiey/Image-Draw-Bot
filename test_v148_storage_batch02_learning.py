import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import CompletedDrawLearning as learning
import AutoTunerFeedback as feedback
import CorrectionHistory as history
import DrawTimeCalibration as timing
import DrawTimeEstimate as eta
import PerformanceAutoTuner as tuner
import RuntimePaths
from test_step16_correction_history_v10140 import base_plan


class StorageLearningBatch02Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state.json'

    def test_history_discards_corrupt_rows_without_losing_valid_older_entries(self):
        valid = history.build_history_entry(base_plan(), actual_seconds=12, created_at=123)
        invalid = json.loads(json.dumps(valid))
        invalid['before']['visual_accuracy_percent'] = 'broken'
        bad_count = json.loads(json.dumps(valid)); bad_count['correction']['executed_paths'] = []
        self.path.write_text(json.dumps(dict(version=1, profile_key='microsoft-paint',
                                            entries=[valid, invalid, bad_count])))
        loaded = history.load_correction_history({'profile_key': 'microsoft-paint'}, path=self.path)
        self.assertEqual(loaded['entry_count'], 1)
        self.assertIn('71.5%', history.format_correction_history(loaded))

    def test_history_timestamp_cannot_publish_nonfinite_or_negative_state(self):
        for value in (float('nan'), float('inf'), -1, True, 10**400):
            with self.subTest(value=value), self.assertRaises(ValueError):
                history.record_correction_history(base_plan(), path=self.path, created_at=value)
        self.assertFalse(self.path.exists())

    def test_optional_live_benchmark_corruption_falls_back_before_strict_save(self):
        scheduler = dict(logical_cpus=4, recommended_workers=2, best_score=1, scores=[])
        with patch.object(tuner, 'available_ram_mb', return_value=4096), \
             patch.object(tuner, 'resolve_allocation', return_value={}), \
             patch.object(tuner, 'benchmark_scheduler', return_value=scheduler), \
             patch.object(tuner, 'run_universal_hardware_benchmark', return_value={'primary_backend': {'safe_memory_budget_mb': float('inf')}}), \
             patch.object(tuner, 'load_hardware_profile', return_value={}):
            result = tuner.run_auto_tune(path=self.path, gpu_benchmark=lambda *args: {
                'used_gpu': True, 'throughput_mp_s': float('nan')})
        self.assertEqual(result['recommendation']['gpu_mode'], 'CPU')
        self.assertTrue(result['gpu_error'])
        self.assertTrue(result['hardware_error'])
        self.assertIsNotNone(tuner.load_tune_result(self.path))
        RuntimePaths.read_json(self.path)

    def test_live_primary_backend_shape_and_gpu_flags_are_validated(self):
        scheduler = dict(logical_cpus=4, recommended_workers=2, best_score=1)
        for hardware in ({'primary_backend': 42}, {'detected_gpus': 42},
                         {'primary_backend': {'tile_size': float('inf')}}):
            with self.subTest(hardware=hardware):
                rec = tuner.build_recommendation(scheduler_result=scheduler, available_mb=4096,
                    gpu_result={'used_gpu': 'false', 'throughput_mp_s': 25}, hardware_result=hardware)
                self.assertEqual(rec.gpu_mode, 'CPU')
                self.assertIsNone(rec.hardware_tile_size)

    def test_benchmark_interruption_is_not_driver_failure_or_a_saved_cpu_result(self):
        with patch.object(tuner, 'available_ram_mb', return_value=4096), \
             patch.object(tuner, 'resolve_allocation', return_value={}), \
             patch.object(tuner, 'benchmark_scheduler', return_value={}), \
             patch.object(tuner, 'run_universal_hardware_benchmark') as hardware, \
             patch.object(tuner, 'save_tune_result') as save:
            with self.assertRaises(InterruptedError):
                tuner.run_auto_tune(gpu_benchmark=lambda *args: (_ for _ in ()).throw(InterruptedError()))
        hardware.assert_not_called(); save.assert_not_called()

    def test_timing_writer_retains_current_context_and_stays_within_reader_limits(self):
        contexts = {f'test|legacy-{i}': dict(samples=1, ratio_ema=1, mape_ema=0, updated_at=i)
                    for i in range(19000)}
        self.path.write_text(json.dumps(dict(version=timing.VERSION, profiles=contexts)))
        self.assertEqual(len(timing.load_all(self.path)['profiles']), 19000)
        result = timing.record_sample({'profile_key': 'test'}, 10, 12, path=self.path)
        self.assertTrue(result['recorded'])
        saved = RuntimePaths.read_json(self.path)
        self.assertLessEqual(len(saved['profiles']), timing.MAX_CONTEXTS)
        self.assertIn(result['key'], saved['profiles'])
        self.assertIn('test|legacy-18999', saved['profiles'])
        self.assertNotIn('test|legacy-0', saved['profiles'])

    def test_timing_operation_metadata_is_bounded_before_persistence(self):
        operations = {f'operation-{i}': dict(count=1, total_seconds=.5) for i in range(200)}
        result = timing.record_sample({'profile_key': 'test'}, 10, 12, path=self.path,
                                      operation_runtime=operations, operation_counts={key: 1 for key in operations})
        self.assertTrue(result['recorded'])
        row = RuntimePaths.read_json(self.path)['profiles'][result['key']]
        self.assertLessEqual(len(row['last_operation_runtime']), timing.MAX_OPERATION_KINDS)
        self.assertLessEqual(len(row['last_operation_counts']), timing.MAX_OPERATION_KINDS)

    def test_planned_fills_and_tool_switches_do_not_count_as_completed_drawing(self):
        for options in ({'background_fill_plan': {'enabled': True}}, {'fill_regions': [{}]},
                        {'runtime_operation_timing': {'palette_change': {'count': 1, 'total_seconds': 1}}},
                        {'runtime_operation_timing': {'stroke': {'count': 0, 'total_seconds': 1}}}):
            with self.subTest(options=options):
                self.assertFalse(learning.timing_sample_gate(options)['allowed'])
        self.assertTrue(learning.timing_sample_gate({'runtime_operation_timing': {
            'stroke': {'count': 1, 'total_seconds': .1}}})['allowed'])
        for invalid in (True, '2.0', None, float('inf'), float('nan'), 10 ** 400):
            with self.subTest(elapsed_type=type(invalid).__name__):
                options = {'runtime_operation_timing': {'stroke': {'count': 1, 'total_seconds': invalid}}}
                self.assertFalse(learning.has_completed_drawing_work(options))
                self.assertFalse(learning.timing_sample_gate(options)['allowed'])

    def test_timing_evidence_respects_explicit_negative_snapshot_trust(self):
        legacy = dict(available=True, trusted=True,
                      visual_accuracy_percent=97., actual_coverage_percent=99.)
        for addition in ({}, {'feedback_trust': 'high'}, {'feedback_trust': 'medium'}):
            result = learning.timing_sample_gate({'post_draw_accuracy_meta': {**legacy, **addition}},
                                                 completed_paths=1, planned_paths=1)
            self.assertTrue(result['allowed'])
            self.assertEqual(result['confidence'], 'trusted-final-canvas')
        for addition in ({'feedback_trust': 'none'}, {'feedback_trust': 'low'},
                         {'geometry_ok': False}, {'confidence_percent': True}):
            result = learning.timing_sample_gate({'post_draw_accuracy_meta': {**legacy, **addition}},
                                                 completed_paths=1, planned_paths=1)
            self.assertFalse(result['allowed'])

    def test_executed_fills_allow_zero_path_learning_and_are_the_persisted_count(self):
        options = {'background_fill_plan': {'enabled': True}, 'fill_regions': [{}, {}, {}, {}],
                   'runtime_safety_report': {'mode': 'drawing', 'fills': {
                       'background_fill_clicks': 1, 'better_fill_clicks': 2, 'better_fill_simulated': 100}}}
        self.assertEqual(learning.completed_fill_actions(options), 3)
        self.assertTrue(learning.timing_sample_gate(options)['allowed'])
        plan = {'count': 0, 'options': options, 'draw_time_estimate': {'preview_seconds': 10}}
        with patch.object(timing, 'record_sample', return_value={'recorded': True}) as record:
            self.assertTrue(eta.record_completed_draw(plan, 12)['recorded'])
        self.assertEqual(record.call_args.kwargs['fill_actions'], 3)
        options['runtime_safety_report']['mode'] = 'dry-run'
        self.assertEqual(learning.completed_fill_actions(options), 0)

    def test_feedback_adjusted_outcomes_update_the_policy_the_next_decision_reads(self):
        from test_step12_auto_tuner_feedback_v10136 import base_options, plan_for
        options = base_options()
        for _ in range(3):
            plan = plan_for(options, predicted=50, usable=60)
            feedback.record_completed_feedback(plan, 70, completed_paths=100, path=self.path)
        before = feedback.recommend_adjustment(options, source_kind='flat illustration',
            strategy='deadline-hybrid-fast', budget_seconds=60, color_ceiling=14, path=self.path)
        self.assertEqual(before['action'], 'protect-deadline')
        for _ in range(8):
            plan = plan_for(options, strategy='deadline-hybrid-fast+feedback-protect-deadline',
                            predicted=50, usable=60)
            plan['options']['auto_tuner_meta']['base_strategy'] = 'deadline-hybrid-fast'
            result = feedback.record_completed_feedback(plan, 40, completed_paths=100, path=self.path)
        self.assertEqual(result['strategy'], 'deadline-hybrid-fast')
        self.assertEqual(result['samples'], 11)
        after = feedback.recommend_adjustment(options, source_kind='flat illustration',
            strategy='deadline-hybrid-fast', budget_seconds=60, color_ceiling=14, path=self.path)
        self.assertEqual(after['samples'], 11)
        self.assertEqual(after['action'], 'none')
        rescue = plan_for(options, strategy='deadline-rescue', predicted=50, usable=60)
        rescue['options']['auto_tuner_meta']['base_strategy'] = 'deadline-hybrid-fast'
        result = feedback.record_completed_feedback(rescue, 40, completed_paths=100, path=self.path)
        self.assertEqual(result['strategy'], 'deadline-rescue')
        self.assertEqual(result['samples'], 1)

    def test_feedback_does_not_record_an_empty_drawing_as_a_success(self):
        from test_step12_auto_tuner_feedback_v10136 import base_options, plan_for
        plan = plan_for(base_options(), count=0)
        self.assertFalse(feedback.record_completed_feedback(plan, 10, path=self.path)['recorded'])
        self.assertFalse(self.path.exists())
        plan['options']['runtime_safety_report'] = {
            'mode': 'drawing', 'fills': {'background_fill_clicks': 1}}
        self.assertTrue(feedback.record_completed_feedback(plan, 10, path=self.path)['recorded'])

    def test_timing_counters_are_real_nonnegative_integers(self):
        for invalid in (True, 1.5, '1', -1, 10 ** 400):
            with self.subTest(invalid=type(invalid).__name__):
                self.assertFalse(learning.timing_sample_gate({}, completed_paths=invalid)['allowed'])
                self.assertFalse(learning.timing_sample_gate({}, completed_paths=1,
                                                           planned_paths=invalid)['allowed'])


if __name__ == '__main__':
    unittest.main()
