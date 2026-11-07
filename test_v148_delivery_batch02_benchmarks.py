import math
import tempfile
import tracemalloc
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import BenchmarkSuite as benchmark
import GoldenImageRegression as golden
import HybridBenchmark as hybrid
import HybridBenchmarkSuite as hybrid_suite


def tiny():
    return Image.new('RGB', (8, 6), 'white')


def good_plan(image, area, options, cancelled):
    return {'estimate': 1, 'count': 1, 'options': {'adaptive_accuracy_meta': {
        'visual_accuracy_percent': 95, 'perceptual_color_accuracy_percent': 95,
        'hue_accuracy_percent': 95, 'coverage_percent': 99},
        'preview_delta_e_meta': {'p95_delta_e_oklab': .1}, 'post_draw_correction_meta': {'safe': True}}}


class BenchmarkEvidenceBatch02Tests(unittest.TestCase):
    def test_golden_required_metrics_cannot_be_missing_nonfinite_or_out_of_range(self):
        case = golden.GOLDEN_CASES[-1]
        row = {'visual_accuracy_percent': 95, 'perceptual_color_accuracy_percent': 95,
               'hue_accuracy_percent': 95, 'coverage_percent': 99, 'p95_delta_e_oklab': .1,
               'estimated_draw_seconds': 1, 'usable_seconds': 50, 'correction_safe': True}
        self.assertTrue(golden._pass_fail(row, case)[0])
        for key in row:
            missing = dict(row); missing.pop(key)
            with self.subTest(key=key):self.assertFalse(golden._pass_fail(missing, case)[0])
        for value in (math.nan, math.inf, -1, 101, True):
            self.assertFalse(golden._pass_fail({**row, 'visual_accuracy_percent': value}, case)[0])
        self.assertFalse(golden._pass_fail({**row, 'correction_safe': 'false'}, case)[0])

    def test_unknown_estimates_and_empty_golden_suite_never_pass(self):
        case = replace(golden.GOLDEN_CASES[0], name='unknown-time-test', factory=tiny)
        with tempfile.TemporaryDirectory() as tmp:
            result = golden.run(lambda *args: {}, {}, cases=[case], directory=tmp, ensure_assets=False)
            self.assertIsNone(result['rows'][0]['estimated_draw_seconds'])
            self.assertFalse(result['passed'])
            self.assertIn('time n/a', golden.format_result(result))
            self.assertFalse(golden.run(good_plan, {}, cases=[], ensure_assets=False)['passed'])
        with patch.object(benchmark, 'CASES', (('tiny', tiny),)):
            result = benchmark.run(lambda *args: {}, {})
        self.assertEqual(result['fit_count'], 0)
        self.assertIsNone(result['rows'][0]['estimated_draw_seconds'])
        self.assertIn('UNKNOWN n/a', benchmark.format_result(result))
        with patch.object(hybrid, 'CASES', (('tiny', tiny),)):
            result = hybrid.run(lambda *args: {}, {})
        self.assertIsNone(result['cases'][0]['estimated_draw_delta_seconds'])

    def test_benchmark_invalid_quality_and_nonboolean_acceptance_are_unavailable(self):
        def planner(*args):
            return {'estimate': 1, 'options': {'adaptive_accuracy_meta': {'visual_accuracy_percent': math.nan},
                                             'auto_tuner_acceptance_meta': {'accepted': 'false'}}}
        with patch.object(benchmark, 'CASES', (('tiny', tiny),)):
            result = benchmark.run(planner, {})
        self.assertIsNone(result['average_visual_accuracy_percent'])
        self.assertIsNone(result['acceptance_pass_count'])
        self.assertNotIn('gate PASS', benchmark.format_result(result))

    def test_fixture_factory_runs_once_per_selected_case(self):
        calls = []; images = []
        def factory():
            calls.append(1); image = tiny(); images.append(image); return image
        case = replace(golden.GOLDEN_CASES[0], name='single-generated-test', factory=factory)
        with tempfile.TemporaryDirectory() as tmp:
            result = golden.ensure_local_golden_images(tmp, cases=[case])
            self.assertEqual(len(calls), 1)
            self.assertEqual((result['cases'][0]['width'], result['cases'][0]['height']), (8, 6))
            golden.ensure_local_golden_images(tmp, cases=[case])
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(list(Path(tmp).glob('*.png'))), 1)
        for image in images:
            with self.assertRaises(ValueError):image.getpixel((0, 0))

    def test_precancelled_golden_run_creates_no_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'must-not-exist'
            with self.assertRaises(InterruptedError):
                golden.run(good_plan, {}, directory=directory, cancelled=lambda: True)
            self.assertFalse(directory.exists())

    def test_benchmark_options_are_independent_for_every_case_and_engine(self):
        base = {'nested': {'seen': []}}; calls = []
        def planner(image, area, options, cancelled):
            self.assertEqual(options['nested']['seen'], [])
            options['nested']['seen'].append('mutated'); calls.append(1)
            return good_plan(image, area, options, cancelled)
        cases = (('first', tiny), ('second', tiny))
        with patch.object(benchmark, 'CASES', cases):benchmark.run(planner, base)
        with patch.object(hybrid, 'CASES', cases):hybrid.run(planner, base)
        golden_cases = [replace(golden.GOLDEN_CASES[0], name=name+'-isolation', factory=factory) for name, factory in cases]
        with tempfile.TemporaryDirectory() as tmp:
            golden.run(planner, base, cases=golden_cases, directory=tmp, ensure_assets=False)
        self.assertEqual(len(calls), 8)
        self.assertEqual(base, {'nested': {'seen': []}})

    def test_hybrid_comparison_cannot_mutate_the_other_engines_source(self):
        seen = []; inputs = []
        def planner(image, area, options, cancelled):
            seen.append(image.getpixel((0, 0))); inputs.append(image)
            image.putpixel((0, 0), (0, 0, 0))
            return good_plan(image, area, options, cancelled)
        with patch.object(hybrid, 'CASES', (('tiny', tiny),)):
            hybrid.run(planner, {})
        self.assertEqual(seen, [(255, 255, 255)]*2)
        for image in inputs:
            with self.assertRaises(ValueError):image.getpixel((0, 0))

    def test_last_planner_cancellation_propagates_and_owned_inputs_close(self):
        for suite in ('benchmark', 'golden', 'hybrid'):
            stop = [False]; inputs = []
            def planner(image, area, options, cancelled):
                inputs.append(image); stop[0] = True
                return good_plan(image, area, options, cancelled)
            with self.subTest(suite=suite), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(InterruptedError):
                    if suite == 'benchmark':
                        with patch.object(benchmark, 'CASES', (('tiny', tiny),)):
                            benchmark.run(planner, {}, cancelled=lambda: stop[0])
                    elif suite == 'hybrid':
                        with patch.object(hybrid, 'CASES', (('tiny', tiny),)):
                            hybrid.run(planner, {}, cancelled=lambda: stop[0])
                    else:
                        case = replace(golden.GOLDEN_CASES[0], name='cancelled-test', factory=tiny)
                        golden.run(planner, {}, cases=[case], directory=tmp, ensure_assets=False, cancelled=lambda: stop[0])
                self.assertEqual(len(inputs), 1)
                with self.assertRaises(ValueError):inputs[0].getpixel((0, 0))

    def test_planner_exception_closes_benchmark_input(self):
        inputs = []
        def planner(image, *args):
            inputs.append(image); raise RuntimeError('planner failed')
        with patch.object(benchmark, 'CASES', (('tiny', tiny),)):
            with self.assertRaises(RuntimeError):benchmark.run(planner, {})
        with self.assertRaises(ValueError):inputs[0].getpixel((0, 0))


