"""Step 29 — Hybrid Renderer 3.0 for Image Draw Bot.

Hybrid Renderer 3.0 is a deterministic orchestration layer.  It does not create
native input, screen coordinates or calibration state.  Instead it analyses the
source image with bounded Pillow/NumPy statistics and routes each specialised
mode into Image Draw Bot's existing, tested geometry engines:

* Pixel Art -> Pixel Accurate / full-resolution PixelMap
* Icon / Logo -> Quick Sketch safe Fill + visible contour
* Line Art -> contour-first Shape Paths / black-outline pipeline
* Portrait -> PortraitPlanner for single-colour targets, high-detail colour
  planning otherwise
* Shaded Object -> progressive fill/shape/detail planning
* Deadline Silhouette -> recognition-first Quick Sketch with a strict path cap

Auto Hybrid may select Pixel Art, Icon / Logo, Line Art, Shaded Object or
Deadline Silhouette.  It deliberately does not claim to recognise human faces;
Portrait remains an explicit user choice.

CanvasGuard, FinalMouseGuard, target locks, calibration, tool coordinates,
preflight, dry-run and input authorisation are outside this module and remain
fully authoritative.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

import numpy as np
from PIL import Image

HYBRID_RENDER_STYLE = "Hybrid Renderer 3.0"
HYBRID_RENDERER_VERSION = "3.0"
HYBRID_MODES = (
    "Auto Hybrid",
    "Pixel Art",
    "Icon / Logo",
    "Line Art",
    "Portrait",
    "Shaded Object",
    "Deadline Silhouette",
)

# These keys are documented here so tests can prove the renderer never weakens
# native-input/safety state.  apply_hybrid_policy() never writes any of them.
SAFETY_STATE_KEYS = frozenset({
    "armed", "full_draw_armed", "draw_immediately", "auto_draw",
    "target_handle", "target_window", "target_client_rect",
    "target_lock_passed", "target_lock_signature", "target_lock_fingerprint",
    "small_test_passed", "safety_preflight_passed", "dry_run_passed",
    "corners", "canvas_polygon", "palette_positions", "tool_actions",
    "canvas_guard_enabled", "strict_runtime_safety", "start_authorization",
})


@dataclass(frozen=True)
class HybridSourceAnalysis:
    width: int
    height: int
    sampled_width: int
    sampled_height: int
    alpha_fraction: float
    white_fraction: float
    chroma_fraction: float
    edge_density: float
    mean_gradient: float
    luminance_std: float
    quantized_colors: int
    dominant8_fraction: float
    flatness_score: float
    line_art_score: float
    pixel_art_score: float

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in tuple(data.items()):
            if isinstance(value, float):
                data[key] = round(value, 5)
        return data


def validate_hybrid_mode(value: str) -> str:
    value = str(value or "Auto Hybrid")
    if value not in HYBRID_MODES:
        raise ValueError("Hybrid mode must be one of: " + ", ".join(HYBRID_MODES))
    return value


def is_hybrid_renderer(options: dict[str, Any] | None) -> bool:
    if not isinstance(options, dict):
        return False
    return bool(options.get("hybrid_renderer_active")) or str(options.get("render_style") or "") == HYBRID_RENDER_STYLE


def _deadline_seconds(options: dict[str, Any]) -> float | None:
    if options.get("unlimited_time") or str(options.get("time_budget_mode") or "") == "Unlimited":
        return None
    if not options.get("time_budget_active"):
        return None
    for key in ("deadline_render_budget_seconds", "time_budget_seconds", "max_seconds"):
        try:
            value = float(options.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def analyze_source(image: Image.Image, *, cancelled: Callable[[], bool] = lambda: False) -> HybridSourceAnalysis:
    """Return bounded deterministic source statistics used by Auto Hybrid.

    The image is never uploaded and no object/face recognition is performed.
    Analysis is capped to a 160px thumbnail so UI preview and planning remain
    responsive on very large source images.
    """
    if not isinstance(image, Image.Image):
        raise TypeError("Hybrid Renderer 3.0 needs a Pillow image.")
    if cancelled():
        raise InterruptedError()

    width, height = map(int, image.size)
    if width <= 0 or height <= 0:
        raise ValueError("Hybrid Renderer 3.0 cannot analyse an empty image.")

    rgba = image.convert("RGBA")
    sample = rgba.copy()
    sample.thumbnail((160, 160), Image.Resampling.NEAREST)
    if cancelled():
        raise InterruptedError()

    arr_rgba = np.asarray(sample, dtype=np.uint8)
    alpha = arr_rgba[:, :, 3].astype(np.float32)
    alpha_fraction = float(np.mean(alpha < 250.0, dtype=np.float64))

    # Composite transparency onto white exactly like the normal drawing path.
    rgb = arr_rgba[:, :, :3].astype(np.float32)
    a = (alpha / 255.0)[:, :, None]
    rgb = np.rint(rgb * a + 255.0 * (1.0 - a)).astype(np.uint8)
    rgb16 = rgb.astype(np.int16)

    white_fraction = float(np.mean(np.min(rgb16, axis=2) >= 238, dtype=np.float64))
    chroma = np.max(rgb16, axis=2) - np.min(rgb16, axis=2)
    chroma_fraction = float(np.mean(chroma >= 28, dtype=np.float64))

    # Integer luminance is sufficient for structural classification and avoids
    # importing the heavier colour engine into this lightweight policy module.
    # Weighted channels can sum to 65,280. int16 wraps bright pixels negative
    # and makes a white/black edge nearly disappear in the structural metrics.
    rgb32 = rgb.astype(np.int32)
    lum = (54 * rgb32[:, :, 0] + 183 * rgb32[:, :, 1] + 19 * rgb32[:, :, 2]) / 256.0
    luminance_std = float(np.std(lum, dtype=np.float64) / 255.0)

    gx = np.abs(np.diff(lum, axis=1)) if lum.shape[1] > 1 else np.zeros((lum.shape[0], 0))
    gy = np.abs(np.diff(lum, axis=0)) if lum.shape[0] > 1 else np.zeros((0, lum.shape[1]))
    edge_total = int(gx.size + gy.size)
    if edge_total:
        edge_hits = int(np.count_nonzero(gx >= 24.0) + np.count_nonzero(gy >= 24.0))
        edge_density = float(edge_hits / edge_total)
        mean_gradient = float((float(gx.sum()) + float(gy.sum())) / edge_total / 255.0)
    else:
        edge_density = mean_gradient = 0.0

    # 5-bit-ish coarse occupancy.  This is a palette/texture statistic, not
    # semantic recognition.  Ignore one-off antialias/noise bins.
    bins = (rgb.astype(np.uint16) // 32).astype(np.int32)
    codes = bins[:, :, 0] * 64 + bins[:, :, 1] * 8 + bins[:, :, 2]
    hist = np.bincount(codes.ravel(), minlength=512)
    pixels = max(1, int(hist.sum()))
    occupancy_floor = max(2, int(round(pixels * 0.0008)))
    quantized_colors = int(np.count_nonzero(hist >= occupancy_floor))
    dominant8_fraction = float(np.sort(hist)[-8:].sum() / pixels)

    flatness_score = max(0.0, min(1.0,
        dominant8_fraction * 0.72 + (1.0 - min(1.0, mean_gradient * 3.0)) * 0.28))
    line_art_score = max(0.0, min(1.0,
        white_fraction * 0.62 + (1.0 - min(1.0, chroma_fraction * 4.0)) * 0.23
        + min(1.0, edge_density * 4.0) * 0.15))
    small_source = max(width, height) <= 256
    pixel_art_score = max(0.0, min(1.0,
        (0.34 if small_source else 0.0)
        + max(0.0, 1.0 - min(1.0, quantized_colors / 36.0)) * 0.31
        + dominant8_fraction * 0.25
        + min(1.0, edge_density * 2.0) * 0.10))

    return HybridSourceAnalysis(
        width=width, height=height,
        sampled_width=int(sample.size[0]), sampled_height=int(sample.size[1]),
        alpha_fraction=alpha_fraction, white_fraction=white_fraction,
        chroma_fraction=chroma_fraction, edge_density=edge_density,
        mean_gradient=mean_gradient, luminance_std=luminance_std,
        quantized_colors=quantized_colors, dominant8_fraction=dominant8_fraction,
        flatness_score=flatness_score, line_art_score=line_art_score,
        pixel_art_score=pixel_art_score,
    )


def resolve_hybrid_mode(image: Image.Image, options: dict[str, Any], *,
                        analysis: HybridSourceAnalysis | None = None,
                        cancelled: Callable[[], bool] = lambda: False) -> tuple[str, HybridSourceAnalysis]:
    requested = validate_hybrid_mode(options.get("hybrid_mode", "Auto Hybrid"))
    analysis = analysis or analyze_source(image, cancelled=cancelled)
    if requested != "Auto Hybrid":
        return requested, analysis

    deadline = _deadline_seconds(options)

    # Preserve intentionally sparse line art even under a short deadline; its
    # contour representation is already cheaper than a silhouette conversion.
    if analysis.line_art_score >= 0.78 and analysis.white_fraction >= 0.58:
        return "Line Art", analysis

    # Short-round recognition wins for ordinary coloured/texture sources.
    if deadline is not None and deadline <= 55.0:
        return "Deadline Silhouette", analysis

    # Pixel Art is intentionally strict because icons/logos are often small too.
    if (max(analysis.width, analysis.height) <= 256 and
            analysis.quantized_colors <= 28 and
            analysis.dominant8_fraction >= 0.78 and
            analysis.pixel_art_score >= 0.68):
        return "Pixel Art", analysis

    if (analysis.quantized_colors <= 36 and analysis.dominant8_fraction >= 0.88 and
            analysis.flatness_score >= 0.78):
        return "Icon / Logo", analysis

    # Portrait is never auto-selected: source statistics cannot truthfully prove
    # that a face/person is present without semantic recognition.
    return "Shaded Object", analysis


def pass_plan(mode: str) -> tuple[str, ...]:
    mode = validate_hybrid_mode(mode)
    return {
        "Auto Hybrid": ("analyse", "resolve specialised mode"),
        "Pixel Art": ("full-resolution pixel map", "lossless runs", "micro-detail correction"),
        "Icon / Logo": ("safe closed-region fill", "outer contour", "structural runs", "detail correction"),
        "Line Art": ("outer contour", "structural line paths", "critical micro-lines"),
        "Portrait": ("large tones", "feature edges", "shading/detail", "correction pass"),
        "Shaded Object": ("base regions", "shadow/highlight shapes", "contour", "detail pass"),
        "Deadline Silhouette": ("recognisable silhouette", "outer contour", "critical marks"),
    }[mode]


def _apply_mode_policy(out: dict[str, Any], mode: str) -> None:
    """Write renderer/planner options only.  Never write SAFETY_STATE_KEYS."""
    if mode == "Pixel Art":
        out.update({
            "render_style": "Standard / pixel",
            "draw_quality": "Pixel Accurate",
            "quality": "Maximum detail",
            "planning_resolution": "Extreme",
            "background_fill": "Off",
            "background_simplification": "Off",
            "color_grouping": "Accurate",
            "color_workflow": "Finish color first",
            "stroke_optimizer": "Travel only",
            "adaptive_detail": "Off",
            "progressive_rendering": "On",
            "max_stroke_cap": "Unlimited",
            "target_stroke_count": "Auto",
        })
        return

    if mode == "Icon / Logo":
        out.update({
            "render_style": "Quick Sketch Fill + Contour",
            "quick_sketch_style": "Detailed",
            "quick_sketch_fill_preference": "Safe Fill First",
            "drawing_mode": "Shape paths",
            "smart_paths": False,
            "lines": True,
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "draw_quality": "High likeness",
            "quality": "High detail",
            "planning_resolution": "High",
            "background_fill": "Off",
            "fill_engine": "Closed regions v2",
            "use_region_fill_engine": True,
            "background_simplification": "Conservative",
            "color_grouping": "Smart",
            "color_workflow": "Progressive passes",
            "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Preserve detail",
            "progressive_rendering": "On",
        })
        return

    if mode == "Line Art":
        out.update({
            "render_style": "Standard / pixel",
            "drawing_mode": "Shape paths",
            "smart_paths": False,
            "lines": True,
            "shape_model": "Better shapes v2",
            "shape_order": "Contour first",
            "outline": True,
            "draw_quality": "High likeness",
            "quality": "High detail",
            "planning_resolution": "High",
            "background_fill": "Off",
            "background_simplification": "Off",
            "color_grouping": "Accurate",
            "color_layers": "Off",
            "stroke_optimizer": "Travel only",
            "adaptive_detail": "Preserve detail",
            "progressive_rendering": "On",
        })
        return

    if mode == "Portrait":
        single_colour = bool(out.get("paint_current_color")) and not bool(out.get("erase_mode"))
        out.update({
            "render_style": "Portrait / shaded" if single_colour else "Standard / pixel",
            "drawing_mode": "Smart paths (recommended)",
            "smart_paths": True,
            "lines": True,
            "draw_quality": "Maximum likeness",
            "quality": "Maximum detail",
            "planning_resolution": "High",
            "background_simplification": "Conservative",
            "color_grouping": "Smart",
            "color_workflow": "Progressive passes",
            "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Preserve detail",
            "detail_zoom": "2x",
            "progressive_rendering": "On",
            "portrait_focus": True,
        })
        return

    if mode == "Shaded Object":
        out.update({
            "render_style": "Standard / pixel",
            "drawing_mode": "Shape paths",
            "smart_paths": False,
            "lines": True,
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "draw_quality": "High likeness",
            "quality": "High detail",
            "planning_resolution": "High",
            "background_fill": "Conservative",
            "fill_engine": "Closed regions v2",
            "use_region_fill_engine": True,
            "background_simplification": "Balanced",
            "color_grouping": "Smart",
            "color_workflow": "Progressive passes",
            "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Preserve detail",
            "detail_zoom": "Auto",
            "progressive_rendering": "On",
        })
        return

    if mode == "Deadline Silhouette":
        out.update({
            "render_style": "Quick Sketch Fill + Contour",
            "quick_sketch_style": "Simple",
            "quick_sketch_fill_preference": "Safe Fill First",
            "drawing_mode": "Smart paths (recommended)",
            "smart_paths": True,
            "lines": True,
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "draw_quality": "Balanced",
            "quality": "Quick sketch",
            "planning_resolution": "Standard",
            "background_fill": "Off",
            "fill_engine": "Closed regions v2",
            "use_region_fill_engine": True,
            "background_simplification": "Strong",
            "color_grouping": "Reduced palette",
            "color_workflow": "Progressive passes",
            "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Strong simplify",
            "progressive_rendering": "On",
            "max_stroke_cap": "1000",
            "target_stroke_count": "800",
            "target_stroke_count_resolved": 800,
            "exact_color_limit_profile_ceiling": 6,
        })
        return

    raise ValueError(f"Unsupported Hybrid Renderer mode: {mode}")


def apply_hybrid_policy(image: Image.Image, options: dict[str, Any], *,
                        cancelled: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """Resolve and apply Hybrid Renderer 3.0 without weakening safety state."""
    if not is_hybrid_renderer(options):
        return options
    source = dict(options)
    before_safety = {key: source.get(key) for key in SAFETY_STATE_KEYS if key in source}
    requested = validate_hybrid_mode(source.get("hybrid_mode", "Auto Hybrid"))
    resolved, analysis = resolve_hybrid_mode(image, source, cancelled=cancelled)

    out = dict(source)
    _apply_mode_policy(out, resolved)

    # Prevent the older generic AutoDrawing selector from replacing an explicit
    # Hybrid Renderer decision later in make_plan().
    out["auto_engine_resolved"] = True
    out["hybrid_renderer_active"] = True
    out["hybrid_mode"] = requested
    out["hybrid_mode_resolved"] = resolved
    out["hybrid_renderer_meta"] = {
        "enabled": True,
        "engine": "Hybrid Renderer 3.0",
        "step": 29,
        "version": HYBRID_RENDERER_VERSION,
        "requested_mode": requested,
        "resolved_mode": resolved,
        "base_renderer": out.get("render_style"),
        "passes": list(pass_plan(resolved)),
        "deadline_seconds": _deadline_seconds(source),
        "analysis": analysis.as_dict(),
        "semantic_ai_used": False,
        "ocr_used": False,
        "native_input_changed": False,
        "safety_policy": "Existing CanvasGuard / target-lock / preflight / dry-run / calibration remain authoritative",
    }

    # Defensive invariant: if a future edit accidentally writes a native safety
    # field, fail planning rather than silently weakening it.
    after_safety = {key: out.get(key) for key in before_safety}
    if after_safety != before_safety:
        raise RuntimeError("Hybrid Renderer 3.0 attempted to change protected safety/input state.")
    return out


def format_hybrid_summary(meta: dict[str, Any] | None) -> str:
    meta = meta if isinstance(meta, dict) else {}
    if not meta.get("enabled"):
        return "Hybrid Renderer 3.0: inactive"
    mode = str(meta.get("resolved_mode") or "?")
    passes = meta.get("passes") if isinstance(meta.get("passes"), list) else []
    tail = " → ".join(str(x) for x in passes[:4])
    return f"Hybrid Renderer 3.0 · {mode}" + (f" · {tail}" if tail else "")
