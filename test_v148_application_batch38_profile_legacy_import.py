"""Replace imports retire only their own legacy calibration inputs atomically.

The public importer, staged file-set publisher, profile reload and palette/tool
readers are real. The existing headless profile fixture replaces unrelated UI
surfaces; no input or raster generation is involved.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import AppTools
import Colors
import GameProfiles
import PaintTools
import ProfilePortability as portability
import RuntimePaths
import test_v148_application_batch37_legacy_palette as palette_fixture


class LegacyCalibrationImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = palette_fixture.LegacyPaletteResetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.paint_legacy = self.root / 'paint-tools.json'
        self.paint_current = self.root / 'paint-tools-microsoft-paint.json'
        self.enterContext(patch.object(PaintTools, 'TOOL_FILE', self.paint_current))
        self.enterContext(patch.object(PaintTools, 'LEGACY_TOOL_FILE', self.paint_legacy))
        self.paint_source = {
            'version': 3, 'tools': {'Pencil': [40, 30], 'Fill': [20, 30]},
            'anchor': {'version': 1, 'client_rect': [0, 0, 200, 100]},
        }
        self.paint_legacy.write_text(json.dumps(self.paint_source), encoding='utf-8')

    def package(self, name, calibration=None):
        path = self.root / 'incoming.drawprofile'
        portability.write_profile_file(path, portability.build_package(
            name, {'quality': 'High detail'}, calibration))
        return portability.read_profile_file(path)

    def assert_generic_retired(self, app):
        self.assertFalse(self.fixture.positions.exists())
        self.assertFalse(self.fixture.palette.exists())
        self.assertFalse(app.palette_ready)
        app.refresh_palette()
        self.assertFalse(app.palette_ready)
        self.fixture.assert_shared_unchanged()

    def test_generic_replace_without_palette_cannot_reload_old_legacy_calibration(self):
        for canonical_exists in (False, True):
            with self.subTest(canonical_exists=canonical_exists):
                self.fixture.seed_legacy()
                app = self.fixture.app()
                if canonical_exists:
                    self.fixture.seed_current(app)
                app.refresh_palette()
                self.assertTrue(app.palette_ready)
                paint_bytes = self.paint_legacy.read_bytes()
                package = self.package('Other drawing app')
                original = deepcopy(package)
                self.assertEqual(portability.import_package_into_app(app, package), 'Other drawing app')
                self.assert_generic_retired(app)
                self.assertFalse(self.fixture.current.exists())
                self.assertEqual(app.quality.get(), 'High detail')
                self.assertEqual(self.paint_legacy.read_bytes(), paint_bytes)
                self.assertEqual(package, original)
                self.assertIsNone(app.plan)
                self.assertTrue(app.stop.is_set())

    def test_generic_replace_with_palette_retires_aliases_and_loads_imported_colors(self):
        app = self.fixture.app()
        payload = {'version': 4, 'profile': 'generic', 'state': 'calibrated', 'colors': [
            {'name': 'Imported color', 'position': [80, 90], 'rgb': [12, 34, 56]}]}
        package = self.package('Other drawing app', {'palette': payload})
        portability.import_package_into_app(app, package)
        self.assertFalse(self.fixture.positions.exists())
        self.assertFalse(self.fixture.palette.exists())
        self.assertTrue(app.palette_ready)
        self.assertEqual([(color.x, color.y, color.RGB) for color in Colors.allColors],
                         [(80, 90, (12, 34, 56))])
        self.assertEqual(json.loads(self.fixture.current.read_text(encoding='utf-8')), payload)
        self.fixture.assert_shared_unchanged()
        # Removing this newly imported calibration must not reveal the previous
        # profile's fixed coordinates on the next normal reload.
        self.fixture.current.unlink()
        app.refresh_palette()
        self.assertFalse(app.palette_ready)

    def test_paint_replace_without_tools_prevents_legacy_automatic_remigration(self):
        app = self.fixture.app('Microsoft Paint')
        self.assertEqual(PaintTools.load_tool_calibration(self.paint_current)['tools'],
                         self.paint_source['tools'])
        self.assertTrue(self.paint_current.exists())
        generic_before = {path: path.read_bytes() for path in (self.fixture.positions, self.fixture.palette)}
        portability.import_package_into_app(app, self.package('Microsoft Paint'))
        self.assertFalse(self.paint_legacy.exists())
        self.assertFalse(self.paint_current.exists())
        for _attempt in range(2):
            with self.assertRaises(FileNotFoundError):
                PaintTools.load_tool_calibration(self.paint_current)
        self.assertEqual({path: path.read_bytes() for path in generic_before}, generic_before)
        self.fixture.assert_shared_unchanged()

    def test_paint_replace_with_tools_preserves_new_coordinates_and_removes_old_source(self):
        app = self.fixture.app('Microsoft Paint')
        payload = deepcopy(self.paint_source)
        payload['tools']['Pencil'] = [100, 50]
        portability.import_package_into_app(app, self.package('Microsoft Paint', {'tools': payload}))
        self.assertFalse(self.paint_legacy.exists())
        self.assertEqual(PaintTools.load_tool_calibration(self.paint_current)['tools'], payload['tools'])
        self.paint_current.unlink()
        with self.assertRaises(FileNotFoundError):
            PaintTools.load_tool_calibration(self.paint_current)
        self.fixture.assert_shared_unchanged()

    def test_copy_does_not_retire_sources_owned_by_the_original_builtin(self):
        source_paths = (self.fixture.positions, self.fixture.palette, self.paint_legacy)
        original_bytes = {path: path.read_bytes() for path in source_paths}
        registry_before = json.loads((self.root / 'profiles.json').read_text(encoding='utf-8'))
        for name, calibration in (('Other drawing app', {}),
                                  ('Microsoft Paint', {'tools': self.paint_source})):
            with self.subTest(profile=name):
                app = self.fixture.app(name)
                copied_name = f'{name} copy'
                self.assertEqual(portability.import_package_into_app(
                    app, self.package(name, calibration), action='copy', copy_name=copied_name), copied_name)
                key = GameProfiles.PROFILES[copied_name][0]
                self.assertTrue(key.startswith('custom-'))
                self.assertEqual({path: path.read_bytes() for path in source_paths}, original_bytes)
                self.assertEqual(app._active_profile_name, copied_name)
                self.assertEqual(app.quality.get(), 'High detail')
                if calibration:
                    tools = AppTools.load_calibration(key, self.root / f'app-tools-{key}.json')
                    self.assertEqual(tools['tools'], {'Fill': [20, 30]})
                    self.assertEqual(tools['anchor'], self.paint_source['anchor'])
        registry_after = json.loads((self.root / 'profiles.json').read_text(encoding='utf-8'))
        for name, key in registry_before.items():
            self.assertEqual(registry_after[name], key)
        for path in self.fixture.shared_paths[1:]:
            self.assertEqual(path.read_bytes(), self.fixture.shared_bytes[path])

    def test_other_builtin_and_custom_replacements_leave_both_legacy_owners_untouched(self):
        source_paths = (self.fixture.positions, self.fixture.palette, self.paint_legacy)
        before = {path: path.read_bytes() for path in source_paths}
        for name in ('Gartic Phone', 'Legacy reset custom'):
            with self.subTest(profile=name):
                app = self.fixture.app(name)
                self.fixture.seed_current(app)
                portability.import_package_into_app(app, self.package(name))
                self.assertFalse(app.calibration_path.exists())
                self.assertFalse(app.palette_ready)
                self.assertEqual(app.quality.get(), 'High detail')
                self.assertEqual({path: path.read_bytes() for path in source_paths}, before)
                self.fixture.assert_shared_unchanged()

    def test_locked_legacy_backup_rolls_back_settings_and_calibration_before_reload(self):
        native_replace = RuntimePaths.os.replace
        for name, blocked in (('Other drawing app', self.fixture.positions),
                              ('Other drawing app', self.fixture.palette),
                              ('Microsoft Paint', self.paint_legacy)):
            with self.subTest(profile=name, locked=blocked.name):
                app = self.fixture.app(name)
                self.fixture.seed_current(app)
                app.refresh_palette()
                package = self.package(name)
                before = self.fixture.disk_state()
                original_plan = app.plan
                failed = False

                def deny_legacy_backup(source, destination):
                    nonlocal failed
                    if Path(source) == blocked and Path(destination).suffix == '.backup' and not failed:
                        failed = True
                        raise PermissionError('Legacy calibration is locked')
                    return native_replace(source, destination)

                with patch.object(RuntimePaths.os, 'replace', side_effect=deny_legacy_backup):
                    with self.assertRaisesRegex(portability.ProfilePortabilityError, 'previous files were restored'):
                        portability.import_package_into_app(app, package)
                self.assertTrue(failed)
                self.assertEqual(self.fixture.disk_state(), before)
                self.assertTrue(app.palette_ready)
                self.assertIs(app.plan, original_plan)
                app.root.title.assert_not_called()
                self.fixture.assert_shared_unchanged()


if __name__ == '__main__':
    unittest.main()
