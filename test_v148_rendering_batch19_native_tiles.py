"""Tile-local scoring reuses bounded native ink without changing paint order."""
from contextlib import ExitStack, closing
import copy
from fractions import Fraction
import math
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageDraw

import AdaptiveRegionHybrid as regional
import DrawBot
from NativeBrushProjection import NativeBrushProjection
from PixelAccuratePlanner import PixelMap
from test_v148_rendering_batch06_canvas import close_plan
import test_v148_rendering_batch10_physical as physical


def sample_map(size=(17, 13), seed=1481901):
    width, height = size
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 3, (height, width), dtype=np.int16)
    drawable = rng.random((height, width)) > .16
    labels[~drawable] = -1
    return PixelMap(width, height, np.zeros((height, width, 3), np.uint8), labels,
        drawable, rng.random((height, width), dtype=np.float32),
        rng.random((height, width), dtype=np.float32),
        rng.random((height, width)) > .55, {})


def independent_ink(pixel_map, sequence, fitted, area, *, origin=(-33, -17),
                    default_brush=1, fill_regions=()):
    """Literal source-cell mapping and Pillow brush stamps; no production raster helpers."""
    width, height = area
    offset = ((width-fitted[0])/2, (height-fitted[1])/2)
    xs = np.array([math.floor((Fraction(x)+Fraction(1, 2)-Fraction(offset[0]))*
        pixel_map.width/Fraction(fitted[0])) for x in range(width)], np.int64)
    ys = np.array([math.floor((Fraction(y)+Fraction(1, 2)-Fraction(offset[1]))*
        pixel_map.height/Fraction(fitted[1])) for y in range(height)], np.int64)
    valid = ((ys >= 0) & (ys < pixel_map.height))[:, None] & \
            ((xs >= 0) & (xs < pixel_map.width))[None, :]
    lookup = np.ix_(np.clip(ys, 0, pixel_map.height-1), np.clip(xs, 0, pixel_map.width-1))
    target = pixel_map.palette_index[lookup]
    drawable = pixel_map.drawable_mask[lookup] & valid
    with closing(Image.new('I', area, -1)) as image:
        draw = ImageDraw.Draw(image)
        for region in fill_regions:
            for y, left, right in region.get('row_spans', ()):
                left, right = sorted((int(left), int(right)))
                columns = np.flatnonzero((xs >= left) & (xs <= right))
                rows = np.flatnonzero(ys == int(y))
                if len(columns) and len(rows):
                    draw.rectangle((int(columns[0]), int(rows[0]), int(columns[-1]), int(rows[-1])),
                                   fill=region['color_index'])
        brush = default_brush
        for entry in sequence:
            if not entry.get('path'):
                continue
            brush = max(1, int(entry.get('brush_px') or brush))
            before, after = (brush-1)//2, brush//2
            def native(point):
                values = [origin[i]+offset[i]+((float(point[i])+.5)*fitted[i]/
                          (pixel_map.width if i == 0 else pixel_map.height))-.5 for i in (0, 1)]
                return tuple(math.floor(value)+int(value-math.floor(value) >= .5)-origin[i]
                             for i, value in enumerate(values))
            points = [native(point) for point in entry['path']]
            def stamp(x, y):
                draw.rectangle((x-before, y-before, x+after, y+after), fill=entry['color_index'])
            if len(points) == 1:
                stamp(*points[0])
            for start, end in zip(points, points[1:]):
                if start[0] == end[0] or start[1] == end[1]:
                    draw.rectangle((min(start[0], end[0])-before, min(start[1], end[1])-before,
                                    max(start[0], end[0])+after, max(start[1], end[1])+after),
                                   fill=entry['color_index'])
                else:
                    steps = max(abs(end[0]-start[0]), abs(end[1]-start[1]), 1)
                    for step in range(steps+1):
                        stamp(round(start[0]+(end[0]-start[0])*(step/steps)),
                              round(start[1]+(end[1]-start[1])*(step/steps)))
        ink = np.asarray(image).copy()
    painted = ink >= 0
    correct = drawable & (ink == target)
    wrong = drawable & painted & (ink != target)
    spill = ~drawable & painted
    edge = drawable & (pixel_map.edge_map[lookup] >= .5)
    protected = drawable & pixel_map.protected_mask[lookup].astype(bool)
    count = np.count_nonzero
    intended = max(1, count(drawable))
    coverage = 100*count(drawable & painted)/intended
    color = 100*count(correct)/intended
    edges = 100*count(correct & edge)/count(edge) if count(edge) else color
    detail = 100*count(correct & protected)/count(protected) if count(protected) else color
    spill_score = max(0., 100-100*count(spill)/max(1, count(painted)))
    metrics = dict(coverage_percent=round(coverage, 4), color_accuracy_percent=round(color, 4),
        edge_preservation_percent=round(edges, 4), protected_detail_percent=round(detail, 4),
        spill_accuracy_percent=round(spill_score, 4), wrong_color_pixels=int(count(wrong)),
        spill_pixels=int(count(spill)), missing_pixels=int(count(drawable & ~painted)),
        pixel_accuracy_score=round(.35*color+.25*coverage+.20*edges+.15*detail+.05*spill_score, 4))
    diagnostic = np.full((*ink.shape, 3), 255, np.uint8)
    diagnostic[correct] = (225, 225, 225)
    diagnostic[drawable & ~painted] = (255, 80, 80)
    diagnostic[wrong] = (255, 170, 45)
    diagnostic[spill] = (175, 60, 220)
    scale = min(1., 1600/max(area))
    size = (max(1, round(width*scale)), max(1, round(height*scale)))
    with closing(Image.fromarray(diagnostic)) as full, \
            closing(full.resize(size, Image.Resampling.NEAREST)) as preview:
        return metrics, preview.tobytes(), size


