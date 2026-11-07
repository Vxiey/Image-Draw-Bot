"""Public source startup keeps installs and child Python imports private."""
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import GpuSetupRuntime as policy
import SourceStartup as startup


class SourceStartupTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        (self.root/'DrawBot.py').write_text('# source entry\n')
        (self.root/'requirements.txt').write_text('Pillow>=13\n')
        self.directory = self.root/'.venv'
        self.python = self.directory/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
        self.marker = self.directory/'installed-requirements.txt'
        self.commands = []
        self.details = dict(prefix=str(self.directory), base_prefix=str(self.root/'base'),
            version=[3, 11], user_site=False, site_packages=[str(self.directory/'Lib/site-packages')], frozen=False)
        self.import_result = self.check_result = self.install_result = self.application_result = 0
        self.upgrade_result = self.gpu_result = 0
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(startup, 'ROOT', self.root))
        self.stack.enter_context(patch.object(startup.subprocess, 'run', side_effect=self.process))

    def process(self, command, **kwargs):
        self.commands.append((list(command), kwargs))
        stdout, code = '', 0
        if 'venv' in command:
            self.python.parent.mkdir(parents=True, exist_ok=True)
            self.python.write_bytes(b'private interpreter placeholder')
        elif command[-1] == policy._PRIVATE_ENVIRONMENT_PROBE:
            stdout = json.dumps(self.details)
        elif command[-1] == policy._ENVIRONMENT_PROBE:
            stdout = json.dumps(self.details)
        elif 'config' in command:
            stdout = "global.index-url='https://user:secret@packages.example/simple'\nglobal.proxy='http://proxy.example:8080'\ninstall.target='/wrong/target'\ninstall.user='true'\n"
        elif command[-1] == startup._IMPORT_CHECK:
            code = self.import_result
        elif '-m' in command and 'pip' in command:
            if command[-1] == 'check': code = self.check_result
            elif 'eager' in command: code = self.install_result
            else: code = self.upgrade_result
        elif command[-1] == str(self.root/'DrawBot.py'):
            code = self.application_result
        elif any(str(self.root/name) in command for name in ('AutoGpuSetup.py', 'AutoUniversalGpuSetup.py')):
            code = self.gpu_result
        else:
            raise AssertionError(f'Unexpected process: {command}')
        if code and kwargs.get('check'):
            raise subprocess.CalledProcessError(code, command)
        return SimpleNamespace(returncode=code, stdout=stdout, stderr='')

    def installed(self):
        self.python.parent.mkdir(parents=True, exist_ok=True)
        self.python.write_bytes(b'private interpreter placeholder')
        self.marker.write_bytes((self.root/'requirements.txt').read_bytes())

    def pip_calls(self):
        return [(command, options) for command, options in self.commands if '-m' in command and 'pip' in command]

    def test_public_main_creates_verifies_and_installs_only_private_runtime_requirements(self):
        with patch.dict(os.environ, {'PATH':os.environ.get('PATH',''), 'PIP_TARGET':'/outside',
                'PIP_PREFIX':'/outside-prefix', 'PIP_USER':'1', 'PIP_PYTHON':'/another/python',
                'PYTHONPATH':'/untrusted/startup', 'PYTHONHOME':'/another/python',
                'PYTHONINSPECT':'1', 'PYTHONSTARTUP':'/untrusted/startup.py'}, clear=True):
            self.assertEqual(startup.main([]), 0)
        self.assertEqual(self.marker.read_bytes(), (self.root/'requirements.txt').read_bytes())
        self.assertEqual(self.commands[0][0], [sys.executable,'-I','-m','venv',str(self.directory)])
        self.assertEqual(self.commands[1][0][-1], policy._PRIVATE_ENVIRONMENT_PROBE)
        installs = [command for command, _ in self.pip_calls() if 'install' in command]
        self.assertEqual(len(installs), 2)
        self.assertEqual(installs[-1][-2:], ['-r', str(self.root/'requirements.txt')])
        for command, options in self.pip_calls():
            self.assertEqual(command[:6], [str(self.python),'-I','-m','pip','--require-virtualenv','--no-input'])
            env = options['env']
            for name in ('PIP_TARGET','PIP_PREFIX','PIP_USER','PIP_PYTHON','PYTHONPATH','PYTHONHOME','PYTHONINSPECT','PYTHONSTARTUP'):
                self.assertNotIn(name, env)
            if 'config' not in command:
                self.assertEqual(env['PIP_INDEX_URL'], 'https://user:secret@packages.example/simple')
                self.assertEqual(env['PIP_PROXY'], 'http://proxy.example:8080')
                self.assertEqual(env['PIP_CONFIG_FILE'], os.devnull)
        command, options = self.commands[-1]
        self.assertEqual(command, [str(self.python),'-s','-X','faulthandler','-u',str(self.root/'DrawBot.py')])
        self.assertEqual(options['env']['PYTHONPATH'], str(self.root))
        self.assertNotIn('PYTHONINSPECT', options['env'])
        self.assertNotIn('secret', self.output.getvalue())

    def test_cached_dependencies_need_no_install_and_explicit_flags_control_gpu_setup(self):
        self.installed()
        self.assertEqual(startup.main([]), 0)
        self.assertFalse(any('install' in command for command, _ in self.pip_calls()))
        self.assertFalse(any('AutoGpuSetup.py' in ' '.join(command) for command, _ in self.commands))
        self.commands.clear(); self.gpu_result = 1
        self.assertEqual(startup.main(['--gpu']), 0)
        optional = [command for command, _ in self.commands if '--ensure' in command]
        self.assertEqual(len(optional), 2)
        self.assertTrue(all('--force' not in command for command in optional))
        self.assertIn('CPU fallback remains enabled', self.output.getvalue())
        self.commands.clear()
        self.assertEqual(startup.main(['--update']), 0)
        self.assertTrue(any('install' in command for command, _ in self.pip_calls()))
        optional = [command for command, _ in self.commands if '--ensure' in command]
        self.assertEqual(len(optional), 2)
        self.assertTrue(all('--force' in command for command in optional))

    def test_invalid_private_interpreter_cannot_reach_pip_or_application(self):
        self.installed()
        valid = dict(self.details)
        for change in ({'prefix':str(self.root/'base')}, {'base_prefix':str(self.directory)},
                {'version':[3,10]}, {'site_packages':[str(self.root/'base/site-packages')]},
                {'user_site':True}, {'frozen':True}):
            with self.subTest(change=change):
                self.details = dict(valid, **change); self.commands.clear()
                self.assertEqual(startup.main([]), 1)
                self.assertEqual(len(self.commands), 1)
                self.assertEqual(self.commands[0][0][-1], policy._PRIVATE_ENVIRONMENT_PROBE)
        self.assertIn('Rename .venv', self.output.getvalue())

    def test_install_failure_or_failed_pip_check_cannot_publish_marker_or_launch(self):
        self.installed()
        original = self.marker.read_bytes()
        for failing in ('install_result', 'check_result'):
            with self.subTest(failing=failing):
                self.install_result = self.check_result = 0
                setattr(self, failing, 1); self.commands.clear()
                self.assertEqual(startup.main(['--update']), 1)
                self.assertEqual(self.marker.read_bytes(), original)
                self.assertFalse(any(command[-1] == str(self.root/'DrawBot.py') for command, _ in self.commands))

    def test_existing_import_failure_repairs_packages_and_app_exit_status_is_preserved(self):
        self.installed(); self.import_result = 1; self.upgrade_result = 1
        self.application_result = 7
        self.assertEqual(startup.main([]), 7)
        self.assertTrue(any('eager' in command for command, _ in self.pip_calls()))
        self.assertIn('Continuing with the installed version', self.output.getvalue())


class ActualSourceIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        cls.directory = cls.root/'.venv'
        subprocess.run([sys.executable,'-I','-m','venv',str(cls.directory)],check=True,capture_output=True,timeout=90)
        cls.python = str(cls.directory/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python'))

    def runner(self, command, *, env=None, capture_stderr=False, timeout=30):
        return subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',timeout=timeout,check=False)

    def test_real_private_probe_rejects_base_python_and_pip_cannot_inherit_relocation_or_startup(self):
        policy.require_private_environment(self.python, self.directory, self.runner)
        with self.assertRaises(policy.SetupEnvironmentError):
            policy.require_private_environment(sys._base_executable, self.directory, self.runner)
        extra = self.root/'outside'; extra.mkdir(exist_ok=True)
        marker = extra/'executed.txt'
        (extra/'sitecustomize.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("unexpected")\n')
        config = self.root/'pip.ini'
        config.write_text('[install]\ntarget = '+str(extra/'packages')+'\nuser = true\n')
        env = {'PYTHONPATH':str(extra),'PYTHONINSPECT':'1','PIP_CONFIG_FILE':str(config),
               'PIP_TARGET':str(extra/'override'),'PIP_PREFIX':str(extra/'prefix')}
        parser = ('import json; from pip._internal.commands import create_command; '
                  'o,_=create_command("install").parse_args(["--upgrade","-r","requirements.txt"]); '
                  'print(json.dumps([o.target_dir,o.prefix_path,o.use_user_site]))')
        with patch.dict(os.environ, env):
            with policy.pip_environment(self.python, self.runner) as selected:
                result = self.runner([self.python,'-I','-c',parser],env=selected.for_command('install'))
            child = self.runner([self.python,'-s','-c','print("source-child")'],
                                env=startup._source_environment(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [None,None,None])
        self.assertEqual(child.stdout.strip(), 'source-child')
        self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows batch launcher')
    def test_actual_batch_entry_forwards_flags_and_ignores_python_startup_overrides(self):
        import shutil
        root = self.root/'batch-entry'; root.mkdir()
        shutil.copyfile(Path(startup.__file__).with_name('Start.bat'), root/'Start.bat')
        # A real private interpreter runs a harmless entry stub; no dependencies,
        # GPU setup or application/window/input are executed by this fixture.
        subprocess.run([sys.executable,'-I','-m','venv','--without-pip',str(root/'.venv')],
                       check=True,capture_output=True,timeout=90)
        (root/'DrawBot.py').write_text('# required source file\n')
        (root/'requirements.txt').write_text('Pillow>=13\n')
        (root/'SourceStartup.py').write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'Path("arguments.json").write_text(json.dumps(sys.argv[1:]))\n'
            'raise SystemExit(7 if "--fail" in sys.argv else 0)\n')
        outside = root/'outside'; outside.mkdir()
        (outside/'sitecustomize.py').write_text('raise RuntimeError("startup override ran")\n')
        environment = dict(os.environ, TEMP=str(root), PYTHONPATH=str(outside),
                           PYTHONHOME=str(outside), PYTHONINSPECT='1')
        for flag, code in (('--gpu', 0), ('--fail', 1)):
            with self.subTest(flag=flag):
                result = subprocess.run(['cmd.exe','/d','/c','Start.bat',flag],cwd=root,
                    env=environment,input='\n',capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode, code, result.stdout+result.stderr)
                self.assertEqual(json.loads((root/'arguments.json').read_text()), [flag])
                self.assertNotIn('startup override ran', (root/'ImageDrawBot-start.log').read_text())


if __name__ == '__main__':
    unittest.main()
