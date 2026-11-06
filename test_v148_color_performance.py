import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import AdaptivePaletteFidelity as adaptive
import ColorMatchingEngine as measurement
import ExactColorEngine as exact
import PaletteMaps
import PicturePaletteRefinement as refinement
import SmartColorEngine as smart
import VisualImportanceMap as importance
from ColorFidelity import delta_e_oklab


class ColorWorkReuseTests(unittest.TestCase):
    def test_rgb_fast_path_preserves_visible_pixels_and_ownership(self):
        source = Image.new('RGB', (8, 5), (12, 34, 56))
        visible = measurement.visible_rgb_image(source)
        self.assertEqual(visible.tobytes(), source.tobytes())
        visible.putpixel((0, 0), (0, 0, 0))
        self.assertEqual(source.getpixel((0, 0)), (12, 34, 56))
        source.info['transparency'] = (12, 34, 56)
        self.assertEqual(measurement.visible_rgb_image(source).getpixel((0, 0)), (255, 255, 255))

    def test_grouped_region_measurements_match_independent_masks(self):
        rng = np.random.default_rng(31)
        source = Image.fromarray(rng.integers(0, 256, (80, 300, 4), dtype=np.uint8))
        labels = rng.integers(0, 2, (80, 300), dtype=np.uint8)
        visible = np.asarray(measurement.visible_rgb_image(source))
        alpha = np.asarray(source)[..., 3]
        expected = {int(i): measurement.measure_color_pixels(visible[labels == i], alpha_values=alpha[labels == i])
                    for i in np.unique(labels)}
        actual = measurement.measure_quantized_regions(source, Image.fromarray(labels))
        self.assertEqual(actual, expected)
        with self.assertRaises(ValueError):
            measurement.measure_quantized_regions(source, source.convert('RGB'))

    def test_joint_statistics_match_separate_reference_statistics(self):
        rng = np.random.default_rng(32)
        for count in (1, 2, 31, 1000):
            pixels = rng.integers(0, 256, (count, 3), dtype=np.uint8)
            sample = measurement.measure_color_pixels(pixels)
            region = exact.analyze_region_pixels(pixels)
            mean = tuple(map(lambda v: int(round(v)), np.mean(pixels, axis=0)))
            median = tuple(map(lambda v: int(round(v)), np.median(pixels, axis=0)))
            spread = float(np.max(np.percentile(pixels, 90, axis=0) - np.percentile(pixels, 10, axis=0)))
            for result in (sample, region):
                self.assertEqual(result.mean_rgb, mean)
                self.assertEqual(result.median_rgb, median)
                self.assertEqual(result.spread, spread)

    def test_vector_representative_retains_scalar_winner_and_source_membership(self):
        rng = np.random.default_rng(33)
        for _ in range(30):
            pixels = rng.integers(0, 256, (250, 3), dtype=np.uint8)
            target = tuple(map(int, rng.integers(0, 256, 3)))
            candidates = [tuple(map(int, c)) for c in np.unique(pixels, axis=0)]
            expected = min(candidates, key=lambda c: delta_e_oklab(c, target))
            self.assertEqual(exact._nearest_actual(pixels, target), expected)
            self.assertEqual(exact._nearest_actual(pixels, candidates[0]), candidates[0])

    def test_explicit_single_color_budget_is_authoritative(self):
        groups = [[(0, 0, 9, 0)], [(0, 1, 9, 1)], [(0, 2, 9, 2)]]
        palette = [(0, 0, 0), (255, 255, 255), (255, 0, 0)]
        kept, mapping, metadata = adaptive.select_adaptive_palette(groups, palette, 1)
        self.assertEqual(len(kept), 1)
        self.assertEqual(set(mapping.values()), set(kept))
        self.assertEqual(metadata['max_colors'], 1)
        with self.assertRaises(ValueError):
            adaptive.select_adaptive_palette(groups, palette, 0)

    def test_adaptive_pair_cache_does_not_change_mapping_or_ties(self):
        palette = [(i, (i * 3) % 256, 255 - i) for i in range(0, 256, 8)]
        active = list(range(len(palette)))
        weights = [float(i % 4 + 1) for i in active]
        costs, errors = {}, {}
        for keep in ([0, 4, 9], [0, 4, 9, 12], [9, 4, 0, 14]):
            self.assertEqual(adaptive._map_indices(active, keep, palette, weights, 'Faithful'),
                             adaptive._map_indices(active, keep, palette, weights, 'Faithful',
                                                   cost_cache=costs, error_cache=errors))

    def test_smart_color_compares_each_unordered_pair_once(self):
        palette = [(i, (i * 3) % 256, 255 - i) for i in range(0, 256, 16)]
        groups = [[(0, i, i + 2, i)] for i in range(len(palette))]
        with patch.object(smart, 'delta_e2000', wraps=smart.delta_e2000) as distance:
            weights, meta = smart.smart_color_weights(groups, palette, [1.] * len(palette))
        self.assertEqual(distance.call_count, len(palette) * (len(palette) - 1) // 2)
        self.assertAlmostEqual(sum(weights), len(palette))
        self.assertTrue(meta['smart_color_enabled'])

    def test_preset_component_tracking_keeps_geometry_and_ambiguity_checks(self):
        colors = ((10, 20, 30), (200, 40, 50))
        preset = PaletteMaps.Palette('fixture', 'fixture', ('A', 'B'), colors)
        image = Image.new('RGB', (100, 40), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 29, 29), fill=colors[0])
        draw.rectangle((60, 10, 79, 29), fill=colors[1])
        self.assertEqual(PaletteMaps.detect_preset(image, preset, (100, 200)), [(119, 219), (169, 219)])
        draw.rectangle((35, 10, 54, 29), fill=colors[0])
        with self.assertRaisesRegex(ValueError, 'unambiguously'):
            PaletteMaps.detect_preset(image, preset)

    def test_weighted_tail_matches_expanded_percentile_exactly(self):
        rng = np.random.default_rng(34)
        for count in (1, 2, 5, 64, 1000):
            for _ in range(10):
                errors = rng.random(count, dtype=np.float32)
                weights = rng.integers(1, 31, count, dtype=np.int64)
                expected = float(np.percentile(np.repeat(errors, weights), 95))
                self.assertEqual(refinement._weighted_tail_error(errors, weights), expected)
        errors = np.linspace(0, 1, 40, dtype=np.float32)
        self.assertEqual(refinement._weighted_tail_error(errors, np.ones(40, np.int64)),
                         float(np.percentile(errors, 95)))


