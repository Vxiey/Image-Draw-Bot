import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

import AccuracyEvaluator as accuracy
import AdaptiveColor
import AdvancedColor
import ColorFidelity
import Colors
import PixelData
import UniversalGpuAcceleration as universal


class ColorCorrectnessTests(unittest.TestCase):
    def tearDown(self):
        Colors.reset_palette()

    def test_cached_color_method_still_requires_its_controls(self):
        selector = {'kind': 'custom', 'require_exact': True}
        for method in ('numeric', 'spectrum', 'eyedropper', 'palette'):
            with self.subTest(method=method):
                self.assertEqual(AdaptiveColor.method_candidates(
                    selector, {}, keyboard_available=False, cached_method=method), ())
        controls = {name: (1, 2) for name in
                    ('OpenCustomColor', 'ConfirmColor', 'RedField', 'GreenField', 'BlueField')}
        self.assertEqual(AdaptiveColor.method_candidates(
            selector, controls, cached_method='numeric'), ('numeric',))
        self.assertEqual(AdaptiveColor.method_candidates(
            selector, controls, keyboard_available=False, cached_method='numeric'), ())

    def test_probe_consumes_only_first_distinct_segment(self):
        def path():
            yield (1, 1)
            yield (1, 1)
            yield (21, 1)
            raise AssertionError('The probe must not materialize the remaining path')
        self.assertEqual(AdaptiveColor.probe_item(path(), True), [(1, 1), (5, 1)])

    def test_worker_uses_entire_supplied_palette(self):
        palette = ((255, 255, 255),) * 23 + ((1, 2, 3),)
        names = ('Black',) * 18 + ('Custom',) * 6
        for workflow in ('Calibrated palette', 'Custom colors only'):
            index = AdvancedColor._closest_palette_index_cached(
                (1, 2, 3), palette, names, 'Perceptual match', workflow, 'Exact')
            self.assertEqual(index, 23)
        result = AdvancedColor._color_rows_worker((
            0, 1, bytes((1, 2, 3, 255)), True, False, 'Perceptual match', 'Off',
            'Calibrated palette', 'Exact', palette, names))
        self.assertEqual(result[0][23], [(0, 0, 0, 0)])

    def test_transparent_pixels_break_cpu_runs_when_white_is_enabled(self):
        image = Image.new('RGBA', (3, 1), (255, 0, 19, 255))
        image.putpixel((1, 0), (12, 200, 30, 0))
        groups, metadata = AdvancedColor.build_color_strokes(
            image, skip_white=False, gpu_mode='CPU')
        self.assertEqual(sorted(s for group in groups for s in group),
                         [(0, 0, 0, 0), (2, 0, 2, 0)])
        self.assertEqual(metadata['color_fidelity_diagnostics']['mapped_pixels'], 2)
        palette = tuple(c.RGB for c in Colors.allColors)
        names = tuple(c.name for c in Colors.allColors)
        worker = AdvancedColor._color_rows_worker((
            0, 3, image.tobytes(), True, False, 'Perceptual match', 'Off',
            'Calibrated palette', 'Balanced', palette, names))
        self.assertEqual(worker[0], groups)

    def test_rgb_nearest_matches_euclidean_reference_for_every_fidelity(self):
        rng = np.random.default_rng(12)
        palette = rng.integers(0, 256, (11, 3), dtype=np.int16)
        for source in rng.integers(0, 256, (30, 3), dtype=np.int16):
            expected = int(np.argmin(np.sum((palette.astype(np.int32) - source) ** 2, axis=1)))
            for fidelity in ColorFidelity.COLOR_FIDELITY_MODES:
                scalar = [ColorFidelity.palette_match_cost(
                    tuple(source), tuple(color), color_rendering='RGB nearest', fidelity=fidelity)
                    for color in palette]
                vector = universal._palette_cost_cpu(
                    source[None, :], palette, perceptual=False, fidelity=fidelity)
                self.assertEqual(int(np.argmin(scalar)), expected)
                self.assertEqual(int(np.argmin(vector)), expected)

    def test_serial_mapping_uses_one_palette_snapshot(self):
        image = Image.new('RGB', (12, 3), (255, 0, 19))
        with patch.object(AdvancedColor, 'closest_palette_index', side_effect=AssertionError(
                'Do not reconstruct the same palette for each pixel')):
            groups, _ = AdvancedColor.build_color_strokes(image, gpu_mode='CPU')
        self.assertEqual(groups[10], [(0, y, 11, y) for y in range(3)])

    def test_basic_strokes_normalize_decoded_image_modes(self):
        for image in (Image.new('RGB', (3, 2), 'red'), Image.new('L', (3, 2), 0),
                      Image.new('P', (3, 2), 0)):
            with self.subTest(mode=image.mode):
                self.assertEqual(PixelData.build_strokes(image),
                                 PixelData.build_strokes(image.convert('RGBA')))

    def test_rounded_preparation_never_exceeds_pixel_budget(self):
        for size in ((64, 60), (3, 4000), (4000, 3), (37, 41)):
            image = Image.new('RGB', size)
            for limit in (1, 2, 9, 100, 157):
                with self.subTest(size=size, limit=limit):
                    prepared, _ = PixelData.prepare_image(
                        image, size, sample_limit=10000, max_pixels=limit)
                    self.assertLessEqual(prepared.width * prepared.height, limit)

    def test_preparation_checks_cancellation_before_and_after_resize(self):
        with self.assertRaises(InterruptedError):
            PixelData.prepare_image(None, (20, 20), cancelled=lambda: True)
        stopped = False
        resize = Image.Image.resize
        def stop_after_resize(image, *args, **kwargs):
            nonlocal stopped
            result = resize(image, *args, **kwargs)
            stopped = True
            return result
        with patch.object(Image.Image, 'resize', stop_after_resize):
            with self.assertRaises(InterruptedError):
                PixelData.prepare_image(Image.new('RGB', (20, 20)), (20, 20),
                                        cancelled=lambda: stopped)

    def test_reloading_palette_invalidates_nearest_color_cache(self):
        self.assertEqual(PixelData.closest_color((0, 0, 0)), 0)
        values = [list(c.RGB) for c in Colors.allColors]
        values[0], values[3] = values[3], values[0]
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'palette.json'
            file.write_text(json.dumps(values), encoding='utf-8')
            with patch.object(Colors, 'PALETTE_FILE', file):
                Colors.load_palette()
        self.assertEqual(PixelData.closest_color((0, 0, 0)), 3)


