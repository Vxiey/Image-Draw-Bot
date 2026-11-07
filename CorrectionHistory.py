"""Step 16 — compact correction history and before/after metrics.

Stores only bounded numeric/text metadata per profile.  It never stores source
images, canvas snapshots, screenshots, crops, thumbnails, hashes or raw pixels.
The history is for local review/diagnostics only and is profile-isolated through
ProfileStorage.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

from ProfileStorage import profile_correction_history_file, safe_profile_key
from RuntimePaths import atomic_write_text, file_transaction, is_finite_number, read_json

VERSION = 1
MAX_ENTRIES = 30
DISPLAY_LIMIT = 8
FORBIDDEN_IMAGE_KEYS = (
    "screenshot", "thumbnail", "crop", "image_data", "canvas_data", "raw_pixels",
    "pixel_array", "source_pixels", "canvas_pixels", "image_bytes", "bitmap", "hash",
)
_ALLOWED_PIXEL_METRICS = {
    "source_pixel_accuracy_percent", "selected_correction_pixels", "missing_pixels",
    "wrong_color_pixels", "raw_candidate_pixels", "expected_foreground_pixels",
    "actual_foreground_pixels",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _metric(value: Any) -> float | None:
    out = _finite(value, None)
    if out is None:
        return None
    return round(max(0.0, min(100.0, out)), 3)


def _num(value: Any, ndigits: int = 3) -> float | None:
    out = _finite(value, None)
    return None if out is None else round(out, ndigits)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _profile_from_options(options: dict[str, Any]) -> str:
    return safe_profile_key(options.get("profile_key") or options.get("profile_name") or "generic")


def _resolved_path(options: dict[str, Any], path: Path | None = None) -> Path:
    return Path(path) if path is not None else profile_correction_history_file(_profile_from_options(options))


def _empty(profile_key: str) -> dict[str, Any]:
    return {"version": VERSION, "profile_key": safe_profile_key(profile_key), "entries": []}


def _valid_entry(entry) -> bool:
    """Keep legacy rows only when their display fields have their real domains."""
    if not isinstance(entry, dict) or contains_image_data(entry):
        return False
    if 'state' in entry and (not isinstance(entry['state'], str) or len(entry['state']) > 80):
        return False
    for section in ('before', 'after', 'delta', 'correction', 'context'):
        if section in entry and not isinstance(entry[section], dict):
            return False
    for section in ('before', 'after', 'delta'):
        for key, value in entry.get(section, {}).items():
            if value is None or not key.endswith(('_percent', '_delta')):
                continue
            low = -100 if key.endswith('_delta') else 0
            if not is_finite_number(value) or not low <= value <= 100:
                return False
    for key in ('executed_paths', 'planned_paths', 'executed_colors', 'corrected_colors',
                'selected_correction_pixels', 'missing_pixels', 'wrong_color_pixels'):
        value = entry.get('correction', {}).get(key)
        if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000_000):
            return False
    for key in ('created_at', 'actual_seconds'):
        value = entry.get(key)
        if value is not None and (not is_finite_number(value) or value < 0):
            return False
    return True


def _load(options: dict[str, Any], path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    resolved = _resolved_path(options, path)
    profile = _profile_from_options(options)
    try:
        raw = read_json(resolved)
    except (OSError, ValueError, TypeError):
        return resolved, _empty(profile)
    if not isinstance(raw, dict):
        return resolved, _empty(profile)
    if type(raw.get("version")) is not int or raw["version"] != VERSION:
        return resolved, _empty(profile)
    if safe_profile_key(raw.get("profile_key")) != profile:
        return resolved, _empty(profile)
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return resolved, _empty(profile)
    return resolved, {"version": VERSION, "profile_key": profile, "entries": [e for e in entries if _valid_entry(e)][-MAX_ENTRIES:]}


def _budget_class(seconds: Any) -> str:
    value = _finite(seconds, None)
    if value is None or value <= 0:
        return "unlimited"
    if value <= 82:
        return "short-75-80"
    if value <= 155:
        return "medium-150"
    if value <= 305:
        return "long-300"
    return "extended"


def _context(plan_or_options: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if isinstance(plan_or_options.get("options"), dict):
        plan = plan_or_options
        options = _as_dict(plan.get("options"))
    else:
        plan = {}
        options = plan_or_options if isinstance(plan_or_options, dict) else {}
    tuner = _as_dict(options.get("auto_tuner_meta"))
    acceptance = _as_dict(options.get("auto_tuner_acceptance_meta"))
    gates = _as_dict(acceptance.get("gates")) or _as_dict(tuner.get("acceptance_gates"))
    deadline = acceptance.get("usable_deadline_seconds")
    if deadline is None:
        deadline = tuner.get("usable_budget_seconds") or options.get("max_seconds")
    ctx = {
        "profile_key": _profile_from_options(options),
        "profile_name": str(options.get("profile_name") or options.get("profile_key") or ""),
        "renderer": str(tuner.get("renderer") or options.get("mode") or plan.get("mode") or "unknown"),
        "strategy": str(tuner.get("selected_strategy") or tuner.get("speed_strategy") or options.get("speed") or "unknown"),
        "budget_class": _budget_class(deadline),
        "usable_deadline_seconds": _num(deadline),
        "visual_gate_percent": _metric(gates.get("visual_accuracy_min_percent")),
        "tool": str(options.get("effective_paint_tool") or options.get("paint_tool") or options.get("tool_strategy") or "default"),
        "brush_px": max(1, min(128, _int(options.get("brush_px"), 1))),
        "workflow": str(options.get("custom_color_workflow") or options.get("color_workflow") or "calibrated-palette"),
    }
    return plan, options, ctx


def compact_result_metrics(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Return before/after result metrics safe for persistence."""
    meta = _as_dict(meta)
    if not meta:
        return {}
    def preferred(primary, secondary):
        value = meta.get(primary)
        return meta.get(secondary) if value is None else value
    out = {
        "available": bool(meta.get("available", True)),
        "trusted": bool(meta.get("trusted")) if "trusted" in meta else None,
        "trust": meta.get("feedback_trust") or meta.get("post_correction_trust"),
        "confidence_percent": _metric(preferred("confidence_percent", "post_correction_confidence_percent")),
        "visual_accuracy_percent": _metric(preferred("visual_accuracy_percent", "post_correction_visual_accuracy_percent")),
        "source_pixel_accuracy_percent": _metric(meta.get("source_pixel_accuracy_percent")),
        "perceptual_color_accuracy_percent": _metric(meta.get("perceptual_color_accuracy_percent")),
        "luminance_accuracy_percent": _metric(meta.get("luminance_accuracy_percent")),
        "hue_accuracy_percent": _metric(meta.get("hue_accuracy_percent")),
        "edge_accuracy_percent": _metric(meta.get("edge_accuracy_percent")),
        "actual_coverage_percent": _metric(preferred("actual_coverage_percent", "post_correction_actual_coverage_percent")),
        "actual_vs_simulated_visual_percent": _metric(meta.get("actual_vs_simulated_visual_percent")),
        "unexpected_ink_percent": _metric(meta.get("unexpected_ink_percent")),
        "visual_gate_passed": meta.get("visual_gate_passed") if isinstance(meta.get("visual_gate_passed"), bool) else None,
        "deadline_safe": meta.get("deadline_safe") if isinstance(meta.get("deadline_safe"), bool) else None,
        "blank_canvas": bool(meta.get("blank_canvas")) if "blank_canvas" in meta else None,
        "scoring_state": meta.get("scoring_state"),
    }
    return {k: v for k, v in out.items() if v is not None}


