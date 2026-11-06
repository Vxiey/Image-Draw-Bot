"""Exercise readable Paint script transport without accessing Paint or desktop input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from PaintPreparation import _automation_script, _powershell_json_literal, _run_powershell


class PaintScriptTransportTests(unittest.TestCase):
    def setUp(self):
        # Portable process-transport tests inject the OS directory; the Windows
        # integration class below exercises real GetSystemDirectoryW calls.
        patcher=patch('PaintPreparation.system_directory',return_value=Path('/trusted/System32'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture_process(self, process, captured):
        def launch(args, **kwargs):
            captured['args']=args
            captured.update(kwargs)
            captured['source']=kwargs['stdin'].read()
            kwargs['stdin'].seek(0)
            return process
        return launch

    def test_readable_source_uses_file_input_without_command_line_payload(self):
        process=Mock(returncode=0)
        process.communicate.return_value=(b'[]',b'')
        process.poll.return_value=0
        captured={}
        source=_automation_script(42,element={'name':"Redigera färger 'quoted'",'kind':'ControlType.Button','rect':[1,2,3,4]},action='invoke')
        with patch('PaintPreparation.subprocess.Popen',side_effect=self.capture_process(process,captured)):
            self.assertEqual(_run_powershell(source),b'[]')
        self.assertEqual(captured['args'][1:],['-NoProfile','-NonInteractive','-Command','-'])
        self.assertNotIn('shell',captured)
        self.assertIn(b'public static class PaintModalAction',captured['source'])
        self.assertIn(b'ConvertFrom-Json -InputObject',captured['source'])
        self.assertNotIn(b'FromBase64String',captured['source'])
        self.assertTrue(captured['source'].endswith(b'}\n\n'))
        self.assertTrue(captured['stdin'].closed)
        process.communicate.assert_called_once_with(timeout=.1)
        process.kill.assert_not_called()

    def test_pre_cancel_does_not_start_process_or_create_script(self):
        with patch('PaintPreparation.subprocess.Popen') as launch, \
             patch('PaintPreparation.tempfile.TemporaryFile') as temporary:
            with self.assertRaises(InterruptedError):
                _run_powershell('throw "must not run"',cancelled=lambda:True)
        launch.assert_not_called()
        temporary.assert_not_called()

    def test_cancellation_kills_process_and_closes_temporary_input(self):
        process=Mock(returncode=None)
        process.poll.return_value=None
        process.communicate.return_value=(b'',b'')
        captured={}
        with patch('PaintPreparation.subprocess.Popen',side_effect=self.capture_process(process,captured)):
            with self.assertRaises(InterruptedError):
                _run_powershell('Start-Sleep -Seconds 60',cancelled=Mock(side_effect=[False,True]))
        process.kill.assert_called_once_with()
        process.communicate.assert_called_once_with(timeout=1)
        self.assertTrue(captured['stdin'].closed)

    def test_twelve_second_timeout_kills_process_and_closes_temporary_input(self):
        process=Mock(returncode=None)
        process.poll.return_value=None
        process.communicate.return_value=(b'',b'')
        captured={}
        with patch('PaintPreparation.subprocess.Popen',side_effect=self.capture_process(process,captured)), \
             patch('PaintPreparation.time.monotonic',side_effect=[100,112.001]):
            with self.assertRaisesRegex(TimeoutError,'during invoke'):
                _run_powershell('Start-Sleep -Seconds 60',action='invoke')
        process.kill.assert_called_once_with()
        process.communicate.assert_called_once_with(timeout=1)
        self.assertTrue(captured['stdin'].closed)

    def test_process_failure_reports_utf8_error_and_closes_input(self):
        process=Mock(returncode=1)
        process.communicate.return_value=(b'',"Paint: färger unavailable".encode('utf-8'))
        process.poll.return_value=1
        captured={}
        with patch('PaintPreparation.subprocess.Popen',side_effect=self.capture_process(process,captured)):
            with self.assertRaisesRegex(ValueError,'Paint: färger unavailable'):
                _run_powershell('throw "probe"')
        self.assertTrue(captured['stdin'].closed)
        process.kill.assert_not_called()

    def test_child_that_never_reads_large_input_remains_cancellable(self):
        # The helper process intentionally never reads stdin. A pipe write can
        # block before communicate's timeout on Windows; a seekable input cannot.
        original_popen=subprocess.Popen
        captured={}
        def launch(_args,**kwargs):
            captured['input']=kwargs['stdin']
            process=original_popen([sys.executable,'-c','import time; time.sleep(60)'],**kwargs)
            captured['process']=process
            captured['started']=time.monotonic()
            return process
        def cancelled():
            return 'started' in captured and time.monotonic()-captured['started']>.3
        started=time.monotonic()
        with patch('PaintPreparation.subprocess.Popen',side_effect=launch):
            with self.assertRaises(InterruptedError):
                _run_powershell('# '+('x'*262144),cancelled=cancelled)
        self.assertLess(time.monotonic()-started,8)
        self.assertIsNotNone(captured['process'].poll())
        self.assertTrue(captured['input'].closed)


@unittest.skipUnless(os.name=='nt','Windows PowerShell transport')
class WindowsPaintScriptTransportTests(unittest.TestCase):
    def test_unicode_and_script_shaped_control_names_round_trip_as_json_data(self):
        names=["Röd", "Grön", "Blå", "Edit colors", "Redigera färger 🎨",
               "'); $script:injected=$true; #",
               '"; $script:injected=$true; #',
               "$($script:injected=$true) `n `\" @'\n'@\r\n'quoted' \\"]
        elements=[{'name':name,'kind':'ControlType.Button','rect':[-10,20,30,40]} for name in names]
        script="$script:injected=$false\n$elements=ConvertFrom-Json -InputObject "+_powershell_json_literal(elements)+"\n"
        script+="ConvertTo-Json -InputObject @{elements=@($elements);injected=$script:injected} -Depth 5 -Compress"
        result=json.loads(_run_powershell(script).decode('utf-8-sig'))
        self.assertEqual(result,{'elements':elements,'injected':False})

    def test_long_label_does_not_exceed_windows_command_line_limit(self):
        element={'name':('Redigera färger '*4000)+"'"}
        script="$wanted=ConvertFrom-Json -InputObject "+_powershell_json_literal(element)+"\n"
        script+="ConvertTo-Json -InputObject $wanted -Compress"
        self.assertEqual(json.loads(_run_powershell(script).decode('utf-8-sig')),element)

    def test_multiline_block_runs_as_one_complete_statement(self):
        script="""
