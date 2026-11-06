"""Byte palette normalization and measured backend status regression tests."""
from contextlib import nullcontext
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from ColorFidelity import rgb_to_oklab
import GpuAcceleration as ga
import GpuBackendStatus as status
import UniversalGpuAcceleration as universal


def route(workload, backend_id, pixels):
    accelerated = backend_id != "cpu:numpy"
    return universal.RouteInfo(workload, workload, backend_id, backend_id, "test", "test",
                               accelerated, pixels)


class PaletteNormalizationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.colors = [(0, 0, 0), (1, 1, 1), (1, 0, 0), (0, 1, 0)]
        lab = np.asarray([rgb_to_oklab(color) for color in self.colors], dtype=np.float32)
        self.expected = np.linalg.norm(lab[:, None] - lab[None, :], axis=-1) * 100.0
        self.addCleanup(universal.reset_runtime_backend_health)

    def test_dark_byte_palette_cpu_matches_color_fidelity_reference(self):
        actual, _ = universal.pairwise_oklab_distance(self.colors, gpu_mode="CPU")
        np.testing.assert_allclose(actual, self.expected, rtol=2e-5, atol=2e-5)
        self.assertLess(float(actual[0, 1]), 7.0)

    def test_dark_byte_palette_cuda_receives_the_same_normalization(self):
        cp = ModuleType("cupy")
        cp.__getattr__ = lambda name: getattr(np, name)
        cp.asnumpy = np.asarray
        cp.cuda = SimpleNamespace(Device=lambda _: nullcontext(),
                                  Stream=SimpleNamespace(null=SimpleNamespace(synchronize=lambda: None)))
        with mock.patch.dict(sys.modules, {"cupy": cp}), \
             mock.patch.object(universal, "select_route", return_value=route("quantization", "cuda:0", 16)):
            actual, meta = universal.pairwise_oklab_distance(self.colors)
        self.assertTrue(meta["accelerated"], meta)
        np.testing.assert_allclose(actual, self.expected, rtol=2e-5, atol=2e-5)

    def test_dark_byte_palette_opencl_receives_the_same_normalization(self):
        class Buffer:
            def __init__(self, _ctx, _flags, size=None, *, hostbuf=None):
                self.data = np.array(hostbuf, copy=True) if hostbuf is not None else np.empty(size // 4, dtype=np.float32)

        def lab_kernel(_queue, _global, _local, src, dst, _n):
            target = dst.data.reshape(-1, 4)
            target[:, :3] = universal._oklab_cpu(src.data[:, :3])

        def distance_kernel(_queue, _global, _local, lab, dst, _n):
            values = lab.data.reshape(-1, 4)[:, :3]
            dst.data[:] = (np.linalg.norm(values[:, None] - values[None, :], axis=-1) * 100.0).ravel()

        cl = SimpleNamespace(
            Buffer=Buffer,
            mem_flags=SimpleNamespace(READ_ONLY=1, COPY_HOST_PTR=2, READ_WRITE=4, WRITE_ONLY=8),
            enqueue_copy=lambda _queue, sink, src: np.copyto(sink, src.data),
        )
        context = (cl, object(), SimpleNamespace(finish=lambda: None),
                   SimpleNamespace(ds_oklab_kernel=lab_kernel, ds_pairwise_lab=distance_kernel))
        with mock.patch.object(universal, "_opencl_context", return_value=context), \
             mock.patch.object(universal, "select_route", return_value=route("quantization", "opencl:0:0", 16)):
            actual, meta = universal.pairwise_oklab_distance(self.colors)
        self.assertTrue(meta["accelerated"], meta)
        np.testing.assert_allclose(actual, self.expected, rtol=2e-5, atol=2e-5)

    def test_normalized_float_rgb_api_still_treats_one_as_white(self):
        lab, _ = universal.oklab_array(np.ones((1, 1, 3), dtype=np.float32), gpu_mode="CPU")
        self.assertAlmostEqual(float(lab[0, 0, 0]), 1.0, places=6)


class BackendStatusRegressionTests(unittest.TestCase):
    def setUp(self):
        status._CACHE.clear()
        self.addCleanup(status._CACHE.clear)

    def test_auto_status_respects_measured_crossover_inside_legacy_bucket(self):
        def choose(workload, *, pixels, gpu_mode, profile):
            return route(workload, "opencl:0:0" if pixels >= 80_000 else "cpu:numpy", pixels)

        with mock.patch.object(universal, "select_route", side_effect=choose), \
             mock.patch("UniversalHardwareBenchmark.load_hardware_profile", return_value={}) as load_profile:
            small = status.verified_gpu_status(pixels=40_000)
            large = status.verified_gpu_status(pixels=120_000)
        self.assertFalse(small["gpu_analysis_active"])
        self.assertTrue(large["gpu_analysis_active"])
        self.assertEqual(large["universal_routes"]["palette_match"]["pixels"], 120_000)
        self.assertEqual(load_profile.call_count, 2)

    def test_auto_status_refreshes_same_size_after_route_becomes_unavailable(self):
        available = [True]

        def choose(workload, *, pixels, gpu_mode, profile):
            return route(workload, "opencl:0:0" if available[0] else "cpu:numpy", pixels)

        with mock.patch.object(universal, "select_route", side_effect=choose), \
             mock.patch("UniversalHardwareBenchmark.load_hardware_profile", return_value={}):
            first = status.verified_gpu_status(pixels=200_000)
            available[0] = False
            second = status.verified_gpu_status(pixels=200_000)
        self.assertTrue(first["gpu_analysis_active"])
        self.assertFalse(second["gpu_analysis_active"])

    def test_explicit_cpu_status_keeps_its_existing_cache(self):
        info = ga.AccelerationInfo("CPU", "CPU", False)
        with mock.patch.object(ga, "acceleration_info", return_value=info) as probe:
            first = status.verified_gpu_status("CPU", pixels=1000)
            second = status.verified_gpu_status("CPU", pixels=1000)
        self.assertEqual(first, second)
        self.assertEqual(probe.call_count, 1)


if __name__ == "__main__":
    unittest.main()
