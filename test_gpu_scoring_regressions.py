"""Tiled retry accounting and cancellation tests without a CUDA dependency."""
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

import GpuAcceleration as ga
import PixelAccuracyGpu as gpu
from PixelAccuracyEngine import _score


class Scalar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class CpuBackedScoring:
    int16 = np.int16
    uint16 = np.uint16
    uint8 = np.uint8
    uint64 = np.uint64
    asarray = staticmethod(np.asarray)
    zeros = staticmethod(np.zeros)

    def __init__(self, *, fail_copy=None, fail_reduction=None):
        self.copy_count = 0
        self.reduction_count = 0
        self.fail_copy = fail_copy
        self.fail_reduction = fail_reduction
        self.cuda = SimpleNamespace(Stream=SimpleNamespace(null=SimpleNamespace(synchronize=lambda: None)))

    def asnumpy(self, array):
        self.copy_count += 1
        if self.copy_count == self.fail_copy:
            raise MemoryError("simulated host-copy allocation failure")
        return np.asarray(array)

    def count_nonzero(self, array):
        self.reduction_count += 1
        if self.reduction_count == self.fail_reduction:
            raise MemoryError("simulated reduction allocation failure")
        return Scalar(np.count_nonzero(array))

    def sum(self, *args, **kwargs):
        return Scalar(np.sum(*args, **kwargs))


class ScoreRetryRegressionTests(unittest.TestCase):
    def test_failed_tile_does_not_double_count_or_lose_prior_tiles(self):
        shape = (48, 4)
        drawable = np.ones(shape, dtype=bool)
        drawable[:, 3] = False
        desired = np.zeros(shape, dtype=np.int16)
        desired[:, 1] = 1
        desired[:, 2] = 2
        sim = desired.copy()
        counts = np.ones(shape, dtype=np.uint16)
        counts[::3, 0] = 0
        counts[1::2, 2] = 3
        sim[::2, 1] = 2
        sim[::4, 3] = 1
        pixel_map = SimpleNamespace(
            drawable_mask=drawable, palette_index=desired,
            edge_map=np.linspace(0, 1, np.prod(shape), dtype=np.float32).reshape(shape),
            protected_mask=desired == 2,
        )
        expected_error, expected_metrics = _score(pixel_map, sim, counts, 0)

        for failure in ({"fail_copy": 1}, {"fail_copy": 2}, {"fail_reduction": 4}):
            with self.subTest(failure=failure):
                cp = CpuBackedScoring(**failure)
                with mock.patch.object(gpu, "_cuda_context", return_value=(cp, SimpleNamespace(device="Fake GPU"))), \
                     mock.patch.object(ga, "gpu_score_tile_rows", return_value=16), \
                     mock.patch.object(ga, "release_gpu_memory_cache", return_value={}), \
                     mock.patch("CrashDiagnostics.log_event"):
                    result = gpu.score_cuda_host(pixel_map, sim, counts, 0)
                self.assertIsNotNone(result)
                actual_error, actual_metrics = result
                np.testing.assert_array_equal(actual_error, expected_error)
                for key, expected in expected_metrics.items():
                    self.assertEqual(actual_metrics[key], expected, key)
                self.assertEqual(actual_metrics["score_vram_retries"], 1)


class StrokeCancellationRegressionTests(unittest.TestCase):
    def test_cancellation_is_checked_during_one_long_diagonal(self):
        generated = [0]
        original = gpu._bresenham

        def tracked(a, b):
            for point in original(a, b):
                generated[0] += 1
                yield point

        with mock.patch.object(gpu, "_bresenham", side_effect=tracked):
            with self.assertRaises(InterruptedError):
                gpu.compile_swept_rectangles(
                    [{"color_index": 1, "path": [(0, 0), (2000, 2000)]}], 1, 4, 4,
                    cancelled=lambda: generated[0] >= 130)
        self.assertLessEqual(generated[0], 258)

    def test_cancellation_is_checked_while_reading_one_long_path(self):
        generated = [0]

        def points():
            for index in range(2000):
                generated[0] += 1
                yield index % 4, 0

        with self.assertRaises(InterruptedError):
            gpu.compile_swept_rectangles(
                [{"color_index": 1, "path": points()}], 1, 4, 4,
                cancelled=lambda: generated[0] >= 130)
        self.assertLessEqual(generated[0], 258)

    def test_cancellation_is_checked_between_segments_of_one_path(self):
        import PixelAccuracyEngine
        processed = [0]
        original = PixelAccuracyEngine._clip_rect

        def clip(*args):
            processed[0] += 1
            return original(*args)

        with mock.patch.object(PixelAccuracyEngine, "_clip_rect", side_effect=clip):
            with self.assertRaises(InterruptedError):
                gpu.compile_swept_rectangles(
                    [{"color_index": 1, "path": [(0, 0), (1, 0)] * 1000}], 1, 4, 4,
                    cancelled=lambda: processed[0] >= 130)
        self.assertLessEqual(processed[0], 257)


if __name__ == "__main__":
    unittest.main()
