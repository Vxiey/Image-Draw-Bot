"""Actual autosave dispatch, PNG ownership and publication identity."""
from contextlib import ExitStack
import gc
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import weakref

from PIL import Image

from DrawBot import DrawBotApp
import RecoveryImagePreparation as preparation
import SessionRecovery as recovery
from test_v148_application_batch05_subject_recovery import application


class Root:
    def __init__(self):
        self.callbacks = {}
        self.serial = 0

    def after(self, delay, callback):
        self.serial += 1
        name = f'after#{self.serial}'
        self.callbacks[name] = (delay, callback)
        return name

    def after_cancel(self, name):
        self.callbacks.pop(name, None)

    def run_next(self):
        name = next(iter(self.callbacks))
        _delay, callback = self.callbacks.pop(name)
        callback()


class RecoveryPreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name, path in {'RECOVERY_DIR': self.directory, 'STATE_FILE': self.directory/'state.json',
                           'IMAGE_FILE': self.directory/'last-image.png',
                           'RENDER_FILE': self.directory/'render.json'}.items():
            self.stack.enter_context(patch.object(recovery, name, path))
        self.log = self.stack.enter_context(patch('DrawBot.log_event'))
        self.apps = []
        self.addCleanup(self.stop_jobs)

    def stop_jobs(self):
        for app in self.apps:
            job = getattr(app, '_recovery_image_job', None)
            if job is not None:
                job.cancel()
                self.assertTrue(job.wait_idle(5), 'Test encoder did not stop')

    def source(self, mode='RGBA', color='blue', size=(11, 9)):
        image = Image.new(mode, size, color)
        self.addCleanup(image.close)
        return image

    def app(self, image):
        app = application(image)
        app.root = Root()
        app.events = queue.Queue()
        app.activity = None
        app.worker = None
        app.stop = threading.Event()
        self.apps.append(app)
        return app

    def complete(self, app, job=None):
        job = job or app._recovery_image_job
        self.assertTrue(job.wait_idle(5))
        kind, value = app.events.get(timeout=3)
        self.assertEqual(kind, 'recovery_image_prepared')
        self.assertIs(value, job)
        DrawBotApp._handle_event(app, kind, value)

    def assert_no_staging(self):
        self.assertEqual(list(self.directory.glob('.recovery-pending-*')), [])

    def test_actual_timer_prepares_off_tk_then_publishes_latest_settings_and_exact_pixels(self):
        source = self.source()
        source.info['borrowed'] = 'unchanged'
        app = self.app(source)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        actual_prepare = preparation.prepare_image
        encoder_threads, private_images, reads = [], [], []
        ui_thread = threading.get_ident()

        def blocked(snapshot, **kwargs):
            encoder_threads.append(threading.get_ident())
            private_images.append(snapshot)
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture did not release encoder')
            return actual_prepare(snapshot, **kwargs)

        actual_get = app.game.get
        def ui_get():
            reads.append(threading.get_ident())
            self.assertEqual(threading.get_ident(), ui_thread)
            return actual_get()
        app.game.get = ui_get
        with patch.object(preparation, 'prepare_image', side_effect=blocked), \
                patch.object(recovery, '_store_image', side_effect=AssertionError('No GUI PNG encoding')):
            DrawBotApp._schedule_recovery_checkpoint(app, include_image=True, delay=40)
            self.assertFalse(encoder_threads)
            app.root.run_next()
            self.assertTrue(entered.wait(3))
            self.assertFalse(recovery.STATE_FILE.exists())
            self.assertFalse(reads)
            self.assertIsNot(private_images[0], source)
            # The UI can keep editing while encoding is in progress. The
            # publication captures those current primitive values on Tk.
            app.subject_region = (.3, .2, .8, .7)
            app.subject_focus.set('Subject first')
            release.set()
            self.complete(app)
        self.assertTrue(all(value != ui_thread for value in encoder_threads))
        self.assertTrue(reads)
        state = recovery.load_snapshot()
        self.assertEqual(state['subject_selection']['region'], list(app.subject_region))
        self.assertEqual(state['subject_selection']['mode'], 'Subject first')
        with recovery.load_cached_image(state['image_sha256']) as cached:
            self.assertEqual(cached.tobytes(), source.tobytes())
            self.assertEqual(cached.size, source.size)
        self.assertIs(app._recovery_source_ref(), source)
        self.assertEqual(source.info, {'borrowed': 'unchanged'})
        with self.assertRaises(ValueError):
            private_images[0].getpixel((0, 0))
        self.assert_no_staging()

    def test_many_replacements_coalesce_to_one_private_snapshot_and_the_latest_source(self):
        first = self.source(color='red')
        app = self.app(first)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        actual_prepare = preparation.prepare_image
        snapshots = []

        def blocked(snapshot, **kwargs):
            snapshots.append(snapshot)
            if len(snapshots) == 1:
                entered.set()
                if not release.wait(3):raise AssertionError('Fixture did not release encoder')
            return actual_prepare(snapshot, **kwargs)

        with patch.object(preparation, 'prepare_image', side_effect=blocked):
            DrawBotApp._queue_recovery_checkpoint(app, include_image=True)
            self.assertTrue(entered.wait(3))
            first_job = app._recovery_image_job
            for value in range(12):
                app.original = self.source(color=(value, 80, 140, 255))
                DrawBotApp._queue_recovery_checkpoint(app, include_image=True)
                self.assertIs(app._recovery_image_job, first_job)
            self.assertEqual(len(snapshots), 1)
            latest = app.original
            app.subject_region = (.5, .1, .9, .8)
            release.set()
            self.complete(app, first_job)
            self.assertFalse(recovery.STATE_FILE.exists())
            with self.assertRaises(ValueError):snapshots[0].getpixel((0, 0))
            app.root.run_next()
            self.complete(app)
        self.assertEqual(len(snapshots), 2)
        state = recovery.load_snapshot()
        with recovery.load_cached_image(state['image_sha256']) as cached:
            self.assertEqual(cached.tobytes(), latest.tobytes())
        self.assertEqual(state['subject_selection']['region'], list(app.subject_region))
        self.assertIs(app._recovery_source_ref(), latest)
        self.assert_no_staging()

    def test_failed_publication_preserves_prior_source_and_selection_then_retries(self):
        old, new = self.source(color='red'), self.source(color='green', size=(13, 7))
        app = self.app(old)
        self.assertTrue(DrawBotApp._save_recovery_checkpoint(app, include_image=True))
        previous = recovery.STATE_FILE.read_bytes()
        old_state = recovery.load_snapshot()
        app.original = new
        app.subject_region = (.5, .2, .9, .8)
        DrawBotApp._queue_recovery_checkpoint(app, include_image=True)
        with patch.object(recovery, 'atomic_write_text', side_effect=OSError('disk full')):
            self.complete(app)
        self.assertEqual(recovery.STATE_FILE.read_bytes(), previous)
        self.assertIs(app._recovery_source_ref(), old)
        with recovery.load_cached_image(old_state['image_sha256']) as cached:
            self.assertEqual(cached.tobytes(), old.tobytes())
        self.assert_no_staging()
        DrawBotApp._queue_recovery_checkpoint(app)
        self.complete(app)
        state = recovery.load_snapshot()
        self.assertNotEqual(state['image_sha256'], old_state['image_sha256'])
        self.assertEqual(state['subject_selection']['region'], list(app.subject_region))
        self.assertIs(app._recovery_source_ref(), new)

    def test_ready_cancelled_result_does_not_replace_the_previous_checkpoint(self):
        old, new = self.source(color='red'), self.source(color='green')
        app = self.app(old)
        DrawBotApp._save_recovery_checkpoint(app, include_image=True)
        previous = recovery.STATE_FILE.read_bytes()
        app.original = new
        DrawBotApp._queue_recovery_checkpoint(app, include_image=True)
        job = app._recovery_image_job
        self.assertTrue(job.wait_idle(5))
        job.cancel()
        self.complete(app, job)
        self.assertEqual(recovery.STATE_FILE.read_bytes(), previous)
        self.assertIs(app._recovery_source_ref(), old)
        self.assert_no_staging()

    def test_collected_original_and_empty_ui_cannot_match_two_none_identities(self):
        source = Image.new('RGBA', (7, 5), 'red')
        source_ref = weakref.ref(source)
        app = self.app(source)
        DrawBotApp._queue_recovery_checkpoint(app, include_image=True)
        job = app._recovery_image_job
        self.assertTrue(job.wait_idle(5))
        app.original = None
        del source
        gc.collect()
        self.assertIsNone(source_ref())
        self.complete(app, job)
        self.assertIsNone(recovery.load_snapshot())
        self.assert_no_staging()

    def test_late_png_commit_preserves_new_draw_progress_and_selection_only_reuses_it(self):
        app = self.app(self.source())
        DrawBotApp._queue_recovery_checkpoint(app, include_image=True)
        self.assertTrue(app._recovery_image_job.wait_idle(5))
        # Image adoption already cleared the previous draw. A new draw can
        # legitimately have saved its progress while this PNG was encoding.
        progress = b'new draw progress must survive image publication'
        recovery.RENDER_FILE.write_bytes(progress)
        self.complete(app)
        self.assertEqual(recovery.RENDER_FILE.read_bytes(), progress)
        app.subject_focus.set('Subject first')
        with patch.object(preparation, 'RecoveryImageJob', side_effect=AssertionError('No redundant copy/encoder')):
            self.assertTrue(DrawBotApp._queue_recovery_checkpoint(app))
        self.assertEqual(recovery.load_snapshot()['subject_selection']['mode'], 'Subject first')
        self.assertEqual(recovery.RENDER_FILE.read_bytes(), progress)

    def test_thread_start_failure_closes_private_copy_and_preserves_the_ui_source(self):
        source = self.source()
        app = self.app(source)
        copied = []
        copy = Image.Image.copy
        def capture(image):
            result = copy(image)
            if image is source:copied.append(result)
            return result
        with patch.object(Image.Image, 'copy', capture), \
                patch.object(threading.Thread, 'start', side_effect=RuntimeError('cannot create thread')):
            self.assertFalse(DrawBotApp._queue_recovery_checkpoint(app, include_image=True))
        self.assertIsNone(app._recovery_image_job)
        self.assertEqual(source.getpixel((0, 0)), (0, 0, 255, 255))
        self.assertEqual(len(copied), 1)
        with self.assertRaises(ValueError):copied[0].getpixel((0, 0))
        self.assert_no_staging()

    def test_failed_encode_closes_converted_core_even_while_exception_is_retained(self):
        source = self.source(mode='RGB')
        converted = []
        convert = Image.Image.convert
        def capture(image, *args, **kwargs):
            result = convert(image, *args, **kwargs)
            converted.append(result)
            return result
        with patch.object(Image.Image, 'convert', capture), \
                patch.object(Image.Image, 'save', side_effect=OSError('encoder failed')):
            with self.assertRaisesRegex(OSError, 'encoder failed') as caught:
                preparation.prepare_image(source)
        self.assertIsNotNone(caught.exception)
        self.assertEqual(len(converted), 1)
        with self.assertRaises(ValueError):converted[0].getpixel((0, 0))
        self.assertEqual(source.getpixel((0, 0)), (0, 0, 255))
        self.assert_no_staging()

    def test_encoder_stop_and_snapshot_cleanup_failure_still_notify_idle_with_primary_error(self):
        source = self.source()
        delivered = queue.Queue()
        job = preparation.RecoveryImageJob(source, delivered.put)
        snapshot = job._snapshot
        real_close = snapshot.close
        def failed_close():
            real_close()
            raise OSError('close failed after cleanup')
        with patch.object(preparation, 'prepare_image', side_effect=InterruptedError('primary Stop')), \
                patch.object(snapshot, 'close', side_effect=failed_close):
            job.start()
            self.assertTrue(job.wait_idle(3))
            self.assertIs(delivered.get(timeout=3), job)
            result, error = job.take()
        self.assertIsNone(result)
        self.assertIsInstance(error, InterruptedError)
        self.assertTrue(any('OSError' in note for note in error.__notes__))
        self.assertFalse(job.is_alive())
        with self.assertRaises(ValueError):snapshot.getpixel((0, 0))

    def test_clear_removes_abandoned_private_png_but_refuses_unexpected_directory_contents(self):
        first = self.directory/'.recovery-pending-abandoned'
        first.mkdir()
        (first/'image.png').write_bytes(b'partial PNG')
        recovery.clear_snapshot()
        self.assertFalse(first.exists())
        second = self.directory/'.recovery-pending-unexpected'
        second.mkdir()
        unrelated = second/'unrecognized.txt'
        unrelated.write_bytes(b'preserve unknown contents')
        with self.assertRaisesRegex(OSError, 'could not be completely removed'):
            recovery.clear_snapshot()
        self.assertEqual(unrelated.read_bytes(), b'preserve unknown contents')


if __name__ == '__main__':
    unittest.main()
