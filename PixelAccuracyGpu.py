"""CUDA/tiled stroke simulation backend for Image Draw Bot v1.0.90-beta.

Block D keeps Block C's brush model and scoring semantics, but moves the expensive
planned-stroke raster simulation to NVIDIA CUDA when available.  The sequence is
compiled to ordered swept rectangles; row tiles and rectangle batches are chosen
from the configured VRAM budget.  CPU remains the deterministic fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import math

import numpy as np
from AdaptiveBrushEngine import brush_for_entry

Point = tuple[int, int]


@dataclass(frozen=True)
class SimulationPlan:
    rectangle_count: int
    tile_rows: int
    tile_count: int
    rectangle_batch_size: int
    rectangle_batches: int
    vram_budget_mb: int
    allocation_mode: str

    def as_dict(self) -> dict:
        return {
            'rectangle_count': int(self.rectangle_count),
            'tile_rows': int(self.tile_rows),
            'tile_count': int(self.tile_count),
            'rectangle_batch_size': int(self.rectangle_batch_size),
            'rectangle_batches': int(self.rectangle_batches),
            'vram_budget_mb': int(self.vram_budget_mb),
            'allocation_mode': str(self.allocation_mode),
        }


def _brush_extents(brush_px: int) -> tuple[int, int]:
    b=max(1,int(round(brush_px)));before=(b-1)//2;return before,b-1-before


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


def compile_swept_rectangles(sequence: Sequence[dict], brush_px: int, width: int, height: int,
                             *, cancelled=lambda: False) -> np.ndarray:
    """Compile execution order to x0,y0,x1,y1,color rectangles.

    Rectangle order is the paint order.  Orthogonal Block-B paths become one
    rectangle per segment; diagonal compatibility paths become ordered point
    rectangles via Bresenham, matching the CPU simulator.
    """
    rects=[]
    w=max(1,int(width));h=max(1,int(height))
    def add(x0,y0,x1,y1,color):
        from PixelAccuracyEngine import _clip_rect
        clipped=_clip_rect(x0,y0,x1,y1,w,h)
        if clipped is None:return
        x0,y0,x1,y1=clipped
        rects.append((x0,y0,x1,y1,int(color)))
    def checked_path(points):
        for point_index,point in enumerate(points):
            if point_index%128==0 and cancelled():raise InterruptedError()
            yield tuple(map(int,point))
    for n,entry in enumerate(sequence):
        if n%128==0 and cancelled():raise InterruptedError()
        try:color=int(entry['color_index']);path=tuple(checked_path(entry['path']))
        except (KeyError,TypeError,ValueError):continue
        if color<0 or not path:continue
        entry_brush=brush_for_entry(entry,brush_px);before,after=_brush_extents(entry_brush)
        if len(path)==1:
            x,y=path[0];add(x-before,y-before,x+after,y+after,color);continue
        for segment_index,(a,b) in enumerate(zip(path,path[1:])):
            if segment_index%128==0 and cancelled():raise InterruptedError()
            x0,y0=a;x1,y1=b
            if y0==y1:
                lo,hi=sorted((x0,x1));add(lo-before,y0-before,hi+after,y0+after,color)
            elif x0==x1:
                lo,hi=sorted((y0,y1));add(x0-before,lo-before,x0+after,hi+after,color)
            else:
                for point_index,(x,y) in enumerate(_bresenham(a,b)):
                    if point_index%128==0 and cancelled():raise InterruptedError()
                    add(x-before,y-before,x+after,y+after,color)
    if not rects:return np.empty((0,5),dtype=np.int32)
    return np.asarray(rects,dtype=np.int32)


_KERNEL_SOURCE = r'''
extern "C" __global__ void simulate_rects(
    short* sim, unsigned short* counts, const int width, const int tile_y0,
    const int tile_h, const int* rects, const int nrect)
{
    int p = blockDim.x * blockIdx.x + threadIdx.x;
    int total = width * tile_h;
    if (p >= total) return;
    int x = p % width;
    int y = tile_y0 + p / width;
    short color = sim[p];
    unsigned int c = counts[p];
    for (int i=0; i<nrect; ++i) {
        const int* r = rects + i*5;
        if (x>=r[0] && x<=r[2] && y>=r[1] && y<=r[3]) {
            color = (short)r[4];
            if (c < 65535u) ++c;
        }
    }
    sim[p] = color;
    counts[p] = (unsigned short)c;
}
'''


def _cuda_context(mode: str, vram_budget: str, performance: str):
    from GpuAcceleration import cuda_context
    return cuda_context(mode=mode,vram_budget=vram_budget,performance=performance)


def _plan(info, width: int, height: int, rectangle_count: int) -> SimulationPlan:
    from GpuAcceleration import plan_vram_allocation
    p=plan_vram_allocation(info,width,height,arrays=4,overlap=0)
    budget=max(128,int(info.vram_budget_mb or info.free_vram_mb or 256))
    # A rectangle is 20 bytes.  Keep rectangle staging under ~8% of the user
    # budget and under 250k entries to keep individual kernel launches bounded.
    batch=max(1024,min(250_000,int((budget*1024*1024*.08)//20)))
    tile_rows=max(1,min(128,int(height),int(p.get('tile_rows') or height)))
    # Bound work as well as allocation: every pixel scans every rectangle.
    # VRAM alone allowed billions of tests in a single desktop CUDA launch.
    batch=min(batch,max(1,8_000_000//max(1,int(width)*tile_rows)))
    tile_count=max(1,math.ceil(max(1,int(height))/tile_rows))
    batches=max(1,math.ceil(max(1,int(rectangle_count))/batch))
    return SimulationPlan(rectangle_count,tile_rows,tile_count,batch,batches,budget,
                          'VRAM-aware tiled CUDA' if tile_count>1 or batches>1 else 'VRAM-aware full CUDA')


\
def _simulation_attempt(cp, kernel, rects: np.ndarray, plan: SimulationPlan, width: int, height: int,
                        background_index: int, sim_host: np.ndarray, counts_host: np.ndarray,
                        *, cancelled=lambda: False) -> tuple[int,int]:
    sim_host.fill(int(background_index));counts_host.fill(0)
    launches=0;filtered_rectangles=0
    for y0 in range(0,height,plan.tile_rows):
        if cancelled():raise InterruptedError()
        y1=min(height,y0+plan.tile_rows);tile_h=y1-y0
        if len(rects):
            mask=(rects[:,3]>=y0)&(rects[:,1]<y1);tile_rects=rects[mask]
        else:tile_rects=rects
        filtered_rectangles+=len(tile_rects)
        sim_gpu=cp.asarray(sim_host[y0:y1],dtype=cp.int16)
        counts_gpu=cp.asarray(counts_host[y0:y1],dtype=cp.uint16)
        for start in range(0,len(tile_rects),plan.rectangle_batch_size):
            if cancelled():raise InterruptedError()
            batch=cp.asarray(tile_rects[start:start+plan.rectangle_batch_size],dtype=cp.int32)
            n=int(batch.shape[0])
            if n:
                total=width*tile_h;threads=256;blocks=(total+threads-1)//threads
                kernel((blocks,),(threads,),(sim_gpu,counts_gpu,np.int32(width),np.int32(y0),np.int32(tile_h),batch,np.int32(n)))
                launches+=1
            del batch
        sim_host[y0:y1]=cp.asnumpy(sim_gpu);counts_host[y0:y1]=cp.asnumpy(counts_gpu)
        del sim_gpu,counts_gpu
    cp.cuda.Stream.null.synchronize()
    return launches,filtered_rectangles


def _recovery_plan(base: SimulationPlan, height: int, rectangle_count: int, tile_rows: int, batch_size: int) -> SimulationPlan:
    rows=max(1,min(int(height),int(tile_rows)));batch=max(1,int(batch_size))
    return SimulationPlan(int(rectangle_count),rows,max(1,math.ceil(max(1,int(height))/rows)),batch,
                          max(1,math.ceil(max(1,int(rectangle_count))/batch)),base.vram_budget_mb,
                          'VRAM-recovery tiled CUDA' if rows<height or batch<max(1,rectangle_count) else base.allocation_mode)


def simulate_cuda(sequence: Sequence[dict], width: int, height: int, background_index: int, *,
                  brush_px: int = 1, gpu_mode: str = 'Auto', gpu_vram: str = 'Auto',
                  gpu_performance: str = 'High throughput', cancelled=lambda: False):
    """Return simulation arrays, shrinking CUDA work units before CPU fallback on OOM."""
    if gpu_mode=='CPU':return None
    try:
        context=_cuda_context(gpu_mode,gpu_vram,gpu_performance)
        if context is None:return None
        cp,info=context
        if not info.accelerated:return None
        rects=compile_swept_rectangles(sequence,brush_px,width,height,cancelled=cancelled)
        base_plan=_plan(info,width,height,len(rects))
        sim_host=np.full((height,width),int(background_index),dtype=np.int16)
        counts_host=np.zeros((height,width),dtype=np.uint16)
        kernel=cp.RawKernel(_KERNEL_SOURCE,'simulate_rects')
        from GpuAcceleration import gpu_memory_recovery_steps,is_gpu_memory_error,release_gpu_memory_cache
        steps=gpu_memory_recovery_steps(base_plan.tile_rows,base_plan.rectangle_batch_size,max_retries=3)
        oom_events=[];pool_releases=[]
        for n,step in enumerate(steps):
            plan=_recovery_plan(base_plan,height,len(rects),step['tile_rows'],step['batch_size'])
            try:
                launches,filtered_rectangles=_simulation_attempt(cp,kernel,rects,plan,width,height,background_index,
                                                                sim_host,counts_host,cancelled=cancelled)
                meta={
                    'simulation_backend':'cuda-cupy-tiled-raster','cuda_device':info.device,
                    'compute_capability':info.compute_capability,'gpu_performance':gpu_performance,
                    'kernel_launches':launches,'tile_filtered_rectangles':int(filtered_rectangles),**plan.as_dict(),
                    'vram_recovery_attempts':n,'vram_recovered':bool(n>0),
                    'initial_tile_rows':int(base_plan.tile_rows),'initial_rectangle_batch_size':int(base_plan.rectangle_batch_size),
                    'oom_events':tuple(oom_events),'pool_releases':tuple(pool_releases),
                }
                return sim_host,counts_host,meta
            except InterruptedError:
                raise
            except Exception as exc:
                if not is_gpu_memory_error(exc):
                    from CrashDiagnostics import log_event
                    log_event(f'CUDA stroke simulation failed; using CPU: {type(exc).__name__}: {exc}')
                    return None
                oom_events.append(f'{type(exc).__name__}: {exc}')
                from CrashDiagnostics import log_event
                if n+1>=len(steps):
                    log_event(f'CUDA stroke simulation exhausted {len(steps)} VRAM recovery attempt(s); using CPU: {type(exc).__name__}: {exc}')
                    return None
                pool_releases.append(release_gpu_memory_cache(cp))
                nxt=steps[n+1]
                log_event(f'CUDA stroke simulation VRAM pressure: retry {n+1}/{len(steps)-1} with tile_rows={nxt["tile_rows"]}, batch={nxt["batch_size"]}.')
        return None
    except InterruptedError:
        raise
    except Exception as exc:
        from CrashDiagnostics import log_event
        log_event(f'CUDA stroke simulation setup failed; using CPU: {type(exc).__name__}: {exc}')
        return None

\
def score_cuda_host(pixel_map, simulated: np.ndarray, coverage_count: np.ndarray, background_index: int, *,
                    gpu_mode: str = 'Auto', gpu_vram: str = 'Auto', gpu_performance: str = 'High throughput',
                    cancelled=lambda: False):
    """GPU categorical error scoring in bounded row tiles with OOM tile shrink."""
    if gpu_mode=='CPU':return None
    try:
        context=_cuda_context(gpu_mode,gpu_vram,gpu_performance)
        if context is None:return None
        cp,info=context
        from GpuAcceleration import gpu_score_tile_rows,is_gpu_memory_error,release_gpu_memory_cache
        drawable_h=np.asarray(pixel_map.drawable_mask,dtype=np.bool_)
        desired_h=np.where(drawable_h,pixel_map.palette_index,int(background_index)).astype(np.int16,copy=False)
        edge_h=np.asarray(pixel_map.edge_map,dtype=np.float32)
        protected_h=np.asarray(pixel_map.protected_mask,dtype=np.bool_)&drawable_h
        vals=edge_h[drawable_h]
        edge_threshold=max(.32,float(np.percentile(vals,70.0))) if vals.size else .32
        height,width=drawable_h.shape
        initial_rows=gpu_score_tile_rows(info,width,height,bytes_per_pixel=64,share=.42)
        tile_rows=initial_rows;min_rows=max(1,min(8,height));retries=0;tiles=0
        error_host=np.zeros((height,width),dtype=np.uint8)
        totals={k:0 for k in ('evaluation','drawable','correct','covered','target_correct','edge','edge_correct',
                               'protected','protected_correct','overdraw','touched','hits','missing','wrong','spill','errors')}
        y0=0
        while y0<height:
            if cancelled():raise InterruptedError()
            y1=min(height,y0+tile_rows)
            try:
                drawable=cp.asarray(drawable_h[y0:y1]);desired=cp.asarray(desired_h[y0:y1],dtype=cp.int16)
                sim=cp.asarray(simulated[y0:y1],dtype=cp.int16);counts=cp.asarray(coverage_count[y0:y1],dtype=cp.uint16)
                coverage=counts>0;missing=drawable&~coverage;wrong=drawable&coverage&(sim!=desired)
                spill=(~drawable)&coverage&(sim!=int(background_index))
                error=cp.zeros(drawable.shape,dtype=cp.uint8);error[missing]=1;error[wrong]=2;error[spill]=3
                evaluation=drawable|coverage;correct=evaluation&(sim==desired)
                edge=cp.asarray(edge_h[y0:y1]);edge_mask=drawable&(edge>=edge_threshold)
                protected=cp.asarray(protected_h[y0:y1])
                def nz(value):return int(cp.count_nonzero(value).get())
                # Reductions and the host copy may fail after earlier reductions
                # have completed. Commit a tile only after every operation has
                # succeeded, so retrying y0 cannot count its pixels twice.
                tile_totals={
                    'evaluation':nz(evaluation),'drawable':nz(drawable),'correct':nz(correct),
                    'covered':nz(drawable&coverage),'target_correct':nz(drawable&(sim==desired)),
                    'edge':nz(edge_mask),'edge_correct':nz(edge_mask&(sim==desired)),
                    'protected':nz(protected),'protected_correct':nz(protected&(sim==desired)),
                    'overdraw':nz(counts>1),'touched':nz(coverage),
                    'hits':int(cp.sum(counts,dtype=cp.uint64).get()),
                    'missing':nz(missing),'wrong':nz(wrong),'spill':nz(spill),'errors':nz(error),
                }
                tile_error=cp.asnumpy(error)
                next_totals={key:totals[key]+tile_totals[key] for key in totals}
                error_host[y0:y1]=tile_error
                totals=next_totals
                del drawable,desired,sim,counts,coverage,missing,wrong,spill,error,evaluation,correct,edge,edge_mask,protected
                y0=y1;tiles+=1
            except InterruptedError:
                raise
            except Exception as exc:
                if not is_gpu_memory_error(exc):
                    from CrashDiagnostics import log_event
                    log_event(f'CUDA accuracy scoring failed; using CPU score: {type(exc).__name__}: {exc}')
                    return None
                release_gpu_memory_cache(cp);retries+=1
                if tile_rows<=min_rows or retries>4:
                    from CrashDiagnostics import log_event
                    log_event(f'CUDA accuracy scoring exhausted VRAM tile recovery; using CPU score: {type(exc).__name__}: {exc}')
                    return None
                tile_rows=max(min_rows,tile_rows//2)
                from CrashDiagnostics import log_event
                log_event(f'CUDA accuracy scoring VRAM pressure: retrying current tile with {tile_rows} row(s).')
        try:cp.cuda.Stream.null.synchronize()
        except Exception:pass
        eval_count=totals['evaluation'];drawable_count=totals['drawable'];correct_count=totals['correct']
        metrics={
            'plan_execution_accuracy_percent':round(100.0*correct_count/max(1,eval_count),4),
            'pixel_accuracy_percent':round(100.0*correct_count/max(1,eval_count),4),
            'target_color_accuracy_percent':round(100.0*totals['target_correct']/max(1,drawable_count),4),
            'coverage_percent':round(100.0*totals['covered']/max(1,drawable_count),4),
            'edge_accuracy_percent':round(100.0*totals['edge_correct']/max(1,totals['edge']),4),
            'protected_accuracy_percent':round(100.0*totals['protected_correct']/max(1,totals['protected']),4),
            'evaluation_pixels':eval_count,'drawable_pixels':drawable_count,'correct_pixels':correct_count,
            'missing_pixels':totals['missing'],'wrong_color_pixels':totals['wrong'],'spill_pixels':totals['spill'],
            'error_pixels':totals['errors'],'covered_target_pixels':totals['covered'],'edge_pixels':totals['edge'],
            'protected_pixels':totals['protected'],'touched_pixels':totals['touched'],'overdraw_pixels':totals['overdraw'],
            'total_brush_hits':totals['hits'],'mean_hits_per_touched_pixel':round(float(totals['hits']/max(1,totals['touched'])),5),
            'edge_threshold':round(edge_threshold,5),'background_index':int(background_index),
            'score_backend':'cuda-cupy-tiled-reduction' if initial_rows<height or retries else 'cuda-cupy-reduction',
            'score_cuda_device':info.device,'score_tile_rows':int(tile_rows),'score_initial_tile_rows':int(initial_rows),
            'score_tile_count':int(tiles),'score_vram_retries':int(retries),'score_vram_recovered':bool(retries>0),
        }
        return error_host,metrics
    except InterruptedError:
        raise
    except Exception as exc:
        from CrashDiagnostics import log_event
        log_event(f'CUDA accuracy scoring setup failed; using CPU score: {type(exc).__name__}: {exc}')
        return None
