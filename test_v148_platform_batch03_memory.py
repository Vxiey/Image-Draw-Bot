from types import SimpleNamespace
import unittest
from unittest import mock
import weakref

import numpy as np

import GpuAcceleration as ga
import PixelAccuracyGpu as gpu
from test_gpu_scoring_regressions import CpuBackedScoring


def information(*, free=100, budget=100, used=0, cached=0):
    return ga.AccelerationInfo("NVIDIA CUDA", "CUDA", True, "Synthetic GPU", 8192, free,
                               vram_budget_mb=budget, pool_used_mb=used, pool_cached_mb=cached)


class VramBudgetTests(unittest.TestCase):
    def test_zero_free_and_small_limits_are_never_increased(self):
        self.assertEqual(ga.resolve_vram_budget_mb("Auto", 8192, 0), 0)
        for free in (1, 16, 64, 100):
            self.assertLessEqual(ga.resolve_vram_budget_mb("24 GB", 8192, free), free)
        cp = SimpleNamespace(get_default_memory_pool=mock.Mock())
        with self.assertRaises(MemoryError):
            ga._configure_memory_pool(cp, 0)
        cp.get_default_memory_pool.assert_not_called()
        ga._configure_memory_pool(cp, 16)
        cp.get_default_memory_pool.return_value.set_limit.assert_called_once_with(size=16 * 1024 * 1024)

    def test_pool_live_and_reusable_bytes_are_counted_once(self):
        self.assertEqual(ga.available_vram_mb(information(free=0, budget=100, used=40, cached=90)), 50)
        self.assertEqual(ga.available_vram_mb(information(free=100, budget=50, used=40, cached=90)), 10)
        self.assertEqual(ga.available_vram_mb(information(free=100, budget=0)), 0)
        self.assertEqual(ga.available_vram_mb(information(free=100, budget=None)), 100)

    def test_one_row_and_halo_must_fit_real_budget(self):
        for info in (information(free=0), information(budget=0), information(free=1, budget=1)):
            with self.subTest(info=info), self.assertRaises(MemoryError):
                ga.plan_vram_allocation(info, 32768, 100, arrays=40, overlap=8)
        with self.assertRaises(MemoryError):
            ga.gpu_score_tile_rows(information(free=0), 1000, 100)
        rows = ga.gpu_score_tile_rows(information(free=1, budget=1), 1000, 100)
        self.assertLess(rows, 8)
        self.assertLessEqual(rows * 1000 * 64, 1024 * 1024 * .42)
        self.assertFalse(ga._enough_memory(information(budget=0), 8, 8))

    def test_simulation_batch_never_uses_old_128_mib_floor(self):
        plan = gpu._plan(information(free=1, budget=1), 10, 10, 100000)
        self.assertEqual(plan.vram_budget_mb, 1)
        self.assertLessEqual(plan.rectangle_batch_size * 20, 1024 * 1024 * .08)

    def test_transient_allocation_failure_preserves_working_backend(self):
        sentinel = object()
        with mock.patch.object(ga, "_BACKEND_CACHE", sentinel), mock.patch.object(ga, "_BACKEND_DEVICE_ID", 2), \
             mock.patch.object(ga, "_DISABLED_REASON", ""):
            ga._disable_backend(MemoryError("temporary pressure"))
            self.assertIs(ga._BACKEND_CACHE, sentinel)
            self.assertEqual(ga._BACKEND_DEVICE_ID, 2)
            ga._disable_backend(RuntimeError("illegal memory access"))
            self.assertIsNone(ga._BACKEND_CACHE)


class ScoringLifetimeTests(unittest.TestCase):
    def pixel_map(self, shape=(8, 4)):
        return SimpleNamespace(drawable_mask=np.ones(shape, dtype=bool),
                               palette_index=np.zeros(shape, dtype=np.int16),
                               edge_map=np.zeros(shape, dtype=np.float32),
                               protected_mask=np.zeros(shape, dtype=bool))

    def run_score(self, cp, *, cancelled=lambda: False, release=None):
        pixel_map = self.pixel_map()
        with mock.patch.object(gpu, "_cuda_context", return_value=(cp, information())), \
             mock.patch.object(ga, "gpu_score_tile_rows", return_value=8), \
             mock.patch.object(ga, "release_gpu_memory_cache", side_effect=release or (lambda cp: {})), \
             mock.patch("CrashDiagnostics.log_event"):
            return gpu.score_cuda_host(pixel_map, pixel_map.palette_index,
                                       np.ones((8, 4), dtype=np.uint16), 0, cancelled=cancelled)

    def test_failed_tile_arrays_are_released_before_pool_trim_and_retry(self):
        cp = CpuBackedScoring(fail_copy=1)
        references = []
        def uploaded(value, dtype=None):
            result = np.array(value, dtype=dtype, copy=True)
            references.append(weakref.ref(result))
            return result
        cp.asarray = uploaded
        trimmed = []
        def release(_cp):
            trimmed.append(True)
            self.assertTrue(references)
            self.assertTrue(all(reference() is None for reference in references))
            return {}
        result = self.run_score(cp, release=release)
        self.assertIsNotNone(result)
        self.assertEqual(trimmed, [True])
        self.assertEqual(result[1]["score_vram_retries"], 1)
        self.assertEqual(result[1]["score_tile_rows"], 4)

    def test_cancel_during_final_copy_does_not_publish_score(self):
        cp = CpuBackedScoring()
        stop = [False]
        original = cp.asnumpy
        def copy(value):
            stop[0] = True
            return original(value)
        cp.asnumpy = copy
        with self.assertRaises(InterruptedError):
            self.run_score(cp, cancelled=lambda: stop[0])

    def test_final_synchronization_error_is_not_a_verified_score(self):
        cp = CpuBackedScoring()
        cp.cuda.Stream.null.synchronize = mock.Mock(side_effect=RuntimeError("late device failure"))
        self.assertIsNone(self.run_score(cp))

    def test_compiler_rejects_indices_that_cannot_fit_native_short(self):
        for value in (32768, -1, True, "1", 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gpu.compile_swept_rectangles([{"color_index": value, "path": [(0, 0)]}], 1, 4, 4)
        result = gpu.compile_swept_rectangles([{"color_index": np.int32(32767), "path": [(0, 0)]}], 1, 4, 4)
        self.assertEqual(result[0, 4], 32767)


if __name__ == "__main__":
    unittest.main()
