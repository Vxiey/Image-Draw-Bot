import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock
import uuid

import WindowsGpuDiscovery as native


class FakeInterface:
    def __init__(self, count):
        self.callbacks = []
        self.vtable = (ctypes.c_void_p * count)()
        self.instance = (ctypes.c_void_p * 1)(ctypes.addressof(self.vtable))
        self.pointer = ctypes.c_void_p(ctypes.addressof(self.instance))
        self.released = 0

        def release(_this):
            self.released += 1
            return 0

        self.method(2, native.UINT, (), release)

    def method(self, slot, result, args, function):
        callback = native._COMCALL(result, ctypes.c_void_p, *args)(function)
        self.callbacks.append(callback)
        self.vtable[slot] = ctypes.cast(callback, ctypes.c_void_p).value


class FakeAdapter(FakeInterface):
    def __init__(self, name="GPU", vendor=0x10DE, memory=16 * 1024**3, *, flags=0,
                 desc_hresult=0, driver_hresult=0, driver_version=(32, 0, 15, 6094)):
        super().__init__(11)
        self.desc = native.DXGI_ADAPTER_DESC1()
        encoded = name.encode("utf-16-le")[:254]
        ctypes.memmove(ctypes.addressof(self.desc), encoded, len(encoded))
        self.desc.VendorId = vendor
        self.desc.DeviceId = 0x1234
        self.desc.DedicatedVideoMemory = memory
        self.desc.SharedSystemMemory = 32 * 1024**3 if ctypes.sizeof(ctypes.c_size_t) == 8 else 1024**3
        self.desc.Flags = flags
        self.driver_iid = None

        def get_desc(_this, out):
            if not desc_hresult:
                ctypes.memmove(out, ctypes.byref(self.desc), ctypes.sizeof(self.desc))
            return desc_hresult

        def check_driver(_this, iid, out):
            self.driver_iid = ctypes.string_at(iid, 16)
            if not driver_hresult:
                out[0] = sum(part << shift for part, shift in zip(driver_version, (48, 32, 16, 0)))
            return driver_hresult

        self.method(10, native.HRESULT, (ctypes.POINTER(native.DXGI_ADAPTER_DESC1),), get_desc)
        self.method(9, native.HRESULT, (ctypes.POINTER(native.GUID), ctypes.POINTER(ctypes.c_int64)), check_driver)


class FakeDxgi:
    def __init__(self, adapters=(), *, create_hresult=0, enumeration_hresult=None, null_factory=False):
        self.adapters = list(adapters)
        self.factory = FakeInterface(14)
        self.iid = None
        self.indices = []

        def enumerate_adapter(_this, index, out):
            self.indices.append(index)
            if enumeration_hresult is not None:
                return enumeration_hresult
            if index >= len(self.adapters):
                return ctypes.c_int32(native.DXGI_ERROR_NOT_FOUND).value
            out[0] = self.adapters[index].pointer.value
            return 0

        self.factory.method(12, native.HRESULT, (native.UINT, ctypes.POINTER(ctypes.c_void_p)), enumerate_adapter)

        def create_factory(iid, out):
            self.iid = ctypes.string_at(iid, 16)
            if not create_hresult and not null_factory:
                out[0] = self.factory.pointer.value
            return create_hresult

        self.CreateDXGIFactory1 = native._COMCALL(
            native.HRESULT, ctypes.POINTER(native.GUID), ctypes.POINTER(ctypes.c_void_p),
        )(create_factory)


