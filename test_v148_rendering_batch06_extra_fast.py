"""Unchanged Extra Fast geometry is priced once, including production callers."""
from contextlib import closing
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import ExtraFast2
from ContinuousPaths import SMART_PATH_MODE, build_execution_paths
from ExecutionCostModel import EXECUTION_MODEL_VERSION


class FinalPlanReuseTests(unittest.TestCase):
    def test_unchanged_plan_retains_pixels_and_portrait_barrier_under_real_cap(self):
        dots = [(x * 3, y * 3, x * 3, y * 3) for y in range(6) for x in range(8)]
        groups = [dots, []]
        options = {'stroke_optimizer': 'Travel only', 'drawing_mode': SMART_PATH_MODE,
                   'speed': 'Balanced', 'target_stroke_count_resolved': 12,
                   '_hybrid_cost_calibration_override': {}}
        with patch('ExtraFast2._downstream_plan_cost', wraps=ExtraFast2._downstream_plan_cost) as cost:
            result, meta = ExtraFast2.build_fast_paths(groups, options, portrait_edge_count=5)
        self.assertEqual(result, [[((x, y),) for x, y, _, _ in dots], []])
        self.assertEqual(result.phase_hints[0], ['portrait-outline'] * 5 + ['portrait-tone'] * 43)
        self.assertEqual(result.protected_prefix_counts, [5, 0])
        self.assertEqual(cost.call_count, 1)
        self.assertEqual(meta['adaptive_colors_improved'], 0)
        self.assertTrue(meta['downstream_target_cap_applied'])
        self.assertTrue(meta['downstream_semantic_hints_preserved'])
        self.assertEqual(meta['downstream_protected_prefix_after'], 5)
        self.assertEqual(meta['ordered_cost_before_seconds'], meta['ordered_cost_after_seconds'])
        self.assertEqual(meta['execution_cost_model'], f'ExecutionCostModel stateful v{EXECUTION_MODEL_VERSION}')
        self.assertEqual(groups, [dots, []])

    def test_changed_geometry_still_receives_complete_regression_guard(self):
        groups = [[(x, 2, x, 35) for x in range(2, 35)]]
        with patch('ExtraFast2._downstream_plan_cost', wraps=ExtraFast2._downstream_plan_cost) as cost:
            result, meta = ExtraFast2.build_fast_paths(groups, {'_hybrid_cost_calibration_override': {}})
        self.assertEqual(cost.call_count, 2)
        self.assertGreater(meta['adaptive_colors_improved'], 0)
        self.assertLessEqual(meta['ordered_cost_after_seconds'], meta['ordered_cost_before_seconds'])
        with closing(Image.new('1', (40, 40))) as raster:
            draw = ImageDraw.Draw(raster)
            for path in result[0]:
                draw.line(path, fill=1, width=1)
            actual = {(x, y) for y in range(40) for x in range(40) if raster.getpixel((x, y))}
        self.assertEqual(actual, {(x, y) for x in range(2, 35) for y in range(2, 36)})

    def test_stop_after_first_final_evaluation_still_interrupts_reused_plan(self):
        stop = [False]
        original = ExtraFast2._downstream_plan_cost
        def evaluate(*args, **kwargs):
            result = original(*args, **kwargs)
            stop[0] = True
            return result
        with patch('ExtraFast2._downstream_plan_cost', side_effect=evaluate) as cost:
            with self.assertRaises(InterruptedError):
                ExtraFast2.build_fast_paths([[(2, 2, 2, 2)]], {}, cancelled=lambda: stop[0])
        self.assertEqual(cost.call_count, 1)

    def test_actual_extra_fast_line_art_plan_reuses_unchanged_final_pricing(self):
        from DrawBot import make_plan
        options = {
            'render_preset': 'Extra fast', 'drawing_style': 'Line Art',
            'profile_name': 'Microsoft Paint', 'profile_key': 'microsoft-paint',
            'fill_tool_available': False, 'detail': 8, 'delay': .01, 'speed': 'Fast',
            'precision': 'High', 'lines': True, 'skip_white': True, 'contrast': 1.,
            'outline': False, 'paint_current_color': False, 'brush_px': 1,
            'time_budget_mode': 'Unlimited', 'unlimited_time': True, 'max_seconds': 80,
            'gpu_mode': 'CPU', 'planning_resolution': 'Standard',
            'custom_color_workflow': 'Calibrated palette', 'exact_color_available': False,
            'color_rendering': 'Perceptual match', 'color_fidelity': 'Faithful',
            'detail_zoom': 'Off', 'adaptive_detail': 'Off', 'preview_plan': True,
        }
        with closing(Image.new('RGB', (80, 60), 'white')) as image:
            ImageDraw.Draw(image).rectangle((10, 10, 65, 45), outline='black', width=1)
            with patch('ExtraFast2._downstream_plan_cost', wraps=ExtraFast2._downstream_plan_cost) as cost:
                plan = make_plan(image, (80, 60), options)
            try:
                self.assertEqual(cost.call_count, 1)
                meta = plan['options']['extra_fast_v2_meta']
                self.assertEqual(meta['adaptive_colors_improved'], 0)
                self.assertEqual(meta['ordered_cost_before_seconds'], meta['ordered_cost_after_seconds'])
                self.assertEqual(plan['count'], 4)
                self.assertTrue(plan['options']['outline'])
                self.assertEqual(plan['path_stats']['mode'], 'Extra Fast 2.0 connected regions')
            finally:
                for value in (*plan.values(), *plan['options'].values()):
                    if isinstance(value, Image.Image):
                        value.close()


if __name__ == '__main__':
    unittest.main()
