"""Normalize existing integer RGB buffers without a second full float owner."""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import UniversalGpuAcceleration as gpu


def dense_reference(raw):
    result = np.asarray(raw, dtype=np.float32)
    maximum = float(np.max(result)) if result.size else 0.
    if np.issubdtype(raw.dtype, np.integer) or maximum > 1.5:
        result = result / 255.0
        maximum /= 255.0
    if not result.size or (maximum <= 1.0 and float(np.min(result)) >= 0.0):
        return result
    return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)


class RgbNormalizationTests(unittest.TestCase):
    def setUp(self):
        asset = Path(__file__).resolve().parent / 'assets' / 'image-draw-bot-app-screenshot.webp'
        with Image.open(asset) as source, source.convert('RGB') as rgb:
            self.source = np.asarray(rgb).copy()

    def test_new_float_owner_survives_division_without_second_rgb_allocation(self):
        # Observe the actual dtype-conversion owner. Its reuse avoids another
        # source-sized float allocation; this is payload identity, not RSS.
        asarray = np.asarray
        converted = []
        def observe(value, *args, **kwargs):
            result = asarray(value, *args, **kwargs)
            if value is self.source and result.dtype == np.float32:
                converted.append(result)
            return result
        expected = dense_reference(self.source)
        with patch.object(np, 'asarray', new=observe):
            actual = gpu._rgb01(self.source)
        self.assertEqual(len(converted), 1)
        self.assertIs(actual, converted[0])
        np.testing.assert_array_equal(actual, expected)

    def test_numeric_dtypes_ranges_and_strides_preserve_exact_normalized_values(self):
        for array in (self.source, self.source[:, ::-1], self.source.astype(np.int16) - 10,
                      self.source.astype(np.uint16) * 257, self.source.astype(np.float64),
                      self.source.astype(np.float32), self.source.astype(np.float32) / 255,
                      self.source.transpose(1, 0, 2), self.source[:0]):
            before = array.tobytes()
            array.flags.writeable = False
            expected = dense_reference(array)
            with self.subTest(dtype=array.dtype.str, shape=array.shape, strides=array.strides):
                actual = gpu._rgb01(array)
                np.testing.assert_array_equal(actual, expected)
                self.assertEqual(actual.dtype, np.float32)
                self.assertEqual(array.tobytes(), before)
                self.assertFalse(array.flags.writeable)

    def test_normalized_float_input_remains_borrowed_and_byte_scaled_float_is_copied(self):
        normalized = self.source.astype(np.float32) / 255
        normalized.flags.writeable = False
        self.assertIs(gpu._rgb01(normalized), normalized)
        scaled = self.source.astype(np.float32)
        scaled.flags.writeable = False
        result = gpu._rgb01(scaled)
        self.assertFalse(np.shares_memory(result, scaled))
        np.testing.assert_array_equal(scaled, self.source)

    def test_all_public_numeric_callers_retain_integer_byte_scale(self):
        integer = self.source
        normalized = dense_reference(integer)
        for operation in (
                lambda value: gpu.oklab_array(value, gpu_mode='CPU'),
                lambda value: gpu.perceptual_pair(value, value[:, ::-1], gpu_mode='CPU'),
                lambda value: gpu.pixel_channel_error(value, value[:, ::-1], gpu_mode='CPU')):
            actual, expected = operation(integer), operation(normalized)
            for left, right in zip(actual[:-1], expected[:-1]):
                np.testing.assert_array_equal(left, right)
            self.assertEqual(actual[-1], expected[-1])


if __name__ == '__main__':
    unittest.main()
