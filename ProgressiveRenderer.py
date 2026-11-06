"""Progressive execution ordering for Image Draw Bot v1.0.21.

The planner remains pure: it only reorders already-safe execution paths. It does
not move the mouse, read files, touch Tk, or change calibration. DrawBot uses the
returned sequence so a drawing becomes recognizable early: broad fill/foundation
paths first, important contours second, tiny details last.
"""
from __future__ import annotations

import math
from typing import Sequence, Any

Point = tuple[int, int]
Path = tuple[Point, ...]

PROGRESSIVE_RENDERING_MODES = ("Auto", "On", "Off")
_PHASE_ORDER = {"foundation": 0, "contour": 1, "details": 2}
_PHASE_LABELS = {
    "foundation": "large forms",
    "contour": "important contours",
    "details": "small details",
}


def validate_progressive_rendering(value: str) -> str:
    if value not in PROGRESSIVE_RENDERING_MODES:
        raise ValueError("Choose a valid progressive rendering mode.")
    return value


def progressive_enabled(value: str, *, drawing_mode: str = "", time_budget_active: bool = False) -> bool:
    validate_progressive_rendering(value)
    if value == "On":
        return True
    if value == "Off":
        return False
    # Auto is deliberately conservative for exact Paint sketches, but enabled
    # for the fast approximate renderers where a recognizable early result is
    # more useful than strict colour-by-colour completion.
    return drawing_mode == "Shape paths" or bool(time_budget_active)


def _path_len(path: Sequence[Point]) -> float:
    if len(path) < 2:
        return 0.0
    return sum(math.hypot(float(b[0] - a[0]), float(b[1] - a[1])) for a, b in zip(path, path[1:]))


def _bounds(path: Sequence[Point]) -> tuple[int, int, int, int]:
    xs = [int(p[0]) for p in path]
    ys = [int(p[1]) for p in path]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_area(path: Sequence[Point]) -> int:
    x0, y0, x1, y1 = _bounds(path)
    return max(1, x1 - x0 + 1) * max(1, y1 - y0 + 1)


def _path_metrics(path: Sequence[Point]) -> tuple[float, int, tuple[float, float]]:
    """Compute the repeatedly used geometry without temporary coordinate lists."""
    first = path[0]
    xmin = xmax = int(first[0])
    ymin = ymax = int(first[1])
    sum_x = sum_y = length = 0.0
    previous = None
    for point in path:
        x, y = int(point[0]), int(point[1])
        xmin = min(xmin, x); xmax = max(xmax, x)
        ymin = min(ymin, y); ymax = max(ymax, y)
        sum_x += float(point[0]); sum_y += float(point[1])
        if previous is not None:
            length += math.hypot(float(point[0] - previous[0]), float(point[1] - previous[1]))
        previous = point
    area = max(1, xmax - xmin + 1) * max(1, ymax - ymin + 1)
    return length, area, (sum_x / len(path), sum_y / len(path))


def _normalize_phase(phase: Any, path: Sequence[Point], *, metrics=None) -> str:
    if phase in _PHASE_ORDER:
        return str(phase)
    if len(path) <= 1:
        return "details"
    length, area = metrics[:2] if metrics is not None else (_path_len(path), _bbox_area(path))
    if area >= 900 or length >= 80:
        return "foundation"
    if len(path) == 2 and (length >= 18 or area >= 80):
        return "contour"
    return "details"


def _importance(path: Sequence[Point], phase: str, serial: int, *, metrics=None) -> float:
    length, area = metrics[:2] if metrics is not None else (_path_len(path), _bbox_area(path))
    if phase == "foundation":
        return area * 0.18 + length * 1.4 - serial * 1e-6
    if phase == "contour":
        return length * 1.8 + area * 0.03 - serial * 1e-6
    return length + (3.0 if len(path) == 1 else 0.0) - serial * 1e-6


def _center(path: Sequence[Point]) -> tuple[float,float]:
    xs=[float(p[0]) for p in path];ys=[float(p[1]) for p in path]
    return (sum(xs)/max(1,len(xs)),sum(ys)/max(1,len(ys)))


def _normalized_importance(raw: float, phase: str) -> float:
    # Monotonic bounded score for runtime deadline/replanning logic.
    scale=80.0 if phase=='foundation' else (45.0 if phase=='contour' else 18.0)
    value=max(0.0,float(raw))
    return max(0.0,min(1.0,value/(value+scale)))


