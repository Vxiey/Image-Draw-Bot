"""Sketch Fill's contour color must select the same RGB that its preview uses."""
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import Colors
import DrawBot
from PixelData import closest_color
from SketchFillRenderer import _black_selector
from test_drawbot import Mouse, NoWait
import test_v148_ui_batch07_renderer as ui_fixtures


NATIVE_RGB = ((4, 4, 4), (255, 255, 255), (220, 30, 30), (254, 175, 168))
ORIGIN = (100, 100)


class PaletteInkMouse(Mouse):
    """Paint actual delivered coordinates using only the clicked native swatch.

    The plan's RGB values never determine ink. The read-only verification
    boundary samples this independently painted surface, so a wrong palette
    index must fail Paint's ordinary color probe.
    """
    def __init__(self, surface, positions, rgbs, brush):
        super().__init__()
        self.surface = surface
        self.palette = dict(zip(positions, rgbs))
        self.brush = brush
        self.color = None
        self.phase = None
        self.selections = []
        self.ink_colors = []
        self.verifications = []
        self.phase_views = {}

    def _inside(self, point):
        return all(origin <= value < origin + extent
                   for value, origin, extent in zip(point, ORIGIN, self.surface.size))

    def _paint(self, start, end):
        if self.color is None:
            raise AssertionError('Native palette selection must precede drawing.')
        ax, ay = (int(start[i]) - ORIGIN[i] for i in (0, 1))
        bx, by = (int(end[i]) - ORIGIN[i] for i in (0, 1))
        left, top = min(ax, bx), min(ay, by)
        # Independent Pillow centerline, then the actual fixed square brush.
        # Bound the temporary mask to this native mouse segment.
        with Image.new('1', (abs(bx - ax) + 1, abs(by - ay) + 1)) as mask:
            ImageDraw.Draw(mask).line(((ax - left, ay - top), (bx - left, by - top)), fill=1)
            before, after = (self.brush - 1) // 2, self.brush // 2
            draw = ImageDraw.Draw(self.surface)
            for y in range(mask.height):
                for x in range(mask.width):
                    if mask.getpixel((x, y)):
                        draw.rectangle((left + x - before, top + y - before,
                                        left + x + after, top + y + after), fill=self.color)

    def move(self, x, y):
        previous = self.position
        super().move(x, y)
        if self.held:
            self._paint(previous, self.position)

    def press(self):
        super().press()
        self.ink_colors.append((self.phase, self.color, self.brush))
        self._paint(self.position, self.position)

    def click(self):
        super().click()
        if self.position in self.palette:
            self.color = self.palette[self.position]
            self.selections.append((self.position, self.color))
        elif self._inside(self.position):
            self.ink_colors.append((self.phase, self.color, self.brush))
            self._paint(self.position, self.position)
        else:
            raise AssertionError(f'Unexpected native control: {self.position!r}')

    def inspect_ink_segment(self, start, end, expected, brush, tolerance):
        sample = tuple(int(start[i]) - ORIGIN[i] for i in (0, 1))
        actual = self.surface.getpixel(sample)
        matched = actual == tuple(expected)
        self.verifications.append((tuple(expected), actual, matched))
        return {'matched': matched, 'actual': actual, 'confidence': 100.0 if matched else 0.0,
                'sample_count': 1, 'error': sum(abs(a - b) for a, b in zip(actual, expected))}

    def report(self, kind, value):
        if kind == 'status' and str(value).startswith('Progressive pass '):
            if self.phase is not None:
                self.phase_views[self.phase] = self.surface.copy()
            if 'Sketch 2.0 contours' in value:
                self.phase = 'sketch'
            elif 'final re-outline' in value:
                self.phase = 'reoutline'
            else:
                self.phase = 'color_fill'

    def close(self):
        for image in self.phase_views.values():
            image.close()


