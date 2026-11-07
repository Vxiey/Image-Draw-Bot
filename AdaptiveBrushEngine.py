"""Adaptive brush policy for Image Draw Bot.

The planner keeps source geometry authoritative, then this module assigns a
physically executable brush width to every path. Multi-size drawing is enabled
only when BrowserBrushSize verified the target controls. The selector uses the
verified brush ladder, component geometry and path semantics while protecting
corrections, small details and thin structures. A conservative hysteresis pass
removes one-path brush upshifts that cost more UI time than they can save.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite
from typing import Sequence
from CalibrationValidation import screen_point


def _unique_sizes(values, fallback: int) -> tuple[int, ...]:
    out=[]
    for value in values or ():
        try:v=max(1,int(round(float(value))))
        except (TypeError,ValueError,OverflowError):continue
        if v not in out:out.append(v)
    if not out:out=[max(1,int(fallback))]
    return tuple(sorted(out))


def _plan_confidence(plan: dict) -> float:
    if isinstance(plan.get('confidence'),bool):return 0.0
    try:
        value=float(plan.get('confidence',0) or 0)
        return value if isfinite(value) and 0 <= value <= 1 else 0.0
    except (TypeError,ValueError,OverflowError):return 0.0


def _screen_position(value):
    try:
        return screen_point(value,'brush control')
    except (TypeError,ValueError,OverflowError):return None


def verified_brush_sizes(profile_key: str, browser_brush_plan: dict | None,
                         default_brush_px: int) -> tuple[tuple[int,...], bool]:
    """Return only brush sizes whose UI controls and safety inset were verified."""
    default=max(1,int(default_brush_px or 1))
    plan=browser_brush_plan if isinstance(browser_brush_plan,dict) else {}
    if plan.get('profile_key') and str(plan['profile_key']).lower()!=str(profile_key or '').lower():
        return (default,),False
    nominal=plan.get('nominal_sizes')
    if not isinstance(nominal,(tuple,list)) or not nominal:
        return (default,),False
    try:
        if any(isinstance(v,bool) or not isfinite(float(v)) or float(v)!=int(v) or int(v)<=0 for v in nominal):
            return (default,),False
        nominal=tuple(map(int,nominal))
    except (TypeError,ValueError,OverflowError):
        return (default,),False
    if len(set(nominal))!=len(nominal):return (default,),False
    sizes=tuple(sorted(nominal))
    positions=plan.get('control_positions') or ()
    confidence=_plan_confidence(plan)
    if not isinstance(positions,(tuple,list)):
        return (default,),False
    points=tuple(_screen_position(p) for p in positions)
    target=_screen_position(plan.get('target_position'))
    verified=(target is not None and confidence>=.58 and len(points)==len(sizes)
              and len(sizes)>1 and all(p is not None for p in points)
              and len(set(points))==len(points) and target in points)
    if not verified:
        return (default,),False
    if 'verified_sizes' in plan:
        values=plan.get('verified_sizes')
        if not isinstance(values,(tuple,list)) or not values:
            return (default,),False
        # An explicit subset is authoritative. Empty/invalid evidence must never
        # fall through to the older, guard-bounded whole-ladder contract.
        try:
            verified_set={int(v) for v in values if not isinstance(v,bool) and isfinite(float(v)) and float(v)==int(v) and int(v)>0}
        except (TypeError,ValueError,OverflowError):
            return (default,),False
        indices=plan.get('verified_indices')
        if indices is not None:
            if not isinstance(indices,(tuple,list)) or any(type(i) is not int or not 0<=i<len(nominal) for i in indices):
                return (default,),False
            verified_set.intersection_update(nominal[i] for i in indices)
        usable=tuple(v for v in sizes if v in verified_set)
        if not usable:usable=(default,)
        return usable,len(usable)>1
    try:safe_guard=max(default,int(round(float(plan.get('safe_guard_px',default) or default))))
    except (TypeError,ValueError,OverflowError):safe_guard=default
    usable=tuple(v for v in sizes if v<=safe_guard)
    if not usable:usable=(default,)
    return usable,len(usable)>1


def _nearest_not_above(sizes: Sequence[int], wanted: int) -> int:
    wanted=max(1,int(wanted));below=[int(v) for v in sizes if int(v)<=wanted]
    return max(below) if below else min(map(int,sizes))


def _safe_float(value, default=0.0) -> float:
    try:
        result=float(value)
        return result if isfinite(result) else float(default)
    except (TypeError,ValueError,OverflowError):return float(default)


def _component_thin(entry: dict) -> int | None:
    try:
        w=max(0,int(entry.get('component_width',0) or 0))
        h=max(0,int(entry.get('component_height',0) or 0))
    except (TypeError,ValueError,AttributeError):
        return None
    dims=[v for v in (w,h) if v>0]
    return min(dims) if dims else None


def analyze_brush_demand(execution_sequence: Sequence[dict]) -> dict:
    """Classify planned image geometry without allocating another image buffer."""
    total=0
    detail=protected=high_importance=turn_heavy=narrow=large_foundation=0
    importance_sum=0.0;thin_values=[]
    for raw in execution_sequence or ():
        if not isinstance(raw,dict):continue
        total+=1
        phase=str(raw.get('phase') or 'fine_detail').rsplit('/',1)[-1]
        is_protected=bool(raw.get('protected'))
        importance=max(0.0,min(1.0,_safe_float(raw.get('importance',0),0)))
        path=raw.get('path') or ();turns=max(0,len(path)-2)
        thin=_component_thin(raw)
        try:area=max(0,int(raw.get('component_area',0) or 0))
        except (TypeError,ValueError):area=0
        if phase in ('fine_detail','cleanup') or phase.startswith('correction_'):detail+=1
        if is_protected:protected+=1
        if importance>=.58:high_importance+=1
        if turns>=2:turn_heavy+=1
        if thin is not None:
            thin_values.append(thin)
            if thin<=6:narrow+=1
        if phase in ('fill','foundation','base') and area>=128 and importance<.58 and not is_protected:large_foundation+=1
        importance_sum+=importance
    if total<=0:
        return {'classification':'balanced','detail_score':0.5,'flat_score':0.0,'paths':0,
                'detail_ratio':0.0,'protected_ratio':0.0,'narrow_ratio':0.0,'turn_ratio':0.0,
                'mean_importance':0.0,'large_foundation_ratio':0.0,'median_thin_px':None}
    detail_ratio=detail/total;protected_ratio=protected/total;high_ratio=high_importance/total
    turn_ratio=turn_heavy/total;narrow_ratio=narrow/total;foundation_ratio=large_foundation/total
    mean_importance=importance_sum/total;median_thin=None
    if thin_values:
        ordered=sorted(thin_values);median_thin=ordered[len(ordered)//2]
    detail_score=min(1.0,detail_ratio*.34+protected_ratio*.22+high_ratio*.18+turn_ratio*.10+narrow_ratio*.10+mean_importance*.06)
    flat_score=min(1.0,foundation_ratio*.72+max(0.0,.45-detail_score)*.62)
    classification='detail-heavy' if detail_score>=.48 else 'flat-shape' if flat_score>=.42 and detail_score<=.30 else 'balanced'
    return {'classification':classification,'detail_score':round(detail_score,4),'flat_score':round(flat_score,4),
            'paths':int(total),'detail_ratio':round(detail_ratio,4),'protected_ratio':round(protected_ratio,4),
            'narrow_ratio':round(narrow_ratio,4),'turn_ratio':round(turn_ratio,4),'mean_importance':round(mean_importance,4),
            'large_foundation_ratio':round(foundation_ratio,4),'median_thin_px':median_thin}


def _select_auto_levels(sizes: Sequence[int], default: int, demand: dict,
                        *, dynamic: bool) -> tuple[int,int,int,str]:
    values=tuple(sorted({max(1,int(v)) for v in sizes})) or (max(1,int(default)),)
    smallest=values[0];manual=_nearest_not_above(values,default)
    if not dynamic or len(values)==1:return manual,manual,smallest,'fixed-unverified-controls'
    # Base remains conservative. Large flat regions may independently climb the
    # verified ladder after geometry checks in _foundation_brush().
    growth_cap=max(default,default*2)
    candidates=tuple(v for v in values if v<=growth_cap) or (manual,)
    classification=str(demand.get('classification') or 'balanced')
    if classification=='flat-shape':base=max(candidates);reason='auto-flat-shape'
    elif classification=='detail-heavy':
        target=max(smallest,int(round(default*.75)));base=_nearest_not_above(candidates,target);reason='auto-detail-heavy'
    else:base=_nearest_not_above(candidates,default);reason='auto-balanced'
    lower=[v for v in values if v<base];middle=max(lower) if lower else smallest
    return int(base),int(middle),int(smallest),reason


def _foundation_brush(sizes: Sequence[int], base: int, entry: dict) -> tuple[int,int]:
    """Choose the largest verified width that fits this component's real geometry."""
    values=tuple(sorted({max(1,int(v)) for v in sizes})) or (max(1,int(base)),)
    thin=_component_thin(entry)
    try:area=max(0,int(entry.get('component_area',0) or 0))
    except (TypeError,ValueError,AttributeError):area=0
    path=entry.get('path') or ();turns=max(0,len(path)-2)
    importance=max(0.0,min(1.0,_safe_float(entry.get('importance',0),0)))
    ceiling=max(values)
    # Keep a broad brush well inside the component rather than merely inside its bbox.
    if thin is not None:ceiling=min(ceiling,max(1,int(thin*.45)))
    if area>0:ceiling=min(ceiling,max(1,int((area**.5)*.42)))
    if turns>=2:ceiling=min(ceiling,max(1,int(base)))
    if importance>=.58:ceiling=min(ceiling,max(1,int(base)))
    brush=_nearest_not_above(values,ceiling)
    return int(brush),int(max(1,ceiling))


