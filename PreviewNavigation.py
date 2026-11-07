"""Preview navigation in source pixels, using the renderer's exact geometry."""
from __future__ import annotations

import math

from PreviewQuality import viewport_geometry


def reset_pan(canvas):
    canvas._preview_pan=(0.0,0.0)
    if hasattr(canvas,'_drag'):
        del canvas._drag


def clear_viewport(canvas):
    """An empty view must not keep geometry from its previously shown image."""
    reset_pan(canvas)
    for name in ('_preview_image_size','_preview_viewport_size','_preview_scale'):
        if hasattr(canvas,name):
            delattr(canvas,name)


def record_viewport(canvas,image_size,viewport_size,zoom=0,pan=(0,0)):
    """Record a successfully rendered view; no source-image reference is kept."""
    geometry=viewport_geometry(image_size,viewport_size,zoom,pan)
    canvas._preview_image_size=tuple(image_size)
    canvas._preview_viewport_size=tuple(viewport_size)
    canvas._preview_scale=geometry.scale
    canvas._preview_pan=geometry.pan


def relative_zoom(zoom,delta,fit_scale=1.0):
    """Step from the displayed Fit scale without reversing the requested direction."""
    zoom=float(zoom)
    delta=float(delta)
    if not math.isfinite(zoom) or not math.isfinite(delta):
        raise ValueError('Preview zoom and its step must be finite.')
    fit=zoom<=0
    if fit:
        try:
            current=float(fit_scale)
        except (TypeError,ValueError,OverflowError):
            current=1.0
        if not math.isfinite(current) or current<=0:
            current=1.0
    else:
        current=max(.125,min(8.0,zoom))
    if delta==0 or (delta>0 and current>=8.0) or (delta<0 and current<=.125):
        return 0.0 if fit else current
    return max(.125,min(8.0,current+delta))


def begin_pan(canvas,x,y):
    canvas._drag=(float(x),float(y))


def pan_by(canvas,dx,dy,zoom):
    """Move the visible source window by display pixels, clamping at each edge."""
    image_size=getattr(canvas,'_preview_image_size',None)
    viewport_size=getattr(canvas,'_preview_viewport_size',None)
    if zoom<=0 or image_size is None or viewport_size is None:
        return False
    dx,dy=float(dx),float(dy)
    if not math.isfinite(dx) or not math.isfinite(dy):
        return False
    previous=viewport_geometry(image_size,viewport_size,zoom,getattr(canvas,'_preview_pan',(0,0)))
    requested=(previous.pan[0]+dx/previous.scale,previous.pan[1]+dy/previous.scale)
    pan=viewport_geometry(image_size,viewport_size,zoom,requested).pan
    canvas._preview_pan=pan
    return pan!=previous.pan


def move_pan(canvas,x,y,zoom):
    """Consume each drag delta, including at an edge, so reversal is immediate."""
    if zoom<=0 or not hasattr(canvas,'_drag'):
        return False
    image_size=getattr(canvas,'_preview_image_size',None)
    viewport_size=getattr(canvas,'_preview_viewport_size',None)
    if image_size is None or viewport_size is None:
        return False
    x,y=float(x),float(y)
    if not math.isfinite(x) or not math.isfinite(y):
        return False
    previous=viewport_geometry(image_size,viewport_size,zoom,getattr(canvas,'_preview_pan',(0,0)))
    old_x,old_y=canvas._drag
    requested=(previous.pan[0]-(x-old_x)/previous.scale,
               previous.pan[1]-(y-old_y)/previous.scale)
    pan=viewport_geometry(image_size,viewport_size,zoom,requested).pan
    canvas._drag=(x,y)
    canvas._preview_pan=pan
    return pan!=previous.pan
