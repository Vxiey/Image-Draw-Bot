"""Recommendations must enable their measured routes and remain applicable."""
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import PerformanceAutoTuner as tuner
import ResourceAllocation as allocation
import ResourceScheduler as scheduler
import UniversalGpuAcceleration as gpu
import UniversalHardwareBenchmark as hardware


def measured_profile(*, gpu_wins=True, cpu_bulk=False):
    """Deterministic score records exercise the real preference/routing logic."""
    small, large = [], []
    for workload in hardware.WORKLOADS:
        for scores, size in ((small, 128), (large, 512)):
            rate = 200.0 if size == 512 and gpu_wins else 10.0
            if cpu_bulk and workload == 'bulk_matrix':
                rate = 10.0
            scores.extend((
                hardware.BackendScore('cpu:numpy', 'CPU/NumPy', 'CPU', 'CPU',
                    workload, size, size*size, 1.0, 80.0),
                hardware.BackendScore('opencl:0:0', 'OpenCL', 'AMD', 'OpenCL adapter',
                    workload, size, size*size, 1.0, rate, 8192),
                hardware.BackendScore('cuda:0', 'CUDA/CuPy', 'NVIDIA', 'CUDA adapter',
                    workload, size, size*size, 1.0, 20.0, 8192),
            ))
    preferences = hardware.build_preferences(small_scores=small, large_scores=large)
    return {'version': hardware.PROFILE_VERSION, 'hardware_signature': 'route-fixture',
            'primary_backend': preferences['primary_backend'],
            'workload_preferences': preferences['workloads'],
            'scores_small': [score.as_dict() for score in small],
            'scores_large': [score.as_dict() for score in large]}


class TunerRoutingTests(unittest.TestCase):
    def recommendation(self, profile, *, cuda=False):
        return tuner.build_recommendation(
            scheduler_result={'logical_cpus': 8, 'recommended_workers': 4, 'best_score': 1.0},
            available_mb=16000, hardware_result=profile,
            gpu_result={'used_gpu': cuda, 'accelerated': cuda, 'throughput_mp_s': 20.0 if cuda else 0.0})

    def route(self, recommendation, profile, workload='oklab', pixels=512*512):
        return gpu.select_route(workload, pixels=pixels, gpu_mode=recommendation.gpu_mode, profile=profile)

    def test_verified_opencl_winner_remains_enabled_without_legacy_cuda(self):
        profile = measured_profile()
        rec = self.recommendation(profile)
        self.assertEqual(profile['workload_preferences']['oklab']['backend_id'], 'opencl:0:0')
        self.assertEqual(self.route(rec, profile).backend_id, 'opencl:0:0')
        self.assertEqual(rec.gpu_mode, 'Auto')
        self.assertFalse(rec.gpu_available)  # Legacy portrait CUDA remains unavailable.
        self.assertEqual(self.route(rec, profile, pixels=128*128).backend_id, 'cpu:numpy')

    def test_legacy_cuda_success_does_not_override_faster_opencl_or_cpu_workloads(self):
        profile = measured_profile(cpu_bulk=True)
        rec = self.recommendation(profile, cuda=True)
        self.assertEqual(self.route(rec, profile).backend_id, 'opencl:0:0')
        self.assertEqual(self.route(rec, profile, workload='pixel_math').backend_id, 'cpu:numpy')
        self.assertEqual(self.route(rec, profile, pixels=128*128).backend_id, 'cpu:numpy')
        self.assertTrue(rec.gpu_available)

    def test_measured_cpu_winners_are_respected_even_when_cuda_probe_succeeds(self):
        profile = measured_profile(gpu_wins=False)
        rec = self.recommendation(profile, cuda=True)
        self.assertEqual(self.route(rec, profile).backend_id, 'cpu:numpy')

    def test_detected_adapter_or_summary_only_does_not_enable_unmeasured_compute(self):
        for profile in ({}, {'detected_gpus': [{'vendor': 'AMD'}]},
                        {'primary_backend': {'backend': 'OpenCL', 'vendor': 'AMD'}},
                        {'workload_preferences': []},
                        {'workload_preferences': {'oklab': {'backend_id': 'opencl:0:0'}}}):
            with self.subTest(profile=profile):
                self.assertEqual(self.recommendation(profile).gpu_mode, 'CPU')
        self.assertEqual(self.recommendation(measured_profile(gpu_wins=False)).gpu_mode, 'CPU')

    def test_explicit_cpu_policy_and_existing_cuda_only_recommendation_are_preserved(self):
        profile = measured_profile()
        route = gpu.select_route('oklab', pixels=512*512, gpu_mode='CPU', profile=profile)
        self.assertEqual(route.backend_id, 'cpu:numpy')
        self.assertEqual(self.recommendation({}, cuda=True).gpu_mode, 'NVIDIA CUDA')


class TunerBudgetApplicabilityTests(unittest.TestCase):
    def run_tune(self, available):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ))
        directory = stack.enter_context(tempfile.TemporaryDirectory())
        base = Path(directory)
        scheduler_path = base / 'scheduler.json'
        stack.enter_context(patch.object(tuner, 'logical_cpu_count', return_value=16))
        stack.enter_context(patch.object(allocation, 'logical_cpu_count', return_value=16))
        stack.enter_context(patch.object(tuner, 'available_ram_mb', return_value=available))
        stack.enter_context(patch.object(allocation, 'available_ram_mb', return_value=available))
        stack.enter_context(patch.object(tuner, 'run_universal_hardware_benchmark', return_value={}))
        stack.enter_context(patch.object(scheduler, 'SCHEDULER_FILE', scheduler_path))
        stack.enter_context(patch.object(hardware, 'PROFILE_FILE', base / 'hardware.json'))
        result = tuner.run_auto_tune(path=base / 'tuner.json', scheduler_loops=8000)
        rec = result['recommendation']
        applied = allocation.resolve_allocation(rec['cpu_workers'], rec['cpu_engine'],
                                               rec['ram_budget'], rec['ram_custom_mb'])
        return scheduler_path, result, applied

    def test_high_memory_tune_loads_its_own_worker_recommendation_after_apply(self):
        for available in (28000, 32768, 65536):
            with self.subTest(available=available):
                path, result, applied = self.run_tune(available)
                saved = scheduler.load_recommendation(path)
                self.assertIsNotNone(saved)
                self.assertEqual(saved['ram_budget_mb'], applied['ram_budget_mb'])
                signature = scheduler.machine_signature(logical_cpus=applied['logical_cpus'],
                                                        ram_mb=applied['ram_budget_mb'])
                loaded = scheduler.load_recommendation(path, signature=signature)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded['recommended_workers'], result['recommendation']['cpu_workers_effective'])

    def test_low_memory_recommendation_reports_the_actual_allocator_budget(self):
        for available in (128, 256, 600, 900):
            with self.subTest(available=available):
                path, result, applied = self.run_tune(available)
                self.assertEqual(int(result['recommendation']['ram_custom_mb']), applied['ram_budget_mb'])
                self.assertEqual(scheduler.load_recommendation(path)['ram_budget_mb'], applied['ram_budget_mb'])

    def test_existing_middle_budget_and_next_operation_capacity_recheck_remain(self):
        path, result, applied = self.run_tune(16000)
        saved = scheduler.load_recommendation(path)
        self.assertEqual(saved['ram_budget_mb'], applied['ram_budget_mb'])
        changed = scheduler.machine_signature(logical_cpus=4, ram_mb=applied['ram_budget_mb'])
        self.assertIsNone(scheduler.load_recommendation(path, signature=changed))


if __name__ == '__main__':
    unittest.main()
