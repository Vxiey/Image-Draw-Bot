"""Sketch previews describe guarded native fixed-width ink at every scale.

The axis oracle uses rational center mapping and explicit square membership;
it shares no geometry or raster helper with the product. Public plans also run
the actual executor, using clicked calibrated swatches as their ink colors.
This models the existing square brush contract, not a physical Paint capture.
"""
from contextlib import ExitStack, closing, contextmanager
import copy
from fractions import Fraction
import math
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot
import SketchFillRenderer
from test_drawbot import NoWait
from test_v148_rendering_batch16_selector import PaletteInkMouse
import test_v148_rendering_batch27_sketch_finalization as fixtures


PALETTE = fixtures.PALETTE
POSITIONS = tuple((-400 + 10 * i, -100) for i in range(len(PALETTE)))
PHASE_LABELS = {'sketch': 'Sketch 2.0 contours', 'color_fill': 'color fill',
                'reoutline': 'final re-outline'}


class NativeInkMouse(PaletteInkMouse):
    """Existing ink boundary with an explicit, possibly negative canvas origin."""
    def __init__(self, surface, brush, origin):
        super().__init__(surface, POSITIONS, PALETTE, brush)
        self.origin = tuple(origin)

    def _inside(self, point):
        return all(origin <= value < origin + extent
                   for value, origin, extent in zip(point, self.origin, self.surface.size))

    def _paint(self, start, end):
        if self.color is None:
            raise AssertionError('A clicked calibrated swatch must precede native ink.')
        ax, ay = (int(start[i]) - self.origin[i] for i in (0, 1))
        bx, by = (int(end[i]) - self.origin[i] for i in (0, 1))
        left, top = min(ax, bx), min(ay, by)
        with Image.new('1', (abs(bx - ax) + 1, abs(by - ay) + 1)) as mask:
            pen = ImageDraw.Draw(mask)
            draw = ImageDraw.Draw(self.surface)
            try:
                pen.line(((ax - left, ay - top), (bx - left, by - top)), fill=1)
                before, after = (self.brush - 1) // 2, self.brush // 2
                for y in range(mask.height):
                    for x in range(mask.width):
                        if mask.getpixel((x, y)):
                            draw.rectangle((left + x - before, top + y - before,
                                            left + x + after, top + y + after), fill=self.color)
            finally:
                pen.draw = pen.im = pen._image = None
                draw.draw = draw.im = draw._image = None

    def inspect_ink_segment(self, start, end, expected, brush, tolerance):
        sample = tuple(int(start[i]) - self.origin[i] for i in (0, 1))
        actual = self.surface.getpixel(sample)
        matched = actual == tuple(expected)
        self.verifications.append((tuple(expected), actual, matched))
        return {'matched': matched, 'actual': actual,
                'confidence': 100.0 if matched else 0.0, 'sample_count': 1,
                'error': sum(abs(a - b) for a, b in zip(actual, expected))}


def entries(*specifications):
    return [{'color_index': color, 'path': tuple(path), 'phase': phase,
             'phase_label': PHASE_LABELS[phase], 'serial': serial}
            for serial, (phase, color, path) in enumerate(specifications)]


def rational_center(position, source_extent, fitted_extent, origin, offset):
    value = (Fraction(origin) + Fraction(offset)
             + (Fraction(position) + Fraction(1, 2)) * Fraction(fitted_extent) / source_extent
             - Fraction(1, 2))
    # Canvas pixel centers use translation-invariant half ties toward +infinity.
    return math.floor(value + Fraction(1, 2))


