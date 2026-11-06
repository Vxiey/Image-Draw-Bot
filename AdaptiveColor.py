"""Adaptive one-check-per-color-batch recovery helpers (v1.0.35).

Pure helpers live here so the recovery policy can be tested without Windows UI
or native mouse input.  Actual input remains exclusively in DrawBot.execute_plan.
"""
from __future__ import annotations
import math

METHOD_LABELS={
    'eyedropper':'Eyedropper reuse',
    'spectrum':'Paint custom color palette',
    'numeric':'Exact RGB fields',
    'palette':'Nearest calibrated palette',
}


def rgb_key(rgb):
    r,g,b=(max(0,min(255,int(v))) for v in rgb[:3])
    return f'{r:02X}{g:02X}{b:02X}'


def method_candidates(selector, actions=None, *, has_sample=False, keyboard_available=True, cached_method=None, allow_exact_palette_recovery=False):
    """Return safe color-selection methods in preferred recovery order."""
    actions=actions or {}
    selector_kind=(selector or {}).get('kind')
    result=[]
    if selector_kind!='custom' and not allow_exact_palette_recovery:
        return ('palette',)
    def add(name,ready=True):
        if ready and name not in result:result.append(name)
    spectrum=all(k in actions for k in ('OpenCustomColor','ConfirmColor','SpectrumTopLeft','SpectrumBottomRight'))
    numeric=all(k in actions for k in ('OpenCustomColor','ConfirmColor','RedField','GreenField','BlueField')) and bool(keyboard_available)
    eye=has_sample and 'Eyedropper' in actions
    if selector_kind!='custom':
        # v1.0.122: Paint palette coordinates can become stale after a Paint UI
        # update even when calibration is close enough to pass the coarse layout
        # guard.  After a rendered-color mismatch, allow verified exact RGB as a
        # safe recovery instead of stopping the whole drawing immediately.
        add('palette',True);add('numeric',numeric);add('spectrum',spectrum);add('eyedropper',eye)
        return tuple(result)
    add('eyedropper',eye)
    ready = {'eyedropper': eye, 'spectrum': spectrum, 'numeric': numeric,
             'palette': not selector.get('require_exact', False)}
    add(cached_method, isinstance(cached_method, str) and ready.get(cached_method, False))
    # v1.0.109: image-derived custom selectors prefer calibrated numeric RGB
    # because it can reproduce the measured source RGB exactly. Older/manual
    # selectors keep the spectrum-first order for backwards compatibility.
    if (selector or {}).get('prefer_numeric'):
        add('numeric',numeric);add('spectrum',spectrum)
    else:
        add('spectrum',spectrum);add('numeric',numeric)
    add('palette',not selector.get('require_exact',False))
    return tuple(result)


def method_label(method):
    return METHOD_LABELS.get(str(method),str(method or 'unknown'))


def probe_item(item, smart_group, max_source_span=4.0):
    """Return a short overwrite-safe probe derived from the first planned path.

    The successful full path is drawn over this probe immediately afterwards.
    On a mismatch, another selector can overwrite the same tiny segment.
    """
    span=max(1.0,float(max_source_span))
    if smart_group:
        points=(tuple(map(int,p[:2])) for p in item)
        a=next(points, None)
        if a is None:return item
        b=next((p for p in points if p!=a),None)
        if b is None:return [a]
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if length<=span:return [a,b]
        t=span/length
        end=(round(a[0]+dx*t),round(a[1]+dy*t))
        if end==a:end=b
        return [a,end]
    stroke=tuple(map(int,item[:4]))
    if len(stroke)<4:return item
    x1,y1,x2,y2=stroke;dx,dy=x2-x1,y2-y1;length=math.hypot(dx,dy)
    if length<=span:return stroke
    t=span/length
    end=(round(x1+dx*t),round(y1+dy*t))
    if end==(x1,y1):end=(x2,y2)
    return (x1,y1,end[0],end[1])


def confidence_text(result):
    try:return f"{float(result.get('confidence',0)):.0f}% match · rendered RGB {tuple(result.get('actual') or ())}"
    except Exception:return 'color verification unavailable'
