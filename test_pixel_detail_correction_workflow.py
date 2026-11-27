"""Exercise review and correction on two real plans of the same shipped asset."""
from contextlib import ExitStack
import threading
import unittest
from unittest.mock import patch

import numpy as np

import Colors
from CorrectionReviewRecovery import build_correction_retry_plan
from DrawBot import execute_plan, make_plan
from PreviewDetailReview import review_data
from test_drawbot import Mouse, NoWait
from test_v148_rendering_batch38_prepared_paths import close_plan
from test_v148_rendering_batch39_pixel_runs import public_options, source_image


class Playback(NoWait):
    """Virtual timer with an optional delivery delay at each positive wait."""
    def __init__(self, latency=0.0):
        super().__init__()
        self.now = 0.0
        self.latency = latency

    def wait(self, seconds):
        if seconds > 0:
            self.now += seconds + self.latency
        return self.stopped


class PlanSnapshotMouse(Mouse):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame

    def snapshot_canvas(self, area):
        return self.frame.copy()


class PixelDetailCorrectionWorkflowTests(unittest.TestCase):
    def test_timed_preview_exposes_damage_and_unlimited_draw_retry_honors_its_own_cap(self):
        previous = list(Colors.allColors)
        Colors.reset_palette()
        self.addCleanup(Colors.allColors.__setitem__, slice(None), previous)
        from PixelData import closest_color
        self.addCleanup(closest_color.cache_clear)
        with ExitStack() as scope:
            # Keep recording and logging out of the real user's storage.
            for target in ('DrawBot.log_event', 'DrawBot.save_runtime_safety_report',
                           'RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                           'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                           'CorrectionHistory.record_correction_history'):
                scope.enter_context(patch(target, return_value={}))
            source = scope.enter_context(source_image('golden-regression/small-detail-preservation.png', 96))
            options = public_options(delay=.03, brush_px=1, profile_key='microsoft-paint',
                                     _preview_plan=True, skip_white=True)
            partial = make_plan(source, source.size, dict(options, time_budget_mode='30 sec',
                                unlimited_time=False, max_seconds=30, manual_max_seconds=30))
            scope.callback(close_plan, partial, source)
            complete = make_plan(source, source.size, dict(options, delay=.003))
            scope.callback(close_plan, complete, source)

            regions = review_data(partial)['regions']
            self.assertEqual(len({row['component_id'] for row in regions}), 3)
            layers = partial['ui_previews']
            target = np.asarray(layers['quantized_target'])[..., :3]
            simulated = np.asarray(layers['simulated_final'])[..., :3]
            for region in regions:
                x0, y0, x1, y1 = region['bbox']
                self.assertGreater(region['protected_error_pixels'], 0)
                self.assertTrue(np.any(target[y0:y1, x0:x1] != simulated[y0:y1, x0:x1]))
            self.assertIsNone(review_data(complete))

            # Replay the incomplete preview as the captured frame for a retry of
            # the complete plan. Both the snapshot scorer and selector run normally.
            for latency in (0., .06):
                with self.subTest(wait_latency=latency):
                    retry = build_correction_retry_plan(complete)
                    retry['options'].update(post_draw_correction_budget_seconds=5,
                                            strict_color_verification=False, adaptive_color_verification=False)
                    playback = Playback(latency)
                    mouse = PlanSnapshotMouse(partial['preview'])
                    execute_plan(retry, (100, 100, *source.size), [(10, 10)] * len(complete['colors']),
                                 mouse, playback, threading.Event(), lambda *args: None, clock=lambda: playback.now)
                    evidence = retry['options']['post_draw_accuracy_meta']
                    result = retry['options']['post_draw_correction_meta']
                    self.assertTrue(evidence['trusted'])
                    self.assertGreater(result['executed_paths'], 0)
                    self.assertGreater(result['predicted_error_reduction_percent'], 0)
                    self.assertLessEqual(result['estimated_seconds'], 5.)
                    self.assertLessEqual(result['execution_seconds'], 5. + latency + .0001)
                    self.assertFalse(mouse.held)
                    if latency:
                        self.assertTrue(result['stopped_early'])
                        self.assertLess(result['executed_paths'], result['correction_paths'])
                    else:
                        self.assertEqual(result['executed_paths'], result['correction_paths'])
