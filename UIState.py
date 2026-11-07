"""Pure UI-state helpers for Image Draw Bot's modern workspace.

This module deliberately contains no Tk imports so readiness/error logic can be
unit-tested without a display. The GUI renders these states on the Tk main loop.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    label: str
    state: str  # ready, attention, blocked, optional
    detail: str = ""


@dataclass(frozen=True)
class WorkspaceState:
    label: str
    tone: str  # ready, attention, blocked, working, error
    ready: bool
    can_test: bool
    items: tuple[ChecklistItem, ...]


def _looks_like_error(status: str) -> bool:
    text = str(status or "").strip().lower()
    if not text:
        return False
    # These success messages carry a user-chosen filename/folder after the colon.
    # A file named crash.png or timeout.gif must not disable the ready workspace.
    if text.startswith(('png saved: ', 'recording saved: ', 'diagnostics package created: ',
                        'app data: ', 'safety reports: ', 'latest safety report: ')):
        return False
    markers = (
        "operation failed", "preflight stopped", "could not", "crash",
        "did not get the expected color", "unexpectedly", "access violation",
        "invalid plan", "failed:", "error:", "stopped:",
        "timeout", "timed out", "out of memory", "permission denied",
        "no space left", "disk full", "start locked", "cannot identify image",
        "no module named", "read-only file system",
    )
    # Normal user cancellation/stopping should not turn the workspace red.
    if text in {"stopped.", "stopping…", "stopping...", "cancelled."}:
        return False
    return any(marker in text for marker in markers)


def compute_workspace_state(*, image_loaded: bool, target_name: str,
                            paint_tools_ready: bool, area_ready: bool,
                            palette_ready: bool, test_passed: bool,
                            target_locked: bool = False,
                            preflight_passed: bool = True,
                            dry_run_passed: bool = True,
                            gpu_text: str = "CPU fallback available", strict_safety: bool = True,
                            prepare_on_start: bool = False,
                            activity: str | None = None, status: str = "") -> WorkspaceState:
    """Return a compact, deterministic readiness model for the GUI."""
    paint_selected = target_name == "Microsoft Paint"
    automatic_paint = paint_selected and prepare_on_start
    diagnostic_required = strict_safety and not automatic_paint
    target_selected = bool((target_name or "").strip())
    target_label = f"{target_name} profile selected" if target_selected else "Target profile selected"
    tools_label = "Paint drawing tool ready" if paint_selected else "Drawing controls ready"
    tools_detail = ("Tool preflight is ready." if paint_tools_ready else "Calibrate the selected Paint tool and its required controls.") if paint_selected else \
                   "Current brush can be used; optional Brush/Fill controls can be calibrated for this profile."
    items = (
        ChecklistItem("image", "Image loaded", "ready" if image_loaded else "blocked",
                      "Source image is ready." if image_loaded else "Choose, paste or drop an image."),
        ChecklistItem("target", target_label, "ready" if target_selected else "blocked",
                      f"Current profile: {target_name}" if target_selected else "Choose the drawing application/profile."),
        ChecklistItem("tools", tools_label,
                      "ready" if paint_tools_ready else ("optional" if automatic_paint else "attention"),
                      "Prepare Paint & draw verifies the pencil and its size." if automatic_paint and not paint_tools_ready else tools_detail),
        ChecklistItem("area", "Drawing area selected", "ready" if area_ready else ("optional" if automatic_paint else "blocked"),
                      "Canvas coordinates locked." if area_ready else ("Prepare Paint & draw detects and verifies the canvas." if automatic_paint else "Select only the drawable canvas.")),
        ChecklistItem("palette", "Palette ready", "ready" if palette_ready else ("optional" if automatic_paint else "attention"),
                      "Color input is ready." if palette_ready else ("Prepare Paint & draw calibrates color input." if automatic_paint else "Read colors or use a Paint mode that bypasses palette clicks.")),
        ChecklistItem("test", "First stroke test passed", "ready" if test_passed else ("blocked" if diagnostic_required else "optional"),
                      "Small test completed." if test_passed else ("Required for this setup." if diagnostic_required else "Optional diagnostic for this profile.")),
        ChecklistItem("lock", "Setup locked", "ready" if target_locked else ("blocked" if diagnostic_required else "optional"),
                      "Target, DPI, area and palette are fingerprinted." if target_locked else ("Required for this setup." if diagnostic_required else "Optional extra safety for this profile.")),
        ChecklistItem("preflight", "Safety preflight passed", "ready" if preflight_passed else ("blocked" if diagnostic_required else "optional"),
                      "No-click safety validation is current." if preflight_passed else ("Required for this setup." if diagnostic_required else "Optional no-click diagnostic.")),
        ChecklistItem("dryrun", "Dry run passed", "ready" if dry_run_passed else ("blocked" if diagnostic_required else "optional"),
                      "Full route was simulated without clicks." if dry_run_passed else ("Required for this setup." if diagnostic_required else "Optional route diagnostic.")),
        ChecklistItem("gpu", "GPU ready / CPU fallback active", "ready", gpu_text or "CPU fallback available."),
    )
    if activity:
        return WorkspaceState("Drawing" if activity == "draw" else "Working", "working", False, False, items)
    if _looks_like_error(status):
        return WorkspaceState("Error", "error", False, False, items)
    can_test = target_selected and image_loaded and area_ready and paint_tools_ready and palette_ready
    if automatic_paint and image_loaded:
        return WorkspaceState("Ready to prepare Paint", "ready", True, can_test, items)
    ready = can_test and ((test_passed and target_locked and preflight_passed and dry_run_passed) if strict_safety else True)
    if ready:
        return WorkspaceState("Ready to draw", "ready", True, True, items)
    if image_loaded and (area_ready or paint_tools_ready or palette_ready):
        return WorkspaceState("Setup needed", "attention", False, can_test, items)
    if image_loaded:
        return WorkspaceState("Ready to test" if can_test else "Setup needed", "attention", False, can_test, items)
    return WorkspaceState("Not ready", "blocked", False, False, items)


def classify_error(status: str) -> dict[str, str] | None:
    """Translate common technical failures into short actionable UI copy."""
    text = str(status or "").strip()
    low = text.lower()
    if not _looks_like_error(text):
        return None
    if "expected color" in low or "solid black" in low or "closest rendered rgb" in low:
        return {
            "title": "Paint color verification failed",
            "message": "Image Draw Bot could not confirm the requested color in the test stroke. This can be a missed stroke, a stale palette position, background sampling, or a different selected color.",
            "action": "Run Auto Paint calibration again, keep the Paint ribbon visible, then retry the small test. If custom colors are enabled, recalibrate the custom color controls too.",
        }
    if "drawing area" in low or "target window" in low or "display scaling" in low:
        return {
            "title": "Drawing area needs attention",
            "message": text,
            "action": "Keep the target on the same display, select only the drawable canvas again, then Lock setup before Start.",
        }
    if "preview" in low and ("timeout" in low or "timed out" in low or "too long" in low):
        return {
            "title": "Preview planning was too heavy",
            "message": text,
            "action": "Use Fast/Balanced preview detail or keep Manual preview. Full Start still builds its own guarded final plan.",
        }
    if "start locked" in low or "unlock full drawing" in low or "dry run" in low or "preflight" in low:
        return {
            "title": "Start is still safely locked",
            "message": text,
            "action": "Open Setup wizard to see the next step. Paint uses Prepare Paint & draw; its tests and previews are optional. Other profiles use Unlock full drawing, then Start after setup.",
        }
    if "gpu" in low or "cuda" in low or "vram" in low:
        return {
            "title": "GPU acceleration issue",
            "message": text,
            "action": "Switch GPU acceleration to Auto or CPU, or lower the VRAM budget, then retry.",
        }
    remedies = (
        (("disk full", "no space left"), "Storage is full", "Free space on the drive containing Image Draw Bot data, then save again."),
        (("permission denied", "read-only file system"), "File cannot be written", "Choose a writable folder and check whether another program has locked the file."),
        (("cannot identify image",), "Image could not be opened", "Try opening the image in an image editor and exporting it as PNG."),
        (("no module named",), "A required component is missing", "Run Start.bat --update from the complete extracted source package."),
        (("out of memory",), "Not enough memory", "Reduce the drawing area or preview detail and close other memory-heavy applications."),
    )
    for markers, title, action in remedies:
        if any(marker in low for marker in markers):
            return {"title": title, "message": text, "action": action}
    if "calibrat" in low or "palette" in low or "color" in low:
        return {
            "title": "Calibration needs attention",
            "message": text,
            "action": "Re-run the relevant tool or color calibration, then use Draw a small test.",
        }
    return {
        "title": "Image Draw Bot could not complete that action",
        "message": text or "An unexpected error occurred.",
        "action": "Open the logs for details. You can also create a local sanitized diagnostics ZIP from Tools.",
    }
