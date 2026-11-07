"""Real legacy/grid consumers keep their bounded, all-or-nothing storage contract."""
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import Colors
import GetColorPositions as capture
import RuntimePaths
from test_v148_platform_batch26_color_storage import ColorStorageFixture, Value


class Widget:
    def __init__(self, *args, **kwargs):
        self.destroyed = False

    def __getattr__(self, name):
        if name == 'get_children':
            return lambda: ()
        return lambda *args, **kwargs: None

    def destroy(self):
        self.destroyed = True


class Layout(Widget):
    def __init__(self, root, **kwargs):
        super().__init__()
        self.body, self.footer = Widget(), Widget()

    def label(self, **kwargs):
        return Widget()


class NoMouse:
    def __getattr__(self, name):
        raise AssertionError('No mouse operation is permitted: ' + name)


class PaletteBoundaryTests(ColorStorageFixture):
    @contextmanager
    def native_ui_boundary(self):
        with ExitStack() as stack:
            stack.enter_context(patch('WindowsMouse.WindowsMouse', return_value=NoMouse()))
            stack.enter_context(patch('WorkspaceLayout.fit_window'))
            stack.enter_context(patch('CalibrationDialogLayout.CalibrationDialogLayout', Layout))
            for name in ('Style', 'Label', 'Button', 'Frame', 'Combobox', 'Entry', 'Treeview'):
                stack.enter_context(patch.object(capture.ttk, name, Widget))
            for name in ('StringVar', 'IntVar'):
                stack.enter_context(patch.object(capture.tk, name, Value))
            stack.enter_context(patch.object(capture.tk, 'Canvas', Widget))
            yield

    def construct(self):
        root = Widget()
        with self.native_ui_boundary():
            app = capture.CalibrationApp(root, path=self.palette, profile='generic')
            try:
                return app.rows.get(), app.columns.get()
            finally:
                app.close()
                self.assertTrue(root.destroyed)

    def assert_bounded_reads(self, reads, expected_bytes):
        self.assertTrue(reads)
        self.assertTrue(all(0 < size <= 65536 for size, _actual in reads), reads)
        self.assertEqual(sum(actual for _size, actual in reads), expected_bytes)

    def test_actual_constructor_rejects_ambiguous_grid_preferences(self):
        path = self.palette.with_suffix('.grid.json')
        path.write_text('{"rows": 1, "columns": 3}', encoding='utf-8')
        self.assertEqual(self.construct(), (1, 3))
        cases = {
            'duplicate': '{"rows": 2, "rows": 1, "columns": 3}',
            'nonfinite extra': '{"rows": 1, "columns": 3, "extra": NaN}',
            'depth40 extra': '{"rows": 1, "columns": 3, "extra": ' + '[' * 40 + '0' + ']' * 40 + '}',
            'oversized preference': '{"rows": 1, "columns": 3}' + ' ' * (4 * 1024 * 1024),
        }
        for name, content in cases.items():
            with self.subTest(document=name):
                path.write_text(content, encoding='utf-8')
                before = path.read_bytes()
                with self.observe_reads(path) as reads:
                    actual = self.construct()
                self.assertEqual(path.read_bytes(), before)
                with self.subTest(boundary='safe defaults', actual=actual):
                    self.assertEqual(actual, (2, 9))
                with self.subTest(boundary='bounded read'):
                    self.assert_bounded_reads(reads, min(len(before), 4 * 1024 * 1024 + 1))

    def test_grid_exact_limit_and_existing_domain_defaults(self):
        path = self.palette.with_suffix('.grid.json')
        limit = 4 * 1024 * 1024
        valid = b'\xef\xbb\xbf{"rows": 1, "columns": 3, "note": "local preference"}'
        content = valid + b' ' * (limit - len(valid))
        path.write_bytes(content)
        with self.observe_reads(path) as reads:
            self.assertEqual(self.construct(), (1, 3))
        self.assert_bounded_reads(reads, limit)
        self.assertEqual(path.read_bytes(), content)
        for content in (b'\xff', b'[]', b'{"rows":true,"columns":3}',
                        b'{"rows":0,"columns":3}', b'{"rows":97,"columns":1}',
                        b'{"rows":1}', b'{"rows":1.0,"columns":3}'):
            with self.subTest(content=content):
                path.write_bytes(content)
                self.assertEqual(self.construct(), (2, 9))
                self.assertEqual(path.read_bytes(), content)
        path.unlink()
        self.assertEqual(self.construct(), (2, 9))
        self.assertFalse(path.exists())

    def test_actual_legacy_fallback_bounds_positions_before_publishing_colors(self):
        positions = self.root / 'positions.txt'
        palette = self.root / 'palette.json'
        expected = [(i - 30, 20) for i in range(len(Colors.allColors))]
        raw = ''.join(f'{x}\r\n{y}\r\n' for x, y in expected).encode('utf-8')
        palette.write_text(json.dumps([list(c.RGB) for c in Colors.allColors]), encoding='utf-8')
        with patch.object(Colors, 'CALIBRATION_FILE', self.palette), \
             patch.object(Colors, 'PALETTE_FILE', palette), \
             patch.object(Colors.load_positions, '__defaults__', (positions,)):
            for size in (len(raw), 8 * 1024 * 1024):
                with self.subTest(accepted_bytes=size):
                    content = b' ' * (size - len(raw)) + raw
                    positions.write_bytes(content)
                    with self.observe_reads(positions) as reads:
                        result = Colors.load_calibration(self.palette)
                    self.assertEqual(result, {'anchor': None, 'count': len(expected)})
                    self.assertEqual([(c.x, c.y) for c in Colors.allColors], expected)
                    self.assert_bounded_reads(reads, size)
                    self.assertEqual(positions.read_bytes(), content)
                    self.restore_palette()
            before = self.palette_state()
            # Whitespace keeps every old integer and line count valid.
            size = 8 * 1024 * 1024 + 1
            positions.write_bytes(b' ' * (size - len(raw)) + raw)
            failure = None
            with self.observe_reads(positions) as reads:
                try:
                    Colors.load_calibration(self.palette)
                except ValueError as exc:
                    failure = exc
            with self.subTest(boundary='controlled byte rejection'):
                self.assertIsInstance(failure, ValueError)
            with self.subTest(boundary='unchanged palette'):
                self.assertEqual(self.palette_state(), before)
            with self.subTest(boundary='bounded read'):
                self.assert_bounded_reads(reads, size)
            for content in (b'\xff', b'1\n2\n', b'\xef\xbb\xbf' + raw, raw.replace(b'-30', b'bad', 1)):
                with self.subTest(invalid_prefix=content[:12]):
                    self.restore_palette()
                    before = self.palette_state()
                    positions.write_bytes(content)
                    with self.assertRaises(ValueError):
                        Colors.load_calibration(self.palette)
                    self.assertEqual(self.palette_state(), before)
                    self.assertEqual(positions.read_bytes(), content)

    def test_shared_text_reader_preserves_newlines_and_closes_before_decode_failure(self):
        path = self.root / 'text.txt'
        text = 'Å\r\n-30\n20\r'
        content = text.encode('utf-8')
        path.write_bytes(content)
        with self.observe_reads(path) as reads:
            self.assertEqual(RuntimePaths.read_bounded_text(path, max_bytes=len(content)), text)
        self.assert_bounded_reads(reads, len(content))
        with self.assertRaises(ValueError):
            RuntimePaths.read_bounded_text(path, max_bytes=len(content) - 1)
        opened = []
        original = Path.open
        def opening(source, *args, **kwargs):
            stream = original(source, *args, **kwargs)
            opened.append(stream)
            return stream
        path.write_bytes(b'\xff')
        with patch.object(Path, 'open', new=opening):
            with self.assertRaises(UnicodeDecodeError) as caught:
                RuntimePaths.read_bounded_text(path)
        self.assertIsNotNone(caught.exception)
        self.assertTrue(opened)
        self.assertTrue(all(stream.closed for stream in opened))
        self.assertEqual(path.read_bytes(), b'\xff')


if __name__ == '__main__':
    unittest.main(verbosity=2)
