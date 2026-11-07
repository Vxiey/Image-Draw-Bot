"""The actual Upscale dialog is keyboard reachable through real image adoption."""
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

import customtkinter as ctk
from PIL import Image

import DrawBot
from UiCompatibility import scoped_window_class
from test_v148_ui_batch24_picture_palette import controller_values


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Actual Upscale keyboard flow requires a native Tk display')
class NativeUpscaleKeyboardTests(unittest.TestCase):
    def isolated(self):
        flag = 'IMAGEDRAWBOT_UPSCALE_KEYBOARD_CHILD'
        if os.environ.get(flag) == self._testMethodName:
            return False
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', '-v',
            self.id()], cwd=Path(__file__).resolve().parent,
            env={**os.environ, flag: self._testMethodName}, capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for diagnostic in ('invalid command name', 'Tcl_AsyncDelete', 'Exception ignored in'):
            self.assertNotIn(diagnostic, result.stderr)
        return True

    def surface(self, size=(3, 2)):
        self.stack = self.enterContext(ExitStack())
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.log_error'))
        self.stack.enter_context(patch('SessionRecovery.clear_render_progress'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_start_buttons_text'))
        self.root = scoped_window_class(ctk.CTk)()
        self.root.geometry('480x360+60+60')
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.tk.eval('set ::upscale_fixture_errors {}; proc bgerror {message} {lappend ::upscale_fixture_errors $message}')
        self.images = []
        app = SimpleNamespace(**controller_values())
        self.app = app
        app.root = self.root
        app.closing = False
        app.activity = None
        app.worker = None
        app.pending_clear_drawing = None
        app.profile_change_after = None
        app.profile_change_in_progress = False
        app.plan = None
        app.preview_mode.set('Manual')
        app.original = Image.new('RGBA', size, (231, 11, 72, 255))
        app.original.putpixel((0, 0), (1, 97, 223, 255))
        app.original.putpixel((size[0]-1, size[1]-1), (0, 255, 0, 0))
        app.original.info['draw_studio_format'] = 'PNG'
        app.original.info['fixture'] = 'keyboard image'
        self.images.append(app.original)
        app.upscale_original = None
        app.background_removal_original = None
        app.background_removal_meta = None
        app.color_session_cache = {}
        app.corners = []
        app.canvas_anchor_detection = None
        app.stop = threading.Event()
        app.paused = threading.Event()
        app.events = queue.Queue()
        app.progress = {'value': 0}
        app.mouse = Mock()
        app.set_busy = lambda activity: setattr(app, 'activity', activity)
        for name in ('show_previews', 'schedule_previews', '_schedule_recovery_checkpoint'):
            setattr(app, name, Mock())
        for name in ('begin_worker', '_handle_event', '_mark_plan_stale'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        self.addCleanup(self.release_surface)
        self.root.update()
        return app

    def release_surface(self):
        app = self.app
        worker = app.worker
        if isinstance(worker, threading.Thread) and worker.is_alive():
            app.stop.set()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive(), 'The actual worker must finish before native owners are released')
        while not app.events.empty():
            kind, value = app.events.get_nowait()
            DrawBot.DrawBotApp._discard_worker_result(app, kind, value)
        self.root.destroy()
        self.assertFalse(self.errors, self.errors)
        self.assertEqual(tuple(self.root.tk.splitlist(self.root.tk.eval('set ::upscale_fixture_errors'))), ())
        self.root.tk.eval('rename bgerror {}; unset ::upscale_fixture_errors')
        for image in self.images:
            image.close()
        vars(app).clear()
        self.app = None
        self.root = None

    def dialog(self):
        DrawBot.DrawBotApp.upscale_dialog(self.app)
        self.root.update()
        dialogs = [child for child in self.root.winfo_children() if isinstance(child, ctk.CTkToplevel)]
        self.assertEqual(len(dialogs), 1)
        dialog = dialogs[0]
        choices = [child for child in dialog.winfo_children() if isinstance(child, ctk.CTkOptionMenu)]
        actions = [child for child in dialog.winfo_children() if isinstance(child, ctk.CTkButton)]
        self.assertEqual(len(choices), 2)
        self.assertEqual(len(actions), 1)
        self.assertIs(self.root.grab_current(), dialog)
        return dialog, choices[0], choices[1], actions[0]

    def key(self, widget, symbol, *, flush=True):
        widget.event_generate('<KeyPress-' + symbol + '>', when='now')
        # Escape can synchronously destroy the focused dialog. A physical key
        # release then goes to the remaining root, never to a dead widget path.
        recipient = widget if widget.winfo_exists() else self.root
        recipient.event_generate('<KeyRelease-' + symbol + '>', when='now')
        if flush:
            self.root.update()

    def visible_hint(self, dialog):
        return next(str(child._label.cget('text')) for child in dialog.winfo_children()
                    if isinstance(child, ctk.CTkLabel) and child.cget('textvariable'))

    def result_events(self):
        worker = self.app.worker
        self.assertIsInstance(worker, threading.Thread)
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        events = []
        while not self.app.events.empty():
            events.append(self.app.events.get_nowait())
        self.assertEqual([kind for kind, _ in events], ['upscaled', 'done'])
        self.images.append(events[0][1][0])
        return events

    def test_actual_tab_selection_return_worker_adoption_and_undo_preserve_pixels(self):
        if self.isolated(): return
        app = self.surface()
        source = app.original
        before = source.tobytes()
        globals_before = {name: self.root.bind_all(name) for name in ('<Tab>', '<Return>', '<Escape>')}
        dialog, factor, method, action = self.dialog()
        dialog.focus_force()
        self.root.update()
        self.key(dialog, 'Tab')
        self.assertIs(self.root.focus_get(), factor)
        # The selector's popup keeps its own Escape semantics; dismissing that
        # real menu must not close the containing modal editing dialog.
        from test_v148_ui_batch16_pointer_focus import NativePopupDriver
        popup = NativePopupDriver(self, factor)
        popup.run(lambda: self.key(factor, 'F4', flush=False),
                  (lambda: popup.assert_owner(popup.assert_open()), lambda: popup.key('Escape')))
        self.root.update()
        self.assertTrue(dialog.winfo_exists())
        self.assertIs(self.root.grab_current(), dialog)
        self.assertIs(self.root.focus_get(), factor)
        self.key(factor, 'Home')
        self.assertEqual(factor.get(), '2×')
        self.assertIn('Result: 6 × 4', self.visible_hint(dialog))
        self.key(factor, 'End')
        self.assertEqual(factor.get(), '4×')
        self.assertIn('Result: 12 × 8', self.visible_hint(dialog))
        self.key(factor, 'Tab')
        self.assertIs(self.root.focus_get(), method)
        self.key(method, 'End')
        self.assertEqual(method.get(), 'Pixel art')
        self.key(method, 'Tab')
        self.assertIs(self.root.focus_get(), action)
        # Key repeat must still produce just one actual worker and result.
        for _ in range(3):
            action.event_generate('<KeyPress-Return>', when='now')
        action.event_generate('<KeyRelease-Return>', when='now')
        self.root.update()
        self.assertFalse(dialog.winfo_exists())
        self.assertIsNone(self.root.grab_current())
        events = self.result_events()
        self.assertIs(app.original, source)
        for kind, value in events:
            app._handle_event(kind, value)
        with source.resize((12, 8), Image.Resampling.NEAREST) as expected:
            self.assertEqual(app.original.size, expected.size)
            self.assertEqual(app.original.tobytes(), expected.tobytes())
        self.assertEqual(app.original.info['draw_studio_format'], 'PNG')
        self.assertEqual(app.original.info['fixture'], 'keyboard image')
        self.assertIs(app.upscale_original, source)
        self.assertEqual(source.tobytes(), before)
        self.assertIsNone(app.activity)
        self.assertIsNone(app.worker)
        self.assertTrue(app.needs_plan)
        self.assertEqual(app.preview_mode.get(), 'Manual')
        DrawBot.DrawBotApp.undo_upscale(app)
        self.assertIs(app.original, source)
        self.assertIsNone(app.upscale_original)
        self.assertEqual(source.tobytes(), before)
        self.assertEqual(app.mouse.mock_calls, [])
        self.assertEqual({name: self.root.bind_all(name) for name in globals_before}, globals_before)

    def test_escape_from_each_control_and_late_key_release_cancel_without_editing(self):
        if self.isolated(): return
        app = self.surface()
        source = app.original
        before = source.tobytes()
        app.stop.set()
        for control_index in (0, 1, 2):
            with self.subTest(control=control_index):
                dialog, factor, method, action = self.dialog()
                control = (factor, method, action)[control_index]
                control.focus_force()
                self.root.update()
                if control is action:
                    action.event_generate('<KeyPress-Return>', when='now')
                    action.event_generate('<KeyRelease-Return>', when='now')
                self.key(control, 'Escape')
                self.assertFalse(dialog.winfo_exists())
                self.assertIsNone(self.root.grab_current())
                self.assertIsNone(app.worker)
                self.assertTrue(app.events.empty())
                self.assertTrue(app.stop.is_set())
                self.assertIs(app.original, source)
                self.assertEqual(source.tobytes(), before)
        self.assertEqual(app.mouse.mock_calls, [])

    def test_keyboard_apply_retains_stop_and_source_identity_at_real_result_boundary(self):
        if self.isolated(): return
        app = self.surface()
        source = app.original
        dialog, factor, method, action = self.dialog()
        action.focus_force()
        self.root.update()
        self.key(action, 'Return')
        self.assertFalse(dialog.winfo_exists())
        events = self.result_events()
        candidate = events[0][1][0]
        app.stop.set()
        for kind, value in events:
            app._handle_event(kind, value)
        self.assertIs(app.original, source)
        self.assertIsNone(app.upscale_original)
        self.assertTrue(app.stop.is_set())
        with self.assertRaises(ValueError): candidate.getpixel((0, 0))
        self.assertIsNone(app.activity)
        self.assertIsNone(app.worker)
        # A different source accepted while the modal was open cannot be resized
        # by the old dialog's Apply callback, even after Stop was cleared.
        app.stop.clear()
        dialog, factor, method, action = self.dialog()
        replacement = Image.new('RGBA', (5, 4), 'blue')
        self.images.append(replacement)
        app._handle_event('pasted', (replacement, None))
        action.focus_force()
        self.root.update()
        self.key(action, 'Return')
        self.assertFalse(dialog.winfo_exists())
        self.assertIs(app.original, replacement)
        self.assertIsNone(app.worker)
        self.assertTrue(app.events.empty())
        self.assertIn('changed', app.status.get())
        self.assertEqual(source.getpixel((0, 0)), (1, 97, 223, 255))
        self.assertEqual(app.mouse.mock_calls, [])

    def test_keyboard_dimension_limit_disables_apply_and_recovers_without_hidden_job(self):
        if self.isolated(): return
        app = self.surface((1800, 1000))
        source = app.original
        dialog, factor, method, action = self.dialog()
        factor.focus_force()
        self.root.update()
        self.key(factor, 'End')
        self.assertEqual(factor.get(), '4×')
        self.assertEqual(action.cget('state'), 'disabled')
        self.assertIn('25', self.visible_hint(dialog))
        action.focus_force()
        self.root.update()
        self.key(action, 'Return')
        self.assertTrue(dialog.winfo_exists())
        self.assertIsNone(app.worker)
        factor.focus_force()
        self.root.update()
        self.key(factor, 'Home')
        self.assertEqual(factor.get(), '2×')
        self.assertEqual(action.cget('state'), 'normal')
        self.assertIn('Result: 3600 × 2000', self.visible_hint(dialog))
        self.key(factor, 'Escape')
        self.assertFalse(dialog.winfo_exists())
        self.assertIs(app.original, source)
        self.assertTrue(app.events.empty())


if __name__ == '__main__':
    unittest.main()