def independent_axis_ink(source_size, fitted, canvas_size, origin, sequence, brush,
                         *, phases=None):
    """Explicit axis membership after a rectangular brush-inset clip.

    This does not call CanvasTransform, CanvasGuard, Precision, a product raster
    helper or Pillow's line routine. All axis fixtures stay in the whole canvas;
    only the documented brush-safe interior clips their endpoints.
    """
    canvas = Image.new('RGB', canvas_size, 'white')
    offset = tuple((Fraction(c) - Fraction(f)) / 2 for c, f in zip(canvas_size, fitted))
    inset = (brush + 1) // 2 + 2
    bounds = (inset, inset, canvas_size[0] - 1 - inset, canvas_size[1] - 1 - inset)
    before, after = (brush - 1) // 2, brush // 2
    try:
        for entry in sequence:
            if phases is not None and entry['phase'] not in phases:
                continue
            points = [tuple(rational_center(value, source_size[axis], fitted[axis],
                                             origin[axis], offset[axis]) - origin[axis]
                            for axis, value in enumerate(point)) for point in entry['path']]
            for point in points:
                assert 0 <= point[0] < canvas_size[0] and 0 <= point[1] < canvas_size[1]
            segments = zip(points, points[1:]) if len(points) > 1 else ((points[0], points[0]),)
            for (ax, ay), (bx, by) in segments:
                assert ax == bx or ay == by, 'The independent oracle accepts axes only.'
                if ay == by:
                    if not bounds[1] <= ay <= bounds[3]:
                        continue
                    centers = ((x, ay) for x in range(max(bounds[0], min(ax, bx)),
                                                      min(bounds[2], max(ax, bx)) + 1))
                else:
                    if not bounds[0] <= ax <= bounds[2]:
                        continue
                    centers = ((ax, y) for y in range(max(bounds[1], min(ay, by)),
                                                      min(bounds[3], max(ay, by)) + 1))
                for x, y in centers:
                    for oy in range(-before, after + 1):
                        for ox in range(-before, after + 1):
                            canvas.putpixel((x + ox, y + oy), PALETTE[entry['color_index']])
        return canvas
    except BaseException:
        canvas.close()
        raise


def sampled_fitted_canvas(canvas, fitted, preview_size):
    """Independent exact nearest-cell sampling of the delivered whole canvas."""
    offset = tuple((Fraction(c) - Fraction(f)) / 2 for c, f in zip(canvas.size, fitted))
    coordinates = [tuple(math.floor(offset[axis] + (Fraction(i) + Fraction(1, 2))
                                     * Fraction(fitted[axis]) / preview_size[axis])
                         for i in range(preview_size[axis])) for axis in (0, 1)]
    result = Image.new('RGB', preview_size)
    try:
        result.putdata([canvas.getpixel((x, y)) for y in coordinates[1] for x in coordinates[0]])
        return result
    except BaseException:
        result.close()
        raise


def public_source(kind, size=(96, 72)):
    if size == (40, 32):
        return fixtures.source_image('rgb')
    source = Image.new('RGBA' if kind == 'rgba' else 'RGB', size, 'white')
    pen = ImageDraw.Draw(source)
    try:
        if kind == 'rgba':
            pen.rectangle((9, 9, 60, 62), fill=(220, 30, 30, 192),
                          outline=(0, 0, 0, 255), width=2)
            pen.rectangle((40, 24, 86, 56), fill=(0, 80, 205, 128), outline=(0, 0, 0, 255))
            pen.rectangle((3, 3, 6, 6), fill=(123, 45, 67, 0))
        else:
            pen.rectangle((9, 9, 60, 62), fill=PALETTE[2], outline='black', width=2)
            pen.rectangle((40, 24, 86, 56), fill=PALETTE[3], outline='black')
    finally:
        pen.draw = pen.im = pen._image = None
    source.info['draw_studio_format'] = 'PNG'
    return source


@contextmanager
def direct_fixture(sequence, *, brush=1, source_size=(67, 50), fitted=(96, 72),
                   canvas_size=None, origin=(100, 100), full_preview=False):
    canvas_size = canvas_size or tuple(map(int, fitted))
    with fixtures.planner_fixture('Balanced', brush) as (_unused_source, settings), ExitStack() as stack:
        source = stack.enter_context(closing(Image.new('RGBA', source_size, 'white')))
        groups = [[] for _ in PALETTE]
        strokes = [[] for _ in PALETTE]
        for entry in sequence:
            path = tuple(entry['path'])
            groups[entry['color_index']].append(path)
            strokes[entry['color_index']].append((*path[0], *path[-1]))
        settings.update(sketch_fill_active=True, _planning_canvas_size=canvas_size,
            _target_screen_area=(*origin, *canvas_size),
            _sketch_fill_execution_groups=groups,
            _sketch_fill_execution_sequence=copy.deepcopy(sequence),
            _accuracy_original_source=source, plan_palette_rgb=PALETTE,
            progressive_rendering='On', color_workflow='Progressive passes',
            stroke_optimizer='Off', fill_regions=[], background_fill='Off',
            detail_zoom='Off', target_stroke_count_resolved=None,
            edge_behavior='Hard Clip', _full_detail_preview=full_preview)
        yield source, fitted, strokes, settings


