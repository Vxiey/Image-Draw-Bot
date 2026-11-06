"""Invalid helper output and all-or-nothing registry preflight regressions."""
from contextlib import ExitStack, nullcontext
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import CrashDumpConfig as dumps
import TargetCapture as target


class TargetMetadataMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.patch = mock.patch.object(target, 'BASE', Path(self.temporary.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def payload(self, **changes):
        value = {'ok': True, 'handle': 123, 'rect': [-300, 0, 300, 400],
                 'client_rect': [-290, 30, 290, 390], 'target_pid': 456,
                 'dpi': 144, 'dpi_scale': 1.5}
        value.update(changes)
        return value

    def run_payload(self, value):
        result = SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr='')
        with mock.patch.object(target.subprocess, 'run', return_value=result):
            return target._run(['synthetic-helper'])

    def test_valid_negative_monitor_coordinates_remain_supported(self):
        result = self.run_payload(self.payload())
        self.assertEqual(result['rect'], (-300, 0, 300, 400))
        self.assertEqual(result['dpi_scale'], 1.5)

    def test_non_object_payloads_raise_a_controlled_helper_error(self):
        for value in (None, [], 'text', 123, True, {}):
            with self.subTest(value=value), self.assertRaisesRegex(OSError, 'no valid response'):
                self.run_payload(value)

    def test_handles_and_process_ids_reject_booleans_zero_and_overflow(self):
        for key, values in {'handle': (True, 0, -1, 2**64, '123'),
                            'target_pid': (True, 0, -1, 2**32, '456')}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(OSError):
                    self.run_payload(self.payload(**{key: value}))

    def test_target_rectangles_require_real_coordinates_and_positive_area(self):
        for rect in ([True, 0, 10, 20], [10, 0, 0, 20], [0, 0, 0, 10],
                     [0, 5, 10, 5], [-(2**31)-1, 0, 10, 20], [0, 0, 2**31, 20]):
            for key in ('rect', 'client_rect'):
                with self.subTest(key=key, rect=rect), self.assertRaises(OSError):
                    self.run_payload(self.payload(**{key: rect}))

    def test_inconsistent_or_nonfinite_dpi_scale_is_rejected(self):
        for scale in (True, 0, float('nan'), float('inf'), 10**1000, 1.0, '1.5'):
            with self.subTest(scale=scale), self.assertRaises(OSError):
                self.run_payload(self.payload(dpi_scale=scale))

    def test_optional_bad_monitor_rectangles_are_dropped(self):
        result = self.run_payload(self.payload(monitor_rect=[0, 0, 0, 0],
                                               monitor_work_rect=[False, 0, 10, 20]))
        self.assertIsNone(result['monitor_rect'])
        self.assertIsNone(result['monitor_work_rect'])

    def test_handle_probe_cannot_return_a_different_target(self):
        with mock.patch.object(target, '_run', return_value=self.payload(handle=999)):
            with self.assertRaisesRegex(OSError, 'different target window'):
                target.probe_handle_isolated(123)
        with mock.patch.object(target, '_run') as run:
            for handle in (True, 0, -1, 2**64):
                with self.subTest(handle=handle), self.assertRaises(ValueError):
                    target.probe_handle_isolated(handle)
            run.assert_not_called()


class FakeRegistry:
    KEY_READ = 1
    KEY_WRITE = 2
    KEY_WOW64_64KEY = 4
    REG_SZ = 1
    REG_EXPAND_SZ = 2
    REG_DWORD = 4
    HKEY_LOCAL_MACHINE = object()

    def __init__(self):
        self.values = {}
        self.mutations = []
        self.before_write = lambda: None

    def name(self, path):
        prefix = dumps.REG_BASE + '\\'
        if not path.startswith(prefix):
            raise AssertionError('Only application LocalDumps keys may be used')
        return path[len(prefix):]

    def OpenKey(self, hive, path, *args):
        name = self.name(path)
        if name not in self.values:
            raise FileNotFoundError(name)
        return nullcontext(name)

    def CreateKeyEx(self, hive, path, *args):
        self.before_write()
        name = self.name(path)
        self.mutations.append(('create', name))
        self.values.setdefault(name, {})
        return nullcontext(name)

    def QueryValueEx(self, name, value):
        if value not in self.values[name]:
            raise FileNotFoundError(value)
        pair = self.values[name][value]
        return pair[0], pair[1]

    def SetValueEx(self, name, value_name, reserved, kind, value):
        self.mutations.append(('set', name, value_name))
        self.values[name][value_name] = [value, kind]

    def DeleteValue(self, name, value_name):
        if value_name not in self.values[name]:
            raise FileNotFoundError(value_name)
        self.mutations.append(('delete', name, value_name))
        del self.values[name][value_name]


class LocalDumpsMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.folder = self.base / 'ImageDrawBot' / 'dumps'
        self.folder.mkdir(parents=True)
        self.backup = self.folder / 'localdumps-backup.json'
        self.registry = FakeRegistry()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(dumps.sys.modules, {'winreg': self.registry}))
        self.stack.enter_context(mock.patch.object(dumps.sys, 'platform', 'win32'))
        self.stack.enter_context(mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.base)}))
        self.stack.enter_context(mock.patch.object(dumps, 'load_system_library',
                                                  return_value=SimpleNamespace(IsUserAnAdmin=mock.Mock(return_value=1))))

    def written(self):
        return {'DumpFolder': [dumps.DUMP_FOLDER_TEMPLATE, self.registry.REG_EXPAND_SZ],
                'DumpCount': [5, self.registry.REG_DWORD], 'DumpType': [1, self.registry.REG_DWORD]}

    def saved(self, original=None):
        return {'original': {} if original is None else original, 'written': self.written()}

    def test_invalid_later_backup_entry_causes_zero_registry_mutations(self):
        for bad_name, saved in (('cmd.exe', self.saved()),
                                ('python.exe', {'original': {}, 'written': {}}),
                                ('python.exe', {'original': {'DumpCount': ['five', 4]}, 'written': self.written()})):
            self.registry.values['ImageDrawBot.exe'] = self.written()
            state = {'ImageDrawBot.exe': self.saved(), bad_name: saved}
            self.backup.write_text(json.dumps(state), encoding='utf-8')
            with self.subTest(name=bad_name, saved=saved), self.assertRaises(ValueError):
                dumps.configure('disable')
            self.assertEqual(self.registry.mutations, [])
            self.assertEqual(json.loads(self.backup.read_text()), state)

    def test_enable_preflights_changed_later_configuration_before_adding_first_key(self):
        self.backup.write_text(json.dumps({'python.exe': self.saved()}), encoding='utf-8')
        changed = self.written()
        changed['DumpCount'] = [9, self.registry.REG_DWORD]
        self.registry.values['python.exe'] = changed
        with self.assertRaisesRegex(RuntimeError, 'settings changed'):
            dumps.configure('enable', include_python=True)
        self.assertEqual(self.registry.mutations, [])

    def test_enable_preflights_unrestorable_original_types_for_all_targets(self):
        self.registry.values['pythonw.exe'] = {'DumpCount': ['wrong type', self.registry.REG_SZ]}
        with self.assertRaises(ValueError):
            dumps.configure('enable', include_python=True)
        self.assertEqual(self.registry.mutations, [])
        self.assertFalse(self.backup.exists())

    def test_valid_enable_persists_undo_state_before_registry_write(self):
        def verify_backup():
            self.assertEqual(json.loads(self.backup.read_text()), {'ImageDrawBot.exe': self.saved()})
        self.registry.before_write = verify_backup
        dumps.configure('enable')
        self.assertEqual(self.registry.values, {'ImageDrawBot.exe': self.written()})
        self.assertTrue(all(row[1] == 'ImageDrawBot.exe' for row in self.registry.mutations))

    def test_disable_restores_owned_values_and_preserves_external_changes(self):
        saved = self.saved({'DumpCount': [9, 4], 'DumpType': [2, 4]})
        self.backup.write_text(json.dumps({'ImageDrawBot.exe': saved}), encoding='utf-8')
        current = self.written()
        current.update({'DumpCount': [7, 4], 'OtherToolValue': ['kept', 1]})
        self.registry.values['ImageDrawBot.exe'] = current
        dumps.configure('disable')
        self.assertEqual(self.registry.values['ImageDrawBot.exe'],
                         {'DumpCount': [7, 4], 'DumpType': [2, 4], 'OtherToolValue': ['kept', 1]})
        self.assertEqual(json.loads(self.backup.read_text()), {})

    def test_oversized_backup_is_rejected_before_any_registry_mutation(self):
        self.backup.write_bytes(b' ' * 100)
        with mock.patch.object(dumps, 'MAX_BACKUP_BYTES', 20), self.assertRaisesRegex(ValueError, 'too large'):
            dumps.configure('disable')
        self.assertEqual(self.registry.mutations, [])


if __name__ == '__main__':
    unittest.main()
