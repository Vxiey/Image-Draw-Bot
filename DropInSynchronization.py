"""One-shot Drop-In synchronization for browser auto setup/preflight.

The module contains no GUI, network, screenshot, or native input code.  It only
tracks whether a user-authorized image import may wait for read-only browser
setup work and whether the original target is still the same before drawing.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import time
import math
from typing import Any

IDLE = 'IDLE'
AUTO_SETUP_RUNNING = 'AUTO_SETUP_RUNNING'
AUTO_RECALIBRATING = 'AUTO_RECALIBRATING'
VISUAL_PREFLIGHT_RUNNING = 'VISUAL_PREFLIGHT_RUNNING'
READY_TO_DRAW = 'READY_TO_DRAW'
DRAW_PENDING = 'DRAW_PENDING'
DRAWING = 'DRAWING'

WAITABLE_STATES = frozenset({AUTO_SETUP_RUNNING, AUTO_RECALIBRATING, VISUAL_PREFLIGHT_RUNNING})
WAITABLE_ACTIVITIES = frozenset({'browser-auto-calibration'})
PENDING_TIMEOUT_SECONDS = 30.0


def _rect(value: Any) -> tuple[int, ...] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        return tuple(int(v) for v in value)
    except (TypeError, ValueError, OverflowError):
        return None


def target_fingerprint(profile_name: str, target_window=None, client_rect=None, dpi=None) -> tuple:
    handle = None
    outer = None
    if isinstance(target_window, (tuple, list)) and len(target_window) == 2:
        try:
            handle = int(target_window[0])
        except (TypeError, ValueError, OverflowError):
            handle = None
        outer = _rect(target_window[1])
    try:dpi_value=None if dpi is None else int(dpi)
    except (TypeError,ValueError,OverflowError):dpi_value=None
    if dpi_value is not None and dpi_value<=0:dpi_value=None
    return (str(profile_name or ''), handle, outer, _rect(client_rect), dpi_value)


@dataclass(frozen=True)
class PendingDropIn:
    source: Any
    label: str
    action: str
    fingerprint: tuple
    requested_at: float
    deadline: float
    sequence: int = 1

    @property
    def expired(self) -> bool:
        return request_expired(self)


def make_request(source, label: str, action: str, fingerprint: tuple, *, previous: PendingDropIn | None = None,
                 now: float | None = None, timeout_seconds: float = PENDING_TIMEOUT_SECONDS) -> PendingDropIn:
    now = time.monotonic() if now is None else float(now)
    timeout_seconds = float(timeout_seconds)
    if not math.isfinite(now) or not math.isfinite(timeout_seconds) or timeout_seconds<=0:
        raise ValueError('Drop-In authorization needs a finite positive lifetime and clock.')
    timeout_seconds = max(1.0, min(300.0,timeout_seconds))
    sequence = (int(previous.sequence) + 1) if previous is not None else 1
    return PendingDropIn(source, str(label), str(action), tuple(fingerprint), now, now + timeout_seconds, sequence)


def request_expired(request: PendingDropIn | None, *, now: float | None = None) -> bool:
    if request is None:
        return False
    now = time.monotonic() if now is None else float(now)
    try:deadline=float(request.deadline)
    except (TypeError,ValueError,OverflowError):return True
    return not math.isfinite(now) or not math.isfinite(deadline) or now >= deadline


def target_matches(request: PendingDropIn | None, fingerprint: tuple) -> bool:
    """Match target identity (profile + HWND), allowing safe geometry/DPI reflow."""
    if request is None:
        return False
    left=tuple(request.fingerprint);right=tuple(fingerprint)
    return (len(left)>=2 and len(right)>=2 and bool(left[0]) and
            type(left[1]) is int and left[1]>0 and type(right[1]) is int and
            left[:2]==right[:2])


def replace_fingerprint(request: PendingDropIn, fingerprint: tuple) -> PendingDropIn:
    return replace(request, fingerprint=tuple(fingerprint))


def should_wait(*, activity: str | None = None, phase: str | None = None) -> bool:
    return activity in WAITABLE_ACTIVITIES or phase in WAITABLE_STATES
