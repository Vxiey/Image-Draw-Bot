"""Precise contrast input follows the real CTk variable and controller paths."""
import ast
from contextlib import ExitStack
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import MethodType, SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk
from customtkinter.windows.widgets.core_widget_classes import CTkBaseClass

import DrawBot
import StudioUI
from UiKeyboardNavigation import KeyboardSlider
from test_v148_ui_batch10_numeric import controller_app
from test_v148_ui_batch12_switches import Scheduler
from test_v148_ui_layout_batch04 import ScrollHarness, panel
from test_v148_application_batch14_browser_start import DeferredThread


def event(symbol='', state=0, *, delta=0, num=None, x=0, y=0):
    return SimpleNamespace(keysym=symbol, state=state, delta=delta, num=num, x=x, y=y)


class Surface:
    """Native allocation/drawing boundary; value, input and trace code stays real."""
    def __init__(self, *args, **kwargs):
        self.options = dict(kwargs)
        self.bindings = {}
        self.pack = Mock()
        self.delete = Mock()
        self.create_rectangle = Mock()
        self.tag_raise = Mock()

    def configure(self, **kwargs): self.options.update(kwargs)
    def cget(self, name): return self.options[name]
    def winfo_width(self): return 240
    def winfo_height(self): return 24

    def bind(self, sequence, callback, add=None):
        if add not in ('+', True): self.bindings[sequence] = []
        self.bindings.setdefault(sequence, []).append(callback)

    def deliver(self, sequence, value=None):
        result = None
        for callback in tuple(self.bindings.get(sequence, ())):
            result = callback(value or event())
            if result == 'break': break
        return result


def actual_contrast_row(app, parent):
    """Run the active StudioUI row and its real factories/callbacks."""
    tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf8'))
    build = next(node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == 'build_ui')
    nodes = [node for node in build.body
             if isinstance(node, ast.FunctionDef) and node.name in ('label', 'control')]
    active = False
    for node in build.body:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)] \
            if isinstance(node, ast.Assign) else []
        if 'contrast_value' in names: active = True
        if 'gpu_card' in names: break
        if active: nodes.append(node)
    scope = dict(vars(StudioUI), a=app, smart_card=parent)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), StudioUI.__file__, 'exec'), scope)
    return scope['contrast_slider'], scope['contrast_value']


class ContrastKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.interpreter = tk.Tcl()
        self.widgets = []
        self.addCleanup(self.close_widgets)
        self.stack.enter_context(patch.object(ctk.CTkSlider, '__init__',
            lambda widget, *args, **kwargs: self.native_init(widget, *args, **kwargs)))
        self.stack.enter_context(patch.object(ctk.CTkSlider, '_draw'))
        self.stack.enter_context(patch.object(ctk.CTkSlider, '_set_cursor'))
        self.stack.enter_context(patch.object(ctk, 'CTkLabel', Surface))
        self.stack.enter_context(patch.object(CTkBaseClass, 'configure', self.native_configure))
        self.stack.enter_context(patch.object(CTkBaseClass, 'destroy', self.native_destroy))
        self.stack.enter_context(patch.object(tk.Frame, 'configure', self.frame_configure))
        self.stack.enter_context(patch.object(tk.Misc, 'bind', self.logical_bind))
        self.stack.enter_context(patch.object(tk.Misc, 'focus_set', self.logical_focus))
        self.global_bind = self.stack.enter_context(patch.object(tk.Misc, 'bind_all'))

    def native_init(self, widget, master=None, **kwargs):
        widget.master = master
        widget._state = kwargs.get('state', 'normal')
        widget._from_, widget._to = kwargs.get('from_', 0), kwargs.get('to', 1)
        widget._number_of_steps = kwargs.get('number_of_steps')
        widget._scroll_step = .05
        widget._value = .5
        widget._output_value = widget._from_ + .5 * (widget._to - widget._from_)
        widget._orientation = kwargs.get('orientation', 'horizontal')
        widget._current_width, widget._current_height = 240, 24
        widget._variable = kwargs.get('variable')
        widget._variable_callback_blocked = False
        widget._command = kwargs.get('command')
        widget._canvas = Surface()
        widget._variable_callback_name = (widget._variable.trace_add('write', widget._variable_callback)
                                         if widget._variable is not None else None)
        widget.winfo_exists = Mock(return_value=True)
        widget.winfo_ismapped = Mock(return_value=True)
        widget.winfo_class = lambda: 'Frame'
        widget.focus_get = Mock(return_value=widget)
        widget._get_widget_scaling = lambda: 1
        widget._reverse_widget_scaling = lambda value: value
        widget.pack = Mock()
        widget.native_options = {}
        widget.logical_surface = Surface()
        widget.scheduler = Scheduler()
        widget.after, widget.after_cancel = widget.scheduler.after, widget.scheduler.after_cancel
        widget._create_bindings()
        if widget._variable is not None:
            widget.set(widget._variable.get(), from_variable_callback=True)
        self.widgets.append(widget)

    @staticmethod
    def native_configure(widget, require_redraw=False, **kwargs):
        widget.native_options.update(kwargs)
        if require_redraw: widget._draw()

    @staticmethod
    def frame_configure(widget, **kwargs): widget.native_options.update(kwargs)
    @staticmethod
    def native_destroy(widget): widget.winfo_exists.return_value = False
    @staticmethod
    def logical_bind(widget, sequence, callback, add=None):
        widget.logical_surface.bind(sequence, callback, add=add)
    @staticmethod
    def logical_focus(widget): widget.focus_get.return_value = widget

    def close_widgets(self):
        for widget in self.widgets:
            if not widget._keyboard_closed: widget.destroy()

    def slider(self, **kwargs):
        kwargs.setdefault('variable', tk.DoubleVar(self.interpreter, value=1.25))
        kwargs.setdefault('command', Mock())
        return KeyboardSlider(None, from_=.5, to=2, reset_value=1.0, **kwargs)

    @staticmethod
    def press(widget, symbol, state=0):
        return widget.logical_surface.deliver('<KeyPress>', event(symbol, state))

    def test_numeric_keys_follow_native_variable_then_command_with_bounded_steps(self):
        variable = tk.DoubleVar(self.interpreter, value=1.25)
        observed = []
        widget = self.slider(variable=variable,
            command=lambda value: observed.append(('command', value, variable.get())))
        trace = variable.trace_add('write', lambda *_: observed.append(('variable', variable.get())))
        self.addCleanup(variable.trace_remove, 'write', trace)
        for symbol, state, expected in (
                ('Right', 0, 1.26), ('Up', 1, 1.36), ('Next', 0, 1.26),
                ('Prior', 0, 1.36), ('Down', 0, 1.35), ('Left', 1, 1.25),
                ('Home', 0, .5), ('End', 0, 2), ('BackSpace', 0, 1)):
            before = len(observed)
            self.assertEqual(self.press(widget, symbol, state), 'break')
            self.assertAlmostEqual(widget.get(), expected)
            self.assertAlmostEqual(variable.get(), expected)
            self.assertEqual(observed[before][0], 'variable')
            self.assertEqual(observed[before + 1][0], 'command')
            self.assertEqual(observed[before][1], observed[before + 1][1])
            self.assertEqual(observed[before + 1][1], observed[before + 1][2])
            self.assertEqual(len(observed), before + 2)
        for symbol in ('Home', 'End', 'BackSpace'):
            self.press(widget, symbol)
            before = len(observed)
            self.press(widget, symbol)
            self.assertEqual(len(observed), before)
        widget.set(1.253)
        self.press(widget, 'Right')
        self.assertAlmostEqual(variable.get(), 1.26)
        for _ in range(400): self.press(widget, 'Right')
        self.assertEqual(variable.get(), 2)
        before = len(observed)
        self.press(widget, 'Right')
        self.assertEqual(len(observed), before)
        self.press(widget, 'Left')
        self.assertAlmostEqual(variable.get(), 1.99)

    def test_real_factory_and_controller_invalidate_once_without_starting_work(self):
        app = controller_app(self.interpreter, Scheduler())
        app.contrast = tk.DoubleVar(self.interpreter, value=1.25)
        app._safe_widget_configure = DrawBot.DrawBotApp._safe_widget_configure
        for name in ('draw', 'quick_start', 'begin_worker'): setattr(app, name, Mock())
        for name in ('_refresh_start_buttons_text', '_refresh_target_lock_text'):
            self.stack.enter_context(patch.object(DrawBot.DrawBotApp, name))
        self.stack.enter_context(patch('DrawBot.log_event'))
        widget, label = actual_contrast_row(app, object())
        self.assertEqual(app.controls, [(widget, 'normal')])
        self.assertIs(widget.cget('variable'), app.contrast)
        self.assertEqual(label.cget('text'), 'Contrast · 1.25×')
        self.press(widget, 'Right')
        self.assertIsNone(app.plan)
        self.assertFalse(app.small_test_passed)
        self.assertEqual(app.preview_generation, 1)
        self.assertEqual(label.cget('text'), 'Contrast · 1.26×')
        with tempfile.TemporaryDirectory() as directory, \
                patch('RuntimePaths.source_dir', return_value=Path(directory)), \
                patch('DrawBot.custom_rgb_available', return_value=False):
            self.assertAlmostEqual(DrawBot.DrawBotApp.options(app)['contrast'], 1.26)
        for activity in ('preview', 'draw', 'load'):
            with self.subTest(activity=activity), patch('ProfileIsolation.update_visibility'):
                DrawBot.DrawBotApp.set_busy(app, activity)
                self.assertEqual(widget.cget('state'), 'disabled')
                for symbol in ('Right', 'Home', 'End', 'BackSpace'): self.press(widget, symbol)
                for delta, num in ((120, None), (-120, None), (0, 4), (0, 5)):
                    self.assertIsNone(widget._mouse_scroll_event(event(delta=delta, num=num)))
                widget._canvas.deliver('<Button-1>', event(x=240))
                self.assertAlmostEqual(app.contrast.get(), 1.26)
                self.assertEqual(app.preview_generation, 1)
        for name in ('draw', 'quick_start', 'begin_worker'): getattr(app, name).assert_not_called()

    def test_wheel_ownership_routes_unfocused_or_disabled_row_to_real_panel_dispatcher(self):
        parent, canvas = panel('1')
        widget = self.slider()
        widget.master = parent
        leaf = SimpleNamespace(winfo_class=lambda: 'Canvas', master=widget)
        harness = ScrollHarness(leaf)
        for state in ('unfocused', 'disabled'):
            widget.focus_get.return_value = None if state == 'unfocused' else widget
            widget.configure(state='disabled' if state == 'disabled' else 'normal')
            self.assertIsNone(widget._mouse_scroll_event(event(delta=-120)))
            self.assertEqual(harness.wheel(), 'break')
            harness.flush()
            self.assertEqual(widget.get(), 1.25)
        self.assertEqual(canvas.yview_scroll.call_count, 2)
        canvas.yview_scroll.assert_called_with(20, 'units')
        widget.configure(state='normal')
        for delta, num, state, expected in ((120, None, 0, 1.26), (0, 5, 1, 1.16),
                                          (0, 4, 0, 1.17), (-120, None, 0, 1.16)):
            self.assertEqual(widget._mouse_scroll_event(event(state=state, delta=delta, num=num)), 'break')
            self.assertAlmostEqual(widget.get(), expected)
            self.assertIsNone(harness.wheel())
            self.assertFalse(harness.jobs)
        self.assertEqual(canvas.yview_scroll.call_count, 2)

    def test_browser_one_click_worker_keeps_contrast_and_its_request_unchanged(self):
        app = controller_app(self.interpreter, Scheduler())
        app.game.set('Gartic Phone')
        app.contrast = tk.DoubleVar(self.interpreter, value=1.25)
        app.stop = threading.Event()
        app.events = queue.Queue()
        app.worker = None
        app._safe_widget_configure = DrawBot.DrawBotApp._safe_widget_configure
        app.set_busy = MethodType(DrawBot.DrawBotApp.set_busy, app)
        widget, label = actual_contrast_row(app, object())
        task = Mock()
        with patch('DrawBot.log_event'), patch('ScreenTaskWindow.ScreenTaskWindow'), \
                patch('DrawBot.threading.Thread', DeferredThread), \
                patch('ProfileIsolation.update_visibility'):
            request = DrawBot.DrawBotApp._new_browser_one_click_request(app, force=True)
            request['phase'] = 'setup'
            app.browser_one_click_worker_request = request
            self.assertTrue(DrawBot.DrawBotApp.begin_worker(app, 'browser-one-click-setup', task))
        self.assertEqual(app.activity, 'browser-one-click-setup')
        self.assertEqual(widget.cget('state'), 'disabled')
        for delta, num in ((120, None), (-120, None), (0, 4), (0, 5)):
            self.assertIsNone(widget._mouse_scroll_event(event(delta=delta, num=num)))
        self.press(widget, 'End')
        widget._canvas.deliver('<Button-1>', event(x=240))
        self.assertEqual(app.contrast.get(), 1.25)
        self.assertEqual(label.cget('text'), 'Contrast · 1.25×')
        self.assertIsNotNone(app.plan)
        self.assertEqual(app.preview_generation, 0)
        self.assertIs(app.browser_one_click_request, request)
        self.assertFalse(request['cancelled'].is_set())
        self.assertTrue(DrawBot.DrawBotApp._browser_one_click_request_current(app, request))
        task.assert_not_called()

    def test_live_visibility_and_shortcuts_never_mutate_inactive_slider(self):
        for change in ('disabled', 'closed', 'unmapped', 'destroyed', 'unfocused', 'clipped'):
            with self.subTest(change=change):
                widget = self.slider()
                if change == 'disabled': widget.configure(state='disabled')
                elif change == 'closed': widget.destroy()
                elif change == 'unmapped': widget.winfo_ismapped.return_value = False
                elif change == 'destroyed': widget.winfo_exists.return_value = False
                elif change == 'unfocused': widget.focus_get.return_value = None
                else: widget._keyboard_in_view = lambda: False
                for symbol in ('Right', 'Prior', 'Home', 'End', 'BackSpace'):
                    self.press(widget, symbol)
                self.assertIsNone(widget._mouse_scroll_event(event(delta=120)))
                self.assertEqual(widget.get(), 1.25)
                widget.cget('command').assert_not_called()
        widget = self.slider()
        for symbol in ('Tab', 'ISO_Left_Tab', 'Escape', 'F1', 'F6', 'Return'):
            self.assertIsNone(self.press(widget, symbol))
        for modifier in (4, 8, 128, 0x20000):
            for symbol in ('Right', 'Home', 'BackSpace'):
                self.assertIsNone(self.press(widget, symbol, modifier))
            self.assertIsNone(widget._mouse_scroll_event(event(state=modifier, delta=120)))
        self.assertIsNone(widget._mouse_scroll_event(event()))
        widget.cget('command').assert_not_called()
        self.global_bind.assert_not_called()

    def test_pointer_focus_native_drag_and_programmatic_updates_keep_readout_synchronized(self):
        app = SimpleNamespace(controls=[], contrast=tk.DoubleVar(self.interpreter, value=1.25),
                              options_changed=Mock())
        widget, label = actual_contrast_row(app, object())
        widget.focus_get.return_value = None
        widget._canvas.deliver('<Button-1>', event(x=80))
        self.assertIs(widget.focus_get(), widget)
        self.assertEqual(app.contrast.get(), 1)
        self.assertEqual(label.cget('text'), 'Contrast · 1.00×')
        self.press(widget, 'Right')
        self.assertAlmostEqual(app.contrast.get(), 1.01)
        widget._canvas.deliver('<B1-Motion>', event(x=240))
        self.assertEqual(app.contrast.get(), 2)
        self.assertEqual(app.options_changed.call_count, 3)
        widget.set(.75)
        self.assertEqual(label.cget('text'), 'Contrast · 0.75×')
        app.contrast.set(1.55)
        self.assertEqual(widget.get(), 1.55)
        self.assertEqual(label.cget('text'), 'Contrast · 1.55×')
        self.assertEqual(app.options_changed.call_count, 3)
        original = label.configure
        label.configure = Mock(wraps=original)
        widget._draw(); widget._draw()
        label.configure.assert_not_called()

    def test_lifetime_retains_only_native_trace_and_tooltip_tracks_logical_focus(self):
        widget = self.slider(value_changed=Mock())
        variable = widget.cget('variable')
        self.assertEqual(len(variable.trace_info()), 1)
        self.assertEqual(widget._canvas.cget('takefocus'), 0)
        self.assertTrue(widget.native_options['takefocus']())
        StudioUI.tooltip(widget, 'Precise contrast.')
        tip = widget._image_draw_bot_tooltip
        widget.logical_surface.deliver('<FocusIn>')
        self.assertEqual(widget.scheduler.delays, [450])
        self.assertTrue(widget._keyboard_focus_displayed)
        window = Mock(); tip.window = window
        widget.logical_surface.deliver('<FocusOut>')
        self.assertFalse(widget.scheduler.pending)
        window.destroy.assert_called_once_with()
        replacement = tk.DoubleVar(self.interpreter, value=.9)
        widget.configure(variable=replacement)
        self.assertFalse(variable.trace_info())
        self.assertEqual(len(replacement.trace_info()), 1)
        variable.set(1.8)
        self.assertEqual(widget.get(), .9)
        widget.destroy()
        self.assertFalse(replacement.trace_info())
        self.assertIsNone(widget._keyboard_value_callback)
        self.press(widget, 'End')
        self.assertEqual(replacement.get(), .9)
        widget.cget('command').assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'Native CTk contrast interaction runs on Windows CI.')
class NativeContrastKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.root = ctk.CTk()
        self.root.geometry('680x460+50+50')
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)

    def tearDown(self):
        self.root.destroy()
        self.assertFalse(self.errors, self.errors)

    def test_factory_tab_pointer_focus_value_readout_busy_state_and_teardown(self):
        entry = ttk.Entry(self.root); entry.pack()
        app = SimpleNamespace(controls=[], contrast=tk.DoubleVar(self.root, value=1.25),
                              options_changed=Mock())
        widget, label = actual_contrast_row(app, self.root)
        disabled = KeyboardSlider(self.root, state='disabled'); disabled.pack()
        after = ttk.Entry(self.root); after.pack()
        self.root.update()
        self.assertIs(entry.tk_focusNext(), widget)
        self.assertIs(widget.tk_focusNext(), after)
        self.assertIs(after.tk_focusPrev(), widget)
        self.assertEqual(int(widget._canvas.cget('takefocus')), 0)
        globals_before = self.root.bind_all('<KeyPress>')
        entry.focus_force(); self.root.update()
        entry.event_generate('<Tab>', when='now'); self.root.update()
        self.assertIs(self.root.focus_get(), widget)
        self.assertEqual(len(widget._canvas.find_withtag(widget._focus_tag)), 1)
        widget.event_generate('<KeyPress-End>', when='now'); self.root.update()
        self.assertEqual(app.contrast.get(), 2)
        self.assertEqual(label.cget('text'), 'Contrast · 2.00×')
        after.focus_force(); self.root.update()
        widget._canvas.event_generate('<MouseWheel>', delta=-120, when='now'); self.root.update()
        self.assertEqual(app.contrast.get(), 2)
        widget._canvas.event_generate('<Button-1>', x=0, y=8, when='now'); self.root.update()
        self.assertIs(self.root.focus_get(), widget)
        self.assertEqual(app.contrast.get(), .5)
        widget.event_generate('<KeyPress-Right>', when='now'); self.root.update()
        self.assertAlmostEqual(app.contrast.get(), .51)
        widget.focus_set(); self.root.update()
        self.assertIs(self.root.focus_get(), widget)
        widget.focus_force(); self.root.update()
        self.assertIs(self.root.focus_get(), widget)
        widget.configure(state='disabled')
        widget._canvas.event_generate('<MouseWheel>', delta=120, when='now')
        widget.event_generate('<KeyPress-End>', when='now'); self.root.update()
        self.assertAlmostEqual(app.contrast.get(), .51)
        self.assertEqual(app.options_changed.call_count, 3)
        tokens = tuple(widget._tclCommands or ())
        widget.destroy(); self.root.update()
        self.assertFalse(app.contrast.trace_info())
        for token in tokens: self.assertFalse(self.root.tk.call('info', 'commands', token))
        self.assertEqual(self.root.bind_all('<KeyPress>'), globals_before)

    def test_tab_reveals_offscreen_slider_before_key_adjustment(self):
        panel = ctk.CTkScrollableFrame(self.root, width=440, height=130); panel.pack()
        before = ttk.Entry(panel); before.pack()
        ctk.CTkFrame(panel, width=10, height=900).pack()
        value = tk.DoubleVar(self.root, value=1)
        widget = KeyboardSlider(panel, from_=.5, to=2, variable=value); widget.pack()
        self.root.update()
        self.assertFalse(widget._keyboard_in_view())
        before.focus_force(); self.root.update()
        before.event_generate('<Tab>', when='now'); self.root.update()
        self.assertIs(self.root.focus_get(), widget)
        self.assertTrue(widget._keyboard_in_view())
        widget.event_generate('<KeyPress-Right>', when='now'); self.root.update()
        self.assertAlmostEqual(value.get(), 1.01)


if __name__ == '__main__':
    unittest.main()
