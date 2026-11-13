"""Release verification installs the dependencies needed to actually run tests."""
from pathlib import Path
import tempfile
import unittest

import build_release
from test_v148_platform_batch08_build import BuildFixture


class ReleaseTestDependencyTests(unittest.TestCase):
    def test_default_release_installs_test_requirements_before_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = BuildFixture(Path(directory))
            (fixture.root/'requirements-dev.txt').write_text('hypothesis>=6,<7\n')
            with fixture.active(release_args=[]):
                self.assertEqual(build_release.main(), 0)
            commands = [command for command, _ in fixture.calls]
            install = next(command for command in commands
                if 'pip' in command and str(fixture.root/'requirements.txt') in command)
            self.assertIn(str(fixture.root/'requirements-dev.txt'), install)
            discovery = next(command for command in commands if 'unittest' in command)
            self.assertLess(commands.index(install), commands.index(discovery))

    def test_ci_skip_tests_does_not_require_test_only_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = BuildFixture(Path(directory))
            (fixture.root/'requirements-dev.txt').unlink(missing_ok=True)
            with fixture.active(release_args=['--skip-tests']):
                self.assertEqual(build_release.main(), 0)
            commands = [command for command, _ in fixture.calls]
            self.assertFalse(any('unittest' in command for command in commands))
            self.assertFalse(any(str(fixture.root/'requirements-dev.txt') in command for command in commands))

    def test_release_workflow_installs_dev_dependencies_before_complete_suite(self):
        workflow = Path(__file__).with_name('.github').joinpath('workflows/build-windows.yml').read_text()
        install = 'python -m pip install -r requirements.txt -r requirements-dev.txt'
        self.assertIn(install, workflow)
        self.assertLess(workflow.index(install), workflow.index('python -m unittest discover -v'))


if __name__ == '__main__':
    unittest.main()
