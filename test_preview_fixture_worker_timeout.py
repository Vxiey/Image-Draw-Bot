"""Preview test timeouts retire borrowed workers before assertion unwinding."""
import queue
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest

from test_v148_ui_batch20_preview_estimate import PreviewEstimateFixture, run_preview_process


class PreviewFixtureWorkerTimeoutTests(unittest.TestCase):
    def fixture(self):
        fixture = PreviewEstimateFixture()
        fixture.plans = []
        return fixture

    def test_timeout_stops_and_joins_before_reporting_failure(self):
        fixture = self.fixture()
        app = SimpleNamespace(stop=threading.Event(), paused=threading.Event(),
                              events=queue.Queue())
        app.paused.set()
        finished = threading.Event()
        plan = {'test': 'queued result retained for cleanup'}
        def work():
            app.stop.wait(5)
            app.events.put(('planned', plan))
            app.events.put(('done', None))
            finished.set()
        app.worker = threading.Thread(target=work)
        app.worker.start()
        try:
            with self.assertRaisesRegex(AssertionError, 'exceeded its fixture bound'):
                fixture.wait_for_preview_worker(app, worker_timeout=.001)
            self.assertTrue(finished.is_set())
            self.assertFalse(app.worker.is_alive())
            self.assertFalse(app.paused.is_set())
            self.assertEqual(fixture.plans, [plan])
            self.assertTrue(app.events.empty())
        finally:
            app.stop.set()
            app.worker.join(5)

    def test_completed_worker_keeps_results_and_does_not_request_stop(self):
        fixture = self.fixture()
        app = SimpleNamespace(stop=threading.Event(), paused=threading.Event(),
                              events=queue.Queue())
        app.events.put(('done', None))
        app.worker = threading.Thread(target=lambda: None)
        app.worker.start()
        fixture.wait_for_preview_worker(app)
        self.assertFalse(app.stop.is_set())
        self.assertEqual(app.events.get_nowait(), ('done', None))
        self.assertEqual(fixture.plans, [])

    def test_stuck_worker_is_killed_without_unwinding_borrowed_resources(self):
        # A real worker deliberately ignores cancellation. The child must not
        # leave the borrowed-resource scope, even after both join bounds pass.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            marker = str(Path(directory) / 'unsafe-unwind')
            code = """
import threading, queue
from pathlib import Path
from types import SimpleNamespace
from test_v148_ui_batch20_preview_estimate import PreviewEstimateFixture
fixture = PreviewEstimateFixture()
fixture.plans = []
app = SimpleNamespace(stop=threading.Event(), paused=threading.Event(), events=queue.Queue())
app.worker = threading.Thread(target=lambda: threading.Event().wait())
app.worker.start()
Path(MARKER + '.ready').write_text('worker started')
try:
    fixture.wait_for_preview_worker(app, worker_timeout=.01, stop_timeout=.01)
finally:
    Path(MARKER).write_text('resources unwound with live worker')
""".replace('MARKER', repr(marker))
            with self.assertRaisesRegex(AssertionError, 'process bound') as failure:
                run_preview_process([sys.executable, '-c', code], timeout=.2,
                                    ready_file=marker + '.ready', startup_timeout=60)
            self.assertIsInstance(failure.exception.__cause__, subprocess.TimeoutExpired)
            self.assertTrue(Path(marker + '.ready').exists())
            self.assertFalse(Path(marker).exists())

    def test_child_skip_is_reported_as_skip_not_success(self):
        from unittest.mock import patch
        fixture = PreviewEstimateFixture()
        child = subprocess.CompletedProcess([], 0,
            'IDB_PREVIEW_RESULT={"skipped": ["native display unavailable"]}\n', '')
        result = unittest.TestResult()
        with patch('test_v148_ui_batch20_preview_estimate.run_preview_process', return_value=child):
            fixture.run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual([reason for _, reason in result.skipped], ['native display unavailable'])
        self.assertFalse(result.errors or result.failures)
