"""One private Python environment for release tests and frozen packaging."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading

from GpuSetupRuntime import SetupEnvironmentError, checked_requirements, pip_command, pip_environment


class BuildEnvironmentError(RuntimeError):
    pass


@dataclass
class _WorkspaceOwner:
    process: int
    thread: int
    acquired: bool = False


_WORKSPACE_GUARD = threading.Lock()
_WORKSPACE_OWNERS: dict[str, _WorkspaceOwner] = {}
_BUSY_MESSAGE = ('Another build is already using this source workspace. '
                 'Wait for that build to finish before trying again.')


def _workspace_key(root):
    return os.path.normcase(str(Path(root).resolve()))


def require_build_workspace(root):
    """Only the current CLI's owner may mutate its shared builder and outputs."""
    with _WORKSPACE_GUARD:
        owner = _WORKSPACE_OWNERS.get(_workspace_key(root))
        if (owner is None or not owner.acquired or owner.process != os.getpid()
                or owner.thread != threading.get_ident()):
            raise BuildEnvironmentError('Build preparation and packaging require an active workspace build session.')


@contextmanager
def build_workspace(root):
    """Reserve one checkout through environment setup, tests and publication.

    The stable sidecar stays under PyInstaller's excluded build directory. It
    is never removed: another process must not acquire a replacement inode
    while the previous owner still holds the original one. Internal build APIs
    reuse this owner; a second CLI entry cannot silently nest or skip the lock.
    """
    root = Path(root).resolve()
    key = _workspace_key(root)
    owner = _WorkspaceOwner(os.getpid(), threading.get_ident())
    stream = None
    unlock = None
    failure = None
    try:
        with _WORKSPACE_GUARD:
            existing = _WORKSPACE_OWNERS.get(key)
            if existing is not None and existing.process == owner.process:
                raise BuildEnvironmentError(_BUSY_MESSAGE)
            _WORKSPACE_OWNERS[key] = owner
        work = root/'build'
        work.mkdir(parents=True, exist_ok=True)
        stream = (work/'.workspace-build.lock').open('a+b')
        if os.name == 'nt':
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            def acquire():
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BuildEnvironmentError(_BUSY_MESSAGE) from error
            raise
        unlock = release
        with _WORKSPACE_GUARD:
            owner.acquired = True
        yield root
    except BaseException as error:
        failure = error
        raise
    finally:
        with _WORKSPACE_GUARD:
            owner.acquired = False
        cleanup_error = None
        for cleanup in (unlock, stream.close if stream is not None else None):
            if cleanup is not None:
                try:
                    cleanup()
                except OSError as error:
                    if cleanup_error is None:
                        cleanup_error = error
        with _WORKSPACE_GUARD:
            if _WORKSPACE_OWNERS.get(key) is owner:
                del _WORKSPACE_OWNERS[key]
        if cleanup_error is not None:
            if failure is None:
                raise cleanup_error
            failure.add_note(f'Build workspace lock cleanup also failed: {type(cleanup_error).__name__}.')


@dataclass(frozen=True)
class Builder:
    python: Path
    root: Path
    environment: dict[str, str]

    def source_environment(self) -> dict[str, str]:
        environment = dict(self.environment)
        # Source entry points need this explicitly trusted checkout, not an
        # inherited PYTHONPATH, user site or unrelated working directory.
        environment['PYTHONPATH'] = str(self.root)
        return environment


_BUILDER_PROBE = (
    "import json,sys,site; print(json.dumps({"
    "'prefix':sys.prefix,'base_prefix':getattr(sys,'base_prefix',sys.prefix),"
    "'version':list(sys.version_info[:2]),'bits':64 if sys.maxsize>2**32 else 32,"
    "'user_site':site.ENABLE_USER_SITE,'site_packages':site.getsitepackages(),"
    "'frozen':bool(getattr(sys,'frozen',False))}))"
)


def _startup_environment():
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith('PYTHON')}
    environment.update(PYTHONNOUSERSITE='1', PYTHONSAFEPATH='1')
    return environment


def _probe(command, *, timeout=30.0, env=None, capture_stderr=False, cwd=None):
    # Configuration can contain credentials; capture it for the shared pip
    # policy parser instead of copying it into a build transcript.
    return subprocess.run(command, cwd=cwd, env=env, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding='utf-8', errors='replace', check=False)


def _verify_builder(python: Path, directory: Path, root: Path):
    try:
        result = _probe([str(python), '-I', '-c', _BUILDER_PROBE],
                        cwd=root, env=_startup_environment())
        if result.returncode or not isinstance(result.stdout, str) or len(result.stdout)>16384:
            raise ValueError('invalid interpreter response')
        details = json.loads(result.stdout)
        prefix = details['prefix']
        base_prefix = details['base_prefix']
        version = details['version']
        sites = details['site_packages']
        if (not isinstance(prefix, str) or not Path(prefix).is_absolute()
                or not isinstance(base_prefix, str) or not Path(base_prefix).is_absolute()
                or Path(prefix).resolve()!=directory.resolve()
                or Path(prefix).resolve()==Path(base_prefix).resolve()
                or not isinstance(version, list) or len(version)!=2
                or any(type(item) is not int for item in version)
                or tuple(version)<(3,11) or details['bits']!=64
                or not isinstance(sites, list) or not sites
                or any(not isinstance(path, str) or not Path(path).is_absolute()
                       or not Path(path).resolve().is_relative_to(directory.resolve()) for path in sites)
                or details['user_site'] is not False or details['frozen'] is not False):
            raise ValueError('unexpected interpreter environment')
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError) as error:
        raise BuildEnvironmentError(
            'The private .build-venv must be an isolated 64-bit Python 3.11+ environment. '
            'Rename .build-venv and run the build again to recreate it.'
        ) from error


def prepare_builder(root: Path, *, gpu=False, include_tests=False) -> Builder:
    """Install only into the actual verified private builder, never the caller."""
    root = Path(root).resolve()
    require_build_workspace(root)
    requirement_names = ['requirements.txt', 'requirements-build.txt', 'requirements-gpu-universal.txt']
    if include_tests:
        requirement_names.append('requirements-dev.txt')
    if gpu:
        requirement_names.append('requirements-gpu-nvidia.txt')
    try:
        for name in requirement_names:
            checked_requirements(root/name)
    except SetupEnvironmentError as error:
        raise BuildEnvironmentError('The build requirements are missing or invalid; no packages were changed.') from error
    directory = root/'.build-venv'
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and (not stat.S_ISDIR(metadata.st_mode)
                                 or getattr(metadata, 'st_reparse_tag', 0)):
        raise BuildEnvironmentError('The private .build-venv must be a regular directory, not a linked environment.')
    python = directory/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    if not python.is_file():
        subprocess.run([sys.executable, '-I', '-m', 'venv', str(directory)],
                       cwd=root, env=_startup_environment(), check=True)
    _verify_builder(python, directory, root)

    def runner(command, **options):
        return _probe(command, cwd=root, **options)

    try:
        with pip_environment(str(python), runner) as policy:
            environment = policy.for_command('install')
            subprocess.run(pip_command(str(python), 'install', '--upgrade', 'pip'),
                           cwd=root, env=environment, check=True)
            requirements = [argument for name in requirement_names for argument in ('-r', str(root/name))]
            subprocess.run(pip_command(str(python), 'install', '--upgrade', '--upgrade-strategy',
                                       'eager', *requirements),
                           cwd=root, env=environment, check=True)
            return Builder(python, root, dict(environment))
    except SetupEnvironmentError as error:
        raise BuildEnvironmentError('Could not verify the private build package configuration; no packages were changed.') from error
