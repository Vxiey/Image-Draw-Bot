"""The real preview pages support local, bounded keyboard inspection."""
import ast
from contextlib import ExitStack
from pathlib import Path
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import StudioUI
from PreviewNavigation import begin_pan, clear_viewport, move_pan, pan_by, record_viewport
from UiKeyboardNavigation import KeyboardPreviewCanvas
from test_v148_ui_batch06_preview import preview_callbacks


def native_canvas_boundary(canvas, parent, **values):
    """Replace only Tk allocation/event delivery, retaining the local class."""
    canvas.master = parent
    canvas.values = {'state': 'normal', **values}
    canvas.bindings = {}
    canvas.mapped = canvas.alive = True
    canvas.focused = None
    canvas.configure = lambda **kwargs: canvas.values.update(kwargs)
    canvas.cget = lambda name: canvas.values[name]
    def bind(sequence, callback, add=None):
        if add != '+': canvas.bindings[sequence] = []
        canvas.bindings.setdefault(sequence, []).append(callback)
    canvas.bind = bind
    canvas.pack = Mock()
    canvas.winfo_exists = lambda: canvas.alive
    canvas.winfo_ismapped = lambda: canvas.mapped
    canvas.focus_get = lambda: canvas.focused


def deliver(canvas, sequence, symbol='', state=0, **extra):
    result = None
    event = SimpleNamespace(widget=canvas, keysym=symbol, state=state, **extra)
    for callback in canvas.bindings.get(sequence, ()):
        result = callback(event)
        if result == 'break': break
    return result


class PreviewKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(tk.Canvas, '__init__', native_canvas_boundary))
        self.stack.enter_context(patch.object(tk.Misc, 'focus_set', lambda item: setattr(item, 'focused', item)))
        self.global_bind = self.stack.enter_context(patch.object(tk.Misc, 'bind_all'))
        seed = SimpleNamespace(winfo_ismapped=lambda: True)
        self.app, self.scope = preview_callbacks([seed], 1.0)
        self.app.closing = False
        self.app.preview_tabs = SimpleNamespace(add=lambda _name: SimpleNamespace(master=None))
        self.scope.update(KeyboardPreviewCanvas=KeyboardPreviewCanvas, PREVIEW=StudioUI.PREVIEW,
            begin_pan=begin_pan, move_pan=move_pan, preview_canvases=[])
        tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf-8'))
        build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build_ui')
        specs = next(node for node in build.body if isinstance(node, ast.Assign) and
                     any(isinstance(target, ast.Name) and target.id == 'preview_specs' for target in node.targets))
        loop = next(node for node in build.body if isinstance(node, ast.For) and
                    isinstance(node.iter, ast.Name) and node.iter.id == 'preview_specs')
        exec(compile(ast.Module(body=[specs, loop], type_ignores=[]), StudioUI.__file__, 'exec'), self.scope)
        self.canvases = self.scope['preview_canvases']
        self.canvas = self.app.original_canvas
        for canvas in self.canvases: canvas.mapped = canvas is self.canvas
        record_viewport(self.canvas, (400, 300), (100, 80), 1)
        self.canvas.focused = self.canvas

    def key(self, symbol, state=0):
        return deliver(self.canvas, '<KeyPress>', symbol, state)

    def test_actual_twelve_page_factory_connects_navigation_without_drawing_actions(self):
        self.assertEqual(len(self.canvases), 12)
        self.assertTrue(all(type(canvas) is KeyboardPreviewCanvas for canvas in self.canvases))
        self.assertEqual([canvas.values['takefocus']() for canvas in self.canvases], [True] + [False] * 11)
        self.assertEqual(self.key('Right'), 'break')
        self.assertEqual(self.canvas._preview_pan, (32.0, 0.0))
        self.app.schedule_previews.assert_called_once_with(delay=30)
        self.key('plus')
        self.assertEqual(self.app.preview_zoom.get(), 1.25)
        self.key('minus')
        self.assertEqual(self.app.preview_zoom.get(), 1.0)
        self.key('0')
        self.assertEqual(self.app.preview_zoom.get(), 0.0)
        self.assertTrue(all(canvas._preview_pan == (0.0, 0.0) for canvas in self.canvases))
        self.key('1')
        self.assertEqual(self.app.preview_zoom.get(), 1.0)
        self.global_bind.assert_not_called()

    def test_pan_uses_display_distance_clamps_and_reverses_immediately(self):
        record_viewport(self.canvas, (400, 300), (100, 80), 2)
        self.app.preview_zoom.set(2)
        self.key('Right')
        self.assertEqual(self.canvas._preview_pan, (16.0, 0.0))
        self.key('Down', 1)
        self.assertEqual(self.canvas._preview_pan, (16.0, 80.0))
        self.key('Next')
        self.assertEqual(self.canvas._preview_pan, (16.0, 112.0))
        for _ in range(10): self.key('Right', 1)
        self.assertEqual(self.canvas._preview_pan[0], 175.0)
        calls = self.app.schedule_previews.call_count
        self.key('Right')
        self.assertEqual(self.app.schedule_previews.call_count, calls)
        self.key('Left')
        self.assertEqual(self.canvas._preview_pan[0], 159.0)
        self.key('Home')
        self.assertEqual(self.canvas._preview_pan, (0.0, 0.0))
        calls = self.app.schedule_previews.call_count
        self.key('Home')
        self.assertEqual(self.app.schedule_previews.call_count, calls)
        self.app.preview_zoom.set(0)
        self.key('Right')
        self.assertEqual(self.app.schedule_previews.call_count, calls)

    def test_local_guard_rejects_invisible_closed_disabled_or_unfocused_pages(self):
        for change in ('unmapped', 'destroyed', 'disabled', 'closing', 'unfocused', 'empty', 'clipped'):
            with self.subTest(change=change):
                record_viewport(self.canvas, (400, 300), (100, 80), 1)
                self.canvas.mapped = self.canvas.alive = True
                self.canvas.values['state'] = 'normal'
                self.canvas.focused = self.canvas
                self.app.closing = False
                self.canvas._keyboard_in_view = lambda: change != 'clipped'
                if change == 'unmapped': self.canvas.mapped = False
                elif change == 'destroyed': self.canvas.alive = False
                elif change == 'disabled': self.canvas.values['state'] = 'disabled'
                elif change == 'closing': self.app.closing = True
                elif change == 'unfocused': self.canvas.focused = None
                elif change == 'empty': clear_viewport(self.canvas)
                self.app.schedule_previews.reset_mock()
                for key in ('Right', 'Next', 'Home', 'plus', '0', '1'): self.key(key)
                self.assertEqual(self.canvas._preview_pan, (0.0, 0.0))
                self.app.schedule_previews.assert_not_called()

    def test_modifiers_and_application_shortcuts_keep_their_existing_bindings(self):
        for symbol in ('Tab', 'ISO_Left_Tab', 'Escape', 'F1', 'F6', 'Return'):
            self.assertIsNone(self.key(symbol))
        for modifier in (4, 8, 128, 0x20000):
            for symbol in ('Right', 'plus', '0'):
                self.assertIsNone(self.key(symbol, modifier))
        self.app.schedule_previews.assert_not_called()
        self.global_bind.assert_not_called()

    def test_pointer_drag_retains_its_actual_handlers_and_adds_local_focus(self):
        self.canvas.focused = None
        deliver(self.canvas, '<ButtonPress-1>', x=20, y=30)
        self.assertIs(self.canvas.focused, self.canvas)
        self.assertEqual(self.canvas._drag, (20.0, 30.0))
        deliver(self.canvas, '<B1-Motion>', x=30, y=50)
        self.assertEqual(self.canvas._preview_pan, (-10.0, -20.0))
        self.app.schedule_previews.assert_called_once_with(delay=30)

    def test_physical_step_helper_never_pans_an_empty_fit_or_nonfinite_request(self):
        for step in ((float('nan'), 1), (0, float('inf'))):
            self.assertFalse(pan_by(self.canvas, *step, 1))
        self.assertFalse(pan_by(self.canvas, 10, 10, 0))
        clear_viewport(self.canvas)
        self.assertFalse(pan_by(self.canvas, 10, 10, 1))


