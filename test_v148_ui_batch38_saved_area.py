"""A saved-area probe keeps its cancellation and previous target ownership.

The application methods, Tcl variables, settings and browser region are real.
The isolated helper is a real Python child which emits the native protocol;
this checks parent cancellation/reaping, not a physical Windows window probe.
Raster data comes only from the existing batch37 repository-asset fixture.
"""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import DrawBot
import TargetCapture
from BrowserDrawingRegion import BrowserDrawingRegion
import test_v148_ui_batch37_boundary as boundary


class SavedAreaCancellationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = boundary.BoundaryAdoptionTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def application(self, profile='Gartic Phone'):
        app = self.fixture.application(profile)
        app.saved_area = [boundary.NEW_BOX[:2], boundary.NEW_BOX[2:]]
        return app

    def assert_previous(self, app, before):
        self.fixture.assert_previous(app, before)

    def probe_child(self, app, *, shutdown=False, select=False):
        directory = self.fixture.directory / ('select' if select else 'reuse')
        directory.mkdir(exist_ok=True)
        started, release = directory / 'started', directory / 'release'
        payload = dict(boundary.NEW_TARGET, ok=True)
        code = (
            'import json, pathlib, sys, time\n'
            'started, release = map(pathlib.Path, sys.argv[1:3])\n'
            'started.write_text("ready", encoding="utf-8")\n'
            'deadline = time.monotonic() + 5\n'
            'while not release.exists() and time.monotonic() < deadline:\n'
            '    time.sleep(.01)\n'
            'print(sys.argv[3], flush=True)\n'
        )
        command = [sys.executable, '-c', code, str(started), str(release), json.dumps(payload)]
        processes, errors = [], []
        native_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = native_popen(*args, **kwargs)
            processes.append(child)
            return child

        def interrupt():
            try:
                deadline = time.monotonic() + 3
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                if not started.exists():
                    raise AssertionError('The real helper did not reach its ready barrier.')
                if shutdown:
                    app.closing = True
                else:
                    DrawBot.DrawBotApp._request_stop(app)
                # A cancellable parent reaps the waiting child. Let the old
                # noncancellable parent finish too, retaining a bounded red run.
                deadline = time.monotonic() + .7
                while processes and processes[0].poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
            except BaseException as error:
                errors.append(error)
            finally:
                release.write_text('release', encoding='utf-8')

        interrupt_thread = threading.Thread(target=interrupt, name='saved-area-test-stop')
        failures = []
        crop = None

        def picked(_owner, selected, failed, *, cancelled):
            nonlocal crop
            crop = self.fixture.own(self.fixture.source.copy())
            try:
                selected(boundary.NEW_BOX, crop)
            except Exception as error:
                failures.append(error)
                failed(str(error))

        with patch.object(TargetCapture, 'BASE', directory), \
                patch.object(TargetCapture, 'helper_command', return_value=command), \
                patch.object(TargetCapture.subprocess, 'Popen', side_effect=spawn), \
                patch('RegionPicker.select_region', side_effect=picked):
            interrupt_thread.start()
            try:
                if select:
                    result = DrawBot.DrawBotApp.set_boundary(app)
                else:
                    result = DrawBot.DrawBotApp.reuse_area(app)
            finally:
                release.write_text('release', encoding='utf-8')
                interrupt_thread.join(4)
                for child in processes:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=3)
        self.assertFalse(interrupt_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(processes), 1)
        child = processes[0]
        self.assertIsNotNone(child.returncode)
        self.assertTrue(child.stdout.closed)
        self.assertTrue(child.stderr.closed)
        self.assertNotEqual(child.returncode, 0, 'Stop must terminate the still-waiting helper.')
        if crop is not None:
            with self.assertRaises(ValueError):
                crop.getpixel((0, 0))
        return result, failures

    def test_stop_reaps_saved_area_helper_and_retains_previous_setup(self):
        app = self.application()
        before = self.fixture.snapshot(app)
        result, failures = self.probe_child(app)
        self.assertFalse(result)
        self.assertEqual(failures, [])
        self.assertTrue(app.stop.is_set())
        self.assert_previous(app, before)
        self.assertIn('cancelled', app.status.get().lower())

    def test_shutdown_reaps_saved_area_helper_without_late_ui_feedback(self):
        app = self.application('Other drawing app')
        before = self.fixture.snapshot(app)
        status = app.status.get()
        result, _failures = self.probe_child(app, shutdown=True)
        self.assertFalse(result)
        self.assert_previous(app, before)
        self.assertEqual(app.status.get(), status)

    def test_screen_picker_forwards_stop_into_the_same_actual_helper(self):
        app = self.application()
        before = self.fixture.snapshot(app)
        _result, failures = self.probe_child(app, select=True)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], InterruptedError)
        self.assert_previous(app, before)

    def test_late_stop_during_browser_region_capture_cannot_publish_new_target(self):
        app = self.application()
        before = self.fixture.snapshot(app)
        capture = BrowserDrawingRegion.capture

        def interrupted(*args, **kwargs):
            region = capture(*args, **kwargs)
            DrawBot.DrawBotApp._request_stop(app)
            return region

        with patch.object(TargetCapture, 'capture_target_metadata_isolated',
                          return_value=dict(boundary.NEW_TARGET)), \
                patch.object(BrowserDrawingRegion, 'capture', side_effect=interrupted):
            self.assertFalse(DrawBot.DrawBotApp.reuse_area(app))
        self.assert_previous(app, before)

    def test_failed_capture_rolls_back_browser_region_with_other_geometry(self):
        app = self.application()
        before = self.fixture.snapshot(app)
        capture = app.capture_target

        def failed_capture():
            capture()
            raise OSError('Target closed after capture.')

        app.capture_target = failed_capture
        with patch.object(TargetCapture, 'capture_target_metadata_isolated',
                          return_value=dict(boundary.NEW_TARGET)):
            self.assertFalse(DrawBot.DrawBotApp.reuse_area(app))
        self.assert_previous(app, before)
        self.assertIn('Target closed', app.status.get())

    def test_explicit_reuse_after_old_stop_accepts_current_target_and_retires_old_plan(self):
        app = self.application()
        app.stop.set()
        before = self.fixture.snapshot(app)
        with patch.object(TargetCapture, 'capture_target_metadata_isolated',
                          return_value=dict(boundary.NEW_TARGET)) as probe:
            self.assertTrue(DrawBot.DrawBotApp.reuse_area(app))
        self.assertFalse(app.stop.is_set())
        self.assertEqual(probe.call_args.args[0], (300, 100, 720, 393))
        self.assertEqual(app.target_window, (boundary.NEW_TARGET['handle'], boundary.NEW_TARGET['rect']))
        self.assertEqual(app.browser_drawing_region.handle, boundary.NEW_TARGET['handle'])
        self.assertEqual(app.corners, app.saved_area)
        self.assertIsNone(app.plan)
        self.assertFalse(app.small_test_passed)
        self.assertFalse(app.target_lock_passed)
        self.assertFalse(app.safety_preflight_passed)
        self.assertFalse(app.dry_run_passed)
        self.assertEqual(app.color_session_cache, {})
        self.assertEqual(app.settings_path.read_bytes(), before['settings'])


if __name__ == '__main__':
    unittest.main()
