import unittest
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch

from PIL import Image

import ReleaseStabilityHardening as stability
import ResourceAllocation as allocation
import AdvancedColor
import PixelData


class StorageResourcesBatch02Tests(unittest.TestCase):
    def test_serial_cancel_stops_before_the_next_task(self):
        stop = threading.Event()
        seen = []
        def operation(value):
            seen.append(value)
            stop.set()
            return value
        with self.assertRaises(InterruptedError):
            allocation.parallel_map(operation, list(range(100)), backend='serial', workers=1,
                                    cancelled=stop.is_set)
        self.assertEqual(seen, [0])

    def test_cancellation_is_polled_while_waiting_and_queued_work_is_not_replenished(self):
        stop, started, release, observed = [threading.Event() for _ in range(4)]
        seen = []
        def operation(value):
            seen.append(value)
            started.set()
            release.wait(3)
            return value
        def cancelled():
            value = stop.is_set()
            if value:
                observed.set()
            return value
        with ThreadPoolExecutor(1) as outer:
            future = outer.submit(allocation.parallel_map, operation, list(range(100)),
                                  backend='threads', workers=2, cancelled=cancelled)
            try:
                self.assertTrue(started.wait(2))
                stop.set()
                self.assertTrue(observed.wait(1), 'cancellation was not polled during Future.result')
            finally:
                release.set()
            with self.assertRaises(InterruptedError):
                future.result(timeout=3)
        self.assertLessEqual(len(seen), 4)

    def test_worker_timeout_is_not_mistaken_for_a_poll_timeout(self):
        def operation(value):
            raise TimeoutError('actual worker failure')
        with self.assertRaisesRegex(TimeoutError, 'actual worker failure'):
            allocation.parallel_map(operation, [1, 2], backend='threads', workers=2,
                                    cancelled=lambda: False)

    def test_colour_planners_propagate_pool_cancellation_without_a_serial_retry(self):
        image = Image.new('RGBA', (20, 20), 'black')
        callback = lambda: False
        with patch.object(allocation, 'choose_parallel_backend', return_value='threads'), \
             patch.object(allocation, 'row_chunk_ranges', return_value=[(0, 10), (10, 20)]), \
             patch.object(allocation, 'parallel_map', side_effect=InterruptedError('stop pool')) as parallel:
            with self.assertRaises(InterruptedError):
                PixelData._parallel_basic_strokes(image, True, False, callback, 2, 'Threads', 512, False)
            self.assertIs(parallel.call_args.kwargs['cancelled'], callback)
            with self.assertRaises(InterruptedError):
                AdvancedColor._parallel_color_strokes(image, lines=True, skip_white=False,
                    color_rendering='Perceptual match', color_layers='Off',
                    custom_color_workflow='Calibrated palette', color_fidelity='Balanced',
                    cancelled=callback, cpu_workers=2, cpu_engine='Threads', ram_budget_mb=512, preview_plan=False)
            self.assertIs(parallel.call_args.kwargs['cancelled'], callback)

    def test_preview_budget_is_not_raised_to_a_hidden_minimum(self):
        with self.assertRaises(ValueError):
            stability.apply_preview_memory_limits(900_000, 1300, memory_budget_mb=128)
        result = stability.apply_preview_memory_limits(900_000, 1300, memory_budget_mb=160)
        self.assertEqual(result.memory_budget_mb, 160)
        self.assertLessEqual(result.estimated_working_set_mb, 160 * .62)
        self.assertLess(result.resolved_pixels, 120_000)

    def test_memory_reduction_never_enlarges_a_requested_dimension(self):
        result = stability.apply_preview_memory_limits(900_000, 200, memory_budget_mb=192)
        self.assertLessEqual(result.resolved_dimension, 200)
        self.assertLessEqual(result.resolved_pixels, 900_000)
        self.assertLessEqual(result.estimated_working_set_mb, result.memory_budget_mb * .62)

    def test_invalid_memory_parameters_do_not_disable_the_guard(self):
        for invalid in (float('nan'), float('inf'), True, -1, 10 ** 400):
            with self.subTest(value=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    stability.apply_preview_memory_limits(120_000, 500, memory_budget_mb=invalid)
                with self.assertRaises(ValueError):
                    stability.apply_preview_memory_limits(120_000, 500, safety_ratio=invalid)

    def test_cancelled_attempt_does_not_resume_when_external_flag_clears(self):
        stop = [True]
        guard = stability.PreviewAttemptGuard(10, external_cancelled=lambda: stop[0], clock=lambda: 0)
        self.assertTrue(guard.cancelled())
        stop[0] = False
        self.assertTrue(guard.cancelled())
        self.assertEqual(guard.remaining_seconds(), 0)
        with self.assertRaises(InterruptedError):
            guard.raise_if_cancelled()

    def test_timeout_cannot_be_reversed_by_a_backwards_clock(self):
        now = [0]
        guard = stability.PreviewAttemptGuard(1, clock=lambda: now[0])
        now[0] = 2
        self.assertTrue(guard.cancelled())
        now[0] = 0
        self.assertTrue(guard.cancelled())

    def test_timeout_and_start_must_define_a_finite_deadline(self):
        for invalid in (float('nan'), float('inf'), True, 10 ** 400):
            with self.subTest(value=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    stability.PreviewAttemptGuard(invalid)
                with self.assertRaises(ValueError):
                    stability.PreviewAttemptGuard(1, started=invalid)


if __name__ == '__main__':
    unittest.main()
