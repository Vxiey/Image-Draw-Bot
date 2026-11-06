import math
import random
import unittest
from collections import Counter

import AxisRegionPlanner as ARP
import ShapePaths as SP
import StrokeOptimizer as SO
from RasterIdentity import compare_runs_to_paths


def directed_edges(paths):
    return Counter((a, b) for path in paths for a, b in zip(path, path[1:]) if a != b)


def expected_components(runs):
    pixels = {(x, y) for x0, y, x1, _ in runs for x in range(min(x0, x1), max(x0, x1) + 1)}
    groups = []
    while pixels:
        seed = pixels.pop()
        group = {seed}
        pending = [seed]
        while pending:
            x, y = pending.pop()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in pixels:
                    pixels.remove(point)
                    group.add(point)
                    pending.append(point)
        groups.append(frozenset(group))
    return set(groups)


class StrokeDirectionTests(unittest.TestCase):
    def test_merge_and_two_opt_obey_explicit_directed_paths(self):
        paths = [((0, 0), (1, 0)), ((2, 0), (1, 0)), ((3, 0), (2, 0))]
        for mode in ('Travel only', 'Smart merge', 'Smart merge + 2-opt'):
            result, _ = SO.optimize_path_group(paths, mode=mode, allow_reverse=False)
            self.assertEqual(directed_edges(result), directed_edges(paths))
        allowed, _ = SO.optimize_path_group(paths, mode='Smart merge', allow_reverse=True)
        self.assertEqual(allowed, [((0, 0), (1, 0), (2, 0), (3, 0))])

    def test_neighbor_merge_also_preserves_forbidden_direction(self):
        paths = [((0, 0), (1, 0)), ((2, 0), (1, 0))]
        self.assertEqual(SO._merge_exact_neighbors(paths, allow_reverse=False), (paths, 0))

    def test_bounded_queue_keeps_original_nearest_neighbor_choices(self):
        rng = random.Random(148)
        for speed in ('Safe', 'Balanced', 'Fast'):
            for reverse in (False, True):
                paths = [((rng.randrange(30), rng.randrange(30)), (rng.randrange(30), rng.randrange(30)))
                         for _ in range(180)]
                paths = [path if path[0] != path[1] else (path[0],) for path in paths]
                remaining = list(paths)
                expected = [remaining.pop(0)]
                window = max({'Safe': 28, 'Balanced': 96, 'Fast': 160}[speed], 128)
                while remaining:
                    cursor = expected[-1][-1]
                    options = []
                    for index, path in enumerate(remaining[:window]):
                        forward = math.dist(cursor, path[0])
                        backward = math.dist(cursor, path[-1]) if reverse else float('inf')
                        options.append((min(forward, backward) + index * 1e-5, index, backward < forward))
                    _, index, flipped = min(options)
                    path = remaining.pop(index)
                    expected.append(tuple(reversed(path)) if flipped else path)
                self.assertEqual(SO._nearest_order(paths, speed=speed, allow_reverse=reverse), expected)
        chain = [((index, 0), (index + 1, 0)) for index in range(14000)]
        self.assertEqual(SO._nearest_order(chain), chain)


class ShapeGeometryTests(unittest.TestCase):
    def test_compression_preserves_collinear_backtracks(self):
        points = [(0, 0), (5, 0), (2, 0), (2, 5), (2, 1)]
        self.assertEqual(SP._compress(points), tuple(points))
        self.assertEqual(SP._compress([(0, 0), (2, 0), (5, 0)]), ((0, 0), (5, 0)))

    def test_hatch_keeps_both_sides_of_an_interior_connector(self):
        runs = [(2, 0, 5, 0), (0, 1, 8, 1)]
        components, _ = SP._components_from_runs(runs)
        paths = SP._hatch_paths(components[0], step=1)
        self.assertTrue(compare_runs_to_paths(runs, paths).safe)
        self.assertIn((0, 1), paths[0])

    def test_large_zigzag_simplifies_without_python_recursion(self):
        points = [(index, index % 2) for index in range(1600)]
        self.assertEqual(SP._rdp(points, .2), points)
        self.assertEqual(SP._rdp([(0, 0), (1, 0), (2, 0), (3, 0)], .5), [(0, 0), (3, 0)])
        self.assertEqual(SP._rdp([(0, 0), (1, 2), (2, 0)], 1), [(0, 0), (1, 2), (2, 0)])

    def test_rdp_can_cancel_inside_one_long_contour(self):
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls >= 4
        with self.assertRaises(InterruptedError):
            SP._rdp([(index, index % 2) for index in range(10000)], .2, cancelled=cancel)
        self.assertEqual(calls, 4)

    def test_component_sweep_matches_independent_pixel_flood(self):
        rng = random.Random(148)
        for _ in range(80):
            runs = []
            for y in range(8):
                for _ in range(rng.randrange(7)):
                    x0 = rng.randrange(-10, 15)
                    runs.append((x0, y, x0 + rng.randrange(5), y))
            components, passthrough = SP._components_from_runs(runs)
            actual = {frozenset((x, y) for y, row in component.rows.items()
                                for x0, x1 in row for x in range(x0, x1 + 1))
                      for component in components}
            self.assertEqual(actual, expected_components(runs))
            self.assertEqual(sum(component.area for component in components), sum(map(len, actual)))
            self.assertEqual(passthrough, [])


class AxisComponentTests(unittest.TestCase):
    def test_nested_same_row_runs_are_one_connected_component(self):
        runs = [(0, 0, 20, 0), (2, 0, 4, 0), (10, 0, 12, 0), (18, 1, 25, 1)]
        result = ARP.horizontal_components(runs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['indices'], (0, 1, 2, 3))
        self.assertEqual(result[0]['runs'], tuple(runs))
        self.assertEqual(result[0]['pixels'], 29)

    def test_component_pixel_mass_counts_union_not_duplicate_runs(self):
        runs = [(0, 0, 3, 0), (2, 0, 6, 0), (0, 0, 3, 0), (3, 1, 4, 1), (20, 0, 22, 0)]
        result = ARP.horizontal_components(runs)
        self.assertEqual([row['pixels'] for row in result], [9, 3])
        self.assertEqual([row['indices'] for row in result], [(0, 1, 2, 3), (4,)])


if __name__ == '__main__':
    unittest.main()
