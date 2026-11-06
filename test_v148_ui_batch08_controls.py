"""The effective renderer consumes the choices displayed in active controls."""
from contextlib import ExitStack, closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import AppTools
import DrawBot
import RegionFillEngine
from CalibrationAnchors import make_anchor
from test_precision_v102 import Value
import test_v148_application_batch04_settings as settings_fixtures
import test_v148_ui_batch07_renderer as renderer_fixtures


class RegionFillControlTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=root))
        self.stack.enter_context(patch('AppTools.data_dir', return_value=root))
        self.stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
        self.stack.enter_context(patch('DrawBot.log_event'))
        AppTools.save_calibration('generic', {'Brush': (140, 10), 'Fill': (140, 30)},
                                  anchor=make_anchor((0, 0, 200, 200)))

    def app(self, enabled, aggression, background='Balanced'):
        app = renderer_fixtures.AdvertisedRendererTests().app('Other drawing app')
        app.render_style.set('Standard / pixel')
        app.background_fill.set(background)
        app.use_region_fill_engine.set(enabled)
        app.fill_aggressiveness = Value(aggression)
        app.adaptive_detail = Value('Off')
        app.background_simplification = Value('Off')
        return app

    def plan(self, options):
        with closing(Image.new('RGB', (120, 90), 'white')) as source:
            ImageDraw.Draw(source).rectangle((20, 15, 95, 72), fill='black')
            return DrawBot.make_plan(source, source.size, options)

    def test_disabled_switch_and_each_aggression_reach_the_real_planner(self):
        for enabled, aggression in ((False, 'Safe'), (True, 'Safe'),
                                    (True, 'Balanced'), (True, 'Aggressive')):
            with self.subTest(enabled=enabled, aggression=aggression):
                options = DrawBot.DrawBotApp.options(self.app(enabled, aggression))
                self.assertIs(options['use_region_fill_engine'], enabled)
                self.assertEqual(options['fill_aggressiveness'], aggression)
                self.assertTrue(options['fill_tool_available'])
                with patch.object(RegionFillEngine, 'build_region_fill_plan',
                                  wraps=RegionFillEngine.build_region_fill_plan) as region:
                    plan = self.plan(options)
                try:
                    if enabled:
                        region.assert_called_once()
                        self.assertEqual(plan['options']['region_fill_meta']['fill_aggressiveness'], aggression)
                    else:
                        region.assert_not_called()
                        self.assertNotIn('region_fill_meta', plan['options'])
                finally:
                    renderer_fixtures.close_images(plan)

    def test_region_switch_remains_independent_of_legacy_auto_fill(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                options = DrawBot.DrawBotApp.options(self.app(enabled, 'Safe', background='Off'))
                with patch.object(RegionFillEngine, 'build_region_fill_plan',
                                  wraps=RegionFillEngine.build_region_fill_plan) as region:
                    plan = self.plan(options)
                try:
                    self.assertEqual(region.call_count, int(enabled))
                    self.assertFalse((plan['options'].get('background_fill_plan') or {}).get('enabled'))
                finally:
                    renderer_fixtures.close_images(plan)

    def test_region_choices_round_trip_without_reverting_to_default_policy(self):
        fixture = settings_fixtures.LocalSettingsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for enabled, aggression in ((False, 'Safe'), (True, 'Aggressive')):
            with self.subTest(enabled=enabled, aggression=aggression):
                fixture.app.use_region_fill_engine.set(enabled)
                fixture.app.fill_aggressiveness.set(aggression)
                self.assertTrue(DrawBot.DrawBotApp.save_settings(fixture.app))
                fixture.app.use_region_fill_engine.set(not enabled)
                fixture.app.fill_aggressiveness.set('Balanced')
                self.assertTrue(DrawBot.DrawBotApp.read_settings(fixture.app))
                self.assertIs(fixture.app.use_region_fill_engine.get(), enabled)
                self.assertEqual(fixture.app.fill_aggressiveness.get(), aggression)


if __name__ == '__main__':
    unittest.main()
