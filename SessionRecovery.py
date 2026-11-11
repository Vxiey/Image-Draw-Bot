"""Crash-safe local session checkpointing for Image Draw Bot.

Only local app state is cached. The cached source image is never included in
reports/diagnostics automatically. Recovery never restores an armed/validated
drawing state: target lock, small-test pass, preflight, dry-run and input arming
must all be redone after restart.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
import warnings
from contextlib import contextmanager
from pathlib import Path

from RuntimePaths import atomic_write_text, data_dir, file_transaction, read_json

SCHEMA = 3
SUPPORTED_SCHEMAS = (1, 2, 3)
RECOVERY_DIR = data_dir() / "recovery"
STATE_FILE = RECOVERY_DIR / "session-recovery.json"
IMAGE_FILE = RECOVERY_DIR / "last-image.png"
RENDER_FILE = RECOVERY_DIR / "render-resume.json"
MAX_STATE_BYTES = 128 * 1024
MAX_RENDER_BYTES = 8 * 1024 * 1024
MAX_CACHED_IMAGE_PIXELS = 40_000_000
MAX_CACHED_IMAGE_BYTES = 256 * 1024 * 1024
_SNAPSHOT_LOCK = threading.RLock()
_CURRENT_IMAGE = object()

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
    "max_seconds", "paint_simple", "paint_tool", "resource_scheduler",
    "detail_zoom", "visual_verification", "color_fidelity", "profile_engine",
    "edge_behavior", "sketch_detail", "read_gartic_timer", "render_preset",
    "adaptive_deadline_renderer", "deadline_safety_reserve", "use_region_fill_engine",
    "fill_aggressiveness", "quick_sketch_style", "quick_sketch_fill_preference",
    "hybrid_mode", "gartic_opacity", "preview_detail_level",
}
RECOVERABLE_OPTION_KEYS = frozenset(_OPTION_KEYS)


def _safe_primitive(value):
    if isinstance(value, bool):
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:200]
    return None


def _clean_area(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in value):
        return None
    if any(type(v) is not int or abs(v) > 200000 for p in value for v in p):
        return None
    if value[0][0] == value[1][0] or value[0][1] == value[1][1]:
        return None
    return [list(p) for p in value]


def _clean_target_lock(value):
    """Store a non-authoritative target-lock hint; never a restored pass state."""
    if not isinstance(value, dict):
        return None
    out = {}
    for key, limit in (('profile', 160), ('paint_tool', 80)):
        if isinstance(value.get(key), str):
            out[key] = value[key][:limit]
    for key, limit in (('version', 100), ('target_dpi', 9600)):
        raw = value.get(key)
        if type(raw) is int and 0 < raw <= limit:
            out[key] = raw
    for key, length in (('drawing_area_rel', 4), ('image_size', 2)):
        raw = value.get(key)
        if isinstance(raw, (list, tuple)) and len(raw) == length and all(
            type(v) is int and abs(v) <= 200000 and (key != 'image_size' or v > 0) for v in raw
        ):
            out[key] = list(raw)
    if type(value.get('palette_required')) is bool:
        out['palette_required'] = value['palette_required']
    return out or None


def _read_json(path, limit):
    """Bound both bytes read and decoded container depth/items."""
    return read_json(path, max_bytes=limit, max_depth=16)


def _read_state():
    try:
        raw = _read_json(STATE_FILE, MAX_STATE_BYTES)
    except (OSError, ValueError, TypeError, RecursionError):
        return None
    if not isinstance(raw, dict) or type(raw.get('schema')) is not int or raw['schema'] not in SUPPORTED_SCHEMAS:
        return None
    if type(raw.get('has_image', False)) is not bool:
        return None
    return raw


def _valid_digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def clean_subject_selection(value, image_sha256):
    """Keep a bounded image-specific selection only for its saved raster."""
    if not _valid_digest(image_sha256) or not isinstance(value, dict):
        return None
    if value.get('image_sha256') != image_sha256:
        return None
    from SubjectFocus import MODES
    mode = value.get('mode')
    if mode not in MODES:
        return None
    region = value.get('region')
    if region is not None:
        if (not isinstance(region, (list, tuple)) or len(region) != 4
                or any(type(v) not in (int, float) for v in region)):
            return None
        try:
            region = [float(v) for v in region]
        except (ValueError, OverflowError):
            return None
        x0, y0, x1, y1 = region
        if not all(math.isfinite(v) for v in region) or not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            return None
    return {'image_sha256': image_sha256, 'mode': mode, 'region': region}


def _image_path(digest):
    return IMAGE_FILE.with_name(f'{IMAGE_FILE.stem}-{digest}.png')


def _image_reference(raw):
    if not isinstance(raw, dict) or raw.get('has_image') is not True:
        return None, None
    digest = raw.get('image_sha256')
    if _valid_digest(digest):
        return _image_path(digest), digest
    if raw.get('schema') in (1, 2) and digest is None:
        return IMAGE_FILE, None
    return None, None


@contextmanager
def _snapshot_guard():
    """Serialize publishers/cleanup across threads and local app processes."""
    with _SNAPSHOT_LOCK:
        # Keep the historical sidecar name while sharing bounded contention,
        # reentrancy and error-preserving unlock behavior with local state.
        with file_transaction(RECOVERY_DIR / '.snapshot', timeout=2.0):
            yield


def _stream_digest(stream, *, cancelled=lambda: False):
    digest = hashlib.sha256()
    total = 0
    for block in iter(lambda: stream.read(65536), b''):
        if cancelled():raise InterruptedError('Recovery loading cancelled.')
        total += len(block)
        if total > MAX_CACHED_IMAGE_BYTES:
            raise ValueError('Cached image is too large.')
        digest.update(block)
    return digest.hexdigest()


@contextmanager
def _closing_preserving(resource):
    """Close an owned recovery resource without replacing its primary failure."""
    try:
        yield resource
    except BaseException as failure:
        try:
            resource.close()
        except BaseException as cleanup_error:
            failure.add_note(f'Recovery resource cleanup also failed: {type(cleanup_error).__name__}.')
        raise
    else:
        resource.close()


def _file_digest(path):
    with _closing_preserving(Path(path).open('rb')) as stream:
        return _stream_digest(stream)


def _store_image(image=None, *, legacy_path=None):
    temporary = None
    primary_failure = None
    try:
        with _closing_preserving(tempfile.NamedTemporaryFile(
                'wb', prefix='.recovery-image-', suffix='.png.tmp',
                dir=IMAGE_FILE.parent, delete=False)) as stream:
            temporary = Path(stream.name)
            if image is not None:
                if image.width < 1 or image.height < 1 or image.width * image.height > MAX_CACHED_IMAGE_PIXELS:
                    raise ValueError('Recovery image exceeds the supported pixel limit.')
                if image.mode=='RGBA':
                    image.save(stream,format='PNG')
                else:
                    with _closing_preserving(image.convert('RGBA')) as rgba:
                        rgba.save(stream, format='PNG')
            else:
                with _closing_preserving(Path(legacy_path).open('rb')) as source:
                    copied = 0
                    for block in iter(lambda: source.read(65536), b''):
                        copied += len(block)
                        if copied > MAX_CACHED_IMAGE_BYTES:
                            raise ValueError('Cached image is too large.')
                        stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        digest = _file_digest(temporary)
        temporary.replace(_image_path(digest))
        return digest
    except BaseException as failure:
        primary_failure = failure
        raise
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                if primary_failure is None:
                    raise
                primary_failure.add_note(f'Recovery staging cleanup also failed: {type(cleanup_error).__name__}.')


def _clean_old_images(keep, *, strict=False):
    """Prune under the publish lock; explicit clearing reports deletion errors."""
    keep = set(keep)
    if not strict:
        _current_path, current_digest = _image_reference(_read_state())
        keep.add(current_digest)
    failures = []
    try:
        # scandir does not materialize unrelated directory entries before the
        # first deletion; the snapshot guard excludes cooperative writers.
        with os.scandir(IMAGE_FILE.parent) as entries:
            for entry in entries:
                name=entry.name
                digest = name[len(IMAGE_FILE.stem)+1:-4] if name.startswith(IMAGE_FILE.stem+'-') and name.endswith('.png') else None
                staging = name.startswith('.recovery-image-') and name.endswith('.png.tmp')
                if staging or (_valid_digest(digest) and digest not in keep):
                    path=Path(entry.path)
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as error:
                        failures.append((path,error))
    except FileNotFoundError:
        return
    except OSError as error:
        if strict:
            raise OSError('Could not enumerate cached recovery files.') from error
        return
    if strict and failures:
        names = ', '.join(path.name for path, _error in failures)
        raise OSError(f'Could not remove cached recovery files: {names}') from failures[0][1]


def save_snapshot(*, profile: str, options: dict, saved_area=None, image=None, clear_render_resume=False, target_lock=None, subject_selection=None, prepared_image=None) -> Path:
    """Write a bounded local checkpoint. ``image=None`` preserves any old cache."""
    with _snapshot_guard():
        if image is not None and prepared_image is not None:
            raise ValueError('Supply either an image or its prepared PNG, not both.')
        return _save_snapshot(profile=profile, options=options, saved_area=saved_area, image=image,
                              clear_render_resume=clear_render_resume, target_lock=target_lock,
                              subject_selection=subject_selection, prepared_image=prepared_image)


def _save_snapshot(*, profile, options, saved_area, image, clear_render_resume, target_lock, subject_selection=None, prepared_image=None):
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = {}
    for key in _OPTION_KEYS:
        if key in options:
            value = _safe_primitive(options[key])
            if value is not None:
                cleaned[key] = value
    area = _clean_area(saved_area)
    previous = _read_state()
    old_path, old_digest = _image_reference(previous)
    digest = old_digest if old_path is not None and old_path.is_file() else None
    if prepared_image is not None:
        from RecoveryImagePreparation import PreparedImage
        if not isinstance(prepared_image, PreparedImage) or not _valid_digest(prepared_image.digest):
            raise ValueError('Invalid prepared recovery image.')
        digest = prepared_image.digest
        prepared_image.path.replace(_image_path(digest))
    elif image is not None:
        digest = _store_image(image)
    elif old_path is not None and old_path.is_file() and old_digest is None:
        digest = _store_image(legacy_path=old_path)
    elif previous is None and IMAGE_FILE.is_file():
        digest = _store_image(legacy_path=IMAGE_FILE)
    state = {
        "schema": SCHEMA,
        "created_at": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        "profile": str(profile or '')[:160],
        "options": cleaned,
        "saved_area": area,
        "has_image": digest is not None,
        "image_sha256": digest,
        "target_lock_hint": _clean_target_lock(target_lock),
        "subject_selection": clean_subject_selection(
            dict(subject_selection, image_sha256=digest) if isinstance(subject_selection, dict) else None,
            digest,
        ),
        "safety": {
            "drawing_armed": False,
            "target_lock_restored": False,
            "preflight_restored": False,
            "dry_run_restored": False,
            "small_test_restored": False,
        },
    }
    try:
        atomic_write_text(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False))
    except Exception:
        _clean_old_images({old_digest})
        raise
    if clear_render_resume:
        clear_render_progress()
    _clean_old_images({digest, old_digest})
    return STATE_FILE


def _load_render_resume(value=None):
    try:
        from RenderResume import validate_progress
        raw = _read_json(RENDER_FILE, MAX_RENDER_BYTES) if value is None else value
        return validate_progress(raw)
    except Exception:
        return None

def save_render_progress(progress: dict) -> Path:
    """Atomically persist render progress in its own checkpoint file.

    This is deliberately separate from session-recovery.json. If this file is
    corrupt or incompatible, the session checkpoint can still restore the image
    and settings while rendering restarts safely from color 1.
    """
    with _snapshot_guard():
        from RenderResume import validate_progress
        clean = validate_progress(progress)
        if clean is None:
            raise ValueError('Invalid render resume checkpoint.')
        RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_text(RENDER_FILE, json.dumps(clean, ensure_ascii=False, indent=2))
        return RENDER_FILE

def clear_render_progress() -> None:
    with _snapshot_guard():
        RENDER_FILE.unlink(missing_ok=True)

def load_render_progress() -> dict | None:
    return _load_render_resume()

def load_snapshot() -> dict | None:
    raw = _read_state()
    if raw is None:
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
    valid_area = _clean_area(raw.get('saved_area'))
    image_path, digest = _image_reference(raw)
    return {
        "schema": SCHEMA,
        "created_at": str(raw.get('created_at') or '')[:80],
        "profile": profile[:160],
        "options": cleaned,
        "saved_area": valid_area,
        "has_image": image_path is not None and image_path.is_file(),
        "image_sha256": digest,
        "target_lock_hint": _clean_target_lock(raw.get('target_lock_hint')),
        "subject_selection": clean_subject_selection(raw.get('subject_selection'), digest),
        "render_resume": load_render_progress(),
    }


def load_cached_image(expected_sha256=_CURRENT_IMAGE, *, cancelled=lambda: False):
    """Load only the image associated with the checkpoint (legacy files supported)."""
    from PIL import Image
    if cancelled():raise InterruptedError('Recovery loading cancelled.')
    try:
        if expected_sha256 is _CURRENT_IMAGE:
            state = _read_state()
            path, digest = _image_reference(state) if state is not None else (IMAGE_FILE, None)
        elif expected_sha256 is None:
            # Explicit None identifies an already-read legacy snapshot. Do not
            # substitute the latest schema-3 image after a concurrent save.
            path, digest = IMAGE_FILE, None
        else:
            if not _valid_digest(expected_sha256):
                return None
            path, digest = _image_path(expected_sha256), expected_sha256
        if path is None or not path.is_file() or path.stat().st_size > MAX_CACHED_IMAGE_BYTES:
            return None
        # Hash and decode the same open file so a concurrent replacement cannot
        # change the pixels after identity verification.
        with path.open('rb') as stream, warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            if digest is not None:
                actual = _stream_digest(stream,cancelled=cancelled)
                if actual != digest:
                    return None
                stream.seek(0)
            with Image.open(stream) as image:
                if image.width < 1 or image.height < 1 or image.width * image.height > MAX_CACHED_IMAGE_PIXELS:
                    return None
                if cancelled():raise InterruptedError('Recovery loading cancelled.')
                result=image.convert('RGBA')
                if cancelled():
                    result.close()
                    raise InterruptedError('Recovery loading cancelled.')
                return result
    except InterruptedError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def clear_snapshot() -> None:
    with _snapshot_guard():
        failures = []
        for path in (STATE_FILE, RENDER_FILE, IMAGE_FILE, IMAGE_FILE.with_suffix('.png.tmp')):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                failures.append(f'{path.name}: {error}')
        try:
            _clean_old_images(set(), strict=True)
        except OSError as error:
            failures.append(str(error))
        # A clean/explicit shutdown of the controller waits for its cancelled
        # image encoder. This also removes private PNG staging left by a crash.
        # Never recursively remove unexpected contents or follow a job symlink.
        try:
            with os.scandir(RECOVERY_DIR) as entries:
                for entry in entries:
                    if not entry.name.startswith('.recovery-pending-') or not entry.is_dir(follow_symlinks=False):
                        continue
                    path = Path(entry.path)
                    try:
                        (path / 'image.png').unlink(missing_ok=True)
                        path.rmdir()
                    except OSError as error:
                        failures.append(f'{path.name}: {error}')
        except FileNotFoundError:
            pass
        except OSError as error:
            failures.append(f'Recovery staging: {error}')
        if failures:
            raise OSError('Recovery data could not be completely removed: ' + '; '.join(failures))


def diagnostics_summary() -> dict:
    from LocalSanitization import sanitize_text
    state = load_snapshot()
    if not state:
        return {"available": False}
    return {
        "available": True,
        "created_at": sanitize_text(state.get('created_at', '')),
        "profile": sanitize_text(state.get('profile', '')),
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
