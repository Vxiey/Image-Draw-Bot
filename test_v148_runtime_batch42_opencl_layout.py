"""Exercise real callers at the OpenCL allocation/transfer/kernel boundary.

Only the unavailable native ABI is supplied here. CPU arithmetic supplies the
boundary's deterministic numerical output; these tests establish host layout,
byte counts, producer/consumer agreement and fallback, not physical GPU speed.
All raster samples come from the committed Paint reference asset.
"""
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import UniversalGpuAcceleration as gpu


def measured_profile():
    preference = {'backend_id': 'opencl:0:0', 'backend': 'OpenCL',
                  'vendor': 'controlled', 'device': 'typed native boundary',
                  'min_pixels': 0}
    return {'workload_preferences': {name: dict(preference)
                                    for name in ('oklab', 'palette_match')}}


def asset_rgb():
    path = Path(__file__).parent / 'assets' / 'paint-tools-reference.png'
    with closing(Image.open(path)) as image, closing(image.convert('RGB')) as rgb, \
            closing(rgb.resize((64, 48), Image.Resampling.NEAREST)) as sample:
        return np.asarray(sample, dtype=np.float32) / np.float32(255)


def retained_owner_bytes(array):
    owner = array
    while isinstance(owner.base, np.ndarray):
        owner = owner.base
    return owner.nbytes


