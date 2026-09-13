import unittest
from PIL import Image

from PreviewSafety import build_preview_safety_plan, render_preview_safety_map
from Version import APP_VERSION, FILE_VERSION


BASE_OPTIONS = {
    'delay': 0,
    'max_seconds': 30,
    'precision': 'Normal',
    'speed': 'Fast',
    'brush_px': 3,
    'drawing_mode': 'Lines (fastest)',
    'edge_behavior': 'Hard Clip',
    'outline': False,
}


class SmartPreviewSafetyV1055Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_hard_clip_preview_skips_edge_band_stroke(self):
        image_size = (10, 10)
        fitted = (20, 20)
        groups = [[(0, 0, 9, 0)]]
        plan = build_preview_safety_plan(image_size, fitted, groups, None, dict(BASE_OPTIONS))
        self.assertEqual(plan.mode, 'Hard Clip')
        self.assertEqual(plan.groups, [[]])
        self.assertEqual(plan.meta['hard_skip'], 1)
        self.assertEqual(plan.meta['skipped_total'], 1)

    def test_adaptive_preview_follows_safe_edge(self):
        image_size = (10, 10)
        fitted = (20, 20)
        groups = [[(0, 0, 9, 0)]]
        options = dict(BASE_OPTIONS, edge_behavior='Adaptive Clip', drawing_mode='Smart paths (recommended)')
        plan = build_preview_safety_plan(image_size, fitted, groups, None, options)
        self.assertEqual(plan.mode, 'Adaptive Clip')
        self.assertEqual(plan.meta['adaptive_boundary'], 1)
        self.assertEqual(plan.meta['adapted_total'], 1)
        self.assertTrue(plan.groups[0])

    def test_safety_map_is_rendered(self):
        image = Image.new('RGB', (10, 10), 'white')
        plan = build_preview_safety_plan(image.size, (20, 20), [[(2, 2, 7, 7)]], None, dict(BASE_OPTIONS))
        safety = render_preview_safety_map(image, (40, 40), plan, ((0, 0, 0),), 2)
        self.assertEqual(safety.size, (40, 40))


if __name__ == '__main__':
    unittest.main()
