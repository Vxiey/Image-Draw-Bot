"""Portrait style policy remains usable with the supported single-color path."""
from contextlib import closing
import unittest

from PIL import Image

from AutoDrawing import resolve_drawing
from DrawingStyleProfiles import apply_drawing_style


class PortraitCompatibilityTests(unittest.TestCase):
    def test_single_color_style_does_not_inject_a_full_color_subject_mode(self):
        options = {'drawing_style': 'Portrait', 'paint_current_color': True,
                   'subject_focus': 'Off', 'calibration_marker': object()}
        with closing(Image.new('RGB', (10, 10), (90, 90, 90))) as image:
            result = apply_drawing_style(image, options)
        self.assertEqual(result['subject_focus'], 'Off')
        self.assertEqual(result['render_style'], 'Portrait / shaded')
        self.assertIs(result['calibration_marker'], options['calibration_marker'])
        self.assertEqual(options['subject_focus'], 'Off')
        self.assertNotIn('render_style', options)

    def test_full_color_portrait_keeps_its_subject_policy(self):
        with closing(Image.new('RGB', (10, 10), (90, 90, 90))) as image:
            result = apply_drawing_style(image, {'drawing_style': 'Portrait', 'paint_current_color': False})
        self.assertEqual(result['subject_focus'], 'Subject first')

    def test_actual_manual_and_auto_portraits_use_existing_shaded_renderer(self):
        from DrawBot import make_plan
        for preset in ('Manual', 'Auto'):
            with self.subTest(preset=preset), closing(Image.new('RGB', (24, 20))) as image:
                image.putdata([(value, value, value) for value in
                               [40 + (x * 7 + y * 3) % 150 for y in range(20) for x in range(24)]])
                options = {
                    'render_preset': preset, 'drawing_style': 'Portrait',
                    'paint_current_color': True, 'subject_focus': 'Off',
                    'profile_name': 'Microsoft Paint', 'profile_key': 'microsoft-paint',
                    'detail': 10, 'delay': .01, 'lines': True, 'contrast': 1., 'skip_white': True,
                    'outline': False, 'gpu_mode': 'CPU', 'preview_plan': True,
                    'time_budget_mode': 'Unlimited', 'unlimited_time': True, 'max_seconds': 180,
                }
                plan = make_plan(image, (48, 40), options)
                try:
                    self.assertGreater(plan['count'], 0)
                    self.assertTrue(plan['options']['portrait_stats'])
                    self.assertEqual(plan['options']['subject_focus'], 'Off')
                    self.assertEqual(len(plan['groups']), 1)
                    self.assertTrue(plan['options']['paint_current_color'])
                    self.assertFalse(plan['options'].get('outline'))
                finally:
                    for value in (*plan.values(), *plan['options'].values()):
                        if isinstance(value, Image.Image):
                            value.close()

    def test_explicit_invalid_subject_mode_is_still_rejected_by_real_planner(self):
        from DrawBot import make_plan
        with closing(Image.new('RGB', (10, 10), (90, 90, 90))) as image:
            with self.assertRaisesRegex(ValueError, 'Subject focus needs full colour drawing'):
                make_plan(image, (20, 20), {
                    'render_preset': 'Manual', 'drawing_style': 'Portrait',
                    'paint_current_color': True, 'subject_focus': 'Subject first',
                    'detail': 10, 'delay': .01, 'lines': True, 'contrast': 1.,
                })

    def test_extra_fast_single_color_keeps_its_established_contour_policy(self):
        with closing(Image.new('RGB', (10, 10), (90, 90, 90))) as image:
            result = resolve_drawing(image, {
                'render_preset': 'Extra fast', 'drawing_style': 'Portrait',
                'paint_current_color': True, 'subject_focus': 'Off',
            })
        self.assertTrue(result['outline'])
        self.assertEqual(result['subject_focus'], 'Off')


if __name__ == '__main__':
    unittest.main()
