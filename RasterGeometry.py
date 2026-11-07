"""Integer raster helpers that preserve the original line's sampling phase."""
from __future__ import annotations

from bisect import bisect_left, bisect_right


def clipped_bresenham(start, end, width: int, height: int, *, before: int = 0, after: int = 0):
    """Yield exactly the Bresenham centres whose square brush can hit the canvas.

    Clipping endpoints and starting Bresenham again changes diagonal pixels.
    Instead, derive each lattice point from its original major-axis position
    and skip the invisible prefix/suffix. Work is bounded by the canvas's major
    dimension plus the brush footprint, even for far-off-canvas endpoints.
    """
    if width <= 0 or height <= 0:
        return
    x0, y0 = map(int, start)
    x1, y1 = map(int, end)
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x1 >= x0 else -1), (1 if y1 >= y0 else -1)
    xmin, xmax = -int(after), int(width) - 1 + int(before)
    ymin, ymax = -int(after), int(height) - 1 + int(before)
    if not max(dx, dy):
        if xmin <= x0 <= xmax and ymin <= y0 <= ymax:
            yield x0, y0
        return
    horizontal = dx >= dy
    major, minor = (dx, dy) if horizontal else (dy, dx)
    origin, direction = (x0, sx) if horizontal else (y0, sy)
    lower, upper = (xmin, xmax) if horizontal else (ymin, ymax)
    k0, k1 = sorted(((lower - origin) * direction, (upper - origin) * direction))
    for k in range(max(0, k0), min(major, k1) + 1):
        offset = (k * minor + major // 2) // major
        x, y = ((x0 + sx * k, y0 + sy * offset) if horizontal
                else (x0 + sx * offset, y0 + sy * k))
        if xmin <= x <= xmax and ymin <= y <= ymax:
            yield x, y


def clipped_interpolated_line(start, end, width: int, height: int, *, before: int = 0, after: int = 0):
    """Clip the hybrid simulator's rounded interpolation without rephasing it."""
    if width <= 0 or height <= 0:return
    x0,y0=map(int,start);x1,y1=map(int,end)
    dx,dy=x1-x0,y1-y0;steps=max(abs(dx),abs(dy),1)
    horizontal=abs(dx)>=abs(dy)
    origin=x0 if horizontal else y0
    direction=1 if (dx if horizontal else dy)>=0 else -1
    lower=-after;upper=(width if horizontal else height)-1+before
    begin,end=sorted(((lower-origin)*direction,(upper-origin)*direction))
    for index in range(max(0,begin),min(steps,end)+1):
        ratio=index/steps
        x,y=round(x0+dx*ratio),round(y0+dy*ratio)
        if -after<=x<=width-1+before and -after<=y<=height-1+before:
            yield x,y


def nearest_axis_samples(source_size: int, target_size: int, *, cancelled=lambda:False):
    """Return Pillow-compatible NEAREST source samples for one preview axis.

    An exact rational formula differs at some integer boundaries: Pillow's
    sampler advances a floating-point position, so its accumulated rounding is
    part of the observable raster. Retain that phase with O(target_size) space,
    independent of the source image's pixel count.
    """
    if source_size<=0 or target_size<=0:raise ValueError('Raster dimensions must be positive.')
    scale=source_size/target_size
    position=scale*.5
    samples=[]
    for index in range(target_size):
        if index%1024==0 and cancelled():raise InterruptedError()
        samples.append(int(position))
        position+=scale
    if cancelled():raise InterruptedError()
    return samples


def project_pixel_interval(first: int, last: int, source_size: int, target_size: int, *, samples=None):
    """Map inclusive source pixels to the Pillow NEAREST destination interval."""
    if samples is None:samples=nearest_axis_samples(source_size,target_size)
    return bisect_left(samples,first),bisect_right(samples,last)-1
