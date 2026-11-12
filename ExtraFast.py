"""Extra Fast 2.0 safe region selector.

Candidates have already passed Image Draw Bot's connected-component/closed-contour
safety checks. This layer decides whether outline+Fill is actually cheaper than
keeping the same region as connected scanlines. Fill/restore controls are charged
once per colour batch, never once per region plus once again for the batch.
"""
from collections import defaultdict
import math
from Precision import CanvasTransform,precision_path_count
from SpeedOptimizer import phase_delay,estimated_motion_seconds


def _legacy_cost(region, transform, options, cancelled=lambda:False):
    delay=float(options.get('delay',.01));speed=options.get('speed','Balanced')
    precision=options.get('precision','High');step=options.get('stroke_step_px',8)
    contour=list(region.get('contour') or ())
    moves=0
    for a,b in zip(contour,contour[1:]):
        if cancelled():raise InterruptedError()
        moves+=precision_path_count(transform.point(*a),transform.point(*b),precision,step)
    # Tool switches are excluded here. They are paid once per same-colour batch.
    fill_core=moves*max(.004,phase_delay(delay,speed,'path')) + .24
    spans=region.get('row_spans') or ()
    scan_moves=0
    for y,x0,x1 in spans:
        if cancelled():raise InterruptedError()
        scan_moves+=precision_path_count(transform.point(x0,y),transform.point(x1,y),precision,step)
    scan_cost=estimated_motion_seconds(scan_moves,len(spans),0,delay,speed)
    return scan_cost,fill_core


def _finite_cost(value, fallback=None):
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return fallback
    return value if math.isfinite(value) and value>0 else fallback


def select_fast_regions(regions,source_size,target_size,options,cancelled=lambda:False):
    transform=CanvasTransform(*source_size,target_size)
    by_color=defaultdict(list);rejected=0;model_costs=False
    for region in regions:
        if cancelled():raise InterruptedError()
        contour=list(region.get('contour') or ())
        if len(contour)<4 or contour[0]!=contour[-1]:
            rejected+=1;continue

        scan_cost=_finite_cost(region.get('stroke_cost_seconds'))
        total_fill=_finite_cost(region.get('fill_cost_seconds'))
        fill_core=_finite_cost(region.get('fill_core_cost_seconds'))
        removed_batchable=0.0
        if fill_core is None and total_fill is not None:
            # Backward compatibility: legacy/external region metadata defines
            # fill_cost_seconds as its authoritative core cost. Only the new
            # RegionFill contract may explicitly identify an already embedded,
            # shareable per-region switch cost.
            explicit=_finite_cost(region.get('fill_batchable_overhead_seconds'))
            if explicit is None:
                fill_core=total_fill
            else:
                removed_batchable=max(0.0,min(float(explicit),total_fill))
                fill_core=max(.001,total_fill-removed_batchable)
        elif fill_core is not None and total_fill is not None:
            removed_batchable=max(0.0,total_fill-fill_core)
        if scan_cost is None or fill_core is None:
            scan_cost,fill_core=_legacy_cost(region,transform,options,cancelled)
            total_fill=fill_core
            removed_batchable=0.0

        # Only the non-shareable Fill cost is compared here. Shared Fill/restore
        # UI actions are evaluated once after regions are grouped by colour.
        if fill_core>=scan_cost*.985:
            rejected+=1;continue
        item=dict(region)
        item['extra_fast_strategy']='OUTLINE_FILL'
        item['extra_fast_scanline_cost_seconds']=round(scan_cost,5)
        item['extra_fast_fill_core_cost_seconds']=round(fill_core,5)
        item['extra_fast_fill_cost_seconds']=round(total_fill if total_fill is not None else fill_core,5)
        item['extra_fast_removed_batchable_overhead_seconds']=round(removed_batchable,5)
        try:key=int(item.get('color_index',-1))
        except (TypeError,ValueError):key=-1
        by_color[key].append(item)
        model_costs|=('fill_core_cost_seconds' in region or
                      'fill_batchable_overhead_seconds' in region)

    if model_costs:
        from RegionFillEngine import fill_tool_batch_cost
        batch_overhead=fill_tool_batch_cost(options)
    else:
        # External legacy candidates declare their own cost semantics. Keep
        # their explicit UI-delay override; real RegionFill candidates share
        # the same calibrated transition model as their scanline comparison.
        ui_actions=len(options.get('fill_tool_actions') or ())+len(options.get('fill_restore_actions') or ())
        if ui_actions==0 and options.get('fill_tool_available'):ui_actions=2
        try:ui_delay=float(options.get('ui_control_delay',.22))
        except (TypeError,ValueError,OverflowError):ui_delay=.22
        if not math.isfinite(ui_delay) or ui_delay<0:ui_delay=.22
        batch_overhead=max(0.,ui_actions*ui_delay)

    accepted=[];seconds=0.;saved=0.;batch_rejected=0
    for color,items in sorted(by_color.items(),key=lambda kv:kv[0]):
        if cancelled():raise InterruptedError()
        batch_scan=sum(float(r['extra_fast_scanline_cost_seconds']) for r in items)
        batch_fill=sum(float(r['extra_fast_fill_core_cost_seconds']) for r in items)+batch_overhead
        if batch_fill>=batch_scan*.96:
            rejected+=len(items);batch_rejected+=len(items);continue
        for item in items:
            item['extra_fast_batch_overhead_seconds']=round(batch_overhead/max(1,len(items)),5)
            item['extra_fast_region_saving_seconds']=round(
                max(0.,float(item['extra_fast_scanline_cost_seconds'])-
                    float(item['extra_fast_fill_core_cost_seconds'])-
                    batch_overhead/max(1,len(items))),5)
        accepted.extend(items);seconds+=batch_fill;saved+=batch_scan-batch_fill

    pixels=sum(max(0,int(r.get('area_pixels',0) or 0)) for r in accepted)
    return accepted,{
        'engine':'Extra Fast 2.0 outline/fill selector',
        'accepted_regions':len(accepted),'cost_rejected_regions':rejected,
        'batch_rejected_regions':batch_rejected,
        'fill_color_batches':len({int(r.get('color_index',-1)) for r in accepted}),
        'fill_pixels':pixels,'fill_estimated_seconds':round(seconds,3),
        'estimated_seconds_saved_vs_scanlines':round(saved,3),
        'fallback_strategy':'connected serpentine scanlines',
        'tool_switch_cost_model':('calibrated actual controls shared once per color batch' if model_costs else
            'legacy explicit UI delay shared once per color batch'),
        'per_region_tool_switch_double_charge':False,
        'legacy_fill_cost_semantics_preserved':True,
    }
