"""Stateful discrete Fill simulation for Image Draw Bot.

FillOptimizer remains the topology detector and RegionFillEngine remains the
first safety/cost gate. This module adds a state-at-operation check: it rasterizes
the planned contour with the configured brush footprint, flood-fills from the
planned seed, and rejects any region that can escape its intended row-span mask
or loses too much interior to a narrow passage.

Batch filtering simulates each candidate in a padded local ROI and updates one
global painted-state mask in place. This preserves the same discrete safety
rules while avoiding several full-canvas allocations and copies per Fill region.
Runtime CanvasGuard and post-Fill guard-pixel verification remain authoritative
against application-specific anti-aliasing and behaviour.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
import math
from typing import Any, Iterable

import numpy as np


@dataclass(frozen=True)
class FillSimulationResult:
    safe: bool
    reason: str
    intended_pixels: int
    flood_pixels: int
    contour_pixels: int
    spill_pixels: int
    missing_pixels: int
    missing_percent: float
    seed_pixel: tuple[int, int] | None
    brush_px: int
    guards_checked: int = 0

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["missing_percent"] = round(float(out["missing_percent"]), 4)
        return out


def _mask_from_spans(region: dict[str, Any], size: tuple[int, int], *, cancelled=lambda: False) -> np.ndarray:
    if cancelled():
        raise InterruptedError()
    w, h = map(int, size)
    mask = np.zeros((h, w), dtype=np.bool_)
    for index, raw in enumerate(region.get("row_spans") or ()):
        if index % 512 == 0 and cancelled():
            raise InterruptedError()
        try:
            y, x0, x1 = map(int, raw)
        except (TypeError, ValueError):
            continue
        if y < 0 or y >= h:
            continue
        if x1 < x0:
            x0, x1 = x1, x0
        x0 = max(0, x0); x1 = min(w-1, x1)
        if x0 <= x1:
            mask[y, x0:x1+1] = True
    return mask


def _line_points(a, b):
    x0, y0 = map(lambda v: int(round(float(v))), a)
    x1, y1 = map(lambda v: int(round(float(v))), b)
    dx = abs(x1-x0); sx = 1 if x0 < x1 else -1
    dy = -abs(y1-y0); sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            break
        e2 = 2*err
        if e2 >= dy:
            err += dy; x0 += sx
        if e2 <= dx:
            err += dx; y0 += sy


def _paint_square(mask: np.ndarray, x: int, y: int, brush_px: int) -> None:
    h, w = mask.shape
    b = max(1, int(brush_px))
    lo = (b-1)//2
    hi = b//2
    x0=max(0,x-lo);x1=min(w-1,x+hi)
    y0=max(0,y-lo);y1=min(h-1,y+hi)
    if x0<=x1 and y0<=y1:
        mask[y0:y1+1,x0:x1+1]=True


def _contour_wall(region: dict[str, Any], size: tuple[int, int], brush_px: int, *,
                  cancelled=lambda: False) -> np.ndarray:
    if cancelled():
        raise InterruptedError()
    w, h = map(int, size)
    wall = np.zeros((h, w), dtype=np.bool_)
    contour = tuple(region.get("contour") or ())
    if len(contour) < 4:
        return wall
    for a, b in zip(contour, contour[1:]):
        for index, (x, y) in enumerate(_line_points(a, b)):
            if index % 1024 == 0 and cancelled():
                raise InterruptedError()
            if 0 <= x < w and 0 <= y < h:
                _paint_square(wall, x, y, brush_px)
    return wall


def _flood(blank: np.ndarray, seed: tuple[int, int], intended: np.ndarray,
           *, cancelled=lambda: False) -> tuple[np.ndarray, int, bool]:
    if cancelled():
        raise InterruptedError()
    h, w = blank.shape
    sx, sy = map(int, seed)
    visited = np.zeros_like(blank)
    if not (0 <= sx < w and 0 <= sy < h) or not bool(blank[sy, sx]):
        return visited, 0, False
    q=deque([(sx,sy)]);visited[sy,sx]=True;spill=0;steps=0
    while q:
        x,y=q.popleft();steps+=1
        if steps % 2048 == 0 and cancelled():
            raise InterruptedError()
        if not bool(intended[y,x]):
            spill += 1
            return visited, spill, True
        for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if 0<=nx<w and 0<=ny<h and blank[ny,nx] and not visited[ny,nx]:
                visited[ny,nx]=True;q.append((nx,ny))
    return visited, spill, False


def simulate_fill_region(region: dict[str, Any], size: tuple[int, int], *,
                         brush_px: int = 1, painted_state: np.ndarray | None = None,
                         max_missing_percent: float = 8.0,
                         cancelled=lambda: False) -> tuple[FillSimulationResult, np.ndarray]:
    """Simulate one contour+Fill operation against the supplied discrete canvas."""
    if cancelled():
        raise InterruptedError()
    max_missing_percent = float(max_missing_percent)
    if not math.isfinite(max_missing_percent) or not 0.0 <= max_missing_percent <= 100.0:
        raise ValueError("max_missing_percent must be finite and between zero and 100")
    w,h=map(int,size)
    intended=_mask_from_spans(region,(w,h),cancelled=cancelled)
    intended_n=int(np.count_nonzero(intended))
    state=(np.asarray(painted_state,dtype=np.bool_).copy()
           if painted_state is not None else np.zeros((h,w),dtype=np.bool_))
    if state.shape != intended.shape:
        raise ValueError("painted_state shape does not match Fill canvas")
    if intended_n <= 0:
        return FillSimulationResult(False,"missing exact row-span mask",0,0,0,0,0,100.0,None,max(1,int(brush_px))),state
    contour=tuple(region.get("contour") or ())
    if len(contour) < 5 or contour[0] != contour[-1]:
        return FillSimulationResult(False,"planned contour is not a closed loop",intended_n,0,0,0,intended_n,100.0,
                                    tuple(region.get("seed_pixel") or ()) or None,max(1,int(brush_px))),state
    if np.any(state & intended):
        return FillSimulationResult(False,"Fill region overlaps already-painted state",intended_n,0,0,0,intended_n,100.0,
                                    tuple(region.get("seed_pixel") or ()) or None,max(1,int(brush_px))),state

    wall=_contour_wall(region,(w,h),brush_px,cancelled=cancelled)
    wall_n=int(np.count_nonzero(wall))
    outside_wall=wall & ~intended
    if np.any(outside_wall):
        near=np.zeros_like(intended)
        near[1:,:] |= intended[:-1,:]; near[:-1,:] |= intended[1:,:]
        near[:,1:] |= intended[:,:-1]; near[:,:-1] |= intended[:,1:]
        far=outside_wall & ~near
        if np.any(far):
            spill=int(np.count_nonzero(far))
            return FillSimulationResult(False,"contour brush footprint paints beyond the safe one-pixel boundary halo",
                                        intended_n,0,wall_n,spill,intended_n,100.0,
                                        tuple(region.get("seed_pixel") or ()) or None,max(1,int(brush_px))),state

    seed=region.get("seed_pixel")
    try:
        seed=(int(seed[0]),int(seed[1]))
    except Exception:
        return FillSimulationResult(False,"missing/invalid Fill seed",intended_n,0,wall_n,0,intended_n,100.0,None,max(1,int(brush_px))),state
    blank=~(state|wall)
    flood,spill,escaped=_flood(blank,seed,intended,cancelled=cancelled)
    flood_n=int(np.count_nonzero(flood))
    if escaped or spill:
        return FillSimulationResult(False,"stateful flood escaped the intended component",intended_n,flood_n,wall_n,
                                    max(1,spill),intended_n,100.0,seed,max(1,int(brush_px))),state

    covered=(flood|wall)&intended
    missing=int(np.count_nonzero(intended & ~covered))
    missing_pct=missing/max(1,intended_n)*100.0
    guards=0
    for raw in region.get("guard_pixels") or ():
        try:gx,gy=map(int,raw)
        except Exception:continue
        if 0<=gx<w and 0<=gy<h:
            guards+=1
            if flood[gy,gx]:
                return FillSimulationResult(False,"outside guard pixel became flood-connected",intended_n,flood_n,wall_n,
                                            1,missing,missing_pct,seed,max(1,int(brush_px)),guards),state
    if missing_pct > max_missing_percent:
        return FillSimulationResult(False,"narrow passage/brush footprint removes too much intended interior",
                                    intended_n,flood_n,wall_n,0,missing,missing_pct,seed,max(1,int(brush_px)),guards),state

    if cancelled():
        raise InterruptedError()
    new_state=state.copy()
    new_state |= wall
    new_state |= flood
    return FillSimulationResult(True,"closed contour remains bounded in current canvas state",intended_n,flood_n,wall_n,
                                0,missing,missing_pct,seed,max(1,int(brush_px)),guards),new_state


def _region_roi(region: dict[str, Any], size: tuple[int,int], brush_px: int) -> tuple[int,int,int,int]:
    """Return an exclusive padded ROI that cannot hide a one-step Fill escape."""
    w,h=map(int,size);xs=[];ys=[]
    for raw in region.get("row_spans") or ():
        try:y,x0,x1=map(int,raw)
        except (TypeError,ValueError):continue
        xs.extend((x0,x1));ys.append(y)
    for raw in region.get("contour") or ():
        try:x,y=map(lambda value:int(round(float(value))),raw)
        except (TypeError,ValueError):continue
        xs.append(x);ys.append(y)
    for key in ("seed_pixel",):
        raw=region.get(key)
        try:x,y=map(int,raw)
        except (TypeError,ValueError):continue
        xs.append(x);ys.append(y)
    for raw in region.get("guard_pixels") or ():
        try:x,y=map(int,raw)
        except (TypeError,ValueError):continue
        xs.append(x);ys.append(y)
    if not xs or not ys:
        return (0,0,w,h)
    pad=max(3,(max(1,int(brush_px))+1)//2+2)
    x0=max(0,min(xs)-pad);y0=max(0,min(ys)-pad)
    x1=min(w,max(xs)+pad+1);y1=min(h,max(ys)+pad+1)
    if x1<=x0 or y1<=y0:return (0,0,w,h)
    return x0,y0,x1,y1


def _local_region(region: dict[str,Any], x0: int, y0: int) -> dict[str,Any]:
    """Translate only simulation geometry; all other metadata stays untouched."""
    out=dict(region)
    spans=[]
    for raw in region.get("row_spans") or ():
        try:y,left,right=map(int,raw)
        except (TypeError,ValueError):continue
        spans.append((y-y0,left-x0,right-x0))
    out["row_spans"]=spans
    contour=[]
    for raw in region.get("contour") or ():
        try:x,y=raw;contour.append((int(round(float(x)))-x0,int(round(float(y)))-y0))
        except (TypeError,ValueError):continue
    out["contour"]=contour
    seed=region.get("seed_pixel")
    try:out["seed_pixel"]=(int(seed[0])-x0,int(seed[1])-y0)
    except Exception:pass
    guards=[]
    for raw in region.get("guard_pixels") or ():
        try:x,y=map(int,raw);guards.append((x-x0,y-y0))
        except (TypeError,ValueError):continue
    out["guard_pixels"]=guards
    return out


def filter_stateful_fill_regions(regions: Iterable[dict[str, Any]], size: tuple[int, int], *,
                                 brush_px: int = 1, cancelled=lambda: False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if cancelled():
        raise InterruptedError()
    rows=list(regions or ());w,h=map(int,size)
    accepted=[];rejected=[];state=np.zeros((h,w),dtype=np.bool_)
    peak_roi_pixels=0;total_roi_pixels=0
    for serial,raw in enumerate(rows):
        if cancelled():raise InterruptedError()
        region=dict(raw);x0,y0,x1,y1=_region_roi(region,(w,h),brush_px)
        roi_w=max(1,x1-x0);roi_h=max(1,y1-y0);roi_pixels=roi_w*roi_h
        peak_roi_pixels=max(peak_roi_pixels,roi_pixels);total_roi_pixels+=roi_pixels
        local=_local_region(region,x0,y0)
        # state[y0:y1,x0:x1] is a view; simulate_fill_region copies only this ROI,
        # never the whole canvas. Safe results are committed back in place.
        result,next_local_state=simulate_fill_region(
            local,(roi_w,roi_h),brush_px=brush_px,
            painted_state=state[y0:y1,x0:x1],cancelled=cancelled)
        simulation=result.as_dict()
        if simulation.get("seed_pixel") is not None:
            sx,sy=simulation["seed_pixel"];simulation["seed_pixel"]=(int(sx)+x0,int(sy)+y0)
        simulation["roi"]=(x0,y0,x1,y1);simulation["roi_pixels"]=roi_pixels
        region["stateful_fill_simulation"]=simulation
        if result.safe:
            region["fill_sequence_index"]=serial
            accepted.append(region)
            state[y0:y1,x0:x1]=next_local_state
        else:
            rejected.append({"region_id":region.get("region_fill_id",serial),"reason":result.reason,
                             "spill_pixels":result.spill_pixels,"missing_percent":result.missing_percent})
    canvas_pixels=max(1,w*h)
    return accepted,{
        "enabled":True,"model":"stateful local-ROI discrete contour + flood simulation",
        "runtime_guard_authoritative":True,"input_regions":len(rows),
        "accepted_regions":len(accepted),"rejected_regions":len(rejected),
        "painted_state_pixels":int(np.count_nonzero(state)),"rejections":rejected[:24],
        "allocation_strategy":"one global state + bounded per-region ROI masks",
        "peak_roi_pixels":int(peak_roi_pixels),"total_roi_pixels":int(total_roi_pixels),
        "peak_roi_percent_of_canvas":round(peak_roi_pixels/canvas_pixels*100.0,3),
        "full_canvas_state_copies_per_region":0,
    }
