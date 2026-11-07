"""RC02 completion: unused shadow outputs end at their real caller boundary."""
from contextlib import ExitStack, closing, contextmanager
import hashlib
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import PixelAccuratePlanner as planner
import ShadowDetailEngine as shadow
import UniversalGpuAcceleration as gpu
from benchmark_v148_colour_batch20 import comparable
from test_v148_platform_batch22_numeric_ownership import retained_error
from test_v148_platform_batch26_opencl_host import PALETTE, pixel_source, public_plan
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_shadow import reference_maps
from test_v148_rendering_batch17_layered_diagnostics import calibrated


UNUSED = ('luma_map', 'local_tone_map', 'contour_mask',
          'shadow_detail_mask', 'deep_shadow_mask')
USED = ('contour_map', 'shadow_map', 'shadow_detail_map')
CONSUMERS = ('micro_detail_map', 'importance_map', 'protect_tiny_features')


def array_state(value):
    return value.dtype.str, value.shape, value.flags.writeable, hashlib.sha256(value.tobytes()).hexdigest()


@contextmanager
def observed_analysis(*, retained=None, after_analysis=lambda: None, fail_consumer=None, failure=None):
    evidence = {'references': {}, 'boundaries': [], 'states': {}, 'metadata': {}}
    original = shadow.analyze_shadow_contours
    def analyze(*args, **kwargs):
        result = original(*args, **kwargs)
        evidence['references'].update({key: weakref.ref(result[key]) for key in UNUSED + USED})
        evidence['states'].update({key: array_state(result[key]) for key in UNUSED + USED})
        evidence['metadata'].update(result['metadata'])
        if retained is not None:
            retained.append(result)
        after_analysis()
        return result
    def consumer(name, actual):
        def call(*args, **kwargs):
            evidence['boundaries'].append((name,
                {key: evidence['references'][key]() is not None for key in UNUSED + USED}))
            result = actual(*args, **kwargs)
            if name == fail_consumer:
                raise failure
            return result
        return call
    with ExitStack() as stack:
        stack.enter_context(patch.object(shadow, 'analyze_shadow_contours', new=analyze))
        for name in CONSUMERS:
            stack.enter_context(patch.object(planner, name, new=consumer(name, getattr(planner, name))))
        yield evidence


