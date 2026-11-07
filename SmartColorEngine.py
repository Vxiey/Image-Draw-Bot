"""Smart Color Engine for Image Draw Bot.

Pure planning helpers used by AdaptivePaletteFidelity. The engine raises the
priority of small but locally dominant / perceptually unique colours without
allowing them to overwhelm broad coverage. It also provides a conservative
marginal-value gate so colour-switch cost can influence when palette growth
stops instead of merely changing a diagnostic number.
"""
from __future__ import annotations

from math import hypot
from typing import Sequence

from ColorFidelity import delta_e2000

Segment = tuple[int,int,int,int]


def _stroke_mass(stroke) -> float:
    try:
        x1,y1,x2,y2=map(float,stroke)
        return max(1.0,hypot(x2-x1,y2-y1))
    except Exception:
        return 1.0


def _clamp(value: float, lo: float=0.0, hi: float=1.0) -> float:
    return max(lo,min(hi,float(value)))


def smart_color_weights(groups: Sequence[Sequence[Segment]], palette_rgb: Sequence[Sequence[int]],
                        base_weights: Sequence[float], *, fidelity: str='Faithful', grid: int=4):
    """Return importance-adjusted colour weights plus deterministic diagnostics.

    The multiplier is driven by local cell dominance, spatial locality and
    perceptual uniqueness. Total weight is re-normalized afterwards so this is
    a redistribution of importance, not an artificial increase in image mass.
    """
    palette=[tuple(map(int,row[:3])) for row in palette_rgb]
    n=max(len(groups),len(base_weights),len(palette))
    base=[float(base_weights[i]) if i<len(base_weights) else 0.0 for i in range(n)]
    active=[i for i in range(min(len(groups),len(palette))) if base[i]>0 and groups[i]]
    empty_meta={
        'smart_color_engine':'Smart Color Engine v1','smart_color_enabled':False,
        'smart_color_grid':f'{max(2,int(grid))}x{max(2,int(grid))}',
        'smart_color_anchor_indexes':(), 'smart_color_unique_indexes':(),
        'smart_color_priority_multipliers':{}, 'smart_color_max_priority_multiplier':1.0,
    }
    if not active:
        return base,empty_meta

    g=max(2,min(8,int(grid)))
    from ColorSpatialSummary import midpoint_color_cells
    cells=midpoint_color_cells(groups,active,g)
    if not cells:
        return base,empty_meta

    max_base=max(base[i] for i in active) or 1.0
    coefficients={
        'Fast':(.10,.06,.05,1.28),
        'Balanced':(.26,.14,.09,1.65),
        'Faithful':(.44,.23,.14,2.00),
        'Exact':(.50,.28,.16,2.20),
    }
    local_k,unique_k,scarce_k,cap=coefficients.get(str(fidelity),coefficients['Faithful'])
    multipliers={};anchor_scores={};unique_indexes=[]
    nearest_distances={ci:100.0 for ci in active}
    for position,ci in enumerate(active):
        for other in active[position+1:]:
            distance=float(delta_e2000(palette[ci],palette[other]))
            nearest_distances[ci]=min(nearest_distances[ci],distance)
            nearest_distances[other]=min(nearest_distances[other],distance)
    for ci in active:
        shares=[];dominant_cells=0;occupied=0
        for bucket in cells.values():
            if ci not in bucket:continue
            occupied+=1;total=sum(bucket.values()) or 1.0
            share=bucket[ci]/total;shares.append(share)
            top=max(bucket,key=lambda k:(bucket[k],-k))
            if top==ci:dominant_cells+=1
        local_dom=max(shares or [0.0])
        locality=1.0-_clamp((occupied-1)/max(1.0,g*g*.50))
        cell_authority=_clamp(dominant_cells/max(1,occupied))
        nearest=nearest_distances[ci]
        uniqueness=_clamp((nearest-2.5)/22.0)
        if nearest>=12.0:unique_indexes.append(ci)
        scarcity=1.0-_clamp(base[ci]/max_base)
        local_signal=local_dom*(.55+.45*locality)
        multiplier=1.0 + local_k*local_signal + unique_k*uniqueness + scarce_k*scarcity*local_dom
        multiplier += .08*cell_authority*locality if fidelity!='Fast' else 0.0
        multiplier=max(.80,min(cap,multiplier));multipliers[ci]=multiplier
        anchor_scores[ci]=local_signal*.58+uniqueness*.27+cell_authority*.15

    raw=[0.0]*n
    for i in range(n):raw[i]=base[i]*multipliers.get(i,1.0)
    base_total=sum(base[i] for i in active) or 1.0
    raw_total=sum(raw[i] for i in active) or base_total
    scale=base_total/raw_total
    adjusted=[raw[i]*scale for i in range(n)]

    # Only a bounded set is eligible for guaranteed local-priority anchoring.
    # Broad dominant colours are already protected by the normal hue/tone logic;
    # these anchors are mainly for locally authoritative accents/details.
    limit=max(2,min(8,(len(active)+3)//4))
    candidates=[i for i in active if anchor_scores[i]>=.42]
    candidates.sort(key=lambda i:(-anchor_scores[i],-multipliers[i],i))
    anchors=tuple(candidates[:limit])
    meta={
        'smart_color_engine':'Smart Color Engine v1','smart_color_enabled':True,
        'smart_color_grid':f'{g}x{g}','smart_color_anchor_indexes':anchors,
        'smart_color_unique_indexes':tuple(sorted(unique_indexes)),
        'smart_color_priority_multipliers':{str(i):round(multipliers[i],4) for i in active},
        'smart_color_max_priority_multiplier':round(max(multipliers.values()),4),
        'smart_color_weight_normalization':round(scale,6),
    }
    return adjusted,meta


def should_keep_color_candidate(relative_gain: float, posterization_score: float, fidelity: str,
                                color_switch_seconds: float) -> bool:
    """Conservative marginal-value gate for adding another palette colour."""
    fidelity=str(fidelity or 'Faithful')
    force_risk={'Fast':.62,'Balanced':.52,'Faithful':.38,'Exact':.31}.get(fidelity,.38)
    if float(posterization_score)>=force_risk:
        return True
    base_threshold={'Fast':.0100,'Balanced':.0045,'Faithful':.0018,'Exact':.00045}.get(fidelity,.0018)
    cost_scale=max(.30,min(5.0,float(color_switch_seconds or .065)/.065))
    return max(0.0,float(relative_gain)) >= base_threshold*cost_scale
