"""Typed timing history must compare against the same kinds of real paths."""
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import DrawBot
import DrawTimeEstimate as eta
from ExecutionCostModel import ExecutionCostModel, build_cost_model
from test_v148_rendering_batch07_transparency import standard_options
from test_v148_rendering_batch06_canvas import close_plan


class TypedEtaTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.stack.enter_context(patch('DrawBot.log_event'))
        with Image.open(Path(__file__).with_name('assets') / 'paint-tools-reference.png') as asset:
            self.source = asset.convert('RGBA')
        self.stack.callback(self.source.close)
        options = standard_options(profile_key='microsoft-paint', profile_name='Microsoft Paint',
            paint_profile=True, time_budget_mode='Custom', manual_max_seconds=120, max_seconds=120,
            unlimited_time=False, adaptive_deadline_renderer=True, deadline_safety_reserve='Off',
            _execution_cost_calibration_override={})
        self.plan = DrawBot.make_plan(self.source, self.source.size, options)
        self.stack.callback(close_plan, self.plan, self.source)
        self.sequence = self.plan['execution_sequence']
        self.model = build_cost_model(dict(self.plan['options'], _execution_cost_calibration_override={}),
                                      self.plan['image'].size, self.plan['fitted'])

    def cold_types(self):
        # Public path costs supply each exact cursor/brush-dependent baseline.
        # The aggregate must compare like operation types, rather than assign
        # a long-stroke/dot global average to every type of runtime observation.
        values = defaultdict(list)
        cursor = None
        for row in self.sequence:
            path = row.get('path')
            if path:
                key = row.get('operation_type') or ('dot' if len(path) <= 1 else 'stroke')
                values[key].append(self.model.path_cost(path, cursor=cursor,
                                                        brush_px=row.get('brush_px')).total_seconds)
                cursor = path[-1]
        self.assertTrue({'dot', 'short_stroke', 'long_stroke', 'outline'} <= values.keys())
        self.assertGreater(sum(values['long_stroke']) / len(values['long_stroke']),
                           sum(values['dot']) / len(values['dot']) * 5)
        return values

    def test_partial_history_matching_each_exact_cold_type_has_unit_ratio(self):
        values = self.cold_types()
        _seconds, metadata = eta._sequence_operation_estimate(self.plan)
        for kind, costs in values.items():
            with self.subTest(kind=kind):
                average = sum(costs) / len(costs)
                self.assertAlmostEqual(metadata['operation_model_average_seconds'][kind], average, places=7)
                calibration = {'samples': 8, 'ratio': 1., 'mape': 0., 'operation_runtime': {
                    kind: {'average_seconds': average, 'samples': 8}}}
                adjustment = eta._operation_calibration_adjustment(calibration, metadata)
                self.assertTrue(adjustment['used'])
                self.assertEqual(adjustment['matched_operations'], len(costs))
                self.assertAlmostEqual(adjustment['raw_ratio'], 1., places=5)
                self.assertAlmostEqual(adjustment['applied_ratio'], 1., places=5)

    def test_changed_dot_history_covers_only_its_actual_modeled_time(self):
        values = self.cold_types()
        average = sum(values['dot']) / len(values['dot'])
        calibration = {'samples': 8, 'ratio': 1., 'mape': 0., 'operation_runtime': {
            'dot': {'average_seconds': average * 2, 'samples': 8}}}
        _seconds, metadata = eta._sequence_operation_estimate(self.plan)
        adjustment = eta._operation_calibration_adjustment(calibration, metadata)
        total = metadata['modeled_operation_seconds']
        self.assertAlmostEqual(adjustment['raw_ratio'], 2., places=5)
        self.assertAlmostEqual(adjustment['modeled_matched_seconds'], sum(values['dot']), places=4)
        self.assertAlmostEqual(adjustment['coverage_percent'], 100 * sum(values['dot']) / total, places=2)
        with patch.object(eta, '_local_calibration', return_value=calibration):
            visible = eta.estimate_from_plan(self.plan)
        self.assertEqual(visible['operation_calibration'], adjustment)
        self.assertGreater(visible['projected_seconds'], 0)

    def test_preview_scope_transfers_typed_totals_without_repricing_paths(self):
        path_cost = ExecutionCostModel.path_cost
        sequence_cost = ExecutionCostModel.sequence_cost
        path_calls, sequence_calls = [], []

        def path(model, points, **kwargs):
            path_calls.append(points)
            return path_cost(model, points, **kwargs)

        def sequence(model, rows, **kwargs):
            sequence_calls.append(len(rows))
            return sequence_cost(model, rows, **kwargs)

        before = self.source.tobytes()
        with patch.object(ExecutionCostModel, 'path_cost', new=path), \
                patch.object(ExecutionCostModel, 'sequence_cost', new=sequence), eta.preview_estimate_scope():
            first = eta.attach_draw_time_estimate(self.plan)
            first_calls = len(path_calls)
            second = eta.attach_preview_draw_time_estimate(self.plan)
        self.assertEqual(first_calls, sum(bool(row.get('path')) for row in self.sequence))
        self.assertEqual(len(path_calls), first_calls)
        self.assertEqual(sequence_calls, [len(self.sequence)])
        self.assertEqual(first, second)
        self.assertEqual(second, eta.estimate_from_plan(self.plan))
        self.assertEqual(self.source.tobytes(), before)

    def test_legacy_and_keyword_ignoring_cost_models_keep_the_previous_fallback(self):
        model = self.model
        dots = self.cold_types()['dot']

        class LegacyModel:
            def __getattr__(self, name):
                return getattr(model, name)

            def sequence_cost(self, rows, *, initial_brush, include_color_verification):
                return model.sequence_cost(rows, initial_brush=initial_brush,
                                           include_color_verification=include_color_verification)

        class KeywordIgnoringModel(LegacyModel):
            def sequence_cost(self, rows, **kwargs):
                kwargs.pop('path_cost_totals', None)
                return super().sequence_cost(rows, **kwargs)

        class PositionalCollectorModel(LegacyModel):
            def sequence_cost(self, rows, *path_cost_totals, initial_brush, include_color_verification):
                return super().sequence_cost(rows, initial_brush=initial_brush,
                                             include_color_verification=include_color_verification)

        class PartialModel(LegacyModel):
            def sequence_cost(self, rows, **kwargs):
                totals = kwargs.pop('path_cost_totals', None)
                if totals is not None:
                    totals['dot'] = (len(dots), sum(dots))
                return super().sequence_cost(rows, **kwargs)

        class InvalidOptionalModel(LegacyModel):
            def sequence_cost(self, rows, **kwargs):
                totals = kwargs.pop('path_cost_totals', None)
                if totals is not None:
                    totals['dot'] = None
                return super().sequence_cost(rows, **kwargs)

        for supplied in (LegacyModel(), KeywordIgnoringModel(), PositionalCollectorModel(),
                         PartialModel(), InvalidOptionalModel()):
            with self.subTest(model=type(supplied).__name__), \
                    patch('ExecutionCostModel.build_cost_model', return_value=supplied):
                seconds, metadata = eta._sequence_operation_estimate(self.plan)
            means = metadata['operation_model_average_seconds']
            self.assertTrue(metadata['used'])
            self.assertGreater(seconds, 0)
            self.assertEqual(len({means[kind] for kind in ('dot', 'short_stroke', 'long_stroke', 'outline')}), 1)

    def test_optional_accumulation_preserves_costs_and_stop_between_real_paths(self):
        expected = self.model.sequence_cost(self.sequence, initial_brush=1, include_color_verification=True)
        totals = {}
        actual = self.model.sequence_cost(self.sequence, initial_brush=1, include_color_verification=True,
                                          path_cost_totals=totals)
        self.assertEqual(actual, expected)
        self.assertEqual(sum(value[0] for value in totals.values()),
                         sum(bool(row.get('path')) for row in self.sequence))
        stopped = threading.Event()
        path_cost = self.model.path_cost
        calls = []

        def path(points, **kwargs):
            value = path_cost(points, **kwargs)
            calls.append(points)
            stopped.set()
            return value

        partial = {}
        with patch.object(self.model, 'path_cost', new=path), self.assertRaises(InterruptedError):
            self.model.sequence_cost(self.sequence, cancelled=stopped.is_set, path_cost_totals=partial)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(value[0] for value in partial.values()), 1)


if __name__ == '__main__':
    unittest.main()
