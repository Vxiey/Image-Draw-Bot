"""A public build owns its mutable environment and outputs until publication."""
from contextlib import contextmanager
import multiprocessing
from pathlib import Path
import threading
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

import BuildEnvironment as environment
import build_exe
import build_release
from ReleaseCandidateHardening import validate_windows_release
from test_v148_platform_batch08_build import BuildFixture


CPU_BYTES = b'MZ synthetic first CPU application'
GPU_BYTES = b'MZ synthetic second CUDA application'


def _held_public_build(root, entry, ready, proceed, result, fail):
    """Run the real public pipeline; replace only external tool processes."""
    try:
        fixture = BuildFixture(Path(root))
        fixture.application = CPU_BYTES
        original = fixture.run
        held = False

        def run(command, **options):
            nonlocal held
            command = list(map(str, command))
            answer = original(command, **options)
            boundary = ('PyInstaller' in command if entry == 'exe' else
                        Path(command[0]).name == 'ImageDrawBot.exe')
            if boundary and not held:
                held = True
                ready.set()
                if not proceed.wait(20):
                    raise TimeoutError('The test did not release its build boundary.')
                if fail:
                    raise OSError('injected external build failure')
            return answer

        fixture.run = run
        with fixture.active(release_args=['--skip-tests']):
            code = build_release.main() if entry == 'release' else build_exe.main([])
        result.send(('ok', code))
    except BaseException as error:
        result.send(('error', type(error).__name__, str(error)))
    finally:
        result.close()


@contextmanager
def held_build(root, entry, *, fail=False):
    # Spawn exercises a genuinely independent Python owner on Linux and Windows.
    context = multiprocessing.get_context('spawn')
    ready, proceed = context.Event(), context.Event()
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_held_public_build,
                              args=(str(root), entry, ready, proceed, send, fail))
    process.start()
    send.close()
    try:
        if not ready.wait(15):
            detail = receive.recv() if receive.poll() else f'exit={process.exitcode}'
            raise AssertionError(f'Public build did not reach the test boundary: {detail!r}')
        yield process, proceed, receive
    finally:
        # A terminated process can leave an Event's internal semaphore locked.
        # Do not touch that shared synchronization object after it has exited.
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


def application_in_zip(root):
    path = Path(root)/'release'/f'ImageDrawBot-{build_release.APP_VERSION}-Windows-x64.zip'
    with zipfile.ZipFile(path) as archive:
        member = next(name for name in archive.namelist() if name.endswith('/ImageDrawBot.exe'))
        return archive.read(member)


