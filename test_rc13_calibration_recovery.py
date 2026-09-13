\
import unittest
from pathlib import Path
from unittest.mock import patch

from BrowserAutoRecalibration import (
    BrowserLayoutDelta, calibrate_browser_with_retry, evaluate_cached_canvas, plan_recalibration,
)
from CalibrationHealth import summarize_calibration_health
from Version import APP_VERSION


class Rc13CalibrationRecoveryTests(unittest.TestCase):
    def test_small_canvas_drift_is_partial(self):
        plan = evaluate_cached_canvas((100,100,900,600), (106,103,906,603), .91)
        self.assertEqual(plan.action, 'canvas-only')
        self.assertTrue(plan.safe_to_reuse_palette)
        self.assertFalse(plan.safe_to_reuse_canvas)

    def test_large_canvas_drift_requires_full(self):
        plan = evaluate_cached_canvas((100,100,900,600), (150,100,950,600), .95)
        self.assertEqual(plan.action, 'full')

    def test_dpi_or_resize_requires_full(self):
        delta = BrowserLayoutDelta(True, ('DPI 96→120','client resize 1000×700→1200×840'), 0, 0)
        plan = plan_recalibration(delta, palette_confidence=.98, canvas_confidence=.98)
        self.assertEqual(plan.action, 'full')

    def test_retry_is_bounded_and_adaptive(self):
        class Result: pass
        calls=[]; sleeps=[]
        def fake(*args, **kwargs):
            calls.append(1)
            if len(calls)==1:
                raise ValueError('Palette confidence is too low (61%). Manual fallback is safer for this layout.')
            return Result()
        with patch('BrowserAutoCalibration.auto_calibrate_browser', side_effect=fake):
            result,meta=calibrate_browser_with_retry(
                'gartic-phone', {'client_rect':(0,0,100,100)}, Path('x'),
                screenshot=object(), recapture=lambda:object(), sleep_fn=sleeps.append)
        self.assertIsInstance(result, Result)
        self.assertEqual(meta['attempts'], 2)
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)
        self.assertLessEqual(sleeps[0], .45)

    def test_non_transient_geometry_error_is_not_retried(self):
        calls=[]
        def fake(*args, **kwargs):
            calls.append(1)
            raise ValueError('Target screenshot size changed during calibration. Keep the browser window still.')
        with patch('BrowserAutoCalibration.auto_calibrate_browser', side_effect=fake):
            with self.assertRaises(ValueError):
                calibrate_browser_with_retry('gartic-phone', {}, Path('x'), screenshot=object(), sleep_fn=lambda _s:None)
        self.assertEqual(len(calls), 1)

    def test_health_weights_layout_and_palette_as_safety_evidence(self):
        summary={
            'palette':{'state':'verified','available':True,'count':48,'verification':{'confidence':.96}},
            'tools':{'state':'calibrated','available':True,'confidence':.85},
            'exact_color':{'state':'unavailable','available':False},
            'timing':{'state':'calibrated','available':True,'samples':5,'mape':.08},
        }
        good=summarize_calibration_health(summary)
        self.assertIn(good.level, ('healthy','verified'))
        self.assertFalse(good.blocking)
        bad=summarize_calibration_health(summary, layout_delta=BrowserLayoutDelta(True, ('DPI 96→144',), 0, 0))
        self.assertLess(bad.score, good.score)
        self.assertIn('layout', bad.recalibrate_components)

    def test_runtime_source_contains_partial_refresh_and_retry(self):
        src=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('evaluate_cached_canvas', src)
        self.assertIn('calibrate_browser_with_retry', src)
        self.assertIn("'recalibration_plan':recalibration_plan.as_dict()", src)

    def test_version(self):
        self.assertEqual(APP_VERSION, '1.0.146-rc2')


if __name__ == '__main__':
    unittest.main()
