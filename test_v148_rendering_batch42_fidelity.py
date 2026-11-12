"""Real-source Pixel edge and adaptive/background fidelity regressions.

Every raster is the existing small-detail fixture or a palette/size derivative
of its labels. No new source geometry or mocked planner is used.
"""
from contextlib import ExitStack, closing, contextmanager
import gc
from pathlib import Path
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

import AdaptiveDetail as detail
import Colors
import PixelAccuratePlanner as pixel
from DrawBot import make_plan
from FillOptimizer import simplify_background
from ImageGradients import luminance_edges
from PixelStrokeEngine import build_pixel_stroke_plan
from test_v148_rendering_batch38_prepared_paths import close_plan
from test_v148_rendering_batch39_pixel_runs import public_options


ROOT = Path(__file__).resolve().parent
ASSET = ROOT / 'golden-regression/small-detail-preservation.png'
ISOLUMINANT = ((160, 100, 10), (116, 103, 110))
LOW_CONTRAST = ((220, 220, 220), (190, 190, 190))


@contextmanager
def source_labels(colors, size=None):
    with ExitStack() as owned:
        source = owned.enter_context(closing(Image.open(ASSET)))
        if size:
            source = owned.enter_context(closing(source.resize(size, Image.Resampling.NEAREST)))
        gray = owned.enter_context(closing(source.convert('L')))
        labels = owned.enter_context(closing(gray.point(lambda value: int(value < 60), mode='P')))
        labels.putpalette([channel for color in colors for channel in color] + [0] * 762)
        yield owned.enter_context(closing(labels.convert('RGBA')))


@contextmanager
def calibrated_palette(colors):
    from PixelData import closest_color
    previous = list(Colors.allColors)
    Colors.allColors.clear()
    try:
        for index, color in enumerate(colors):
            Colors.Color(str(index), *color)
        closest_color.cache_clear()
        yield
    finally:
        Colors.allColors[:] = previous
        closest_color.cache_clear()


def standard_options(**changes):
    result = public_options(draw_quality='Standard', planning_resolution='High',
        adaptive_detail='Preserve detail', background_simplification='Off',
        brush_px=1, portrait_focus=False, _full_detail_preview=True)
    result.update(changes)
    return result


def scalar_opponent_edges(rgb):
    """Independent centered/one-sided finite differences of the actual pixels."""
    values = np.asarray(rgb, dtype=np.float32)
    height, width = values.shape[:2]
    result = np.empty((height, width), dtype=np.float32)
    for y in range(height):
        for x in range(width):
            magnitude = np.float32(0)
            for channel in (0, 2):
                def opponent(py, px):
                    return values[py, px, channel] - values[py, px, 1]
                dx = (np.float32(0) if width <= 1 else
                      opponent(y, 1) - opponent(y, 0) if x == 0 else
                      opponent(y, x) - opponent(y, x - 1) if x == width - 1 else
                      (opponent(y, x + 1) - opponent(y, x - 1)) * np.float32(.5))
                dy = (np.float32(0) if height <= 1 else
                      opponent(1, x) - opponent(0, x) if y == 0 else
                      opponent(y, x) - opponent(y - 1, x) if y == height - 1 else
                      (opponent(y + 1, x) - opponent(y - 1, x)) * np.float32(.5))
                magnitude = max(magnitude, np.sqrt(dx * dx + dy * dy))
            result[y, x] = magnitude
    return result


def historical_luminance_signal(rgb):
    gray = np.rint(rgb[..., 0] * .299 + rgb[..., 1] * .587 + rgb[..., 2] * .114)
    gray = gray.clip(0, 255).astype(np.uint8)
    magnitude = luminance_edges(gray.astype(np.float32))
    return np.clip(magnitude / max(1., float(np.percentile(magnitude, 99.5))), 0, 1).astype(np.float32)


