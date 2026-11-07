"""A destroyed application button retires its own real Tcl animation jobs."""
from functools import wraps
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

import customtkinter as ctk

from UiKeyboardNavigation import KeyboardButton


def pending_commands(interpreter):
    result = {}
    for job in interpreter.splitlist(interpreter.call('after', 'info')):
        script, kind = interpreter.call('after', 'info', job)
        result[job] = (interpreter.splitlist(script), kind)
    return result


class ButtonTclLifetimeTests(unittest.TestCase):
    def test_destroy_cancels_only_its_real_tcl_jobs_before_deleting_commands(self):
        interpreter = tk.Tcl()
        errors, delivered = [], []
        interpreter.tk.createcommand('bgerror', errors.append)
        button = object.__new__(KeyboardButton)
        # Only native window allocation is absent. Registration, scheduling,
        # command deletion and the application's destroy method remain real.
        button.tk = interpreter.tk
        button.master = interpreter
        button.children = {}
        button._tclCommands = []
        button._keyboard_closed = False
        button._keyboard_pressed = None
        button._keyboard_job = None
        button.winfo_children = lambda: []
        button._click_animation_running = False
        jobs = [button.after(0, button._click_animation) for _ in range(5)]
        commands = tuple(button._tclCommands)
        survivor = interpreter.after(0, lambda: delivered.append('live owner'))
        try:
            self.assertEqual(len(commands), 5)
            self.assertTrue(all('_click_animation' in name for name in commands))
            self.assertEqual({pending_commands(interpreter.tk)[job][0][0] for job in jobs},
                             set(commands))
            # Use Tk's real command deletion at the native CTk destroy boundary.
            with patch.object(ctk.CTkButton, 'destroy', new=tk.Misc.destroy):
                button.destroy()
            self.assertTrue(button._keyboard_closed)
            self.assertFalse(set(jobs) & set(pending_commands(interpreter.tk)))
            self.assertIn(survivor, pending_commands(interpreter.tk))
            self.assertFalse(any(interpreter.tk.call('info', 'commands', command)
                                 for command in commands))
            interpreter.eval('update')
            self.assertEqual(delivered, ['live owner'])
            self.assertEqual(errors, [])
        finally:
            for job in (*jobs, survivor):
                interpreter.tk.call('after', 'cancel', job)
            tk.Misc.destroy(button)
            interpreter.tk.deletecommand('bgerror')


def isolated_native(method):
    @wraps(method)
    def run(case):
        flag = 'IMAGEDRAWBOT_BUTTON_LIFETIME_TEST_CHILD'
        if os.environ.get(flag) == method.__name__:
            return method(case)
        code = '''import importlib, sys, unittest
test_class = getattr(importlib.import_module(sys.argv[1]), sys.argv[2])
case = test_class(sys.argv[3])
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([case]))
raise SystemExit(not result.wasSuccessful())
'''
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code,
                                 case.__class__.__module__, case.__class__.__name__,
                                 method.__name__], cwd=Path(__file__).resolve().parent,
            env={**os.environ, flag: method.__name__}, capture_output=True, text=True,
            timeout=20)
        case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        case.assertNotIn('invalid command name', result.stderr)
        case.assertNotIn('Tcl_AsyncDelete', result.stderr)
    return run


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native application button lifetime requires a Tk display')
class NativeButtonLifetimeTests(unittest.TestCase):
    def root(self):
        from DrawBot import create_root
        root = create_root()
        root.geometry('520x320+30+30')
        self.addCleanup(root.destroy)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        root.tk.createcommand('bgerror', lambda message: errors.append(message))
        self.addCleanup(lambda: root.tk.deletecommand('bgerror'))
        return root, errors

    @staticmethod
    def drain(root):
        root.after(180, root.quit)
        root.mainloop()

    @isolated_native
    def test_five_real_pointer_animations_end_with_their_factory_button(self):
        import StudioUI
        root, errors = self.root()
        delivered = []
        button = StudioUI.button(root, 'Actual pointer action',
                                 lambda: delivered.append('clicked'))
        other = StudioUI.button(root, 'Surviving button', lambda: None)
        button.pack(); other.pack(); root.update()
        for _ in range(5):
            button._on_enter()
            button._on_release()
        owned = set(button._tclCommands or ())
        jobs = {job: script for job, (script, _kind) in pending_commands(root.tk).items()
                if len(script) == 1 and script[0] in owned and '_click_animation' in script[0]}
        self.assertEqual(len(jobs), 5)
        self.assertEqual(delivered, ['clicked'] * 5)
        other._on_enter(); other._on_release()
        other_commands = set(other._tclCommands or ())
        other_jobs = {job for job, (script, _kind) in pending_commands(root.tk).items()
                      if len(script) == 1 and script[0] in other_commands}
        survivor = root.after(0, lambda: delivered.append('root still live'))
        button.destroy()
        pending = pending_commands(root.tk)
        self.assertFalse(set(jobs) & set(pending))
        self.assertTrue(other_jobs <= set(pending))
        self.assertIn(survivor, pending)
        for script in jobs.values():
            self.assertFalse(root.tk.call('info', 'commands', script[0]))
        self.drain(root)
        self.assertEqual(delivered, ['clicked'] * 5 + ['root still live'])
        self.assertTrue(other.winfo_exists())
        self.assertEqual(errors, [])

    @isolated_native
    def test_pointer_command_can_destroy_its_own_button_without_late_animation(self):
        import StudioUI
        root, errors = self.root()
        delivered = []
        button = StudioUI.button(root, 'Remove this control', lambda: (
            delivered.append('invoked'), button.destroy()))
        button.pack(); root.update()
        button._on_enter(); button._on_release()
        self.assertFalse(button.winfo_exists())
        self.drain(root)
        self.assertEqual(delivered, ['invoked'])
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
