from types import SimpleNamespace
import sys
import unittest
from unittest import mock

import numpy as np

import GpuAcceleration as ga
import GpuBackendStatus as status
import GpuHardware as hardware


class ProbeCuda:
    float32 = np.float32
    arange = staticmethod(np.arange)

    def __init__(self, modes=("good",)):
        self.modes = modes
        self.current = 0
        self.attempts = []
        self.copies = 0
        self.cuda = SimpleNamespace(
            Device=self.device,
            Stream=SimpleNamespace(null=SimpleNamespace(synchronize=lambda: None)),
            runtime=SimpleNamespace(getDeviceCount=lambda: len(modes),
                                    getDevice=lambda: self.current,
                                    getDeviceProperties=lambda i: {"name": f"Visible {i}".encode()}))

    def device(self, index):
        owner = self
        class Device:
            def __enter__(self):
                owner.attempts.append(index)
                owner.current = index
                if owner.modes[index] == "broken":
                    raise RuntimeError("driver unavailable")
                if owner.modes[index] == "interrupted":
                    raise InterruptedError()
            def __exit__(self, *args):
                return False
        return Device()

    def RawKernel(self, *_args):
        def kernel(_blocks, _threads, values):
            if self.modes[self.current] == "partial":
                values[0][3] = 7.0
            else:
                values[0][:] = values[0] * 2 + 1
        return kernel

    def asnumpy(self, value):
        self.copies += 1
        if self.modes[self.current] == "nan":
            return np.full(value.shape, np.nan, dtype=np.float32)
        return np.asarray(value)


class CudaReadinessTests(unittest.TestCase):
    def test_partial_output_is_rejected_and_other_visible_device_is_tested(self):
        cp = ProbeCuda(("partial", "good"))
        # An SMI ordinal/name must not override this runtime's visible ordering.
        with mock.patch.dict(sys.modules, {"cupy": cp}), \
             mock.patch.object(hardware, "best_nvidia_gpu", return_value=hardware.NvidiaGpu(7, "Hidden SMI GPU")):
            ok, message = hardware.cupy_smoke_test()
        self.assertTrue(ok)
        self.assertEqual(cp.attempts, [0, 1])
        self.assertEqual(message, "CUDA ready on Visible 1")

    def test_all_partial_devices_fail_without_false_ready_claim(self):
        cp = ProbeCuda(("broken", "partial"))
        with mock.patch.dict(sys.modules, {"cupy": cp}), mock.patch.object(hardware, "best_nvidia_gpu", return_value=None):
            ok, message = hardware.cupy_smoke_test()
        self.assertFalse(ok)
        self.assertIn("No CUDA-visible GPU passed", message)

    def test_cancellation_during_device_probe_is_not_cpu_fallback(self):
        cp = ProbeCuda(("interrupted", "good"))
        with mock.patch.dict(sys.modules, {"cupy": cp}), mock.patch.object(hardware, "best_nvidia_gpu", return_value=None), \
             self.assertRaises(InterruptedError):
            hardware.cupy_smoke_test()
        self.assertEqual(cp.attempts, [0])


class CudaStatusTests(unittest.TestCase):
    def setUp(self):
        status._CACHE.clear()
        self.addCleanup(status._CACHE.clear)

    def test_bad_arithmetic_does_not_advertise_active_gpu(self):
        cp = ProbeCuda(("nan",))
        info = ga.AccelerationInfo("NVIDIA CUDA", "CuPy CUDA", True, "Visible 0", 8192, 4096)
        with mock.patch.object(ga, "acceleration_info", return_value=info), \
             mock.patch.object(ga, "cuda_context", return_value=(cp, info)):
            result = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
        self.assertFalse(result["gpu_analysis_active"])
        self.assertIn("incorrect output", result["fallback_reason"])

    def test_current_health_and_memory_refresh_while_probe_is_reused(self):
        cp = ProbeCuda()
        info = ga.AccelerationInfo("NVIDIA CUDA", "CuPy CUDA", True, "Visible 0", 8192, 4096)
        newer = ga.AccelerationInfo("NVIDIA CUDA", "CuPy CUDA", True, "Visible 0", 8192, 1024)
        failed = ga.AccelerationInfo("NVIDIA CUDA", "CPU", False, reason="driver lost")
        with mock.patch.object(ga, "acceleration_info", side_effect=[info, newer, failed]), \
             mock.patch.object(ga, "cuda_context", return_value=(cp, info)):
            first = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
            first["benchmark"]["elements"] = 999  # must not mutate cached probe evidence
            second = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
            third = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
        self.assertTrue(second["gpu_analysis_active"])
        self.assertEqual(second["vram_free_mb"], 1024)
        self.assertEqual(second["benchmark"]["elements"], 256)
        self.assertEqual(cp.copies, 1)
        self.assertFalse(third["gpu_analysis_active"])
        self.assertEqual(third["fallback_reason"], "driver lost")

    def test_probe_expires_and_cache_is_bounded(self):
        cp = ProbeCuda()
        info = ga.AccelerationInfo("NVIDIA CUDA", "CuPy CUDA", True, "Visible 0")
        with mock.patch.object(status.time, "monotonic", return_value=100):
            status._cuda_probe(cp, info)
        with mock.patch.object(status.time, "monotonic", return_value=131):
            status._cuda_probe(cp, info)
        self.assertEqual(cp.copies, 2)
        for value in range(100):
            status._remember((value,), {"value": value})
        self.assertEqual(len(status._CACHE), status._CACHE_LIMIT)

    def test_same_model_cards_cannot_share_arithmetic_approval(self):
        cp = ProbeCuda(("good", "nan"))
        info = ga.AccelerationInfo("NVIDIA CUDA", "CuPy CUDA", True, "Identical model", 8192, 4096)
        with mock.patch.object(ga, "acceleration_info", return_value=info), \
             mock.patch.object(ga, "cuda_context", return_value=(cp, info)):
            first = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
            cp.current = 1
            second = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
        self.assertTrue(first["gpu_analysis_active"])
        self.assertFalse(second["gpu_analysis_active"])
        self.assertIn("incorrect output", second["fallback_reason"])
        self.assertEqual(cp.copies, 2)

    def test_unreadable_runtime_identity_never_reuses_probe_evidence(self):
        cp = ProbeCuda(("good", "nan"))
        cp.cuda.runtime.getDevice = mock.Mock(side_effect=OSError("identity unavailable"))
        info = ga.AccelerationInfo("NVIDIA CUDA", "CuPy CUDA", True, "Identical model", 8192, 4096)
        with mock.patch.object(ga, "acceleration_info", return_value=info), \
             mock.patch.object(ga, "cuda_context", return_value=(cp, info)):
            first = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
            cp.current = 1
            second = status.verified_gpu_status("NVIDIA CUDA", pixels=200000)
        self.assertTrue(first["gpu_analysis_active"])
        self.assertFalse(second["gpu_analysis_active"])
        self.assertEqual(cp.copies, 2)
        self.assertEqual(status._CACHE, {})


if __name__ == "__main__":
    unittest.main()