class AccuracyCorrectnessTests(unittest.TestCase):
    def test_preview_and_cached_source_are_compared_as_visible_rgb(self):
        white = Image.new('RGB', (2, 2), 'white')
        clear = Image.new('RGBA', (2, 2), (0, 0, 0, 0))
        result = accuracy.evaluate_preview(white, clear, gpu_mode='CPU')
        self.assertEqual(result['source_pixel_accuracy_percent'], 100.0)
        self.assertEqual(result['perceptual_color_accuracy_percent'], 100.0)
        result = accuracy.evaluate_preview(white, white, normalized_source=clear, gpu_mode='CPU')
        self.assertEqual(result['source_pixel_accuracy_percent'], 100.0)
        gray = Image.new('L', (2, 2), 80)
        result = accuracy.evaluate_preview(gray, gray, normalized_source=gray, gpu_mode='CPU')
        self.assertEqual(result['source_pixel_accuracy_percent'], 100.0)

    def test_importance_keeps_fractional_values_at_protection_threshold(self):
        source = np.array([[.62001, .12345], [.99, .8]], dtype=np.float32)
        same, _ = accuracy._importance_weights(source, (2, 2))
        np.testing.assert_array_equal(same, source)
        resized, _ = accuracy._importance_weights(source, (5, 3))
        expected = np.asarray(Image.fromarray(source).resize((5, 3), Image.Resampling.BILINEAR))
        np.testing.assert_array_equal(resized, expected)
        self.assertGreaterEqual(float(same[0, 0]), .62)
        with self.assertRaises(ValueError):
            accuracy._importance_weights(np.full((2, 2), np.nan), (2, 2))

    def test_nonfinite_percentage_cannot_be_reported_as_perfect_accuracy(self):
        source = Image.new('RGB', (2, 2))
        for name in ('coverage_percent', 'plan_execution_accuracy_percent'):
            for value in (np.nan, np.inf, -np.inf):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    accuracy.evaluate_preview(source, source, gpu_mode='CPU', **{name: value})

    def test_finished_accuracy_result_is_not_returned_after_stop(self):
        stopped = False
        summary = accuracy._delta_e_summary
        def stop_at_summary(*args):
            nonlocal stopped
            result = summary(*args)
            stopped = True
            return result
        with patch.object(accuracy, '_delta_e_summary', side_effect=stop_at_summary):
            with self.assertRaises(InterruptedError):
                accuracy.evaluate_preview(Image.new('RGB', (4, 4)), Image.new('RGB', (4, 4)),
                                          gpu_mode='CPU', cancelled=lambda: stopped)

    def test_heatmap_retains_color_stops_and_clipping(self):
        levels = np.array([[-1, 0, .2, .45, .72, 1, 2]], dtype=np.float32) * .45
        rgb = np.asarray(accuracy._delta_e_preview(levels))[0]
        expected = np.array([(8, 15, 24), (8, 15, 24), (34, 118, 85), (224, 177, 55),
                             (228, 78, 65), (250, 245, 245), (250, 245, 245)])
        np.testing.assert_allclose(rgb, expected, atol=1, rtol=0)


if __name__ == '__main__':
    unittest.main()
