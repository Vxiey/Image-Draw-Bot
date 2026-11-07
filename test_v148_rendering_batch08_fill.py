"""Fill contours use the same pixel centers as native drawing and simulation."""
from contextlib import ExitStack, closing
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import FillOptimizer as fill
from StatefulFillSimulation import simulate_fill_region
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_transparency import standard_options


BLUE = (0, 80, 205)


def fixture(shape='rectangle'):
    image = Image.new('RGBA', (180, 120), 'white')
    draw = ImageDraw.Draw(image)
    if shape == 'rectangle':
        draw.rectangle((20, 20, 150, 99), fill=(*BLUE, 255))
    elif shape == 'l':
        draw.rectangle((20, 20, 70, 99), fill=(*BLUE, 255))
        draw.rectangle((20, 60, 150, 99), fill=(*BLUE, 255))
    elif shape == 'u':
        draw.rectangle((20, 20, 50, 99), fill=(*BLUE, 255))
        draw.rectangle((120, 20, 150, 99), fill=(*BLUE, 255))
        draw.rectangle((20, 70, 150, 99), fill=(*BLUE, 255))
    elif shape == 'stair':
        for y in range(20, 100):
            draw.line((20, y, 70 + (y // 10) * 4, y), fill=(*BLUE, 255))
    elif shape == 'spur':
        draw.rectangle((20, 20, 100, 99), fill=(*BLUE, 255))
        draw.line((100, 60, 150, 60), fill=(*BLUE, 255))
    elif shape == 'neck':
        draw.rectangle((20, 20, 70, 99), fill=(*BLUE, 255))
        draw.rectangle((100, 20, 150, 99), fill=(*BLUE, 255))
        draw.rectangle((60, 60, 110, 61), fill=(*BLUE, 255))
    return image


def group_input(image):
    # Independent one-pixel groups keep the fixture's actual palette index.
    pixels = np.asarray(image)
    target = np.all(pixels[:, :, :3] == BLUE, axis=2) & (pixels[:, :, 3] != 0)
    group = [(int(x), int(y), int(x), int(y)) for y, x in np.argwhere(target)]
    return [group], target


def fill_options(**extra):
    settings = standard_options(extra_fast=True, extra_fast_v2=True, gpu_mode='CPU',
        fill_tool_available=True, use_region_fill_engine=True, fill_engine='Closed regions v2',
        fill_tool_actions=[('fill', (10, 10))], fill_restore_actions=[('brush', (20, 10))],
        brush_px=1, strict_color_verification=False, adaptive_color_verification=False,
        visual_verification_enabled=False, visual_verification_resolved='Off',
        _execution_cost_calibration_override={})
    settings.update(extra)
    return settings


class PixelCenterFillTests(unittest.TestCase):
    def test_both_detectors_match_independent_pillow_contour_and_flood_pixels(self):
        for shape in ('rectangle', 'l', 'u', 'stair', 'spur'):
            with self.subTest(shape=shape), closing(fixture(shape)) as image:
                groups, target = group_input(image)
                engines = ('Safe rectangles', 'Closed regions v2') if shape == 'rectangle' else ('Closed regions v2',)
                for engine in engines:
                    for kind in ('image', 'groups'):
                        with self.subTest(engine=engine, kind=kind):
                            regions = (fill.detect_fill_regions(image, 'Aggressive', engine=engine)
                                if kind == 'image' else fill.detect_fill_regions_from_groups(
                                    groups, [BLUE], image.size, 'Aggressive', engine=engine))
                            self.assertEqual(len(regions), 1)
                            region = regions[0].as_dict()
                            with closing(Image.new('1', image.size)) as oracle:
                                ImageDraw.Draw(oracle).line(region['contour'], fill=1, width=1)
                                wall = np.asarray(oracle).copy()
                                self.assertFalse(np.any(wall & ~target))
                                ImageDraw.floodfill(oracle, region['seed_pixel'], 1)
                                expected = np.asarray(oracle).copy()
                            np.testing.assert_array_equal(expected, target)
                            result, state = simulate_fill_region(region, image.size, brush_px=1,
                                                                 max_missing_percent=0)
                            self.assertTrue(result.safe, result.reason)
                            self.assertEqual((result.missing_pixels, result.spill_pixels), (0, 0))
                            np.testing.assert_array_equal(state, expected)

    def test_disconnected_interior_and_holes_keep_scanline_fallback(self):
        with closing(fixture('neck')) as image:
            groups, _ = group_input(image)
            for kind in ('image', 'groups'):
                with self.subTest(kind=kind):
                    regions, meta = (fill.detect_fill_regions(image, 'Aggressive', return_meta=True,
                        engine='Closed regions v2') if kind == 'image' else fill.detect_fill_regions_from_groups(
                            groups, [BLUE], image.size, 'Aggressive', engine='Closed regions v2', return_meta=True))
                    self.assertEqual(regions, [])
                    self.assertEqual(meta['rejected']['no connected interior seed'], 1)
        with closing(fixture()) as image:
            ImageDraw.Draw(image).rectangle((50, 40, 70, 60), fill='white')
            groups, _ = group_input(image)
            regions, meta = fill.detect_fill_regions_from_groups(groups, [BLUE], image.size,
                'Aggressive', engine='Closed regions v2', return_meta=True)
            self.assertFalse(regions)
            self.assertEqual(meta['rejected']['holes'], 1)

    def test_actual_hybrid_accepts_centered_fill_and_reports_final_rejected_brush(self):
        from DrawBot import make_plan
        with closing(fixture()) as image, patch('DrawTimeCalibration.load_profile', return_value=None):
            for engine in ('Safe rectangles', 'Closed regions v2'):
                for brush in (1, 2, 5):
                    with self.subTest(engine=engine, brush=brush):
                        plan = make_plan(image, image.size, fill_options(fill_engine=engine, brush_px=brush))
                        try:
                            regions = plan['options']['fill_regions']
                            meta = plan['options']['region_fill_meta']
                            self.assertTrue(plan['options']['adaptive_hybrid_meta']['enabled'])
                            if brush == 1:
                                self.assertEqual(len(regions), 1)
                                self.assertEqual(meta['stateful_fill_simulation']['painted_state_pixels'], 131 * 80)
                                self.assertEqual(meta['outline_paths'], 1)
                                self.assertEqual(meta['fill_coverage_percent'], round(131 * 80 / (180 * 120) * 100, 3))
                                self.assertEqual(plan['options']['adaptive_hybrid_meta']['quality']['missing_pixels'], 0)
                            else:
                                self.assertEqual(regions, [])
                                self.assertEqual(meta['stateful_fill_simulation']['rejected_regions'], 1)
                                self.assertIn('safe one-pixel boundary halo', meta['stateful_fill_simulation']['rejections'][0]['reason'])
                                for field in ('accepted_regions', 'fill_safe_regions', 'fill_actions', 'outline_paths',
                                              'fill_color_batches', 'fill_coverage_percent', 'estimated_saved_strokes',
                                              'estimated_time_saved_seconds'):
                                    self.assertEqual(meta[field], 0, field)
                                self.assertEqual(meta['fill_execution_order']['color_batches'], 0)
                                self.assertFalse(meta['decisions'][0]['accepted'])
                                self.assertEqual(meta['decisions'][0]['estimated_time_saved_seconds'], 0.)
                        finally:
                            close_plan(plan, image)

    def test_actual_transparent_hole_still_prevents_bucket_fill(self):
        from DrawBot import make_plan
        with closing(fixture()) as image:
            image.putpixel((85, 60), (*BLUE, 0))
            for engine in ('Safe rectangles', 'Closed regions v2'):
                with self.subTest(engine=engine):
                    plan = make_plan(image, image.size, fill_options(fill_engine=engine))
                    try:
                        self.assertFalse(plan['options']['fill_regions'])
                        with closing(Image.new('1', image.size)) as raster:
                            draw = ImageDraw.Draw(raster)
                            for group in plan['execution_groups']:
                                for path in group:
                                    if len(path) == 1: draw.point(path[0], fill=1)
                                    else: draw.line(path, fill=1, width=1)
                            self.assertFalse(raster.getpixel((85, 60)))
                    finally:
                        close_plan(plan, image)

    def test_stop_inside_new_contour_conversion_propagates_through_both_detectors(self):
        with closing(Image.new('RGBA', (640, 480), 'white')) as image:
            ImageDraw.Draw(image).rectangle((10, 10, 629, 469), fill=(*BLUE, 255))
            groups = [[(10, y, 629, y) for y in range(10, 470)]]
            convert = fill._pixel_center_contour
            for kind in ('image', 'groups'):
                entered = False
                polls = 0
                def observed(*args, **kwargs):
                    nonlocal entered
                    entered = True
                    return convert(*args, **kwargs)
                def cancelled():
                    nonlocal polls
                    if entered: polls += 1
                    return polls == 2
                with self.subTest(kind=kind), patch.object(fill, '_pixel_center_contour', side_effect=observed):
                    with self.assertRaises(InterruptedError):
                        if kind == 'image':
                            fill.detect_fill_regions(image, 'Aggressive', cancelled=cancelled)
                        else:
                            fill.detect_fill_regions_from_groups(groups, [BLUE], image.size, 'Aggressive', cancelled=cancelled)
                self.assertEqual(polls, 2)
                self.assertEqual(image.getpixel((10, 10)), (*BLUE, 255))

    def test_actual_native_contour_and_bucket_actions_paint_exact_source_rectangle(self):
        from DrawBot import execute_plan, make_plan
        from test_drawbot import Mouse, NoWait

        class RasterMouse(Mouse):
            def __init__(self, surface, colors):
                super().__init__()
                self.surface = surface
                self.bucket = False
                self.ink = 0
                self.palette = {(40+i*3,10): int(tuple(rgb) != (255,255,255)) for i,rgb in enumerate(colors)}
            def move(self, x, y):
                previous = self.position
                super().move(x, y)
                if self.held:
                    ImageDraw.Draw(self.surface).line([(previous[0]-100, previous[1]-100), (x-100, y-100)], fill=self.ink)
            def press(self):
                super().press()
                ImageDraw.Draw(self.surface).point((self.position[0]-100, self.position[1]-100), fill=self.ink)
            def click(self):
                super().click()
                if self.position == (10, 10): self.bucket = True
                elif self.position == (20, 10): self.bucket = False
                elif self.position in self.palette: self.ink = self.palette[self.position]
                elif self.bucket and 100 <= self.position[0] < 280 and 100 <= self.position[1] < 220:
                    ImageDraw.floodfill(self.surface, (self.position[0]-100, self.position[1]-100), self.ink)

        with ExitStack() as stack:
            image = stack.enter_context(closing(fixture()))
            surface = stack.enter_context(closing(Image.new('1', image.size)))
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda s: s.as_dict()))
            for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name, return_value={}))
            plan = make_plan(image, image.size, fill_options(paint_profile=True,
                profile_name='Microsoft Paint', profile_key='microsoft-paint', corners=((100, 100), (280, 220))))
            stack.callback(close_plan, plan, image)
            self.assertEqual(len(plan['options']['fill_regions']), 1)
            mouse = RasterMouse(surface, plan['colors'])
            execute_plan(plan, (100, 100, 180, 120), [(40+i*3, 10) for i in range(len(plan['colors']))],
                         mouse, NoWait(), threading.Event(), lambda *args: None, clock=lambda: 0)
            _, target = group_input(image)
            np.testing.assert_array_equal(np.asarray(surface), target)
            self.assertEqual(plan['options']['runtime_safety_report']['fills']['better_fill_clicks'], 1)
            self.assertFalse(mouse.held)


if __name__ == '__main__':
    unittest.main()
