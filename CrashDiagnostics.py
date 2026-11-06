"""Crash/fault logging that remains useful even for native ctypes failures."""
from __future__ import annotations

import faulthandler
import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path

from RuntimePaths import atomic_write_text, data_dir
from LocalSanitization import sanitize_text

_LOG_STREAM = None
_INSTALLED = False
_LOG_LOCK = threading.RLock()
_MAX_LOG_BYTES = 2 * 1024 * 1024
_MAX_RECORD_CHARS = 64 * 1024

LOG_DIR = data_dir() / 'logs'
CRASH_LOG = LOG_DIR / 'ImageDrawBot-crash.log'
SESSION_LOG = LOG_DIR / 'ImageDrawBot-session.log'
DEBUG_ERROR_LOG = LOG_DIR / 'ImageDrawBot-debug-errors.log'
RUN_MARKER = LOG_DIR / 'ImageDrawBot-running.marker'
PREVIOUS_RUN_UNCLEAN = False
RUN_MARKER_OWNED = False

_ERROR_MARKERS = (
    ' error', 'error:', 'failed', 'failure', 'exception', 'traceback', 'crash',
    'cuda error', 'gpu error', 'out of memory', 'oom', 'safety stop',
    'calibration failed', 'could not', 'invalid image', 'target closed',
)


def _stamp():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _rotate_if_large(path: Path, limit: int = _MAX_LOG_BYTES, *, incoming_bytes: int = 0) -> bool:
    """Keep logs bounded so a long-running beta cannot fill the user profile."""
    try:
        if not path.exists() or path.stat().st_size + incoming_bytes <= limit:
            return incoming_bytes <= limit
        backup = path.with_suffix(path.suffix + '.1')
        backup.unlink(missing_ok=True)
        os.replace(path, backup)
        return incoming_bytes <= limit
    except OSError:
        # Diagnostics must never become a reason the app cannot start.
        return False


def _looks_like_error(message: str) -> bool:
    text=' ' + str(message or '').casefold()
    return any(marker in text for marker in _ERROR_MARKERS)


def _record_text(message) -> str:
    # Sanitize before shortening: a cut URL/header can otherwise leave a secret
    # suffix whose original context is no longer recognizable.
    text = sanitize_text(str(message))
    if len(text) > _MAX_RECORD_CHARS:
        marker = '\n[long log record truncated]\n'
        keep = (_MAX_RECORD_CHARS - len(marker)) // 2
        text = text[:keep] + marker + text[-keep:]
    return text


def _append_error(message, *, category='runtime'):
    try:
        text = _record_text(message)
        label = _record_text(category).replace('\r', ' ').replace('\n', ' ')[:80]
        record = f'[{_stamp()}] [{label}] {text}\n'
        with _LOG_LOCK:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if _rotate_if_large(DEBUG_ERROR_LOG, incoming_bytes=len(record.encode('utf-8'))):
                with DEBUG_ERROR_LOG.open('a', encoding='utf-8') as stream:
                    stream.write(record)
    except Exception:
        # Debug logging is never allowed to break drawing.
        pass


def log_error(message, *, category='runtime', exc_info=None):
    """Write one error to both the normal session log and consolidated error log."""
    detail=str(message)
    if exc_info:
        try:
            if exc_info is True:
                detail += '\n' + traceback.format_exc()
            elif isinstance(exc_info, tuple) and len(exc_info)==3:
                detail += '\n' + ''.join(traceback.format_exception(*exc_info))
            else:
                detail += '\n' + str(exc_info)
        except Exception:
            pass
    log_event(detail, force_error=True, error_category=category)


def log_event(message, *, force_error=False, error_category='runtime'):
    try:
        text=_record_text(message)
        record=f'[{_stamp()}] {text}\n'
        with _LOG_LOCK:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if _rotate_if_large(SESSION_LOG, incoming_bytes=len(record.encode('utf-8'))):
                with SESSION_LOG.open('a', encoding='utf-8') as stream:
                    stream.write(record)
            if force_error or _looks_like_error(text):
                _append_error(text, category=error_category)
    except Exception:
        pass


