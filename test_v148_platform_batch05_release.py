from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_exe
import ReleaseCandidateHardening as gate
import ReleasePackage as release
import test_step30_release_candidate_hardening_v10129rc1 as gate_fixtures


class SourceInventoryTests(unittest.TestCase):
    def test_any_included_traversal_failure_preserves_the_previous_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'source'
            root.mkdir()
            for relative in release.REQUIRED_RELEASE_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('source fixture\n', encoding='utf-8')
            resource = root / 'assets' / 'theme'
            resource.mkdir(parents=True)
            (resource / 'theme.json').write_text('{"theme":"test"}', encoding='utf-8')
            destination = Path(temporary) / 'source.zip'
            real_scandir = os.scandir
            # Validation inventories twice; publication inventories once more.
            # None of those walks may silently skip an unreadable subtree.
            for failed_visit in (1, 2, 3):
                visits = []
                destination.write_bytes(b'previous complete archive')
                def denied(path):
                    if Path(path) == resource:
                        visits.append(path)
                        if len(visits) == failed_visit:
                            raise PermissionError('injected resource traversal failure')
                    return real_scandir(path)
                with self.subTest(failed_visit=failed_visit), patch.object(release.os, 'scandir', side_effect=denied):
                    with self.assertRaisesRegex(PermissionError, 'resource traversal'):
                        release.create_source_archive(root, destination)
                self.assertEqual(destination.read_bytes(), b'previous complete archive')
                self.assertEqual(list(destination.parent.glob('.source-release-*.tmp')), [])

    def test_private_excluded_subtrees_are_not_opened_to_validate_the_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / 'logs'
            private.mkdir()
            (private / 'private.log').write_text('not release contents')
            (root / 'kept.py').write_text('source')
            real_scandir = os.scandir
            def denied(path):
                if Path(path) == private:
                    raise AssertionError('excluded runtime logs were inspected')
                return real_scandir(path)
            with patch.object(release.os, 'scandir', side_effect=denied):
                self.assertEqual([path.name for path in release.iter_release_files(root)], ['kept.py'])

    def test_source_gate_and_archive_require_the_release_identity_helper(self):
        self.assertIn('ReleaseIdentity.py', release.REQUIRED_RELEASE_FILES)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gate_fixtures.Step30ReleaseCandidateHardeningTests()._fake_root(root)
            (root / 'ReleaseIdentity.py').unlink()
            errors = gate.collect_source_gate_errors(root, app_version='1.0.131-beta', file_version='1.0.131', channel='beta')
        self.assertTrue(any('release identity' in error for error in errors))

    def test_hygiene_ignores_private_dependency_trees_but_keeps_actual_source_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = ['real_patch_once.py', '.github/workflows/release-once.yml',
                     '.build-venv/Lib/site-packages/upstream/check_once.py',
                     'dist/ImageDrawBot/_internal/upstream/check_once.py', '.git/private_once.py',
                     '.github/workflows-backup/documented-once.yml']
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            real_scandir = os.scandir
            def only_source(path):
                if Path(path).name in {'.build-venv', 'dist', '.git'}:
                    raise AssertionError('A private dependency/output tree was traversed')
                return real_scandir(path)
            with patch.object(gate.os, 'scandir', side_effect=only_source):
                self.assertEqual(gate.find_one_shot_source_files(root),
                                 ['.github/workflows/release-once.yml', 'real_patch_once.py'])

    def test_hygiene_reports_included_traversal_failure_instead_of_a_clean_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            included = root / 'module'
            included.mkdir()
            (included / 'patch_once.py').write_text('fixture')
            real_scandir = os.scandir
            def denied(path):
                if Path(path) == included:
                    raise PermissionError('injected included-directory denial')
                return real_scandir(path)
            with patch.object(gate.os, 'scandir', side_effect=denied):
                with self.assertRaisesRegex(gate.ReleaseGateError, 'could not be fully inspected'):
                    gate.find_one_shot_source_files(root)


class BuildArgumentTests(unittest.TestCase):
    def test_help_succeeds_on_any_platform_without_creating_a_builder_or_installing(self):
        for platform in ('win32', 'linux'):
            output = StringIO()
            with self.subTest(platform=platform), patch.object(build_exe.sys, 'platform', platform), \
                 patch.object(build_exe.subprocess, 'run') as run, redirect_stdout(output):
                with self.assertRaises(SystemExit) as result:
                    build_exe.main(['--help'])
                self.assertEqual(result.exception.code, 0)
                run.assert_not_called()
                self.assertIn('--onefile', output.getvalue())
                self.assertIn('--gpu', output.getvalue())

    def test_unknown_or_misspelled_modes_fail_before_any_environment_side_effect(self):
        for arguments in (['--gpuu'], ['--onefile', '--unknown'], ['unexpected.exe']):
            with self.subTest(arguments=arguments), patch.object(build_exe.sys, 'platform', 'win32'), \
                 patch.object(build_exe.subprocess, 'run') as run, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as result:
                    build_exe.main(arguments)
                self.assertEqual(result.exception.code, 2)
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
