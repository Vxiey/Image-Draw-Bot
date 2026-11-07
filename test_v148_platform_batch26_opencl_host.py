"""Real palette callers at a typed, portable OpenCL transfer/kernel boundary.

The facade supplies numerical results on the host. It does not measure or claim
physical OpenCL execution; production routing, buffering, tiling, fallback and
ownership are real, and the unchanged kernel's complete arguments are observed.
"""
from contextlib import ExitStack, closing, contextmanager
import hashlib
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageDraw

import DrawBot
import UniversalGpuAcceleration as gpu
import UniversalHardwareBenchmark as hardware
from test_gpu_execution_regressions import FakeCupy
from test_pixel_accuracy_engine_v1088 import options
from test_v148_platform_batch22_numeric_ownership import retained_error
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch17_layered_diagnostics import calibrated


PALETTE = ((0, 0, 0), (255, 255, 255), (220, 30, 30), (0, 80, 205), (0, 0, 0))


def measured_profile(backend='opencl:0:0'):
    """Only palette matching prefers the given backend; other work stays CPU."""
    return {'version': 1, 'workload_preferences': {
        'palette_match': {'backend_id': backend, 'backend': 'OpenCL' if backend.startswith('opencl:') else 'CUDA/CuPy',
                          'vendor': 'controlled', 'device': 'typed host boundary',
                          'min_pixels': 0, 'reason': 'controlled measured preference'}},
        'scores_large': []}


def array_evidence(value):
    return (value.dtype.str, value.shape, value.nbytes, hashlib.sha256(value.tobytes()).hexdigest())


def kernel_reference(raw, palette, lab, ids, custom, *, perceptual, fidelity, custom_first, skip_white,
                     numeric=gpu):
    """Supply deterministic output at the native boundary, without host prep.

This uses the established numeric cost model and the kernel's raw-RGBA input,
not the production caller's _rgba_visible_rgb result. Driver/kernel arithmetic
remains separately covered by the existing optional physical-device tests.
"""
    alpha = raw[:, 3:4]
    rgb = (raw[:, :3] * alpha + np.float32(255) * (np.float32(255) - alpha)) / np.float32(255)
    visible = alpha[:, 0] > 0
    if skip_white:
        visible &= rgb.min(axis=1) < 245
    cost = numeric._palette_cost_cpu(rgb, palette, perceptual=bool(perceptual),
                                    fidelity=('Off', 'Balanced', 'Faithful')[fidelity],
                                    pal_lab=lab if perceptual else None)
    selected = cost.argmin(axis=1)
    if custom_first:
        custom_cost = np.where(custom.astype(bool), cost, np.inf)
        preferred = custom_cost.argmin(axis=1)
        selected = np.where(custom_cost.min(axis=1) <= cost.min(axis=1) * 1.06 + .0006,
                            preferred, selected)
    return ids[selected].astype(np.int16), visible.astype(np.uint8)


