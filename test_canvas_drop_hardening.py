"""Regression coverage for malformed drops and URL preservation."""
import unittest
from urllib.parse import quote

from CanvasDropPayload import parse_canvas_drop


class CanvasDropHardeningTests(unittest.TestCase):
    def test_malformed_ipv6_does_not_hide_later_valid_item(self):
        good = 'https://cdn.example.com/image.png'
        source = parse_canvas_drop('', split_items=['https://[', good])
        self.assertEqual(source.source, good)

    def test_malformed_html_image_does_not_hide_later_image(self):
        good = 'https://cdn.example.com/image.png'
        source = parse_canvas_drop('<img src="https://["><img src="' + good + '">')
        self.assertEqual(source.source, good)

    def test_bad_nested_url_does_not_hide_next_candidate(self):
        good = 'https://cdn.example.com/image.png'
        wrapper = 'https://www.google.com/imgres?imgurl=' + quote('https://[', safe='') + '&mediaurl=' + quote(good, safe='')
        self.assertEqual(parse_canvas_drop(wrapper).source, good)

    def test_invalid_http_urls_are_rejected_with_controlled_error(self):
        for value in ('https:///image.png', 'https://[',
                      'https://example.com:abc/image.png',
                      'https://example.com:99999/image.png',
                      'https://example.com/a\x00b.png'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'No image was found'):
                    parse_canvas_drop(value)

    def test_valid_ipv6_is_supported(self):
        value = 'https://[2001:db8::1]/image.png'
        self.assertEqual(parse_canvas_drop(value).source, value)

    def test_search_wrapper_decodes_exactly_once(self):
        value = 'https://cdn.example.com/a%2Fb.png?token=a%26b%2Fc&copy=raw'
        wrapper = 'https://www.google.com/imgres?imgurl=' + quote(value, safe='')
        self.assertEqual(parse_canvas_drop(wrapper).source, value)

    def test_plain_url_does_not_decode_html_entities(self):
        value = 'https://cdn.example.com/image.png?token=a&copy=raw'
        self.assertEqual(parse_canvas_drop(value).source, value)

    def test_url_punctuation_is_preserved(self):
        for suffix in (')', ',', ';'):
            value = 'https://cdn.example.com/image.png?token=signed' + suffix
            with self.subTest(suffix=suffix):
                self.assertEqual(parse_canvas_drop(value).source, value)
                self.assertEqual(parse_canvas_drop('<img src="' + value + '">').source, value)

    def test_html_attribute_entities_are_decoded_exactly_once(self):
        html = '<img src="https://cdn.example.com/image.png?a=1&amp;copy=raw">'
        self.assertEqual(parse_canvas_drop(html).source,
                         'https://cdn.example.com/image.png?a=1&copy=raw')

    def test_first_inline_image_is_returned_unchanged(self):
        value = 'data:image/png;base64,aGVsbG8='
        self.assertEqual(parse_canvas_drop(value + ' data:image/png;base64,bmV4dA==').source, value)


if __name__ == '__main__':
    unittest.main()
