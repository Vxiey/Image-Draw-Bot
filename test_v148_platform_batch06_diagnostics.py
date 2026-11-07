"""Per-account WER paths and privacy/rotation failure regressions."""
from contextlib import ExitStack, redirect_stdout
import copy
import importlib.metadata
from io import StringIO
import json
import ntpath
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import CrashDiagnostics as crash
import CrashDumpConfig as dumps
import DiagnosticsPackage as diagnostics
from test_native_safety_maintenance_rc4 import FakeRegistry


class PerAccountDumpsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.admin = self.root / 'administrator'
        self.user = self.root / 'ordinary-user'
        self.registry = FakeRegistry()
        self.original = {'DumpFolder': ['original folder', 2], 'DumpCount': [9, 4], 'DumpType': [2, 4]}
        self.registry.values['ImageDrawBot.exe'] = copy.deepcopy(self.original)
        self.stack.enter_context(patch.dict(dumps.sys.modules, {'winreg': self.registry}))
        self.stack.enter_context(patch.object(dumps.sys, 'platform', 'win32'))
        self.stack.enter_context(patch.dict(os.environ, {'LOCALAPPDATA': str(self.admin)}))
        self.stack.enter_context(patch.object(dumps, 'load_system_library', return_value=SimpleNamespace(IsUserAnAdmin=Mock(return_value=1))))
        self.backup = self.admin / 'ImageDrawBot/dumps/localdumps-backup.json'

    def legacy(self):
        old = {'DumpFolder': [str(self.admin / 'ImageDrawBot/dumps'), 2], 'DumpCount': [5, 4], 'DumpType': [1, 4]}
        self.registry.values['ImageDrawBot.exe'] = copy.deepcopy(old)
        self.backup.parent.mkdir(parents=True, exist_ok=True)
        self.backup.write_text(json.dumps({'ImageDrawBot.exe': {'original': self.original, 'written': old}}))
        return old

    def test_elevated_configuration_is_expanded_for_the_crashing_account(self):
        message = dumps.configure('enable')
        folder, kind = self.registry.values['ImageDrawBot.exe']['DumpFolder']
        self.assertEqual((folder, kind), (r'%LOCALAPPDATA%\ImageDrawBot\dumps', self.registry.REG_EXPAND_SZ))
        self.assertNotIn(str(self.admin), folder)
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.user)}):
            self.assertEqual(ntpath.expandvars(folder), str(self.user) + r'\ImageDrawBot\dumps')
            self.assertEqual(dumps.user_dump_folder(), self.user / 'ImageDrawBot/dumps')
        self.assertIn('Each Windows account', message)
        dumps.configure('disable')
        self.assertEqual(self.registry.values['ImageDrawBot.exe'], self.original)

    def test_old_owned_absolute_path_migrates_without_forgetting_original_values(self):
        old = self.legacy()
        def before_write():
            saved = json.loads(self.backup.read_text())['ImageDrawBot.exe']
            self.assertEqual(saved['original'], self.original)
            self.assertEqual(saved['previous_written'], old)
            self.assertEqual(saved['written']['DumpFolder'], [dumps.DUMP_FOLDER_TEMPLATE, 2])
        with patch.object(self.registry, 'before_write', side_effect=before_write):
            dumps.configure('enable')
        self.assertNotIn('previous_written', json.loads(self.backup.read_text())['ImageDrawBot.exe'])
        dumps.configure('disable')
        self.assertEqual(self.registry.values['ImageDrawBot.exe'], self.original)

    def test_partial_migration_can_be_disabled_at_each_native_write_failure(self):
        setter = self.registry.SetValueEx
        for field in dumps.VALUE_NAMES:
            old = self.legacy()
            def fail(name, value_name, reserved, kind, value):
                if value_name == field:
                    raise PermissionError('injected registry write failure')
                setter(name, value_name, reserved, kind, value)
            with self.subTest(field=field), patch.object(self.registry, 'SetValueEx', side_effect=fail):
                with self.assertRaises(PermissionError):
                    dumps.configure('enable')
            saved = json.loads(self.backup.read_text())['ImageDrawBot.exe']
            self.assertEqual(saved['previous_written'], old)
            dumps.configure('disable')
            self.assertEqual(self.registry.values['ImageDrawBot.exe'], self.original)

    def test_post_registry_backup_failure_retains_both_known_versions_for_recovery(self):
        self.legacy()
        writer = dumps.atomic_write_text
        calls = []
        def fail_final(path, text):
            calls.append(1)
            if len(calls) == 2:
                raise PermissionError('injected final backup publication failure')
            writer(path, text)
        with patch.object(dumps, 'atomic_write_text', side_effect=fail_final):
            with self.assertRaises(PermissionError):
                dumps.configure('enable')
        self.assertIn('previous_written', json.loads(self.backup.read_text())['ImageDrawBot.exe'])
        self.registry.values['ImageDrawBot.exe']['DumpFolder'] = ['external later folder', 2]
        dumps.configure('disable')
        expected = dict(self.original, DumpFolder=['external later folder', 2])
        self.assertEqual(self.registry.values['ImageDrawBot.exe'], expected)

    def test_normal_start_prepares_its_own_dump_directory_and_export_lists_that_account(self):
        dumps.configure('enable')
        log_dir = self.user / 'ImageDrawBot/logs'
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.user)}), ExitStack() as local:
            local.enter_context(patch.object(crash, '_INSTALLED', False))
            local.enter_context(patch.object(crash, '_LOG_STREAM', None))
            for name, value in {'LOG_DIR': log_dir, 'CRASH_LOG': log_dir / 'crash.log',
                                'SESSION_LOG': log_dir / 'session.log', 'DEBUG_ERROR_LOG': log_dir / 'errors.log'}.items():
                local.enter_context(patch.object(crash, name, value))
            local.enter_context(patch.object(crash.sys, 'excepthook', Mock()))
            local.enter_context(patch.object(crash.threading, 'excepthook', Mock()))
            local.enter_context(patch.object(crash.platform, 'platform', return_value='fixture Windows'))
            local.enter_context(patch.object(crash.faulthandler, 'enable'))
            crash.install()
            if crash._LOG_STREAM is not None:
                local.callback(crash._LOG_STREAM.close)
            folder = self.user / 'ImageDrawBot/dumps'
            self.assertTrue(folder.is_dir())
            (folder / 'ImageDrawBot.exe.123.dmp').write_bytes(b'synthetic dump inventory only')
            local.enter_context(patch.object(diagnostics, 'data_dir', return_value=self.user / 'ImageDrawBot'))
            local.enter_context(patch.object(diagnostics, 'DIAGNOSTICS_DIR', self.user / 'diagnostics'))
            local.enter_context(patch.object(diagnostics, '_technical_info', return_value={'app': 'fixture'}))
            with zipfile.ZipFile(diagnostics.create_diagnostics_package()) as archive:
                inventory = json.loads(archive.read('dump-files.json'))
                self.assertFalse(inventory['memory_dumps_included'])
                self.assertEqual(inventory['files'][0]['name'], 'ImageDrawBot.exe.123.dmp')
                self.assertFalse(any(name.endswith('.dmp') for name in archive.namelist()))


