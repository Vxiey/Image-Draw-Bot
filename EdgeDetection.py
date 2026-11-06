"""Deterministic canvas edge verification for Image Draw Bot v1.0.51.

No AI/ML is used.  The verifier reads a screenshot around the selected canvas,
looks for real contrast edges near the selected rectangle, and stops only when a
clear edge is detected too far away from the saved canvas boundary.  Weak or
unavailable edges fall back to CanvasGuard instead of causing false positives on
blank/full-window canvases.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import math

try:  # Pillow is already required by Image Draw Bot.
    from PIL import Image
except Exception:  # pragma: no cover - import-time fallback for static tooling
    Image = object  # type: ignore

Rect = tuple[int, int, int, int]  # x, y, w, h
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class EdgeSideResult:
    side: str
    available: bool
    detected: bool
    ok: bool
    offset_px: int = 0
    strength: float = 0.0
    contrast: float = 0.0
    reason: str = ''

    def as_dict(self) -> dict:
        return {
            'side': self.side,
            'available': bool(self.available),
            'detected': bool(self.detected),
            'ok': bool(self.ok),
            'offset_px': int(self.offset_px),
            'strength': round(float(self.strength), 3),
            'contrast': round(float(self.contrast), 3),
            'reason': self.reason,
        }


@dataclass(frozen=True)
class CanvasEdgeResult:
    ok: bool
    confidence: float
    sides: tuple[EdgeSideResult, ...]
    max_offset_px: int
    tolerance_px: int
    method: str = 'deterministic-gradient'

    @property
    def available_sides(self) -> int:
        return sum(1 for s in self.sides if s.available)

    @property
    def detected_sides(self) -> int:
        return sum(1 for s in self.sides if s.detected)

    @property
    def failed_sides(self) -> tuple[EdgeSideResult, ...]:
        return tuple(s for s in self.sides if s.available and s.detected and not s.ok)

    def as_dict(self) -> dict:
        return {
            'ok': bool(self.ok),
            'confidence': round(float(self.confidence), 4),
            'available_sides': int(self.available_sides),
            'detected_sides': int(self.detected_sides),
            'max_offset_px': int(self.max_offset_px),
            'tolerance_px': int(self.tolerance_px),
            'method': self.method,
            'sides': tuple(s.as_dict() for s in self.sides),
        }

    def describe(self) -> str:
        if not self.available_sides:
            return 'Edge verification: no outside margin available; Canvas Guard fallback remains active.'
        if not self.detected_sides:
            return 'Edge verification: no strong external edges detected; Canvas Guard fallback remains active.'
        status = 'passed' if self.ok else 'stopped'
        return (f'Edge verification {status}: {self.detected_sides}/{self.available_sides} side(s) detected, '
                f'max offset {self.max_offset_px}px, confidence {self.confidence*100:.0f}%.')

    def stop_message(self) -> str:
        failures = self.failed_sides
        if not failures:
            return 'Canvas edge verification stopped before drawing.'
        worst = max(failures, key=lambda s: abs(s.offset_px))
        return (f'Canvas edge verification stopped before drawing: the {worst.side} edge appears '
                f'{worst.offset_px:+d}px from the selected canvas boundary. Select only the real canvas and retry. '
                'No mouse input was sent.')


def _rect(value: Sequence[int | float], label: str = 'rectangle') -> Rect:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError(f'Invalid {label}.')
    try:
        x, y, w, h = (int(round(float(v))) for v in value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Invalid {label}.') from error
    if w <= 0 or h <= 0:
        raise ValueError(f'Invalid {label}.')
    return x, y, w, h


def _luma(rgb: RGB) -> float:
    return float(rgb[0]) * 0.299 + float(rgb[1]) * 0.587 + float(rgb[2]) * 0.114


def _rgb_distance(a: RGB, b: RGB) -> float:
    return math.sqrt(((int(a[0]) - int(b[0])) ** 2) * 0.30 +
                     ((int(a[1]) - int(b[1])) ** 2) * 0.59 +
                     ((int(a[2]) - int(b[2])) ** 2) * 0.11)


def _mean_rgb(image: Image.Image, box: tuple[int, int, int, int], max_samples: int = 900) -> RGB:
    left, top, right, bottom = box
    left = max(0, min(image.width, int(left)))
    right = max(0, min(image.width, int(right)))
    top = max(0, min(image.height, int(top)))
    bottom = max(0, min(image.height, int(bottom)))
    if right <= left or bottom <= top:
        return (0, 0, 0)
    pixels = image.load()
    total = (right - left) * (bottom - top)
    stride = max(1, int(math.ceil(math.sqrt(total / max(1, int(max_samples))))))
    r = g = b = count = 0
    for yy in range(top, bottom, stride):
        for xx in range(left, right, stride):
            pr, pg, pb = pixels[xx, yy][:3]
            r += int(pr); g += int(pg); b += int(pb); count += 1
    if not count:
        return (0, 0, 0)
    return (int(round(r / count)), int(round(g / count)), int(round(b / count)))


def _vertical_strength(image: Image.Image, boundary_x: int, top: int, bottom: int, max_samples: int = 600) -> float:
    x = int(boundary_x)
    if x <= 0 or x >= image.width:
        return 0.0
    top = max(0, min(image.height, int(top)))
    bottom = max(0, min(image.height, int(bottom)))
    if bottom <= top:
        return 0.0
    step = max(1, int(math.ceil((bottom - top) / max(1, int(max_samples)))))
    pixels = image.load(); total = 0.0; count = 0
    for yy in range(top, bottom, step):
        # A chromatic canvas boundary can have exactly the same luminance on
        # both sides. Use the same RGB evidence as the side-band contrast so
        # that accepting a colored edge also gives it a real location.
        total += _rgb_distance(pixels[x, yy][:3], pixels[x - 1, yy][:3])
        count += 1
    return total / max(1, count)


def _horizontal_strength(image: Image.Image, boundary_y: int, left: int, right: int, max_samples: int = 600) -> float:
    y = int(boundary_y)
    if y <= 0 or y >= image.height:
        return 0.0
    left = max(0, min(image.width, int(left)))
    right = max(0, min(image.width, int(right)))
    if right <= left:
        return 0.0
    step = max(1, int(math.ceil((right - left) / max(1, int(max_samples)))))
    pixels = image.load(); total = 0.0; count = 0
    for xx in range(left, right, step):
        total += _rgb_distance(pixels[xx, y][:3], pixels[xx, y - 1][:3])
        count += 1
    return total / max(1, count)


def _best_vertical_edge(image: Image.Image, expected_x: int, top: int, bottom: int, search_px: int) -> tuple[int, float]:
    left = max(1, expected_x - search_px)
    right = min(image.width - 1, expected_x + search_px)
    best_x = expected_x
    best_strength = 0.0
    for x in range(left, right + 1):
        strength = _vertical_strength(image, x, top, bottom)
        if (strength > best_strength or
                (strength == best_strength and abs(x - expected_x) < abs(best_x - expected_x))):
            best_x, best_strength = x, strength
    return best_x, max(0.0, best_strength)


def _best_horizontal_edge(image: Image.Image, expected_y: int, left: int, right: int, search_px: int) -> tuple[int, float]:
    top = max(1, expected_y - search_px)
    bottom = min(image.height - 1, expected_y + search_px)
    best_y = expected_y
    best_strength = 0.0
    for y in range(top, bottom + 1):
        strength = _horizontal_strength(image, y, left, right)
        if (strength > best_strength or
                (strength == best_strength and abs(y - expected_y) < abs(best_y - expected_y))):
            best_y, best_strength = y, strength
    return best_y, max(0.0, best_strength)


def _side_contrast(image: Image.Image, selected: Rect, side: str, band_px: int) -> tuple[bool, float]:
    x, y, w, h = selected
    x1 = x + w; y1 = y + h
    band = max(2, int(band_px))
    # Leave 1 px at the boundary so anti-aliased borders do not dominate both bands.
    if side == 'left':
        outside = (x - band, y, x - 1, y1)
        inside = (x + 1, y, min(x1, x + band + 1), y1)
        available = x - band >= 0
    elif side == 'right':
        outside = (x1 + 1, y, x1 + band, y1)
        inside = (max(x, x1 - band - 1), y, x1 - 1, y1)
        available = x1 + band <= image.width
    elif side == 'top':
        outside = (x, y - band, x1, y - 1)
        inside = (x, y + 1, x1, min(y1, y + band + 1))
        available = y - band >= 0
    elif side == 'bottom':
        outside = (x, y1 + 1, x1, y1 + band)
        inside = (x, max(y, y1 - band - 1), x1, y1 - 1)
        available = y1 + band <= image.height
    else:
        raise ValueError('Invalid edge side.')
    if not available:
        return False, 0.0
    return True, _rgb_distance(_mean_rgb(image, outside), _mean_rgb(image, inside))


def verify_canvas_edges(
    screenshot: Image.Image,
    selected_box: Sequence[int | float],
    *,
    tolerance_px: int = 4,
    search_px: int = 24,
    band_px: int = 5,
    min_strength: float = 10.0,
    min_contrast: float = 14.0,
) -> CanvasEdgeResult:
    """Verify that visible canvas edges agree with the selected rectangle.

    ``screenshot`` is normally an expanded capture around the selected canvas.
    ``selected_box`` is the selected canvas rectangle relative to that screenshot.
    If there is no outside margin, or the side has no strong visible edge, that
    side is marked as a safe fallback rather than a failure.
    """
    if screenshot is None:
        raise ValueError('No screenshot was provided for edge verification.')
    selected = _rect(selected_box, 'selected canvas box')
    x, y, w, h = selected
    if x < 0 or y < 0 or x + w > screenshot.width or y + h > screenshot.height:
        raise ValueError('Selected canvas box is outside the edge-verification screenshot.')
    tolerance = max(1, int(tolerance_px))
    search = max(tolerance + 2, int(search_px))
    band = max(2, int(band_px))
    image = screenshot if screenshot.mode == 'RGB' else screenshot.convert('RGB')
    try:
        return _verify_rgb_edges(image, selected, tolerance, search, band, min_strength, min_contrast)
    finally:
        if image is not screenshot:
            image.close()


def _verify_rgb_edges(image, selected, tolerance, search, band, min_strength, min_contrast):
    x, y, w, h = selected
    side_results: list[EdgeSideResult] = []

    specs = (
        ('left', x, 'vertical'),
        ('right', x + w, 'vertical'),
        ('top', y, 'horizontal'),
        ('bottom', y + h, 'horizontal'),
    )
    for side, expected, axis in specs:
        available, contrast = _side_contrast(image, selected, side, band)
        if not available:
            side_results.append(EdgeSideResult(side, False, False, True, reason='outside margin unavailable'))
            continue
        if axis == 'vertical':
            best, strength = _best_vertical_edge(image, expected, y, y + h, search)
        else:
            best, strength = _best_horizontal_edge(image, expected, x, x + w, search)
        # Band contrast alone cannot localize a boundary when every sampled
        # adjacent pair is identical. Keep that case on the normal fallback.
        strong = strength > 0.0 and (strength >= float(min_strength) or contrast >= float(min_contrast))
        if not strong:
            side_results.append(EdgeSideResult(side, True, False, True, 0, strength, contrast, 'no strong visible edge'))
            continue
        offset = int(best - expected)
        # A visible edge *outside* the selected rectangle means the user/auto
        # detector chose a conservative inset. That cannot cause drawing to
        # escape the real canvas because CanvasGuard is already tighter than
        # the visible boundary. Only an edge that falls *inside* the selected
        # rectangle is safety-critical. Gartic Phone in particular renders
        # stacked-paper decoration below the real canvas, which can otherwise
        # look like a stronger +20px bottom edge.
        conservative_outset = (
            (side == 'left' and offset < -tolerance) or
            (side == 'right' and offset > tolerance) or
            (side == 'top' and offset < -tolerance) or
            (side == 'bottom' and offset > tolerance)
        )
        ok = abs(offset) <= tolerance or conservative_outset
        if abs(offset) <= tolerance:
            reason = 'edge near selected boundary'
        elif conservative_outset:
            reason = 'selected canvas is conservatively inside visible edge'
        else:
            reason = 'visible edge falls inside selected canvas and exceeds tolerance'
        side_results.append(EdgeSideResult(side, True, True, ok, offset, strength, contrast, reason))

    failures = tuple(s for s in side_results if s.available and s.detected and not s.ok)
    detected = sum(1 for s in side_results if s.detected)
    available = sum(1 for s in side_results if s.available)
    max_offset = max((abs(s.offset_px) for s in side_results if s.detected), default=0)
    if failures:
        confidence = max(0.0, min(1.0, 0.95 - 0.08 * len(failures)))
    elif detected:
        close = sum(1 for s in side_results if s.detected and abs(s.offset_px) <= tolerance)
        confidence = max(0.45, min(1.0, 0.55 + 0.45 * close / max(1, detected)))
    elif available:
        confidence = 0.35
    else:
        confidence = 0.20
    return CanvasEdgeResult(ok=not failures, confidence=confidence, sides=tuple(side_results),
                            max_offset_px=int(max_offset), tolerance_px=tolerance)


def verify_canvas_edges_from_capture(capture: object, *, tolerance_px: int = 4, search_px: int = 24) -> CanvasEdgeResult:
    """Accept either (image, selected_box, bbox) or (image, selected_box)."""
    if not isinstance(capture, (tuple, list)) or len(capture) < 2:
        raise ValueError('Edge capture must contain an image and selected box.')
    image = capture[0]
    selected_box = capture[1]
    return verify_canvas_edges(image, selected_box, tolerance_px=tolerance_px, search_px=search_px)
