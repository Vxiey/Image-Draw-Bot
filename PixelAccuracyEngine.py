"""Pixel-accuracy simulation and correction engine for Image Draw Bot v1.0.90-beta.

Block C consumes the lossless PixelMap + component-aware execution sequence from
Block B.  It simulates the brush footprint in planning coordinates, measures
coverage/color/edge/protected-feature accuracy, builds a categorical pixel error
map, and can append bounded correction passes only when the simulated score
improves.  No screen capture, mouse input, telemetry or native calls occur here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import math

import numpy as np
from PIL import Image

from PixelAccuratePlanner import PixelMap, validated_pixel_indices
from PixelMapValidation import validate_palette_count, validate_color_index
from RasterGeometry import clipped_bresenham
from AdaptiveBrushEngine import brush_for_entry, brush_sizes_for_sequence

Point = tuple[int, int]
Path = tuple[Point, ...]

ERROR_CORRECT = 0
ERROR_MISSING = 1
ERROR_WRONG_COLOR = 2
ERROR_SPILL = 3
UNPAINTED_WHITE = -1


@dataclass
class SimulationResult:
    simulated_index: np.ndarray
    coverage_count: np.ndarray
    coverage_map: np.ndarray
    error_map: np.ndarray
    metrics: dict

    def meta(self) -> dict:
        return dict(self.metrics)


def nearest_background_index(palette_rgb: Sequence[Sequence[int]]) -> int:
    if not palette_rgb:
        return 0
    return min(range(len(palette_rgb)), key=lambda i: sum((255-int(v))**2 for v in palette_rgb[i][:3]))


def _white_background_index(palette_rgb: Sequence[Sequence[int]]) -> int:
    """Represent the actual white canvas without inventing a drawing color.

    A calibrated white swatch can repaint spills. Otherwise the signed sentinel
    is simulation state only and must never become an executable correction.
    """
    return next((i for i, rgb in enumerate(palette_rgb)
                 if tuple(rgb[:3]) == (255, 255, 255)), UNPAINTED_WHITE)


def _clip_rect(x0: int, y0: int, x1: int, y1: int, width: int, height: int):
    x0,x1=sorted((int(x0),int(x1)));y0,y1=sorted((int(y0),int(y1)))
    if width<1 or height<1 or x1<0 or y1<0 or x0>=width or y0>=height:
        return None
    return max(0,x0),max(0,y0),min(width-1,x1),min(height-1,y1)


def _brush_extents(brush_px: int) -> tuple[int,int]:
    """Deterministic integer footprint with exactly ``brush_px`` pixels per axis."""
    b=max(1,int(round(brush_px)))
    before=(b-1)//2
    after=b-1-before
    return before,after


def _paint_rect(sim: np.ndarray, counts: np.ndarray, color: int,
                x0: int, y0: int, x1: int, y1: int) -> None:
    h,w=sim.shape
    if w<1 or h<1:return
    clipped=_clip_rect(x0,y0,x1,y1,w,h)
    if clipped is None:return
    x0,y0,x1,y1=clipped
    sim[y0:y1+1,x0:x1+1]=int(color)
    view=counts[y0:y1+1,x0:x1+1]
    np.add(view,1,out=view,where=view<np.iinfo(np.uint16).max)


def _bresenham(a: Point, b: Point):
    x0,y0=map(int,a);x1,y1=map(int,b)
    dx=abs(x1-x0);sx=1 if x0<x1 else -1
    dy=-abs(y1-y0);sy=1 if y0<y1 else -1
    err=dx+dy
    while True:
        yield x0,y0
        if x0==x1 and y0==y1:break
        e2=2*err
        if e2>=dy:err+=dy;x0+=sx
        if e2<=dx:err+=dx;y0+=sy


def _apply_path(sim: np.ndarray, counts: np.ndarray, color: int, path: Sequence[Point], brush_px: int,
                *, cancelled=lambda: False) -> None:
    if cancelled():raise InterruptedError()
    if not path:return
    before,after=_brush_extents(brush_px)
    if len(path)==1:
        x,y=map(int,path[0]);_paint_rect(sim,counts,color,x-before,y-before,x+after,y+after);return
    for segment_number,(a,b) in enumerate(zip(path,path[1:])):
        if segment_number%128==0 and cancelled():raise InterruptedError()
        x0,y0=map(int,a);x1,y1=map(int,b)
        if y0==y1:
            lo,hi=sorted((x0,x1));_paint_rect(sim,counts,color,lo-before,y0-before,hi+after,y0+after)
        elif x0==x1:
            lo,hi=sorted((y0,y1));_paint_rect(sim,counts,color,x0-before,lo-before,x0+after,hi+after)
        else:
            # Safety fallback for future non-orthogonal engines. Block B emits
            # orthogonal paths, but the simulator must never silently skip data.
            for point_number,(x,y) in enumerate(clipped_bresenham(
                    (x0,y0),(x1,y1),sim.shape[1],sim.shape[0],before=before,after=after)):
                if point_number%256==0 and cancelled():raise InterruptedError()
                _paint_rect(sim,counts,color,x-before,y-before,x+after,y+after)


def _apply_sequence(sim: np.ndarray, counts: np.ndarray, sequence: Sequence[dict], brush_px: int,
                    *, cancelled=lambda: False) -> int:
    current_brush=max(1,int(brush_px))
    for n,entry in enumerate(sequence):
        if n%128==0 and cancelled():raise InterruptedError()
        try:
            raw_color=entry['color_index'];path=tuple(tuple(map(int,p)) for p in entry['path'])
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
        if not path:continue
        color=validate_color_index(raw_color)
        current_brush=brush_for_entry(entry,current_brush)
        _apply_path(sim,counts,color,path,current_brush,cancelled=cancelled)
    if cancelled():raise InterruptedError()
    return current_brush


def _validate_simulation_input(pixel_map, sequence, palette_rgb, background_index, cancelled):
    if cancelled():raise InterruptedError()
    count=validate_palette_count(len(palette_rgb))
    validated_pixel_indices(pixel_map,count,cancelled=cancelled)
    bg=_white_background_index(palette_rgb) if background_index is None else validate_color_index(background_index,palette_count=count)
    for n,entry in enumerate(sequence):
        if n%128==0 and cancelled():raise InterruptedError()
        if isinstance(entry,dict) and entry.get('path'):
            validate_color_index(entry.get('color_index'),palette_count=count)
    return bg


def _desired_index(pixel_map: PixelMap, background_index: int) -> np.ndarray:
    return np.where(pixel_map.drawable_mask,pixel_map.palette_index,int(background_index)).astype(np.int16,copy=False)


def _score(pixel_map: PixelMap, simulated: np.ndarray, coverage_count: np.ndarray,
           background_index: int) -> tuple[np.ndarray,dict]:
    coverage=coverage_count>0
    desired=_desired_index(pixel_map,background_index)
    drawable=np.asarray(pixel_map.drawable_mask,dtype=bool)
    error=np.zeros(drawable.shape,dtype=np.uint8)
    missing=drawable & ~coverage
    wrong=drawable & coverage & (simulated!=desired)
    spill=(~drawable) & coverage & (simulated!=int(background_index))
    error[missing]=ERROR_MISSING;error[wrong]=ERROR_WRONG_COLOR;error[spill]=ERROR_SPILL

    evaluation=drawable | coverage
    correct=evaluation & (simulated==desired)
    eval_count=int(np.count_nonzero(evaluation))
    drawable_count=int(np.count_nonzero(drawable))
    correct_count=int(np.count_nonzero(correct))
    covered_target=int(np.count_nonzero(drawable & coverage))
    target_color_correct=int(np.count_nonzero(drawable & (simulated==desired)))

    edge_values=np.asarray(pixel_map.edge_map,dtype=np.float32)[drawable]
    edge_threshold=max(.32,float(np.percentile(edge_values,70.0))) if edge_values.size else .32
    edge_mask=drawable & (np.asarray(pixel_map.edge_map,dtype=np.float32)>=edge_threshold)
    edge_count=int(np.count_nonzero(edge_mask))
    edge_correct=int(np.count_nonzero(edge_mask & (simulated==desired)))
    protected=np.asarray(pixel_map.protected_mask,dtype=bool) & drawable
    protected_count=int(np.count_nonzero(protected))
    protected_correct=int(np.count_nonzero(protected & (simulated==desired)))
    overdraw_pixels=int(np.count_nonzero(coverage_count>1))
    total_hits=int(np.sum(coverage_count,dtype=np.uint64))
    touched=int(np.count_nonzero(coverage))
    target_accuracy=100.0*target_color_correct/max(1,drawable_count)

    metrics={
        'plan_execution_accuracy_percent':round(100.0*correct_count/max(1,eval_count),4),
        'pixel_accuracy_percent':round(100.0*correct_count/max(1,eval_count),4),
        'target_color_accuracy_percent':round(target_accuracy,4),
        'coverage_percent':round(100.0*covered_target/max(1,drawable_count),4),
        'edge_accuracy_percent':round(100.0*edge_correct/edge_count if edge_count else target_accuracy,4),
        'protected_accuracy_percent':round(100.0*protected_correct/protected_count if protected_count else target_accuracy,4),
        'evaluation_pixels':eval_count,'drawable_pixels':drawable_count,'correct_pixels':correct_count,
        'missing_pixels':int(np.count_nonzero(missing)),'wrong_color_pixels':int(np.count_nonzero(wrong)),
        'spill_pixels':int(np.count_nonzero(spill)),'error_pixels':int(np.count_nonzero(error)),
        'covered_target_pixels':covered_target,'edge_pixels':edge_count,'protected_pixels':protected_count,
        'touched_pixels':touched,'overdraw_pixels':overdraw_pixels,'total_brush_hits':total_hits,
        'mean_hits_per_touched_pixel':round(float(total_hits/max(1,touched)),5),
        'edge_threshold':round(edge_threshold,5),'background_index':int(background_index),
        'background_repaint_available':background_index != UNPAINTED_WHITE,
        'unrepairable_background_pixels':int(np.count_nonzero(spill)) if background_index == UNPAINTED_WHITE else 0,
    }
    return error,metrics


def simulate_strokes(pixel_map: PixelMap, execution_sequence: Sequence[dict], palette_rgb: Sequence[Sequence[int]], *,
                     brush_px: int = 1, background_index: int | None = None,
                     gpu_mode: str = "CPU", gpu_vram: str = "Auto",
                     gpu_performance: str = "High throughput",
                     cancelled=lambda: False) -> SimulationResult:
    """Rasterize the exact planned order, preferring Block-D CUDA when requested."""
    bg=_validate_simulation_input(pixel_map,execution_sequence,palette_rgb,background_index,cancelled)
    gpu_meta=None
    if gpu_mode != "CPU":
        try:
            from PixelAccuracyGpu import simulate_cuda
            gpu_result=simulate_cuda(execution_sequence,pixel_map.width,pixel_map.height,bg,
                                     brush_px=max(1,int(brush_px)),gpu_mode=gpu_mode,
                                     gpu_vram=gpu_vram,gpu_performance=gpu_performance,cancelled=cancelled)
            if gpu_result is not None:
                sim,counts,gpu_meta=gpu_result
                score_gpu=None
                try:
                    from PixelAccuracyGpu import score_cuda_host
                    score_gpu=score_cuda_host(pixel_map,sim,counts,bg,gpu_mode=gpu_mode,gpu_vram=gpu_vram,
                                             gpu_performance=gpu_performance,cancelled=cancelled)
                except InterruptedError:
                    raise
                except Exception:
                    score_gpu=None
                if cancelled():raise InterruptedError()
                if score_gpu is not None:error,metrics=score_gpu
                else:error,metrics=_score(pixel_map,sim,counts,bg)
                metrics.update(gpu_meta)
                _sizes=brush_sizes_for_sequence(execution_sequence,brush_px)
                metrics.update({'brush_model':'adaptive-square-swept-footprint','brush_px':max(1,int(brush_px)),
                                'brush_sizes_used':_sizes,'adaptive_brush':len(_sizes)>1})
                if cancelled():raise InterruptedError()
                return SimulationResult(sim,counts,counts>0,error,metrics)
        except InterruptedError:
            raise
        except Exception as exc:
            gpu_meta={'simulation_gpu_fallback':f'{type(exc).__name__}: {exc}'}
    sim=np.full((pixel_map.height,pixel_map.width),bg,dtype=np.int16)
    counts=np.zeros((pixel_map.height,pixel_map.width),dtype=np.uint16)
    _apply_sequence(sim,counts,execution_sequence,max(1,int(brush_px)),cancelled=cancelled)
    error,metrics=_score(pixel_map,sim,counts,bg)
    if cancelled():raise InterruptedError()
    _sizes=brush_sizes_for_sequence(execution_sequence,brush_px)
    metrics.update({'simulation_backend':'cpu-numpy-raster','brush_model':'adaptive-square-swept-footprint','brush_px':max(1,int(brush_px)),
                    'brush_sizes_used':_sizes,'adaptive_brush':len(_sizes)>1})
    if gpu_meta:metrics.update(gpu_meta)
    return SimulationResult(sim,counts,counts>0,error,metrics)


def progressive_time_budget(execution_sequence: Sequence[dict], *, active: bool, seconds: int,
                            profile_key: str = '', correction_reserve_ratio: float = .12) -> dict:
    """Choose a quality-first path subset without altering PixelMap geometry.

    Real-Speed history is used only as a throughput estimate. Unlike the old
    speed policy this function never reduces colours/resolution or simplifies
    components. Protected cleanup receives a reserved slice before low-priority
    fine detail when a timer is tight.
    """
    sequence=[dict(e) for e in execution_sequence]
    total=len(sequence)
    if not active or total<=0:
        return {'execution_sequence':sequence,'active':False,'path_budget':total,'base_path_budget':total,
                'correction_reserve':0,'paths_omitted':0,'paths_per_second':None,'source':'unlimited'}
    sec=max(5,int(seconds or 5));key=str(profile_key or '').lower()
    learned=False
    try:
        from RealSpeedBudget import load_profile, FALLBACK_PPS
        stored=load_profile(key)
        learned=bool(stored and float(stored.get('paths_per_second') or 0)>0)
        pps=float(stored.get('paths_per_second')) if learned else float(FALLBACK_PPS.get(key,5.0))
    except Exception:
        pps=5.0
    reserve_seconds=min(8.0,max(3.0,sec*.09));drawable=max(1.0,sec-reserve_seconds)
    path_budget=min(total,max(1,int(drawable*max(.25,pps)*.88)))
    correction_reserve=0 if path_budget>=total or correction_reserve_ratio<=0 else max(1,min(path_budget//4,int(round(path_budget*float(correction_reserve_ratio)))))
    base_budget=max(1,path_budget-correction_reserve)
    if base_budget>=total:
        selected=sequence
    else:
        phases={p:[] for p in ('fill','mid_detail','cleanup','fine_detail')}
        other=[]
        for e in sequence:
            phase=str(e.get('phase') or '')
            (phases[phase] if phase in phases else other).append(e)
        # Coverage/form first, guaranteed protected cleanup next, then remaining fine detail.
        fractions={'fill':.38,'mid_detail':.34,'cleanup':.16,'fine_detail':.12}
        caps={p:min(len(v),max(0,int(round(base_budget*fractions[p])))) for p,v in phases.items()}
        used=sum(caps.values())
        # Give unused quota to phases in quality-first order.
        for p in ('fill','mid_detail','cleanup','fine_detail'):
            if used>=base_budget:break
            extra=min(len(phases[p])-caps[p],base_budget-used)
            caps[p]+=max(0,extra);used+=max(0,extra)
        selected=[]
        for p in ('fill','mid_detail','cleanup','fine_detail'):
            selected.extend(phases[p][:caps[p]])
        if len(selected)<base_budget:selected.extend(other[:base_budget-len(selected)])
        selected=selected[:base_budget]
    return {
        'execution_sequence':selected,'active':True,'path_budget':path_budget,'base_path_budget':len(selected),
        'correction_reserve':max(0,path_budget-len(selected)),'paths_omitted':max(0,total-len(selected)),
        'paths_per_second':round(pps,4),'learned_speed':learned,'seconds':sec,'reserve_seconds':reserve_seconds,
        'source':'progressive-accuracy-time-budget','phase_order':'fill -> mid detail -> protected cleanup -> fine detail',
    }


def progressive_accuracy_checkpoints(pixel_map: PixelMap, execution_sequence: Sequence[dict],
                                     palette_rgb: Sequence[Sequence[int]], *, brush_px: int = 1,
                                     cancelled=lambda: False) -> list[dict]:
    """Measure accuracy after each progressive phase using one incremental CPU raster."""
    bg=_validate_simulation_input(pixel_map,execution_sequence,palette_rgb,None,cancelled)
    sim=np.full((pixel_map.height,pixel_map.width),bg,dtype=np.int16)
    counts=np.zeros((pixel_map.height,pixel_map.width),dtype=np.uint16);out=[]
    from itertools import groupby
    current_brush=max(1,int(brush_px))
    # Checkpoints must follow contiguous execution phases, including a phase
    # that occurs again later. Regrouping changes overpainting and scores.
    for phase, entries_iter in groupby(execution_sequence, key=lambda e:str(e.get('phase') or 'other')):
        entries=list(entries_iter)
        current_brush=_apply_sequence(sim,counts,entries,current_brush,cancelled=cancelled)
        _err,m=_score(pixel_map,sim,counts,bg)
        out.append({'phase':phase,'paths':len(entries),'pixel_accuracy_percent':m['pixel_accuracy_percent'],
                    'coverage_percent':m['coverage_percent'],'error_pixels':m['error_pixels']})
    if cancelled():raise InterruptedError()
    return out

def _correction_runs(pixel_map: PixelMap, result: SimulationResult, background_index: int, *,
                     pass_number: int, correction_brush_px: int = 1, cancelled=lambda: False) -> list[dict]:
    error=result.error_map
    desired=_desired_index(pixel_map,background_index)
    imp=np.asarray(pixel_map.importance_map,dtype=np.float32)
    protected=np.asarray(pixel_map.protected_mask,dtype=bool)
    h,w=error.shape
    entries=[];serial=0
    for y in range(h):
        if y%32==0 and cancelled():raise InterruptedError()
        x=0
        while x<w:
            if x%256==0 and cancelled():raise InterruptedError()
            # An absent white swatch cannot erase spill. Keep that error in the
            # report instead of emitting the simulation-only negative sentinel.
            if not error[y,x] or desired[y,x] < 0:x+=1;continue
            color=int(desired[y,x]);x0=x;score=float(imp[y,x]);protect=bool(protected[y,x]);x+=1
            while x<w and error[y,x] and int(desired[y,x])==color:
                if x%256==0 and cancelled():raise InterruptedError()
                score=max(score,float(imp[y,x]));protect=protect or bool(protected[y,x]);x+=1
            x1=x-1
            path=((x0,y),) if x0==x1 else ((x0,y),(x1,y))
            entries.append({'color_index':color,'path':path,'phase':f'correction_{pass_number}',
                            'phase_label':f'accuracy correction {pass_number}','component_id':-100-pass_number,
                            'orientation':'horizontal','serial':serial,'correction':True,
                            'brush_px':max(1,int(correction_brush_px)),'brush_reason':'accuracy-correction',
                            '_priority':(1 if protect else 0,score,x1-x0+1)})
            serial+=1
    # Protected/high-importance corrections first; stable coordinate serial breaks ties.
    entries.sort(key=lambda e:(-e['_priority'][0],-e['_priority'][1],-e['_priority'][2],e['serial']))
    for serial,e in enumerate(entries):
        e['serial']=serial;e.pop('_priority',None)
    return entries


def region_accuracy_scores(pixel_map: PixelMap, result: SimulationResult, *, max_regions: int = 64,
                           cancelled=lambda: False) -> dict:
    """Measure planned execution accuracy per exact connected target region."""
    from PixelStrokeEngine import connected_components
    components,cmap,_meta=connected_components(pixel_map,cpu_workers=1,include_vertical_runs=False,cancelled=cancelled)
    desired=np.asarray(pixel_map.palette_index,dtype=np.int16)
    simulated=np.asarray(result.simulated_index,dtype=np.int16)
    covered=np.asarray(result.coverage_count)>0
    edge=np.asarray(pixel_map.edge_map,dtype=np.float32)>=.5
    protected=np.asarray(pixel_map.protected_mask,dtype=bool)
    # Sum component statistics in bounded linear passes. A full-canvas mask for
    # every component makes checkerboards and fine text quadratic in pixels.
    component_counts=np.zeros((6,len(components)),dtype=np.int64)
    planes=[np.asarray(plane).ravel() for plane in (cmap,simulated,desired,covered,edge,protected)]
    for start in range(0,cmap.size,262_144):
        if cancelled():raise InterruptedError()
        ids,actual,wanted,hit,is_edge,is_detail=[plane[start:start+262_144] for plane in planes]
        valid=ids>=0
        if not np.any(valid):continue
        ids=ids[valid]
        correct=actual[valid]==wanted[valid]
        flags=(correct,hit[valid],is_edge[valid],is_detail[valid],
               correct & is_edge[valid],correct & is_detail[valid])
        for index,flag in enumerate(flags):
            component_counts[index] += np.bincount(ids[flag],minlength=len(components))
    rows=[];weighted=0.0;weighted_area=0
    def pct(n,d,fallback):
        return float(fallback) if int(d)<=0 else float(n)/float(d)*100.0
    for serial,comp in enumerate(components):
        if serial%64==0 and cancelled():raise InterruptedError()
        cid=int(comp.component_id);area=int(comp.area)
        if area<=0:continue
        correct_n,covered_n,edge_n,detail_n,correct_edge_n,correct_detail_n=map(int,component_counts[:,cid])
        color_acc=pct(correct_n,area,0.0)
        coverage_acc=pct(covered_n,area,0.0)
        edge_acc=pct(correct_edge_n,edge_n,color_acc)
        detail_acc=pct(correct_detail_n,detail_n,color_acc)
        score=.40*color_acc+.25*coverage_acc+.20*edge_acc+.15*detail_acc
        row={'component_id':int(comp.component_id),'color_index':int(comp.color_index),'area':area,
             'bbox':tuple(map(int,comp.bbox)),'score':round(score,4),
             'color_accuracy_percent':round(color_acc,4),'coverage_percent':round(coverage_acc,4),
             'edge_accuracy_percent':round(edge_acc,4),'protected_detail_percent':round(detail_acc,4),
             'error_pixels':int(area-correct_n),
             'protected_pixels':detail_n}
        rows.append(row);weighted+=score*area;weighted_area+=area
    rows.sort(key=lambda row:(float(row['score']),-int(row['area']),int(row['component_id'])))
    limit=max(1,int(max_regions))
    scores=[float(row['score']) for row in rows]
    return {'region_count':len(rows),'weighted_score':round(weighted/max(1,weighted_area),4),
            'mean_score':round(sum(scores)/max(1,len(scores)),4) if rows else 100.0,
            'minimum_score':round(min(scores),4) if rows else 100.0,
            'worst_regions':rows[:limit],
            'score_formula':'0.40*color + 0.25*coverage + 0.20*edge + 0.15*protected_detail'}


def refine_with_corrections(pixel_map: PixelMap, execution_sequence: Sequence[dict], palette_rgb: Sequence[Sequence[int]], *,
                            brush_px: int = 1, max_passes: int = 2, min_improvement: float = .0001,
                            correction_brush_px: int | None = None,
                            max_total_paths: int | None = None, min_repaired_pixels_per_path: float = .05,
                            gpu_mode: str = "CPU",
                            gpu_vram: str = "Auto", gpu_performance: str = "High throughput",
                            cancelled=lambda: False) -> dict:
    """Simulate, score and append correction passes only while accuracy improves."""
    background_index=_white_background_index(palette_rgb)
    sequence=[dict(e) for e in execution_sequence]
    if correction_brush_px is None:
        correction_brush_px=min(brush_sizes_for_sequence(sequence,brush_px))
    correction_brush_px=max(1,int(correction_brush_px))
    current=simulate_strokes(pixel_map,sequence,palette_rgb,brush_px=brush_px,
                             gpu_mode=gpu_mode,gpu_vram=gpu_vram,
                             gpu_performance=gpu_performance,cancelled=cancelled)
    initial=dict(current.metrics)
    pass_meta=[];accepted_entries=[]
    for pass_number in range(1,max(0,int(max_passes))+1):
        if cancelled():raise InterruptedError()
        if int(current.metrics.get('error_pixels',0))<=0:break
        remaining=None if max_total_paths is None else max(0,int(max_total_paths)-len(sequence))
        if remaining is not None and remaining<=0:break
        corrections=_correction_runs(pixel_map,current,background_index,pass_number=pass_number,correction_brush_px=correction_brush_px,cancelled=cancelled)
        if remaining is not None:corrections=corrections[:remaining]
        if not corrections:break
        if gpu_mode!='CPU':
            candidate=simulate_strokes(pixel_map,sequence+corrections,palette_rgb,brush_px=brush_px,
                                       gpu_mode=gpu_mode,gpu_vram=gpu_vram,
                                       gpu_performance=gpu_performance,cancelled=cancelled)
        else:
            sim=current.simulated_index.copy();counts=current.coverage_count.copy()
            _apply_sequence(sim,counts,corrections,max(1,int(brush_px)),cancelled=cancelled)
            error,metrics=_score(pixel_map,sim,counts,background_index)
            from itertools import chain
            _sizes=brush_sizes_for_sequence(chain(sequence,corrections),brush_px)
            metrics.update({'simulation_backend':'cpu-numpy-raster','brush_model':'adaptive-square-swept-footprint',
                            'brush_px':max(1,int(brush_px)),'brush_sizes_used':_sizes,
                            'adaptive_brush':len(_sizes)>1,'correction_brush_px':correction_brush_px})
            candidate=SimulationResult(sim,counts,counts>0,error,metrics)
        before=float(current.metrics['pixel_accuracy_percent']);after=float(candidate.metrics['pixel_accuracy_percent'])
        before_errors=int(current.metrics['error_pixels']);after_errors=int(candidate.metrics['error_pixels'])
        accuracy_gain=after-before
        errors_repaired=max(0,before_errors-after_errors)
        path_count=max(1,len(corrections))
        repaired_per_path=errors_repaired/path_count
        gain_per_path=max(0.0,accuracy_gain)/path_count
        accepted=(after>before+float(min_improvement)) or (after>=before and after_errors<before_errors)
        efficiency_floor=max(0.0,float(min_repaired_pixels_per_path))
        inefficient=(pass_number>1 and len(corrections)>=8 and errors_repaired>0 and
                     repaired_per_path<efficiency_floor and accuracy_gain<max(.005,float(min_improvement)*4.0))
        if inefficient:accepted=False
        pass_meta.append({'pass':pass_number,'generated_paths':len(corrections),'accepted':bool(accepted),
                          'before_accuracy':round(before,4),'after_accuracy':round(after,4),
                          'accuracy_gain':round(accuracy_gain,6),'accuracy_gain_per_path':round(gain_per_path,8),
                          'before_errors':before_errors,'after_errors':after_errors,
                          'errors_repaired':int(errors_repaired),'repaired_pixels_per_path':round(repaired_per_path,6),
                          'efficiency_floor':round(efficiency_floor,6),
                          'stop_reason':'low marginal correction gain' if inefficient else ('accepted' if accepted else 'no accuracy improvement')})
        if not accepted:break
        sequence.extend(corrections);accepted_entries.extend(corrections);current=candidate
    final=dict(current.metrics)
    try:
        region_meta=region_accuracy_scores(pixel_map,current,max_regions=64,cancelled=cancelled)
    except InterruptedError:raise
    except Exception as exc:
        region_meta={'region_count':0,'weighted_score':None,'mean_score':None,'minimum_score':None,
                     'worst_regions':[],'reason':f'{type(exc).__name__}: {exc}'}
    meta={
        'engine':'Pixel Accuracy Engine Block D','simulation':True,'coverage_map':True,'pixel_error_map':True,
        'score_scope':'planned strokes before CanvasGuard/runtime delivery',
        'automatic_corrections':True,'correction_pass_limit':max(0,int(max_passes)),
        'correction_passes_attempted':len(pass_meta),'correction_passes_accepted':sum(1 for p in pass_meta if p['accepted']),
        'correction_paths_added':len(accepted_entries),'correction_brush_px':correction_brush_px,
        'initial_plan_execution_accuracy_percent':initial['plan_execution_accuracy_percent'],
        'final_plan_execution_accuracy_percent':final['plan_execution_accuracy_percent'],
        # Legacy aliases remain for internal correction logic/backwards compatibility.
        'initial_accuracy_percent':initial['pixel_accuracy_percent'],
        'final_accuracy_percent':final['pixel_accuracy_percent'],'initial_error_pixels':initial['error_pixels'],
        'final_error_pixels':final['error_pixels'],'passes':pass_meta,
        'region_accuracy':region_meta,'region_accuracy_score':region_meta.get('weighted_score'),
        'worst_region_accuracy_score':region_meta.get('minimum_score'),
        'correction_efficiency_floor':max(0.0,float(min_repaired_pixels_per_path)),**final,
    }
    return {'execution_sequence':sequence,'correction_entries':accepted_entries,'simulation':current,'metadata':meta}

def execution_groups_from_sequence(sequence: Sequence[dict], palette_count: int) -> list[list[Path]]:
    groups=[[] for _ in range(max(0,int(palette_count)))]
    for entry in sequence:
        try:ci=int(entry['color_index']);path=tuple(tuple(map(int,p)) for p in entry['path'])
        except (KeyError,TypeError,ValueError):continue
        if 0<=ci<len(groups) and path:groups[ci].append(path)
    return groups


def render_coverage_map(pixel_map: PixelMap, result: SimulationResult) -> Image.Image:
    """Diagnostic map: target covered=green, target missing=amber, spill=red."""
    h,w=pixel_map.height,pixel_map.width
    out=np.zeros((h,w,3),dtype=np.uint8);out[:]=(20,25,32)
    drawable=np.asarray(pixel_map.drawable_mask,dtype=bool);coverage=result.coverage_map
    out[drawable & coverage]=(45,180,120)
    out[drawable & ~coverage]=(240,175,55)
    out[(~drawable)&coverage]=(220,70,75)
    return Image.fromarray(out,'RGB')


def render_error_map(pixel_map: PixelMap, result: SimulationResult) -> Image.Image:
    """Categorical pixel error map with protected unresolved features highlighted."""
    h,w=pixel_map.height,pixel_map.width
    out=np.zeros((h,w,3),dtype=np.uint8);out[:]=(22,26,34)
    drawable=np.asarray(pixel_map.drawable_mask,dtype=bool);correct=drawable & (result.error_map==ERROR_CORRECT)
    out[correct]=(52,125,92)
    out[result.error_map==ERROR_MISSING]=(245,182,60)
    out[result.error_map==ERROR_WRONG_COLOR]=(235,75,78)
    out[result.error_map==ERROR_SPILL]=(185,75,225)
    unresolved_protected=np.asarray(pixel_map.protected_mask,dtype=bool) & (result.error_map!=ERROR_CORRECT)
    out[unresolved_protected]=(255,235,110)
    return Image.fromarray(out,'RGB')
