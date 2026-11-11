"""Reset retires the generic profile's real legacy palette sources atomically.

The public reset/reload, settings reader, palette consumer and file-set publisher
run unchanged. Only unrelated window/render feedback and native dialogs are
replaced; no raster fixtures or image generation are involved.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import Colors
import DrawBot
import GameProfiles
import PixelData
import ProfileIsolation
import ProfilePortability as portability
import ProfileStorage
import RealSpeedBudget
import RuntimePaths
from SettingsValidation import ADDITIONAL_VARIABLES
from test_v148_application_batch04_settings import Value


class LegacyPaletteResetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(RuntimePaths, 'source_dir', return_value=self.root))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.current = self.root / 'calibration.json'
        self.positions = self.root / 'positions.txt'
        self.palette = self.root / 'palette.json'
        self.stack.enter_context(patch.object(Colors, 'CALIBRATION_FILE', self.current))
        self.stack.enter_context(patch.object(Colors, 'PALETTE_FILE', self.palette))
        self.stack.enter_context(patch.object(Colors.load_positions, '__defaults__', (self.positions,)))
        self.stack.enter_context(patch.object(RealSpeedBudget, 'SPEED_FILE', self.root / 'real-speed-profiles.json'))
        builtins = {name: value for name, value in GameProfiles.PROFILES.items()
                    if not value[0].startswith('custom-')}
        self.stack.enter_context(patch.dict(GameProfiles.PROFILES, builtins, clear=True))
        self.stack.enter_context(patch.dict(GameProfiles.PROFILE_UI))
        GameProfiles.add_custom_profile('Legacy reset custom', self.root / 'profiles.json')
        saved_colors = [(color, dict(vars(color))) for color in Colors.allColors]

        def restore_colors():
            for color, attributes in saved_colors:
                vars(color).clear()
                vars(color).update(attributes)
            Colors.allColors[:] = [color for color, _attributes in saved_colors]
            PixelData.closest_color.cache_clear()

        self.addCleanup(restore_colors)
        Colors.reset_palette()
        self.legacy_positions = [(101 + 3 * index, 207) for index in range(len(Colors.allColors))]
        self.legacy_rgbs = [list(color.RGB) for color in Colors.allColors]
        self.legacy_rgbs[0] = [31, 47, 63]
        self.seed_legacy()
        shared = {
            'draw-time-calibration.json': {'version': 1, 'profiles': {'legacy': {'samples': 4}}},
            'real-speed-profiles.json': {'version': 1, 'profiles': {'skribbl': {'samples': 9}}},
        }
        for name, document in shared.items():
            (self.root / name).write_text(json.dumps(document), encoding='utf-8')
        self.other = ProfileStorage.profile_palette_file('skribbl')
        Colors.save_calibration([(40, 50)], [(70, 80, 90)], self.other, profile_key='skribbl')
        self.shared_paths = (self.root / 'profiles.json', self.root / 'draw-time-calibration.json',
                             self.root / 'real-speed-profiles.json', self.other)
        self.shared_bytes = {path: path.read_bytes() for path in self.shared_paths}

    def seed_legacy(self):
        self.positions.write_text(''.join(f'{x}\n{y}\n' for x, y in self.legacy_positions), encoding='utf-8')
        self.palette.write_text(json.dumps(self.legacy_rgbs), encoding='utf-8')

    def app(self, name='Other drawing app'):
        app = SimpleNamespace(**{field: Value('') for field in
            (*ProfileIsolation.SETTING_NAMES, *ADDITIONAL_VARIABLES)})
        values = {'game': name, 'paint_simple': False, 'paint_tool': 'Use current tool',
                  'manual_drop_in_start': False, 'preview_mode': 'Manual', 'auto_clear_canvas': False,
                  'summary': '', 'status': '', 'palette_text': '', 'profile_hint': '', 'area_text': ''}
        for field, value in values.items():
            setattr(app, field, Value(value))
        app.root = SimpleNamespace(title=Mock())
        app.profile_selector = Mock()
        app.paint_check = Mock()
        app.activity = None
        app.closing = False
        app.profile_change_after = None
        app.profile_change_ticket = None
        app.profile_change_in_progress = False
        app.pending_clear_drawing = None
        app._active_profile_name = name
        app.color_session_cache = {}
        app.plan = object()
        app.stop = threading.Event()
        app.stop.set()
        key = GameProfiles.PROFILES[name][0]
        app.settings_path = ProfileStorage.profile_settings_file(key)
        app.calibration_path = ProfileStorage.profile_palette_file(key)
        for method in ('read_settings', 'refresh_palette', '_apply_profile_change'):
            setattr(app, method, MethodType(getattr(DrawBot.DrawBotApp, method), app))
        # These separate view/tool/preview surfaces are not part of palette
        # reset. The real _reload_profile and _apply_profile_change still run.
        for method in ('refresh_tool_calibration', 'refresh_app_tool_calibration',
                       'refresh_exact_color_status', 'set_busy', '_mark_plan_stale',
                       'show_previews', '_schedule_recovery_checkpoint'):
            setattr(app, method, Mock())
        return app

    def seed_current(self, app):
        key = GameProfiles.PROFILES[app.game.get()][0]
        Colors.save_calibration([(7, 8)], [(21, 22, 23)], app.calibration_path, profile_key=key)
        app.settings_path.write_text('{"settings_schema":2,"quality":"High detail"}', encoding='utf-8')

    def disk_state(self):
        return {path.relative_to(self.root): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def assert_shared_unchanged(self):
        self.assertEqual({path: path.read_bytes() for path in self.shared_paths}, self.shared_bytes)

    def test_generic_reset_retires_legacy_palette_before_real_reload_and_stays_reset(self):
        for canonical_exists in (False, True):
            with self.subTest(canonical_exists=canonical_exists):
                self.seed_legacy()
                app = self.app()
                if canonical_exists:
                    self.seed_current(app)
                app.refresh_palette()
                self.assertTrue(app.palette_ready)
                expected_position = (7, 8) if canonical_exists else self.legacy_positions[0]
                self.assertEqual((Colors.allColors[0].x, Colors.allColors[0].y), expected_position)
                self.assertEqual(portability.reset_profile(app), 'Other drawing app')
                self.assert_shared_unchanged()
                self.assertFalse(app.palette_ready)
                self.assertFalse(any(path.exists() for path in (self.current, self.positions, self.palette)))
                self.assertIn('unavailable', app.palette_text.get().lower())
                self.assertIsNone(app.plan)
                self.assertIsNone(app.target_window)
                self.assertTrue(app.stop.is_set())
                self.assertEqual(app.preview_mode.get(), 'Manual')
                app.root.title.assert_called_once_with('Image Draw Bot · Other drawing app')
                self.assertEqual(portability.reset_profile(app), 'Other drawing app')
                app.refresh_palette()
                self.assertFalse(app.palette_ready)
                self.assert_shared_unchanged()
                # Reset must still permit later explicit calibration.
                Colors.save_calibration([(90, 80)], [(12, 34, 56)], self.current, profile_key='generic')
                app.refresh_palette()
                self.assertTrue(app.palette_ready)
                self.assertEqual(Colors.allColors[0].RGB, (12, 34, 56))
                self.current.unlink()

    def test_legacy_palette_stays_usable_until_an_explicit_reset(self):
        app = self.app()
        before = self.disk_state()
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        self.assertEqual([(color.x, color.y) for color in Colors.allColors], self.legacy_positions)
        self.assertEqual([list(color.RGB) for color in Colors.allColors], self.legacy_rgbs)
        self.assertEqual(self.disk_state(), before)
        self.assertFalse(self.current.exists())

    def test_other_builtin_and_custom_resets_preserve_generic_legacy_and_shared_files(self):
        legacy = {path: path.read_bytes() for path in (self.positions, self.palette)}
        for name in ('Microsoft Paint', 'Gartic Phone', 'Legacy reset custom'):
            with self.subTest(profile=name):
                app = self.app(name)
                self.seed_current(app)
                self.assertEqual(portability.reset_profile(app), name)
                self.assertFalse(app.calibration_path.exists())
                self.assertFalse(app.settings_path.exists())
                self.assertEqual({path: path.read_bytes() for path in legacy}, legacy)
                self.assert_shared_unchanged()
                self.assertEqual(app._active_profile_name, name)
                self.assertTrue(app.stop.is_set())
        generic = self.app()
        generic.refresh_palette()
        self.assertTrue(generic.palette_ready)
        self.assertEqual([list(color.RGB) for color in Colors.allColors], self.legacy_rgbs)

    def test_legacy_backup_failure_rolls_back_every_reset_file_without_reloading(self):
        real_replace = RuntimePaths.os.replace
        for blocked in (self.positions, self.palette):
            with self.subTest(source=blocked.name):
                app = self.app()
                self.seed_current(app)
                app.refresh_palette()
                # The real transaction deliberately retains its stable lock
                # sidecar. Establish it before comparing the complete file set.
                with RuntimePaths.file_transaction(portability.profile_timing_file('generic')):
                    pass
                before = self.disk_state()
                old_plan = app.plan
                failed = False

                def fail_backup(source, destination):
                    nonlocal failed
                    if Path(source) == blocked and Path(destination).suffix == '.backup' and not failed:
                        failed = True
                        raise PermissionError('legacy calibration is locked')
                    return real_replace(source, destination)

                with patch.object(RuntimePaths.os, 'replace', side_effect=fail_backup):
                    with self.assertRaisesRegex(portability.ProfilePortabilityError, 'previous files were restored'):
                        portability.reset_profile(app)
                self.assertTrue(failed)
                self.assertEqual(self.disk_state(), before)
                self.assertIs(app.plan, old_plan)
                self.assertTrue(app.palette_ready)
                self.assertEqual((Colors.allColors[0].x, Colors.allColors[0].y), (7, 8))
                app.root.title.assert_not_called()
                app.show_previews.assert_not_called()
                self.assert_shared_unchanged()

    def test_cancelled_or_stale_reset_confirmation_preserves_all_sources(self):
        app = self.app()
        self.seed_current(app)
        before = self.disk_state()
        with patch('tkinter.messagebox.askyesno', return_value=False), \
                patch('tkinter.messagebox.showinfo') as info, \
                patch('tkinter.messagebox.showerror') as error:
            self.assertIsNone(portability.reset_profile_dialog(app))
        info.assert_not_called()
        error.assert_not_called()
        self.assertEqual(self.disk_state(), before)

        def change_selection(*_args, **_kwargs):
            app.game.set('Gartic Phone')
            return True

        with patch('tkinter.messagebox.askyesno', side_effect=change_selection), \
                patch('tkinter.messagebox.showinfo') as info, \
                patch('tkinter.messagebox.showerror') as error:
            self.assertIsNone(portability.reset_profile_dialog(app))
        info.assert_not_called()
        error.assert_called_once()
        self.assertEqual(self.disk_state(), before)
        app.root.title.assert_not_called()


if __name__ == '__main__':
    unittest.main()