class ShadowCallerOwnershipTests(unittest.TestCase):
    def assert_released_before_consumers(self, evidence):
        self.assertEqual([name for name, _alive in evidence['boundaries']], list(CONSUMERS))
        for name, alive in evidence['boundaries']:
            with self.subTest(consumer=name):
                self.assertEqual({key: alive[key] for key in UNUSED}, dict.fromkeys(UNUSED, False))
                self.assertTrue(all(alive[key] for key in USED))

    def assert_unused_dead(self, evidence):
        self.assertEqual(set(evidence['references']), set(UNUSED + USED))
        self.assertTrue(all(evidence['references'][key]() is None for key in UNUSED))

    def test_actual_build_releases_unused_planes_and_transfers_exact_guidance(self):
        for kind in ('opaque', 'mixed-alpha', 'transparent'):
            with self.subTest(kind=kind), ExitStack() as stack:
                original_image = stack.enter_context(closing(pixel_source()))
                source = (stack.enter_context(closing(original_image.convert('RGB'))) if kind == 'opaque'
                          else stack.enter_context(closing(Image.new('RGBA', original_image.size, (31, 65, 99, 0))))
                          if kind == 'transparent' else original_image)
                before = source.tobytes(), dict(source.info)
                with observed_analysis() as evidence:
                    result = planner.build_pixel_map(source, PALETTE, gpu_mode='CPU')
                self.assert_released_before_consumers(evidence)
                expected = reference_maps(result.rgb, result.palette_index, result.drawable_mask, result.edge_map)
                for key in USED:
                    self.assertIs(getattr(result, key), evidence['references'][key]())
                    np.testing.assert_array_equal(getattr(result, key), expected[key])
                for key, value in evidence['metadata'].items():
                    self.assertEqual(result.metadata[key], value, key)
                self.assertEqual((source.tobytes(), source.info), before)

    def test_actual_public_pixel_plan_preserves_every_field_and_source(self):
        with calibrated(PALETTE), closing(pixel_source()) as source:
            before = source.tobytes(), dict(source.info)
            control, result = public_plan(source, 'CPU'), None
            try:
                with observed_analysis() as evidence:
                    result = public_plan(source, 'CPU')
                self.assert_released_before_consumers(evidence)
                self.assertEqual(comparable(result), comparable(control))
                self.assertEqual((source.tobytes(), source.info), before)
            finally:
                close_plan(control, source)
                if result is not None:
                    close_plan(result, source)

    def test_external_analysis_owner_keeps_all_arrays_and_mapping_unchanged(self):
        retained = []
        with closing(pixel_source()) as source, observed_analysis(retained=retained) as evidence:
            result = planner.build_pixel_map(source, PALETTE, gpu_mode='CPU')
            self.assertEqual(len(retained), 1)
            self.assertEqual(set(retained[0]), set(UNUSED + USED) | {'metadata'})
            self.assertEqual(retained[0]['metadata'], evidence['metadata'])
            for key in UNUSED + USED:
                self.assertEqual(array_state(retained[0][key]), evidence['states'][key])
            for key in USED:
                self.assertIs(getattr(result, key), retained[0][key])
            for _name, alive in evidence['boundaries']:
                self.assertTrue(all(alive.values()))
            retained.clear()  # Release only this observer's owning list.
            self.assert_unused_dead(evidence)
            for key in USED:
                self.assertIs(getattr(result, key), evidence['references'][key]())

    def test_stop_after_real_analysis_releases_result_with_traceback_retained(self):
        stopped = threading.Event()
        with closing(pixel_source()) as source, observed_analysis(after_analysis=stopped.set) as evidence:
            before = source.tobytes(), dict(source.info)
            error = retained_error(lambda: planner.build_pixel_map(source, PALETTE,
                gpu_mode='CPU', cancelled=stopped.is_set))
            self.assertIsInstance(error, InterruptedError)
            self.assertIsNotNone(error.__traceback__)
            self.assert_unused_dead(evidence)
            self.assertTrue(all(reference() is None for reference in evidence['references'].values()))
            self.assertEqual(evidence['boundaries'], [])
            self.assertEqual((source.tobytes(), source.info), before)

    def test_post_analysis_cancel_callback_failure_preserves_exception_identity(self):
        completed = threading.Event()
        failure = RuntimeError('cancel callback after analysis')
        def cancelled():
            if completed.is_set():
                raise failure
            return False
        with closing(pixel_source()) as source, observed_analysis(after_analysis=completed.set) as evidence:
            before = source.tobytes(), dict(source.info)
            error = retained_error(lambda: planner.build_pixel_map(source, PALETTE,
                gpu_mode='CPU', cancelled=cancelled))
            self.assertIs(error, failure)
            self.assertIsNotNone(error.__traceback__)
            self.assert_unused_dead(evidence)
            self.assertEqual(evidence['boundaries'], [])
            self.assertEqual((source.tobytes(), source.info), before)

    def test_real_consumer_failure_does_not_retain_unused_planes(self):
        for name in CONSUMERS:
            failure = MemoryError('after actual ' + name)
            with self.subTest(consumer=name), closing(pixel_source()) as source, \
                    observed_analysis(fail_consumer=name, failure=failure) as evidence:
                before = source.tobytes(), dict(source.info)
                error = retained_error(lambda: planner.build_pixel_map(source, PALETTE, gpu_mode='CPU'))
                self.assertIs(error, failure)
                self.assertIsNotNone(error.__traceback__)
                self.assertEqual(evidence['boundaries'][-1][0], name)
                self.assert_unused_dead(evidence)
                self.assertEqual((source.tobytes(), source.info), before)

    def test_actual_palette_fallback_preserves_output_and_shadow_ownership(self):
        def unavailable(*args, **kwargs):
            raise RuntimeError('controlled unavailable palette backend')
        with closing(pixel_source()) as source, \
                patch.object(gpu, 'palette_indices_rgba', new=unavailable):
            before = source.tobytes(), dict(source.info)
            control = planner.build_pixel_map(source, PALETTE, gpu_mode='CPU')
            with observed_analysis() as evidence:
                result = planner.build_pixel_map(source, PALETTE, gpu_mode='CPU')
            self.assertIn('controlled unavailable palette backend', result.metadata['palette_route']['fallback_reason'])
            self.assertEqual(result.metadata['palette_backend_id'], 'cpu:numpy')
            self.assert_released_before_consumers(evidence)
            self.assertEqual(comparable(result), comparable(control))
            self.assertEqual((source.tobytes(), source.info), before)


if __name__ == '__main__':
    unittest.main()
