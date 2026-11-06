"""Explicit Windows taskbar artwork and relaunch metadata, without extra packages."""
import ctypes as C
import subprocess
import sys
import uuid
from RuntimePaths import resource_path, is_frozen
from WindowsSystem import load_system_library

PROPERTY_IDS = (2, 3, 4, 5)  # RelaunchCommand, IconResource, DisplayName, ID


class GUID(C.Structure):
    _fields_ = [('data1', C.c_uint32), ('data2', C.c_uint16),
                ('data3', C.c_uint16), ('data4', C.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class PROPERTYKEY(C.Structure):
    _fields_ = [('fmtid', GUID), ('pid', C.c_uint32)]


class CountedPointer(C.Structure):
    _fields_ = [('count', C.c_uint32), ('pointer', C.c_void_p)]


class VariantValue(C.Union):
    _fields_ = [('text', C.c_void_p), ('integer', C.c_int64), ('array', CountedPointer)]


class PROPVARIANT(C.Structure):
    _fields_ = [('vt', C.c_uint16), ('reserved', C.c_uint16 * 3), ('value', VariantValue)]


def _check(hr):
    if hr < 0:
        raise OSError(f'Windows taskbar property error 0x{hr & 0xffffffff:08x}')


class WindowProperties:
    """Short-lived IPropertyStore reference; values belong to the native window."""
    def __init__(self, hwnd):
        shell = load_system_library('shell32')
        get_store = shell.SHGetPropertyStoreForWindow
        get_store.argtypes = [C.c_void_p, C.POINTER(GUID), C.POINTER(C.c_void_p)]
        get_store.restype = C.c_int32
        self.pointer = C.c_void_p()
        iid = GUID.parse('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
        _check(get_store(hwnd, C.byref(iid), C.byref(self.pointer)))
        if not self.pointer:
            raise OSError('Windows returned no taskbar property store.')
        self.vtable = C.cast(self.pointer, C.POINTER(C.POINTER(C.c_void_p))).contents

    def _method(self, slot, result, *arguments):
        return C.WINFUNCTYPE(result, C.c_void_p, *arguments)(self.vtable[slot])

    def set(self, pid, text):
        key = PROPERTYKEY(GUID.parse('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), pid)
        value = PROPVARIANT()
        # SetValue copies the string. Keep the Python buffer alive for that call.
        if text is not None:
            buffer = C.create_unicode_buffer(text)
            value.vt = 31  # VT_LPWSTR; zero-initialized variant is VT_EMPTY.
            value.value.text = C.cast(buffer, C.c_void_p)
        _check(self._method(6, C.c_int32, C.POINTER(PROPERTYKEY), C.POINTER(PROPVARIANT))(
            self.pointer, C.byref(key), C.byref(value)))

    def get(self, pid):
        key = PROPERTYKEY(GUID.parse('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), pid)
        value = PROPVARIANT()
        clear = load_system_library('ole32').PropVariantClear
        clear.argtypes = [C.POINTER(PROPVARIANT)]
        clear.restype = C.c_int32
        try:
            _check(self._method(5, C.c_int32, C.POINTER(PROPERTYKEY), C.POINTER(PROPVARIANT))(
                self.pointer, C.byref(key), C.byref(value)))
            return C.wstring_at(value.value.text) if value.vt == 31 and value.value.text else None
        finally:
            _check(clear(C.byref(value)))

    def close(self):
        if self.pointer:
            self._method(2, C.c_uint32)(self.pointer)
            self.pointer = C.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


def window_handle(window):
    user = load_system_library('user32')
    user.GetAncestor.argtypes = [C.c_void_p, C.c_uint32]
    user.GetAncestor.restype = C.c_void_p
    return user.GetAncestor(window.winfo_id(), 2)  # GA_ROOT: Tk's native wrapper.


def relaunch_command():
    args = [sys.executable]
    if not is_frozen():
        args.append(str(resource_path('DrawBot.py')))
    return subprocess.list2cmdline(args)


def clear_window_identity(window):
    hwnd = getattr(window, '_image_draw_bot_taskbar_hwnd', None)
    if hwnd:
        user = load_system_library('user32')
        user.IsWindow.argtypes = [C.c_void_p]
        user.IsWindow.restype = C.c_int
        if user.IsWindow(hwnd):
            with WindowProperties(hwnd) as properties:
                for pid in PROPERTY_IDS:
                    properties.set(pid, None)
        window._image_draw_bot_taskbar_hwnd = None


def set_window_identity(window, app_id, icon):
    hwnd = window_handle(window)
    if not hwnd:
        return
    previous = getattr(window, '_image_draw_bot_taskbar_hwnd', None)
    if previous and previous != hwnd:
        clear_window_identity(window)
    with WindowProperties(hwnd) as properties:
        # Set relaunch information before the explicit window AppUserModelID.
        properties.set(2, relaunch_command())
        properties.set(3, f'{icon.resolve()},0')
        properties.set(4, 'Image Draw Bot')
        properties.set(5, app_id)
    window._image_draw_bot_taskbar_hwnd = hwnd