def _spatial_seed(entries: Sequence[dict], grid: int = 4) -> tuple[list[dict],int]:
    """Put one high-value path from each occupied coarse cell before refinements."""
    rows=list(entries or ())
    if len(rows)<=1:return rows,len(rows)
    centers=[row.get('_center') or _center(row['path']) for row in rows]
    xs=[c[0] for c in centers];ys=[c[1] for c in centers]
    xmin,xmax=min(xs),max(xs);ymin,ymax=min(ys),max(ys)
    dx=max(1.0,xmax-xmin);dy=max(1.0,ymax-ymin);g=max(2,int(grid))
    best={}
    for index,(row,(x,y)) in enumerate(zip(rows,centers)):
        cx=min(g-1,max(0,int((x-xmin)/dx*g)));cy=min(g-1,max(0,int((y-ymin)/dy*g)))
        key=(cx,cy);old=best.get(key)
        score=float(row.get('_progressive_score',0.0))
        if old is None or score>float(rows[old].get('_progressive_score',0.0)):
            best[key]=index
    seed_indexes=set(best.values())
    seeded=sorted((rows[i] for i in seed_indexes),key=lambda row:-float(row.get('_progressive_score',0.0)))
    rest=sorted((row for i,row in enumerate(rows) if i not in seed_indexes),
                key=lambda row:(-float(row.get('_progressive_score',0.0)),int(row.get('serial',0))))
    return seeded+rest,len(seeded)


def build_progressive_sequence(execution_groups: Sequence[Sequence[Path]], *,
                               phase_hints: Sequence[Sequence[str]] | None = None,
                               enabled: bool = True) -> tuple[list[dict], dict]:
    """Return a pass-based execution sequence and metadata.

    Each sequence item is a small dict with color_index, path, phase and serial.
    The original per-colour execution groups remain unchanged for preview and
    legacy code.  When disabled an empty sequence is returned with compatible
    metadata.
    """
    total = sum(len(paths) for paths in execution_groups)
    if not enabled or total <= 0:
        return [], {
            "progressive_enabled": False,
            "progressive_sequence_paths": 0,
            "progressive_foundation_paths": 0,
            "progressive_contour_paths": 0,
            "progressive_detail_paths": 0,
        }

    entries: list[dict] = []
    serial = 0
    counts = {"foundation": 0, "contour": 0, "details": 0}
    hints = phase_hints or []
    for color_index, paths in enumerate(execution_groups):
        color_hints = hints[color_index] if color_index < len(hints) else []
        for local_index, path in enumerate(paths):
            path = tuple(path)
            if not path:
                continue
            hint = color_hints[local_index] if local_index < len(color_hints) else None
            metrics = _path_metrics(path)
            phase = _normalize_phase(hint, path, metrics=metrics)
            counts[phase] += 1
            raw_score=_importance(path, phase, serial, metrics=metrics)
            structural=.92 if phase=='foundation' else (.72 if phase=='contour' else .18)
            entries.append({
                "color_index": int(color_index),
                "path": path,
                "phase": phase,
                "phase_label": _PHASE_LABELS[phase],
                "serial": serial,
                "importance": round(_normalized_importance(raw_score,phase),6),
                "structural_score": structural,
                "optional": phase=='details',
                "_progressive_score": raw_score,
                "_center": metrics[2],
            })
            serial += 1

    ordered=[];seed_count=0;seed_cells=0
    for phase in ('foundation','contour','details'):
        block=[item for item in entries if item['phase']==phase]
        if phase in ('foundation','contour'):
            block,seeds=_spatial_seed(block,4);seed_count+=seeds;seed_cells+=seeds
        else:
            block.sort(key=lambda item:(-float(item['_progressive_score']),int(item['color_index']),int(item['serial'])))
        ordered.extend(block)
    # Keep normalized importance/structure metadata for the runtime scheduler,
    # but remove planner-only score/center fields.
    sequence=[{k:v for k,v in item.items() if k not in ('_progressive_score','_center')} for item in ordered]
    return sequence, {
        "progressive_enabled": True,
        "progressive_sequence_paths": len(sequence),
        "progressive_foundation_paths": counts["foundation"],
        "progressive_contour_paths": counts["contour"],
        "progressive_detail_paths": counts["details"],
        "progressive_spatial_seed_paths": int(seed_count),
        "progressive_early_coverage_cells": int(seed_cells),
        "progressive_priority_model": "phase barriers + 4x4 spatial seeding + normalized importance",
        "progressive_phase_order": "large forms → important contours → details",
    }
