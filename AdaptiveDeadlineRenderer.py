"""Adaptive deadline planning for Image Draw Bot v1.0.119-beta.

Turns an already geometry-safe execution plan into the highest-value subset that
fits the real game deadline.  It never mutates pixel colours or invents shortcut
geometry.  Region Fill remains a separate safe prelude; this module schedules
remaining brush paths around its measured/modelled cost.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any

from Precision import CanvasTransform, precision_path_count
from SpeedOptimizer import normalize_speed, phase_delay
from StrokeDelivery import resolve_stroke_delivery
from TimeBudgetEngine import resolve_budget, classify_budget
from VisualImportanceMap import build_importance_map, sample_path_importance


PHASES = ("major_coverage", "structure", "important_details", "accuracy", "correction")
PHASE_LABELS = {
    "major_coverage": "major coverage",
    "structure": "structure / silhouettes",
    "important_details": "important details",
    "accuracy": "accuracy",
    "correction": "targeted correction",
}


@dataclass
class DeadlineEntry:
    color_index: int
    path: tuple
    source_index: int
    estimated_cost_seconds: float
    importance: float
    structural_score: float
    value_score: float
    phase: str
    optional: bool
    center: tuple[float, float]
    operation_type: str = "stroke"

    def as_sequence_entry(self) -> dict[str, Any]:
        return {
            "color_index": int(self.color_index), "path": tuple(self.path),
            "phase": self.phase, "deadline_phase": self.phase,
            "estimated_cost_seconds": round(float(self.estimated_cost_seconds), 6),
            "importance": round(float(self.importance), 6),
            "structural_score": round(float(self.structural_score), 6),
            "value_score": round(float(self.value_score), 6),
            "optional": bool(self.optional), "source_index": int(self.source_index),
            "operation_type": str(self.operation_type),
        }


def _path_geometry(path, source_size: tuple[int, int]) -> tuple[float, float, float, tuple[float, float]]:
    if not path:
        return 0.0, 0.0, 0.0, (0.0, 0.0)
    xs = [float(p[0]) for p in path]; ys = [float(p[1]) for p in path]
    w, h = max(1, int(source_size[0])), max(1, int(source_size[1]))
    diag = max(1.0, math.hypot(w, h))
    span = math.hypot(max(xs)-min(xs), max(ys)-min(ys)) / diag
    length = sum(math.hypot(float(b[0]-a[0]), float(b[1]-a[1])) for a,b in zip(path,path[1:])) / diag
    closed = 1.0 if len(path) >= 4 and math.hypot(path[0][0]-path[-1][0], path[0][1]-path[-1][1]) <= 3.0 else 0.0
    return min(1.0, span), min(2.0, length), closed, (sum(xs)/len(xs), sum(ys)/len(ys))


def _operation_type(path, span: float, closed: float, length: float) -> str:
    if len(path) <= 1:
        return "dot"
    if closed >= .5:
        return "outline"
    if length <= .055 and span <= .06:
        return "short_stroke"
    return "long_stroke"


def _path_cost(path, transform: CanvasTransform, options: dict[str, Any]) -> float:
    delivery = resolve_stroke_delivery(options, dry_run=False)
    speed = normalize_speed(options.get("speed", "Balanced"))
    delay = float(options.get("delay", 0.0) or 0.0)
    path_wait = max(float(delivery.min_path_delay), float(phase_delay(delay, speed, "path")))
    travel_wait = max(.0005, float(phase_delay(delay, speed, "travel")))
    boundary_wait = max(.0005, float(phase_delay(delay, speed, "boundary")))
    precision = str(options.get("precision") or "High")
    if len(path) <= 1:
        return travel_wait + .015 + delivery.press_settle + delivery.release_settle + .0015
    moves = 0
    for a, b in zip(path, path[1:]):
        if a == b:
            continue
        moves += precision_path_count(transform.point(*a), transform.point(*b), precision, delivery.step_px)
    return (travel_wait + boundary_wait + delivery.press_settle + delivery.release_settle +
            moves * path_wait + .0015)


def _fixed_overhead(options: dict[str, Any], groups, image_size, fitted) -> tuple[float, dict[str, float]]:
    delivery = resolve_stroke_delivery(options, dry_run=False)
    active_colors = sum(any(bool(path) for path in g) for g in groups)
    palette = 0.0 if options.get("paint_current_color") else active_colors * delivery.palette_click_delay
    tool = len(options.get("tool_actions") or ()) * delivery.ui_control_delay
    clear = max(0.0, float(options.get("canvas_clear_estimate_seconds", 0.0) or 0.0))
    fill = 0.0
    regions = options.get("fill_regions") or []
    if regions:
        try:
            from RegionFillEngine import estimate_fill_execution_seconds
            fill = float(estimate_fill_execution_seconds(regions, image_size, fitted, options).get("total_seconds", 0.0) or 0.0)
        except Exception:
            fill = len(regions) * max(.12, delivery.ui_control_delay + .04)
    bg = options.get("background_fill_plan") or {}
    if bg.get("enabled"):
        fill += .34 + (len(options.get("fill_tool_actions") or ()) + len(options.get("fill_restore_actions") or ())) * delivery.ui_control_delay
    custom_selectors=sum(1 for x in (options.get('color_selectors') or ()) if isinstance(x,dict) and x.get('kind')=='custom')
    custom_color=custom_selectors*(.78 if options.get('exact_color_available') else 0.0)
    verification=0.0
    if options.get('adaptive_color_verification'):
        verification += active_colors*(delivery.palette_click_delay+.14)
    if options.get('visual_verification_enabled'):
        verification += active_colors*.08
    countdown = 3.0
    path_count=sum(sum(bool(path) for path in (g or ())) for g in groups)
    focus = 0.0 if options.get("paint_profile") else .35
    guard = min(1.8, path_count * .0009)
    scheduler_jitter = min(2.8, .25 + path_count * .0018)
    total=countdown + palette + tool + clear + fill + custom_color + verification + focus + guard + scheduler_jitter
    return total, {
        "countdown_seconds": countdown, "palette_seconds": palette, "tool_seconds": tool,
        "clear_seconds": clear, "fill_seconds": fill,
        "custom_color_seconds": custom_color, "verification_seconds": verification,
        "focus_seconds": focus, "canvas_guard_seconds": guard,
        "scheduler_jitter_seconds": scheduler_jitter,
    }


def _phase_for(importance: float, span: float, closed: float, length: float) -> str:
    structural = min(1.0, span * 1.65 + closed * .25 + min(1.0, length) * .18)
    if structural >= .58 or span >= .34:
        return "major_coverage"
    if importance >= .66 or structural >= .34:
        return "structure"
    if importance >= .50:
        return "important_details"
    if importance >= .31:
        return "accuracy"
    return "correction"


def _calibration_guard(options: dict[str, Any], budget_seconds: float) -> tuple[float, dict[str, Any]]:
    try:
        from DrawTimeCalibration import correction_for
        cal = correction_for(options)
    except Exception:
        cal = {"samples": 0, "ratio": 1.0, "mape": None, "learned": False}
    samples = int(cal.get("samples") or 0)
    ratio = max(.55, min(4.0, float(cal.get("ratio") or 1.0)))
    mape = cal.get("mape")
    try: mape = max(0.0, min(.60, float(mape))) if mape is not None else None
    except Exception: mape = None
    if samples <= 0:
        multiplier = 1.28
        uncertainty = min(10.0, max(2.5, budget_seconds * .08))
        stage = "cold-start"
    elif samples == 1:
        multiplier = max(1.18, ratio)
        uncertainty = min(7.0, max(1.5, budget_seconds * max(.045, mape or .10)))
        stage = "learning-1"
    elif samples == 2:
        multiplier = max(1.08, ratio)
        uncertainty = min(5.0, max(1.0, budget_seconds * max(.035, mape or .07)))
        stage = "learning-2"
    else:
        multiplier = ratio
        uncertainty = min(4.0, budget_seconds * max(.02, min(.12, mape or .06)))
        stage = "measured"
    return uncertainty, {"samples": samples, "ratio": ratio, "mape": mape,
                         "cost_multiplier": round(multiplier,6),
                         "uncertainty_reserve_seconds": uncertainty,
                         "confidence_stage": stage}


def _local_batch(entries: list[DeadlineEntry], window: int = 18) -> list[DeadlineEntry]:
    """Small-window colour/spatial batching without destroying progressive order."""
    out: list[DeadlineEntry] = []
    previous = None
    for start in range(0, len(entries), window):
        chunk = list(entries[start:start+window])
        while chunk:
            if previous is None:
                chosen_i = max(range(len(chunk)), key=lambda i: chunk[i].value_score)
            else:
                px, py, pc = previous
                def key(i):
                    e = chunk[i]
                    dist = math.hypot(e.center[0]-px, e.center[1]-py)
                    color_bonus = .25 if e.color_index == pc else 0.0
                    return e.value_score + color_bonus - dist * .00035
                chosen_i = max(range(len(chunk)), key=key)
            e = chunk.pop(chosen_i)
            out.append(e); previous = (e.center[0], e.center[1], e.color_index)
    return out


def adapt_execution_plan(image, fitted: tuple[int, int], execution_groups, options: dict[str, Any], *, cancelled=lambda: False):
    """Return (groups, progressive_sequence, metadata, importance_map).

    If the selected mode has no active deadline, the original groups are returned.
    """
    budget = resolve_budget(options.get("time_budget_mode", "Manual"),
                            options.get("manual_max_seconds", options.get("max_seconds", 180)),
                            options.get("deadline_safety_reserve", "Auto"))
    if not bool(options.get("adaptive_deadline_renderer", True)) or not budget.get("active") or execution_groups is None:
        return execution_groups, None, {**budget, "enabled": False, "reason": "deadline renderer inactive"}, None
    if cancelled():
        raise InterruptedError()

    importance, importance_meta = build_importance_map(image, options, cancelled)
    transform = CanvasTransform(image.width, image.height, fitted)
    entries: list[DeadlineEntry] = []
    serial = 0
    for color_index, paths in enumerate(execution_groups):
        for path in paths:
            if cancelled(): raise InterruptedError()
            path = tuple(path)
            if not path:
                continue
            imp = sample_path_importance(path, importance)
            span, length, closed, center = _path_geometry(path, image.size)
            structural = min(1.0, span * 1.55 + closed * .25 + min(1.0, length) * .20)
            phase = _phase_for(imp, span, closed, length)
            value = max(.01, imp * .62 + structural * .30 + min(1.0, length) * .08)
            cost = _path_cost(path, transform, options)
            entries.append(DeadlineEntry(color_index, path, serial, cost, imp, structural, value,
                                         phase, phase in ("accuracy", "correction"), center,
                                         _operation_type(path, span, closed, length)))
            serial += 1

    fixed, fixed_meta = _fixed_overhead(options, execution_groups, image.size, fitted)
    render_budget = float(budget.get("render_budget_seconds") or options.get("max_seconds") or 180)
    uncertainty, cal_meta = _calibration_guard(options, render_budget)
    cost_multiplier=max(.55,min(4.0,float(cal_meta.get("cost_multiplier") or cal_meta.get("ratio") or 1.0)))
    for e in entries:
        e.estimated_cost_seconds *= cost_multiplier
    fixed *= cost_multiplier
    fixed_meta={k:(float(v)*cost_multiplier if isinstance(v,(int,float)) else v) for k,v in fixed_meta.items()}
    path_budget = max(0.0, render_budget - fixed - uncertainty)

    before_cost = fixed + sum(e.estimated_cost_seconds for e in entries)
    selected: list[DeadlineEntry] = []
    used = 0.0

    # Preserve one strong path per coarse spatial cell before optional detail.
    w, h = image.size
    cell_best: dict[tuple[int,int], DeadlineEntry] = {}
    for e in entries:
        if e.phase not in ("major_coverage", "structure"):
            continue
        cx = min(3, max(0, int(e.center[0] / max(1, w) * 4)))
        cy = min(3, max(0, int(e.center[1] / max(1, h) * 4)))
        old = cell_best.get((cx,cy))
        if old is None or e.value_score > old.value_score:
            cell_best[(cx,cy)] = e
    seeded = sorted(cell_best.values(), key=lambda e: -e.value_score)
    chosen_ids = set()
    for e in seeded:
        if used + e.estimated_cost_seconds <= path_budget:
            selected.append(e); chosen_ids.add(e.source_index); used += e.estimated_cost_seconds

    phase_weight = {"major_coverage": 1.40, "structure": 1.28, "important_details": 1.12,
                    "accuracy": .78, "correction": .45}
    candidates = [e for e in entries if e.source_index not in chosen_ids]
    candidates.sort(key=lambda e: (PHASES.index(e.phase), -(e.value_score * phase_weight[e.phase] / max(.001, e.estimated_cost_seconds)), e.source_index))
    for e in candidates:
        if used + e.estimated_cost_seconds <= path_budget:
            selected.append(e); chosen_ids.add(e.source_index); used += e.estimated_cost_seconds

    # Progressive order first, then bounded local colour/travel optimisation.
    ordered: list[DeadlineEntry] = []
    for phase in PHASES:
        block = [e for e in selected if e.phase == phase]
        block.sort(key=lambda e: (-e.value_score, e.source_index))
        ordered.extend(_local_batch(block))

    filtered = [[] for _ in execution_groups]
    for e in selected:
        filtered[e.color_index].append(e.path)
    sequence = [e.as_sequence_entry() for e in ordered]
    selected_cost = fixed + sum(e.estimated_cost_seconds for e in selected)
    dropped = len(entries) - len(selected)
    phase_counts = {p: sum(1 for e in selected if e.phase == p) for p in PHASES}
    dropped_importance = [e.importance for e in entries if e.source_index not in chosen_ids]
    safe_estimate=selected_cost + uncertainty
    status = classify_budget(safe_estimate, render_budget)
    operation_counts={}
    for e in selected:
        operation_counts[e.operation_type]=operation_counts.get(e.operation_type,0)+1
    active_colors=len({e.color_index for e in selected})
    operation_counts.update({
        "palette_change":active_colors if not options.get("paint_current_color") else 0,
        "tool_change":len(options.get("tool_actions") or ()),
        "fill":len(options.get("fill_regions") or ()) + (1 if (options.get("background_fill_plan") or {}).get("enabled") else 0),
        "verification":active_colors if options.get("adaptive_color_verification") else 0,
        "focus_change":0 if options.get("paint_profile") else 1,
    })
    meta = {
        **budget,
        "enabled": True,
        "engine": "Adaptive Deadline Renderer",
        "source_paths": len(entries), "selected_paths": len(selected), "dropped_paths": dropped,
        "dropped_low_priority_paths": sum(1 for e in entries if e.source_index not in chosen_ids and e.importance < .50),
        "selected_path_cost_seconds": round(sum(e.estimated_cost_seconds for e in selected), 4),
        "fixed_overhead_seconds": round(fixed, 4),
        "estimated_before_seconds": round(before_cost, 4),
        "estimated_after_seconds": round(selected_cost, 4),
        "effective_estimated_seconds": round(safe_estimate, 4),
        "estimated_range_seconds": [round(selected_cost,4), round(safe_estimate,4)],
        "planning_guard_seconds": round(uncertainty, 4),
        "operation_counts": operation_counts,
        "operation_timing_model": "typed operations + local profile calibration",
        "budget_status": status,
        "phase_counts": phase_counts,
        "calibration": cal_meta,
        "importance": importance_meta,
        "fixed_overhead": fixed_meta,
        "average_dropped_importance": round(sum(dropped_importance)/len(dropped_importance), 5) if dropped_importance else 0.0,
        "quality_retained_percent": round(100.0 * sum(e.value_score for e in selected) / max(.001, sum(e.value_score for e in entries)), 2) if entries else 100.0,
        "progressive_phase_order": "major coverage -> structure -> important details -> accuracy -> correction",
    }
    return filtered, sequence, meta, importance
