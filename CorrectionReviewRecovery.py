"""Step 15 — correction review and guarded recovery actions.

This module is UI/state logic only.  It turns Step 13 real-result metrics and
Step 14 correction metadata into a small review card plus explicit user actions.
It stores no screenshots, crops, thumbnails, hashes or source/canvas pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import math
from SafeCanvasSnapshotScoring import trusted_snapshot_evidence

REVIEW_VERSION = 1
TRUSTED_LEVELS = {"high", "medium"}
IMAGE_DATA_WORDS = ("screenshot", "thumbnail", "crop", "hash", "image_data", "canvas_data", "raw_pixels", "pixel_array")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _trust(meta: dict[str, Any]) -> str:
    return str(meta.get("feedback_trust") or meta.get("post_correction_trust") or "none").strip().lower()


def _gate(options: dict[str, Any]) -> float | None:
    acceptance = _as_dict(options.get("auto_tuner_acceptance_meta"))
    gates = _as_dict(acceptance.get("gates"))
    return _float(gates.get("visual_accuracy_min_percent"), None)


def _actual_visual(options: dict[str, Any]) -> float | None:
    corr = _as_dict(options.get("post_draw_correction_meta"))
    value = _float(corr.get("post_correction_visual_accuracy_percent"), None)
    if value is not None:
        return value
    post = _as_dict(options.get("post_draw_accuracy_meta"))
    return _float(post.get("visual_accuracy_percent"), None)


def _actual_coverage(options: dict[str, Any]) -> float | None:
    corr = _as_dict(options.get("post_draw_correction_meta"))
    value = _float(corr.get("post_correction_actual_coverage_percent"), None)
    if value is not None:
        return value
    post = _as_dict(options.get("post_draw_accuracy_meta"))
    return _float(post.get("actual_coverage_percent"), None)


@dataclass(frozen=True)
class ReviewAction:
    label: str
    enabled: bool
    reason: str
    requires_user_click: bool = True
    requires_safety_chain: bool = True
    native_input: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CorrectionReviewState:
    version: int
    state: str
    tone: str
    title: str
    summary: str
    reason: str
    next_step: str
    real_result: dict[str, Any]
    correction: dict[str, Any]
    actions: dict[str, dict[str, Any]]
    history: dict[str, Any] | None = None
    stores_image_data: bool = False
    capture_pixels_persisted: bool = False
    image_pixels_persisted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compact_real(post: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "available", "trusted", "feedback_trust", "scoring_state", "confidence_percent",
        "visual_accuracy_percent", "source_pixel_accuracy_percent", "perceptual_color_accuracy_percent",
        "actual_coverage_percent", "actual_vs_simulated_visual_percent", "unexpected_ink_percent",
        "blank_canvas", "visual_gate_passed", "deadline_safe", "summary", "reason",
    )
    return {k: post.get(k) for k in keys if post.get(k) is not None}


def _compact_correction(corr: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "enabled", "safe", "reason", "correction_paths", "selected_correction_pixels", "missing_pixels",
        "wrong_color_pixels", "corrected_colors", "estimated_seconds", "executed_paths", "executed_colors",
        "stopped_early", "post_correction_visual_accuracy_percent", "post_correction_actual_coverage_percent",
        "post_correction_trust", "post_correction_confidence_percent", "stores_image_data",
    )
    return {k: corr.get(k) for k in keys if corr.get(k) is not None}


def build_correction_review_state(options: dict[str, Any] | None, *, can_snapshot: bool = False,
                                  strict_safety_ready: bool = False,
                                  full_start_unlocked: bool = False) -> dict[str, Any]:
    """Return a compact state object for the post-draw review UI.

    ``can_snapshot``, ``strict_safety_ready`` and ``full_start_unlocked`` are UI
    context hints.  They never relax safety; they only determine whether buttons
    should be enabled or shown as a guided next step.
    """
    options = options if isinstance(options, dict) else {}
    post = _as_dict(options.get("post_draw_accuracy_meta"))
    corr = _as_dict(options.get("post_draw_correction_meta"))
    gate = _gate(options)
    visual = _actual_visual(options)
    coverage = _actual_coverage(options)
    corr_enabled = corr.get("enabled") is True
    corr_safe = corr.get("safe", True) is True
    if any(key in corr and type(corr[key]) is not bool for key in ('enabled', 'safe', 'stopped_early')):
        corr_safe = False
    executed = _int(corr.get("executed_paths", 0), 0)
    planned = _int(corr.get("correction_paths", 0), 0)
    stopped = bool(corr.get("stopped_early"))
    post_available = post.get("available") is True
    trusted = trusted_snapshot_evidence(post)
    after_trust = str(corr.get('post_correction_trust') or '').strip().lower()
    after_untrusted = 'post_correction_trust' in corr and after_trust not in TRUSTED_LEVELS
    for key in ('post_correction_visual_accuracy_percent', 'post_correction_actual_coverage_percent',
                'post_correction_confidence_percent'):
        if key in corr and corr[key] is not None:
            value = _float(corr[key])
            if isinstance(corr[key], bool) or value is None or not 0 <= value <= 100:
                after_untrusted = True
    low_trust = (post_available and not trusted) or after_untrusted
    blank = bool(post.get("blank_canvas"))
    unexpected = (_float(post.get("unexpected_ink_percent"), 0.0) or 0.0) > 18.0
    below_visual_gate = bool(gate is not None and visual is not None and visual < gate)
    below_coverage_gate = bool(coverage is not None and coverage < 96.0)
    needs_more = bool(below_visual_gate or below_coverage_gate or stopped or (planned and executed < planned))

    if not post and not corr:
        state = "no_result"; tone = "muted"; title = "No completed real drawing yet"
        summary = "Run a real drawing to get result verification and correction review."
        reason = "no Step 13/14 metadata"
        next_step = "Complete the normal setup chain, then Start Drawing."
    elif post and not post_available:
        state = "verification_unavailable"; tone = "warning"; title = "Real-result verification unavailable"
        reason = str(post.get("reason") or corr.get("reason") or "safe canvas snapshot was unavailable")
        summary = "Image Draw Bot could not score the final canvas, so it did not trust automatic correction decisions."
        next_step = "Inspect the canvas manually. Use full retry only after re-running the safety chain."
    elif low_trust or blank or unexpected or not corr_safe:
        state = "manual_review_required"; tone = "danger"; title = "Manual review required"
        reason = ("post-correction verification was not trusted" if after_untrusted else
                  str(corr.get("reason") or post.get("reason") or ("blank canvas" if blank else "snapshot trust was too low")))
        summary = "Automatic correction is blocked because the captured result is not safe enough to patch."
        next_step = "Inspect the target canvas, then run normal Safety preflight / Dry run before retrying."
    elif corr_enabled and executed > 0:
        if needs_more:
            state = "corrected_partial"; tone = "warning"; title = "Correction pass ran, but more review is useful"
            reason = str(corr.get("reason") or "correction was bounded by safety/time caps")
            summary = f"Correction executed {executed}/{max(planned, executed)} path(s) without saving image data."
            next_step = "Run a correction-only retry only if the canvas still visibly needs it and the safety chain is current."
        else:
            state = "corrected_pass"; tone = "success"; title = "Correction completed"
            reason = str(corr.get("reason") or "post-draw correction completed")
            summary = f"Correction executed {executed}/{max(planned, executed)} path(s) and the result is within review gates."
            next_step = "No retry is needed unless the target canvas still looks wrong."
    elif corr and corr.get("reason"):
        reason = str(corr.get("reason"))
        if not needs_more and trusted and reason.strip().lower() == 'real result is already within correction gates':
            state = "within_gates"; tone = "success"; title = "Result is within correction gates"
            summary = "Correction was skipped because the verified result already met the configured gates."
            next_step = "No action needed."
        else:
            state = "correction_skipped"; tone = "warning"; title = "Correction skipped"
            summary = "Correction did not run. The reason is shown so the next action is explicit."
            next_step = "Fix the shown blocker or use full retry through the normal safety chain."
    elif needs_more:
        state = "correction_available"; tone = "warning"; title = "Correction may be useful"
        reason = "verified result is below one or more correction gates"
        summary = "The final result was trusted enough to score and appears below the configured quality/coverage gate."
        next_step = "Use correction-only retry with current safety gates, or full retry if geometry/color setup changed."
    else:
        state = "verified_clean"; tone = "success"; title = "Verified result looks clean"
        reason = "real result is within review gates"
        summary = "Real-result verification did not find a correction-worthy problem."
        next_step = "No action needed."

    if "reason" not in locals():
        reason = str(corr.get("reason") or post.get("reason") or "")

    correction_retry_allowed = bool(
        can_snapshot is True and trusted and not blank and not unexpected and not bool(options.get("paint_current_color"))
        and state in {"corrected_partial", "correction_skipped", "correction_available"}
    )
    correction_reason = "available after current safety gates" if correction_retry_allowed else "not available for the current review state"
    if correction_retry_allowed and strict_safety_ready is not True:
        correction_reason = "run the normal setup safety chain first"
    elif correction_retry_allowed and full_start_unlocked is not True:
        correction_reason = "press Unlock full drawing first; correction-only still sends native input"

    full_retry_allowed = bool(options) and state != "no_result"
    full_retry_reason = "uses current image/settings but still requires the normal safety chain" if full_retry_allowed else "no completed plan to retry yet"

    reverify_allowed = bool(can_snapshot is True and options and state != "no_result")
    reverify_reason = "available while the same target canvas is visible" if reverify_allowed else "requires snapshot support and a completed draw"

    actions = {
        "retry_correction_only": ReviewAction(
            "Retry correction only", bool(correction_retry_allowed and strict_safety_ready is True and full_start_unlocked is True), correction_reason,
            requires_safety_chain=True, native_input=True).as_dict(),
        "retry_full_drawing": ReviewAction(
            "Retry full drawing", full_retry_allowed, full_retry_reason,
            requires_safety_chain=True, native_input=True).as_dict(),
        "rerun_result_verification": ReviewAction(
            "Re-check result", bool(reverify_allowed and strict_safety_ready is True), reverify_reason,
            requires_safety_chain=True, native_input=False).as_dict(),
    }
    history_meta = _as_dict(options.get('correction_history_meta'))
    if not history_meta:
        try:
            from CorrectionHistory import load_correction_history
            history_meta = load_correction_history(options, limit=3)
        except Exception:
            history_meta = {}
    review = CorrectionReviewState(
        version=REVIEW_VERSION, state=state, tone=tone, title=title, summary=summary, reason=reason,
        next_step=next_step, real_result=_compact_real(post), correction=_compact_correction(corr), actions=actions,
        history=history_meta or None)
    return review.as_dict()


def format_correction_review(state: dict[str, Any] | None) -> str:
    state = state if isinstance(state, dict) else {}
    if not state:
        return "Correction Review: unavailable."
    lines = [f"Correction Review: {state.get('title', 'Unknown')}"]
    summary = str(state.get("summary") or "").strip()
    if summary:
        lines.append(summary)
    reason = str(state.get("reason") or "").strip()
    if reason:
        lines.append("Reason: " + reason)
    real = _as_dict(state.get("real_result"))
    if real:
        bits = []
        if real.get("feedback_trust") is not None:
            bits.append(f"trust {real.get('feedback_trust')}")
        if real.get("confidence_percent") is not None:
            bits.append(f"confidence {float(real.get('confidence_percent') or 0):.0f}%")
        if real.get("visual_accuracy_percent") is not None:
            bits.append(f"Visual {float(real.get('visual_accuracy_percent') or 0):.1f}%")
        if real.get("actual_coverage_percent") is not None:
            bits.append(f"Coverage {float(real.get('actual_coverage_percent') or 0):.1f}%")
        if bits:
            lines.append("Real result: " + " · ".join(bits))
    corr = _as_dict(state.get("correction"))
    if corr:
        bits = []
        if corr.get("executed_paths") is not None or corr.get("correction_paths") is not None:
            bits.append(f"paths {int(corr.get('executed_paths', 0) or 0)}/{int(corr.get('correction_paths', 0) or 0)}")
        if corr.get("selected_correction_pixels") is not None:
            bits.append(f"pixels {int(corr.get('selected_correction_pixels', 0) or 0)}")
        if corr.get("post_correction_visual_accuracy_percent") is not None:
            bits.append(f"post Visual {float(corr.get('post_correction_visual_accuracy_percent') or 0):.1f}%")
        if corr.get("stopped_early"):
            bits.append("stopped by reserve")
        if bits:
            lines.append("Correction: " + " · ".join(bits))
    history = _as_dict(state.get("history"))
    summary = _as_dict(history.get("summary"))
    if summary.get("entry_count"):
        avg = summary.get("average_visual_delta")
        text = f"History: {int(summary.get('entry_count') or 0)} saved"
        if avg is not None:
            text += f" · recent Visual {float(avg):+.1f} pp"
        lines.append(text)
    actions = _as_dict(state.get("actions"))
    if actions:
        labels = []
        for key in ("retry_correction_only", "rerun_result_verification", "retry_full_drawing"):
            item = _as_dict(actions.get(key))
            if not item:
                continue
            labels.append(("✓ " if item.get("enabled") else "· ") + str(item.get("label") or key) + ("" if item.get("enabled") else f" — {item.get('reason','disabled')}"))
        if labels:
            lines.append("Actions: " + " | ".join(labels))
    next_step = str(state.get("next_step") or "").strip()
    if next_step:
        lines.append("Next: " + next_step)
    lines.append("Privacy: no screenshots, crops, hashes or pixels are saved.")
    return "\n".join(lines)


def contains_image_data(payload: Any) -> bool:
    """Defensive test helper used to catch accidental image persistence fields.

    Count-like keys such as ``selected_correction_pixels`` are allowed.  Raw
    capture artifacts, screenshots, crops, thumbnails, hashes and pixel arrays
    are not.
    """
    allowed_flags = {"stores_image_data", "capture_pixels_persisted", "image_pixels_persisted"}
    allowed_counts = {"selected_correction_pixels", "missing_pixels", "wrong_color_pixels"}

    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                k = str(key).lower()
                if k in allowed_counts:
                    continue
                if k in allowed_flags:
                    if bool(item):
                        return True
                    continue
                if any(word in k for word in IMAGE_DATA_WORDS):
                    return True
                if walk(item):
                    return True
            return False
        if isinstance(value, (list, tuple, set)):
            return any(walk(item) for item in value)
        return False
    return walk(payload)
