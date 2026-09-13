from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one patch anchor, found {count}: {old[:90]!r}")
    write(path, text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# 1. rc29 version metadata
# ---------------------------------------------------------------------------
replace_once("Version.py", "APP_VERSION = '1.0.145-rc28'", "APP_VERSION = '1.0.145-rc29'")
for test_file in ROOT.glob("test_*.py"):
    text = test_file.read_text(encoding="utf-8")
    if "1.0.145-rc28" in text:
        test_file.write_text(text.replace("1.0.145-rc28", "1.0.145-rc29"), encoding="utf-8")

history = read("VERSION-HISTORY.md")
if not history.startswith("# Image Draw Bot v1.0.145-rc29"):
    write(
        "VERSION-HISTORY.md",
        "# Image Draw Bot v1.0.145-rc29 — Stability & Planner Validation\n\n"
        "- Ignore stale preview plans with a monotonic preview generation ID so cancelled/settings-invalidated workers cannot overwrite a newer UI state.\n"
        "- Route all centralized background-worker exceptions into the consolidated debug error log while preserving normal session diagnostics.\n"
        "- Quality-gate local ETA learning: incomplete execution, untrusted final-canvas evidence, low accuracy and missing coverage cannot train future timing estimates.\n"
        "- Keep full-detail Preview on the real final planner geometry while retaining its bounded CPU-only preview resource policy.\n"
        "- Preserve existing Paint/browser pre-input target validation, CanvasGuard and auto-recalibration rather than duplicating a second safety system.\n"
        "- Remove rc27/rc28 one-off integration triggers/scripts/workflows before mainline release.\n\n"
        + history,
    )


# ---------------------------------------------------------------------------
# 2. Completed-draw timing sample gate
# ---------------------------------------------------------------------------
write(
    "CompletedDrawLearning.py",
    '''"""Safety gate for profile-local timing learning from completed real drawings.\n\nThe timing model is useful only when a run actually executed the intended work.\nThis module deliberately does not tune rendering settings; it decides whether a\ncompleted run is trustworthy enough to teach future ETA calculations.\n"""\nfrom __future__ import annotations\n\nimport math\nfrom typing import Any\n\n\ndef _number(value: Any, default: float | None = None) -> float | None:\n    try:\n        result = float(value)\n    except (TypeError, ValueError, OverflowError):\n        return default\n    return result if math.isfinite(result) else default\n\n\ndef timing_sample_gate(options: dict[str, Any] | None, *, completed_paths: int = 0,\n                       planned_paths: int = 0) -> dict[str, Any]:\n    """Return whether one real draw may update local ETA calibration.\n\n    Final-canvas quality evidence is fail-closed when it exists: untrusted, low\n    accuracy, or materially incomplete coverage cannot make the timing model\n    learn from a draw that did less useful work than intended. Modes where safe\n    final-canvas capture is unavailable may still learn from a fully completed\n    execution; the returned confidence clearly records that distinction.\n    """\n    opts = options if isinstance(options, dict) else {}\n    if bool(opts.get("test_run")) or bool(opts.get("dry_run_sampled")):\n        return {"allowed": False, "reason": "test/dry-run execution", "confidence": "none"}\n    if bool(opts.get("correction_only_retry")):\n        return {"allowed": False, "reason": "correction-only retry", "confidence": "none"}\n    if opts.get("render_resume_state"):\n        return {"allowed": False, "reason": "resumed execution", "confidence": "none"}\n\n    try:\n        done = max(0, int(completed_paths or 0))\n    except (TypeError, ValueError, OverflowError):\n        done = 0\n    try:\n        planned = max(0, int(planned_paths or 0))\n    except (TypeError, ValueError, OverflowError):\n        planned = 0\n\n    runtime = opts.get("runtime_operation_timing") if isinstance(opts.get("runtime_operation_timing"), dict) else {}\n    has_runtime_work = False\n    for item in runtime.values():\n        if isinstance(item, dict):\n            try:\n                if int(item.get("count") or 0) > 0 or float(item.get("total_seconds") or 0.0) > 0.0:\n                    has_runtime_work = True\n                    break\n            except (TypeError, ValueError, OverflowError):\n                pass\n    has_fill_work = bool(opts.get("fill_regions")) or bool((opts.get("background_fill_plan") or {}).get("enabled") if isinstance(opts.get("background_fill_plan"), dict) else False)\n\n    completion_ratio = 1.0\n    if planned > 0:\n        completion_ratio = min(1.0, done / planned)\n        if completion_ratio < 0.98:\n            return {\n                "allowed": False, "reason": f"incomplete execution ({done}/{planned} paths)",\n                "confidence": "none", "completion_ratio": round(completion_ratio, 4),\n            }\n    elif done <= 0 and not has_runtime_work and not has_fill_work:\n        return {"allowed": False, "reason": "no completed drawing work", "confidence": "none", "completion_ratio": 0.0}\n\n    post = opts.get("post_draw_accuracy_meta") if isinstance(opts.get("post_draw_accuracy_meta"), dict) else None\n    if post and bool(post.get("available")):\n        if not bool(post.get("trusted")):\n            return {\n                "allowed": False, "reason": "final-canvas accuracy evidence is untrusted",\n                "confidence": "none", "completion_ratio": round(completion_ratio, 4),\n            }\n        score = _number(post.get("visual_accuracy_percent"), None)\n        coverage = _number(post.get("actual_coverage_percent"), None)\n        if score is not None and score < 82.0:\n            return {\n                "allowed": False, "reason": f"final-canvas accuracy too low ({score:.1f}/100)",\n                "confidence": "none", "completion_ratio": round(completion_ratio, 4),\n                "accuracy_score": round(score, 2),\n            }\n        if coverage is not None and coverage < 94.0:\n            return {\n                "allowed": False, "reason": f"final-canvas coverage too low ({coverage:.1f}%)",\n                "confidence": "none", "completion_ratio": round(completion_ratio, 4),\n                "accuracy_score": None if score is None else round(score, 2),\n                "coverage_percent": round(coverage, 2),\n            }\n        return {\n            "allowed": True, "reason": "trusted completed draw", "confidence": "trusted-final-canvas",\n            "completion_ratio": round(completion_ratio, 4),\n            "accuracy_score": None if score is None else round(score, 2),\n            "coverage_percent": None if coverage is None else round(coverage, 2),\n        }\n\n    return {\n        "allowed": True, "reason": "completed execution; final-canvas quality evidence unavailable",\n        "confidence": "execution-only", "completion_ratio": round(completion_ratio, 4),\n    }\n''',
)

# Integrate the gate at the single ETA-learning entry point.
replace_once(
    "DrawTimeEstimate.py",
    "from dataclasses import dataclass\nimport math\nfrom typing import Any\n",
    "from dataclasses import dataclass\nimport math\nfrom typing import Any\n\nfrom CompletedDrawLearning import timing_sample_gate\n",
)
replace_once(
    "DrawTimeEstimate.py",
    "        options = plan.get(\"options\") if isinstance(plan.get(\"options\"), dict) else {}\n        predicted_meta=plan.get(\"draw_time_estimate\") or estimate_from_plan(plan)\n",
    "        options = plan.get(\"options\") if isinstance(plan.get(\"options\"), dict) else {}\n        gate=timing_sample_gate(options, completed_paths=completed_paths, planned_paths=int(plan.get(\"count\") or 0))\n        if not gate.get(\"allowed\"):\n            return {\"recorded\": False, \"reason\": gate.get(\"reason\", \"timing sample rejected\"), \"sample_gate\": gate}\n        predicted_meta=plan.get(\"draw_time_estimate\") or estimate_from_plan(plan)\n",
)
replace_once(
    "DrawTimeEstimate.py",
    "        return record_sample(options, predicted, actual_seconds, completed_paths=completed_paths, fill_actions=fill_actions,\n                             operation_counts=operation_counts, operation_runtime=operation_runtime)\n",
    "        result=record_sample(options, predicted, actual_seconds, completed_paths=completed_paths, fill_actions=fill_actions,\n                             operation_counts=operation_counts, operation_runtime=operation_runtime)\n        if isinstance(result,dict):\n            result[\"sample_gate\"]=gate\n        return result\n",
)


# ---------------------------------------------------------------------------
# 3. Preview stale-result guard + centralized worker diagnostics
# ---------------------------------------------------------------------------
replace_once(
    "DrawBot.py",
    "from CrashDiagnostics import (install as install_crash_diagnostics, begin_run_marker,\n                              log_event, previous_run_unclean, clean_exit)\n",
    "from CrashDiagnostics import (install as install_crash_diagnostics, begin_run_marker,\n                              log_event, log_error, previous_run_unclean, clean_exit)\n",
)
replace_once(
    "DrawBot.py",
    "        self.preview_after = None\n        # Preview rendering has its own debounce job. Keeping this separate from\n",
    "        self.preview_after = None\n        # Monotonic generation protects the UI from late preview worker results.\n        self.preview_generation = 0\n        # Preview rendering has its own debounce job. Keeping this separate from\n",
)
replace_once(
    "DrawBot.py",
    "    def _mark_plan_stale(self, message='Settings changed. Press Build preview or Start Drawing when ready.'):\n        DrawBotApp._cancel_after_attr(self,'preview_after')\n        self.needs_plan=False\n",
    "    def _mark_plan_stale(self, message='Settings changed. Press Build preview or Start Drawing when ready.'):\n        DrawBotApp._cancel_after_attr(self,'preview_after')\n        self.preview_generation=int(getattr(self,'preview_generation',0))+1\n        self.needs_plan=False\n",
)
replace_once(
    "DrawBot.py",
    "    def update_plan(self, user_initiated=False, reason='automatic',full_detail=False):\n        self.preview_after=None\n        if self.activity:\n",
    "    def update_plan(self, user_initiated=False, reason='automatic',full_detail=False):\n        self.preview_after=None\n        self.preview_generation=int(getattr(self,'preview_generation',0))+1\n        generation=self.preview_generation\n        if self.activity:\n",
)
replace_once(
    "DrawBot.py",
    "            plan['preview_fallback_used']=bool(used_fallback)\n            log_event(f'Preview planning finished in {plan[\"preview_elapsed_seconds\"]:.3f} s fallback={used_fallback}: {_plan_log_text(plan)}.')\n",
    "            plan['preview_fallback_used']=bool(used_fallback)\n            plan['preview_generation']=generation\n            log_event(f'Preview planning finished in {plan[\"preview_elapsed_seconds\"]:.3f} s fallback={used_fallback}: {_plan_log_text(plan)}.')\n",
)
replace_once(
    "DrawBot.py",
    "        elif kind=='planned':\n            if not isinstance(value,dict) or 'preview' not in value or 'count' not in value or 'estimate' not in value:\n                raise ValueError('The preview worker returned an invalid plan.')\n            self.plan=value\n",
    "        elif kind=='planned':\n            if not isinstance(value,dict) or 'preview' not in value or 'count' not in value or 'estimate' not in value:\n                raise ValueError('The preview worker returned an invalid plan.')\n            if int(value.get('preview_generation',-1))!=int(getattr(self,'preview_generation',0)):\n                log_event(f\"Ignored stale preview result generation={value.get('preview_generation')} current={getattr(self,'preview_generation',0)}.\")\n                return\n            self.plan=value\n",
)
replace_once(
    "DrawBot.py",
    "        # Emergency stop also revokes native mouse permission immediately.\n        DrawBotApp._close_smart_drop_overlay(self,'cancel/stop pressed')\n        self.smart_drop_pending_payload=None\n        self.smart_drop_generation=int(getattr(self,'smart_drop_generation',0))+1\n        mouse=getattr(self,'mouse',None)\n",
    "        # Emergency stop also revokes native mouse permission immediately.\n        DrawBotApp._close_smart_drop_overlay(self,'cancel/stop pressed')\n        self.smart_drop_pending_payload=None\n        self.smart_drop_generation=int(getattr(self,'smart_drop_generation',0))+1\n        self.preview_generation=int(getattr(self,'preview_generation',0))+1\n        mouse=getattr(self,'mouse',None)\n",
)
replace_once(
    "DrawBot.py",
    "                import traceback\n                log_event(f'Worker {activity} failed after {time.monotonic()-started:.3f} s: {error!r}\\n{traceback.format_exc()}')\n                self.events.put(('status',f'Operation failed: {error}'))\n",
    "                log_error(f'Worker {activity} failed after {time.monotonic()-started:.3f} s: {error!r}',\n                          category=f'worker:{activity}', exc_info=True)\n                self.events.put(('status',f'Operation failed: {error}'))\n",
)
replace_once(
    "DrawBot.py",
    "        try:\n            self.worker.start()\n        except Exception:\n            self.worker=None\n            self.set_busy(None)\n            screen_window.restore()\n            raise\n",
    "        try:\n            self.worker.start()\n        except Exception as error:\n            self.worker=None\n            self.set_busy(None)\n            screen_window.restore()\n            log_error(f'Worker {activity} could not start: {error!r}', category='worker-start', exc_info=True)\n            raise\n",
)


# ---------------------------------------------------------------------------
# 4. rc29 focused regressions
# ---------------------------------------------------------------------------
write(
    "test_rc29_stability_planner_validation.py",
    '''from __future__ import annotations\n\nimport unittest\nfrom pathlib import Path\n\nfrom CompletedDrawLearning import timing_sample_gate\nfrom PreviewQuality import full_preview_options\nfrom Version import APP_VERSION\n\n\nclass Rc29StabilityPlannerValidationTests(unittest.TestCase):\n    def test_version(self):\n        self.assertEqual(APP_VERSION, "1.0.145-rc29")\n\n    def test_incomplete_draw_cannot_train_eta(self):\n        result = timing_sample_gate({}, completed_paths=80, planned_paths=100)\n        self.assertFalse(result["allowed"])\n        self.assertIn("incomplete", result["reason"])\n\n    def test_untrusted_final_canvas_cannot_train_eta(self):\n        opts = {"post_draw_accuracy_meta": {\n            "available": True, "trusted": False,\n            "visual_accuracy_percent": 99.0, "actual_coverage_percent": 99.0,\n        }}\n        result = timing_sample_gate(opts, completed_paths=100, planned_paths=100)\n        self.assertFalse(result["allowed"])\n        self.assertIn("untrusted", result["reason"])\n\n    def test_low_quality_or_coverage_cannot_train_eta(self):\n        low_score = {"post_draw_accuracy_meta": {\n            "available": True, "trusted": True,\n            "visual_accuracy_percent": 79.0, "actual_coverage_percent": 99.0,\n        }}\n        low_coverage = {"post_draw_accuracy_meta": {\n            "available": True, "trusted": True,\n            "visual_accuracy_percent": 96.0, "actual_coverage_percent": 90.0,\n        }}\n        self.assertFalse(timing_sample_gate(low_score, completed_paths=100, planned_paths=100)["allowed"])\n        self.assertFalse(timing_sample_gate(low_coverage, completed_paths=100, planned_paths=100)["allowed"])\n\n    def test_trusted_complete_draw_can_train_eta(self):\n        opts = {"post_draw_accuracy_meta": {\n            "available": True, "trusted": True,\n            "visual_accuracy_percent": 95.0, "actual_coverage_percent": 98.0,\n        }}\n        result = timing_sample_gate(opts, completed_paths=100, planned_paths=100)\n        self.assertTrue(result["allowed"])\n        self.assertEqual(result["confidence"], "trusted-final-canvas")\n\n    def test_execution_only_modes_remain_compatible(self):\n        result = timing_sample_gate({}, completed_paths=100, planned_paths=100)\n        self.assertTrue(result["allowed"])\n        self.assertEqual(result["confidence"], "execution-only")\n\n    def test_full_preview_preserves_planner_policy_and_target_geometry(self):\n        options = {\n            "draw_quality": "Pixel Accurate", "drawing_mode": "Shape paths",\n            "drawing_style": "Logo / Flat Graphic", "speed": "Fast",\n            "precision": "High", "cpu_workers": "2", "ram_budget_mb": 512,\n        }\n        out = full_preview_options(options, (640, 400))\n        for key in ("draw_quality", "drawing_mode", "drawing_style", "speed", "precision"):\n            self.assertEqual(out[key], options[key])\n        self.assertEqual(out["_target_area"], (640, 400))\n        self.assertEqual(out["_preview_area"], (640, 400))\n        self.assertFalse(out["_preview_plan"])\n\n    def test_drawbot_contains_generation_guard_and_central_worker_error_log(self):\n        source = Path("DrawBot.py").read_text(encoding="utf-8")\n        self.assertIn("plan['preview_generation']=generation", source)\n        self.assertIn("Ignored stale preview result generation=", source)\n        self.assertIn("category=f'worker:{activity}'", source)\n        self.assertIn("log_error", source)\n\n    def test_eta_entrypoint_uses_sample_gate(self):\n        source = Path("DrawTimeEstimate.py").read_text(encoding="utf-8")\n        self.assertIn("timing_sample_gate", source)\n        self.assertIn('result["sample_gate"]=gate', source)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
)


# ---------------------------------------------------------------------------
# 5. Remove one-off rc27/rc28 integration machinery before mainline release.
# ---------------------------------------------------------------------------
for rel in (
    ".github/rc27-completed-analysis-trigger",
    ".github/rc28-background-remover-trigger",
    ".github/rc28-style-trigger",
    ".github/rc28-style-trigger-v2",
    ".github/scripts/fix_rc27_opacity_flatness.py",
    ".github/scripts/implement_rc27.py",
    ".github/scripts/implement_rc28_background_remover.py",
    ".github/scripts/implement_rc28_styles.py",
    ".github/scripts/implement_rc28_styles_v2.py",
    ".github/workflows/implement-rc27-completed-analysis.yml",
    ".github/workflows/implement-rc28-background-remover.yml",
    ".github/workflows/implement-rc28-styles.yml",
    ".github/workflows/implement-rc28-styles-v2.yml",
):
    (ROOT / rel).unlink(missing_ok=True)

# The integration action is intentionally one-shot. Remove both temporary files
# from the resulting product commit after this script has been loaded.
(ROOT / ".github/scripts/implement_rc29_stability.py").unlink(missing_ok=True)
(ROOT / ".github/workflows/implement-rc29-stability.yml").unlink(missing_ok=True)

print("rc29 stability/planner validation patch applied")