def _write_crash_record(record):
    if _LOG_STREAM is None:
        return
    with _LOG_LOCK:
        # Keep faulthandler's descriptor open and stable. Python exceptions are
        # already copied to the rotating error log; they must not grow this
        # native-crash stream indefinitely after its fixed budget is exhausted.
        if os.fstat(_LOG_STREAM.fileno()).st_size + len(record.encode('utf-8')) <= _MAX_LOG_BYTES:
            _LOG_STREAM.write(record)
            _LOG_STREAM.flush()


def install():
    global _LOG_STREAM, _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_if_large(CRASH_LOG)
        _rotate_if_large(SESSION_LOG)
        _rotate_if_large(DEBUG_ERROR_LOG)
        _LOG_STREAM = CRASH_LOG.open('a', encoding='utf-8', buffering=1)
        _write_crash_record('\n' + '=' * 72 + '\n'
                            f'[{_stamp()}] Image Draw Bot start\n'
                            f'Python: {sys.version.replace(chr(10), " ")}\n'
                            f'Executable: {_record_text(sys.executable)}\n'
                            f'Platform: {platform.platform()}\n'
                            f'PID: {os.getpid()}\n')
        faulthandler.enable(file=_LOG_STREAM, all_threads=True)
    except Exception:
        _LOG_STREAM = None

    previous_hook = sys.excepthook

    def exception_hook(exc_type, exc, tb):
        try:
            rendered=_record_text(''.join(traceback.format_exception(exc_type, exc, tb)))
            _append_error('Unhandled exception\n' + rendered, category='unhandled-main-thread')
            _write_crash_record(f'[{_stamp()}] Unhandled exception\n' + rendered)
        except Exception:
            pass
        finally:
            try:
                previous_hook(exc_type, exc, tb)
            except Exception:
                pass

    sys.excepthook = exception_hook

    if hasattr(threading, 'excepthook'):
        previous_thread_hook = threading.excepthook

        def thread_hook(args):
            try:
                name = _record_text(getattr(getattr(args, 'thread', None), 'name', '<unknown>'))[:200]
                rendered=_record_text(''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
                _append_error(f'Unhandled thread exception: {name}\n{rendered}', category='unhandled-worker-thread')
                _write_crash_record(f'[{_stamp()}] Unhandled thread exception: {name}\n' + rendered)
            except Exception:
                pass
            finally:
                try:
                    previous_thread_hook(args)
                except Exception:
                    pass

        threading.excepthook = thread_hook

    log_event(f'Crash diagnostics enabled. Consolidated error log: {DEBUG_ERROR_LOG.name}.')


def begin_run_marker():
    """Claim the clean-shutdown marker after the single-instance lock is held."""
    global PREVIOUS_RUN_UNCLEAN, RUN_MARKER_OWNED
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        PREVIOUS_RUN_UNCLEAN = RUN_MARKER.exists()
        atomic_write_text(RUN_MARKER, f'pid={os.getpid()} started={_stamp()}\n')
        RUN_MARKER_OWNED = True
        log_event(f'Run marker claimed. previous_unclean={PREVIOUS_RUN_UNCLEAN}.')
        if PREVIOUS_RUN_UNCLEAN:
            _append_error('Previous Image Draw Bot run did not record a clean shutdown.', category='previous-unclean-run')
    except OSError as error:
        RUN_MARKER_OWNED = False
        log_error(f'Run marker could not be created: {error}.', category='startup')


def previous_run_unclean():
    return bool(PREVIOUS_RUN_UNCLEAN)


def clean_exit():
    global RUN_MARKER_OWNED
    try:
        if RUN_MARKER_OWNED:
            # Do not delete another process's marker if ownership changed.
            try:
                with RUN_MARKER.open('rb') as marker:
                    raw = marker.read(1025)
                content = raw.decode('utf-8') if len(raw) <= 1024 else ''
            except (OSError, UnicodeError):
                content = ''
            if content.split() and content.split()[0] == f'pid={os.getpid()}':
                RUN_MARKER.unlink(missing_ok=True)
            RUN_MARKER_OWNED = False
        log_event('Clean shutdown recorded.')
    except Exception:
        pass
