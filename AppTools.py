"""Generic drawing-app tool calibration and capability model.

v1.0.6 adds a small, explicit capability layer instead of pretending every
website/app exposes tools in the same place.  Known profiles declare the tools
Image Draw Bot can use, but every native click position is still calibrated by the
user and anchored to the selected target window.
"""
from __future__ import annotations

import json
from pathlib import Path

from CalibrationAnchors import validate_anchor, resolve_point
from RuntimePaths import atomic_write_text, data_dir, read_json
from ProfileStorage import safe_profile_key

APP_TOOL_SCHEMA = 1
GENERIC_TOOLS = ("Brush", "Fill", "Eraser", "Clear")

# Tool *semantics*, not hard-coded screen coordinates.  UI locations vary with
# browser zoom/app releases, so coordinates are always user-calibrated.
PROFILE_CAPABILITIES = {
    "microsoft-paint": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Native Paint tools; Paint-specific calibration is preferred."},
    "generic": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Calibrate the controls visible in your drawing app."},
    "gartic-phone": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Brush, Fill, Eraser and Clear can be inferred automatically after browser visual preflight; manual anchored calibration remains the fallback."},
    "skribbl": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Calibrate with the canvas/tool bar in its final browser layout."},
    "skribbl-fast": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Fast profile uses the same visible Skribbl controls; recalibrate after browser zoom/layout changes."},
    "sketchheads": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Auto setup handles the palette/canvas. Manual tool capture is optional for Fill/Eraser workflows."},
    "sketchful": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Auto setup can detect the palette; manual tool capture is optional."},
    "drawize": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Tool positions are profile-specific and must be calibrated."},
    "gartic-io": {"brush": True, "fill": True, "eraser": True, "clear": True, "note": "Uses the conservative Gartic browser tool detector when the verified layout matches; manual calibration remains the fallback."},
    "kleki": {"brush": True, "fill": True, "eraser": True, "clear": False, "note": "Kleki controls are manually calibrated and anchored to this profile; no layout coordinates are assumed."},
    "magma": {"brush": True, "fill": True, "eraser": True, "clear": False, "note": "Magma controls are manually calibrated per canvas/profile; collaborative UI changes require recalibration."},
}


def capability(profile_key: str) -> dict:
    return dict(PROFILE_CAPABILITIES.get(profile_key, PROFILE_CAPABILITIES["generic"]))


def tool_file(profile_key: str) -> Path:
    return data_dir() / f"app-tools-{safe_profile_key(profile_key)}.json"


def _point(value, label: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(type(v) is not int for v in value):
        raise ValueError(f"Invalid {label} position. Recalibrate application tools.")
    x, y = value
    if not (-100000 <= x <= 100000 and -100000 <= y <= 100000):
        raise ValueError(f"Invalid {label} position. Recalibrate application tools.")
    return int(x), int(y)


def validate_calibration(data: dict, profile_key: str | None = None) -> dict:
    if not isinstance(data, dict) or type(data.get('version')) is not int or data.get("version") != APP_TOOL_SCHEMA:
        raise ValueError("Invalid application tool calibration.")
    if profile_key is not None and data.get("profile") != profile_key:
        raise ValueError("Tool calibration belongs to a different application profile.")
    clean = {
        "version": APP_TOOL_SCHEMA,
        "profile": str(data.get("profile", "")),
        "anchor": validate_anchor(data.get("anchor")),
        "tools": {},
    }
    tools = data.get("tools")
    if not isinstance(tools, dict):
        raise ValueError("Application tool calibration is missing tool positions.")
    for name in GENERIC_TOOLS:
        if tools.get(name) is not None:
            clean["tools"][name] = list(_point(tools[name], name))
    return clean


def save_calibration(profile_key: str, tools: dict, *, anchor, path: Path | None = None) -> dict:
    data = {"version": APP_TOOL_SCHEMA, "profile": profile_key, "anchor": validate_anchor(anchor), "tools": {}}
    for name, value in tools.items():
        if name not in GENERIC_TOOLS:
            raise ValueError(f"Unsupported application tool: {name}")
        data["tools"][name] = list(_point(value, name))
    clean = validate_calibration(data, profile_key)
    path = Path(path or tool_file(profile_key)); path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False))
    return clean


def load_calibration(profile_key: str, path: Path | None = None) -> dict:
    path = Path(path or tool_file(profile_key))
    return validate_calibration(read_json(path, max_bytes=128 * 1024), profile_key)


def build_tool_action(profile_key: str, tool: str, current_client_rect, path: Path | None = None) -> tuple[str, tuple[int, int]]:
    if tool not in GENERIC_TOOLS:
        raise ValueError("Unknown application drawing tool.")
    data = load_calibration(profile_key, path)
    position = data["tools"].get(tool)
    if position is None:
        raise ValueError(f"{tool} is not calibrated for this application profile.")
    if current_client_rect is None:
        raise ValueError("The target window geometry is unavailable. Select the drawing area again.")
    return (tool.lower(), resolve_point(position, data["anchor"], current_client_rect))
