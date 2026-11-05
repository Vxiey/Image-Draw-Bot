"""Hard canvas safety layer for Image Draw Bot v1.0.54.

CanvasGuard is deterministic: no AI, no heuristic drawing outside of the
selected canvas, and no profile-controlled off switch.  v1.0.48 upgraded the
model from a rectangle-only guard to a polygon-first canvas model; v1.0.49
adds normalized corner/triangle anchors to the same guard model. The selected
rectangle remains a compatibility fallback, while custom/auto-detected polygons
can now define the real drawable surface. v1.0.53 added segment-by-segment stroke clipping; v1.0.54 keeps CanvasGuard authoritative under the new Edge Behavior policy layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Mapping, Sequence, Tuple

Point = Tuple[int, int]
FloatPoint = Tuple[float, float]


class CanvasSafetyStop(InterruptedError):
    """Raised before native input can draw outside the safe canvas."""


def _finite_number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{name} must be a finite number.') from error
    if not math.isfinite(number):
        raise ValueError(f'{name} must be a finite number.')
    return number


def _round_point(point: Sequence[float | int]) -> Point:
    if len(point) != 2:
        raise ValueError('Point must contain x and y.')
    return (int(round(_finite_number(point[0], 'x'))),
            int(round(_finite_number(point[1], 'y'))))


def _float_point(point: Sequence[float | int]) -> FloatPoint:
    if len(point) != 2:
        raise ValueError('Point must contain x and y.')
    return (_finite_number(point[0], 'x'), _finite_number(point[1], 'y'))


def _rect_polygon(left: int, top: int, right: int, bottom: int) -> tuple[Point, Point, Point, Point]:
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _polygon_bounds(polygon: Sequence[Sequence[float | int]]) -> tuple[int, int, int, int]:
    pts = [_float_point(p) for p in polygon]
    if not pts:
        raise ValueError('Canvas polygon is empty.')
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (int(math.floor(min(xs))), int(math.floor(min(ys))),
            int(math.ceil(max(xs))), int(math.ceil(max(ys))))


def _signed_area(points: Sequence[FloatPoint]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _centroid(points: Sequence[Sequence[float | int]]) -> FloatPoint:
    pts = [_float_point(p) for p in points]
    if not pts:
        raise ValueError('Canvas polygon is empty.')
    area = _signed_area(pts)
    if abs(area) < 1e-7:
        return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
    cx = 0.0
    cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    factor = 1.0 / (6.0 * area)
    return (cx * factor, cy * factor)


def _dedupe_polygon(polygon: Sequence[Sequence[float | int]]) -> tuple[FloatPoint, ...]:
    pts: list[FloatPoint] = []
    for raw in polygon:
        pt = _float_point(raw)
        if not pts or math.hypot(pt[0] - pts[-1][0], pt[1] - pts[-1][1]) > 0.01:
            pts.append(pt)
    if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 0.01:
        pts.pop()
    if len(pts) < 3:
        raise ValueError('Canvas polygon must contain at least 3 unique points.')
    if abs(_signed_area(pts)) < 0.5:
        raise ValueError('Canvas polygon area is too small.')
    return tuple(pts)


def _round_polygon(points: Sequence[Sequence[float | int]]) -> tuple[Point, ...]:
    return tuple(_round_point(p) for p in points)


def point_in_polygon(point: Sequence[float | int], polygon: Sequence[Sequence[float | int]]) -> bool:
    """Return True when point is inside or on the boundary of a simple polygon."""
    x, y = _float_point(point)
    pts = [_float_point(p) for p in polygon]
    if len(pts) < 3:
        return False

    # Boundary check first so exact safe-edge coordinates are allowed.
    eps = 1e-7
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) <= eps:
            if min(x1, x2) - eps <= x <= max(x1, x2) + eps and min(y1, y2) - eps <= y <= max(y1, y2) + eps:
                return True

    inside = False
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if ((yi > y) != (yj > y)):
            x_intersect = (xj - xi) * (y - yi) / ((yj - yi) or eps) + xi
            if x <= x_intersect:
                inside = not inside
        j = i
    return inside


def _line_intersection(n1: FloatPoint, c1: float, n2: FloatPoint, c2: float) -> FloatPoint | None:
    # n dot p = c
    det = n1[0] * n2[1] - n1[1] * n2[0]
    if abs(det) < 1e-9:
        return None
    x = (c1 * n2[1] - n1[1] * c2) / det
    y = (n1[0] * c2 - c1 * n2[0]) / det
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return (x, y)


def _has_edge_clearance(points: Sequence[FloatPoint], polygon: Sequence[FloatPoint], margin: float) -> bool:
    """Check every inward edge half-plane of a convex polygon.

    Checking the original vertices with zero margin also rejects concave or
    self-intersecting polygons, whose centroid is not a safe inset reference.
    """
    orientation = 1.0 if _signed_area(polygon) >= 0 else -1.0
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-7:
            return False
        for x, y in points:
            distance = orientation * (dx * (y - y1) - dy * (x - x1)) / length
            if distance + 1e-7 < margin:
                return False
    return True


def _convex_inset_polygon(polygon: Sequence[Sequence[float | int]], margin: float) -> tuple[FloatPoint, ...] | None:
    """Inset a convex polygon by offsetting each edge inward.

    Returns None when the original polygon or its full brush inset cannot be
    verified. Image Draw Bot canvas polygons are normally rectangles or convex
    quadrilaterals derived from calibration anchors.
    """
    pts = list(_dedupe_polygon(polygon))
    if len(set(pts)) != len(pts) or not _has_edge_clearance(pts, pts, 0.0):
        return None
    # Calibration may add an anchor in the middle of a straight edge. Remove
    # only those redundant vertices before intersecting offset lines, since two
    # identical adjacent lines have no unique intersection. Validate the full
    # original polygon above so this never hides a concavity or backtracking.
    corners: list[FloatPoint] = []
    for i, point in enumerate(pts):
        before, after = pts[i - 1], pts[(i + 1) % len(pts)]
        ax, ay = point[0] - before[0], point[1] - before[1]
        bx, by = after[0] - point[0], after[1] - point[1]
        if ax * by - ay * bx == 0.0 and ax * bx + ay * by > 0.0:
            continue
        corners.append(point)
    pts = corners
    if margin <= 0:
        return tuple(pts)
    orientation = 1.0 if _signed_area(pts) >= 0 else -1.0
    lines: list[tuple[FloatPoint, float]] = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-7:
            return None
        if orientation >= 0:
            nx, ny = -dy / length, dx / length
        else:
            nx, ny = dy / length, -dx / length
        c = nx * x1 + ny * y1 + margin
        lines.append(((nx, ny), c))

    out: list[FloatPoint] = []
    for i in range(len(lines)):
        prev_n, prev_c = lines[i - 1]
        cur_n, cur_c = lines[i]
        p = _line_intersection(prev_n, prev_c, cur_n, cur_c)
        if p is None:
            return None
        out.append(p)

    if abs(_signed_area(out)) < 0.5:
        return None
    # An over-large inset can invert while leaving all corners inside the
    # original bounds. Every corner must satisfy every *offset* edge instead.
    if not _has_edge_clearance(out, pts, margin):
        return None
    return tuple(out)


def inset_polygon(polygon: Sequence[Sequence[float | int]], margin: float) -> tuple[Point, ...]:
    """Return a verified convex brush-inset polygon or stop before input.

    A centroid shrink is unsafe for concave or collapsed polygons: it can move
    points outside the selected canvas or reduce the required brush clearance.
    """
    pts = _dedupe_polygon(polygon)
    margin = max(0.0, _finite_number(margin, 'margin'))
    if margin <= 0:
        return _round_polygon(pts)
    message = ('Canvas Guard cannot fit the brush safely inside this canvas polygon. '
               'Use a smaller brush or recalibrate a convex drawing area.')
    inset = _convex_inset_polygon(pts, margin)
    if inset is None:
        raise CanvasSafetyStop(message)
    rounded = _round_polygon(inset)
    if not _has_edge_clearance(rounded, pts, margin):
        # Integer rounding moves a point by at most sqrt(0.5) pixels. Apply that
        # extra inset only where needed; axis-aligned canvases stay unchanged.
        inset = _convex_inset_polygon(pts, margin + math.sqrt(0.5))
        if inset is None:
            raise CanvasSafetyStop(message)
        rounded = _round_polygon(inset)
        if not _has_edge_clearance(rounded, pts, margin):
            raise CanvasSafetyStop(message)
    try:
        return _round_polygon(_dedupe_polygon(rounded))
    except ValueError as error:
        raise CanvasSafetyStop(message) from error


def normalize_canvas_polygon(
    polygon: Sequence[Sequence[float | int]],
    area: Sequence[int | float] | None = None,
    coordinate_space: str | None = None,
) -> tuple[Point, ...]:
    """Normalize a canvas polygon to screen coordinates.

    coordinate_space accepts:
      - screen/absolute: polygon points are already screen coordinates
      - area/relative: x,y are relative to the selected drawing-area origin
      - normalized: x,y are 0..1 fractions of the selected drawing-area size
      - auto/default: normalized if all values are 0..1, area-relative if all
        points fit inside area width/height, otherwise screen coordinates.
    """
    pts = [_float_point(p) for p in polygon]
    _dedupe_polygon(pts)
    mode = (coordinate_space or 'auto').strip().lower()
    if mode in ('absolute', 'screen'):
        return _round_polygon(pts)
    if area is None:
        if mode in ('normalized', 'relative', 'area'):
            raise ValueError('Canvas polygon coordinate_space requires area.')
        return _round_polygon(pts)
    if len(area) != 4:
        raise ValueError('Canvas area must be (x, y, width, height).')
    ax, ay, aw, ah = [_finite_number(v, 'canvas area') for v in area]
    if aw <= 0 or ah <= 0:
        raise ValueError('Canvas area has invalid size.')
    if mode == 'auto':
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if all(-0.001 <= v <= 1.001 for v in xs + ys):
            mode = 'normalized'
        elif all(-0.001 <= x <= aw + 0.001 for x in xs) and all(-0.001 <= y <= ah + 0.001 for y in ys):
            mode = 'area'
        else:
            mode = 'screen'
    if mode == 'normalized':
        return _round_polygon((ax + x * (aw - 1), ay + y * (ah - 1)) for x, y in pts)
    if mode in ('relative', 'area'):
        return _round_polygon((ax + x, ay + y) for x, y in pts)
    if mode in ('absolute', 'screen'):
        return _round_polygon(pts)
    raise ValueError(f'Unknown canvas polygon coordinate_space: {coordinate_space!r}')




def _normalise_space(value: str | None) -> str:
    mode = (value or 'auto').strip().lower()
    if mode == 'relative':
        return 'area'
    if mode == 'absolute':
        return 'screen'
    return mode


def _point_to_screen(point: Sequence[float | int], area: Sequence[int | float] | None, coordinate_space: str | None) -> FloatPoint:
    x, y = _float_point(point)
    mode = _normalise_space(coordinate_space)
    if mode == 'screen':
        return (x, y)
    if area is None:
        if mode in ('normalized', 'area'):
            raise ValueError('Canvas anchor coordinate_space requires area.')
        return (x, y)
    if len(area) != 4:
        raise ValueError('Canvas area must be (x, y, width, height).')
    ax, ay, aw, ah = [_finite_number(v, 'canvas area') for v in area]
    if aw <= 0 or ah <= 0:
        raise ValueError('Canvas area has invalid size.')
    if mode == 'auto':
        if -0.001 <= x <= 1.001 and -0.001 <= y <= 1.001:
            mode = 'normalized'
        elif -0.001 <= x <= aw + 0.001 and -0.001 <= y <= ah + 0.001:
            mode = 'area'
        else:
            mode = 'screen'
    if mode == 'normalized':
        return (ax + x * (aw - 1), ay + y * (ah - 1))
    if mode == 'area':
        return (ax + x, ay + y)
    if mode == 'screen':
        return (x, y)
    raise ValueError(f'Unknown canvas anchor coordinate_space: {coordinate_space!r}')


def _anchor_from_mapping(data: Mapping[str, object]) -> 'CanvasAnchor':
    kind = str(data.get('kind') or data.get('type') or '').strip().lower()
    if kind not in ('corner', 'triangle'):
        raise ValueError('Canvas anchor kind must be corner or triangle.')
    center = data.get('center') or data.get('point')
    if center is None:
        raise ValueError('Canvas anchor requires a center point.')
    tip = data.get('tip')
    confidence = float(data.get('confidence', 1.0))
    orientation = data.get('orientation')
    return CanvasAnchor(kind=kind, center=_float_point(center),
                        tip=(_float_point(tip) if tip is not None else None),
                        confidence=max(0.0, min(1.0, confidence)),
                        orientation=(float(orientation) if orientation is not None else None))


def normalize_canvas_anchors(
    anchors: Sequence['CanvasAnchor | Mapping[str, object]'],
    area: Sequence[int | float] | None = None,
    coordinate_space: str | None = None,
) -> tuple['CanvasAnchor', ...]:
    """Normalize corner/triangle anchors to screen coordinates.

    Anchors may already be CanvasAnchor instances or dictionaries with
    kind/center/tip/confidence/orientation fields. coordinate_space follows the
    same screen, area, normalized and auto rules used by canvas polygons.
    """
    result: list[CanvasAnchor] = []
    for raw in anchors or ():
        if isinstance(raw, CanvasAnchor):
            anchor = raw
        elif isinstance(raw, Mapping):
            anchor = _anchor_from_mapping(raw)
        else:
            raise ValueError('Canvas anchors must be CanvasAnchor objects or dictionaries.')
        center = _point_to_screen(anchor.center, area, coordinate_space)
        tip = _point_to_screen(anchor.tip, area, coordinate_space) if anchor.tip is not None else None
        result.append(CanvasAnchor(anchor.kind, center, tip=tip,
                                   confidence=max(0.0, min(1.0, float(anchor.confidence))),
                                   orientation=anchor.orientation))
    return tuple(result)


def _lerp(a: FloatPoint, b: FloatPoint, t: float) -> FloatPoint:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _cross(a: FloatPoint, b: FloatPoint) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _sub(a: FloatPoint, b: FloatPoint) -> FloatPoint:
    return (a[0] - b[0], a[1] - b[1])


def _add_unique_t(values: list[float], value: float, eps: float = 1e-7) -> None:
    if not math.isfinite(value):
        return
    value = max(0.0, min(1.0, float(value)))
    if not any(abs(value - existing) <= eps for existing in values):
        values.append(value)


def _segment_edge_t_values(a: FloatPoint, b: FloatPoint, c: FloatPoint, d: FloatPoint) -> tuple[float, ...]:
    """Return AB parameters where segment AB intersects polygon edge CD."""
    r = _sub(b, a)
    s = _sub(d, c)
    denom = _cross(r, s)
    ca = _sub(c, a)
    eps = 1e-9
    if abs(denom) > eps:
        t = _cross(ca, s) / denom
        u = _cross(ca, r) / denom
        if -eps <= t <= 1.0 + eps and -eps <= u <= 1.0 + eps:
            return (max(0.0, min(1.0, t)),)
        return ()
    # Parallel. If collinear, add edge endpoints projected on AB so overlapped
    # boundary segments are split at the correct parameters.
    if abs(_cross(ca, r)) > eps:
        return ()
    rr = r[0] * r[0] + r[1] * r[1]
    if rr <= eps:
        return ()
    values = []
    for point in (c, d):
        t = ((point[0] - a[0]) * r[0] + (point[1] - a[1]) * r[1]) / rr
        if -eps <= t <= 1.0 + eps:
            _add_unique_t(values, t)
    return tuple(values)


def clip_segment_to_polygon(start: Sequence[float | int], end: Sequence[float | int], polygon: Sequence[Sequence[float | int]]) -> tuple[tuple[Point, Point], ...]:
    """Clip one segment to a simple polygon and return drawable subsegments.

    The implementation is deterministic and polygon-agnostic: it splits the line
    at every polygon-edge intersection, then keeps the intervals whose midpoint
    is inside the polygon.  This supports the rectangle fallback, convex anchor
    polygons and mild non-convex safe polygons without relying on AI/ML.
    """
    a = _float_point(start)
    b = _float_point(end)
    pts = [_float_point(p) for p in polygon]
    if len(pts) < 3:
        return ()
    if math.hypot(b[0] - a[0], b[1] - a[1]) <= 1e-7:
        if point_in_polygon(a, pts):
            rounded = _round_point(a)
            if point_in_polygon(rounded, pts):
                return ((rounded, rounded),)
            safe = _safe_projection(a, pts)
            return ((safe, safe),) if point_in_polygon(safe, pts) else ()
        return ()

    t_values = [0.0, 1.0]
    for c, d in zip(pts, pts[1:] + pts[:1]):
        for t in _segment_edge_t_values(a, b, c, d):
            _add_unique_t(t_values, t)
    t_values.sort()

    out: list[tuple[Point, Point]] = []
    for t0, t1 in zip(t_values, t_values[1:]):
        if t1 - t0 <= 1e-7:
            continue
        mid = _lerp(a, b, (t0 + t1) * 0.5)
        if not point_in_polygon(mid, pts):
            continue
        p0f = _lerp(a, b, t0)
        p1f = _lerp(a, b, t1)
        p0 = _round_point(p0f)
        p1 = _round_point(p1f)
        if not point_in_polygon(p0, pts):
            p0 = _safe_projection(p0f, pts)
        if not point_in_polygon(p1, pts):
            p1 = _safe_projection(p1f, pts)
        if point_in_polygon(p0, pts) and point_in_polygon(p1, pts):
            if out and out[-1][1] == p0:
                out[-1] = (out[-1][0], p1)
            else:
                out.append((p0, p1))

    # Entirely-inside segments have no intersections and produce exactly one
    # interval. If rounding collapsed it, keep a safe dot instead of inventing a
    # rectangle clamp.
    if not out and point_in_polygon(a, pts) and point_in_polygon(b, pts):
        p0 = _round_point(a)
        p1 = _round_point(b)
        if not point_in_polygon(p0, pts):
            p0 = _safe_projection(a, pts)
        if not point_in_polygon(p1, pts):
            p1 = _safe_projection(b, pts)
        if point_in_polygon(p0, pts) and point_in_polygon(p1, pts):
            return ((p0, p1),)
    return tuple(out)


def clip_path_to_polygon(points: Iterable[Sequence[float | int]], polygon: Sequence[Sequence[float | int]]) -> tuple[tuple[Point, ...], ...]:
    """Clip a polyline to a polygon and preserve gaps as separate subpaths."""
    raw = [_float_point(p) for p in points]
    pts = [_float_point(p) for p in polygon]
    if not raw or len(pts) < 3:
        return ()
    if len(raw) == 1:
        if not point_in_polygon(raw[0], pts):
            return ()
        rounded = _round_point(raw[0])
        if not point_in_polygon(rounded, pts):
            rounded = _safe_projection(raw[0], pts)
        return ((rounded,),) if point_in_polygon(rounded, pts) else ()

    subpaths: list[list[Point]] = []
    current: list[Point] = []
    for a, b in zip(raw, raw[1:]):
        pieces = clip_segment_to_polygon(a, b, pts)
        if not pieces:
            if current:
                subpaths.append(current)
                current = []
            continue
        for start, end in pieces:
            if current and current[-1] == start:
                if end != current[-1]:
                    current.append(end)
            else:
                if current:
                    subpaths.append(current)
                current = [start]
                if end != start:
                    current.append(end)
    if current:
        subpaths.append(current)
    return tuple(tuple(path) for path in subpaths if path)


def _nearest_boundary_point(point: Sequence[float | int], polygon: Sequence[Sequence[float | int]]) -> FloatPoint:
    px, py = _float_point(point)
    pts = [_float_point(p) for p in polygon]
    best: FloatPoint | None = None
    best_dist = float('inf')
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = x2 - x1, y2 - y1
        denom = dx * dx + dy * dy
        t = 0.0 if denom <= 1e-9 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / denom))
        candidate = (x1 + dx * t, y1 + dy * t)
        dist = (candidate[0] - px) ** 2 + (candidate[1] - py) ** 2
        if dist < best_dist:
            best_dist = dist
            best = candidate
    if best is None:
        return _centroid(pts)
    return best


def _safe_projection(point: Sequence[float | int], polygon: Sequence[Sequence[float | int]]) -> Point:
    """Move a point into a polygon without using rectangular clamping.

    The initial boundary projection is pulled toward the polygon centroid so the
    rounded result lands inside the safe polygon even on thin/inset shapes.
    """
    pts = [_float_point(p) for p in polygon]
    cx, cy = _centroid(pts)
    if point_in_polygon(point, pts):
        return _round_point(point)
    bx, by = _nearest_boundary_point(point, pts)
    # Nudge toward center to avoid sitting just outside after rounding.
    for ratio in (0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.75, 1.0):
        nx = bx + (cx - bx) * ratio
        ny = by + (cy - by) * ratio
        rounded = _round_point((nx, ny))
        if point_in_polygon(rounded, pts):
            return rounded
    return _round_point((cx, cy))


@dataclass(frozen=True)
class BrushInset:
    brush_px: int = 3
    edge_margin_px: int = 2

    @property
    def radius_px(self) -> int:
        return int(math.ceil(max(1, int(self.brush_px)) / 2.0))

    @property
    def total_px(self) -> int:
        return max(1, self.radius_px + max(0, int(self.edge_margin_px)))

    def as_dict(self) -> dict:
        return {'brush_px': int(self.brush_px), 'radius_px': self.radius_px,
                'edge_margin_px': int(self.edge_margin_px), 'total_px': self.total_px}


@dataclass(frozen=True)
class CanvasAnchor:
    kind: str
    center: FloatPoint
    tip: FloatPoint | None = None
    confidence: float = 1.0
    orientation: float | None = None

    def as_dict(self) -> dict:
        return {
            'kind': self.kind,
            'center': tuple(self.center),
            'tip': tuple(self.tip) if self.tip else None,
            'confidence': float(self.confidence),
            'orientation': self.orientation,
        }


@dataclass(frozen=True)
class SafePolygon:
    polygon: tuple[Point, ...]
    safe_polygon: tuple[Point, ...]
    bounds: tuple[int, int, int, int]
    safe_bounds: tuple[int, int, int, int]

    def contains(self, point: Sequence[float | int]) -> bool:
        return point_in_polygon(point, self.polygon)

    def contains_safe(self, point: Sequence[float | int]) -> bool:
        return point_in_polygon(point, self.safe_polygon)

    def clamp_to_safe(self, point: Sequence[float | int]) -> Point:
        return _safe_projection(point, self.safe_polygon)


@dataclass(frozen=True)
class CanvasModel:
    area: tuple[int, int, int, int]
    polygon: tuple[Point, ...]
    safe_polygon: tuple[Point, ...]
    bounds: tuple[int, int, int, int]
    safe_bounds: tuple[int, int, int, int]
    brush_inset: BrushInset
    anchors: tuple[CanvasAnchor, ...] = field(default_factory=tuple)
    confidence: float = 1.0
    polygon_source: str = 'area-rectangle'

    @classmethod
    def from_area(cls, area: Sequence[int | float], brush_px: int | float = 3, edge_margin_px: int = 2) -> 'CanvasModel':
        if len(area) != 4:
            raise ValueError('Canvas area must be (x, y, width, height).')
        x, y, w, h = [int(round(_finite_number(v, 'canvas area'))) for v in area]
        if w < 2 or h < 2:
            raise ValueError('Canvas area is too small for Canvas Guard.')
        left, top = x, y
        right, bottom = x + w - 1, y + h - 1
        return cls.from_polygon(
            _rect_polygon(left, top, right, bottom),
            area=(x, y, w, h),
            brush_px=brush_px,
            edge_margin_px=edge_margin_px,
            polygon_source='area-rectangle',
        )

    @classmethod
    def from_polygon(
        cls,
        polygon: Sequence[Sequence[int | float]],
        area: Sequence[int | float] | None = None,
        brush_px: int | float = 3,
        edge_margin_px: int = 2,
        anchors: Sequence[CanvasAnchor] | None = None,
        confidence: float = 1.0,
        polygon_source: str = 'canvas-polygon',
    ) -> 'CanvasModel':
        pts = _round_polygon(_dedupe_polygon(polygon))
        if area is None:
            left, top, right, bottom = _polygon_bounds(pts)
            area_tuple = (left, top, right - left + 1, bottom - top + 1)
        else:
            if len(area) != 4:
                raise ValueError('Canvas area must be (x, y, width, height).')
            area_tuple = tuple(int(round(_finite_number(v, 'canvas area'))) for v in area)  # type: ignore[assignment]
        inset = BrushInset(int(round(_finite_number(brush_px, 'brush_px'))), int(edge_margin_px))
        left, top, right, bottom = _polygon_bounds(pts)
        safe_pts = inset_polygon(pts, inset.total_px)
        safe_left, safe_top, safe_right, safe_bottom = _polygon_bounds(safe_pts)
        return cls(
            area=area_tuple,  # type: ignore[arg-type]
            polygon=tuple(pts),
            safe_polygon=tuple(safe_pts),
            bounds=(left, top, right, bottom),
            safe_bounds=(safe_left, safe_top, safe_right, safe_bottom),
            brush_inset=inset,
            anchors=tuple(anchors or ()),
            confidence=float(max(0.0, min(1.0, _finite_number(confidence, 'confidence')))),
            polygon_source=str(polygon_source or 'canvas-polygon'),
        )

    @classmethod
    def from_area_or_polygon(
        cls,
        area: Sequence[int | float],
        polygon: Sequence[Sequence[int | float]] | None = None,
        coordinate_space: str | None = None,
        brush_px: int | float = 3,
        edge_margin_px: int = 2,
        anchors: Sequence[CanvasAnchor] | None = None,
        confidence: float = 1.0,
    ) -> 'CanvasModel':
        if polygon:
            screen_polygon = normalize_canvas_polygon(polygon, area=area, coordinate_space=coordinate_space)
            return cls.from_polygon(
                screen_polygon,
                area=area,
                brush_px=brush_px,
                edge_margin_px=edge_margin_px,
                anchors=anchors,
                confidence=confidence,
                polygon_source=(coordinate_space or 'auto-polygon'),
            )
        return cls.from_area(area, brush_px=brush_px, edge_margin_px=edge_margin_px)

    @property
    def safe(self) -> SafePolygon:
        return SafePolygon(self.polygon, self.safe_polygon, self.bounds, self.safe_bounds)

    @property
    def vertex_count(self) -> int:
        return len(self.polygon)

    @property
    def safe_vertex_count(self) -> int:
        return len(self.safe_polygon)

    def as_dict(self) -> dict:
        return {
            'area': self.area,
            'bounds': self.bounds,
            'safe_bounds': self.safe_bounds,
            'polygon': self.polygon,
            'safe_polygon': self.safe_polygon,
            'polygon_source': self.polygon_source,
            'vertex_count': self.vertex_count,
            'safe_vertex_count': self.safe_vertex_count,
            'brush_inset': self.brush_inset.as_dict(),
            'anchors': len(self.anchors),
            'anchor_items': tuple(a.as_dict() for a in self.anchors),
            'confidence': float(self.confidence),
            'active': True,
        }


class CanvasGuard:
    """Validate and brush-inset drawing coordinates against one CanvasModel."""

    def __init__(self, model: CanvasModel):
        self.model = model
        self.safe = model.safe

    @classmethod
    def from_area(cls, area: Sequence[int | float], brush_px: int | float = 3, edge_margin_px: int = 2) -> 'CanvasGuard':
        return cls(CanvasModel.from_area(area, brush_px=brush_px, edge_margin_px=edge_margin_px))

    @classmethod
    def from_polygon(
        cls,
        polygon: Sequence[Sequence[int | float]],
        area: Sequence[int | float] | None = None,
        brush_px: int | float = 3,
        edge_margin_px: int = 2,
        anchors: Sequence[CanvasAnchor] | None = None,
        confidence: float = 1.0,
    ) -> 'CanvasGuard':
        return cls(CanvasModel.from_polygon(polygon, area=area, brush_px=brush_px,
                                            edge_margin_px=edge_margin_px, anchors=anchors,
                                            confidence=confidence))

    @classmethod
    def from_area_or_polygon(
        cls,
        area: Sequence[int | float],
        polygon: Sequence[Sequence[int | float]] | None = None,
        coordinate_space: str | None = None,
        brush_px: int | float = 3,
        edge_margin_px: int = 2,
        anchors: Sequence[CanvasAnchor] | None = None,
        confidence: float = 1.0,
    ) -> 'CanvasGuard':
        return cls(CanvasModel.from_area_or_polygon(area, polygon=polygon, coordinate_space=coordinate_space,
                                                    brush_px=brush_px, edge_margin_px=edge_margin_px,
                                                    anchors=anchors, confidence=confidence))

    def require_source_inside_canvas(self, point: Sequence[int | float], context: str = 'drawing point') -> Point:
        rounded = _round_point(point)
        if not self.safe.contains(rounded):
            raise CanvasSafetyStop(f'Canvas Guard stopped {context}: {rounded} is outside the selected canvas polygon.')
        return rounded

    def protect_point(self, point: Sequence[int | float], context: str = 'drawing point') -> Point:
        """Return a brush-inset-safe point or stop before native input.

        A point inside the selected polygon but too close to the edge is moved to
        the polygon safe inset.  A point outside the selected polygon is never
        guessed or clipped inward; drawing stops because the plan/target is stale.
        """
        rounded = self.require_source_inside_canvas(point, context)
        if self.safe.contains_safe(rounded):
            return rounded
        return self.safe.clamp_to_safe(rounded)

    def protect_path(self, points: Iterable[Sequence[int | float]], context: str = 'drawing path') -> list[Point]:
        out: list[Point] = []
        for index, point in enumerate(points):
            safe_point = self.protect_point(point, f'{context} point {index + 1}')
            if not out or out[-1] != safe_point:
                out.append(safe_point)
        return out

    def clip_segment_to_safe(self, start: Sequence[int | float], end: Sequence[int | float], context: str = 'drawing segment') -> tuple[tuple[Point, Point], ...]:
        """Clip one drawing segment to the brush-inset safe polygon.

        Unlike protect_point(), this does not move both endpoints independently.
        The segment is intersected with safe_polygon first, so edge strokes keep
        their intended angle and terminate exactly at the safe canvas boundary.
        """
        return clip_segment_to_polygon(start, end, self.model.safe_polygon)

    def clip_path_to_safe_subpaths(self, points: Iterable[Sequence[int | float]], context: str = 'drawing path') -> tuple[tuple[Point, ...], ...]:
        """Clip a complete polyline to safe_polygon and preserve split gaps.

        Every planned input point must still be inside the selected canvas polygon;
        Step 7 only replaces independent endpoint clamping near the brush-inset
        edge with true segment clipping. Completely stale/off-canvas plans still
        stop before native input.
        """
        raw_points = tuple(_round_point(p) for p in points)
        for index, point in enumerate(raw_points):
            self.require_source_inside_canvas(point, f'{context} source point {index + 1}')
        subpaths = clip_path_to_polygon(raw_points, self.model.safe_polygon)
        validated: list[tuple[Point, ...]] = []
        for path_index, path in enumerate(subpaths):
            clean: list[Point] = []
            for point_index, point in enumerate(path):
                rounded = _round_point(point)
                if not self.safe.contains_safe(rounded):
                    raise CanvasSafetyStop(
                        f'Canvas Guard stroke clipping produced an unsafe point in {context} '
                        f'subpath {path_index + 1}, point {point_index + 1}: {rounded}.')
                if not clean or clean[-1] != rounded:
                    clean.append(rounded)
            if clean:
                validated.append(tuple(clean))
        return tuple(validated)

    def require_current_safe(self, point: Sequence[int | float], context: str = 'current cursor') -> Point:
        rounded = _round_point(point)
        if not self.safe.contains_safe(rounded):
            raise CanvasSafetyStop(f'Final Mouse Guard stopped {context}: cursor {rounded} is outside the brush-inset safe canvas polygon.')
        return rounded

    def describe(self) -> str:
        x0, y0, x1, y1 = self.model.safe_bounds
        inset = self.model.brush_inset.total_px
        corners = sum(1 for anchor in self.model.anchors if anchor.kind == 'corner')
        triangles = sum(1 for anchor in self.model.anchors if anchor.kind == 'triangle')
        anchor_text = f' · anchors={corners} corners/{triangles} triangles' if self.model.anchors else ''
        return (f'Canvas Guard active · polygon vertices={self.model.vertex_count}'
                f'{anchor_text} · safe bounds=({x0},{y0})–({x1},{y1}) · brush inset={inset}px')


class FinalMouseGuard:
    """Last drawing-coordinate gate before the mouse backend.

    This wrapper is used only for canvas drawing operations. Palette/tool/modal UI
    clicks remain guarded by ScreenGuard because those points intentionally live
    outside the selected canvas.
    """

    def __init__(self, mouse, canvas_guard: CanvasGuard):
        self.mouse = mouse
        self.canvas_guard = canvas_guard

    def set_canvas_guard(self, canvas_guard: CanvasGuard) -> None:
        if not isinstance(canvas_guard, CanvasGuard):
            raise TypeError('FinalMouseGuard requires a CanvasGuard instance.')
        self.canvas_guard = canvas_guard

    def move(self, x: int | float, y: int | float, context: str = 'drawing move') -> Point:
        safe = self.canvas_guard.protect_point((x, y), context)
        self.mouse.move(*safe)
        return safe

    def move_point(self, point: Sequence[int | float], context: str = 'drawing move') -> Point:
        return self.move(point[0], point[1], context=context)

    def press(self, context: str = 'drawing press'):
        if hasattr(self.mouse, 'get_position'):
            self.canvas_guard.require_current_safe(self.mouse.get_position(), context)
        self.mouse.press()

    def click(self, context: str = 'drawing click'):
        if hasattr(self.mouse, 'get_position'):
            self.canvas_guard.require_current_safe(self.mouse.get_position(), context)
        self.mouse.click()

    def release(self):
        self.mouse.release()