def public_plan(source, area, *, observations=None):
    real = regional.simulate_native_plan
    def observed(pixel_map, sequence, projection, *args, **kwargs):
        native = projection.native_path
        with patch.object(projection, 'native_path', wraps=native) as calls:
            result = real(pixel_map, sequence, projection, *args, **kwargs)
        if observations is not None:
            observations.append({'reference': pixel_map,
                'nonempty_paths': sum(bool(row.get('path')) for row in sequence),
                'tiles': sum(1 for _ in projection.tiles()), 'native_path_calls': calls.call_count})
        return result
    with patch.object(regional, 'simulate_native_plan', new=observed):
        return DrawBot.make_plan(source, area, physical.physical_options((100, 100), area))


def simulation_output(source, sequence, projection, fills=()):
    metrics, coverage, error = regional.simulate_native_plan(source, sequence, projection, fills)
    with closing(coverage), closing(error):
        return metrics, coverage.size, coverage.tobytes(), error.tobytes()


def projection_for(source, area=(64, 192), limit=75000):
    return NativeBrushProjection((source.width, source.height), tuple(map(float, area)),
        {'_planning_canvas_size': area, 'planner_max_pixels': limit,
         'corners': ((-33, -17), (-33+area[0], -17+area[1]))})


def mixed_sequence(size=(17, 13), seed=1481901):
    rng = np.random.default_rng(seed)
    width, height = size
    result = []
    for index in range(9):
        points = tuple((int(rng.integers(-2, width+2)), int(rng.integers(-2, height+2)))
                       for _ in range(1+index % 3))
        result.append({'color_index': index % 3, 'path': points})
        if index % 2 == 0:
            result[-1]['brush_px'] = 1+index % 5
        if index == 4:
            result.append({'color_index': 2, 'brush_px': 1, 'path': ()})
    return result


