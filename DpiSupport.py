"""Windows DPI helpers used by Image Draw Bot.

v1.0.116 centralises DPI detection so target capture, browser discovery and
live safety checks all use the same physical-pixel rules.  The functions are
safe to import on non-Windows systems and have no input side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import sys
from WindowsSystem import load_system_library

BASE_DPI = 96
MIN_DPI = 48
MAX_DPI = 768


@dataclass(frozen=True)
class DpiInfo:
    dpi: int
    source: str
    scale: float
    monitor_rect: tuple[int, int, int, int] | None = None
    work_rect: tuple[int, int, int, int] | None = None

    def as_dict(self):
        return {
            'dpi': int(self.dpi),
            'dpi_source': self.source,
            'dpi_scale': float(self.scale),
            'monitor_rect': self.monitor_rect,
            'monitor_work_rect': self.work_rect,
        }


def _valid(value) -> bool:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return False
    return MIN_DPI <= value <= MAX_DPI


def enable_per_monitor_v2() -> str:
    """Enable the strongest available Windows DPI awareness before GUI setup.

    Returns a short mode label for diagnostics.  Calling this after another
    component has already fixed process awareness can return ACCESS_DENIED;
    that is not treated as fatal because the existing awareness still applies.
    """
    if sys.platform != 'win32':
        return 'non-windows'
    import ctypes
    try:
        user32 = load_system_library('user32', use_last_error=True)
    except OSError:
        return 'unavailable'

    # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    try:
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_bool
        if fn(ctypes.c_void_p(-4)):
            return 'per-monitor-v2'
        # ERROR_ACCESS_DENIED (5) means awareness was already established.
        if ctypes.get_last_error() == 5:
            return 'already-set'
    except (AttributeError, OSError, TypeError):
        pass

    # Windows 8.1 fallback: PROCESS_PER_MONITOR_DPI_AWARE = 2
    try:
        shcore = load_system_library('shcore', use_last_error=True)
        fn = shcore.SetProcessDpiAwareness
        fn.argtypes = [ctypes.c_int]
        fn.restype = ctypes.c_long
        hr = int(fn(2))
        if hr == 0:
            return 'per-monitor-v1'
        if hr in (-2147024891, 0x80070005):
            return 'already-set'
    except (AttributeError, OSError, TypeError):
        pass

    try:
        fn = user32.SetProcessDPIAware
        fn.argtypes = []
        fn.restype = ctypes.c_bool
        if fn():
            return 'system-aware'
    except (AttributeError, OSError, TypeError):
        pass
    return 'unknown'


def _monitor_info(user32, monitor):
    if not monitor:
        return None, None
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('rcMonitor', wintypes.RECT),
            ('rcWork', wintypes.RECT),
            ('dwFlags', wintypes.DWORD),
        ]

    try:
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            m = info.rcMonitor
            w = info.rcWork
            return (m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom)
    except (AttributeError, OSError, TypeError):
        pass
    return None, None


def get_window_dpi_info(hwnd, *, user32=None, shcore=None, gdi32=None) -> DpiInfo:
    """Read effective DPI for a target HWND with monitor/system fallbacks.

    Order: GetDpiForWindow -> GetDpiForMonitor -> desktop LOGPIXELSX -> 96.
    This avoids silently assuming 96 DPI on 4K/high-scaling systems when one
    Windows API is unavailable or temporarily returns an invalid value.
    """
    if sys.platform != 'win32' and user32 is None:
        return DpiInfo(BASE_DPI, 'default', 1.0)
    import ctypes
    from ctypes import wintypes

    if user32 is None:
        try:
            user32 = load_system_library('user32', use_last_error=True)
        except OSError:
            return DpiInfo(BASE_DPI, 'default-96', 1.0)
    monitor = None
    try:
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    except (AttributeError, OSError, TypeError):
        monitor = None
    monitor_rect, work_rect = _monitor_info(user32, monitor)

    try:
        fn = user32.GetDpiForWindow
        fn.argtypes = [wintypes.HWND]
        fn.restype = wintypes.UINT
        value = int(fn(hwnd))
        if _valid(value):
            return DpiInfo(value, 'GetDpiForWindow', value / BASE_DPI, monitor_rect, work_rect)
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    if monitor:
        try:
            if shcore is None:
                shcore = load_system_library('shcore', use_last_error=True)
            fn = shcore.GetDpiForMonitor
            fn.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                           ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
            fn.restype = ctypes.c_long
            x = wintypes.UINT(0)
            y = wintypes.UINT(0)
            if int(fn(monitor, 0, ctypes.byref(x), ctypes.byref(y))) == 0 and _valid(x.value):
                value = int(x.value)
                return DpiInfo(value, 'GetDpiForMonitor', value / BASE_DPI, monitor_rect, work_rect)
        except (AttributeError, OSError, TypeError, ValueError):
            pass

    # Last useful Windows fallback.  On a per-monitor aware process this is
    # normally system DPI, but it is still more informative than forcing 96.
    dc = None
    try:
        if gdi32 is None:
            gdi32 = load_system_library('gdi32', use_last_error=True)
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        dc = user32.GetDC(None)
        if dc:
            value = int(gdi32.GetDeviceCaps(dc, 88))  # LOGPIXELSX
            if _valid(value):
                return DpiInfo(value, 'LOGPIXELSX', value / BASE_DPI, monitor_rect, work_rect)
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    finally:
        if dc:
            try:
                user32.ReleaseDC(None, dc)
            except Exception:
                pass

    return DpiInfo(BASE_DPI, 'default-96', 1.0, monitor_rect, work_rect)


def normalize_uniform_capture_mapping(metric_size, capture_size):
    """Return uniform logical->physical capture scales for a DPI mismatch.

    RegionPicker normally receives identical virtual-desktop and ImageGrab
    sizes in per-monitor-v2 mode.  If Windows/Tk/Pillow disagree, accept only a
    plausible near-uniform DPI scale rather than hard failing on 4K systems.
    """
    mw, mh = map(int, metric_size)
    cw, ch = map(int, capture_size)
    if min(mw, mh, cw, ch) <= 0:
        raise ValueError('Invalid desktop/capture size.')
    sx = cw / mw
    sy = ch / mh
    if not (0.5 <= sx <= 4.0 and 0.5 <= sy <= 4.0):
        raise ValueError('Display scaling mismatch is outside the supported range.')
    if abs(sx - sy) > max(0.03, 0.03 * max(sx, sy)):
        raise ValueError('Mixed display scaling could not be mapped uniformly.')
    return sx, sy
