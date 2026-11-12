"""Exact existing-source compositing and ordered compact rectangle staging."""
from contextlib import ExitStack, closing
import copy
import gc
from pathlib import Path
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageOps

import Colors
import DetailZoomPass as zoom
import PixelAccuracyGpu as gpu
from PixelAccuracyEngine import _apply_sequence
from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan
from test_v148_rendering_batch39_pixel_runs import public_options
from test_v148_rendering_batch42_costs import PaletteOwner


ROOT = Path(__file__).resolve().parent
ICON = ROOT / 'assets/image-draw-bot-icon.png'


def integer_composite(source):
    """Independent exact rounded white compositing of byte-valued source data."""
    with ImageOps.exif_transpose(source) as oriented, oriented.convert('RGBA') as image:
        rgba = np.asarray(image).astype(np.uint32)
    alpha = rgba[..., 3:4]
    return ((rgba[..., :3] * alpha + 255 * (255 - alpha) + 127) // 255).astype(np.uint8)


class DetailZoomStagingTests(unittest.TestCase):
    def test_actual_alpha_modes_and_exif_match_independent_integer_composite(self):
        with Image.open(ICON) as original, ExitStack() as owned:
            cropped = owned.enter_context(closing(original.crop((3, 7, 310, 211))))
            for mode in ('RGBA', 'RGB', 'L', 'P'):
                with self.subTest(mode=mode), cropped.convert(mode) as source:
                    exif = source.getexif(); exif[274] = 6; source.info['exif'] = exif.tobytes()
                    before = source.tobytes(), dict(source.info)
                    expected = integer_composite(source)
                    for side in (64, 256):
                        with patch.object(zoom, '_VISIBLE_TILE_SIDE', side):
                            actual = zoom._visible_rgb(source)
                        np.testing.assert_array_equal(actual, expected)
                        self.assertEqual(actual.dtype, np.uint8)
                        self.assertTrue(actual.flags.c_contiguous)
                    self.assertEqual((source.tobytes(), dict(source.info)), before)

    def test_each_composite_tile_is_bounded_on_the_real_icon(self):
        sizes = []
        real = zoom._visible_rgb_tile
        def observe(source):
            sizes.append(source.size)
            return real(source)
        with Image.open(ICON) as source, patch.object(zoom, '_visible_rgb_tile', new=observe):
            actual = zoom._visible_rgb(source)
            np.testing.assert_array_equal(actual, integer_composite(source))
        self.assertEqual(len(sizes), 4)
        self.assertTrue(all(width <= 256 and height <= 256 for width, height in sizes))

    def test_small_panorama_keeps_one_bounded_composite_call(self):
        with Image.open(ICON) as original:
            for box in ((0, 128, 512, 130), (128, 0, 130, 512)):
                with self.subTest(box=box), original.crop(box) as source, \
                        patch.object(zoom, '_visible_rgb_tile', wraps=zoom._visible_rgb_tile) as tiles:
                    actual = zoom._visible_rgb(source)
                    np.testing.assert_array_equal(actual, integer_composite(source))
                    self.assertEqual(tiles.call_count, 1)

    def check_retained_failure(self, failure_kind):
        images, references, completed = [], [], []
        real_new, real_empty, real_tile = Image.Image._new, np.empty, zoom._visible_rgb_tile
        failure = MemoryError('actual tile boundary allocation failure')
        def created(owner, core):
            image = real_new(owner, core)
            images.append(image)
            return image
        def empty(shape, *args, **kwargs):
            result = real_empty(shape, *args, **kwargs)
            if shape == (512, 512, 3):
                references.append(weakref.ref(result))
            return result
        def tile(source):
            if failure_kind == 'allocation' and completed:
                raise failure
            result = real_tile(source)
            completed.append(True)
            return result
        with Image.open(ICON) as source:
            before = source.tobytes()
            caught = None
            with patch.object(Image.Image, '_new', new=created), patch.object(zoom.np, 'empty', new=empty), \
                    patch.object(zoom, '_visible_rgb_tile', new=tile):
                try:
                    zoom._visible_rgb(source, cancelled=lambda: failure_kind == 'stop' and bool(completed))
                except (InterruptedError, MemoryError) as error:
                    caught = error
            self.assertIsNotNone(caught)
            self.assertIsNotNone(caught.__traceback__)
            if failure_kind == 'allocation':
                self.assertIs(caught, failure)
            for image in images:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))
            self.assertEqual(len(references), 1)
            gc.collect()
            self.assertIsNone(references[0]())
            self.assertEqual(source.tobytes(), before)

    def test_stop_releases_owned_images_and_unpublished_output(self):
        self.check_retained_failure('stop')

    def test_failed_tile_releases_owned_images_and_unpublished_output(self):
        self.check_retained_failure('allocation')


