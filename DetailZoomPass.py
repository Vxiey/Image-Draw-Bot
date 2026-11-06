"""Adaptive Detail Zoom Pass for Image Draw Bot.

This is an *internal source-analysis zoom*, not browser/page zoom.  The pass
revisits a bounded set of high-frequency source regions at 2x/4x analysis
resolution, then maps only high-value micro details back into the existing
canvas coordinate system.  That preserves target calibration and CanvasGuard
while recovering details that a globally reduced planning resolution can miss.

The pass is deterministic, local-only, palette-safe and deadline-aware.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import math

import numpy as np
from PIL import Image, ImageOps, ImageDraw

DETAIL_ZOOM_MODES = ("Auto", "Off", "2x", "4x")


def validate_detail_zoom_mode(value: str) -> str:
    value = str(value or "Auto")
    if value not in DETAIL_ZOOM_MODES:
        raise ValueError(f"Detail zoom must be one of: {', '.join(DETAIL_ZOOM_MODES)}")
    return value


def _visible_rgb(image: Image.Image) -> np.ndarray:
    rgba = np.asarray(ImageOps.exif_transpose(image).convert("RGBA"), dtype=np.uint8)
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)
    return np.rint(rgb).clip(0, 255).astype(np.uint8)


def _resolved_factor(mode: str, options: dict, source_size, work_size) -> int:
    mode = validate_detail_zoom_mode(mode)
    if mode == "Off":
        return 1
    # Pixel Accurate already plans against the full target PixelMap. Repeating
    # the same target pixels at a higher analysis zoom cannot add real detail,
    # even when a stale/manual 2x/4x preference was restored from settings.
    if str(options.get("draw_quality") or "") == "Pixel Accurate":
        return 1
    if mode == "2x":
        return 2
    if mode == "4x":
        return 4
    if options.get("outline") or options.get("erase_mode") or options.get("paint_current_color"):
        return 1

    quality = str(options.get("draw_quality") or "High likeness")
    time_active = bool(options.get("time_budget_active"))
    seconds = float(options.get("time_budget_seconds") or options.get("max_seconds") or 180)
    sw, sh = map(int, source_size)
    ww, wh = map(int, work_size)
    source_gain = max(sw / max(1, ww), sh / max(1, wh))

    # If the source contains materially more spatial information than the global
    # planning image, zooming the analysis is useful.  Tight game budgets stay
    # conservative because Step 8 should not spend the silhouette budget on texture.
    if time_active and seconds <= 80:
        return 2 if quality in ("Maximum likeness", "GPU enhanced") and source_gain >= 1.25 else 1
    if quality in ("Maximum likeness", "GPU enhanced"):
        return 4 if source_gain >= 1.55 and (not time_active or seconds >= 150) else 2
    if quality == "High likeness" and source_gain >= 1.20:
        return 2
    return 1


def _path_cap(options: dict, factor: int) -> int:
    if factor <= 1:
        return 0
    active = bool(options.get("time_budget_active"))
    seconds = float(options.get("time_budget_seconds") or options.get("max_seconds") or 180)
    if not active or options.get("unlimited_time"):
        return 120 if factor >= 4 else 84
    if seconds <= 80:
        return 16
    if seconds <= 150:
        return 32
    if seconds <= 300:
        return 60
    return 90


def _smallest_runtime_brush(options: dict) -> int:
    default = max(1, int(options.get("brush_px", 1) or 1))
    plan = options.get("browser_brush_plan") or {}
    try:
        from AdaptiveBrushEngine import verified_brush_sizes
        sizes, dynamic = verified_brush_sizes(str(options.get("profile_key") or ""), plan, default)
        if dynamic:
            return min(sizes)
    except Exception:
        pass
    if str(options.get("profile_key") or "") == "microsoft-paint" and str(options.get("effective_paint_tool") or "") == "Pencil":
        return 1
    return default


def _palette_index(rgb, palette: Sequence[Sequence[int]], options: dict) -> tuple[int, float]:
    from ColorFidelity import palette_match_cost
    fidelity = str(options.get("color_fidelity") or "Faithful")
    rendering = str(options.get("color_rendering") or "Perceptual match")
    best_i = 0
    best = float("inf")
    for i, candidate in enumerate(palette):
        cost = palette_match_cost(rgb, candidate, color_rendering=rendering, fidelity=fidelity)
        if cost < best:
            best, best_i = float(cost), int(i)
    return best_i, best


def _gray(arr: np.ndarray) -> np.ndarray:
    a = arr.astype(np.float32)
    return a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722


def _gradient(gray: np.ndarray) -> np.ndarray:
    gx = np.zeros_like(gray, dtype=np.float32)
    gy = np.zeros_like(gray, dtype=np.float32)
    gx[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1])
    gy[1:, :] = np.abs(gray[1:, :] - gray[:-1, :])
    return np.maximum(gx, gy)


def _pool_blocks(arr: np.ndarray, factor: int, h: int, w: int, reducer: str) -> np.ndarray:
    work = arr[:h * factor, :w * factor]
    shaped = work.reshape(h, factor, w, factor)
    if reducer == "max":
        return shaped.max(axis=(1, 3))
    if reducer == "std":
        return shaped.std(axis=(1, 3))
    if reducer == "mean":
        return shaped.mean(axis=(1, 3))
    raise ValueError(reducer)


def _candidate_cells(source_zoom: np.ndarray, base_rgb: np.ndarray, factor: int, *, skip_white: bool) -> tuple[np.ndarray, np.ndarray]:
    h, w = base_rgb.shape[:2]
    zg = _gray(source_zoom)
    bg = _gray(base_rgb)
    edge_hi = _pool_blocks(_gradient(zg), factor, h, w, "max")
    std_hi = _pool_blocks(zg, factor, h, w, "std")

    # Colour range catches tiny saturated accents that have similar luminance.
    zf = source_zoom[:h * factor, :w * factor].reshape(h, factor, w, factor, 3).astype(np.float32)
    color_range = (zf.max(axis=(1, 3)) - zf.min(axis=(1, 3))).max(axis=2)
    base_edge = _gradient(bg)
    lost = np.maximum(edge_hi - base_edge * .72, 0.0)
    score = lost * .52 + std_hi * .31 + color_range * .17

    if skip_white:
        # Avoid spending detail budget on imperceptible white-paper texture.
        mean_hi = zf.mean(axis=(1, 3))
        near_white = np.all(mean_hi >= 246.0, axis=2)
        score[near_white] = 0.0

    # Border pixels are legal, but edge-heavy resampling there is frequently a
    # crop artefact rather than useful subject detail.
    if h > 2 and w > 2:
        score[[0, -1], :] *= .35
        score[:, [0, -1]] *= .35
    return score.astype(np.float32), edge_hi.astype(np.float32)


def _pick_cells(score: np.ndarray, cap: int, *, threshold: float) -> list[tuple[int, int, float]]:
    if cap <= 0 or score.size == 0:
        return []
    flat = score.ravel()
    eligible = np.flatnonzero(flat >= threshold)
    if not len(eligible):
        return []
    # Each accepted cell blocks at most nine eligible cells. The best 9*(2*cap)
    # entries therefore contain every cell the legacy scan can accept before
    # reaching its 2*cap limit. Keep ties by original index, including at the
    # partition boundary, then sort only that bounded shortlist.
    shortlist = min(len(eligible), 18 * cap)
    if shortlist < len(eligible):
        values = flat[eligible]
        cutoff = np.partition(values, len(values) - shortlist)[len(values) - shortlist]
        stronger = eligible[values > cutoff]
        tied = eligible[values == cutoff][:shortlist - len(stronger)]
        eligible = np.concatenate((stronger, tied))
    order = eligible[np.lexsort((eligible, -flat[eligible].astype(np.float64)))]
    h, w = score.shape
    blocked = np.zeros((h, w), dtype=bool)
    out = []
    for idx in order:
        y, x = divmod(idx, w)
        if blocked[y, x]:
            continue
        value = float(score[y, x])
        out.append((x, y, value))
        y0, y1 = max(0, y - 1), min(h, y + 2)
        x0, x1 = max(0, x - 1), min(w, x + 2)
        blocked[y0:y1, x0:x1] = True
        if len(out) >= cap * 2:
            break
    return out


def _subpixel_rgb(source_zoom: np.ndarray, x: int, y: int, factor: int,
                  base_rgb: Sequence[int] | None = None) -> tuple[int, int, int]:
    block = source_zoom[y * factor:(y + 1) * factor, x * factor:(x + 1) * factor]
    if block.size == 0:
        return (255, 255, 255)
    g = _gray(block)
    grad = _gradient(g).astype(np.float32)
    # A pure edge maximum can land on the background side of a transition. For
    # detail recovery, prefer the source subpixel that differs most from the
    # already-planned base pixel, with local edge energy as a secondary signal.
    # This recovers tiny dark lines/colored accents that global downsampling erased.
    if base_rgb is not None:
        base = np.asarray(tuple(base_rgb)[:3], dtype=np.float32).reshape(1, 1, 3)
        diff = np.linalg.norm(block.astype(np.float32) - base, axis=2)
        score = diff + grad * 0.35
    else:
        score = grad
    pos = int(np.argmax(score))
    yy, xx = divmod(pos, block.shape[1])
    return tuple(map(int, block[yy, xx, :3]))


def _group_same_color(points_by_color: dict[int, list[tuple[int, int, float]]]) -> dict[int, list[list[tuple[int, int]]]]:
    """Join only adjacent points of the same colour; never bridge empty pixels."""
    result: dict[int, list[list[tuple[int, int]]]] = {}
    for color, items in points_by_color.items():
        remaining = {(int(x), int(y)): float(s) for x, y, s in items}
        paths = []
        while remaining:
            start = min(remaining, key=lambda p: (-remaining[p], p[1], p[0]))
            path = [start]
            remaining.pop(start, None)
            current = start
            # Greedy bounded 4-neighbour chain. This is purely an operation-count
            # optimization; every connector lands on another selected detail pixel.
            for _ in range(7):
                x, y = current
                candidates = [p for p in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if p in remaining]
                if not candidates:
                    break
                nxt = max(candidates, key=lambda p: (remaining[p], -p[1], -p[0]))
                path.append(nxt)
                remaining.pop(nxt, None)
                current = nxt
            paths.append(path)
        result[int(color)] = paths
    return result


def _roi_boxes(cells: list[tuple[int, int, float]], width: int, height: int, factor: int) -> list[tuple[int, int, int, int]]:
    if not cells:
        return []
    # Cluster selected cells into a handful of coarse tiles for diagnostics.
    tile = max(4, round(min(width, height) / 12))
    buckets: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y, _ in cells:
        buckets.setdefault((x // tile, y // tile), []).append((x, y))
    boxes = []
    for _, pts in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8]:
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        pad = 2 if factor == 2 else 3
        boxes.append((max(0, min(xs) - pad), max(0, min(ys) - pad),
                      min(width - 1, max(xs) + pad), min(height - 1, max(ys) + pad)))
    return boxes


def add_detail_zoom_pass(original_source: Image.Image, working_image: Image.Image,
                         palette_rgb: Sequence[Sequence[int]], groups, execution_groups,
                         execution_sequence, options: dict, *, cancelled=lambda: False):
    """Return updated geometry plus compact Detail Zoom metadata.

    The original source is revisited at a bounded 2x/4x analysis resolution.  Only
    source-backed micro details whose palette mapping actually changes the current
    working pixel are appended.  No application/browser zoom is performed.
    """
    mode = validate_detail_zoom_mode(options.get("detail_zoom", "Auto"))
    if not isinstance(original_source, Image.Image) or not isinstance(working_image, Image.Image):
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "reason": "source image unavailable"}
    if execution_groups is None or not palette_rgb:
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "reason": "no path/palette plan"}

    factor = _resolved_factor(mode, options, original_source.size, working_image.size)
    if factor <= 1:
        reason = "Pixel Accurate/full target already preserves target pixels" if str(options.get("draw_quality") or "") == "Pixel Accurate" else "no useful zoom gain for current quality/budget"
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "factor": 1, "reason": reason, "target_app_zoomed": False}

    cap = _path_cap(options, factor)
    if cap <= 0:
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "factor": factor, "reason": "detail path budget is zero", "target_app_zoomed": False}
    if cancelled():
        raise InterruptedError()

    w, h = map(int, working_image.size)
    # Bound memory even for large source photos.  The zoom factor describes local
    # analysis density relative to the plan, not an unbounded source upsample.
    max_dim = 1800 if factor >= 4 else 1500
    effective = factor
    if max(w * effective, h * effective) > max_dim:
        effective = min(factor, int(max_dim / max(w, h)))
    if effective < 2:
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "factor": 1, "reason": "planning image already near detail-analysis limit", "target_app_zoomed": False}

    base = _visible_rgb(working_image)
    source_zoom = np.asarray(Image.fromarray(_visible_rgb(original_source), "RGB").resize((w * effective, h * effective), Image.Resampling.LANCZOS), dtype=np.uint8)
    if cancelled():
        raise InterruptedError()
    score, edge_hi = _candidate_cells(source_zoom, base, effective, skip_white=bool(options.get("skip_white", True)))
    nz = score[score > 0]
    if not nz.size:
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "factor": effective, "reason": "no high-frequency detail regions", "target_app_zoomed": False}
    threshold = max(18.0, float(np.percentile(nz, 82.0)))
    candidates = _pick_cells(score, cap, threshold=threshold)
    if not candidates:
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "factor": effective, "reason": "no detail exceeded the zoom threshold", "target_app_zoomed": False}

    palette = tuple(tuple(map(int, p[:3])) for p in palette_rgb)
    points_by_color: dict[int, list[tuple[int, int, float]]] = {}
    accepted_cells = []
    rejected_same = 0
    rejected_weak = 0
    for x, y, raw_score in candidates:
        if cancelled():
            raise InterruptedError()
        rgb = _subpixel_rgb(source_zoom, x, y, effective, base[y, x, :3])
        index, cost = _palette_index(rgb, palette, options)
        current_index, current_cost = _palette_index(tuple(map(int, base[y, x, :3])), palette, options)
        # If the zoomed source resolves to the same palette colour as the existing
        # plan, drawing it again adds no visible information.
        if index == current_index:
            rejected_same += 1
            continue
        # Reject tiny palette deltas; detail budget should buy a visible feature.
        from ColorFidelity import delta_e_oklab
        palette_delta = float(delta_e_oklab(palette[current_index], palette[index]))
        if palette_delta < 5.0:
            rejected_weak += 1
            continue
        normalized = max(0.0, min(1.0, raw_score / 140.0))
        importance = .70 + normalized * .28
        points_by_color.setdefault(index, []).append((x, y, importance))
        accepted_cells.append((x, y, raw_score))
        if sum(len(v) for v in points_by_color.values()) >= cap * 2:
            break

    grouped = _group_same_color(points_by_color)
    detail_paths = []
    for color in sorted(grouped):
        for path in grouped[color]:
            detail_paths.append((color, path))
    detail_paths.sort(key=lambda item: (-max(score[y, x] for x, y in item[1]), item[0], item[1][0][1], item[1][0][0]))
    detail_paths = detail_paths[:cap]
    if not detail_paths:
        return groups, execution_groups, execution_sequence, {"enabled": False, "requested": mode, "factor": effective, "reason": "zoomed details mapped to existing plan colors", "target_app_zoomed": False, "rejected_same_color": rejected_same}

    new_groups = [list(g) for g in groups]
    new_exec = [list(g) for g in execution_groups]
    sequence_active = bool(execution_sequence)
    new_seq = [dict(e) for e in (execution_sequence or [])]
    smallest_brush = _smallest_runtime_brush(options)
    phases = {str(e.get("phase") or "") for e in new_seq}
    deadline_mode = bool(phases.intersection({"major_coverage", "structure", "important_details", "accuracy", "correction"}))
    phase = "important_details" if deadline_mode else "details"
    seconds_per = max(.015, float(options.get("delay", .002) or .002) * 3.0 + .018)

    appended = 0
    detail_pixels = 0
    for color, path in detail_paths:
        if cancelled():
            raise InterruptedError()
        if not (0 <= color < len(new_exec)):
            continue
        clean = [(int(x), int(y)) for x, y in path]
        if not clean:
            continue
        new_exec[color].append(clean)
        # Keep legacy group-based diagnostics/active-colour accounting aware of
        # the new detail without changing the earlier source-stroke count.
        if 0 <= color < len(new_groups):
            if len(clean) == 1:
                x, y = clean[0]; new_groups[color].append((x, y, x, y))
            else:
                for a, b in zip(clean, clean[1:]):
                    new_groups[color].append((a[0], a[1], b[0], b[1]))
        imp = max(.72, min(.99, max(float(score[y, x]) for x, y in clean) / 140.0 * .25 + .74))
        entry = {
            "color_index": int(color), "path": tuple(clean), "phase": phase,
            "brush_px": int(smallest_brush), "importance": round(imp, 4),
            "structural_score": .22, "optional": True,
            "operation_type": "zoom_detail_stroke",
            "estimated_cost_seconds": round(seconds_per + max(0, len(clean) - 1) * .006, 5),
            "detail_zoom": True, "detail_zoom_factor": int(effective),
        }
        if deadline_mode:
            entry["deadline_phase"] = "important_details"
        if sequence_active:
            new_seq.append(entry)
        appended += 1
        detail_pixels += len(clean)

    rois = _roi_boxes(accepted_cells, w, h, effective)
    meta = {
        "enabled": bool(appended), "requested": mode, "factor": int(effective),
        "analysis_zoom": f"{int(effective)}x", "target_app_zoomed": False,
        "target_zoom_policy": "internal-source-analysis-only",
        "detail_paths_added": int(appended), "detail_pixels_added": int(detail_pixels),
        "candidate_cells": int(len(candidates)), "accepted_cells": int(len(accepted_cells)),
        "rejected_same_color": int(rejected_same), "rejected_weak_palette_delta": int(rejected_weak),
        "threshold": round(float(threshold), 3), "smallest_detail_brush_px": int(smallest_brush),
        "roi_boxes": tuple(tuple(map(int, b)) for b in rois),
        "deadline_aware": bool(options.get("time_budget_active")),
        "path_cap": int(cap),
        "sequence_appended": bool(sequence_active and appended),
        "active_color_indices": tuple(sorted(int(i) for i in points_by_color if grouped.get(i))),
        "working_size": (int(w), int(h)),
        "reason": "zoomed source regions added as bounded high-value detail paths" if appended else "no useful detail paths",
    }
    return new_groups, new_exec, new_seq, meta


def render_detail_zoom_preview(size, meta: dict) -> Image.Image:
    """Render a compact transparent diagnostic overlay for selected zoom ROIs."""
    w, h = map(int, size)
    im = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    if not isinstance(meta, dict) or not meta.get("enabled"):
        return im
    source_size = meta.get("working_size")
    if not source_size:
        return im
    sw, sh = map(int, source_size)
    if sw <= 0 or sh <= 0:
        return im
    draw = ImageDraw.Draw(im)
    for box in meta.get("roi_boxes") or ():
        try:
            x0, y0, x1, y1 = map(int, box)
            px0 = round(x0 * w / sw); py0 = round(y0 * h / sh)
            px1 = round((x1 + 1) * w / sw); py1 = round((y1 + 1) * h / sh)
            draw.rectangle((px0, py0, px1, py1), outline=(255, 255, 255, 220), width=2)
        except Exception:
            continue
    return im
