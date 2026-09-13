"""Profile/style policy for the Extra Fast renderer.

This module is deterministic and local.  It does not inspect target windows or
send input; it only chooses planner settings before Adaptive Region Hybrid builds
the real execution plan.

The purpose is to stop Extra Fast from behaving like one generic scanline preset
for every target and every source type.  Target profiles provide the hard speed /
palette defaults, while Drawing Style provides the geometry/quality bias.
"""
from __future__ import annotations

from typing import Any


_TARGETS: dict[str, dict[str, Any]] = {
    "Microsoft Paint": {
        "name": "Paint region quality",
        "background_simplification": "Conservative",
        "adaptive_detail": "Preserve detail",
        "planning_resolution": "High",
        "color_grouping": "Smart",
        "exact_color_limit_profile_ceiling": 28,
        "precision": "High",
        "phase_priority": ("foundation", "structure", "detail", "correction"),
    },
    "Gartic Phone": {
        "name": "Gartic recognition sprint",
        "background_simplification": "Balanced",
        "adaptive_detail": "Balanced",
        "planning_resolution": "Standard",
        "color_grouping": "Reduced palette",
        "exact_color_limit_profile_ceiling": 12,
        "speed": "Fast",
        "precision": "Normal",
        "phase_priority": ("foundation", "structure", "detail", "correction"),
    },
    "Gartic.io": {
        "name": "Gartic short-round recognition",
        "background_simplification": "Strong",
        "adaptive_detail": "Balanced",
        "planning_resolution": "Standard",
        "color_grouping": "Reduced palette",
        "exact_color_limit_profile_ceiling": 9,
        "speed": "Fast",
        "precision": "Normal",
        "phase_priority": ("structure", "foundation", "detail", "correction"),
    },
    "Skribbl.io Fast": {
        "name": "Skribbl recognition sprint",
        "background_simplification": "Strong",
        "adaptive_detail": "Balanced",
        "planning_resolution": "Standard",
        "color_grouping": "Reduced palette",
        "exact_color_limit_profile_ceiling": 10,
        "speed": "Fast",
        "precision": "Normal",
        "phase_priority": ("structure", "foundation", "detail", "correction"),
    },
    "Skribbl.io": {
        "name": "Skribbl balanced recognition",
        "background_simplification": "Balanced",
        "adaptive_detail": "Preserve detail",
        "planning_resolution": "High",
        "color_grouping": "Smart",
        "exact_color_limit_profile_ceiling": 18,
        "precision": "Normal",
        "phase_priority": ("structure", "foundation", "detail", "correction"),
    },
    "SketchHeads": {
        "name": "SketchHeads recognition sprint",
        "background_simplification": "Strong",
        "adaptive_detail": "Balanced",
        "planning_resolution": "Standard",
        "color_grouping": "Reduced palette",
        "exact_color_limit_profile_ceiling": 10,
        "speed": "Fast",
        "precision": "Normal",
        "phase_priority": ("structure", "foundation", "detail", "correction"),
    },
    "Sketchful.io": {
        "name": "Sketchful balanced recognition",
        "background_simplification": "Balanced",
        "adaptive_detail": "Balanced",
        "planning_resolution": "Standard",
        "color_grouping": "Reduced palette",
        "exact_color_limit_profile_ceiling": 16,
        "phase_priority": ("foundation", "structure", "detail", "correction"),
    },
    "Drawize": {
        "name": "Drawize region-first",
        "background_simplification": "Balanced",
        "adaptive_detail": "Balanced",
        "planning_resolution": "Standard",
        "color_grouping": "Smart",
        "exact_color_limit_profile_ceiling": 16,
        "phase_priority": ("foundation", "structure", "detail", "correction"),
    },
    "Kleki": {
        "name": "Kleki quality-fast",
        "background_simplification": "Conservative",
        "adaptive_detail": "Preserve detail",
        "planning_resolution": "High",
        "color_grouping": "Smart",
        "exact_color_limit_profile_ceiling": 24,
        "precision": "High",
        "phase_priority": ("structure", "foundation", "detail", "correction"),
    },
    "Magma": {
        "name": "Magma quality-fast",
        "background_simplification": "Conservative",
        "adaptive_detail": "Preserve detail",
        "planning_resolution": "High",
        "color_grouping": "Smart",
        "exact_color_limit_profile_ceiling": 24,
        "precision": "High",
        "phase_priority": ("structure", "foundation", "detail", "correction"),
    },
    "Other drawing app": {
        "name": "Generic recognition-first",
        "background_simplification": "Balanced",
        "adaptive_detail": "Auto",
        "planning_resolution": "Standard",
        "color_grouping": "Smart",
        "exact_color_limit_profile_ceiling": 18,
        "phase_priority": ("foundation", "structure", "detail", "correction"),
    },
}


