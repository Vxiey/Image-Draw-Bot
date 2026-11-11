"""One exact horizontal-run extraction supplies Pixel paths and source groups.

Every source is an existing repository PNG. Numeric label/ink oracles inspect
those pixels and real plans; no new source images or motifs are constructed.
"""
from collections import deque
from contextlib import closing, contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import Colors
import ExecutionCostModel
import PixelStrokeEngine as strokes
from ContinuousPaths import DOT_MODE
from PixelAccuratePlanner import build_pixel_map, groups_from_pixel_map
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch38_prepared_paths import close_plan


ROOT = Path(__file__).resolve().parent
EVIDENCE = []


@contextmanager
def source_image(asset='assets/paint-tools-reference.png', bound=None):
    with closing(Image.open(ROOT / asset)) as original, closing(original.convert('RGBA')) as image:
        if bound:
            image.thumbnail((bound, bound))
        yield image


def public_options(**changes):
    settings = opts(render_preset='Manual', drawing_style='Auto', subject_focus='Off',
        time_budget_mode='Unlimited', unlimited_time=True, cpu_workers_resolved=1,
        ram_budget_mb=512, cpu_workers='1', resource_scheduler='Off',
        _execution_cost_calibration_override={}, detail_zoom='Off', preview_plan=True)
    settings.update(changes)
    return settings


