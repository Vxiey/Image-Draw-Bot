"""Native resize failure must release its work before a real Pillow fallback.

Pixels come only from an existing repository PNG. Pillow conversion, preflight,
pre-reduction, CPU resizing and cancellation run normally. The unavailable CUDA
upload/interpolation boundary allocates from those pixels and fails; it does
not simulate successful GPU arithmetic or claim physical-device coverage.
"""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import GpuAcceleration as gpu


ASSET = Path(__file__).resolve().parent / 'assets' / 'image-draw-bot-icon.png'
TARGET = (48, 37)


class NativeAllocationBoundary:
    """Retain errors, but hold source-derived scratch only through weak refs."""
    float32 = np.float32

    def __init__(self, stage, stopped):
        self.stage, self.stopped = stage, stopped
        self.arrays, self.errors, self.calls = [], [], []

    def fail(self):
        if self.stage == 'chained':
            try:
                raise MemoryError('native cubic allocation failed')
            except MemoryError as cause:
                failure = RuntimeError('native cubic transform failed')
                self.errors.append(failure)
                raise failure from cause
        failure = (InterruptedError('native resize stopped') if self.stage == 'interrupt' else
                   MemoryError('native allocation failed'))
        self.errors.append(failure)
        if self.stopped is not None:
            self.stopped.set()
        raise failure

    def asarray(self, raw, dtype=None, *, blocking=False):
        self.calls.append('upload')
        if not blocking:
            raise AssertionError('The private host owner requires a completed upload.')
        array = np.array(raw, dtype=dtype, copy=True)
        self.arrays.append(weakref.ref(array))
        if self.stage == 'upload':
            self.fail()
        return array

    def zoom(self, array, **_options):
        self.calls.append('cubic')
        scratch = array.copy()
        self.arrays.append(weakref.ref(scratch))
        self.fail()


class ResizeOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        with Image.open(ASSET) as existing:
            self.source = existing.copy()
        self.addCleanup(self.source.close)
        self.original_pixels = self.source.tobytes()
        self.original_info = dict(self.source.info)
        self.images = []
        self.native = None
        self.fallback_observations = []
        self.info = gpu.AccelerationInfo('Auto', 'CUDA', True, 'Native failure boundary',
            total_vram_mb=256, free_vram_mb=128, vram_budget_mb=64,
            pool_used_mb=0, pool_cached_mb=0)
        self.stack.enter_context(patch.object(gpu, 'best_nvidia_gpu', return_value=None))

    def observe_images(self, before_fallback=None, after_resize=None):
        convert, resize = Image.Image.convert, Image.Image.resize

        def converted(image, mode=None, *args, **kwargs):
            output = convert(image, mode, *args, **kwargs)
            if output is not image:
                self.images.append(('convert', output))
                self.addCleanup(output.close)
            return output

        def resized(image, size, *args, **kwargs):
            if tuple(size) == TARGET and before_fallback is not None:
                before_fallback()
            output = resize(image, size, *args, **kwargs)
            self.images.append(('resize', output))
            self.addCleanup(output.close)
            if after_resize is not None:
                after_resize(tuple(size))
            return output

        self.stack.enter_context(patch.object(Image.Image, 'convert', converted))
        self.stack.enter_context(patch.object(Image.Image, 'resize', resized))

    def native_boundary(self, stage='cubic', stopped=None):
        self.native = NativeAllocationBoundary(stage, stopped)
        self.stack.enter_context(patch.object(gpu, 'acceleration_info', side_effect=lambda *_a: self.info))
        self.stack.enter_context(patch.object(gpu, '_resolve_backend',
            return_value=('CUDA', (self.native, self.native))))
        return self.native

    @staticmethod
    def is_closed(image):
        try:
            image.getpixel((0, 0))
        except ValueError:
            return True
        return False

    def assert_images_closed(self, *, except_image=None):
        live = [(kind, image.size) for kind, image in self.images
                if image is not except_image and not self.is_closed(image)]
        self.assertEqual(live, [], 'Private image cores survived their operation.')

    def assert_source_unchanged(self):
        self.assertEqual(self.source.tobytes(), self.original_pixels)
        self.assertEqual(self.source.info, self.original_info)

    def assert_cpu_pixels(self, result, info):
        self.addCleanup(result.close)
        # Call Pillow after removing the observation wrappers. This is
        # the established full-source CPU output, never a generated test motif.
        with self.source.convert('L') as gray, gray.resize(TARGET, Image.Resampling.LANCZOS) as expected:
            self.assertEqual(result.size, expected.size)
            self.assertEqual(result.tobytes(), expected.tobytes())
        self.assertFalse(info.accelerated)
        self.assertEqual(info.backend, 'CPU')
        self.assert_source_unchanged()

    def test_native_upload_and_cubic_failures_release_arrays_before_cpu_fallback(self):
        for stage in ('upload', 'cubic', 'chained'):
            with self.subTest(stage=stage):
                with ExitStack() as case:
                    previous = self.stack
                    self.stack = case
                    self.images = []
                    native = self.native_boundary(stage)

                    def before_cpu():
                        self.fallback_observations.append(stage)
                        self.assertTrue(native.errors, 'The real fallback must follow the native failure.')
                        self.assertTrue(native.arrays)
                        self.assertTrue(all(reference() is None for reference in native.arrays),
                                        'Failed native frames retained arrays while CPU resize started.')

                    self.observe_images(before_cpu)
                    try:
                        result, info = gpu.resize_gray_advanced(self.source, TARGET)
                    finally:
                        self.stack = previous
                self.assert_cpu_pixels(result, info)
                self.assertIn('native', info.reason)
        self.assertEqual(self.fallback_observations, ['upload', 'cubic', 'chained'])

    def test_failed_cpu_fallback_retains_its_error_without_native_arrays_or_images(self):
        native = self.native_boundary('chained')
        failure = OSError('CPU resize allocation failed')

        def fail_cpu():
            raise failure

        self.observe_images(fail_cpu)
        try:
            gpu.resize_gray_advanced(self.source, TARGET)
        except OSError as actual:
            self.assertIs(actual, failure)
        else:
            self.fail('The CPU failure must remain visible.')
        self.assertTrue(native.errors and native.arrays)
        self.assertTrue(all(reference() is None for reference in native.arrays))
        self.assert_images_closed()
        self.assert_source_unchanged()

    def test_stop_at_native_failure_skips_cpu_retry_and_releases_retained_work(self):
        stopped = threading.Event()
        native = self.native_boundary(stopped=stopped)
        cpu = []
        self.observe_images(lambda: cpu.append(True))
        try:
            gpu.resize_gray_advanced(self.source, TARGET, cancelled=stopped.is_set)
        except InterruptedError as failure:
            retained = failure
        else:
            self.fail('Stop must remain an interruption.')
        self.assertIsInstance(retained, InterruptedError)
        self.assertEqual(cpu, [])
        self.assertTrue(native.errors and native.arrays)
        self.assertTrue(all(reference() is None for reference in native.arrays))
        self.assert_images_closed()
        self.assert_source_unchanged()

    def test_normalized_and_prereduced_images_close_after_successful_fallback(self):
        self.native_boundary()
        self.observe_images()
        result, info = gpu.resize_gray_advanced(self.source, TARGET)
        self.assert_images_closed(except_image=result)
        # Stop observing before computing the independent CPU oracle.
        self.stack.close()
        self.assert_cpu_pixels(result, info)

    def test_vram_rejection_closes_prereduced_image_before_cpu_resize(self):
        native = self.native_boundary()
        self.info = replace(self.info, free_vram_mb=1, vram_budget_mb=1)

        def before_cpu():
            private = [image for kind, image in self.images if kind == 'resize']
            self.assertTrue(private, 'The actual pre-reduction must have run.')
            self.assertTrue(all(self.is_closed(image) for image in private),
                            'VRAM fallback retained its discarded pre-reduction.')

        self.observe_images(before_cpu)
        result, info = gpu.resize_gray_advanced(self.source, TARGET)
        self.assertEqual(native.calls, [])
        self.assert_images_closed(except_image=result)
        self.stack.close()
        self.assert_cpu_pixels(result, info)
        self.assertIn('VRAM', info.reason)

    def test_cpu_resize_and_equal_size_preserve_exact_pixels_and_borrowed_source(self):
        with self.source.convert('L') as gray:
            for source in (self.source, gray):
                for target in (TARGET, source.size):
                    with self.subTest(mode=source.mode, target=target):
                        result, info = gpu.resize_gray_advanced(source, target, mode='CPU')
                        with result, source.convert('L') as expected_gray, \
                                expected_gray.resize(target, Image.Resampling.LANCZOS) as expected:
                            self.assertIsNot(result, source)
                            self.assertEqual(result.tobytes(), expected.tobytes())
                            self.assertFalse(info.accelerated)
                        source.getpixel((0, 0))
        self.assert_source_unchanged()

    def test_late_cpu_stop_closes_result_and_normalized_source(self):
        stopped = threading.Event()
        self.observe_images(after_resize=lambda size: stopped.set() if size == TARGET else None)
        with self.assertRaises(InterruptedError):
            gpu.resize_gray_advanced(self.source, TARGET, mode='CPU', cancelled=stopped.is_set)
        self.assert_images_closed()
        self.assert_source_unchanged()

    def test_native_failure_or_stop_stays_primary_when_prereduction_close_also_fails(self):
        close = Image.Image.close
        for stage in ('cubic', 'interrupt'):
            with self.subTest(stage=stage), ExitStack() as case:
                previous = self.stack
                self.stack = case
                native = self.native_boundary(stage)
                closed = []

                def noisy_close(image):
                    close(image)
                    if image.mode == 'L' and image.size == (192, 148):
                        closed.append(image)
                        raise OSError('private pre-reduction disposal failed')

                case.enter_context(patch.object(Image.Image, 'close', noisy_close))
                try:
                    if stage == 'interrupt':
                        with self.assertRaises(InterruptedError) as caught:
                            gpu.resize_gray_advanced(self.source, TARGET)
                        self.assertIs(caught.exception, native.errors[0])
                    else:
                        result, info = gpu.resize_gray_advanced(self.source, TARGET)
                        self.addCleanup(result.close)
                        self.assertIn('MemoryError: native allocation failed', info.reason)
                    self.assertEqual(len(closed), 1)
                    self.assertTrue(any('OSError' in note for note in native.errors[0].__notes__))
                finally:
                    self.stack = previous
        # With no primary error, disposal failure is still a real failure.
        def normalized_close(image):
            close(image)
            if image.mode == 'L' and image.size == self.source.size:
                raise OSError('normalization disposal failed')
        with patch.object(Image.Image, 'close', normalized_close):
            with self.assertRaisesRegex(OSError, 'normalization disposal failed'):
                gpu.resize_gray_advanced(self.source, TARGET, mode='CPU')
        self.assert_source_unchanged()

    def test_native_shape_mismatch_fits_real_pixels_and_closes_only_private_images(self):
        # Inject only an unexpected native result shape. Its pixels are a real
        # existing-image resize; the production final fit is actual Pillow.
        with self.source.convert('L') as gray, \
                gray.resize((47, 36), Image.Resampling.LANCZOS) as native_image, \
                native_image.resize(TARGET, Image.Resampling.LANCZOS) as expected:
            native_pixels = np.asarray(native_image).copy()
            expected_pixels = expected.tobytes()
        cp = SimpleNamespace(float32=np.float32, uint8=np.uint8,
            asarray=lambda value, dtype=None, **_kwargs: np.array(value, dtype=dtype, copy=True),
            asnumpy=lambda value: np.array(value, copy=True), clip=np.clip, rint=np.rint)
        native = SimpleNamespace(zoom=lambda *_a, **_k: native_pixels.copy())
        self.stack.enter_context(patch.object(gpu, 'acceleration_info', return_value=self.info))
        self.stack.enter_context(patch.object(gpu, '_resolve_backend', return_value=('CUDA', (cp, native))))
        self.observe_images()
        fromarray = Image.fromarray

        def observed(*args, **kwargs):
            image = fromarray(*args, **kwargs)
            self.images.append(('native result', image))
            self.addCleanup(image.close)
            return image

        self.stack.enter_context(patch.object(Image, 'fromarray', observed))
        result, info = gpu.resize_gray_advanced(self.source, TARGET)
        self.addCleanup(result.close)
        self.assertEqual(result.tobytes(), expected_pixels)
        self.assertEqual(info.scaler, 'CUDA cubic + CPU final fit')
        self.assert_images_closed(except_image=result)
        self.assert_source_unchanged()


if __name__ == '__main__':
    unittest.main()