def _style_policy(style: str) -> dict[str, Any]:
    style = str(style or "Auto")
    if style == "Pixel Art":
        return {
            "engine_kind": "pixel-components",
            "draw_quality": "Pixel Accurate",
            "render_style": "Standard / pixel",
            "background_simplification": "Off",
            "adaptive_detail": "Off",
            "detail_zoom": "Off",
            "color_grouping": "Accurate",
            "color_fidelity": "Exact",
            "stroke_optimizer": "Travel only",
            "planning_resolution": "High",
            "max_stroke_cap": "Unlimited",
            "recognition_priority": "exact pixel regions and palette boundaries",
            "phase_priority": ("structure", "foundation", "detail", "correction"),
        }
    if style == "Line Art":
        return {
            "engine_kind": "contour-sketch",
            "outline": True,
            "sketch_detail": "Balanced",
            "background_fill": "Off",
            "background_simplification": "Off",
            "adaptive_detail": "Auto",
            "detail_zoom": "Auto",
            "recognition_priority": "continuous contours before micro detail",
            "phase_priority": ("structure", "detail", "foundation", "correction"),
        }
    if style in ("Logo / Flat Graphic", "Cartoon / Illustration"):
        return {
            "engine_kind": "regional-hybrid",
            "draw_quality": "High likeness",
            "render_style": "Standard / pixel",
            "drawing_mode": "Smart paths (recommended)",
            "smart_paths": True,
            "shape_order": "Fill first",
            "background_simplification": "Balanced",
            "adaptive_detail": "Balanced",
            "recognition_priority": "large color regions and silhouettes before detail",
            "phase_priority": ("foundation", "structure", "detail", "correction"),
        }
    if style == "Portrait":
        return {
            "engine_kind": "regional-hybrid",
            "draw_quality": "High likeness",
            "render_style": "Standard / pixel",
            "drawing_mode": "Smart paths (recommended)",
            "smart_paths": True,
            "background_simplification": "Balanced",
            "adaptive_detail": "Preserve detail",
            "detail_zoom": "Auto",
            "recognition_priority": "face-scale structure, high-contrast detail and broad tone regions",
            "phase_priority": ("structure", "foundation", "detail", "correction"),
        }
    if style == "Photo / Shaded":
        return {
            "engine_kind": "regional-hybrid",
            "draw_quality": "High likeness",
            "render_style": "Standard / pixel",
            "drawing_mode": "Smart paths (recommended)",
            "smart_paths": True,
            "background_simplification": "Balanced",
            "adaptive_detail": "Balanced",
            "detail_zoom": "Auto",
            "recognition_priority": "recognisable structure and broad tones before texture",
            "phase_priority": ("structure", "foundation", "detail", "correction"),
        }
    return {
        "engine_kind": "regional-hybrid",
        "recognition_priority": "large safe regions and structure before optional detail",
    }


def _target_policy(profile_name: str) -> dict[str, Any]:
    return dict(_TARGETS.get(str(profile_name or ""), _TARGETS["Other drawing app"]))


