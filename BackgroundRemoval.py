"""Safe, dependency-light background removal for Image Draw Bot.

Only border-connected background pixels are made transparent. The existing
PixelData planner already treats alpha=0 as an empty pixel, so removed background
creates no strokes and directly reduces planned drawing work.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Any, Callable
from PIL import Image, ImageFilter, ImageOps, ImageStat

MODES=("Auto","Light background","Dark background","Corner color")
STRENGTHS=("Conservative","Balanced","Aggressive")


def validate_mode(value:Any)->str:
    value=str(value or "Auto")
    if value not in MODES:raise ValueError("Invalid background removal mode.")
    return value


def validate_strength(value:Any)->str:
    value=str(value or "Balanced")
    if value not in STRENGTHS:raise ValueError("Invalid background removal strength.")
    return value


def _distance(a,b):
    dr=float(a[0])-b[0];dg=float(a[1])-b[1];db=float(a[2])-b[2]
    return sqrt(.30*dr*dr+.59*dg*dg+.11*db*db)


def _luma(p):return .2126*p[0]+.7152*p[1]+.0722*p[2]


def _median(samples):
    if not samples:return (255,255,255)
    return tuple(sorted(int(p[c]) for p in samples)[len(samples)//2] for c in range(3))


def _edge_samples(rgb):
    w,h=rgb.size;step=max(1,min(w,h)//96);out=[]
    for x in range(0,w,step):out.extend((rgb.getpixel((x,0)),rgb.getpixel((x,h-1))))
    for y in range(step,h-1,step):out.extend((rgb.getpixel((0,y)),rgb.getpixel((w-1,y))))
    return [tuple(map(int,p[:3])) for p in out]


def _corners(rgb):
    w,h=rgb.size;r=max(1,min(12,min(w,h)//20));out=[]
    for box in ((0,0,r,r),(w-r,0,w,r),(0,h-r,r,h),(w-r,h-r,w,h)):
        mean=ImageStat.Stat(rgb.crop(box)).mean[:3]
        out.append(tuple(int(round(v)) for v in mean))
    return out


def _reference(rgb,mode):
    edge=_edge_samples(rgb);corners=_corners(rgb);ref=_median(corners)
    if mode=="Light background":ref=_median([p for p in edge if _luma(p)>=190] or edge)
    elif mode=="Dark background":ref=_median([p for p in edge if _luma(p)<=65] or edge)
    distances=sorted(_distance(p,ref) for p in edge)
    p75=distances[int(.75*(len(distances)-1))] if distances else 0.0
    return ref,p75


def _threshold(strength,ref,spread):
    value={"Conservative":18.0,"Balanced":28.0,"Aggressive":42.0}[strength]
    value+=min(12.0,max(0.0,spread-5.0)*.35)
    if _luma(ref)>=238 or _luma(ref)<=18:value+=5
    return max(10.0,min(58.0,value))


def _match(p,ref,limit,mode):
    if _distance(p,ref)>limit:return False
    if mode=="Light background" and _luma(p)<150:return False
    if mode=="Dark background" and _luma(p)>105:return False
    return True


def _connected_mask(rgb,ref,limit,mode,cancelled):
    w,h=rgb.size;pix=rgb.load();seen=bytearray(w*h);mask=bytearray(w*h);q=deque()
    def add(x,y):
        i=y*w+x
        if seen[i]:return
        seen[i]=1
        if _match(pix[x,y],ref,limit,mode):mask[i]=1;q.append(i)
    for x in range(w):add(x,0);add(x,h-1)
    for y in range(1,h-1):add(0,y);add(w-1,y)
    count=0
    while q:
        i=q.popleft();y,x=divmod(i,w);count+=1
        if count%4096==0 and cancelled():raise InterruptedError()
        if x:add(x-1,y)
        if x+1<w:add(x+1,y)
        if y:add(x,y-1)
        if y+1<h:add(x,y+1)
    return mask,count


@dataclass(frozen=True)
class BackgroundRemovalResult:
    image:Image.Image
    metadata:dict


def remove_background(image:Image.Image,*,mode="Auto",strength="Balanced",feather_px=.6,
                      cancelled:Callable[[],bool]=lambda:False)->BackgroundRemovalResult:
    mode=validate_mode(mode);strength=validate_strength(strength)
    source=ImageOps.exif_transpose(image).convert("RGBA");w,h=source.size;total=max(1,w*h)
    old_alpha=source.getchannel("A").tobytes();before=sum(1 for a in old_alpha if a>8)
    rgb=source.convert("RGB");ref,spread=_reference(rgb,mode);limit=_threshold(strength,ref,spread)
    mask,count=_connected_mask(rgb,ref,limit,mode,cancelled)
    no_op=None
    if count/total>.985:
        mask=bytearray(total);no_op="candidate background exceeded 98.5%; original preserved"
    alpha=bytearray(old_alpha)
    for i,bg in enumerate(mask):
        if bg:alpha[i]=0
    alpha_img=Image.frombytes("L",(w,h),bytes(alpha))
    if any(mask) and feather_px:
        alpha_img=alpha_img.filter(ImageFilter.GaussianBlur(radius=max(.1,min(1.2,float(feather_px)))))
        softened=bytearray(alpha_img.tobytes())
        for i,bg in enumerate(mask):
            if bg:softened[i]=0
        alpha_img=Image.frombytes("L",(w,h),bytes(softened))
    result=source.copy();result.putalpha(alpha_img)
    after=sum(1 for a in alpha_img.tobytes() if a>8)
    removed=max(0,before-after);reduction=100.0*removed/max(1,before)
    bbox=alpha_img.getbbox()
    return BackgroundRemovalResult(result,{
        "mode":mode,"strength":strength,"reference_rgb":list(ref),"threshold":round(limit,2),
        "removed_pixels":removed,"removed_percent":round(100.0*removed/total,2),
        "estimated_work_reduction_percent":round(reduction,2),"drawable_after_percent":round(100.0*after/total,2),
        "foreground_bbox":list(bbox) if bbox else None,"no_op_reason":no_op,
        "method":"border-connected background to transparent alpha"
    })


def png_export_ready(image:Image.Image)->Image.Image:
    return ImageOps.exif_transpose(image).convert("RGBA")
