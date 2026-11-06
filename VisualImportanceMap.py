"""Full-resolution visual importance analysis for v1.0.118-beta.

The map is rule-based (no face recognition model).  It protects high-contrast
micro-features, boundaries and foreground structure during deadline pruning.
NumPy is the authoritative path; CuPy is used opportunistically without repeated
CPU/GPU transfers.
"""
from __future__ import annotations

from typing import Any
import math
from itertools import pairwise
import numpy as np
from PIL import Image


def _normalize(a):
    a = np.asarray(a, dtype=np.float32)
    lo = float(np.percentile(a, 2.0)) if a.size else 0.0
    hi = float(np.percentile(a, 98.0)) if a.size else 1.0
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo + 1e-6:
        lo, hi = float(a.min(initial=0.0)), float(a.max(initial=1.0))
    return np.clip((a - lo) / max(1e-6, hi - lo), 0.0, 1.0)


def _cpu_map(rgb: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    f = rgb.astype(np.float32) / 255.0
    lum = f[..., 0] * .2126 + f[..., 1] * .7152 + f[..., 2] * .0722
    from ImageGradients import luminance_edges
    edge = luminance_edges(lum)

    # Cheap local contrast using four-neighbour differences.  This catches eyes,
    # mouth lines and isolated dark details without semantic/AI detection.
    local = np.zeros_like(lum)
    local[1:-1, 1:-1] = (
        np.abs(lum[1:-1, 1:-1] - lum[:-2, 1:-1]) +
        np.abs(lum[1:-1, 1:-1] - lum[2:, 1:-1]) +
        np.abs(lum[1:-1, 1:-1] - lum[1:-1, :-2]) +
        np.abs(lum[1:-1, 1:-1] - lum[1:-1, 2:])
    ) * .25

    # Foreground pressure: distance from the robust border colour.  It is not a
    # segmentation oracle; it merely stops flat backgrounds consuming budget.
    border = np.concatenate((f[0], f[-1], f[:, 0], f[:, -1]), axis=0)
    border_rgb = np.median(border, axis=0)
    # Accumulate three channels without an extra full RGB difference cube.
    fg = (f[..., 0] - border_rgb[0]) ** 2
    fg += (f[..., 1] - border_rgb[1]) ** 2
    fg += (f[..., 2] - border_rgb[2]) ** 2
    np.sqrt(fg, out=fg)
    del f, border

    dark_micro = np.clip((.48 - lum) * 2.0, 0.0, 1.0) * np.clip(local * 6.0, 0.0, 1.0)
    edge_n = _normalize(edge)
    del edge
    contrast_n = _normalize(local)
    del local
    fg_n = _normalize(fg)
    del fg

    edge_mean = float(edge_n.mean())
    contrast_mean = float(contrast_n.mean())
    foreground_mean = float(fg_n.mean())
    imp = edge_n
    imp *= .48
    imp += .22 * contrast_n
    del contrast_n
    imp += .20 * fg_n
    del fg_n
    imp += .10 * dark_micro
    del dark_micro
    # Center weighting is deliberately mild.  It helps portraits while not
    # deleting important edge objects in landscape/game images.
    h, w = lum.shape
    del lum
    yy, xx = np.ogrid[:h, :w]
    nx = (xx - (w - 1) * .5) / max(1.0, w * .5)
    ny = (yy - (h - 1) * .5) / max(1.0, h * .5)
    center = np.sqrt(nx * nx + ny * ny)
    np.subtract(1.0, center, out=center)
    np.clip(center, 0.0, 1.0, out=center)
    center32 = center.astype(np.float32)
    del center
    center32 *= .05
    imp += center32
    np.clip(imp, 0.0, 1.0, out=imp)
    return imp.astype(np.float32, copy=False), {
        "backend": "cpu-numpy", "edge_mean": edge_mean,
        "contrast_mean": contrast_mean, "foreground_mean": foreground_mean,
        "protected_percent": float((imp >= .62).mean() * 100.0),
        "border_rgb": tuple(int(round(v * 255)) for v in border_rgb),
    }


def _gpu_map(rgb: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    import cupy as cp
    x = cp.asarray(rgb, dtype=cp.float32) / 255.0
    lum = x[..., 0] * .2126 + x[..., 1] * .7152 + x[..., 2] * .0722
    from ImageGradients import luminance_edges
    edge = luminance_edges(lum, xp=cp)
    local = cp.zeros_like(lum)
    local[1:-1, 1:-1] = (
        cp.abs(lum[1:-1, 1:-1] - lum[:-2, 1:-1]) +
        cp.abs(lum[1:-1, 1:-1] - lum[2:, 1:-1]) +
        cp.abs(lum[1:-1, 1:-1] - lum[1:-1, :-2]) +
        cp.abs(lum[1:-1, 1:-1] - lum[1:-1, 2:])
    ) * .25
    border = cp.concatenate((x[0], x[-1], x[:, 0], x[:, -1]), axis=0)
    border_rgb = cp.median(border, axis=0)
    fg = cp.sqrt(cp.sum((x - border_rgb[None, None, :]) ** 2, axis=2))

    edge_n, contrast_n, fg_n = (_normalize_gpu(a, cp) for a in (edge, local, fg))
    dark_micro = cp.clip((.48 - lum) * 2.0, 0.0, 1.0) * cp.clip(local * 6.0, 0.0, 1.0)
    imp = cp.clip(.48 * edge_n + .22 * contrast_n + .20 * fg_n + .10 * dark_micro, 0.0, 1.0)
    h, w = lum.shape
    yy, xx = cp.ogrid[:h, :w]
    nx = (xx - (w - 1) * .5) / max(1.0, w * .5)
    ny = (yy - (h - 1) * .5) / max(1.0, h * .5)
    center = cp.clip(1.0 - cp.sqrt(nx * nx + ny * ny), 0.0, 1.0)
    imp = cp.clip(imp + center * .05, 0.0, 1.0)
    meta = {
        "backend": "gpu-cupy", "edge_mean": float(edge_n.mean().get()),
        "contrast_mean": float(contrast_n.mean().get()), "foreground_mean": float(fg_n.mean().get()),
        "protected_percent": float(((imp >= .62).mean() * 100.0).get()),
        "border_rgb": tuple(int(round(float(v) * 255)) for v in cp.asnumpy(border_rgb)),
    }
    return cp.asnumpy(imp).astype(np.float32, copy=False), meta


def _normalize_gpu(a, cp):
    """Match the CPU fallback when percentiles collapse on sparse/flat maps."""
    lo = cp.percentile(a, 2.0); hi = cp.percentile(a, 98.0)
    fallback = (~cp.isfinite(lo)) | (~cp.isfinite(hi)) | (hi <= lo + 1e-6)
    lo = cp.where(fallback, cp.minimum(a.min(), 0.0), lo)
    hi = cp.where(fallback, cp.maximum(a.max(), 1.0), hi)
    return cp.clip((a - lo) / cp.maximum(cp.float32(1e-6), hi - lo), 0.0, 1.0)


def build_importance_map(image: Image.Image, options: dict[str, Any] | None = None,
                         cancelled=lambda: False) -> tuple[np.ndarray, dict[str, Any]]:
    if cancelled():
        raise InterruptedError()
    options = options or {}
    from ColorMatchingEngine import visible_rgb_image
    rgb = np.asarray(visible_rgb_image(image), dtype=np.uint8)
    h, w = rgb.shape[:2]
    pixels = int(h * w)
    use_gpu = str(options.get("gpu_mode") or "Auto") != "CPU"
    # Approx working set ~ 12 float planes. Respect an explicit VRAM allocation
    # if one is available from ResourceAllocation.
    try:
        vram_mb = float(options.get("gpu_vram_budget_mb") or options.get("vram_budget_mb") or 0.0)
        valid_budget = math.isfinite(vram_mb) and vram_mb >= 0.0
    except (ValueError, TypeError, OverflowError):
        vram_mb = 0.0
        valid_budget = False
    estimated_mb = pixels * 4 * 12 / (1024 * 1024)
    if use_gpu and valid_budget and (not vram_mb or estimated_mb <= vram_mb * .55):
        try:
            out, meta = _gpu_map(rgb)
            if cancelled():
                raise InterruptedError()
            meta.update(width=w, height=h, pixels=pixels, estimated_working_mb=round(estimated_mb, 2))
            return out, meta
        except InterruptedError:
            raise
        except Exception as error:
            gpu_error = repr(error)
    else:
        gpu_error = "GPU disabled or VRAM budget too small"
    if cancelled():
        raise InterruptedError()
    out, meta = _cpu_map(rgb)
    if cancelled():
        raise InterruptedError()
    meta.update(width=w, height=h, pixels=pixels, estimated_working_mb=round(estimated_mb, 2), gpu_fallback_reason=gpu_error)
    return out, meta


def _path_vertices(path, *, reverse=False, cancelled=lambda: False):
    """Stream the corners, retaining turns/backtracking and omitting subdivisions."""
    if cancelled():
        raise InterruptedError()
    points = iter(reversed(path) if reverse else path)
    first = tuple(next(points))
    yield first
    anchor = previous = first
    for index, raw in enumerate(points):
        if index % 128 == 0 and cancelled():
            raise InterruptedError()
        point = tuple(raw)
        if point == previous:
            continue
        ax, ay = previous[0] - anchor[0], previous[1] - anchor[1]
        bx, by = point[0] - previous[0], point[1] - previous[1]
        if ax * by != ay * bx or ax * bx + ay * by < 0:
            yield previous
            anchor = previous
        previous = point
    if previous != anchor:
        yield previous


def _canonical_path_vertices(path, *, cancelled=lambda: False):
    # The same geometric traversal gives identical floating-point sample
    # positions after a path reversal. Compare corners for a closed path too,
    # so inserting a collinear vertex cannot change the chosen direction.
    reverse = False
    for left, right in zip(_path_vertices(path, cancelled=cancelled),
                           _path_vertices(path, reverse=True, cancelled=cancelled)):
        if left != right:
            reverse = left > right
            break
    return _path_vertices(path, reverse=reverse, cancelled=cancelled)


def sample_path_importance(path, importance: np.ndarray, *, cancelled=lambda: False) -> float:
    if cancelled():
        raise InterruptedError()
    if not path or importance.size == 0:
        return 0.0
    h, w = importance.shape
    # Sample at most 24 distinct pixels along the geometry, not the stored
    # vertices. A two-point segment has an interior; neither its direction nor
    # redundant collinear vertices should change its deadline priority.
    length = math.fsum(math.dist(a, b) for a, b in
                       pairwise(_canonical_path_vertices(path, cancelled=cancelled)))
    count = min(24, max(2, math.ceil(length) + 1))
    values = []
    seen = set()

    def sample(point):
        x = min(w - 1, max(0, int(round(point[0]))))
        y = min(h - 1, max(0, int(round(point[1]))))
        if (x, y) not in seen:
            seen.add((x, y))
            values.append(float(importance[y, x]))

    vertices = _canonical_path_vertices(path, cancelled=cancelled)
    previous = next(vertices)
    sample(previous)
    distance = 0.0
    index = 1
    for point in vertices:
        segment = math.dist(previous, point)
        end = distance + segment
        while index < count - 1 and length * index / (count - 1) <= end:
            if cancelled():
                raise InterruptedError()
            fraction = max(0.0, min(1.0, (length * index / (count - 1) - distance) / segment))
            sample((previous[0] + (point[0] - previous[0]) * fraction,
                    previous[1] + (point[1] - previous[1]) * fraction))
            index += 1
        distance = end
        previous = point
    sample(previous)
    if cancelled():
        raise InterruptedError()
    values.sort()
    mean = sum(values) / len(values)
    high = values[max(0, int(len(values) * .80) - 1)]
    return max(0.0, min(1.0, mean * .62 + high * .38))


def render_importance_preview(importance: np.ndarray) -> Image.Image:
    arr = np.clip(importance * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="L").convert("RGB")
