"""Read selected visible pixels without converting the whole source raster."""
from __future__ import annotations

import numpy as np


def visible_samples(image, indices, *, cancelled=lambda: False):
    """Return RGB samples in the supplied flat-index order using bounded tiles.

    Sampling remains relative to every source pixel. Reducing the image first
    would change tiny accents and the deterministic refinement sample.
    """
    from ColorMatchingEngine import visible_rgb_image
    width, height = image.size
    if width < 1 or height < 1:
        raise ValueError('Image sampling needs a nonempty source.')
    selected = np.asarray(indices)
    if (selected.ndim != 1 or selected.dtype.kind not in 'iu' or
            (selected.size and (selected.min() < 0 or selected.max() >= width * height))):
        raise ValueError('Sample indices must identify existing source pixels.')
    if cancelled():
        raise InterruptedError('Image sampling cancelled.')
    result = np.empty((selected.size, 3), dtype=np.uint8)
    if not selected.size:
        return result
    xs, ys = selected % width, selected // width
    tile_width, tile_height = min(width, 256), min(height, 256)
    columns = (width + tile_width - 1) // tile_width
    keys = (ys // tile_height) * columns + xs // tile_width
    order = np.argsort(keys, kind='stable')
    sorted_keys = keys[order]
    boundaries = np.concatenate(([0], np.flatnonzero(sorted_keys[1:] != sorted_keys[:-1]) + 1,
                                 [selected.size]))
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        if cancelled():
            raise InterruptedError('Image sampling cancelled.')
        members = order[start:stop]
        key = int(sorted_keys[start])
        top, left = (key // columns) * tile_height, (key % columns) * tile_width
        box = (left, top, min(width, left + tile_width), min(height, top + tile_height))
        with image.crop(box) as tile, visible_rgb_image(tile) as rgb:
            pixels = np.asarray(rgb, dtype=np.uint8)
            result[members] = pixels[ys[members] - top, xs[members] - left]
    if cancelled():
        raise InterruptedError('Image sampling cancelled.')
    return result
