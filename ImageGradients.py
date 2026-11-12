"""Shared finite-difference semantics for CPU and array-compatible GPU callers."""
from __future__ import annotations

import numpy as np

_EDGE_TILE_SIDE = 256
_DENSE_EDGE_PIXELS = 262144


def _dense_luminance_edges(luminance, *, xp):
    """Unchanged finite-difference arithmetic for one complete grid."""
    gx = gy = None
    try:
        gx = xp.zeros_like(luminance)
        gy = xp.zeros_like(luminance)
        height, width = luminance.shape
        if width > 1:
            gx[:, 0] = luminance[:, 1] - luminance[:, 0]
            gx[:, -1] = luminance[:, -1] - luminance[:, -2]
            gx[:, 1:-1] = (luminance[:, 2:] - luminance[:, :-2]) * .5
        if height > 1:
            gy[0, :] = luminance[1, :] - luminance[0, :]
            gy[-1, :] = luminance[-1, :] - luminance[-2, :]
            gy[1:-1, :] = (luminance[2:, :] - luminance[:-2, :]) * .5
        return xp.sqrt(gx * gx + gy * gy)
    finally:
        gx = gy = luminance = None


def luminance_edges(luminance, *, xp=np, cancelled=None):
    """Centered interior differences and one-sided existing-image boundaries.

    A singleton axis has no gradient. Two-pixel axes retain their real edge on
    both pixels, and empty grids retain their shape without a backend launch.
    The caller owns input validation and conversion to floating-point luminance.
    """
    def check():
        if cancelled is not None and cancelled():
            raise InterruptedError('Edge analysis cancelled.')

    result = output = None
    try:
        check()
        # Native GPU expressions and small grids keep their existing dispatch.
        # Below this cutoff, output plus halo scratch barely saves allocation
        # and per-tile dispatch can be slower than the original dense operation.
        # Other dtypes also retain NumPy's established casting/error behavior;
        # the documented callers prepare float luminance before reaching here.
        if xp is not np or luminance.size <= _DENSE_EDGE_PIXELS or luminance.dtype.kind != 'f':
            result = _dense_luminance_edges(luminance, xp=xp)
            check()
            return result
        height, width = luminance.shape
        output = np.empty_like(luminance, order='K')
        # One sample of halo is sufficient for the centered differences. Only
        # original-image boundaries use the one-sided formula. Keep both axes
        # bounded, including a panorama whose single row exceeds a tile.
        for top in range(0, height, _EDGE_TILE_SIDE):
            bottom = min(height, top + _EDGE_TILE_SIDE)
            halo_top, halo_bottom = max(0, top - 1), min(height, bottom + 1)
            for left in range(0, width, _EDGE_TILE_SIDE):
                check()
                right = min(width, left + _EDGE_TILE_SIDE)
                halo_left, halo_right = max(0, left - 1), min(width, right + 1)
                result = _dense_luminance_edges(
                    luminance[halo_top:halo_bottom, halo_left:halo_right], xp=np)
                output[top:bottom, left:right] = result[
                    top - halo_top:bottom - halo_top, left - halo_left:right - halo_left]
                result = None
        check()
        return output
    finally:
        # Returned owners transfer normally; stopped/failed private tile or
        # full-output owners must not survive solely in a retained traceback.
        result = output = luminance = None
