"""Step 12 — local Auto Tuner feedback loop and real-draw learning.

This module is deliberately *not* machine learning.  It stores bounded EWMA
statistics from completed real drawings and feeds those statistics back into the
Step 11 deterministic Auto policy.  No image pixels, screenshots, URLs, account
data, text prompts or network telemetry are persisted.

Storage is isolated by profile.  A Microsoft Paint sample can never affect
Gartic/Skribbl and vice versa.  Inside each profile, strategy history is further
keyed by source kind, deadline class, active tool, brush width and colour
workflow so materially different delivery setups do not contaminate each other.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from CompletedDrawLearning import has_completed_drawing_work
from ProfileStorage import profile_auto_tuner_feedback_file, safe_profile_key
from RuntimePaths import atomic_write_text, file_transaction, is_finite_number, read_json

VERSION = 1
MIN_LEARNING_SAMPLES = 3
MAX_HISTORY = 12
MAX_CONTEXTS = 256


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _profile(options: dict[str, Any]) -> str:
    return safe_profile_key(options.get("profile_key") or options.get("profile_name") or "generic")


def _budget_class(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(float(seconds)) or float(seconds) <= 0:
        return "unlimited"
    seconds = float(seconds)
    if seconds <= 82:
        return "short-75-80"
    if seconds <= 155:
        return "medium-150"
    if seconds <= 305:
        return "long-300"
    return "extended"


def _tool(options: dict[str, Any]) -> str:
    return str(options.get("effective_paint_tool") or options.get("paint_tool") or
               options.get("tool_strategy") or "default").strip().lower().replace(" ", "-")


def _workflow(options: dict[str, Any]) -> str:
    return str(options.get("custom_color_workflow") or "calibrated-palette").strip().lower().replace(" ", "-")


def _brush(options: dict[str, Any]) -> int:
    try:
        return max(1, min(128, int(options.get("brush_px") or 1)))
    except Exception:
        return 1


def _empty(profile_key: str) -> dict[str, Any]:
    return {"version": VERSION, "profile_key": safe_profile_key(profile_key), "contexts": {}}


def _resolved_path(options: dict[str, Any], path: Path | None) -> Path:
    return Path(path) if path is not None else profile_auto_tuner_feedback_file(_profile(options))


def _load(options: dict[str, Any], path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    resolved = _resolved_path(options, path)
    profile = _profile(options)
    try:
        raw = read_json(resolved)
        if (not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != VERSION or
                safe_profile_key(raw.get("profile_key")) != profile or
                not isinstance(raw.get("contexts"), dict)):
            return resolved, _empty(profile)
        contexts = {key: item for key, item in raw['contexts'].items()
                    if isinstance(key, str) and _valid_context(item)}
        contexts = dict(sorted(contexts.items(), key=lambda pair: _finite(pair[1].get('updated_at')))[-MAX_CONTEXTS:])
        return resolved, {"version": VERSION, "profile_key": profile, "contexts": contexts}
    except (OSError, ValueError, TypeError):
        return resolved, _empty(profile)


def _valid_context(item):
    if not isinstance(item, dict):
        return False
    for key in ('samples', 'snapshot_samples'):
        value = item.get(key, 0)
        if type(value) is not int or not 0 <= value <= 1_000_000_000:
            return False
    if not isinstance(item.get('history', []), list):
        return False
    for key, value in item.items():
        if key.endswith('_ema') and value is not None:
            if not is_finite_number(value):
                return False
    return True


def _context_dimensions(options: dict[str, Any], source_kind: str, strategy: str,
                        budget_seconds: float | None) -> dict[str, Any]:
    return {
        "profile_key": _profile(options),
        "source_kind": str(source_kind or "unknown"),
        "budget_class": _budget_class(budget_seconds),
        "strategy": str(strategy or "unknown"),
        "tool": _tool(options),
        "brush_px": _brush(options),
        "workflow": _workflow(options),
    }


def _context_key(dim: dict[str, Any]) -> str:
    # Values are sanitized/bounded and the file itself is already profile scoped.
    return '|'.join(f'{name}={quote(str(dim[field]), safe="-_. /")}' for name, field in (
        ('source', 'source_kind'), ('budget', 'budget_class'), ('strategy', 'strategy'),
        ('tool', 'tool'), ('brush', 'brush_px'), ('color', 'workflow')))


def _alpha(samples: int) -> float:
    if samples < 2:
        return .42
    if samples < 5:
        return .28
    return .16


def _ema(old: Any, value: float, samples: int, *, lo: float, hi: float) -> float:
    value = _clamp(value, lo, hi)
    if old is None or samples <= 0:
        return value
    old_f = _clamp(_finite(old, value), lo, hi)
    a = _alpha(samples)
    return old_f * (1.0 - a) + value * a


def _planned_accuracy(options: dict[str, Any]) -> dict[str, float | None]:
    meta = options.get("adaptive_accuracy_meta") if isinstance(options, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    def metric(name):
        value = meta.get(name)
        if value is None:
            return None
        v = _finite(value, float("nan"))
        return _clamp(v, 0.0, 100.0) if math.isfinite(v) else None
    return {
        "visual": metric("visual_accuracy_percent"),
        "perceptual": metric("perceptual_color_accuracy_percent"),
        "edge": metric("edge_accuracy_percent"),
        "coverage": metric("coverage_percent"),
        "plan_execution": metric("plan_execution_accuracy_percent"),
    }


def _actual_snapshot_accuracy(options: dict[str, Any]) -> dict[str, Any]:
    meta = options.get("post_draw_accuracy_meta") if isinstance(options, dict) else {}
    if not isinstance(meta, dict):
        return {"available": False, "trusted": False}
    def metric(name):
        value = meta.get(name)
        if not is_finite_number(value) or not 0 <= value <= 100:
            return None
        return float(value)
    visual = metric('visual_accuracy_percent')
    trust = str(meta.get("feedback_trust") or "none").lower()
    state = str(meta.get("scoring_state") or "").lower()
    available = visual is not None and ('available' not in meta or meta['available'] is True)
    trusted = (available and trust in ("high", "medium")
               and ('trusted' not in meta or meta['trusted'] is True)
               and state not in ("unavailable", "rejected"))
    return {
        "available": available,
        "trusted": bool(trusted),
        "trust": trust,
        "scoring_state": state or None,
        "confidence_percent": metric("confidence_percent"),
        "visual": None if visual is None else _clamp(visual, 0.0, 100.0),
        "perceptual": metric("perceptual_color_accuracy_percent"),
        "edge": metric("edge_accuracy_percent"),
        "source_pixel": metric("source_pixel_accuracy_percent"),
        "actual_coverage_percent": metric("actual_coverage_percent"),
        "actual_vs_simulated_visual_percent": metric("actual_vs_simulated_visual_percent"),
        "unexpected_ink_percent": metric("unexpected_ink_percent"),
        "blank_canvas": bool(meta.get("blank_canvas")),
        "visual_gate_passed": meta.get("visual_gate_passed"),
        "evidence": meta.get("evidence"),
    }


def _runtime_result(plan: dict[str, Any], completed_paths: int) -> dict[str, Any]:
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    deadline = options.get("deadline_runtime_meta") if isinstance(options.get("deadline_runtime_meta"), dict) else {}
    safety = options.get("runtime_safety_report") if isinstance(options.get("runtime_safety_report"), dict) else {}
    counts = safety.get("counts") if isinstance(safety.get("counts"), dict) else {}
    planned_paths = max(0, int(plan.get("count") or 0))
    executed = int(deadline.get("executed_paths") or 0)
    scheduler_skipped = int(deadline.get("skipped_paths") or 0)
    if executed + scheduler_skipped > 0:
        completion = executed / max(1, executed + scheduler_skipped)
    elif planned_paths > 0:
        completion = max(0.0, min(1.0, float(completed_paths or 0) / planned_paths))
    else:
        completion = 1.0
    structural = deadline.get("structural_coverage_percent")
    if structural is None:
        structural = completion * 100.0
    structural = _clamp(_finite(structural, completion * 100.0), 0.0, 100.0) / 100.0
    # RuntimeSafetyReport classifies these as exclusive delivered path kinds.
    # A boundary-clipped or edge-following path still delivered drawing input.
    drawn = sum(max(0, int(counts.get(name) or 0)) for name in ('drawn', 'clipped', 'edge_follow'))
    blocked = max(0, int(counts.get("blocked") or 0))
    safe_skipped = max(0, int(counts.get("skipped") or 0))
    safety_total = drawn + blocked + safe_skipped
    safety_delivery = 1.0 if safety_total <= 0 else drawn / max(1, safety_total)
    return {
        "planned_paths": planned_paths,
        "completed_paths": max(0, int(completed_paths or 0)),
        "scheduler_executed_paths": max(0, executed),
        "scheduler_skipped_paths": max(0, scheduler_skipped),
        "completion_ratio": _clamp(completion, 0.0, 1.0),
        "structural_completion_ratio": _clamp(structural, 0.0, 1.0),
        "safety_delivery_ratio": _clamp(safety_delivery, 0.0, 1.0),
        "panic_mode": bool(deadline.get("panic_mode")),
        "panic_activations": max(0, int(deadline.get("panic_activations") or 0)),
        "catch_up_activations": max(0, int(deadline.get("catch_up_activations") or 0)),
        "runtime_cost_multiplier": _finite(deadline.get("runtime_cost_multiplier"), 1.0),
    }


def _usable_deadline(plan: dict[str, Any]) -> float | None:
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    acceptance = options.get("auto_tuner_acceptance_meta") if isinstance(options.get("auto_tuner_acceptance_meta"), dict) else {}
    value = acceptance.get("usable_deadline_seconds")
    if value is None:
        tuner = options.get("auto_tuner_meta") if isinstance(options.get("auto_tuner_meta"), dict) else {}
        value = tuner.get("usable_budget_seconds")
    if value is None:
        return None
    result = _finite(value, 0.0)
    return result if result > 0 else None


def _visual_gate(plan: dict[str, Any]) -> float | None:
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    acceptance = options.get("auto_tuner_acceptance_meta") if isinstance(options.get("auto_tuner_acceptance_meta"), dict) else {}
    tuner = options.get("auto_tuner_meta") if isinstance(options.get("auto_tuner_meta"), dict) else {}
    gates = acceptance.get("gates") if isinstance(acceptance.get("gates"), dict) else tuner.get("acceptance_gates")
    gates = gates if isinstance(gates, dict) else {}
    value = gates.get("visual_accuracy_min_percent")
    return None if value is None else _clamp(_finite(value, 0.0), 0.0, 100.0)


def record_completed_feedback(plan: dict[str, Any], actual_seconds: float, *, completed_paths: int = 0,
                              path: Path | None = None) -> dict[str, Any]:
    """Record one clean completed *real* Auto draw.

    The time measurement is real wall-clock execution time.  Source-relative
    visual metrics are taken from a read-only post-draw canvas snapshot when the
    execution layer could safely obtain one.  If no trustworthy snapshot exists,
    a clearly-labelled delivery proxy is used for strategy learning instead of
    pretending that simulated plan accuracy was measured from the final canvas.
    """
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    tuner = options.get("auto_tuner_meta") if isinstance(options.get("auto_tuner_meta"), dict) else {}
    if not tuner.get("active"):
        return {"recorded": False, "reason": "Auto tuner inactive"}
    if bool(options.get("test_run")) or bool(options.get("dry_run_sampled")) or options.get("render_resume_state"):
        return {"recorded": False, "reason": "test/dry-run/resume sample"}
    from CompletedDrawLearning import paused_learning_reason
    pause_reason = paused_learning_reason(options)
    if pause_reason:
        return {"recorded": False, "reason": pause_reason}
    if not has_completed_drawing_work(options, completed_paths):
        return {"recorded": False, "reason": "no completed drawing work"}
    actual = _finite(actual_seconds, 0.0)
    if actual < 1.0:
        return {"recorded": False, "reason": "sample too small"}

    draw_time = plan.get("draw_time_estimate") if isinstance(plan.get("draw_time_estimate"), dict) else {}
    predicted = _finite(draw_time.get("projected_seconds", plan.get("estimate")), 0.0)
    if predicted < 1.0:
        return {"recorded": False, "reason": "missing predicted time"}
    source_features = tuner.get('source_features')
    source_features = source_features if isinstance(source_features, dict) else {}
    source_kind = str(source_features.get("source_kind") or "unknown")
    selected_strategy = str(tuner.get("selected_strategy") or "unknown")
    base_strategy = tuner.get('base_strategy')
    # The next tuning decision reads the base policy's context. Feed adjusted
    # outcomes back into that context, while keeping rescue strategies separate.
    strategy = (base_strategy if isinstance(base_strategy, str) and base_strategy
                and selected_strategy.startswith(base_strategy + '+feedback-') else selected_strategy)
    usable = _usable_deadline(plan)
    dim = _context_dimensions(options, source_kind, strategy, usable)
    key = _context_key(dim)
    runtime = _runtime_result(plan, completed_paths)
    planned = _planned_accuracy(options)
    snapshot = _actual_snapshot_accuracy(options)

    # Delivery proxy: plan visual likeness multiplied by what was actually
    # delivered. Structural completion gets more weight than optional path count.
    delivery_factor = (runtime["completion_ratio"] * .34 +
                       runtime["structural_completion_ratio"] * .50 +
                       runtime["safety_delivery_ratio"] * .16)
    planned_visual = planned.get("visual")
    proxy = None if planned_visual is None else _clamp(float(planned_visual) * delivery_factor, 0.0, 100.0)
    result_visual = snapshot.get("visual") if snapshot.get("trusted") else proxy
    result_source = "post-draw canvas snapshot" if snapshot.get("trusted") else "runtime delivery proxy"

    deadline_pass = True if usable is None else actual <= usable + .15
    gate = _visual_gate(plan)
    if result_visual is None or gate is None:
        quality_pass = runtime["structural_completion_ratio"] >= .90 and runtime["safety_delivery_ratio"] >= .97
    else:
        # Proxy evidence is intentionally given a small tolerance because it is
        # not a pixel measurement. Snapshot evidence uses the actual gate.
        threshold = gate if snapshot.get("trusted") else max(0.0, gate - 5.0)
        quality_pass = float(result_visual) + 1e-9 >= threshold
    delivery_pass = (runtime["structural_completion_ratio"] >= .88 and
                     runtime["safety_delivery_ratio"] >= .96)
    accepted = bool(deadline_pass and quality_pass and delivery_pass)

    ratio = _clamp(actual / predicted, .30, 5.0)
    abs_pct = _clamp(abs(actual - predicted) / max(1.0, actual), 0.0, 2.0)
    headroom = None if usable is None else usable - actual

    with file_transaction(_resolved_path(options, path)):
        resolved, db = _load(options, path)
        old = db["contexts"].get(key)
        if not isinstance(old, dict):
            old = {}
        samples = max(0, int(old.get("samples") or 0))
        deadline_value = 1.0 if deadline_pass else 0.0
        acceptance_value = 1.0 if accepted else 0.0
        panic_value = 1.0 if runtime["panic_activations"] > 0 else 0.0
        catchup_value = 1.0 if runtime["catch_up_activations"] > 0 else 0.0

        item = dict(dim)
        item.update({
            "samples": samples + 1,
            "time_ratio_ema": round(_ema(old.get("time_ratio_ema"), ratio, samples, lo=.45, hi=4.0), 6),
            "time_abs_error_ema": round(_ema(old.get("time_abs_error_ema"), abs_pct, samples, lo=0.0, hi=2.0), 6),
            "deadline_pass_rate_ema": round(_ema(old.get("deadline_pass_rate_ema"), deadline_value, samples, lo=0.0, hi=1.0), 6),
            "acceptance_pass_rate_ema": round(_ema(old.get("acceptance_pass_rate_ema"), acceptance_value, samples, lo=0.0, hi=1.0), 6),
            "completion_ratio_ema": round(_ema(old.get("completion_ratio_ema"), runtime["completion_ratio"], samples, lo=0.0, hi=1.0), 6),
            "structural_completion_ema": round(_ema(old.get("structural_completion_ema"), runtime["structural_completion_ratio"], samples, lo=0.0, hi=1.0), 6),
            "safety_delivery_ema": round(_ema(old.get("safety_delivery_ema"), runtime["safety_delivery_ratio"], samples, lo=0.0, hi=1.0), 6),
            "panic_rate_ema": round(_ema(old.get("panic_rate_ema"), panic_value, samples, lo=0.0, hi=1.0), 6),
            "catchup_rate_ema": round(_ema(old.get("catchup_rate_ema"), catchup_value, samples, lo=0.0, hi=1.0), 6),
            "last_predicted_seconds": round(predicted, 4),
            "last_actual_seconds": round(actual, 4),
            "last_time_ratio": round(ratio, 6),
            "last_deadline_met": bool(deadline_pass),
            "last_accepted": bool(accepted),
            "last_result_source": result_source,
            "last_selected_strategy": selected_strategy,
            "last_result_visual_percent": None if result_visual is None else round(float(result_visual), 3),
            "last_plan_visual_percent": None if planned_visual is None else round(float(planned_visual), 3),
            "last_actual_snapshot_visual_percent": None if not snapshot.get("available") else round(float(snapshot.get("visual")), 3),
            "last_actual_snapshot_trust": snapshot.get("trust", "none"),
            "last_snapshot_scoring_state": snapshot.get("scoring_state"),
            "last_snapshot_confidence_percent": snapshot.get("confidence_percent"),
            "last_actual_snapshot_coverage_percent": snapshot.get("actual_coverage_percent"),
            "last_actual_vs_simulated_visual_percent": snapshot.get("actual_vs_simulated_visual_percent"),
            "last_snapshot_unexpected_ink_percent": snapshot.get("unexpected_ink_percent"),
            "last_completion_percent": round(runtime["completion_ratio"] * 100.0, 2),
            "last_structural_completion_percent": round(runtime["structural_completion_ratio"] * 100.0, 2),
            "last_safety_delivery_percent": round(runtime["safety_delivery_ratio"] * 100.0, 2),
            "last_headroom_seconds": None if headroom is None else round(headroom, 3),
            "updated_at": time.time(),
        })
        if result_visual is not None:
            item["result_visual_ema"] = round(_ema(old.get("result_visual_ema"), float(result_visual), samples, lo=0.0, hi=100.0), 4)
        if planned_visual is not None:
            item["planned_visual_ema"] = round(_ema(old.get("planned_visual_ema"), float(planned_visual), samples, lo=0.0, hi=100.0), 4)
        if snapshot.get("trusted"):
            item["snapshot_visual_ema"] = round(_ema(old.get("snapshot_visual_ema"), float(snapshot["visual"]), samples, lo=0.0, hi=100.0), 4)
            item["snapshot_samples"] = max(0, int(old.get("snapshot_samples") or 0)) + 1
        else:
            item["snapshot_samples"] = max(0, int(old.get("snapshot_samples") or 0))

        history = list(old.get("history") or ())[-(MAX_HISTORY - 1):]
        history.append({
            "time_ratio": round(ratio, 4), "deadline_met": bool(deadline_pass),
            "accepted": bool(accepted), "completion_percent": round(runtime["completion_ratio"] * 100.0, 1),
            "structure_percent": round(runtime["structural_completion_ratio"] * 100.0, 1),
            "result_visual_percent": None if result_visual is None else round(float(result_visual), 1),
            "result_source": result_source, "snapshot_trust": snapshot.get("trust", "none"),
            "snapshot_confidence_percent": snapshot.get("confidence_percent"),
            "panic": bool(runtime["panic_activations"]),
        })
        item["history"] = history
        db["contexts"][key] = item
        while len(db['contexts']) > MAX_CONTEXTS:
            oldest = min((name for name in db['contexts'] if name != key),
                         key=lambda name: _finite(db['contexts'][name].get('updated_at')))
            del db['contexts'][oldest]
        resolved.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(resolved, json.dumps(db, ensure_ascii=False, indent=2, allow_nan=False))

        return {
            "recorded": True, "profile_key": dim["profile_key"], "context_key": key,
            "samples": item["samples"], "strategy": strategy, "selected_strategy": selected_strategy,
            "source_kind": source_kind,
            "budget_class": dim["budget_class"], "predicted_seconds": round(predicted, 3),
            "actual_seconds": round(actual, 3), "time_ratio": round(ratio, 4),
            "deadline_met": bool(deadline_pass), "accepted": bool(accepted),
            "completion_percent": item["last_completion_percent"],
            "structural_completion_percent": item["last_structural_completion_percent"],
            "result_visual_percent": item["last_result_visual_percent"],
            "result_source": result_source, "snapshot_trust": snapshot.get("trust", "none"),
            "snapshot_scoring_state": snapshot.get("scoring_state"),
            "snapshot_confidence_percent": snapshot.get("confidence_percent"),
            "actual_snapshot_coverage_percent": snapshot.get("actual_coverage_percent"),
            "actual_vs_simulated_visual_percent": snapshot.get("actual_vs_simulated_visual_percent"),
            "storage_path": str(resolved),
        }


def _matching_contexts(db: dict[str, Any], dim: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in (db.get("contexts") or {}).values():
        if not isinstance(item, dict):
            continue
        if all(item.get(k) == dim.get(k) for k in ("profile_key", "source_kind", "budget_class", "tool", "brush_px", "workflow")):
            out.append(item)
    return out


def recommend_adjustment(options: dict[str, Any], *, source_kind: str, strategy: str,
                         budget_seconds: float | None, color_ceiling: int,
                         visual_gate_percent: float | None = None,
                         path: Path | None = None) -> dict[str, Any]:
    """Return a bounded deterministic policy adjustment from prior real draws."""
    resolved, db = _load(options, path)
    dim = _context_dimensions(options, source_kind, strategy, budget_seconds)
    key = _context_key(dim)
    current = db["contexts"].get(key)
    current = current if isinstance(current, dict) else {}
    samples = max(0, int(current.get("samples") or 0))
    matches = _matching_contexts(db, dim)

    result = {
        "version": VERSION, "active": False, "state": "cold-start" if samples == 0 else "learning",
        "profile_key": dim["profile_key"], "context_key": key, "samples": samples,
        "storage_path": str(resolved), "action": "none", "reason": "not enough completed real draws",
        "color_ceiling_before": int(color_ceiling), "color_ceiling_after": int(color_ceiling),
        "time_ratio_ema": current.get("time_ratio_ema"),
        "deadline_pass_rate": current.get("deadline_pass_rate_ema"),
        "acceptance_pass_rate": current.get("acceptance_pass_rate_ema"),
        "result_visual_ema": current.get("result_visual_ema"),
    }
    if samples < MIN_LEARNING_SAMPLES:
        return result

    ratio = _finite(current.get("time_ratio_ema"), 1.0)
    deadline_rate = _finite(current.get("deadline_pass_rate_ema"), 1.0)
    accept_rate = _finite(current.get("acceptance_pass_rate_ema"), 1.0)
    panic_rate = _finite(current.get("panic_rate_ema"), 0.0)
    result_visual = current.get("result_visual_ema")
    result_visual = None if result_visual is None else _finite(result_visual, 0.0)
    gate = None if visual_gate_percent is None else _finite(visual_gate_percent, 0.0)
    timed = budget_seconds is not None
    action = "none"
    reason = "learned strategy is within expected timing/quality range"
    changes: dict[str, Any] = {}
    ceiling = int(color_ceiling)

    # Rescue history can graduate into the first-pass policy, but only after a
    # minimum of three clean samples and only when it clearly beats the current
    # strategy in the same isolated context.
    rescue = None
    for item in matches:
        if str(item.get("strategy")) != "deadline-rescue" or int(item.get("samples") or 0) < MIN_LEARNING_SAMPLES:
            continue
        if rescue is None or _finite(item.get("acceptance_pass_rate_ema"), 0.0) > _finite(rescue.get("acceptance_pass_rate_ema"), 0.0):
            rescue = item
    if timed and rescue is not None:
        rescue_accept = _finite(rescue.get("acceptance_pass_rate_ema"), 0.0)
        rescue_deadline = _finite(rescue.get("deadline_pass_rate_ema"), 0.0)
        if rescue_accept >= .80 and rescue_deadline >= .86 and (accept_rate < .68 or deadline_rate < .72):
            action = "promote-deadline-rescue"
            reason = "real completed draws show deadline-rescue is materially more reliable for this exact profile/context"
            changes.update({
                "drawing_mode": "Smart paths (recommended)", "mode": "Smart paths (recommended)",
                "smart_paths": True, "lines": True, "draw_quality": "Balanced" if float(budget_seconds or 999) <= 82 else "High likeness",
                "planning_resolution": "Standard", "quality": "Balanced", "detail": 8,
                "adaptive_detail": "Strong simplify", "speed": "Fast", "precision": "Normal",
                "extra_fast": True, "extra_fast_v2": True, "progressive_rendering": "On",
                "stroke_optimizer": "Smart merge", "background_simplification": "Strong",
            })
            ceiling = max(4, int(math.floor(ceiling * .82)))

    if action == "none" and timed and (ratio >= 1.12 or deadline_rate < .76 or panic_rate >= .28):
        pressure = max(ratio - 1.0, .76 - deadline_rate, panic_rate * .45)
        reduction = 4 if pressure >= .25 else 2
        ceiling = max(4, ceiling - reduction)
        action = "protect-deadline"
        reason = "real draws are slower or tighter than the static strategy estimate"
        changes.update({"speed": "Fast", "extra_fast": True, "extra_fast_v2": True})
        if float(budget_seconds or 999) <= 155:
            changes.update({"planning_resolution": "Standard", "adaptive_detail": "Strong simplify" if pressure >= .25 else "Balanced"})
    elif action == "none" and result_visual is not None and gate is not None and result_visual < gate - 3.0:
        # Buy quality only when real timing has consistently demonstrated actual
        # headroom. Tight short rounds require exceptional headroom before the
        # feedback loop is allowed to spend more.
        enough_headroom = ratio <= (.76 if float(budget_seconds or 999) <= 82 else .88)
        if (not timed) or (deadline_rate >= .92 and enough_headroom):
            ceiling = min(32, ceiling + (2 if timed else 4))
            action = "buy-quality"
            reason = "real draws consistently finish with headroom but result quality remains below the visual gate"
            changes.update({"adaptive_detail": "Preserve detail", "precision": "High"})
            if not timed or float(budget_seconds or 999) > 82:
                changes["planning_resolution"] = "High"

    result.update({
        "active": action != "none", "state": "learned", "action": action, "reason": reason,
        "color_ceiling_after": int(ceiling), "changes": changes,
        "time_ratio_ema": round(ratio, 4), "deadline_pass_rate": round(deadline_rate, 4),
        "acceptance_pass_rate": round(accept_rate, 4), "panic_rate": round(panic_rate, 4),
        "result_visual_ema": None if result_visual is None else round(result_visual, 3),
    })
    return result


def reset_profile(options: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Reset only this profile's Step 12 strategy feedback database."""
    resolved = _resolved_path(options, path)
    with file_transaction(resolved):
        existed = resolved.exists()
        try:
            resolved.unlink()
        except FileNotFoundError:
            pass
        return {"reset": bool(existed), "profile_key": _profile(options), "storage_path": str(resolved)}
