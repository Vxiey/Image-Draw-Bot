"""Single-ink planning closes private images even with its failure retained."""
from contextlib import ExitStack, closing, contextmanager
import sys
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot
import PixelData
from test_v148_platform_batch22_numeric_ownership import retained_error
from test_v148_rendering_batch17_layered_diagnostics import calibrated
import test_v148_ui_batch07_renderer as renderer_fixture


def source_image(mode='RGBA'):
    with closing(Image.new('RGBA', (24, 16), 'white')) as source:
        draw = ImageDraw.Draw(source)
        draw.rectangle((2, 3, 8, 11), fill=(0, 0, 0, 255))
        draw.rectangle((10, 4, 14, 8), fill=(0, 0, 0, 100))
        draw.line((0, 15, 23, 0), fill=(60, 30, 80, 240))
        draw.rectangle((18, 5, 21, 10), fill=(0, 0, 0, 0))
        return source.convert(mode)


def image_open(image):
    try:
        image.getpixel((0, 0))
    except ValueError:
        return False
    return True


@contextmanager
def observed_images(*, cancelled=None, failure_at=None, failure=None, module=PixelData):
    """Retain actual private images to test explicit closure, never caller images."""
    evidence = {'images': [], 'operations': []}
    actual_convert, actual_new = Image.Image.convert, Image.new
    actual_composite = Image.Image.alpha_composite

    def in_reader():
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code is module.monochrome_strokes.__code__:
                return True
            frame = frame.f_back
        return False

    def remember(image, operation):
        # Strong references prevent object-id reuse and make explicit close
        # observable after success as well as through a retained traceback.
        if not any(image is existing for existing in evidence['images']):
            evidence['images'].append(image)
        evidence['operations'].append((operation, image.mode, image.size))
        if cancelled is not None and operation == 'gray':
            cancelled.set()
        return image

    def convert(image, mode=None, *args, **kwargs):
        observed = in_reader()
        if observed and mode == 'L' and failure_at == 'gray':
            raise failure
        result = actual_convert(image, mode, *args, **kwargs)
        return remember(result, 'gray' if mode == 'L' else 'rgba') if observed else result

    def new(*args, **kwargs):
        result = actual_new(*args, **kwargs)
        return remember(result, 'composite') if in_reader() else result

    def composite(image, *args, **kwargs):
        result = actual_composite(image, *args, **kwargs)
        if in_reader() and failure_at == 'composite':
            raise failure
        return result

    with patch.object(Image.Image, 'convert', convert), patch.object(Image, 'new', new), \
            patch.object(Image.Image, 'alpha_composite', composite):
        yield evidence


def expected_groups(source, lines):
    """Independent pixel membership and maximal-run oracle after Pillow luma."""
    with closing(source.convert('RGBA')) as rgba, \
            closing(Image.new('RGBA', source.size, 'white')) as white:
        white.alpha_composite(rgba)
        with closing(white.convert('L')) as gray:
            points = {(x, y) for y in range(gray.height) for x in range(gray.width)
                      if gray.getpixel((x, y)) < 180}
    if not lines:
        return [[(x, y, x, y) for x, y in sorted(points, key=lambda p: (p[1], p[0]))]]
    runs = []
    for y in range(source.height):
        starts = sorted(x for x, py in points if py == y and (x - 1, y) not in points)
        for start in starts:
            end = start
            while (end + 1, y) in points:
                end += 1
            runs.append((start, y, end, y))
    return [runs]


def public_options(*, outline=False):
    app = renderer_fixture.AdvertisedRendererTests().app('Microsoft Paint')
    app.render_style.set('Standard / pixel')
    app.paint_simple.set(True)
    app.outline.set(outline)
    return DrawBot.DrawBotApp.options(app)