class BenchmarkMeasurementBatch02Tests(unittest.TestCase):
    def test_failed_hybrid_quantization_releases_owned_trace(self):
        was_tracing = tracemalloc.is_tracing()
        with tiny() as image, patch.object(hybrid_suite, 'build_pixel_map', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):hybrid_suite._run_case('tiny', image)
        self.assertEqual(tracemalloc.is_tracing(), was_tracing)

    def test_existing_caller_trace_is_preserved_and_not_claimed_as_local_memory(self):
        owned = not tracemalloc.is_tracing()
        if owned:tracemalloc.start()
        try:
            previous_peak = tracemalloc.get_traced_memory()[1]
            with tiny() as image:
                row = hybrid._row(good_plan, image, (8, 6), {}, False, lambda: False)
            self.assertTrue(tracemalloc.is_tracing())
            self.assertIsNone(row['peak_python_memory_bytes'])
            value, elapsed, peak = hybrid_suite._measure(lambda: 'ok', lambda: False)
            self.assertEqual(value, 'ok'); self.assertIsNone(peak)
            self.assertGreaterEqual(tracemalloc.get_traced_memory()[1], previous_peak)
        finally:
            if owned:tracemalloc.stop()

    def test_fair_timing_includes_adaptive_preparation_and_both_quality_simulations(self):
        clock = [0.0]
        def stage(seconds, result):
            def run(*args, **kwargs):
                clock[0] += seconds; return result
            return run
        quality = {'pixel_accuracy_score': 100.}
        seq = [{'color_index': 0, 'path': ((1, 1), (2, 1))}]
        adaptive = {'execution_sequence': seq, 'metrics': quality, 'metadata': {}}
        cost = SimpleNamespace(total_seconds=1., palette_switches=0, brush_switches=0)
        model = SimpleNamespace(sequence_cost=lambda seq: cost, fixed_overhead=lambda **kw: cost)
        with tiny() as image, \
             patch.object(hybrid_suite, 'time', SimpleNamespace(perf_counter=lambda: clock[0])), \
             patch.object(hybrid_suite, 'build_pixel_map', side_effect=stage(2, object())), \
             patch.object(hybrid_suite, 'build_pixel_stroke_plan', side_effect=stage(3, {'execution_sequence': seq})), \
             patch.object(hybrid_suite, 'simulate_quantized_plan', side_effect=stage(1, (quality, None))), \
             patch.object(hybrid_suite, 'groups_from_pixel_map', side_effect=stage(1, [])), \
             patch.object(hybrid_suite, '_build_fill_regions', side_effect=stage(5, ([], {}))), \
             patch.object(hybrid_suite, 'pixel_map_from_groups', side_effect=stage(2, object())), \
             patch.object(hybrid_suite, 'build_adaptive_execution', side_effect=stage(7, adaptive)), \
             patch.object(hybrid_suite, 'build_cost_model', return_value=model):
            result = hybrid_suite._run_case('tiny', image)
        self.assertEqual(result['measurement']['common_preparation_ms'], 2000)
        self.assertEqual(result['baseline']['planning_ms'], 4000)
        self.assertEqual(result['adaptive']['planning_ms'], 15000)
        self.assertEqual(result['comparison']['planning_delta_ms'], 11000)

    def test_suite_precancellation_prevents_fixture_creation(self):
        with patch.object(hybrid_suite, 'CASES', (('tiny', lambda: self.fail('created cancelled fixture')),)):
            with self.assertRaises(InterruptedError):hybrid_suite.run_benchmarks(cancelled=lambda: True)


if __name__ == '__main__':
    unittest.main()
