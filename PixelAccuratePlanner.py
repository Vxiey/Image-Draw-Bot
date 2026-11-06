"""Pixel-accurate analysis core for Image Draw Bot Step 26.

Step 26 is deliberately analysis-first. Every target pixel survives into a
PixelMap before any path optimisation. Step 23 routes palette matching and edge analysis through the fastest measured
CUDA/OpenCL/NumPy backend per workload; NumPy remains the deterministic fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from typing import Sequence
import math

import numpy as np
from PIL import Image, ImageOps
from PixelMapValidation import validate_palette_count


@dataclass
class PixelMap:
    width: int
    height: int
    rgb: np.ndarray
    palette_index: np.ndarray
    drawable_mask: np.ndarray
    edge_map: np.ndarray
    importance_map: np.ndarray
    protected_mask: np.ndarray
    metadata: dict
    contour_map: np.ndarray | None = None
    shadow_map: np.ndarray | None = None
    shadow_detail_map: np.ndarray | None = None
    micro_detail_map: np.ndarray | None = None

    @property
    def pixels(self) -> int:
        return int(self.width * self.height)

    def as_meta(self) -> dict:
        out = dict(self.metadata)
        out.update({
            "width": self.width,
            "height": self.height,
            "pixels": self.pixels,
            "drawable_pixels": int(np.count_nonzero(self.drawable_mask)),
            "protected_pixels": int(np.count_nonzero(self.protected_mask)),
            "protected_percent": round(float(np.mean(self.protected_mask) * 100.0), 3),
            "edge_mean": round(float(np.mean(self.edge_map)), 4),
            "importance_mean": round(float(np.mean(self.importance_map)), 4),
        })
        if self.contour_map is not None:
            out["contour_mean"] = round(float(np.mean(self.contour_map)), 4)
        if self.shadow_map is not None:
            out["shadow_mean"] = round(float(np.mean(self.shadow_map)), 4)
        if self.shadow_detail_map is not None:
            out["shadow_detail_mean"] = round(float(np.mean(self.shadow_detail_map)), 4)
        if self.micro_detail_map is not None:
            micro = np.asarray(self.micro_detail_map, dtype=np.float32)
            out["micro_detail_mean"] = round(float(np.mean(micro)), 4)
            out["micro_detail_percent"] = round(float(np.mean(micro >= .5) * 100.0), 3)
        return out


def _visible_rgb_rgba(image: Image.Image) -> tuple[Image.Image, np.ndarray]:
    with closing(ImageOps.exif_transpose(image)) as oriented:
        rgba = oriented.convert("RGBA")
    try:
        raw = np.asarray(rgba, dtype=np.uint8)
        alpha = raw[..., 3:4].astype(np.float32) / 255.0
        rgb = raw[..., :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)
        return rgba, np.rint(rgb).clip(0, 255).astype(np.uint8)
    except BaseException:
        rgba.close()
        raise


def _to_oklab(arr: np.ndarray) -> np.ndarray:
    """Vectorized sRGB 0..255 -> OKLab float32."""
    c = np.clip(arr.astype(np.float32) / 255.0, 0.0, 1.0)
    lin = np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    ss = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    ll, mm, s3 = np.cbrt(l), np.cbrt(m), np.cbrt(ss)
    return np.stack((
        0.2104542553 * ll + 0.7936177850 * mm - 0.0040720468 * s3,
        1.9779984951 * ll - 2.4285922050 * mm + 0.4505937099 * s3,
        0.0259040371 * ll + 0.7827717662 * mm - 0.8086757660 * s3,
    ), axis=-1).astype(np.float32, copy=False)


def _oklab_chroma_hue(lab: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    aa, bb = lab[..., 1], lab[..., 2]
    chroma = np.hypot(aa, bb).astype(np.float32, copy=False) * 100.0
    hue = np.mod(np.degrees(np.arctan2(bb, aa)), 360.0).astype(np.float32, copy=False)
    return chroma, hue


def _palette_tiles(height: int, width: int, palette_count: int, row_chunk: int):
    """Keep the pixel-by-palette working tensors bounded, even for wide rows."""
    if height <= 0 or width <= 0:
        return
    pixels = max(1, 262_144 // max(1, palette_count))
    tile_width = min(width, pixels)
    tile_height = min(max(1, int(row_chunk)), max(1, pixels // tile_width))
    for y0 in range(0, height, tile_height):
        for x0 in range(0, width, tile_width):
            yield (slice(y0, min(height, y0 + tile_height)),
                   slice(x0, min(width, x0 + tile_width)))


def _cpu_palette_map(rgb: np.ndarray, palette: np.ndarray, *, perceptual: bool,
                     color_fidelity: str = "Faithful", row_chunk: int = 96,
                     cancelled=lambda: False) -> np.ndarray:
    if cancelled():raise InterruptedError()
    validate_palette_count(len(palette))
    h, w = rgb.shape[:2]
    out = np.empty((h, w), dtype=np.int16)
    pal = palette.astype(np.float32)
    if perceptual:
        pal_ok = _to_oklab(pal)
        pal_L = pal_ok[:, 0] * 100.0
        pal_chroma, pal_hue = _oklab_chroma_hue(pal_ok)
        for rows, columns in _palette_tiles(h, w, len(pal), row_chunk):
            if cancelled():raise InterruptedError()
            src_ok = _to_oklab(rgb[rows, columns])
            diff = src_ok[:, :, None, :] - pal_ok[None, None, :, :]
            dist = np.sqrt(np.sum(diff * diff, axis=3, dtype=np.float32), dtype=np.float32) * 100.0
            if color_fidelity in ("Balanced", "Faithful"):
                src_L = src_ok[..., 0] * 100.0
                light_error = np.abs(src_L[:, :, None] - pal_L[None, None, :])
                dark_loss = np.maximum(src_L[:, :, None] - pal_L[None, None, :], 0.0)
                src_chroma, src_hue = _oklab_chroma_hue(src_ok)
                chroma_error = np.abs(src_chroma[:, :, None] - pal_chroma[None, None, :])
                hue_delta = np.abs(src_hue[:, :, None] - pal_hue[None, None, :])
                hue_error = np.minimum(hue_delta, 360.0 - hue_delta)
                hue_error = np.where(np.minimum(src_chroma[:, :, None], pal_chroma[None, None, :]) < 2.5, 0.0, hue_error)
                bright_boost = 1.0 + np.maximum(src_L - 52.0, 0.0)[:, :, None] / 80.0
                vivid = src_chroma[:, :, None] >= 5.0
                neutral_cut = np.maximum(2.5, src_chroma[:, :, None] * 0.28)
                neutral_loss = np.where(vivid & (pal_chroma[None, None, :] < neutral_cut),
                                        src_chroma[:, :, None] - pal_chroma[None, None, :], 0.0)
                # The scalar matcher applies hue-family protection only to a
                # chromatic source. Near-neutral hue angles are unstable.
                hue_excess = np.where(vivid, np.maximum(hue_error - 45.0, 0.0), 0.0)
                hue_extreme = np.where(vivid, np.maximum(hue_error - 85.0, 0.0), 0.0)
                if color_fidelity == "Balanced":
                    family = neutral_loss * 0.18 + hue_excess * 0.035 + hue_extreme * 0.060
                    dist += light_error * 0.10 + dark_loss * 0.24 * bright_boost + chroma_error * 0.055 + hue_error * 0.010 + family
                else:
                    family = neutral_loss * 0.32 + hue_excess * 0.080 + hue_extreme * 0.120
                    dist += light_error * 0.22 + dark_loss * 0.55 * bright_boost + chroma_error * 0.115 + hue_error * 0.026 + family
            out[rows, columns] = np.argmin(dist, axis=2).astype(np.int16)
    else:
        for rows, columns in _palette_tiles(h, w, len(pal), row_chunk):
            if cancelled():raise InterruptedError()
            src = rgb[rows, columns].astype(np.float32)
            diff = src[:, :, None, :] - pal[None, None, :, :]
            dist = np.sum(diff * diff, axis=3)
            out[rows, columns] = np.argmin(dist, axis=2).astype(np.int16)
    if cancelled():raise InterruptedError()
    return out

def exact_palette_map(image: Image.Image, palette_rgb: Sequence[Sequence[int]], *,
                      color_rendering: str = "Perceptual match", color_fidelity: str = "Faithful", skip_white: bool = True,
                      gpu_mode: str = "Auto", gpu_vram: str = "Auto",
                      gpu_performance: str = "High throughput", cancelled=lambda: False) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    if cancelled():raise InterruptedError()
    validate_palette_count(len(palette_rgb))
    palette = np.asarray([tuple(map(int, p[:3])) for p in palette_rgb], dtype=np.uint8)
    if palette.ndim != 2 or palette.shape[0] < 1 or palette.shape[1] != 3:
        raise ValueError("Pixel Accurate mode requires at least one RGB palette colour.")

    rgba, rgb = _visible_rgb_rgba(image)
    try:
        return _exact_palette_map_visible(rgba, rgb, palette, color_rendering=color_rendering,
                                          color_fidelity=color_fidelity, skip_white=skip_white,
                                          gpu_mode=gpu_mode,cancelled=cancelled)
    finally:
        rgba.close()


def _exact_palette_map_visible(rgba, rgb, palette, *, color_rendering, color_fidelity, skip_white, gpu_mode, cancelled):
    if cancelled():raise InterruptedError()

    drawable = np.any(np.asarray(rgba, dtype=np.uint8)[..., 3:4] > 0, axis=2)
    if skip_white:
        drawable &= np.min(rgb, axis=2) < 245

    # Step 23: Auto is vendor-neutral. The saved Step 22 profile may select
    # CUDA, OpenCL (AMD/Intel/NVIDIA) or CPU independently for palette matching.
    try:
        from UniversalGpuAcceleration import palette_indices_rgba as universal_palette_indices
        candidates = tuple(range(len(palette)))
        (index_map, routed_drawable), route = universal_palette_indices(
            rgba, tuple(map(tuple, palette.tolist())), candidates, tuple(False for _ in candidates),
            color_rendering=color_rendering, custom_mode="Calibrated palette",
            color_fidelity=color_fidelity, skip_white=skip_white, gpu_mode=gpu_mode,cancelled=cancelled)
        validate_index_arrays(index_map, routed_drawable, shape=rgb.shape[:2], palette_count=len(palette),cancelled=cancelled)
        backend_id = str(route.get("backend_id") or "cpu:numpy")
        legacy_backend = "cpu-numpy" if backend_id == "cpu:numpy" else ("cuda" if backend_id.startswith("cuda:") else ("opencl" if backend_id.startswith("opencl:") else str(route.get("backend") or backend_id)))
        return (np.asarray(index_map, dtype=np.int16),
                np.asarray(routed_drawable, dtype=np.bool_), rgb,
                {"palette_backend": legacy_backend,
                 "palette_backend_id": backend_id,
                 "palette_vendor": str(route.get("vendor") or "CPU"),
                 "palette_device": str(route.get("device") or "CPU"),
                 "palette_route": dict(route),
                 "palette_distance": "OKLab" if color_rendering != "RGB nearest" else "RGB nearest",
                 "palette_fidelity": str(color_fidelity)})
    except InterruptedError:
        raise
    except Exception as exc:
        # Last-resort deterministic path. UniversalGpuAcceleration already
        # falls back internally, but this protects imports/corrupt profiles too.
        perceptual = color_rendering != "RGB nearest"
        index_map = _cpu_palette_map(rgb, palette, perceptual=perceptual, color_fidelity=color_fidelity,cancelled=cancelled)
        return index_map, drawable.astype(np.bool_), rgb, {
            "palette_backend": "cpu-numpy", "palette_backend_id": "cpu:numpy",
            "palette_route": {"fallback_reason": f"{type(exc).__name__}: {exc}"},
            "palette_distance": "OKLab" if perceptual else "RGB nearest",
            "palette_fidelity": str(color_fidelity),
        }


def edge_map(rgb: np.ndarray, *, gpu_mode: str = "Auto", gpu_vram: str = "Auto",
             gpu_performance: str = "High throughput", cancelled=lambda: False) -> tuple[np.ndarray, dict]:
    if cancelled():raise InterruptedError()
    gray = np.rint(rgb[..., 0] * .299 + rgb[..., 1] * .587 + rgb[..., 2] * .114).clip(0, 255).astype(np.uint8)
    try:
        from UniversalGpuAcceleration import edge_magnitude
        mag, route = edge_magnitude(gray.astype(np.float32), gpu_mode=gpu_mode,cancelled=cancelled)
        scale = max(1.0, float(np.percentile(mag, 99.5)))
        backend_id = str(route.get("backend_id") or "cpu:numpy")
        legacy_backend = "cpu-numpy" if backend_id == "cpu:numpy" else ("cuda" if backend_id.startswith("cuda:") else ("opencl" if backend_id.startswith("opencl:") else str(route.get("backend") or backend_id)))
        if cancelled():raise InterruptedError()
        return np.clip(mag / scale, 0.0, 1.0).astype(np.float32), {
            "edge_backend": legacy_backend,
            "edge_backend_id": backend_id,
            "edge_vendor": str(route.get("vendor") or "CPU"),
            "edge_device": str(route.get("device") or "CPU"),
            "edge_route": dict(route)}
    except InterruptedError:
        raise
    except Exception as exc:
        from ImageGradients import luminance_edges
        mag = luminance_edges(gray.astype(np.float32))
        scale = max(1.0, float(np.percentile(mag, 99.5)))
        if cancelled():raise InterruptedError()
        return np.clip(mag / scale, 0.0, 1.0).astype(np.float32), {
            "edge_backend": "cpu-numpy", "edge_backend_id": "cpu:numpy",
            "edge_route": {"fallback_reason": f"{type(exc).__name__}: {exc}"}}


def micro_detail_map(palette_index: np.ndarray, drawable: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Detect tiny/thin palette features without connected-component allocation.

    A pixel scores highly when it lies on a palette boundary, has strong edge
    energy and has few same-colour 4-neighbours. This catches pupils, whiskers,
    small text/marks and one-pixel contour fragments that global rarity alone can
    underweight. The calculation is deterministic NumPy and complements the
    GPU-routed palette/edge stages.
    """
    idx = np.asarray(palette_index)
    mask = np.asarray(drawable, dtype=np.bool_)
    edge = np.asarray(edges, dtype=np.float32)
    same = np.zeros(idx.shape, dtype=np.float32)
    neighbours = np.zeros(idx.shape, dtype=np.float32)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        src_y = slice(max(0, -dy), idx.shape[0] - max(0, dy))
        src_x = slice(max(0, -dx), idx.shape[1] - max(0, dx))
        dst_y = slice(max(0, dy), idx.shape[0] - max(0, -dy))
        dst_x = slice(max(0, dx), idx.shape[1] - max(0, -dx))
        valid = mask[src_y, src_x] & mask[dst_y, dst_x]
        # Skipped white/transparent neighbors still bound a visible feature.
        # They contribute no same-color support, but must not disappear from
        # the boundary denominator merely because they need no drawing.
        neighbours[src_y, src_x] += mask[src_y, src_x]
        same[src_y, src_x] += (valid & (idx[src_y, src_x] == idx[dst_y, dst_x])).astype(np.float32)
    boundary = np.where(neighbours > 0, 1.0 - same / np.maximum(neighbours, 1.0), 1.0).astype(np.float32)
    thin = np.clip((2.5 - same) / 2.5, 0.0, 1.0).astype(np.float32)
    score = np.clip(boundary * .48 + edge * .34 + thin * .18, 0.0, 1.0)
    score *= mask.astype(np.float32)
    return score.astype(np.float32, copy=False)


