"""Small, deterministic UI transaction helpers for fragile desktop workflows.

The runtime intentionally does not own mouse/keyboard input.  Callers keep their
existing guarded input backend and use this module for explicit state,
bounded retries, adaptive settle delays and lightweight telemetry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Integral
import math
import time
from typing import Any, Callable

STATES = (
    "READY",
    "OPEN_DIALOG",
    "WRITE_VALUE",
    "VERIFY_VALUE",
    "COMMIT_VALUE",
    "VERIFY_COMMIT",
    "RECOVER",
    "DONE",
    "FAILED",
)
MAX_HISTORY = 512
MAX_DETAIL = 1024


@dataclass
class AdaptivePacer:
    """Conservative feedback pacer for UI automation.

    The delay grows only after a transient failure and decays after successful
    transactions.  This avoids flooding a temporarily slow XAML/WinUI dialog
    while keeping the fast path essentially unchanged.
    """

    base_delay: float = 0.025
    max_delay: float = 0.30
    growth: float = 1.8
    decay: float = 0.72
    current_delay: float = field(init=False)
    failures: int = 0

    def __post_init__(self) -> None:
        for name in ('base_delay','max_delay','growth','decay'):
            try:
                value=float(getattr(self,name))
            except (ValueError,TypeError,OverflowError) as error:
                raise ValueError(f'{name} must be a finite number.') from error
            if not math.isfinite(value):
                raise ValueError(f'{name} must be a finite number.')
            setattr(self,name,value)
        self.base_delay = max(0.0, float(self.base_delay))
        self.max_delay = max(self.base_delay, float(self.max_delay))
        self.growth = max(1.0, float(self.growth))
        self.decay = min(1.0, max(0.0, float(self.decay)))
        self.current_delay = self.base_delay

    def failed(self) -> float:
        self.failures += 1
        seed = self.current_delay if self.current_delay > 0 else max(self.base_delay, 0.01)
        self.current_delay = min(self.max_delay, max(self.base_delay, seed * self.growth))
        return self.current_delay

    def succeeded(self) -> float:
        self.failures = 0
        self.current_delay = max(self.base_delay, self.current_delay * self.decay)
        return self.current_delay


@dataclass(frozen=True)
class Transition:
    state: str
    attempt: int
    item_index: int
    detail: str
    monotonic: float


class UiTransaction:
    """State + retry coordinator; input remains entirely caller-owned."""

    def __init__(self, *, max_attempts: int = 3, pacer: AdaptivePacer | None = None,
                 cancelled: Callable[[], bool] = lambda: False,
                 wait: Callable[[float], Any] = time.sleep,
                 on_state: Callable[[Transition], Any] | None = None):
        if isinstance(max_attempts,bool) or not isinstance(max_attempts,Integral) or max_attempts<1:
            raise ValueError('UI retries must be a positive integer.')
        self.max_attempts = min(8,int(max_attempts))
        self.pacer = pacer or AdaptivePacer()
        self.cancelled = cancelled
        self.wait = wait
        self.on_state = on_state
        self.history: list[Transition] = []
        self.history_dropped = 0
        self.state = "READY"

    def check_cancelled(self, message: str = "UI transaction cancelled.") -> None:
        if self.cancelled():
            raise InterruptedError(message)

    def transition(self, state: str, *, attempt: int = 0, item_index: int = 0,
                   detail: str = "") -> Transition:
        if state not in STATES:
            raise ValueError(f"Unknown UI transaction state: {state}")
        if any(isinstance(v,bool) or not isinstance(v,Integral) or v<0 for v in (attempt,item_index)):
            raise ValueError('UI transition counters must be nonnegative integers.')
        text=str(detail)
        if len(text)>MAX_DETAIL:text=text[:MAX_DETAIL-1]+'…'
        event = Transition(state, int(attempt), int(item_index), text, time.monotonic())
        self.state = state
        self.history.append(event)
        if len(self.history)>MAX_HISTORY:
            del self.history[0]
            self.history_dropped+=1
        if self.on_state is not None:
            self.on_state(event)
        return event

    def _failed(self, error: Exception, *, attempt: int, item_index: int) -> None:
        # Telemetry must not replace the terminal operation/recovery exception.
        try:
            self.transition('FAILED',attempt=attempt,item_index=item_index,
                            detail=f'{type(error).__name__}: {error}')
        except Exception as observer_error:
            self.state='FAILED'
            error.add_note(f'Failure-state reporting also failed: {type(observer_error).__name__}.')

    def retry(self, operation: Callable[[int], Any], *, item_index: int = 0,
              retry_on: tuple[type[BaseException], ...] = (TimeoutError, ValueError),
              recover: Callable[[int, BaseException], Any] | None = None,
              cancel_message: str = "UI transaction cancelled.") -> Any:
        """Run ``operation`` with bounded retries and adaptive backoff.

        Only exceptions explicitly named in ``retry_on`` are retried.  The last
        exception is re-raised unchanged so callers preserve existing error
        classification and recovery behavior.
        """
        if isinstance(item_index,bool) or not isinstance(item_index,Integral) or item_index<0:
            raise ValueError('UI transaction item index must be a nonnegative integer.')
        item_index=int(item_index)
        for attempt in range(1, self.max_attempts + 1):
            self.check_cancelled(cancel_message)
            try:
                result = operation(attempt)
            except InterruptedError:
                # Cancellation is never a transient UI failure, including when
                # a caller explicitly chooses retry_on=(Exception,).
                raise
            except retry_on as exc:
                self.check_cancelled(cancel_message)
                if attempt >= self.max_attempts:
                    self._failed(exc,attempt=attempt,item_index=item_index)
                    raise
                try:
                    self.transition("RECOVER", attempt=attempt, item_index=item_index,
                                    detail=f"{type(exc).__name__}: {exc}")
                    if recover is not None:
                        self.check_cancelled(cancel_message)
                        recover(attempt, exc)
                    self.check_cancelled(cancel_message)
                    self.wait(self.pacer.failed())
                except InterruptedError:
                    raise
                except Exception as recovery_error:
                    self._failed(recovery_error,attempt=attempt,item_index=item_index)
                    raise
                continue
            except Exception as error:
                self._failed(error,attempt=attempt,item_index=item_index)
                raise
            self.check_cancelled(cancel_message)
            self.pacer.succeeded()
            return result
        raise RuntimeError("UI transaction retry loop exhausted unexpectedly.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "max_attempts": self.max_attempts,
            "adaptive_delay": round(float(self.pacer.current_delay), 6),
            "events_dropped": self.history_dropped,
            "events": [
                {
                    "state": e.state,
                    "attempt": e.attempt,
                    "item_index": e.item_index,
                    "detail": e.detail,
                    "monotonic": round(e.monotonic, 6),
                }
                for e in self.history
            ],
        }
