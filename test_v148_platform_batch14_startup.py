"""Source launchers cannot update a private environment while another uses it."""
from contextlib import contextmanager, redirect_stdout
import io
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import GpuSetupRuntime as policy
import SourceStartup as startup


class StartupFixture:
    """Run the actual startup pipeline; replace only external Python processes."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / '.venv'
        self.python = self.directory / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        self.calls = []
        self.output = io.StringIO()
        self.before = lambda command: None

    def process(self, command, **options):
        command = list(map(str, command))
        self.calls.append(command)
        self.before(command)
        stdout = ''
        if 'venv' in command:
            self.python.parent.mkdir(parents=True, exist_ok=True)
            self.python.write_bytes(b'private interpreter boundary fixture')
        elif command[-1] in (policy._PRIVATE_ENVIRONMENT_PROBE, policy._ENVIRONMENT_PROBE):
            stdout = json.dumps(dict(prefix=str(self.directory), base_prefix=str(self.root / 'base-python'),
                version=[3, 12], user_site=False, site_packages=[str(self.directory / 'Lib/site-packages')],
                frozen=False))
        elif 'config' in command:
            stdout = ''
        elif command[-1] == startup._IMPORT_CHECK or ('-m' in command and 'pip' in command):
            pass
        elif command[-1] == str(self.root / 'DrawBot.py'):
            pass
        elif any(str(self.root / name) in command for name in ('AutoGpuSetup.py', 'AutoUniversalGpuSetup.py')):
            pass
        else:
            raise AssertionError(f'Unexpected startup process: {command}')
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    @contextmanager
    def active(self):
        with patch.object(startup, 'ROOT', self.root), \
             patch.object(startup.subprocess, 'run', side_effect=self.process), \
             redirect_stdout(self.output):
            yield self


def _held_source_start(root, boundary, ready, proceed, result, fail):
    try:
        fixture = StartupFixture(root)
        held = False
        def before(command):
            nonlocal held
            matched = ('eager' in command if boundary == 'install'
                       else command[-1] == str(fixture.root / 'DrawBot.py'))
            if matched and not held:
                held = True
                ready.set()
                if not proceed.wait(20):
                    raise TimeoutError('Source-startup fixture was not released.')
                if fail:
                    raise OSError('injected startup process failure')
        fixture.before = before
        with fixture.active():
            code = startup.main([])
        result.send(('ok', code, fixture.output.getvalue()))
    except BaseException as error:
        result.send(('error', type(error).__name__, str(error)))
    finally:
        result.close()


@contextmanager
def held_startup(root, boundary, *, fail=False):
    context = multiprocessing.get_context('spawn')
    ready, proceed = context.Event(), context.Event()
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_held_source_start,
                              args=(str(root), boundary, ready, proceed, send, fail))
    process.start()
    send.close()
    try:
        if not ready.wait(15):
            detail = receive.recv() if receive.poll() else f'exit={process.exitcode}'
            raise AssertionError(f'Source startup did not reach its external boundary: {detail!r}')
        yield process, proceed, receive
    finally:
        if process.is_alive():
            proceed.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        receive.close()
        process.close()


class SourceStartupSessionTests(unittest.TestCase):
    def root(self):
        temporary = tempfile.TemporaryDirectory(prefix='source startup with spaces ')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        (root / 'DrawBot.py').write_text('# no real application runs in this fixture\n')
        (root / 'requirements.txt').write_text('Pillow>=13\n')
        return root

    def test_competing_launch_and_update_cannot_touch_installing_or_running_environment(self):
        for boundary in ('install', 'application'):
            with self.subTest(boundary=boundary):
                root = self.root()
                with held_startup(root, boundary) as (process, proceed, result):
                    fixture = StartupFixture(root)
                    with fixture.active():
                        self.assertEqual(startup.main(['--update']), 1)
                    self.assertEqual(fixture.calls, [], 'The contender must not run venv, pip, GPU setup or the application.')
                    self.assertIn('already using', fixture.output.getvalue())
                    proceed.set()
                    process.join(10)
                    self.assertFalse(process.is_alive())
                    self.assertTrue(result.poll(2))
                    self.assertEqual(result.recv()[:2], ('ok', 0))
                fixture = StartupFixture(root)
                with fixture.active():
                    self.assertEqual(startup.main([]), 0)
                self.assertTrue(fixture.calls, 'Normal completion must release the stable session lock.')

    def test_failed_owner_releases_session_and_retry_completes_private_setup(self):
        root = self.root()
        with held_startup(root, 'install', fail=True) as (process, proceed, result):
            proceed.set()
            process.join(10)
            self.assertFalse(process.is_alive())
            self.assertTrue(result.poll(2))
            self.assertEqual(result.recv()[:2], ('ok', 1))
        self.assertFalse((root / '.venv/installed-requirements.txt').exists())
        fixture = StartupFixture(root)
        with fixture.active():
            self.assertEqual(startup.main([]), 0)
        self.assertEqual((root / '.venv/installed-requirements.txt').read_bytes(),
                         (root / 'requirements.txt').read_bytes())

    def test_terminated_owner_has_no_permanent_stale_lock(self):
        root = self.root()
        with held_startup(root, 'application') as (process, _, _result):
            # Only the launcher is real here. This does not claim to terminate
            # an orphaned application/pip child when its parent is forcibly killed.
            process.terminate()
            process.join(5)
            self.assertFalse(process.is_alive())
        fixture = StartupFixture(root)
        with fixture.active():
            self.assertEqual(startup.main([]), 0)

    def test_other_checkout_remains_independent_and_resolved_alias_cannot_bypass_owner(self):
        root, separate = self.root(), self.root()
        with held_startup(root, 'application'):
            fixture = StartupFixture(separate)
            with fixture.active():
                self.assertEqual(startup.main([]), 0)
            fixture = StartupFixture(root)
            with fixture.active():
                with self.assertRaisesRegex(policy.SetupEnvironmentError, 'already using'):
                    startup.start_source(root / '.venv' / '..', update=True)
            self.assertEqual(fixture.calls, [])


if __name__ == '__main__':
    unittest.main()
