"""Repeated route-search work does not change the selected ink or route."""
from collections import Counter
import copy
import random
import unittest
from unittest.mock import patch

import StrokeOptimizer as optimizer


def paths_for_seed(seed, count):
    rng = random.Random(seed)
    paths = []
    for _ in range(count):
        x, y = rng.randrange(-2000, 2001), rng.randrange(-2000, 2001)
        paths.append(((x, y), (x + rng.randrange(1, 20), y + rng.randrange(-12, 13))))
    return paths


def ink_segments(paths, *, directed=False):
    return Counter((a, b) if directed or a <= b else (b, a)
                   for path in paths for a, b in zip(path, path[1:]) if a != b)


class BoundaryCostReuseTests(unittest.TestCase):
    def test_repeated_reversals_keep_recorded_route_and_complete_metadata(self):
        # Recorded on 4704a94d. Three accepted reversals make stale edge costs
        # visible; integer distances also avoid a platform-specific float golden.
        paths = [((x, 0), (x + 2, 0)) for x in (0, 60, 20, 80, 40, 100)]
        original = copy.deepcopy(paths)
        expected = [((0, 0), (2, 0)), ((22, 0), (20, 0)),
                    ((42, 0), (40, 0)), ((62, 0), (60, 0)),
                    ((80, 0), (82, 0)), ((100, 0), (102, 0))]
        actual, metadata = optimizer._bounded_two_opt(paths, speed='Safe')
        self.assertEqual(actual, expected)
        self.assertEqual(metadata, {
            'optimizer_two_opt_iterations': 4,
            'optimizer_two_opt_improvements': 3,
            'optimizer_two_opt_evaluations': 60,
            'optimizer_two_opt_before': 258.0,
            'optimizer_two_opt_after': 102.0,
        })
        self.assertEqual(ink_segments(actual), ink_segments(paths))
        self.assertEqual(paths, original)

    def test_search_evaluates_old_route_edges_once_per_pass(self):
        paths = paths_for_seed(1481301, 72)
        calls = 0
        distance = optimizer._distance
        def counted(*args):
            nonlocal calls
            calls += 1
            return distance(*args)
        with patch.object(optimizer, '_distance', new=counted):
            result, metadata = optimizer._bounded_two_opt(paths, speed='Balanced')
        evaluations = metadata['optimizer_two_opt_evaluations']
        passes = metadata['optimizer_two_opt_iterations']
        self.assertGreater(evaluations, 4 * len(paths))
        # At most two proposed links per candidate, one existing-link pass per
        # iteration, and the unchanged complete before/after travel checks.
        self.assertLessEqual(calls, 2 * evaluations + (passes + 2) * (len(paths) - 1))
        self.assertEqual(ink_segments(result), ink_segments(paths))

    def test_stop_is_observed_during_existing_edge_preparation(self):
        paths = [((index * 4, 0), (index * 4 + 1, 0)) for index in range(1600)]
        original = copy.deepcopy(paths)
        calls = 0
        distance = optimizer._distance
        def counted(*args):
            nonlocal calls
            calls += 1
            return distance(*args)
        # The initial complete route metric is unchanged. Request Stop after
        # another 260 distances, while the new per-pass preparation is running.
        with patch.object(optimizer, '_distance', new=counted), self.assertRaises(InterruptedError):
            optimizer._bounded_two_opt(paths, speed='Fast',
                cancelled=lambda: calls >= len(paths) - 1 + 260)
        self.assertLessEqual(calls, len(paths) - 1 + 512)
        self.assertEqual(paths, original)

    def test_independent_calls_directed_paths_and_short_routes_keep_their_contract(self):
        for count in (0, 1, 2, 3):
            paths = paths_for_seed(count, count)
            result, metadata = optimizer._bounded_two_opt(paths)
            self.assertEqual(result, paths)
            self.assertEqual(metadata['optimizer_two_opt_evaluations'], 0)
        paths = paths_for_seed(13, 16)
        result, metadata = optimizer._bounded_two_opt(paths, allow_reverse=False)
        self.assertEqual(result, paths)
        self.assertEqual(ink_segments(result, directed=True), ink_segments(paths, directed=True))
        self.assertEqual(metadata['optimizer_two_opt_iterations'], 0)
        optimizer._bounded_two_opt(paths)
        paths[5] = ((9001, -9001), (9011, -9001))
        result, metadata = optimizer._bounded_two_opt(paths)
        self.assertEqual(metadata['optimizer_two_opt_before'], optimizer.pen_up_distance(paths))
        self.assertEqual(metadata['optimizer_two_opt_after'], optimizer.pen_up_distance(result))
        self.assertEqual(ink_segments(result), ink_segments(paths))


if __name__ == '__main__':
    unittest.main()
