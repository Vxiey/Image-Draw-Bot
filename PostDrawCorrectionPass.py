"""Step 14 — bounded post-draw correction planning.

The correction pass is intentionally conservative.  It consumes only in-memory
images from the just-finished real draw and returns compact correction geometry
plus numeric metadata.  It never saves screenshots, crops, thumbnails, hashes or
source/canvas pixels to disk.  Execution remains the responsibility of
``DrawBot.execute_plan`` so all existing CanvasGuard, colour verification and
profile isolation rules still apply.
"""
from __future__ import annotations
from contextlib import closing
from dataclasses import dataclass

from typing import Any, Callable, Sequence
from numbers import Integral
import math
from time import monotonic
import numpy as np
from PIL import Image, ImageFilter

from AccuracyEvaluator import _srgb_to_oklab, normalize_source
from AxisRegionPlanner import mask_horizontal_runs
from ContinuousPaths import build_execution_paths
from SafeCanvasSnapshotScoring import crop_fitted_canvas, trusted_snapshot_evidence, validated_comparison_size

BACKGROUND_RGB = (255, 255, 255)
MIN_TRUST = {"high", "medium"}
DEFAULT_MAX_PATHS = 120
DEFAULT_MAX_PIXELS = 6000
DEFAULT_MAX_FRACTION = 0.10
DELTA_E_THRESHOLD = 0.115
MISS_THRESHOLD = 20
UNEXPECTED_INK_MAX = 18.0


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _rgb_tuple(value: Any, default: tuple[int, int, int] = BACKGROUND_RGB) -> tuple[int, int, int]:
    try:
        r, g, b = value[:3]
        return (max(0, min(255, int(round(float(r))))),
                max(0, min(255, int(round(float(g))))),
                max(0, min(255, int(round(float(b))))))
    except Exception:
        return tuple(default)


def _palette_tuple(palette_rgb: Sequence[Any] | None) -> tuple[tuple[int, int, int], ...]:
    if palette_rgb is None:
        return ()
    result = []
    for color in palette_rgb:
        if len(result) >= 65_536:
            raise ValueError('Correction palette exceeds the bounded color count.')
        values = tuple(float(c) for c in color)
        if len(values) != 3 or not all(math.isfinite(c) and 0 <= c <= 255 for c in values):
            raise ValueError('Correction palette must contain finite RGB colors in the byte range.')
        result.append(tuple(int(round(c)) for c in values))
    return tuple(result)


def _as_rgb_image(image: Image.Image, size: tuple[int, int] | None = None) -> Image.Image:
    return normalize_source(image, tuple(size) if size is not None else image.size)


def _foreground(arr: np.ndarray, *, background: tuple[int, int, int] = BACKGROUND_RGB,
                threshold: int = MISS_THRESHOLD) -> np.ndarray:
    bg = np.asarray(background, dtype=np.int16).reshape(1, 1, 3)
    return np.max(np.abs(arr.astype(np.int16) - bg), axis=2) > int(threshold)


def _plan_enabled(options: dict[str, Any], post_draw_meta: dict[str, Any] | None,
                  usable_deadline_seconds: float | None, elapsed_seconds: float | None) -> tuple[bool, str]:
    mode = str(options.get("post_draw_correction_pass", options.get("post_draw_corrections", "Auto"))).strip().lower()
    if mode in ("off", "false", "0", "disabled", "never", "none"):
        return False, "post-draw correction pass disabled"
    if bool(options.get("dry_run_sampled")) or bool(options.get("test_run")) or options.get("render_resume_state"):
        return False, "not enabled for dry-run, small-test or resume samples"
    if bool(options.get("paint_current_color")):
        return False, "current-color mode cannot safely select source-matched correction colours"
    if post_draw_meta:
        if not trusted_snapshot_evidence(post_draw_meta):
            return False, "real-result snapshot was not trusted enough"
        if bool(post_draw_meta.get("blank_canvas")):
            return False, "blank canvas snapshot is never corrected automatically"
        unexpected = _float(post_draw_meta.get("unexpected_ink_percent"), 0.0) or 0.0
        if unexpected > UNEXPECTED_INK_MAX:
            return False, "unexpected ink outside the plan is too high for safe correction"
    if usable_deadline_seconds is not None or elapsed_seconds is not None:
        usable = _float(usable_deadline_seconds)
        elapsed = _float(elapsed_seconds)
        if usable is None or elapsed is None or usable <= 0 or elapsed < 0:
            return False, "invalid verified deadline headroom for a correction pass"
        remaining = usable - elapsed
        if remaining < 1.25:
            return False, "not enough verified deadline headroom for a correction pass"
    return True, "enabled"


