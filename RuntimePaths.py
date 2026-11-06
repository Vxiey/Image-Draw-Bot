"""Runtime path and atomic-file helpers for source and PyInstaller builds."""
from __future__ import annotations

import errno
import json
import math
import os
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import threading
import time

_FILE_LOCKS = tuple(threading.RLock() for _ in range(32))
_HELD_FILES = threading.local()
# Logical file transactions may hold a stripe while publishing multiple paths.
# Publication must never acquire another stripe: a different logical writer can
# already hold it while waiting to publish. Both ordinary and file-set writes
# instead use this reentrant lock, always after any logical transaction locks.
_PUBLICATION_LOCK = threading.RLock()


class FileSetTransactionError(OSError):
    """A staged file-set publish failed; any recovery backups are retained."""
    def __init__(self, message, recovery_paths=()):
        super().__init__(message)
        self.recovery_paths = tuple(recovery_paths)


def _path_lock_key(path):
    return os.path.normcase(str(path.parent.resolve() / path.name))


def _replace_with_retry(source: Path, destination: Path) -> None:
    """Serialize publishers; briefly retry Windows' transient sharing failures."""
    with _PUBLICATION_LOCK:
        for attempt in range(10):
            try:
                os.replace(source, destination)
                return
            except OSError as error:
                if (sys.platform != 'win32' or getattr(error, 'winerror', None) not in (5, 32, 33)
                        or attempt == 9):
                    raise
                # Antivirus/indexer readers and another process can briefly keep
                # the old destination delete-pending. Never delete it first or
                # fall back to a partial in-place write; permanent denial still
                # raises after at most 0.65 seconds of retry delays.
                time.sleep(min(.01 * (2 ** attempt), .10))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def source_dir() -> Path:
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return source_dir()


def resource_path(name: str) -> Path:
    return resource_dir() / name


