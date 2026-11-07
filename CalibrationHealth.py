\
"""Profile-scoped calibration confidence for Image Draw Bot rc13.

Pure scoring only: this module never captures the screen or sends native input.
Safety-critical palette/layout evidence carries more weight than optional timing
learning, so a fast historical ETA can never mask stale target geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
from RuntimePaths import is_finite_number


def _clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        value = 0.0
    return max(float(low), min(float(high), value)) if math.isfinite(value) else float(low)


def _state_score(item: dict[str, Any] | None, *, optional=False) -> float:
    item = item if isinstance(item, dict) else {}
    state = str(item.get("state") or "unavailable").lower()
    available = bool(item.get("available"))
    confidence = item.get("confidence")
    if 'available' in item and type(item['available']) is not bool:
        return 0.0
    if item.get('available') is False and state in ('verified', 'calibrated'):
        return 0.0
    if confidence is not None and (not is_finite_number(confidence) or not 0 <= confidence <= 1):
        return 0.0
    if confidence is not None:
        base = _clamp(confidence)
    elif state == "verified":
        base = 1.0
    elif state == "calibrated":
        base = .82
    elif state == "estimated":
        base = .55
    elif optional and not available:
        base = .78
    else:
        base = 0.0
    if state == "verified":
        base = max(base, .94)
    elif state == "calibrated":
        base = max(base, .72)
    return _clamp(base)


def _palette_score(item: dict[str, Any] | None) -> float:
    item = item if isinstance(item, dict) else {}
    if 'available' in item and item['available'] is not True:
        return 0.0
    if 'verification' in item and not isinstance(item['verification'], dict):
        return 0.0
    confidence = item.get('confidence')
    if confidence is not None and (not is_finite_number(confidence) or not 0 <= confidence <= 1):
        return 0.0
    verification = item.get('verification') if isinstance(item.get('verification'), dict) else {}
    score = _state_score(item)
    if verification:
        value = verification.get('confidence')
        if value is not None and (not is_finite_number(value) or not 0 <= value <= 1):
            return 0.0
        score = max(score, _clamp(verification.get("confidence")))
    count = item.get('count', 0)
    if type(count) is not int:
        return 0.0
    if count <= 0:
        return 0.0
    if count < 3:
        score = min(score, .35)
    return _clamp(score)


def _timing_score(item: dict[str, Any] | None) -> float:
    item = item if isinstance(item, dict) else {}
    samples = item.get('samples', 0)
    if type(samples) is not int:
        return .55
    if samples <= 0:
        return .55
    depth = min(1.0, samples / 5.0)
    try:
        mape = float(item.get("mape")) if item.get("mape") is not None else .18
    except (TypeError, ValueError, OverflowError):
        mape = 1.0
    if not math.isfinite(mape) or mape < 0:
        mape = 1.0
    quality = max(.20, 1.0 - min(1.0, max(0.0, mape)))
    return _clamp(.55 + .45 * depth * quality)


def _layout_score(delta) -> float:
    if delta is None:
        return 1.0
    if not bool(getattr(delta, "changed", False)):
        return 1.0
    reasons = " ".join(getattr(delta, "reasons", ()) or ()).lower()
    if "dpi " in reasons or "client resize" in reasons:
        return .20
    canvas = max(0, int(getattr(delta, "max_canvas_shift", 0) or 0))
    palette = max(0, int(getattr(delta, "max_palette_shift", 0) or 0))
    shift = max(canvas, palette)
    if shift <= 6:
        return .76
    if shift <= 18:
        return .55
    return .28


@dataclass(frozen=True)
class CalibrationHealth:
    score: float
    level: str
    component_confidence: dict[str, float]
    recalibrate_components: tuple[str, ...]
    blocking: bool
    reason: str

    def as_dict(self):
        return {
            "score": round(float(self.score), 4),
            "level": self.level,
            "component_confidence": {k: round(float(v), 4) for k, v in self.component_confidence.items()},
            "recalibrate_components": list(self.recalibrate_components),
            "blocking": bool(self.blocking),
            "reason": self.reason,
        }


def summarize_calibration_health(summary: dict[str, Any], *, layout_delta=None) -> CalibrationHealth:
    summary = summary if isinstance(summary, dict) else {}
    palette = _palette_score(summary.get("palette"))
    tools = _state_score(summary.get("tools"), optional=True)
    exact = _state_score(summary.get("exact_color"), optional=True)
    timing = _timing_score(summary.get("timing"))
    try:
        layout = _layout_score(layout_delta)
    except (TypeError, ValueError, OverflowError):
        layout = 0.0
    components = {
        "palette": palette,
        "tools": tools,
        "exact_color": exact,
        "timing": timing,
        "layout": layout,
    }
    weights = {"palette": .34, "tools": .16, "exact_color": .10, "timing": .08, "layout": .32}
    score = sum(components[key] * weights[key] for key in weights)
    recalibrate = []
    if palette < .70:
        recalibrate.append("palette")
    if tools < .55:
        recalibrate.append("tools")
    if exact < .50:
        recalibrate.append("exact_color")
    if layout < .70:
        recalibrate.append("layout")
    blocking = palette < .50 or layout < .40
    if blocking:
        level = "unsafe"
    elif score >= .90:
        level = "verified"
    elif score >= .76:
        level = "healthy"
    else:
        level = "degraded"
    reason = "calibration evidence is current" if not recalibrate else "refresh " + ", ".join(recalibrate)
    return CalibrationHealth(_clamp(score), level, components, tuple(recalibrate), blocking, reason)
