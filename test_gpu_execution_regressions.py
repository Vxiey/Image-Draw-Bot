"""Portable CUDA device-selection and raw-kernel ABI regression tests."""
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from PIL import Image

import GpuAcceleration as ga


class FakeCupy(ModuleType):
    """A CPU-backed CUDA facade whose current device is genuinely thread-local."""

    def __init__(self):
        super().__init__("cupy")
        self.local = threading.local()
        self.failed_probes = set()
        self.fail_selection = False
        self.probed = []
        self.pool_devices = []
        self.memory = [(3072, 4096), (6144, 8192)]
        owner = self

        class Device:
            def __init__(self, device_id):
                self.id = device_id

            def __enter__(self):
                self.previous = owner.current_device()
                owner.local.device_id = self.id
                return self

            def __exit__(self, *_):
                owner.local.device_id = self.previous

            def use(self):
                if owner.fail_selection:
                    raise RuntimeError("device cannot be selected")
                owner.local.device_id = self.id

        self.cuda = SimpleNamespace(
            Device=Device,
            runtime=SimpleNamespace(
                getDeviceCount=lambda: len(self.memory),
                getDeviceProperties=self.device_properties,
                memGetInfo=self.memory_info,
            ),
            Stream=SimpleNamespace(null=SimpleNamespace(synchronize=lambda: None)),
        )
        self.pool = SimpleNamespace(
            set_limit=lambda *args, **kwargs: self.pool_devices.append(self.current_device()),
            used_bytes=lambda: 0,
            total_bytes=lambda: 0,
        )
        self.get_default_memory_pool = lambda: self.pool
        self.asarray = lambda value, dtype=None, *, blocking=False: np.array(value, dtype=dtype, copy=True)
        self.asnumpy = np.asarray
        self.empty_like = np.empty_like
        self.clip = np.clip
        self.rint = np.rint
        self.float32 = np.float32
        self.uint8 = np.uint8

    def current_device(self):
        return getattr(self.local, "device_id", 0)

    def device_properties(self, device_id):
        self.probed.append(device_id)
        if device_id in self.failed_probes:
            raise RuntimeError(f"unavailable CUDA device {device_id}")
        return {"name": f"GPU{device_id}".encode(), "major": 8, "minor": 6,
                "multiProcessorCount": 32}

    def memory_info(self):
        free, total = self.memory[self.current_device()]
        return free * 1024**2, total * 1024**2


