"""Shared finite-difference semantics for CPU and array-compatible GPU callers."""
from __future__ import annotations

import numpy as np


def luminance_edges(luminance, *, xp=np):
    """Centered interior differences and one-sided existing-image boundaries.

    A singleton axis has no gradient. Two-pixel axes retain their real edge on
    both pixels, and empty grids retain their shape without a backend launch.
    The caller owns input validation and conversion to floating-point luminance.
    """
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
