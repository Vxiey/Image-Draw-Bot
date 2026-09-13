"""Automatic pixel brush-width selection for Image Draw Bot.

The selector is deliberately conservative. It chooses a baseline from the
actual image and target canvas, while AdaptiveBrushEngine may still select
smaller verified brushes for contours/details/corrections. No mouse input is
performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageFilter, ImageStat


@dataclass(frozen=True)
class AutoBrushDecision:
    brush_px: int
    classification: str
    edge_density: float
    color_complexity: float
    target_size: tuple[int, int]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            'brush_px': int(self.brush_px),
            'classification': str(self.classification),
            'edge_density': round(float(self.edge_density),4),
            'color_complexity': round(float(self.color_complexity),4),
            'target_size': tuple(map(int,self.target_size)),
            'reason': str(self.reason),
        }


def _target_size(image: Image.Image, target_size=None) -> tuple[int,int]:
    try:
        w,h=map(int,target_size)
        if w>0 and h>0:return w,h
    except Exception:
        pass
    return max(1,int(image.width)),max(1,int(image.height))


def _metrics(image: Image.Image) -> tuple[float,float]:
    rgb=image.convert('RGB')
    w=max(24,min(144,rgb.width));h=max(24,min(144,rgb.height))
    sample=rgb.resize((w,h),Image.Resampling.BILINEAR)
    edge=float(ImageStat.Stat(sample.convert('L').filter(ImageFilter.FIND_EDGES)).mean[0])/255.0
    palette=rgb.resize((w,h),Image.Resampling.NEAREST).quantize(colors=32,method=Image.Quantize.MEDIANCUT)
    used=sum(1 for value in palette.histogram() if value)
    colors=min(1.0,used/32.0)
    return max(0.0,min(1.0,edge)),max(0.0,min(1.0,colors))


def resolve_brush_width(image: Image.Image | None, *, target_size=None,
                        draw_quality: str='', render_preset: str='', render_style: str='',
                        outline: bool=False, subject_focus: str='Off', profile_key: str='',
                        speed: str='', quality: str='') -> AutoBrushDecision:
    if image is None:
        return AutoBrushDecision(1,'safe-default',0.0,0.0,(1,1),'No image is loaded; use the safest 1 px baseline.')
    target=_target_size(image,target_size)
    area=max(1,target[0]*target[1]);longest=max(target)
    dq=str(draw_quality or '')
    if 'Pixel Accurate' in dq:
        return AutoBrushDecision(1,'pixel-accurate',1.0,1.0,target,'Pixel Accurate keeps a 1 px baseline for exact source geometry.')
    if outline or str(subject_focus or 'Off')!='Off':
        return AutoBrushDecision(1,'protected-detail',1.0,1.0,target,'Outline/subject-preserving drawing uses the finest baseline.')

    edge,color=_metrics(image)
    detail_score=min(1.0,edge*.72+color*.28)
    if longest<=520:base=1
    elif longest<=900:base=2
    elif longest<=1400:base=3
    elif longest<=2000:base=4
    else:base=5

    classification='balanced';reason='Balanced baseline from target pixel dimensions and image complexity.'
    if detail_score>=.40:
        base=max(1,base-1);classification='detail-heavy'
        reason='High edge/color complexity: use a smaller baseline to preserve details.'
    elif detail_score<=.17 and area>=220_000:
        base=min(7,base+1);classification='flat-shape'
        reason='Large simple color regions: a wider baseline is safe and faster.'

    if str(render_preset or '')=='Extra fast' and classification!='detail-heavy':
        base=min(7,base+1);reason+=' Extra fast permits one wider safe level.'
    if str(quality or '') in ('Best','Ultra') or dq in ('High likeness','Maximum likeness'):
        base=max(1,base-1);reason+=' High-likeness quality nudges the baseline finer.'
    if str(render_style or '')=='Portrait / shaded':
        base=max(1,base-1);reason+=' Portrait/shaded rendering protects fine facial and tonal structure.'

    # Microsoft Paint supports a wide size slider, but very large Pencil sizes
    # are destructive for automatic image recreation. Keep Auto conservative.
    key=str(profile_key or '').lower()
    if key=='microsoft-paint':cap=6
    elif key in ('gartic-phone','gartic-io'):cap=5
    else:cap=8
    base=max(1,min(cap,int(base)))
    return AutoBrushDecision(base,classification,edge,color,target,reason)
