"""Exercise the Windows verification CLI without native input or real child processes."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class WindowsVerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.script = self.base / "verify_windows.py"
        source = Path(__file__).resolve().with_name("verify_windows.py")
        self.script.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    def run_cli(self, runner, *, platform="win32"):
        output = io.StringIO()
        with patch.object(sys, "platform", platform), \
                patch.object(subprocess, "run", side_effect=runner) as child, \
                redirect_stdout(output):
            with self.assertRaises(SystemExit) as exited:
                runpy.run_path(str(self.script), run_name="__main__")
        return exited.exception.code, output.getvalue(), child

    def report(self):
        return (self.base / "verification.txt").read_text(encoding="utf-8")

    def test_import_is_inert_on_windows_and_other_platforms(self):
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), \
                    patch.object(subprocess, "run", side_effect=AssertionError("import launched a check")), \
                    redirect_stdout(io.StringIO()) as output:
                runpy.run_path(str(self.script), run_name="verification_import_test")
                self.assertEqual(output.getvalue(), "")
                self.assertFalse((self.base / "verification.txt").exists())

    def test_suite_longer_than_one_minute_succeeds_with_separate_diagnostic_budgets(self):
        def runner(command, *, timeout, **kwargs):
            elapsed = 90 if command[1:4] == ["-m", "unittest", "discover"] else 1
            if elapsed > timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            return subprocess.CompletedProcess(command, 0, "check passed", "")

        code, output, child = self.run_cli(runner)
        self.assertEqual(code, 0)
        expected_commands = [
            [sys.executable, "-m", "unittest", "discover", "-s", str(self.base), "-p", "test_*.py", "-v"],
            [sys.executable, str(self.base / "DrawBot.py"), "--self-test"],
            [sys.executable, str(self.base / "DrawBot.py"), "--smoke-test"],
            [sys.executable, str(self.base / "MouseProbe.py"), "--diagnostics-only"],
        ]
        self.assertEqual([call.args[0] for call in child.call_args_list], expected_commands)
        self.assertEqual([call.kwargs["timeout"] for call in child.call_args_list], [1800, 60, 60, 60])
        for call in child.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.base)
            self.assertTrue(call.kwargs["capture_output"])
            self.assertTrue(call.kwargs["text"])
        self.assertIn("PASSED: startup and logic.", self.report())
        self.assertIn(f"Report: {self.base / 'verification.txt'}", output)

    def test_nonzero_exit_stops_checks_and_preserves_failure_output(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 7, "failing assertion", "traceback details")

        code, output, child = self.run_cli(runner)
        self.assertEqual(code, 1)
        self.assertEqual(child.call_count, 1)
        report = self.report()
        self.assertIn("exit 7", report)
        self.assertIn("failing assertion", report)
        self.assertIn("traceback details", report)
        self.assertIn("FAILED: read the errors above.", output)

    def test_diagnostic_timeout_remains_bounded_and_stops_later_steps(self):
        def runner(command, *, timeout, **kwargs):
            if "--self-test" in command:
                raise subprocess.TimeoutExpired(command, timeout)
            return subprocess.CompletedProcess(command, 0, "suite passed", "")

        code, _, child = self.run_cli(runner)
        self.assertEqual(code, 1)
        self.assertEqual(child.call_count, 2)
        self.assertEqual(child.call_args.kwargs["timeout"], 60)
        self.assertIn("suite passed", self.report())
        self.assertIn("exceeded 60 seconds", self.report())

    def test_full_suite_timeout_reports_its_actual_budget(self):
        def runner(command, *, timeout, **kwargs):
            raise subprocess.TimeoutExpired(command, timeout)

        code, _, child = self.run_cli(runner)
        self.assertEqual(code, 1)
        self.assertEqual(child.call_count, 1)
        self.assertEqual(child.call_args.kwargs["timeout"], 1800)
        self.assertIn("exceeded 1800 seconds", self.report())

    def test_non_windows_cli_exits_before_running_checks_or_writing_report(self):
        code, _, child = self.run_cli(AssertionError("unexpected process"), platform="linux")
        self.assertEqual(code, "Run this check on Windows.")
        child.assert_not_called()
        self.assertFalse((self.base / "verification.txt").exists())


if __name__ == "__main__":
    unittest.main()
