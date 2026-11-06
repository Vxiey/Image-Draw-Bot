import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import UpdateCenter as update
from test_update_security import DATA, DOWNLOAD, release
from test_update_maintenance_rc4 import Response


class StorageUpdateBatch02Tests(unittest.TestCase):
    def test_response_cleanup_failure_does_not_hide_rate_limit_or_cancellation(self):
        response = Response(headers={'Retry-After': '10'})
        response.status_code = 429
        response.close = Mock(side_effect=OSError('close failed'))
        with patch('CrashDiagnostics.log_error') as log:
            with self.assertRaisesRegex(update.UpdateCheckError, 'request limit'):
                update.check_for_updates(request_get=lambda *args, **kwargs: response)
        log.assert_called_once()
        self.assertNotIn('https://', log.call_args.args[0])

    def test_download_stream_construction_failure_closes_raw_descriptor(self):
        with tempfile.TemporaryDirectory() as td:
            closed = []
            original = os.close
            def close(fd):
                closed.append(fd)
                return original(fd)
            with patch.object(os, 'fdopen', side_effect=OSError('buffer allocation failed')), \
                 patch.object(os, 'close', side_effect=close), \
                 patch.object(update, '_get_trusted_response') as get:
                with self.assertRaisesRegex(OSError, 'buffer allocation'):
                    update.download_installer(update.installer_asset(release()), directory=td)
            self.assertEqual(len(closed), 1)
            with self.assertRaises(OSError):
                os.fstat(closed[0])
            get.assert_not_called()
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_staging_delete_failure_preserves_the_original_download_error(self):
        with tempfile.TemporaryDirectory() as td:
            response = Response(DATA + b'excess')
            response.url = DOWNLOAD
            original = Path.unlink
            def fail_part(path, *args, **kwargs):
                if path.suffix == '.part':
                    raise PermissionError('staging file locked')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'unlink', fail_part):
                with self.assertRaisesRegex(update.UpdateCheckError, 'exceeds its published size') as caught:
                    update.download_installer(update.installer_asset(release()), directory=td,
                                              request_get=lambda *args, **kwargs: response)
            self.assertTrue(response.closed)
            self.assertIn('PermissionError', ' '.join(caught.exception.__notes__))
            self.assertFalse(list(Path(td).glob('*.exe')))

    def test_deadline_expiring_during_the_last_progress_callback_blocks_publication(self):
        with tempfile.TemporaryDirectory() as td:
            response = Response(DATA)
            response.url = DOWNLOAD
            clock = [0]
            def progress(*args):
                clock[0] = 1801
            with patch.object(update.time, 'monotonic', side_effect=lambda: clock[0]):
                with self.assertRaisesRegex(update.UpdateCheckError, 'timed out'):
                    update.download_installer(update.installer_asset(release()), directory=td,
                        request_get=lambda *args, **kwargs: response, progress=progress)
            self.assertTrue(response.closed)
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
