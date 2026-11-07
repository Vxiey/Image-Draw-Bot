"""Stop covers the real diagnostic export, publication and UI completion."""
import json
from pathlib import Path
import queue
import tempfile
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import DiagnosticsPackage as diagnostics
from DrawBot import DrawBotApp


class DiagnosticCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.base = Path(self.temporary)
        self.destination = self.base / 'diagnostics'
        self.stop = threading.Event()
        self.enterContext(patch.object(diagnostics, 'data_dir', return_value=self.base))
        self.enterContext(patch.object(diagnostics, 'DIAGNOSTICS_DIR', self.destination))
        self.enterContext(patch.object(diagnostics, '_technical_info', return_value={'app': 'fixture'}))
        self.enterContext(patch('CrashDumpConfig.user_dump_folder', return_value=self.base / 'dumps'))

    def previous_export(self):
        self.destination.mkdir()
        path = self.destination / 'previous-diagnostics.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('old.txt', 'Preserve earlier completed diagnostic evidence.')
        return path, path.read_bytes()

    def assert_preserved(self, previous):
        path, contents = previous
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(list(self.destination.iterdir()), [path])

    def app(self):
        app = SimpleNamespace(activity=None, closing=False, root=Mock(),
            stop=self.stop, events=queue.Queue(), status=Mock(),
            _diagnostics_context=lambda: {'activity': 'idle'})
        app.set_busy = lambda activity: setattr(app, 'activity', activity)
        app.begin_worker = MethodType(DrawBotApp.begin_worker, app)
        self.enterContext(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.enterContext(patch('DrawBot.log_event'))
        self.enterContext(patch('DrawBot.log_error'))
        return app

    def test_public_gui_export_stops_between_files_without_zip_or_success_dialog(self):
        previous = self.previous_export()
        for name in ('a', 'b', 'c'):
            (self.base / f'settings-{name}.json').write_text(json.dumps({'quality': 'High'}))
        read = diagnostics._json_input
        reads = []

        def read_first(path, base, **options):
            result = read(path, base, **options)
            reads.append(path.name)
            self.stop.set()
            return result

        app = self.app()
        with patch.object(diagnostics, '_json_input', side_effect=read_first), \
             patch('DrawBot.messagebox.showinfo') as success:
            DrawBotApp.collect_diagnostics(app)
            worker = app.worker
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive(), 'Diagnostics did not stop at the next file boundary')
            self.assertEqual(reads, ['settings-a.json'])
            events = []
            while not app.events.empty():
                event = app.events.get_nowait()
                events.append(event)
                DrawBotApp._handle_event(app, *event)
            self.assertNotIn('diagnostics_ready', [event[0] for event in events])
            self.assertEqual(events[-1], ('done', 'diagnostics'))
            success.assert_not_called()
        self.assertTrue(self.stop.is_set())
        self.assertIsNone(app.activity)
        self.assert_preserved(previous)

    def test_already_cancelled_export_creates_no_directory(self):
        self.stop.set()
        with self.assertRaises(InterruptedError):
            diagnostics.create_diagnostics_package(cancelled=self.stop.is_set)
        self.assertFalse(self.destination.exists())

    def test_stop_during_directory_inventory_does_not_scan_remaining_candidates(self):
        previous = self.previous_export()
        inspected = []
        real_glob = Path.glob

        def files(path, pattern):
            if path == self.base and pattern == 'settings*.json':
                def candidates():
                    for number in range(1000):
                        inspected.append(number)
                        if number == 4:
                            self.stop.set()
                        yield self.base / f'settings-{number:04d}.json'
                return candidates()
            return real_glob(path, pattern)

        with patch.object(Path, 'glob', files):
            with self.assertRaises(InterruptedError):
                diagnostics.create_diagnostics_package(cancelled=self.stop.is_set)
        self.assertEqual(inspected, list(range(5)))
        self.assert_preserved(previous)

    def test_stop_during_log_redaction_aborts_before_publication(self):
        previous = self.previous_export()
        logs = self.base / 'logs'
        logs.mkdir()
        (logs / 'ImageDrawBot-session.log').write_text('Authorization: Bearer PRIVATE\n')
        sanitize = diagnostics.sanitize_text

        def cancelled_redaction(text):
            result = sanitize(text)
            self.stop.set()
            return result

        with patch.object(diagnostics, 'sanitize_text', side_effect=cancelled_redaction):
            with self.assertRaises(InterruptedError):
                diagnostics.create_diagnostics_package(cancelled=self.stop.is_set)
        self.assert_preserved(previous)

    def test_cancel_after_zip_close_still_preserves_previous_export(self):
        previous = self.previous_export()
        real_close = zipfile.ZipFile.close

        def close(archive):
            real_close(archive)
            if archive.mode == 'w':
                self.stop.set()

        with patch.object(zipfile.ZipFile, 'close', close), \
             patch.object(diagnostics.os, 'replace') as publish:
            with self.assertRaises(InterruptedError):
                diagnostics.create_diagnostics_package(cancelled=self.stop.is_set)
            publish.assert_not_called()
        self.assert_preserved(previous)

    def test_cleanup_failure_preserves_cancellation_as_primary_exception(self):
        previous = self.previous_export()
        real_unlink = Path.unlink

        def deny_staging(path, *args, **kwargs):
            if path.name.startswith('.diagnostics-'):
                raise PermissionError('temporary file is busy')
            return real_unlink(path, *args, **kwargs)

        def stop_collection(**_options):
            self.stop.set()
            raise InterruptedError('the original Stop')

        with patch.object(diagnostics, '_settings_summary', side_effect=stop_collection), \
             patch.object(Path, 'unlink', deny_staging):
            with self.assertRaisesRegex(InterruptedError, 'the original Stop') as caught:
                diagnostics.create_diagnostics_package(cancelled=self.stop.is_set)
        self.assertTrue(any('PermissionError' in note for note in caught.exception.__notes__))
        self.assertEqual(previous[0].read_bytes(), previous[1])
        self.assertEqual(list(self.destination.glob('*.zip')), [previous[0]])
        self.assertEqual(len(list(self.destination.glob('.diagnostics-*'))), 1)

    def test_archive_close_failure_does_not_replace_an_existing_stop(self):
        previous = self.previous_export()
        real_close = zipfile.ZipFile.close

        def failed_close(archive):
            was_open = archive.fp is not None
            real_close(archive)
            if archive.mode == 'w' and was_open:
                raise OSError('archive finalization failed')

        with patch.object(diagnostics, '_settings_summary', side_effect=InterruptedError('original cancellation')), \
             patch.object(zipfile.ZipFile, 'close', failed_close):
            with self.assertRaisesRegex(InterruptedError, 'original cancellation') as caught:
                diagnostics.create_diagnostics_package(cancelled=self.stop.is_set)
        self.assertTrue(any('archive cleanup' in note for note in caught.exception.__notes__))
        self.assert_preserved(previous)

    def test_late_cancelled_or_closing_ui_result_does_not_open_success_dialog(self):
        previous = self.previous_export()
        for closing in (False, True):
            with self.subTest(closing=closing):
                app = SimpleNamespace(closing=closing, stop=threading.Event(), status=Mock())
                if not closing:
                    app.stop.set()
                with patch('DrawBot.messagebox.showinfo') as success:
                    DrawBotApp._handle_event(app, 'diagnostics_ready', str(previous[0]))
                success.assert_not_called()
                app.status.set.assert_not_called()
        self.assert_preserved(previous)

    def test_standalone_helper_does_not_open_folder_after_late_stop(self):
        previous = self.previous_export()

        def completed(**_options):
            self.stop.set()
            return previous[0]

        operating_system = SimpleNamespace(name='nt', startfile=Mock())
        with patch.object(diagnostics, 'os', operating_system), \
             patch.object(diagnostics, 'create_diagnostics_package', side_effect=completed), \
             patch('tkinter.messagebox.showinfo') as success, \
             patch('tkinter.messagebox.showerror') as failure:
            with self.assertRaises(InterruptedError):
                diagnostics.main(cancelled=self.stop.is_set)
        operating_system.startfile.assert_not_called()
        success.assert_not_called()
        failure.assert_not_called()
        self.assert_preserved(previous)

    def test_json_cancellation_is_not_swallowed_as_an_optional_read_failure(self):
        previous = self.previous_export()
        (self.base / 'settings.json').write_text('{"quality":"High"}')
        with patch.object(diagnostics.json, 'loads', side_effect=InterruptedError('parse cancelled')):
            with self.assertRaisesRegex(InterruptedError, 'parse cancelled'):
                diagnostics.create_diagnostics_package(cancelled=self.stop.is_set)
        self.assert_preserved(previous)


if __name__ == '__main__':
    unittest.main()
