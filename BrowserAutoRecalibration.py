"""Read-only browser layout state comparison for automatic recalibration.

The module contains no mouse or keyboard input.  It compares client-relative
canvas/palette geometry so a harmless window translation is not confused with
browser zoom/reflow, while DPI/client-size/layout changes are detected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
from CalibrationValidation import (screen_rect, screen_point, contained_rect,
                                   finite_confidence, nonnegative_integer)


@dataclass(frozen=True)
class BrowserLayoutState:
    client_size: tuple[int, int]
    dpi: int | None
    canvas_rel: tuple[int, int, int, int] | None
    palette_rel: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class BrowserLayoutDelta:
    changed: bool
    reasons: tuple[str, ...]
    max_palette_shift: int
    max_canvas_shift: int

    @property
    def reason(self) -> str:
        return ', '.join(self.reasons) if self.reasons else 'layout unchanged'


def _client(rect: Sequence[int]) -> tuple[int, int, int, int]:
    return screen_rect(rect, 'browser client rectangle')


def make_layout_state(client_rect: Sequence[int], dpi: int | None,
                      canvas_box: Sequence[int] | None,
                      palette_positions: Iterable[Sequence[int]] = ()) -> BrowserLayoutState:
    l, t, r, b = _client(client_rect)
    canvas_rel = None
    if canvas_box is not None:
        cl, ct, cr, cb = contained_rect(canvas_box, (l,t,r,b), 'browser canvas')
        canvas_rel = (cl-l, ct-t, cr-l, cb-t)
    palette_rel = tuple((x-l, y-t) for x,y in (screen_point(p) for p in palette_positions))
    if any(not (0 <= x < r-l and 0 <= y < b-t) for x,y in palette_rel):
        raise ValueError('Palette position is outside the browser client.')
    if dpi is not None:
        dpi = nonnegative_integer(dpi, 'DPI', maximum=10000)
        if dpi == 0: raise ValueError('DPI must be positive.')
    return BrowserLayoutState(
        client_size=(r-l, b-t),
        dpi=(int(dpi) if dpi is not None else None),
        canvas_rel=canvas_rel,
        palette_rel=palette_rel,
    )


def compare_layout_states(old: BrowserLayoutState | None, new: BrowserLayoutState,
                          *, tolerance_px: int = 4) -> BrowserLayoutDelta:
    if old is None:
        return BrowserLayoutDelta(True, ('initial browser calibration',), 0, 0)
    tolerance = nonnegative_integer(tolerance_px, 'Layout tolerance')
    reasons: list[str] = []
    if old.client_size != new.client_size:
        reasons.append(f'client resize {old.client_size[0]}×{old.client_size[1]}→{new.client_size[0]}×{new.client_size[1]}')
    if old.dpi is not None and new.dpi is not None and old.dpi != new.dpi:
        reasons.append(f'DPI {old.dpi}→{new.dpi}')

    canvas_shift = 0
    if old.canvas_rel is None or new.canvas_rel is None:
        if old.canvas_rel != new.canvas_rel:
            reasons.append('canvas detection changed')
    else:
        canvas_shift = max(abs(a-b) for a, b in zip(old.canvas_rel, new.canvas_rel))
        if canvas_shift > tolerance:
            reasons.append(f'canvas reflow/zoom {canvas_shift}px')

    palette_shift = 0
    if len(old.palette_rel) != len(new.palette_rel):
        reasons.append(f'palette count {len(old.palette_rel)}→{len(new.palette_rel)}')
    elif old.palette_rel:
        palette_shift = max(
            max(abs(ox-nx), abs(oy-ny))
            for (ox, oy), (nx, ny) in zip(old.palette_rel, new.palette_rel)
        )
        if palette_shift > tolerance:
            reasons.append(f'palette reflow/zoom {palette_shift}px')

    return BrowserLayoutDelta(bool(reasons), tuple(reasons), palette_shift, canvas_shift)


@dataclass(frozen=True)
class RecalibrationPlan:
    action: str
    reason: str
    confidence: float
    safe_to_reuse_palette: bool
    safe_to_reuse_canvas: bool
    retry_delay_seconds: float = 0.0

    def as_dict(self):
        return {
            "action": self.action,
            "reason": self.reason,
            "confidence": round(float(self.confidence), 4),
            "safe_to_reuse_palette": bool(self.safe_to_reuse_palette),
            "safe_to_reuse_canvas": bool(self.safe_to_reuse_canvas),
            "retry_delay_seconds": round(float(self.retry_delay_seconds), 4),
        }


def adaptive_retry_delay(attempt: int, confidence: float | None = None) -> float:
    """Small bounded settle delay for a read-only re-scan; never an input delay."""
    n = nonnegative_integer(attempt, 'Retry attempt')
    confidence = finite_confidence(confidence, default=.68 if confidence is None else 0.0)
    deficit = max(0.0, min(1.0, .82 - confidence))
    return round(min(.45, .09 + n * .09 + deficit * .32), 3)


def plan_recalibration(delta: BrowserLayoutDelta | None, *, palette_confidence: float = 1.0,
                       canvas_confidence: float = 1.0, attempt: int = 0) -> RecalibrationPlan:
    pc = finite_confidence(palette_confidence)
    cc = finite_confidence(canvas_confidence)
    reasons = tuple(getattr(delta, "reasons", ()) or ()) if delta is not None else ()
    text = " ".join(reasons).lower()
    # The comparison already applies its tolerance. Raw sub-tolerance shifts
    # are diagnostic values, not a reason to repeatedly rescan a stable page.
    changed = bool(getattr(delta, 'changed', False))
    canvas_changed = changed and ("canvas " in text or (not reasons and getattr(delta, 'max_canvas_shift', 0) > 0))
    palette_changed = changed and ("palette " in text or (not reasons and getattr(delta, 'max_palette_shift', 0) > 0))
    structural = "client resize" in text or "dpi " in text or "canvas detection changed" in text or "initial browser calibration" in text
    low_palette = pc < .70
    low_canvas = cc < .68
    if structural or (canvas_changed and palette_changed) or (low_palette and low_canvas):
        action = "full"
        reason = ", ".join(reasons) or "palette and canvas confidence are both low"
    elif canvas_changed or low_canvas:
        action = "canvas-only"
        reason = ", ".join(reasons) or f"canvas confidence {cc:.2f}"
    elif palette_changed or low_palette:
        action = "palette-only"
        reason = ", ".join(reasons) or f"palette confidence {pc:.2f}"
    else:
        action = "none"
        reason = "layout and calibration confidence are stable"
    confidence = max(0.0, min(1.0, .52 * pc + .48 * cc))
    delay = adaptive_retry_delay(attempt, min(pc, cc)) if action != "none" else 0.0
    return RecalibrationPlan(
        action, reason, confidence,
        safe_to_reuse_palette=(action in ("none", "canvas-only") and pc >= .70),
        safe_to_reuse_canvas=(action in ("none", "palette-only") and cc >= .68),
        retry_delay_seconds=delay,
    )


def evaluate_cached_canvas(cached_box, detected_box, canvas_confidence: float, *,
                           tolerance_px: int = 4, max_partial_shift_px: int = 28) -> RecalibrationPlan:
    """Decide whether a verified cached palette can survive a canvas-only drift."""
    try:
        old = screen_rect(cached_box, 'cached canvas')
        new = screen_rect(detected_box, 'detected canvas')
    except Exception:
        delta = BrowserLayoutDelta(True, ("canvas detection changed",), 0, 999)
        return plan_recalibration(delta, palette_confidence=1.0, canvas_confidence=canvas_confidence)
    shift = max(abs(a - b) for a, b in zip(old, new))
    tolerance_px = nonnegative_integer(tolerance_px, 'Canvas tolerance')
    max_partial_shift_px = nonnegative_integer(max_partial_shift_px, 'Partial canvas shift')
    conf = finite_confidence(canvas_confidence)
    if conf < .68:
        return RecalibrationPlan(
            "full", f"canvas confidence {conf:.2f}", .5 * (1.0 + conf), True, False,
            adaptive_retry_delay(0, conf),
        )
    if shift <= max(0, int(tolerance_px)):
        return RecalibrationPlan("none", "cached canvas matches live detection", .5 * (1.0 + conf), True, True, 0.0)
    if shift <= max(int(tolerance_px) + 1, int(max_partial_shift_px)):
        delta = BrowserLayoutDelta(True, (f"canvas drift {shift}px",), 0, shift)
        return plan_recalibration(delta, palette_confidence=1.0, canvas_confidence=conf)
    return RecalibrationPlan(
        "full", f"large canvas reflow {shift}px", .5 * (1.0 + conf), True, False,
        adaptive_retry_delay(0, conf),
    )


def _confidence_from_error(error: BaseException) -> float | None:
    import re
    match = re.search(r"(\d{1,3})%", str(error or ""))
    if not match:
        return None
    return max(0.0, min(1.0, int(match.group(1)) / 100.0))


def calibrate_browser_with_retry(profile_key, target_metadata, palette_path, *, screenshot=None,
                                 recapture=None, max_attempts: int = 3, cancelled=lambda: False,
                                 sleep_fn=None):
    """Retry only transient read-only visual confidence failures.

    Geometry/DPI/safety errors are never retried here; callers must refresh target
    metadata instead. Successful calibration is still produced by the existing
    BrowserAutoCalibration implementation.
    """
    import time
    from BrowserAutoCalibration import auto_calibrate_browser
    if sleep_fn is None:
        def sleep_fn(delay):
            end=time.monotonic()+delay
            while True:
                if cancelled():raise InterruptedError('Browser recalibration cancelled.')
                remaining=end-time.monotonic()
                if remaining<=0:return
                time.sleep(min(.05,remaining))
    attempts = max(1, min(3, nonnegative_integer(max_attempts, 'Retry count')))
    current = screenshot
    errors = []
    delays = []
    transient = (
        "confidence is too low",
        "verified colors",
        "palette grid could not be verified",
        "show the whole palette",
    )
    try:
        for attempt in range(attempts):
            if cancelled():
                raise InterruptedError("Browser recalibration cancelled.")
            try:
                result = auto_calibrate_browser(profile_key, target_metadata, palette_path, screenshot=current,
                                                cancelled=cancelled)
                if cancelled():
                    raise InterruptedError("Browser recalibration cancelled.")
                return result, {
                    "attempts": attempt + 1,
                    "retries": attempt,
                    "errors": tuple(errors),
                    "delays": tuple(delays),
                }
            except ValueError as error:
                message = str(error).lower()
                errors.append(str(error))
                if attempt + 1 >= attempts or not any(token in message for token in transient):
                    raise
                delay = adaptive_retry_delay(attempt, _confidence_from_error(error))
                delays.append(delay)
                sleep_fn(delay)
                if cancelled():
                    raise InterruptedError("Browser recalibration cancelled.")
                if recapture is not None:
                    fresh=recapture()
                    if current is not None and current is not screenshot and current is not fresh:current.close()
                    current=fresh
        raise RuntimeError("Browser recalibration retry loop exhausted unexpectedly.")

    finally:
        if current is not None and current is not screenshot:
            current.close()
