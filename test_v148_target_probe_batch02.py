"""Native helper ownership metadata with mocked read-only Win32 responses."""
import io
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock,patch

import TargetProbe


class TargetMetadataTests(unittest.TestCase):
    def monitor(self):
        api=Mock()
        def process(handle,pid):
            pid._obj.value=777
            return 3
        api.GetWindowThreadProcessId.side_effect=process
        api.GetAncestor.return_value=100
        api.IsWindow.return_value=True
        monitor=Mock(api=api)
        monitor.rectangle.return_value=(0,0,800,600)
        monitor.client_rectangle.return_value=(0,30,800,600)
        monitor.dpi_info.return_value=SimpleNamespace(dpi=96,scale=1,source='window',
                                                     monitor_rect=None,work_rect=None)
        return monitor

    def run_probe(self,monitor):
        with patch('Colors.enable_dpi_awareness'),patch('ScreenGuard.WindowMonitor',return_value=monitor), \
             patch('TargetProbe.emit') as emit,redirect_stderr(io.StringIO()):
            code=TargetProbe.main(['--handle','200'])
        return code,emit.call_args.args[0]

    def test_owned_dialog_keeps_its_actual_window_and_root_owner_identity(self):
        monitor=self.monitor();code,payload=self.run_probe(monitor)
        self.assertEqual(code,0);self.assertEqual(payload['handle'],200)
        self.assertEqual(payload['owner_root_handle'],100)
        monitor.api.GetAncestor.assert_called_once_with(200,3)

    def test_disappearing_window_cannot_return_a_successful_probe(self):
        monitor=self.monitor();monitor.api.GetWindowThreadProcessId.side_effect=lambda *_:0
        code,payload=self.run_probe(monitor)
        self.assertEqual(code,2);self.assertFalse(payload['ok'])
        self.assertIn('process',payload['error'])

    def test_missing_root_owner_fails_without_inventing_identity(self):
        monitor=self.monitor();monitor.api.GetAncestor.return_value=None
        code,payload=self.run_probe(monitor)
        self.assertEqual(code,2);self.assertFalse(payload['ok'])
        self.assertIn('ownership',payload['error'])


if __name__=='__main__':unittest.main()
