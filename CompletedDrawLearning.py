"""Safety gate for profile-local timing learning from completed real drawings.

The timing model is useful only when a run actually executed the intended work.
This module deliberately does not tune rendering settings; it decides whether a
completed run is trustworthy enough to teach future ETA calculations.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any, default: float | None = None) -> float | None:
    if type(value) not in (int, float):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def completed_fill_actions(options: dict[str, Any] | None) -> int:
    """Count delivered bucket clicks, excluding plans and dry-run simulations."""
    opts = options if isinstance(options, dict) else {}
    report = opts.get('runtime_safety_report')
    if not isinstance(report, dict) or report.get('mode') == 'dry-run':
        return 0
    fills = report.get('fills')
    if not isinstance(fills, dict):
        return 0
    counts = [fills.get(name, 0) for name in ('background_fill_clicks', 'better_fill_clicks')]
    if any(type(count) is not int or not 0 <= count <= 1_000_000_000 for count in counts):
        return 0
    return sum(counts)


def has_completed_drawing_work(options: dict[str, Any] | None, completed_paths: int = 0) -> bool:
    """Whether real drawing, rather than setup/planning, has been measured."""
    opts = options if isinstance(options, dict) else {}
    if type(completed_paths) is int and 0 < completed_paths <= 1_000_000_000:
        return True
    if completed_fill_actions(opts) > 0:
        return True
    runtime = opts.get('runtime_operation_timing')
    if not isinstance(runtime, dict):
        return False
    drawing_operations = {'stroke', 'path', 'drag', 'mouse_drag', 'dot', 'point',
                          'short_stroke', 'long_stroke', 'outline', 'fill', 'fill_action', 'bucket_fill'}
    for kind, item in runtime.items():
        if kind in drawing_operations and isinstance(item, dict):
            count = item.get('count', 0)
            elapsed = _number(item.get('total_seconds'), 0.0)
            if type(count) is int and 0 < count <= 1_000_000_000 and elapsed > 0.0:
                return True
    return False


def paused_learning_reason(options: dict[str, Any] | None) -> str | None:
    """Manual idle and resume countdowns are not device performance samples."""
    opts = options if isinstance(options, dict) else {}
    count = opts.get('execution_pause_count', 0)
    seconds = opts.get('execution_pause_seconds', 0.0)
    if (type(count) is not int or count < 0 or _number(seconds) is None or seconds < 0):
        return 'invalid execution pause measurement'
    if count or seconds:
        return 'manually paused execution'
    return None


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
    pause_reason = paused_learning_reason(opts)
    if pause_reason:
        return {"allowed": False, "reason": pause_reason, "confidence": "none"}

    if any(type(value) is not int or not 0 <= value <= 1_000_000_000
           for value in (completed_paths, planned_paths)):
        return {"allowed": False, "reason": "invalid execution counters", "confidence": "none"}
    done, planned = completed_paths, planned_paths

    completion_ratio = 1.0
    if planned > 0:
        completion_ratio = min(1.0, done / planned)
        if completion_ratio < 0.98:
            return {
                "allowed": False, "reason": f"incomplete execution ({done}/{planned} paths)",
                "confidence": "none", "completion_ratio": round(completion_ratio, 4),
            }
    elif not has_completed_drawing_work(opts, done):
        return {"allowed": False, "reason": "no completed drawing work", "confidence": "none", "completion_ratio": 0.0}

    post = opts.get("post_draw_accuracy_meta") if isinstance(opts.get("post_draw_accuracy_meta"), dict) else None
    if post and 'available' in post and type(post['available']) is not bool:
        return {"allowed": False, "reason": "final-canvas availability flag is invalid", "confidence": "none"}
    if post and post.get('available') not in (None, False):
        from SafeCanvasSnapshotScoring import trusted_snapshot_evidence
        if (post.get('available') is not True or post.get("trusted") is not True
                or not trusted_snapshot_evidence(post)):
            return {
                "allowed": False, "reason": "final-canvas accuracy evidence is untrusted",
                "confidence": "none", "completion_ratio": round(completion_ratio, 4),
            }
        score = _number(post.get("visual_accuracy_percent"), None)
        coverage = _number(post.get("actual_coverage_percent"), None)
        if (score is None or coverage is None or not 0 <= score <= 100 or not 0 <= coverage <= 100
                or type(post.get('visual_accuracy_percent')) not in (int, float)
                or type(post.get('actual_coverage_percent')) not in (int, float)):
            return {"allowed": False, "reason": "final-canvas accuracy metrics are incomplete or invalid",
                    "confidence": "none", "completion_ratio": round(completion_ratio, 4)}
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
