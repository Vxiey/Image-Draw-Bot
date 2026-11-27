"""OS-library loading and taskbar/DPI failure-path regressions."""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import DpiSupport
import TaskbarIdentity
import WindowsSystem as windows


class WindowsSystemTests(unittest.TestCase):
    def setUp(self):
        windows._load_system_library.cache_clear()

    def tearDown(self):
        windows._load_system_library.cache_clear()

    def test_native_loader_restricts_search_before_frozen_wrapper(self):
        with mock.patch.object(windows.sys, 'platform', 'win32'), \
                mock.patch('_ctypes.LoadLibrary', return_value=123, create=True) as native, \
                mock.patch('_ctypes.FreeLibrary', create=True), \
                mock.patch.object(ctypes, 'WinDLL', create=True) as wrapper:
            result = windows.load_system_library('SHCORE', use_last_error=True)
            self.assertIs(result, wrapper.return_value)
            native.assert_called_once_with('shcore.dll', 0x800)
            wrapper.assert_called_once_with(None, handle=123, winmode=0x800, use_last_error=True)
            self.assertIs(windows.load_system_library('shcore.dll', use_last_error=True), result)
            self.assertEqual(native.call_count, 1)

    def test_failed_handle_wrapping_releases_reference(self):
        with mock.patch.object(windows.sys, 'platform', 'win32'), \
                mock.patch('_ctypes.LoadLibrary', return_value=123, create=True), \
                mock.patch('_ctypes.FreeLibrary', create=True) as free, \
                mock.patch.object(ctypes, 'WinDLL', side_effect=OSError('wrapper failed'), create=True):
            with self.assertRaises(OSError):
                windows.load_system_library('shcore')
            free.assert_called_once_with(123)

    def test_input_backends_use_independent_function_caches_on_one_trusted_handle(self):
        from ScreenGuard import WindowMonitor
        from WindowsMouse import WindowsMouse

        def wrap(name, *, handle, winmode, use_last_error):
            self.assertIsNone(name)
            self.assertEqual((handle, winmode, use_last_error), (123, 0x800, True))
            return mock.Mock(_handle=handle)

        with mock.patch.object(windows.sys, 'platform', 'win32'), \
                mock.patch('_ctypes.LoadLibrary', return_value=123, create=True) as native, \
                mock.patch('_ctypes.FreeLibrary', create=True), \
                mock.patch.object(ctypes, 'WinDLL', side_effect=wrap, create=True):
            mouse = WindowsMouse()
            monitor = WindowMonitor()
            shared = windows.load_system_library('user32.dll', use_last_error=True)
            native.assert_called_once_with('user32.dll', 0x800)
            self.assertIsNot(mouse.api, shared)
            self.assertIsNot(monitor.api, shared)
            self.assertIsNot(mouse.api, monitor.api)
            self.assertFalse(mouse.input_armed)

    def test_branding_and_drop_cursor_bind_private_symbols_on_trusted_modules(self):
        from ctypes import wintypes
        import AppBranding
        from SmartDropInCanvas import cursor_position

        def read_position(pointer):
            point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = -10, 25
            return 1

        get_cursor = mock.Mock(side_effect=read_position)
        set_app_id = mock.Mock(return_value=0)
        with mock.patch.object(windows, 'load_system_library',
                               return_value={'GetCursorPos': get_cursor}) as user32, \
                mock.patch.object(AppBranding, 'load_system_library',
                                  return_value={'SetCurrentProcessExplicitAppUserModelID': set_app_id}) as shell32, \
                mock.patch.object(windows.sys, 'platform', 'win32'):
            self.assertEqual(cursor_position(), (-10, 25))
            AppBranding.set_windows_app_id()
        user32.assert_called_once_with('user32.dll')
        shell32.assert_called_once_with('shell32.dll')
        set_app_id.assert_called_once_with(AppBranding.APP_USER_MODEL_ID)

    def test_paths_and_alternate_streams_are_rejected_before_loading(self):
        with mock.patch.object(windows, '_load_system_library') as native:
            for name in ('', '../shcore.dll', r'C:\temp\shcore.dll', 'shcore.dll:extra',
                         'shcore.dll.', 'shcore.dll\x00', 'user32.exe', None):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    windows.load_system_library(name)
            native.assert_not_called()

    def test_system_directory_uses_api_and_resizes_without_environment(self):
        expected = 'D:\\Windows\\' + 'x' * 270
        def fill(buffer, size):
            if size <= len(expected):
                return len(expected) + 1
            buffer.value = expected
            return len(expected)
        function = mock.Mock(side_effect=fill)
        with mock.patch.object(windows, 'load_system_library', return_value=SimpleNamespace(GetSystemDirectoryW=function)), \
                mock.patch.dict(os.environ, {'SystemRoot': 'Z:\\untrusted'}):
            self.assertEqual(str(windows.system_directory()), expected)
        self.assertEqual(function.call_count, 2)

    def test_system_directory_failure_and_invalid_path_fail_closed(self):
        for result in (0, 40000):
            with self.subTest(result=result), mock.patch.object(windows, 'load_system_library',
                    return_value=SimpleNamespace(GetSystemDirectoryW=mock.Mock(return_value=result))):
                with self.assertRaises(OSError):
                    windows.system_directory()
        with self.assertRaises(OSError):
            windows._directory_path('relative/Windows', 'system')

    def test_known_folder_output_is_freed_on_success_and_failure(self):
        for result in (0, -2147467259):
            buffer = ctypes.create_unicode_buffer(r'D:\Apps')
            def get_folder(guid, flags, token, output):
                ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(buffer)
                return result
            free = mock.Mock()
            libraries = {'shell32.dll': SimpleNamespace(SHGetKnownFolderPath=mock.Mock(side_effect=get_folder)),
                         'ole32.dll': SimpleNamespace(CoTaskMemFree=free)}
            with self.subTest(result=result), mock.patch.object(windows, 'load_system_library', side_effect=libraries.__getitem__):
                if result == 0:
                    self.assertEqual(str(windows._known_folder('905e63b6-c1bf-494e-b29c-65b732d3d21a')), r'D:\Apps')
                else:
                    with self.assertRaises(OSError):
                        windows._known_folder('905e63b6-c1bf-494e-b29c-65b732d3d21a')
                self.assertEqual(free.call_count, 1)
                self.assertEqual(free.call_args.args[0].value, ctypes.addressof(buffer))

    def test_program_files_ignores_environment_and_deduplicates_paths(self):
        with mock.patch.object(windows, '_known_folder', return_value=Path(r'D:\Applications')), \
                mock.patch.dict(os.environ, {'ProgramFiles': 'Z:\\untrusted'}):
            self.assertEqual(windows.program_files_directories(), (Path(r'D:\Applications'),))
        with mock.patch.object(windows, '_known_folder', side_effect=OSError('unavailable')):
            self.assertEqual(windows.program_files_directories(), ())

    def test_dpi_lookup_load_failure_retains_safe_default(self):
        with mock.patch.object(DpiSupport.sys, 'platform', 'win32'), \
                mock.patch.object(DpiSupport, 'load_system_library', side_effect=OSError('unavailable')):
            self.assertEqual(DpiSupport.get_window_dpi_info(123).dpi, 96)
            self.assertEqual(DpiSupport.enable_per_monitor_v2(), 'unavailable')

    def test_null_taskbar_store_is_reported_before_dereferencing(self):
        library = SimpleNamespace(SHGetPropertyStoreForWindow=mock.Mock(return_value=0))
        with mock.patch.object(TaskbarIdentity, 'load_system_library', return_value=library):
            with self.assertRaisesRegex(OSError, 'no taskbar property store'):
                TaskbarIdentity.WindowProperties(123)

    def test_taskbar_variant_is_cleared_even_when_getvalue_fails(self):
        properties = object.__new__(TaskbarIdentity.WindowProperties)
        properties.pointer = ctypes.c_void_p(123)
        properties._method = mock.Mock(return_value=mock.Mock(return_value=-2147467259))
        clear = mock.Mock(return_value=0)
        with mock.patch.object(TaskbarIdentity, 'load_system_library', return_value=SimpleNamespace(PropVariantClear=clear)):
            with self.assertRaises(OSError):
                properties.get(2)
        self.assertEqual(clear.call_count, 1)

    def test_null_taskbar_text_pointer_is_not_dereferenced(self):
        properties = object.__new__(TaskbarIdentity.WindowProperties)
        properties.pointer = ctypes.c_void_p(123)
        def get_value(pointer, key, value):
            ctypes.cast(value, ctypes.POINTER(TaskbarIdentity.PROPVARIANT)).contents.vt = 31
            return 0
        properties._method = mock.Mock(return_value=get_value)
        clear = mock.Mock(return_value=0)
        with mock.patch.object(TaskbarIdentity, 'load_system_library', return_value=SimpleNamespace(PropVariantClear=clear)):
            self.assertIsNone(properties.get(2))
        self.assertEqual(clear.call_count, 1)

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows DLL/path integration')
    def test_real_system_library_ignores_same_named_bundle_file(self):
        original = ctypes.WinDLL
        def frozen_wrapper(name, *args, **kwargs):
            # Model the filename rewrite performed by the actual frozen loader.
            if name and not Path(name).is_file():
                bundled = Path(sys._MEIPASS) / Path(name).name
                if bundled.is_file():
                    name = str(bundled)
            return original(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(sys, '_MEIPASS', temp, create=True), \
                mock.patch.object(ctypes, 'WinDLL', side_effect=frozen_wrapper):
            (Path(temp) / 'version.dll').write_text('non-executable marker', encoding='utf-8')
            library = windows.load_system_library('version.dll')
            kernel = windows.load_system_library('kernel32.dll')
            function = kernel.GetModuleFileNameW
            function.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
            function.restype = ctypes.c_uint
            buffer = ctypes.create_unicode_buffer(32768)
            self.assertGreater(function(library._handle, buffer, len(buffer)), 0)
            self.assertEqual(Path(buffer.value).parent, windows.system_directory())
            self.assertTrue(windows.program_files_directories())


if __name__ == '__main__':
    unittest.main()
