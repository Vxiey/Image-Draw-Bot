"""Crash-safe deterministic render resume helpers for Image Draw Bot v1.0.79.

Schema 2 keeps the existing completed-color checkpoint and can additionally
identify the next *uncompleted path* inside the active browser color batch.
It never stores or restores input authorization.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, defaultdict
from contextlib import closing

SCHEMA = 3
SUPPORTED_SCHEMAS = (1, 2, 3)
MAX_SEQUENCE_OPERATIONS = 25_000_000


def _clean_rgb(value):
    try:
        return tuple(max(0, min(255, int(v))) for v in value[:3])
    except Exception:
        return (0, 0, 0)


def active_color_order(plan):
    groups = plan.get('groups') or []
    execution_groups = plan.get('execution_groups')
    count = max(len(groups), len(execution_groups or ()))
    requested = (plan.get('options') or {}).get('color_order') or list(range(count))
    result = []
    for raw in requested:
        try:index = int(raw)
        except (TypeError, ValueError, OverflowError):continue
        if not 0 <= index < count or index in result:continue
        has_strokes = bool(index < len(groups) and groups[index])
        has_paths = bool(execution_groups is not None and index < len(execution_groups) and execution_groups[index])
        if has_strokes or has_paths:result.append(index)
    return result


def batch_key(plan, index):
    if type(index) is not int or index < 0:
        raise ValueError('Invalid color batch index.')
    colors = plan.get('colors') or ()
    selectors = plan.get('color_selectors') or ()
    rgb = _clean_rgb(colors[index] if index < len(colors) else (0, 0, 0))
    selector = selectors[index] if index < len(selectors) and isinstance(selectors[index], dict) else {}
    payload = {
        'index': int(index), 'rgb': rgb, 'kind': str(selector.get('kind') or 'palette'),
        'palette_index': selector.get('palette_index'), 'fallback_palette_index': selector.get('fallback_palette_index'),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:20]


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


def plan_fingerprint(plan):
    h = hashlib.sha256()
    image = plan.get('image')
    if image is not None:
        # Keep the exact historical RGBA byte stream without a whole-image
        # RGBA allocation plus a second full-size bytes object.
        h.update(f'image-rgba:{image.width}x{image.height}:'.encode())
        rows = max(1, (1024 * 1024) // max(1, image.width * 4))
        for top in range(0, image.height, rows):
            with closing(image.crop((0, top, image.width, min(image.height, top + rows)))) as strip:
                with closing(strip.convert('RGBA')) as rgba:
                    h.update(rgba.tobytes())
    h.update(repr(tuple(plan.get('fitted') or ())).encode())
    h.update(repr(tuple(_clean_rgb(c) for c in (plan.get('colors') or ()))).encode())
    order = active_color_order(plan);h.update(repr(tuple(order)).encode());h.update(str(int(plan.get('count') or 0)).encode())
    selectors=[]
    for index in order:
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
    h.update(json.dumps({k:options.get(k) for k in context_keys},sort_keys=True,
                        separators=(',',':'),default=str).encode('utf-8'))
    for key in ('groups','execution_groups','execution_sequence','plan_area'):
        h.update(key.encode('ascii'))
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), default=str)
        for chunk in encoder.iterencode(plan.get(key)):
            h.update(chunk.encode('utf-8'))
    return h.hexdigest()


def _base(plan, completed_count, *, prelude_complete=True, fingerprint=None):
    order = active_color_order(plan)
    if (type(completed_count) is not int or not 0 <= completed_count <= len(order)
            or type(prelude_complete) is not bool or (completed_count and not prelude_complete)):
        raise ValueError('Completed color count/prelude is inconsistent with the plan.')
    completed = completed_count
    return {
        'schema':SCHEMA,'plan_fingerprint':fingerprint if fingerprint is not None else plan_fingerprint(plan),'total_colors':len(order),
        'completed_count':completed,'completed_keys':[batch_key(plan,index) for index in order[:completed]],
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
        'active_batch_key':batch_key(plan,color_index),'next_path_index':path_index,
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
    """
    if not isinstance(entry, dict):
        payload=entry
    else:
        payload={k:v for k,v in entry.items() if not str(k).startswith('_resume_')}
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),default=str,ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:20]


def _sequence_catalog(plan):
    sequence = plan.get('execution_sequence') or ()
    if len(sequence) > MAX_SEQUENCE_OPERATIONS:
        raise ValueError('Execution sequence exceeds the supported resume limit.')
    keys=sorted(sequence_entry_key(row) for row in sequence if isinstance(row,dict))
    digest=hashlib.sha256('|'.join(keys).encode('ascii')).hexdigest()
    return keys,digest


def sequence_context_fingerprint(plan):
    """Fingerprint everything except sequence order, which Dynamic Replanner may change."""
    clone=dict(plan)
    clone['execution_sequence']=[]
    return plan_fingerprint(clone)


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


def checkpoint_sequence_progress(plan, completed_counts, *, prelude_complete=True, last_entry=None):
    """Persist completed operations for progressive/Pixel Accurate execution.

    The checkpoint stores a bitset over a sorted multiset of operation hashes.
    This is both compact and order-independent, so a Dynamic Replanner reorder
    cannot invalidate safe already-completed work.
    """
    keys,catalog_fp=_sequence_catalog(plan)
    available=Counter(keys);requested=Counter()
    for key,value in dict(completed_counts or {}).items():
        if not isinstance(key,str) or len(key)!=20:continue
        try:n=max(0,int(value or 0))
        except (TypeError,ValueError,OverflowError):continue
        if key in available:requested[key]=min(n,available[key])
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
    expected=[batch_key(plan,index) for index in order[:clean['completed_count']]]
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
        if index != clean['active_color_index'] or batch_key(plan,index)!=clean['active_batch_key']:
            return {'compatible':False,'completed_count':0,'total_colors':len(order),'reason':'active color batch changed'}
        result.update({'path_level':True,'active_color_number':n,'active_color_index':index,
                       'next_path_index':clean['next_path_index'],'active_path_count':clean['active_path_count'],
                       'active_items_fingerprint':clean['active_items_fingerprint']})
    return result
