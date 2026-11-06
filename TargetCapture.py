"""Safe parent-side wrappers for isolated target-window capture/inspection."""
from __future__ import annotations

import json
import math
import os
import subprocess

from Colors import DATA_DIR
from RuntimePaths import helper_command

BASE=DATA_DIR


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


def _run(command, timeout=8):
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    try:
        result=subprocess.run(command,cwd=BASE,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=timeout,
                              creationflags=flags)
    except subprocess.TimeoutExpired as error:
        raise InterruptedError('The target-window check took too long and was stopped.') from error
    try:
        log_dir=BASE/'logs';log_dir.mkdir(parents=True,exist_ok=True)
        (log_dir/'ImageDrawBot-target-probe.log').write_text(
            f'Command: {command!r}\nExit: {result.returncode}\n\nSTDOUT:\n{result.stdout or ""}\n\nSTDERR:\n{result.stderr or ""}',
            encoding='utf-8')
    except OSError:pass
    payload=None
    for line in (result.stdout or '').splitlines():
        try:
            value=json.loads(line)
            if isinstance(value,dict):payload=value
        except (json.JSONDecodeError,TypeError):pass
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
    dpi=payload.get('dpi')
    if dpi is not None and (type(dpi) is not int or not 48<=dpi<=768):
        raise OSError('The Windows check returned invalid DPI data.')
    scale = payload.get('dpi_scale')
    if scale is not None and (type(scale) not in (int, float) or not 0.5 <= scale <= 8
                              or (dpi is not None and not math.isclose(scale, dpi/96, abs_tol=0.001))):
        raise OSError('The Windows check returned inconsistent DPI scaling.')
    monitor_rect=payload.get('monitor_rect');work_rect=payload.get('monitor_work_rect')
    return {'handle':handle,'rect':rect,'client_rect':client,
            'target_pid':target_pid,'dpi':dpi,
            'dpi_source':payload.get('dpi_source'),'dpi_scale':scale,
            'monitor_rect':_window_rectangle(monitor_rect),'monitor_work_rect':_window_rectangle(work_rect)}


def capture_target_metadata_isolated(area,exclude_pid=None,timeout=8):
    x,y,w,h=map(int,area)
    command=helper_command('target','--area',str(x),str(y),str(w),str(h),
                           '--exclude-pid',str(int(exclude_pid or os.getpid())))
    return _run(command,timeout)


def capture_target_isolated(area,exclude_pid=None,timeout=8):
    metadata=capture_target_metadata_isolated(area,exclude_pid,timeout)
    return metadata['handle'],metadata['rect']


def probe_handle_isolated(handle,timeout=8):
    if not _native_id(handle, 64):
        raise ValueError('A valid target window handle is required.')
    command=helper_command('target','--handle',str(int(handle)))
    result = _run(command,timeout)
    if result['handle'] != handle:
        raise OSError('The Windows check returned a different target window.')
    return result
