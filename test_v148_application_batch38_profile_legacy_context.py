"""Legacy calibration identity follows the sources consumed by the profile.

The real palette reader, context hasher and render-resume checkpoint/resolver
run against private files. These tests create no rasters and send no input.
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
import ProfileStorage as storage
import RenderResume
import test_v148_application_batch37_legacy_palette as palette_fixture


class LegacyCalibrationContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = palette_fixture.LegacyPaletteResetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def context(self, key='generic', **kwargs):
        return storage.calibration_context_fingerprint(key, workflow='Calibrated palette', **kwargs)

    def test_changed_legacy_positions_reject_an_actual_partly_completed_render_checkpoint(self):
        app = self.fixture.app()
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        previous_position = (Colors.allColors[0].x, Colors.allColors[0].y)
        items = [(1, 1), (2, 1)]
        plan = {
            'groups': [items], 'colors': [Colors.allColors[0].RGB], 'fitted': (10, 10), 'count': 2,
            'color_selectors': [{'kind': 'palette', 'palette_index': 0}],
            'options': {'profile_key': 'generic', 'calibration_fingerprint': self.context()},
        }
        checkpoint = RenderResume.checkpoint_after_path(plan, 1, 0, len(items), ordered_items=items)
        path = self.root / 'render-checkpoint.json'
        path.write_text(json.dumps(checkpoint), encoding='utf-8')
        retained = json.loads(path.read_text(encoding='utf-8'))
        self.assertTrue(RenderResume.resolve_resume(plan, retained)['compatible'])
        source = self.fixture.positions.read_text(encoding='utf-8')
        self.fixture.positions.write_text(source.replace('101\n207', '901\n207', 1), encoding='utf-8')
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        self.assertNotEqual((Colors.allColors[0].x, Colors.allColors[0].y), previous_position)
        self.assertEqual(Colors.allColors[0].RGB, plan['colors'][0])
        current = deepcopy(plan)
        current['options']['calibration_fingerprint'] = self.context()
        result = RenderResume.resolve_resume(current, retained)
        self.assertFalse(result['compatible'])
        self.assertEqual(result['reason'], 'final plan fingerprint changed')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), checkpoint)
        self.fixture.assert_shared_unchanged()

    def test_legacy_palette_color_updates_change_the_loaded_context(self):
        app = self.fixture.app()
        app.refresh_palette()
        before = self.context()
        colors = deepcopy(self.fixture.legacy_rgbs)
        colors[0] = [22, 44, 66]
        self.fixture.palette.write_text(json.dumps(colors), encoding='utf-8')
        app.refresh_palette()
        self.assertEqual(Colors.allColors[0].RGB, (22, 44, 66))
        self.assertNotEqual(self.context(), before)
        self.assertEqual(self.context(), self.context(palette_path=self.fixture.current))

    def test_canonical_and_explicit_other_palette_paths_do_not_depend_on_shadowed_legacy(self):
        app = self.fixture.app()
        self.fixture.seed_current(app)
        alternate = self.root / 'chosen-palette.json'
        Colors.save_calibration([(70, 80)], [(9, 8, 7)], alternate, profile_key='generic')
        missing_alternate = self.root / 'missing-explicit-palette.json'
        before = {path: self.context(palette_path=path)
                  for path in (self.fixture.current, alternate, missing_alternate)}
        self.fixture.positions.write_text('unusable shadowed positions', encoding='utf-8')
        self.fixture.palette.write_text('unusable shadowed RGB data', encoding='utf-8')
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        self.assertEqual(Colors.allColors[0].RGB, (21, 22, 23))
        Colors.load_calibration(alternate, profile_key='generic')
        self.assertEqual(Colors.allColors[0].RGB, (9, 8, 7))
        with self.assertRaises(FileNotFoundError):
            Colors.load_calibration(missing_alternate, profile_key='generic')
        self.assertEqual({path: self.context(palette_path=path) for path in before}, before)

    def test_other_builtin_and_custom_contexts_are_independent_of_generic_legacy_sources(self):
        custom = GameProfiles.PROFILES['Legacy reset custom'][0]
        keys = ('microsoft-paint', 'gartic-phone', custom)
        before = {key: self.context(key) for key in keys}
        self.fixture.positions.write_text('changed generic positions', encoding='utf-8')
        self.fixture.palette.write_text('changed generic RGB', encoding='utf-8')
        self.assertEqual({key: self.context(key) for key in keys}, before)
        # Existing Paint-only legacy ownership must still be included.
        (self.root / 'paint-tools.json').write_text('{"version":1,"tools":{}}', encoding='utf-8')
        self.assertNotEqual(self.context('microsoft-paint'), before['microsoft-paint'])
        self.assertEqual({key: self.context(key) for key in keys[1:]}, {key: before[key] for key in keys[1:]})

    def test_legacy_creation_removal_and_canonical_promotion_change_only_the_active_context(self):
        self.fixture.positions.unlink()
        self.fixture.palette.unlink()
        missing = self.context()
        self.fixture.seed_legacy()
        legacy = self.context()
        self.assertNotEqual(legacy, missing)
        self.fixture.palette.unlink()
        positions_only = self.context()
        self.assertNotEqual(positions_only, legacy)
        app = self.fixture.app()
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        self.fixture.seed_current(app)
        canonical = self.context()
        self.assertNotEqual(canonical, positions_only)
        self.fixture.positions.unlink()
        self.assertEqual(self.context(), canonical)
        self.fixture.current.unlink()
        self.assertEqual(self.context(), missing)

    def test_active_legacy_sources_keep_regular_file_byte_and_io_failure_boundaries(self):
        native_open = Path.open
        for source in (self.fixture.positions, self.fixture.palette):
            with self.subTest(source=source.name, failure='permission'):
                def denied(path, *args, **kwargs):
                    if path == source:
                        raise PermissionError('Calibration is temporarily locked')
                    return native_open(path, *args, **kwargs)

                with patch.object(Path, 'open', denied):
                    with self.assertRaisesRegex(ValueError, 'cannot be read'):
                        self.context()
            original = source.read_bytes()
            source.unlink()
            source.mkdir()
            try:
                with self.subTest(source=source.name, failure='directory'):
                    with self.assertRaisesRegex(ValueError, 'not a regular file'):
                        self.context()
            finally:
                source.rmdir()
                source.write_bytes(original)
            with source.open('wb') as stream:
                stream.truncate(storage.MAX_CALIBRATION_CONTEXT_BYTES + 1)
            try:
                with self.subTest(source=source.name, failure='oversized'):
                    with self.assertRaisesRegex(ValueError, 'too large'):
                        self.context()
            finally:
                source.write_bytes(original)
            if hasattr(os, 'mkfifo') and os.name == 'posix':
                source.unlink()
                os.mkfifo(source)
                try:
                    with self.subTest(source=source.name, failure='FIFO'):
                        with self.assertRaisesRegex(ValueError, 'not a regular file'):
                            self.context()
                finally:
                    source.unlink()
                    source.write_bytes(original)

    def test_regular_links_track_content_and_broken_context_links_are_not_missing_files(self):
        source = self.fixture.positions
        target = self.root / 'position-target.txt'
        source.replace(target)
        try:
            source.symlink_to(target.name)
        except (NotImplementedError, OSError) as error:
            if isinstance(error, NotImplementedError) or getattr(error, 'winerror', None) == 1314 or \
                    getattr(error, 'errno', None) in (errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP):
                self.skipTest('This host does not permit the native symlink fixture.')
            raise
        before = self.context()
        target.write_text(target.read_text(encoding='utf-8').replace('101\n207', '901\n207', 1), encoding='utf-8')
        with self.subTest(link='regular legacy'):
            self.assertNotEqual(self.context(), before)
        target.unlink()
        with self.subTest(link='broken legacy'):
            with self.assertRaises(ValueError):
                self.context()
        self.assertTrue(source.is_symlink())
        # Explicit canonical input has the same distinction between absent
        # data and an existing broken source, independent of legacy fallback.
        alternate = self.root / 'explicit-broken.json'
        alternate.symlink_to('absent-palette.json')
        with self.subTest(link='broken explicit palette'):
            with self.assertRaises(ValueError):
                self.context(palette_path=alternate)
        self.assertTrue(alternate.is_symlink())


if __name__ == '__main__':
    unittest.main()