def compact_correction_metrics(correction: dict[str, Any] | None) -> dict[str, Any]:
    correction = _as_dict(correction)
    if not correction:
        return {}
    out = {
        "enabled": bool(correction.get("enabled")),
        "safe": bool(correction.get("safe", True)),
        "reason": str(correction.get("reason") or "")[:220],
        "planned_paths": _int(correction.get("correction_paths"), 0),
        "executed_paths": _int(correction.get("executed_paths"), 0),
        "executed_colors": _int(correction.get("executed_colors"), 0),
        "corrected_colors": _int(correction.get("corrected_colors"), 0),
        "selected_correction_pixels": _int(correction.get("selected_correction_pixels"), 0),
        "missing_pixels": _int(correction.get("missing_pixels"), 0),
        "wrong_color_pixels": _int(correction.get("wrong_color_pixels"), 0),
        "estimated_seconds": _num(correction.get("estimated_seconds")),
        "stopped_early": bool(correction.get("stopped_early")),
        "capped": bool(correction.get("capped")),
        "post_correction_trust": correction.get("post_correction_trust"),
        "post_correction_confidence_percent": _metric(correction.get("post_correction_confidence_percent")),
        "stores_image_data": False,
        "capture_pixels_persisted": False,
        "image_pixels_persisted": False,
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


def _after_from_options(options: dict[str, Any], correction: dict[str, Any]) -> dict[str, Any]:
    if correction.get("post_correction_visual_accuracy_percent") is not None or correction.get("post_correction_actual_coverage_percent") is not None:
        return compact_result_metrics({
            "available": True,
            "trusted": str(correction.get("post_correction_trust") or "none").lower() in ("high", "medium"),
            "feedback_trust": correction.get("post_correction_trust"),
            "confidence_percent": correction.get("post_correction_confidence_percent"),
            "visual_accuracy_percent": correction.get("post_correction_visual_accuracy_percent"),
            "actual_coverage_percent": correction.get("post_correction_actual_coverage_percent"),
        })
    # If a correction pass ran and Step 13 re-scored afterwards, DrawBot stores
    # the post-correction metrics as post_draw_accuracy_meta.
    if _int(correction.get("executed_paths"), 0) > 0:
        return compact_result_metrics(_as_dict(options.get("post_draw_accuracy_meta")))
    return {}


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "visual_accuracy_percent", "source_pixel_accuracy_percent", "perceptual_color_accuracy_percent",
        "luminance_accuracy_percent", "hue_accuracy_percent", "edge_accuracy_percent", "actual_coverage_percent",
        "actual_vs_simulated_visual_percent",
    ):
        a = _finite(after.get(key), None)
        b = _finite(before.get(key), None)
        if a is not None and b is not None:
            out[key.replace("_percent", "_delta")] = round(a - b, 3)
    return out


