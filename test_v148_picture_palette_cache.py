import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import PictureCustomPaletteLegacy as palette
from ColorMatchingEngine import visible_rgb_image


class PicturePaletteCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.paths = patch.object(palette, 'data_dir', return_value=self.root)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.valid = palette.PicturePalette(
            'a' * 64, 'cal', (20, 10), 8, 'Faithful',
            ((12, 34, 56),), ((12, 34, 56),), (), (.5,))

    def write_payload(self, data):
        path = palette.cache_path('a' * 64, 'cal')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def load(self):
        return palette.load_cached_palette('a' * 64, 'cal', max_colors=8, fidelity='Faithful')

    def test_oversized_or_deep_cache_is_a_miss(self):
        path = self.write_payload(self.valid.as_dict())
        path.write_bytes(b' ' * (palette.MAX_CACHE_BYTES + 1))
        with patch.object(palette.json, 'loads', side_effect=AssertionError('Oversized JSON must not be parsed')):
            self.assertIsNone(self.load())
        path.write_bytes(b'[' * 2000 + b']' * 2000)
        self.assertIsNone(self.load())

    def test_cache_metadata_requires_exact_supported_types(self):
        for key, values in {
            'version': ('3', 3.5, True, float('inf'), []),
            'source_size': ([True, 10], [1.5, 10], ['20', 10], [0, 10], [1]),
            'max_colors': (True, 0, 33, '8', 8.5),
            'fidelity': ('Unknown', [], None),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    data = self.valid.as_dict()
                    data[key] = value
                    self.write_payload(data)
                    self.assertIsNone(self.load())

    def test_cache_cannot_clamp_invalid_rgb_into_a_trusted_color(self):
        for channels in ([256, 34, 56], [-1, 34, 56], [True, 34, 56],
                         [12.5, 34, 56], ['12', 34, 56], [12, 34, 56, 255]):
            data = self.valid.as_dict()
            data['colors'] = data['custom_colors'] = [channels]
            self.write_payload(data)
            self.assertIsNone(self.load(), channels)

    def test_cache_enforces_complete_unique_bounded_color_groups(self):
        variants = []
        data = self.valid.as_dict(); data['colors'] = []; variants.append(data)
        data = self.valid.as_dict(); data['colors'] *= 2; variants.append(data)
        data = self.valid.as_dict(); data['custom_colors'] = [[1, 2, 3]]; variants.append(data)
        data = self.valid.as_dict(); data['palette_colors'] = copy.deepcopy(data['colors']); variants.append(data)
        data = self.valid.as_dict(); data['colors'] = [[i, 0, 0] for i in range(9)]; variants.append(data)
        for data in variants:
            self.write_payload(data)
            self.assertIsNone(self.load())

    def test_cache_coverage_has_matching_length_and_finite_range(self):
        for coverage in ([], [0, 0], [True], ['0.5'], [-.1], [1.1], [float('nan')], [float('inf')]):
            data = self.valid.as_dict(); data['custom_coverages'] = coverage
            self.write_payload(data)
            self.assertIsNone(self.load(), coverage)

    def test_invalid_save_keeps_previous_valid_cache(self):
        path = palette.save_palette(self.valid)
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            palette.save_palette(replace(self.valid, custom_coverages=(float('nan'),)))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.load().colors, self.valid.colors)

    def test_fingerprint_observes_edits_lost_by_thumbnail_resampling(self):
        original = Image.new('RGB', (1024, 1024), (128, 128, 128))
        changed = original.copy(); changed.putpixel((500, 500), (129, 128, 128))
        a = original.copy(); b = changed.copy()
        a.thumbnail((512, 512), Image.Resampling.LANCZOS)
        b.thumbnail((512, 512), Image.Resampling.LANCZOS)
        self.assertEqual(a.tobytes(), b.tobytes(), 'This fixture must exercise the old thumbnail collision')
        self.assertNotEqual(palette.image_fingerprint(original), palette.image_fingerprint(changed))

    def test_streamed_fingerprint_matches_complete_visible_pixels(self):
        source = Image.new('RGBA', (17, 401), (40, 80, 120, 128))
        source.putpixel((4, 300), (200, 0, 100, 255))
        expected = hashlib.sha256(b'17x401|RGB|' + visible_rgb_image(source).tobytes()).hexdigest()
        self.assertEqual(palette.image_fingerprint(source), expected)

    def test_cancelled_cache_hit_never_returns_prepared_palette(self):
        stopped = False
        def load(*args, **kwargs):
            nonlocal stopped
            stopped = True
            return self.valid
        with patch.object(palette, 'load_cached_palette', side_effect=load):
            with self.assertRaises(InterruptedError):
                palette.build_picture_palette(Image.new('RGB', (20, 10)), [(0, 0, 0)],
                                              cancelled=lambda: stopped)
        with patch.object(palette, 'image_fingerprint') as fingerprint:
            with self.assertRaises(InterruptedError):
                palette.build_picture_palette(None, (), cancelled=lambda: True)
            fingerprint.assert_not_called()

    def test_fingerprint_checks_stop_between_strips(self):
        stopped = False
        visible = palette._visible_rgb
        def stop_after_strip(*args):
            nonlocal stopped
            result = visible(*args)
            stopped = True
            return result
        with patch.object(palette, '_visible_rgb', side_effect=stop_after_strip) as convert:
            with self.assertRaises(InterruptedError):
                palette.image_fingerprint(Image.new('RGB', (10, 600)), cancelled=lambda: stopped)
        self.assertEqual(convert.call_count, 1)

    def test_optional_cache_failure_keeps_computed_palette_usable(self):
        with patch.object(palette, 'cache_path', side_effect=PermissionError('Read-only directory')):
            self.assertIsNone(self.load())
        with patch.object(palette, 'load_cached_palette', return_value=None), \
                patch.object(palette, 'save_palette', side_effect=PermissionError('Read-only directory')):
            result = palette.build_picture_palette(
                Image.new('RGB', (20, 10), (12, 34, 56)), [(0, 0, 0), (255, 255, 255)], max_colors=8)
        self.assertEqual(result.colors, ((12, 34, 56),))
        self.assertFalse(result.cache_hit)

    def test_cache_lookup_does_not_create_empty_directories(self):
        self.assertIsNone(self.load())
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
