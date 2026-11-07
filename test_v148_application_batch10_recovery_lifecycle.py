"""Real recovery workers cannot resurrect cleared data or outlive UI cleanup."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import queue
import tempfile
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

from PIL import Image

from DrawBot import DrawBotApp
import RecoveryImagePreparation as preparation
import RenderResume
import SessionRecovery as recovery
from test_smart_recovery_resume_v1079 import plan as resume_plan


class UiRoot:
    def __init__(self):
        self.owner = threading.get_ident()
        self.jobs = {}
        self.serial = 0
        self.now = 0
        self.destroyed = False

    def ui(self):
        if threading.get_ident() != self.owner:
            raise AssertionError('A background recovery worker called Tk.')

    def after(self, delay, callback):
        self.ui()
        self.serial += 1
        self.jobs[self.serial] = (self.now + delay, callback)
        return self.serial

    def after_cancel(self, token):
        self.ui()
        self.jobs.pop(token, None)

    def run_next(self):
        self.ui()
        token = min(self.jobs, key=lambda item: (self.jobs[item][0], item))
        self.now, callback = self.jobs.pop(token)
        callback()

    def destroy(self):
        self.ui()
        self.destroyed = True

    def deiconify(self):
        self.ui()


class UiValue:
    def __init__(self, root, value=''):
        self.root, self.value = root, value

    def get(self):
        self.root.ui()
        return self.value

    def set(self, value):
        self.root.ui()
        self.value = value


class RecoveryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.directory = Path(directory)
        for name, path in (
                ('RECOVERY_DIR', self.directory),
                ('STATE_FILE', self.directory/'session-recovery.json'),
                ('IMAGE_FILE', self.directory/'last-image.png'),
                ('RENDER_FILE', self.directory/'render-resume.json')):
            self.stack.enter_context(patch.object(recovery, name, path))
        for name in ('_close_smart_drop_overlay', '_disarm_manual_drop_in', '_disarm_full_draw'):
            self.stack.enter_context(patch.object(DrawBotApp, name))
        for name in ('log_event', 'log_error', 'clean_exit'):
            self.stack.enter_context(patch('DrawBot.'+name))
        self.original_plan = resume_plan()
        self.original = self.original_plan['image']
        self.addCleanup(self.original.close)
        recovery.save_snapshot(profile='Other drawing app', options={}, image=self.original)
        self.resume = RenderResume.checkpoint_before_path(
            self.original_plan, 1, 1, 2, ordered_items=self.original_plan['execution_groups'][0])
        recovery.save_render_progress(self.resume)
        self.previous = self.payloads()
        root = UiRoot()
        self.app = SimpleNamespace(
            root=root, closing=False, shutdown_complete=False, activity=None, worker=None,
            stop=threading.Event(), paused=threading.Event(), events=queue.Queue(),
            original=self.original, plan=self.original_plan, pending_render_resume=self.resume,
            _recovery_source_ref=weakref.ref(self.original), _recovery_image_job=None,
            _recovery_save_pending=False, _suppress_recovery=False,
            recovery_image_pending=False, recovery_checkpoint_after=None,
            pending_clear_drawing=None, recovery_loaded_pending=None,
            saved_area=None, corners=[], target_lock_passed=False,
            subject_focus=UiValue(root, 'Off'), subject_region=None,
            game=UiValue(root, 'Other drawing app'), status=UiValue(root),
            file_label=UiValue(root, 'source'), url=UiValue(root), summary=UiValue(root),
            color_session_cache={}, progress={'value': 10}, needs_plan=False,
            small_test_passed=False, upscale_original=None, screen_task_window=None,
            show_previews=Mock(), _sync_mobile_preview=Mock(), save_settings=Mock(return_value=True),
            _remove_hotkeys=Mock(), stop_mobile_preview=Mock(),
        )
        def set_busy(activity):
            root.ui()
            self.app.activity = activity
        self.app.set_busy = set_busy
        for name in ('begin_worker', 'cancel', '_handle_event', '_finish_shutdown'):
            setattr(self.app, name, MethodType(getattr(DrawBotApp, name), self.app))
        self.jobs = []
        self.releases = []
        self.addCleanup(self.finish_workers)

    def payloads(self):
        return {path.name: path.read_bytes() for path in self.directory.iterdir()
                if path.is_file() and path.suffix in ('.json', '.png')}

    def finish_workers(self):
        self.app.stop.set()
        for release in self.releases:
            release.set()
        for job in self.jobs:
            try:
                job.cancel()
            except OSError:
                pass
            thread = job._thread
            if thread is not None:
                thread.join(5)
        worker = self.app.worker
        if worker is not None:
            worker.join(5)

    @contextmanager
    def blocked_encoder(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        save = Image.Image.save
        def encode(image, *args, **kwargs):
            if threading.current_thread().name == 'recovery-image-encoder':
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('The test did not release the image encoder.')
            return save(image, *args, **kwargs)
        with patch.object(Image.Image, 'save', encode):
            self.assertTrue(DrawBotApp._queue_recovery_checkpoint(self.app, include_image=True))
            job = self.app._recovery_image_job
            self.jobs.append(job)
            self.assertTrue(entered.wait(3), 'The real encoder thread must reach PNG save.')
            try:
                yield job, release
            finally:
                release.set()
                job._thread.join(5)
                self.assertFalse(job._thread.is_alive())

    def drain_events(self):
        handled = []
        while True:
            try:
                kind, value = self.app.events.get_nowait()
            except queue.Empty:
                return handled
            handled.append(kind)
            DrawBotApp._handle_event(self.app, kind, value)

    def assert_previous_resume(self):
        self.assertEqual(self.payloads(), self.previous)
        loaded = recovery.load_snapshot()
        self.assertTrue(RenderResume.resolve_resume(self.original_plan, loaded['render_resume'])['compatible'])
        self.assertIs(self.app.pending_render_resume, self.resume)

    def test_explicit_clear_uses_actual_tracked_worker_and_cannot_resurrect_old_data(self):
        with self.blocked_encoder() as (job, release):
            DrawBotApp.clear_recovery_snapshot(self.app)
            worker = self.app.worker
            self.assertEqual(self.app.activity, 'recovery-clear')
            self.assertTrue(worker.is_alive())
            self.assertTrue(job.is_alive())
            self.assertTrue(self.app._suppress_recovery)
            self.assertEqual(self.payloads(), self.previous)
            heartbeat = []
            self.app.root.after(1, lambda: heartbeat.append('responsive'))
            self.app.root.run_next()
            self.assertEqual(heartbeat, ['responsive'])
            release.set()
            job._thread.join(3); worker.join(3)
            self.assertFalse(job._thread.is_alive()); self.assertFalse(worker.is_alive())
            kinds = self.drain_events()
            self.assertIn('recovery_clear_complete', kinds)
            self.assertIn('done', kinds)
            self.assertIsNone(self.app.activity)
            self.assertIsNone(self.app.pending_render_resume)
            self.assertTrue(self.app._suppress_recovery)
            self.assertEqual(self.payloads(), {})
            self.assertEqual(list(self.directory.glob('.recovery-pending-*')), [])
            # A delayed duplicate completion never restores the cancelled PNG.
            DrawBotApp._handle_event(self.app, 'recovery_image_prepared', job)
            self.assertFalse(DrawBotApp._queue_recovery_checkpoint(self.app, include_image=True))
            self.assertEqual(self.payloads(), {})
            self.assertEqual(self.original.getpixel((0, 0)), (255, 255, 255))

    def test_stop_during_clear_preserves_the_previous_usable_resume(self):
        with self.blocked_encoder() as (job, release):
            DrawBotApp.clear_recovery_snapshot(self.app)
            worker = self.app.worker
            DrawBotApp.cancel(self.app)
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertTrue(job.is_alive())
            self.drain_events()
            self.assertTrue(self.app.stop.is_set())
            self.assertIsNone(self.app.activity)
            self.assertFalse(self.app._suppress_recovery)
            self.assert_previous_resume()
            release.set(); job._thread.join(3)
            self.drain_events()
            self.assert_previous_resume()

    def test_failed_clear_restores_previous_suppression_and_resume(self):
        with self.blocked_encoder() as (job, release):
            with patch.object(recovery, 'clear_snapshot', side_effect=OSError('checkpoint is locked')) as clear:
                DrawBotApp.clear_recovery_snapshot(self.app)
                worker = self.app.worker
                release.set(); job._thread.join(3); worker.join(3)
                self.assertFalse(worker.is_alive())
                self.drain_events()
            clear.assert_called_once()
            self.assertFalse(self.app._suppress_recovery)
            self.assertIsNone(self.app.activity)
            self.assertIn('checkpoint is locked', self.app.status.get())
            self.assert_previous_resume()

    def test_failed_clear_worker_start_does_not_permanently_disable_recovery(self):
        with self.blocked_encoder() as (job, release):
            failure = RuntimeError('cannot start recovery clear thread')
            with patch.object(threading.Thread, 'start', side_effect=failure):
                try:
                    DrawBotApp.clear_recovery_snapshot(self.app)
                except RuntimeError as error:
                    self.assertIs(error, failure)
            self.assertIsNone(self.app.activity)
            self.assertIsNone(self.app.worker)
            self.assertFalse(self.app._suppress_recovery)
            self.assert_previous_resume()
            release.set(); job._thread.join(3)
            self.drain_events()
            self.assert_previous_resume()

    def test_stop_before_clear_task_enters_restores_recovery_after_done(self):
        with self.blocked_encoder() as (job, release):
            entered, start_task = threading.Event(), threading.Event()
            self.releases.append(start_task)
            real_thread = threading.Thread
            def new_thread(*args, **kwargs):
                target = kwargs.get('target')
                if kwargs.get('name') == 'imagedrawbot-recovery-clear':
                    def delayed():
                        entered.set()
                        if not start_task.wait(10):
                            raise TimeoutError('The test did not release worker startup.')
                        target()
                    kwargs['target'] = delayed
                return real_thread(*args, **kwargs)
            with patch('DrawBot.threading.Thread', side_effect=new_thread):
                DrawBotApp.clear_recovery_snapshot(self.app)
            worker = self.app.worker
            self.assertTrue(entered.wait(3))
            DrawBotApp.cancel(self.app)
            start_task.set(); worker.join(3)
            self.assertFalse(worker.is_alive())
            kinds = self.drain_events()
            self.assertIn('done', kinds)
            self.assertIsNone(self.app.activity)
            self.assertFalse(self.app._suppress_recovery)
            self.assert_previous_resume()
            release.set(); job._thread.join(3)
            self.drain_events()
            self.assert_previous_resume()

    def test_clear_drawing_waits_for_encoder_without_blocking_ui_or_keeping_late_result(self):
        for remove_image in (False, True):
            with self.subTest(remove_image=remove_image):
                self.app._suppress_recovery = False
                self.app.original = self.original
                self.app.plan = self.original_plan
                self.app.pending_render_resume = self.resume
                recovery.save_snapshot(profile='Other drawing app', options={}, image=self.original)
                recovery.save_render_progress(self.resume)
                with self.blocked_encoder() as (job, release):
                    DrawBotApp._request_clear_drawing(self.app, remove_image)
                    self.assertEqual(self.app.pending_clear_drawing, remove_image)
                    self.assertIs(self.app.original, self.original)
                    self.assertTrue(recovery.STATE_FILE.exists())
                    heartbeat = []
                    self.app.root.after(1, lambda: heartbeat.append(True))
                    self.app.root.run_next()
                    self.assertEqual(heartbeat, [True])
                    release.set(); job._thread.join(3)
                    self.drain_events()
                    self.assertIsNone(self.app._recovery_image_job)
                    self.app.root.run_next()
                    self.assertIsNone(self.app.pending_clear_drawing)
                    self.assertIsNone(self.app.plan)
                    self.assertIsNone(self.app.pending_render_resume)
                    self.assertIs(self.app.original, None if remove_image else self.original)
                    self.assertTrue(self.app._suppress_recovery)
                    self.assertEqual(self.payloads(), {})
                    DrawBotApp._handle_event(self.app, 'recovery_image_prepared', job)
                    self.assertEqual(self.payloads(), {})

    def test_pending_clear_discards_an_already_prepared_result_before_old_worker_done(self):
        self.assertTrue(DrawBotApp._queue_recovery_checkpoint(self.app, include_image=True))
        job = self.app._recovery_image_job; self.jobs.append(job)
        job._thread.join(3)
        self.assertFalse(job._thread.is_alive())
        self.assertTrue(list(self.directory.glob('.recovery-pending-*/image.png')))
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def work():
            entered.set()
            if not release.wait(10):
                raise TimeoutError('The test did not release the previous UI worker.')
        self.assertTrue(DrawBotApp.begin_worker(self.app, 'preview', work))
        worker = self.app.worker
        self.assertTrue(entered.wait(3))
        DrawBotApp._request_clear_drawing(self.app, False)
        self.assertIsNotNone(self.app.pending_clear_drawing)
        self.drain_events()
        self.assertIsNone(self.app._recovery_image_job)
        self.assertEqual(list(self.directory.glob('.recovery-pending-*')), [])
        self.assertTrue(worker.is_alive())
        self.assertEqual(self.payloads(), self.previous)
        release.set(); worker.join(3)
        self.drain_events()
        self.app.root.run_next()
        self.assertEqual(self.payloads(), {})
        self.assertIsNone(self.app.pending_clear_drawing)
        DrawBotApp._handle_event(self.app, 'recovery_image_prepared', job)
        self.assertEqual(self.payloads(), {})

    def test_shutdown_keeps_ui_responsive_until_owned_encoder_cleanup_finishes(self):
        with self.blocked_encoder() as (job, release):
            DrawBotApp.close(self.app)
            self.assertTrue(self.app.closing)
            self.assertFalse(self.app.shutdown_complete)
            self.assertFalse(self.app.root.destroyed)
            self.assertTrue(recovery.STATE_FILE.exists())
            token = self.app.recovery_shutdown_after
            DrawBotApp._finish_shutdown(self.app)
            self.assertEqual(self.app.recovery_shutdown_after, token)
            heartbeat = []
            self.app.root.after(1, lambda: heartbeat.append(True))
            self.app.root.run_next()
            self.assertEqual(heartbeat, [True])
            self.assertTrue(job.is_alive())
            release.set(); job._thread.join(3)
            self.app.root.run_next()
            self.assertTrue(self.app.shutdown_complete)
            self.assertTrue(self.app.root.destroyed)
            self.assertIsNone(self.app._recovery_image_job)
            self.assertEqual(self.payloads(), {})
            self.assertEqual(list(self.directory.glob('.recovery-pending-*')), [])
            self.drain_events()
            self.assertEqual(self.payloads(), {})


if __name__ == '__main__':
    unittest.main()
