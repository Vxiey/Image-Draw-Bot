"""Step 25 — Quick Sketch Fill + Contour renderer for Image Draw Bot.

This renderer is a deterministic, deadline-aware specialization that builds on
Image Draw Bot's existing color, Safe Fill Mask, Region Fill Engine, CanvasGuard,
and connected-path systems.  It does not invent a second input engine.

The policy is intentionally recognition-first:
  1) keep a small hue-safe palette,
  2) convert large closed regions into verified contour + bucket-fill actions,
  3) add a simplified dark visible contour after fills,
  4) keep long/structural runs and trim only bounded micro texture,
  5) leave Adaptive Detail Zoom / Deadline Scheduler to spend any remaining time.

Unsafe fills always remain normal connected scanlines.  The target application's
page/canvas zoom is never changed.
"""
from __future__ import annotations

from typing import Any, Sequence
import heapq
import math

QUICK_SKETCH_RENDER_STYLE = "Quick Sketch Fill + Contour"
QUICK_SKETCH_STYLES = ("Simple", "Balanced", "Detailed")
QUICK_SKETCH_FILL_PREFERENCES = ("Safe Fill First", "Balanced", "Scanline Preferred")


def validate_quick_sketch_style(value: str) -> str:
    value = str(value or "Balanced")
    if value not in QUICK_SKETCH_STYLES:
        raise ValueError(f"Quick Sketch style must be one of: {', '.join(QUICK_SKETCH_STYLES)}")
    return value


def validate_fill_preference(value: str) -> str:
    value = str(value or "Safe Fill First")
    if value not in QUICK_SKETCH_FILL_PREFERENCES:
        raise ValueError(f"Quick Sketch fill preference must be one of: {', '.join(QUICK_SKETCH_FILL_PREFERENCES)}")
    return value


def is_quick_sketch(options: dict[str, Any] | None) -> bool:
    if not isinstance(options, dict):
        return False
    return bool(options.get("quick_sketch_auto")) or str(options.get("render_style") or "") == QUICK_SKETCH_RENDER_STYLE


