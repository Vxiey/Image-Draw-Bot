"""Displayed exact color names and aliases must parse back to that same RGB."""
from contextlib import closing
import unittest

from PIL import Image

from Colors import normalize_rgb
from NamedColorData import CSS4_COLORS, X11_TK_COLORS
from NamedColorIntelligence import aliases_for_rgb, nearest_named_color, resolve_named_color


class NamedColorRoundTripTests(unittest.TestCase):
    def test_every_exact_color_name_and_published_alias_round_trips(self):
        # Enumerate the independent source data, not the implementation's
        # canonical table; this includes collisions absent from CSS itself.
        colors = {tuple(rgb) for _name, rgb in (*CSS4_COLORS, *X11_TK_COLORS)}
        for rgb in sorted(colors):
            with self.subTest(rgb=rgb):
                info = nearest_named_color(rgb)
                self.assertTrue(info['exact'])
                self.assertEqual(info['rgb'], rgb)
                self.assertEqual(normalize_rgb(info['name']), rgb)
                self.assertTrue(info['aliases'])
                for name in info['aliases']:
                    self.assertEqual(resolve_named_color(name), rgb, (rgb, name))

    def test_css_names_keep_precedence_and_x11_collisions_are_explicit(self):
        for name, rgb in CSS4_COLORS:
            with self.subTest(name=name):
                self.assertEqual(resolve_named_color(name), tuple(rgb))
        for name, rgb in (('Gray', (190, 190, 190)), ('Green', (0, 255, 0)),
                          ('Maroon', (176, 48, 96)), ('Purple', (160, 32, 240))):
            with self.subTest(name=name):
                self.assertEqual(normalize_rgb('X11 ' + name), rgb)
                self.assertEqual(normalize_rgb('x11_' + name.lower()), rgb)
                self.assertNotEqual(resolve_named_color(name), rgb)
                self.assertNotIn(name.casefold(), {alias.casefold() for alias in aliases_for_rgb(rgb)})
        self.assertEqual(nearest_named_color((190, 190, 190))['name'], 'X11 Gray')
        self.assertEqual(nearest_named_color((176, 48, 96))['name'], 'X11 Maroon')
        self.assertEqual(nearest_named_color((160, 32, 240))['name'], 'X11 Purple')

    def test_exact_extended_matches_report_the_vocabulary_they_actually_used(self):
        self.assertEqual(nearest_named_color((190, 190, 190))['vocabulary'], 'extended-tk-x11')
        self.assertEqual(nearest_named_color((128, 128, 128))['vocabulary'], 'css4')
        self.assertEqual(nearest_named_color((176, 48, 96))['vocabulary'], 'extended-tk-x11')
        self.assertEqual(nearest_named_color((26, 141, 249))['vocabulary'], 'css4')

    def test_real_dynamic_mapping_distinguishes_x11_source_from_css_target(self):
        from DynamicColors import build_dynamic_color_strokes
        for source, target, name in (((190, 190, 190), (128, 128, 128), 'Gray'),
                                    ((176, 48, 96), (128, 0, 0), 'Maroon'),
                                    ((160, 32, 240), (128, 0, 128), 'Purple')):
            with self.subTest(name=name), closing(Image.new('RGB', (6, 2), source)) as image:
                groups, colors, selectors, metadata = build_dynamic_color_strokes(
                    image, (target,), max_colors=1, skip_white=False, exact_available=False)
            mapping = metadata['named_color_mappings'][0]
            self.assertEqual(mapping['source_name'], 'X11 ' + name)
            self.assertEqual(mapping['mapped_name'], name)
            self.assertGreater(mapping['delta_e_oklab'], 15)
            self.assertEqual(colors, (target,))
            self.assertEqual(groups, [[(0, 0, 5, 0), (0, 1, 5, 1)]])
            self.assertEqual(selectors[0]['kind'], 'palette')


if __name__ == '__main__':
    unittest.main()
