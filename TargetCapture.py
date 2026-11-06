"""Safe parent-side wrappers for isolated target-window capture/inspection."""
from __future__ import annotations

import json
import math
import os
import subprocess
import time

from Colors import DATA_DIR
from RuntimePaths import atomic_write_text, helper_command, is_finite_number
from LocalSanitization import sanitize_text

BASE=DATA_DIR
MAX_HELPER_LOG_CHARS = 64 * 1024


def _output_text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value or '')


def _helper_log_text(command, result, failure=None):
    note = '' if failure is None else f'Failure: {type(failure).__name__}: {failure}\n'
    if failure is not None:
        note += '\n'.join(getattr(failure, '__notes__', ()))
    text = sanitize_text(f'Command: {command!r}\nExit: {result.returncode}\n{note}\nSTDOUT:\n{_output_text(result.stdout)}\n\nSTDERR:\n{_output_text(result.stderr)}')
    if len(text) > MAX_HELPER_LOG_CHARS:
        marker = '\n[long helper output truncated]\n'
        keep = (MAX_HELPER_LOG_CHARS - len(marker)) // 2
        text = text[:keep] + marker + text[-keep:]
    return text


def _save_helper_log(command, result, failure=None):
    try:
        log_dir = BASE / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(log_dir / 'ImageDrawBot-target-probe.log', _helper_log_text(command, result, failure))
    except Exception:
        pass  # Diagnostic storage must not replace the process/protocol outcome.


def _cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('The target-window check was cancelled.')


def _stop_helper(process, error):
    """Bounded cleanup after interruption; preserve the original operation error."""
    failures = []
    try:
        if process.poll() is None:
            try:
                process.terminate()
            except Exception as cleanup_error:
                failures.append(cleanup_error)
            try:
                process.wait(timeout=.5)
            except Exception:
                try:
                    process.kill()
                except Exception as cleanup_error:
                    failures.append(cleanup_error)
                try:
                    process.wait(timeout=1)
                except Exception as cleanup_error:
                    failures.append(cleanup_error)
    except Exception as cleanup_error:
        failures.append(cleanup_error)
    finally:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception as cleanup_error:
                    failures.append(cleanup_error)
    if failures:
        # Error notes are later sanitized with the whole diagnostic record.
        error.add_note('Target helper cleanup also reported: ' + '; '.join(str(item) for item in failures))


def _run_cancellable(command, timeout, flags, cancelled):
    _cancelled(cancelled)
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(command, cwd=BASE, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
        errors='replace', creationflags=flags)
    out = err = None
    try:
        while True:
            _cancelled(cancelled)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout, output=out, stderr=err)
            try:
                out, err = process.communicate(timeout=min(.1, remaining))
                break
            except subprocess.TimeoutExpired as pending:
                out, err = pending.output, pending.stderr
        _cancelled(cancelled)
        return subprocess.CompletedProcess(command, process.returncode, out, err)
    except BaseException as error:
        _stop_helper(process, error)
        # TimeoutExpired carries bytes even with text=True. Retain available
        # partial output for a sanitized failure log instead of the old run.
        error._helper_stdout, error._helper_stderr = out, err
        error._helper_returncode = process.returncode
        raise


def _window_rectangle(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or not all(type(item) is int and -(2**31) <= item < 2**31 for item in value)):
        return None
    left, top, right, bottom = value
    return tuple(value) if right > left and bottom > top else None


def _native_id(value, bits):
    return type(value) is int and 0 < value < 2**bits


def _describe_exit(code):
    if code is None:return 'unknown exit code'
    unsigned=code & 0xFFFFFFFF
    known={
        0xC0000005:'Access Violation (0xC0000005)',
        0xC0000409:'Stack/fast-fail (0xC0000409)',
        0xC00000FD:'Stack overflow (0xC00000FD)',
    }
    return known.get(unsigned, f'exit code {code} / 0x{unsigned:08X}')


