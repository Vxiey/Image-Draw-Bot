"""Validate release variants using synthetic binaries and real ZIP/hash manifests."""
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import build_release
import ReleaseCandidateHardening as hardening
from Version import APP_VERSION


class ReleaseVariantTests(unittest.TestCase):
    def build_fixture(self, root, *, gpu=False, installer=False):
        dist = root / 'dist/ImageDrawBot'
        release = root / 'release'
        commands = []

        def external_command(command, **kwargs):
            # None of these synthetic files is executable. The production ZIP,
            # checksum, manifest and validation steps run normally around them.
            commands.append(command)
            if len(command) > 1 and command[1] == 'build_exe.py':
                dist.mkdir(parents=True)
                (dist / 'ImageDrawBot.exe').write_bytes(b'MZ synthetic application')
            elif Path(command[0]).name == 'ISCC.exe':
                (release / f'ImageDrawBot-{APP_VERSION}-Windows-x64-Setup.exe').write_bytes(
                    b'MZ synthetic installer'
                )

        argv = ['build_release.py', '--skip-tests']
        if gpu:
            argv.append('--gpu')
        if installer:
            argv.append('--installer')
        report = SimpleNamespace(as_dict=lambda: {'passed': True})
        with patch.object(build_release, 'BASE', root), \
             patch.object(build_release, 'DIST', dist), \
             patch.object(build_release, 'RELEASE', release), \
             patch.object(build_release.sys, 'platform', 'win32'), \
             patch.object(build_release.sys, 'version_info', (3, 12, 0)), \
             patch.object(build_release.sys, 'argv', argv), \
             patch.dict(build_release.os.environ, {'GITHUB_REF_TYPE': '', 'GITHUB_REF_NAME': ''}), \
             patch.object(build_release, 'run_source_release_gate', return_value=report), \
             patch.object(build_release, 'run', side_effect=external_command), \
             patch.object(build_release, 'find_iscc', return_value=root / 'ISCC.exe'), \
             patch.object(build_release, 'validate_windows_release', wraps=hardening.validate_windows_release) as validate, \
             patch('builtins.print'):
            self.assertEqual(build_release.main(), 0)
        validate.assert_called_once_with(release, app_version=APP_VERSION,
                                         require_installer=installer, gpu=gpu)
        return release, commands

    def test_cuda_builder_produces_and_validates_only_the_selected_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            release, commands = self.build_fixture(Path(temporary), gpu=True)
            name = f'ImageDrawBot-{APP_VERSION}-Windows-x64-CUDA.zip'
            self.assertTrue((release / name).is_file())
            self.assertFalse((release / f'ImageDrawBot-{APP_VERSION}-Windows-x64.zip').exists())
            self.assertTrue(any(command[1:] == ['build_exe.py', '--gpu'] for command in commands))
            report = hardening.validate_windows_release(release, gpu=True, require_installer=False)
            self.assertNotIn('installer', report)
            self.assertEqual(report['checksums']['files'], [name])
            self.assertEqual([item['name'] for item in report['manifest']['artifacts']], [name])

    def test_standard_default_still_validates_zip_and_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            release, _ = self.build_fixture(Path(temporary), installer=True)
            report = hardening.validate_windows_release(release)
            self.assertEqual(report['checksums']['verified'], 2)
            self.assertIn('installer', report)
            self.assertEqual(Path(report['zip']['path']).name,
                             f'ImageDrawBot-{APP_VERSION}-Windows-x64.zip')

    def test_standard_ci_zip_only_build_remains_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            release, _ = self.build_fixture(Path(temporary))
            report = hardening.validate_windows_release(release, require_installer=False)
            self.assertNotIn('installer', report)
            self.assertEqual(report['checksums']['verified'], 1)
            with self.assertRaisesRegex(hardening.ReleaseGateError, 'Installer is missing'):
                hardening.validate_windows_release(release)

    def test_selected_variant_never_falls_back_to_the_other_archive(self):
        for existing_gpu in (False, True):
            with self.subTest(existing_gpu=existing_gpu), tempfile.TemporaryDirectory() as temporary:
                release, _ = self.build_fixture(Path(temporary), gpu=existing_gpu)
                with self.assertRaisesRegex(hardening.ReleaseGateError, 'Windows ZIP is missing'):
                    hardening.validate_windows_release(release, gpu=not existing_gpu, require_installer=False)

    def test_cuda_checksum_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            release, _ = self.build_fixture(Path(temporary), gpu=True)
            checksum = release / f'ImageDrawBot-{APP_VERSION}-SHA256.txt'
            text = checksum.read_text(encoding='utf-8')
            checksum.write_text('0' * 64 + text[64:], encoding='utf-8')
            with self.assertRaisesRegex(hardening.ReleaseGateError, 'Checksum mismatch'):
                hardening.validate_windows_release(release, gpu=True, require_installer=False)

    def test_cuda_manifest_cannot_substitute_the_standard_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            release, _ = self.build_fixture(Path(temporary), gpu=True)
            manifest = release / f'ImageDrawBot-{APP_VERSION}-manifest.json'
            payload = json.loads(manifest.read_text(encoding='utf-8'))
            payload['artifacts'][0]['name'] = f'ImageDrawBot-{APP_VERSION}-Windows-x64.zip'
            manifest.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaisesRegex(hardening.ReleaseGateError, 'manifest is missing artifacts'):
                hardening.validate_windows_release(release, gpu=True, require_installer=False)

    def test_gpu_installer_combination_fails_before_any_build_side_effect(self):
        with patch.object(build_release.sys, 'argv', ['build_release.py', '--gpu', '--installer']), \
             patch.object(build_release, 'run_source_release_gate') as gate, \
             patch.object(build_release, '_clean_current_release_outputs') as clean, \
             patch.object(build_release, 'run') as run, \
             patch('sys.stderr', new_callable=StringIO) as error_output:
            with self.assertRaises(SystemExit) as caught:
                build_release.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('CUDA release ships as a ZIP', error_output.getvalue())
        gate.assert_not_called()
        clean.assert_not_called()
        run.assert_not_called()
        with self.assertRaisesRegex(hardening.ReleaseGateError, 'ZIP-only'):
            hardening.validate_windows_release(Path('unused'), gpu=True)

    def test_standalone_validator_has_explicit_cuda_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            release, _ = self.build_fixture(Path(temporary), gpu=True)
            with patch('builtins.print'):
                self.assertEqual(hardening.main(['--release-dir', str(release), '--gpu']), 0)
            with self.assertRaisesRegex(hardening.ReleaseGateError, 'Windows ZIP is missing'):
                hardening.main(['--release-dir', str(release)])

    def test_standalone_gpu_flag_requires_a_release_directory(self):
        with patch('sys.stderr', new_callable=StringIO) as error_output:
            with self.assertRaises(SystemExit) as caught:
                hardening.main(['--gpu'])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('--gpu requires --release-dir', error_output.getvalue())


if __name__ == '__main__':
    unittest.main()
