"""Local classical background removal for Image Draw Bot.

No AI model, cloud API or model download is used. The remover models colours
from the image border, protects chromatic edges, grows only border-connected
background and fails closed when the cut looks destructive.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter, ImageOps

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


def _luma(a):
    return .2126 * a[..., 0] + .7152 * a[..., 1] + .0722 * a[..., 2]


def _distance(a, b):
    d = a.astype(np.float32, copy=False) - b
    return np.sqrt(.30 * d[..., 0] ** 2 + .59 * d[..., 1] ** 2 + .11 * d[..., 2] ** 2)


def _proxy(rgb: Image.Image) -> Image.Image:
    w, h = rgb.size
    scale = min(1.0, _PROXY_MAX_DIMENSION / max(w, h), sqrt(_PROXY_MAX_PIXELS / max(1, w * h)))
    if scale >= .999:
        return rgb
    return rgb.resize((max(2, round(w * scale)), max(2, round(h * scale))), Image.Resampling.BOX)


def _edge_strength(a: np.ndarray) -> np.ndarray:
    h, w, _ = a.shape
    out = np.zeros((h, w), np.float32)
    if w > 1:
        dx = _distance(a[:, 1:], a[:, :-1])
        out[:, 1:] = np.maximum(out[:, 1:], dx)
        out[:, :-1] = np.maximum(out[:, :-1], dx)
    if h > 1:
        dy = _distance(a[1:], a[:-1])
        out[1:] = np.maximum(out[1:], dy)
        out[:-1] = np.maximum(out[:-1], dy)
    return out


def _border_samples(a: np.ndarray, edge: np.ndarray) -> np.ndarray:
    h, w, _ = a.shape
    band = max(1, min(12, round(min(w, h) * .015)))
    parts = [a[:band].reshape(-1, 3), a[-band:].reshape(-1, 3)]
    grads = [edge[:band].reshape(-1), edge[-band:].reshape(-1)]
    if h > band * 2:
        parts += [a[band:-band, :band].reshape(-1, 3), a[band:-band, -band:].reshape(-1, 3)]
        grads += [edge[band:-band, :band].reshape(-1), edge[band:-band, -band:].reshape(-1)]
    samples = np.concatenate(parts).astype(np.float32, copy=False)
    gradients = np.concatenate(grads).astype(np.float32, copy=False)
    if len(samples) >= 32:
        quiet = gradients <= max(18.0, float(np.percentile(gradients, 70)))
        if np.count_nonzero(quiet) >= max(24, len(samples) // 5):
            samples = samples[quiet]
    if len(samples) > _MAX_BORDER_SAMPLES:
        samples = samples[np.linspace(0, len(samples) - 1, _MAX_BORDER_SAMPLES, dtype=np.int32)]
    return samples


def _cluster_border(samples: np.ndarray):
    if len(samples) == 0:
        return np.array([[255., 255., 255.]], np.float32), np.array([10.], np.float32), np.array([1.], np.float32)
    median = np.median(samples, axis=0)
    d0 = _distance(samples, median)
    spread75 = float(np.percentile(d0, 75))
    spread90 = float(np.percentile(d0, 90))
    k = 1 if spread90 <= 18 else (2 if spread75 <= 24 and spread90 <= 42 else 4)
    k = min(k, len(samples))
    order = np.argsort(_luma(samples))
    centers = samples[order[np.linspace(0, len(order) - 1, k, dtype=np.int32)]].copy()
    labels = np.full(len(samples), -1, np.int32)
    for _ in range(10):
        dist = np.stack([_distance(samples, c) for c in centers], axis=1)
        new_labels = np.argmin(dist, axis=1).astype(np.int32)
        new_centers = centers.copy()
        for i in range(k):
            members = samples[new_labels == i]
            if len(members):
                new_centers[i] = np.median(members, axis=0)
        if np.array_equal(labels, new_labels) and np.max(np.abs(new_centers - centers)) < .35:
            labels, centers = new_labels, new_centers
            break
        labels, centers = new_labels, new_centers
    spreads = np.empty(k, np.float32)
    weights = np.empty(k, np.float32)
    for i in range(k):
        members = samples[labels == i]
        weights[i] = len(members) / max(1, len(samples))
        if len(members) < 4:
            spreads[i] = 10.
        else:
            spreads[i] = max(5., float(np.percentile(_distance(members, centers[i]), 85)))
    keep = weights >= .025
    if not np.any(keep):
        keep[np.argmax(weights)] = True
    return centers[keep], spreads[keep], weights[keep]


def _filter_mode(centers, spreads, weights, mode):
    if mode not in ("Light background", "Dark background"):
        return centers, spreads, weights
    lum = _luma(centers)
    keep = lum >= 135 if mode == "Light background" else lum <= 120
    return (centers[keep], spreads[keep], weights[keep]) if np.any(keep) else (centers, spreads, weights)


def _candidate_maps(a, centers, spreads, strength, mode):
    norm_limit = {"Conservative": 1.25, "Balanced": 1.65, "Aggressive": 2.05}[strength]
    abs_limit = {"Conservative": 21., "Balanced": 30., "Aggressive": 42.}[strength]
    ds = [_distance(a, c) for c in centers]
    ns = [d / max(6., float(s)) for d, s in zip(ds, spreads)]
    best_dist = np.min(np.stack(ds), axis=0)
    best_norm = np.min(np.stack(ns), axis=0)
    candidate = (best_norm <= norm_limit) | (best_dist <= abs_limit)
    lum = _luma(a)
    if mode == "Light background":
        candidate &= lum >= 135
    elif mode == "Dark background":
        candidate &= lum <= 120
    return candidate, best_dist, best_norm


def _grow(a, centers, spreads, strength, mode, edge, cancelled):
    h, w, _ = a.shape
    candidate, best_dist, best_norm = _candidate_maps(a, centers, spreads, strength, mode)
    edge_limit = {"Conservative": 20., "Balanced": 27., "Aggressive": 35.}[strength]
    step_limit = {"Conservative": 14., "Balanced": 20., "Aggressive": 27.}[strength]
    relaxed = {"Conservative": 1.85, "Balanced": 2.40, "Aggressive": 3.00}[strength]
    mask = np.zeros((h, w), np.uint8)
    q = deque()

    def seed(x, y):
        if mask[y, x]:
            return
        close = best_norm[y, x] <= .75
        if candidate[y, x] and (edge[y, x] <= edge_limit * 1.45 or close):
            mask[y, x] = 1
            q.append((x, y))

    for x in range(w):
        seed(x, 0); seed(x, h - 1)
    for y in range(1, h - 1):
        seed(0, y); seed(w - 1, y)

    processed = 0
    while q:
        x, y = q.popleft()
        processed += 1
        if processed % _CANCEL_INTERVAL == 0 and cancelled():
            raise InterruptedError()
        src = a[y, x]
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h or mask[ny, nx]:
                continue
            local = float(_distance(a[ny, nx], src))
            close = best_norm[ny, nx] <= .78
            edge_ok = edge[ny, nx] <= edge_limit or close
            model_ok = candidate[ny, nx] or (best_norm[ny, nx] <= relaxed and local <= step_limit)
            if edge_ok and model_ok:
                mask[ny, nx] = 1
                q.append((nx, ny))
    return mask, best_dist, best_norm, processed, edge_limit


def _cleanup(mask, strength):
    image = Image.fromarray(mask * 255, mode="L")
    radius = 5 if strength == "Aggressive" else 3
    image = image.filter(ImageFilter.MaxFilter(radius)).filter(ImageFilter.MinFilter(radius))
    if strength == "Aggressive":
        image = image.filter(ImageFilter.MedianFilter(3))
    return (np.asarray(image, np.uint8) > 127).astype(np.uint8)


def _largest_component(mask, cancelled):
    h, w = mask.shape
    seen = np.zeros((h, w), np.uint8)
    best = 0; bbox = None; checked = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        q = deque([(int(x0), int(y0))]); seen[y0, x0] = 1
        size = 0; minx = maxx = int(x0); miny = maxy = int(y0)
        while q:
            x, y = q.popleft(); size += 1; checked += 1
            if checked % _CANCEL_INTERVAL == 0 and cancelled():
                raise InterruptedError()
            minx = min(minx, x); maxx = max(maxx, x); miny = min(miny, y); maxy = max(maxy, y)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = 1; q.append((nx, ny))
        if size > best:
            best, bbox = size, (minx, miny, maxx + 1, maxy + 1)
    return best, bbox


def _alpha(mask, target_size, feather_px):
    bg = Image.fromarray(mask * 255, mode="L")
    if bg.size != target_size:
        bg = bg.resize(target_size, Image.Resampling.NEAREST)
    fg = ImageOps.invert(bg)
    radius = max(0., min(1.4, float(feather_px or 0.)))
    if radius <= .05:
        return fg
    outer = fg.filter(ImageFilter.MaxFilter(3)); inner = fg.filter(ImageFilter.MinFilter(3))
    boundary = np.asarray(outer, np.int16) != np.asarray(inner, np.int16)
    soft = np.asarray(fg.filter(ImageFilter.GaussianBlur(radius)), np.uint8)
    out = np.asarray(fg, np.uint8).copy()
    values = soft[boundary]
    out[boundary] = np.where(values < 64, 0, np.where(values > 192, 255, 128)).astype(np.uint8)
    return Image.fromarray(out, mode="L")


def _preserve(source, mode, strength, reason, extra=None, method="safety guard preserved original"):
    alpha = source.getchannel("A"); total = max(1, source.width * source.height)
    visible = sum(v > 8 for v in alpha.tobytes())
    meta = {
        "mode": mode, "strength": strength, "removed_pixels": 0, "removed_percent": 0.0,
        "estimated_work_reduction_percent": 0.0, "drawable_after_percent": round(100 * visible / total, 2),
        "foreground_bbox": list(alpha.getbbox()) if alpha.getbbox() else None,
        "no_op_reason": reason, "method": method, "ai_used": False,
    }
    if extra: meta.update(extra)
    return BackgroundRemovalResult(source, meta)


def remove_background(image: Image.Image, *, mode="Auto", strength="Balanced", feather_px=.6,
                      cancelled: Callable[[], bool] = lambda: False) -> BackgroundRemovalResult:
    mode = validate_mode(mode); strength = validate_strength(strength)
    source = ImageOps.exif_transpose(image).convert("RGBA")
    w, h = source.size; total = max(1, w * h)
    if cancelled(): raise InterruptedError()
    old_alpha = source.getchannel("A").tobytes(); before = sum(a > 8 for a in old_alpha)
    if 1.0 - before / total >= .20:
        return _preserve(source, mode, strength, "image already contains substantial transparency; original alpha preserved", method="existing alpha preserved")

    proxy = _proxy(source.convert("RGB")); a = np.asarray(proxy, np.float32)
    edge = _edge_strength(a); samples = _border_samples(a, edge)
    centers, spreads, weights = _cluster_border(samples)
    centers, spreads, weights = _filter_mode(centers, spreads, weights, mode)
    mask, best_dist, best_norm, processed, edge_limit = _grow(a, centers, spreads, strength, mode, edge, cancelled)
    mask = _cleanup(mask, strength)

    n = max(1, mask.size); bg_fraction = np.count_nonzero(mask) / n
    fg = (mask == 0).astype(np.uint8); largest, bbox_proxy = _largest_component(fg, cancelled)
    largest_fraction = largest / n; fg_fraction = 1.0 - bg_fraction
    definite_bg = mask.astype(bool)
    uncertain = (~definite_bg) & (best_norm <= 1.25) & (edge <= edge_limit * 1.35)
    extra = {
        "reference_rgb": [round(float(v), 2) for v in centers[int(np.argmax(weights))]], "threshold": None,
        "background_clusters": [[round(float(v), 2) for v in c] for c in centers],
        "background_cluster_weights": [round(float(v), 4) for v in weights],
        "background_cluster_spreads": [round(float(v), 2) for v in spreads],
        "proxy_size": list(proxy.size), "edge_limit": edge_limit, "region_pixels_processed": int(processed),
        "largest_foreground_component_percent": round(100 * largest_fraction, 2),
        "largest_foreground_bbox_proxy": list(bbox_proxy) if bbox_proxy else None,
        "definite_background_percent": round(100 * np.count_nonzero(definite_bg) / n, 2),
        "uncertain_percent": round(100 * np.count_nonzero(uncertain) / n, 2),
        "definite_foreground_percent": round(100 * np.count_nonzero((~definite_bg) & (~uncertain)) / n, 2),
        "edge_policy": "chromatic contour barrier with local-gradient continuation",
        "trimap_policy": "uncertain pixels remain foreground; only verified border-connected background is removed",
    }
    reason = None
    if bg_fraction > .985: reason = "segmentation would remove over 98.5% of the image"
    elif bg_fraction < .003: reason = "no reliable border-connected background was found"
    elif fg_fraction < .01 and bg_fraction > .50: reason = "remaining foreground is implausibly small"
    elif largest_fraction < .003 and bg_fraction > .20: reason = "remaining foreground has no sufficiently large connected subject region"
    if reason:
        return _preserve(source, mode, strength, reason + "; original preserved", extra)

    alpha = _alpha(mask, (w, h), feather_px)
    new = np.frombuffer(alpha.tobytes(), np.uint8).astype(np.uint16)
    old = np.frombuffer(old_alpha, np.uint8).astype(np.uint16)
    alpha = Image.frombytes("L", (w, h), (((new * old + 127) // 255).astype(np.uint8)).tobytes())
    after = sum(v > 8 for v in alpha.tobytes())
    if after / total < .005:
        return _preserve(source, mode, strength, "foreground safety guard rejected the cut; original preserved", extra)
    result = source.copy(); result.putalpha(alpha)
    removed = max(0, before - after); bbox = alpha.getbbox()
    meta = {
        "mode": mode, "strength": strength, **extra, "removed_pixels": removed,
        "removed_percent": round(100 * removed / total, 2),
        "estimated_work_reduction_percent": round(100 * removed / max(1, before), 2),
        "drawable_after_percent": round(100 * after / total, 2),
        "foreground_bbox": list(bbox) if bbox else None, "no_op_reason": None,
        "method": "classical edge-aware multi-colour border segmentation", "ai_used": False,
    }
    return BackgroundRemovalResult(result, meta)


def png_export_ready(image: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(image).convert("RGBA")
