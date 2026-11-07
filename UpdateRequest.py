"""One user-triggered update's cancellation and handoff state; no Tk calls."""
from __future__ import annotations

import threading


class UpdateRequest:
    """A private cancellation flag survives reuse of the app's global Stop.

    Cancellation can be signalled from the keyboard thread. Phase transitions
    are short local operations; the lock is never held during I/O or launch.
    Only the real install worker may mark a successfully started process.
    """

    def __init__(self):
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._phase = 'checking'

    @property
    def phase(self):
        with self._lock:
            return self._phase

    def cancel(self):
        with self._lock:
            self._cancelled.set()

    def is_cancelled(self):
        return self._cancelled.is_set()

    def _advance(self, expected, following):
        with self._lock:
            if self._cancelled.is_set() or self._phase != expected:
                return False
            self._phase = following
            return True

    def ready(self):
        return self._advance('checking', 'ready')

    def finish_check(self):
        return self._advance('checking', 'finished')

    def begin_install(self):
        return self._advance('ready', 'installing')

    def mark_started(self):
        """Record an actual successful process start, even if Stop arrived then.

        The verified launcher checks cancellation immediately before launch.
        Once it returns successfully, a later Stop cannot undo that process;
        the app must still complete its existing close-for-update handoff.
        """
        with self._lock:
            if self._phase != 'installing':
                return False
            self._phase = 'started'
            return True

    def consume_started(self):
        with self._lock:
            if self._phase != 'started':
                return False
            self._phase = 'consumed'
            return True
