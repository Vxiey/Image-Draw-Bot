"""An accepted import must fit the actual destination's persisted-state reader.

Real portable files, settings/tool/color readers and file-set publication exercise
the boundaries. Only unrelated UI surfaces use the established profile fixture.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

import AppTools
import ExactColorTools
import GameProfiles
import PaintTools
import ProfilePortability as portability
import test_v148_application_batch37_legacy_palette as palette_fixture


class ProfileReaderLimitTests(unittest.TestCase):
    def setUp(self):
        self.fixture = palette_fixture.LegacyPaletteResetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.anchor = {'version': 1, 'client_rect': [0, 0, 200, 100]}

    @staticmethod
    def text(payload):
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def package(self, name, settings=None, calibration=None):
        path = self.root / 'incoming.drawprofile'
        portability.write_profile_file(path, portability.build_package(
            name, settings or {'quality': 'High detail'}, calibration))
        return portability.read_profile_file(path)

    def calibration(self, logical, key):
        if logical == 'exact_colors':
            return {'version': 2, 'profile': key, 'anchor': self.anchor,
                    'controls': {'RedField': [20, 30], 'GreenField': [40, 30], 'BlueField': [60, 30]}}
        if key == 'microsoft-paint':
            return {'version': 3, 'anchor': self.anchor, 'tools': {'Pencil': [20, 30]}}
        return {'version': 1, 'profile': key, 'anchor': self.anchor, 'tools': {'Fill': [20, 30]}}

    @staticmethod
    def load_calibration(logical, key, path):
        if logical == 'exact_colors':
            return ExactColorTools.load(key, path)
        if key == 'microsoft-paint':
            return PaintTools.load_tool_calibration(path)
        return AppTools.load_calibration(key, path)

    def seed_app(self, name):
        app = self.fixture.app(name)
        self.fixture.seed_current(app)
        app.settings_path.write_text('{"settings_schema":2,"quality":"Balanced"}', encoding='utf-8')
        app.refresh_palette()
        return app

    def assert_rejected_without_publication(self, app, package, **kwargs):
        before = self.fixture.disk_state()
        profiles = dict(GameProfiles.PROFILES)
        old_plan = app.plan
        original_package = deepcopy(package)
        with self.assertRaises(portability.ProfilePortabilityError):
            portability.import_package_into_app(app, package, **kwargs)
        self.assertEqual(self.fixture.disk_state(), before)
        self.assertEqual(dict(GameProfiles.PROFILES), profiles)
        self.assertEqual(package, original_package)
        self.assertIs(app.plan, old_plan)
        self.assertTrue(app.palette_ready)
        app.root.title.assert_not_called()
        self.fixture.assert_shared_unchanged()

    def test_settings_that_exceed_actual_reader_budget_do_not_replace_previous_profile(self):
        app = self.seed_app('Other drawing app')
        settings = {'quality': 'High detail', 'canvas_anchor_detection': {
            'first': 'x' * 140000, 'second': 'y' * 140000}}
        package = self.package('Other drawing app', settings=settings)
        candidate = portability.flatten_settings(package['settings'], package['canvas'])
        probe = self.root / 'settings-reader-probe.json'
        probe.write_text(self.text(candidate), encoding='utf-8', newline='')
        reader_app = self.fixture.app()
        reader_app.settings_path = probe
        self.assertGreater(probe.stat().st_size, 256 * 1024)
        self.assertFalse(reader_app.read_settings())
        self.assertEqual(reader_app._settings_protected_path, probe)
        self.assert_rejected_without_publication(app, package)

    def test_calibration_byte_limits_match_paint_generic_and_exact_color_readers(self):
        for name, logical in (('Microsoft Paint', 'tools'), ('Other drawing app', 'tools'),
                              ('Other drawing app', 'exact_colors')):
            with self.subTest(profile=name, document=logical):
                app = self.seed_app(name)
                key = GameProfiles.PROFILES[name][0]
                payload = self.calibration(logical, key)
                path = portability.portable_path_map(key)[logical]
                path.write_text(self.text(payload), encoding='utf-8')
                self.load_calibration(logical, key, path)
                payload['note'] = 'å' * 70000
                package = self.package(name, calibration={logical: payload})
                probe = self.root / 'calibration-reader-probe.json'
                probe.write_text(self.text(payload), encoding='utf-8', newline='')
                self.assertLess(len(self.text(payload)), 128 * 1024)
                self.assertGreater(probe.stat().st_size, 128 * 1024)
                with self.assertRaisesRegex(ValueError, 'file size'):
                    self.load_calibration(logical, key, probe)
                self.assert_rejected_without_publication(app, package)

    def test_paint_value_count_limit_is_checked_even_below_its_byte_limit(self):
        app = self.seed_app('Microsoft Paint')
        payload = self.calibration('tools', 'microsoft-paint')
        payload['unused'] = [None] * 2100
        package = self.package('Microsoft Paint', calibration={'tools': payload})
        probe = self.root / 'paint-reader-probe.json'
        probe.write_text(self.text(payload), encoding='utf-8', newline='')
        self.assertLess(probe.stat().st_size, 128 * 1024)
        with self.assertRaisesRegex(ValueError, 'too many'):
            PaintTools.load_tool_calibration(probe)
        self.assert_rejected_without_publication(app, package)

    def fill_to_bytes(self, payload, limit, *, settings=False):
        payload = deepcopy(payload)
        container = payload.setdefault('canvas_anchor_detection', {}) if settings else payload
        container['note'] = ''
        remaining = limit - len(self.text(payload).encode('utf-8'))
        container['note'] = 'å' * (remaining // 2) + 'x' * (remaining % 2)
        self.assertEqual(len(self.text(payload).encode('utf-8')), limit)
        return payload

    def test_exact_reader_byte_boundaries_keep_unicode_metadata_and_remain_loadable(self):
        for name, logical in (('Microsoft Paint', 'tools'), ('Other drawing app', 'tools'),
                              ('Other drawing app', 'exact_colors'), ('Other drawing app', 'settings')):
            with self.subTest(profile=name, document=logical):
                app = self.seed_app(name)
                key = GameProfiles.PROFILES[name][0]
                if logical == 'settings':
                    payload = self.fill_to_bytes({'settings_schema': 2, 'quality': 'High detail'},
                                                 256 * 1024, settings=True)
                    package = self.package(name, settings=payload)
                else:
                    payload = self.fill_to_bytes(self.calibration(logical, key), 128 * 1024)
                    package = self.package(name, calibration={logical: payload})
                self.assertEqual(portability.import_package_into_app(app, package), name)
                published = portability.portable_path_map(key)[logical]
                self.assertEqual(json.loads(published.read_text(encoding='utf-8')), payload)
                self.assertEqual(published.stat().st_size, (256 if logical == 'settings' else 128) * 1024)
                self.assertEqual(app.quality.get(), 'High detail')
                if logical == 'settings':
                    self.assertTrue(app.read_settings())
                    self.assertEqual(app.canvas_anchor_detection, payload['canvas_anchor_detection'])
                else:
                    self.load_calibration(logical, key, published)

    def test_longer_copy_owner_is_checked_before_registry_or_profile_files_are_published(self):
        app = self.seed_app('Other drawing app')
        payload = self.fill_to_bytes(self.calibration('tools', 'generic'), 128 * 1024)
        package = self.package('Other drawing app', calibration={'tools': payload})
        probe = self.root / 'generic-reader-probe.json'
        probe.write_text(self.text(payload), encoding='utf-8', newline='')
        self.assertEqual(AppTools.load_calibration('generic', probe)['tools'], {'Fill': [20, 30]})
        self.assert_rejected_without_publication(app, package, action='copy', copy_name='Bounded copy')

    def test_paint_copy_checks_the_converted_generic_document_not_unused_source_metadata(self):
        app = self.seed_app('Microsoft Paint')
        payload = self.calibration('tools', 'microsoft-paint')
        payload['tools']['Fill'] = [40, 50]
        payload['note'] = 'x' * 150000
        payload['unused'] = [None] * 2100
        package = self.package('Microsoft Paint', calibration={'tools': payload})
        before = deepcopy(package)
        name = portability.import_package_into_app(app, package, action='copy', copy_name='Paint converted copy')
        key = GameProfiles.PROFILES[name][0]
        path = portability.portable_path_map(key)['tools']
        loaded = AppTools.load_calibration(key, path)
        self.assertEqual(loaded['tools'], {'Fill': [40, 50]})
        self.assertEqual(loaded['anchor'], self.anchor)
        self.assertLess(path.stat().st_size, 128 * 1024)
        self.assertEqual(package, before)


if __name__ == '__main__':
    unittest.main()
