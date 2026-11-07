"""One bounded, Tk-free address lookup and one replaceable next intention.

OS hostname resolution is not interruptible. Cancellation retires its result
without joining that thread or starting another resolver beside it. The GUI
polls the plain mailbox; no Tk object, callback, image or server reaches it.
"""
import threading


class MobilePreviewDiscovery:
    def __init__(self, resolve=None):
        if resolve is None:
            from MobilePreview import local_ipv4_addresses
            resolve = local_ipv4_addresses
        self._resolve = resolve
        self._lock = threading.Lock()
        self._retired = False
        self._current = self._pending = self._outcome = None
        self.thread = None

    def submit(self, ticket):
        """Replace the pending intent; an older live resolver still owns its slot."""
        with self._lock:
            if self._retired:
                raise RuntimeError('Mobile Preview discovery is closed.')
            if self._current is not None:
                self._current.set()
            self._current = self._pending = ticket
            self._outcome = None
            self._start_pending()

    def _start_pending(self):
        """Called under the lock; a finished thread must really have exited."""
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = None
        ticket, self._pending = self._pending, None
        if ticket is None or ticket.is_set() or self._retired:
            return
        try:
            self.thread = threading.Thread(target=self._run, args=(ticket,),
                name='mobile-preview-discovery', daemon=True)
            self.thread.start()
        except BaseException as error:
            self.thread = None
            self._outcome = (ticket, 'error', f'{type(error).__name__}: {error}')

    def take(self):
        with self._lock:
            if self.thread is not None and self.thread.is_alive():
                return None
            self.thread = None
            self._start_pending()
            outcome, self._outcome = self._outcome, None
            if (outcome is None or self._retired or outcome[0] is not self._current
                    or outcome[0].is_set()):
                return None
            self._current = None
            return outcome

    def cancel(self):
        """Thread-safe permanent request cancellation, with no GUI references."""
        with self._lock:
            if self._current is not None:
                self._current.set()
            self._current = self._pending = self._outcome = None

    def retire(self):
        with self._lock:
            self._retired = True
            if self._current is not None:
                self._current.set()
            self._current = self._pending = self._outcome = None
            self._resolve = None

    def _run(self, ticket):
        outcome = values = resolve = None
        try:
            with self._lock:
                resolve = self._resolve
            if ticket.is_set() or resolve is None:
                return
            values = tuple(resolve())
            if not ticket.is_set():
                outcome = (ticket, 'result', values)
        except BaseException as error:
            # Do not retain the resolver traceback or its local/native owners.
            outcome = (ticket, 'error', f'{type(error).__name__}: {error}')
        finally:
            with self._lock:
                if not self._retired and self._current is ticket and not ticket.is_set():
                    self._outcome = outcome
            outcome = values = resolve = None
