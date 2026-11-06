"""Public image imports check ICO payload dimensions before eager decoding."""
from contextlib import closing
import base64
from io import BytesIO
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, IcoImagePlugin, PngImagePlugin, features

import ImageImport as imports
import test_v148_platform_batch07_import_redirects as redirects


def png_bytes(size=(32, 32), color='red'):
    with BytesIO() as stream, closing(Image.new('RGBA', size, color)) as image:
        image.save(stream, format='PNG')
        return stream.getvalue()


def icon_bytes(entries):
    """Entries are directory size/depth/colour-count plus actual payload."""
    directory = bytearray(b'\0\0\1\0' + struct.pack('<H', len(entries)))
    offset = 6 + len(entries) * 16
    for size, depth, colors, payload in entries:
        width, height = size
        directory.extend(struct.pack('<BBBBHHII', width % 256, height % 256,
                                     colors, 0, 1, depth, len(payload), offset))
        offset += len(payload)
    return bytes(directory) + b''.join(entry[-1] for entry in entries)


def monochrome_png(width, height):
    """A complete PNG without ever constructing its decoded pixel buffer."""
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind + data)))
    compressor = zlib.compressobj()
    row = b'\0' * (1 + (width + 7) // 8)
    compressed = b''.join(compressor.compress(row) for _ in range(height))
    compressed += compressor.flush()
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 1, 0, 0, 0, 0)) +
            chunk(b'IDAT', compressed) + chunk(b'IEND', b''))


