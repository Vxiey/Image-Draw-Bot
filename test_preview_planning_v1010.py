
import unittest
from pathlib import Path
from PIL import Image

from DrawBot import preview_area_for, make_plan, PREVIEW_MAX_PIXELS, PREVIEW_PLAN_TIMEOUT_SECONDS
from PreviewLayers import build_auxiliary_previews
from Version import APP_VERSION, FILE_VERSION


class PreviewPlanningV1010Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_preview_area_downscales_large_canvas(self):
        area = preview_area_for((4000, 2200))
        self.assertLessEqual(area[0] * area[1], PREVIEW_MAX_PIXELS + 2500)
        self.assertLessEqual(max(area), 760)
        self.assertAlmostEqual(area[0] / area[1], 4000 / 2200, delta=0.02)

    def test_preview_area_keeps_small_canvas(self):
        self.assertEqual(preview_area_for((640, 360)), (640, 360))

    def test_preview_options_are_preserved_in_plan(self):
        image = Image.new('RGBA', (160, 100), (30, 30, 30, 255))
        options = {
            'detail': 6, 'delay': .01, 'speed': 'Balanced', 'precision': 'High', 'lines': True,
            'render_style': 'Standard / pixel', 'draw_quality': 'Balanced', 'human_mode': 'Off',
            'gpu_mode': 'CPU', 'gpu_vram': 'Auto', 'gpu_performance': 'Balanced',
            'background_fill': 'Off', 'background_simplification': 'Off', 'color_grouping': 'Accurate',
            'color_rendering': 'RGB nearest', 'color_layers': 'Off', 'custom_color_workflow': 'Calibrated palette',
            'tool_strategy': 'Auto', 'portrait_focus': True, 'skip_white': False, 'contrast': 1.0,
            'outline': False, 'brush_px': 1, 'max_seconds': 60, 'paint_current_color': False,
            'erase_mode': False, 'paint_tool': 'Pencil', 'effective_paint_tool': 'Pencil',
            'tool_actions': [], 'fill_tool_available': False, 'fill_tool_actions': [], 'fill_restore_actions': [],
            '_preview_plan': True, '_target_area': (1600, 1000), '_preview_area': (640, 400),
        }
        plan = make_plan(image, (160, 100), options)
        self.assertTrue(plan['options']['_preview_plan'])
        self.assertIn('ui_previews', plan)

    def test_auxiliary_preview_cancellation_propagates(self):
        image = Image.new('RGB', (40, 30), 'white')
        groups = [[(0, 0, 39, 0) for _ in range(50)]]
        calls = {'n': 0}
        def cancelled():
            calls['n'] += 1
            return calls['n'] > 3
        with self.assertRaises(InterruptedError):
            build_auxiliary_previews(image, (80, 60), groups, ((0, 0, 0),), lambda x, y: (x, y), 1, {'_preview_plan': True}, cancelled)

    def test_drawbot_contains_preview_timeout_handler(self):
        source = (Path(__file__).resolve().parent / 'DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('PREVIEW_PLAN_TIMEOUT_SECONDS', source)
        self.assertIn("elif kind=='preview_timeout':", source)
        self.assertIn('Planning optimized preview', source)


if __name__ == '__main__':
    unittest.main()
