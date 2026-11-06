"""Local classical background removal for Image Draw Bot.

No AI model, cloud API or model download is used. The remover models colours
from the image border, protects chromatic edges, grows only border-connected
background and fails closed when the cut looks destructive.
Corner color uses the dominant colour sampled at the four actual corners;
Auto models multiple colours across the full border.
"""
from __future__ import annotations

from collections import deque
from contextlib import closing
from dataclasses import dataclass
from math import isfinite, sqrt
from numbers import Real
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MODES = ("Auto", "Light background", "Dark background", "Corner color")
STRENGTHS = ("Conservative", "Balanced", "Aggressive")
_PROXY_MAX_PIXELS = 900_000
_PROXY_MAX_DIMENSION = 1200
_MAX_BORDER_SAMPLES = 4096
_CANCEL_INTERVAL = 4096
_MAX_SOURCE_PIXELS = 25_000_000
_ALPHA_STRIP_PIXELS = 262_144


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
    if w < 1 or h < 1:
        raise ValueError('Background removal needs a nonempty image.')
    scale = min(1.0, _PROXY_MAX_DIMENSION / max(w, h), sqrt(_PROXY_MAX_PIXELS / max(1, w * h)))
    if scale >= 1.0:
        return rgb
    return rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BOX)


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


def _corner_samples(a: np.ndarray) -> np.ndarray:
    """Small patches at the four actual corners, independent of side colours."""
    h, w, _ = a.shape
    band = max(1, min(12, round(min(w, h) * .03)))
    return np.concatenate([
        a[:band, :band].reshape(-1, 3), a[:band, -band:].reshape(-1, 3),
        a[-band:, :band].reshape(-1, 3), a[-band:, -band:].reshape(-1, 3),
    ]).astype(np.float32, copy=False)


def _cluster_border(samples: np.ndarray, cancelled=lambda: False):
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
        if cancelled(): raise InterruptedError()
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


def _candidate_maps(a, centers, spreads, strength, mode, cancelled=lambda: False):
    norm_limit = {"Conservative": 1.25, "Balanced": 1.65, "Aggressive": 2.05}[strength]
    abs_limit = {"Conservative": 21., "Balanced": 30., "Aggressive": 42.}[strength]
    best_dist = best_norm = None
    for center, spread in zip(centers, spreads):
        if cancelled(): raise InterruptedError()
        distance = _distance(a, center)
        normalized = distance / max(6., float(spread))
        if best_dist is None:
            best_dist, best_norm = distance, normalized
        else:
            np.minimum(best_dist, distance, out=best_dist)
            np.minimum(best_norm, normalized, out=best_norm)
    candidate = (best_norm <= norm_limit) | (best_dist <= abs_limit)
    lum = _luma(a)
    if mode == "Light background":
        candidate &= lum >= 135
    elif mode == "Dark background":
        candidate &= lum <= 120
    return candidate, best_dist, best_norm


def _grow(a, centers, spreads, strength, mode, edge, cancelled):
    h, w, _ = a.shape
    candidate, best_dist, best_norm = _candidate_maps(a, centers, spreads, strength, mode, cancelled)
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
            close = best_norm[ny, nx] <= .78
            edge_ok = edge[ny, nx] <= edge_limit or close
            if not edge_ok:
                continue
            # The expensive scalar distance matters only for relaxed growth;
            # a definite candidate already satisfies the model predicate.
            model_ok = candidate[ny, nx] or (best_norm[ny, nx] <= relaxed and
                       float(_distance(a[ny, nx], src)) <= step_limit)
            if model_ok:
                mask[ny, nx] = 1
                q.append((nx, ny))
    return mask, best_dist, best_norm, processed, edge_limit


