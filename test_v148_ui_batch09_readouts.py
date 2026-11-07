"""Actual StudioUI drawing readouts follow their live Tk variables."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

import customtkinter as ctk

import StudioUI


READOUTS = {
    'color_plan': 'color_plan_text',
    'draw_time_side': 'draw_time_text',
    'draw_live_side': 'draw_live_time_text',
    'total_draw_side': 'total_draw_time_text',
}


def actual_live_readouts(parent, app):
    """Run the real factory and four active statements, without unrelated UI."""
    tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf-8'))
    build = next(node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == 'build_ui')
    statements = []
    for node in build.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'label':
            statements.append(node)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id in READOUTS):
            statements.append(node)
    namespace = dict(vars(StudioUI), a=app, step5=parent)
    try:
        exec(compile(ast.Module(body=statements, type_ignores=[]), StudioUI.__file__, 'exec'), namespace)
        return {name: namespace[name] for name in READOUTS}
    finally:
        # The temporary label function otherwise retains its own globals and
        # their app/Tcl owner until whichever thread next collects cycles.
        namespace.clear()


class LiveReadoutTests(unittest.TestCase):
    def test_actual_drawing_summary_statements_bind_variables_instead_of_names(self):
        interpreter = tk.Tcl()
        app = SimpleNamespace(**{name: tk.StringVar(interpreter, value=f'Initial {name}')
                                 for name in READOUTS.values()})
        with patch.object(ctk, 'CTkLabel', side_effect=lambda parent, **kwargs: kwargs):
            widgets = actual_live_readouts(object(), app)
        for widget_name, variable_name in READOUTS.items():
            with self.subTest(readout=variable_name):
                options = widgets[widget_name]
                self.assertIs(options['textvariable'], getattr(app, variable_name))
                self.assertEqual(options['text'], '')


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows Tk live readout binding')
class WindowsLiveReadoutTests(unittest.TestCase):
    def test_readouts_show_initial_and_updated_values_without_recreating_widgets(self):
        root = ctk.CTk()
        self.addCleanup(root.destroy)
        root.geometry('500x320')
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        app = SimpleNamespace(**{name: tk.StringVar(root, value=f'Initial {name}')
                                 for name in READOUTS.values()})
        widgets = actual_live_readouts(root, app)
        for widget in widgets.values():
            widget.pack(fill='x', padx=10, pady=4)
        root.update()
        for widget_name, variable_name in READOUTS.items():
            variable = getattr(app, variable_name)
            native = widgets[widget_name]._label
            self.assertEqual(native.cget('text'), variable.get())
            for value in ('12 färger · återstår 3.5 s', 'Completed\nElapsed: 2 min', ''):
                variable.set(value)
                root.update()
                self.assertEqual(native.cget('text'), value)
                self.assertIs(widgets[widget_name]._label, native)
        self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
