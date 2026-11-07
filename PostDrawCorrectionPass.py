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

from typing import Any, Callable, Sequence
from numbers import Integral
import math
from time import monotonic
import numpy as np
from PIL import Image, ImageFilter

from AccuracyEvaluator import _srgb_to_oklab, normalize_source
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


def _limit_mask(mask: np.ndarray, score: np.ndarray, *, max_pixels: int, max_fraction: float) -> tuple[np.ndarray, int, float]:
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
    values = score[mask]
    # Deterministic top-K threshold; keep all pixels above the cutoff then trim
    # by row-major order if ties still exceed the cap.
    kth = np.partition(values, max(0, selected - pixel_cap))[selected - pixel_cap]
    limited = mask & (score > kth)
    remaining = pixel_cap - int(np.count_nonzero(limited))
    ties = np.flatnonzero(mask & (score == kth))
    limited.reshape(-1)[ties[:remaining]] = True
    return limited, int(np.count_nonzero(limited)), round(pixel_cap * 100.0 / max(1, selected), 2)


def _runs_from_mask(mask: np.ndarray, cancelled=lambda: False) -> list[tuple[int, int, int, int]]:
    rows, cols = np.nonzero(np.asarray(mask, dtype=bool))
    if len(rows) == 0:
        return []
    out: list[tuple[int, int, int, int]] = []
    # Rows from np.nonzero are sorted; scan per row without allocating Python
    # objects per pixel in the main analysis phase.
    start = 0
    while start < len(rows):
        if cancelled():
            raise InterruptedError()
        y = int(rows[start])
        end = start + 1
        while end < len(rows) and int(rows[end]) == y:
            if end % 4096 == 0 and cancelled():
                raise InterruptedError()
            end += 1
        xs = cols[start:end]
        if len(xs):
            x0 = int(xs[0]); prev = int(xs[0])
            for raw in xs[1:]:
                x = int(raw)
                if x == prev + 1:
                    prev = x
                else:
                    out.append((x0, y, prev, y))
                    x0 = prev = x
            out.append((x0, y, prev, y))
        start = end
    return out


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
    limited_mask, selected_pixels, selected_ratio = _limit_mask(
        raw_mask, score, max_pixels=max_pixels, max_fraction=max_area_fraction)
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
    radius=0 if brush==1 and scale==1 else int(math.ceil((brush/2+1)/scale))
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
    selected_pixels=int(np.count_nonzero(limited_mask))
    selected_ratio=100.0*selected_pixels/max(1,limited_mask.size)

    groups: list[list[tuple[int, int, int, int]]] = [[] for _ in palette]
    color_errors: list[tuple[float, int]] = []
    for index in np.unique(wanted[wanted >= 0]):
        index = int(index)
        if cancelled():
            raise InterruptedError()
        cmask = wanted == int(index)
        pixels = int(np.count_nonzero(cmask))
        if pixels <= 0:
            color_errors.append((0.0, index))
            continue
        groups[index] = _runs_from_mask(cmask, cancelled)
        color_errors.append((float(np.mean(score[cmask], dtype=np.float64)), index))

    execution_groups = build_execution_paths(groups, enabled=True, max_rows_per_path=96,
                                             max_points_per_path=520, cancelled=cancelled) or [[] for _ in palette]
    total_paths = sum(len(g) for g in execution_groups)
    color_order = [idx for _, idx in sorted(color_errors, reverse=True) if idx < len(execution_groups) and execution_groups[idx]]

    if total_paths > int(max_paths):
        # Cap per path deterministically, preserving colours with higher average
        # error first.  Paths inside a colour stay in scanline order.
        keep_left = int(max_paths)
        capped = [[] for _ in palette]
        for idx in color_order:
            if keep_left <= 0:
                break
            paths = list(execution_groups[idx])
            take = min(len(paths), keep_left)
            capped[idx] = paths[:take]
            keep_left -= take
        execution_groups = capped
        groups = [[] for _ in palette]
        # Groups are not executed when execution_groups are present; expose only a
        # compact run count for diagnostics after path capping.
        total_paths = sum(len(g) for g in execution_groups)
        capped_flag = True
    else:
        capped_flag = False

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
    estimated_seconds = total_paths * float(seconds_per_path)
    if usable_deadline_seconds is not None and elapsed_seconds is not None:
        remaining = max(0.0, float(usable_deadline_seconds) - float(elapsed_seconds) - (monotonic()-started))
        # Leave at least half a second for release/final safety and never consume
        # more than 80% of the verified leftover budget.
        allowed = max(0.0, (remaining - 0.50) * 0.80)
        if allowed < 1.0:
            return {"enabled": False, "safe": True, "reason": "insufficient leftover budget after final safety reserve", "stores_image_data": False}
        if estimated_seconds > allowed:
            path_cap = min(total_paths, int(math.floor(allowed / seconds_per_path)))
            if path_cap <= 0:
                return {"enabled": False, "safe": True, "reason": "no correction path fits the verified leftover budget", "stores_image_data": False}
            keep_left = path_cap
            capped = [[] for _ in palette]
            for idx in color_order:
                if keep_left <= 0:
                    break
                paths = list(execution_groups[idx])
                take = min(len(paths), keep_left)
                capped[idx] = paths[:take]
                keep_left -= take
            execution_groups = capped
            total_paths = sum(len(g) for g in execution_groups)
            estimated_seconds = total_paths * float(seconds_per_path)
            capped_flag = True

    color_order = [i for i in color_order if execution_groups[i]]
    if capped_flag:
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
        "estimated_seconds": round(float(estimated_seconds), 3),
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
        "acceleration_routes",
    )
    return {k: correction.get(k) for k in keep if k in correction}