class SketchFillNativeSelectorTests(unittest.TestCase):
    @contextmanager
    def planned(self, quality='Balanced', *, rgbs=NATIVE_RGB, brush=1, prepared=()):
        old_palette = list(Colors.allColors)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            def restore_palette():
                Colors.allColors[:] = old_palette
                closest_color.cache_clear()
            stack.callback(restore_palette)
            directory = Path(directory)
            positions = [(-400 + 10 * i, -100) for i in range(len(rgbs))]
            calibration = directory / 'calibration.json'
            calibration.write_text(json.dumps({'version': 4, 'profile': 'microsoft-paint',
                'state': 'calibrated', 'colors': [
                    {'name': f'Swatch {i}', 'position': list(point), 'rgb': list(rgb)}
                    for i, (point, rgb) in enumerate(zip(positions, rgbs))]}), encoding='utf-8')
            Colors.load_calibration(calibration, profile_key='microsoft-paint')
            stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
            stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=bool(prepared)))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            stack.enter_context(patch('ColorCache.load_cache', return_value={}))
            stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
            for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name, return_value={}))
            source = stack.enter_context(closing(Image.new('RGB', (40, 32), 'white')))
            ImageDraw.Draw(source).rectangle((7, 6, 32, 25), fill=(220, 30, 30), outline='black', width=2)
            source_bytes = source.tobytes()
            app = ui_fixtures.AdvertisedRendererTests().app()
            app.draw_quality.set(quality)
            app.brush_px.set(str(brush))
            app.visual_verification = ui_fixtures.Value('Off')
            app.time_budget_mode = ui_fixtures.Value('Unlimited / Accuracy')
            if prepared:
                app.original = source
                app.picture_custom_palette_state = {
                    'profile_key': 'microsoft-paint', 'image_id': id(source),
                    'colors': prepared, 'prepared_count': len(prepared)}
            options = DrawBot.DrawBotApp.options(app)
            options['_execution_cost_calibration_override'] = {}
            inner = []
            real_make_plan = DrawBot.make_plan
            def record_inner(image, area, settings, cancelled=lambda: False):
                result = real_make_plan(image, area, settings, cancelled)
                if settings.get('_sketch_fill_inner'):
                    inner.append((result, copy.deepcopy((result['colors'], result['color_selectors']))))
                return result
            with patch('DrawBot.make_plan', side_effect=record_inner):
                plan = DrawBot.make_plan(source, source.size, options)
            seen = set()
            stack.callback(ui_fixtures.close_images, plan, seen)
            for subplan, _snapshot in inner:
                stack.callback(ui_fixtures.close_images, subplan, seen)
            self.assertEqual(len(inner), 1)
            self.assertTrue(plan['options']['strict_color_verification'])
            self.assertTrue(plan['options']['adaptive_color_verification'])
            yield source, plan, positions, inner[0]
            self.assertEqual(source.tobytes(), source_bytes)
            self.assertEqual((inner[0][0]['colors'], inner[0][0]['color_selectors']), inner[0][1])

    def replay(self, source, plan, positions, rgbs, brush):
        surface = Image.new('RGB', source.size, 'white')
        self.addCleanup(surface.close)
        mouse = PaletteInkMouse(surface, positions, rgbs, brush)
        self.addCleanup(mouse.close)
        DrawBot.execute_plan(plan, (*ORIGIN, *source.size), positions, mouse, NoWait(),
                             threading.Event(), mouse.report, clock=lambda: 0)
        self.assertFalse(mouse.held)
        self.assertTrue(mouse.verifications)
        self.assertTrue(all(item[2] for item in mouse.verifications))
        self.assertEqual(plan['options']['runtime_path_counts']['sent'], plan['count'])
        self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)
        self.assertEqual({item[2] for item in mouse.ink_colors}, {brush})
        self.assertEqual(plan['options']['brush_px'], brush)
        self.assertEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'], brush)
        return mouse

    def test_actual_palette_only_ui_plan_selects_measured_dark_ink_for_all_phases(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality), self.planned(quality) as (source, plan, positions, inner):
                before_sequence = copy.deepcopy(plan['execution_sequence'])
                mouse = self.replay(source, plan, positions, NATIVE_RGB, 1)
                self.assertEqual(inner[0]['color_selectors'], ())
                self.assertEqual(len(plan['color_selectors']), len(plan['colors']))
                self.assertEqual(plan['colors'][-1], NATIVE_RGB[0])
                self.assertEqual(plan['color_selectors'][-1],
                                 {'kind': 'palette', 'palette_index': 0, 'rgb': NATIVE_RGB[0]})
                for phase in ('sketch', 'reoutline'):
                    self.assertEqual({rgb for name, rgb, _ in mouse.ink_colors if name == phase}, {NATIVE_RGB[0]})
                self.assertEqual(plan['execution_sequence'], before_sequence)
                self.assertEqual(Counter(entry['phase'] for entry in before_sequence),
                                 {'sketch': 2, 'color_fill': 3, 'reoutline': 1})
                self.assertEqual(plan['count'], len(before_sequence))
                self.assertEqual(mouse.surface.tobytes(), plan['preview'].tobytes())
                self.assertEqual(mouse.phase_views['sketch'].tobytes(), plan['ui_previews']['sketch2'].tobytes())
                self.assertEqual(mouse.phase_views['color_fill'].tobytes(), plan['ui_previews']['sketch_fill'].tobytes())

    def test_reordered_dark_swatch_keeps_native_color_and_four_pixel_brush(self):
        rgbs = (NATIVE_RGB[2], NATIVE_RGB[1], NATIVE_RGB[0], NATIVE_RGB[3])
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality), self.planned(quality, rgbs=rgbs, brush=4) as (source, plan, positions, _inner):
                sequence = copy.deepcopy(plan['execution_sequence'])
                mouse = self.replay(source, plan, positions, rgbs, 4)
                self.assertEqual(mouse.selections[0], (positions[2], rgbs[2]))
                self.assertEqual(mouse.selections[-1], (positions[2], rgbs[2]))
                self.assertEqual(plan['color_selectors'][-1]['palette_index'], 2)
                self.assertEqual({rgb for phase, rgb, _ in mouse.ink_colors if phase in ('sketch', 'reoutline')},
                                 {rgbs[2]})
                self.assertEqual(plan['execution_sequence'], sequence)
                counts = Counter(entry['phase'] for entry in sequence)
                meta = plan['options']['sketch_fill_meta']
                self.assertEqual(counts, {'sketch': meta['sketch_paths'], 'color_fill': meta['color_fill_paths'],
                                          'reoutline': meta['reoutline_paths']})
                self.assertEqual(mouse.surface.tobytes(), plan['preview'].tobytes())

    def test_existing_exact_native_black_keeps_implicit_palette_and_real_execution(self):
        rgbs = ((0, 0, 0), *NATIVE_RGB[1:])
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality), self.planned(quality, rgbs=rgbs) as (source, plan, positions, inner):
                mouse = self.replay(source, plan, positions, rgbs, 1)
                self.assertEqual(plan['colors'], inner[0]['colors'])
                self.assertEqual(plan['color_selectors'], ())
                self.assertEqual(mouse.selections[0], (positions[0], rgbs[0]))
                self.assertEqual(mouse.surface.tobytes(), plan['preview'].tobytes())

    def test_actual_prepared_picture_palette_keeps_every_existing_custom_selector(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            for prepared in (((220, 30, 30), (20, 120, 220)), ((220, 30, 30), (0, 0, 0))):
                with self.subTest(quality=quality, prepared=prepared), \
                        self.planned(quality, prepared=prepared) as (_source, plan, _positions, inner):
                    color_plan = inner[0]
                    self.assertEqual(color_plan['colors'], prepared)
                    self.assertTrue(all(selector['kind'] == 'custom' and selector['require_exact']
                                        for selector in color_plan['color_selectors']))
                    self.assertEqual(plan['colors'][:len(prepared)], color_plan['colors'])
                    self.assertEqual(plan['color_selectors'][:len(prepared)], color_plan['color_selectors'])
                    contour_indexes = {entry['color_index'] for entry in plan['execution_sequence']
                                       if entry['phase'] in ('sketch', 'reoutline')}
                    if (0, 0, 0) in prepared:
                        self.assertEqual(plan['colors'], prepared)
                        self.assertEqual(plan['color_selectors'], color_plan['color_selectors'])
                        self.assertEqual(contour_indexes, {prepared.index((0, 0, 0))})
                    else:
                        self.assertEqual(contour_indexes, {len(prepared)})
                        self.assertEqual(plan['colors'][-1], NATIVE_RGB[0])
                        self.assertEqual(plan['color_selectors'][-1],
                                         {'kind': 'palette', 'palette_index': 0, 'rgb': NATIVE_RGB[0]})

    def test_existing_exact_black_and_explicit_custom_selectors_are_retained(self):
        colors = ((220, 30, 30), (0, 0, 0))
        selectors = ({'kind': 'palette', 'palette_index': 2, 'rgb': colors[0]},
                     {'kind': 'custom', 'rgb': colors[1], 'source_rgb': colors[1],
                      'require_exact': True, 'fallback_palette_index': 0})
        before = copy.deepcopy(selectors)
        index, actual_colors, actual_selectors = _black_selector(colors, selectors)
        self.assertEqual(index, 1)
        self.assertEqual(actual_colors, list(colors))
        self.assertEqual(actual_selectors, list(selectors))
        self.assertEqual(selectors, before)


if __name__ == '__main__':
    unittest.main()
