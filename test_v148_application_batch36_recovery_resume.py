"""Accepted background edits resume autosave after an explicit cache clear.

The source is an existing repository PNG. Background removal, its real worker,
the controller, Tcl timers, recovery encoder and disk publication all run here.
No native window or external input is needed; only preview painting is omitted.
"""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from DrawBot import DrawBotApp
import SessionRecovery as recovery


ASSET = Path(__file__).resolve().parent / 'assets' / 'paint-tools-reference.png'


class RecoveryAfterBackgroundEditTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name, filename in (
                ('RECOVERY_DIR', ''), ('STATE_FILE', 'session-recovery.json'),
                ('IMAGE_FILE', 'last-image.png'), ('RENDER_FILE', 'render-resume.json')):
            self.stack.enter_context(patch.object(recovery, name, self.directory / filename))
        self.root = tk.Tcl()
        self.callback_errors = []
        self.root.report_callback_exception = lambda kind, value, tb: self.callback_errors.append(
            f'{kind.__name__}: {value}')
        self.images, self.workers, self.variables = [], [], []
        with Image.open(ASSET) as existing:
            self.source = self.own(existing.copy())
        self.original_pixels = self.pixels(self.source)
        self.app = SimpleNamespace(
            root=self.root, closing=False, shutdown_complete=False,
            activity=None, worker=None, original=self.source, plan=None,
            saved_area=None, corners=[], subject_region=None,
            background_removal_original=None, background_removal_meta=None,
            upscale_original=None, color_session_cache={}, events=queue.Queue(),
            stop=threading.Event(), paused=threading.Event(), progress={'value': 0},
            _recovery_image_job=None, _recovery_save_pending=False,
            recovery_image_pending=False, recovery_checkpoint_after=None,
            pending_clear_drawing=None, needs_plan=False, show_previews=lambda: None,
        )
        for name, value in {
                'game': 'Other drawing app', 'quality': 'Balanced', 'subject_focus': 'Off',
                'status': 'Ready', 'file_label': 'Existing asset', 'preview_mode': 'Manual',
                'color_plan_text': '', 'summary': '', 'url': ''}.items():
            variable = tk.StringVar(master=self.root, value=value)
            self.variables.append((name, variable))
            setattr(self.app, name, variable)
        # The fixture has no widget tree to enable/disable. The actual worker
        # still owns the controller's activity until its real done event.
        self.app.set_busy = lambda activity: setattr(self.app, 'activity', activity)
        for name in ('begin_worker', 'cancel', '_schedule_recovery_checkpoint',
                     '_mark_plan_stale', '_sync_mobile_preview',
                     '_maybe_auto_preview', '_auto_preview_enabled'):
            setattr(self.app, name, MethodType(getattr(DrawBotApp, name), self.app))
        self.addCleanup(self.close_owned_resources)
        self.assertTrue(DrawBotApp._save_recovery_checkpoint(self.app, include_image=True))
        self.assertTrue(recovery.STATE_FILE.exists())

    @staticmethod
    def pixels(image):
        return image.mode, image.size, image.tobytes()

    def own(self, image):
        if all(image is not existing for existing in self.images):
            self.images.append(image)
        return image

    def close_owned_resources(self):
        app = self.app
        app.closing = True
        app.stop.set()
        job = getattr(app, '_recovery_image_job', None)
        if job is not None:
            job.cancel()
            if job._thread is not None:
                self.workers.append(job._thread)
        for worker in self.workers:
            worker.join(5)
            self.assertFalse(worker.is_alive(), 'An owned image worker did not finish.')
        for token in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(token)
        while not app.events.empty():
            kind, value = app.events.get_nowait()
            DrawBotApp._discard_worker_result(app, kind, value)
        history = getattr(app, 'background_removal_original', None)
        if history is not None:
            self.own(history)
        for image in self.images:
            image.close()
        # Release Tcl variables/interpreter on this owning thread, including
        # when an assertion retained the rest of the controller fixture.
        while self.variables:
            name, variable = self.variables.pop()
            setattr(app, name, None)
            del variable
        app.root = None
        self.root = None

    def run_background(self):
        self.assertTrue(DrawBotApp.remove_image_background(self.app))
        worker = self.app.worker
        self.assertIsInstance(worker, threading.Thread)
        self.workers.append(worker)
        worker.join(5)
        self.assertFalse(worker.is_alive(), 'The real background-removal worker did not finish.')
        events = []
        while not self.app.events.empty():
            events.append(self.app.events.get_nowait())
        self.assertEqual([kind for kind, _ in events], ['background_removed', 'done'])
        result = events[0][1]
        self.own(result.image)
        return result, events

    def adopt(self, events):
        for kind, value in events:
            DrawBotApp._handle_event(self.app, kind, value)
        history = self.app.background_removal_original
        if history is not None:
            self.own(history)
        self.assertIsNone(self.app.activity)

    def pump_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.root.eval('update')
            time.sleep(.002)
        self.assertTrue(predicate(), 'The actual Tcl callback did not finish before its deadline.')
        self.assertEqual(self.callback_errors, [])

    def clear_recovery(self):
        DrawBotApp.clear_recovery_snapshot(self.app)
        self.assert_suppressed()

    def assert_suppressed(self):
        self.assertTrue(self.app._suppress_recovery)
        self.assertFalse(DrawBotApp._queue_recovery_checkpoint(self.app, include_image=True))
        self.assertIsNone(self.app._recovery_image_job)
        self.assertFalse(recovery.STATE_FILE.exists())
        self.assertEqual(list(self.directory.glob('*.png')), [])
        self.assertEqual(list(self.directory.glob('.recovery-pending-*')), [])

    def finish_autosave(self):
        self.assertIsNotNone(self.app.recovery_checkpoint_after)
        self.pump_until(lambda: self.app.recovery_checkpoint_after is None)
        job = self.app._recovery_image_job
        self.assertIsNotNone(job, 'An accepted image edit must restart its recovery encoder.')
        self.assertIs(job.source(), self.app.original)
        self.assertEqual(job._thread.name, 'recovery-image-encoder')
        self.workers.append(job._thread)
        job._thread.join(5)
        self.assertFalse(job._thread.is_alive())
        kind, value = self.app.events.get(timeout=1)
        self.assertEqual(kind, 'recovery_image_prepared')
        self.assertIs(value, job)
        DrawBotApp._handle_event(self.app, kind, value)
        self.assertIsNone(self.app._recovery_image_job)
        self.assertFalse(self.app._suppress_recovery)
        self.assertIs(self.app._recovery_source_ref(), self.app.original)
        state = recovery.load_snapshot()
        self.assertIsNotNone(state)
        self.assertEqual(state['profile'], 'Other drawing app')
        self.assertEqual(state['options']['quality'], 'Balanced')
        digest = state['image_sha256']
        self.assertEqual(hashlib.sha256(recovery._image_path(digest).read_bytes()).hexdigest(), digest)
        restored = recovery.load_cached_image(expected_sha256=digest)
        self.assertIsNotNone(restored)
        try:
            self.assertEqual(self.pixels(restored), self.pixels(self.app.original))
        finally:
            restored.close()
        self.assertEqual(list(self.directory.glob('.recovery-pending-*')), [])
        self.assertEqual(self.pixels(self.source), self.original_pixels)

    def test_background_adoption_after_recovery_clear_resumes_persistent_autosave(self):
        self.clear_recovery()
        result, events = self.run_background()
        self.assertIsNone(result.metadata['no_op_reason'])
        self.assertGreater(result.metadata['removed_percent'], 0)
        self.adopt(events)
        self.assertIs(self.app.original, result.image)
        self.assertNotEqual(self.app.original.tobytes(), self.source.tobytes())
        self.finish_autosave()

    def test_background_undo_after_cached_drawing_clear_resumes_persistent_autosave(self):
        result, events = self.run_background()
        self.assertIsNone(result.metadata['no_op_reason'])
        self.adopt(events)
        history = self.app.background_removal_original
        self.assertIsNotNone(history)
        DrawBotApp.clear_cached_drawing(self.app)
        self.assertIsNone(self.app.pending_clear_drawing)
        self.assertIs(self.app.original, result.image)
        self.assertIs(self.app.background_removal_original, history)
        self.assertTrue(self.app.stop.is_set())
        self.assert_suppressed()
        self.assertTrue(DrawBotApp.undo_background_removal(self.app))
        self.assertIs(self.app.original, history)
        self.assertEqual(self.pixels(history), self.original_pixels)
        self.assertIsNone(self.app.background_removal_original)
        self.finish_autosave()
        self.assertTrue(self.app.stop.is_set(), 'Autosave must not restart stopped drawing or preview.')

    def test_noop_background_operation_keeps_explicit_recovery_clear_suppressed(self):
        first, events = self.run_background()
        self.assertIsNone(first.metadata['no_op_reason'])
        self.adopt(events)
        source, history = self.app.original, self.app.background_removal_original
        before = self.pixels(source)
        self.clear_recovery()
        # The real remover preserves this existing derived PNG's substantial
        # transparency; no synthetic transparent test image is constructed.
        noop, events = self.run_background()
        self.assertTrue(noop.metadata['no_op_reason'])
        self.adopt(events)
        self.assertIs(self.app.original, source)
        self.assertIs(self.app.background_removal_original, history)
        self.assertEqual(self.pixels(source), before)
        with self.assertRaises(ValueError):
            noop.image.getpixel((0, 0))
        self.assertIsNone(self.app.recovery_checkpoint_after)
        self.assert_suppressed()

    def test_stop_discards_real_ready_background_result_without_resuming_recovery(self):
        self.clear_recovery()
        result, events = self.run_background()
        self.assertIsNone(result.metadata['no_op_reason'])
        DrawBotApp.cancel(self.app)
        self.adopt(events)
        self.assertTrue(self.app.stop.is_set())
        self.assertIs(self.app.original, self.source)
        self.assertIsNone(self.app.background_removal_original)
        with self.assertRaises(ValueError):
            result.image.getpixel((0, 0))
        self.assertEqual(self.pixels(self.source), self.original_pixels)
        self.assert_suppressed()

    def test_pending_clear_rejects_real_ready_background_result_and_stays_suppressed(self):
        result, events = self.run_background()
        self.assertIsNone(result.metadata['no_op_reason'])
        DrawBotApp.clear_cached_drawing(self.app)
        self.assertIsNotNone(self.app.pending_clear_drawing)
        self.adopt(events)
        self.pump_until(lambda: self.app.pending_clear_drawing is None)
        self.assertIs(self.app.original, self.source)
        self.assertIsNone(self.app.background_removal_original)
        with self.assertRaises(ValueError):
            result.image.getpixel((0, 0))
        self.assertEqual(self.pixels(self.source), self.original_pixels)
        self.assert_suppressed()

    def test_rejected_requests_and_undo_without_history_keep_recovery_suppressed(self):
        self.clear_recovery()
        for reason in ('busy', 'closing', 'no image'):
            with self.subTest(reason=reason):
                self.app.activity = 'preview' if reason == 'busy' else None
                self.app.closing = reason == 'closing'
                self.app.original = None if reason == 'no image' else self.source
                self.assertFalse(DrawBotApp.remove_image_background(self.app))
                self.assertIsNone(self.app.worker)
                self.assertIsNone(self.app.recovery_checkpoint_after)
                self.assert_suppressed()
        self.app.activity = None
        self.app.closing = False
        self.app.original = self.source
        self.assertFalse(DrawBotApp.undo_background_removal(self.app))
        self.assertIs(self.app.original, self.source)
        self.assertEqual(self.pixels(self.source), self.original_pixels)
        self.assert_suppressed()


if __name__ == '__main__':
    unittest.main()
