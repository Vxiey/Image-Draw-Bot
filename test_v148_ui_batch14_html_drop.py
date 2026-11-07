"""Browser HTML drops use the selected fragment and its original URL context."""
from contextlib import closing
import base64
from io import BytesIO
from pathlib import Path
import re
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, features

from CanvasDropPayload import IMAGE_FILE_PATTERNS, parse_canvas_drop
from DrawBot import DrawBotApp
from ImageImport import read_image
import test_canvas_drop_to_draw_v1083 as drop_fixtures


def clipboard_html(fragment, *, source='https://example.test/gallery/page.html',
                   prefix='<html><head></head><body>', suffix='</body></html>\r\n', markers=True):
    """Independent CF_HTML writer: offsets are UTF-8 bytes, as on Windows."""
    template = ('Version:1.0\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n'
                'StartFragment:{:010d}\r\nEndFragment:{:010d}\r\nSourceURL:' + source + '\r\n')
    if markers:
        prefix += '<!--StartFragment-->'
        suffix = '<!--EndFragment-->' + suffix
    start_html = len(template.format(0, 0, 0, 0).encode('utf-8'))
    start = start_html + len(prefix.encode('utf-8'))
    end = start + len(fragment.encode('utf-8'))
    end_html = end + len(suffix.encode('utf-8'))
    return template.format(start_html, end_html, start, end) + prefix + fragment + suffix


