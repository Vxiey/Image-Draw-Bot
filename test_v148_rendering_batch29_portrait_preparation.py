"""Portrait borrows oriented sources while preserving pixels and owned exits."""
from contextlib import ExitStack, closing, contextmanager
import copy
from dataclasses import asdict, is_dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageOps

import Colors
import DrawBot
import ImageImport
import PixelData
import PortraitPlanner as portrait
import test_v148_ui_batch07_renderer as ui_fixture
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS


def image_state(image):
    return image.mode, image.size, image.tobytes(), dict(image.info), image.getexif().tobytes()


def fingerprint(value, path=()):
    if is_dataclass(value):
        return fingerprint(asdict(value), path)
    if isinstance(value, Image.Image):
        return (value.mode, value.size, hashlib.sha256(value.tobytes()).hexdigest(),
                fingerprint(dict(value.info), path), value.getexif().tobytes())
    if isinstance(value, np.ndarray):
        return str(value.dtype), value.shape, hashlib.sha256(value.tobytes()).hexdigest()
    if isinstance(value, dict):
        return {key: fingerprint(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (tuple, list)):
        return [fingerprint(item, path) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def close_images(value, borrowed=(), seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen or any(value is image for image in borrowed):
        return
    seen.add(id(value))
    if isinstance(value, Image.Image):
        value.close()
    elif isinstance(value, dict):
        for item in value.values(): close_images(item, borrowed, seen)
    elif isinstance(value, (tuple, list)):
        for item in value: close_images(item, borrowed, seen)


def source_image(mode='RGBA', size=(73, 55), orientation=None, *, opaque=False):
    y, x = np.indices((size[1], size[0]))
    pixels = np.empty((size[1], size[0], 4), dtype=np.uint8)
    pixels[..., 0] = (x * 11 + y * 3) % 256
    pixels[..., 1] = (x * 5 + y * 7) % 256
    pixels[..., 2] = (x * 2 + y * 13) % 256
    pixels[..., 3] = (255 if opaque else
        np.array([0, 1, 127, 128, 254, 255], dtype=np.uint8)[(x + y) % 6])
    base = Image.fromarray(pixels)
    image = base
    if mode != 'RGBA':
        image = base.convert(mode)
        base.close()
    if mode in ('RGB', 'L'): image.info['transparency'] = image.getpixel((1, 1))
    if mode == 'P': image.info['transparency'] = bytes(range(256))
    image.info['fixture_marker'] = 'borrowed portrait source'
    exif = image.getexif(); exif[270] = 'Portrait preparation source'
    if orientation is not None: exif[274] = orientation
    image.info['exif'] = exif.tobytes()
    return image


def normalized_reference(source, *args, **kwargs):
    """Original Pillow normalization, then the unchanged downstream planner.

    The separate historical verifier also compares the complete published
    Portrait module. This control independently checks the changed input
    boundary without duplicating its conditionals or grayscale arithmetic.
    """
    with closing(ImageOps.exif_transpose(source)) as oriented, \
            closing(oriented.convert('RGBA')) as normalized:
        return portrait.prepare_portrait_image(normalized, *args, **kwargs)


@contextmanager
def planner_fixture(style='Portrait / shaded', quality='Balanced'):
    old_palette = list(Colors.allColors)
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        directory = Path(directory)
        for name in ('source_dir', 'data_dir'):
            stack.enter_context(patch('RuntimePaths.' + name, return_value=directory))
        stack.enter_context(patch.object(DrawBot, 'log_event', new=lambda *_a, **_k: None))
        stack.enter_context(patch.object(DrawBot, 'custom_rgb_available', return_value=False))
        stack.enter_context(patch('ResourceAllocation.available_ram_mb', return_value=8192))
        calibration = directory / 'palette.json'
        calibration.write_text(json.dumps({'version': 4, 'profile': 'microsoft-paint', 'state': 'calibrated',
            'colors': [{'name': 'Black', 'position': [-400, -100], 'rgb': [0, 0, 0]},
                       {'name': 'White', 'position': [-390, -100], 'rgb': [255, 255, 255]}]}))
        Colors.load_calibration(calibration, profile_key='microsoft-paint')
        def restore_palette():
            Colors.allColors[:] = old_palette
            PixelData.closest_color.cache_clear()
        stack.callback(restore_palette)
        app = ui_fixture.AdvertisedRendererTests().app()
        try:
            app.render_style.set(style)
            app.paint_simple.set(True)
            app.outline.set(False)
            app.portrait_focus.set(True)
            app.draw_quality.set(quality)
            app.time_budget_mode = ui_fixture.Value('Unlimited / Accuracy')
            options = DrawBot.DrawBotApp.options(app)
        finally:
            vars(app).clear()
        options.update(available_ram_mb=8192, logical_cpus=4, ram_budget_mb=2048,
                       cpu_workers_resolved=1)
        assert options['paint_current_color'] and not options['outline']
        yield directory, options


@contextmanager
def owned_images():
    images = []
    real = portrait._OwnedImages.own
    def capture(owner, image):
        if image is not owner.original:
            images.append(image)
        return real(owner, image)
    with patch.object(portrait._OwnedImages, 'own', new=capture):
        yield images


def retained_pixel_access(error):
    values = []
    tb = error.__traceback__
    while tb is not None:
        for key, value in tuple(tb.tb_frame.f_locals.items()):
            if type(value).__name__ == 'PixelAccess':
                values.append((Path(tb.tb_frame.f_code.co_filename).name,
                               tb.tb_frame.f_code.co_name, key, value))
        tb = tb.tb_next
    return values


class PortraitPreparationTests(unittest.TestCase):
    def assert_closed(self, images, keep=()):
        for image in images:
            if any(image is retained for retained in keep): continue
            with self.assertRaises(ValueError): image.getpixel((0, 0))

    def test_real_imported_current_ink_plans_avoid_the_two_full_source_copies(self):
        for style, quality, opaque in (('Auto', 'Balanced', True),
                                       ('Portrait / shaded', 'High likeness', False)):
            with self.subTest(style=style, quality=quality), planner_fixture(style, quality) as (directory, options):
                with closing(source_image(size=(640, 480), opaque=opaque)) as raw:
                    path = directory / 'source.png'; raw.save(path)
                with closing(ImageImport.read_image(path)) as source:
                    initial = image_state(source)
                    copied = []; preparing = [False]
                    real_copy = Image.Image.copy
                    real_prepare = DrawBot.prepare_portrait_image
                    def prepare(*args, **kwargs):
                        preparing[0] = True
                        try:
                            return real_prepare(*args, **kwargs)
                        finally:
                            preparing[0] = False
                    def copy_image(image, *args, **kwargs):
                        result = real_copy(image, *args, **kwargs)
                        if preparing[0] and image.mode == 'RGBA' and image.size == source.size:
                            copied.append(image.width * image.height * 4)
                        return result
                    result = reference = None
                    try:
                        with patch.object(Image.Image, 'copy', new=copy_image), \
                                patch.object(DrawBot, 'prepare_portrait_image', new=prepare):
                            result = DrawBot.make_plan(source, (128, 96), copy.deepcopy(options))
                        self.assertEqual(copied, [])
                        self.assertGreater(result['options']['portrait_stats']['tone_strokes'], 0)
                        self.assertTrue(result['options']['paint_current_color'])
                        with patch.object(DrawBot, 'prepare_portrait_image', new=normalized_reference):
                            reference = DrawBot.make_plan(source, (128, 96), copy.deepcopy(options))
                        self.assertEqual(fingerprint(result), fingerprint(reference))
                        self.assertEqual(image_state(source), initial)
                    finally:
                        close_images(result, (source,)); close_images(reference, (source,))

    def test_modes_alpha_orientation_and_detail_outputs_match_pillow_normalization(self):
        for mode in ('RGBA', 'RGB', 'L', 'LA', 'P', 'RGBa'):
            for orientation in (None, 6):
                with closing(source_image(mode, orientation=orientation)) as source:
                    initial = image_state(source)
                    for preview in (None, 'Detailed'):
                        with self.subTest(mode=mode, orientation=orientation, preview=preview):
                            old_meta, new_meta = {}, {}
                            old_detail, new_detail = {}, {}
                            settings = dict(contrast=1.25, subject_focus=True, gpu_mode='CPU',
                                preview_detail_mode=preview)
                            expected, old_fit = normalized_reference(source, (96, 72), 8,
                                acceleration_meta=old_meta, preview_detail_meta=old_detail, **settings)
                            actual, new_fit = portrait.prepare_portrait_image(source, (96, 72), 8,
                                acceleration_meta=new_meta, preview_detail_meta=new_detail, **settings)
                            with closing(expected), closing(actual):
                                self.assertEqual(image_state(actual), image_state(expected))
                                self.assertEqual(new_fit, old_fit)
                                self.assertEqual(new_meta, old_meta)
                                self.assertEqual(new_detail, old_detail)
                            self.assertEqual(image_state(source), initial)
        for orientation in (1, 2, 3, 4, 5, 7, 8):
            with closing(source_image(orientation=orientation)) as source, self.subTest(orientation=orientation):
                expected, fit = normalized_reference(source, (96, 72), 8, gpu_mode='CPU')
                actual, actual_fit = portrait.prepare_portrait_image(source, (96, 72), 8, gpu_mode='CPU')
                with closing(expected), closing(actual):
                    self.assertEqual(image_state(actual), image_state(expected))
                    self.assertEqual(actual_fit, fit)

    def test_lazy_png_and_tiff_preserve_orientation_and_caller_stream(self):
        with closing(source_image(orientation=6)) as source:
            for fmt in ('PNG', 'TIFF'):
                with BytesIO() as encoded:
                    source.save(encoded, format=fmt, exif=source.getexif().tobytes())
                    payload = encoded.getvalue()
                outputs = []
                for prepare in (normalized_reference, portrait.prepare_portrait_image):
                    with BytesIO(payload) as stream, closing(Image.open(stream)) as borrowed:
                        result, fitted = prepare(borrowed, (96, 72), 8, gpu_mode='CPU')
                        with closing(result): outputs.append((image_state(result), fitted))
                        borrowed.getpixel((0, 0))
                        self.assertFalse(stream.closed)
                self.assertEqual(outputs[0], outputs[1])

    def test_success_retires_private_images_but_preserves_source_and_returned_gray(self):
        for mode, orientation in (('RGBA', None), ('RGBA', 6), ('RGB', 8), ('P', 1)):
            with self.subTest(mode=mode, orientation=orientation), \
                    closing(source_image(mode, (32, 24), orientation)) as source:
                initial = image_state(source)
                with owned_images() as images:
                    result, _ = portrait.prepare_portrait_image(source, (32, 24), 8, gpu_mode='CPU')
                with closing(result):
                    self.assertIsNot(result, source)
                    self.assert_closed(images, (result,))
                    result.putpixel((0, 0), 123)
                    self.assertEqual(image_state(source), initial)

    def test_initial_and_post_orientation_stop_do_not_allocate_the_next_buffer(self):
        with closing(source_image('RGB', orientation=6)) as source:
            initial = image_state(source)
            with patch.object(ImageOps, 'exif_transpose', side_effect=AssertionError('allocation before Stop')):
                with self.assertRaises(InterruptedError):
                    portrait.prepare_portrait_image(source, (64, 48), 8, cancelled=lambda: True)
            stopped = [False]; converted = []
            real_orient, real_convert = ImageOps.exif_transpose, Image.Image.convert
            def oriented(*args, **kwargs):
                result = real_orient(*args, **kwargs); stopped[0] = True
                return result
            def convert(image, *args, **kwargs):
                converted.append(image.mode)
                return real_convert(image, *args, **kwargs)
            with owned_images() as images, patch.object(ImageOps, 'exif_transpose', new=oriented), \
                    patch.object(Image.Image, 'convert', new=convert):
                with self.assertRaises(InterruptedError):
                    portrait.prepare_portrait_image(source, (64, 48), 8, cancelled=lambda: stopped[0])
            self.assertEqual(converted, [])
            self.assert_closed(images)
            self.assertEqual(image_state(source), initial)

    def test_retained_native_gray_and_resize_errors_close_only_private_images(self):
        for boundary in ('gray', 'resize', 'resize_stop'):
            with self.subTest(boundary=boundary), closing(source_image()) as source:
                initial = image_state(source); stopped = [False]; retained = []
                real_convert, real_resize = Image.Image.convert, Image.Image.resize
                def convert(image, mode=None, *args, **kwargs):
                    if boundary == 'gray' and mode == 'L':
                        return real_convert(image, 'INVALID_PORTRAIT_MODE', *args, **kwargs)
                    return real_convert(image, mode, *args, **kwargs)
                def resize(image, size, *args, **kwargs):
                    if boundary == 'resize': return real_resize(image, (0, 1), *args, **kwargs)
                    result = real_resize(image, size, *args, **kwargs)
                    if boundary == 'resize_stop': stopped[0] = True
                    return result
                try:
                    with owned_images() as images, patch.object(Image.Image, 'convert', new=convert), \
                            patch.object(Image.Image, 'resize', new=resize):
                        try:
                            portrait.prepare_portrait_image(source, (96, 72), 8, gpu_mode='CPU',
                                cancelled=lambda: stopped[0])
                        except (ValueError, InterruptedError) as error: retained.append(error)
                    self.assertEqual(len(retained), 1)
                    self.assertIsInstance(retained[0], InterruptedError if boundary == 'resize_stop' else ValueError)
                    if boundary != 'resize_stop':
                        self.assertTrue(any(Path(row.filename).name == 'Image.py'
                            for row in traceback.extract_tb(retained[0].__traceback__)))
                    self.assert_closed(images)
                    self.assertEqual(image_state(source), initial)
                finally:
                    for error in retained: traceback.clear_frames(error.__traceback__)
                    retained.clear()

    def test_retained_stop_in_actual_subject_lift_releases_pixel_access(self):
        for public in (False, True):
            with self.subTest(public=public), planner_fixture() as (_, options), \
                    closing(source_image()) as source:
                initial = image_state(source); retained = []
                def cancelled():
                    frame = sys._getframe(1)
                    try:
                        while frame is not None:
                            if (frame.f_code.co_name == '_prepare_portrait_image_impl'
                                    and frame.f_locals.get('px') is not None): return True
                            frame = frame.f_back
                        return False
                    finally:
                        frame = None
                try:
                    with owned_images() as images:
                        try:
                            if public: DrawBot.make_plan(source, (96, 72), options, cancelled)
                            else: portrait.prepare_portrait_image(source, (96, 72), 8,
                                subject_focus=True, gpu_mode='CPU', cancelled=cancelled)
                        except InterruptedError as error: retained.append(error)
                    self.assertEqual(len(retained), 1)
                    self.assert_closed(images)
                    self.assertEqual(retained_pixel_access(retained[0]), [])
                    self.assertEqual(image_state(source), initial)
                finally:
                    for error in retained: traceback.clear_frames(error.__traceback__)
                    retained.clear()

    def test_public_stop_after_preparation_retires_the_returned_gray(self):
        with planner_fixture() as (_, options), closing(source_image()) as source:
            initial = image_state(source); stopped = [False]; returned = []; retained = []
            real_prepare = DrawBot.prepare_portrait_image
            def prepare(*args, **kwargs):
                result = None
                try:
                    result = real_prepare(*args, **kwargs)
                    returned.append(result[0]); stopped[0] = True
                    return result
                finally:
                    result = None; args = (); kwargs = {}
            try:
                with patch.object(DrawBot, 'prepare_portrait_image', new=prepare):
                    try: DrawBot.make_plan(source, (128, 96), options, lambda: stopped[0])
                    except InterruptedError as error: retained.append(error)
                self.assertEqual(len(returned), 1)
                self.assertEqual(len(retained), 1)
                self.assertTrue(any(row.name == '_make_plan' for row in traceback.extract_tb(retained[0].__traceback__)))
                self.assert_closed(returned)
                self.assertEqual(image_state(source), initial)
            finally:
                for error in retained: traceback.clear_frames(error.__traceback__)
                retained.clear()
                for image in returned: image.close()


if __name__ == '__main__':
    unittest.main()
