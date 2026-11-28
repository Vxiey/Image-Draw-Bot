from collections import Counter
from contextlib import ExitStack
from pathlib import Path
import unittest

from PIL import Image

from DrawBot import make_plan
from ExecutionCostModel import build_cost_model
from GarticSketchPaths import _opaque_contour_route, trace_contours
from RasterIdentity import canonical_pixels_from_paths


class GarticContourDeliveryTests(unittest.TestCase):
    def test_normal_outline_plan_joins_only_verified_opaque_target(self):
        fixture = Path(__file__).parent / 'golden-regression' / 'small-detail-preservation.png'
        options = dict(detail=10, delay=.01, lines=True, skip_white=True, contrast=1.,
                       outline=True, profile_key='gartic-phone', brush_px=1, paint_current_color=True,
                       unlimited_time=True, _execution_cost_calibration_override={'samples': 0})
        control = dict(profile_key='gartic-phone', control_verified=True, target_position=(20, 20))
        with ExitStack() as stack:
            source = stack.enter_context(Image.open(fixture))
            plans = []
            for percent in (80, 100):
                plan = make_plan(source, (800, 600), dict(options, gartic_opacity_plan=dict(control, selected_percent=percent)))
                plans.append(plan)
                for key in ('image', 'preview'):
                    stack.callback(plan[key].close)
            original, joined = [plan['execution_groups'][0] for plan in plans]
            self.assertLess(len(joined), len(original))
            self.assertLess(plans[1]['estimate'], plans[0]['estimate'])
            self.assertEqual(plans[0]['preview'].tobytes(), plans[1]['preview'].tobytes())
            self.assertEqual(canonical_pixels_from_paths(original), canonical_pixels_from_paths(joined))
            def directed_segments(paths):
                return Counter((a, b) for path in paths for a, b in zip(path, path[1:]))
            self.assertEqual(directed_segments(original), directed_segments(joined))
            self.assertEqual(plans[1]['path_stats']['contour_pen_lifts_saved'], len(original) - len(joined))
            self.assertTrue(all(len(path) <= 160 for path in joined))
            for override in ({'control_verified': False}, {'target_position': None}, {'profile_key': 'gartic-io'}):
                actual, meta = trace_contours(plans[0]['image'], fitted_size=plans[0]['fitted'],
                    options=dict(options, gartic_opacity_plan=dict(control, selected_percent=100, **override)))
                self.assertEqual(actual, original)
                self.assertEqual(meta['contour_pen_lifts_saved'], 0)

    def test_fitted_canvas_calibration_can_make_two_separate_paths_faster(self):
        paths = [((0, 0), (5, 0)), ((5, 0), (10, 0))]
        options = {'profile_key': 'gartic-phone', '_execution_cost_calibration_override': {
            'samples': 5, 'operation_runtime': {'short_stroke': {'average_seconds': .02},
                                              'long_stroke': {'average_seconds': .2}}}}
        small = build_cost_model(options, (20, 10), (20, 10))
        large = build_cost_model(options, (20, 10), (80, 40))
        self.assertEqual(len(_opaque_contour_route(paths, None, small, 160, lambda: False)[0]), 1)
        self.assertEqual(_opaque_contour_route(paths, None, large, 160, lambda: False), (paths, 0.))
        with self.assertRaises(InterruptedError):
            _opaque_contour_route(paths, None, small, 160, lambda: True)

    def test_joined_gestures_keep_point_limit_and_gaps(self):
        model = build_cost_model({'_execution_cost_calibration_override': {'samples': 0}}, (80, 80), (110, 90))
        paths = [((i, 0), (i + 1, 0)) for i in range(9)] + [((20, 0), (22, 0))]
        joined, _ = _opaque_contour_route(paths, None, model, 4, lambda: False)
        self.assertLess(len(joined), len(paths))
        self.assertTrue(all(len(path) <= 4 for path in joined))
        self.assertEqual(canonical_pixels_from_paths(paths), canonical_pixels_from_paths(joined))
