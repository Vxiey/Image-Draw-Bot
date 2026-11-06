"""Reuse one desktop bitmap for an immutable accepted image and viewport.

App and plan images are replaced when their pixels change. This cache belongs
to that UI publication contract; the public viewport_image helper still reads
mutable caller images afresh. The source reference is weak, so an obsolete
plan/source cannot be retained merely by a displayed Tk bitmap.
"""
from contextlib import closing
from dataclasses import dataclass
import weakref

from PreviewQuality import viewport_geometry


@dataclass(frozen=True)
class _Bitmap:
    source: weakref.ReferenceType
    geometry: object
    mode: str
    photo: object


def clear_bitmap(canvas):
    canvas._preview_bitmap = None
    canvas._preview_photo = None


def photo_for(canvas, image, size, zoom, pan, *, make_photo):
    from PreviewQuality import viewport_image
    # Closing a source is a state change even though Pillow retains its size.
    # Do not let a previously displayed bitmap conceal a broken live owner.
    try:
        image.im
        geometry = viewport_geometry(image.size, size, zoom, pan)
    except BaseException:
        clear_bitmap(canvas)
        raise
    cached = getattr(canvas, '_preview_bitmap', None)
    if (isinstance(cached, _Bitmap) and cached.source() is image and
            cached.geometry == geometry and cached.mode == image.mode and
            getattr(canvas, '_preview_photo', None) is cached.photo):
        return cached.photo
    clear_bitmap(canvas)
    viewport, _ = viewport_image(image, size, zoom, pan)
    with closing(viewport):
        photo = make_photo(viewport)
    canvas._preview_bitmap = _Bitmap(weakref.ref(image), geometry, image.mode, photo)
    canvas._preview_photo = photo
    return photo
