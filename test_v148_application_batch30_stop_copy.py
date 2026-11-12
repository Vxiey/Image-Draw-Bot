"""Keep a new Stop across the real image-copy to image-worker handoff."""
from contextlib import closing, contextmanager
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image

import BackgroundRemoval
from DrawBot import DrawBotApp
import test_v148_application_batch15_image_worker_cleanup as worker_fixture


REAL_THREAD = threading.Thread
OPERATIONS = ('save_png_copy', 'remove_image_background')


@contextmanager
def actual_controller(operation):
    # Reuse only the established UI/native-window ports. Replace its deferred
    # thread below with a real Thread; the controller, worker and task are real.
    harness = worker_fixture.ImageWorkerCleanupTests('runTest')
    harness.setUp()
    app = None
    try:
        app, source, _captured, destination = harness.fixture(operation)
        app.stop = threading.Event()
        yield app, source, destination
    finally:
        if app is not None:
            worker = getattr(app, 'worker', None)
            if isinstance(worker, REAL_THREAD) and worker.is_alive():
                app.stop.set()
                worker.join(timeout=10)
                if worker.is_alive():
                    raise AssertionError('Image worker did not finish before fixture cleanup')
            for name in ('original', 'background_removal_original', 'upscale_original'):
                image = getattr(app, name, None)
                if isinstance(image, Image.Image):
                    image.close()
        harness.doCleanups()


