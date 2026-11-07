"""Real CTk global click delivery keeps composite controls' logical focus."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock

from PIL import Image
import customtkinter as ctk

import StudioUI
from test_v148_ui_batch08_keyboard import actual_menu_factory
from test_v148_ui_batch10_numeric import release_factory_scopes
from test_v148_ui_batch12_switches import actual_switch_rows, switch_app


_SELECTOR_CASE = 'test_selector_decorations_keep_logical_focus_without_stealing_native_popup_or_entry'
_MENU_CHILD = 'IMAGEDRAWBOT_NATIVE_MENU_TEST_CHILD'


class NativePopupDriver:
    """Drive a real menu from callbacks scheduled before its modal entry."""
    def __init__(self, case, widget):
        self.case, self.root, self.widget = case, case.root, widget
        self.menu = widget._dropdown_menu
        self.windows = sys.platform == 'win32'
        if self.windows:
            import ctypes
            from WindowsSystem import load_system_library
            self.ctypes = ctypes

            class Rect(ctypes.Structure):
                _fields_ = [(name, ctypes.c_int32) for name in ('left', 'top', 'right', 'bottom')]

            class GuiThreadInfo(ctypes.Structure):
                _fields_ = [('cbSize', ctypes.c_uint32), ('flags', ctypes.c_uint32)] + [
                    (name, ctypes.c_void_p) for name in ('hwndActive', 'hwndFocus', 'hwndCapture',
                        'hwndMenuOwner', 'hwndMoveSize', 'hwndCaret')] + [('rcCaret', Rect)]

            self.info_type = GuiThreadInfo
            self.thread_id = threading.get_native_id()
            self.api = load_system_library('user32', use_last_error=True)
            self.api.GetGUIThreadInfo.argtypes = [ctypes.c_uint32, ctypes.POINTER(GuiThreadInfo)]
            self.api.GetGUIThreadInfo.restype = ctypes.c_int32
            self.api.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            self.api.GetWindowThreadProcessId.restype = ctypes.c_uint32
            self.api.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t]
            self.api.PostMessageW.restype = ctypes.c_int32
            self.api.MapVirtualKeyW.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
            self.api.MapVirtualKeyW.restype = ctypes.c_uint32
            self.api.EndMenu.argtypes = []
            self.api.EndMenu.restype = ctypes.c_int32

    def native_state(self):
        info = self.info_type()
        info.cbSize = self.ctypes.sizeof(info)
        self.case.assertTrue(self.api.GetGUIThreadInfo(self.thread_id, self.ctypes.byref(info)),
                             f'GetGUIThreadInfo failed: {self.ctypes.get_last_error()}')
        return info

    def visible(self):
        # Windows TrackPopupMenu owns an HMENU, not a mapped Tk menu window.
        return bool(self.native_state().flags & 0x10) if self.windows else bool(self.menu.winfo_viewable())

    def assert_open(self):
        self.case.assertTrue(self.visible(), 'The real popup is not active')
        if self.windows:
            info = self.native_state()
            self.case.assertTrue(info.flags & 0x04, 'GUI_INMENUMODE must accompany the popup')
            self.case.assertTrue(info.hwndMenuOwner)
            pid = self.ctypes.c_uint32()
            thread = self.api.GetWindowThreadProcessId(info.hwndMenuOwner, self.ctypes.byref(pid))
            self.case.assertEqual(thread, self.thread_id)
            self.case.assertEqual(pid.value, os.getpid())
            return info.hwndMenuOwner
        return self.menu

    def assert_closed(self):
        self.case.assertFalse(self.visible(), 'The real popup did not close')

    def assert_owner(self, owner):
        self.case.assertEqual(self.assert_open(), owner)
        if not self.windows:
            self.case.assertIs(self.root.focus_get(), self.menu)

    def key(self, symbol):
        if self.windows:
            owner = self.assert_open()
            code = {'Escape': 0x1B, 'Down': 0x28, 'Return': 0x0D}[symbol]
            scan = self.api.MapVirtualKeyW(code, 0)
            flags = 1 | (scan << 16) | (0x01000000 if symbol == 'Down' else 0)
            # Address only this test's verified native menu owner. The Windows
            # modal loop consumes real queued key messages, not menu.invoke().
            for message, value in ((0x0100, flags), (0x0101, flags | 0xC0000000)):
                self.case.assertTrue(self.api.PostMessageW(owner, message, code, value),
                    f'Native {symbol} delivery failed: {self.ctypes.get_last_error()}')
        else:
            focused = self.root.focus_get()
            self.case.assertIsNotNone(focused)
            focused.event_generate('<KeyPress-' + symbol + '>', when='tail')
            focused.event_generate('<KeyRelease-' + symbol + '>', when='tail')

    def highlight(self, index):
        """Return an action that navigates with Down and observes native state.

        Tk/Windows mirrors WM_MENUSELECT into the read-only active index. Home
        does not establish the assumed first-item baseline on every Windows
        menu. Wait for each real navigation event before sending another key.
        """
        waiting, sent = object(), 0
        limit = int(self.menu.index('end')) + 2

        def advance():
            nonlocal waiting, sent
            current = self.menu.index('active')
            if current == index:
                return True
            if current != waiting:
                self.case.assertLess(sent, limit,
                    f'Native menu did not reach index {index}; active={current}, Down events={sent}')
                self.key('Down')
                waiting = current
                sent += 1
            return False

        return advance

    def abort(self):
        # This is failure cleanup only; successful Escape/Return must dismiss
        # the actual menu themselves before the driver accepts the result.
        if self.windows:
            if self.visible():
                self.assert_open()
                self.api.EndMenu()
        else:
            self.menu.unpost()
            if self.menu.grab_current() is self.menu:
                self.menu.grab_release()

    def run(self, open_popup, actions):
        finished = tk.BooleanVar(self.root, value=False)
        failures, timers = [], set()

        def fail(error):
            failures.append(error)
            try:
                self.abort()
            finally:
                finished.set(True)

        def later(callback, delay=20):
            token = None

            def invoke():
                timers.discard(token)
                if finished.get():
                    return
                try:
                    callback()
                except BaseException as error:
                    fail(error)

            token = self.root.after(delay, invoke)
            timers.add(token)

        def closed():
            if self.visible():
                later(closed)
            else:
                finished.set(True)

        def step(index=0):
            self.assert_open()
            complete = actions[index]() is not False
            following = index + 1 if complete else index
            later((lambda: step(following)) if following < len(actions) else closed)

        def opened():
            if self.visible():
                step()
            else:
                later(opened)

        def timeout():
            raise AssertionError('Native popup did not complete its interaction within 3 seconds')

        later(opened)
        later(timeout, 3000)
        try:
            # Tk/Windows enters TrackPopupMenu here and returns only after the
            # scheduled interaction closes it. X11 returns before that work.
            open_popup()
            if not finished.get():
                self.root.wait_variable(finished)
        except BaseException:
            self.abort()
            raise
        finally:
            for token in timers:
                self.root.after_cancel(token)
        if failures:
            raise failures[0]
        self.assert_closed()


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native pointer/focus regression requires a Tk display.')
class NativeCompositePointerFocusTests(unittest.TestCase):
    def setUp(self):
        # A broken native modal loop must fail this case, not stall the whole
        # Windows regression job. The child executes every original assertion.
        if self._testMethodName == _SELECTOR_CASE and os.environ.get(_MENU_CHILD) != '1':
            self.root = None
            return
        from UiCompatibility import scoped_window_class
        self.root = scoped_window_class(ctk.CTk)()
        self.factory_scopes = []
        self.root.geometry('740x620+30+30')
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.images = []
        self.entry = ctk.CTkEntry(self.root)
        self.entry.pack()
        self.clicks = []
        self.root.bind_all('<Button-1>',
            lambda event: self.clicks.append((event.widget, self.root.focus_get())), add='+')
        self.bindings = {sequence: self.root.bind_all(sequence)
                         for sequence in ('<Button-1>', '<KeyPress>', '<Tab>', '<Escape>')}

    def tearDown(self):
        if self.root is None:
            return
        # Use the same owned callback/shared-service teardown as the app root.
        self.root.destroy()
        release_factory_scopes(self.factory_scopes)
        for image in self.images:
            image.close()
        self.assertFalse(self.errors, self.errors)

    def map_widgets(self):
        self.root.update()
        self.entry.focus_force()
        self.root.update()
        self.assertIs(self.root.focus_get(), self.entry._entry)

    def click(self, child):
        child.event_generate('<Enter>', x=6, y=6, when='now')
        child.event_generate('<ButtonPress-1>', x=6, y=6, when='now')
        child.event_generate('<ButtonRelease-1>', x=6, y=6, when='now')
        self.root.update()

    def press_focused(self, symbol='space'):
        focused = self.root.focus_get()
        self.assertIsNotNone(focused)
        focused.event_generate('<KeyPress-' + symbol + '>', when='now')
        focused.event_generate('<KeyRelease-' + symbol + '>', when='now')
        self.root.update()

    def assert_owner(self, child, widget):
        self.assertIs(self.root.focus_get(), widget)
        self.assertEqual(self.clicks[-1], (child, widget))
        self.assertEqual(int(child.cget('takefocus')), 0)
        self.assertEqual(len(widget._canvas.find_withtag(widget._focus_tag)), 1)

    def assert_focus_entries(self, child, widget):
        for method in ('focus', 'focus_set', 'focus_force'):
            self.entry.focus_force()
            self.root.update()
            getattr(child, method)()
            self.root.update()
            self.assertIs(self.root.focus_get(), widget)

    @staticmethod
    def owned_commands(widget):
        commands = list(widget._tclCommands or ())
        for child in widget.winfo_children():
            commands.extend(NativeCompositePointerFocusTests.owned_commands(child))
        return commands

    def assert_destroyed_commands(self, commands):
        for token in commands:
            self.assertFalse(self.root.tk.call('info', 'commands', token), token)

    def assert_global_bindings(self):
        self.assertEqual({sequence: self.root.bind_all(sequence)
                          for sequence in self.bindings}, self.bindings)

    def test_button_canvas_and_late_text_image_labels_keep_pointer_to_key_activation(self):
        command = Mock()
        widget = StudioUI.button(self.root, '', command)
        widget.pack()
        self.map_widgets()

        def activate(child):
            before = command.call_count
            self.click(child)
            self.assertEqual(command.call_count, before + 1)
            self.assert_owner(child, widget)
            self.press_focused()
            self.assertEqual(command.call_count, before + 2)
            self.assert_focus_entries(child, widget)

        activate(widget._canvas)
        widget.configure(text='Late text label')
        self.root.update()
        original_label = widget._text_label
        activate(original_label)
        widget.configure(text='', require_redraw=True)
        widget.configure(text='Replacement label')
        self.root.update()
        self.assertIsNot(widget._text_label, original_label)
        self.assertFalse(original_label.winfo_exists())
        activate(widget._text_label)
        image = Image.new('RGB', (16, 16), '#72e2bd')
        self.images.append(image)
        widget.configure(image=ctk.CTkImage(light_image=image, size=(16, 16)))
        self.root.update()
        original_image = widget._image_label
        activate(original_image)
        widget.configure(image=None, require_redraw=True)
        widget.configure(image=ctk.CTkImage(light_image=image, size=(16, 16)))
        self.root.update()
        self.assertIsNot(widget._image_label, original_image)
        self.assertFalse(original_image.winfo_exists())
        activate(widget._image_label)

        count = command.call_count
        widget.configure(state='disabled')
        for child in (widget._canvas, widget._text_label, widget._image_label):
            self.click(child)
            self.press_focused()
        self.assertEqual(command.call_count, count)
        self.click(self.entry._entry)
        self.assertIs(self.root.focus_get(), self.entry._entry)

        # A pending key release belongs to this widget, including after clicks.
        widget.configure(state='normal')
        widget.focus_force()
        self.root.update()
        widget.event_generate('<KeyPress-space>', when='now')
        widget.event_generate('<KeyRelease-space>', when='now')
        self.assertIsNotNone(widget._keyboard_job)
        commands = self.owned_commands(widget)
        owned_jobs = set()
        for token in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            script, _kind = self.root.tk.call('after', 'info', token)
            words = self.root.tk.splitlist(script)
            if len(words) == 1 and words[0] in commands:
                owned_jobs.add(token)
        widget.destroy()
        self.assertFalse(owned_jobs & set(self.root.tk.splitlist(self.root.tk.call('after', 'info'))),
                         'Deleting a button command must also retire its delayed animation script')
        self.root.update()
        self.assertIsNone(widget._keyboard_job)
        self.assertEqual(command.call_count, count)
        self.assert_destroyed_commands(commands)
        self.assert_global_bindings()

    def test_real_switch_row_canvas_text_and_background_preserve_state_and_trace_lifetime(self):
        app = switch_app(self.root)
        widgets = actual_switch_rows(app, self.root, scopes=self.factory_scopes)
        widget = widgets[0]
        widget.pack()
        command = app.paint_mode_changed
        self.map_widgets()
        self.assertFalse(app.paint_simple.get())
        for child in (widget._canvas, widget._text_label):
            before = command.call_count
            self.click(child)
            self.assert_owner(child, widget)
            self.assertTrue(app.paint_simple.get())
            self.assertEqual(command.call_count, before + 1)
            self.press_focused()
            self.assertFalse(app.paint_simple.get())
            self.assertEqual(command.call_count, before + 2)
            self.assert_focus_entries(child, widget)
        widget.configure(text='Changed switch text')
        self.root.update()
        self.click(widget._text_label)
        self.assert_owner(widget._text_label, widget)
        self.press_focused()
        self.assertFalse(app.paint_simple.get())
        before = command.call_count
        self.click(widget._bg_canvas)
        self.assert_owner(widget._bg_canvas, widget)
        self.assertEqual(command.call_count, before)
        self.press_focused()
        self.assertTrue(app.paint_simple.get())
        self.assertEqual(command.call_count, before + 1)

        widget.configure(state='disabled')
        before = command.call_count
        for child in (widget._canvas, widget._text_label, widget._bg_canvas):
            self.click(child)
            self.press_focused()
        self.assertTrue(app.paint_simple.get())
        self.assertEqual(command.call_count, before)
        commands = self.owned_commands(widget)
        widget.destroy()
        self.root.update()
        self.assertFalse(app.paint_simple.trace_info())
        self.assert_destroyed_commands(commands)
        self.assert_global_bindings()

    def test_selector_decorations_keep_logical_focus_without_stealing_native_popup_or_entry(self):
        if self.root is None:
            command = [sys.executable, '-m', 'unittest', '-v',
                f'{Path(__file__).stem}.NativeCompositePointerFocusTests.{_SELECTOR_CASE}']
            try:
                result = subprocess.run(command, cwd=Path(__file__).resolve().parent,
                    env=dict(os.environ, **{_MENU_CHILD: '1'}), capture_output=True, text=True, timeout=20)
            except subprocess.TimeoutExpired as error:
                self.fail(f'Native popup child exceeded 20 seconds.\n{error.stdout}\n{error.stderr}')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        import faulthandler
        faulthandler.dump_traceback_later(12)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        app = SimpleNamespace(controls=[], options_changed=Mock())
        variable = tk.StringVar(self.root, value='Balanced')
        widget = actual_menu_factory(app)(self.root, variable, ['Safe', 'Balanced', 'Aggressive'])
        widget.pack()
        self.map_widgets()
        menu = widget._dropdown_menu
        driver = NativePopupDriver(self, widget)
        for child in (widget._canvas, widget._text_label):
            before = app.options_changed.call_count
            driver.run(lambda: self.click(child), [
                lambda: self.assertIn(self.root.focus_get(), (widget, menu)),
                lambda: driver.key('Escape'),
            ])
            driver.assert_closed()
            self.assertFalse(widget._close_on_next_click)
            self.assertIs(self.root.focus_get(), widget)
            self.assertIn(self.clicks[-1], ((child, widget), (child, menu)))
            self.assertEqual(int(child.cget('takefocus')), 0)
            self.assertEqual(len(widget._canvas.find_withtag(widget._focus_tag)), 1)
            self.press_focused('Down')
            self.assertEqual(variable.get(), 'Aggressive')
            self.assertEqual(app.options_changed.call_count, before + 1)
            self.assert_focus_entries(child, widget)
            widget.set('Balanced')

        # Real native menu focus and menu entry dispatch remain native. The
        # decorative child's delayed/global focus call cannot steal it back.
        widget.set('Safe')
        widget.focus_force()
        self.root.update()
        owner = []
        actions = []
        if not driver.windows:
            actions.append(menu.focus_force)
        actions.append(lambda: owner.append(driver.assert_open()))
        for child in (widget._canvas, widget._text_label):
            for method in ('focus', 'focus_set', 'focus_force'):
                actions.append(lambda child=child, method=method: getattr(child, method)())
                actions.append(lambda: driver.assert_owner(owner[0]))
        before = app.options_changed.call_count
        # Observe actual highlight on both platforms; do not infer it from
        # focus or the entry argument passed to tk_popup. Only native Down
        # events select the highlighted entries, and Return invokes the item.
        actions.extend((driver.highlight(0),
            lambda: self.assertEqual(menu.entrycget(menu.index('active'), 'label').strip(), 'Safe'),
            driver.highlight(1),
            lambda: self.assertEqual(menu.entrycget(menu.index('active'), 'label').strip(), 'Balanced'),
            lambda: self.assertEqual(variable.get(), 'Safe'),
            lambda: self.assertEqual(app.options_changed.call_count, before),
            lambda: driver.key('Return')))
        driver.run(lambda: self.press_focused('F4'), actions)
        self.assertEqual(variable.get(), 'Balanced')
        self.assertEqual(app.options_changed.call_count, before + 1)
        driver.assert_closed()
        self.assertFalse(widget._close_on_next_click)
        self.assertIs(self.root.focus_get(), widget)
        for _ in range(2):
            # Reopening after Escape needs one F4, without a pointer Enter or
            # a Tk-menu Unmap to repair Windows' native modal return state.
            driver.run(lambda: self.press_focused('F4'), [lambda: driver.key('Escape')])
            driver.assert_closed()
            self.assertFalse(widget._close_on_next_click)
            self.assertEqual(variable.get(), 'Balanced')
            self.assertEqual(app.options_changed.call_count, before + 1)
        self.click(self.entry._entry)
        self.assertIs(self.root.focus_get(), self.entry._entry)

        widget.configure(state='disabled')
        for child in (widget._canvas, widget._text_label):
            self.click(child)
            self.press_focused('End')
        driver.assert_closed()
        self.assertEqual(variable.get(), 'Balanced')
        self.assertEqual(app.options_changed.call_count, before + 1)
        commands = self.owned_commands(widget)
        widget.destroy()
        self.root.update()
        self.assertFalse(variable.trace_info())
        self.assert_destroyed_commands(commands)
        self.assert_global_bindings()


if __name__ == '__main__':
    unittest.main()
