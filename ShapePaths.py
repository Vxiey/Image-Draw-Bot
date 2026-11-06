"""Fast approximate shape-path planner for Image Draw Bot v1.0.17.

Shape paths are intended for fast browser drawing profiles such as skribbl.io.
They do not replace the exact line planner.  Instead, they compress same-colour
raster runs into larger component hatches and keep only the most useful paths
when a user-selected stroke cap is active.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Sequence

Point = tuple[int, int]
Segment = tuple[int, int, int, int]
Path = tuple[Point, ...]

SHAPE_ORDERS = ("Fill first", "Contour first")
SHAPE_MODEL_MODES = ("Auto", "Fast raster", "Better shapes v2")
STROKE_CAPS = ("Auto", "1000", "2500", "5000", "10000", "Unlimited")


def validate_shape_order(value: str) -> str:
    if value not in SHAPE_ORDERS:
        raise ValueError("Choose a valid Shape paths order.")
    return value


def validate_stroke_cap(value: str) -> str:
    if value not in STROKE_CAPS:
        raise ValueError("Choose a valid max stroke cap.")
    return value


def validate_shape_model(value: str) -> str:
    if value not in SHAPE_MODEL_MODES:
        raise ValueError("Choose a valid shape model.")
    return value


def resolve_stroke_cap(value: str, *, preview: bool = False) -> int | None:
    validate_stroke_cap(value)
    if value == "Unlimited":
        return None
    if value == "Auto":
        return 1200 if preview else 2500
    return int(value)


def _norm_run(stroke: Sequence[int]) -> Segment:
    x1, y1, x2, y2 = map(int, stroke)
    if y1 != y2:
        return (x1, y1, x2, y2)
    if x2 < x1:
        x1, x2 = x2, x1
    return (x1, y1, x2, y2)


def _append(points: list[Point], point: Point) -> None:
    if not points or points[-1] != point:
        points.append(point)


def _compress(points: Iterable[Point]) -> Path:
    cleaned: list[Point] = []
    for point in points:
        point = (int(point[0]), int(point[1]))
        if cleaned and cleaned[-1] == point:
            continue
        cleaned.append(point)
        while len(cleaned) >= 3:
            ax, ay = cleaned[-3]
            bx, by = cleaned[-2]
            cx, cy = cleaned[-1]
            if ((bx - ax) * (cy - by) == (by - ay) * (cx - bx)
                    and (bx - ax) * (cx - bx) + (by - ay) * (cy - by) >= 0):
                cleaned.pop(-2)
            else:
                break
    return tuple(cleaned)


@dataclass
class _Component:
    rows: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    area: int = 0
    bbox: tuple[int, int, int, int] | None = None

    def add(self, x1: int, y: int, x2: int) -> None:
        if x2 < x1:
            x1, x2 = x2, x1
        self.rows.setdefault(y, []).append((x1, x2))
        self.area += x2 - x1 + 1
        if self.bbox is None:
            self.bbox = (x1, y, x2, y)
        else:
            a, b, c, d = self.bbox
            self.bbox = (min(a, x1), min(b, y), max(c, x2), max(d, y))

    def sorted_rows(self) -> list[int]:
        return sorted(self.rows)

    def contains(self, x: int, y: int) -> bool:
        return any(x1 <= x <= x2 for x1, x2 in self.rows.get(y, ()))


def _components_from_runs(strokes: Sequence[Segment], cancelled=lambda: False) -> tuple[list[_Component], list[Path]]:
    """Build same-colour connected components from horizontal runs.

    The planner connects only runs from neighbouring rows when their x-ranges
    overlap.  Non-horizontal legacy strokes are passed through unchanged.
    """
    rows: dict[int, list[tuple[int, int]]] = {}
    passthrough: list[Path] = []
    for stroke in strokes:
        if cancelled():
            raise InterruptedError()
        x1, y1, x2, y2 = _norm_run(stroke)
        if y1 != y2:
            passthrough.append(((x1, y1), (x2, y2)))
        else:
            rows.setdefault(y1, []).append((x1, x2))
    if not rows:
        return [], passthrough

    # Union-find over runs in adjacent rows.  Row counts are usually modest
    # because PixelData emits already-merged horizontal raster runs.
    records: list[tuple[int, int, int]] = []
    ids_by_row: dict[int, list[int]] = {}
    for y in sorted(rows):
        merged: list[tuple[int, int]] = []
        for x1, x2 in sorted(rows[y]):
            if merged and x1 <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], x2))
            else:
                merged.append((x1, x2))
        for x1, x2 in merged:
            ids_by_row.setdefault(y, []).append(len(records))
            records.append((x1, y, x2))

    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for y in sorted(ids_by_row):
        prev = ids_by_row.get(y - 1, [])
        if not prev:
            continue
        first_possible = 0
        for i in ids_by_row[y]:
            if cancelled():
                raise InterruptedError()
            x1, _, x2 = records[i]
            while first_possible < len(prev) and records[prev[first_possible]][2] < x1:
                first_possible += 1
            for position in range(first_possible, len(prev)):
                j = prev[position]
                px1, _, px2 = records[j]
                if px1 > x2:
                    break
                if max(x1, px1) <= min(x2, px2):
                    union(i, j)

    components: dict[int, _Component] = {}
    for i, (x1, y, x2) in enumerate(records):
        components.setdefault(find(i), _Component()).add(x1, y, x2)
    return list(components.values()), passthrough


def _can_bridge(component: _Component, x: int, y1: int, y2: int) -> bool:
    if y2 < y1:
        y1, y2 = y2, y1
    return all(component.contains(x, y) for y in range(y1, y2 + 1))


def _hatch_paths(component: _Component, *, step: int, cancelled=lambda: False) -> list[Path]:
    ys = component.sorted_rows()
    if not ys:
        return []
    step = max(1, int(step))
    chosen = set(ys[::step])
    # Always keep extremities so broad shapes keep their silhouette.
    chosen.add(ys[0]); chosen.add(ys[-1])
    selected = [y for y in ys if y in chosen]
    paths: list[Path] = []
    active: list[dict] = []

    for y in selected:
        if cancelled():
            raise InterruptedError()
        runs = sorted(component.rows.get(y, ()))
        used: set[int] = set()
        next_active: list[dict] = []
        for x1, x2 in runs:
            candidates = []
            for i, state in enumerate(active):
                if i in used:
                    continue
                lo, hi = max(int(state['x1']), x1), min(int(state['x2']), x2)
                if lo > hi:
                    continue
                end_x = int(state['points'][-1][0])
                connector = min(hi, max(lo, end_x))
                if not _can_bridge(component, connector, int(state['y']), y):
                    continue
                candidates.append((abs(connector - end_x), i, connector, state))
            if candidates:
                _, i, connector, state = min(candidates)
                points = state['points']
                _append(points, (connector, int(state['y'])))
                _append(points, (connector, y))
                # Serpentine sweep from the connector to cover the full run.
                if x1 != x2:
                    if abs(connector - x1) <= abs(x2 - connector):
                        _append(points, (x1, y)); _append(points, (x2, y))
                    else:
                        _append(points, (x2, y)); _append(points, (x1, y))
                state.update({'x1': x1, 'x2': x2, 'y': y})
                used.add(i); next_active.append(state)
            else:
                pts = [(x1, y)]
                if x2 != x1:
                    pts.append((x2, y))
                next_active.append({'points': pts, 'x1': x1, 'x2': x2, 'y': y})
        for i, state in enumerate(active):
            if i not in used:
                path = _compress(state['points'])
                if path:
                    paths.append(path)
        active = next_active

    for state in active:
        path = _compress(state['points'])
        if path:
            paths.append(path)
    return paths


def _contour_paths(component: _Component) -> list[Path]:
    ys = component.sorted_rows()
    if not ys:
        return []
    top, bottom = ys[0], ys[-1]
    paths: list[Path] = []
    for y in (top, bottom):
        for x1, x2 in sorted(component.rows.get(y, ())) :
            paths.append(((x1, y),) if x1 == x2 else ((x1, y), (x2, y)))
    # Add a few left/right horizontal edge rows for tall irregular silhouettes.
    if bottom - top >= 8:
        stride = max(3, (bottom - top) // 16)
        for y in ys[::stride]:
            runs = sorted(component.rows.get(y, ()))
            if not runs:
                continue
            x1, x2 = runs[0][0], runs[-1][1]
            paths.append(((x1, y),))
            if x2 != x1:
                paths.append(((x2, y),))
    return [p for p in paths if p]




def _bbox_area_from_box(bbox: tuple[int, int, int, int] | None) -> int:
    if not bbox:
        return 0
    x0, y0, x1, y1 = bbox
    return max(1, (x1 - x0 + 1) * (y1 - y0 + 1))


def _component_density(component: _Component) -> float:
    return float(component.area) / float(_bbox_area_from_box(component.bbox) or 1)


def _row_edges(component: _Component) -> tuple[list[Point], list[Point]]:
    """Return left and right silhouette samples for the largest outer span.

    Shape v2 uses this to draw one simplified contour instead of many tiny side
    dots. It intentionally follows the outermost occupied span on each row; it
    never tries to trace holes because those are better represented by later
    colour/detail passes.
    """
    left: list[Point] = []
    right: list[Point] = []
    for y in component.sorted_rows():
        runs = sorted(component.rows.get(y, ()))
        if not runs:
            continue
        left.append((runs[0][0], y))
        right.append((runs[-1][1], y))
    return left, right


def _rdp(points: Sequence[Point], tolerance: float, *, cancelled=lambda: False) -> list[Point]:
    """Ramer-Douglas-Peucker simplification for smoother long paths."""
    if cancelled():
        raise InterruptedError()
    pts = [tuple(map(int, p)) for p in points]
    if len(pts) <= 2 or tolerance <= 0:
        return pts
    # A zigzag can split off one point per iteration. An explicit stack keeps
    # that valid contour independent of Python's recursion limit and avoids
    # copying/re-normalizing every recursive suffix.
    kept = {0, len(pts) - 1}
    pending = [(0, len(pts) - 1)]
    while pending:
        if cancelled():
            raise InterruptedError()
        start, end = pending.pop()
        ax, ay = pts[start]
        bx, by = pts[end]
        dx, dy = bx - ax, by - ay
        denom = math.hypot(dx, dy)
        best_index = -1
        best_distance = -1.0
        for i in range(start + 1, end):
            if i % 256 == 0 and cancelled():
                raise InterruptedError()
            px, py = pts[i]
            if denom == 0:
                distance = math.hypot(px - ax, py - ay)
            else:
                distance = abs(dy * px - dx * py + bx * ay - by * ax) / denom
            if distance > best_distance:
                best_distance, best_index = distance, i
        if best_distance > tolerance and best_index > start:
            kept.add(best_index)
            pending.append((best_index, end))
            pending.append((start, best_index))
    return [pts[index] for index in sorted(kept)]


def _smooth_path(points: Sequence[Point], *, tolerance: float, closed: bool = False,
                 cancelled=lambda: False) -> Path:
    cleaned = _compress(points)
    if len(cleaned) <= 2:
        return cleaned
    work = list(cleaned)
    if closed and work[0] != work[-1]:
        work.append(work[0])
    simplified = _rdp(work, tolerance, cancelled=cancelled)
    if closed and simplified and simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return _compress(simplified)


def _contour_paths_v2(component: _Component, *, brush_px: int, cancelled=lambda: False) -> list[Path]:
    """Build a recognizable outer silhouette for a connected colour component."""
    if not component.bbox:
        return []
    left, right = _row_edges(component)
    if not left:
        return []
    x0, y0, x1, y1 = component.bbox
    width, height = x1 - x0 + 1, y1 - y0 + 1
    tolerance = max(0.7, min(4.0, brush_px * 0.85, max(width, height) / 28.0))
    if len(left) == 1:
        y = left[0][1]
        return [((x0, y), (x1, y)) if x0 != x1 else ((x0, y),)]
    # left edge downward + bottom bridge + right edge upward + top bridge
    polygon = list(left) + list(reversed(right))
    path = _smooth_path(polygon, tolerance=tolerance, closed=True, cancelled=cancelled)
    if len(path) >= 2:
        return [path]
    return []


def _v2_sample_rows(component: _Component, *, brush_px: int, preview: bool) -> list[int]:
    ys = component.sorted_rows()
    if not ys:
        return []
    density = _component_density(component)
    x0, y0, x1, y1 = component.bbox or (0, 0, 0, 0)
    height = y1 - y0 + 1
    # v2 uses wider bands for dense shapes; sparse shapes stay closer to the
    # old raster model so silhouettes do not collapse.
    base = max(1, int(round(max(1, brush_px) * (1.15 if density >= .68 else .9))))
    if density >= .80 and height >= 12:
        base += 1
    if component.area > 9000:
        base += 1
    if preview:
        base += 1
    step = max(1, min(base, 8))
    selected = set(ys[::step])
    selected.add(ys[0]); selected.add(ys[-1])
    if len(ys) >= 5:
        selected.add(ys[len(ys) // 2])
    return [y for y in ys if y in selected]


def _band_paths_v2(component: _Component, *, brush_px: int, preview: bool, cancelled=lambda: False) -> list[Path]:
    """Generate fewer, broader fill paths for shape-like components.

    Compared with the v1 shape hatcher this prefers one serpentine path per
    connected mass where connectors stay inside the component. Dense compact
    shapes get wider row steps and path smoothing; sparse shapes keep separate
    paths to avoid ugly bridges.
    """
    selected = _v2_sample_rows(component, brush_px=brush_px, preview=preview)
    if not selected:
        return []
    density = _component_density(component)
    bridge_gap = 2 if density >= .70 else 1
    tolerance = max(0.0, min(3.0, brush_px * (.55 if density >= .70 else .25)))
    paths: list[Path] = []
    active: list[dict] = []

    for y in selected:
        if cancelled():
            raise InterruptedError()
        runs = sorted(component.rows.get(y, ()))
        # On dense shapes, merge small internal run splits caused by anti-aliasing
        # so the fill reads as one coherent surface instead of stripes/dots.
        if density >= .76 and len(runs) > 1:
            merged: list[tuple[int, int]] = []
            for x1, x2 in runs:
                if merged and x1 <= merged[-1][1] + max(1, brush_px):
                    merged[-1] = (merged[-1][0], max(merged[-1][1], x2))
                else:
                    merged.append((x1, x2))
            runs = merged
        used: set[int] = set()
        next_active: list[dict] = []
        for x1, x2 in runs:
            candidates = []
            for i, state in enumerate(active):
                if i in used:
                    continue
                previous_y = int(state['y'])
                if y - previous_y > max(1, bridge_gap * max(1, brush_px)) + 3:
                    continue
                lo, hi = max(int(state['x1']), x1), min(int(state['x2']), x2)
                if lo > hi:
                    continue
                end_x = int(state['points'][-1][0])
                connector = min(hi, max(lo, end_x))
                # Check every intermediate source row if the gap is small; this
                # prevents diagonal shortcuts across empty holes.
                if not _can_bridge(component, connector, previous_y, y):
                    continue
                candidates.append((abs(connector - end_x), i, connector, state))
            if candidates:
                _, i, connector, state = min(candidates)
                points = state['points']
                _append(points, (connector, int(state['y'])))
                _append(points, (connector, y))
                if x1 != x2:
                    # Alternate sweep direction naturally from the connector.
                    if abs(connector - x1) <= abs(x2 - connector):
                        _append(points, (x1, y)); _append(points, (x2, y))
                    else:
                        _append(points, (x2, y)); _append(points, (x1, y))
                state.update({'x1': x1, 'x2': x2, 'y': y})
                used.add(i); next_active.append(state)
            else:
                pts = [(x1, y)]
                if x2 != x1:
                    pts.append((x2, y))
                next_active.append({'points': pts, 'x1': x1, 'x2': x2, 'y': y})
        for i, state in enumerate(active):
            if i not in used:
                # Fill paths keep every bridge point. Smoothing a serpentine fill
                # could create unsafe diagonals across holes; only exact collinear
                # compression is allowed here.
                path = _compress(state['points'])
                if path:
                    paths.append(path)
        active = next_active
    for state in active:
        # Fill paths keep every bridge point. Smoothing a serpentine fill
        # could create unsafe diagonals across holes; only exact collinear
        # compression is allowed here.
        path = _compress(state['points'])
        if path:
            paths.append(path)
    return paths


def _component_importance(component: _Component) -> float:
    density = _component_density(component)
    bbox_area = _bbox_area_from_box(component.bbox)
    return component.area + bbox_area * 0.08 + density * 25.0

def _path_len(path: Path) -> float:
    if len(path) < 2:
        return 0.0
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))


def _shape_step(component: _Component, brush_px: int, *, preview: bool) -> int:
    # Browser canvases usually show a round brush.  Drawing every 2-4 source
    # rows is much faster and still fills mass when the brush is wider than 1px.
    base = max(1, int(round(max(1, brush_px) * (0.75 if not preview else 1.05))))
    if component.area > 4000:
        base += 1
    if component.area > 16000:
        base += 1
    return max(1, min(base, 6))


def build_shape_execution_paths(groups: Sequence[Sequence[Segment]], *,
                                brush_px: int = 3,
                                order: str = "Fill first",
                                stroke_cap: str = "Auto",
                                shape_model: str = "Auto",
                                preview: bool = False,
                                cancelled=lambda: False) -> tuple[list[list[Path]], dict]:
    """Return approximate, capped path groups plus metadata.

    The original source groups are not modified; callers can still display and
    count the exact source runs while using this faster execution path.
    """
    validate_shape_order(order)
    validate_shape_model(shape_model)
    cap = resolve_stroke_cap(stroke_cap, preview=preview)
    use_v2 = shape_model in ("Auto", "Better shapes v2")
    brush_px = max(1, int(brush_px or 1))
    tiny_area = max(1, int(brush_px * brush_px * (1.2 if preview else 1.0)))

    grouped: list[list[Path]] = []
    phase_hints: list[list[str]] = []
    components_total = 0
    skipped_tiny = 0
    skipped_tiny_pixels = 0
    passthrough_paths = 0

    for strokes in groups:
        if cancelled():
            raise InterruptedError()
        components, passthrough = _components_from_runs(list(strokes), cancelled)
        components_total += len(components)
        out: list[Path] = list(passthrough)
        hints: list[str] = ["details" for _ in passthrough]
        passthrough_paths += len(passthrough)
        # Big shapes first makes skribbl drawings recognizable early. v2
        # ranks by a mix of pixel mass, bbox coverage and density so compact
        # visible shapes survive caps before scattered texture noise.
        sort_key = (lambda c: _component_importance(c)) if use_v2 else (lambda c: c.area)
        for component in sorted(components, key=sort_key, reverse=True):
            if component.area < tiny_area:
                skipped_tiny += 1
                skipped_tiny_pixels += component.area
                continue
            if use_v2:
                fills = _band_paths_v2(component, brush_px=brush_px, preview=preview, cancelled=cancelled)
                contours = _contour_paths_v2(component, brush_px=brush_px, cancelled=cancelled)
            else:
                step = _shape_step(component, brush_px, preview=preview)
                fills = _hatch_paths(component, step=step, cancelled=cancelled)
                contours = _contour_paths(component)
            if order == "Contour first":
                out.extend(contours); hints.extend(["contour"] * len(contours))
                out.extend(fills); hints.extend(["foundation"] * len(fills))
            else:
                out.extend(fills); hints.extend(["foundation"] * len(fills))
                out.extend(contours); hints.extend(["contour"] * len(contours))
        grouped.append(out)
        phase_hints.append(hints)

    raw = sum(len(g) for g in groups)
    before_cap = sum(len(g) for g in grouped)
    skipped_by_cap = 0
    if cap is not None and before_cap > cap:
        entries: list[tuple[int, int, float, Path]] = []
        serial = 0
        for color_index, paths in enumerate(grouped):
            for path in paths:
                entries.append((color_index, serial, _path_len(path) + (2.0 if len(path) == 1 else 0.0), path))
                serial += 1
        entries.sort(key=lambda item: (-item[2], item[1]))
        keep = entries[:cap]
        skipped_by_cap = len(entries) - len(keep)
        regrouped = [[] for _ in grouped]
        regrouped_hints = [[] for _ in grouped]
        kept_serials = {serial for _color_index, serial, _score, _path in keep}
        # Restore a stable within-colour order after ranking globally.
        global_serial = 0
        for color_index, paths in enumerate(grouped):
            for local_index, path in enumerate(paths):
                if global_serial in kept_serials:
                    regrouped[color_index].append(path)
                    hint = phase_hints[color_index][local_index] if color_index < len(phase_hints) and local_index < len(phase_hints[color_index]) else "details"
                    regrouped_hints[color_index].append(hint)
                global_serial += 1
        grouped = regrouped
        phase_hints = regrouped_hints

    execution = sum(len(g) for g in grouped)
    meta = {
        'mode': 'Shape paths',
        'source_strokes': raw,
        'execution_paths': execution,
        'joined_strokes': max(0, raw - execution),
        'compression_ratio': 0.0 if raw <= 0 else max(0.0, min(1.0, 1.0 - execution / raw)),
        'shape_components': components_total,
        'shape_order': order,
        'shape_model': shape_model,
        'shape_v2_enabled': bool(use_v2),
        'max_stroke_cap': stroke_cap,
        'max_stroke_cap_resolved': cap,
        'before_cap_paths': before_cap,
        'skipped_tiny_details': skipped_tiny,
        'skipped_tiny_pixels': skipped_tiny_pixels,
        'skipped_due_cap': skipped_by_cap,
        'passthrough_paths': passthrough_paths,
        'brush_px': brush_px,
        'path_phase_hints': phase_hints,
    }
    return grouped, meta
