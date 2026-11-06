"""Precision helpers shared by preview planning and native drawing.

The drawing engine ultimately targets integer Windows desktop pixels.  This module
keeps the conversion deterministic and makes the quality/speed trade-off explicit
instead of scattering round()/step-size rules throughout DrawBot.
"""
from __future__ import annotations

import math

PRECISION_PROFILES = {
    # Normal preserves the pre-1.0.2 movement density for compatibility.
    'Normal': {
        'max_step_px': 12.0,
        'cursor_tolerance_px': 1,
        'cursor_attempts': 10,
        'cursor_retry_after': 0,
        'tracking_tolerance_px': 4,
    },
    # High is the new default: exact endpoint placement and denser path sampling.
    'High': {
        'max_step_px': 4.0,
        'cursor_tolerance_px': 0,
        'cursor_attempts': 14,
        'cursor_retry_after': 3,
        'tracking_tolerance_px': 3,
    },
    # Ultra follows long strokes at ~2 px intervals.  It is intentionally slower.
    'Ultra': {
        'max_step_px': 2.0,
        'cursor_tolerance_px': 0,
        'cursor_attempts': 20,
        'cursor_retry_after': 2,
        'tracking_tolerance_px': 2,
    },
}


def validate_precision(value: str) -> str:
    if value not in PRECISION_PROFILES:
        raise ValueError('Choose a valid precision level.')
    return value


def profile(value: str) -> dict:
    return dict(PRECISION_PROFILES[validate_precision(value)])


def round_screen(value: float) -> int:
    """Round .5 deterministically instead of Python's banker's rounding.

    Screen coordinates can be negative on a monitor left/up of the primary
    display, so ties are rounded away from zero symmetrically.
    """
    value = float(value)
    return int(math.floor(value + .5) if value >= 0 else math.ceil(value - .5))


def map_pixel_center(pixel: float, source_size: int, target_size: float, origin: float = 0.0) -> float:
    """Map a source pixel index to a destination pixel-index coordinate.

    The -0.5 term is important.  Without it, a 1:1 mapping turns source pixel 0
    into coordinate 0.5 and creates an alternating one-pixel bias after round().
    """
    source_size = int(source_size)
    if source_size <= 0:
        raise ValueError('Source dimensions must be positive.')
    target_size = float(target_size)
    if not math.isfinite(target_size) or target_size <= 0:
        raise ValueError('Target dimensions must be positive.')
    origin, pixel = float(origin), float(pixel)
    if not math.isfinite(origin) or not math.isfinite(pixel):
        raise ValueError('Pixel coordinates and origin must be finite.')
    return origin + ((pixel + .5) * target_size / source_size) - .5


class CanvasTransform:
    """Deterministic source-image -> physical-screen coordinate transform."""
    __slots__ = ('width', 'height', 'fw', 'fh', 'left', 'top')

    def __init__(self, width: int, height: int, fitted, left: float = 0.0, top: float = 0.0):
        self.width, self.height = int(width), int(height)
        self.fw, self.fh = map(float, fitted)
        self.left, self.top = float(left), float(top)
        if not all(math.isfinite(v) for v in (self.fw,self.fh,self.left,self.top)):
            raise ValueError("Canvas geometry must be finite.")
        if self.width <= 0 or self.height <= 0 or self.fw <= 0 or self.fh <= 0:
            raise ValueError('Canvas transform dimensions must be positive.')

    def float_point(self, x: float, y: float):
        return (map_pixel_center(x, self.width, self.fw, self.left),
                map_pixel_center(y, self.height, self.fh, self.top))

    def point(self, x: float, y: float):
        px, py = self.float_point(x, y)
        return round_screen(px), round_screen(py)


def effective_step(precision: str, requested_step_px: float | int = 8) -> float:
    try:
        requested = float(requested_step_px)
    except (TypeError, ValueError, OverflowError):
        requested = 8.0
    if not math.isfinite(requested) or requested <= 0:
        requested = 8.0
    return max(1.0, min(requested, float(profile(precision)['max_step_px'])))


def precision_path(start, end, precision: str = 'High', requested_step_px: float | int = 8):
    """Return a de-duplicated integer path including *end* but not *start*.

    Sampling uses Euclidean distance (not just max(dx, dy)), so diagonal strokes
    receive the same physical movement density as horizontal/vertical strokes.
    """
    sx, sy = map(int, start)
    ex, ey = map(int, end)
    if (sx, sy) == (ex, ey):
        return []
    step = effective_step(precision, requested_step_px)
    distance = math.hypot(ex - sx, ey - sy)
    count = max(1, int(math.ceil(distance / step)))
    # A malformed/corrupted plan must never allocate an unbounded path.
    if count > 100_000:
        raise ValueError('A brush stroke is unexpectedly long. Select the drawing area again.')
    points = []
    previous = (sx, sy)
    for index in range(1, count + 1):
        ratio = index / count
        point = (round_screen(sx + (ex - sx) * ratio),
                 round_screen(sy + (ey - sy) * ratio))
        if point != previous:
            points.append(point)
            previous = point
    if not points or points[-1] != (ex, ey):
        points.append((ex, ey))
    return points


def precision_path_count(start, end, precision: str = 'High', requested_step_px: float | int = 8) -> int:
    sx, sy = map(int, start)
    ex, ey = map(int, end)
    if (sx, sy) == (ex, ey):
        return 0
    step = effective_step(precision, requested_step_px)
    count = max(1, int(math.ceil(math.hypot(ex - sx, ey - sy) / step)))
    if count > 100_000:
        raise ValueError('A brush stroke is unexpectedly long. Select the drawing area again.')
    # When each sample advances at least one pixel along the major axis,
    # integer rounding cannot produce adjacent duplicates. Normal desktop
    # coordinates also keep floating-point interpolation below rounding error.
    if count <= max(abs(ex - sx), abs(ey - sy)) and max(abs(v) for v in (sx, sy, ex, ey)) <= 2**31:
        return count
    # Dense one-pixel diagonal sampling can repeat points. Preserve the exact
    # execution-path contract for that case and unusually large coordinates.
    return len(precision_path(start, end, precision, requested_step_px))
