"""Verifies dependencies and GUI startup without sending mouse input."""
import subprocess
import sys
from pathlib import Path

# Full discovery uses the CI core-check ceiling; startup diagnostics stay short.
FULL_SUITE_TIMEOUT_SECONDS = 30 * 60
DIAGNOSTIC_TIMEOUT_SECONDS = 60


def main() -> int:
    if sys.platform != 'win32':
        raise SystemExit('Run this check on Windows.')
    base = Path(__file__).resolve().parent
    log = []
    commands = [
        (['-m', 'unittest', 'discover', '-s', str(base), '-p', 'test_*.py', '-v'], FULL_SUITE_TIMEOUT_SECONDS),
        ([str(base / 'DrawBot.py'), '--self-test'], DIAGNOSTIC_TIMEOUT_SECONDS),
        ([str(base / 'DrawBot.py'), '--smoke-test'], DIAGNOSTIC_TIMEOUT_SECONDS),
        ([str(base / 'MouseProbe.py'), '--diagnostics-only'], DIAGNOSTIC_TIMEOUT_SECONDS),
    ]
    passed = True
    for arguments, timeout in commands:
        try:
            result = subprocess.run(
                [sys.executable, *arguments], cwd=base, capture_output=True, text=True, timeout=timeout,
            )
            log.append(f'{arguments}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
            if result.returncode:
                passed = False
                break
        except subprocess.TimeoutExpired:
            log.append(f'The check exceeded {timeout} seconds and was stopped.')
            passed = False
            break
    log.append('PASSED: startup and logic. Actual drawing in the target application still needs verification.'
               if passed else 'FAILED: read the errors above.')
    path = base / 'verification.txt'
    path.write_text('\n'.join(log), encoding='utf-8')
    print(log[-1])
    print(f'Report: {path}')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
