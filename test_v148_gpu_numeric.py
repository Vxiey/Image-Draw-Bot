import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from ColorFidelity import rgb_to_oklab
import UniversalGpuAcceleration as gpu
import AdvancedColor


def profile(backend='opencl:0:0'):
    return {'version': 1, 'workload_preferences': {
        name: {'backend_id': backend, 'min_pixels': 0}
        for name in ('oklab', 'palette_match', 'edge_map', 'bulk_matrix')
    }, 'scores_large': []}


class GpuNumericTests(unittest.TestCase):
    def tearDown(self):
        gpu.reset_runtime_backend_health()

    def test_dark_integer_rgb_and_normalized_float_are_distinct(self):
        rgb = np.array([[[0, 0, 0], [1, 1, 1], [0, 1, 0]]], dtype=np.uint8)
        expected = np.array([[rgb_to_oklab(tuple(map(int, c))) for c in rgb[0]]])
        for dtype in (np.uint8, np.int32):
            lab, _ = gpu.oklab_array(rgb.astype(dtype), gpu_mode='CPU')
            np.testing.assert_allclose(lab, expected, atol=1e-6)
            left, right, delta, _ = gpu.perceptual_pair(rgb.astype(dtype), rgb / 255, gpu_mode='CPU')
            np.testing.assert_allclose(left, right, atol=1e-6)
            np.testing.assert_allclose(delta, 0, atol=1e-6)
            error, _ = gpu.pixel_channel_error(rgb.astype(dtype), rgb / 255, gpu_mode='CPU')
            np.testing.assert_allclose(error, 0, atol=1e-7)
        white, _ = gpu.oklab_array(np.ones((1, 1, 3), np.float32), gpu_mode='CPU')
        self.assertGreater(float(white[0, 0, 0]), .99)

    def test_nonfinite_rgb_is_rejected_before_backend_dispatch(self):
        for value in (np.nan, np.inf, -np.inf):
            with self.subTest(value=value), patch.object(gpu, 'select_route') as route:
                with self.assertRaises(ValueError):
                    gpu.oklab_array(np.full((1, 1, 3), value), profile=profile())
                route.assert_not_called()
        self.assertEqual(gpu.backend_health_snapshot(), {})

    def test_empty_distance_matrix_needs_no_compute_backend(self):
        with patch.object(gpu, 'select_route', side_effect=AssertionError('No device needed')):
            result, meta = gpu.pairwise_oklab_distance([])
        self.assertEqual(result.shape, (0, 0))
        self.assertEqual(result.dtype, np.float32)
        self.assertFalse(meta['accelerated'])

    def test_forced_cuda_ignores_invalid_scores_and_selects_verified_candidate(self):
        payload = profile('cpu:numpy')
        payload['scores_large'] = [
            {'workload': 'oklab', 'backend_id': 'cuda:0', 'throughput_mp_s': value}
            for value in ('invalid', None, np.nan, np.inf, -1, 0)
        ] + [{'workload': 'oklab', 'backend_id': 'cuda:1', 'throughput_mp_s': 50, 'elapsed_ms': 2}]
        route = gpu.select_route('oklab', pixels=100, gpu_mode='NVIDIA CUDA', profile=payload)
        self.assertEqual(route.backend_id, 'cuda:1')
        for invalid in (None, {'unexpected': 'object'}, 'invalid'):
            payload['scores_large'] = invalid
            self.assertFalse(gpu.select_route('oklab', pixels=100, gpu_mode='NVIDIA CUDA', profile=payload).accelerated)

    def test_invalid_backend_indices_never_select_python_negative_index(self):
        for value in ('opencl:-1:0', 'opencl:0:-1', 'opencl:0:1.5', 'opencl:0:١',
                      'cuda:-1', 'cuda:0.5', 'unknown:0', 'cuda:'):
            with self.subTest(value=value):
                self.assertFalse(gpu.select_route('oklab', pixels=20, profile=profile(value)).accelerated)
        with self.assertRaises(ValueError):
            gpu._opencl_context('opencl:-1:0')
        with self.assertRaises(ValueError):
            gpu._cuda_device_id('other:0')

    def test_backend_cancellation_is_not_quarantined_or_retried_as_cpu(self):
        rgb = np.ones((2, 2, 3), np.float32)
        operations = (
            lambda: gpu.oklab_array(rgb, profile=profile()),
            lambda: gpu.perceptual_pair(rgb, rgb, profile=profile()),
            lambda: gpu.edge_magnitude(rgb[..., 0], profile=profile()),
            lambda: gpu.pixel_channel_error(rgb, rgb, profile=profile()),
            lambda: gpu.pairwise_oklab_distance([(1, 2, 3)], profile=profile()),
        )
        with patch.object(gpu, '_opencl_context', side_effect=InterruptedError()):
            for operation in operations:
                with self.assertRaises(InterruptedError):
                    operation()
        self.assertEqual(gpu.backend_health_snapshot(), {})

    def test_cpu_result_is_withheld_if_stop_arrives_during_computation(self):
        stopped = False
        original = gpu._oklab_cpu
        def complete_then_stop(*args, **kwargs):
            nonlocal stopped
            result = original(*args, **kwargs)
            stopped = True
            return result
        with patch.object(gpu, '_oklab_cpu', side_effect=complete_then_stop):
            with self.assertRaises(InterruptedError):
                gpu.oklab_array(np.zeros((2, 2, 3)), gpu_mode='CPU', cancelled=lambda: stopped)

    def test_color_planner_passes_stop_into_acceleration_and_discards_late_result(self):
        stopped = False
        cancel = lambda: stopped
        def map_colors(image, *args, **kwargs):
            nonlocal stopped
            self.assertIs(kwargs['cancelled'], cancel)
            stopped = True
            return (np.zeros((2, 2), np.int16), np.ones((2, 2), bool)), {'backend_id': 'opencl:0:0'}
        route = gpu.RouteInfo('palette_match', 'palette_match', 'opencl:0:0',
                              'OpenCL', 'GPU', 'fixture', True, 4)
        with patch.object(gpu, 'select_route', return_value=route), \
                patch.object(gpu, 'palette_indices_rgba', side_effect=map_colors), \
                patch.object(AdvancedColor, '_parallel_color_strokes') as retry:
            groups, meta = AdvancedColor.build_color_strokes(
                Image.new('RGB', (2, 2)), gpu_mode='Auto', cancelled=cancel, cpu_workers=2)
        self.assertIsNone(groups)
        self.assertTrue(meta['cancelled'])
        retry.assert_not_called()

    def test_health_snapshot_waits_for_coherent_mutation(self):
        entered, finished = threading.Event(), threading.Event()
        result = []
        def read():
            entered.set()
            result.append(gpu.backend_health_snapshot())
            finished.set()
        with gpu._HEALTH_LOCK:
            gpu._FAILED[('cuda:0', 'oklab')] = 'first'
            worker = threading.Thread(target=read)
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(finished.wait(.02))
            gpu._FAILED[('cuda:1', 'pixel_math')] = 'second'
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [{'cuda:0|oklab': 'first', 'cuda:1|pixel_math': 'second'}])

    def test_palette_transform_reuse_preserves_dense_reference(self):
        rng = np.random.default_rng(67)
        rgb = rng.integers(0, 256, (3, 1500, 3), dtype=np.uint8)
        palette = rng.integers(0, 256, (71, 3)).tolist()
        source_float = rgb.astype(np.float32)
        palette_float = np.asarray(palette, dtype=np.float32)
        dense_difference = source_float[..., None, :] - palette_float
        np.testing.assert_array_equal(gpu._squared_color_distances(source_float, palette_float),
                                      np.sum(dense_difference * dense_difference, axis=-1, dtype=np.float32))
        expected = gpu._palette_cost_cpu(rgb, np.asarray(palette),
                                        perceptual=True, fidelity='Faithful').argmin(axis=-1)
        with patch.object(gpu, '_oklab_cpu', wraps=gpu._oklab_cpu) as convert:
            (actual, _), _ = gpu.palette_indices_rgba(
                Image.fromarray(rgb), palette, range(71), [], gpu_mode='CPU', color_fidelity='Faithful')
        np.testing.assert_array_equal(actual, expected)
        # One palette conversion and two bounded source tiles replace the
        # former repeated conversion for every pixel/palette tile pair.
        self.assertEqual(convert.call_count, 3)


if __name__ == '__main__':
    unittest.main()
