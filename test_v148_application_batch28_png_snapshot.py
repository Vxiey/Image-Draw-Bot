"""Actual PNG worker reuses its private snapshot without changing export pixels."""
from contextlib import closing, contextmanager
import copy
import unittest
from unittest.mock import patch

from PIL import Image, ImageCms

import BackgroundRemoval
from DrawBot import DrawBotApp
import test_v148_application_batch15_image_worker_cleanup as worker_fixture


def source_image(mode='RGBA', size=(9, 6), orientation=1):
    image = Image.new(mode, size)
    if mode == 'P':
        image.putpalette([255, 255, 255, 220, 30, 50, 15, 180, 60, 20, 50, 210] + [0]*756)
        image.info['transparency'] = bytes((0, 64, 192, 255))
    for y in range(size[1]):
        for x in range(size[0]):
            rgb = ((x*31+y*7) % 256, (x*13+y*37) % 256, (x*43+y*11) % 256)
            value = rgb + ((x*29+y*17) % 256,) if mode == 'RGBA' else (
                rgb if mode == 'RGB' else ((x+2*y) % 4 if mode == 'P' else (x*31+y*19) % 256))
            image.putpixel((x, y), value)
    exif = image.getexif()
    exif[274] = orientation
    exif[315] = 'PNG snapshot fixture'
    image.info['exif'] = exif.tobytes()
    image.info['icc_profile'] = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    image.info['xmp'] = f'<tiff:Orientation>{orientation}</tiff:Orientation><dc:title>fixture</dc:title>'.encode()
    image.info['comment'] = b'borrowed metadata stays unchanged'
    return image


def expected_rgba(image):
    """Independent mode/alpha membership and integer EXIF coordinate oracle."""
    width, height = image.size
    orientation = image.getexif().get(274, 1)
    target_size = (height, width) if orientation in (6, 8) else (width, height)
    pixels = [None] * (target_size[0]*target_size[1])
    palette = image.getpalette() if image.mode == 'P' else None
    for y in range(height):
        for x in range(width):
            value = image.getpixel((x, y))
            if image.mode == 'RGBA': rgba = value
            elif image.mode == 'RGB': rgba = (*value, 255)
            elif image.mode == 'L': rgba = (value, value, value, 255)
            else:
                alpha = image.info['transparency'][value]
                rgba = (*palette[3*value:3*value+3], alpha)
            xx, yy = ((height-1-y, x) if orientation == 6 else
                      (y, width-1-x) if orientation == 8 else
                      (width-1-x, height-1-y) if orientation == 3 else (x, y))
            pixels[yy*target_size[0]+xx] = bytes(rgba)
    return target_size, b''.join(pixels)


def is_open(image):
    try: image.getpixel((0, 0))
    except ValueError: return False
    return True


@contextmanager
def actual_worker(source):
    # Reuse the established real begin_worker/runner fixture without importing
    # its TestCase into this module's discovery or rerunning inherited tests.
    harness = worker_fixture.ImageWorkerCleanupTests()
    harness.setUp()
    try:
        app, old_source, captured, destination = harness.fixture('save_png_copy')
        old_source.close()
        app.original = source
        yield app, destination
    finally:
        harness.doCleanups()


@contextmanager
def observed_images():
    copies, outputs = [], []
    actual_copy, actual_convert = Image.Image.copy, Image.Image.convert
    def copied(image, *args, **kwargs):
        result = actual_copy(image, *args, **kwargs)
        copies.append(dict(mode=image.mode, size=image.size, bytes=image.width*image.height*len(image.getbands())))
        outputs.append(result)
        return result
    def converted(image, *args, **kwargs):
        result = actual_convert(image, *args, **kwargs)
        if result is not image: outputs.append(result)
        return result
    with patch.object(Image.Image, 'copy', new=copied), patch.object(Image.Image, 'convert', new=converted):
        yield copies, outputs


