"""Direct GPU installers participate in the source environment's ownership."""
from contextlib import ExitStack, contextmanager, redirect_stdout
import io
import json
import multiprocessing
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import AutoGpuSetup as nvidia
import AutoUniversalGpuSetup as universal
import GpuSetupRuntime as policy
import SourceStartup as startup
from test_v148_platform_batch14_startup import held_startup


ROOT = Path(__file__).resolve().parent
BATCHES = {'nvidia': 'Install-GPU-NVIDIA.bat', 'universal': 'Install-GPU-Universal.bat'}
MODULES = {'AutoGpuSetup.py': nvidia, 'AutoUniversalGpuSetup.py': universal}


def batch_dispatch(backend):
    """Read the actual one-command batch dispatch, including Python flags."""
    text = (ROOT / BATCHES[backend]).read_text(encoding='utf-8')
    commands = [shlex.split(match.group(1)) for line in text.splitlines()
                if (match := re.match(r'^"\.venv\\Scripts\\python\.exe"\s+(.+)$', line))]
    assert len(commands) == 1
    command = commands[0]
    flags = []
    while command and command[0].startswith('-'):
        flags.append(command.pop(0))
    assert flags == ['-E', '-s']
    return command[0], command[1:]


class InstallerFixture:
    """Real CLI/setup policy; only external Python and GPU probes are replaced."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / '.venv'
        self.python = self.directory / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        self.commands = []
        self.external = []
        self.output = io.StringIO()
        self.before_helper = lambda command: None
        self.install_code = 0
        self.helper_error = None
        self.gpu_present = True
        self.details = dict(prefix=str(self.directory), base_prefix=str(self.root / 'base-python'),
            real_prefix=None, version=[3, 12], user_site=False,
            site_packages=[str(self.directory / 'Lib/site-packages')], frozen=False)

    def prepare(self):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'DrawBot.py').write_text('# no application executes in this fixture\n')
        (self.root / 'requirements.txt').write_text('Pillow>=13\n')
        (self.root / 'requirements-gpu-nvidia.txt').write_text('cupy-cuda12x>=13\n')
        (self.root / 'requirements-gpu-universal.txt').write_text('pyopencl>=2026\n')
        for name in MODULES:
            (self.root / name).write_text('# external-process dispatch boundary\n')
        self.python.parent.mkdir(parents=True, exist_ok=True)
        self.python.write_bytes(b'private interpreter boundary fixture')
        (self.directory / 'installed-requirements.txt').write_bytes((self.root / 'requirements.txt').read_bytes())

    def external_process(self, command, **kwargs):
        command = list(map(str, command))
        self.external.append(command)
        code, stdout = 0, ''
        if command[-1] in (policy._PRIVATE_ENVIRONMENT_PROBE, policy._ENVIRONMENT_PROBE):
            stdout = json.dumps(self.details)
        elif '--smoke-json' in command:
            stdout = json.dumps(dict(ok=True, devices=['AMD fixture'], message='ready'))
        elif '--cupy-smoke' in command:
            stdout = 'ready'
        elif 'pip' in command:
            if 'config' in command:
                stdout = ''
            elif 'list' in command:
                stdout = '[{"name":"cupy-cuda11x"}]'
            elif 'install' in command or 'uninstall' in command:
                code = self.install_code
        else:
            raise AssertionError(f'Unexpected external command: {command}')
        if code and kwargs.get('check'):
            raise subprocess.CalledProcessError(code, command)
        return SimpleNamespace(returncode=code, stdout=stdout, stderr='')

    def helper(self, name, arguments):
        module = MODULES[name]
        with patch.object(sys, 'prefix', str(self.directory)), \
                patch.object(sys, 'executable', str(self.python)):
            return module.main(arguments)

    def source_process(self, command, *, root, environment, check=False, capture=False, timeout=None):
        command = list(map(str, command))
        self.commands.append((command, dict(environment)))
        helper = next((name for name in MODULES if str(self.root / name) in command), None)
        if helper:
            self.before_helper(command)
            if self.helper_error is not None:
                raise self.helper_error
            index = command.index(str(self.root / helper))
            code = self.helper(helper, command[index + 1:])
            return SimpleNamespace(returncode=code, stdout='', stderr='')
        if command[-1] == str(self.root / 'DrawBot.py') or command[-1] == startup._IMPORT_CHECK:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        return self.external_process(command, check=check)

    @contextmanager
    def active(self):
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(self.output))
            stack.enter_context(patch.object(startup, 'ROOT', self.root))
            stack.enter_context(patch.object(startup, '_run', side_effect=self.source_process))
            for module in MODULES.values():
                stack.enter_context(patch.object(module, '_run', side_effect=self.external_process))
                stack.enter_context(patch.object(module, 'BASE', self.root))
            stack.enter_context(patch.object(nvidia, 'GPU_REQUIREMENTS', self.root / 'requirements-gpu-nvidia.txt'))
            stack.enter_context(patch.object(universal, 'REQUIREMENTS', self.root / 'requirements-gpu-universal.txt'))
            stack.enter_context(patch.object(nvidia, 'best_nvidia_gpu', side_effect=lambda **_: (
                SimpleNamespace(name='NVIDIA fixture', driver_version='fixture') if self.gpu_present else None)))
            stack.enter_context(patch.object(universal, 'detect_gpus', return_value=[SimpleNamespace(vendor='AMD')]))
            yield self

    def dispatch(self, backend):
        name, arguments = batch_dispatch(backend)
        return startup.main(arguments) if name == 'SourceStartup.py' else self.helper(name, arguments)

    def mutations(self):
        return [command for command in self.external if 'pip' in command
                and ('install' in command or 'uninstall' in command)]


def _held_gpu_setup(root, backend, ready, proceed, result):
    try:
        fixture = InstallerFixture(root)
        def hold(command):
            ready.set()
            if not proceed.wait(20):
                raise TimeoutError('GPU setup fixture was not released.')
        fixture.before_helper = hold
        with fixture.active():
            code = fixture.dispatch(backend)
        result.send(('ok', code, len(fixture.mutations())))
    except BaseException as error:
        result.send(('error', type(error).__name__, str(error)))
    finally:
        result.close()


@contextmanager
def held_gpu_setup(root, backend):
    context = multiprocessing.get_context('spawn')
    ready, proceed = context.Event(), context.Event()
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_held_gpu_setup, args=(str(root), backend, ready, proceed, send))
    process.start()
    send.close()
    try:
        if not ready.wait(15):
            detail = receive.recv() if receive.poll() else f'exit={process.exitcode}'
            raise AssertionError(f'GPU setup did not reach its external boundary: {detail!r}')
        yield process, proceed, receive
    finally:
        proceed.set()
        process.join(5)
        if process.is_alive():
            process.terminate(); process.join(5)
        if process.is_alive():
            process.kill(); process.join(5)
        receive.close(); process.close()


class DirectGpuInstallerTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='GPU setup source with spaces ')
        self.addCleanup(temporary.cleanup)
        fixture = InstallerFixture(temporary.name)
        fixture.prepare()
        return fixture

    def test_both_batch_entries_cannot_mutate_a_running_source_environment(self):
        for backend in BATCHES:
            with self.subTest(backend=backend):
                fixture = self.fixture()
                with held_startup(fixture.root, 'application'):
                    with fixture.active():
                        code = fixture.dispatch(backend)
                    self.assertEqual(code, 1,
                        f'Actual helper attempted {len(fixture.mutations())} package mutations under another owner.')
                    self.assertEqual(fixture.commands, [])
                    self.assertEqual(fixture.external, [])
                    self.assertIn('already using', fixture.output.getvalue())

    def test_setup_only_verifies_private_interpreter_and_preserves_helper_policy(self):
        for backend in BATCHES:
            with self.subTest(backend=backend):
                fixture = self.fixture()
                marker = fixture.directory / 'installed-requirements.txt'
                original = marker.read_bytes()
                with fixture.active(), patch.dict(os.environ, {'PYTHONHOME': '/wrong',
                        'PYTHONINSPECT': '1', 'PYTHONSTARTUP': '/wrong/startup.py'}):
                    self.assertEqual(fixture.dispatch(backend), 0)
                commands = [command for command, _ in fixture.commands]
                self.assertEqual(len(commands), 2)
                self.assertEqual(commands[0][-1], policy._PRIVATE_ENVIRONMENT_PROBE)
                script = 'AutoGpuSetup.py' if backend == 'nvidia' else 'AutoUniversalGpuSetup.py'
                expected = [str(fixture.python), '-s', str(fixture.root / script), '--ensure', '--force']
                if backend == 'nvidia':
                    expected.append('--require-nvidia')
                self.assertEqual(commands[1], expected)
                self.assertTrue(fixture.mutations())
                self.assertFalse(any(str(fixture.root / 'requirements.txt') in command
                                     for command in fixture.external))
                self.assertFalse(any('venv' in command or str(fixture.root / 'DrawBot.py') in command
                                     for command in commands))
                for _, environment in fixture.commands:
                    for key in ('PYTHONHOME', 'PYTHONINSPECT', 'PYTHONSTARTUP'):
                        self.assertNotIn(key, environment)
                self.assertEqual(marker.read_bytes(), original)

    def test_private_environment_failure_and_absence_never_reach_helper(self):
        invalid = ({'prefix': 'outside'}, {'version': [3, 10]}, {'user_site': True},
                   {'frozen': True}, {'site_packages': ['/outside/site-packages']})
        for changes in invalid:
            with self.subTest(changes=changes):
                fixture = self.fixture()
                fixture.details.update(changes)
                with fixture.active():
                    self.assertEqual(fixture.dispatch('universal'), 1)
                self.assertEqual(len(fixture.commands), 1)
                self.assertEqual(fixture.commands[0][0][-1], policy._PRIVATE_ENVIRONMENT_PROBE)
                self.assertEqual(fixture.mutations(), [])
        fixture = self.fixture()
        fixture.python.unlink()
        with fixture.active():
            self.assertEqual(startup.main(['--setup-gpu', 'nvidia', '--force', '--require-nvidia']), 1)
        self.assertEqual(fixture.commands, [])
        self.assertFalse(fixture.python.exists())

    def test_setup_owner_blocks_other_setup_and_start_until_helper_returns(self):
        fixture = self.fixture()
        with held_gpu_setup(fixture.root, 'universal') as (process, proceed, result):
            for arguments in (['--setup-gpu', 'nvidia', '--force', '--require-nvidia'], [], ['--update']):
                with self.subTest(arguments=arguments), fixture.active():
                    self.assertEqual(startup.main(arguments), 1)
            self.assertEqual(fixture.commands, [])
            self.assertEqual(fixture.external, [])
            proceed.set(); process.join(10)
            self.assertFalse(process.is_alive())
            self.assertTrue(result.poll(2))
            self.assertEqual(result.recv(), ('ok', 0, 1))
        with fixture.active():
            self.assertEqual(fixture.dispatch('nvidia'), 0)
        self.assertTrue(fixture.mutations())

    def test_helper_errors_keep_exit_status_and_release_the_lock_for_retry(self):
        for backend in BATCHES:
            with self.subTest(backend=backend):
                fixture = self.fixture()
                fixture.install_code = 7
                with fixture.active():
                    self.assertEqual(fixture.dispatch(backend), 3)
                fixture.install_code = 0
                fixture.helper_error = OSError('could not launch selected helper')
                with fixture.active():
                    self.assertEqual(fixture.dispatch(backend), 1)
                fixture.helper_error = None
                with fixture.active():
                    self.assertEqual(fixture.dispatch(backend), 0)
        fixture = self.fixture()
        fixture.gpu_present = False
        with fixture.active():
            self.assertEqual(fixture.dispatch('nvidia'), 2)
        self.assertEqual(fixture.mutations(), [])

    def test_existing_start_gpu_and_update_use_direct_helpers_under_the_parent_lock(self):
        for arguments in (['--gpu'], ['--update']):
            with self.subTest(arguments=arguments):
                fixture = self.fixture()
                with fixture.active():
                    self.assertEqual(startup.main(arguments), 0)
                commands = [command for command, _ in fixture.commands]
                helpers = [command for command in commands if '--ensure' in command]
                self.assertEqual(len(helpers), 2)
                self.assertTrue(all('--force' in command for command in helpers) if arguments == ['--update']
                                else all('--force' not in command for command in helpers))
                self.assertFalse(any('SourceStartup.py' in ' '.join(command) for command in helpers))
                self.assertEqual(commands[-1][-1], str(fixture.root / 'DrawBot.py'))

    @unittest.skipUnless(sys.platform == 'win32', 'Actual Windows GPU installer batch exit codes')
    def test_actual_batches_keep_arguments_markers_and_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix='GPU batch & spaces ') as temporary:
            root = Path(temporary)
            subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', str(root / '.venv')],
                           check=True, capture_output=True, timeout=90)
            stub = ('import json,sys\nfrom pathlib import Path\n'
                    'Path("arguments.json").write_text(json.dumps([sys.argv[1:],'
                    'sys.flags.ignore_environment,sys.flags.no_user_site]))\n'
                    'raise SystemExit(int(Path("result-code.txt").read_text()))\n')
            (root / 'SourceStartup.py').write_text(stub, encoding='utf-8')
            for backend, filename in BATCHES.items():
                shutil.copyfile(ROOT / filename, root / filename)
                expected = ['--setup-gpu', backend, '--force']
                if backend == 'nvidia':
                    expected.append('--require-nvidia')
                marker = root / '.venv/gpu-install-failed.marker'
                for child_code in (3, 0):
                    with self.subTest(backend=backend, child_code=child_code):
                        (root / 'result-code.txt').write_text(str(child_code))
                        marker.write_text('existing diagnostic marker')
                        result = subprocess.run(['cmd.exe', '/d', '/c', filename], cwd=root,
                            input='\n', capture_output=True, text=True, timeout=20)
                        expected_code = (1 if child_code else 0) if backend == 'nvidia' else child_code
                        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
                        self.assertEqual(json.loads((root / 'arguments.json').read_text()), [expected, 1, 1])
                        self.assertEqual(marker.exists(), backend != 'nvidia' or child_code != 0)


if __name__ == '__main__':
    unittest.main()
