"""Local measured calibration for Image Draw Bot draw-time estimates.

Timing data is isolated by drawing profile and execution policy. Paint, Gartic and Skribbl
now have separate files, and each timing key also includes the active tool,
brush width and color workflow so learned costs cannot silently leak between
materially different delivery setups.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from RuntimePaths import atomic_write_text, data_dir, file_transaction, is_finite_number, read_json
from ProfileStorage import profile_timing_file, safe_profile_key

# Legacy shared database. It is read only for one-time per-profile migration.
FILE = data_dir() / "draw-time-calibration.json"
VERSION = 4


def _empty() -> dict[str, Any]:
    return {"version": VERSION, "profiles": {}}


def _profile(options: dict[str, Any]) -> str:
    return safe_profile_key(options.get("profile_key") or options.get("profile_name") or "generic")


def _legacy_key(options: dict[str, Any]) -> str:
    profile = _profile(options)
    speed = _token(options.get("speed"), "Balanced")
    precision = _token(options.get("precision"), "High")
    region = "region" if bool(options.get("use_region_fill_engine")) else "legacy"
    return f"{profile}|{speed}|{precision}|{region}"


def _token(value: Any, fallback: str) -> str:
    text=str(value or fallback).strip().lower().replace(" ", "-")
    return quote(text or fallback, safe='-_. /')


def _v2_key(options: dict[str, Any]) -> str:
    base = _legacy_key(options)
    tool = _token(options.get("effective_paint_tool") or options.get("paint_tool") or options.get("tool_strategy"), "default")
    try:
        brush = max(1, min(128, int(options.get("brush_px") or 1)))
    except Exception:
        brush = 1
    workflow = _token(options.get("custom_color_workflow"), "calibrated-palette")
    return f"{base}|tool={tool}|brush={brush}|color={workflow}"


def _key(options: dict[str, Any]) -> str:
    base=_v2_key(options)
    mode=_token(options.get("drawing_mode") or options.get("mode"),"default")
    preset=_token(options.get("render_preset"),"manual")
    quality=_token(options.get("draw_quality"),"balanced")
    style=_token(options.get("render_style"),"auto")
    style_profile=_token(options.get("drawing_style_resolved") or options.get("drawing_style"),"auto")
    return f"{base}|mode={mode}|preset={preset}|quality={quality}|style={style}|drawing-style={style_profile}"


def _load_raw(path: Path, *, accept_legacy_version: bool = False) -> dict[str, Any]:
    try:
        raw = read_json(path)
        version = raw.get("version") if isinstance(raw, dict) else None
        valid_version = type(version) is int and (version == VERSION or (accept_legacy_version and version in (1,2,3)))
        if not isinstance(raw, dict) or not valid_version or not isinstance(raw.get("profiles"), dict):
            return _empty()
        return {"version": VERSION, "profiles": {
            key: dict(item) for key, item in raw['profiles'].items()
            if isinstance(key, str) and _valid_item(item)
        }}
    except (OSError, ValueError, TypeError):
        return _empty()


def _valid_item(item):
    if not isinstance(item, dict) or type(item.get('samples')) is not int or not 0 <= item['samples'] <= 1_000_000_000:
        return False
    for name, default in (('ratio_ema', 1.0), ('mape_ema', 0.0)):
        value = item.get(name, default)
        if not is_finite_number(value) or value < 0:
            return False
    for name in ('operation_runtime_ema', 'last_operation_runtime', 'last_operation_counts'):
        if name in item and not isinstance(item[name], dict):
            return False
    return True


def load_all(path: Path = FILE) -> dict[str, Any]:
    """Compatibility reader for an explicitly supplied database path."""
    return _load_raw(Path(path), accept_legacy_version=True)


def _resolved_path(options: dict[str, Any], path: Path | None) -> Path:
    return Path(path) if path is not None else profile_timing_file(_profile(options))


def _ensure_profile_db(options: dict[str, Any], path: Path | None) -> tuple[Path, dict[str, Any]]:
    resolved = _resolved_path(options, path)
    if resolved.exists():
        return resolved, _load_raw(resolved, accept_legacy_version=True)
    if path is not None or not FILE.exists():
        return resolved, _empty()
    with file_transaction(resolved):
        if resolved.exists():
            return resolved, _load_raw(resolved, accept_legacy_version=True)
        # Only this profile's old keys are copied under the same publisher lock.
        db = _empty()
        prefix = _profile(options) + "|"
        db['profiles'] = {k: dict(v) for k, v in _load_raw(FILE, accept_legacy_version=True)['profiles'].items()
                          if k.startswith(prefix)}
        if db['profiles']:
            atomic_write_text(resolved, json.dumps(db, ensure_ascii=False, indent=2, allow_nan=False))
        return resolved, db


def load_profile(options: dict[str, Any], path: Path | None = None) -> dict[str, Any] | None:
    _resolved, db = _ensure_profile_db(options, path)
    item = db["profiles"].get(_key(options))
    if not isinstance(item, dict):
        item = db["profiles"].get(_v2_key(options))
    if not isinstance(item, dict):
        item = db["profiles"].get(_legacy_key(options))
    return dict(item) if isinstance(item, dict) else None


def correction_for(options: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    item = load_profile(options, path)
    if not item:
        return {"learned": False, "samples": 0, "ratio": 1.0, "mape": None, "key": _key(options),
                "profile_key": _profile(options), "storage_path": str(_resolved_path(options, path))}
    samples = max(0, int(item.get("samples") or 0))
    ratio = float(item.get("ratio_ema") or 1.0)
    if not math.isfinite(ratio) or ratio <= 0:
        ratio = 1.0
    mape = item.get("mape_ema")
    try:
        mape = max(0.0, min(2.0, float(mape)))
    except Exception:
        mape = None
    return {
        "learned": samples > 0,
        "samples": samples,
        "ratio": max(.55, min(4.0, ratio)),
        "mape": mape,
        "last_actual_seconds": item.get("last_actual_seconds"),
        "last_predicted_seconds": item.get("last_predicted_seconds"),
        "operation_runtime": {key: clean for key, value in (item.get("operation_runtime_ema") or item.get("last_operation_runtime") or {}).items()
                              if (clean := _runtime_entry(value, default_samples=1)) is not None},
        "operation_runtime_source": "ema" if item.get("operation_runtime_ema") else ("last-sample" if item.get("last_operation_runtime") else "none"),
        "operation_counts": dict(item.get("last_operation_counts") or {}),
        "seconds_per_completed_path": item.get("last_seconds_per_completed_path"),
        "key": _key(options),
        "profile_key": _profile(options),
        "storage_path": str(_resolved_path(options, path)),
    }


def _runtime_entry(item: Any, *, default_samples: int = 0) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    try:
        count=item.get('count', item.get('last_count', 0))
        samples=item.get('samples', default_samples or 0)
        observations=item.get('observations', count)
        last_count=item.get('last_count', count)
        if any(type(v) is not int or not 0 <= v <= 1_000_000_000 for v in (count, samples, observations, last_count)):
            return None
        total=float(item.get("total_seconds") or 0.0)
        avg=float(item.get("average_seconds") or 0.0)
        if not math.isfinite(total) or total < 0 or not math.isfinite(avg) or avg < 0:
            return None
        if avg<=0 and count>0 and total>0:
            avg=total/count
        last_average = float(item.get('last_average_seconds', avg))
    except (TypeError,ValueError,OverflowError):
        return None
    if not math.isfinite(avg) or avg<=0 or not math.isfinite(last_average) or last_average < 0:
        return None
    return {
        "average_seconds":avg,"samples":samples,"observations":observations,
        "last_average_seconds":last_average,
        "last_count":last_count,
        "count":count,"total_seconds":total,
    }


def _merge_operation_runtime(old_runtime: dict[str, Any] | None, new_runtime: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Merge one completed draw into stable per-operation timing EMAs."""
    out: dict[str, dict[str, Any]] = {}
    for key,item in (old_runtime if isinstance(old_runtime, dict) else {}).items():
        parsed=_runtime_entry(item,default_samples=1)
        if parsed is not None:
            out[str(key)]=parsed
    for key,item in (new_runtime if isinstance(new_runtime, dict) else {}).items():
        parsed=_runtime_entry(item)
        if parsed is None:
            continue
        name=str(key);prior=out.get(name)
        if prior is None:
            avg=parsed["average_seconds"];samples=1;observations=max(1,parsed["observations"])
        else:
            prior_samples=max(1,int(prior.get("samples") or 1))
            alpha=.45 if prior_samples<2 else (.28 if prior_samples<5 else .16)
            avg=float(prior["average_seconds"])*(1.0-alpha)+float(parsed["average_seconds"])*alpha
            samples=prior_samples+1
            observations=max(0,int(prior.get("observations") or 0))+max(1,int(parsed.get("observations") or 0))
        out[name]={
            "average_seconds":round(max(.000001,float(avg)),7),
            "samples":int(samples),"observations":int(observations),
            "last_average_seconds":round(float(parsed["average_seconds"]),7),
            "last_count":max(0,int(parsed.get("last_count") or parsed.get("observations") or 0)),
        }
    return out


