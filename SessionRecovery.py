"""Crash-safe local session checkpointing for Image Draw Bot.

Only local app state is cached. The cached source image is never included in
reports/diagnostics automatically. Recovery never restores an armed/validated
drawing state: target lock, small-test pass, preflight, dry-run and input arming
must all be redone after restart.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from RuntimePaths import atomic_write_text, data_dir

SCHEMA = 2
SUPPORTED_SCHEMAS = (1, 2)
RECOVERY_DIR = data_dir() / "recovery"
STATE_FILE = RECOVERY_DIR / "session-recovery.json"
IMAGE_FILE = RECOVERY_DIR / "last-image.png"
RENDER_FILE = RECOVERY_DIR / "render-resume.json"

_OPTION_KEYS = {
    "quality", "speed", "precision", "mode", "shape_order", "shape_model",
    "max_stroke_cap", "progressive_rendering", "planning_watchdog",
    "time_budget_mode", "target_stroke_count", "target_stroke_custom",
    "drawing_style", "render_style", "draw_quality", "human_mode", "gpu_mode", "gpu_vram",
    "gpu_performance", "cpu_workers", "cpu_engine", "ram_budget",
    "ram_custom_mb", "planning_resolution", "background_fill",
    "background_simplification", "fill_engine", "color_grouping", "color_workflow", "stroke_optimizer", "adaptive_detail", "color_rendering",
    "color_layers", "custom_color_workflow", "exact_color_limit", "stroke_optimizer", "tool_strategy",
    "portrait_focus", "skip_white", "contrast", "outline", "brush_px",
    "max_seconds", "paint_simple", "paint_tool",
}


def _safe_primitive(value):
    if isinstance(value, bool):
        return value
    if type(value) in (int, float):
        return value
    if isinstance(value, str):
        return value[:200]
    return None


def _clean_target_lock(value):
    """Store a non-authoritative target-lock hint; never a restored pass state."""
    if not isinstance(value, dict):
        return None
    allowed = ('version','profile','paint_tool','target_dpi','drawing_area_rel','image_size','palette_required')
    out = {}
    for key in allowed:
        raw = value.get(key)
        if isinstance(raw, bool) or type(raw) in (int, float) or isinstance(raw, str):
            out[key] = raw
        elif isinstance(raw, (list, tuple)):
            try:
                out[key] = json.loads(json.dumps(raw))
            except (TypeError, ValueError):
                pass
    return out or None


def save_snapshot(*, profile: str, options: dict, saved_area=None, image=None, clear_render_resume=False, target_lock=None) -> Path:
    """Write a bounded local checkpoint. ``image=None`` preserves any old cache."""
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = {}
    for key in _OPTION_KEYS:
        if key in options:
            value = _safe_primitive(options[key])
            if value is not None:
                cleaned[key] = value
    area = None
    if isinstance(saved_area, (list, tuple)) and len(saved_area) == 2:
        try:
            points = [[int(p[0]), int(p[1])] for p in saved_area]
            if all(abs(v) <= 200000 for p in points for v in p):
                area = points
        except (TypeError, ValueError, IndexError):
            area = None
    if image is not None:
        # PNG keeps the recovered source deterministic and local. Atomic rename
        # avoids leaving a half-written cache if the process is interrupted.
        temp = IMAGE_FILE.with_suffix('.png.tmp')
        try:
            image.convert('RGBA').save(temp, format='PNG')
            temp.replace(IMAGE_FILE)
        finally:
            temp.unlink(missing_ok=True)
    if clear_render_resume:
        clear_render_progress()
    state = {
        "schema": SCHEMA,
        "created_at": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        "profile": str(profile or '')[:160],
        "options": cleaned,
        "saved_area": area,
        "has_image": IMAGE_FILE.exists(),
        "target_lock_hint": _clean_target_lock(target_lock) if 'target_lock' in locals() else None,
        "safety": {
            "drawing_armed": False,
            "target_lock_restored": False,
            "preflight_restored": False,
            "dry_run_restored": False,
            "small_test_restored": False,
        },
    }
    atomic_write_text(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2))
    return STATE_FILE


def _load_render_resume(value=None):
    try:
        from RenderResume import validate_progress
        raw = json.loads(RENDER_FILE.read_text(encoding='utf-8')) if value is None else value
        return validate_progress(raw)
    except Exception:
        return None

def save_render_progress(progress: dict) -> Path:
    """Atomically persist render progress in its own checkpoint file.

    This is deliberately separate from session-recovery.json. If this file is
    corrupt or incompatible, the session checkpoint can still restore the image
    and settings while rendering restarts safely from color 1.
    """
    from RenderResume import validate_progress
    clean = validate_progress(progress)
    if clean is None:
        raise ValueError('Invalid render resume checkpoint.')
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(RENDER_FILE, json.dumps(clean, ensure_ascii=False, indent=2))
    return RENDER_FILE

def clear_render_progress() -> None:
    try:
        RENDER_FILE.unlink(missing_ok=True)
    except OSError:
        pass

def load_render_progress() -> dict | None:
    return _load_render_resume()

def load_snapshot() -> dict | None:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict) or raw.get('schema') not in SUPPORTED_SCHEMAS:
        return None
    profile = raw.get('profile')
    options = raw.get('options')
    if not isinstance(profile, str) or not isinstance(options, dict):
        return None
    cleaned = {}
    for key in _OPTION_KEYS:
        if key in options:
            value = _safe_primitive(options[key])
            if value is not None:
                cleaned[key] = value
    area = raw.get('saved_area')
    valid_area = None
    if isinstance(area, list) and len(area) == 2:
        try:
            valid_area = [[int(p[0]), int(p[1])] for p in area]
        except (TypeError, ValueError, IndexError):
            valid_area = None
    return {
        "schema": SCHEMA,
        "created_at": str(raw.get('created_at') or '')[:80],
        "profile": profile[:160],
        "options": cleaned,
        "saved_area": valid_area,
        "has_image": bool(raw.get('has_image')) and IMAGE_FILE.exists(),
        "target_lock_hint": _clean_target_lock(raw.get('target_lock_hint')),
        "render_resume": load_render_progress(),
    }


def load_cached_image():
    if not IMAGE_FILE.exists():
        return None
    from PIL import Image
    try:
        with Image.open(IMAGE_FILE) as image:
            return image.convert('RGBA').copy()
    except (OSError, ValueError):
        return None


def clear_snapshot() -> None:
    for path in (STATE_FILE, RENDER_FILE, IMAGE_FILE, IMAGE_FILE.with_suffix('.png.tmp')):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        RECOVERY_DIR.rmdir()
    except OSError:
        pass


def diagnostics_summary() -> dict:
    state = load_snapshot()
    if not state:
        return {"available": False}
    return {
        "available": True,
        "created_at": state.get('created_at', ''),
        "profile": state.get('profile', ''),
        "has_cached_image": bool(state.get('has_image')),
        "saved_area_available": state.get('saved_area') is not None,
        "render_resume": {
            "completed_count": int((state.get('render_resume') or {}).get('completed_count',0)),
            "total_colors": int((state.get('render_resume') or {}).get('total_colors',0)),
            "sequence_level": bool((state.get('render_resume') or {}).get('sequence_level',False)),
            "sequence_completed_count": int((state.get('render_resume') or {}).get('sequence_completed_count',0)),
            "sequence_total": int((state.get('render_resume') or {}).get('sequence_total',0)),
            "sequence_coverage_percent": float((state.get('render_resume') or {}).get('sequence_coverage_percent',0.0)),
        },
        "restores_armed_state": False,
    }
