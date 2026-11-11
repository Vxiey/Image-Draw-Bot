"""A valid GRAY profile also belongs to a one-bit grayscale PNG/clipboard.

All pixel data is converted from existing repository assets. The existing GRAY
ICC fixture supplies only profile metadata; no synthetic raster is constructed.
Public importers, Pillow encoding and LittleCMS transforms remain real.
"""
from contextlib import contextmanager, ExitStack
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageCms

from ClipboardImport import prepare_bitmap
from ImageImport import read_image
import ImageColorManagement as management
from test_v148_application_batch06_color_import import gray_profile


ASSET = Path(__file__).resolve().parent / 'assets' / 'paint-tools-reference.png'
ALPHA_ASSET = ASSET.with_name('image-draw-bot-icon.png')


class MonochromeGrayProfileTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.profile = gray_profile()

    def own(self, image):
        self.addCleanup(image.close)
        return image

    def source(self, mode='1', *, asset=ASSET, tagged=True):
        with Image.open(asset) as existing:
            source = self.own(existing.convert(mode))
        if tagged:
            source.info['icc_profile'] = self.profile
        else:
            source.info.pop('icc_profile', None)
        return source

    @staticmethod
    def pixels(image):
        return image.mode, image.size, image.tobytes()

    def saved(self, source, name='source.png'):
        path = self.directory / name
        options = {}
        if source.mode == '1' and 'transparency' in source.info:
            # PNG stores the raw one-bit sample, while Pillow exposes white as
            # 255 after decoding. Keep the actual file's tRNS value in 0..1.
            options['transparency'] = int(bool(source.info['transparency']))
        source.save(path, **options)
        return path

    def imported(self, operation):
        try:
            return self.own(operation())
        except Exception as failure:
            self.fail(f'The supported grayscale import was rejected: {failure}')

    def assert_borrowed(self, source, pixels, info):
        self.assertEqual(self.pixels(source), pixels)
        self.assertEqual(source.info, info)

    def assert_srgb(self, result):
        profile = ImageCms.ImageCmsProfile(BytesIO(result.info['icc_profile']))
        self.assertEqual(profile.profile.xcolor_space.strip(), 'RGB')
        self.assertEqual(result.info['draw_studio_color_managed'], 'sRGB from embedded ICC')
        self.assertNotIn('transparency', result.info)

    @contextmanager
    def observed_owned_images(self, *, after_l=None):
        images = []
        native_convert, native_channel = Image.Image.convert, Image.Image.getchannel

        def convert(source, *args, **kwargs):
            result = self.own(native_convert(source, *args, **kwargs))
            images.append((f'{source.mode}->{result.mode}', result))
            if source.mode == '1' and result.mode == 'L' and after_l is not None:
                after_l()
            return result

        def channel(source, *args, **kwargs):
            result = self.own(native_channel(source, *args, **kwargs))
            images.append((f'{source.mode} channel {args[0]}', result))
            return result

        with patch.object(Image.Image, 'convert', convert), patch.object(Image.Image, 'getchannel', channel):
            yield images

    def failure_from(self, operation):
        try:
            result = operation()
        except BaseException as failure:
            return failure
        result.close()
        self.fail('The interrupted or failed import unexpectedly returned an image.')

    def assert_closed(self, images):
        self.assertTrue(images)
        for label, image in images:
            with self.subTest(resource=label), self.assertRaises(ValueError):
                image.getpixel((0, 0))

    def test_gray_tagged_monochrome_png_matches_same_l_pixels_and_srgb_roundtrip(self):
        source = self.source()
        before, info = self.pixels(source), dict(source.info)
        self.assertEqual(source.getextrema(), (0, 255))
        luminance = self.own(source.convert('L'))
        expected = self.imported(lambda: read_image(self.saved(luminance, 'reference.png')))
        actual = self.imported(lambda: read_image(self.saved(source)))
        self.assertEqual(self.pixels(actual), self.pixels(expected))
        with actual.getchannel('A') as alpha:
            self.assertEqual(alpha.getextrema(), (255, 255))
        self.assertEqual(actual.info['draw_studio_format'], 'PNG')
        self.assert_srgb(actual)
        again = self.imported(lambda: read_image(self.saved(actual, 'roundtrip.png')))
        self.assertEqual(self.pixels(again), self.pixels(actual))
        self.assert_borrowed(source, before, info)

    def test_public_file_and_clipboard_preserve_both_monochrome_transparency_keys(self):
        for key in (0, 255):
            for route in ('file', 'clipboard'):
                with self.subTest(key=key, route=route):
                    source = self.source()
                    source.info['transparency'] = key
                    before, info = self.pixels(source), dict(source.info)
                    luminance = self.own(source.convert('L'))
                    expected = self.imported(lambda: prepare_bitmap(luminance))
                    if route == 'file':
                        actual = self.imported(lambda: read_image(self.saved(source)))
                    else:
                        actual = self.imported(lambda: prepare_bitmap(source))
                    self.assertEqual(self.pixels(actual), self.pixels(expected))
                    # The independent opacity oracle compares original decoded
                    # black/white samples, before CMS can change any values.
                    with actual.getchannel('A') as alpha:
                        expected_alpha = bytes(
                            0 if source.getpixel((x, y)) == key else 255
                            for y in range(source.height) for x in range(source.width))
                        self.assertEqual(alpha.tobytes(), expected_alpha)
                    self.assert_srgb(actual)
                    self.assert_borrowed(source, before, info)

    def test_stop_after_actual_l_conversion_closes_normalization_and_keeps_borrowed_source(self):
        source = self.source()
        before, info = self.pixels(source), dict(source.info)
        stopped = threading.Event()
        with self.observed_owned_images(after_l=stopped.set) as owned:
            failure = self.failure_from(lambda: prepare_bitmap(source, cancelled=stopped.is_set))
        self.assert_closed(owned)
        self.assert_borrowed(source, before, info)
        self.assertTrue(any(label == '1->L' for label, _ in owned))
        self.assertTrue(stopped.is_set())
        self.assertIsInstance(failure, InterruptedError)

    def test_transform_failure_closes_owned_l_and_colorkey_alpha_without_closing_source(self):
        source = self.source()
        source.info['transparency'] = 0
        before, info = self.pixels(source), dict(source.info)
        primary = ImageCms.PyCMSError('controlled CMS transform failure')

        def fail_transform(*args, **kwargs):
            raise primary

        with self.observed_owned_images() as owned, patch.object(ImageCms, 'profileToProfile', fail_transform):
            failure = self.failure_from(lambda: prepare_bitmap(source))
        self.assert_closed(owned)
        self.assert_borrowed(source, before, info)
        self.assertIsInstance(failure, ValueError)
        self.assertIs(failure.__cause__, primary)
        self.assertTrue(any(label == '1->L' for label, _ in owned))
        self.assertTrue(any(label == 'RGBA channel A' for label, _ in owned))

    def test_stop_after_real_cms_transform_closes_result_and_owned_intermediates(self):
        source = self.source()
        source.info['transparency'] = 255
        before, info = self.pixels(source), dict(source.info)
        stopped = threading.Event()
        outputs = []
        native_transform = ImageCms.profileToProfile

        def transform(*args, **kwargs):
            result = self.own(native_transform(*args, **kwargs))
            outputs.append(result)
            stopped.set()
            return result

        with self.observed_owned_images() as owned, patch.object(ImageCms, 'profileToProfile', transform):
            failure = self.failure_from(lambda: prepare_bitmap(source, cancelled=stopped.is_set))
        self.assert_closed(owned)
        self.assert_borrowed(source, before, info)
        self.assertEqual(len(outputs), 1)
        self.assert_closed([('CMS result', outputs[0])])
        self.assertIsInstance(failure, InterruptedError)

    def test_untagged_monochrome_and_existing_gray_alpha_and_depth_paths_keep_pixels(self):
        source = self.source(tagged=False)
        expected = self.own(source.convert('RGBA'))
        for operation in (lambda: prepare_bitmap(source), lambda: read_image(self.saved(source))):
            actual = self.imported(operation)
            self.assertEqual(self.pixels(actual), self.pixels(expected))
            self.assertNotIn('draw_studio_color_managed', actual.info)
        for mode in ('L', 'LA', 'I;16'):
            with self.subTest(mode=mode):
                if mode == 'I;16':
                    luminance = self.source('L')
                    integer = self.own(luminance.convert('I'))
                    scaled = self.own(integer.point(lambda value: value * 257))
                    sample = self.own(scaled.convert('I;16'))
                    sample.info['icc_profile'] = self.profile
                    expected = self.own(management.srgb_source(luminance))
                else:
                    sample = self.source(mode, asset=ALPHA_ASSET)
                    gray = sample if mode == 'L' else self.own(sample.getchannel('L'))
                    # Ask LittleCMS directly for RGB, then restore the original
                    # alpha independently of the application's RGBA path.
                    rgb = self.own(ImageCms.profileToProfile(gray,
                        ImageCms.ImageCmsProfile(BytesIO(self.profile)),
                        ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')),
                        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, outputMode='RGB'))
                    expected = self.own(rgb.convert('RGBA'))
                    if mode == 'LA':
                        with sample.getchannel('A') as alpha:
                            expected.putalpha(alpha)
                before, info = self.pixels(sample), dict(sample.info)
                for operation in (lambda: prepare_bitmap(sample), lambda: read_image(self.saved(sample))):
                    actual = self.imported(operation)
                    self.assertEqual(self.pixels(actual), self.pixels(expected))
                    self.assert_srgb(actual)
                self.assert_borrowed(sample, before, info)


if __name__ == '__main__':
    unittest.main()