class TypedOpenCL:
    """Typed transfer facade; it stores no strong reference to native buffers."""
    def __init__(self, *, numeric=gpu, failure=None, stop=None, record=True):
        self.numeric, self.failure, self.stop, self.record = numeric, failure, stop, record
        self.context, self.queue = object(), object()
        self.mem_flags = SimpleNamespace(READ_ONLY=1, WRITE_ONLY=2, COPY_HOST_PTR=4)
        self.events, self.uploads, self.calls = [], [], []
        self.references, self.downloads = [], []
        owner = self

        class Buffer:
            def __init__(self, context, flags, size=None, hostbuf=None):
                assert context is owner.context
                self.flags = flags
                if hostbuf is not None:
                    assert flags == 5 and size is None
                    assert isinstance(hostbuf, np.ndarray) and hostbuf.flags.c_contiguous
                    self.data = hostbuf.view(np.uint8).reshape(-1).copy()
                    if owner.record:
                        owner.events.append(('buffer-host', flags, array_evidence(hostbuf)))
                else:
                    assert flags in (1, 2) and type(size) is int and size > 0
                    self.data = np.empty(size, dtype=np.uint8)
                    if owner.record:
                        owner.events.append(('buffer-empty', flags, size))
                owner.references.append(weakref.ref(self))

        self.Buffer = Buffer
        self.program = SimpleNamespace(ds_palette_kernel=self.palette_kernel)
        self.native = (self, self.context, self.queue, self.program)

    def enqueue_copy(self, queue, destination, source, *, is_blocking):
        assert queue is self.queue and is_blocking is True
        if isinstance(destination, self.Buffer):
            assert destination.flags == 1
            assert isinstance(source, np.ndarray) and source.dtype == np.float32
            assert source.flags.c_contiguous and source.ndim == 2 and source.shape[1] == 4
            assert source.nbytes <= destination.data.nbytes
            destination.data[:source.nbytes] = source.view(np.uint8).reshape(-1)
            if self.record:
                self.uploads.append(source.tobytes())
                self.events.append(('upload', array_evidence(source)))
        else:
            assert isinstance(source, self.Buffer) and source.flags == 2
            assert isinstance(destination, np.ndarray) and destination.flags.c_contiguous
            assert destination.dtype in (np.dtype(np.int16), np.dtype(np.uint8))
            destination.view(np.uint8).reshape(-1)[:] = source.data[:destination.nbytes]
            self.downloads.append(weakref.ref(destination))
            if self.record:
                self.events.append(('download', array_evidence(destination)))

    def palette_kernel(self, queue, global_size, local_size, rgba, palette, lab, ids, custom,
                       output, visible, n, count, perceptual, fidelity, custom_first, skip_white):
        assert queue is self.queue and local_size is None
        scalars = (n, count, perceptual, fidelity, custom_first, skip_white)
        assert all(type(value) is np.int32 for value in scalars)
        n, count, perceptual, fidelity, custom_first, skip_white = map(int, scalars)
        assert global_size == (n,) and n > 0 and count > 0
        assert perceptual in (0, 1) and fidelity in (0, 1, 2)
        assert custom_first in (0, 1) and skip_white in (0, 1)
        assert [value.flags for value in (rgba, palette, lab, ids, custom, output, visible)] == [1, 5, 5, 5, 5, 2, 2]
        assert palette.data.nbytes == lab.data.nbytes == count * 16
        assert ids.data.nbytes == count * 2 and custom.data.nbytes == count
        assert rgba.data.nbytes >= n * 16 and output.data.nbytes >= n * 2 and visible.data.nbytes >= n
        self.calls.append((n, count, perceptual, fidelity, custom_first, skip_white))
        if self.stop is not None:
            self.stop.set()
        if self.failure is not None:
            raise self.failure
        raw = rgba.data.view(np.float32).reshape(-1, 4)[:n]
        pal = palette.data.view(np.float32).reshape(count, 4)
        plab = lab.data.view(np.float32).reshape(count, 4)
        np.testing.assert_array_equal(pal[:, 3], 1)
        np.testing.assert_array_equal(plab[:, 3], 1)
        result, mask = kernel_reference(raw, pal[:, :3], plab[:, :3], ids.data.view(np.int16),
            custom.data, perceptual=perceptual, fidelity=fidelity,
            custom_first=custom_first, skip_white=skip_white, numeric=self.numeric)
        output.data[:n * 2] = result.view(np.uint8)
        visible.data[:n] = mask


@contextmanager
def observed_host(module=gpu):
    events = []
    original = module._rgba_visible_rgb
    def observe(raw):
        result = original(raw)
        events.append({'raw_shape': raw.shape, 'rgb_bytes': result[0].nbytes,
                       'visible_bytes': result[1].nbytes,
                       'rgb': weakref.ref(result[0]), 'visible': weakref.ref(result[1])})
        return result
    with patch.object(module, '_rgba_visible_rgb', new=observe):
        yield events


