"""Source helper entry points ignore inherited Python startup overrides."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
HELPERS = {
    'Enable-Crash-Dumps.bat': ('CrashDumpConfig.py', ['enable', '--include-python']),
    'Disable-Crash-Dumps.bat': ('CrashDumpConfig.py', ['disable', '--include-python']),
    'Collect-Diagnostics.bat': ('DiagnosticsPackage.py', []),
    'Install-GPU-NVIDIA.bat': ('SourceStartup.py', ['--setup-gpu', 'nvidia', '--force', '--require-nvidia']),
    'Install-GPU-Universal.bat': ('SourceStartup.py', ['--setup-gpu', 'universal', '--force']),
}


def source_commands(filename):
    commands = []
    for line in (ROOT / filename).read_text(encoding='utf-8').splitlines():
        match = re.match(r'^\s*(?:"[^"\r\n]*python\.exe"|py -3)\s+(.*)$', line)
        if match:
            remainder = match.group(1).split()
            flags = []
            while remainder and remainder[0].startswith('-'):
                flags.append(remainder.pop(0))
            commands.append(flags)
    return commands


class SourceHelperBootstrapTests(unittest.TestCase):
    def test_real_harmless_helper_does_not_execute_an_inherited_startup_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / 'hook-ran.txt'
            (directory / 'sitecustomize.py').write_text(
                'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("fixture")\n',
                encoding='utf-8')
            environment = {key: value for key, value in os.environ.items()
                           if not key.upper().startswith('PYTHON')}
            environment['PYTHONPATH'] = str(directory)
            command = [sys.executable, str(ROOT / 'CrashDumpConfig.py'), '--help']
            baseline = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                      text=True, timeout=15)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertTrue(marker.is_file(), 'Fixture must demonstrate ordinary inherited startup')
            marker.unlink()
            for filename in HELPERS:
                commands = source_commands(filename)
                self.assertEqual(len(commands), 1 if filename.startswith('Install-GPU') else 2)
                for flags in commands:
                    with self.subTest(launcher=filename, flags=flags):
                        # Use the actual harmless public helper; --help exits
                        # before any registry access or elevation check.
                        result = subprocess.run([command[0], *flags, *command[1:]], cwd=ROOT,
                            env=environment, capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn('--include-python', result.stdout)
                        self.assertFalse(marker.exists())

    def test_bootstrap_flags_preserve_explicit_proxy_and_package_index_environment(self):
        environment = dict(os.environ, HTTPS_PROXY='https://fixture-proxy.invalid',
                           PIP_INDEX_URL='https://fixture-index.invalid/simple', PYTHONINSPECT='1')
        command = [sys.executable, *source_commands('Install-GPU-NVIDIA.bat')[0], '-c',
                   'import json,os,sys;print(json.dumps([os.environ["HTTPS_PROXY"],'
                   'os.environ["PIP_INDEX_URL"],sys.flags.ignore_environment,sys.flags.no_user_site]))']
        result = subprocess.run(command, env=environment, input='', capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [environment['HTTPS_PROXY'],
            environment['PIP_INDEX_URL'], 1, 1])

    @unittest.skipUnless(sys.platform == 'win32', 'Actual Windows helper batch files')
    def test_actual_five_batch_entries_forward_arguments_without_startup_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'source helpers & spaces'
            root.mkdir()
            subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', str(root / '.venv')],
                           check=True, capture_output=True, timeout=90)
            outside = root / 'outside'
            outside.mkdir()
            marker = outside / 'hook-ran.txt'
            (outside / 'sitecustomize.py').write_text(
                'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("fixture")\n')
            stub = ('import json,sys\nfrom pathlib import Path\n'
                    'Path("result.json").write_text(json.dumps({"args":sys.argv[1:],'
                    '"ignore_environment":sys.flags.ignore_environment,'
                    '"no_user_site":sys.flags.no_user_site}))\n')
            for script, _ in HELPERS.values():
                (root / script).write_text(stub, encoding='utf-8')
            environment = dict(os.environ, PYTHONPATH=str(outside), PYTHONHOME=str(outside), PYTHONINSPECT='1')
            for filename, (_, arguments) in HELPERS.items():
                with self.subTest(launcher=filename):
                    shutil.copyfile(ROOT / filename, root / filename)
                    result = subprocess.run(['cmd.exe', '/d', '/c', filename], cwd=root,
                        env=environment, input='\n', capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(json.loads((root / 'result.json').read_text()), {
                        'args': arguments, 'ignore_environment': 1, 'no_user_site': 1})
                    self.assertFalse(marker.exists())
                    (root / 'result.json').unlink()


if __name__ == '__main__':
    unittest.main()