def importance_map(rgb: np.ndarray, palette_index: np.ndarray, edges: np.ndarray,
                   drawable: np.ndarray, *, contour_map: np.ndarray | None = None,
                   shadow_map: np.ndarray | None = None,
                   shadow_detail_map: np.ndarray | None = None,
                   micro_detail: np.ndarray | None = None) -> np.ndarray:
    gray = rgb.astype(np.float32).mean(axis=2) / 255.0
    local = np.zeros_like(gray, dtype=np.float32)
    local[:, 1:-1] += np.abs(gray[:, 2:] - gray[:, :-2]) * .5
    local[1:-1, :] += np.abs(gray[2:, :] - gray[:-2, :]) * .5
    local = np.clip(local, 0.0, 1.0)

    valid = palette_index[drawable]
    rarity = np.zeros_like(gray, dtype=np.float32)
    if valid.size:
        counts = np.bincount(valid.astype(np.int64), minlength=int(np.max(palette_index)) + 1).astype(np.float64)
        pixel_counts = counts[np.clip(palette_index, 0, len(counts) - 1)]
        rarity = np.where(drawable, 1.0 - np.clip(pixel_counts / max(1.0, float(valid.size)), 0.0, 1.0), 0.0).astype(np.float32)
    darkness = (1.0 - gray).astype(np.float32)
    contour = np.asarray(contour_map, dtype=np.float32) if contour_map is not None else edges
    shadow = np.asarray(shadow_map, dtype=np.float32) if shadow_map is not None else np.zeros_like(gray, dtype=np.float32)
    shadow_detail = np.asarray(shadow_detail_map, dtype=np.float32) if shadow_detail_map is not None else np.zeros_like(gray, dtype=np.float32)
    micro = np.asarray(micro_detail, dtype=np.float32) if micro_detail is not None else np.zeros_like(gray, dtype=np.float32)
    # Step 26 explicitly boosts tiny/thin palette transitions in addition to
    # contours/shadows so a small but recognizable feature is not treated like
    # disposable texture merely because its global pixel count is low.
    imp = (contour * .29 + edges * .18 + shadow_detail * .15 + micro * .18 + local * .08 +
           rarity * .06 + darkness * .03 + shadow * .03)
    imp *= drawable.astype(np.float32)
    return np.clip(imp, 0.0, 1.0).astype(np.float32)


