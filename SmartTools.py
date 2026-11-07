"""Plan-level drawing-tool choice for Image Draw Bot v1.0.7."""
from __future__ import annotations

TOOL_STRATEGIES = ("Auto", "Precision first", "Speed first", "Respect selected")


def validate_tool_strategy(value: str) -> str:
    if value not in TOOL_STRATEGIES:
        raise ValueError("Tool strategy must be Auto, Precision first, Speed first or Respect selected.")
    return value


def choose_paint_tool(selected: str, strategy: str, calibration: dict | None, *, portrait: bool, brush_px: int) -> str:
    """Choose a concrete Paint tool without inventing uncalibrated controls."""
    validate_tool_strategy(strategy)
    if selected != "Auto (recommended)" or strategy == "Respect selected":
        return selected
    from CalibrationValidation import screen_point
    data = calibration if isinstance(calibration, dict) else {}
    tools = data.get("tools", {})
    if not isinstance(tools, dict): tools = {}
    def ready(value):
        try: screen_point(value)
        except ValueError: return False
        return True
    pencil_ready = ready(tools.get("Pencil"))
    brush_ready = all(ready(data.get(key)) for key in ("opacity_100", "brush_menu", "brush_preset"))
    if strategy == "Precision first":
        if pencil_ready: return "Pencil"
        if brush_ready: return "Brush"
    elif strategy == "Speed first":
        if brush_ready: return "Brush"
        if pencil_ready: return "Pencil"
    else:
        # Portrait/small brush work benefits from Pencil.  Standard large-area
        # palette rendering can use a calibrated solid Brush to reduce event load.
        if portrait or int(brush_px) <= 1:
            if pencil_ready: return "Pencil"
            if brush_ready: return "Brush"
        else:
            if brush_ready: return "Brush"
            if pencil_ready: return "Pencil"
    return selected