class CudaExecutionRegressionTests(unittest.TestCase):
    def setUp(self):
        ga.reset_backend_cache()
        self.addCleanup(ga.reset_backend_cache)
        self.cp = FakeCupy()
        scipy = ModuleType("cupyx.scipy")
        scipy.ndimage = SimpleNamespace(gaussian_filter=lambda arr, **kwargs: arr.copy())
        self.enterContext(mock.patch.dict(sys.modules, {
            "cupy": self.cp, "cupyx": ModuleType("cupyx"), "cupyx.scipy": scipy,
        }))
        self.enterContext(mock.patch.object(ga, "best_nvidia_gpu", return_value=None))

    def test_failed_first_device_does_not_hide_healthy_cuda_device(self):
        self.cp.failed_probes.add(0)
        info = ga.acceleration_info()
        self.assertTrue(info.accelerated, info.reason)
        self.assertEqual(info.device, "GPU1")
        self.assertEqual(info.total_vram_mb, 8192)
        self.assertEqual(self.cp.probed, [0, 1])

    def test_all_failed_devices_return_informative_cpu_fallback(self):
        self.cp.failed_probes.update((0, 1))
        info = ga.acceleration_info()
        self.assertFalse(info.accelerated)
        self.assertIn("device 0", info.reason)
        self.assertIn("device 1", info.reason)

    def test_selected_device_is_bound_on_worker_and_after_external_change(self):
        self.assertEqual(ga.acceleration_info().device, "GPU1")
        results = []
        errors = []

        def worker():
            try:
                before = self.cp.current_device()
                context = ga.cuda_context()
                results.append((before, self.cp.current_device(), context[1]))
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0][:2], (0, 1))
        self.assertEqual(results[0][2].device, "GPU1")
        self.assertEqual(results[0][2].total_vram_mb, 8192)
        self.assertTrue(all(device == 1 for device in self.cp.pool_devices))

        self.cp.local.device_id = 0
        self.assertEqual(ga.acceleration_info().total_vram_mb, 8192)
        self.assertEqual(self.cp.current_device(), 1)

    def test_reset_reselects_device_instead_of_reusing_previous_id(self):
        self.assertEqual(ga.acceleration_info().device, "GPU1")
        ga.reset_backend_cache()
        self.cp.memory = [(12000, 16384), (6144, 8192)]
        info = ga.acceleration_info()
        self.assertEqual(info.device, "GPU0")
        self.assertEqual(self.cp.current_device(), 0)

    def test_failed_binding_preserves_cpu_fallback_contract(self):
        self.assertTrue(ga.acceleration_info().accelerated)
        self.cp.fail_selection = True
        info = ga.acceleration_info()
        self.assertFalse(info.accelerated)
        self.assertIn("device cannot be selected", info.reason)

    def test_fused_kernels_receive_the_declared_scalar_abi(self):
        """Exercise both full-frame and tiled call sites, not only source text."""
        image = Image.fromarray(np.arange(32 * 24, dtype=np.uint8).reshape(24, 32))
        expected = np.rint(255.0 * (np.asarray(image, dtype=np.float32) / 255.0)**np.float32(.97)).astype(np.uint8)
        profile = {"structure_weight": .42, "dark_weight": .12, "centre_bias": .20}

        for allocation_mode in ("full", "tiled"):
            with self.subTest(allocation_mode=allocation_mode):
                calls = []

                def enhance(_grid, _block, args):
                    arr, _blur, out, width, height, strength, gamma, focus, lift, tile_y0, canvas_w, canvas_h = args
                    for scalar in (width, height, focus, tile_y0, canvas_w, canvas_h):
                        self.assertIsInstance(scalar, np.int32)
                    for scalar in (strength, gamma, lift):
                        self.assertIsInstance(scalar, np.float32)
                    self.assertEqual(arr.shape, (height, width))
                    self.assertEqual((canvas_w, canvas_h), image.size)
                    self.assertGreaterEqual(tile_y0, 0)
                    self.assertLessEqual(tile_y0 + height, canvas_h)
                    out[...] = 255.0 * (arr / 255.0)**gamma
                    calls.append("enhance")

                def analyze(_grid, _block, args):
                    arr, _blur, saliency, gx, gy, width, height, focus, structure, dark, centre, tile_y0, canvas_w, canvas_h = args
                    for scalar in (width, height, focus, tile_y0, canvas_w, canvas_h):
                        self.assertIsInstance(scalar, np.int32)
                    self.assertEqual((canvas_w, canvas_h), image.size)
                    self.assertGreaterEqual(tile_y0, 0)
                    self.assertLessEqual(tile_y0 + height, canvas_h)
                    for scalar in (structure, dark, centre):
                        self.assertIsInstance(scalar, np.float32)
                    self.assertAlmostEqual(float(structure), .42, places=6)
                    self.assertAlmostEqual(float(dark), .12, places=6)
                    saliency[...] = 1.0 + dark * ((255.0 - arr) / 255.0)
                    gx.fill(0)
                    gy.fill(0)
                    calls.append("analysis")

                plan = {"mode": allocation_mode, "tile_rows": 8 if allocation_mode == "tiled" else 24,
                        "workspace_mb": 1, "budget_mb": 256}
                with mock.patch.object(ga, "_kernels", return_value=(enhance, analyze)), \
                     mock.patch.object(ga, "plan_vram_allocation", return_value=plan):
                    result, info, session = ga.enhance_portrait(
                        image, .42, .97, False, 0, performance="High throughput")
                    self.assertIsNotNone(result, info.reason)
                    np.testing.assert_array_equal(np.asarray(result), expected)
                    saliency, saliency_info = ga.saliency(
                        result, False, profile, performance="High throughput", session=session)
                    self.assertIsNotNone(saliency, saliency_info.reason)
                self.assertIn("enhance", calls)
                self.assertIn("analysis", calls)


if __name__ == "__main__":
    unittest.main()
