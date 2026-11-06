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
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
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
    key = os.path.normcase(str(path.parent.resolve() / path.name))
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
