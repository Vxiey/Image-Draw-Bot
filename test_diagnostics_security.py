"""Regressions for local tool launching and shareable diagnostic logs."""
import json
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import requests
from urllib3 import HTTPSConnectionPool
from urllib3.exceptions import MaxRetryError

import DiagnosticsPackage as diagnostics
from DrawBot import DrawBotApp
from LocalSanitization import sanitize_text


class DiagnosticToolLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.app = SimpleNamespace(activity=None, status=Mock())

    def test_tool_paths_with_spaces_and_ampersands_are_literal_files(self):
        for folder in ('A&B', 'Folder With Spaces', 'A & B'):
            with self.subTest(folder=folder):
                path = self.base / folder / 'Enable-Crash-Dumps.bat'
                path.parent.mkdir()
                path.write_text('@echo off\n', encoding='utf-8')
                with patch.object(sys, 'platform', 'win32'), \
                        patch('RuntimePaths.resource_path', return_value=path), \
                        patch.object(os, 'startfile', create=True) as startfile, \
                        patch('subprocess.Popen', side_effect=AssertionError('No command shell should be constructed')):
                    DrawBotApp.launch_diagnostic_tool(self.app, path.name, 'Tool opened.')
                startfile.assert_called_once_with(str(path), 'open', cwd=str(path.parent))
                self.app.status.set.assert_called_with('Tool opened.')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows ShellExecute integration')
    def test_windows_shell_opens_batch_file_in_its_own_working_directory(self):
        for folder in ('Native&Ampersand', 'Native & Spaces'):
            with self.subTest(folder=folder):
                path = self.base / folder / 'diagnostic-probe.bat'
                path.parent.mkdir()
                marker = path.parent / 'working-directory.txt'
                # Synthetic batch file only: record cwd in its own temporary folder.
                path.write_text('@echo off\ncd > "%~dp0working-directory.txt"\nexit /b 0\n', encoding='utf-8')
                with patch('RuntimePaths.resource_path', return_value=path):
                    DrawBotApp.launch_diagnostic_tool(self.app, path.name, 'Tool opened.')
                self.app.status.set.assert_called_with('Tool opened.')
                deadline = time.monotonic() + 10
                while not marker.is_file() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.is_file(), 'Windows did not run the batch file at its literal path')
                time.sleep(0.1)  # Let the short-lived CMD process close its output and cwd handles.
                self.assertEqual(os.path.normcase(marker.read_text().strip()), os.path.normcase(str(path.parent)))

    def test_busy_app_does_not_resolve_or_launch_a_tool(self):
        self.app.activity = 'draw'
        with patch('RuntimePaths.resource_path') as resource, \
                patch.object(os, 'startfile', create=True) as startfile, \
                patch('subprocess.Popen') as process:
            DrawBotApp.launch_diagnostic_tool(self.app, 'Enable-Crash-Dumps.bat', 'Opened.')
        resource.assert_not_called()
        startfile.assert_not_called()
        process.assert_not_called()
        self.app.status.set.assert_not_called()

    def test_missing_tool_is_reported_without_launching(self):
        path = self.base / 'missing.bat'
        with patch.object(sys, 'platform', 'win32'), \
                patch('RuntimePaths.resource_path', return_value=path), \
                patch.object(os, 'startfile', create=True) as startfile, \
                patch('subprocess.Popen') as process:
            DrawBotApp.launch_diagnostic_tool(self.app, path.name, 'Opened.')
        startfile.assert_not_called()
        process.assert_not_called()
        self.assertIn('missing.bat is missing', self.app.status.set.call_args.args[0])

    def test_directory_with_tool_name_is_not_opened(self):
        path = self.base / 'Enable-Crash-Dumps.bat'
        path.mkdir()
        with patch.object(sys, 'platform', 'win32'), \
                patch('RuntimePaths.resource_path', return_value=path), \
                patch.object(os, 'startfile', create=True) as startfile, \
                patch('subprocess.Popen') as process:
            DrawBotApp.launch_diagnostic_tool(self.app, path.name, 'Opened.')
        startfile.assert_not_called()
        process.assert_not_called()
        self.assertIn('is missing', self.app.status.set.call_args.args[0])

    def test_non_windows_platform_reports_a_clear_error(self):
        path = self.base / 'Enable-Crash-Dumps.bat'
        path.write_text('@echo off\n', encoding='utf-8')
        with patch.object(sys, 'platform', 'linux'), \
                patch('RuntimePaths.resource_path', return_value=path), \
                patch.object(os, 'startfile', create=True) as startfile, \
                patch('subprocess.Popen') as process:
            DrawBotApp.launch_diagnostic_tool(self.app, path.name, 'Opened.')
        startfile.assert_not_called()
        process.assert_not_called()
        self.assertIn('Windows', self.app.status.set.call_args.args[0])

    def test_native_launch_failures_are_reported_without_fallback_shell(self):
        path = self.base / 'Enable-Crash-Dumps.bat'
        path.write_text('@echo off\n', encoding='utf-8')
        for error in (PermissionError('Access denied'), NotImplementedError('ShellExecute unavailable')):
            with self.subTest(error=type(error).__name__), \
                    patch.object(sys, 'platform', 'win32'), \
                    patch('RuntimePaths.resource_path', return_value=path), \
                    patch.object(os, 'startfile', create=True, side_effect=error), \
                    patch('subprocess.Popen') as process:
                DrawBotApp.launch_diagnostic_tool(self.app, path.name, 'Opened.')
            process.assert_not_called()
            self.assertIn(str(error), self.app.status.set.call_args.args[0])


