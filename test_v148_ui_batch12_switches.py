"""The actual boolean settings use local keys through CTk's real toggle path."""
import ast
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import time
from types import MethodType, SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk
from customtkinter.windows.widgets.core_widget_classes import CTkBaseClass

import DrawBot
import StudioUI
from UiKeyboardNavigation import KeyboardSwitch
import test_v148_ui_batch07_keyboard as button_fixtures
import test_v148_ui_batch10_numeric as numeric_fixtures


SWITCH_VARIABLES = (
    'paint_simple', 'browser_one_click_enabled', 'auto_clear_canvas', 'outline',
    'read_gartic_timer', 'adaptive_deadline_renderer', 'use_region_fill_engine',
    'skip_white', 'portrait_focus', 'preview_show_background', 'preview_show_fill',
    'preview_show_strokes',
)


def event(symbol='space', state=0, widget=None):
    return SimpleNamespace(keysym=symbol, state=state, widget=widget)


class Scheduler(button_fixtures.Scheduler):
    def __init__(self):
        super().__init__()
        self.delays = []

    def after(self, delay, callback):
        self.delays.append(delay)
        return self.after_idle(callback)


class Surface:
    """Only the native drawing/binding surface, not the control behavior."""
    def __init__(self):
        self.bindings = {}
        self.options = {}
        self.delete = Mock()
        self.create_rectangle = Mock()
        self.tag_raise = Mock()

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def bind(self, sequence, callback, add=None):
        if add not in ('+', True):
            self.bindings[sequence] = []
        self.bindings.setdefault(sequence, []).append(callback)

    def deliver(self, sequence, value=None):
        for callback in tuple(self.bindings.get(sequence, ())):
            if callback(value or event(widget=self)) == 'break':
                break

    def winfo_width(self): return 36
    def winfo_height(self): return 24


def switch_app(interpreter):
    app = SimpleNamespace(controls=[])
    for name in SWITCH_VARIABLES:
        setattr(app, name, tk.BooleanVar(interpreter, value=False))
    for name in ('options_changed', 'paint_mode_changed', 'canvas_clear_changed',
                 'sketch_mode_changed', 'schedule_previews'):
        setattr(app, name, Mock())
    return app


def actual_switch_rows(app, parent, constructor=KeyboardSwitch, *, scopes):
    """Execute the live twelve constructors and loops, with their real callbacks."""
    tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf8'))
    build = next(node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == 'build_ui')
    nodes = [node for node in build.body
             if isinstance(node, ast.FunctionDef) and node.name == 'control']
    for node in build.body:
        if isinstance(node, (ast.Assign, ast.Expr, ast.For)) and any(
                isinstance(part, ast.Call) and (
                    isinstance(part.func, ast.Name) and part.func.id == 'KeyboardSwitch'
                    or isinstance(part.func, ast.Attribute) and part.func.attr == 'CTkSwitch')
                for part in ast.walk(node)):
            nodes.append(node)
    created = []

    def create(*args, **kwargs):
        widget = constructor(*args, **kwargs)
        created.append(widget)
        return widget

    scope = dict(vars(StudioUI), a=app, KeyboardSwitch=create, _fixture_controls=created)
    scope.update({name: parent for name in
                  ('step1', 'step2', 'step4', 'precision_card', 'smart_card', 'preview_options')})
    scopes.append(scope)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), StudioUI.__file__, 'exec'), scope)
    return created


class SwitchKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.interpreter = tk.Tcl()
        self.widgets = []
        self.factory_scopes = []
        self.addCleanup(self.close_widgets)
        self.stack.enter_context(patch.object(ctk.CTkSwitch, '__init__',
            lambda widget, *args, **kwargs: self.native_init(widget, *args, **kwargs)))
        self.stack.enter_context(patch.object(ctk.CTkSwitch, '_draw'))
        self.stack.enter_context(patch.object(ctk.CTkSwitch, '_set_cursor'))
        self.stack.enter_context(patch.object(CTkBaseClass, 'configure', self.native_configure))
        self.stack.enter_context(patch.object(CTkBaseClass, 'destroy', self.native_destroy))
        self.stack.enter_context(patch.object(tk.Frame, 'configure', self.frame_configure))
        self.stack.enter_context(patch.object(tk.Misc, 'bind', self.logical_bind))
        self.stack.enter_context(patch.object(tk.Misc, 'focus_set', self.logical_focus))

    def native_init(self, widget, master=None, **kwargs):
        widget.master = master
        widget._state = kwargs.get('state', 'normal')
        widget._text = kwargs.get('text', '')
        widget._onvalue, widget._offvalue = kwargs.get('onvalue', 1), kwargs.get('offvalue', 0)
        widget._variable = kwargs.get('variable')
        widget._variable_callback_blocked = False
        widget._command = kwargs.get('command')
        widget._font = None
        widget._canvas, widget._text_label, widget._bg_canvas = Surface(), Surface(), Surface()
        widget._check_state = bool(widget._variable is not None and
                                   widget._variable.get() == widget._onvalue)
        widget._variable_callback_name = (widget._variable.trace_add('write', widget._variable_callback)
                                         if widget._variable is not None else None)
        widget.winfo_exists = Mock(return_value=True)
        widget.winfo_ismapped = Mock(return_value=True)
        widget.focus_get = Mock(return_value=widget)
        widget._get_widget_scaling = lambda: 1
        widget.pack = Mock()
        widget.native_options = {}
        widget.logical_surface = Surface()
        widget.scheduler = Scheduler()
        widget.after_idle = widget.scheduler.after_idle
        widget.after_cancel = widget.scheduler.after_cancel
        widget.after = widget.scheduler.after
        widget._create_bindings()
        self.widgets.append(widget)

    @staticmethod
    def native_configure(widget, require_redraw=False, **kwargs):
        widget.native_options.update(kwargs)
        if require_redraw:
            widget._draw()

    @staticmethod
    def frame_configure(widget, **kwargs):
        widget.native_options.update(kwargs)

    @staticmethod
    def native_destroy(widget):
        widget.winfo_exists.return_value = False

    @staticmethod
    def logical_bind(widget, sequence, callback, add=None):
        widget.logical_surface.bind(sequence, callback, add=add)

    @staticmethod
    def logical_focus(widget):
        widget.focus_get.return_value = widget

    def close_widgets(self):
        for widget in self.widgets:
            if not widget._keyboard_closed:
                widget.destroy()
        for widget in self.widgets:
            numeric_fixtures.release_control_references(widget)
        numeric_fixtures.release_factory_scopes(self.factory_scopes)
        self.widgets.clear()
        self.interpreter = None

    def switch(self, **kwargs):
        kwargs.setdefault('variable', tk.BooleanVar(self.interpreter, value=False))
        kwargs.setdefault('command', Mock())
        return KeyboardSwitch(None, **kwargs)

    @staticmethod
    def deliver(widget, sequence, symbol='space', state=0):
        widget.logical_surface.deliver(sequence, event(symbol, state, widget))

    def press(self, widget, symbol='space'):
        self.deliver(widget, '<KeyPress-' + symbol + '>', symbol)
        self.deliver(widget, '<KeyRelease-' + symbol + '>', symbol)
        widget.scheduler.flush()

    def test_actual_factory_reaches_all_twelve_variables_and_preserves_callback_kinds(self):
        app = switch_app(self.interpreter)
        widgets = actual_switch_rows(app, object(), scopes=self.factory_scopes)
        self.assertEqual(len(widgets), 12)
        self.assertEqual([widget.cget('variable') for widget in widgets],
                         [getattr(app, name) for name in SWITCH_VARIABLES])
        self.assertTrue(all(isinstance(widget, KeyboardSwitch) for widget in widgets))
        self.assertEqual(app.controls, [(widget, 'normal') for widget in widgets[:9]])
        for widget in widgets:
            self.press(widget)
            self.assertTrue(widget.cget('variable').get())
        app.paint_mode_changed.assert_called_once_with()
        app.canvas_clear_changed.assert_called_once_with()
        app.sketch_mode_changed.assert_called_once_with()
        self.assertEqual(app.options_changed.call_count, 6)
        self.assertEqual([call.kwargs for call in app.schedule_previews.call_args_list],
                         [{'delay': 15}] * 3)

    def test_real_toggle_preserves_exact_values_and_variable_before_command_order(self):
        for symbol in ('space', 'Return', 'KP_Enter'):
            for values in ((False, True), ('leave unchanged', 'use selected ink')):
                with self.subTest(symbol=symbol, values=values):
                    off, on = values
                    variable = (tk.BooleanVar(self.interpreter, value=off) if isinstance(off, bool)
                                else tk.StringVar(self.interpreter, value=off))
                    observed = []
                    widget = self.switch(variable=variable, onvalue=on, offvalue=off,
                                         command=lambda: observed.append(('command', variable.get())))
                    trace = variable.trace_add('write', lambda *_: observed.append(('variable', variable.get())))
                    try:
                        self.deliver(widget, '<KeyPress-' + symbol + '>', symbol)
                        self.assertEqual(variable.get(), off)
                        self.deliver(widget, '<KeyRelease-' + symbol + '>', symbol)
                        widget.scheduler.flush()
                        self.assertEqual(observed, [('variable', on), ('command', on)])
                        self.assertEqual(widget.get(), on)
                        self.press(widget, symbol)
                        self.assertEqual(observed[-2:], [('variable', off), ('command', off)])
                    finally:
                        variable.trace_remove('write', trace)

    def test_programmatic_variable_and_reconfiguration_do_not_issue_user_commands(self):
        variable = tk.StringVar(self.interpreter, value='off')
        widget = self.switch(variable=variable, onvalue='on', offvalue='off')
        command = widget.cget('command')
        variable.set('on')
        self.assertEqual(widget.get(), 'on')
        widget.deselect()
        self.assertEqual(variable.get(), 'off')
        widget.select()
        self.assertEqual(variable.get(), 'on')
        replacement = tk.StringVar(self.interpreter, value='no')
        widget.configure(variable=replacement, onvalue='yes', offvalue='no')
        variable.set('off')
        self.assertEqual(widget.get(), 'no')
        command.assert_not_called()
        self.press(widget)
        self.assertEqual(replacement.get(), 'yes')
        self.assertEqual(variable.get(), 'off')
        command.assert_called_once_with()
        widget.configure(command=None)
        self.press(widget)
        self.assertEqual(replacement.get(), 'no')
        command.assert_called_once_with()

    def test_repeated_presses_and_release_press_pairs_toggle_once(self):
        widget = self.switch()
        for _ in range(20):
            self.deliver(widget, '<KeyPress-space>')
        self.deliver(widget, '<KeyRelease-space>')
        self.deliver(widget, '<KeyPress-space>')
        widget.scheduler.flush()
        self.assertFalse(widget.get())
        self.deliver(widget, '<KeyRelease-space>')
        widget.scheduler.flush()
        self.assertTrue(widget.get())
        self.deliver(widget, '<KeyRelease-space>')
        widget.scheduler.flush()
        widget.cget('command').assert_called_once_with()

    def test_focus_and_modified_shortcuts_are_not_toggles(self):
        widget = self.switch()
        self.deliver(widget, '<FocusIn>')
        self.deliver(widget, '<FocusOut>')
        for symbol, state in (('space', 4), ('Return', 8), ('space', 128), ('Return', 0x20000)):
            self.deliver(widget, '<KeyPress-' + symbol + '>', symbol, state)
            self.deliver(widget, '<KeyRelease-' + symbol + '>', symbol, state)
        widget.scheduler.flush()
        self.assertFalse(widget.get())
        widget.cget('command').assert_not_called()

    def test_disabled_hidden_destroyed_unfocused_and_clipped_release_cannot_toggle(self):
        for changed in ('disabled', 'hidden', 'destroyed', 'unfocused', 'clipped', 'closed'):
            with self.subTest(changed=changed):
                widget = self.switch()
                self.deliver(widget, '<KeyPress-space>')
                self.deliver(widget, '<KeyRelease-space>')
                if changed == 'disabled': widget.configure(state='disabled')
                elif changed == 'hidden': widget.winfo_ismapped.return_value = False
                elif changed == 'destroyed': widget.winfo_exists.return_value = False
                elif changed == 'unfocused': widget.focus_get.return_value = None
                elif changed == 'clipped': widget._keyboard_in_view = lambda: False
                else: widget.destroy()
                widget.scheduler.flush()
                self.assertFalse(widget.get())
                widget.cget('command').assert_not_called()

    def test_focus_loss_and_unmap_cancel_even_if_the_control_returns_before_idle(self):
        for signal in ('<FocusOut>', '<Unmap>'):
            with self.subTest(signal=signal):
                widget = self.switch()
                self.deliver(widget, '<KeyPress-space>')
                self.deliver(widget, '<KeyRelease-space>')
                self.deliver(widget, signal)
                self.deliver(widget, '<FocusIn>')
                self.assertFalse(widget.scheduler.pending)
                self.assertFalse(widget.get())

    def test_pointer_toggle_cancels_release_before_a_reentrant_callback(self):
        widget = self.switch()
        observed = []
        widget.configure(command=lambda: (observed.append(widget.get()), widget.scheduler.flush()))
        self.deliver(widget, '<KeyPress-space>')
        self.deliver(widget, '<KeyRelease-space>')
        widget._canvas.deliver('<Button-1>')
        self.assertEqual(observed, [1])
        self.assertTrue(widget.get())
        self.assertFalse(widget.scheduler.pending)

    def test_destroy_cancels_pending_callback_and_removes_the_real_variable_trace(self):
        widget = self.switch()
        variable = widget.cget('variable')
        self.assertEqual(len(variable.trace_info()), 1)
        self.deliver(widget, '<KeyPress-space>')
        self.deliver(widget, '<KeyRelease-space>')
        widget.destroy()
        self.assertFalse(variable.trace_info())
        self.assertFalse(widget.scheduler.pending)
        widget._keyboard_activate()  # An already captured late callback is inert.
        self.assertFalse(variable.get())
        widget.cget('command').assert_not_called()

    def test_actual_tooltip_observes_logical_focus_and_cancels_on_blur(self):
        widget = self.switch()
        StudioUI.tooltip(widget, 'Toggle this existing option.')
        tip = widget._image_draw_bot_tooltip
        self.deliver(widget, '<FocusIn>')
        self.assertEqual(widget.scheduler.delays, [450])
        window = Mock()
        tip.window = window
        self.deliver(widget, '<FocusOut>')
        self.assertFalse(widget.scheduler.pending)
        window.destroy.assert_called_once_with()
        self.assertIsNone(tip.window)
        self.assertEqual(set(widget._canvas.bindings),
                         {'<Enter>', '<Leave>', '<Button-1>', '<ButtonPress>', '<Destroy>'})

    def test_focus_reveals_nested_viewports_and_failed_reveal_cannot_toggle(self):
        widget = self.switch()
        outer = button_fixtures.ScrollCanvas()
        inner = button_fixtures.ScrollCanvas(rooty=lambda: outer.winfo_rooty() + 800 - outer.top,
                                              height=150)
        widget.master = button_fixtures.scroll_frame(
            inner, master=button_fixtures.scroll_frame(outer))
        widget.winfo_rootx = lambda: 120
        widget.winfo_rooty = lambda: inner.winfo_rooty() + 900 - inner.top
        widget.winfo_width = lambda: 100
        widget.winfo_height = lambda: 24
        self.assertFalse(widget._keyboard_in_view())
        self.deliver(widget, '<FocusIn>')
        self.assertEqual(len(inner.scrolls), 1)
        self.assertEqual(len(outer.scrolls), 1)
        self.assertTrue(widget._keyboard_in_view())
        self.press(widget)
        self.assertTrue(widget.get())
        inner.top = outer.top = 0
        self.press(widget)
        self.assertTrue(widget.get())
        inner.yview_moveto = Mock(side_effect=tk.TclError('viewport gone'))
        self.deliver(widget, '<FocusIn>')
        self.press(widget)
        widget.cget('command').assert_called_once_with()

    def controller(self):
        root = Scheduler()
        app = numeric_fixtures.controller_app(self.interpreter, root)
        for name in SWITCH_VARIABLES:
            setattr(app, name, tk.BooleanVar(self.interpreter, value=False))
        for name in ('schedule_previews', '_run_scheduled_previews', 'set_busy'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        app._safe_widget_configure = DrawBot.DrawBotApp._safe_widget_configure
        app.show_previews = Mock()
        for name in ('paint_mode_changed', 'canvas_clear_changed', 'sketch_mode_changed',
                     'draw', 'quick_start', 'begin_worker'):
            setattr(app, name, Mock())
        app.preview_render_after = None
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_start_buttons_text'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_target_lock_text'))
        return app, actual_switch_rows(app, object(), scopes=self.factory_scopes)

    def test_actual_factory_options_callback_invalidates_once_without_requesting_input(self):
        app, widgets = self.controller()
        skip_white = widgets[7]
        self.deliver(skip_white, '<FocusIn>')
        self.assertIsNotNone(app.plan)
        self.assertEqual(app.preview_generation, 0)
        self.press(skip_white)
        self.assertTrue(app.skip_white.get())
        self.assertIsNone(app.plan)
        self.assertEqual(app.preview_generation, 1)
        self.assertFalse(app.small_test_passed)
        with tempfile.TemporaryDirectory() as directory, \
                patch('RuntimePaths.source_dir', return_value=Path(directory)), \
                patch('DrawBot.custom_rgb_available', return_value=False):
            self.assertTrue(DrawBot.DrawBotApp.options(app)['skip_white'])
        for name in ('draw', 'quick_start', 'begin_worker'):
            getattr(app, name).assert_not_called()

    def test_actual_busy_controller_disables_settings_but_preserves_preview_only_toggles(self):
        app, widgets = self.controller()
        skip_white, preview = widgets[7], widgets[9]
        self.deliver(skip_white, '<KeyPress-space>')
        self.deliver(skip_white, '<KeyRelease-space>')
        with patch('ProfileIsolation.update_visibility'):
            app.set_busy('preview')
        self.assertTrue(all(widget.cget('state') == 'disabled' for widget in widgets[:9]))
        self.assertTrue(all(widget.cget('state') == 'normal' for widget in widgets[9:]))
        skip_white.configure(state='normal')
        skip_white.scheduler.flush()
        self.assertFalse(app.skip_white.get())
        plan = app.plan
        self.press(preview)
        self.assertTrue(app.preview_show_background.get())
        self.assertIs(app.plan, plan)
        self.assertEqual(app.preview_generation, 0)
        self.assertEqual(app.root.delays, [15])
        app.root.flush()
        app.show_previews.assert_called_once_with()
        for name in ('draw', 'quick_start', 'begin_worker'):
            getattr(app, name).assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows Tk switch key delivery')
