import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import AdaptiveDetail
import ContinuousPaths
import DeadlineScheduler as DS
import FastDryRun
import Precision
import RealSpeedBudget as RSB
import SafeFillMask as SFM
from CanvasGuard import CanvasGuard
from RasterIdentity import compare_runs_to_paths
from TimeBudget import apply_target_path_cap


class DryRunCapsTests(unittest.TestCase):
    def plan(self):
        return {'groups': [[(x, color, x + 1, color) for x in range(12)] for color in range(6)],
                'options': {}, 'count': 72}

    def test_path_limit_smaller_than_color_limit_and_zero_are_respected(self):
        for paths in (0, 1, 2, 3, 5):
            out = FastDryRun.sample_plan(self.plan(), max_colors=6, max_paths=paths)
            self.assertLessEqual(out['count'], paths)
            self.assertEqual(sum(len(group) for group in out['groups']), out['count'])
        self.assertEqual(FastDryRun.sample_plan(self.plan(), max_paths=0)['options']['color_order'], [])

    def test_progressive_sequence_obeys_color_cap_and_keeps_original_order(self):
        sequence = [{'color_index': index % 8, 'path': ((index, 0), (index + 1, 0)), 'id': index}
                    for index in range(80)]
        plan = dict(self.plan(), execution_sequence=sequence)
        out = FastDryRun.sample_plan(plan, max_colors=2, max_paths=8)
        self.assertLessEqual(len({row['color_index'] for row in out['execution_sequence']}), 2)
        self.assertEqual(out['count'], 8)
        self.assertEqual([row['id'] for row in out['execution_sequence']], sorted(row['id'] for row in out['execution_sequence']))
        self.assertEqual(out['options']['dry_run_sample_colors'], len(out['options']['color_order']))
        self.assertEqual(plan['execution_sequence'], sequence)
        self.assertEqual(FastDryRun.sample_plan(plan, max_colors=0)['execution_sequence'], [])


class ProtectedGeometryTests(unittest.TestCase):
    def test_every_short_raster_pixel_is_protected_including_reverse_and_diagonal(self):
        cases = [((0, 0, 3, 0), (2, 0)), ((3, 0, 0, 0), (1, 0)),
                 ((0, 0, 0, 3), (0, 2)), ((0, 0, 3, 3), (2, 2))]
        for stroke, protected in cases:
            mask = Image.new('L', (4, 4), 0)
            mask.putpixel(protected, 255)
            groups, meta = AdaptiveDetail.prune_flat_micro_strokes([[stroke]], mask, 'Strong simplify')
            self.assertEqual(groups, [[stroke]])
            self.assertEqual(meta['adaptive_detail_pruned_micro_pixels'], 0)
        groups, meta = AdaptiveDetail.prune_flat_micro_strokes([[(0, 0, 3, 0)]], Image.new('L', (4, 1)), 'Strong simplify')
        self.assertEqual(groups, [[]])
        self.assertEqual(meta['adaptive_detail_pruned_micro_pixels'], 4)

    def test_path_cap_filters_semantics_with_the_same_original_indices(self):
        outline = ((0, 0), (1, 0))
        tone = ((0, 1), (100, 1))
        source = ContinuousPaths.ExecutionGroups([[(), outline, tone]], phase_hints=[['empty', 'outline', 'tone']],
                                                 protected_prefix_counts=[2], semantic_meta={'portrait_semantic_barrier': True})
        kept, meta = apply_target_path_cap(source, 1)
        self.assertEqual(kept, [[outline]])
        self.assertEqual(meta['path_phase_hints'], [['outline']])
        self.assertEqual(kept.protected_prefix_counts, [1])
        unlimited, meta = apply_target_path_cap(source, None)
        self.assertEqual(unlimited, [[outline, tone]])
        self.assertEqual(meta['path_phase_hints'], [['outline', 'tone']])
        self.assertEqual(meta['protected_prefix_before'], 1)
        self.assertEqual(source.phase_hints, [['empty', 'outline', 'tone']])


class DeadlineTransitionTests(unittest.TestCase):
    def test_replanning_includes_transitions_at_phase_boundaries(self):
        rows = [dict(operation_type='stroke', color_index=color, brush_px=brush, phase=phase,
                     importance=importance, estimated_cost_seconds=.1, id=index)
                for index, (color, brush, phase, importance) in enumerate([
                    (0, 1, 'major_coverage', .5), (0, 1, 'structure', .5),
                    (1, 2, 'structure', .9), (1, 2, 'accuracy', .5)])]
        for barrier in (False, True):
            sequence = list(rows)
            if barrier:
                sequence.insert(1, {'operation_type': 'verify', 'estimated_cost_seconds': .1})
            scheduler = DS.DeadlineScheduler(sequence, start_time=0, budget_seconds=60, clock=lambda: 0)
            scheduler.mode = DS.CATCH_UP
            result = scheduler.replan_remaining(sequence, force=True)
            states = [(row['color_index'], row['brush_px']) for row in result if row['operation_type'] == 'stroke']
            self.assertEqual(sum(a != b for a, b in zip(states, states[1:])), 1)
            self.assertEqual([row['id'] for row in result if row['operation_type'] == 'stroke'], [0, 1, 2, 3])
            self.assertEqual(scheduler.replan_rejected_switch_cost, 1)


