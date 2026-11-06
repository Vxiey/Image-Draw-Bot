import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import AppTools
import ExactColorTools
import GameProfiles as GP
import ProfileIsolation as PI
import ProfilePortability as PP
from ProfileStorage import safe_profile_key


class ProfileIntegrityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for target, attr, value in ((PP, 'data_dir', lambda: self.root),
                                    (AppTools, 'data_dir', lambda: self.root),
                                    (ExactColorTools, 'data_dir', lambda: self.root)):
            mock = patch.object(target, attr, value)
            mock.start(); self.addCleanup(mock.stop)
        for registry in (GP.PROFILES, GP.PROFILE_UI):
            mock = patch.dict(registry)
            mock.start(); self.addCleanup(mock.stop)

    def package(self):
        palette = {'version': 4, 'profile': 'microsoft-paint', 'state': 'calibrated',
                   'colors': [{'name': 'Black', 'position': [10, 20], 'rgb': [0, 0, 0]}]}
        return PP.build_package('Microsoft Paint', {'quality': 'High detail'}, {'palette': palette})

    def app(self):
        return SimpleNamespace(activity=None, save_settings=Mock(), game=SimpleNamespace(get=lambda: 'Microsoft Paint'), status=Mock())

    def test_custom_names_reject_case_collisions_and_control_characters(self):
        path = self.root / 'profiles.json'
        GP.add_custom_profile('My brushes', path)
        previous = path.read_bytes()
        for name in ('my BRUSHES', 'microsoft paint', 'bad\nname', 'bad\x00name', 'hidden\u202ename', 'trailing\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                GP.add_custom_profile(name, path)
            self.assertEqual(path.read_bytes(), previous)
        GP.add_custom_profile('Mina färger 🎨', path)
        self.assertIn('Mina färger 🎨', GP.PROFILES)

    def test_registry_cannot_give_two_names_one_storage_owner(self):
        key = 'custom-' + 'a' * 32
        self.root.joinpath('profiles.json').write_text(json.dumps({'First': key, 'Second': key}), encoding='utf-8')
        GP.load_custom_profiles(self.root / 'profiles.json')
        self.assertEqual(GP.PROFILES['First'][0], key)
        self.assertNotIn('Second', GP.PROFILES)
        self.assertEqual(len({v[0] for v in GP.PROFILES.values()}), len(GP.PROFILES))

    def test_registry_ignores_invalid_bounded_utf8_and_nested_json(self):
        path = self.root / 'profiles.json'
        previous = dict(GP.PROFILES)
        for raw in (b'\xff', b'{' + b' ' * GP.MAX_CUSTOM_PROFILE_BYTES,
                    b'[' * 2000 + b'0' + b']' * 2000,
                    b'{"Same":"custom-' + b'a' * 32 + b'","Same":"custom-' + b'b' * 32 + b'"}'):
            path.write_bytes(raw)
            GP.load_custom_profiles(path)
            self.assertEqual(GP.PROFILES, previous)

    def test_registry_skips_case_and_control_names_without_changing_builtins(self):
        path = self.root / 'profiles.json'
        path.write_text(json.dumps({'microsoft paint': 'custom-' + 'c' * 32,
                                    'Bad\nName': 'custom-' + 'd' * 32,
                                    'Good': 'custom-' + 'e' * 32}), encoding='utf-8')
        GP.load_custom_profiles(path)
        self.assertNotIn('microsoft paint', GP.PROFILES)
        self.assertNotIn('Bad\nName', GP.PROFILES)
        self.assertEqual(GP.PROFILES['Microsoft Paint'][0], 'microsoft-paint')
        self.assertIn('Good', GP.PROFILES)

    def test_import_publish_failure_restores_updated_deleted_and_absent_files(self):
        paths = PP.portable_path_map('microsoft-paint', self.root)
        originals = {paths['settings']: b'old settings', paths['tools']: b'old tools', paths['exact_colors']: b'old exact'}
        for path, payload in originals.items():
            path.write_bytes(payload)
        real_replace = os.replace
        failed = False
        def fail_once(source, destination):
            nonlocal failed
            if Path(source) == paths['exact_colors'] and not failed:
                failed = True
                raise OSError('simulated delete failure')
            return real_replace(source, destination)
        with patch.object(PP.os, 'replace', side_effect=fail_once):
            with self.assertRaises(PP.ProfilePortabilityError):
                PP.apply_package_to_paths(self.package(), 'microsoft-paint', root=self.root)
        self.assertTrue(failed)
        for path, payload in originals.items():
            self.assertEqual(path.read_bytes(), payload)
        self.assertFalse(paths['palette'].exists())
        self.assertEqual(set(self.root.iterdir()), set(originals))

    def test_import_staging_failure_leaves_every_original_in_place(self):
        paths = PP.portable_path_map('microsoft-paint', self.root)
        originals = {path: f'old {logical}'.encode() for logical, path in paths.items()}
        for path, payload in originals.items():
            path.write_bytes(payload)
        real_write = PP.atomic_write_text
        calls = 0
        def fail_second(path, text):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('disk full during staging')
            real_write(path, text)
        with patch('RuntimePaths.atomic_write_text', side_effect=fail_second):
            with self.assertRaises(PP.ProfilePortabilityError):
                PP.apply_package_to_paths(self.package(), 'microsoft-paint', root=self.root)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertEqual(set(self.root.iterdir()), set(originals))

    def test_failed_rollback_keeps_original_backup_for_recovery(self):
        paths = PP.portable_path_map('microsoft-paint', self.root)
        paths['settings'].write_bytes(b'original settings')
        real_replace = os.replace
        def fail_publish_and_restore(source, destination):
            source, destination = Path(source), Path(destination)
            if destination == paths['settings'] and source.suffix in ('.import', '.backup'):
                raise OSError('destination remains locked')
            return real_replace(source, destination)
        with patch.object(PP.os, 'replace', side_effect=fail_publish_and_restore):
            with self.assertRaisesRegex(PP.ProfilePortabilityError, 'Retained recovery paths'):
                PP.apply_package_to_paths(self.package(), 'microsoft-paint', root=self.root)
        backups = list(self.root.glob('*.backup'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'original settings')
        self.assertEqual(list(self.root.glob('*.import')), [])

    def test_custom_copy_registration_and_profile_files_roll_back_together(self):
        registry = self.root / 'profiles.json'
        registry.write_text('{}', encoding='utf-8')
        real_replace = os.replace
        failed = False
        def fail_once(source, destination):
            nonlocal failed
            if Path(destination) == registry and Path(source).suffix == '.import' and not failed:
                failed = True
                raise OSError('registry cannot publish')
            return real_replace(source, destination)
        with patch.object(PP.os, 'replace', side_effect=fail_once), patch.object(PP, '_reload_profile') as reload_profile:
            with self.assertRaises(PP.ProfilePortabilityError):
                PP.import_package_into_app(self.app(), self.package(), action='copy', copy_name='My imported Paint')
            reload_profile.assert_not_called()
        self.assertTrue(failed)
        self.assertNotIn('My imported Paint', GP.PROFILES)
        self.assertNotIn('My imported Paint', GP.PROFILE_UI)
        self.assertEqual(registry.read_text(), '{}')
        self.assertEqual(list(self.root.iterdir()), [registry])

    def test_successful_custom_copy_publishes_matching_key_then_reloads(self):
        with patch.object(PP, '_reload_profile') as reload_profile:
            app = self.app()
            name = PP.import_package_into_app(app, self.package(), action='copy', copy_name='Portable brushes')
            reload_profile.assert_called_once_with(app, name)
        key = GP.PROFILES[name][0]
        registry = json.loads((self.root / 'profiles.json').read_text())
        self.assertEqual(registry[name], key)
        paths = PP.portable_path_map(key, self.root)
        self.assertEqual(json.loads(paths['settings'].read_text())['quality'], 'High detail')
        self.assertEqual(json.loads(paths['palette'].read_text())['profile'], key)

    def test_reset_failure_restores_files_and_never_reloads_defaults(self):
        paths = [self.root / 'settings.json', self.root / 'calibration.json', self.root / 'timing.json']
        for path in paths:
            path.write_bytes(path.name.encode())
        real_replace = os.replace
        failed = False
        def fail_once(source, destination):
            nonlocal failed
            if Path(source) == paths[1] and not failed:
                failed = True
                raise OSError('file is locked')
            return real_replace(source, destination)
        with patch.object(PP, 'profile_reset_paths', return_value=paths), \
             patch.object(PP.os, 'replace', side_effect=fail_once), patch.object(PP, '_reload_profile') as reload_profile:
            with self.assertRaises(PP.ProfilePortabilityError):
                PP.reset_profile(self.app())
            reload_profile.assert_not_called()
        for path in paths:
            self.assertEqual(path.read_bytes(), path.name.encode())
        self.assertEqual(set(self.root.iterdir()), set(paths))

    def test_tools_share_profile_storage_key_without_unsafe_name_collisions(self):
        for key in ('generic', 'microsoft-paint', 'custom-' + 'a' * 32, 'a/b', 'a-b', 'x' * 90, 'x' * 89 + 'y'):
            self.assertEqual(AppTools.tool_file(key).name, f'app-tools-{safe_profile_key(key)}.json')
            self.assertEqual(ExactColorTools.file_for(key).name, f'exact-colors-{safe_profile_key(key)}.json')
        self.assertNotEqual(AppTools.tool_file('a/b'), AppTools.tool_file('a-b'))
        self.assertNotEqual(ExactColorTools.file_for('a/b'), ExactColorTools.file_for('a-b'))
        self.assertNotEqual(AppTools.tool_file('x' * 90), AppTools.tool_file('x' * 89 + 'y'))

    def test_reset_cancels_previous_profile_setup_callback(self):
        pending = {'setup-1': Mock()}
        cancelled = []
        def cancel(token):
            cancelled.append(token)
            pending.pop(token)
        app = SimpleNamespace(root=SimpleNamespace(after_cancel=cancel), one_click_setup_after='setup-1', _profile_defaults={})
        PI.reset_settings(app)
        self.assertEqual(cancelled, ['setup-1'])
        self.assertEqual(pending, {})
        self.assertIsNone(app.one_click_setup_after)
        self.assertIsNone(app.one_click_setup_verify_payload)


if __name__ == '__main__':
    unittest.main()
