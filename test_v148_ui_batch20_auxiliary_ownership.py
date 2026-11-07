"""Older real Tcl fixtures retire their owners before later worker collection."""
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = '''import gc, json, sys, threading, tkinter as tk, unittest, weakref
from unittest.mock import patch
from test_v148_ui_batch14_html_drop import BrowserHtmlDropTests, drop_fixtures
from test_v148_ui_batch18_mobile_dialog import MobileDialogWorkflowTests

mode = sys.argv[1]
owners, variables, roots, callbacks, finalized, failures = [], [], [], [], [], []
creator = threading.get_ident()
actual_tcl = tk.Tcl
actual_finalize = tk.Variable.__del__
actual_make_app = drop_fixtures.CanvasDropToDrawV1083Tests.make_app

def tracked_tcl(*args, **kwargs):
    owner = actual_tcl(*args, **kwargs)
    owners.append(weakref.ref(owner))
    return owner

def finalize(variable):
    finalized.append(threading.get_ident())
    actual_finalize(variable)

def make_app(case, *args, **kwargs):
    app, loaded = actual_make_app(case, *args, **kwargs)
    roots.append(app.root)
    return app, loaded

def retained_failure():
    try:
        raise RuntimeError('retained error after real UI operation')
    except RuntimeError as error:
        failures.append(error)
        raise

class ObservedHtml(BrowserHtmlDropTests):
    failing = False
    def assertEqual(self, first, second, *args, **kwargs):
        super().assertEqual(first, second, *args, **kwargs)
        if self.failing and first == 'copy' and second == 'copy':
            retained_failure()

class ObservedMobile(MobileDialogWorkflowTests):
    failing = False
    def app(self):
        app = super().app()
        roots.append(app.root)
        variables.extend(weakref.ref(value) for value in vars(app).values()
                         if isinstance(value, tk.Variable))
        return app
    def controls(self, window):
        result = super().controls(window)
        callbacks.extend(widget.options['command'] for widget in result[0].values())
        if self.failing:
            self.failing = False
            retained_failure()
        return result

# Only this child delays cyclic collection to expose the ownership boundary.
# Every real Variable finalizer still runs; no product GC policy is changed.
gc.disable()
tk.Variable.__del__ = finalize
with patch.object(tk, 'Tcl', new=tracked_tcl), patch.object(
        drop_fixtures.CanvasDropToDrawV1083Tests, 'make_app', new=make_app):
    for failing in (False, True):
        if mode == 'html':
            case = ObservedHtml('test_actual_window_drop_imports_only_the_selected_image_through_public_decoder')
        elif mode == 'mobile':
            case = ObservedMobile('test_callbacks_retained_from_an_old_panel_cannot_open_copy_or_stop_a_restart')
        else:
            raise AssertionError(mode)
        case.failing = failing
        result = unittest.TestResult()
        case.run(result)
        if failing:
            assert len(result.errors) == 1 and not result.failures, (result.errors, result.failures)
            assert 'retained error after real UI operation' in result.errors[0][1], result.errors
        else:
            assert result.wasSuccessful(), (result.errors, result.failures)
        del case

assert roots and failures and failures[0].__traceback__ is not None
assert owners and all(reference() is None for reference in owners)
assert all(reference() is None for reference in variables)
assert len(finalized) == len(variables)
assert not finalized or set(finalized) == {creator}, finalized
if mode == 'html':
    assert all(not isinstance(root.tk, tk.Misc) for root in roots)
else:
    assert callbacks and all(callback() is False for callback in callbacks)
worker = threading.Thread(target=gc.collect)
worker.start()
worker.join(timeout=5)
assert not worker.is_alive()
assert not finalized or set(finalized) == {creator}, finalized
print(json.dumps({'mode': mode, 'retired_owners': len(owners),
                  'retired_variables': len(variables), 'worker_gc': 'complete'}))
'''


class AuxiliaryFixtureOwnershipTests(unittest.TestCase):
    def check_fixture(self, mode):
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', PROBE, mode],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"worker_gc": "complete"', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)

    def test_html_drop_releases_borrowed_interpreter_with_retained_native_call_history(self):
        self.check_fixture('html')

    def test_mobile_callbacks_release_fixture_variables_after_real_stop_and_destroy(self):
        self.check_fixture('mobile')


if __name__ == '__main__':
    unittest.main()
