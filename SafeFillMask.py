"""Deterministic Safe Fill mask layer for Image Draw Bot v1.0.52.

This module is intentionally small and non-AI.  It protects bucket-fill plans
before the mouse layer by requiring fill seeds, perimeters and row spans to stay
inside a brush-inset source/canvas mask.  Unsafe fill regions are rejected so the
normal stroke renderer remains the fallback.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Sequence, Tuple

Point = Tuple[int, int]


def _pair(point: Sequence[int | float]) -> Point:
    if isinstance(point, (str, bytes, Mapping)) or len(point) != 2:
        raise ValueError('point must contain x and y')
    return int(round(float(point[0]))), int(round(float(point[1])))


def _source_size(size: Sequence[int | float]) -> tuple[int, int]:
    if len(size) != 2:
        raise ValueError('source size must be (width, height)')
    w, h = int(round(float(size[0]))), int(round(float(size[1])))
    if w <= 0 or h <= 0:
        raise ValueError('source size must be positive')
    return w, h


def source_fill_margin_px(brush_px: int | float = 3, edge_margin_px: int | float = 2,
                          source_size: Sequence[int | float] | None = None) -> int:
    """Return a conservative source-pixel margin for Fill planning.

    The margin mirrors CanvasGuard's brush inset.  Very small images reduce the
    margin so the safe mask never collapses to an impossible area.
    """
    try:
        radius = int(round((max(1.0, float(brush_px)) + 1.0) / 2.0))
    except (TypeError, ValueError):
        radius = 2
    try:
        extra = int(round(max(0.0, float(edge_margin_px))))
    except (TypeError, ValueError):
        extra = 2
    margin = max(1, radius + extra)
    if source_size is not None:
        w, h = _source_size(source_size)
        margin = min(margin, max(1, (min(w, h) - 3) // 2))
    return margin


def source_safe_bounds(size: Sequence[int | float], margin_px: int | float) -> tuple[int, int, int, int]:
    w, h = _source_size(size)
    margin = max(0, int(round(float(margin_px))))
    margin = min(margin, max(0, (min(w, h) - 1) // 2))
    return margin, margin, w - 1 - margin, h - 1 - margin


def point_inside_source_mask(point: Sequence[int | float], size: Sequence[int | float], margin_px: int | float) -> bool:
    x, y = _pair(point)
    left, top, right, bottom = source_safe_bounds(size, margin_px)
    return left <= x <= right and top <= y <= bottom


def _row_spans(region: Mapping[str, object]) -> tuple[tuple[int, int, int], ...]:
    spans = region.get('row_spans')
    if spans is None:
        spans = ()
    if isinstance(spans, (str, bytes, Mapping)):
        raise ValueError('invalid row spans')
    try:
        iterator = iter(spans)
    except TypeError as error:
        raise ValueError('invalid row spans') from error
    out = []
    for raw in iterator:
        try:
            if isinstance(raw, (str, bytes, Mapping)) or len(raw) != 3:
                raise ValueError('invalid row span')
            y, x0, x1 = raw  # type: ignore[misc]
            converted = (int(y), int(x0), int(x1))
            if any(clean != original for clean, original in zip(converted, raw)) or converted[1] > converted[2]:
                raise ValueError('invalid row span')
            out.append(converted)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError('invalid row span') from error
    if out:
        return tuple(out)
    try:
        x0, y0, x1, y1 = [int(v) for v in region.get('bbox', ())]  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return ()
    return tuple((y, x0, x1) for y in range(y0, y1 + 1))


def _contour_points(region: Mapping[str, object]) -> tuple[Point, ...] | None:
    contour = region.get('contour')
    if contour is None:
        contour = ()
    if isinstance(contour, (str, bytes, Mapping)):
        return None
    try:
        iterator = iter(contour)
    except TypeError:
        return None
    out = []
    for raw in iterator:
        try:
            out.append(_pair(raw))
        except (TypeError, ValueError, OverflowError):
            return None
    return tuple(out)


def _region_mask_failure(region: Mapping[str, object], size: Sequence[int | float], margin_px: int | float) -> str:
    try:
        x0, y0, x1, y1 = [int(v) for v in region.get('bbox', ())]  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 'invalid bbox'
    w, h = _source_size(size)
    if x0 < 0 or y0 < 0 or x1 >= w or y1 >= h or x0 > x1 or y0 > y1:
        return 'bbox outside source'
    left, top, right, bottom = source_safe_bounds(size, margin_px)
    if x0 < left or y0 < top or x1 > right or y1 > bottom:
        return 'outside safe fill mask'
    try:
        seed = _pair(region.get('seed_pixel', ()))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 'invalid seed'
    if not point_inside_source_mask(seed, size, margin_px):
        return 'seed outside safe fill mask'
    try:
        spans = _row_spans(region)
    except (TypeError, ValueError, OverflowError):
        return 'invalid row span'
    seed_in_region = False
    for y, sx0, sx1 in spans:
        if y < top or y > bottom or sx0 < left or sx1 > right:
            return 'span outside safe fill mask'
        if not y0 <= y <= y1 or sx0 < x0 or sx1 > x1:
            return 'span outside region bbox'
        seed_in_region |= y == seed[1] and sx0 <= seed[0] <= sx1
    if not seed_in_region:
        return 'seed outside intended region'
    contour = _contour_points(region)
    if contour is None:
        return 'invalid contour'
    if contour:
        for point in contour:
            if not point_inside_source_mask(point, size, margin_px):
                return 'contour outside safe fill mask'
    return ''


def filter_fill_regions_by_source_mask(regions: Iterable[Mapping[str, object]], size: Sequence[int | float],
                                       *, brush_px: int | float = 3, edge_margin_px: int | float = 2,
                                       margin_px: int | float | None = None) -> tuple[list[dict], dict]:
    """Remove bucket-fill regions that are too close to the source/canvas edge."""
    if margin_px is None:
        margin_px = source_fill_margin_px(brush_px, edge_margin_px, size)
    margin = int(round(float(margin_px)))
    accepted: list[dict] = []
    rejected = Counter()
    total = 0
    for raw in regions or ():
        total += 1
        region = dict(raw)
        why = _region_mask_failure(region, size, margin)
        if why:
            rejected[why] += 1
            continue
        safe_region = dict(region)
        safe_region['safe_fill_mask'] = True
        safe_region['safe_fill_margin_px'] = margin
        accepted.append(safe_region)
    meta = {
        'active': True,
        'source_size': tuple(_source_size(size)),
        'margin_px': margin,
        'input_regions': total,
        'accepted_regions': len(accepted),
        'rejected_regions': total - len(accepted),
        'rejected': dict(rejected),
    }
    return accepted, meta


def choose_safe_background_seed(candidates: Iterable[Sequence[int | float]], size: Sequence[int | float],
                                margin_px: int | float) -> tuple[Point, ...]:
    """Return unique candidates inside the same source mask used by Better Fill."""
    safe = []
    seen = set()
    for raw in candidates:
        try:
            point = _pair(raw)
        except (TypeError, ValueError):
            continue
        if point in seen:
            continue
        seen.add(point)
        if point_inside_source_mask(point, size, margin_px):
            safe.append(point)
    if safe:
        return tuple(safe)
    left, top, right, bottom = source_safe_bounds(size, margin_px)
    cx, cy = (left + right) // 2, (top + bottom) // 2
    fallback = ((left, top), (right, top), (left, bottom), (right, bottom), (cx, cy))
    return tuple(dict.fromkeys(fallback))


@dataclass(frozen=True)
class RuntimeFillMaskResult:
    accepted_regions: tuple[dict, ...]
    input_regions: int
    rejected_regions: int
    rejected: dict

    @property
    def ok(self) -> bool:
        return self.rejected_regions == 0

    def as_dict(self) -> dict:
        data = asdict(self)
        data['accepted_regions'] = len(self.accepted_regions)
        data['active'] = True
        return data


def _source_to_screen(transform, point: Sequence[int | float]) -> Point:
    x, y = _pair(point)
    return tuple(map(int, transform.point(x, y)))  # type: ignore[return-value]


def _screen_safe(canvas_guard, screen: Sequence[int | float]) -> bool:
    try:
        return bool(canvas_guard.safe.contains_safe(screen))
    except AttributeError:
        return False


def _runtime_region_failure(region: Mapping[str, object], source_size: Sequence[int | float], transform, canvas_guard) -> str:
    w, h = _source_size(source_size)
    def source_ok(point: Sequence[int | float]) -> bool:
        x, y = _pair(point)
        return 0 <= x < w and 0 <= y < h and _screen_safe(canvas_guard, _source_to_screen(transform, (x, y)))
    try:
        seed = _pair(region.get('seed_pixel', ()))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 'invalid seed'
    if not source_ok(seed):
        return 'seed outside runtime safe canvas'
    try:
        x0, y0, x1, y1 = [int(v) for v in region.get('bbox', ())]  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 'invalid bbox'
    if x0 > x1 or y0 > y1:
        return 'invalid bbox'
    for point in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        if not source_ok(point):
            return 'bbox outside runtime safe canvas'
    contour = _contour_points(region)
    if contour is None:
        return 'invalid contour'
    if contour:
        for point in contour:
            if not source_ok(point):
                return 'contour outside runtime safe canvas'
    try:
        spans = _row_spans(region)
    except (TypeError, ValueError, OverflowError):
        return 'invalid row span'
    seed_in_region = False
    for y, sx0, sx1 in spans:
        if not source_ok((sx0, y)) or not source_ok((sx1, y)):
            return 'span outside runtime safe canvas'
        if not y0 <= y <= y1 or sx0 < x0 or sx1 > x1:
            return 'span outside region bbox'
        seed_in_region |= y == seed[1] and sx0 <= seed[0] <= sx1
    if not seed_in_region:
        return 'seed outside intended region'
    return ''


def filter_fill_regions_by_runtime_mask(regions: Iterable[Mapping[str, object]], source_size: Sequence[int | float],
                                        transform, canvas_guard) -> RuntimeFillMaskResult:
    """Final no-clamp fill gate used immediately before selecting the Fill tool."""
    accepted: list[dict] = []
    rejected = Counter()
    total = 0
    for raw in regions or ():
        total += 1
        region = dict(raw)
        why = _runtime_region_failure(region, source_size, transform, canvas_guard)
        if why:
            rejected[why] += 1
            continue
        region['runtime_safe_fill_mask'] = True
        accepted.append(region)
    return RuntimeFillMaskResult(tuple(accepted), total, total - len(accepted), dict(rejected))
