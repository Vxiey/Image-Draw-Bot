"""Crash-safe deterministic render resume helpers for Image Draw Bot v1.0.79.

Schema 2 keeps the existing completed-color checkpoint and can additionally
identify the next *uncompleted path* inside the active browser color batch.
It never stores or restores input authorization.
"""
from __future__ import annotations

import base64
import hashlib
import heapq
import json
from collections import Counter, defaultdict
from contextlib import closing
from itertools import islice
from types import MappingProxyType

SCHEMA = 3
SUPPORTED_SCHEMAS = (1, 2, 3)
MAX_SEQUENCE_OPERATIONS = 25_000_000


def _clean_rgb(value):
    try:
        return tuple(max(0, min(255, int(v))) for v in value[:3])
    except Exception:
        return (0, 0, 0)


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('Render checkpoint preparation cancelled.')


def active_color_order(plan, *, cancelled=None):
    groups = plan.get('groups') or []
    execution_groups = plan.get('execution_groups')
    count = max(len(groups), len(execution_groups or ()))
    requested = (plan.get('options') or {}).get('color_order') or list(range(count))
    result = []
    for number, raw in enumerate(requested):
        if number % 256 == 0:
            _check_cancelled(cancelled)
        try:index = int(raw)
        except (TypeError, ValueError, OverflowError):continue
        if not 0 <= index < count:continue
        has_strokes = bool(index < len(groups) and groups[index])
        has_paths = bool(execution_groups is not None and index < len(execution_groups) and execution_groups[index])
        if has_strokes or has_paths:result.append(index)
    _check_cancelled(cancelled)
    return result


def batch_key(plan, index, *, occurrence=1):
    if type(index) is not int or index < 0:
        raise ValueError('Invalid color batch index.')
    if type(occurrence) is not int or occurrence < 1:
        raise ValueError('Invalid color batch occurrence.')
    colors = plan.get('colors') or ()
    selectors = plan.get('color_selectors') or ()
    rgb = _clean_rgb(colors[index] if index < len(colors) else (0, 0, 0))
    selector = selectors[index] if index < len(selectors) and isinstance(selectors[index], dict) else {}
    payload = {
        'index': int(index), 'rgb': rgb, 'kind': str(selector.get('kind') or 'palette'),
        'palette_index': selector.get('palette_index'), 'fallback_palette_index': selector.get('fallback_palette_index'),
    }
    # Keep historical keys for ordinary single visits. A later visit to the
    # same colour is a different batch even when its geometry is identical.
    if occurrence > 1:
        payload['occurrence'] = occurrence
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:20]


def _batch_keys(plan, order):
    seen = Counter()
    keys = []
    for index in order:
        seen[index] += 1
        keys.append(batch_key(plan, index, occurrence=seen[index]))
    return keys


def items_fingerprint(items) -> str:
    """Fingerprint the actual ordered path list without storing source pixels."""
    h=hashlib.sha256()
    try:
        for item in items or ():
            if isinstance(item,(list,tuple)):
                h.update(repr(tuple(tuple(v) if isinstance(v,(list,tuple)) else v for v in item)).encode('utf-8'))
            else:h.update(repr(item).encode('utf-8'))
            h.update(b'|')
    except Exception:
        h.update(repr(items).encode('utf-8'))
    return h.hexdigest()


def _hash_json(hasher, value, cancelled):
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), default=str)
    if cancelled is None:
        for chunk in encoder.iterencode(value):
            hasher.update(chunk.encode('utf-8'))
    else:
        for number, chunk in enumerate(encoder.iterencode(value)):
            if number % 256 == 0:
                _check_cancelled(cancelled)
            hasher.update(chunk.encode('utf-8'))
        _check_cancelled(cancelled)


