"""Sketch 2.0 + Auto Fill orchestration for Image Draw Bot v1.0.131-beta.

Microsoft Paint is the first supported target. This module creates plans only;
it never sends input and never weakens CanvasGuard/preflight/authorization. The
colour phase reuses Image Draw Bot's existing colour/custom-RGB planning but forces
path-based fills so no bucket prelude can run before the sketch.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Sequence
from PIL import Image, ImageDraw

SKETCH_FILL_RENDER_STYLE='Sketch + Auto Fill'
SKETCH_FILL_VERSION='2.0'
SKETCH_FILL_PHASES=('sketch','color_fill','reoutline')


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
    colors.append((0,0,0));selectors.append({'kind':'palette','palette_index':native,'rgb':(0,0,0)})
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
                           cancelled: Callable[[],bool]=lambda:False):
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
        'render_style':'Standard / pixel','outline':False,'paint_current_color':False,'erase_mode':False,
        'drawing_mode':'Smart paths (recommended)','smart_paths':True,'lines':True,
        'fill_tool_available':False,'background_fill':'Off','use_region_fill_engine':False,
        'progressive_rendering':'Off','color_workflow':'Finish color first','detail_zoom':'Off',
    })
    inner.pop('background_fill_plan',None);inner.pop('fill_regions',None)
    color_plan=make_plan(original,area,inner,cancelled)
    if cancelled():raise InterruptedError()
    colors=tuple(color_plan.get('colors') or ())
    selectors=tuple(color_plan.get('color_selectors') or ())
    black_index,colors,selectors=_black_selector(colors,selectors)
    color_groups=[list(map(tuple,paths)) for paths in (color_plan.get('execution_groups') or [])]
    while len(color_groups)<len(colors):color_groups.append([])

    from Sketch2Planner import contour_image_v2
    from PixelData import monochrome_strokes
    from ContinuousPaths import build_execution_paths
    source=original.convert('RGBA').resize(color_plan['image'].size,Image.Resampling.LANCZOS)
    detail=str(options.get('sketch_detail') or 'Detailed')
    if detail=='Auto':detail='Balanced'
    sketch_image,sketch_meta=contour_image_v2(source,cancelled,detail=detail)
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
    outer.update({
        'render_style':SKETCH_FILL_RENDER_STYLE,'sketch_fill_active':True,'sketch_fill_version':SKETCH_FILL_VERSION,
        'sketch2_meta':dict(sketch_meta),'fill_regions':[],'background_fill':'Off','use_region_fill_engine':False,
        'detail_zoom':'Off','stroke_optimizer':'Off','progressive_rendering':'On','color_workflow':'Progressive passes',
        'plan_palette_rgb':tuple(colors),'color_selectors':tuple(selectors),
        '_sketch_fill_execution_groups':combined,'_sketch_fill_execution_sequence':sequence,
        '_accuracy_original_source':original.copy(),
    })
    outer.pop('background_fill_plan',None)
    outer['sketch_fill_meta']={
        'enabled':True,'version':SKETCH_FILL_VERSION,'target':'Microsoft Paint','paint_first':True,
        'phase_order':'Sketch -> Color Fill -> Re-outline','sketch_paths':len(sketch_paths),
        'color_fill_paths':color_paths,'reoutline_paths':len(reoutline),'total_paths':len(sequence),
        'native_bucket_prelude':False,'fill_method':'connected color runs','custom_colors_reused':bool(outer.get('exact_color_available')),
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