class WindowsSwitchKeyboardTests(unittest.TestCase):
    def setUp(self):
        from UiCompatibility import scoped_window_class
        self.root = scoped_window_class(ctk.CTk)()
        self.factory_scopes = []
        self.root.geometry('760x680+50+50')
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)

    def tearDown(self):
        self.root.destroy()
        numeric_fixtures.release_factory_scopes(self.factory_scopes)
        self.assertFalse(self.errors, self.errors)

    def settle(self, predicate):
        deadline = time.monotonic() + 4
        while True:
            self.root.update()
            if predicate(): return
            if time.monotonic() >= deadline:
                self.fail('Native switch mapping/focus did not settle')
            time.sleep(.01)

    def press(self, widget, symbol='space', repeats=1):
        for _ in range(repeats):
            widget.event_generate('<KeyPress-' + symbol + '>', when='now')
        widget.event_generate('<KeyRelease-' + symbol + '>', when='now')
        self.root.update()

    def test_native_factory_tab_values_callbacks_focus_tooltip_and_teardown(self):
        sequences = ('<KeyPress>', '<Return>', '<space>', '<Tab>')
        before = {name: self.root.bind_all(name) for name in sequences}
        entry = ttk.Entry(self.root)
        entry.pack()
        app = switch_app(self.root)
        observed = []
        app.paint_mode_changed = lambda: observed.append(app.paint_simple.get())
        widgets = actual_switch_rows(app, self.root, scopes=self.factory_scopes)
        for widget in widgets:
            widget.pack_forget()
        for widget in widgets:
            widget.pack(anchor='w', pady=3)
        first, disabled, third = widgets[:3]
        disabled.configure(state='disabled')
        StudioUI.tooltip(first, 'Toggle current-ink sketch mode.')
        tip = first._image_draw_bot_tooltip
        tip.delay = 0
        self.settle(lambda: all(widget.winfo_ismapped() for widget in widgets))
        self.assertIs(entry.tk_focusNext(), first)
        self.assertIs(first.tk_focusNext(), third)
        self.assertIs(third.tk_focusPrev(), first)
        for child in (first._bg_canvas, first._canvas, first._text_label):
            self.assertEqual(int(child.cget('takefocus')), 0)
        entry.focus_force()
        self.root.update()
        entry.event_generate('<Tab>', when='now')
        self.settle(lambda: self.root.focus_get() is first and tip.window is not None)
        self.assertEqual(len(first._canvas.find_withtag(first._focus_tag)), 1)
        self.assertFalse(app.paint_simple.get())
        self.press(first, repeats=20)
        self.assertEqual(observed, [True])
        self.press(first, 'Return')
        self.assertEqual(observed, [True, False])
        app.paint_simple.set(True)
        self.root.update()
        self.assertTrue(first.get())
        self.assertEqual(observed, [True, False])
        third.focus_force()
        self.settle(lambda: tip.window is None)
        first.focus_force()
        self.root.update()
        first.event_generate('<KeyPress-space>', when='now')
        first.event_generate('<KeyRelease-space>', when='now')
        first.configure(state='disabled')
        first.configure(state='normal')
        self.root.update()
        self.assertEqual(observed, [True, False])
        tokens = tuple(first._tclCommands or ())
        first.destroy()
        self.root.update()
        self.assertFalse(app.paint_simple.trace_info())
        for token in tokens:
            self.assertFalse(self.root.tk.call('info', 'commands', token))
        self.assertEqual({name: self.root.bind_all(name) for name in sequences}, before)

    def test_native_tab_reveals_switch_and_scrolled_out_or_destroyed_release_is_inert(self):
        panel = ctk.CTkScrollableFrame(self.root, width=500, height=130)
        panel.pack()
        first = StudioUI.button(panel, 'Before the switches', lambda: None)
        first.pack()
        ctk.CTkFrame(panel, width=10, height=900).pack()
        variable = tk.StringVar(self.root, value='unchanged')
        observed = []
        last = KeyboardSwitch(panel, text='A switch below the viewport', variable=variable,
                              onvalue='selected', offvalue='unchanged',
                              command=lambda: observed.append(variable.get()))
        last.pack()
        self.settle(lambda: last.winfo_ismapped())
        self.assertFalse(last._keyboard_in_view())
        first.focus_force()
        self.root.update()
        first.event_generate('<Tab>', when='now')
        self.settle(lambda: self.root.focus_get() is last and last._keyboard_in_view())
        self.press(last)
        self.assertEqual(variable.get(), 'selected')
        self.assertEqual(observed, ['selected'])
        panel._parent_canvas.yview_moveto(0)
        self.root.update()
        self.assertFalse(last._keyboard_in_view())
        self.press(last)
        self.assertEqual(observed, ['selected'])
        last.event_generate('<KeyPress-space>', when='now')
        last.event_generate('<KeyRelease-space>', when='now')
        last.destroy()
        self.root.update()
        self.assertEqual(variable.get(), 'selected')
        self.assertEqual(observed, ['selected'])
        self.assertFalse(variable.trace_info())


if __name__ == '__main__':
    unittest.main()
