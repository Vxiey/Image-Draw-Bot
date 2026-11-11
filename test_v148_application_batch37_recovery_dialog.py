"""A recovery decision applies only to the checkpoint and source it offered.

Every raster comes from an existing repository PNG. Storage, encoder/loader
threads, cancellation, Tcl variables and result adoption run normally; only
the modal answer and selected interleaving boundaries are controlled here.
"""
from contextlib import contextmanager, ExitStack
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
import RenderResume
import SessionRecovery as recovery


ASSETS = Path(__file__).resolve().parent / 'assets'


class RecoveryDialogIdentityTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name, filename in (
                ('RECOVERY_DIR', ''), ('STATE_FILE', 'session-recovery.json'),
                ('IMAGE_FILE', 'last-image.png'), ('RENDER_FILE', 'render-resume.json')):
            self.stack.enter_context(patch.object(recovery, name, self.directory / filename))
        self.stack.enter_context(patch('DrawBot.previous_run_unclean', return_value=False))
        self.root = tk.Tcl()
        self.images, self.variables, self.jobs, self.workers, self.releases = [], [], [], [], []
        self.source = self.source_image('paint-tools-reference.png')
        self.offered_source = self.source_image('image-draw-bot-icon.png')
        self.app = SimpleNamespace(
            root=self.root, closing=False, shutdown_complete=False,
            activity=None, worker=None, original=self.source, plan=None,
            saved_area=None, corners=[], subject_region=None, mouse=None,
            background_removal_original=None, upscale_original=None,
            color_session_cache={}, events=queue.Queue(), stop=threading.Event(),
            _recovery_image_job=None, _recovery_save_pending=False,
            recovery_image_pending=False, recovery_checkpoint_after=None,
            pending_clear_drawing=None, needs_plan=False, show_previews=lambda: None,
        )
        for name, value in {
                'game': 'Other drawing app', 'quality': 'Balanced',
                'subject_focus': 'Off', 'subject_hint': '', 'status': 'Ready',
                'file_label': 'Current asset', 'preview_mode': 'Auto full',
                'color_plan_text': '', 'summary': '', 'area_text': ''}.items():
            variable = tk.StringVar(master=self.root, value=value)
            self.variables.append((name, variable))
            setattr(self.app, name, variable)
        # No native widget tree is created. These are the actual worker and
        # adoption paths; enabling widgets and painting previews are omitted.
        self.app.set_busy = lambda activity: setattr(self.app, 'activity', activity)
        for name in ('begin_worker', '_mark_plan_stale', '_sync_mobile_preview'):
            setattr(self.app, name, MethodType(getattr(DrawBotApp, name), self.app))
        self.addCleanup(self.close_resources)
        recovery.save_snapshot(profile='Other drawing app', options={'quality': 'High detail'},
                               image=self.offered_source, saved_area=[(10, 20), (110, 120)])
        recovery.save_render_progress(RenderResume.new_progress({'image': self.offered_source}))
        self.offered_state = recovery.load_snapshot()
        self.app.pending_render_resume = self.offered_state['render_resume']
        self.before = self.payloads()

    def source_image(self, filename):
        with Image.open(ASSETS / filename) as existing:
            image = existing.convert('RGBA')
        self.images.append(image)
        return image

    @staticmethod
    def pixels(image):
        return image.mode, image.size, image.tobytes()

    def payloads(self):
        return {path.name: path.read_bytes() for path in self.directory.iterdir()
                if path.is_file() and path.suffix in ('.json', '.png')}

    def close_resources(self):
        self.app.closing = True
        self.app.stop.set()
        for release in self.releases:
            release.set()
        for job in self.jobs:
            job.cancel()
            if job._thread is not None:
                self.workers.append(job._thread)
        worker = self.app.worker
        if worker is not None:
            self.workers.append(worker)
        for worker in self.workers:
            worker.join(5)
            self.assertFalse(worker.is_alive(), 'An owned worker did not finish.')
        for token in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(token)
        while not self.app.events.empty():
            kind, value = self.app.events.get_nowait()
            DrawBotApp._discard_worker_result(self.app, kind, value)
        pending = getattr(self.app, 'recovery_loaded_pending', None)
        if pending is not None:
            DrawBotApp._discard_worker_result(self.app, 'recovery_loaded', pending)
        for image in self.images:
            image.close()
        while self.variables:
            name, variable = self.variables.pop()
            setattr(self.app, name, None)
            del variable
        # Even a non-screen worker owns this creator-thread Tcl alias. Retire
        # it after joining workers, before later worker GC can collect the app.
        screen_window = getattr(self.app, 'screen_task_window', None)
        if screen_window is not None:
            screen_window.root = None
        self.app.screen_task_window = None
        self.app.root = None
        self.root = None

    def offer(self, answer, during_dialog=lambda: None):
        def respond(*args, **kwargs):
            during_dialog()
            return answer
        with patch('DrawBot.messagebox.askyesno', side_effect=respond) as dialog:
            try:
                DrawBotApp.offer_safe_session_recovery(self.app)
                dialog.assert_called_once()
            finally:
                # Mock call history also borrows parent=self.root. Do not leave
                # that Tcl alias in mock cycles for a later worker to collect.
                dialog.reset_mock(return_value=True, side_effect=True)
        if self.app.worker is not None:
            self.workers.append(self.app.worker)

    def drain(self):
        while not self.app.events.empty():
            kind, value = self.app.events.get_nowait()
            if kind == 'recovery_loaded' and value[1] is not None:
                self.images.append(value[1])
            DrawBotApp._handle_event(self.app, kind, value)

    def finish_worker(self):
        worker = self.app.worker
        self.assertIsNotNone(worker)
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.drain()

    def start_encoder(self):
        self.assertTrue(DrawBotApp._queue_recovery_checkpoint(self.app, include_image=True))
        job = self.app._recovery_image_job
        self.jobs.append(job)
        self.assertIsNotNone(job)
        return job

    def finish_encoder(self, job):
        job._thread.join(5)
        self.assertFalse(job._thread.is_alive())
        self.drain()

    @contextmanager
    def blocked_encoder(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        native_save = Image.Image.save

        def save(image, *args, **kwargs):
            if threading.current_thread().name == 'recovery-image-encoder':
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('The test did not release the real encoder.')
            return native_save(image, *args, **kwargs)

        with patch.object(Image.Image, 'save', save):
            try:
                yield entered, release
            finally:
                release.set()

    def assert_cached_pixels(self, source):
        state = recovery.load_snapshot()
        self.assertIsNotNone(state)
        cached = recovery.load_cached_image(state['image_sha256'])
        self.assertIsNotNone(cached)
        try:
            self.assertEqual(self.pixels(cached), self.pixels(source))
        finally:
            cached.close()

    def changed_checkpoint(self, answer):
        published = {}

        def autosave():
            job = self.start_encoder()
            self.finish_encoder(job)
            recovery.save_render_progress(RenderResume.new_progress({'image': self.source}))
            published.update(self.payloads())
            self.assertNotEqual(recovery.load_snapshot()['image_sha256'], self.offered_state['image_sha256'])

        self.offer(answer, autosave)
        self.assertIsNone(self.app.worker, 'An older modal choice must not start recovery work.')
        self.assertEqual(self.payloads(), published)
        self.assertIs(self.app.original, self.source)
        self.assert_cached_pixels(self.source)
        self.assertIn('changed', self.app.status.get().lower())

    def test_yes_does_not_restore_a_checkpoint_replaced_during_the_dialog(self):
        self.changed_checkpoint(True)

    def test_no_does_not_delete_a_checkpoint_replaced_during_the_dialog(self):
        self.changed_checkpoint(False)

    def changed_source(self, answer):
        replacement = self.source_image('image-draw-bot-icon.png')
        with self.blocked_encoder() as (entered, release):
            started = []

            def replace_source():
                self.app.original = replacement
                started.append(self.start_encoder())
                self.assertTrue(entered.wait(3))

            self.offer(answer, replace_source)
            job = started[0]
            self.assertIsNone(self.app.worker)
            self.assertIs(self.app.original, replacement)
            self.assertEqual(self.payloads(), self.before)
            self.assertFalse(job._cancelled.is_set(), 'The new source still owns its encoder.')
            self.assertTrue(job.is_alive())
            self.assertIn('changed', self.app.status.get().lower())
            release.set()
            self.finish_encoder(job)
        self.assert_cached_pixels(replacement)

    def test_yes_keeps_a_new_source_and_its_owned_encoder(self):
        self.changed_source(True)

    def test_no_keeps_a_new_source_and_its_owned_encoder(self):
        self.changed_source(False)

    def test_accepted_yes_retires_pending_autosave_before_restoring_the_offered_image(self):
        with self.blocked_encoder() as (entered, release):
            job = self.start_encoder()
            self.assertTrue(entered.wait(3))
            token = self.root.after(10000, lambda: DrawBotApp._queue_recovery_checkpoint(self.app))
            self.app.recovery_checkpoint_after = token
            self.app.recovery_image_pending = True
            self.offer(True)
            self.assertTrue(job._cancelled.is_set())
            self.assertIsNone(self.app.recovery_checkpoint_after)
            self.assertFalse(self.app.recovery_image_pending)
            self.assertNotIn(token, self.root.tk.splitlist(self.root.tk.call('after', 'info')))
            release.set()
            job._thread.join(5)
            self.assertFalse(job._thread.is_alive())
            self.finish_worker()
        self.assertEqual(self.pixels(self.app.original), self.pixels(self.offered_source))
        self.assertEqual(self.payloads(), self.before)
        self.assertIs(self.app._recovery_source_ref(), self.app.original)
        self.assertTrue(DrawBotApp._queue_recovery_checkpoint(self.app))
        self.assert_cached_pixels(self.app.original)
        self.assertEqual(list(self.directory.glob('.recovery-pending-*')), [])

    def test_no_compares_again_after_waiting_for_its_cancelled_encoder(self):
        resume = self.app.pending_render_resume
        with self.blocked_encoder() as (entered, release):
            job = self.start_encoder()
            self.assertTrue(entered.wait(3))
            self.offer(False)
            self.assertEqual(self.app.activity, 'recovery-clear')
            self.assertTrue(job._cancelled.is_set())
            self.assertTrue(self.app._suppress_recovery)
            recovery.save_snapshot(profile='Other drawing app', options={'quality': 'Maximum detail'},
                                   image=self.source)
            recovery.save_render_progress(RenderResume.new_progress({'image': self.source}))
            newer = self.payloads()
            release.set()
            job._thread.join(5)
            self.assertFalse(job._thread.is_alive())
            self.finish_worker()
        self.assertEqual(self.payloads(), newer)
        self.assertFalse(self.app._suppress_recovery)
        self.assertIs(self.app.pending_render_resume, resume)
        self.assertIn('changed', self.app.status.get().lower())
        self.assert_cached_pixels(self.source)
        # A rejected clear restores normal autosave admission; it cannot revive
        # the already-cancelled encoder, but a fresh real job must succeed.
        retry = self.start_encoder()
        self.finish_encoder(retry)
        self.assert_cached_pixels(self.source)

    def test_unchanged_yes_loads_exact_pixels_and_settings_with_input_disarmed(self):
        self.offer(True)
        self.assertEqual(self.app.activity, 'recovery-load')
        self.finish_worker()
        self.assertIsNone(self.app.activity)
        self.assertEqual(self.pixels(self.app.original), self.pixels(self.offered_source))
        self.assertEqual(self.app.quality.get(), 'High detail')
        self.assertEqual(self.app.preview_mode.get(), 'Manual')
        self.assertEqual(self.app.saved_area, [(10, 20), (110, 120)])
        for name in ('small_test_passed', 'target_lock_passed', 'safety_preflight_passed', 'dry_run_passed'):
            self.assertFalse(getattr(self.app, name), name)
        self.assertEqual(self.app.full_draw_armed_until, 0.)
        self.assertEqual(self.payloads(), self.before)

    def test_unchanged_no_keeps_current_image_and_existing_suppression_policy(self):
        before = self.pixels(self.source)
        self.app._suppress_recovery = False
        self.offer(False)
        self.assertIsNone(self.app.worker)
        self.assertEqual(self.payloads(), {})
        self.assertIs(self.app.original, self.source)
        self.assertEqual(self.pixels(self.source), before)
        self.assertFalse(self.app._suppress_recovery)

    def test_no_serializes_conditional_deletion_with_a_real_racing_publisher(self):
        native_clear = recovery.clear_snapshot
        published = threading.Event()
        failures, order = [], []

        def publish():
            order.append('publisher-requested')
            try:
                recovery.save_snapshot(profile='Other drawing app', options={'quality': 'Maximum detail'},
                                       image=self.source)
            except BaseException as failure:
                failures.append(failure)
            finally:
                order.append('publisher-finished')
                published.set()

        def competing_clear():
            thread = threading.Thread(target=publish, name='checkpoint-publisher')
            self.workers.append(thread)
            thread.start()
            # The conditional operation must already own the real snapshot
            # guard. A publisher cannot finish in the check/delete interval.
            published.wait(1)
            native_clear()
            order.append('clear-finished')

        with patch.object(recovery, 'clear_snapshot', competing_clear):
            self.offer(False)
        self.assertTrue(published.wait(5))
        self.workers[-1].join(5)
        self.assertFalse(self.workers[-1].is_alive())
        self.assertEqual(failures, [])
        self.assertLess(order.index('clear-finished'), order.index('publisher-finished'))
        self.assert_cached_pixels(self.source)
        self.assertEqual(recovery.load_snapshot()['options']['quality'], 'Maximum detail')

    def test_busy_and_closing_before_or_after_the_dialog_preserve_all_data(self):
        for answer in (False, True):
            for field, value in (('closing', True), ('activity', 'draw')):
                for moment in ('before', 'during'):
                    with self.subTest(answer=answer, field=field, moment=moment):
                        self.app.closing, self.app.activity = False, None
                        if moment == 'before':
                            setattr(self.app, field, value)
                        def respond(*args, **kwargs):
                            setattr(self.app, field, value)
                            return answer
                        with patch('DrawBot.messagebox.askyesno', side_effect=respond) as dialog:
                            try:
                                DrawBotApp.offer_safe_session_recovery(self.app)
                                self.assertEqual(dialog.call_count, int(moment == 'during'))
                            finally:
                                dialog.reset_mock(return_value=True, side_effect=True)
                        self.assertIsNone(self.app.worker)
                        self.assertEqual(self.payloads(), self.before)
                        self.assertIs(self.app.original, self.source)
        self.app.closing, self.app.activity = False, None


if __name__ == '__main__':
    unittest.main()
