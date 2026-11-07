"""Real source images exercise background and protected-detail contracts."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import PixelAccuracyEngine as accuracy
import PixelAccuracyGpu as gpu
from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan
from test_gpu_scoring_regressions import CpuBackedScoring


def dot_source(color=(0, 0, 0), *, transparent=False):
    image = Image.new('RGBA', (21, 21), (255, 255, 255, 0 if transparent else 255))
    image.putpixel((10, 10), (*color, 255))
    return image


class ActualCanvasBackgroundTests(unittest.TestCase):
    def test_implicit_brush_state_survives_phases_and_empty_entries(self):
        # Completion of PL31: the renderer inherits brush state until a real
        # nonempty action changes it, including across progressive checkpoints.
        with Image.new('RGB', (18,9), 'white') as source:
            draw = ImageDraw.Draw(source)
            draw.rectangle((3,3,5,5), fill='black')
            draw.rectangle((11,3,13,5), fill='black')
            palette = ((255,255,255),(0,0,0))
            pixel_map = build_pixel_map(source, palette, gpu_mode='CPU')
        sequence = [
            {'color_index':1, 'path':((4,4),), 'brush_px':3, 'phase':'fill'},
            {'color_index':0, 'path':(), 'brush_px':1, 'phase':'fill'},
            {'color_index':1, 'path':((12,4),), 'phase':'cleanup'},
        ]
        result = accuracy.simulate_strokes(pixel_map, sequence, palette, brush_px=1)
        self.assertEqual(result.metrics['coverage_percent'], 100)
        self.assertEqual(result.metrics['brush_sizes_used'], [3])
        checkpoints = accuracy.progressive_accuracy_checkpoints(pixel_map, sequence, palette, brush_px=1)
        self.assertEqual([row['coverage_percent'] for row in checkpoints], [50,100])
        np.testing.assert_array_equal(gpu.compile_swept_rectangles(sequence,1,18,9),
            np.asarray(((3,3,5,5,1),(11,3,13,5,1)), np.int32))
        refined = accuracy.refine_with_corrections(pixel_map, sequence, palette, brush_px=1)
        self.assertEqual(refined['metadata']['correction_brush_px'], 3)

    def test_absent_feature_categories_use_target_accuracy_on_cpu_and_gpu(self):
        # Completion of RP18: an absent category must not penalize flat art.
        with Image.new('RGB', (17,13), 'black') as source:
            palette = ((0,0,0),)
            pixel_map = build_pixel_map(source, palette, gpu_mode='CPU')
        self.assertFalse(np.any(pixel_map.edge_map))
        self.assertFalse(np.any(pixel_map.protected_mask))
        sequence = [{'color_index':0, 'path':((0,y),(16,y))} for y in range(13)]
        actual = accuracy.simulate_strokes(pixel_map, sequence, palette)
        self.assertEqual(actual.metrics['edge_accuracy_percent'], 100)
        self.assertEqual(actual.metrics['protected_accuracy_percent'], 100)
        with patch.object(gpu, '_cuda_context', return_value=(CpuBackedScoring(), SimpleNamespace(device='host-backed arithmetic'))), \
             patch('GpuAcceleration.gpu_score_tile_rows', return_value=4):
            _error, metadata = gpu.score_cuda_host(pixel_map, actual.simulated_index, actual.coverage_count, -1)
        self.assertEqual(metadata['edge_accuracy_percent'], 100)
        self.assertEqual(metadata['protected_accuracy_percent'], 100)

    def test_absent_white_never_counts_a_missing_black_stroke_as_correct(self):
        for palette in (((0, 0, 0),), ((250, 250, 250), (0, 0, 0))):
            with self.subTest(palette=palette), dot_source() as source:
                pixel_map = build_pixel_map(source, palette, skip_white=True, gpu_mode='CPU')
                result = accuracy.simulate_strokes(pixel_map, [], palette)
                self.assertEqual(result.metrics['plan_execution_accuracy_percent'], 0)
                self.assertEqual(result.metrics['target_color_accuracy_percent'], 0)
                self.assertEqual(result.metrics['missing_pixels'], 1)
                self.assertEqual(result.metrics['background_index'], -1)
                self.assertFalse(result.metrics['background_repaint_available'])
                self.assertEqual(int(result.simulated_index[10, 10]), -1)

    def test_missing_color_is_corrected_without_a_white_palette_entry(self):
        with dot_source() as source:
            palette = ((0, 0, 0),)
            pixel_map = build_pixel_map(source, palette, skip_white=True, gpu_mode='CPU')
            result = accuracy.refine_with_corrections(pixel_map, [], palette)
            self.assertEqual(result['metadata']['initial_accuracy_percent'], 0)
            self.assertEqual(result['metadata']['final_accuracy_percent'], 100)
            self.assertEqual(result['metadata']['correction_paths_added'], 1)
            self.assertEqual(result['execution_sequence'][0]['color_index'], 0)
            self.assertEqual(result['metadata']['final_error_pixels'], 0)

    def test_unavailable_white_cannot_be_used_to_erase_brush_spill(self):
        with dot_source() as source:
            palette = ((0, 0, 0),)
            pixel_map = build_pixel_map(source, palette, skip_white=True, gpu_mode='CPU')
            sequence = [{'color_index': 0, 'path': ((10, 10),), 'brush_px': 3}]
            result = accuracy.refine_with_corrections(pixel_map, sequence, palette, brush_px=3)
            self.assertEqual(result['metadata']['spill_pixels'], 8)
            self.assertEqual(result['metadata']['unrepairable_background_pixels'], 8)
            self.assertEqual(result['metadata']['correction_paths_added'], 0)
            self.assertLess(result['metadata']['final_accuracy_percent'], 12)
            self.assertTrue(all(entry['color_index'] >= 0 for entry in result['execution_sequence']))

    def test_exact_white_repaints_spill_and_explicit_background_remains_supported(self):
        with dot_source() as source:
            palette = ((0, 0, 0), (255, 255, 255))
            pixel_map = build_pixel_map(source, palette, skip_white=True, gpu_mode='CPU')
            result = accuracy.refine_with_corrections(pixel_map,
                [{'color_index': 0, 'path': ((10, 10),), 'brush_px': 3}], palette,
                brush_px=3, correction_brush_px=1)
            self.assertEqual(result['metadata']['background_index'], 1)
            self.assertTrue(result['metadata']['background_repaint_available'])
            self.assertEqual(result['metadata']['final_error_pixels'], 0)
            self.assertTrue(any(entry['color_index'] == 1 for entry in result['correction_entries']))
            explicit = accuracy.simulate_strokes(pixel_map, [], palette, background_index=0)
            self.assertEqual(explicit.metrics['background_index'], 0)
            self.assertTrue(np.all(explicit.simulated_index == 0))
            with self.assertRaises(ValueError):
                accuracy.simulate_strokes(pixel_map, [], palette, background_index=-1)

    def test_real_gpu_score_branch_accepts_internal_background_sentinel(self):
        with dot_source() as source:
            palette = ((0, 0, 0),)
            pixel_map = build_pixel_map(source, palette, skip_white=True, gpu_mode='CPU')
            simulated = np.full((21, 21), -1, np.int16)
            counts = np.zeros((21, 21), np.uint16)
            simulated[9:12, 9:12] = 0
            counts[9:12, 9:12] = 1
            expected_error, expected = accuracy._score(pixel_map, simulated, counts, -1)
            with patch.object(gpu, '_cuda_context', return_value=(CpuBackedScoring(), SimpleNamespace(device='host-backed arithmetic'))), \
                 patch('GpuAcceleration.gpu_score_tile_rows', return_value=4):
                actual_error, actual = gpu.score_cuda_host(pixel_map, simulated, counts, -1)
            np.testing.assert_array_equal(actual_error, expected_error)
            for key, value in expected.items():
                self.assertEqual(actual[key], value, key)
            self.assertEqual(actual['unrepairable_background_pixels'], 8)

    def test_drawbot_prepared_single_color_plan_reports_real_background(self):
        from DrawBot import make_plan
        from test_pixel_accurate_v1086 import opts
        with dot_source() as source:
            plan = make_plan(source, source.size, opts(
                profile_name='Microsoft Paint', profile_key='microsoft-paint',
                picture_palette_rgb=((0, 0, 0),), exact_color_available=True,
                custom_color_workflow='Adaptive exact (recommended)', skip_white=True,
                brush_px=3, auto_tune=False, hybrid_mode='Manual', detail_zoom='Off',
                time_budget_mode='Unlimited'))
        metadata = plan['options']['pixel_accuracy_meta']
        self.assertEqual(plan['colors'], ((0, 0, 0),))
        self.assertEqual(metadata['background_index'], -1)
        self.assertFalse(metadata['background_repaint_available'])
        self.assertGreater(metadata['unrepairable_background_pixels'], 0)
        self.assertTrue(all(entry['color_index'] == 0 for entry in plan['execution_sequence']))


class BackgroundBoundaryDetailTests(unittest.TestCase):
    def test_skipped_white_and_transparency_preserve_isolated_detail_priority(self):
        for color in ((0, 0, 0), (255, 0, 0), (0, 0, 255)):
            for transparent in (False, True):
                with self.subTest(color=color, transparent=transparent), dot_source(color, transparent=transparent) as source:
                    palette = ((255, 255, 255), color)
                    pixel_map = build_pixel_map(source, palette, skip_white=True, gpu_mode='CPU')
                    plan = build_pixel_stroke_plan(pixel_map, len(palette), options={'adaptive_hybrid_cost': 'Off'})
                    self.assertTrue(pixel_map.protected_mask[10, 10])
                    self.assertGreater(float(pixel_map.micro_detail_map[10, 10]), .6)
                    self.assertEqual(np.count_nonzero(pixel_map.protected_mask), 1)
                    self.assertEqual(len(plan['execution_sequence']), 1)
                    entry = plan['execution_sequence'][0]
                    self.assertEqual(entry['phase'], 'cleanup')
                    self.assertTrue(entry['protected'])
                    self.assertGreater(float(pixel_map.contour_map[10, 10]), 0)
                    self.assertFalse(np.any(pixel_map.contour_map[~pixel_map.drawable_mask]))

    def test_actual_detail_entry_gets_reserved_cleanup_budget(self):
        with dot_source() as source:
            pixel_map = build_pixel_map(source, ((255, 255, 255), (0, 0, 0)), skip_white=True, gpu_mode='CPU')
            plan = build_pixel_stroke_plan(pixel_map, 2, options={'adaptive_hybrid_cost': 'Off'})
        others = [{'color_index': 0, 'path': ((n, 0),), 'phase': phase}
                  for phase in ('fill', 'mid_detail', 'fine_detail') for n in range(40)]
        selected = accuracy.progressive_time_budget(others + plan['execution_sequence'],
            active=True, seconds=5, profile_key='batch05-isolated-detail')['execution_sequence']
        self.assertIn(plan['execution_sequence'][0], selected)

    def test_border_details_are_protected_without_protecting_flat_fill(self):
        with Image.new('RGB', (17, 13), 'white') as source:
            source.putpixel((0, 0), (0, 0, 0))
            ImageDraw.Draw(source).rectangle((5, 4, 14, 11), fill='black')
            pixel_map = build_pixel_map(source, ((255, 255, 255), (0, 0, 0)), skip_white=True, gpu_mode='CPU')
        self.assertTrue(pixel_map.protected_mask[0, 0])
        self.assertFalse(pixel_map.protected_mask[7, 9])
        with Image.new('RGB', (1, 1), 'black') as singleton:
            self.assertTrue(build_pixel_map(singleton, ((0, 0, 0),), gpu_mode='CPU').protected_mask[0, 0])


if __name__ == '__main__':
    unittest.main()
