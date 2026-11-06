from __future__ import annotations

import random
import unittest
from unittest.mock import patch

import numpy as np

import PixelAccuracyEngine as engine
from PixelAccuratePlanner import PixelMap
from RasterGeometry import clipped_bresenham, clipped_interpolated_line


def target(indices):
    values = np.asarray(indices, np.int16)
    h, w = values.shape
    return PixelMap(w, h, np.zeros((h, w, 3), np.uint8), np.where(values >= 0, values, 0),
                    values >= 0, np.ones((h, w), np.float32), np.ones((h, w), np.float32),
                    np.ones((h, w), bool), {})


class VisibleLatticeTests(unittest.TestCase):
    def test_clipped_interpolation_preserves_original_rounding_phase(self):
        randomizer=random.Random(14805)
        for _ in range(1500):
            a,b=[(randomizer.randrange(-15,16),randomizer.randrange(-15,16)) for _ in range(2)]
            if a==b:continue
            steps=max(abs(a[0]-b[0]),abs(a[1]-b[1]),1)
            before,after=randomizer.randrange(4),randomizer.randrange(4)
            expected=[]
            for k in range(steps+1):
                x=round(a[0]+(b[0]-a[0])*(k/steps));y=round(a[1]+(b[1]-a[1])*(k/steps))
                if -after<=x<=6+before and -after<=y<=4+before:expected.append((x,y))
            self.assertEqual(list(clipped_interpolated_line(a,b,7,5,before=before,after=after)),expected)

    def test_clipped_lattice_keeps_original_sampling_phase_in_all_octants(self):
        generator = random.Random(14803)
        for _ in range(3000):
            a, b = [(generator.randrange(-15, 16), generator.randrange(-15, 16)) for _ in range(2)]
            before, after = generator.randrange(4), generator.randrange(4)
            expected = [(x, y) for x, y in engine._bresenham(a, b)
                        if -after <= x <= 6 + before and -after <= y <= 4 + before]
            self.assertEqual(list(clipped_bresenham(a, b, 7, 5, before=before, after=after)), expected)

    def test_far_outside_prefix_does_not_need_traversal(self):
        huge = 10 ** 30
        self.assertEqual(list(clipped_bresenham((-huge, -huge), (huge, huge), 4, 3)),
                         [(0, 0), (1, 1), (2, 2)])
        self.assertEqual(list(clipped_bresenham((-huge, huge), (huge, huge - 1), 4, 3)), [])
        self.assertEqual(list(clipped_bresenham((1, 1), (1, 1), 0, 3)), [])

    def test_brush_hits_match_full_line_then_clipping(self):
        generator = random.Random(14804)
        for brush in (1, 2, 3, 4):
            for _ in range(50):
                a, b = [(generator.randrange(-12, 13), generator.randrange(-12, 13)) for _ in range(2)]
                if a[0] == b[0] or a[1] == b[1]:continue
                expected = np.zeros((7, 9), np.uint16)
                lo, hi = (brush - 1) // 2, brush // 2
                for x, y in engine._bresenham(a, b):
                    for yy in range(y - lo, y + hi + 1):
                        for xx in range(x - lo, x + hi + 1):
                            if 0 <= xx < 9 and 0 <= yy < 7:
                                expected[yy, xx] += 1
                actual = np.zeros_like(expected)
                simulated = np.zeros((7, 9), np.int16)
                engine._apply_path(simulated, actual, 1, (a, b), brush)
                np.testing.assert_array_equal(actual, expected)
                np.testing.assert_array_equal(simulated == 1, expected > 0)