def protect_tiny_features(palette_index: np.ndarray, drawable: np.ndarray,
                          edges: np.ndarray, importance: np.ndarray, *,
                          contour_map: np.ndarray | None = None,
                          shadow_detail_map: np.ndarray | None = None,
                          micro_detail: np.ndarray | None = None) -> np.ndarray:
    if not np.any(drawable):
        return np.zeros_like(drawable, dtype=np.bool_)
    scores = importance[drawable]
    hi = max(.58, float(np.percentile(scores, 88.0))) if scores.size else .58
    contour = np.asarray(contour_map, dtype=np.float32) if contour_map is not None else edges
    shadow_detail = np.asarray(shadow_detail_map, dtype=np.float32) if shadow_detail_map is not None else np.zeros_like(importance)
    micro = np.asarray(micro_detail, dtype=np.float32) if micro_detail is not None else np.zeros_like(importance)
    protected = drawable & ((importance >= hi) | (edges >= .68) | (contour >= .62) |
                            (shadow_detail >= .58) | (micro >= .56))
    # One-pixel dilation keeps the visual footprint of a tiny eye/edge from being
    # split by later brush-aware planning, without changing its palette index.
    grown = protected.copy()
    grown[1:, :] |= protected[:-1, :]
    grown[:-1, :] |= protected[1:, :]
    grown[:, 1:] |= protected[:, :-1]
    grown[:, :-1] |= protected[:, 1:]
    # Only protect neighbouring pixels if they are drawable and have either the
    # same colour or meaningful local importance.
    same_or_important = np.zeros_like(drawable, dtype=np.bool_)
    same_or_important[1:, :] |= palette_index[1:, :] == palette_index[:-1, :]
    same_or_important[:-1, :] |= palette_index[:-1, :] == palette_index[1:, :]
    same_or_important[:, 1:] |= palette_index[:, 1:] == palette_index[:, :-1]
    same_or_important[:, :-1] |= palette_index[:, :-1] == palette_index[:, 1:]
    return drawable & grown & (same_or_important | (importance >= .42) | (micro >= .56))