def _state(correction: dict[str, Any]) -> str:
    if not correction:
        return "not-recorded"
    if not bool(correction.get("safe", True)):
        return "blocked"
    if not bool(correction.get("enabled")):
        reason = str(correction.get("reason") or "").lower()
        if "within" in reason or "already" in reason or "no bounded" in reason:
            return "skipped-clean"
        return "skipped"
    planned = _int(correction.get("correction_paths", correction.get("planned_paths")), 0)
    executed = _int(correction.get("executed_paths"), 0)
    if executed <= 0:
        return "planned-not-executed"
    if bool(correction.get("stopped_early")) or (planned > 0 and executed < planned):
        return "corrected-partial"
    return "corrected"


def contains_image_data(payload: Any) -> bool:
    """Return True if the payload appears to contain persisted image artifacts."""
    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                k = str(key).lower()
                if k in _ALLOWED_PIXEL_METRICS:
                    continue
                if any(word in k for word in FORBIDDEN_IMAGE_KEYS):
                    # The explicit persisted flags are allowed only when False.
                    if k in {"capture_pixels_persisted", "image_pixels_persisted", "stores_image_data"}:
                        if bool(item):
                            return True
                        continue
                    return True
                if walk(item):
                    return True
            return False
        if isinstance(value, (list, tuple, set)):
            return any(walk(item) for item in value)
        return False
    return walk(payload)


