"""Read local Windows display-adapter metadata through the documented DXGI API.

Only copied Python values leave a probe; COM interfaces belong to the calling
thread and are released before it returns. This module does not create a D3D
device, initialize CUDA/OpenCL, launch a process, or change graphics settings.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
import uuid

from WindowsSystem import load_system_library


# Windows uses 32-bit LONG/HRESULT and 16-bit WCHAR even on 64-bit systems.
# Explicit widths also let the native ABI tests run on non-Windows hosts.
HRESULT = ctypes.c_int32
UINT = ctypes.c_uint32
_COMCALL = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ADAPTER_FLAG_SOFTWARE = 2
MAX_ADAPTERS = 64


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8),
    ]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_uint16 * 128),
        ("VendorId", UINT), ("DeviceId", UINT), ("SubSysId", UINT),
        ("Revision", UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID), ("Flags", UINT),
    ]


_IID_IDXGIFACTORY1 = GUID.from_buffer_copy(uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
_IID_IDXGIDEVICE = GUID.from_buffer_copy(uuid.UUID("54ec77fa-1377-44e6-8c32-88fd5f44c84c").bytes_le)


@dataclass(frozen=True)
class WindowsGpuAdapter:
    index: int
    name: str
    vendor_id: int
    device_id: int
    dedicated_video_memory: int
    dedicated_system_memory: int = 0
    shared_system_memory: int = 0
    driver_version: str = ""


class WindowsGpuDiscoveryError(OSError):
    """A DXGI probe failed, as distinct from finding no hardware adapters."""


def _check_hresult(result: int, operation: str) -> None:
    if int(result) & 0x80000000:
        raise WindowsGpuDiscoveryError(f"{operation} failed (HRESULT 0x{int(result) & 0xFFFFFFFF:08X})")


def _method(interface: ctypes.c_void_p, slot: int, result_type, *argument_types):
    if not interface.value:
        raise WindowsGpuDiscoveryError("DXGI returned a null interface")
    table = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    address = table[slot]
    if not address:
        raise WindowsGpuDiscoveryError(f"DXGI interface has no method at slot {slot}")
    return _COMCALL(result_type, ctypes.c_void_p, *argument_types)(address)


def _release(interface: ctypes.c_void_p) -> None:
    if interface.value:
        try:
            _method(interface, 2, UINT)(interface)
        finally:
            interface.value = None


def _driver_version(adapter: ctypes.c_void_p) -> str:
    # Microsoft recommends IDXGIDevice here to query the UMD binary version.
    # Unsupported interfaces are normal and must not hide an otherwise usable
    # adapter. This is not a check for CUDA/OpenCL/Direct3D rendering support.
    version = ctypes.c_int64()
    result = _method(adapter, 9, HRESULT, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_int64))(
        adapter, ctypes.byref(_IID_IDXGIDEVICE), ctypes.byref(version),
    )
    if result != 0 or not version.value:
        return ""
    value = version.value & 0xFFFFFFFFFFFFFFFF
    return ".".join(str((value >> shift) & 0xFFFF) for shift in (48, 32, 16, 0))


def enumerate_adapters() -> tuple[WindowsGpuAdapter, ...]:
    """Strict native probe; return hardware adapters or raise on DXGI failure.

    A headless/remote session may expose no hardware adapters, which is a valid
    empty result. Native failures remain visible to Windows release smoke tests;
    the application-facing GpuHardware API supplies its own best-effort fallback.
    The adapter-count bound guards a broken enumeration loop, not a hung driver
    call; release smoke tests additionally run this probe with a process timeout.
    """
    if os.name != "nt":
        raise WindowsGpuDiscoveryError("DXGI adapter discovery requires Windows")

    dxgi = load_system_library("dxgi.dll")
    create_factory = dxgi.CreateDXGIFactory1
    create_factory.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    create_factory.restype = HRESULT
    factory = ctypes.c_void_p()
    adapters: list[WindowsGpuAdapter] = []
    try:
        _check_hresult(create_factory(ctypes.byref(_IID_IDXGIFACTORY1), ctypes.byref(factory)),
                       "CreateDXGIFactory1")
        enum_adapters = _method(factory, 12, HRESULT, UINT, ctypes.POINTER(ctypes.c_void_p))
        for index in range(MAX_ADAPTERS + 1):
            adapter = ctypes.c_void_p()
            try:
                result = enum_adapters(factory, index, ctypes.byref(adapter))
                if int(result) & 0xFFFFFFFF == DXGI_ERROR_NOT_FOUND:
                    return tuple(adapters)
                _check_hresult(result, "IDXGIFactory1.EnumAdapters1")
                if index == MAX_ADAPTERS:
                    raise WindowsGpuDiscoveryError("DXGI adapter enumeration exceeded its safety limit")
                desc = DXGI_ADAPTER_DESC1()
                get_desc = _method(adapter, 10, HRESULT, ctypes.POINTER(DXGI_ADAPTER_DESC1))
                _check_hresult(get_desc(adapter, ctypes.byref(desc)), "IDXGIAdapter1.GetDesc1")
                if desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE:
                    continue
                # The REMOTE flag is reserved. Names such as "Software Adapter"
                # can also describe feature-level-9 hardware; only SOFTWARE is
                # a documented reason to filter an adapter here.
                name = bytes(desc.Description).decode("utf-16-le", errors="replace").split("\0", 1)[0].strip()
                adapters.append(WindowsGpuAdapter(
                    index=index,
                    name=name or f"Display adapter {index + 1}",
                    vendor_id=int(desc.VendorId),
                    device_id=int(desc.DeviceId),
                    dedicated_video_memory=int(desc.DedicatedVideoMemory),
                    dedicated_system_memory=int(desc.DedicatedSystemMemory),
                    shared_system_memory=int(desc.SharedSystemMemory),
                    driver_version=_driver_version(adapter),
                ))
            finally:
                _release(adapter)
    finally:
        _release(factory)
    return tuple(adapters)
