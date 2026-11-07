"""Spatial indexing preserves every lossless attachment and bounded Stop."""
import builtins
import copy
import random
import unittest
from unittest.mock import patch

import PixelStrokeEngine as strokes
from RasterIdentity import canonical_pixels_from_paths, canonical_pixels_from_runs


class LosslessAttachmentIndexTests(unittest.TestCase):
    def test_nested_overlaps_ties_row_gaps_and_caps_keep_recorded_paths(self):
        # Literal results recorded on f7b561f. The wide first interval encloses
        # a later short interval, so an index based on sorted ends is invalid.
        runs = [(0,0,10,0),(1,0,3,0),(8,0,6,0),(0,1,2,1),(3,1,8,1),
                (9,1,10,1),(2,2,9,2),(20,4,20,4),(21,6,22,6),(30,4,30,7)]
        expected = {
            4: [((1,0),(3,0)), ((6,0),(8,0),(8,1),(3,1)),
                ((0,0),(10,0),(10,1),(9,1)), ((0,1),(2,1),(2,2),(9,2)),
                ((20,4),), ((21,6),(22,6)), ((30,4),(30,7))],
            12: [((1,0),(3,0)), ((0,0),(10,0),(2,0),(2,1),(0,1)),
                 ((9,1),(10,1)), ((6,0),(8,0),(8,1),(3,1),(3,2),(2,2),(9,2)),
                 ((20,4),), ((21,6),(22,6)), ((30,4),(30,7))],
        }
        original = copy.deepcopy(runs)
        for cap, paths in expected.items():
            with self.subTest(cap=cap):
                result = strokes._merge_horizontal_runs_lossless(runs, max_points_per_path=cap)
                self.assertEqual(result, paths)
                self.assertEqual(canonical_pixels_from_paths(result), canonical_pixels_from_runs(runs))
        self.assertEqual(runs, original)

    def test_parallel_strips_do_not_scan_unrelated_active_intervals(self):
        runs = [(index*3,y,index*3+1,y) for y in range(25) for index in range(180)]
        calls = 0
        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return builtins.max(*args, **kwargs)
        with patch.object(strokes, 'max', new=counted, create=True):
            result = strokes._merge_horizontal_runs_lossless(runs)
        # Count overlap/attachment arithmetic, not elapsed machine time.
        # f7b561f performs 412,560 max operations on the same 4,500 runs.
        self.assertLess(calls, 8*len(runs))
        self.assertEqual(len(result), 180)
        self.assertEqual(canonical_pixels_from_paths(result), canonical_pixels_from_runs(runs))

    def test_stop_during_a_busy_row_is_bounded_and_does_not_mutate_input(self):
        runs = [(index*3,y,index*3+1,y) for y in range(2) for index in range(900)]
        original = copy.deepcopy(runs)
        calls = 0
        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return builtins.max(*args, **kwargs)
        with patch.object(strokes, 'max', new=counted, create=True), self.assertRaises(InterruptedError):
            strokes._merge_horizontal_runs_lossless(runs, cancelled=lambda: calls >= 500)
        self.assertLessEqual(calls, 756)
        self.assertEqual(runs, original)

    def test_varied_caps_and_reordered_runs_keep_exact_ink_on_independent_calls(self):
        rng = random.Random(1481401)
        for seed in range(12):
            runs = [(x,y,x+rng.randrange(1,9),y)
                    for y in range(-3,12) if y%5
                    for x in (-8, rng.randrange(0,5), 18)]
            rng.shuffle(runs)
            for cap, rows in ((2,1), (3,2), (7,3), (480,96)):
                with self.subTest(seed=seed, cap=cap, rows=rows):
                    result = strokes._merge_horizontal_runs_lossless(runs,
                        max_points_per_path=cap, max_rows_per_path=rows)
                    self.assertTrue(all(len(path)<=cap for path in result))
                    self.assertEqual(canonical_pixels_from_paths(result), canonical_pixels_from_runs(runs))
            runs[0] = (40,20,43,20)
            result = strokes._merge_horizontal_runs_lossless(runs)
            self.assertEqual(canonical_pixels_from_paths(result), canonical_pixels_from_runs(runs))


if __name__ == '__main__':
    unittest.main()
