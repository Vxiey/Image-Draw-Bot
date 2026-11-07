"""Actual Pixel stages share exact topology within one bounded operation."""
from collections import deque
from contextlib import ExitStack, closing, contextmanager
from dataclasses import asdict, is_dataclass, replace
import hashlib
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageDraw
import AdaptiveBrushEngine
import Colors
import DrawBot
import PixelAccuracyEngine as accuracy
import PixelStrokeEngine as strokes
import PixelRegionTopology as topology
from test_pixel_accuracy_engine_v1088 import pm_from_index
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated
from test_v148_rendering_batch24_component_queue import PALETTE, public_options, checker_source


TIMED_ASSET = Path(__file__).parent / 'golden-regression/small-detail-preservation.png'
TIMED_CROP = (155, 102, 174, 121)
TIMED_PALETTE = tuple(rgb for _name, rgb in Colors.DEFAULT_COLORS)
TIMED_PALETTE_NAMES = tuple(name for name, _rgb in Colors.DEFAULT_COLORS)


def timed_source():
    with closing(Image.open(TIMED_ASSET)) as asset:
        return asset.crop(TIMED_CROP)


def timed_options(**changes):
    settings = public_options(subject_focus='Off', brush_px=3,
        time_budget_mode='30 sec', unlimited_time=False)
    settings.update(changes)
    return settings


def scalar_topology(pixel_map):
    """Independent row-major four-neighbor flood, not production union/find."""
    indices = np.asarray(pixel_map.palette_index)
    drawable = np.asarray(pixel_map.drawable_mask, dtype=bool)
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
            area, x0, y0, x1, y1 = 0, x, y, x, y
            while queue:
                px, py = queue.popleft()
                area += 1
                x0, y0 = min(x0, px), min(y0, py)
                x1, y1 = max(x1, px), max(y1, py)
                for nx, ny in ((px - 1, py), (px + 1, py),
                               (px, py - 1), (px, py + 1)):
                    if (0 <= nx < width and 0 <= ny < height and
                            drawable[ny, nx] and labels[ny, nx] < 0 and
                            int(indices[ny, nx]) == color):
                        labels[ny, nx] = cid
                        queue.append((nx, ny))
            records.append((cid, color, area, x0, y0, x1, y1))
    return labels, records


@contextmanager
def observe_topology(module=strokes, controller=DrawBot, *, check_scalar=True):
    """Count actual stages without retaining their labels or Component graph."""
    calls, reductions, boundaries, label_refs = [], [], [], []
    original = module.connected_components
    original_row = module._row_component_statistics
    original_finish = controller.finish_plan

    def row_observer(pixel_map, y, runs, *args, **kwargs):
        reductions.append((int(y), len(runs)))
        return original_row(pixel_map, y, runs, *args, **kwargs)

    def component_observer(pixel_map, *args, **kwargs):
        caller = sys._getframe(1).f_code.co_name
        start = len(reductions)
        result = original(pixel_map, *args, **kwargs)
        components, labels, metadata = result
        rows = [(int(c.component_id), int(c.color_index), int(c.area), *map(int, c.bbox))
                for c in components]
        if check_scalar:
            expected_labels, expected_rows = scalar_topology(pixel_map)
            np.testing.assert_array_equal(labels, expected_labels)
            if rows != expected_rows:
                raise AssertionError('Topology differs from independent scalar flood.')
        label_refs.append((caller, weakref.ref(labels)))
        calls.append(dict(caller=caller, components=len(components),
            source_runs=int(metadata['source_runs']), row_statistic_calls=len(reductions) - start,
            include_vertical_runs=kwargs.get('include_vertical_runs', True),
            label_sha256=hashlib.sha256(labels.tobytes()).hexdigest(),
            rows_sha256=hashlib.sha256(json.dumps(rows,separators=(',', ':')).encode()).hexdigest()))
        return result

    def finish_observer(*args, **kwargs):
        boundaries.append({'label_owners_still_alive':
                           [caller for caller, ref in label_refs if ref() is not None]})
        return original_finish(*args, **kwargs)

    with patch.object(module, 'connected_components', component_observer), \
            patch.object(module, '_row_component_statistics', row_observer), \
            patch.object(controller, 'finish_plan', finish_observer):
        yield calls, reductions, boundaries, label_refs