class TimingIntegrityTests(unittest.TestCase):
    def test_invalid_elapsed_samples_do_not_modify_learned_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timing.json'
            RSB.record_runtime_sample('gartic-phone', 120, 20, path=path)
            previous = path.read_bytes()
            for elapsed in (float('nan'), float('inf'), -float('inf'), 0, -1, 'bad'):
                self.assertFalse(RSB.record_runtime_sample('gartic-phone', 20, elapsed, path=path)['recorded'])
                self.assertEqual(path.read_bytes(), previous)

    def test_corrupt_old_profile_falls_back_and_next_good_sample_repairs_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timing.json'
            path.write_text(json.dumps({'version': 1, 'profiles': {'gartic-phone': {'paths_per_second': float('nan'), 'samples': 4}}}))
            recommendation = RSB.recommend_budget('gartic-phone', 60, path=path)
            self.assertFalse(recommendation.learned)
            self.assertEqual(recommendation.paths_per_second, RSB.FALLBACK_PPS['gartic-phone'])
            sample = RSB.record_runtime_sample('gartic-phone', 120, 20, path=path)
            self.assertEqual(sample['paths_per_second'], 6.0)
            self.assertEqual(sample['samples'], 1)
            self.assertEqual(json.loads(path.read_text())['profiles']['gartic-phone']['total_seconds'], 20.0)


class PrecisionCountTests(unittest.TestCase):
    def test_normal_count_does_not_construct_execution_coordinates(self):
        with patch.object(Precision, 'precision_path', side_effect=AssertionError('allocated execution path')):
            self.assertEqual(Precision.precision_path_count((0, 0), (4000, 3000), 'High', 8), 1250)
            self.assertEqual(Precision.precision_path_count((-20, 3), (20, 3), 'Ultra', 8), 20)
            self.assertEqual(Precision.precision_path_count((1, 1), (1, 1)), 0)

    def test_dense_rounding_and_negative_coordinates_match_actual_execution(self):
        self.assertEqual(Precision.precision_path_count((0, 0), (1, 1), 'Ultra', 1), 1)
        self.assertEqual(Precision.precision_path_count((0, 0), (2, 1), 'Ultra', 1), 3)
        rng = random.Random(148)
        for _ in range(800):
            start = (rng.randrange(-200, 201), rng.randrange(-200, 201))
            end = (rng.randrange(-200, 201), rng.randrange(-200, 201))
            step = rng.choice((1, 1.1, 1.5, 2, 4, 8, 12))
            level = rng.choice(('Normal', 'High', 'Ultra'))
            self.assertEqual(Precision.precision_path_count(start, end, level, step),
                             len(Precision.precision_path(start, end, level, step)))
        with self.assertRaises(ValueError):
            Precision.precision_path_count((0, 0), (500001, 0), 'High', 4)


class ContinuousSweepTests(unittest.TestCase):
    def test_separated_columns_have_exact_expected_vertical_paths(self):
        strokes = [(x * 3, y, x * 3, y) for y in range(8) for x in range(400)]
        result = ContinuousPaths.build_execution_paths([strokes], enabled=True)[0]
        self.assertEqual(result, [((x * 3, 0), (x * 3, 7)) for x in range(400)])

    def test_overlap_sweep_preserves_integer_raster_with_overlapping_runs_and_gaps(self):
        rng = random.Random(148)
        for _ in range(80):
            strokes = []
            for y in range(12):
                if rng.random() < .15:
                    continue
                for _ in range(rng.randrange(1, 8)):
                    x1, x2 = rng.randrange(-10, 25), rng.randrange(-10, 25)
                    strokes.append((x1, y, x2, y))
            paths = ContinuousPaths.build_execution_paths([strokes], enabled=True, max_rows_per_path=4)[0]
            report = compare_runs_to_paths(strokes, paths)
            self.assertTrue(report.safe, report.as_dict())


class FillGeometryGateTests(unittest.TestCase):
    def setUp(self):
        self.base = {'bbox': (5, 5, 20, 20), 'seed_pixel': (10, 10), 'row_spans': [(10, 5, 20)]}
        self.guard = CanvasGuard.from_area((0, 0, 40, 40), brush_px=1, edge_margin_px=0)
        self.transform = Precision.CanvasTransform(40, 40, (40, 40))

    def accepted(self, region):
        source, _ = SFM.filter_fill_regions_by_source_mask([region], (40, 40), margin_px=2)
        runtime = SFM.filter_fill_regions_by_runtime_mask([region], (40, 40), self.transform, self.guard)
        return bool(source), bool(runtime.accepted_regions)

    def test_malformed_present_contour_cannot_be_treated_as_absent(self):
        for contour in ([(5, 5), (float('nan'), 10), (20, 20)], [(5, 5), (float('inf'), 10)],
                        [(5, 5), (1,)], 42, 'bad', {'55': 1}, '', False, {}, 0, [{'x': 5, 'y': 5}]):
            self.assertEqual(self.accepted(dict(self.base, contour=contour)), (False, False))
        self.assertEqual(self.accepted(self.base), (True, True))
        for contour in (None, [], ()):
            self.assertEqual(self.accepted(dict(self.base, contour=contour)), (True, True))

    def test_malformed_reversed_or_inconsistent_spans_are_rejected(self):
        for spans in ([(10, 100, -10)], [('bad',)], [(10, 4, 21)], [(10.5, 5, 20)], [(float('inf'), 5, 20)],
                      '', False, {}, 0, [{0: 10, 1: 5, 2: 20}]):
            self.assertEqual(self.accepted(dict(self.base, row_spans=spans)), (False, False))
        self.assertEqual(self.accepted(dict(self.base, row_spans=[])), (True, True))
        self.assertEqual(self.accepted(dict(self.base, row_spans=None)), (True, True))

    def test_seed_must_belong_to_its_exact_region_not_just_safe_canvas(self):
        for seed in ((30, 30), (10, 11), (21, 10)):
            self.assertEqual(self.accepted(dict(self.base, seed_pixel=seed)), (False, False))
        self.assertEqual(self.accepted(dict(self.base, seed_pixel=(20, 10))), (True, True))


if __name__ == '__main__':
    unittest.main()