class DiagnosticsSanitizationTests(unittest.TestCase):
    def test_prepared_urls_with_apostrophes_are_redacted_in_text_errors_and_json(self):
        for url in (
            "https://images.example.test/image.png?signature=first'LEAKED_SUFFIX",
            "https://images.example.test/o'connor.png?signature=PRIVATE_SUFFIX",
        ):
            with self.subTest(url=url):
                prepared = requests.Request('GET', url).prepare()
                self.assertEqual(prepared.url, url)
                response = requests.Response()
                response.status_code = 403
                response.reason = 'Forbidden'
                response.url = prepared.url
                with self.assertRaises(requests.HTTPError) as caught:
                    response.raise_for_status()
                for text in (prepared.url, str(caught.exception), repr(caught.exception)):
                    cleaned = sanitize_text(text)
                    self.assertNotIn('LEAKED_SUFFIX', cleaned)
                    self.assertNotIn('PRIVATE_SUFFIX', cleaned)
                    self.assertIn('images.example.test/', cleaned)
                logged = json.dumps({'url': prepared.url, 'status': 403, 'retry': False})
                cleaned = json.loads(sanitize_text(logged))
                self.assertEqual(cleaned['status'], 403)
                self.assertFalse(cleaned['retry'])
                self.assertNotIn('LEAKED_SUFFIX', cleaned['url'])
                self.assertNotIn('PRIVATE_SUFFIX', cleaned['url'])

    def test_requests_connection_error_relative_target_is_redacted(self):
        prepared = requests.Request(
            'GET', "https://images.example.test/o'connor.png?sig=first'RELATIVE_SECRET"
        ).prepare()
        pool = HTTPSConnectionPool('images.example.test')
        reason = MaxRetryError(pool, prepared.path_url, OSError('test connection failed'))
        error = requests.ConnectionError(reason)
        for text in (str(error), repr(error)):
            with self.subTest(text=text):
                cleaned = sanitize_text(text)
                self.assertNotIn('RELATIVE_SECRET', cleaned)
                self.assertIn('images.example.test', cleaned)
                self.assertIn("/o'connor.png", cleaned)
                self.assertIn('test connection failed', cleaned)

    def test_compact_json_url_does_not_absorb_later_at_sign_fields(self):
        for field, value, expected in (
            ('email', 'contact@example.org', 'contact@example.org'),
            ('password', 'secret@here', '<redacted>'),
        ):
            with self.subTest(field=field):
                payload = {'url': 'https://images.example.test', field: value, 'status': 403}
                cleaned = json.loads(sanitize_text(json.dumps(payload, separators=(',', ':'))))
                self.assertEqual(cleaned, {'url': payload['url'], field: expected, 'status': 403})

    def test_requests_http_error_keeps_context_but_removes_url_secrets(self):
        response = requests.Response()
        response.status_code = 403
        response.reason = 'Forbidden'
        response.url = ('https://image-user:image-password@images.example.test/picture.png'
                        '?X-Amz-Credential=private-credential&X-Amz-Signature=private-signature'
                        '#private-fragment')
        with self.assertRaises(requests.HTTPError) as caught:
            response.raise_for_status()
        cleaned = sanitize_text(f'Worker load failed: {caught.exception!r}')
        for secret in ('image-user', 'image-password', 'private-credential', 'private-signature', 'private-fragment'):
            self.assertNotIn(secret, cleaned)
        self.assertIn('403 Client Error: Forbidden', cleaned)
        self.assertIn('images.example.test/picture.png', cleaned)
        self.assertTrue(cleaned.endswith("')"))

    def test_all_url_query_values_and_fragments_are_redacted(self):
        values = (
            'https://blob.example.test/image.png?sig=azure-secret&sv=api-version',
            'HTTP://images.example.test/image.png?unfamiliar_key=custom-secret',
            'https://images.example.test/image.png#fragment-secret',
        )
        for value in values:
            with self.subTest(value=value):
                cleaned = sanitize_text(f'Download failed ({value}); retry later.')
                for secret in ('azure-secret', 'api-version', 'custom-secret', 'fragment-secret'):
                    self.assertNotIn(secret, cleaned)
                self.assertIn('/image.png', cleaned)
                self.assertTrue(cleaned.endswith('); retry later.'))

    def test_url_userinfo_is_redacted_even_without_query(self):
        for password in ('pass%40word', "pass'word"):
            with self.subTest(password=password):
                cleaned = sanitize_text(f'GET https://user-name:{password}@images.example.test:443/image.png failed')
                self.assertNotIn('user-name', cleaned)
                self.assertNotIn(password, cleaned)
                self.assertIn('https://<redacted>@images.example.test:443/image.png failed', cleaned)

    def test_basic_and_bearer_authorization_are_redacted(self):
        for value in (
            'Authorization: Basic ZmFrZTpmYWtlcGFzcw==',
            'Proxy-Authorization: Basic ZmFrZTpmYWtlcGFzcw==',
            'Authorization: Bearer example-bearer-value',
            '{"Authorization": "Basic ZmFrZTpmYWtlcGFzcw==", "status": 401}',
        ):
            with self.subTest(value=value):
                cleaned = sanitize_text(value)
                self.assertNotIn('ZmFrZTpmYWtlcGFzcw==', cleaned)
                self.assertNotIn('example-bearer-value', cleaned)
                self.assertIn('Authorization', cleaned)
                self.assertIn('<redacted>', cleaned)

    def test_quoted_and_unquoted_credentials_preserve_surrounding_fields(self):
        original = json.dumps({'token': 'token with spaces', 'api_key': 'private-key',
                               'password': 'private-password', 'status': 401})
        cleaned = json.loads(sanitize_text(original))
        self.assertEqual(cleaned, {'token': '<redacted>', 'api_key': '<redacted>',
                                  'password': '<redacted>', 'status': 401})
        self.assertEqual(sanitize_text('token=sample-token; api-key=sample-key; retry=2'),
                         'token=<redacted>; api-key=<redacted>; retry=2')

    def test_malformed_url_does_not_break_redaction(self):
        cleaned = sanitize_text('Invalid URL: https://[broken/image.png?sig=private-signature')
        self.assertNotIn('private-signature', cleaned)
        self.assertIn('Invalid URL:', cleaned)

    def test_ordinary_error_context_and_public_urls_are_preserved(self):
        original = 'HTTP 404 at https://images.example.test/picture.png; retry after 5 seconds.'
        self.assertEqual(sanitize_text(original), original)

    def test_home_path_redaction_does_not_split_a_url_before_secret_redaction(self):
        home = Path.home().as_posix()
        value = f'https://images.example.test{home}/image.png?sig=private-signature'
        cleaned = sanitize_text(value)
        self.assertNotIn('private-signature', cleaned)
        self.assertNotIn(home, cleaned)
        self.assertIn('images.example.test', cleaned)

    def test_exported_diagnostics_logs_do_not_contain_signed_url_or_basic_auth_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / 'logs').mkdir()
            (base / 'logs' / 'ImageDrawBot-session.log').write_text(
                '403 Forbidden: https://user-name:pass-value@images.example.test/image.png?sig=signed-secret\n'
                'Authorization: Basic ZmFrZTpmYWtlcGFzcw==\n', encoding='utf-8')
            with patch.object(diagnostics, 'DIAGNOSTICS_DIR', base / 'diagnostics'), \
                    patch.object(diagnostics, 'data_dir', return_value=base), \
                    patch.object(diagnostics, '_technical_info', return_value={'app': 'Image Draw Bot'}), \
                    patch.dict(os.environ, {'LOCALAPPDATA': str(base)}):
                path = diagnostics.create_diagnostics_package()
            with zipfile.ZipFile(path) as archive:
                contents = archive.read('logs/ImageDrawBot-session.log').decode('utf-8')
            for secret in ('user-name', 'pass-value', 'signed-secret', 'ZmFrZTpmYWtlcGFzcw=='):
                self.assertNotIn(secret, contents)
            self.assertIn('403 Forbidden', contents)
            self.assertIn('images.example.test/image.png', contents)


