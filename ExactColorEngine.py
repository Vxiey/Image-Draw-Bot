"""Exact/perceptual color analysis for Image Draw Bot v1.0.122-beta.

The module is intentionally UI-free.  It centralises source-colour statistics,
representative-colour choice and perceptual candidate scoring so preview and
final planning can share the same decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
import colorsys
import numpy as np

from ColorFidelity import color_metrics, delta_e2000, delta_e_oklab, oklab_metrics, rgb_to_lab, rgb_to_oklab

RGB = tuple[int, int, int]


def _rgb(values: Iterable[int | float]) -> RGB:
    vals=list(values)[:3]
    while len(vals)<3: vals.append(0)
    return tuple(max(0,min(255,int(round(float(v))))) for v in vals)  # type: ignore[return-value]


@dataclass(frozen=True)
class ColorRegionStats:
    region_id: int
    pixel_count: int
    mean_rgb: RGB
    median_rgb: RGB
    dominant_rgb: RGB
    representative_rgb: RGB
    representative_lab: tuple[float,float,float]
    luminance: float
    saturation: float
    hue: float
    local_contrast: float = 0.0
    importance_score: float = 0.0
    highlight_score: float = 0.0
    shadow_score: float = 0.0
    dominant_fraction: float = 0.0
    spread: float = 0.0


@dataclass(frozen=True)
class ColorCandidateScore:
    rgb: RGB
    delta_e2000: float
    lightness_error: float
    saturation_error: float
    hue_error: float
    darkening_penalty: float
    total_cost: float
    oklab_distance: float = 0.0


def _dominant_exact(px: np.ndarray) -> tuple[RGB,float]:
    if len(px)==0: return (0,0,0),0.0
    packed=(px[:,0].astype(np.uint32)<<16)|(px[:,1].astype(np.uint32)<<8)|px[:,2].astype(np.uint32)
    values,counts=np.unique(packed,return_counts=True)
    pos=int(np.argmax(counts));v=int(values[pos]);n=int(counts[pos])
    return ((v>>16)&255,(v>>8)&255,v&255),n/max(1,len(px))


def analyze_region_pixels(pixels, *, region_id: int=0, importance_score: float=0.0,
                          local_contrast: float=0.0) -> ColorRegionStats:
    px=np.asarray(pixels,dtype=np.uint8).reshape(-1,3)
    if len(px)==0:
        rgb=(0,0,0)
        return ColorRegionStats(region_id,0,rgb,rgb,rgb,rgb,rgb_to_lab(rgb),0.0,0.0,0.0,
                                float(local_contrast),float(importance_score),0.0,0.0,0.0,0.0)
    mean=_rgb(np.mean(px,axis=0));dominant,dom_frac=_dominant_exact(px)
    p10,median_values,p90=np.percentile(px,(10,50,90),axis=0)
    median=_rgb(median_values);spread=float(np.max(p90-p10))
    representative=select_representative_color(px, mean_rgb=mean, median_rgb=median,
                                                dominant_rgb=dominant, dominant_fraction=dom_frac,
                                                spread=spread, importance_score=importance_score)
    L,s,h,Y=color_metrics(representative)
    highlight=max(0.0,min(1.0,(L-68.0)/25.0))*(0.55+0.45*max(0.0,min(1.0,importance_score)))
    shadow=max(0.0,min(1.0,(38.0-L)/28.0))
    return ColorRegionStats(int(region_id),len(px),mean,median,dominant,representative,
                            rgb_to_lab(representative),float(Y),float(s),float(h),float(local_contrast),
                            float(importance_score),float(highlight),float(shadow),float(dom_frac),spread)


def _nearest_actual(px: np.ndarray, target: RGB) -> RGB:
    if len(px)==0:return target
    # An exact source color must not disappear because it was near the end of
    # the source region. Search in bounded strips before approximate sampling.
    target_array=np.asarray(target,dtype=np.uint8)
    for start in range(0,len(px),8192):
        if np.any(np.all(px[start:start+8192]==target_array,axis=1)):
            return tuple(target)
    work=px if len(px)<=8192 else px[np.linspace(0,len(px)-1,8192,dtype=np.int64)]
    # perceptual candidate refinement only over real source pixels
    candidates=np.unique(work,axis=0)
    if len(candidates)>2048:candidates=candidates[np.linspace(0,len(candidates)-1,2048,dtype=np.int64)]
    # Reuse canonical cached color conversions, then reduce the distance
    # vector once instead of repeatedly normalizing the same target RGB.
    labs=np.asarray([rgb_to_oklab(tuple(map(int,row))) for row in candidates],dtype=np.float64)
    delta=labs-np.asarray(rgb_to_oklab(tuple(target)),dtype=np.float64)
    scores=np.sum(delta*delta,axis=1)
    return tuple(map(int,candidates[int(np.argmin(scores))]))


def select_representative_color(pixels, *, mean_rgb: RGB|None=None, median_rgb: RGB|None=None,
                                dominant_rgb: RGB|None=None, dominant_fraction: float|None=None,
                                spread: float|None=None, importance_score: float=0.0) -> RGB:
    """Select a source-backed representative without washing out small important colors."""
    px=np.asarray(pixels,dtype=np.uint8).reshape(-1,3)
    if len(px)==0:return (0,0,0)
    mean=mean_rgb or _rgb(np.mean(px,axis=0));median=median_rgb or _rgb(np.median(px,axis=0))
    if dominant_rgb is None or dominant_fraction is None:
        dominant_rgb,dominant_fraction=_dominant_exact(px)
    if spread is None:
        p10,p90=np.percentile(px,(10,90),axis=0)
        spread=float(np.max(p90-p10))
    # Important/tiny accents keep a real dominant color sooner than broad noisy regions.
    dom_threshold=max(0.10,0.22-0.08*max(0.0,min(1.0,float(importance_score))))
    if float(dominant_fraction)>=dom_threshold:
        return tuple(map(int,dominant_rgb))
    if float(spread)>=48:
        target=median
    else:
        target=_rgb(tuple(median[i]*0.65+mean[i]*0.35 for i in range(3)))
    return _nearest_actual(px,target)


def _hue_error(h1: float,h2: float,s1: float,s2: float) -> float:
    if min(s1,s2)<6.0:return 0.0
    d=abs(h1-h2)%360.0
    return min(d,360.0-d)


def _candidate_components(source, candidate, fidelity, importance, shadow):
    src=_rgb(source);dst=_rgb(candidate)
    sL,sC,sH=oklab_metrics(src);dL,dC,dH=oklab_metrics(dst)
    oklab=delta_e_oklab(src,dst)
    light=abs(sL-dL);chroma=abs(sC-dC);hue=_hue_error(sH,dH,sC,dC)
    dark=max(0.0,sL-dL)
    bright_boost=1.0+max(0.0,sL-55.0)/36.0
    importance_boost=1.0+0.65*max(0.0,min(1.0,float(importance)))
    if shadow:
        weights=(1.0,0.34,0.20,0.030,0.34)
    elif fidelity=='Fast':
        weights=(1.0,0.05,0.02,0.006,0.08)
    elif fidelity=='Balanced':
        weights=(1.0,0.16,0.07,0.015,0.30)
    elif fidelity=='Exact':
        weights=(1.0,0.0,0.0,0.0,0.0)
    else:
        weights=(1.0,0.30,0.13,0.032,0.62)
    dark_penalty=dark*weights[4]*bright_boost*importance_boost
    family_penalty=0.0
    if fidelity not in ('Fast','Exact') and sC>=5.0:
        if dC < max(2.5,sC*.28):
            family_penalty+=(sC-dC)*(0.18 if fidelity=='Balanced' else 0.32)
        if hue>45.0:
            family_penalty+=(hue-45.0)*(0.035 if fidelity=='Balanced' else 0.080)
            if hue>85.0:
                family_penalty+=(hue-85.0)*(0.060 if fidelity=='Balanced' else 0.120)
    total=oklab*weights[0]+light*weights[1]+chroma*weights[2]+hue*weights[3]+dark_penalty+family_penalty
    return src,dst,light,chroma,hue,dark_penalty,float(total),float(oklab)


def candidate_cost(source: Sequence[int], candidate: Sequence[int], *, fidelity: str='Faithful',
                   importance: float=0.0, shadow: bool=False) -> float:
    """Return the matching cost without computing unused CIEDE2000 diagnostics."""
    return _candidate_components(source,candidate,fidelity,importance,shadow)[6]


def score_candidate(source: Sequence[int], candidate: Sequence[int], *, fidelity: str='Faithful',
                    importance: float=0.0, shadow: bool=False) -> ColorCandidateScore:
    """Score in OKLab and include CIEDE2000 for diagnostics and legacy tie breaks."""
    src,dst,light,chroma,hue,dark_penalty,total,oklab=_candidate_components(
        source,candidate,fidelity,importance,shadow)
    return ColorCandidateScore(dst,delta_e2000(src,dst),light,chroma,hue,dark_penalty,total,oklab)

def best_candidate(source: Sequence[int], candidates: Sequence[Sequence[int]], *, fidelity: str='Faithful',
                   importance: float=0.0, shadow: bool=False) -> tuple[int,ColorCandidateScore]:
    if not candidates:raise ValueError('No color candidates are available.')
    scored=[(i,score_candidate(source,c,fidelity=fidelity,importance=importance,shadow=shadow)) for i,c in enumerate(candidates)]
    return min(scored,key=lambda item:(item[1].total_cost,item[1].delta_e2000,item[0]))
