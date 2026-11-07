"""Retained scanner errors release private pixel cores, arrays and iterators."""
from contextlib import contextmanager
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageDraw

import GetColorPositions as capture
import PaletteMaps as maps


def swatches(mode='RGBA'):
    image = Image.new(mode, (80, 40), (210, 210, 210))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 35, 35), fill=(255, 0, 0))
    draw.rectangle((44, 4, 75, 35), fill=(0, 0, 255))
    return image


def noisy_swatches(mode='RGBA'):
    data = np.zeros((96, 96, 3), np.uint8)
    yy, xx = np.indices(data.shape[:2])
    data[:] = np.where(((xx + yy) % 2)[..., None], 215, 120)
    data[30:42, 30:42] = (255, 0, 0)
    with Image.fromarray(data) as image:
        return image.convert(mode)


def frames(error):
    trace = error.__traceback__
    while trace is not None:
        yield trace.tb_frame
        trace = trace.tb_next


@contextmanager
def converted_images(source):
    images = []
    original = Image.Image.convert
    def observe(image, *args, **kwargs):
        result = original(image, *args, **kwargs)
        if image is source and result is not source:
            images.append(result)
        return result
    with patch.object(Image.Image, 'convert', new=observe):
        yield images


class PaletteScanOwnershipTests(unittest.TestCase):
    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def assert_no_readable_pixel_access(self, error):
        retained = []
        for frame in frames(error):
            for name, value in frame.f_locals.items():
                if type(value).__name__ != 'PixelAccess':
                    continue
                try:
                    value[0, 0]
                except ValueError:
                    continue
                retained.append((frame.f_code.co_name, name))
        self.assertEqual(retained, [], 'A saved exception still owns a readable native pixel core')

    def test_real_preset_validation_error_releases_owned_pixel_core(self):
        preset = maps.Palette('test', 'test', ('missing green',), ((0, 255, 0),))
        with swatches() as source, converted_images(source) as copies:
            before = source.tobytes()
            try:
                maps.detect_preset(source, preset)
            except ValueError as caught:
                failure = caught
            else:
                self.fail('The actual unmatched-preset validation must fail')
            self.assertIn('unambiguously', str(failure))
            self.assertEqual(len(copies), 1)
            self.assert_closed(copies[0])
            self.assert_no_readable_pixel_access(failure)
            self.assertEqual(source.tobytes(), before)

    def test_inner_preset_stop_and_allocation_error_keep_trace_but_release_pixel_access(self):
        for failure in (InterruptedError('retained Stop'), MemoryError('retained allocation')):
            with self.subTest(error=type(failure).__name__), Image.new('RGBA', (64, 64), 'white') as source:
                count = 0
                def interrupted():
                    nonlocal count
                    count += 1
                    if count == 3:
                        raise failure
                    return False
                with converted_images(source) as copies:
                    try:
                        maps.detect_preset(source, maps.Palette('test', 'test', ('white',), ((255, 255, 255),)),
                                           cancelled=interrupted)
                    except type(failure) as caught:
                        self.assertIs(caught, failure)
                    else:
                        self.fail('The original in-flood cancellation boundary was not reached')
                self.assertEqual(count, 3)
                self.assert_closed(copies[0])
                self.assert_no_readable_pixel_access(failure)
                self.assertEqual(source.getpixel((0, 0)), (255, 255, 255, 255))

    def test_span_row_failure_releases_both_pixel_aliases_and_numpy_exports(self):
        for mode in ('RGB', 'RGBA'):
            with self.subTest(mode=mode), swatches(mode) as source:
                before = source.tobytes()
                failure = MemoryError('retained row allocation')
                exports, calls = [], 0
                original = np.asarray
                def exported(*args, **kwargs):
                    result = original(*args, **kwargs)
                    exports.append(weakref.ref(result))
                    return result
                def interrupted():
                    nonlocal calls
                    calls += 1
                    if calls == 3:
                        raise failure
                    return False
                with converted_images(source) as copies, patch.object(np, 'asarray', new=exported):
                    try:
                        maps.detect_color_swatches(source, cancelled=interrupted)
                    except MemoryError as caught:
                        self.assertIs(caught, failure)
                    else:
                        self.fail('The real span scan did not reach its row boundary')
                self.assertEqual(calls, 3)
                self.assertTrue(exports)
                self.assertTrue(all(reference() is None for reference in exports),
                                'The saved span traceback retained a private NumPy image export')
                self.assert_no_readable_pixel_access(failure)
                for image in copies:
                    self.assert_closed(image)
                self.assertEqual(source.tobytes(), before)

    def test_noisy_vector_reduction_error_releases_every_private_array(self):
        failure = MemoryError('retained possible-swatches reduction')
        exports = []
        original, original_asarray = np.any, np.asarray
        def exported(*args, **kwargs):
            result = original_asarray(*args, **kwargs)
            exports.append(weakref.ref(result))
            return result
        def reduce(array, *args, **kwargs):
            if array.ndim == 2:
                # This is the actual noise precheck after a/breaks and all
                # three boolean scratch arrays exist. Keep only a weak ref and
                # remove the fault injector's own argument before raising.
                exports.append(weakref.ref(array))
                del array
                raise failure
            result = original(array, *args, **kwargs)
            exports.append(weakref.ref(result))
            return result
        with noisy_swatches() as source, converted_images(source) as copies:
            before = source.tobytes()
            with patch.object(np, 'any', new=reduce), patch.object(np, 'asarray', new=exported):
                try:
                    maps.detect_color_swatches(source)
                except MemoryError as caught:
                    self.assertIs(caught, failure)
                else:
                    self.fail('The actual noisy-image precheck did not run')
            self.assertEqual(len(exports), 3)
            self.assertTrue(all(reference() is None for reference in exports),
                            'The retained reduction traceback still owns private image/boolean arrays')
            for frame in frames(failure):
                if frame.f_code.co_name == '_span_components':
                    for name in ('a', 'breaks', 'same', 'row_solid', 'possible'):
                        self.assertIsNone(frame.f_locals.get(name), name)
            self.assert_no_readable_pixel_access(failure)
            self.assert_closed(copies[0])
            self.assertEqual(source.tobytes(), before)

    def test_real_dfs_iteration_error_releases_generator_frame_buffers(self):
        with noisy_swatches() as source, converted_images(source) as copies:
            failure, calls = MemoryError('retained DFS row allocation'), 0
            def interrupted():
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise failure
                return False
            try:
                maps.detect_color_swatches(source, cancelled=interrupted)
            except MemoryError as caught:
                self.assertIs(caught, failure)
            else:
                self.fail('The actual noisy-image DFS fallback did not reach its next row boundary')
            self.assertEqual(calls, 4)
            self.assertTrue(any(frame.f_code.co_name == '_pixel_components' for frame in frames(failure)))
            self.assert_no_readable_pixel_access(failure)
            for frame in frames(failure):
                if frame.f_code.co_name == '_pixel_components':
                    self.assertIsNone(frame.f_locals.get('visited'))
                    self.assertIsNone(frame.f_locals.get('stack'))
            self.assert_closed(copies[0])

    def test_real_consumer_type_error_closes_suspended_dfs_generator(self):
        generators = []
        original = maps._pixel_components
        def observe(*args, **kwargs):
            result = original(*args, **kwargs)
            generators.append(weakref.ref(result))
            return result
        with noisy_swatches() as source, converted_images(source) as copies, \
                patch.object(maps, '_pixel_components', new=observe):
            before = source.tobytes()
            try:
                # A native Python TypeError occurs when the real swatch consumer
                # adds its first detected x-coordinate to this invalid offset.
                maps.detect_color_swatches(source, offset=(None, 0))
            except TypeError as caught:
                failure = caught
            else:
                self.fail('The actual post-yield consumer calculation must fail')
            self.assertEqual(len(generators), 1)
            self.assertTrue(all(reference() is None for reference in generators),
                            'The retained consumer frame kept its suspended private DFS generator')
            self.assert_no_readable_pixel_access(failure)
            self.assert_closed(copies[0])
            self.assertEqual(source.tobytes(), before)

    def test_success_and_regular_stop_preserve_borrowed_sources_and_exact_results(self):
        for mode in ('RGB', 'RGBA'):
            with self.subTest(mode=mode), swatches(mode) as source, converted_images(source) as copies:
                before = source.tobytes()
                self.assertEqual(maps.detect_color_swatches(source, offset=(100, 200)),
                    ([(119, 219), (159, 219)], [(255, 0, 0), (0, 0, 255)],
                     {'found': 2, 'duplicates': 0, 'rejected': 1}))
                with self.assertRaises(InterruptedError):
                    maps.detect_color_swatches(source, cancelled=lambda: True)
                self.assertEqual(source.tobytes(), before)
                for image in copies:
                    self.assert_closed(image)

    def test_real_pillow_line_type_error_releases_retained_draw_handle(self):
        original_line = ImageDraw.ImageDraw.line
        originals = []
        def invalid_width(pen, xy, *args, **kwargs):
            # Keep the genuine Pillow frame and genuine C draw_lines TypeError.
            return original_line(pen, xy, fill='#ff00bf', width=None)
        original_copy = Image.Image.copy
        def copied(image):
            result = original_copy(image)
            originals.append(result)
            return result
        with Image.new('RGB', (40, 20), 'red') as source:
            ImageDraw.Draw(source).rectangle((20, 0, 39, 19), fill='blue')
            before = source.tobytes()
            settings = dict(box=(0, 0, 40, 20), mode='Grid', preset=None, rows=1, columns=2,
                            is_paint=False, max_colors=64)
            with patch.object(ImageDraw.ImageDraw, 'line', new=invalid_width), \
                    patch.object(Image.Image, 'copy', new=copied):
                try:
                    capture._analyze_palette_snapshot(source, settings, lambda: False)
                except TypeError as caught:
                    failure = caught
                else:
                    self.fail('Pillow must reject the noninteger line width')
            handles = {id(value): value for frame in frames(failure)
                       for value in frame.f_locals.values() if isinstance(value, ImageDraw.ImageDraw)}
            self.assertTrue(handles)
            self.assertTrue(any(frame.f_code.co_name == 'line' for frame in frames(failure)))
            for pen in handles.values():
                self.assertIsNone(pen.draw)
                self.assertIsNone(pen.im)
                self.assertIsNone(pen._image)
            self.assertTrue(originals)
            for image in originals:
                self.assert_closed(image)
            self.assertEqual(source.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
