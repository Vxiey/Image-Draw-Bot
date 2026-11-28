"""Read-only modern Paint setup, verified against ribbon geometry and icons."""
import math
import numpy as np
from PIL import Image,ImageFilter
from contextlib import ExitStack
from functools import lru_cache
from types import MappingProxyType
from PaletteMaps import detect_color_swatches
from PaintCanvasGrips import verified_grip_depth
from GameProfiles import PAINT_WINDOW_TITLE
from RuntimePaths import resource_path
from CalibrationValidation import (calibration_screenshot,screen_rect,screen_point,contained_rect,nonnegative_integer,
                                   finite_confidence)

ROW1=((0,0,0),(127,127,127),(136,0,21),(237,28,36),(255,127,39),(255,242,0),(34,177,76),(0,162,232),(63,72,204),(163,73,164))
ROW2=((255,255,255),(195,195,195),(185,122,87),(255,174,201),(255,201,14),(239,228,176),(181,230,29),(153,217,234),(112,146,190),(200,191,231))


def _run(mask):
    best=(0,0);start=None
    for i,value in enumerate(list(mask)+[False]):
        if value and start is None:start=i
        elif not value and start is not None:
            if i-start>best[1]-best[0]:best=(start,i)
            start=None
    return best


def _significant_runs(mask,min_length):
    out=[];start=None
    for i,value in enumerate(list(mask)+[False]):
        if value and start is None:start=i
        elif not value and start is not None:
            if i-start>=min_length:out.append((start,i))
            start=None
    return out


def resolve_manual_canvas_override(corners, selected_handle, selected_client_rect,
                                   current_handle, current_client_rect):
    """Return a rebased user-selected Paint canvas when it still matches Paint.

    Manual selection is an explicit hard boundary.  It is safer and more useful
    than re-guessing Paint's pale document shadow every time Prepare Paint runs.
    The selection is reused only for the same native window and same client size;
    a pure window move is rebased, while resize/target changes fall back to fresh
    automatic detection instead of silently transforming the user's boundary.
    """
    try:
        if len(corners)!=2:return None
        selected_handle=nonnegative_integer(selected_handle,'Selected window',maximum=(1<<64)-1)
        current_handle=nonnegative_integer(current_handle,'Current window',maximum=(1<<64)-1)
        if not selected_handle or selected_handle!=current_handle:return None
        old=screen_rect(selected_client_rect);cur=screen_rect(current_client_rect)
        ow,oh=old[2]-old[0],old[3]-old[1];cw,ch=cur[2]-cur[0],cur[3]-cur[1]
        if ow<=0 or oh<=0 or (ow,oh)!=(cw,ch):return None
        dx,dy=cur[0]-old[0],cur[1]-old[1]
        a,b=screen_point(corners[0]),screen_point(corners[1])
        p0=screen_point((a[0]+dx,a[1]+dy));p1=screen_point((b[0]+dx,b[1]+dy))
        left,right=sorted((p0[0],p1[0]));top,bottom=sorted((p0[1],p1[1]))
        if right-left<64 or bottom-top<64:return None
        if left<cur[0] or top<cur[1] or right>cur[2] or bottom>cur[3]:return None
        return (left,top,right,bottom)
    except (TypeError,ValueError,OverflowError,IndexError):
        return None


def _validate_canvas_override(box, *, screen_origin, w, h, ratio, toolbar_end, scale,original_size=None):
    left,top,right,bottom=screen_rect(box,'selected Paint drawing area',min_side=64)
    if right-left<64 or bottom-top<64:
        raise ValueError('The selected Paint drawing area is too small. Select the canvas again.')
    ox,oy=map(int,screen_origin)
    if original_size is not None:
        contained_rect(box,(ox,oy,ox+original_size[0],oy+original_size[1]),'selected Paint drawing area',min_side=64)
    lx0=(left-ox)*ratio;ly0=(top-oy)*ratio;lx1=(right-ox)*ratio;ly1=(bottom-oy)*ratio
    tolerance=max(2,round(3*scale))
    if lx0 < -tolerance or ly0 < -tolerance or lx1 > w+tolerance or ly1 > h+tolerance:
        raise ValueError('The selected Paint drawing area is outside the current Paint window. Select it again.')
    if ly0 < toolbar_end-tolerance:
        raise ValueError('The selected Paint drawing area overlaps the Paint toolbar. Select only the drawable canvas.')
    return (left,top,right,bottom)


