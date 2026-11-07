"""Keep the latest display updates without dropping commands or worker results.

Only adjacent runs of display notifications may be combined. Every other event
is an ordering barrier, including input commands, results, failures and done.
Queue's lock protects both producers and the GUI consumer; producers never wait
for Tk to render an obsolete intermediate value.
"""
from collections import OrderedDict, deque
from queue import Queue


DISPLAY_EVENTS = frozenset({
    'status', 'progress', 'draw_timer', 'deadline_telemetry', 'update_progress',
})


class _DisplayBatch(OrderedDict):
    """One bounded run of replaceable display values, in last-update order."""


class WorkerEventQueue(Queue):
    def __init__(self):
        # Lossless result/command events deliberately have no capacity limit.
        # Queue's standard get/put/task_done/join/timeout behavior is retained.
        super().__init__(maxsize=0)

    def _init(self, maxsize):
        self.queue = deque()
        self._pending_events = 0

    def _qsize(self):
        return self._pending_events

    def _put(self, item):
        kind = item[0] if isinstance(item, tuple) and len(item) == 2 else None
        if isinstance(kind, str) and kind in DISPLAY_EVENTS:
            if self.queue and isinstance(self.queue[-1], _DisplayBatch):
                batch = self.queue[-1]
            else:
                batch = _DisplayBatch()
                self.queue.append(batch)
            if kind in batch:
                del batch[kind]
                # Queue.put adds one task after _put returns. Replacing one
                # pending notification cancels its old task at the same time.
                self.unfinished_tasks -= 1
            else:
                self._pending_events += 1
            batch[kind] = item
        else:
            self.queue.append(item)
            self._pending_events += 1

    def _get(self):
        first = self.queue[0]
        if isinstance(first, _DisplayBatch):
            _, item = first.popitem(last=False)
            if not first:
                self.queue.popleft()
        else:
            item = self.queue.popleft()
        self._pending_events -= 1
        return item
