"""Bounded read-only Windows screen sampling; no saved captures or input.

Dense, compact requests use one top-down 32-bit DIB transfer. Sparse, large,
cross-monitor or unsupported requests retain GetPixel and its error behavior.
Every native resource belongs to this invocation; nothing is cached globally.
"""
from __future__ import annotations

import ctypes
from itertools import chain

from WindowsSystem import load_system_library


_LONG = ctypes.c_int32
_DWORD = ctypes.c_uint32
_HANDLE = ctypes.c_void_p
_MAX_POINTS = 2048
_MIN_POINTS = 16
_MAX_PIXELS = 65_536
_SRCCOPY_CAPTUREBLT = 0x40CC0020
_END = object()


class _Point(ctypes.Structure):
    _fields_ = [('x', _LONG), ('y', _LONG)]


class _Rect(ctypes.Structure):
    _fields_ = [('left', _LONG), ('top', _LONG), ('right', _LONG), ('bottom', _LONG)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [('size', _DWORD), ('monitor', _Rect), ('work', _Rect), ('flags', _DWORD)]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [('size', _DWORD), ('width', _LONG), ('height', _LONG),
                ('planes', ctypes.c_uint16), ('bits', ctypes.c_uint16),
                ('compression', _DWORD), ('image_size', _DWORD),
                ('x_resolution', _LONG), ('y_resolution', _LONG),
                ('colors_used', _DWORD), ('colors_important', _DWORD)]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [('header', _BitmapInfoHeader), ('colors', _DWORD * 1)]


def _function(library, name, arguments, result):
    # Indexing a DLL supplies a private function signature. Concurrent callers
    # must not replace another consumer's ctypes argument classes.
    function = library[name]
    function.argtypes = arguments
    function.restype = result
    return function


def _compact_bounds(points, user32):
    if not _MIN_POINTS <= len(points) <= _MAX_POINTS:
        return None
    left = min(x for x, _ in points)
    right = max(x for x, _ in points) + 1
    top = min(y for _, y in points)
    bottom = max(y for _, y in points) + 1
    pixels = (right - left) * (bottom - top)
    if pixels > _MAX_PIXELS or pixels > len(points) * 64:
        return None
    if not all(-(2**31) <= value < 2**31 for value in (left, top, right - 1, bottom - 1)):
        return None
    # The virtual desktop bounding box can contain gaps between monitors.
    # Only one fully contained physical-monitor rectangle is safe for a bulk
    # read; GetPixel remains authoritative at edges, gaps and spanning requests.
    from_point = _function(user32, 'MonitorFromPoint', [_Point, _DWORD], _HANDLE)
    monitor = from_point(_Point(left, top), 0)
    if not monitor:
        return None
    info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
    get_info = _function(user32, 'GetMonitorInfoW', [_HANDLE, ctypes.POINTER(_MonitorInfo)], _LONG)
    if not get_info(monitor, ctypes.byref(info)):
        return None
    rect = info.monitor
    if not (rect.left <= left < right <= rect.right and rect.top <= top < bottom <= rect.bottom):
        return None
    return left, top, right, bottom


def _read_compact(dc, points, bounds, gdi32):
    create_dc = _function(gdi32, 'CreateCompatibleDC', [_HANDLE], _HANDLE)
    delete_dc = _function(gdi32, 'DeleteDC', [_HANDLE], _LONG)
    create_dib = _function(gdi32, 'CreateDIBSection',
                           [_HANDLE, ctypes.POINTER(_BitmapInfo), _DWORD,
                            ctypes.POINTER(ctypes.c_void_p), _HANDLE, _DWORD], _HANDLE)
    delete_object = _function(gdi32, 'DeleteObject', [_HANDLE], _LONG)
    select = _function(gdi32, 'SelectObject', [_HANDLE, _HANDLE], _HANDLE)
    bitblt = _function(gdi32, 'BitBlt',
                      [_HANDLE, _LONG, _LONG, _LONG, _LONG, _HANDLE, _LONG, _LONG, _DWORD], _LONG)
    flush = _function(gdi32, 'GdiFlush', [], _LONG)
    memory_dc = create_dc(dc)
    if not memory_dc:
        raise OSError('Screen sample memory DC is unavailable.')
    bitmap = previous = None
    data = None
    try:
        left, top, right, bottom = bounds
        width, height = right - left, bottom - top
        info = _BitmapInfo()
        info.header = _BitmapInfoHeader(size=ctypes.sizeof(_BitmapInfoHeader),
                                       width=width, height=-height, planes=1, bits=32)
        pointer = ctypes.c_void_p()
        bitmap = create_dib(dc, ctypes.byref(info), 0, ctypes.byref(pointer), None, 0)
        if not bitmap or not pointer.value:
            raise OSError('Screen sample bitmap is unavailable.')
        selected = select(memory_dc, bitmap)
        if selected in (None, 0, ctypes.c_void_p(-1).value):
            raise OSError('Screen sample bitmap could not be selected.')
        previous = selected
        if not bitblt(memory_dc, 0, 0, width, height, dc, left, top, _SRCCOPY_CAPTUREBLT):
            raise OSError('Screen sample transfer is unavailable.')
        # The bitmap pointer cannot be read until this thread's pending GDI
        # writes have completed, even when BitBlt has already returned success.
        if not flush():
            raise OSError('Screen sample transfer did not complete.')
        data = (ctypes.c_ubyte * (width * height * 4)).from_address(pointer.value)
        colors = []
        for x, y in points:
            offset = ((y - top) * width + x - left) * 4
            colors.append((data[offset + 2], data[offset + 1], data[offset]))
        return colors
    finally:
        # Do not leave a view of freed native bytes in a retained traceback.
        data = None
        if previous is not None:
            select(memory_dc, previous)
        # Destroy the private DC before the bitmap as a second line of cleanup
        # if restoring the previous selection was rejected by Windows.
        delete_dc(memory_dc)
        if bitmap:
            delete_object(bitmap)


def sample_screen_colors(points):
    """Return ordered RGB triples, borrowing no caller buffers or native DCs."""
    user32 = load_system_library('user32.dll')
    gdi32 = load_system_library('gdi32.dll')
    get_dc = _function(user32, 'GetDC', [_HANDLE], _HANDLE)
    release_dc = _function(user32, 'ReleaseDC', [_HANDLE, _HANDLE], _LONG)
    get_pixel = _function(gdi32, 'GetPixel', [_HANDLE, _LONG, _LONG], _DWORD)
    dc = get_dc(None)
    if not dc:
        raise OSError('Cannot read screen colors.')
    try:
        iterator = iter(points)
        # One extra item determines whether a request is too large. The tail
        # stays streaming on the scalar path instead of duplicating all points.
        # Keep the just-read point until append succeeds: an optional prefix
        # allocation failure must not drop an element from a one-shot iterator.
        prefix = ()
        pending = ()
        compact = True
        try:
            prefix = list()
        except MemoryError:
            compact = False
        if compact:
            for _ in range(_MAX_POINTS + 1):
                point = next(iterator, _END)
                if point is _END:
                    break
                # A producer may reuse one mutable coordinate pair. Observe
                # each yielded value before asking it for the next point, as
                # the streaming GetPixel reader does.
                x, y = point
                try:
                    prefix.append((int(x), int(y)))
                except MemoryError:
                    pending = ((x, y),)
                    compact = False
                    break
        if compact and len(prefix) <= _MAX_POINTS:
            try:
                bounds = _compact_bounds(prefix, user32)
                if bounds is not None:
                    return _read_compact(dc, prefix, bounds, gdi32)
            except (AttributeError, OSError, MemoryError):
                # Optional bulk allocation/device support must not make an
                # otherwise readable palette or stroke sample unavailable.
                pass
        values = []
        for x, y in chain(prefix, pending, iterator):
            value = get_pixel(dc, int(x), int(y))
            if value == 0xFFFFFFFF:
                raise OSError('Cannot read this screen position.')
            values.append((value & 255, (value >> 8) & 255, (value >> 16) & 255))
        return values
    finally:
        release_dc(None, dc)