class NativeTilePreparationTests(unittest.TestCase):
    def test_actual_public_tiled_plans_prepare_native_paths_once_and_preserve_delivered_ink(self):
        for area in ((400, 300), (1200, 900)):
            with self.subTest(canvas=area), ExitStack() as stack:
                stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
                source = stack.enter_context(closing(Image.new('RGB', (200, 150), 'white')))
                ImageDraw.Draw(source).rectangle((48, 40, 143, 103), fill=(0, 80, 205))
                observed = []
                plan = public_plan(source, area, observations=observed)
                stack.callback(close_plan, plan, source)
                self.assertEqual(len(observed), 1)
                row = observed[0]
                self.assertGreater(row['tiles'], 1)
                actual, _selected = physical.replay_executor(plan, (100, 100), area)
                physical.PhysicalBrushProjectionTests.assert_report_matches_native_actions(
                    self, plan, row['reference'], actual, area)
                self.assertEqual(row['native_path_calls'], row['nonempty_paths'],
                                 {key: value for key, value in row.items() if key != 'reference'})

    def test_overpaint_diagonals_fill_inherited_width_and_preview_sampling_match_literal_ink(self):
        source = sample_map()
        sequence = [
            {'color_index': 1, 'brush_px': 4, 'path': ((-2, 4), (18, 4))},
            {'color_index': 2, 'brush_px': 1, 'path': ()},
            {'color_index': 0, 'path': ((8, -2), (8, 14))},
            {'color_index': 2, 'brush_px': 3, 'path': ((1, 1), (15, 11))},
            {'color_index': 1, 'brush_px': 2, 'path': ((12, 5),)},
            {'color_index': 0, 'brush_px': 1, 'path': ((15, 2), (2, 10))},
        ]
        fills = [{'color_index': 2, 'row_spans': [(2, 2, 14), (7, 11, 3)]}]
        for area, fitted, limit in (((71, 53), (60.5, 44.5), 73),
                ((2200, 1300), (2199., 1299.), 75000)):
            with self.subTest(canvas=area):
                options = {'_planning_canvas_size': area, 'planner_max_pixels': limit,
                           'corners': ((-33, -17), (-33+area[0], -17+area[1]))}
                projection = NativeBrushProjection((17, 13), fitted, options)
                expected, pixels, size = independent_ink(source, sequence, fitted, area, fill_regions=fills)
                metrics, coverage, error = regional.simulate_native_plan(source, sequence, projection, fills)
                with closing(coverage), closing(error):
                    self.assertEqual({key: metrics[key] for key in expected}, expected)
                    self.assertEqual(coverage.size, size)
                    self.assertEqual(coverage.tobytes(), pixels)
                    self.assertEqual(error.tobytes(), pixels)
                    self.assertEqual(metrics['simulation_tile_pixel_limit'], limit)
                    self.assertEqual(metrics['canvas_size'], area)

    def test_one_tile_does_not_prepare_an_index(self):
        source = sample_map()
        projection = projection_for(source, (64, 48))
        sequence = [{'color_index': 1, 'brush_px': 2, 'path': ((0, 0), (16, 12))}]
        with patch.object(regional, '_native_footprint_index',
                          side_effect=AssertionError('Single-tile geometry must stay streamed.')):
            actual = simulation_output(source, sequence, projection)
        expected, pixels, size = independent_ink(source, sequence, (64., 48.), (64, 48))
        self.assertEqual({key: actual[0][key] for key in expected}, expected)
        self.assertEqual(actual[1:], (size, pixels, pixels))

    def test_seeded_overpaint_and_empty_schedule_match_independent_ink(self):
        area, fitted = (85, 203), (80.5, 199.25)
        for seed in (1481901, 1481902):
            source = sample_map(seed=seed)
            projection = NativeBrushProjection((17, 13), fitted,
                {'_planning_canvas_size': area, 'corners': ((-33, -17), (52, 186))})
            for sequence in ([], mixed_sequence(seed=seed)):
                with self.subTest(seed=seed, paths=len(sequence)):
                    expected, pixels, size = independent_ink(source, sequence, fitted, area)
                    actual = simulation_output(source, sequence, projection)
                    self.assertEqual({key: actual[0][key] for key in expected}, expected)
                    self.assertEqual(actual[1:], (size, pixels, pixels))

    def test_capacity_overflow_streams_identical_ink_without_mutating_borrowed_maps(self):
        source = sample_map()
        arrays = [value for value in vars(source).values() if isinstance(value, np.ndarray)]
        saved = [value.tobytes() for value in arrays]
        for value in arrays:
            value.flags.writeable = False
        projection = projection_for(source)
        sequence = [{'color_index': 1, 'brush_px': 4, 'path': ((0, 0), (16, 12))},
                    {'color_index': 2, 'path': ((0, 6), (16, 6))}]
        original = copy.deepcopy(sequence)
        with patch.object(regional, '_MAX_NATIVE_FOOTPRINTS', 0):
            expected = simulation_output(source, sequence, projection)
        allocate = np.empty
        allocated, references = [], []
        def observed(shape, *args, **kwargs):
            result = allocate(shape, *args, **kwargs)
            if result.ndim == 2 and result.shape[1] == 5 and result.dtype == np.int64:
                allocated.append(result.nbytes)
                references.append(weakref.ref(result))
            return result
        with patch.object(regional, '_MAX_NATIVE_FOOTPRINTS', 16), \
                patch.object(regional.np, 'empty', new=observed):
            actual = simulation_output(source, sequence, projection)
        self.assertEqual(actual, expected)
        self.assertEqual(allocated, [16*5*8])
        self.assertTrue(all(reference() is None for reference in references))
        self.assertEqual(sequence, original)
        self.assertEqual([value.tobytes() for value in arrays], saved)
        # A larger allowed index handles the same diagonal without changing
        # any count, paint ordering, or downsampled diagnostic byte.
        self.assertEqual(simulation_output(source, sequence, projection), expected)

    def test_pixel_allowance_limits_preparation_and_success_retains_only_used_records(self):
        source = sample_map()
        projection = projection_for(source, limit=192)
        sequence = [{'color_index': 1, 'brush_px': 2, 'path': ((0, 3), (16, 3))},
                    {'color_index': 0, 'brush_px': 4, 'path': ((0, 8), (16, 8))}]
        allocate = np.empty
        allocated = []
        def observed(shape, *args, **kwargs):
            result = allocate(shape, *args, **kwargs)
            if result.ndim == 2 and result.shape[1] == 5:
                allocated.append(result.nbytes)
            return result
        with patch.object(regional.np, 'empty', new=observed):
            records = regional._native_footprint_index(projection, sequence, (),
                default_brush=1, cancelled=lambda: False)
        self.assertEqual(allocated, [192*5*8])
        self.assertEqual(records.nbytes, 2*5*8)
        self.assertTrue(records.flags.owndata)
        self.assertEqual(records.shape, (2, 5))

    def test_one_shot_paths_sequences_and_fill_spans_keep_streaming_consumption(self):
        source = sample_map()
        projection = projection_for(source)
        base = [{'color_index': 1, 'brush_px': 2, 'path': ((0, 3), (16, 3))},
                {'color_index': 0, 'path': ((8, 0), (8, 12))}]
        def inputs(kind):
            sequence, fills = copy.deepcopy(base), [{'color_index': 2, 'row_spans': [(2, 1, 15)]}]
            if kind == 'sequence':
                sequence = iter(sequence)
            elif kind == 'path':
                sequence[0]['path'] = iter(sequence[0]['path'])
            elif kind == 'fills':
                fills = iter(fills)
            elif kind == 'spans':
                fills[0]['row_spans'] = iter(fills[0]['row_spans'])
            return sequence, fills
        for kind in ('sequence', 'path', 'fills', 'spans'):
            with self.subTest(iterator=kind):
                sequence, fills = inputs(kind)
                with patch.object(regional, '_MAX_NATIVE_FOOTPRINTS', 0):
                    expected = simulation_output(source, sequence, projection, fills)
                sequence, fills = inputs(kind)
                actual = simulation_output(source, sequence, projection, fills)
                self.assertEqual(actual, expected)

    def test_optional_index_allocation_and_shrink_failure_fall_back_to_exact_streaming(self):
        source = sample_map()
        projection = projection_for(source)
        sequence = [{'color_index': 1, 'brush_px': 2, 'path': ((0, 3), (16, 3))},
                    {'color_index': 0, 'path': ((8, 0), (8, 12))}]
        with patch.object(regional, '_MAX_NATIVE_FOOTPRINTS', 0):
            expected = simulation_output(source, sequence, projection)
        allocate = np.empty
        class Unshrinkable(np.ndarray):
            def resize(self, *args, **kwargs):
                raise MemoryError('Optional shrink allocation unavailable.')
        for stage in ('allocate', 'shrink'):
            with self.subTest(stage=stage):
                events = []
                def failing(shape, *args, **kwargs):
                    if tuple(np.atleast_1d(shape)) == (8192, 5):
                        events.append(stage)
                        if stage == 'allocate':
                            raise MemoryError('Optional index allocation unavailable.')
                        return allocate(shape, *args, **kwargs).view(Unshrinkable)
                    return allocate(shape, *args, **kwargs)
                with patch.object(regional.np, 'empty', new=failing):
                    actual = simulation_output(source, sequence, projection)
                self.assertEqual(events, [stage])
                self.assertEqual(actual, expected)

    def test_optional_allocation_does_not_hide_stop_or_invalid_geometry(self):
        source = sample_map()
        projection = projection_for(source)
        sequence = [{'color_index': 1, 'path': ((0, 3), (16, 3))}]
        allocate = np.empty
        state = {'stop': False}
        def unavailable(shape, *args, **kwargs):
            if tuple(np.atleast_1d(shape)) == (8192, 5):
                state['stop'] = True
                raise MemoryError('Stop arrived while optional storage was unavailable.')
            return allocate(shape, *args, **kwargs)
        with patch.object(regional.np, 'empty', new=unavailable), self.assertRaises(InterruptedError):
            regional.simulate_native_plan(source, sequence, projection, cancelled=lambda: state['stop'])
        for bad in ({'color_index': -2, 'path': ((0, 0),)},
                    {'color_index': 1, 'path': ((0,),)}):
            with self.subTest(entry=bad), self.assertRaises(ValueError):
                regional.simulate_native_plan(source, [bad], projection)

    def test_stop_during_preparation_or_query_releases_private_index_with_retained_traceback(self):
        for stage in ('preparation', 'query'):
            with self.subTest(stage=stage), ExitStack() as stack:
                source = sample_map()
                projection = projection_for(source)
                sequence = [{'color_index': 1, 'brush_px': 2, 'path': ((0, 3), (16, 3))},
                            {'color_index': 0, 'path': ((8, 0), (8, 12))}]
                allocated, images = [], []
                state = {'stop': False}
                allocate, create = np.empty, Image.new
                native, indices = projection.native_path, np.flatnonzero
                prepare = regional._native_footprint_index
                def observed_empty(shape, *args, **kwargs):
                    result = allocate(shape, *args, **kwargs)
                    if stage == 'preparation' and result.ndim == 2 and result.shape[1] == 5 and result.dtype == np.int64:
                        allocated.append(weakref.ref(result))
                    return result
                def observed_prepared(*args, **kwargs):
                    result = prepare(*args, **kwargs)
                    # NumPy forbids resizing an array with live weakrefs even
                    # with refcheck=False. Observe the completed private table.
                    allocated.append(weakref.ref(result))
                    return result
                def observed_image(*args, **kwargs):
                    result = create(*args, **kwargs)
                    images.append(result)
                    return result
                def native_then_stop(*args, **kwargs):
                    result = native(*args, **kwargs)
                    state['stop'] = True
                    return result
                def indices_then_stop(*args, **kwargs):
                    result = indices(*args, **kwargs)
                    state['stop'] = True
                    return result
                stack.enter_context(patch.object(regional.np, 'empty', new=observed_empty))
                stack.enter_context(patch.object(regional.Image, 'new', new=observed_image))
                stack.enter_context(patch.object(projection, 'native_path', new=native_then_stop)
                    if stage == 'preparation' else patch.object(regional.np, 'flatnonzero', new=indices_then_stop))
                if stage == 'query':
                    stack.enter_context(patch.object(regional, '_native_footprint_index', new=observed_prepared))
                failure = None
                try:
                    regional.simulate_native_plan(source, sequence, projection,
                        cancelled=lambda: state['stop'])
                except InterruptedError as error:
                    failure = error
                self.assertIsNotNone(failure)
                self.assertIsNotNone(failure.__traceback__)
                self.assertEqual(len(allocated), 1)
                self.assertTrue(all(reference() is None for reference in allocated))
                self.assertEqual(len(images), 1)
                with self.assertRaises(ValueError):
                    images[0].getpixel((0, 0))
                # Caller-owned numeric maps remain usable while the stopped
                # frame is deliberately retained for diagnostics.
                self.assertEqual(source.palette_index.shape, (13, 17))


if __name__ == '__main__':
    unittest.main()
