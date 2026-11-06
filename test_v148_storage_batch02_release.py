import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import build_exe
import build_release as builder
import CodeSigning as signing
import ReleaseCandidateHardening as gate
import ReleasePackage as source
import test_build_documentation_data as build_fixtures
import test_step30_release_candidate_hardening_v10129rc1 as gate_fixtures


class StorageReleaseBatch02Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dist = self.root / 'dist'
        self.dist.mkdir()
        (self.dist / 'ImageDrawBot.exe').write_bytes(b'MZ synthetic fixture')
        (self.dist / 'asset.txt').write_text('unchanged asset')
        self.archive = self.root / 'application.zip'

    def test_failed_zip_creation_preserves_previous_output_and_cleans_staging(self):
        self.archive.write_bytes(b'previous complete ZIP')
        with patch.object(builder, 'DIST', self.dist), \
             patch.object(builder.shutil, 'copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                builder.zip_onedir(self.archive)
        self.assertEqual(self.archive.read_bytes(), b'previous complete ZIP')
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['application.zip', 'dist'])

    def test_runtime_zip_is_independent_of_checkout_timestamps(self):
        with patch.object(builder, 'DIST', self.dist):
            builder.zip_onedir(self.archive)
            first = self.archive.read_bytes()
            for path in self.dist.iterdir():
                os.utime(path, (1_700_000_000, 1_700_000_000))
            builder.zip_onedir(self.archive)
        self.assertEqual(self.archive.read_bytes(), first)
        self.assertEqual(gate.validate_windows_zip(self.archive)['integrity'], 'PASS')

    def test_zip_preflight_rejects_external_file_links_before_any_compression(self):
        outside = self.root / 'private.txt'
        outside.write_text('synthetic secret outside distribution')
        try:
            (self.dist / 'linked.txt').symlink_to(outside)
        except OSError:
            self.skipTest('file links are unavailable')
        with patch.object(builder, 'DIST', self.dist), patch.object(builder.shutil, 'copyfileobj') as compress:
            with self.assertRaisesRegex(ValueError, 'link or non-regular'):
                builder.zip_onedir(self.archive)
            compress.assert_not_called()
        self.assertFalse(self.archive.exists())

    def test_zip_preflight_rejects_windows_junction_metadata(self):
        junction = self.dist / 'junction'
        junction.mkdir()
        original = Path.lstat
        def metadata(path):
            value = original(path)
            if path == junction:
                return SimpleNamespace(st_mode=value.st_mode, st_reparse_tag=0xA0000003)
            return value
        with patch.object(builder, 'DIST', self.dist), patch.object(Path, 'lstat', metadata):
            with self.assertRaisesRegex(ValueError, 'link or non-regular'):
                builder.zip_onedir(self.archive)

    def test_dependency_build_failure_does_not_delete_completed_release_assets(self):
        release = self.root / 'release'
        release.mkdir()
        old = release / f'ImageDrawBot-{builder.APP_VERSION}-Windows-x64.zip'
        old.write_bytes(b'old complete release')
        report = SimpleNamespace(as_dict=lambda: {})
        with patch.object(builder, 'RELEASE', release), patch.object(builder.sys, 'platform', 'win32'), \
             patch.object(builder.sys, 'version_info', (3, 12, 0)), \
             patch.object(builder.sys, 'argv', ['build_release.py', '--skip-tests']), \
             patch.dict(builder.os.environ, {'GITHUB_REF_TYPE': '', 'GITHUB_REF_NAME': ''}), \
             patch.object(builder, 'run_source_release_gate', return_value=report), \
             patch.object(builder, 'run', side_effect=subprocess.CalledProcessError(1, ['pip'])), \
             patch('builtins.print'):
            with self.assertRaises(subprocess.CalledProcessError):
                builder.main()
        self.assertEqual(old.read_bytes(), b'old complete release')

    def test_standard_and_cuda_collection_are_explicit_even_with_a_reused_environment(self):
        for gpu in (False, True):
            with self.subTest(gpu=gpu), tempfile.TemporaryDirectory() as td:
                with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded executable read')):
                    command, _ = build_fixtures.BuildDocumentationDataTests().build_command(Path(td), gpu=gpu)
                pairs = set(zip(command, command[1:]))
                self.assertIn(('--collect-all', 'pyopencl'), pairs)
                for package in ('cupy', 'cupyx'):
                    self.assertEqual(('--exclude-module', package) in pairs, not gpu)
                    self.assertEqual(('--collect-all', package) in pairs, gpu)

    def test_documentation_junction_is_not_walked_or_bundled(self):
        docs = self.root / 'docs'
        docs.mkdir()
        linked = docs / 'external'
        linked.mkdir()
        (linked / 'private.md').write_text('external text')
        original = Path.lstat
        def metadata(path):
            value = original(path)
            return SimpleNamespace(st_mode=value.st_mode, st_reparse_tag=0xA0000003) if path == linked else value
        with patch.object(Path, 'lstat', metadata):
            self.assertEqual(build_exe.documentation_data(self.root), [])

    def test_source_gate_requires_consistent_app_and_numeric_installer_versions(self):
        fixture = self.root / 'source'
        fixture.mkdir()
        gate_fixtures.Step30ReleaseCandidateHardeningTests()._fake_root(fixture)
        installer = fixture / 'installer/ImageDrawBot.iss'
        installer.write_text(installer.read_text().replace('VersionInfoVersion=1.0.131.0',
                                                         'VersionInfoVersion=1.0.130.0'))
        errors = gate.collect_source_gate_errors(fixture, app_version='1.0.131-beta',
                                                file_version='1.0.131', channel='beta')
        self.assertTrue(any('VersionInfoVersion' in error for error in errors))
        errors = gate.collect_source_gate_errors(fixture, app_version='1.0.131-beta',
                                                file_version='1.0.130', channel='beta')
        self.assertTrue(any('APP_VERSION base' in error for error in errors))

    def test_forbidden_bundle_entries_fail_before_archive_decompression(self):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('ImageDrawBot/ImageDrawBot.exe', b'MZ fixture')
            archive.writestr('ImageDrawBot/docs/history/archives/private.zip', b'old source archive')
        with patch.object(zipfile.ZipFile, 'testzip', side_effect=AssertionError('unnecessary decompression')):
            with self.assertRaisesRegex(gate.ReleaseGateError, 'leaked'):
                gate.validate_windows_zip(self.archive)

    def test_manifest_cannot_silently_omit_a_requested_missing_artifact(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text('old valid manifest')
        with self.assertRaisesRegex(ValueError, 'missing or linked'):
            source.write_release_manifest(self.root, manifest, [self.root / 'missing.zip'])
        self.assertEqual(manifest.read_text(), 'old valid manifest')

    def test_certificate_probe_uses_os_resolved_powershell_without_path_lookup(self):
        system = self.root / 'TrustedSystem32'
        with patch.object(signing, 'system_directory', return_value=system), \
             patch.object(signing.subprocess, 'run') as run:
            signing.validate_certificate(('signtool', 'AB' * 20))
        self.assertEqual(run.call_args.args[0][0], str(system / 'WindowsPowerShell/v1.0/powershell.exe'))
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        with patch.object(signing.subprocess, 'run') as run:
            with self.assertRaises(signing.SigningError):
                signing.validate_certificate(('signtool', 'bad; expression'))
            run.assert_not_called()

    def test_unreadable_signing_subtree_aborts_before_any_signature_change(self):
        def failed_walk(*args, **kwargs):
            yield str(self.dist), ['private'], ['ImageDrawBot.exe']
            kwargs['onerror'](PermissionError('subtree unavailable'))
        (self.dist / 'private').mkdir()
        with patch.object(signing.os, 'walk', side_effect=failed_walk), \
             patch.object(signing, 'sign_file') as sign, patch.object(signing, 'verify') as verify:
            with self.assertRaisesRegex(signing.SigningError, 'could not be inspected'):
                signing.sign_distribution(self.dist, ('tool', 'AB' * 20))
            sign.assert_not_called()
            verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