def _edge_supported_horizontal_span(white, *, top, bottom, scale, min_safe_w):
    """Infer the document span from clean bands near its top/bottom edges."""
    probe_h=max(3,round(6*scale));inset=max(3,round(10*scale))
    profiles=[]
    for y0 in (top+inset,bottom-inset-probe_h):
        y0=int(y0)
        if y0>=top and y0+probe_h<=bottom:
            profiles.append(np.mean(white[y0:y0+probe_h],axis=0))
    if not profiles:return (0,0)
    support=np.maximum.reduce(profiles)
    runs=_significant_runs(support>.985,max(8,round(20*scale)))
    if not runs:return (0,0)
    left,right=runs[0][0],runs[-1][1]
    return (left,right) if right-left>=min_safe_w else (0,0)


def _border_band_has_workspace(white, side, *, left, right, top, bottom, width, trim, toolbar_end):
    """Verify a visible edge using a band instead of one brittle pixel line."""
    h,w=white.shape
    trim=max(0,int(trim));width=max(1,int(width))
    y0=min(bottom,top+trim);y1=max(y0+1,bottom-trim)
    x0=min(right,left+trim);x1=max(x0+1,right-trim)
    if side=='left':
        if left<=0:return True
        band=white[y0:y1,max(0,left-width):left];line_axis=1
    elif side=='right':
        if right>=w:return True
        band=white[y0:y1,right:min(w,right+width)];line_axis=1
    elif side=='top':
        if top<=toolbar_end:return True
        band=white[max(toolbar_end,top-width):top,x0:x1];line_axis=0
    elif side=='bottom':
        if bottom>=h:return True
        band=white[bottom:min(h,bottom+width),x0:x1];line_axis=0
    else:raise ValueError(f'Unknown Paint canvas edge: {side}')
    if band.size==0:return False
    nonwhite=np.logical_not(band)
    density=float(np.mean(nonwhite))
    line_density=np.mean(nonwhite,axis=line_axis)
    thickness=band.shape[1] if line_axis==1 else band.shape[0]
    separator_threshold=max(.04,min(.20,.75/max(1,thickness)))
    separator_support=float(np.mean(line_density>=separator_threshold)) if line_density.size else 0.
    return density>=.14 or separator_support>=.80


def _visible_canvas_frame(white, *, toolbar_end, w, h, scale):
    """Find the blank document edges before applying a drawable inset."""
    min_safe_w=max(96,round(160*scale));min_safe_h=max(96,round(120*scale))
    row_fraction=min(.35,max(.06,(min_safe_w/max(1,w))*.72))
    bands=_significant_runs(np.mean(white,axis=1)>row_fraction,min_safe_h)
    if not bands:
        raise ValueError('Paint canvas visible area is too small. Enlarge Paint or select the drawing area manually.')
    if len(bands)>1:
        raise ValueError('More than one possible Paint canvas is visible. Close overlays or select the drawing area manually.')
    top,bottom=bands[0]

    left,right=_edge_supported_horizontal_span(white,top=top,bottom=bottom,scale=scale,min_safe_w=min_safe_w)
    if right-left<min_safe_w:
        edge_trim=max(2,round(8*scale));sample_top=min(bottom,top+edge_trim);sample_bottom=max(sample_top+1,bottom-edge_trim)
        left,right=_run(np.mean(white[sample_top:sample_bottom],axis=0)>.985)
    if right-left<min_safe_w:
        raise ValueError('Paint canvas visible area is too small. Enlarge Paint or select the drawing area manually.')

    verify_inset=max(2,round(5*scale));vy0=min(bottom,top+verify_inset);vy1=max(vy0+1,bottom-verify_inset)
    vx0=min(right,left+verify_inset);vx1=max(vx0+1,right-verify_inset)
    interior=white[vy0:vy1,vx0:vx1]
    if interior.size==0 or float(np.mean(interior))<.997:
        raise ValueError('Paint canvas is not blank or is covered. Clear it or select the area manually.')

    edge_tol=max(2,round(3*scale));clipped=[]
    if left<=edge_tol:clipped.append('left')
    if right>=w-edge_tol:clipped.append('right')
    if bottom>=h-edge_tol:clipped.append('bottom')

    band_width=max(3,round(6*scale));border_trim=max(4,round(12*scale))
    visible_sides=[]
    if left>edge_tol:visible_sides.append('left')
    if right<w-edge_tol:visible_sides.append('right')
    if top>toolbar_end:visible_sides.append('top')
    if bottom<h-edge_tol:visible_sides.append('bottom')
    if any(not _border_band_has_workspace(white,side,left=left,right=right,top=top,bottom=bottom,
                                           width=band_width,trim=border_trim,toolbar_end=toolbar_end)
           for side in visible_sides):
        raise ValueError('Paint canvas border is ambiguous or covered. Clear Paint or select the drawing area manually.')

    return (left,top,right,bottom),tuple(clipped)


