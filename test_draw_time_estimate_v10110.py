import unittest

from DrawTimeEstimate import estimate_from_plan, format_duration, status_line
from Version import APP_VERSION, FILE_VERSION


class DrawTimeEstimateV10110Tests(unittest.TestCase):
    def test_duration_formatting(self):
        self.assertEqual(format_duration(45), '45s')
        self.assertEqual(format_duration(125), '2m 05s')
        self.assertEqual(format_duration(3600), '1h')
        self.assertEqual(format_duration(3665), '1h 01m')

    def test_full_detail_uses_plan_estimate(self):
        plan = {
            'estimate': 125.0,
            'count': 1200,
            'plan_area': (800, 600),
            'preview_area': (800, 600),
            'target_area': (800, 600),
            'options': {},
            'path_stats': {},
        }
        meta = estimate_from_plan(plan)
        self.assertFalse(meta['is_projection'])
        self.assertEqual(meta['projected_label'], '2m 40s')
        self.assertIn('Estimated draw time', status_line({'draw_time_estimate': meta}))

    def test_downscaled_preview_projects_final_time(self):
        plan = {
            'estimate': 120.0,
            'count': 3000,
            'preview_area': (500, 250),
            'target_area': (1000, 500),
            'options': {'_preview_safe_pipeline': True, 'draw_quality': 'High likeness'},
            'path_stats': {'mode': 'Shape paths', 'shape_model': 'Better shapes v2'},
            'groups': [[], [], []],
        }
        meta = estimate_from_plan(plan)
        self.assertTrue(meta['is_projection'])
        self.assertGreater(meta['projected_seconds'], plan['estimate'])
        self.assertIn(meta['confidence'], {'cold-start', 'rough', 'medium'})
        self.assertIn('Estimated final draw time', status_line({'draw_time_estimate': meta}))

    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')


if __name__ == '__main__':
    unittest.main()
