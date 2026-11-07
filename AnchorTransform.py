"""Deterministic canvas anchor transform helpers for Image Draw Bot v1.0.50.

No AI/ML is used.  This module only performs conservative coordinate math:
previously saved canvas/corner/triangle anchors are converted from the old target
client rectangle to the current target client rectangle.  Pure translation is
always safe; tiny scale changes are accepted only within strict tolerances and
are still followed by CanvasGuard before native mouse input.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence
from CalibrationValidation import LONG_MIN,LONG_MAX,bounded_number,nonnegative_integer,screen_point

Point = tuple[int, int]
FloatPoint = tuple[float, float]
Rect = tuple[int, int, int, int]
Area = tuple[int, int, int, int]


@dataclass(frozen=True)
class AnchorTransformResult:
    dx: float
    dy: float
    sx: float = 1.0
    sy: float = 1.0
    residual_px: float = 0.0
    max_residual_px: float = 0.0
    used_anchors: int = 0
    used_triangles: int = 0
    method: str = 'client-rect'
    accepted: bool = True

    @property
    def is_identity(self) -> bool:
        return (abs(self.dx) < 1e-7 and abs(self.dy) < 1e-7 and
                abs(self.sx - 1.0) < 1e-7 and abs(self.sy - 1.0) < 1e-7)

    @property
    def scale_changed(self) -> bool:
        return abs(self.sx - 1.0) > 1e-7 or abs(self.sy - 1.0) > 1e-7

    def apply_point(self, point: Sequence[int | float]) -> FloatPoint:
        _validate_transform(self)
        if not isinstance(point,(list,tuple)) or len(point) != 2:
            raise ValueError('Point must contain x and y.')
        x,y=(_finite_coordinate(value) for value in point)
        return (_finite_coordinate(x*self.sx+self.dx),_finite_coordinate(y*self.sy+self.dy))

    def as_dict(self) -> dict:
        return {
            'method': self.method,
            'dx': round(float(self.dx), 4),
            'dy': round(float(self.dy), 4),
            'sx': round(float(self.sx), 6),
            'sy': round(float(self.sy), 6),
            'residual_px': round(float(self.residual_px), 4),
            'max_residual_px': round(float(self.max_residual_px), 4),
            'used_anchors': int(self.used_anchors),
            'used_triangles': int(self.used_triangles),
            'accepted': bool(self.accepted),
        }


def _finite_coordinate(value):
    return bounded_number(value,'coordinate',minimum=LONG_MIN,maximum=LONG_MAX)


def _validate_transform(transform):
    if not isinstance(transform,AnchorTransformResult) or transform.accepted is not True:
        raise ValueError('A rejected anchor transform cannot be applied.')
    _finite_coordinate(transform.dx);_finite_coordinate(transform.dy)
    for scale in (transform.sx,transform.sy):
        if bounded_number(scale,'anchor scale',minimum=0,maximum=LONG_MAX)<=0:
            raise ValueError('Anchor scale must be positive.')


def _rect(value: Sequence[int | float], label: str = 'client rectangle') -> Rect:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'Invalid {label}.')
    try:
        left, top, right, bottom = (round(_finite_coordinate(v)) for v in value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Invalid {label}.') from error
    if right <= left or bottom <= top:
        raise ValueError(f'Invalid {label}.')
    return left, top, right, bottom


def _area(value: Sequence[int | float], label: str = 'canvas area') -> Area:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'Invalid {label}.')
    try:
        x, y, w, h = (round(_finite_coordinate(v)) for v in value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Invalid {label}.') from error
    if w <= 0 or h <= 0:
        raise ValueError(f'Invalid {label}.')
    screen_point((x+w,y+h),label)
    return x, y, w, h


def _anchor_points_from_options(options: Mapping[str, object] | None, area: Area) -> tuple[list[FloatPoint], int]:
    if not isinstance(options, Mapping):
        return [], 0
    raw_anchors = options.get('canvas_anchors') or ()
    if not raw_anchors:
        return [], 0
    from CanvasGuard import normalize_canvas_anchors
    coordinate_space = str(options.get('canvas_anchor_space') or options.get('canvas_polygon_space') or 'normalized')
    anchors = normalize_canvas_anchors(raw_anchors, area=area, coordinate_space=coordinate_space)
    points: list[FloatPoint] = []
    triangles = 0
    for anchor in anchors:
        if anchor.confidence < 0.35:
            continue
        points.append((float(anchor.center[0]), float(anchor.center[1])))
        if anchor.kind == 'triangle':
            triangles += 1
            if anchor.tip is not None:
                # The tip is precise but may be slightly noisier than the center.
                # Include it as additional evidence only when the triangle itself
                # has decent confidence.
                if anchor.confidence >= 0.50:
                    points.append((float(anchor.tip[0]), float(anchor.tip[1])))
    return points, triangles


def _fit_axis_aligned(reference: Sequence[FloatPoint], current: Sequence[FloatPoint]) -> tuple[float, float, float, float, float, float]:
    if len(reference) != len(current) or not reference:
        raise ValueError('Anchor point sets must have the same non-zero length.')
    for points in (reference,current):
        for point in points:
            if not isinstance(point,(list,tuple)) or len(point)!=2:raise ValueError('Invalid anchor point.')
            for value in point:_finite_coordinate(value)
    if len(reference) == 1:
        sx = sy = 1.0
        dx = current[0][0] - reference[0][0]
        dy = current[0][1] - reference[0][1]
    else:
        rx0 = min(p[0] for p in reference); rx1 = max(p[0] for p in reference)
        ry0 = min(p[1] for p in reference); ry1 = max(p[1] for p in reference)
        cx0 = min(p[0] for p in current); cx1 = max(p[0] for p in current)
        cy0 = min(p[1] for p in current); cy1 = max(p[1] for p in current)
        sx = (cx1 - cx0) / (rx1 - rx0) if abs(rx1 - rx0) > 1e-7 else 1.0
        sy = (cy1 - cy0) / (ry1 - ry0) if abs(ry1 - ry0) > 1e-7 else 1.0
        rcx = sum(p[0] for p in reference) / len(reference)
        rcy = sum(p[1] for p in reference) / len(reference)
        ccx = sum(p[0] for p in current) / len(current)
        ccy = sum(p[1] for p in current) / len(current)
        dx = ccx - rcx * sx
        dy = ccy - rcy * sy
    residuals = [math.hypot((r[0] * sx + dx) - c[0], (r[1] * sy + dy) - c[1]) for r, c in zip(reference, current)]
    mean = sum(residuals) / len(residuals) if residuals else 0.0
    max_residual = max(residuals) if residuals else 0.0
    return dx, dy, sx, sy, mean, max_residual


def estimate_client_transform(
    old_client_rect: Sequence[int | float],
    current_client_rect: Sequence[int | float],
    *,
    max_scale_delta: float = 0.025,
    max_size_delta_px: int = 32,
) -> AnchorTransformResult:
    """Estimate a conservative axis-aligned transform from one client rect to another."""
    old = _rect(old_client_rect, 'old client rectangle')
    current = _rect(current_client_rect, 'current client rectangle')
    max_scale_delta=bounded_number(max_scale_delta,'Maximum scale delta',minimum=0,maximum=1)
    max_size_delta_px=nonnegative_integer(max_size_delta_px,'Maximum client size delta')
    old_w, old_h = old[2] - old[0], old[3] - old[1]
    new_w, new_h = current[2] - current[0], current[3] - current[1]
    if abs(new_w - old_w) > int(max_size_delta_px) or abs(new_h - old_h) > int(max_size_delta_px):
        raise ValueError(
            f'The target window changed size from {old_w}×{old_h} to {new_w}×{new_h}. '
            'The change is too large for safe anchor rebasing.')
    sx = new_w / max(1.0, float(old_w))
    sy = new_h / max(1.0, float(old_h))
    if abs(sx - 1.0) > float(max_scale_delta) or abs(sy - 1.0) > float(max_scale_delta):
        raise ValueError(
            f'The target window scale changed too much for safe anchor rebasing: sx={sx:.4f}, sy={sy:.4f}.')
    dx = current[0] - old[0] * sx
    dy = current[1] - old[1] * sy
    method = 'client-translation' if abs(sx - 1.0) < 1e-7 and abs(sy - 1.0) < 1e-7 else 'client-scale'
    return AnchorTransformResult(dx=dx, dy=dy, sx=sx, sy=sy, method=method, used_anchors=4)


def transform_area(area: Sequence[int | float], transform: AnchorTransformResult) -> Area:
    x, y, w, h = _area(area)
    x0, y0 = transform.apply_point((x, y))
    x1, y1 = transform.apply_point((x + w, y + h))
    left = int(round(min(x0, x1)))
    top = int(round(min(y0, y1)))
    right = int(round(max(x0, x1)))
    bottom = int(round(max(y0, y1)))
    if right<=left or bottom<=top:raise ValueError('The transform collapsed the canvas area.')
    return _area((left,top,right-left,bottom-top))


def transform_points(points: Sequence[Sequence[int | float]], transform: AnchorTransformResult) -> tuple[Point, ...]:
    _validate_transform(transform)
    result: list[Point] = []
    for point in points:
        x, y = transform.apply_point(point)
        result.append(screen_point((round(x),round(y))))
    return tuple(result)


def estimate_canvas_anchor_transform(
    old_area: Sequence[int | float],
    candidate_area: Sequence[int | float],
    anchor_options: Mapping[str, object] | None,
    *,
    fallback: AnchorTransformResult,
    max_residual_px: float = 2.5,
) -> AnchorTransformResult:
    """Use stored canvas anchors to validate/refine a client-rect transform.

    The same normalized anchors are projected into the old and candidate areas.
    This lets the six triangle points participate in the rebase math once they
    exist, while four corners keep the system compatible with blank canvases.
    """
    old = _area(old_area, 'old canvas area')
    candidate = _area(candidate_area, 'candidate canvas area')
    _validate_transform(fallback)
    max_residual_px=bounded_number(max_residual_px,'Maximum anchor residual',minimum=0,maximum=LONG_MAX)
    ref, triangles = _anchor_points_from_options(anchor_options, old)
    cur, _ = _anchor_points_from_options(anchor_options, candidate)
    if len(ref) < 2 or len(ref) != len(cur):
        return fallback
    dx, dy, sx, sy, mean, max_residual = _fit_axis_aligned(ref, cur)
    if mean > max_residual_px or max_residual > max_residual_px * 2.0:
        raise ValueError(
            f'Canvas anchors did not agree with the target transform: residual {mean:.2f}px, max {max_residual:.2f}px.')
    method = 'anchors+triangles' if triangles else 'anchors+corners'
    return AnchorTransformResult(dx=dx, dy=dy, sx=sx, sy=sy, residual_px=mean,
                                 max_residual_px=max_residual, used_anchors=len(ref),
                                 used_triangles=triangles, method=method)


def rebase_canvas_area(
    area: Sequence[int | float],
    old_client_rect: Sequence[int | float],
    current_client_rect: Sequence[int | float],
    anchor_options: Mapping[str, object] | None = None,
    *,
    max_scale_delta: float = 0.025,
    max_size_delta_px: int = 32,
) -> tuple[Area, AnchorTransformResult]:
    """Return a safely rebased canvas area and transform metadata."""
    old_area = _area(area)
    if not area_inside_client(old_area,old_client_rect):raise ValueError('The saved canvas is outside its target client area.')
    base = estimate_client_transform(old_client_rect, current_client_rect,
                                     max_scale_delta=max_scale_delta,
                                     max_size_delta_px=max_size_delta_px)
    candidate = transform_area(old_area, base)
    refined = estimate_canvas_anchor_transform(old_area, candidate, anchor_options, fallback=base)
    refined_area = transform_area(old_area, refined)
    if not area_inside_client(refined_area,current_client_rect):raise ValueError('The transformed canvas is outside the current target client area.')
    return refined_area, refined


def area_inside_client(area: Sequence[int | float], client_rect: Sequence[int | float], margin: int = 0) -> bool:
    x, y, w, h = _area(area)
    left, top, right, bottom = _rect(client_rect)
    m = nonnegative_integer(margin,'Canvas containment margin')
    return left + m <= x and top + m <= y and x + w <= right - m and y + h <= bottom - m
