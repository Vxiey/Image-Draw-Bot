"""Bounded source-color refinement in perceptual OKLab space.

Keep source RGB values (medoids), fill unused color slots and accept only steps
that reduce sample error without worsening the 95th-percentile error. The OKLab
transform is shared with PixelAccuratePlanner; background/fixed-palette policy
is deliberately outside this image-specific pass.
Color-space reference: https://bottosson.github.io/posts/oklab/
"""
from __future__ import annotations

import numpy as np
from numbers import Integral

MAX_SAMPLES = 16384
MAX_ITERATIONS = 8
CHUNK = 2048


def _assign(points, centers, cancelled):
    indices = np.empty(len(points), dtype=np.int32)
    errors = np.empty(len(points), dtype=np.float32)
    for start in range(0, len(points), CHUNK):
        if cancelled():
            raise InterruptedError('Picture palette refinement cancelled.')
        stop = min(start + CHUNK, len(points))
        delta = points[start:stop, None, :] - centers[None, :, :]
        distances = np.sum(delta * delta, axis=2)
        indices[start:stop] = np.argmin(distances, axis=1)
        errors[start:stop] = distances[np.arange(stop-start), indices[start:stop]]
    return indices, errors


def _weighted_tail_error(errors, weights):
    """Linear p95 of repeated errors without expanding every repeated pixel."""
    if not len(errors):
        return 0.0
    if np.all(weights == 1):
        return float(np.percentile(errors, 95))
    order = np.argsort(errors, kind='stable')
    cumulative = np.cumsum(weights[order], dtype=np.int64)
    total = int(cumulative[-1])
    if total <= 0:
        return 0.0
    position = (total - 1) * .95
    low, high = int(np.floor(position)), int(np.ceil(position))
    left = errors[order[np.searchsorted(cumulative, low, side='right')]]
    right = errors[order[np.searchsorted(cumulative, high, side='right')]]
    if left == right:
        return float(left)
    # Let NumPy retain its own interpolation and dtype rules; two endpoints
    # reproduce the selected order statistics without an expanded array.
    return float(np.quantile(np.asarray([left, right], dtype=errors.dtype), position - low))


def refine_picture_palette(image, colors, max_colors, *, cancelled=lambda: False):
    from CalibrationValidation import rgb_value
    from ImageSampling import visible_samples
    from PixelAccuratePlanner import _to_oklab
    if cancelled():
        raise InterruptedError('Picture palette refinement cancelled.')
    if isinstance(max_colors, bool) or not isinstance(max_colors, Integral) or max_colors < 1:
        raise ValueError('Picture palette size must be a positive integer.')
    limit = min(32, int(max_colors))
    if not isinstance(colors, (list, tuple)) or len(colors) > 256:
        raise ValueError('Picture palette seeds must be a bounded color sequence.')
    seeds = tuple(dict.fromkeys(rgb_value(c) for c in colors))[:limit]
    if not seeds:
        raise ValueError('Picture palette refinement needs initial colors.')
    # The usual caller supplies a <=640 px analysis image. Direct callers can
    # supply a large source: only bounded tiles, never a full RGB copy, are read.
    pixels = image.width * image.height
    if pixels < 1:
        raise ValueError('Picture palette refinement needs a nonempty image.')
    count = min(pixels, MAX_SAMPLES)
    # Fixed-seed sampling avoids row/stripe aliasing without global RNG state.
    indices = (np.arange(count, dtype=np.int64) if pixels <= MAX_SAMPLES else
               np.random.default_rng(0).choice(pixels, count, replace=False))
    sampled = visible_samples(image, indices, cancelled=cancelled)
    rgb, weights = np.unique(sampled, axis=0, return_counts=True)
    if cancelled():
        raise InterruptedError('Picture palette refinement cancelled.')
    if len(rgb) <= limit and pixels <= MAX_SAMPLES:
        return tuple(tuple(map(int, c)) for c in rgb)
    points = _to_oklab(rgb)
    palette = np.asarray(seeds, dtype=np.uint8)
    labels, error = _assign(points, _to_oklab(palette), cancelled)
    # A near-color merge must not leave slots unused while gradients still
    # have measurable error. Weighted error favors repeated tones over noise.
    while len(palette) < limit and float(error.max()) > 1e-8:
        index = int(np.argmax(error * weights))
        palette = np.vstack((palette, rgb[index]))
        labels, error = _assign(points, _to_oklab(palette), cancelled)

    def quality(errors):
        return float(np.dot(errors, weights)), _weighted_tail_error(errors, weights)

    best_score, best_tail = quality(error)
    for _ in range(MAX_ITERATIONS):
        if cancelled():
            raise InterruptedError('Picture palette refinement cancelled.')
        candidate = palette.copy()
        for index in range(len(palette)):
            members = np.flatnonzero(labels == index)
            if not len(members):
                continue
            mass = int(weights[members].sum())
            # Preserve tiny accents already given a slot by the source planner.
            if mass <= max(2, len(sampled) // 200):
                continue
            center = np.average(points[members], axis=0, weights=weights[members])
            nearest = members[int(np.argmin(np.sum((points[members] - center) ** 2, axis=1)))]
            candidate[index] = rgb[nearest]
        if np.array_equal(candidate, palette):
            break
        new_labels, new_error = _assign(points, _to_oklab(candidate), cancelled)
        score, tail = quality(new_error)
        if score >= best_score or tail > best_tail + 1e-9:
            break
        palette, labels, error = candidate, new_labels, new_error
        best_score, best_tail = score, tail
    if cancelled():
        raise InterruptedError('Picture palette refinement cancelled.')
    return tuple(dict.fromkeys(tuple(map(int, color)) for color in palette))