class SketchNativePreviewTests(unittest.TestCase):
    @contextmanager
    def replay(self, plan, canvas_size, origin=(100, 100)):
        sequence = copy.deepcopy(plan['execution_sequence'])
        with ExitStack() as stack:
            surface = stack.enter_context(closing(Image.new('RGB', canvas_size, 'white')))
            mouse = NativeInkMouse(surface, int(plan['options']['brush_px']), origin)
            stack.callback(mouse.close)
            stack.enter_context(patch.object(DrawBot, 'save_runtime_safety_report',
                                             side_effect=lambda state: state.as_dict()))
            for target in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                           'CompletedDrawingAnalysis.record_completed_drawing',
                           'AutoTunerFeedback.record_completed_feedback',
                           'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(target, return_value={}))
            DrawBot.execute_plan(plan, (*origin, *canvas_size), POSITIONS, mouse,
                                NoWait(), threading.Event(), mouse.report, clock=lambda: 0)
            self.assertFalse(mouse.held)
            self.assertTrue(mouse.verifications)
            self.assertTrue(all(row[-1] for row in mouse.verifications))
            self.assertEqual(plan['execution_sequence'], sequence)
            self.assertEqual({row[2] for row in mouse.ink_colors}, {plan['options']['brush_px']})
            yield mouse

    def assert_preview(self, plan, native, key='preview'):
        preview = plan['preview'] if key == 'preview' else plan['ui_previews'][key]
        with closing(sampled_fitted_canvas(native, plan['fitted'], preview.size)) as expected:
            self.assertEqual(preview.mode, 'RGB')
            self.assertEqual(preview.tobytes(), expected.tobytes(), key)

    def test_scaled_axis_keeps_one_three_and_four_native_pixels(self):
        sequence = entries(('sketch', 0, ((10, 10), (20, 10))))
        for brush in (1, 3, 4):
            with self.subTest(brush=brush), direct_fixture(sequence, brush=brush) as data:
                source, fitted, strokes, settings = data
                before = source.tobytes()
                plan = DrawBot.finish_plan(source, fitted, strokes, settings)
                try:
                    with self.replay(plan, (96, 72)) as mouse, closing(independent_axis_ink(
                            source.size, fitted, (96, 72), (100, 100), sequence, brush)) as oracle:
                        self.assertEqual(mouse.surface.tobytes(), oracle.tobytes())
                        colored = sum(oracle.getpixel((x, y)) != (255, 255, 255)
                                      for y in range(oracle.height) for x in range(oracle.width))
                        self.assertEqual(colored, {1: 15, 3: 51, 4: 72}[brush])
                        self.assertEqual(plan['options']['runtime_path_counts'],
                                         {'processed': 1, 'sent': 1, 'guard_skipped': 0})
                        self.assertEqual(source.tobytes(), before)
                        self.assert_preview(plan, oracle)
                finally:
                    fixtures.close_plan(plan)

    def test_three_phase_overpaint_matches_independent_physical_snapshots(self):
        sequence = entries(('sketch', 0, ((12, 5), (12, 35))),
                           ('color_fill', 2, ((5, 20), (30, 20))),
                           ('reoutline', 0, ((12, 17), (12, 23))))
        for brush in (1, 3, 4):
            with self.subTest(brush=brush), direct_fixture(sequence, brush=brush) as data:
                source, fitted, strokes, settings = data
                plan = DrawBot.finish_plan(source, fitted, strokes, settings)
                try:
                    with self.replay(plan, (96, 72)) as mouse:
                        self.assertEqual([row[1] for row in mouse.selections],
                                         [PALETTE[0], PALETTE[2], PALETTE[0]])
                        for key, phases, native in (
                                ('sketch2', ('sketch',), mouse.phase_views['sketch']),
                                ('sketch_fill', ('sketch', 'color_fill'), mouse.phase_views['color_fill']),
                                ('sketch_fill_final', None, mouse.surface),
                                ('preview', None, mouse.surface)):
                            with self.subTest(layer=key), closing(independent_axis_ink(
                                    source.size, fitted, (96, 72), (100, 100), sequence, brush,
                                    phases=phases)) as oracle:
                                self.assertEqual(native.tobytes(), oracle.tobytes())
                                self.assert_preview(plan, oracle, key)
                finally:
                    fixtures.close_plan(plan)

    def test_half_pixel_letterbox_signed_origin_and_clipped_or_skipped_ink(self):
        sequence = entries(('sketch', 0, ((0, 10), (66, 10))),
                           ('color_fill', 2, ((0, 25), (66, 25))),
                           ('reoutline', 0, ((30, 0), (30, 49))),
                           ('reoutline', 0, ((0, 0), (66, 0))))
        canvas = (97, 73)
        for origin in ((100, 100), (-120, -90)):
            for brush in (1, 3, 4):
                with self.subTest(origin=origin, brush=brush), direct_fixture(
                        sequence, brush=brush, canvas_size=canvas, origin=origin) as data:
                    source, fitted, strokes, settings = data
                    plan = DrawBot.finish_plan(source, fitted, strokes, settings)
                    try:
                        with self.replay(plan, canvas, origin) as mouse, closing(independent_axis_ink(
                                source.size, fitted, canvas, origin, sequence, brush)) as oracle:
                            self.assertEqual(mouse.surface.tobytes(), oracle.tobytes())
                            self.assertEqual(plan['options']['runtime_path_counts'],
                                             {'processed': 4, 'sent': 3, 'guard_skipped': 1})
                            self.assertEqual(plan['options']['preview_safety_meta']['skipped_total'], 1)
                            for key in ('preview', 'sketch_fill_final'):
                                with self.subTest(layer=key):
                                    self.assert_preview(plan, oracle, key)
                    finally:
                        fixtures.close_plan(plan)

    def test_reduced_preview_samples_physical_ink_and_full_view_keeps_it(self):
        sequence = entries(('sketch', 0, ((10, 10), (20, 10))),
                           ('color_fill', 2, ((33, 10), (33, 38))),
                           ('reoutline', 0, ((10, 35), (20, 35))))
        canvas, fitted, origin = (3202, 82), (3201, 81), (-3300, -100)
        for brush, full in ((1, False), (3, False), (4, False), (4, True)):
            with self.subTest(brush=brush, full=full), direct_fixture(sequence, brush=brush,
                    fitted=fitted, canvas_size=canvas, origin=origin, full_preview=full) as data:
                source, fitted, strokes, settings = data
                plan = DrawBot.finish_plan(source, fitted, strokes, settings)
                try:
                    self.assertEqual(plan['preview'].size, fitted if full else (1600, 40))
                    with self.replay(plan, canvas, origin) as mouse, closing(independent_axis_ink(
                            source.size, fitted, canvas, origin, sequence, brush)) as oracle:
                        self.assertEqual(mouse.surface.tobytes(), oracle.tobytes())
                        self.assert_preview(plan, oracle)
                        for key, phase in (('sketch2', 'sketch'), ('sketch_fill', 'color_fill')):
                            with self.subTest(layer=key):
                                self.assert_preview(plan, mouse.phase_views[phase], key)
                finally:
                    fixtures.close_plan(plan)

    def test_public_balanced_rgb_and_rgba_scaled_final_and_phase_views(self):
        for kind in ('rgb', 'rgba'):
            for brush in (1, 3, 4):
                with self.subTest(kind=kind, brush=brush), fixtures.planner_fixture(
                        'Balanced', brush) as (_unused, settings), closing(public_source(kind)) as source:
                    before = (source.mode, source.size, source.tobytes(), copy.deepcopy(source.info))
                    plan = DrawBot.make_plan(source, source.size, settings)
                    try:
                        self.assertEqual(plan['image'].size, (67, 50))
                        self.assertEqual(plan['fitted'], (96, 72))
                        with self.replay(plan, source.size) as mouse:
                            self.assertEqual(plan['options']['runtime_path_counts']['sent'], plan['count'])
                            self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)
                            self.assertEqual((source.mode, source.size, source.tobytes(), source.info), before)
                            for key, native in (('preview', mouse.surface),
                                    ('sketch_fill_final', mouse.surface),
                                    ('sketch2', mouse.phase_views['sketch']),
                                    ('sketch_fill', mouse.phase_views['color_fill'])):
                                with self.subTest(layer=key):
                                    self.assert_preview(plan, native, key)
                    finally:
                        fixtures.close_plan(plan)

    def test_actual_identity_balanced_and_pixel_controls_keep_final_and_phase_views(self):
        for quality, kind, size in (('Balanced', 'rgb', (40, 32)),
                                    ('Pixel Accurate', 'rgba', (96, 72))):
            for brush in (1, 3, 4):
                with self.subTest(quality=quality, brush=brush), fixtures.planner_fixture(
                        quality, brush) as (_unused, settings), closing(public_source(kind, size)) as source:
                    plan = DrawBot.make_plan(source, size, settings)
                    try:
                        self.assertEqual(plan['image'].size, size)
                        with self.replay(plan, size) as mouse:
                            self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)
                            for key, native in (('preview', mouse.surface),
                                    ('sketch_fill_final', mouse.surface),
                                    ('sketch2', mouse.phase_views['sketch']),
                                    ('sketch_fill', mouse.phase_views['color_fill'])):
                                with self.subTest(layer=key):
                                    self.assert_preview(plan, native, key)
                    finally:
                        fixtures.close_plan(plan)

    def test_entire_reoutline_outside_safe_inset_stays_absent_from_final_preview(self):
        sequence = entries(('sketch', 0, ((10, 10), (20, 10))),
                           ('color_fill', 2, ((10, 20), (20, 20))),
                           ('reoutline', 0, ((0, 0), (66, 0))))
        with direct_fixture(sequence, brush=4) as data:
            source, fitted, strokes, settings = data
            plan = DrawBot.finish_plan(source, fitted, strokes, settings)
            try:
                with self.replay(plan, (96, 72)) as mouse:
                    self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 1)
                    self.assertEqual(mouse.surface.tobytes(), mouse.phase_views['color_fill'].tobytes())
                    for key in ('preview', 'sketch_fill_final'):
                        with self.subTest(layer=key):
                            self.assert_preview(plan, mouse.surface, key)
            finally:
                fixtures.close_plan(plan)

    def test_stop_during_phase_publication_closes_owned_views_and_preserves_source(self):
        sequence = entries(('sketch', 0, ((10, 10), (20, 10))),
                           ('color_fill', 2, ((10, 20), (20, 20))),
                           ('reoutline', 0, ((10, 30), (20, 30))))
        with direct_fixture(sequence, brush=3) as data:
            source, fitted, strokes, settings = data
            before = source.tobytes()
            stop = threading.Event()
            created = []
            original = SketchFillRenderer.render_sequence_preview
            def stop_after_first_phase(*args, **kwargs):
                result = original(*args, **kwargs)
                created.append(result)
                if len(created) == 2:
                    stop.set()
                return result
            retained = None
            with patch.object(SketchFillRenderer, 'render_sequence_preview',
                              side_effect=stop_after_first_phase):
                try:
                    DrawBot.finish_plan(source, fitted, strokes, settings, stop.is_set)
                except InterruptedError as error:
                    retained = error
            self.assertIsNotNone(retained)
            self.assertIsNotNone(retained.__traceback__)
            self.assertEqual(len(created), 2)
            for image in created:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))
            self.assertEqual(source.tobytes(), before)

    def test_one_phase_path_keeps_both_fragments_after_leaving_the_safe_inset(self):
        # Supported convex canvas; the one source polyline leaves and re-enters
        # its brush-safe interior. A concave canvas is deliberately rejected by
        # CanvasGuard and must not be made permissive to test fragmentation.
        sequence = entries(('sketch', 0, ((10, 10), (0, 10), (0, 35), (10, 35))),
                           ('color_fill', 2, ((6, 10), (12, 10))),
                           ('reoutline', 0, ((8, 35), (12, 35))))
        canvas, origin, brush = (96, 72), (-120, -90), 3
        with direct_fixture(sequence, brush=brush, origin=origin) as data:
            source, fitted, strokes, settings = data
            settings.update(canvas_polygon=((0, 0), (95, 0), (95, 71), (0, 71)),
                            canvas_polygon_space='area')
            plan = DrawBot.finish_plan(source, fitted, strokes, settings)
            try:
                safety = plan['options']['preview_safety_meta']
                self.assertEqual((safety['paths_in'], safety['drawable_subpaths']), (3, 4))
                self.assertEqual(len(plan['options']['_preview_safety_groups'][0]), 3)
                self.assertEqual(plan['execution_sequence'], sequence)
                with self.replay(plan, canvas, origin) as mouse:
                    self.assertEqual(plan['options']['runtime_path_counts'],
                                     {'processed': 3, 'sent': 3, 'guard_skipped': 0})
                    for key, phases, native in (
                            ('sketch2', ('sketch',), mouse.phase_views['sketch']),
                            ('sketch_fill', ('sketch', 'color_fill'), mouse.phase_views['color_fill']),
                            ('preview', None, mouse.surface),
                            ('sketch_fill_final', None, mouse.surface)):
                        with self.subTest(layer=key), closing(independent_axis_ink(
                                source.size, fitted, canvas, origin, sequence, brush,
                                phases=phases)) as oracle:
                            self.assertEqual(native.tobytes(), oracle.tobytes())
                            self.assert_preview(plan, oracle, key)
            finally:
                fixtures.close_plan(plan)

    def test_diagonal_views_follow_actual_precision_moves_after_verified_axis_probes(self):
        # First verify each color with an axis, then compare actual delivered
        # diagonal segments. No change to color verification or probe policy is
        # needed to exercise the renderer's signed precision-sampling branch.
        sequence = entries(('sketch', 0, ((5, 5), (15, 5))),
                           ('color_fill', 2, ((5, 40), (15, 40))),
                           ('color_fill', 2, ((8, 12), (50, 34), (15, 38))),
                           ('reoutline', 0, ((52, 39), (12, 14))))
        for brush, precision, pixel, origin in (
                (1, 'Normal', False, (100, 100)),
                (1, 'High', False, (-120, -90)),
                (1, 'Ultra', True, (-120, -90)),
                (4, 'High', False, (-120, -90))):
            with self.subTest(brush=brush, precision=precision, pixel=pixel, origin=origin), \
                    direct_fixture(sequence, brush=brush, origin=origin) as data:
                source, fitted, strokes, settings = data
                settings.update(precision=precision, pixel_accurate=pixel,
                                stroke_step_px=5, paint_stroke_delivery='Compatible')
                plan = DrawBot.finish_plan(source, fitted, strokes, settings)
                try:
                    with self.replay(plan, (96, 72), origin) as mouse:
                        self.assertEqual(len(mouse.verifications), 2)
                        self.assertEqual(plan['options']['runtime_path_counts'],
                                         {'processed': 4, 'sent': 4, 'guard_skipped': 0})
                        for key, native in (('preview', mouse.surface),
                                ('sketch_fill_final', mouse.surface),
                                ('sketch2', mouse.phase_views['sketch']),
                                ('sketch_fill', mouse.phase_views['color_fill'])):
                            with self.subTest(layer=key):
                                self.assert_preview(plan, native, key)
                finally:
                    fixtures.close_plan(plan)

    def test_stop_inside_physical_stamp_loop_releases_images_and_draw_cores(self):
        sequence = entries(('sketch', 0, ((10, 10), (20, 10))),
                           ('color_fill', 2, ((10, 20), (20, 20))))
        with direct_fixture(sequence, brush=3) as data:
            source, fitted, strokes, settings = data
            before = source.tobytes()
            stop = threading.Event()
            drawings, images, failures = [], [], []
            original_render = SketchFillRenderer.render_sequence_preview
            original_rectangle = ImageDraw.ImageDraw.rectangle
            def stamp_then_stop(draw, *args, **kwargs):
                result = original_rectangle(draw, *args, **kwargs)
                drawings.append(draw)
                images.append(draw._image)
                stop.set()
                return result
            def rendering(*args, **kwargs):
                with patch.object(ImageDraw.ImageDraw, 'rectangle', new=stamp_then_stop):
                    return original_render(*args, **kwargs)
            plan = None
            try:
                with patch.object(SketchFillRenderer, 'render_sequence_preview', new=rendering):
                    try:
                        plan = DrawBot.finish_plan(source, fitted, strokes, settings, stop.is_set)
                    except InterruptedError as error:
                        failures.append(error)
                self.assertEqual(len(failures), 1)
                self.assertIsNotNone(failures[0].__traceback__)
                self.assertTrue(images)
                for image in images:
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))
                for draw in drawings:
                    self.assertIsNone(draw.draw)
                    self.assertIsNone(draw.im)
                    self.assertIsNone(draw._image)
                self.assertEqual(source.tobytes(), before)
            finally:
                fixtures.close_plan(plan)

    def test_real_pillow_error_inside_physical_loop_releases_core_and_keeps_fallback(self):
        sequence = entries(('sketch', 0, ((10, 10), (20, 10))),
                           ('color_fill', 2, ((10, 20), (20, 20))))
        with direct_fixture(sequence, brush=3) as data:
            source, fitted, strokes, settings = data
            before = source.tobytes()
            drawings, images, failures = [], [], []
            original_render = SketchFillRenderer.render_sequence_preview
            original_rectangle = ImageDraw.ImageDraw.rectangle
            calls = 0
            def real_pillow_failure(draw, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return original_rectangle(draw, *args, **kwargs)
                drawings.append(draw)
                images.append(draw._image)
                # Deliberately enter Pillow's real rectangle implementation so
                # its retained C-call traceback still references the draw core.
                return original_rectangle(draw, (0, 0, None, 1), fill='black')
            def rendering(*args, **kwargs):
                if failures:
                    return original_render(*args, **kwargs)
                try:
                    with patch.object(ImageDraw.ImageDraw, 'rectangle', new=real_pillow_failure):
                        return original_render(*args, **kwargs)
                except (TypeError, ValueError) as error:
                    failures.append(error)
                    raise
            plan = None
            try:
                with patch.object(SketchFillRenderer, 'render_sequence_preview', new=rendering):
                    plan = DrawBot.finish_plan(source, fitted, strokes, settings)
                self.assertEqual(len(failures), 1)
                self.assertIsNotNone(failures[0].__traceback__)
                self.assertEqual(calls, 2)
                trace = failures[0].__traceback__
                pillow_frames = []
                while trace is not None:
                    pillow_frames.append(trace.tb_frame.f_code.co_filename.replace('\\', '/'))
                    trace = trace.tb_next
                self.assertTrue(any(path.endswith('/PIL/ImageDraw.py') for path in pillow_frames))
                self.assertEqual(plan['count'], 2)
                self.assertEqual(plan['execution_sequence'], sequence)
                plan['preview'].getpixel((0, 0))
                for image in images:
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))
                for draw in drawings:
                    self.assertIsNone(draw.draw)
                    self.assertIsNone(draw.im)
                    self.assertIsNone(draw._image)
                self.assertEqual(source.tobytes(), before)
            finally:
                fixtures.close_plan(plan)

    def test_long_axis_retains_the_native_step_limit_without_a_full_canvas_image(self):
        from PreviewSafety import build_preview_safety_plan

        canvas = (100020, 24)
        options = {'_planning_canvas_size': canvas,
                   '_target_screen_area': (-100100, -24, *canvas),
                   'profile_name': 'Microsoft Paint', 'profile_key': 'microsoft-paint',
                   'draw_quality': 'Balanced', 'brush_px': 1, 'precision': 'High',
                   'paint_stroke_delivery': 'Compatible', 'stroke_step_px': 1,
                   'edge_behavior': 'Hard Clip'}
        for length in (100000, 100001):
            with self.subTest(native_steps=length):
                sequence = entries(('sketch', 0, ((10, 12), (10 + length, 12))))
                before = copy.deepcopy(sequence)
                safe = build_preview_safety_plan(canvas, canvas, [[] for _ in PALETTE],
                    None, options, execution_sequence=sequence, retain_phases=True)
                arguments = dict(safety_plan=safe, fitted=canvas, options=options)
                if length == 100001:
                    with self.assertRaisesRegex(ValueError, 'unexpectedly long'):
                        SketchFillRenderer.render_sequence_preview(
                            canvas, (9, 24), sequence, PALETTE, **arguments)
                else:
                    with closing(SketchFillRenderer.render_sequence_preview(
                            canvas, (9, 24), sequence, PALETTE, **arguments)) as actual, \
                            closing(Image.new('RGB', (9, 24), 'white')) as expected:
                        # Every sampled column lies strictly inside the long
                        # horizontal stroke; only its one physical row is ink.
                        for x in range(9):
                            expected.putpixel((x, 12), PALETTE[0])
                        self.assertEqual(actual.tobytes(), expected.tobytes())
                self.assertEqual(sequence, before)


if __name__ == '__main__':
    unittest.main()
