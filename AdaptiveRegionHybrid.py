"""Adaptive Region Hybrid 4.0 for Image Draw Bot v1.0.132-beta.

This is a planning/orchestration layer, not a second native-input engine. It
reuses Image Draw Bot's proven color pipeline, exact component topology, Fill
detector, profile calibration, preview and single guarded mouse executor.

For each exact colour component it evaluates safe horizontal/vertical connected
run plans (and verified multi-brush interior plans when the target exposes real
brush-size controls), using calibrated *time* rather than stroke count. Native
Fill remains optional and is accepted only after RegionFillEngine plus the
stateful contour/flood simulator agree. Under a deadline, components are
scheduled by simulated visual gain per millisecond with coarse spatial seeding
so a recognisable whole appears before optional detail.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from contextlib import closing
import time
import math
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image, ImageDraw

from AdaptiveBrushEngine import verified_brush_sizes
from ExecutionCostModel import build_cost_model
from PixelAccuratePlanner import PixelMap, validated_pixel_indices
from PixelMapValidation import validate_color_index, validate_palette_count
from RasterGeometry import clipped_bresenham, clipped_interpolated_line, nearest_axis_samples, project_pixel_interval
from ColorMatchingEngine import visible_rgb_image
from PixelStrokeEngine import connected_components
from StatefulFillSimulation import filter_stateful_fill_regions

ADAPTIVE_HYBRID_RENDER_STYLE = "Adaptive Hybrid 4.0"
ADAPTIVE_HYBRID_VERSION = "4.0"
PHASES = ("foundation", "structure", "detail", "correction")


@dataclass
class RegionChoice:
    component_id: int
    color_index: int
    method: str
    phase: str
    area: int
    importance: float
    edge: float
    protected_pixels: int
    estimated_seconds: float
    visual_gain: float
    gain_per_ms: float
    paths: int
    brush_px: int
    exact: bool
    reason: str

    def as_dict(self):
        out=asdict(self)
        for key,value in tuple(out.items()):
            if isinstance(value,float):out[key]=round(value,6)
        return out


def is_adaptive_hybrid(options: dict[str, Any]) -> bool:
    return (str(options.get("render_style") or "") == ADAPTIVE_HYBRID_RENDER_STYLE
            and not bool(options.get("_adaptive_hybrid_inner")))


def _cancel(cancelled):
    if cancelled():raise InterruptedError()


def _raster_line(index: np.ndarray, color: int, stroke, *, cancelled=lambda: False) -> None:
    h,w=index.shape
    try:x0,y0,x1,y1=map(int,stroke)
    except Exception:return
    if y0==y1:
        if 0<=y0<h:
            a,b=sorted((x0,x1));a=max(0,a);b=min(w-1,b)
            if a<=b:index[y0,a:b+1]=color
        return
    if x0==x1:
        if 0<=x0<w:
            a,b=sorted((y0,y1));a=max(0,a);b=min(h-1,b)
            if a<=b:index[a:b+1,x0]=color
        return
    for point_number,(x,y) in enumerate(clipped_bresenham((x0,y0),(x1,y1),w,h)):
        if point_number%256==0:_cancel(cancelled)
        index[y,x]=color


def pixel_map_from_groups(image: Image.Image, groups, palette_rgb: Sequence[Sequence[int]], *,
                          gpu_mode: str = "Auto", cancelled=lambda: False) -> PixelMap:
    """Reconstruct the exact quantized target raster from already-built groups."""
    _cancel(cancelled)
    palette_count=validate_palette_count(len(palette_rgb))
    w,h=map(int,image.size)
    index=np.full((h,w),-1,dtype=np.int16)
    for ci,strokes in enumerate(groups or ()):
        if strokes:validate_color_index(ci,palette_count=palette_count)
        for n,stroke in enumerate(strokes or ()):
            if n%512==0:_cancel(cancelled)
            _raster_line(index,ci,stroke,cancelled=cancelled)
    drawable=index>=0
    palette=np.asarray([tuple(map(int,c[:3])) for c in palette_rgb],dtype=np.uint8)
    rgb=np.full((h,w,3),255,dtype=np.uint8)
    if len(palette):
        rgb[drawable]=palette[index[drawable]]

    edge=np.zeros((h,w),dtype=np.float32)
    if w>1:
        diff=(index[:,1:]!=index[:,:-1]) & (drawable[:,1:]|drawable[:,:-1])
        edge[:,1:]=np.maximum(edge[:,1:],diff)
        edge[:,:-1]=np.maximum(edge[:,:-1],diff)
    if h>1:
        diff=(index[1:,:]!=index[:-1,:]) & (drawable[1:,:]|drawable[:-1,:])
        edge[1:,:]=np.maximum(edge[1:,:],diff)
        edge[:-1,:]=np.maximum(edge[:-1,:],diff)

    source_edge=np.zeros_like(edge)
    route_meta={}
    try:
        from UniversalGpuAcceleration import edge_magnitude
        with closing(visible_rgb_image(image)) as source_rgb:
            visible=np.asarray(source_rgb,dtype=np.float32)
        lum=(visible[...,0]*.2126+visible[...,1]*.7152+visible[...,2]*.0722)/255.0
        source_edge,route=edge_magnitude(lum,gpu_mode=gpu_mode,cancelled=cancelled)
        source_edge=np.asarray(source_edge,dtype=np.float32)
        if source_edge.shape!=edge.shape:source_edge=np.zeros_like(edge)
        source_edge=np.clip(source_edge/max(.001,float(np.percentile(source_edge,95)) if source_edge.size else 1.0),0,1)
        route_meta=route if isinstance(route,dict) else getattr(route,"as_dict",lambda:{})()
    except InterruptedError:
        raise
    except Exception:
        pass
    _cancel(cancelled)
    edge=np.maximum(edge,source_edge*.72).astype(np.float32,copy=False)

    neighbours=np.zeros((h,w),dtype=np.uint8)
    neighbours[1:,:]+=drawable[:-1,:];neighbours[:-1,:]+=drawable[1:,:]
    neighbours[:,1:]+=drawable[:,:-1];neighbours[:,:-1]+=drawable[:,1:]
    micro=drawable & ((neighbours<=2)|(edge>=.78))
    importance=np.where(drawable,.18,0.0).astype(np.float32)
    importance += edge*.58
    importance += micro.astype(np.float32)*.24
    importance=np.clip(importance,0,1)
    protected=drawable & ((edge>=.62)|micro)
    return PixelMap(w,h,rgb,index,drawable,edge,importance,protected,{
        "engine":"Adaptive Region Hybrid target raster","source":"existing quantized groups",
        "gpu_edge_route":route_meta,"drawable_pixels":int(np.count_nonzero(drawable)),
    },contour_map=edge,micro_detail_map=micro.astype(np.float32))


def _individual_paths(runs):
    out=[]
    for x0,y0,x1,y1 in runs:
        out.append(((int(x0),int(y0)),) if (x0,y0)==(x1,y1) else ((int(x0),int(y0)),(int(x1),int(y1))))
    return out


def _orientation_paths(comp, orientation: str, component_map: np.ndarray, cancelled=lambda: False):
    """Reuse PixelStrokeEngine's verified lossless merger for one forced orientation."""
    from PixelStrokeEngine import (
        _merge_horizontal_runs_lossless, _transpose_segments, _transpose_paths,
        _path_inside_component, _paths_exact_component_coverage,
    )
    runs=comp.horizontal_runs if orientation=="horizontal" else comp.vertical_runs
    if orientation=="horizontal":
        paths=_merge_horizontal_runs_lossless(runs,cancelled=cancelled)
    else:
        paths=_transpose_paths(_merge_horizontal_runs_lossless(_transpose_segments(runs),cancelled=cancelled))
    exact=all(_path_inside_component(p,component_map,comp.component_id) for p in paths)
    exact=exact and _paths_exact_component_coverage(paths,component_map,comp)
    if not exact:
        paths=_individual_paths(runs)
        exact=all(_path_inside_component(p,component_map,comp.component_id) for p in paths)
        exact=exact and _paths_exact_component_coverage(paths,component_map,comp)
    return list(paths),bool(exact)


def _phase(comp,total_drawable:int) -> str:
    ratio=comp.area/max(1,total_drawable)
    if ratio>=.015 and comp.edge_mean<.42 and comp.protected_ratio<.10:return "foundation"
    if comp.contour_mean>=.48 or comp.edge_mean>=.52 or comp.importance_mean>=.52:return "structure"
    if comp.protected_pixels or comp.area<=24:return "detail"
    return "structure" if comp.importance_mean>=.38 else "correction"


def _component_gain(comp,total_drawable:int) -> float:
    area=comp.area/max(1,total_drawable)
    structural=min(1.0,comp.edge_mean*.72+comp.contour_mean*.48+comp.protected_ratio*.75)
    detail=min(1.0,comp.importance_mean*.72+comp.importance_max*.28)
    return max(.00001,area*(.58+.42*detail)+structural*.012+min(comp.area,64)/max(1,total_drawable)*.22)