def block_source(size=(96, 72)):
    with closing(Image.new('RGB', (96, 72), 'white')) as source:
        draw = ImageDraw.Draw(source)
        draw.rectangle((8, 8, 41, 52), fill=(0, 0, 0))
        draw.rectangle((51, 17, 86, 61), fill=(239, 19, 11))
        draw.line((7, 64, 88, 64), fill=(0, 80, 205), width=1)
        return source.resize(size, Image.Resampling.NEAREST)


def alpha_source(size=(64, 48)):
    with closing(Image.new('RGBA', (64, 48), (85, 11, 209, 0))) as source:
        draw = ImageDraw.Draw(source)
        draw.rectangle((8, 8, 29, 39), fill=(0, 0, 0, 255))
        draw.rectangle((34, 11, 54, 36), fill=(239, 19, 11, 128))
        return source.resize(size, Image.Resampling.NEAREST)


def fixtures():
    return (
        ('checker64_subject_off_lines', lambda: checker_source((64, 64), margin=4), {}),
        ('blocks96_subject_off_lines', block_source, {}),
        ('alpha64_subject_off_lines', alpha_source, {}),
        ('blocks96_include_white_control', block_source, {'skip_white': False}),
        ('blocks96_fill_policy_control', block_source,
         {'background_fill': 'Balanced', 'use_region_fill_engine': True}),
        ('checker64_dot_control', lambda: checker_source((64, 64), margin=4), {'lines': False}),
        ('blocks96_subject_first_control', block_source,
         {'subject_focus': 'Subject first', 'subject_region': (.20, .20, .75, .80)}),
        ('blocks96_subject_only_control', block_source,
         {'subject_focus': 'Subject only', 'subject_region': (.20, .20, .75, .80)}),
        ('transparent32_empty_control', lambda: Image.new('RGBA', (32, 24), (13, 55, 91, 0)), {}),
    )


def fixture():
    return pm_from_index([[0, 0, -1, 1, 1], [0, -1, -1, 1, -1],
                          [2, 2, 2, -1, 1], [-1, 2, -1, 1, 1]])


def prepared(pixel_map, **limits):
    components, labels, _ = strokes.connected_components(pixel_map,
                                                          include_vertical_runs=False)
    owner = topology.PixelRegionTopology(pixel_map, **limits)
    return owner, components, labels