def validate_index_arrays(indices, drawable, *, shape=None, palette_count=None, cancelled=lambda: False):
    """Validate active categories before any narrowing cast or raster backend."""
    if cancelled():
        raise InterruptedError()
    count = 32768 if palette_count is None else validate_palette_count(palette_count)
    idx = np.asarray(indices)
    mask = np.asarray(drawable, dtype=np.bool_)
    if idx.ndim != 2 or idx.shape != mask.shape or (shape is not None and idx.shape != shape) or not np.issubdtype(idx.dtype, np.integer):
        raise ValueError("PixelMap indices and drawable mask must match its dimensions")
    for y in range(idx.shape[0]):
        if cancelled():
            raise InterruptedError()
        active = idx[y][mask[y]]
        if active.size and (np.min(active) < 0 or np.max(active) >= count):
            raise ValueError("Drawable PixelMap index is outside the palette")
    return idx, mask


def validated_pixel_indices(pixel_map: PixelMap, palette_count=None, *, cancelled=lambda: False):
    idx = np.asarray(pixel_map.palette_index)
    # PicturePalettePlanning's legacy adapter carries height and the arrays;
    # full PixelMap instances also declare width, which remains authoritative.
    width = getattr(pixel_map, 'width', idx.shape[1] if idx.ndim == 2 else -1)
    shape = (pixel_map.height, width)
    return validate_index_arrays(idx, pixel_map.drawable_mask, shape=shape,
                                 palette_count=palette_count, cancelled=cancelled)


