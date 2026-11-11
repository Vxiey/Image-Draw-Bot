"""Committed profile files and failed UI reloads must be reported separately.

Real native application, profile publisher, reader, settings and selector retry.
Only native-dialog answers and the failing file-read boundary are supplied.
No raster data is created or changed.
"""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_v148_ui_batch36_profile_load as profile_ui


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native Tk display required')
class NativeProfileReloadFeedbackTests(unittest.TestCase):
    isolated = profile_ui.NativeProfileLoadTests.isolated
    workspace = profile_ui.NativeProfileLoadTests.workspace
    wait = profile_ui.NativeProfileLoadTests.wait
    resize = profile_ui.NativeProfileLoadTests.resize
    select_profile = profile_ui.NativeProfileLoadTests.select_profile
    choose = profile_ui.NativeProfileLoadTests.choose

    @contextmanager
    def dialogs(self, *, path=None, replace=True, name=None):
        with ExitStack() as stack:
            if path is not None:
                stack.enter_context(patch('tkinter.filedialog.askopenfilename', return_value=str(path)))
            stack.enter_context(patch('tkinter.messagebox.askyesnocancel', return_value=replace))
            stack.enter_context(patch('tkinter.messagebox.askyesno', return_value=True))
            if name is not None:
                stack.enter_context(patch('tkinter.simpledialog.askstring', return_value=name))
            info = stack.enter_context(patch('tkinter.messagebox.showinfo'))
            warning = stack.enter_context(patch('tkinter.messagebox.showwarning'))
            error = stack.enter_context(patch('tkinter.messagebox.showerror'))
            yield info, warning, error

    @contextmanager
    def denied_reload(self, app):
        import RuntimePaths
        reader = RuntimePaths.read_json
        attempts = []

        def denied(path, **kwargs):
            if Path(path) == Path(app.settings_path):
                attempts.append(Path(path))
                raise PermissionError('profile reload read is temporarily denied')
            return reader(path, **kwargs)

        with patch.object(RuntimePaths, 'read_json', side_effect=denied):
            yield attempts
        self.assertTrue(attempts, 'The actual post-publication settings read must reach the denied file.')

    def import_source(self, data):
        import ProfilePortability as profiles
        package = profiles.build_package('Gartic Phone', {'quality': 'Maximum detail', 'brush_px': '7'})
        return profiles.write_profile_file(data / 'selected.drawprofile', package)

    def assert_warning(self, app, info, warning, error, completed_word):
        self.assertEqual(app._settings_protected_path, app.settings_path)
        self.assertEqual(app.status.get(), app._settings_load_error)
        self.assertIn('retry', app.status.get().lower())
        info.assert_not_called()
        error.assert_not_called()
        warning.assert_called_once()
        title, text = warning.call_args.args[:2]
        self.assertIn(completed_word, (title + ' ' + text).lower())
        self.assertIn(app._settings_load_error, text)

    def test_replace_import_reports_saved_files_and_preserves_reload_error_until_selector_retry(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, backend, data):
            import DrawBot
            import ProfilePortability as profiles
            self.select_profile(root, app, 'Gartic Phone')
            source = self.import_source(data)
            target = DrawBot.profile_settings_file('gartic-phone')
            with self.dialogs(path=source) as (info, warning, error), self.denied_reload(app):
                result = profiles.import_profile_dialog(app)
                self.assertEqual(result, 'Gartic Phone')
                saved = target.read_bytes()
                self.assertEqual(json.loads(saved)['quality'], 'Maximum detail')
                self.assertNotEqual(app.quality.get(), 'Maximum detail')
                self.assert_warning(app, info, warning, error, 'imported')
                self.assertFalse(app.save_settings())
                self.assertEqual(target.read_bytes(), saved)
            self.choose(root, app, result)
            self.assertIsNone(app._settings_protected_path)
            self.assertEqual(app.quality.get(), 'Maximum detail')
            self.assertEqual(app.brush_px.get(), '7')
            self.assertEqual(target.read_bytes(), saved)
            self.assertEqual(app.preview_mode.get(), 'Manual')
            self.assertEqual(backend.attempts, [])

    def test_copy_import_keeps_one_committed_profile_when_reload_requires_retry(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, _backend, data):
            import GameProfiles
            import ProfilePortability as profiles
            source = self.import_source(data)
            name = 'Imported brush setup'
            with self.dialogs(path=source, replace=False, name=name) as (info, warning, error), self.denied_reload(app):
                self.assertEqual(profiles.import_profile_dialog(app), name)
                registry = (data / 'profiles.json').read_bytes()
                key = GameProfiles.PROFILES[name][0]
                self.assertEqual(json.loads(registry)[name], key)
                saved = app.settings_path.read_bytes()
                self.assertEqual(json.loads(saved)['brush_px'], '7')
                self.assert_warning(app, info, warning, error, 'imported')
            self.choose(root, app, name)
            self.assertIsNone(app._settings_protected_path)
            self.assertEqual(app.quality.get(), 'Maximum detail')
            self.assertEqual((data / 'profiles.json').read_bytes(), registry)
            self.assertEqual(GameProfiles.PROFILES[name][0], key)
            self.assertEqual(app.settings_path.read_bytes(), saved)

    def test_reset_reports_completed_deletion_and_failed_reload_without_false_success(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, _backend, _data):
            import ProfilePortability as profiles
            self.select_profile(root, app, 'Gartic Phone')
            app.quality.set('Maximum detail')
            self.assertTrue(app.save_settings())
            target = app.settings_path
            self.assertTrue(target.is_file())
            with self.dialogs() as (info, warning, error), self.denied_reload(app):
                result = profiles.reset_profile_dialog(app)
                self.assertEqual(result, 'Gartic Phone')
                self.assertFalse(target.exists())
                self.assert_warning(app, info, warning, error, 'reset')
                self.assertFalse(app.save_settings())
                self.assertFalse(target.exists())
            self.choose(root, app, result)
            self.assertIsNone(app._settings_protected_path)
            self.assertEqual(app.quality.get(), 'Balanced')
            self.assertTrue(app.save_settings())
            self.assertEqual(json.loads(target.read_text())['quality'], 'Balanced')

    def test_rename_and_remove_retain_committed_identity_and_failed_reload_feedback(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, _backend, data):
            import DrawBot
            import GameProfiles
            import ProfilePortability as profiles
            name, renamed = 'Review brush setup', 'Renamed brush setup'
            GameProfiles.add_custom_profile(name, data / 'profiles.json')
            app.profile_selector.configure(values=list(GameProfiles.PROFILES))
            self.select_profile(root, app, name)
            app.quality.set('Maximum detail')
            self.assertTrue(app.save_settings())
            custom_path = app.settings_path
            key = GameProfiles.PROFILES[name][0]
            with self.dialogs(name=renamed) as (info, warning, error), self.denied_reload(app):
                result = profiles.rename_custom_profile_dialog(app)
                self.assertEqual(result, renamed)
                self.assertNotIn(name, GameProfiles.PROFILES)
                self.assertEqual(GameProfiles.PROFILES[renamed][0], key)
                self.assertEqual(json.loads((data / 'profiles.json').read_text())[renamed], key)
                self.assertEqual(json.loads(custom_path.read_text())['quality'], 'Maximum detail')
                with self.subTest(operation='rename'):
                    self.assert_warning(app, info, warning, error, 'renamed')
            self.choose(root, app, renamed)
            self.assertIsNone(app._settings_protected_path)
            self.assertEqual(app.quality.get(), 'Maximum detail')
            generic = DrawBot.profile_settings_file('generic')
            invalid = b'{"quality":'
            generic.write_bytes(invalid)
            with self.dialogs() as (info, warning, error):
                self.assertEqual(profiles.remove_custom_profile_dialog(app), renamed)
                self.assertNotIn(renamed, GameProfiles.PROFILES)
                self.assertNotIn(renamed, json.loads((data / 'profiles.json').read_text()))
                self.assertFalse(custom_path.exists())
                self.assertEqual(app.game.get(), 'Other drawing app')
                self.assertEqual(generic.read_bytes(), invalid)
                with self.subTest(operation='remove'):
                    self.assert_warning(app, info, warning, error, 'removed')

    def test_successful_actions_keep_normal_feedback_and_ignore_another_protected_path(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, backend, data):
            import GameProfiles
            import ProfilePortability as profiles
            source = self.import_source(data)
            app._settings_protected_path = data / 'settings-unrelated.json'
            app._settings_load_error = 'Unrelated profile warning'
            with self.dialogs(path=source) as (info, warning, error):
                self.assertEqual(profiles.import_profile_dialog(app), 'Gartic Phone')
                self.assertEqual(app.quality.get(), 'Maximum detail')
                info.assert_called_once()
                self.assertIn('Imported Gartic Phone.', app.status.get())
                warning.assert_not_called(); error.assert_not_called()
            with self.dialogs() as (info, warning, error):
                self.assertEqual(profiles.reset_profile_dialog(app), 'Gartic Phone')
                self.assertEqual(app.quality.get(), 'Balanced')
                info.assert_called_once()
                self.assertIn('restored', app.status.get())
                warning.assert_not_called(); error.assert_not_called()
            name, renamed = 'Working brush setup', 'Working renamed setup'
            GameProfiles.add_custom_profile(name, data / 'profiles.json')
            app.profile_selector.configure(values=list(GameProfiles.PROFILES))
            self.select_profile(root, app, name)
            with self.dialogs(name=renamed) as (info, warning, error):
                self.assertEqual(profiles.rename_custom_profile_dialog(app), renamed)
                self.assertIn('renamed', app.status.get())
                info.assert_not_called(); warning.assert_not_called(); error.assert_not_called()
            with self.dialogs() as (info, warning, error):
                self.assertEqual(profiles.remove_custom_profile_dialog(app), renamed)
                self.assertIn('Removed custom profile', app.status.get())
                info.assert_not_called(); warning.assert_not_called(); error.assert_not_called()
            self.assertEqual(backend.attempts, [])


if __name__ == '__main__':
    unittest.main()
