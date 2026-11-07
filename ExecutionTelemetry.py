"""Pure execution-plan telemetry for Image Draw Bot.

This module measures geometry and shared execution-cost estimates without changing
path order, planner choices, target input, or saved user settings.
"""
from __future__ import annotations

import math
from itertools import pairwise
from typing import Any, Sequence

Point = tuple[int, int]
Path = Sequence[Point]


def _distance(a: Point, b: Point, scale_x: float = 1.0, scale_y: float = 1.0) -> float:
    return math.hypot(
        (float(b[0]) - float(a[0])) * float(scale_x),
        (float(b[1]) - float(a[1])) * float(scale_y),
    )


def draw_distance_px(paths: Sequence[Path], *, scale_x: float = 1.0, scale_y: float = 1.0) -> float:
    total = 0.0
    for path in paths:
        if len(path) < 2:
            continue
        total += sum(_distance(a, b, scale_x, scale_y) for a, b in pairwise(path))
    return total


def pen_up_distance_px(
    paths: Sequence[Path],
    *,
    cursor: Point | None = None,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> float:
    total = 0.0
    current = cursor
    for path in paths:
        if not path:
            continue
        if current is not None:
            total += _distance(current, path[0], scale_x, scale_y)
        current = tuple(path[-1])
    return total


def flatten_groups(groups: Sequence[Sequence[Path]], color_order: Sequence[int] | None = None) -> list[Path]:
    count = len(groups)
    requested = list(range(count)) if color_order is None else [int(i) for i in color_order]
    seen: set[int] = set()
    order: list[int] = []
    for index in requested:
        if 0 <= index < count and index not in seen:
            order.append(index)
            seen.add(index)
    order.extend(index for index in range(count) if index not in seen)

    out: list[Path] = []
    for index in order:
        out.extend(path for path in groups[index] if path)
    return out


def execution_metrics(
    groups: Sequence[Sequence[Path]],
    cost_model,
    *,
    color_order: Sequence[int] | None = None,
    cursor: Point | None = None,
    count_color_selection: bool = True,
) -> dict[str, Any]:
    """Return complete path-sequence telemetry for the supplied plan."""
    scale_x = float(getattr(cost_model, "scale_x", 1.0) or 1.0)
    scale_y = float(getattr(cost_model, "scale_y", 1.0) or 1.0)

    count = len(groups)
    requested = list(range(count)) if color_order is None else [int(i) for i in color_order]
    seen: set[int] = set()
    order: list[int] = []
    for index in requested:
        if 0 <= index < count and index not in seen:
            order.append(index)
            seen.add(index)
    order.extend(index for index in range(count) if index not in seen)

    path_count = 0
    point_count = 0
    draw_px = 0.0
    travel_px = 0.0
    path_seconds = 0.0
    color_changes = 0
    current = cursor

    for index in order:
        selected = False
        for raw_path in groups[index]:
            if not raw_path:
                continue
            path = tuple(raw_path)
            if count_color_selection and not selected:
                color_changes += 1
                selected = True
            path_count += 1
            point_count += len(path)
            draw_px += draw_distance_px([path], scale_x=scale_x, scale_y=scale_y)
            if current is not None:
                travel_px += _distance(current, path[0], scale_x, scale_y)
            path_seconds += float(cost_model.path_seconds(path, cursor=current))
            current = tuple(path[-1])

    color_seconds = color_changes * float(getattr(cost_model, "color_change_seconds", 0.0) or 0.0)
    total_seconds = path_seconds + color_seconds
    risk_fn=getattr(cost_model,'risk_adjusted_seconds',None)
    risk_adjusted=float(risk_fn(total_seconds)) if callable(risk_fn) else total_seconds
    return {
        "path_count": int(path_count),
        "path_boundaries": int(path_count),
        "point_count": int(point_count),
        "draw_px": round(draw_px, 6),
        "travel_px": round(travel_px, 6),
        "color_change_count": int(color_changes),
        "tool_change_count": 0,
        "fill_action_count": 0,
        "verification_operation_count": 0,
        "modeled_path_seconds": round(path_seconds, 6),
        "modeled_color_seconds": round(color_seconds, 6),
        "modeled_total_seconds": round(total_seconds, 6),
        "modeled_risk_adjusted_seconds": round(risk_adjusted, 6),
        "cost_model_version": int(getattr(cost_model,'model_version',1) or 1),
        "cost_model_confidence": round(float(getattr(cost_model,'calibration_confidence',0.0) or 0.0),6),
        "cost_model_uncertainty_multiplier": round(float(getattr(cost_model,'uncertainty_multiplier',1.0) or 1.0),6),
    }
