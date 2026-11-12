"""Exact regional plans with bounded/reused component preparation.

All categorical maps come from existing repository source fixtures.
"""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveRegionHybrid as regional
import PixelStrokeEngine as strokes
from PixelAccuratePlanner import build_pixel_map
from test_v148_rendering_batch39_pixel_runs import public_options

ROOT = Path(__file__).resolve().parent
PALETTE = ((0, 0, 0), (255, 255, 255), (221, 43, 54), (247, 209, 38),
    (42, 165, 86), (48, 100, 220), (132, 36, 48), (65, 36, 25),
    (197, 64, 45), (45, 145, 82), (248, 211, 45), (99, 104, 108))


def pixel_map():
    with closing(Image.open(ROOT / 'golden-regression/red-bananas-texture.png')) as original, \
            closing(original.resize((96, 64))) as source:
        return build_pixel_map(source, PALETTE, gpu_mode='CPU')


def scalar_vertical(labels, start, stop):
    result = []
    for x in range(start, stop):
        y = 0
        while y < len(labels):
            color = int(labels[y, x]); first = y
            while y + 1 < len(labels) and int(labels[y + 1, x]) == color:
                y += 1
            if color >= 0:
                result.append((color, (x, first, x, y)))
            y += 1
    return result


class VerticalComponentTests(unittest.TestCase):
    def test_exact_column_and_component_order_matches_scalar_runs(self):
        mapped = pixel_map()
        _components, labels, _meta = strokes.connected_components(mapped, include_vertical_runs=False)
        for view in (labels, labels[:, ::-1], labels.T, labels[:1], labels[:, :1]):
            view.flags.writeable = False
            before = view.tobytes()
            width = view.shape[1]
            for start, stop in ((0, width), (min(1, width), width), (width, width)):
                with self.subTest(shape=view.shape, start=start):
                    self.assertEqual(strokes._vertical_run_chunk(view, start, stop), scalar_vertical(view, start, stop))
                    self.assertEqual(view.tobytes(), before)

    def test_real_component_builder_uses_fewer_numpy_boundary_scans(self):
        mapped = pixel_map()
        original_nonzero = np.nonzero
        original_flat = np.flatnonzero
        _components, labels, _meta = strokes.connected_components(mapped, include_vertical_runs=False)
        with patch.object(np, 'nonzero', wraps=original_nonzero) as scans, \
                patch.object(np, 'flatnonzero', wraps=original_flat) as flat_scans:
            actual = strokes._vertical_run_chunk(labels, 0, mapped.width)
        self.assertEqual(actual, scalar_vertical(labels, 0, mapped.width))
        # One 96-column fixture previously dispatched 96 independent searches.
        self.assertLess(scans.call_count + flat_scans.call_count, mapped.width // 4)

    def test_parallel_components_preserve_the_complete_serial_result(self):
        mapped = pixel_map()
        serial = strokes.connected_components(mapped, cpu_workers=1)
        parallel = strokes.connected_components(mapped, cpu_workers=3)
        self.assertEqual(serial[0], parallel[0])
        np.testing.assert_array_equal(serial[1], parallel[1])
        for key in ('component_count', 'source_runs', 'component_connectivity'):
            self.assertEqual(serial[2][key], parallel[2][key])

    def test_late_stop_during_real_vertical_emission_has_no_result(self):
        mapped = pixel_map()
        _components, labels, _meta = strokes.connected_components(mapped, include_vertical_runs=False)
        attempts = 0
        def stop():
            nonlocal attempts
            attempts += 1
            return attempts >= 4
        with self.assertRaises(InterruptedError):
            strokes._vertical_run_chunk(labels, 0, mapped.width, stop)
        self.assertEqual(attempts, 4)


class HybridPreparationTests(unittest.TestCase):
    def test_real_hybrid_schedule_keeps_plan_with_linear_membership_partition(self):
        mapped = pixel_map()
        original = regional._schedule
        receipts = []
        class CountedColor(int):
            calls = 0
            def __int__(self):
                CountedColor.calls += 1
                return super().__int__()
        def observe(choices, sequences, *args, **kwargs):
            expected = original(choices, sequences, *args, **kwargs)
            counted = [replace(choice, color_index=CountedColor(choice.color_index)) for choice in choices]
            CountedColor.calls = 0
            actual = original(counted, sequences, *args, **kwargs)
            self.assertEqual(actual, expected)
            receipts.append((len(choices), CountedColor.calls))
            return actual
        with patch.object(regional, '_schedule', new=observe):
            result = regional.build_adaptive_execution(mapped, PALETTE,
                public_options(brush_px=1), (mapped.width, mapped.height))
        try:
            self.assertTrue(result['execution_sequence'])
            self.assertEqual(result['metrics']['missing_pixels'], 0)
            self.assertEqual(result['metrics']['wrong_color_pixels'], 0)
            self.assertEqual(len(receipts), 1)
            components, calls = receipts[0]
            self.assertGreater(components, 100)
            self.assertLess(calls, components * 50, receipts)
        finally:
            result['coverage_preview'].close(); result['error_preview'].close()

    def test_hybrid_coverage_verifier_observes_cancellation_at_its_boundary(self):
        mapped = pixel_map()
        components, labels, _meta = strokes.connected_components(mapped)
        component = max(components, key=lambda item: item.area)
        merge = strokes._merge_horizontal_runs_lossless
        stopped = False
        def complete(*args, **kwargs):
            nonlocal stopped
            result = merge(*args, **kwargs)
            stopped = True
            return result
        with patch.object(strokes, '_merge_horizontal_runs_lossless', new=complete):
            with self.assertRaises(InterruptedError):
                regional._orientation_paths(component, 'horizontal', labels, cancelled=lambda: stopped)


if __name__ == '__main__':
    unittest.main()
