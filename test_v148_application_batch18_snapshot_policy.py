"""Final result scoring follows the caller's selected CPU/GPU policy."""
from contextlib import closing
import sys
import unittest
from unittest.mock import patch

from PIL import Image

import UniversalGpuAcceleration as gpu
import UniversalHardwareBenchmark as hardware
from SafeCanvasSnapshotScoring import score_final_canvas_snapshot
from test_step23_universal_gpu_acceleration_v10146 import profile
import test_v148_application_batch17_runtime_report as execution_fixture
import test_v148_application_batch18_result_recheck as recheck_fixture


class SnapshotPolicyApplicationTests(unittest.TestCase):
    def setUp(self):
        gpu.reset_runtime_backend_health()
        self.addCleanup(gpu.reset_runtime_backend_health)
        self.measured = profile('opencl:0:0', 'OpenCL', 'AMD', 'Controlled OpenCL')

    def test_actual_executor_selected_cpu_does_not_open_saved_accelerator_for_final_result(self):
        fixture = execution_fixture.RuntimeReportApplicationTests('test_startup_still_loads_saved_history')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch.object(hardware, 'load_hardware_profile', return_value=self.measured), \
                patch.object(gpu, '_opencl_context', side_effect=RuntimeError('No native device is opened by this test')) as opened:
            plan = fixture.start_draw()
        self.assertEqual(plan['options']['gpu_mode'], 'CPU')
        self.assertTrue(plan['options']['post_draw_accuracy_meta']['available'])
        self.assertTrue(plan['options']['runtime_safety_report']['completed'])
        self.assertEqual(opened.call_count, 0,
            'The explicit CPU execution opened a saved GPU backend during final canvas scoring.')

    def test_actual_read_only_recheck_preserves_the_retained_plans_cpu_policy(self):
        fixture = recheck_fixture.ResultRecheckApplicationTests('test_advertised_recheck_has_an_actual_review_card_action')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch.object(hardware, 'load_hardware_profile', return_value=self.measured), \
                patch.object(gpu, '_opencl_context', side_effect=RuntimeError('No native device is opened by this test')) as opened:
            fixture.finish_recheck()
        self.assertEqual(fixture.plan['options']['gpu_mode'], 'CPU')
        self.assertTrue(fixture.plan['options']['post_draw_accuracy_meta']['available'])
        fixture.assert_no_input()
        fixture.assert_capture_closed()
        self.assertEqual(opened.call_count, 0,
            'The explicit CPU result re-check opened a saved GPU backend.')

    def test_default_auto_scoring_retains_measured_routing_and_its_existing_fallback(self):
        with closing(Image.new('RGB', (12, 10), 'black')) as image, \
                patch.object(hardware, 'load_hardware_profile', return_value=self.measured), \
                patch.object(gpu, '_opencl_context', side_effect=RuntimeError('controlled unavailable device')) as opened:
            result = score_final_canvas_snapshot(snapshot=image, original_source=image,
                simulated_final=image, quantized_target=image, area=(0, 0, 12, 10), fitted=(12, 10))
        self.assertTrue(result['available'])
        self.assertEqual(result['visual_accuracy_percent'], 100.)
        self.assertGreater(opened.call_count, 0)
        self.assertTrue(gpu.backend_health_snapshot())

    def test_all_three_real_comparisons_forward_cpu_auto_or_forced_cuda_unchanged(self):
        self.measured['scores_large'] = [dict(backend_id='cuda:0', workload=name,
            throughput_mp_s=200., elapsed_ms=1., device='Controlled CUDA')
            for name in ('bulk_matrix', 'oklab', 'edge_map')]
        actual_select = gpu.select_route
        for policy, expected in (('CPU', 'cpu:numpy'), ('Auto', 'opencl:0:0'),
                                 ('NVIDIA CUDA', 'cuda:0')):
            with self.subTest(policy=policy):
                gpu.reset_runtime_backend_health()
                selected = []
                def select(workload, **kwargs):
                    route = actual_select(workload, **kwargs)
                    selected.append((workload, kwargs['gpu_mode'], route.backend_id))
                    return route
                with closing(Image.new('RGB', (12, 10), 'black')) as image, \
                        patch.object(hardware, 'load_hardware_profile', return_value=self.measured) as loaded, \
                        patch.object(gpu, 'select_route', side_effect=select), \
                        patch.object(gpu, '_opencl_context', side_effect=RuntimeError('controlled unavailable OpenCL')) as opened, \
                        patch.dict(sys.modules, {'cupy': None}):
                    result = score_final_canvas_snapshot(snapshot=image, original_source=image,
                        simulated_final=image, quantized_target=image,
                        area=(0, 0, 12, 10), fitted=(12, 10), gpu_mode=policy)
                # The actual selector is unchanged. Unavailable native devices
                # exercise its existing quarantine + CPU numerical fallback.
                self.assertEqual(len(selected), 12)
                self.assertEqual({mode for _, mode, _ in selected}, {policy})
                for workload in ('pixel_math', 'delta_e', 'edge_map'):
                    first = next(backend for name, _, backend in selected if name == workload)
                    self.assertEqual(first, expected)
                self.assertTrue(result['available'])
                self.assertEqual(result['visual_accuracy_percent'], 100.)
                if policy == 'CPU':
                    loaded.assert_not_called()
                    opened.assert_not_called()
                    self.assertFalse(gpu.backend_health_snapshot())
                else:
                    self.assertTrue(gpu.backend_health_snapshot())


if __name__ == '__main__':
    unittest.main()
