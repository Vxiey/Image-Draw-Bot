"""Profile export distinguishes absent calibration from unusable source paths.

Package capture, JSON validation and atomic export remain real. Fixtures replace
only native dialogs and observe/fail the selected filesystem read boundary.
"""
from contextlib import ExitStack
import errno
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ProfilePortability as portability
import ProfileStorage as storage
from RuntimePaths import atomic_write_text


class ProfileExportSourceTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        temporary = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = temporary / 'data'
        self.root.mkdir()
        self.exports = temporary / 'exports'
        self.exports.mkdir()
        self.destination = self.exports / 'previous.drawprofile'
        self.stack.enter_context(patch.object(portability, 'data_dir', lambda: self.root))
        self.stack.enter_context(patch.object(storage, 'data_dir', lambda: self.root))
        self.paths = portability.portable_path_map('generic')
        self.source = self.paths['palette']
        self.palette = {
            'version': 4, 'profile': 'generic', 'state': 'calibrated',
            'colors': [{'name': 'Black', 'position': [10, 20], 'rgb': [0, 0, 0]}],
        }
        self.settings_text = json.dumps({'settings_schema': 2, 'quality': 'Balanced'})
        self.app = SimpleNamespace(activity=None, closing=False, root=None,
                                   game=SimpleNamespace(get=lambda: 'Other drawing app'),
                                   settings_path=self.paths['settings'], save_settings=self.save_settings)
        self.save_settings()
        portability.write_profile_file(self.destination, portability.build_package(
            'Microsoft Paint', {'quality': 'High detail'}))
        self.previous_export = self.destination.read_bytes()

    def save_settings(self):
        atomic_write_text(self.paths['settings'], self.settings_text)
        return True

    def export_files(self):
        return {path.name: path.read_bytes() for path in self.exports.iterdir()}

    def dialog(self):
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.destination)) as chooser, \
                patch('tkinter.messagebox.showerror') as error, \
                patch('tkinter.messagebox.showinfo') as info:
            result = portability.export_profile_dialog(self.app)
        return result, chooser, error, info

    def assert_blocked(self, source, expected_type=portability.ProfilePortabilityError):
        self.destination.write_bytes(self.previous_export)
        before = self.export_files()
        capture_error = None
        try:
            portability.package_from_app(self.app)
        except Exception as failure:
            capture_error = failure
        result, chooser, error, info = self.dialog()
        # A historical silent omission reaches the real publisher and changes
        # this existing export. Check that outcome before the error assertions.
        self.assertEqual(self.export_files(), before)
        self.assertIsInstance(capture_error, expected_type)
        self.assertIsNone(result, source.name)
        chooser.assert_not_called()
        error.assert_called_once()
        self.assertIn(str(capture_error), str(error.call_args.args[1]))
        info.assert_not_called()

    def assert_success(self, expected_calibration):
        captured = portability.package_from_app(self.app)
        self.assertEqual(captured['calibration'], expected_calibration)
        result, chooser, error, info = self.dialog()
        self.assertEqual(result, self.destination)
        chooser.assert_called_once()
        error.assert_not_called()
        info.assert_called_once()
        exported = portability.read_profile_file(self.destination)
        self.assertEqual(exported['profile'], {'name': 'Other drawing app', 'key': 'generic'})
        self.assertEqual(exported['settings']['renderer']['quality'], 'Balanced')
        self.assertEqual(exported['calibration'], expected_calibration)
        self.assertEqual(set(self.export_files()), {self.destination.name})

    def symlink(self, path, target):
        try:
            path.symlink_to(target)
        except (NotImplementedError, OSError) as error:
            if isinstance(error, NotImplementedError) or getattr(error, 'winerror', None) == 1314 or \
                    getattr(error, 'errno', None) in (errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP):
                self.skipTest('This host does not permit the native symlink fixture.')
            raise

    def test_existing_calibration_directories_stop_export_without_overwriting_destination(self):
        for logical in ('palette', 'tools', 'exact_colors'):
            with self.subTest(source=logical):
                source = self.paths[logical]
                source.mkdir()
                retained = source / 'user-data.json'
                retained.write_text('{"keep": true}', encoding='utf-8')
                try:
                    self.assert_blocked(source)
                    self.assertEqual(retained.read_text(encoding='utf-8'), '{"keep": true}')
                finally:
                    retained.unlink()
                    source.rmdir()

    def test_dangling_calibration_symlink_is_not_exported_as_missing(self):
        self.symlink(self.source, 'missing-palette.json')
        self.assertTrue(self.source.is_symlink())
        self.assertFalse(self.source.exists())
        self.assert_blocked(self.source)
        self.assertTrue(self.source.is_symlink())

    def test_regular_calibration_symlink_preserves_payload_and_target(self):
        target = self.root / 'shared-palette.json'
        target.write_text(json.dumps(self.palette), encoding='utf-8')
        before = target.read_bytes()
        self.symlink(self.source, target.name)
        self.assert_success({'palette': self.palette})
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(target.read_bytes(), before)

    def test_genuinely_absent_optional_calibration_still_exports(self):
        self.assertTrue(all(not path.exists() for key, path in self.paths.items() if key != 'settings'))
        self.assert_success({})

    @unittest.skipUnless(hasattr(os, 'mkfifo') and os.name == 'posix', 'Native FIFO/device fixture needs POSIX.')
    def test_fifo_and_device_calibration_sources_are_rejected_without_opening(self):
        native_open = Path.open
        attempted = []

        def guarded_open(path, *args, **kwargs):
            if path == self.source:
                attempted.append(path)
                raise AssertionError('A nonregular calibration source was opened.')
            return native_open(path, *args, **kwargs)

        for kind in ('fifo', 'device'):
            with self.subTest(source=kind):
                if kind == 'fifo':
                    os.mkfifo(self.source)
                    self.assertTrue(stat.S_ISFIFO(self.source.stat().st_mode))
                else:
                    self.symlink(self.source, os.devnull)
                    self.assertTrue(stat.S_ISCHR(self.source.stat().st_mode))
                try:
                    with patch.object(Path, 'open', guarded_open):
                        self.assert_blocked(self.source)
                    self.assertEqual(attempted, [])
                finally:
                    self.source.unlink()

    def test_regular_source_read_failure_reports_error_and_preserves_previous_export(self):
        self.source.write_text(json.dumps(self.palette), encoding='utf-8')
        native_open = Path.open
        attempts = []

        def denied(path, *args, **kwargs):
            if path == self.source:
                attempts.append(path)
                raise PermissionError(errno.EACCES, 'Calibration read denied', str(path))
            return native_open(path, *args, **kwargs)

        with patch.object(Path, 'open', denied):
            self.assert_blocked(self.source, PermissionError)
        self.assertEqual(attempts, [self.source, self.source])
        self.assertEqual(json.loads(self.source.read_text(encoding='utf-8')), self.palette)

    def test_json_type_validation_and_byte_budget_errors_do_not_publish_export(self):
        wrong_owner = dict(self.palette, profile='microsoft-paint')
        for raw in (b'{', b'\xff', json.dumps(wrong_owner).encode('utf-8'), b' ' * 1025):
            with self.subTest(source=raw[:40]):
                self.source.write_bytes(raw)
                with patch.object(portability, 'MAX_PROFILE_BYTES', 1024):
                    self.assert_blocked(self.source)
                self.assertEqual(self.source.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
