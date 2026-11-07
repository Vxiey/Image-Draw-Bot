"""AW15/068 completion: Reset confirms one profile across the modal event loop."""
import json
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import GameProfiles as profiles
import ProfilePortability as portability
import test_v148_ui_batch08_profile_management as management_fixtures


class ResetModalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = management_fixtures.CustomProfileManagementTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.app
        self.originals = {}
        for key in (self.fixture.key, self.fixture.other_key):
            for logical, path in portability.portable_path_map(key).items():
                path.write_bytes(f'{key} {logical} preserved'.encode())
                self.originals[path] = path.read_bytes()

    def assert_files_preserved(self):
        self.assertEqual({path: path.read_bytes() for path in self.originals}, self.originals)
        self.app._apply_profile_change.assert_not_called()
        self.app.save_settings.assert_not_called()

    def test_completed_profile_switch_inside_confirmation_preserves_both_profiles(self):
        def confirm(_title, message, **kwargs):
            self.assertIn("'My brushes'", message)
            self.assertEqual(kwargs['default'], 'no')
            self.app.game.set('Other custom')
            return True
        with patch('tkinter.messagebox.askyesno', side_effect=confirm), \
                patch('tkinter.messagebox.showinfo') as success, \
                patch('tkinter.messagebox.showerror') as failure:
            self.assertIsNone(portability.reset_profile_dialog(self.app))
        self.assert_files_preserved()
        success.assert_not_called()
        failure.assert_called_once()
        self.assertIn('selected profile changed', failure.call_args.args[1])

    def test_same_name_rebound_to_another_storage_owner_cannot_use_old_confirmation(self):
        def confirm(*_args, **_kwargs):
            old = profiles.PROFILES['My brushes']
            profiles.PROFILES['My brushes'] = (self.fixture.other_key, *old[1:])
            return True
        with patch('tkinter.messagebox.askyesno', side_effect=confirm), \
                patch('tkinter.messagebox.showinfo') as success, \
                patch('tkinter.messagebox.showerror') as failure:
            self.assertIsNone(portability.reset_profile_dialog(self.app))
        self.assert_files_preserved()
        success.assert_not_called()
        failure.assert_called_once()

    def test_worker_or_pending_profile_started_during_modal_blocks_reset(self):
        for attribute, value in (('activity', 'preview'), ('profile_change_after', 'after#pending'),
                                 ('profile_change_in_progress', True),
                                 ('pending_clear_drawing', object())):
            with self.subTest(attribute=attribute), patch.object(self.app, attribute, None, create=True):
                def confirm(*_args, **_kwargs):
                    setattr(self.app, attribute, value)
                    return True
                with patch('tkinter.messagebox.askyesno', side_effect=confirm), \
                        patch('tkinter.messagebox.showinfo') as success, \
                        patch('tkinter.messagebox.showerror') as failure:
                    self.assertIsNone(portability.reset_profile_dialog(self.app))
                self.assert_files_preserved()
                success.assert_not_called()
                failure.assert_called_once()

    def test_shutdown_before_or_inside_modal_never_reads_destroyed_tk_or_shows_feedback(self):
        for close_before in (False, True):
            with self.subTest(close_before=close_before):
                self.app.closing = close_before
                original_game = self.app.game
                destroyed_game = Mock()
                destroyed_game.get.side_effect = tk.TclError('interpreter destroyed')
                if close_before:
                    self.app.game = destroyed_game
                def confirm(*_args, **_kwargs):
                    self.app.closing = True
                    self.app.game = destroyed_game
                    return True
                try:
                    with patch('tkinter.messagebox.askyesno', side_effect=confirm) as question, \
                            patch('tkinter.messagebox.showinfo') as success, \
                            patch('tkinter.messagebox.showerror') as failure:
                        self.assertIsNone(portability.reset_profile_dialog(self.app))
                    self.assertEqual(question.call_count, 0 if close_before else 1)
                    destroyed_game.get.assert_not_called()
                    success.assert_not_called()
                    failure.assert_not_called()
                    self.assert_files_preserved()
                finally:
                    self.app.game = original_game
                    self.app.closing = False

    def test_cancel_is_no_op_and_matching_confirmation_resets_only_named_profile(self):
        with patch('tkinter.messagebox.askyesno', return_value=False), \
                patch('tkinter.messagebox.showinfo') as success:
            self.assertIsNone(portability.reset_profile_dialog(self.app))
        self.assert_files_preserved()
        success.assert_not_called()
        with patch('tkinter.messagebox.askyesno', return_value=True), \
                patch('tkinter.messagebox.showinfo') as success, \
                patch('tkinter.messagebox.showerror') as failure:
            self.assertEqual(portability.reset_profile_dialog(self.app), 'My brushes')
        failure.assert_not_called()
        success.assert_called_once()
        for path in portability.portable_path_map(self.fixture.key).values():
            self.assertFalse(path.exists())
        for path in portability.portable_path_map(self.fixture.other_key).values():
            self.assertEqual(path.read_bytes(), self.originals[path])
        self.app._apply_profile_change.assert_called_once_with('My brushes')

    def test_direct_reset_call_without_confirmation_parameters_remains_supported(self):
        self.assertEqual(portability.reset_profile(self.app), 'My brushes')
        timing = portability.profile_timing_file(self.fixture.key)
        self.assertEqual(json.loads(timing.read_text())['profiles'], {})
        for path in portability.portable_path_map(self.fixture.other_key).values():
            self.assertEqual(path.read_bytes(), self.originals[path])


if __name__ == '__main__':
    unittest.main()