$values=@()
foreach($value in @(0,1,2)) {
    $values+=($value*$value)
}
ConvertTo-Json -InputObject @{values=$values} -Compress
"""
        self.assertEqual(json.loads(_run_powershell(script).decode('utf-8-sig')),{'values':[0,1,4]})

    def test_script_failure_is_propagated_without_paint_input(self):
        with self.assertRaisesRegex(ValueError,'transport failure probe'):
            _run_powershell("throw 'transport failure probe'")

    def test_running_powershell_remains_cancellable_and_is_reaped(self):
        original_popen=subprocess.Popen
        captured={}
        def launch(*args,**kwargs):
            captured['input']=kwargs['stdin']
            process=original_popen(*args,**kwargs)
            captured['process']=process
            captured['started']=time.monotonic()
            return process
        def cancelled():
            return 'started' in captured and time.monotonic()-captured['started']>.6
        started=time.monotonic()
        with patch('PaintPreparation.subprocess.Popen',side_effect=launch):
            with self.assertRaises(InterruptedError):
                _run_powershell('Start-Sleep -Seconds 60',cancelled=cancelled)
        self.assertLess(time.monotonic()-started,8)
        self.assertIsNotNone(captured['process'].poll())
        self.assertTrue(captured['input'].closed)


if __name__=='__main__':unittest.main()