def _run(command, timeout=8, *, cancelled=None):
    if not is_finite_number(timeout) or not 0 < timeout <= 120:
        raise ValueError('The target-window check needs a finite timeout between zero and 120 seconds.')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    if cancelled is not None and not callable(cancelled):
        raise TypeError('cancelled must be a callable or None.')
    try:
        if cancelled is None:
            result=subprocess.run(command,cwd=BASE,capture_output=True,text=True,
                                  encoding='utf-8',errors='replace',timeout=timeout,
                                  creationflags=flags)
        else:
            result = _run_cancellable(command, timeout, flags, cancelled)
    except BaseException as error:
        failed = subprocess.CompletedProcess(command, getattr(error, '_helper_returncode', None),
            getattr(error, '_helper_stdout', getattr(error, 'stdout', None)),
            getattr(error, '_helper_stderr', getattr(error, 'stderr', None)))
        _save_helper_log(command, failed, error)
        if isinstance(error, subprocess.TimeoutExpired):
            raise InterruptedError('The target-window check took too long and was stopped.') from error
        raise
    _save_helper_log(command, result)
    _cancelled(cancelled)
    payload=None
    for line in (result.stdout or '').splitlines():
        try:
            value=json.loads(line)
            if isinstance(value,dict):payload=value
        except (ValueError,TypeError,RecursionError):pass
    if result.returncode!=0:
        if payload and payload.get('error'):raise ValueError(payload['error'])
        raise OSError(f'The Windows target check exited unexpectedly: {_describe_exit(result.returncode)}.')
    if not payload or payload.get('ok') is not True:
        raise OSError('The Windows check returned no valid response.')
    handle=payload.get('handle');rect=payload.get('rect');client=payload.get('client_rect')
    rect = _window_rectangle(rect)
    client = _window_rectangle(client)
    if not _native_id(handle, 64) or rect is None or client is None:
        raise OSError('The Windows check returned invalid window data.')
    target_pid = payload.get('target_pid')
    if target_pid is not None and not _native_id(target_pid, 32):
        raise OSError('The Windows check returned an invalid process identifier.')
    owner_root_handle = payload.get('owner_root_handle')
    if owner_root_handle is not None and not _native_id(owner_root_handle, 64):
        raise OSError('The Windows check returned an invalid owner window.')
    dpi=payload.get('dpi')
    if dpi is not None and (type(dpi) is not int or not 48<=dpi<=768):
        raise OSError('The Windows check returned invalid DPI data.')
    scale = payload.get('dpi_scale')
    if scale is not None and (type(scale) not in (int, float) or not 0.5 <= scale <= 8
                              or (dpi is not None and not math.isclose(scale, dpi/96, abs_tol=0.001))):
        raise OSError('The Windows check returned inconsistent DPI scaling.')
    monitor_rect=payload.get('monitor_rect');work_rect=payload.get('monitor_work_rect')
    _cancelled(cancelled)
    return {'handle':handle,'rect':rect,'client_rect':client,
            'target_pid':target_pid,'dpi':dpi,
            'owner_root_handle':owner_root_handle,
            'dpi_source':payload.get('dpi_source'),'dpi_scale':scale,
            'monitor_rect':_window_rectangle(monitor_rect),'monitor_work_rect':_window_rectangle(work_rect)}


def capture_target_metadata_isolated(area,exclude_pid=None,timeout=8, *, cancelled=None):
    if (not isinstance(area, (tuple, list)) or len(area) != 4
            or any(type(value) is not int for value in area)):
        raise ValueError('The target area must contain four integer coordinates/dimensions.')
    x,y,w,h=area
    if (w <= 0 or h <= 0 or _window_rectangle((x, y, x+w, y+h)) is None):
        raise ValueError('The target area must have positive dimensions within Windows coordinate limits.')
    excluded = os.getpid() if exclude_pid is None else exclude_pid
    if not _native_id(excluded, 32):
        raise ValueError('The excluded process identifier must be a valid process ID.')
    command=helper_command('target','--area',str(x),str(y),str(w),str(h),
                           '--exclude-pid',str(excluded))
    return _run(command,timeout,cancelled=cancelled)


def capture_target_isolated(area,exclude_pid=None,timeout=8, *, cancelled=None):
    metadata=capture_target_metadata_isolated(area,exclude_pid,timeout,cancelled=cancelled)
    return metadata['handle'],metadata['rect']


def probe_handle_isolated(handle,timeout=8, *, cancelled=None):
    if not _native_id(handle, 64):
        raise ValueError('A valid target window handle is required.')
    command=helper_command('target','--handle',str(int(handle)))
    result = _run(command,timeout,cancelled=cancelled)
    if result['handle'] != handle:
        raise OSError('The Windows check returned a different target window.')
    return result
