"""Adaptive palette fidelity / anti-posterization planning for Image Draw Bot v1.0.123.

This module sits *after* source->game palette matching.  Its job is to decide
how many of the calibrated game colours are worth retaining under a deadline.
It deliberately treats a colour switch as a small execution cost instead of
an excuse to collapse a rich image to a fixed 4/6/8-colour palette.

Pure planning code: no GUI, mouse, browser, network or filesystem access.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable, Sequence

from ColorFidelity import color_metrics, delta_e2000, palette_match_cost, validate_color_fidelity
from DominantHuePreservation import dominant_hue_anchors, dominant_hue_family
from RegionAwareQuantization import region_detail_anchor_candidates
from SmartColorEngine import smart_color_weights, should_keep_color_candidate

Segment = tuple[int, int, int, int]


def _stroke_weight(stroke) -> float:
    try:
        x1, y1, x2, y2 = map(float, stroke)
        return max(1.0, hypot(x2 - x1, y2 - y1))
    except Exception:
        return 1.0


def group_weights(groups: Sequence[Sequence[tuple]]) -> list[float]:
    return [sum(_stroke_weight(s) for s in g) for g in groups]


def adaptive_palette_cap(seconds: int | float, fidelity: str, *, profile_key: str = "",
                         paths_per_second: float | None = None) -> int:
    """Return a deadline-aware *upper* palette budget.

    The old browser policy used 4/6/8 fixed colours.  That saved little real
    time (a palette switch is cheap compared with thousands of strokes) while
    causing severe posterization.  v1.0.123 therefore allows more colours in
    Balanced/Faithful modes and lets the selector stop early when additional
    colours no longer buy useful perceptual accuracy.
    """
    validate_color_fidelity(fidelity)
    sec = max(5, int(float(seconds)))
    if sec <= 30:
        table = {"Fast": 4, "Balanced": 10, "Faithful": 14, "Exact": 18}
    elif sec <= 60:
        table = {"Fast": 6, "Balanced": 16, "Faithful": 28, "Exact": 36}
    elif sec <= 90:
        table = {"Fast": 8, "Balanced": 20, "Faithful": 34, "Exact": 44}
    elif sec <= 120:
        table = {"Fast": 10, "Balanced": 26, "Faithful": 40, "Exact": 52}
    elif sec <= 180:
        table = {"Fast": 12, "Balanced": 30, "Faithful": 46, "Exact": 60}
    else:
        table = {"Fast": 14, "Balanced": 36, "Faithful": 56, "Exact": 72}
    cap = table[fidelity]

    # Extremely slow measured input can justify a modest reduction, but never
    # collapse Faithful/Exact back to the old 4/6-colour failure mode.
    pps = None if paths_per_second is None else max(0.0, float(paths_per_second))
    if pps is not None and pps > 0:
        if pps < 3.0:
            cap = int(round(cap * 0.78))
        elif pps < 4.5:
            cap = int(round(cap * 0.90))
    floors = {"Fast": 3, "Balanced": 8, "Faithful": 12, "Exact": 16}
    cap = max(floors[fidelity], cap)

    # Skribbl Fast remains intentionally lean, but no longer hard-clamps to six
    # when the user explicitly asks for Faithful/Exact colour fidelity.
    key = str(profile_key or "").lower()
    if key == "skribbl-fast":
        cap = min(cap, {"Fast": 6, "Balanced": 12, "Faithful": 20, "Exact": 28}[fidelity])
    return max(2, min(72, int(cap)))


def _tone_bin(rgb: Sequence[int]) -> int:
    L = color_metrics(tuple(map(int, rgb[:3])))[0]
    return min(4, max(0, int(L // 20.0)))


def _hue_bin(rgb: Sequence[int]) -> int | None:
    _L, sat, hue, _lum = color_metrics(tuple(map(int, rgb[:3])))
    if sat < 12.0:
        return None
    return int(hue // 30.0) % 12


def _spatial_anchor_candidates(groups: Sequence[Sequence[Segment]], active: Sequence[int],
                               weights: Sequence[float]) -> list[int]:
    """Return dominant colours from a bounded 3x3 spatial grid.

    This is a cheap regional palette allocation: an important background/side
    object can keep a colour even if another large object dominates globally.
    """
    coords: list[tuple[float, float, float, int]] = []
    xs: list[float] = []; ys: list[float] = []
    for i in active:
        for s in groups[i]:
            try:
                x1, y1, x2, y2 = map(float, s)
            except Exception:
                continue
            w = max(1.0, hypot(x2-x1, y2-y1))
            cx = (x1+x2)*0.5; cy=(y1+y2)*0.5
            coords.append((cx,cy,w,i)); xs.append(cx); ys.append(cy)
    if not coords:
        return []
    xmin,xmax=min(xs),max(xs); ymin,ymax=min(ys),max(ys)
    dx=max(1.0,xmax-xmin); dy=max(1.0,ymax-ymin)
    cells: dict[tuple[int,int],dict[int,float]] = {}
    for x,y,w,i in coords:
        cx=min(2,max(0,int((x-xmin)/dx*3.0)))
        cy=min(2,max(0,int((y-ymin)/dy*3.0)))
        bucket=cells.setdefault((cx,cy),{})
        bucket[i]=bucket.get(i,0.0)+w
    out=[]
    for cell in sorted(cells):
        by_color=cells[cell]
        if by_color:
            out.append(max(by_color,key=lambda i:(by_color[i],weights[i],-i)))
    return list(dict.fromkeys(out))


def _base_anchors(groups: Sequence[Sequence[Segment]], palette: Sequence[tuple[int,int,int]],
                  active: Sequence[int], weights: Sequence[float], cap: int,
                  fidelity: str, priority_anchors: Sequence[int]=()) -> list[int]:
    ranked=sorted(active,key=lambda i:(-weights[i],i))
    keep: list[int] = []
    def add(i):
        if i in active and i not in keep and len(keep)<cap:
            keep.append(i)
    # Step 3: reserve palette slots for large chromatic source families before
    # spending capacity on extra tone/shade/detail anchors. Step 4 also folds a
    # global light/dark extreme into an already-reserved hue family when the cap
    # is tight. That preserves the family *and* avoids losing a critical highlight
    # merely because a heavier midtone was chosen as that family's representative.
    dominant_anchors,_dominant_meta=dominant_hue_anchors(palette,weights,cap,fidelity=fidelity)
    darkest=min(active,key=lambda i:(color_metrics(palette[i])[0],-weights[i],i))
    brightest=max(active,key=lambda i:(color_metrics(palette[i])[0],weights[i],-i))
    dom_families={dominant_hue_family(palette[i]):pos for pos,i in enumerate(dominant_anchors)}
    for extreme in (brightest,darkest):
        family=dominant_hue_family(palette[extreme])
        if family in dom_families and extreme not in dominant_anchors:
            pos=dom_families[family]
            dominant_anchors[pos]=extreme
    for i in dominant_anchors:
        add(i)
    add(darkest); add(brightest)
    # Smart Color anchors come after broad hue/extreme protection so a local
    # accent cannot evict the image's essential hue structure.
    for i in priority_anchors:
        add(int(i))

    # Preserve a luminance ladder after dominant hue families. This remains the
    # anti-muddy-shadow guard, but it may no longer consume a dominant hue slot.
    for tb in range(5):
        candidates=[i for i in active if _tone_bin(palette[i])==tb]
        if candidates:
            add(max(candidates,key=lambda i:(weights[i],-i)))

    # Step 4: reserve a very small part of the remaining capacity for localized
    # high-contrast details before spending slots on extra global hue shades.
    # This is region-aware but bounded, so main hue families remain authoritative.
    if fidelity in ("Balanced","Faithful","Exact"):
        for i in region_detail_anchor_candidates(groups,palette,active,weights,cap):
            add(i)

    if fidelity in ("Balanced","Faithful","Exact"):
        # Fine 30-degree hue bins are now supplemental shade diversity only.
        # Dominant broad families above have already received guaranteed slots.
        for hb in range(12):
            candidates=[i for i in active if _hue_bin(palette[i])==hb]
            if candidates:
                add(max(candidates,key=lambda i:(weights[i],-i)))

    if fidelity in ("Faithful","Exact"):
        for i in _spatial_anchor_candidates(groups,active,weights):
            add(i)

    # Enough global mass to make the first candidate set stable.
    minimum=min(cap, max(4, int(round(cap * (0.42 if fidelity in ("Faithful","Exact") else 0.34)))))
    for i in ranked:
        if len(keep)>=minimum: break
        add(i)
    return keep


def _map_indices(active: Sequence[int], keep: Sequence[int], palette: Sequence[tuple[int,int,int]],
                 weights: Sequence[float], fidelity: str, *, cost_cache=None, error_cache=None) -> tuple[dict[int,int], list[tuple[int,float,float]]]:
    mapping: dict[int,int]={}
    errors=[]
    def cost(i,j):
        key=(i,j)
        if cost_cache is not None and key in cost_cache:
            return cost_cache[key]
        value=palette_match_cost(palette[i],palette[j],color_rendering="Perceptual match",fidelity=fidelity)
        if cost_cache is not None:
            cost_cache[key]=value
        return value
    for i in active:
        if i in keep:
            target=i; de=0.0
        else:
            target=min(keep,key=lambda j:(cost(i,j),-weights[j],j))
            key=(i,target)
            if error_cache is not None and key in error_cache:
                de=error_cache[key]
            else:
                de=delta_e2000(palette[i],palette[target])
                if error_cache is not None:
                    error_cache[key]=de
        mapping[i]=target
        errors.append((i,float(de),float(weights[i])))
    return mapping,errors


def _weighted_percentile(errors: Sequence[tuple[int,float,float]], q: float) -> float:
    rows=sorted((de,max(0.0,w)) for _i,de,w in errors if w>0)
    total=sum(w for _de,w in rows)
    if total<=0:return 0.0
    threshold=total*max(0.0,min(1.0,float(q))); acc=0.0
    for de,w in rows:
        acc+=w
        if acc>=threshold:return float(de)
    return float(rows[-1][0]) if rows else 0.0


def palette_quality_metrics(active: Sequence[int], keep: Sequence[int], palette: Sequence[tuple[int,int,int]],
                            weights: Sequence[float], mapping: dict[int,int],
                            errors: Sequence[tuple[int,float,float]], *, fidelity: str="Faithful",
                            max_colors: int | None=None) -> dict:
    total=sum(max(0.0,weights[i]) for i in active) or 1.0
    avg=sum(de*w for _i,de,w in errors)/total
    p95=_weighted_percentile(errors,.95)
    coverage=sum(w for _i,de,w in errors if de<=6.0)/total*100.0
    active_tones={_tone_bin(palette[i]) for i in active}
    kept_tones={_tone_bin(palette[i]) for i in keep}
    lost_tones=active_tones-kept_tones
    active_mid={b for b in active_tones if b in (1,2,3)}
    kept_mid={b for b in kept_tones if b in (1,2,3)}
    midtone_loss=bool(active_mid-kept_mid)
    tone_loss_ratio=len(lost_tones)/max(1,len(active_tones))
    dominant_cap=max(0,int(max_colors if max_colors is not None else len(keep)))
    _dominant_indexes,_dominant_meta=dominant_hue_anchors(palette,weights,dominant_cap,fidelity=fidelity)
    dominant_before=set(_dominant_meta.get('dominant_hue_families',()))
    kept_families={dominant_hue_family(palette[i]) for i in keep}
    kept_families.discard(None)
    lost_dominant=dominant_before-kept_families
    hue_preservation=(len(dominant_before-lost_dominant)/max(1,len(dominant_before))*100.0) if dominant_before else 100.0
    risk=min(1.0,(p95/28.0)*.45 + (1.0-coverage/100.0)*.35 + tone_loss_ratio*.20)
    if midtone_loss:risk=min(1.0,risk+.12)
    if lost_dominant:risk=min(1.0,risk+.20*len(lost_dominant))
    risk_label="LOW" if risk<.28 else ("MEDIUM" if risk<.50 else "HIGH")
    return {
        'palette_coverage_percent':round(coverage,2),
        'average_reduction_delta_e2000':round(avg,2),
        'p95_reduction_delta_e2000':round(p95,2),
        'posterization_risk':risk_label,
        'posterization_score':round(risk,3),
        'midtone_loss':midtone_loss,
        'tone_bins_before':len(active_tones),
        'tone_bins_after':len(kept_tones),
        'lost_tone_bins':tuple(sorted(lost_tones)),
        'dominant_hue_families_before':tuple(sorted(dominant_before)),
        'dominant_hue_families_after':tuple(sorted(f for f in kept_families if f in dominant_before)),
        'lost_dominant_hue_families':tuple(sorted(lost_dominant)),
        'dominant_hue_preservation_percent':round(hue_preservation,2),
    }


def select_adaptive_palette(groups: Sequence[Sequence[Segment]], palette_rgb: Sequence[Sequence[int]],
                            max_colors: int, *, fidelity: str="Faithful",
                            color_switch_seconds: float=.065) -> tuple[list[int],dict[int,int],dict]:
    """Select retained colours by visual gain per colour-switch cost.

    ``max_colors`` is a deadline-aware ceiling.  The selector starts with tone,
    hue and spatial anchors, then adds the colour that removes the most weighted
    perceptual error per estimated palette-switch second until the result is no
    longer posterized or the ceiling is reached.
    """
    validate_color_fidelity(fidelity)
    limit=int(max_colors)
    if limit < 1:
        raise ValueError('Palette limit must be positive.')
    palette=[tuple(map(int,r[:3])) for r in palette_rgb]
    base_weights=group_weights(groups)
    weights,smart_meta=smart_color_weights(groups,palette,base_weights,fidelity=fidelity)
    active=[i for i,w in enumerate(weights) if w>0 and i<len(palette)]
    cap=min(limit,len(active)) if active else limit
    if not active:
        meta={'active_colors_before':0,'active_colors_after':0,'max_colors':int(max_colors),'posterization_risk':'LOW','palette_coverage_percent':100.0}
        meta.update(smart_meta);meta['smart_color_switch_cost_seconds']=round(max(.005,float(color_switch_seconds)),6)
        return [],{},meta
    if len(active)<=cap:
        mapping={i:i for i in active}
        errors=[(i,0.0,weights[i]) for i in active]
        meta=palette_quality_metrics(active,active,palette,weights,mapping,errors,fidelity=fidelity,max_colors=cap)
        _dominant_indexes,_dominant_selection_meta=dominant_hue_anchors(palette,weights,cap,fidelity=fidelity)
        _region_detail_indexes=region_detail_anchor_candidates(groups,palette,active,weights,cap)
        meta.update(smart_meta)
        meta.update({'active_colors_before':len(active),'active_colors_after':len(active),'max_colors':int(max_colors),'selected_colors':len(active),'visual_gain_per_color_switch':0.0,
                     'smart_color_switch_cost_seconds':round(max(.005,float(color_switch_seconds)),6),
                     'smart_color_cost_stop':False,
                     'kept_color_indexes':tuple(map(int,active)),
                     'region_aware_quantization':True,
                     'region_detail_anchor_indexes':tuple(map(int,_region_detail_indexes)),
                     'dominant_hue_anchor_indexes':tuple(map(int,_dominant_indexes)),
                     'dominant_hue_families_selected':tuple(_dominant_selection_meta.get('dominant_hue_families',())),
                     'dominant_hue_coverage':dict(_dominant_selection_meta.get('dominant_hue_coverage',{})),
                     'dominant_hue_preservation':bool(_dominant_selection_meta.get('dominant_hue_preservation',False))})
        return list(active),mapping,meta

    keep=_base_anchors(groups,palette,active,weights,cap,fidelity,smart_meta.get('smart_color_anchor_indexes',()))
    cost_cache,error_cache={},{}
    mapping,errors=_map_indices(active,keep,palette,weights,fidelity,
                                cost_cache=cost_cache,error_cache=error_cache)
    metrics=palette_quality_metrics(active,keep,palette,weights,mapping,errors,fidelity=fidelity,max_colors=cap)
    last_gain=0.0;last_relative_gain=0.0;cost_stop=False
    # Faithful/Exact demand a better reduced palette before stopping.
    target_risk={"Fast":.52,"Balanced":.40,"Faithful":.28,"Exact":.20}[fidelity]
    while len(keep)<cap and metrics['posterization_score']>target_risk:
        best=None
        current_error={i:de*weights[i] for i,de,_w in errors}
        old_total=sum(current_error.values())
        for candidate in active:
            if candidate in keep: continue
            trial_keep=keep+[candidate]
            _m,_e=_map_indices(active,trial_keep,palette,weights,fidelity,
                               cost_cache=cost_cache,error_cache=error_cache)
            new_total=sum(de*w for _i,de,w in _e)
            delta=max(0.0,old_total-new_total)
            relative=delta/max(1e-9,old_total)
            gain=delta/max(.005,float(color_switch_seconds))
            if best is None or gain>best[0]:
                best=(gain,relative,candidate,_m,_e)
        if not best:break
        candidate_gain,candidate_relative,candidate,candidate_mapping,candidate_errors=best
        if not should_keep_color_candidate(candidate_relative,float(metrics['posterization_score']),fidelity,color_switch_seconds):
            cost_stop=True;break
        last_gain,last_relative_gain=candidate_gain,candidate_relative
        mapping,errors=candidate_mapping,candidate_errors
        keep.append(candidate)
        metrics=palette_quality_metrics(active,keep,palette,weights,mapping,errors,fidelity=fidelity,max_colors=cap)

    _dominant_indexes,_dominant_selection_meta=dominant_hue_anchors(palette,weights,cap,fidelity=fidelity)
    _region_detail_indexes=region_detail_anchor_candidates(groups,palette,active,weights,cap)
    metrics.update(smart_meta)
    metrics.update({
        'active_colors_before':len(active),'active_colors_after':len(keep),
        'smart_color_switch_cost_seconds':round(max(.005,float(color_switch_seconds)),6),
        'smart_color_last_relative_gain_percent':round(float(last_relative_gain)*100.0,4),
        'smart_color_cost_stop':bool(cost_stop),
        'region_aware_quantization':True,
        'region_detail_anchor_indexes':tuple(map(int,_region_detail_indexes)),
        'region_detail_anchors_kept':tuple(map(int,[i for i in _region_detail_indexes if i in keep])),
        'max_colors':int(max_colors),'selected_colors':len(keep),
        'visual_gain_per_color_switch':round(float(last_gain),2),
        'kept_color_indexes':tuple(map(int,keep)),
        'dominant_hue_anchor_indexes':tuple(map(int,_dominant_indexes)),
        'dominant_hue_families_selected':tuple(_dominant_selection_meta.get('dominant_hue_families',())),
        'dominant_hue_coverage':dict(_dominant_selection_meta.get('dominant_hue_coverage',{})),
        'dominant_hue_preservation':bool(_dominant_selection_meta.get('dominant_hue_preservation',False)),
    })
    return keep,mapping,metrics