class CompactRectangleTests(PaletteOwner):
    def sequence(self):
        palette = tuple(color.RGB for color in Colors.allColors)
        with Image.open(ROOT / 'golden-regression/red-bananas-texture.png') as original, \
                original.resize((96, 64)) as source:
            mapped = build_pixel_map(source, palette, gpu_mode='CPU', skip_white=False)
        actual = build_pixel_stroke_plan(mapped, len(palette), options=public_options())
        return actual['execution_sequence'], (mapped.width, mapped.height)

    def assert_raster(self, sequence, size, brush):
        rectangles = gpu.compile_swept_rectangles(sequence, brush, *size)
        self.assertEqual(rectangles.dtype, np.int32)
        self.assertTrue(rectangles.flags.c_contiguous)
        self.assertEqual(rectangles.shape[1], 5)
        shape = size[1], size[0]
        expected = np.full(shape, -1, dtype=np.int16)
        expected_counts = np.zeros(shape, dtype=np.uint16)
        _apply_sequence(expected, expected_counts, sequence, brush)
        actual = np.full(shape, -1, dtype=np.int16)
        counts = np.zeros(shape, dtype=np.uint16)
        for left, top, right, bottom, color in rectangles:
            region = slice(top, bottom + 1), slice(left, right + 1)
            actual[region] = color
            counts[region] = np.minimum(counts[region].astype(np.uint32) + 1, 65535)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(counts, expected_counts)
        return rectangles

    def test_existing_component_paths_match_actual_cpu_order_and_coverage_counts(self):
        sequence, size = self.sequence()
        before = copy.deepcopy(sequence)
        self.assertGreater(len(self.assert_raster(sequence, size, 1)), 0)
        # Translate the same source geometry through canvas bounds and vary
        # physical brush state; no new source shape is constructed.
        shifted = []
        for index, entry in enumerate(sequence):
            row = dict(entry, path=tuple((x - 31, y - 13) for x, y in entry['path']))
            if index % 3:
                row.pop('brush_px', None)
            else:
                row['brush_px'] = (1, 2, 5)[(index // 3) % 3]
            shifted.append(row)
        self.assert_raster(shifted, size, 3)
        self.assertEqual(sequence, before)

    def test_result_buffer_is_private_and_survives_its_compiler_frame(self):
        sequence, size = self.sequence()
        first = gpu.compile_swept_rectangles(sequence, 1, *size)
        second = gpu.compile_swept_rectangles(sequence, 1, *size)
        self.assertFalse(np.shares_memory(first, second))
        np.testing.assert_array_equal(first, second)
        before = second.copy()
        first[0, 4] = -1
        gc.collect()
        np.testing.assert_array_equal(second, before)

    def test_stop_drops_the_partial_compact_buffer_with_retained_traceback(self):
        sequence, size = self.sequence()
        references = []
        real = gpu.array
        def allocate(*args, **kwargs):
            result = real(*args, **kwargs)
            references.append(weakref.ref(result))
            return result
        caught = None
        with patch.object(gpu, 'array', new=allocate):
            try:
                gpu.compile_swept_rectangles(sequence, 1, *size,
                    cancelled=lambda: bool(references and references[0]() is not None and len(references[0]()) > 0))
            except InterruptedError as error:
                caught = error
        self.assertIsNotNone(caught)
        self.assertIsNotNone(caught.__traceback__)
        gc.collect()
        self.assertEqual(len(references), 1)
        self.assertIsNone(references[0]())

    def test_late_source_failure_drops_staging_and_preserves_the_error(self):
        sequence, size = self.sequence()
        failure = MemoryError('input iteration failed after real source geometry')
        def entries():
            yield sequence[0]
            raise failure
        references = []
        real = gpu.array
        def allocate(*args, **kwargs):
            result = real(*args, **kwargs)
            references.append(weakref.ref(result))
            return result
        caught = None
        with patch.object(gpu, 'array', new=allocate):
            try:
                gpu.compile_swept_rectangles(entries(), 1, *size)
            except MemoryError as error:
                caught = error
        self.assertIs(caught, failure)
        self.assertIsNotNone(caught.__traceback__)
        gc.collect()
        self.assertIsNone(references[0]())


if __name__ == '__main__':
    unittest.main()
