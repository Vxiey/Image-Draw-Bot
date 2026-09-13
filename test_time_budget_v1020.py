import unittest
from PIL import Image

from ContinuousPaths import SHAPE_PATH_MODE, SMART_PATH_MODE
from TimeBudget import (TIME_BUDGET_MODES, TARGET_STROKE_COUNTS, apply_target_path_cap,
                        resolve_time_budget_seconds, resolve_target_stroke_count,
                        validate_time_budget_mode, validate_target_stroke_count,
                        parse_custom_stroke_count)
from DrawBot import make_plan
from test_skribbl_fast_renderer_v1017 import base_options
from Version import APP_VERSION, FILE_VERSION


class TimeBudgetV1020Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_modes_validate_and_resolve(self):
        self.assertIn('90 sec', TIME_BUDGET_MODES)
        self.assertIn('Custom', TARGET_STROKE_COUNTS)
        self.assertEqual(validate_time_budget_mode('2 min'), '2 min')
        self.assertEqual(validate_target_stroke_count('5000'), '5000')
        self.assertEqual(resolve_time_budget_seconds('90 sec', 180), (80, True))
        self.assertEqual(resolve_time_budget_seconds('Manual', 180), (180, False))
        with self.assertRaises(ValueError):
            validate_time_budget_mode('Soon')
        with self.assertRaises(ValueError):
            validate_target_stroke_count('1234')

    def test_custom_target_validation(self):
        self.assertEqual(parse_custom_stroke_count('2500'), 2500)
        with self.assertRaises(ValueError):
            parse_custom_stroke_count('20')
        with self.assertRaises(ValueError):
            parse_custom_stroke_count('abc')

    def test_auto_target_is_only_active_with_time_budget(self):
        cap, meta = resolve_target_stroke_count('Auto', time_budget_mode='Manual', effective_time_seconds=180)
        self.assertIsNone(cap)
        self.assertEqual(meta['target_stroke_count_reason'], 'manual-auto')
        cap, meta = resolve_target_stroke_count('Auto', time_budget_mode='60 sec', effective_time_seconds=60,
                                                speed='Fast', drawing_mode=SHAPE_PATH_MODE)
        self.assertIsInstance(cap, int)
        self.assertLess(cap, 1000)
        self.assertEqual(meta['target_stroke_count_reason'], 'time-budget-auto')

    def test_target_path_cap_keeps_largest_paths(self):
        groups = [[((0, 0), (100, 0)), ((0, 1), (2, 1)), ((0, 2), (80, 2))]]
        capped, meta = apply_target_path_cap(groups, 2)
        self.assertEqual(meta['target_before_paths'], 3)
        self.assertEqual(meta['target_after_paths'], 2)
        self.assertEqual(meta['target_skipped_paths'], 1)
        self.assertNotIn(((0, 1), (2, 1)), capped[0])

    def test_make_plan_respects_target_count(self):
        im = Image.new('RGBA', (80, 80), 'white')
        for y in range(5, 75):
            for x in range(5, 75):
                if (x // 5 + y // 5) % 2 == 0:
                    im.putpixel((x, y), (0, 0, 0, 255))
        plan = make_plan(im, (800, 800), base_options(
            drawing_mode=SHAPE_PATH_MODE, target_stroke_count='Custom', target_stroke_custom='50',
            max_stroke_cap='Unlimited', time_budget_mode='Manual'))
        self.assertLessEqual(plan['count'], 50)
        self.assertEqual(plan['options']['target_stroke_count_resolved'], 50)
        self.assertGreaterEqual(plan['path_stats'].get('target_skipped_paths', 0), 0)

    def test_time_budget_updates_effective_limit(self):
        im = Image.new('RGBA', (20, 20), 'black')
        plan = make_plan(im, (200, 200), base_options(
            drawing_mode=SMART_PATH_MODE, time_budget_mode='60 sec', target_stroke_count='Auto', max_seconds=180))
        self.assertEqual(plan['options']['max_seconds'], 53)
        self.assertTrue(plan['options']['time_budget_active'])
        self.assertIsNotNone(plan['options']['target_stroke_count_resolved'])


if __name__ == '__main__':
    unittest.main()
