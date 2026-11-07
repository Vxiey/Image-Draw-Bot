"""Deterministic edge behavior policy for Image Draw Bot v1.0.54.

Edge Behavior sits above CanvasGuard stroke clipping. It can decide how a
near-edge path is represented, but it never disables source-canvas validation,
safe-polygon clipping, or FinalMouseGuard. No AI/ML/OCR is used.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence, Tuple

from CanvasGuard import CanvasGuard, CanvasSafetyStop, _float_point, _round_point, _safe_projection, _nearest_boundary_point, point_in_polygon

Point = Tuple[int, int]
FloatPoint = Tuple[float, float]

EDGE_BEHAVIOR_MODES = ("Auto", "Hard Clip", "Adaptive Clip", "Preserve Outline")


def validate_edge_behavior(value: str) -> str:
    if value not in EDGE_BEHAVIOR_MODES:
        raise ValueError("Edge behavior must be Auto, Hard Clip, Adaptive Clip or Preserve Outline.")
    return value


def resolve_edge_behavior(value: str | None, *, profile_name: str | None = None, drawing_mode: str | None = None, outline: bool = False) -> str:
    """Resolve Auto to a concrete, safe edge policy.

    The default/fallback is Hard Clip so older plans keep their Step 7 safety
    behavior unless a profile or the user explicitly requests edge adaptation.
    """
    value = value or "Hard Clip"
    validate_edge_behavior(value)
    if value != "Auto":
        return value
    profile = (profile_name or "").strip()
    if outline:
        return "Preserve Outline"
    if profile == "Microsoft Paint":
        return "Adaptive Clip"
    if profile in {"Skribbl.io Fast", "Gartic.io", "Gartic Phone"}:
        return "Hard Clip"
    if (drawing_mode or "") == "Lines (fastest)":
        return "Hard Clip"
    return "Hard Clip"


@dataclass(frozen=True)
class EdgeBehaviorResult:
    subpaths: tuple[tuple[Point, ...], ...]
    mode: str
    strategy: str
    original_points: int
    output_points: int

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "strategy": self.strategy,
            "original_points": int(self.original_points),
            "output_points": int(self.output_points),
            "subpaths": len(self.subpaths),
        }


def _path_length(points: Sequence[Sequence[float | int]]) -> float:
    pts = [_float_point(p) for p in points]
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


def _dedupe_points(points: Iterable[Sequence[float | int]]) -> tuple[Point, ...]:
    out: list[Point] = []
    for point in points:
        rounded = _round_point(point)
        if not out or out[-1] != rounded:
            out.append(rounded)
    return tuple(out)


def _max_distance_to_safe_boundary(points: Sequence[Sequence[float | int]], safe_polygon: Sequence[Sequence[float | int]]) -> float:
    max_dist = 0.0
    for point in points:
        p = _float_point(point)
        if point_in_polygon(p, safe_polygon):
            continue
        b = _nearest_boundary_point(p, safe_polygon)
        max_dist = max(max_dist, math.hypot(p[0] - b[0], p[1] - b[1]))
    return max_dist


def _edge_follow_subpath(
    guard: CanvasGuard,
    raw_points: Sequence[Sequence[float | int]],
    *,
    mode: str,
    cancelled=lambda: False,
) -> tuple[tuple[Point, ...], ...]:
    """Project a near-edge path onto the safe boundary/inset.

    This is only used when hard clipping removed the whole path. Projection is
    bounded by brush inset distance and validated against safe_polygon before it
    can reach native input.
    """
    if len(raw_points) < 2:
        return ()
    safe_polygon = guard.model.safe_polygon
    raw_len = _path_length(raw_points)
    if raw_len < 1.0:
        return ()
    inset = max(1, int(guard.model.brush_inset.total_px))
    if mode == "Preserve Outline":
        max_project_distance = max(6.0, inset * 3.0 + 4.0)
        min_ratio = 0.20
    else:
        max_project_distance = max(5.0, inset * 2.0 + 2.0)
        min_ratio = 0.35
    if _max_distance_to_safe_boundary(raw_points, safe_polygon) > max_project_distance:
        return ()
    projected_points = []
    for index, point in enumerate(raw_points):
        if index % 512 == 0 and cancelled():
            raise InterruptedError()
        projected_points.append(_safe_projection(point, safe_polygon))
    projected = _dedupe_points(projected_points)
    if len(projected) < 2:
        return ()
    projected_len = _path_length(projected)
    if projected_len < 1.0 or projected_len / max(raw_len, 1e-6) < min_ratio:
        return ()
    for point in projected:
        if not guard.safe.contains_safe(point):
            raise CanvasSafetyStop(f"Edge Behavior produced an unsafe boundary point: {point}.")
    return (projected,)


def apply_edge_behavior(
    guard: CanvasGuard,
    raw_points: Iterable[Sequence[float | int]],
    *,
    behavior: str | None = None,
    profile_name: str | None = None,
    drawing_mode: str | None = None,
    outline: bool = False,
    context: str = "normal stroke",
    cancelled=lambda: False,
) -> EdgeBehaviorResult:
    """Clip or edge-adapt one canvas path.

    Source points are always validated against the selected canvas polygon first.
    Hard Clip preserves v1.0.53 behavior exactly. Adaptive/Preserve can only
    reintroduce a path by projecting it onto the safe inset boundary and only
    when the path is close enough to that boundary.
    """
    if cancelled():
        raise InterruptedError()
    raw = []
    for index, point in enumerate(raw_points):
        if index % 512 == 0 and cancelled():
            raise InterruptedError()
        raw.append(_round_point(point))
    raw = tuple(raw)
    mode = resolve_edge_behavior(behavior, profile_name=profile_name, drawing_mode=drawing_mode, outline=outline)
    hard = guard.clip_path_to_safe_subpaths(raw, context, cancelled=cancelled)
    if hard:
        output_points = sum(len(path) for path in hard)
        return EdgeBehaviorResult(hard, mode, "hard_clip", len(raw), output_points)
    if mode == "Hard Clip":
        return EdgeBehaviorResult((), mode, "hard_skip", len(raw), 0)
    followed = _edge_follow_subpath(guard, raw, mode=mode, cancelled=cancelled)
    if followed:
        strategy = "preserve_outline_boundary" if mode == "Preserve Outline" else "adaptive_boundary"
        return EdgeBehaviorResult(followed, mode, strategy, len(raw), sum(len(path) for path in followed))
    return EdgeBehaviorResult((), mode, "safe_skip", len(raw), 0)
