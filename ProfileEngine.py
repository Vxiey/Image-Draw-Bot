"""Profile Engine v2: profile-specific renderer policies.

This module is pure planning policy.  It never touches Tk, the mouse, files,
calibration, target windows or native input.  A policy only rewrites renderer
options before validation/planning; Image Draw Bot's existing safety gates remain
independent and authoritative.
"""
from __future__ import annotations

PROFILE_ENGINE_MODES = ("Auto", "Manual settings")
UNLIMITED_TIME_MODES = frozenset(("Unlimited", "Unlimited / Accuracy"))
PIXEL_ACCURATE_SETTINGS = frozenset((
    "draw_quality", "quality", "planning_resolution",
    "background_simplification", "color_grouping", "stroke_optimizer",
    "adaptive_detail", "time_budget_mode", "target_stroke_count",
    "max_stroke_cap", "progressive_rendering", "color_rendering", "color_fidelity",
))


def profile_setting_is_locked(key: str, options: dict) -> bool:
    """Keep explicit accuracy/budget choices through every automatic preset pass."""
    budget=options.get(key)
    if key == "time_budget_mode" and isinstance(budget,str) and budget in UNLIMITED_TIME_MODES:
        return True
    return options.get("draw_quality") == "Pixel Accurate" and key in PIXEL_ACCURATE_SETTINGS


def validate_profile_engine(value: str) -> str:
    if value not in PROFILE_ENGINE_MODES:
        raise ValueError("Profile policy must be Auto or Manual settings.")
    return value


