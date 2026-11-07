"""Timed admission keeps the selected physical strokes' original paint order."""
from collections import Counter
from contextlib import ExitStack, closing
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from AdaptiveBrushEngine import assign_adaptive_brushes
import PixelAccuracyEngine as accuracy
from PixelStrokeEngine import build_pixel_stroke_plan
from test_pixel_accuracy_engine_v1088 import pm_from_index
from test_v148_accuracy_batch12_context import public_options
from test_v148_rendering_batch06_canvas import close_plan


PALETTE = ((255, 255, 255), (0, 0, 0), (255, 0, 0))
ASSET = Path(__file__).parent / 'golden-regression/small-detail-preservation.png'


def detail_pairs():
    labels = np.full((32, 32), -1, np.int16)
    for y in range(3, 30, 6):
        for x in range(3, 30, 6):
            labels[y, x] = 1
            labels[y, x + 1] = 2
    return pm_from_index(labels, protected=labels == 1,
        edges=np.zeros(labels.shape, np.float32), importance=np.where(labels == 1, 1., .1))


def square_stamp_dots(sequence, size, brush):
    """Literal native square oracle for the component fixture's single-point paths."""
    width, height = size
    ink = np.full((height, width), -1, np.int16)
    for row in sequence:
        assert len(row['path']) == 1
        x, y = row['path'][0]
        brush = row.get('brush_px', brush)
        for py in range(y - (brush - 1) // 2, y + brush // 2 + 1):
            for px in range(x - (brush - 1) // 2, x + brush // 2 + 1):
                if 0 <= px < width and 0 <= py < height:
                    ink[py, px] = row['color_index']
    return ink


class ProgressivePaintOrderTests(unittest.TestCase):
    def test_real_component_plan_keeps_protected_cleanup_above_selected_fine_detail(self):
        pixel_map = detail_pairs()
        plan = build_pixel_stroke_plan(pixel_map, len(PALETTE))
        sequence = assign_adaptive_brushes(plan['execution_sequence'],
            default_brush_px=3)['execution_sequence']
        before = copy.deepcopy(sequence)
        with patch('RealSpeedBudget.load_profile', return_value=None):
            result = accuracy.progressive_time_budget(sequence, active=True,
                seconds=10, correction_reserve_ratio=0)
        selected = result['execution_sequence']
        self.assertEqual(sequence, before)
        self.assertEqual(result['path_budget'], 30)
        # Admission still reserves the same important work; only playback order
        # must follow the original component planner's overpainting contract.
        self.assertEqual(Counter(row['phase'] for row in selected),
            {'cleanup': 25, 'fine_detail': 5})
        self.assertEqual({row['brush_px'] for row in selected}, {3})
        actual = square_stamp_dots(selected, (32, 32), 3)
        self.assertTrue(np.all(actual[pixel_map.protected_mask] == 1))
        simulation = accuracy.simulate_strokes(pixel_map, selected, PALETTE,
            brush_px=3, gpu_mode='CPU')
        np.testing.assert_array_equal(simulation.simulated_index[actual >= 0], actual[actual >= 0])
        self.assertEqual(simulation.metrics['protected_accuracy_percent'], 100.)

    def test_interleaved_occurrences_remain_a_subsequence_without_changing_admission(self):
        phases = ['fine_detail', 'cleanup', 'fill', 'mid_detail'] * 20
        source = [dict(color_index=1, path=((3, 3),), brush_px=3,
                       phase=phase, occurrence=index) for index, phase in enumerate(phases)]
        with patch('RealSpeedBudget.load_profile', return_value=None):
            result = accuracy.progressive_time_budget(source, active=True, seconds=10,
                correction_reserve_ratio=0)
        rows = result['execution_sequence']
        self.assertEqual(Counter(row['phase'] for row in rows),
            {'fill': 11, 'mid_detail': 10, 'cleanup': 5, 'fine_detail': 4})
        occurrences = [row['occurrence'] for row in rows]
        self.assertEqual(occurrences, sorted(occurrences))
        self.assertEqual(len(occurrences), len(set(occurrences)))
        for row in rows:
            self.assertEqual(row, source[row['occurrence']])
            self.assertIsNot(row, source[row['occurrence']])
        for active, seconds in ((False, 10), (True, 3600)):
            with patch('RealSpeedBudget.load_profile', return_value=None):
                untouched = accuracy.progressive_time_budget(source, active=active, seconds=seconds)
            self.assertEqual(untouched['execution_sequence'], source)

    def test_existing_asset_public_timed_plan_retains_the_admitted_component_order(self):
        from DrawBot import make_plan
        real_budget = accuracy.progressive_time_budget
        observed = []
        def budget(sequence, **kwargs):
            result = real_budget(sequence, **kwargs)
            observed.append((copy.deepcopy(sequence), copy.deepcopy(result)))
            return result
        with ExitStack() as stack:
            asset = stack.enter_context(closing(Image.open(ASSET)))
            source = stack.enter_context(closing(asset.crop((155, 102, 174, 121))))
            source_bytes = source.tobytes()
            stack.enter_context(patch('RealSpeedBudget.load_profile', return_value=None))
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            stack.enter_context(patch.object(accuracy, 'progressive_time_budget', new=budget))
            settings = public_options(3)
            settings.update(time_budget_mode='30 sec', unlimited_time=False)
            plan = make_plan(source, (100, 100), settings)
            stack.callback(close_plan, plan, source)
            original, result = observed[0]
            self.assertTrue(result['active'])
            self.assertGreater(result['paths_omitted'], 0)
            selected = result['execution_sequence']
            order = {row['serial']: index for index, row in enumerate(original)}
            positions = [order[row['serial']] for row in selected]
            self.assertEqual(positions, sorted(positions))
            self.assertEqual(Counter(row['phase'] for row in selected),
                {'fill': 24, 'mid_detail': 17, 'cleanup': 40, 'fine_detail': 11})
            self.assertEqual(plan['execution_sequence'][:len(selected)], selected)
            self.assertEqual({row['brush_px'] for row in plan['execution_sequence']}, {3})
            self.assertEqual(source.tobytes(), source_bytes)


if __name__ == '__main__':
    unittest.main()