@unittest.skipUnless(sys.platform == 'win32', 'Native Tk keyboard delivery runs on Windows CI.')
class NativePreviewKeyboardTests(unittest.TestCase):
    def test_tab_focus_local_delivery_visibility_and_tcl_cleanup(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('600x360')
        before = tk.Button(root, text='Before'); before.pack()
        zoom = tk.DoubleVar(root, value=1)
        changed = Mock()
        canvas = KeyboardPreviewCanvas(root, bg='#101319', width=300, height=160,
            get_zoom=zoom.get, set_zoom=zoom.set, step_zoom=lambda delta: zoom.set(zoom.get()+delta), on_pan=changed)
        canvas.pack()
        after = tk.Button(root, text='After'); after.pack()
        root.update()
        record_viewport(canvas, (800, 600), (300, 160), 1)
        self.assertEqual(str(root.tk.call('tk_focusNext', before._w)), canvas._w)
        before_globals = root.bind_all('<KeyPress>')
        escaped = []
        root.bind('<Escape>', lambda _event: escaped.append(True), add='+')
        canvas.focus_force(); root.update()
        canvas.event_generate('<KeyPress-Right>'); root.update()
        self.assertEqual(canvas._preview_pan, (32.0, 0.0))
        changed.assert_called_once_with()
        canvas.event_generate('<KeyPress-plus>'); root.update()
        self.assertEqual(zoom.get(), 1.25)
        canvas.event_generate('<Escape>'); root.update()
        self.assertEqual(escaped, [True])
        self.assertEqual(int(canvas.cget('highlightthickness')), 2)
        self.assertEqual(canvas.cget('highlightcolor'), '#72e2bd')
        canvas.pack_forget(); root.update()
        self.assertFalse(canvas._keyboard_focusable())
        self.assertEqual(str(root.tk.call('tk_focusNext', before._w)), after._w)
        commands = tuple(canvas._tclCommands)
        canvas.destroy(); root.update()
        for command in commands:
            self.assertFalse(root.tk.call('info', 'commands', command))
        self.assertEqual(root.bind_all('<KeyPress>'), before_globals)


if __name__ == '__main__':
    unittest.main()