class IconDecoderBudgetTests(unittest.TestCase):
    def read_payload(self, payload, **kwargs):
        with TemporaryDirectory() as folder:
            # Content detection remains independent of the selected extension.
            path = Path(folder) / 'source-image.bin'
            path.write_bytes(payload)
            return imports.read_image(path, **kwargs)

    def test_default_budget_checks_embedded_png_not_the_256_directory_dimensions(self):
        # 25,001,000 pixels exceed the real default limit. The valid one-bit
        # PNG is streamed/compressed; neither fixture nor tested code allocates
        # the large decoded plane. The decoder spy fails before any load.
        payload = monochrome_png(25001, 1000)
        self.assertLess(len(payload), 10_000)
        data = icon_bytes([((256, 256), 1, 2, payload)])
        with patch.object(PngImagePlugin.PngImageFile, 'load',
                          side_effect=AssertionError('pixel decoder was reached')) as decoder:
            with self.assertRaisesRegex(ValueError, '25 megapixels'):
                self.read_payload(data)
        decoder.assert_not_called()

    def test_lower_custom_budget_rejects_a_valid_icon_before_any_pixel_load(self):
        data = icon_bytes([((32, 32), 32, 0, png_bytes())])
        with patch.object(IcoImagePlugin.IcoImageFile, 'load',
                          side_effect=AssertionError('eager icon load')) as decoder:
            with self.assertRaisesRegex(ValueError, 'megapixels'):
                self.read_payload(data, max_source_pixels=100)
        decoder.assert_not_called()

    def test_dib_dimensions_are_checked_before_the_eager_mask_or_pixel_read(self):
        for header_size in (12, 40, 52, 56, 64, 108, 124):
            for top_down in (False, True):
                if top_down and header_size == 12:
                    continue
                with self.subTest(header_size=header_size, top_down=top_down):
                    if header_size == 12:
                        payload = struct.pack('<IHHHH', 12, 64, 128, 1, 32)
                    else:
                        payload = struct.pack('<IIiHH', header_size, 64,
                                              -128 if top_down else 128, 1, 32)
                        payload += bytes(header_size - len(payload))
                    data = icon_bytes([((64, 64), 32, 0, payload)])
                    with patch.object(IcoImagePlugin.IcoImageFile, 'load',
                                      side_effect=AssertionError('eager icon load')) as decoder:
                        with self.assertRaisesRegex(ValueError, 'megapixels'):
                            self.read_payload(data, max_source_pixels=4095)
                    decoder.assert_not_called()

    def test_legitimate_png_and_dib_multisize_icons_keep_exact_decoded_pixels(self):
        for bitmap in (False, True):
            with self.subTest(bitmap=bitmap), BytesIO() as stream:
                with closing(Image.new('RGBA', (64, 64), (41, 82, 123, 170))) as source:
                    source.putpixel((10, 10), (200, 100, 50, 255))
                    options = {'bitmap_format': 'bmp'} if bitmap else {}
                    source.save(stream, format='ICO', sizes=[(16, 16), (32, 32), (64, 64)], **options)
                data = stream.getvalue()
                with closing(Image.open(BytesIO(data))) as expected:
                    with closing(expected.convert('RGBA')) as reference:
                        with closing(self.read_payload(data, max_source_pixels=4096)) as actual:
                            self.assertEqual(actual.size, (64, 64))
                            self.assertEqual(actual.mode, 'RGBA')
                            self.assertEqual(actual.tobytes(), reference.tobytes())
                            self.assertEqual(actual.info['draw_studio_format'], 'ICO')

    def test_entry_selection_keeps_pillow_area_depth_and_stable_tie_order(self):
        entries = [
            ((16, 16), 32, 0, png_bytes((16, 16), 'red')),
            ((32, 32), 0, 3, png_bytes(color='blue')),
            ((32, 32), 8, 0, png_bytes(color='green')),
            ((32, 32), 0, 2, png_bytes(color='yellow')),
            ((32, 32), 1, 0, png_bytes(color='magenta')),
        ]
        for variants in (entries, entries[::-1], entries[:3]):
            data = icon_bytes(variants)
            with self.subTest(order=[entry[1:3] for entry in variants]):
                with closing(Image.open(BytesIO(data))) as reference:
                    with closing(reference.convert('RGBA')) as expected:
                        with closing(self.read_payload(data, max_source_pixels=1024)) as actual:
                            self.assertEqual(actual.size, expected.size)
                            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_only_the_selected_payload_budget_is_relevant(self):
        data = icon_bytes([
            ((16, 16), 32, 0, monochrome_png(25001, 1000)),
            ((32, 32), 32, 0, png_bytes(color='blue')),
        ])
        with closing(self.read_payload(data, max_source_pixels=1024)) as actual:
            self.assertEqual(actual.size, (32, 32))
            self.assertEqual(actual.getpixel((0, 0)), (0, 0, 255, 255))

    def test_directory_scan_observes_stop_and_restores_the_stream(self):
        entries = [((16, 16), 32, 0, png_bytes((16, 16)))] * 200
        class StopStream(BytesIO):
            def read(self, size=-1):
                chunk = super().read(size)
                if self.tell() >= 6 + 64 * 16:
                    self.stopped = True
                return chunk
        with StopStream(icon_bytes(entries)) as stream:
            stream.stopped = False
            with self.assertRaises(InterruptedError):
                imports._preflight_icon_size(stream, 1000, lambda: stream.stopped)
            self.assertEqual(stream.tell(), 0)

    def test_truncated_directory_never_enters_the_eager_decoder(self):
        for data in (b'\0\0\1\0', b'\0\0\1\0\2\0' + bytes(16)):
            with self.subTest(size=len(data)), patch.object(IcoImagePlugin.IcoImageFile, 'load') as decoder:
                with self.assertRaisesRegex(ValueError, 'directory is incomplete'):
                    self.read_payload(data)
                decoder.assert_not_called()


