"""Sketch 2.0 + Auto Fill orchestration for Image Draw Bot v1.0.131-beta.

Microsoft Paint is the first supported target. This module creates plans only;
it never sends input and never weakens CanvasGuard/preflight/authorization. The
colour phase reuses Image Draw Bot's existing colour/custom-RGB planning but forces
path-based fills so no bucket prelude can run before the sketch.
"""
from __future__ import annotations

import math
from contextlib import closing, contextmanager
from contextvars import ContextVar
import threading
from typing import Any, Callable, Sequence
from PIL import Image, ImageDraw

SKETCH_FILL_RENDER_STYLE='Sketch + Auto Fill'
SKETCH_FILL_VERSION='2.0'
SKETCH_FILL_PHASES=('sketch','color_fill','reoutline')


def _plan_images(plan):
    """Known renderer-owned buffers, including the normalized-source aliases."""
    if not isinstance(plan,dict):return ()
    images=[plan.get('image'),plan.get('preview')]
    previews=plan.get('ui_previews')
    if isinstance(previews,dict):images.extend(previews.values())
    options=plan.get('options')
    if isinstance(options,dict):
        for key in ('_accuracy_original_source','_accuracy_quantized_target',
                    '_pixel_coverage_preview','_pixel_error_preview','_preview_quantized_target'):
            images.append(options.get(key))
        cache=options.get('_accuracy_normalized_source_cache')
        if isinstance(cache,dict):images.extend((cache.get('image'),cache.get('source')))
    return [image for image in images if isinstance(image,Image.Image)]


class _PlanImageOwner:
    """Operation-local image/core ownership; never stored in plan options."""
    def __init__(self,borrowed=()):
        self.borrowed={id(image) for image in borrowed if isinstance(image,Image.Image)}
        self.images={}
        self.drawings=[]
        self.thread=threading.current_thread()
        self.closed=False

    def own(self,image):
        if isinstance(image,Image.Image) and id(image) not in self.borrowed:
            self.images[id(image)]=image
        return image

    def capture(self,plan):
        for image in _plan_images(plan):self.own(image)

    def drawing(self,drawing):
        self.drawings.append(drawing)
        return drawing

    def retire(self,retained=None,failure=None):
        keep=self.borrowed|{id(image) for image in _plan_images(retained)}
        errors=[]
        try:
            for key,image in tuple(self.images.items()):
                if key not in keep:
                    try:image.close()
                    except Exception as error:errors.append(error)
                    finally:self.images.pop(key,None)
        finally:
            image=None
        if errors:
            if failure is not None:
                failure.add_note('Sketch presentation image cleanup also failed: '+type(errors[0]).__name__)
            else:raise errors[0]

    def close(self,retained=None,failure=None):
        if self.closed:return
        self.closed=True
        try:
            # A retained Pillow traceback can hold its ImageDraw instance even
            # after the image wrapper is closed. Drop all native-core aliases.
            for drawing in self.drawings:
                drawing.draw=drawing.im=drawing._image=None
            self.retire(retained,failure)
        finally:
            self.drawings.clear();self.images.clear();self.borrowed.clear()
            drawing=None


_COLOR_PLAN_IMAGES=ContextVar('sketch_fill_color_plan_images',default=None)


def _current_plan_image_owner():
    owner=_COLOR_PLAN_IMAGES.get()
    return owner if owner is not None and not owner.closed and owner.thread is threading.current_thread() else None


def _own_color_plan_image(image):
    owner=_current_plan_image_owner()
    return owner.own(image) if owner is not None else image


@contextmanager
def _color_plan_image_scope(owner):
    token=_COLOR_PLAN_IMAGES.set(owner)
    try:yield
    finally:_COLOR_PLAN_IMAGES.reset(token)


def is_sketch_fill(options: dict[str,Any]) -> bool:
    return str(options.get('render_style') or '')==SKETCH_FILL_RENDER_STYLE and not bool(options.get('_sketch_fill_inner'))


