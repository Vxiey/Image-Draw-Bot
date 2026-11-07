"""The shared categorical index contract for CPU and GPU pixel maps.

Pixel maps use signed 16-bit storage so that ``-1`` remains available for an
unpainted pixel.  Validate before casts or backend fallback: a backend error
must never turn an out-of-range colour into another colour through wrapping.
"""
from __future__ import annotations

from numbers import Integral


MAX_PALETTE_COUNT = 1 << 15


def validate_palette_count(value: object) -> int:
    """Return a nonempty palette size that fits the signed int16 index ABI."""
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError("Palette size must be an integer between 1 and 32768.")
    count = int(value)
    if not 1 <= count <= MAX_PALETTE_COUNT:
        raise ValueError("Palette size must be an integer between 1 and 32768.")
    return count


def validate_color_index(value: object, *, palette_count: int | None = None) -> int:
    """Return an actual colour index; sentinels are not drawing colours."""
    count = MAX_PALETTE_COUNT if palette_count is None else validate_palette_count(palette_count)
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError("Colour index must be a nonnegative integer within the palette.")
    index = int(value)
    if not 0 <= index < count:
        raise ValueError("Colour index must be a nonnegative integer within the palette.")
    return index
