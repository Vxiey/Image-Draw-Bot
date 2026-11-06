"""Profile creation preserves disk registrations after incomplete startup reads."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import DrawBot
import GameProfiles as profiles
import ProfilePortability as portability
from test_v148_application_batch04_settings import Value


class RegistryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path = self.root / 'profiles.json'
        self.stack.enter_context(patch.dict(profiles.PROFILES))
        self.stack.enter_context(patch.dict(profiles.PROFILE_UI))
        self.stack.enter_context(patch.object(portability, 'data_dir', return_value=self.root))
        self.stack.enter_context(patch.object(DrawBot, 'DATA_DIR', self.root))
        self.existing = {'Existing valid profile': 'custom-' + 'a' * 32}
        self.path.write_text(json.dumps(self.existing), encoding='utf8')
        self.app = SimpleNamespace(activity=None, closing=False, root=Mock(),
            game=Value('Microsoft Paint'), profile_selector=Mock(), change_profile=Mock(),
            save_settings=Mock(return_value=True), status=Mock())

    def package(self):
        return portability.build_package('Microsoft Paint', {'quality': 'High detail'})

    def fail_startup_read(self):
        original = Path.open
        def unavailable(path, *args, **kwargs):
            if path == self.path:
                raise PermissionError('temporary registry read lock')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', unavailable):
            profiles.load_custom_profiles(self.path)
        self.assertNotIn('Existing valid profile', profiles.PROFILES)

    def test_actual_add_dialog_preserves_and_recovers_profiles_after_failed_startup_read(self):
        self.fail_startup_read()
        with patch('tkinter.simpledialog.askstring', return_value='New valid profile'), \
                patch('DrawBot.messagebox.showerror') as error:
            DrawBot.DrawBotApp.add_profile(self.app)
        error.assert_not_called()
        data = json.loads(self.path.read_text(encoding='utf8'))
        self.assertEqual(data['Existing valid profile'], self.existing['Existing valid profile'])
        self.assertEqual(data['New valid profile'], profiles.PROFILES['New valid profile'][0])
        self.assertEqual(profiles.PROFILES['Existing valid profile'][0], data['Existing valid profile'])
        self.app.profile_selector.configure.assert_called_once_with(values=list(profiles.PROFILES))
        self.assertEqual(self.app.game.get(), 'New valid profile')
        self.app.change_profile.assert_called_once()

    def test_actual_import_copy_preserves_disk_profiles_and_publishes_matching_settings(self):
        self.fail_startup_read()
        with patch.object(portability, '_reload_profile') as reload_profile:
            name = portability.import_package_into_app(self.app, self.package(),
                action='copy', copy_name='Imported valid profile')
        data = json.loads(self.path.read_text(encoding='utf8'))
        self.assertEqual(data['Existing valid profile'], self.existing['Existing valid profile'])
        self.assertEqual(profiles.PROFILES['Existing valid profile'][0], data['Existing valid profile'])
        settings = portability.portable_path_map(data[name], self.root)['settings']
        self.assertEqual(json.loads(settings.read_text())['quality'], 'High detail')
        reload_profile.assert_called_once_with(self.app, name)

    def test_each_add_reads_new_disk_entries_and_rejects_their_casefold_name(self):
        profiles.load_custom_profiles(self.path)
        data = dict(self.existing, **{'Added while open': 'custom-' + 'b' * 32})
        self.path.write_text(json.dumps(data), encoding='utf8')
        previous = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unique'):
            profiles.add_custom_profile('ADDED WHILE OPEN', self.path)
        self.assertEqual(self.path.read_bytes(), previous)
        profiles.add_custom_profile('Third profile', self.path)
        written = json.loads(self.path.read_text(encoding='utf8'))
        self.assertEqual({name: written[name] for name in data}, data)
        self.assertEqual(profiles.PROFILES['Added while open'][0], data['Added while open'])

    def test_unreadable_registry_blocks_add_and_import_without_state_or_file_changes(self):
        previous = self.path.read_bytes()
        original = Path.open
        def unavailable(path, *args, **kwargs):
            if path == self.path:
                raise PermissionError('temporary registry read lock')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', unavailable), \
                patch('tkinter.simpledialog.askstring', return_value='Blocked new profile'), \
                patch('DrawBot.messagebox.showerror') as error, \
                patch.object(portability, '_reload_profile') as reload_profile:
            DrawBot.DrawBotApp.add_profile(self.app)
            error.assert_called_once()
            with self.assertRaisesRegex(portability.ProfilePortabilityError, 'temporary registry'):
                portability.import_package_into_app(self.app, self.package(),
                    action='copy', copy_name='Blocked imported profile')
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.root.iterdir()), [self.path])
        self.assertNotIn('Blocked new profile', profiles.PROFILES)
        self.assertNotIn('Blocked imported profile', profiles.PROFILES)
        self.app.change_profile.assert_not_called()
        reload_profile.assert_not_called()

    def test_invalid_or_conflicting_registry_is_preserved_instead_of_silently_cleaned(self):
        raws = (
            b'not JSON', b'[]', b'\xff', b' ' * (profiles.MAX_CUSTOM_PROFILE_BYTES + 1),
            b'{"same":"custom-' + b'a' * 32 + b'","same":"custom-' + b'b' * 32 + b'"}',
            json.dumps({'Bad key': 'future-key-format'}).encode(),
            json.dumps({'Same': 'custom-' + 'a' * 32, 'same': 'custom-' + 'b' * 32}).encode(),
            json.dumps({'First': 'custom-' + 'a' * 32, 'Second': 'custom-' + 'a' * 32}).encode(),
            json.dumps({'Same': 'custom-' + 'a' * 32, ' Same ': 'custom-' + 'a' * 32}).encode(),
            json.dumps({'Bad\nname': 'custom-' + 'a' * 32}).encode(),
            json.dumps({'Microsoft Paint': 'custom-' + 'a' * 32}).encode(),
        )
        for raw in raws:
            with self.subTest(raw=raw[:80]):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    profiles.add_custom_profile('Unpublished', self.path)
                self.assertEqual(self.path.read_bytes(), raw)
                self.assertNotIn('Unpublished', profiles.PROFILES)

    def test_missing_registry_keeps_known_profiles_and_failed_publish_does_not_register(self):
        profiles.load_custom_profiles(self.path)
        self.path.unlink()
        profiles.add_custom_profile('Second profile', self.path)
        self.assertEqual(json.loads(self.path.read_text())['Existing valid profile'],
                         self.existing['Existing valid profile'])
        previous = self.path.read_bytes()
        with patch('RuntimePaths.atomic_write_text', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                profiles.add_custom_profile('Unpublished', self.path)
        self.assertNotIn('Unpublished', profiles.PROFILES)
        self.assertEqual(self.path.read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