class WorkspaceBuildTests(unittest.TestCase):
    def test_second_public_entry_cannot_mutate_a_build_owned_by_another_process(self):
        for first in ('release', 'exe'):
            with self.subTest(first=first), TemporaryDirectory(prefix='build source with spaces ') as folder:
                root = Path(folder).resolve()
                fixture = BuildFixture(root)
                fixture.application = GPU_BYTES
                with held_build(root, first) as (process, proceed, result):
                    with fixture.active(release_args=['--skip-tests']), \
                            patch.object(build_exe, '__file__', str(root/'build/../build_exe.py')), \
                            patch.object(build_release, 'BASE', root/'build/..'):
                        with self.assertRaisesRegex(SystemExit, 'Another build is already using'):
                            if first == 'release':
                                build_exe.main(['--gpu'])
                            else:
                                build_release.main()
                    self.assertFalse(fixture.calls, 'A rejected contender must not run pip or PyInstaller.')
                    self.assertEqual((root/'dist/ImageDrawBot/ImageDrawBot.exe').read_bytes(), CPU_BYTES)
                    proceed.set()
                    process.join(15)
                    self.assertFalse(process.is_alive())
                    self.assertTrue(result.poll(2))
                    self.assertEqual(result.recv()[0], 'ok')
                if first == 'release':
                    validate_windows_release(root/'release', require_installer=False)
                    self.assertEqual(application_in_zip(root), CPU_BYTES)
                # Normal completion releases the same persistent sidecar.
                with fixture.active():
                    build_exe.main(['--gpu'])
                self.assertEqual((root/'dist/ImageDrawBot/ImageDrawBot.exe').read_bytes(), GPU_BYTES)

    def test_original_reentrant_public_call_cannot_replace_cpu_bytes_with_cuda_bytes(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            fixture = BuildFixture(root)
            original = fixture.run
            rejected = []

            def run(command, **options):
                command = list(map(str, command))
                if 'PyInstaller' in command:
                    fixture.application = GPU_BYTES if '--exclude-module' not in command else CPU_BYTES
                answer = original(command, **options)
                if Path(command[0]).name == 'ImageDrawBot.exe':
                    try:
                        build_exe.main(['--gpu'])
                    except SystemExit as error:
                        rejected.append(str(error))
                return answer

            fixture.run = run
            with fixture.active(release_args=['--skip-tests']):
                self.assertEqual(build_release.main(), 0)
            self.assertEqual(len(rejected), 1)
            self.assertIn('Another build is already using', rejected[0])
            self.assertEqual(sum('PyInstaller' in command for command, _ in fixture.calls), 1)
            validate_windows_release(root/'release', require_installer=False)
            self.assertEqual(application_in_zip(root), CPU_BYTES)

    def test_failed_public_owner_releases_the_workspace_for_a_complete_retry(self):
        with TemporaryDirectory(prefix='failed build ') as folder:
            root = Path(folder).resolve()
            fixture = BuildFixture(root)
            with held_build(root, 'release', fail=True) as (process, proceed, result):
                proceed.set()
                process.join(15)
                self.assertFalse(process.is_alive())
                self.assertTrue(result.poll(2))
                self.assertEqual(result.recv(), ('error', 'OSError', 'injected external build failure'))
            self.assertFalse(list((root/'release').glob('*.zip')))
            with fixture.active(release_args=['--skip-tests']):
                self.assertEqual(build_release.main(), 0)
            validate_windows_release(root/'release', require_installer=False)
            self.assertEqual(application_in_zip(root), fixture.application)

    def test_terminated_owner_has_no_permanent_stale_lock(self):
        with TemporaryDirectory(prefix='terminated build ') as folder:
            root = Path(folder).resolve()
            fixture = BuildFixture(root)
            with held_build(root, 'exe') as (process, _proceed, _result):
                # The fixture has no external child tool: it is stopped inside
                # the mocked tool boundary. This asserts OS-lock lifetime, not
                # automatic cleanup of a real orphaned pip/PyInstaller process.
                process.terminate()
                process.join(15)
                self.assertFalse(process.is_alive())
            self.assertTrue((root/'build/.workspace-build.lock').is_file())
            with fixture.active(release_args=['--skip-tests']):
                self.assertEqual(build_release.main(), 0)
            validate_windows_release(root/'release', require_installer=False)

    def test_internal_apis_require_the_current_thread_and_matching_workspace(self):
        with TemporaryDirectory(prefix='owned workspace ') as folder, TemporaryDirectory() as other:
            root = Path(folder).resolve()
            prepared = environment.Builder(root/'python.exe', root, {})
            with patch.object(environment.subprocess, 'run') as process:
                with self.assertRaisesRegex(environment.BuildEnvironmentError, 'active workspace'):
                    environment.prepare_builder(root)
                with self.assertRaisesRegex(environment.BuildEnvironmentError, 'active workspace'):
                    build_exe.build_application(root, prepared)
                process.assert_not_called()
                with environment.build_workspace(root):
                    environment.require_build_workspace(root/'build/..')
                    errors = []
                    def contend():
                        with environment.build_workspace(root):
                            pass
                    def other_thread():
                        for action in (lambda: environment.require_build_workspace(root),
                                       contend):
                            try:
                                action()
                            except environment.BuildEnvironmentError as error:
                                errors.append(str(error))
                    thread = threading.Thread(target=other_thread, daemon=True)
                    thread.start(); thread.join(3)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(len(errors), 2)
                    wrong = environment.Builder(prepared.python, Path(other).resolve(), {})
                    with self.assertRaisesRegex(environment.BuildEnvironmentError, 'different source workspace'):
                        build_exe.build_application(root, wrong)
                    with environment.build_workspace(Path(other)):
                        environment.require_build_workspace(Path(other))
                process.assert_not_called()
            with self.assertRaisesRegex(environment.BuildEnvironmentError, 'active workspace'):
                environment.require_build_workspace(root)

    def test_release_owner_spans_tests_signing_archives_gate_and_publication(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            fixture = BuildFixture(root)
            original = fixture.run
            stages = []
            def run(command, **options):
                environment.require_build_workspace(root)
                stages.append('process')
                return original(command, **options)
            fixture.run = run
            def guarded(label, callback):
                def call(*args, **kwargs):
                    environment.require_build_workspace(root)
                    stages.append(label)
                    return callback(*args, **kwargs)
                return call
            with fixture.active(release_args=['--installer', '--signed']), \
                    patch('CodeSigning.signing_configuration', return_value=('tool', 'AB'*20)), \
                    patch('CodeSigning.validate_certificate'), \
                    patch('CodeSigning.sign_distribution', side_effect=guarded('sign', lambda *_: None)), \
                    patch('CodeSigning.inno_arguments', return_value=[]), \
                    patch('CodeSigning.verify', side_effect=guarded('verify', lambda *_: True)), \
                    patch.object(build_release, 'zip_onedir', side_effect=guarded('zip', build_release.zip_onedir)), \
                    patch.object(build_release, 'validate_windows_release', side_effect=guarded('gate', build_release.validate_windows_release)), \
                    patch.object(build_release, 'publish_release', side_effect=guarded('publish', build_release.publish_release)):
                self.assertEqual(build_release.main(), 0)
            self.assertTrue({'process', 'sign', 'verify', 'zip', 'gate', 'publish'} <= set(stages))
            self.assertEqual(stages[-1], 'publish')
            validate_windows_release(root/'release')
            with self.assertRaises(environment.BuildEnvironmentError):
                environment.require_build_workspace(root)


if __name__ == '__main__':
    unittest.main()
