"""Bound scalar accuracy-reduction scratch while preserving existing pixels."""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import UniversalGpuAcceleration as gpu
from test_v148_gpu_numeric import profile


class ErrorReductionTileTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parent / 'assets' / 'image-draw-bot-app-screenshot.webp'
        with Image.open(source) as existing, existing.convert('RGB') as rgb:
            self.source = np.asarray(rgb).astype(np.float32) / 255.0
        self.source.flags.writeable = False
        self.before = self.source.tobytes()

    def test_channel_error_uses_bounded_reductions_and_matches_dense_oracle(self):
        for source in (self.source, self.source[:, ::-1], self.source.transpose(1, 0, 2),
                       self.source.reshape(1, -1, 3), self.source.reshape(1, 1, -1, 3)):
            target = source[::-1]
            expected = np.mean(np.abs(source - target), axis=-1, dtype=np.float32)
            mean = np.mean
            sizes = []
            def bounded(array, *args, **kwargs):
                sizes.append(array.size)
                if array.size > 65536 * 3:
                    raise MemoryError('Scalar channel reduction exceeds its scratch budget')
                return mean(array, *args, **kwargs)
            with self.subTest(strides=source.strides), patch.object(np, 'mean', new=bounded):
                actual, metadata = gpu.pixel_channel_error(source, target, gpu_mode='CPU')
                np.testing.assert_array_equal(actual, expected)
                self.assertFalse(metadata['accelerated'])
                self.assertEqual(sum(sizes), source.size)
                self.assertGreater(len(sizes), 1)
        self.assertEqual(self.source.tobytes(), self.before)

    def test_perceptual_error_uses_bounded_reductions_and_matches_dense_oracle(self):
        target = self.source[::-1, ::-1]
        expected_source, expected_target = gpu._oklab_cpu(self.source), gpu._oklab_cpu(target)
        expected_error = np.linalg.norm(expected_source - expected_target, axis=-1).astype(np.float32)
        norm = np.linalg.norm
        sizes = []
        def bounded(array, *args, **kwargs):
            sizes.append(array.size)
            if array.size > 65536 * 3:
                raise MemoryError('Scalar perceptual reduction exceeds its scratch budget')
            return norm(array, *args, **kwargs)
        with patch.object(np.linalg, 'norm', new=bounded):
            source, target, error, metadata = gpu.perceptual_pair(self.source, target, gpu_mode='CPU')
        for actual, expected in ((source, expected_source), (target, expected_target), (error, expected_error)):
            np.testing.assert_array_equal(actual, expected)
        self.assertEqual(sum(sizes), self.source.size)
        self.assertFalse(metadata['accelerated'])
        self.assertEqual(self.source.tobytes(), self.before)

    def test_single_rgb_keeps_the_original_numpy_scalar_contract(self):
        source, target = self.source[0, 0], self.source[-1, -1]
        channel, _ = gpu.pixel_channel_error(source, target, gpu_mode='CPU')
        a, b, delta, _ = gpu.perceptual_pair(source, target, gpu_mode='CPU')
        self.assertIsInstance(channel, np.float32)
        self.assertIsInstance(delta, np.float32)
        self.assertEqual(channel, np.mean(np.abs(source - target), axis=-1, dtype=np.float32))
        self.assertEqual(delta, np.linalg.norm(a - b, axis=-1))

    def test_cancel_after_one_channel_tile_releases_partial_output(self):
        stopped = threading.Event()
        mean, empty = np.mean, np.empty
        observed = []
        blocks = []
        def allocate(shape, *args, **kwargs):
            result = empty(shape, *args, **kwargs)
            if tuple(shape) == self.source.shape[:-1]:
                observed.append(weakref.ref(result))
            return result
        def reduce(array, *args, **kwargs):
            result = mean(array, *args, **kwargs)
            blocks.append(array.size)
            stopped.set()
            return result
        failure = None
        with patch.object(np, 'mean', new=reduce), patch.object(np, 'empty', new=allocate):
            try:
                gpu.pixel_channel_error(self.source, self.source[::-1], gpu_mode='CPU',
                                        cancelled=stopped.is_set)
            except InterruptedError as error:
                failure = error
        self.assertIsInstance(failure, InterruptedError)
        self.assertEqual(len(blocks), 1)
        self.assertGreater(blocks[0], 0)
        self.assertLessEqual(blocks[0], 65536 * 3)
        self.assertTrue(observed)
        self.assertTrue(all(ref() is None for ref in observed))
        self.assertEqual(self.source.tobytes(), self.before)

    def test_failed_native_attempt_uses_the_bounded_real_cpu_reduction(self):
        expected = np.mean(np.abs(self.source - self.source[::-1]), axis=-1, dtype=np.float32)
        mean = np.mean
        sizes = []
        def reduce(array, *args, **kwargs):
            sizes.append(array.size)
            return mean(array, *args, **kwargs)
        with patch.object(gpu, '_FAILED', {}), \
                patch.object(gpu, '_opencl_context', side_effect=MemoryError('Device is temporarily full')), \
                patch.object(np, 'mean', new=reduce):
            actual, metadata = gpu.pixel_channel_error(self.source, self.source[::-1], profile=profile())
            self.assertEqual(gpu.backend_health_snapshot(), {})
        np.testing.assert_array_equal(actual, expected)
        self.assertFalse(metadata['accelerated'])
        self.assertLessEqual(max(sizes), 65536 * 3)


if __name__ == '__main__':
    unittest.main()
