"""One owned recovery raster at a time; encode before the publication lock.

The controller captures a private source copy on Tk and coalesces later saves.
This worker never reads Tk, publishes a checkpoint, or closes the source image.
The small final state/image publication remains a controller operation.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import threading
import weakref


def _check(cancelled):
    if cancelled():
        raise InterruptedError('Recovery image preparation cancelled.')


def _close_preserving(resource, failure=None):
    try:
        resource.close()
    except BaseException as cleanup_error:
        if failure is None:
            return cleanup_error
        failure.add_note(f'Recovery resource cleanup also failed: {type(cleanup_error).__name__}.')
    return failure


@dataclass
class PreparedImage:
    directory: tempfile.TemporaryDirectory
    path: Path
    digest: str

    def close(self):
        self.directory.cleanup()


class _CancellableWriter:
    def __init__(self, stream, cancelled, limit):
        self.stream = stream
        self.cancelled = cancelled
        self.limit = limit

    def write(self, value):
        _check(self.cancelled)
        if self.stream.tell() + len(value) > self.limit:
            raise ValueError('Cached image is too large.')
        return self.stream.write(value)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def prepare_image(image, *, cancelled=lambda: False):
    """Encode and hash a private PNG without holding the checkpoint guard."""
    import SessionRecovery as recovery
    _check(cancelled)
    if image.width < 1 or image.height < 1 or image.width * image.height > recovery.MAX_CACHED_IMAGE_PIXELS:
        raise ValueError('Recovery image exceeds the supported pixel limit.')
    recovery.RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    # Normal checkpoint pruning only touches its own flat final/staging files.
    # Explicit cache clearing waits for this worker before removing job dirs.
    directory = tempfile.TemporaryDirectory(prefix='.recovery-pending-', dir=recovery.RECOVERY_DIR)
    path = Path(directory.name) / 'image.png'
    try:
        with path.open('wb') as stream:
            writer = _CancellableWriter(stream, cancelled, recovery.MAX_CACHED_IMAGE_BYTES)
            if image.mode == 'RGBA':
                image.save(writer, format='PNG')
            else:
                rgba = image.convert('RGBA')
                try:
                    rgba.save(writer, format='PNG')
                except BaseException as failure:
                    _close_preserving(rgba, failure)
                    raise
                else:
                    rgba.close()
            _check(cancelled)
            stream.flush()
            os.fsync(stream.fileno())
        _check(cancelled)
        with path.open('rb') as stream:
            digest = recovery._stream_digest(stream, cancelled=cancelled)
        _check(cancelled)
        return PreparedImage(directory, path, digest)
    except BaseException as failure:
        try:
            directory.cleanup()
        except OSError as cleanup_error:
            failure.add_note(f'Recovery staging cleanup also failed: {type(cleanup_error).__name__}.')
        raise


class RecoveryImageJob:
    """A private copy, one encoder thread and one explicitly owned result."""
    def __init__(self, source, notify):
        from SessionRecovery import MAX_CACHED_IMAGE_PIXELS
        if source.width < 1 or source.height < 1 or source.width * source.height > MAX_CACHED_IMAGE_PIXELS:
            raise ValueError('Recovery image exceeds the supported pixel limit.')
        self.source = weakref.ref(source)
        self._snapshot = source.copy()
        self._notify = notify
        self._cancelled = threading.Event()
        self._idle = threading.Event()
        self._lock = threading.Lock()
        self._result = None
        self._error = None
        self._thread = None

    def start(self):
        try:
            thread = threading.Thread(target=self._run, name='recovery-image-encoder', daemon=True)
            self._thread = thread
            thread.start()
        except BaseException as failure:
            _close_preserving(self._snapshot, failure)
            self._snapshot = None
            self._idle.set()
            raise

    def is_alive(self):
        return not self._idle.is_set()

    def wait_idle(self, timeout):
        """A bounded wait for worker/test callers; never block the Tk thread."""
        return self._idle.wait(timeout)

    def take(self):
        with self._lock:
            result, error = self._result, self._error
            self._result = self._error = None
            return result, error

    def cancel(self):
        self._cancelled.set()
        result, _error = self.take()
        if result is not None:
            result.close()

    def _run(self):
        result = error = None
        try:
            result = prepare_image(self._snapshot, cancelled=self._cancelled.is_set)
        except BaseException as failure:
            error = failure
        finally:
            error = _close_preserving(self._snapshot, error)
            self._snapshot = None
        if error is not None and result is not None:
            error = _close_preserving(result, error)
            result = None
        with self._lock:
            cancelled = self._cancelled.is_set()
            if not cancelled:
                self._result, self._error = result, error
        try:
            if cancelled and result is not None:
                error = _close_preserving(result, error)
            if cancelled and error is not None:
                with self._lock:
                    self._error = error
        finally:
            self._idle.set()
            try:
                self._notify(self)
            except BaseException:
                self.cancel()
