"""Gartic Phone Engine v2 planning and layout helpers.

Pure deterministic code only: no native mouse input, no browser access and no
network calls.  The helpers are intentionally conservative so failed detection
returns a low-confidence result instead of guessing clickable coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
import math
from typing import Iterable, Sequence

from GarticPhoneLayout import REFERENCE_CANVAS_ASPECT

Point = tuple[int, int]
Path = tuple[Point, ...]
Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class CanvasDetection:
    found: bool
    box: Box | None
    confidence: float
    aspect: float
    white_score: float
    frame_score: float
    reason: str

    def as_options(self) -> dict:
        return {
            "found": self.found,
            "box": self.box,
            "confidence": self.confidence,
            "aspect": self.aspect,
            "white_score": self.white_score,
            "frame_score": self.frame_score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GarticRuntimeProfile:
    seconds_left: int | None
    max_colors: int
    max_paths: int
    stroke_step_px: float
    precision: str
    adaptive_detail: str
    color_order: str
    reason: str

    def as_options(self) -> dict:
        return {
            "seconds_left": self.seconds_left,
            "max_colors": self.max_colors,
            "max_paths": self.max_paths,
            "stroke_step_px": self.stroke_step_px,
            "precision": self.precision,
            "adaptive_detail": self.adaptive_detail,
            "color_order": self.color_order,
            "reason": self.reason,
        }


def _near_white(rgb) -> bool:
    r, g, b = map(int, rgb[:3])
    return r >= 242 and g >= 242 and b >= 242 and max(r, g, b) - min(r, g, b) <= 18


def _purple_frame(rgb) -> bool:
    r, g, b = map(int, rgb[:3])
    return b >= 95 and r >= 55 and g <= 100 and (b - g) >= 35


def _flood_largest_white(mask: list[bytearray], *, min_area: int) -> tuple[Box | None, int]:
    h = len(mask)
    w = len(mask[0]) if h else 0
    visited = [bytearray(w) for _ in range(h)]
    best_box: Box | None = None
    best_area = 0
    for sy in range(h):
        row = mask[sy]
        for sx in range(w):
            if not row[sx] or visited[sy][sx]:
                continue
            visited[sy][sx] = 1
            stack = [(sx, sy)]
            left = right = sx
            top = bottom = sy
            area = 0
            while stack:
                x, y = stack.pop()
                area += 1
                if x < left: left = x
                elif x > right: right = x
                if y < top: top = y
                elif y > bottom: bottom = y
                nx = x - 1
                if nx >= 0 and mask[y][nx] and not visited[y][nx]:
                    visited[y][nx] = 1; stack.append((nx, y))
                nx = x + 1
                if nx < w and mask[y][nx] and not visited[y][nx]:
                    visited[y][nx] = 1; stack.append((nx, y))
                ny = y - 1
                if ny >= 0 and mask[ny][x] and not visited[ny][x]:
                    visited[ny][x] = 1; stack.append((x, ny))
                ny = y + 1
                if ny < h and mask[ny][x] and not visited[ny][x]:
                    visited[ny][x] = 1; stack.append((x, ny))
            if area >= min_area and area > best_area:
                best_area = area
                best_box = (left, top, right + 1, bottom + 1)
    return best_box, best_area


def _frame_score(image, box: Box, pad: int = 7) -> float:
    if image.mode != 'RGB':
        with closing(image.convert('RGB')) as rgb:
            return _frame_score(rgb,box,pad)
    w, h = image.size
    left, top, right, bottom = box
    samples = []
    for x in range(max(0, left-pad), min(w, right+pad)):
        for y in (max(0, top-pad), min(h-1, bottom+pad-1)):
            samples.append(image.getpixel((x, y)))
    for y in range(max(0, top-pad), min(h, bottom+pad)):
        for x in (max(0, left-pad), min(w-1, right+pad-1)):
            samples.append(image.getpixel((x, y)))
    if not samples:
        return 0.0
    return sum(1 for rgb in samples if _purple_frame(rgb)) / len(samples)



def _flood_components(mask: list[bytearray], *, min_area: int, limit: int = 48, cancelled=lambda: False) -> list[tuple[Box, int]]:
    """Return the largest connected mask components without assuming the largest is canvas."""
    h=len(mask);w=len(mask[0]) if h else 0
    visited=[bytearray(w) for _ in range(h)]
    out=[]
    for sy in range(h):
        if cancelled():raise InterruptedError()
        for sx in range(w):
            if not mask[sy][sx] or visited[sy][sx]:
                continue
            visited[sy][sx]=1;stack=[(sx,sy)]
            left=right=sx;top=bottom=sy;area=0
            while stack:
                x,y=stack.pop();area+=1
                if area%1024==0 and cancelled():raise InterruptedError()
                left=min(left,x);right=max(right,x);top=min(top,y);bottom=max(bottom,y)
                for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if 0<=nx<w and 0<=ny<h and mask[ny][nx] and not visited[ny][nx]:
                        visited[ny][nx]=1;stack.append((nx,ny))
            if area>=min_area:
                out.append(((left,top,right+1,bottom+1),area))
    out.sort(key=lambda item:item[1],reverse=True)
    return out[:max(1,int(limit))]


def _sample_white_fraction(image, box: Box, *, step: int = 6) -> float:
    if image.mode != 'RGB':
        with closing(image.convert('RGB')) as rgb:
            return _sample_white_fraction(rgb,box,step=step)
    l,t,r,b=box
    hit=total=0
    stride=max(2,int(step))
    for y in range(max(0,t),min(image.height,b),stride):
        for x in range(max(0,l),min(image.width,r),stride):
            total+=1;hit+=1 if _near_white(image.getpixel((x,y))) else 0
    return hit/max(1,total)

def detect_gartic_canvas(image, *, downsample: int = 2, min_canvas_area_ratio: float = 0.08,
                         cancelled=lambda: False) -> CanvasDetection:
    """Detect Gartic's drawable canvas without assuming the largest white area wins.

    Blank canvases are ranked from all sizeable near-white components. If the
    canvas is already partly drawn, a second read-only pass looks for a large
    non-frame component bounded by Gartic's violet frame. Aspect, frame evidence
    and area must agree before coordinates are returned.
    """
    if cancelled():raise InterruptedError()
    try:minimum=float(min_canvas_area_ratio)
    except (TypeError,ValueError,OverflowError) as error:raise ValueError('Canvas area ratio must be finite and between zero and one.') from error
    if not math.isfinite(minimum) or not 0<=minimum<=1:
        raise ValueError('Canvas area ratio must be finite and between zero and one.')
    if image.mode != 'RGB':
        with closing(image.convert('RGB')) as rgb:
            return _detect_gartic_canvas_rgb(rgb,downsample=downsample,min_canvas_area_ratio=minimum,cancelled=cancelled)
    return _detect_gartic_canvas_rgb(image,downsample=downsample,min_canvas_area_ratio=minimum,cancelled=cancelled)


def _detect_gartic_canvas_rgb(image, *, downsample, min_canvas_area_ratio, cancelled):
    w,h=image.size
    if w<200 or h<120:
        return CanvasDetection(False,None,0.0,0.0,0.0,0.0,'image too small')
    step=max(1,int(downsample));sw,sh=(w+step-1)//step,(h+step-1)//step

    def make_mask(predicate):
        mask=[bytearray(sw) for _ in range(sh)]
        for yy in range(sh):
            if yy%8==0 and cancelled():raise InterruptedError()
            y=min(h-1,yy*step)
            for xx in range(sw):
                x=min(w-1,xx*step)
                if predicate(image.getpixel((x,y))):mask[yy][xx]=1
        return mask

    def full_box(small):
        l,t,r,b=small
        return (l*step,t*step,min(w,r*step),min(h,b*step))

    candidates=[]
    # Do not let a larger white page/panel hide a correctly-shaped canvas.
    white_mask=make_mask(_near_white)
    white_min=max(24,int(sw*sh*min(.035,max(.012,float(min_canvas_area_ratio)*.45))))
    for small,area in _flood_components(white_mask,min_area=white_min,cancelled=cancelled):
        candidates.append(('white',full_box(small),area))

    # A drawing can fragment the white background. Gartic's violet frame usually
    # still isolates the entire drawable surface, so rank non-frame components too.
    structural_mask=make_mask(lambda rgb:not _purple_frame(rgb))
    structural_min=max(36,int(sw*sh*.035))
    for small,area in _flood_components(structural_mask,min_area=structural_min,cancelled=cancelled):
        candidates.append(('frame',full_box(small),area))

    best=None;best_eligible=None
    for source,box,component_area in candidates:
        if cancelled():raise InterruptedError()
        l,t,r,b=box;bw,bh=r-l,b-t
        if bw<max(180,int(w*.22)) or bh<max(105,int(h*.16)):
            continue
        aspect=bw/max(1,bh)
        rel=abs(aspect-REFERENCE_CANVAS_ASPECT)/REFERENCE_CANVAS_ASPECT
        aspect_score=max(0.0,1.0-rel/.22)
        if aspect_score<=0.0:continue
        area_ratio=(bw*bh)/max(1.0,float(w*h))
        size_score=max(0.0,min(1.0,area_ratio/.24))
        frame=_frame_score(image,box,pad=max(4,int(min(w,h)*.006)))
        white=_sample_white_fraction(image,box,step=max(4,step*3))
        cx=((l+r)*.5)/max(1,w);cy=((t+b)*.5)/max(1,h)
        center=max(0.0,1.0-(abs(cx-.57)/.62+abs(cy-.54)/.72)*.5)
        if source=='white':
            confidence=.52*aspect_score+.27*white+.13*min(1.0,frame*4.0)+.05*size_score+.03*center
            evidence_ok=white>=.48
        else:
            confidence=.57*aspect_score+.24*min(1.0,frame*5.0)+.11*size_score+.08*center
            # Structural fallback is accepted only when the Gartic frame is visible.
            evidence_ok=frame>=.018
        confidence=max(0.0,min(1.0,confidence))
        rank=confidence + min(.025,frame*.08)
        candidate=(rank,source,box,confidence,aspect,white,frame,aspect_score,area_ratio,evidence_ok)
        if best is None or rank>best[0]:
            best=candidate
        if (confidence>=.68 and aspect_score>=.58 and area_ratio>=max(.055,min_canvas_area_ratio) and evidence_ok
                and (best_eligible is None or rank>best_eligible[0])):
            best_eligible=candidate

    if cancelled():raise InterruptedError()
    if best is None:
        return CanvasDetection(False,None,0.0,0.0,0.0,0.0,'no plausible Gartic canvas region')
    _,source,box,confidence,aspect,white,frame,aspect_score,area_ratio,evidence_ok=best_eligible or best
    found=best_eligible is not None
    if found:
        reason='gartic canvas matched' if source=='white' else 'gartic canvas matched by structural frame fallback'
        return CanvasDetection(True,box,confidence,aspect,white,frame,reason)
    return CanvasDetection(False,None,confidence,aspect,white,frame,'candidate needs user confirmation')

def choose_runtime_profile(seconds_left: int | None, *, canvas_size: tuple[int, int] | None = None,
                           requested_speed: str = 'Fast') -> GarticRuntimeProfile:
    """Return deterministic Gartic settings for normal/turbo/time-critical phases."""
    try:
        seconds = None if seconds_left is None else max(0, int(seconds_left))
    except (TypeError, ValueError):
        seconds = None
    speed = str(requested_speed or 'Fast')
    pixels = 0
    if canvas_size:
        try:
            pixels = max(0, int(canvas_size[0])) * max(0, int(canvas_size[1]))
        except Exception:
            pixels = 0
    if seconds is not None and seconds <= 20:
        return GarticRuntimeProfile(seconds, 4, 350, 24.0, 'Normal', 'Extreme simplify', 'dark-first', 'final seconds turbo')
    if seconds is not None and seconds <= 45:
        return GarticRuntimeProfile(seconds, 6, 650, 20.0, 'Normal', 'Strong simplify', 'dark-first', 'low time turbo')
    if pixels and pixels > 1_200_000:
        return GarticRuntimeProfile(seconds, 7, 850, 18.0, 'Normal', 'Strong simplify', 'dark-first', 'large canvas turbo')
    if speed == 'Safe':
        return GarticRuntimeProfile(seconds, 8, 1000, 12.0, 'High', 'Balanced', 'largest-first', 'safe quality')
    return GarticRuntimeProfile(seconds, 8, 1000, 16.0, 'Normal', 'Strong simplify', 'largest-first', 'default gartic turbo')


def _dist(a: Point, b: Point) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _clean(path: Sequence[Point]) -> Path:
    out: list[Point] = []
    for x, y in path:
        p = (int(x), int(y))
        if not out or out[-1] != p:
            out.append(p)
    return tuple(out)


def stroke_graph_order(paths: Sequence[Sequence[Point]], *, allow_reverse: bool = True,
                       window: int = 192, cancelled=lambda: False) -> tuple[list[Path], dict]:
    """Bounded nearest-neighbour StrokeGraph order for one color batch.

    It changes only order and direction. It never adds connector strokes, so the
    geometry remains safe for CanvasGuard and SafePolygon clipping.
    """
    remaining = [_clean(p) for p in paths if p]
    before = len(remaining)
    if before < 3:
        return remaining, {'stroke_graph': True, 'before_paths': before, 'after_paths': before,
                           'pen_up_before': 0.0, 'pen_up_after': 0.0, 'travel_reduction': 0.0}

    def pen_up(seq: Sequence[Path]) -> float:
        total = 0.0; prev = None
        for path in seq:
            if prev is not None:
                total += _dist(prev, path[0])
            prev = path[-1]
        return total

    before_dist = pen_up(remaining)
    out: list[Path] = []
    current = remaining.pop(0)
    out.append(current)
    cursor = current[-1]
    limit_window = max(8, min(int(window), 256))
    while remaining:
        if cancelled():
            raise InterruptedError()
        limit = min(limit_window, len(remaining))
        best_i = 0; best_rev = False; best = float('inf')
        for i in range(limit):
            path = remaining[i]
            d0 = _dist(cursor, path[0])
            d1 = _dist(cursor, path[-1]) if allow_reverse and len(path) > 1 else float('inf')
            if d1 < d0:
                d = d1; rev = True
            else:
                d = d0; rev = False
            d += i * 1e-5
            if d < best:
                best_i, best_rev, best = i, rev, d
        chosen = remaining.pop(best_i)
        if best_rev:
            chosen = tuple(reversed(chosen))
        out.append(chosen)
        cursor = chosen[-1]
    after_dist = pen_up(out)
    return out, {
        'stroke_graph': True,
        'before_paths': before,
        'after_paths': len(out),
        'pen_up_before': before_dist,
        'pen_up_after': after_dist,
        'travel_reduction': 0.0 if before_dist <= 0 else max(0.0, min(1.0, 1.0 - after_dist / before_dist)),
        'allow_reverse': bool(allow_reverse),
        'window': limit_window,
    }
