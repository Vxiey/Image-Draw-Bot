"""Parallel palette readers keep only bounded task payloads and owned images."""
from contextlib import contextmanager, closing
import inspect
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdvancedColor
import DrawBot
import PixelData
import ResourceAllocation
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch17_layered_diagnostics import calibrated, plan_options


def graphic(size=(256, 196), mode='RGBA'):
    width, height = size
    data = np.full((height, width, 4), (35, 35, 35, 255), np.uint8)
    data[:, width//3:2*width//3] = (210, 210, 210, 255)
    data[height//3:2*height//3, width//4:3*width//4] = (25, 25, 25, 128)
    data[::11, ::7] = (230, 20, 90, 0)
    image = Image.fromarray(data)
    if mode == 'RGBA':
        return image
    with closing(image):
        return image.convert(mode)


def build(kind, source, *, workers=2, engine='Threads', cancelled=lambda: False):
    common = dict(lines=True, skip_white=False, cpu_workers=workers,
                  cpu_engine=engine, cancelled=cancelled)
    if kind == 'basic':
        return PixelData.build_strokes(source, **common), None
    return AdvancedColor.build_color_strokes(source, color_rendering='Layered color mix',
        color_layers='Full color mix', color_fidelity='Balanced', gpu_mode='CPU', **common)


@contextmanager
def dispatch_observations():
    """Observe actual work resident before the real scheduler consumes tasks."""
    rows = []
    mapper = ResourceAllocation.parallel_map

    def observe(function, tasks, **kwargs):
        frame = inspect.currentframe().f_back
        try:
            while frame is not None and frame.f_code.co_name not in (
                    '_parallel_color_strokes', '_parallel_basic_strokes'):
                frame = frame.f_back
            if frame is not None:
                locals_ = frame.f_locals
                raw = locals_.get('raw')
                payloads = ({id(raw): len(raw)} if isinstance(raw, bytes) else {})
                if isinstance(tasks, (list, tuple)):
                    payloads.update({id(task[2]): len(task[2]) for task in tasks
                                     if isinstance(task[2], bytes)})
                image = next((locals_.get(name) for name in ('rgb_image', 'rgba', 'image')
                              if isinstance(locals_.get(name), Image.Image)), None)
                rows.append({'caller': frame.f_code.co_name, 'size': image.size,
                             'eager_payload_bytes': sum(payloads.values()),
                             'tasks': len(tasks), 'backend': kwargs['backend']})
        finally:
            del frame
        return mapper(function, tasks, **kwargs)

    with patch.object(ResourceAllocation, 'parallel_map', side_effect=observe):
        yield rows


@contextmanager
def copied_images(size):
    owned = []
    copy = Image.Image.copy
    convert = Image.Image.convert

    def retain(image, result):
        if result is not image and result.size == size and all(result is not item for item in owned):
            owned.append(result)
        return result

    def observe(image):
        result = copy(image)
        return retain(image, result)

    def converted(image, *args, **kwargs):
        return retain(image, convert(image, *args, **kwargs))

    with patch.object(Image.Image, 'copy', observe), patch.object(Image.Image, 'convert', converted):
        yield owned


def public_options(kind, resolution):
    options = plan_options()
    options.update(planning_resolution=resolution, cpu_workers='4', cpu_workers_resolved=4,
        cpu_engine='Threads', ram_budget_mb=512, resource_scheduler='Off',
        color_layers='Off', color_rendering='RGB nearest' if kind == 'basic' else 'Perceptual match',
        color_fidelity='Fast' if kind == 'basic' else 'Balanced')
    return options


class RowPayloadTests(unittest.TestCase):
    def test_parallel_rgba_input_is_borrowed_without_whole_image_copies(self):
        with calibrated(), closing(graphic()) as source:
            original = source.tobytes()
            for kind in ('basic', 'advanced'):
                with self.subTest(kind=kind), copied_images(source.size) as copies:
                    groups, _metadata = build(kind, source)
                    self.assertTrue(any(groups))
                    self.assertEqual(len(copies), 0, 'Read-only RGBA input needs no whole-image copies')
                    self.assertEqual(source.tobytes(), original)

    def test_dispatch_does_not_retain_whole_raw_and_all_row_payloads(self):
        with calibrated(), closing(graphic()) as source:
            for kind in ('basic', 'advanced'):
                with self.subTest(kind=kind), dispatch_observations() as rows:
                    groups, _metadata = build(kind, source)
                    self.assertTrue(any(groups))
                    self.assertEqual(len(rows), 1)
                    self.assertGreater(rows[0]['tasks'], 1)
                    self.assertEqual(rows[0]['size'], source.size)
                    self.assertEqual(rows[0]['backend'], 'threads')
                    self.assertEqual(rows[0]['eager_payload_bytes'], 0)

    def test_actual_serial_threads_and_processes_preserve_complete_results(self):
        with calibrated(), closing(graphic()) as source:
            original = source.tobytes()
            for kind in ('basic', 'advanced'):
                expected, expected_meta = build(kind, source, workers=1)
                for engine in ('Threads', 'Processes'):
                    with self.subTest(kind=kind, engine=engine), dispatch_observations() as rows:
                        actual, metadata = build(kind, source, engine=engine)
                        self.assertEqual(actual, expected)
                        self.assertEqual(rows[0]['backend'], engine.lower())
                        if metadata is not None:
                            self.assertEqual(metadata['cpu_backend'], engine.lower())
                            self.assertGreater(metadata['cpu_chunks'], 1)
                            self.assertEqual({k:v for k,v in metadata.items() if k not in ('cpu_backend','cpu_chunks')},
                                             {k:v for k,v in expected_meta.items() if k not in ('cpu_backend','cpu_chunks')})
                        self.assertEqual(source.tobytes(), original)

    def test_rgb_worker_failure_falls_back_and_closes_private_images_with_retained_traceback(self):
        with calibrated(), closing(graphic(mode='RGB')) as source:
            original = source.tobytes()
            for kind in ('basic', 'advanced'):
                expected, _ = build(kind, source, workers=1)
                retained = []
                def failed(*args, **kwargs):
                    try:
                        raise RuntimeError('worker failure before result')
                    except RuntimeError as error:
                        retained.append(error)
                        raise
                with self.subTest(kind=kind), copied_images(source.size) as copies, \
                        patch.object(ResourceAllocation, 'parallel_map', side_effect=failed):
                    groups, metadata = build(kind, source)
                    self.assertEqual(groups, expected)
                    if metadata is not None:
                        self.assertEqual(metadata['cpu_backend'], 'serial')
                    self.assertTrue(retained[0].__traceback__)
                    self.assertTrue(copies)
                    for private in copies:
                        with self.assertRaises(ValueError):
                            private.getpixel((0, 0))
                    self.assertEqual(source.tobytes(), original)

    def test_stop_during_parallel_dispatch_never_returns_partial_groups_or_closes_source(self):
        with calibrated(), closing(graphic(mode='RGB')) as source:
            original = source.tobytes()
            for kind in ('basic', 'advanced'):
                kept = []
                def stopped(*args, **kwargs):
                    try:
                        raise InterruptedError('stop inside scheduler')
                    except InterruptedError as error:
                        kept.append(error)
                        raise
                with self.subTest(kind=kind), copied_images(source.size) as copies, \
                        patch.object(ResourceAllocation, 'parallel_map', side_effect=stopped):
                    try:
                        build(kind, source)
                    except InterruptedError as error:
                        self.assertIs(error, kept[0])
                    else:
                        self.fail('Stop must not publish a partial group list')
                    self.assertTrue(kept[0].__traceback__)
                    self.assertTrue(copies)
                    for private in copies:
                        with self.assertRaises(ValueError):
                            private.getpixel((0, 0))
                    self.assertEqual(source.tobytes(), original)

    def test_actual_high_and_ultra_public_planners_reach_the_bounded_payload_path(self):
        with calibrated(), closing(graphic((768, 512))) as source:
            original = source.tobytes()
            for kind in ('basic', 'advanced'):
                for resolution in ('High', 'Ultra'):
                    with self.subTest(kind=kind, resolution=resolution), dispatch_observations() as rows:
                        plan = DrawBot.make_plan(source, source.size, public_options(kind, resolution))
                        try:
                            self.assertGreater(plan['count'], 0)
                            self.assertEqual(plan['options']['planning_resolution_effective'], resolution)
                            self.assertEqual(len(rows), 1)
                            self.assertGreater(rows[0]['size'][0] * rows[0]['size'][1], 48_000)
                            self.assertEqual(rows[0]['backend'], 'threads')
                            self.assertEqual(rows[0]['eager_payload_bytes'], 0)
                            self.assertEqual(source.tobytes(), original)
                        finally:
                            close_plan(plan, source)

    def test_blocked_real_workers_bound_exports_and_stop_discards_pending_work(self):
        with calibrated(), closing(graphic((64, 2048))) as source:
            original = source.tobytes()
            for kind, module, worker_name in (
                    ('basic', PixelData, '_basic_rows_worker'),
                    ('advanced', AdvancedColor, '_color_rows_worker')):
                with self.subTest(kind=kind):
                    ready, release, stop = threading.Event(), threading.Event(), threading.Event()
                    crops, payloads, outcomes = [], [], []
                    crop, worker = Image.Image.crop, getattr(module, worker_name)
                    def export(image, box=None):
                        result = crop(image, box)
                        if image is source:
                            crops.append(result)
                            if len(crops) == 4:
                                ready.set()
                        return result
                    def blocked(task):
                        payloads.append(task[2])
                        if not release.wait(5):
                            raise AssertionError('Test did not release the real worker.')
                        return worker(task)
                    def plan():
                        try:
                            outcomes.append(build(kind, source, cancelled=stop.is_set))
                        except BaseException as error:
                            outcomes.append(error)
                    with patch.object(Image.Image, 'crop', new=export), \
                            patch.object(module, worker_name, new=blocked):
                        thread = threading.Thread(target=plan)
                        thread.start()
                        try:
                            self.assertTrue(ready.wait(5), 'The real mapper must reach its four-task bound.')
                            self.assertEqual(len(crops), 4)
                            self.assertTrue(all(isinstance(payload, bytes) for payload in payloads))
                            # The fourth crop has signalled before its context manager
                            # exits; the first three already reached worker submission.
                            for private in crops[:3]:
                                with self.assertRaises(ValueError):
                                    private.getpixel((0, 0))
                            stop.set()
                        finally:
                            release.set()
                            thread.join(5)
                        self.assertFalse(thread.is_alive())
                    self.assertEqual(len(outcomes), 1)
                    self.assertIsInstance(outcomes[0], InterruptedError)
                    self.assertEqual(len(crops), 4)
                    for private in crops:
                        with self.assertRaises(ValueError):
                            private.getpixel((0, 0))
                    self.assertEqual(source.tobytes(), original)

    def test_row_export_failure_closes_crop_before_serial_fallback(self):
        with calibrated(), closing(graphic(mode='RGB')) as source:
            for kind in ('basic', 'advanced'):
                with self.subTest(kind=kind):
                    expected, _ = build(kind, source, workers=1)
                    crops, retained = [], []
                    crop, tobytes = Image.Image.crop, Image.Image.tobytes
                    def export(image, box=None):
                        result = crop(image, box)
                        crops.append(result)
                        return result
                    def fail_export(image, *args, **kwargs):
                        if any(image is private for private in crops):
                            try:
                                raise RuntimeError('export failed with a live traceback')
                            except RuntimeError as error:
                                retained.append(error)
                                raise
                        return tobytes(image, *args, **kwargs)
                    with copied_images(source.size) as copies, \
                            patch.object(Image.Image, 'crop', new=export), \
                            patch.object(Image.Image, 'tobytes', new=fail_export):
                        actual, metadata = build(kind, source)
                    self.assertEqual(actual, expected)
                    if metadata is not None:
                        self.assertEqual(metadata['cpu_backend'], 'serial')
                    self.assertTrue(retained[0].__traceback__)
                    self.assertEqual(len(crops), 1)
                    for private in crops + copies:
                        with self.assertRaises(ValueError):
                            private.getpixel((0, 0))
                    self.assertEqual(source.mode, 'RGB')
                    self.assertTrue(source.tobytes())


if __name__ == '__main__':
    unittest.main()
