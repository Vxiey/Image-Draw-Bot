"""One current hardware-profile observation per complete scoring operation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import weakref
from unittest.mock import patch

import numpy as np
from PIL import Image

import AccuracyEvaluator as accuracy
import SafeCanvasSnapshotScoring as snapshots
import UniversalGpuAcceleration as gpu
import UniversalHardwareBenchmark as hardware
from test_step23_universal_gpu_acceleration_v10146 import profile


class ProfileObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'hardware-profile.json'
        for target, value in (
                ('PROFILE_FILE', self.path), ('detect_gpus', []),
                ('_total_ram_mb', 16384), ('available_ram_mb', 8192),
                ('logical_cpu_count', 8), ('cpu_name', 'Controlled CPU')):
            replacement = (patch.object(hardware, target, value)
                           if target == 'PROFILE_FILE' else
                           patch.object(hardware, target, return_value=value))
            replacement.start()
            self.addCleanup(replacement.stop)
        gpu.reset_runtime_backend_health()
        self.addCleanup(gpu.reset_runtime_backend_health)
        self.measured = self.save_profile()
        yy, xx = np.indices((18, 24))
        source = np.stack(((xx * 11) % 256, (yy * 17) % 256,
                           ((xx + yy) * 7) % 256), axis=-1).astype(np.uint8)
        self.source = Image.fromarray(source)
        self.actual = Image.fromarray(np.roll(source, 2, axis=1))
        self.simulated = Image.fromarray(np.roll(source, 1, axis=0))
        self.target = Image.fromarray((source // 32 * 32).astype(np.uint8))
        for image in (self.source, self.actual, self.simulated, self.target):
            self.addCleanup(image.close)

    def save_profile(self, backend_id='cpu:numpy', minimum=0):
        measured = profile(backend_id, backend_id, 'Controlled', 'Controlled device', minimum)
        measured['hardware_signature'] = hardware.hardware_snapshot()['hardware_signature']
        hardware.save_hardware_profile(measured)
        return measured

    def evaluate(self, mode='Auto', **kwargs):
        return accuracy.evaluate_preview(self.source, self.actual,
            coverage_percent=93.25, plan_execution_accuracy_percent=88.5,
            gpu_mode=mode, **kwargs)

    def score(self, mode='Auto', **kwargs):
        return snapshots.score_final_canvas_snapshot(snapshot=self.actual,
            original_source=self.source, simulated_final=self.simulated,
            quantized_target=self.target, area=(11, 17, 24, 18), fitted=(24, 18),
            comparison_size=(24, 18), actual_elapsed_seconds=7.125,
            usable_deadline_seconds=15.5, visual_gate_percent=90.,
            gpu_mode=mode, **kwargs)

    @contextmanager
    def observations(self):
        with patch.object(hardware, 'load_hardware_profile', wraps=hardware.load_hardware_profile) as loaded, \
                patch.object(hardware, 'read_json', wraps=hardware.read_json) as read, \
                patch.object(hardware, 'hardware_snapshot', wraps=hardware.hardware_snapshot) as probed:
            yield loaded, read, probed

    def assert_observations(self, observed, expected):
        actual = tuple(item.call_count for item in observed)
        self.assertEqual(actual, (expected,) * 3,
            'Profile reads, real JSON reads and current-hardware observations must share one operation lifetime.')

    def test_complete_evaluator_observes_profile_and_current_hardware_once(self):
        with self.observations() as observed:
            result = self.evaluate()
        self.assertEqual(len(result['acceleration_routes']), 4)
        self.assert_observations(observed, 1)

    def test_all_three_snapshot_comparisons_share_one_current_observation(self):
        with self.observations() as observed, \
                patch.object(snapshots, 'evaluate_preview', wraps=snapshots.evaluate_preview) as compared:
            result = self.score()
        self.assertTrue(result['available'], result)
        self.assertEqual(compared.call_count, 3)
        self.assert_observations(observed, 1)

    def test_explicit_cpu_keeps_zero_profile_reads_for_both_complete_operations(self):
        with self.observations() as observed, \
                patch.object(gpu, '_opencl_context', side_effect=AssertionError('CPU must not open a device')) as opened:
            evaluated = self.evaluate('CPU')
            scored = self.score('CPU')
        self.assertTrue(scored['available'], scored)
        self.assertEqual({row['backend_id'] for row in evaluated['acceleration_routes'].values()}, {'cpu:numpy'})
        self.assert_observations(observed, 0)
        opened.assert_not_called()

    def test_complete_scores_and_diagnostic_images_match_an_explicit_validated_profile(self):
        measured = hardware.load_hardware_profile()
        self.assertIsInstance(measured, dict)
        expected = self.evaluate(_profile_observation=measured,
                                 return_error_map=True, return_delta_e_heatmap=True)
        with self.observations() as observed:
            actual = self.evaluate(return_error_map=True, return_delta_e_heatmap=True)
        for key in ('_error_map_image', '_delta_e_heatmap_image'):
            left, right = expected.pop(key), actual.pop(key)
            self.addCleanup(left.close)
            self.addCleanup(right.close)
            self.assertEqual((left.mode, left.size, left.tobytes()),
                             (right.mode, right.size, right.tobytes()))
        self.assertEqual(actual, expected)
        self.assert_observations(observed, 1)

        evaluate = snapshots.evaluate_preview
        def explicit(*args, **kwargs):
            kwargs['_profile_observation'] = measured
            return evaluate(*args, **kwargs)
        with patch.object(snapshots, 'evaluate_preview', side_effect=explicit):
            expected_snapshot = self.score()
        with self.observations() as observed:
            actual_snapshot = self.score()
        self.assertEqual(actual_snapshot, expected_snapshot)
        self.assert_observations(observed, 1)

    def test_profile_replacement_is_seen_on_the_next_operation_not_halfway_through_one(self):
        for operation in ('evaluate', 'snapshot'):
            with self.subTest(operation=operation):
                first = deepcopy(self.measured)
                second = deepcopy(self.measured)
                for value in first['workload_preferences'].values():
                    value['reason'] = 'first complete observation'
                for value in second['workload_preferences'].values():
                    value['reason'] = 'next complete observation'
                hardware.save_hardware_profile(first)
                routes = []
                select = gpu.select_route
                def selecting(*args, **kwargs):
                    result = select(*args, **kwargs)
                    routes.append(result.reason)
                    if len(routes) == 1:
                        hardware.save_hardware_profile(second)
                    return result
                with self.observations() as observed, \
                        patch.object(gpu, 'select_route', side_effect=selecting):
                    result = self.evaluate() if operation == 'evaluate' else self.score()
                self.assertTrue(result.get('available', True))
                self.assertEqual(len(routes), 4 if operation == 'evaluate' else 12)
                self.assertEqual(set(routes), {'first complete observation'})
                self.assert_observations(observed, 1)
                with self.observations() as fresh:
                    result = self.evaluate()
                self.assertEqual({item['reason'] for item in result['acceleration_routes'].values()},
                                 {'next complete observation'})
                self.assert_observations(fresh, 1)

    def test_next_operation_revalidates_the_current_hardware_signature(self):
        first = self.evaluate()
        self.assertEqual({item['reason'] for item in first['acceleration_routes'].values()}, {'test preference'})
        versions = dict(hardware.runtime_versions(), python='changed runtime signature')
        with patch.object(hardware, 'runtime_versions', return_value=versions), \
                self.observations() as observed:
            second = self.evaluate()
        self.assertEqual({item['reason'] for item in second['acceleration_routes'].values()},
                         {'no benchmark preference'})
        self.assert_observations(observed, 1)

    def test_missing_damaged_and_invalid_profiles_remain_recoverable_cache_misses(self):
        expected = self.evaluate(_profile_observation={})
        for invalid in (None, '{not json', '{"version":999}',
                        '{"version":2,"workload_preferences":[]}'):
            with self.subTest(invalid=invalid):
                if invalid is None:
                    self.path.unlink(missing_ok=True)
                else:
                    self.path.write_text(invalid, encoding='utf-8')
                with self.observations() as (loaded, read, probed):
                    result = self.evaluate()
                self.assertEqual(result, expected)
                self.assertEqual((loaded.call_count, read.call_count, probed.call_count), (1, 1, 0))
                hardware.save_hardware_profile(self.measured)
                recovered = self.evaluate()
                self.assertEqual({item['reason'] for item in recovered['acceleration_routes'].values()},
                                 {'test preference'})

    def test_failed_load_reason_is_preserved_and_only_the_next_operation_retries(self):
        actual_load = hardware.load_hardware_profile
        attempts = []
        def unavailable_then_current():
            attempts.append(None)
            if len(attempts) == 1:
                raise OSError('controlled profile access failure')
            return actual_load()
        with patch.object(hardware, 'load_hardware_profile', side_effect=unavailable_then_current):
            failed = self.evaluate()
            self.assertEqual(len(attempts), 1)
            recovered = self.evaluate()
        self.assertEqual(len(attempts), 2)
        self.assertEqual({item['reason'] for item in failed['acceleration_routes'].values()},
                         {'hardware profile unavailable: OSError: controlled profile access failure'})
        self.assertEqual({item['reason'] for item in recovered['acceleration_routes'].values()},
                         {'test preference'})
        # Only provenance differs; every numeric and nonroute field survives.
        failed.pop('acceleration_routes')
        recovered.pop('acceleration_routes')
        self.assertEqual(failed, recovered)

    def test_auto_forced_cuda_crossover_and_live_quarantine_keep_real_selection(self):
        measured = self.save_profile('opencl:0:0')
        measured['scores_large'] = [dict(backend_id='cuda:0', workload=workload,
            throughput_mp_s=100., elapsed_ms=1., device='Controlled CUDA')
            for workload in ('bulk_matrix', 'oklab', 'edge_map')]
        for mode, minimum, first_backend in (
                ('Auto', 0, 'opencl:0:0'), ('Auto', 100_000, 'cpu:numpy'),
                ('NVIDIA CUDA', 100_000, 'cuda:0')):
            with self.subTest(mode=mode, minimum=minimum):
                for preference in measured['workload_preferences'].values():
                    preference['min_pixels'] = minimum
                hardware.save_hardware_profile(measured)
                gpu.reset_runtime_backend_health()
                selected = []
                select = gpu.select_route
                def selecting(workload, **kwargs):
                    result = select(workload, **kwargs)
                    selected.append((workload, kwargs['gpu_mode'], result.backend_id, result.reason))
                    return result
                with self.observations() as observed, \
                        patch.object(gpu, 'select_route', side_effect=selecting), \
                        patch.object(gpu, '_opencl_context', side_effect=RuntimeError('controlled unavailable device')) as opened, \
                        patch.dict(sys.modules, {'cupy': None}):
                    result = self.score(mode)
                self.assertTrue(result['available'], result)
                self.assertEqual(len(selected), 12)
                self.assertEqual({row[1] for row in selected}, {mode})
                self.assert_observations(observed, 1)
                for workload in ('pixel_math', 'delta_e', 'edge_map'):
                    self.assertEqual(next(row[2] for row in selected if row[0] == workload), first_backend)
                if first_backend == 'cpu:numpy':
                    opened.assert_not_called()
                    self.assertFalse(gpu.backend_health_snapshot())
                    self.assertTrue(all('crossover' in row[3] for row in selected))
                else:
                    self.assertTrue(gpu.backend_health_snapshot())
                    # The second source edge and every later comparison must
                    # consult updated health, not a cached accelerated route.
                    self.assertTrue(all(row[2] == 'cpu:numpy' and 'quarantined' in row[3]
                                        for row in selected[3:]))
                    if mode == 'Auto':
                        self.assertEqual(opened.call_count, 3)

    def test_already_stopped_operations_do_not_read_a_profile(self):
        with self.observations() as observed:
            for operation in (self.evaluate, self.score):
                with self.assertRaises(InterruptedError):
                    operation(cancelled=lambda: True)
        self.assert_observations(observed, 0)

    def test_success_stop_and_retained_failure_tracebacks_release_owned_profiles(self):
        class TrackedProfile(dict):
            pass
        actual_load = hardware.load_hardware_profile
        for operation in (self.evaluate, self.score):
            for boundary in ('success', 'stop in load', 'failure after load'):
                with self.subTest(operation=operation.__name__, boundary=boundary):
                    stop = threading.Event()
                    references = []
                    error = RuntimeError('retained scoring failure')
                    def loading():
                        result = TrackedProfile(actual_load())
                        references.append(weakref.ref(result))
                        if boundary == 'stop in load':
                            stop.set()
                        return result
                    with patch.object(hardware, 'load_hardware_profile', side_effect=loading), \
                            patch.object(accuracy, '_importance_weights',
                                side_effect=error if boundary == 'failure after load' else None,
                                wraps=accuracy._importance_weights):
                        try:
                            result = operation(cancelled=stop.is_set)
                        except (InterruptedError, RuntimeError) as caught:
                            # Keep the real traceback live across the ownership
                            # assertion; do not rely on a GC/exception sweep.
                            retained = caught
                            self.assertNotEqual(boundary, 'success')
                        else:
                            retained = error
                            self.assertNotEqual(boundary, 'stop in load')
                            if boundary == 'failure after load':
                                self.assertFalse(result['available'])
                                self.assertIn('retained scoring failure', result['reason'])
                    self.assertEqual(len(references), 1)
                    self.assertIsNone(references[0](), 'A retained traceback kept the operation profile alive.')
                    self.assertIsNotNone(retained)
                    self.source.getpixel((0, 0))
                    self.actual.getpixel((0, 0))

    def test_parallel_operations_have_independent_current_observations(self):
        barrier = threading.Barrier(2)
        actual_load = hardware.load_hardware_profile
        reads = []
        def loading():
            result = actual_load()
            identity = threading.current_thread().name
            for preference in result['workload_preferences'].values():
                preference['reason'] = identity
            reads.append(identity)
            barrier.wait(timeout=2.)
            return result
        with patch.object(hardware, 'load_hardware_profile', side_effect=loading), \
                ThreadPoolExecutor(max_workers=2, thread_name_prefix='profile-observation') as workers:
            futures = [workers.submit(self.evaluate) for _ in range(2)]
            results = [future.result(timeout=5.) for future in futures]
        self.assertEqual(len(reads), 2)
        self.assertEqual(len(set(reads)), 2)
        observed = [{row['reason'] for row in result['acceleration_routes'].values()} for result in results]
        self.assertCountEqual(observed, [{identity} for identity in reads])


if __name__ == '__main__':
    unittest.main()
