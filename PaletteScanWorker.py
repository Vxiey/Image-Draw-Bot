"""Own one cancellable palette analysis without retaining a Tk interpreter.

The worker sees a private Pillow image and plain settings only. Results remain
owned by its mailbox until the GUI takes them; retiring the mailbox closes a
queued or late result instead of posting a callback to a destroyed window.
"""
from dataclasses import dataclass
import threading


@dataclass
class PaletteScanResult:
    image: object
    preview: object
    values: dict

    def take_image(self):
        image, self.image = self.image, None
        return image

    def close(self):
        preview, self.preview = self.preview, None
        image, self.image = self.image, None
        try:
            if preview is not None:
                preview.close()
        finally:
            if image is not None:
                image.close()


class PaletteScanJob:
    """A single-producer mailbox with an explicit image-ownership handoff."""

    def __init__(self, image, operation, settings):
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._retired = False
        self._done = False
        self._outcome = None
        self._operation = operation
        self._settings = settings
        self.thread = None
        self._input = image

    @property
    def done(self):
        with self._lock:
            return self._done

    def start(self):
        try:
            self.thread = threading.Thread(target=self._run, name='palette-scan', daemon=True)
            self.thread.start()
        except BaseException:
            # A failed start still retires the input. If a thread already took
            # it under the lock, that thread alone closes it in its finally.
            self.retire()
            raise

    def take(self):
        with self._lock:
            outcome, self._outcome = self._outcome, None
            return outcome

    def retire(self):
        self._cancel.set()
        with self._lock:
            self._retired = True
            outcome, self._outcome = self._outcome, None
            image, self._input = self._input, None
        if image is not None:
            image.close()
        if outcome is not None and outcome[0] == 'result':
            outcome[1].close()

    def _publish(self, outcome):
        with self._lock:
            self._done = True
            keep = not self._retired
            if keep:
                self._outcome = outcome
        if not keep and outcome[0] == 'result':
            outcome[1].close()

    def _run(self):
        image = preview = result = values = None
        outcome = None
        with self._lock:
            image, self._input = self._input, None
        try:
            if image is None or self._cancel.is_set():
                raise InterruptedError('Palette scan cancelled.')
            values, preview = self._operation(image, self._settings, self._cancel.is_set)
            if self._cancel.is_set():
                raise InterruptedError('Palette scan cancelled.')
            result = PaletteScanResult(image, preview, values)
            outcome = ('result', result)
            image = preview = values = None
        except InterruptedError:
            outcome = ('cancelled', 'Palette scan cancelled.')
        except BaseException as error:
            # Do not transfer a traceback, callback or local buffer to Tk.
            outcome = ('error', f'{type(error).__name__}: {error}')
        finally:
            try:
                if preview is not None:
                    preview.close()
            finally:
                if image is not None:
                    image.close()
                image = preview = values = None
                self._operation = self._settings = None
        try:
            self._publish(outcome)
        finally:
            result = outcome = None
