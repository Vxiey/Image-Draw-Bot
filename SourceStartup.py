"""Private, explicit source-startup setup used by Start.bat.

The invoking Python only creates the private environment. Dependency changes,
optional GPU setup and the application run with its verified interpreter.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import subprocess
import sys

from GpuSetupRuntime import (SetupEnvironmentError, checked_requirements,
                             pip_command, pip_environment, require_private_environment)
from RuntimePaths import atomic_write_text, file_transaction


ROOT = Path(__file__).resolve().parent
_IMPORT_CHECK = 'import PIL, requests, keyboard, tkinterdnd2, customtkinter, numpy, qrcode'


def _source_environment(root):
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith('PYTHON')}
    environment.update(PYTHONNOUSERSITE='1', PYTHONSAFEPATH='1',
                       PYTHONPATH=str(root), PYTHONFAULTHANDLER='1', PYTHONUNBUFFERED='1')
    return environment


def _run(command, *, root, environment, check=False, capture=False, timeout=None):
    options = dict(cwd=root, env=environment, check=check, timeout=timeout)
    if capture:
        options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding='utf-8', errors='replace')
    return subprocess.run(command, **options)


@contextmanager
def _source_session(root):
    """Share one checkout owner across startup and explicit optional setup."""
    acquired = False
    try:
        with file_transaction(root / 'build' / '.source-startup', timeout=0.):
            acquired = True
            yield
    except TimeoutError as error:
        if acquired:
            raise
        raise SetupEnvironmentError(
            'Another source startup or application is already using this environment. '
            'Close it before starting or updating this checkout again.'
        ) from error


def start_source(root=ROOT, *, update=False, gpu=False):
    """Own the private environment through setup and the launched app's exit.

    A second Start/Update or optional GPU installer must not run pip against
    an environment currently being created, repaired or used by the first
    source application. The stable lock lives in the already excluded build
    directory, outside .venv, so it also protects first-time creation.
    """
    root = Path(root).resolve()
    with _source_session(root):
        return _start_source(root, update=update, gpu=gpu)


def _private_environment(root, *, create):
    directory = root/'.venv'
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and (not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, 'st_reparse_tag', 0) in (0xA0000003, 0xA000000C)):
        raise SetupEnvironmentError('The private .venv must be a regular directory, not a linked environment.')
    python = str(directory/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python'))
    environment = _source_environment(root)
    if not Path(python).is_file():
        if not create:
            raise SetupEnvironmentError('The private .venv was not found. Run Start.bat once first.')
        print('Creating the private Python environment…')
        _run([sys.executable, '-I', '-m', 'venv', str(directory)],
             root=root, environment=environment, check=True)

    def runner(command, *, timeout=30.0, env=None, capture_stderr=False):
        return _run(command, root=root, environment=environment if env is None else env,
                    capture=True, timeout=timeout)

    require_private_environment(python, directory, runner)
    return python, environment, runner


def setup_gpu_source(root=ROOT, *, backend, force=False, require_nvidia=False):
    """Install only one optional backend under the existing checkout owner.

    The selected public helper does not acquire this lock: Start --gpu/update
    already invokes those helpers while its parent owns the same environment.
    """
    scripts = {'nvidia': 'AutoGpuSetup.py', 'universal': 'AutoUniversalGpuSetup.py'}
    if backend not in scripts or (require_nvidia and backend != 'nvidia'):
        raise SetupEnvironmentError('Choose nvidia or universal optional GPU setup; only nvidia accepts --require-nvidia.')
    root = Path(root).resolve()
    with _source_session(root):
        script = root / scripts[backend]
        if not script.is_file():
            raise SetupEnvironmentError('The optional GPU setup helper is missing. Extract the entire source ZIP first.')
        python, environment, _runner = _private_environment(root, create=False)
        command = [python, '-s', str(script), '--ensure']
        if force:
            command.append('--force')
        if require_nvidia:
            command.append('--require-nvidia')
        return _run(command, root=root, environment=environment).returncode


def _start_source(root, *, update=False, gpu=False):
    if not (root/'DrawBot.py').is_file():
        raise SetupEnvironmentError('Required source files are missing. Extract the entire source ZIP before starting.')
    try:
        requirements = checked_requirements(root/'requirements.txt')
    except SetupEnvironmentError as error:
        raise SetupEnvironmentError('The source requirements file is missing or invalid; no packages were changed.') from error
    python, environment, runner = _private_environment(root, create=True)
    directory = root/'.venv'
    marker = directory/'installed-requirements.txt'
    try:
        with marker.open('rb') as stream:
            installed = stream.read(65537)
    except OSError:
        installed = None
    install = update or installed != requirements.encode('utf-8')
    with pip_environment(python, runner) as policy:
        if not install:
            install = bool(_run([python, '-I', '-c', _IMPORT_CHECK],
                root=root, environment=environment).returncode)
        if not install:
            install = bool(_run(pip_command(python, 'check'), root=root,
                environment=policy.for_command('check')).returncode)
        if install:
            print('Checking and installing source dependencies. Internet access is required…')
            install_environment = policy.for_command('install')
            result = _run(pip_command(python, 'install', '--upgrade', 'pip',
                '--disable-pip-version-check', '--timeout', '20', '--retries', '1'),
                root=root, environment=install_environment)
            if result.returncode:
                print('pip could not be updated. Continuing with the installed version.')
            _run(pip_command(python, 'install', '--upgrade', '--upgrade-strategy', 'eager',
                '--disable-pip-version-check', '--timeout', '20', '--retries', '1',
                '-r', str(root/'requirements.txt')), root=root, environment=install_environment, check=True)
            _run(pip_command(python, 'check'), root=root,
                environment=policy.for_command('check'), check=True)
            # Publish the cache stamp only after the private dependency check.
            atomic_write_text(marker, requirements)

    if update or gpu:
        for script, label in (('AutoGpuSetup.py', 'NVIDIA GPU'),
                              ('AutoUniversalGpuSetup.py', 'AMD / Intel GPU')):
            print(f'Checking optional {label} acceleration…')
            command = [python, '-s', str(root/script), '--ensure']
            if update:
                command.append('--force')
            result = _run(command, root=root, environment=environment)
            if result.returncode:
                print(f'Optional {label} setup is unavailable; CPU fallback remains enabled. '
                      'Run Start.bat --gpu to retry.')
    print('Opening Image Draw Bot…')
    return _run([python, '-s', '-X', 'faulthandler', '-u', str(root/'DrawBot.py')],
                root=root, environment=environment).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description='Start Image Draw Bot in its private source environment.')
    parser.add_argument('--update', action='store_true', help='Refresh source and optional GPU dependencies.')
    parser.add_argument('--gpu', action='store_true', help='Explicitly set up optional GPU dependencies.')
    parser.add_argument('--setup-gpu', choices=('nvidia', 'universal'),
                        help='Set up only the selected optional backend in the existing private environment, then exit.')
    parser.add_argument('--force', action='store_true', help='Force the selected --setup-gpu helper to reinstall/update.')
    parser.add_argument('--require-nvidia', action='store_true', help='Fail --setup-gpu nvidia if NVIDIA hardware is absent.')
    args = parser.parse_args(argv)
    if args.setup_gpu and (args.update or args.gpu):
        parser.error('--setup-gpu cannot be combined with --update or --gpu.')
    if (args.force or args.require_nvidia) and not args.setup_gpu:
        parser.error('--force and --require-nvidia require --setup-gpu.')
    if args.require_nvidia and args.setup_gpu != 'nvidia':
        parser.error('--require-nvidia requires --setup-gpu nvidia.')
    try:
        if args.setup_gpu:
            return setup_gpu_source(ROOT, backend=args.setup_gpu,
                                    force=args.force, require_nvidia=args.require_nvidia)
        return start_source(ROOT, update=args.update, gpu=args.gpu)
    except (OSError, SetupEnvironmentError, subprocess.SubprocessError) as error:
        print(f'Source startup failed: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
