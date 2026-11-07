import json
import tempfile
import unittest
from pathlib import Path

from ProfilePortability import (
    FORMAT_ID, SCHEMA_VERSION, MACHINE_STATE_EXCLUDED, ProfilePortabilityError,
    apply_package_to_paths, build_package, flatten_settings, migrate_package,
    portable_path_map, read_profile_file, sanitize_settings, split_settings,
    unique_copy_name, validate_package, write_profile_file,
)


class Step27ProfilePortabilityTests(unittest.TestCase):
    def basic_settings(self):
        return {
            'settings_schema': 2,
            'quality': 'High detail',
            'mode': 'Shape paths',
            'color_rendering': 'Perceptual match',
            'gpu_mode': 'Auto',
            'gpu_vram': '4 GB',
            'cpu_workers': '8',
            'ram_budget': '8 GB',
            'planning_resolution': 'High',
            'resource_scheduler': 'Auto',
            'corners': [[100, 120], [900, 620]],
            'canvas_anchor_detection': {'version': 1, 'confidence': 0.9},
            'profile_extras': {'ui_mode': 'Advanced'},
        }

    def palette(self, profile='microsoft-paint'):
        return {
            'version': 4,
            'profile': profile,
            'state': 'calibrated',
            'colors': [
                {'name': 'Black', 'position': [10, 20], 'rgb': [0, 0, 0]},
                {'name': 'White', 'position': [30, 20], 'rgb': [255, 255, 255]},
            ],
        }

    def test_package_separates_renderer_resources_canvas_and_ui(self):
        package = build_package('Microsoft Paint', self.basic_settings(), {'palette': self.palette()})
        self.assertEqual(package['format'], FORMAT_ID)
        self.assertEqual(package['schema_version'], SCHEMA_VERSION)
        self.assertEqual(package['profile']['key'], 'microsoft-paint')
        self.assertEqual(package['settings']['resources']['cpu_workers'], '8')
        self.assertEqual(package['settings']['renderer']['mode'], 'Shape paths')
        self.assertEqual(package['settings']['ui']['profile_extras']['ui_mode'], 'Advanced')
        self.assertEqual(package['canvas']['corners'][1], [900, 620])
        self.assertTrue(package['safety']['requires_reverification'])
        self.assertFalse(package['safety']['machine_specific_state_included'])

    def test_flatten_round_trip_restores_resource_and_canvas_settings(self):
        package = build_package('Microsoft Paint', self.basic_settings(), {'palette': self.palette()})
        flat = flatten_settings(package['settings'], package['canvas'])
        self.assertEqual(flat['cpu_workers'], '8')
        self.assertEqual(flat['quality'], 'High detail')
        self.assertEqual(flat['corners'], [[100, 120], [900, 620]])

    def test_runtime_authorization_is_never_portable(self):
        data = self.basic_settings()
        data.update({'auto_draw': True, 'full_draw_armed': True, 'target_handle': 1234})
        clean = sanitize_settings(data, strict=False)
        self.assertNotIn('auto_draw', clean)
        self.assertNotIn('full_draw_armed', clean)
        self.assertNotIn('target_handle', clean)

    def test_unknown_settings_are_rejected_before_import(self):
        with self.assertRaises(ProfilePortabilityError):
            sanitize_settings({'quality': 'Balanced', 'totally_unknown_setting': 'x'})

    def test_schema_zero_migrates_to_current_schema(self):
        old = {
            'name': 'Microsoft Paint', 'profile_key': 'microsoft-paint',
            'renderer_settings': {'quality': 'Balanced'},
            'resource_limits': {'cpu_workers': '4'},
            'canvas': {'corners': [[1, 2], [101, 202]]},
            'palette': self.palette(),
        }
        migrated = validate_package(migrate_package(old))
        self.assertEqual(migrated['schema_version'], SCHEMA_VERSION)
        self.assertEqual(migrated['settings']['resources']['cpu_workers'], '4')
        self.assertEqual(migrated['calibration']['palette']['profile'], 'microsoft-paint')

    def test_future_schema_is_rejected(self):
        with self.assertRaises(ProfilePortabilityError):
            validate_package({'format': FORMAT_ID, 'schema_version': SCHEMA_VERSION + 1})

    def test_palette_cross_profile_owner_is_rejected(self):
        with self.assertRaises(ProfilePortabilityError):
            build_package('Microsoft Paint', self.basic_settings(), {'palette': self.palette('gartic-phone')})

    def test_apply_as_copy_rewrites_calibration_owner_and_isolates_files(self):
        package = build_package('Microsoft Paint', self.basic_settings(), {
            'palette': self.palette(),
            'tools': {'version': 2, 'profile': 'microsoft-paint', 'tools': {},
                      'anchor': {'version': 1, 'client_rect': [0, 0, 200, 100]}},
        })
        destination = 'custom-' + ('a' * 32)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = apply_package_to_paths(package, destination, root=root)
            settings = json.loads(paths['settings'].read_text(encoding='utf-8'))
            palette = json.loads(paths['palette'].read_text(encoding='utf-8'))
            tools = json.loads(paths['tools'].read_text(encoding='utf-8'))
            self.assertEqual(settings['cpu_workers'], '8')
            self.assertEqual(palette['profile'], destination)
            self.assertEqual(tools['profile'], destination)
            self.assertIn(destination, paths['settings'].name)
            self.assertNotEqual(paths['settings'], portable_path_map('microsoft-paint', root)['settings'])

    def test_write_and_read_drawprofile_round_trip(self):
        package = build_package('Microsoft Paint', self.basic_settings(), {'palette': self.palette()})
        with tempfile.TemporaryDirectory() as td:
            path = write_profile_file(Path(td) / 'paint.drawprofile', package)
            loaded = read_profile_file(path)
            self.assertEqual(loaded['profile'], package['profile'])
            self.assertEqual(loaded['settings']['resources'], package['settings']['resources'])
            self.assertEqual(loaded['canvas'], package['canvas'])

    def test_import_copy_name_is_deterministic_and_unique(self):
        name = unique_copy_name('Microsoft Paint', {'Microsoft Paint', 'Microsoft Paint (Imported)'})
        self.assertEqual(name, 'Microsoft Paint (Imported 2)')

    def test_machine_specific_learning_is_explicitly_excluded(self):
        package = build_package('Microsoft Paint', self.basic_settings(), {'palette': self.palette()})
        excluded = package['safety']['excluded_state']
        self.assertEqual(tuple(excluded), MACHINE_STATE_EXCLUDED)
        joined = ' '.join(excluded).lower()
        self.assertIn('hardware', joined)
        self.assertIn('timing', joined)
        self.assertIn('target window', joined)

    def test_builtin_name_cannot_claim_another_target_key(self):
        package = build_package('Microsoft Paint', self.basic_settings(), {'palette': self.palette()})
        package['profile']['key'] = 'gartic-phone'
        package['calibration']['palette']['profile'] = 'gartic-phone'
        with self.assertRaises(ProfilePortabilityError):
            validate_package(package)

    def test_invalid_tool_calibration_is_rejected(self):
        with self.assertRaises(ProfilePortabilityError):
            build_package('Microsoft Paint', self.basic_settings(), {
                'palette': self.palette(), 'tools': {'version': 99, 'tools': {}}
            })

    def test_invalid_exact_color_calibration_is_rejected(self):
        with self.assertRaises(ProfilePortabilityError):
            build_package('Microsoft Paint', self.basic_settings(), {
                'palette': self.palette(), 'exact_colors': {'version': 99, 'profile': 'microsoft-paint'}
            })

    def test_invalid_canvas_is_rejected(self):
        data = self.basic_settings()
        data['corners'] = [[1.5, 2], [100, 200]]
        with self.assertRaises(ProfilePortabilityError):
            build_package('Microsoft Paint', data, {'palette': self.palette()})


if __name__ == '__main__':
    unittest.main()