class PixelChromaticPriorityTests(unittest.TestCase):
    def test_equal_luminance_source_reaches_actual_protected_cleanup(self):
        with source_labels(ISOLUMINANT) as source:
            before = source.tobytes()
            with closing(source.convert('L')) as gray:
                self.assertEqual(gray.getextrema(), (108, 108))
            mapped = pixel.build_pixel_map(source, ISOLUMINANT, gpu_mode='CPU', skip_white=False)
            self.assertGreater(np.count_nonzero(mapped.edge_map), 0)
            foreground = mapped.palette_index == 1
            self.assertGreater(np.count_nonzero(mapped.protected_mask & foreground), 0)
            actual = build_pixel_stroke_plan(mapped, len(ISOLUMINANT), options=public_options())
            self.assertTrue(any(row['color_index'] == 1 and row['phase'] == 'cleanup'
                                and row['protected'] for row in actual['execution_sequence']))
            self.assertEqual(source.tobytes(), before)

    def test_public_pixel_plan_keeps_exact_source_and_protected_quality(self):
        with source_labels(ISOLUMINANT, (96, 64)) as source, calibrated_palette(ISOLUMINANT):
            before = source.tobytes()
            plan = make_plan(source, source.size, public_options(portrait_focus=False))
            try:
                self.assertTrue(plan['options']['pixel_accurate'])
                meta = plan['options']['pixel_accuracy_meta']
                self.assertGreater(meta['protected_pixels'], 0)
                self.assertEqual(meta['error_pixels'], 0)
                self.assertEqual(meta['protected_accuracy_percent'], 100.)
                self.assertTrue(any(row['protected'] for row in plan['execution_sequence']))
                self.assertEqual(source.tobytes(), before)
            finally:
                close_plan(plan, source)

    def test_chroma_tiling_matches_independent_differences_and_real_boundaries(self):
        with Image.open(ASSET) as original, original.resize((37, 23)) as reduced, reduced.convert('RGB') as source:
            rgb = np.asarray(source)
            views = (rgb, rgb[::-1, ::-2], rgb[11:12], rgb[:, 17:18], rgb[:2, :2])
            for view in views:
                expected = scalar_opponent_edges(view)
                for side in (1, 7, 256):
                    with self.subTest(shape=view.shape, side=side), patch.object(pixel, '_FEATURE_TILE_SIDE', side):
                        actual = pixel._chromatic_edge_map(view, cancelled=lambda: False)
                        np.testing.assert_array_equal(actual, expected)
                actual, _ = pixel.edge_map(view, gpu_mode='CPU')
                chroma = np.clip(expected / max(1., float(np.percentile(expected, 99.5))), 0, 1)
                np.testing.assert_array_equal(actual, np.maximum(historical_luminance_signal(view), chroma))

    def test_grayscale_normalization_remains_bit_exact(self):
        with Image.open(ASSET) as original, original.convert('L') as gray, gray.convert('RGB') as source:
            rgb = np.asarray(source)
            for view in (rgb, rgb[::-1, ::-3], rgb[32:33], rgb[:, 31:33]):
                with self.subTest(shape=view.shape):
                    actual, _ = pixel.edge_map(view, gpu_mode='CPU')
                    np.testing.assert_array_equal(actual, historical_luminance_signal(view))

    def test_feature_tiles_bound_scratch_and_stop_releases_unpublished_result(self):
        with source_labels(ISOLUMINANT) as source:
            rgb = np.asarray(source)[..., :3]
            before = source.tobytes()
            sizes, references = [], []
            actual_tile, actual_empty = pixel._chromatic_edge_tile, np.empty
            def tile(value):
                result = actual_tile(value)
                sizes.append(value.shape)
                return result
            def empty(shape, *args, **kwargs):
                result = actual_empty(shape, *args, **kwargs)
                if shape == rgb.shape[:2]:
                    references.append(weakref.ref(result))
                return result
            caught = None
            with patch.object(pixel, '_chromatic_edge_tile', new=tile), patch.object(pixel.np, 'empty', new=empty):
                try:
                    pixel._chromatic_edge_map(rgb, cancelled=lambda: bool(sizes))
                except InterruptedError as error:
                    caught = error
            self.assertIsNotNone(caught)
            self.assertIsNotNone(caught.__traceback__)
            self.assertEqual(len(sizes), 1)
            self.assertTrue(all(height <= 258 and width <= 258 for height, width, _ in sizes))
            self.assertEqual(len(references), 1)
            gc.collect()
            self.assertTrue(all(reference() is None for reference in references))
            self.assertEqual(source.tobytes(), before)

    def test_late_stop_releases_completed_private_luminance_planes(self):
        with source_labels(ISOLUMINANT, (96, 64)) as source:
            rgb = np.asarray(source)[..., :3]
            completed, references = [], []
            actual_tile, actual_combine = pixel._chromatic_edge_tile, pixel._combine_edge_signals
            def tile(value):
                result = actual_tile(value)
                completed.append(True)
                return result
            def combine(rgb, luminance, **kwargs):
                references.append(weakref.ref(luminance))
                try:
                    return actual_combine(rgb, luminance, **kwargs)
                finally:
                    rgb = luminance = None
            caught = None
            with patch.object(pixel, '_chromatic_edge_tile', new=tile), \
                    patch.object(pixel, '_combine_edge_signals', new=combine):
                try:
                    pixel.edge_map(rgb, gpu_mode='CPU', cancelled=lambda: bool(completed))
                except InterruptedError as error:
                    caught = error
            self.assertIsNotNone(caught)
            trace = caught.__traceback__
            while trace is not None:
                frame = trace.tb_frame
                if frame.f_code.co_name == 'edge_map':
                    self.assertIsNone(frame.f_locals['gray'])
                    self.assertIsNone(frame.f_locals['mag'])
                elif frame.f_code.co_name == '_combine_edge_signals':
                    self.assertIsNone(frame.f_locals['luminance'])
                trace = trace.tb_next
            gc.collect()
            self.assertEqual(len(references), 1)
            self.assertIsNone(references[0]())


