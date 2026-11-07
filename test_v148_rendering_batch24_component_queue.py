"""Pixel's bounded candidate queue preserves order, pricing and real delivery."""
from contextlib import ExitStack, closing, contextmanager
import builtins
import copy
import math
import random
import sys
import threading
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageDraw

import DrawBot
import ExecutionCostModel as costs
import PixelStrokeEngine as strokes
from test_drawbot import NoWait
from test_v148_accuracy_batch12_context import public_options as pixel_options
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch16_selector import PaletteInkMouse, ORIGIN
from test_v148_rendering_batch17_layered_diagnostics import calibrated


PALETTE = ((0, 0, 0), (255, 255, 255), (239, 19, 11), (0, 80, 205))


def components_fixture(count, *, seed=24, single_phase=False):
    rng = random.Random(seed)
    result = []
    for cid in range(count):
        x, y = rng.randrange(-15, 65), rng.randrange(-10, 55)
        length = rng.randrange(1, 8)
        path = ((x, y),) if cid % 4 == 0 else ((x, y), (x + length, y))
        result.append(strokes.Component(cid, cid % 4, area=length,
            bbox=(x, y, x + length - 1, y), importance_mean=(cid % 7) / 10,
            importance_max=(cid % 9) / 10, edge_mean=(cid % 5) / 10,
            contour_mean=(cid % 3) / 10, shadow_mean=(cid % 4) / 10,
            shadow_detail_mean=(cid % 6) / 10, protected_pixels=int(cid % 5 == 0),
            render_role=('base', 'detail', 'shadow', 'contour')[cid % 4],
            phase='fine_detail' if single_phase else strokes.PHASES[cid % 4],
            paths=[path, ()] if cid % 17 == 0 else [path]))
    rng.shuffle(result)
    return result


def priority(component):
    """Scalar priority oracle; it does not call the production scheduler."""
    c = component
    if c.phase == 'fill':
        return c.area * 1.0 + c.importance_mean * 20.0
    if c.phase == 'mid_detail':
        return c.area * .20 + c.importance_mean * 120.0 + c.edge_mean * 50.0
    if c.phase == 'fine_detail':
        bonus = 80.0 if c.render_role == 'contour' else 60.0 if c.render_role == 'shadow_detail' else 0.0
        return (c.importance_mean * 180.0 + c.edge_mean * 80.0 + c.contour_mean * 90.0 +
                c.shadow_detail_mean * 70.0 + min(c.area, 80) * .15 + bonus)
    bonus = 120.0 if c.render_role == 'contour' else 90.0 if c.render_role == 'shadow_detail' else 0.0
    ratio = 0.0 if c.area <= 0 else float(c.protected_pixels) / float(c.area)
    return (c.importance_max * 220.0 + ratio * 160.0 + c.edge_mean * 50.0 +
            c.contour_mean * 110.0 + c.shadow_detail_mean * 90.0 + bonus)


def legacy_component_order(components, model=None):
    """Independent original full-list selection, including exact cost order.

    This deliberately removes from the full pending list. It is a small order
    oracle, not a second implementation of the new bounded queue. The benchmark
    separately compares every result field with the whole historical module.
    """
    intrinsic, entry_costs = {}, {}
    prepare = getattr(model, 'prepare_path_cost', None)
    if model is not None:
        for c in components:
            if not c.paths:
                continue
            intrinsic[c.component_id] = float(model.paths_seconds(c.paths))
            if callable(prepare):
                entry_costs[c.component_id] = prepare(c.paths[0], cancelled=lambda: False)
    result, cursor, current_color = [], None, None
    for phase in strokes.PHASES:
        pending = sorted((c for c in components if c.phase == phase and c.paths),
                         key=lambda c: (-priority(c), c.component_id))
        if pending and model is not None:
            current_color = None
        while pending:
            best, best_cost = 0, float('inf')
            for index, component in enumerate(pending[:72]):
                start = component.paths[0][0] if component.paths[0] else component.bbox[:2]
                if model is None:
                    travel = 0.0 if cursor is None else math.hypot(start[0] - cursor[0], start[1] - cursor[1])
                    penalty = 0.0 if current_color in (None, component.color_index) else 18.0
                    credit = min(30.0, priority(component) * .025)
                    value = travel + penalty - credit + index * 1e-6
                else:
                    seconds = intrinsic[component.component_id]
                    if cursor is not None and component.paths[0]:
                        first = component.paths[0]
                        prepared = entry_costs.get(component.component_id)
                        if prepared is None:
                            moved = float(model.path_seconds(first, cursor=cursor))
                            base = float(model.path_seconds(first, cursor=None))
                        else:
                            moved, base = prepared.seconds(cursor=cursor), prepared.seconds()
                        seconds += max(0.0, moved - base)
                    if current_color != component.color_index:
                        seconds += sum(model.color_selection_cost(component.color_index))
                    value = (seconds / max(.001, float(priority(component)))) + index * 1e-9
                if value < best_cost:
                    best, best_cost = index, value
            chosen = pending.pop(best)
            result.append(chosen)
            for path in chosen.paths:
                if path:
                    cursor = path[-1]
            current_color = chosen.color_index
    return result