class BrowserHtmlDropTests(unittest.TestCase):
    @unittest.skipUnless(features.check('avif'), 'Pillow was built without its optional AVIF codec')
    def test_advertised_avif_format_reaches_the_existing_decoder_from_file_and_browser_drops(self):
        with BytesIO() as encoded, closing(Image.new('RGB', (7, 5), (10, 90, 180))) as image:
            image.save(encoded, 'AVIF')
            raw = encoded.getvalue()
        self.assertIn('*.avif', IMAGE_FILE_PATTERNS.split())
        uri = 'data:image/avif;base64,' + base64.b64encode(raw).decode('ascii')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'Test Image.avif')
            path.write_bytes(raw)
            expected = None
            for payload in (str(path), path.as_uri(), uri, clipboard_html('<img src="' + uri + '">')):
                with self.subTest(source=payload[:40]):
                    parsed = parse_canvas_drop(payload)
                    with closing(read_image(parsed.source)) as decoded:
                        self.assertEqual(decoded.size, (7, 5))
                        self.assertEqual(decoded.info['draw_studio_format'], 'AVIF')
                        if expected is None: expected = decoded.tobytes()
                        self.assertEqual(decoded.tobytes(), expected)

    def test_selected_fragment_wins_over_unselected_context_and_source_page(self):
        wanted = 'https://images.test/selected.png?sig=a%2Fb%26c&copy=raw'
        raw = clipboard_html('<img src="' + wanted.replace('&', '&amp;') + '">',
            prefix='<html><body><p>Åäö — 🎨</p><img src="https://images.test/earlier.png">',
            suffix='<img src="https://images.test/later.png"></body></html>\r\n')
        result = parse_canvas_drop(raw, split_items=('https://images.test/short.png',))
        self.assertEqual((result.source, result.kind), (wanted, 'url'))
        self.assertTrue(raw.endswith('\r\n'))

    def test_relative_image_attributes_use_source_url_and_preserve_signed_escapes(self):
        for relative, expected in (
                ('../images/photo.png?sig=a%2Fb%26c&amp;x=1', 'https://example.test/images/photo.png?sig=a%2Fb%26c&x=1'),
                ('/images/photo.png', 'https://example.test/images/photo.png'),
                ('//cdn.test/image.webp', 'https://cdn.test/image.webp'),
                ('my photo.png', 'https://example.test/gallery/my%20photo.png')):
            with self.subTest(relative=relative):
                raw = clipboard_html('<img src="' + relative + '">')
                self.assertEqual(parse_canvas_drop(raw).source, expected)

    def test_buffered_context_text_or_partial_tags_cannot_enter_the_selected_fragment(self):
        for pending in ('&', '&#', '&#3'):
            prefix = '<html><body>https://outside.test/image.png' + pending
            with self.subTest(pending=pending):
                raw = clipboard_html('<p>No image selected</p>', prefix=prefix, markers=False)
                with self.assertRaisesRegex(ValueError, 'No image'):
                    parse_canvas_drop(raw)
                raw = clipboard_html('<img src="selected.png">', prefix=prefix, markers=False)
                self.assertEqual(parse_canvas_drop(raw).source, 'https://example.test/gallery/selected.png')
        for prefix, fragment in (
                ('<html><body><img src="https://outside.test/', 'image.png"><p>No image selected</p>'),
                ('<html><body><img ', 'src="https://outside.test/image.png"><p>No image selected</p>'),
                ('<html><body><!-- outside ', '<img src="https://outside.test/image.png"> -->')):
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, 'HTML'):
                parse_canvas_drop(clipboard_html(fragment, prefix=prefix, markers=False))
        for prefix in ('<html><body><script>https://outside.test/image.png&',
                       '<html><body><template>https://outside.test/image.png&'):
            with self.subTest(inert=prefix), self.assertRaisesRegex(ValueError, 'No image'):
                parse_canvas_drop(clipboard_html('<img src="https://outside.test/image.png">',
                                                prefix=prefix, markers=False))

    def test_context_base_and_first_html_base_resolve_without_exposing_inert_sources(self):
        cases = (
            ('<head><base href="https://cdn.test/album/"></head><body>', 'https://cdn.test/album/photo.png'),
            ('<head><base href="/images/"></head><body>', 'https://example.test/images/photo.png'),
            ('<head><base target="_blank"><base href="https://one.test/"><base href="https://two.test/"></head><body>',
             'https://one.test/photo.png'),
            ('<head><template><base href="https://ignored.test/"></template></head><body>',
             'https://example.test/gallery/photo.png'),
            ('<head><!-- <base href="https://ignored.test/"> --></head><body>',
             'https://example.test/gallery/photo.png'),
        )
        for prefix, expected in cases:
            with self.subTest(prefix=prefix):
                self.assertEqual(parse_canvas_drop(clipboard_html('<img src="photo.png">', prefix=prefix)).source, expected)
        ordinary = '<head><base href="https://cdn.test/album/"></head><img src="photo.png">'
        self.assertEqual(parse_canvas_drop(ordinary).source, 'https://cdn.test/album/photo.png')

    def test_relative_image_link_and_inline_image_follow_the_same_selected_fragment(self):
        raw = clipboard_html('<a href="../image.png?x=1&amp;y=2">Image</a>')
        self.assertEqual(parse_canvas_drop(raw).source, 'https://example.test/image.png?x=1&y=2')
        with BytesIO() as encoded, closing(Image.new('RGB', (3, 2), 'red')) as image:
            image.save(encoded, 'PNG')
            uri = 'data:image/png;base64,' + base64.b64encode(encoded.getvalue()).decode('ascii')
        raw = clipboard_html('<img src="' + uri + '">',
            prefix='<html><body><img src="https://example.test/wrong.png">')
        source = parse_canvas_drop(raw)
        self.assertEqual((source.kind, source.source), ('data', uri))
        with closing(read_image(source.source)) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

    def test_empty_inert_or_unresolvable_fragment_never_imports_metadata_or_outside_images(self):
        for fragment in ('', '<p>No image selected</p>',
                         '<template><img src="https://selected.test/inert.png"></template>',
                         '<img src="javascript:alert(1)">'):
            with self.subTest(fragment=fragment), self.assertRaisesRegex(ValueError, 'No image'):
                parse_canvas_drop(clipboard_html(fragment,
                    prefix='<html><body><img src="https://example.test/outside.png">'))
        for source in ('file:///C:/page.html', 'https://example.test:bad/page.html', ''):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'No image'):
                parse_canvas_drop(clipboard_html('<img src="relative.png">', source=source))
        with self.assertRaisesRegex(ValueError, 'No image'):
            parse_canvas_drop('<img src="relative.png">')

    def test_invalid_offsets_fail_before_any_metadata_fallback(self):
        raw = clipboard_html('<img src="../image.png">', prefix='<html><body>å')
        cases = (
            re.sub(r'StartFragment:[0-9]+', 'StartFragment:0000000000', raw),
            re.sub(r'EndFragment:[0-9]+', 'EndFragment:9999999999', raw),
            re.sub(r'StartHTML:[0-9]+', 'StartHTML:0000000000', raw),
            raw.replace('Version:1.0', 'Version:2.0'),
            raw.replace('StartHTML:', 'StartHTML:not-a-number', 1),
            raw.replace('SourceURL:', 'Version:1.0\r\nSourceURL:', 1),
        )
        for broken in cases:
            with self.subTest(header=broken[:100]), self.assertRaisesRegex(ValueError, 'HTML'):
                parse_canvas_drop(broken)
        split_unicode = raw.encode('utf-8').index('å'.encode('utf-8')) + 1
        broken = re.sub(r'StartFragment:[0-9]+', f'StartFragment:{split_unicode:010d}', raw)
        with self.assertRaisesRegex(ValueError, 'offsets'):
            parse_canvas_drop(broken)

    def test_actual_window_drop_imports_only_the_selected_image_through_public_decoder(self):
        wanted = 'https://example.test/images/chosen.png?token=a%2Fb'
        raw = clipboard_html('<img src="../images/chosen.png?token=a%2Fb">',
            prefix='<html><body><img src="https://example.test/unselected.png">')
        app, _loaded = drop_fixtures.CanvasDropToDrawV1083Tests().make_app('unused')
        previous_tk = app.root.tk
        app.root.tk = tk.Tcl()
        try:
            loaded = []
            def load(source, label, action=None):
                with closing(read_image(source)) as decoded:
                    loaded.append((source, label, action, decoded.size, decoded.getpixel((0, 0))))
                return True
            app.load_source = load
            def download(stream, url, limit, cancelled):
                self.assertEqual(url, wanted)
                self.assertFalse(cancelled())
                with closing(Image.new('RGB', (7, 5), (10, 90, 180))) as image:
                    image.save(stream, 'PNG')
            with patch('ImageImport._download', side_effect=download) as transfer, \
                    patch.object(DrawBotApp, '_manual_drop_in_armed', return_value=False), \
                    patch.object(DrawBotApp, 'draw') as draw:
                self.assertEqual(DrawBotApp.drop_image(app, SimpleNamespace(data=raw)), 'copy')
            transfer.assert_called_once()
            draw.assert_not_called()
            self.assertEqual(loaded, [(wanted, 'Dropped web image', None, (7, 5), (10, 90, 180, 255))])
        finally:
            # Retained Mock calls or an assertion traceback may keep this fake
            # root alive. Its borrowed interpreter belongs to this test thread.
            app.root.tk = previous_tk


if __name__ == '__main__':
    unittest.main()
