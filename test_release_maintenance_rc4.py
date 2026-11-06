"""Synthetic archive and manifest checks; no downloaded or executed binaries."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import warnings
import zipfile

import build_release
import ReleaseCandidateHardening as gate
import ReleasePackage as source


class RuntimeArchiveMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.archive = self.base / 'runtime.zip'

    def write_archive(self, *entries):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w') as output:
                output.writestr('ImageDrawBot/ImageDrawBot.exe', b'MZ synthetic fixture')
                for entry in entries:
                    output.writestr(entry, b'fixture')

    def test_rejects_traversal_absolute_and_windows_special_paths(self):
        for entry in ('ImageDrawBot/../escaped.txt', '/ImageDrawBot/data.txt',
                      'C:/ImageDrawBot/data.txt', 'ImageDrawBot/data:stream',
                      'ImageDrawBot/NUL.txt', 'ImageDrawBot/COM¹.txt',
                      'ImageDrawBot/directory./file', 'ImageDrawBot/file ',
                      'ImageDrawBot//file', 'unexpected-root/file'):
            with self.subTest(entry=entry):
                self.write_archive(entry)
                with self.assertRaises(gate.ReleaseGateError):
                    gate.validate_windows_zip(self.archive)

    def test_rejects_duplicates_under_windows_path_comparison(self):
        for entries in (('ImageDrawBot/ImageDrawBot.exe',),
                        ('ImageDrawBot/imagedrawbot.EXE',),
                        ('ImageDrawBot/data.txt', r'ImageDrawBot\DATA.TXT')):
            with self.subTest(entries=entries):
                self.write_archive(*entries)
                with self.assertRaisesRegex(gate.ReleaseGateError, 'Duplicate Windows ZIP path'):
                    gate.validate_windows_zip(self.archive)

    def test_rejects_a_file_that_is_also_another_entry_parent(self):
        self.write_archive('ImageDrawBot/data', 'ImageDrawBot/data/image.png')
        with self.assertRaisesRegex(gate.ReleaseGateError, 'file/directory path collision'):
            gate.validate_windows_zip(self.archive)

    def test_rejects_link_and_special_file_metadata(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            with self.subTest(mode=mode):
                entry = zipfile.ZipInfo('ImageDrawBot/link')
                entry.create_system = 3
                entry.external_attr = (mode | 0o777) << 16
                self.write_archive(entry)
                with self.assertRaisesRegex(gate.ReleaseGateError, 'link or special file'):
                    gate.validate_windows_zip(self.archive)

    def test_header_checks_do_not_read_entire_executable_files_into_memory(self):
        self.write_archive('ImageDrawBot/data.txt')
        installer = self.base / 'ImageDrawBot-1.2.3-Setup.exe'
        installer.write_bytes(b'MZ' + b'x' * 1024)
        with mock.patch.object(zipfile.ZipFile, 'read', side_effect=AssertionError('unbounded ZIP member read')), \
                mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded file read')):
            self.assertEqual(gate.validate_windows_zip(self.archive)['integrity'], 'PASS')
            self.assertEqual(gate.validate_installer(installer, app_version='1.2.3')['size'], 1026)
            self.assertTrue(build_release.is_pe_executable(installer))


class ReleaseMetadataMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.artifact = self.base / 'application.zip'
        self.artifact.write_bytes(b'synthetic content')
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.checksums = self.base / 'SHA256.txt'
        self.manifest = self.base / 'manifest.json'

    def manifest_data(self):
        return {'schema': 1, 'version': '1.2.3', 'architecture': 'windows-x64',
                'artifacts': [{'name': self.artifact.name, 'sha256': self.digest,
                               'bytes': self.artifact.stat().st_size}]}

    def validate(self, data, expected=None):
        self.manifest.write_text(json.dumps(data), encoding='utf-8')
        return gate.validate_manifest(self.manifest, app_version='1.2.3',
                                      expected_files=[self.artifact.name] if expected is None else expected)

    def test_checksum_paths_are_rejected_before_hashing_any_target(self):
        for name in ('../private.txt', r'..\private.txt', '/private.txt',
                     'C:/private.txt', 'application.zip:stream'):
            with self.subTest(name=name):
                self.checksums.write_text(f'{self.digest}  {name}\n', encoding='utf-8')
                with mock.patch.object(gate, '_sha256') as digest:
                    with self.assertRaises(gate.ReleaseGateError):
                        gate.verify_checksum_file(self.checksums)
                    digest.assert_not_called()

    def test_checksum_duplicates_are_rejected(self):
        self.checksums.write_text(f'{self.digest}  application.zip\n' * 2, encoding='utf-8')
        with self.assertRaisesRegex(gate.ReleaseGateError, 'Duplicate checksum'):
            gate.verify_checksum_file(self.checksums)

    def test_checksum_list_must_cover_exactly_the_requested_release(self):
        self.checksums.write_text(f'{self.digest}  application.zip\n', encoding='utf-8')
        self.assertEqual(gate.verify_checksum_file(self.checksums, expected_files=['application.zip'])['verified'], 1)
        for expected in ([], ['application.zip', 'installer.exe'], ['other.zip']):
            with self.subTest(expected=expected), self.assertRaisesRegex(gate.ReleaseGateError, 'exactly'):
                gate.verify_checksum_file(self.checksums, expected_files=expected)

    def test_manifest_shape_errors_use_release_gate_errors(self):
        for data in (None, [], 'text', 123):
            with self.subTest(data=data), self.assertRaises(gate.ReleaseGateError):
                self.validate(data)
        data = self.manifest_data()
        data['artifacts'].append('invalid row')
        with self.assertRaisesRegex(gate.ReleaseGateError, 'rows must be objects'):
            self.validate(data)

    def test_manifest_rejects_duplicate_and_unexpected_rows(self):
        data = self.manifest_data()
        data['artifacts'].append(dict(data['artifacts'][0]))
        with self.assertRaisesRegex(gate.ReleaseGateError, 'Duplicate release manifest'):
            self.validate(data)
        data['artifacts'][1]['name'] = 'unexpected.zip'
        with self.assertRaisesRegex(gate.ReleaseGateError, 'unexpected artifacts'):
            self.validate(data)

    def test_manifest_rejects_unsafe_names_before_hashing(self):
        data = self.manifest_data()
        data['artifacts'][0]['name'] = '../private.txt'
        with mock.patch.object(gate, '_sha256') as digest:
            with self.assertRaises(gate.ReleaseGateError):
                self.validate(data, expected=['../private.txt'])
            digest.assert_not_called()

    def test_manifest_size_and_schema_require_real_integers(self):
        for size in (True, float(self.artifact.stat().st_size), str(self.artifact.stat().st_size), 0, -1):
            data = self.manifest_data()
            data['artifacts'][0]['bytes'] = size
            with self.subTest(size=size), self.assertRaisesRegex(gate.ReleaseGateError, 'byte size is invalid'):
                self.validate(data)
        data = self.manifest_data()
        data['schema'] = True
        with self.assertRaises(gate.ReleaseGateError):
            self.validate(data)

    def test_expected_files_generator_is_fully_verified(self):
        data = self.manifest_data()
        data['artifacts'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(gate.ReleaseGateError, 'SHA-256 mismatch'):
            self.validate(data, expected=(name for name in [self.artifact.name]))


class SourceArchiveMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'source'
        for name in source.REQUIRED_RELEASE_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public fixture\n', encoding='utf-8')

    def test_failed_creation_preserves_the_previous_archive(self):
        target = self.base / 'source.zip'
        target.write_bytes(b'previous archive')
        with mock.patch.object(source.shutil, 'copyfileobj', side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                source.create_source_archive(self.root, target)
        self.assertEqual(target.read_bytes(), b'previous archive')
        self.assertFalse(list(self.base.glob('.source-release-*')))

    def test_identical_content_has_identical_archive_bytes_despite_metadata_changes(self):
        first = self.base / 'first.zip'
        second = self.base / 'second.zip'
        source.create_source_archive(self.root, first)
        for path in source.iter_release_files(self.root):
            os.utime(path, (1700000000, 1700000000))
            path.chmod(0o600)
        source.create_source_archive(self.root, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(second) as archive:
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))
            self.assertTrue(all(info.external_attr >> 16 == 0o100644 for info in archive.infolist()))

    def test_archive_inside_source_tree_does_not_include_its_previous_copy(self):
        (self.root / 'sub').mkdir()
        target = self.root / 'sub' / '..' / 'source.zip'
        first = source.create_source_archive(self.root, target)
        second = source.create_source_archive(self.root, target)
        self.assertEqual(first['sha256'], second['sha256'])
        with zipfile.ZipFile(target) as archive:
            self.assertNotIn('Image-Draw-Bot/source.zip', archive.namelist())

    def test_destination_symlink_is_replaced_without_overwriting_its_target(self):
        existing = self.base / 'unrelated.txt'
        existing.write_text('keep this file', encoding='utf-8')
        destination = self.base / 'source.zip'
        try:
            destination.symlink_to(existing)
        except OSError as error:
            self.skipTest(f'Filesystem does not permit test symlinks: {error}')
        source.create_source_archive(self.root, destination)
        self.assertFalse(destination.is_symlink())
        self.assertEqual(existing.read_text(), 'keep this file')
        self.assertTrue(zipfile.is_zipfile(destination))

    def test_privacy_filters_apply_to_windows_case_variants(self):
        private = ('SETTINGS-PRIVATE.JSON', 'CALIBRATION.JSON', 'Logs/private.txt',
                   'RECOVERY/private.png', 'COMPLETED-DRAWINGS/history.json')
        for name in private:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('PRIVATE-CONTENT', encoding='utf-8')
        public = self.root / 'docs' / 'Settings-Example.json'
        public.parent.mkdir(exist_ok=True)
        public.write_text('public example', encoding='utf-8')
        target = self.base / 'source.zip'
        source.create_source_archive(self.root, target)
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            self.assertIn('Image-Draw-Bot/docs/Settings-Example.json', names)
            for name in private:
                self.assertNotIn('Image-Draw-Bot/' + name, names)

    def test_file_and_directory_links_do_not_export_outside_source_data(self):
        external = self.base / 'private'
        external.mkdir()
        private = external / 'private.txt'
        private.write_text('PRIVATE-CONTENT', encoding='utf-8')
        try:
            (self.root / 'linked-file.txt').symlink_to(private)
            (self.root / 'linked-folder').symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'Filesystem does not permit test symlinks: {error}')
        target = self.base / 'source.zip'
        source.create_source_archive(self.root, target)
        with zipfile.ZipFile(target) as archive:
            self.assertNotIn('Image-Draw-Bot/linked-file.txt', archive.namelist())
            self.assertFalse(any('/linked-folder/' in name for name in archive.namelist()))

    def test_windows_junction_detection_also_works_without_path_is_junction(self):
        for tag, expected in ((0xA0000003, True), (0xA000000C, True), (0x9000001A, False), (0, False)):
            path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=tag))
            with self.subTest(tag=tag):
                self.assertEqual(source._is_link(path), expected)


if __name__ == '__main__':
    unittest.main()
