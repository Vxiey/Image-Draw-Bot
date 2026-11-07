"""Step 19 final profile polish for Image Draw Bot.

This module is intentionally pure: no Tk, no mouse, no file writes and no
screen capture.  It centralizes the release-ready defaults, setup warnings and
calibration flow for the core shipped profiles so the GUI, Profile Engine and
tests do not each invent slightly different guidance.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, Mapping

from ProfileEngine import profile_setting_is_locked


CORE_RELEASE_PROFILES = ("Microsoft Paint", "Gartic Phone", "Skribbl.io", "Skribbl.io Fast")
BROWSER_RELEASE_PROFILES = ("Gartic Phone", "Skribbl.io", "Skribbl.io Fast")


@dataclass(frozen=True)
class ProfileReleasePreset:
    profile_name: str
    preset_name: str
    profile_key: str
    recommended_time_budget: str
    renderer: str
    detail_level: str
    planning_resolution: str
    color_policy: str
    palette_requirement: str
    tool_requirement: str
    safety_flow: tuple[str, ...]
    calibration_flow: tuple[str, ...]
    warnings: tuple[str, ...]
    default_overrides: Mapping[str, Any]

    def __post_init__(self):
        object.__setattr__(self, 'default_overrides', MappingProxyType(dict(self.default_overrides)))

    def as_dict(self) -> dict[str, Any]:
        data = {field.name: getattr(self, field.name) for field in fields(self)}
        data["default_overrides"] = dict(self.default_overrides)
        return data


_PRESETS: dict[str, ProfileReleasePreset] = {
    "Microsoft Paint": ProfileReleasePreset(
        profile_name="Microsoft Paint",
        preset_name="Paint release quality",
        profile_key="microsoft-paint",
        recommended_time_budget="Manual",
        renderer="Shape paths + Safe Fill",
        detail_level="High detail",
        planning_resolution="High",
        color_policy="Perceptual Adaptive Exact custom RGB with OKLab fallback",
        palette_requirement="Verified Paint palette or Adaptive Exact controls",
        tool_requirement="Pencil/Brush plus Fill/Eraser calibration recommended",
        safety_flow=("image", "prepare Paint and calibrate colors", "start"),
        calibration_flow=("Prepare Paint automatically", "Detect canvas and pencil size", "Read palette and RGB dialog"),
        warnings=(
            "Paint prepares its canvas, pencil and RGB controls before drawing. Small tests and previews are optional.",
            "Keep the Paint window, DPI and toolbar layout unchanged after calibration.",
            "Use Adaptive Exact for best color fidelity; preset palettes are treated as estimated until verified.",
        ),
        default_overrides={
            "mode": "Shape paths",
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "progressive_rendering": "On",
            "quality": "High detail",
            "speed": "Balanced",
            "precision": "High",
            "draw_quality": "High likeness",
            "planning_resolution": "High",
            "background_fill": "Conservative",
            "fill_engine": "Closed regions v2",
            "background_simplification": "Balanced",
            "color_grouping": "Smart",
            "color_rendering": "Perceptual match",
            "color_fidelity": "Faithful",
            "custom_color_workflow": "Adaptive exact (recommended)",
            "exact_color_limit": "Auto",
            "time_budget_mode": "Manual",
            "target_stroke_count": "Auto",
            "max_stroke_cap": "10000",
            "visual_verification": "Strict",
            "edge_behavior": "Adaptive Clip",
        },
    ),
    "Gartic Phone": ProfileReleasePreset(
        profile_name="Gartic Phone",
        preset_name="Gartic Phone 75s release",
        profile_key="gartic-phone",
        recommended_time_budget="Gartic Phone Fast",
        renderer="Extra Fast 2.0 connected regions",
        detail_level="Balanced",
        planning_resolution="Standard",
        color_policy="Perceptual calibrated palette with OKLab matching and dominant hue anchors",
        palette_requirement="Verified 6×12 palette or fresh Auto Setup",
        tool_requirement="Brush + Fill recommended; manual capture is fallback",
        safety_flow=("browser auto setup", "image", "canvas verify", "unlock", "start"),
        calibration_flow=("Auto setup browser", "Verify canvas/palette", "Optional manual tools", "Build preview", "Unlock full drawing"),
        warnings=(
            "Use the 75s Gartic Phone Fast budget for normal fast rounds.",
            "Do not move/zoom the browser after Auto Setup; layout changes force a safe re-scan.",
            "If palette state is only estimated, color accuracy can drop; re-run Auto setup browser.",
        ),
        default_overrides={
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
            "fill_engine": "Closed regions v2",
            "background_simplification": "Strong",
            "color_grouping": "Reduced palette",
            "color_rendering": "Perceptual match",
            "color_fidelity": "Faithful",
            "custom_color_workflow": "Calibrated palette",
            "exact_color_limit": "Auto",
            "exact_color_limit_profile_ceiling": 12,
            "time_budget_mode": "Gartic Phone Fast",
            "target_stroke_count": "Auto",
            "max_stroke_cap": "2500",
            "visual_verification": "Off",
            "edge_behavior": "Hard Clip",
        },
    ),
    "Skribbl.io": ProfileReleasePreset(
        profile_name="Skribbl.io",
        preset_name="Skribbl default 80s quality",
        profile_key="skribbl",
        recommended_time_budget="Skribbl Default",
        renderer="Shape paths + time-aware colors",
        detail_level="Balanced",
        planning_resolution="Standard",
        color_policy="Perceptual OKLab palette/exact matching with protected important details",
        palette_requirement="Verified palette or Auto Setup",
        tool_requirement="Brush + Fill + eraser calibration recommended for One-Click",
        safety_flow=("browser auto setup", "image", "canvas verify", "unlock", "start"),
        calibration_flow=("Auto setup browser", "Verify palette/brush size", "Select canvas fallback", "Build preview", "Unlock full drawing"),
        warnings=(
            "Default Skribbl public rounds are usually short; use Skribbl Default for 80s planning.",
            "Keep browser zoom/layout stable after setup.",
            "Use Skribbl.io Fast when the lobby timer is 60s or lower.",
        ),
        default_overrides={
            "mode": "Shape paths",
            "shape_model": "Better shapes v2",
            "shape_order": "Fill first",
            "progressive_rendering": "On",
            "quality": "Balanced",
            "speed": "Fast",
            "precision": "Normal",
            "draw_quality": "High likeness",
            "planning_resolution": "Standard",
            "background_fill": "Off",
            "fill_engine": "Closed regions v2",
            "background_simplification": "Balanced",
            "color_grouping": "Reduced palette",
            "color_rendering": "Perceptual match",
            "color_fidelity": "Faithful",
            "custom_color_workflow": "Adaptive exact (recommended)",
            "exact_color_limit": "Auto",
            "exact_color_limit_profile_ceiling": 18,
            "time_budget_mode": "Skribbl Default",
            "target_stroke_count": "Auto",
            "max_stroke_cap": "2500",
            "visual_verification": "Off",
            "edge_behavior": "Preserve Outline",
        },
    ),
    "Skribbl.io Fast": ProfileReleasePreset(
        profile_name="Skribbl.io Fast",
        preset_name="Skribbl 60s turbo",
        profile_key="skribbl-fast",
        recommended_time_budget="Skribbl 60",
        renderer="Extra Fast 2.0 scanline/Fill hybrid",
        detail_level="Balanced",
        planning_resolution="Standard",
        color_policy="Perceptual small calibrated palette with OKLab hue protection",
        palette_requirement="Verified palette or Auto Setup",
        tool_requirement="Brush + Fill recommended; eraser optional",
        safety_flow=("browser auto setup", "image", "canvas verify", "unlock", "start"),
        calibration_flow=("Auto setup browser", "Verify palette/brush", "Build preview", "Unlock full drawing"),
        warnings=(
            "Fast preset prioritizes recognizable structure over texture.",
            "If the round is 80s or longer, Skribbl.io may preserve more detail.",
            "A stale palette causes wrong colors; re-run Auto setup after zoom/layout changes.",
        ),
        default_overrides={
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
            "fill_engine": "Closed regions v2",
            "background_simplification": "Strong",
            "color_grouping": "Reduced palette",
            "color_rendering": "Perceptual match",
            "color_fidelity": "Faithful",
            "custom_color_workflow": "Calibrated palette",
            "exact_color_limit": "Auto",
            "exact_color_limit_profile_ceiling": 10,
            "time_budget_mode": "Skribbl 60",
            "target_stroke_count": "Auto",
            "max_stroke_cap": "1000",
            "visual_verification": "Off",
            "edge_behavior": "Hard Clip",
        },
    ),
}


def profile_release_preset(profile_name: str | None) -> ProfileReleasePreset:
    name = str(profile_name or '')
    preset = _PRESETS.get(name)
    if preset is not None:
        return preset
    return ProfileReleasePreset(
        profile_name=name or 'Other drawing app',
        preset_name="Generic release profile",
        profile_key="generic",
        recommended_time_budget="Manual",
        renderer="Smart paths",
        detail_level="Balanced",
        planning_resolution="High",
        color_policy="Perceptual match with user calibration",
        palette_requirement="Read the visible palette or use current-ink sketch mode",
        tool_requirement="Brush/Fill calibration recommended",
        safety_flow=("image", "palette/tools", "canvas", "small test", "lock", "preflight", "dry run", "start"),
        calibration_flow=("Calibrate Brush / Fill", "Read colors / palette", "Select drawing area", "Build preview"),
        warnings=("Generic profiles need manual layout verification because the app is unknown.",),
        default_overrides={},
    )


def final_profile_defaults(profile_name: str | None) -> dict[str, Any]:
    return dict(profile_release_preset(profile_name).default_overrides)


def profile_setup_flow(profile_name: str | None) -> tuple[str, ...]:
    return tuple(profile_release_preset(profile_name).calibration_flow)


def profile_release_warnings(profile_name: str | None, calibration_state: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    preset = profile_release_preset(profile_name)
    warnings = list(preset.warnings)
    state_data = calibration_state if isinstance(calibration_state, Mapping) else {}
    # Keep the original flat aliases authoritative, and also accept the nested
    # palette evidence produced by CalibrationState for actual app callers.
    palette = state_data.get("palette")
    palette = palette if isinstance(palette, Mapping) else {}
    state = str(state_data.get("palette_state") or state_data.get("state") or
                palette.get("state") or "").lower()
    if state in ("estimated", "unavailable", "none"):
        warnings.append("Palette is not verified for this profile; use Auto Setup or Read colors before relying on color accuracy.")
    if str(profile_name or "") in BROWSER_RELEASE_PROFILES:
        warnings.append("Browser One-Click is allowed only after read-only canvas/palette verification.")
    return tuple(dict.fromkeys(warnings))


def apply_profile_polish(profile_name: str | None, options: Mapping[str, Any] | None,
                         *, calibration_state: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attach release-preset metadata and enforce release defaults in Auto mode.

    User Manual settings remain respected.  In Auto/Profile Engine mode the core
    shipped profiles receive the final Step 19 defaults, including game-specific
    time budgets and OKLab color policy.
    """
    out = dict(options or {})
    preset = profile_release_preset(profile_name)
    changed: dict[str, dict[str, Any]] = {}
    if str(out.get("profile_engine") or "Auto") == "Auto":
        for key, value in preset.default_overrides.items():
            if profile_setting_is_locked(key, out):
                continue
            old = out.get(key)
            if old != value:
                out[key] = value
                changed[key] = {"before": old, "after": value}
    warnings = profile_release_warnings(profile_name, calibration_state if calibration_state is not None else out.get("calibration_state"))
    meta = {
        "step": 19,
        "profile_name": preset.profile_name,
        "profile_key": preset.profile_key,
        "preset_name": preset.preset_name,
        "recommended_time_budget": preset.recommended_time_budget,
        "effective_time_budget": out.get("time_budget_mode", preset.recommended_time_budget),
        "renderer": preset.renderer,
        "detail_level": preset.detail_level,
        "planning_resolution": preset.planning_resolution,
        "color_policy": preset.color_policy,
        "palette_requirement": preset.palette_requirement,
        "tool_requirement": preset.tool_requirement,
        "calibration_flow": list(preset.calibration_flow),
        "safety_flow": list(preset.safety_flow),
        "warnings": list(warnings),
        "changed": changed,
        "changed_count": len(changed),
        "applied": str(out.get("profile_engine") or "Auto") == "Auto",
    }
    out["profile_polish_meta"] = meta
    return out, meta


def format_profile_polish(meta: Mapping[str, Any] | None, *, compact: bool = True) -> str:
    if not isinstance(meta, Mapping) or not meta:
        return "Profile polish: unavailable"
    name = str(meta.get("preset_name") or meta.get("profile_name") or "profile")
    budget = str(meta.get("effective_time_budget") or meta.get("recommended_time_budget") or "Manual")
    renderer = str(meta.get("renderer") or "renderer")
    color = str(meta.get("color_policy") or "color policy")
    raw_warnings = meta.get("warnings")
    warnings = [raw_warnings] if isinstance(raw_warnings, str) else list(raw_warnings) if isinstance(raw_warnings, (list, tuple)) else []
    if compact:
        warn = f" · {len(warnings)} warning(s)" if warnings else ""
        return f"Profile polish: {name} · {budget} · {renderer}{warn}"
    flow = " → ".join(str(x) for x in (meta.get("calibration_flow") or []))
    warning_text = "\n".join(f"- {w}" for w in warnings[:6]) or "- No active warnings."
    return f"{name}\nBudget: {budget}\nRenderer: {renderer}\nColors: {color}\nSetup: {flow}\nWarnings:\n{warning_text}"
