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

_LOG_STREAM = None
_INSTALLED = False
_LOG_LOCK = threading.RLock()
_MAX_LOG_BYTES = 2 * 1024 * 1024

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


def _rotate_if_large(path: Path, limit: int = _MAX_LOG_BYTES) -> None:
    """Keep logs bounded so a long-running beta cannot fill the user profile."""
    try:
        if not path.exists() or path.stat().st_size <= limit:
            return
        backup = path.with_suffix(path.suffix + '.1')
        backup.unlink(missing_ok=True)
        os.replace(path, backup)
    except OSError:
        # Diagnostics must never become a reason the app cannot start.
        return


def _looks_like_error(message: str) -> bool:
    text=' ' + str(message or '').casefold()
    return any(marker in text for marker in _ERROR_MARKERS)


def _append_error(message, *, category='runtime'):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_if_large(DEBUG_ERROR_LOG)
        with DEBUG_ERROR_LOG.open('a', encoding='utf-8') as stream:
            stream.write(f'[{_stamp()}] [{category}] {message}\n')
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
        text=str(message)
        with _LOG_LOCK:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            _rotate_if_large(SESSION_LOG)
            with SESSION_LOG.open('a', encoding='utf-8') as stream:
                stream.write(f'[{_stamp()}] {text}\n')
            if force_error or _looks_like_error(text):
                _append_error(text, category=error_category)
    except Exception:
        pass


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
        _LOG_STREAM.write('\n' + '=' * 72 + '\n')
        _LOG_STREAM.write(f'[{_stamp()}] Image Draw Bot start\n')
        _LOG_STREAM.write(f'Python: {sys.version.replace(chr(10), " ")}\n')
        _LOG_STREAM.write(f'Executable: {sys.executable}\n')
        _LOG_STREAM.write(f'Platform: {platform.platform()}\n')
        _LOG_STREAM.write(f'PID: {os.getpid()}\n')
        _LOG_STREAM.flush()
        faulthandler.enable(file=_LOG_STREAM, all_threads=True)
    except Exception:
        _LOG_STREAM = None

    previous_hook = sys.excepthook

    def exception_hook(exc_type, exc, tb):
        try:
            rendered=''.join(traceback.format_exception(exc_type, exc, tb))
            _append_error('Unhandled exception\n' + rendered, category='unhandled-main-thread')
            if _LOG_STREAM:
                _LOG_STREAM.write(f'[{_stamp()}] Unhandled exception\n')
                traceback.print_exception(exc_type, exc, tb, file=_LOG_STREAM)
                _LOG_STREAM.flush()
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
                name = getattr(getattr(args, 'thread', None), 'name', '<unknown>')
                rendered=''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
                _append_error(f'Unhandled thread exception: {name}\n{rendered}', category='unhandled-worker-thread')
                if _LOG_STREAM:
                    _LOG_STREAM.write(f'[{_stamp()}] Unhandled thread exception: {name}\n')
                    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=_LOG_STREAM)
                    _LOG_STREAM.flush()
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
                content = RUN_MARKER.read_text(encoding='utf-8')
            except OSError:
                content = ''
            if content.split() and content.split()[0] == f'pid={os.getpid()}':
                RUN_MARKER.unlink(missing_ok=True)
            RUN_MARKER_OWNED = False
        log_event('Clean shutdown recorded.')
    except Exception:
        pass
