import math
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from AccuracyEvaluator import _srgb_to_oklab
from ExecutionCostModel import build_cost_model
from PostDrawCorrectionPass import (
    _rank_correction_paths, build_post_draw_correction_plan, compact_correction_meta,
)
from RasterIdentity import canonical_pixels_from_paths


class CorrectionValueBudgetTests(unittest.TestCase):
    def setUp(self):
        self.options = {'gpu_mode': 'CPU', 'brush_px': 1, 'strict_color_verification': False,
                        '_execution_cost_calibration_override': {}}

    def test_public_budget_prices_real_paths_and_measures_only_selected_pixel_gain(self):
        directory = Path(__file__).parent / 'golden-regression'
        with Image.open(directory / 'small-detail-preservation.png') as source, \
                Image.open(directory / 'dominant-hue-four-color.png') as observed:
            palette = [rgb[:3] for _, rgb in sorted(source.getcolors(256), reverse=True)]
            args = dict(original_source=source, actual_canvas=observed, palette_rgb=palette,
                        post_draw_meta={'trusted': True, 'actual_coverage_percent': 80.0})
            options = dict(self.options, post_draw_correction_budget_seconds=1.0)
            result = build_post_draw_correction_plan(**args, options=options)
            repeat = build_post_draw_correction_plan(**args, options=options)
            generous = build_post_draw_correction_plan(**args, options=dict(options,
                post_draw_correction_budget_seconds=30.0))
            self.assertTrue(result['enabled'])
            self.assertEqual(result['execution_groups'], repeat['execution_groups'])
            self.assertLessEqual(result['estimated_seconds'], 1.0)
            self.assertLess(result['correction_paths'], generous['correction_paths'])
            model = build_cost_model(options, source.size, source.size)
            expected_time = 0.0
            centers = set()
            before = _srgb_to_oklab(np.asarray(source, dtype=np.float32)[..., :3] / 255.0)
            actual = _srgb_to_oklab(np.asarray(observed, dtype=np.float32)[..., :3] / 255.0)
            ink = _srgb_to_oklab(np.array(palette, dtype=np.float32).reshape(-1, 1, 3) / 255.0)[:, 0, :]
            gain = 0.0
            cursor = None
            for color in result['color_order']:
                expected_time += sum(model.color_selection_cost(color))
                for path in result['execution_groups'][color]:
                    expected_time += model.path_seconds(path, cursor=cursor)
                    cursor = path[-1]
                local = canonical_pixels_from_paths(result['execution_groups'][color])
                self.assertTrue(centers.isdisjoint(local))
                centers.update(local)
                for x, y in local:
                    old = (before[y, x] - actual[y, x]) ** 2
                    new = (before[y, x] - ink[color]) ** 2
                    difference = old - new
                    gain += float(difference.sum() + difference[0] * .65)
            self.assertAlmostEqual(result['estimated_seconds'], expected_time)
            self.assertAlmostEqual(result['predicted_error_reduction'], gain, delta=.001)
            self.assertEqual(result['selected_correction_pixels'], len(centers))
            compact = compact_correction_meta(result)
            self.assertEqual(compact['selection_policy'], 'quality_gain_per_second')
            self.assertGreater(compact['predicted_error_reduction_percent'], 0)
            self.assertLessEqual(compact['predicted_error_reduction_percent'], 100)
            self.assertNotIn('execution_groups', compact)
            for budget in (0, -1, math.nan, math.inf, True, '5'):
                with self.subTest(budget=budget):
                    disabled = build_post_draw_correction_plan(**args, options=dict(options,
                        post_draw_correction_budget_seconds=budget))
                    self.assertFalse(disabled['enabled'])

    def test_same_color_batch_charges_selection_and_unverified_probe_only_once(self):
        wanted = np.array([[0, -1, 0]], dtype=int)
        paths = [[((0, 0),), ((2, 0),)]]
        options = dict(self.options, strict_color_verification=True)
        model = build_cost_model(options, (3, 1), (3, 1))
        def cost(verified):
            result, _, _, spent, _ = _rank_correction_paths(
                paths, wanted, {0: 1.0, 2: 1.0}, model,
                dict(options, post_draw_correction_verified_colors=verified),
                0, 3, lambda: 10, lambda: False)
            self.assertEqual(result, paths)
            return spent
        base = model.paths_seconds(paths[0]) + sum(model.color_selection_cost(0))
        self.assertAlmostEqual(cost((0,)), base)
        self.assertAlmostEqual(cost(()), base + model.switch_cost('verification'))

    def test_inserting_in_earlier_batch_reprices_travel_to_following_color(self):
        wanted = np.array([[0, -1, 1, -1, -1, -1, 0]])
        paths = [[((0, 0),), ((6, 0),)], [((2, 0),)]]
        model = build_cost_model(self.options, (7, 1), (1400, 200))
        groups, _, _, spent, order = _rank_correction_paths(paths, wanted,
            {0: 3., 2: 2., 6: .001}, model, self.options, 0, 3, lambda: 5., lambda: False)
        self.assertEqual(groups, paths)
        self.assertEqual(order, [0, 1])
        expected = model.paths_seconds(paths[0] + paths[1])
        expected += sum(sum(model.color_selection_cost(i)) for i in order)
        self.assertAlmostEqual(spent, expected)
        # One-millisecond difference in the total allowance must remove the
        # least valuable path, including the change to the next colour's travel.
        groups, _, _, _, _ = _rank_correction_paths(paths, wanted, {0: 3., 2: 2., 6: .001},
            model, self.options, 0, 3, lambda: expected - .001, lambda: False)
        self.assertEqual(groups, [[((0, 0),)], [((2, 0),)]])

    def test_skips_gap_crossings_and_conflicting_brush_envelopes(self):
        wanted = np.array([[0, -1, 0, 1, -1, 1, -1, -1, 1]])
        paths = [[((0, 0), (2, 0)), ((2, 0),)], [((3, 0),), ((5, 0),), ((8, 0),)]]
        model = build_cost_model(self.options, (9, 1), (9, 1))
        groups, mask, gain, _, _ = _rank_correction_paths(
            paths, wanted, {0: 1., 2: 10., 3: 1., 5: 1., 8: 1.}, model, self.options,
            1, 8, lambda: 100., lambda: False)
        self.assertEqual(groups, [[((2,0),)], [((5,0),), ((8,0),)]])
        self.assertEqual(np.flatnonzero(mask).tolist(), [2, 5, 8])
        self.assertEqual(gain, 12.)
        with self.assertRaises(InterruptedError):
            _rank_correction_paths(paths, wanted, {}, model, self.options, 0, 3, lambda: 10, lambda: True)

    def test_costly_color_choice_can_lose_to_higher_gain_per_second(self):
        wanted = np.array([[0, -1, 1]])
        paths = [[((0, 0),)], [((2, 0),)]]
        options = dict(self.options, exact_color_available=True,
                       color_selectors=[{'kind': 'custom'}, {'kind': 'palette'}])
        model = build_cost_model(options, (3, 1), (3, 1))
        groups, _, gain, _, _ = _rank_correction_paths(
            paths, wanted, {0: 1.4, 2: 1.}, model, options, 0, 1, lambda: 5., lambda: False)
        self.assertEqual(groups, [[], [((2, 0),)]])
        self.assertEqual(gain, 1.)