def record_sample(options: dict[str, Any], predicted_seconds: float, actual_seconds: float, *,
                  completed_paths: int = 0, fill_actions: int = 0, operation_counts: dict[str, Any] | None = None,
                  operation_runtime: dict[str, Any] | None = None, path: Path | None = None) -> dict[str, Any]:
    try:
        predicted = float(predicted_seconds or 0.0)
        actual = float(actual_seconds or 0.0)
    except (TypeError, ValueError, OverflowError):
        return {"recorded": False, "reason": "invalid timing sample", "key": _key(options)}
    if predicted < 1.0 or actual < 1.0 or not math.isfinite(predicted) or not math.isfinite(actual):
        return {"recorded": False, "reason": "sample too small", "key": _key(options)}
    if bool(options.get("test_run")) or bool(options.get("dry_run_sampled")):
        return {"recorded": False, "reason": "test/dry-run sample", "key": _key(options)}
    if options.get("render_resume_state"):
        return {"recorded": False, "reason": "resume sample", "key": _key(options)}
    if any(type(v) is not int or v < 0 for v in (completed_paths, fill_actions)):
        return {"recorded": False, "reason": "invalid operation counts", "key": _key(options)}
    operation_counts = {str(k): v for k, v in (operation_counts if isinstance(operation_counts, dict) else {}).items()
                        if type(v) is int and 0 <= v <= 1_000_000_000}
    operation_runtime = {str(k): clean for k, v in (operation_runtime if isinstance(operation_runtime, dict) else {}).items()
                         if (clean := _runtime_entry(v)) is not None}

    ratio = max(.35, min(5.0, actual / predicted))
    abs_pct = abs(actual - predicted) / max(1.0, actual)
    with file_transaction(_resolved_path(options, path)):
        resolved, db = _ensure_profile_db(options, path)
        key = _key(options)
        old = db["profiles"].get(key)
        if not isinstance(old, dict):
            old = db["profiles"].get(_v2_key(options))
        if not isinstance(old, dict):
            old = db["profiles"].get(_legacy_key(options)) if isinstance(db["profiles"].get(_legacy_key(options)), dict) else {}
        samples = int(old.get("samples") or 0)
        old_ratio = float(old.get("ratio_ema") or ratio)
        old_mape = float(old.get("mape_ema", abs_pct))

        alpha = .42 if samples < 2 else (.28 if samples < 5 else .16)
        learned_ratio = ratio if samples == 0 else old_ratio * (1.0 - alpha) + ratio * alpha
        learned_mape = abs_pct if samples == 0 else old_mape * (1.0 - alpha) + abs_pct * alpha
        old_operation_runtime=old.get("operation_runtime_ema") or old.get("last_operation_runtime") or {}
        operation_runtime_ema=_merge_operation_runtime(old_operation_runtime, operation_runtime or {})
        item = {
            "key": key,
            "profile_key": _profile(options),
            "samples": samples + 1,
            "ratio_ema": round(max(.55, min(4.0, learned_ratio)), 6),
            "mape_ema": round(max(0.0, min(2.0, learned_mape)), 6),
            "last_ratio": round(ratio, 6),
            "last_predicted_seconds": round(predicted, 4),
            "last_actual_seconds": round(actual, 4),
            "last_completed_paths": max(0, int(completed_paths or 0)),
            "last_fill_actions": max(0, int(fill_actions or 0)),
            "last_seconds_per_completed_path": round(actual/max(1,int(completed_paths or 0)),6) if completed_paths else None,
            "last_operation_counts": {str(k):max(0,int(v or 0)) for k,v in (operation_counts or {}).items() if isinstance(v,(int,float))},
            "last_operation_runtime": {str(k):dict(v) for k,v in (operation_runtime or {}).items() if isinstance(v,dict)},
            "operation_runtime_ema": operation_runtime_ema,
            "operation_runtime_types": len(operation_runtime_ema),
            "updated_at": time.time(),
        }
        db["profiles"].pop(_legacy_key(options), None)
        db["profiles"][key] = item
        resolved.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(resolved, json.dumps(db, ensure_ascii=False, indent=2, allow_nan=False))
        result = dict(item)
        result["recorded"] = True
        result["storage_path"] = str(resolved)
        return result


def reset_profile(options: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Delete learned timing for exactly one isolated profile/tool/brush/workflow key."""
    with file_transaction(_resolved_path(options, path)):
        resolved, db = _ensure_profile_db(options, path)
        key = _key(options)
        v2 = _v2_key(options)
        legacy = _legacy_key(options)
        existed = key in db["profiles"] or v2 in db["profiles"] or legacy in db["profiles"]
        db["profiles"].pop(key, None)
        db["profiles"].pop(v2, None)
        db["profiles"].pop(legacy, None)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(resolved, json.dumps(db, ensure_ascii=False, indent=2))
        return {"reset": bool(existed), "key": key, "profile_key": _profile(options), "storage_path": str(resolved)}
