"""Passive, short-lived Win32 borders for a previously detected canvas."""
import ctypes
from ctypes import wintypes
import sys

from CalibrationValidation import screen_rect
from ScreenGuard import WindowMonitor
from SmartDropInCanvas import position_verified_overlay
from WindowsSystem import private_system_library


def outline_supported():
    return sys.platform == 'win32'


_EX_PASSIVE = 0x08000000 | 0x00080000 | 0x00000020 | 0x00000080  # NOACTIVATE, LAYERED, TRANSPARENT, TOOLWINDOW
_POPUP_DISABLED = 0x80000000 | 0x08000000


def border_strips(box, dpi):
    left, top, right, bottom = screen_rect(box, 'Canvas outline')
    width, height = right-left, bottom-top
    if min(width, height) < 10 or max(width, height) >= 2**31:
        raise ValueError('The suggested canvas cannot be outlined at this size.')
    thickness = max(1, min(4, round(2 * dpi / 96), (min(width, height)-1)//4))
    # The second ring uses the contrasting system brush and sits just inside the first.
    for style in (0x04, 0x06):  # SS_BLACKRECT, SS_WHITERECT
        yield style, (left, top, right, top+thickness)
        yield style, (left, bottom-thickness, right, bottom)
        yield style, (left, top+thickness, left+thickness, bottom-thickness)
        yield style, (right-thickness, top+thickness, right, bottom-thickness)
        left, top, right, bottom = left+thickness, top+thickness, right-thickness, bottom-thickness


class CanvasOutline:
    def __init__(self, box, meta):
        self.box = tuple(box)
        self.meta = meta
        self.handles = []
        self.monitor = WindowMonitor()
        self.check_target()
        api = self.api = private_system_library('user32.dll', use_last_error=True)
        api.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                        wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        api.CreateWindowExW.restype = wintypes.HWND
        api.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
        api.SetLayeredWindowAttributes.restype = wintypes.BOOL
        api.DestroyWindow.argtypes = [wintypes.HWND]
        api.DestroyWindow.restype = wintypes.BOOL
        try:
            # Eight thin, disabled windows leave the entire interior physically open.
            # No custom window class, input hooks, capture, activation or Tk mapping.
            for style, rect in border_strips(self.box, meta['dpi']):
                left, top, right, bottom = rect
                handle = api.CreateWindowExW(_EX_PASSIVE, 'STATIC', None, _POPUP_DISABLED | style,
                                             left, top, right-left, bottom-top, None, None, None, None)
                if not handle:
                    raise OSError('Windows could not create the canvas outline.')
                self.handles.append(handle)
                if not api.SetLayeredWindowAttributes(handle, 0, 255, 0x02):  # LWA_ALPHA
                    raise OSError('Windows could not make the outline click-through.')
                position_verified_overlay(api, handle, rect, insert_after=-1, flags=0x0010)
            # Each strip is still hidden. Only reveal the complete verified outline,
            # preserving position, z-order, size and the current foreground window.
            for handle in self.handles:
                if not api.SetWindowPos(handle, None, 0, 0, 0, 0, 0x0057):
                    raise OSError('Windows could not display the canvas outline.')
        except BaseException:
            self.close()
            raise

    def check_target(self):
        meta, monitor = self.meta, self.monitor
        handle = meta['handle']
        left, top, right, bottom = self.box
        if (monitor._process_identity(handle) != (meta['target_pid'], meta['target_thread'])
                or monitor.client_rectangle(handle) != tuple(meta['client_rect'])
                or monitor.dpi(handle) != meta['dpi'] or monitor.api.IsIconic(handle)):
            raise ValueError('The drawing window changed. Find the canvas again.')
        if monitor.capture((left, top, right-left, bottom-top)) != (handle, tuple(meta['rect'])):
            raise ValueError('Move covering windows aside to show the suggested canvas.')

    def close(self):
        while self.handles:
            handle = self.handles.pop()
            if not self.api.DestroyWindow(handle):
                # A handle already destroyed by Windows is harmless. Hide any
                # still-live window without activating it if destruction failed.
                self.api.SetWindowPos(handle, None, 0, 0, 0, 0, 0x0097)