def _detect_visible_canvas(white, *, toolbar_end, w, h, scale, screen_origin, ratio):
    """Return a safe visible Paint drawing area, including compact/clipped viewports."""
    (left,top,right,bottom),clipped=_visible_canvas_frame(white,toolbar_end=toolbar_end,w=w,h=h,scale=scale)
    # A pure-white Paint shadow is visually indistinguishable from the document
    # in a screenshot. Keep a conservative inward margin on auto-detected visible
    # borders so a few pixels of shadow/resize chrome can never become drawable.
    normal_inset=max(6,round(10*scale));clipped_inset=max(normal_inset+2,round(12*scale))
    x0=left+(clipped_inset if 'left' in clipped else normal_inset)
    x1=right-(clipped_inset if 'right' in clipped else normal_inset)
    y0=top+normal_inset;y1=bottom-(clipped_inset if 'bottom' in clipped else normal_inset)
    if x1-x0<max(64,round(120*scale)) or y1-y0<max(64,round(90*scale)):
        raise ValueError('Paint canvas safe visible area is too small. Enlarge Paint or select the drawing area manually.')
    box=(round(x0/ratio)+screen_origin[0],round(y0/ratio)+screen_origin[1],
         round(x1/ratio)+screen_origin[0],round(y1/ratio)+screen_origin[1])
    compact=(right-left)<w*.35 or (bottom-top)<max(1,h-toolbar_end)*.35
    return box,tuple(clipped),compact


@lru_cache(maxsize=1)
def _reference_templates():
    templates={}
    with Image.open(resource_path('assets/paint-tools-reference.png'), formats=('PNG',)) as raw:
        reference=raw.convert('RGB')
    try:
        for name,rx,ry in (('Pencil',268,88),('Fill',308,88),('Eraser',268,128)):
            with reference.crop((rx-262,ry-82,rx-238,ry-58)) as patch:
                rgb=np.asarray(patch,dtype=np.int16)
            mask=np.min(rgb,axis=2)<170
            dilation=np.asarray(Image.fromarray(mask.astype('uint8')*255).filter(ImageFilter.MaxFilter(3)))>0
            for value in (rgb,mask,dilation):value.setflags(write=False)
            templates[name]=(rgb,mask,dilation)
    finally:reference.close()
    return MappingProxyType(templates)


def _palette_search_box(ribbon, cancelled):
    """Find a small candidate search window; the complete grid and icons are verified next."""
    # These saturated red and blue swatches are five pitches apart. A coarse
    # sample locates their approximate centres even on a 4K display at 100% DPI.
    # Multiple or missing landmarks fall back to the broad ribbon scan.
    pixels = np.asarray(ribbon)[::4, ::4]
    centers = []
    for rgb in (ROW1[3], ROW1[8]):
        if cancelled():
            raise InterruptedError()
        mask = ((pixels[..., 0] == rgb[0]) & (pixels[..., 1] == rgb[1])
                & (pixels[..., 2] == rgb[2]))
        ys, xs = np.nonzero(mask)
        if not xs.size or xs.max()-xs.min() > 12 or ys.max()-ys.min() > 12:
            return None
        centers.append(((int(xs.min()) + int(xs.max()))*2, (int(ys.min()) + int(ys.max()))*2))
    (red_x, red_y), (blue_x, blue_y) = centers
    pitch = (blue_x - red_x) / 5
    if not 12 <= pitch <= 50 or abs(red_y - blue_y) > max(4, pitch*.15):
        return None
    anchor = red_x - 3*pitch
    return (max(0, math.floor(anchor - pitch)), max(0, math.floor(red_y - pitch)),
            min(ribbon.width, math.ceil(anchor + 10*pitch)), min(ribbon.height, math.ceil(red_y + 2*pitch)))


