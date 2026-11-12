"""Actual-source detail fidelity and bounded Pixel feature regressions.

Sources are repository fixtures (including palette-only derivatives of the same
motif); no new source imagery is created. Numeric maps are analysis fixtures.
"""
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
import unittest
import gc
import weakref
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageChops, ImageFilter

import AdaptiveDetail as detail
import PixelAccuratePlanner as planner

ROOT = Path(__file__).resolve().parent
ASSET = ROOT / 'golden-regression/small-detail-preservation.png'


@contextmanager
def source_image(*, chromatic=False):
    with ExitStack() as owned:
        source = owned.enter_context(closing(Image.open(ASSET)))
        if chromatic:
            gray = owned.enter_context(closing(source.convert('L')))
            labels = owned.enter_context(closing(gray.point(lambda v: int(v < 60), mode='P')))
            # Both colours have Pillow luminance 76. The existing text/eyes/
            # outline motif is unchanged; only its two colour labels change.
            labels.putpalette([0, 130, 0, 255, 0, 0] + [0] * 762)
            source = labels
        yield owned.enter_context(closing(source.convert('RGBA')))


def luminance_only_signal(rgb):
    with closing(rgb.convert('L')) as gray, \
            closing(gray.filter(ImageFilter.MaxFilter(5))) as hi, \
            closing(gray.filter(ImageFilter.MinFilter(5))) as lo:
        return ImageChops.subtract(hi, lo)


@contextmanager
def observe_images():
    # Observe buffers returned to this module, not private Pillow scratch whose
    # library lifetime would be changed by a retained instrumentation reference.
    import sys
    created = []
    def observer(actual):
        def call(*args, **kwargs):
            owner = Path(sys._getframe(1).f_code.co_filename).name == 'AdaptiveDetail.py'
            result = actual(*args, **kwargs)
            if owner:
                for value in result if isinstance(result, tuple) else (result,):
                    if isinstance(value, Image.Image):
                        created.append(value)
            return result
        return call
    with ExitStack() as patches:
        for module, names in ((Image, ('new', 'composite')),
                (Image.Image, ('convert', 'filter', 'resize', 'point', 'getchannel', 'split')),
                (ImageChops, ('subtract', 'lighter'))):
            for name in names:
                patches.enter_context(patch.object(module, name, new=observer(getattr(module, name))))
        yield created


def scalar_micro(indices, mask, edges):
    result = np.empty(indices.shape, np.float32)
    height, width = indices.shape
    for y in range(height):
        for x in range(width):
            if not mask[y, x]:
                result[y, x] = 0
                continue
            neighbours = same = 0
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    neighbours += 1
                    same += bool(mask[ny, nx] and indices[y, x] == indices[ny, nx])
            boundary = np.float32(1) - np.float32(same) / np.float32(max(1, neighbours))
            thin = np.clip((np.float32(2.5) - np.float32(same)) / np.float32(2.5), 0, 1)
            result[y, x] = np.clip(boundary * np.float32(.48) + edges[y, x] * np.float32(.34)
                                  + thin * np.float32(.18), 0, 1)
    return result


class ChromaticDetailTests(unittest.TestCase):
    def test_existing_thin_detail_survives_equal_luminance_palette(self):
        with source_image(chromatic=True) as source:
            before = source.tobytes()
            with closing(source.convert('RGB')) as rgb, closing(rgb.convert('L')) as gray:
                self.assertEqual(gray.getextrema(), (76, 76))
                with closing(luminance_only_signal(rgb)) as legacy_signal:
                    self.assertEqual(legacy_signal.getextrema(), (0, 0))
            with patch.object(detail, '_detail_signal', new=luminance_only_signal):
                legacy, legacy_mask, _ = detail.apply_adaptive_detail(source, 'Strong simplify')
            try:
                self.assertGreater(np.count_nonzero(np.any(np.asarray(legacy) != np.asarray(source), axis=2)), 100)
            finally:
                legacy.close(); legacy_mask.close()
            for mode in ('Preserve detail', 'Balanced', 'Strong simplify', 'Auto'):
                with self.subTest(mode=mode):
                    output, mask, stats = detail.apply_adaptive_detail(source, mode)
                    try:
                        self.assertEqual(output.tobytes(), before)
                        self.assertGreater(stats.protected_pixels, 0)
                        self.assertEqual(mask.getextrema(), (0, 255))
                    finally:
                        output.close(); mask.close()
            self.assertEqual(source.tobytes(), before)

    def test_grayscale_detail_signal_is_byte_identical_to_previous_policy(self):
        with source_image() as source, closing(source.convert('L')) as gray, closing(gray.convert('RGB')) as rgb:
            with closing(luminance_only_signal(rgb)) as expected, closing(detail._detail_signal(rgb)) as actual:
                self.assertEqual(actual.tobytes(), expected.tobytes())

    def assert_retired(self, images, survivors=()):
        allowed = {id(image) for image in survivors}
        for image in images:
            if id(image) in allowed:
                image.getpixel((0, 0))
            else:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))

    def test_success_transfers_only_outputs_and_preserves_borrowed_source(self):
        with source_image() as source:
            before = source.tobytes()
            for mode in ('Off', 'Balanced', 'Strong simplify'):
                with self.subTest(mode=mode), observe_images() as images:
                    output, mask, _ = detail.apply_adaptive_detail(source, mode, subject_focus=True)
                try:
                    self.assert_retired(images, (output, mask))
                    self.assertEqual(source.tobytes(), before)
                    self.assertIsNot(source, output)
                finally:
                    output.close(); mask.close()

    def test_stop_releases_images_even_with_retained_traceback(self):
        with source_image() as source:
            before = source.tobytes()
            for stop_at in (1, 2, 3, 4):
                calls = 0
                def cancelled():
                    nonlocal calls
                    calls += 1
                    return calls >= stop_at
                caught = None
                with self.subTest(stop_at=stop_at), observe_images() as images:
                    try:
                        detail.apply_adaptive_detail(source, 'Strong simplify', subject_focus=True, cancelled=cancelled)
                    except InterruptedError as error:
                        caught = error
                    self.assertIsNotNone(caught)
                    self.assertIsNotNone(caught.__traceback__)
                    self.assert_retired(images)
                    self.assertEqual(source.tobytes(), before)

    def test_filter_failure_preserves_error_and_retires_created_images(self):
        failure = MemoryError('retained post-signal error')
        caught = None
        with source_image() as source, observe_images() as images, \
                patch.object(detail, '_complexity_from_detail', side_effect=failure):
            try:
                detail.apply_adaptive_detail(source, 'Balanced')
            except MemoryError as error:
                caught = error
            self.assertIs(caught, failure)
            self.assert_retired(images)
            source.getpixel((0, 0))