class DiagnosticsBoundedLogTests(unittest.TestCase):
    def read_log(self, content, limit=30):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'session.log'
            path.write_bytes(content.encode('utf-8'))
            return diagnostics._read_text(path, limit=limit)

    def test_redaction_precedes_final_character_tail(self):
        # The complete URL fits in the byte budget, but its secret occupies the
        # final 30 characters. Truncating to 30 before redaction loses "https:".
        value = 'https://img.test/a?signature=' + 'LEAKED_SUFFIX' * 5
        self.assertLess(len(value), 30 * 4)
        cleaned = self.read_log(value)
        self.assertNotIn('LEAKED_SUFFIX', cleaned)
        self.assertIn('<redacted>', cleaned)

    def test_partial_first_line_is_discarded_and_later_lines_remain(self):
        value = 'https://img.test/a?signature=' + 'LEAKED_SUFFIX' * 30 + '\nHTTP 403; retry later.\n'
        cleaned = self.read_log(value)
        self.assertNotIn('LEAKED_SUFFIX', cleaned)
        self.assertIn('HTTP 403; retry later.', cleaned)
        self.assertIn('[older content omitted]', cleaned)

    def test_long_unterminated_line_is_omitted_completely(self):
        for ending in ('', '\n'):
            with self.subTest(ending=ending):
                value = 'Authorization: Basic ' + 'LEAKED_SUFFIX' * 30 + ending
                self.assertEqual(self.read_log(value), '[older content omitted]\n')

    def test_complete_line_at_exact_byte_boundary_is_retained_and_redacted(self):
        last_line = 'url: /a?sig=SECRET_VALUE'
        prefix = 'old line\n'
        # Choose a limit that makes the final buffer begin immediately after LF.
        limit = 24
        last_line = last_line + 'X' * (limit * 4 - len(last_line))
        cleaned = self.read_log(prefix + last_line, limit=limit)
        self.assertNotIn('SECRET_VALUE', cleaned)
        self.assertEqual(cleaned, '[older content omitted]\nurl: /a?<redacted>')

    def test_multibyte_cut_does_not_export_a_secret_fragment(self):
        value = 'https://img.test/a?sig=' + 'ÅLEAKED_SUFFIX' * 30 + '\nUseful final error.\n'
        cleaned = self.read_log(value)
        self.assertNotIn('LEAKED_SUFFIX', cleaned)
        self.assertIn('Useful final error.', cleaned)

    def test_log_read_stays_bounded_even_when_there_is_no_newline(self):
        class BoundedStream(BytesIO):
            def read(self, size=-1):
                if size < 0 or size > 120:
                    raise AssertionError('Diagnostics must not read an unbounded log line')
                return super().read(size)
        stream = BoundedStream(b'url: /image?sig=' + b'LEAKED_SUFFIX' * 100)
        path = Mock()
        path.open.return_value = stream
        self.assertEqual(diagnostics._read_text(path, limit=30), '[older content omitted]\n')


if __name__ == '__main__':
    unittest.main()
