from io import StringIO
import json
from pathlib import Path
from queue import Queue
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import TargetCapture as target


def reply():
    return json.dumps({'ok': True, 'handle': 42, 'rect': [0, 0, 200, 200],
                       'client_rect': [10, 30, 190, 190], 'target_pid': 123})


class ProbeProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        changed = patch.object(target, 'BASE', self.root)
        changed.start()
        self.addCleanup(changed.stop)

    def process(self):
        process = Mock(returncode=None, stdout=StringIO(), stderr=StringIO())
        process.poll.return_value = None
        process.wait.return_value = 0
        return process

    def test_stop_before_spawn_never_creates_a_helper(self):
        with patch.object(target.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(InterruptedError, 'cancelled'):
                target.probe_handle_isolated(42, cancelled=lambda: True)
        spawn.assert_not_called()

    def test_late_stop_discards_a_successful_response_and_closes_pipes(self):
        process = self.process()
        stop = threading.Event()
        def complete(**kwargs):
            process.returncode = 0
            process.poll.return_value = 0
            stop.set()
            return reply(), ''
        process.communicate.side_effect = complete
        with patch.object(target.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(InterruptedError, 'cancelled'):
                target.probe_handle_isolated(42, cancelled=stop.is_set)
        process.terminate.assert_not_called()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_stop_terminates_then_kills_and_reaps_a_nonresponding_helper(self):
        process = self.process()
        stop = threading.Event()
        def blocked(**kwargs):
            stop.set()
            raise subprocess.TimeoutExpired(['helper'], .1, output=b'waiting for Windows\n')
        process.communicate.side_effect = blocked
        process.wait.side_effect = [subprocess.TimeoutExpired(['helper'], .5), 0]
        with patch.object(target.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(InterruptedError, 'cancelled'):
                target._run(['helper'], cancelled=stop.is_set)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual([row.kwargs['timeout'] for row in process.wait.call_args_list], [.5, 1])
        self.assertTrue(process.stdout.closed)
        self.assertIn('waiting for Windows', (self.root / 'logs/ImageDrawBot-target-probe.log').read_text())

    def test_cleanup_failures_never_replace_the_original_interruption(self):
        process = self.process()
        stop = threading.Event()
        def blocked(**kwargs):
            stop.set()
            raise subprocess.TimeoutExpired(['helper'], .1)
        process.communicate.side_effect = blocked
        process.terminate.side_effect = OSError('terminate unavailable')
        process.wait.side_effect = [subprocess.TimeoutExpired(['helper'], .5), OSError('reap unavailable')]
        process.kill.side_effect = OSError('kill unavailable')
        process.stderr = Mock()
        process.stderr.close.side_effect = RuntimeError('pipe close unavailable')
        with patch.object(target.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(InterruptedError, 'cancelled') as caught:
                target._run(['helper'], cancelled=stop.is_set)
        self.assertTrue(caught.exception.__notes__)
        process.kill.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_deadline_uses_bounded_waits_then_stops_the_helper(self):
        process = self.process()
        process.communicate.side_effect = subprocess.TimeoutExpired(['helper'], .1)
        with patch.object(target.subprocess, 'Popen', return_value=process), \
             patch.object(target.time, 'monotonic', side_effect=[0, 0, .3]):
            with self.assertRaisesRegex(InterruptedError, 'took too long'):
                target._run(['helper'], timeout=.2, cancelled=lambda: False)
        self.assertEqual(process.communicate.call_args.kwargs['timeout'], .1)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=.5)

    def test_actual_local_child_is_reaped_when_cancelled(self):
        actual_popen = subprocess.Popen
        children = []
        def start(*args, **kwargs):
            child = actual_popen(*args, **kwargs)
            children.append(child)
            return child
        deadline = time.monotonic() + .3
        with patch.object(target.subprocess, 'Popen', side_effect=start):
            with self.assertRaises(InterruptedError):
                target._run([sys.executable, '-I', '-c',
                             'import time; print("probe started",flush=True); time.sleep(30)'],
                            timeout=5, cancelled=lambda: bool(children) and time.monotonic() >= deadline)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_failed_start_or_timeout_replaces_stale_logs_with_sanitized_context(self):
        path = self.root / 'logs/ImageDrawBot-target-probe.log'
        path.parent.mkdir()
        command = [r'C:\Users\PRIVATE_USER\bin\helper.exe', '--target-probe']
        failures = [
            subprocess.TimeoutExpired(command, 8,
                output=b'Current run failed https://host.test/a?signature=OUTPUT_SECRET\n',
                stderr=b'Authorization: Bearer STDERR_SECRET\n'),
            OSError('Cannot start ' + command[0]),
        ]
        for error in failures:
            path.write_text('STALE PREVIOUS RUN')
            with self.subTest(error=type(error).__name__), \
                 patch.object(target.subprocess, 'run', side_effect=error):
                with self.assertRaises((OSError, InterruptedError)):
                    target._run(command)
            contents = path.read_text()
            for secret in ('STALE PREVIOUS RUN', 'PRIVATE_USER', 'OUTPUT_SECRET', 'STDERR_SECRET'):
                self.assertNotIn(secret, contents)
            self.assertIn(type(error).__name__, contents)

    def test_logging_failure_does_not_replace_spawn_failure(self):
        original = FileNotFoundError('helper missing')
        with patch.object(target.subprocess, 'run', side_effect=original), \
             patch.object(target, 'atomic_write_text', side_effect=UnicodeError('log failed')):
            with self.assertRaises(FileNotFoundError) as caught:
                target._run(['missing-helper'])
        self.assertIs(caught.exception, original)

    def test_picture_palette_worker_cancels_both_calibration_probes(self):
        from PIL import Image
        import PictureCustomPaletteLegacy as legacy
        from test_drawbot import NoWait
        for stop_at_probe in (1, 2):
            stop = NoWait()
            variable = lambda value: SimpleNamespace(get=lambda: value)
            source = Image.new('RGB', (4, 4), (1, 2, 3))
            self.addCleanup(source.close)
            app = SimpleNamespace(activity=None, closing=False, game=variable('Microsoft Paint'),
                original=source, status=Mock(), stop=stop, events=Queue(),
                exact_color_limit=variable('8'), draw_quality=variable('High likeness'),
                color_fidelity=variable('Faithful'), calibration_path='unused-test-palette.json')
            app.begin_worker = lambda _kind, work: work()
            monitor = Mock()
            monitor.activate.return_value = True
            calls = []
            def probe(handle, *, cancelled=None):
                self.assertEqual(cancelled, stop.is_set)
                calls.append(handle)
                if len(calls) == stop_at_probe:
                    stop.stopped = True
                if cancelled():
                    raise InterruptedError('Target probe cancelled.')
                return {'handle': handle, 'client_rect': (0, 0, 100, 100)}
            with self.subTest(stop_at_probe=stop_at_probe), \
                 patch.object(legacy, '_resolve_target', return_value=(42, (0, 0, 100, 100))), \
                 patch('ScreenGuard.WindowMonitor', return_value=monitor), \
                 patch.object(target, 'probe_handle_isolated', side_effect=probe), \
                 patch('ExactColorTools.numeric_rgb_available', return_value=False), \
                 patch('PaintPreparation.calibrate_rgb_controls', return_value={}) as calibrate, \
                 patch('ExactColorTools.save') as save, \
                 patch.object(legacy, 'build_picture_palette') as build:
                with self.assertRaisesRegex(InterruptedError, 'Target probe cancelled'):
                    legacy.start_picture_custom_palette(app)
                self.assertEqual(calls, [42] * stop_at_probe)
                self.assertEqual(calibrate.call_count, stop_at_probe - 1)
                save.assert_not_called()
                build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