class MonochromeOwnershipTests(unittest.TestCase):
    def assert_private_closed(self, evidence):
        self.assertTrue(evidence['images'])
        self.assertEqual([image_open(image) for image in evidence['images']],
                         [False] * len(evidence['images']))

    def test_preexisting_stop_does_not_allocate_or_read_the_image(self):
        with closing(source_image()) as source, observed_images() as evidence:
            before = source.tobytes()
            error = retained_error(lambda: PixelData.monochrome_strokes(source, cancelled=lambda: True))
            self.assertIsInstance(error, InterruptedError)
            self.assertIsNotNone(error.__traceback__)
            self.assertEqual(evidence['operations'], [])
            self.assertEqual(source.tobytes(), before)

    def test_normal_rgb_rgba_luma_and_palette_results_close_only_private_images(self):
        for mode in ('RGB', 'RGBA', 'L', 'P'):
            for lines in (False, True):
                with self.subTest(mode=mode, lines=lines), closing(source_image(mode)) as source:
                    before = source.tobytes(), dict(source.info)
                    expected = expected_groups(source, lines)
                    with observed_images() as evidence:
                        result = PixelData.monochrome_strokes(source, lines=lines)
                    self.assertEqual(result, expected)
                    self.assert_private_closed(evidence)
                    self.assertEqual((source.tobytes(), source.info), before)
                    self.assertFalse(any(image is source for image in evidence['images']))

    def test_stop_after_real_gray_conversion_closes_images_with_traceback_retained(self):
        for mode in ('RGB', 'RGBA'):
            with self.subTest(mode=mode), closing(source_image(mode)) as source:
                before = source.tobytes()
                stop = threading.Event()
                with observed_images(cancelled=stop) as evidence:
                    error = retained_error(lambda: PixelData.monochrome_strokes(source, cancelled=stop.is_set))
                self.assertIsInstance(error, InterruptedError)
                self.assertIsNotNone(error.__traceback__)
                self.assertTrue(stop.is_set())
                self.assert_private_closed(evidence)
                self.assertEqual(source.tobytes(), before)

    def test_partial_composite_and_gray_failure_close_completed_buffers(self):
        for mode in ('RGB', 'RGBA'):
            for boundary in ('composite', 'gray'):
                with self.subTest(mode=mode, boundary=boundary), closing(source_image(mode)) as source:
                    before = source.tobytes()
                    failure = MemoryError('image operation boundary')
                    with observed_images(failure_at=boundary, failure=failure) as evidence:
                        error = retained_error(lambda: PixelData.monochrome_strokes(source))
                    self.assertIs(error, failure)
                    self.assertIsNotNone(error.__traceback__)
                    self.assert_private_closed(evidence)
                    self.assertEqual(source.tobytes(), before)

    def test_actual_public_current_ink_and_sketch_keep_their_result_images(self):
        with calibrated(), closing(source_image()) as source:
            before = source.tobytes()
            for outline in (False, True):
                with self.subTest(outline=outline):
                    options = public_options(outline=outline)
                    self.assertTrue(options['paint_current_color'])
                    self.assertEqual(options['outline'], outline)
                    plan = None
                    try:
                        with observed_images() as evidence:
                            plan = DrawBot.make_plan(source, source.size, options)
                        self.assert_private_closed(evidence)
                        self.assertTrue(image_open(plan['image']))
                        self.assertTrue(image_open(plan['preview']))
                        self.assertEqual(plan['colors'], ((0, 0, 0),))
                        self.assertGreater(plan['count'], 0)
                        self.assertEqual(source.tobytes(), before)
                    finally:
                        renderer_fixture.close_images(plan)

    def test_actual_public_stop_preserves_the_caller_while_retiring_reader_images(self):
        with calibrated(), closing(source_image()) as source:
            before = source.tobytes()
            stop = threading.Event()
            options = public_options()
            with observed_images(cancelled=stop) as evidence:
                error = retained_error(lambda: DrawBot.make_plan(source, source.size, options, stop.is_set))
            self.assertIsInstance(error, InterruptedError)
            self.assertIsNotNone(error.__traceback__)
            self.assert_private_closed(evidence)
            self.assertEqual(source.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
