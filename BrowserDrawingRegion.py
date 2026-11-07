"""Keep an explicit drawing region inside a separately verified browser canvas."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from numbers import Integral, Real

from CalibrationValidation import contained_rect, screen_rect


UNVERIFIED_REGION_MESSAGE = (
    'The selected drawing region is not verified. Show the complete drawing '
    'canvas, then run Auto setup browser.'
)


def _context(profile_key, metadata):
    if not isinstance(profile_key, str) or not profile_key:
        raise ValueError('Select the drawing area again for the current profile.')
    handle = metadata.get('handle')
    if isinstance(handle, bool) or not isinstance(handle, Integral) or handle <= 0:
        raise ValueError('Select the drawing area again to identify its browser window.')
    client = screen_rect(metadata.get('client_rect'), 'browser client rectangle')
    dpi = metadata.get('dpi')
    if dpi is not None:
        if isinstance(dpi, bool) or not isinstance(dpi, Real) or not isfinite(float(dpi)) or dpi <= 0:
            raise ValueError('Select the drawing area again to verify the browser DPI.')
        dpi = float(dpi)
    return profile_key, int(handle), client, dpi


def _relative(box, client):
    return (box[0] - client[0], box[1] - client[1],
            box[2] - client[0], box[3] - client[1])


def _absolute(box, client):
    return (box[0] + client[0], box[1] + client[1],
            box[2] + client[0], box[3] + client[1])


@dataclass(frozen=True)
class BrowserDrawingRegion:
    """One explicit selection, never a recovered or inferred drawing permission.

    Relative integer coordinates permit a same-size window translation only.
    The first verified canvas is retained as the layout reference; subsequent
    detections cannot accumulate tolerated edge jitter into a layout change.
    This object holds geometry, not permission to send native input.
    """
    profile_key: str
    handle: int
    client_size: tuple[int, int]
    dpi: float | None
    selected: tuple[int, int, int, int]
    layout_canvas: tuple[int, int, int, int] | None = None
    verified_canvas: tuple[int, int, int, int] | None = None

    @classmethod
    def capture(cls, profile_key, metadata, selected):
        profile_key, handle, client, dpi = _context(profile_key, metadata)
        selected = contained_rect(selected, client, 'Selected drawing region', min_side=10)
        return cls(profile_key, handle, (client[2] - client[0], client[3] - client[1]),
                   dpi, _relative(selected, client))

    def _client(self, profile_key, metadata):
        profile_key, handle, client, dpi = _context(profile_key, metadata)
        if profile_key != self.profile_key or handle != self.handle:
            raise ValueError('The selected drawing region belongs to another profile or window. '
                             'Select the drawing area again.')
        if (client[2] - client[0], client[3] - client[1]) != self.client_size:
            raise ValueError('The browser client changed size after region selection. '
                             'Select the drawing area again; the region was not resized.')
        if dpi != self.dpi:
            raise ValueError('The browser DPI changed after region selection. '
                             'Select the drawing area again; the region was not scaled.')
        return client

    def drawing_box(self, profile_key, metadata):
        client = self._client(profile_key, metadata)
        return contained_rect(_absolute(self.selected, client), client, 'Selected drawing region', min_side=10)

    def require_current(self, profile_key, metadata, corners, *, verified=False):
        box = self.drawing_box(profile_key, metadata)
        if (not isinstance(corners, (list, tuple)) or len(corners) != 2 or
                tuple(corners[0]) != box[:2] or tuple(corners[1]) != box[2:]):
            raise ValueError('The selected drawing region changed. Select the drawing area again.')
        if verified and self.verified_canvas is None:
            raise ValueError(UNVERIFIED_REGION_MESSAGE)
        return box

    def with_canvas(self, profile_key, metadata, canvas):
        client = self._client(profile_key, metadata)
        canvas = contained_rect(canvas, client, 'Verified browser canvas', min_side=10)
        relative = _relative(canvas, client)
        if self.layout_canvas is not None and max(
                abs(a - b) for a, b in zip(relative, self.layout_canvas)) > 4:
            raise ValueError('The browser canvas layout changed after region selection. '
                             'Select the drawing area again; the region was not enlarged.')
        box = self.drawing_box(profile_key, metadata)
        try:
            contained_rect(box, canvas, 'Selected drawing region', min_side=10)
        except ValueError as error:
            raise ValueError('The selected drawing region is not fully inside the verified canvas. '
                             'Select the drawing area again.') from error
        return replace(self, layout_canvas=self.layout_canvas or relative, verified_canvas=relative)

    def without_verification(self):
        return replace(self, verified_canvas=None)

    def expected_canvas(self, profile_key, metadata):
        client = self._client(profile_key, metadata)
        if self.verified_canvas is None:
            raise ValueError(UNVERIFIED_REGION_MESSAGE)
        return _absolute(self.verified_canvas, client)
