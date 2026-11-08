"""Append-only palette growth keeps exact choices without rescoring old centers."""
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import PictureCustomPalette as picture
import PicturePaletteRefinement as refinement
from PixelAccuratePlanner import _to_oklab


PALETTE = ((0, 0, 0), (255, 255, 255), (230, 30, 20), (25, 190, 60),
           (30, 70, 220), (235, 200, 30), (200, 40, 180), (25, 190, 195))


def palette_source(kind, size=(128, 96)):
    width, height = size
    y, x = np.indices((height, width))
    raw = np.empty((height, width, 3), dtype=np.uint8)
    if kind == 'near-grey':
        raw[...] = (100 + (x * 5 + y * 3) % 45)[..., None]
    elif kind == 'red-shades':
        raw[..., 0] = 170 + (x + y) % 70
        raw[..., 1] = 30 + (x * 2 + y) % 35
        raw[..., 2] = 20 + (x + y * 2) % 25
    else:
        raw[..., 0] = (x * 2 + y) % 256
        raw[..., 1] = (x + y * 2) % 256
        raw[..., 2] = (x * 3 + y * 5) % 256
    return Image.fromarray(raw)


@contextmanager
def private_picture_cache():
    with TemporaryDirectory() as directory, \
            patch.object(picture._legacy, 'data_dir', return_value=Path(directory)), \
            patch.object(picture, 'data_dir', return_value=Path(directory)):
        yield Path(directory)


class PaletteGrowthTests(unittest.TestCase):
    def test_actual_cold_picture_builder_keeps_colors_with_less_assignment_work(self):
        # Complete public outputs from published 4b90, observed before edits.
        expected = {
            'near-grey': ((105, 105, 105), (122, 122, 122), (134, 134, 134),
                          (101, 101, 101), (116, 116, 116), (129, 129, 129),
                          (141, 141, 141), (110, 110, 110)),
            'red-shades': ((217, 48, 33), (189, 44, 33), (199, 59, 33),
                           (176, 40, 33), (204, 39, 33), (233, 40, 34),
                           (178, 57, 32), (228, 58, 31)),
        }
        old_pairs = {'near-grey': 2790, 'red-shades': 990535}
        for kind in expected:
            with self.subTest(kind=kind), closing(palette_source(kind)) as source, private_picture_cache():
                before = source.tobytes(), dict(source.info), source.getexif().tobytes()
                work = []
                assign = refinement._assign
                def observed(points, centers, cancelled):
                    work.append(len(points) * len(centers))
                    return assign(points, centers, cancelled)
                with patch.object(refinement, '_assign', new=observed):
                    result = picture.build_picture_palette(source, PALETTE, max_colors=8)
                self.assertFalse(result.cache_hit)
                self.assertEqual(result.colors, expected[kind])
                self.assertEqual(result.custom_colors, expected[kind])
                self.assertEqual(result.palette_colors, ())
                self.assertEqual(result.custom_coverages, (0.0,) * 8)
                self.assertLess(sum(work), old_pairs[kind] * .75)
                self.assertEqual((source.tobytes(), dict(source.info), source.getexif().tobytes()), before)
                # The actual saved palette, including chosen order, is reusable.
                with patch.object(refinement, '_assign', side_effect=AssertionError('Warm cache rescored')):
                    cached = picture.build_picture_palette(source, PALETTE, max_colors=8)
                self.assertTrue(cached.cache_hit)
                self.assertEqual(cached.colors, result.colors)

    def test_extension_matches_full_assignment_at_tile_and_center_boundaries(self):
        rng = np.random.default_rng(1483002)
        for count in (1, 2047, 2048, 2049, 4097):
            points = _to_oklab(rng.integers(0, 256, (count, 3), dtype=np.uint8))
            for old_count in (1, 7, 8, 15, 16, 31):
                with self.subTest(points=count, previous_centers=old_count):
                    centers = _to_oklab(rng.integers(0, 256, (old_count + 1, 3), dtype=np.uint8))
                    previous = centers[:-1].copy()
                    labels, errors = refinement._assign(points, previous, lambda: False)
                    expected = refinement._assign(points, centers, lambda: False)
                    result = refinement._extend_assignment(points, centers, previous, labels, errors, lambda: False)
                    np.testing.assert_array_equal(result[0], expected[0])
                    np.testing.assert_array_equal(result[1], expected[1])

    def test_exact_ties_keep_the_first_center(self):
        points = np.array(((.5, .5, 0), (0, 1, 0), (0, 0, 0)), np.float32)
        centers = np.array(((0, 0, 0), (1, 1, 0), (0, 1, 0)), np.float32)
        labels, errors = refinement._assign(points, centers[:-1], lambda: False)
        result = refinement._extend_assignment(points, centers, centers[:-1], labels, errors, lambda: False)
        np.testing.assert_array_equal(result[0], (0, 2, 0))
        expected = refinement._assign(points, centers, lambda: False)
        np.testing.assert_array_equal(result[1], expected[1])

    def test_changed_transformed_prefix_requires_full_reassignment(self):
        # Numeric backends may round different vector lengths differently.
        # A real changed coordinate is enough to invalidate the old distances.
        points = np.array(((.25, 0, 0), (.75, 0, 0)), np.float32)
        previous = np.array(((0, 0, 0), (1, 0, 0)), np.float32)
        centers = np.array(((.5, 0, 0), (1, 0, 0), (0, 1, 0)), np.float32)
        labels, errors = refinement._assign(points, previous, lambda: False)
        expected = refinement._assign(points, centers, lambda: False)
        result = refinement._extend_assignment(points, centers, previous, labels, errors, lambda: False)
        np.testing.assert_array_equal(result[0], expected[0])
        np.testing.assert_array_equal(result[1], expected[1])

    def test_stop_mid_extension_does_not_publish_partial_labels(self):
        points = np.zeros((4097, 3), np.float32)
        centers = np.array(((1, 0, 0), (0, 0, 0)), np.float32)
        labels, errors = refinement._assign(points, centers[:1], lambda: False)
        before = labels.copy(), errors.copy()
        calls = []
        def cancelled():
            calls.append(True)
            return len(calls) == 2
        with self.assertRaises(InterruptedError):
            refinement._extend_assignment(points, centers, centers[:1], labels, errors, cancelled)
        self.assertEqual(len(calls), 2)
        np.testing.assert_array_equal(labels, before[0])
        np.testing.assert_array_equal(errors, before[1])

    def test_actual_picture_growth_stop_cannot_save_a_partial_palette(self):
        with closing(palette_source('red-shades')) as source, private_picture_cache() as directory:
            before = source.tobytes()
            extend = refinement._extend_assignment
            reached = []
            def stop(points, centers, previous_centers, labels, errors, cancelled):
                reached.append(True)
                return extend(points, centers, previous_centers, labels, errors, lambda: True)
            with patch.object(refinement, '_extend_assignment', new=stop), self.assertRaises(InterruptedError):
                picture.build_picture_palette(source, PALETTE, max_colors=24)
            self.assertEqual(reached, [True])
            self.assertEqual(list(directory.iterdir()), [])
            self.assertEqual(source.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
