"""Visible Studio primary-button focus completes the existing UK01 contract.

These cases use the actual Studio factory, KeyboardButton and native Tk canvas.
No widgets or callbacks are mocked, and no images are created. Each native case
runs in its own process so retained failure tracebacks cannot outlive a Tk owner
and be collected by an unrelated later worker.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import traceback
import unittest

import customtkinter as ctk

import StudioUI
from UiCompatibility import scoped_window_class
from UiKeyboardNavigation import KeyboardButton


def contrast_ratio(first, second):
    """Relative sRGB luminance ratio for the actual hexadecimal UI colors."""
    def luminance(color):
        values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in values]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + .05) / (darker + .05)


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native Tk display required')
class NativeStudioFocusTests(unittest.TestCase):
    def isolated(self):
        name = f'{Path(__file__).stem}.{type(self).__name__}.{self._testMethodName}'
        if os.environ.get('IDB_UI_FOCUS_CASE') == name:
            return False
        result = subprocess.run(
            [sys.executable, '-X', 'faulthandler', '-m', 'unittest', '-v', name],
            cwd=Path(__file__).resolve().parent,
            env=dict(os.environ, IDB_UI_FOCUS_CASE=name),
            text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=20,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        for diagnostic in ('invalid command name', 'Tcl_AsyncDelete', 'Exception ignored in'):
            self.assertNotIn(diagnostic, output)
        return True

    @contextmanager
    def surface(self):
        root = scoped_window_class(ctk.CTk)()
        root.geometry('420x300+50+50')
        callback_errors = []
        root.report_callback_exception = lambda *error: callback_errors.append(
            ''.join(traceback.format_exception(*error)))
        try:
            yield root
        finally:
            root.destroy()
            self.assertEqual(callback_errors, [])

    def outline(self, item):
        tags = item._canvas.find_withtag(item._focus_tag)
        self.assertEqual(len(tags), 1)
        return item._canvas.itemcget(tags[0], 'outline')

    def test_actual_factory_focus_remains_visible_on_normal_and_hover_fills(self):
        if self.isolated():
            return
        with self.surface() as root:
            buttons = [(kind, StudioUI.button(root, kind, lambda: None, **options))
                       for kind, options in (
                           ('Primary', {'primary': True}),
                           ('Secondary', {}),
                           ('Danger', {'danger': True}),
                       )]
            for _kind, item in buttons:
                self.assertIsInstance(item, KeyboardButton)
                item.pack(pady=5)
            root.update()

            for kind, item in buttons:
                with self.subTest(kind=kind):
                    item.focus_force()
                    root.update()
                    self.assertIs(root.focus_get(), item)
                    outline = self.outline(item)
                    self.assertEqual(outline, item._keyboard_focus_color)
                    if kind != 'Primary':
                        self.assertEqual(outline, StudioUI.ACCENT)
                    for fill in ('fg_color', 'hover_color'):
                        self.assertGreaterEqual(
                            contrast_ratio(outline, item.cget(fill)), 3.0,
                            f'{kind} focus {outline} disappears against {fill}={item.cget(fill)}',
                        )
                    # Run CTk's real hover callbacks and inspect their native
                    # canvas colors; changing the fill must retain the outline.
                    item._on_enter()
                    self.assertEqual(item._canvas.itemcget('inner_parts', 'fill'), item.cget('hover_color'))
                    self.assertEqual(self.outline(item), outline)
                    item._on_leave()
                    self.assertEqual(item._canvas.itemcget('inner_parts', 'fill'), item.cget('fg_color'))
                    self.assertEqual(self.outline(item), outline)

    def test_caller_focus_override_and_disabled_or_unfocused_states_are_preserved(self):
        if self.isolated():
            return
        with self.surface() as root:
            item = StudioUI.button(root, 'Custom primary', lambda: None,
                                   primary=True, focus_color='#ffffff')
            other = StudioUI.button(root, 'Other action', lambda: None)
            item.pack(pady=5)
            other.pack(pady=5)
            root.update()
            item.focus_force()
            root.update()
            self.assertEqual(self.outline(item), '#ffffff')

            other.focus_force()
            root.update()
            self.assertEqual(item._canvas.find_withtag(item._focus_tag), ())
            item.focus_force()
            root.update()
            item.configure(state='disabled')
            root.update()
            self.assertEqual(item._canvas.find_withtag(item._focus_tag), ())
            item.configure(state='normal')
            root.update()
            self.assertEqual(self.outline(item), '#ffffff')


if __name__ == '__main__':
    unittest.main()
