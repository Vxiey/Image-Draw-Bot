from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import CrashDiagnostics as crash
import DiagnosticsPackage as diagnostics
import LocalSanitization as sanitization
import SessionRecovery as recovery


class StorageDiagnosticsBatch02Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_every_authorization_scheme_is_private_and_quoted_json_stays_valid(self):
        values = ['Negotiate NEGOTIATE_SECRET', 'NTLM NTLM_SECRET', 'Token TOKEN_SECRET',
                  'Digest username="PRIVATE_USER", realm="realm", response="PRIVATE_RESPONSE"',
                  'AWS4-HMAC-SHA256 Credential=PRIVATE_KEY/region, Signature=PRIVATE_SIGNATURE']
        for value in values:
            for key in ('Authorization', 'Proxy-Authorization'):
                with self.subTest(value=value, key=key):
                    original = json.dumps({key: value, 'status': 401}, separators=(',', ':'))
                    clean = json.loads(sanitization.sanitize_text(original))
                    self.assertEqual(clean, {key: '<redacted>', 'status': 401})
                    clean = sanitization.sanitize_text(f'{key}: {value}\r\nHTTP 401')
                    self.assertEqual(clean, f'{key}: <redacted>\r\nHTTP 401')

    def test_recovery_profile_credentials_never_enter_the_shareable_system_summary(self):
        state = self.root / 'state.json'
        state.write_text(json.dumps({'schema': 3, 'profile': 'https://private.test/?sig=PROFILE_SECRET',
                                    'created_at': 'token=TIME_SECRET', 'options': {}, 'has_image': False}))
        with patch.object(recovery, 'STATE_FILE', state), patch.object(recovery, 'RENDER_FILE', self.root / 'none'), \
             patch.object(diagnostics, 'data_dir', return_value=self.root), \
             patch.object(diagnostics, 'DIAGNOSTICS_DIR', self.root / 'diagnostics'), \
             patch.object(diagnostics, '_package_versions', return_value={}), \
             patch.object(diagnostics, '_memory_total_mb', return_value=None), \
             patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)}):
            path = diagnostics.create_diagnostics_package()
        with zipfile.ZipFile(path) as archive:
            system = archive.read('system.json').decode()
        self.assertNotIn('PROFILE_SECRET', system)
        self.assertNotIn('TIME_SECRET', system)
        self.assertIn('<redacted>', system)
        self.assertEqual(json.loads(system)['recovery']['restores_armed_state'], False)

    def test_summary_selection_keeps_only_a_bounded_number_of_path_objects(self):
        counts = {'live': 0, 'peak': 0}
        class Candidate:
            def __init__(self, number):
                self.number = number
                counts['live'] += 1
                counts['peak'] = max(counts['peak'], counts['live'])
            def __lt__(self, other):
                return self.number < other.number
            def __del__(self):
                counts['live'] -= 1
        paths = (Candidate(number) for number in range(200, 0, -1))
        with patch.object(diagnostics, 'data_dir', return_value=self.root), \
             patch.object(diagnostics, 'MAX_SUMMARY_FILES', 3), \
             patch.object(Path, 'glob', return_value=paths), \
             patch.object(diagnostics, '_json_input', return_value=None):
            self.assertEqual(diagnostics._settings_summary(), {})
        self.assertLess(counts['peak'], 10)

    def test_rotation_failure_does_not_turn_a_bounded_log_into_unbounded_append(self):
        log = self.root / 'session.log'
        log.write_bytes(b'x' * 128)
        rotate = crash._rotate_if_large
        with patch.object(crash, 'LOG_DIR', self.root), patch.object(crash, 'SESSION_LOG', log), \
             patch.object(crash, '_rotate_if_large', side_effect=lambda path, **kw: rotate(path, limit=128, **kw)), \
             patch.object(crash.os, 'replace', side_effect=PermissionError('backup is open')):
            for _ in range(20):
                crash.log_event('another event')
        self.assertEqual(log.read_bytes(), b'x' * 128)

    def test_python_crash_records_keep_the_native_handler_descriptor_and_budget(self):
        path = self.root / 'crash.log'
        with path.open('a', encoding='utf-8') as stream, \
             patch.object(crash, '_LOG_STREAM', stream), patch.object(crash, '_MAX_LOG_BYTES', 128):
            descriptor = stream.fileno()
            for _ in range(20):
                crash._write_crash_record('exception detail\n')
            self.assertEqual(stream.fileno(), descriptor)
            self.assertFalse(stream.closed)
            self.assertLessEqual(path.stat().st_size, 128)
            self.assertGreater(path.stat().st_size, 0)

    def test_oversized_run_marker_is_not_read_unbounded_or_deleted_as_owned(self):
        path = self.root / 'running.marker'
        path.write_bytes(f'pid={os.getpid()} '.encode() + b'x' * 5000)
        requests = []
        original = Path.open
        class ReadBudget:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def read(self, size=-1):
                requests.append(size)
                return self.stream.read(size)
        def open_marker(target, *args, **kwargs):
            stream = original(target, *args, **kwargs)
            return ReadBudget(stream) if target == path else stream
        with patch.object(crash, 'RUN_MARKER', path), patch.object(crash, 'RUN_MARKER_OWNED', True), \
             patch.object(crash, 'log_event'), patch.object(Path, 'open', open_marker):
            crash.clean_exit()
        self.assertEqual(requests, [1025])
        self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
