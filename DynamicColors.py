"""Dynamic exact-color planning with perceptual color reduction.

Color Engine v3 groups nearly identical source colours perceptually, prioritises
them by coverage, and only spends exact custom-color selections when they make a
visible improvement over the nearest calibrated palette swatch.
"""
from __future__ import annotations
from contextlib import ExitStack, closing
from math import sqrt, ceil
from itertools import chain
import numpy as np
from ColorMatchingEngine import visible_rgb_image, measure_quantized_regions, _ColorSourceAnalysis
from ColorFidelity import delta_e2000, delta_e_oklab, mapping_pair_metrics, finalize_mapping_stats
from ExactColorEngine import candidate_cost
from DominantHuePreservation import dominant_hue_family, protected_hue_families, summarize_hue_families
from RegionAwareQuantization import (build_region_context, cluster_region_relation,
                                    merge_threshold_multiplier, _prepare_cluster_region)

EXACT_COLOR_LIMITS=("Auto","8","16","24","32")


def validate_exact_color_limit(value):
    text=str(value)
    if text not in EXACT_COLOR_LIMITS:
        raise ValueError(f'Unknown exact color limit: {value}')
    return text


def resolve_exact_color_limit(value, *, draw_quality='High likeness', preview=False):
    text=validate_exact_color_limit(value)
    if text!='Auto':
        return int(text)
    if preview:
        return 8
    quality=str(draw_quality)
    if quality=='Balanced':
        return 12
    if quality=='Maximum likeness':
        return 20
    if quality=='GPU enhanced':
        return 24
    if quality=='Pixel Accurate':
        return 32
    return 16


def _distance2(a,b):
    return sum((int(x)-int(y))**2 for x,y in zip(a[:3],b[:3]))


def _visible_white(rgb):
    r,g,b=map(int,rgb[:3]); hi=max(r,g,b); lo=min(r,g,b)
    return r>=245 and g>=245 and b>=245 and hi-lo<=12


def _rgb_to_space(rgb):
    r,g,b=[max(0,min(255,int(v)))/255.0 for v in rgb[:3]]
    def lin(c):
        return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
    lr,lg,lb=lin(r),lin(g),lin(b)
    y=0.2126*lr + 0.7152*lg + 0.0722*lb
    co=lr-lb
    cg=lg - (lr+lb)*0.5
    chroma=sqrt(co*co + cg*cg)
    return y,co,cg,chroma


def _perceptual_distance2(a,b):
    # Step 2: OKLab is now the canonical reduction/matching geometry. Keep the
    # legacy small squared scale so existing merge thresholds remain bounded.
    de=delta_e_oklab(tuple(a[:3]),tuple(b[:3]))
    return (de/100.0)**2


def _closest_palette_index(rgb,palette,fidelity='Faithful'):
    scored=[(candidate_cost(rgb,p,fidelity=fidelity),i) for i,p in enumerate(palette)]
    return min(scored,key=lambda item:(item[0],item[1]))


def _weighted_rgb(items):
    total=max(1,sum(int(it['count']) for it in items))
    r=round(sum(int(it['rgb'][0])*int(it['count']) for it in items)/total)
    g=round(sum(int(it['rgb'][1])*int(it['count']) for it in items)/total)
    b=round(sum(int(it['rgb'][2])*int(it['count']) for it in items)/total)
    return (int(r),int(g),int(b)), total


