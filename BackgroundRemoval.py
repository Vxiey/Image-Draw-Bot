"""Classical, local background segmentation for Image Draw Bot.

This module intentionally uses no AI model and no network service. It combines
border-colour modelling, edge-aware region growing, conservative morphology,
connected-component sanity checks and contour-only alpha feathering.

Quality rule: when confidence is poor, preserve the original image rather than
remove likely foreground.
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
_CANCEL_INTERVAL = 4096


@dataclass(frozen=True)
class BackgroundRemovalResult:
    image: Image.Image
    metadata: dict


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


def _distance(a, b) -> float:
    dr = float(a[0]) - float(b[0])
    dg = float(a[1]) - float(b[1])
    db = float(a[2]) - float(b[2])
    return sqrt(.30 * dr * dr + .59 * dg * dg + .11 * db * db)


def _luma(p) -> float:
    return .2126 * float(p[0]) + .7152 * float(p[1]) + .0722 * float(p[2])


def _median(samples):
    if not samples:
        return (255, 255, 255)
    return tuple(sorted(int(p[c]) for p in samples)[len(samples) // 2] for c in range(3))


def _edge_samples(rgb: Image.Image):
    w, h = rgb.size
    step = max(1, min(w, h) // 96)
    out = []
    for x in range(0, w, step):
        out.extend((rgb.getpixel((x, 0)), rgb.getpixel((x, h - 1))))
    for y in range(step, h - 1, step):
        out.extend((rgb.getpixel((0, y)), rgb.getpixel((w - 1, y))))
    return [tuple(map(int, p[:3])) for p in out]


def _corners(rgb: Image.Image):
    w, h = rgb.size
    r = max(1, min(12, min(w, h) // 20))
    out = []
    for box in ((0, 0, r, r), (w - r, 0, w, r), (0, h - r, r, h), (w - r, h - r, w, h)):
        mean = ImageStat.Stat(rgb.crop(box)).mean[:3]
        out.append(tuple(int(round(v)) for v in mean))
    return out


def _reference(rgb: Image.Image, mode: str):
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
    corner_ref = _median(corners)
    corner_spread = max((_distance(p, corner_ref) for p in corners), default=0.0)
    return ref, p75, p90, corner_spread


def _proxy(rgb: Image.Image) -> Image.Image:
    w, h = rgb.size
    scale = min(
        1.0,
        _PROXY_MAX_DIMENSION / max(w, h),
        sqrt(_PROXY_MAX_PIXELS / max(1, w * h)),
    )
    if scale >= .999:
        return rgb
    return rgb.resize(
        (max(2, round(w * scale)), max(2, round(h * scale))),
        Image.Resampling.BOX,
    )


def _weighted_rgb_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a.astype(np.float32, copy=False) - b
    return np.sqrt(
        .30 * diff[..., 0] ** 2
        + .59 * diff[..., 1] ** 2
        + .11 * diff[..., 2] ** 2
    )


def _edge_strength(arr: np.ndarray) -> np.ndarray:
    """Chromatic edge magnitude, not only luma."""
    h, w, _ = arr.shape
    edge = np.zeros((h, w), dtype=np.float32)
    if w > 1:
        dx = _weighted_rgb_distance(arr[:, 1:, :], arr[:, :-1, :])
        edge[:, 1:] = np.maximum(edge[:, 1:], dx)
        edge[:, :-1] = np.maximum(edge[:, :-1], dx)
    if h > 1:
        dy = _weighted_rgb_distance(arr[1:, :, :], arr[:-1, :, :])
        edge[1:, :] = np.maximum(edge[1:, :], dy)
        edge[:-1, :] = np.maximum(edge[:-1, :], dy)
    return edge


def _border_samples(arr: np.ndarray, edge: np.ndarray) -> np.ndarray:
    h, w, _ = arr.shape
    band = max(1, min(12, round(min(w, h) * .015)))

    chunks = [
        arr[:band, :, :].reshape(-1, 3),
        arr[h - band:, :, :].reshape(-1, 3),
    ]
    edge_chunks = [
        edge[:band, :].reshape(-1),
        edge[h - band:, :].reshape(-1),
    ]
    if h > band * 2:
        chunks.extend((
            arr[band:h - band, :band, :].reshape(-1, 3),
            arr[band:h - band, w - band:, :].reshape(-1, 3),
        ))
        edge_chunks.extend((
            edge[band:h - band, :band].reshape(-1),
            edge[band:h - band, w - band:].reshape(-1),
        ))

    samples = np.concatenate(chunks, axis=0).astype(np.float32, copy=False)
    gradients = np.concatenate(edge_chunks, axis=0).astype(np.float32, copy=False)

    # Exclude high-gradient border pixels when enough quiet border evidence
    # exists. This stops an object touching the frame from becoming a colour
    # prototype while still supporting textured backgrounds.
    if len(samples) >= 32:
        cutoff = max(18.0, float(np.percentile(gradients, 70)))
        quiet = gradients <= cutoff
        if int(np.count_nonzero(quiet)) >= max(24, len(samples) // 5):
            samples = samples[quiet]

    if len(samples) > _MAX_BORDER_SAMPLES:
        indexes = np.linspace(0, len(samples) - 1, _MAX_BORDER_SAMPLES, dtype=np.int32)
        samples = samples[indexes]
    return samples


def _kmeans_border(samples: np.ndarray, clusters: int):
    """Deterministic colour clustering of border samples only."""
    if len(samples) == 0:
        return (
            np.asarray([[255., 255., 255.]], dtype=np.float32),
            np.asarray([12.], dtype=np.float32),
            np.asarray([1.], dtype=np.float32),
        )

    k = max(1, min(int(clusters), len(samples)))
    luma = .2126 * samples[:, 0] + .7152 * samples[:, 1] + .0722 * samples[:, 2]
    order = np.argsort(luma)
    seeds = np.linspace(0, len(order) - 1, k, dtype=np.int32)
    centers = samples[order[seeds]].copy()
    labels = np.full(len(samples), -1, dtype=np.int32)

    for _ in range(10):
        distances = np.stack([_weighted_rgb_distance(samples, c) for c in centers], axis=1)
        new_labels = np.argmin(distances, axis=1).astype(np.int32)
        new_centers = centers.copy()
        for idx in range(k):
            members = samples[new_labels == idx]
            if len(members):
                new_centers[idx] = np.median(members, axis=0)
        stable = np.array_equal(new_labels, labels) and np.max(np.abs(new_centers - centers)) < .35
        labels = new_labels
        centers = new_centers
        if stable:
            break

    spreads = np.empty(k, dtype=np.float32)
    weights = np.empty(k, dtype=np.float32)
    for idx in range(k):
        members = samples[labels == idx]
        weights[idx] = len(members) / max(1, len(samples))
        if len(members) < 4:
            spreads[idx] = 10.0
        else:
            d = np.sort(_weighted_rgb_distance(members, centers[idx]))
            spreads[idx] = max(5.0, float(d[int(.85 * (len(d) - 1))]))

    # Tiny clusters are commonly an object that only happens to touch an edge.
    keep = weights >= .025
    if not np.any(keep):
        keep[int(np.argmax(weights))] = True
    return centers[keep], spreads[keep], weights[keep]


def _filter_centers_for_mode(centers, spreads, weights, mode: str):
    if mode not in ("Light background", "Dark background"):
        return centers, spreads, weights
    luma = .2126 * centers[:, 0] + .7152 * centers[:, 1] + .0722 * centers[:, 2]
    keep = luma >= 135 if mode == "Light background" else luma <= 120
    if np.any(keep):
        return centers[keep], spreads[keep], weights[keep]
    return centers, spreads, weights


def _candidate_maps(arr: np.ndarray, centers: np.ndarray, spreads: np.ndarray,
                    strength: str, mode: str):
    norm_limit = {"Conservative": 1.25, "Balanced": 1.65, "Aggressive": 2.05}[strength]
    abs_limit = {"Conservative": 21.0, "Balanced": 30.0, "Aggressive": 42.0}[strength]

    distances = []
    normalized = []
    for center, spread in zip(centers, spreads):
        d = _weighted_rgb_distance(arr, center)
        distances.append(d)
        normalized.append(d / max(6.0, float(spread)))

    best_dist = np.min(np.stack(distances, axis=0), axis=0)
    best_norm = np.min(np.stack(normalized, axis=0), axis=0)
    candidate = (best_norm <= norm_limit) | (best_dist <= abs_limit)

    luma = .2126 * arr[..., 0] + .7152 * arr[..., 1] + .0722 * arr[..., 2]
    if mode == "Light background":
        candidate &= luma >= 135
    elif mode == "Dark background":
        candidate &= luma <= 120
    return candidate, best_dist, best_norm


def _region_grow(arr: np.ndarray, centers: np.ndarray, spreads: np.ndarray,
                 strength: str, mode: str, edge: np.ndarray,
                 cancelled: Callable[[], bool]):
    """Grow verified background from the image border with contour barriers."""
    h, w, _ = arr.shape
    candidate, best_dist, best_norm = _candidate_maps(arr, centers, spreads, strength, mode)

    edge_limit = {"Conservative": 20.0, "Balanced": 27.0, "Aggressive": 35.0}[strength]
    seed_edge_limit = edge_limit * 1.45
    step_limit = {"Conservative": 14.0, "Balanced": 20.0, "Aggressive": 27.0}[strength]
    relaxed_norm = {"Conservative": 1.85, "Balanced": 2.40, "Aggressive": 3.00}[strength]

    accepted = np.zeros((h, w), dtype=np.uint8)
    queued = np.zeros((h, w), dtype=np.uint8)
    q = deque()

    def seed(x: int, y: int):
        if queued[y, x]:
            return
        very_close = best_norm[y, x] <= .75
        if candidate[y, x] and (edge[y, x] <= seed_edge_limit or very_close):
            queued[y, x] = 1
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
        if processed % _CANCEL_INTERVAL == 0 and cancelled():
            raise InterruptedError()

        source = arr[y, x]
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h or accepted[ny, nx]:
                continue

            local_delta = float(_weighted_rgb_distance(arr[ny, nx], source))
            very_close = best_norm[ny, nx] <= .78
            model_ok = bool(candidate[ny, nx])
            gradual_ok = best_norm[ny, nx] <= relaxed_norm and local_delta <= step_limit
            edge_ok = edge[ny, nx] <= edge_limit or very_close

            if edge_ok and (model_ok or gradual_ok):
                accepted[ny, nx] = 1
                queued[ny, nx] = 1
                q.append((nx, ny))

    return accepted, best_dist, best_norm, processed, edge_limit


def _cleanup_background(mask: np.ndarray, strength: str) -> np.ndarray:
    """Conservative morphology for isolated one-pixel segmentation defects."""
    image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    close_radius = 3 if strength != "Aggressive" else 5
    image = image.filter(ImageFilter.MaxFilter(close_radius))
    image = image.filter(ImageFilter.MinFilter(close_radius))
    if strength == "Aggressive":
        image = image.filter(ImageFilter.MedianFilter(3))
    return (np.asarray(image, dtype=np.uint8) > 127).astype(np.uint8)


def _largest_component(mask: np.ndarray, cancelled: Callable[[], bool]):
    """Return size and bbox of the largest 4-connected foreground component."""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=np.uint8)
    best_size = 0
    best_bbox = None
    processed = 0

    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            q = deque([(x0, y0)])
            seen[y0, x0] = 1
            size = 0
            minx = maxx = x0
            miny = maxy = y0
            while q:
                x, y = q.popleft()
                size += 1
                processed += 1
                if processed % _CANCEL_INTERVAL == 0 and cancelled():
                    raise InterruptedError()
                minx = min(minx, x)
                maxx = max(maxx, x)
                miny = min(miny, y)
                maxy = max(maxy, y)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = 1
                        q.append((nx, ny))
            if size > best_size:
                best_size = size
                best_bbox = (minx, miny, maxx + 1, maxy + 1)

    return best_size, best_bbox


def _trimap_stats(background: np.ndarray, best_norm: np.ndarray, edge: np.ndarray, edge_limit: float):
    """Quantify definite background, uncertain pixels and definite foreground.

    Uncertain pixels are intentionally retained as foreground; only verified
    border-connected background becomes transparent.
    """
    definite_bg = background.astype(bool)
    likely_bg = best_norm <= 1.25
    uncertain = (~definite_bg) & likely_bg & (edge <= edge_limit * 1.35)
    definite_fg = (~definite_bg) & (~uncertain)
    total = max(1, background.size)
    return {
        "definite_background_percent": round(100.0 * int(np.count_nonzero(definite_bg)) / total, 2),
        "uncertain_percent": round(100.0 * int(np.count_nonzero(uncertain)) / total, 2),
        "definite_foreground_percent": round(100.0 * int(np.count_nonzero(definite_fg)) / total, 2),
    }


def _soft_alpha_from_background(background: np.ndarray, target_size: tuple[int, int],
                                feather_px: float) -> Image.Image:
    bg_img = Image.fromarray(background.astype(np.uint8) * 255, mode="L")
    if bg_img.size != target_size:
        bg_img = bg_img.resize(target_size, Image.Resampling.NEAREST)
    foreground = ImageOps.invert(bg_img)

    radius = max(0.0, min(1.4, float(feather_px or 0.0)))
    if radius <= .05:
        return foreground

    # Feather only the immediate contour; never blur the whole subject alpha.
    outer = foreground.filter(ImageFilter.MaxFilter(3))
    inner = foreground.filter(ImageFilter.MinFilter(3))
    boundary = np.asarray(outer, dtype=np.int16) != np.asarray(inner, dtype=np.int16)
    soft = foreground.filter(ImageFilter.GaussianBlur(radius=radius))
    hard_arr = np.asarray(foreground, dtype=np.uint8)
    soft_arr = np.asarray(soft, dtype=np.uint8)
    out = hard_arr.copy()
    out[boundary] = soft_arr[boundary]
    return Image.fromarray(out, mode="L")


def _apply_existing_alpha(alpha_img: Image.Image, old_alpha: bytes,
                          size: tuple[int, int]) -> Image.Image:
    new = np.frombuffer(alpha_img.tobytes(), dtype=np.uint8).astype(np.uint16)
    old = np.frombuffer(old_alpha, dtype=np.uint8).astype(np.uint16)
    combined = ((new * old + 127) // 255).astype(np.uint8)
    return Image.frombytes("L", size, combined.tobytes())


def _preserved_result(source: Image.Image, mode: str, strength: str, reason: str,
                      *, method: str = "safety guard preserved original",
                      extra: dict | None = None) -> BackgroundRemovalResult:
    alpha = source.getchannel("A")
    total = max(1, source.width * source.height)
    visible = sum(1 for value in alpha.tobytes() if value > 8)
    bbox = alpha.getbbox()
    metadata = {
        "mode": mode,
        "strength": strength,
        "removed_pixels": 0,
        "removed_percent": 0.0,
        "estimated_work_reduction_percent": 0.0,
        "drawable_after_percent": round(100.0 * visible / total, 2),
        "foreground_bbox": list(bbox) if bbox else None,
        "no_op_reason": reason,
        "method": method,
        "ai_used": False,
    }
    if extra:
        metadata.update(extra)
    return BackgroundRemovalResult(source, metadata)


def remove_background(image: Image.Image, *, mode="Auto", strength="Balanced", feather_px=.6,
                      cancelled: Callable[[], bool] = lambda: False) -> BackgroundRemovalResult:
    mode = validate_mode(mode)
    strength = validate_strength(strength)
    source = ImageOps.exif_transpose(image).convert("RGBA")
    w, h = source.size
    total = max(1, w * h)

    if cancelled():
        raise InterruptedError()

    old_alpha_img = source.getchannel("A")
    old_alpha = old_alpha_img.tobytes()
    before = sum(1 for a in old_alpha if a > 8)
    existing_transparency = 1.0 - (before / total)

    # Existing cutouts keep their alpha instead of being segmented a second time.
    if existing_transparency >= .20:
        return _preserved_result(
            source, mode, strength,
            "image already contains substantial transparency; original alpha preserved",
            method="existing alpha preserved",
        )

    rgb = source.convert("RGB")
    ref, spread75, spread90, corner_spread = _reference(rgb, mode)
    proxy = _proxy(rgb)
    arr = np.asarray(proxy, dtype=np.float32)

    if cancelled():
        raise InterruptedError()

    edge = _edge_strength(arr)
    samples = _border_samples(arr, edge)

    # Use fewer clusters for genuinely plain backgrounds and up to four for
    # rooms, tiles, shadows, gradients and uneven lighting.
    if corner_spread <= 10 and spread75 <= 10 and spread90 <= 18:
        cluster_count = 1
    elif corner_spread <= 24 and spread75 <= 24 and spread90 <= 42:
        cluster_count = 2
    else:
        cluster_count = 4

    centers, spreads, weights = _kmeans_border(samples, cluster_count)
    centers, spreads, weights = _filter_centers_for_mode(centers, spreads, weights, mode)

    background, best_dist, best_norm, processed, edge_limit = _region_grow(
        arr, centers, spreads, strength, mode, edge, cancelled
    )
    background = _cleanup_background(background, strength)

    proxy_total = max(1, background.size)
    bg_count = int(np.count_nonzero(background))
    bg_fraction = bg_count / proxy_total
    foreground = (background == 0).astype(np.uint8)
    largest_size, largest_bbox = _largest_component(foreground, cancelled)
    largest_fraction = largest_size / proxy_total
    foreground_fraction = 1.0 - bg_fraction
    trimap = _trimap_stats(background, best_norm, edge, edge_limit)

    safety_reason = None
    if bg_fraction > .985:
        safety_reason = "segmentation would remove over 98.5% of the image"
    elif bg_fraction < .003:
        safety_reason = "no reliable border-connected background was found"
    elif foreground_fraction < .01 and bg_fraction > .50:
        safety_reason = "remaining foreground is implausibly small"
    elif largest_fraction < .003 and bg_fraction > .20:
        safety_reason = "remaining foreground has no sufficiently large connected subject region"

    extra = {
        "reference_rgb": list(ref),
        "threshold": None,
        "border_spread_p75": round(spread75, 2),
        "border_spread_p90": round(spread90, 2),
        "corner_spread": round(corner_spread, 2),
        "background_clusters": [[round(float(v), 2) for v in center] for center in centers],
        "background_cluster_weights": [round(float(v), 4) for v in weights],
        "background_cluster_spreads": [round(float(v), 2) for v in spreads],
        "proxy_size": list(proxy.size),
        "edge_limit": edge_limit,
        "region_pixels_processed": int(processed),
        "largest_foreground_component_percent": round(100.0 * largest_fraction, 2),
        "largest_foreground_bbox_proxy": list(largest_bbox) if largest_bbox else None,
        "edge_policy": "chromatic contour barrier with local-gradient continuation",
        "trimap_policy": "uncertain pixels remain foreground; only verified border-connected background is removed",
        **trimap,
    }

    if safety_reason is not None:
        return _preserved_result(
            source, mode, strength,
            safety_reason + "; original preserved",
            extra=extra,
        )

    alpha_img = _soft_alpha_from_background(background, (w, h), feather_px)
    alpha_img = _apply_existing_alpha(alpha_img, old_alpha, (w, h))
    alpha_bytes = alpha_img.tobytes()
    after = sum(1 for a in alpha_bytes if a > 8)

    if after / total < .005:
        return _preserved_result(
            source, mode, strength,
            "foreground safety guard rejected the cut; original preserved",
            extra=extra,
        )

    result = source.copy()
    result.putalpha(alpha_img)
    removed = max(0, before - after)
    reduction = 100.0 * removed / max(1, before)
    bbox = alpha_img.getbbox()

    metadata = {
        "mode": mode,
        "strength": strength,
        **extra,
        "removed_pixels": removed,
        "removed_percent": round(100.0 * removed / total, 2),
        "estimated_work_reduction_percent": round(reduction, 2),
        "drawable_after_percent": round(100.0 * after / total, 2),
        "foreground_bbox": list(bbox) if bbox else None,
        "no_op_reason": None,
        "method": "classical edge-aware multi-colour border segmentation",
        "ai_used": False,
    }
    return BackgroundRemovalResult(result, metadata)


def png_export_ready(image: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(image).convert("RGBA")