def correction_needed(post_draw_meta: dict[str, Any] | None, *, visual_gate_percent: float | None = None,
                      coverage_gate_percent: float = 96.0) -> tuple[bool, str]:
    """Return whether Step 13 evidence justifies one bounded correction pass."""
    meta = post_draw_meta if isinstance(post_draw_meta, dict) else {}
    if not meta:
        return False, "no post-draw snapshot evidence"
    if not trusted_snapshot_evidence(meta):
        return False, "snapshot trust below correction threshold"
    if bool(meta.get("blank_canvas")):
        return False, "blank canvas cannot be corrected safely"
    if (_float(meta.get("unexpected_ink_percent"), 0.0) or 0.0) > UNEXPECTED_INK_MAX:
        return False, "unexpected ink outside plan requires manual inspection"
    cov = _float(meta.get("actual_coverage_percent"), None)
    visual = _float(meta.get("visual_accuracy_percent"), None)
    perceptual = _float(meta.get("perceptual_color_accuracy_percent"), None)
    sim = _float(meta.get("actual_vs_simulated_visual_percent"), None)
    gate = _float(visual_gate_percent, None)
    if gate is None:
        gate = _float(meta.get("visual_gate_percent"), None)
    if cov is not None and cov < float(coverage_gate_percent):
        return True, "actual coverage is below the correction gate"
    if gate is not None and visual is not None and visual < gate:
        return True, "actual Visual Accuracy is below the gate"
    if perceptual is not None and perceptual < 88.0 and sim is not None and sim >= 70.0:
        return True, "actual colours differ from the source in otherwise trustworthy geometry"
    return False, "real result is already within correction gates"


def _extract_actual_canvas(*, snapshot: Image.Image | None, actual_canvas: Image.Image | None,
                           area: tuple[int, int, int, int] | None, fitted: tuple[float, float] | None,
                           size: tuple[int, int]) -> tuple[Image.Image, dict[str, Any]]:
    if isinstance(actual_canvas, Image.Image):
        return _as_rgb_image(actual_canvas, size), {"source": "actual_canvas", "geometry_ok": True}
    if not isinstance(snapshot, Image.Image):
        raise ValueError("missing actual canvas image")
    if area is None or fitted is None:
        raise ValueError("snapshot correction needs area and fitted size")
    crop, geometry = crop_fitted_canvas(snapshot, area=tuple(area), fitted=tuple(fitted))
    try:
        return _as_rgb_image(crop, size), {"source": "snapshot", **dict(geometry)}
    finally:
        crop.close()


def _limit_mask(mask: np.ndarray, score: np.ndarray, *, max_pixels: int, max_fraction: float,
                cancelled=lambda: False) -> tuple[np.ndarray, int, float]:
    mask = np.asarray(mask, dtype=bool)
    score = np.asarray(score, dtype=np.float32)
    selected = int(np.count_nonzero(mask))
    if selected <= 0:
        return mask, 0, 0.0
    pixel_cap = min(max(0, int(max_pixels)), max(0, int(math.floor(mask.size * float(max_fraction)))))
    if pixel_cap <= 0:
        return np.zeros_like(mask), 0, 0.0
    if selected <= pixel_cap:
        return mask, selected, 100.0
    # Keep only the strongest cap values across completed blocks. Once full,
    # equal or weaker values cannot raise the cutoff, even on flat colour fills.
    block_size = max(65_536, pixel_cap)
    retained = np.empty(min(selected, pixel_cap + block_size), dtype=score.dtype)
    filled = 0
    kth = -np.inf
    mask_flat = mask.reshape(-1) if mask.flags.c_contiguous else mask.flat
    score_flat = score.reshape(-1) if score.flags.c_contiguous else score.flat
    for start in range(0, mask.size, block_size):
        if cancelled():raise InterruptedError()
        block = slice(start, start + block_size)
        scores = score_flat[block]
        eligible = mask_flat[block]
        if filled == pixel_cap:
            eligible = eligible & (scores > kth)
        new_values = scores[eligible]
        if not new_values.size:continue
        total = filled + new_values.size
        retained[filled:total] = new_values
        if total > pixel_cap:
            cutoff = total - pixel_cap
            retained[:total].partition(cutoff)
            kth = retained[cutoff]
            retained[:pixel_cap] = retained[cutoff:total]
        elif total == pixel_cap:
            kth = retained[:total].min()
        filled = min(total, pixel_cap)
    del retained
    limited = np.empty(mask.shape, dtype=bool, order='C')
    np.greater(score, kth, out=limited)
    limited &= mask
    remaining = pixel_cap - int(np.count_nonzero(limited))
    # A large uniformly missing area may have millions of tied pixels. Walk
    # bounded row-major slices only until the remaining allowance is filled.
    for start in range(0, mask.size, 65_536):
        if cancelled():raise InterruptedError()
        if not remaining:break
        block = slice(start, start + 65_536)
        ties = np.flatnonzero(mask_flat[block] & (score_flat[block] == kth))[:remaining]
        limited.flat[start + ties] = True
        remaining -= len(ties)
    return limited, pixel_cap - remaining, round(pixel_cap * 100.0 / max(1, selected), 2)


