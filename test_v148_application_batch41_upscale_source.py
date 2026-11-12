"""Borrow already oriented input while preserving complete resampling output."""
from contextlib import ExitStack, closing
from copy import deepcopy
from pathlib import Path
import queue
import threading
from types import MethodType
import unittest
from unittest.mock import patch

from PIL import Image, ImageOps

import DrawBot
import ImageUpscale as upscale
from ImageImport import read_image
from test_v148_ui_batch16_plan_status import PlanStatusFixture


ASSET = Path(__file__).with_name('assets') / 'image-draw-bot-icon.png'


def historical_pixels(image, factor, method):
    """The prior complete Pillow pipeline, kept as an exact regression oracle."""
    with ExitStack() as owned:
        source = owned.enter_context(closing(ImageOps.exif_transpose(image)))
        if source.mode != 'RGBA':
            source = owned.enter_context(closing(source.convert('RGBA')))
        target = upscale.upscale_size(source.size, factor)
        if method == 'Pixel art':
            result = source.resize(target, Image.Resampling.NEAREST)
        else:
            premultiplied = owned.enter_context(closing(source.convert('RGBa')))
            resized = owned.enter_context(closing(premultiplied.resize(target, Image.Resampling.LANCZOS)))
            result = resized.convert('RGBA')
        result.info.update(source.info)
        result.info['draw_studio_upscale'] = dict(factor=factor, method=method, source_size=source.size)
        return result


class _ImportedAssetFixture(PlanStatusFixture):
    def image(self, _color):
        image = read_image(ASSET)
        self.images.append(image)
        return image


class UpscaleSourceTests(unittest.TestCase):
    def source(self):
        image = read_image(ASSET)
        self.addCleanup(image.close)
        return image

    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_actual_worker_adoption_and_undo_avoid_the_imported_rgba_input_copy(self):
        fixture = _ImportedAssetFixture('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        fixture.stack.enter_context(patch('DrawBot.log_error'))
        for method in ('Pixel art', 'Smooth'):
            with self.subTest(method=method):
                app = fixture.app()
                app.events = queue.Queue()
                app.begin_worker = MethodType(DrawBot.DrawBotApp.begin_worker, app)
                source = app.original
                before = source.tobytes(), deepcopy(source.info), source.getexif().tobytes()
                self.assertEqual(source.mode, 'RGBA')
                self.assertEqual(source.getexif().get(274, 1), 1)
                with patch.object(source, 'copy', wraps=source.copy) as copies:
                    self.assertTrue(DrawBot.DrawBotApp._start_upscale(app, source, 2, method))
                    app.worker.join(timeout=5)
                    self.assertFalse(app.worker.is_alive())
                events = [app.events.get_nowait(), app.events.get_nowait()]
                self.assertEqual([kind for kind, _ in events], ['upscaled', 'done'])
                result = events[0][1][0]
                fixture.images.append(result)
                self.assertEqual(copies.call_count, 0, 'Already oriented input was duplicated before resizing')
                with closing(historical_pixels(source, 2, method)) as expected:
                    self.assertEqual((result.mode, result.size, result.tobytes(), result.info),
                                     (expected.mode, expected.size, expected.tobytes(), expected.info))
                for kind, value in events:
                    DrawBot.DrawBotApp._handle_event(app, kind, value)
                self.assertIs(app.original, result)
                self.assertIs(app.upscale_original, source)
                DrawBot.DrawBotApp.undo_upscale(app)
                self.assertIs(app.original, source)
                self.assertEqual((source.tobytes(), source.info, source.getexif().tobytes()), before)

    def test_modes_alpha_factor_and_rotation_metadata_match_the_complete_prior_pipeline(self):
        source = self.source()
        with closing(source.resize((31, 29), Image.Resampling.LANCZOS)) as sample, ExitStack() as owned:
            variants = [owned.enter_context(closing(sample.convert(mode))) for mode in ('RGBA', 'RGB', 'L', 'LA', 'P')]
            for orientation in range(2, 9):
                image = owned.enter_context(closing(sample.copy()))
                image.getexif()[274] = orientation
                image.info['exif'] = image.getexif().tobytes()
                variants.append(image)
            for image in variants:
                before = image.tobytes(), deepcopy(image.info), image.getexif().tobytes()
                for factor in (2, 4):
                    for method in ('Pixel art', 'Smooth'):
                        with self.subTest(mode=image.mode, orientation=image.getexif().get(274, 1), factor=factor, method=method), \
                                closing(historical_pixels(image, factor, method)) as expected, \
                                closing(upscale.upscale_image(image, factor, method)) as actual:
                            self.assertEqual((actual.mode, actual.size, actual.tobytes(), actual.info),
                                             (expected.mode, expected.size, expected.tobytes(), expected.info))
                            self.assertEqual(actual.getexif().get(274, 1), 1)
                            self.assertEqual((image.tobytes(), image.info, image.getexif().tobytes()), before)

    def test_stop_and_failed_resize_preserve_borrowed_input_and_close_private_results(self):
        source = self.source()
        before = source.tobytes(), deepcopy(source.info)
        resize = Image.Image.resize
        for method in ('Pixel art', 'Smooth'):
            with self.subTest(method=method):
                stopped = threading.Event()
                results = []

                def complete_then_stop(image, *args, **kwargs):
                    result = resize(image, *args, **kwargs)
                    results.append(result)
                    stopped.set()
                    return result

                with patch.object(Image.Image, 'resize', new=complete_then_stop), self.assertRaises(InterruptedError):
                    upscale.upscale_image(source, 2, method, stopped.is_set)
                self.assertTrue(results)
                for image in results:
                    self.assert_closed(image)
                self.assertEqual((source.tobytes(), source.info), before)
                failure = MemoryError('The native resampler has insufficient memory')
                with patch.object(Image.Image, 'resize', side_effect=failure), self.assertRaises(MemoryError) as caught:
                    upscale.upscale_image(source, 2, method)
                self.assertIs(caught.exception, failure)
                self.assertEqual((source.tobytes(), source.info), before)


if __name__ == '__main__':
    unittest.main()
