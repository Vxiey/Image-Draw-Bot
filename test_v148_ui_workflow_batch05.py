"""Drop payload provenance and decoder parity; no network or desktop input."""
from contextlib import closing
from pathlib import Path
import base64
import io
import json
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image

import CanvasDropPayload as drops
import GameProfiles as profiles
from ImageImport import read_image


class DropPayloadTests(unittest.TestCase):
    def test_only_real_image_attributes_can_outrank_the_dragged_image(self):
        wanted = 'https://cdn.example.com/photo.png'
        prefixes = (
            '<script src="https://cdn.example.com/app.js"></script>',
            '<div data-src="https://cdn.example.com/api"></div>',
            '<!-- <img src="https://old.example.com/removed.png"> -->',
            '<style>.a{background:url(https://cdn.example.com/background.png)}</style>',
            '<template><img src="https://cdn.example.com/template.png"></template>',
            '<noscript><img src="https://cdn.example.com/fallback.png"></noscript>',
            '<img not-src="https://cdn.example.com/not-source.png">',
        )
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                raw = prefix + '<img src="' + wanted + '">'
                # Tk list fragments must not reintroduce a script/comment URL.
                result = drops.parse_canvas_drop(raw, split_items=('https://old.example.com/x.png',))
                self.assertEqual(result.source, wanted)

    def test_html_with_only_inert_images_does_not_fall_back_into_its_markup(self):
        for raw in ('<!-- <img src="https://example.com/a.png"> -->',
                    '<script>const a="data:image/png;base64,aGVsbG8="</script>',
                    '<template><img src="https://example.com/a.png"></template>'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'No image'):
                drops.parse_canvas_drop(raw)

    def test_unquoted_html_attributes_decode_entities_once(self):
        raw = '<img src=https://cdn.example.com/a.png?x=1&amp;copy=raw>'
        self.assertEqual(drops.parse_canvas_drop(raw).source,
                         'https://cdn.example.com/a.png?x=1&copy=raw')

    def test_duplicate_html_attribute_uses_the_first_browser_value(self):
        raw = '<img src="https://cdn.example.com/first.png" src="https://cdn.example.com/second.png">'
        self.assertEqual(drops.parse_canvas_drop(raw).source, 'https://cdn.example.com/first.png')

    def test_visible_image_link_is_still_supported_without_an_image_element(self):
        raw = '<a href="https://cdn.example.com/photo.png?a=1&amp;b=2">Photo</a>'
        self.assertEqual(drops.parse_canvas_drop(raw).source,
                         'https://cdn.example.com/photo.png?a=1&b=2')

    def test_uri_list_comments_cannot_become_the_selected_image(self):
        wanted = 'https://cdn.example.com/photo.png'
        raw = '# https://x.test/x.png\r\n\r\n' + wanted + '\r\n'
        items = tk.Tcl().splitlist(raw)
        self.assertEqual(drops.parse_canvas_drop(raw, split_items=items).source, wanted)

    def test_uri_list_supports_multiple_file_uris_without_tcl_splitting(self):
        with tempfile.TemporaryDirectory() as folder:
            unsupported = Path(folder) / 'notes.txt'
            image = Path(folder) / 'my image.png'
            unsupported.write_text('notes')
            image.write_bytes(b'PNG fixture')
            raw = '# dropped files\r\n' + unsupported.as_uri() + '\r\n' + image.as_uri() + '\r\n'
            result = drops.parse_canvas_drop(raw)
            self.assertEqual(result.kind, 'file')
            self.assertEqual(result.source, str(image))

    def test_uri_list_has_the_same_item_bound_as_split_file_drops(self):
        raw = '\n'.join(f'https://example.com/{index}.png' for index in range(4))
        with patch.object(drops, 'MAX_DROP_ITEMS', 3), self.assertRaisesRegex(ValueError, '256'):
            drops.parse_canvas_drop(raw)

    def test_local_tiff_ico_and_apng_drops_reach_the_existing_decoder(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix, format_name in (('.tif', 'TIFF'), ('.tiff', 'TIFF'),
                                        ('.ico', 'ICO'), ('.apng', 'PNG')):
                with self.subTest(suffix=suffix):
                    path = Path(folder) / ('picture' + suffix)
                    with closing(Image.new('RGB', (32, 32), 'red')) as image:
                        image.save(path, format=format_name)
                    source = drops.parse_canvas_drop(str(path), split_items=(str(path),))
                    with closing(read_image(source.source)) as decoded:
                        self.assertEqual(decoded.size, (32, 32))
                        self.assertEqual(decoded.info['draw_studio_format'], format_name)
                    self.assertIn('*' + suffix, drops.IMAGE_FILE_PATTERNS.split())

    def test_inline_image_never_allocates_path_components_or_stats_a_filename(self):
        with io.BytesIO() as stream:
            with closing(Image.new('RGB', (8, 8), 'red')) as image:
                image.save(stream, format='PNG')
            raw = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')
        with patch.object(drops, 'Path', side_effect=AssertionError('URI is not a filename')):
            source = drops.parse_canvas_drop(raw)
        self.assertEqual(source.source, raw)
        with closing(read_image(source.source)) as decoded:
            self.assertEqual(decoded.getpixel((0, 0)), (255, 0, 0, 255))

    def test_inline_token_boundaries_and_case_do_not_hide_invalid_encoded_suffixes(self):
        value = 'DATA:IMAGE/PNG;BASE64,aGVsbG8='
        self.assertEqual(drops.parse_canvas_drop(value).source, value)
        for suffix in ('!', 'K', ')'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                drops.parse_canvas_drop(value+suffix)

    def test_ordinary_image_url_does_not_parse_a_search_engine_query(self):
        raw = 'https://cdn.example.com/photo.png?token=a%2Fb&copy=raw'
        with patch.object(drops, 'parse_qs', side_effect=AssertionError('not a search wrapper')), \
             patch.object(Path, 'is_file', side_effect=AssertionError('URL is not a filename')):
            self.assertEqual(drops.parse_canvas_drop(raw).source, raw)

    def test_only_balanced_drop_wrappers_are_removed(self):
        raw = 'https://cdn.example.com/photo.png?token=value}'
        self.assertEqual(drops.parse_canvas_drop(raw).source, raw)
        self.assertEqual(drops.parse_canvas_drop('{' + raw + '}').source, raw)

    def test_inert_html_nesting_cannot_allocate_an_unbounded_stack(self):
        raw = '<template>' * 257 + '<img src="https://example.com/a.png">' + '</template>' * 257
        with self.assertRaisesRegex(ValueError, 'nested too deeply'):
            drops.parse_canvas_drop(raw)


class ProfileRegistryTests(unittest.TestCase):
    def test_loading_indexes_existing_names_once_and_preserves_first_valid_owner(self):
        calls = []
        class ExistingName(str):
            def casefold(self):
                calls.append(str(self))
                return super().casefold()
        original = dict(profiles.PROFILES)
        existing = {ExistingName(name): value for name, value in original.items()}
        data = {f'Profile {index:04}': f'custom-{index+1:032x}' for index in range(990)}
        data.update({
            'microsoft paint': 'custom-'+'a'*32,
            'Bad\nName': 'custom-'+'b'*32,
            ' First ': 'custom-'+'c'*32,
            'FIRST': 'custom-'+'d'*32,
            'Duplicate owner': 'custom-'+'c'*32,
            'Last': 'custom-'+'e'*32,
        })
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(profiles.PROFILES, existing, clear=True), \
             patch.dict(profiles.PROFILE_UI, dict(profiles.PROFILE_UI), clear=True):
            path = Path(folder) / 'profiles.json'
            path.write_text(json.dumps(data), encoding='utf8')
            profiles.load_custom_profiles(path)
            self.assertEqual(len(calls), len(existing))
            self.assertEqual(profiles.PROFILES['First'][0], 'custom-'+'c'*32)
            self.assertEqual(profiles.PROFILES['Last'][0], 'custom-'+'e'*32)
            self.assertNotIn('FIRST', profiles.PROFILES)
            self.assertNotIn('Duplicate owner', profiles.PROFILES)
            self.assertNotIn('Bad\nName', profiles.PROFILES)
            self.assertEqual(len(profiles.PROFILES), len(original)+992)


if __name__ == '__main__':
    unittest.main()
