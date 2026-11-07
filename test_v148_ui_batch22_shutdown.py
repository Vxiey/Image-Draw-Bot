"""Application shutdown commits only after its owned root actually closes."""
from contextlib import ExitStack
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
from types import MethodType, SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import CrashDiagnostics
from DrawBot import DrawBotApp
import SessionRecovery
from test_v148_application_batch04_settings import Value
from UiWindowLifetime import scoped_window_class


class NativeDestroyBoundary:
    """Replace native window allocation; keep the real scoped-root controller."""
    def __init__(self):
        self.alive = True
        self.attempts = 0
        self.failure = None
        self.reenter = None
        self.jobs = {}

    def winfo_exists(self):
        return self.alive

    def winfo_children(self):
        return []

    def after(self, _delay, callback):
        token = object()
        self.jobs[token] = callback
        return token

    def after_cancel(self, token):
        self.jobs.pop(token, None)

    def destroy(self):
        self.attempts += 1
        failure, self.failure = self.failure, None
        if failure is not None:
            raise failure
        if self.reenter is not None:
            self.reenter()
        self.alive = False


class ShutdownFixture(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state_file = self.directory / 'session-recovery.json'
        self.marker_file = self.directory / 'running.marker'
        for name, path in (
            ('RECOVERY_DIR', self.directory), ('STATE_FILE', self.state_file),
            ('IMAGE_FILE', self.directory / 'last-image.png'),
            ('RENDER_FILE', self.directory / 'render-resume.json'),
        ):
            self.stack.enter_context(patch.object(SessionRecovery, name, path))
        self.stack.enter_context(patch.object(CrashDiagnostics, 'RUN_MARKER', self.marker_file))
        self.stack.enter_context(patch.object(CrashDiagnostics, 'RUN_MARKER_OWNED', True))
        self.stack.enter_context(patch('CrashDiagnostics.log_event'))
        self.log = self.stack.enter_context(patch('DrawBot.log_event'))
        self.error_log = self.stack.enter_context(patch('DrawBot.log_error'))
        self.clean = self.stack.enter_context(patch('DrawBot.clean_exit', wraps=CrashDiagnostics.clean_exit))
        for name in ('_close_smart_drop_overlay', '_disarm_manual_drop_in', '_disarm_full_draw'):
            self.stack.enter_context(patch.object(DrawBotApp, name))
        # Use real recovery/marker files; no image is needed for this lifecycle.
        SessionRecovery.save_snapshot(profile='Other drawing app', options={})
        self.marker_file.write_text(f'pid={os.getpid()} started=fixture\n', encoding='utf-8')
        self.before = self.state_file.read_bytes()
        self.app = self.app_for(scoped_window_class(NativeDestroyBoundary)())

    def app_for(self, root):
        app = SimpleNamespace(
            root=root, closing=False, shutdown_complete=False, activity=None, worker=None,
            stop=threading.Event(), paused=threading.Event(), events=queue.Queue(),
            _recovery_image_job=None, _recovery_save_pending=False,
            recovery_checkpoint_after=None, recovery_shutdown_after=None,
            poll_after=None, pending_clear_drawing=None, needs_plan=False,
            smart_drop_pending_payload=None, smart_drop_generation=0,
            preview_generation=0, plan=None, original=None, mouse=Mock(),
            _remove_hotkeys=Mock(), stop_mobile_preview=Mock(), save_settings=Mock(),
            status=Value('Ready'),
        )
        app.set_busy = lambda activity: setattr(app, 'activity', activity)
        for name in ('cancel', 'close', '_finish_shutdown', 'poll', '_handle_event'):
            setattr(app, name, MethodType(getattr(DrawBotApp, name), app))
        return app

    def assert_preserved(self, app):
        self.assertTrue(app.closing)
        self.assertFalse(app.shutdown_complete)
        self.assertFalse(getattr(app, '_shutdown_finishing', False))
        self.assertEqual(self.state_file.read_bytes(), self.before)
        self.assertTrue(self.marker_file.exists())
        self.clean.assert_not_called()

    def assert_complete(self, app):
        self.assertTrue(app.closing)
        self.assertTrue(app.shutdown_complete)
        self.assertFalse(getattr(app, '_shutdown_finishing', False))
        self.assertFalse(self.state_file.exists())
        self.assertFalse(self.marker_file.exists())
        self.clean.assert_called_once_with()
        app._remove_hotkeys.assert_called()
        app.stop_mobile_preview.assert_called()


class ApplicationShutdownTests(ShutdownFixture):
    def test_live_root_destroy_failure_preserves_recovery_and_close_can_retry(self):
        app = self.app
        app.root.failure = tk.TclError('bad window path name ".still-live"')
        app.poll_after = app.root.after(50, app.poll)
        app.close()
        self.assert_preserved(app)
        self.assertTrue(app.root.winfo_exists())
        self.assertEqual(app.root.attempts, 1)
        self.assertTrue(app.stop.is_set())
        self.assertIn('Close again', app.status.get())
        self.error_log.assert_called_once()
        self.assertIn('still-live', self.error_log.call_args.args[0])
        self.assertFalse(app.root.jobs)
        app.close()
        self.assert_complete(app)
        self.assertFalse(app.root.winfo_exists())
        self.assertEqual(app.root.attempts, 2)
        app.close()
        app._finish_shutdown()
        self.assertEqual(app.root.attempts, 2)
        self.clean.assert_called_once_with()

    def test_runtime_failure_stays_visible_retryable_and_never_declares_clean_exit(self):
        app = self.app
        app.root.failure = RuntimeError('native teardown is still in progress')
        app.close()
        self.assert_preserved(app)
        self.assertTrue(app.root.winfo_exists())
        self.error_log.assert_called_once()
        app.close()
        self.assert_complete(app)

    def test_reentrant_native_close_cannot_commit_or_cleanup_twice(self):
        app = self.app
        seen = []
        def reenter():
            seen.append((app.shutdown_complete, self.marker_file.exists()))
            app.close()
            app._finish_shutdown()
        app.root.reenter = reenter
        app.close()
        self.assert_complete(app)
        self.assertEqual(seen, [(False, True)])
        self.assertEqual(app.root.attempts, 1)
        app._remove_hotkeys.assert_called_once_with()
        app.stop_mobile_preview.assert_called_once_with(quiet=True)

    def test_unrelated_destroy_exception_propagates_with_truthful_state_then_can_retry(self):
        app = self.app
        error = ValueError('a child could not dispose its native resource')
        app.root.failure = error
        with self.assertRaises(ValueError) as raised:
            app.close()
        self.assertIs(raised.exception, error)
        self.assert_preserved(app)
        app.close()
        self.assert_complete(app)

    def test_already_destroyed_native_interpreter_completes_idempotently(self):
        app = self.app
        # This known converging Tk state is a successful close, not a live-root
        # failure. The branded Windows guard normally handles it itself.
        app.root.failure = tk.TclError('can\'t invoke "destroy" command: application has been destroyed')
        app.root.alive = False
        app.close()
        self.assert_complete(app)
        app.close()
        self.assertEqual(app.root.attempts, 1)
        self.error_log.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native application shutdown requires a Tk display')
class NativeApplicationShutdownTests(ShutdownFixture):
    def test_public_root_failure_and_reentrant_close_keep_real_recovery_until_destroy(self):
        flag = 'IMAGEDRAWBOT_APPLICATION_SHUTDOWN_CHILD'
        if os.environ.get(flag) != '1':
            code = '''import unittest
from test_v148_ui_batch22_shutdown import NativeApplicationShutdownTests
NativeApplicationShutdownTests.__unittest_skip__ = False
suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeApplicationShutdownTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
'''
            result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code],
                cwd=Path(__file__).resolve().parent, env={**os.environ, flag: '1'},
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('invalid command name', result.stderr)
            return
        from DrawBot import create_root
        root = create_root()
        def destroy():
            try:
                root.destroy()
            except (tk.TclError, RuntimeError):
                pass
        self.addCleanup(destroy)
        app = self.app_for(root)
        root.geometry('320x160')
        root.protocol('WM_DELETE_WINDOW', app.close)
        root.update_idletasks()
        native_destroy = tk.Tk.destroy
        failures = []
        def fail_once(window):
            if window is root and not failures:
                failures.append(True)
                raise tk.TclError('bad window path name ".actual-live-root"')
            return native_destroy(window)
        with patch.object(tk.Tk, 'destroy', fail_once):
            app.close()
        self.assert_preserved(app)
        self.assertTrue(root.winfo_exists())
        seen = []
        def close_again(event):
            if event.widget is root:
                seen.append((app.shutdown_complete, self.marker_file.exists()))
                app.close()
        root.bind('<Destroy>', close_again, add='+')
        app.close()
        self.assert_complete(app)
        self.assertEqual(seen, [(False, True)])


if __name__ == '__main__':
    unittest.main()