def _deadline_seconds(options: dict[str, Any]) -> float | None:
    if not options.get("time_budget_active") or options.get("unlimited_time"):
        return None
    try:
        value = float(options.get("time_budget_seconds") or options.get("max_seconds") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def resolve_color_cap(options: dict[str, Any]) -> int:
    """Recognition-first color ceiling for Quick Sketch.

    This is only a ceiling. Step 3 dominant-hue protection and Step 5/6 adaptive
    color logic may choose a smaller/larger protected floor when necessary.
    """
    style = validate_quick_sketch_style(options.get("quick_sketch_style", "Balanced"))
    seconds = _deadline_seconds(options)
    if style == "Simple":
        if seconds is not None and seconds <= 65: return 5
        if seconds is not None and seconds <= 82: return 6
        if seconds is not None and seconds <= 155: return 7
        if seconds is not None and seconds <= 305: return 9
        return 10
    if style == "Detailed":
        if seconds is not None and seconds <= 65: return 8
        if seconds is not None and seconds <= 82: return 10
        if seconds is not None and seconds <= 155: return 12
        if seconds is not None and seconds <= 305: return 14
        return 16
    # Balanced
    if seconds is not None and seconds <= 65: return 6
    if seconds is not None and seconds <= 82: return 8
    if seconds is not None and seconds <= 155: return 10
    if seconds is not None and seconds <= 305: return 12
    return 14


def _fill_cap(options: dict[str, Any]) -> int:
    style = validate_quick_sketch_style(options.get("quick_sketch_style", "Balanced"))
    preference = validate_fill_preference(options.get("quick_sketch_fill_preference", "Safe Fill First"))
    seconds = _deadline_seconds(options)
    if seconds is not None and seconds <= 65: base = 12
    elif seconds is not None and seconds <= 82: base = 18
    elif seconds is not None and seconds <= 155: base = 30
    elif seconds is not None and seconds <= 305: base = 44
    else: base = 60
    if style == "Simple": base = round(base * .75)
    elif style == "Detailed": base = round(base * 1.15)
    if preference == "Scanline Preferred": base = max(4, round(base * .45))
    return max(4, min(72, int(base)))


def _micro_cap(options: dict[str, Any]) -> int:
    style = validate_quick_sketch_style(options.get("quick_sketch_style", "Balanced"))
    seconds = _deadline_seconds(options)
    base = 140
    if seconds is not None and seconds <= 65: base = 70
    elif seconds is not None and seconds <= 82: base = 110
    elif seconds is not None and seconds <= 155: base = 190
    elif seconds is not None and seconds <= 305: base = 300
    else: base = 420
    if style == "Simple": base = round(base * .65)
    elif style == "Detailed": base = round(base * 1.45)
    return max(40, int(base))


def apply_quick_sketch_policy(options: dict[str, Any]) -> dict[str, Any]:
    """Apply only renderer/planning knobs; never weaken safety/calibration."""
    if not is_quick_sketch(options):
        return options
    out = dict(options)
    style = validate_quick_sketch_style(out.get("quick_sketch_style", "Balanced"))
    preference = validate_fill_preference(out.get("quick_sketch_fill_preference", "Safe Fill First"))
    cap = resolve_color_cap(out)

    # Quick Sketch is intentionally not Pixel Accurate. If a stale setting was
    # restored, switch to a bounded likeness policy instead of mixing semantics.
    if str(out.get("draw_quality") or "") == "Pixel Accurate":
        out["draw_quality"] = "High likeness"
    out.update({
        "quick_sketch_enabled": True,
        "quick_sketch_style": style,
        "quick_sketch_fill_preference": preference,
        "drawing_mode": "Smart paths (recommended)",
        "smart_paths": True,
        "lines": True,
        "extra_fast": True,
        "extra_fast_v2": True,
        "use_region_fill_engine": True,
        "fill_engine": "Closed regions v2",
        "background_fill": "Off",  # do not waste a short round painting paper/background
        "shape_order": "Fill first",
        "progressive_rendering": "On",
        "color_workflow": "Progressive passes",
        "stroke_optimizer": "Smart merge",
        "color_grouping": "Smart",
        "adaptive_detail": "Balanced" if style != "Detailed" else "Preserve detail",
        "background_simplification": "Strong" if style == "Simple" else ("Balanced" if style == "Balanced" else "Conservative"),
        "planning_resolution": "Standard" if style != "Detailed" else "High",
        "precision": "Normal" if _deadline_seconds(out) is not None and _deadline_seconds(out) <= 82 else out.get("precision", "High"),
        "exact_color_limit_profile_ceiling": int(cap),
        "_quick_sketch_color_cap": int(cap),
    })
    # More candidates are allowed under Safe Fill First, but Region Fill Engine
    # and Safe Fill Mask remain the hard safety authorities.
    out["fill_aggressiveness"] = {
        "Safe Fill First": "Balanced",
        "Balanced": "Safe",
        "Scanline Preferred": "Safe",
    }[preference]
    return out


def _stroke_length(stroke) -> int:
    try:
        x0, y0, x1, y1 = map(int, stroke)
    except Exception:
        return 0
    return abs(x1 - x0) + abs(y1 - y0) + 1


def _trim_micro_texture(groups, cap: int):
    """Drop only bounded 1–2 px texture when a sketch contains too much noise."""
    work = [list(g) for g in (groups or ())]
    cap = max(0, int(cap))
    micro = []
    micro_count = 0
    long_count = 0
    for color, group in enumerate(work):
        for idx, stroke in enumerate(group):
            length = _stroke_length(stroke)
            if length <= 2:
                micro_count += 1
                # The least valuable retained item is first. Prefer longer
                # micro runs, then the earliest colour/local source index.
                item = (length, -color, -idx)
                if len(micro) < cap:
                    heapq.heappush(micro, item)
                elif cap and item > micro[0]:
                    heapq.heapreplace(micro, item)
            else:
                long_count += 1
    if micro_count <= cap:
        return work, 0, micro_count, long_count
    # Prefer 2px segments over isolated dots, then stable source order.
    keep_keys = {(-c, -i) for _l, c, i in micro}
    pruned = 0
    result = []
    for color, group in enumerate(work):
        out = []
        for idx, stroke in enumerate(group):
            if _stroke_length(stroke) <= 2 and (color, idx) not in keep_keys:
                pruned += 1
                continue
            out.append(stroke)
        result.append(out)
    return result, pruned, cap, long_count


def _luminance(rgb: Sequence[int]) -> float:
    r, g, b = (float(v) / 255.0 for v in rgb[:3])
    def lin(v): return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    return .2126*r + .7152*g + .0722*b


def _dark_outline_index(groups, palette_rgb) -> int:
    active = [i for i, g in enumerate(groups or ()) if g and 0 <= i < len(palette_rgb)]
    candidates = active or list(range(len(palette_rgb)))
    if not candidates:
        return 0
    # Avoid choosing almost-white as an outline when any darker color exists.
    candidates = sorted(candidates, key=lambda i: (_luminance(palette_rgb[i]), i))
    for i in candidates:
        if _luminance(palette_rgb[i]) < .78:
            return int(i)
    return int(candidates[0])


def _point_line_distance(p, a, b) -> float:
    px, py = p; ax, ay = a; bx, by = b
    dx, dy = bx-ax, by-ay
    if dx == 0 and dy == 0:
        return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / float(dx*dx + dy*dy)))
    x, y = ax+t*dx, ay+t*dy
    return math.hypot(px-x, py-y)


