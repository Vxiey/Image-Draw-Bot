"""Share a final drawing plan between its worker and the queued UI result."""
from threading import RLock


class WorkerPlanPublication:
    """Release rejected images only after the executor has stopped using them.

    The publication remains outside the serializable plan. UI adoption takes
    over image ownership; a queued, undecided result remains alive even when
    the worker finishes before Tk processes it. The release callback must not
    access Tk because either the UI or worker can become the last consumer.
    """

    def __init__(self, release):
        self._lock = RLock()
        self._release = release
        self._plan = None
        self._published = False
        self._adopted = False
        self._rejected = False
        self._finished = False
        self._closed = False

    def own(self, plan):
        with self._lock:
            if self._published or self._finished:
                raise RuntimeError('A published drawing plan cannot be replaced.')
            # Dry-run sampling returns a shallow plan with the same owned
            # images. Until publication, the worker can replace that wrapper.
            self._plan = plan

    def publish(self, events):
        with self._lock:
            if self._plan is None or self._published or self._finished:
                raise RuntimeError('The drawing plan is not ready for publication.')
            events.put(('planned', self._plan))
            self._published = True

    def owns(self, plan):
        with self._lock:
            return self._plan is not None and plan is self._plan

    def adopt(self, plan):
        with self._lock:
            if (plan is not self._plan or not self._published or
                    self._rejected or self._closed):
                return False
            self._adopted = True
            return True

    def reject(self, plan=None):
        with self._lock:
            if plan is not None and plan is not self._plan:
                return False
            self._rejected = True
            self._release_if_unowned()
            return True

    def finish(self):
        with self._lock:
            self._finished = True
            self._release_if_unowned()

    def _release_if_unowned(self):
        if (self._plan is not None and self._finished and not self._adopted and
                not self._closed and (self._rejected or not self._published)):
            self._closed = True
            self._release(self._plan)
