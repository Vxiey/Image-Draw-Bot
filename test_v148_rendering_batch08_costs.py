"""The shared budget prices controls that execute_plan actually performs (RP28)."""
import colorsys
from contextlib import ExitStack, closing
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from ExecutionCostModel import build_cost_model
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_transparency import standard_options


def brush_plan():
    return {'target_position': (25, 10), 'target_index': 1, 'effective_px': 5,
            'control_positions': [(15, 10), (25, 10)], 'nominal_sizes': [1, 5],
            'verified_sizes': [1, 5], 'confidence': .95, 'safe_guard_px': 5}


def phase_sequence():
    # Five selections: start, new phase, actual brush switch, green, red again.
    return [{'color_index': color, 'phase': phase, 'brush_px': brush,
             'path': ((10, 10 + i * 10), (30, 10 + i * 10))}
            for i, (color, phase, brush) in enumerate((
                (0, 'contour', 5), (0, 'contour', 5), (0, 'details', 5),
                (0, 'details', 1), (1, 'details', 1), (0, 'details', 1)))]


class RetainedOperationCostTests(unittest.TestCase):
    def model(self, **overrides):
        options = dict(profile_key='gartic-phone', brush_px=5, delay=0,
            exact_color_available=True, color_selectors=[{'kind': 'custom'}] * 2,
            adaptive_color_verification=True, browser_brush_plan=brush_plan(),
            _execution_cost_calibration_override={})
        options.update(overrides)
        return build_cost_model(options, (40, 80), (40, 80))

    def test_selection_resets_and_once_per_retained_colour_verification(self):
        for controls, selections in ((brush_plan(), 5), ({}, 4)):
            with self.subTest(verified_controls=bool(controls)):
                model = self.model(browser_brush_plan=controls)
                sequence = phase_sequence()
                # Empty geometry is not an executed phase or colour.
                sequence.insert(1, {'color_index': 31, 'phase': 'unused', 'path': ()})
                result = model.sequence_cost(sequence, initial_brush=5, include_color_verification=True)
                self.assertEqual(result.palette_switches, selections)
                self.assertAlmostEqual(result.palette_seconds, selections * model.delivery.palette_click_delay)
                self.assertAlmostEqual(result.custom_color_seconds, selections * .78)
                self.assertAlmostEqual(result.verification_seconds, 2 * model.switch_cost('verification'))
                self.assertEqual(result.brush_switches, 1)
                cursor = None
                geometry = 0.
                for entry in sequence:
                    if entry['path']:
                        geometry += model.path_cost(entry['path'], cursor=cursor,
                                                    brush_px=entry.get('brush_px')).total_seconds
                        cursor = entry['path'][-1]
                self.assertAlmostEqual(result.total_seconds, geometry + result.palette_seconds
                    + selections * .78 + model.switch_cost('brush_change')
                    + 2 * model.switch_cost('verification'))

    def test_complete_learned_custom_selection_replaces_default_dialog_cost(self):
        for palette_average in (None, .2, 1.4):
            with self.subTest(palette_average=palette_average):
                runtime = {'color_change': {'average_seconds': .9, 'count': 7}}
                if palette_average is not None:
                    runtime['palette_change'] = {'average_seconds': palette_average, 'count': 7}
                model = self.model(_execution_cost_calibration_override={
                    'samples': 5, 'ratio': 2., 'operation_runtime': runtime})
                parts = model.color_selection_cost(0)
                self.assertTrue(all(value >= 0 for value in parts))
                self.assertAlmostEqual(sum(parts), .9)
                sequence = model.sequence_cost(phase_sequence(), initial_brush=5)
                self.assertAlmostEqual(sequence.palette_seconds + sequence.custom_color_seconds, 5 * .9)

    def test_current_colour_and_unused_selectors_have_no_control_cost(self):
        model = self.model(paint_current_color=True)
        result = model.sequence_cost(phase_sequence(), initial_brush=5, include_color_verification=True)
        self.assertEqual((result.palette_seconds, result.custom_color_seconds,
                          result.verification_seconds, result.palette_switches), (0., 0., 0., 0))
        sparse = self.model(color_selectors=[{'kind': 'custom'}] * 32)
        sequence = [{'color_index': 0, 'phase': 'details', 'path': ((10, 10),)}]
        result = sparse.sequence_cost(sequence, initial_brush=5, include_color_verification=True)
        self.assertEqual(result.palette_switches, 1)
        self.assertEqual(result.custom_color_seconds, .78)
        self.assertEqual(result.verification_seconds, sparse.switch_cost('verification'))
        self.assertEqual(sparse.sequence_cost([], include_color_verification=True).total_seconds, 0.)

    def test_fake_native_executor_performs_the_same_phase_and_brush_reselections(self):
        from DrawBot import execute_plan
        from test_drawbot import Mouse, NoWait
        from test_visual_verification_v1043 import simple_visual_plan

        class PositionMouse(Mouse):
            def __init__(self):
                super().__init__()
                self.click_positions = []
            def click(self):
                self.click_positions.append(self.position)
                super().click()

        with ExitStack() as stack:
            plan = simple_visual_plan()
            plan['image'].close()
            plan['image'] = stack.enter_context(closing(Image.new('RGB', (40, 80), 'white')))
            sequence = phase_sequence()
            paths = [[entry['path'] for entry in sequence if entry['color_index'] == i] for i in range(2)]
            plan.update(fitted=(40, 80), execution_sequence=sequence, execution_groups=paths,
                        groups=[[(*path[0], *path[-1]) for path in group] for group in paths], count=len(sequence))
            plan['options'].update(brush_px=5, canvas_guard_brush_px=5, _planning_canvas_size=(120, 80),
                corners=((100, 100), (220, 180)), unlimited_time=True,
                strict_color_verification=False, adaptive_color_verification=False,
                visual_verification_enabled=False, visual_verification_resolved='Off',
                browser_brush_plan=brush_plan(), _execution_cost_calibration_override={})
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda s: s.as_dict()))
            stack.enter_context(patch('BrowserBrushSize.verify_brush_selection', return_value=True))
            for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name, return_value={}))
            model = build_cost_model(plan['options'], plan['image'].size, plan['fitted'])
            expected = model.sequence_cost(sequence, initial_brush=5)
            mouse = PositionMouse()
            execute_plan(plan, (100, 100, 120, 80), [(10, 10), (20, 10)], mouse,
                         NoWait(), threading.Event(), lambda *args: None, clock=lambda: 0)
            palette_clicks = [p for p in mouse.click_positions if p in ((10, 10), (20, 10))]
            self.assertEqual(palette_clicks, [(10, 10)] * 3 + [(20, 10), (10, 10)])
            self.assertEqual(expected.palette_switches, len(palette_clicks))
            self.assertEqual(sum(action[0] == 'press' for action in mouse.actions), len(sequence))
            self.assertFalse(mouse.held)

    def test_actual_hybrid_custom_budget_includes_only_retained_selection_controls(self):
        from DrawBot import make_plan
        with closing(Image.new('RGB', (64, 32), 'white')) as image, \
                patch('DrawTimeCalibration.load_profile', return_value=None):
            draw = ImageDraw.Draw(image)
            for y in range(4):
                for x in range(8):
                    draw.rectangle((x * 8, y * 8, x * 8 + 7, y * 8 + 7),
                        fill=tuple(round(v * 255) for v in colorsys.hsv_to_rgb(x / 8, .8, .2 + y * .25)))
            for budget, verify in ((10, False), (30, False), (30, True)):
                with self.subTest(budget=budget, adaptive_verify=verify):
                    options = standard_options(extra_fast=True, extra_fast_v2=True,
                        time_budget_mode='Custom', manual_max_seconds=budget, max_seconds=budget,
                        unlimited_time=False, deadline_safety_reserve='Off', profile_name='Microsoft Paint',
                        profile_key='microsoft-paint', paint_profile=True, exact_color_available=True,
                        custom_color_workflow='Exact custom + palette fallback', exact_color_limit='32',
                        color_fidelity='Faithful', adaptive_color_verification=verify,
                        _execution_cost_calibration_override={})
                    plan = make_plan(image, image.size, options)
                    try:
                        meta = plan['options']['adaptive_hybrid_meta']['schedule']
                        actual = meta['selected_operation_cost']
                        selections = []
                        previous = None
                        retained_colours = set()
                        for entry in plan['execution_sequence']:
                            key = (entry['color_index'], entry.get('phase', 'details'))
                            if key != previous:
                                selections.append(key[0])
                            previous = key
                            retained_colours.add(key[0])
                        self.assertTrue(selections)
                        custom_count = sum(plan['color_selectors'][i]['kind'] == 'custom' for i in selections)
                        self.assertLess(custom_count, sum(s['kind'] == 'custom' for s in plan['color_selectors']))
                        self.assertAlmostEqual(actual['custom_color_seconds'], custom_count * .78, places=5)
                        self.assertEqual(actual['palette_switches'], len(selections))
                        model = build_cost_model(plan['options'], plan['image'].size, plan['fitted'])
                        self.assertAlmostEqual(actual['palette_seconds'],
                                               len(selections) * model.delivery.palette_click_delay, places=5)
                        expected_verify = len(retained_colours) * model.switch_cost('verification') if verify else 0.
                        self.assertAlmostEqual(actual['verification_seconds'], expected_verify, places=5)
                        outside = meta['fixed_overhead']['outside_sequence_seconds']
                        self.assertEqual(meta['fixed_overhead']['adaptive_verification_seconds'], 0.)
                        self.assertLessEqual(outside + actual['total_seconds'], budget + .00001)
                    finally:
                        close_plan(plan, image)

    def test_actual_pixel_builder_prices_its_retained_phase_selections(self):
        from PixelAccuratePlanner import build_pixel_map
        from PixelStrokeEngine import build_pixel_stroke_plan
        palette = ((255, 255, 255), (200, 20, 30), (10, 90, 190))
        with closing(Image.new('RGB', (48, 32), 'white')) as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((4, 4, 32, 22), fill=palette[1])
            draw.line((39, 3, 39, 28), fill=palette[1])
            draw.rectangle((8, 8, 10, 10), fill=palette[2])
            pixel_map = build_pixel_map(image, palette, gpu_mode='CPU', skip_white=True)
            options = dict(brush_px=1, exact_color_available=True, adaptive_color_verification=True,
                color_selectors=[{'kind': 'palette'}, {'kind': 'custom'}, {'kind': 'custom'}],
                profile_key='microsoft-paint', _execution_cost_calibration_override={})
            plan = build_pixel_stroke_plan(pixel_map, len(palette), options=options)
            model = build_cost_model(options, image.size, image.size)
            sequence = plan['execution_sequence']
            selections = []
            previous = None
            for entry in sequence:
                key = (entry['color_index'], entry['phase'])
                if key != previous:
                    selections.append(key[0])
                previous = key
            geometry = model.paths_seconds([entry['path'] for entry in sequence])
            expected = geometry + len(selections) * (model.delivery.palette_click_delay + .78)
            expected += len({entry['color_index'] for entry in sequence}) * model.switch_cost('verification')
            self.assertGreaterEqual(len({entry['phase'] for entry in sequence}), 2)
            self.assertAlmostEqual(plan['metadata']['estimated_execution_seconds'], expected, places=4)
            self.assertEqual(plan['metadata']['cost_policy'], f'ExecutionCostModel stateful v{model.model_version}')


if __name__ == '__main__':
    unittest.main()
