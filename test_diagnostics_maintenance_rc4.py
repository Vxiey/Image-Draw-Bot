"""Privacy, bounded collection and concurrent crash-log regressions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

import CrashDiagnostics as crash
import DiagnosticsPackage as diagnostics
from LocalSanitization import safe_context, sanitize_text


class DiagnosticMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(diagnostics, 'data_dir', return_value=self.base))
        self.stack.enter_context(mock.patch.object(diagnostics, 'DIAGNOSTICS_DIR', self.base / 'diagnostics'))
        self.stack.enter_context(mock.patch.object(diagnostics, '_technical_info', return_value={'app': 'test'}))
        self.stack.enter_context(mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.base)}))

    def test_failed_collection_never_leaves_a_partial_shareable_zip(self):
        with mock.patch.object(diagnostics, '_settings_summary', side_effect=OSError('collection interrupted')):
            with self.assertRaisesRegex(OSError, 'collection interrupted'):
                diagnostics.create_diagnostics_package()
        self.assertEqual(list((self.base / 'diagnostics').iterdir()), [])

    def test_complete_archive_is_published_after_zip_close(self):
        replace = os.replace
        checked = []
        def verify_before_publish(source, target):
            self.assertFalse(Path(target).exists())
            with zipfile.ZipFile(source) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('system.json', archive.namelist())
            checked.append(Path(target))
            replace(source, target)
        with mock.patch.object(diagnostics.os, 'replace', side_effect=verify_before_publish):
            target = diagnostics.create_diagnostics_package()
        self.assertEqual(checked, [target])
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_settings_and_calibration_json_reads_have_a_byte_budget(self):
        (self.base / 'settings-small.json').write_text('{"quality":"High"}', encoding='utf-8')
        (self.base / 'settings-huge.json').write_text('{"quality":"' + 'x' * 1000 + '"}', encoding='utf-8')
        (self.base / 'calibration-huge.json').write_text('{"version":"' + 'x' * 1000 + '"}', encoding='utf-8')
        with mock.patch.object(diagnostics, 'MAX_JSON_BYTES', 64):
            self.assertEqual(diagnostics._settings_summary(), {'settings-001.json': {'quality': 'High'}})
            self.assertEqual(diagnostics._calibration_summary(), {})

    def test_summary_file_count_is_bounded(self):
        for number in range(5):
            (self.base / f'settings-{number}.json').write_text('{"quality":"High"}', encoding='utf-8')
        with mock.patch.object(diagnostics, 'MAX_SUMMARY_FILES', 2):
            self.assertEqual(len(diagnostics._settings_summary()), 2)

    def test_linked_logs_and_settings_are_not_exported(self):
        with tempfile.TemporaryDirectory() as external:
            secret = Path(external) / 'private.txt'
            secret.write_text('{"quality":"PRIVATE-CONTENT"}', encoding='utf-8')
            logs = self.base / 'logs'
            logs.mkdir()
            try:
                (logs / 'ImageDrawBot-session.log').symlink_to(secret)
                (self.base / 'settings-linked.json').symlink_to(secret)
                (self.base / 'calibration-linked.json').symlink_to(secret)
            except OSError as error:
                self.skipTest(f'Filesystem does not permit test symlinks: {error}')
            target = diagnostics.create_diagnostics_package()
            with zipfile.ZipFile(target) as archive:
                self.assertNotIn('logs/ImageDrawBot-session.log', archive.namelist())
                self.assertEqual(json.loads(archive.read('settings-summary.json')), {})
                self.assertEqual(json.loads(archive.read('calibration-summary.json')), {})

    def test_linked_parent_directory_is_not_traversed(self):
        with tempfile.TemporaryDirectory() as external:
            target = Path(external) / 'ImageDrawBot-session.log'
            target.write_text('PRIVATE-CONTENT', encoding='utf-8')
            try:
                (self.base / 'logs').symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f'Filesystem does not permit test symlinks: {error}')
            with zipfile.ZipFile(diagnostics.create_diagnostics_package()) as archive:
                self.assertNotIn('logs/ImageDrawBot-session.log', archive.namelist())

    def test_consolidated_error_log_and_rotation_are_included_and_redacted(self):
        logs = self.base / 'logs'
        logs.mkdir()
        for suffix in ('', '.1'):
            (logs / f'ImageDrawBot-debug-errors.log{suffix}').write_text(
                'Error: Cookie: session=COOKIE_SECRET; tracking=TRACKING_SECRET\n', encoding='utf-8')
        with zipfile.ZipFile(diagnostics.create_diagnostics_package()) as archive:
            for suffix in ('', '.1'):
                value = archive.read(f'logs/ImageDrawBot-debug-errors.log{suffix}').decode('utf-8')
                self.assertIn('Error:', value)
                self.assertNotIn('COOKIE_SECRET', value)
                self.assertNotIn('TRACKING_SECRET', value)

    def test_calibration_version_cannot_export_arbitrary_nested_private_data(self):
        path = self.base / 'calibration.json'
        path.write_text(json.dumps({'version': {'private': 'PRIVATE-CONTENT'}, 'colors': [1, 2]}), encoding='utf-8')
        summary = diagnostics._calibration_summary()['calibration-001.json']
        self.assertIsNone(summary['version'])
        self.assertEqual(summary['color_count'], 2)
        path.write_text(json.dumps({'version': 'token=VERSION_SECRET ' + 'v' * 500}), encoding='utf-8')
        version = diagnostics._calibration_summary()['calibration-001.json']['version']
        self.assertNotIn('VERSION_SECRET', version)
        self.assertLessEqual(len(version), 200)

    def test_cookie_headers_are_redacted_without_breaking_json(self):
        for key in ('Cookie', 'Set-Cookie', 'cookie'):
            with self.subTest(header=key):
                raw = json.dumps({key: 'session=COOKIE_SECRET; token=MORE_SECRET', 'status': 403})
                cleaned = json.loads(sanitize_text(raw))
                self.assertEqual(cleaned, {key: '<redacted>', 'status': 403})
        cleaned = sanitize_text('Cookie: session=COOKIE_SECRET; token=MORE_SECRET\r\nHTTP 403\n')
        self.assertNotIn('COOKIE_SECRET', cleaned)
        self.assertNotIn('MORE_SECRET', cleaned)
        self.assertIn('HTTP 403', cleaned)

    def test_user_home_paths_on_other_drives_and_platforms_are_redacted(self):
        for path in (r'D:\Users\PrivatePerson\data.txt', 'E:/Users/PrivatePerson/data.txt',
                     '/home/PrivatePerson/data.txt', '/Users/PrivatePerson/data.txt'):
            with self.subTest(path=path):
                self.assertNotIn('PrivatePerson', sanitize_text(path))
        with mock.patch('LocalSanitization.Path.home', side_effect=RuntimeError('no home')):
            self.assertEqual(sanitize_text('HTTP 403'), 'HTTP 403')

    def test_nonfinite_context_never_creates_nonstandard_json(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value):
                context = safe_context({'ram_budget': value, 'cpu_workers': 4, 'palette_ready': True})
                self.assertNotIn('ram_budget', context)
                self.assertEqual(json.loads(json.dumps(context, allow_nan=False)), context)


class CrashLogMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {'LOG_DIR': self.base, 'SESSION_LOG': self.base / 'session.log',
                            'DEBUG_ERROR_LOG': self.base / 'errors.log', 'CRASH_LOG': self.base / 'crash.log'}.items():
            self.stack.enter_context(mock.patch.object(crash, name, value))

    def test_persisted_session_and_error_records_are_redacted_at_write_time(self):
        crash.log_error('Failed https://host.test/a?sig=SIGNED_SECRET\nAuthorization: Bearer AUTH_SECRET')
        for path in (crash.SESSION_LOG, crash.DEBUG_ERROR_LOG):
            contents = path.read_text(encoding='utf-8')
            self.assertNotIn('SIGNED_SECRET', contents)
            self.assertNotIn('AUTH_SECRET', contents)
            self.assertIn('Failed', contents)

    def test_record_limit_does_not_cut_away_secret_redaction_context(self):
        with mock.patch.object(crash, '_MAX_RECORD_CHARS', 128):
            crash.log_error('Failure ' + 'x' * 2000 + '\nhttps://host.test/a?sig=' + 'URL_SECRET' * 200)
        contents = crash.DEBUG_ERROR_LOG.read_text(encoding='utf-8')
        self.assertNotIn('URL_SECRET', contents)
        self.assertIn('[long log record truncated]', contents)
        self.assertLess(len(contents), 220)

    def test_incoming_record_rotates_before_crossing_the_file_budget(self):
        crash.SESSION_LOG.write_text('x' * 120, encoding='utf-8')
        rotate = crash._rotate_if_large
        with mock.patch.object(crash, '_rotate_if_large',
                side_effect=lambda path, **kw: rotate(path, limit=128, **kw)):
            crash.log_event('new event')
        self.assertEqual(crash.SESSION_LOG.with_suffix('.log.1').read_text(), 'x' * 120)
        self.assertIn('new event', crash.SESSION_LOG.read_text())

    def test_direct_concurrent_error_writes_hold_the_rotation_lock(self):
        lock = threading.RLock()
        rotate = crash._rotate_if_large
        observations = []
        def locked_rotation(*args, **kwargs):
            observations.append(lock._is_owned())
            return rotate(*args, **kwargs)
        with mock.patch.object(crash, '_LOG_LOCK', lock), \
                mock.patch.object(crash, '_rotate_if_large', side_effect=locked_rotation):
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(lambda number: crash._append_error(f'worker-{number:03d}'), range(80)))
        contents = crash.DEBUG_ERROR_LOG.read_text(encoding='utf-8')
        self.assertEqual(len(contents.splitlines()), 80)
        self.assertEqual(observations, [True] * 80)
        for number in range(80):
            self.assertEqual(contents.count(f'worker-{number:03d}'), 1)

    def test_unhandled_exception_log_is_redacted_before_it_is_persisted(self):
        with mock.patch.object(crash, '_INSTALLED', False), \
                mock.patch.object(crash, '_LOG_STREAM', None), \
                mock.patch.object(crash.faulthandler, 'enable'), \
                mock.patch.object(crash.sys, 'excepthook'), \
                mock.patch.object(crash.threading, 'excepthook'):
            crash.install()
            try:
                error = ValueError('request failed https://host.test/a?sig=EXCEPTION_SECRET')
                crash.sys.excepthook(type(error), error, None)
            finally:
                if crash._LOG_STREAM:
                    crash._LOG_STREAM.close()
        contents = crash.CRASH_LOG.read_text(encoding='utf-8')
        self.assertNotIn('EXCEPTION_SECRET', contents)
        self.assertIn('ValueError', contents)


if __name__ == '__main__':
    unittest.main()