def _entry_sequence(color_index:int, paths, *, phase:str, comp, brush_px:int, method:str):
    out=[]
    for serial,path in enumerate(paths):
        out.append({
            "color_index":int(color_index),"path":tuple(path),"phase":phase,
            "phase_label":phase.replace("_"," "),"component_id":int(comp.component_id),
            "component_area":int(comp.area),"component_width":int(comp.width),"component_height":int(comp.height),
            "importance":round(float(comp.importance_max),6),"protected":bool(comp.protected_pixels),
            "edge_mean":round(float(comp.edge_mean),6),"contour_mean":round(float(comp.contour_mean),6),
            "brush_px":int(brush_px),"hybrid_method":method,"local_serial":serial,
        })
    return out


def _path_rectangles(path,brush_px,width,height,*,cancelled=lambda:False):
    _cancel(cancelled)
    h,w=height,width;b=max(1,int(brush_px));lo=(b-1)//2;hi=b//2
    def rect(x0,y0,x1,y1):
        xa=max(0,min(x0,x1)-lo);xb=min(w-1,max(x0,x1)+hi)
        ya=max(0,min(y0,y1)-lo);yb=min(h-1,max(y0,y1)+hi)
        return (xa,ya,xb,yb) if xa<=xb and ya<=yb else None
    pts=path or ()
    if not pts:return
    if len(pts)==1:
        x,y=map(int,pts[0]);bounds=rect(x,y,x,y)
        if bounds is not None:yield bounds
        return
    for segment_number,(a,bp) in enumerate(zip(pts,pts[1:])):
        if segment_number%128==0:_cancel(cancelled)
        x0,y0=map(int,a);x1,y1=map(int,bp)
        if x0==x1 or y0==y1:
            bounds=rect(x0,y0,x1,y1)
            if bounds is not None:yield bounds
        else:
            for i,(x,y) in enumerate(clipped_interpolated_line((x0,y0),(x1,y1),w,h,before=lo,after=hi)):
                if i%256==0:_cancel(cancelled)
                bounds=rect(x,y,x,y)
                if bounds is not None:yield bounds


def _paint_path(mask:np.ndarray,path,brush_px:int,*,value=True,cancelled=lambda:False):
    for x0,y0,x1,y1 in _path_rectangles(path,brush_px,mask.shape[1],mask.shape[0],cancelled=cancelled):
        mask[y0:y1+1,x0:x1+1]=value


def _axis_footprint(mask,brush_px,axis,require_all,*,cancelled):
    """Rolling Boolean window counts with at most 16x1024 int64 scratch.

    A count changes only when one source value enters and another leaves. The
    cumulative delta is evaluated in bounded chunks, so neither brush size nor
    a very wide source creates an expanded window tensor or full-frame shifts.
    Missing source coordinates contribute zero, matching the physical border.
    """
    view=mask if axis==1 else mask.T
    rows,width=view.shape
    result=np.empty(view.shape,dtype=np.bool_)
    before=(brush_px-1)//2;after=brush_px//2
    for top in range(0,rows,16):
        _cancel(cancelled)
        block=view[top:top+16]
        # At x=0, the entering value at +after is handled by the first delta.
        carry=np.count_nonzero(block[:,:min(after,width)],axis=1).astype(np.int64)
        for left in range(0,width,1024):
            _cancel(cancelled)
            right=min(width,left+1024)
            deltas=np.zeros((len(block),right-left),dtype=np.int64)
            enter_end=min(right,width-after)
            if enter_end>left:
                deltas[:,:enter_end-left]=block[:,left+after:enter_end+after]
            leave_start=max(left,before+1)
            if leave_start<right:
                deltas[:,leave_start-left:]-=block[:,leave_start-before-1:right-before-1]
            np.cumsum(deltas,axis=1,out=deltas)
            deltas+=carry[:,None]
            result[top:top+len(block),left:right]=(deltas==brush_px) if require_all else (deltas>0)
            carry=deltas[:,-1].copy()
            del deltas
    _cancel(cancelled)
    return result if axis==1 else result.T


def _square_footprint(mask,brush_px,require_all,*,cancelled):
    _cancel(cancelled)
    mask=np.asarray(mask,dtype=np.bool_)
    brush=max(1,int(brush_px))
    if brush==1 or (require_all and brush>min(mask.shape)):
        result=mask.copy() if brush==1 else np.zeros_like(mask)
        _cancel(cancelled)
        return result
    vertical=_axis_footprint(mask,brush,0,require_all,cancelled=cancelled)
    return _axis_footprint(vertical,brush,1,require_all,cancelled=cancelled)


def _eroded_centers(target:np.ndarray,brush_px:int,*,cancelled=lambda:False) -> np.ndarray:
    """Centres whose entire asymmetric square brush footprint stays in target."""
    return _square_footprint(target,brush_px,True,cancelled=cancelled)


def _runs_from_mask(mask:np.ndarray,row_stride:int=1,row_offset:int=0,orientation:str="horizontal"):
    """Return axis-aligned runs through a boolean centre mask.

    The mask contains only brush centres whose complete footprint is already
    proven to stay inside the source component.  Connecting consecutive true
    centres therefore remains safe for square browser brushes.
    """
    view=mask if orientation!="vertical" else mask.T
    h,w=view.shape;out=[]
    stride=max(1,int(row_stride));offset=int(row_offset)%stride
    for y in range(offset,h,stride):
        row=view[y];x=0
        while x<w:
            if not row[x]:x+=1;continue
            x0=x;x+=1
            while x<w and row[x]:x+=1
            if orientation=="vertical":
                out.append(((y,x0),(y,x-1)) if x-1!=x0 else ((y,x0),))
            else:
                out.append(((x0,y),(x-1,y)) if x-1!=x0 else ((x0,y),))
    return out


def _centers_touching_mask(mask:np.ndarray,brush_px:int,*,cancelled=lambda:False) -> np.ndarray:
    """Return centres whose simulated footprint touches at least one wanted pixel."""
    return _square_footprint(mask,brush_px,False,cancelled=cancelled)



def _offset_paths(paths, origin):
    """Translate ROI-local paths back to absolute planner/canvas coordinates."""
    ox,oy=map(int,origin)
    if ox==0 and oy==0:return [tuple((int(x),int(y)) for x,y in path) for path in paths]
    return [tuple((int(x)+ox,int(y)+oy) for x,y in path) for path in paths]


