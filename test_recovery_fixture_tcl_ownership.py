"""Background recovery fixtures retire their worker's borrowed Tcl owner."""
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = '''import gc, threading, tkinter as tk, unittest, weakref
from unittest.mock import patch
from test_v148_application_batch36_recovery_resume import RecoveryAfterBackgroundEditTests
owners, finalized = [], []
creator = threading.get_ident()
actual = tk.Tcl

def tracked(*args, **kwargs):
    owner = actual(*args, **kwargs)
    owners.append(weakref.ref(owner, lambda _ref: finalized.append(threading.get_ident())))
    return owner

# Diagnostic policy only: deterministic cleanup must not depend on automatic GC.
gc.disable()
with patch.object(tk, 'Tcl', new=tracked):
    result = unittest.TestResult()
    cases = list(unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryAfterBackgroundEditTests))
    for case in cases:
        case.run(result)
    assert result.wasSuccessful(), (result.errors, result.failures)
    assert result.testsRun == 6 and not result.skipped
    assert len(owners) == 6
    assert all(reference() is None for reference in owners), 'Recovery fixture retained Tcl'
    assert finalized == [creator] * 6, finalized
    worker = threading.Thread(target=gc.collect)
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    assert finalized == [creator] * 6
print('Recovery fixture Tcl retired before worker collection')
'''


class RecoveryFixtureTclOwnershipTests(unittest.TestCase):
    def test_recovery_fixtures_retire_tcl_before_worker_collection(self):
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', PROBE],
                                cwd=Path(__file__).resolve().parent,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Tcl retired before worker collection', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)


if __name__ == '__main__':
    unittest.main()