# Renderer-only fields.  Intentionally excludes target/input state, calibration,
# brush width, coordinates, arming, locks and native mouse behavior.
_POLICIES = {
    "Microsoft Paint": {
        "name": "Paint quality + verification",
        "goal": "Exact/perceptual colors, closed-region fill, strong shapes and full batch verification.",
        "overrides": {
            "mode": "Shape paths",
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "progressive_rendering": "On",
            "quality": "High detail",
            "speed": "Balanced",
            "precision": "High",
            "draw_quality": "Maximum likeness",
            "planning_resolution": "High",
            "background_fill": "Balanced",
            "fill_engine": "Closed regions v2",
            "background_simplification": "Conservative",
            "color_grouping": "Smart",
            "color_workflow": "Finish color first",
            "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Preserve detail",
            "visual_verification": "Strict",
            "color_rendering": "Perceptual match",
            "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)",
            "exact_color_limit": "Auto",
            "exact_color_limit_profile_ceiling": 32,
            "time_budget_mode": "Manual",
            "target_stroke_count": "Auto",
            "max_stroke_cap": "10000",
            "planning_watchdog": "On",
            "resource_scheduler": "Auto",
            "edge_behavior": "Adaptive Clip",
        },
    },
    "Skribbl.io Fast": {
        "name": "Skribbl fast",
        "goal": "Few colors, large recognizable shapes and aggressive stroke reduction inside a short round.",
        "overrides": {
            "mode": "Smart paths (recommended)",
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "progressive_rendering": "Off",
            "quality": "Balanced",
            "speed": "Fast",
            "precision": "Normal",
            "draw_quality": "Balanced",
            "planning_resolution": "Standard",
            "background_fill": "Off",
            "background_simplification": "Strong",
            "color_grouping": "Reduced palette",
            "color_workflow": "Finish color first",
            "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Strong simplify",
            "visual_verification": "Off",
            "color_rendering": "Perceptual match",
            "color_fidelity": "Faithful",
            "color_layers": "Off",
            "custom_color_workflow": "Calibrated palette",
            "exact_color_limit": "Auto",
            "exact_color_limit_profile_ceiling": 10,
            "time_budget_mode": "Skribbl 60",
            "target_stroke_count": "Auto",
            "max_stroke_cap": "1000",
            "planning_watchdog": "On",
            "resource_scheduler": "Auto",
            "edge_behavior": "Hard Clip",
        },
    },
    "Skribbl.io": {
        "name": "Skribbl quality",
        "goal": "More colors and protected contours/details while still using game-friendly shape paths.",
        "overrides": {
            "mode": "Shape paths",
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "progressive_rendering": "On",
            "quality": "High detail",
            "speed": "Balanced",
            "precision": "Normal",
            "draw_quality": "High likeness",
            "planning_resolution": "High",
            "background_fill": "Off",
            "background_simplification": "Conservative",
            "color_grouping": "Smart",
            "color_workflow": "Finish color first",
            "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Preserve detail",
            "visual_verification": "Off",
            "color_rendering": "Perceptual match",
            "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)",
            "exact_color_limit": "Auto",
            "exact_color_limit_profile_ceiling": 18,
            "time_budget_mode": "Skribbl Default",
            "target_stroke_count": "Auto",
            "max_stroke_cap": "2500",
            "planning_watchdog": "On",
            "resource_scheduler": "Auto",
            "edge_behavior": "Preserve Outline",
        },
    },
    "Gartic.io": {
        "name": "Gartic timer-aware",
        "goal": "Progressive subject-first rendering with a round-aware time/stroke budget.",
        "overrides": {
            "mode": "Shape paths", "shape_model": "Better shapes v2", "shape_order": "Fill first",
            "progressive_rendering": "On", "quality": "Balanced", "speed": "Fast", "precision": "Normal",
            "draw_quality": "Balanced", "planning_resolution": "Standard", "background_fill": "Off",
            "background_simplification": "Strong", "color_grouping": "Reduced palette",
            "color_workflow": "Finish color first", "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Strong simplify", "visual_verification": "Off",
            "color_rendering": "RGB nearest", "color_fidelity": "Balanced", "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)", "exact_color_limit": "8",
            "time_budget_mode": "60 sec", "target_stroke_count": "Auto", "max_stroke_cap": "2500",
            "planning_watchdog": "On", "resource_scheduler": "Auto",
            "edge_behavior": "Hard Clip",
        },
    },
    "Gartic Phone": {
        "name": "Gartic Phone turbo",
        "goal": "Calibrated palette batches with the cheaper horizontal/vertical run orientation per colour.",
        "overrides": {
            "mode": "Smart paths (recommended)", "shape_model": "Better shapes v2", "shape_order": "Fill first",
            "progressive_rendering": "Off", "quality": "Balanced", "speed": "Fast", "precision": "Normal",
            "draw_quality": "Balanced", "planning_resolution": "Standard", "background_fill": "Off",
            "background_simplification": "Strong", "color_grouping": "Reduced palette",
            "color_workflow": "Finish color first", "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Strong simplify", "visual_verification": "Off",
            "color_rendering": "Perceptual match", "color_fidelity": "Faithful", "color_layers": "Off",
            "custom_color_workflow": "Calibrated palette", "exact_color_limit": "Auto", "exact_color_limit_profile_ceiling": 12,
            "time_budget_mode": "Gartic Phone Fast", "target_stroke_count": "Auto", "max_stroke_cap": "2500",
            "planning_watchdog": "On", "resource_scheduler": "Auto",
            "edge_behavior": "Hard Clip",
        },
    },
    "SketchHeads": {
        "name": "SketchHeads fast",
        "goal": "Fast browser drawing with automatically detected bottom palette and conservative UI-safe canvas.",
        "overrides": {
            "mode": "Smart paths (recommended)", "shape_model": "Better shapes v2", "shape_order": "Fill first",
            "progressive_rendering": "Off", "quality": "Balanced", "speed": "Fast", "precision": "Normal",
            "draw_quality": "Balanced", "planning_resolution": "Standard", "background_fill": "Off",
            "background_simplification": "Strong", "color_grouping": "Reduced palette",
            "color_workflow": "Finish color first", "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Strong simplify", "visual_verification": "Off",
            "color_rendering": "RGB nearest", "color_fidelity": "Balanced", "color_layers": "Off",
            "custom_color_workflow": "Calibrated palette", "exact_color_limit": "12",
            "time_budget_mode": "60 sec", "target_stroke_count": "Auto", "max_stroke_cap": "1000",
            "planning_watchdog": "On", "resource_scheduler": "Auto", "edge_behavior": "Hard Clip",
        },
    },
    "Sketchful.io": {
        "name": "Sketchful balanced game",
        "goal": "Broad shapes first, moderate palette reduction and preserved important detail.",
        "overrides": {
            "mode": "Shape paths", "shape_model": "Better shapes v2", "shape_order": "Fill first",
            "progressive_rendering": "On", "quality": "Balanced", "speed": "Fast", "precision": "Normal",
            "draw_quality": "Balanced", "planning_resolution": "Standard", "background_fill": "Off",
            "background_simplification": "Balanced", "color_grouping": "Reduced palette",
            "color_workflow": "Finish color first", "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Balanced", "visual_verification": "Off",
            "color_rendering": "Perceptual match", "color_fidelity": "Faithful", "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)", "exact_color_limit": "16",
            "time_budget_mode": "2 min", "target_stroke_count": "Auto", "max_stroke_cap": "5000",
            "planning_watchdog": "On", "resource_scheduler": "Auto",
            "edge_behavior": "Adaptive Clip",
        },
    },
    "Drawize": {
        "name": "Drawize balanced",
        "goal": "Balanced shapes/colors with moderate simplification and safe fill when calibrated.",
        "overrides": {
            "mode": "Shape paths", "shape_model": "Better shapes v2", "shape_order": "Fill first",
            "progressive_rendering": "On", "quality": "Balanced", "speed": "Balanced", "precision": "Normal",
            "draw_quality": "Balanced", "planning_resolution": "Standard", "background_fill": "Conservative",
            "background_simplification": "Balanced", "color_grouping": "Smart",
            "color_workflow": "Finish color first", "stroke_optimizer": "Smart merge",
            "adaptive_detail": "Balanced", "visual_verification": "Off",
            "color_rendering": "Perceptual match", "color_fidelity": "Faithful", "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)", "exact_color_limit": "16",
            "time_budget_mode": "2 min", "target_stroke_count": "Auto", "max_stroke_cap": "5000",
            "planning_watchdog": "On", "resource_scheduler": "Auto",
            "edge_behavior": "Adaptive Clip",
        },
    },
    "Kleki": {
        "name": "Kleki quality",
        "goal": "High-quality browser painting with explicit user-calibrated tools/colors and no unverified automatic coordinates.",
        "overrides": {
            "mode": "Shape paths", "shape_model": "Better shapes v2", "shape_order": "Fill first",
            "progressive_rendering": "On", "quality": "High detail", "speed": "Balanced", "precision": "High",
            "draw_quality": "High likeness", "planning_resolution": "High", "background_fill": "Conservative",
            "background_simplification": "Conservative", "color_grouping": "Smart", "color_workflow": "Finish color first",
            "stroke_optimizer": "Smart merge", "adaptive_detail": "Preserve detail", "visual_verification": "Off",
            "color_rendering": "Perceptual match", "color_fidelity": "Faithful", "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)", "exact_color_limit": "Auto",
            "time_budget_mode": "Manual", "target_stroke_count": "Auto", "max_stroke_cap": "10000",
            "planning_watchdog": "On", "resource_scheduler": "Auto", "edge_behavior": "Adaptive Clip",
        },
    },
    "Magma": {
        "name": "Magma collaborative quality",
        "goal": "Stable progressive rendering on a collaborative browser canvas with isolated manual calibration.",
        "overrides": {
            "mode": "Shape paths", "shape_model": "Better shapes v2", "shape_order": "Fill first",
            "progressive_rendering": "On", "quality": "High detail", "speed": "Balanced", "precision": "High",
            "draw_quality": "High likeness", "planning_resolution": "High", "background_fill": "Conservative",
            "background_simplification": "Conservative", "color_grouping": "Smart", "color_workflow": "Finish color first",
            "stroke_optimizer": "Smart merge", "adaptive_detail": "Preserve detail", "visual_verification": "Off",
            "color_rendering": "Perceptual match", "color_fidelity": "Faithful", "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)", "exact_color_limit": "Auto",
            "time_budget_mode": "Manual", "target_stroke_count": "Auto", "max_stroke_cap": "10000",
            "planning_watchdog": "On", "resource_scheduler": "Auto", "edge_behavior": "Adaptive Clip",
        },
    },
    "Other drawing app": {
        "name": "Generic balanced",
        "goal": "Conservative general-purpose policy for an unknown drawing application.",
        "overrides": {
            "mode": "Smart paths (recommended)", "progressive_rendering": "Auto",
            "quality": "Balanced", "speed": "Balanced", "precision": "High",
            "draw_quality": "High likeness", "planning_resolution": "High",
            "background_fill": "Conservative", "background_simplification": "Balanced",
            "color_grouping": "Smart", "color_workflow": "Finish color first",
            "stroke_optimizer": "Auto", "adaptive_detail": "Auto", "visual_verification": "Off",
            "color_rendering": "Perceptual match", "color_fidelity": "Faithful", "color_layers": "Off",
            "custom_color_workflow": "Adaptive exact (recommended)", "exact_color_limit": "Auto",
            "exact_color_limit_profile_ceiling": 32,
            "time_budget_mode": "Manual", "target_stroke_count": "Auto",
            "planning_watchdog": "Auto", "resource_scheduler": "Auto",
            "edge_behavior": "Hard Clip",
        },
    },
}


