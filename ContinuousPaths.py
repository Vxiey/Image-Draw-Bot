"""Continuous safe-path planner for Image Draw Bot v1.0.12.

The legacy planner emits one straight mouse stroke for every raster run.  That is
simple and exact, but thousands of press/release boundaries dominate runtime.
This module joins adjacent same-colour horizontal runs only when their pixel
intervals overlap.  Every connector therefore stays inside pixels that already
belong to the same planned colour.

The original ``groups`` are intentionally left unchanged.  Continuous paths are
an execution layer built on top of them, so Fill, colour grouping, GPU planning,
preview maps and old Lines/Dots behaviour remain compatible.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

SMART_PATH_MODE = "Smart paths (recommended)"
SHAPE_PATH_MODE = "Shape paths"
LEGACY_LINE_MODE = "Lines (fastest)"
DOT_MODE = "Dots"
DRAWING_MODES = (SMART_PATH_MODE, SHAPE_PATH_MODE, LEGACY_LINE_MODE, DOT_MODE)

Point = tuple[int, int]
Segment = tuple[int, int, int, int]
Path = tuple[Point, ...]


class ExecutionGroups(list):
    """List-compatible execution groups carrying optional semantic barriers.

    Existing callers still see a normal list. Metadata is intentionally attached
    only at the execution layer so source groups remain untouched.
    """
    def __init__(self, groups=(), *, phase_hints=None, protected_prefix_counts=None, semantic_meta=None):
        super().__init__(groups)
        self.phase_hints = phase_hints
        self.protected_prefix_counts = protected_prefix_counts
        self.semantic_meta = dict(semantic_meta or {})


def execution_groups_with_portrait_semantics(groups, portrait_edge_count):
    """Attach a hard outline->tone barrier to portrait execution paths."""
    if portrait_edge_count is None or not groups:
        return groups
    try:
        prefix=max(0,min(len(groups[0]),int(portrait_edge_count)))
    except (TypeError,ValueError,OverflowError):
        prefix=0
    hints=[[] for _ in groups]
    hints[0]=['portrait-outline']*prefix + ['portrait-tone']*(len(groups[0])-prefix)
    prefixes=[prefix]+[0]*max(0,len(groups)-1)
    return ExecutionGroups(
        groups, phase_hints=hints, protected_prefix_counts=prefixes,
        semantic_meta={
            'portrait_semantic_barrier':True,
            'portrait_outline_paths_before_cap':prefix,
        })


@dataclass
class _ActivePath:
    points: list[Point]
    last_y: int
    x1: int
    x2: int
    rows: int = 1


def _append(points: list[Point], point: Point) -> None:
    if not points or points[-1] != point:
        points.append(point)


def _compress(points: Sequence[Point]) -> Path:
    """Drop duplicate and exactly collinear intermediate points."""
    cleaned: list[Point] = []
    for point in points:
        if cleaned and cleaned[-1] == point:
            continue
        cleaned.append(point)
        while len(cleaned) >= 3:
            ax, ay = cleaned[-3]
            bx, by = cleaned[-2]
            cx, cy = cleaned[-1]
            if ((bx-ax) * (cy-by) == (by-ay) * (cx-bx)
                    and (bx-ax) * (cx-bx) + (by-ay) * (cy-by) >= 0):
                cleaned.pop(-2)
            else:
                break
    return tuple(cleaned)


def _segment_path(stroke: Segment) -> Path:
    x1, y1, x2, y2 = map(int, stroke)
    if (x1, y1) == (x2, y2):
        return ((x1, y1),)
    return ((x1, y1), (x2, y2))


def _attach(state: _ActivePath, run: Segment) -> None:
    """Attach an adjacent horizontal run using an overlap-safe connector."""
    x1, y, x2, _ = run
    if x2 < x1:
        x1, x2 = x2, x1
    lo, hi = max(state.x1, x1), min(state.x2, x2)
    if lo > hi or y != state.last_y + 1:
        raise ValueError("Runs are not safely adjacent.")

    end_x = state.points[-1][0]
    endpoint_candidates = [x for x in (x1, x2) if lo <= x <= hi]
    if endpoint_candidates:
        connector = min(endpoint_candidates, key=lambda x: abs(x-end_x))
    else:
        connector = min(hi, max(lo, end_x))

    # Move along the previous valid run to a shared x, then vertically by one
    # sample row.  Both pixels at this x belong to the same colour group.
    _append(state.points, (connector, state.last_y))
    _append(state.points, (connector, y))

    if x1 == x2:
        pass
    elif connector == x1:
        _append(state.points, (x2, y))
    elif connector == x2:
        _append(state.points, (x1, y))
    else:
        # The new run is wider than the overlap. Visit the nearest edge first,
        # then sweep to the far edge so the whole source run is still covered.
        if abs(connector-x1) <= abs(x2-connector):
            _append(state.points, (x1, y)); _append(state.points, (x2, y))
        else:
            _append(state.points, (x2, y)); _append(state.points, (x1, y))

    state.last_y = y
    state.x1, state.x2 = x1, x2
    state.rows += 1


def _horizontal_paths(strokes: Sequence[Segment], cancelled=lambda: False,
                      max_rows_per_path: int = 72, max_points_per_path: int = 320) -> list[Path]:
    """Convert horizontal raster runs into continuous serpentine paths."""
    rows: dict[int, list[Segment]] = {}
    passthrough: list[Path] = []
    for stroke in strokes:
        if cancelled():
            raise InterruptedError()
        x1, y1, x2, y2 = map(int, stroke)
        if y1 != y2:
            passthrough.append(_segment_path((x1, y1, x2, y2)))
            continue
        if x2 < x1:
            x1, x2 = x2, x1
        rows.setdefault(y1, []).append((x1, y1, x2, y1))

    completed: list[Path] = []
    active: list[_ActivePath] = []
    for y in sorted(rows):
        if cancelled():
            raise InterruptedError()
        runs = sorted(rows[y], key=lambda s: (s[0], s[2]))

        # Paths that missed a row cannot be safely connected later.
        still_active = [p for p in active if p.last_y == y-1]
        for p in active:
            if p.last_y != y-1:
                completed.append(_compress(p.points))
        active = still_active
        used: set[int] = set()
        next_active: list[_ActivePath] = []
        first_possible = 0

        for run in runs:
            x1, _, x2, _ = run
            candidates = []
            # Active paths inherit the previous row's increasing x1 order.
            # Once an unused interval ends before this run, it cannot overlap
            # any later run either. Avoid rescanning all separated columns.
            while first_possible < len(active) and (first_possible in used or active[first_possible].x2 < x1):
                first_possible += 1
            for idx in range(first_possible, len(active)):
                state = active[idx]
                if idx % 256 == 0 and cancelled():
                    raise InterruptedError()
                if idx in used:
                    continue
                if state.x1 > x2:
                    break
                if state.rows >= max_rows_per_path or len(state.points) >= max_points_per_path:
                    continue
                lo, hi = max(state.x1, x1), min(state.x2, x2)
                if lo <= hi:
                    end_x = state.points[-1][0]
                    connector = min(hi, max(lo, end_x))
                    # Prefer large overlap, then little retrace from current endpoint.
                    candidates.append((-(hi-lo+1), abs(connector-end_x), idx, state))
            if candidates:
                _, _, idx, state = min(candidates)
                used.add(idx)
                _attach(state, run)
                next_active.append(state)
            else:
                points = [(x1, y)]
                if x2 != x1:
                    points.append((x2, y))
                next_active.append(_ActivePath(points, y, x1, x2))

        for idx, state in enumerate(active):
            if idx not in used:
                completed.append(_compress(state.points))
        active = next_active

    completed.extend(_compress(p.points) for p in active)
    completed.extend(passthrough)
    return [p for p in completed if p]


def build_execution_paths(groups: Sequence[Sequence[Segment]], *, enabled: bool,
                          portrait_edge_count: int | None = None,
                          max_rows_per_path: int = 72, max_points_per_path: int = 320,
                          cancelled=lambda: False) -> list[list[Path]] | None:
    """Build safe continuous execution paths while preserving legacy groups.

    Portrait contours are kept as independent strokes.  Tonal hatch strokes may
    still be chained when they are horizontal and adjacent, preserving the
    structure-first ordering introduced by PortraitPlanner.
    """
    if not enabled:
        return None
    result: list[list[Path]] = []
    for group_index, group in enumerate(groups):
        if cancelled():
            raise InterruptedError()
        group = list(group)
        if portrait_edge_count is not None and group_index == 0:
            edge_n = max(0, min(len(group), int(portrait_edge_count)))
            edges = [_segment_path(s) for s in group[:edge_n]]
            tones = _horizontal_paths(group[edge_n:], cancelled, max_rows_per_path=max_rows_per_path, max_points_per_path=max_points_per_path)
            result.append(edges + tones)
        else:
            result.append(_horizontal_paths(group, cancelled, max_rows_per_path=max_rows_per_path, max_points_per_path=max_points_per_path))
    return execution_groups_with_portrait_semantics(result, portrait_edge_count)


def path_segment_count(path: Sequence[Point]) -> int:
    return max(0, len(path)-1)


def path_length(path: Sequence[Point]) -> float:
    return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(path, path[1:]))


def reverse_path(path: Sequence[Point]) -> Path:
    return tuple(reversed(path))


def order_paths(paths: Sequence[Path], speed: str, *, allow_reverse: bool = True) -> list[Path]:
    """Small bounded nearest-neighbour pass for pen-up travel between paths."""
    paths = [tuple(p) for p in paths if p]
    if len(paths) < 3 or speed == "Safe":
        return paths
    window = 18 if speed == "Balanced" else 48
    output: list[Path] = []
    for start in range(0, len(paths), window):
        chunk = list(paths[start:start+window])
        if not chunk:
            continue
        current = chunk.pop(0)
        output.append(current)
        cursor = current[-1]
        while chunk:
            best_i = 0; best_reverse = False; best_d = float("inf")
            for i, path in enumerate(chunk):
                d0 = math.hypot(path[0][0]-cursor[0], path[0][1]-cursor[1])
                if d0 < best_d:
                    best_i, best_reverse, best_d = i, False, d0
                if allow_reverse and len(path) > 1:
                    d1 = math.hypot(path[-1][0]-cursor[0], path[-1][1]-cursor[1])
                    if d1 < best_d:
                        best_i, best_reverse, best_d = i, True, d1
            chosen = chunk.pop(best_i)
            if best_reverse:
                chosen = reverse_path(chosen)
            output.append(chosen); cursor = chosen[-1]
    return output


def stats(groups: Sequence[Sequence[Segment]], execution_groups: Sequence[Sequence[Path]] | None) -> dict:
    raw = sum(len(g) for g in groups)
    execution = raw if execution_groups is None else sum(len(g) for g in execution_groups)
    out = {
        "source_strokes": raw,
        "execution_paths": execution,
        "joined_strokes": max(0, raw-execution),
        "compression_ratio": (0.0 if raw <= 0 else max(0.0, min(1.0, 1.0-execution/raw))),
    }
    if execution_groups is not None:
        phase_hints=getattr(execution_groups,'phase_hints',None)
        if phase_hints is not None:
            out['path_phase_hints']=[list(group) for group in phase_hints]
        prefixes=getattr(execution_groups,'protected_prefix_counts',None)
        if prefixes is not None:
            out['protected_prefix_counts']=[int(value) for value in prefixes]
        semantic=getattr(execution_groups,'semantic_meta',None)
        if isinstance(semantic,dict):
            out.update(semantic)
    return out
