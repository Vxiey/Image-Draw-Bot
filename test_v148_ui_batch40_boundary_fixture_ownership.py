"""Real area fixtures retire their Tcl owner before a later worker collection."""
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = '''import gc, json, sys, threading, tkinter as tk, unittest, weakref
from unittest.mock import patch
from test_v148_ui_batch37_boundary import BoundaryAdoptionTests
from test_v148_ui_batch38_saved_area import SavedAreaCancellationTests

mode = sys.argv[1]
creator = threading.get_ident()
owners, variables, owner_finalized, variable_finalized, frames = [], [], [], [], []
actual_tcl = tk.Tcl
actual_variable_init = tk.Variable.__init__
actual_variable_finalize = tk.Variable.__del__

def tracked_tcl(*args, **kwargs):
    owner = actual_tcl(*args, **kwargs)
    owners.append(weakref.ref(owner, lambda _reference: owner_finalized.append(threading.get_ident())))
    return owner

def variable_init(variable, *args, **kwargs):
    actual_variable_init(variable, *args, **kwargs)
    variables.append(weakref.ref(variable))

def variable_finalize(variable):
    variable_finalized.append(threading.get_ident())
    actual_variable_finalize(variable)

def retain_native_boundary(frame, event, _arg):
    # Keep the real boundary frame, including its actual exception/traceback
    # list, alive beyond cleanup. No GC policy or native destructor is removed.
    if (event == 'return' and frame.f_code.co_name in ('delivered', 'picked') and
            frame.f_code.co_filename.endswith(('test_v148_ui_batch37_boundary.py',
                                               'test_v148_ui_batch38_saved_area.py'))):
        frames.append(frame)

assert gc.isenabled()
with patch.object(tk, 'Tcl', new=tracked_tcl), \\
     patch.object(tk.Variable, '__init__', new=variable_init), \\
     patch.object(tk.Variable, '__del__', new=variable_finalize):
    case_type = BoundaryAdoptionTests if mode == 'selection' else SavedAreaCancellationTests
    cases = list(unittest.defaultTestLoader.loadTestsFromTestCase(case_type))
    result = unittest.TestResult()
    sys.setprofile(retain_native_boundary)
    try:
        for case in cases:
            case.run(result)
    finally:
        sys.setprofile(None)
    assert result.testsRun == 6 and result.wasSuccessful(), (result.testsRun, result.errors, result.failures)
    assert not result.skipped, result.skipped
    assert frames, 'The actual picker boundary did not run'
    failures = [error for frame in frames for error in frame.f_locals.get('failures', [])]
    assert failures and all(error.__traceback__ is not None for error in failures)
    assert len(owners) == 6 and variables
    alive_owners = [index for index, reference in enumerate(owners) if reference() is not None]
    assert not alive_owners, ('Picker fixture retained its Tcl owner', alive_owners)
    assert all(reference() is None for reference in variables), 'A fixture Tcl variable survived cleanup'
    assert len(owner_finalized) == len(owners) and set(owner_finalized) == {creator}, owner_finalized
    assert len(variable_finalized) == len(variables) and set(variable_finalized) == {creator}, variable_finalized
    assert gc.isenabled()
    worker = threading.Thread(target=gc.collect)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert set(owner_finalized) == set(variable_finalized) == {creator}
    print(json.dumps({'mode': mode, 'actual_workflows': result.testsRun,
                      'retired_owners': len(owners), 'retired_variables': len(variables),
                      'retained_boundary_frames': len(frames), 'retained_exceptions': len(failures),
                      'worker_gc': 'complete', 'automatic_gc': 'enabled'}))
'''


class BoundaryFixtureOwnershipTests(unittest.TestCase):
    def check_fixture(self, mode):
        result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', PROBE, mode],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"worker_gc": "complete"', result.stdout)
        self.assertIn('"automatic_gc": "enabled"', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)

    def test_real_selection_errors_cannot_retain_the_fixture_interpreter(self):
        self.check_fixture('selection')

    def test_real_saved_area_helpers_release_tcl_before_worker_collection(self):
        self.check_fixture('saved-area')


if __name__ == '__main__':
    unittest.main()
