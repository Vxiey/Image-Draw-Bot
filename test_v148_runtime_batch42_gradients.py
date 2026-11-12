"""Exact bounded gradient work on committed-image derivatives.

The independent oracle uses NumPy's public gradient operation. Complete public
consumer comparisons also retain the real dense branch as their control; they
do not replace planners or manufacture image motifs.
"""
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import ImageGradients as gradients
import UniversalGpuAcceleration as gpu


def source_image(size=(385, 257)):
    path = Path(__file__).parent / 'assets' / 'paint-tools-reference.png'
    with closing(Image.open(path)) as image, closing(image.convert('RGB')) as rgb:
        return rgb.resize(size, Image.Resampling.NEAREST)


def luminance_sample(size=(771, 517), dtype=np.float32):
    with closing(source_image(size)) as image, closing(image.convert('L')) as gray:
        return np.asarray(gray, dtype=dtype) / dtype(255)


def independent_gradient(source):
    # np.gradient implements one-sided physical edges and centered interiors.
    # A singleton axis contributes zero, and an empty result keeps its shape.
    horizontal = np.gradient(source, axis=1) if source.shape[1] > 1 else np.zeros_like(source)
    vertical = np.gradient(source, axis=0) if source.shape[0] > 1 else np.zeros_like(source)
    return np.sqrt(horizontal * horizontal + vertical * vertical)


