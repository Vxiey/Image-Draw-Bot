"""Resource bounds, policy and optimizer regressions for v1.0.148."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import EndToEndAutoTuner as tuner
import ExecutionTelemetry
import PerformanceAutoTuner as performance
import PerformanceProfiler as profiler
import ResourceAllocation as allocation
import ResourceScheduler as scheduler
import TargetCapabilities


class ResourceSafetyTests(unittest.TestCase):
    def test_process_cpu_affinity_limits_worker_selection(self):
        with patch.object(allocation.os, 'process_cpu_count', None, create=True), \
             patch.object(allocation.os, 'sched_getaffinity', return_value={2, 3}, create=True), \
             patch.object(allocation.os, 'cpu_count', return_value=64):
            self.assertEqual(allocation.resolve_cpu_workers('All logical'), 2)

    def test_cpu_probe_falls_back_when_affinity_is_unavailable(self):
        with patch.object(allocation.os, 'process_cpu_count', None, create=True), \
             patch.object(allocation.os, 'sched_getaffinity', side_effect=OSError('unsupported'), create=True), \
             patch.object(allocation.os, 'cpu_count', return_value=4):
            self.assertEqual(allocation.logical_cpu_count(), 4)

    def test_linux_available_memory_includes_reclaimable_ram(self):
        with patch.object(allocation.sys, 'platform', 'linux'), \
             patch('ResourceAllocation.Path.open', return_value=io.StringIO('MemFree: 16384 kB\nMemAvailable: 2097152 kB\n')):
            self.assertEqual(allocation.available_ram_mb(), 2048)

    def test_allocation_uses_one_consistent_hardware_snapshot(self):
        with patch.object(allocation, 'logical_cpu_count', side_effect=[8, 32]) as cpus, \
             patch.object(allocation, 'available_ram_mb', side_effect=[4096, 128]) as memory:
            result = allocation.resolve_allocation('All logical', 'Threads', 'Auto')
        self.assertEqual(cpus.call_count, 1); self.assertEqual(memory.call_count, 1)
        self.assertEqual(result['logical_cpus'], result['cpu_workers_resolved'])
        self.assertEqual(result['available_ram_mb'], 4096)
        self.assertEqual(result['ram_budget_mb'], int(4096 * .35))

    def test_known_exhausted_memory_cannot_resolve_to_larger_budget(self):
        for free in (0, 64, 127):
            with self.subTest(free=free), patch.object(allocation, 'available_ram_mb', return_value=free):
                with self.assertRaisesRegex(ValueError, '128 MB'):
                    allocation.resolve_ram_budget_mb('Auto')
            with self.assertRaises(ValueError):
                performance._ram_recommendation(free)
        self.assertEqual(performance._ram_recommendation(256), ('Custom', '256', 256))
        self.assertEqual(allocation.resolve_ram_budget_mb('Auto', available_mb=None), 2048)

    def test_wide_image_chunks_obey_ram_budget_even_below_eight_rows(self):
        width, workers, ram = 32768, 8, 128
        chunks = allocation.row_chunk_ranges(40, width, workers=workers, ram_budget_mb=ram)
        self.assertEqual(chunks[0], (0, 2))
        self.assertEqual(chunks[-1][1], 40)
        self.assertTrue(all((stop - start) * width * 64 <= ram * 1024**2 // (workers * 4)
                            for start, stop in chunks))
        self.assertEqual(scheduler._chunk_hint(40, width, workers, ram)['rows_per_chunk'], 2)
        with self.assertRaises(ValueError):
            allocation.row_chunk_ranges(10, 10**7, workers=workers, ram_budget_mb=ram)

    def test_pressure_scaling_never_increases_a_small_safe_chunk(self):
        result = scheduler.resolve_resource_schedule({'cpu_workers': '8', 'logical_cpus': 8,
            'cpu_engine': 'Threads', 'ram_budget_mb': 128, 'available_ram_mb': 400}, area=(100000, 20), gpu_mode='CPU')
        chunk = result['phases']['shape_extraction']
        self.assertLessEqual(chunk['rows_per_chunk'], 2)

    def test_explicit_cpu_mode_also_controls_correction_scoring(self):
        result = scheduler.resolve_resource_schedule({'cpu_workers': '2', 'logical_cpus': 8,
            'cpu_engine': 'Threads', 'ram_budget_mb': 512}, area=(1000, 1000), gpu_mode='CPU', gpu_available=True)
        self.assertEqual(result['phases']['image_matrix']['backend'], 'CPU')
        self.assertEqual(result['phases']['correction_scoring']['backend'], 'CPU')

    def test_bounded_executor_preserves_order_and_limits_inflight_tasks(self):
        factory = FakeExecutorFactory()
        with patch.object(allocation, 'ThreadPoolExecutor', factory):
            result = allocation.parallel_map(lambda item: item * 2, list(range(200)), backend='threads', workers=3)
        self.assertEqual(result, list(range(0, 400, 2)))
        self.assertLessEqual(factory.executor.peak, 6)

    def test_executor_failure_cancels_remaining_window_and_submits_no_more(self):
        factory = FakeExecutorFactory(fail_at=0)
        with patch.object(allocation, 'ThreadPoolExecutor', factory), self.assertRaisesRegex(ValueError, 'worker failed'):
            allocation.parallel_map(lambda item: item, list(range(200)), backend='threads', workers=3)
        self.assertEqual(factory.executor.submitted, 6)
        self.assertEqual(factory.executor.cancelled, 5)

    def test_windows_process_executor_respects_documented_worker_limit(self):
        factory = FakeExecutorFactory()
        with patch.object(allocation.sys, 'platform', 'win32'), patch.object(allocation, 'ProcessPoolExecutor', factory):
            result = allocation.parallel_map(abs, list(range(200)), backend='processes', workers=128)
        self.assertEqual(factory.workers, 61)
        self.assertEqual(result, list(range(200)))

    def test_real_thread_executor_keeps_input_order(self):
        self.assertEqual(allocation.parallel_map(abs, [-3, -1, -2], backend='threads', workers=2), [3, 1, 2])

    def test_corrupt_scheduler_recommendations_fail_closed(self):
        data = {'version': 2, 'logical_cpus': 8, 'recommended_workers': 4, 'ram_budget_mb': 512,
                'recommended_engine': 'Threads', 'machine_signature': 'test', 'best_score': 3.0, 'scores': []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scheduler.json'
            for key, value in (('version', []), ('recommended_workers', 'all'), ('logical_cpus', True),
                               ('best_score', float('nan')), ('best_score', 10**400), ('recommended_engine', 'unknown')):
                changed = dict(data); changed[key] = value
                path.write_text(json.dumps(changed))
                self.assertIsNone(scheduler.load_recommendation(path, signature='test'))
        workers, _ = scheduler.recommended_workers({'logical_cpus': 8}, recommendation={'recommended_workers': []})
        self.assertGreater(workers, 0)

    def test_saved_scheduler_recommendation_must_match_current_cpu_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scheduler.json'
            data = scheduler.save_recommendation({'logical_cpus': 8, 'recommended_workers': 4,
                'ram_budget_mb': 512, 'best_score': 3.0, 'scores': []}, path)
            with patch.object(allocation, 'logical_cpu_count', return_value=4):
                self.assertIsNone(scheduler.load_recommendation(path))
            self.assertIsNotNone(scheduler.load_recommendation(path, signature=data['machine_signature']))

    def test_auto_tune_save_false_does_not_persist_scheduler_or_hardware(self):
        base = {'logical_cpus': 4, 'recommended_workers': 2, 'best_score': 1, 'scores': []}
        with patch.object(performance, 'logical_cpu_count', return_value=4), \
             patch.object(performance, 'available_ram_mb', return_value=4096), \
             patch.object(performance, 'resolve_allocation', return_value={}), \
             patch.object(performance, 'benchmark_scheduler', return_value=base) as benchmark, \
             patch.object(performance, 'run_universal_hardware_benchmark', return_value={}) as hardware, \
             patch.object(performance, 'save_tune_result') as save:
            performance.run_auto_tune(save=False)
        self.assertFalse(benchmark.call_args.kwargs['save'])
        self.assertFalse(hardware.call_args.kwargs['save'])
        save.assert_not_called()

    def test_failed_hardware_benchmark_cannot_reuse_unvalidated_machine_profile(self):
        base = {'logical_cpus': 4, 'recommended_workers': 2, 'best_score': 1, 'scores': []}
        with patch.object(performance, 'available_ram_mb', return_value=4096), \
             patch.object(performance, 'resolve_allocation', return_value={}), \
             patch.object(performance, 'benchmark_scheduler', return_value=base), \
             patch.object(performance, 'run_universal_hardware_benchmark', side_effect=RuntimeError('driver')), \
             patch.object(performance, 'load_hardware_profile', return_value={}) as load:
            result = performance.run_auto_tune(save=False)
        load.assert_called_once_with(validate_current=True)
        self.assertEqual(result['recommendation']['primary_compute_backend'], 'CPU/NumPy')

    def test_corrupt_tune_settings_are_not_loaded_into_ui(self):
        valid = {'version': 1, 'elapsed_ms': 12, 'recommendation': {'cpu_workers_effective': 2,
                 'logical_cpus': 4, 'planning_resolution': 'Standard', 'ram_budget': '512 MB', 'gpu_available': False}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tuner.json'
            performance.save_tune_result(valid, path)
            self.assertIsNotNone(performance.load_tune_result(path))
            for key, value in (('cpu_workers_effective', []), ('gpu_available', 'false'), ('planning_resolution', 'Unlimited')):
                changed = dict(valid, recommendation=dict(valid['recommendation']))
                changed['recommendation'][key] = value
                path.write_text(json.dumps(changed))
                self.assertIsNone(performance.load_tune_result(path))
            changed = dict(valid, elapsed_ms=10**400)
            path.write_text(json.dumps(changed))
            self.assertIsNone(performance.load_tune_result(path))


class FakeExecutorFactory:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
    def __call__(self, max_workers):
        self.workers = max_workers
        self.executor = FakeExecutor(self.fail_at)
        return self.executor


class FakeExecutor:
    def __init__(self, fail_at):
        self.fail_at = fail_at
        self.submitted = self.pending = self.peak = self.cancelled = 0
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def submit(self, function, item):
        self.submitted += 1; self.pending += 1; self.peak = max(self.peak, self.pending)
        owner = self
        class Future:
            def result(self):
                owner.pending -= 1
                if item == owner.fail_at:
                    raise ValueError('worker failed')
                return function(item)
            def cancel(self):
                owner.cancelled += 1
        return Future()


class PlanningEvidenceTests(unittest.TestCase):
    def plan(self):
        return {'estimate': 10, 'options': {'auto_tuner_meta': {'acceptance_gates': {
            'visual_accuracy_min_percent': 85, 'deadline_required': True, 'usable_deadline_seconds': 20}},
            'adaptive_accuracy_meta': {'visual_accuracy_percent': 90, 'plan_execution_accuracy_percent': 100}}}

    def test_invalid_or_missing_time_estimate_cannot_pass_timed_acceptance(self):
        self.assertTrue(tuner.evaluate_plan_acceptance(self.plan())['accepted'])
        for value in (None, float('nan'), float('inf'), -10, 'broken'):
            plan = self.plan(); plan['estimate'] = value
            result = tuner.evaluate_plan_acceptance(plan)
            self.assertFalse(result['accepted'])
            self.assertFalse(result['deadline_gate_passed'])
            self.assertIsNone(result['projected_draw_seconds'])

    def test_invalid_quality_threshold_and_out_of_range_metrics_cannot_pass(self):
        for value in (None, float('nan'), -1, 101):
            plan = self.plan(); plan['options']['auto_tuner_meta']['acceptance_gates']['visual_accuracy_min_percent'] = value
            self.assertFalse(tuner.evaluate_plan_acceptance(plan)['accepted'])
        plan = self.plan(); plan['options']['adaptive_accuracy_meta']['visual_accuracy_percent'] = 1000
        self.assertFalse(tuner.evaluate_plan_acceptance(plan)['accepted'])

    def test_cancellation_after_color_analysis_skips_next_probe(self):
        with Image.new('RGB', (20, 20), 'white') as image:
            with patch.object(tuner, 'recommend_adaptive_color_count', return_value=(3, {})), \
                 patch.object(tuner, '_bounded_stats') as stats:
                with self.assertRaises(InterruptedError):
                    tuner.analyze_source(image, cancelled=iter((False, True)).__next__)
            stats.assert_not_called()

    def test_rgb_probe_resizes_before_any_conversion_and_preserves_statistics(self):
        image = Image.fromarray(np.arange(640 * 480 * 3, dtype=np.uint8).reshape(480, 640, 3))
        with image, image.resize((128, 96), Image.Resampling.BOX) as reference:
            array = np.asarray(reference, dtype=np.int16)
            expected = (float(np.mean(array.min(axis=2) >= 238)),
                        float(np.mean(array.max(axis=2) - array.min(axis=2) >= 30)))
            with patch.object(Image.Image, 'convert', side_effect=AssertionError('unexpected full RGB copy')):
                self.assertEqual(tuner._bounded_stats(image), expected)
            self.assertEqual(image.size, (640, 480))

    def test_profiler_tokens_are_consumed_once_and_nested_marks_survive(self):
        options = {}
        with patch.object(profiler.time, 'perf_counter', return_value=0) as clock:
            profiler.begin(options)
            clock.return_value = 1
            older = profiler.start(options, 'color_planning')
            clock.return_value = 2
            newer = profiler.start(options, 'color_planning')
            clock.return_value = 4
            self.assertEqual(profiler.stop(options, 'color_planning', older), 3)
            clock.return_value = 5
            self.assertEqual(profiler.stop(options, 'color_planning', older), 0)
            clock.return_value = 6
            self.assertEqual(profiler.stop(options, 'color_planning'), 4)
            clock.return_value = 7
            self.assertEqual(profiler.stop(options, 'color_planning', newer), 0)
        json.dumps(options)

    def test_profiler_has_no_false_bottleneck_for_unmeasured_phases(self):
        for timings in ({'preprocessing': 0}, {'preprocessing': float('nan')}, {'unknown': 3}):
            self.assertEqual(profiler.dominant_phase({'timings': timings}), (None, 0.0))

    def test_telemetry_streams_groups_without_changing_cost_inputs_or_counts(self):
        class Model:
            scale_x = 2; scale_y = 1; color_change_seconds = .5
            def path_seconds(self, path, cursor):
                self.assert_tuple(path)
                return len(path)
            def assert_tuple(self, path):
                if not isinstance(path, tuple):
                    raise AssertionError('Cost model contract changed')
        groups = [[[(0, 0), (3, 4)], [], [(6, 8)]], [[(10, 10)]]]
        result = ExecutionTelemetry.execution_metrics(groups, Model(), color_order=[0, 0, 1])
        self.assertEqual(result['path_count'], 3)
        self.assertEqual(result['point_count'], 4)
        self.assertEqual(result['color_change_count'], 2)
        self.assertEqual(result['modeled_total_seconds'], 5)
        self.assertAlmostEqual(result['draw_px'], (36 + 16)**.5, places=6)

    def test_capability_catalog_reuses_immutable_results_and_known_objects(self):
        self.assertIs(TargetCapabilities.browser_profile_keys(), TargetCapabilities.browser_profile_keys())
        self.assertIs(TargetCapabilities.all_capabilities(), TargetCapabilities.all_capabilities())
        known = TargetCapabilities.capability_for_key('microsoft-paint')
        with patch.object(TargetCapabilities, 'TargetCapability', side_effect=AssertionError('unneeded fallback allocation')):
            self.assertIs(TargetCapabilities.capability_for_key('Microsoft-Paint'), known)
        self.assertTrue(TargetCapabilities.requires_manual_setup('user-custom-profile'))


if __name__ == '__main__':
    unittest.main()
