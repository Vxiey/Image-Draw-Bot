from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from PixelMapValidation import validate_color_index, validate_palette_count
from PixelAccuratePlanner import PixelMap, exact_palette_map, groups_from_pixel_map, _cpu_palette_map, build_pixel_map
from PixelAccuracyEngine import simulate_strokes, progressive_accuracy_checkpoints
from PixelStrokeEngine import connected_components


def pixel_map(indices):
    values = np.asarray(indices)
    h, w = values.shape
    return PixelMap(w, h, np.zeros((h, w, 3), np.uint8), values,
                    np.ones((h, w), bool), np.ones((h, w), np.float32),
                    np.ones((h, w), np.float32), np.ones((h, w), bool), {})


class CategoricalIndexContractTests(unittest.TestCase):
    def test_palette_size_keeps_signed_int16_sentinel_available(self):
        for value in (1, 32768, np.int64(32768)):
            self.assertEqual(validate_palette_count(value), int(value))
        for value in (0, -1, 32769, True, False, 2.0, "2", float("nan"), 10 ** 100):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                validate_palette_count(value)

    def test_color_index_never_coerces_or_wraps(self):
        for value in (0, 32767, np.uint16(32767)):
            self.assertEqual(validate_color_index(value), int(value))
        for value in (-1, 32768, np.uint64(2 ** 63), True, 1.0, "1", float("inf")):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                validate_color_index(value)
        self.assertEqual(validate_color_index(np.int16(1), palette_count=2), 1)
        with self.assertRaises(ValueError):
            validate_color_index(2, palette_count=2)

    def test_oversized_palette_is_rejected_before_image_allocation_or_backend_fallback(self):
        with Image.new('RGB', (1, 1)) as source:
            with patch('PixelAccuratePlanner._visible_rgb_rgba', side_effect=AssertionError('allocated')):
                with self.assertRaises(ValueError):
                    exact_palette_map(source, [(0, 0, 0)] * 32769, gpu_mode='CPU')

    def test_invalid_backend_categories_fall_back_without_int16_wrap(self):
        invalid_route = ((np.array([[32768]], np.uint16), np.array([[True]])), {})
        with Image.new('RGB', (1, 1), 'black') as source:
            with patch('UniversalGpuAcceleration.palette_indices_rgba', return_value=invalid_route):
                indices, _, _, metadata = exact_palette_map(source, [(255, 255, 255), (0, 0, 0)], gpu_mode='CPU')
            self.assertEqual(int(indices[0, 0]), 1)
            self.assertIn('outside the palette', metadata['palette_route']['fallback_reason'])
            self.assertEqual(source.getpixel((0, 0)), (0, 0, 0))

    def test_unsigned_component_inputs_keep_the_background_sentinel(self):
        for dtype in (np.uint8, np.uint16, np.uint32, np.uint64):
            pm = pixel_map(np.array([[0, 0]], dtype=dtype))
            pm.drawable_mask[0, 1] = False
            components, labels, _ = connected_components(pm)
            self.assertEqual([component.area for component in components], [1])
            self.assertEqual(labels.tolist(), [[0, -1]])
            self.assertEqual(groups_from_pixel_map(pm, 1), [[(0, 0, 0, 0)]])

    def test_simulation_rejects_invalid_target_background_and_path_indices_before_backend(self):
        palette = [(255, 255, 255), (0, 0, 0)]
        pm = pixel_map(np.array([[1]], np.int16))
        with patch('PixelAccuracyGpu.simulate_cuda', side_effect=AssertionError('backend was called')):
            for index in (-1, 2, 32768, True, '1', 1.0):
                with self.subTest(index=repr(index)), self.assertRaises(ValueError):
                    simulate_strokes(pm, [{'color_index': index, 'path': ((0, 0),)}], palette, gpu_mode='Auto')
            with self.assertRaises(ValueError):
                simulate_strokes(pm, [], palette, background_index=2, gpu_mode='Auto')
            invalid = pixel_map(np.array([[32768]], np.uint16))
            with self.assertRaises(ValueError):
                simulate_strokes(invalid, [], palette, gpu_mode='Auto')
            with self.assertRaises(ValueError):
                progressive_accuracy_checkpoints(invalid, [], palette)


class PixelMapCancellationTests(unittest.TestCase):
    def test_pre_cancelled_mapping_never_allocates_an_image(self):
        with patch('PixelAccuratePlanner._visible_rgb_rgba', side_effect=AssertionError('allocated')):
            with self.assertRaises(InterruptedError):
                exact_palette_map(None, [(0, 0, 0)], cancelled=lambda: True)

    def test_cpu_palette_fallback_can_stop_between_tiles(self):
        checks = 0
        def cancelled():
            nonlocal checks
            checks += 1
            return checks >= 3
        with self.assertRaises(InterruptedError):
            _cpu_palette_map(np.zeros((8, 8, 3), np.uint8), np.array([[0, 0, 0], [255, 255, 255]], np.uint8),
                             perceptual=False, row_chunk=1, cancelled=cancelled)
        self.assertEqual(checks, 3)

    def test_cancelled_map_backend_cannot_continue_to_feature_analysis(self):
        with Image.new('RGB', (2, 2)) as source:
            with patch('UniversalGpuAcceleration.palette_indices_rgba', side_effect=InterruptedError()), \
                    patch('PixelAccuratePlanner.edge_map', side_effect=AssertionError('continued')):
                with self.assertRaises(InterruptedError):
                    build_pixel_map(source, [(0, 0, 0)], cancelled=lambda: False)


if __name__ == "__main__":
    unittest.main()
