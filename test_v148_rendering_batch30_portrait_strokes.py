"""Private Portrait stroke views retire on Stop; borrowed inputs remain usable."""
from contextlib import ExitStack, closing, contextmanager
from copy import deepcopy
import sys
import threading
import traceback
import unittest
from unittest.mock import patch

from PIL import Image, ImageFilter

import DrawBot
import ImageImport
import PortraitPlanner as portrait
from test_v148_rendering_batch29_portrait_preparation import (
    planner_fixture, source_image, image_state, close_images, retained_pixel_access)


@contextmanager
def stroke_observation(target=None, *, callback_error=None, native_failure=False):
    """Delegate real Pillow/planner work; latch only the selected real boundary."""
    records = dict(prepared=[], converted=[], blurs=[], callbacks=[], scores=[], native_errors=[])
    stopped = threading.Event()
    prepare, convert, filtering = DrawBot.prepare_portrait_image, Image.Image.convert, Image.Image.filter

    def prepared(*args, **kwargs):
        result = None
        try:
            result = prepare(*args, **kwargs)
            records['prepared'].append(result[0])
            return result
        finally:
            result = args = kwargs = None

    def converted(image, mode=None, *args, **kwargs):
        result = caller = None
        try:
            caller = sys._getframe(1)
            result = convert(image, mode, *args, **kwargs)
            if (caller.f_globals is portrait.__dict__ and caller.f_code.co_name == 'portrait_strokes'
                    and mode == 'L'):
                records['converted'].append(result)
            return result
        finally:
            image = result = caller = args = kwargs = None

    def filtered(image, operation):
        result = caller = None
        try:
            caller = sys._getframe(1)
            owned_blur = caller.f_globals is portrait.__dict__ and caller.f_code.co_name == '_saliency_map'
            if native_failure and owned_blur:
                # Deliberate native-failure injection, not a supported GUI radius.
                # Keep Pillow's own TypeError and exact failure traceback.
                try:
                    return filtering(image, ImageFilter.GaussianBlur(('invalid-radius', 1.2)))
                except TypeError as error:
                    records['native_errors'].append(error)
                    raise
            result = filtering(image, operation)
            if owned_blur: records['blurs'].append(result)
            return result
        finally:
            image = operation = result = caller = None

    def cancelled():
        frame = parent = None
        try:
            if stopped.is_set(): return True
            frame = sys._getframe(1)
            if frame.f_globals is not portrait.__dict__: return False
            name = frame.f_code.co_name
            selected = ((target == 'saliency' and name == '_saliency_map' and frame.f_locals.get('bp') is not None)
                        or (target == 'dots' and name == '_dot_strokes' and frame.f_locals.get('px') is not None)
                        or (target == 'edges' and name == '_edge_strokes' and frame.f_locals.get('px') is not None)
                        or (target in ('sort', 'heap') and name == 'scores'))
            if not selected: return False
            row = {'function': name}
            parent = frame
            while parent is not None:
                if parent.f_code.co_name == '_select_tone_candidates':
                    local = parent.f_locals
                    count, priority = len(local['candidates']), local['priority_n']
                    records['scores'].append(local['scores'])
                    row.update(candidates=count, priority_n=priority,
                               branch='sort' if priority >= max(1, count // 4) else 'heap')
                    local = None
                    break
                parent = parent.f_back
            records['callbacks'].append(row)
            stopped.set()
            if callback_error is not None: raise callback_error
            return True
        finally:
            frame = parent = None

    records['cancelled'] = cancelled
    with ExitStack() as stack:
        stack.enter_context(patch.object(DrawBot, 'prepare_portrait_image', new=prepared))
        stack.enter_context(patch.object(Image.Image, 'convert', new=converted))
        stack.enter_context(patch.object(Image.Image, 'filter', new=filtered))
        try:
            yield records
        finally:
            for name in ('prepared', 'converted', 'blurs'):
                for image in records[name]: image.close()
            # Cleanup happens only after all retained-error assertions.
            for error in records['native_errors']: traceback.clear_frames(error.__traceback__)
            records.clear()
            image = error = None


def options_for(options, *, finite=False, dots=False):
    result = deepcopy(options)
    result.update(gpu_mode='CPU', lines=not dots, unlimited_time=not finite,
                  time_budget_mode='Manual' if finite else 'Unlimited / Accuracy',
                  manual_max_seconds=3 if finite else 180, max_seconds=3 if finite else 180)
    return result


class PortraitStrokeOwnershipTests(unittest.TestCase):
    def assert_closed(self, images):
        for image in images:
            with self.assertRaises(ValueError): image.getpixel((0, 0))

    def assert_own_views_released(self, error, records):
        self.assertEqual(retained_pixel_access(error), [],
                         'A failed product frame still owns a native PixelAccess')
        for function in records['scores']:
            cells = dict(zip(function.__code__.co_freevars, function.__closure__ or ()))
            self.assertIn('pixels', cells)
            self.assertIsNone(cells['pixels'].cell_contents)
        self.assert_closed(records['prepared'] + records['converted'] + records['blurs'])

    def public_interruption(self, target, *, finite=False, callback_error=None):
        with planner_fixture() as (_, options), closing(source_image(opaque=True)) as source:
            original = image_state(source)
            retained = None
            with stroke_observation(target, callback_error=callback_error) as records:
                try:
                    try:
                        DrawBot.make_plan(source, (128, 96), options_for(options, finite=finite,
                                          dots=target == 'dots'), records['cancelled'])
                    except (InterruptedError, RuntimeError) as error:
                        retained = error
                    self.assertIsNotNone(retained, 'The actual selected boundary must be reached')
                    if callback_error is not None: self.assertIs(retained, callback_error)
                    else: self.assertIsInstance(retained, InterruptedError)
                    self.assertEqual(len(records['prepared']), 1)
                    self.assertEqual(len(records['callbacks']), 1)
                    if target in ('sort', 'heap'):
                        self.assertEqual(records['callbacks'][0]['branch'], target)
                        self.assertGreater(records['callbacks'][0]['priority_n'], 0)
                    self.assert_own_views_released(retained, records)
                    self.assertEqual(image_state(source), original)
                    self.assertTrue(any(row.name == '_make_plan' for row in traceback.extract_tb(retained.__traceback__)))
                finally:
                    if retained is not None: traceback.clear_frames(retained.__traceback__)
                    retained = None

    def test_actual_public_saliency_stop_closes_blur_and_releases_both_gray_views(self):
        self.public_interruption('saliency')

    def test_actual_public_sort_and_finite_heap_stop_clear_the_captured_pixel_cell(self):
        for target in ('sort', 'heap'):
            with self.subTest(target=target): self.public_interruption(target, finite=target == 'heap')

    def test_actual_public_dot_and_edge_row_stop_release_their_own_views(self):
        for target in ('dots', 'edges'):
            with self.subTest(target=target): self.public_interruption(target)

    def test_actual_callback_failure_preserves_exception_identity_and_drops_private_views(self):
        for target in ('saliency', 'heap'):
            with self.subTest(target=target):
                self.public_interruption(target, finite=target == 'heap',
                                         callback_error=RuntimeError('actual callback failure'))

    def test_direct_borrowed_gray_and_converted_rgba_survive_actual_stroke_stop(self):
        for mode in ('L', 'RGBA'):
            with self.subTest(mode=mode), closing(source_image(mode, opaque=True)) as source:
                original = image_state(source)
                retained = None
                with stroke_observation('saliency') as records:
                    try:
                        try:
                            portrait.portrait_strokes(source, detail=8, gpu_mode='CPU',
                                                     cancelled=records['cancelled'])
                        except InterruptedError as error:
                            retained = error
                        self.assertIsNotNone(retained)
                        self.assertEqual(len(records['converted']), int(mode != 'L'))
                        self.assert_own_views_released(retained, records)
                        self.assertEqual(image_state(source), original)
                        source.putpixel((0, 0), 17 if mode == 'L' else (17, 23, 31, 255))
                    finally:
                        if retained is not None: traceback.clear_frames(retained.__traceback__)
                        retained = None

    def test_native_pillow_failure_keeps_its_diagnostics_but_retires_our_pixel_aliases(self):
        for public in (True, False):
            with self.subTest(public=public), planner_fixture() as (_, options), \
                    closing(source_image(opaque=True)) as source:
                original = image_state(source)
                retained = None
                with stroke_observation(native_failure=True) as records:
                    try:
                        try:
                            if public: DrawBot.make_plan(source, (128, 96), options_for(options))
                            else: portrait.portrait_strokes(source, detail=8, gpu_mode='CPU')
                        except TypeError as error:
                            retained = error
                        self.assertEqual(len(records['native_errors']), 1)
                        self.assertIs(retained, records['native_errors'][0])
                        self.assert_own_views_released(retained, records)
                        self.assertEqual(image_state(source), original)
                        # Deliberately keep third-party frame/diagnostics intact.
                        # This malformed-radius fault is not a valid UI setting.
                        frames = []
                        tb = retained.__traceback__
                        try:
                            while tb is not None:
                                if tb.tb_frame.f_code is ImageFilter.GaussianBlur.filter.__code__:
                                    frames.append(tb.tb_frame)
                                tb = tb.tb_next
                            self.assertEqual(len(frames), 1)
                            self.assertEqual(type(frames[0].f_locals['image']).__name__, 'ImagingCore')
                            frames[0].f_locals['image'].getpixel((0, 0))
                        finally:
                            frames.clear(); tb = None
                    finally:
                        if retained is not None: traceback.clear_frames(retained.__traceback__)
                        retained = None

    def test_successful_imported_public_plans_close_analysis_images_and_keep_source_and_output(self):
        for style, quality, dots in (('Auto', 'Balanced', False),
                                    ('Portrait / shaded', 'High likeness', False),
                                    ('Portrait / shaded', 'Balanced', True)):
            with self.subTest(style=style, quality=quality, dots=dots), \
                    planner_fixture(style, quality) as (directory, options):
                with closing(source_image(opaque=False)) as raw:
                    path = directory / 'portrait.png'
                    raw.save(path)
                with closing(ImageImport.read_image(path)) as source:
                    original = image_state(source)
                    result = None
                    with stroke_observation() as records:
                        try:
                            result = DrawBot.make_plan(source, (128, 96), options_for(options, dots=dots))
                            self.assertGreater(result['count'], 0)
                            self.assert_closed(records['prepared'] + records['blurs'])
                            self.assertEqual(image_state(source), original)
                            result['image'].getpixel((0, 0))
                            result['preview'].getpixel((0, 0))
                            self.assertIsNot(result['image'], source)
                        finally:
                            close_images(result, (source,))


if __name__ == '__main__':
    unittest.main()
