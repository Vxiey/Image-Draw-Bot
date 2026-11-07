"""The resolved profile color bound reaches the real adaptive Auto planner."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import DrawBot
from DynamicColors import resolve_exact_color_limit
import test_v148_ui_batch07_renderer as renderer_fixtures


class ProfileColorCeilingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
        self.stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.image = Image.new('RGB', (24, 16))
        self.image.putdata([((x * 7 + y * 3) % 256, (y * 11 + x) % 256,
                             (x * 5 + y * 7) % 256) for y in range(16) for x in range(24)])
        self.addCleanup(self.image.close)

    def app(self, profile, *, policy='Auto', count='Auto'):
        app = renderer_fixtures.AdvertisedRendererTests().app(profile)
        app.profile_engine.set(policy)
        app.render_style.set('Standard / pixel')
        app.custom_color_workflow.set('Adaptive exact (recommended)')
        app.drawing_style = renderer_fixtures.Value('Photo / Shaded')
        app.exact_color_limit = renderer_fixtures.Value(count)
        return app

    def planned(self, app):
        options = DrawBot.DrawBotApp.options(app)
        with patch('DrawBot.recommend_adaptive_color_count',
                   wraps=DrawBot.recommend_adaptive_color_count) as recommendation:
            plan = DrawBot.make_plan(self.image, self.image.size, options)
        self.addCleanup(renderer_fixtures.close_images, plan)
        return options, plan, recommendation

    def test_each_resolved_profile_bound_reaches_actual_auto_color_analysis(self):
        for profile, expected in (('Microsoft Paint', 32), ('Skribbl.io', 18)):
            with self.subTest(profile=profile):
                app = self.app(profile)
                options, plan, recommendation = self.planned(app)
                self.assertEqual(recommendation.call_count, 1)
                self.assertEqual(recommendation.call_args.kwargs['ceiling'], expected)
                self.assertEqual(options['exact_color_limit_profile_ceiling'], expected)
                metadata = plan['options']['adaptive_color_count_meta']
                self.assertEqual(metadata['ceiling_colors'], expected)
                self.assertLessEqual(metadata['recommended_colors'], expected)
                self.assertEqual(app.profile_engine.get(), 'Auto')
                self.assertEqual(app.exact_color_limit.get(), 'Auto')

    def test_manual_policy_keeps_the_generic_quality_bound_without_a_profile_override(self):
        options, plan, recommendation = self.planned(self.app('Microsoft Paint', policy='Manual settings'))
        self.assertNotIn('exact_color_limit_profile_ceiling', options)
        expected = resolve_exact_color_limit('Auto', draw_quality=plan['options']['draw_quality'])
        self.assertEqual(recommendation.call_args.kwargs['ceiling'], expected)
        self.assertEqual(plan['options']['adaptive_color_count_meta']['ceiling_colors'], expected)

    def test_explicit_manual_count_bypasses_auto_analysis_and_retains_its_limit(self):
        app = self.app('Skribbl.io', policy='Manual settings', count='8')
        options, plan, recommendation = self.planned(app)
        self.assertNotIn('exact_color_limit_profile_ceiling', options)
        recommendation.assert_not_called()
        self.assertEqual(options['exact_color_limit'], '8')
        self.assertEqual(plan['options']['exact_color_limit_resolved'], 8)
        self.assertEqual(plan['options']['adaptive_color_count_meta']['policy'], 'manual')
        self.assertEqual(app.exact_color_limit.get(), '8')


if __name__ == '__main__':
    unittest.main()
