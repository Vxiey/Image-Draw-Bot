"""Deterministic canvas corner/triangle anchor detection for Image Draw Bot v1.0.49.

No AI/ML is used here.  The detector relies on geometry, colour contrast,
connected components and triangle-shape checks.  It is intentionally
conservative: four rectangle corner anchors are always emitted from the user's
selected area, while the six triangle anchors are added only when the screenshot
contains clear triangular marker components.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

from PIL import Image, ImageFilter, ImageOps

from CanvasGuard import CanvasAnchor
from CalibrationValidation import nonnegative_integer

FloatPoint = tuple[float, float]


@dataclass(frozen=True)
class TriangleCandidate:
    center: FloatPoint
    tip: FloatPoint
    confidence: float
    orientation: float
    bbox: tuple[int, int, int, int]
    area: int

    def as_anchor(self) -> CanvasAnchor:
        return CanvasAnchor('triangle', self.center, tip=self.tip,
                            confidence=self.confidence, orientation=self.orientation)

    def as_dict(self) -> dict:
        return {
            'center': tuple(self.center),
            'tip': tuple(self.tip),
            'confidence': float(self.confidence),
            'orientation': float(self.orientation),
            'bbox': tuple(self.bbox),
            'area': int(self.area),
        }


@dataclass(frozen=True)
class AnchorDetectionResult:
    polygon: tuple[FloatPoint, ...]
    anchors: tuple[CanvasAnchor, ...]
    triangle_candidates: tuple[TriangleCandidate, ...]
    width: int
    height: int
    confidence: float
    expected_triangles: int = 6
    method: str = 'deterministic-geometry-v1'

    @property
    def corner_count(self) -> int:
        return sum(1 for a in self.anchors if a.kind == 'corner')

    @property
    def triangle_count(self) -> int:
        return sum(1 for a in self.anchors if a.kind == 'triangle')

    def as_options(self) -> dict:
        return {
            'canvas_polygon': tuple(self.polygon),
            'canvas_polygon_space': 'normalized',
            'canvas_anchors': tuple(anchor.as_dict() for anchor in self.anchors),
            'canvas_anchor_space': 'normalized',
            'canvas_anchor_meta': self.as_dict(compact=True),
        }

    def as_dict(self, compact: bool = False) -> dict:
        data = {
            'method': self.method,
            'width': int(self.width),
            'height': int(self.height),
            'corner_count': int(self.corner_count),
            'triangle_count': int(self.triangle_count),
            'expected_triangles': int(self.expected_triangles),
            'confidence': float(self.confidence),
            'polygon': tuple(self.polygon),
        }
        if not compact:
            data['anchors'] = tuple(a.as_dict() for a in self.anchors)
            data['triangle_candidates'] = tuple(c.as_dict() for c in self.triangle_candidates)
        return data


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalise(point: Sequence[float | int], width: int, height: int) -> FloatPoint:
    x = _clamp01(float(point[0]) / max(1.0, float(width - 1)))
    y = _clamp01(float(point[1]) / max(1.0, float(height - 1)))
    return (x, y)


def _corner_anchors(width: int, height: int) -> tuple[CanvasAnchor, ...]:
    corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    return tuple(CanvasAnchor('corner', p, tip=None, confidence=1.0, orientation=None) for p in corners)


def _border_background(rgb: Image.Image) -> tuple[float, float, float]:
    width, height = rgb.size
    samples: list[tuple[int, int, int]] = []
    if width <= 0 or height <= 0:
        return (255.0, 255.0, 255.0)
    step_x = max(1, width // 80)
    step_y = max(1, height // 80)
    px = rgb.load()
    for x in range(0, width, step_x):
        samples.append(px[x, 0]); samples.append(px[x, height - 1])
    for y in range(0, height, step_y):
        samples.append(px[0, y]); samples.append(px[width - 1, y])
    if not samples:
        return (255.0, 255.0, 255.0)
    channels = []
    for i in range(3):
        values = sorted(float(p[i]) for p in samples)
        channels.append(values[len(values) // 2])
    return tuple(channels)  # type: ignore[return-value]


def _binary_foreground(rgb: Image.Image) -> list[bytearray]:
    import numpy as np
    bg = _border_background(rgb)
    pixels=np.asarray(rgb,dtype=np.int16)
    distance=np.abs(pixels-np.asarray(bg,dtype=np.int16)).sum(axis=2)
    saturation=pixels.max(axis=2)-pixels.min(axis=2)
    with ImageOps.grayscale(rgb) as gray:
        with gray.filter(ImageFilter.FIND_EDGES) as edges:
            foreground=(distance>=95)|(saturation>=55)|(np.asarray(edges)>=115)
    return [bytearray(row) for row in foreground.astype(np.uint8)]


def _component_points(mask: list[bytearray], max_components: int = 120, *, max_side=None,
                      cancelled=lambda:False) -> list[list[tuple[int, int]]]:
    height = len(mask)
    width = len(mask[0]) if height else 0
    seen = [bytearray(width) for _ in range(height)]
    components: list[list[tuple[int, int]]] = []
    for y in range(height):
        if y%16==0 and cancelled():raise InterruptedError('Canvas anchor detection cancelled.')
        for x in range(width):
            if not mask[y][x] or seen[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = 1
            pts: list[tuple[int, int]] = []
            left=right=x;top=bottom=y;oversized=False;visited=0
            while stack:
                cx, cy = stack.pop()
                visited+=1
                if visited%4096==0 and cancelled():raise InterruptedError('Canvas anchor detection cancelled.')
                if not oversized:
                    left=min(left,cx);right=max(right,cx);top=min(top,cy);bottom=max(bottom,cy)
                    if max_side is not None and max(right-left+1,bottom-top+1)>max_side:
                        oversized=True;pts.clear()
                    else:pts.append((cx,cy))
                for ny in (cy - 1, cy, cy + 1):
                    if ny < 0 or ny >= height:
                        continue
                    for nx in (cx - 1, cx, cx + 1):
                        if nx < 0 or nx >= width or (nx == cx and ny == cy):
                            continue
                        if mask[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = 1
                            stack.append((nx, ny))
            # Single-pixel noise must not spend the budget reserved for actual
            # marker candidates farther down the image.
            if len(pts)<18:continue
            components.append(pts)
            if len(components) >= max_components:
                return components
    return components


def _point_line_distance(p: FloatPoint, a: FloatPoint, b: FloatPoint) -> float:
    px, py = p; ax, ay = a; bx, by = b
    dx, dy = bx - ax, by - ay
    denom = math.hypot(dx, dy)
    if denom <= 1e-9:
        return math.hypot(px - ax, py - ay)
    return abs((px - ax) * dy - (py - ay) * dx) / denom


def _triangle_area(a: FloatPoint, b: FloatPoint, c: FloatPoint) -> float:
    return abs((a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1])) / 2.0)


def _inside_triangle(p: FloatPoint, a: FloatPoint, b: FloatPoint, c: FloatPoint) -> bool:
    area = _triangle_area(a, b, c)
    if area <= 1e-7:
        return False
    a1 = _triangle_area(p, b, c)
    a2 = _triangle_area(a, p, c)
    a3 = _triangle_area(a, b, p)
    return abs((a1 + a2 + a3) - area) <= max(1.0, area * 0.10)


def _farthest(points: Sequence[FloatPoint], origin: FloatPoint) -> FloatPoint:
    ox, oy = origin
    return max(points, key=lambda p: (p[0] - ox) ** 2 + (p[1] - oy) ** 2)


def _candidate_from_component(points: list[tuple[int, int]], width: int, height: int) -> TriangleCandidate | None:
    if len(points) < 18:
        return None
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    min_side = max(5, int(min(width, height) * 0.012))
    max_side = max(18, int(min(width, height) * 0.38))
    if bw < min_side or bh < min_side or bw > max_side or bh > max_side:
        return None
    bbox_area = max(1, bw * bh)
    density = len(points) / bbox_area
    if not 0.10 <= density <= 0.86:
        return None
    # Work on a bounded sample so very large components do not slow selection.
    if len(points) > 700:
        step = math.ceil(len(points) / 700)
        raw = points[::step]
    else:
        raw = points
    pts = [(float(x), float(y)) for x, y in raw]
    cx = sum(x for x, _ in pts) / len(pts); cy = sum(y for _, y in pts) / len(pts)
    v1 = _farthest(pts, (cx, cy))
    v2 = _farthest(pts, v1)
    v3 = max(pts, key=lambda p: _point_line_distance(p, v1, v2))
    tri_area = _triangle_area(v1, v2, v3)
    if tri_area < max(12.0, bbox_area * 0.18):
        return None
    # Avoid long diagonal scratches: a triangle should explain most of its own
    # component points and not have a huge empty hull.
    inside = sum(1 for p in pts if _inside_triangle(p, v1, v2, v3)) / max(1, len(pts))
    fill_ratio = min(1.0, len(points) / max(1.0, tri_area))
    if inside < 0.72 or fill_ratio < 0.18:
        return None
    vertices = (v1, v2, v3)
    tip = max(vertices, key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
    orientation = math.degrees(math.atan2(tip[1] - cy, tip[0] - cx))
    score = 0.35 * inside + 0.25 * min(1.0, fill_ratio) + 0.20 * min(1.0, density * 2.2)
    # Compactness reward: triangular handles are normally not thin lines.
    compact = min(bw, bh) / max(1, max(bw, bh))
    score += 0.20 * max(0.0, min(1.0, compact * 1.7))
    confidence = max(0.0, min(0.96, score))
    if confidence < 0.50:
        return None
    return TriangleCandidate(center=_normalise((cx, cy), width, height),
                             tip=_normalise(tip, width, height),
                             confidence=confidence,
                             orientation=orientation,
                             bbox=(x0, y0, x1, y1),
                             area=len(points))


def _suppress_near_duplicates(candidates: Iterable[TriangleCandidate], min_distance: float = 0.035) -> tuple[TriangleCandidate, ...]:
    accepted: list[TriangleCandidate] = []
    for candidate in sorted(candidates, key=lambda c: c.confidence, reverse=True):
        cx, cy = candidate.center
        if any(math.hypot(cx - a.center[0], cy - a.center[1]) < min_distance for a in accepted):
            continue
        accepted.append(candidate)
    return tuple(sorted(accepted, key=lambda c: (c.center[1], c.center[0])))


def detect_triangle_anchors(image: Image.Image, expected: int = 6, *, cancelled=lambda:False) -> tuple[TriangleCandidate, ...]:
    """Detect triangular marker components in a selected canvas screenshot."""
    expected=nonnegative_integer(expected,'Expected triangle count',maximum=120)
    if cancelled():raise InterruptedError('Canvas anchor detection cancelled.')
    if not expected or image.width < 10 or image.height < 10:
        return ()
    max_dim = max(image.width, image.height)
    from ColorMatchingEngine import visible_rgb_image
    rgb=image if image.mode=='RGB' and 'transparency' not in image.info else visible_rgb_image(image)
    working=rgb
    try:
        if max_dim > 520:
            scale = 520.0 / max_dim
            working = rgb.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.BILINEAR)
        mask = _binary_foreground(working)
        found: list[TriangleCandidate] = []
        max_side=max(18,int(min(working.size)*0.38))
        for pts in _component_points(mask,max_side=max_side,cancelled=cancelled):
            if cancelled():raise InterruptedError('Canvas anchor detection cancelled.')
            candidate = _candidate_from_component(pts, working.width, working.height)
            if candidate is not None:found.append(candidate)
        return _suppress_near_duplicates(found)[:expected]
    finally:
        if working is not rgb:working.close()
        if rgb is not image:rgb.close()


def detect_canvas_anchors(image: Image.Image | None, expected_triangles: int = 6, *, cancelled=lambda:False) -> AnchorDetectionResult:
    """Return rectangle corners plus any detected triangle marker anchors.

    The returned polygon and anchors use normalized canvas coordinates so they
    survive target-window translations and can be mapped to the live screen area
    by CanvasGuard at execution time.
    """
    expected_triangles=nonnegative_integer(expected_triangles,'Expected triangle count',maximum=120)
    if cancelled():raise InterruptedError('Canvas anchor detection cancelled.')
    if image is None:
        width = height = 1
        triangles: tuple[TriangleCandidate, ...] = ()
    else:
        width, height = max(1, int(image.width)), max(1, int(image.height))
        triangles = detect_triangle_anchors(image, expected_triangles,cancelled=cancelled)
    corners = _corner_anchors(width, height)
    triangle_anchors = tuple(t.as_anchor() for t in triangles)
    expected = max(1, int(expected_triangles))
    triangle_factor = min(1.0, len(triangle_anchors) / expected)
    # Corners are deterministic from the user-selected crop. Triangles are
    # additive evidence, not a safety prerequisite.
    confidence = min(1.0, 0.78 + 0.22 * triangle_factor)
    return AnchorDetectionResult(
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        anchors=corners + triangle_anchors,
        triangle_candidates=triangles,
        width=width,
        height=height,
        confidence=confidence,
        expected_triangles=expected_triangles,
    )
