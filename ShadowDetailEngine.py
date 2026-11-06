"""Deterministic contour, shadow and local-tone analysis for Image Draw Bot.

The engine is intentionally non-AI. It derives luminance, local contrast,
palette boundaries and shadow-detail maps directly from the source pixels. The
maps guide the lossless Pixel Accurate scheduler; they never change source
palette assignments or invent geometry.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def _luma(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    return (arr[..., 0] * 0.2126 + arr[..., 1] * 0.7152 + arr[..., 2] * 0.0722).astype(np.float32)


def _box_blur(values: np.ndarray, radius: int) -> np.ndarray:
    radius = max(1, int(radius))
    image = Image.fromarray(np.rint(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8), mode="L")
    return (np.asarray(image.filter(ImageFilter.BoxBlur(radius)), dtype=np.float32) / 255.0).astype(np.float32)


def _gradient(values: np.ndarray) -> np.ndarray:
    f = np.asarray(values, dtype=np.float32)
    from ImageGradients import luminance_edges
    mag = luminance_edges(f)
    scale = max(1e-4, float(np.percentile(mag, 99.0)))
    return np.clip(mag / scale, 0.0, 1.0).astype(np.float32)


def _palette_boundaries(index_map: np.ndarray, drawable: np.ndarray) -> np.ndarray:
    idx = np.asarray(index_map)
    draw = np.asarray(drawable, dtype=bool)
    out = np.zeros(draw.shape, dtype=np.float32)

    valid = draw[:, 1:] & draw[:, :-1]
    diff = valid & (idx[:, 1:] != idx[:, :-1])
    out[:, 1:] = np.maximum(out[:, 1:], diff.astype(np.float32))
    out[:, :-1] = np.maximum(out[:, :-1], diff.astype(np.float32))

    valid = draw[1:, :] & draw[:-1, :]
    diff = valid & (idx[1:, :] != idx[:-1, :])
    out[1:, :] = np.maximum(out[1:, :], diff.astype(np.float32))
    out[:-1, :] = np.maximum(out[:-1, :], diff.astype(np.float32))
    return out


def analyze_shadow_contours(rgb: np.ndarray, palette_index: np.ndarray,
                            drawable: np.ndarray, edges: np.ndarray, *, cancelled=lambda:False) -> dict:
    """Return lossless guidance maps for contours, shadows and post-processing."""
    if cancelled():raise InterruptedError()
    draw = np.asarray(drawable, dtype=bool)
    luma = _luma(rgb)
    if cancelled():raise InterruptedError()
    h, w = luma.shape
    radius = max(2, min(18, int(round(min(h, w) / 48.0))))
    local_tone = _box_blur(luma, radius)
    if cancelled():raise InterruptedError()

    # A shadow is primarily a pixel that is darker than its local surroundings.
    relative = np.maximum(local_tone - luma, 0.0)
    if np.any(draw):
        scale = max(0.025, float(np.percentile(relative[draw], 97.0)))
    else:
        scale = 1.0
    local_shadow = np.clip(relative / scale, 0.0, 1.0)
    global_dark = np.clip((0.68 - luma) / 0.68, 0.0, 1.0)
    shadow = np.clip(local_shadow * 0.76 + global_dark * 0.24, 0.0, 1.0)
    shadow *= draw.astype(np.float32)

    boundary = _palette_boundaries(palette_index, draw)
    contour = np.clip(np.asarray(edges, dtype=np.float32) * 0.78 + boundary * 0.34, 0.0, 1.0)
    contour *= draw.astype(np.float32)

    shadow_gradient = _gradient(shadow)
    if cancelled():raise InterruptedError()
    fine_shadow = np.clip(shadow * (0.30 + 0.70 * contour) + shadow_gradient * 0.56, 0.0, 1.0)
    fine_shadow *= draw.astype(np.float32)

    if np.any(draw):
        contour_threshold = max(0.52, float(np.percentile(contour[draw], 86.0)))
        shadow_threshold = max(0.48, float(np.percentile(fine_shadow[draw], 84.0)))
    else:
        contour_threshold = 0.60; shadow_threshold = 0.55
    contour_mask = draw & (contour >= contour_threshold)
    shadow_detail_mask = draw & (fine_shadow >= shadow_threshold)
    deep_shadow_mask = draw & (shadow >= max(0.58, shadow_threshold * 0.88))

    denom = max(1, int(np.count_nonzero(draw)))
    metadata = {
        "engine": "Shadow + Contour Analysis v1",
        "non_ai": True,
        "local_tone_radius": int(radius),
        "contour_pixels": int(np.count_nonzero(contour_mask)),
        "contour_percent": round(100.0 * np.count_nonzero(contour_mask) / denom, 3),
        "shadow_detail_pixels": int(np.count_nonzero(shadow_detail_mask)),
        "shadow_detail_percent": round(100.0 * np.count_nonzero(shadow_detail_mask) / denom, 3),
        "deep_shadow_pixels": int(np.count_nonzero(deep_shadow_mask)),
        "deep_shadow_percent": round(100.0 * np.count_nonzero(deep_shadow_mask) / denom, 3),
        "contour_threshold": round(float(contour_threshold), 4),
        "shadow_detail_threshold": round(float(shadow_threshold), 4),
        "post_processing": "contour + shadow-detail cleanup priority",
    }
    if cancelled():raise InterruptedError()
    return {
        "luma_map": luma.astype(np.float32),
        "local_tone_map": local_tone.astype(np.float32),
        "shadow_map": shadow.astype(np.float32),
        "contour_map": contour.astype(np.float32),
        "shadow_detail_map": fine_shadow.astype(np.float32),
        "contour_mask": contour_mask,
        "shadow_detail_mask": shadow_detail_mask,
        "deep_shadow_mask": deep_shadow_mask,
        "metadata": metadata,
    }
