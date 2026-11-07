"""Custom timers retain monotonic usable time through real budget consumers."""
from contextlib import closing
import math
import unittest
from unittest.mock import patch

from PIL import Image

from TimeBudgetEngine import automatic_reserve, resolve_budget


class AutomaticReserveTests(unittest.TestCase):
    def test_every_valid_quarter_second_adds_usable_time_without_losing_reserve(self):
        totals = [n / 4 for n in range(20, 14401)]
        for boundary in (30, 60, 80, 90, 120, 150, 180, 300, 400, 600):
            totals.extend((math.nextafter(boundary, 0), math.nextafter(boundary, math.inf)))
        previous = None
        for total in sorted(totals):
            budget = resolve_budget('Custom', total, 'Auto')
            reserve = budget['reserve_seconds']
            usable = budget['render_budget_seconds']
            self.assertGreaterEqual(reserve, 3.0)
            self.assertLessEqual(reserve, 30.0)
            self.assertAlmostEqual(usable + reserve, total)
            if previous:
                self.assertGreaterEqual(reserve + 1e-12, previous[1], (previous, total, reserve))
                self.assertGreaterEqual(usable + 1e-12, previous[2], (previous, total, usable))
                self.assertLessEqual(reserve - previous[1], total - previous[0] + 1e-12)
            previous = (total, reserve, usable)

    def test_legacy_timer_anchors_and_builtin_game_reserves_are_preserved(self):
        for mode, total, reserve in (('30 sec', 30, 3.45), ('60 sec', 60, 7),
                                     ('90 sec', 90, 10), ('2 min', 120, 10.2),
                                     ('5 min', 300, 19.5), ('10 min', 600, 30)):
            with self.subTest(mode=mode):
                actual = resolve_budget(mode)
                self.assertAlmostEqual(actual['reserve_seconds'], reserve)
                self.assertAlmostEqual(actual['render_budget_seconds'], total - reserve)
        for mode, total, usable in (('Gartic Phone Fast', 75, 67), ('Gartic Phone Normal', 150, 138),
                                   ('Gartic Phone Slow', 300, 283), ('Skribbl Default', 80, 72),
                                   ('Skribbl 60', 60, 53), ('Skribbl 120', 120, 110),
                                   ('Skribbl 150', 150, 138), ('Emergency 30 s', 30, 26),
                                   ('Ultra Fast 60 s', 60, 53), ('Detailed 120 s', 120, 110),
                                   ('Maximum 300 s', 300, 280)):
            with self.subTest(mode=mode):
                actual = resolve_budget(mode)
                self.assertEqual(actual['total_seconds'], total)
                self.assertEqual(actual['render_budget_seconds'], usable)

    def test_application_color_budget_and_adaptive_plan_use_same_continuous_budget(self):
        from AdaptiveDeadlineRenderer import adapt_execution_plan
        from DrawBot import _ensure_time_budget_options
        from TimeAwareColorBudget import apply_time_aware_color_budget

        with closing(Image.new('RGB', (20, 20), 'white')) as image:
            for before, after in ((30, 31), (80, 81), (150, 151), (300, 301)):
                results = []
                for total in (before, after):
                    options = _ensure_time_budget_options({
                        'time_budget_mode': 'Custom', 'max_seconds': total,
                        'preview_plan': True, 'gpu_mode': 'CPU', 'speed': 'Balanced',
                        'delay': .006, 'precision': 'High', 'profile_key': 'batch06-no-history',
                        'deadline_safety_reserve': 'Auto', 'adaptive_deadline_renderer': True,
                    })
                    with patch('TimeAwareColorBudget._load_calibration', return_value={}):
                        _, color = apply_time_aware_color_budget(12, {}, options)
                    _, sequence, deadline, _ = adapt_execution_plan(
                        image, (20, 20), [[((4, 4), (15, 4))]], options)
                    expected = resolve_budget('Custom', total)
                    self.assertEqual(color['render_budget_seconds'], expected['render_budget_seconds'])
                    self.assertEqual(deadline['render_budget_seconds'], expected['render_budget_seconds'])
                    self.assertEqual(options['deadline_safety_reserve_seconds'], expected['reserve_seconds'])
                    self.assertTrue(sequence)
                    results.append(expected['render_budget_seconds'])
                self.assertGreater(results[1], results[0])

    def test_explicit_reserves_and_manual_unlimited_modes_are_unchanged(self):
        self.assertEqual(resolve_budget('Custom', 100, 15)['render_budget_seconds'], 85)
        self.assertEqual(resolve_budget('Custom', 100, 'Off')['render_budget_seconds'], 100)
        self.assertEqual(resolve_budget('Manual', 100)['render_budget_seconds'], 100)
        self.assertIsNone(resolve_budget('Unlimited')['render_budget_seconds'])
        for invalid in (0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                automatic_reserve(invalid)


if __name__ == '__main__':
    unittest.main()
