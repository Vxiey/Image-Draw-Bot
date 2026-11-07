"""Time-budget and target-stroke controls for Image Draw Bot v1.0.20.

This module is intentionally pure and deterministic. It does not touch Tk,
mouse input, files, network, GPU state or calibration.  DrawBot uses it to turn
user-facing budget controls into conservative planning caps before the guarded
mouse is armed.
"""
from __future__ import annotations

import math
import heapq
from typing import Sequence

Point = tuple[int, int]
Path = tuple[Point, ...]

TIME_BUDGET_MODES = (
    "Manual", "Custom",
    "Gartic Phone Fast", "Gartic Phone Normal", "Gartic Phone Slow",
    "Skribbl Default", "Skribbl 60", "Skribbl 120", "Skribbl 150",
    "Emergency 30 s", "Ultra Fast 60 s", "Detailed 120 s", "Maximum 300 s",
    "Unlimited / Accuracy",
    # Legacy names remain valid for old profile/settings files.
    "Unlimited", "30 sec", "60 sec", "90 sec", "2 min", "5 min", "10 min",
)
TARGET_STROKE_COUNTS = ("Auto", "500", "1000", "2500", "5000", "10000", "Custom", "Unlimited")

_TIME_SECONDS = {
    "30 sec": 30,
    "60 sec": 60,
    "90 sec": 90,
    "2 min": 120,
    "5 min": 300,
    "10 min": 600,
}


def validate_time_budget_mode(value: str) -> str:
    if value not in TIME_BUDGET_MODES:
        raise ValueError("Choose a valid time budget mode.")
    return value


def validate_target_stroke_count(value: str) -> str:
    if value not in TARGET_STROKE_COUNTS:
        raise ValueError("Choose a valid target stroke count.")
    return value


def parse_custom_stroke_count(value: str | int | None) -> int:
    try:
        count = int(str(value or "").strip())
    except (TypeError, ValueError):
        raise ValueError("Custom target stroke count must be a whole number.") from None
    if not 50 <= count <= 50000:
        raise ValueError("Custom target stroke count must be 50–50000.")
    return count


def resolve_time_budget_seconds(mode: str, manual_seconds: int | float) -> tuple[int, bool]:
    """Return usable render seconds and whether deadline adaptation is active.

    New v1.0.119 presets and legacy generic timers reserve time before the real game deadline. Legacy
    Manual keeps its historical behavior for compatibility.
    """
    validate_time_budget_mode(mode)
    from TimeBudgetEngine import resolve_budget
    meta = resolve_budget(mode, manual_seconds, "Auto")
    if meta.get("unlimited"):
        return 3600, False
    return max(1, int(round(float(meta.get("render_budget_seconds") or manual_seconds)))), bool(meta.get("active"))


def resolve_time_budget_details(mode: str, manual_seconds: int | float, reserve="Auto") -> dict:
    validate_time_budget_mode(mode)
    from TimeBudgetEngine import resolve_budget
    return resolve_budget(mode, manual_seconds, reserve)


def _auto_count_from_time(seconds: int, speed: str, drawing_mode: str, *, preview: bool = False) -> int:
    """Conservative path-count target derived from a visible time budget.

    It is deliberately not a guarantee; exact draw time still depends on path
    length, precision, palette changes and Fill/tool actions.  The final estimate
    remains the hard safety gate in DrawBot.
    """
    from SpeedOptimizer import normalize_speed
    speed = normalize_speed(str(speed or "Balanced"))
    if speed == "Fast":
        paths_per_second = 8.0
    elif speed == "Safe":
        paths_per_second = 3.8
    else:
        paths_per_second = 5.7
    mode = str(drawing_mode or "")
    if mode == "Shape paths":
        paths_per_second *= 1.20
    elif mode == "Dots":
        paths_per_second *= 0.55
    elif mode.startswith("Smart paths"):
        paths_per_second *= 0.95
    # Reserve time for countdown, palette/tool changes, target activation and
    # small planner inaccuracies. Preview gets a tighter cap so it appears fast.
    drawable_seconds = max(2.0, float(seconds) - (8.0 if not preview else 2.0))
    target = int(drawable_seconds * paths_per_second)
    floor = 120 if not preview else 80
    ceiling = 12000 if not preview else 3000
    return max(floor, min(ceiling, target))