class LoggedModel:
    def __init__(self, model, *, prepared=True):
        self.model, self.calls = model, []
        self.options, self.model_version = model.options, model.model_version
        if not prepared:
            self.prepare_path_cost = None

    def paths_seconds(self, paths):
        self.calls.append(('paths', tuple(paths)))
        return self.model.paths_seconds(paths)

    def path_seconds(self, path, *, cursor):
        self.calls.append(('path', path, cursor))
        return self.model.path_seconds(path, cursor=cursor)

    def prepare_path_cost(self, path, *, cancelled):
        self.calls.append(('prepare', path))
        prepared = self.model.prepare_path_cost(path, cancelled=cancelled)
        calls = self.calls
        class Entry:
            def seconds(self, *, cursor=None):
                calls.append(('entry', path, cursor))
                return prepared.seconds(cursor=cursor)
        return Entry()

    def color_selection_cost(self, index):
        self.calls.append(('color', index))
        return self.model.color_selection_cost(index)

    def sequence_cost(self, *args, **kwargs):
        return self.model.sequence_cost(*args, **kwargs)

    def as_dict(self):
        return self.model.as_dict()


@contextmanager
def observed_queue_work(module=strokes):
    """Count actual list-pop shifts outside any timing/traced measurement.

    The sorted pending list is instrumented directly. A C-call profile observes
    the literal active list's real pop with the selected best_i; it does not
    replace selection or infer a faster result from a hypothetical algorithm.
    """
    if sys.getprofile() is not None:
        raise RuntimeError('Queue work observation requires an unowned profiler.')
    work = dict(phase_lists=0, initial_components=0, pending_pops=0,
                pending_reference_shifts=0, active_pops=0, active_reference_shifts=0,
                maximum_active_size=0, maximum_selected_index=0)
    refs = []
    class Pending(list):
        def pop(self, index=-1):
            actual_index = index if index >= 0 else len(self) + index
            work['pending_pops'] += 1
            work['pending_reference_shifts'] += len(self) - actual_index - 1
            work['maximum_selected_index'] = max(work['maximum_selected_index'], actual_index if index >= 0 else 0)
            return super().pop(index)
    def sorted_pending(*args, **kwargs):
        values = builtins.sorted(*args, **kwargs)
        if sys._getframe(1).f_code.co_name != 'schedule_components':
            return values
        pending = Pending(values)
        refs.append(weakref.ref(pending))
        work['phase_lists'] += 1
        work['initial_components'] += len(pending)
        return pending
    def observe(frame, event, argument):
        if (event == 'c_call' and frame.f_code.co_name == 'schedule_components'
                and getattr(argument, '__name__', '') == 'pop'):
            active = frame.f_locals.get('window')
            if active is not None and getattr(argument, '__self__', None) is active:
                index = frame.f_locals['best_i']
                work['active_pops'] += 1
                work['active_reference_shifts'] += len(active) - index - 1
                work['maximum_active_size'] = max(work['maximum_active_size'], len(active))
                work['maximum_selected_index'] = max(work['maximum_selected_index'], index)
    with patch.object(module, 'sorted', new=sorted_pending, create=True):
        sys.setprofile(observe)
        try:
            yield work, refs
        finally:
            sys.setprofile(None)


def checker_source(size=(64, 64), *, margin=0):
    yy, xx = np.indices((size[1], size[0]))
    data = np.full((size[1], size[0], 3), 255, np.uint8)
    active = ((xx + yy) % 2 == 0)
    if margin:
        active &= (xx >= margin) & (xx < size[0] - margin) & (yy >= margin) & (yy < size[1] - margin)
    data[active] = 0
    return Image.fromarray(data)