def build_history_entry(plan_or_options: dict[str, Any], *, actual_seconds: float | None = None,
                        created_at: float | None = None) -> dict[str, Any]:
    plan, options, ctx = _context(plan_or_options if isinstance(plan_or_options, dict) else {})
    before = compact_result_metrics(_as_dict(options.get("post_draw_before_correction_accuracy_meta")))
    if not before:
        before = compact_result_metrics(_as_dict(options.get("pre_correction_accuracy_meta")))
    post = _as_dict(options.get("post_draw_accuracy_meta"))
    correction = compact_correction_metrics(_as_dict(options.get("post_draw_correction_meta")))
    if not before:
        before = compact_result_metrics(post)
    after = _after_from_options(options, _as_dict(options.get("post_draw_correction_meta")))
    if not after and _state(correction) in {"skipped", "skipped-clean", "blocked", "planned-not-executed"}:
        after = dict(before)

    created = time.time() if created_at is None else created_at
    if not is_finite_number(created) or created < 0:
        raise ValueError('Correction-history timestamp must be finite and nonnegative.')
    created = float(created)
    material = json.dumps({"t": round(created, 3), "ctx": ctx, "corr": correction, "before": before, "after": after}, sort_keys=True, default=str)
    entry_id = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    entry = {
        "id": entry_id,
        "version": VERSION,
        "created_at": round(created, 3),
        "profile_key": ctx["profile_key"],
        "state": _state(correction),
        "context": ctx,
        "before": before,
        "after": after,
        "delta": _delta(before, after),
        "correction": correction,
        "actual_seconds": _num(actual_seconds),
        "planned_paths": _int(plan.get("count"), 0) if plan else None,
        "privacy": "Compact before/after metrics only; no persisted image artifacts.",
        "stores_image_data": False,
        "capture_pixels_persisted": False,
        "image_pixels_persisted": False,
    }
    return {k: v for k, v in entry.items() if v is not None}


def record_correction_history(plan_or_options: dict[str, Any], *, actual_seconds: float | None = None,
                              path: Path | None = None, created_at: float | None = None) -> dict[str, Any]:
    """Append one compact correction-history entry for the current profile."""
    plan, options, ctx = _context(plan_or_options if isinstance(plan_or_options, dict) else {})
    if bool(options.get("dry_run_sampled")) or bool(options.get("test_run")):
        return {"recorded": False, "reason": "test/dry-run sample", "profile_key": ctx["profile_key"]}
    if not _as_dict(options.get("post_draw_correction_meta")) and not _as_dict(options.get("post_draw_accuracy_meta")):
        return {"recorded": False, "reason": "no post-draw correction/result metadata", "profile_key": ctx["profile_key"]}
    entry = build_history_entry(plan if plan else options, actual_seconds=actual_seconds, created_at=created_at)
    if contains_image_data(entry):
        return {"recorded": False, "reason": "blocked unsafe image-data field", "profile_key": ctx["profile_key"]}
    with file_transaction(_resolved_path(options, path)):
        resolved, db = _load(options, path)
        entries = list(db.get("entries") or [])
        # Avoid duplicate double-click/UI-event records from the same correction run.
        if not entries or entries[-1].get("id") != entry.get("id"):
            entries.append(entry)
        db["entries"] = entries[-MAX_ENTRIES:]
        db["updated_at"] = round(time.time(), 3)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(resolved, json.dumps(db, ensure_ascii=False, indent=2, allow_nan=False))
        summary = summarize_correction_history(db, limit=DISPLAY_LIMIT)
        return {
            "recorded": True,
            "profile_key": ctx["profile_key"],
            "entry_id": entry.get("id"),
            "state": entry.get("state"),
            "entries": len(db["entries"]),
            "latest": compact_history_entry(entry),
            "summary": summary,
            "storage_path": str(resolved),
        }


