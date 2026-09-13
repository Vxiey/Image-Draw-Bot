from __future__ import annotations

import unittest
from pathlib import Path

from CompletedDrawLearning import timing_sample_gate
from PreviewQuality import full_preview_options
from Version import APP_VERSION


class Rc29StabilityPlannerValidationTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "1.0.145-rc29")

    def test_incomplete_draw_cannot_train_eta(self):
        result = timing_sample_gate({}, completed_paths=80, planned_paths=100)
        self.assertFalse(result["allowed"])
        self.assertIn("incomplete", result["reason"])

    def test_untrusted_final_canvas_cannot_train_eta(self):
        opts = {"post_draw_accuracy_meta": {
            "available": True, "trusted": False,
            "visual_accuracy_percent": 99.0, "actual_coverage_percent": 99.0,
        }}
        result = timing_sample_gate(opts, completed_paths=100, planned_paths=100)
        self.assertFalse(result["allowed"])
        self.assertIn("untrusted", result["reason"])

    def test_low_quality_or_coverage_cannot_train_eta(self):
        low_score = {"post_draw_accuracy_meta": {
            "available": True, "trusted": True,
            "visual_accuracy_percent": 79.0, "actual_coverage_percent": 99.0,
        }}
        low_coverage = {"post_draw_accuracy_meta": {
            "available": True, "trusted": True,
            "visual_accuracy_percent": 96.0, "actual_coverage_percent": 90.0,
        }}
        self.assertFalse(timing_sample_gate(low_score, completed_paths=100, planned_paths=100)["allowed"])
        self.assertFalse(timing_sample_gate(low_coverage, completed_paths=100, planned_paths=100)["allowed"])

    def test_trusted_complete_draw_can_train_eta(self):
        opts = {"post_draw_accuracy_meta": {
            "available": True, "trusted": True,
            "visual_accuracy_percent": 95.0, "actual_coverage_percent": 98.0,
        }}
        result = timing_sample_gate(opts, completed_paths=100, planned_paths=100)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["confidence"], "trusted-final-canvas")

    def test_execution_only_modes_remain_compatible(self):
        result = timing_sample_gate({}, completed_paths=100, planned_paths=100)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["confidence"], "execution-only")

    def test_full_preview_preserves_planner_policy_and_target_geometry(self):
        options = {
            "draw_quality": "Pixel Accurate", "drawing_mode": "Shape paths",
            "drawing_style": "Logo / Flat Graphic", "speed": "Fast",
            "precision": "High", "cpu_workers": "2", "ram_budget_mb": 512,
        }
        out = full_preview_options(options, (640, 400))
        for key in ("draw_quality", "drawing_mode", "drawing_style", "speed", "precision"):
            self.assertEqual(out[key], options[key])
        self.assertEqual(out["_target_area"], (640, 400))
        self.assertEqual(out["_preview_area"], (640, 400))
        self.assertFalse(out["_preview_plan"])

    def test_drawbot_contains_generation_guard_and_central_worker_error_log(self):
        source = Path("DrawBot.py").read_text(encoding="utf-8")
        self.assertIn("plan['preview_generation']=generation", source)
        self.assertIn("Ignored stale preview result generation=", source)
        self.assertIn("category=f'worker:{activity}'", source)
        self.assertIn("log_error", source)

    def test_eta_entrypoint_uses_sample_gate(self):
        source = Path("DrawTimeEstimate.py").read_text(encoding="utf-8")
        self.assertIn("timing_sample_gate", source)
        self.assertIn('result["sample_gate"]=gate', source)


if __name__ == "__main__":
    unittest.main()
