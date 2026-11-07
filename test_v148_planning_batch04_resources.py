"""Independent output checks for bounded planner working sets."""
from collections import defaultdict
import math
import random
import unittest

import numpy as np

import AxisRegionPlanner as axis
import QuickSketchFillContour as quick
import Sketch2Planner as sketch2
import SketchPlanner as sketch
import TimeBudget as budget
from ContinuousPaths import ExecutionGroups


def connected_components(mask):
    """Small union/find oracle independent of the planners' flood traversals."""
    points = [(int(y), int(x)) for y, x in zip(*np.nonzero(mask))]
    parent = {point: point for point in points}
    def find(point):
        while parent[point] != point:
            point = parent[point]
        return point
    for y, x in points:
        for other in ((y - 1, x - 1), (y - 1, x), (y - 1, x + 1), (y, x - 1)):
            if other in parent:
                parent[find(other)] = find((y, x))
    groups = defaultdict(list)
    for point in points:
        groups[find(point)].append(point)
    return list(groups.values())


class BoundedComponentTests(unittest.TestCase):
    def test_size_and_protected_peak_rules_match_union_find_components(self):
        rng = np.random.default_rng(1480401)
        for density in (0, .03, .18, .4, 1):
            mask = rng.random((17, 21)) < density
            strength = rng.uniform(0, 25, mask.shape).astype(np.float32)
            components = connected_components(mask)
            original = mask.copy()
            for floor in (1, 2, 3, 7, 12):
                with self.subTest(density=density, floor=floor):
                    expected_plain = mask.copy()
                    expected_protected = mask.copy()
                    removed = protected = 0
                    for component in components:
                        if len(component) >= floor:
                            continue
                        for y, x in component:
                            expected_plain[y, x] = False
                        peak = max(float(strength[y, x]) for y, x in component)
                        if len(component) >= 2 and peak >= 17:
                            protected += 1
                        else:
                            removed += 1
                            for y, x in component:
                                expected_protected[y, x] = False
                    actual_plain = sketch._remove_small_components(mask.copy(), floor, lambda: False)
                    actual, actual_removed, actual_protected = sketch2._filter_components(
                        mask, strength, 10, min_component=floor, protect_factor=1.7,
                        cancelled=lambda: False)
                    np.testing.assert_array_equal(actual_plain, expected_plain)
                    np.testing.assert_array_equal(actual, expected_protected)
                    np.testing.assert_array_equal(mask, original)
                    self.assertEqual((actual_removed, actual_protected), (removed, protected))

    def test_large_surviving_components_still_observe_stop_inside_the_flood(self):
        mask = np.ones((80, 80), bool)
        for function in (
                lambda stop: sketch._remove_small_components(mask.copy(), 4, stop),
                lambda stop: sketch2._filter_components(mask, np.ones(mask.shape), 1,
                    min_component=4, protect_factor=1.5, cancelled=stop)):
            calls = 0
            def stop():
                nonlocal calls
                calls += 1
                return calls == 2
            with self.assertRaises(InterruptedError):
                function(stop)
            self.assertEqual(calls, 2)


class VerticalRunBlockTests(unittest.TestCase):
    def test_block_boundaries_overlap_and_offsets_match_pixel_set_oracle(self):
        rng = random.Random(1480402)
        for width in (1, 63, 64, 65, 129):
            strokes = [(10, -9, 10 + width - 1, -9)]
            strokes += [(10 + rng.randrange(width), rng.randrange(-10, 11),
                         10 + rng.randrange(width), 0) for _ in range(100)]
            strokes = [(x0, y, x1, y) for x0, y, x1, _ in strokes]
            pixels = {(x, y) for x0, y, x1, _ in strokes
                      for x in range(min(x0, x1), max(x0, x1) + 1)}
            expected = []
            for x in sorted({point[0] for point in pixels}):
                ys = sorted(y for px, y in pixels if px == x)
                start = end = ys[0]
                for y in ys[1:]:
                    if y == end + 1:
                        end = y
                    else:
                        expected.append((x, start, x, end)); start = end = y
                expected.append((x, start, x, end))
            self.assertEqual(axis.verticalize_horizontal_runs(strokes), tuple(expected))


class BoundedRankingTests(unittest.TestCase):
    def test_quick_texture_heap_preserves_priority_and_source_order(self):
        rng = random.Random(1480403)
        groups = [[(x, y, x + rng.randrange(5), y) for x, y in
                   ((i, color * 10) for i in range(81))] for color in range(4)]
        micro = [(abs(s[2] - s[0]) + 1, color, index)
                 for color, group in enumerate(groups) for index, s in enumerate(group)
                 if abs(s[2] - s[0]) + 1 <= 2]
        for cap in (0, 1, 7, len(micro) - 1, len(micro), len(micro) + 1):
            selected = {(c, i) for _, c, i in sorted(micro, key=lambda row: (-row[0], row[1], row[2]))[:cap]}
            expected = [[s for i, s in enumerate(group) if abs(s[2] - s[0]) + 1 > 2
                         or (c, i) in selected] for c, group in enumerate(groups)]
            result, removed, retained, long_count = quick._trim_micro_texture(groups, cap)
            self.assertEqual(result, expected)
            self.assertEqual(removed, max(0, len(micro) - cap))
            self.assertEqual(retained, min(cap, len(micro)))
            self.assertEqual(long_count, sum(map(len, groups)) - len(micro))

    def test_streamed_path_ranking_keeps_protected_prefixes_hints_and_ties(self):
        rng = random.Random(1480404)
        paths = [[((i, c), (i + rng.randrange(6), c)) for i in range(35)] for c in range(3)]
        hints = [[f'color{c}-path{i}' for i in range(len(group))] for c, group in enumerate(paths)]
        prefixes = [2, 0, 3]
        groups = ExecutionGroups(paths, phase_hints=hints, protected_prefix_counts=prefixes,
                                 semantic_meta={'portrait_semantic_barrier': True})
        ranked = []
        for color, group in enumerate(paths):
            for index, path in enumerate(group):
                serial = sum(map(len, paths[:color])) + index
                length = math.dist(path[0], path[1])
                ranked.append((index >= prefixes[color], -(length - serial * 1e-9), serial, color, index))
        for cap in (0, 1, 4, 5, 20, 104):
            chosen = {(c, i) for _, _, _, c, i in sorted(ranked)[:cap]}
            result, meta = budget.apply_target_path_cap(groups, cap)
            expected = [[path for i, path in enumerate(group) if (c, i) in chosen]
                        for c, group in enumerate(paths)]
            expected_hints = [[hint for i, hint in enumerate(group) if (c, i) in chosen]
                              for c, group in enumerate(hints)]
            self.assertEqual(result, expected)
            self.assertEqual(result.phase_hints, expected_hints)
            self.assertEqual(meta['path_phase_hints'], expected_hints)
            self.assertEqual(sum(result.protected_prefix_counts), min(cap, sum(prefixes)))
            self.assertEqual(meta['target_after_paths'], cap)
        self.assertEqual(groups, paths)
        self.assertEqual(groups.phase_hints, hints)


if __name__ == '__main__':
    unittest.main()
