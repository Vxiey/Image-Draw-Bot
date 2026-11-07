"""Final previews keep the colour and brush order sent to native drawing input."""
from contextlib import ExitStack, closing
import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import DrawBot
from test_drawbot import Mouse, NoWait
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch06_canvas import close_plan


BLACK = (0, 0, 0)
BLUE = (0, 80, 205)
ORIGIN = (1000, 1000)


class NativeRasterMouse(Mouse):
    """Record real executor input and paint each completed native path.

    The surface has a fixed physical brush unless a verified control is clicked.
    No production preview, safety-plan or simulation helper builds this raster.
    """
    def __init__(self, surface, palette, colors, brush, controls=None):
        super().__init__()
        self.surface = surface
        self.palette = dict(zip(palette, colors))
        self.controls = dict(controls or {})
        self.brush = brush
        self.color = None
        self.path = []
        self.painted = []

    def move(self, x, y):
        super().move(x, y)
        if self.held:
            self.path.append(self.position)

    def press(self):
        super().press()
        self.path = [self.position]

    def release(self):
        if self.held and self.path:
            self._paint(self.path)
        self.path = []
        super().release()

    def click(self):
        super().click()
        if self.position in self.palette:
            self.color = self.palette[self.position]
        elif self.position in self.controls:
            self.brush = self.controls[self.position]
        elif all(start <= value < start + extent
                 for value, start, extent in zip(self.position, ORIGIN, self.surface.size)):
            self._paint([self.position])

    def _paint(self, path):
        if self.color is None:
            raise AssertionError('The executor must select a colour before drawing.')
        points = [(x - ORIGIN[0], y - ORIGIN[1]) for x, y in path]
        draw = ImageDraw.Draw(self.surface)
        if len(points) > 1:
            draw.line(points, fill=self.color, width=self.brush, joint='curve')
        for x, y in (points[0], points[-1]):
            if self.brush == 1:
                draw.point((x, y), fill=self.color)
            else:
                before, after = (self.brush - 1) // 2, self.brush // 2
                draw.ellipse((x - before, y - before, x + after, y + after), fill=self.color)
        self.painted.append((self.color, self.brush, tuple(points)))


class PreviewExecutionOrderTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
        for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(name, return_value={}))

    def source(self, size=(64, 48)):
        return self.stack.enter_context(closing(Image.new('RGB', size, 'white')))

    def options(self, **changes):
        values = dict(render_preset='Manual', auto_engine_resolved=True, draw_quality='Balanced',
                      unlimited_time=True, time_budget_mode='Unlimited', detail_zoom='Off',
                      color_grouping='Smart', skip_white=True, color_layers='Off',
                      strict_color_verification=False, adaptive_color_verification=False,
                      visual_verification_enabled=False, visual_verification_resolved='Off',
                      _execution_cost_calibration_override={})
        values.update(changes)
        return opts(**values)

    def remember(self, plan, source):
        self.stack.callback(close_plan, plan, source)
        return plan

    def execute(self, plan):
        surface = self.source(tuple(map(round, plan['fitted'])))
        palette = [(10 + 5 * index, 10) for index in range(len(plan['colors']))]
        brush_plan = plan['options'].get('browser_brush_plan') or {}
        controls = dict(zip(map(tuple, brush_plan.get('control_positions') or ()),
                            brush_plan.get('nominal_sizes') or ()))
        mouse = NativeRasterMouse(surface, palette, plan['colors'], plan['options']['brush_px'], controls)
        with patch('BrowserBrushSize.verify_brush_selection',
                   side_effect=lambda settings, index: mouse.brush == settings['nominal_sizes'][index]):
            DrawBot.execute_plan(plan, (*ORIGIN, *surface.size), palette, mouse, NoWait(),
                                 threading.Event(), lambda *args: None, clock=lambda: 0)
        self.assertFalse(mouse.held)
        self.assertTrue(mouse.painted)
        return surface, mouse

    def assert_native_preview(self, plan):
        surface, mouse = self.execute(plan)
        actual, preview = np.asarray(surface), np.asarray(plan['preview'])
        differences = int(np.count_nonzero(np.any(actual != preview, axis=2)))
        self.assertEqual(differences, 0, f'{differences} preview pixels disagree with actual executor input.')
        self.assertIs(plan['ui_previews']['simulated_final'], plan['preview'])
        return surface, mouse

    def pixel_sequence_plan(self, *, fitted=(64, 64), image_size=(64, 64), edge_paths=True, **changes):
        source = self.source(image_size)
        sequence = [
            {'color_index': 1, 'path': ((8, 20), (52, 20)), 'brush_px': 5, 'phase': 'fill'},
            {'color_index': 0, 'path': ((18, 20), (44, 20)), 'brush_px': 1, 'phase': 'fine_detail'},
            {'color_index': 0, 'path': ((32, 18), (32, 22)), 'phase': 'cleanup'},
            # The broad brush cannot reach this edge; the thin brush can.
            {'color_index': 1, 'path': ((3, 12), (3, 50)), 'brush_px': 5, 'phase': 'correction_1'},
            {'color_index': 0, 'path': ((3, 12), (3, 50)), 'brush_px': 1, 'phase': 'correction_2'},
        ]
        if not edge_paths:sequence = sequence[:3]
        groups = [[], []]
        paths = [[], []]
        for entry in sequence:
            index = entry['color_index']
            groups[index].append((*entry['path'][0], *entry['path'][-1]))
            paths[index].append(entry['path'])
        values = dict(brush_px=3, canvas_guard_brush_px=5, plan_palette_rgb=(BLACK, BLUE),
                      color_order=[0, 1], profile_key='gartic-phone', profile_name='Gartic Phone',
                      _pixel_execution_groups=paths, _pixel_execution_sequence=sequence,
                      browser_brush_plan={'target_position': (25, 50), 'target_index': 1,
                          'effective_px': 3, 'nominal_sizes': [1, 3, 5], 'verified_sizes': [1, 3, 5],
                          'control_positions': [(15, 50), (25, 50), (35, 50)], 'confidence': .95,
                          'safe_guard_px': 5})
        values.update(changes)
        plan = self.remember(DrawBot.finish_plan(source, fitted, groups, self.options(**values)), source)
        self.assertEqual(plan['execution_sequence'], sequence)
        return plan

    def test_public_smart_batches_preserve_black_line_after_blue_base(self):
        source = self.source()
        draw = ImageDraw.Draw(source)
        draw.rectangle((10, 8, 54, 40), fill=BLUE)
        draw.line((20, 24, 44, 24), fill=BLACK)
        plan = self.remember(DrawBot.make_plan(source, source.size,
            self.options(brush_px=3, color_workflow='Finish color first')), source)
        self.assertFalse(plan['execution_sequence'])
        self.assertEqual([plan['colors'][index] for index in plan['options']['color_order']], [BLUE, BLACK])
        surface, _ = self.execute(plan)
        self.assertEqual(surface.getpixel((32, 24)), BLACK)
        self.assertEqual(plan['preview'].getpixel((32, 24)), BLACK)
        np.testing.assert_array_equal(np.asarray(plan['preview']), np.asarray(surface))

    def test_progressive_passes_keep_late_black_detail_without_detail_zoom(self):
        source = self.source((64, 64))
        groups = [[(26, 32, 38, 32)], [(8, 32, 56, 32)]]
        plan = self.remember(DrawBot.finish_plan(source, source.size, groups,
            self.options(brush_px=1, plan_palette_rgb=(BLACK, BLUE), color_order=[0, 1],
                         progressive_rendering='On', color_workflow='Progressive passes',
                         stroke_optimizer='Off')), source)
        self.assertEqual([entry['color_index'] for entry in plan['execution_sequence']], [1, 0])
        self.assertFalse(plan['options']['detail_zoom_meta']['enabled'])
        surface, _ = self.assert_native_preview(plan)
        self.assertEqual(surface.getpixel((32, 32)), BLACK)

    def test_explicit_batch_omissions_repeats_and_empty_sequence_follow_executor(self):
        for mode in ('Lines (fastest)', 'Smart paths (recommended)'):
            for order in ([1, 0], [0, 1, 0], [0], []):
                with self.subTest(mode=mode, order=order):
                    source = self.source((64, 64))
                    groups = [[(18, 32, 46, 32)], [(8, 32, 56, 32)]]
                    plan = self.remember(DrawBot.finish_plan(source, source.size, groups,
                        self.options(brush_px=1, plan_palette_rgb=(BLACK, BLUE), color_order=order,
                                     drawing_mode=mode, color_workflow='Finish color first',
                                     progressive_rendering='Off', stroke_optimizer='Off')), source)
                    self.assertEqual(plan['execution_sequence'], [])
                    self.assert_native_preview(plan)

    def test_public_pixel_corrections_use_their_final_native_order(self):
        from test_v148_accuracy_batch12_context import source_fixture
        source = self.stack.enter_context(closing(source_fixture()))
        plan = self.remember(DrawBot.make_plan(source, source.size,
            self.options(draw_quality='Pixel Accurate', brush_px=4)), source)
        self.assertTrue(any(entry['phase'].startswith('correction_') for entry in plan['execution_sequence']))
        self.assert_native_preview(plan)

    def test_repeated_phases_and_inherited_verified_brush_keep_native_guard_and_pixels(self):
        plan = self.pixel_sequence_plan()
        surface, mouse = self.assert_native_preview(plan)
        self.assertEqual([width for _, width, _ in mouse.painted], [5, 1, 1, 1])
        self.assertEqual(plan['options']['preview_safety_meta']['skipped_total'], 1)
        self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 1)
        self.assertEqual(surface.getpixel((32, 20)), BLACK)
        self.assertEqual(surface.getpixel((3, 30)), BLACK)

    def test_reduced_preview_scales_physical_sequence_brush_exactly_once(self):
        plan = self.pixel_sequence_plan(fitted=(3200, 320), image_size=(640, 64))
        surface, mouse = self.execute(plan)
        self.assertEqual(plan['preview'].size, (1600, 160))
        expected = self.source(plan['preview'].size)
        draw = ImageDraw.Draw(expected)
        scale = expected.width / surface.width
        for color, physical_width, sent_points in mouse.painted:
            points = [(x * scale, y * scale) for x, y in sent_points]
            width = max(1, round(physical_width * scale))
            if len(points) > 1:
                draw.line(points, fill=color, width=width, joint='curve')
            for x, y in (points[0], points[-1]):
                if width == 1:
                    draw.point((x, y), fill=color)
                else:
                    before, after = (width - 1) // 2, width // 2
                    draw.ellipse((x - before, y - before, x + after, y + after), fill=color)
        np.testing.assert_array_equal(np.asarray(plan['preview']), np.asarray(expected))

    def test_preview_failure_keeps_sequence_order_and_propagates_stop(self):
        source = self.source((64, 64))
        groups = [[(26, 32, 38, 32)], [(8, 32, 56, 32)]]
        options = self.options(brush_px=1, plan_palette_rgb=(BLACK, BLUE), color_order=[0, 1],
                               progressive_rendering='On', color_workflow='Progressive passes',
                               stroke_optimizer='Off')
        with patch('DrawBot.build_preview_safety_plan', side_effect=RuntimeError('diagnostic unavailable')):
            plan = self.remember(DrawBot.finish_plan(source, source.size, groups, copy.deepcopy(options)), source)
        self.assertFalse(plan['options']['preview_safety_meta']['active'])
        self.assert_native_preview(plan)
        with patch('DrawBot.build_preview_safety_plan', side_effect=InterruptedError('stopped')):
            with self.assertRaisesRegex(InterruptedError, 'stopped'):
                DrawBot.finish_plan(source, source.size, groups, copy.deepcopy(options))

    def test_preview_failure_keeps_verified_brush_switches_and_inherited_width(self):
        with patch('DrawBot.build_preview_safety_plan', side_effect=RuntimeError('diagnostic unavailable')):
            plan = self.pixel_sequence_plan(edge_paths=False)
        self.assertFalse(plan['options']['preview_safety_meta']['active'])
        _, mouse = self.assert_native_preview(plan)
        self.assertEqual([width for _, width, _ in mouse.painted], [5, 1, 1])

    def test_partial_preview_failure_removes_stale_ink_before_batch_fallback(self):
        source = self.source((64, 64))
        groups = [[(26, 32, 38, 32)], [(8, 32, 56, 32)]]
        def partial(draw, *args, **kwargs):
            draw.point((61, 61), fill=BLACK)
            raise RuntimeError('diagnostic failed after drawing')
        with patch('DrawBot.draw_safe_paths', side_effect=partial):
            plan = self.remember(DrawBot.finish_plan(source, source.size, groups,
                self.options(brush_px=1, plan_palette_rgb=(BLACK, BLUE), color_order=[0, 1, 0],
                             color_workflow='Finish color first', progressive_rendering='Off',
                             stroke_optimizer='Off')), source)
        self.assertFalse(plan['options']['preview_safety_meta']['active'])
        self.assert_native_preview(plan)
        self.assertEqual(plan['preview'].getpixel((61, 61)), (255, 255, 255))

    def test_partial_preview_failure_restores_background_and_region_fill_prelude(self):
        source = self.source((64, 64))
        groups = [[(26, 32, 38, 32)], [(8, 32, 56, 32)], []]
        options = self.options(brush_px=1, plan_palette_rgb=(BLACK, BLUE, (220, 230, 240)),
            color_order=[0, 1, 0], color_workflow='Finish color first', progressive_rendering='Off',
            stroke_optimizer='Off', background_fill_plan={'enabled': True, 'color_index': 2},
            fill_regions=[{'color_index': 1, 'bbox': (8, 8, 12, 12)},
                          {'color_index': 0, 'row_spans': [(15, 8, 12)]}])
        reference = self.remember(DrawBot.finish_plan(source, source.size, groups, copy.deepcopy(options)), source)
        def partial(draw, *args, **kwargs):
            draw.rectangle((0, 0, 20, 20), fill=(255, 0, 255))
            raise RuntimeError('diagnostic failed after drawing')
        with patch('DrawBot.draw_safe_paths', side_effect=partial):
            fallback = self.remember(DrawBot.finish_plan(source, source.size, groups, copy.deepcopy(options)), source)
        self.assertEqual(fallback['preview'].getpixel((10, 10)), BLUE)
        self.assertEqual(fallback['preview'].getpixel((10, 15)), BLACK)
        self.assertEqual(fallback['preview'].getpixel((5, 5)), (220, 230, 240))
        np.testing.assert_array_equal(np.asarray(fallback['preview']), np.asarray(reference['preview']))


if __name__ == '__main__':
    unittest.main()
