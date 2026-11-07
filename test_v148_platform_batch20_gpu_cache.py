"""Explicit cache maintenance follows used resources, never compute policy."""
from contextlib import ExitStack
import queue
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

import numpy as np

import DrawBot
import GpuAcceleration as legacy
import GpuResourceCache as resources
import UniversalGpuAcceleration as universal
from test_gpu_execution_regressions import FakeCupy
from test_v148_application_batch04_settings import Value
from test_v148_application_batch14_browser_start import DeferredThread, ScheduledRoot, REAL_THREAD
from test_step23_universal_gpu_acceleration_v10146 import profile


class NativePool:
    """Native allocator boundary: live arrays and reusable blocks are distinct."""
    def __init__(self):
        self.live = 0
        self.total = 0
        self.limit = None
        self.clears = 0

    def set_limit(self, size):
        self.limit = size

    def used_bytes(self):
        return self.live

    def total_bytes(self):
        return self.total

    def free_all_blocks(self):
        self.clears += 1
        self.total = self.live

    def allocate(self, array):
        size = array.nbytes
        self.live += size
        self.total = max(self.total, self.live)
        weakref.finalize(array, self.release, size)
        return array

    def release(self, size):
        self.live -= size


class PoolCupy(FakeCupy):
    def __init__(self):
        super().__init__()
        self.pools = [NativePool() for _ in self.memory]
        self.pinned = NativePool()
        self.get_default_memory_pool = lambda: self.pools[self.current_device()]
        self.get_default_pinned_memory_pool = lambda: self.pinned
        self.asarray = lambda value, dtype=None, **kwargs: self.get_default_memory_pool().allocate(
            np.array(value, dtype=dtype, copy=True))
        self.mean = np.mean
        self.abs = np.abs


class OpenCLResource:
    def __init__(self, owner, kind, context=None):
        self.owner, self.kind, self.context = owner, kind, context
        owner.resources.append(weakref.ref(self))

    def release(self):
        self.owner.releases += 1
        raise AssertionError('Cache maintenance must never release native owners')

    def finish(self):
        pass

    def build(self, **kwargs):
        if self.owner.on_build is not None:
            self.owner.on_build()
        return self

    def ds_absdiff_kernel(self, _queue, _shape, _local, a, b, out, _count):
        if self.owner.on_kernel is not None:
            self.owner.on_kernel()
        out.data = np.mean(np.abs(a.data[:, :3] - b.data[:, :3]), axis=-1)


class CacheOpenCL(ModuleType):
    """Native ABI facade; context caching/borrowing stays in production code."""
    device_type = SimpleNamespace(GPU=1)
    mem_flags = SimpleNamespace(READ_ONLY=1, WRITE_ONLY=2, COPY_HOST_PTR=4)

    def __init__(self):
        super().__init__('pyopencl')
        self.resources = []
        self.contexts = []
        self.releases = 0
        self.on_kernel = None
        self.on_build = None

    def get_platforms(self):
        return [SimpleNamespace(get_devices=lambda **_: [object(), object()])]

    def Context(self, **kwargs):
        value = OpenCLResource(self, 'context')
        self.contexts.append(weakref.ref(value))
        return value

    def CommandQueue(self, ctx):
        return OpenCLResource(self, 'queue', ctx)

    def Program(self, ctx, _source):
        return OpenCLResource(self, 'program', ctx)

    def Buffer(self, ctx, _flags, size=None, hostbuf=None):
        return SimpleNamespace(context=ctx, data=None if hostbuf is None else np.array(hostbuf, copy=True))

    def enqueue_copy(self, _queue, destination, source, **kwargs):
        np.copyto(destination, np.asarray(source.data).reshape(destination.shape))


class GpuCacheActionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.cp = PoolCupy()
        scipy = ModuleType('cupyx.scipy')
        scipy.ndimage = SimpleNamespace(gaussian_filter=lambda array, **kwargs: array.copy())
        self.stack.enter_context(patch.dict(sys.modules, {
            'cupy': self.cp, 'cupyx': ModuleType('cupyx'), 'cupyx.scipy': scipy,
        }))
        self.stack.enter_context(patch.object(legacy, '_BACKEND_CACHE', False))
        self.stack.enter_context(patch.object(legacy, '_BACKEND_DEVICE_ID', None))
        self.stack.enter_context(patch.object(legacy, '_DISABLED_REASON', ''))
        self.stack.enter_context(patch.object(legacy, 'best_nvidia_gpu', return_value=None))
        self.stack.enter_context(patch.object(resources, '_CUDA_DEVICES', weakref.WeakKeyDictionary()))
        self.stack.enter_context(patch.object(universal, '_OPENCL_CACHE', {}))
        self.stack.enter_context(patch.object(universal, '_OPENCL_IN_USE', {}))
        self.stack.enter_context(patch.object(universal, '_FAILED', {}))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.log_error'))
        self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.stack.enter_context(patch('DrawBot.threading.Thread', DeferredThread))
        self.app = DrawBot.DrawBotApp.__new__(DrawBot.DrawBotApp)
        self.app.root = ScheduledRoot()
        self.app.activity = None
        self.app.worker = None
        self.app.closing = False
        self.app.shutdown_complete = False
        self.app.pending_clear_drawing = None
        self.app.profile_change_after = None
        self.app.profile_change_in_progress = False
        self.app.stop = threading.Event()
        self.app.paused = threading.Event()
        self.app.events = queue.Queue()
        self.app.status = Value('Ready.')
        self.app.gpu_mode = Value('Auto')
        self.app.set_busy = lambda activity: setattr(self.app, 'activity', activity)

    def clear_and_drain(self):
        self.app.clear_gpu_cache()
        worker = self.app.worker
        if worker is not None:
            worker.run()
        self.drain()

    def drain(self):
        while not self.app.events.empty():
            self.app._handle_event(*self.app.events.get_nowait())

    def use_legacy_cuda(self):
        context = legacy.cuda_context('Auto')
        self.assertIs(context[0], self.cp)
        self.assertEqual(context[1].device, 'GPU1')
        live = self.cp.asarray(np.arange(32, dtype=np.float32))
        temporary = self.cp.asarray(np.ones((24, 12, 3), dtype=np.float32))
        del temporary
        pool = self.cp.pools[1]
        self.assertGreater(pool.total_bytes(), pool.used_bytes())
        return live, pool

    def test_used_cuda_is_cleared_after_switching_policy_to_cpu_without_touching_live_array(self):
        live, pool = self.use_legacy_cuda()
        expected = live.copy()
        policy = self.app.gpu_mode
        policy.set('CPU')
        self.cp.local.device_id = 0
        with patch.object(legacy, '_load_cupy', side_effect=AssertionError('Must not probe CUDA')) as probe:
            self.clear_and_drain()
        self.assertEqual(pool.total_bytes(), pool.used_bytes())
        self.assertEqual(pool.used_bytes(), live.nbytes)
        self.assertEqual(pool.clears, 1)
        np.testing.assert_array_equal(live, expected)
        self.assertEqual(policy.get(), 'CPU')
        self.assertEqual(self.cp.current_device(), 0)
        probe.assert_not_called()

    def test_clear_before_any_gpu_use_never_initializes_a_backend(self):
        with patch.object(legacy, '_load_cupy', side_effect=AssertionError('Unused CUDA was initialized')) as probe:
            self.clear_and_drain()
        probe.assert_not_called()
        self.assertEqual([pool.clears for pool in self.cp.pools], [0, 0])
        self.assertEqual(self.app.gpu_mode.get(), 'Auto')

    def use_universal_cuda(self, device=0):
        source = np.arange(72, dtype=np.uint8).reshape(4, 6, 3)
        target = np.flip(source, axis=1).copy()
        result, meta = universal.pixel_channel_error(
            source, target, profile=profile(f'cuda:{device}', 'CUDA/CuPy', 'NVIDIA', f'GPU{device}'))
        reference, _ = universal.pixel_channel_error(source, target, gpu_mode='CPU')
        self.assertEqual(meta['backend_id'], f'cuda:{device}')
        np.testing.assert_array_equal(result, reference)
        return result

    def test_clear_reaches_legacy_and_measured_devices_and_shared_pinned_pool_once(self):
        live, legacy_pool = self.use_legacy_cuda()
        result = self.use_universal_cuda(0)
        expected = result.copy()
        pinned_live = self.cp.pinned.allocate(np.arange(12, dtype=np.uint8))
        pinned_temp = self.cp.pinned.allocate(np.ones(48, dtype=np.uint8))
        del pinned_temp
        self.app.gpu_mode.set('CPU')
        limits = [pool.limit for pool in self.cp.pools]
        self.clear_and_drain()
        self.assertEqual([pool.clears for pool in self.cp.pools], [1, 1])
        self.assertEqual([pool.total_bytes() for pool in self.cp.pools], [0, live.nbytes])
        self.assertEqual([pool.limit for pool in self.cp.pools], limits)
        self.assertEqual(self.cp.pinned.clears, 1)
        self.assertEqual(self.cp.pinned.total_bytes(), pinned_live.nbytes)
        np.testing.assert_array_equal(result, expected)
        self.assertEqual(legacy_pool.used_bytes(), live.nbytes)
        self.assertEqual(self.app.gpu_mode.get(), 'CPU')
        self.assertIn('2 device(s)', self.app.status.get())

    def test_idle_opencl_cache_is_dropped_but_active_operation_and_health_survive(self):
        cl = CacheOpenCL()
        self.stack.enter_context(patch.dict(sys.modules, {'pyopencl': cl}))
        self.app.gpu_mode.set('CPU')
        source = np.full((3, 5, 3), 80, dtype=np.uint8)
        target = np.full_like(source, 130)
        reference, _ = universal.pixel_channel_error(source, target, gpu_mode='CPU')
        first, _ = universal.pixel_channel_error(source, target,
            profile=profile('opencl:0:0', 'OpenCL', 'AMD', 'GPU0'))
        universal._FAILED[('opencl:0:0', 'edge_map')] = 'existing driver quarantine'
        health = universal.backend_health_snapshot()
        observed = []
        def while_active():
            self.clear_and_drain()
            observed.append((cl.contexts[0]() is None, cl.contexts[1]() is not None,
                             set(universal._OPENCL_CACHE)))
        cl.on_kernel = while_active
        second, meta = universal.pixel_channel_error(source, target,
            profile=profile('opencl:0:1', 'OpenCL', 'Intel', 'GPU1'))
        self.assertEqual(observed, [(True, True, {'opencl:0:1'})])
        self.assertEqual(meta['backend_id'], 'opencl:0:1')
        np.testing.assert_array_equal(first, reference)
        np.testing.assert_array_equal(second, reference)
        self.assertEqual(universal._OPENCL_IN_USE, {})
        self.assertIn('Active OpenCL resources were kept', self.app.status.get())
        self.clear_and_drain()
        self.assertEqual(universal._OPENCL_CACHE, {})
        self.assertTrue(all(reference() is None for reference in cl.resources))
        self.assertEqual(cl.releases, 0)
        self.assertEqual(universal.backend_health_snapshot(), health)
        self.assertEqual(self.app.gpu_mode.get(), 'CPU')

    def test_opencl_build_on_another_worker_is_kept_without_waiting_for_native_build(self):
        cl = CacheOpenCL()
        self.stack.enter_context(patch.dict(sys.modules, {'pyopencl': cl}))
        entered, finish = threading.Event(), threading.Event()
        def building():
            entered.set()
            if not finish.wait(2):
                raise RuntimeError('test native build was not released')
        cl.on_build = building
        outputs, failures = [], []
        def operation():
            try:
                value = np.full((2, 2, 3), 110, dtype=np.uint8)
                outputs.append(universal.pixel_channel_error(value, value,
                    profile=profile('opencl:0:0', 'OpenCL', 'AMD', 'GPU0')))
            except BaseException as error:
                failures.append(error)
        worker = REAL_THREAD(target=operation)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.clear_and_drain()
            self.assertIn('Active OpenCL resources were kept', self.app.status.get())
            self.assertTrue(worker.is_alive())
            self.assertEqual(cl.releases, 0)
        finally:
            finish.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(outputs[0][1]['backend_id'], 'opencl:0:0')
        np.testing.assert_array_equal(outputs[0][0], np.zeros((2, 2), dtype=np.float32))
        self.clear_and_drain()
        self.assertEqual(universal._OPENCL_CACHE, {})
        self.assertTrue(all(reference() is None for reference in cl.resources))

    def test_opencl_error_and_stop_release_borrow_without_erasing_quarantine_or_external_owner(self):
        cl = CacheOpenCL()
        self.stack.enter_context(patch.dict(sys.modules, {'pyopencl': cl}))
        value = np.full((2, 2, 3), 110, dtype=np.uint8)
        for error in (RuntimeError('kernel failed'), InterruptedError('stopped')):
            with self.subTest(error=type(error).__name__):
                universal._FAILED.clear()
                def fail():
                    raise error
                cl.on_kernel = fail
                kwargs = {'profile': profile('opencl:0:0', 'OpenCL', 'AMD', 'GPU0')}
                if isinstance(error, InterruptedError):
                    with self.assertRaises(InterruptedError):
                        universal.pixel_channel_error(value, value, **kwargs)
                else:
                    result, meta = universal.pixel_channel_error(value, value, **kwargs)
                    self.assertEqual(meta['backend_id'], 'cpu:numpy')
                    np.testing.assert_array_equal(result, np.zeros((2, 2), dtype=np.float32))
                self.assertEqual(universal._OPENCL_IN_USE, {})
                owned = universal._OPENCL_CACHE['opencl:0:0']
                health = universal.backend_health_snapshot()
                self.clear_and_drain()
                self.assertEqual(universal._OPENCL_CACHE, {})
                self.assertEqual(owned[1].kind, 'context')
                self.assertEqual(cl.releases, 0)
                self.assertEqual(universal.backend_health_snapshot(), health)

    def test_registry_failure_does_not_change_numeric_success_or_thread_device(self):
        class BrokenRegistry:
            def setdefault(self, *args):
                raise RuntimeError('registration unavailable')
        self.cp.local.device_id = 1
        with patch.object(resources, '_CUDA_DEVICES', BrokenRegistry()):
            self.use_universal_cuda(0)
        self.assertEqual(self.cp.current_device(), 1)

    def test_opencl_stop_releases_already_removed_cache_references_in_retained_traceback(self):
        cl = CacheOpenCL()
        self.stack.enter_context(patch.dict(sys.modules, {'pyopencl': cl}))
        value = np.full((2, 2, 3), 110, dtype=np.uint8)
        for index in (0, 1):
            universal.pixel_channel_error(value, value,
                profile=profile(f'opencl:0:{index}', 'OpenCL', 'AMD', f'GPU{index}'))
        caught = None
        try:
            legacy.clear_gpu_cache('CPU', cancelled=lambda: len(universal._OPENCL_CACHE) == 1)
        except InterruptedError as error:
            caught = error
        self.assertIsNotNone(caught)
        self.assertIsNotNone(caught.__traceback__)
        self.assertEqual(set(universal._OPENCL_CACHE), {'opencl:0:1'})
        self.assertIsNone(cl.contexts[0]())
        self.assertIsNotNone(cl.contexts[1]())
        self.assertEqual(cl.releases, 0)

    def test_used_cuda_remains_maintainable_after_quarantine_and_one_native_trim_failure(self):
        live, pool = self.use_legacy_cuda()
        self.use_universal_cuda(0)
        legacy._disable_backend(RuntimeError('existing CUDA quarantine'))
        universal._FAILED[('cuda:0', 'edge_map')] = 'existing measured quarantine'
        health = universal.backend_health_snapshot()
        reason = legacy._DISABLED_REASON
        with patch.object(self.cp.pools[0], 'free_all_blocks', side_effect=RuntimeError('device busy')):
            self.clear_and_drain()
        self.assertIn('CUDA device 0: RuntimeError: device busy', self.app.status.get())
        self.assertEqual(pool.total_bytes(), live.nbytes)
        self.assertEqual(self.cp.pinned.clears, 1)
        self.assertIsNone(legacy._BACKEND_CACHE)
        self.assertEqual(legacy._DISABLED_REASON, reason)
        self.assertEqual(universal.backend_health_snapshot(), health)
        self.use_universal_cuda(0)  # An allocator-maintenance error is not a new quarantine.

    def test_worker_handoff_keeps_ui_responsive_and_stop_before_work_keeps_pools(self):
        live, pool = self.use_legacy_cuda()
        self.assertTrue(self.app.clear_gpu_cache())
        self.assertEqual(self.app.activity, 'gpu-cache')
        self.assertEqual(pool.clears, 0)
        self.app.stop.set()
        self.app.worker.run()
        self.drain()
        self.assertEqual(pool.clears, 0)
        self.assertGreater(pool.total_bytes(), live.nbytes)
        self.assertIsNone(self.app.activity)
        self.assertEqual(self.app.status.get(), 'Stopped.')

    def test_explicit_start_clears_old_stop_but_constructor_stop_and_late_event_do_not(self):
        live, pool = self.use_legacy_cuda()
        self.app.stop.set()
        self.clear_and_drain()
        self.assertEqual(pool.clears, 1)
        self.assertFalse(self.app.stop.is_set())
        app = self.app
        class StopDuringConstruction(DeferredThread):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                app.stop.set()
        with patch('DrawBot.threading.Thread', StopDuringConstruction):
            self.clear_and_drain()
        self.assertEqual(pool.clears, 1)
        self.assertEqual(self.app.status.get(), 'Stopped.')
        self.assertTrue(self.app.clear_gpu_cache())
        self.app.worker.run()
        self.app.stop.set()
        self.drain()
        self.assertEqual(pool.clears, 2)
        self.assertEqual(self.app.status.get(), 'Stopped.')
        self.assertEqual(pool.used_bytes(), live.nbytes)

    def test_stop_after_one_native_trim_skips_remaining_resources_and_success(self):
        live, pool = self.use_legacy_cuda()
        self.use_universal_cuda(0)
        original = self.cp.pools[0].free_all_blocks
        def stop_after_trim():
            original()
            self.app.stop.set()
        with patch.object(self.cp.pools[0], 'free_all_blocks', side_effect=stop_after_trim):
            self.clear_and_drain()
        self.assertEqual([item.clears for item in self.cp.pools], [1, 0])
        self.assertEqual(self.cp.pinned.clears, 0)
        self.assertEqual(pool.used_bytes(), live.nbytes)
        self.assertEqual(self.app.status.get(), 'Stopped.')

    def test_busy_profile_clear_and_shutdown_guards_do_not_touch_resources_or_stop(self):
        live, pool = self.use_legacy_cuda()
        self.app.stop.set()
        for name, blocked in (('activity', 'draw'), ('pending_clear_drawing', object()),
                              ('profile_change_after', 'after-token'), ('closing', True)):
            with self.subTest(name=name), patch.object(self.app, name, blocked):
                self.assertFalse(self.app.clear_gpu_cache())
                self.assertIsNone(self.app.worker)
                self.assertTrue(self.app.stop.is_set())
        self.assertEqual(pool.clears, 0)
        self.assertEqual(pool.used_bytes(), live.nbytes)


if __name__ == '__main__':
    unittest.main()
