"""Retain a keyboard Stop between a real export snapshot and worker handoff.

The public controller, worker, Pillow encoder and atomic writer are real.
Existing repository PNGs provide every raster; only native chooser, logging
and narrowly observed/failing copy, thread-start or encoding boundaries vary.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from DrawBot import DrawBotApp


ROOT = Path(__file__).resolve().parent
REAL_THREAD = threading.Thread
OPERATIONS = ('export_preview', '_save_captured_png')


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@contextmanager
def export_controller():
    with ExitStack() as stack:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        source = stack.enter_context(Image.open(ROOT / 'assets/paint-tools-reference.png'))
        source.load()
        original = stack.enter_context(Image.open(ROOT / 'assets/image-draw-bot-icon.png'))
        original.load()
        destination = directory / 'export.png'
        destination.write_bytes((ROOT / 'assets/image-draw-bot-icon.png').read_bytes())
        app = SimpleNamespace(
            original=original, plan={'preview': source}, preview_tabs=Value('Simulated final'),
            closing=False, activity=None, root=None, pending_clear_drawing=None,
            profile_change_after=None, profile_change_in_progress=False,
            events=queue.Queue(), stop=threading.Event(), status=Value('Ready.'), worker=None,
        )
        app.begin_worker = MethodType(DrawBotApp.begin_worker, app)
        app.set_busy = lambda value: setattr(app, 'activity', value)
        stack.enter_context(patch('DrawBot.log_event'))
        stack.enter_context(patch('DrawBot.log_error'))
        try:
            yield app, source, destination
        finally:
            worker = app.worker
            if isinstance(worker, REAL_THREAD) and worker.is_alive():
                app.stop.set()
                worker.join(10)
                if worker.is_alive():
                    raise AssertionError('Export worker survived fixture cleanup.')


class ExportSnapshotStopTests(unittest.TestCase):
    def request_stop(self, app):
        errors = []

        def stop():
            try:
                DrawBotApp._request_stop(app)
            except BaseException as error:
                errors.append(error)

        stopper = REAL_THREAD(target=stop, name='export-keyboard-stop')
        stopper.start()
        stopper.join(3)
        self.assertFalse(stopper.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(app.stop.is_set())

    def exercise(self, operation, moment, *, feedback_error=None):
        with export_controller() as (app, source, destination):
            before = destination.read_bytes()
            pixels = source.mode, source.size, source.tobytes()
            original = app.original.tobytes()
            files = set(destination.parent.iterdir())
            copies, threads, encoded = [], [], []
            copy, save = source.copy, Image.Image.save
            caller = threading.get_ident()

            def copied():
                result = copy()
                copies.append(result)
                if moment == 'copy':
                    self.request_stop(app)
                return result

            def construct(*args, **kwargs):
                if moment == 'startup-failure':
                    raise RuntimeError('thread startup unavailable')
                result = REAL_THREAD(*args, **kwargs)
                threads.append(result)
                if moment == 'constructor':
                    self.request_stop(app)
                return result

            def encode(image, *args, **kwargs):
                encoded.append(threading.get_ident())
                result = save(image, *args, **kwargs)
                if moment == 'encode':
                    self.request_stop(app)
                return result

            if moment in ('previous', 'cancel'):
                self.request_stop(app)
            if feedback_error is not None:
                set_status = app.status.set

                def status(value):
                    if value == 'Stopped.':
                        raise feedback_error
                    set_status(value)

                app.status.set = status
            accepted = False
            try:
                with patch.object(source, 'copy', new=copied), \
                        patch.object(Image.Image, 'save', new=encode), \
                        patch('DrawBot.threading.Thread', new=construct), \
                        patch('DrawBot.filedialog.asksaveasfilename',
                              return_value='' if moment == 'cancel' else str(destination)):
                    def invoke():
                        if operation == '_save_captured_png':
                            return DrawBotApp._save_captured_png(app, source)
                        return DrawBotApp.export_preview(app)

                    if moment == 'startup-failure':
                        with self.assertRaisesRegex(RuntimeError, 'thread startup unavailable'):
                            invoke()
                    else:
                        accepted = invoke()
                    for worker in threads:
                        worker.join(10)
                        self.assertFalse(worker.is_alive())
                events = []
                while not app.events.empty():
                    events.append(app.events.get_nowait())
                for event in events:
                    DrawBotApp._handle_event(app, *event)
                self.assertIsNone(app.activity)
                self.assertEqual((source.mode, source.size, source.tobytes()), pixels)
                self.assertEqual(app.original.tobytes(), original)
                self.assertEqual(set(destination.parent.iterdir()), files)
                self.assertEqual(len(copies), 0 if moment == 'cancel' else 1)
                for image in copies:
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))
                if moment == 'previous':
                    self.assertTrue(accepted)
                    self.assertFalse(app.stop.is_set())
                    self.assertEqual(len(encoded), 1)
                    self.assertNotEqual(encoded[0], caller)
                    with Image.open(destination) as saved:
                        saved.load()
                        self.assertEqual((saved.mode, saved.size, saved.tobytes()), pixels)
                    self.assertEqual(events[-1], ('done', 'preview-export' if operation == 'export_preview' else 'png-export'))
                    self.assertIn('saved', app.status.get())
                else:
                    self.assertEqual(destination.read_bytes(), before)
                    self.assertTrue(app.stop.is_set())
                    if moment in ('copy', 'cancel', 'startup-failure'):
                        self.assertFalse(accepted)
                        self.assertEqual(threads, [])
                        self.assertEqual(events, [])
                        self.assertEqual(encoded, [])
                    else:
                        self.assertTrue(accepted)
                        self.assertEqual(len(threads), 1)
                        self.assertEqual([kind for kind, _ in events], ['status', 'done'])
                        self.assertEqual(len(encoded), 1 if moment == 'encode' else 0)
                    if moment != 'cancel' and feedback_error is None:
                        self.assertEqual(app.status.get(), 'Stopped.' if moment != 'startup-failure' else 'Ready.')
            finally:
                for image in copies:
                    image.close()

    def test_stop_during_preview_snapshot_preserves_existing_export(self):
        self.exercise('export_preview', 'copy')

    def test_stop_during_captured_snapshot_preserves_existing_export(self):
        self.exercise('_save_captured_png', 'copy')

    def test_explicit_export_after_previous_stop_encodes_real_snapshot(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'previous')

    def test_stop_at_real_thread_construction_skips_encoding(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'constructor')

    def test_stop_after_actual_encoding_prevents_atomic_publication(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'encode')

    def test_cancelled_chooser_retains_stop_and_does_not_copy(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'cancel')

    def test_startup_failure_closes_snapshot_and_preserves_existing_export(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'startup-failure')

    def test_unavailable_status_does_not_break_stopped_snapshot_cleanup(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'copy', feedback_error=tk.TclError('status destroyed'))


if __name__ == '__main__':
    unittest.main()
