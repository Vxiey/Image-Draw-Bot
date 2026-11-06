"""Mobile snapshot pixel parity, ownership and retained-memory limits."""
from contextlib import closing
import gc
import threading
import unittest
from unittest.mock import Mock, patch
import weakref

from PIL import Image

import MobilePreview as mobile
import MobilePreviewQueue as queue


class MobileSnapshotTests(unittest.TestCase):
    def image_cases(self):
        size = (128, 96)
        rgb = Image.frombytes('RGB', size, bytes((index * 73 + index // 89) % 256 for index in range(size[0]*size[1]*3)))
        result = [(mode, rgb.convert(mode)) for mode in ('RGB', 'L', 'RGBA', 'LA', 'P', '1', 'CMYK')]
        with closing(rgb.convert('L')) as gray:
            result.extend((mode, gray.convert(mode)) for mode in ('I', 'F'))
        rgba = rgb.convert('RGBA')
        with closing(Image.linear_gradient('L')) as gradient, closing(gradient.resize(size)) as alpha:
            rgba.putalpha(alpha)
        result.append(('fractional-alpha', rgba))
        for mode in ('RGB', 'L', 'P'):
            value = rgb.convert(mode)
            value.info['transparency'] = value.getpixel((0, 0))
            result.append((mode+'-color-key', value))
        rgb.close()
        return result

    def close_snapshots(self, snapshots):
        for image in {id(value): value for value in snapshots.values()}.values():
            image.close()

    def test_reduced_owned_snapshots_preserve_exact_existing_png_across_modes_and_alpha(self):
        cases = self.image_cases()
        try:
            with patch.object(mobile, 'MOBILE_PREVIEW_MAX_DIMENSION', 32):
                for name, source in cases:
                    with self.subTest(mode=name):
                        before = source.tobytes()
                        expected = mobile._image_png_bytes(source)
                        snapshots = queue.capture_snapshots({'preview': source}, maximum=32,
                                                            budget=8_000, current=lambda: True)
                        try:
                            self.assertLessEqual(queue.pixel_bytes(snapshots['preview']), 8_000)
                            self.assertLessEqual(max(snapshots['preview'].size), 32)
                            self.assertEqual(mobile._image_png_bytes(snapshots['preview']), expected)
                            self.assertEqual(source.tobytes(), before)
                        finally:
                            self.close_snapshots(snapshots)
        finally:
            for _, image in cases:
                image.close()

    def test_shared_source_uses_one_snapshot_and_one_png_for_multiple_views(self):
        source = Image.new('RGBA', (40, 30), (20, 50, 80, 120))
        server = mobile.MobilePreviewServer()
        server._server = Mock()
        try:
            encode = mobile._image_png_bytes
            with patch.object(mobile, '_image_png_bytes', wraps=encode) as encoded:
                server.queue_images(original=source, preview=source, safety=source)
                self.assertTrue(server._image_queue.wait_idle(5))
                self.assertEqual(encoded.call_count, 1)
            self.assertIs(server._images['original'], server._images['preview'])
            self.assertIs(server._images['original'], server._images['safety'])
            snapshots = queue.capture_snapshots({'original': source, 'preview': source}, maximum=32,
                                                budget=queue.pixel_bytes(source), current=lambda: True)
            try:
                self.assertIs(snapshots['original'], snapshots['preview'])
                self.assertEqual(snapshots['original'].size, source.size)
            finally:
                self.close_snapshots(snapshots)
        finally:
            server.stop()
            source.close()

    def test_real_32_mib_budget_bounds_both_active_and_pending_requests(self):
        server = mobile.MobilePreviewServer()
        server._server = Mock()
        entered, release = threading.Event(), threading.Event()
        encode = mobile._image_png_bytes
        copy = Image.Image.copy
        owned = []
        # 25 MB + 7.84 MB + 7.84 MB exceeds the actual production budget.
        first = Image.new('RGBA', (2500, 2500), 'red')
        latest = Image.new('RGBA', (2500, 2500), 'blue')
        preview = Image.new('RGB', (1400, 1400), 'green')
        safety = Image.new('RGB', (1400, 1400), 'yellow')

        def blocked(image):
            owned.append(image)
            if len(owned) == 1:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('budget test was not released')
            return encode(image)

        def check_copy(image):
            if image is first or image is latest:
                self.fail('oversized source was copied before reduction')
            return copy(image)

        try:
            with patch.object(mobile, '_image_png_bytes', side_effect=blocked), \
                 patch.object(Image.Image, 'copy', check_copy):
                server.queue_images(original=first, preview=preview, safety=safety)
                self.assertTrue(entered.wait(3))
                server.queue_images(original=latest, preview=preview, safety=safety)
                active, pending = server._image_queue._active, server._image_queue._pending
                self.assertLessEqual(active.snapshot_bytes, queue.SNAPSHOT_BUDGET_BYTES)
                self.assertLessEqual(pending.snapshot_bytes, queue.SNAPSHOT_BUDGET_BYTES)
                self.assertLessEqual(active.snapshot_bytes + pending.snapshot_bytes, 2*queue.SNAPSHOT_BUDGET_BYTES)
                self.assertEqual(active.snapshots['original'].size, (1600, 1600))
                self.assertEqual(pending.snapshots['original'].size, (1600, 1600))
                self.assertEqual(first.size, (2500, 2500))
                release.set()
                self.assertTrue(server._image_queue.wait_idle(5))
            self.assertIsNone(server._image_queue._pending)
            self.assertIsNone(server._image_queue._active)
            for snapshot in owned:
                with self.assertRaises(ValueError):
                    snapshot.getpixel((0, 0))
        finally:
            release.set()
            server.stop()
            server._image_queue.wait_idle(5)
            for image in (first, latest, preview, safety):
                image.close()

    def test_failed_reduction_closes_partial_capture_and_native_resize_result(self):
        small = Image.new('RGB', (10, 10), 'red')
        large = Image.new('RGB', (128, 96), 'blue')
        copy, resize, convert = Image.Image.copy, Image.Image.resize, Image.Image.convert
        owned = []
        retained_error = None

        def record_copy(image):
            result = copy(image)
            owned.append(result)
            return result

        def record_resize(image, *args, **kwargs):
            result = resize(image, *args, **kwargs)
            owned.append(result)
            return result

        def failed_convert(image, *args, **kwargs):
            if any(image is value for value in owned):
                raise OSError('injected reduced-conversion failure')
            return convert(image, *args, **kwargs)

        try:
            with patch.object(Image.Image, 'copy', record_copy), \
                 patch.object(Image.Image, 'resize', record_resize), \
                 patch.object(Image.Image, 'convert', failed_convert):
                try:
                    queue.capture_snapshots({'original': small, 'preview': large}, maximum=32,
                                            budget=8_000, current=lambda: True)
                except OSError as error:
                    retained_error = error
            self.assertIsInstance(retained_error, OSError)
            self.assertGreaterEqual(len(owned), 2)
            for image in owned:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))
            self.assertEqual(small.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(large.getpixel((0, 0)), (0, 0, 255))
        finally:
            for image in owned:
                image.close()
            small.close()
            large.close()

    def test_source_identity_cache_does_not_keep_full_resolution_caller_images_alive(self):
        server = mobile.MobilePreviewServer()
        server._server = Mock()
        source = Image.new('RGB', (40, 30), 'red')
        reference = weakref.ref(source)
        try:
            server.queue_images(preview=source)
            self.assertTrue(server._image_queue.wait_idle(5))
            del source
            gc.collect()
            self.assertIsNone(reference())
            self.assertIsNotNone(server._images['preview'])
            self.assertTrue(server.queue_images())
            self.assertEqual(server._images, dict.fromkeys(queue.VIEW_NAMES))
        finally:
            server.stop()

    def test_stopped_server_neither_copies_nor_encodes_borrowed_sources(self):
        server = mobile.MobilePreviewServer()
        source = Image.new('RGB', (10, 10), 'red')
        try:
            with patch.object(Image.Image, 'copy', side_effect=AssertionError('copy')), \
                 patch.object(mobile, '_image_png_bytes', side_effect=AssertionError('PNG')):
                self.assertFalse(server.queue_images(preview=source))
            self.assertTrue(server._image_queue.wait_idle(0))
        finally:
            source.close()


if __name__ == '__main__':
    unittest.main()
