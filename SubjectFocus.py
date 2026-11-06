"""Deterministic subject selection. No semantic person detection or ML."""
from collections import deque
from dataclasses import replace
from contextlib import closing
from numbers import Integral, Real
import math
import numpy as np
from PIL import Image

MODES = ('Off', 'Subject first', 'Subject only')
_MAX_MASK_PIXELS = 64_000_000
_ALPHA_STRIP_PIXELS = 262_144

def _mask_size(size):
    try:
        width,height=size
    except (TypeError,ValueError) as error:
        raise ValueError('Subject mask needs two positive integer dimensions.') from error
    if any(isinstance(v,bool) or not isinstance(v,Integral) or v<1 for v in (width,height)):
        raise ValueError('Subject mask needs positive dimensions within 64 megapixels.')
    width,height=int(width),int(height)
    if width*height>_MAX_MASK_PIXELS:
        raise ValueError('Subject mask needs positive dimensions within 64 megapixels.')
    return width,height


def rectangle_mask(size, region):
    width, height = _mask_size(size)
    try:
        points=tuple(region)
        if len(points)!=4 or any(isinstance(v,bool) or not isinstance(v,Real) for v in points):
            raise ValueError()
        x0,y0,x1,y1=map(float,points)
        if not all(math.isfinite(v) for v in (x0,y0,x1,y1)):raise ValueError()
    except (TypeError,ValueError,OverflowError) as error:
        raise ValueError('Invalid subject rectangle. Mark the subject again.') from error
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError('Subject rectangle must be inside the image.')
    mask = np.zeros((height, width), dtype=bool)
    mask[int(y0*height):math.ceil(y1*height), int(x0*width):math.ceil(x1*width)] = True
    return mask

