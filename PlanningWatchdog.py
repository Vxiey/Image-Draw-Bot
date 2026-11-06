"""Planning watchdog and fallback attempts for Image Draw Bot v1.0.22.

The watchdog protects the safety boundary before mouse input is armed. It does
not move the cursor and it never bypasses Start Guard/Preflight. It only builds a
small list of progressively safer planning configurations so a heavy final plan
can fall back to a lighter one instead of appearing frozen for a long time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Any

PLANNING_WATCHDOG_MODES = ("Auto", "On", "Off")


@dataclass(frozen=True)
class PlanningAttempt:
    index: int
    total: int
    name: str
    options: dict
    timeout_seconds: float | None
    fallback: bool = False


def validate_planning_watchdog(value: str) -> str:
    if value not in PLANNING_WATCHDOG_MODES:
        raise ValueError("Planning watchdog must be Auto, On, or Off.")
    return value


def watchdog_enabled(value: str = "Auto", *, preview: bool = False, test: bool = False) -> bool:
    validate_planning_watchdog(value)
    if value == "On":
        return True
    if value == "Off":
        return False
    # Preview already has its own strict light-planning path. Small tests must
    # stay exact and fast; falling back there would hide calibration problems.
    return not preview and not test


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _base_timeout(options: Mapping[str, Any]) -> float:
    raw = options.get("planning_timeout_seconds", 75)
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        value = 75.0
    if not math.isfinite(value):
        value = 75.0
    return max(12.0, min(120.0, value))


def _reduced_target(current: Any, *, ceiling: int) -> str:
    if current in (None, "Auto", "Unlimited"):
        return str(ceiling)
    try:
        return str(max(50, min(int(current), ceiling)))
    except (TypeError, ValueError, OverflowError):
        return str(ceiling)


def _with_meta(options: Mapping[str, Any], name: str, *, timeout: float | None,
               fallback_level: int, overrides: Mapping[str, Any] | None = None) -> dict:
    out = dict(options)
    if overrides:
        out.update(overrides)
    out["planning_attempt_name"] = name
    out["planning_watchdog_fallback_level"] = int(fallback_level)
    out["planning_watchdog_attempt_timeout_seconds"] = None if timeout is None else float(timeout)
    return out


def build_planning_attempts(options: Mapping[str, Any], *, test: bool = False,
                            preview: bool = False, dry_run: bool = False) -> list[PlanningAttempt]:
    """Return primary + fallback attempt configurations.

    Fallbacks deliberately trade quality for responsiveness: Standard planning
    resolution, Threads instead of Processes, less colour layering, smaller caps
    and reduced background/fill work.  They preserve the user's actual safety
    settings, target profile, canvas and input locks.
    """
    if dry_run:
        from FastDryRun import DRY_RUN_PLANNING_SECONDS
        timeout=float(DRY_RUN_PLANNING_SECONDS)
        opts=_with_meta(options, "Fast calibrated dry run", timeout=timeout, fallback_level=0, overrides={
            "planning_resolution":"Standard", "cpu_engine":"Threads",
            "cpu_workers_resolved":min(max(1,_as_int(options.get("cpu_workers_resolved"),4)),4),
            "gpu_mode":"CPU", "color_layers":"Off", "background_fill":"Off", "use_region_fill_engine":False,
            "background_simplification":"Strong", "target_stroke_count":"500",
            "target_stroke_count_resolved":500, "max_stroke_cap":"1000",
            "planning_timeout_seconds":timeout, "visual_verification_enabled":False,
        })
        return [PlanningAttempt(1,1,"Fast calibrated dry run",opts,timeout,False)]
    mode = str(options.get("planning_watchdog", "Auto"))
    enabled = watchdog_enabled(mode, preview=preview, test=test)
    base = _base_timeout(options)
    primary_timeout = None if mode == 'Off' else base if not enabled else min(base, 24.0)

    attempts: list[tuple[str, dict, float | None, bool]] = [(
        "Primary settings",
        _with_meta(options, "Primary settings", timeout=primary_timeout, fallback_level=0),
        primary_timeout,
        False,
    )]

    if enabled:
        speed = options.get("speed", "Balanced")
        first_target = _reduced_target(options.get("target_stroke_count_resolved"), ceiling=2500 if speed != "Fast" else 1800)
        attempts.append((
            "Fallback 1: safe standard planner",
            _with_meta(options, "Fallback 1: safe standard planner", timeout=20.0, fallback_level=1, overrides={
                "planning_resolution": "Standard",
                "cpu_engine": "Threads",
                "cpu_workers": "Auto",
                "cpu_workers_resolved": min(max(1, _as_int(options.get("cpu_workers_resolved"), 4)), 6),
                "color_layers": "Off",
                "background_fill": "Conservative" if options.get("background_fill") != "Off" else "Off",
                "background_simplification": "Balanced",
                "target_stroke_count": first_target,
                "target_stroke_count_resolved": int(first_target),
                "max_stroke_cap": "2500" if options.get("max_stroke_cap") not in ("1000", "2500") else options.get("max_stroke_cap"),
                "planning_timeout_seconds": 20,
            }),
            20.0,
            True,
        ))
        final_target = _reduced_target(options.get("target_stroke_count_resolved"), ceiling=1200)
        attempts.append((
            "Fallback 2: emergency fast planner",
            _with_meta(options, "Fallback 2: emergency fast planner", timeout=16.0, fallback_level=2, overrides={
                "planning_resolution": "Standard",
                "cpu_engine": "Threads",
                "cpu_workers": "Auto",
                "cpu_workers_resolved": min(max(1, _as_int(options.get("cpu_workers_resolved"), 3)), 4),
                "gpu_mode": "CPU",
                "gpu_performance": "Balanced",
                "color_rendering": "RGB nearest",
                "color_layers": "Off",
                "custom_color_workflow": "Calibrated palette",
                "background_fill": "Off",
                "use_region_fill_engine": False,
                "background_simplification": "Strong",
                "target_stroke_count": final_target,
                "target_stroke_count_resolved": int(final_target),
                "max_stroke_cap": "1000" if options.get("drawing_mode") == "Shape paths" else options.get("max_stroke_cap", "Auto"),
                "planning_timeout_seconds": 16,
            }),
            16.0,
            True,
        ))

    if (options.get("time_budget_mode") in ("Unlimited", "Unlimited / Accuracy")
            or options.get("unlimited_time") or options.get("draw_quality") == 'Pixel Accurate'):
        for _name, opts, _timeout, fallback in attempts:
            if fallback:
                for key in ("target_stroke_count", "target_stroke_count_resolved", "max_stroke_cap",
                            "background_simplification", "color_rendering", "custom_color_workflow",
                            "planning_resolution", "color_layers", "background_fill", "use_region_fill_engine"):
                    if key in options:
                        opts[key] = options[key]
                    else:
                        opts.pop(key, None)
    total = len(attempts)
    return [PlanningAttempt(i + 1, total, name, opts, timeout, fallback)
            for i, (name, opts, timeout, fallback) in enumerate(attempts)]