def stable(value):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key != 'planning_stage_seconds'}
    if isinstance(value, (tuple, list)):
        return [stable(item) for item in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(stable(value), sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def map_pixels(pixel_map):
    return {name: hashlib.sha256(np.asarray(getattr(pixel_map, name)).tobytes()).hexdigest()
            for name in ('rgb', 'palette_index', 'drawable_mask', 'edge_map',
                         'importance_map', 'protected_mask')}


def scalar_components(pixel_map):
    """Independent row-major four-neighbor flood on the actual mapped asset."""
    indices, drawable = pixel_map.palette_index, pixel_map.drawable_mask
    height, width = drawable.shape
    labels = np.full((height, width), -1, dtype=np.int32)
    records = []
    for y in range(height):
        for x in range(width):
            if not drawable[y, x] or labels[y, x] >= 0:
                continue
            cid, color = len(records), int(indices[y, x])
            queue = deque([(x, y)])
            labels[y, x] = cid
            area, left, top, right, bottom = 0, x, y, x, y
            while queue:
                px, py = queue.popleft()
                area += 1
                left, top, right, bottom = min(left, px), min(top, py), max(right, px), max(bottom, py)
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if (0 <= nx < width and 0 <= ny < height and drawable[ny, nx]
                            and labels[ny, nx] < 0 and int(indices[ny, nx]) == color):
                        labels[ny, nx] = cid
                        queue.append((nx, ny))
            records.append((cid, color, area, (left, top, right, bottom)))
    return labels, records


def plan_signature(plan):
    result = {key: stable(plan[key]) for key in ('groups', 'execution_groups', 'execution_sequence',
              'colors', 'fitted', 'estimate', 'path_stats', 'count', 'source_count')}
    result['pixel_metadata'] = {key: stable(plan['options'].get(key)) for key in (
        'pixel_map_meta', 'pixel_stroke_meta', 'pixel_accuracy_meta', 'picture_palette_meta')}
    result['image'] = hashlib.sha256(plan['image'].tobytes()).hexdigest()
    result['preview'] = hashlib.sha256(plan['preview'].tobytes()).hexdigest()
    result['ui_previews'] = {key: hashlib.sha256(value.tobytes()).hexdigest()
        for key, value in plan.get('ui_previews', {}).items() if isinstance(value, Image.Image)}
    return digest(result)


class PixelRunReuseTests(unittest.TestCase):
    def setUp(self):
        self.previous_palette = list(Colors.allColors)
        Colors.reset_palette()
        self.palette = tuple(color.RGB for color in Colors.allColors)

    def tearDown(self):
        Colors.allColors[:] = self.previous_palette
        from PixelData import closest_color
        closest_color.cache_clear()

    def pixel_map(self, image, skip_white=False):
        return build_pixel_map(image, self.palette, gpu_mode='CPU', skip_white=skip_white)

    def assert_component_oracle(self, pixel_map, components, labels):
        expected_labels, records = scalar_components(pixel_map)
        np.testing.assert_array_equal(labels, expected_labels)
        self.assertEqual([(c.component_id, c.color_index, c.area, c.bbox) for c in components], records)

    def test_public_pixel_and_subject_plans_omit_the_duplicate_run_scan(self):
        from DrawBot import make_plan
        cases = (('lines', {}, 0),
                 ('timed', {'time_budget_mode':'30 sec', 'unlimited_time':False, 'brush_px':3}, 0),
                 ('subject-first', {'subject_focus':'Subject first', 'subject_region':(.2, .1, .85, .8)}, 0),
                 ('subject-only', {'subject_focus':'Subject only', 'subject_region':(.2, .1, .85, .8)}, 0),
                 ('dots', {'lines':False, 'drawing_mode':DOT_MODE, 'smart_paths':False}, 1))
        for name, change, expected_scans in cases:
            with self.subTest(case=name), source_image() as image:
                before = image.tobytes()
                with patch.object(strokes, 'groups_from_pixel_map', wraps=strokes.groups_from_pixel_map) as scans:
                    plan = make_plan(image, (96, 96), public_options(**change))
                try:
                    self.assertTrue(plan['options']['pixel_accurate'])
                    self.assertGreater(plan['count'], 0)
                    EVIDENCE.append(dict(case='public', name=name, legacy_group_scans=scans.call_count,
                        source_runs=plan['source_count'], paths=plan['count'], signature=plan_signature(plan)))
                    self.assertEqual(image.tobytes(), before)
                    self.assertEqual(scans.call_count, expected_scans)
                finally:
                    close_plan(plan, image)

    def test_component_and_color_lists_share_the_same_real_segment_tuples(self):
        real = strokes.connected_components
        for asset in ('assets/paint-tools-reference.png', 'assets/image-draw-bot-app-screenshot.png',
                      'assets/image-draw-bot-icon.png'):
            with self.subTest(asset=asset), source_image(asset, 96) as image:
                pixel_map = self.pixel_map(image, skip_white=True)
                before = map_pixels(pixel_map)
                expected = groups_from_pixel_map(pixel_map, len(self.palette))
                segment_ids, component_records = set(), []
                def observe(target, **kwargs):
                    result = real(target, **kwargs)
                    components, labels, _ = result
                    self.assert_component_oracle(target, components, labels)
                    for component in components:
                        segment_ids.update(map(id, component.horizontal_runs))
                    component_records.append([(c.component_id, c.color_index, c.area, c.bbox) for c in components])
                    return result
                with patch.object(strokes, 'connected_components', observe):
                    actual = strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), options=public_options())
                self.assertEqual(actual['groups'], expected)
                self.assertEqual(len(component_records), 1)
                self.assertEqual(map_pixels(pixel_map), before)
                output_ids = {id(segment) for group in actual['groups'] for segment in group}
                shared = len(segment_ids & output_ids)
                EVIDENCE.append(dict(case='builder', asset=asset, source_runs=sum(map(len, expected)),
                    shared_segments=shared, signature=digest(actual), component_signature=digest(component_records)))
                self.assertGreater(len(output_ids), 0)
                self.assertEqual(shared, len(output_ids),
                    'The same horizontal segment is still allocated separately for source groups and components.')
                self.assertEqual(shared, len(segment_ids))

    def test_standalone_components_and_parallel_paths_keep_their_contract(self):
        with source_image('assets/image-draw-bot-app-screenshot.png', 96) as image:
            pixel_map = self.pixel_map(image, skip_white=True)
            before = map_pixels(pixel_map)
            serial = strokes.connected_components(pixel_map, cpu_workers=1)
            self.assert_component_oracle(pixel_map, serial[0], serial[1])
            parallel = strokes.connected_components(pixel_map, cpu_workers=2)
            self.assert_component_oracle(pixel_map, parallel[0], parallel[1])
            self.assertEqual([c.meta() for c in serial[0]], [c.meta() for c in parallel[0]])
            self.assertEqual([c.horizontal_runs for c in serial[0]], [c.horizontal_runs for c in parallel[0]])
            self.assertEqual([c.vertical_runs for c in serial[0]], [c.vertical_runs for c in parallel[0]])
            result = strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), cpu_workers=2,
                                                     options=public_options())
            self.assertEqual(result['groups'], groups_from_pixel_map(pixel_map, len(self.palette)))
            EVIDENCE.append(dict(case='parallel', signature=digest(result)))
            self.assertEqual(map_pixels(pixel_map), before)

    def test_dots_and_empty_asset_crops_keep_the_existing_group_builder(self):
        with source_image() as image:
            pixel_map = self.pixel_map(image)
            expected = groups_from_pixel_map(pixel_map, len(self.palette), lines=False)
            with patch.object(strokes, 'groups_from_pixel_map', wraps=strokes.groups_from_pixel_map) as scan, \
                 patch.object(strokes, 'connected_components', wraps=strokes.connected_components) as components:
                result = strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), lines=False,
                                                         options=public_options())
            self.assertEqual(scan.call_count, 1)
            self.assertEqual(components.call_count, 0)
            self.assertEqual(result['groups'], expected)
            self.assertEqual(sum(map(len, result['execution_groups'])), int(np.count_nonzero(pixel_map.drawable_mask)))
            self.assertTrue(result['metadata']['dot_mode'])
        with source_image('assets/image-draw-bot-icon.png') as icon, closing(icon.crop((0, 0, 1, 1))) as corner:
            pixel_map = self.pixel_map(corner, skip_white=True)
            self.assertFalse(np.any(pixel_map.drawable_mask), 'The existing icon corner must remain unpainted.')
            for lines in (False, True):
                with self.subTest(lines=lines):
                    result = strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), lines=lines,
                                                             options=public_options())
                    self.assertEqual(result['groups'], [[] for _ in self.palette])
                    self.assertEqual(result['execution_sequence'], [])

    def test_unsigned_and_read_only_target_arrays_preserve_color_and_run_order(self):
        with source_image('assets/image-draw-bot-icon.png', 64) as image:
            pixel_map = self.pixel_map(image, skip_white=True)
            unsigned = pixel_map.palette_index.astype(np.uint16)
            unsigned.flags.writeable = False
            mask = pixel_map.drawable_mask.copy()
            mask.flags.writeable = False
            target = replace(pixel_map, palette_index=unsigned, drawable_mask=mask)
            before = map_pixels(target)
            actual = strokes.build_pixel_stroke_plan(target, len(self.palette), options=public_options())
            self.assertEqual(actual['groups'], groups_from_pixel_map(target, len(self.palette)))
            self.assertEqual(actual['groups'], groups_from_pixel_map(pixel_map, len(self.palette)))
            self.assertEqual(map_pixels(target), before)
            EVIDENCE.append(dict(case='unsigned', signature=digest(actual)))

    def test_palette_validation_and_initial_stop_precede_model_construction(self):
        with source_image() as image:
            pixel_map = self.pixel_map(image)
            before = map_pixels(pixel_map)
            maximum = int(np.max(pixel_map.palette_index[pixel_map.drawable_mask]))
            self.assertGreater(maximum, 0)
            for count in (True, 0, maximum):
                with self.subTest(palette_count=count), \
                     patch.object(ExecutionCostModel, 'build_cost_model', wraps=ExecutionCostModel.build_cost_model) as model:
                    with self.assertRaises(ValueError):
                        strokes.build_pixel_stroke_plan(pixel_map, count, options=public_options())
                    self.assertEqual(model.call_count, 0)
            with patch.object(ExecutionCostModel, 'build_cost_model', wraps=ExecutionCostModel.build_cost_model) as model:
                with self.assertRaises(InterruptedError):
                    strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), options=public_options(),
                                                    cancelled=lambda: True)
                self.assertEqual(model.call_count, 0)
            self.assertEqual(map_pixels(pixel_map), before)

    def test_stop_during_real_component_collection_leaves_target_reusable(self):
        real = strokes._row_component_statistics
        with source_image() as image:
            pixel_map = self.pixel_map(image)
            before = map_pixels(pixel_map)
            expected = strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), options=public_options())
            rows, stopped = [], [False]
            def observe(*args, **kwargs):
                result = real(*args, **kwargs)
                rows.append(1)
                if len(rows) == 3:
                    stopped[0] = True
                return result
            retained = None
            with patch.object(strokes, '_row_component_statistics', observe):
                try:
                    strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), options=public_options(),
                                                    cancelled=lambda: stopped[0])
                except InterruptedError as error:
                    retained = error
            self.assertIsNotNone(retained)
            self.assertEqual(len(rows), 3)
            self.assertEqual(map_pixels(pixel_map), before)
            retried = strokes.build_pixel_stroke_plan(pixel_map, len(self.palette), options=public_options())
            self.assertEqual(stable(retried), stable(expected))
            self.assertIsNotNone(retained.__traceback__)


if __name__ == '__main__':
    unittest.main()
