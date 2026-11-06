"""Sketch 2.0 structure extraction for Image Draw Bot v1.0.131-beta.

Paint-first deterministic planner. It combines luminance and colour-boundary
edges, protects small high-contrast components and removes isolated noise. It
contains no native input, AI, ML or OCR. Browser/Gartic sketch routing remains
in the legacy SketchPlanner/GarticSketchPaths path.
"""
from __future__ import annotations

from collections import deque
from typing import Callable
import numpy as np
from PIL import Image, ImageFilter

SKETCH2_DETAILS=("Simple","Balanced","Detailed")

_PROFILES={
    "Simple": dict(blur=1.8, percentile=82.0, floor=34.0, min_component=10, protect_factor=1.75),
    "Balanced": dict(blur=1.25, percentile=77.0, floor=27.0, min_component=6, protect_factor=1.60),
    "Detailed": dict(blur=.85, percentile=72.0, floor=20.0, min_component=3, protect_factor=1.45),
}


def _flatten(image: Image.Image) -> Image.Image:
    rgba=image.convert('RGBA')
    flat=Image.new('RGBA',rgba.size,'white');flat.alpha_composite(rgba)
    return flat.convert('RGB')


def _nms(mag: np.ndarray, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    angle=(np.rad2deg(np.arctan2(gy,gx))+180.0)%180.0
    out=np.zeros_like(mag,dtype=np.float32)
    bins=(np.round(angle/45.0).astype(np.int16))%4
    dirs=((0,1),(1,1),(1,0),(1,-1))
    for b,(dy,dx) in enumerate(dirs):
        m=bins==b
        a=np.roll(mag,(dy,dx),(0,1));c=np.roll(mag,(-dy,-dx),(0,1))
        keep=m & (mag>=a) & (mag>=c)
        out[keep]=mag[keep]
    out[[0,-1],:]=0;out[:,[0,-1]]=0
    return out


def _filter_components(mask: np.ndarray, strength: np.ndarray, threshold: float,
                       *, min_component: int, protect_factor: float,
                       cancelled: Callable[[],bool]) -> tuple[np.ndarray,int,int]:
    h,w=mask.shape;seen=np.zeros_like(mask,dtype=bool);out=mask.copy()
    removed=0;protected=0
    for y in range(h):
        if cancelled():raise InterruptedError()
        for x in range(w):
            if not mask[y,x] or seen[y,x]:continue
            q=deque([(y,x)]);seen[y,x]=True;cells=[];peak=0.0
            while q:
                cy,cx=q.popleft();cells.append((cy,cx));peak=max(peak,float(strength[cy,cx]))
                if len(cells) % 512 == 0 and cancelled():
                    raise InterruptedError()
                for dy in (-1,0,1):
                    for dx in (-1,0,1):
                        if not (dx or dy):continue
                        ny,nx=cy+dy,cx+dx
                        if 0<=ny<h and 0<=nx<w and mask[ny,nx] and not seen[ny,nx]:
                            seen[ny,nx]=True;q.append((ny,nx))
            keep=len(cells)>=min_component or (len(cells)>=2 and peak>=threshold*protect_factor)
            if keep:
                if len(cells)<min_component:protected+=1
            else:
                removed+=1
                for cy,cx in cells:out[cy,cx]=False
    return out,removed,protected


def structure_map(image: Image.Image, cancelled=lambda:False, detail='Detailed'):
    if detail not in SKETCH2_DETAILS:
        raise ValueError('Choose Simple, Balanced or Detailed sketch detail.')
    if cancelled():
        raise InterruptedError()
    if max(image.size)>1500:
        raise ValueError('Sketch 2.0 source is too large for the bounded structure pass.')
    cfg=_PROFILES[detail]
    flat=_flatten(image)
    smooth=flat.filter(ImageFilter.GaussianBlur(cfg['blur']))
    arr=np.asarray(smooth,dtype=np.float32)
    lum=arr[:,:,0]*.2126+arr[:,:,1]*.7152+arr[:,:,2]*.0722
    # Central differences. Colour-boundary magnitude deliberately remains
    # independent of luminance so equal-brightness red/blue boundaries survive.
    lx=np.zeros_like(lum);ly=np.zeros_like(lum)
    lx[:,1:-1]=lum[:,2:]-lum[:,:-2];ly[1:-1,:]=lum[2:,:]-lum[:-2,:]
    lum_mag=np.hypot(lx,ly)
    cx=np.zeros_like(arr);cy=np.zeros_like(arr)
    cx[:,1:-1,:]=arr[:,2:,:]-arr[:,:-2,:];cy[1:-1,:,:]=arr[2:,:,:]-arr[:-2,:,:]
    color_mag=np.sqrt(np.max(cx*cx+cy*cy,axis=2))
    # Strong luminance edges remain primary; chromatic edges supplement them.
    combined=lum_mag*.78+color_mag*.46
    gx=lx + (cx[:,:,0]-cx[:,:,2])*.10
    gy=ly + (cy[:,:,0]-cy[:,:,2])*.10
    thin=_nms(combined,gx,gy)
    active=thin[thin>0]
    threshold=max(float(cfg['floor']),float(np.percentile(active,cfg['percentile'])) if active.size else 255.0)
    mask=thin>=threshold
    # Micro-detail protection uses the unblurred source only for very strong
    # local boundaries. This recovers tiny eyes/symbols/corners that Gaussian
    # smoothing can erase, without turning ordinary low-contrast texture into
    # sketch noise.
    raw=np.asarray(flat,dtype=np.float32)
    raw_lum=raw[:,:,0]*.2126+raw[:,:,1]*.7152+raw[:,:,2]*.0722
    rgx=np.zeros_like(raw_lum);rgy=np.zeros_like(raw_lum)
    rgx[:,1:-1]=raw_lum[:,2:]-raw_lum[:,:-2];rgy[1:-1,:]=raw_lum[2:,:]-raw_lum[:-2,:]
    rcx=np.zeros_like(raw);rcy=np.zeros_like(raw)
    rcx[:,1:-1,:]=raw[:,2:,:]-raw[:,:-2,:];rcy[1:-1,:,:]=raw[2:,:,:]-raw[:-2,:,:]
    raw_strength=np.hypot(rgx,rgy)*.72 + np.sqrt(np.max(rcx*rcx+rcy*rcy,axis=2))*.40
    micro_threshold=max(88.0,threshold*1.18)
    micro=raw_strength>=micro_threshold
    micro[[0,-1],:]=False;micro[:,[0,-1]]=False
    mask|=micro
    strength=np.maximum(thin,raw_strength)
    mask,removed,protected=_filter_components(mask,strength,threshold,
        min_component=int(cfg['min_component']),protect_factor=float(cfg['protect_factor']),cancelled=cancelled)
    lum_only=lum_mag>=threshold
    color_only=(color_mag*.46>=threshold*.55)&(~lum_only)&mask
    if cancelled():
        raise InterruptedError()
    meta={
        'engine':'Sketch 2.0','detail':detail,'threshold':round(threshold,3),
        'ink_pixels':int(mask.sum()),'luminance_edge_pixels':int((mask&lum_only).sum()),
        'color_boundary_pixels':int(color_only.sum()),'removed_noise_components':int(removed),
        'protected_small_components':int(protected),'ai_ml_ocr':False,
    }
    return mask,meta


def contour_image_v2(image: Image.Image, cancelled=lambda:False, detail='Detailed'):
    mask,meta=structure_map(image,cancelled,detail)
    out=np.full(mask.shape,255,dtype=np.uint8);out[mask]=0
    return Image.fromarray(out,'L').convert('RGBA'),meta
