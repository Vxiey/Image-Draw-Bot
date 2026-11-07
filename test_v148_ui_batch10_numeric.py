"""Real numeric-row commits preserve plans until their displayed value changes."""
import ast
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk

import DrawBot
import StudioUI
from SettingsValidation import settings_application
import test_v148_ui_batch07_renderer as renderer_fixtures


class NativeWidget:
    def __init__(self, *_args, **kwargs):
        self.bindings = {}
        self.alive = True
        self.kwargs = kwargs

    def pack(self, **_kwargs):
        pass

    def bind(self, event, callback, add=None):
        if add != '+':
            self.bindings[event] = []
        self.bindings.setdefault(event, []).append(callback)

    def deliver(self, event):
        for callback in tuple(self.bindings.get(event, ())):
            callback(SimpleNamespace(widget=self))

    def winfo_exists(self):
        return self.alive

    def destroy(self):
        self.alive = False
        self.deliver('<Destroy>')


def release_control_references(widget):
    """Retire only fixture-held references, after the real destroy assertions."""
    handler = getattr(widget, '_numeric_entry_commit', None)
    if handler is not None:
        if handler.alive:
            raise AssertionError('Destroy the real numeric binding before releasing its fixture')
        handler.field = handler.variable = handler.callback = handler.owner = None
        widget._numeric_entry_commit = None
    if hasattr(widget, '_keyboard_closed') and not widget._keyboard_closed:
        raise AssertionError('Destroy the real keyboard control before releasing its fixture')
    for name in ('_variable', '_textvariable', '_command'):
        if name in vars(widget):
            setattr(widget, name, None)


def release_factory_scopes(scopes):
    """Callbacks need their exec globals until every owned control is destroyed."""
    for scope in scopes:
        app = scope.get('a')
        controls = list(scope.get('_fixture_controls', ()))
        if app is not None:
            controls.extend(widget for widget, _state in getattr(app, 'controls', ()))
        for widget in controls:
            release_control_references(widget)
        if app is not None:
            # controller_app's real-method adapters close over this same app.
            vars(app).clear()
        scope.clear()
    scopes.clear()


def actual_numeric_row(app, parent, variable, *, scopes):
    """Compile the live factory chain, replacing only widgets in portable tests."""
    tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf8'))
    build = next(node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == 'build_ui')
    factories = {'frame', 'label', 'control', 'entry', 'numeric_row'}
    nodes = [node for node in build.body
             if isinstance(node, ast.FunctionDef) and node.name in factories]
    scope = dict(vars(StudioUI), a=app, root=app.root)
    scopes.append(scope)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), StudioUI.__file__, 'exec'), scope)
    return scope['numeric_row'](parent, 'Brush width', variable)


def controller_app(interpreter, root):
    app = renderer_fixtures.AdvertisedRendererTests().app()
    app.brush_px = tk.StringVar(interpreter, value='3')
    app.controls = []
    app.root = root
    app.activity = None
    app.closing = False
    app.profile_change_in_progress = False
    app.original = object()
    app.plan = {'count': 5}
    app.small_test_passed = True
    app.preview_generation = 0
    app.summary = Mock()
    app.status = Mock()
    for name in ('options_changed', '_mark_plan_stale', '_maybe_auto_preview', '_auto_preview_enabled'):
        method = getattr(DrawBot.DrawBotApp, name)
        setattr(app, name, lambda *args, _method=method, **kwargs: _method(app, *args, **kwargs))
    return app


class NumericCommitTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.interpreter = tk.Tcl()
        self.app = controller_app(self.interpreter, Mock())
        self.widgets = []
        self.factory_scopes = []
        self.addCleanup(self.close_widgets)

        def create(*args, **kwargs):
            widget = NativeWidget(*args, **kwargs)
            self.widgets.append(widget)
            return widget

        for name in ('CTkFrame', 'CTkLabel', 'CTkEntry'):
            self.stack.enter_context(patch.object(ctk, name, new=create))
        self.stack.enter_context(patch.object(StudioUI, 'KeyboardButton', new=create))
        self.stack.enter_context(patch.object(StudioUI, 'tooltip'))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_start_buttons_text'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_target_lock_text'))
        self.field = actual_numeric_row(self.app, object(), self.app.brush_px,
                                       scopes=self.factory_scopes)

    def close_widgets(self):
        for widget in reversed(self.widgets):
            if widget.alive:
                widget.destroy()
        for widget in self.widgets:
            release_control_references(widget)
            widget.kwargs.clear()
            widget.bindings.clear()
        release_factory_scopes(self.factory_scopes)
        self.widgets.clear()
        self.field = self.app = self.interpreter = None

    def test_unchanged_focus_and_return_keep_plan_small_test_and_generation(self):
        original_plan = self.app.plan
        self.field.deliver('<FocusIn>')
        self.field.deliver('<Return>')
        self.field.deliver('<FocusOut>')
        self.assertIs(self.app.plan, original_plan)
        self.assertTrue(self.app.small_test_passed)
        self.assertEqual(self.app.preview_generation, 0)
        self.app.root.after.assert_not_called()

    def test_changed_return_commits_once_and_later_blur_keeps_new_plan(self):
        self.field.deliver('<FocusIn>')
        self.app.brush_px.set('4')
        self.field.deliver('<Return>')
        self.assertIsNone(self.app.plan)
        self.assertFalse(self.app.small_test_passed)
        self.assertEqual(self.app.preview_generation, 1)
        new_plan = self.app.plan = {'count': 9}
        self.app.small_test_passed = True
        self.field.deliver('<Return>')
        self.field.deliver('<FocusOut>')
        self.assertIs(self.app.plan, new_plan)
        self.assertTrue(self.app.small_test_passed)
        self.assertEqual(self.app.preview_generation, 1)

    def test_editing_back_to_original_text_is_not_a_settings_change(self):
        self.field.deliver('<FocusIn>')
        self.app.brush_px.set('5')
        self.app.brush_px.set('3')
        self.field.deliver('<FocusOut>')
        self.assertIsNotNone(self.app.plan)
        self.assertEqual(self.app.preview_generation, 0)

    def test_invalid_edit_and_its_correction_keep_actual_options_validation(self):
        self.field.deliver('<FocusIn>')
        self.app.brush_px.set('invalid')
        self.field.deliver('<Return>')
        self.assertIsNone(self.app.plan)
        with self.assertRaisesRegex(ValueError, 'whole number'):
            DrawBot.DrawBotApp.options(self.app)
        self.app.brush_px.set('4')
        self.field.deliver('<Return>')
        with tempfile.TemporaryDirectory() as directory, \
                patch('RuntimePaths.source_dir', return_value=Path(directory)), \
                patch('DrawBot.custom_rgb_available', return_value=False):
            self.assertEqual(DrawBot.DrawBotApp.options(self.app)['brush_px'], 4)
        self.field.deliver('<FocusOut>')
        self.assertEqual(self.app.preview_generation, 2)

    def test_external_and_guarded_settings_updates_refresh_the_commit_baseline(self):
        self.app.brush_px.set('7')
        self.field.deliver('<FocusIn>')
        self.field.deliver('<FocusOut>')
        self.assertEqual(self.app.preview_generation, 0)
        self.field.deliver('<FocusIn>')
        with settings_application(self.app):
            self.app.brush_px.set('8')
        with self.assertRaisesRegex(ValueError, 'rollback'):
            with settings_application(self.app):
                self.app.brush_px.set('9')
                raise ValueError('rollback')
        self.assertEqual(self.app.brush_px.get(), '8')
        self.field.deliver('<Return>')
        self.assertEqual(self.app.preview_generation, 0)
        self.app.brush_px.set('10')
        self.field.deliver('<FocusOut>')
        self.assertEqual(self.app.preview_generation, 1)

    def test_another_actual_controller_action_acknowledges_the_focused_field(self):
        self.field.deliver('<FocusIn>')
        self.app.outline.set(True)
        self.app.subject_focus = renderer_fixtures.Value('Off')
        DrawBot.DrawBotApp.sketch_mode_changed(self.app)
        self.assertEqual(self.app.brush_px.get(), '1')
        self.assertEqual(self.app.preview_generation, 1)
        new_plan = self.app.plan = {'count': 12}
        self.app.small_test_passed = True
        self.field.deliver('<FocusOut>')
        self.assertIs(self.app.plan, new_plan)
        self.assertTrue(self.app.small_test_passed)
        self.assertEqual(self.app.preview_generation, 1)

    def test_failed_invalidation_is_not_acknowledged_and_can_be_retried(self):
        self.field.deliver('<FocusIn>')
        self.app.brush_px.set('4')
        actual = self.app._mark_plan_stale
        self.app._mark_plan_stale = Mock(side_effect=ValueError('invalid settings'))
        with self.assertRaisesRegex(ValueError, 'invalid settings'):
            self.field.deliver('<Return>')
        self.assertIsNotNone(self.app.plan)
        self.app._mark_plan_stale = actual
        self.field.deliver('<FocusOut>')
        self.assertIsNone(self.app.plan)
        self.assertEqual(self.app.preview_generation, 1)

    def test_destroy_removes_the_owned_variable_trace_and_late_callbacks_are_inert(self):
        self.assertTrue(self.app.brush_px.trace_info())
        self.field.destroy()
        self.assertFalse(self.app.brush_px.trace_info())
        old_plan = self.app.plan
        self.app.brush_px.set('4')
        self.field.deliver('<Return>')
        self.assertIs(self.app.plan, old_plan)


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows CTk entry focus/Return delivery')
class WindowsNumericCommitTests(unittest.TestCase):
    def test_native_entry_change_and_focus_events_preserve_existing_class_bindings(self):
        with ExitStack() as stack:
            root = ctk.CTk()
            scopes = []
            stack.callback(release_factory_scopes, scopes)
            stack.callback(root.destroy)
            root.geometry('620x310')
            errors = []
            root.report_callback_exception = lambda *args: errors.append(args)
            app = controller_app(root, root)
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_start_buttons_text'))
            stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_target_lock_text'))
            field = actual_numeric_row(app, root, app.brush_px, scopes=scopes)
            other = ctk.CTkEntry(root)
            other.pack(pady=10)
            root.update()
            original_plan = app.plan
            field.focus_force()
            root.update()
            self.assertIs(root.focus_get(), field._entry)
            field._entry.event_generate('<Return>')
            other.focus_force()
            root.update()
            self.assertIs(app.plan, original_plan)
            self.assertEqual(app.preview_generation, 0)
            field.focus_force()
            root.update()
            field.delete(0, 'end')
            field.insert(0, '4')
            field._entry.event_generate('<Return>')
            root.update()
            self.assertEqual(app.brush_px.get(), '4')
            self.assertIsNone(app.plan)
            self.assertEqual(app.preview_generation, 1)
            field._entry.event_generate('<Return>')
            other.focus_force()
            root.update()
            self.assertEqual(app.preview_generation, 1)
            self.assertFalse(errors, errors)
            field.destroy()
            self.assertFalse(app.brush_px.trace_info())


if __name__ == '__main__':
    unittest.main()