def _cleanup(mask, strength):
    radius = 5 if strength == "Aggressive" else 3
    with closing(Image.fromarray(mask * 255)) as image:
        with closing(image.filter(ImageFilter.MaxFilter(radius))) as expanded:
            with closing(expanded.filter(ImageFilter.MinFilter(radius))) as closed:
                if strength == "Aggressive":
                    with closing(closed.filter(ImageFilter.MedianFilter(3))) as median:
                        return (np.asarray(median, np.uint8) > 127).astype(np.uint8)
                return (np.asarray(closed, np.uint8) > 127).astype(np.uint8)


def _largest_component(mask, cancelled):
    h, w = mask.shape
    seen = np.zeros((h, w), np.uint8)
    best = 0; bbox = None; checked = 0
    for y0 in range(h):
        if y0 % 32 == 0 and cancelled(): raise InterruptedError()
        for x0 in np.flatnonzero((mask[y0] != 0) & (seen[y0] == 0)):
            if seen[y0, x0]:
                continue
            q = deque([(int(x0), y0)]); seen[y0, x0] = 1
            size = 0; minx = maxx = int(x0); miny = maxy = y0
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
    with closing(Image.fromarray(mask * 255)) as bg:
        if bg.size != target_size:
            with closing(bg.resize(target_size, Image.Resampling.NEAREST)) as resized:
                fg = ImageOps.invert(resized)
        else:
            fg = ImageOps.invert(bg)
    radius = max(0., min(1.4, float(feather_px or 0.)))
    if radius <= .05:
        return fg
    try:
        with closing(fg.filter(ImageFilter.MaxFilter(3))) as outer, \
             closing(fg.filter(ImageFilter.MinFilter(3))) as inner, \
             closing(fg.filter(ImageFilter.GaussianBlur(radius))) as blurred:
            boundary = np.asarray(outer, np.uint8) != np.asarray(inner, np.uint8)
            soft = np.asarray(blurred, np.uint8)
            out = np.asarray(fg, np.uint8).copy()
            values = soft[boundary]
            out[boundary] = np.where(values < 64, 0, np.where(values > 192, 255, 128)).astype(np.uint8)
            return Image.fromarray(out)
    finally:
        fg.close()


