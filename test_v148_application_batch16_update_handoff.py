"""Deferred update installation cannot outlive its user's emergency Stop.

The actual app constructor registers Esc, and the real update controller,
begin_worker wrapper and event handler run. Tk surfaces,
network/download work and installer launch are replaced with local doubles.
"""
from contextlib import ExitStack
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import DrawBot
from DrawBot import DrawBotApp
import test_v148_application_batch14_browser_start as worker_fixtures


class Value:
    def __init__(self, *args, value='', **kwargs):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class HeadlessRoot(worker_fixtures.ScheduledRoot):
    def title(self, *args):
        pass

    def configure(self, **kwargs):
        pass

    def bind(self, *args, **kwargs):
        pass

    def protocol(self, *args):
        pass


class Keyboard:
    def __init__(self):
        self.callbacks = {}

    def add_hotkey(self, key, callback, **kwargs):
        self.callbacks[key] = callback
        return key

    def remove_hotkey(self, key):
        self.callbacks.pop(key, None)


class DeferredUpdateHandoffTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch('DrawBot.DATA_DIR', Path(temporary)))
        self.stack.enter_context(patch('GameProfiles.load_custom_profiles'))
        self.stack.enter_context(patch('DrawBot.ttk.Style'))
        self.stack.enter_context(patch('StudioUI.build_ui'))
        self.stack.enter_context(patch('ReleaseState.should_show_welcome', return_value=False))
        self.stack.enter_context(patch('DrawBot.previous_run_unclean', return_value=False))
        for name in ('BooleanVar', 'StringVar', 'DoubleVar'):
            self.stack.enter_context(patch.object(DrawBot.tk, name, Value))
        for name in ('read_settings', 'refresh_runtime_safety_ui', 'refresh_auto_tuner_ui',
                     'refresh_beginner_setup_wizard', 'refresh_palette',
                     'refresh_tool_calibration', 'refresh_app_tool_calibration', '_schedule_poll'):
            self.stack.enter_context(patch.object(DrawBotApp, name))
        self.stack.enter_context(patch.object(
            DrawBotApp, 'set_busy', lambda app, activity: setattr(app, 'activity', activity)))
        for target in ('DrawBot.log_event', 'DrawBot.log_error', 'ScreenTaskWindow.ScreenTaskWindow'):
            self.stack.enter_context(patch(target))
        self.stack.enter_context(patch('DrawBot.threading.Thread', worker_fixtures.DeferredThread))
        self.root = HeadlessRoot()
        self.keyboard = Keyboard()
        self.mouse = Mock()
        # This runs the actual constructor and captures precisely the Esc
        # callback it supplies to the keyboard backend; no copied stop lambda.
        self.app = DrawBotApp(self.root, self.mouse, self.keyboard)
        self.assertIn('esc', self.keyboard.callbacks)
        self.app.save_settings = Mock(return_value=True)
        self.app.close = Mock()
        self.asset = {'version': '99.0.0', 'sentinel': 'verified-downloader-result'}
        self.check = self.stack.enter_context(patch(
            'UpdateCenter.check_for_updates', side_effect=lambda **kwargs: {
                'update_available': True, 'installer': self.asset,
                'latest_version': '99.0.0', 'release_name': 'Update fixture',
                'release_url': 'https://github.com/Vxiey/Image-Draw-Bot/releases/tag/v99.0.0',
                'message': 'A verified update is available.',
            }))
        self.download = self.stack.enter_context(patch(
            'UpdateCenter.download_installer', return_value='unused-verified-installer.exe'))
        self.launch = self.stack.enter_context(patch('UpdateCenter.launch_installer'))

    def drain(self):
        delivered = []
        while True:
            try:
                event = self.app.events.get_nowait()
            except queue.Empty:
                return delivered
            delivered.append(event)
            self.app._handle_event(*event)

    def begin_completed_check(self, *, deliver=True):
        before = set(self.root.jobs)
        self.assertTrue(self.app.check_for_updates())
        self.assertEqual(self.app.activity, 'update-check')
        self.app.worker.run()
        if not deliver:
            return before
        self.drain()
        self.assertIsNone(self.app.activity)
        pending = set(self.root.jobs) - before
        self.assertEqual(len(pending), 1)
        return pending.pop()

    def other_operation(self):
        ran = []
        self.assertTrue(self.app.begin_worker('fixture-read-only-operation', lambda: ran.append(True)))
        self.assertFalse(self.app.stop.is_set())
        self.app.worker.run()
        self.drain()
        self.assertEqual(ran, [True])
        self.assertIsNone(self.app.activity)

    def run_handoff(self, token):
        self.root.run(token)
        if self.app.worker is not None:
            self.app.worker.run()
            self.drain()

    def assert_no_install_or_close(self):
        self.assertEqual(
            (self.launch.call_count, self.app.close.call_count), (0, 0),
            'A cancelled deferred update must not launch its installer or close the current app.')

    def test_successful_current_request_installs_once_through_actual_worker_and_events(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        observed = []
        def launch(path, asset, *, cancelled):
            observed.append((path, asset, request.phase, cancelled()))
        self.launch.side_effect = launch
        self.assertTrue(self.root.run(token))
        self.assertEqual(request.phase, 'installing')
        # A duplicate while the worker is accepted cannot create another
        # worker, settings save or deferred callback.
        self.assertFalse(self.root.history[token]())
        self.app.save_settings.assert_called_once_with()
        self.app.worker.run()
        self.drain()
        self.launch.assert_called_once()
        self.assertEqual(observed, [('unused-verified-installer.exe', self.asset, 'installing', False)])
        self.app.close.assert_called_once_with()
        self.assertIsNone(self.app.update_request)
        self.assertEqual(request.phase, 'consumed')
        # A retained duplicate callback cannot consume the same request again.
        self.root.history[token]()
        self.app._handle_event('update_installer_started', request)
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(self.app.close.call_count, 1)

    def test_registered_escape_without_later_operation_blocks_pending_install(self):
        token = self.begin_completed_check()
        self.keyboard.callbacks['esc']()
        self.assertTrue(self.app.stop.is_set())
        self.run_handoff(token)
        self.assert_no_install_or_close()

    def test_stop_button_then_new_operation_keeps_old_install_cancelled(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        self.app.cancel()
        self.assertTrue(request.is_cancelled())
        self.other_operation()
        self.run_handoff(token)
        self.assert_no_install_or_close()

    def test_registered_escape_then_new_operation_cannot_revive_deferred_install(self):
        token = self.begin_completed_check()
        self.keyboard.callbacks['esc']()
        self.assertTrue(self.app.stop.is_set())
        self.other_operation()
        self.run_handoff(token)
        self.assert_no_install_or_close()

    def test_hotkey_thread_latches_private_cancel_before_publishing_reusable_stop(self):
        token = self.begin_completed_check()
        signalled = threading.Event()
        release_hotkey = threading.Event()
        original_set = self.app.stop.set
        failures = []
        def publish_then_park():
            original_set()
            signalled.set()
            if not release_hotkey.wait(2):
                raise RuntimeError('test did not release the hotkey thread')
        def escape():
            try:
                self.keyboard.callbacks['esc']()
            except BaseException as error:
                failures.append(error)
        with patch.object(self.app.stop, 'set', side_effect=publish_then_park):
            hotkey = worker_fixtures.REAL_THREAD(target=escape, daemon=True)
            hotkey.start()
            try:
                self.assertTrue(signalled.wait(2))
                # Let the GUI thread perform a new accepted task while the
                # keyboard thread is descheduled at the Event.set boundary.
                # No poll or second emergency Stop runs between these actions.
                self.other_operation()
                self.run_handoff(token)
            finally:
                release_hotkey.set()
                hotkey.join(2)
        self.assertFalse(hotkey.is_alive())
        self.assertEqual(failures, [])
        self.assert_no_install_or_close()

    def test_registered_escape_before_queued_result_cannot_install_after_new_operation(self):
        before = self.begin_completed_check(deliver=False)
        self.keyboard.callbacks['esc']()
        self.assertTrue(self.app.stop.is_set())
        self.drain()
        self.assertIsNone(self.app.activity)
        tokens = set(self.root.jobs) - before
        self.other_operation()
        for token in tokens:
            self.run_handoff(token)
        self.assert_no_install_or_close()

    def test_new_explicit_update_replaces_the_older_pending_handoff(self):
        older = self.begin_completed_check()
        previous = self.app.update_request
        newer = self.begin_completed_check()
        self.assertTrue(previous.is_cancelled())
        self.run_handoff(older)
        self.assert_no_install_or_close()
        self.run_handoff(newer)
        self.assertEqual((self.launch.call_count, self.app.close.call_count), (1, 1))

    def test_fresh_explicit_update_can_follow_an_earlier_escape(self):
        older = self.begin_completed_check()
        previous = self.app.update_request
        self.keyboard.callbacks['esc']()
        newer = self.begin_completed_check()
        self.assertIsNot(self.app.update_request, previous)
        self.assertTrue(previous.is_cancelled())
        self.run_handoff(older)
        self.assert_no_install_or_close()
        self.run_handoff(newer)
        self.assertEqual((self.launch.call_count, self.app.close.call_count), (1, 1))

    def test_escape_during_settings_save_prevents_worker_handoff(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        def save():
            self.keyboard.callbacks['esc']()
            return True
        self.app.save_settings.side_effect = save
        self.run_handoff(token)
        self.assertTrue(request.is_cancelled())
        self.assertIsNone(self.app.worker)
        self.assertIsNone(self.app.activity)
        self.assert_no_install_or_close()
        self.other_operation()
        self.root.history[token]()
        self.app.save_settings.assert_called_once_with()
        self.assert_no_install_or_close()

    def test_escape_during_worker_window_construction_survives_start(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        def construct(*args, **kwargs):
            self.keyboard.callbacks['esc']()
            return Mock()
        with patch('ScreenTaskWindow.ScreenTaskWindow', side_effect=construct):
            self.run_handoff(token)
        self.assertTrue(request.is_cancelled())
        self.assertIsNone(self.app.activity)
        self.assert_no_install_or_close()

    def test_escape_during_thread_construction_survives_start(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        def construct(**kwargs):
            self.keyboard.callbacks['esc']()
            return worker_fixtures.DeferredThread(**kwargs)
        with patch('DrawBot.threading.Thread', side_effect=construct):
            self.run_handoff(token)
        self.assertTrue(request.is_cancelled())
        self.assertIsNone(self.app.activity)
        self.assert_no_install_or_close()

    def test_thread_start_failure_revokes_request_before_a_later_operation(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        class FailingThread(worker_fixtures.DeferredThread):
            def start(self):
                raise OSError('controlled updater thread start failure')
        with patch('DrawBot.threading.Thread', FailingThread):
            with self.assertRaisesRegex(OSError, 'controlled updater thread start failure'):
                self.root.run(token)
        self.assertTrue(request.is_cancelled())
        self.assertIsNone(self.app.activity)
        self.assertIsNone(self.app.worker)
        self.other_operation()
        self.root.history[token]()
        self.assert_no_install_or_close()

    def test_escape_before_check_worker_cannot_be_cleared_by_start(self):
        original_set = self.app.update_summary.set
        def stop_when_check_is_announced(value):
            original_set(value)
            self.keyboard.callbacks['esc']()
        self.app.update_summary.set = stop_when_check_is_announced
        self.assertFalse(self.app.check_for_updates())
        self.assertTrue(self.app.update_request.is_cancelled())
        self.assertIsNone(self.app.worker)
        self.check.assert_not_called()
        self.download.assert_not_called()
        self.assert_no_install_or_close()

    def test_transfer_callback_retains_private_stop_after_global_event_is_reused(self):
        def download(asset, *, cancelled, progress):
            self.assertFalse(cancelled())
            self.keyboard.callbacks['esc']()
            self.app.stop.clear()
            self.assertTrue(cancelled())
            raise InterruptedError('controlled cancelled transfer')
        self.download.side_effect = download
        before = set(self.root.jobs)
        self.assertTrue(self.app.check_for_updates())
        request = self.app.update_request
        self.app.worker.run()
        events = self.drain()
        self.assertTrue(request.is_cancelled())
        self.assertNotIn('update_check_complete', [kind for kind, value in events])
        self.assertEqual(set(self.root.jobs), before)
        self.assert_no_install_or_close()

    def test_superseded_progress_and_results_cannot_touch_current_update(self):
        older = self.begin_completed_check()
        previous = self.app.update_request
        self.assertTrue(self.app.check_for_updates())
        current = self.app.update_request
        before_text = (self.app.update_summary.get(), self.app.update_detail.get())
        before_jobs = set(self.root.jobs)
        self.app._handle_event('update_progress', (previous, 'stale previous download'))
        self.app._handle_event('update_check_complete', {
            'request': previous, 'error': 'stale previous error',
            'installer_path': 'unused.exe', 'installer': self.asset})
        self.assertEqual((self.app.update_summary.get(), self.app.update_detail.get()), before_text)
        self.assertEqual(set(self.root.jobs), before_jobs)
        self.assertIs(self.app.update_request, current)
        self.app.worker.run()
        self.drain()
        newer = (set(self.root.jobs) - before_jobs).pop()
        self.run_handoff(older)
        self.assert_no_install_or_close()
        self.run_handoff(newer)
        self.assertEqual((self.launch.call_count, self.app.close.call_count), (1, 1))

    def test_actual_shutdown_revokes_pending_handoff(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        with patch.object(DrawBotApp, '_finish_shutdown') as finish:
            DrawBotApp.close(self.app)
        self.assertTrue(self.app.closing)
        self.assertTrue(request.is_cancelled())
        finish.assert_called_once_with()
        self.run_handoff(token)
        self.assert_no_install_or_close()

    def test_stop_after_verified_process_start_still_completes_the_close_handoff(self):
        token = self.begin_completed_check()
        request = self.app.update_request
        def started_just_before_escape(path, asset, *, cancelled):
            self.assertFalse(cancelled())
            # Represent a launcher that has already successfully created the
            # process. Esc cannot undo that external boundary after it returns.
            self.keyboard.callbacks['esc']()
        self.launch.side_effect = started_just_before_escape
        self.run_handoff(token)
        self.assertTrue(request.is_cancelled())
        self.assertEqual(request.phase, 'consumed')
        self.assertEqual((self.launch.call_count, self.app.close.call_count), (1, 1))


if __name__ == '__main__':
    unittest.main()