def _merge_quantized(entries,max_colors,cancelled=lambda:False, *, region_context=None, diagnostics=None):
    """Greedy OKLab merge with dominant-hue + Step-4 region protection.

    Step 4 uses spatial adjacency/local contrast to merge same-object texture
    shades sooner, while highlight/shadow roles and small important features are
    deliberately expensive to collapse.  The colour cap and renderer remain
    unchanged.
    """
    if not entries:
        return [],{}
    max_colors=max(1,int(max_colors))
    total_pixels=sum(e['count'] for e in entries) or 1
    entry_colors=[tuple(e['rgb']) for e in entries]
    entry_weights=[float(e['count']) for e in entries]
    protected=set(protected_hue_families(entry_colors,entry_weights,max_colors,fidelity='Faithful'))
    threshold2=0.0018  # perceptually very close after quantization
    clusters=[]
    prepared=[]
    item_prepared=None
    has_region_stats=bool(region_context and region_context.get('stats'))
    source_to_cluster={}
    diag=diagnostics if diagnostics is not None else {}
    diag.setdefault('region_texture_merges',0)
    diag.setdefault('region_tone_conflict_merges',0)
    diag.setdefault('region_protected_detail_merges',0)
    diag.setdefault('region_forced_merges',0)

    def family_of(rgb):
        return dominant_hue_family(rgb)

    def protected_members(cluster_or_item):
        items=(cluster_or_item.get('items') or []) if isinstance(cluster_or_item,dict) and 'items' in cluster_or_item else [cluster_or_item]
        out=set()
        for row in items:
            try: fam=family_of(row['rgb'])
            except Exception: fam=None
            if fam in protected: out.add(fam)
        return out

    def note_merge(relation, *, forced=False):
        if forced: diag['region_forced_merges']=int(diag.get('region_forced_merges',0))+1
        if float(relation.get('texture_affinity',0.0))>=.18:
            diag['region_texture_merges']=int(diag.get('region_texture_merges',0))+1
        if relation.get('tone_conflict'):
            diag['region_tone_conflict_merges']=int(diag.get('region_tone_conflict_merges',0))+1
        if relation.get('detail_conflict'):
            diag['region_protected_detail_merges']=int(diag.get('region_protected_detail_merges',0))+1

    def region_state(cluster,index):
        state=prepared[index]
        if state is None:
            state=prepared[index]=_prepare_cluster_region(cluster,region_context)
        return state

    # Cache only current cluster states; merged members are always
    # recomputed in their original order, never from averaged summaries.
    try:
        for item in sorted(entries,key=lambda e:e['count'],reverse=True):
            if cancelled():
                return None,None
            item_prepared=None
            item_family=family_of(item['rgb'])
            best_i=None; best_key=None; best_distance=None; best_relation=None
            for i,cl in enumerate(clusters):
                cl_family=family_of(cl['rgb'])
                # A protected hue may absorb shades from its own family, but never
                # disappear into another protected family during the early merge.
                item_protected={item_family} if item_family in protected else set()
                cl_protected=protected_members(cl)
                if item_protected and cl_protected and item_protected.isdisjoint(cl_protected):
                    continue
                if item_protected and cl_family not in (item_family,None):
                    continue
                if cl_protected and item_family is not None and item_family not in cl_protected:
                    continue
                d2=_perceptual_distance2(item['rgb'],cl['rgb'])
                if has_region_stats:
                    if item_prepared is None:
                        item_prepared=_prepare_cluster_region(item,region_context)
                    relation=cluster_region_relation(item,cl,region_context,
                        _prepared=(item_prepared,region_state(cl,i)))
                else:
                    relation=cluster_region_relation(item,cl,region_context)
                key=(d2*float(relation.get('region_penalty',1.0)),d2,i)
                if best_key is None or key<best_key:
                    best_key=key;best_i=i;best_distance=d2;best_relation=relation
            frac=item['count']/total_pixels
            local_threshold=threshold2*(1.0 + max(0.0,0.02-frac)*20.0)
            allowed=(local_threshold*merge_threshold_multiplier(best_relation or {}))
            if best_i is not None and best_distance is not None and best_distance<=allowed:
                clusters[best_i]['items'].append(item)
                prepared[best_i]=None
                rgb,count=_weighted_rgb(clusters[best_i]['items'])
                clusters[best_i]['rgb']=rgb; clusters[best_i]['count']=count
                source_to_cluster[item['qindex']]=best_i
                note_merge(best_relation or {},forced=False)
            else:
                source_to_cluster[item['qindex']]=len(clusters)
                clusters.append({'items':[item],'rgb':tuple(item['rgb']),'count':int(item['count'])})
                prepared.append(item_prepared)

        # If still over budget, merge same-object low-detail shades first.  Distinct
        # dominant hues, intentional tone roles and protected small details remain
        # progressively more expensive and are only collapsed if the hard cap leaves
        # no legal alternative.
        while len(clusters)>max_colors:
            if cancelled():
                return None,None
            family_counts={}
            for cl in clusters:
                fam=family_of(cl['rgb'])
                if fam is not None: family_counts[fam]=family_counts.get(fam,0)+1
            best_pair=None; best_key=None; best_relation=None
            for i in range(len(clusters)):
                for j in range(i+1,len(clusters)):
                    ci,cj=clusters[i],clusters[j]
                    fi,fj=family_of(ci['rgb']),family_of(cj['rgb'])
                    relation=(cluster_region_relation(ci,cj,region_context,
                        _prepared=(region_state(ci,i),region_state(cj,j))) if has_region_stats
                        else cluster_region_relation(ci,cj,region_context))
                    texture=float(relation.get('texture_affinity',0.0))
                    pi,pj=protected_members(ci),protected_members(cj)
                    # Protected *source* families outrank the current weighted RGB.
                    # This prevents a forced merge from averaging green into yellow
                    # and silently defeating Step 3's one-slot-per-main-hue promise.
                    if pi and pj and pi!=pj:
                        tier=9
                    elif pi or pj:
                        protected_set=pi or pj
                        other_family=fj if pi else fi
                        if other_family in protected_set:
                            tier=0 if texture>=.18 and not relation.get('tone_conflict') else 1
                        else:
                            tier=5
                    elif fi==fj:
                        tier=0 if texture>=.18 and not relation.get('tone_conflict') and not relation.get('detail_conflict') else 1
                    else:
                        tier=2
                    # Detail/tone protection matters *inside* the hue-protection
                    # tier, but can never make two different protected hue families
                    # cheaper than disposable texture shades.
                    if tier<5 and relation.get('tone_conflict'): tier+=2
                    if tier<5 and relation.get('detail_conflict'): tier+=2
                    d2=_perceptual_distance2(ci['rgb'],cj['rgb'])
                    coverage=(ci['count']+cj['count'])/total_pixels
                    regional=float(relation.get('region_penalty',1.0))
                    key=(tier,d2*coverage*regional,d2*regional,-texture,i,j)
                    if best_key is None or key<best_key:
                        best_key=key;best_pair=(i,j);best_relation=relation
            if best_pair is None:
                break
            i,j=best_pair
            merged={'items':clusters[i]['items']+clusters[j]['items']}
            rgb,count=_weighted_rgb(merged['items']); merged['rgb']=rgb; merged['count']=count
            clusters[i]=merged;clusters.pop(j)
            prepared[i]=None;prepared.pop(j)
            note_merge(best_relation or {},forced=True)
            for src,cidx in list(source_to_cluster.items()):
                if cidx==j: source_to_cluster[src]=i
                elif cidx>j: source_to_cluster[src]=cidx-1

    finally:
        # Tracebacks may retain the private prepared pair passed to a relation.
        # Drop its arrays as well as the operation's list of snapshots.
        for state in prepared:
            if state is not None:
                state[1].clear()
        if item_prepared is not None:
            item_prepared[1].clear()
        prepared.clear()
        item_prepared=None

    if region_context:
        diag.update(dict(region_context.get('diagnostics') or {}))
    return clusters,source_to_cluster


