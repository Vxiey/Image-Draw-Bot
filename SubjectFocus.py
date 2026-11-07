"""Deterministic subject selection. No semantic person detection or ML."""
from collections import deque
from dataclasses import replace
from contextlib import ExitStack, closing
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


def _native_subject_roi(mask, projection, cancelled):
    if tuple(projection.source_size)!=(mask.shape[1],mask.shape[0]):
        raise ValueError('Subject projection must describe the same source mask.')
    if cancelled():raise InterruptedError('Subject brush clipping cancelled.')
    rows=np.flatnonzero(np.any(mask,axis=1));columns=np.flatnonzero(np.any(mask,axis=0))
    if not len(rows) or not len(columns):return None
    bounds=(int(columns[0]),int(rows[0]),int(columns[-1]),int(rows[-1]))
    roi,reason=projection.component_roi(mask,True,bounds,cancelled=cancelled)
    if roi is None and 'exceeds' in reason:raise ValueError(reason)
    return roi


def clip_subject_brush_sequence(sequence, subject_mask, *, default_brush_px=1,
                                projection=None, cancelled=lambda: False):
    """Retain only centers whose actual square brush stays inside the subject.

    A native projection keeps half-pixel letterboxing and signed desktop
    rounding in the footprint proof. Paths remain in source coordinates.
    Keep the target mask unchanged: features that cannot fit the verified
    brush remain measurable missing pixels instead of enlarging the subject.
    """
    from AdaptiveBrushEngine import brush_for_entry
    from RasterGeometry import clipped_bresenham
    if cancelled(): raise InterruptedError('Subject brush clipping cancelled.')
    mask=np.asarray(subject_mask,dtype=np.bool_)
    if mask.ndim!=2: raise ValueError('Subject brush mask must be two-dimensional.')
    height,width=mask.shape
    _mask_size((width,height))
    native_roi=_native_subject_roi(mask,projection,cancelled) if projection is not None else None
    masks={};current_brush=max(1,int(default_brush_px));result=[]
    source_paths=omitted_paths=split_paths=trimmed_paths=rejected_visits=0
    unsafe_native_connectors=0

    def safe_centers(brush):
        target=mask if projection is None else (native_roi.target if native_roi is not None else None)
        if target is None or brush==1:return target
        cached=masks.pop(brush,None)
        if cached is None:
            # Reuse the exact asymmetric footprint already used by regional
            # simulation, with at most two private full-plane masks retained.
            from AdaptiveRegionHybrid import _eroded_centers
            cached=_eroded_centers(target,brush,cancelled=cancelled)
        masks[brush]=cached
        if len(masks)>2:masks.pop(next(iter(masks)))
        return cached

    def local_native(point):
        return (int(projection.x_centers[point[0]])-native_roi.native_origin[0],
                int(projection.y_centers[point[1]])-native_roi.native_origin[1])

    def safe_point(safe,point):
        if safe is None:return False
        x,y=point if projection is None else local_native(point)
        return 0<=y<safe.shape[0] and 0<=x<safe.shape[1] and bool(safe[y,x])

    def safe_native_connection(safe,a,b):
        for number,(x,y) in enumerate(clipped_bresenham(a,b,safe.shape[1],safe.shape[0])):
            if number%256==0 and cancelled():raise InterruptedError('Subject brush clipping cancelled.')
            if not safe[y,x]:return False
        return True

    def safe_connection(safe,a,b):
        return safe_native_connection(safe,local_native(a),local_native(b))

    def append_point(fragment,point):
        if not fragment or fragment[-1]!=point:
            if len(fragment)>=2:
                a,b=fragment[-2:]
                if ((a[0]==b[0]==point[0] and (b[1]-a[1])*(point[1]-b[1])>0)
                        or (a[1]==b[1]==point[1] and (b[0]-a[0])*(point[0]-b[0])>0)):
                    fragment[-1]=point
                    return
            fragment.append(point)

    for entry in sequence:
        if cancelled(): raise InterruptedError('Subject brush clipping cancelled.')
        path=tuple(entry.get('path') or ())
        if not path:
            result.append(dict(entry))
            continue
        # Empty entries do not select a tool in the executor. A real path that
        # is later omitted still supplies the width intended by following paths.
        current_brush=brush_for_entry(entry,current_brush)
        source_paths+=1
        safe=safe_centers(current_brush)
        fragments=[];fragment=[];last_sample=None;sample_number=0;changed=False
        segments=((path[0],path[0]),) if len(path)==1 else zip(path,path[1:])
        for a,b in segments:
            if cancelled(): raise InterruptedError('Subject brush clipping cancelled.')
            if any(not (0<=int(p[0])<width and 0<=int(p[1])<height) for p in (a,b)):
                changed=True
            for point in clipped_bresenham(a,b,width,height):
                if sample_number%256==0 and cancelled(): raise InterruptedError('Subject brush clipping cancelled.')
                sample_number+=1
                if point==last_sample:continue
                last_sample=point
                if not safe_point(safe,point):
                    changed=True;rejected_visits+=1
                    if fragment:fragments.append(tuple(fragment));fragment=[]
                    continue
                # Clipping an off-canvas segment can omit a nonadjacent prefix
                # or suffix. Never join two returned pieces across that gap.
                if fragment and max(abs(point[0]-fragment[-1][0]),abs(point[1]-fragment[-1][1]))>1:
                    fragments.append(tuple(fragment));fragment=[]
                if projection is not None and fragment and not safe_connection(safe,fragment[-1],point):
                    fragments.append(tuple(fragment));fragment=[]
                    changed=True;unsafe_native_connectors+=1
                append_point(fragment,point)
        if fragment:fragments.append(tuple(fragment))
        if not changed and projection is not None and len(path)>1:
            # A long diagonal's native raster can differ from the separately
            # rounded source samples. Reuse the original vertices only when
            # that actual native connector also passed the footprint proof.
            native=projection.native_path(path,cancelled=cancelled)
            local=tuple((x-native_roi.native_origin[0],y-native_roi.native_origin[1]) for x,y in native)
            for a,b in zip(local,local[1:]):
                if not safe_native_connection(safe,a,b):
                    changed=True;unsafe_native_connectors+=1
                    break
        if not changed:
            result.append(dict(entry,path=path,brush_px=current_brush))
            continue
        trimmed_paths+=1
        if not fragments:omitted_paths+=1
        if len(fragments)>1:split_paths+=1
        for fragment in fragments:
            result.append(dict(entry,path=fragment,brush_px=current_brush))
    if cancelled(): raise InterruptedError('Subject brush clipping cancelled.')
    brush_counts={};reason_counts={};previous_brush=None;brush_switches=0
    for entry in result:
        if not entry.get('path'):continue
        brush=brush_for_entry(entry,previous_brush or default_brush_px)
        brush_counts[str(brush)]=brush_counts.get(str(brush),0)+1
        reason=str(entry.get('brush_reason') or 'unknown')
        reason_counts[reason]=reason_counts.get(reason,0)+1
        if previous_brush is not None and brush!=previous_brush:brush_switches+=1
        previous_brush=brush
    metadata={'enabled':True,'mode':'Subject only','mask_unchanged':True,
        'footprint_model':('native square footprint through CanvasTransform' if projection is not None
                           else 'exact asymmetric square in planning pixels'),
        'source_paths':source_paths,'retained_paths':sum(bool(e.get('path')) for e in result),
        'trimmed_source_paths':trimmed_paths,'omitted_source_paths':omitted_paths,
        'split_source_paths':split_paths,'rejected_center_visits':rejected_visits,
        'used_brush_sizes':tuple(sorted(map(int,brush_counts))),
        'brush_path_counts':brush_counts,'brush_reason_counts':reason_counts,
        'planned_brush_switches':brush_switches,
        'coverage_policy':'unreachable subject pixels remain missing in accuracy diagnostics',
        'maximum_cached_footprint_masks':2}
    if projection is not None:
        metadata.update(native_projection=projection.as_meta(),unsafe_native_connectors=unsafe_native_connectors,
            native_subject_roi=None if native_roi is None else (*native_roi.native_origin,
                native_roi.target.shape[1],native_roi.target.shape[0]))
    return result,metadata