def _is_paint(options):
    return str(options.get('profile_key') or '').strip().lower()=='microsoft-paint' or str(options.get('profile_name') or '').strip()=='Microsoft Paint'


def _path_length(path):
    return sum(math.hypot(float(b[0]-a[0]),float(b[1]-a[1])) for a,b in zip(path,path[1:])) if len(path)>1 else 0.0


def _path_area(path):
    if not path:return 0
    xs=[p[0] for p in path];ys=[p[1] for p in path]
    return max(1,max(xs)-min(xs)+1)*max(1,max(ys)-min(ys)+1)


def _strokes_from_paths(groups):
    out=[]
    for paths in groups:
        strokes=[]
        for path in paths:
            pts=[tuple(map(int,p)) for p in path]
            if not pts:continue
            if len(pts)==1:
                x,y=pts[0];strokes.append((x,y,x,y));continue
            strokes.extend((a[0],a[1],b[0],b[1]) for a,b in zip(pts,pts[1:]) if a!=b)
        out.append(strokes)
    return out


def _black_selector(colors, selectors):
    colors=list(map(tuple,colors));selectors=list(selectors or ())
    try:return colors.index((0,0,0)),colors,selectors
    except ValueError:pass
    from Colors import allColors
    native=min(range(len(allColors)),key=lambda i:sum(int(v)*int(v) for v in allColors[i].RGB))
    # Palette-only sub-plans use implicit, index-matched selectors. Preserve
    # those existing actions before appending a contour selector at its own
    # color index; otherwise it occupies index zero and execution falls back
    # to the last native swatch for the new contour color.
    for index in range(len(selectors),len(colors)):
        selectors.append({'kind':'palette','palette_index':index,'rgb':colors[index]})
    # A native fallback can only paint the measured swatch, even when its
    # darkest RGB is near-black rather than exactly zero. Preview and Paint's
    # color verifier must describe that same available ink.
    rgb=tuple(allColors[native].RGB)
    colors.append(rgb);selectors.append({'kind':'palette','palette_index':native,'rgb':rgb})
    return len(colors)-1,colors,selectors


def _reoutline_paths(paths, detail):
    paths=[tuple(p) for p in paths if p]
    if not paths:return []
    ratio={'Simple':.20,'Balanced':.32,'Detailed':.45}.get(str(detail),.32)
    wanted=max(1,min(len(paths),int(math.ceil(len(paths)*ratio))))
    ranked=sorted(enumerate(paths),key=lambda row:(-_path_area(row[1]),-_path_length(row[1]),row[0]))
    chosen={i for i,_ in ranked[:wanted]}
    return [p for i,p in enumerate(paths) if i in chosen]


def build_sketch_fill_plan(original: Image.Image, area, options: dict[str,Any], make_plan, finish_plan,
                           cancelled: Callable[[],bool]=lambda:False,*,_finalize=None):
    borrowed=[original]+[value for value in options.values() if isinstance(value,Image.Image)]
    borrowed.extend(_plan_images({'options':options}))
    owner=_PlanImageOwner(borrowed)
    result=plan=failure=None
    try:
        with _color_plan_image_scope(owner):
            plan=_build_sketch_fill_plan(original,area,options,make_plan,finish_plan,cancelled,owner)
            owner.capture(plan)
            # Acceptance/rescue needs this completed composite, never the
            # discarded colour diagnostics. Keep its images owned until the
            # actual public result is known, including an interrupted rescue.
            owner.retire(plan)
            result=_finalize(plan,original,area,cancelled) if _finalize is not None else plan
            owner.capture(result)
        return result
    except BaseException as error:
        failure=error
        raise
    finally:
        owner.close(result,failure)
        borrowed=result=plan=failure=None


