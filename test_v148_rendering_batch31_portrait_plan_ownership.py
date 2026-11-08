"""Actual Portrait finish/time-fit/rescue owns only its unpublished images."""
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
import sys
import threading
import traceback
import unittest
from unittest.mock import patch
import weakref

from PIL import Image

import DrawBot
import EndToEndAutoTuner
import ImageImport
import SketchFillRenderer
from test_v148_rendering_batch29_portrait_preparation import (
    planner_fixture, source_image, image_state)


def plan_images(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, Image.Image):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from plan_images(item, seen)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from plan_images(item, seen)


def is_open(image):
    try:
        image.getpixel((0, 0))
        return True
    except (ValueError, AttributeError, AssertionError):
        # Pillow's own allocation-failure frame can hold an uninitialized Image.
        return False


@contextmanager
def public_fixture(*, finite=True, borrowed=False, rescue=False):
    with planner_fixture('Portrait / shaded', 'High likeness') as (directory, options), ExitStack() as stack:
        size = (320, 240) if finite else (73, 55)
        area = (1200, 900) if finite else (128, 96)
        with closing(source_image(size=size, opaque=False)) as raw:
            path = directory / 'source.png'
            raw.save(path)
        source = stack.enter_context(closing(ImageImport.read_image(path)))
        options.update(gpu_mode='CPU', unlimited_time=not finite,
            time_budget_mode='Manual' if finite else 'Unlimited / Accuracy',
            manual_max_seconds=180, max_seconds=180)
        if finite:
            options.update(detail=10, delay=.025)
        if rescue:
            options = EndToEndAutoTuner.tune_options(source, dict(options,
                render_preset='Auto', render_style='Standard / pixel', paint_current_color=False))
            # A supported retained Auto context with an explicit Portrait choice;
            # all source analysis, acceptance gates and rescue decisions stay real.
            options.update(render_preset='Manual', render_style='Portrait / shaded',
                drawing_style='Auto', paint_current_color=True, outline=False,
                subject_focus='Off', extra_fast=False, extra_fast_v2=False,
                gpu_mode='CPU', unlimited_time=True, time_budget_mode='Unlimited / Accuracy')
            assert options['auto_tuner_meta']['active']
        inputs = [source]
        if borrowed:
            accuracy = stack.enter_context(closing(source.copy()))
            target = stack.enter_context(closing(source.copy()))
            with closing(source.convert('RGB')) as rgb:
                normalized = stack.enter_context(closing(rgb.resize(area)))
            inputs.extend((accuracy, target, normalized))
            options.update(_accuracy_original_source=accuracy, _accuracy_quantized_target=target,
                _accuracy_normalized_source_cache={'size': area, 'source': accuracy, 'image': normalized})
        yield source, options, area, tuple(inputs)


class Observation:
    def __init__(self, boundary=None, *, pillow_failure=False):
        self.boundary = boundary
        self.pillow_failure = pillow_failure
        self.stop = threading.Event()
        self.created = []
        self.finishes = []
        self.inputs = []
        self.completed_images = []
        self.active = 0
        self.injected = False
        self.original_error = None

    @contextmanager
    def installed(self):
        actual_finish, actual_new, actual_allocate = DrawBot.finish_plan, Image.Image._new, Image.new
        observer = self

        def created(owner, core):
            image = actual_new(owner, core)
            observer.created.append(weakref.ref(image))
            return image

        def allocate(mode, size, color=0):
            frame = None
            try:
                frame = sys._getframe(1)
                if (observer.pillow_failure and observer.active == observer.boundary
                        and frame.f_globals is DrawBot.__dict__
                        and frame.f_code.co_name == '_finish_plan' and not observer.injected):
                    observer.injected = True
                    # The real Pillow allocation boundary raises TypeError.
                    return actual_allocate(mode, size, object())
                return actual_allocate(mode, size, color)
            finally:
                frame = None

        def finish(image, fitted, groups, options, cancelled=lambda: False):
            result = None
            number = len(observer.finishes) + 1
            row = {'number': number, 'completed': False,
                'rescue': int(options.get('_auto_tuner_replan_attempt') or 0),
                'source_count': sum(len(group) for group in groups)}
            observer.finishes.append(row)
            observer.inputs.append(weakref.ref(image))
            observer.active = number
            match = number == observer.boundary or observer.boundary == 'rescue' and row['rescue'] == 1
            if match and not observer.pillow_failure:
                observer.stop.set()
            try:
                result = actual_finish(image, fitted, groups, options, cancelled)
                row.update(completed=True, count=result['count'], estimate=result['estimate'],
                    time_fitted=bool(result['options']['portrait_stats'].get('time_fitted')))
                observer.completed_images.append([weakref.ref(value) for value in plan_images(result)])
                return result
            except BaseException as error:
                observer.original_error = error
                raise
            finally:
                observer.active = 0
                result = image = groups = options = None

        with patch.object(DrawBot, 'finish_plan', new=finish), \
                patch.object(Image.Image, '_new', new=created), patch.object(Image, 'new', new=allocate):
            yield self

    def cleanup(self, borrowed=()):
        # Only after assertions: dispose observed private test images, without
        # clearing or modifying any original product/third-party traceback.
        for reference in self.created:
            image = reference()
            if image is not None and not any(image is value for value in borrowed):
                image.close()
        image = None
        self.original_error = None