def _rdp(points, epsilon: float):
    pts = list(points)
    if len(pts) <= 2 or epsilon <= 0:
        return pts
    a, b = pts[0], pts[-1]
    best_i, best_d = -1, 0.0
    for i in range(1, len(pts)-1):
        d = _point_line_distance(pts[i], a, b)
        if d > best_d:
            best_d, best_i = d, i
    if best_i >= 0 and best_d > epsilon:
        left = _rdp(pts[:best_i+1], epsilon)
        right = _rdp(pts[best_i:], epsilon)
        return left[:-1] + right
    return [a, b]


def _visible_contour_strokes(regions, image_size, style: str):
    w, h = max(1, int(image_size[0])), max(1, int(image_size[1]))
    epsilon = {"Simple": 1.65, "Balanced": .85, "Detailed": .30}[style]
    strokes = []
    contour_count = 0
    vertices_before = vertices_after = 0
    for region in regions or ():
        contour = region.get("contour") if isinstance(region, dict) else getattr(region, "contour", ())
        if not contour or len(contour) < 4:
            continue
        pts = []
        for raw in contour:
            try:
                x, y = map(int, raw)
            except Exception:
                continue
            # Visible contour is cosmetic and executes after fill. Keep it one
            # pixel inside the raster bounds so CanvasGuard need not rescue a
            # cell-edge coordinate of exactly width/height.
            p = (max(0, min(w-1, x)), max(0, min(h-1, y)))
            if not pts or p != pts[-1]:
                pts.append(p)
        if len(pts) < 3:
            continue
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        vertices_before += max(0, len(pts)-1)
        open_pts = pts[:-1]
        # Simplify two arcs instead of running RDP over a closed curve whose
        # first/last point are identical.
        if len(open_pts) >= 6 and epsilon > 0:
            mid = len(open_pts)//2
            a = _rdp(open_pts[:mid+1], epsilon)
            b = _rdp(open_pts[mid:] + [open_pts[0]], epsilon)
            simp = a[:-1] + b
        else:
            simp = open_pts + [open_pts[0]]
        clean = []
        for p in simp:
            if not clean or p != clean[-1]: clean.append(p)
        if len(clean) < 3:
            continue
        if clean[0] != clean[-1]: clean.append(clean[0])
        vertices_after += max(0, len(clean)-1)
        added = 0
        for a, b in zip(clean, clean[1:]):
            if a == b: continue
            strokes.append((int(a[0]), int(a[1]), int(b[0]), int(b[1])))
            added += 1
        if added:
            contour_count += 1
    return strokes, contour_count, vertices_before, vertices_after


def _fill_modes(preference: str):
    # Candidate topology can be broad; the separate Region Fill Engine safety
    # layer remains stricter and Safe Fill Mask runs afterwards.
    if preference == "Safe Fill First":
        return "Aggressive", "Balanced"
    if preference == "Scanline Preferred":
        return "Conservative", "Safe"
    return "Balanced", "Safe"


