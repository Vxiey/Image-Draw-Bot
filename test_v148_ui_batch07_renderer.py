"""Advertised renderer choices reach their real Paint planner and persistence."""
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot
from SketchFillRenderer import SKETCH_FILL_RENDER_STYLE
from test_precision_v102 import Value
import test_v148_application_batch04_settings as settings_fixtures


def close_images(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, Image.Image):
        value.close()
    elif isinstance(value, dict):
        for item in value.values():
            close_images(item, seen)
    elif isinstance(value, (tuple, list)):
        for item in value:
            close_images(item, seen)


class AdvertisedRendererTests(unittest.TestCase):
    def app(self, profile='Microsoft Paint'):
        values = dict(brush_px='2', max_seconds='180', quality='Balanced', speed='Normal',
            precision='High', mode='Smart paths (recommended)', render_style=SKETCH_FILL_RENDER_STYLE,
            game=profile, paint_tool='Use current tool', contrast=1.0, portrait_focus=False,
            skip_white=True, outline=False, paint_simple=False, profile_engine='Manual settings',
            render_preset='Manual', gpu_mode='CPU', cpu_workers='1', cpu_engine='Threads',
            resource_scheduler='Off', background_fill='Off', use_region_fill_engine=False,
            custom_color_workflow='Calibrated palette', detail_zoom='Off',
            planning_resolution='Standard', draw_quality='Balanced', color_layers='Off')
        return SimpleNamespace(**{name: Value(value) for name, value in values.items()})

    def test_paint_ui_options_reach_the_real_sketch_fill_phase_planner(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch('RuntimePaths.source_dir', return_value=Path(directory)))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
            app = self.app()
            options = DrawBot.DrawBotApp.options(app)
            self.assertEqual(options['render_style'], SKETCH_FILL_RENDER_STYLE)
            source = Image.new('RGB', (40, 32), 'white')
            drawing = ImageDraw.Draw(source)
            drawing.rectangle((7, 6, 32, 25), fill=(220, 30, 30), outline='black', width=2)
            plan = None
            try:
                with patch('DrawBot.build_sketch_fill_plan', wraps=DrawBot.build_sketch_fill_plan) as dispatch:
                    plan = DrawBot.make_plan(source, (40, 32), options)
                dispatch.assert_called_once()
                self.assertTrue(plan['options']['sketch_fill_active'])
                self.assertEqual(plan['options']['render_style'], SKETCH_FILL_RENDER_STYLE)
                phases = [entry['phase'] for entry in plan['execution_sequence']]
                ranks = {'sketch': 0, 'color_fill': 1, 'reoutline': 2}
                self.assertEqual([ranks[name] for name in phases], sorted(ranks[name] for name in phases))
                self.assertEqual(set(phases), set(ranks))
                self.assertFalse(plan['options']['fill_regions'])
                self.assertEqual(source.getpixel((20, 16)), (220, 30, 30))
            finally:
                close_images(plan)
                source.close()

    def test_selected_style_round_trips_through_actual_save_and_read(self):
        fixture = settings_fixtures.LocalSettingsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.app.render_style.set(SKETCH_FILL_RENDER_STYLE)
        self.assertTrue(DrawBot.DrawBotApp.save_settings(fixture.app))
        fixture.app.render_style.set('Auto')
        self.assertTrue(DrawBot.DrawBotApp.read_settings(fixture.app))
        self.assertEqual(fixture.app.render_style.get(), SKETCH_FILL_RENDER_STYLE)

    def test_browser_restriction_and_unknown_style_validation_remain_explicit(self):
        app = self.app('Gartic Phone')
        with tempfile.TemporaryDirectory() as directory, \
                patch('RuntimePaths.source_dir', return_value=Path(directory)), \
                patch('DrawBot.custom_rgb_available', return_value=False):
            options = DrawBot.DrawBotApp.options(app)
        with closing(Image.new('RGB', (8, 8), 'white')) as source:
            with self.assertRaisesRegex(ValueError, 'optimized for Microsoft Paint'):
                DrawBot.make_plan(source, (8, 8), options)
        app.render_style.set('Unknown renderer')
        with self.assertRaisesRegex(ValueError, 'valid rendering style'):
            DrawBot.DrawBotApp.options(app)


if __name__ == '__main__':
    unittest.main()
