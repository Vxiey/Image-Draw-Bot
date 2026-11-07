"""Whole release sets survive compilation, signing, validation and move faults."""
from contextlib import ExitStack
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import build_release as release
import ReleaseCandidateHardening as gate
import ReleasePublication as publication
import test_v148_platform_batch08_build as builds


def inventory(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir()
            if path.is_file() and not path.name.startswith('.release-publication')}


class CoherentReleaseTests(unittest.TestCase):
    def fixture(self, root, *, gpu=False, installer=True):
        fixture = builds.BuildFixture(root)
        arguments = ['--skip-tests'] + (['--gpu'] if gpu else ['--installer'] if installer else [])
        with fixture.active(release_args=arguments):
            self.assertEqual(release.main(), 0)
        fixture.application = b'MZ new synthetic application bytes'
        fixture.installer = b'MZ new synthetic installer bytes'
        return fixture

    def assert_no_workspaces(self, directory):
        self.assertFalse(list(directory.glob('.release-stage-*')))
        self.assertFalse(list(directory.glob('.release-backup-*')))

    def test_every_prepublication_failure_preserves_the_previous_gate_valid_set(self):
        for failure in ('freeze', 'installer', 'signature', 'checksum', 'manifest', 'gate'):
            with self.subTest(failure=failure), TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                fixture = self.fixture(root)
                output = root/'release'
                previous = inventory(output)
                with ExitStack() as stack:
                    arguments = ['--skip-tests', '--installer']
                    if failure in ('freeze', 'installer'):
                        fixture.fail_at = failure
                    elif failure == 'signature':
                        arguments.append('--signed')
                        stack.enter_context(patch('CodeSigning.signing_configuration', return_value=('tool', 'AB'*20)))
                        stack.enter_context(patch('CodeSigning.validate_certificate'))
                        stack.enter_context(patch('CodeSigning.sign_distribution'))
                        stack.enter_context(patch('CodeSigning.inno_arguments', return_value=[]))
                        stack.enter_context(patch('CodeSigning.verify', return_value=False))
                    elif failure in ('checksum', 'manifest'):
                        write = release.atomic_write_text
                        def failing_write(path, text, **kwargs):
                            if str(path).endswith('SHA256.txt' if failure == 'checksum' else 'manifest.json'):
                                raise OSError('injected metadata publication failure')
                            return write(path, text, **kwargs)
                        stack.enter_context(patch.object(release, 'atomic_write_text', side_effect=failing_write))
                    else:
                        stack.enter_context(patch.object(release, 'validate_windows_release',
                                                       side_effect=gate.ReleaseGateError('injected final gate failure')))
                    publish = stack.enter_context(patch.object(release, 'publish_release', wraps=release.publish_release))
                    stack.enter_context(fixture.active(release_args=arguments))
                    with self.assertRaises((OSError, SystemExit, subprocess.CalledProcessError, gate.ReleaseGateError)):
                        release.main()
                    publish.assert_not_called()
                self.assertEqual(inventory(output), previous)
                gate.validate_windows_release(output)
                self.assert_no_workspaces(output)

    def test_each_backup_or_candidate_move_failure_rolls_back_all_previous_files(self):
        # Four previous files, four new files: fail each actual publication move
        # once while allowing its compensating moves to restore the old set.
        for fail_at in range(1, 9):
            with self.subTest(move=fail_at), TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                fixture = self.fixture(root)
                output = root/'release'
                previous = inventory(output)
                move = publication._replace_with_retry
                calls = 0
                def failing_move(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == fail_at:
                        raise PermissionError('injected release move failure')
                    return move(source, destination)
                with fixture.active(release_args=['--skip-tests', '--installer']), \
                        patch.object(publication, '_replace_with_retry', side_effect=failing_move):
                    with self.assertRaisesRegex(PermissionError, 'injected release move failure'):
                        release.main()
                self.assertEqual(inventory(output), previous)
                gate.validate_windows_release(output)
                self.assert_no_workspaces(output)

    def test_failed_new_installer_publication_restores_its_previous_absence(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            fixture = self.fixture(root, installer=False)
            output = root/'release'
            previous = inventory(output)
            move = publication._replace_with_retry
            def failing_move(source, destination):
                if Path(source).parent.name.startswith('.release-stage-') and Path(source).name.endswith('manifest.json'):
                    raise OSError('injected last candidate failure')
                return move(source, destination)
            with fixture.active(release_args=['--skip-tests', '--installer']), \
                    patch.object(publication, '_replace_with_retry', side_effect=failing_move):
                with self.assertRaisesRegex(OSError, 'injected last candidate failure'):
                    release.main()
            self.assertEqual(inventory(output), previous)
            self.assertFalse(list(output.glob('*-Setup.exe')))
            gate.validate_windows_release(output, require_installer=False)
            self.assert_no_workspaces(output)

    def test_success_retires_only_obsolete_variants_of_this_exact_version(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            fixture = self.fixture(root, gpu=True, installer=False)
            output = root/'release'
            unrelated = output/f'ImageDrawBot-{release.APP_VERSION}-my-notes.txt'
            older = output/'ImageDrawBot-0.0.1-Windows-x64.zip'
            unrelated.write_bytes(b'user notes'); older.write_bytes(b'old version')
            with fixture.active(release_args=['--skip-tests', '--installer']):
                self.assertEqual(release.main(), 0)
            gate.validate_windows_release(output)
            self.assertFalse((output/f'ImageDrawBot-{release.APP_VERSION}-Windows-x64-CUDA.zip').exists())
            self.assertEqual(unrelated.read_bytes(), b'user notes')
            self.assertEqual(older.read_bytes(), b'old version')
            with fixture.active(release_args=['--skip-tests']):
                self.assertEqual(release.main(), 0)
            gate.validate_windows_release(output, require_installer=False)
            self.assertFalse(list(output.glob('*-Setup.exe')))
            self.assertEqual(unrelated.read_bytes(), b'user notes')
            self.assert_no_workspaces(output)

    def test_failed_rollback_preserves_recovery_bytes_and_the_original_error(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            fixture = self.fixture(root)
            output = root/'release'
            name = f'ImageDrawBot-{release.APP_VERSION}-Windows-x64.zip'
            original_zip = (output/name).read_bytes()
            move = publication._replace_with_retry
            primary = PermissionError('injected new installer move failure')
            def failing_move(source, destination):
                source = Path(source)
                if source.parent.name.startswith('.release-stage-') and source.name.endswith('Setup.exe'):
                    raise primary
                if source.parent.name.startswith('.release-backup-') and source.name == name:
                    raise PermissionError('injected blocked rollback')
                return move(source, destination)
            with fixture.active(release_args=['--skip-tests', '--installer']), \
                    patch.object(publication, '_replace_with_retry', side_effect=failing_move):
                with self.assertRaises(PermissionError) as caught:
                    release.main()
            self.assertIs(caught.exception, primary)
            backups = list(output.glob('.release-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0]/name).read_bytes(), original_zip)
            self.assertIn(str(backups[0]), '\n'.join(caught.exception.__notes__))
            self.assertFalse(list(output.glob('.release-stage-*')))

    def test_postcommit_backup_cleanup_failure_keeps_the_new_valid_release(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            fixture = self.fixture(root)
            output = root/'release'
            previous = inventory(output)
            remove_tree = shutil.rmtree
            def failed_cleanup(path, *args, **kwargs):
                if Path(path).name.startswith('.release-backup-'):
                    raise PermissionError('backup is busy')
                return remove_tree(path, *args, **kwargs)
            with fixture.active(release_args=['--skip-tests', '--installer']) as console, \
                    patch.object(shutil, 'rmtree', side_effect=failed_cleanup):
                self.assertEqual(release.main(), 0)
            self.assertNotEqual(inventory(output), previous)
            gate.validate_windows_release(output)
            self.assertIn('Release published; temporary backup cleanup', console.getvalue())
            self.assertEqual(len(list(output.glob('.release-backup-*'))), 1)


if __name__ == '__main__':
    unittest.main()
