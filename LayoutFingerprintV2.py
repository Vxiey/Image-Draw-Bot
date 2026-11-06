"""Local browser layout cache for Image Draw Bot v1.0.76.

The cache stores only deterministic layout/calibration metadata: profile key,
client size, DPI, a geometry-derived browser zoom/layout signature, canvas
coordinates and palette swatches. It never stores screenshots, source images,
URLs, telemetry or mouse input.

A cache hit is deliberately read-only. The current browser is sampled at a few
saved palette control points. Only after those samples match is the cached
canvas/palette restored. The normal Browser Visual Preflight still runs before
real drawing, so this is a setup speed-up rather than a safety bypass.
"""
from __future__ import annotations
from CalibrationValidation import calibration_screenshot

from dataclasses import dataclass
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Iterable, Sequence

from CalibrationAnchors import make_anchor
from Colors import save_calibration
from RuntimePaths import atomic_write_text, data_dir, read_json, file_transaction
from ProfileStorage import profile_layout_cache_file
from CalibrationValidation import (screen_rect, screen_point, contained_rect, point_in_rect,
                                   rgb_value, bounded_number, nonnegative_integer)

CACHE_FILE = data_dir() / 'layout-fingerprints-v2.json'
CACHE_VERSION = 3
MAX_PER_PROFILE = 8
MAX_TOTAL = 32
MAX_CACHE_BYTES = 2 * 1024 * 1024


def _rect(value: Sequence[int], label: str = 'rectangle') -> tuple[int, int, int, int]:
    return screen_rect(value,label)


def _rgb(value) -> tuple[int, int, int]:
    return rgb_value(value)


def _distance(a, b) -> float:
    return math.sqrt(sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)))


