"""Step 20 beginner setup wizard helpers for Image Draw Bot.

Pure, deterministic checklist builder used by the GUI and tests.  It never uses
Tk, native input, screenshots, files, network or telemetry.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping

from TargetCapabilities import capability_for_key
from GameProfiles import PROFILES


@dataclass(frozen=True)
class WizardStep:
    key: str
    title: str
    state: str  # done, next, blocked, optional
    action: str
    detail: str = ""
    blocks_start: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _state(done: bool, *, optional: bool = False, blocked: bool = False) -> str:
    if done:
        return "done"
    if optional:
        return "optional"
    return "blocked" if blocked else "next"


def build_setup_wizard(*, profile_name: str = "Other drawing app", image_loaded: bool = False,
                       tools_ready: bool = False, palette_ready: bool = False, area_ready: bool = False,
                       small_test_passed: bool = False, target_locked: bool = False,
                       preflight_passed: bool = False, dry_run_passed: bool = False,
                       full_draw_unlocked: bool = False, activity: str | None = None) -> tuple[WizardStep, ...]:
    if profile_name == "Microsoft Paint":
        return (
            WizardStep("image", "Load image", _state(image_loaded), "Select, paste or drop an image.", blocks_start=not image_loaded),
            WizardStep("prepare", "Automatic Paint preparation", "optional", "Start finds Paint, canvas, pencil size, palette and RGB controls automatically."),
            WizardStep("start", "Prepare Paint & draw", _state(False, blocked=not image_loaded or bool(activity)), "Press Prepare Paint & draw. Tests and previews are optional.", blocks_start=not image_loaded or bool(activity)),
        )
    strict = False
    profile_key=str(PROFILES.get(profile_name,('generic',))[0])
    capability=capability_for_key(profile_key)
    browser=capability.kind.startswith('browser-')
    steps = [
        WizardStep("profile", "Choose target profile", "done" if profile_name else "next",
                   "Choose Paint, Gartic Phone, Skribbl.io or another drawing target.",
                   detail=f"Current profile: {profile_name or 'none'}", blocks_start=not bool(profile_name)),
        WizardStep("image", "Load image", _state(image_loaded),
                   "Select, paste or drop an image.",
                   detail="Source image is loaded." if image_loaded else "No source image is loaded.", blocks_start=not image_loaded),
        WizardStep("calibration", "Calibrate tools and colors", _state(tools_ready and palette_ready, optional=(browser and palette_ready)),
                   "Run Auto setup for browser games or Auto setup Paint / Read colors for Paint.",
                   detail=("Tools and palette are ready." if tools_ready and palette_ready else "Tool or palette setup is still missing."),
                   blocks_start=not palette_ready),
        WizardStep("canvas", "Select drawing area", _state(area_ready, blocked=not image_loaded),
                   "Select only the drawable canvas, not the toolbar or browser chrome.",
                   detail="Drawing area is selected." if area_ready else "Canvas bounds are missing.", blocks_start=not area_ready),
        WizardStep("preview", "Build preview", "optional" if image_loaded else "blocked",
                   "Use Build preview to inspect Original → Quantized target → Simulated final and accuracy heatmaps.",
                   detail="Manual preview avoids lag while changing settings.", blocks_start=False),
    ]
    if strict:
        steps.extend([
            WizardStep("small_test", "Run small test", _state(small_test_passed, blocked=not area_ready),
                       "Draw a tiny test before locking setup.", blocks_start=not small_test_passed),
            WizardStep("lock", "Lock setup", _state(target_locked, blocked=not small_test_passed),
                       "Fingerprint target window, DPI, canvas, palette and tool calibration.", blocks_start=not target_locked),
            WizardStep("preflight", "Safety preflight", _state(preflight_passed, blocked=not target_locked),
                       "Run read-only validation. No clicks are sent.", blocks_start=not preflight_passed),
            WizardStep("dryrun", "Fast Dry run", _state(dry_run_passed, blocked=not preflight_passed),
                       "Simulate representative routes without clicks.", blocks_start=not dry_run_passed),
        ])
    else:
        steps.extend([
            WizardStep("auto_setup", "Browser/game setup", _state(tools_ready and palette_ready and area_ready, optional=not browser),
                       "Use Auto setup browser when available; manual setup is fallback.",
                       blocks_start=False),
            WizardStep("diagnostics", "Optional diagnostics", "optional",
                       "Small test, Lock setup, Safety preflight and Dry run remain available for extra safety.",
                       blocks_start=False),
        ])
    steps.append(WizardStep("unlock", "Unlock and start", _state(full_draw_unlocked and not activity, blocked=bool(activity)),
                            "Wait for the current operation or press Stop." if activity else "Press Unlock full drawing, then Start. Esc stops immediately.",
                            detail=("Another operation is running." if activity else "Start remains locked until Unlock is pressed."),
                            blocks_start=not full_draw_unlocked or bool(activity)))
    return tuple(steps)


def missing_start_requirements(steps: Iterable[WizardStep]) -> tuple[WizardStep, ...]:
    return tuple(step for step in steps if step.blocks_start and step.state != "done")


def next_action(steps: Iterable[WizardStep]) -> str:
    steps=tuple(steps)
    for step in steps:
        if step.state in ("next", "blocked") and step.blocks_start:
            return step.action
    for step in steps:
        if step.state == "next":
            return step.action
    return "Unlock full drawing, then press Start."


def format_setup_status(steps: Iterable[WizardStep], *, max_missing: int = 3) -> str:
    steps = tuple(steps)
    missing = missing_start_requirements(steps)
    final_action=("Prepare Paint & draw" if any(step.key=="prepare" for step in steps)
                  else "Unlock full drawing, then Start")
    if not missing:
        return f"Setup wizard: ready. {final_action}."
    short = ", ".join(step.title for step in missing[:max(1, int(max_missing))])
    extra = len(missing) - max(1, int(max_missing))
    suffix = f" +{extra} more" if extra > 0 else ""
    return f"Setup wizard: {len(missing)} blocking item(s) · {short}{suffix}. Next: {next_action(steps)} · Final: {final_action}."


def format_wizard_dialog(steps: Iterable[WizardStep], *, profile_warnings: Iterable[str] = ()) -> str:
    icons = {"done": "✓", "next": "→", "blocked": "×", "optional": "•"}
    lines = ["Beginner setup wizard", ""]
    for step in steps:
        lines.append(f"{icons.get(step.state, '•')} {step.title}")
        lines.append(f"  {step.action}")
        if step.detail:
            lines.append(f"  {step.detail}")
    warnings = [str(w) for w in profile_warnings if str(w).strip()]
    if warnings:
        lines.extend(["", "Profile warnings:"])
        lines.extend(f"- {w}" for w in warnings[:8])
    return "\n".join(lines).strip() + "\n"


def friendly_error_message(raw_status: str, *, profile_name: str = "") -> str:
    text = str(raw_status or "").strip()
    low = text.lower()
    if not text:
        return "No error is active."
    if "target lock" in low or "drawing area" in low or "canvas" in low:
        return "Canvas/target setup changed. Select the drawing area again, lock setup and rerun preflight."
    if "palette" in low or "expected color" in low or "color" in low:
        return "Color setup needs refresh. Re-run Auto setup or Read colors for the active profile, then run the small test."
    if "timeout" in low or "timed out" in low or "preview" in low:
        return "Preview planning took too long. Use Fast preview or lower preview detail; full Start can still build its final plan."
    if "gpu" in low or "cuda" in low or "vram" in low:
        return "GPU acceleration is not required. Switch GPU mode to Auto or CPU and retry."
    if profile_name == "Microsoft Paint" and ("preflight" in low or "dry run" in low):
        return "Paint diagnostics are optional. Use Prepare Paint & draw to recalibrate and start."
    return text
