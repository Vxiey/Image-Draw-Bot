import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ReleaseCandidateHardening import (
    EXPECTED_REPOSITORY, ReleaseGateError, collect_source_gate_errors, find_one_shot_source_files,
    run_lifecycle_soak, run_profile_isolation_soak, validate_windows_zip,
    verify_checksum_file, validate_manifest,
)


class Step30ReleaseCandidateHardeningTests(unittest.TestCase):
    def test_expected_repository_is_current(self):
        self.assertEqual(EXPECTED_REPOSITORY, 'Vxiey/Image-Draw-Bot')

    def test_lifecycle_soak_finishes_disarmed(self):
        result = run_lifecycle_soak(2500)
        self.assertEqual(result['cycles'], 2500)
        self.assertFalse(result['final_state']['armed'])
        self.assertFalse(result['final_state']['pending'])
        self.assertIsNone(result['final_state']['activity'])

    def test_profile_isolation_soak_is_stable(self):
        result = run_profile_isolation_soak(250)
        self.assertGreaterEqual(result['profiles'], 1)
        self.assertEqual(result['profiles'], result['unique_keys'])

    def _fake_root(self, root: Path, *, updater_repo='Vxiey/Image-Draw-Bot', channel='beta'):
        (root/'.github/workflows').mkdir(parents=True)
        (root/'installer').mkdir(parents=True)
        (root/'version_info.txt').write_text(
            "filevers=(1,0,131,0)\nprodvers=(1,0,131,0)\n"
            "StringStruct('FileVersion', '1.0.131')\n"
            "StringStruct('ProductVersion', '1.0.131')\n", encoding='utf-8')
        (root/'installer/ImageDrawBot.iss').write_text(
            '#define MyAppVersion "1.0.131-beta"\n'
            'AppId={{6A4AD303-4F16-4ED7-A9AF-5B912352D83E}\nPrivilegesRequired=lowest\n', encoding='utf-8')
        (root/'UpdateCenter.py').write_text(f'GITHUB_REPOSITORY = "{updater_repo}"\n', encoding='utf-8')
        (root/'build_release.py').write_text('run_source_release_gate\nvalidate_windows_release\n', encoding='utf-8')
        (root/'RELEASE-NOTES-v1.0.131-beta.md').write_text('Release notes\n', encoding='utf-8')
        (root/'.github/workflows/build-windows.yml').write_text(
            'ReleaseCandidateHardening.py --source-gate\n'
            'Validate silent installer round-trip\n'
            '$version = python -c "from Version import APP_VERSION; print(APP_VERSION)"\n'
            '$notes = "RELEASE-NOTES-v$version.md"\n'
            'gh release create --notes-file $notes\n', encoding='utf-8')

    def test_source_gate_detects_stale_update_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self._fake_root(root, updater_repo='yesverynice12/Image-Draw-Bot')
            errors=collect_source_gate_errors(root, app_version='1.0.131-beta', file_version='1.0.131', channel='beta')
            self.assertTrue(any('legacy GitHub repository' in e or 'UpdateCenter' in e for e in errors))

    def test_source_gate_detects_channel_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self._fake_root(root)
            errors=collect_source_gate_errors(root, app_version='1.0.131-beta', file_version='1.0.131', channel='rc')
            self.assertTrue(any('requires BUILD_CHANNEL' in e for e in errors))

    def test_source_gate_accepts_consistent_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self._fake_root(root)
            errors=collect_source_gate_errors(root, app_version='1.0.131-beta', file_version='1.0.131', channel='beta')
            self.assertEqual(errors, [])

    def test_source_gate_detects_missing_release_notes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self._fake_root(root)
            (root/'RELEASE-NOTES-v1.0.131-beta.md').unlink()
            errors=collect_source_gate_errors(root, app_version='1.0.131-beta', file_version='1.0.131', channel='beta')
            self.assertTrue(any("release notes: missing" in e for e in errors))

    def test_source_gate_accepts_static_release_notes_wiring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self._fake_root(root)
            (root/'.github/workflows/build-windows.yml').write_text(
                'ReleaseCandidateHardening.py --source-gate\n'
                'Validate silent installer round-trip\n'
                '$notes = "RELEASE-NOTES-v1.0.131-beta.md"\n'
                'gh release create --notes-file $notes\n', encoding='utf-8')
            errors=collect_source_gate_errors(root, app_version='1.0.131-beta', file_version='1.0.131', channel='beta')
            self.assertEqual(errors, [])

    def test_source_hygiene_detects_one_shot_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'step99_patch_once.py').write_text('x=1\n', encoding='utf-8')
            (root/'.github/workflows').mkdir(parents=True)
            (root/'.github/workflows/release-once.yml').write_text('name: temp\n', encoding='utf-8')
            found = find_one_shot_source_files(root)
            self.assertIn('step99_patch_once.py', found)
            self.assertIn('.github/workflows/release-once.yml', found)

    def test_manifest_rejects_stale_hash_and_metadata(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root/'ImageDrawBot-1.0.131-beta-Windows-x64.zip'
            artifact.write_bytes(b'payload')
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = root/'manifest.json'
            payload = {
                'schema': 1, 'app': 'Image Draw Bot', 'version': '1.0.131-beta',
                'file_version': '1.0.131', 'channel': 'beta', 'architecture': 'windows-x64',
                'artifacts': [{'name': artifact.name, 'type': 'windows-zip', 'sha256': digest, 'bytes': artifact.stat().st_size}],
            }
            manifest.write_text(json.dumps(payload), encoding='utf-8')
            validate_manifest(manifest, app_version='1.0.131-beta', expected_files=[artifact.name],
                              file_version='1.0.131', channel='beta', base_dir=root)
            payload['channel'] = 'rc'
            manifest.write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaises(ReleaseGateError):
                validate_manifest(manifest, app_version='1.0.131-beta', expected_files=[artifact.name],
                                  file_version='1.0.131', channel='beta', base_dir=root)

    def test_windows_zip_rejects_test_and_runtime_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.zip'
            with zipfile.ZipFile(path,'w') as zf:
                zf.writestr('ImageDrawBot/ImageDrawBot.exe', b'MZdummy')
                zf.writestr('ImageDrawBot/test_leak.py', 'bad')
            with self.assertRaises(ReleaseGateError):
                validate_windows_zip(path)

    def test_windows_zip_accepts_clean_mz_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'good.zip'
            with zipfile.ZipFile(path,'w') as zf:
                zf.writestr('ImageDrawBot/ImageDrawBot.exe', b'MZdummy')
                zf.writestr('ImageDrawBot/README.md', 'ok')
            result=validate_windows_zip(path)
            self.assertEqual(result['integrity'],'PASS')
            self.assertEqual(result['entries'],2)

    def test_windows_zip_rejects_archived_source_and_unused_native_extensions(self):
        paths = (
            'ImageDrawBot/_internal/history/archives/legacy-source-1.0.58-beta.zip',
            'ImageDrawBot/_internal/docs/history/archives/legacy-source-1.0.61-beta.zip',
            'ImageDrawBot/_internal/tkinterdnd2/tkdnd/win-x86/libtkdnd2.9.5.dll',
            'ImageDrawBot/_internal/tkinterdnd2/tkdnd/win-arm64/pkgIndex.tcl',
            'ImageDrawBot/_internal/tkinterdnd2/tkdnd/linux-x64/libtkdnd.so',
            'ImageDrawBot/_internal/tkinterdnd2/tkdnd/osx-arm64/libtkdnd.dylib',
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bundle.zip'
            for leaked_path in paths:
                with self.subTest(path=leaked_path):
                    with zipfile.ZipFile(path, 'w') as archive:
                        archive.writestr('ImageDrawBot/ImageDrawBot.exe', b'MZfixture')
                        archive.writestr(leaked_path, b'unused fixture')
                    with self.assertRaisesRegex(ReleaseGateError, 'leaked into Windows ZIP'):
                        validate_windows_zip(path)

    def test_windows_zip_keeps_help_and_required_x64_drag_and_drop_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bundle.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('ImageDrawBot/ImageDrawBot.exe', b'MZfixture')
                archive.writestr('ImageDrawBot/_internal/docs/history/README.md', 'History')
                archive.writestr('ImageDrawBot/_internal/docs/PAINT-AUTOMATIC-PREPARATION.md', 'Help')
                for platform_dir in ('win-x64', 'win-x64-tcl9'):
                    prefix = f'ImageDrawBot/_internal/tkinterdnd2/tkdnd/{platform_dir}/'
                    archive.writestr(prefix + 'pkgIndex.tcl', 'package ifneeded tkdnd')
                    archive.writestr(prefix + 'libtkdnd.dll', b'MZfixture')
            self.assertEqual(validate_windows_zip(path)['integrity'], 'PASS')

    def test_checksum_verification_detects_tampering(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); target=root/'a.bin'; target.write_bytes(b'hello')
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            sums=root/'sum.txt'; sums.write_text(f'{digest}  a.bin\n',encoding='utf-8')
            self.assertEqual(verify_checksum_file(sums)['verified'],1)
            target.write_bytes(b'changed')
            with self.assertRaises(ReleaseGateError):
                verify_checksum_file(sums)

    def test_repository_files_have_step30_hooks(self):
        root=Path(__file__).resolve().parent
        self.assertIn('run_source_release_gate', (root/'build_release.py').read_text(encoding='utf-8'))
        self.assertIn('ReleaseCandidateHardening.py --source-gate', (root/'.github/workflows/build-windows.yml').read_text(encoding='utf-8'))
        self.assertIn('Vxiey/Image-Draw-Bot', (root/'UpdateCenter.py').read_text(encoding='utf-8'))

    def test_release_version_is_v10131_beta(self):
        from Version import APP_VERSION, FILE_VERSION, BUILD_CHANNEL
        self.assertEqual(APP_VERSION,'1.0.146-rc4')
        self.assertEqual(FILE_VERSION,'1.0.146')
        self.assertEqual(BUILD_CHANNEL,'rc')


if __name__ == '__main__':
    unittest.main()