def _palette_spacing(points: Sequence[Sequence[int]]) -> float:
    pts = [(int(p[0]), int(p[1])) for p in points]
    if len(pts) < 2:
        return 0.0
    distances = []
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0]-a[0], b[1]-a[1])
        if 2 <= d <= 250:
            distances.append(d)
    if not distances:
        return 0.0
    distances.sort()
    return float(distances[len(distances)//2])


def zoom_signature(client_rect: Sequence[int], canvas_box: Sequence[int], palette_positions: Sequence[Sequence[int]]) -> tuple[str, float]:
    """Return (stable signature, scale hint) inferred from browser geometry.

    Chrome does not expose its page-zoom percentage through the Win32 target
    metadata used by Image Draw Bot. We therefore persist a deterministic geometry
    signature that changes when page zoom/reflow changes, plus a normalized
    scale hint based on canvas width and palette spacing.
    """
    cl, ct, cr, cb = _rect(client_rect, 'client rectangle')
    xl, yt, xr, yb = _rect(canvas_box, 'canvas rectangle')
    cw, ch = cr-cl, cb-ct
    rel_canvas = (xl-cl, yt-ct, xr-cl, yb-ct)
    rel_palette = [(int(x)-cl, int(y)-ct) for x, y in palette_positions]
    spacing = _palette_spacing(rel_palette)
    canvas_ratio = (xr-xl) / max(1.0, float(cw))
    spacing_ratio = spacing / max(1.0, float(cw))
    payload = {
        'client': [cw, ch],
        'canvas': [round(v / max(1.0, float(cw if i % 2 == 0 else ch)), 5) for i, v in enumerate(rel_canvas)],
        'palette_spacing_ratio': round(spacing_ratio, 6),
        'palette_count': len(rel_palette),
        'palette_positions': rel_palette,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()[:16]
    scale_hint = round((canvas_ratio * 0.75) + (spacing_ratio * 25.0), 4)
    return digest, scale_hint


def _empty_db() -> dict:
    return {'version': CACHE_VERSION, 'entries': []}


def _clean_entry(entry):
    if not isinstance(entry,dict):raise ValueError('Invalid layout fingerprint.')
    profile=entry.get('profile_key')
    if not isinstance(profile,str) or not profile or len(profile)>100:raise ValueError('Invalid fingerprint profile.')
    size=entry.get('client_size')
    if not isinstance(size,(list,tuple)) or len(size)!=2:raise ValueError('Invalid fingerprint size.')
    client=screen_rect((0,0,*size))
    canvas=contained_rect(entry.get('canvas_rel'),client,'cached canvas')
    dpi=entry.get('dpi')
    if dpi is not None:
        dpi=nonnegative_integer(dpi,'Cached DPI',maximum=10000)
        if not dpi:raise ValueError('Invalid cached DPI.')
    signature=entry.get('zoom_signature')
    if not isinstance(signature,str) or len(signature)!=16 or any(c not in '0123456789abcdef' for c in signature):raise ValueError('Invalid fingerprint signature.')
    palette=entry.get('palette')
    if not isinstance(palette,list) or not 3<=len(palette)<=96:raise ValueError('Invalid cached palette size.')
    clean_palette=[];seen=set()
    for item in palette:
        if not isinstance(item,dict):raise ValueError('Invalid cached swatch.')
        point=screen_point(item.get('rel'),'cached palette position')
        if point in seen or not point_in_rect(point,client) or point_in_rect(point,canvas):raise ValueError('Cached palette positions are duplicated, outside the client or inside the canvas.')
        rgb=_rgb(item.get('rgb'));name=item.get('name')
        if not isinstance(name,str) or not name or len(name)>80:raise ValueError('Invalid cached swatch name.')
        seen.add(point);clean_palette.append({'name':name,'rel':list(point),'rgb':list(rgb)})
    # Emit only schema fields. Retaining arbitrary extras could let this writer
    # publish a file within its byte cap that exceeds the reader's item budget.
    clean={'profile_key':profile,'client_size':list(size),'canvas_rel':list(canvas),
           'palette':clean_palette,'dpi':dpi,'zoom_signature':signature}
    for name in ('saved_at','last_used','browser_zoom_hint'):
        clean[name]=bounded_number(entry.get(name,0),name,minimum=0,maximum=1e20)
    if not isinstance(entry.get('method',''),str) or len(entry.get('method',''))>120:raise ValueError('Invalid fingerprint method.')
    clean['method']=entry.get('method','')
    return clean


def load_cache(path: Path = CACHE_FILE) -> dict:
    try:
        raw = read_json(Path(path),max_bytes=MAX_CACHE_BYTES,max_items=80000)
        if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] != CACHE_VERSION or not isinstance(raw.get('entries'), list):
            return _empty_db()
        entries=[]
        for entry in raw['entries'][:MAX_TOTAL]:
            try:entries.append(_clean_entry(entry))
            except (ValueError,TypeError,OverflowError):continue
        return {'version': CACHE_VERSION, 'entries': entries}
    except (OSError, ValueError, TypeError):
        return _empty_db()


def save_cache(data: dict, path: Path = CACHE_FILE) -> None:
    entries = [_clean_entry(entry) for entry in list(data.get('entries') or [])[:MAX_TOTAL]]
    text=json.dumps({'version': CACHE_VERSION, 'entries': entries}, ensure_ascii=False, indent=2,allow_nan=False)
    if len(text.encode('utf-8'))>MAX_CACHE_BYTES:raise ValueError('Layout fingerprint cache exceeds its byte budget.')
    atomic_write_text(Path(path), text)


def _relative_box(box, client):
    cl, ct, _cr, _cb = _rect(client, 'client rectangle')
    l, t, r, b = contained_rect(box,client,'canvas rectangle')
    return [l-cl, t-ct, r-cl, b-ct]


def _absolute_box(rel, client):
    cl, ct, cr, cb = _rect(client, 'client rectangle')
    if not isinstance(rel, (tuple, list)) or len(rel) != 4:
        raise ValueError('Cached canvas rectangle is invalid.')
    l, t, r, b = [int(v) for v in rel]
    box = (cl+l, ct+t, cl+r, ct+b)
    if not (cl <= box[0] < box[2] <= cr and ct <= box[1] < box[3] <= cb):
        raise ValueError('Cached canvas is outside the current browser client.')
    return box


def record_layout(profile_key: str, target_metadata: dict, canvas_box: Sequence[int],
                  palette_entries: Iterable[dict], *, method: str = 'browser auto calibration',
                  path: Path | None = None) -> dict:
    client = _rect(target_metadata.get('client_rect'), 'client rectangle')
    dpi = target_metadata.get('dpi')
    if dpi is not None:
        dpi=nonnegative_integer(dpi,'Target DPI',maximum=10000)
        if not dpi:raise ValueError('Target DPI must be positive.')
    cl, ct, cr, cb = client
    palette = []
    abs_positions = []
    for index, entry in enumerate(palette_entries):
        if index>=96:raise ValueError('A layout fingerprint supports at most 96 colors.')
        if not isinstance(entry, dict):
            raise ValueError('Invalid palette entry for fingerprinting.')
        pos = entry.get('position')
        if not isinstance(pos, (tuple, list)) or len(pos) != 2:
            raise ValueError('Invalid palette position for fingerprinting.')
        x, y = screen_point(pos)
        rgb = _rgb(entry.get('rgb'))
        if not (cl <= x < cr and ct <= y < cb):
            raise ValueError('Palette position is outside the fingerprint client.')
        abs_positions.append((x, y))
        palette.append({
            'name': str(entry.get('name') or f'Color {index+1}')[:80],
            'rel': [x-cl, y-ct],
            'rgb': list(rgb),
        })
    if len(palette) < 3:
        raise ValueError('At least three palette swatches are required for a layout fingerprint.')
    canvas = contained_rect(canvas_box,client,'canvas rectangle')
    signature, zoom_hint = zoom_signature(client, canvas, abs_positions)
    now = time.time()
    entry = {
        'profile_key': str(profile_key or '').lower(),
        'client_size': [cr-cl, cb-ct],
        'dpi': dpi,
        'zoom_signature': signature,
        'browser_zoom_hint': zoom_hint,
        'canvas_rel': _relative_box(canvas, client),
        'palette': palette,
        'method': str(method)[:120],
        'saved_at': now,
        'last_used': now,
    }
    entry=_clean_entry(entry)
    path = Path(path) if path is not None else profile_layout_cache_file(profile_key)
    with file_transaction(path):
        _record_entry(entry,path)
    return dict(entry)


def _record_entry(entry,path):
    db=load_cache(path)
    current = []
    for old in db['entries']:
        same = (
            old.get('profile_key') == entry['profile_key'] and
            old.get('client_size') == entry['client_size'] and
            old.get('dpi') == entry['dpi'] and
            old.get('zoom_signature') == entry['zoom_signature']
        )
        if not same:
            current.append(old)
    current.insert(0, entry)
    # Keep a bounded number per profile and globally.
    counts = {}
    kept = []
    for item in current:
        key = str(item.get('profile_key') or '')
        if counts.get(key, 0) >= MAX_PER_PROFILE:
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(item)
        if len(kept) >= MAX_TOTAL:
            break
    save_cache({'version': CACHE_VERSION, 'entries': kept}, path)


def record_from_calibration_file(profile_key: str, target_metadata: dict, canvas_box: Sequence[int],
                                 palette_path: Path, *, method: str = 'browser auto calibration',
                                 path: Path | None = None) -> dict:
    from Colors import validate_calibration
    from CalibrationAnchors import resolve_point
    raw=read_json(Path(palette_path),max_bytes=256*1024,max_items=10000)
    colors=validate_calibration(raw,profile_key=profile_key)
    if raw.get('profile')!=profile_key or raw.get('state')!='verified':
        raise ValueError('Only a verified palette from this profile can seed a layout fingerprint.')
    if raw.get('anchor') is not None:
        colors=[dict(row,position=list(resolve_point(row['position'],raw['anchor'],target_metadata['client_rect']))) for row in colors]
    return record_layout(profile_key, target_metadata, canvas_box, colors, method=method, path=path)


def _sample_indices(count: int, limit: int = 6) -> tuple[int, ...]:
    count=nonnegative_integer(count,'Cached palette count',maximum=96)
    limit=nonnegative_integer(limit,'Cached palette sample limit',maximum=96)
    if limit<1:raise ValueError('Cached palette sample limit must be positive.')
    if count <= 0:
        return ()
    if count <= limit:
        return tuple(range(count))
    if limit==1:return (0,)
    values = [round(i*(count-1)/(limit-1)) for i in range(limit)]
    out = []
    for value in values:
        value = int(value)
        if value not in out:
            out.append(value)
    return tuple(out)


def _best_error(image, x: int, y: int, expected, radius: int = 2) -> float:
    w, h = image.size
    best = float('inf')
    for yy in range(max(0, y-radius), min(h, y+radius+1)):
        for xx in range(max(0, x-radius), min(w, x+radius+1)):
            best = min(best, _distance(image.getpixel((xx, yy))[:3], expected))
    return best


@dataclass(frozen=True)
class FingerprintRestoreResult:
    hit: bool
    profile_key: str
    canvas_box: tuple[int, int, int, int] | None
    palette_count: int
    confidence: float
    matched_swatches: int
    tested_swatches: int
    zoom_signature: str | None
    browser_zoom_hint: float | None
    reason: str

    def as_dict(self) -> dict:
        return {
            'hit': bool(self.hit), 'profile_key': self.profile_key,
            'canvas_box': self.canvas_box, 'palette_count': int(self.palette_count),
            'confidence': float(self.confidence), 'matched_swatches': int(self.matched_swatches),
            'tested_swatches': int(self.tested_swatches), 'zoom_signature': self.zoom_signature,
            'browser_zoom_hint': self.browser_zoom_hint, 'reason': self.reason,
        }


def try_restore(profile_key: str, target_metadata: dict, palette_path: Path, *, screenshot=None,
                tolerance: float = 42.0, path: Path | None = None,cancelled=lambda:False) -> FingerprintRestoreResult:
    if cancelled():raise InterruptedError('Layout restoration cancelled.')
    tolerance=bounded_number(tolerance,'Cached palette tolerance',minimum=0,maximum=442)
    profile_key = str(profile_key or '').lower()
    path = Path(path) if path is not None else profile_layout_cache_file(profile_key)
    client = _rect(target_metadata.get('client_rect'), 'client rectangle')
    cl, ct, cr, cb = client
    size = [cr-cl, cb-ct]
    dpi = target_metadata.get('dpi')
    candidates = [entry for entry in load_cache(path)['entries']
                  if entry.get('profile_key') == profile_key and entry.get('client_size') == size
                  and (entry.get('dpi') is None or dpi is None or int(entry.get('dpi')) == int(dpi))]
    if not candidates:
        return FingerprintRestoreResult(False, profile_key, None, 0, 0.0, 0, 0, None, None, 'no matching client-size/DPI fingerprint')
    with calibration_screenshot(screenshot,client) as screenshot:
        best = None
        for candidate in candidates:
            if cancelled():raise InterruptedError('Layout restoration cancelled.')
            palette = candidate.get('palette') or []
            indices = _sample_indices(len(palette), 6)
            if len(indices) < 3:
                continue
            matched = 0
            errors = []
            for index in indices:
                item = palette[index]
                rel = item.get('rel') or []
                if len(rel) != 2:
                    errors.append(float('inf')); continue
                x, y = map(int, rel)
                if not (0 <= x < screenshot.size[0] and 0 <= y < screenshot.size[1]):
                    errors.append(float('inf')); continue
                error = _best_error(screenshot, x, y, _rgb(item.get('rgb')), radius=2)
                errors.append(error)
                if error <= tolerance:
                    matched += 1
            required = len(indices) if len(indices) <= 4 else max(4, math.ceil(len(indices)*.80))
            confidence = matched / max(1, len(indices))
            score = (matched >= required, confidence, -max((e for e in errors if math.isfinite(e)), default=9999.0), float(candidate.get('last_used') or 0.0))
            if best is None or score > best[0]:
                best = (score, candidate, matched, len(indices), confidence)

        if best is None or not best[0][0]:
            return FingerprintRestoreResult(False, profile_key, None, 0, float(best[4] if best else 0.0), int(best[2] if best else 0), int(best[3] if best else 0), None, None, 'saved swatches did not match current browser layout')

        _score, candidate, matched, tested, confidence = best
        try:
            canvas = _absolute_box(candidate.get('canvas_rel'), client)
            palette = candidate.get('palette') or []
            positions = [(cl+int(item['rel'][0]), ct+int(item['rel'][1])) for item in palette]
            rgbs = [_rgb(item.get('rgb')) for item in palette]
            names = [str(item.get('name') or f'Color {i+1}') for i, item in enumerate(palette)]
            if cancelled():raise InterruptedError('Layout restoration cancelled.')
            save_calibration(positions, rgbs, Path(palette_path), names=names, anchor=make_anchor(client), profile_key=profile_key, state='verified', verification={'method':'layout-fingerprint-screen-verification','confidence':float(confidence),'source':'profile-isolated-layout-cache'})
        except InterruptedError:
            raise
        except Exception as error:
            return FingerprintRestoreResult(False, profile_key, None, 0, confidence, matched, tested, None, None, f'cached layout could not be restored: {error}')

        # Touch last-used without changing the geometry signature.
        try:
            with file_transaction(path):
                db = load_cache(path)
                for item in db['entries']:
                    if (item.get('profile_key') == candidate.get('profile_key') and
                        item.get('zoom_signature') == candidate.get('zoom_signature') and
                        item.get('client_size') == candidate.get('client_size') and
                        item.get('dpi') == candidate.get('dpi')):
                        item['last_used'] = time.time()
                        break
                save_cache(db, path)
        except OSError:
            pass  # Optional recency bookkeeping cannot undo a verified restoration.
        if cancelled():raise InterruptedError('Layout restoration cancelled.')
        return FingerprintRestoreResult(
            True, profile_key, canvas, len(candidate.get('palette') or []), float(confidence),
            matched, tested, str(candidate.get('zoom_signature') or ''),
            float(candidate.get('browser_zoom_hint') or 0.0),
            'layout fingerprint matched current palette control points',
        )
