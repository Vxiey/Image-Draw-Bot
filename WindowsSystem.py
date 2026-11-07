"""Windows system libraries and directories, without PATH/environment lookup.

The frozen application uses PyInstaller's ctypes wrapper. That wrapper may
rewrite a bare DLL name to a file in the application bundle before Windows
receives it, even when WinDLL is given secure search flags. Load the native
handle with CPython's underlying loader first, then wrap that handle for typed
calls. This restriction is for Windows OS libraries, not bundled extensions.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
from pathlib import Path, PureWindowsPath
import re
import sys
import uuid

LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
_MAX_DIRECTORY_CHARS = 32768


def load_system_library(name: str, *, use_last_error: bool = False):
    """Load a DLL basename only from Windows' system-library search directory."""
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.dll)?', name, re.IGNORECASE):
        raise ValueError('A Windows system DLL basename is required.')
    if sys.platform != 'win32':
        raise OSError('Windows system libraries are unavailable on this platform.')
    normalized = name.lower()
    if not normalized.endswith('.dll'):
        normalized += '.dll'
    return _load_system_library(normalized, bool(use_last_error))


@lru_cache(maxsize=None)
def _load_system_library(name: str, use_last_error: bool):
    # _ctypes.LoadLibrary is CPython's LoadLibraryExW boundary. Do not replace
    # this with WinDLL(name): PyInstaller can redirect that name into _MEIPASS.
    from _ctypes import LoadLibrary, FreeLibrary
    handle = LoadLibrary(name, LOAD_LIBRARY_SEARCH_SYSTEM32)
    try:
        return ctypes.WinDLL(None, handle=handle, winmode=LOAD_LIBRARY_SEARCH_SYSTEM32,
                             use_last_error=use_last_error)
    except BaseException:
        FreeLibrary(handle)
        raise


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_uint32), ('dwMemoryLoad', ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in (
            'ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile', 'ullAvailPageFile',
            'ullTotalVirtual', 'ullAvailVirtual', 'ullAvailExtendedVirtual')]


def physical_memory_bytes() -> tuple[int, int]:
    """Return fresh (total, available) physical bytes through a private ABI.

    The system DLL handle is cached, but indexing it creates a new function
    object. A concurrent native consumer cannot overwrite this call's argument
    types, and this call cannot change a different consumer's cached symbol.
    No memory observation is cached; available zero is a real measurement.
    """
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    query = load_system_library('kernel32.dll', use_last_error=True)['GlobalMemoryStatusEx']
    query.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
    query.restype = ctypes.c_int32
    if not query(ctypes.byref(status)):
        raise OSError('GlobalMemoryStatusEx failed.')
    total, available = int(status.ullTotalPhys), int(status.ullAvailPhys)
    if total <= 0 or available > total:
        raise OSError('Windows returned inconsistent physical memory information.')
    return total, available


def _directory_path(value: str, label: str) -> Path:
    if not value or not PureWindowsPath(value).is_absolute():
        raise OSError(f'Windows returned an invalid {label} directory.')
    return Path(value)


def system_directory() -> Path:
    """Return GetSystemDirectoryW's path, including on non-default Windows drives."""
    kernel = load_system_library('kernel32.dll', use_last_error=True)
    get_directory = kernel.GetSystemDirectoryW
    get_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    get_directory.restype = ctypes.c_uint
    size = 260
    while size <= _MAX_DIRECTORY_CHARS:
        buffer = ctypes.create_unicode_buffer(size)
        count = int(get_directory(buffer, size))
        if count == 0:
            raise OSError('GetSystemDirectoryW failed.')
        if count < size:
            return _directory_path(buffer.value, 'system')
        size = count + 1
    raise OSError('Windows system directory exceeds the supported path length.')


class _GUID(ctypes.Structure):
    _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
                ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]


def _known_folder(identifier: str) -> Path:
    shell = load_system_library('shell32.dll')
    ole = load_system_library('ole32.dll')
    get_path = shell.SHGetKnownFolderPath
    get_path.argtypes = [ctypes.POINTER(_GUID), ctypes.c_uint32,
                        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    get_path.restype = ctypes.c_int32
    free = ole.CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    guid = _GUID.from_buffer_copy(uuid.UUID(identifier).bytes_le)
    pointer = ctypes.c_void_p()
    try:
        result = int(get_path(ctypes.byref(guid), 0, None, ctypes.byref(pointer)))
        if result != 0 or not pointer.value:
            raise OSError(f'SHGetKnownFolderPath failed (0x{result & 0xffffffff:08x}).')
        return _directory_path(ctypes.wstring_at(pointer), 'Program Files')
    finally:
        # The API requires freeing the output even when it reports failure.
        if pointer.value:
            free(pointer)


def program_files_directories() -> tuple[Path, ...]:
    """Return OS-reported Program Files roots; never trust environment overrides."""
    identifiers = ['905e63b6-c1bf-494e-b29c-65b732d3d21a']  # FOLDERID_ProgramFiles
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        identifiers.append('6d809377-6af0-444b-8957-a3773f02200e')  # ProgramFilesX64
    paths = []
    seen = set()
    for identifier in identifiers:
        try:
            path = _known_folder(identifier)
        except OSError:
            continue
        identity = str(path).replace('/', '\\').casefold()
        if identity not in seen:
            paths.append(path)
            seen.add(identity)
    return tuple(paths)