class PngSnapshotTests(unittest.TestCase):
    def enqueue(self, app, destination):
        with patch('DrawBot.filedialog.asksaveasfilename', return_value=str(destination)):
            self.assertTrue(DrawBotApp.save_png_copy(app))

    def assert_saved(self, destination, expected, profile):
        with closing(Image.open(destination)) as saved:
            saved.load()
            self.assertEqual(saved.mode, 'RGBA')
            self.assertEqual(saved.size, expected[0])
            self.assertEqual(saved.tobytes(), expected[1])
            self.assertEqual(saved.info['icc_profile'], profile)
            # The existing encoder call publishes ICC, but does not explicitly
            # pass source EXIF to PNG save. Preserve that established output.
            self.assertEqual(dict(saved.getexif()), {})
            self.assertNotIn('exif', saved.info)

    def test_actual_unrotated_export_copies_source_once_and_keeps_snapshot_pixels(self):
        for mode in ('RGBA', 'RGB', 'L', 'P'):
            with self.subTest(mode=mode), closing(source_image(mode, (64, 48))) as source, actual_worker(source) as (app, destination):
                expected = expected_rgba(source)
                metadata = copy.deepcopy(source.info)
                with observed_images() as (copies, outputs):
                    self.enqueue(app, destination)
                    source.putpixel((0, 0), (1, 2, 3, 4) if mode == 'RGBA' else ((1, 2, 3) if mode == 'RGB' else 1))
                    app.worker.run()
                self.assert_saved(destination, expected, metadata['icc_profile'])
                self.assertTrue(is_open(source))
                self.assertEqual(source.info, metadata)
                self.assertTrue(outputs)
                self.assertTrue(all(not is_open(image) for image in outputs))
                self.assertEqual([kind for kind, _ in worker_fixture.ImageWorkerCleanupTests.events(app)], ['png_saved', 'done'])
                self.assertEqual(len(copies), 1, copies)
                self.assertEqual(sum(row['bytes'] for row in copies), 64*48*len(source.getbands()))

    def test_actual_export_orients_once_and_preserves_alpha_profile_and_source_metadata(self):
        for mode in ('RGBA', 'RGB', 'L', 'P'):
            for orientation in (3, 6, 8):
                with self.subTest(mode=mode, orientation=orientation), closing(source_image(mode, orientation=orientation)) as source, actual_worker(source) as (app, destination):
                    before = source.tobytes(), copy.deepcopy(source.info), source.getexif().tobytes()
                    expected = expected_rgba(source)
                    with observed_images() as (_, outputs):
                        self.enqueue(app, destination)
                        app.worker.run()
                    self.assert_saved(destination, expected, before[1]['icc_profile'])
                    self.assertEqual((source.tobytes(), source.info, source.getexif().tobytes()), before)
                    self.assertTrue(all(not is_open(image) for image in outputs))

    def test_encoding_stop_and_retained_failure_keep_old_file_and_close_private_images(self):
        actual_save = Image.Image.save
        for mode in ('RGBA', 'RGB'):
            for stop in (False, True):
                with self.subTest(mode=mode, stop=stop), closing(source_image(mode, orientation=6)) as source, actual_worker(source) as (app, destination):
                    destination.write_bytes(b'previous complete PNG')
                    existing = set(destination.parent.iterdir())
                    before = source.tobytes(), copy.deepcopy(source.info)
                    error = OSError('controlled failure after actual PNG encoding')
                    def save(image, stream, *args, **kwargs):
                        actual_save(image, stream, *args, **kwargs)
                        if stop: app.stop.set()
                        else: raise error
                    with observed_images() as (_, outputs), patch.object(Image.Image, 'save', new=save):
                        self.enqueue(app, destination)
                        app.worker.run()
                    self.assertEqual(destination.read_bytes(), b'previous complete PNG')
                    self.assertEqual(set(destination.parent.iterdir()), existing)
                    self.assertEqual((source.tobytes(), source.info), before)
                    self.assertTrue(all(not is_open(image) for image in outputs))
                    delivered = worker_fixture.ImageWorkerCleanupTests.events(app)
                    self.assertNotIn('png_saved', [kind for kind, _ in delivered])
                    self.assertEqual(delivered[-1], ('done', 'png-export'))
                    if not stop: self.assertIsNotNone(error.__traceback__)

    def test_public_helper_still_returns_independent_owned_rgba_for_borrowed_inputs(self):
        for mode in ('RGBA', 'RGB', 'L', 'P'):
            for orientation in (1, 6):
                with self.subTest(mode=mode, orientation=orientation), closing(source_image(mode, orientation=orientation)) as source:
                    before = source.tobytes(), copy.deepcopy(source.info), source.getexif().tobytes()
                    expected = expected_rgba(source)
                    ready = BackgroundRemoval.png_export_ready(source)
                    self.assertIsNot(ready, source)
                    with closing(ready):
                        self.assertEqual((ready.size, ready.tobytes()), expected)
                        self.assertEqual(ready.mode, 'RGBA')
                        self.assertEqual(ready.getexif()[315], 'PNG snapshot fixture')
                        self.assertEqual(ready.getexif().get(274), 1 if orientation == 1 else None)
                    self.assertEqual((source.tobytes(), source.info, source.getexif().tobytes()), before)


if __name__ == '__main__':
    unittest.main()