def resolve_target_stroke_count(value: str, custom_value: str | int | None = None, *,
                                time_budget_mode: str = "Manual",
                                effective_time_seconds: int = 180,
                                speed: str = "Balanced",
                                drawing_mode: str = "Smart paths (recommended)",
                                preview: bool = False) -> tuple[int | None, dict]:
    """Resolve a target path cap and explanatory metadata.

    None means unlimited.  Auto only creates a cap when a preset time budget is
    active; Manual+Auto preserves existing behaviour.
    """
    validate_target_stroke_count(value)
    validate_time_budget_mode(time_budget_mode)
    source = value
    if value == "Unlimited":
        resolved = None
        reason = "unlimited"
    elif value == "Custom":
        resolved = parse_custom_stroke_count(custom_value)
        reason = "custom"
    elif value == "Auto":
        if time_budget_mode in ("Manual", "Unlimited", "Unlimited / Accuracy"):
            resolved = None
            reason = "manual-auto"
        else:
            resolved = _auto_count_from_time(effective_time_seconds, speed, drawing_mode, preview=preview)
            reason = "time-budget-auto"
    else:
        resolved = int(value)
        reason = "explicit"
    return resolved, {
        "target_stroke_count": source,
        "target_stroke_count_resolved": resolved,
        "target_stroke_count_reason": reason,
        "time_budget_mode": time_budget_mode,
        "time_budget_seconds": int(effective_time_seconds),
        "time_budget_active": time_budget_mode not in ("Manual", "Unlimited", "Unlimited / Accuracy"),
    }


def _path_len(path: Sequence[Point]) -> float:
    if len(path) < 2:
        return 0.0
    return sum(math.hypot(float(b[0] - a[0]), float(b[1] - a[1])) for a, b in zip(path, path[1:]))


def _importance_score(path: Sequence[Point], serial: int, *, prioritize_structure: bool = False) -> float:
    # Long paths are usually large visible shapes. Single-point details still get
    # a small score so a low cap keeps some dots instead of only outlines.
    length=_path_len(path)
    score=length + (2.5 if len(path) == 1 else 0.0)
    if prioritize_structure and path:
        xs=[float(p[0]) for p in path];ys=[float(p[1]) for p in path]
        span=math.hypot(max(xs)-min(xs),max(ys)-min(ys))
        closed=(len(path)>=4 and math.hypot(float(path[0][0]-path[-1][0]),float(path[0][1]-path[-1][1]))<=3.0)
        # v1.0.77: a tight real-time budget should preserve recognizable
        # structure before micro-detail. Large/closed contours receive a strong
        # deterministic bonus while isolated dots remain low priority.
        score += span*(1.65 if closed else .75)
        if closed:score += length*.30
        if len(path)==1:score *= .35
    return score - serial * 1e-9


def _aligned_phase_hints(groups, phase_hints):
    if phase_hints is None:
        return None
    hints=[]
    for index, group in enumerate(groups):
        raw=list(phase_hints[index]) if index < len(phase_hints) else []
        hints.append(raw if len(raw)==len(group) else [None]*len(group))
    return hints


def _prefix_counts(groups, values):
    raw=list(values or ())
    counts=[]
    for index, group in enumerate(groups):
        try:value=int(raw[index]) if index < len(raw) else 0
        except (TypeError,ValueError,OverflowError):value=0
        counts.append(max(0,min(len(group),value)))
    return counts


