"""Image preparation borrows safe inputs and owns unpublished resize results."""
from contextlib import ExitStack, closing, contextmanager
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageOps

import DrawBot
import PixelData
import PreviewDetailEngine
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import (
    comparable_plan, graphic_source, planner_options,
)


def reference_prepare(image, area, detail=9, *, sample_limit=None, max_pixels=None,
                      preview_detail_mode=None, preview_detail_meta=None, cancelled=lambda: False):
    """Original orientation/conversion/geometry; close only oracle-owned images."""
    with closing(ImageOps.exif_transpose(image)) as oriented, \
            closing(oriented.convert('RGBA')) as source:
        width, height = area
        scale = min(width/source.width, height/source.height)
        fitted = source.width*scale, source.height*scale
        samples = 200/(11-detail) if sample_limit is None else max(1.0, float(sample_limit))
        sample_scale = min(samples/max(fitted), 1.0)
        pixel_limit = None
        if max_pixels is not None:
            try:
                pixel_limit = max(1, int(max_pixels))
                sample_scale = min(sample_scale, (pixel_limit/max(1.0, fitted[0]*fitted[1]))**.5, 1.0)
            except (TypeError, ValueError, OverflowError):
                pass
        size = tuple(max(1, round(value*sample_scale)) for value in fitted)
        if pixel_limit is not None and size[0]*size[1] > pixel_limit:
            if size[0] >= size[1]:
                size = max(1, min(size[0], pixel_limit//size[1])), size[1]
            else:
                size = size[0], max(1, min(size[1], pixel_limit//size[0]))
        result = (PreviewDetailEngine.detail_aware_resize(source, size, preview_detail_mode,
                    cancelled=cancelled, metadata=preview_detail_meta) if preview_detail_mode
                  else source.resize(size, Image.Resampling.LANCZOS))
    return result, fitted


def image_state(image):
    return image.mode, image.size, image.tobytes(), dict(image.info), image.getexif().tobytes()


@contextmanager
def observe_owned_boundaries():
    """Keep direct returned buffers alive, not Pillow's internal temporaries."""
    images = []
    def record(function, caller_only=False):
        def wrapped(*args, **kwargs):
            direct = not caller_only or Path(sys._getframe(1).f_code.co_filename).name == 'PixelData.py'
            result = function(*args, **kwargs)
            if direct:
                images.append(result)
            return result
        return wrapped
    with ExitStack() as stack:
        stack.enter_context(patch.object(ImageOps, 'exif_transpose', new=record(ImageOps.exif_transpose)))
        for name in ('convert', 'resize'):
            stack.enter_context(patch.object(Image.Image, name, new=record(getattr(Image.Image, name), True)))
        stack.enter_context(patch.object(PreviewDetailEngine, 'detail_aware_resize',
                                        new=record(PreviewDetailEngine.detail_aware_resize)))
        yield images


def source_copy_count(operation, source_size):
    copied = []
    original = Image.Image.copy
    def record(image, *args, **kwargs):
        result = original(image, *args, **kwargs)
        if image.mode == 'RGBA' and image.size == source_size:
            copied.append(image.width*image.height*4)
        return result
    with patch.object(Image.Image, 'copy', new=record):
        result = operation()
    return {'full_source_rgba_copies': len(copied), 'nominal_copied_pixel_bytes': sum(copied)}, result


class PrepareImageBorrowingTests(unittest.TestCase):
    def assert_closed(self, images, retained=()):
        retained_ids = {id(image) for image in retained}
        for image in images:
            if id(image) not in retained_ids:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))

    def test_pixels_geometry_exif_and_preview_metadata_match_original_pipeline(self):
        rng = np.random.default_rng(1481502)
        pixels = rng.integers(0, 256, (19, 27, 4), dtype=np.uint8)
        pixels.flags.writeable = False
        with closing(Image.fromarray(pixels)) as original:
            for mode in ('RGBA', 'RGB', 'L', 'LA', 'P', 'RGBa'):
                for orientation in (None, 1, 2, 3, 4, 5, 6, 7, 8):
                    with closing(original.convert(mode)) as source:
                        source.info['fixture_marker'] = 'borrowed metadata'
                        if mode == 'P': source.info['transparency'] = bytes(range(256))
                        if mode == 'RGB': source.info['transparency'] = source.getpixel((1, 1))
                        if mode == 'L': source.info['transparency'] = source.getpixel((1, 1))
                        exif = source.getexif(); exif[270] = 'orientation fixture'
                        if orientation is not None: exif[274] = orientation
                        source.info['exif'] = exif.tobytes()
                        before = image_state(source)
                        for preview in (None, 'Fast', 'Detailed', 'Micro detail'):
                            with self.subTest(mode=mode, orientation=orientation, preview=preview):
                                old_meta = {}; new_meta = {}
                                settings = dict(detail=8, sample_limit=21, max_pixels=143,
                                                preview_detail_mode=preview)
                                expected, old_fit = reference_prepare(source, (43, 37),
                                    preview_detail_meta=old_meta, **settings)
                                actual, new_fit = PixelData.prepare_image(source, (43, 37),
                                    preview_detail_meta=new_meta, **settings)
                                with closing(expected), closing(actual):
                                    self.assertEqual(image_state(actual), image_state(expected))
                                    self.assertEqual(new_fit, old_fit)
                                    self.assertEqual(new_meta, old_meta)
                                    self.assertLessEqual(actual.width*actual.height, 143)
                                self.assertEqual(image_state(source), before)

    def test_lazy_decoders_keep_the_same_orientation_and_borrowed_input(self):
        with closing(graphic_source((32, 24))) as source:
            exif = source.getexif(); exif[274] = 6
            for format in ('PNG', 'TIFF'):
                with BytesIO() as encoded:
                    source.save(encoded, format=format, exif=exif.tobytes())
                    payload = encoded.getvalue()
                states = []
                for function in (reference_prepare, PixelData.prepare_image):
                    with BytesIO(payload) as stream, closing(Image.open(stream)) as borrowed:
                        result, fitted = function(borrowed, (40, 30), 10)
                        with closing(result):
                            states.append((image_state(result), fitted))
                        borrowed.getpixel((0, 0))
                        self.assertFalse(stream.closed)
                self.assertEqual(states[0], states[1])

    def test_oriented_rgba_avoids_two_full_source_identity_copies(self):
        with closing(graphic_source((640, 480))) as source:
            counts = []
            for function in (reference_prepare, PixelData.prepare_image):
                count, (result, fitted) = source_copy_count(
                    lambda: function(source, (160, 120), 10), source.size)
                counts.append(count)
                with closing(result):
                    self.assertEqual(result.size, (160, 120))
                    self.assertEqual(fitted, (160.0, 120.0))
            self.assertEqual(counts, [
                {'full_source_rgba_copies': 2, 'nominal_copied_pixel_bytes': 2*640*480*4},
                {'full_source_rgba_copies': 0, 'nominal_copied_pixel_bytes': 0},
            ])

    def test_success_preserves_owned_result_even_when_target_size_is_unchanged(self):
        for mode, orientation in (('RGBA', None), ('RGBA', 6), ('RGB', 8), ('P', 1)):
            with closing(graphic_source((32, 24))) as graphic, closing(graphic.convert(mode)) as source:
                if orientation is not None:
                    source.getexif()[274] = orientation
                    source.info['exif'] = source.getexif().tobytes()
                before = image_state(source)
                area = (24, 32) if orientation in (6, 8) else source.size
                with observe_owned_boundaries() as created:
                    result, _fitted = PixelData.prepare_image(source, area, 10)
                try:
                    self.assertIsNot(result, source)
                    self.assertEqual(result.size, area)
                    self.assert_closed(created, (result,))
                    result.putpixel((0, 0), (12, 34, 56, 78))
                    self.assertEqual(image_state(source), before)
                finally:
                    result.close()

    def test_late_stop_and_failed_resize_close_private_buffers_with_traceback_retained(self):
        for preview, fail in ((None, False), ('Detailed', False), (None, True), ('Fast', True)):
            with closing(graphic_source((32, 24))) as graphic, closing(graphic.convert('RGB')) as source:
                source.getexif()[274] = 6
                source.info['exif'] = source.getexif().tobytes()
                before = image_state(source); stopped = [False]; errors = []
                owner, name = ((Image.Image, 'resize') if preview is None
                               else (PreviewDetailEngine, 'detail_aware_resize'))
                actual_resize = getattr(owner, name)
                def resize(*args, **kwargs):
                    if fail: raise MemoryError('injected resize failure')
                    result = actual_resize(*args, **kwargs)
                    stopped[0] = True
                    return result
                with self.subTest(preview=preview, fail=fail), \
                        patch.object(owner, name, new=resize), observe_owned_boundaries() as created:
                    try:
                        PixelData.prepare_image(source, (16, 12), preview_detail_mode=preview,
                                                cancelled=lambda: stopped[0])
                    except (InterruptedError, MemoryError) as error:
                        errors.append(error)
                    self.assertEqual(len(errors), 1)
                    self.assertIsInstance(errors[0], MemoryError if fail else InterruptedError)
                    self.assert_closed(created)
                self.assertEqual(image_state(source), before)

    def test_stop_after_orientation_cannot_convert_or_close_the_borrowed_source(self):
        with closing(graphic_source((32, 24))) as source:
            source.getexif()[274] = 6
            source.info['exif'] = source.getexif().tobytes()
            before = image_state(source); stopped = [False]; owned = []
            actual = ImageOps.exif_transpose
            def orient(*args, **kwargs):
                result = actual(*args, **kwargs); owned.append(result); stopped[0] = True
                return result
            with patch.object(ImageOps, 'exif_transpose', new=orient), \
                    patch.object(Image.Image, 'convert', side_effect=AssertionError('Stopped before conversion')):
                with self.assertRaises(InterruptedError):
                    PixelData.prepare_image(source, (16, 12), cancelled=lambda: stopped[0])
            self.assert_closed(owned)
            self.assertEqual(image_state(source), before)

    def test_real_public_plan_keeps_every_stable_field_with_two_fewer_source_copies(self):
        with ExitStack() as stack:
            source = stack.enter_context(closing(graphic_source((128, 96))))
            before = image_state(source)
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
            options = planner_options('Standard / pixel'); options['outline'] = False
            results = []; counts = []
            for function in (reference_prepare, PixelData.prepare_image):
                def plan():
                    with patch('DrawBot.prepare_image', new=function):
                        return DrawBot.make_plan(source, (64, 48), dict(options))
                count, result = source_copy_count(plan, source.size)
                stack.callback(close_plan, result, source)
                counts.append(count); results.append(comparable_plan(result))
            self.assertEqual(results[0], results[1])
            self.assertEqual(counts[0]['full_source_rgba_copies']-counts[1]['full_source_rgba_copies'], 2)
            self.assertGreater(results[0]['count'], 0)
            self.assertEqual(image_state(source), before)


if __name__ == '__main__':
    unittest.main()