def render_native_subject_preview(safety_plan, fitted, preview_size, palette_rgb, *, cancelled=lambda:False):
    """Sample already guarded native square footprints into the fitted view.

    The safety plan owns canvas-local paths and their actual physical widths.
    Sampling their intervals avoids scaling widths or rounding fractional
    letterboxes a second time. Only display-sized RGB storage is allocated.
    """
    from AdaptiveRegionHybrid import _path_rectangles
    from PixelMapValidation import validate_color_index
    from RasterGeometry import clipped_bresenham
    if cancelled():raise InterruptedError('Subject preview cancelled.')
    pw,ph=_mask_size(preview_size)
    offset=safety_plan.meta.get('image_offset') or (0,0)
    width,height=(round(float(fit)+2*float(pad)) for fit,pad in zip(fitted,offset))
    xs=np.floor(float(offset[0])+(np.arange(pw)+.5)*float(fitted[0])/pw).astype(np.int64)
    ys=np.floor(float(offset[1])+(np.arange(ph)+.5)*float(fitted[1])/ph).astype(np.int64)
    pixels=np.full((ph,pw,3),255,dtype=np.uint8)
    def rectangles(path,brush):
        if len(path)<2:
            yield from _path_rectangles(path,brush,width,height,cancelled=cancelled)
            return
        for number,(a,b) in enumerate(zip(path,path[1:])):
            if number%128==0 and cancelled():raise InterruptedError('Subject preview cancelled.')
            if a[0]==b[0] or a[1]==b[1]:
                yield from _path_rectangles((a,b),brush,width,height,cancelled=cancelled)
            else:
                # Pixel Accuracy uses Bresenham for its future diagonal paths;
                # retain that phase rather than the hybrid engine's interpolation.
                before,after=(brush-1)//2,brush//2
                for visit,(x,y) in enumerate(clipped_bresenham(a,b,width,height,before=before,after=after)):
                    if visit%256==0 and cancelled():raise InterruptedError('Subject preview cancelled.')
                    yield max(0,x-before),max(0,y-before),min(width-1,x+after),min(height-1,y+after)
    for entry in safety_plan.sequence or ():
        if cancelled():raise InterruptedError('Subject preview cancelled.')
        path=entry.get('path') or ()
        if not path:continue
        color=palette_rgb[validate_color_index(entry['color_index'],palette_count=len(palette_rgb))]
        brush=max(1,int(entry['brush_px']))
        for x0,y0,x1,y1 in rectangles(path,brush):
            left,right=np.searchsorted(xs,(x0,x1+1),side='left')
            top,bottom=np.searchsorted(ys,(y0,y1+1),side='left')
            if left<right and top<bottom:pixels[top:bottom,left:right]=color
    if cancelled():raise InterruptedError('Subject preview cancelled.')
    return Image.fromarray(pixels,'RGB')