def record_result_verification(options: dict[str, Any], metrics: dict[str, Any], *,
                               path: Path | None = None, created_at: float | None = None,
                               cancelled=lambda: False) -> dict[str, Any]:
    """Append a read-only observation without attributing correction or drawing.

    Old correction fields in ``options`` supply no before/after pair, counters
    or gain. Only the context and this fresh observation enter the history.
    Cancellation is checked before the atomic publication; an already committed
    observation is never deleted if Stop arrives afterward.
    """
    def check():
        if cancelled():
            raise InterruptedError('Result re-check history cancelled.')
    check()
    _, options, ctx = _context(options if isinstance(options, dict) else {})
    observed = compact_result_metrics(metrics)
    if not observed:
        raise ValueError('Result re-check history requires fresh result metadata.')
    created = time.time() if created_at is None else created_at
    if not is_finite_number(created) or created < 0:
        raise ValueError('Result re-check timestamp must be finite and nonnegative.')
    material = json.dumps({'t': round(created, 3), 'ctx': ctx, 'observed': observed,
                           'operation': 'read-only-verification'}, sort_keys=True, allow_nan=False)
    entry = {'id': hashlib.sha256(material.encode('utf-8')).hexdigest()[:16],
             'version': VERSION, 'created_at': round(created, 3),
             'profile_key': ctx['profile_key'], 'operation': 'read-only-verification',
             'state': 'rechecked' if metrics.get('available') is True else 'recheck-unavailable',
             'context': ctx, 'before': {}, 'after': observed, 'delta': {}, 'correction': {},
             'reason': str(metrics.get('reason') or metrics.get('summary') or '')[:220],
             'privacy': 'Read-only result observation; no correction gain or persisted image artifacts.',
             'stores_image_data': False, 'capture_pixels_persisted': False, 'image_pixels_persisted': False}
    if not _valid_entry(entry):
        raise ValueError('Result re-check history contains invalid result metadata.')
    check()
    with file_transaction(_resolved_path(options, path)):
        resolved, db = _load(options, path)
        entries = list(db.get('entries') or [])
        if not entries or entries[-1].get('id') != entry['id']:
            entries.append(entry)
        db['entries'] = entries[-MAX_ENTRIES:]
        db['updated_at'] = round(time.time(), 3)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        check()
        atomic_write_text(resolved, json.dumps(db, ensure_ascii=False, indent=2, allow_nan=False))
        return {'recorded': True, 'profile_key': ctx['profile_key'], 'entry_id': entry['id'],
                'state': entry['state'], 'entries': len(db['entries']),
                'latest': compact_history_entry(entry),
                'summary': summarize_correction_history(db, limit=DISPLAY_LIMIT),
                'storage_path': str(resolved)}


def compact_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    entry = _as_dict(entry)
    before = _as_dict(entry.get("before")); after = _as_dict(entry.get("after")); delta = _as_dict(entry.get("delta")); corr = _as_dict(entry.get("correction"))
    result = {
        "id": entry.get("id"),
        "created_at": entry.get("created_at"),
        "state": entry.get("state"),
        "before_visual_accuracy_percent": before.get("visual_accuracy_percent"),
        "after_visual_accuracy_percent": after.get("visual_accuracy_percent"),
        "visual_accuracy_delta": delta.get("visual_accuracy_delta"),
        "before_coverage_percent": before.get("actual_coverage_percent"),
        "after_coverage_percent": after.get("actual_coverage_percent"),
        "coverage_delta": delta.get("actual_coverage_delta"),
        "executed_paths": corr.get("executed_paths"),
        "planned_correction_paths": corr.get("planned_paths"),
        "selected_correction_pixels": corr.get("selected_correction_pixels"),
        "reason": corr.get("reason"),
    }
    if entry.get('operation') == 'read-only-verification':
        result['operation'] = 'read-only-verification'
        result['reason'] = entry.get('reason')
    return result


def load_correction_history(options: dict[str, Any] | None, *, path: Path | None = None,
                            limit: int = DISPLAY_LIMIT) -> dict[str, Any]:
    options = options if isinstance(options, dict) else {}
    resolved, db = _load(options, path)
    entries = [_as_dict(e) for e in list(db.get("entries") or [])[-max(1, int(limit)):]]
    return {
        "version": VERSION,
        "profile_key": _profile_from_options(options),
        "entries": [compact_history_entry(e) for e in entries],
        "entry_count": len(db.get("entries") or []),
        "storage_path": str(resolved),
        "stores_image_data": False,
        "summary": summarize_correction_history(db, limit=limit),
    }