def _sensitive(entry: dict) -> bool:
    phase=str(entry.get('phase') or 'fine_detail').rsplit('/',1)[-1]
    return bool(entry.get('protected')) or phase in ('fine_detail','cleanup') or phase.startswith('correction_')


def _collapse_transient_upshifts(rows: list[dict]) -> int:
    """Remove A-B-A one-path upshifts when B is only a speed optimization.

    Replacing B with the smaller surrounding brush cannot reduce raster detail;
    it only avoids two UI brush changes whose overhead dominates a single path.
    """
    changed=0
    if len(rows)<3:return changed
    for i in range(1,len(rows)-1):
        previous,current,nxt=rows[i-1],rows[i],rows[i+1]
        try:a=int(previous.get('brush_px',1));b=int(current.get('brush_px',1));c=int(nxt.get('brush_px',1))
        except (TypeError,ValueError):continue
        if a!=c or b<=a or _sensitive(current):continue
        current['brush_px']=a
        current['brush_reason']=str(current.get('brush_reason') or 'auto')+'+switch-hysteresis'
        changed+=1
    return changed


def assign_adaptive_brushes(execution_sequence: Sequence[dict], *, profile_key: str = '',
                            default_brush_px: int = 1,
                            browser_brush_plan: dict | None = None) -> dict:
    default=max(1,int(default_brush_px or 1))
    sizes,dynamic=verified_brush_sizes(profile_key,browser_brush_plan,default)
    demand=analyze_brush_demand(execution_sequence)
    base,middle,smallest,auto_reason=_select_auto_levels(sizes,default,demand,dynamic=dynamic)

    result=[]
    for raw in execution_sequence:
        entry=dict(raw);phase=str(entry.get('phase') or 'fine_detail').rsplit('/',1)[-1]
        protected=bool(entry.get('protected'))
        importance=max(0.0,min(1.0,_safe_float(entry.get('importance',0),0)))
        thin=_component_thin(entry);path=entry.get('path') or ();turns=max(0,len(path)-2)
        brush=base;reason=auto_reason;ceiling=base
        if not dynamic:
            brush=base;reason='fixed-unverified-controls'
        elif phase.startswith('correction_'):
            brush=smallest;reason='accuracy-correction';ceiling=smallest
        elif phase=='cleanup' or protected:
            brush=smallest;reason='protected-detail';ceiling=smallest
        elif phase=='fine_detail':
            brush=smallest;reason='fine-detail';ceiling=smallest
        elif phase=='mid_detail':
            thin_value=thin if thin is not None else 999999
            if thin_value<=max(3,base*2) or importance>=.58 or turns>=2:
                brush=smallest;reason='edge-sensitive-mid-detail';ceiling=smallest
            else:
                brush=middle;reason='mid-detail';ceiling=middle
        elif phase in ('fill','foundation','base'):
            brush,ceiling=_foundation_brush(sizes,base,entry);reason='geometry-foundation'
        elif phase in ('structure','contour','outline'):
            geometric,ceiling=_foundation_brush(sizes,base,entry)
            brush=min(geometric,base if importance>=.46 or (thin is not None and thin<=max(5,base*2)) else geometric)
            reason='structure-detail-balance'
        else:
            brush=base;reason=auto_reason;ceiling=base
        brush=int(max(1,brush));entry['brush_px']=brush;entry['brush_reason']=reason;entry['brush_ceiling_px']=int(max(1,ceiling))
        result.append(entry)

    collapsed=_collapse_transient_upshifts(result) if dynamic else 0
    counts=Counter();reasons=Counter();previous=None;switches=0
    for entry in result:
        brush=int(entry.get('brush_px',base) or base);counts[brush]+=1;reasons[str(entry.get('brush_reason') or 'unknown')]+=1
        if previous is not None and brush!=previous:switches+=1
        previous=brush
    return {'execution_sequence':result,'metadata':{
        'engine':'Adaptive Brush Draw Motor v2','policy_version':5,
        'automatic_image_brush_selection':bool(dynamic),'dynamic_brush_enabled':bool(dynamic),
        'profile_key':str(profile_key or ''),'available_brush_sizes':tuple(map(int,sizes)),
        'used_brush_sizes':tuple(sorted(counts)),'requested_brush_px':default,'default_brush_px':base,
        'detail_brush_px':smallest,'mid_brush_px':middle,'auto_base_reason':auto_reason,
        'image_brush_demand':demand,'brush_path_counts':{str(k):int(v) for k,v in sorted(counts.items())},
        'brush_reason_counts':dict(reasons),'planned_brush_switches':int(switches),
        'transient_upshifts_collapsed':int(collapsed),'geometry_changed':False,
        'quality_priority':'all independently verified sizes for safe broad regions; protected/detail paths use the smallest verified brush','brush_aware_canvasguard':bool((browser_brush_plan or {}).get('verified_sizes'))}}


def brush_for_entry(entry: dict, default_brush_px: int) -> int:
    try:return max(1,int(entry.get('brush_px',default_brush_px) or default_brush_px))
    except (TypeError,ValueError,AttributeError):return max(1,int(default_brush_px or 1))


def brush_sizes_for_sequence(sequence, default_brush_px: int) -> list[int]:
    """Report brushes actually used, retaining state across implicit entries."""
    current = max(1, int(default_brush_px or 1))
    sizes = set()
    for entry in sequence:
        if not isinstance(entry, dict) or not entry.get('path'):
            continue
        current = brush_for_entry(entry, current)
        sizes.add(current)
    return sorted(sizes) or [max(1, int(default_brush_px or 1))]
