"""The mobile PNG encoder borrows RGBA pixels, using existing repository art.

HTTP transport is outside these tests. The real public queue, detached snapshot,
encoder thread, PNG pipeline and publication/retirement paths still run.
"""
from contextlib import ExitStack, closing
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import MobilePreview as mobile
from ImageImport import read_image


ASSET = Path(__file__).parent / 'assets' / 'image-draw-bot-icon.png'


def previous_png(image):
    """Independent pre-change codec pipeline, retained only as a parity oracle."""
    target = None
    if max(image.size) > mobile.MOBILE_PREVIEW_MAX_DIMENSION:
        ratio = mobile.MOBILE_PREVIEW_MAX_DIMENSION / float(max(image.size))
        target = tuple(max(1, round(axis * ratio)) for axis in image.size)
    with ExitStack() as owned:
        if target is not None and image.mode in ('RGB', 'L') and 'transparency' not in image.info:
            reduced = owned.enter_context(closing(image.resize(target, Image.Resampling.LANCZOS)))
            rgba = owned.enter_context(closing(reduced.convert('RGBA')))
        else:
            rgba = owned.enter_context(closing(image.convert('RGBA')))
            if target is not None:
                rgba = owned.enter_context(closing(rgba.resize(target, Image.Resampling.LANCZOS)))
        background = owned.enter_context(closing(Image.new('RGBA', rgba.size, 'white')))
        background.alpha_composite(rgba)
        flattened = owned.enter_context(closing(background.convert('RGB')))
        with BytesIO() as out:
            flattened.save(out, format='PNG', optimize=True)
            return out.getvalue()


class MobileEncoderTests(unittest.TestCase):
    def source(self):
        image = read_image(ASSET)
        self.addCleanup(image.close)
        return image

    def server(self):
        server = mobile.MobilePreviewServer()
        server._server = Mock()  # Only the unneeded HTTP listener is replaced.
        self.addCleanup(server.stop)
        self.addCleanup(lambda: self.assertTrue(server._image_queue.wait_idle(5)))
        return server

    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_public_queue_keeps_one_detached_snapshot_and_no_inner_rgba_conversion(self):
        source = self.source()
        original_pixels, original_info = source.tobytes(), deepcopy(source.info)
        expected = previous_png(source)
        server = self.server()
        encode, convert = mobile._image_png_bytes, Image.Image.convert
        encoded_sources, rgba_conversions = [], []

        def tracked_encode(image):
            encoded_sources.append((image, threading.get_ident()))
            return encode(image)

        def tracked_convert(image, mode=None, *args, **kwargs):
            if mode == 'RGBA' and any(image is value for value, _thread in encoded_sources):
                rgba_conversions.append(image.width * image.height * 4)
            return convert(image, mode, *args, **kwargs)

        with patch.object(mobile, '_image_png_bytes', tracked_encode), \
                patch.object(Image.Image, 'convert', tracked_convert):
            self.assertTrue(server.queue_images(original=source, preview=source))
            self.assertTrue(server._image_queue.wait_idle(5))
        self.assertEqual(len(encoded_sources), 1)
        snapshot, worker = encoded_sources[0]
        self.assertIsNot(snapshot, source)
        self.assertNotEqual(worker, threading.get_ident())
        self.assertEqual(rgba_conversions, [])
        self.assert_closed(snapshot)
        self.assertEqual(server._images['original'], expected)
        self.assertIs(server._images['original'], server._images['preview'])
        self.assertEqual(source.tobytes(), original_pixels)
        self.assertEqual(source.info, original_info)

    def test_exact_png_parity_for_alpha_modes_metadata_and_both_size_branches(self):
        source = self.source()
        with ExitStack() as owned:
            cases = [(mode, owned.enter_context(closing(source.convert(mode))))
                     for mode in ('RGBA', 'RGB', 'L', 'LA', 'P')]
            for mode in ('RGB', 'L', 'P'):
                keyed = owned.enter_context(closing(source.convert(mode)))
                keyed.info['transparency'] = keyed.getpixel((0, 0))
                cases.append((mode + '-colorkey', keyed))
            for maximum in (128, 1024):
                with patch.object(mobile, 'MOBILE_PREVIEW_MAX_DIMENSION', maximum):
                    for name, image in cases:
                        with self.subTest(mode=name, maximum=maximum):
                            before = image.tobytes(), deepcopy(image.info)
                            self.assertEqual(mobile._image_png_bytes(image), previous_png(image))
                            self.assertEqual((image.tobytes(), image.info), before)
        self.assertIsNone(mobile._image_png_bytes(None))

    def test_compositor_and_png_failures_preserve_borrowed_source_and_close_owned_reduction(self):
        source = self.source()
        pixels, metadata = source.tobytes(), deepcopy(source.info)
        resize = Image.Image.resize
        for maximum in (128, 1024):
            for operation in ('composite', 'save'):
                with self.subTest(maximum=maximum, operation=operation):
                    owned = []
                    error = MemoryError('injected encoder allocation failure')
                    retained = None

                    def tracked_resize(image, *args, **kwargs):
                        result = resize(image, *args, **kwargs)
                        if image is source:
                            owned.append(result)
                        return result

                    target = 'alpha_composite' if operation == 'composite' else 'save'
                    with patch.object(mobile, 'MOBILE_PREVIEW_MAX_DIMENSION', maximum), \
                            patch.object(Image.Image, 'resize', tracked_resize), \
                            patch.object(Image.Image, target, side_effect=error):
                        try:
                            mobile._image_png_bytes(source)
                        except MemoryError as failure:
                            retained = failure
                    self.assertIs(retained, error)  # Keep the actual traceback alive.
                    self.assertEqual(len(owned), int(maximum < max(source.size)))
                    for image in owned:
                        self.assert_closed(image)
                    self.assertEqual(source.tobytes(), pixels)
                    self.assertEqual(source.info, metadata)

    def test_queue_cancellation_during_borrowed_encode_retires_snapshot_without_publication(self):
        source = self.source()
        pixels = source.tobytes()
        server = self.server()
        entered, resume = threading.Event(), threading.Event()
        encode = mobile._image_png_bytes
        snapshots = []

        def blocked(image):
            snapshots.append(image)
            entered.set()
            if not resume.wait(5):
                raise TimeoutError('encoder was not released')
            return encode(image)

        try:
            with patch.object(mobile, '_image_png_bytes', blocked):
                self.assertTrue(server.queue_images(original=source))
                self.assertTrue(entered.wait(3))
                server.cancel_updates()
                resume.set()
                self.assertTrue(server._image_queue.wait_idle(5))
            self.assertEqual(server.state().revision, 0)
            self.assertEqual(server._images, dict.fromkeys(('original', 'preview', 'safety')))
            self.assertEqual(len(snapshots), 1)
            self.assert_closed(snapshots[0])
            self.assertEqual(source.tobytes(), pixels)
        finally:
            resume.set()
            server._image_queue.wait_idle(5)


if __name__ == '__main__':
    unittest.main()