class ImportanceConsistencyTests(unittest.TestCase):
    def test_gpu_formula_matches_cpu_sparse_and_constant_normalization(self):
        rng = np.random.default_rng(35)
        cases = [np.full((8, 8), .1, np.float32), np.zeros((8, 8), np.float32),
                 rng.random((32, 32), dtype=np.float32)]
        sparse = np.zeros((20, 20), np.float32); sparse[1, 1] = .1; cases.append(sparse)
        for values in cases:
            np.testing.assert_allclose(importance._normalize_gpu(values, np),
                                       importance._normalize(values), atol=1e-6)

    def test_transparent_hidden_colors_do_not_create_importance(self):
        source = Image.new('RGBA', (12, 12), (255, 0, 0, 0))
        source.putpixel((6, 6), (0, 0, 0, 255))
        visible = measurement.visible_rgb_image(source)
        actual, _ = importance.build_importance_map(source, {'gpu_mode': 'CPU'})
        expected, _ = importance.build_importance_map(visible, {'gpu_mode': 'CPU'})
        np.testing.assert_array_equal(actual, expected)

    def test_small_or_invalid_vram_budget_does_not_dispatch_gpu(self):
        source = Image.new('RGB', (128, 128))
        for budget in (1, float('nan'), float('inf'), -1, 'invalid'):
            with self.subTest(budget=budget), patch.object(importance, '_gpu_map') as device:
                result, meta = importance.build_importance_map(source, {'gpu_vram_budget_mb': budget})
                device.assert_not_called()
                self.assertEqual(meta['backend'], 'cpu-numpy')
                self.assertEqual(result.shape, (128, 128))

    def test_stop_during_cpu_or_gpu_map_never_publishes_result(self):
        for backend in ('_cpu_map', '_gpu_map'):
            stopped = False
            def finish(*args):
                nonlocal stopped
                stopped = True
                return np.zeros((4, 4), np.float32), {}
            options = {'gpu_mode': 'CPU'} if backend == '_cpu_map' else {}
            with patch.object(importance, backend, side_effect=finish):
                with self.assertRaises(InterruptedError):
                    importance.build_importance_map(Image.new('RGB', (4, 4)), options,
                                                    cancelled=lambda: stopped)
        with patch.object(importance, '_gpu_map', side_effect=InterruptedError()):
            with self.assertRaises(InterruptedError):
                importance.build_importance_map(Image.new('RGB', (4, 4)))


if __name__ == '__main__':
    unittest.main()