class DiagnosticContractCompletionTests(unittest.TestCase):
    def test_failed_rotation_preserves_the_current_and_previous_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            current = Path(temporary) / 'session.log'
            backup = Path(temporary) / 'session.log.1'
            current.write_bytes(b'current evidence')
            backup.write_bytes(b'previous evidence')
            with patch.object(crash.os, 'replace', side_effect=PermissionError('synthetic file lock')):
                self.assertFalse(crash._rotate_if_large(current, limit=4))
            self.assertEqual(current.read_bytes(), b'current evidence')
            self.assertEqual(backup.read_bytes(), b'previous evidence')
            self.assertTrue(crash._rotate_if_large(current, limit=4))
            self.assertEqual(backup.read_bytes(), b'current evidence')

    def test_private_summary_names_are_opaque_and_redaction_collisions_keep_both_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for number, secret in enumerate(('FIRST_SECRET', 'SECOND_SECRET'), 1):
                (root / f'settings-token={secret}.json').write_text(json.dumps({'quality': f'choice-{number}'}))
                (root / f'calibration-token={secret}.json').write_text(json.dumps({'version': number, 'colors': [1] * number}))
            with patch.object(diagnostics, 'data_dir', return_value=root), \
                 patch.object(diagnostics, 'DIAGNOSTICS_DIR', root / 'diagnostics'), \
                 patch.object(diagnostics, '_technical_info', return_value={'app': 'fixture'}):
                with zipfile.ZipFile(diagnostics.create_diagnostics_package()) as archive:
                    settings = archive.read('settings-summary.json')
                    calibration = archive.read('calibration-summary.json')
            for content in (settings, calibration):
                self.assertNotIn(b'FIRST_SECRET', content)
                self.assertNotIn(b'SECOND_SECRET', content)
                self.assertEqual(len(json.loads(content)), 2)
            self.assertEqual({value['quality'] for value in json.loads(settings).values()}, {'choice-1', 'choice-2'})


class DiagnosticFailureReportingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(diagnostics, 'data_dir', return_value=self.root))
        self.stack.enter_context(patch.object(diagnostics, 'DIAGNOSTICS_DIR', self.root / 'diagnostics'))
        self.stack.enter_context(patch.object(diagnostics, 'diagnostics_summary', return_value={'available': False}))
        self.stack.enter_context(patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)}))

    def test_bad_real_distribution_metadata_is_reported_without_losing_other_versions_or_logs(self):
        metadata = self.root / 'requests-1.0.dist-info'
        metadata.mkdir()
        (metadata / 'METADATA').write_bytes(b'Name: requests\nVersion: \xff\n')
        distribution = importlib.metadata.PathDistribution(metadata)
        log = self.root / 'logs/ImageDrawBot-session.log'
        log.parent.mkdir()
        log.write_text('Useful synthetic failure evidence\n')
        def version(name):
            return distribution.version if name == 'requests' else '9.0'
        with patch.object(diagnostics.importlib.metadata, 'version', side_effect=version):
            with zipfile.ZipFile(diagnostics.create_diagnostics_package()) as archive:
                system = json.loads(archive.read('system.json'))
                self.assertIn(b'Useful synthetic failure evidence', archive.read('logs/ImageDrawBot-session.log'))
                self.assertEqual(system['packages']['Pillow'], '9.0')
                self.assertNotIn('requests', system['packages'])
                self.assertEqual(system['collection_issues'], [{
                    'section': 'package-version', 'package': 'requests', 'error': 'UnicodeDecodeError'}])

    def test_optional_metadata_error_never_copies_the_exception_message(self):
        def version(name):
            if name == 'requests':
                raise PermissionError('token=PRIVATE_SECRET C:\\private\\account')
            return '9.0'
        with patch.object(diagnostics.importlib.metadata, 'version', side_effect=version):
            with zipfile.ZipFile(diagnostics.create_diagnostics_package()) as archive:
                system = archive.read('system.json')
        self.assertNotIn(b'PRIVATE_SECRET', system)
        self.assertIn(b'PermissionError', system)

    def test_isolated_surrogate_in_local_settings_cannot_break_the_report_zip(self):
        (self.root / 'settings.json').write_bytes(b'{"quality":"damaged \\udc80 name"}')
        with zipfile.ZipFile(diagnostics.create_diagnostics_package()) as archive:
            data = archive.read('settings-summary.json')
            self.assertEqual(json.loads(data)['settings-001.json']['quality'], 'damaged \udc80 name')
            self.assertIsNone(archive.testzip())

    def test_saved_zip_remains_a_success_when_explorer_cannot_open_its_folder(self):
        folder_opener = Mock(side_effect=OSError('Explorer unavailable'))
        operating_system = SimpleNamespace(name='nt', close=os.close, replace=os.replace,
                                           environ=os.environ, startfile=folder_opener)
        output = StringIO()
        with patch.object(diagnostics, 'os', operating_system), \
             patch.object(diagnostics, '_technical_info', return_value={'app': 'fixture'}), \
             patch.object(diagnostics.sys, 'frozen', True, create=True), \
             patch('tkinter.messagebox.showinfo') as notice, \
             redirect_stdout(output):
            code = diagnostics.main()
        self.assertEqual(code, 0)
        paths = list((self.root / 'diagnostics').glob('*.zip'))
        self.assertEqual(len(paths), 1)
        with zipfile.ZipFile(paths[0]) as archive:
            self.assertIsNone(archive.testzip())
        self.assertIn(str(paths[0]), output.getvalue())
        self.assertIn('saved successfully', output.getvalue())
        self.assertNotIn('Could not collect', output.getvalue())
        folder_opener.assert_called_once_with(str(paths[0].parent))
        self.assertIn(str(paths[0]), notice.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
