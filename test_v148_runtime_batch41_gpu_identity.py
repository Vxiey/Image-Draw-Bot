"""Runtime GPU evidence follows the measured hardware/profile generation.

Routing, profile files, context caching and concurrent operation ownership are
production code. The existing OpenCL ABI facade isolates unavailable native
resources; these are not physical-driver or performance measurements. Image
inputs are pixels from the committed Paint reference.
"""
from contextlib import ExitStack, closing
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import UniversalGpuAcceleration as gpu
import UniversalHardwareBenchmark as hardware
from test_v148_gpu_numeric import profile
from test_v148_platform_batch20_gpu_cache import CacheOpenCL


class RuntimeGpuIdentityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(directory) / 'hardware.json'
        for name in ('_FAILED', '_OPENCL_CACHE', '_OPENCL_IN_USE'):
            self.stack.enter_context(patch.object(gpu, name, {}))
        self.stack.enter_context(patch.object(hardware, 'PROFILE_FILE', self.path))
        self.current = self.measured()
        self.stack.enter_context(patch.object(hardware, 'hardware_snapshot',
            side_effect=lambda **kwargs: {'hardware_signature': self.current['hardware_signature']}))
        self.native = CacheOpenCL()
        self.stack.enter_context(patch.dict(sys.modules, {'pyopencl': self.native}))
        source = Path(__file__).resolve().parent / 'assets' / 'paint-tools-reference.png'
        with closing(Image.open(source)) as image, closing(image.convert('RGB')) as rgb:
            self.source = np.asarray(rgb).copy()
        self.source.flags.writeable = False
        self.target = self.source[::-1, ::-1]
        self.expected, _ = gpu.pixel_channel_error(self.source, self.target, gpu_mode='CPU')
        self.publish(self.current)

    def measured(self, *, hardware_id='adapter-A', revision='a' * 32, created_at=100):
        result = profile()
        result.update(version=hardware.PROFILE_VERSION, hardware_signature=hardware_id,
                      created_at=created_at)
        if revision is not None:
            result['measurement_id'] = revision
        return result

    def publish(self, result):
        self.current = deepcopy(result)
        hardware.save_hardware_profile(self.current)
        self.assertEqual(hardware.load_hardware_profile(), self.current)

    def operation(self, **kwargs):
        actual, metadata = gpu.pixel_channel_error(self.source, self.target, **kwargs)
        np.testing.assert_array_equal(actual, self.expected)
        return metadata

    def test_replacement_hardware_does_not_inherit_the_old_device_failure(self):
        def disconnected():
            raise RuntimeError('The old adapter disconnected')
        self.native.on_kernel = disconnected
        failed = self.operation()
        self.assertFalse(failed['accelerated'])
        self.assertIn('failed safely', failed['reason'])
        self.assertFalse(self.operation()['accelerated'])
        self.native.on_kernel = None
        self.publish(self.measured(hardware_id='adapter-B', revision='b' * 32))
        self.assertTrue(self.operation()['accelerated'])
        self.assertEqual(len(self.native.contexts), 2)
        self.assertIsNone(self.native.contexts[0]())

    def test_same_hardware_and_measurement_reuses_its_live_context(self):
        first = self.operation()
        self.publish(self.current)
        second = self.operation()
        self.assertEqual(first, second)
        self.assertTrue(second['accelerated'])
        self.assertEqual(len(self.native.contexts), 1)
        self.assertIsNotNone(self.native.contexts[0]())
        self.assertEqual(len(gpu._OPENCL_CACHE), 1)

    def test_new_measurement_in_the_same_second_gets_a_new_context(self):
        first = self.operation()
        self.publish(self.measured(revision='b' * 32, created_at=100))
        second = self.operation()
        self.assertEqual(first, second, 'Private cache identity leaked into public route metadata')
        self.assertEqual(len(self.native.contexts), 2)
        self.assertIsNone(self.native.contexts[0]())
        self.assertIsNotNone(self.native.contexts[1]())
        self.assertEqual(self.native.releases, 0)

    def test_completed_benchmarks_publish_distinct_measurements_in_one_second(self):
        # Exercise the actual benchmark and publisher with committed source
        # pixels. Only optional native availability and the source-data input
        # are isolated; NumPy workload verification and all profile code run.
        def existing_pixels(size):
            with closing(Image.fromarray(self.source)) as image, \
                    closing(image.resize((size, size), Image.Resampling.NEAREST)) as resized:
                return np.asarray(resized).astype(np.float32) / np.float32(255)
        with patch.dict(sys.modules, {'cupy': None, 'pyopencl': None}), \
                patch.object(hardware, '_synthetic_rgb', new=existing_pixels), \
                patch.object(hardware.time, 'time', return_value=100):
            results = [hardware.run_universal_hardware_benchmark(
                path=self.path, small_size=32, large_size=64, repeats=1,
                refresh_hardware=False) for _ in range(2)]
        self.assertEqual([result['created_at'] for result in results], [100, 100])
        first, second = (result['measurement_id'] for result in results)
        self.assertNotEqual(first, second)
        for revision in (first, second):
            self.assertRegex(revision, r'^[0-9a-f]{32}$')
        self.assertEqual(hardware.load_hardware_profile(path=self.path), results[-1])

    def test_new_completed_measurement_can_revalidate_the_same_adapter(self):
        old_route = gpu.select_route('pixel_math', pixels=1000)
        gpu._mark_failed(old_route, RuntimeError('Previous measurement generation failed'))
        self.assertFalse(self.operation()['accelerated'])
        self.publish(self.measured(revision='b' * 32, created_at=100))
        self.assertTrue(self.operation()['accelerated'])
        gpu._mark_failed(old_route, RuntimeError('Late error still belongs to the old measurement'))
        self.assertTrue(self.operation()['accelerated'])
        self.assertEqual(len(self.native.contexts), 1)

    def test_late_old_failure_cannot_poison_the_new_generation_or_release_its_context(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        old_results, errors = [], []
        def boundary():
            if threading.current_thread().name == 'old-gpu-generation':
                entered.set()
                if not release.wait(10):
                    raise AssertionError('The test did not release its old GPU operation')
                raise RuntimeError('Late failure from retired hardware')
        self.native.on_kernel = boundary
        def work():
            try:
                old_results.append(self.operation())
            except BaseException as error:
                errors.append(repr(error))
        thread = threading.Thread(target=work, name='old-gpu-generation')
        thread.start()
        try:
            self.assertTrue(entered.wait(10))
            old_context = self.native.contexts[0]
            self.publish(self.measured(hardware_id='adapter-B', revision='b' * 32))
            self.assertTrue(self.operation()['accelerated'])
            self.assertEqual(len(self.native.contexts), 2)
            self.assertIsNotNone(old_context(), 'Active old operation lost its native owner')
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(old_results), 1)
        self.assertFalse(old_results[0]['accelerated'])
        self.assertTrue(self.operation()['accelerated'])
        self.assertIsNone(old_context())
        self.assertEqual(len(gpu._OPENCL_CACHE), 1)
        self.assertEqual(gpu._OPENCL_IN_USE, {})
        self.assertEqual(self.native.releases, 0)

    def test_repeated_profile_replacements_retire_inactive_contexts(self):
        for generation in range(12):
            self.publish(self.measured(revision=f'{generation:032x}'))
            self.assertTrue(self.operation()['accelerated'])
            self.assertEqual(len(gpu._OPENCL_CACHE), 1)
            self.assertEqual(sum(value() is not None for value in self.native.contexts), 1)
        self.assertEqual(len(self.native.contexts), 12)
        self.assertEqual(gpu._OPENCL_IN_USE, {})

    def test_legacy_saved_profiles_use_hardware_and_record_time_identity(self):
        self.publish(self.measured(revision=None, created_at=100))
        self.assertTrue(self.operation()['accelerated'])
        self.publish(self.measured(revision=None, created_at=101))
        self.assertTrue(self.operation()['accelerated'])
        self.assertEqual(len(self.native.contexts), 2)
        self.assertIsNone(self.native.contexts[0]())

    def test_unidentified_legacy_callers_keep_the_existing_process_quarantine(self):
        legacy = profile()
        def unavailable():
            raise RuntimeError('Legacy device unavailable')
        self.native.on_kernel = unavailable
        self.assertFalse(self.operation(profile=legacy)['accelerated'])
        self.native.on_kernel = None
        self.assertFalse(self.operation(profile=legacy)['accelerated'])
        self.assertIn('opencl:0:0|pixel_math', gpu.backend_health_snapshot())

    def test_explicit_idle_cache_clear_preserves_generation_specific_failures(self):
        self.assertTrue(self.operation()['accelerated'])
        route = gpu.select_route('oklab', pixels=self.source.shape[0] * self.source.shape[1])
        gpu._mark_failed(route, RuntimeError('Only this generation has an OKLab failure'))
        before = gpu.backend_health_snapshot()
        result = gpu.clear_idle_opencl_cache()
        self.assertEqual(result['opencl_entries'], 1)
        self.assertEqual(gpu.backend_health_snapshot(), before)
        self.assertFalse(gpu.select_route('oklab', pixels=1000).accelerated)
        self.assertTrue(gpu.select_route('pixel_math', pixels=1000).accelerated)


if __name__ == '__main__':
    unittest.main()
