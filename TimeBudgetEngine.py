"""Deadline-aware time budgets for Image Draw Bot v1.0.119-beta.

Pure planning helpers.  No mouse, GUI or network access.  The engine separates
*game timer* from the smaller *usable render budget* and keeps a reserve so a
plan is never intentionally scheduled to the timer edge.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any


@dataclass(frozen=True)
class TimePreset:
    name: str
    total_seconds: float | None
    default_render_seconds: float | None
    game: str = "Custom"

    @property
    def default_reserve_seconds(self) -> float:
        if self.total_seconds is None or self.default_render_seconds is None:
            return 0.0
        return max(0.0, float(self.total_seconds) - float(self.default_render_seconds))


PRESETS: dict[str, TimePreset] = {
    "Gartic Phone Fast": TimePreset("Gartic Phone Fast", 75.0, 67.0, "Gartic Phone"),
    "Gartic Phone Normal": TimePreset("Gartic Phone Normal", 150.0, 138.0, "Gartic Phone"),
    "Gartic Phone Slow": TimePreset("Gartic Phone Slow", 300.0, 283.0, "Gartic Phone"),
    "Skribbl Default": TimePreset("Skribbl Default", 80.0, 72.0, "Skribbl.io"),
    "Skribbl 60": TimePreset("Skribbl 60", 60.0, 53.0, "Skribbl.io"),
    "Skribbl 120": TimePreset("Skribbl 120", 120.0, 110.0, "Skribbl.io"),
    "Skribbl 150": TimePreset("Skribbl 150", 150.0, 138.0, "Skribbl.io"),
    "Emergency 30 s": TimePreset("Emergency 30 s", 30.0, 26.0),
    "Ultra Fast 60 s": TimePreset("Ultra Fast 60 s", 60.0, 53.0),
    "Detailed 120 s": TimePreset("Detailed 120 s", 120.0, 110.0),
    "Maximum 300 s": TimePreset("Maximum 300 s", 300.0, 280.0),
    "Unlimited / Accuracy": TimePreset("Unlimited / Accuracy", None, None),
}

# Kept for backward-compatible settings and tests.  These names map to a total
# timer and then use the scalable reserve unless an old caller explicitly asks
# for legacy resolution through TimeBudget.resolve_time_budget_seconds.
LEGACY_TOTALS = {
    "30 sec": 30.0,
    "60 sec": 60.0,
    "90 sec": 90.0,
    "2 min": 120.0,
    "5 min": 300.0,
    "10 min": 600.0,
}


def automatic_reserve(total_seconds: float) -> float:
    """Continuous reserve used by Custom/legacy deadline presets.

    Interpolate established timer anchors instead of jumping to a new minimum
    at 30, 80, 150 and 300 seconds. Every segment grows more slowly than the
    timer, so increasing it cannot reduce the usable drawing budget. Built-in
    game presets keep their separately specified reserves.
    """
    total = float(total_seconds)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Time budget must be finite and positive.")
    total = max(5.0, total)
    anchors = ((5.0, 3.0), (30.0, 3.45), (60.0, 7.0), (80.0, 8.4),
               (90.0, 10.0), (120.0, 10.2), (150.0, 12.75), (180.0, 15.0),
               (300.0, 19.5), (400.0, 20.0), (600.0, 30.0))
    for (start, reserve_start), (end, reserve_end) in zip(anchors, anchors[1:]):
        if total <= end:
            return reserve_start + (total - start) * (reserve_end - reserve_start) / (end - start)
    return 30.0


def _custom_reserve(raw: Any, total: float) -> float:
    text = str(raw if raw is not None else "Auto").strip()
    lowered = text.lower()
    if not text or lowered == "auto":
        return automatic_reserve(total)
    # Advanced explicit opt-out. Auto remains the safe default everywhere.
    if lowered in ("off", "none", "disabled"):
        return 0.0
    try:
        value = float(text)
    except (TypeError, ValueError):
        return automatic_reserve(total)
    if not math.isfinite(value):
        return automatic_reserve(total)
    if value <= 0:
        return 0.0
    return max(1.0, min(total * .45, value))


def resolve_budget(mode: str, manual_seconds: float | int = 180,
                   reserve: Any = "Auto") -> dict[str, Any]:
    """Resolve timer, safety reserve and usable drawing budget.

    ``Manual`` is intentionally legacy/non-adaptive. ``Custom`` is the new
    deadline-aware manual timer. This preserves old saved settings while giving
    the new renderer an unambiguous opt-in custom target.
    """
    mode = str(mode or "Manual").strip()
    try:
        manual = float(manual_seconds)
    except (TypeError, ValueError):
        manual = 180.0
    if mode in ("Manual", "Custom") and (not math.isfinite(manual) or not 5 <= manual <= 3600):
        raise ValueError("Time limit must be 5–3600 seconds.")

    if mode in ("Unlimited", "Unlimited / Accuracy"):
        return {
            "mode": mode, "active": False, "unlimited": True,
            "total_seconds": None, "reserve_seconds": 0.0,
            "render_budget_seconds": None, "status": "UNLIMITED",
            "source": "unlimited accuracy mode",
        }
    if mode == "Manual":
        return {
            "mode": mode, "active": False, "unlimited": False,
            "total_seconds": manual, "reserve_seconds": 0.0,
            "render_budget_seconds": manual, "status": "MANUAL",
            "source": "legacy manual limit",
        }

    preset = PRESETS.get(mode)
    if preset is not None:
        total = float(preset.total_seconds or manual)
        default_reserve = preset.default_reserve_seconds
        resolved_reserve = default_reserve if str("Auto" if reserve is None else reserve).strip().lower() == "auto" else _custom_reserve(reserve, total)
        usable = max(1.0, total - resolved_reserve)
        return {
            "mode": mode, "active": True, "unlimited": False,
            "game": preset.game, "total_seconds": total,
            "reserve_seconds": resolved_reserve,
            "render_budget_seconds": usable, "hard_stop_seconds": total, "status": "PENDING",
            "source": "built-in game preset",
        }

    if mode in LEGACY_TOTALS:
        # v1.0.119: legacy generic timers are deadline-aware too. Older builds
        # accidentally used the complete game timer as drawing time, leaving no
        # reserve for browser focus/input jitter or the last mouse-up.
        total = float(LEGACY_TOTALS[mode])
        resolved_reserve = _custom_reserve(reserve, total)
        usable = max(1.0, total - resolved_reserve)
        return {
            "mode": mode, "active": True, "unlimited": False,
            "total_seconds": total, "reserve_seconds": resolved_reserve,
            "render_budget_seconds": usable, "hard_stop_seconds": total,
            "status": "PENDING", "source": "legacy preset + safety reserve",
        }

    if mode == "Custom":
        total = manual
        resolved_reserve = _custom_reserve(reserve, total)
        return {
            "mode": mode, "active": True, "unlimited": False,
            "total_seconds": total, "reserve_seconds": resolved_reserve,
            "render_budget_seconds": max(1.0, total - resolved_reserve), "hard_stop_seconds": total,
            "status": "PENDING", "source": "custom deadline",
        }
    raise ValueError("Choose a valid time budget mode.")


def classify_budget(estimated_seconds: float, budget_seconds: float | None) -> str:
    try:
        estimate = float(estimated_seconds)
        if not math.isfinite(estimate) or estimate < 0:
            return "PANIC"
        if budget_seconds is None:
            return "SAFE"
        budget = float(budget_seconds)
        if not math.isfinite(budget) or budget <= 0:
            return "PANIC"
    except (TypeError, ValueError, OverflowError):
        return "PANIC"
    ratio = estimate / budget
    if ratio <= .88:
        return "SAFE"
    if ratio <= 1.0:
        return "CLOSE"
    if ratio <= 1.18:
        return "OVER BUDGET"
    return "PANIC"


def time_preset_names() -> tuple[str, ...]:
    return tuple(PRESETS)
