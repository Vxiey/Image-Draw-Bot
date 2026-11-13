"""Correction history must never publish rows its own reader discards."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import CorrectionHistory as history
from test_step16_correction_history_v10140 import base_plan


class HistoryWriteValidationTests(unittest.TestCase):
    def test_invalid_rows_cannot_evict_valid_history_or_report_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            for i in range(history.MAX_ENTRIES):
                history.record_correction_history(base_plan(), path=path, created_at=i + 1)
            original = path.read_bytes()
            cases = [('actual_seconds', -1)]
            cases += [(field, value) for field in (
                'executed_paths', 'correction_paths', 'executed_colors',
                'corrected_colors', 'selected_correction_pixels', 'missing_pixels',
                'wrong_color_pixels') for value in (-1, 1_000_000_001)]
            for field, value in cases:
                with self.subTest(field=field, value=value):
                    plan = base_plan()
                    kwargs = {'actual_seconds': value} if field == 'actual_seconds' else {}
                    if not kwargs:
                        plan['options']['post_draw_correction_meta'][field] = value
                    with patch.object(history, 'atomic_write_text') as write:
                        result = history.record_correction_history(plan, path=path,
                            created_at=100, **kwargs)
                    self.assertFalse(result['recorded'])
                    self.assertIn('invalid', result['reason'])
                    write.assert_not_called()
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(history.load_correction_history(plan['options'],
                        path=path)['entry_count'], history.MAX_ENTRIES)

    def test_valid_boundary_row_round_trips_and_keeps_profile_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            plan = base_plan()
            plan['options']['post_draw_correction_meta'].update(
                correction_paths=1_000_000_000, executed_paths=0)
            result = history.record_correction_history(plan, path=path,
                actual_seconds=0, created_at=0)
            self.assertTrue(result['recorded'])
            loaded = history.load_correction_history(plan['options'], path=path)
            self.assertEqual(loaded['entry_count'], 1)
            self.assertEqual(loaded['entries'][0]['planned_correction_paths'], 1_000_000_000)
            self.assertEqual(history.load_correction_history({'profile_key': 'other'},
                path=path)['entry_count'], 0)


if __name__ == '__main__':
    unittest.main()
