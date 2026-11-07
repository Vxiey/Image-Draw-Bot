"""Native disposal of one Studio button preserves unrelated live callbacks."""
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
import unittest


_CHILD = 'IMAGEDRAWBOT_WIDGET_TIMER_TEST_CHILD'


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native widget timer regression requires a Tk display.')
class NativeButtonTimerTests(unittest.TestCase):
    def test_actual_click_then_child_disposal_leaves_only_live_owners(self):
        if os.environ.get(_CHILD) != '1':
            result = subprocess.run([sys.executable, '-X', 'faulthandler', '-m',
                'unittest', '-v', __name__ + '.' + type(self).__name__ + '.' + self._testMethodName],
                cwd=Path(__file__).resolve().parent, env={**os.environ, _CHILD: '1'},
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('invalid command name', result.stderr)
            return

        import customtkinter as ctk
        import StudioUI
        from UiCompatibility import scoped_window_class

        root = scoped_window_class(ctk.CTk)()
        root.geometry('540x340+30+30')
        errors, callbacks = [], []
        root.report_callback_exception = lambda *error: errors.append(('Python', repr(error)))
        # Leave this diagnostic command alive through native window destruction
        # so a later interpreter can expose an orphaned timer without masking it.
        root.tk.createcommand('bgerror', lambda message: errors.append(('Tcl', message)))
        try:
            for disposition in ('direct button', 'containing frame', 'own action'):
                with self.subTest(disposition=disposition):
                    frame = ctk.CTkFrame(root)
                    frame.pack()
                    target = StudioUI.button(frame, 'Remove this control',
                        lambda: callbacks.append((disposition, 'target action')))
                    target.pack()
                    survivor = StudioUI.button(root, 'Keep this control',
                        lambda: callbacks.append((disposition, 'live action')))
                    survivor.pack()
                    other_window = tk.Toplevel(root)
                    root.update()

                    def click(widget):
                        for sequence in ('<Enter>', '<ButtonPress-1>', '<ButtonRelease-1>'):
                            widget._canvas.event_generate(sequence, x=6, y=6, when='now')

                    def animation_jobs(widget):
                        result = {}
                        owned = set(widget._tclCommands or ())
                        for job in widget.tk.call('after', 'info'):
                            script = widget.tk.call('after', 'info', job)[0]
                            words = widget.tk.splitlist(script)
                            if len(words) == 1 and words[0] in owned and words[0].endswith('_click_animation'):
                                result[job] = words[0]
                        return result

                    # This actual native click has not returned to the event
                    # loop, so its real 100 ms animation must still be pending.
                    click(survivor)
                    survivor_jobs = animation_jobs(survivor)
                    self.assertTrue(survivor_jobs)
                    self.assertFalse(survivor._mouse_inside)
                    removed_jobs = {}
                    if disposition == 'own action':
                        def remove_self():
                            callbacks.append((disposition, 'target action'))
                            removed_jobs.update(animation_jobs(target))
                            target.destroy()
                        target.configure(command=remove_self)
                    click(target)
                    if disposition != 'own action':
                        removed_jobs.update(animation_jobs(target))
                    self.assertTrue(removed_jobs, 'The actual mouse animation must reach disposal')

                    root_job = root.after(30, lambda: callbacks.append((disposition, 'root')))
                    survivor_job = survivor.after(30, lambda: callbacks.append((disposition, 'sibling')))
                    other_job = other_window.after(30, lambda: callbacks.append((disposition, 'other window')))
                    if disposition == 'direct button':
                        target.destroy()
                    elif disposition == 'containing frame':
                        frame.destroy()

                    pending = set(root.tk.call('after', 'info'))
                    self.assertFalse(set(removed_jobs) & pending)
                    for command in removed_jobs.values():
                        self.assertFalse(root.tk.call('info', 'commands', command))
                    self.assertTrue(set(survivor_jobs) <= pending)
                    self.assertTrue({root_job, survivor_job, other_job} <= pending)
                    for command in survivor_jobs.values():
                        self.assertTrue(root.tk.call('info', 'commands', command))

                    root.after(180, root.quit)
                    root.mainloop()
                    self.assertTrue(survivor.winfo_exists())
                    self.assertTrue(other_window.winfo_exists())
                    self.assertTrue(survivor._mouse_inside, 'The live button animation must still execute')
                    self.assertCountEqual([kind for case, kind in callbacks if case == disposition],
                        ['target action', 'live action', 'root', 'sibling', 'other window'])
                    self.assertEqual(errors, [])
                    survivor.destroy()
                    other_window.destroy()
                    if frame.winfo_exists():
                        frame.destroy()
        finally:
            root.destroy()
            observer = tk.Tk()
            try:
                observer.after(180, observer.quit)
                observer.mainloop()
                self.assertEqual(errors, [])
            finally:
                observer.destroy()
                root.tk.deletecommand('bgerror')


if __name__ == '__main__':
    unittest.main()