def _build_sketch_fill_plan(original,area,options,make_plan,finish_plan,cancelled,owner):
    if not _is_paint(options):
        raise ValueError('Sketch + Auto Fill is currently optimized for Microsoft Paint. Choose another rendering style for browser targets.')
    if options.get('erase_mode'):
        raise ValueError('Sketch + Auto Fill needs Pencil or Brush, not Eraser.')
    # Build the colour layer through the proven Paint planner, but explicitly
    # disable native Fill so it cannot execute as the existing prelude before
    # the sketch. Auto Fill v1 uses long connected colour runs instead.
    inner=dict(options)
    inner.update({
        '_sketch_fill_inner':True,'auto_engine_resolved':True,
        '_sketch_fill_defer_presentation':True,
        'render_style':'Standard / pixel','outline':False,'paint_current_color':False,'erase_mode':False,
        'drawing_mode':'Smart paths (recommended)','smart_paths':True,'lines':True,
        'fill_tool_available':False,'background_fill':'Off','use_region_fill_engine':False,
        'progressive_rendering':'Off','color_workflow':'Finish color first','detail_zoom':'Off',
    })
    inner.pop('background_fill_plan',None);inner.pop('fill_regions',None)
    color_plan=make_plan(original,area,inner,cancelled)
    owner.capture(color_plan)
    if cancelled():raise InterruptedError()
    colors=tuple(color_plan.get('colors') or ())
    selectors=tuple(color_plan.get('color_selectors') or ())
    black_index,colors,selectors=_black_selector(colors,selectors)
    color_groups=[list(map(tuple,paths)) for paths in (color_plan.get('execution_groups') or [])]
    while len(color_groups)<len(colors):color_groups.append([])

    from Sketch2Planner import contour_image_v2
    from PixelData import monochrome_strokes
    from ContinuousPaths import build_execution_paths
    detail=str(options.get('sketch_detail') or 'Detailed')
    if detail=='Auto':detail='Balanced'
    with closing(original.convert('RGBA')) as rgba:
        source=rgba.resize(color_plan['image'].size,Image.Resampling.LANCZOS)
    with closing(source):
        sketch_image,sketch_meta=contour_image_v2(source,cancelled,detail=detail)
    with closing(sketch_image):
        ink=monochrome_strokes(sketch_image,True,cancelled)[0]
    sketch_paths=build_execution_paths([ink],enabled=True,cancelled=cancelled)[0] if ink else []
    sketch_paths=[tuple(map(tuple,p)) for p in sketch_paths if p]
    reoutline=_reoutline_paths(sketch_paths,detail)

    combined=[list(paths) for paths in color_groups]
    combined[black_index]=list(sketch_paths)+combined[black_index]+list(reoutline)
    sequence=[];serial=0
    for path in sketch_paths:
        sequence.append({'color_index':black_index,'path':path,'phase':'sketch','phase_label':'Sketch 2.0 contours','serial':serial});serial+=1
    order=[];seen=set()
    for raw in list((color_plan.get('options') or {}).get('color_order') or ()) + list(range(len(color_groups))):
        try:i=int(raw)
        except (TypeError,ValueError):continue
        if 0<=i<len(color_groups) and i not in seen:
            order.append(i);seen.add(i)
    color_paths=0
    for i in order:
        # Large/long runs first inside each colour: the image fills visibly fast.
        paths=sorted(color_groups[i],key=lambda p:(-_path_area(p),-_path_length(p)))
        for path in paths:
            if not path:continue
            sequence.append({'color_index':i,'path':tuple(path),'phase':'color_fill','phase_label':'color fill','serial':serial});serial+=1;color_paths+=1
    for path in reoutline:
        sequence.append({'color_index':black_index,'path':path,'phase':'reoutline','phase_label':'final re-outline','serial':serial});serial+=1

    outer=dict(color_plan.get('options') or {})
    # The colour sub-plan deliberately supplies its palette and paths, but it
    # no longer owns execution after contours/re-outline have been added. In
    # particular, stale Pixel groups otherwise win finish_plan's group/count
    # dispatch while the Sketch sequence wins its separate sequence dispatch.
    # Keep pixel_accurate: the executor also uses that policy hint for its
    # existing small-brush interpolation. It is not a measurement or a compiled
    # sequence. Drop references only; the inner plan may own these buffers.
    for key in (
        '_sketch_fill_defer_presentation',
        '_pixel_execution_groups','_pixel_execution_sequence',
        'pixel_map_meta','pixel_stroke_meta','pixel_stroke_engine','pixel_accuracy_meta',
        '_adaptive_hybrid_execution_groups','_adaptive_hybrid_execution_sequence',
        'adaptive_hybrid_active','adaptive_hybrid_meta','adaptive_hybrid_version',
        'sketch_execution_groups','gartic_sketch_meta',
        '_pixel_coverage_preview','_pixel_error_preview',
        '_preview_safety_groups','preview_safety_meta','adaptive_accuracy_meta',
        'preview_delta_e_meta','preview_diagnostics_meta','accuracy_buffer_meta',
        'adaptive_deadline_meta','detail_zoom_meta','operation_timing_meta',
        'region_fill_meta','fill_timing_meta','auto_tuner_acceptance_meta',
    ):
        outer.pop(key,None)
    outer.update({
        'render_style':SKETCH_FILL_RENDER_STYLE,'sketch_fill_active':True,'sketch_fill_version':SKETCH_FILL_VERSION,
        'sketch2_meta':dict(sketch_meta),'fill_regions':[],'background_fill':'Off','use_region_fill_engine':False,
        'detail_zoom':'Off','stroke_optimizer':'Off','progressive_rendering':'On','color_workflow':'Progressive passes',
        'plan_palette_rgb':tuple(colors),'color_selectors':tuple(selectors),
        '_sketch_fill_execution_groups':combined,'_sketch_fill_execution_sequence':sequence,
        '_accuracy_original_source':owner.own(original.copy()),
    })
    outer.pop('background_fill_plan',None)
    outer['sketch_fill_meta']={
        'enabled':True,'version':SKETCH_FILL_VERSION,'target':'Microsoft Paint','paint_first':True,
        'phase_order':'Sketch -> Color Fill -> Re-outline','sketch_paths':len(sketch_paths),
        'color_fill_paths':color_paths,'reoutline_paths':len(reoutline),'total_paths':len(sequence),
        'native_bucket_prelude':False,'fill_method':'connected color runs','custom_colors_reused':bool(outer.get('exact_color_available')),
        'pixel_metrics_status':'not_calculated',
        'pixel_metrics_reason':'The composed Sketch Fill sequence has no final Pixel coverage or plan-execution measurement; color sub-plan metrics do not describe its added contours.',
        'browser_policy_changed':False,'ai_ml_ocr':False,
    }
    groups=_strokes_from_paths(combined)
    return finish_plan(color_plan['image'],color_plan['fitted'],groups,outer,cancelled)


def render_sequence_preview(source_size, preview_size, sequence, palette_rgb, brush_px=1, *, phases=None,cancelled=lambda:False):
    from AdaptiveRegionHybrid import render_adaptive_preview
    allowed=set(phases) if phases is not None else None
    def selected():
        for raw in sequence or ():
            if cancelled():raise InterruptedError()
            if allowed is not None and str(raw.get('phase')) not in allowed:continue
            entry=dict(raw);entry.setdefault('brush_px',max(1,int(round(float(brush_px)))))
            yield entry
    return render_adaptive_preview(source_size,preview_size,selected(),palette_rgb,cancelled=cancelled)


def build_phase_previews(source_size, preview_size, sequence, palette_rgb, brush_px=1, *, cancelled=lambda:False):
    previews={}
    try:
        for key,phases in (('sketch2',('sketch',)),('sketch_fill',('sketch','color_fill')),
                           ('sketch_fill_final',None)):
            if cancelled():raise InterruptedError()
            previews[key]=render_sequence_preview(source_size,preview_size,sequence,palette_rgb,brush_px,
                                                   phases=phases,cancelled=cancelled)
        if cancelled():raise InterruptedError()
        return previews
    except BaseException:
        for preview in previews.values():preview.close()
        raise