def subject_mask(image, region=None, cancelled=lambda: False):
    """Use explicit rectangle, alpha, or border-connected uniform background.

    Automatic mode deliberately refuses complex borders. It is an estimate,
    never a claim that a person was recognized. Mask estimation is bounded;
    the original image and full-resolution PixelMap are not resampled here.
    """
    if cancelled(): raise InterruptedError()
    _mask_size(image.size)
    if region is not None:
        mask=rectangle_mask(image.size, region)
        if cancelled():raise InterruptedError()
        return mask, 'Marked rectangle (includes its background)'
    from ImageFormatInfo import _has_transparency
    from ImageGeometry import thumbnail_size
    width,height=_mask_size(image.size)
    if _has_transparency(image):
        # Decode alpha in bounded strips; no full RGBA image is needed for a mask.
        mask=np.empty((height,width),dtype=bool)
        has_zero=False
        rows=max(1,_ALPHA_STRIP_PIXELS//width)
        for top in range(0,height,rows):
            if cancelled():raise InterruptedError()
            bottom=min(height,top+rows)
            with closing(image.crop((0,top,width,bottom))) as part, closing(part.convert('RGBA')) as rgba:
                visible=np.asarray(rgba)[...,3]>0
                mask[top:bottom]=visible
                has_zero=has_zero or not bool(visible.all())
        if cancelled():raise InterruptedError()
        if has_zero:
            if not mask.any():raise ValueError('No visible subject exists in this fully transparent image.')
            return mask, 'Image transparency'
        del mask
    if cancelled():raise InterruptedError()
    target=thumbnail_size(image.size,(384,384))
    # Palette/key transparency must be decoded before interpolation; RGB/RGBA/L sources can
    # be sampled directly, avoiding full-size conversion before reduction.
    if image.mode=='P' or 'transparency' in image.info:
        with closing(image.convert('RGBA')) as source:
            small=source.resize(target,Image.Resampling.BICUBIC,reducing_gap=2.0)
    else:
        small=image.resize(target,Image.Resampling.BICUBIC,reducing_gap=2.0)
    try:
        with closing(small.convert('RGBA')) as rgba, closing(Image.new('RGBA',small.size,'white')) as flat:
            flat.alpha_composite(rgba)
            with closing(flat.convert('RGB')) as visible:
                rgb=np.asarray(visible,dtype=np.int16)
    finally:small.close()
    if cancelled():raise InterruptedError()
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
    bg = np.median(border, axis=0)
    distances = np.max(np.abs(border-bg), axis=1)
    if np.mean(distances <= 28) < .85:
        raise ValueError('Background is too complex for automatic subject selection. Click Mark subject and draw a rectangle, or use a transparent PNG.')
    candidate = np.max(np.abs(rgb-bg), axis=2) <= 28
    h, w = candidate.shape
    visited = np.zeros_like(candidate)
    queue = deque()
    def add(y, x):
        if candidate[y, x] and not visited[y, x]:
            visited[y, x] = True
            queue.append((y, x))
    for x in range(w): add(0, x); add(h-1, x)
    for y in range(h): add(y, 0); add(y, w-1)
    count = 0
    while queue:
        y, x = queue.popleft()
        count += 1
        if count % 1024 == 0 and cancelled(): raise InterruptedError()
        if y: add(y-1, x)
        if y+1 < h: add(y+1, x)
        if x: add(y, x-1)
        if x+1 < w: add(y, x+1)
    if cancelled():raise InterruptedError()
    with closing(Image.fromarray((~visited).astype('uint8')*255)) as compact:
        with closing(compact.resize(image.size,Image.Resampling.NEAREST)) as full:
            mask=np.asarray(full)>0
    if cancelled():raise InterruptedError()
    if not mask.any() or mask.mean() > .95:
        raise ValueError('No clear subject found. Click Mark subject or use a transparent PNG.')
    return mask, 'Estimated from uniform border; check Coverage preview'

def focused_stroke_plan(pixel_map, image, palette_count, mode, region=None, *, lines=True, cpu_workers=1, options=None, cancelled=lambda: False):
    from PixelStrokeEngine import build_pixel_stroke_plan
    from PixelAccuracyEngine import execution_groups_from_sequence
    if mode not in MODES: raise ValueError('Unknown subject focus mode')
    from PixelMapValidation import validate_palette_count
    from PixelAccuratePlanner import validated_pixel_indices
    palette_count=validate_palette_count(palette_count)
    indices,drawable=validated_pixel_indices(pixel_map,palette_count,cancelled=cancelled)
    if mode!='Off' and image.size!=(indices.shape[1],indices.shape[0]):
        raise ValueError('Subject image dimensions must match its drawing pixel map.')
    kwargs = dict(lines=lines, cpu_workers=cpu_workers, options=options, cancelled=cancelled)
    if mode == 'Off':
        return pixel_map, build_pixel_stroke_plan(pixel_map, palette_count, **kwargs)
    mask, method = subject_mask(image, region, cancelled)
    foreground = pixel_map.drawable_mask & mask
    if not foreground.any():
        raise ValueError('The selected subject has no drawable pixels. Check the selection, palette and Skip white.')
    meta = dict(pixel_map.metadata, subject_focus=mode, subject_method=method,
                subject_pixels=int(foreground.sum()), subject_share=round(float(foreground.sum())/max(1,int(pixel_map.drawable_mask.sum())),4))
    def subset(selection):
        return replace(pixel_map, drawable_mask=selection,
                       protected_mask=pixel_map.protected_mask & selection, metadata=meta)
    target = subset(foreground) if mode == 'Subject only' else replace(pixel_map, metadata=meta)
    plans = [('subject', build_pixel_stroke_plan(subset(foreground), palette_count, **kwargs))]
    if mode == 'Subject first':
        plans.append(('background', build_pixel_stroke_plan(subset(pixel_map.drawable_mask & ~mask), palette_count, **kwargs)))
    groups = [[] for _ in range(palette_count)]
    sequence = []
    for section, plan in plans:
        for ci, group in enumerate(plan['groups']): groups[ci].extend(group)
        for entry in plan['execution_sequence']:
            # The timer preserves these section-prefixed phases as ordered paths.
            sequence.append(dict(entry, phase=section+'/'+entry['phase'],
                                 phase_label=section+' / '+entry.get('phase_label',entry['phase']),
                                 serial=len(sequence), subject_section=section))
    return target, dict(groups=groups, execution_groups=execution_groups_from_sequence(sequence,palette_count),
                       execution_sequence=sequence, metadata=dict(engine='Subject Focus / Pixel Stroke Engine',
                       execution_paths=len(sequence), subject_focus=mode, subject_method=method,
                       sections={section:plan['metadata'] for section,plan in plans}))
