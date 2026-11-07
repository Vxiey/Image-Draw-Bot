"""Release stability and crash/freeze hardening helpers for Image Draw Bot Step 18.

The helpers are deliberately pure/small so they can be unit-tested without a GUI,
mouse hook or Windows-only APIs. DrawBot uses them to keep preview planning
bounded and cancellable; tests use them to stress cancellation, event coalescing
and memory-limit decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Any, Callable
import math
import time

from RuntimePaths import is_finite_number


@dataclass(frozen=True)
class PreviewLimitResult:
    requested_pixels: int
    requested_dimension: int
    resolved_pixels: int
    resolved_dimension: int
    memory_budget_mb: float
    estimated_working_set_mb: float
    reduced: bool
    reason: str

    def as_options_meta(self) -> dict[str, Any]:
        return {
            "requested_pixels": self.requested_pixels,
            "requested_dimension": self.requested_dimension,
            "resolved_pixels": self.resolved_pixels,
            "resolved_dimension": self.resolved_dimension,
            "memory_budget_mb": round(float(self.memory_budget_mb), 3),
            "estimated_working_set_mb": round(float(self.estimated_working_set_mb), 3),
            "reduced": bool(self.reduced),
            "reason": self.reason,
        }


def _finite(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def estimate_preview_working_set_mb(pixel_count: int, *, layers: int = 14, bytes_per_channel: int = 4,
                                    overhead_mb: float = 96.0) -> float:
    """Conservative preview array estimate for RGB/OKLab/edge/error buffers."""
    px = max(1, int(pixel_count))
    layers = max(1, int(layers))
    bytes_per_channel = max(1, int(bytes_per_channel))
    return float(overhead_mb) + (px * layers * bytes_per_channel) / (1024.0 * 1024.0)


def apply_preview_memory_limits(requested_pixels: int, requested_dimension: int, *,
                                memory_budget_mb: float | None = None,
                                min_pixels: int = 120_000,
                                min_dimension: int = 420,
                                safety_ratio: float = 0.62) -> PreviewLimitResult:
    """Return safe preview limits under the available RAM budget.

    This does not touch final rendering resolution. It only prevents diagnostic
    preview planning from allocating many full-resolution OKLab/heatmap buffers.
    """
    for value in (requested_pixels, requested_dimension, min_pixels, min_dimension):
        if type(value) is not int or not 1 <= value <= 1_000_000_000:
            raise ValueError('Preview dimensions and pixel limits must be positive bounded integers.')
    req_px, req_dim = requested_pixels, requested_dimension
    budget = 768.0 if memory_budget_mb is None else memory_budget_mb
    if not is_finite_number(budget) or budget <= 0:
        raise ValueError('Preview memory budget must be a finite positive number.')
    if not is_finite_number(safety_ratio) or not 0 < safety_ratio <= 1:
        raise ValueError('Preview memory safety ratio must be between zero and one.')
    budget = float(budget)
    target_mb = budget * max(0.20, min(0.90, float(safety_ratio)))
    if target_mb < estimate_preview_working_set_mb(1):
        raise ValueError('Available preview memory is below the minimum working set. Increase the RAM budget or close other applications.')
    estimate = estimate_preview_working_set_mb(req_px)
    if estimate <= target_mb:
        return PreviewLimitResult(req_px, req_dim, req_px, req_dim, budget, estimate, False, "within budget")
    # Pixel/dimension preferences cannot override the caller's hard RAM limit
    # or enlarge the preview dimensions it requested.
    usable_for_arrays = (target_mb - 96.0) * 1024.0 * 1024.0
    resolved_px = max(1, min(req_px, int(usable_for_arrays / (14 * 4))))
    scale = math.sqrt(resolved_px / max(1.0, float(req_px)))
    resolved_dim = min(req_dim, max(min(min_dimension, req_dim), round(req_dim * scale)))
    new_estimate = estimate_preview_working_set_mb(resolved_px)
    return PreviewLimitResult(req_px, req_dim, resolved_px, resolved_dim, budget, new_estimate, True, "preview memory limit applied")


@dataclass
class PreviewAttemptGuard:
    """Deadline-aware cancellation helper for preview planning attempts."""
    timeout_seconds: float
    external_cancelled: Callable[[], bool] = lambda: False
    label: str = "preview"
    clock: Callable[[], float] = time.monotonic
    started: float | None = None
    checks: int = 0
    timed_out: bool = False
    cancelled_by_user: bool = False

    def __post_init__(self) -> None:
        if not is_finite_number(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError('Preview timeout must be finite and positive.')
        self.timeout_seconds = max(0.05, float(self.timeout_seconds))
        if self.started is None:
            self.started = self.clock()
        if not is_finite_number(self.started):
            raise ValueError('Preview start time must be finite.')
        self.deadline = float(self.started) + self.timeout_seconds
        if not math.isfinite(self.deadline):
            raise ValueError('Preview deadline is outside the supported range.')

    def remaining_seconds(self) -> float:
        if self.timed_out or self.cancelled_by_user:
            return 0.0
        return max(0.0, self.deadline - float(self.clock()))

    def cancelled(self) -> bool:
        self.checks += 1
        if self.cancelled_by_user or self.timed_out:
            return True
        if bool(self.external_cancelled()):
            self.cancelled_by_user = True
            return True
        if float(self.clock()) >= self.deadline:
            self.timed_out = True
            return True
        return False

    def raise_if_cancelled(self) -> None:
        if self.cancelled():
            if self.cancelled_by_user:
                raise InterruptedError(f"{self.label} cancelled.")
            raise InterruptedError(f"{self.label} timed out after {self.timeout_seconds:.1f}s.")

    def meta(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "timeout_seconds": round(float(self.timeout_seconds), 3),
            "remaining_seconds": round(float(self.remaining_seconds()), 3),
            "checks": int(self.checks),
            "timed_out": bool(self.timed_out),
            "cancelled_by_user": bool(self.cancelled_by_user),
        }


class EventCoalescer:
    """Bound a UI/event queue by coalescing noisy event kinds.

    It is a pure container; DrawBot can use the same policy before posting to Tk.
    The most recent status/progress/preview event wins while important events are
    kept in order up to a hard maximum.
    """

    def __init__(self, *, max_events: int = 256, coalesce_kinds: set[str] | None = None):
        self.max_events = max(4, int(max_events))
        self.coalesce_kinds = set(coalesce_kinds or {"status", "progress", "deadline_telemetry", "preview_render"})
        self._events: deque[tuple[str, Any]] = deque()
        self.dropped = 0
        self.coalesced = 0

    def push(self, kind: str, value: Any = None) -> None:
        kind = str(kind)
        if kind in self.coalesce_kinds:
            for i in range(len(self._events) - 1, -1, -1):
                if self._events[i][0] == kind:
                    self._events[i] = (kind, value)
                    self.coalesced += 1
                    return
        self._events.append((kind, value))
        while len(self._events) > self.max_events:
            self._events.popleft()
            self.dropped += 1

    def drain(self) -> list[tuple[str, Any]]:
        out = list(self._events)
        self._events.clear()
        return out

    def stats(self) -> dict[str, int]:
        return {"queued": len(self._events), "dropped": self.dropped, "coalesced": self.coalesced, "max_events": self.max_events}


class ProgressThrottle:
    """Limit high-frequency status/progress updates to avoid Tk event storms."""

    def __init__(self, *, min_interval_seconds: float = 0.08, min_delta_percent: float = 0.35,
                 clock: Callable[[], float] = time.monotonic):
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.min_delta_percent = max(0.0, float(min_delta_percent))
        self.clock = clock
        self._last_time: float | None = None
        self._last_percent: float | None = None

    def should_emit(self, done: int, total: int) -> bool:
        if total <= 0:
            return True
        now = float(self.clock())
        pct = max(0.0, min(100.0, float(done) * 100.0 / float(total)))
        if self._last_time is None or self._last_percent is None:
            self._last_time = now
            self._last_percent = pct
            return True
        if pct >= 100.0:
            self._last_time = now
            self._last_percent = pct
            return True
        if (now - self._last_time) >= self.min_interval_seconds and abs(pct - self._last_percent) >= self.min_delta_percent:
            self._last_time = now
            self._last_percent = pct
            return True
        return False


def classify_preview_timeout(elapsed_seconds: float, *, timeout_seconds: float, fallback_used: bool = False) -> dict[str, Any]:
    elapsed = max(0.0, _finite(elapsed_seconds, 0.0))
    timeout = max(0.05, _finite(timeout_seconds, 1.0))
    ratio = elapsed / timeout
    if ratio >= 1.0 and fallback_used:
        action = "retain previous preview; final Start can still make full plan"
        state = "fallback-timeout"
    elif ratio >= 1.0:
        action = "retry fast fallback"
        state = "primary-timeout"
    elif ratio >= 0.85:
        action = "warn slow preview"
        state = "near-timeout"
    else:
        action = "ok"
        state = "ok"
    return {"state": state, "elapsed_seconds": round(elapsed, 3), "timeout_seconds": round(timeout, 3), "ratio": round(ratio, 3), "fallback_used": bool(fallback_used), "recommended_action": action}


def merge_stability_meta(options: dict[str, Any], **items: Any) -> dict[str, Any]:
    """Attach bounded Step 18 metadata to an options dictionary."""
    opts = options if isinstance(options, dict) else {}
    meta = opts.get("release_stability_meta") if isinstance(opts.get("release_stability_meta"), dict) else {}
    meta = dict(meta)
    for key, value in items.items():
        if value is not None:
            meta[key] = value
    meta.setdefault("version", 1)
    meta.setdefault("local_only", True)
    meta.setdefault("mouse_input", False)
    meta.setdefault("stores_image_data", False)
    opts["release_stability_meta"] = meta
    return meta