class WindowsGpuDiscoveryTests(unittest.TestCase):
    def probe(self, fake):
        with mock.patch.object(native.os, "name", "nt"), \
             mock.patch.object(native, "load_system_library", return_value=fake) as loader:
            rows = native.enumerate_adapters()
        loader.assert_called_once_with("dxgi.dll")
        return rows

    def test_windows_struct_layout_and_hresult_width(self):
        self.assertEqual(ctypes.sizeof(native.HRESULT), 4)
        self.assertEqual(ctypes.sizeof(native.GUID), 16)
        self.assertEqual(ctypes.sizeof(native.LUID), 8)
        expected = 312 if ctypes.sizeof(ctypes.c_void_p) == 8 else 296
        self.assertEqual(ctypes.sizeof(native.DXGI_ADAPTER_DESC1), expected)
        self.assertEqual(native.DXGI_ADAPTER_DESC1.DedicatedVideoMemory.offset, 272)
        self.assertEqual(native.DXGI_ADAPTER_DESC1.Flags.offset, expected - (8 if expected == 312 else 4))
        fields32 = [(name, ctypes.c_uint32 if name.endswith("Memory") else kind)
                    for name, kind in native.DXGI_ADAPTER_DESC1._fields_]
        desc32 = type("Desc32", (ctypes.Structure,), {"_fields_": fields32})
        self.assertEqual(ctypes.sizeof(desc32), 296)
        self.assertEqual(desc32.AdapterLuid.offset, 284)
        self.assertEqual(desc32.Flags.offset, 292)

    def test_native_vtable_unicode_driver_version_and_large_memory(self):
        if ctypes.sizeof(ctypes.c_size_t) < 8:
            self.skipTest("Greater-than-4GiB SIZE_T capacity requires a 64-bit process")
        gpu = FakeAdapter("Radeon Åäö – 显卡", vendor=0x1002, memory=24 * 1024**3)
        fake = FakeDxgi([gpu])
        rows = self.probe(fake)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "Radeon Åäö – 显卡")
        self.assertEqual(rows[0].vendor_id, 0x1002)
        self.assertEqual(rows[0].dedicated_video_memory, 24 * 1024**3)
        self.assertEqual(rows[0].shared_system_memory, 32 * 1024**3)
        self.assertEqual(rows[0].driver_version, "32.0.15.6094")
        self.assertEqual(fake.iid, uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
        self.assertEqual(gpu.driver_iid, uuid.UUID("54ec77fa-1377-44e6-8c32-88fd5f44c84c").bytes_le)
        self.assertEqual(gpu.released, 1)
        self.assertEqual(fake.factory.released, 1)

    def test_only_software_flag_filters_and_identical_hardware_is_retained(self):
        adapters = [FakeAdapter("Software renderer", flags=2),
                    FakeAdapter("Software Adapter", vendor=0, memory=0),
                    FakeAdapter("Intel Arc A770", vendor=0x8086, flags=1),
                    FakeAdapter("Intel Arc A770", vendor=0x8086)]
        fake = FakeDxgi(adapters)
        rows = self.probe(fake)
        self.assertEqual([row.index for row in rows], [1, 2, 3])
        self.assertEqual(rows[0].dedicated_video_memory, 0)
        self.assertTrue(all(adapter.released == 1 for adapter in adapters))
        self.assertEqual(fake.factory.released, 1)

    def test_unsupported_driver_version_keeps_adapter(self):
        gpu = FakeAdapter(driver_hresult=ctypes.c_int32(0x887A0004).value)
        rows = self.probe(FakeDxgi([gpu]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].driver_version, "")

    def test_failed_description_releases_adapter_and_factory(self):
        gpu = FakeAdapter(desc_hresult=-2147467259)
        fake = FakeDxgi([gpu])
        with self.assertRaisesRegex(native.WindowsGpuDiscoveryError, "GetDesc1.*80004005"):
            self.probe(fake)
        self.assertEqual(gpu.released, 1)
        self.assertEqual(fake.factory.released, 1)

    def test_enumeration_failure_is_not_an_empty_success(self):
        fake = FakeDxgi(enumeration_hresult=-2147024891)
        with self.assertRaisesRegex(native.WindowsGpuDiscoveryError, "EnumAdapters1.*80070005"):
            self.probe(fake)
        self.assertEqual(fake.factory.released, 1)

    def test_factory_failure_and_null_success_are_errors(self):
        for fake in (FakeDxgi(create_hresult=-2147467259), FakeDxgi(null_factory=True)):
            with self.subTest(fake=fake), self.assertRaises(native.WindowsGpuDiscoveryError):
                self.probe(fake)
            self.assertEqual(fake.factory.released, 0)

    def test_valid_empty_result_releases_factory(self):
        fake = FakeDxgi()
        self.assertEqual(self.probe(fake), ())
        self.assertEqual(fake.factory.released, 1)

    def test_adapter_limit_fails_without_leaking_interfaces(self):
        adapters = [FakeAdapter() for _ in range(3)]
        fake = FakeDxgi(adapters)
        with mock.patch.object(native, "MAX_ADAPTERS", 2), \
             self.assertRaisesRegex(native.WindowsGpuDiscoveryError, "safety limit"):
            self.probe(fake)
        self.assertEqual(fake.indices, [0, 1, 2])
        self.assertTrue(all(adapter.released == 1 for adapter in adapters))
        self.assertEqual(fake.factory.released, 1)

    @unittest.skipUnless(os.name == "nt", "Real DXGI requires Windows")
    def test_real_windows_probe_in_bounded_process(self):
        script = (
            "from dataclasses import asdict; import json; "
            "from WindowsGpuDiscovery import enumerate_adapters; "
            "print(json.dumps([asdict(x) for x in enumerate_adapters()]))"
        )
        completed = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parent,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        rows = json.loads(completed.stdout)
        self.assertIsInstance(rows, list)
        self.assertLessEqual(len(rows), native.MAX_ADAPTERS)
        for row in rows:
            self.assertIsInstance(row["name"], str)
            self.assertGreaterEqual(row["dedicated_video_memory"], 0)


if __name__ == "__main__":
    unittest.main()
