"""Failed profile loads preserve disk preferences and expose a real UI retry.

Persistence checks use actual temporary JSON files and the production reader,
validator, application transaction and writer. Native cases drive the real
profile selector and its after_idle callback; no test images are created.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_v148_ui_batch33_workspace as workspace_tests


class ProfileLoadPersistenceTests(unittest.TestCase):
    def setUp(self):
        import test_v148_application_batch04_settings as settings_tests
        fixture = settings_tests.LocalSettingsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.app, self.path = fixture.app, fixture.path
        self.controller = settings_tests.DrawBotApp
        self.original = json.dumps({
            'settings_schema': 2, 'quality': 'Maximum detail', 'speed': 'Fast',
            'brush_px': '7', 'profile_extras': {'ui_mode': 'Advanced'},
        }).encode('utf-8')
        self.path.write_bytes(self.original)
        logging = patch('DrawBot.log_event')
        logging.start()
        self.addCleanup(logging.stop)

    def read(self):
        return self.controller.read_settings(self.app)

    def save(self):
        return self.controller.save_settings(self.app)

    def assert_protected(self, expected):
        self.assertFalse(self.save())
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertEqual(self.app._settings_protected_path, self.path)
        message = self.app.status.set.call_args.args[0]
        self.assertIn('retry', message.lower())
        self.assertIn('unchanged', message.lower())

    def test_temporary_read_failure_cannot_publish_fallback_settings(self):
        with patch('RuntimePaths.read_json', side_effect=PermissionError('settings file is locked')):
            self.assertFalse(self.read())
        self.assertEqual(self.app.quality.get(), 'Balanced')
        self.assert_protected(self.original)

    def test_invalid_json_documents_are_preserved_through_later_saves(self):
        for document in (b'{"quality":', b'{"quality":"High detail","quality":"Maximum detail"}', b'[]'):
            with self.subTest(document=document):
                self.path.write_bytes(document)
                self.assertFalse(self.read())
                self.assertEqual(self.app.quality.get(), 'Balanced')
                self.assert_protected(document)

    def test_failed_setting_application_cannot_overwrite_the_valid_document(self):
        variable = self.app.speed
        original_set = variable.set
        for error in (RuntimeError('Tk variable application failed'),
                      FileNotFoundError('A setter dependency is missing')):
            with self.subTest(error=type(error).__name__):
                self.path.write_bytes(self.original)

                def fail_saved_value(value):
                    if value == 'Fast':
                        raise error
                    original_set(value)

                with patch.object(variable, 'set', side_effect=fail_saved_value):
                    self.assertFalse(self.read())
                self.assertEqual(self.app.quality.get(), 'Balanced')
                self.assertEqual(self.app.speed.get(), 'Safe')
                self.assertFalse(self.app.profile_change_in_progress)
                self.assert_protected(self.original)

    def test_successful_reread_releases_protection_after_applying_saved_values(self):
        with patch('RuntimePaths.read_json', side_effect=PermissionError('temporary lock')):
            self.assertFalse(self.read())
        self.assert_protected(self.original)
        self.assertTrue(self.read())
        self.assertIsNone(self.app._settings_protected_path)
        self.assertEqual(self.app.quality.get(), 'Maximum detail')
        self.assertEqual(self.app.brush_px.get(), '7')
        self.assertEqual(self.app.ui_mode.get(), 'Advanced')
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(self.save())
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['quality'], 'Maximum detail')

    def test_confirmed_missing_file_allows_defaults_after_an_explicit_removal(self):
        with patch('RuntimePaths.read_json', side_effect=PermissionError('temporary lock')):
            self.assertFalse(self.read())
        self.path.unlink()
        self.assertFalse(self.read())
        self.assertIsNone(self.app._settings_protected_path)
        self.assertTrue(self.save())
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['quality'], 'Balanced')

    def test_shutdown_preserves_failed_load_without_touching_status(self):
        self.app.closing = True
        with patch('RuntimePaths.read_json', side_effect=PermissionError('temporary lock')):
            self.assertFalse(self.read())
        self.assertFalse(self.save())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.app.status.set.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native Tk display required')
class NativeProfileLoadTests(unittest.TestCase):
    wait = workspace_tests.NativeStudioWorkspaceTests.wait
    workspace = workspace_tests.NativeStudioWorkspaceTests.workspace
    resize = workspace_tests.NativeStudioWorkspaceTests.resize
    select_profile = workspace_tests.NativeStudioWorkspaceTests.select_profile

    def isolated(self):
        name = f'{type(self).__module__}.{type(self).__name__}.{self._testMethodName}'
        if os.environ.get('IDB_UI_WORKSPACE_CASE') == name:
            return False
        # The parent owns runtime data until the child's crash-log descriptor is
        # closed. This is required for the same tests to clean up on Windows.
        with tempfile.TemporaryDirectory(prefix='idb-profile-load-') as temporary:
            data = Path(temporary).resolve()
            result = subprocess.run(
                [sys.executable, '-X', 'faulthandler', '-m', 'unittest', '-v', name],
                cwd=Path(__file__).resolve().parent,
                env=dict(os.environ, IDB_UI_WORKSPACE_CASE=name, IDB_UI_WORKSPACE_DATA_DIR=str(data)),
                text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=45,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            for diagnostic in ('invalid command name', 'Tcl_AsyncDelete', 'Exception ignored in'):
                self.assertNotIn(diagnostic, output)
            self.assertTrue((data / 'logs' / 'ImageDrawBot-crash.log').is_file())
        self.assertFalse(data.exists())
        return True

    def choose(self, root, app, name):
        app.profile_selector.set(name)
        app.profile_selector.event_generate('<<ComboboxSelected>>')
        self.wait(root, lambda: app.profile_change_after is None and not app.profile_change_in_progress,
                  'Profile selector callback did not finish')

    def test_locked_profile_preserves_bytes_and_selector_retry_loads_saved_values(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, backend, _data):
            import DrawBot
            import RuntimePaths
            target = DrawBot.profile_settings_file('gartic-phone')
            original = json.dumps({'settings_schema': 2, 'quality': 'Maximum detail',
                                   'brush_px': '7', 'profile_extras': {'ui_mode': 'Advanced'}}).encode('utf-8')
            target.write_bytes(original)
            read_json = RuntimePaths.read_json

            def locked(path, **kwargs):
                if Path(path) == target:
                    raise PermissionError('settings file is locked')
                return read_json(path, **kwargs)

            with patch.object(RuntimePaths, 'read_json', side_effect=locked):
                self.choose(root, app, 'Gartic Phone')
                self.assertEqual(app._active_profile_name, 'Gartic Phone')
                self.assertEqual(app.settings_path, target)
                self.assertIn('retry', app.status.get().lower())
                self.assertNotIn('Profile changed.', app.status.get())
                self.assertFalse(app.save_settings())
                self.assertEqual(target.read_bytes(), original)
                # Switching away must not first replace the unread document.
                self.choose(root, app, 'Skribbl.io')
                self.assertEqual(app.game.get(), 'Gartic Phone')
                self.assertEqual(app._active_profile_name, 'Gartic Phone')
                self.assertIn('retry', app.status.get().lower())
                self.assertEqual(target.read_bytes(), original)
            # Choosing the current entry again is a real explicit retry. It
            # must run after_idle without saving the fallback state first.
            self.choose(root, app, 'Gartic Phone')
            self.assertIsNone(app._settings_protected_path)
            self.assertEqual(app.quality.get(), 'Maximum detail')
            self.assertEqual(app.brush_px.get(), '7')
            self.assertEqual(app.ui_mode.get(), 'Advanced')
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(app.preview_mode.get(), 'Manual')
            self.assertIsNone(app.activity)
            self.assertIsNone(app.worker)
            self.assertEqual(backend.attempts, [])
            self.choose(root, app, 'Skribbl.io')
            self.assertEqual(app._active_profile_name, 'Skribbl.io')
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['quality'], 'Maximum detail')

    def test_explicit_reset_releases_invalid_profile_without_success_feedback_on_failed_load(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, _backend, _data):
            import DrawBot
            import ProfilePortability
            target = DrawBot.profile_settings_file('gartic-phone')
            original = b'{"quality":'
            target.write_bytes(original)
            self.choose(root, app, 'Gartic Phone')
            self.assertIn('retry', app.status.get().lower())
            self.assertNotIn('Profile changed.', app.status.get())
            self.assertFalse(app.save_settings())
            self.assertEqual(target.read_bytes(), original)
            # Reset is the existing explicit data-replacement action, and its
            # real same-profile reload must still accept the now-missing file.
            self.assertEqual(ProfilePortability.reset_profile(app), 'Gartic Phone')
            self.assertIsNone(app._settings_protected_path)
            self.assertTrue(app.save_settings())
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['settings_schema'], 2)
            self.assertIn('restored', app.status.get())


if __name__ == '__main__':
    unittest.main()
