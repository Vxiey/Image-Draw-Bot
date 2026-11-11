"""Portable capture includes the legacy calibration actually used by its owner.

Real source files, package validation, export publication and import/readback
are used. Native dialogs and unrelated window feedback are the only UI doubles.
"""
from copy import deepcopy
import errno
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import Colors
import GameProfiles
import PaintTools
import PixelData
import ProfilePortability as portability
import RuntimePaths
import test_v148_application_batch37_legacy_palette as palette_fixture


class LegacyCalibrationExportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = palette_fixture.LegacyPaletteResetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.export = self.root / 'retained.drawprofile'
        portability.write_profile_file(self.export, portability.build_package('Microsoft Paint', {}))
        self.old_export = self.export.read_bytes()
        self.paint_legacy = self.root / 'paint-tools.json'
        self.paint_current = self.root / 'paint-tools-microsoft-paint.json'
        self.paint_source = {'version': 3, 'tools': {'Pencil': [40, 30], 'Fill': [20, 30]},
                             'anchor': {'version': 1, 'client_rect': [0, 0, 200, 100]}}
        self.paint_legacy.write_text(json.dumps(self.paint_source), encoding='utf-8')

    def app(self, name='Other drawing app'):
        app = self.fixture.app(name)

        def save_settings():
            RuntimePaths.atomic_write_text(app.settings_path, '{"settings_schema":2,"quality":"Balanced"}')
            return True

        app.save_settings = save_settings
        save_settings()
        return app

    @staticmethod
    def color_state():
        return [(color, dict(vars(color))) for color in Colors.allColors]

    def expected_legacy(self, *, default_rgb=False):
        rgbs = [list(rgb) for _name, rgb in Colors.DEFAULT_COLORS] if default_rgb else self.fixture.legacy_rgbs
        return {'version': 1, 'colors': [
            {'name': name, 'position': list(position), 'rgb': rgb}
            for (name, _default_rgb), position, rgb in zip(
                Colors.DEFAULT_COLORS, self.fixture.legacy_positions, rgbs)]}

    def export_dialog(self, app):
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.export)) as chooser, \
                patch('tkinter.messagebox.showerror') as error, \
                patch('tkinter.messagebox.showinfo') as info:
            result = portability.export_profile_dialog(app)
        return result, chooser, error, info

    def assert_blocked(self, app):
        self.export.write_bytes(self.old_export)
        before = self.fixture.disk_state()
        colors = self.color_state()
        captured_error = None
        try:
            portability.package_from_app(app)
        except Exception as error:
            captured_error = error
        result, chooser, error, info = self.export_dialog(app)
        self.assertEqual(self.fixture.disk_state(), before)
        self.assertIsInstance(captured_error, (portability.ProfilePortabilityError, OSError))
        self.assertIsNone(result)
        chooser.assert_not_called()
        error.assert_called_once()
        info.assert_not_called()
        self.assertEqual(self.color_state(), colors)

    def test_generic_export_roundtrip_keeps_actual_legacy_palette_without_mutating_it(self):
        app = self.app()
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        colors = self.color_state()
        cache = PixelData.closest_color.cache_info()
        sources = {path: path.read_bytes() for path in (self.fixture.positions, self.fixture.palette)}
        captured = portability.package_from_app(app)
        self.assertEqual(captured['calibration'], {'palette': self.expected_legacy()})
        self.assertEqual(self.color_state(), colors)
        self.assertEqual(PixelData.closest_color.cache_info(), cache)
        self.assertFalse(self.fixture.current.exists())
        result, chooser, error, info = self.export_dialog(app)
        self.assertEqual(result, self.export)
        chooser.assert_called_once()
        error.assert_not_called()
        info.assert_called_once()
        package = portability.read_profile_file(self.export)
        self.assertEqual(package['calibration'], captured['calibration'])
        self.assertTrue(package['safety']['requires_reverification'])
        self.assertFalse(package['safety']['machine_specific_state_included'])
        before_package = deepcopy(package)
        copied = portability.import_package_into_app(app, package, action='copy', copy_name='Legacy palette copy')
        self.assertEqual(copied, 'Legacy palette copy')
        self.assertTrue(app.palette_ready)
        self.assertEqual([(color.x, color.y) for color in Colors.allColors], self.fixture.legacy_positions)
        self.assertEqual([list(color.RGB) for color in Colors.allColors], self.fixture.legacy_rgbs)
        self.assertEqual({path: path.read_bytes() for path in sources}, sources)
        self.assertEqual(package, before_package)

    def test_positions_only_exports_the_same_default_colors_as_normal_profile_reload(self):
        self.fixture.palette.unlink()
        app = self.app()
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        expected = self.expected_legacy(default_rgb=True)
        self.assertEqual([list(color.RGB) for color in Colors.allColors], [row['rgb'] for row in expected['colors']])
        before = self.color_state()
        self.assertEqual(portability.package_from_app(app)['calibration'], {'palette': expected})
        self.assertEqual(self.color_state(), before)
        self.assertFalse(self.fixture.palette.exists())
        self.assertFalse(self.fixture.current.exists())

    def test_paint_export_keeps_legacy_tools_without_publishing_a_migration_as_a_side_effect(self):
        for payload in ({'version': 1, 'tools': {'Pencil': [20, 30], 'Brush': [40, 50]}}, self.paint_source):
            with self.subTest(version=payload['version']):
                self.paint_legacy.write_text(json.dumps(payload), encoding='utf-8')
                app = self.app('Microsoft Paint')
                before = self.fixture.disk_state()
                package = portability.package_from_app(app)
                self.assertEqual(package['calibration'], {'tools': payload})
                self.assertEqual(self.fixture.disk_state(), before)
                self.assertFalse(self.paint_current.exists())
                portability.write_profile_file(self.export, package)
                imported = portability.read_profile_file(self.export)
                self.assertEqual(imported['calibration'], {'tools': payload})
                portability.apply_package_to_paths(imported, 'microsoft-paint', root=self.root / 'receiver')
                restored = PaintTools.load_tool_calibration(self.root / 'receiver' / self.paint_current.name)
                self.assertEqual(restored, PaintTools.validate_tool_calibration(payload))

    def test_canonical_calibration_wins_without_reading_or_changing_old_legacy_sources(self):
        app = self.app()
        self.fixture.seed_current(app)
        self.fixture.positions.write_text('invalid old positions', encoding='utf-8')
        self.fixture.palette.write_text('{bad old palette', encoding='utf-8')
        self.paint_legacy.write_text('{bad old tools', encoding='utf-8')
        canonical_palette = json.loads(self.fixture.current.read_text(encoding='utf-8'))
        self.paint_current.write_text(json.dumps(self.paint_source), encoding='utf-8')
        for name, expected in (('Other drawing app', {'palette': canonical_palette}),
                               ('Microsoft Paint', {'tools': self.paint_source})):
            with self.subTest(profile=name):
                app = self.app(name)
                before = self.fixture.disk_state()
                self.assertEqual(portability.package_from_app(app)['calibration'], expected)
                self.assertEqual(self.fixture.disk_state(), before)

    def test_legacy_paint_sources_must_fit_the_actual_tool_reader_before_export(self):
        app = self.app('Microsoft Paint')
        for extra in ({'note': 'x' * (140 * 1024)}, {'unused': [None] * 2100}):
            with self.subTest(limit=next(iter(extra))):
                payload = dict(self.paint_source, **extra)
                self.paint_legacy.write_text(json.dumps(payload), encoding='utf-8', newline='')
                with self.assertRaises(ValueError):
                    PaintTools.load_tool_calibration(self.paint_legacy)
                self.assert_blocked(app)
                self.assertFalse(self.paint_current.exists())

    def test_other_builtin_and_custom_exports_do_not_capture_generic_or_paint_legacy_files(self):
        for name in ('Gartic Phone', 'Legacy reset custom'):
            with self.subTest(profile=name):
                app = self.app(name)
                before = self.fixture.disk_state()
                package = portability.package_from_app(app)
                self.assertEqual(package['calibration'], {})
                self.assertEqual(package['profile']['key'], GameProfiles.PROFILES[name][0])
                self.assertEqual(self.fixture.disk_state(), before)

    def test_incomplete_malformed_and_oversized_legacy_sources_cannot_replace_previous_export(self):
        app = self.app()
        for case in ('missing_positions', 'truncated_positions', 'duplicate_positions',
                     'bad_palette_json', 'bad_palette_count', 'bad_palette_color', 'oversized_positions'):
            with self.subTest(source=case):
                self.fixture.seed_legacy()
                if case == 'missing_positions':
                    self.fixture.positions.unlink()
                elif case == 'truncated_positions':
                    self.fixture.positions.write_text('10\n20\n', encoding='utf-8')
                elif case == 'duplicate_positions':
                    self.fixture.positions.write_text('10\n20\n' * len(Colors.DEFAULT_COLORS), encoding='utf-8')
                elif case == 'bad_palette_json':
                    self.fixture.palette.write_text('{invalid', encoding='utf-8')
                elif case == 'bad_palette_count':
                    self.fixture.palette.write_text('[]', encoding='utf-8')
                elif case == 'bad_palette_color':
                    values = deepcopy(self.fixture.legacy_rgbs)
                    values[0] = [999, 0, 0]
                    self.fixture.palette.write_text(json.dumps(values), encoding='utf-8')
                else:
                    with self.fixture.positions.open('wb') as stream:
                        stream.truncate(Colors.MAX_CALIBRATION_BYTES + 1)
                self.assert_blocked(app)
        app = self.app('Microsoft Paint')
        self.paint_legacy.write_text('{invalid old Paint JSON', encoding='utf-8')
        self.assert_blocked(app)

    def test_absent_legacy_sources_remain_optional_and_existing_directories_are_rejected(self):
        self.fixture.positions.unlink()
        self.fixture.palette.unlink()
        app = self.app()
        self.assertEqual(portability.package_from_app(app)['calibration'], {})
        for path in (self.fixture.positions, self.fixture.palette):
            with self.subTest(source=path.name):
                path.mkdir()
                try:
                    self.assert_blocked(app)
                finally:
                    path.rmdir()

    def test_regular_legacy_symlinks_export_without_replacing_links_and_broken_links_fail(self):
        source = self.fixture.positions
        target = self.root / 'positions-original.txt'
        source.replace(target)
        try:
            source.symlink_to(target.name)
        except (NotImplementedError, OSError) as error:
            if isinstance(error, NotImplementedError) or getattr(error, 'winerror', None) == 1314 or \
                    getattr(error, 'errno', None) in (errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP):
                self.skipTest('This host does not permit the native symlink fixture.')
            raise
        app = self.app()
        self.assertEqual(portability.package_from_app(app)['calibration'], {'palette': self.expected_legacy()})
        self.assertTrue(source.is_symlink())
        self.assertTrue(target.exists())
        target.unlink()
        self.assertTrue(source.is_symlink())
        # disk_state reads regular files, so the dangling link itself is checked
        # explicitly in addition to all existing source/destination bytes.
        self.assert_blocked(app)
        self.assertTrue(source.is_symlink())

    @unittest.skipUnless(hasattr(os, 'mkfifo') and os.name == 'posix', 'Native FIFO fixture requires POSIX.')
    def test_fifo_legacy_sources_are_rejected_before_any_open(self):
        app = self.app()
        native_open = Path.open
        for source in (self.fixture.positions, self.fixture.palette):
            with self.subTest(source=source.name):
                original = source.read_bytes()
                source.unlink()
                os.mkfifo(source)
                opened = []

                def guarded_open(path, *args, **kwargs):
                    if path == source:
                        opened.append(path)
                        raise AssertionError('A FIFO must not be opened by profile export')
                    return native_open(path, *args, **kwargs)

                try:
                    with patch.object(Path, 'open', guarded_open):
                        self.assert_blocked(app)
                    self.assertEqual(opened, [])
                finally:
                    source.unlink()
                    source.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