def apply_target_path_cap(groups: Sequence[Sequence[Path]], cap: int | None, *,
                          prioritize_structure: bool = False, phase_hints=None,
                          protected_prefix_counts=None) -> tuple[list[list[Path]], dict]:
    """Keep important paths while preserving semantic execution barriers.

    List-compatible execution metadata from ``ContinuousPaths.ExecutionGroups``
    is consumed automatically. Protected prefixes are selected before ordinary
    detail, while paths inside each class retain the established visual score.
    Phase hints are filtered with the exact same kept path indices and returned
    in metadata so DrawBot's existing ``path_meta.update`` keeps them aligned.
    """
    original = [paths if isinstance(paths, Sequence) else list(paths) for paths in groups]
    inherited_hints=getattr(groups,'phase_hints',None)
    inherited_prefixes=getattr(groups,'protected_prefix_counts',None)
    inherited_semantic=getattr(groups,'semantic_meta',None)
    hints=_aligned_phase_hints(original, phase_hints if phase_hints is not None else inherited_hints)
    prefixes=_prefix_counts(original, protected_prefix_counts if protected_prefix_counts is not None else inherited_prefixes)
    normalized = []
    for index, paths in enumerate(original):
        kept = [position for position, path in enumerate(paths) if path]
        normalized.append([tuple(paths[position]) for position in kept])
        if hints is not None:
            hints[index] = [hints[index][position] for position in kept]
        prefixes[index] = sum(position < prefixes[index] for position in kept)
    semantic=dict(inherited_semantic or {}) if isinstance(inherited_semantic,dict) else {}
    before=sum(len(paths) for paths in normalized)
    protected_before=sum(prefixes)

    def wrap(result, result_hints, prefix_after):
        if hints is None and not semantic and not any(prefixes):
            return result
        try:
            from ContinuousPaths import ExecutionGroups
            meta=dict(semantic)
            if 'portrait_semantic_barrier' in meta:
                meta['portrait_outline_paths_after_cap']=sum(prefix_after)
            return ExecutionGroups(result, phase_hints=result_hints,
                                   protected_prefix_counts=prefix_after, semantic_meta=meta)
        except Exception:
            return result

    def metadata(after, prefix_after, skipped, result_hints):
        meta={
            'target_before_paths':before,'target_after_paths':after,
            'target_skipped_paths':skipped,'structure_priority':bool(prioritize_structure),
            'protected_prefix_before':protected_before,
            'protected_prefix_after':sum(prefix_after),
            'protected_prefix_truncated':sum(prefix_after)<protected_before,
            'semantic_hints_preserved':hints is not None,
        }
        if result_hints is not None:
            meta['path_phase_hints']=[list(group) for group in result_hints]
        if semantic:
            meta.update(semantic)
            if semantic.get('portrait_semantic_barrier'):
                meta['portrait_outline_paths_after_cap']=sum(prefix_after)
        return meta

    if cap is None or before <= int(cap):
        result_hints=[list(group) for group in hints] if hints is not None else None
        result=wrap(normalized,result_hints,list(prefixes))
        return result,metadata(before,list(prefixes),0,result_hints)

    cap=max(0,int(cap))
    def ranked_entries():
        serial=0
        for color_index,paths in enumerate(normalized):
            prefix=prefixes[color_index]
            for local_index,path in enumerate(paths):
                score=_importance_score(path,serial,prioritize_structure=prioritize_structure)
                yield (color_index,local_index,serial,score,path,local_index<prefix)
                serial+=1
    # nsmallest already holds only cap candidates. Feeding it a full scored list
    # duplicates every path reference and tuple for potentially huge dot plans.
    keep=heapq.nsmallest(cap,ranked_entries(),key=lambda item:(0 if item[5] else 1,-item[3],item[2]))
    kept_serials={item[2] for item in keep}
    regrouped=[[] for _ in normalized]
    regrouped_hints=[[] for _ in normalized] if hints is not None else None
    prefix_after=[0 for _ in normalized]
    serial=0
    for color_index,paths in enumerate(normalized):
        for local_index,path in enumerate(paths):
            if serial in kept_serials:
                regrouped[color_index].append(path)
                if regrouped_hints is not None:
                    regrouped_hints[color_index].append(hints[color_index][local_index])
                if local_index<prefixes[color_index]:
                    prefix_after[color_index]+=1
            serial+=1
    after=sum(len(paths) for paths in regrouped)
    result=wrap(regrouped,regrouped_hints,prefix_after)
    return result,metadata(after,prefix_after,before-after,regrouped_hints)
