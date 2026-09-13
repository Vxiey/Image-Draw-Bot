"""Safety gate for profile-local timing learning from completed real drawings.

The timing model is useful only when a run actually executed the intended work.
This module deliberately does not tune rendering settings; it decides whether a
completed run is trustworthy enough to teach future ETA calculations.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def timing_sample_gate(options: dict[str, Any] | None, *, completed_paths: int = 0,
                       planned_paths: int = 0) -> dict[str, Any]:
    """Return whether one real draw may update local ETA calibration.

    Final-canvas quality evidence is fail-closed when it exists: untrusted, low
    accuracy, or materially incomplete coverage cannot make the timing model
    learn from a draw that did less useful work than intended. Modes where safe
    final-canvas capture is unavailable may still learn from a fully completed
    execution; the returned confidence clearly records that distinction.
    """
    opts = options if isinstance(options, dict) else {}
    if bool(opts.get("test_run")) or bool(opts.get("dry_run_sampled")):
        return {"allowed": False, "reason": "test/dry-run execution", "confidence": "none"}
    if bool(opts.get("correction_only_retry")):
        return {"allowed": False, "reason": "correction-only retry", "confidence": "none"}
    if opts.get("render_resume_state"):
        return {"allowed": False, "reason": "resumed execution", "confidence": "none"}

    try:
        done = max(0, int(completed_paths or 0))
    except (TypeError, ValueError, OverflowError):
        done = 0
    try:
        planned = max(0, int(planned_paths or 0))
    except (TypeError, ValueError, OverflowError):
        planned = 0

    runtime = opts.get("runtime_operation_timing") if isinstance(opts.get("runtime_operation_timing"), dict) else {}
    has_runtime_work = False
    for item in runtime.values():
        if isinstance(item, dict):
            try:
                if int(item.get("count") or 0) > 0 or float(item.get("total_seconds") or 0.0) > 0.0:
                    has_runtime_work = True
                    break
            except (TypeError, ValueError, OverflowError):
                pass
    has_fill_work = bool(opts.get("fill_regions")) or bool((opts.get("background_fill_plan") or {}).get("enabled") if isinstance(opts.get("background_fill_plan"), dict) else False)

    completion_ratio = 1.0
    if planned > 0:
        completion_ratio = min(1.0, done / planned)
        if completion_ratio < 0.98:
            return {
                "allowed": False, "reason": f"incomplete execution ({done}/{planned} paths)",
                "confidence": "none", "completion_ratio": round(completion_ratio, 4),
            }
    elif done <= 0 and not has_runtime_work and not has_fill_work:
        return {"allowed": False, "reason": "no completed drawing work", "confidence": "none", "completion_ratio": 0.0}

    post = opts.get("post_draw_accuracy_meta") if isinstance(opts.get("post_draw_accuracy_meta"), dict) else None
    if post and bool(post.get("available")):
        if not bool(post.get("trusted")):
            return {
                "allowed": False, "reason": "final-canvas accuracy evidence is untrusted",
                "confidence": "none", "completion_ratio": round(completion_ratio, 4),
            }
        score = _number(post.get("visual_accuracy_percent"), None)
        coverage = _number(post.get("actual_coverage_percent"), None)
        if score is not None and score < 82.0:
            return {
                "allowed": False, "reason": f"final-canvas accuracy too low ({score:.1f}/100)",
                "confidence": "none", "completion_ratio": round(completion_ratio, 4),
                "accuracy_score": round(score, 2),
            }
        if coverage is not None and coverage < 94.0:
            return {
                "allowed": False, "reason": f"final-canvas coverage too low ({coverage:.1f}%)",
                "confidence": "none", "completion_ratio": round(completion_ratio, 4),
                "accuracy_score": None if score is None else round(score, 2),
                "coverage_percent": round(coverage, 2),
            }
        return {
            "allowed": True, "reason": "trusted completed draw", "confidence": "trusted-final-canvas",
            "completion_ratio": round(completion_ratio, 4),
            "accuracy_score": None if score is None else round(score, 2),
            "coverage_percent": None if coverage is None else round(coverage, 2),
        }

    return {
        "allowed": True, "reason": "completed execution; final-canvas quality evidence unavailable",
        "confidence": "execution-only", "completion_ratio": round(completion_ratio, 4),
    }