def groups_from_pixel_map(pixel_map: PixelMap, palette_count: int, *, lines: bool = True,
                          cancelled=lambda: False) -> list[list[tuple[int, int, int, int]]]:
    count = validate_palette_count(palette_count)
    idx, mask = validated_pixel_indices(pixel_map, count, cancelled=cancelled)
    groups = [[] for _ in range(count)]
    for y in range(pixel_map.height):
        if cancelled():
            raise InterruptedError()
        active = idx[y][mask[y]]
        # The -1 background sentinel must not be cast into an unsigned source
        # dtype (NumPy 2 rejects that cast). Only validated drawable indices are
        # copied; arbitrary masked-out values never participate in rendering.
        row = np.full(mask[y].shape, -1, dtype=np.intp)
        row[mask[y]] = active
        if not lines:
            for x in np.flatnonzero(mask[y]):
                groups[int(row[x])].append((int(x), y, int(x), y))
            continue
        # Row-sized temporaries; no Python work for every background pixel.
        boundaries = np.r_[0, np.flatnonzero(row[1:] != row[:-1]) + 1, row.size]
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            color = int(row[start]) if start < row.size else -1
            if color >= 0:
                groups[color].append((int(start), y, int(end) - 1, y))
    return groups


def build_pixel_map(image: Image.Image, palette_rgb: Sequence[Sequence[int]], *,
                    color_rendering: str = "Perceptual match", color_fidelity: str = "Faithful", skip_white: bool = True,
                    gpu_mode: str = "Auto", gpu_vram: str = "Auto",
                    gpu_performance: str = "High throughput", cancelled=lambda: False) -> PixelMap:
    index_map, drawable, rgb, palette_meta = exact_palette_map(
        image, palette_rgb, color_rendering=color_rendering, color_fidelity=color_fidelity, skip_white=skip_white,
        gpu_mode=gpu_mode, gpu_vram=gpu_vram, gpu_performance=gpu_performance,cancelled=cancelled)
    edges, edge_meta = edge_map(rgb, gpu_mode=gpu_mode, gpu_vram=gpu_vram,
                                gpu_performance=gpu_performance,cancelled=cancelled)
    if cancelled():raise InterruptedError()
    from ShadowDetailEngine import analyze_shadow_contours
    tone = analyze_shadow_contours(rgb, index_map, drawable, edges,cancelled=cancelled)
    if cancelled():raise InterruptedError()
    micro = micro_detail_map(index_map, drawable, edges)
    if cancelled():raise InterruptedError()
    importance = importance_map(
        rgb, index_map, edges, drawable, contour_map=tone["contour_map"],
        shadow_map=tone["shadow_map"], shadow_detail_map=tone["shadow_detail_map"],
        micro_detail=micro)
    if cancelled():raise InterruptedError()
    protected = protect_tiny_features(
        index_map, drawable, edges, importance, contour_map=tone["contour_map"],
        shadow_detail_map=tone["shadow_detail_map"], micro_detail=micro)
    if cancelled():raise InterruptedError()
    meta = {
        "engine": "Step 26 Detail Fidelity PixelMap + Shadow/Contour",
        "step": 26,
        "detail_fidelity": True,
        "full_resolution": True,
        "destructive_simplification": False,
        "tiny_feature_protection": True,
        "shadow_analysis": True,
        "contour_analysis": True,
        "post_processing_priority": True,
        "micro_detail_protection": True,
        "simplification_policy": "lossless-only",
        "analysis_backends": {
            "palette": palette_meta.get("palette_backend_id", palette_meta.get("palette_backend", "cpu:numpy")),
            "edge": edge_meta.get("edge_backend_id", edge_meta.get("edge_backend", "cpu:numpy")),
            "importance": "cpu:numpy",
            "micro_detail": "cpu:numpy",
        },
        **palette_meta, **edge_meta, **tone["metadata"],
    }
    return PixelMap(rgb.shape[1], rgb.shape[0], rgb, index_map, drawable,
                    edges, importance, protected, meta, tone["contour_map"],
                    tone["shadow_map"], tone["shadow_detail_map"], micro)