class BackgroundDetailProtectionTests(unittest.TestCase):
    def test_background_flood_keeps_protected_pixels_and_still_simplifies_flat_pixels(self):
        colors = ((223, 223, 223), (193, 193, 193))
        with source_labels(colors) as source, calibrated_palette(LOW_CONTRAST), ExitStack() as owned:
            before = source.tobytes()
            processed, mask, stats = detail.apply_adaptive_detail(source, 'Preserve detail')
            owned.callback(processed.close); owned.callback(mask.close)
            mask_before = mask.tobytes()
            output, meta = simplify_background(processed, 'Strong', protected_mask=mask)
            owned.callback(output.close)
            protected = np.asarray(mask) != 0
            source_rgb = np.asarray(processed)[..., :3]
            changed = np.any(np.asarray(output) != source_rgb, axis=2)
            foreground = np.all(source_rgb == colors[1], axis=2)
            self.assertGreater(stats.protected_pixels, 0)
            self.assertGreater(np.count_nonzero(foreground & ~protected), 0)
            self.assertFalse(np.any(changed & protected))
            self.assertFalse(np.any(changed & foreground), 'Protected contours must also stop the flood entering their interior.')
            self.assertGreater(np.count_nonzero(changed & ~protected), 0)
            self.assertEqual(meta.changed_pixels, int(np.count_nonzero(changed)))
            self.assertEqual(source.tobytes(), before)
            self.assertEqual(mask.tobytes(), mask_before)

    def test_public_background_stage_preserves_the_already_protected_foreground(self):
        with source_labels(LOW_CONTRAST, (96, 64)) as source, calibrated_palette(LOW_CONTRAST), ExitStack() as owned:
            before = source.tobytes()
            off = make_plan(source, source.size, standard_options())
            owned.callback(close_plan, off, source)
            strong = make_plan(source, source.size, standard_options(background_simplification='Strong'))
            owned.callback(close_plan, strong, source)
            self.assertGreater(strong['options']['adaptive_detail_meta']['adaptive_detail_protected_pixels'], 0)
            self.assertEqual(strong['image'].tobytes(), off['image'].tobytes())
            self.assertEqual(strong['groups'], off['groups'])
            self.assertTrue(strong['groups'][1])
            self.assertEqual(source.tobytes(), before)

    def test_no_mask_keeps_explicit_legacy_background_simplification(self):
        with source_labels(LOW_CONTRAST, (96, 64)) as source, calibrated_palette(LOW_CONTRAST):
            plan = make_plan(source, source.size, standard_options(adaptive_detail='Off',
                background_simplification='Strong'))
            try:
                self.assertEqual(plan['options']['adaptive_detail_effective'], 'Off')
                self.assertFalse(plan['groups'][1])
                self.assertGreater(plan['options']['background_simplification_meta']['changed_pixels'], 0)
            finally:
                close_plan(plan, source)


class AutoPreviewDrawFidelityTests(unittest.TestCase):
    def test_same_public_auto_policy_preserves_low_contrast_source_in_preview_and_draw(self):
        with source_labels(LOW_CONTRAST, (96, 64)) as source, calibrated_palette(LOW_CONTRAST), ExitStack() as owned:
            before = source.tobytes()
            plans = []
            for preview in (True, False):
                plan = make_plan(source, source.size, standard_options(adaptive_detail='Auto',
                    background_simplification='Off', _preview_plan=preview))
                owned.callback(close_plan, plan, source)
                plans.append(plan)
                self.assertEqual(plan['image'].size, source.size)
                self.assertEqual(plan['options']['adaptive_detail_effective'], 'Balanced')
                self.assertGreater(plan['options']['adaptive_detail_meta']['adaptive_detail_protected_pixels'], 0)
                self.assertEqual(plan['image'].tobytes(), before)
                self.assertTrue(plan['groups'][1])
            self.assertEqual(plans[0]['groups'], plans[1]['groups'])
            self.assertEqual(plans[0]['execution_groups'], plans[1]['execution_groups'])
            self.assertEqual(plans[0]['options']['adaptive_detail_meta'], plans[1]['options']['adaptive_detail_meta'])
            self.assertEqual(source.tobytes(), before)

    def test_explicit_strong_and_high_complexity_auto_remain_available(self):
        for preview in (False, True):
            self.assertEqual(detail.resolve_adaptive_detail('Auto', complexity_score=.05, preview=preview), 'Balanced')
            self.assertEqual(detail.resolve_adaptive_detail('Auto', complexity_score=.5, preview=preview), 'Preserve detail')
            self.assertEqual(detail.resolve_adaptive_detail('Strong simplify', complexity_score=.05,
                preview=preview), 'Strong simplify')
        with source_labels(LOW_CONTRAST, (96, 64)) as source, calibrated_palette(LOW_CONTRAST):
            plan = make_plan(source, source.size, standard_options(adaptive_detail='Strong simplify'))
            try:
                self.assertEqual(plan['options']['adaptive_detail_effective'], 'Strong simplify')
                self.assertFalse(plan['groups'][1])
            finally:
                close_plan(plan, source)


if __name__ == '__main__':
    unittest.main()
