"""Step 27 — portable profile export/import for Image Draw Bot.

A .drawprofile is JSON.  It deliberately contains profile-owned renderer/resource
settings plus calibration metadata, but never runtime input authorization,
hardware benchmark output, timing feedback, target handles or other machine-only
state.  Imported calibration is always treated as unverified until the normal
Image Draw Bot setup/safety gates pass again.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from GameProfiles import (PROFILES, PROFILE_UI, clean_profile_name, prepare_custom_profile,
                          current_custom_profile_registry, register_custom_profiles,
                          CUSTOM_PROFILE_LOCK)
from ProfileIsolation import SETTING_NAMES
from ProfileStorage import (
    profile_auto_tuner_feedback_file,
    profile_correction_history_file,
    profile_layout_cache_file,
    profile_palette_file,
    profile_settings_file,
    profile_timing_file,
    profile_verified_color_file,
    safe_profile_key,
)
from RuntimePaths import atomic_write_text, data_dir, replace_text_files
from StabilityRC import migrate_settings
from Version import APP_VERSION

FORMAT_ID = "image-draw-bot-profile"
SCHEMA_VERSION = 1
MAX_PROFILE_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_ITEMS = 20000

RESOURCE_SETTING_NAMES = frozenset({
    "gpu_mode", "gpu_vram", "gpu_performance", "cpu_workers", "cpu_engine",
    "ram_budget", "ram_custom_mb", "planning_resolution", "resource_scheduler",
})

# save_settings() has a few newer settings that predate ProfileIsolation's compact
# list.  Keep an explicit allow-list so a profile file cannot restore arbitrary
# object attributes or future input-authorization flags.
EXTRA_PORTABLE_SETTING_NAMES = frozenset({
    "settings_schema", "use_region_fill_engine", "fill_aggressiveness",
    "detail_zoom", "quick_sketch_style", "quick_sketch_fill_preference", "hybrid_mode",
    "preview_mode", "auto_clear_canvas", "profile_extras",
})

CANVAS_SETTING_NAMES = frozenset({"corners", "canvas_anchor_detection"})
PORTABLE_SETTING_NAMES = frozenset(SETTING_NAMES) | EXTRA_PORTABLE_SETTING_NAMES | CANVAS_SETTING_NAMES

FORBIDDEN_SETTING_NAMES = frozenset({
    "draw_immediately", "auto_draw", "drop_action_pending", "manual_drop_in_start",
    "full_draw_armed", "target_handle", "target_window", "target_client_rect",
    "target_lock_passed", "target_lock_signature", "target_lock_fingerprint",
    "small_test_passed", "safety_preflight_passed", "dry_run_passed",
})

MACHINE_STATE_EXCLUDED = (
    "hardware benchmark / adapter signature",
    "draw timing calibration",
    "auto-tuner feedback",
    "correction history",
    "layout fingerprint cache",
    "verified-color runtime cache",
    "target window handles / input authorization",
)

_BUILTIN_KEYS = frozenset(value[0] for value in PROFILES.values() if not value[0].startswith("custom-"))
_CUSTOM_KEY_RE = re.compile(r"custom-[a-f0-9]{32}\Z")
_PROFILE_FILE_LOCK = threading.RLock()


class ProfilePortabilityError(ValueError):
    pass


def _json_guard(value, *, depth=0, counter=None):
    """Reject non-JSON/extreme payloads before they reach app settings/files."""
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_ITEMS or depth > MAX_JSON_DEPTH:
        raise ProfilePortabilityError("Profile data is too large or deeply nested.")
    if type(value) is float and not math.isfinite(value):
        raise ProfilePortabilityError("Profile numbers must be finite.")
    if value is None or type(value) in (bool, int, float, str):
        if isinstance(value, str) and len(value) > 200000:
            raise ProfilePortabilityError("Profile contains an oversized text value.")
        return
    if isinstance(value, list):
        for item in value:
            _json_guard(item, depth=depth + 1, counter=counter)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 200:
                raise ProfilePortabilityError("Profile contains an invalid JSON key.")
            _json_guard(item, depth=depth + 1, counter=counter)
        return
    raise ProfilePortabilityError("Profile contains a value that is not portable JSON.")


def _profile_identity(name: str):
    if name not in PROFILES:
        raise ProfilePortabilityError("Unknown Image Draw Bot profile.")
    key = str(PROFILES[name][0])
    return name, key


def _matching_profile_identity(name: str):
    """Resolve the same name equivalence used by custom-profile registration."""
    folded = name.casefold()
    with CUSTOM_PROFILE_LOCK:
        matches = [(label, str(value[0])) for label, value in PROFILES.items()
                   if label.casefold() == folded]
    if len(matches) > 1:
        raise ProfilePortabilityError('Conflicting profile names must be resolved before import.')
    return matches[0] if matches else None


def _checked_import_identity(name, expected_name=None, expected_key=None, *, expected_absent=False):
    identity = _matching_profile_identity(name)
    if expected_absent and identity is not None:
        raise ProfilePortabilityError('A profile with this name appeared. Open Import again to choose Replace or Copy.')
    if ((expected_name is not None and (identity is None or identity[0] != expected_name)) or
            (expected_key is not None and (identity is None or identity[1] != expected_key))):
        raise ProfilePortabilityError('The existing profile changed. Open Import again before replacing or copying it.')
    return identity


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfilePortabilityError(f"Profile contains duplicate JSON key: {key[:80]}")
        result[key] = value
    return result


def _decode_profile(raw):
    try:
        result = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_json_object)
        _json_guard(result)
        return result
    except RecursionError as error:
        raise ProfilePortabilityError("Profile data is too deeply nested.") from error


def _read_json(path: Path):
    try:
        if not Path(path).is_file():
            return None
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
        if len(raw) > MAX_PROFILE_BYTES:
            raise ProfilePortabilityError(f"{Path(path).name} is too large to export safely.")
        value = _decode_profile(raw)
    except UnicodeDecodeError as error:
        raise ProfilePortabilityError(f"{Path(path).name} is not UTF-8 JSON.") from error
    except json.JSONDecodeError as error:
        raise ProfilePortabilityError(f"{Path(path).name} contains invalid JSON.") from error
    _json_guard(value)
    return value


def _portable_calibration_paths(profile_key: str, root: Path | None = None):
    """Only calibration inputs, never learned runtime/hardware caches."""
    key = safe_profile_key(profile_key)
    root = Path(root) if root is not None else data_dir()
    paths = {
        "palette": root / ("calibration.json" if key == "generic" else f"calibration-{key}.json"),
        "exact_colors": root / f"exact-colors-{key}.json",
    }
    if key == "microsoft-paint":
        paths["tools"] = root / "paint-tools-microsoft-paint.json"
    else:
        paths["tools"] = root / f"app-tools-{key}.json"
    return paths


def portable_path_map(profile_key: str, root: Path | None = None):
    """Public/testable destination map; keys are profile-isolated."""
    key = safe_profile_key(profile_key)
    root = Path(root) if root is not None else data_dir()
    result = {"settings": root / ("settings.json" if key == "generic" else f"settings-{key}.json")}
    result.update(_portable_calibration_paths(key, root))
    return result


def sanitize_settings(data: dict, *, strict: bool = True) -> dict:
    if not isinstance(data, dict):
        raise ProfilePortabilityError("Profile settings must be a JSON object.")
    from SettingsValidation import validated_settings
    try:
        migrated = validated_settings(data, strict=strict)
    except ValueError as error:
        raise ProfilePortabilityError(str(error)) from error
    for forbidden in FORBIDDEN_SETTING_NAMES:
        migrated.pop(forbidden, None)
    unknown = sorted(set(migrated) - PORTABLE_SETTING_NAMES)
    if strict and unknown:
        raise ProfilePortabilityError("Profile contains unsupported settings: " + ", ".join(unknown[:8]))
    clean = {key: deepcopy(value) for key, value in migrated.items() if key in PORTABLE_SETTING_NAMES}
    clean["settings_schema"] = int(migrated.get("settings_schema", 2) or 2)
    _json_guard(clean)
    return clean


def split_settings(settings: dict):
    settings = sanitize_settings(settings)
    canvas = {key: settings.pop(key) for key in tuple(CANVAS_SETTING_NAMES) if key in settings}
    resources = {key: settings.pop(key) for key in tuple(RESOURCE_SETTING_NAMES) if key in settings}
    ui = {}
    if "profile_extras" in settings:
        ui["profile_extras"] = settings.pop("profile_extras")
    return settings, resources, ui, canvas


def flatten_settings(package_settings: dict, canvas: dict | None = None) -> dict:
    if not isinstance(package_settings, dict):
        raise ProfilePortabilityError("Profile settings section is invalid.")
    if set(package_settings) - {"renderer", "resources", "ui"}:
        raise ProfilePortabilityError("Profile contains an unknown settings section.")
    clean = {}
    for section in ("renderer", "resources", "ui"):
        values = package_settings.get(section, {})
        if not isinstance(values, dict):
            raise ProfilePortabilityError(f"Profile {section} settings must be an object.")
        overlap = set(clean).intersection(values)
        if overlap:
            raise ProfilePortabilityError("Profile contains duplicate setting names.")
        clean.update(values)
    if canvas is not None:
        if not isinstance(canvas, dict):
            raise ProfilePortabilityError("Canvas metadata must be an object.")
        for key in CANVAS_SETTING_NAMES:
            if key in canvas:
                if key in clean:
                    raise ProfilePortabilityError('Profile repeats canvas metadata in its settings section.')
                clean[key] = canvas[key]
    return sanitize_settings(clean)


def _validate_canvas(canvas: dict):
    if not isinstance(canvas, dict):
        raise ProfilePortabilityError("Canvas metadata must be an object.")
    unknown = set(canvas) - CANVAS_SETTING_NAMES
    if unknown:
        raise ProfilePortabilityError("Canvas metadata contains unsupported fields.")
    corners = canvas.get("corners")
    if corners is not None:
        if not (isinstance(corners, list) and len(corners) == 2):
            raise ProfilePortabilityError("Canvas corners must contain two points.")
        for point in corners:
            if not (isinstance(point, list) and len(point) == 2 and all(type(v) is int for v in point)):
                raise ProfilePortabilityError("Canvas coordinates are invalid.")
            if any(abs(v) > 1000000 for v in point):
                raise ProfilePortabilityError("Canvas coordinates are outside the supported range.")
    if corners is not None and (corners[0][0] == corners[1][0] or corners[0][1] == corners[1][1]):
        raise ProfilePortabilityError("Canvas must have non-zero width and height.")
    anchors = canvas.get("canvas_anchor_detection")
    if anchors is not None and not isinstance(anchors, dict):
        raise ProfilePortabilityError("Canvas anchor metadata is invalid.")
    _json_guard(canvas)


def _validate_source_key(key: str):
    if key in _BUILTIN_KEYS or _CUSTOM_KEY_RE.fullmatch(key):
        return key
    raise ProfilePortabilityError("Profile target key is invalid.")


def migrate_package(data: dict) -> dict:
    """Migrate the initial pre-schema prototype to the Step 27 v1 schema."""
    if not isinstance(data, dict):
        raise ProfilePortabilityError("Profile file must contain a JSON object.")
    version = data.get("schema_version", 0)
    if type(version) is not int or version < 0:
        raise ProfilePortabilityError("Profile schema version is invalid.")
    if version > SCHEMA_VERSION:
        raise ProfilePortabilityError(
            f"This profile uses schema {version}; this Image Draw Bot build supports up to {SCHEMA_VERSION}."
        )
    if version == SCHEMA_VERSION:
        return deepcopy(data)

    # Schema 0 was an internal Step 27 prototype: flat renderer/resource fields.
    name = data.get("name") or data.get("profile_name") or data.get("target")
    key = data.get("profile_key") or data.get("target_key") or "generic"
    renderer = data.get("renderer_settings") or data.get("settings") or {}
    resources = data.get("resource_limits") or {}
    calibration = data.get("calibration") or {}
    if data.get("palette") is not None and isinstance(calibration, dict):
        calibration = dict(calibration)
        calibration.setdefault("palette", data.get("palette"))
    return {
        "format": FORMAT_ID,
        "schema_version": 1,
        "created_by": {"app_version": str(data.get("app_version") or "legacy")},
        "profile": {"name": name, "key": key},
        "settings": {"renderer": renderer, "resources": resources, "ui": {}},
        "canvas": data.get("canvas") or {},
        "calibration": calibration,
        "safety": {"requires_reverification": True, "machine_specific_state_included": False},
    }


def validate_package(data: dict) -> dict:
    _json_guard(data)
    data = migrate_package(data)
    if data.get("format") != FORMAT_ID or data.get("schema_version") != SCHEMA_VERSION:
        raise ProfilePortabilityError("This is not a supported Image Draw Bot .drawprofile file.")
    _json_guard(data)

    profile = data.get("profile")
    if not isinstance(profile, dict):
        raise ProfilePortabilityError("Profile identity is missing.")
    name = profile.get("name")
    key = profile.get("key")
    try:
        name = clean_profile_name(name)
    except ValueError as error:
        raise ProfilePortabilityError(str(error)) from error
    if not isinstance(key, str):
        raise ProfilePortabilityError("Profile target key is missing.")
    _validate_source_key(key)
    existing = _matching_profile_identity(name)
    if existing is not None and not existing[1].startswith("custom-") and key != existing[1]:
        raise ProfilePortabilityError("Built-in profile name does not match its Image Draw Bot target key.")

    for section in ("canvas", "settings", "calibration", "safety"):
        if section in data and not isinstance(data[section], dict):
            raise ProfilePortabilityError(f"Profile {section} section must be an object.")
    canvas = deepcopy(data.get("canvas") or {})
    _validate_canvas(canvas)
    clean_settings = flatten_settings(data.get("settings") or {}, canvas)
    renderer, resources, ui, clean_canvas = split_settings(clean_settings)

    calibration = data.get("calibration") or {}
    if not isinstance(calibration, dict):
        raise ProfilePortabilityError("Calibration section must be an object.")
    unknown_calibration = set(calibration) - {"palette", "tools", "exact_colors"}
    if unknown_calibration:
        raise ProfilePortabilityError("Calibration contains unsupported sections.")
    for logical, payload in calibration.items():
        if payload is not None and not isinstance(payload, (dict, list)):
            raise ProfilePortabilityError(f"Calibration section {logical} is invalid.")
        _json_guard(payload)

    palette = calibration.get("palette")
    if palette is not None:
        try:
            from Colors import validate_calibration
            validate_calibration(palette, profile_key=key)
        except (ValueError, TypeError) as error:
            raise ProfilePortabilityError(f"Palette calibration failed validation: {error}") from error

    tools = calibration.get("tools")
    if tools is not None:
        try:
            if key == "microsoft-paint":
                from PaintTools import validate_tool_calibration
                validate_tool_calibration(tools)
            else:
                from AppTools import validate_calibration as validate_app_tools
                validate_app_tools(tools, key)
        except (ValueError, TypeError) as error:
            raise ProfilePortabilityError(f"Tool calibration failed validation: {error}") from error

    exact_colors = calibration.get("exact_colors")
    if exact_colors is not None:
        try:
            from ExactColorTools import validate as validate_exact_colors
            validate_exact_colors(exact_colors, key)
        except (ValueError, TypeError) as error:
            raise ProfilePortabilityError(f"Exact-color calibration failed validation: {error}") from error

    safety = data.get("safety") or {}
    if not isinstance(safety, dict):
        raise ProfilePortabilityError("Safety metadata is invalid.")
    if safety.get("machine_specific_state_included") is True:
        raise ProfilePortabilityError("Profile contains machine-specific state and will not be imported.")

    return {
        "format": FORMAT_ID,
        "schema_version": SCHEMA_VERSION,
        "created_at": data.get("created_at"),
        "created_by": deepcopy(data.get("created_by") or {}),
        "profile": {"name": name.strip(), "key": key},
        "settings": {"renderer": renderer, "resources": resources, "ui": ui},
        "canvas": clean_canvas,
        "calibration": deepcopy(calibration),
        "safety": {
            "requires_reverification": True,
            "machine_specific_state_included": False,
            "excluded_state": list(MACHINE_STATE_EXCLUDED),
        },
    }


def build_package(profile_name: str, settings: dict, calibration: dict | None = None) -> dict:
    name, key = _profile_identity(profile_name)
    renderer, resources, ui, canvas = split_settings(settings)
    package = {
        "format": FORMAT_ID,
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": {"app": "Image Draw Bot", "app_version": APP_VERSION},
        "profile": {"name": name, "key": key},
        "settings": {"renderer": renderer, "resources": resources, "ui": ui},
        "canvas": canvas,
        "calibration": deepcopy(calibration or {}),
        "safety": {
            "requires_reverification": True,
            "machine_specific_state_included": False,
            "excluded_state": list(MACHINE_STATE_EXCLUDED),
        },
    }
    return validate_package(package)


def read_profile_file(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ProfilePortabilityError("The selected profile file does not exist.")
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ProfilePortabilityError("The profile file is larger than 8 MB.")
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
        if len(raw) > MAX_PROFILE_BYTES:
            raise ProfilePortabilityError('The profile file is larger than 8 MB.')
        data = _decode_profile(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProfilePortabilityError("The selected file is not valid UTF-8 JSON.") from error
    return validate_package(data)


def write_profile_file(path: Path, package: dict) -> Path:
    clean = validate_package(package)
    path = Path(path)
    if path.suffix.lower() not in (".drawprofile", ".json"):
        path = path.with_suffix(".drawprofile")
    text = json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True)
    if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ProfilePortabilityError("Profile is too large to save safely.")
    atomic_write_text(path, text)
    return path


def _capture_calibration(profile_key: str):
    result = {}
    for logical, path in _portable_calibration_paths(profile_key).items():
        payload = _read_json(path)
        if payload is not None:
            result[logical] = payload
    return result


def _require_idle_profile(app):
    if (getattr(app,'activity',None) or getattr(app,'closing',False) or
            getattr(app,'pending_clear_drawing',None) is not None or
            getattr(app,'profile_change_in_progress',False) or
            getattr(app,'profile_change_after',None) is not None):
        raise ProfilePortabilityError('Wait for the current operation or profile change to finish before managing profiles.')


def package_from_app(app) -> dict:
    _require_idle_profile(app)
    profile_name = str(app.game.get())
    name, key = _profile_identity(profile_name)
    try:
        if app.save_settings() is False:
            raise OSError('The current settings could not be saved.')
    except Exception as error:
        raise ProfilePortabilityError(f"Could not save current profile settings: {error}") from error
    settings_path = Path(getattr(app, "settings_path", profile_settings_file(key)))
    settings = _read_json(settings_path) or {}
    return build_package(name, sanitize_settings(settings), _capture_calibration(key))


def _rewrite_calibration_owner(payload, destination_key: str):
    if payload is None:
        return None
    clean = deepcopy(payload)
    if isinstance(clean, dict) and "profile" in clean:
        clean["profile"] = destination_key
    return clean


def _package_file_changes(package, destination_key, root=None):
    package = validate_package(package)
    destination_key = safe_profile_key(destination_key)
    settings = flatten_settings(package["settings"], package.get("canvas"))
    settings["settings_schema"] = 2
    paths = portable_path_map(destination_key, root)
    changes = {paths['settings']: json.dumps(settings, ensure_ascii=False, indent=2)}
    calibration = package.get("calibration") or {}
    for logical in ("palette", "tools", "exact_colors"):
        payload = calibration.get(logical)
        path = paths[logical]
        if payload is None:
            changes[path] = None
            continue
        payload = _rewrite_calibration_owner(payload, destination_key)
        if logical == 'tools' and package['profile']['key'] == 'microsoft-paint' and destination_key != 'microsoft-paint':
            # A custom profile uses the generic tool protocol. Paint dropdown
            # menus/presets are multi-click actions, never a generic Brush click.
            from PaintTools import validate_tool_calibration
            paint = validate_tool_calibration(payload)
            if paint.get('version', 0) < 2:
                changes[path] = None  # Unanchored legacy controls need recapture.
                continue
            from AppTools import validate_calibration
            payload = validate_calibration({
                'version': 1, 'profile': destination_key, 'anchor': paint['anchor'],
                'tools': {name: value for name, value in paint['tools'].items()
                          if name in ('Fill', 'Eraser')},
            }, destination_key)
        changes[path] = json.dumps(payload, ensure_ascii=False, indent=2)
    return paths, changes


def _replace_profile_files(changes):
    """Use the shared staged publisher, preserving the profile-facing error."""
    try:
        replace_text_files(changes)
    except (OSError, ValueError) as error:
        raise ProfilePortabilityError(str(error)) from error


def apply_package_to_paths(package: dict, destination_key: str, *, root: Path | None = None):
    """Write one profile only, with rollback if one of its files cannot publish."""
    paths, changes = _package_file_changes(package, destination_key, root)
    _replace_profile_files(changes)
    return paths


def unique_copy_name(base_name: str, existing=None) -> str:
    existing = {str(name).casefold() for name in (PROFILES if existing is None else existing)}
    base_name = str(base_name).strip() or "Profile"
    stem = f"{base_name[:39]} (Imported)"
    if stem.casefold() not in existing:
        return stem
    for index in range(2, 1000):
        suffix = f" (Imported {index})"
        candidate = base_name[: max(1, 50 - len(suffix))] + suffix
        if candidate.casefold() not in existing:
            return candidate
    raise ProfilePortabilityError("Could not create a unique imported profile name.")


def profile_reset_paths(profile_key: str):
    """Every file removed by Reset profile; all are scoped to one profile."""
    key = safe_profile_key(profile_key)
    paths = list(portable_path_map(key).values())
    paths.extend((
        profile_timing_file(key), profile_auto_tuner_feedback_file(key),
        profile_correction_history_file(key), profile_layout_cache_file(key),
        profile_verified_color_file(key),
    ))
    # Paint had one legacy tool path. Only delete it while resetting Paint.
    if key == "microsoft-paint":
        paths.append(data_dir() / "paint-tools.json")
    # De-duplicate without touching another profile's names.
    out = []
    seen = set()
    for path in paths:
        path = Path(path)
        if path not in seen:
            seen.add(path); out.append(path)
    return tuple(out)


def _reload_profile(app, name: str):
    """Configuration-only reload; it must not bypass normal safety/setup gates."""
    app.game.set(name)
    if hasattr(app, "profile_selector"):
        try:
            app.profile_selector.configure(values=list(PROFILES))
        except Exception:
            pass
    apply_now = getattr(app, "_apply_profile_change", None)
    if callable(apply_now):
        apply_now(name)
    else:
        app.change_profile()


def import_package_into_app(app, package: dict, *, action: str = "replace", copy_name: str | None = None,
                            expected_name=None, expected_key=None, expected_absent=False):
    _require_idle_profile(app)
    package = validate_package(package)
    source_name = package["profile"]["name"]
    if action not in ("replace", "copy"):
        raise ProfilePortabilityError("Import action must be Replace or Import as copy.")
    _checked_import_identity(source_name, expected_name, expected_key, expected_absent=expected_absent)

    try:
        if hasattr(app, "save_settings"):
            if app.save_settings() is False:
                raise OSError('The current settings could not be saved.')
    except Exception as error:
        raise ProfilePortabilityError(f"Could not save the current profile before import: {error}") from error

    with CUSTOM_PROFILE_LOCK:
        _require_idle_profile(app)
        existing = _checked_import_identity(source_name, expected_name, expected_key,
                                           expected_absent=expected_absent)
        destination_name = source_name if action == 'replace' else (copy_name or unique_copy_name(source_name))
        registry = None
        if action == 'copy' or existing is None:
            try:
                destination_name, destination_key, registry = prepare_custom_profile(
                    destination_name, data_dir() / 'profiles.json')
            except (OSError, ValueError) as error:
                raise ProfilePortabilityError(str(error)) from error
        else:
            destination_name, destination_key = existing
        _paths, changes = _package_file_changes(package, destination_key)
        if registry is not None:
            changes[data_dir() / 'profiles.json'] = json.dumps(registry, ensure_ascii=False)
        _replace_profile_files(changes)
        if registry is not None:
            register_custom_profiles(registry)

    # Imported geometry/calibration can be useful metadata, but never counts as
    # a completed safety test. _apply_profile_change clears locks, target handles,
    # plan state and small-test state before reading the imported profile files.
    _reload_profile(app, destination_name)
    if hasattr(app, "status"):
        try:
            app.status.set(
                f"Imported {destination_name}. Re-verify target, palette/canvas and run the normal safety tests before drawing."
            )
        except Exception:
            pass
    return destination_name


def reset_profile(app, *, expected_name=None, expected_key=None):
    _require_idle_profile(app)
    name, key = _profile_identity(str(app.game.get()))
    if ((expected_name is not None and name != expected_name) or
            (expected_key is not None and key != expected_key)):
        raise ProfilePortabilityError('The selected profile changed. Open profile management again.')
    # Do not let the profile-change wrapper save the old values after deletion.
    changes = {path: None for path in profile_reset_paths(key)}
    # A missing per-profile ETA file triggers one-time migration from the old
    # shared database. Keep an empty current-format record to make Reset final.
    from DrawTimeCalibration import VERSION as TIMING_VERSION
    changes[profile_timing_file(key)] = json.dumps({'version': TIMING_VERSION, 'profiles': {}})
    _replace_profile_files(changes)
    _reload_profile(app, name)
    if hasattr(app, "status"):
        try: app.status.set(f"{name} restored to Image Draw Bot defaults. Calibration/setup must be verified again.")
        except Exception: pass
    return name


def _managed_custom_identity(app, expected_name=None, expected_key=None):
    _require_idle_profile(app)
    name, key = _profile_identity(str(app.game.get()))
    if ((expected_name is not None and name != expected_name) or
            (expected_key is not None and key != expected_key)):
        raise ProfilePortabilityError('The selected profile changed. Open profile management again.')
    if _CUSTOM_KEY_RE.fullmatch(key) is None:
        raise ProfilePortabilityError('Only your custom profiles can be renamed or removed. Built-in profiles can be reset instead.')
    return name, key


def _reload_managed_profile(app, name):
    # Discard transient authorization/resume state without deleting the shared
    # recovery snapshot. Only the selected profile's canonical files are removed.
    for method_name in ('_disarm_manual_drop_in', '_disarm_full_draw'):
        method = getattr(app, method_name, None)
        if callable(method):
            method('custom profile changed')
    app.pending_render_resume = None
    mouse = getattr(app, 'mouse', None)
    disarm = getattr(mouse, 'disarm_input', None)
    if callable(disarm):
        try: disarm()
        except OSError: pass
    _reload_profile(app, name)


def rename_custom_profile(app, new_name, *, expected_name=None, expected_key=None):
    """Rename one label while preserving its storage UUID and every owned file."""
    name, key = _managed_custom_identity(app, expected_name, expected_key)
    try:
        new_name = clean_profile_name(new_name)
    except ValueError as error:
        raise ProfilePortabilityError(str(error)) from error
    if new_name == name:
        return name
    registry_path = data_dir() / 'profiles.json'
    with CUSTOM_PROFILE_LOCK:
        try:
            registry = current_custom_profile_registry(registry_path)
        except (OSError, ValueError) as error:
            raise ProfilePortabilityError(str(error)) from error
        if registry.get(name) != key:
            raise ProfilePortabilityError('The custom profile registry changed. Reload profiles before renaming.')
        other_names = {value.casefold() for value in (*PROFILES, *registry) if value != name}
        if new_name.casefold() in other_names:
            raise ProfilePortabilityError('Choose a unique name containing 1–50 characters.')
        if hasattr(app, 'save_settings') and app.save_settings() is False:
            raise ProfilePortabilityError('Could not save the current settings. The profile was not renamed.')
        registry = {new_name if old_name == name else old_name: value
                    for old_name, value in registry.items()}
        _replace_profile_files({registry_path: json.dumps(registry, ensure_ascii=False)})
        PROFILES.pop(name); PROFILE_UI.pop(name, None)
        register_custom_profiles(registry)
    _reload_managed_profile(app, new_name)
    return new_name


def remove_custom_profile(app, *, expected_name, expected_key):
    """Delete one explicitly selected custom namespace with publication rollback."""
    name, key = _managed_custom_identity(app, expected_name, expected_key)
    registry_path = data_dir() / 'profiles.json'
    with CUSTOM_PROFILE_LOCK:
        try:
            registry = current_custom_profile_registry(registry_path)
        except (OSError, ValueError) as error:
            raise ProfilePortabilityError(str(error)) from error
        if registry.get(name) != key:
            raise ProfilePortabilityError('The custom profile registry changed. Reload profiles before removing it.')
        registry.pop(name)
        changes = {path: None for path in profile_reset_paths(key)}
        changes[registry_path] = json.dumps(registry, ensure_ascii=False)
        _replace_profile_files(changes)
        PROFILES.pop(name); PROFILE_UI.pop(name, None)
        register_custom_profiles(registry)
    _reload_managed_profile(app, 'Other drawing app')
    return name


def rename_custom_profile_dialog(app):
    from tkinter import messagebox, simpledialog
    try:
        name, key = _managed_custom_identity(app)
        selected = simpledialog.askstring('Rename custom profile', 'New profile name:',
            initialvalue=name, parent=getattr(app, 'root', None))
        if selected is None:
            return None
        result = rename_custom_profile(app, selected, expected_name=name, expected_key=key)
        if hasattr(app, 'status'):
            app.status.set(f'Custom profile renamed to {result}. Saved settings and calibration were kept.')
        return result
    except (ProfilePortabilityError, OSError) as error:
        if not getattr(app, 'closing', False):
            messagebox.showerror('Could not rename profile', str(error), parent=getattr(app, 'root', None))
        return None


def remove_custom_profile_dialog(app):
    from tkinter import messagebox
    try:
        name, key = _managed_custom_identity(app)
        if not messagebox.askyesno('Remove custom profile',
            f"Remove '{name}' and its saved settings, calibration and profile caches?\n\n"
            'Other profiles, source images and exported .drawprofile files are kept. '
            'Export this profile first if you want a backup.',
            parent=getattr(app, 'root', None), default='no'):
            return None
        result = remove_custom_profile(app, expected_name=name, expected_key=key)
        if hasattr(app, 'status'):
            app.status.set(f'Removed custom profile {result}. Other drawing app is now selected; verify its setup before drawing.')
        return result
    except (ProfilePortabilityError, OSError) as error:
        if not getattr(app, 'closing', False):
            messagebox.showerror('Could not remove profile', str(error), parent=getattr(app, 'root', None))
        return None


def export_profile_dialog(app):
    from tkinter import filedialog, messagebox
    try:
        package = package_from_app(app)
        default = safe_profile_key(package["profile"]["name"]) + ".drawprofile"
        selected = filedialog.asksaveasfilename(
            parent=getattr(app, "root", None), title="Export Image Draw Bot profile",
            defaultextension=".drawprofile", initialfile=default,
            filetypes=(("Image Draw Bot profile", "*.drawprofile"), ("JSON", "*.json")),
        )
        if not selected:
            return None
        path = write_profile_file(Path(selected), package)
        messagebox.showinfo("Profile exported", f"Profile saved to:\n{path}", parent=getattr(app, "root", None))
        return path
    except (ProfilePortabilityError, OSError) as error:
        messagebox.showerror("Could not export profile", str(error), parent=getattr(app, "root", None))
        return None


def import_profile_dialog(app):
    from tkinter import filedialog, messagebox, simpledialog
    try:
        _require_idle_profile(app)
        selected = filedialog.askopenfilename(
            parent=getattr(app, "root", None), title="Import Image Draw Bot profile",
            filetypes=(("Image Draw Bot profile", "*.drawprofile *.json"), ("All files", "*.*")),
        )
        if not selected:
            return None
        _require_idle_profile(app)
        package = read_profile_file(Path(selected))
        name = package["profile"]["name"]
        existing = _matching_profile_identity(name)
        action = "replace"
        copy_name = None
        if existing is not None:
            name = existing[0]
            answer = messagebox.askyesnocancel(
                "Profile already exists",
                f"A profile named '{name}' already exists.\n\nYes = Replace this profile\nNo = Import as copy\nCancel = Do nothing",
                parent=getattr(app, "root", None),
            )
            if answer is None:
                return None
            _require_idle_profile(app)
            _checked_import_identity(package['profile']['name'], *existing)
            if answer is False:
                action = "copy"
                suggestion = unique_copy_name(name)
                copy_name = simpledialog.askstring(
                    "Import profile as copy", "Name for the imported copy:",
                    initialvalue=suggestion, parent=getattr(app, "root", None),
                )
                if not copy_name:
                    return None
        destination = import_package_into_app(app, package, action=action, copy_name=copy_name,
            expected_name=existing[0] if existing is not None else None,
            expected_key=existing[1] if existing is not None else None,
            expected_absent=existing is None)
        if not getattr(app, 'closing', False):
            messagebox.showinfo(
                "Profile imported",
                f"Imported '{destination}'.\n\nFor safety, imported canvas/palette calibration is not trusted as a completed setup. Verify the target and run the normal tests before drawing.",
                parent=getattr(app, "root", None),
            )
        return destination
    except (ProfilePortabilityError, OSError) as error:
        if not getattr(app, 'closing', False):
            messagebox.showerror("Could not import profile", str(error), parent=getattr(app, "root", None))
        return None


def reset_profile_dialog(app):
    from tkinter import messagebox
    try:
        _require_idle_profile(app)
        name, key = _profile_identity(str(app.game.get()))
        if not messagebox.askyesno(
            "Reset profile to defaults",
            f"Reset '{name}' to Image Draw Bot defaults?\n\nThis removes this profile's saved settings and calibration/cache files only. Other profiles are not changed.",
            parent=getattr(app, "root", None), default='no',
        ):
            return None
        result = reset_profile(app, expected_name=name, expected_key=key)
        if not getattr(app, 'closing', False):
            messagebox.showinfo(
                "Profile reset",
                f"'{result}' was restored to defaults. Re-run calibration/setup before drawing.",
                parent=getattr(app, "root", None),
            )
        return result
    except ProfilePortabilityError as error:
        if not getattr(app, 'closing', False):
            messagebox.showerror("Could not reset profile", str(error), parent=getattr(app, "root", None))
        return None
