"""Truthful, profile-scoped calibration state reporting for Image Draw Bot Step 9."""
from __future__ import annotations

from pathlib import Path

from ProfileStorage import (calibration_context_fingerprint, profile_palette_file,
                            profile_timing_file, safe_profile_key)

STATES = ("unavailable", "estimated", "calibrated", "verified")


def _state(value: str | None, default: str = "calibrated") -> str:
    value = str(value or default).strip().lower()
    return value if value in STATES else default


def palette_state(profile_key: str, *, palette_path: Path | None = None,
                  preset_available: bool = False) -> dict:
    from Colors import calibration_metadata
    key = safe_profile_key(profile_key)
    path = Path(palette_path or profile_palette_file(key))
    try:
        meta = calibration_metadata(path, profile_key=key)
        if not int(meta.get("version") or 0):
            raise OSError(path)
        state = _state(meta.get("state"), "calibrated")
        return {"state": state, "available": True, "count": int(meta.get("count") or 0),
                "profile_key": key, "verification": dict(meta.get("verification") or {}),
                "path": str(path)}
    except (OSError, ValueError, TypeError):
        state = "estimated" if preset_available else "unavailable"
        return {"state": state, "available": False, "count": 0, "profile_key": key,
                "verification": {}, "path": str(path)}


def tool_state(profile_key: str) -> dict:
    key = safe_profile_key(profile_key)
    try:
        if key == "microsoft-paint":
            from PaintTools import load_tool_calibration
            data = load_tool_calibration()
            available = bool(data.get("tools") or data.get("brush_menu"))
            auto = data.get('auto') if isinstance(data.get('auto'), dict) else {}
            return {"state": "calibrated" if available else "unavailable", "available": available,
                    "profile_key": key, "confidence": float(auto.get("confidence", 0.0) or 0.0)}
        from AppTools import load_calibration
        data = load_calibration(key)
        available = bool(data.get("tools"))
        return {"state": "calibrated" if available else "unavailable", "available": available,
                "profile_key": key, "confidence": None}
    except (OSError, ValueError, TypeError):
        return {"state": "unavailable", "available": False, "profile_key": key, "confidence": None}


def exact_color_state(profile_key: str, *, workflow: str = "", context_fingerprint: str | None = None) -> dict:
    key = safe_profile_key(profile_key)
    try:
        from ExactColorTools import custom_rgb_available
        available = bool(custom_rgb_available(key))
    except Exception:
        available = False
    verified = False
    if available:
        try:
            from ColorCache import load_cache
            verified = bool(load_cache(key, workflow=workflow, context_fingerprint=context_fingerprint))
        except Exception:
            verified = False
    return {"state": "verified" if verified else ("calibrated" if available else "unavailable"),
            "available": available, "verified": verified, "profile_key": key}


def timing_state(options: dict) -> dict:
    try:
        from DrawTimeCalibration import correction_for
        info = correction_for(options)
    except Exception:
        info = {"learned": False, "samples": 0, "ratio": 1.0}
    learned = bool(info.get("learned"))
    return {"state": "calibrated" if learned else "estimated", "available": learned,
            "samples": int(info.get("samples") or 0), "ratio": float(info.get("ratio") or 1.0),
            "mape": info.get("mape"), "operation_runtime_source": info.get("operation_runtime_source", "none")}


def profile_calibration_summary(profile_key: str, *, palette_path: Path | None = None,
                                preset_available: bool = False, workflow: str = "",
                                context_fingerprint: str | None = None,
                                timing_options: dict | None = None) -> dict:
    key = safe_profile_key(profile_key)
    palette = palette_state(key, palette_path=palette_path, preset_available=preset_available)
    tools = tool_state(key)
    exact = exact_color_state(key, workflow=workflow, context_fingerprint=context_fingerprint)
    timing_input = dict(timing_options or {})
    timing_input["profile_key"] = key
    timing = timing_state(timing_input)
    result = {
        "profile_key": key,
        "palette": palette,
        "tools": tools,
        "exact_color": exact,
        "timing": timing,
        "fingerprint": str(context_fingerprint or calibration_context_fingerprint(key, workflow=workflow, palette_path=palette_path)),
        "timing_file": str(profile_timing_file(key)),
    }
    try:
        from CalibrationHealth import summarize_calibration_health
        result["health"] = summarize_calibration_health(result).as_dict()
    except Exception as error:
        result["health"] = {"level":"unknown","score":0.0,"blocking":True,"reason":str(error)}
    return result
