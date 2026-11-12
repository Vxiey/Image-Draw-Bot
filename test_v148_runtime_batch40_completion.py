"""Real executor completion races and inert empty numeric workloads.

Source pixels are read from a committed asset; empty inputs are slices of that
asset. Driver/profile failures are injected at their existing boundaries.
"""
from concurrent.futures import Future
from contextlib import ExitStack
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import ResourceAllocation as allocation
import UniversalGpuAcceleration as gpu
import UniversalHardwareBenchmark as hardware
from test_v148_gpu_numeric import profile


class ExecutorCompletionRaceTests(unittest.TestCase):
    def test_success_between_poll_timeout_and_done_is_collected_in_order(self):
        release = threading.Event()
        self.addCleanup(release.set)
        result = Future.result
        crossed = []

        def operation(value):
            if not release.wait(3):
                raise AssertionError('The test did not release its real workers.')
            return value * value

        def boundary(future, timeout=None):
            try:
                return result(future, timeout)
            except TimeoutError:
                # Reproduce the allowed interleaving: the real timed wait
                # expired, and a real worker then completed before done().
                if timeout == .05 and not crossed:
                    crossed.append(True)
                    release.set()
                    result(future, timeout=2)
                raise

        with patch.object(Future, 'result', new=boundary):
            actual = allocation.parallel_map(operation, [3, 1, 2, 5],
                backend='threads', workers=2, cancelled=lambda: False)
        self.assertEqual(crossed, [True])
        self.assertEqual(actual, [9, 1, 4, 25])

    def test_actual_worker_timeout_keeps_original_exception_identity(self):
        failure = TimeoutError('The actual operation timed out.')
        def operation(value):
            raise failure
        with self.assertRaises(TimeoutError) as observed:
            allocation.parallel_map(operation, [1, 2], backend='threads', workers=2,
                                    cancelled=lambda: False)
        self.assertIs(observed.exception, failure)


class NumericRoutingCompletionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gpu, '_FAILED', {}))
        source = Path(__file__).resolve().parent / 'assets' / 'paint-tools-reference.png'
        with Image.open(source) as existing, existing.convert('RGB') as rgb:
            self.source = np.asarray(rgb).copy()
        self.source.flags.writeable = False

    def test_empty_numeric_arrays_do_not_open_or_quarantine_a_measured_device(self):
        for shape in ('rows', 'columns'):
            empty = self.source[:0] if shape == 'rows' else self.source[:, :0]
            operations = (
                ('oklab', lambda: gpu.oklab_array(empty, profile=profile())),
                ('pair', lambda: gpu.perceptual_pair(empty, empty, profile=profile())),
                ('channels', lambda: gpu.pixel_channel_error(empty, empty, profile=profile())),
                ('edges', lambda: gpu.edge_magnitude(empty[..., 0], profile=profile())),
            )
            for name, operation in operations:
                with self.subTest(shape=shape, operation=name), \
                        patch.object(gpu, '_opencl_context', side_effect=RuntimeError('Zero-size native buffers are invalid')) as opened, \
                        patch.object(hardware, 'load_hardware_profile', side_effect=AssertionError('Empty work loaded a profile')) as loaded:
                    actual = operation()
                    self.assertFalse(actual[-1]['accelerated'])
                    self.assertEqual(actual[-1]['pixels'], 0)
                    for array in actual[:-1]:
                        self.assertEqual(array.size, 0)
                        self.assertEqual(array.shape[:2], empty.shape[:2])
                        self.assertEqual(array.dtype, np.float32)
                    opened.assert_not_called()
                    loaded.assert_not_called()
                    self.assertEqual(gpu.backend_health_snapshot(), {})

    def test_empty_work_respects_stop_before_publication(self):
        empty = self.source[:0]
        for operation in (
                lambda: gpu.oklab_array(empty, cancelled=lambda: True),
                lambda: gpu.perceptual_pair(empty, empty, cancelled=lambda: True),
                lambda: gpu.pixel_channel_error(empty, empty, cancelled=lambda: True),
                lambda: gpu.edge_magnitude(empty[..., 0], cancelled=lambda: True)):
            with self.assertRaises(InterruptedError):
                operation()

    def test_profile_interruption_never_falls_back_to_heavy_cpu_work(self):
        failure = InterruptedError('Stop during current hardware validation')
        for observed in (None, gpu.HardwareProfileObservation()):
            try:
                with self.subTest(observation=observed is not None), \
                        patch.object(hardware, 'load_hardware_profile', side_effect=failure), \
                        patch.object(gpu, '_oklab_cpu', side_effect=AssertionError('Cancelled routing ran CPU work')):
                    with self.assertRaises(InterruptedError) as caught:
                        gpu.oklab_array(self.source, profile=observed)
                    self.assertIs(caught.exception, failure)
                    self.assertEqual(gpu.backend_health_snapshot(), {})
            finally:
                if observed is not None:
                    observed.close()

    def test_interrupted_observation_can_retry_without_reusing_partial_state(self):
        observed = gpu.HardwareProfileObservation()
        self.addCleanup(observed.close)
        measured = profile('cpu:numpy')
        for preference in measured['workload_preferences'].values():
            preference['reason'] = 'current validated profile'
        with patch.object(hardware, 'load_hardware_profile',
                          side_effect=[InterruptedError('Stop'), measured]) as loaded:
            with self.assertRaises(InterruptedError):
                gpu.select_route('oklab', pixels=16, profile=observed)
            route = gpu.select_route('oklab', pixels=16, profile=observed)
            again = gpu.select_route('oklab', pixels=16, profile=observed)
        self.assertEqual(loaded.call_count, 2)
        self.assertEqual(route, again)
        self.assertEqual(route.backend_id, 'cpu:numpy')
        self.assertEqual(route.reason, 'current validated profile')

    def test_ordinary_profile_failure_still_selects_cpu(self):
        with patch.object(hardware, 'load_hardware_profile', side_effect=OSError('Unreadable profile')):
            actual, metadata = gpu.oklab_array(self.source)
        expected, _ = gpu.oklab_array(self.source, gpu_mode='CPU')
        np.testing.assert_array_equal(actual, expected)
        self.assertFalse(metadata['accelerated'])
        self.assertIn('Unreadable profile', metadata['reason'])


if __name__ == '__main__':
    unittest.main()