def _ribbon_controls(work, screen_origin, ratio, cancelled, search_box=None):
    w,rh=work.size
    if search_box is None:
        pos,colors,_=detect_color_swatches(work,cancelled=cancelled)
    else:
        with work.crop(search_box) as search:
            pos,colors,_=detect_color_swatches(search,offset=search_box[:2],cancelled=cancelled)
    if cancelled():raise InterruptedError()
    matches=[]
    for expected in ROW1[1:]:
        hits=[p for p,c in zip(pos,colors) if max(abs(a-b) for a,b in zip(c,expected))<=8]
        if len(hits)!=1:raise ValueError('Paint colour ribbon was not recognized. Expand the ribbon and use the light theme, or calibrate manually.')
        matches.append(hits[0])
    pitch,anchor_x=map(float,np.polyfit(np.arange(1,10),[p[0] for p in matches],1))
    scale=pitch/24.;anchor_y=float(np.median([p[1] for p in matches]))
    # At 200% a fitted pitch can exceed 48 by a fraction of a pixel because
    # the returned centers must be integer sample coordinates.
    if not .55<=scale<=2.03 or any(abs(p[0]-(anchor_x+(i+1)*pitch))>2.5*scale or abs(p[1]-anchor_y)>2.5*scale for i,p in enumerate(matches)):
        raise ValueError('Paint palette grid is ambiguous. Keep the complete ribbon visible.')
    positions=[];rgbs=[]
    for row,expected_row in enumerate((ROW1,ROW2)):
        for col,expected in enumerate(expected_row):
            x,y=round(anchor_x+col*pitch),round(anchor_y+row*pitch)
            if not (2<=x<w-2 and 2<=y<rh-2):raise ValueError('Paint palette is clipped.')
            with work.crop((x-1,y-1,x+2,y+2)) as patch:
                pixels=np.asarray(patch,dtype=np.int16)
            rgb=tuple(int(v) for v in np.median(pixels.reshape(-1,3),axis=0))
            if max(abs(a-b) for a,b in zip(rgb,expected))>10 or np.max(np.ptp(pixels.reshape(-1,3),axis=0))>10:
                raise ValueError('Paint colour cells are covered or changed. Close menus and try again.')
            positions.append((round(x/ratio)+screen_origin[0],round(y/ratio)+screen_origin[1]));rgbs.append(rgb)
    references=_reference_templates()
    tools={}
    for name,rx,ry in (('Pencil',268,88),('Fill',308,88),('Eraser',268,128)):
        if cancelled():raise InterruptedError()
        cx=anchor_x+(rx-794)*scale;cy=anchor_y+(ry-83)*scale;radius=12*scale
        if cx-radius<0 or cy-radius<0 or cx+radius>w or cy+radius>rh:raise ValueError('Paint tools are clipped.')
        ee,em,ed=references[name];best=(float('inf'),cx,cy)
        for dx in (-2,0,2):
            for dy in (-2,0,2):
                x,y=cx+dx*scale,cy+dy*scale
                bounds=round(x-radius),round(y-radius),round(x+radius),round(y+radius)
                if bounds[0]<0 or bounds[1]<0 or bounds[2]>w or bounds[3]>rh:
                    continue
                with work.crop(bounds) as patch:
                    with patch.resize((24,24)) as actual:
                        aa=np.asarray(actual,dtype=np.int16)
                am=np.min(aa,axis=2)<170
                ad=np.asarray(Image.fromarray(am.astype('uint8')*255).filter(ImageFilter.MaxFilter(3)))>0
                overlap=min(float(np.sum(am&ed))/max(1,int(am.sum())),float(np.sum(em&ad))/max(1,int(em.sum())))
                difference=float(np.mean(np.abs(aa-ee))) if overlap>=.75 else float('inf')
                if difference<best[0]:best=(difference,x,y)
        difference,cx,cy=best
        if difference>32:raise ValueError(f'Paint {name} icon could not be verified. Close menus or use manual tool calibration.')
        tools[name]=(round(cx/ratio)+screen_origin[0],round(cy/ratio)+screen_origin[1])
    if cancelled():raise InterruptedError()
    return tools, positions, rgbs, anchor_y, scale


