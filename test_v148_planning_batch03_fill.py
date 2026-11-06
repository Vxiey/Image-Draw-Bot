from __future__ import annotations

import unittest
from unittest.mock import patch

from ExecutionCostModel import build_cost_model
import RegionFillEngine as fill


def region():
    return {'color_index': 1, 'row_spans': [(y, 2, 10) for y in range(6)],
            'contour': [(2, 0), (10, 0), (10, 5), (2, 5), (2, 0)], 'seed_pixel': (5, 2),
            'area_pixels': 54, 'perimeter_pixels': 28, 'safety_score': .99, 'bbox_density': 1.0}


class FillEvidenceTests(unittest.TestCase):
    def test_nonfinite_and_coerced_safety_evidence_cannot_approve_a_fill(self):
        for field in ('safety_score', 'bbox_density'):
            for value in (float('nan'), float('inf'), -.1, 1.1, True, '1'):
                candidate = dict(region(), **{field: value})
                with self.subTest(field=field, value=repr(value)):
                    accepted, metadata = fill.evaluate_region_candidates([candidate], (20, 20), (200, 200),
                        {'brush_px': 1, 'fill_aggressiveness': 'Aggressive'})
                    self.assertEqual(accepted, [])
                    self.assertEqual(metadata['rejected_by_safety'], 1)
                    self.assertEqual(metadata['decisions'][0]['reason'], 'invalid region safety evidence')
        for field in ('area_pixels', 'perimeter_pixels'):
            for value in (0, -1, True, 5.0, 10 ** 1000):
                self.assertEqual(fill._risk(dict(region(), **{field: value}), aggressiveness='Aggressive',
                                           quality='Balanced', brush_px=1),
                                 (1.0, 0.0, 'invalid region safety evidence'))

    def test_invalid_persisted_fill_cost_is_recomputed_instead_of_becoming_zero(self):
        options = {'brush_px': 1, '_execution_cost_calibration_override': {}}
        expected = fill.estimate_fill_execution_seconds([region()], (20, 20), (200, 200), options)
        self.assertGreater(expected['total_seconds'], 0)
        for value in (float('nan'), float('inf'), -1, 0, True, '1'):
            candidate = dict(region(), fill_core_cost_seconds=value, fill_cost_seconds=value,
                             fill_batchable_overhead_seconds=0)
            with self.subTest(value=repr(value)):
                self.assertEqual(fill.estimate_fill_execution_seconds([candidate], (20, 20), (200, 200), options), expected)


class FillCostSnapshotTests(unittest.TestCase):
    def test_one_candidate_batch_uses_one_calibration_model(self):
        options = {'brush_px': 1, '_execution_cost_calibration_override': {}}
        candidates = [region() for _ in range(10)]
        real = build_cost_model(options, (20, 20), (200, 200))
        with patch('ExecutionCostModel.build_cost_model', return_value=real) as factory:
            fill.evaluate_region_candidates(candidates, (20, 20), (200, 200), options)
        factory.assert_called_once_with(options, (20, 20), (200, 200))

    def test_fill_estimate_uses_one_model_for_all_uncached_regions(self):
        options = {'brush_px': 1, '_execution_cost_calibration_override': {}}
        real = build_cost_model(options, (20, 20), (200, 200))
        with patch('ExecutionCostModel.build_cost_model', return_value=real) as factory:
            result = fill.estimate_fill_execution_seconds([region() for _ in range(8)], (20, 20), (200, 200), options)
        factory.assert_called_once()
        self.assertEqual(result['fill_regions'], 8)
        self.assertGreater(result['total_seconds'], 0)


if __name__ == '__main__':
    unittest.main()
