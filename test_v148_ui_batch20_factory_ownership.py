"""Actual UI factory fixtures release Tcl owners before a later worker's GC."""
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = '''import gc, json, sys, threading, tkinter as tk, unittest, weakref
from unittest.mock import patch
import customtkinter as ctk
import test_v148_ui_batch09_readouts as readouts
import test_v148_ui_batch10_numeric as numeric
import test_v148_ui_batch12_switches as switches
import test_v148_ui_batch15_contrast as contrast

mode = sys.argv[1]
creator = threading.get_ident()
roots, variables, finalized, retained, failures, destroyed = [], [], [], [], [], []
actual_root_init = tk.Tk.__init__
actual_variable_init = tk.Variable.__init__
actual_finalize = tk.Variable.__del__

def root_init(owner, *args, **kwargs):
    actual_root_init(owner, *args, **kwargs)
    roots.append(weakref.ref(owner))

def variable_init(variable, *args, **kwargs):
    actual_variable_init(variable, *args, **kwargs)
    variables.append(weakref.ref(variable))

def finalize(variable):
    finalized.append(threading.get_ident())
    actual_finalize(variable)

def retained_failure():
    try:
        raise RuntimeError('retained assertion frame after actual UI delivery')
    except RuntimeError as error:
        failures.append(error)
        raise

def capture(case):
    if mode == 'readouts':
        return
    retained.extend(case.widgets)
    retained.extend(case.factory_scopes)
    # The actual numeric Help closure needs root in its exec globals. Exercise
    # it while the controls are alive, before either success or error teardown.
    if mode == 'numeric':
        help_buttons = [widget for widget in case.widgets if widget.kwargs.get('text') == '?']
        assert len(help_buttons) == 1
        calls = []
        def showinfo(*args, **kwargs):
            calls.append((args, kwargs))
        command = help_buttons[0].kwargs['command']
        with patch('tkinter.messagebox.showinfo', new=showinfo):
            command()
        assert len(calls) == 1 and calls[0][1]['parent'] is case.app.root
        retained.append(command)
        retained.extend(case.field.bindings['<Return>'])
    else:
        for widget in case.widgets:
            retained.extend(callback for callbacks in widget.logical_surface.bindings.values()
                            for callback in callbacks)

class ObserveAssertions:
    failing = False
    captured = False
    def assertEqual(self, first, second, *args, **kwargs):
        super().assertEqual(first, second, *args, **kwargs)
        match = ((mode == 'readouts' and first == second == '')
                 or (mode == 'numeric' and first == second == 0)
                 or (mode == 'switches' and second == [{'delay': 15}] * 3)
                 or (mode == 'contrast' and second == 'Contrast · 1.26×'))
        if match and not self.captured:
            self.captured = True
            capture(self)
            if self.failing:
                retained_failure()

classes = {
    'readouts': (readouts.LiveReadoutTests,
        'test_actual_drawing_summary_statements_bind_variables_instead_of_names'),
    'numeric': (numeric.NumericCommitTests,
        'test_unchanged_focus_and_return_keep_plan_small_test_and_generation'),
    'switches': (switches.SwitchKeyboardTests,
        'test_actual_factory_reaches_all_twelve_variables_and_preserves_callback_kinds'),
    'contrast': (contrast.ContrastKeyboardTests,
        'test_real_factory_and_controller_invalidate_once_without_starting_work'),
}
base, method = classes[mode]
Observed = type('Observed', (ObserveAssertions, base), {})
actual_readouts = readouts.actual_live_readouts
def observe_readouts(*args, **kwargs):
    result = actual_readouts(*args, **kwargs)
    retained.extend(result.values())
    return result

def observe_destroy(original):
    def destroy(widget):
        handler = getattr(widget, '_numeric_entry_commit', None)
        variable = handler.variable if handler is not None else getattr(widget, '_variable', None)
        original(widget)
        if variable is not None:
            # The fixture may release Python owners only after the actual
            # product destroy has removed its live Tcl trace.
            assert not variable.trace_info()
            variable.get()
            destroyed.append(True)
    return destroy

# Delay collection only in this diagnostic child. Every real Tk Variable
# finalizer remains active and is required to finish on its creator thread.
gc.disable()
with patch.object(tk.Tk, '__init__', new=root_init), \
     patch.object(tk.Variable, '__init__', new=variable_init), \
     patch.object(tk.Variable, '__del__', new=finalize), \
     patch.object(readouts, 'actual_live_readouts', new=observe_readouts), \
     patch.object(numeric.NativeWidget, 'destroy', new=observe_destroy(numeric.NativeWidget.destroy)), \
     patch.object(ctk.CTkSwitch, 'destroy', new=observe_destroy(ctk.CTkSwitch.destroy)), \
     patch.object(ctk.CTkSlider, 'destroy', new=observe_destroy(ctk.CTkSlider.destroy)):
    for failing in (False, True):
        case = Observed(method)
        case.failing = failing
        result = unittest.TestResult()
        case.run(result)
        assert case.captured
        if failing:
            assert len(result.errors) == 1 and not result.failures, (result.errors, result.failures)
            assert 'retained assertion frame' in result.errors[0][1], result.errors
        else:
            assert result.wasSuccessful(), (result.errors, result.failures)
        del case

    assert retained and failures and failures[0].__traceback__ is not None
    assert len(roots) == 2 and all(reference() is None for reference in roots)
    assert variables and all(reference() is None for reference in variables)
    assert len(finalized) == len(variables) and set(finalized) == {creator}, finalized
    assert mode == 'readouts' or destroyed
    worker = threading.Thread(target=gc.collect)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert set(finalized) == {creator}, finalized
print(json.dumps({'mode': mode, 'retired_roots': len(roots),
                  'retired_variables': len(variables), 'worker_gc': 'complete'}))
'''


class FactoryFixtureOwnershipTests(unittest.TestCase):
    def check_fixture(self, mode):
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', PROBE, mode],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"worker_gc": "complete"', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)

    def test_readouts_release_real_variables_with_retained_assertion_frames(self):
        self.check_fixture('readouts')

    def test_numeric_globals_live_through_help_and_real_trace_destroy_then_release(self):
        self.check_fixture('numeric')

    def test_switch_globals_live_through_all_commands_and_real_trace_destroy_then_release(self):
        self.check_fixture('switches')

    def test_contrast_globals_live_through_value_readout_and_real_trace_destroy_then_release(self):
        self.check_fixture('contrast')


if __name__ == '__main__':
    unittest.main()