def summarize_correction_history(db_or_history: dict[str, Any] | None, *, limit: int = DISPLAY_LIMIT) -> dict[str, Any]:
    data = db_or_history if isinstance(db_or_history, dict) else {}
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    entries = [e for e in entries if isinstance(e, dict)]
    recent = entries[-max(1, int(limit)):]
    corrected = sum(1 for e in recent if str(e.get("state")) in ("corrected", "corrected-partial"))
    skipped = sum(1 for e in recent if str(e.get("state", "")).startswith("skipped"))
    blocked = sum(1 for e in recent if str(e.get("state")) == "blocked")
    visual_deltas = [_finite((_as_dict(e.get("delta"))).get("visual_accuracy_delta"), None) for e in recent]
    visual_deltas = [v for v in visual_deltas if v is not None]
    coverage_deltas = [_finite((_as_dict(e.get("delta"))).get("actual_coverage_delta"), None) for e in recent]
    coverage_deltas = [v for v in coverage_deltas if v is not None]
    return {
        "entry_count": len(entries),
        "recent_count": len(recent),
        "corrected_recent": corrected,
        "skipped_recent": skipped,
        "blocked_recent": blocked,
        "average_visual_delta": None if not visual_deltas else round(sum(visual_deltas) / len(visual_deltas), 3),
        "average_coverage_delta": None if not coverage_deltas else round(sum(coverage_deltas) / len(coverage_deltas), 3),
        "latest_state": recent[-1].get("state") if recent else None,
    }


def format_correction_history(history: dict[str, Any] | None, *, max_entries: int = DISPLAY_LIMIT) -> str:
    history = history if isinstance(history, dict) else {}
    entries = history.get("entries") if isinstance(history.get("entries"), list) else []
    summary = _as_dict(history.get("summary"))
    if not entries:
        return "Correction History: no saved correction history for this profile yet."
    lines = [f"Correction History: {int(summary.get('entry_count', len(entries)) or len(entries))} saved result(s) for profile {history.get('profile_key','generic')}."]
    avg = summary.get("average_visual_delta")
    if avg is not None:
        cov = summary.get("average_coverage_delta")
        lines.append(f"Recent average: Visual {float(avg):+.1f} pp" + (f" · Coverage {float(cov):+.1f} pp" if cov is not None else ""))
    for item in entries[-max(1, int(max_entries)):][::-1]:
        state = str(item.get("state") or "unknown")
        before = item.get("before_visual_accuracy_percent")
        after = item.get("after_visual_accuracy_percent")
        delta = item.get("visual_accuracy_delta")
        coverage_delta = item.get("coverage_delta")
        paths = item.get("executed_paths")
        planned = item.get("planned_correction_paths")
        parts = [state]
        if before is not None and after is not None:
            parts.append(f"Visual {float(before):.1f}% → {float(after):.1f}%")
        elif item.get('operation') == 'read-only-verification':
            parts.append('read-only observation')
            if after is not None:
                parts.append(f'Visual {float(after):.1f}%')
            coverage = item.get('after_coverage_percent')
            if coverage is not None:
                parts.append(f'Coverage {float(coverage):.1f}%')
        if delta is not None:
            parts.append(f"Δ {float(delta):+.1f} pp")
        if coverage_delta is not None:
            parts.append(f"coverage {float(coverage_delta):+.1f} pp")
        if paths is not None or planned is not None:
            parts.append(f"paths {int(paths or 0)}/{int(planned or 0)}")
        lines.append("- " + " · ".join(parts))
    lines.append("Privacy: compact metrics only; no screenshots, crops, hashes or pixels are saved.")
    return "\n".join(lines)


def reset_profile_history(options: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    resolved = _resolved_path(options if isinstance(options, dict) else {}, path)
    with file_transaction(resolved):
        existed = resolved.exists()
        try:
            resolved.unlink()
        except FileNotFoundError:
            pass
        return {"reset": bool(existed), "profile_key": _profile_from_options(options if isinstance(options, dict) else {}), "storage_path": str(resolved)}
