"""Read-only discovery for the first-run canvas guide. No calibration is written."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import PureWindowsPath
import re

from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES, detect_browser_canvas
from BrowserOneClick import _enumerate_windows, _foreground_window_handle
from CalibrationValidation import calibration_screenshot, bounded_number, contained_rect, screen_rect
from ScreenGuard import WindowMonitor
from WindowsSystem import private_system_library


_TITLES = {
    'microsoft-paint': re.compile(r'(?:^|[–—-]\s*)Paint\s*$', re.I),
    'gartic-phone': re.compile(r'\bgartic[\s-]*phone\b', re.I),
    'skribbl': re.compile(r'\bskribbl(?:\.io)?\b', re.I),
    'skribbl-fast': re.compile(r'\bskribbl(?:\.io)?\b', re.I),
    'sketchheads': re.compile(r'\bsketch\s*heads\b', re.I),
    'sketchful': re.compile(r'\bsketchful(?:\.io)?\b', re.I),
}
_BROWSERS = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe',
             'vivaldi.exe', 'chromium.exe', 'librewolf.exe', 'waterfox.exe', 'arc.exe'}


def _process_name(pid):
    """Return only the executable basename for a prospective window owner."""
    kernel = private_system_library('kernel32.dll', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    process = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return ''
    try:
        length = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(length.value)
        if not query(process, 0, buffer, ctypes.byref(length)):
            return ''
        return PureWindowsPath(buffer.value).name.lower()
    finally:
        kernel.CloseHandle(process)


def _cancel(cancelled):
    if cancelled():
        raise InterruptedError('Canvas search cancelled.')


def _title_fingerprint(title):
    # The title can contain a private document or room name. Keep only a
    # digest in the in-memory offer, outside the saved calibration metadata.
    return hashlib.sha256(title.strip().encode('utf-16-le', errors='surrogatepass')).digest()


def _window_title(monitor, handle):
    read = monitor.api.GetWindowTextW
    read.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    read.restype = ctypes.c_int
    title = ctypes.create_unicode_buffer(32768)
    count = read(handle, title, len(title))
    if not 0 < count < len(title) - 1:
        raise ValueError('The drawing window title could not be verified. Find the canvas again.')
    return title.value


def _select_window(profile_key, preferred, cancelled):
    pattern = _TITLES[profile_key]
    allowed = _BROWSERS
    if profile_key == 'microsoft-paint':
        allowed = {'mspaint.exe'}
    elif profile_key == 'gartic-phone':
        allowed = {'chrome.exe'}
    if profile_key == 'sketchheads':
        allowed = allowed | {'discord.exe'}
    matches = []
    for item in _enumerate_windows(exclude_pid=os.getpid()):
        _cancel(cancelled)
        if (preferred is None or item['handle'] == preferred) and pattern.search(item['title']):
            if _process_name(item['pid']) in allowed:
                matches.append(item)
    if not matches:
        if profile_key == 'gartic-phone':
            raise ValueError('Open Gartic Phone in Google Chrome with Artist Tools enabled and show the drawing canvas.')
        raise ValueError('Open the selected drawing app or game and make its canvas visible.')
    if len(matches) != 1:
        foreground = _foreground_window_handle()
        for item in matches:
            if item['handle'] == foreground:
                return item
        raise ValueError('Several drawing windows match. Bring the one you want to the front.')
    return matches[0]


def _inspect_guided_window(profile_key, preferred_handle, previous, cancelled):
    _cancel(cancelled)
    if profile_key not in _TITLES or (profile_key != 'microsoft-paint' and profile_key not in SUPPORTED_BROWSER_PROFILES):
        raise ValueError('Mark the canvas manually for this profile.')
    if previous is not None:
        old = previous.get('target_meta') or {}
        if (previous.get('profile_key') != profile_key or not old.get('handle') or
                preferred_handle not in (None, old['handle'])):
            raise ValueError('The selected drawing target changed. Find the canvas again.')
        preferred_handle = old['handle']
    window = _select_window(profile_key, preferred_handle, cancelled)
    title_fingerprint = _title_fingerprint(window['title'])
    if previous is not None and previous.get('_window_title_fingerprint') != title_fingerprint:
        raise ValueError('The drawing document or tab changed. Find the canvas again.')
    handle = window['handle']
    rect = screen_rect(window['rect'])
    client = screen_rect(window['client_rect'])
    monitor = WindowMonitor()
    target = (handle, rect)
    monitor.lock_target(target)
    pid, thread = monitor._process_identity(handle)
    meta = {'handle': handle, 'rect': rect, 'client_rect': client, 'dpi': monitor.dpi(handle),
            'target_pid': pid, 'target_thread': thread}
    if (pid != window['pid'] or monitor.client_rectangle(handle) != client or
            meta['dpi'] != window['dpi']):
        raise ValueError('The drawing window changed during discovery. Find the canvas again.')
    if previous is not None and any(old.get(k) != v for k, v in meta.items()):
        raise ValueError('The window moved or its display scale changed. Find the canvas again.')
    _cancel(cancelled)
    return meta, title_fingerprint, monitor


def recheck_guided_window(accepted, *, monitor=None, cancelled=lambda: False):
    """Recheck the confirmed window and document identity without capturing or activating it."""
    _cancel(cancelled)
    if not isinstance(accepted, dict) or not (accepted.get('target_meta') or {}).get('handle'):
        raise ValueError('Find and confirm the drawing canvas again.')
    expected = accepted['target_meta']
    handle = expected['handle']
    monitor = monitor if monitor is not None else WindowMonitor()
    if (_title_fingerprint(_window_title(monitor, handle)) != accepted.get('_window_title_fingerprint')):
        raise ValueError('The drawing document or tab changed. Find the canvas again.')
    if (monitor.rectangle(handle) != expected['rect'] or monitor.client_rectangle(handle) != expected['client_rect']
            or monitor.dpi(handle) != expected['dpi']
            or monitor._process_identity(handle) != (expected['target_pid'], expected['target_thread'])):
        raise ValueError('The confirmed drawing window changed. Find the canvas again.')
    _cancel(cancelled)
    return dict(expected)


def discover_guided_canvas(profile_key, *, preferred_handle=None, previous=None, cancelled=lambda: False):
    """Find one visible candidate or independently recheck a suggested rectangle."""
    meta, title_fingerprint, monitor = _inspect_guided_window(profile_key, preferred_handle, previous, cancelled)
    handle, rect, client = meta['handle'], meta['rect'], meta['client_rect']
    target = handle, rect
    if previous is not None and not monitor.active(target):
        raise ValueError('Bring the drawing window to the front to confirm its canvas.')
    with calibration_screenshot(None, client) as frame:
        if profile_key == 'microsoft-paint':
            from PaintFullCalibration import detect_canvas_area
            found = detect_canvas_area(frame, screen_origin=client[:2], cancelled=cancelled)
        else:
            found = detect_browser_canvas(profile_key, frame, screen_origin=client[:2], cancelled=cancelled)
        if found.get('canvas_box') is None:
            raise ValueError('Canvas edges could not be verified. Show the entire drawing area or select it manually.')
        box = contained_rect(found.get('canvas_box'), client, min_side=10)
        confidence = bounded_number(found.get('canvas_confidence'), 'Canvas confidence', minimum=.70)
    _cancel(cancelled)
    if previous is not None and tuple(previous['canvas_box']) != box:
        raise ValueError('The canvas changed since the suggestion. Find it again or mark it manually.')
    left, top, right, bottom = box
    if monitor.capture((left, top, right-left, bottom-top)) != target:
        raise ValueError('Another window covers the canvas. Move it aside and retry.')
    # Recheck the title because a tab switch can preserve the PID, HWND and size.
    final_window = _select_window(profile_key, handle, cancelled)
    if (_title_fingerprint(final_window['title']) != title_fingerprint or
            final_window['pid'] != meta['target_pid'] or monitor.rectangle(handle) != rect or
            monitor.client_rectangle(handle) != client or monitor.dpi(handle) != meta['dpi'] or
            (previous is not None and not monitor.active(target))):
        raise ValueError('The target changed while its canvas was being checked. Try again.')
    _cancel(cancelled)
    return {'profile_key': profile_key, 'target_meta': meta, 'canvas_box': box,
            'canvas_confidence': confidence, '_window_title_fingerprint': title_fingerprint}
