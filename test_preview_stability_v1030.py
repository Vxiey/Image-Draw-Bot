import unittest
from DrawBot import preview_safe_options, PREVIEW_PLAN_TIMEOUT_SECONDS, PREVIEW_FALLBACK_TIMEOUT_SECONDS
from Version import APP_VERSION, FILE_VERSION


class PreviewStabilityV1030Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_extreme_preview_is_bounded_and_cancellable(self):
        options = {
            'planning_resolution':'Extreme', 'cpu_workers':'8', 'cpu_workers_resolved':8,
            'cpu_engine':'Auto', 'gpu_mode':'Auto', 'gpu_performance':'High throughput',
            'color_rendering':'Perceptual match', 'color_layers':'Off',
            'target_stroke_count_resolved':5000, 'drawing_mode':'Shape paths',
        }
        safe = preview_safe_options(options, 'Manual')
        self.assertEqual(safe['planning_resolution'], 'High')
        self.assertEqual(safe['cpu_workers'], '4')
        self.assertEqual(safe['cpu_workers_resolved'], 4)
        self.assertEqual(safe['cpu_engine'], 'Threads')
        self.assertEqual(safe['gpu_mode'], 'CPU')
        self.assertLessEqual(safe['target_stroke_count_resolved'], 1600)
        self.assertTrue(safe['_preview_safe_pipeline'])
        self.assertEqual(safe['_preview_requested_planning_resolution'], 'Extreme')

    def test_layered_preview_uses_perceptual_base_only(self):
        safe = preview_safe_options({
            'planning_resolution':'Ultra', 'color_rendering':'Layered color mix',
            'color_layers':'Full color mix', 'cpu_workers_resolved':8,
        }, 'Manual')
        self.assertEqual(safe['color_rendering'], 'Perceptual match')
        self.assertEqual(safe['color_layers'], 'Off')
        self.assertEqual(safe['_preview_requested_color_layers'], 'Full color mix')

    def test_fallback_is_emergency_lightweight(self):
        fallback = preview_safe_options({
            'planning_resolution':'Extreme', 'color_rendering':'Perceptual match',
            'color_layers':'Full color mix', 'drawing_mode':'Shape paths',
            'target_stroke_count_resolved':9000, 'background_fill':'Conservative',
        }, 'Manual', fallback=True)
        self.assertEqual(fallback['planning_resolution'], 'Standard')
        self.assertEqual(fallback['color_rendering'], 'RGB nearest')
        self.assertEqual(fallback['color_layers'], 'Off')
        self.assertEqual(fallback['background_fill'], 'Off')
        self.assertEqual(fallback['target_stroke_count_resolved'], 800)
        self.assertEqual(fallback['max_stroke_cap'], '1000')

    def test_preview_timeouts_are_short(self):
        self.assertLessEqual(PREVIEW_PLAN_TIMEOUT_SECONDS, 15)
        self.assertLessEqual(PREVIEW_FALLBACK_TIMEOUT_SECONDS, 8)


if __name__ == '__main__':
    unittest.main()