def build_quick_sketch_geometry(image_size, groups, palette_rgb: Sequence[Sequence[int]], fitted,
                                options: dict[str, Any], *, cancelled=lambda: False):
    """Return sketch groups, accepted fill regions and compact metadata."""
    if not is_quick_sketch(options):
        return groups, list(options.get("fill_regions") or ()), {"enabled": False, "reason": "renderer not selected"}
    style = validate_quick_sketch_style(options.get("quick_sketch_style", "Balanced"))
    preference = validate_fill_preference(options.get("quick_sketch_fill_preference", "Safe Fill First"))
    palette = tuple(tuple(map(int, p[:3])) for p in (palette_rgb or ()))
    work = [list(g) for g in (groups or ())]
    source_runs = sum(len(g) for g in work)
    active_before = sum(bool(g) for g in work)
    color_cap = resolve_color_cap(options)

    palette_meta = {"active": False, "before_colors": active_before, "after_colors": active_before}
    if palette and active_before > color_cap:
        try:
            from RealSpeedBudget import reduce_palette_groups
            work, palette_meta = reduce_palette_groups(work, palette, color_cap,
                                                       color_fidelity=str(options.get("color_fidelity") or "Faithful"))
        except InterruptedError:
            raise
        except Exception as error:
            palette_meta = {"active": False, "reason": str(error), "before_colors": active_before, "after_colors": active_before}
    active_after = sum(bool(g) for g in work)

    micro_cap = _micro_cap(options)
    work, micro_pruned, micro_kept, structural_runs = _trim_micro_texture(work, micro_cap)
    runs_after_micro = sum(len(g) for g in work)

    accepted = []
    detector_meta = {}
    region_meta = {}
    mask_meta = {}
    fill_available = bool(options.get("fill_tool_available"))
    if fill_available and bool(options.get("use_region_fill_engine", True)) and palette:
        try:
            from FillOptimizer import detect_fill_regions_from_groups
            from RegionFillEngine import evaluate_region_candidates
            from SafeFillMask import filter_fill_regions_by_source_mask
            detect_mode, risk_mode = _fill_modes(preference)
            candidates, detector_meta = detect_fill_regions_from_groups(
                work, palette, image_size, detect_mode, engine="Closed regions v2",
                max_regions=max(_fill_cap(options)*3, 24), cancelled=cancelled,
                return_meta=True, safe_margin_px=int(options.get("safe_fill_mask_margin_px", 0) or 0))
            risk_options = dict(options, fill_aggressiveness=risk_mode)
            accepted, region_meta = evaluate_region_candidates(
                candidates, image_size, fitted, risk_options, base_meta=detector_meta, cancelled=cancelled)
            accepted, mask_meta = filter_fill_regions_by_source_mask(
                accepted, image_size, margin_px=int(options.get("safe_fill_mask_margin_px", 0) or 0))
            # Recognition-first ranking: largest useful regions first. The hard
            # Safe Fill filters above are already complete at this point.
            accepted = sorted((dict(r) for r in accepted), key=lambda r: (
                float(r.get("estimated_time_saved_seconds", 0) or 0),
                int(r.get("area_pixels", 0) or 0),
                float(r.get("fill_confidence", 0) or 0)), reverse=True)[:_fill_cap(options)]
        except InterruptedError:
            raise
        except Exception as error:
            accepted = []
            region_meta = {"enabled": True, "reason": str(error), "fill_safe_regions": 0}
    elif not fill_available:
        region_meta = {"enabled": True, "reason": "Fill tool is not calibrated/available; using connected scanline fallback.", "fill_safe_regions": 0}

    if accepted:
        from FillOptimizer import remove_filled_region_strokes
        work = remove_filled_region_strokes(work, accepted)

    # Visible contour is a normal post-fill stroke. Runtime Better Fill still
    # draws its exact same-color safety contour first, so this cosmetic outline
    # cannot make an unsafe region safe or change fill topology.
    outline_index = _dark_outline_index(work, palette) if palette else 0
    visible_strokes, outlined_regions, verts_before, verts_after = _visible_contour_strokes(accepted, image_size, style)
    if visible_strokes and 0 <= outline_index < len(work):
        work[outline_index].extend(visible_strokes)

    final_runs = sum(len(g) for g in work)
    filled_pixels = sum(max(0, int(r.get("area_pixels", 0) or 0)) for r in accepted)
    total_pixels = max(1, int(image_size[0]) * int(image_size[1]))
    detector_total = int((detector_meta or {}).get("total_components", 0) or 0)
    fallback_regions = max(0, detector_total - len(accepted))
    removed = max(0, runs_after_micro - (final_runs - len(visible_strokes)))
    reduction = max(0.0, min(100.0, (source_runs - final_runs) / max(1, source_runs) * 100.0))

    meta = {
        "enabled": True,
        "engine": "Quick Sketch Fill + Contour",
        "style": style,
        "fill_preference": preference,
        "fill_tool_available": bool(fill_available),
        "color_cap": int(color_cap),
        "active_colors_before": int(active_before),
        "active_colors_after": int(active_after),
        "palette_reduction": dict(palette_meta or {}),
        "source_runs": int(source_runs),
        "runs_after_micro_trim": int(runs_after_micro),
        "micro_strokes_pruned": int(micro_pruned),
        "micro_strokes_kept": int(micro_kept),
        "structural_runs_kept": int(structural_runs),
        "fill_regions": int(len(accepted)),
        "fill_pixels": int(filled_pixels),
        "fill_coverage_percent": round(filled_pixels / total_pixels * 100.0, 3),
        "fallback_scanline_regions": int(fallback_regions),
        "fill_detector": dict(detector_meta or {}),
        "fill_safety": dict(region_meta or {}),
        "safe_fill_mask": dict(mask_meta or {}),
        "filled_source_runs_removed": int(removed),
        "visible_contour_regions": int(outlined_regions),
        "visible_contour_segments": int(len(visible_strokes)),
        "visible_contour_color_index": int(outline_index),
        "contour_vertices_before": int(verts_before),
        "contour_vertices_after": int(verts_after),
        "final_runs": int(final_runs),
        "stroke_run_reduction_percent": round(reduction, 3),
        "deadline_aware": bool(options.get("time_budget_active")),
        "detail_zoom_handoff": str(options.get("detail_zoom") or "Auto"),
        "safety_policy": "Region Fill Engine + Safe Fill Mask + CanvasGuard remain authoritative",
        "target_app_zoomed": False,
    }
    return work, accepted, meta
