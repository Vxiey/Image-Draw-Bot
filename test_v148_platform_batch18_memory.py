"""Actual RAM consumers must not overwrite one another's native ABI."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import ctypes
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import DiagnosticsPackage
import ResourceAllocation
import UniversalHardwareBenchmark
import WindowsSystem


MIB = 1024 * 1024


class MemoryBuffer(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_uint32), ('dwMemoryLoad', ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in (
            'ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile', 'ullAvailPageFile',
            'ullTotalVirtual', 'ullAvailVirtual', 'ullAvailExtendedVirtual')]


class NativeFunction:
    """Delegate conversion to real ctypes; only schedule the interleaving."""
    def __init__(self, owner, function):
        self.owner, self.function = owner, function

    @property
    def argtypes(self):
        return self.function.argtypes

    @argtypes.setter
    def argtypes(self, value):
        self.function.argtypes = value

    @property
    def restype(self):
        return self.function.restype

    @restype.setter
    def restype(self, value):
        self.function.restype = value
        if self.owner.block_ident == threading.get_ident() and self.owner.block_once:
            self.owner.block_once = False
            self.owner.configured.set()
            if not self.owner.release.wait(5):
                raise AssertionError('The other RAM probe did not finish its scheduled interleave')

    def __call__(self, pointer):
        try:
            return self.function(pointer)
        except BaseException as error:
            self.owner.call_errors.append(error)
            raise


class MemoryLibrary:
    """One cached native symbol plus independent indexed function objects."""
    def __init__(self):
        self.total = 32 * 1024 * MIB + 511
        self.available = 12 * 1024 * MIB + MIB // 2
        self.success = True
        self.sizes, self.call_errors, self.raw_lookups = [], [], []
        self.configured, self.release = threading.Event(), threading.Event()
        self.block_ident, self.block_once = None, False
        self.prototype = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)
        self.callback = self.prototype(self.fill)
        self.address = ctypes.cast(self.callback, ctypes.c_void_p).value
        self.GlobalMemoryStatusEx = self.bind()
        self.original_argtypes = tuple(self.GlobalMemoryStatusEx.argtypes)
        self.index_reads = 0

    def fill(self, address):
        status = MemoryBuffer.from_address(address)
        self.sizes.append(int(status.dwLength))
        if not self.success or status.dwLength != ctypes.sizeof(MemoryBuffer):
            return 0
        status.dwMemoryLoad = 63
        status.ullTotalPhys, status.ullAvailPhys = self.total, self.available
        return 1

    def bind(self):
        return NativeFunction(self, self.prototype(self.address))

    def __getitem__(self, name):
        if name != 'GlobalMemoryStatusEx':
            raise AssertionError(name)
        self.index_reads += 1
        return self.bind()

    def forbidden_raw_loader(self, name):
        self.raw_lookups.append(name)
        raise AssertionError('The RAM consumer bypassed the System32 loader')


class LiveMemoryLibrary:
    """Keep the real Windows API; interpose only scheduling and observations."""
    def __init__(self):
        self.dll = WindowsSystem.load_system_library('kernel32.dll', use_last_error=True)
        self.configured, self.release = threading.Event(), threading.Event()
        self.block_ident, self.block_once = None, False
        self.call_errors, self.raw_lookups = [], []
        self.GlobalMemoryStatusEx = NativeFunction(self, self.dll.GlobalMemoryStatusEx)
        self.original_argtypes = self.GlobalMemoryStatusEx.argtypes
        self.index_reads = 0

    def __getitem__(self, name):
        if name != 'GlobalMemoryStatusEx':
            raise AssertionError(name)
        self.index_reads += 1
        return NativeFunction(self, self.dll[name])

    def forbidden_raw_loader(self, name):
        self.raw_lookups.append(name)
        raise AssertionError('The RAM consumer bypassed the System32 loader')


def interleaved_reads(library, first, second):
    with windows_consumers(library), ThreadPoolExecutor(max_workers=2) as pool:
        def paused_probe():
            library.block_ident = threading.get_ident()
            library.block_once = True
            return first()
        pending = pool.submit(paused_probe)
        try:
            if not library.configured.wait(5):
                raise AssertionError('The first actual consumer did not configure the native API')
            following = pool.submit(second).result(timeout=5)
        finally:
            library.release.set()
        initial = pending.result(timeout=5)
    return initial, following


@contextmanager
def windows_consumers(library):
    class RawLibraries:
        def __getattr__(self, name):
            return library.forbidden_raw_loader(name)

    with ExitStack() as stack:
        stack.enter_context(patch.object(UniversalHardwareBenchmark, 'sys', SimpleNamespace(platform='win32')))
        stack.enter_context(patch.object(ResourceAllocation, 'sys', SimpleNamespace(platform='win32')))
        stack.enter_context(patch.object(DiagnosticsPackage, 'os', SimpleNamespace(name='nt')))
        stack.enter_context(patch.object(UniversalHardwareBenchmark, 'load_system_library', return_value=library, create=True))
        loader = stack.enter_context(patch.object(WindowsSystem, 'load_system_library', return_value=library))
        stack.enter_context(patch.object(ctypes, 'windll', RawLibraries(), create=True))
        yield loader


class NativeMemoryConsumerTests(unittest.TestCase):
    def test_overlapping_real_consumers_keep_their_native_pointer_types(self):
        probes = (UniversalHardwareBenchmark._total_ram_mb, DiagnosticsPackage._memory_total_mb)
        for first, second in (probes, probes[::-1]):
            with self.subTest(first=first.__module__):
                library = MemoryLibrary()
                initial, following = interleaved_reads(library, first, second)
                self.assertEqual(following, 32 * 1024)
                self.assertEqual(initial, 32 * 1024,
                    f'Valid native RAM was lost after another caller rebound its ABI: {library.call_errors!r}')
                self.assertFalse(library.call_errors)
                self.assertEqual(library.sizes, [64, 64])
                self.assertEqual(tuple(library.GlobalMemoryStatusEx.argtypes), library.original_argtypes)

    def test_existing_single_total_reads_keep_64_bit_values_and_refresh_every_call(self):
        library = MemoryLibrary()
        with windows_consumers(library):
            for total in (32 * 1024 * MIB + 511, 64 * 1024 * MIB + 12345):
                library.total = total
                self.assertEqual(UniversalHardwareBenchmark._total_ram_mb(), total // MIB)
                self.assertEqual(DiagnosticsPackage._memory_total_mb(), total // MIB)
        self.assertEqual(library.sizes, [64] * 4)
        self.assertFalse(library.call_errors)

    def test_available_ram_uses_the_typed_system_loader_and_retains_known_zero(self):
        library = MemoryLibrary()
        with windows_consumers(library) as loader:
            self.assertEqual(ResourceAllocation.available_ram_mb(), 12 * 1024)
            library.available = 0
            self.assertEqual(ResourceAllocation.available_ram_mb(), 0)
            with self.assertRaisesRegex(ValueError, '128 MB'):
                ResourceAllocation.resolve_ram_budget_mb('Auto')
        self.assertFalse(library.raw_lookups)
        self.assertTrue(loader.called)
        self.assertEqual(library.sizes, [64] * 3)

    def test_failed_or_inconsistent_native_readings_remain_unavailable(self):
        probes = (UniversalHardwareBenchmark._total_ram_mb,
                  DiagnosticsPackage._memory_total_mb, ResourceAllocation.available_ram_mb)
        for success, total, available in ((False, 32 * 1024 * MIB, 12 * 1024 * MIB),
                                           (True, 0, 0), (True, 1024 * MIB, 2048 * MIB)):
            with self.subTest(success=success, total=total, available=available):
                library = MemoryLibrary()
                library.success, library.total, library.available = success, total, available
                with windows_consumers(library):
                    with self.assertRaises(OSError):
                        WindowsSystem.physical_memory_bytes()
                    for probe in probes:
                        self.assertIsNone(probe(), probe.__module__)
                self.assertEqual(library.sizes, [64] * 4)
                self.assertFalse(library.call_errors)
        with windows_consumers(MemoryLibrary()) as loader:
            loader.side_effect = OSError('System library unavailable')
            for probe in probes:
                self.assertIsNone(probe(), probe.__module__)

    def test_non_windows_system_probes_do_not_enter_the_native_loader(self):
        values = {'SC_PHYS_PAGES': 8 * 1024 * 1024,
                  'SC_AVPHYS_PAGES': 3 * 1024 * 1024, 'SC_PAGE_SIZE': 4096}
        portable_os = SimpleNamespace(name='posix', sysconf=values.__getitem__)
        with ExitStack() as stack:
            for module in (UniversalHardwareBenchmark, ResourceAllocation):
                stack.enter_context(patch.object(module, 'sys', SimpleNamespace(platform='freebsd')))
            for module in (UniversalHardwareBenchmark, ResourceAllocation, DiagnosticsPackage):
                stack.enter_context(patch.object(module, 'os', portable_os))
            native = stack.enter_context(patch.object(WindowsSystem, 'load_system_library',
                side_effect=AssertionError('Portable probes must not use a Windows DLL')))
            self.assertEqual(UniversalHardwareBenchmark._total_ram_mb(), 32 * 1024)
            self.assertEqual(DiagnosticsPackage._memory_total_mb(), 32 * 1024)
            self.assertEqual(ResourceAllocation.available_ram_mb(), 12 * 1024)
            native.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Requires the real Windows kernel32 API')
    def test_real_windows_consumers_survive_overlap_with_live_native_values(self):
        probes = (UniversalHardwareBenchmark._total_ram_mb, DiagnosticsPackage._memory_total_mb)
        for first, second in (probes, probes[::-1]):
            with self.subTest(first=first.__module__):
                library = LiveMemoryLibrary()
                initial, following = interleaved_reads(library, first, second)
                # Available memory is volatile; never demand equality between
                # separate real observations or replace native values with fixtures.
                self.assertIsInstance(initial, int)
                self.assertIsInstance(following, int)
                self.assertGreater(initial, 0)
                self.assertGreater(following, 0)
                self.assertFalse(library.call_errors)
                self.assertFalse(library.raw_lookups)
                self.assertEqual(library.index_reads, 2)
                self.assertEqual(library.GlobalMemoryStatusEx.argtypes, library.original_argtypes)
        total, available = WindowsSystem.physical_memory_bytes()
        self.assertGreater(total, 0)
        self.assertGreaterEqual(available, 0)
        self.assertLessEqual(available, total)


if __name__ == '__main__':
    unittest.main()