def plan_fingerprint(plan, *, cancelled=None):
    _check_cancelled(cancelled)
    h = hashlib.sha256()
    image = plan.get('image')
    if image is not None:
        # Keep the exact historical RGBA byte stream without a whole-image
        # RGBA allocation plus a second full-size bytes object.
        h.update(f'image-rgba:{image.width}x{image.height}:'.encode())
        rows = max(1, (1024 * 1024) // max(1, image.width * 4))
        for top in range(0, image.height, rows):
            _check_cancelled(cancelled)
            with closing(image.crop((0, top, image.width, min(image.height, top + rows)))) as strip:
                with closing(strip.convert('RGBA')) as rgba:
                    h.update(rgba.tobytes())
        _check_cancelled(cancelled)
    h.update(repr(tuple(plan.get('fitted') or ())).encode())
    h.update(repr(tuple(_clean_rgb(c) for c in (plan.get('colors') or ()))).encode())
    order = active_color_order(plan, cancelled=cancelled);h.update(repr(tuple(order)).encode());h.update(str(int(plan.get('count') or 0)).encode())
    selectors=[]
    for number, index in enumerate(order):
        if number % 256 == 0:
            _check_cancelled(cancelled)
        src=(plan.get('color_selectors') or ())
        selector=src[index] if index < len(src) and isinstance(src[index],dict) else {}
        selectors.append((selector.get('kind'),selector.get('palette_index'),selector.get('fallback_palette_index'),_clean_rgb(selector.get('rgb') or (0,0,0))))
    h.update(repr(tuple(selectors)).encode())
    # Same image/count is insufficient: geometry, brush, target and preludes
    # can change while all old fingerprint fields remain identical.
    options=plan.get('options') or {}
    context_keys=(
        'profile_key','profile_name','brush_px','effective_paint_tool','paint_tool',
        'speed','precision','drawing_mode','corners','canvas_polygon','target_dpi',
        'calibration_fingerprint','target_lock_fingerprint','edge_behavior_resolved',
        'fill_regions','background_fill_plan','tool_actions','fill_tool_actions',
        'fill_restore_actions','exact_color_actions','canvas_clear_actions',
    )
    _hash_json(h, {k:options.get(k) for k in context_keys}, cancelled)
    for key in ('groups','execution_groups','execution_sequence','plan_area'):
        h.update(key.encode('ascii'))
        _hash_json(h, plan.get(key), cancelled)
    _check_cancelled(cancelled)
    return h.hexdigest()


def _base(plan, completed_count, *, prelude_complete=True, fingerprint=None, cancelled=None):
    order = active_color_order(plan, cancelled=cancelled)
    if (type(completed_count) is not int or not 0 <= completed_count <= len(order)
            or type(prelude_complete) is not bool or (completed_count and not prelude_complete)):
        raise ValueError('Completed color count/prelude is inconsistent with the plan.')
    completed = completed_count
    return {
        'schema':SCHEMA,'plan_fingerprint':fingerprint if fingerprint is not None else plan_fingerprint(plan),'total_colors':len(order),
        'completed_count':completed,'completed_keys':_batch_keys(plan,order[:completed]),
        'next_color':completed+1 if completed < len(order) else 0,'prelude_complete':bool(prelude_complete),
        'active_color_number':0,'active_color_index':None,'active_batch_key':'','next_path_index':0,
        'active_path_count':0,'active_items_fingerprint':'','path_level':False,
    }


def new_progress(plan):
    return _base(plan,0,prelude_complete=False)


def checkpoint_after_batch(plan, completed_count, *, prelude_complete=True):
    return _base(plan,completed_count,prelude_complete=prelude_complete)


def checkpoint_before_path(plan, color_number, path_index, path_count, *, ordered_items=None, prelude_complete=True):
    order=active_color_order(plan)
    if type(color_number) is not int or not 1 <= color_number <= len(order):raise ValueError('Invalid active color number for path checkpoint.')
    if type(path_count) is not int or type(path_index) is not int or not 0 <= path_index <= path_count:
        raise ValueError("Path checkpoint index must be within the path count.")
    if path_index and not prelude_complete:
        raise ValueError('Completed paths require a completed prelude.')
    if ordered_items is not None and len(ordered_items) != path_count:
        raise ValueError("Path checkpoint count does not match ordered items.")
    color_index=order[color_number-1]
    out=_base(plan,color_number-1,prelude_complete=prelude_complete)
    out.update({
        'next_color':color_number,'active_color_number':color_number,'active_color_index':int(color_index),
        'active_batch_key':_batch_keys(plan,order[:color_number])[-1],'next_path_index':path_index,
        'active_path_count':path_count,'active_items_fingerprint':items_fingerprint(ordered_items),
        'path_level':True,
    })
    return out


def checkpoint_after_path(plan, color_number, completed_path_index, path_count, *, ordered_items=None, prelude_complete=True):
    if type(completed_path_index) is not int or completed_path_index < 0:
        raise ValueError('Completed path index must be a nonnegative integer.')
    return checkpoint_before_path(plan,color_number,completed_path_index+1,path_count,
                                  ordered_items=ordered_items,prelude_complete=prelude_complete)




def sequence_entry_key(entry) -> str:
    """Stable content key for one final execution-sequence operation.

    Runtime replanning may reorder entries, so resume identity deliberately does
    not depend on list position. Identical duplicate operations are interchangeable
    and are tracked by occurrence count in the compact canonical bitset.
    For rows with inherited brush widths, checkpoint creation resolves this raw
    key against the plan. Use materialized rows when one raw key occurs at
    different physical widths and therefore cannot identify completed work.
    """
    if not isinstance(entry, dict):
        payload=entry
    else:
        payload={k:v for k,v in entry.items() if not str(k).startswith('_resume_')}
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),default=str,ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:20]