def pixel_source(size=(48, 32)):
    image = Image.new('RGBA', size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle((3, 3, w // 2, h - 4), fill=(220, 30, 30, 255), outline=(0, 0, 0, 255))
    draw.rectangle((w // 2 + 2, 5, w - 4, h - 6), fill=(0, 80, 205, 128))
    draw.rectangle((w - 8, h - 8, w - 3, h - 3), fill=(0, 0, 0, 0))
    image.info['draw_studio_format'] = 'PNG'
    return image


def public_plan_settings(mode='Auto'):
    return options(profile_name='Microsoft Paint', profile_key='microsoft-paint',
        render_preset='Manual', drawing_style='Auto', auto_engine_resolved=True,
        draw_quality='Pixel Accurate', planning_resolution='Standard', gpu_mode=mode,
        portrait_focus=False, detail_zoom='Off', progressive_rendering='Off',
        color_workflow='Finish color first', time_budget_mode='Unlimited', unlimited_time=True,
        adaptive_deadline_renderer=False, _execution_cost_calibration_override={},
        cpu_workers='1', cpu_workers_resolved=1, ram_budget_mb=2048,
        available_ram_mb=8192, logical_cpus=4, preview_plan=False)


def public_plan(source, mode='Auto'):
    return DrawBot.make_plan(source, source.size, public_plan_settings(mode))


class OpenCLHostPreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('_FAILED', '_OPENCL_CACHE', '_OPENCL_IN_USE'):
            self.stack.enter_context(patch.object(gpu, name, {}))

    def assert_output(self, actual, expected):
        for left, right in zip(actual, expected):
            self.assertEqual(left.dtype, right.dtype)
            np.testing.assert_array_equal(left, right)

    def test_successful_opencl_uses_raw_rgba_without_an_unused_host_composite(self):
        raw = np.array([[[0, 0, 0, 0], [0, 0, 0, 1], [12, 70, 200, 128],
                         [255, 255, 255, 254], [244, 244, 244, 255], [245, 245, 245, 255],
                         [0, 0, 0, 255], [220, 30, 30, 255]]], dtype=np.uint8)
        candidates, flags = (4, 4, 2, 3, 1, 0), (False, False, True, False, True)
        with closing(Image.fromarray(raw)) as source:
            before = source.tobytes()
            for rendering, fidelity, skip, first in (
                    ('RGB nearest', 'Fast', True, False), ('RGB nearest', 'Faithful', False, True),
                    ('Perceptual match', 'Balanced', True, True), ('Perceptual match', 'Faithful', False, False)):
                settings = dict(color_rendering=rendering, color_fidelity=fidelity, skip_white=skip,
                                custom_mode='Custom colors first' if first else 'Calibrated palette')
                expected, _ = gpu.palette_indices_rgba(source, PALETTE, candidates, flags, gpu_mode='CPU', **settings)
                boundary = TypedOpenCL()
                with patch.object(gpu, '_opencl_context', return_value=boundary.native), observed_host() as host:
                    actual, metadata = gpu.palette_indices_rgba(source, PALETTE, candidates, flags,
                        profile=measured_profile(), **settings)
                self.assert_output(actual, expected)
                self.assertEqual(metadata, gpu.select_route('palette_match', pixels=source.width * source.height,
                                                            profile=measured_profile()).as_dict())
                self.assertEqual(b''.join(boundary.uploads), raw.astype(np.float32).tobytes())
                self.assertEqual(boundary.calls[0][:2], (8, 5))
                self.assertEqual(source.tobytes(), before)
                self.assertEqual(gpu._OPENCL_IN_USE, {})
                self.assertTrue(all(reference() is None for reference in boundary.references))
                self.assertEqual(len(host), 0, 'Successful OpenCL must not allocate an unused full RGB/visibility pair')

    def test_actual_public_pixel_plan_keeps_all_rasters_and_does_no_opencl_host_preparation(self):
        boundary = TypedOpenCL()
        with calibrated(PALETTE), closing(pixel_source()) as source, \
                patch.object(hardware, 'load_hardware_profile', return_value=measured_profile()):
            before = source.tobytes(), dict(source.info)
            cpu = public_plan(source, 'CPU')
            plan = None
            try:
                with patch.object(gpu, '_opencl_context', return_value=boundary.native), observed_host() as host:
                    plan = public_plan(source)
                self.assertTrue(boundary.calls, 'The complete public plan must reach the real OpenCL branch')
                for key in ('colors', 'color_selectors', 'groups', 'execution_groups', 'execution_sequence', 'count'):
                    self.assertEqual(plan[key], cpu[key], key)
                for key in ('image', 'preview'):
                    self.assertEqual(plan[key].tobytes(), cpu[key].tobytes(), key)
                self.assertEqual(set(plan['ui_previews']), set(cpu['ui_previews']))
                for key in plan['ui_previews']:
                    self.assertEqual(plan['ui_previews'][key].tobytes(), cpu['ui_previews'][key].tobytes(), key)
                self.assertEqual((source.tobytes(), source.info), before)
                self.assertEqual(len(host), 0, 'Actual OpenCL planning still prepared a full unused host image')
            finally:
                close_plan(plan, source)
                close_plan(cpu, source)

    def test_opencl_chunks_keep_tail_bytes_and_typed_outputs(self):
        raw = np.zeros((513, 512, 4), dtype=np.uint8)
        raw[..., 3] = 255
        raw[::7, ::3] = (255, 255, 255, 0)
        boundary = TypedOpenCL()
        palette = PALETTE[:2]
        with closing(Image.fromarray(raw)) as source, \
                patch.object(gpu, '_opencl_context', return_value=boundary.native), observed_host() as host:
            (indices, visible), meta = gpu.palette_indices_rgba(source, palette, (), (),
                color_rendering='RGB nearest', skip_white=False, profile=measured_profile())
        self.assertEqual([row[0] for row in boundary.calls], [262144, 512])
        self.assertEqual(b''.join(boundary.uploads), raw.astype(np.float32).tobytes())
        np.testing.assert_array_equal(indices, np.where(raw[..., 3] == 0, 1, 0))
        np.testing.assert_array_equal(visible, raw[..., 3] > 0)
        self.assertEqual(indices.dtype, np.int16)
        self.assertEqual(visible.dtype, np.bool_)
        self.assertTrue(meta['accelerated'])
        self.assertEqual(len(host), 0)

    def test_cpu_mode_prepares_once_and_never_attempts_a_native_backend(self):
        with closing(pixel_source()) as source, observed_host() as host, \
                patch.object(gpu, '_opencl_context', side_effect=AssertionError('CPU opened a device')):
            result, metadata = gpu.palette_indices_rgba(source, PALETTE, (), (),
                gpu_mode='CPU', profile=measured_profile())
            self.assertEqual(len(host), 1)
            self.assertIs(result[1], host[0]['visible']())
            self.assertFalse(metadata['accelerated'])
            self.assertEqual(metadata['backend_id'], 'cpu:numpy')
            self.assertIsNone(host[0]['rgb']())

    def test_cuda_host_pixels_exist_before_the_native_exception_boundary(self):
        cp, events = FakeCupy(), []
        run, host_original = gpu._run_accelerated, gpu._rgba_visible_rgb
        def prepare(raw):
            events.append('host')
            return host_original(raw)
        def attempt(*args):
            events.append('attempt')
            return run(*args)
        def match(provider, rgb, pal, lab, ids, flags, **settings):
            self.assertIs(provider, cp)
            self.assertEqual(cp.current_device(), 1)
            self.assertEqual(events, ['host', 'attempt'])
            self.assertEqual(rgb.dtype, np.float32)
            cost = gpu._palette_cost_cpu(rgb, pal, perceptual=settings['perceptual'],
                                        fidelity=('Off', 'Balanced', 'Faithful')[settings['fidelity']], pal_lab=lab)
            return ids[cost.argmin(axis=-1)]
        with closing(pixel_source()) as source:
            expected, _ = gpu.palette_indices_rgba(source, PALETTE, (), (), gpu_mode='CPU')
            with patch.dict(sys.modules, {'cupy': cp}), patch('CudaPalette.match', new=match), \
                    patch.object(gpu, '_rgba_visible_rgb', new=prepare), \
                    patch.object(gpu, '_run_accelerated', new=attempt):
                actual, metadata = gpu.palette_indices_rgba(source, PALETTE, (), (), profile=measured_profile('cuda:1'))
            self.assert_output(actual, expected)
            self.assertEqual(metadata['backend_id'], 'cuda:1')
            self.assertEqual(events, ['host', 'attempt'])
            self.assertEqual(cp.current_device(), 0)

    def test_cuda_host_memory_error_never_quarantines_or_enters_native_attempt(self):
        failure, owners = MemoryError('host composite allocation failed'), []
        original = gpu._rgba_visible_rgb
        def prepare(raw):
            rgb, visible = original(raw)
            owners.extend((weakref.ref(raw), weakref.ref(rgb), weakref.ref(visible)))
            raise failure
        with closing(pixel_source()) as source, patch.object(gpu, '_rgba_visible_rgb', new=prepare), \
                patch.object(gpu, '_run_accelerated') as attempted:
            error = retained_error(lambda: gpu.palette_indices_rgba(source, PALETTE, (), (),
                profile=measured_profile('cuda:1')))
            self.assertIs(error, failure)
            attempted.assert_not_called()
            self.assertEqual(gpu.backend_health_snapshot(), {})
            self.assertTrue(all(reference() is None for reference in owners))
            source.getpixel((0, 0))

    def test_actual_cuda_host_failure_is_not_retried_as_native_then_cpu_work(self):
        failure, owners, events = MemoryError('host allocation failed'), [], []
        original_host, original_run = gpu._rgba_visible_rgb, gpu._run_accelerated
        def prepare(raw):
            events.append('host')
            rgb, visible = original_host(raw)
            owners.extend(weakref.ref(value) for value in (raw, rgb, visible))
            raise failure
        def attempt(*args):
            events.append('native-boundary')
            return original_run(*args)
        def unexpected_match(*args, **kwargs):
            events.append('cuda-match')
            raise AssertionError('Host allocation failed before CUDA matching')
        with closing(pixel_source()) as source, \
                patch.dict(sys.modules, {'cupy': FakeCupy()}), \
                patch.object(gpu, '_rgba_visible_rgb', new=prepare), \
                patch.object(gpu, '_run_accelerated', new=attempt), \
                patch('CudaPalette.match', new=unexpected_match):
            original = source.tobytes(), dict(source.info)
            error = retained_error(lambda: gpu.palette_indices_rgba(source, PALETTE, (), (),
                profile=measured_profile('cuda:1')))
            self.assertIs(error, failure)
            self.assertIsNotNone(error.__traceback__)
            self.assertEqual(events, ['host'],
                'A host allocation failure must not enter native fallback or prepare twice')
            self.assertEqual(gpu.backend_health_snapshot(), {})
            self.assertEqual(len(owners), 3)
            self.assertTrue(all(reference() is None for reference in owners))
            self.assertEqual((source.tobytes(), source.info), original)

    def test_stop_during_actual_route_selection_prevents_host_preparation(self):
        for mode, backend in (('CPU', 'opencl:0:0'), ('Auto', 'cuda:1')):
            with self.subTest(mode=mode, backend=backend), closing(pixel_source()) as source:
                stopped, events = threading.Event(), []
                original_route, original_run = gpu.select_route, gpu._run_accelerated
                def route(*args, **kwargs):
                    result = original_route(*args, **kwargs)
                    events.append(('route', result.backend_id))
                    stopped.set()
                    return result
                def attempt(*args):
                    events.append(('native-boundary', args[0].backend_id))
                    return original_run(*args)
                original = source.tobytes(), dict(source.info)
                with patch.object(gpu, 'select_route', new=route), \
                        patch.object(gpu, '_run_accelerated', new=attempt), \
                        observed_host() as host:
                    error = retained_error(lambda: gpu.palette_indices_rgba(source, PALETTE, (), (),
                        gpu_mode=mode, profile=measured_profile(backend), cancelled=stopped.is_set))
                self.assertIsInstance(error, InterruptedError)
                self.assertEqual(len(host), 0)
                self.assertEqual(events, [('route', 'cpu:numpy' if mode == 'CPU' else 'cuda:1')])
                self.assertEqual(gpu.backend_health_snapshot(), {})
                self.assertEqual((source.tobytes(), source.info), original)

    def test_failed_opencl_releases_native_work_before_one_fresh_cpu_preparation(self):
        for failure in (RuntimeError('native driver error'), MemoryError('native allocation pressure')):
            with self.subTest(failure=type(failure).__name__), patch.object(gpu, '_FAILED', {}), \
                    closing(pixel_source()) as source:
                expected, _ = gpu.palette_indices_rgba(source, PALETTE, (), (), gpu_mode='CPU')
                boundary = TypedOpenCL(failure=failure)
                original, events = gpu._rgba_visible_rgb, []
                def prepare(raw):
                    events.append('host')
                    self.assertTrue(boundary.calls, 'CPU preparation ran before the actual native attempt failed')
                    self.assertTrue(all(reference() is None for reference in boundary.references))
                    self.assertEqual(gpu._OPENCL_IN_USE, {})
                    return original(raw)
                with patch.object(gpu, '_opencl_context', return_value=boundary.native), \
                        patch.object(gpu, '_rgba_visible_rgb', new=prepare):
                    actual, metadata = gpu.palette_indices_rgba(source, PALETTE, (), (), profile=measured_profile())
                self.assert_output(actual, expected)
                self.assertEqual(events, ['host'])
                self.assertFalse(metadata['accelerated'])
                self.assertIn(str(failure), metadata['reason'])
                self.assertEqual(bool(gpu.backend_health_snapshot()), isinstance(failure, RuntimeError))
                self.assertIsNotNone(failure.__traceback__)

    def test_host_preparation_failure_releases_private_inputs_on_cpu_and_native_fallback(self):
        for mode in ('CPU', 'Auto'):
            with self.subTest(mode=mode), patch.object(gpu, '_FAILED', {}), closing(pixel_source()) as source:
                failure, owners = MemoryError('CPU host allocation failed'), []
                boundary = TypedOpenCL(failure=RuntimeError('native failed first'))
                original = gpu._rgba_visible_rgb
                def prepare(raw):
                    rgb, visible = original(raw)
                    owners.extend(weakref.ref(value) for value in (raw, rgb, visible))
                    raise failure
                with patch.object(gpu, '_opencl_context', return_value=boundary.native), \
                        patch.object(gpu, '_rgba_visible_rgb', new=prepare):
                    error = retained_error(lambda: gpu.palette_indices_rgba(source, PALETTE, (), (),
                        gpu_mode=mode, profile=measured_profile()))
                self.assertIs(error, failure)
                self.assertEqual(len(owners), 3)
                self.assertTrue(all(reference() is None for reference in owners))
                self.assertTrue(all(reference() is None for reference in boundary.references))
                self.assertEqual(bool(boundary.calls), mode == 'Auto')
                health = gpu.backend_health_snapshot()
                self.assertEqual(health, {'opencl:0:0|palette_match': 'RuntimeError: native failed first'}
                                 if mode == 'Auto' else {})
                self.assertEqual(gpu._OPENCL_IN_USE, {})
                source.getpixel((0, 0))

    def test_stop_before_work_at_native_failure_or_after_download_never_prepares_host_pixels(self):
        for kind in ('before', 'interrupt', 'failed', 'completed'):
            with self.subTest(stop=kind), patch.object(gpu, '_FAILED', {}), closing(pixel_source()) as source:
                stop = threading.Event()
                failure = InterruptedError('native Stop') if kind == 'interrupt' else (
                    RuntimeError('failed together with Stop') if kind == 'failed' else None)
                boundary = TypedOpenCL(failure=failure, stop=stop)
                if kind == 'before':
                    stop.set()
                with patch.object(gpu, '_opencl_context', return_value=boundary.native) as opened, \
                        observed_host() as host:
                    error = retained_error(lambda: gpu.palette_indices_rgba(source, PALETTE, (), (),
                        profile=measured_profile(), cancelled=stop.is_set))
                self.assertIsInstance(error, InterruptedError)
                self.assertEqual(len(host), 0)
                self.assertEqual(gpu._OPENCL_IN_USE, {})
                self.assertTrue(all(reference() is None for reference in boundary.references + boundary.downloads))
                if kind == 'before':
                    opened.assert_not_called()
                if kind == 'interrupt':
                    self.assertIs(error, failure)
                    self.assertEqual(gpu.backend_health_snapshot(), {})
                source.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
