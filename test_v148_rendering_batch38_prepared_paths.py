"""Extra Fast reuses exact path costs while keeping its existing selection.

All source pixels come from existing PNG assets. Numerical ink masks only
replay the real plans; these tests do not create new source images.
"""
from contextlib import closing, contextmanager
import copy
from pathlib import Path
import traceback
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import Colors
import ExecutionCostModel as costs
import ExtraFast2 as fast
from ContinuousPaths import build_execution_paths
from PixelData import build_strokes, closest_color
from PreviewSafety import build_preview_safety_plan


ROOT = Path(__file__).resolve().parent
EVIDENCE = []


@contextmanager
def asset_image(name='assets/paint-tools-reference.png', longest=None):
    with closing(Image.open(ROOT / name)) as opened, closing(opened.convert('RGBA')) as image:
        if longest is not None:
            image.thumbnail((longest, longest))
        yield image


def options(**changes):
    settings = dict(profile_key='gartic-phone', brush_px=1, speed='Balanced',
        stroke_optimizer='Travel only', drawing_mode='Smart paths (recommended)',
        delay=.01, precision='High', _hybrid_scale_x=1., _hybrid_scale_y=1.,
        _execution_cost_calibration_override={})
    settings.update(changes)
    return settings


def public_options(**changes):
    settings = dict(render_preset='Extra fast', drawing_style='Line Art',
        profile_name='Microsoft Paint', profile_key='microsoft-paint',
        fill_tool_available=False, detail=8, delay=.01, speed='Fast', precision='High',
        lines=True, skip_white=True, contrast=1., outline=False, paint_current_color=False,
        brush_px=1, time_budget_mode='Unlimited', unlimited_time=True, max_seconds=80,
        gpu_mode='CPU', planning_resolution='Standard', custom_color_workflow='Calibrated palette',
        exact_color_available=False, color_rendering='Perceptual match', color_fidelity='Faithful',
        detail_zoom='Off', adaptive_detail='Off', preview_plan=True, edge_behavior='Hard Clip',
        _execution_cost_calibration_override={})
    settings.update(changes)
    return settings


def raster(paths, size):
    """Independent inclusive-axis membership for real planned strokes."""
    width, height = map(int, size)
    covered = np.zeros((height, width), dtype=bool)
    for path in paths:
        if not path:
            continue
        pairs = zip(path, path[1:]) if len(path) > 1 else ((path[0], path[0]),)
        for start, end in pairs:
            ax, ay = map(int, start)
            bx, by = map(int, end)
            assert ax == bx or ay == by
            assert 0 <= ax < width and 0 <= bx < width and 0 <= ay < height and 0 <= by < height
            covered[min(ay, by):max(ay, by) + 1, min(ax, bx):max(ax, bx) + 1] = True
    return covered


def close_plan(plan, original):
    values = (*plan.values(), *plan.get('options', {}).values(),
              *plan.get('ui_previews', {}).values())
    for value in values:
        if isinstance(value, Image.Image) and value is not original:
            value.close()


def plan_snapshot(plan, area):
    result = {key: copy.deepcopy(plan[key]) for key in (
        'groups', 'execution_groups', 'execution_sequence', 'colors', 'fitted',
        'estimate', 'path_stats', 'count', 'source_count')}
    result['extra_fast_meta'] = copy.deepcopy(plan['options']['extra_fast_v2_meta'])
    result['image'] = (plan['image'].mode, plan['image'].size, plan['image'].tobytes())
    result['preview'] = (plan['preview'].mode, plan['preview'].size, plan['preview'].tobytes())
    safety = build_preview_safety_plan(plan['image'].size, plan['fitted'], plan['groups'],
        plan['execution_groups'], plan['options'],
        execution_sequence=plan['execution_sequence'] or None)
    result['final_ink'] = [raster(paths, area).tobytes() for paths in safety.groups]
    return result


