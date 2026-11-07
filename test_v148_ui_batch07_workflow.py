"""Error actions explain the actual failure; responsive focus keeps its panel."""
import ast
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import StudioUI
from UIState import classify_error
import test_v148_ui_batch06_workspace as workspace_fixtures

Value, Widget = workspace_fixtures.Value, workspace_fixtures.Widget


def error_help_callback(app):
    source = ast.parse(Path('StudioUI.py').read_text(encoding='utf-8'))
    call = next(node for node in ast.walk(source)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'button' and len(node.args) > 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == '❓ Help')
    return eval(compile(ast.Expression(call.args[2]), 'StudioUI.py', 'eval'),
                {'a': app, 'show_error_help': StudioUI.show_error_help})


class ErrorHelpTests(unittest.TestCase):
    def app(self, status):
        return SimpleNamespace(closing=False, status=Value(value=status), root=Mock(),
            draw=Mock(), start_full_drawing=Mock(), quick_start_hotkey=Mock(), begin_worker=Mock())

    def test_actual_error_card_callback_explains_storage_import_and_gpu_without_drawing(self):
        for message in ('Could not save PNG: disk full', 'Operation failed: cannot identify image file',
                        'Operation failed: GPU backend unavailable', 'Operation failed: palette is stale'):
            with self.subTest(message=message), patch('tkinter.messagebox.showinfo') as info:
                app = self.app(message)
                self.assertTrue(error_help_callback(app)())
                expected = classify_error(message)
                self.assertEqual(info.call_args.args[0], expected['title'])
                self.assertIn(expected['message'], info.call_args.args[1])
                self.assertIn(expected['action'], info.call_args.args[1])
                self.assertIs(info.call_args.kwargs['parent'], app.root)
                for action in (app.draw, app.start_full_drawing, app.quick_start_hotkey, app.begin_worker):
                    action.assert_not_called()

    def test_help_reads_current_error_instead_of_replaying_the_old_card_operation(self):
        app = self.app('Could not save PNG: disk full')
        callback = error_help_callback(app)
        app.status.set('Operation failed: cannot identify image file')
        with patch('tkinter.messagebox.showinfo') as info:
            callback()
        self.assertEqual(info.call_args.args[0], 'Image could not be opened')
        app.draw.assert_not_called()

    def test_resolved_error_and_shutdown_do_not_open_stale_dialogs(self):
        for message, closing in (('PNG saved: image.png', False), ('Operation failed: disk full', True)):
            app = self.app(message)
            app.closing = closing
            with self.subTest(message=message), patch('tkinter.messagebox.showinfo') as info:
                self.assertFalse(error_help_callback(app)())
                info.assert_not_called()


class ScrollbarFocusCompletionTests(unittest.TestCase):
    def test_scrollframe_outer_scrollbar_focus_survives_a_compact_transition(self):
        with ExitStack() as stack:
            main, panels, layout, _ = workspace_fixtures.WorkspaceLayoutTests().create(stack, 1500, 1)
            outer = Widget(main)
            panels['Readiness']._parent_frame = outer
            main.focus = Widget(outer)
            self.assertEqual(layout._focused_panel(), 'Readiness')
            main.width = 900
            layout.schedule()
            main.flush()
            self.assertEqual(layout.selected, 'Readiness')
            self.assertEqual([name for name, panel in panels.items() if panel.layout], ['Readiness'])

    def test_selecting_another_panel_moves_focus_out_of_its_hidden_outer_wrapper(self):
        with ExitStack() as stack:
            main, panels, layout, _ = workspace_fixtures.WorkspaceLayoutTests().create(stack, 900, 1)
            outer = Widget(main)
            panels['Readiness']._parent_frame = outer
            layout.select('Readiness')
            main.focus = Widget(outer)
            layout.select('Setup')
            self.assertIs(layout.selector.focus, layout.selector)


if __name__ == '__main__':
    unittest.main()
