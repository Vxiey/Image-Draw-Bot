"""Custom profile maintenance keeps storage ownership and explicit confirmation."""
import ast
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import DrawBot
import GameProfiles as profiles
import ProfileIsolation
import ProfilePortability as portability
from test_v148_application_batch04_settings import Value


class CustomProfileManagementTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.root))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch.object(portability, 'data_dir', return_value=self.root))
        builtins = {name: value for name, value in profiles.PROFILES.items()
                    if not value[0].startswith('custom-')}
        self.stack.enter_context(patch.dict(profiles.PROFILES, builtins, clear=True))
        self.stack.enter_context(patch.dict(profiles.PROFILE_UI))
        self.registry = self.root / 'profiles.json'
        profiles.add_custom_profile('My brushes', self.registry)
        profiles.add_custom_profile('Other custom', self.registry)
        self.key = profiles.PROFILES['My brushes'][0]
        self.other_key = profiles.PROFILES['Other custom'][0]
        self.app = SimpleNamespace(activity=None, closing=False, root=Mock(),
            game=Value('My brushes'), status=Mock(), save_settings=Mock(return_value=True),
            profile_selector=Mock(), _apply_profile_change=Mock(), mouse=Mock(),
            full_draw_armed_until=float('inf'), manual_drop_in_armed_until=float('inf'),
            manual_drop_in_start=Value(True), pending_render_resume=object(),
            drop_action_pending=object(), pending_drop_in_import=object())
        self.app._disarm_full_draw = lambda reason: DrawBot.DrawBotApp._disarm_full_draw(self.app, reason)
        self.app._disarm_manual_drop_in = lambda reason: DrawBot.DrawBotApp._disarm_manual_drop_in(self.app, reason)

    def state(self):
        return {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}

    def owned_files(self):
        paths = portability.profile_reset_paths(self.key)
        for index, path in enumerate(paths):
            path.write_bytes(f'owned data {index}'.encode())
        return {path: path.read_bytes() for path in paths}

    def remove(self):
        return portability.remove_custom_profile(self.app, expected_name='My brushes', expected_key=self.key)

    def assert_disarmed(self):
        self.assertEqual(self.app.full_draw_armed_until, 0)
        self.assertEqual(self.app.manual_drop_in_armed_until, 0)
        self.assertFalse(self.app.manual_drop_in_start.get())
        self.assertIsNone(self.app.drop_action_pending)
        self.assertIsNone(self.app.pending_drop_in_import)
        self.assertIsNone(self.app.pending_render_resume)
        self.app.mouse.disarm_input.assert_called_once()

    def test_rename_and_case_only_rename_keep_storage_uuid_and_owned_file_bytes(self):
        originals = self.owned_files()
        result = portability.rename_custom_profile(self.app, 'My calibrated brushes')
        self.assertEqual(result, 'My calibrated brushes')
        self.assertNotIn('My brushes', profiles.PROFILES)
        self.assertEqual(profiles.PROFILES[result][0], self.key)
        self.assertEqual(json.loads(self.registry.read_text())[result], self.key)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.app._apply_profile_change.assert_called_once_with(result)
        self.assert_disarmed()
        self.app.mouse.reset_mock()
        result = portability.rename_custom_profile(self.app, 'MY CALIBRATED BRUSHES')
        self.assertEqual(profiles.PROFILES[result][0], self.key)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        exported = portability.build_package(result, {'quality': 'Balanced'})
        self.assertEqual(exported['profile'], {'name': result, 'key': self.key})

    def test_same_name_is_noop_and_builtin_or_colliding_names_are_rejected(self):
        previous = self.state()
        self.assertEqual(portability.rename_custom_profile(self.app, ' My brushes '), 'My brushes')
        self.app.save_settings.assert_not_called()
        self.app._apply_profile_change.assert_not_called()
        self.app.mouse.disarm_input.assert_not_called()
        for name in ('OTHER CUSTOM', 'microsoft paint', 'Bad\nname', ''):
            with self.subTest(name=name), self.assertRaises(portability.ProfilePortabilityError):
                portability.rename_custom_profile(self.app, name)
        for name in ('Microsoft Paint', 'Other drawing app'):
            self.app.game.set(name)
            with self.subTest(builtin=name), self.assertRaises(portability.ProfilePortabilityError):
                portability.rename_custom_profile(self.app, 'A new label')
            with self.assertRaises(portability.ProfilePortabilityError):
                portability.remove_custom_profile(self.app, expected_name=name,
                    expected_key=profiles.PROFILES[name][0])
        self.assertEqual(self.state(), previous)

    def test_remove_deletes_only_canonical_custom_files_and_frees_capacity(self):
        originals = self.owned_files()
        unrelated = ('source.png', 'export.drawprofile', 'session-recovery.json',
                     'session-image.png', 'render-progress.json', 'settings.json',
                     f'settings-{self.other_key}.json', f'unrelated-{self.key}.txt')
        for name in unrelated:
            (self.root / name).write_bytes(b'keep exact bytes')
        with patch.object(profiles, 'MAX_CUSTOM_PROFILES', 2):
            with self.assertRaisesRegex(ValueError, 'Too many'):
                profiles.add_custom_profile('Replacement', self.registry)
            self.assertEqual(self.remove(), 'My brushes')
            profiles.add_custom_profile('Replacement', self.registry)
        self.assertTrue(all(not path.exists() for path in originals))
        for name in unrelated:
            self.assertEqual((self.root / name).read_bytes(), b'keep exact bytes')
        self.assertNotIn('My brushes', profiles.PROFILES)
        self.assertNotIn('My brushes', profiles.PROFILE_UI)
        self.assertEqual(json.loads(self.registry.read_text())['Other custom'], self.other_key)
        self.assertEqual(self.app.game.get(), 'Other drawing app')
        self.app._apply_profile_change.assert_called_once_with('Other drawing app')
        self.app.save_settings.assert_not_called()
        self.assert_disarmed()

    def test_rename_failed_save_or_registry_publication_preserves_identity_and_files(self):
        self.owned_files()
        previous = self.state()
        self.app.save_settings.return_value = False
        with self.assertRaisesRegex(portability.ProfilePortabilityError, 'not renamed'):
            portability.rename_custom_profile(self.app, 'Changed')
        self.app.save_settings.return_value = True
        with patch.object(portability, '_replace_profile_files', side_effect=portability.ProfilePortabilityError('write failed')):
            with self.assertRaisesRegex(portability.ProfilePortabilityError, 'write failed'):
                portability.rename_custom_profile(self.app, 'Changed')
        self.assertEqual(self.state(), previous)
        self.assertEqual(self.app.game.get(), 'My brushes')
        self.assertEqual(profiles.PROFILES['My brushes'][0], self.key)
        self.assertNotIn('Changed', profiles.PROFILES)
        self.app._apply_profile_change.assert_not_called()
        self.app.mouse.disarm_input.assert_not_called()

    def test_remove_publication_failure_restores_deleted_files_and_registry(self):
        self.owned_files()
        previous = self.state()
        replace = os.replace
        failed = False
        def fail_registry(source, destination):
            nonlocal failed
            if Path(destination) == self.registry and Path(source).suffix == '.import' and not failed:
                failed = True
                raise PermissionError('registry is locked')
            return replace(source, destination)
        with patch('RuntimePaths.os.replace', side_effect=fail_registry):
            with self.assertRaises(portability.ProfilePortabilityError):
                self.remove()
        self.assertTrue(failed)
        self.assertEqual(self.state(), previous)
        self.assertEqual(self.app.game.get(), 'My brushes')
        self.assertEqual(profiles.PROFILES['My brushes'][0], self.key)
        self.app._apply_profile_change.assert_not_called()
        self.app.mouse.disarm_input.assert_not_called()

    def test_dialog_cancel_preserves_every_file_and_confirmation_names_exact_profile(self):
        previous = self.state()
        with patch('tkinter.messagebox.askyesno', return_value=False) as ask:
            self.assertIsNone(portability.remove_custom_profile_dialog(self.app))
        self.assertIn("'My brushes'", ask.call_args.args[1])
        self.assertEqual(ask.call_args.kwargs['default'], 'no')
        with patch('tkinter.simpledialog.askstring', return_value=None):
            self.assertIsNone(portability.rename_custom_profile_dialog(self.app))
        self.assertEqual(self.state(), previous)
        self.app._apply_profile_change.assert_not_called()

    def test_modal_callbacks_recheck_work_closing_and_exact_name_and_uuid(self):
        for action in ('rename', 'remove'):
            for state in ('busy', 'closing', 'pending', 'clearing', 'changed-name', 'changed-uuid'):
                with self.subTest(action=action, state=state), ExitStack() as context:
                    self.app.activity = None; self.app.closing = False
                    self.app.profile_change_after = None; self.app.pending_clear_drawing = None
                    self.app.game.set('My brushes')
                    context.enter_context(patch.dict(profiles.PROFILES))
                    previous = self.state()
                    def answer(*args, **kwargs):
                        if state == 'busy': self.app.activity = 'draw'
                        elif state == 'closing': self.app.closing = True
                        elif state == 'pending': self.app.profile_change_after = 'pending-job'
                        elif state == 'clearing': self.app.pending_clear_drawing = False
                        elif state == 'changed-name': self.app.game.set('Other custom')
                        else: profiles.PROFILES['My brushes'] = ('custom-' + 'f' * 32, '#000000', 'replacement')
                        return 'Renamed' if action == 'rename' else True
                    context.enter_context(patch('tkinter.messagebox.showerror'))
                    context.enter_context(patch('tkinter.simpledialog.askstring', side_effect=answer))
                    context.enter_context(patch('tkinter.messagebox.askyesno', side_effect=answer))
                    callback = (portability.rename_custom_profile_dialog if action == 'rename'
                                else portability.remove_custom_profile_dialog)
                    self.assertIsNone(callback(self.app))
                    self.assertEqual(self.state(), previous)
        self.app._apply_profile_change.assert_not_called()
        self.app.mouse.disarm_input.assert_not_called()

    def test_active_ui_exposes_both_actions_only_for_custom_profile_scope(self):
        source = ast.parse(Path('StudioUI.py').read_text(encoding='utf8'))
        calls = [node for node in ast.walk(source) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'btn'
                 and len(node.args) >= 3 and isinstance(node.args[1], ast.Constant)
                 and node.args[1].value in ('Rename…', 'Remove…')]
        self.assertEqual(len(calls), 2)
        callbacks = {'rename_custom_profile_dialog': Mock(), 'remove_custom_profile_dialog': Mock()}
        for call in calls:
            callback = eval(compile(ast.Expression(call.args[2]), '<actual profile action>', 'eval'),
                            {'a': self.app, **callbacks})
            callback()
        for callback in callbacks.values():
            callback.assert_called_once_with(self.app)
        self.assertTrue(ProfileIsolation.scope_visible('custom', self.key))
        for key in ('generic', 'microsoft-paint', 'gartic-phone'):
            self.assertFalse(ProfileIsolation.scope_visible('custom', key))


if __name__ == '__main__':
    unittest.main()
