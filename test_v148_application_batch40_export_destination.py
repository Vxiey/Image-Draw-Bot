"""The confirmation must refer to the profile file that is actually replaced."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import ProfilePortability as portability
import test_v148_ui_batch32_profile_export as fixture


class ProfileExportDestinationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.ProfileExportLifecycleTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.app
        self.destination = self.fixture.exports / 'brushes.drawprofile'
        self.selected = self.fixture.exports / 'brushes.backup'
        self.destination.write_bytes(b'previous complete export')
        self.selected.write_bytes(b'unrelated backup file')

    def export(self, answer=True, selected=None):
        with ExitStack() as stack:
            stack.enter_context(patch('tkinter.filedialog.asksaveasfilename',
                                      return_value=str(selected or self.selected)))
            confirm = stack.enter_context(patch('tkinter.messagebox.askyesno',
                **({'side_effect': answer} if callable(answer) else {'return_value': answer})))
            info = stack.enter_context(patch('tkinter.messagebox.showinfo'))
            error = stack.enter_context(patch('tkinter.messagebox.showerror'))
            result = portability.export_profile_dialog(self.app)
        return result, confirm, info, error

    def test_declining_normalized_destination_keeps_both_complete_files(self):
        before = self.fixture.export_state()
        result, confirm, info, error = self.export(False)
        self.assertIsNone(result)
        self.assertEqual(self.fixture.export_state(), before)
        confirm.assert_called_once()
        self.assertIn(str(self.destination), confirm.call_args.args[1])
        self.assertEqual(confirm.call_args.kwargs['default'], 'no')
        info.assert_not_called()
        error.assert_not_called()

    def test_approval_replaces_only_the_resolved_destination(self):
        result, confirm, info, error = self.export()
        self.assertEqual(result, self.destination)
        self.fixture.assert_package(result)
        self.assertEqual(self.selected.read_bytes(), b'unrelated backup file')
        self.assertEqual(set(self.fixture.export_state()), {'brushes.drawprofile', 'brushes.backup'})
        confirm.assert_called_once()
        info.assert_called_once()
        error.assert_not_called()

    def test_owner_changes_during_confirmation_cannot_publish(self):
        changes = (
            ('activity', 'preview'), ('pending_clear_drawing', False),
            ('profile_change_after', 'after#pending'), ('profile_change_in_progress', True),
            ('closing', True), ('game', fixture.Value('Microsoft Paint')),
        )
        for name, changed in changes:
            with self.subTest(name=name):
                before = self.fixture.export_state()
                previous = getattr(self.app, name)
                def answer(*_args, **_kwargs):
                    setattr(self.app, name, changed)
                    return True
                try:
                    result, confirm, info, error = self.export(answer)
                    self.assertIsNone(result)
                    self.assertEqual(self.fixture.export_state(), before)
                    confirm.assert_called_once()
                    info.assert_not_called()
                    if name == 'closing':
                        error.assert_not_called()
                    else:
                        error.assert_called_once()
                finally:
                    setattr(self.app, name, previous)

    def test_new_normalized_file_does_not_request_replacement(self):
        self.destination.unlink()
        result, confirm, info, error = self.export()
        self.assertEqual(result, self.destination)
        self.fixture.assert_package(result)
        confirm.assert_not_called()
        info.assert_called_once()
        error.assert_not_called()

    def test_supported_suffix_preserves_native_chooser_confirmation(self):
        for extension in ('.drawprofile', '.JSON', '.DRAWPROFILE'):
            with self.subTest(extension=extension):
                selected = self.fixture.exports / ('native' + extension)
                selected.write_bytes(b'previous export approved by native chooser')
                result, confirm, info, error = self.export(selected=selected)
                self.assertEqual(result, selected)
                self.fixture.assert_package(result)
                confirm.assert_not_called()
                info.assert_called_once()
                error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
