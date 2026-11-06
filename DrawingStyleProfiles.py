"""Drawing-style profiles for Image Draw Bot.

These profiles tune the existing planner; they do not replace target profiles or
calibration.  A style may change geometry, quality, brush/fill policy and opacity,
while target-specific safety/CanvasGuard remains authoritative.
"""
from __future__ import annotations

from typing import Any
from contextlib import ExitStack, closing
from ImageGeometry import thumbnail_size

import numpy as np
from PIL import Image, ImageFilter, ImageStat

DRAWING_STYLES=(
    'Auto',
    'Pixel Art',
    'Logo / Flat Graphic',
    'Portrait',
    'Photo / Shaded',
    'Line Art',
    'Cartoon / Illustration',
)


def validate_drawing_style(value: Any) -> str:
    value=str(value or 'Auto')
    if value not in DRAWING_STYLES:
        raise ValueError('Choose a valid drawing style profile.')
    return value


def _metrics(image: Image.Image | None) -> dict[str,float]:
    if not isinstance(image,Image.Image) or min(image.size)<1:
        return {'unique':1.0,'edge':.5,'white':0.0,'chroma':.5,'alpha_empty':0.0}
    target=thumbnail_size(image.size,(160,160))
    with ExitStack() as temporary:
        own=lambda value:temporary.enter_context(closing(value))
        # Resize directly from the caller source; only the bounded sample is copied.
        sampled=own(image.resize(target,Image.Resampling.NEAREST))
        sample=sampled if sampled.mode=='RGBA' else own(sampled.convert('RGBA'))
        flat=own(Image.new('RGBA',sample.size,'white'));flat.alpha_composite(sample)
        rgb=own(flat.convert('RGB'));gray=own(rgb.convert('L'))
        quantized=own(rgb.quantize(colors=64,method=Image.Quantize.MEDIANCUT))
        used=sum(1 for v in quantized.histogram() if v)
        edges=own(gray.filter(ImageFilter.FIND_EDGES))
        edge=float(ImageStat.Stat(edges).mean[0])/255.0
        pixels=np.asarray(rgb);count=max(1,rgb.width*rgb.height)
        low=pixels.min(axis=2);high=pixels.max(axis=2)
        white=float(np.count_nonzero(low>=235))/count
        chroma=float(np.count_nonzero(high-low>=30))/count
        alpha=own(sample.getchannel('A'))
        alpha_empty=sum(alpha.histogram()[:9])/count
        return {'unique':min(1.0,used/64.0),'edge':edge,'white':white,
                'chroma':chroma,'alpha_empty':alpha_empty}


def classify_drawing_style(image: Image.Image | None) -> tuple[str,dict[str,float]]:
    m=_metrics(image)
    if isinstance(image,Image.Image) and max(image.size)<=320 and m['unique']<=.35 and m['edge']>=.05:
        style='Pixel Art'
    elif m['white']>=.68 and m['chroma']<=.14:
        style='Line Art'
    elif m['unique']<=.25 and (m['alpha_empty']>=.05 or m['edge']>=.035):
        style='Logo / Flat Graphic'
    elif m['unique']>=.70 and m['edge']<=.14:
        style='Photo / Shaded'
    elif m['unique']<=.55:
        style='Cartoon / Illustration'
    else:
        style='Photo / Shaded'
    return style,m


def _explicit_profile(style:str) -> dict[str,Any]:
    common={'profile_engine':'Manual settings'}
    if style=='Pixel Art':
        return {**common,
            'render_style':'Standard / pixel','draw_quality':'Pixel Accurate','brush_px':1,
            'background_simplification':'Off','adaptive_detail':'Off','detail_zoom':'Off',
            'color_layers':'Off','color_fidelity':'Faithful','stroke_optimizer':'Travel only',
            'gartic_opacity':'100%','style_accuracy_priority':'exact pixels / palette boundaries'}
    if style=='Logo / Flat Graphic':
        return {**common,
            'render_style':'Standard / pixel','draw_quality':'High likeness',
            'drawing_mode':'Shape paths','lines':True,'shape_order':'Fill first',
            'background_fill':'Balanced','fill_engine':'Closed regions v2',
            'background_simplification':'Off','adaptive_detail':'Auto','color_layers':'Off',
            'color_fidelity':'Faithful','stroke_optimizer':'Smart merge + 2-opt',
            'gartic_opacity':'100%','style_accuracy_priority':'clean silhouettes / flat color regions'}
    if style=='Portrait':
        return {**common,
            'render_style':'Portrait / shaded','draw_quality':'Maximum likeness',
            'drawing_mode':'Smart paths (recommended)','lines':True,'smart_paths':True,
            'background_simplification':'Balanced','adaptive_detail':'Auto','detail_zoom':'Auto',
            'subject_focus':'Subject first','color_fidelity':'Faithful','gartic_opacity':'Auto',
            'style_accuracy_priority':'face / eyes / local contrast / smooth shading'}
    if style=='Photo / Shaded':
        return {**common,
            'render_style':'Portrait / shaded','draw_quality':'Maximum likeness',
            'drawing_mode':'Smart paths (recommended)','lines':True,'smart_paths':True,
            'background_simplification':'Balanced','adaptive_detail':'Auto','detail_zoom':'Auto',
            'color_fidelity':'Faithful','gartic_opacity':'Auto',
            'style_accuracy_priority':'perceptual color / luminance / tonal gradients'}
    if style=='Line Art':
        return {**common,
            'render_style':'Standard / pixel','draw_quality':'High likeness','outline':True,
            'background_fill':'Off','background_simplification':'Off','sketch_detail':'Detailed',
            'adaptive_detail':'Auto','detail_zoom':'Auto','color_layers':'Off','brush_px':1,
            'gartic_opacity':'100%','style_accuracy_priority':'thin contours / gaps / small line detail'}
    if style=='Cartoon / Illustration':
        return {**common,
            'render_style':'Standard / pixel','draw_quality':'High likeness',
            'drawing_mode':'Shape paths','lines':True,'shape_order':'Fill first',
            'background_fill':'Balanced','fill_engine':'Closed regions v2',
            'background_simplification':'Off','adaptive_detail':'Auto','detail_zoom':'Auto',
            'color_fidelity':'Faithful','stroke_optimizer':'Smart merge + 2-opt',
            'gartic_opacity':'100%','style_accuracy_priority':'color regions / outlines / protected detail'}
    return {}


def apply_drawing_style(image: Image.Image | None, options: dict[str,Any]) -> dict[str,Any]:
    out=dict(options)
    requested=validate_drawing_style(out.get('drawing_style','Auto'))
    resolved,metrics=(classify_drawing_style(image) if requested=='Auto' else (requested,_metrics(image)))
    # Explicit style selection is authoritative. Auto detection is advisory to the
    # existing Auto/Extra Fast engines, avoiding a second independent planner.
    if requested!='Auto':
        out.update(_explicit_profile(resolved))
    out['drawing_style']=requested
    out['drawing_style_resolved']=resolved
    out['drawing_style_meta']={
        'requested':requested,'resolved':resolved,'automatic':requested=='Auto',
        'metrics':{k:round(float(v),4) for k,v in metrics.items()},
        'policy':_explicit_profile(resolved).get('style_accuracy_priority','existing planner policy'),
    }
    return out
