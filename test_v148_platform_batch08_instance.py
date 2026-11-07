"""The existing instance guard uses the shared system-only DLL loader."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import InstanceLock


class InstanceSystemLoaderTests(unittest.TestCase):
    def test_shared_loader_preserves_mutex_identity_and_idempotent_close(self):
        for last_error, expected in ((0, False), (183, True)):
            with self.subTest(last_error=last_error):
                api = SimpleNamespace(CreateMutexW=Mock(return_value=42), CloseHandle=Mock(return_value=1))
                with patch.object(InstanceLock, 'load_system_library', return_value=api) as loader, \
                        patch.object(InstanceLock.ctypes, 'get_last_error', return_value=last_error, create=True):
                    lock = InstanceLock.InstanceLock()
                loader.assert_called_once_with('kernel32', use_last_error=True)
                api.CreateMutexW.assert_called_once_with(None, False, 'Local\\ImageDrawBot.SingleInstance')
                self.assertEqual(lock.already_running, expected)
                lock.close(); lock.close()
                api.CloseHandle.assert_called_once_with(42)
                self.assertIsNone(lock.handle)

    def test_system_loader_failure_never_falls_back_to_a_bare_library(self):
        with patch.object(InstanceLock, 'load_system_library', side_effect=OSError('system loader failed')), \
                patch.object(InstanceLock.ctypes, 'WinDLL', create=True) as bare:
            with self.assertRaisesRegex(OSError, 'system loader failed'):
                InstanceLock.InstanceLock()
        bare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
