"""Physical Fill diagnostics follow actual contour, tool and bucket actions."""
from collections import deque
from contextlib import ExitStack, closing
import copy
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveRegionHybrid as hybrid
from NativeBrushProjection import NativeBrushProjection
import NativeFillSimulation as native_fill
from test_drawbot import Mouse, NoWait
from test_pixel_accuracy_engine_v1088 import pm_from_index
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch08_fill import fill_options


ASSET = Path(__file__).parent / 'golden-regression/dominant-hue-four-color.png'
BLUE = (0, 80, 205)


def rectangle_case():
    labels = np.full((120, 180), -1, np.int16)
    labels[20:100, 20:151] = 0
    groups = [[(20, y, 150, y) for y in range(20, 100)]]
    settings = fill_options(_planning_canvas_size=(360, 240),
        corners=((100, 100), (460, 340)))
    with patch('DrawTimeCalibration.load_profile', return_value=None):
        regions, _ = hybrid._build_fill_regions(groups, [BLUE], (180, 120),
            (360, 240), settings, lambda: False)
    assert len(regions) == 1
    projection = NativeBrushProjection((180, 120), (360, 240), settings)
    return pm_from_index(labels), regions, projection, settings


def flood_pixels(surface, seed, color):
    """Independent literal four-neighbor flood over a dense numeric canvas."""
    x, y = seed
    old = int(surface[y, x])
    if old == color:
        return
    pending = deque([(x, y)])
    surface[y, x] = color
    while pending:
        x, y = pending.popleft()
        for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if (0 <= ny < surface.shape[0] and 0 <= nx < surface.shape[1]
                    and surface[ny, nx] == old):
                surface[ny, nx] = color
                pending.append((nx, ny))


