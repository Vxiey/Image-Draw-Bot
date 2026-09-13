"""Deterministic, local background removal for Image Draw Bot.

No AI model or external background-removal service is used.  The remover builds
an adaptive background model from the image border, segments only regions that
are connected to that border, protects strong object edges, and creates a soft
alpha transition at the cut boundary.

The implementation intentionally fails closed: if the segmentation looks
implausible, the original image is returned instead of deleting the subject.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageStat

MODES = ("Auto", "Light background", "Dark background", "Corner color")
STRENGTHS = ("Conservative", "Balanced", "Aggressive")

_PROXY_MAX_PIXELS = 900_000
_PROXY_MAX_DIMENSION = 1200
_MAX_BORDER_SAMPLES = 4096


def validate_mode(value: Any) -> str:
    value = str(value or "Auto")
    if value not in MODES:
        raise ValueError("Invalid background removal mode.")
    return value


def validate_strength(value: Any) -> str:
    value = str(value or "Balanced")
    if value not in STRENGTHS:
        raise ValueError("Invalid background removal strength.")
    return value


def _distance(a, b):
    dr = float(a[0]) - b[0]
    dg = float(a[1]) - b[1]
    db = float(a[2]) - b[2]
    return sqrt(.30 * dr * dr + .59 * dg * dg + .11 * db * db)


def _luma(p):
    return .2126 * p[0] + .7152 * p[1] + .0722 * p[2]


def _median(samples):
    if not samples:
        return (255, 255, 255)
    return tuple(sorted(int(p[c]) for p in samples)[len(samples) // 2] for c in range(3))


def _edge_samples(rgb):
    w, h = rgb.size
    step = max(1, min(w, h) // 96)
    out = []
    for x in range(0, w, step):
        out.extend((rgb.getpixel((x, 0)), rgb.getpixel((x, h - 1))))
    for y in range(step, h - 1, step):
        out.extend((rgb.getpixel((0, y)), rgb.getpixel((w - 1, y))))
    return [tuple(map(int, p[:3])) for p in out]


def _corners(rgb):
    w, h = rgb.size
    r = max(1, min(12, min(w, h) // 20))
    out = []
    for box in ((0, 0, r, r), (w - r, 0, w, r), (0, h - r, r, h), (w - r, h - r, w, h)):
        mean = ImageStat.Stat(rgb.crop(box)).mean[:3]
        out.append(tuple(int(round(v)) for v in mean))
    return out


def _reference(rgb, mode):
    edge = _edge_samples(rgb)
    corners = _corners(rgb)
    ref = _median(corners)
    if mode == "Light background":
        ref = _median([p for p in edge if _luma(p) >= 190] or edge)
    elif mode == "Dark background":
        ref = _median([p for p in edge if _luma(p) <= 65] or edge)
    distances = sorted(_distance(p, ref) for p in edge)
    p75 = distances[int(.75 * (len(distances) - 1))] if distances else 0.0
    p90 = distances[int(.90 * (len(distances) - 1))] if distances else 0.0
    corner_spread = max((_distance(p, _median(corners)) for p in corners), default=0.0)
    return ref, p75, p90, corner_spread


def _threshold(strength, ref, spread):
    value = {"Conservative": 18.0, "Balanced": 28.0, "Aggressive": 42.0}[strength]
    value += min(12.0, max(0.0, spread - 5.0) * .35)
    if _luma(ref) >= 238 or _luma(ref) <= 18:
        value += 5
    return max(10.0, min(58.0, value))


def _match(p, ref, limit, mode):
    if _distance(p, ref) > limit:
        return False
    if mode == "Light background" and _luma(p) < 150:
        return False
    if mode == "Dark background" and _luma(p) > 105:
        return False
    return True


def _connected_mask(rgb, ref, limit, mode, cancelled):
    w, h = rgb.size
    pix = rgb.load()
    seen = bytearray(w * h)
    mask = bytearray(w * h)
    q = deque()

    def add(x, y):
        i = y * w + x
        if seen[i]:
            return
        seen[i] = 1
        if _match(pix[x, y], ref, limit, mode):
            mask[i] = 1
            q.append(i)

    for x in range(w):
        add(x, 0)
        add(x, h - 1)
    for y in range(1, h - 1):
        add(0, y)
        add(w - 1, y)
    count = 0
    while q:
        i = q.popleft()
        y, x = divmod(i, w)
        count += 1
        if count % 4096 == 0 and cancelled():
            raise InterruptedError()
        if x:
            add(x - 1, y)
        if x + 1 < w:
            add(x + 1, y)
        if y:
            add(x, y - 1)
        if y + 1 < h:
            add(x, y + 1)
    return mask, count


def _plain_background(spread75: float, spread90: float, corner_spread: float) -> bool:
    return corner_spread <= 20.0 and spread75 <= 15.0 and spread90 <= 30.0


def _proxy(rgb: Image.Image) -> Image.Image:
    w, h = rgb.size
    scale = min(1.0, _PROXY_MAX_DIMENSION / max(w, h), sqrt(_PROXY_MAX_PIXELS / max(1, w * h)))
    if scale >= .999:
        return rgb
    return rgb.resize((max(2, round(w * scale)), max(2, round(h * scale))), Image.Resampling.BOX)


def _border_array(arr: np.ndarray) -> np.ndarray:
    h, w, _ = arr.shape
    band = max(1, min(12, round(min(w, h) * .015)))
    strips = [
        arr[:band, :, :].reshape(-1, 3),
        arr[h - band:, :, :].reshape(-1, 3),
        arr[band:h - band, :band, :].reshape(-1, 3) if h > band * 2 else np.empty((0, 3), np.float32),
        arr[band:h - band, w - band:, :].reshape(-1, 3) if h > band * 2 else np.empty((0, 3), np.float32),
    ]
    out = np.concatenate(strips, axis=0).astype(np.float32, copy=False)
    if len(out) > _MAX_BORDER_SAMPLES:
        indexes = np.linspace(0, len(out) - 1, _MAX_BORDER_SAMPLES, dtype=np.int32)
        out = out[indexes]
    return out


def _weighted_rgb_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a - b
    return np.sqrt(.30 * diff[..., 0] ** 2 + .59 * diff[..., 1] ** 2 + .11 * diff[..., 2] ** 2)


def _kmeans_border(samples: np.ndarray, clusters: int) -> tuple[np.ndarray, np.ndarray]:
    """Small deterministic k-means used only to model colours already on the border."""
    if len(samples) == 0:
        return np.asarray([[255., 255., 255.]], np.float32), np.asarray([18.], np.float32)
    k = max(1, min(int(clusters), len(samples)))
    luma = .2126 * samples[:, 0] + .7152 * samples[:, 1] + .0722 * samples[:, 2]
    order = np.argsort(luma)
    seeds = np.linspace(0, len(order) - 1, k, dtype=np.int32)
    centers = samples[order[seeds]].copy()
    labels = np.zeros(len(samples), np.int32)
    for _ in range(8):
        d = np.stack([_weighted_rgb_distance(samples, center) for center in centers], axis=1)
        new_labels = np.argmin(d, axis=1).astype(np.int32)
        new_centers = centers.copy()
        for index in range(k):
            members = samples[new_labels == index]
            if len(members):
                new_centers[index] = np.median(members, axis=0)
        if np.array_equal(new_labels, labels) and np.max(np.abs(new_centers - centers)) < .5:
            centers = new_centers
            labels = new_labels
            break
        centers = new_centers
        labels = new_labels
    spreads = []
    for index in range(k):
        members = samples[labels == index]
        if len(members) < 4:
            spreads.append(12.0)
            continue
        dist = np.sort(_weighted_rgb_distance(members, centers[index]))
        spreads.append(max(6.0, float(dist[int(.85 * (len(dist) - 1))])))
    return centers.astype(np.float32), np.asarray(spreads, np.float32)


def _edge_strength(arr: np.ndarray) -> np.ndarray:
    gray = .2126 * arr[..., 0] + .7152 * arr[..., 1] + .0722 * arr[..., 2]
    edge = np.zeros(gray.shape, dtype=np.float32)
    if gray.shape[1] > 1:
        dx = np.abs(gray[:, 1:] - gray[:, :-1])
        edge[:, 1:] = np.maximum(edge[:, 1:], dx)
        edge[:, :-1] = np.maximum(edge[:, :-1], dx)
    if gray.shape[0] > 1:
        dy = np.abs(gray[1:, :] - gray[:-1, :])
        edge[1:, :] = np.maximum(edge[1:, :], dy)
        edge[:-1, :] = np.maximum(edge[:-1, :], dy)
    return edge


def _multicluster_candidate(arr: np.ndarray, centers: np.ndarray, spreads: np.ndarray,
                            strength: str, mode: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    base = {"Conservative": 1.35, "Balanced": 1.75, "Aggressive": 2.20}[strength]
    absolute = {"Conservative": 24.0, "Balanced": 34.0, "Aggressive": 48.0}[strength]
    distances = []
    normalized = []
    for center, spread in zip(centers, spreads):
        d = _weighted_rgb_distance(arr, center)
        distances.append(d)
        normalized.append(d / max(7.0, float(spread)))
    best_dist = np.min(np.stack(distances, axis=0), axis=0)
    best_norm = np.min(np.stack(normalized, axis=0), axis=0)
    candidate = (best_norm <= base) | (best_dist <= absolute)
    luma = .2126 * arr[..., 0] + .7152 * arr[..., 1] + .0722 * arr[..., 2]
    if mode == "Light background":
        candidate &= luma >= 135
    elif mode == "Dark background":
        candidate &= luma <= 120
    return candidate, best_dist, best_norm


def _edge_aware_connected_background(arr: np.ndarray, centers: np.ndarray, spreads: np.ndarray,
                                     strength: str, mode: str, cancelled: Callable[[], bool]):
    """Region-grow from the border while respecting foreground-like edges.

    A pixel can enter through either the global border colour model or gradual
    local colour continuation.  The latter handles shadows/gradients, while an
    edge barrier prevents that continuation from walking across object contours.
    """
    h, w, _ = arr.shape
    candidate, best_dist, best_norm = _multicluster_candidate(arr, centers, spreads, strength, mode)
    edge = _edge_strength(arr)
    edge_limit = {"Conservative": 20.0, "Balanced": 27.0, "Aggressive": 35.0}[strength]
    step_limit = {"Conservative": 15.0, "Balanced": 21.0, "Aggressive": 29.0}[strength]
    relaxed_norm = {"Conservative": 2.0, "Balanced": 2.6, "Aggressive": 3.3}[strength]

    accepted = np.zeros((h, w), dtype=np.uint8)
    queued = np.zeros((h, w), dtype=np.uint8)
    q = deque()

    def seed(x: int, y: int):
        if queued[y, x]:
            return
        queued[y, x] = 1
        # Border pixels are background seeds unless they are grossly unlike all
        # other border colours. This stops a foreground object touching the edge
        # from becoming an unconditional background seed.
        if candidate[y, x] or best_norm[y, x] <= relaxed_norm:
            accepted[y, x] = 1
            q.append((x, y))

    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(1, h - 1):
        seed(0, y)
        seed(w - 1, y)

    processed = 0
    while q:
        x, y = q.popleft()
        processed += 1
        if processed % 4096 == 0 and cancelled():
            raise InterruptedError()
        source = arr[y, x]
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h or queued[ny, nx]:
                continue
            queued[ny, nx] = 1
            local_delta = float(_weighted_rgb_distance(arr[ny, nx], source))
            very_close = best_norm[ny, nx] <= .85
            model_ok = bool(candidate[ny, nx])
            gradual_ok = best_norm[ny, nx] <= relaxed_norm and local_delta <= step_limit
            edge_ok = edge[ny, nx] <= edge_limit or very_close
            if edge_ok and (model_ok or gradual_ok):
                accepted[ny, nx] = 1
                q.append((nx, ny))
    return accepted, best_dist, best_norm, edge, processed


def _cleanup_background(mask: Image.Image, strength: str) -> Image.Image:
    # Close one-pixel pinholes in the background but do not perform aggressive
    # morphology that would eat hair, eyelashes or thin contours.
    radius = {"Conservative": 3, "Balanced": 3, "Aggressive": 5}[strength]
    mask = mask.filter(ImageFilter.MaxFilter(radius))
    mask = mask.filter(ImageFilter.MinFilter(radius))
    return mask


def _soft_alpha_from_background(background: Image.Image, size: tuple[int, int], feather_px: float) -> Image.Image:
    if background.size != size:
        background = background.resize(size, Image.Resampling.NEAREST)
    foreground = ImageOps.invert(background)
    radius = max(0.0, min(1.4, float(feather_px or 0.0)))
    if radius <= .05:
        return foreground

    # Feather only near the segmentation contour. Deep foreground stays opaque
    # and deep background stays transparent, so blur cannot create a grey halo
    # across the whole subject.
    outer = foreground.filter(ImageFilter.MaxFilter(3))
    inner = foreground.filter(ImageFilter.MinFilter(3))
    boundary_arr = np.asarray(outer, dtype=np.int16) != np.asarray(inner, dtype=np.int16)
    soft = foreground.filter(ImageFilter.GaussianBlur(radius=radius))
    hard_arr = np.asarray(foreground, dtype=np.uint8)
    soft_arr = np.asarray(soft, dtype=np.uint8)
    out = hard_arr.copy()
    out[boundary_arr] = soft_arr[boundary_arr]
    return Image.fromarray(out, mode="L")


def _apply_existing_alpha(alpha_img: Image.Image, old_alpha: bytes, size: tuple[int, int]) -> Image.Image:
    new = np.frombuffer(alpha_img.tobytes(), dtype=np.uint8).astype(np.uint16)
    old = np.frombuffer(old_alpha, dtype=np.uint8).astype(np.uint16)
    combined = ((new * old + 127) // 255).astype(np.uint8)
    return Image.frombytes("L", size, combined.tobytes())


@dataclass(frozen=True)
class BackgroundRemovalResult:
    image: Image.Image
    metadata: dict


def remove_background(image: Image.Image, *, mode="Auto", strength="Balanced", feather_px=.6,
                      cancelled: Callable[[], bool] = lambda: False) -> BackgroundRemovalResult:
    mode = validate_mode(mode)
    strength = validate_strength(strength)
    source = ImageOps.exif_transpose(image).convert("RGBA")
    w, h = source.size
    total = max(1, w * h)
    old_alpha_img = source.getchannel("A")
    old_alpha = old_alpha_img.tobytes()
    before = sum(1 for a in old_alpha if a > 8)
    if cancelled():
        raise InterruptedError()

    existing_transparency = 1.0 - (before / total)
    if existing_transparency >= .20:
        bbox = old_alpha_img.getbbox()
        return BackgroundRemovalResult(source, {
            "mode": mode,
            "strength": strength,
            "removed_pixels": 0,
            "removed_percent": 0.0,
            "estimated_work_reduction_percent": 0.0,
            "drawable_after_percent": round(100.0 * before / total, 2),
            "foreground_bbox": list(bbox) if bbox else None,
            "no_op_reason": "image already contains substantial transparency; original alpha preserved",
            "method": "existing alpha preserved",
        })

    rgb = source.convert("RGB")
    ref, spread75, spread90, corner_spread = _reference(rgb, mode)
    plain = _plain_background(spread75, spread90, corner_spread)
    no_op = None

    if plain:
        limit = _threshold(strength, ref, spread75)
        mask_bytes, count = _connected_mask(rgb, ref, limit, mode, cancelled)
        fraction = count / total
        if fraction > .985:
            background = Image.new("L", (w, h), 0)
            no_op = "candidate background exceeded 98.5%; original preserved"
        else:
            background = Image.frombytes("L", (w, h), bytes(255 if v else 0 for v in mask_bytes))
        method = "fast border-connected colour segmentation"
        proxy_size = [w, h]
        clusters = [list(ref)]
        edge_limit = None
    else:
        proxy = _proxy(rgb)
        proxy_arr = np.asarray(proxy, dtype=np.float32)
        samples = _border_array(proxy_arr)
        centers, spreads = _kmeans_border(samples, 4)
        mask, _best_dist, _best_norm, _edge, processed = _edge_aware_connected_background(
            proxy_arr, centers, spreads, strength, mode, cancelled
        )
        background = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
        background = _cleanup_background(background, strength)
        bg_fraction = float(np.mean(np.asarray(background, dtype=np.uint8) > 127))
        if bg_fraction > .985:
            background = Image.new("L", proxy.size, 0)
            no_op = "segmentation would remove over 98.5% of the image; original preserved"
        elif bg_fraction < .003:
            background = Image.new("L", proxy.size, 0)
            no_op = "no reliable border-connected background was found; original preserved"
        method = "edge-aware multi-colour border region segmentation"
        proxy_size = list(proxy.size)
        clusters = [[round(float(v), 2) for v in center] for center in centers]
        limit = None
        edge_limit = {"Conservative": 20.0, "Balanced": 27.0, "Aggressive": 35.0}[strength]
        count = int(processed)

    alpha_img = _soft_alpha_from_background(background, (w, h), feather_px)
    alpha_img = _apply_existing_alpha(alpha_img, old_alpha, (w, h))
    alpha_bytes = alpha_img.tobytes()
    after = sum(1 for a in alpha_bytes if a > 8)

    # Final fail-closed guard.  It is better to leave background pixels for the
    # drawing planner than to destroy the actual subject.
    if after / total < .005:
        alpha_img = old_alpha_img
        alpha_bytes = old_alpha
        after = before
        no_op = "foreground safety guard rejected the cut; original preserved"
        method = "safety guard preserved original"

    result = source.copy()
    result.putalpha(alpha_img)
    removed = max(0, before - after)
    reduction = 100.0 * removed / max(1, before)
    bbox = alpha_img.getbbox()
    return BackgroundRemovalResult(result, {
        "mode": mode,
        "strength": strength,
        "reference_rgb": list(ref),
        "threshold": round(limit, 2) if limit is not None else None,
        "border_spread_p75": round(spread75, 2),
        "border_spread_p90": round(spread90, 2),
        "corner_spread": round(corner_spread, 2),
        "background_clusters": clusters,
        "proxy_size": proxy_size,
        "edge_limit": edge_limit,
        "region_pixels_processed": int(count),
        "removed_pixels": removed,
        "removed_percent": round(100.0 * removed / total, 2),
        "estimated_work_reduction_percent": round(reduction, 2),
        "drawable_after_percent": round(100.0 * after / total, 2),
        "foreground_bbox": list(bbox) if bbox else None,
        "no_op_reason": no_op,
        "method": method,
        "edge_policy": "strong-edge barrier plus contour-only alpha feather",
        "ai_used": False,
    })


def png_export_ready(image: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(image).convert("RGBA")
