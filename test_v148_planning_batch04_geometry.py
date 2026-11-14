import math
import random
import unittest
from collections import Counter

from PIL import Image, ImageDraw

import DetailZoomPass as zoom
import SpeedOptimizer as speed
import StrokeOptimizer as strokes


def distance(paths):
    return sum(math.dist(a[-1], b[0]) for a, b in zip(paths, paths[1:]))


def segments(paths):
    return Counter(tuple(sorted((a, b))) for path in paths for a, b in zip(path, path[1:]))


class TravelNonRegressionTests(unittest.TestCase):
    def test_known_greedy_regressions_keep_shorter_original_routes(self):
        paths = [((6, 9), (14, 12)), ((17, 18), (4, 4)), ((8, 10), (18, 6)), ((19, 14), (10, 2))]
        out, meta = strokes.optimize_path_group(paths, mode='Travel only')
        self.assertEqual(out, paths)
        self.assertAlmostEqual(meta['optimizer_pen_up_after'], 21.981564231725898)
        source = [(6, 16, 2, 3), (1, 17, 12, 9), (16, 7, 4, 16), (6, 18, 9, 14)]
        self.assertEqual(speed.optimize_strokes(source, 'Balanced'), source)

    def test_random_paths_never_increase_travel_or_change_geometry(self):
        rng = random.Random(14804)
        for _ in range(90):
            paths = [((rng.randrange(30), rng.randrange(30)), (rng.randrange(30), rng.randrange(30))) for _ in range(rng.randrange(4, 32))]
            paths = [p for p in paths if p[0] != p[1]]
            for reverse in (False, True):
                out, _ = strokes.optimize_path_group(paths, mode='Travel only', allow_reverse=reverse)
                self.assertLessEqual(distance(out), distance(paths) + 1e-9)
                self.assertEqual(segments(out), segments(paths))
                if not reverse:
                    self.assertEqual(Counter(out), Counter(paths))
                flat = [(*p[0], *p[1]) for p in paths]
                ordered = speed.optimize_strokes(flat, 'Safe', allow_reverse=reverse)
                restored = [(s[:2], s[2:]) for s in ordered]
                self.assertLessEqual(distance(restored), distance(paths) + 1e-9)
                self.assertEqual(segments(restored), segments(paths))
                self.assertEqual(ordered[0] in (flat[0], speed._reverse(flat[0])), True)

    def test_aliases_select_same_path_search_and_two_opt_budget(self):
        paths = [((i % 4, i * 9 % 37), (i % 4 + 2, i * 9 % 37)) for i in range(150)]
        for alias, canonical in speed.LEGACY_SPEED_NAMES.items():
            self.assertEqual(strokes._nearest_order(paths, speed=alias), strokes._nearest_order(paths, speed=canonical))
            self.assertEqual(strokes._two_opt_budget(alias, 400), strokes._two_opt_budget(canonical, 400))


class DetailPassDeliveryTests(unittest.TestCase):
    def test_detail_pass_follows_complete_base_for_both_color_orders(self):
        palette = ((0, 0, 0), (255, 255, 255))
        with Image.new('RGB', (64, 64), 'white') as source, Image.new('RGB', (16, 16), 'white') as work:
            draw = ImageDraw.Draw(source)
            for x in range(6, 11):
                draw.line((x * 4, 24, x * 4 + 3, 27), fill='black')
            groups = [[(0, 0, 0, 0)], [(0, y, 15, y) for y in range(16)]]
            execution = [[((0, 0),)], [((0, y), (15, y)) for y in range(16)]]
            for order in ((0, 1), (1, 0)):
                options = dict(detail_zoom='4x', draw_quality='Maximum likeness', time_budget_active=False,
                    skip_white=False, brush_px=1, color_fidelity='Faithful', color_rendering='Perceptual match',
                    profile_key='microsoft-paint', effective_paint_tool='Pencil', delay=.002, color_order=order)
                new_groups, new_execution, sequence, meta = zoom.add_detail_zoom_pass(
                    source, work, palette, groups, execution, [], options, fitted=(64,64))
                self.assertTrue(meta['enabled'])
                self.assertTrue(meta['sequence_created_for_detail_pass'])
                expected_base = [(ci, tuple(path)) for ci in order for path in execution[ci]]
                self.assertEqual([(row['color_index'], row['path']) for row in sequence[:17]], expected_base)
                details = sequence[17:]
                self.assertTrue(details)
                self.assertTrue(all(row.get('detail_zoom') for row in details))
                self.assertEqual(meta['sequence_base_paths'], 17)
                self.assertEqual(meta['detail_paths_added'], len(details))
                self.assertEqual(sum(map(len, new_execution)), len(sequence))
                with Image.new('RGB', (16, 16), 'magenta') as canvas:
                    painter = ImageDraw.Draw(canvas)
                    for row in sequence:
                        path = row['path']
                        painter.line(path if len(path) > 1 else (path[0], path[0]), fill=palette[row['color_index']])
                    for row in details:
                        for point in row['path']:
                            self.assertEqual(canvas.getpixel(point), (0, 0, 0))
                    self.assertEqual(canvas.getpixel((15, 15)), (255, 255, 255))
                self.assertEqual(groups, [[(0, 0, 0, 0)], [(0, y, 15, y) for y in range(16)]])

    def test_materialized_base_preserves_phase_hints_and_checks_stop(self):
        from ContinuousPaths import ExecutionGroups
        groups = ExecutionGroups([[((0, 0),), ((1, 1),)]], phase_hints=[['contour', 'tone']])
        sequence = zoom._base_color_sequence(groups, {}, lambda: False)
        self.assertEqual([row['phase'] for row in sequence], ['contour', 'tone'])
        with self.assertRaises(InterruptedError):
            zoom._base_color_sequence(groups, {}, lambda: True)


if __name__ == '__main__':
    unittest.main()
