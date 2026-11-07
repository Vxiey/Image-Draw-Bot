"""RP02/RP28 completion: price the moves and controls actually delivered."""
from contextlib import ExitStack
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot
from ExecutionCostModel import build_cost_model
from test_drawbot import Mouse, NoWait
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_single_brush import options as brush_options, rectangle_source


class DeliveryMouse(Mouse):
    def __init__(self):
        super().__init__()
        self.drag_moves = []
        self.drag_paths = []

    def press(self):
        super().press()
        self.drag_paths.append([])

    def move(self, x, y):
        if self.held:
            self.drag_moves.append((x, y))
            self.drag_paths[-1].append((x, y))
        super().move(x, y)


class RecordingWait(NoWait):
    def __init__(self, mouse):
        super().__init__()
        self.mouse = mouse
        self.waits = []

    def wait(self, seconds):
        self.waits.append((self.mouse.position, self.mouse.held, seconds))
        return self.stopped


class NativeDeliveryCostTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        for target in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                       'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(target, return_value={}))

    def plan(self, source, settings):
        self.stack.callback(source.close)
        plan = DrawBot.make_plan(source, source.size, settings)
        self.stack.callback(close_plan, plan, source)
        return plan

    def line_plan(self, **changes):
        source = Image.new('RGBA', (96, 32), 'white')
        ImageDraw.Draw(source).line((8, 16, 87, 16), fill='black')
        settings = opts(profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_profile=True, skip_white=True, cpu_workers_resolved=1,
            unlimited_time=True, time_budget_mode='Unlimited', detail_zoom='Off',
            canvas_edge_verification='Off', strict_color_verification=False,
            adaptive_color_verification=False, visual_verification_enabled=False,
            post_draw_correction_pass='Off', _execution_cost_calibration_override={})
        settings.update(changes)
        return self.plan(source, settings)

    def execute(self, plan):
        mouse = DeliveryMouse()
        stop = RecordingWait(mouse)
        area = (100, 100, *plan['image'].size)
        palette = [(50 + index * 5, 10) for index in range(len(plan['colors']))]
        DrawBot.execute_plan(plan, area, palette, mouse, stop, threading.Event(),
                             lambda *args: None, clock=lambda: 0.)
        self.assertFalse(mouse.held)
        self.assertEqual(plan['options']['runtime_path_counts']['sent'], plan['count'])
        self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)
        return mouse, stop

    def assert_line_motion(self, plan):
        mouse, stop = self.execute(plan)
        self.assertEqual(plan['count'], 1)
        self.assertEqual(plan['execution_groups'][0], [((8, 16), (87, 16))])
        model = build_cost_model(plan['options'], plan['image'].size, plan['fitted'])
        cost = model.path_cost(plan['execution_groups'][0][0], brush_px=1)
        self.assertEqual(cost.moves, len(mouse.drag_moves))
        # The fixture has no in-canvas controls, corrections, human cadence or
        # extra probes. Every wait inside its actual canvas belongs to motion.
        actual_motion = sum(seconds for (x, y), _held, seconds in stop.waits
                            if 100 <= x < 196 and 100 <= y < 132)
        self.assertAlmostEqual(plan['options']['operation_timing_meta']['motion_seconds'],
                               actual_motion, places=4)
        return mouse, cost

    def test_real_pixel_plan_prices_its_native_one_pixel_brush_density(self):
        plan = self.line_plan()
        self.assertTrue(plan['options']['pixel_accurate'])
        mouse, cost = self.assert_line_motion(plan)
        self.assertEqual(len(mouse.drag_moves), 53)
        self.assertEqual(cost.moves, 53)

    def test_preview_fallback_uses_the_same_native_pixel_density(self):
        with patch('DrawBot.build_preview_safety_plan', side_effect=ValueError('preview unavailable')):
            plan = self.line_plan()
        self.assertFalse(plan['options']['preview_safety_meta']['active'])
        self.assert_line_motion(plan)

    def test_current_color_paint_without_pixel_geometry_keeps_its_existing_density(self):
        plan = self.line_plan(paint_current_color=True)
        self.assertFalse(plan['options'].get('pixel_accurate'))
        mouse, cost = self.assert_line_motion(plan)
        self.assertEqual((len(mouse.drag_moves), cost.moves), (40, 40))

    def test_final_sequence_and_preview_fallback_price_each_physical_brush(self):
        previews = []
        for fail_preview in (False, True):
            with self.subTest(fail_preview=fail_preview):
                source = Image.new('RGBA', (96, 64), 'white')
                self.stack.callback(source.close)
                paths = [((8, y), (87, y)) for y in (16, 32, 48)]
                sequence = [dict(color_index=0, path=path, phase='details') for path in paths]
                sequence[0]['brush_px'] = 5
                sequence[1]['brush_px'] = 1
                # Empty rows have no native operation and cannot change the
                # width inherited by the following real path.
                sequence.insert(2, dict(color_index=0, path=(), brush_px=5, phase='details'))
                controls = dict(profile_key='gartic-phone', target_position=(10, 10), target_index=0,
                    effective_px=5, confidence=.99, nominal_sizes=[5, 1], verified_sizes=[5, 1],
                    control_positions=[(10, 10), (20, 10)], safe_guard_px=5)
                settings = opts(profile_name='Gartic Phone', profile_key='gartic-phone', brush_px=5,
                    pixel_accurate=True, plan_palette_rgb=((0, 0, 0),), browser_brush_plan=controls,
                    _pixel_execution_groups=[paths], _pixel_execution_sequence=sequence,
                    _planning_canvas_size=source.size, unlimited_time=True, time_budget_mode='Unlimited',
                    detail_zoom='Off', canvas_edge_verification='Off', strict_color_verification=False,
                    adaptive_color_verification=False, visual_verification_enabled=False,
                    post_draw_correction_pass='Off', _execution_cost_calibration_override={})
                with ExitStack() as local:
                    if fail_preview:
                        local.enter_context(patch('DrawBot.build_preview_safety_plan',
                                                  side_effect=ValueError('preview unavailable')))
                    plan = DrawBot.finish_plan(source, source.size,
                        [[(*path[0], *path[-1]) for path in paths]], settings)
                self.stack.callback(close_plan, plan, source)
                previews.append(plan['preview'].tobytes())
                with patch('BrowserBrushSize.verify_brush_selection', return_value=True):
                    mouse, stop = self.execute(plan)
                self.assertEqual([len(path) for path in mouse.drag_paths], [40, 53, 53])
                model = build_cost_model(plan['options'], source.size, plan['fitted'])
                cost = model.sequence_cost(plan['execution_sequence'], initial_brush=5)
                self.assertEqual(cost.moves, len(mouse.drag_moves))
                actual_motion = sum(seconds for (x, y), _held, seconds in stop.waits
                                    if 100 <= x < 196 and 100 <= y < 164)
                self.assertAlmostEqual(plan['options']['operation_timing_meta']['motion_seconds'],
                                       actual_motion, places=4)
        self.assertEqual(previews[0], previews[1])

    def test_final_public_summary_keeps_the_actual_verified_brush_switch_waits(self):
        plan = self.plan(rectangle_source(), brush_options())
        self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']}, {16})
        self.stack.enter_context(patch('BrowserBrushSize.verify_brush_selection', return_value=True))
        mouse, stop = self.execute(plan)
        controls = {tuple(point) for point in plan['options']['browser_brush_plan']['control_positions']}
        actual_control_wait = sum(seconds for position, _held, seconds in stop.waits if position in controls)
        # Observed on the reference executor before the pricing correction;
        # sharing the timing policy must not change the native waits to make
        # an optimistic model appear correct.
        self.assertAlmostEqual(actual_control_wait, .13825)
        self.assertEqual(plan['options']['adaptive_brush_runtime_meta']['switches'], 1)
        model = build_cost_model(plan['options'], plan['image'].size, plan['fitted'])
        controls_cost = model.sequence_cost(plan['execution_sequence'], initial_brush=2, include_geometry=False)
        self.assertEqual(controls_cost.brush_switches, 1)
        self.assertAlmostEqual(controls_cost.brush_seconds, actual_control_wait)
        summary = plan['options']['operation_timing_meta']
        self.assertAlmostEqual(summary['brush_seconds'], actual_control_wait, places=4)
        self.assertAlmostEqual(summary['operation_overhead_seconds'], sum(summary[name] for name in
            ('palette_seconds', 'custom_color_seconds', 'brush_seconds', 'fill_seconds',
             'tool_seconds', 'canvas_clear_seconds', 'verification_seconds')), delta=.0004)


if __name__ == '__main__':
    unittest.main()
