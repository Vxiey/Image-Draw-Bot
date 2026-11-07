from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import CrashDumpConfig as dumps
from test_native_safety_maintenance_rc4 import FakeRegistry


class LocalDumpsTransactionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.registry = FakeRegistry()
        self.initial = {'DumpFolder': ['original-location', 2], 'DumpCount': [9, 4], 'DumpType': [2, 4]}
        self.registry.values['ImageDrawBot.exe'] = dict(self.initial)
        self.stack.enter_context(patch.dict(dumps.sys.modules, {'winreg': self.registry}))
        self.stack.enter_context(patch.object(dumps.sys, 'platform', 'win32'))
        self.stack.enter_context(patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)}))
        self.stack.enter_context(patch.object(dumps, 'load_system_library', return_value=SimpleNamespace(IsUserAnAdmin=Mock(return_value=1))))
        self.backup = self.root / 'ImageDrawBot/dumps/localdumps-backup.json'

    def test_disable_cannot_consume_undo_before_enable_publishes_its_values(self):
        enabled_before_write, resume_enable, disable_entered, disable_finished = (threading.Event() for _ in range(4))
        failures = []
        def before_write():
            if threading.current_thread().name == 'dump-enable':
                enabled_before_write.set()
                if not resume_enable.wait(3):
                    raise TimeoutError('fixture coordination timeout')
        self.registry.before_write = before_write
        transaction = dumps.file_transaction
        def monitored_transaction(*args, **kwargs):
            if threading.current_thread().name == 'dump-disable':
                disable_entered.set()
            return transaction(*args, **kwargs)
        def invoke(action):
            try:
                dumps.configure(action)
            except BaseException as error:
                failures.append(error)
            finally:
                if action == 'disable':
                    disable_finished.set()
        enable = threading.Thread(target=invoke, args=('enable',), name='dump-enable', daemon=True)
        disable = threading.Thread(target=invoke, args=('disable',), name='dump-disable', daemon=True)
        with patch.object(dumps, 'file_transaction', side_effect=monitored_transaction):
            enable.start()
            try:
                self.assertTrue(enabled_before_write.wait(3))
                self.assertIn('ImageDrawBot.exe', json.loads(self.backup.read_text()))
                disable.start()
                self.assertTrue(disable_entered.wait(3))
                self.assertFalse(disable_finished.wait(.1), 'Disable must wait until Enable finishes its undo-backed write')
            finally:
                resume_enable.set()
                enable.join(3)
                if disable.ident is not None:
                    disable.join(3)
        self.assertFalse(enable.is_alive())
        self.assertFalse(disable.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(self.registry.values['ImageDrawBot.exe'], self.initial)
        self.assertEqual(json.loads(self.backup.read_text()), {})

    def test_failed_registry_write_releases_transaction_and_keeps_recoverable_undo(self):
        original_set = self.registry.SetValueEx
        def fail_count(name, value_name, reserved, kind, value):
            if value_name == 'DumpCount':
                raise PermissionError('injected registry write failure')
            return original_set(name, value_name, reserved, kind, value)
        with patch.object(self.registry, 'SetValueEx', side_effect=fail_count):
            with self.assertRaisesRegex(PermissionError, 'registry write'):
                dumps.configure('enable')
        self.assertEqual(json.loads(self.backup.read_text())['ImageDrawBot.exe']['original'], self.initial)
        dumps.configure('disable')
        self.assertEqual(self.registry.values['ImageDrawBot.exe'], self.initial)
        self.assertEqual(json.loads(self.backup.read_text()), {})


if __name__ == '__main__':
    unittest.main()
