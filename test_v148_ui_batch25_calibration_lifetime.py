"""Tool-dialog startup/close own busy state, native cleanup and visibility."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import MethodType, SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

import AppToolCalibration
import DrawBot
import PaintToolCalibration
from UiWindowLifetime import scoped_window_class
from test_v148_ui_batch25_button_lifetime import isolated_native
from test_v148_ui_batch25_worker_handoff import WorkerHandoffFixture


class NativeDialogBoundary(tk.Misc):
    """Real Tcl callbacks with only the native top-level window substituted."""
    def __init__(self, interpreter):
        self.master = interpreter
        self.tk = interpreter.tk
        self._tclCommands = []
        self.children = {}
        self.alive = True
        self.attempts = 0
        self.failure = None
        self.reenter = None
        self.visibility = 'normal'

    def winfo_exists(self):return self.alive
    def winfo_children(self):return []
    def state(self, value=None):
        if value is not None:self.visibility = value
        return self.visibility
    def iconify(self):self.visibility = 'iconic'
    def deiconify(self):self.visibility = 'normal'
    def withdraw(self):self.visibility = 'withdrawn'
    def lift(self):pass
    def update_idletasks(self):pass

    def destroy(self):
        self.attempts += 1
        if self.reenter is not None:self.reenter()
        failure, self.failure = self.failure, None
        if failure is not None:raise failure
        tk.Misc.destroy(self)
        self.alive = False


class CalibrationLifetimeTests(WorkerHandoffFixture):
    ROUTES = (
        ('Microsoft Paint', 'calibrate_paint_tools', 'paint_tool_window',
         PaintToolCalibration, 'PaintToolCalibrationApp', 'refresh_tool_calibration'),
        ('Gartic Phone', 'calibrate_app_tools', 'app_tool_window',
         AppToolCalibration, 'AppToolCalibrationApp', 'refresh_app_tool_calibration'),
    )

    def route(self, row):
        profile, method, attribute, module, name, refresh = row
        app = self.app(); app.game.set(profile); app._active_profile_name = profile
        setattr(app, method, MethodType(getattr(DrawBot.DrawBotApp, method), app))
        window = scoped_window_class(NativeDialogBoundary)(self.tcl)
        self.addCleanup(window.destroy)
        helper_type = getattr(module, name)
        helpers = []
        def constructor(root, *_args, on_close):
            # The GUI's content construction is a native boundary here. Its
            # actual close method, controller callback and scoped window run.
            helper = helper_type.__new__(helper_type)
            helper.root = root; helper.on_close = on_close
            helper.closed = False; helper.job = None
            helpers.append(helper)
            return helper
        return app, window, helpers, constructor

    def test_top_level_allocation_failure_restores_idle_without_hiding_the_app(self):
        for row in self.ROUTES:
            with self.subTest(profile=row[0]):
                app, window, helpers, constructor = self.route(row)
                error = MemoryError('native top-level allocation')
                with patch('UiCompatibility.scoped_toplevel', side_effect=error):
                    with self.assertRaises(MemoryError) as caught:getattr(app, row[1])()
                self.assertIs(caught.exception, error)
                self.assertIsNone(app.activity)
                self.assertEqual(app.root.visibility, 'normal')
                self.assertIsNone(getattr(app, row[2], None))

    def test_visibility_constructor_failure_releases_already_allocated_dialog(self):
        for row in self.ROUTES:
            with self.subTest(profile=row[0]):
                app, window, helpers, constructor = self.route(row)
                token = window.after(60_000, lambda: None)
                with patch('UiCompatibility.scoped_toplevel', return_value=window), \
                        patch('ScreenTaskWindow.ScreenTaskWindow', side_effect=RuntimeError('visibility allocation')):
                    with self.assertRaisesRegex(RuntimeError, 'visibility allocation'):getattr(app, row[1])()
                self.assertIsNone(app.activity)
                self.assertFalse(window.winfo_exists())
                self.assertNotIn(token, self.tcl.tk.splitlist(self.tcl.tk.call('after', 'info')))
                self.assertEqual(app.root.visibility, 'normal')

    def test_content_failure_keeps_original_error_and_restores_app_even_if_destroy_fails(self):
        for row in self.ROUTES:
            with self.subTest(profile=row[0]):
                app, window, helpers, constructor = self.route(row)
                error = MemoryError('native control allocation')
                window.failure = tk.TclError('native dialog cleanup needs retry')
                with patch('UiCompatibility.scoped_toplevel', return_value=window), \
                        patch.object(row[3], row[4], side_effect=error):
                    with self.assertRaises(MemoryError) as caught:getattr(app, row[1])()
                self.assertIs(caught.exception, error)
                self.assertIsNone(app.activity)
                self.assertEqual(app.root.visibility, 'normal')
                self.assertIs(getattr(app, row[2]), window)
                self.assertTrue(window.winfo_exists())
                window.destroy()
                self.assertFalse(window.winfo_exists())

    def test_real_tool_close_releases_busy_and_visibility_even_if_refresh_raises(self):
        for row in self.ROUTES:
            with self.subTest(profile=row[0]):
                app, window, helpers, constructor = self.route(row)
                with patch('UiCompatibility.scoped_toplevel', return_value=window), \
                        patch.object(row[3], row[4], side_effect=constructor):
                    getattr(app, row[1])()
                self.assertEqual(app.activity, 'tool-calibration')
                self.assertEqual(app.root.visibility, 'iconic')
                getattr(app, row[5]).side_effect = ValueError('invalid refreshed calibration')
                with self.assertRaisesRegex(ValueError, 'invalid refreshed calibration'):helpers[0].close()
                self.assertFalse(window.winfo_exists())
                self.assertIsNone(app.activity)
                self.assertEqual(app.root.visibility, 'normal')

    def test_real_tool_close_can_retry_native_failure_and_converging_callback(self):
        for row in self.ROUTES:
            with self.subTest(profile=row[0]):
                app, window, helpers, constructor = self.route(row)
                with patch('UiCompatibility.scoped_toplevel', return_value=window), \
                        patch.object(row[3], row[4], side_effect=constructor):
                    getattr(app, row[1])()
                helper = helpers[0]
                helper.job = window.after(60_000, lambda: None)
                window.failure = tk.TclError('native dialog teardown needs retry')
                observed = []
                def pointer():
                    observed.append('unexpected capture')
                    raise RuntimeError('capture while the dialog is closing')
                helper.mouse = SimpleNamespace(get_position=pointer)
                def reenter():
                    helper.close()
                    helper._capture_tick('Fill', 0)
                window.reenter = reenter
                with self.assertRaisesRegex(tk.TclError, 'teardown needs retry'):helper.close()
                self.assertFalse(helper.closed)
                self.assertTrue(window.winfo_exists())
                self.assertEqual(app.activity, 'tool-calibration')
                self.assertIsNone(helper.job)
                helper.close()
                self.assertTrue(helper.closed)
                self.assertFalse(window.winfo_exists())
                self.assertEqual(window.attempts, 2)
                self.assertIsNone(app.activity)
                self.assertEqual(app.root.visibility, 'normal')
                self.assertEqual(observed, [])
                getattr(app, row[5]).assert_called_once()
                helper.close()
                self.assertEqual(window.attempts, 2)

    def test_failed_close_restores_the_cancelled_capture_dialog_for_visible_retry(self):
        for row in self.ROUTES:
            with self.subTest(profile=row[0]):
                app, window, helpers, constructor = self.route(row)
                with patch('UiCompatibility.scoped_toplevel', return_value=window), \
                        patch.object(row[3], row[4], side_effect=constructor):
                    getattr(app, row[1])()
                helper = helpers[0]
                helper.status = tk.StringVar(self.tcl)
                helper.profile_name = row[0]
                helper.capture('Fill', 3)
                token = helper.job
                self.assertIsNotNone(token)
                self.assertEqual(window.state(), 'iconic')
                self.assertIn(token, self.tcl.tk.splitlist(self.tcl.tk.call('after', 'info')))
                window.failure = tk.TclError('native countdown dialog needs retry')
                with self.assertRaisesRegex(tk.TclError, 'countdown dialog needs retry'):helper.close()
                self.assertFalse(helper.closed)
                self.assertEqual(window.state(), 'normal')
                self.assertIsNone(helper.capture_visibility)
                self.assertIsNone(helper.job)
                self.assertNotIn(token, self.tcl.tk.splitlist(self.tcl.tk.call('after', 'info')))
                self.assertEqual(app.activity, 'tool-calibration')
                getattr(app, row[5]).assert_not_called()
                helper.close()
                self.assertFalse(window.winfo_exists())
                self.assertIsNone(app.activity)
                self.assertEqual(app.root.visibility, 'normal')
                getattr(app, row[5]).assert_called_once()


@unittest.skipUnless(sys.platform == 'win32',
                     'Actual tool calibration factories require Windows native APIs')
class NativeToolCalibrationLifetimeTests(unittest.TestCase):
    @isolated_native
    def test_real_tool_factories_retry_destroy_and_restore_after_refresh_failure(self):
        root = DrawBot.create_root()
        self.addCleanup(root.destroy)
        root.geometry('520x320+30+30'); root.update()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        root.tk.createcommand('bgerror', lambda message: errors.append(message))
        self.addCleanup(lambda: root.tk.deletecommand('bgerror'))
        app = SimpleNamespace(root=root, closing=False, activity=None,
            status=tk.StringVar(root), game=tk.StringVar(root))
        app.set_busy = lambda value: setattr(app, 'activity', value)
        with tempfile.TemporaryDirectory() as directory:
            for route in CalibrationLifetimeTests.ROUTES:
                with self.subTest(profile=route[0]), ExitStack() as stack:
                    app.game.set(route[0]); helpers = []
                    helper_type = getattr(route[3], route[4])
                    def constructor(*args, **kwargs):
                        helper = helper_type(*args, **kwargs)
                        helpers.append(helper)
                        return helper
                    if route[0] == 'Microsoft Paint':
                        read = PaintToolCalibration.load_tool_calibration
                        stack.enter_context(patch.object(PaintToolCalibration, 'load_tool_calibration',
                            side_effect=lambda _path: read(Path(directory) / 'paint-tools.json')))
                    else:
                        read = AppToolCalibration.load_calibration
                        stack.enter_context(patch.object(AppToolCalibration, 'load_calibration',
                            side_effect=lambda key: read(key, Path(directory) / 'app-tools.json')))
                    stack.enter_context(patch.object(route[3], route[4], side_effect=constructor))
                    setattr(app, route[5], lambda: None)
                    getattr(DrawBot.DrawBotApp, route[1])(app)
                    self.assertEqual(len(helpers), 1)
                    helper = helpers[0]; window = getattr(app, route[2])
                    self.assertIs(helper.root, window)
                    self.assertEqual(app.activity, 'tool-calibration')
                    helper.capture('Fill', 3)
                    self.assertIsNotNone(helper.job)
                    original_destroy = tk.Toplevel.destroy
                    fail_once = [True]
                    def native_destroy(widget):
                        if widget is window and fail_once[0]:
                            fail_once[0] = False
                            raise tk.TclError('native dialog teardown needs retry')
                        return original_destroy(widget)
                    with patch.object(tk.Toplevel, 'destroy', new=native_destroy):
                        with self.assertRaisesRegex(tk.TclError, 'teardown needs retry'):helper.close()
                        self.assertFalse(helper.closed)
                        self.assertTrue(window.winfo_exists())
                        self.assertEqual(app.activity, 'tool-calibration')
                        self.assertIsNone(helper.job)
                        self.assertIsNone(helper.capture_visibility)
                        root.update()
                        self.assertTrue(window.winfo_viewable())
                        def refresh_failure():raise ValueError('native close refresh boundary')
                        setattr(app, route[5], refresh_failure)
                        with self.assertRaisesRegex(ValueError, 'close refresh boundary'):helper.close()
                    root.update()
                    self.assertTrue(helper.closed)
                    self.assertFalse(window.winfo_exists())
                    self.assertIsNone(app.activity)
                    self.assertTrue(root.winfo_viewable())
        root.after(180, root.quit); root.mainloop()
        self.assertEqual(errors, [])
