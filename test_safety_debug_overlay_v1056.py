import unittest

from PreviewSafety import build_preview_safety_plan
from SafetyDebugOverlay import render_safety_debug_overlay
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


class SafetyDebugOverlayV1056Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_debug_marks_hard_clipped_stroke(self):
        plan = build_preview_safety_plan((10, 10), (20, 20), [[(0, 5, 9, 5)]], None, dict(BASE_OPTIONS))
        self.assertEqual(plan.meta['safety_debug']['clipped'], 1)
        event = plan.meta['debug_events'][0]
        self.assertEqual(event['action'], 'clipped')
        self.assertIn('clipped', event['reason'].lower())
        self.assertTrue(event['output_subpaths'])

    def test_debug_marks_hard_skipped_edge_band(self):
        plan = build_preview_safety_plan((10, 10), (20, 20), [[(0, 0, 9, 0)]], None, dict(BASE_OPTIONS))
        self.assertEqual(plan.meta['safety_debug']['skipped'], 1)
        event = plan.meta['debug_events'][0]
        self.assertEqual(event['action'], 'skipped')
        self.assertEqual(event['strategy'], 'hard_skip')
        self.assertIn('unsafe edge band', event['reason'])

    def test_debug_marks_adaptive_edge_follow(self):
        options = dict(BASE_OPTIONS, edge_behavior='Adaptive Clip', drawing_mode='Smart paths (recommended)')
        plan = build_preview_safety_plan((10, 10), (20, 20), [[(0, 0, 9, 0)]], None, options)
        self.assertEqual(plan.meta['safety_debug']['edge_follow'], 1)
        event = plan.meta['debug_events'][0]
        self.assertEqual(event['action'], 'edge-follow')
        self.assertIn('Adaptive Clip', event['reason'])

    def test_debug_overlay_is_rendered(self):
        plan = build_preview_safety_plan((10, 10), (20, 20), [[(0, 5, 9, 5), (0, 0, 9, 0)]], None, dict(BASE_OPTIONS))
        image = render_safety_debug_overlay((80, 60), plan, ((0, 0, 0),), 2)
        self.assertEqual(image.size, (80, 60))


if __name__ == '__main__':
    unittest.main()
