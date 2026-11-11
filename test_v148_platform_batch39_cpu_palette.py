"""Bound CPU palette preparation using real repository source pixels.

The unchanged dense cost model is the numerical reference. Allocation faults
are injected only at host preparation or an unavailable native boundary; the
public mapper, Pixel Accurate caller and complete public planner remain real.
No new raster motif is generated. Native facade tests do not claim GPU timing.
"""
from contextlib import ExitStack, contextmanager
import hashlib
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import CudaPalette
import PixelAccuratePlanner as pixel
import UniversalGpuAcceleration as gpu
from test_gpu_execution_regressions import FakeCupy
import test_v148_platform_batch26_opencl_host as native_fixture


ASSETS = Path(__file__).resolve().parent / 'assets'
BASE_PALETTE = ((0, 0, 0), (255, 255, 255), (220, 30, 30), (0, 80, 205), (0, 0, 0))
VISIBLE_REFERENCE = gpu._rgba_visible_rgb
EVIDENCE = {}


def retained_failure(operation):
    try:
        operation()
    except BaseException as failure:
        return failure
    raise AssertionError('The operation unexpectedly succeeded')


def digest(array):
    return {'shape': list(array.shape), 'dtype': array.dtype.str,
            'sha256': hashlib.sha256(array.tobytes()).hexdigest()}


def dense_reference(source, palette, candidates, custom, *, color_rendering,
                    color_fidelity, skip_white, custom_mode):
    """Whole-image composite and dense scoring, independent of CPU tiling."""
    with source.convert('RGBA') as rgba:
        rgb, visible = VISIBLE_REFERENCE(np.asarray(rgba, dtype=np.uint8))
    ids = np.asarray(list(dict.fromkeys(candidates)) or list(range(len(palette))), dtype=np.int16)
    selected_palette = np.asarray([palette[index] for index in ids], dtype=np.float32)
    cost = gpu._palette_cost_cpu(rgb, selected_palette,
        perceptual=color_rendering != 'RGB nearest', fidelity=color_fidelity)
    positions = cost.argmin(axis=-1)
    selected_custom = np.asarray([custom[index] for index in ids], dtype=bool)
    if custom_mode == 'Custom colors first' and selected_custom.any():
        preferred = np.where(selected_custom, cost, np.inf)
        positions = np.where(preferred.min(axis=-1) <= cost.min(axis=-1) * 1.06 + .0006,
                             preferred.argmin(axis=-1), positions)
    if skip_white:
        visible &= rgb.min(axis=-1) < 245.0
    return ids[positions], visible