def _multiply_alpha(alpha, old_alpha, cancelled=lambda: False):
    """Multiply masks with the existing rounded integer result and bounded scratch."""
    width, height = alpha.size
    rows = max(1, _ALPHA_STRIP_PIXELS // width)
    result = Image.new('L', alpha.size)
    try:
        for top in range(0, height, rows):
            if cancelled(): raise InterruptedError()
            bottom = min(height, top + rows)
            with closing(alpha.crop((0, top, width, bottom))) as strip:
                new = np.asarray(strip, np.uint16)
                old = np.frombuffer(old_alpha, np.uint8, count=width*(bottom-top),
                                    offset=width*top).reshape(bottom-top, width).astype(np.uint16)
                pixels = ((new * old + 127) // 255).astype(np.uint8)
                with closing(Image.fromarray(pixels)) as combined:
                    result.paste(combined, (0, top))
        return result
    except BaseException:
        result.close()
        raise


def _oriented_rgba(image):
    oriented = ImageOps.exif_transpose(image)
    if oriented.mode == 'RGBA':
        return oriented
    try:
        return oriented.convert('RGBA')
    finally:
        oriented.close()


def _preserve(source, mode, strength, reason, extra=None, method="safety guard preserved original"):
    total = max(1, source.width * source.height)
    with closing(source.getchannel("A")) as alpha:
        visible = sum(alpha.histogram()[9:])
        bbox = alpha.getbbox()
    meta = {
        "mode": mode, "strength": strength, "removed_pixels": 0, "removed_percent": 0.0,
        "estimated_work_reduction_percent": 0.0, "drawable_after_percent": round(100 * visible / total, 2),
        "foreground_bbox": list(bbox) if bbox else None,
        "no_op_reason": reason, "method": method, "ai_used": False,
    }
    if extra: meta.update(extra)
    return BackgroundRemovalResult(source, meta)


def remove_background(image: Image.Image, *, mode="Auto", strength="Balanced", feather_px=.6,
                      cancelled: Callable[[], bool] = lambda: False) -> BackgroundRemovalResult:
    mode = validate_mode(mode); strength = validate_strength(strength)
    if not isinstance(image, Image.Image) or min(image.size) < 1:
        raise ValueError('Background removal needs a nonempty image.')
    if image.width * image.height > _MAX_SOURCE_PIXELS:
        raise ValueError('Background removal is limited to 25 megapixels.')
    if isinstance(feather_px, bool) or not isinstance(feather_px, Real):
        raise ValueError('Feather radius must be a finite number.')
    try:
        feather_px = float(feather_px)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError('Feather radius must be a finite number.') from error
    if not isfinite(feather_px):
        raise ValueError('Feather radius must be a finite number.')
    owned = []
    retained = None
    def own(value):
        owned.append(value)
        return value
    if cancelled(): raise InterruptedError()
    def finish(result):
        nonlocal retained
        if cancelled(): raise InterruptedError()
        retained = result.image
        return result
    try:
        source = own(_oriented_rgba(image))
        w, h = source.size; total = max(1, w * h)
        if cancelled(): raise InterruptedError()
        with closing(source.getchannel("A")) as original_alpha:
            old_alpha = original_alpha.tobytes()
            before = sum(original_alpha.histogram()[9:])
        if 1.0 - before / total >= .20:
            return finish(_preserve(source, mode, strength, "image already contains substantial transparency; original alpha preserved", method="existing alpha preserved"))

        # Shrink before RGB conversion; invisible source RGB is not visible evidence.
        proxy_rgba = _proxy(source)
        if proxy_rgba is not source: own(proxy_rgba)
        with closing(Image.new('RGBA', proxy_rgba.size, 'white')) as flat:
            flat.alpha_composite(proxy_rgba)
            proxy = own(flat.convert('RGB'))
        a = np.asarray(proxy, np.float32)
        edge = _edge_strength(a)
        samples = _corner_samples(a) if mode == "Corner color" else _border_samples(a, edge)
        centers, spreads, weights = _cluster_border(samples, cancelled)
        if mode == "Corner color":
            # Use the dominant corner colour rather than adding every side colour
            # to the background model. Border connectivity and safety guards remain.
            chosen = int(np.argmax(weights))
            centers, spreads, weights = centers[chosen:chosen + 1], spreads[chosen:chosen + 1], weights[chosen:chosen + 1]
        centers, spreads, weights = _filter_mode(centers, spreads, weights, mode)
        if cancelled(): raise InterruptedError()
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
            return finish(_preserve(source, mode, strength, reason + "; original preserved", extra))

        with closing(_alpha(mask, (w, h), feather_px)) as foreground_alpha:
            alpha = own(_multiply_alpha(foreground_alpha, old_alpha, cancelled))
        after = sum(alpha.histogram()[9:])
        if after / total < .005:
            return finish(_preserve(source, mode, strength, "foreground safety guard rejected the cut; original preserved", extra))
        result = own(source.copy()); result.putalpha(alpha)
        removed = max(0, before - after); bbox = alpha.getbbox()
        meta = {
            "mode": mode, "strength": strength, **extra, "removed_pixels": removed,
            "removed_percent": round(100 * removed / total, 2),
            "estimated_work_reduction_percent": round(100 * removed / max(1, before), 2),
            "drawable_after_percent": round(100 * after / total, 2),
            "foreground_bbox": list(bbox) if bbox else None, "no_op_reason": None,
            "method": "classical edge-aware multi-colour border segmentation", "ai_used": False,
        }
        return finish(BackgroundRemovalResult(result, meta))
    finally:
        for value in reversed(owned):
            if value is not retained:
                value.close()


def png_export_ready(image: Image.Image) -> Image.Image:
    return _oriented_rgba(image)
