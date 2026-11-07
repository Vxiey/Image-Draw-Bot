"""Existing casefold/import-identity contracts through the real modal flow."""
from contextlib import ExitStack
import json
import unittest
from unittest.mock import patch

import GameProfiles as profiles
import ProfilePortability as portability
import test_v148_ui_batch08_profile_management as management_fixtures


class ProfileImportIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = management_fixtures.CustomProfileManagementTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.app
        self.root = self.fixture.root
        self.key = self.fixture.key
        self.original = portability.profile_settings_file(self.key)
        self.other = portability.profile_settings_file(self.fixture.other_key)
        self.original.write_text('{"quality": "Balanced"}', encoding='utf-8')
        self.other.write_text('{"quality": "Maximum"}', encoding='utf-8')
        self.package = portability.build_package('My brushes', {'quality': 'High detail'})
        self.package['profile'].update(name='MY BRUSHES', key='custom-' + 'e' * 32)
        self.path = self.root / 'case-variant.drawprofile'
        portability.write_profile_file(self.path, self.package)

    def dialog(self, answer=True, copy_name='Imported copy'):
        with ExitStack() as context:
            context.enter_context(patch('tkinter.filedialog.askopenfilename', return_value=str(self.path)))
            choice = context.enter_context(patch('tkinter.messagebox.askyesnocancel',
                **({'side_effect': answer} if callable(answer) else {'return_value': answer})))
            copy = context.enter_context(patch('tkinter.simpledialog.askstring',
                **({'side_effect': copy_name} if callable(copy_name) else {'return_value': copy_name})))
            error = context.enter_context(patch('tkinter.messagebox.showerror'))
            info = context.enter_context(patch('tkinter.messagebox.showinfo'))
            result = portability.import_profile_dialog(self.app)
        return result, choice, copy, error, info

    def test_case_variant_replace_names_canonical_target_and_keeps_its_uuid(self):
        registry = self.fixture.registry.read_bytes()
        other = self.other.read_bytes()
        result, choice, copy, error, _info = self.dialog(True)
        self.assertEqual(result, 'My brushes')
        choice.assert_called_once()
        self.assertIn("'My brushes'", choice.call_args.args[1])
        copy.assert_not_called(); error.assert_not_called()
        self.assertEqual(profiles.PROFILES[result][0], self.key)
        self.assertEqual(self.fixture.registry.read_bytes(), registry)
        self.assertEqual(json.loads(self.original.read_text())['quality'], 'High detail')
        self.assertEqual(self.other.read_bytes(), other)
        self.assertFalse(portability.profile_settings_file(self.package['profile']['key']).exists())
        self.app._apply_profile_change.assert_called_once_with('My brushes')

    def test_case_variant_copy_keeps_existing_data_and_publishes_new_owner(self):
        original = self.original.read_bytes()
        result, choice, copy, error, _info = self.dialog(False)
        self.assertEqual(result, 'Imported copy')
        choice.assert_called_once(); copy.assert_called_once(); error.assert_not_called()
        new_key = profiles.PROFILES[result][0]
        self.assertNotIn(new_key, (self.key, self.package['profile']['key']))
        self.assertEqual(self.original.read_bytes(), original)
        self.assertEqual(json.loads(portability.profile_settings_file(new_key).read_text())['quality'], 'High detail')
        self.assertEqual(json.loads(self.fixture.registry.read_text())[result], new_key)
        self.app._apply_profile_change.assert_called_once_with(result)

    def test_cancel_at_either_prompt_preserves_files_and_does_not_save_or_reload(self):
        previous = self.fixture.state()
        for answer, copy_name in ((None, 'unused'), (False, None), (False, '')):
            with self.subTest(answer=answer, copy_name=copy_name):
                result, choice, _copy, error, info = self.dialog(answer, copy_name)
                self.assertIsNone(result)
                choice.assert_called_once(); error.assert_not_called(); info.assert_not_called()
                self.assertEqual(self.fixture.state(), previous)
        self.app.save_settings.assert_not_called()
        self.app._apply_profile_change.assert_not_called()

    def test_changed_collision_name_or_uuid_during_either_prompt_cannot_publish(self):
        for action in ('replace', 'copy'):
            for change in ('renamed', 'rebound'):
                with self.subTest(action=action, change=change), patch.dict(profiles.PROFILES):
                    previous = self.fixture.state()
                    def mutate(*_args, **_kwargs):
                        record = profiles.PROFILES['My brushes']
                        if change == 'renamed':
                            del profiles.PROFILES['My brushes']
                            profiles.PROFILES['My renamed brushes'] = record
                        else:
                            profiles.PROFILES['My brushes'] = ('custom-' + 'f' * 32, *record[1:])
                        return True if action == 'replace' else 'Imported copy'
                    result, _choice, _copy, error, info = self.dialog(
                        mutate if action == 'replace' else False,
                        mutate if action == 'copy' else 'unused')
                    self.assertIsNone(result)
                    error.assert_called_once(); info.assert_not_called()
                    self.assertIn('changed', error.call_args.args[1])
                    self.assertEqual(self.fixture.state(), previous)
        self.app.save_settings.assert_not_called()
        self.app._apply_profile_change.assert_not_called()

    def test_busy_or_closing_modal_callback_does_not_publish_or_show_shutdown_feedback(self):
        previous = self.fixture.state()
        for answer in (True, False):
            for state in ('activity', 'closing', 'profile_change_after'):
                with self.subTest(answer=answer, state=state):
                    def mutate(*_args, **_kwargs):
                        setattr(self.app, state, True if state == 'closing' else 'pending')
                        return answer
                    try:
                        result, _choice, copy, error, info = self.dialog(mutate)
                        self.assertIsNone(result)
                        self.assertEqual(self.fixture.state(), previous)
                        copy.assert_not_called(); info.assert_not_called()
                        if state == 'closing': error.assert_not_called()
                        else: error.assert_called_once()
                    finally:
                        setattr(self.app, state, False if state == 'closing' else None)
        self.app.save_settings.assert_not_called()
        self.app._apply_profile_change.assert_not_called()

    def test_case_variant_builtin_identity_requires_the_original_target_key(self):
        bad = dict(self.package)
        bad['profile'] = dict(self.package['profile'], name='MICROSOFT PAINT')
        with self.assertRaisesRegex(portability.ProfilePortabilityError, 'Built-in'):
            portability.validate_package(bad)
        self.path.write_text(json.dumps(bad), encoding='utf-8')
        previous = self.fixture.state()
        result, choice, copy, error, info = self.dialog(True)
        self.assertIsNone(result)
        choice.assert_not_called(); copy.assert_not_called(); info.assert_not_called()
        error.assert_called_once()
        self.assertEqual(self.fixture.state(), previous)
        self.app.save_settings.assert_not_called()
        good = portability.build_package('Microsoft Paint', {'quality': 'High detail'})
        good['profile']['name'] = 'MICROSOFT PAINT'
        portability.write_profile_file(self.path, good)
        result, choice, _copy, error, _info = self.dialog(True)
        self.assertEqual(result, 'Microsoft Paint')
        self.assertIn("'Microsoft Paint'", choice.call_args.args[1])
        error.assert_not_called()

    def test_direct_default_replace_resolves_case_without_changing_copy_semantics(self):
        self.assertEqual(portability.import_package_into_app(self.app, self.package), 'My brushes')
        copied = portability.import_package_into_app(self.app, self.package,
                                                     action='copy', copy_name='Explicit copy')
        self.assertEqual(copied, 'Explicit copy')
        self.assertEqual(profiles.PROFILES['My brushes'][0], self.key)
        self.assertNotEqual(profiles.PROFILES[copied][0], self.key)

    def test_reentrant_save_rechecks_confirmed_destination_before_publication(self):
        previous = self.fixture.state()
        with patch.dict(profiles.PROFILES):
            def changed_during_save():
                record = profiles.PROFILES['My brushes']
                profiles.PROFILES['My brushes'] = ('custom-' + 'f' * 32, *record[1:])
                return True
            self.app.save_settings.side_effect = changed_during_save
            result, _choice, _copy, error, info = self.dialog(True)
            self.assertIsNone(result)
            error.assert_called_once(); info.assert_not_called()
            self.assertEqual(self.fixture.state(), previous)
            self.app._apply_profile_change.assert_not_called()

    def test_new_collision_during_save_requires_a_fresh_dialog_before_replacement(self):
        self.package['profile']['name'] = 'Incoming profile'
        portability.write_profile_file(self.path, self.package)
        appeared = {}
        def introduced_during_save():
            profiles.add_custom_profile('INCOMING PROFILE', self.fixture.registry)
            key = profiles.PROFILES['INCOMING PROFILE'][0]
            path = portability.profile_settings_file(key)
            path.write_text('{"quality": "Balanced", "brush_px": "7"}', encoding='utf-8')
            appeared.update(key=key, path=path, state=self.fixture.state())
            return True
        self.app.save_settings.side_effect = introduced_during_save
        result, choice, copy, error, info = self.dialog()
        self.assertEqual(self.fixture.state(), appeared['state'])
        self.assertIsNone(result)
        choice.assert_not_called(); copy.assert_not_called(); info.assert_not_called()
        error.assert_called_once()
        self.app._apply_profile_change.assert_not_called()
        self.assertEqual(profiles.PROFILES['INCOMING PROFILE'][0], appeared['key'])
        # The dialog-only expectation must not change the existing direct API:
        # an explicit default Replace can still target this now-known name.
        self.app.save_settings.side_effect = None
        destination = portability.import_package_into_app(self.app, self.package)
        self.assertEqual(destination, 'INCOMING PROFILE')
        self.assertEqual(profiles.PROFILES[destination][0], appeared['key'])
        self.assertEqual(json.loads(appeared['path'].read_text())['quality'], 'High detail')


if __name__ == '__main__':
    unittest.main()
