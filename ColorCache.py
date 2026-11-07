"""Profile-isolated verified-color cache for Paint custom RGB.

Step 9 binds every persistent verified color to both the drawing profile and a
fingerprint of the palette/tool/exact-color calibration context. Recalibration
therefore invalidates stale verified colors without touching another profile.
"""
from __future__ import annotations

import json
import math
import threading
from RuntimePaths import atomic_write_text, read_json

from ProfileStorage import calibration_context_fingerprint, profile_verified_color_file

SCHEMA = 2
MAX_COLORS = 256
MAX_CACHE_BYTES = 1024 * 1024
_LOCK = threading.RLock()


def cache_path(profile):
    return profile_verified_color_file(profile)


def _context(profile, context_fingerprint=None, workflow=''):
    return str(context_fingerprint or calibration_context_fingerprint(profile, workflow=str(workflow or '')))


def _rgb(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError('A color must contain exactly three RGB channels.')
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in value):
        raise ValueError('RGB channels must be integers from 0 to 255.')
    return list(value)


def _colors(raw, context, workflow):
    clean = {}
    if not isinstance(raw, dict):
        return clean
    for key, entry in raw.items():
        try:
            if not isinstance(entry, dict) or entry.get('verified') is not True:
                continue
            requested, detected = _rgb(entry['requested_rgb']), _rgb(entry['created_rgb'])
            if key != ''.join(f'{v:02X}' for v in requested):
                continue
            if entry.get('context_fingerprint') != context or entry.get('workflow', '') != workflow:
                continue
            de, confidence = float(entry['delta_e2000']), float(entry['confidence'])
            if not math.isfinite(de) or de < 0 or not math.isfinite(confidence) or not 0 <= confidence <= 100:
                continue
            clean[key] = dict(requested_rgb=requested, created_rgb=detected, delta_e2000=de,
                              confidence=confidence, method=str(entry.get('method', ''))[:200],
                              verified=True, context_fingerprint=context, workflow=workflow)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return dict(list(clean.items())[-MAX_COLORS:])


def _read(profile):
    try:
        data = read_json(cache_path(profile), max_bytes=MAX_CACHE_BYTES)
        if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != SCHEMA:
            return None
        if data.get('profile') != str(profile):
            return None
        return data
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def load_cache(profile, *, context_fingerprint=None, workflow=''):
    data = _read(profile)
    if data is None:
        return {}
    context, workflow = _context(profile, context_fingerprint, workflow), str(workflow or '')
    if data.get('context_fingerprint') != context or data.get('workflow', '') != workflow:
        return {}
    return _colors(data.get('colors'), context, workflow)


def save_cache(profile, colors, *, context_fingerprint=None, workflow=''):
    context, workflow = _context(profile, context_fingerprint, workflow), str(workflow or '')
    payload = dict(version=SCHEMA, profile=str(profile), context_fingerprint=context,
                   workflow=workflow, colors=_colors(colors, context, workflow))
    with _LOCK:
        atomic_write_text(cache_path(profile), json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))


def put_verified(profile, requested_rgb, detected_rgb, *, delta_e2000, method, confidence=100.0,
                 context_fingerprint=None, workflow=''):
    requested, detected = _rgb(requested_rgb), _rgb(detected_rgb)
    de, confidence = float(delta_e2000), float(confidence)
    if not math.isfinite(de) or de < 0 or not math.isfinite(confidence) or not 0 <= confidence <= 100:
        raise ValueError('Color verification metrics must be finite and within range.')
    context = _context(profile, context_fingerprint, workflow)
    key = ''.join(f'{v:02X}' for v in requested)
    with _LOCK:
        colors = load_cache(profile, context_fingerprint=context, workflow=workflow)
        colors.pop(key, None)
        colors[key] = dict(requested_rgb=requested, created_rgb=detected, delta_e2000=de,
                           method=str(method)[:200], confidence=confidence, verified=True,
                           context_fingerprint=context, workflow=str(workflow or ''))
        save_cache(profile, colors, context_fingerprint=context, workflow=workflow)
        return dict(colors[key])
