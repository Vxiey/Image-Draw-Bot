"""Post-run analysis for completed real Image Draw Bot drawings.

Only compact numeric telemetry is persisted. Screenshots, source pixels and image
crops are never written by this module. The report is intended to make later
planner work evidence-driven: it separates speed bottlenecks from quality loss
and never recommends a faster setting when the measured final-canvas quality is
already below the safe quality gate.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from ProfileStorage import safe_profile_key
from RuntimePaths import atomic_write_text, data_dir

REPORT_VERSION = 1
MAX_HISTORY = 40


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _round(value: Any, digits: int = 4):
    number = _float(value, None)
    return None if number is None else round(number, digits)


def _profile(options: dict[str, Any]) -> str:
    return safe_profile_key(options.get("profile_key") or options.get("profile_name") or "generic")


def _report_dir(options: dict[str, Any]) -> Path:
    return data_dir() / "completed-drawings" / _profile(options)


def _accuracy(options: dict[str, Any]) -> dict[str, Any]:
    post = _dict(options.get("post_draw_accuracy_meta"))
    if not post or not post.get("available"):
        return {
            "available": False,
            "trusted": False,
            "score_0_100": None,
            "reason": str(post.get("reason") or "final canvas snapshot was unavailable"),
        }

    # visual_accuracy_percent is the source-relative real-canvas score produced
    # by AccuracyEvaluator. Keep it as the headline score rather than inventing
    # another opaque weighted number. The component scores remain visible below.
    score = _float(post.get("visual_accuracy_percent"), None)
    if score is not None:
        score = max(0.0, min(100.0, score))
    delta = _dict(post.get("delta_e_oklab"))
    return {
        "available": True,
        "trusted": bool(post.get("trusted")),
        "trust": str(post.get("feedback_trust") or "none"),
        "confidence_percent": _round(post.get("confidence_percent"), 2),
        "score_0_100": _round(score, 2),
        "visual_accuracy_percent": _round(post.get("visual_accuracy_percent"), 2),
        "source_pixel_accuracy_percent": _round(post.get("source_pixel_accuracy_percent"), 2),
        "perceptual_color_accuracy_percent": _round(post.get("perceptual_color_accuracy_percent"), 2),
        "luminance_accuracy_percent": _round(post.get("luminance_accuracy_percent"), 2),
        "hue_accuracy_percent": _round(post.get("hue_accuracy_percent"), 2),
        "edge_accuracy_percent": _round(post.get("edge_accuracy_percent"), 2),
        "actual_coverage_percent": _round(post.get("actual_coverage_percent"), 2),
        "unexpected_ink_percent": _round(post.get("unexpected_ink_percent"), 2),
        "actual_vs_simulated_visual_percent": _round(post.get("actual_vs_simulated_visual_percent"), 2),
        "actual_vs_quantized_target_visual_percent": _round(post.get("actual_vs_quantized_target_visual_percent"), 2),
        "mean_delta_e_oklab": _round(delta.get("mean_delta_e_oklab"), 3),
        "p95_delta_e_oklab": _round(delta.get("p95_delta_e_oklab"), 3),
        "severe_error_pixels_percent": _round(delta.get("severe_error_pixels_percent"), 2),
        "reasons": list(post.get("reasons") or ()),
        "method": str(post.get("method") or "safe final canvas snapshot"),
    }


def _operation_breakdown(options: dict[str, Any], actual_seconds: float) -> dict[str, Any]:
    runtime = _dict(options.get("runtime_operation_timing"))
    rows: dict[str, dict[str, Any]] = {}
    measured_total = 0.0
    for kind, raw in runtime.items():
        item = _dict(raw)
        count = max(0, _int(item.get("count"), 0))
        total = max(0.0, _float(item.get("total_seconds"), 0.0) or 0.0)
        average = max(0.0, _float(item.get("average_seconds"), 0.0) or 0.0)
        if average <= 0.0 and count:
            average = total / count
        measured_total += total
        rows[str(kind)] = {
            "count": count,
            "total_seconds": round(total, 5),
            "average_seconds": round(average, 6),
            "share_of_actual_percent": round(100.0 * total / max(.001, actual_seconds), 2),
        }
    unclassified = max(0.0, float(actual_seconds) - measured_total)
    return {
        "operations": rows,
        "measured_operation_seconds": round(measured_total, 5),
        "measured_share_percent": round(100.0 * measured_total / max(.001, actual_seconds), 2),
        "unclassified_seconds": round(unclassified, 5),
        "unclassified_share_percent": round(100.0 * unclassified / max(.001, actual_seconds), 2),
    }


def _brush(options: dict[str, Any]) -> dict[str, Any]:
    browser = _dict(options.get("browser_brush_plan"))
    adaptive = _dict(options.get("adaptive_brush_meta"))
    if not adaptive:
        adaptive = _dict(options.get("adaptive_brush_plan_meta"))
    runtime = _dict(options.get("adaptive_brush_runtime_meta"))
    auto = _dict(options.get("auto_brush_width_meta"))
    return {
        "requested": options.get("brush_px_requested"),
        "effective_physical_px": _int(options.get("brush_px"), 0) or None,
        "auto_decision": auto,
        "gartic_requested_level": browser.get("requested_level"),
        "gartic_effective_level": browser.get("effective_level"),
        "physical_ladder_px": list(browser.get("nominal_sizes") or ()),
        "verified_levels": list(browser.get("verified_levels") or ()),
        "used_physical_sizes_px": list(adaptive.get("used_brush_sizes") or runtime.get("sizes") or ()),
        "planned_switches": _int(adaptive.get("planned_brush_switches"), 0),
        "runtime_switches": _int(runtime.get("switches"), 0),
        "path_counts": dict(adaptive.get("brush_path_counts") or {}),
        "reason_counts": dict(adaptive.get("brush_reason_counts") or {}),
        "image_demand": dict(adaptive.get("image_brush_demand") or {}),
    }


def _opacity(options: dict[str, Any]) -> dict[str, Any]:
    plan = _dict(options.get("gartic_opacity_plan"))
    runtime = _dict(options.get("gartic_opacity_runtime_meta"))
    return {
        "requested": options.get("gartic_opacity", "Auto"),
        "selected_percent": plan.get("selected_percent", options.get("gartic_opacity_percent")),
        "confidence": _round(plan.get("confidence"), 4),
        "auto_reason": plan.get("reason"),
        "control_verified": bool(plan.get("target_position")),
        "runtime_applied": bool(runtime.get("applied")),
        "runtime_seconds": _round(runtime.get("seconds"), 5),
    }


def _recommendations(*, options: dict[str, Any], actual: float, predicted: float,
                     accuracy: dict[str, Any], operations: dict[str, Any], brush: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ops = _dict(operations.get("operations"))
    score = _float(accuracy.get("score_0_100"), None)
    coverage = _float(accuracy.get("actual_coverage_percent"), None)
    trusted = bool(accuracy.get("trusted"))

    def add(priority: int, code: str, title: str, reason: str, action: str):
        out.append({"priority": int(priority), "code": code, "title": title, "reason": reason, "action": action})

    # Quality gates come first. Never tell a future optimizer to trade more quality
    # away when the real canvas already shows a quality or coverage problem.
    quality_limited = False
    if trusted and score is not None and score < 82.0:
        quality_limited = True
        add(100, "protect_accuracy", "Protect accuracy before more speed",
            f"Measured final-canvas accuracy is {score:.1f}/100.",
            "Prefer correction/detail recovery, smaller protected-detail brushes and better color matching before removing work.")
    if trusted and coverage is not None and coverage < 94.0:
        quality_limited = True
        add(96, "coverage_gap", "Recover missing coverage",
            f"Actual canvas coverage is {coverage:.1f}%.",
            "Inspect skipped/clipped regions and correction passes; do not raise simplification until coverage recovers.")

    estimate_error = (actual - predicted) / max(1.0, actual)
    if abs(estimate_error) >= .12:
        direction = "underestimated" if actual > predicted else "overestimated"
        add(86, "eta_model", "Refine the draw-time model",
            f"ETA {direction} this run by {abs(estimate_error)*100.0:.1f}% ({predicted:.1f}s predicted vs {actual:.1f}s actual).",
            "Use this run's per-operation timings to update the profile-local cost EMA before the next plan.")

    tool = _dict(ops.get("tool_change")); palette = _dict(ops.get("palette_change")); color = _dict(ops.get("color_change"))
    brush_switches = max(_int(brush.get("runtime_switches"), 0), _int(brush.get("planned_switches"), 0))
    tool_share = _float(tool.get("share_of_actual_percent"), 0.0) or 0.0
    if brush_switches >= 10 or tool_share >= 6.0:
        add(78, "brush_switch_churn", "Reduce brush/tool switch churn",
            f"Brush/tool switching used {tool_share:.1f}% of measured time with {brush_switches} brush switch(es).",
            "Increase brush hysteresis and group adjacent safe regions by brush size when the saved path time exceeds switch cost.")

    color_share = (_float(palette.get("share_of_actual_percent"), 0.0) or 0.0) + (_float(color.get("share_of_actual_percent"), 0.0) or 0.0)
    color_count = _int(palette.get("count"), 0) + _int(color.get("count"), 0)
    if color_count >= 10 and color_share >= 5.0:
        add(74, "color_batching", "Batch colors more aggressively",
            f"{color_count} color selections consumed about {color_share:.1f}% of actual time.",
            "Prefer finishing nearby same-color regions before switching unless deadline/importance ordering gives a larger quality gain.")

    fill = _dict(ops.get("fill_action")); fill_share = _float(fill.get("share_of_actual_percent"), 0.0) or 0.0
    flat = str(_dict(brush.get("image_demand")).get("classification") or "") == "flat-shape"
    if flat and _int(fill.get("count"), 0) == 0 and not quality_limited:
        add(72, "safe_fill_opportunity", "Look for more safe Fill regions",
            "The brush planner classified the image as flat-shape but no measured Fill action was used.",
            "Compare contour+Fill cost with region-stroke cost and use Fill only for closed, verified regions where it wins in real time.")
    elif fill_share >= 18.0:
        add(70, "fill_overhead", "Recheck Fill economics",
            f"Fill actions consumed about {fill_share:.1f}% of measured draw time.",
            "Avoid small Fill regions whose contour/tool/verification overhead exceeds direct region strokes.")

    unclassified_share = _float(operations.get("unclassified_share_percent"), 0.0) or 0.0
    if unclassified_share >= 25.0:
        add(68, "telemetry_gap", "Instrument the remaining runtime",
            f"{unclassified_share:.1f}% of the completed draw is still outside typed operation timings.",
            "Add timing around prelude/travel/fill verification/UI waits so planner costs are learned from the real bottleneck.")

    if trusted and score is not None and score >= 92.0 and not quality_limited and actual > 10.0:
        add(45, "safe_speed_headroom", "Use quality headroom carefully",
            f"Measured accuracy is {score:.1f}/100 with trusted final-canvas evidence.",
            "Test broader brushes or cheaper ordering only where the simulator predicts no protected-detail loss; reject changes that lower the real score materially.")

    out.sort(key=lambda row: (-int(row["priority"]), str(row["code"])))
    return out[:8]


def _efficiency_score(actual: float, predicted: float, accuracy: dict[str, Any], operations: dict[str, Any]) -> float:
    eta = 1.0 - min(1.0, abs(actual - predicted) / max(1.0, actual))
    classified = min(1.0, (_float(operations.get("measured_share_percent"), 0.0) or 0.0) / 90.0)
    acc = _float(accuracy.get("score_0_100"), None)
    quality = 1.0 if acc is None else max(0.0, min(1.0, acc / 100.0))
    return round(100.0 * (.48 * quality + .32 * eta + .20 * classified), 2)


def build_completed_drawing_report(plan: dict[str, Any], actual_seconds: float, *, completed_paths: int = 0) -> dict[str, Any]:
    options = _dict(plan.get("options"))
    actual = max(.001, float(actual_seconds or 0.0))
    estimate = _dict(plan.get("draw_time_estimate"))
    predicted = max(.001, _float(estimate.get("projected_seconds"), None)
                    or _float(estimate.get("preview_seconds"), None)
                    or _float(plan.get("raw_execution_estimate_seconds"), None)
                    or _float(plan.get("estimate"), 0.001) or .001)
    accuracy = _accuracy(options)
    operations = _operation_breakdown(options, actual)
    brush = _brush(options)
    opacity = _opacity(options)
    recommendations = _recommendations(options=options, actual=actual, predicted=predicted,
                                       accuracy=accuracy, operations=operations, brush=brush)
    return {
        "version": REPORT_VERSION,
        "created_at": time.time(),
        "profile_key": _profile(options),
        "profile_name": str(options.get("profile_name") or ""),
        "drawing_mode": str(options.get("drawing_mode") or options.get("mode") or ""),
        "render_preset": str(options.get("render_preset") or ""),
        "draw_quality": str(options.get("draw_quality") or ""),
        "speed": str(options.get("speed") or ""),
        "precision": str(options.get("precision") or ""),
        "completed_paths": max(0, int(completed_paths or 0)),
        "predicted_seconds": round(predicted, 4),
        "actual_seconds": round(actual, 4),
        "eta_error_seconds": round(actual - predicted, 4),
        "eta_error_percent_of_actual": round((actual - predicted) * 100.0 / max(1.0, actual), 2),
        "accuracy": accuracy,
        "drawing_accuracy_score_0_100": accuracy.get("score_0_100"),
        "operations": operations,
        "brush": brush,
        "opacity": opacity,
        "efficiency_score_0_100": _efficiency_score(actual, predicted, accuracy, operations),
        "recommendations": recommendations,
        "privacy": "Metrics only. No source image, final canvas screenshot, crop, thumbnail or pixel buffer is persisted.",
    }


def _load_history(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
    except (OSError, ValueError, TypeError):
        pass
    return []


def _text_report(report: dict[str, Any]) -> str:
    acc = _dict(report.get("accuracy")); ops = _dict(report.get("operations")); brush = _dict(report.get("brush"))
    lines = [
        "Image Draw Bot — Completed Drawing Analysis",
        f"Profile: {report.get('profile_name') or report.get('profile_key')}",
        f"Mode: {report.get('drawing_mode')} · preset {report.get('render_preset')} · quality {report.get('draw_quality')}",
        f"Time: predicted {report.get('predicted_seconds')}s · actual {report.get('actual_seconds')}s · error {report.get('eta_error_percent_of_actual')}% of actual",
        f"Paths: {report.get('completed_paths')}",
        f"Drawing Accuracy Score: {acc.get('score_0_100') if acc.get('score_0_100') is not None else 'unavailable'}/100 · trust {acc.get('trust','none')}",
        f"Coverage: {acc.get('actual_coverage_percent')}% · edge {acc.get('edge_accuracy_percent')}% · color {acc.get('perceptual_color_accuracy_percent')}%",
        f"Brush: requested={brush.get('requested')} · Gartic level={brush.get('gartic_effective_level')} · physical={brush.get('effective_physical_px')}px · switches={max(_int(brush.get('runtime_switches')), _int(brush.get('planned_switches')))}",
        f"Typed runtime coverage: {ops.get('measured_share_percent')}% · unclassified {ops.get('unclassified_share_percent')}%",
        "",
        "Recommended next improvements:",
    ]
    for index, item in enumerate(report.get("recommendations") or (), 1):
        lines.append(f"{index}. {item.get('title')}: {item.get('reason')} Next: {item.get('action')}")
    lines.extend(["", str(report.get("privacy") or "")])
    return "\n".join(lines).rstrip() + "\n"


def record_completed_drawing(plan: dict[str, Any], actual_seconds: float, *, completed_paths: int = 0) -> dict[str, Any]:
    options = _dict(plan.get("options"))
    report = build_completed_drawing_report(plan, actual_seconds, completed_paths=completed_paths)
    directory = _report_dir(options)
    directory.mkdir(parents=True, exist_ok=True)
    latest_json = directory / "latest.json"
    latest_txt = directory / "latest.txt"
    history_path = directory / "history.json"
    history = _load_history(history_path)
    history.append(report)
    history = history[-MAX_HISTORY:]
    atomic_write_text(latest_json, json.dumps(report, ensure_ascii=False, indent=2))
    atomic_write_text(latest_txt, _text_report(report))
    atomic_write_text(history_path, json.dumps(history, ensure_ascii=False, indent=2))
    result = dict(report)
    result.update({
        "recorded": True,
        "latest_json_path": str(latest_json),
        "latest_text_path": str(latest_txt),
        "history_path": str(history_path),
        "history_entries": len(history),
    })
    options["completed_drawing_analysis_meta"] = result
    return result
