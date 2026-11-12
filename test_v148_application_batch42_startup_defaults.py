"""First launch and profile reload begin with the same declared defaults."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import DrawBot
import GameProfiles
import ProfileIsolation
from test_v148_application_batch04_settings import Value


class NativeValue(Value):
    """Only Tk storage is substituted; constructor/settings/options are real."""
    def __init__(self, value='', **_kwargs):
        super().__init__(value)


class StartupProfileDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.directory))
        self.stack.enter_context(patch.object(DrawBot, 'DATA_DIR', self.directory))
        self.stack.enter_context(patch.object(DrawBot, 'log_event'))
        self.stack.enter_context(patch.dict(GameProfiles.PROFILES))
        self.stack.enter_context(patch.dict(GameProfiles.PROFILE_UI))
        for name in ('StringVar', 'BooleanVar', 'DoubleVar', 'IntVar'):
            self.stack.enter_context(patch.object(DrawBot.tk, name, NativeValue))
        self.stack.enter_context(patch.object(DrawBot.ttk, 'Style'))
        self.stack.enter_context(patch.object(DrawBot, 'previous_run_unclean', return_value=False))
        self.stack.enter_context(patch('ReleaseState.should_show_welcome', return_value=False))
        self.stack.enter_context(patch.object(DrawBot, 'load_resource_recommendation', return_value=None))
        # These callbacks normally operate on native widgets / deferred UI
        # services. They do not participate in settings construction or options.
        for name in ('refresh_runtime_safety_ui', 'refresh_auto_tuner_ui',
                     'refresh_beginner_setup_wizard', 'refresh_palette',
                     'refresh_tool_calibration', 'refresh_app_tool_calibration', 'set_busy'):
            self.stack.enter_context(patch.object(DrawBot.DrawBotApp, name))
        self.build_values = []

        def build(app, *_args):
            self.build_values.append({name: getattr(app, name).get()
                for name in GameProfiles.profile_defaults(app.game.get())})

        self.stack.enter_context(patch('StudioUI.build_ui', new=build))
        self.settings = DrawBot.profile_settings_file('generic')

    def app(self):
        root = SimpleNamespace(title=Mock(), configure=Mock(), bind=Mock(),
            protocol=Mock(), after=Mock(return_value='deferred-native-job'))
        app = DrawBot.DrawBotApp(root, mouse_backend=Mock(), keyboard_backend=Mock())
        self.addCleanup(vars(app).clear)
        self.assertEqual(app.game.get(), 'Other drawing app')
        self.assertEqual(app.settings_path, self.settings)
        self.assertFalse(app.profile_change_in_progress)
        self.assertIsNone(app.worker)
        return app

    def test_missing_file_starts_with_the_profile_defaults_before_ui_and_options(self):
        self.assertFalse(self.settings.exists())
        app = self.app()
        defaults = GameProfiles.profile_defaults('Other drawing app')
        self.assertEqual(self.build_values[-1], defaults)
        current = app.options()
        self.assertEqual(current['background_fill'], defaults['background_fill'])
        self.assertEqual(current['custom_color_workflow'], defaults['custom_color_workflow'])
        self.assertEqual(current['profile_key'], 'generic')
        self.assertEqual(app._profile_defaults['background_fill'], 'Balanced')
        self.assertEqual(app._profile_defaults['custom_color_workflow'], 'Calibrated palette')
        ProfileIsolation.reset_settings(app)
        DrawBot.apply_profile_defaults(app, app.game.get())
        reloaded = app.options()
        self.assertEqual(reloaded['background_fill'], current['background_fill'])
        self.assertEqual(reloaded['custom_color_workflow'], current['custom_color_workflow'])
        self.assertFalse(self.settings.exists())

    def test_valid_persisted_values_override_shared_defaults_before_widgets_see_them(self):
        saved = {'profile_engine': 'Manual settings',
                 'background_fill': 'Off', 'custom_color_workflow': 'Calibrated palette',
                 'speed': 'Safe', 'contrast': 1.25}
        self.settings.write_text(json.dumps(saved), encoding='utf-8')
        before = self.settings.read_bytes()
        app = self.app()
        self.assertEqual(app.background_fill.get(), saved['background_fill'])
        self.assertEqual(app.custom_color_workflow.get(), saved['custom_color_workflow'])
        self.assertEqual(app.contrast.get(), saved['contrast'])
        self.assertEqual(self.build_values[-1]['background_fill'], 'Off')
        self.assertEqual(self.build_values[-1]['custom_color_workflow'], 'Calibrated palette')
        current = app.options()
        self.assertEqual(current['profile_engine'], saved['profile_engine'])
        self.assertEqual(current['background_fill'], 'Off')
        self.assertEqual(current['custom_color_workflow'], 'Calibrated palette')
        self.assertEqual(current['speed'], 'Safe')
        self.assertEqual(self.settings.read_bytes(), before)

    def test_partial_invalid_and_future_files_keep_safe_defaults_without_overwriting_data(self):
        cases = ({'speed': 'Fast', 'background_fill': [], 'contrast': True},
                 {'settings_schema': 999, 'background_fill': 'Off'}, 'broken-json')
        defaults = GameProfiles.profile_defaults('Other drawing app')
        for saved in cases:
            with self.subTest(saved=saved):
                text = saved if isinstance(saved, str) else json.dumps(saved)
                self.settings.write_text(text, encoding='utf-8')
                before = self.settings.read_bytes()
                app = self.app()
                current = app.options()
                self.assertEqual(current['background_fill'], defaults['background_fill'])
                self.assertEqual(current['custom_color_workflow'], defaults['custom_color_workflow'])
                self.assertEqual(current['contrast'], 1.)
                self.assertEqual(self.settings.read_bytes(), before)
                if isinstance(saved, dict) and saved.get('settings_schema') == 999:
                    self.assertFalse(app.save_settings())
                    self.assertEqual(self.settings.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
