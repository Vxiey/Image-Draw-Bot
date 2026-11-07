"""Only routes that consume host visible RGB should prepare its full buffer.

NumPy provides the unchanged native-result oracle at the unavailable device
boundary. These tests verify production routing, preparation, transfers,
fallback and ownership; they do not measure or emulate GPU performance.
"""
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

import CudaPalette
import UniversalGpuAcceleration as gpu
from test_gpu_execution_regressions import FakeCupy
from test_v148_gpu_numeric import profile
from test_v148_platform_batch22_numeric_ownership import retained_error


VISIBLE_REFERENCE = gpu._rgba_visible_rgb
PALETTE = ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 100, 255), (0, 0, 0))
CANDIDATES = (4, 3, 2, 1, 0)
CUSTOM = (False, True, False, True, True)
SOURCE = np.array([
    [(0, 0, 0, 255), (255, 255, 255, 255), (255, 0, 0, 128), (0, 100, 255, 254)],
    [(13, 29, 48, 0), (0, 0, 0, 1), (250, 245, 240, 255), (0, 100, 255, 255)],
], dtype=np.uint8)


def native_indices(rgb, palette, ids, custom, *, perceptual, fidelity, custom_first):
    cost = gpu._palette_cost_cpu(rgb, palette, perceptual=bool(perceptual),
                                fidelity=('Off', 'Balanced', 'Faithful')[int(fidelity)])
    chosen = np.argmin(cost, axis=-1)
    if custom_first:
        custom_cost = np.where(custom, cost, np.inf)
        chosen = np.where(custom_cost.min(axis=-1) <= cost.min(axis=-1)*1.06+.0006,
                          custom_cost.argmin(axis=-1), chosen)
    return ids[chosen]


class OpenCLBoundary:
    def __init__(self):
        self.buffers = []
        self.after_kernel = None
        self.failure = None
        self.launches = 0
        boundary = self
        class Buffer:
            def __init__(self, _context, _flags, size=None, hostbuf=None):
                self.data = (np.array(hostbuf, copy=True).view(np.uint8).reshape(-1)
                             if hostbuf is not None else np.empty(size, dtype=np.uint8))
                boundary.buffers.append(weakref.ref(self))
        self.Buffer = Buffer
        self.mem_flags = SimpleNamespace(READ_ONLY=1, WRITE_ONLY=2, COPY_HOST_PTR=4)
        self.context = object()
        self.native = (self, self.context, object(), SimpleNamespace(ds_palette_kernel=self.kernel))

    def enqueue_copy(self, _queue, destination, source, **_settings):
        if isinstance(destination, self.Buffer):
            raw = np.ascontiguousarray(source).view(np.uint8).reshape(-1)
            destination.data[:len(raw)] = raw
        else:
            raw = destination.view(np.uint8).reshape(-1)
            raw[...] = source.data[:len(raw)]

    def kernel(self, _queue, _shape, _local, br, bp, _bl, bi, bc, bo, bm,
               n, count, perceptual, fidelity, custom_first, skip_white):
        n, count = int(n), int(count)
        raw = br.data.view(np.float32)[:n*4].reshape(n, 4).astype(np.uint8)
        rgb, visible = VISIBLE_REFERENCE(raw)
        if skip_white:
            visible &= np.min(rgb, axis=-1) < 245.0
        palette = bp.data.view(np.float32).reshape(count, 4)[:, :3]
        bo.data.view(np.int16)[:n] = native_indices(rgb, palette,
            bi.data.view(np.int16), bc.data, perceptual=perceptual,
            fidelity=fidelity, custom_first=custom_first)
        bm.data[:n] = visible
        self.launches += 1
        if self.after_kernel is not None:
            self.after_kernel()
        if self.failure is not None:
            raise self.failure


class PalettePreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gpu, '_FAILED', {}))
        self.stack.enter_context(patch.object(gpu, '_OPENCL_IN_USE', {}))

    def operation(self, source=SOURCE, **settings):
        return gpu.palette_indices_rgba(source, PALETTE, CANDIDATES, CUSTOM, **settings)

    def test_opencl_outputs_match_cpu_without_preparing_unused_host_buffers(self):
        for rendering in ('RGB nearest', 'Perceptual match'):
            for fidelity in ('Off', 'Balanced', 'Faithful'):
                for skip_white in (False, True):
                    with self.subTest(rendering=rendering, fidelity=fidelity, skip_white=skip_white):
                        settings = dict(color_rendering=rendering, color_fidelity=fidelity,
                                        skip_white=skip_white, custom_mode='Custom colors first')
                        expected, _ = self.operation(gpu_mode='CPU', **settings)
                        native = OpenCLBoundary()
                        with patch.object(gpu, '_opencl_context', return_value=native.native), \
                             patch.object(gpu, '_rgba_visible_rgb', side_effect=MemoryError('unused host buffer')) as prepare:
                            actual, metadata = self.operation(profile=profile(), **settings)
                        self.assertTrue(metadata['accelerated'])
                        self.assertEqual(native.launches, 1)
                        prepare.assert_not_called()
                        for a, b in zip(actual, expected):
                            np.testing.assert_array_equal(a, b)
                        self.assertTrue(all(reference() is None for reference in native.buffers))

    def test_opencl_failure_releases_partial_native_work_before_one_real_cpu_preparation(self):
        expected, _ = self.operation(gpu_mode='CPU')
        native = OpenCLBoundary()
        native.failure = MemoryError('native allocation pressure after partial output')
        calls = []
        def prepare(raw):
            calls.append(True)
            self.assertEqual(native.launches, 1)
            self.assertTrue(native.buffers)
            self.assertTrue(all(reference() is None for reference in native.buffers))
            self.assertEqual(gpu._OPENCL_IN_USE, {})
            return VISIBLE_REFERENCE(raw)
        with patch.object(gpu, '_opencl_context', return_value=native.native), \
             patch.object(gpu, '_rgba_visible_rgb', new=prepare):
            actual, metadata = self.operation(profile=profile())
        self.assertEqual(calls, [True])
        self.assertEqual(native.launches, 1)
        self.assertFalse(metadata['accelerated'])
        self.assertEqual(gpu.backend_health_snapshot(), {})
        for a, b in zip(actual, expected):
            np.testing.assert_array_equal(a, b)

    def test_stop_with_partial_opencl_failure_does_not_start_host_preparation(self):
        stop = threading.Event()
        native = OpenCLBoundary()
        native.failure = MemoryError('native allocation pressure')
        native.after_kernel = stop.set
        with patch.object(gpu, '_opencl_context', return_value=native.native), \
             patch.object(gpu, '_rgba_visible_rgb', wraps=VISIBLE_REFERENCE) as prepare:
            error = retained_error(lambda: self.operation(profile=profile(), cancelled=stop.is_set))
        self.assertIsInstance(error, InterruptedError)
        self.assertEqual(native.launches, 1)
        prepare.assert_not_called()
        self.assertTrue(all(reference() is None for reference in native.buffers))
        self.assertEqual(gpu.backend_health_snapshot(), {})

    def test_cuda_success_and_fallback_reuse_one_correct_host_preparation(self):
        expected, _ = self.operation(gpu_mode='CPU', custom_mode='Custom colors first')
        expected_rgb, expected_visible = VISIBLE_REFERENCE(SOURCE)
        expected_visible &= np.min(expected_rgb, axis=-1) < 245.0
        for failure in (None, MemoryError('native allocation pressure')):
            with self.subTest(fallback=failure is not None):
                cp = FakeCupy()
                def match(_cp, rgb, palette, _lab, ids, custom, **settings):
                    np.testing.assert_array_equal(rgb, expected_rgb)
                    if failure is not None:
                        raise failure
                    return native_indices(rgb, palette, ids, custom,
                        **{key: settings[key] for key in ('perceptual', 'fidelity', 'custom_first')})
                with patch.dict(sys.modules, {'cupy': cp}), \
                     patch.object(CudaPalette, 'match', new=match), \
                     patch.object(gpu, '_rgba_visible_rgb', wraps=VISIBLE_REFERENCE) as prepare:
                    actual, metadata = self.operation(profile=profile('cuda:0'),
                                                       custom_mode='Custom colors first')
                self.assertEqual(prepare.call_count, 1)
                self.assertEqual(metadata['accelerated'], failure is None)
                for a, b in zip(actual, expected):
                    np.testing.assert_array_equal(a, b)
                np.testing.assert_array_equal(actual[1], expected_visible)

    def test_existing_image_and_successful_result_remain_owned_by_the_caller(self):
        fixture = Path(__file__).resolve().parent / 'golden-regression' / 'small-detail-preservation.png'
        native = OpenCLBoundary()
        with Image.open(fixture) as source:
            original = source.tobytes()
            expected, _ = self.operation(source, gpu_mode='CPU')
            with patch.object(gpu, '_opencl_context', return_value=native.native):
                actual, metadata = self.operation(source, profile=profile())
            self.assertTrue(metadata['accelerated'])
            self.assertEqual(source.tobytes(), original)
        for a, b in zip(actual, expected):
            np.testing.assert_array_equal(a, b)


if __name__ == '__main__':
    unittest.main()
