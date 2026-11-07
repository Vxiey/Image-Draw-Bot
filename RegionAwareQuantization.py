"""Region-aware colour quantization helpers for Image Draw Bot Step 4.

The colour reducer previously reasoned almost entirely about global colour mass.
That is insufficient for textured objects: several nearby shades from one object
can consume palette capacity while a small high-contrast feature, highlight or
shadow disappears.  This module adds a cheap spatial/structural context layer.

It is deterministic planning code only.  It does not alter mouse execution,
stroke geometry, fill planning, time budgets, profile calibration or UI state.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from math import sqrt
from typing import Sequence

import numpy as np
from PIL import Image

from ColorFidelity import delta_e_oklab, oklab_metrics
from DominantHuePreservation import dominant_hue_family

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class RegionColorStats:
    qindex: int
    pixel_count: int
    coverage: float
    lightness: float
    hue_family: str | None
    tone_role: str
    edge_fraction: float
    importance: float
    protected_fraction: float
    spatial_concentration: float
    tile_weights: tuple[float, ...]


def _as_rgb(rgb: Sequence[int | float]) -> RGB:
    vals=list(rgb[:3])
    while len(vals)<3:
        vals.append(0)
    return tuple(max(0,min(255,int(round(float(v))))) for v in vals)  # type: ignore[return-value]


def _tone_roles(entries: Sequence[dict]) -> dict[int,str]:
    """Classify shades relative to other colours in the same broad hue family."""
    by_family: dict[str,list[tuple[int,float,float]]] = {}
    out: dict[int,str] = {}
    for e in entries:
        q=int(e['qindex']); rgb=_as_rgb(e['rgb']); count=max(0.0,float(e.get('count',0)))
        family=dominant_hue_family(rgb)
        L,_C,_H=oklab_metrics(rgb)
        if family is None:
            # Neutral extremes remain useful structural roles.
            out[q] = 'highlight' if L>=82.0 else ('shadow' if L<=28.0 else 'midtone')
        else:
            by_family.setdefault(family,[]).append((q,L,count))
    for family,rows in by_family.items():
        total=sum(w for _q,_L,w in rows) or 1.0
        mean=sum(L*w for _q,L,w in rows)/total
        lo=min(L for _q,L,_w in rows); hi=max(L for _q,L,_w in rows)
        spread=hi-lo
        for q,L,_w in rows:
            if spread>=13.0 and L <= mean-5.5:
                out[q]='shadow'
            elif spread>=13.0 and L >= mean+5.5:
                out[q]='highlight'
            else:
                out[q]='midtone'
    return out


def _local_importance(rgb: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
    """Return bounded local-contrast importance and hard-edge masks.

    This intentionally stays lighter than VisualImportanceMap.  Dynamic colour
    planning can run before the deadline renderer has built its reusable full
    importance map, so Step 4 uses a compact NumPy signal unless the caller
    supplies the AdaptiveDetail protected mask.
    """
    try:
        f=rgb.astype(np.float32)/255.0
        lum=f[...,0]*.2126+f[...,1]*.7152+f[...,2]*.0722
        diff=np.zeros_like(lum,dtype=np.float32)
        count=np.zeros_like(lum,dtype=np.float32)
        if lum.shape[1]>1:
            d=np.abs(lum[:,1:]-lum[:,:-1])
            diff[:,1:]+=d; diff[:,:-1]+=d; count[:,1:]+=1; count[:,:-1]+=1
        if lum.shape[0]>1:
            d=np.abs(lum[1:,:]-lum[:-1,:])
            diff[1:,:]+=d; diff[:-1,:]+=d; count[1:,:]+=1; count[:-1,:]+=1
        local=diff/np.maximum(count,1.0)
        # Fixed thresholds make diagnostics deterministic across images.
        importance=np.clip(local*5.5,0.0,1.0).astype(np.float32,copy=False)
        edge=(local>=0.075).astype(np.float32,copy=False)
        return importance,edge
    finally:
        rgb=None


def build_region_context(source: Image.Image, labels: Image.Image, entries: Sequence[dict], *,
                         protected_mask: Image.Image | None=None, grid_size: int=6,
                         cancelled=lambda:False, drawable_mask=None, _source_data=None) -> dict:
    """Analyse spatial adjacency, local structure and relative tone roles.

    ``labels`` is the temporary quantizer label image.  The analysis is O(pixels)
    and uses bounded ``grid_size``/label matrices rather than Python objects per
    pixel.  It is deliberately approximate: adjacency + local contrast are a
    safer proxy for "same object" than global colour distance alone.
    """
    if cancelled():
        raise InterruptedError()
    src=None
    try:
        if _source_data is None:
            # Direct callers keep their existing RGB conversion semantics. Dynamic
            # color planning already prepared the visible (composited) RGB pixels.
            with closing(source.convert('RGB')) as converted:
                src=np.asarray(converted,dtype=np.uint8)
        else:
            src=_source_data.rgb_for(source)
        lab=np.asarray(labels,dtype=np.int32)
        if src.shape[:2] != lab.shape[:2]:
            raise ValueError('Region-aware quantization requires source and label images at the same resolution.')
        if cancelled():raise InterruptedError()
        if lab.ndim != 2:
            raise ValueError('Region color labels must be a single-channel image.')
        h,w=lab.shape
        draw=np.ones((h,w),dtype=bool) if drawable_mask is None else np.asarray(drawable_mask)
        if draw.shape!=lab.shape or draw.dtype!=np.bool_:
            raise ValueError('Drawable region mask must be Boolean and match the label image.')
        pixels=max(1,int(np.count_nonzero(draw)))
        grid=max(2,min(12,int(grid_size)))
        qindexes=sorted({int(e['qindex']) for e in entries})
        if not qindexes:
            return {'stats':{},'adjacency':{},'grid_size':grid,'diagnostics':{'region_aware_quantization':False}}
        max_label=max(max(qindexes),int(lab.max(initial=0)))+1

        local_importance,edge=_local_importance(src)
    finally:
        src=None
    if cancelled():raise InterruptedError()
    protected=np.zeros((h,w),dtype=np.float32)
    if protected_mask is not None:
        try:
            with closing(protected_mask.resize((w,h),Image.Resampling.NEAREST)) as resized:
                with closing(resized.convert('L')) as grayscale:
                    pm=np.asarray(grayscale,dtype=np.float32)/255.0
            protected=np.clip(pm,0.0,1.0)
            # Hard AdaptiveDetail protection is authoritative; soft focus values
            # contribute proportionally instead of turning the whole centre into
            # an unmergeable region.
            local_importance=np.maximum(local_importance,protected*.82)
        except Exception:
            protected=np.zeros((h,w),dtype=np.float32)

    flat_labels=lab[draw]
    counts=np.bincount(flat_labels,minlength=max_label).astype(np.float64)
    imp_sum=np.bincount(flat_labels,weights=local_importance[draw],minlength=max_label)
    edge_sum=np.bincount(flat_labels,weights=edge[draw],minlength=max_label)
    prot_sum=np.bincount(flat_labels,weights=protected[draw],minlength=max_label)

    # Build tile ids from 1-D axes rather than np.indices().  This keeps the
    # region-analysis scratch memory bounded on full-resolution canvases.
    tx=np.minimum(grid-1,(np.arange(w,dtype=np.int32)*grid)//max(1,w))
    ty=np.minimum(grid-1,(np.arange(h,dtype=np.int32)*grid)//max(1,h))
    tile=(ty[:,None]*grid+tx[None,:])[draw]
    combo=flat_labels*(grid*grid)+tile
    tile_counts=np.bincount(combo,minlength=max_label*grid*grid).reshape(max_label,grid*grid).astype(np.float64)
    if cancelled():raise InterruptedError()

    # Boundary adjacency counts between temporary quantizer labels.  Repeated
    # contact is strong evidence that two close same-hue colours are texture or
    # shading inside one object rather than unrelated global swatches.
    adjacency_counts: dict[tuple[int,int],float] = {}
    boundary=np.zeros(max_label,dtype=np.float64)
    def add_pairs(a: np.ndarray,b: np.ndarray,valid: np.ndarray):
        if cancelled():raise InterruptedError()
        mask=(a!=b)&valid
        if not np.any(mask):
            return
        aa=a[mask].astype(np.int64,copy=False); bb=b[mask].astype(np.int64,copy=False)
        boundary[:] += np.bincount(aa,minlength=max_label)
        boundary[:] += np.bincount(bb,minlength=max_label)
        lo=np.minimum(aa,bb); hi=np.maximum(aa,bb)
        packed=lo*max_label+hi
        vals,nums=np.unique(packed,return_counts=True)
        for val,num in zip(vals,nums):
            if cancelled():raise InterruptedError()
            i=int(val//max_label); j=int(val%max_label)
            adjacency_counts[(i,j)]=adjacency_counts.get((i,j),0.0)+float(num)
    if w>1: add_pairs(lab[:,:-1].ravel(),lab[:,1:].ravel(),(draw[:,:-1]&draw[:,1:]).ravel())
    if h>1: add_pairs(lab[:-1,:].ravel(),lab[1:,:].ravel(),(draw[:-1,:]&draw[1:,:]).ravel())

    roles=_tone_roles(entries)
    entry_rgb={int(e['qindex']):_as_rgb(e['rgb']) for e in entries}
    stats: dict[int,RegionColorStats] = {}
    for q in qindexes:
        if cancelled():raise InterruptedError()
        n=max(1.0,float(counts[q] if q<len(counts) else 0.0))
        tiles=tile_counts[q] if q<len(tile_counts) else np.zeros(grid*grid,dtype=np.float64)
        norm=tiles/n
        L,_C,_H=oklab_metrics(entry_rgb[q])
        stats[q]=RegionColorStats(
            qindex=q,pixel_count=int(round(n)),coverage=float(n/pixels),lightness=float(L),
            hue_family=dominant_hue_family(entry_rgb[q]),tone_role=roles.get(q,'midtone'),
            edge_fraction=float(edge_sum[q]/n),importance=float(imp_sum[q]/n),
            protected_fraction=float(prot_sum[q]/n),spatial_concentration=float(np.max(norm,initial=0.0)),
            tile_weights=tuple(float(v) for v in norm),
        )

    adjacency: dict[tuple[int,int],float] = {}
    for (i,j),contacts in adjacency_counts.items():
        denom=max(1.0,min(boundary[i],boundary[j]))
        adjacency[(i,j)]=max(0.0,min(1.0,float(contacts/denom)))

    protected_details=sum(1 for s in stats.values() if s.coverage<=.035 and (s.importance>=.30 or s.protected_fraction>=.22))
    texture_buckets=sum(1 for s in stats.values() if s.edge_fraction<.18 and s.importance<.28)
    if cancelled():raise InterruptedError()
    return {
        'stats':stats,'adjacency':adjacency,'grid_size':grid,
        'diagnostics':{
            'region_aware_quantization':True,'region_grid':f'{grid}x{grid}',
            'region_color_buckets':len(stats),'protected_detail_buckets':protected_details,
            'low_detail_texture_buckets':texture_buckets,
            'adjacent_color_pairs':len(adjacency),
            'protected_mask_used':bool(protected_mask is not None),
        },
    }


def _members(cluster_or_items) -> list[dict]:
    if isinstance(cluster_or_items,dict) and 'items' in cluster_or_items:
        return list(cluster_or_items.get('items') or [])
    if isinstance(cluster_or_items,dict):
        return [cluster_or_items]
    return list(cluster_or_items or [])


def _weighted_stats(items: Sequence[dict], context: dict) -> dict:
    stats=context.get('stats') or {}
    rows=[]
    for item in items:
        s=stats.get(int(item.get('qindex',-1)))
        if s is not None:
            rows.append((s,max(1.0,float(item.get('count',s.pixel_count)))))
    if not rows:
        return {'coverage':0.0,'lightness':50.0,'importance':0.0,'protected':0.0,'edge':0.0,
                'tiles':np.zeros(int(context.get('grid_size',6))**2,dtype=np.float64),'roles':set(),'families':set()}
    total=sum(w for _s,w in rows) or 1.0
    tiles=sum((np.asarray(s.tile_weights,dtype=np.float64)*w for s,w in rows),np.zeros(len(rows[0][0].tile_weights),dtype=np.float64))/total
    return {
        # Coverage is the union mass of disjoint quantizer buckets. Averaging
        # it made any number of merged 3% buckets still look like a 3% detail.
        'coverage':sum(s.coverage for s,_w in rows),
        'lightness':sum(s.lightness*w for s,w in rows)/total,
        'importance':sum(s.importance*w for s,w in rows)/total,
        'protected':sum(s.protected_fraction*w for s,w in rows)/total,
        'edge':sum(s.edge_fraction*w for s,w in rows)/total,
        'tiles':tiles,
        'roles':{s.tone_role for s,_w in rows},
        'families':{s.hue_family for s,_w in rows if s.hue_family is not None},
    }


def _prepare_cluster_region(cluster, context: dict) -> tuple:
    """Prepare one ordered membership state for its owner's merge operation.

    The owner must invalidate this value after changing members. Nothing is
    cached on the caller's mutable cluster/context or in module-global state.
    """
    items = tuple(_members(cluster))
    return items, _weighted_stats(items, context)


def cluster_region_relation(a, b, context: dict | None, *, _prepared=None) -> dict:
    """Return merge affinity/protection signals for two quantized clusters."""
    if not context or not context.get('stats'):
        return {'texture_affinity':0.0,'adjacency':0.0,'spatial_overlap':0.0,
                'tone_conflict':False,'detail_conflict':False,'region_penalty':1.0}
    if _prepared is None:
        ai=_members(a); bi=_members(b)
        sa=_weighted_stats(ai,context); sb=_weighted_stats(bi,context)
    else:
        (ai,sa),(bi,sb)=_prepared
    ta=tb=None
    try:
        ta=np.asarray(sa['tiles'],dtype=np.float64); tb=np.asarray(sb['tiles'],dtype=np.float64)
        denom=sqrt(float(np.dot(ta,ta))*float(np.dot(tb,tb)))
        overlap=0.0 if denom<=1e-12 else max(0.0,min(1.0,float(np.dot(ta,tb)/denom)))
    finally:
        # Later relation errors must not keep aliases to the owner's arrays in
        # a retained traceback after that owner has cleared its prepared state.
        ta=tb=None
    adjacency_map=context.get('adjacency') or {}
    adj=0.0
    for x in ai:
        qi=int(x.get('qindex',-1))
        for y in bi:
            qj=int(y.get('qindex',-1))
            key=(min(qi,qj),max(qi,qj))
            adj=max(adj,float(adjacency_map.get(key,0.0)))
    same_family=bool(sa['families'] and sb['families'] and sa['families']&sb['families'])
    roles_a=sa['roles']; roles_b=sb['roles']
    tone_conflict=(('highlight' in roles_a and 'shadow' in roles_b) or ('shadow' in roles_a and 'highlight' in roles_b))
    if not tone_conflict and same_family and abs(float(sa['lightness'])-float(sb['lightness']))>=18.0:
        # Strong same-family lightness separation is intentional shading even if
        # one bucket landed just inside the broad midtone band.
        tone_conflict=True
    detail_a=(float(sa['coverage'])<=.04 and (float(sa['importance'])>=.30 or float(sa['protected'])>=.20))
    detail_b=(float(sb['coverage'])<=.04 and (float(sb['importance'])>=.30 or float(sb['protected'])>=.20))
    # Preserve an important small feature when the other side is materially
    # different.  Two adjacent high-detail shades may still merge when nearly
    # identical, which avoids protecting compression noise around an edge.
    detail_conflict=bool(detail_a or detail_b)
    low_detail=max(float(sa['importance']),float(sb['importance']))<.26 and max(float(sa['edge']),float(sb['edge']))<.22
    texture_affinity=(0.55*adj+0.45*overlap) if same_family and low_detail and not tone_conflict else 0.0
    texture_affinity=max(0.0,min(1.0,texture_affinity))
    penalty=1.0
    if same_family:
        penalty*=0.86
    penalty*=max(.58,1.0-.30*texture_affinity)
    if tone_conflict:
        penalty*=2.8
    if detail_conflict:
        penalty*=2.1
    if not same_family and overlap<.10 and adj<.04:
        penalty*=1.25
    return {
        'texture_affinity':texture_affinity,'adjacency':adj,'spatial_overlap':overlap,
        'tone_conflict':bool(tone_conflict),'detail_conflict':bool(detail_conflict),
        'region_penalty':float(penalty),'same_family':bool(same_family),
    }


def merge_threshold_multiplier(relation: dict) -> float:
    """Multiplier for the non-forced perceptual merge threshold."""
    mult=1.0+1.65*float(relation.get('texture_affinity',0.0))
    if relation.get('tone_conflict'):
        mult*=.24
    if relation.get('detail_conflict'):
        mult*=.36
    return max(.12,min(2.65,float(mult)))


def region_detail_anchor_candidates(groups, palette: Sequence[Sequence[int]], active: Sequence[int],
                                    weights: Sequence[float], cap: int, *, max_fraction: float=.16) -> list[int]:
    """Find a few local high-contrast colours worth retaining in reduced game palettes.

    This complements dominant hue/tone anchors.  It never allocates more than a
    small fraction of the palette cap and therefore cannot crowd out main hues.
    """
    if cap<=0 or not active:
        return []
    # 4x4 midpoint occupancy is intentionally cheap because this path can be
    # called several times while evaluating adaptive palette quality.
    from ColorSpatialSummary import midpoint_color_cells
    cells=midpoint_color_cells(groups,active,4,legacy_sqrt_mass=True)
    scores: dict[int,float]={}
    for row in cells.values():
        if len(row)<2:
            continue
        total=sum(row.values()) or 1.0
        main=max(row,key=lambda i:(row[i],weights[i],-i))
        for i,mass in row.items():
            if i==main or mass/total<.035:
                continue
            de=delta_e_oklab(palette[i],palette[main])
            if de<14.0:
                continue
            # Reward local contrast and enough cell presence, while not letting
            # globally dominant shades masquerade as "detail" anchors.
            global_frac=float(weights[i])/max(1.0,sum(weights[j] for j in active))
            score=de*(mass/total)*(1.0+max(0.0,.05-global_frac)*5.0)
            scores[i]=max(scores.get(i,0.0),score)
    budget=max(0,min(3,int(round(max(1,cap)*max_fraction))))
    ranked=sorted(scores,key=lambda i:(-scores[i],-weights[i],i))
    return ranked[:budget]
