"""Isolated Windows mouse probe.

This helper is intentionally launched in a separate process by Image Draw Bot.
If a native Win32/ctypes call fails catastrophically, the GUI process survives
and can report the helper's exit code and log instead of disappearing.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from pathlib import Path


def probe_points(area):
    x, y, w, h = map(int, area)
    if w < 10 or h < 10:
        raise ValueError('The drawing area is too small for the mouse test.')
    cx, cy = x + w // 2, y + h // 2
    step = min(30, max(2, w // 4))
    # Keep every target inside the selected rectangle, even on narrow areas.
    right = min(x + w - 2, cx + step)
    return [(cx, cy), (right, cy), (cx, cy)]


def run_probe(target, area, mouse=None, monitor=None, stop=None, wait=None, report=None):
    points = probe_points(area)
    if mouse is None:
        from WindowsMouse import WindowsMouse
        mouse = WindowsMouse()
    if monitor is None:
        from ScreenGuard import WindowMonitor
        monitor = WindowMonitor()
    if stop is None:
        stop = threading.Event()
    if wait is None:
        def wait(seconds):
            if stop.wait(seconds):
                raise InterruptedError()
    if report is None:
        report = lambda kind, value: None

    from ScreenGuard import GuardedMouse
    guarded = GuardedMouse(mouse, monitor, target)
    positions = []
    try:
        report('status', 'Activating target window...')
        guarded.prepare_target(stop, wait, report)
        report('status', 'Target window is active. Mouse test without clicking is starting.')
        for index, point in enumerate(points, 1):
            if stop.is_set():
                raise InterruptedError()
            guarded.move(*point)
            actual = tuple(map(int, mouse.get_position()))
            tolerance=max(0,min(16,int(getattr(mouse,'position_tolerance',1))))
            if max(abs(actual[i]-point[i]) for i in (0,1))>tolerance:
                raise OSError(f'The mouse test requested {point}, but Windows reported {actual}. Select the area again.')
            positions.append(actual)
            report('status', f'Mouse movement {index}/3 verified: {actual[0]}, {actual[1]}')
            wait(.35)
        return {
            'ok': True,
            'positions': positions,
            'diagnostics': mouse.diagnostics() if hasattr(mouse, 'diagnostics') else {},
        }
    finally:
        if hasattr(guarded,'disarm_input'):guarded.disarm_input()


def emit(kind, value):
    print(json.dumps({'type': kind, 'value': value}, ensure_ascii=False), flush=True)


def main(argv=None):
    from Colors import enable_dpi_awareness
    enable_dpi_awareness()
    parser = argparse.ArgumentParser()
    parser.add_argument('--handle', type=int)
    parser.add_argument('--rect', nargs=4, type=int)
    parser.add_argument('--area', nargs=4, type=int)
    parser.add_argument('--diagnostics-only', action='store_true')
    args = parser.parse_args(argv)

    try:
        from CrashDiagnostics import install, log_event
        install()
        from WindowsMouse import WindowsMouse
        mouse = WindowsMouse()
        if args.diagnostics_only:
            result = {'ok': True, 'diagnostics': mouse.diagnostics()}
            emit('result', result)
            return 0
        if args.handle is None or args.rect is None or args.area is None:
            parser.error('--handle, --rect and --area are required unless --diagnostics-only is used')
        target = (int(args.handle), tuple(args.rect))
        log_event(f'Isolated mouse probe start. target={target!r} area={tuple(args.area)!r}')
        result = run_probe(target, tuple(args.area), mouse=mouse, report=emit)
        log_event(f'Isolated mouse probe success. result={result!r}')
        emit('result', result)
        return 0
    except InterruptedError as error:
        emit('error', str(error) or 'Mouse test cancelled.')
        return 2
    except Exception as error:
        try:
            from CrashDiagnostics import log_event
            log_event(f'Isolated mouse probe failed: {error!r}\n{traceback.format_exc()}')
        except Exception:
            pass
        emit('error', f'{type(error).__name__}: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