class PackedLabBoundary:
    def __init__(self, *, finish_error=None, stop=None):
        self.context = object()
        self.mem_flags = SimpleNamespace(READ_ONLY=1, WRITE_ONLY=2, READ_WRITE=4, COPY_HOST_PTR=8)
        self.allocations = []
        self.references = []
        self.downloads = []
        self.calls = []
        self.finish_error, self.stop = finish_error, stop
        self.queue = SimpleNamespace(finish=self.finish)
        self.program = SimpleNamespace(ds_oklab_kernel=self.lab, ds_delta_kernel=self.delta,
                                       ds_pairwise_lab=self.pairwise)
        owner = self

        class Buffer:
            def __init__(self, context, flags, size=None, *, hostbuf=None):
                assert context is owner.context
                if hostbuf is not None:
                    assert flags == 9 and size is None
                    assert hostbuf.dtype == np.float32 and hostbuf.flags.c_contiguous
                    self.data = hostbuf.reshape(-1).copy()
                else:
                    assert flags in (2, 4) and type(size) is int and size > 0 and size % 4 == 0
                    self.data = np.empty(size // 4, dtype=np.float32)
                owner.allocations.append((flags, self.data.nbytes))
                owner.references.append(weakref.ref(self))

        self.Buffer = Buffer
        self.native = (self, self.context, self.queue, self.program)

    def launch(self, queue, global_size, local_size, count):
        assert queue is self.queue and local_size is None
        assert type(count) is np.int32 and count > 0
        assert global_size == (int(count),)

    def lab(self, queue, global_size, local_size, source, destination, count):
        self.launch(queue, global_size, local_size, count)
        assert source.data.size == count * 4
        assert destination.data.size == count * 3
        self.calls.append(('lab', int(count)))
        destination.data[:] = gpu._oklab_cpu(source.data.reshape(-1, 4)[:, :3]).reshape(-1)
        if self.stop is not None:
            self.stop.set()

    def delta(self, queue, global_size, local_size, left, right, destination, count):
        self.launch(queue, global_size, local_size, count)
        assert left.data.size == right.data.size == count * 3
        assert destination.data.size == count
        self.calls.append(('delta', int(count)))
        destination.data[:] = np.linalg.norm(left.data.reshape(-1, 3) - right.data.reshape(-1, 3), axis=1)

    def pairwise(self, queue, global_size, local_size, source, destination, count):
        assert type(count) is np.int32
        self.launch(queue, global_size, local_size, np.int32(count * count))
        assert source.data.size == count * 3 and destination.data.size == count * count
        self.calls.append(('pairwise', int(count)))
        values = source.data.reshape(-1, 3)
        destination.data[:] = (np.linalg.norm(values[:, None] - values[None, :], axis=-1) * 100).reshape(-1)

    def enqueue_copy(self, queue, destination, source):
        assert queue is self.queue
        assert destination.dtype == np.float32 and destination.flags.c_contiguous
        assert destination.nbytes == source.data.nbytes
        self.downloads.append(weakref.ref(destination))
        np.copyto(destination.reshape(-1), source.data)

    def finish(self):
        if self.finish_error is not None:
            raise self.finish_error


class OpenCLPackedOutputTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('_FAILED', '_OPENCL_CACHE', '_OPENCL_IN_USE'):
            self.stack.enter_context(patch.object(gpu, name, {}))
        self.source = asset_rgb()
        self.profile = measured_profile()

    def assert_packed(self, array):
        self.assertEqual(array.dtype, np.float32)
        self.assertTrue(array.flags.c_contiguous)
        self.assertEqual(retained_owner_bytes(array), array.nbytes)

    def test_oklab_publishes_dense_exact_shape_without_padding_or_a_copy(self):
        for source in (self.source, self.source[::-1, ::2],
                       self.source.transpose(1, 0, 2), self.source.reshape(2, 24, 64, 3)):
            with self.subTest(shape=source.shape, strides=source.strides):
                boundary = PackedLabBoundary()
                before = source.copy()
                expected, _ = gpu.oklab_array(source, gpu_mode='CPU')
                with patch.object(gpu, '_opencl_context', return_value=boundary.native):
                    output, metadata = gpu.oklab_array(source, profile=self.profile)
                self.assertTrue(metadata['accelerated'], metadata)
                np.testing.assert_array_equal(output, expected)
                np.testing.assert_array_equal(source, before)
                self.assert_packed(output)
                self.assertIs(boundary.downloads[0](), output, 'Publish the actual download owner')
                count = source.size // 3
                self.assertEqual(boundary.allocations, [(9, count * 16), (2, count * 12)])
                self.assertTrue(all(reference() is None for reference in boundary.references))

    def test_pair_owns_only_its_three_channel_results_and_delta(self):
        target = self.source[:, ::-1]
        expected = gpu.perceptual_pair(self.source, target, gpu_mode='CPU')
        boundary = PackedLabBoundary()
        with patch.object(gpu, '_opencl_context', return_value=boundary.native):
            output = gpu.perceptual_pair(self.source, target, profile=self.profile)
        self.assertTrue(output[3]['accelerated'], output[3])
        for actual, reference in zip(output[:3], expected[:3]):
            np.testing.assert_array_equal(actual, reference)
            self.assert_packed(actual)
        self.assertIs(boundary.downloads[0](), output[0])
        self.assertIs(boundary.downloads[1](), output[1])
        pixels = self.source.shape[0] * self.source.shape[1]
        self.assertEqual(sum(retained_owner_bytes(value) for value in output[:3]), pixels * 28)
        self.assertEqual(boundary.allocations,
                         [(9, pixels * 16), (9, pixels * 16), (4, pixels * 12),
                          (4, pixels * 12), (2, pixels * 4)])
        self.assertTrue(all(reference() is None for reference in boundary.references))

    def test_pair_preserves_single_rgb_and_scalar_delta_shapes(self):
        source, target = self.source[0, 0], self.source[-1, -1]
        boundary = PackedLabBoundary()
        with patch.object(gpu, '_opencl_context', return_value=boundary.native):
            output = gpu.perceptual_pair(source, target, profile=self.profile)
        self.assertTrue(output[3]['accelerated'], output[3])
        self.assertEqual([value.shape for value in output[:3]], [(3,), (3,), ()])
        for actual, expected in zip(output[:3], gpu.perceptual_pair(source, target, gpu_mode='CPU')[:3]):
            np.testing.assert_array_equal(actual, expected)
            self.assert_packed(actual)

    def test_pairwise_consumer_reads_the_same_packed_lab_abi(self):
        colors = np.unique((self.source * 255).astype(np.uint8).reshape(-1, 3), axis=0)[:31]
        expected, _ = gpu.pairwise_oklab_distance(colors, gpu_mode='CPU')
        boundary = PackedLabBoundary()
        with patch.object(gpu, '_opencl_context', return_value=boundary.native):
            output, metadata = gpu.pairwise_oklab_distance(colors, profile=self.profile)
        self.assertTrue(metadata['accelerated'], metadata)
        np.testing.assert_array_equal(output, expected)
        self.assertEqual(boundary.allocations, [(9, len(colors) * 16),
                                               (4, len(colors) * 12), (2, len(colors) ** 2 * 4)])
        self.assert_packed(output)

    def test_completed_native_failure_releases_downloads_before_cpu_fallback(self):
        error = RuntimeError('controlled queue completion failure')
        boundary = PackedLabBoundary(finish_error=error)
        expected = gpu.perceptual_pair(self.source, self.source[:, ::-1], gpu_mode='CPU')
        with patch.object(gpu, '_opencl_context', return_value=boundary.native):
            output = gpu.perceptual_pair(self.source, self.source[:, ::-1], profile=self.profile)
        self.assertFalse(output[3]['accelerated'])
        for actual, reference in zip(output[:3], expected[:3]):
            np.testing.assert_array_equal(actual, reference)
        self.assertTrue(all(reference() is None for reference in boundary.downloads))
        self.assertTrue(all(reference() is None for reference in boundary.references))
        self.assertEqual(gpu._OPENCL_IN_USE, {})

    def test_stop_withholds_packed_outputs_without_retained_private_buffers(self):
        stop = threading.Event()
        boundary = PackedLabBoundary(stop=stop)
        failure = None
        with patch.object(gpu, '_opencl_context', return_value=boundary.native):
            try:
                gpu.perceptual_pair(self.source, self.source, profile=self.profile, cancelled=stop.is_set)
            except InterruptedError as error:
                failure = error
        self.assertIsInstance(failure, InterruptedError)
        self.assertTrue(all(reference() is None for reference in boundary.downloads))
        self.assertTrue(all(reference() is None for reference in boundary.references))
        self.assertEqual(gpu._OPENCL_IN_USE, {})
        self.assertEqual(gpu._FAILED, {})


if __name__ == '__main__':
    unittest.main()
