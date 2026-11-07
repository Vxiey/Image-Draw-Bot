"""Owned, bounded snapshots and a single latest-request mobile encoder.

Capture runs on the caller's image-owning thread. The encoder never reads a
borrowed PIL image, and superseded snapshots are explicitly closed. The byte
budget covers retained pixel cores, not Pillow/native resizing or PNG scratch
buffers. Native Pillow operations finish before cancellation is observed.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
import threading
import weakref


SNAPSHOT_BUDGET_BYTES = 32 * 1024 * 1024
VIEW_NAMES = ('original', 'preview', 'safety')


def image_identities(images):
    """Weak identities cannot keep old full-resolution caller images alive."""
    return {name: None if image is None else weakref.ref(image)
            for name, image in images.items()}


def same_images(identities, images):
    if identities is None or identities.keys() != images.keys():
        return False
    return all((image is None if identities[name] is None else image is not None and identities[name]() is image)
               for name, image in images.items())


def pixel_bytes(image):
    # Pillow RGB cores may use four bytes per pixel despite exposing 3 bands.
    return image.width * image.height * max(4, len(image.getbands()))


def _reduced_snapshot(image, maximum):
    """Match the existing mobile encoder's alpha/resampling order exactly."""
    from PIL import Image
    ratio = maximum / float(max(image.size))
    target = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    if image.mode in ('RGB', 'L') and 'transparency' not in image.info:
        # Conversion remains after opaque resizing, as in _image_png_bytes.
        with closing(image.resize(target, Image.Resampling.LANCZOS)) as reduced:
            return reduced.convert('RGBA')
    if image.mode == 'RGBA':
        # The source is read only. Avoid a full-size RGBA copy before reduction.
        return image.resize(target, Image.Resampling.LANCZOS)
    with closing(image.convert('RGBA')) as rgba:
        return rgba.resize(target, Image.Resampling.LANCZOS)


def capture_snapshots(images, *, maximum, current, budget=SNAPSHOT_BUDGET_BYTES):
    """Return owned snapshots, or None when superseded during capture.

    At most three mobile views are accepted. If their conservative combined
    footprint exceeds the budget, reduce large inputs to the existing mobile
    dimensions before retaining them. This may perform resize work on Tk; it
    deliberately avoids retaining a second full-size 25 MP RGBA source.
    """
    if any(name not in VIEW_NAMES for name in images):
        raise ValueError('Unknown mobile preview view.')
    unique = {id(image): image for image in images.values() if image is not None}
    reduce = sum(pixel_bytes(image) for image in unique.values()) > budget
    captured = {}
    complete = False
    try:
        for identity, source in unique.items():
            if not current():
                return None
            snapshot = (_reduced_snapshot(source, maximum)
                        if reduce and max(source.size) > maximum else source.copy())
            captured[identity] = snapshot
            if sum(pixel_bytes(value) for value in captured.values()) > budget:
                raise ValueError('Mobile preview snapshots exceed the pixel-memory budget.')
        if not current():
            return None
        result = {name: captured[id(image)] for name, image in images.items() if image is not None}
        complete = True
        return result
    finally:
        if not complete:
            for snapshot in captured.values():
                snapshot.close()


@dataclass
class ImageRequest:
    ticket: tuple[int, int]
    identities: dict
    snapshots: dict
    encoded: dict = field(default_factory=dict)

    @property
    def snapshot_bytes(self):
        return sum(pixel_bytes(image) for image in {id(value): value for value in self.snapshots.values()}.values())

    def close(self):
        owned = {id(value): value for value in self.snapshots.values()}
        self.snapshots.clear()
        for snapshot in owned.values():
            snapshot.close()


class LatestImageQueue:
    """One encoder plus one replaceable pending slot; no unbounded executor."""

    def __init__(self, *, encode, current, publish, failed):
        self._encode = encode
        self._current = current
        self._publish = publish
        self._failed = failed
        self.submission_lock = threading.Lock()
        self._lock = threading.Lock()
        self._pending = None
        self._active = None
        self._thread = None
        self._idle = threading.Event()
        self._idle.set()

    def discard_before(self, ticket):
        old = None
        with self._lock:
            if self._pending is not None and self._pending.ticket < ticket:
                old, self._pending = self._pending, None
        if old is not None:
            old.close()

    def submit(self, request):
        old = None
        try:
            with self._lock:
                old, self._pending = self._pending, request
                self._idle.clear()
                if self._thread is None:
                    try:
                        thread = threading.Thread(target=self._run, name='mobile-preview-encoder', daemon=True)
                        self._thread = thread
                        thread.start()
                    except BaseException:
                        self._thread = None
                        self._pending = None
                        self._idle.set()
                        raise
        except BaseException:
            request.close()
            raise
        finally:
            if old is not None:
                old.close()

    def _run(self):
        try:
            while True:
                with self._lock:
                    request, self._pending = self._pending, None
                    if request is None:
                        self._thread = None
                        self._idle.set()
                        return
                    self._active = request
                try:
                    encoded = dict(request.encoded)
                    encoded_snapshots = {}
                    for name, snapshot in request.snapshots.items():
                        if not self._current(request.ticket):
                            break
                        identity = id(snapshot)
                        if identity not in encoded_snapshots:
                            encoded_snapshots[identity] = self._encode(snapshot)
                        encoded[name] = encoded_snapshots[identity]
                    if self._current(request.ticket):
                        self._publish(request, encoded)
                except Exception as error:
                    self._failed(request.ticket, error)
                finally:
                    request.close()
                    with self._lock:
                        self._active = None
        finally:
            # Unexpected BaseException or an error callback must not leave a
            # dead worker registered, nor retain an abandoned pending snapshot.
            abandoned = None
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                    abandoned, self._pending = self._pending, None
                    self._idle.set()
            if abandoned is not None:
                abandoned.close()

    def wait_idle(self, timeout):
        """Bounded joining for tests/shutdown observers, never used from Tk."""
        return self._idle.wait(timeout)
