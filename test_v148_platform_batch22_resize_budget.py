"""Resize preflight must reserve destination work before any native upload.

The existing tracked fixture and real Pillow fallback supply the pixels. The
native interpolation boundary raises an allocation error deliberately; these
tests check whether dispatch was permitted, not simulated CUDA image quality.
"""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import GpuAcceleration as gpu
from PIL import Image

from test_gpu_execution_regressions import FakeCupy


class ResizeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).resolve().parent / 'golden-regression' / 'small-detail-preservation.png'
        with Image.open(fixture) as existing:
            self.source = existing.convert('L')
        self.addCleanup(self.source.close)
        self.source_bytes = self.source.tobytes()
        self.info = gpu.AccelerationInfo('Auto', 'CUDA', True, 'Observed native boundary',
            total_vram_mb=16, free_vram_mb=4, vram_budget_mb=4,
            pool_used_mb=0, pool_cached_mb=0)
        self.cp = FakeCupy()
        self.uploads = []
        self.native_calls = []
        self.before_failure = None
        upload = self.cp.asarray
        def observed_upload(value, *args, **kwargs):
            self.uploads.append(value.shape)
            return upload(value, *args, **kwargs)
        self.cp.asarray = observed_upload
        def no_native_memory(array, **settings):
            self.native_calls.append((array.shape, settings))
            if self.before_failure is not None:
                self.before_failure()
            raise MemoryError('observed native allocation boundary')
        cnd = SimpleNamespace(zoom=no_native_memory)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gpu, 'acceleration_info', side_effect=lambda *args: self.info))
        self.stack.enter_context(patch.object(gpu, '_resolve_backend', return_value=('CUDA', (self.cp, cnd))))
        self.stack.enter_context(patch.object(gpu, 'best_nvidia_gpu', return_value=None))

    def assert_cpu_result(self, target, result, metadata):
        self.addCleanup(result.close)
        with self.source.resize(target, Image.Resampling.LANCZOS) as expected:
            self.assertEqual(result.size, expected.size)
            self.assertEqual(result.tobytes(), expected.tobytes())
        self.assertEqual(metadata.backend, 'CPU')
        self.assertFalse(metadata.accelerated)
        self.assertEqual(self.source.tobytes(), self.source_bytes)

    def test_upscale_checks_destination_workspace_before_upload(self):
        target = (720, 480)
        self.assertEqual(gpu.estimate_workspace_mb(*self.source.size, arrays=5), 3)
        self.assertEqual(gpu.estimate_workspace_mb(*target, arrays=5), 9)
        result, metadata = gpu.resize_gray_advanced(self.source, target)
        self.assert_cpu_result(target, result, metadata)
        self.assertEqual(self.uploads, [], 'An oversized destination was uploaded despite preflight')
        self.assertEqual(self.native_calls, [])
        self.assertEqual(metadata.workspace_estimate_mb, 9)
        self.assertIn('VRAM', metadata.scaler)

    def test_live_pool_allocations_remain_reserved_for_their_owners(self):
        self.info = replace(self.info, free_vram_mb=12, vram_budget_mb=16,
                            pool_used_mb=12, pool_cached_mb=12)
        self.assertEqual(gpu.available_vram_mb(self.info), 4)
        target = (720, 480)
        result, metadata = gpu.resize_gray_advanced(self.source, target)
        self.assert_cpu_result(target, result, metadata)
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.native_calls, [])
        self.assertEqual(metadata.workspace_estimate_mb, 9)

    def test_equal_pixel_count_opposite_aspect_ratio_still_permits_dispatch(self):
        target = (240, 360)
        result, metadata = gpu.resize_gray_advanced(self.source, target)
        self.assert_cpu_result(target, result, metadata)
        # Budget the larger pixel footprint, not the empty bounding rectangle
        # formed by independently taking the widest and tallest dimensions.
        self.assertEqual(self.uploads, [(240, 360)])
        self.assertEqual(len(self.native_calls), 1)
        self.assertIn('observed native allocation boundary', metadata.reason)

    def test_downscale_budget_uses_the_existing_prereduced_source(self):
        self.info = replace(self.info, free_vram_mb=2, vram_budget_mb=2)
        target = (30, 20)
        result, metadata = gpu.resize_gray_advanced(self.source, target)
        self.assert_cpu_result(target, result, metadata)
        self.assertEqual(self.uploads, [(80, 120)])
        self.assertEqual(len(self.native_calls), 1)
        self.assertIn('observed native allocation boundary', metadata.reason)

    def observed_cpu_fallback(self):
        original = Image.Image.resize
        calls = []
        def resized(image, target, *args, **kwargs):
            if image is self.source:
                calls.append(target)
            return original(image, target, *args, **kwargs)
        self.stack.enter_context(patch.object(Image.Image, 'resize', new=resized))
        return calls

    def test_stop_after_preflight_prevents_upload_and_cpu_retry(self):
        stop = threading.Event()
        original = gpu.plan_vram_allocation
        def planned(*args, **kwargs):
            plan = original(*args, **kwargs)
            stop.set()
            return plan
        self.stack.enter_context(patch.object(gpu, 'plan_vram_allocation', new=planned))
        cpu_calls = self.observed_cpu_fallback()
        with self.assertRaises(InterruptedError):
            gpu.resize_gray_advanced(self.source, (720, 480), cancelled=stop.is_set)
        self.assertEqual(cpu_calls, [])
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.source.tobytes(), self.source_bytes)

    def test_stop_at_native_allocation_failure_prevents_cpu_retry(self):
        stop = threading.Event()
        self.before_failure = stop.set
        cpu_calls = self.observed_cpu_fallback()
        with self.assertRaises(InterruptedError):
            gpu.resize_gray_advanced(self.source, (240, 360), cancelled=stop.is_set)
        self.assertEqual(len(self.native_calls), 1)
        self.assertEqual(cpu_calls, [])
        self.assertEqual(self.source.tobytes(), self.source_bytes)


if __name__ == '__main__':
    unittest.main()