def policy_for(profile_name: str) -> dict:
    base = _POLICIES.get(profile_name, _POLICIES["Other drawing app"])
    return {"name": base["name"], "goal": base["goal"], "overrides": dict(base["overrides"])}


def resolve_profile_policy(profile_name: str, requested: dict, *, mode: str = "Auto") -> tuple[dict, dict]:
    """Return effective renderer settings and explanatory metadata.

    ``Manual settings`` returns the request unchanged.  ``Auto`` overlays only
    renderer settings from the selected policy.  Safety/native input state is
    never represented in this module and therefore cannot be restored/armed.
    """
    validate_profile_engine(mode)
    effective = dict(requested or {})
    policy = policy_for(profile_name)
    changed = {}
    if mode == "Auto":
        pixel_accurate = str(effective.get("draw_quality") or "") == "Pixel Accurate"
        for key, value in policy["overrides"].items():
            # v1.0.86 Block A: explicit Pixel Accurate is a quality lock.
            # A browser speed policy may still supply safe target/tool defaults,
            # but it must not reduce source information or impose destructive
            # stroke/color caps before the accuracy planner runs.
            if profile_setting_is_locked(key, effective):
                continue
            old = effective.get(key)
            # Step 5: when the user selected Auto and this profile uses the
            # adaptive exact-colour workflow, keep Auto alive through Profile
            # Engine resolution.  The old policy value becomes a hard profile
            # ceiling instead of replacing Auto with a fixed colour count.
            if (key == "exact_color_limit" and str(old) == "Auto" and
                    str(effective.get("custom_color_workflow") or "") in
                    ("Adaptive exact (recommended)", "Exact custom + palette fallback")):
                effective[key] = "Auto"
                try:
                    ceiling = int(value)
                except (TypeError, ValueError):
                    ceiling = None
                if ceiling is not None:
                    effective["exact_color_limit_profile_ceiling"] = max(2, ceiling)
                    changed["exact_color_limit_profile_ceiling"] = {"requested": None, "effective": max(2, ceiling)}
                continue
            effective[key] = value
            if old != value:
                changed[key] = {"requested": old, "effective": value}
        if pixel_accurate:
            accuracy_overrides = {
                "draw_quality": "Pixel Accurate",
                "quality": "Maximum detail",
                "planning_resolution": "Extreme",
                "background_simplification": "Off",
                "color_grouping": "Accurate",
                "stroke_optimizer": "Travel only",
                "adaptive_detail": "Off",
                "target_stroke_count": "Auto",
                "max_stroke_cap": "Unlimited",
                "progressive_rendering": "On",
                "color_rendering": "Perceptual match",
                "color_fidelity": "Exact",
            }
            for key, value in accuracy_overrides.items():
                old = effective.get(key)
                effective[key] = value
                if old != value:
                    changed[key] = {"requested": old, "effective": value}
    meta = {
        "engine": "Profile Engine v2",
        "mode": mode,
        "profile": profile_name,
        "policy": policy["name"],
        "goal": policy["goal"],
        "applied": mode == "Auto",
        "changed": changed,
        "changed_count": len(changed),
    }
    return effective, meta


def policy_summary(profile_name: str) -> str:
    p = policy_for(profile_name)
    o = p["overrides"]
    bits = ["Profile Engine v2", p["name"]]
    if o.get("exact_color_limit"):
        bits.append(f"colors {o['exact_color_limit']}")
    if o.get("edge_behavior"):
        bits.append(f"edge {o['edge_behavior']}")
    if o.get("time_budget_mode") and o["time_budget_mode"] != "Manual":
        bits.append(o["time_budget_mode"])
    bits.append(o.get("mode", "renderer"))
    return " · ".join(bits)