class ImageCopyStopTests(unittest.TestCase):
    def exercise(self, operation, moment, *, feedback_error=None):
        with actual_controller(operation) as (app, source, destination):
            with closing(Image.new('RGBA', (3, 2), (21, 43, 65, 255))) as old:
                old.save(destination, format='PNG')
            old_bytes, before = destination.read_bytes(), source.tobytes()
            old_files = set(destination.parent.iterdir())
            copies, calls, callback_threads, callback_errors, created, results = [], [], [], [], [], []
            caller = threading.get_ident()
            copy = source.copy
            backend_name = ('png_export_ready' if operation == 'save_png_copy'
                            else 'remove_background')
            backend = getattr(BackgroundRemoval, backend_name)
            if feedback_error is not None:
                def feedback(value):
                    if value == 'Stopped.':
                        raise feedback_error
                app.status.set.side_effect = feedback

            def request_stop():
                callback_threads.append(threading.get_ident())
                try:
                    DrawBotApp._request_stop(app)
                except BaseException as error:
                    callback_errors.append(error)

            def stop_from_other_thread():
                stopper = REAL_THREAD(target=request_stop, name='actual-keyboard-stop-boundary')
                stopper.start()
                stopper.join(timeout=3)
                self.assertFalse(stopper.is_alive())
                self.assertEqual(callback_errors, [])
                self.assertTrue(app.stop.is_set())
                self.assertNotEqual(callback_threads[-1], caller)

            def copied():
                image = copy()
                copies.append(image)
                if moment == 'copy':
                    # This is the real completed PIL copy, before the caller
                    # can enter begin_worker. No mock worker resets the signal.
                    stop_from_other_thread()
                return image

            def construct(*args, **kwargs):
                thread = REAL_THREAD(*args, **kwargs)
                created.append(thread)
                if moment == 'constructor':
                    stop_from_other_thread()
                return thread

            def run_backend(*args, **kwargs):
                calls.append((threading.get_ident(), app.stop.is_set()))
                result = backend(*args, **kwargs)
                results.append(result)
                return result

            try:
                if moment == 'previous':
                    stop_from_other_thread()
                with patch('DrawBot.threading.Thread', new=construct), \
                        patch.object(source, 'copy', new=copied), \
                        patch('DrawBot.filedialog.asksaveasfilename', return_value=str(destination)), \
                        patch.object(BackgroundRemoval, backend_name, new=run_backend):
                    accepted = getattr(DrawBotApp, operation)(app)
                    for worker in created:
                        worker.join(timeout=10)
                        self.assertFalse(worker.is_alive())
                self.assertEqual(len(copies), 1)
                if operation == 'remove_image_background' and moment == 'previous':
                    self.assertEqual(copies[0].tobytes(), before)
                else:
                    with self.assertRaises(ValueError):
                        copies[0].getpixel((0, 0))
                self.assertEqual(source.tobytes(), before)
                events = worker_fixture.ImageWorkerCleanupTests.events(app)
                kinds = [kind for kind, _ in events]
                self.assertNotIn('terminal_status', kinds)
                # Deliver on the UI after the worker transfers its owned Undo
                # snapshot; no second source copy is needed for this handoff.
                with patch.object(DrawBotApp, '_clear_render_resume'):
                    for event in events:
                        DrawBotApp._handle_event(app, *event)
                self.assertEqual(source.tobytes(), before)
                self.assertEqual(set(destination.parent.iterdir()), old_files)
                if moment == 'previous':
                    self.assertTrue(accepted)
                    self.assertEqual(len(created), 1)
                    self.assertEqual(len(calls), 1)
                    self.assertNotEqual(calls[0][0], caller)
                    self.assertFalse(calls[0][1])
                    self.assertFalse(app.stop.is_set())
                    if operation == 'save_png_copy':
                        self.assertEqual(kinds, ['png_saved', 'done'])
                        self.assertNotEqual(destination.read_bytes(), old_bytes)
                        with closing(Image.open(destination)) as saved:
                            saved.load()
                            self.assertEqual((saved.mode, saved.size, saved.tobytes()),
                                             (source.mode, source.size, before))
                        self.assertIs(app.original, source)
                    else:
                        self.assertEqual(kinds, ['background_removed', 'done'])
                        self.assertIsNot(app.original, source)
                        self.assertEqual(app.original.getpixel((0, 0))[3], 0)
                        self.assertEqual(app.original.getpixel((30, 20)), (220, 30, 50, 255))
                        self.assertEqual(app.background_removal_original.tobytes(), before)
                        self.assertEqual(destination.read_bytes(), old_bytes)
                else:
                    self.assertEqual(calls, [])
                    self.assertTrue(app.stop.is_set())
                    self.assertIs(app.original, source)
                    self.assertIsNone(app.background_removal_original)
                    self.assertEqual(destination.read_bytes(), old_bytes)
                    if moment == 'copy':
                        self.assertFalse(accepted)
                        self.assertEqual(created, [])
                        self.assertEqual(events, [])
                        self.assertIsNone(app.activity)
                        self.assertEqual(app.status.set.call_args.args[0], 'Stopped.')
                    else:
                        self.assertTrue(accepted)
                        self.assertEqual(len(created), 1)
                        self.assertEqual(kinds, ['status', 'done'])
                        self.assertEqual(app.status.set.call_args.args[0], 'Stopped.')
            finally:
                for image in copies:
                    image.close()
                for result in results:
                    image = getattr(result, 'image', result)
                    if isinstance(image, Image.Image):
                        image.close()

    def test_png_stop_during_copy_preserves_the_existing_file(self):
        self.exercise('save_png_copy', 'copy')

    def test_background_stop_during_copy_preserves_source_and_undo(self):
        self.exercise('remove_image_background', 'copy')

    def test_explicit_actions_clear_a_previous_stop_and_finish_actual_work(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'previous')

    def test_stop_at_real_thread_construction_still_skips_task_and_releases_copy(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation, 'constructor')

    def test_destroyed_status_feedback_does_not_change_refusal_or_snapshot_cleanup(self):
        for operation in OPERATIONS:
            for error_type in (tk.TclError, RuntimeError, AttributeError):
                with self.subTest(operation=operation, error=error_type.__name__):
                    self.exercise(operation, 'copy', feedback_error=error_type('status is unavailable'))

    def test_startup_error_is_not_replaced_by_stopped_feedback_and_copy_still_closes(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation), actual_controller(operation) as (app, source, destination):
                before = source.tobytes()
                copies = []
                copy = source.copy
                failure = RuntimeError('controlled actual worker-construction failure')
                retained = None
                def copied():
                    image = copy()
                    copies.append(image)
                    return image
                def feedback(value):
                    if value == 'Stopped.':
                        raise tk.TclError('must not mask the worker startup error')
                app.status.set.side_effect = feedback
                with patch.object(source, 'copy', new=copied), \
                        patch('DrawBot.filedialog.asksaveasfilename', return_value=str(destination)), \
                        patch('DrawBot.threading.Thread', side_effect=failure):
                    try:
                        getattr(DrawBotApp, operation)(app)
                    except BaseException as error:
                        retained = error
                self.assertIs(retained, failure)
                self.assertIsNotNone(retained.__traceback__)
                self.assertTrue(app.stop.is_set())
                self.assertIsNone(app.activity)
                self.assertIsNone(app.worker)
                self.assertTrue(app.events.empty())
                self.assertFalse(destination.exists())
                self.assertEqual(source.tobytes(), before)
                self.assertEqual(len(copies), 1)
                for image in copies:
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))
                self.assertNotIn('Stopped.', [call.args[0] for call in app.status.set.call_args_list])

    def test_cancelled_or_invalidated_png_dialog_preserves_stop_without_copy(self):
        for change in ('cancel', 'source', 'closing', 'busy'):
            with self.subTest(change=change), actual_controller('save_png_copy') as (app, source, destination):
                app.stop.set()
                before = source.tobytes()
                replacement = Image.new('RGBA', source.size, 'blue')
                with closing(replacement):
                    def dialog(**kwargs):
                        if change == 'source': app.original = replacement
                        elif change == 'closing': app.closing = True
                        elif change == 'busy': app.activity = 'draw'
                        return '' if change == 'cancel' else str(destination)
                    with patch('DrawBot.filedialog.asksaveasfilename', new=dialog), \
                            patch.object(source, 'copy', side_effect=AssertionError('Rejected request copied source')), \
                            patch('DrawBot.threading.Thread', side_effect=AssertionError('Rejected request started worker')):
                        self.assertFalse(DrawBotApp.save_png_copy(app))
                    self.assertTrue(app.stop.is_set())
                    self.assertTrue(app.events.empty())
                    self.assertFalse(destination.exists())
                    self.assertEqual(source.tobytes(), before)

    def test_rejected_actions_do_not_clear_stop_or_create_a_snapshot(self):
        for operation in OPERATIONS:
            for reason in ('closing', 'busy', 'missing-image'):
                with self.subTest(operation=operation, reason=reason), actual_controller(operation) as (app, source, destination):
                    app.stop.set()
                    before = source.tobytes()
                    if reason == 'closing': app.closing = True
                    elif reason == 'busy': app.activity = 'draw'
                    else: app.original = None
                    with patch('DrawBot.filedialog.asksaveasfilename', side_effect=AssertionError('Unexpected dialog')), \
                            patch.object(source, 'copy', side_effect=AssertionError('Unexpected copy')), \
                            patch('DrawBot.threading.Thread', side_effect=AssertionError('Unexpected worker')):
                        self.assertFalse(getattr(DrawBotApp, operation)(app))
                    self.assertTrue(app.stop.is_set())
                    self.assertTrue(app.events.empty())
                    self.assertFalse(destination.exists())
                    self.assertEqual(source.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
