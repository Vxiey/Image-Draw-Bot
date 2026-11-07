import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import DrawTimeCalibration as timing
import ProfilePortability as portability
import ProfileStorage as storage
import AppTools


class StorageProfilesBatch02Tests(unittest.TestCase):
    def test_paint_copy_preserves_anchored_direct_tools_in_the_generic_schema(self):
        source = {'version': 3, 'tools': {'Fill': [20, 30], 'Eraser': [30, 30], 'Pencil': [40, 30]},
                  'anchor': {'version': 1, 'client_rect': [0, 0, 200, 100]},
                  'brush_menu': [50, 30], 'brush_preset': [60, 30]}
        package = portability.build_package('Microsoft Paint', {}, {'tools': source})
        with tempfile.TemporaryDirectory() as td:
            key = 'custom-' + 'a' * 32
            paths = portability.apply_package_to_paths(package, key, root=Path(td))
            copied = AppTools.load_calibration(key, paths['tools'])
            self.assertEqual(copied['tools'], {'Fill': [20, 30], 'Eraser': [30, 30]})
            self.assertEqual(copied['anchor'], source['anchor'])
            self.assertNotIn('Brush', copied['tools'])
            self.assertEqual(package['calibration']['tools'], source)

    def test_unanchored_legacy_paint_tools_are_not_mislabeled_as_generic_calibration(self):
        package = portability.build_package('Microsoft Paint', {},
                                           {'tools': {'version': 1, 'tools': {'Brush': [40, 50]}}})
        with tempfile.TemporaryDirectory() as td:
            paths = portability.apply_package_to_paths(package, 'custom-' + 'a' * 32, root=Path(td))
            self.assertFalse(paths['tools'].exists())
            self.assertTrue(paths['settings'].exists())

    def test_calibration_fingerprint_is_bounded_and_does_not_equate_unreadable_with_missing(self):
        with tempfile.TemporaryDirectory() as td, patch.object(storage, 'data_dir', return_value=Path(td)):
            missing = storage.calibration_context_fingerprint('test')
            path = storage.profile_palette_file('test')
            path.write_bytes(b'123456789')
            with patch.object(storage, 'MAX_CALIBRATION_CONTEXT_BYTES', 8):
                with self.assertRaisesRegex(ValueError, 'too large'):
                    storage.calibration_context_fingerprint('test')
            self.assertNotEqual(storage.calibration_context_fingerprint('test'), missing)
            original = Path.open
            def denied(target, *args, **kwargs):
                if target == path:
                    raise PermissionError('locked calibration')
                return original(target, *args, **kwargs)
            with patch.object(Path, 'open', denied):
                with self.assertRaisesRegex(ValueError, 'cannot be read'):
                    storage.calibration_context_fingerprint('test')

    def test_profile_reset_cannot_reimport_legacy_timing_on_next_load(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy, current, other = [root / name for name in ('legacy.json', 'timing.json', 'other.json')]
            options = {'profile_key': 'microsoft-paint'}
            old = {'version': 1, 'profiles': {timing._legacy_key(options):
                {'samples': 5, 'ratio_ema': 2, 'mape_ema': .1}}}
            legacy.write_text(json.dumps(old), encoding='utf-8')
            current.write_text(json.dumps(old), encoding='utf-8')
            other.write_text('preserve this other profile', encoding='utf-8')
            app = SimpleNamespace(game=SimpleNamespace(get=lambda: 'Microsoft Paint'))
            with patch.object(portability, 'profile_reset_paths', return_value=(current,)), \
                 patch.object(portability, 'profile_timing_file', return_value=current), \
                 patch.object(portability, '_reload_profile'), \
                 patch.object(timing, 'profile_timing_file', return_value=current), \
                 patch.object(timing, 'FILE', legacy):
                self.assertTrue(timing.correction_for(options)['learned'])
                portability.reset_profile(app)
                self.assertFalse(timing.correction_for(options)['learned'])
                self.assertFalse(timing.correction_for(options)['learned'])
            self.assertEqual(json.loads(current.read_text()), {'version': timing.VERSION, 'profiles': {}})
            self.assertEqual(json.loads(legacy.read_text()), old)
            self.assertEqual(other.read_text(), 'preserve this other profile')


if __name__ == '__main__':
    unittest.main()
