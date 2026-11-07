"""Private, explicit source-startup setup used by Start.bat.

The invoking Python only creates the private environment. Dependency changes,
optional GPU setup and the application run with its verified interpreter.
"""
from __future__ import annotations

import argparse
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


def start_source(root=ROOT, *, update=False, gpu=False):
    """Own the private environment through setup and the launched app's exit.

    A second Start/Update must not run pip against an environment currently
    being created, repaired or used by the first source application. The
    stable lock lives in the already excluded build directory, outside .venv
    so it also protects first-time environment creation.
    """
    root = Path(root).resolve()
    acquired = False
    try:
        with file_transaction(root / 'build' / '.source-startup', timeout=0.):
            acquired = True
            return _start_source(root, update=update, gpu=gpu)
    except TimeoutError as error:
        if acquired:
            raise
        raise SetupEnvironmentError(
            'Another source startup or application is already using this environment. '
            'Close it before starting or updating this checkout again.'
        ) from error


def _start_source(root, *, update=False, gpu=False):
    if not (root/'DrawBot.py').is_file():
        raise SetupEnvironmentError('Required source files are missing. Extract the entire source ZIP before starting.')
    try:
        requirements = checked_requirements(root/'requirements.txt')
    except SetupEnvironmentError as error:
        raise SetupEnvironmentError('The source requirements file is missing or invalid; no packages were changed.') from error
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
        print('Creating the private Python environment…')
        _run([sys.executable, '-I', '-m', 'venv', str(directory)],
             root=root, environment=environment, check=True)

    def runner(command, *, timeout=30.0, env=None, capture_stderr=False):
        return _run(command, root=root, environment=environment if env is None else env,
                    capture=True, timeout=timeout)

    require_private_environment(python, directory, runner)
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
    args = parser.parse_args(argv)
    try:
        return start_source(ROOT, update=args.update, gpu=args.gpu)
    except (OSError, SetupEnvironmentError, subprocess.SubprocessError) as error:
        print(f'Source startup failed: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
