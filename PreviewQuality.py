"""Bounded native-resolution planning and viewport-only image rendering."""
from PIL import Image
from contextlib import closing
import math
from numbers import Integral
from typing import NamedTuple

from ResourceAllocation import resolve_cpu_workers


def full_preview_options(options,area):
    try:
        w,h=area
    except (TypeError,ValueError) as error:
        raise ValueError('Full preview needs two positive integer dimensions.') from error
    if any(isinstance(v,bool) or not isinstance(v,Integral) or v<1 for v in (w,h)):
        raise ValueError('Full preview needs two positive integer dimensions.')
    w,h=int(w),int(h)
    from ReleaseStabilityHardening import apply_preview_memory_limits
    budget=options.get('ram_budget_mb')
    limits=apply_preview_memory_limits(w*h,max(w,h),memory_budget_mb=512 if budget is None else budget)
    if limits.reduced:
        raise ValueError('Full-detail preview exceeds the selected memory budget. Use the normal preview or a smaller drawing area.')
    ram=limits.memory_budget_mb
    # Reserve most of the configured RAM for the planner, app and source image.
    pixel_limit=(8_000_000 if ram>=8_000_000*512/(1024*1024)
                 else int(ram*1024*1024//512))
    if w<1 or h<1 or w*h>pixel_limit:
        raise ValueError(f'Full preview exceeds its memory budget ({pixel_limit:,} target pixels). Use the normal preview or a smaller drawing area.')
    requested_workers=str(options.get('cpu_workers') or 'Auto')
    try:
        supplied=options.get('cpu_workers_resolved')
        resolved=int(supplied) if supplied not in (None,'') else resolve_cpu_workers(requested_workers)
    except (TypeError,ValueError):
        resolved=resolve_cpu_workers('Auto')
    preview_workers=max(1,min(4,int(resolved)))
    preview_mode=str(options.get('preview_mode') or options.get('_preview_mode') or 'Manual')
    out=dict(options,_full_detail_preview=True,_preview_plan=False,
             _preview_mode=preview_mode,_target_area=(w,h),_preview_area=(w,h),
             cpu_workers=str(preview_workers),cpu_workers_resolved=preview_workers,cpu_engine='Threads',gpu_mode='CPU',
             _preview_resource_policy='full-detail-planner-parity',
             _preview_resource_worker_cap=preview_workers)
    screen_area=options.get("_target_screen_area") or options.get("target_area") or options.get("_target_area")
    if isinstance(screen_area, (list,tuple)) and len(screen_area)==4:
        out["_target_screen_area"]=tuple(screen_area)
    return out


class ViewportGeometry(NamedTuple):
    scale: float
    pan: tuple[float, float]
    box: tuple[float, float, float, float]
    target: tuple[int, int]


def viewport_geometry(image_size,size,zoom=0,pan=(0,0)):
    """Resolve the exact visible source rectangle and its bounded pan offset."""
    w,h=[max(1,min(4096,int(v))) for v in size]
    iw,ih=image_size
    if iw < 1 or ih < 1:
        raise ValueError("Source image must have positive dimensions.")
    try:
        zoom=float(zoom)
    except (TypeError, ValueError, OverflowError):
        zoom=0.0
    if not math.isfinite(zoom):
        zoom=0.0
    try:
        pan=tuple(float(v) for v in pan)
        if len(pan) != 2 or not all(math.isfinite(v) for v in pan):
            pan=(0.0,0.0)
    except (TypeError, ValueError, OverflowError):
        pan=(0.0,0.0)
    scale=min(w/iw,h/ih) if zoom<=0 else max(.125,min(8,zoom))
    sw=min(iw,w/scale);sh=min(ih,h/scale)
    cx=min(iw-sw/2,max(sw/2,iw/2+float(pan[0])))
    cy=min(ih-sh/2,max(sh/2,ih/2+float(pan[1])))
    box=(cx-sw/2,cy-sh/2,cx+sw/2,cy+sh/2)
    # Resize the source region directly; convert only the bounded result.
    # In Fit mode this also avoids an RGBA copy of a huge original image.
    target=(max(1,min(w,round(sw*scale))),max(1,min(h,round(sh*scale))))
    return ViewportGeometry(scale,(cx-iw/2,cy-ih/2),box,target)


def viewport_image(image,size,zoom=0,pan=(0,0)):
    geometry=viewport_geometry(image.size,size,zoom,pan)
    with closing(image.resize(geometry.target,Image.Resampling.NEAREST if geometry.scale>=1 else Image.Resampling.LANCZOS,
                              box=geometry.box)) as resized:
        with closing(resized.convert('RGBA')) as crop:
            with closing(Image.new('RGBA',geometry.target,'white')) as out:
                out.alpha_composite(crop)
                return out.convert('RGB'),geometry.scale
