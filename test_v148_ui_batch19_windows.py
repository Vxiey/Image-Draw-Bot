"""Actual branded Tk window lifetimes, with Tcl background errors observable."""
from functools import wraps
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch


class WindowOwnershipTests(unittest.TestCase):
    def test_actual_source_fixture_releases_tcl_before_worker_cycle_collection(self):
        code = '''import gc, threading, tkinter as tk, unittest, weakref
from test_v148_ui_batch17_source_timer import SourceTimerTests
owners, variables, finalized = [], [], []
creator = threading.get_ident()
original_finalize = tk.Variable.__del__
def finalize(variable):
    finalized.append(threading.get_ident())
    original_finalize(variable)
tk.Variable.__del__ = finalize
class ObservedSourceCase(SourceTimerTests):
    def setUp(self):
        super().setUp()
        owners.append(weakref.ref(self.tcl))
    def app(self):
        app = super().app()
        variables.extend(weakref.ref(value) for value in vars(app).values()
                         if isinstance(value, tk.Variable))
        return app
# Delay collection only inside this diagnostic child. Product GC is unchanged.
gc.disable()
case = ObservedSourceCase('test_actual_noop_background_result_preserves_source_plan_and_completed_time')
result = unittest.TestResult()
case.run(result)
assert result.wasSuccessful(), (result.errors, result.failures)
del case
assert variables and all(reference() is None for reference in variables)
assert all(reference() is None for reference in owners)
assert len(finalized) == len(variables) and set(finalized) == {creator}, finalized
worker = threading.Thread(target=gc.collect)
worker.start()
worker.join(timeout=5)
assert not worker.is_alive()
assert set(finalized) == {creator}
print('real source fixture and worker GC completed with creator-thread Tcl cleanup')
'''
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('creator-thread Tcl cleanup', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)

    def test_timer_cleanup_matches_exact_subtree_commands_and_leaves_deletion_owned(self):
        from UiWindowLifetime import cancel_widget_after_jobs
        interpreter = tk.Tcl()
        for name in ('owned', 'owned_suffix', 'outside'):
            interpreter.tk.createcommand(name, lambda: None)
        child = SimpleNamespace(_tclCommands=['owned'], winfo_children=lambda: [])
        panel = SimpleNamespace(tk=interpreter.tk, _tclCommands=[], winfo_children=lambda: [child])
        scripts = ('owned', '{owned}', 'owned_suffix', 'outside', 'owned data', 'owned; outside')
        jobs = {script: interpreter.tk.call('after', 60_000, script) for script in scripts}
        self.addCleanup(lambda: [interpreter.tk.call('after', 'cancel', job) for job in jobs.values()])
        cancel_widget_after_jobs(panel)
        remaining = interpreter.tk.splitlist(interpreter.tk.call('after', 'info'))
        self.assertNotIn(jobs['owned'], remaining)
        self.assertNotIn(jobs['{owned}'], remaining)
        self.assertEqual(set(remaining), {jobs[script] for script in scripts[2:]})
        self.assertTrue(interpreter.tk.call('info', 'commands', 'owned'))
        self.assertEqual(child._tclCommands, ['owned'])

    def test_real_destroy_failure_remains_retryable_and_a_late_callback_is_inert(self):
        from UiCompatibility import scoped_window_class

        class NativeBoundary:
            def __init__(self):
                self.callbacks, self.pending = {}, set()
                self.alive, self.attempts = True, 0
            def after(self, _delay, callback):
                job = len(self.callbacks) + 1
                self.callbacks[job] = callback
                self.pending.add(job)
                return job
            def after_cancel(self, job):
                self.pending.discard(job)
            def winfo_exists(self):
                return self.alive
            def destroy(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise tk.TclError('bad window path name ".still-live"')
                self.destroy()  # A converging native close cannot recurse.
                self.alive = False

        window = scoped_window_class(NativeBoundary)()
        delivered = []
        job = window.after(1, lambda: delivered.append('old'))
        late = window.callbacks[job]
        with self.assertRaisesRegex(tk.TclError, 'still-live'):
            window.destroy()
        self.assertTrue(window.winfo_exists())
        self.assertFalse(window._window_destroyed)
        self.assertFalse(window._window_destroying)
        late()
        self.assertEqual(delivered, [])
        window.after(1, lambda: delivered.append('new'))
        window.destroy()
        window.destroy()
        late()
        self.assertEqual(window.attempts, 2)
        self.assertFalse(window.winfo_exists())
        self.assertFalse(window.pending)
        self.assertEqual(delivered, [])


def isolated_native(method):
    @wraps(method)
    def run(case):
        flag = 'IMAGEDRAWBOT_WINDOW_LIFETIME_TEST_CHILD'
        if os.environ.get(flag) == method.__name__:
            return method(case)
        code = '''import sys, unittest
from test_v148_ui_batch19_windows import NativeWindowLifetimeTests
NativeWindowLifetimeTests.__unittest_skip__ = False
case = NativeWindowLifetimeTests(sys.argv[1])
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([case]))
raise SystemExit(not result.wasSuccessful())
'''
        result = subprocess.run([sys.executable, '-c', code, method.__name__],
            cwd=Path(__file__).resolve().parent, env={**os.environ, flag: method.__name__},
            capture_output=True, text=True, timeout=20)
        case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    return run


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native branded window regression requires a Tk display')
class NativeWindowLifetimeTests(unittest.TestCase):
    def root(self, errors):
        from DrawBot import create_root
        root = create_root()
        self.addCleanup(self.close, root)
        root.geometry('680x500+40+40')
        root.report_callback_exception = lambda *error: errors.append(('Python callback', error))
        # This literal Tcl command deliberately survives root.destroy during
        # the test, so a later interpreter can expose stale timer commands.
        root.tk.createcommand('bgerror', lambda message: errors.append(('Tcl bgerror', message)))
        return root

    @staticmethod
    def close(root):
        try:
            root.destroy()
        except (tk.TclError, RuntimeError):
            pass

    @staticmethod
    def drain(root, milliseconds=350):
        root.after(milliseconds, root.quit)
        root.mainloop()

    @staticmethod
    def widgets(widget):
        for child in widget.winfo_children():
            yield child
            yield from NativeWindowLifetimeTests.widgets(child)

    @isolated_native
    def test_real_tooltip_and_about_close_preserve_other_jobs_without_background_errors(self):
        import customtkinter as ctk
        import StudioUI
        from DrawBot import DrawBotApp

        errors, survivors = [], []
        root = self.root(errors)
        button = StudioUI.button(root, 'Hover for help', lambda: None)
        button.pack()
        root.update()
        original_bindings = root.bind_all('<Button-1>').strip()
        tip = StudioUI.ToolTip(button, 'Actual tooltip content', delay=0)
        app = DrawBotApp.__new__(DrawBotApp)
        app.root = root
        retained = []
        for repeat in range(2):
            tip._enter()
            root.update()
            tooltip_window = tip.window
            self.assertTrue(tooltip_window.winfo_exists())
            self.assertTrue(getattr(tooltip_window, '_image_draw_bot_icon_after', None))
            tip._leave()
            self.assertFalse(tooltip_window.winfo_exists())
            app.show_about()
            root.update()
            about = next(child for child in root.winfo_children()
                         if isinstance(child, tk.Toplevel) and child.title() == 'About Image Draw Bot')
            retained.append(about)
            close_button = next(widget for widget in self.widgets(about)
                if isinstance(widget, ctk.CTkButton) and widget.cget('text') == 'Close')
            close_button._on_enter()
            close_button._on_release()
            self.assertFalse(about.winfo_exists())
        other = tk.Toplevel(root)
        other.after(30, lambda: survivors.append('other window'))
        root.after(30, lambda: survivors.append('root'))
        self.drain(root)
        self.assertCountEqual(survivors, ['root', 'other window'])
        self.assertTrue(other.winfo_exists())
        with self.subTest(behavior='native delayed callbacks have no dead command'):
            self.assertEqual(errors, [])
        with self.subTest(behavior='closed dialogs remove only their global observers'):
            self.assertEqual(root.bind_all('<Button-1>').strip(), original_bindings)
        self.assertTrue(all(str(image) in root.tk.call('image', 'names')
                            for image in root._image_draw_bot_icons))

    @isolated_native
    def test_real_root_factory_disposes_failed_dnd_root_before_fallback(self):
        from customtkinter.windows.widgets.appearance_mode.appearance_mode_tracker import AppearanceModeTracker
        errors = []
        with patch('tkinterdnd2.TkinterDnD._require', side_effect=RuntimeError('missing native DnD test boundary')):
            root = self.root(errors)
        alive = [candidate for candidate in AppearanceModeTracker.app_list if candidate.winfo_exists()]
        self.addCleanup(lambda: [self.close(candidate) for candidate in alive])
        with self.subTest(behavior='one remaining interpreter window'):
            self.assertEqual(alive, [root])
        with self.subTest(behavior='default variables use the returned root'):
            self.assertIs(tk._default_root, root)
            variable = tk.StringVar(value='correct interpreter')
            self.assertIs(variable._tk, root.tk)
        self.drain(root)
        self.assertEqual(errors, [])

    @isolated_native
    def test_actual_root_destroy_error_can_retry_without_stopping_another_root(self):
        import customtkinter as ctk
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

        errors = []
        first = self.root(errors)
        ctk.CTkLabel(first, text='Retry closing this root').pack()
        second = self.root(errors)
        ctk.CTkLabel(second, text='Preserve this root').pack()
        original_destroy = tk.Tk.destroy
        failed = []

        def fail_once(window):
            if window is first and not failed:
                failed.append(True)
                raise tk.TclError('bad window path name ".native-retry-fixture"')
            return original_destroy(window)

        with patch.object(tk.Tk, 'destroy', fail_once):
            with self.assertRaisesRegex(tk.TclError, 'native-retry-fixture'):
                first.destroy()
            self.assertTrue(first.winfo_exists())
            self.assertFalse(getattr(first, '_image_draw_bot_destroyed', False))
            first.destroy()
            first.destroy()
        self.assertTrue(second.winfo_exists())
        with patch.object(ScalingTracker, 'get_window_dpi_scaling',
                          wraps=ScalingTracker.get_window_dpi_scaling) as dpi:
            self.drain(second)
        self.assertTrue(any(call.args == (second,) for call in dpi.call_args_list))
        self.assertEqual(errors, [])

    @isolated_native
    def test_destroyed_root_hands_shared_services_to_surviving_and_later_roots(self):
        import customtkinter as ctk
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker
        from customtkinter.windows.widgets.appearance_mode.appearance_mode_tracker import AppearanceModeTracker

        errors = []
        first = self.root(errors)
        ctk.CTkLabel(first, text='First application root').pack()
        second = self.root(errors)
        remaining = ctk.CTkLabel(second, text='Surviving application root')
        remaining.pack()
        first.update()
        second.update()
        first.destroy()
        desired = 'Dark' if AppearanceModeTracker.appearance_mode == 0 else 'Light'
        with patch('darkdetect.theme', return_value=desired), \
                patch.object(ScalingTracker, 'get_window_dpi_scaling',
                             wraps=ScalingTracker.get_window_dpi_scaling) as dpi:
            self.drain(second)
        with self.subTest(phase='surviving root DPI'):
            self.assertTrue(any(call.args == (second,) for call in dpi.call_args_list))
        with self.subTest(phase='surviving root appearance'):
            self.assertEqual(remaining._get_appearance_mode(), desired.lower())
        second.destroy()
        third = self.root(errors)
        new_widget = ctk.CTkLabel(third, text='Later application root')
        new_widget.pack()
        desired = 'Light' if desired == 'Dark' else 'Dark'
        with patch('darkdetect.theme', return_value=desired), \
                patch.object(ScalingTracker, 'get_window_dpi_scaling',
                             wraps=ScalingTracker.get_window_dpi_scaling) as dpi:
            self.drain(third)
        with self.subTest(phase='later root DPI'):
            self.assertTrue(any(call.args == (third,) for call in dpi.call_args_list))
        with self.subTest(phase='later root appearance'):
            self.assertEqual(new_widget._get_appearance_mode(), desired.lower())
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