class SimulationCancellationTests(unittest.TestCase):
    def test_empty_precancelled_simulation_does_not_allocate(self):
        pm = target([[1]])
        for function in (engine.simulate_strokes, engine.progressive_accuracy_checkpoints):
            with patch.object(engine.np, 'full', side_effect=AssertionError('allocation')):
                with self.assertRaises(InterruptedError):
                    function(pm, [], [(255, 255, 255), (0, 0, 0)], cancelled=lambda: True)

    def test_single_long_diagonal_checks_cancellation_inside_the_stroke(self):
        painted = 0
        real = engine._paint_rect
        def paint(*args):
            nonlocal painted
            painted += 1
            real(*args)
        sim = np.zeros((1000, 1000), np.int16)
        counts = np.zeros((1000, 1000), np.uint16)
        with patch.object(engine, '_paint_rect', side_effect=paint):
            with self.assertRaises(InterruptedError):
                engine._apply_path(sim, counts, 1, ((0, 0), (999, 998)), 1, cancelled=lambda: painted >= 10)
        self.assertLessEqual(painted, 256)

    def test_gpu_score_cancellation_is_not_swallowed_as_cpu_fallback(self):
        pm = target([[1]])
        result = (np.ones((1, 1), np.int16), np.ones((1, 1), np.uint16), {})
        with patch('PixelAccuracyGpu.simulate_cuda', return_value=result), \
                patch('PixelAccuracyGpu.score_cuda_host', side_effect=InterruptedError()):
            with self.assertRaises(InterruptedError):
                engine.simulate_strokes(pm, [], [(255, 255, 255), (0, 0, 0)], gpu_mode='Auto')

    def test_correction_run_scan_checks_inside_one_wide_row(self):
        pm = target(np.ones((1, 5000), np.int16))
        result = engine.SimulationResult(np.zeros((1, 5000), np.int16), np.zeros((1, 5000), np.uint16),
                                         np.zeros((1, 5000), bool), np.ones((1, 5000), np.uint8), {})
        checks = 0
        def cancel():
            nonlocal checks
            checks += 1
            return checks >= 3
        with self.assertRaises(InterruptedError):
            engine._correction_runs(pm, result, 0, pass_number=1, cancelled=cancel)
        self.assertEqual(checks, 3)


class RegionScoresTests(unittest.TestCase):
    def test_region_statistics_match_independent_component_pixel_sets(self):
        indices = np.array([[0, 0, -1, 1], [0, 1, 1, 1], [-1, 1, 0, 0]], np.int16)
        pm = target(indices)
        pm.edge_map[:] = 0
        pm.edge_map[0, 0] = pm.edge_map[1, 3] = 1
        pm.protected_mask[:] = False
        pm.protected_mask[1, 0] = pm.protected_mask[2, 2] = True
        actual = np.where(indices >= 0, indices, 0).copy()
        actual[0, 0] = 1
        actual[1, 1] = 0
        counts = np.ones(indices.shape, np.uint16)
        counts[2, 1] = 0
        simulation = engine.SimulationResult(actual, counts, counts > 0, np.zeros(indices.shape, np.uint8), {})
        measured = engine.region_accuracy_scores(pm, simulation)
        sets = [{(0, 0), (1, 0), (0, 1)}, {(3, 0), (1, 1), (2, 1), (3, 1), (1, 2)}, {(2, 2), (3, 2)}]
        expected = []
        for cid, points in enumerate(sets):
            correct = {p for p in points if actual[p[1], p[0]] == indices[p[1], p[0]]}
            covered = {p for p in points if counts[p[1], p[0]]}
            edges = {p for p in points if pm.edge_map[p[1], p[0]] >= .5}
            protected = {p for p in points if pm.protected_mask[p[1], p[0]]}
            color = len(correct) / len(points) * 100
            coverage = len(covered) / len(points) * 100
            edge = len(correct & edges) / len(edges) * 100 if edges else color
            detail = len(correct & protected) / len(protected) * 100 if protected else color
            expected.append((cid, round(.4 * color + .25 * coverage + .2 * edge + .15 * detail, 4)))
        self.assertEqual({r['component_id']: r['score'] for r in measured['worst_regions']}, dict(expected))
        self.assertEqual(measured['region_count'], 3)


if __name__ == '__main__':
    unittest.main()