class PublicRasterBoundaryTests(unittest.TestCase):
    EPS = (b'%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n'
           b'%%EndComments\n0 0 moveto 10 10 lineto stroke\nshowpage\n%%EOF\n')

    @staticmethod
    def wmf():
        data = bytearray(44)
        data[:6] = b'\xd7\xcd\xc6\x9a\0\0'
        data[6:16] = struct.pack('<hhhhH', 0, 0, 10, 10, 72)
        data[22:26] = b'\x01\x00\x09\x00'
        return bytes(data)

    def test_eps_and_metafiles_never_reach_a_decoder_or_renderer_from_any_source(self):
        # Misleading suffix/MIME and data-URL labels cannot authorize a
        # document renderer. Real Requests handling uses only an in-process
        # adapter. Every external-renderer boundary is mocked, never executed.
        for label, payload, factory in (
                ('EPS', self.EPS, 'PIL.EpsImagePlugin.EpsImageFile._open'),
                ('WMF', self.wmf(), 'PIL.WmfImagePlugin.WmfStubImageFile._open')):
            for source_kind in ('local', 'data', 'http'):
                with self.subTest(format=label, source=source_kind), TemporaryDirectory() as folder:
                    path = Path(folder) / 'ordinary-image.png'
                    path.write_bytes(payload)
                    source = {'local': path,
                              'data': 'data:image/png;base64,' + base64.b64encode(payload).decode(),
                              'http': 'https://images.invalid/ordinary-image.png'}[source_kind]
                    adapter = redirects.RecordingAdapter(lambda *_: (200, {'Content-Type': 'image/png'}, payload))
                    with redirects.ImageRedirectTests().transport(adapter), \
                            patch(factory, side_effect=AssertionError('document decoder dispatched')) as decoder, \
                            patch('PIL.EpsImagePlugin.Ghostscript',
                                  side_effect=AssertionError('external renderer dispatched')) as renderer:
                        with self.assertRaisesRegex(ValueError, 'Export documents or vector artwork'):
                            imports.read_image(source)
                    decoder.assert_not_called()
                    renderer.assert_not_called()
                    if source_kind == 'http':
                        self.assertEqual(len(adapter.requests), 1)
                        self.assertTrue(adapter.closed)
                        self.assertTrue(adapter.responses[0].raw.closed)

    def assert_raster(self, encoded, *, expected_format=None):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'image-without-a-format-extension.data'
            path.write_bytes(encoded)
            with closing(Image.open(BytesIO(encoded))) as decoded:
                if expected_format is not None:
                    self.assertEqual(decoded.format, expected_format)
                with closing(decoded.convert('RGBA')) as reference:
                    with closing(imports.read_image(path)) as actual:
                        self.assertEqual(actual.size, reference.size)
                        self.assertEqual(actual.tobytes(), reference.tobytes())
                        self.assertEqual(actual.info['draw_studio_format'], decoded.format)

    def test_all_advertised_raster_decoders_preserve_content_identification_and_pixels(self):
        for format_name in ('PNG', 'JPEG', 'WEBP', 'BMP', 'DIB', 'GIF', 'TIFF', 'ICO'):
            with self.subTest(format=format_name), BytesIO() as stream:
                with closing(Image.new('RGB', (32, 32), (40, 80, 120))) as image:
                    image.putpixel((15, 15), (210, 100, 30))
                    image.save(stream, format=format_name)
                self.assert_raster(stream.getvalue(), expected_format=format_name)

    @unittest.skipUnless(features.check('avif'), 'Pillow was built without its optional AVIF codec')
    def test_advertised_avif_remains_a_native_raster_import(self):
        with BytesIO() as stream, closing(Image.new('RGB', (16, 12), (30, 60, 90))) as image:
            image.save(stream, format='AVIF')
            self.assert_raster(stream.getvalue(), expected_format='AVIF')

    def test_apng_and_mpo_still_use_their_normal_first_raster_frame(self):
        for format_name, detected in (('PNG', 'PNG'), ('MPO', 'MPO')):
            with self.subTest(format=format_name), BytesIO() as stream:
                with closing(Image.new('RGB', (16, 12), 'red')) as first, \
                        closing(Image.new('RGB', (16, 12), 'blue')) as second:
                    first.save(stream, format=format_name, save_all=True, append_images=[second])
                with closing(Image.open(BytesIO(stream.getvalue()))) as image:
                    self.assertEqual(image.n_frames, 2)
                self.assert_raster(stream.getvalue(), expected_format=detected)


if __name__ == '__main__':
    unittest.main()