def _add_run(groups,index,start,y,end_x):
    if index is None or start is None or end_x<start:return
    groups[index].append((int(start),int(y),int(end_x),int(y)))


def _drawable_source(image, source_data, skip_white):
    """Keep source skip decisions independent of quantizer/merged colors."""
    pixels=None
    try:
        pixels=source_data.rgb_for(image)
        drawable=np.ones(pixels.shape[:2],dtype=bool)
        if any(band in ('A','a') for band in image.getbands()) or 'transparency' in image.info:
            drawable=source_data.alpha>0
        white=np.all(pixels>=245,axis=2)&drawable if skip_white else np.zeros_like(drawable)
        drawable &= ~white
        return pixels,drawable,int(np.count_nonzero(white))
    finally:
        pixels=None


def _quantize_drawable(source,pixels,drawable,temp_colors):
    """Train only on drawable colors; ignored white cannot consume the budget."""
    try:
        from PIL import Image
        if np.all(drawable):
            quantized=source.quantize(colors=temp_colors,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
            try:
                return quantized,{int(index):int(count) for count,index in (quantized.getcolors() or [])}
            except BaseException:
                quantized.close()
                raise
        # The compact one-row image contains no padded/background samples. Its
        # labels are put back into the source geometry after quantization.
        with closing(Image.fromarray(pixels[drawable].reshape(1,-1,3))) as samples:
            with closing(samples.quantize(colors=temp_colors,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)) as quantized:
                counts={int(index):int(count) for count,index in (quantized.getcolors() or [])}
                labels=np.zeros(drawable.shape,dtype=np.uint8)
                labels[drawable]=np.asarray(quantized,dtype=np.uint8).reshape(-1)
        return Image.fromarray(labels),counts
    finally:
        pixels=None


def _groups_from_labels(labels,drawable,group_by_label,group_count,lines,cancelled):
    """Build deterministic horizontal runs without a Python visit per pixel."""
    groups=[[] for _ in range(group_count)]
    lookup=np.full(256,-1,dtype=np.int32)
    for label,index in group_by_label.items():lookup[int(label)]=int(index)
    labels=np.asarray(labels,dtype=np.uint8)
    for y in range(labels.shape[0]):
        if cancelled():return None
        row=lookup[labels[y]]
        row[~drawable[y]]=-1
        if not lines:
            for x in np.flatnonzero(row>=0):
                groups[int(row[x])].append((int(x),y,int(x),y))
            continue
        boundaries=np.flatnonzero(row[1:]!=row[:-1])+1
        start=0
        for end in chain(boundaries,(len(row),)):
            index=int(row[start])
            if index>=0:groups[index].append((start,y,int(end)-1,y))
            start=int(end)
    return groups


def _coalesce_color_actions(rendered,selectors,coverages):
    """Share one phase when source clusters resolve to the same runtime action."""
    colors=[];actions=[];mass=[];remap={};seen={}
    for index,(rgb,selector,coverage) in enumerate(zip(rendered,selectors,coverages)):
        kind=selector['kind']
        key=(kind,tuple(rgb),selector.get('palette_index'),selector.get('fallback_palette_index'),
             bool(selector.get('require_exact')),bool(selector.get('prefer_numeric')))
        target=seen.get(key)
        if target is None:
            target=len(colors);seen[key]=target
            colors.append(tuple(rgb));actions.append(selector);mass.append(0.0)
        mass[target]+=coverage;remap[index]=target
    return colors,actions,mass,remap


def _custom_color_policy(max_colors, color_fidelity='Faithful', profile_name='', exact_threshold=2.5):
    """Return bounded exact-RGB policy for the current profile/fidelity.

    Paint can reproduce arbitrary RGB after calibration, so Faithful/Exact modes
    should spend more custom-color selections than browser-game profiles.  The
    policy remains bounded to avoid turning every tiny source variation into a
    modal Edit Colors operation.
    """
    limit=max(1,int(max_colors)); fidelity=str(color_fidelity or 'Faithful'); paint=str(profile_name or '')=='Microsoft Paint'
    if paint and fidelity=='Exact':
        return limit, min(float(exact_threshold),0.9), 0.0
    if paint and fidelity=='Faithful':
        budget=min(limit,max(8,int(ceil(limit*0.85))))
        return budget, min(float(exact_threshold),1.6), 0.5
    if paint and fidelity=='Balanced':
        budget=min(limit,max(6,int(ceil(limit*0.65))))
        return budget, min(float(exact_threshold),2.2), 1.0
    budget=min(limit,max(1,min(12,limit//2+1)))
    return budget,float(exact_threshold),2.0


def build_dynamic_color_strokes(image, palette_rgb, *, max_colors=16, skip_white=True,
                                lines=True, exact_available=False, exact_threshold=2.5, color_fidelity='Faithful',
                                profile_name='', protected_mask=None, cancelled=lambda:False, source_palette=False,
                                _palette_only=False):
    """Return groups, rendered colors, selectors and metadata.

    selectors are dictionaries of either:
      {kind:'palette', palette_index:N, rgb:(...)}
      {kind:'custom', rgb:(...), fallback_palette_index:N}

    The palette RGB values passed here are the RGB values measured during the
    user's calibration. No profile preset RGB is preferred over calibrated data.

    Color Engine v3:
    - quantizes to a bounded intermediate palette;
    - merges nearly identical colours perceptually;
    - prioritises colours by coverage;
    - uses exact custom colours only when the nearest calibrated palette would
      be visibly worse.
    """
    palette=tuple(tuple(map(int,c[:3])) for c in palette_rgb)
    if not palette:
        raise ValueError('No calibrated palette colors are available for fallback.')
    if cancelled():
        return None,None,None,None
    with ExitStack() as stack:
        # v1.0.109: measure the pixels the user actually sees (including alpha)
        # instead of trusting only the quantizer's generated palette RGB.
        source_data=stack.enter_context(_ColorSourceAnalysis(image,visible_factory=visible_rgb_image))
        max_colors=max(1,int(max_colors))
        source_pixels=None
        try:
            source_pixels,drawable,skipped_white=_drawable_source(image,source_data,skip_white)
            if cancelled():
                return None,None,None,None
            if not np.any(drawable):
                return [],(),(),{'mode':'dynamic-exact-v4','requested_colors':max_colors,'active_colors':0,
                                 'custom_exact_colors':0,'palette_fallback_colors':0,'white_skipped':skipped_white,
                                 'exact_available':bool(exact_available),
                                 'color_fidelity_diagnostics':finalize_mapping_stats({'mapped_pixels':0})}
            # Slightly higher temporary palette gives the reducer something to merge.
            temp_colors=max(8,min(64,max_colors*3))
            q,counts=_quantize_drawable(source_data.visible,source_pixels,drawable,temp_colors)
            stack.callback(q.close)
            source_data.release_visible()
        finally:
            source_pixels=None
        if cancelled():return None,None,None,None
        # Measure all original pixels belonging to every quantized region.  This
        # provides mean/median/dominant RGB plus a robust source-backed target RGB.
        source_stats=measure_quantized_regions(image,q,drawable_mask=drawable,_source_data=source_data)
        source_data.alpha=None
        entries=[]
        for qindex,count in counts.items():
            if cancelled():
                return None,None,None,None
            sample=source_stats.get(int(qindex))
            if sample is None or count<=0:
                continue
            entries.append({'qindex':int(qindex),'rgb':tuple(sample.rgb),'count':int(count),
                            'source_mean_rgb':tuple(sample.mean_rgb),'source_median_rgb':tuple(sample.median_rgb),
                            'source_dominant_rgb':tuple(sample.dominant_rgb),'source_dominant_fraction':float(sample.dominant_fraction),
                            'source_spread':float(sample.spread),'source_alpha_mean':float(sample.alpha_mean),
                            'source_alpha_median':float(sample.alpha_median)})
        if not entries:
            return [],(),(),{'mode':'dynamic-exact-v4','requested_colors':max_colors,'active_colors':0,
                             'custom_exact_colors':0,'palette_fallback_colors':0,'white_skipped':0,'exact_available':bool(exact_available)}
        _source_hue_summaries=summarize_hue_families(
            [e['rgb'] for e in entries],[float(e['count']) for e in entries],
            fidelity=str(color_fidelity or 'Faithful'),max_families=max_colors)
        # Step 4: build one compact spatial/structural analysis from the temporary
        # quantizer labels. The AdaptiveDetail protected mask is reused when present;
        # no second semantic/renderer pass is introduced.
        region_context=build_region_context(image,q,entries,protected_mask=protected_mask,
            cancelled=cancelled,drawable_mask=drawable,_source_data=source_data)
        source_data.close()
        if _palette_only:q.close()
        region_quant_meta={}
        clusters,source_to_cluster=_merge_quantized(
            entries,max_colors,cancelled=cancelled,region_context=region_context,diagnostics=region_quant_meta)
        if clusters is None:
            return None,None,None,None
        # Sort by coverage so large visual colours receive priority first.
        order=sorted(range(len(clusters)), key=lambda i:(-clusters[i]['count'], i))
        old_to_new={old:new for new,old in enumerate(order)}
        selected=[]
        total_pixels=sum(c['count'] for c in clusters) or 1
        for old in order:
            if cancelled():return None,None,None,None
            c=clusters[old]
            pal_d2,pal_idx=_closest_palette_index(c['rgb'],palette,color_fidelity)
            # Preserve source measurements for diagnostics and exact RGB entry.
            # Merged clusters use the weighted robust RGB, while the largest source
            # bucket supplies median/dominant diagnostics for the UI/logs.
            primary=max(c.get('items') or [{}],key=lambda item:int(item.get('count',0)))
            selected.append({
                'rgb':tuple(c['rgb']),
                'count':int(c['count']),
                'coverage':c['count']/total_pixels,
                'fallback_palette_index':int(pal_idx),
                'palette_distance':float(delta_e2000(c['rgb'],palette[pal_idx])),
                'palette_distance_oklab':float(delta_e_oklab(c['rgb'],palette[pal_idx])),
                'mean_rgb':tuple(primary.get('source_mean_rgb',c['rgb'])),
                'median_rgb':tuple(primary.get('source_median_rgb',c['rgb'])),
                'dominant_rgb':tuple(primary.get('source_dominant_rgb',c['rgb'])),
                'dominant_fraction':float(primary.get('source_dominant_fraction',0.0)),
                'spread':float(primary.get('source_spread',0.0)),
                'alpha_mean':float(primary.get('source_alpha_mean',255.0)),
                'alpha_median':float(primary.get('source_alpha_median',255.0)),
                'hue_family':dominant_hue_family(c['rgb']),
            })
        # Decide where exact custom colours are actually worth using.
        selectors=[None]*len(selected)
        rendered=[None]*len(selected)
        groups=[[] for _ in selected]
        # v1.0.124: Paint Faithful/Exact can reproduce arbitrary RGB after the
        # exact-color controls are calibrated. Spend more of the bounded color plan
        # on real custom RGB rather than accepting a visibly poor 20-swatch palette
        # approximation. Browser/game profiles keep the older conservative budget.
        custom_budget,custom_threshold,tiny_region_penalty=_custom_color_policy(
            max_colors,color_fidelity=color_fidelity,profile_name=profile_name,exact_threshold=exact_threshold)
        custom_budget=min(len(selected),int(custom_budget))
        ranked_custom=sorted(
            range(len(selected)),
            key=lambda i:(selected[i]['palette_distance']*(1.0+selected[i]['coverage']*3.0),
                          selected[i]['coverage'], -i),
            reverse=True
        )
        if source_palette and exact_available:
            custom_budget=len(selected)
        use_custom=set(range(len(selected))) if source_palette and exact_available else set()
        if exact_available and not source_palette:
            for i in ranked_custom:
                item=selected[i]
                # Require visible improvement over palette. Tiny regions need an even
                # larger miss before they deserve a modal custom-colour selection.
                needed=float(custom_threshold) + (float(tiny_region_penalty) if item['coverage'] < 0.01 else 0.0)
                if item['palette_distance'] >= needed and len(use_custom) < custom_budget:
                    use_custom.add(i)
        for i,item in enumerate(selected):
            if cancelled():return None,None,None,None
            fallback=int(item['fallback_palette_index'])
            if exact_available and i in use_custom:
                selectors[i]={'kind':'custom','rgb':tuple(item['rgb']),'fallback_palette_index':fallback,
                              'prefer_numeric':True,'source_rgb':tuple(item['rgb']),
                              'source_mean_rgb':tuple(item['mean_rgb']),'source_median_rgb':tuple(item['median_rgb']),
                              'source_dominant_rgb':tuple(item['dominant_rgb']),
                              'source_dominant_fraction':float(item['dominant_fraction']),'source_spread':float(item['spread']),
                              'source_alpha_mean':float(item['alpha_mean']),'source_alpha_median':float(item['alpha_median'])}
                rendered[i]=tuple(item['rgb'])
            else:
                selectors[i]={'kind':'palette','palette_index':fallback,'rgb':tuple(palette[fallback])}
                rendered[i]=tuple(palette[fallback])
        source_rendered=tuple(rendered)
        rendered,selectors,coverage_priority,action_indexes=_coalesce_color_actions(
            rendered,selectors,[item['coverage'] for item in selected])
        final_group_by_q={int(src_index):action_indexes[old_to_new[old_cluster]] for src_index,old_cluster in source_to_cluster.items()}
        groups=None if _palette_only else _groups_from_labels(q,drawable,final_group_by_q,len(rendered),lines,cancelled)
        q.close()
        if not _palette_only and groups is None:return None,None,None,None
        active=len(rendered)
        fidelity_stats={
            'mapped_pixels':0,'source_lightness_sum':0.0,'mapped_lightness_sum':0.0,
            'source_saturation_sum':0.0,'mapped_saturation_sum':0.0,
            'source_luminance_sum':0.0,'mapped_luminance_sum':0.0,
            'delta_e_sum':0.0,'delta_e_max':0.0,'delta_e2000_sum':0.0,'delta_e2000_max':0.0,
            'delta_e_oklab_sum':0.0,'delta_e_oklab_max':0.0,'hue_error_sum':0.0,
        }
        for item,mapped in zip(selected,source_rendered):
            if cancelled():return None,None,None,None
            n=max(0,int(item.get('count',0)));pair=mapping_pair_metrics(item['rgb'],mapped)
            fidelity_stats['mapped_pixels']+=n
            fidelity_stats['source_lightness_sum']+=pair['source_lightness']*n;fidelity_stats['mapped_lightness_sum']+=pair['mapped_lightness']*n
            fidelity_stats['source_saturation_sum']+=pair['source_saturation']*n;fidelity_stats['mapped_saturation_sum']+=pair['mapped_saturation']*n
            fidelity_stats['source_luminance_sum']+=pair['source_luminance']*n;fidelity_stats['mapped_luminance_sum']+=pair['mapped_luminance']*n
            fidelity_stats['delta_e_sum']+=pair['delta_e76']*n;fidelity_stats['delta_e_max']=max(fidelity_stats['delta_e_max'],pair['delta_e76'])
            fidelity_stats['delta_e2000_sum']+=pair['delta_e2000']*n;fidelity_stats['delta_e2000_max']=max(fidelity_stats['delta_e2000_max'],pair['delta_e2000'])
            fidelity_stats['delta_e_oklab_sum']+=pair['delta_e_oklab']*n;fidelity_stats['delta_e_oklab_max']=max(fidelity_stats['delta_e_oklab_max'],pair['delta_e_oklab'])
            fidelity_stats['hue_error_sum']+=pair.get('hue_error',0.0)*n
        color_diag=finalize_mapping_stats(fidelity_stats)
        # Human-readable names are diagnostics only. They never enter candidate
        # selection or palette reduction, so rendering remains purely RGB/OKLab.
        try:
            from NamedColorIntelligence import describe_color_mapping
            named_color_mappings=tuple(
                dict(describe_color_mapping(item['rgb'],mapped),coverage=round(float(item.get('coverage',0.0)),4))
                for item,mapped in list(zip(selected,source_rendered))[:12])
        except Exception:
            named_color_mappings=()
        if cancelled():return None,None,None,None
        return groups,tuple(rendered),tuple(selectors),{
            'mode':'dynamic-exact-v4',
            'color_rendering':'Perceptual match',
            'color_fidelity':str(color_fidelity),
            'color_fidelity_diagnostics':color_diag,
            'named_color_intelligence':True,
            'named_color_mappings':named_color_mappings,
            'requested_colors':max_colors,
            'intermediate_quantized_colors':len(entries),
            'reduced_colors':len(rendered),
            'source_reduced_colors':len(selected),
            'color_actions_coalesced':len(selected)-len(rendered),
            'active_colors':active,
            'custom_exact_colors':sum(s['kind']=='custom' for s in selectors),
            'palette_fallback_colors':sum(s['kind']=='palette' for s in selectors),
            'white_skipped':skipped_white,
            'exact_available':bool(exact_available),
            'custom_dialog_budget':custom_budget,
            'custom_color_threshold_deltae2000':round(float(custom_threshold),3),
            'custom_color_profile_policy':'paint-faithful-expanded' if str(profile_name or '')=='Microsoft Paint' and str(color_fidelity) in ('Faithful','Exact') else 'bounded-default',
            'coverage_priority':tuple(round(value,4) for value in coverage_priority),
            'dominant_hue_preservation':bool(_source_hue_summaries),
            'dominant_hue_families':tuple(s.family for s in _source_hue_summaries),
            'dominant_hue_coverage':{s.family:round(float(s.coverage),5) for s in _source_hue_summaries},
            'selected_hue_families':tuple(dict.fromkeys(item['hue_family'] for item in selected if item.get('hue_family'))),
            'region_aware_quantization':True,
            'region_quantization':dict(region_quant_meta),
            'average_palette_distance': round(sum(item['palette_distance'] for item in selected)/max(1,len(selected)),3),
            'source_color_measurement':'mean + median + dominant + source-backed robust RGB + OKLab palette geometry',
            'sampled_source_colors':tuple({
                'rgb':tuple(item['rgb']),'mean':tuple(item['mean_rgb']),'median':tuple(item['median_rgb']),
                'dominant':tuple(item['dominant_rgb']),'dominant_fraction':round(float(item['dominant_fraction']),3),
                'spread':round(float(item['spread']),2),'coverage':round(float(item['coverage']),4)
            } for item in selected[:12]),
        }


def build_dynamic_color_palette(image,palette_rgb,**options):
    """Use the same source analysis without allocating unused drawing strokes."""
    _groups,colors,selectors,metadata=build_dynamic_color_strokes(
        image,palette_rgb,**options,_palette_only=True)
    return colors,selectors,metadata