def _subject_diagnostic_canvas(image, origin, projection, background, cancelled):
    """Place one scored ROI into a bounded full-canvas NEAREST diagnostic."""
    from RasterGeometry import nearest_axis_samples
    if cancelled():raise InterruptedError('Subject accuracy cancelled.')
    width,height=projection.canvas_size
    scale=min(1.,1600/max(width,height))
    size=(max(1,round(width*scale)),max(1,round(height*scale)))
    xs=np.asarray(nearest_axis_samples(width,size[0],cancelled=cancelled))
    ys=np.asarray(nearest_axis_samples(height,size[1],cancelled=cancelled))
    left,right=np.searchsorted(xs,(origin[0],origin[0]+image.width),side='left')
    top,bottom=np.searchsorted(ys,(origin[1],origin[1]+image.height),side='left')
    result=Image.new('RGB',size,background)
    try:
        if left<right and top<bottom:
            sample=np.ix_(ys[top:bottom]-origin[1],xs[left:right]-origin[0])
            with closing(Image.fromarray(np.asarray(image)[sample],'RGB')) as block:
                result.paste(block,(int(left),int(top)))
        if cancelled():raise InterruptedError('Subject accuracy cancelled.')
        return result
    except BaseException:
        result.close()
        raise


def evaluate_native_subject_plan(pixel_map, sequence, palette_rgb, projection, *, brush_px=1,
                                  gpu_mode='CPU', gpu_vram='Auto', gpu_performance='High throughput',
                                  cancelled=lambda:False):
    """Score a footprint-constrained subject sequence in physical canvas pixels.

    ``sequence`` must already have passed ``clip_subject_brush_sequence`` with
    this projection. Its footprints stay inside the subject ROI, so the empty
    canvas outside that ROI contributes no evaluation pixels. No transformed
    sequence or projected PixelMap is returned or stored on the original plan.
    """
    from PixelAccuracyEngine import (PixelScoreContext,refine_with_corrections,
        progressive_accuracy_checkpoints,render_coverage_map,render_error_map)
    if cancelled():raise InterruptedError('Subject accuracy cancelled.')
    mask=np.asarray(pixel_map.drawable_mask,dtype=np.bool_)
    roi=_native_subject_roi(mask,projection,cancelled)
    if roi is None:
        native=replace(pixel_map,width=1,height=1,rgb=np.full((1,1,3),255,dtype=np.uint8),
            palette_index=np.zeros((1,1),dtype=np.int16),drawable_mask=np.zeros((1,1),bool),
            edge_map=np.zeros((1,1),np.float32),importance_map=np.zeros((1,1),np.float32),
            protected_mask=np.zeros((1,1),bool),contour_map=None,shadow_map=None,
            shadow_detail_map=None,micro_detail_map=None,metadata={})
        origin=(0,0)
    else:
        origin=roi.native_origin;h,w=roi.target.shape
        xs=projection.x_source[origin[0]:origin[0]+w]
        ys=projection.y_source[origin[1]:origin[1]+h]
        select=np.ix_(ys,xs)
        fields={}
        for name in ('rgb','palette_index','edge_map','importance_map','protected_mask',
                     'contour_map','shadow_map','shadow_detail_map','micro_detail_map'):
            if cancelled():raise InterruptedError('Subject accuracy cancelled.')
            value=getattr(pixel_map,name)
            fields[name]=None if value is None else np.asarray(value)[select]
        native=replace(pixel_map,width=w,height=h,drawable_mask=roi.target,metadata={},**fields)
    native_sequence=[]
    for entry in sequence:
        if cancelled():raise InterruptedError('Subject accuracy cancelled.')
        path=projection.native_path(entry.get('path') or (),cancelled=cancelled)
        native_sequence.append(dict(entry,path=tuple((x-origin[0],y-origin[1]) for x,y in path)))
    context=PixelScoreContext(native)
    evaluated=refine_with_corrections(native,native_sequence,palette_rgb,brush_px=brush_px,
        max_passes=0,gpu_mode=gpu_mode,gpu_vram=gpu_vram,gpu_performance=gpu_performance,
        score_context=context,cancelled=cancelled)
    checkpoints=progressive_accuracy_checkpoints(native,native_sequence,palette_rgb,
        brush_px=brush_px,score_context=context,cancelled=cancelled)
    del context
    metadata=dict(evaluated['metadata'],score_scope='physical canvas pixels before CanvasGuard/runtime delivery',
        coverage_coordinate_space='full physical canvas',native_projection=projection.as_meta(),
        native_subject_roi=None if roi is None else (*origin,native.width,native.height))
    regions=metadata.get('region_accuracy') or {}
    for region in regions.get('worst_regions') or ():
        x0,y0,x1,y1=region['bbox'];region['bbox']=(x0+origin[0],y0+origin[1],x1+origin[0],y1+origin[1])
    regions['coordinate_space']='physical canvas pixels'
    retained=set()
    with ExitStack() as owned:
        def own(image):
            owned.callback(lambda:image.close() if id(image) not in retained else None)
            return image
        coverage_roi=own(render_coverage_map(native,evaluated['simulation']))
        error_roi=own(render_error_map(native,evaluated['simulation']))
        coverage=own(_subject_diagnostic_canvas(coverage_roi,origin,projection,(20,25,32),cancelled))
        error=own(_subject_diagnostic_canvas(error_roi,origin,projection,(22,26,34),cancelled))
        if cancelled():raise InterruptedError('Subject accuracy cancelled.')
        retained.update((id(coverage),id(error)))
        return {'metadata':metadata,'checkpoints':checkpoints,'coverage_preview':coverage,'error_preview':error}