class BoundedMicroDetailTests(unittest.TestCase):
    def arrays(self):
        with source_image() as source, closing(source.resize((69, 41))) as reduced:
            mapped = planner.build_pixel_map(reduced, ((0, 0, 0), (255, 255, 255),
                (239, 91, 72), (248, 211, 45)), gpu_mode='CPU')
        return mapped.palette_index, mapped.drawable_mask, mapped.edge_map

    def test_tiling_matches_independent_scalar_neighbours_including_seams(self):
        arrays = self.arrays()
        for slices in ((slice(None), slice(None)), (slice(None, None, -1), slice(None, None, -1)),
                       (slice(0, 1), slice(None)), (slice(None), slice(0, 1))):
            selected = tuple(value[slices] for value in arrays)
            expected = scalar_micro(*selected)
            for side in (1, 3, 16, 256):
                with self.subTest(shape=selected[0].shape, side=side), patch.object(planner, '_FEATURE_TILE_SIDE', side):
                    actual = planner.micro_detail_map(*selected)
                    np.testing.assert_array_equal(actual, expected)

    def test_actual_pixel_builder_limits_each_feature_working_tile(self):
        sizes = []
        actual_tile = planner._micro_detail_tile
        def observe(*args):
            sizes.append(args[0].shape)
            return actual_tile(*args)
        with source_image() as source, patch.object(planner, '_micro_detail_tile', new=observe):
            mapped = planner.build_pixel_map(source, ((0, 0, 0), (255, 255, 255),
                (239, 91, 72), (248, 211, 45)), gpu_mode='CPU')
        self.assertGreater(len(sizes), 1)
        self.assertTrue(all(height <= 258 and width <= 258 for height, width in sizes), sizes)
        self.assertEqual(mapped.micro_detail_map.shape, (240, 360))

    def test_cancel_after_a_tile_suppresses_partial_feature_result(self):
        arrays = self.arrays()
        count = 0
        actual_tile = planner._micro_detail_tile
        def complete(*args):
            nonlocal count
            count += 1
            return actual_tile(*args)
        with patch.object(planner, '_FEATURE_TILE_SIDE', 16), patch.object(planner, '_micro_detail_tile', new=complete):
            with self.assertRaises(InterruptedError):
                planner.micro_detail_map(*arrays, cancelled=lambda: count >= 2)
        self.assertEqual(count, 2)


    def test_retained_stop_and_tile_failure_release_unpublished_arrays(self):
        arrays = self.arrays()
        actual_tile = planner._micro_detail_tile
        actual_empty = np.empty
        for failure_kind, side in (('stop', 16), ('allocation', 16), ('late-stop', 256)):
            references = []
            count = 0
            caught = None
            failure = MemoryError('second feature tile failed')
            def allocate(*args, **kwargs):
                value = actual_empty(*args, **kwargs)
                if value.shape == arrays[0].shape and value.dtype == np.float32:
                    references.append(weakref.ref(value))
                return value
            def complete(*args):
                nonlocal count
                count += 1
                if failure_kind == 'allocation' and count == 2:
                    raise failure
                value = actual_tile(*args)
                references.append(weakref.ref(value))
                return value
            with self.subTest(failure=failure_kind), \
                    patch.object(planner, '_FEATURE_TILE_SIDE', side), \
                    patch.object(planner, '_micro_detail_tile', new=complete), \
                    patch.object(np, 'empty', new=allocate):
                try:
                    planner.micro_detail_map(*arrays,
                        cancelled=lambda: failure_kind != 'allocation' and count >= 1)
                except (InterruptedError, MemoryError) as error:
                    caught = error
                self.assertIsNotNone(caught)
                self.assertIsNotNone(caught.__traceback__)
                if failure_kind == 'allocation':
                    self.assertIs(caught, failure)
                self.assertTrue(references)
                gc.collect()
                self.assertTrue(all(reference() is None for reference in references),
                    [(reference().shape, reference().nbytes) for reference in references if reference() is not None])


if __name__ == '__main__':
    unittest.main()
