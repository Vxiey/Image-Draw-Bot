"""Advanced source-image colour measurement for Image Draw Bot.

The engine measures real source pixels before Paint palette selection.  It keeps
mean, median and dominant RGB statistics for each quantized colour region and
chooses a robust representative that is resistant to antialiasing/noise while
remaining very close to an RGB value that actually exists in the source image.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

import numpy as np
from PIL import Image
from ExactColorEngine import select_representative_color

RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class ColorSample:
    rgb: RGB
    mean_rgb: RGB
    median_rgb: RGB
    dominant_rgb: RGB
    dominant_fraction: float
    spread: float
    count: int
    alpha_mean: float = 255.0
    alpha_median: float = 255.0

    def as_dict(self):
        return {
            'rgb': tuple(self.rgb),
            'mean_rgb': tuple(self.mean_rgb),
            'median_rgb': tuple(self.median_rgb),
            'dominant_rgb': tuple(self.dominant_rgb),
            'dominant_fraction': round(float(self.dominant_fraction), 4),
            'spread': round(float(self.spread), 3),
            'count': int(self.count),
            'alpha_mean': round(float(self.alpha_mean), 2),
            'alpha_median': round(float(self.alpha_median), 2),
        }


def _rgb_tuple(values) -> RGB:
    values=np.asarray(values,dtype=float).reshape(-1)[:3]
    return tuple(int(max(0,min(255,round(float(v))))) for v in values)  # type: ignore[return-value]


def visible_rgb_image(image: Image.Image, background: RGB=(255,255,255)) -> Image.Image:
    """Return the RGB pixels the user actually sees, including alpha compositing."""
    if image.mode == 'RGB' and 'transparency' not in image.info:
        return image.copy()
    rgba=image.convert('RGBA')
    if rgba.getextrema()[3] == (255,255):
        return rgba.convert('RGB')
    backdrop=Image.new('RGBA',rgba.size,tuple(background)+(255,))
    backdrop.alpha_composite(rgba)
    return backdrop.convert('RGB')


def _dominant_exact(pixels: np.ndarray) -> tuple[RGB,float]:
    if len(pixels)==0:
        return (0,0,0),0.0
    packed=(pixels[:,0].astype(np.uint32)<<16) | (pixels[:,1].astype(np.uint32)<<8) | pixels[:,2].astype(np.uint32)
    values,counts=np.unique(packed,return_counts=True)
    pos=int(np.argmax(counts));value=int(values[pos]);count=int(counts[pos])
    rgb=((value>>16)&255,(value>>8)&255,value&255)
    return rgb,count/max(1,len(pixels))


def _nearest_actual_rgb(pixels: np.ndarray, target: RGB, max_candidates: int=8192) -> RGB:
    """Snap a robust statistic to a real source pixel so we never invent a wild colour."""
    if len(pixels)==0:
        return tuple(target)
    if len(pixels)>max_candidates:
        step=max(1,len(pixels)//max_candidates)
        work=pixels[::step][:max_candidates]
    else:
        work=pixels
    t=np.asarray(target,dtype=np.int32)
    delta=work.astype(np.int32)-t
    # Perceptual-ish RGB weights; still cheap enough for planning.
    score=delta[:,0]*delta[:,0]*30 + delta[:,1]*delta[:,1]*59 + delta[:,2]*delta[:,2]*11
    return tuple(map(int,work[int(np.argmin(score)),:3]))


def measure_color_pixels(pixels: np.ndarray, *, alpha_values: np.ndarray | None=None) -> ColorSample:
    """Measure mean, median, dominant and a robust source-backed representative RGB."""
    px=np.asarray(pixels,dtype=np.uint8).reshape(-1,3)
    if len(px)==0:
        return ColorSample((0,0,0),(0,0,0),(0,0,0),(0,0,0),0.0,0.0,0)
    mean=_rgb_tuple(np.mean(px,axis=0))
    p10,median_values,p90=np.percentile(px,(10,50,90),axis=0)
    median=_rgb_tuple(median_values)
    dominant,dominant_fraction=_dominant_exact(px)
    spread=float(np.max(p90-p10))

    # Flat artwork/UI colours should stay exactly on the dominant source RGB.
    # Noisy/photographic regions use a median/mean blend, then snap to an actual
    # pixel from that region to avoid a representative colour that never existed.
    robust=select_representative_color(px,mean_rgb=mean,median_rgb=median,
                                       dominant_rgb=dominant,dominant_fraction=dominant_fraction,
                                       spread=spread,importance_score=0.0)

    alpha_mean=255.0;alpha_median=255.0
    if alpha_values is not None:
        aa=np.asarray(alpha_values,dtype=np.uint8).reshape(-1)
        if len(aa):
            alpha_mean=float(np.mean(aa));alpha_median=float(np.median(aa))
    return ColorSample(tuple(map(int,robust)),mean,median,dominant,float(dominant_fraction),spread,len(px),alpha_mean,alpha_median)


def measure_quantized_regions(source: Image.Image, labels: Image.Image) -> Dict[int,ColorSample]:
    """Measure the real RGB pixels assigned to every quantizer label."""
    if source.size!=labels.size:
        raise ValueError('Source image and color labels must have the same size.')
    visible=np.asarray(visible_rgb_image(source),dtype=np.uint8)
    lab=np.asarray(labels,dtype=np.int32)
    if lab.ndim != 2:
        raise ValueError('Color labels must be a single-channel image.')
    alpha = None
    if source.mode != 'RGB' or 'transparency' in source.info:
        alpha = np.asarray(source.convert('RGBA').getchannel('A'),dtype=np.uint8).reshape(-1)
    result: Dict[int,ColorSample]={}
    # Stable grouping preserves each region's source order, including the
    # bounded representative sampler, without rescanning the image per label.
    flat = lab.reshape(-1)
    order = np.argsort(flat, kind='stable')
    sorted_labels = flat[order]
    boundaries = np.flatnonzero(sorted_labels[1:] != sorted_labels[:-1]) + 1
    visible = visible.reshape(-1,3)
    for indices in np.split(order,boundaries):
        if len(indices):
            result[int(flat[indices[0]])] = measure_color_pixels(
                visible[indices], alpha_values=None if alpha is None else alpha[indices])
    return result


def rgb_error(actual: Iterable[int], expected: Iterable[int]) -> float:
    a=np.asarray(tuple(actual)[:3],dtype=float);e=np.asarray(tuple(expected)[:3],dtype=float)
    if a.size<3 or e.size<3:return float('inf')
    d=a-e
    return float((d[0]*d[0]*.30+d[1]*d[1]*.59+d[2]*d[2]*.11)**.5)


def preview_matches(actual: Iterable[int] | None, expected: Iterable[int], tolerance: float=16.0) -> bool:
    if actual is None:return False
    return rgb_error(actual,expected)<=float(tolerance)