def _candidate_paths_for_brush(target:np.ndarray,residual:np.ndarray,brush_px:int,*,
                               model,comp,phase:str,final_size:bool,origin=(0,0),cancelled=lambda:False,
                               projection=None):
    """Choose a safe, cost-efficient run layout inside one component ROI.

    Extra Fast tests the native brush stride and one denser half-stride for wide
    brushes.  Candidates within 90% of the best unique-pixel gain compete on
    calibrated execution seconds per newly covered pixel instead of raw gain
    alone.  This avoids accepting a much slower layout for a negligible coverage
    increase while keeping every simulated brush footprint inside the component.
    """
    _cancel(cancelled)
    brush=max(1,int(brush_px))
    safe=_eroded_centers(target,brush,cancelled=cancelled)
    useful=safe & _centers_touching_mask(residual,brush,cancelled=cancelled)
    if projection is not None:
        useful=projection.source_centers(useful)
    if not np.any(useful):return [],np.zeros_like(target,dtype=np.bool_),0.0
    stride_sets={}
    for orientation in ('horizontal','vertical'):
        scale=(projection.scale_y if orientation=='horizontal' else projection.scale_x) if projection is not None else 1.
        stride_sets[orientation]=((1,) if final_size else
            tuple(dict.fromkeys((max(1,int(brush/scale)),max(1,int((brush//2)/scale))))))
    strides=tuple(dict.fromkeys(stride for values in stride_sets.values() for stride in values))
    def paint(mask,path,*,cancelled=cancelled):
        native=projection.native_path(path) if projection is not None else path
        _paint_path(mask,native,brush,cancelled=cancelled)
    candidates=[]
    for stride in strides:
        offsets=(0,) if stride==1 else tuple(range(stride))
        for orientation in ("horizontal","vertical"):
            if stride not in stride_sets[orientation]:continue
            for offset in offsets:
                _cancel(cancelled)
                local_paths=_runs_from_mask(useful,row_stride=stride,row_offset=offset,orientation=orientation)
                if not local_paths:continue
                trial=np.zeros_like(target,dtype=np.bool_)
                for path in local_paths:paint(trial,path)
                if np.any(trial & ~target):continue
                gained=int(np.count_nonzero(trial & residual))
                if gained<=0:continue
                paths=_offset_paths(local_paths,origin)
                seq=_entry_sequence(comp.color_index,paths,phase=phase,comp=comp,brush_px=brush,
                                    method=f"region-brush-pack-{brush}px")
                cost=max(.000001,float(model.sequence_cost(
                    seq,initial_color=int(comp.color_index),initial_brush=brush).total_seconds))
                # Selection needs only scalar scores and the deterministic
                # layout descriptor. Retaining every candidate's full ROI
                # bitmap and path lists multiplied the live workspace by all
                # stride offsets; only the winning geometry is returned.
                candidates.append((gained,cost,len(paths),stride,orientation,offset))
                del local_paths,paths,seq,trial
    if not candidates:return [],np.zeros_like(target,dtype=np.bool_),0.0
    max_gain=max(row[0] for row in candidates)
    gain_floor=max(1,int(max_gain*.90))
    eligible=[row for row in candidates if row[0]>=gain_floor]
    best=min(eligible,key=lambda row:(row[1]/max(1,row[0]),row[1],row[2],-row[0],row[3],row[4],row[5]))
    _cancel(cancelled)
    local_paths=_runs_from_mask(useful,row_stride=best[3],row_offset=best[5],orientation=best[4])
    painted=np.zeros_like(target,dtype=np.bool_)
    for path in local_paths:paint(painted,path)
    paths=_offset_paths(local_paths,origin)
    _cancel(cancelled)
    return paths,painted,float(best[1])


def _eligible_brush_sizes_for_roi(sizes,roi_shape):
    """Return verified sizes that can physically fit a region workspace."""
    roi_h,roi_w=map(int,roi_shape)
    fit_limit=max(1,min(roi_w,roi_h))
    normalized=tuple(sorted({max(1,int(v)) for v in sizes},reverse=True))
    eligible=tuple(v for v in normalized if v<=fit_limit)
    pruned=tuple(v for v in normalized if v>fit_limit)
    return eligible,pruned


def _brush_pack_candidate(comp,component_map,options,model,cancelled=lambda:False,*,projection=None):
    """Find the cheapest exact verified brush packing for one region.

    Work is bbox-local. Brush sizes that physically cannot fit the component ROI
    are rejected before erosion. A bounded set of verified brush ladders is then
    evaluated so an expensive intermediate brush switch is never mandatory just
    because the target exposes five controls. A ladder may need only one of its
    available sizes to finish the region.
    """
    default=max(1,int(options.get("brush_px") or 1))
    verified,dynamic=verified_brush_sizes(str(options.get("profile_key") or ""),
                                          options.get("browser_brush_plan"),default)
    verified=tuple(sorted({max(1,int(v)) for v in verified},reverse=True))
    if not dynamic or len(verified)<2:
        return None,"no verified multi-brush controls"
    smallest=min(verified)
    if projection is None and comp.area<max(48,smallest*smallest*6):
        return None,"component too small for region brush packing"

    h,w=component_map.shape
    x0,y0,x1,y1=map(int,comp.bbox)
    x0=max(0,min(w-1,x0));x1=max(0,min(w-1,x1))
    y0=max(0,min(h-1,y0));y1=max(0,min(h-1,y1))
    if x1<x0 or y1<y0:return None,"invalid component bbox"
    native_roi=None
    if projection is not None:
        native_roi,reason=projection.component_roi(component_map,comp.component_id,
            (x0,y0,x1,y1),cancelled=cancelled)
        if native_roi is None:return None,reason
        target=native_roi.target
        if np.count_nonzero(target)<max(48,smallest*smallest*6):
            return None,'component too small for native region brush packing'
    else:
        roi_map=component_map[y0:y1+1,x0:x1+1]
        target=roi_map==comp.component_id
    if not np.any(target):return None,"empty component"

    roi_h,roi_w=target.shape
    sizes,pruned=_eligible_brush_sizes_for_roi(verified,target.shape)
    if smallest not in sizes or len(sizes)<2:
        return None,f"fewer than two verified brushes fit ROI {roi_w}x{roi_h}; pruned={pruned}"

    ladders=[]
    def add_ladder(raw):
        values=tuple(sorted({int(v) for v in raw if int(v) in sizes},reverse=True))
        if smallest not in values:values=tuple(sorted(set(values+(smallest,)),reverse=True))
        if len(values)>=2 and values not in ladders:ladders.append(values)
    add_ladder(sizes)
    add_ladder((sizes[0],smallest))
    add_ladder(tuple(sizes[::2])+(smallest,))
    if len(sizes)>3:add_ladder(tuple(sizes[1::2])+(sizes[0],smallest))
    for drop in sizes[1:-1]:
        add_ladder(tuple(v for v in sizes if v!=drop))
    ladders=ladders[:6]

    total_drawable=int(np.count_nonzero(component_map>=0))
    base_phase=_phase(comp,total_drawable)
    exact_candidates=[];best_residual=None
    for ladder in ladders:
        _cancel(cancelled)
        painted=np.zeros_like(target,dtype=np.bool_)
        sequence=[];flat_paths=[];used=[];per_size=[]
        for brush in ladder:
            _cancel(cancelled)
            residual=target & ~painted
            if not np.any(residual):break
            extra={'projection':native_roi} if native_roi is not None else {}
            paths,trial,local_cost=_candidate_paths_for_brush(
                target,residual,brush,model=model,comp=comp,
                phase=("detail" if brush==smallest else base_phase),
                final_size=(brush==smallest),origin=(x0,y0),cancelled=cancelled,**extra)
            if not paths:continue
            newly=int(np.count_nonzero(trial & residual))
            if newly<=0:continue
            painted |= trial
            used.append(brush);flat_paths.extend(paths)
            sequence.extend(_entry_sequence(
                comp.color_index,paths,phase=("detail" if brush==smallest else base_phase),
                comp=comp,brush_px=brush,method=f"region-brush-pack-{brush}px"))
            per_size.append({"brush_px":brush,"paths":len(paths),"new_pixels":newly,
                             "local_cost_seconds":round(local_cost,6)})
        if np.any(painted & ~target):continue
        missing=int(np.count_nonzero(target & ~painted))
        best_residual=missing if best_residual is None else min(best_residual,missing)
        if missing or not np.array_equal(painted,target):continue
        # One verified size can already cover the region exactly. It is still
        # a physically selectable candidate and must compete on actual cost;
        # requiring two used sizes rejected the simplest successful pack.
        cost=model.sequence_cost(
            sequence,initial_color=int(comp.color_index),initial_brush=default).total_seconds
        exact_candidates.append({"sequence":sequence,"paths":flat_paths,"cost":float(cost),
            "brush_px":max(used),"method":"region-brush-pack","exact":True,
            "used_brush_sizes":tuple(used),"packing":per_size,
            "requested_ladder":tuple(ladder),"covered_pixels":int(np.count_nonzero(painted))})

    if not exact_candidates:
        residual_text="unknown" if best_residual is None else str(int(best_residual))
        return None,(f"smallest verified brush cannot exactly repair residual pixels "
                     f"(best residual={residual_text}); eligible={sizes} pruned={pruned}")
    best=min(exact_candidates,key=lambda row:(row["cost"],len(row["sequence"]),-len(set(row["used_brush_sizes"]))))
    roi_pixels=int(target.size)
    canvas_pixels=(int(projection.canvas_size[0]*projection.canvas_size[1])
                   if projection is not None else int(component_map.size))
    reduction=max(0.0,1.0-(roi_pixels/max(1,canvas_pixels)))
    best.update({
        "packing_roi_bbox":(x0,y0,x1,y1),"packing_workspace_pixels":roi_pixels,
        "packing_canvas_pixels":canvas_pixels,
        "packing_workspace_reduction_percent":round(reduction*100.0,4),
        "verified_brush_sizes":verified,"eligible_brush_sizes":sizes,"pruned_brush_sizes":pruned,
        "ladder_candidates_evaluated":len(ladders),"exact_ladder_candidates":len(exact_candidates),
    })
    if native_roi is not None:
        best['packing_native_origin']=native_roi.native_origin
        best['packing_coordinate_space']='physical canvas pixels'
    return best,(
        f"exact verified brush packing chose ladder {best['requested_ladder']} using {best['used_brush_sizes']} "
        f"from {len(exact_candidates)}/{len(ladders)} exact candidates; pruned={pruned}")


def _choose_component(comp,component_map,total_drawable,model,options,cancelled=lambda:False,*,projection=None):
    phase=_phase(comp,total_drawable);gain=_component_gain(comp,total_drawable)
    default=max(1,int(options.get("brush_px") or 1))
    verified,dynamic=verified_brush_sizes(str(options.get("profile_key") or ""),options.get("browser_brush_plan"),default)
    base_brush=min(verified) if dynamic and verified else default
    candidates=[]
    for orientation in ("horizontal","vertical"):
        paths,exact=_orientation_paths(comp,orientation,component_map,cancelled)
        if not exact:continue
        seq=_entry_sequence(comp.color_index,paths,phase=phase,comp=comp,
                            brush_px=base_brush,method=f"connected-{orientation}-runs")
        cost=model.sequence_cost(
            seq, initial_color=int(comp.color_index), initial_brush=default).total_seconds
        candidates.append((cost,len(paths),orientation,seq,paths,base_brush))
    extra={'projection':projection} if projection is not None else {}
    packed,pack_reason=_brush_pack_candidate(comp,component_map,options,model,cancelled,**extra)
    if packed:
        candidates.append((packed["cost"],len(packed["paths"]),packed["method"],packed["sequence"],packed["paths"],packed["brush_px"]))
    if comp.area==1:
        x0,y0,_,_=comp.bbox;paths=[((x0,y0),)]
        seq=_entry_sequence(comp.color_index,paths,phase="detail",comp=comp,brush_px=base_brush,method="isolated-point")
        candidates.append((model.sequence_cost(
            seq, initial_color=int(comp.color_index), initial_brush=default).total_seconds,
            1,"isolated-point",seq,paths,base_brush))
    if not candidates:
        paths=_individual_paths(comp.horizontal_runs)
        seq=_entry_sequence(comp.color_index,paths,phase=phase,comp=comp,
                            brush_px=base_brush,method="safe-individual-runs")
        candidates=[(model.sequence_cost(
            seq, initial_color=int(comp.color_index), initial_brush=default).total_seconds,
            len(paths),"safe-individual-runs",seq,paths,base_brush)]
    best=min(candidates,key=lambda row:(row[0],row[1],row[2]))
    cost=max(.000001,float(best[0]))
    choice=RegionChoice(comp.component_id,comp.color_index,best[2],phase,comp.area,
                        float(comp.importance_mean),float(comp.edge_mean),comp.protected_pixels,
                        cost,gain,gain/(cost*1000.0),best[1],best[5],True,
                        f"minimum calibrated execution cost among {len(candidates)} exact candidate(s); {pack_reason}")
    if projection is not None:
        # The legacy connected-run proof describes source centerlines. A
        # scaled fallback may leave native gaps or paint beyond a source cell;
        # only the fully checked native packing earns an exact-footprint claim.
        choice.exact=best[2]=='region-brush-pack'
        choice.reason=(f'minimum calibrated execution cost among {len(candidates)} candidate(s); '
                       f'native exact packing={choice.exact}; {pack_reason}')
    diagnostics={"component_id":comp.component_id,
        "verified_brush_sizes":list(map(int,verified)),"base_brush_px":int(base_brush),
        "candidates":[{"method":c[2],"estimated_seconds":round(float(c[0]),6),"paths":int(c[1])} for c in candidates]}
    if packed:diagnostics["brush_packing"]={"used_brush_sizes":list(packed.get("used_brush_sizes") or ()),
        "packing":packed.get("packing") or (),"covered_pixels":int(packed.get("covered_pixels",0) or 0),
        "roi_bbox":packed.get("packing_roi_bbox"),
        "workspace_pixels":int(packed.get("packing_workspace_pixels",0) or 0),
        "canvas_pixels":int(packed.get("packing_canvas_pixels",0) or 0),
        "workspace_reduction_percent":float(packed.get("packing_workspace_reduction_percent",0.0) or 0.0)}
    if packed and projection is not None:
        diagnostics['brush_packing'].update(coordinate_space='physical canvas pixels',
            native_origin=packed.get('packing_native_origin'))
    return choice,list(best[3]),diagnostics


def _budget_seconds(options,model,choices,fill_regions,image_size,fitted):
    """Resolve one canonical render budget, then subtract real non-path work.

    TimeBudgetEngine owns timer/reserve semantics. If a profile/tuner already
    supplied resolved deadline fields they win. This prevents Extra Fast from
    inventing a second reserve on top of the UI/game preset reserve.
    """
    mode=str(options.get("time_budget_mode") or "")
    active=bool(options.get("time_budget_active")) and mode not in ("Unlimited","Unlimited / Accuracy","Off")
    try:manual=float(options.get("manual_max_seconds") or options.get("max_seconds") or 180)
    except Exception:manual=180.0
    total=manual;reserve=0.0;render_budget=float('inf');deadline_source="inactive"
    if active:
        def finite(raw,default=0.0):
            try:value=float(raw)
            except Exception:return float(default)
            return value if math.isfinite(value) else float(default)
        resolved_render=finite(options.get("deadline_render_budget_seconds"),0.0)
        resolved_total=finite(options.get("deadline_total_seconds"),0.0)
        resolved_reserve=finite(options.get("deadline_safety_reserve_seconds"),-1.0)
        if resolved_render>0:
            render_budget=resolved_render
            total=resolved_total if resolved_total>0 else resolved_render+max(0.0,resolved_reserve)
            reserve=max(0.0,total-render_budget) if resolved_reserve<0 else max(0.0,resolved_reserve)
            deadline_source="pre-resolved deadline fields"
        else:
            try:
                from TimeBudgetEngine import resolve_budget
                resolved=resolve_budget(mode,manual,options.get("deadline_safety_reserve","Auto"))
            except Exception:
                resolved={"active":False}
            if resolved.get("active"):
                total=float(resolved.get("total_seconds") or manual)
                reserve=max(0.0,float(resolved.get("reserve_seconds") or 0.0))
                render_budget=max(0.0,float(resolved.get("render_budget_seconds") or (total-reserve)))
                deadline_source=str(resolved.get("source") or "TimeBudgetEngine")
            else:
                total=max(5.0,manual)
                reserve=max(0.0,finite(options.get("deadline_safety_reserve_seconds"),0.0))
                render_budget=max(0.0,total-reserve)
                deadline_source="legacy active deadline fields"

    fixed=model.fixed_overhead(active_colors=0,fill_actions=0)
    fill_meta={"fill_regions":0,"fill_color_batches":0,"total_seconds":0.0}
    if fill_regions:
        try:
            from RegionFillEngine import estimate_fill_execution_seconds
            fill_meta=dict(estimate_fill_execution_seconds(fill_regions,image_size,fitted,options) or fill_meta)
        except Exception:
            fill_meta={"fill_regions":len(fill_regions),"fill_color_batches":0,
                       "total_seconds":len(fill_regions)*model.switch_cost("fill"),"fallback":True}
    fill_seconds=max(0.0,float(fill_meta.get("total_seconds",0.0) or 0.0))
    fill_colors={int(r.get("color_index",-1)) for r in (fill_regions or ())
                 if isinstance(r,dict) and int(r.get("color_index",-1))>=0}
    fill_selections=[model.color_selection_cost(color) for color in fill_colors]
    fill_palette_seconds=sum(palette for palette,_custom in fill_selections)
    fill_custom_seconds=sum(custom for _palette,custom in fill_selections)
    clear_seconds=max(0.0,float(options.get("canvas_clear_estimate_seconds",0.0) or 0.0))
    outside_seconds=(fixed.total_seconds+fill_seconds+fill_palette_seconds+
                     fill_custom_seconds+clear_seconds)
    usable=max(0.0,render_budget-outside_seconds) if active else float('inf')
    return active,usable,{
        "base_fixed":fixed.as_dict(),"fill":fill_meta,
        "fill_palette_seconds":round(fill_palette_seconds,6),
        "fill_custom_color_seconds":round(fill_custom_seconds,6),
        "adaptive_verification_seconds":0.0,
        "adaptive_verification_policy":"once per retained sequence color",
        "canvas_clear_seconds":round(clear_seconds,6),
        "outside_sequence_seconds":round(outside_seconds,6),
        "deadline":{"source":deadline_source,"total_seconds":round(total,6),
                    "reserve_seconds":round(reserve,6),
                    "render_budget_seconds":None if not active else round(render_budget,6)},
    },reserve,total


def _schedule(choices, sequences_by_component, size, model,options,fill_regions,*,fitted=None,cancelled=lambda:False):
    _cancel(cancelled)
    budget_fitted=tuple(fitted) if fitted is not None else tuple(size)
    active,usable,fixed_meta,reserve,limit=_budget_seconds(
        options,model,choices,fill_regions,size,budget_fitted)
    weights={"foundation":1.25,"structure":1.18,"detail":1.04,"correction":.78}
    phase_order={p:i for i,p in enumerate(PHASES)}
    by_id={c.component_id:c for c in choices}
    try:initial_brush=max(1,int(options.get("brush_px") or 1))
    except Exception:initial_brush=1

    geom_cache={}
    def geometry(c):
        cached=geom_cache.get(c.component_id)
        if cached is not None:return cached
        seq=sequences_by_component.get(c.component_id) or ()
        rows=[e for e in seq if e.get("path")]
        if not rows:
            value=(None,None,initial_brush,initial_brush)
        else:
            value=(tuple(map(int,rows[0]["path"][0])),tuple(map(int,rows[-1]["path"][-1])),
                   max(1,int(rows[0].get("brush_px") or initial_brush)),
                   max(1,int(rows[-1].get("brush_px") or initial_brush)))
        geom_cache[c.component_id]=value;return value

    def transition_seconds(c,cursor,current_color,current_brush):
        start,_end,first_brush,_last_brush=geometry(c)
        travel=0.0
        if cursor is not None and start is not None:
            px=math.hypot((start[0]-cursor[0])*float(getattr(model,"scale_x",1.0)),
                          (start[1]-cursor[1])*float(getattr(model,"scale_y",1.0)))
            travel=min(.10,px*.000045)*float(getattr(model,"multiplier",1.0) or 1.0)
        palette=0.0
        if (not options.get("paint_current_color") and
            (current_color is None or int(current_color)!=int(c.color_index)
             or model.brush_resets_color(current_brush,first_brush))):
            palette=sum(model.color_selection_cost(int(c.color_index)))
        brush=0.0 if current_brush is None or int(current_brush)==int(first_brush) else float(model.switch_cost("brush_change"))
        return travel+palette+brush

    ordering_stats={"greedy_batches":0,"serpentine_batches":0,"components_ordered":0}
    def order_rows(ids):
        _cancel(cancelled)
        selected_rows=[by_id[i] for i in ids if i in by_id]
        cursor=None;current_color=None;current_brush=initial_brush;ordered=[]
        for phase in PHASES:
            phase_rows=[c for c in selected_rows if c.phase==phase]
            if phase_rows:current_color=None
            colors={int(c.color_index) for c in phase_rows}
            while colors:
                _cancel(cancelled)
                if current_color in colors:
                    ci=int(current_color)
                else:
                    def color_key(color):
                        rows=[c for c in phase_rows if int(c.color_index)==color]
                        best=min((transition_seconds(c,cursor,current_color,current_brush) for c in rows),default=0.0)
                        gain=max((c.gain_per_ms for c in rows),default=0.0)
                        return (best,-gain,color)
                    ci=min(colors,key=color_key)
                batch=[c for c in phase_rows if int(c.color_index)==ci]
                if len(batch)<=96:
                    ordering_stats["greedy_batches"]+=1
                    remaining=list(batch)
                    while remaining:
                        _cancel(cancelled)
                        pick=min(remaining,key=lambda c:(transition_seconds(c,cursor,current_color,current_brush),
                                                         -c.gain_per_ms,-c.visual_gain,c.component_id))
                        remaining.remove(pick);ordered.append(pick)
                        _start,cursor,_first,current_brush=geometry(pick)
                        current_color=pick.color_index
                else:
                    ordering_stats["serpentine_batches"]+=1
                    band_h=max(1,int(math.ceil(max(1,size[1])/16.0)))
                    def snake_key(c):
                        start,_end,first_brush,_last=geometry(c)
                        x,y=start or (0,0);band=max(0,int(y//band_h))
                        x_key=x if band%2==0 else -x
                        brush_penalty=0 if int(first_brush)==int(current_brush or first_brush) else 1
                        return (band,x_key,brush_penalty,-c.gain_per_ms,c.component_id)
                    for pick in sorted(batch,key=snake_key):
                        _cancel(cancelled)
                        ordered.append(pick);_start,cursor,_first,current_brush=geometry(pick);current_color=pick.color_index
                colors.remove(ci)
        ordering_stats["components_ordered"]+=len(ordered)
        return ordered

    def build_sequence(ids):
        sequence=[];serial=0
        for c in order_rows(ids):
            _cancel(cancelled)
            for local_index,raw in enumerate(sequences_by_component[c.component_id]):
                if local_index%256==0:_cancel(cancelled)
                e=dict(raw);e["serial"]=serial;serial+=1;sequence.append(e)
        return sequence

    def exact_cost(sequence):
        _cancel(cancelled)
        raw=model.sequence_cost(sequence,initial_brush=initial_brush,include_color_verification=True)
        _cancel(cancelled)
        risk=(model.risk_adjusted_seconds(raw.total_seconds)
              if active and hasattr(model,"risk_adjusted_seconds") else raw.total_seconds)
        return raw,float(risk)

    hard_seed_ids=set();soft_seed_ids=set();phase_seed_ids=set();spatial_seed_ids=set()
    if not active:
        selected={c.component_id for c in choices}
    else:
        selected=set();used=0.0
        protected=[c for c in choices if c.protected_pixels]
        protected.sort(key=lambda c:(-c.importance,-c.visual_gain,c.estimated_seconds,c.component_id))
        protected_cap=max(0.0,usable*.18);protected_used=0.0
        for c in protected[:8]:
            if used+c.estimated_seconds>usable:continue
            if protected_used+c.estimated_seconds>protected_cap and hard_seed_ids:continue
            selected.add(c.component_id);hard_seed_ids.add(c.component_id)
            used+=c.estimated_seconds;protected_used+=c.estimated_seconds

        for phase in ("foundation","structure","detail"):
            rows=[c for c in choices if c.phase==phase and c.component_id not in selected]
            if not rows:continue
            best=max(rows,key=lambda c:(c.gain_per_ms*weights[c.phase],c.visual_gain,-c.estimated_seconds,-c.component_id))
            if used+best.estimated_seconds<=usable:
                selected.add(best.component_id);soft_seed_ids.add(best.component_id);phase_seed_ids.add(best.component_id)
                used+=best.estimated_seconds

        cell_best={}
        for c in choices:
            _cancel(cancelled)
            if c.component_id in selected:continue
            seq=sequences_by_component[c.component_id]
            pts=[p for e in seq for p in (e.get("path") or ())[:1]]
            if not pts:continue
            x,y=pts[0];cx=min(3,max(0,int(x/max(1,size[0])*4)));cy=min(3,max(0,int(y/max(1,size[1])*4)))
            old=cell_best.get((cx,cy))
            if old is None or (c.visual_gain,c.area,-c.component_id)>(old.visual_gain,old.area,-old.component_id):
                cell_best[(cx,cy)]=c
        for c in sorted(cell_best.values(),key=lambda c:(-c.visual_gain,c.component_id)):
            if used+c.estimated_seconds<=usable:
                selected.add(c.component_id);soft_seed_ids.add(c.component_id);spatial_seed_ids.add(c.component_id)
                used+=c.estimated_seconds
        rest=[c for c in choices if c.component_id not in selected]
        rest.sort(key=lambda c:(-(c.gain_per_ms*weights[c.phase]),-c.visual_gain,c.component_id))
        for c in rest:
            _cancel(cancelled)
            if used+c.estimated_seconds<=usable:
                selected.add(c.component_id);used+=c.estimated_seconds

    sequence=build_sequence(selected)
    seq_cost,risk_cost=exact_cost(sequence)
    trimmed=[];refilled=[];swapped=[]

    if active:
        important_protected={c.component_id for c in choices
                             if c.component_id in selected and c.protected_pixels and c.importance>=.50}
        hard_protected=hard_seed_ids|important_protected
        while selected and risk_cost>usable+1e-9:
            rows=order_rows(selected)
            removable=[c for c in rows if c.component_id not in hard_protected and c.component_id not in soft_seed_ids]
            if not removable:removable=[c for c in rows if c.component_id not in hard_protected]
            if not removable:removable=rows
            victim=min(removable,key=lambda c:(c.gain_per_ms*weights[c.phase],c.visual_gain,-c.estimated_seconds,c.component_id))
            selected.remove(victim.component_id);trimmed.append(victim.component_id)
            sequence=build_sequence(selected);seq_cost,risk_cost=exact_cost(sequence)

        omitted=[c for c in choices if c.component_id not in selected]
        omitted.sort(key=lambda c:(-(c.gain_per_ms*weights[c.phase]),-c.visual_gain,c.component_id))
        for c in omitted[:64]:
            trial=set(selected);trial.add(c.component_id)
            trial_sequence=build_sequence(trial);trial_cost,trial_risk=exact_cost(trial_sequence)
            if trial_risk<=usable+1e-9:
                selected=trial;sequence=trial_sequence;seq_cost=trial_cost;risk_cost=trial_risk;refilled.append(c.component_id)

        for _ in range(8):
            omitted=[c for c in choices if c.component_id not in selected]
            omitted.sort(key=lambda c:(-c.visual_gain,-c.gain_per_ms,c.component_id))
            victims=[c for c in choices if c.component_id in selected and c.component_id not in hard_protected]
            victims.sort(key=lambda c:(c.visual_gain,c.gain_per_ms,-c.estimated_seconds,c.component_id))
            best_swap=None
            for incoming in omitted[:16]:
                for victim in victims[:16]:
                    gain_delta=incoming.visual_gain-victim.visual_gain
                    if gain_delta<=1e-12:continue
                    trial=set(selected);trial.remove(victim.component_id);trial.add(incoming.component_id)
                    trial_sequence=build_sequence(trial);trial_cost,trial_risk=exact_cost(trial_sequence)
                    if trial_risk>usable+1e-9:continue
                    score=(gain_delta,-trial_risk,-incoming.estimated_seconds,-incoming.component_id,victim.component_id)
                    if best_swap is None or score>best_swap[0]:
                        best_swap=(score,trial,trial_sequence,trial_cost,trial_risk,incoming.component_id,victim.component_id)
            if best_swap is None:break
            _score,selected,sequence,seq_cost,risk_cost,incoming_id,victim_id=best_swap
            swapped.append((victim_id,incoming_id))

    groups=[[] for _ in range(max([c.color_index for c in choices],default=-1)+1)]
    for e in sequence:
        while len(groups)<=int(e["color_index"]):groups.append([])
        groups[int(e["color_index"])].append(tuple(e["path"]))
    utilization=(risk_cost/usable*100.0) if active and usable>0 else 0.0
    nominal_utilization=(seq_cost.total_seconds/usable*100.0) if active and usable>0 else 0.0
    return groups,sequence,{
        "deadline_active":active,"deadline_seconds":round(limit,4),"usable_path_seconds":round(usable,4) if active else None,
        "fixed_overhead":fixed_meta,"safety_reserve_seconds":round(reserve,4),
        "selected_components":len(selected),"total_components":len(choices),
        "dropped_components":len(choices)-len(selected),
        "selected_path_cost_seconds":round(seq_cost.total_seconds,6),
        "risk_adjusted_path_cost_seconds":round(risk_cost,6),
        "calibration_uncertainty_multiplier":round(float(getattr(model,"uncertainty_multiplier",1.0) or 1.0),6),
        "selected_operation_cost":seq_cost.as_dict(),
        "exact_budget_guard":True,"risk_adjusted_budget_guard":True,
        "budget_trimmed_components":len(trimmed),"budget_refilled_components":len(refilled),
        "budget_swapped_components":len(swapped),"budget_swap_pairs":[list(v) for v in swapped[:16]],
        "budget_utilization_percent":round(utilization,3),"nominal_budget_utilization_percent":round(nominal_utilization,3),
        "palette_switches":int(seq_cost.palette_switches),"brush_switches":int(seq_cost.brush_switches),
        "protected_seed_components":len(hard_seed_ids),"phase_seed_components":len(phase_seed_ids),
        "spatial_seed_components":len(spatial_seed_ids),
        "phase_color_batching":True,"transition_cost_ordering":True,"brush_aware_ordering":True,
        "ordering_stats":dict(ordering_stats),
    }

def simulate_quantized_plan(pixel_map:PixelMap,sequence,fill_regions=(),*,cancelled=lambda:False):
    _cancel(cancelled)
    validated_pixel_indices(pixel_map,cancelled=cancelled)
    h,w=pixel_map.height,pixel_map.width
    canvas=np.full((h,w),-1,dtype=np.int16)
    for region in fill_regions or ():
        _cancel(cancelled)
        ci=validate_color_index(region.get("color_index"))
        for span_number,raw in enumerate(region.get("row_spans") or ()):
            if span_number%256==0:_cancel(cancelled)
            try:y,x0,x1=map(int,raw)
            except Exception:continue
            if 0<=y<h:
                if x1<x0:x0,x1=x1,x0
                x0=max(0,x0);x1=min(w-1,x1)
                if x0<=x1:canvas[y,x0:x1+1]=ci
    for e in sequence or ():
        _cancel(cancelled)
        if not e.get("path"):continue
        ci=validate_color_index(e["color_index"]);brush=max(1,int(e.get("brush_px") or 1))
        _paint_path(canvas,e.get("path") or (),brush,value=ci,cancelled=cancelled)
    target=pixel_map.palette_index;drawable=pixel_map.drawable_mask
    intended=max(1,int(np.count_nonzero(drawable)))
    painted=canvas>=0
    correct=drawable & (canvas==target)
    covered=drawable & painted
    wrong=drawable & painted & (canvas!=target)
    spill=(~drawable)&painted
    edge_target=drawable & (pixel_map.edge_map>=.5)
    protected=drawable & pixel_map.protected_mask
    def pct(n,d,fallback=0.0):return float(n)/int(d)*100.0 if int(d)>0 else float(fallback)
    coverage=pct(np.count_nonzero(covered),intended)
    color=pct(np.count_nonzero(correct),intended)
    edge=pct(np.count_nonzero(correct & edge_target),np.count_nonzero(edge_target),color)
    detail=pct(np.count_nonzero(correct & protected),np.count_nonzero(protected),color)
    spill_acc=max(0.0,100.0-pct(np.count_nonzero(spill),max(1,np.count_nonzero(painted))))
    score=.35*color+.25*coverage+.20*edge+.15*detail+.05*spill_acc
    _cancel(cancelled)
    return {
        "coverage_percent":round(coverage,4),"color_accuracy_percent":round(color,4),
        "edge_preservation_percent":round(edge,4),"protected_detail_percent":round(detail,4),
        "spill_accuracy_percent":round(spill_acc,4),"wrong_color_pixels":int(np.count_nonzero(wrong)),
        "spill_pixels":int(np.count_nonzero(spill)),"missing_pixels":int(np.count_nonzero(drawable & ~painted)),
        "pixel_accuracy_score":round(score,4),
        "score_formula":"0.35*color_accuracy + 0.25*coverage + 0.20*edge_preservation + 0.15*protected_detail + 0.05*spill_accuracy",
    },canvas


def diagnostic_previews(pixel_map:PixelMap,canvas:np.ndarray):
    h,w=canvas.shape
    coverage=np.zeros((h,w,3),dtype=np.uint8)
    coverage[:]=255
    target=pixel_map.palette_index;drawable=pixel_map.drawable_mask
    correct=drawable&(canvas==target);missing=drawable&(canvas<0);wrong=drawable&(canvas>=0)&(canvas!=target);spill=(~drawable)&(canvas>=0)
    coverage[correct]=(225,225,225);coverage[missing]=(255,80,80);coverage[wrong]=(255,170,45);coverage[spill]=(175,60,220)
    error=coverage.copy()
    return Image.fromarray(coverage,"RGB"),Image.fromarray(error,"RGB")


def _native_rectangles(projection,sequence,fill_regions=(),*,default_brush=1,cancelled=lambda:False):
    """Ordered native footprints; the brush is never scaled with the image."""
    width,height=projection.canvas_size
    for region in fill_regions or ():
        _cancel(cancelled)
        color=validate_color_index(region.get('color_index'))
        for number,(y,x0,x1) in enumerate(region.get('row_spans') or ()):
            if number%256==0:_cancel(cancelled)
            x0,x1=sorted((int(x0),int(x1)))
            bounds=projection.source_rectangle(x0,int(y),x1,int(y))
            if bounds[0]<=bounds[2] and bounds[1]<=bounds[3]:yield color,bounds
    brush=max(1,int(default_brush))
    for entry in sequence or ():
        _cancel(cancelled)
        path=entry.get('path') or ()
        if not path:continue
        color=validate_color_index(entry['color_index'])
        brush=max(1,int(entry.get('brush_px') or brush))
        native=projection.native_path(path,cancelled=cancelled)
        for bounds in _path_rectangles(native,brush,width,height,cancelled=cancelled):
            yield color,bounds


def simulate_native_plan(pixel_map,sequence,projection,fill_regions=(),*,default_brush=1,cancelled=lambda:False):
    """Score the whole physical canvas in bounded tiles, including letterbox spill."""
    _cancel(cancelled)
    validated_pixel_indices(pixel_map,cancelled=cancelled)
    width,height=projection.canvas_size
    preview_scale=min(1.,1600/max(width,height))
    preview_size=(max(1,round(width*preview_scale)),max(1,round(height*preview_scale)))
    preview_x=np.asarray(nearest_axis_samples(width,preview_size[0],cancelled=cancelled))
    preview_y=np.asarray(nearest_axis_samples(height,preview_size[1],cancelled=cancelled))
    coverage=Image.new('RGB',preview_size,'white')
    totals=dict(intended=0,painted=0,covered=0,correct=0,wrong=0,spill=0,
                edges=0,correct_edges=0,protected=0,correct_protected=0,missing=0)
    try:
        for left,top,right,bottom in projection.tiles(cancelled=cancelled):
            raw_x=projection.x_source[left:right];raw_y=projection.y_source[top:bottom]
            valid=((raw_y>=0)&(raw_y<pixel_map.height))[:,None]&((raw_x>=0)&(raw_x<pixel_map.width))[None,:]
            xs=np.clip(raw_x,0,pixel_map.width-1);ys=np.clip(raw_y,0,pixel_map.height-1)
            select=np.ix_(ys,xs)
            target=pixel_map.palette_index[select]
            drawable=pixel_map.drawable_mask[select]&valid
            canvas=np.full(target.shape,-1,dtype=np.int16)
            for color,(x0,y0,x1,y1) in _native_rectangles(projection,sequence,fill_regions,
                    default_brush=default_brush,cancelled=cancelled):
                xa,xb=max(left,x0),min(right-1,x1);ya,yb=max(top,y0),min(bottom-1,y1)
                if xa<=xb and ya<=yb:canvas[ya-top:yb-top+1,xa-left:xb-left+1]=color
            painted=canvas>=0
            correct=drawable&(canvas==target)
            edge_target=drawable&(pixel_map.edge_map[select]>=.5)
            protected=drawable&pixel_map.protected_mask[select].astype(np.bool_,copy=False)
            counts={'intended':drawable,'painted':painted,'covered':drawable&painted,
                'correct':correct,'wrong':drawable&painted&(canvas!=target),'spill':(~drawable)&painted,
                'edges':edge_target,'correct_edges':correct&edge_target,
                'protected':protected,'correct_protected':correct&protected,'missing':drawable&~painted}
            for name,mask in counts.items():totals[name]+=int(np.count_nonzero(mask))
            px0,px1=np.searchsorted(preview_x,(left,right),side='left')
            py0,py1=np.searchsorted(preview_y,(top,bottom),side='left')
            if px0<px1 and py0<py1:
                samples=np.ix_(preview_y[py0:py1]-top,preview_x[px0:px1]-left)
                shade=np.full((py1-py0,px1-px0,3),255,dtype=np.uint8)
                shade[correct[samples]]=(225,225,225)
                shade[counts['missing'][samples]]=(255,80,80)
                shade[counts['wrong'][samples]]=(255,170,45)
                shade[counts['spill'][samples]]=(175,60,220)
                with closing(Image.fromarray(shade,'RGB')) as block:coverage.paste(block,(int(px0),int(py0)))
            _cancel(cancelled)
        intended=max(1,totals['intended'])
        def pct(name,denominator,fallback=0.):
            return totals[name]/denominator*100. if denominator else fallback
        covered=pct('covered',intended);color=pct('correct',intended)
        edge=pct('correct_edges',totals['edges'],color)
        detail=pct('correct_protected',totals['protected'],color)
        spill=max(0.,100.-pct('spill',max(1,totals['painted'])))
        metrics={'coverage_percent':round(covered,4),'color_accuracy_percent':round(color,4),
            'edge_preservation_percent':round(edge,4),'protected_detail_percent':round(detail,4),
            'spill_accuracy_percent':round(spill,4),'wrong_color_pixels':totals['wrong'],
            'spill_pixels':totals['spill'],'missing_pixels':totals['missing'],
            'pixel_accuracy_score':round(.35*color+.25*covered+.20*edge+.15*detail+.05*spill,4),
            'score_formula':'0.35*color_accuracy + 0.25*coverage + 0.20*edge_preservation + 0.15*protected_detail + 0.05*spill_accuracy',
            'coordinate_space':'physical canvas pixels before CanvasGuard','target_pixels':totals['intended'],
            'canvas_size':projection.canvas_size,'simulation_tile_pixel_limit':projection.pixel_limit}
        _cancel(cancelled)
        error=coverage.copy()
        return metrics,coverage,error
    except BaseException:
        coverage.close()
        raise


def build_adaptive_execution(pixel_map:PixelMap,palette_rgb,options:dict[str,Any],fitted,
                             *,fill_regions=(),reference_pixel_map:PixelMap|None=None,cancelled=lambda:False):
    t0=time.perf_counter();_cancel(cancelled)
    workers=max(1,int(options.get("cpu_workers_resolved") or 1))
    components,cmap,component_meta=connected_components(pixel_map,cpu_workers=workers,cancelled=cancelled)
    region_seconds=time.perf_counter()-t0
    model=build_cost_model(options,(pixel_map.width,pixel_map.height),tuple(fitted))
    from NativeBrushProjection import NativeBrushProjection
    projection=NativeBrushProjection.for_scaled_plan((pixel_map.width,pixel_map.height),fitted,options,
                                                     cancelled=cancelled)
    total=max(1,int(np.count_nonzero(pixel_map.drawable_mask)))
    choices=[];seqs={};candidate_meta=[]
    t1=time.perf_counter()
    for comp in components:
        _cancel(cancelled)
        extra={'projection':projection} if projection is not None else {}
        choice,seq,meta=_choose_component(comp,cmap,total,model,options,cancelled,**extra)
        choices.append(choice);seqs[comp.component_id]=seq;candidate_meta.append(meta)
    candidate_seconds=time.perf_counter()-t1
    t2=time.perf_counter()
    groups,sequence,schedule_meta=_schedule(
        choices,seqs,(pixel_map.width,pixel_map.height),model,options,fill_regions,fitted=fitted,cancelled=cancelled)
    reference=reference_pixel_map if reference_pixel_map is not None else pixel_map
    if projection is not None:
        metrics,coverage_preview,error_preview=simulate_native_plan(reference,sequence,projection,fill_regions,
            default_brush=options.get('brush_px',1),cancelled=cancelled)
    else:
        metrics,canvas=simulate_quantized_plan(reference,sequence,fill_regions,cancelled=cancelled)
        _cancel(cancelled)
        coverage_preview,error_preview=diagnostic_previews(reference,canvas)
    simulation_seconds=time.perf_counter()-t2
    methods={}
    for c in choices:methods[c.method]=methods.get(c.method,0)+1
    return {
        "execution_groups":groups,"execution_sequence":sequence,
        "metrics":metrics,"coverage_preview":coverage_preview,"error_preview":error_preview,
        "metadata":{
            "enabled":True,"version":ADAPTIVE_HYBRID_VERSION,"engine":"Adaptive Region Hybrid 4.0",
            "extra_fast_regional_route":bool(options.get("extra_fast")),
            "extra_fast_10_pack":True,
            "extra_fast_10_improvements":(
                "canonical-deadline-reserve","risk-adjusted-budget-guard","protected-detail-reserve",
                "phase-minimum-seeding","travel-aware-ordering","brush-aware-ordering",
                "exact-quality-swap","brush-roi-pruning","adaptive-brush-stride","cost-aware-brush-ladders",
            ),
            "component_meta":component_meta,"components":len(components),"methods":methods,
            "region_choices":[c.as_dict() for c in choices[:256]],
            "candidate_diagnostics":candidate_meta[:128],"schedule":schedule_meta,
            "cost_model":{"source":model.source,"measured_samples":model.samples,"calibration_ratio":round(model.multiplier,6),
                          "profile_key":str(options.get("profile_key") or ""), "stroke_delivery":model.delivery.as_dict()},
            "timings":{"region_analysis_seconds":round(region_seconds,6),
                       "candidate_scoring_seconds":round(candidate_seconds,6),
                       "plan_simulation_seconds":round(simulation_seconds,6),
                       "adaptive_hybrid_total_seconds":round(time.perf_counter()-t0,6)},
            "quality":metrics,
            **({'native_projection':projection.as_meta(),'coverage_coordinate_space':'full physical canvas'}
               if projection is not None else {}),
            "fallback_engine":"legacy standard planner",
            "native_input_engine_changed":False,
        },
    }


def _fill_seed(region):
    raw=region.get("seed_pixel") if isinstance(region,dict) else None
    try:return tuple(map(int,raw))
    except Exception:pass
    try:
        x0,y0,x1,y1=map(int,region.get("bbox"))
        return ((x0+x1)//2,(y0+y1)//2)
    except Exception:return (0,0)


def _order_fill_regions_for_execution(regions):
    """Color-batch Fill regions and draw the largest safe region first.

    The ordered list is subsequently passed through StatefulFillSimulation, so
    the exact order used for execution is safety-validated rather than merely
    being a cosmetic sort.
    """
    rows=[dict(r) for r in (regions or ()) if isinstance(r,dict)]
    by_color={}
    for r in rows:by_color.setdefault(int(r.get("color_index",-1)),[]).append(r)
    color_order=sorted(by_color,key=lambda ci:(-sum(max(0,int(r.get("area_pixels",0) or 0)) for r in by_color[ci]),ci))
    out=[];batches=[]
    for ci in color_order:
        remaining=list(by_color[ci])
        if not remaining:continue
        first=max(remaining,key=lambda r:(int(r.get("area_pixels",0) or 0),-_fill_seed(r)[1],-_fill_seed(r)[0]))
        remaining.remove(first);batch=[first];cursor=_fill_seed(first)
        while remaining:
            pick=min(remaining,key=lambda r:(((_fill_seed(r)[0]-cursor[0])**2+(_fill_seed(r)[1]-cursor[1])**2),
                                             -int(r.get("area_pixels",0) or 0),_fill_seed(r)[1],_fill_seed(r)[0]))
            remaining.remove(pick);batch.append(pick);cursor=_fill_seed(pick)
        out.extend(batch);batches.append({"color_index":ci,"regions":len(batch),
                                          "pixels":sum(max(0,int(r.get("area_pixels",0) or 0)) for r in batch)})
    return out,{"policy":"color-batched-large-first-nearest","color_batches":len(batches),"batches":batches}


def _build_fill_regions(groups,palette_rgb,image_size,fitted,options,cancelled,*,source_image=None):
    if not options.get("fill_tool_available"):
        return [],{"enabled":False,"reason":"target has no verified Fill capability"}
    try:
        from FillOptimizer import detect_fill_regions_from_groups
        from RegionFillEngine import evaluate_region_candidates
        from SafeFillMask import filter_fill_regions_by_source_mask,source_fill_margin_px
        mode=str(options.get("background_fill") or "Balanced")
        if mode=="Off":mode="Balanced"
        margin=source_fill_margin_px(options.get("brush_px",1),2,image_size)
        candidates,base=detect_fill_regions_from_groups(
            groups,palette_rgb,image_size,mode,engine=options.get("fill_engine","Closed regions v2"),
            max_regions=384,cancelled=cancelled,return_meta=True,safe_margin_px=margin)
        accepted,meta=evaluate_region_candidates(candidates,image_size,fitted,options,base_meta=base,cancelled=cancelled)
        cost_accepted_count=len(accepted)
        accepted,mask_meta=filter_fill_regions_by_source_mask(accepted,image_size,margin_px=margin)
        if source_image is not None:
            from SafeFillMask import filter_fill_regions_by_source_alpha
            accepted,mask_meta=filter_fill_regions_by_source_alpha(
                accepted,source_image,metadata=mask_meta,cancelled=cancelled)
        accepted,fill_order_meta=_order_fill_regions_for_execution(accepted)
        accepted,state_meta=filter_stateful_fill_regions(accepted,image_size,brush_px=max(1,int(options.get("brush_px") or 1)),cancelled=cancelled)
        meta=dict(meta);meta["safe_fill_mask"]=mask_meta;meta["stateful_fill_simulation"]=state_meta
        # All reported savings/coverage describe the surviving executable
        # regions, not a proposal that a later source/brush proof rejected.
        by_color={}
        for region in accepted:by_color.setdefault(int(region['color_index']),[]).append(region)
        fill_order_meta=dict(fill_order_meta,color_batches=len(by_color),batches=[
            {'color_index':color,'regions':len(rows),'pixels':sum(int(r.get('area_pixels',0)) for r in rows)}
            for color,rows in by_color.items()])
        rejected_after_cost=max(0,cost_accepted_count-len(accepted))
        meta.update(fill_execution_order=fill_order_meta,accepted_regions=len(accepted),
            fill_safe_regions=len(accepted),fill_actions=len(accepted),outline_paths=len(accepted),
            contour_regions=sum(r.get('strategy')=='closed-contour' for r in accepted),
            rectangle_regions=sum(r.get('strategy')=='rectangle' for r in accepted),
            fill_color_batches=len(by_color),fill_sealed_regions=sum(bool(r.get('fill_seal_count')) for r in accepted),
            fill_seal_paths=sum(int(r.get('fill_seal_count',0)) for r in accepted),
            fill_coverage_percent=round(sum(int(r.get('area_pixels',0)) for r in accepted)/max(1,image_size[0]*image_size[1])*100,3),
            estimated_saved_strokes=sum(int(r.get('estimated_saved_strokes',0)) for r in accepted),
            estimated_time_saved_seconds=round(sum(float(r.get('estimated_time_saved_seconds',0)) for r in accepted),3),
            rejected_by_safety=int(meta.get('rejected_by_safety',0))+rejected_after_cost,
            fallback_stroke_regions=int(meta.get('fallback_stroke_regions',0))+rejected_after_cost,
            fallback_scanline_regions=int(meta.get('fallback_scanline_regions',0))+rejected_after_cost)
        retained_ids={r.get('region_fill_id') for r in accepted}
        reasons={r.get('region_id'):r.get('reason') for r in state_meta.get('rejections',())}
        meta['decisions']=[dict(row,accepted=False,render_method='CONNECTED_SCANLINES',
            estimated_time_saved_seconds=0.0,reason=reasons.get(row.get('region_id')) or 'source mask excludes Fill')
            if row.get('accepted') and row.get('region_id') not in retained_ids else row
            for row in meta.get('decisions',())]
        return list(accepted),meta
    except InterruptedError:raise
    except Exception as exc:
        return [],{"enabled":True,"fill_safe_regions":0,"fallback":"connected runs","reason":f"{type(exc).__name__}: {exc}"}


def _strokes_from_paths(groups):
    out=[]
    for paths in groups or ():
        strokes=[]
        for path in paths or ():
            pts=list(path)
            if not pts:continue
            if len(pts)==1:
                x,y=pts[0];strokes.append((int(x),int(y),int(x),int(y)));continue
            strokes.extend((int(a[0]),int(a[1]),int(b[0]),int(b[1])) for a,b in zip(pts,pts[1:]) if a!=b)
        out.append(strokes)
    return out


def build_adaptive_hybrid_plan(original:Image.Image,area,options:dict[str,Any],make_plan,finish_plan,
                               cancelled:Callable[[],bool]=lambda:False):
    """Build through the existing color engine, then replace only safe geometry."""
    if options.get("erase_mode"):
        raise ValueError("Adaptive Hybrid 4.0 needs a drawing tool, not Eraser.")
    inner=dict(options)
    inner.update({
        "_adaptive_hybrid_inner":True,"auto_engine_resolved":True,
        "render_style":"Standard / pixel","outline":False,
        "background_fill":"Off","use_region_fill_engine":False,
        "fill_tool_available":False,"progressive_rendering":"Off","stroke_optimizer":"Off",
        "detail_zoom":"Off",
    })
    inner.pop("background_fill_plan",None);inner.pop("fill_regions",None)
    base=make_plan(original,area,inner,cancelled)
    _cancel(cancelled)
    try:
        groups=[list(g) for g in (base.get("groups") or ())]
        palette=tuple(base.get("colors") or ())
        if not groups or not palette:
            raise ValueError("base color planner produced no drawable groups/palette")
        outer=dict(base.get("options") or {})
        for key in ("fill_tool_available","fill_tool_actions","fill_restore_actions","background_fill",
                    "fill_engine","fill_aggressiveness","use_region_fill_engine","browser_brush_plan",
                    "paint_profile","profile_key","profile_name","brush_px","time_budget_active",
                    "time_budget_mode","max_seconds","manual_max_seconds","deadline_safety_reserve"):
            if key in options:outer[key]=options[key]
        alpha_source=(base['image'] if ((outer.get('source_transparency_meta') or {}).get('zero_alpha_excluded')
                                      or outer.get('pixel_accurate')) else None)
        fill_regions,fill_meta=_build_fill_regions(groups,palette,base["image"].size,base["fitted"],outer,cancelled,
                                                 source_image=alpha_source)
        gpu_mode=str(outer.get('gpu_mode') or 'Auto')
        reference_pixel_map=pixel_map_from_groups(base["image"],groups,palette,gpu_mode=gpu_mode,cancelled=cancelled)
        work_groups=groups
        if fill_regions:
            from FillOptimizer import remove_filled_region_strokes
            work_groups=remove_filled_region_strokes(work_groups,fill_regions)
        pixel_map=(pixel_map_from_groups(base["image"],work_groups,palette,gpu_mode=gpu_mode,cancelled=cancelled)
                   if fill_regions else reference_pixel_map)
        result=build_adaptive_execution(pixel_map,palette,outer,base["fitted"],fill_regions=fill_regions,
                                        reference_pixel_map=reference_pixel_map,cancelled=cancelled)
        outer.update({
            "render_style":ADAPTIVE_HYBRID_RENDER_STYLE,"adaptive_hybrid_active":True,
            "adaptive_hybrid_version":ADAPTIVE_HYBRID_VERSION,"fill_regions":fill_regions,
            "region_fill_meta":fill_meta,"stroke_optimizer":"Off","progressive_rendering":"On",
            "color_workflow":"Progressive passes",
            "_adaptive_hybrid_execution_groups":result["execution_groups"],
            "_adaptive_hybrid_execution_sequence":result["execution_sequence"],
            "_pixel_coverage_preview":result["coverage_preview"],
            "_pixel_error_preview":result["error_preview"],
            "adaptive_hybrid_meta":result["metadata"],
            "_accuracy_original_source":original.copy(),
        })
        outer.pop("background_fill_plan",None)
        final_groups=_strokes_from_paths(result["execution_groups"])
        plan=finish_plan(base["image"],base["fitted"],final_groups,outer,cancelled)
        plan.setdefault("adaptive_hybrid_meta",result["metadata"])
        return plan
    except InterruptedError:raise
    except Exception as exc:
        base.setdefault("options",{})["adaptive_hybrid_meta"]={
            "enabled":False,"fallback":True,"fallback_engine":"legacy standard planner",
            "reason":f"{type(exc).__name__}: {exc}","native_input_engine_changed":False}
        base["adaptive_hybrid_meta"]=dict(base["options"]["adaptive_hybrid_meta"])
        return base


def render_adaptive_preview(source_size,preview_size,sequence,palette_rgb,fill_regions=(),*,cancelled=lambda:False,
                            fitted=None,options=None):
    _cancel(cancelled)
    w,h=map(int,source_size);pw,ph=map(int,preview_size)
    if min(w,h,pw,ph)<=0:raise ValueError('Preview dimensions must be positive.')
    count=len(palette_rgb)
    if count:validate_palette_count(count)
    if fitted is not None:
        from NativeBrushProjection import NativeBrushProjection
        projection=NativeBrushProjection.for_scaled_plan(source_size,fitted,options or {},cancelled=cancelled)
        if projection is not None:
            # Sample the physical fitted crop into the bounded display. Brush
            # intervals have already been painted in native pixels; resizing the
            # display must not resize their widths with the analysis image.
            x_samples=np.floor(projection.offset[0]+(np.arange(pw)+.5)*projection.fitted[0]/pw).astype(np.int64)
            y_samples=np.floor(projection.offset[1]+(np.arange(ph)+.5)*projection.fitted[1]/ph).astype(np.int64)
            out=Image.new('RGB',(pw,ph),'white');draw=ImageDraw.Draw(out)
            try:
                for color,bounds in _native_rectangles(projection,sequence,fill_regions,
                        default_brush=(options or {}).get('brush_px',1),cancelled=cancelled):
                    index=validate_color_index(color,palette_count=count)
                    x0,y0,x1,y1=bounds
                    left,right=np.searchsorted(x_samples,(x0,x1+1),side='left')
                    top,bottom=np.searchsorted(y_samples,(y0,y1+1),side='left')
                    if left<right and top<bottom:
                        draw.rectangle((int(left),int(top),int(right-1),int(bottom-1)),fill=tuple(palette_rgb[index]))
                _cancel(cancelled)
                return out
            except BaseException:
                out.close()
                raise
    x_samples=nearest_axis_samples(w,pw,cancelled=cancelled)
    y_samples=nearest_axis_samples(h,ph,cancelled=cancelled)
    out=Image.new("RGB",(pw,ph),"white");draw=ImageDraw.Draw(out)
    def rectangle(bounds,color):
        x0,y0,x1,y1=bounds
        left,right=project_pixel_interval(x0,x1,w,pw,samples=x_samples)
        top,bottom=project_pixel_interval(y0,y1,h,ph,samples=y_samples)
        if left<=right and top<=bottom:draw.rectangle((left,top,right,bottom),fill=color)
    try:
        for region in fill_regions or ():
            _cancel(cancelled)
            color=tuple(map(int,palette_rgb[validate_color_index(region['color_index'],palette_count=count)]))
            for index,raw in enumerate(region.get('row_spans') or ()):
                if index%256==0:_cancel(cancelled)
                y,x0,x1=map(int,raw);x0,x1=sorted((x0,x1))
                if 0<=y<h and x1>=0 and x0<w:
                    rectangle((max(0,x0),y,min(w-1,x1),y),color)
        for entry in sequence or ():
            _cancel(cancelled)
            if not entry.get('path'):continue
            color=tuple(map(int,palette_rgb[validate_color_index(entry['color_index'],palette_count=count)]))
            brush=max(1,int(entry.get('brush_px') or 1))
            for bounds in _path_rectangles(entry['path'],brush,w,h,cancelled=cancelled):
                rectangle(bounds,color)
        _cancel(cancelled)
        return out
    except BaseException:
        out.close()
        raise