class PreparedExtraFastTests(unittest.TestCase):
    def setUp(self):
        self.previous_colors = list(Colors.allColors)
        Colors.reset_palette()

    def tearDown(self):
        Colors.allColors[:] = self.previous_colors
        closest_color.cache_clear()

    def view_class(self):
        result = getattr(fast, '_PreparedPathCosts', None)
        self.assertIsNotNone(result, 'Extra Fast has no operation-local prepared-cost owner.')
        return result

    def assert_closed(self, view):
        self.assertEqual(view._costs, {})
        self.assertEqual(view._points, 0)
        self.assertFalse(view._enabled)
        self.assertIsNone(view._model)
        self.assertIsNone(view._cancelled)

    def reference(self, groups, settings, prefix=None):
        with patch.object(costs.ExecutionCostModel, 'prepare_path_cost', None):
            return fast.build_fast_paths(groups, settings, portrait_edge_count=prefix)

    def test_public_plan_reuses_costs_with_exact_output_and_metadata(self):
        from DrawBot import make_plan
        real_cost = costs.ExecutionCostModel.path_cost
        cases = (('assets/paint-tools-reference.png', (320, 200), {}),
                 ('assets/image-draw-bot-icon.png', (200, 200),
                  dict(drawing_style='Logo / Flat Graphic', render_style='Standard / pixel',
                       paint_current_color=True)))
        for asset, area, changes in cases:
            with self.subTest(asset=asset), asset_image(asset) as image:
                before_bytes = image.tobytes()
                settings = public_options(**changes, _target_screen_area=(-121, 41, *area))
                calls = []
                def observe(model, *args, **kwargs):
                    calls.append(1)
                    return real_cost(model, *args, **kwargs)
                with patch.object(costs.ExecutionCostModel, 'path_cost', observe):
                    with patch.object(costs.ExecutionCostModel, 'prepare_path_cost', None):
                        reference = make_plan(image, area, settings)
                    try:
                        expected = plan_snapshot(reference, area)
                    finally:
                        close_plan(reference, image)
                    old_count = len(calls)
                    invocation_counts = []
                    for _ in range(2):
                        calls.clear()
                        actual = make_plan(image, area, settings)
                        try:
                            self.assertEqual(plan_snapshot(actual, area), expected)
                        finally:
                            close_plan(actual, image)
                        invocation_counts.append(len(calls))
                EVIDENCE.append(dict(case='public', asset=asset, old_path_cost_calls=old_count,
                                     prepared_path_cost_calls=invocation_counts))
                self.assertEqual(invocation_counts[0], invocation_counts[1])
                self.assertLess(invocation_counts[0], old_count)
                self.assertEqual(image.tobytes(), before_bytes)

    def test_actual_groups_keep_legacy_winner_across_modes_and_calibration(self):
        changes = (({}, None), ({'profile_key':'microsoft-paint'}, None),
            ({'_hybrid_scale_x':2., '_hybrid_scale_y':1.5, 'brush_px':4}, None),
            ({'target_stroke_count_resolved':50}, None), ({}, 5),
            ({'time_budget_active':True}, None), ({'color_workflow':'Progressive passes'}, None),
            ({'extra_fast_travel_optimizer':'Off'}, None),
            ({'_execution_cost_calibration_override':{'samples':5, 'ratio':1.7,
                'operation_runtime':{'short_stroke':{'average_seconds':.12},
                                     'long_stroke':{'average_seconds':.45}}}}, None))
        with asset_image('assets/image-draw-bot-app-screenshot.png', 96) as image:
            groups = build_strokes(image, True, True)
            unchanged = copy.deepcopy(groups)
            for change, prefix in changes:
                with self.subTest(change=change, prefix=prefix):
                    settings = options(**change)
                    expected = self.reference(groups, settings, prefix)
                    with patch.object(fast, '_vertical_alternative', wraps=fast._vertical_alternative) as old_search:
                        actual = fast.build_fast_paths(groups, settings, portrait_edge_count=prefix)
                    self.assertEqual(actual, expected)
                    self.assertEqual(old_search.call_count, len(groups))
                    for source, paths in zip(groups, actual[0]):
                        source_paths = [((ax, ay), (bx, by)) for ax, ay, bx, by in source]
                        np.testing.assert_array_equal(raster(paths, image.size), raster(source_paths, image.size))
                    self.assertEqual(groups, unchanged)

    def test_entry_and_point_budgets_use_real_uncached_fallback(self):
        view_type = self.view_class()
        real_prepare = costs.ExecutionCostModel.prepare_path_cost
        real_cost = costs.ExecutionCostModel.path_cost
        with asset_image() as image:
            groups = build_strokes(image, True, True)
            expected = self.reference(groups, options())
            for entries, points in ((3, 65536), (4096, 64), (0, 0)):
                with self.subTest(entries=entries, points=points):
                    views, preparations, prices = [], [], []
                    def create(model, cancelled):
                        view = view_type(model, cancelled)
                        views.append(view)
                        return view
                    def prepare(model, path, **kwargs):
                        preparations.append(tuple(path))
                        self.assertLessEqual(len(preparations), entries)
                        self.assertLessEqual(sum(map(len, preparations)), points)
                        return real_prepare(model, path, **kwargs)
                    def price(model, *args, **kwargs):
                        prices.append(1)
                        return real_cost(model, *args, **kwargs)
                    with patch.object(fast, '_PreparedPathCosts', create), \
                         patch.object(fast, '_MAX_PREPARED_PATH_COSTS', entries), \
                         patch.object(fast, '_MAX_PREPARED_PATH_POINTS', points), \
                         patch.object(costs.ExecutionCostModel, 'prepare_path_cost', prepare), \
                         patch.object(costs.ExecutionCostModel, 'path_cost', price):
                        self.assertEqual(fast.build_fast_paths(groups, options()), expected)
                    self.assertEqual(len(views), 1)
                    self.assertGreater(len(prices), len(preparations))
                    if entries:
                        self.assertGreater(len(preparations), 0)
                    self.assert_closed(views[0])

    def test_cache_allocation_oom_releases_storage_and_preserves_the_plan(self):
        view_type = self.view_class()
        real_prepare = costs.ExecutionCostModel.prepare_path_cost
        real_cost = costs.ExecutionCostModel.path_cost
        with asset_image() as image:
            groups = build_strokes(image, True, True)
            expected = self.reference(groups, options())
            for stage in ('construction', 'preparation', 'insertion'):
                with self.subTest(stage=stage):
                    views, injected, preparations, fallback = [], [], [], []
                    class FailingInsert(dict):
                        def __setitem__(self, key, value):
                            if len(self) == 2:
                                injected.append(stage)
                                raise MemoryError('controlled cache insertion exhaustion')
                            return super().__setitem__(key, value)
                    def create(model, cancelled):
                        if stage == 'construction':
                            injected.append(stage)
                            raise MemoryError('controlled cache construction exhaustion')
                        view = view_type(model, cancelled)
                        views.append(view)
                        if stage == 'insertion':
                            view._costs = FailingInsert()
                        return view
                    def prepare(model, path, **kwargs):
                        preparations.append(tuple(path))
                        if stage == 'preparation' and len(preparations) == 3:
                            injected.append(stage)
                            raise MemoryError('controlled prepared-cost exhaustion')
                        return real_prepare(model, path, **kwargs)
                    def price(model, *args, **kwargs):
                        if injected:
                            fallback.append(1)
                            for view in views:
                                self.assertEqual(view._costs, {})
                                self.assertEqual(view._points, 0)
                                self.assertFalse(view._enabled)
                        return real_cost(model, *args, **kwargs)
                    with patch.object(fast, '_PreparedPathCosts', create), \
                         patch.object(costs.ExecutionCostModel, 'prepare_path_cost', prepare), \
                         patch.object(costs.ExecutionCostModel, 'path_cost', price):
                        self.assertEqual(fast.build_fast_paths(groups, options()), expected)
                    self.assertEqual(injected, [stage])
                    self.assertGreater(len(fallback), 0)
                    for view in views:
                        self.assert_closed(view)

    def test_stop_and_retained_failure_release_cache_and_allow_retry(self):
        view_type = self.view_class()
        real_prepare = costs.ExecutionCostModel.prepare_path_cost
        with asset_image() as image:
            groups = build_strokes(image, True, True)
            unchanged = copy.deepcopy(groups)
            expected = self.reference(groups, options())
            for fail in (False, True):
                with self.subTest(ordinary_failure=fail):
                    views, prepared, stopped = [], [], [False]
                    primary = RuntimeError('controlled actual preparation failure')
                    def create(model, cancelled):
                        view = view_type(model, cancelled)
                        views.append(view)
                        return view
                    def prepare(model, path, **kwargs):
                        value = real_prepare(model, path, **kwargs)
                        prepared.append(tuple(path))
                        if len(prepared) == 3:
                            if fail:
                                raise primary
                            stopped[0] = True
                        return value
                    retained = None
                    with patch.object(fast, '_PreparedPathCosts', create), \
                         patch.object(costs.ExecutionCostModel, 'prepare_path_cost', prepare):
                        try:
                            fast.build_fast_paths(groups, options(), cancelled=lambda: stopped[0])
                        except (RuntimeError, InterruptedError) as error:
                            retained = error
                    self.assertIsNotNone(retained)
                    if fail:
                        self.assertIs(retained, primary)
                        self.assertIn('prepare', [frame.name for frame in traceback.extract_tb(retained.__traceback__)])
                    else:
                        self.assertIsInstance(retained, InterruptedError)
                    self.assertEqual(len(prepared), 3)
                    self.assertEqual(len(views), 1)
                    self.assert_closed(views[0])
                    self.assertEqual(groups, unchanged)
                    self.assertEqual(fast.build_fast_paths(groups, options()), expected)
                    self.assertIsNotNone(retained.__traceback__)

    def test_oom_fallback_honors_stop_and_propagates_actual_pricing_failure(self):
        view_type = self.view_class()
        real_prepare = costs.ExecutionCostModel.prepare_path_cost
        real_cost = costs.ExecutionCostModel.path_cost
        with asset_image() as image:
            groups = build_strokes(image, True, True)
            for stop in (False, True):
                with self.subTest(stop=stop):
                    views, prepared, exhausted, fallback = [], [], [False], []
                    primary = ValueError('controlled ordinary model pricing failure')
                    def create(model, cancelled):
                        view = view_type(model, cancelled)
                        views.append(view)
                        return view
                    def prepare(model, path, **kwargs):
                        prepared.append(tuple(path))
                        if len(prepared) == 3:
                            exhausted[0] = True
                            raise MemoryError('controlled optional preparation exhaustion')
                        return real_prepare(model, path, **kwargs)
                    def price(model, *args, **kwargs):
                        if exhausted[0]:
                            fallback.append(1)
                            raise primary
                        return real_cost(model, *args, **kwargs)
                    retained = None
                    with patch.object(fast, '_PreparedPathCosts', create), \
                         patch.object(costs.ExecutionCostModel, 'prepare_path_cost', prepare), \
                         patch.object(costs.ExecutionCostModel, 'path_cost', price):
                        try:
                            fast.build_fast_paths(groups, options(), cancelled=lambda: stop and exhausted[0])
                        except (ValueError, InterruptedError) as error:
                            retained = error
                    if stop:
                        self.assertIsInstance(retained, InterruptedError)
                        self.assertEqual(fallback, [])
                    else:
                        self.assertIs(retained, primary)
                        self.assertEqual(fallback, [1])
                    self.assertEqual(len(views), 1)
                    self.assert_closed(views[0])

    def test_missing_prepare_and_initial_stop_keep_the_existing_model_path(self):
        with asset_image() as image:
            groups = build_strokes(image, True, True)
            expected = self.reference(groups, options())
            real_factory = costs.build_cost_model
            with patch.object(costs, 'build_cost_model', wraps=real_factory) as factory:
                with self.assertRaises(InterruptedError):
                    fast.build_fast_paths(groups, options(), cancelled=lambda: True)
            self.assertEqual(factory.call_count, 0)
            with patch.object(costs.ExecutionCostModel, 'prepare_path_cost', None):
                actual = fast.build_fast_paths(groups, options())
            self.assertEqual(actual, expected)

    def test_exact_direction_and_cursor_keys_reuse_real_prepared_costs(self):
        view_type = self.view_class()
        with asset_image() as image:
            groups = build_strokes(image, True, True)
            paths = build_execution_paths(groups, enabled=True)
            path = next(path for group in paths for path in group if len(path) > 3 and path[0] != path[-1])
            for calibration in ({}, {'samples':5, 'ratio':1.7, 'operation_runtime':{
                    'short_stroke':{'average_seconds':.12}, 'long_stroke':{'average_seconds':.45}}}):
                with self.subTest(calibration=calibration):
                    model = costs.build_cost_model(options(_hybrid_scale_x=1.5, _hybrid_scale_y=.8,
                        _execution_cost_calibration_override=calibration), image.size, image.size)
                    view = view_type(model, lambda: False)
                    try:
                        with patch.object(model, 'prepare_path_cost', wraps=model.prepare_path_cost) as prepare:
                            for _ in range(2):
                                for actual in (path, tuple(reversed(path))):
                                    for cursor in (None, path[0], path[-1]):
                                        self.assertEqual(view.path_seconds(actual, cursor=cursor),
                                                         model.path_seconds(actual, cursor=cursor))
                            self.assertEqual(prepare.call_count, 2)
                    finally:
                        view.close()
                    self.assert_closed(view)


if __name__ == '__main__':
    unittest.main()
