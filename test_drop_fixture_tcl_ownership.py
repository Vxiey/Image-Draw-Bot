"""Drop fixtures release real Tcl on their creator thread, not worker GC."""
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = '''import gc, threading, tkinter as tk, unittest, weakref
from unittest.mock import patch
from test_guesser_drop import DropTests
owners, finalized = [], []
creator = threading.get_ident()
actual = tk.Tcl

def tracked(*args, **kwargs):
    owner = actual(*args, **kwargs)
    owners.append(weakref.ref(owner, lambda _ref: finalized.append(threading.get_ident())))
    return owner

# Force proof of deterministic ownership release rather than incidental GC.
gc.disable()
with patch.object(tk, 'Tcl', new=tracked):
    result = unittest.TestResult()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DropTests)
    suite.run(result)
    assert result.wasSuccessful(), (result.errors, result.failures)
    assert len(owners) == 3, len(owners)
    assert all(reference() is None for reference in owners), 'Drop fixture retained Tcl'
    assert finalized == [creator] * 3, finalized
    worker = threading.Thread(target=gc.collect)
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    assert finalized == [creator] * 3
print('Drop fixture Tcl retired before worker collection')
'''


class DropFixtureTclOwnershipTests(unittest.TestCase):
    def test_drop_fixtures_retire_tcl_before_worker_collection(self):
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', PROBE],
                                cwd=Path(__file__).resolve().parent,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Tcl retired before worker collection', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)


if __name__ == '__main__':
    unittest.main()
