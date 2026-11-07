"""Real CTk global click delivery keeps composite controls' logical focus."""
import os
import sys
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock

from PIL import Image
import customtkinter as ctk

import StudioUI
from test_v148_ui_batch08_keyboard import actual_menu_factory
from test_v148_ui_batch12_switches import actual_switch_rows, switch_app


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native pointer/focus regression requires a Tk display.')
class NativeCompositePointerFocusTests(unittest.TestCase):
    def setUp(self):
        self.root = ctk.CTk()
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
        # CTk's process-wide appearance/scaling pollers can outlive a destroyed
        # test root. Cancel its remaining Tcl timers before the next case starts.
        for token in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', token)
        self.root.destroy()
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
        widget.destroy()
        self.root.update()
        self.assertIsNone(widget._keyboard_job)
        self.assertEqual(command.call_count, count)
        self.assert_destroyed_commands(commands)
        self.assert_global_bindings()

    def test_real_switch_row_canvas_text_and_background_preserve_state_and_trace_lifetime(self):
        app = switch_app(self.root)
        widgets = actual_switch_rows(app, self.root)
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
        app = SimpleNamespace(controls=[], options_changed=Mock())
        variable = tk.StringVar(self.root, value='Balanced')
        widget = actual_menu_factory(app)(self.root, variable, ['Safe', 'Balanced', 'Aggressive'])
        widget.pack()
        self.map_widgets()
        menu = widget._dropdown_menu
        for child in (widget._canvas, widget._text_label):
            before = app.options_changed.call_count
            self.click(child)
            self.assertTrue(menu.winfo_viewable())
            self.assertIn(self.root.focus_get(), (widget, menu))
            self.press_focused('Escape')
            self.assertFalse(menu.winfo_viewable())
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
        self.press_focused('F4')
        self.assertTrue(menu.winfo_viewable())
        menu.focus_force()
        self.root.update()
        for child in (widget._canvas, widget._text_label):
            for method in ('focus', 'focus_set', 'focus_force'):
                getattr(child, method)()
                self.root.update()
                self.assertIs(self.root.focus_get(), menu)
        before = app.options_changed.call_count
        self.press_focused('Down')
        self.press_focused('Return')
        self.assertEqual(variable.get(), 'Balanced')
        self.assertEqual(app.options_changed.call_count, before + 1)
        self.assertFalse(menu.winfo_viewable())
        self.assertIs(self.root.focus_get(), widget)
        self.press_focused('F4')
        menu.focus_force()
        self.root.update()
        self.press_focused('Escape')
        self.assertFalse(menu.winfo_viewable())
        self.assertEqual(variable.get(), 'Balanced')
        self.assertEqual(app.options_changed.call_count, before + 1)
        self.click(self.entry._entry)
        self.assertIs(self.root.focus_get(), self.entry._entry)

        widget.configure(state='disabled')
        for child in (widget._canvas, widget._text_label):
            self.click(child)
            self.press_focused('End')
        self.assertFalse(menu.winfo_viewable())
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