def _runs_from_mask(mask: np.ndarray, cancelled=lambda: False) -> list[tuple[int, int, int, int]]:
    return mask_horizontal_runs(mask, cancelled=cancelled)


def _group_candidates(wanted, selected, score, palette_count, *, mean_scores, cancelled):
    """Collect exact row runs for all selected colours in one tiled scan."""
    height, width = wanted.shape
    groups = [[] for _ in range(palette_count)]
    sums = np.zeros(palette_count, dtype=np.float64) if mean_scores else None
    counts = np.zeros(palette_count, dtype=np.intp) if mean_scores else None
    tile_rows = max(1, 65_536 // width)
    for top in range(0, height, tile_rows):
        if cancelled():raise InterruptedError()
        tile = slice(top, top + tile_rows)
        positions = np.flatnonzero(selected[tile])
        if not positions.size:
            continue
        colors = wanted[tile].flat[positions]
        ys, xs = np.divmod(positions, width)
        boundaries = np.flatnonzero((colors[1:] != colors[:-1]) | (ys[1:] != ys[:-1]) |
                                    (xs[1:] != xs[:-1] + 1)) + 1
        starts = np.r_[0, boundaries]
        ends = np.r_[boundaries - 1, len(positions) - 1]
        for color, y, left, right in zip(colors[starts].tolist(), (ys[starts] + top).tolist(),
                                         xs[starts].tolist(), xs[ends].tolist()):
            groups[color].append((left, y, right, y))
        if mean_scores:
            np.add.at(sums, colors, score[tile].flat[positions])
            np.add.at(counts, colors, 1)
    means = ([(float(sums[i] / counts[i]), int(i)) for i in np.flatnonzero(counts)]
             if mean_scores else [])
    return groups, means


@dataclass
class _CorrectionPath:
    color: int
    path: tuple
    pixels: np.ndarray
    gain: float
    cost: Any


def _rank_correction_paths(execution_groups, wanted, gain_by_pixel, model, options, radius,
                           max_paths, seconds_available, cancelled):
    """Greedily insert paths at colour-batch tails, pricing the actual return order."""
    from RasterIdentity import canonical_pixels_from_paths

    height, width = wanted.shape
    candidates = []
    setup_costs = {}
    verified = set(options.get('post_draw_correction_verified_colors') or ())
    verify = (options.get('adaptive_color_verification') or
              options.get('strict_color_verification', True))
    for color, paths in enumerate(execution_groups):
        if not paths:
            continue
        setup_costs[color] = sum(model.color_selection_cost(color))
        if verify and color not in verified:
            setup_costs[color] += model.switch_cost('verification')
        for path in paths:
            if cancelled():
                raise InterruptedError()
            # A serpentine run can retrace its own connector; price all of its
            # travel but credit each centre pixel exactly once.
            points = canonical_pixels_from_paths((path,))
            if not points or any(not (0 <= x < width and 0 <= y < height)
                                 for x, y in points):
                continue
            pixels = np.array(sorted(y * width + x for x, y in points), dtype=np.intp)
            if not np.all(wanted.flat[pixels] == color):
                continue
            gain = math.fsum(gain_by_pixel[int(i)] for i in pixels)
            cost = model.prepare_path_cost(path, cancelled=cancelled)
            candidates.append(_CorrectionPath(color, path, pixels, gain, cost))

    batches = {}
    # For a candidate selected into an earlier colour batch, its end becomes
    # the cursor for the following batch's first path. Reprice just that leg.
    next_batch = {}
    blocked = np.full(wanted.shape, -1, dtype=np.int32) if radius else None
    spent = 0.0
    chosen = 0
    while candidates and chosen < max_paths:
        allowed = seconds_available()
        if spent >= allowed:
            break
        best = None
        best_ratio = -1.0
        last_color = next(reversed(batches), None)
        for i, candidate in enumerate(candidates):
            if i % 128 == 0 and cancelled():
                raise InterruptedError()
            color = candidate.color
            previous_batch = batches.get(color) or batches.get(last_color)
            cursor = previous_batch[-1].path[-1] if previous_batch else None
            increment = candidate.cost.seconds(cursor=cursor)
            if color not in batches:
                increment += setup_costs[color]
            elif color in next_batch:
                following = batches[next_batch[color]][0].cost
                increment += (following.seconds(cursor=candidate.path[-1]) -
                              following.seconds(cursor=cursor))
            ratio = candidate.gain / max(1e-12, increment)
            # Equal ratios retain palette index then original path order.
            if spent + increment <= allowed and ratio > best_ratio:
                best = i, increment
                best_ratio = ratio
        if best is None:
            break
        index, increment = best
        candidate = candidates.pop(index)
        color = candidate.color
        if blocked is not None:
            owners = blocked.flat[candidate.pixels]
            if np.any((owners != -1) & (owners != color)):
                # Drop all conflicts with the current accepted set together.
                # Otherwise each of thousands of rejected paths could trigger
                # another complete scan without changing the selected plan.
                compatible = []
                for i, pending in enumerate(candidates):
                    if i % 128 == 0 and cancelled():
                        raise InterruptedError()
                    existing = blocked.flat[pending.pixels]
                    if np.all((existing == -1) | (existing == pending.color)):
                        compatible.append(pending)
                candidates = compatible
                continue
            # Two conservative brush envelopes with radius r can intersect
            # when their centres are at most 2r apart on both axes.
            reach = radius * 2
            for i, pixel in enumerate(candidate.pixels):
                if i % 128 == 0 and cancelled():
                    raise InterruptedError()
                y, x = divmod(int(pixel), width)
                region = blocked[max(0, y-reach):y+reach+1, max(0, x-reach):x+reach+1]
                # -2 means multiple colours exclude this centre.
                region[:] = np.where((region == -1) | (region == color), color, -2)
        if color not in batches:
            if last_color is not None:
                next_batch[last_color] = color
            batches[color] = []
        batches[color].append(candidate)
        spent += increment
        chosen += 1

    # Planning time can consume deadline headroom. Price the final sequence in
    # delivery order and retain only the prefix that still fits its allowance.
    allowed = seconds_available()
    result = [[] for _ in execution_groups]
    coverage = np.zeros_like(wanted, dtype=bool)
    gain = spent = 0.0
    cursor = None
    for color, batch in batches.items():
        for n, candidate in enumerate(batch):
            if cancelled():
                raise InterruptedError()
            cost = candidate.cost.seconds(cursor=cursor) + (setup_costs[color] if n == 0 else 0.0)
            if spent + cost > allowed:
                return result, coverage, gain, spent, list(batches)
            result[color].append(candidate.path)
            coverage.flat[candidate.pixels] = True
            gain += candidate.gain
            spent += cost
            cursor = candidate.path[-1]
    return result, coverage, gain, spent, list(batches)


def _build_post_draw_correction_plan(*, original_source: Image.Image,
                                    palette_rgb: Sequence[Any],
                                    post_draw_meta: dict[str, Any] | None = None,
                                    snapshot: Image.Image | None = None,
                                    actual_canvas: Image.Image | None = None,
                                    area: tuple[int, int, int, int] | None = None,
                                    fitted: tuple[float, float] | None = None,
                                    comparison_size: tuple[int, int] | None = None,
                                    simulated_final: Image.Image | None = None,
                                    quantized_target: Image.Image | None = None,
                                    options: dict[str, Any] | None = None,
                                    usable_deadline_seconds: float | None = None,
                                    elapsed_seconds: float | None = None,
                                    visual_gate_percent: float | None = None,
                                    estimated_seconds_per_path: float | None = None,
                                    max_paths: int = DEFAULT_MAX_PATHS,
                                    max_pixels: int = DEFAULT_MAX_PIXELS,
                                    max_area_fraction: float = DEFAULT_MAX_FRACTION,
                                    background: tuple[int, int, int] = BACKGROUND_RGB,
                                    cancelled: Callable[[], bool] = lambda: False,
                                    _owned: list) -> dict[str, Any]:
    """Plan one conservative source-relative correction pass.

    The returned ``groups`` and ``execution_groups`` are in source/planning pixel
    coordinates and can be fed through the normal Image Draw Bot execution layer.
    No returned value contains screenshot/canvas/source pixels.
    """
    if cancelled():
        raise InterruptedError()
    started = monotonic()
    options = options if isinstance(options, dict) else {}
    try:
        if any(isinstance(v, bool) or not isinstance(v, Integral) or v < 0 for v in (max_paths, max_pixels)):
            raise ValueError('Correction path and pixel limits must be non-negative integers.')
        fraction = float(max_area_fraction)
        if not math.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError('Correction area fraction must be between zero and one.')
        requested_budget = options.get('post_draw_correction_budget_seconds')
        budget = None
        if requested_budget is not None:
            if (isinstance(requested_budget, bool)
                    or not isinstance(requested_budget, (int, float))
                    or not math.isfinite(requested_budget) or requested_budget < 0):
                raise ValueError('Correction budget must be a finite non-negative number of seconds.')
            budget = float(requested_budget)
            if budget == 0:
                return {"enabled": False, "safe": True, "reason": "correction time budget is zero",
                        "stores_image_data": False, "budget_seconds": 0.0}
            # Bound the greedy search even for manually edited large profile limits.
            max_paths = min(max_paths, DEFAULT_MAX_PATHS)
            max_pixels = min(max_pixels, DEFAULT_MAX_PIXELS)
        palette = _palette_tuple(palette_rgb)
    except (TypeError, ValueError, OverflowError) as error:
        return {"enabled": False, "safe": False, "reason": str(error), "stores_image_data": False}
    if max_paths == 0 or max_pixels == 0 or fraction == 0:
        return {"enabled": False, "safe": True, "reason": "correction cap disables all candidates", "stores_image_data": False}
    if not palette:
        return {"enabled": False, "safe": False, "reason": "palette is empty", "stores_image_data": False}
    ok, reason = _plan_enabled(options, post_draw_meta, usable_deadline_seconds, elapsed_seconds)
    if not ok:
        return {"enabled": False, "safe": False, "reason": reason, "stores_image_data": False}
    needed, needed_reason = correction_needed(post_draw_meta, visual_gate_percent=visual_gate_percent)
    if not needed:
        return {"enabled": False, "safe": True, "reason": needed_reason, "stores_image_data": False}

    if comparison_size is None:
        if isinstance(simulated_final, Image.Image):
            comparison_size = tuple(map(int, simulated_final.size))
        else:
            comparison_size = tuple(map(int, original_source.size))
    size = validated_comparison_size(comparison_size)
    actual, geometry = _extract_actual_canvas(snapshot=snapshot, actual_canvas=actual_canvas, area=area, fitted=fitted, size=size)
    _owned.append(actual)
    if geometry.get('geometry_ok') is not True:
        return {"enabled": False, "safe": False, "reason": "actual canvas geometry was not verified", "stores_image_data": False}
    if cancelled():
        raise InterruptedError()
    source = normalize_source(original_source, size, background=background)
    _owned.append(source)
    src_u8 = np.asarray(source, dtype=np.uint8)
    act_u8 = np.asarray(actual, dtype=np.uint8)
    if src_u8.shape != act_u8.shape:
        raise ValueError("source and actual canvas must share comparison size")

    src = src_u8.astype(np.float32) / 255.0
    act = act_u8.astype(np.float32) / 255.0
    gpu_mode = str(options.get('gpu_mode') or 'Auto')
    try:
        from UniversalGpuAcceleration import perceptual_pair
        src_lab, act_lab, delta, correction_delta_route = perceptual_pair(
            src, act, gpu_mode=gpu_mode, cancelled=cancelled)
    except InterruptedError:
        raise
    except Exception as exc:
        src_lab = _srgb_to_oklab(src); act_lab = _srgb_to_oklab(act)
        delta = np.linalg.norm(src_lab - act_lab, axis=2).astype(np.float32, copy=False)
        correction_delta_route = {'backend_id':'cpu:numpy','backend':'CPU/NumPy','fallback_reason':f'{type(exc).__name__}: {exc}'}
    lum = np.abs(src_lab[..., 0] - act_lab[..., 0]).astype(np.float32, copy=False)
    src_fg = _foreground(src_u8, background=background)
    act_fg = _foreground(act_u8, background=background)
    expected_mask = src_fg
    if isinstance(quantized_target, Image.Image):
        q_image = _as_rgb_image(quantized_target, size)
        _owned.append(q_image)
        q = np.asarray(q_image, dtype=np.uint8)
        q_fg = _foreground(q, background=background)
        # A correction may only target pixels the source and the plan both
        # consider drawable.  This blocks broad repainting outside the planned
        # object when the canvas capture is shifted or stale.
        expected_mask = src_fg & q_fg
    elif isinstance(simulated_final, Image.Image):
        sim_image = _as_rgb_image(simulated_final, size)
        _owned.append(sim_image)
        sim = np.asarray(sim_image, dtype=np.uint8)
        expected_mask = src_fg & _foreground(sim, background=background)

    missing = expected_mask & (~act_fg)
    wrong_colour = expected_mask & act_fg & ((delta >= DELTA_E_THRESHOLD) | (lum >= 0.105))
    raw_mask = missing | wrong_colour
    raw_pixels = int(np.count_nonzero(raw_mask))
    if raw_pixels <= 0:
        return {"enabled": False, "safe": True, "reason": "no bounded source-relative correction pixels found", "stores_image_data": False}

    # Missing pixels are always more important than repainting colour drift.
    score = delta + lum * 0.65 + missing.astype(np.float32) * 0.35
    limited_mask, selected_pixels, _ = _limit_mask(
        raw_mask, score, max_pixels=max_pixels, max_fraction=max_area_fraction, cancelled=cancelled)
    if selected_pixels <= 0:
        return {"enabled": False, "safe": True, "reason": "correction pixel cap removed all candidates", "stores_image_data": False}

    # Assign each selected source pixel to the nearest current plan colour in
    # OKLab.  This honours Step 2/3 hue/tone work without inventing new colours
    # during a post-draw pass.
    flat_src = src_u8.reshape(-1, 3)
    selected_flat = limited_mask.reshape(-1)
    selected_rgb = flat_src[selected_flat].astype(np.float32) / 255.0
    try:
        from UniversalGpuAcceleration import oklab_array
        selected_lab, correction_oklab_route = oklab_array(selected_rgb.reshape(-1, 1, 3), gpu_mode=gpu_mode, cancelled=cancelled)
        palette_lab, correction_palette_lab_route = oklab_array((np.asarray(palette, dtype=np.float32) / 255.0).reshape(-1, 1, 3), gpu_mode=gpu_mode, cancelled=cancelled)
        selected_lab = selected_lab.reshape(-1, 3); palette_lab = palette_lab.reshape(-1, 3)
    except InterruptedError:
        raise
    except Exception:
        selected_lab = _srgb_to_oklab(selected_rgb.reshape(-1, 1, 3)).reshape(-1, 3)
        palette_lab = _srgb_to_oklab((np.asarray(palette, dtype=np.float32) / 255.0).reshape(-1, 1, 3)).reshape(-1, 3)
        correction_oklab_route = {'backend_id':'cpu:numpy','backend':'CPU/NumPy'}
        correction_palette_lab_route = dict(correction_oklab_route)
    # Bound the palette-distance temporary independently of image size.
    wanted_indices=np.empty(len(selected_lab),dtype=np.int32)
    best_error=np.empty(len(selected_lab),dtype=np.float32)
    for start in range(0,len(selected_lab),2048):
        if cancelled():raise InterruptedError()
        values=selected_lab[start:start+2048]
        local_error = np.full(len(values), np.inf, dtype=np.float32)
        local_index = np.zeros(len(values), dtype=np.int32)
        color_step = max(1, 262_144//max(1, len(values)))
        for color_start in range(0, len(palette_lab), color_step):
            if cancelled():raise InterruptedError()
            diff=values[:,None,:]-palette_lab[None,color_start:color_start+color_step,:]
            dist=np.sum(diff*diff,axis=2)+diff[:,:,0]*diff[:,:,0]*.65
            best=np.argmin(dist,axis=1)
            errors=dist[np.arange(len(values)),best]
            improves_tile=errors < local_error
            local_error[improves_tile]=errors[improves_tile]
            local_index[improves_tile]=color_start+best[improves_tile]
        wanted_indices[start:start+len(values)]=local_index
        best_error[start:start+len(values)]=local_error
    before_error=np.sum((src_lab-act_lab)**2,axis=2)+lum*lum*.65
    gains=before_error.reshape(-1)[selected_flat]-best_error
    improves=gains>1e-7
    wanted = np.full(limited_mask.shape, -1, dtype=np.int32)
    wanted.reshape(-1)[selected_flat] = np.where(improves,wanted_indices,-1)
    rejected_non_improving=int(np.count_nonzero(~improves))
    # A brush has area. Every possible touched pixel must be non-worsening,
    # including neighbours that were already correct. A conservative square
    # envelope also covers circular brushes and endpoint rounding.
    brush=_float(options.get('brush_px',1))
    scales=tuple(_float(v) for v in fitted) if fitted is not None else (float(size[0]),float(size[1]))
    if (brush is None or brush<=0 or isinstance(options.get('brush_px'),bool)
            or len(scales)!=2 or any(v is None or v<=0 for v in scales)):
        return {"enabled":False,"safe":False,"reason":"invalid correction brush geometry","stores_image_data":False}
    brush=max(1.0,brush)
    scale=min(scales[0]/size[0],scales[1]/size[1])
    # A single-pixel proof requires identity on both axes, including the
    # actual capture. With an anisotropic fit the smaller scale can still be 1.
    native_capture = (actual_canvas.size == size if isinstance(actual_canvas, Image.Image)
                      else isinstance(snapshot, Image.Image) and snapshot.size == geometry.get('selected_area_size'))
    exact_grid = tuple(scales) == size and native_capture
    radius=0 if brush==1 and exact_grid else int(math.ceil((brush/2+1)/scale))
    if radius>31:
        return {"enabled":False,"safe":True,"reason":"correction brush footprint exceeds bounded verifier","stores_image_data":False}
    rejected_footprint=0
    if radius:
        for index in np.unique(wanted[wanted>=0]):
            if cancelled():raise InterruptedError()
            diff=src_lab-palette_lab[int(index)]
            after=np.sum(diff*diff,axis=2)+diff[:,:,0]*diff[:,:,0]*.65
            allowed=(after<=before_error+1e-7) & expected_mask
            padded=np.pad(allowed, radius, constant_values=False)
            with closing(Image.fromarray(padded.astype(np.uint8)*255)) as padded_image:
                with closing(padded_image.filter(ImageFilter.MinFilter(radius*2+1))) as filtered:
                    eroded=np.asarray(filtered)[radius:-radius,radius:-radius]>0
            reject=(wanted==index)&(~eroded)
            rejected_footprint+=int(np.count_nonzero(reject))
            wanted[reject]=-1
    limited_mask=wanted>=0

    groups, color_errors = _group_candidates(wanted, limited_mask, score, len(palette),
                                              mean_scores=budget is None, cancelled=cancelled)

    execution_groups = build_execution_paths(groups, enabled=True, max_rows_per_path=96,
                                             max_points_per_path=520, cancelled=cancelled) or [[] for _ in palette]
    total_paths = sum(len(g) for g in execution_groups)
    color_order = [idx for _, idx in sorted(color_errors, reverse=True) if idx < len(execution_groups) and execution_groups[idx]]

    ranking_meta = {}
    if budget is not None:
        from ExecutionCostModel import build_cost_model
        model = build_cost_model(dict(options, _execution_scale_x=scales[0] / size[0],
                                      _execution_scale_y=scales[1] / size[1]), size, scales)
        def seconds_available():
            if usable_deadline_seconds is None:
                return budget
            remaining = float(usable_deadline_seconds) - float(elapsed_seconds) - (monotonic() - started)
            return min(budget, max(0.0, (remaining - 0.50) * 0.80))
        gain_by_pixel = dict(zip(np.flatnonzero(selected_flat).tolist(), gains.tolist()))
        baseline_error = float(np.sum(before_error[limited_mask], dtype=np.float64))
        original_paths = total_paths
        execution_groups, limited_mask, gain, estimated_seconds, color_order = _rank_correction_paths(
            execution_groups, wanted, gain_by_pixel, model, options, radius, max_paths,
            seconds_available, cancelled)
        color_order = [i for i in color_order if execution_groups[i]]
        total_paths = sum(len(execution_groups[i]) for i in color_order)
        ranking_meta = {'selection_policy': 'quality_gain_per_second', 'budget_seconds': budget,
                        'predicted_error_reduction': gain,
                        'predicted_error_reduction_percent': min(100.0, 100.0 * gain / baseline_error) if baseline_error else 0.0}
        if not total_paths:
            return {"enabled": False, "safe": True,
                    "reason": "no safe correction path fits the remaining time and quality constraints",
                    "stores_image_data": False, **ranking_meta}
        seconds_per_path = estimated_seconds / total_paths
        capped_flag = total_paths < original_paths
        if capped_flag:
            groups = [[] for _ in palette]
    else:
        if total_paths <= 0:
            return {"enabled": False, "safe": True, "reason": "no improving correction paths survived quality/brush guards and caps", "stores_image_data": False,
                    "rejected_non_improving_pixels":rejected_non_improving,"rejected_brush_footprint_pixels":rejected_footprint}

        seconds_per_path = _float(estimated_seconds_per_path, None)
        if estimated_seconds_per_path is not None and seconds_per_path is None:
            return {"enabled": False, "safe": False, "reason": "correction path timing must be finite and positive", "stores_image_data": False}
        if seconds_per_path is None:
            seconds_per_path = _float((options.get("draw_time_estimate") or {}).get("seconds_per_path"), None) if isinstance(options.get("draw_time_estimate"), dict) else None
        if seconds_per_path is None:
            seconds_per_path = 0.055 if str(options.get("speed", "Balanced")).lower() == "fast" else 0.085
        if seconds_per_path <= 0:
            return {"enabled": False, "safe": False, "reason": "correction path timing must be positive", "stores_image_data": False}
        path_limit = min(max_paths, total_paths)
        if usable_deadline_seconds is not None and elapsed_seconds is not None:
            remaining = float(usable_deadline_seconds) - float(elapsed_seconds) - (monotonic() - started)
            allowed = max(0.0, (remaining - 0.50) * 0.80)
            if allowed < 1.0:
                return {"enabled": False, "safe": True, "reason": "insufficient leftover budget after final safety reserve", "stores_image_data": False}
            if path_limit * seconds_per_path > allowed:
                path_limit = min(path_limit, int(math.floor(allowed / seconds_per_path)))
            if path_limit <= 0:
                return {"enabled": False, "safe": True, "reason": "no correction path fits the verified leftover budget", "stores_image_data": False}

        estimated_seconds = path_limit * seconds_per_path
        capped_flag = path_limit < total_paths
        total_paths = path_limit
        if capped_flag:
            # Legacy callers retain the highest-average-error colours first and
            # keep their scanline order within both the time and path caps.
            capped = [[] for _ in palette]
            for idx in color_order:
                if path_limit == 0:
                    break
                capped[idx] = execution_groups[idx][:path_limit]
                path_limit -= len(capped[idx])
            execution_groups = capped
            color_order = [i for i in color_order if execution_groups[i]]
            from RasterIdentity import rasterize_segment
            covered = np.zeros_like(limited_mask)
            for index in color_order:
                for path in execution_groups[index]:
                    if cancelled():raise InterruptedError()
                    if len(path) == 1:
                        x, y = path[0]
                        covered[y, x] = True
                    for a, b in zip(path, path[1:]):
                        for x, y in rasterize_segment((*a, *b)):
                            covered[y, x] = True
            limited_mask &= covered
            groups = [[] for _ in palette]
    selected_pixels = int(np.count_nonzero(limited_mask))
    selected_ratio = 100.0*selected_pixels/max(1, raw_pixels)
    if cancelled():raise InterruptedError()
    corrected_colors = sum(1 for g in execution_groups if g)
    return {
        "enabled": True,
        "safe": True,
        "reason": needed_reason,
        **ranking_meta,
        "version": 1,
        "method": "bounded source-relative correction from in-memory final canvas snapshot",
        "stores_image_data": False,
        "capture_pixels_persisted": False,
        "image_pixels_persisted": False,
        "privacy": "Only correction geometry and compact metrics are returned; no source/canvas pixels, screenshots, crops, hashes or thumbnails are saved.",
        "comparison_size": tuple(map(int, size)),
        "geometry_ok": bool(geometry.get("geometry_ok", True)),
        "raw_candidate_pixels": int(raw_pixels),
        "rejected_non_improving_pixels": rejected_non_improving,
        "rejected_brush_footprint_pixels": rejected_footprint,
        "correction_footprint_radius": radius,
        "quality_guard": "strict source-relative improvement with non-worsening brush envelope",
        "quality_evidence": "conservative model; actual verification remains separate",
        "selected_correction_pixels": int(selected_pixels),
        "selected_candidate_percent": float(selected_ratio),
        "missing_pixels": int(np.count_nonzero(missing & limited_mask)),
        "wrong_color_pixels": int(np.count_nonzero(wrong_colour & limited_mask)),
        "correction_paths": int(total_paths),
        "corrected_colors": int(corrected_colors),
        "color_order": tuple(int(i) for i in color_order),
        "palette_rgb": tuple(tuple(map(int, c)) for c in palette),
        "groups": groups,
        "execution_groups": execution_groups,
        "estimated_seconds": estimated_seconds if budget is not None else round(float(estimated_seconds), 3),
        "seconds_per_path": round(float(seconds_per_path), 5),
        "capped": bool(capped_flag),
        "max_paths": int(max_paths),
        "max_pixels": int(max_pixels),
        "max_area_fraction": float(max_area_fraction),
        "acceleration_routes": {
            "delta_e": dict(correction_delta_route),
            "selected_oklab": dict(correction_oklab_route),
            "palette_oklab": dict(correction_palette_lab_route),
        },
    }


def build_post_draw_correction_plan(*, original_source: Image.Image,
                                    palette_rgb: Sequence[Any],
                                    post_draw_meta: dict[str, Any] | None = None,
                                    snapshot: Image.Image | None = None,
                                    actual_canvas: Image.Image | None = None,
                                    area: tuple[int, int, int, int] | None = None,
                                    fitted: tuple[float, float] | None = None,
                                    comparison_size: tuple[int, int] | None = None,
                                    simulated_final: Image.Image | None = None,
                                    quantized_target: Image.Image | None = None,
                                    options: dict[str, Any] | None = None,
                                    usable_deadline_seconds: float | None = None,
                                    elapsed_seconds: float | None = None,
                                    visual_gate_percent: float | None = None,
                                    estimated_seconds_per_path: float | None = None,
                                    max_paths: int = DEFAULT_MAX_PATHS,
                                    max_pixels: int = DEFAULT_MAX_PIXELS,
                                    max_area_fraction: float = DEFAULT_MAX_FRACTION,
                                    background: tuple[int, int, int] = BACKGROUND_RGB,
                                    cancelled: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """Plan bounded corrections and release every privately owned image on exit."""
    arguments = locals().copy()
    owned = []
    try:
        return _build_post_draw_correction_plan(**arguments, _owned=owned)
    finally:
        for image in reversed(owned):
            image.close()


def compact_correction_meta(correction: dict[str, Any]) -> dict[str, Any]:
    """Strip path geometry before storing diagnostics in long-lived metadata."""
    keep = (
        "enabled", "safe", "reason", "version", "method", "stores_image_data",
        "rejected_non_improving_pixels", "rejected_brush_footprint_pixels",
        "correction_footprint_radius", "quality_guard", "quality_evidence",
        "capture_pixels_persisted", "image_pixels_persisted", "comparison_size",
        "geometry_ok", "raw_candidate_pixels", "selected_correction_pixels",
        "missing_pixels", "wrong_color_pixels", "correction_paths", "corrected_colors",
        "estimated_seconds", "seconds_per_path", "capped", "max_paths", "max_pixels",
        "max_area_fraction", "executed_paths", "executed_colors", "stopped_early",
        "post_correction_visual_accuracy_percent", "post_correction_actual_coverage_percent",
        "post_correction_trust", "post_correction_confidence_percent",
        "acceleration_routes", "selection_policy", "budget_seconds",
        "predicted_error_reduction", "predicted_error_reduction_percent",
    )
    return {k: correction.get(k) for k in keep if k in correction}