def data_dir() -> Path:
    """Return the writable Image Draw Bot data directory."""
    if is_frozen():
        base = Path((os.environ.get("LOCALAPPDATA") or str(Path.home())))
        root = base / "ImageDrawBot"
    else:
        root = source_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Durably replace a small text file without leaving a half-written config.

    The temporary file is created in the same directory so ``os.replace`` stays
    atomic on Windows. A unique temp name also prevents collisions between a
    normal settings save and a crash/reporting save.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(str(text))
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError as error:
                # Some redirected/network locations do not support fsync. The
                # replace is still safer than writing the destination in place.
                if error.errno not in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}:
                    raise
        _replace_with_retry(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def replace_text_files(changes) -> None:
    """Stage a set of text replacements/deletions and roll back on exceptions.

    This coordinates callers in this process. Each rename is atomic; the whole
    set is not a filesystem transaction and cannot guarantee crash atomicity.
    Failed rollback backups are deliberately left available for recovery.
    """
    normalized = []
    seen = set()
    for path, text in changes.items():
        path = Path(path)
        key = _path_lock_key(path)
        if key in seen or (text is not None and not isinstance(text, str)):
            raise ValueError('File-set destinations must be unique and values must be text or None.')
        seen.add(key)
        normalized.append((path, text))
    with _PUBLICATION_LOCK:
        entries = []
        rollback_failed = set()
        try:
            for path, text in normalized:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and not path.is_file():
                    raise OSError(f'Destination is not a file: {path.name}')
                entry = dict(path=path, staged=None, backup=None, moved=False, published=False)
                entries.append(entry)
                if text is not None:
                    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.import', dir=path.parent)
                    os.close(fd)
                    entry['staged'] = Path(name)
                    atomic_write_text(entry['staged'], text)
                if path.exists() or path.is_symlink():
                    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.backup', dir=path.parent)
                    os.close(fd)
                    entry['backup'] = Path(name)
            for entry in entries:
                if entry['backup'] is not None:
                    _replace_with_retry(entry['path'], entry['backup'])
                    entry['moved'] = True
                if entry['staged'] is not None:
                    _replace_with_retry(entry['staged'], entry['path'])
                    entry['published'] = True
        except BaseException as error:
            for entry in reversed(entries):
                try:
                    if entry['moved']:
                        _replace_with_retry(entry['backup'], entry['path'])
                    elif entry['published']:
                        entry['path'].unlink(missing_ok=True)
                except OSError:
                    rollback_failed.add(entry['backup'] or entry['path'])
            if not isinstance(error, Exception):
                if rollback_failed:
                    error.add_note('File-set rollback retained recovery paths: ' + ', '.join(map(str, sorted(rollback_failed))))
                raise
            if rollback_failed:
                names = ', '.join(str(path) for path in sorted(rollback_failed))
                raise FileSetTransactionError(f'File update failed and could not be fully rolled back. Retained recovery paths: {names}',
                                              sorted(rollback_failed)) from error
            raise FileSetTransactionError(f'File update failed; previous files were restored: {error}') from error
        finally:
            for entry in entries:
                for temporary in (entry['staged'], entry['backup']):
                    if temporary is not None and temporary not in rollback_failed:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass


def is_finite_number(value) -> bool:
    """Whether a JSON number fits the finite floating-point calculation domain."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def read_json(path: Path, *, max_bytes: int = 4 * 1024 * 1024,
              max_depth: int = 32, max_items: int = 100000):
    """Read a bounded local JSON document without ambiguous or nonfinite data."""
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON object key.')
            result[key] = value
        return result

    with Path(path).open('rb') as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('Local state exceeds the supported file size.')
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=object_pairs)
    except RecursionError as error:
        raise ValueError('Local state is too deeply nested.') from error
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > max_depth or count > max_items:
            raise ValueError('Local state contains too many nested values.')
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        if len(pending) + count + len(children) > max_items:
            raise ValueError('Local state contains too many values.')
        pending.extend((child, depth + 1) for child in children)
        if type(item) is float and not math.isfinite(item):
            raise ValueError('Local state numbers must be finite.')
    return value


@contextmanager
def file_transaction(path: Path, *, timeout: float = 5.0):
    """Serialize a local read–modify–replace operation across threads/processes.

    The stable sidecar is deliberately retained: removing a lock file could let
    another process lock a different inode while an earlier writer still owns it.
    Nested use by the same thread is supported for one-time migrations.
    """
    if not is_finite_number(timeout) or not 0 <= timeout <= threading.TIMEOUT_MAX:
        raise ValueError('File transaction timeout must be a finite, nonnegative supported duration.')
    path = Path(path)
    key = _path_lock_key(path)
    deadline = time.monotonic() + timeout
    lock = _FILE_LOCKS[hash(key) % len(_FILE_LOCKS)]
    if not lock.acquire(timeout=max(0.0, timeout)):
        raise TimeoutError('Another operation is updating this local file.')
    try:
        held = getattr(_HELD_FILES, 'paths', None)
        if held is None:
            held = _HELD_FILES.paths = set()
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_name(path.name + '.lock').open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b'\0'); stream.flush()
                def acquire():
                    stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                def release():
                    stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                def acquire():
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                def release():
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            while True:
                try:
                    acquire()
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Another process is updating this local file.') from error
                    time.sleep(min(.02, max(0.0, deadline - time.monotonic())))
            held.add(key)
            failure = None
            try:
                yield
            except BaseException as error:
                failure = error
                raise
            finally:
                held.remove(key)
                try:
                    release()
                except OSError as error:
                    if failure is None:
                        raise
                    failure.add_note(f'File lock cleanup also failed: {type(error).__name__}.')
    finally:
        lock.release()


def helper_command(helper: str, *args: object) -> list[str]:
    """Build a helper command that works both from source and a frozen EXE.

    In a PyInstaller build we re-launch the same ImageDrawBot.exe with an internal
    helper switch. This avoids depending on python.exe or loose .py files.
    """
    switches = {
        "mouse": "--internal-mouse-probe",
        "target": "--internal-target-probe",
        "palette": "--internal-palette-calibration",
        "exactcolor": "--internal-exact-color-calibration",
    }
    scripts = {
        "mouse": "MouseProbe.py",
        "target": "TargetProbe.py",
        "palette": "GetColorPositions.py",
        "exactcolor": "ExactColorCalibration.py",
    }
    if helper not in switches:
        raise ValueError(f"Unknown helper: {helper}")
    tail = [str(value) for value in args]
    if is_frozen():
        return [sys.executable, switches[helper], *tail]
    return [sys.executable, str(source_dir() / scripts[helper]), *tail]
