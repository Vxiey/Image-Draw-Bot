"""Run the normal unittest CLI with diagnostic stacks when progress stops."""
import faulthandler
import os
import sys
import unittest


def main(stall_seconds=90):
    # Running a file normally puts .github/scripts on sys.path. Discovery and
    # its Windows spawn children need the same import root as python -m unittest.
    sys.path[0] = os.getcwd()
    output = sys.__stderr__

    def arm():
        # This native watchdog works even when an extension holds Python's GIL.
        # exit=False keeps a slow test running and preserves unittest's exit code.
        faulthandler.dump_traceback_later(stall_seconds, repeat=True, file=output, exit=False)

    class ProgressResult(unittest.TextTestResult):
        def startTest(self, test):
            # With -v unittest writes and flushes the active test ID to stderr.
            # A stall dump on that same stream completes the open line in CI.
            super().startTest(test)
            arm()

        def stopTest(self, test):
            super().stopTest(test)
            arm()  # Class/module teardown can stall between individual tests.

    class ProgressRunner(unittest.TextTestRunner):
        resultclass = ProgressResult

    print(f'Running unittest. Thread stacks follow {stall_seconds}s without test progress.',
          file=output, flush=True)
    arm()  # Include module imports and discovery before the first test starts.
    try:
        unittest.main(module=None, testRunner=ProgressRunner)
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    main()