def apply_extra_fast_profile_policy(options: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply Extra Fast target/style defaults and return explanatory metadata.

    The preset is authoritative for renderer knobs, but it never writes native
    coordinates, calibration, arming, CanvasGuard or target-window state.
    """
    out = dict(options or {})
    profile_name = str(out.get("profile_name") or "Other drawing app")
    requested_style = str(out.get("drawing_style") or "Auto")
    style = str(out.get("drawing_style_resolved") or requested_style or "Auto")
    target = _target_policy(profile_name)
    style_policy = _style_policy(style)

    # Unknown/generic Auto callers historically keep adaptive_detail=Auto.  Do
    # not turn the default metrics used by non-image tests/legacy callers into a
    # fake Photo profile.  Real target profiles and explicit Drawing Style
    # selections still get the strong binding below.
    generic_auto = profile_name == "Other drawing app" and requested_style == "Auto"
    if generic_auto:
        style_policy = {
            "engine_kind": "regional-hybrid",
            "recognition_priority": "large safe regions and structure before optional detail",
        }

    phase_priority = tuple(style_policy.get("phase_priority") or target.get("phase_priority") or
                           ("foundation", "structure", "detail", "correction"))

    # Target defaults are applied first; style-specific geometry then wins where
    # required (especially Pixel Art and Line Art).
    for key, value in target.items():
        if key in ("name", "phase_priority"):
            continue
        out[key] = value
    for key, value in style_policy.items():
        if key in ("engine_kind", "recognition_priority", "phase_priority"):
            continue
        out[key] = value

    fill_available = bool(out.get("fill_tool_available"))
    if not fill_available:
        out["background_fill"] = "Off"
    elif style != "Line Art":
        out["background_fill"] = "Balanced"
    out["fill_engine"] = "Closed regions v2"
    out["color_workflow"] = "Progressive passes"
    out["progressive_rendering"] = "On"
    out["lines"] = True
    out["extra_fast_recognition_first"] = True
    out["extra_fast_phase_priority"] = phase_priority

    engine_kind = str(style_policy.get("engine_kind") or "regional-hybrid")
    if engine_kind == "contour-sketch":
        engine = "Extra Fast contour sketch: connected structure before detail"
    elif engine_kind == "pixel-components":
        engine = "Extra Fast pixel components: exact regions and boundaries before travel optimization"
    else:
        engine = "Extra Fast regional hybrid: Fill + verified multi-brush regions + structure/detail recovery"
        if not fill_available:
            engine += " (calibrate Fill to enable buckets)"

    meta = {
        "enabled": True,
        "version": 1,
        "recognition_first": True,
        "recognition_badge": "RECOGNITION FIRST",
        "target_profile": profile_name,
        "target_policy": str(target.get("name") or "Generic recognition-first"),
        "drawing_style": style,
        "drawing_style_requested": requested_style,
        "engine_kind": engine_kind,
        "engine": engine,
        "recognition_priority": str(style_policy.get("recognition_priority") or
                                      "large safe regions and structure before optional detail"),
        "phase_priority": phase_priority,
        "fill_policy": "safe closed-region Fill" if fill_available and style != "Line Art" else "connected-region fallback",
        "palette_policy": str(out.get("color_grouping") or "Smart"),
        "color_ceiling": out.get("exact_color_limit_profile_ceiling"),
        "eta_model": "final execution sequence: paths + travel + color + brush + Fill + verification",
        "reason": "Extra Fast is bound to target profile + drawing style instead of one generic scanline policy.",
    }

    # DrawBot already prints extra_fast_v2_meta in the plan/session summary.
    # Populate it early so recognition-first strategy is visible even when the
    # Adaptive Region Hybrid route owns geometry and never uses legacy ExtraFast2.
    legacy_meta = dict(out.get("extra_fast_v2_meta") or {})
    legacy_meta.update({
        "enabled": True,
        "path_policy": f"RECOGNITION-FIRST/{profile_name}/{style}/{engine_kind}",
        "recognition_first": True,
        "recognition_badge": "RECOGNITION FIRST",
        "profile_binding": profile_name,
        "style_binding": style,
        "eta_model": meta["eta_model"],
    })
    out["extra_fast_v2_meta"] = legacy_meta
    out["extra_fast_strategy_meta"] = meta
    return out, meta


def strategy_log_line(meta: dict[str, Any] | None) -> str:
    if not isinstance(meta, dict) or not meta.get("enabled"):
        return "Extra Fast strategy: unavailable"
    phases = " > ".join(str(v) for v in (meta.get("phase_priority") or ()))
    return (
        f"Extra Fast strategy: {meta.get('recognition_badge','RECOGNITION FIRST')} | "
        f"profile={meta.get('target_profile','?')} style={meta.get('drawing_style','?')} "
        f"engine={meta.get('engine_kind','?')} phases={phases or '?'} | ETA={meta.get('eta_model','?')}"
    )