def execution_sequence_with_brushes(plan, *, cancelled=lambda: False):
    """Resolve physical brush inheritance before skip/reorder decisions.

    A skipped completed path or a deadline-trimmed path must not remove the
    brush context of the following operation. Explicit widths also make the
    resume catalogue independent of order only when that order preserves the
    same actual operations. The caller's entries are never modified.
    """
    for _raw, operation in _execution_sequence_pairs(plan, cancelled=cancelled):
        yield operation


def _execution_sequence_pairs(plan, *, cancelled=lambda: False):
    """Share the same raw-to-physical mapping with checkpoint key translation."""
    sequence = plan.get('execution_sequence') or ()
    brush = max(1, int((plan.get('options') or {}).get('brush_px', 1) or 1))
    for number, entry in enumerate(sequence):
        if number % 256 == 0 and cancelled():
            raise InterruptedError('Execution sequence preparation cancelled.')
        if not isinstance(entry, dict) or not entry.get('path'):
            # An empty row is not a drawing operation or a brush command.
            continue
        try:
            int(entry['color_index'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        brush = max(1, int(entry.get('brush_px', brush) or brush))
        if type(entry.get('brush_px')) is int and entry['brush_px'] == brush:
            yield entry, entry
        else:
            yield entry, dict(entry, brush_px=brush)
    if cancelled():
        raise InterruptedError('Execution sequence preparation cancelled.')


def _sequence_catalog(plan):
    sequence = plan.get('execution_sequence') or ()
    if len(sequence) > MAX_SEQUENCE_OPERATIONS:
        raise ValueError('Execution sequence exceeds the supported resume limit.')
    keys=sorted(sequence_entry_key(row) for row in execution_sequence_with_brushes(plan))
    digest=hashlib.sha256('|'.join(keys).encode('ascii')).hexdigest()
    return keys,digest


def sequence_context_fingerprint(plan, *, cancelled=None):
    """Fingerprint everything except sequence order, which Dynamic Replanner may change."""
    clone=dict(plan)
    clone['execution_sequence']=[]
    return plan_fingerprint(clone) if cancelled is None else plan_fingerprint(clone, cancelled=cancelled)


def _encode_bits(flags) -> str:
    raw = bytearray()
    for index,value in enumerate(flags):
        if index % 8 == 0:
            raw.append(0)
        if value:raw[index//8] |= 1 << (index%8)
    return base64.b64encode(bytes(raw)).decode('ascii')


def _decode_packed_bits(text: str, total: int):
    if type(total) is not int or not 0 <= total <= MAX_SEQUENCE_OPERATIONS or not isinstance(text, str):
        return None
    byte_count = (total + 7) // 8
    if len(text) != 4 * ((byte_count + 2) // 3):
        return None
    try:raw=base64.b64decode(text.encode('ascii'),validate=True)
    except Exception:return None
    if len(raw) != byte_count:return None
    # Unused tail bits must stay zero so corrupted state cannot silently validate.
    if total%8 and raw:
        mask=~((1 << (total%8))-1) & 0xff
        if raw[-1] & mask:return None
    return raw


def _decode_bits(text: str, total: int):
    """Compatibility helper; internal validation/counting stays packed."""
    raw = _decode_packed_bits(text, total)
    if raw is None:return None
    return [bool(raw[i // 8] & (1 << (i % 8))) for i in range(total)]


def _sequence_counts_from_bits(keys, bits):
    raw=_decode_packed_bits(bits,len(keys))
    if raw is None:return None
    out=Counter()
    for index,key in enumerate(keys):
        if raw[index // 8] & (1 << (index % 8)):out[key]+=1
    return dict(out)


def _completed_sequence_counts(plan, available, completed_counts):
    """Accept public raw keys only when they identify one physical operation."""
    supplied = Counter()
    for key, value in dict(completed_counts or {}).items():
        if not isinstance(key, str) or len(key) != 20:
            continue
        try:
            count = max(0, int(value or 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if count:
            supplied[key] = count
    requested = Counter({key: min(count, available[key]) for key, count in supplied.items()
                         if key in available})
    unknown = supplied.keys() - available.keys()
    if not unknown:
        return requested  # Normal execution already supplies materialized keys.

    aliases = {}
    for raw, operation in _execution_sequence_pairs(plan):
        if raw is operation:
            continue
        raw_key = sequence_entry_key(raw)
        if raw_key not in unknown:
            continue
        key = sequence_entry_key(operation)
        if aliases.setdefault(raw_key, key) != key:
            raise ValueError('Completed operation has ambiguous inherited brush widths; use materialized sequence keys.')
    for raw_key, key in aliases.items():
        requested[key] = min(available[key], requested[key] + supplied[raw_key])
    return requested


def checkpoint_sequence_progress(plan, completed_counts, *, prelude_complete=True, last_entry=None):
    """Persist completed operations for progressive/Pixel Accurate execution.

    The checkpoint stores a bitset over a sorted multiset of operation hashes.
    This is both compact and order-independent, so a Dynamic Replanner reorder
    cannot invalidate safe already-completed work.
    Raw public entry keys are translated only when the current plan gives them
    one effective brush identity; stored legacy catalogues are never promoted.
    """
    keys,catalog_fp=_sequence_catalog(plan)
    requested = _completed_sequence_counts(plan, Counter(keys), completed_counts)
    seen = Counter()
    def flags():
        for key in keys:
            seen[key] += 1
            yield seen[key] <= requested.get(key, 0)
    completed=sum(requested.values());total=len(keys)
    if completed and not prelude_complete:
        raise ValueError('Completed sequence operations require a completed prelude.')
    last_color = (last_entry or {}).get('color_index')
    out=_base(plan,0,prelude_complete=prelude_complete,fingerprint=sequence_context_fingerprint(plan))
    out.update({
        'schema':SCHEMA,
        'sequence_level':True,'sequence_total':total,'sequence_completed_count':completed,
        'sequence_catalog_fingerprint':catalog_fp,'sequence_completed_bits':_encode_bits(flags()),
        'sequence_coverage_percent':round((completed/max(1,total))*100.0,3),
        'sequence_remaining_count':max(0,total-completed),
        'sequence_last_phase':str((last_entry or {}).get('phase') or '')[:80],
        'sequence_last_color_index':int(last_color) if last_color is not None else -1,
        'sequence_last_brush_px':max(0,int((last_entry or {}).get('brush_px',0) or 0)),
        'path_level':False,
    })
    return out


def _sorted_catalog_keys(keys, cancelled):
    """Bound each noninterruptible sort, then poll while merging the chunks."""
    iterator = iter(keys)
    chunks = []
    while True:
        _check_cancelled(cancelled)
        chunk = list(islice(iterator, 4096))
        if not chunk:
            break
        chunk.sort()
        chunks.append(chunk)
    for number, key in enumerate(heapq.merge(*chunks)):
        if number % 256 == 0:
            _check_cancelled(cancelled)
        yield key
    _check_cancelled(cancelled)


def _sequence_ranges(plan, cancelled):
    """Freeze the existing sorted-multiset identity without retaining geometry."""
    _check_cancelled(cancelled)
    if len(plan.get('execution_sequence') or ()) > MAX_SEQUENCE_OPERATIONS:
        raise ValueError('Execution sequence exceeds the supported resume limit.')
    available = Counter()
    for operation in execution_sequence_with_brushes(plan, cancelled=cancelled):
        available[sequence_entry_key(operation)] += 1
    digest = hashlib.sha256()
    ranges = {}
    total = 0
    for key in _sorted_catalog_keys(available, cancelled):
        count = available[key]
        ranges[key] = (total, count)
        encoded = key.encode('ascii')
        digest.update((b'|' if total else b'') + encoded)
        # A duplicated operation still occupies one canonical bit per visit.
        # Stream its exact old '|'.join byte sequence in small bounded chunks.
        remaining = count - 1
        while remaining:
            _check_cancelled(cancelled)
            take = min(remaining, 2048)
            digest.update((b'|' + encoded) * take)
            remaining -= take
        total += count
    _check_cancelled(cancelled)
    return MappingProxyType(ranges), total, digest.hexdigest()


class SequenceCheckpointSession:
    """One executor's immutable proof plus an incrementally completed bitset.

    Construct after final effective options are fixed, before native input, and
    discard when that invocation exits. Only canonical keys from its frozen
    operation catalogue may be completed. Seed counts must come from a verified
    resume result. The session keeps no plan, source image, path or callback.

    ``completed_counts`` is a live read-only view. The executor marks completion
    only after its existing drawing/visual-verification boundary approves work.
    Snapshots are ordinary independently owned schema-3 dictionaries; Stop can
    save approved work without reopening the source or rescanning the catalogue.
    """

    def __init__(self, plan, *, completed_counts=None, cancelled=lambda: False):
        ranges, total, catalog = _sequence_ranges(plan, cancelled)
        fingerprint = sequence_context_fingerprint(plan, cancelled=cancelled)
        _check_cancelled(cancelled)
        base = _base(plan, 0, prelude_complete=False, fingerprint=fingerprint, cancelled=cancelled)
        base.pop('completed_keys')
        self._base = MappingProxyType(base)
        self._ranges = ranges
        self._total = total
        self._catalog = catalog
        self._bits = bytearray((total + 7) // 8)
        self._completed = {}
        self._completed_view = MappingProxyType(self._completed)
        self._completed_total = 0
        self._encoded_bits = None
        for number, (key, count) in enumerate(dict(completed_counts or {}).items()):
            if number % 256 == 0:
                _check_cancelled(cancelled)
            if not isinstance(key, str) or type(count) is not int or count < 0:
                raise ValueError('Invalid verified sequence completion count.')
            if not count:
                continue
            span = self._ranges.get(key)
            if span is None or count > span[1]:
                raise ValueError('Verified sequence completion exceeds this catalogue.')
            start, end = span[0], span[0] + count
            while start < end and start % 8:
                self._bits[start // 8] |= 1 << (start % 8)
                start += 1
            whole_end = end // 8
            for first in range(start // 8, whole_end, 65536):
                _check_cancelled(cancelled)
                last = min(whole_end, first + 65536)
                self._bits[first:last] = b'\xff' * (last - first)
            start = max(start, whole_end * 8)
            while start < end:
                self._bits[start // 8] |= 1 << (start % 8)
                start += 1
            self._completed[key] = count
            self._completed_total += count
        _check_cancelled(cancelled)

    @property
    def completed_counts(self):
        return self._completed_view

    def complete(self, key):
        """Approve one occurrence; unknown/exhausted operations cannot advance."""
        span = self._ranges.get(key) if isinstance(key, str) else None
        count = self._completed.get(key, 0) if span is not None else 0
        if span is None or count >= span[1]:
            raise ValueError('Completed operation is absent from or exceeds this sequence catalogue.')
        index = span[0] + count
        self._bits[index // 8] |= 1 << (index % 8)
        self._completed[key] = count + 1
        self._completed_total += 1
        self._encoded_bits = None

    def snapshot(self, *, prelude_complete=True, last_entry=None):
        if type(prelude_complete) is not bool or (self._completed_total and not prelude_complete):
            raise ValueError('Completed sequence operations require a completed prelude.')
        if self._encoded_bits is None:
            self._encoded_bits = base64.b64encode(self._bits).decode('ascii')
        completed, total = self._completed_total, self._total
        last_color = (last_entry or {}).get('color_index')
        out = dict(self._base, completed_keys=[], prelude_complete=prelude_complete)
        out.update({
            'schema': SCHEMA,
            'sequence_level': True, 'sequence_total': total, 'sequence_completed_count': completed,
            'sequence_catalog_fingerprint': self._catalog, 'sequence_completed_bits': self._encoded_bits,
            'sequence_coverage_percent': round((completed / max(1, total)) * 100.0, 3),
            'sequence_remaining_count': max(0, total - completed),
            'sequence_last_phase': str((last_entry or {}).get('phase') or '')[:80],
            'sequence_last_color_index': int(last_color) if last_color is not None else -1,
            'sequence_last_brush_px': max(0, int((last_entry or {}).get('brush_px', 0) or 0)),
            'path_level': False,
        })
        return out


def _hex(value, length):
    return isinstance(value, str) and len(value) == length and all(c in '0123456789abcdef' for c in value)


def validate_progress(value):
    if not isinstance(value, dict):
        return None
    schema = value.get('schema')
    if type(schema) is not int or schema not in SUPPORTED_SCHEMAS:
        return None
    fp, total, completed = value.get('plan_fingerprint'), value.get('total_colors'), value.get('completed_count')
    if not _hex(fp, 64) or type(total) is not int or type(completed) is not int or not 0 <= completed <= total:
        return None
    keys = value.get('completed_keys', [])
    if not isinstance(keys, list) or len(keys) != completed or not all(_hex(k, 20) for k in keys) or len(set(keys)) != len(keys):
        return None
    prelude, path_level = value.get('prelude_complete', False), value.get('path_level', False)
    sequence_level = value.get('sequence_level', False) if schema >= 3 else False
    if type(prelude) is not bool or type(path_level) is not bool or type(sequence_level) is not bool:
        return None
    if path_level and sequence_level:
        return None
    if completed and not prelude:
        return None
    out = dict(schema=schema, plan_fingerprint=fp, total_colors=total, completed_count=completed,
               completed_keys=list(keys), next_color=completed+1 if completed<total else 0,
               prelude_complete=prelude, active_color_number=0, active_color_index=None,
               active_batch_key='', next_path_index=0, active_path_count=0,
               active_items_fingerprint='', path_level=False, sequence_level=False,
               sequence_total=0, sequence_completed_count=0, sequence_catalog_fingerprint='',
               sequence_completed_bits='', sequence_coverage_percent=0.0, sequence_remaining_count=0,
               sequence_last_phase='', sequence_last_color_index=-1, sequence_last_brush_px=0)
    if schema >= 3 and sequence_level:
        st=value.get('sequence_total');sc=value.get('sequence_completed_count');catalog=value.get('sequence_catalog_fingerprint');bits=value.get('sequence_completed_bits')
        if type(st) is not int or type(sc) is not int or not 0 <= sc <= st or not _hex(catalog,64):return None
        if sc and not prelude:return None
        packed=_decode_packed_bits(bits,st)
        if packed is None or sum(byte.bit_count() for byte in packed)!=sc:return None
        try:last_color=int(value.get('sequence_last_color_index',-1));last_brush=max(0,int(value.get('sequence_last_brush_px',0) or 0))
        except (TypeError,ValueError,OverflowError):return None
        out.update(sequence_level=True,sequence_total=st,sequence_completed_count=sc,
                   sequence_catalog_fingerprint=catalog,sequence_completed_bits=str(bits),
                   sequence_coverage_percent=round(sc/max(1,st)*100.0,3),sequence_remaining_count=max(0,st-sc),
                   sequence_last_phase=str(value.get('sequence_last_phase') or '')[:80],
                   sequence_last_color_index=last_color,sequence_last_brush_px=last_brush)
        return out
    if schema >= 2 and path_level:
        n, idx = value.get('active_color_number'), value.get('active_color_index')
        nxt, count = value.get('next_path_index'), value.get('active_path_count')
        if any(type(v) is not int for v in (n, idx, nxt, count)):
            return None
        key, items_fp = value.get('active_batch_key'), value.get('active_items_fingerprint')
        if n != completed+1 or not 1 <= n <= total or idx < 0 or not 0 <= nxt <= count:
            return None
        if nxt and not prelude:
            return None
        if not _hex(key, 20) or not _hex(items_fp, 64):
            return None
        out.update(active_color_number=n, active_color_index=idx, active_batch_key=key,
                   next_path_index=nxt, active_path_count=count, active_items_fingerprint=items_fp,
                   next_color=n, path_level=True)
    return out


def resolve_resume(plan,state):
    clean=validate_progress(state);order=active_color_order(plan)
    if not clean:
        return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'no valid render progress'}
    if plan.get('execution_sequence'):
        if not clean.get('sequence_level'):
            return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'progressive passes require a sequence checkpoint'}
        keys,catalog_fp=_sequence_catalog(plan)
        if clean.get('plan_fingerprint') != sequence_context_fingerprint(plan):
            return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'sequence render context changed'}
        if clean.get('sequence_total') != len(keys) or clean.get('sequence_catalog_fingerprint') != catalog_fp:
            return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'execution sequence operations changed'}
        completed_counts=_sequence_counts_from_bits(keys,clean.get('sequence_completed_bits'))
        if completed_counts is None:
            return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'sequence checkpoint bitset is invalid'}
        completed_sequence=sum(completed_counts.values())
        if completed_sequence <= 0:
            return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'no completed sequence operations'}
        return {
            'compatible':True,'completed_count':0,'total_colors':len(order),'next_color':0,
            'prelude_complete':bool(clean.get('prelude_complete')),'reason':'','path_level':False,
            'sequence_level':True,'sequence_total':len(keys),'sequence_completed_count':completed_sequence,
            'sequence_remaining_count':max(0,len(keys)-completed_sequence),
            'sequence_coverage_percent':round(completed_sequence/max(1,len(keys))*100.0,3),
            'sequence_completed_counts':completed_counts,'sequence_last_phase':clean.get('sequence_last_phase',''),
            'sequence_last_color_index':clean.get('sequence_last_color_index',-1),
            'sequence_last_brush_px':clean.get('sequence_last_brush_px',0),
        }
    if clean.get('sequence_level'):
        return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'sequence checkpoint cannot resume a color-batch plan'}
    if not clean['completed_count'] and not clean.get('path_level'):
        return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'no completed color/path progress'}
    if clean['plan_fingerprint'] != plan_fingerprint(plan):
        return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'final plan fingerprint changed'}
    if clean['total_colors'] != len(order):
        return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'color batch count changed'}
    expected=_batch_keys(plan,order[:clean['completed_count']])
    if expected != clean['completed_keys']:
        return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'completed color sequence changed'}
    result={
        'compatible':True,'completed_count':clean['completed_count'],'total_colors':len(order),
        'next_color':clean['next_color'],'prelude_complete':bool(clean['prelude_complete']),'reason':'',
        'path_level':False,'active_color_number':0,'active_color_index':None,'next_path_index':0,
        'active_path_count':0,'active_items_fingerprint':'',
    }
    if clean.get('path_level'):
        n=clean['active_color_number'];index=order[n-1]
        if index != clean['active_color_index'] or _batch_keys(plan,order[:n])[-1]!=clean['active_batch_key']:
            return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'active color batch changed'}
        result.update({'path_level':True,'active_color_number':n,'active_color_index':index,
                       'next_path_index':clean['next_path_index'],'active_path_count':clean['active_path_count'],
                       'active_items_fingerprint':clean['active_items_fingerprint']})
    return result