def _blank_canvas_mask(work, toolbar_end, cancelled):
    # Only the viewport contributes to canvas evidence. Process bounded bands
    # and compare channels directly instead of reducing over interleaved RGB.
    white = np.zeros((work.height, work.width), dtype=bool)
    for y in range(toolbar_end, work.height, 128):
        if cancelled():
            raise InterruptedError()
        with work.crop((0, y, work.width, min(y + 128, work.height))) as band:
            pixels = np.asarray(band)
            white[y:y+len(pixels)] = ((pixels[..., 0] >= 253) & (pixels[..., 1] >= 253)
                                      & (pixels[..., 2] >= 253))
    return white


def detect_setup(image,screen_origin=(0,0),cancelled=lambda:False,canvas_box_override=None):
    if cancelled():raise InterruptedError()
    if image.width<64 or image.height<64:raise ValueError('Paint screenshot is too small to verify its ribbon.')
    screen_origin=screen_point(screen_origin,'Paint screen origin')
    screen_rect((*screen_origin,screen_origin[0]+image.width,screen_origin[1]+image.height),'Paint screenshot')
    ratio=min(1.,1920/image.width,1200/image.height)
    work_size = (max(1, round(image.width*ratio)), max(1, round(image.height*ratio)))
    with ExitStack() as owned:
        # Read ribbon landmarks in physical pixels independently of canvas
        # downsampling. Native controls on a large display can otherwise shrink
        # below the 5x5 solid-cell verification size.
        ribbon_height = min(image.height//2, 360)
        controls = None
        if ribbon_height*image.width <= 4_000_000:
            ribbon = owned.enter_context(image.crop((0,0,image.width,ribbon_height)))
            if ribbon.mode != 'RGB':
                ribbon = owned.enter_context(ribbon.convert('RGB'))
            box = _palette_search_box(ribbon, cancelled)
            if box is not None:
                try:
                    controls = _ribbon_controls(ribbon, screen_origin, 1., cancelled, box)
                except ValueError:
                    # Decorative colors sometimes resemble the two landmarks.
                    # Use the established full-grid verifier in that case.
                    pass
        work = image if work_size == image.size else owned.enter_context(image.resize(work_size))
        if work.mode != 'RGB':
            work = owned.enter_context(work.convert('RGB'))
        w,h=work.size
        if controls is None:
            with work.crop((0,0,w,min(h//2,360))) as ribbon:
                tools,positions,rgbs,anchor_y,scale = _ribbon_controls(ribbon, screen_origin, ratio, cancelled)
        else:
            tools,positions,rgbs,anchor_y,scale = controls
            anchor_y *= ratio
            scale *= ratio
        toolbar_end=min(h,round(anchor_y+100*scale))
        if canvas_box_override is not None:
            box=_validate_canvas_override(canvas_box_override,screen_origin=screen_origin,w=w,h=h,ratio=ratio,toolbar_end=toolbar_end,scale=scale,original_size=image.size)
            clipped_edges=();compact=False;visibility='manual-selected';confidence=.96
        else:
            white = _blank_canvas_mask(work, toolbar_end, cancelled)
            box,clipped_edges,compact=_detect_visible_canvas(white,toolbar_end=toolbar_end,w=w,h=h,scale=scale,
                                                              screen_origin=screen_origin,ratio=ratio)
            clipped=bool(clipped_edges);visibility='viewport-compact' if compact else ('viewport-clipped' if clipped else 'full')
            confidence=.85 if compact else (.87 if clipped else .90)
    if cancelled():raise InterruptedError()
    return {'tools':tools,'positions':positions,'rgbs':rgbs,'canvas_box':box,'palette_count':len(rgbs),
            'confidence':confidence,'method':'modern-paint-grid-and-icons-v7',
            'canvas_visibility':visibility,'canvas_clipped_edges':list(clipped_edges),
            'canvas_source':'manual-selection' if canvas_box_override is not None else 'auto-detected'}


def _guided_document_box(image, screen_origin, cancelled):
    # Limit the viewport pass, but keep the small grip samples in physical
    # pixels. A native 3-pixel handle can disappear on a downsampled 4K client.
    ratio = min(1., 1920 / image.width, 1200 / image.height)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    with ExitStack() as owned:
        work = image if size == image.size else owned.enter_context(image.resize(size))
        mask = _blank_canvas_mask(work, 0, cancelled)
        try:
            edges, clipped = _visible_canvas_frame(mask, toolbar_end=0, w=work.width,
                                                    h=work.height, scale=ratio)
        except ValueError:
            return None
    if clipped:
        return None
    # Integer resizing can produce different horizontal/vertical scale factors.
    factors = (image.width / size[0], image.height / size[1]) * 2
    frame = tuple(round(coordinate * factor) for coordinate, factor in zip(edges, factors))
    depth = verified_grip_depth(image, frame, cancelled)
    if not depth:
        return None
    inset = max(10, depth + 3, math.ceil(2 / ratio))
    left, top, right, bottom = frame
    if right - left - 2 * inset < 96 or bottom - top - 2 * inset < 80:
        return None
    ox, oy = screen_origin
    return left + inset + ox, top + inset + oy, right - inset + ox, bottom - inset + oy


def detect_canvas_area(image, screen_origin=(0, 0), cancelled=lambda: False):
    """Inspect a captured Paint client and return only verified canvas geometry."""
    if cancelled():
        raise InterruptedError()
    screen_origin = screen_point(screen_origin, 'Paint screen origin')
    client = (*screen_origin, screen_origin[0] + image.width, screen_origin[1] + image.height)
    with calibration_screenshot(image, client) as rgb:
        box = _guided_document_box(rgb, screen_origin, cancelled)
        if cancelled():
            raise InterruptedError()
        if box is not None:
            return {'canvas_box': box, 'canvas_confidence': .89, 'canvas_visibility': 'full',
                    'canvas_clipped_edges': [], 'canvas_source': 'auto-detected',
                    'method': 'paint-document-frame-and-grips'}
        # A clipped document or Paint version without recognizable grips can still
        # be identified by the established ribbon and icon verifier.
        try:
            result = detect_setup(rgb, screen_origin=screen_origin, cancelled=cancelled)
        except ValueError as exc:
            raise ValueError('Paint canvas could not be verified. Show the whole blank canvas and its resize handles, '
                             'expand the Paint ribbon, or mark the canvas manually.') from exc
    return {key: result[key] for key in ('canvas_box', 'canvas_visibility', 'canvas_clipped_edges',
                                         'canvas_source', 'method')} | {'canvas_confidence': result['confidence']}


def save_setup(result,meta,palette_path,tool_path=None):
    import json
    from pathlib import Path
    from Colors import validate_calibration,normalize_rgb
    from PaintTools import validate_tool_calibration,TOOL_FILE
    from CalibrationAnchors import make_anchor
    from RuntimePaths import replace_text_files
    anchor=make_anchor(meta['client_rect'])
    confidence=finite_confidence(result.get('confidence'))
    if confidence<.85:raise ValueError('Paint setup confidence is too low to save as verified.')
    positions=result['positions'];rgbs=result['rgbs']
    if len(positions)!=len(rgbs) or len(positions)!=20:raise ValueError('Verified Paint setup needs all 20 palette colors.')
    tools=validate_tool_calibration({'version':3,'tools':result['tools'],'anchor':anchor,
                                    'auto':{'method':result['method'],'confidence':confidence,'detected':list(result['tools'])}})
    if not all(name in tools['tools'] for name in ('Pencil','Fill')):raise ValueError('Verified Paint setup needs Pencil and Fill.')
    for point in list(positions)+list(tools['tools'].values()):
        from CalibrationValidation import point_in_rect
        if not point_in_rect(point,meta['client_rect']):raise ValueError('Paint setup contains a position outside its target.')
    palette={'version':4,'profile':'microsoft-paint','state':'verified','anchor':anchor,
             'colors':[{'name':f'Color {i+1}','position':list(screen_point(point)),'rgb':list(normalize_rgb(rgb))} for i,(point,rgb) in enumerate(zip(positions,rgbs))],
             'verification':{'method':str(result.get('method') or 'paint-auto-calibration'),'confidence':confidence,'source':'paint-screen-verification'}}
    validate_calibration(palette,profile_key='microsoft-paint')
    destination=Path(palette_path);tool_destination=Path(tool_path or TOOL_FILE)
    if destination.resolve()==tool_destination.resolve():raise ValueError('Paint palette and tools need different files.')
    replace_text_files({tool_destination:json.dumps(tools,ensure_ascii=False,indent=2,allow_nan=False),
                        destination:json.dumps(palette,ensure_ascii=False,indent=2,allow_nan=False)})
    return dict(result,target_meta=meta)


def choose_paint_window(windows):
    matches=[m for m in windows if PAINT_WINDOW_TITLE.search(str(m.get('title','')))]
    if len(matches)!=1:raise ValueError('Keep exactly one Paint window open and visible, then try Auto setup again.')
    return matches[0]
