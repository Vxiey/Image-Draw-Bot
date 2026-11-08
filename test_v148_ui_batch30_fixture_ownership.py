"""Calibration test fixtures release Tcl before a later preview worker's GC."""
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = '''import gc, json, sys, threading, tkinter as tk, unittest, weakref
from unittest.mock import patch
from test_v148_ui_batch25_calibration_lifetime import CalibrationLifetimeTests, NativeDialogBoundary

mode = sys.argv[1]
creator = threading.get_ident()
owners, variables, finalized = [], [], []
windows, helpers, constructors, errors = [], [], [], []
actual_tcl = tk.Tcl
actual_variable_init = tk.Variable.__init__
actual_finalize = tk.Variable.__del__
actual_destroy = NativeDialogBoundary.destroy

def tracked_tcl(*args, **kwargs):
    owner = actual_tcl(*args, **kwargs)
    owners.append(weakref.ref(owner))
    return owner

def variable_init(variable, *args, **kwargs):
    actual_variable_init(variable, *args, **kwargs)
    variables.append(weakref.ref(variable))

def finalize(variable):
    finalized.append(threading.get_ident())
    actual_finalize(variable)

def destroy(window):
    try:
        return actual_destroy(window)
    except BaseException as error:
        # Keep the actual native boundary's error and its original traceback.
        # Fixture cleanup must work even while diagnostics retain this frame.
        errors.append((error, error.__traceback__))
        raise

class ObservedCalibration(CalibrationLifetimeTests):
    def route(self, row):
        app, window, group, constructor = super().route(row)
        windows.append(window)
        constructors.append(constructor)
        def create(*args, **kwargs):
            helper = constructor(*args, **kwargs)
            helpers.append(helper)
            return helper
        return app, window, group, create

# Delayed collection exists only inside this diagnostic child. Every original
# Variable finalizer runs, and no application GC policy is modified.
gc.disable()
with patch.object(tk, 'Tcl', new=tracked_tcl), \\
     patch.object(tk.Variable, '__init__', new=variable_init), \\
     patch.object(tk.Variable, '__del__', new=finalize), \\
     patch.object(NativeDialogBoundary, 'destroy', new=destroy):
    case_type = CalibrationLifetimeTests if mode == 'ordinary' else ObservedCalibration
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(case_type).run(result)
    assert result.testsRun == 6 and result.wasSuccessful(), (result.testsRun, result.errors, result.failures)
    assert not result.skipped, result.skipped
    assert len(owners) == 6 and len(variables) == 134, (len(owners), len(variables))
    if mode == 'retained':
        assert windows and helpers and constructors and errors
        assert all(not vars(value) for value in windows + helpers)
        # unittest.assertRaises clears error.__traceback__; keep the original
        # traceback separately so that its real frames still outlive cleanup.
        assert all(trace is not None for error, trace in errors)
    assert all(reference() is None for reference in owners), 'Tcl fixture owner survived cleanup'
    assert all(reference() is None for reference in variables), 'Tcl fixture variable survived cleanup'
    assert len(finalized) == len(variables) and set(finalized) == {creator}, finalized
    worker = threading.Thread(target=gc.collect)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(finalized) == len(variables) and set(finalized) == {creator}, finalized
    print(json.dumps({'mode': mode, 'actual_workflows': result.testsRun,
                      'retired_owners': len(owners), 'retired_variables': len(variables),
                      'retained_native_errors': len(errors), 'worker_gc': 'complete'}))
'''


class CalibrationFixtureOwnershipTests(unittest.TestCase):
    def check_fixture(self, mode):
        result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', PROBE, mode],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"worker_gc": "complete"', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)

    def test_six_actual_calibration_workflows_retire_tcl_before_worker_collection(self):
        self.check_fixture('ordinary')

    def test_retained_native_errors_and_callbacks_cannot_keep_fixture_tcl_alive(self):
        self.check_fixture('retained')


if __name__ == '__main__':
    unittest.main()
