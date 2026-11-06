from __future__ import annotations

import colorsys
from contextlib import closing
import math
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import AdaptiveDeadlineRenderer as deadline
from StrokeDelivery import resolve_stroke_delivery


class ConditionalColourAdmissionTests(unittest.TestCase):
    def options(self, **extra):
        return dict(time_budget_mode='Custom', manual_max_seconds=30,
                    deadline_safety_reserve='Off', gpu_mode='CPU', paint_profile=True,
                    exact_color_available=True, color_selectors=[{'kind': 'custom'} for _ in range(32)],
                    **extra)

    def plan(self, groups, options):
        # Isolate admission from image classification and path-timing variance.
        # The actual production caller is separately exercised below.
        with closing(Image.new('RGB', (16, 16), 'black')) as image, \
                patch.object(deadline, 'build_importance_map', return_value=(np.ones((16, 16), np.float32), {})), \
                patch.object(deadline, '_calibration_guard', return_value=(0, {'cost_multiplier': 1})), \
                patch.object(deadline, '_path_cost', return_value=.1):
            return deadline.adapt_execution_plan(image, image.size, groups, options)

    def test_unused_custom_selectors_and_empty_groups_do_not_consume_time(self):
        source = [[((5, 5),)] * 4]
        small = self.options()
        small['color_selectors'] = small['color_selectors'][:1]
        _, first, first_meta, _ = self.plan(source, small)
        _, second, second_meta, _ = self.plan(source + [[()] for _ in range(31)], self.options())
        self.assertEqual(first, second)
        self.assertEqual(first_meta, second_meta)
        self.assertEqual(len(second), 4)
        self.assertAlmostEqual(second_meta['ordered_delivery']['ordered_custom_color_seconds'], .78)

    def test_only_admitted_colours_are_billed_before_final_ordering(self):
        options = self.options(adaptive_color_verification=True, visual_verification_enabled=True)
        groups = [[((5, 5),)] for _ in range(32)]
        _, sequence, meta, _ = self.plan(groups, options)
        delivery = resolve_stroke_delivery(options, dry_run=False)
        unavoidable = 3 + 32 * .0009 + .25 + 32 * .0018
        one_colour = delivery.palette_click_delay + .78 + delivery.palette_click_delay + .14
        expected_count = math.floor((30 - unavoidable) / (.1 + one_colour))
        self.assertEqual(len(sequence), expected_count)
        self.assertGreater(expected_count, 0)
        self.assertLess(expected_count, 32)
        self.assertAlmostEqual(meta['estimated_after_seconds'],
                               unavoidable + expected_count * (.1 + one_colour), places=4)
        self.assertGreater(meta['estimated_before_seconds'], 30)
        self.assertLessEqual(meta['effective_estimated_seconds'], 30)
        self.assertEqual(meta['ordered_delivery']['ordered_palette_changes'], expected_count)

    def test_same_colour_phase_reset_reselects_without_repeating_verification(self):
        from Precision import CanvasTransform
        entries = [deadline.DeadlineEntry(0, ((5, 5),), i, .1, .8, .8, .8,
                    phase, False, (5, 5)) for i, phase in enumerate(('structure', 'accuracy'))]
        retained, meta = deadline._fit_ordered_delivery(entries, CanvasTransform(10, 10, (10, 10)),
            palette_seconds=.2, multiplier=1, fixed_seconds=0, reserve_seconds=0,
            budget_seconds=3, color_extras={0: (.78, .3)})
        self.assertEqual(meta['ordered_palette_changes'], 2)
        self.assertAlmostEqual(meta['ordered_custom_color_seconds'], 1.56)
        self.assertAlmostEqual(meta['ordered_verification_seconds'], .3)
        self.assertAlmostEqual(retained[0].estimated_cost_seconds, .1 + .2 + .78 + .3)
        self.assertAlmostEqual(retained[1].estimated_cost_seconds, .1 + .2 + .78)

    def test_trimming_transfers_first_colour_verification_or_refunds_last_occurrence(self):
        from Precision import CanvasTransform
        for colors, expected_sources, expected_verification in (((0, 0), [1], .3), ((0, 1), [1], .4)):
            with self.subTest(colors=colors):
                entries = [deadline.DeadlineEntry(color, ((5, 5),), i, .1, .8, .8, .8,
                            phase, phase == 'correction', (5, 5))
                           for i, (color, phase) in enumerate(zip(colors, ('correction', 'structure')))]
                retained, meta = deadline._fit_ordered_delivery(entries, CanvasTransform(10, 10, (10, 10)),
                    palette_seconds=.2, multiplier=1, fixed_seconds=0, reserve_seconds=0,
                    budget_seconds=1.5, color_extras={0: (.78, .3), 1: (.78, .4)})
                self.assertEqual([entry.source_index for entry in retained], expected_sources)
                self.assertAlmostEqual(meta['ordered_verification_seconds'], expected_verification)
                self.assertAlmostEqual(retained[0].estimated_cost_seconds, .1 + .2 + .78 + expected_verification)

    def test_ordinary_deadline_does_not_charge_skipped_batch_visual_verification(self):
        groups = [[((5, 5),)]]
        _, _, plain, _ = self.plan(groups, self.options())
        _, _, flagged, _ = self.plan(groups, self.options(visual_verification_enabled=True))
        self.assertEqual(flagged, plain)

    def test_minimum_budget_can_admit_a_colour_without_buying_the_whole_palette(self):
        options = self.options()
        options['manual_max_seconds'] = 5
        _, sequence, meta, _ = self.plan([[((5, 5),)] for _ in range(32)], options)
        self.assertGreater(len(sequence), 0)
        self.assertLessEqual(meta['effective_estimated_seconds'], 5)

    def test_current_colour_and_empty_plans_never_pay_stale_colour_controls(self):
        groups = [[((5, 5),)] * 3] + [[] for _ in range(31)]
        plain = self.options(paint_current_color=True)
        flagged = self.options(paint_current_color=True, adaptive_color_verification=True,
                               visual_verification_enabled=True)
        _, sequence, meta, _ = self.plan(groups, flagged)
        _, expected, expected_meta, _ = self.plan(groups, plain)
        self.assertEqual(sequence, expected)
        self.assertEqual(meta['estimated_before_seconds'], expected_meta['estimated_before_seconds'])
        self.assertEqual(meta['effective_estimated_seconds'], expected_meta['effective_estimated_seconds'])
        for key in ('ordered_palette_seconds', 'ordered_custom_color_seconds', 'ordered_verification_seconds'):
            self.assertEqual(meta['ordered_delivery'][key], 0)
        _, empty, empty_meta, _ = self.plan([[] for _ in range(32)], self.options())
        self.assertFalse(empty)
        self.assertEqual(empty_meta['estimated_before_seconds'], 3.25)

    def test_actual_make_plan_with_manual_32_colour_limit_keeps_useful_geometry(self):
        from DrawBot import make_plan
        from test_pixel_accurate_v1086 import opts
        from test_v148_rendering_batch06_canvas import close_plan
        settings = opts(render_preset='Manual', draw_quality='High likeness', planning_resolution='Standard',
            time_budget_mode='Custom', manual_max_seconds=30, max_seconds=30, deadline_safety_reserve='Off',
            profile_name='Microsoft Paint', profile_key='microsoft-paint', paint_profile=True,
            exact_color_available=True, custom_color_workflow='Exact custom + palette fallback',
            exact_color_limit='32', detail_zoom='Off', use_region_fill_engine=False,
            target_stroke_count='Unlimited', color_fidelity='Faithful', _execution_cost_calibration_override={})
        with closing(Image.new('RGB', (64, 32), 'white')) as image, \
                patch('DrawTimeCalibration.load_profile', return_value=None):
            draw = ImageDraw.Draw(image)
            for y in range(4):
                for x in range(8):
                    rgb = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(x / 8, .8, .2 + y * .25))
                    draw.rectangle((x * 8, y * 8, x * 8 + 7, y * 8 + 7), fill=rgb)
            plan = make_plan(image, image.size, settings)
            try:
                meta = plan['options']['adaptive_deadline_meta']
                self.assertTrue(meta['enabled'])
                self.assertEqual(plan['options']['adaptive_color_count_meta']['policy'], 'manual')
                self.assertGreater(sum(s['kind'] == 'custom' for s in plan['color_selectors']), 20)
                self.assertGreater(meta['selected_paths'], 0)
                self.assertLess(meta['selected_paths'], meta['source_paths'])
                self.assertEqual(plan['count'], meta['selected_paths'])
                self.assertLessEqual(meta['effective_estimated_seconds'], 30)
                self.assertGreater(meta['estimated_before_seconds'], 30)
                selections = []
                previous = None
                for entry in plan['execution_sequence']:
                    selection = (entry['color_index'], entry.get('phase', 'details'))
                    if selection != previous:
                        selections.append(selection[0])
                    previous = selection
                custom_count = sum(plan['color_selectors'][i]['kind'] == 'custom' for i in selections)
                self.assertLess(custom_count, sum(s['kind'] == 'custom' for s in plan['color_selectors']))
                self.assertAlmostEqual(plan['options']['operation_timing_meta']['custom_color_seconds'], .78 * custom_count)
            finally:
                close_plan(plan, image)

    def test_actual_empty_deadline_plan_reports_no_custom_or_palette_overhead(self):
        from DrawBot import make_plan
        from test_pixel_accurate_v1086 import opts
        from test_v148_rendering_batch06_canvas import close_plan
        settings = opts(render_preset='Manual', draw_quality='High likeness', planning_resolution='Standard',
            time_budget_mode='Custom', manual_max_seconds=5, max_seconds=5, deadline_safety_reserve='Off',
            profile_name='Microsoft Paint', profile_key='microsoft-paint', paint_profile=True,
            exact_color_available=True, custom_color_workflow='Exact custom + palette fallback',
            exact_color_limit='32', detail_zoom='Off', use_region_fill_engine=False,
            adaptive_color_verification=True, target_stroke_count='Unlimited', _execution_cost_calibration_override={})
        with closing(Image.new('RGB', (32, 24), (95, 77, 141))) as image, \
                patch('DrawTimeCalibration.load_profile', return_value=None):
            plan = make_plan(image, image.size, settings)
            try:
                self.assertTrue(plan['color_selectors'])
                self.assertEqual(plan['options']['adaptive_deadline_meta']['selected_paths'], 0)
                self.assertEqual(plan['count'], 0)
                for key in ('palette_seconds', 'custom_color_seconds', 'verification_seconds'):
                    self.assertEqual(plan['options']['operation_timing_meta'][key], 0)
            finally:
                close_plan(plan, image)

    def test_actual_prebuilt_sequence_summary_includes_same_colour_phase_reset(self):
        from DrawBot import finish_plan
        from test_pixel_accurate_v1086 import opts
        from test_v148_rendering_batch06_canvas import close_plan
        paths = [((3, y), (8, y)) for y in (3, 5, 7)]
        sequence = [dict(color_index=0, path=path, phase=phase) for path, phase in
                    zip(paths, ('structure', 'structure', 'accuracy'))]
        settings = opts(draw_quality='High likeness', detail_zoom='Off', time_budget_mode='Unlimited',
            unlimited_time=True, exact_color_available=True, plan_palette_rgb=((95, 77, 141), (20, 200, 90)),
            visual_verification_enabled=True, visual_verification='Strict', visual_verification_resolved='Strict',
            color_selectors=({'kind': 'custom'}, {'kind': 'custom'}),
            _pixel_execution_groups=[paths, []], _pixel_execution_sequence=sequence)
        with closing(Image.new('RGBA', (12, 12), 'white')) as image:
            plan = finish_plan(image, image.size, [[(3, y, 8, y) for y in (3, 5, 7)], []], settings)
            try:
                self.assertEqual(plan['execution_sequence'], sequence)
                timing = plan['options']['operation_timing_meta']
                self.assertAlmostEqual(timing['custom_color_seconds'], 2 * .78)
                self.assertEqual(timing['verification_seconds'], 0)
                delivery = resolve_stroke_delivery(plan['options'], dry_run=False)
                self.assertAlmostEqual(timing['palette_seconds'], 2 * delivery.palette_click_delay, places=4)
            finally:
                close_plan(plan, image)


if __name__ == '__main__':
    unittest.main()
