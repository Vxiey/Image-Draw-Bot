"""Updater regressions: bounded I/O, cancellation and verified Windows handoff."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import UpdateCenter as update
from test_update_security import DATA, NAME, TAG, DOWNLOAD, release


class Response:
    status_code = 200
    url = update.GITHUB_RELEASES_API

    def __init__(self, content=b'[]', headers=None):
        self.content = content
        self.headers = headers or {}
        self.closed = False
        self.read = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def iter_content(self, chunk_size):
        self.read = True
        yield self.content

    def close(self):
        self.closed = True


class UpdateMaintenanceTests(unittest.TestCase):
    def test_cancelled_check_never_contacts_github(self):
        get = Mock()
        with self.assertRaises(InterruptedError):
            update.check_for_updates(request_get=get, cancelled=lambda: True)
        get.assert_not_called()

    def test_cancel_between_chunks_closes_response_and_preserves_cancellation(self):
        response = Response()
        stopped = [False]

        def chunks(chunk_size):
            yield b'['
            stopped[0] = True
            yield b']'

        response.iter_content = chunks
        with self.assertRaises(InterruptedError):
            update.check_for_updates(request_get=lambda *a, **kw: response,
                                     cancelled=lambda: stopped[0])
        self.assertTrue(response.closed)

    def test_stream_budget_is_checked_between_response_chunks(self):
        response = Response()
        clock = [0]

        def chunks(chunk_size):
            yield b'['
            clock[0] = update._MAX_RELEASE_CHECK_SECONDS + 1
            yield b']'

        response.iter_content = chunks
        with patch.object(update.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(update.UpdateCheckError, 'timed out'):
                update.check_for_updates(request_get=lambda *a, **kw: response)
        self.assertTrue(response.closed)

    def test_version_prefix_is_case_insensitive_but_digits_are_ascii(self):
        self.assertEqual(update.normalize_tag(' V2.3.4-RC2 '), '2.3.4-RC2')
        self.assertEqual(update.parse_version('V2.3.4-RC2'), update.parse_version('v2.3.4-rc2'))
        self.assertIsNone(update.parse_version('v２.3.4'))

    def test_release_page_cannot_be_redirected_by_metadata(self):
        for url in ('javascript:alert(1)', 'https://example.com/install',
                    'https://github.com/other/repo/releases/tag/v99.0.0'):
            with self.subTest(url=url):
                item = dict(release(), html_url=url)
                response = Response(json.dumps([item]).encode())
                result = update.check_for_updates(request_get=lambda *a, **kw: response)
                self.assertEqual(result['release_url'], update.GITHUB_RELEASES_PAGE + '/tag/' + TAG)

    def test_only_fully_uploaded_installer_assets_are_offered(self):
        for state in ('new', 'starter', None, 'deleted'):
            item = release()
            item['assets'][0]['state'] = state
            self.assertIsNone(update.installer_asset(item))
        item['assets'][0]['state'] = 'uploaded'
        self.assertIsNotNone(update.installer_asset(item))

    def test_disk_space_failure_precedes_network_and_partial_file(self):
        get = Mock()
        with tempfile.TemporaryDirectory() as tmp, patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(update.UpdateCheckError, 'free space'):
                update.download_installer(update.installer_asset(release()), directory=tmp, request_get=get)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        get.assert_not_called()

    def test_invalid_transfer_envelopes_fail_before_reading_binary(self):
        cases = ({'Content-Length': str(len(DATA) + 1)}, {'Content-Length': '-1'},
                 {'Content-Length': '12, 12'}, {'Content-Encoding': 'gzip'})
        for headers in cases:
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as tmp:
                response = Response(DATA, headers)
                response.url = DOWNLOAD
                with self.assertRaises(update.UpdateCheckError):
                    update.download_installer(update.installer_asset(release()), directory=tmp,
                                              request_get=lambda *a, **kw: response)
                self.assertFalse(response.read)
                self.assertTrue(response.closed)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_github_rate_limit_is_actionable_and_response_is_closed(self):
        response = Response(headers={'Retry-After': '60', 'X-RateLimit-Remaining': '0'})
        response.status_code = 403
        with self.assertRaisesRegex(update.UpdateCheckError, 'Retry in 60 seconds.*Releases page'):
            update.check_for_updates(request_get=lambda *a, **kw: response)
        self.assertTrue(response.closed)
        self.assertFalse(response.read)


@unittest.skipUnless(os.name == 'nt', 'Windows file-sharing semantics')
class LockedInstallerTests(unittest.TestCase):
    def test_read_locked_executable_remains_launchable_by_windows(self):
        executable = Path(sys.executable).resolve(strict=True)
        with update._open_locked_installer(executable):
            result = subprocess.run(
                [str(executable), '-I', '-c', "print('locked-launch-ok')"],
                capture_output=True, text=True, timeout=15, check=True,
            )
        self.assertEqual(result.stdout.strip(), 'locked-launch-ok')

    def test_locked_verification_prevents_modification_and_replacement_at_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'verified.exe'
            target.write_bytes(DATA)
            replacement = Path(tmp) / 'replacement.exe'
            replacement.write_bytes(b'MZchanged')
            seen = []

            def launcher(args):
                self.assertEqual(Path(args[0]), target.resolve())
                with self.assertRaises(OSError):
                    target.write_bytes(b'MZmodified')
                with self.assertRaises(OSError):
                    replacement.replace(target)
                seen.append(target.read_bytes())
                return 'launched'

            self.assertEqual(update.launch_installer(target, update.installer_asset(release()), launcher=launcher), 'launched')
            self.assertEqual(seen, [DATA])
            target.write_bytes(b'released')

    def test_invalid_metadata_or_wrong_size_never_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'verified.exe'
            target.write_bytes(DATA)
            launcher = Mock()
            with self.assertRaises(update.UpdateCheckError):
                update.launch_installer(target, {'size': len(DATA), 'sha256': hashlib.sha256(DATA).hexdigest()}, launcher=launcher)
            target.write_bytes(DATA + b'extra')
            with self.assertRaises(update.UpdateCheckError):
                update.launch_installer(target, update.installer_asset(release()), launcher=launcher)
            launcher.assert_not_called()


if __name__ == '__main__':
    unittest.main()