class BoundedGradientTests(unittest.TestCase):
    def test_exact_oracle_at_tile_seams_empty_singleton_and_two_pixel_axes(self):
        base = luminance_sample()
        cases = [base, base.T, base[::-1, ::-1], base[:, ::2],
                 base[:0, :7], base[:7, :0], base[:1, :1], base[:2, :], base[:, :2],
                 luminance_sample((262145, 1)), luminance_sample((1, 262145)),
                 luminance_sample((131073, 2)), luminance_sample((2, 131073)),
                 base.astype(np.float64), np.asfortranarray(base)]
        for source in cases:
            with self.subTest(shape=source.shape, dtype=source.dtype, strides=source.strides):
                before = source.copy()
                expected = independent_gradient(source)
                actual = gradients.luminance_edges(source)
                self.assertEqual(actual.shape, expected.shape)
                self.assertEqual(actual.dtype, expected.dtype)
                self.assertEqual(actual.strides, expected.strides)
                np.testing.assert_array_equal(actual, expected)
                np.testing.assert_array_equal(source, before)

    def test_large_scratch_is_bounded_and_tile_inputs_borrow_the_source(self):
        source = luminance_sample((771, 517))
        source.setflags(write=False)
        zeros_like = np.zeros_like
        observed = []
        def observe(tile, *args, **kwargs):
            observed.append((tile.shape, tile.size, np.shares_memory(tile, source)))
            return zeros_like(tile, *args, **kwargs)
        with patch.object(gradients.np, 'zeros_like', new=observe):
            result = gradients.luminance_edges(source)
        self.assertGreater(len(observed), 1)
        self.assertLessEqual(max(size for _, size, _ in observed), 258 * 258)
        self.assertTrue(all(shared for _, _, shared in observed))
        np.testing.assert_array_equal(result, independent_gradient(source))

    def test_small_halos_integer_dtype_and_array_backend_keep_dense_dispatch(self):
        source = luminance_sample((258, 258))
        dense = gradients._dense_luminance_edges
        calls = []
        def observe(tile, *, xp):
            calls.append((tile.shape, tile.dtype, xp))
            return dense(tile, xp=xp)
        array_backend = SimpleNamespace(zeros_like=np.zeros_like, sqrt=np.sqrt)
        integer = (source * 255).astype(np.int32)
        with patch.object(gradients, '_dense_luminance_edges', new=observe):
            small = gradients.luminance_edges(source)
            integral = gradients.luminance_edges(integer)
            native = gradients.luminance_edges(source, xp=array_backend)
        self.assertEqual(len(calls), 3)
        self.assertIs(calls[-1][-1], array_backend)
        np.testing.assert_array_equal(small, independent_gradient(source))
        np.testing.assert_array_equal(integral, dense(integer, xp=np))
        np.testing.assert_array_equal(native, small)
        # Exact dense-policy boundaries, including a reversed borrowed view.
        # Keep the original small-halo/integer/native controls above intact.
        for size in ((513, 511), (512, 512), (52429, 5)):
            boundary = luminance_sample(size)
            for values in (boundary, boundary[:, ::-1]):
                calls.clear()
                with self.subTest(pixels=values.size, strides=values.strides), \
                        patch.object(gradients, '_dense_luminance_edges', new=observe):
                    actual = gradients.luminance_edges(values)
                np.testing.assert_array_equal(actual, independent_gradient(values))
                if values.size <= 262144:
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0][0], values.shape)
                else:
                    self.assertGreater(len(calls), 1)
                    self.assertTrue(all(height <= 258 and width <= 258
                                        for (height, width), _dtype, _xp in calls))

    def test_stop_before_allocation_and_after_a_tile_releases_private_outputs(self):
        source = luminance_sample()
        with patch.object(gradients.np, 'empty_like', side_effect=AssertionError('allocation before Stop')):
            with self.assertRaises(InterruptedError):
                gradients.luminance_edges(source, cancelled=lambda: True)
        stop = threading.Event()
        owned = []
        empty_like, dense = np.empty_like, gradients._dense_luminance_edges
        def allocate(*args, **kwargs):
            value = empty_like(*args, **kwargs)
            owned.append(weakref.ref(value))
            return value
        def tile(*args, **kwargs):
            value = dense(*args, **kwargs)
            owned.append(weakref.ref(value))
            stop.set()
            return value
        failure = None
        with patch.object(gradients.np, 'empty_like', new=allocate), \
                patch.object(gradients, '_dense_luminance_edges', new=tile):
            try:
                gradients.luminance_edges(source, cancelled=stop.is_set)
            except InterruptedError as error:
                failure = error
        self.assertIsInstance(failure, InterruptedError)
        self.assertTrue(owned)
        self.assertTrue(all(reference() is None for reference in owned))
        np.testing.assert_array_equal(source, luminance_sample())

    def test_mid_tile_allocation_failure_keeps_identity_and_drops_full_output(self):
        source = luminance_sample()
        empty_like, dense = np.empty_like, gradients._dense_luminance_edges
        outputs, calls = [], []
        failure = MemoryError('controlled second tile allocation')
        def allocate(*args, **kwargs):
            value = empty_like(*args, **kwargs)
            outputs.append(weakref.ref(value))
            return value
        def tile(*args, **kwargs):
            calls.append(None)
            if len(calls) == 2:
                raise failure
            return dense(*args, **kwargs)
        observed = None
        with patch.object(gradients.np, 'empty_like', new=allocate), \
                patch.object(gradients, '_dense_luminance_edges', new=tile):
            try:
                gradients.luminance_edges(source)
            except MemoryError as error:
                observed = error
        self.assertIs(observed, failure)
        self.assertTrue(outputs)
        self.assertTrue(all(reference() is None for reference in outputs))
        np.testing.assert_array_equal(source, luminance_sample())

    def test_real_universal_cpu_and_native_failure_routes_use_exact_bounded_work(self):
        source = luminance_sample()
        expected = independent_gradient(source)
        output, metadata = gpu.edge_magnitude(source, gpu_mode='CPU')
        self.assertEqual(metadata['backend_id'], 'cpu:numpy')
        np.testing.assert_array_equal(output, expected)
        profile = {'workload_preferences': {'edge_map': {
            'backend_id': 'opencl:0:0', 'backend': 'OpenCL', 'vendor': 'controlled',
            'device': 'failed native boundary', 'min_pixels': 0}}}
        with patch.object(gpu, '_FAILED', {}), patch.object(gpu, '_OPENCL_CACHE', {}), \
                patch.object(gpu, '_OPENCL_IN_USE', {}), \
                patch.object(gpu, '_opencl_context', side_effect=MemoryError('native capacity exhausted')) as native:
            output, metadata = gpu.edge_magnitude(source, profile=profile)
            native.assert_called_once()
        self.assertEqual(metadata['backend_id'], 'cpu:numpy')
        np.testing.assert_array_equal(output, expected)

    def test_complete_accuracy_and_visual_importance_consumers_preserve_every_result(self):
        from AccuracyEvaluator import evaluate_preview
        from VisualImportanceMap import build_importance_map
        with closing(source_image((771, 517))) as source, \
                closing(source.resize((97, 65), Image.Resampling.BOX)) as small, \
                closing(small.resize(source.size, Image.Resampling.NEAREST)) as preview:
            before = source.tobytes(), preview.tobytes()
            with patch.object(gradients, '_DENSE_EDGE_PIXELS', 1 << 60):
                expected_accuracy = evaluate_preview(source, preview, gpu_mode='CPU')
                expected_importance, expected_metadata = build_importance_map(source, {'gpu_mode': 'CPU'})
            actual_accuracy = evaluate_preview(source, preview, gpu_mode='CPU')
            actual_importance, actual_metadata = build_importance_map(source, {'gpu_mode': 'CPU'})
            self.assertEqual(actual_accuracy, expected_accuracy)
            self.assertEqual(actual_metadata, expected_metadata)
            np.testing.assert_array_equal(actual_importance, expected_importance)
            self.assertEqual((source.tobytes(), preview.tobytes()), before)

    def test_complete_pixel_map_keeps_palette_edges_shadow_and_protected_masks(self):
        from PixelAccuratePlanner import build_pixel_map
        palette = ((0, 0, 0), (255, 255, 255), (128, 128, 128), (200, 40, 40), (20, 70, 210))
        with closing(source_image((771, 517))) as source:
            before = source.tobytes()
            with patch.object(gradients, '_DENSE_EDGE_PIXELS', 1 << 60):
                expected = build_pixel_map(source, palette, gpu_mode='CPU')
            actual = build_pixel_map(source, palette, gpu_mode='CPU')
            for name, value in vars(actual).items():
                reference = getattr(expected, name)
                if isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(value, reference, err_msg=name)
                else:
                    self.assertEqual(value, reference, name)
            self.assertEqual(actual.as_meta(), expected.as_meta())
            self.assertEqual(source.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
