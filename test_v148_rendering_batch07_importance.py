from __future__ import annotations

from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from AdaptiveDeadlineRenderer import adapt_execution_plan
from VisualImportanceMap import sample_path_importance


class GeometricImportanceTests(unittest.TestCase):
    def test_stop_inside_long_collinear_and_backtracking_geometry(self):
        class ObservedPath(list):
            reads = 0
            def __iter__(self):
                for point in super().__iter__():
                    self.reads += 1
                    yield point
            def __reversed__(self):
                for point in super().__reversed__():
                    self.reads += 1
                    yield point
        values = np.ones((2, 2), np.float32)
        for geometry in ([(x, 0) for x in range(20000)], [(x % 2, 0) for x in range(20000)]):
            path = ObservedPath(geometry)
            with self.subTest(backtracking=geometry[2][0] == 0):
                with self.assertRaises(InterruptedError):
                    sample_path_importance(path, values, cancelled=lambda: path.reads >= 1000)
                self.assertLess(path.reads, 1300)

    def test_actual_deadline_forwards_stop_into_importance_sampling(self):
        import AdaptiveDeadlineRenderer as deadline
        state = {'sampling': False, 'checks': 0}
        def cancelled():
            if state['sampling']:
                state['checks'] += 1
            return state['checks'] >= 8
        def observed(*args, **kwargs):
            state['sampling'] = True
            return sample_path_importance(*args, **kwargs)
        options = {'time_budget_mode': 'Custom', 'manual_max_seconds': 30, 'gpu_mode': 'CPU'}
        with closing(Image.new('RGB', (8, 8), 'black')) as image, \
                patch.object(deadline, 'sample_path_importance', side_effect=observed):
            with self.assertRaises(InterruptedError):
                adapt_execution_plan(image, image.size, [[tuple((x, 0) for x in range(20000))]],
                                     options, cancelled=cancelled)
        self.assertEqual(state['checks'], 8)

    def test_short_segment_includes_each_pixel_once_in_either_direction(self):
        values = np.asarray([[0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1]], np.float32)
        # Eleven visible pixels: arithmetic mean=.5, the original high-order
        # statistic selects sorted pixel 7. Neither endpoint gets extra weight.
        expected = float(values.mean(dtype=np.float64)) * .62 + float(values[0, 7]) * .38
        for path in (((0, 0), (10, 0)), ((10, 0), (0, 0)),
                     ((0, 0), (1, 0), (1, 0), (2, 0), (7, 0), (10, 0))):
            with self.subTest(path=path):
                self.assertAlmostEqual(sample_path_importance(path, values), expected, places=14)

    def test_two_endpoint_segment_samples_important_interior(self):
        values = np.zeros((1, 23), np.float32)
        values[0, 5:18] = 1
        self.assertAlmostEqual(sample_path_importance(((0, 0), (22, 0)), values),
                               (13 / 23) * .62 + .38)

    def test_corners_backtracking_and_closed_geometry_are_invariant(self):
        rng = np.random.default_rng(7311)
        values = rng.random((64, 64), dtype=np.float32)
        cases = [
            (((1, 1), (41, 1), (41, 51)),
             ((1, 1), (3, 1), (19, 1), (41, 1), (41, 3), (41, 51))),
            (((1, 1), (41, 1), (9, 1), (9, 41)),
             ((1, 1), (11, 1), (41, 1), (33, 1), (9, 1), (9, 12), (9, 41))),
            (((1, 1), (41, 1), (41, 41), (1, 41), (1, 1)),
             ((1, 1), (11, 1), (41, 1), (41, 6), (41, 41), (19, 41), (1, 41), (1, 1))),
        ]
        for path, subdivided in cases:
            expected = sample_path_importance(path, values)
            for equivalent in (path[::-1], subdivided, subdivided[::-1]):
                with self.subTest(path=path, equivalent=equivalent):
                    self.assertEqual(sample_path_importance(equivalent, values), expected)

    def test_dot_duplicate_vertices_empty_map_and_clamped_pixels(self):
        values = np.asarray([[.2, .4], [.6, .8]], np.float32)
        self.assertEqual(sample_path_importance((), values), 0)
        self.assertEqual(sample_path_importance(((0, 0),), np.empty((0, 0))), 0)
        self.assertAlmostEqual(sample_path_importance(((1, 1),) * 5, values), float(values[1, 1]))
        self.assertAlmostEqual(sample_path_importance(((-10, -2), (-4, -2)), values), float(values[0, 0]))

    def test_actual_deadline_phase_no_longer_depends_on_stroke_direction(self):
        options = {'time_budget_mode': 'Custom', 'manual_max_seconds': 30,
                   'deadline_safety_reserve': 'Off', 'gpu_mode': 'CPU',
                   'paint_profile': True, 'paint_current_color': True,
                   '_execution_cost_calibration_override': {'samples': 0}}
        with closing(Image.new('RGB', (96, 96), 'white')) as image:
            ImageDraw.Draw(image).rectangle((20, 30, 80, 66), fill='black')
            results = []
            for path in (((20, 48), (30, 48)), ((30, 48), (20, 48)),
                         ((20, 48), (21, 48), (22, 48), (27, 48), (30, 48))):
                _, sequence, meta, importance = adapt_execution_plan(image, image.size, [[path]], options)
                self.assertTrue(meta['enabled'])
                self.assertEqual(len(sequence), 1)
                results.append(tuple(sequence[0][key] for key in ('importance', 'phase', 'optional', 'value_score')))
                self.assertGreater(float(importance[48, 20]), float(importance[48, 30]))
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0], results[2])


if __name__ == '__main__':
    unittest.main()
