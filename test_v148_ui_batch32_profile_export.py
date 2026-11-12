"""AW15 completion: an export chooser cannot outlive its selected profile.

The package reader, validator and atomic publisher run against real temporary
files. Only native dialog boundaries and the publication failure are injected.
"""
from contextlib import ExitStack
import errno
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import GameProfiles as profiles
import ProfilePortability as portability
import RuntimePaths


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ProfileExportLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.data = self.root / 'data'
        self.exports = self.root / 'exports'
        self.data.mkdir()
        self.exports.mkdir()
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.data))
        self.stack.enter_context(patch.dict(profiles.PROFILES))
        self.stack.enter_context(patch.dict(profiles.PROFILE_UI))
        self.name = 'Export brushes'
        self.key = 'custom-' + 'a' * 32
        profiles.register_custom_profiles({self.name: self.key})
        self.settings = {
            'settings_schema': 2, 'quality': 'High detail',
            'cpu_workers': '4', 'corners': [[10, 20], [310, 220]],
        }
        self.save_calls = []
        self.app = SimpleNamespace(
            game=Value(self.name), activity=None, closing=False, root=None,
            pending_clear_drawing=None, profile_change_after=None,
            profile_change_in_progress=False,
            settings_path=portability.profile_settings_file(self.key),
            save_settings=self.save_settings,
        )
        self.palette = {
            'version': 4, 'profile': self.key, 'state': 'calibrated',
            'colors': [
                {'name': 'Black', 'position': [10, 20], 'rgb': [0, 0, 0]},
                {'name': 'White', 'position': [30, 20], 'rgb': [255, 255, 255]},
            ],
        }
        self.palette_path = portability.portable_path_map(self.key)['palette']
        self.palette_path.write_text(json.dumps(self.palette), encoding='utf-8')

    def save_settings(self):
        text = json.dumps(self.settings, ensure_ascii=False)
        self.save_calls.append(text)
        RuntimePaths.atomic_write_text(self.app.settings_path, text)
        return True

    def export_state(self):
        return {path.name: path.read_bytes() for path in self.exports.iterdir()}

    def dialog(self, selected):
        with ExitStack() as context:
            chooser = context.enter_context(patch(
                'tkinter.filedialog.asksaveasfilename',
                **({'side_effect': selected} if callable(selected)
                   else {'return_value': selected}),
            ))
            info = context.enter_context(patch('tkinter.messagebox.showinfo'))
            error = context.enter_context(patch('tkinter.messagebox.showerror'))
            context.enter_context(patch('tkinter.messagebox.askyesno', return_value=True))
            result = portability.export_profile_dialog(self.app)
        return result, chooser, info, error

    def assert_package(self, path):
        package = portability.read_profile_file(path)
        self.assertEqual(package['profile'], {'name': self.name, 'key': self.key})
        self.assertEqual(package['settings']['renderer']['quality'], 'High detail')
        self.assertEqual(package['settings']['resources']['cpu_workers'], '4')
        self.assertEqual(package['canvas']['corners'], [[10, 20], [310, 220]])
        self.assertEqual(package['calibration']['palette'], self.palette)
        self.assertTrue(package['safety']['requires_reverification'])
        self.assertFalse(package['safety']['machine_specific_state_included'])
        self.assertIsInstance(package['created_at'], str)
        return package

    def test_same_profile_exports_real_package_with_supported_and_normalized_suffixes(self):
        for filename, expected in (
            ('paint.drawprofile', 'paint.drawprofile'),
            ('paint.json', 'paint.json'),
            ('paint.DRAWPROFILE', 'paint.DRAWPROFILE'),
            ('paint.backup', 'paint.drawprofile'),
        ):
            with self.subTest(filename=filename):
                target = self.exports / expected
                target.write_bytes(b'previous export')
                before_saves = len(self.save_calls)
                result, chooser, info, error = self.dialog(str(self.exports / filename))
                self.assertEqual(result, target)
                self.assertEqual(len(self.save_calls), before_saves + 1)
                chooser.assert_called_once()
                self.assertEqual(chooser.call_args.kwargs['initialfile'], 'export-brushes.drawprofile')
                self.assertEqual(chooser.call_args.kwargs['defaultextension'], '.drawprofile')
                self.assert_package(target)
                info.assert_called_once()
                error.assert_not_called()
                self.assertFalse(any(path.name.endswith('.tmp') for path in self.exports.iterdir()))

    def test_same_profile_uses_the_captured_snapshot_without_resaving_after_chooser(self):
        target = self.exports / 'snapshot.drawprofile'

        def choose(**_kwargs):
            self.assertEqual(len(self.save_calls), 1)
            self.settings['quality'] = 'Balanced'
            self.settings['cpu_workers'] = '8'
            RuntimePaths.atomic_write_text(self.app.settings_path, json.dumps(self.settings))
            changed_palette = dict(self.palette, colors=list(reversed(self.palette['colors'])))
            self.palette_path.write_text(json.dumps(changed_palette), encoding='utf-8')
            return str(target)

        result, _chooser, info, error = self.dialog(choose)
        self.assertEqual(result, target)
        self.assertEqual(len(self.save_calls), 1)
        self.assert_package(target)
        self.assertEqual(json.loads(self.app.settings_path.read_text())['quality'], 'Balanced')
        info.assert_called_once()
        error.assert_not_called()

    def test_cancel_preserves_absent_and_existing_destinations_without_feedback(self):
        target = self.exports / 'cancelled.drawprofile'
        for selected, existing in (('', False), (None, True)):
            with self.subTest(selected=selected, existing=existing):
                if existing:
                    target.write_bytes(b'keep this export')
                before = self.export_state()
                result, chooser, info, error = self.dialog(selected)
                self.assertIsNone(result)
                self.assertEqual(self.export_state(), before)
                chooser.assert_called_once()
                info.assert_not_called()
                error.assert_not_called()

    def test_work_or_pending_state_started_in_chooser_blocks_publication(self):
        for attribute, value in (
            ('activity', 'preview'), ('pending_clear_drawing', object()),
            ('pending_clear_drawing', False), ('profile_change_after', 'after#pending'),
            ('profile_change_after', False), ('profile_change_in_progress', True),
        ):
            for existing in (False, True):
                with self.subTest(attribute=attribute, value=value, existing=existing):
                    target = self.exports / 'blocked.drawprofile'
                    target.unlink(missing_ok=True)
                    if existing:
                        target.write_bytes(b'keep the previous export')
                    before = self.export_state()

                    def choose(**_kwargs):
                        setattr(self.app, attribute, value)
                        return str(target)

                    try:
                        result, chooser, info, error = self.dialog(choose)
                        self.assertIsNone(result)
                        self.assertEqual(self.export_state(), before)
                        chooser.assert_called_once()
                        info.assert_not_called()
                        error.assert_called_once()
                    finally:
                        setattr(self.app, attribute, False if attribute == 'profile_change_in_progress' else None)

    def test_shutdown_in_chooser_preserves_destination_without_reading_destroyed_state(self):
        target = self.exports / 'shutdown.drawprofile'
        target.write_bytes(b'keep the previous export')
        before = self.export_state()

        def destroyed_getter():
            raise AssertionError('Export read the profile variable after shutdown.')

        def choose(**_kwargs):
            self.app.closing = True
            self.app.game.get = destroyed_getter
            return str(target)

        result, chooser, info, error = self.dialog(choose)
        self.assertIsNone(result)
        self.assertEqual(self.export_state(), before)
        chooser.assert_called_once()
        info.assert_not_called()
        error.assert_not_called()

    def test_completed_profile_switch_rejects_the_old_snapshot(self):
        target = self.exports / 'switched.drawprofile'
        target.write_bytes(b'keep the previous export')
        before = self.export_state()

        def choose(**_kwargs):
            self.app.game.set('Microsoft Paint')
            self.app.settings_path = portability.profile_settings_file('microsoft-paint')
            RuntimePaths.atomic_write_text(self.app.settings_path, '{"quality": "Balanced"}')
            return str(target)

        result, _chooser, info, error = self.dialog(choose)
        self.assertIsNone(result)
        self.assertEqual(self.export_state(), before)
        self.assertEqual(len(self.save_calls), 1)
        self.assertEqual(json.loads(self.app.settings_path.read_text())['quality'], 'Balanced')
        info.assert_not_called()
        error.assert_called_once()

    def test_renamed_removed_or_rebound_profile_cannot_publish_a_stale_snapshot(self):
        for change in ('rename', 'case-only rename', 'remove', 'rebind'):
            with self.subTest(change=change), patch.dict(profiles.PROFILES):
                self.app.game.set(self.name)
                target = self.exports / 'identity.drawprofile'
                target.write_bytes(b'keep the previous export')
                before = self.export_state()

                def choose(**_kwargs):
                    record = profiles.PROFILES[self.name]
                    if change == 'rebind':
                        profiles.PROFILES[self.name] = ('custom-' + 'b' * 32, *record[1:])
                    else:
                        del profiles.PROFILES[self.name]
                        if change != 'remove':
                            renamed = self.name.upper() if change == 'case-only rename' else 'Renamed brushes'
                            profiles.PROFILES[renamed] = record
                            self.app.game.set(renamed)
                    return str(target)

                result, _chooser, info, error = self.dialog(choose)
                self.assertIsNone(result)
                self.assertEqual(self.export_state(), before)
                info.assert_not_called()
                error.assert_called_once()

    def test_preexisting_busy_or_closing_state_blocks_capture_and_chooser(self):
        for attribute, value in (
            ('activity', 'draw'), ('closing', True), ('pending_clear_drawing', False),
            ('profile_change_after', 'after#pending'), ('profile_change_in_progress', True),
        ):
            with self.subTest(attribute=attribute):
                setattr(self.app, attribute, value)
                before_saves = len(self.save_calls)
                try:
                    result, chooser, info, error = self.dialog(str(self.exports / 'not-opened.drawprofile'))
                    self.assertIsNone(result)
                    self.assertEqual(len(self.save_calls), before_saves)
                    self.assertEqual(self.export_state(), {})
                    chooser.assert_not_called()
                    info.assert_not_called()
                    if attribute == 'closing':
                        error.assert_not_called()
                    else:
                        error.assert_called_once()
                finally:
                    setattr(self.app, attribute, False if attribute in ('closing', 'profile_change_in_progress') else None)

    def test_failed_initial_save_never_opens_chooser_and_shutdown_has_no_feedback(self):
        self.app.settings_path.write_text('{"quality": "Balanced"}', encoding='utf-8')
        previous = self.app.settings_path.read_bytes()
        for closing in (False, True):
            with self.subTest(closing=closing):
                self.app.closing = False

                def failed_save():
                    self.app.closing = closing
                    return False

                self.app.save_settings = failed_save
                result, chooser, info, error = self.dialog(str(self.exports / 'not-opened.drawprofile'))
                self.assertIsNone(result)
                self.assertEqual(self.app.settings_path.read_bytes(), previous)
                self.assertEqual(self.export_state(), {})
                chooser.assert_not_called()
                info.assert_not_called()
                if closing:
                    error.assert_not_called()
                else:
                    error.assert_called_once()

    def test_publish_failure_preserves_destination_and_removes_staged_file(self):
        target = self.exports / 'failed.drawprofile'
        original_replace = RuntimePaths.os.replace
        attempts = []

        def fail_publication(source, destination):
            if Path(destination) == target:
                attempts.append(Path(source))
                self.assertTrue(Path(source).is_file())
                raise OSError(errno.EIO, 'profile publication failed')
            return original_replace(source, destination)

        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    target.write_bytes(b'keep the previous export')
                before = self.export_state()
                with patch('RuntimePaths.os.replace', side_effect=fail_publication):
                    result, _chooser, info, error = self.dialog(str(target))
                self.assertIsNone(result)
                self.assertEqual(self.export_state(), before)
                self.assertFalse(any(path.exists() for path in attempts))
                info.assert_not_called()
                error.assert_called_once()
                self.assertIn('profile publication failed', error.call_args.args[1])
        self.assertEqual(len(attempts), 2)

    def test_shutdown_during_successful_publication_suppresses_feedback(self):
        target = self.exports / 'published.drawprofile'
        original_replace = RuntimePaths.os.replace

        def publish_and_close(source, destination):
            result = original_replace(source, destination)
            if Path(destination) == target:
                self.app.closing = True
            return result

        with patch('RuntimePaths.os.replace', side_effect=publish_and_close):
            result, _chooser, info, error = self.dialog(str(target))
        self.assertEqual(result, target)
        self.assert_package(target)
        self.assertEqual(set(self.export_state()), {target.name})
        info.assert_not_called()
        error.assert_not_called()

    def test_shutdown_during_failed_publication_preserves_file_without_feedback(self):
        target = self.exports / 'failed-on-close.drawprofile'
        target.write_bytes(b'keep the previous export')
        before = self.export_state()
        original_replace = RuntimePaths.os.replace

        def fail_and_close(source, destination):
            if Path(destination) == target:
                self.app.closing = True
                raise OSError(errno.EIO, 'profile publication failed during shutdown')
            return original_replace(source, destination)

        with patch('RuntimePaths.os.replace', side_effect=fail_and_close):
            result, _chooser, info, error = self.dialog(str(target))
        self.assertIsNone(result)
        self.assertEqual(self.export_state(), before)
        info.assert_not_called()
        error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
