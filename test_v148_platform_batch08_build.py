"""Actual build entry points isolate package installs and share their test Python."""
from contextlib import contextmanager, ExitStack
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import BuildEnvironment as environment
import build_exe
import build_release


class BuildFixture:
    """Only external processes are replaced; packaging/filesystem remain real."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.python = self.root/'.build-venv/Scripts/python.exe'
        self.calls = []
        self.versions = (3, 12)
        self.bits = 64
        self.prefix = self.python.parent.parent
        self.base_prefix = self.root/'base-python'
        self.system_site = False
        self.application = b'MZ synthetic application'
        self.installer = b'MZ synthetic installer'
        self.fail_at = None
        self.configuration = "global.index-url='https://build-user:build-secret@mirror.invalid/simple'\n"
        self.configuration += "global.proxy='http://proxy.invalid:8080'\nglobal.target='/external-target'\n"
        self.configuration += "install.user='true'\ninstall.prefix='/external-prefix'\n"
        for name in ('requirements.txt', 'requirements-dev.txt', 'requirements-build.txt', 'requirements-gpu-universal.txt',
                     'requirements-gpu-nvidia.txt'):
            (self.root/name).write_text('test-dependency>=1\n', encoding='utf-8')
        (self.root/'version_info.txt').write_text(
            f"StringStruct('FileVersion', '{build_exe.FILE_VERSION}')\n"
            f"StringStruct('ProductVersion', '{build_exe.FILE_VERSION}')\n", encoding='utf-8')

    def run(self, command, **options):
        command = list(map(str, command))
        self.calls.append((command, options))
        if 'venv' in command:
            self.python.parent.mkdir(parents=True, exist_ok=True)
            self.python.touch()
        elif '-c' in command:
            sites = [str(self.prefix/'Lib/site-packages')]
            if self.system_site:
                sites.append(str(self.base_prefix/'Lib/site-packages'))
            payload = dict(prefix=str(self.prefix), base_prefix=str(self.base_prefix),
                           version=list(self.versions), bits=self.bits, user_site=False,
                           site_packages=sites, frozen=False)
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
        elif 'config' in command:
            return SimpleNamespace(returncode=0, stdout=self.configuration, stderr='')
        elif 'PyInstaller' in command:
            if self.fail_at == 'freeze':
                raise subprocess.CalledProcessError(1, command)
            target = self.root/'dist/ImageDrawBot/ImageDrawBot.exe'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.application)
        elif Path(command[0]).name == 'ISCC.exe':
            if self.fail_at == 'installer':
                raise subprocess.CalledProcessError(2, command)
            output = Path(next(arg[2:] for arg in command if arg.startswith('/O')))
            (output/f'ImageDrawBot-{build_release.APP_VERSION}-Windows-x64-Setup.exe').write_bytes(self.installer)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    @contextmanager
    def active(self, *, release_args=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'platform', 'win32'))
            stack.enter_context(patch.object(sys, 'version_info', (3, 12, 0)))
            stack.enter_context(patch.object(sys, 'maxsize', 2**63-1))
            stack.enter_context(patch.object(sys, 'executable', str(self.base_prefix/'python.exe')))
            stack.enter_context(patch.dict(os.environ, {'GITHUB_REF_TYPE': '', 'GITHUB_REF_NAME': ''}))
            stack.enter_context(patch.object(subprocess, 'run', side_effect=self.run))
            stack.enter_context(patch.object(build_exe, '__file__', str(self.root/'build_exe.py')))
            for name, value in (('BASE', self.root), ('DIST', self.root/'dist/ImageDrawBot'),
                                ('RELEASE', self.root/'release')):
                stack.enter_context(patch.object(build_release, name, value))
            stack.enter_context(patch.object(build_release, 'find_iscc', return_value=self.root/'ISCC.exe'))
            stack.enter_context(patch.object(build_release, 'run_source_release_gate',
                                            return_value=SimpleNamespace(as_dict=lambda: {'passed': True})))
            if release_args is not None:
                stack.enter_context(patch.object(sys, 'argv', ['build_release.py', *release_args]))
            output = stack.enter_context(patch('sys.stdout', new_callable=StringIO))
            yield output


class PrivateBuilderTests(unittest.TestCase):
    def test_real_private_interpreter_probe_rejects_inherited_system_site_packages(self):
        for shared_site in (False, True):
            with self.subTest(shared_site=shared_site), TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                target = root/'.build-venv'
                arguments = [sys.executable, '-I', '-m', 'venv', '--without-pip']
                if shared_site:
                    arguments.append('--system-site-packages')
                subprocess.run([*arguments, str(target)], check=True, capture_output=True, timeout=30)
                python = target/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
                if shared_site:
                    with self.assertRaisesRegex(environment.BuildEnvironmentError, 'isolated 64-bit Python'):
                        environment._verify_builder(python, target, root)
                else:
                    environment._verify_builder(python, target, root)

    def test_public_release_tests_and_pyinstaller_share_one_private_environment(self):
        with TemporaryDirectory() as folder:
            fixture = BuildFixture(Path(folder))
            with fixture.active(release_args=['--installer']) as output:
                self.assertEqual(build_release.main(), 0)
            commands = [command for command, _ in fixture.calls]
            private = str(fixture.python)
            self.assertEqual(sum('venv' in command for command in commands), 1)
            installs = [command for command in commands if 'pip' in command and 'install' in command]
            self.assertEqual(len(installs), 2)
            self.assertTrue(all(command[0] == private and command[1:4] == ['-I', '-m', 'pip']
                                and '--require-virtualenv' in command for command in installs))
            steps = [(command, options) for command, options in fixture.calls
                     if 'unittest' in command or 'PyInstaller' in command or 'DrawBot.py' in command]
            self.assertEqual(len(steps), 3)
            for command, options in steps:
                self.assertEqual(command[0], private)
                self.assertEqual(Path(options['cwd']), fixture.root)
                self.assertEqual(options['env']['PYTHONPATH'], str(fixture.root))
                self.assertEqual(options['env']['PYTHONNOUSERSITE'], '1')
                self.assertEqual(options['env']['PYTHONSAFEPATH'], '1')
            self.assertNotIn('build-secret', output.getvalue())

    def test_direct_builder_preserves_pip_network_policy_without_target_or_startup_overrides(self):
        with TemporaryDirectory() as folder:
            fixture = BuildFixture(Path(folder))
            overrides = dict(PYTHONPATH='/inherited-code', PYTHONHOME='/other-python', PYTHONINSPECT='1',
                             PIP_TARGET='/outside', PIP_PREFIX='/other', PIP_ROOT='/redirect', PIP_USER='1',
                             PIP_PYTHON='/different-interpreter', HTTPS_PROXY='https://ordinary-proxy.invalid',
                             REQUESTS_CA_BUNDLE='/certificate-bundle.pem')
            with patch.dict(os.environ, overrides, clear=True), fixture.active():
                build_exe.main(['--gpu'])
            installs = [(command, options['env']) for command, options in fixture.calls
                        if 'pip' in command and 'install' in command]
            self.assertEqual(len(installs), 2)
            for command, policy in installs:
                self.assertEqual(command[0], str(fixture.python))
                for key in ('PIP_TARGET', 'PIP_PREFIX', 'PIP_ROOT', 'PIP_USER', 'PIP_PYTHON',
                            'PYTHONPATH', 'PYTHONHOME', 'PYTHONINSPECT'):
                    self.assertNotIn(key, policy)
                self.assertEqual(policy['PIP_CONFIG_FILE'], os.devnull)
                self.assertEqual(policy['PIP_INDEX_URL'], 'https://build-user:build-secret@mirror.invalid/simple')
                self.assertEqual(policy['PIP_PROXY'], 'http://proxy.invalid:8080')
                self.assertEqual(policy['HTTPS_PROXY'], overrides['HTTPS_PROXY'])
                self.assertEqual(policy['REQUESTS_CA_BUNDLE'], overrides['REQUESTS_CA_BUNDLE'])
            self.assertIn(str(fixture.root/'requirements-gpu-nvidia.txt'), installs[-1][0])
            pyi = next(command for command, _ in fixture.calls if 'PyInstaller' in command)
            self.assertIn('cupy', pyi)

    def test_existing_environment_is_verified_before_package_changes(self):
        for fault in ('base', 'other-venv', '32-bit', 'old-python', 'system-site'):
            with self.subTest(fault=fault), TemporaryDirectory() as folder:
                fixture = BuildFixture(Path(folder))
                fixture.python.parent.mkdir(parents=True)
                fixture.python.touch()
                if fault == 'base':fixture.prefix = fixture.base_prefix
                elif fault == 'other-venv':fixture.prefix = fixture.root/'another-venv'
                elif fault == '32-bit':fixture.bits = 32
                elif fault == 'old-python':fixture.versions = (3, 10)
                else:fixture.system_site = True
                with fixture.active(), self.assertRaisesRegex(SystemExit, 'Rename .build-venv'):
                    build_exe.main([])
                self.assertEqual(len(fixture.calls), 1)
                self.assertIn('-I', fixture.calls[0][0])
                self.assertNotIn('pip', fixture.calls[0][0])

    def test_missing_requirement_fails_before_environment_creation_or_installs(self):
        with TemporaryDirectory() as folder:
            fixture = BuildFixture(Path(folder))
            (fixture.root/'requirements-gpu-universal.txt').unlink()
            with fixture.active(), self.assertRaisesRegex(SystemExit, 'requirements are missing'):
                build_exe.main([])
            self.assertFalse(fixture.calls)

    def test_skip_tests_keeps_ci_semantics_and_still_runs_the_packaged_self_test(self):
        with TemporaryDirectory() as folder:
            fixture = BuildFixture(Path(folder))
            with fixture.active(release_args=['--skip-tests']):
                self.assertEqual(build_release.main(), 0)
            commands = [command for command, _ in fixture.calls]
            self.assertFalse(any('unittest' in command or 'DrawBot.py' in command for command in commands))
            self.assertTrue(any(Path(command[0]).name == 'ImageDrawBot.exe' and command[-1] == '--self-test'
                                for command in commands))
            requirements = next(command for command in commands if '--upgrade-strategy' in command)
            self.assertNotIn(str(fixture.root/'requirements-gpu-nvidia.txt'), requirements)


if __name__ == '__main__':
    unittest.main()
