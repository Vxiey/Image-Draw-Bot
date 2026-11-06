from __future__ import annotations

import random
import unittest

from ContinuousPaths import _horizontal_paths
from PixelStrokeEngine import _merge_horizontal_runs_lossless
from FillOptimizer import detect_fill_regions_from_groups
from GarticPhoneFastRenderer import optimize_gartic_phone_groups


def pixels_in_paths(paths):
    pixels = set()
    for path in paths:
        if len(path) == 1:
            pixels.add(path[0])
        for (x0, y0), (x1, y1) in zip(path, path[1:]):
            if x0 == x1:
                pixels.update((x0, y) for y in range(min(y0, y1), max(y0, y1) + 1))
            elif y0 == y1:
                pixels.update((x, y0) for x in range(min(x0, x1), max(x0, x1) + 1))
            else:
                raise AssertionError("Unexpected non-orthogonal connector")
    return pixels


class RasterPointCapTests(unittest.TestCase):
    def test_extensions_obey_cap_without_losing_pixels(self):
        randomizer = random.Random(14803)
        cases = [[(0, 0, 4, 0), (1, 1, 3, 1)]]
        for _ in range(25):
            cases.append([(x, y, x + randomizer.randrange(8), y)
                          for y in range(12) for x in (randomizer.randrange(3), 12)])
        for merge in (_horizontal_paths, _merge_horizontal_runs_lossless):
            for cap in (2, 3, 4, 5, 8, 12):
                for runs in cases:
                    with self.subTest(merge=merge.__name__, cap=cap):
                        actual = merge(runs, max_points_per_path=cap)
                        self.assertTrue(all(len(path) <= cap for path in actual))
                        expected = {(x, y0) for x0, y0, x1, y1 in runs
                                    for x in range(min(x0, x1), max(x0, x1) + 1)}
                        self.assertEqual(pixels_in_paths(actual), expected)


class GroupFillClippingTests(unittest.TestCase):
    def test_off_returns_before_touching_groups_or_geometry(self):
        class Unreadable:
            def __iter__(self):
                raise AssertionError("Off must not analyze geometry")
        self.assertEqual(detect_fill_regions_from_groups(Unreadable(), [], None, mode="Off"), [])
        regions, meta = detect_fill_regions_from_groups([], [], None, mode="Off", return_meta=True)
        self.assertEqual(regions, [])
        self.assertEqual(meta["accepted_regions"], 0)

    def test_outside_intervals_do_not_become_edge_pixels_or_expand_labels(self):
        for run in ((12, 5, 14, 5), (14, 5, 12, 5), (-6, 5, -2, 5),
                    (-2, 5, -6, 5), (5, 12, 5, 14), (5, 14, 5, 12),
                    (5, -6, 5, -2), (5, -2, 5, -6)):
            with self.subTest(run=run):
                _, meta = detect_fill_regions_from_groups([[run]], [(0, 0, 0)], (10, 10), return_meta=True)
                self.assertEqual(meta["total_components"], 0)

    def test_partly_visible_reversed_intervals_keep_their_visible_component(self):
        for run in ((-4, 5, 4, 5), (4, 5, -4, 5), (5, -4, 5, 4), (5, 4, 5, -4)):
            _, meta = detect_fill_regions_from_groups([[run]], [(0, 0, 0)], (10, 10), return_meta=True)
            self.assertEqual(meta["total_components"], 1)
            self.assertEqual(meta["interior_components"], 0)

    def test_diagonal_groups_include_the_complete_visible_lattice(self):
        # These exact Bresenham pixels form two four-connected pieces:
        # (2,2),(3,2),(4,2) and (5,3),(6,3),(7,3).
        _, meta = detect_fill_regions_from_groups([[(2, 2, 7, 3)]], [(0, 0, 0)], (10, 10), return_meta=True)
        self.assertEqual(meta['total_components'], 2)
        self.assertEqual(meta['interior_components'], 2)


class ForcedDarkPaletteTests(unittest.TestCase):
    def test_every_source_pixel_survives_eviction_of_a_retained_swatch(self):
        source = [[(0, 0, 0, 0)], [(0, 2, 19, 2)], [(0, 4, 19, 4)]]
        result, meta = optimize_gartic_phone_groups(source, [(0, 0, 0), (255, 0, 0), (0, 0, 255)],
                                                   max_colors=2, gap_join=0, min_run=1)
        source_pixels = {(x, y0) for group in source for x0, y0, x1, y1 in group
                         for x in range(x0, x1 + 1)}
        rendered = [((x0, y0), (x1, y1)) for group in result for x0, y0, x1, y1 in group]
        self.assertEqual(pixels_in_paths(rendered), source_pixels)
        self.assertEqual(len(source_pixels), 41)
        self.assertLessEqual(meta["active_colors_after"], 2)
        self.assertTrue(set(meta["color_mapping"].values()) <= set(meta["kept_color_indexes"]))
        self.assertGreater(meta["average_reduction_delta_e2000"], 0)


if __name__ == "__main__":
    unittest.main()
