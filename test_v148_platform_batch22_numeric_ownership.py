"""Retained failures must not pin a completed numeric operation's private data."""
from contextlib import ExitStack
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import UniversalGpuAcceleration as gpu
from test_gpu_execution_regressions import FakeCupy
from test_v148_gpu_numeric import profile


def retained_error(operation):
    try:
        operation()
    except BaseException as error:
        return error
    raise AssertionError('The operation did not propagate the expected failure')


class ObservedCupy(FakeCupy):
    """Real host arithmetic with observed ownership at the native array boundary."""
    def __init__(self, failure=None):
        super().__init__()
        self.failure = failure
        self.device_arrays = []
        self.host_arrays = []
        self.after_download = None
        self.asarray = self.upload
        self.asnumpy = self.download

    def __getattr__(self, name):
        return getattr(np, name)

    def upload(self, value, dtype=None, **kwargs):
        result = np.array(value, dtype=dtype, copy=True)
        self.device_arrays.append(weakref.ref(result))
        return result

    def download(self, value):
        self.device_arrays.append(weakref.ref(value))
        if self.failure is not None:
            raise self.failure
        result = np.array(value, copy=True)
        self.host_arrays.append(weakref.ref(result))
        if self.after_download is not None:
            self.after_download()
        return result


class NumericOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.source = np.arange(96, dtype=np.uint8).reshape(4, 8, 3)
        self.target = self.source[:, ::-1].copy()
        self.source.flags.writeable = self.target.flags.writeable = False
        self.source_bytes = self.source.tobytes()
        self.target_bytes = self.target.tobytes()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gpu, '_FAILED', {}))
        self.stack.enter_context(patch.object(gpu, '_OPENCL_CACHE', {}))
        self.stack.enter_context(patch.object(gpu, '_OPENCL_IN_USE', {}))

    def calls(self, **settings):
        return (
            ('oklab', lambda: gpu.oklab_array(self.source, **settings)),
            ('pair', lambda: gpu.perceptual_pair(self.source, self.target, **settings)),
            ('edge', lambda: gpu.edge_magnitude(self.source[..., 0], **settings)),
            ('channel', lambda: gpu.pixel_channel_error(self.source, self.target, **settings)),
            ('palette-distance', lambda: gpu.pairwise_oklab_distance(self.source.reshape(-1, 3), **settings)),
        )

    def assert_borrowed_inputs_unchanged(self):
        self.assertEqual(self.source.tobytes(), self.source_bytes)
        self.assertEqual(self.target.tobytes(), self.target_bytes)
        self.assertFalse(self.source.flags.writeable)
        self.assertFalse(self.target.flags.writeable)

    def test_late_cpu_stop_releases_the_finished_result_with_traceback_retained(self):
        stop = threading.Event()
        outputs = []
        original = gpu._oklab_cpu
        def completed(value):
            result = original(value)
            outputs.append(weakref.ref(result))
            stop.set()
            return result
        with patch.object(gpu, '_oklab_cpu', new=completed):
            error = retained_error(lambda: gpu.oklab_array(self.source,
                gpu_mode='CPU', cancelled=stop.is_set))
        self.assertIsInstance(error, InterruptedError)
        self.assertIsNotNone(error.__traceback__)
        self.assertTrue(outputs)
        self.assertTrue(all(reference() is None for reference in outputs))
        self.assert_borrowed_inputs_unchanged()

    def test_interrupted_cuda_attempt_releases_its_arrays_without_quarantine_or_retry(self):
        for name, operation in self.calls(profile=profile('cuda:1')):
            with self.subTest(operation=name):
                failure = InterruptedError('Stop at native result transfer')
                cp = ObservedCupy(failure)
                with patch.dict(sys.modules, {'cupy': cp}), patch.object(gpu, '_mark_failed') as fallback:
                    error = retained_error(operation)
                self.assertIs(error, failure)
                self.assertTrue(cp.device_arrays)
                self.assertTrue(all(reference() is None for reference in cp.device_arrays))
                self.assertEqual(cp.current_device(), 0)
                fallback.assert_not_called()
                self.assertEqual(gpu.backend_health_snapshot(), {})
        self.assert_borrowed_inputs_unchanged()

    def test_late_cuda_stop_releases_downloads_and_private_device_arrays(self):
        stop = threading.Event()
        cp = ObservedCupy()
        cp.after_download = stop.set
        with patch.dict(sys.modules, {'cupy': cp}):
            error = retained_error(lambda: gpu.perceptual_pair(self.source, self.target,
                profile=profile('cuda:1'), cancelled=stop.is_set))
        self.assertIsInstance(error, InterruptedError)
        self.assertIsNotNone(error.__traceback__)
        self.assertEqual(len(cp.host_arrays), 3)
        self.assertTrue(all(reference() is None for reference in cp.device_arrays + cp.host_arrays))
        self.assert_borrowed_inputs_unchanged()

    def test_cuda_oom_releases_failed_work_before_real_cpu_fallback(self):
        expected = dict((name, operation()) for name, operation in self.calls(gpu_mode='CPU'))
        original = gpu._mark_failed
        for name, operation in self.calls(profile=profile('cuda:1')):
            with self.subTest(operation=name):
                failure = MemoryError('temporary allocation pressure')
                cp = ObservedCupy(failure)
                observed = []
                def failed(route, error):
                    observed.append(True)
                    self.assertTrue(cp.device_arrays)
                    self.assertTrue(all(reference() is None for reference in cp.device_arrays),
                                    'Failed device arrays survived into CPU fallback')
                    return original(route, error)
                with patch.dict(sys.modules, {'cupy': cp}), patch.object(gpu, '_mark_failed', new=failed):
                    result = operation()
                self.assertEqual(observed, [True])
                self.assertFalse(result[-1]['accelerated'])
                for actual, reference in zip(result[:-1], expected[name][:-1]):
                    np.testing.assert_array_equal(actual, reference)
                self.assertEqual(gpu.backend_health_snapshot(), {})
                self.assertIsNotNone(failure.__traceback__)
        self.assert_borrowed_inputs_unchanged()

    def test_stop_during_failed_attempt_prevents_cpu_retry(self):
        stop = threading.Event()
        cp = ObservedCupy(MemoryError('temporary allocation pressure'))
        original = cp.download
        def failed_download(value):
            stop.set()
            return original(value)
        cp.asnumpy = failed_download
        with patch.dict(sys.modules, {'cupy': cp}), patch.object(gpu, '_oklab_cpu', wraps=gpu._oklab_cpu) as cpu:
            error = retained_error(lambda: gpu.oklab_array(self.source,
                profile=profile('cuda:1'), cancelled=stop.is_set))
        self.assertIsInstance(error, InterruptedError)
        cpu.assert_not_called()
        self.assertTrue(all(reference() is None for reference in cp.device_arrays))
        self.assertEqual(gpu.backend_health_snapshot(), {})

    def test_successful_cuda_result_stays_owned_by_the_caller(self):
        cp = ObservedCupy()
        expected, _ = gpu.pixel_channel_error(self.source, self.target, gpu_mode='CPU')
        with patch.dict(sys.modules, {'cupy': cp}):
            result, metadata = gpu.pixel_channel_error(self.source, self.target, profile=profile('cuda:1'))
        np.testing.assert_array_equal(result, expected)
        self.assertTrue(metadata['accelerated'])
        self.assertEqual(cp.current_device(), 0)
        self.assertTrue(all(reference() is None for reference in cp.device_arrays))
        self.assertIs(cp.host_arrays[0](), result)
        self.assert_borrowed_inputs_unchanged()

    def test_opencl_palette_failure_releases_buffers_but_preserves_borrowed_context(self):
        references = []
        failure = MemoryError('OpenCL allocation pressure')
        context = object()
        class Buffer:
            def __init__(self, _context, _flags, size=None, hostbuf=None):
                self.context = _context
                self.data = np.array(hostbuf, copy=True) if hostbuf is not None else np.empty(size, dtype=np.uint8)
                references.append(weakref.ref(self))
            def release(self):
                raise AssertionError('Borrowed native owners must not be explicitly released')
        cl = SimpleNamespace(Buffer=Buffer,
            mem_flags=SimpleNamespace(READ_ONLY=1, WRITE_ONLY=2, COPY_HOST_PTR=4),
            enqueue_copy=lambda *args, **kwargs: None)
        def kernel(*args):
            raise failure
        native = (cl, context, object(), SimpleNamespace(ds_palette_kernel=kernel))
        palette = [(0, 0, 0), (255, 255, 255), (255, 0, 0)]
        original = gpu._mark_failed
        def failed(route, error):
            self.assertTrue(references)
            self.assertTrue(all(reference() is None for reference in references))
            self.assertEqual(gpu._OPENCL_IN_USE, {})
            self.assertIs(native[1], context)
            return original(route, error)
        asset = Path(__file__).resolve().parent / 'golden-regression' / 'small-detail-preservation.png'
        with Image.open(asset) as image:
            expected, _ = gpu.palette_indices_rgba(image, palette, range(3), [], gpu_mode='CPU')
            with patch.object(gpu, '_opencl_context', return_value=native), patch.object(gpu, '_mark_failed', new=failed):
                result, metadata = gpu.palette_indices_rgba(image, palette, range(3), [], profile=profile())
            self.assertFalse(metadata['accelerated'])
            for actual, reference in zip(result, expected):
                np.testing.assert_array_equal(actual, reference)
            image.getpixel((0, 0))
        self.assertIsNotNone(failure.__traceback__)
        self.assertEqual(gpu.backend_health_snapshot(), {})


if __name__ == '__main__':
    unittest.main()