class PortraitPlanOwnershipTests(unittest.TestCase):
    def assert_released(self, references, borrowed=()):
        keep = {id(image) for image in borrowed}
        retained = []
        for reference in references:
            image = reference()
            if image is not None and id(image) not in keep and is_open(image):
                retained.append((image.mode, image.size))
            image = None
        self.assertEqual(retained, [], 'Unpublished private Portrait images still hold readable cores.')

    def failure_case(self, boundary, *, native=False, borrowed=False, rescue=False):
        with public_fixture(finite=boundary != 1 and not rescue, borrowed=borrowed, rescue=rescue) as (
                source, options, area, inputs):
            initial = [image_state(image) for image in inputs]
            observation = Observation(boundary, pillow_failure=native)
            error = None
            try:
                with observation.installed():
                    try:
                        DrawBot.make_plan(source, area, options, observation.stop.is_set)
                    except (InterruptedError, TypeError) as caught:
                        error = caught
                self.assertIsNotNone(error)
                self.assertIs(error, observation.original_error, 'The original failure is replaced.')
                self.assertEqual([image_state(image) for image in inputs], initial)
                self.assertIsNone(SketchFillRenderer._current_plan_image_owner())
                self.assertEqual(len(observation.finishes), 2 if rescue else boundary)
                if boundary != 1:
                    self.assertTrue(observation.finishes[0]['completed'])
                    self.assertGreater(observation.finishes[0]['count'], 0)
                    if not rescue:
                        self.assertGreater(observation.finishes[0]['estimate'], 180 * .92)
                        self.assertLess(observation.finishes[1]['source_count'],
                                        observation.finishes[0]['source_count'])
                if rescue:
                    self.assertEqual([row['rescue'] for row in observation.finishes], [0, 1])
                if native:
                    self.assertIsInstance(error, TypeError)
                    self.assertTrue(observation.injected)
                    self.assertTrue(any(Path(frame.filename).name == 'Image.py'
                                        for frame in traceback.extract_tb(error.__traceback__)))
                else:
                    self.assertIsInstance(error, InterruptedError)
                # Assertions occur while the unchanged original traceback lives.
                self.assert_released(observation.inputs, inputs)
                for previous in observation.completed_images:
                    self.assert_released(previous, inputs)
                self.assert_released(observation.created, inputs)
            finally:
                observation.cleanup(inputs)
                error = None

    def test_first_real_finisher_stop_retires_private_rgba_and_accuracy_source(self):
        self.failure_case(1)

    def test_second_actual_time_fit_stop_retires_unpublished_previous_plan(self):
        self.failure_case(2)

    def test_real_pillow_failure_preserves_diagnostics_and_retires_unpublished_plans(self):
        self.failure_case(2, native=True)

    def test_retained_stop_preserves_explicit_borrowed_source_target_and_cache(self):
        self.failure_case(2, borrowed=True)

    def test_actual_tuner_rescue_stop_retires_the_first_unpublished_portrait(self):
        self.failure_case('rescue', rescue=True)

    def test_real_rescue_success_and_error_fallback_preserve_the_selected_plan(self):
        for native_failure in (False, True):
            with self.subTest(native_failure=native_failure), \
                    public_fixture(finite=False, borrowed=True, rescue=True) as (source, options, area, inputs):
                initial = [image_state(image) for image in inputs]
                observation = Observation(2 if native_failure else None, pillow_failure=native_failure)
                result = None
                try:
                    with observation.installed():
                        result = DrawBot.make_plan(source, area, options)
                    self.assertEqual([row['rescue'] for row in observation.finishes], [0, 1])
                    self.assertTrue(observation.finishes[0]['completed'])
                    self.assertEqual(observation.finishes[1]['completed'], not native_failure)
                    self.assertEqual(int(result['options'].get('_auto_tuner_replan_attempt') or 0),
                                     0 if native_failure else 1)
                    if native_failure:
                        self.assertIsInstance(observation.original_error, TypeError)
                        self.assertTrue(observation.injected)
                        self.assertEqual(result['count'], observation.finishes[0]['count'])
                    published = tuple(plan_images(result))
                    self.assertTrue(all(is_open(image) for image in published))
                    self.assert_released(observation.created, inputs + published)
                    self.assertEqual([image_state(image) for image in inputs], initial)
                    self.assertIsNone(SketchFillRenderer._current_plan_image_owner())
                finally:
                    observation.cleanup(inputs)
                    result = None

    def test_success_transfers_final_images_and_preserves_borrowed_inputs(self):
        for borrowed in (False, True):
            with self.subTest(borrowed=borrowed), public_fixture(borrowed=borrowed) as (
                    source, options, area, inputs):
                initial = [image_state(image) for image in inputs]
                observation = Observation()
                result = None
                try:
                    with observation.installed():
                        result = DrawBot.make_plan(source, area, options)
                    self.assertEqual(len(observation.finishes), 2)
                    self.assertTrue(all(row['completed'] for row in observation.finishes))
                    self.assertGreater(observation.finishes[0]['count'], result['count'])
                    self.assertTrue(result['options']['portrait_stats']['time_fitted'])
                    published = tuple(plan_images(result))
                    self.assertGreater(len(published), 5)
                    self.assertTrue(all(is_open(image) for image in published))
                    self.assert_released(observation.created, inputs + published)
                    self.assertIsNone(SketchFillRenderer._current_plan_image_owner())
                    self.assertEqual([image_state(image) for image in inputs], initial)
                    self.assertNotIn('_portrait_plan_owner', result['options'])
                    if borrowed:
                        self.assertIs(result['options']['_accuracy_original_source'], inputs[1])
                        self.assertIs(result['options']['_accuracy_quantized_target'], inputs[2])
                        self.assertIs(result['options']['_accuracy_normalized_source_cache']['image'], inputs[3])
                finally:
                    observation.cleanup(inputs)
                    result = None

    def test_existing_outer_image_scope_is_restored_and_can_own_the_returned_plan(self):
        for stop in (False, True):
            with self.subTest(stop=stop), public_fixture(finite=False) as (source, options, area, inputs):
                parent = SketchFillRenderer._PlanImageOwner(inputs)
                observation = Observation(1 if stop else None)
                result = error = None
                try:
                    with SketchFillRenderer._color_plan_image_scope(parent), observation.installed():
                        try:
                            result = DrawBot.make_plan(source, area, options, observation.stop.is_set)
                        except InterruptedError as caught:
                            error = caught
                        self.assertEqual(error is not None, stop)
                        self.assertIs(SketchFillRenderer._current_plan_image_owner(), parent)
                        self.assertFalse(parent.closed)
                        published = tuple(plan_images(result))
                        if not stop:
                            self.assertTrue(all(is_open(image) for image in published))
                            self.assertTrue(all(id(image) in parent.images for image in published
                                                if not any(image is value for value in inputs)))
                    self.assertIsNone(SketchFillRenderer._current_plan_image_owner())
                    parent.close()
                    self.assertTrue(all(not is_open(image) for image in published
                                        if not any(image is value for value in inputs)))
                    self.assert_released(observation.created, inputs)
                    self.assertTrue(all(is_open(image) for image in inputs))
                finally:
                    parent.close()
                    observation.cleanup(inputs)
                    result = error = None


if __name__ == '__main__':
    unittest.main()
