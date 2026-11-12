"""Actual sampling through controlled native boundaries and a live Windows gate."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import Colors
import ScreenPixelSampling as sampling
from ScreenGuard import GuardedMouse, WindowMonitor


class _Function:
    def __init__(self, boundary, name):
        self.boundary, self.name = boundary, name

    def __call__(self, *args):
        self.boundary.calls.append((self.name, args))
        if self.name == self.boundary.fail:
            return 0
        return getattr(self.boundary, self.name)(*args)


class _Library:
    def __init__(self, boundary):
        self.boundary = boundary

    def __getitem__(self, name):
        return _Function(self.boundary, name)

    def __getattr__(self, name):
        return self[name]


class _NativeBoundary:
    """Only the DLL calls are replaced; public code and buffer addressing run."""
    desktop = 2**40 + 1
    memory = 2**40 + 2
    bitmap = 2**40 + 3
    stock = 2**40 + 4
    monitor = 2**40 + 5

    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []
        self.buffers = {}
        self.rect = (-1920, -200, 1920, 1080)
        self.pending = None

    @staticmethod
    def rgb(x, y):
        return (x * 13 + y * 7) % 256, (x * 3 - y * 11) % 256, (x * 17 + y * 19) % 256

    def GetDC(self, window):
        assert window is None
        return self.desktop

    def ReleaseDC(self, window, dc):
        assert window is None and dc == self.desktop
        return 1

    def GetPixel(self, dc, x, y):
        assert dc == self.desktop
        if not (self.rect[0] <= x < self.rect[2] and self.rect[1] <= y < self.rect[3]):
            return 0xFFFFFFFF
        red, green, blue = self.rgb(x, y)
        return red | green << 8 | blue << 16

    def MonitorFromPoint(self, point, flags):
        assert flags == 0
        return self.monitor if self.rect[0] <= point.x < self.rect[2] and self.rect[1] <= point.y < self.rect[3] else 0

    def GetMonitorInfoW(self, monitor, pointer):
        assert monitor == self.monitor and pointer._obj.size == 40
        pointer._obj.monitor = sampling._Rect(*self.rect)
        return 1

    def CreateCompatibleDC(self, dc):
        assert dc == self.desktop
        return self.memory

    def DeleteDC(self, dc):
        assert dc == self.memory
        return 1

    def CreateDIBSection(self, dc, info, usage, pointer, section, offset):
        assert dc == self.desktop and usage == 0 and section is None and offset == 0
        header = info._obj.header
        assert header.size == 40 and header.height < 0 and header.planes == 1
        assert header.bits == 32 and header.compression == 0
        size = header.width * -header.height * 4
        assert size <= sampling._MAX_PIXELS * 4
        buffer = (ctypes.c_ubyte * size)()
        self.buffers[self.bitmap] = buffer
        pointer._obj.value = ctypes.addressof(buffer)
        return self.bitmap

    def SelectObject(self, dc, obj):
        assert dc == self.memory and obj in (self.bitmap, self.stock)
        return self.stock if obj == self.bitmap else self.bitmap

    def DeleteObject(self, obj):
        assert obj == self.bitmap
        self.buffers.pop(obj)
        return 1

    def BitBlt(self, dest, x, y, width, height, source, left, top, flags):
        assert dest == self.memory and source == self.desktop and x == y == 0
        assert flags == 0x40CC0020
        self.pending = width, height, left, top
        return 1

    def GdiFlush(self):
        width, height, left, top = self.pending
        buffer = self.buffers[self.bitmap]
        for y in range(height):
            for x in range(width):
                red, green, blue = self.rgb(left + x, top + y)
                offset = (y * width + x) * 4
                buffer[offset:offset + 4] = blue, green, red, 0
        self.pending = None
        return 1


class ScreenSamplingTests(unittest.TestCase):
    def boundary(self, fail=None):
        native = _NativeBoundary(fail)
        library = _Library(native)
        self.enterContext(patch('WindowsSystem.load_system_library', return_value=library))
        self.enterContext(patch('ScreenPixelSampling.load_system_library', return_value=library))
        # The old public implementation uses this boundary; it must run in the
        # before check instead of an independently rewritten scalar algorithm.
        self.enterContext(patch.object(ctypes, 'windll', SimpleNamespace(user32=library, gdi32=library), create=True))
        return native

    def patch_points(self):
        return [(x, y) for y in range(-9, 4) for x in range(-120, -107)]

    def assert_released(self, native):
        names = [name for name, _ in native.calls]
        self.assertEqual(names.count('GetDC'), 1)
        self.assertEqual(names.count('ReleaseDC'), 1)
        self.assertEqual(names[-1], 'ReleaseDC')
        self.assertEqual(native.buffers, {})

    def test_public_stroke_patch_uses_one_transfer_with_exact_order_and_duplicates(self):
        native = self.boundary()
        points = self.patch_points()[::-1] + [(-120, -9)] * 2
        actual = Colors.sample_screen_colors(iter(points))
        self.assertEqual(actual, [native.rgb(*point) for point in points])
        names = [name for name, _ in native.calls]
        self.assertEqual(names.count('GetPixel'), 0, 'Each dense sample still synchronizes a native GetPixel call.')
        self.assertEqual(names.count('BitBlt'), 1)
        self.assertEqual(names.count('GdiFlush'), 1)
        self.assertLess(names.index('DeleteDC'), names.index('DeleteObject'))
        self.assert_released(native)

    def test_small_palette_and_large_sparse_batch_keep_scalar_results(self):
        for points in (self.patch_points()[:8], [((i % 8) * 240, (i // 8) * 240) for i in range(40)],
                       [(0, 0)] * (sampling._MAX_POINTS + 5), []):
            with self.subTest(count=len(points)):
                native = self.boundary()
                self.assertEqual(Colors.sample_screen_colors(iter(points)), [native.rgb(*p) for p in points])
                names = [name for name, _ in native.calls]
                self.assertNotIn('CreateDIBSection', names)
                self.assertEqual(names.count('GetPixel'), len(points))
                self.assert_released(native)

    def test_real_guarded_stroke_consumer_keeps_its_verdict_with_one_grouped_read(self):
        native = self.boundary()
        monitor = object.__new__(WindowMonitor)
        monitor.verify = lambda *_: None
        mouse = SimpleNamespace(get_position=lambda: (-160, 20))
        guard = GuardedMouse(mouse, monitor, (10, native.rect))
        expected = native.rgb(-148, 20)
        verdict = guard.inspect_ink_segment((-160, 20), (-100, 20), expected, brush_px=1)
        self.assertTrue(verdict['matched'])
        self.assertEqual(verdict['actual'], expected)
        self.assertEqual(verdict['error'], 0)
        self.assertEqual(verdict['confidence'], 100.0)
        self.assertEqual(verdict['sample_count'], 125)
        names = [name for name, _ in native.calls]
        self.assertEqual(names.count('BitBlt'), 1)
        self.assertEqual(names.count('GetPixel'), 0)
        self.assertEqual(names.count('GetDC'), 1)
        self.assertEqual(names.count('ReleaseDC'), 1)
        self.assertEqual(native.buffers, {})

    def test_fallback_releases_every_completed_native_acquisition(self):
        for failure in ('MonitorFromPoint', 'GetMonitorInfoW', 'CreateCompatibleDC',
                        'CreateDIBSection', 'SelectObject', 'BitBlt', 'GdiFlush'):
            with self.subTest(failure=failure):
                native = self.boundary(failure)
                points = self.patch_points()
                self.assertEqual(Colors.sample_screen_colors(points), [native.rgb(*p) for p in points])
                names = [name for name, _ in native.calls]
                self.assertEqual(names.count('GetPixel'), len(points))
                self.assert_released(native)
                if failure in ('CreateDIBSection', 'SelectObject', 'BitBlt', 'GdiFlush'):
                    self.assertEqual(names.count('DeleteDC'), 1)
                if failure in ('SelectObject', 'BitBlt', 'GdiFlush'):
                    self.assertEqual(names.count('DeleteObject'), 1)

    def test_unreadable_monitor_edge_is_not_fabricated_as_a_valid_black_pixel(self):
        native = self.boundary()
        points = [(1915 + x, 20) for x in range(32)]
        with self.assertRaisesRegex(OSError, 'screen position'):
            Colors.sample_screen_colors(points)
        self.assertNotIn('CreateDIBSection', [name for name, _ in native.calls])
        self.assert_released(native)

    def test_memory_error_keeps_the_scalar_reader_available(self):
        native = self.boundary()
        points = self.patch_points()
        with patch('ScreenPixelSampling._read_compact', side_effect=MemoryError('optional buffer')):
            self.assertEqual(Colors.sample_screen_colors(points), [native.rgb(*p) for p in points])
        self.assert_released(native)

    def test_optional_prefix_oom_preserves_the_pending_point_and_iterator_tail(self):
        for after in (0, 8, sampling._MAX_POINTS):
            with self.subTest(after=after):
                native = self.boundary()
                points = (self.patch_points() + [(-120, -9)] * 2) * 15
                class BoundedList(list):
                    def append(self, item):
                        if len(self) == after:
                            raise MemoryError('optional prefix growth')
                        super().append(item)
                with patch.object(sampling, 'list', BoundedList, create=True):
                    actual = Colors.sample_screen_colors(iter(points))
                self.assertEqual(actual, [native.rgb(*point) for point in points])
                self.assertEqual(sum(name == 'GetPixel' for name, _ in native.calls), len(points))
                self.assert_released(native)

    def test_reused_mutable_point_is_observed_before_the_iterator_advances(self):
        for count in (32, sampling._MAX_POINTS + 32):
            with self.subTest(count=count):
                native = self.boundary()
                expected_points = [(-120 + i % 16, -9 + (i // 16) % 13) for i in range(count)]
                def points():
                    pair = [0, 0]
                    for x, y in expected_points:
                        pair[:] = x, y
                        yield pair
                self.assertEqual(Colors.sample_screen_colors(points()),
                                 [native.rgb(*p) for p in expected_points])
                self.assert_released(native)

    def test_optional_prefix_and_coordinate_allocation_oom_can_use_the_original_stream(self):
        for boundary in ('list', 'int'):
            with self.subTest(boundary=boundary):
                native = self.boundary()
                points = self.patch_points()[::-1]
                calls = []
                def allocate(*args):
                    calls.append(args)
                    if len(calls) == 1:
                        raise MemoryError('optional preparation')
                    return int(*args)
                with patch.object(sampling, boundary, side_effect=allocate, create=True):
                    self.assertEqual(Colors.sample_screen_colors(iter(points)),
                                     [native.rgb(*p) for p in points])
                self.assertEqual(sum(name == 'GetPixel' for name, _ in native.calls), len(points))
                self.assert_released(native)

    def test_coordinate_iteration_failure_releases_the_desktop(self):
        native = self.boundary()
        def broken():
            yield (20, 30)
            raise ValueError('broken source')
        with self.assertRaisesRegex(ValueError, 'broken source'):
            Colors.sample_screen_colors(broken())
        self.assert_released(native)

    def test_failed_desktop_acquisition_does_not_release_an_unowned_handle(self):
        native = self.boundary('GetDC')
        with self.assertRaisesRegex(OSError, 'screen colors'):
            Colors.sample_screen_colors(self.patch_points())
        self.assertNotIn('ReleaseDC', [name for name, _ in native.calls])

    def test_fixed_width_native_layouts(self):
        self.assertEqual(ctypes.sizeof(sampling._Point), 8)
        self.assertEqual(ctypes.sizeof(sampling._Rect), 16)
        self.assertEqual(ctypes.sizeof(sampling._MonitorInfo), 40)
        self.assertEqual(ctypes.sizeof(sampling._BitmapInfoHeader), 40)
        self.assertEqual(ctypes.sizeof(sampling._BitmapInfo), 44)


@unittest.skipUnless(sys.platform == 'win32', 'Real Windows desktop sampling gate')
class NativeScreenSamplingTests(unittest.TestCase):
    def test_existing_asset_matches_getpixel_without_retained_gdi_resources(self):
        script = r'''
import ctypes, json, time
from pathlib import Path
import tkinter as tk
from unittest.mock import patch
import Colors
import ScreenPixelSampling as sampling
from WindowsSystem import load_system_library

root = tk.Tk()
try:
    root.geometry('600x600+40+40')
    root.attributes('-topmost', True)
    source = tk.PhotoImage(file=str(Path('assets/image-draw-bot-icon.png').resolve()))
    label = tk.Label(root, image=source, borderwidth=0, highlightthickness=0)
    label.pack()
    root.update()
    left, top = label.winfo_rootx() + 45, label.winfo_rooty() + 45
    points = [(left + x, top + y) for y in range(13) for x in range(13)]
    user, gdi = load_system_library('user32.dll'), load_system_library('gdi32.dll')
    resources = sampling._function(user, 'GetGuiResources', [ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint32)
    def scalar():
        # The previous public reader, including its per-call DLL binding work.
        from ctypes import wintypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi32.GetPixel.restype = wintypes.DWORD
        dc = user32.GetDC(None)
        if not dc:
            raise OSError('Cannot read screen colors.')
        try:
            result = []
            for x,y in points:
                v = gdi32.GetPixel(dc, int(x), int(y))
                if v == 0xffffffff:
                    raise OSError('Cannot read this screen position.')
                result.append((v&255,(v>>8)&255,(v>>16)&255))
            return result
        finally:
            user32.ReleaseDC(None, dc)
    real_read = sampling._read_compact
    calls = []
    def observe(*args):
        result = real_read(*args)
        calls.append(len(result))
        return result
    expected = scalar()
    assert len(set(expected)) > 1, 'Existing artwork fixture did not expose varied native pixels.'
    with patch.object(sampling, '_read_compact', side_effect=observe):
        before = resources(ctypes.c_void_p(-1), 0)
        assert before > 0
        for _ in range(12):
            assert Colors.sample_screen_colors(points) == expected
        after = resources(ctypes.c_void_p(-1), 0)
    assert calls == [169] * 12, calls
    assert after <= before, (before, after)
    measurements = []
    cases = [points[:8]] + [[(left + x, top + y) for y in range(side) for x in range(side)]
                           for side in (5, 9, 13)]
    for points in cases:
        expected = scalar()
        assert Colors.sample_screen_colors(points) == expected
        timings = {'scalar': [], 'public': []}
        for repeat in range(6):
            order = ('scalar','public') if repeat%2 == 0 else ('public','scalar')
            for kind in order:
                start = time.perf_counter()
                actual = scalar() if kind == 'scalar' else Colors.sample_screen_colors(points)
                elapsed = time.perf_counter() - start
                assert actual == expected
                timings[kind].append(elapsed*1000)
        measurements.append({'points':len(points),'paired_ms':timings})
    print('NATIVE_SCREEN_SAMPLING=' + json.dumps({'points':169,'gdi_before':before,'gdi_after':after,'measurements':measurements}))
finally:
    root.destroy()
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parent,
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        self.assertNotIn('invalid command name', result.stderr)
        line = next(line for line in result.stdout.splitlines() if line.startswith('NATIVE_SCREEN_SAMPLING='))
        evidence = json.loads(line.split('=', 1)[1])
        self.assertEqual(evidence['points'], 169)
        print(line)


if __name__ == '__main__':
    unittest.main()