class CompositeObservation:
    """Observe live NumPy composite payload, not native peak memory or RSS."""
    def __init__(self):
        self.pixels, self.rgb_references = [], []
        self.peak_rgb_bytes = 0

    def __call__(self, raw):
        self.pixels.append(raw.size // 4)
        rgb, visible = VISIBLE_REFERENCE(raw)
        self.rgb_references.append(weakref.ref(rgb))
        self.peak_rgb_bytes = max(self.peak_rgb_bytes,
            sum(reference().nbytes for reference in self.rgb_references if reference() is not None))
        return rgb, visible


class CpuPalettePreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gpu, '_FAILED', {}))
        self.stack.enter_context(patch.object(gpu, '_OPENCL_IN_USE', {}))

    @contextmanager
    def source(self, filename='paint-tools-reference.png', *, size=None):
        with Image.open(ASSETS / filename) as existing:
            source = existing.copy() if size is None else existing.resize(size, Image.Resampling.BOX)
        before = source.tobytes(), dict(source.info)
        try:
            yield source
            self.assertEqual((source.tobytes(), source.info), before)
        finally:
            source.close()

    def operation(self, source, **settings):
        return gpu.palette_indices_rgba(source, BASE_PALETTE, (), (), **settings)

    def assert_arrays(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for left, right in zip(actual, expected):
            self.assertEqual(left.dtype, right.dtype)
            np.testing.assert_array_equal(left, right)

    @contextmanager
    def allocation_limit(self):
        observed = []
        def prepare(raw):
            observed.append(raw.size // 4)
            if raw.size // 4 > 4096:
                raise MemoryError('host RGB preparation exceeds the controlled tile budget')
            return VISIBLE_REFERENCE(raw)
        with patch.object(gpu, '_rgba_visible_rgb', new=prepare):
            yield observed

    def test_cpu_preparation_bounds_actual_composite_payload_and_tail(self):
        with self.source('image-draw-bot-app-screenshot.webp') as source:
            observed = CompositeObservation()
            with patch.object(gpu, '_rgba_visible_rgb', new=observed), \
                    patch.object(gpu, '_opencl_context', side_effect=AssertionError('CPU opened a device')):
                result, route = self.operation(source, gpu_mode='CPU', color_rendering='RGB nearest')
            expected = dense_reference(source, BASE_PALETTE, (), (False,) * len(BASE_PALETTE),
                color_rendering='RGB nearest', color_fidelity='Balanced', skip_white=True,
                custom_mode='Calibrated palette')
            self.assert_arrays(result, expected)
            self.assertEqual(route, gpu.select_route('palette_match', pixels=source.width * source.height,
                                                    gpu_mode='CPU').as_dict())
            EVIDENCE['composite_payload'] = {'source_pixels': source.width * source.height,
                'preparations': len(observed.pixels), 'max_preparation_pixels': max(observed.pixels),
                'last_preparation_pixels': observed.pixels[-1],
                'peak_live_composite_rgb_numpy_nbytes': observed.peak_rgb_bytes}
            self.assertEqual(sum(observed.pixels), source.width * source.height)
            self.assertLessEqual(max(observed.pixels), 4096)
            self.assertLessEqual(observed.peak_rgb_bytes, 4096 * 3 * np.dtype(np.float32).itemsize)
            self.assertTrue(all(reference() is None for reference in observed.rgb_references))

    def test_dense_reference_preserves_alpha_fidelity_custom_order_and_ties(self):
        palette = BASE_PALETTE * 14
        candidates = tuple(reversed(range(len(palette)))) + (69, 0, 69)
        custom = tuple(index % 7 == 0 for index in range(len(palette)))
        for filename, size in (('paint-tools-reference.png', None), ('image-draw-bot-icon.png', (95, 73))):
            with self.source(filename, size=size) as source:
                for rendering in ('RGB nearest', 'Perceptual match'):
                    for fidelity in ('Off', 'Balanced', 'Faithful'):
                        for skip_white in (False, True):
                            for custom_mode in ('Calibrated palette', 'Custom colors first'):
                                with self.subTest(source=filename, rendering=rendering, fidelity=fidelity,
                                                  skip_white=skip_white, custom_mode=custom_mode):
                                    settings = dict(color_rendering=rendering, color_fidelity=fidelity,
                                                    skip_white=skip_white, custom_mode=custom_mode)
                                    expected = dense_reference(source, palette, candidates, custom, **settings)
                                    actual, route = gpu.palette_indices_rgba(source, palette, candidates, custom,
                                                                           gpu_mode='CPU', **settings)
                                    self.assert_arrays(actual, expected)
                                    self.assertFalse(route['accelerated'])

    def test_public_pixel_map_keeps_all_pixels_and_metadata_with_host_limit(self):
        with self.source('image-draw-bot-icon.png', size=(95, 73)) as source:
            settings = dict(gpu_mode='CPU', color_rendering='Perceptual match', color_fidelity='Faithful')
            expected = pixel.exact_palette_map(source, BASE_PALETTE, **settings)
            EVIDENCE['public_pixel_map'] = {'arrays': [digest(array) for array in expected[:3]],
                                           'metadata': expected[3]}
            with self.allocation_limit() as prepared:
                actual = pixel.exact_palette_map(source, BASE_PALETTE, **settings)
            self.assert_arrays(actual[:3], expected[:3])
            self.assertEqual(actual[3], expected[3], 'Avoidable whole-host allocation forced the emergency mapper')
            self.assertEqual(sum(prepared), source.width * source.height)

    def test_real_public_plan_preserves_rasters_and_execution_under_host_limit(self):
        with self.source() as source, native_fixture.calibrated(BASE_PALETTE):
            expected = actual = None
            routed = []
            original = gpu.palette_indices_rgba
            def observe(*args, **kwargs):
                result = original(*args, **kwargs)
                routed.append(result[1])
                return result
            try:
                expected = native_fixture.public_plan(source, 'CPU')
                EVIDENCE['public_plan'] = {
                    key: hashlib.sha256(expected[key].tobytes()).hexdigest() for key in ('image', 'preview')}
                EVIDENCE['public_plan']['execution_sha256'] = hashlib.sha256(
                    repr((expected['groups'], expected['execution_sequence'])).encode('utf-8')).hexdigest()
                with self.allocation_limit(), patch.object(gpu, 'palette_indices_rgba', new=observe):
                    actual = native_fixture.public_plan(source, 'CPU')
                for key in ('colors', 'color_selectors', 'groups', 'execution_groups', 'execution_sequence', 'count'):
                    self.assertEqual(actual[key], expected[key], key)
                for key in ('image', 'preview'):
                    self.assertEqual(actual[key].tobytes(), expected[key].tobytes(), key)
                self.assertEqual(set(actual['ui_previews']), set(expected['ui_previews']))
                for key in actual['ui_previews']:
                    self.assertEqual(actual['ui_previews'][key].tobytes(), expected['ui_previews'][key].tobytes(), key)
                self.assertTrue(routed, 'The complete public plan had to abandon the normal palette mapper')
                self.assertTrue(all(route['backend_id'] == 'cpu:numpy' and not route['accelerated']
                                    for route in routed))
            finally:
                for plan in (actual, expected):
                    if plan is not None:
                        native_fixture.close_plan(plan, source)

    def test_opencl_failure_releases_native_attempt_before_bounded_cpu_composites(self):
        with self.source() as source:
            expected, _ = self.operation(source, gpu_mode='CPU')
            failure = MemoryError('controlled native context allocation failure')
            owners = []
            def native_failure(_backend):
                partial = np.empty(16, dtype=np.uint8)
                owners.append(weakref.ref(partial))
                raise failure
            observed = CompositeObservation()
            def prepare(raw):
                self.assertTrue(owners)
                self.assertTrue(all(reference() is None for reference in owners))
                self.assertEqual(gpu._OPENCL_IN_USE, {})
                return observed(raw)
            with patch.object(gpu, '_opencl_context', new=native_failure), \
                    patch.object(gpu, '_rgba_visible_rgb', new=prepare):
                actual, route = self.operation(source, profile=native_fixture.measured_profile())
            self.assert_arrays(actual, expected)
            self.assertFalse(route['accelerated'])
            self.assertIn(str(failure), route['reason'])
            self.assertEqual(gpu.backend_health_snapshot(), {})
            self.assertIsNotNone(failure.__traceback__)
            self.assertEqual(sum(observed.pixels), source.width * source.height)
            self.assertLessEqual(max(observed.pixels), 4096)

    def test_cuda_fallback_reuses_existing_full_host_composite(self):
        with self.source() as source:
            expected, _ = self.operation(source, gpu_mode='CPU')
            observed = CompositeObservation()
            failure = MemoryError('controlled CUDA palette allocation failure')
            def native_failure(_cp, rgb, *_args, **_kwargs):
                self.assertEqual(observed.pixels, [source.width * source.height])
                self.assertIs(rgb, observed.rgb_references[0]())
                raise failure
            with patch.dict(sys.modules, {'cupy': FakeCupy()}), \
                    patch.object(CudaPalette, 'match', new=native_failure), \
                    patch.object(gpu, '_rgba_visible_rgb', new=observed):
                actual, route = self.operation(source, profile=native_fixture.measured_profile('cuda:0'))
            self.assert_arrays(actual, expected)
            self.assertEqual(observed.pixels, [source.width * source.height])
            self.assertFalse(route['accelerated'])
            self.assertEqual(gpu.backend_health_snapshot(), {})
            self.assertIsNone(observed.rgb_references[0]())

    def test_stop_during_composite_or_scoring_releases_partial_owned_work(self):
        for at in ('composite', 'scoring'):
            with self.subTest(at=at), self.source() as source:
                stop = threading.Event()
                owners, preparations, scores = [], [], []
                original_cost = gpu._palette_cost_cpu
                def prepare(raw):
                    rgb, visible = VISIBLE_REFERENCE(raw)
                    owners.extend(weakref.ref(value) for value in (raw, rgb, visible))
                    preparations.append(raw.size // 4)
                    if at == 'composite':
                        stop.set()
                    return rgb, visible
                def score(*args, **kwargs):
                    result = original_cost(*args, **kwargs)
                    owners.append(weakref.ref(result))
                    scores.append(True)
                    stop.set()
                    return result
                with patch.object(gpu, '_rgba_visible_rgb', new=prepare), \
                        patch.object(gpu, '_palette_cost_cpu', new=score):
                    failure = retained_failure(lambda: self.operation(source, gpu_mode='CPU', cancelled=stop.is_set))
                self.assertIsInstance(failure, InterruptedError)
                self.assertEqual(len(preparations), 1)
                self.assertEqual(len(scores), int(at == 'scoring'))
                self.assertLessEqual(preparations[0], 4096)
                self.assertTrue(all(reference() is None for reference in owners))
                self.assertEqual(gpu.backend_health_snapshot(), {})

    def test_retained_host_failure_releases_inputs_without_retry_or_backend_quarantine(self):
        for mode in ('CPU', 'Auto'):
            with self.subTest(mode=mode), self.source() as source:
                owners, preparations = [], []
                failure = MemoryError('controlled host composite failure')
                native = MemoryError('controlled native context failure')
                def prepare(raw):
                    rgb, visible = VISIBLE_REFERENCE(raw)
                    base = raw
                    while isinstance(base.base, np.ndarray):
                        base = base.base
                    owners.extend(weakref.ref(value) for value in (base, raw, rgb, visible))
                    preparations.append(raw.size // 4)
                    raise failure
                with patch.object(gpu, '_rgba_visible_rgb', new=prepare), \
                        patch.object(gpu, '_opencl_context', side_effect=native) as attempted:
                    actual = retained_failure(lambda: self.operation(source, gpu_mode=mode,
                        profile=native_fixture.measured_profile()))
                self.assertIs(actual, failure)
                self.assertEqual(len(preparations), 1)
                self.assertEqual(attempted.call_count, int(mode == 'Auto'))
                self.assertTrue(all(reference() is None for reference in owners))
                self.assertEqual(gpu.backend_health_snapshot(), {})


if __name__ == '__main__':
    unittest.main()
