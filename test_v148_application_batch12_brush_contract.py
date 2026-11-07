"""Automatic quality policy cannot invent a physically unavailable brush."""
from contextlib import ExitStack, closing
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import DrawBot
import EndToEndAutoTuner
from BrowserBrushSize import plan_browser_brush_size
from EndToEndAutoTuner import evaluate_plan_acceptance, propose_rescue_options
from test_drawbot import Mouse, NoWait
from test_precision_v102 import Value
from test_step11_end_to_end_auto_tuner_v10135 import texture_image
from test_v148_rendering_batch06_canvas import close_plan
import test_v148_ui_batch07_renderer as ui_fixtures


AREA = (96, 64)
ORIGIN = (1000, 1000)


class PhysicalBrushMouse(Mouse):
    """Rasterize the actual sent input with an independently fixed native width.

    The second raster applies the plan's declared default to exactly the same
    native coordinates. With no brush controls, this isolates the reported
    footprint mismatch without resizing a planner bitmap or changing the input
    guards. Verified control clicks change both widths to their real size.
    """
    def __init__(self, physical, modeled, palette, *, model_width, controls=None):
        super().__init__()
        self.physical = physical
        self.modeled = modeled
        self.palette = {point: index for index, point in enumerate(palette)}
        self.controls = dict(controls or {})
        self.brush = 4
        self.model_width = int(model_width)
        self.color = None
        self.ink_widths = []
        self.brush_clicks = []

    def _inside(self, point):
        return all(origin <= coordinate < origin + extent
                   for coordinate, origin, extent in zip(point, ORIGIN, AREA))

    def _paint(self, start, end):
        if self.color is None:
            raise AssertionError('A real palette selection must precede ink.')
        if start[0] != end[0] and start[1] != end[1]:
            raise AssertionError('This Pixel fixture must send orthogonal strokes.')
        self.ink_widths.append(self.brush)
        for surface, width in ((self.physical, self.brush), (self.modeled, self.model_width)):
            before, after = (width - 1) // 2, width // 2
            ImageDraw.Draw(surface).rectangle((
                min(start[0], end[0]) - ORIGIN[0] - before,
                min(start[1], end[1]) - ORIGIN[1] - before,
                max(start[0], end[0]) - ORIGIN[0] + after,
                max(start[1], end[1]) - ORIGIN[1] + after,
            ), fill=self.color)

    def move(self, x, y):
        previous = self.position
        super().move(x, y)
        if self.held:
            self._paint(previous, self.position)

    def press(self):
        super().press()
        self._paint(self.position, self.position)

    def click(self):
        super().click()
        if self.position in self.controls:
            self.brush = self.controls[self.position]
            self.model_width = self.brush
            self.brush_clicks.append(self.brush)
        elif self.position in self.palette:
            self.color = self.palette[self.position]
        elif self._inside(self.position):
            self._paint(self.position, self.position)


class PhysicalBrushContractTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
        self.stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.stack.enter_context(patch('AutoTunerFeedback._resolved_path', return_value=directory / 'feedback.json'))
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
        for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(name, return_value={}))
        with closing(texture_image()) as texture:
            self.source = self.stack.enter_context(closing(texture.resize((48, 32))))
        self.line_art = self.stack.enter_context(closing(Image.new('RGB', (48, 32), 'white')))
        ImageDraw.Draw(self.line_art).line(((12, 8), (36, 24)), fill='black', width=1)

    def options(self, *, profile='Other drawing app', preset='Auto', mode='Custom', requested='4', source=None, seconds=60):
        app = ui_fixtures.AdvertisedRendererTests().app(profile)
        for name, value in dict(brush_px=requested, render_style='Standard / pixel', render_preset=preset,
                                time_budget_mode=mode, max_seconds=str(seconds), draw_quality='High likeness',
                                drawing_style='Auto').items():
            setattr(app, name, Value(value))
        app.original = self.source if source is None else source
        app.corners = (ORIGIN, tuple(a + b for a, b in zip(ORIGIN, AREA)))
        app.area = lambda: (*ORIGIN, *AREA)
        options = DrawBot.DrawBotApp.options(app)
        # Isolate learned cost only; actual UI options, policy, acceptance and
        # all renderer/finalizer calls remain real.
        options['_execution_cost_calibration_override'] = {}
        return options

    def plan(self, source, options):
        proposals = []
        def observe(plan, acceptance=None):
            result = propose_rescue_options(plan, acceptance)
            if result is not None:
                proposals.append((dict(acceptance or evaluate_plan_acceptance(plan)), result))
            return result
        with patch.object(EndToEndAutoTuner, 'propose_rescue_options', side_effect=observe):
            plan = DrawBot.make_plan(source, AREA, options)
        self.stack.callback(close_plan, plan, source)
        return plan, proposals

    def execute(self, plan, *, verification=True):
        physical = self.stack.enter_context(closing(Image.new('I', AREA, -1)))
        modeled = self.stack.enter_context(closing(Image.new('I', AREA, -1)))
        palette = [(20 + 5 * index, 15) for index in range(len(plan['colors']))]
        brush_plan = plan['options'].get('browser_brush_plan') or {}
        controls = dict(zip(map(tuple, brush_plan.get('control_positions') or ()),
                            brush_plan.get('nominal_sizes') or ()))
        mouse = PhysicalBrushMouse(physical, modeled, palette,
                                   model_width=plan['options']['brush_px'], controls=controls)
        events = []
        checked = []
        def verify_current(saved, index):
            checked.append(int(saved['nominal_sizes'][index]))
            return verification and mouse.brush == int(saved['nominal_sizes'][index])
        with patch('BrowserBrushSize.verify_brush_selection', side_effect=verify_current):
            DrawBot.execute_plan(plan, (*ORIGIN, *AREA), palette, mouse, NoWait(), threading.Event(),
                                 lambda *event: events.append(event), clock=lambda: 0)
        return mouse, np.asarray(physical).copy(), np.asarray(modeled).copy(), checked

    def assert_fixed_four_pixel_execution(self, plan):
        # Execute before asserting metadata so the regression actually exposes
        # the old policy's untouched native 4 px versus modeled 1 px footprint.
        mouse, actual, modeled, checked = self.execute(plan)
        differences = int(np.count_nonzero(actual != modeled))
        self.assertGreater(len(mouse.ink_widths), 0)
        self.assertEqual(set(mouse.ink_widths), {4})
        self.assertFalse(mouse.brush_clicks)
        self.assertFalse(checked)
        self.assertFalse(mouse.held)
        self.assertEqual(differences, 0,
            f'{differences} native pixels differ: UI/native brush 4 px, plan brush {plan["options"]["brush_px"]} px.')
        self.assertEqual(plan['options']['brush_px'], 4)
        self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']}, {4})
        counts = plan['options']['runtime_path_counts']
        self.assertEqual(counts['sent'] + counts['guard_skipped'], plan['count'])
        self.assertGreaterEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'], 4)

    def test_natural_quality_rescue_preserves_ui_declared_fixed_native_brush(self):
        options = self.options()
        self.assertEqual((options['brush_px'], options['brush_px_requested']), (4, '4'))
        plan, proposals = self.plan(self.source, options)
        self.assertEqual(len(proposals), 1)
        acceptance, proposal = proposals[0]
        self.assertEqual(acceptance['status'], 'BELOW_QUALITY_GATE')
        self.assertTrue(acceptance['deadline_gate_passed'])
        self.assertEqual(proposal['auto_tuner_meta']['selected_strategy'], 'quality-rescue-pixel-accurate')
        self.assertLessEqual(acceptance['projected_draw_seconds'], acceptance['usable_deadline_seconds'] * .32)
        self.assertEqual(plan['options']['_auto_tuner_replan_attempt'], 1)
        self.assertEqual(len(plan['options']['_auto_tuner_attempt_history']), 1)
        self.assertIsNone(propose_rescue_options(plan))
        self.assertEqual(plan['auto_tuner_acceptance'], evaluate_plan_acceptance(plan))
        self.assert_fixed_four_pixel_execution(plan)
        self.assertEqual(options['brush_px'], 4)
        self.assertEqual(plan['options']['calibration_fingerprint'], options['calibration_fingerprint'])
        self.assertEqual(plan['options']['canvas_edge_verification'], options['canvas_edge_verification'])

    def test_masterpiece_and_unlimited_line_art_preserve_fixed_native_width(self):
        for preset, mode in (('Masterpiece', 'Custom'), ('Auto', 'Unlimited')):
            with self.subTest(preset=preset, mode=mode):
                options = self.options(preset=preset, mode=mode, source=self.line_art)
                self.assertEqual(options['brush_px'], 4)
                self.assertTrue(options['unlimited_time'])
                plan, proposals = self.plan(self.line_art, options)
                self.assertFalse(proposals)
                self.assertTrue(plan['options']['pixel_accurate'])
                self.assert_fixed_four_pixel_execution(plan)

    def test_verified_browser_ladder_never_invents_one_pixel_control(self):
        # The real detector proves four controls from a synthetic screenshot.
        # The nominal fifth control is blank and must remain unverified.
        screenshot = self.stack.enter_context(closing(Image.new('RGB', (1000, 700), (245, 245, 245))))
        draw = ImageDraw.Draw(screenshot)
        y = 500 + max(28, min(int(700 * .095), int(360 * .17)))
        for index, fraction in enumerate((.05, .118, .186, .254)):
            x = 200 + 600 * fraction
            radius = 11 + 2 * index
            draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                         fill=(90, 90, 90), outline='white' if index == 1 else (30, 30, 30), width=3)
        options = self.options(profile='Gartic Phone', preset='Masterpiece', requested='2', source=self.line_art)
        brush = plan_browser_brush_size('gartic-phone', screenshot, (0, 0, 1000, 700),
                                       canvas_box=(200, 140, 800, 500), requested_px=options['brush_px'])
        evidence = brush.as_dict()
        self.assertEqual(evidence['verified_sizes'], [2, 4, 8, 16])
        self.assertEqual(brush.effective_px, 4)
        # These are the same three transfers made by Start's real preflight.
        options.update(browser_brush_plan=evidence, brush_px=brush.effective_px,
                       canvas_guard_brush_px=brush.safe_guard_px)
        plan, proposals = self.plan(self.line_art, options)
        self.assertFalse(proposals)
        self.assertTrue(plan['options']['pixel_accurate'])
        self.assertEqual(plan['options']['brush_px'], 4)
        self.assertIsNone(propose_rescue_options(plan))
        widths = {entry['brush_px'] for entry in plan['execution_sequence']}
        self.assertTrue(widths)
        self.assertTrue(widths <= {2, 4, 8, 16})
        self.assertNotIn(1, widths)
        mouse, actual, modeled, checked = self.execute(plan)
        self.assertTrue(checked)
        self.assertTrue(set(checked) <= {2, 4, 8, 16})
        self.assertTrue(set(mouse.ink_widths) <= widths)
        self.assertTrue(mouse.brush_clicks)
        self.assertFalse(mouse.held)
        np.testing.assert_array_equal(actual, modeled)
        self.assertEqual(plan['options']['browser_brush_plan'], evidence)


if __name__ == '__main__':
    unittest.main()