def contains_owner(value):
    if isinstance(value, topology.PixelRegionTopology):
        return True
    if isinstance(value, dict):
        return any(contains_owner(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(contains_owner(item) for item in value)
    return False


def comparable(value, path=()):
    from benchmark_v148_image_workflow import fingerprint
    if is_dataclass(value):
        return comparable(asdict(value), path)
    if isinstance(value, dict):
        return {key: comparable(item, (*path, key)) for key, item in value.items()
                if (*path, key) not in VOLATILE_PATHS}
    if isinstance(value, (tuple, list)):
        return [comparable(item, path) for item in value]
    return fingerprint(value)


class RegionTopologyTests(unittest.TestCase):
    def test_compact_summary_matches_independent_flood_without_component_graph(self):
        pm = fixture()
        owner, components, labels = prepared(pm)
        expected_labels, expected_rows = scalar_topology(pm)
        np.testing.assert_array_equal(labels, expected_labels)
        refs = [weakref.ref(c) for c in components]
        label_flags = labels.flags.writeable
        self.assertTrue(owner.offer(pm, components, labels))
        del components
        self.assertTrue(all(ref() is None for ref in refs))
        rows, handed_labels = owner.take(pm)
        self.assertIs(handed_labels, labels)
        self.assertEqual(rows.tolist(), [list(row) for row in expected_rows])
        self.assertFalse(rows.flags.writeable)
        self.assertEqual(labels.flags.writeable, label_flags)
        self.assertIsNone(owner.take(pm))
        self.assertIsNone(owner._labels)
        self.assertIsNone(owner._records)

    def test_inplace_visibility_color_replacement_and_view_changes_force_fresh_path(self):
        for change in ('mask_value', 'active_color', 'mask_copy', 'mask_view', 'index_copy',
                       'different_map', 'dimensions', 'dimension_type', 'index_dtype'):
            with self.subTest(change=change):
                pm = fixture()
                owner, components, labels = prepared(pm)
                self.assertTrue(owner.offer(pm, components, labels))
                if change == 'mask_value': pm.drawable_mask[0, 0] = False
                elif change == 'active_color': pm.palette_index[0, 0] = 2
                elif change == 'mask_copy': pm.drawable_mask = pm.drawable_mask.copy()
                elif change == 'mask_view': pm.drawable_mask = pm.drawable_mask.view()
                elif change == 'index_copy': pm.palette_index = pm.palette_index.copy()
                elif change == 'different_map': pm = replace(pm)
                elif change == 'dimensions': pm.width += 1
                elif change == 'dimension_type': pm.width = float(pm.width)
                elif change == 'index_dtype': pm.palette_index.dtype = np.float16
                self.assertIsNone(owner.take(pm))
                self.assertIsNone(owner._labels)
                self.assertIsNone(owner._records)

    def test_hidden_index_edits_do_not_change_effective_target(self):
        pm = fixture()
        owner, components, labels = prepared(pm)
        self.assertTrue(owner.offer(pm, components, labels))
        pm.palette_index[~pm.drawable_mask] = 32767
        self.assertIsNotNone(owner.take(pm))

    def test_explicit_bounds_and_noncanonical_masks_keep_fresh_fallback(self):
        for limits in ({'max_label_bytes': 0}, {'max_records': 0}):
            pm = fixture()
            owner, components, labels = prepared(pm, **limits)
            before = labels.copy()
            with patch.object(topology.np, 'empty', side_effect=AssertionError('no optional allocation')):
                self.assertFalse(owner.offer(pm, components, labels))
            np.testing.assert_array_equal(labels, before)
            self.assertIsNone(owner.take(pm))
        pm = fixture()
        pm.drawable_mask = pm.drawable_mask.astype(np.uint8) * 255
        owner, components, labels = prepared(pm)
        self.assertFalse(owner.offer(pm, components, labels))
        self.assertIsNone(owner.take(pm))

    def test_optional_memory_failure_does_not_hide_stop_or_modify_input(self):
        pm = fixture()
        owner, components, labels = prepared(pm)
        before = labels.copy()
        with patch.object(topology.np, 'empty', side_effect=MemoryError('record buffer')):
            self.assertFalse(owner.offer(pm, components, labels))
        self.assertIsNone(owner.take(pm))
        np.testing.assert_array_equal(labels, before)
        owner = topology.PixelRegionTopology(pm)
        with self.assertRaises(InterruptedError):
            owner.offer(pm, components, labels, cancelled=lambda: True)
        self.assertIsNone(owner._labels)

    def test_foreign_thread_cannot_consume_the_original_operations_owner(self):
        pm = fixture()
        owner, components, labels = prepared(pm)
        self.assertTrue(owner.offer(pm, components, labels))
        results = []
        worker = threading.Thread(target=lambda: results.append(owner.take(pm)))
        worker.start(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [None])
        self.assertIs(owner.take(pm)[1], labels)

    def test_retained_take_stop_traceback_releases_all_private_label_views(self):
        pm = fixture()
        owner, components, labels = prepared(pm)
        ref = weakref.ref(labels)
        self.assertTrue(owner.offer(pm, components, labels))
        del components, labels
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls == 2
        failure = None
        try:
            owner.take(pm, cancelled=cancelled)
        except InterruptedError as exc:
            failure = exc
        self.assertIsNotNone(failure)
        self.assertIsNotNone(failure.__traceback__)
        self.assertIsNone(ref())
        self.assertIsNone(owner._labels)

    def test_actual_public_work_reduction_and_no_labels_or_owner_at_export(self):
        with calibrated(PALETTE):
            for name, factory, changes in fixtures():
                if changes.get('subject_focus', 'Off') != 'Off' or changes.get('lines') is False:
                    continue
                with self.subTest(name=name), closing(factory()) as source:
                    before = source.tobytes()
                    plan = None
                    try:
                        with observe_topology(strokes, DrawBot) as (calls, rows, boundaries, refs):
                            settings = public_options(subject_focus='Off')
                            settings.update(changes)
                            plan = DrawBot.make_plan(source, source.size, settings)
                        self.assertEqual([row['caller'] for row in calls], ['build_pixel_stroke_plan'])
                        self.assertTrue(boundaries)
                        self.assertTrue(all(not row['label_owners_still_alive'] for row in boundaries))
                        self.assertTrue(all(ref() is None for _, ref in refs))
                        self.assertFalse(contains_owner(plan))
                        self.assertEqual(source.tobytes(), before)
                    finally:
                        if plan is not None: close_plan(plan, source)

    def test_actual_subject_and_dot_controls_keep_their_existing_fresh_calls(self):
        expected = {'checker64_dot_control': 1, 'blocks96_subject_first_control': 3,
                    'blocks96_subject_only_control': 2}
        with calibrated(PALETTE):
            for name, factory, changes in fixtures():
                if name not in expected:
                    continue
                with self.subTest(name=name), closing(factory()) as source:
                    plan = None
                    try:
                        with observe_topology(strokes, DrawBot) as (calls, _, boundaries, refs):
                            settings = public_options(subject_focus='Off')
                            settings.update(changes)
                            plan = DrawBot.make_plan(source, source.size, settings)
                        self.assertEqual(len(calls), expected[name])
                        self.assertTrue(all(not row['label_owners_still_alive'] for row in boundaries))
                        self.assertTrue(all(ref() is None for _, ref in refs))
                    finally:
                        if plan is not None: close_plan(plan, source)

    def test_actual_active_timer_keeps_complete_output_and_original_admitted_order(self):
        real_init = topology.PixelRegionTopology.__init__
        real_budget = accuracy.progressive_time_budget
        outputs, observations = [], []

        def no_records(self, pixel_map, **kwargs):
            return real_init(self, pixel_map, max_records=0, **kwargs)

        with calibrated(TIMED_PALETTE, names=TIMED_PALETTE_NAMES), closing(timed_source()) as source, \
                patch('RealSpeedBudget.load_profile', return_value=None):
            source_bytes = source.tobytes()
            for reuse in (False, True):
                with self.subTest(reuse=reuse), ExitStack() as stack:
                    if not reuse:
                        stack.enter_context(patch.object(topology.PixelRegionTopology, '__init__', no_records))
                    budget_calls = []
                    def budget(sequence, **kwargs):
                        result = real_budget(sequence, **kwargs)
                        budget_calls.append(([dict(row) for row in sequence], result))
                        return result
                    stack.enter_context(patch.object(accuracy, 'progressive_time_budget', budget))
                    plan = None
                    try:
                        with observe_topology() as (calls, _, boundaries, refs):
                            plan = DrawBot.make_plan(source, (100, 100), timed_options())
                        self.assertEqual(len(calls), 1 if reuse else 2)
                        self.assertEqual(len(budget_calls), 1)
                        original, result = budget_calls[0]
                        self.assertTrue(result['active'])
                        self.assertGreater(result['paths_omitted'], 0)
                        self.assertEqual(result['phase_order'], 'original execution order')
                        self.assertEqual(result['admission_priority'],
                            'fill -> mid detail -> protected cleanup -> fine detail')
                        # Check occurrences, including equal entries, as an
                        # ordered subsequence of the real pre-budget builder.
                        remaining = iter(original)
                        for entry in result['execution_sequence']:
                            self.assertTrue(any(candidate == entry for candidate in remaining))
                        self.assertEqual(plan['options']['pixel_accuracy_meta']['progressive_time_budget'],
                            {key: value for key, value in result.items() if key != 'execution_sequence'})
                        self.assertTrue(boundaries)
                        self.assertTrue(all(not row['label_owners_still_alive'] for row in boundaries))
                        self.assertTrue(all(ref() is None for _, ref in refs))
                        self.assertFalse(contains_owner(plan))
                        outputs.append(comparable(plan))
                        observations.append(result)
                    finally:
                        if plan is not None: close_plan(plan, source)
            self.assertEqual(len(outputs), 2)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(observations[0], observations[1])
            self.assertEqual(source.tobytes(), source_bytes)

    def test_actual_public_optional_allocation_and_capacity_failures_keep_complete_fresh_output(self):
        real_init = topology.PixelRegionTopology.__init__
        real_empty, real_any = np.empty, np.any

        def no_records(self, pixel_map, **kwargs):
            return real_init(self, pixel_map, max_records=0, **kwargs)

        def fail_records(*args, **kwargs):
            if sys._getframe(1).f_code.co_name == 'offer':
                raise MemoryError('optional record allocation')
            return real_empty(*args, **kwargs)

        def fail_validation(*args, **kwargs):
            if sys._getframe(1).f_code.co_name == '_same_effective_target':
                raise MemoryError('optional validation allocation')
            return real_any(*args, **kwargs)

        variants = (
            ('capacity', lambda: patch.object(topology.PixelRegionTopology, '__init__', no_records)),
            ('record allocation', lambda: patch.object(topology.np, 'empty', fail_records)),
            ('validation allocation', lambda: patch.object(topology.np, 'any', fail_validation)),
            ('owner allocation', lambda: patch.object(topology.PixelRegionTopology, '__init__',
                                                      side_effect=MemoryError('optional owner'))),
        )
        with calibrated(PALETTE), closing(block_source()) as source:
            expected_plan = DrawBot.make_plan(source, source.size, public_options(subject_focus='Off'))
            try:
                expected = comparable(expected_plan)
            finally:
                close_plan(expected_plan, source)
            for name, fault in variants:
                with self.subTest(name=name), fault():
                    plan = None
                    try:
                        with observe_topology(check_scalar=False) as (calls, _, boundaries, refs):
                            plan = DrawBot.make_plan(source, source.size, public_options(subject_focus='Off'))
                        self.assertEqual([row['caller'] for row in calls],
                                         ['build_pixel_stroke_plan', 'region_accuracy_scores'])
                        self.assertEqual(comparable(plan), expected)
                        self.assertTrue(all(not row['label_owners_still_alive'] for row in boundaries))
                        self.assertTrue(all(ref() is None for _, ref in refs))
                    finally:
                        if plan is not None: close_plan(plan, source)

    def test_actual_public_retained_stop_and_error_drop_labels_and_all_components(self):
        real_components = strokes.connected_components
        real_priority = strokes._priority
        real_simulate = accuracy.simulate_strokes
        real_brushes = AdaptiveBrushEngine.assign_adaptive_brushes
        for phase in ('late offer Stop', 'regional score Stop', 'simulation error', 'brush assignment error'):
            with self.subTest(phase=phase), calibrated(PALETTE), closing(block_source()) as source, ExitStack() as stack:
                label_refs, component_refs = [], []
                stop_at_offer = False
                regional_checks = 0

                def observed_components(*args, **kwargs):
                    result = real_components(*args, **kwargs)
                    component_refs.extend(weakref.ref(c) for c in result[0])
                    label_refs.append(weakref.ref(result[1]))
                    return result

                def priority(comp):
                    nonlocal stop_at_offer
                    value = real_priority(comp)
                    if (sys._getframe(1).f_code.co_name == '<lambda>' and
                            sys._getframe(2).f_code.co_name == 'build_pixel_stroke_plan'):
                        # The real final diagnostic sort completes before the
                        # late offer sees Stop. This wrapper has already returned
                        # when the exception is raised, so it pins no Component.
                        stop_at_offer = True
                    return value

                def cancelled():
                    nonlocal regional_checks
                    if phase == 'late offer Stop':
                        return stop_at_offer
                    if phase == 'regional score Stop' and sys._getframe(1).f_code.co_name == 'region_accuracy_scores':
                        regional_checks += 1
                        return regional_checks == 3
                    return False

                def fail_after_real_simulation(*args, **kwargs):
                    real_simulate(*args, **kwargs)
                    raise RuntimeError('failure while topology awaits regional scoring')

                def fail_after_real_brushes(*args, **kwargs):
                    real_brushes(*args, **kwargs)
                    raise RuntimeError('failure before the original accuracy try boundary')

                stack.enter_context(patch.object(strokes, 'connected_components', observed_components))
                if phase == 'late offer Stop':
                    stack.enter_context(patch.object(strokes, '_priority', priority))
                if phase == 'simulation error':
                    stack.enter_context(patch.object(accuracy, 'simulate_strokes', fail_after_real_simulation))
                if phase == 'brush assignment error':
                    stack.enter_context(patch.object(AdaptiveBrushEngine, 'assign_adaptive_brushes', fail_after_real_brushes))
                failure = None
                try:
                    DrawBot.make_plan(source, source.size, public_options(subject_focus='Off'), cancelled)
                except (InterruptedError, RuntimeError) as exc:
                    failure = exc
                self.assertIsNotNone(failure)
                self.assertIsInstance(failure, RuntimeError if phase.endswith('error') else InterruptedError)
                self.assertIsNotNone(failure.__traceback__)
                self.assertTrue(label_refs)
                self.assertTrue(component_refs)
                self.assertTrue(all(ref() is None for ref in label_refs))
                self.assertTrue(all(ref() is None for ref in component_refs))

    def test_standalone_scorer_observes_an_inplace_target_edit(self):
        pm = pm_from_index([[0, 0, 0]])
        simulation = accuracy.simulate_strokes(pm,
            [{'color_index': 0, 'path': ((0, 0), (2, 0))}], PALETTE)
        with patch.object(strokes, 'connected_components', wraps=strokes.connected_components) as counted:
            before = accuracy.region_accuracy_scores(pm, simulation)
            pm.palette_index[0, 1] = 1
            after = accuracy.region_accuracy_scores(pm, simulation)
        self.assertEqual(counted.call_count, 2)
        self.assertEqual(before['region_count'], 1)
        self.assertEqual(after['region_count'], 3)

    def test_real_numpy_shape_error_does_not_pin_consumed_labels_in_traceback(self):
        pm = fixture()
        owner, components, labels = prepared(pm)
        ref = weakref.ref(labels)
        self.assertTrue(owner.offer(pm, components, labels))
        del components, labels
        # This actual invalid raster shape reaches NumPy's boolean-index error;
        # no mock fabricates a swallowed exception or clears a frame for us.
        invalid = accuracy.SimulationResult(np.zeros((1, 1), np.int16),
            np.ones((1, 1), np.uint16), np.ones((1, 1), bool), np.zeros((1, 1), np.uint8), {})
        failure = None
        try:
            accuracy.region_accuracy_scores(pm, invalid, _region_topology=owner)
        except IndexError as exc:
            failure = exc
        self.assertIsNotNone(failure)
        self.assertIsNotNone(failure.__traceback__)
        self.assertIsNone(ref())
        self.assertIsNone(owner._labels)


if __name__ == '__main__':
    unittest.main()