def public_options(**changes):
    result = pixel_options(brush=1)
    result.update(cpu_workers='1', cpu_workers_resolved=1, cpu_engine='Threads',
        ram_budget_mb=512, logical_cpus=4, available_ram_mb=8192, resource_scheduler='Off',
        detail_zoom='Off', skip_white=True)
    result.update(changes)
    return result


class ComponentQueueTests(unittest.TestCase):
    def assert_order(self, components, model=None):
        original = copy.deepcopy(components)
        expected = legacy_component_order(components, model)
        groups, sequence, meta = strokes.schedule_components(components, 4, cost_model=model)
        self.assertEqual([(entry['component_id'], entry['path']) for entry in sequence],
                         [(c.component_id, tuple(path)) for c in expected for path in c.paths])
        self.assertEqual(groups, [[path for c in expected if c.color_index == color for path in c.paths]
                                  for color in range(4)])
        self.assertEqual(meta['scheduled_paths'], len(sequence))
        self.assertEqual(meta['phase_component_counts'],
                         {phase: sum(c.phase == phase for c in expected) for phase in strokes.PHASES})
        self.assertEqual(meta['phase_path_counts'],
                         {phase: sum(len(c.paths) for c in expected if c.phase == phase) for phase in strokes.PHASES})
        self.assertEqual([entry['serial'] for entry in sequence], list(range(len(sequence))))
        self.assertEqual(components, original)
        return sequence

    def test_legacy_order_at_empty_short_exact_window_and_replenishment_boundaries(self):
        for count in (0, 1, 2, 71, 72, 73, 143, 144, 145, 389):
            for single_phase in (False, True):
                with self.subTest(count=count, single_phase=single_phase):
                    self.assert_order(components_fixture(count, single_phase=single_phase))

    def test_same_stable_sort_order_survives_equal_keys_and_unscored_components(self):
        components = [strokes.Component(0, 0, area=1, importance_mean=.5,
            bbox=(0, 0, 1, 1), phase='fine_detail', paths=[((0, 0), (index, 0))])
            for index in range(160)]
        components.insert(40, strokes.Component(500, 2, phase='fill', paths=[]))
        components.insert(80, strokes.Component(501, 3, phase='unknown', paths=[((9, 9),)]))
        self.assert_order(components)

    def test_cost_callback_order_and_every_native_pricing_variant_remain_exact(self):
        components = components_fixture(151, single_phase=True)
        for prepared in (False, True):
            for calibration in ({}, {'samples': 5, 'ratio': 1.7,
                    'operation_runtime': {'dot': {'average_seconds': .05},
                                          'short_stroke': {'average_seconds': .2}}}):
                for precision, scale in (('Normal', (1, 1)), ('Ultra', (.55, 2.1))):
                    with self.subTest(prepared=prepared, calibration=bool(calibration), precision=precision):
                        model = costs.ExecutionCostModel(dict(precision=precision, brush_px=3,
                            _execution_scale_x=scale[0], _execution_scale_y=scale[1],
                            _execution_cost_calibration_override=calibration), (100, 100), (100, 100))
                        before, after = LoggedModel(model, prepared=prepared), LoggedModel(model, prepared=prepared)
                        expected = legacy_component_order(components, before)
                        groups, sequence, meta = strokes.schedule_components(components, 4, cost_model=after)
                        self.assertEqual(after.calls, before.calls)
                        self.assertEqual([(entry['component_id'], entry['path']) for entry in sequence],
                            [(c.component_id, tuple(path)) for c in expected for path in c.paths])
                        self.assertEqual(meta['estimated_execution_seconds'], round(model.sequence_cost(
                            sequence, initial_brush=3, include_color_verification=True).total_seconds, 4))

    def test_all_equal_nonfinite_candidate_costs_still_choose_first_pending(self):
        components = components_fixture(146, single_phase=True)
        model = costs.ExecutionCostModel({'_execution_cost_calibration_override': {}}, (100, 100), (100, 100))
        with patch.object(model, 'paths_seconds', return_value=float('inf')):
            sequence = self.assert_order(components, model)
        self.assertEqual([entry['component_id'] for entry in sequence if entry['path']],
                         [c.component_id for c in sorted(components, key=lambda c: (-priority(c), c.component_id))])

    def test_real_public_pixel_caller_moves_only_bounded_candidate_references(self):
        with calibrated(PALETTE), closing(checker_source()) as source:
            original = source.tobytes()
            with observed_queue_work() as (work, refs):
                plan = DrawBot.make_plan(source, source.size, public_options())
            try:
                self.assertEqual(plan['options']['pixel_stroke_meta']['component_count'], 2048)
                self.assertEqual(work['initial_components'], 2048)
                self.assertEqual(work['pending_reference_shifts'], 0)
                self.assertEqual(work['pending_pops'], 2048)
                self.assertEqual(work['active_pops'], 2048)
                self.assertEqual(work['maximum_active_size'], 72)
                self.assertLessEqual(work['active_reference_shifts'], 71 * 2048)
                self.assertLessEqual(work['maximum_selected_index'], 71)
                self.assertTrue(all(ref() is None for ref in refs))
                self.assertEqual(source.tobytes(), original)
            finally:
                close_plan(plan, source)

    def test_actual_public_plan_and_native_palette_delivery_keep_every_preview_pixel(self):
        positions = [(-400 + 10 * index, -100) for index in range(len(PALETTE))]
        for policy, workers in (('Off', 1), ('Auto', 2)):
            with self.subTest(policy=policy, workers=workers), ExitStack() as stack:
                stack.enter_context(calibrated(PALETTE))
                source = stack.enter_context(closing(checker_source((40, 32), margin=4)))
                surface = stack.enter_context(closing(Image.new('RGB', source.size, 'white')))
                settings = public_options(adaptive_hybrid_cost=policy, cpu_workers=str(workers),
                    cpu_workers_resolved=workers, strict_color_verification=True,
                    adaptive_color_verification=True, visual_verification_enabled=False,
                    visual_verification_resolved='Off')
                plan = DrawBot.make_plan(source, source.size, settings)
                stack.callback(close_plan, plan, source)
                mouse = PaletteInkMouse(surface, positions, PALETTE, 1)
                stack.callback(mouse.close)
                stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
                for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                             'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                             'CorrectionHistory.record_correction_history'):
                    stack.enter_context(patch(name, return_value={}))
                original = copy.deepcopy(plan['execution_sequence'])
                DrawBot.execute_plan(plan, (*ORIGIN, *source.size), positions, mouse, NoWait(),
                                     threading.Event(), mouse.report, clock=lambda: 0)
                self.assertEqual(surface.tobytes(), plan['preview'].tobytes())
                self.assertEqual(surface.tobytes(), source.tobytes())
                self.assertEqual(plan['execution_sequence'], original)
                self.assertFalse(mouse.held)
                self.assertEqual(plan['options']['runtime_path_counts']['sent'], plan['count'])
                self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)

    def test_stop_during_preparation_selection_and_final_cost_leaves_inputs_reusable(self):
        components = components_fixture(150, single_phase=True)
        original = copy.deepcopy(components)
        model = costs.ExecutionCostModel({'_execution_cost_calibration_override': {}}, (100, 100), (100, 100))
        for stop_after in (1, 70, 150 * 2 + 5):
            count = 0
            def cancelled():
                nonlocal count
                count += 1
                return count >= stop_after
            with self.subTest(stop_after=stop_after), self.assertRaises(InterruptedError):
                strokes.schedule_components(components, 4, cost_model=model, cancelled=cancelled)
            self.assertEqual(components, original)
        with patch.object(model, 'sequence_cost', side_effect=InterruptedError), self.assertRaises(InterruptedError):
            strokes.schedule_components(components, 4, cost_model=model)
        self.assert_order(components, model)

    def test_failed_final_diagnostics_preserve_geometry_and_exact_legacy_fallback_sum(self):
        components = components_fixture(85)
        model = costs.ExecutionCostModel({'_execution_cost_calibration_override': {}}, (100, 100), (100, 100))
        expected = strokes.schedule_components(components, 4, cost_model=model)
        with patch.object(model, 'sequence_cost', side_effect=ValueError('diagnostic failure')):
            actual = strokes.schedule_components(components, 4, cost_model=model)
        self.assertEqual(actual[:2], expected[:2])
        reference = sum(float(model.paths_seconds(c.paths)) for c in components if c.paths)
        self.assertEqual(actual[2]['estimated_execution_seconds'], round(reference, 4))
        self.assertEqual({key: value for key, value in actual[2].items() if key != 'estimated_execution_seconds'},
                         {key: value for key, value in expected[2].items() if key != 'estimated_execution_seconds'})


if __name__ == '__main__':
    unittest.main()
