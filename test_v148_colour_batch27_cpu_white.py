"""The legacy CPU route uses the same source-white contract as Auto/CPU."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import Colors
import DrawBot
import PixelData
import UniversalGpuAcceleration
from test_precision_v102 import Value
from test_v148_ui_batch07_renderer import close_images


GREY_PALETTE = ((0, 0, 0), (240, 240, 240))
WHITE_PALETTE = ((0, 0, 0), (255, 255, 255))


@contextmanager
def calibration(palette=GREY_PALETTE):
    previous = list(Colors.allColors)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        directory = Path(temporary)
        stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
        stack.enter_context(patch('ProfileStorage.data_dir', return_value=directory))
        stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
        stack.enter_context(patch('DrawBot.log_event'))
        # Only the persisted hardware observation is controlled. The actual
        # Auto selector, CPU route and AdvancedColor planner still run.
        stack.enter_context(patch('UniversalHardwareBenchmark.load_hardware_profile', return_value={}))
        path = directory / 'calibration-microsoft-paint.json'
        try:
            Colors.save_calibration([(-400 + 10 * i, -100) for i in range(len(palette))],
                palette, path, names=[f'Swatch {i}' for i in range(len(palette))],
                profile_key='microsoft-paint')
            Colors.load_calibration(path, profile_key='microsoft-paint')
            saved = path.read_bytes()
            yield path, saved
            assert path.read_bytes() == saved
        finally:
            Colors.allColors[:] = previous
            PixelData.closest_color.cache_clear()


def ui_options(*, gpu='CPU', workers=1, skip_white=True, lines=True):
    values = dict(brush_px='1', max_seconds='180', quality='Maximum detail', speed='Normal',
        precision='High', mode='Lines (fastest)' if lines else DrawBot.DOT_MODE,
        render_style='Standard / pixel', game='Microsoft Paint', paint_tool='Use current tool',
        contrast=1.0, portrait_focus=False, skip_white=skip_white, outline=False,
        paint_simple=False, profile_engine='Manual settings', render_preset='Manual',
        gpu_mode=gpu, cpu_workers=str(workers), cpu_engine='Threads', ram_budget='512 MB',
        resource_scheduler='Off', background_fill='Off', use_region_fill_engine=False,
        background_simplification='Off', custom_color_workflow='Calibrated palette',
        detail_zoom='Off', planning_resolution='High', draw_quality='Balanced',
        color_layers='Off', color_rendering='RGB nearest', color_fidelity='Fast',
        adaptive_detail='Off', stroke_optimizer='Off', progressive_rendering='Off',
        color_grouping='Accurate', time_budget_mode='Unlimited',
        adaptive_deadline_renderer=False, visual_verification='Off', planning_watchdog='Off')
    return DrawBot.DrawBotApp.options(SimpleNamespace(**{
        name: Value(value) for name, value in values.items()}))


def source_image(size=(64, 48), *, boundaries=False):
    if not boundaries:
        source = Image.new('RGBA', size, 'white')
        source.paste((0, 0, 0, 255), (20, 12, 28, 24))
        return source
    colors = np.array(((255, 255, 255, 255), (245, 245, 245, 255),
        (244, 244, 244, 255), (244, 255, 255, 255), (240, 240, 240, 128),
        (0, 0, 0, 10), (0, 0, 0, 11), (255, 10, 70, 0),
        (0, 0, 0, 255), (90, 110, 150, 255), (230, 230, 230, 255),
        (250, 244, 250, 255)), dtype=np.uint8)
    width, height = size
    indices = (np.arange(width)[None, :] // 4 + np.arange(height)[:, None] // 8) % len(colors)
    return Image.fromarray(colors[indices])


def reference_labels(source, palette, *, skip_white):
    """Independent integer alpha, source mask and squared-RGB label oracle."""
    raw = np.asarray(source).astype(np.int32)
    alpha = raw[:, :, 3:4]
    visible = (raw[:, :, :3] * alpha + 255 * (255 - alpha) + 127) // 255
    allowed = (alpha[:, :, 0] > 0)
    if skip_white:
        allowed &= np.min(visible, axis=2) < 245
    distances = np.sum((visible[:, :, None, :] - np.asarray(palette)[None, None, :, :]) ** 2, axis=3)
    return np.where(allowed, np.argmin(distances, axis=2), -1).astype(np.int32)


def stroke_labels(source, groups):
    labels = np.full((source.height, source.width), -1, dtype=np.int32)
    covered = np.zeros_like(labels)
    for index, group in enumerate(groups):
        for x0, y0, x1, y1 in group:
            assert y0 == y1 and 0 <= y0 < source.height and 0 <= x0 <= x1 < source.width
            covered[y0, x0:x1 + 1] += 1
            labels[y0, x0:x1 + 1] = index
    assert np.max(covered, initial=0) <= 1
    return labels


def rgb_raster(labels, palette):
    output = np.full((*labels.shape, 3), 255, dtype=np.uint8)
    for index, rgb in enumerate(palette):
        output[labels == index] = rgb
    return output


class CpuSourceWhiteTests(unittest.TestCase):
    def assert_labels(self, source, groups, palette, *, skip_white):
        expected = reference_labels(source, palette, skip_white=skip_white)
        actual = stroke_labels(source, groups)
        np.testing.assert_array_equal(actual >= 0, expected >= 0,
            err_msg='Drawing ownership follows source alpha/white, not the selected swatch.')
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(rgb_raster(actual, palette), rgb_raster(expected, palette))
        return actual

    @contextmanager
    def actual_plan(self, source, *, gpu='CPU', workers=1, skip_white=True, lines=True):
        options = ui_options(gpu=gpu, workers=workers, skip_white=skip_white, lines=lines)
        self.assertEqual((options['gpu_mode'], options['color_rendering'], options['color_fidelity'],
                          options['custom_color_workflow']),
                         (gpu, 'RGB nearest', 'Fast', 'Calibrated palette'))
        self.assertEqual(options['cpu_workers_resolved'], workers)
        source_bytes = source.tobytes()
        routes = []
        real_route = UniversalGpuAcceleration.select_route

        def observe_route(*args, **kwargs):
            route = real_route(*args, **kwargs)
            routes.append(route)
            return route

        plan = None
        with patch('UniversalGpuAcceleration.select_route', side_effect=observe_route), \
                patch('DrawBot.build_strokes', wraps=PixelData.build_strokes) as basic:
            try:
                plan = DrawBot.make_plan(source, source.size, options)
                self.assertEqual(plan['image'].size, source.size)
                self.assertEqual(source.tobytes(), source_bytes)
                self.assertEqual(basic.call_count, int(gpu == 'CPU'))
                if gpu == 'Auto':
                    palette_routes = [route for route in routes if route.workload == 'palette_match']
                    self.assertTrue(palette_routes)
                    self.assertTrue(all(not route.accelerated and route.backend_id == 'cpu:numpy'
                                        for route in palette_routes))
                yield plan
            finally:
                close_images(plan)
                self.assertEqual(source.tobytes(), source_bytes)

    def test_public_cpu_plan_preserves_white_background_without_a_white_swatch(self):
        with calibration(), source_image() as source:
            for gpu in ('CPU', 'Auto'):
                with self.subTest(gpu=gpu), self.actual_plan(source, gpu=gpu) as plan:
                    labels = self.assert_labels(source, plan['groups'], GREY_PALETTE, skip_white=True)
                    self.assertEqual(int(np.count_nonzero(labels >= 0)), 96)
                    self.assertEqual(int(labels[0, 0]), -1)

    def test_public_threads_really_run_and_match_source_mask(self):
        real_worker = PixelData._basic_rows_worker
        seen = []

        def observe(task):
            seen.append((threading.get_ident(), task[0]))
            return real_worker(task)

        with calibration(), source_image((256, 192)) as source:
            for gpu, workers in (('CPU', 1), ('CPU', 2), ('Auto', 2)):
                with self.subTest(gpu=gpu, workers=workers), \
                        patch('PixelData._basic_rows_worker', side_effect=observe), \
                        self.actual_plan(source, gpu=gpu, workers=workers) as plan:
                    if gpu == 'CPU' and workers == 2:
                        self.assertGreater(len(seen), 1)
                        self.assertTrue(all(ident != threading.get_ident() for ident, _ in seen))
                        self.assertGreater(len({y for _, y in seen}), 1)
                    self.assert_labels(source, plan['groups'], GREY_PALETTE, skip_white=True)

    def test_public_alpha_and_threshold_use_composited_source_rgb(self):
        with calibration(), source_image((80, 32), boundaries=True) as source:
            for gpu in ('CPU', 'Auto'):
                with self.subTest(gpu=gpu), self.actual_plan(source, gpu=gpu) as plan:
                    self.assert_labels(source, plan['groups'], GREY_PALETTE, skip_white=True)
                    self.assertTrue(plan['options']['source_transparency_meta']['zero_alpha_excluded'])

    def test_public_skip_disabled_keeps_white_but_excludes_alpha_zero(self):
        with calibration(), source_image((256, 192), boundaries=True) as source:
            for gpu, workers in (('CPU', 1), ('CPU', 2), ('Auto', 2)):
                with self.subTest(gpu=gpu, workers=workers), \
                        self.actual_plan(source, gpu=gpu, workers=workers, skip_white=False) as plan:
                    labels = self.assert_labels(source, plan['groups'], GREY_PALETTE, skip_white=False)
                    self.assertEqual(int(labels[0, 0]), 1)
                    self.assertTrue(np.any(labels < 0))

    def test_nonwhite_pixels_mapped_to_white_still_have_strokes(self):
        with calibration(WHITE_PALETTE), source_image((256, 192), boundaries=True) as source:
            for workers in (1, 2):
                for lines in (True, False):
                    with self.subTest(workers=workers, lines=lines):
                        groups = PixelData.build_strokes(source, skip_white=True, lines=lines,
                            cpu_workers=workers, cpu_engine='Threads')
                        labels = self.assert_labels(source, groups, WHITE_PALETTE, skip_white=True)
                        self.assertEqual(int(labels[0, 8]), 1)  # source 244, selected 255
                        self.assertEqual(int(labels[0, 4]), -1)  # source 245

    def test_raw_rgba_serial_and_row_worker_agree_for_dots_and_runs(self):
        with calibration(), source_image((48, 8), boundaries=True) as source:
            for skip_white in (True, False):
                for lines in (True, False):
                    for route in ('serial', 'row_worker'):
                        with self.subTest(skip_white=skip_white, lines=lines, route=route):
                            groups = (PixelData.build_strokes(source, lines=lines, skip_white=skip_white)
                                if route == 'serial' else PixelData._basic_rows_worker(
                                    (0, source.width, source.tobytes(), lines, skip_white, GREY_PALETTE)))
                            self.assert_labels(source, groups, GREY_PALETTE, skip_white=skip_white)

    def test_actual_thread_failure_uses_correct_serial_fallback(self):
        real_worker = PixelData._basic_rows_worker
        seen = []

        def fail_after_real_rows(task):
            result = real_worker(task)
            seen.append(threading.get_ident())
            raise RuntimeError('worker failed after producing real rows')

        with calibration(), source_image((256, 192), boundaries=True) as source:
            before = source.tobytes()
            with patch('PixelData._basic_rows_worker', side_effect=fail_after_real_rows):
                groups = PixelData.build_strokes(source, cpu_workers=2, cpu_engine='Threads')
            self.assertTrue(seen)
            self.assertTrue(all(ident != threading.get_ident() for ident in seen))
            self.assert_labels(source, groups, GREY_PALETTE, skip_white=True)
            self.assertEqual(source.tobytes(), before)

    def test_stop_and_borrowed_image_contracts_are_preserved(self):
        with calibration(), source_image((256, 192), boundaries=True) as source:
            before = source.tobytes()
            self.assertIsNone(PixelData.build_strokes(source, cancelled=lambda: True))
            calls = 0

            def stop_in_rows():
                nonlocal calls
                calls += 1
                return calls >= 4

            self.assertIsNone(PixelData.build_strokes(source, cancelled=stop_in_rows))
            self.assertGreaterEqual(calls, 4)
            stop = threading.Event()
            real_worker = PixelData._basic_rows_worker

            def stop_after_rows(task):
                result = real_worker(task)
                stop.set()
                return result

            with patch('PixelData._basic_rows_worker', side_effect=stop_after_rows):
                with self.assertRaises(InterruptedError):
                    PixelData.build_strokes(source, cpu_workers=2, cpu_engine='Threads', cancelled=stop.is_set)
            self.assertTrue(stop.is_set())
            self.assertEqual(source.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