def literal_native_fill(projection, regions, brush, *, batch_contours=True):
    """Dense brush stamps and pixel BFS, independent of production geometry."""
    width, height = projection.canvas_size
    surface = np.full((height, width), -1, np.int16)
    before, after = (brush-1)//2, brush//2
    def point(raw, integral=False):
        result = []
        for axis, value in enumerate(raw):
            if integral:
                value = int(value)
            screen = (projection.origin[axis] + projection.offset[axis] +
                (value+.5)*projection.fitted[axis]/projection.source_size[axis] - .5)
            floor = math.floor(screen)
            result.append(floor+int(screen-floor >= .5)-projection.origin[axis])
        return tuple(result)
    def stamp(x, y, color):
        for row in range(y-before, y+after+1):
            for column in range(x-before, x+after+1):
                if 0 <= row < height and 0 <= column < width:
                    surface[row, column] = color
    def path(points, color, *, integral=False, closed=False):
        if len(points) < 2:
            return
        mapped = [point(raw, integral) for raw in points]
        if closed and mapped[-1] != mapped[0]:
            mapped.append(mapped[0])
        for (x0,y0),(x1,y1) in zip(mapped, mapped[1:]):
            assert x0 == x1 or y0 == y1
            if x0 == x1:
                for y in range(min(y0,y1), max(y0,y1)+1):
                    stamp(x0, y, color)
            else:
                for x in range(min(x0,x1), max(x0,x1)+1):
                    stamp(x, y0, color)
    batches = [[region for region in regions if region['color_index'] == color]
               for color in dict.fromkeys(region['color_index'] for region in regions)]
    if not batch_contours:
        batches = [[region] for group in batches for region in group]
    for batch in batches:
        for region in batch:
            color = region['color_index']
            for seal in region.get('fill_seal_paths', ()):
                path(seal, color, integral=True)
            contour = region.get('contour')
            if not contour:
                x0,y0,x1,y1 = map(int, region['bbox'])
                contour = [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
            path(contour, color, closed=True)
        for region in batch:
            flood_pixels(surface, point(region['seed_pixel'], integral=True), region['color_index'])
    return surface


class NumericFillMouse(Mouse):
    def __init__(self, size, origin, palette):
        super().__init__()
        self.surface = np.full((size[1], size[0]), -1, np.int16)
        self.origin = origin
        self.palette = {point: index for index, point in enumerate(palette)}
        self.bucket = False
        self.ink = 0

    def local(self, point):
        return point[0] - self.origin[0], point[1] - self.origin[1]

    def paint(self, start, end):
        ax, ay = self.local(start)
        bx, by = self.local(end)
        assert ax == bx or ay == by
        self.surface[min(ay,by):max(ay,by)+1, min(ax,bx):max(ax,bx)+1] = self.ink

    def move(self, x, y):
        previous = self.position
        super().move(x, y)
        if self.held:
            self.paint(previous, self.position)

    def press(self):
        super().press()
        self.paint(self.position, self.position)

    def click(self):
        super().click()
        if self.position == (10, 10):
            self.bucket = True
        elif self.position == (20, 10):
            self.bucket = False
        elif self.position in self.palette:
            self.ink = self.palette[self.position]
        else:
            x, y = self.local(self.position)
            if 0 <= y < self.surface.shape[0] and 0 <= x < self.surface.shape[1]:
                if self.bucket:
                    flood_pixels(self.surface, (x, y), self.ink)
                else:
                    self.paint(self.position, self.position)


class PhysicalFillTests(unittest.TestCase):
    def test_row_interval_canvas_matches_dense_overpaint_and_bucket_topology(self):
        rng = np.random.default_rng(1482402)
        for size in ((13,9), (38,21)):
            width, height = size
            expected = np.full((height, width), -1, np.int16)
            with self.subTest(size=size), closing(native_fill._SpanCanvas(size, width*height, lambda: False)) as state:
                for operation in range(60):
                    color = int(rng.integers(0, 4))
                    if operation % 3:
                        x0,x1 = sorted(map(int, rng.integers(0, width, 2)))
                        y0,y1 = sorted(map(int, rng.integers(0, height, 2)))
                        state.paint_rectangle((x0,y0,x1,y1), color)
                        expected[y0:y1+1, x0:x1+1] = color
                    else:
                        seed = int(rng.integers(width)), int(rng.integers(height))
                        list(state.flood(seed, color))
                        flood_pixels(expected, seed, color)
                    actual = np.full((height, width), -1, np.int16)
                    for y, spans in state.rows.items():
                        for left, right, ink in spans:
                            actual[y, left:right+1] = ink
                    np.testing.assert_array_equal(actual, expected, err_msg=f'operation {operation}')
                    self.assertLessEqual(state.spans, width*height)

    def test_native_fills_match_literal_brushes_seals_batched_contours_and_signed_offsets(self):
        regions = [
            {'color_index': 0, 'contour': [(2,2),(13,2),(13,7),(8,7),(8,15),(2,15)],
             'seed_pixel': (4,4)},
            {'color_index': 1, 'bbox': (9,4,20,16), 'seed_pixel': (14,10)},
            {'color_index': 0, 'contour': [(6,6),(19,6),(19,17),(6,17)],
             'fill_seal_paths': [[(6,11),(19,11)], [(4,8)]], 'seed_pixel': (15,8)},
        ]
        original = copy.deepcopy(regions)
        for area, fitted, origin in (((53,47),(46.5,38.25),(-39,-21)),
                ((23,19),(23,19),(100,200)), ((17,13),(13,9),(-7,-5))):
            projection = NativeBrushProjection((23,19), fitted, {
                '_planning_canvas_size': area,
                'corners': (origin, (origin[0]+area[0],origin[1]+area[1]))})
            for brush in (1,2,3,4):
                with self.subTest(area=area, brush=brush):
                    expected = literal_native_fill(projection, regions, brush)
                    actual = np.full((area[1],area[0]), -1, np.int16)
                    for color,(x0,y0,x1,y1) in hybrid._native_rectangles(
                            projection, [], regions, default_brush=brush):
                        actual[y0:y1+1,x0:x1+1] = color
                    np.testing.assert_array_equal(actual, expected)
                    if area == (53,47) and brush == 1:
                        sequential = literal_native_fill(projection, regions, brush, batch_contours=False)
                        self.assertTrue(np.any(expected != sequential), 'Exercise actual color-batched topology.')
        self.assertEqual(regions, original)

    def test_real_detected_rectangle_has_native_boundary_gaps_in_scores_and_preview(self):
        pixel_map, regions, projection, settings = rectangle_case()
        before = copy.deepcopy(regions)
        expected = np.full((240, 360), -1, np.int16)
        # Native pixel-center endpoints are (41,41)..(301,199), each with
        # the real 1 px brush. The source cells also cover row/column 40.
        expected[41:200, 41:302] = 0
        metrics, coverage, error = hybrid.simulate_native_plan(pixel_map, [], projection, regions)
        with closing(coverage), closing(error), closing(hybrid.render_adaptive_preview(
                (180,120), (360,240), [], [BLUE], regions,
                fitted=(360,240), options=settings)) as preview:
            self.assertEqual(metrics['missing_pixels'], 421)
            self.assertEqual(metrics['coverage_percent'], 98.9957)
            actual = np.asarray(preview)
            np.testing.assert_array_equal(np.all(actual == BLUE, axis=2), expected == 0)
        self.assertEqual(regions, before)

    def test_existing_public_fill_plan_matches_actual_executor_and_preview_pixels(self):
        from DrawBot import execute_plan, make_plan
        reference = []
        real_map = hybrid.pixel_map_from_groups
        def observed_map(*args, **kwargs):
            result = real_map(*args, **kwargs)
            reference.append(result)
            return result
        with ExitStack() as stack:
            source = stack.enter_context(closing(Image.open(ASSET)))
            source_bytes = source.tobytes()
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            stack.enter_context(patch('ProfileStorage.data_dir', return_value=directory))
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            stack.enter_context(patch.object(hybrid, 'pixel_map_from_groups', new=observed_map))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
            for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name, return_value={}))
            size = (720, 480)
            settings = fill_options(paint_profile=True, profile_name='Microsoft Paint',
                profile_key='microsoft-paint', skip_white=True, corners=((100,100),(820,580)))
            plan = make_plan(source, size, settings)
            stack.callback(close_plan, plan, source)
            self.assertEqual(len(plan['options']['fill_regions']), 2)
            palette = [(40+i*3, 10) for i in range(len(plan['colors']))]
            mouse = NumericFillMouse(size, (100,100), palette)
            execute_plan(plan, (100,100,*size), palette, mouse, NoWait(), threading.Event(),
                lambda *args: None, clock=lambda: 0)
            projection = NativeBrushProjection(plan['image'].size, plan['fitted'], plan['options'])
            target = reference[0].palette_index[np.ix_(projection.y_source, projection.x_source)]
            drawable = reference[0].drawable_mask[np.ix_(projection.y_source, projection.x_source)]
            missing = int(np.count_nonzero(drawable & (mouse.surface < 0)))
            wrong = int(np.count_nonzero(drawable & (mouse.surface >= 0) & (mouse.surface != target)))
            quality = plan['options']['adaptive_hybrid_meta']['quality']
            self.assertEqual(quality['missing_pixels'], missing)
            self.assertEqual(quality['wrong_color_pixels'], wrong)
            pw, ph = plan['preview'].size
            xs = np.floor((np.arange(pw) + .5) * size[0] / pw).astype(int)
            ys = np.floor((np.arange(ph) + .5) * size[1] / ph).astype(int)
            observed = mouse.surface[np.ix_(ys, xs)]
            expected = np.full((ph,pw,3), 255, np.uint8)
            active = observed >= 0
            expected[active] = np.asarray(plan['colors'], np.uint8)[observed[active]]
            np.testing.assert_array_equal(np.asarray(plan['preview']), expected)
            self.assertEqual(plan['options']['runtime_safety_report']['fills']['better_fill_clicks'], 2)
            self.assertFalse(mouse.held)
            self.assertEqual(source.tobytes(), source_bytes)

    def test_native_fill_stop_releases_private_intervals_and_preserves_regions(self):
        _, regions, projection, _ = rectangle_case()
        original = copy.deepcopy(regions)
        states = []
        entered = False
        polls = 0
        real_init, real_flood = native_fill._SpanCanvas.__init__, native_fill._SpanCanvas.flood
        def initialize(state, *args):
            real_init(state, *args)
            states.append(state)
        def flood(state, *args):
            nonlocal entered
            entered = True
            yield from real_flood(state, *args)
        def cancelled():
            nonlocal polls
            if entered:
                polls += 1
            return polls == 3
        with patch.object(native_fill._SpanCanvas, '__init__', new=initialize), \
                patch.object(native_fill._SpanCanvas, 'flood', new=flood):
            with self.assertRaises(InterruptedError):
                list(hybrid._native_rectangles(projection, [], regions, cancelled=cancelled))
        self.assertTrue(states)
        self.assertTrue(all(state.rows == {} and state.spans == 0 for state in states))
        self.assertEqual(regions, original)

    def test_native_fill_index_overflow_closes_state_before_exact_streaming_retry(self):
        pixel_map, regions, projection, _ = rectangle_case()
        metrics, coverage, error = hybrid.simulate_native_plan(pixel_map, [], projection, regions)
        with closing(coverage), closing(error):
            expected = metrics, coverage.tobytes(), error.tobytes()
        states = []
        real_init = native_fill._SpanCanvas.__init__
        def initialize(state, *args):
            real_init(state, *args)
            states.append(state)
        with patch.object(native_fill._SpanCanvas, '__init__', new=initialize), \
                patch.object(hybrid, '_MAX_NATIVE_FOOTPRINTS', 100):
            self.assertIsNone(hybrid._native_footprint_index(projection, [], regions,
                default_brush=1, cancelled=lambda: False))
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].rows, {})
            metrics, coverage, error = hybrid.simulate_native_plan(pixel_map, [], projection, regions)
            with closing(coverage), closing(error):
                self.assertEqual((metrics, coverage.tobytes(), error.tobytes()), expected)
        self.assertGreater(len(states), 2, 'Overflow must retry through the streamed physical footprints.')
        self.assertTrue(all(state.rows == {} and state.spans == 0 and state.cancelled is None for state in states))

    def test_retained_stop_does_not_keep_partial_row_matches_or_callback(self):
        polls = 0
        def cancelled():
            nonlocal polls
            polls += 1
            return polls == 2
        state = native_fill._SpanCanvas((2048,1), 2048, lambda: False)
        for x in range(0, 2048, 2):
            state.paint_span(0, x, x, 0)
        state.cancelled = cancelled
        failure = None
        try:
            state.matching_spans(0, -1, 0, 2047)
        except InterruptedError as error:
            failure = error
        finally:
            state.close()
        self.assertIsNotNone(failure)
        frames = []
        traceback = failure.__traceback__
        while traceback is not None:
            if traceback.tb_frame.f_code.co_name == 'matching_spans':
                frames.append(traceback.tb_frame)
            traceback = traceback.tb_next
        self.assertEqual(len(frames), 1)
        self.assertIsNone(frames[0].f_locals['result'])
        self.assertEqual(state.rows, {})
        self.assertIsNone(state.cancelled)

    def test_optional_index_does_not_consume_one_shot_contour_or_seal_inputs(self):
        template = {'color_index': 0, 'bbox': (2,2,13,13), 'row_spans': [],
            'contour': [(2,2),(13,2),(13,13),(2,13)],
            'fill_seal_paths': [[(2,8),(13,8)]], 'seed_pixel': (4,4)}
        projection = NativeBrushProjection((16,16), (16,16), {
            '_planning_canvas_size': (16,16), 'corners': ((0,0),(16,16))})
        expected = literal_native_fill(projection, [template], 1)
        for one_shot in ('contour','seals','seal'):
            region = copy.deepcopy(template)
            if one_shot == 'contour':
                region['contour'] = iter(region['contour'])
            elif one_shot == 'seals':
                region['fill_seal_paths'] = iter(region['fill_seal_paths'])
            else:
                region['fill_seal_paths'] = [iter(region['fill_seal_paths'][0])]
            with self.subTest(one_shot=one_shot), patch.object(hybrid, '_MAX_NATIVE_FOOTPRINTS', 8):
                self.assertIsNone(hybrid._native_footprint_index(projection, [], [region],
                    default_brush=1, cancelled=lambda: False))
                actual = np.full((16,16), -1, np.int16)
                for color,(x0,y0,x1,y1) in hybrid._native_rectangles(projection, [], [region]):
                    actual[y0:y1+1,x0:x1+1] = color
                np.testing.assert_array_equal(actual, expected)

    def test_public_stop_inside_native_fill_propagates_without_publishing_fallback(self):
        import DrawBot
        entered = False
        polls = 0
        states = []
        real_make = DrawBot.make_plan
        real_init, real_flood = native_fill._SpanCanvas.__init__, native_fill._SpanCanvas.flood
        def initialize(state, *args):
            real_init(state, *args)
            states.append(state)
        def flood(state, *args):
            nonlocal entered
            entered = True
            yield from real_flood(state, *args)
        def cancelled():
            nonlocal polls
            if entered:
                polls += 1
            return polls == 2
        with ExitStack() as stack:
            source = stack.enter_context(closing(Image.open(ASSET)))
            before = source.tobytes()
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            stack.enter_context(patch('ProfileStorage.data_dir', return_value=directory))
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            def observed_make(image, area, settings, cancelled=lambda: False):
                result = real_make(image, area, settings, cancelled)
                if settings.get('_adaptive_hybrid_inner'):
                    stack.callback(close_plan, result, source)
                return result
            stack.enter_context(patch.object(DrawBot, 'make_plan', new=observed_make))
            stack.enter_context(patch.object(native_fill._SpanCanvas, '__init__', new=initialize))
            stack.enter_context(patch.object(native_fill._SpanCanvas, 'flood', new=flood))
            with self.assertRaises(InterruptedError):
                DrawBot.make_plan(source, (720,480), fill_options(skip_white=True,
                    paint_profile=True, profile_name='Microsoft Paint', profile_key='microsoft-paint',
                    corners=((100,100),(820,580))), cancelled=cancelled)
            self.assertTrue(entered)
            self.assertTrue(states)
            self.assertTrue(all(state.rows == {} and state.spans == 0 and state.cancelled is None for state in states))
            self.assertEqual(source.tobytes(), before)

    def test_public_native_fill_memory_failure_retains_complete_original_base_plan(self):
        import DrawBot
        real_make = DrawBot.make_plan
        real_init, real_paint = native_fill._SpanCanvas.__init__, native_fill._SpanCanvas.paint_span
        for failure in ('interval allowance', 'row allocation'):
            states, bases = [], []
            paints = 0
            with self.subTest(failure=failure), ExitStack() as stack:
                source = stack.enter_context(closing(Image.open(ASSET)))
                before = source.tobytes()
                directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                stack.enter_context(patch('ProfileStorage.data_dir', return_value=directory))
                stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
                def observed_make(image, area, settings, cancelled=lambda: False):
                    result = real_make(image, area, settings, cancelled)
                    if settings.get('_adaptive_hybrid_inner'):
                        snapshot = {key: copy.deepcopy(result[key]) for key in
                                    ('groups','execution_groups','execution_sequence','colors','count')}
                        snapshot['preview_bytes'] = result['preview'].tobytes()
                        bases.append((result, snapshot))
                        stack.callback(close_plan, result, source)
                    return result
                def initialize(state, size, max_spans, cancelled):
                    real_init(state, size, 1 if failure == 'interval allowance' else max_spans, cancelled)
                    states.append(state)
                def paint(state, *args):
                    nonlocal paints
                    paints += 1
                    if failure == 'row allocation' and paints == 8:
                        raise MemoryError('injected row allocation failure')
                    return real_paint(state, *args)
                stack.enter_context(patch.object(DrawBot, 'make_plan', new=observed_make))
                stack.enter_context(patch.object(native_fill._SpanCanvas, '__init__', new=initialize))
                stack.enter_context(patch.object(native_fill._SpanCanvas, 'paint_span', new=paint))
                result = DrawBot.make_plan(source, (720,480), fill_options(skip_white=True,
                    paint_profile=True, profile_name='Microsoft Paint', profile_key='microsoft-paint',
                    corners=((100,100),(820,580))))
                self.assertEqual(len(bases), 1)
                base, snapshot = bases[0]
                self.assertTrue(states, 'The accepted native Fill must reach its private interval canvas.')
                self.assertTrue(result is base, 'Keep the already completed original plan on optional Fill OOM.')
                self.assertGreater(result['count'], 0)
                for key in ('groups','execution_groups','execution_sequence','colors','count'):
                    self.assertEqual(result[key], snapshot[key], key)
                self.assertEqual(result['preview'].tobytes(), snapshot['preview_bytes'])
                self.assertFalse(result['options'].get('fill_regions'))
                self.assertIn('MemoryError', result['adaptive_hybrid_meta']['reason'])
                self.assertEqual(result['adaptive_hybrid_meta']['fallback_engine'], 'legacy standard planner')
                self.assertEqual(source.tobytes(), before)
                self.assertTrue(states)
                self.assertTrue(all(state.rows == {} and state.spans == 0 and state.cancelled is None for state in states))


if __name__ == '__main__':
    unittest.main()
