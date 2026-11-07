"""Bounded diagnostic exports retain and identify the actual active profile."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import DiagnosticsPackage as diagnostics
import DrawBot


class ActiveProfileDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(patch.object(diagnostics, 'data_dir', return_value=self.root))
        self.stack.enter_context(patch.object(diagnostics, 'DIAGNOSTICS_DIR', self.root / 'diagnostics'))
        self.stack.enter_context(patch.object(diagnostics, 'diagnostics_summary', return_value={'available': False}))
        self.stack.enter_context(patch.object(diagnostics, '_package_versions', return_value={}))
        self.stack.enter_context(patch('CrashDumpConfig.user_dump_folder', return_value=self.root / 'dumps'))

    def background_profiles(self, count=100):
        for index in range(count):
            (self.root / f'settings-custom-{index:04d}.json').write_text(json.dumps({'quality': 'Background'}))
            (self.root / f'calibration-custom-{index:04d}.json').write_text(json.dumps({'version': 1, 'colors': []}))

    def active_files(self, key='custom-zzzz'):
        suffix = '' if key == 'generic' else '-' + key
        settings, calibration = self.root / f'settings{suffix}.json', self.root / f'calibration{suffix}.json'
        settings.write_text(json.dumps({'quality': 'Active profile', 'corners': [[123, 456], [789, 987]],
                                        'speed': 'token=PRIVATE_SETTING'}))
        calibration.write_text(json.dumps({'version': 37, 'colors': [[10, 20, 30]],
                                           'anchor': [12, 34], 'client_rect': [56, 78, 90, 12]}))
        return settings, calibration

    def package(self, context):
        with zipfile.ZipFile(diagnostics.create_diagnostics_package(context)) as archive:
            self.assertIsNone(archive.testzip())
            raw = {name: archive.read(name) for name in archive.namelist()}
        return {name: json.loads(value) for name, value in raw.items() if name.endswith('.json')}, raw

    def test_public_archive_keeps_active_profile_within_existing_hundred_file_budget(self):
        self.background_profiles()
        self.active_files()
        result, raw = self.package({'profile': 'Active profile', 'profile_key': 'custom-zzzz'})
        settings, calibration = result['settings-summary.json'], result['calibration-summary.json']
        self.assertEqual(len(settings), 100)
        self.assertEqual(len(calibration), 100)
        self.assertEqual(settings['settings-001.json']['quality'], 'Active profile')
        self.assertEqual(calibration['calibration-001.json']['version'], 37)
        selection = result['profile-summary-selection.json']
        self.assertEqual(selection['settings'], 'settings-001.json')
        self.assertEqual(selection['calibration'], 'calibration-001.json')
        self.assertEqual(selection['candidate_limit_per_kind'], 100)
        self.assertTrue(selection['active_profile_requested'])
        exported = b''.join(raw.values())
        for private in (b'PRIVATE_SETTING', b'custom-zzzz', b'"corners"', b'"anchor"', b'"client_rect"'):
            self.assertNotIn(private, exported)

    def test_actual_context_uses_applied_profile_while_a_new_selection_is_pending(self):
        class ContextApp:
            game = SimpleNamespace(get=lambda: 'Pending profile')
            _active_profile_name = 'Applied profile'
            activity = None
            palette_ready = False
            corners = []
            def __getattr__(self, name):
                return SimpleNamespace(get=lambda: '')
        self.background_profiles()
        self.active_files()
        with patch.dict(DrawBot.PROFILES, {'Applied profile': ('custom-zzzz', ()),
                                         'Pending profile': ('custom-0000', ())}), \
             patch.object(DrawBot.DrawBotApp, '_target_lock_valid', return_value=False):
            context = DrawBot.DrawBotApp._diagnostics_context(ContextApp())
        self.assertEqual(context['profile'], 'Applied profile')
        self.assertEqual(context['profile_key'], 'custom-zzzz')
        result, _ = self.package(context)
        self.assertEqual(result['settings-summary.json']['settings-001.json']['quality'], 'Active profile')

    def test_generic_legacy_filenames_are_prioritized_and_ordinary_standalone_order_remains(self):
        self.background_profiles()
        self.active_files('generic')
        active, _ = self.package({'profile_key': 'generic'})
        self.assertEqual(active['settings-summary.json']['settings-001.json']['quality'], 'Active profile')
        standalone, _ = self.package(None)
        self.assertEqual(standalone['settings-summary.json']['settings-001.json']['quality'], 'Background')
        selection = standalone['profile-summary-selection.json']
        self.assertFalse(selection['active_profile_requested'])
        self.assertIsNone(selection['settings'])
        self.assertIsNone(selection['calibration'])

    def test_missing_or_invalid_active_files_are_not_mislabeled_as_another_profile(self):
        self.background_profiles(2)
        settings, calibration = self.active_files()
        settings.write_text('{broken JSON')
        calibration.unlink()
        result, _ = self.package({'profile_key': 'custom-zzzz'})
        selection = result['profile-summary-selection.json']
        self.assertIsNone(selection['settings'])
        self.assertIsNone(selection['calibration'])
        self.assertEqual(len(result['settings-summary.json']), 2)
        self.assertTrue(all(value['quality'] == 'Background' for value in result['settings-summary.json'].values()))

    def test_linked_active_file_stays_excluded_and_stop_still_prevents_publication(self):
        self.background_profiles(2)
        settings, _ = self.active_files()
        outside = self.root / 'outside.json'
        outside.write_text('{"quality":"DO_NOT_EXPORT_LINK"}')
        settings.unlink()
        try:
            settings.symlink_to(outside)
        except OSError as error:
            self.skipTest(f'Link creation unavailable: {type(error).__name__}')
        result, raw = self.package({'profile_key': 'custom-zzzz'})
        self.assertIsNone(result['profile-summary-selection.json']['settings'])
        self.assertNotIn(b'DO_NOT_EXPORT_LINK', b''.join(raw.values()))
        before = sorted((self.root / 'diagnostics').iterdir())
        stopped = False
        reader = diagnostics._json_input
        def stop_after_active(path, base, **options):
            nonlocal stopped
            value = reader(path, base, **options)
            stopped = True
            return value
        with patch.object(diagnostics, '_json_input', side_effect=stop_after_active):
            with self.assertRaises(InterruptedError):
                diagnostics.create_diagnostics_package({'profile_key': 'custom-zzzz'}, cancelled=lambda: stopped)
        self.assertEqual(sorted((self.root / 'diagnostics').iterdir()), before)


if __name__ == '__main__':
    unittest.main()
