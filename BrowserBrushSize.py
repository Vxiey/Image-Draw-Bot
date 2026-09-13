"""Automatic browser brush-size detection/selection for supported drawing games.

The detector stays deliberately conservative: control locations are derived from
an already verified canvas/palette layout, then checked visually before any click.
If the control row cannot be verified, no guessed click is generated and Image
Draw Bot uses a conservative brush guard fallback instead.

Gartic exposes five user-facing brush levels. Image Draw Bot now treats those as
levels 1..5 while retaining a separate calibrated physical footprint ladder for
CanvasGuard, raster simulation and execution-cost planning.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

SUPPORTED = frozenset({'gartic-phone', 'gartic-io', 'skribbl', 'skribbl-fast', 'sketchheads'})
GARTIC_PROFILES = frozenset({'gartic-phone', 'gartic-io'})
GARTIC_LEVELS = (1, 2, 3, 4, 5)

POLICIES = {
    # Physical canvas footprints for the five Gartic controls. The public/user
    # setting is 1..5; these values remain internal safety geometry.
    'gartic-phone': {'sizes': (2, 4, 8, 16, 28), 'levels': GARTIC_LEVELS, 'safe_index': 1},
    'gartic-io': {'sizes': (2, 4, 8, 16, 28), 'levels': GARTIC_LEVELS, 'safe_index': 1},
    'skribbl': {'sizes': (4, 8, 16, 32), 'safe_index': 1},
    'skribbl-fast': {'sizes': (4, 8, 16, 32), 'safe_index': 1},
    'sketchheads': {'sizes': (4, 8, 14), 'safe_index': 1},
}


def _rgb_distance(a, b):
    return sqrt(sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)))


def _clamp_point(point, rect):
    x, y = map(int, point); l, t, r, b = map(int, rect)
    return max(l, min(r-1, x)), max(t, min(b-1, y))


def _candidate_positions(profile_key, client_rect, canvas_box=None, palette_box=None):
    l, t, r, b = map(int, client_rect); cw, ch = r-l, b-t
    canvas = tuple(map(int, canvas_box)) if isinstance(canvas_box, (tuple, list)) and len(canvas_box) == 4 else None
    palette = tuple(map(int, palette_box)) if isinstance(palette_box, (tuple, list)) and len(palette_box) == 4 else None
    if profile_key in GARTIC_PROFILES and canvas:
        x0, y0, x1, y1 = canvas; w = x1-x0; h = y1-y0
        y = y1 + max(28, min(int(ch*.095), int(h*.17)))
        xs = [x0 + w*f for f in (.05, .118, .186, .254, .322)]
        return [_clamp_point((x, y), client_rect) for x in xs]
    if profile_key in ('skribbl', 'skribbl-fast') and canvas:
        x0, y0, x1, y1 = canvas; w = x1-x0
        y = y1 + max(18, min(34, int(ch*.045)))
        xs = [x0 + w*f for f in (.71, .785, .86, .935)]
        return [_clamp_point((x, y), client_rect) for x in xs]
    if profile_key == 'sketchheads':
        if palette:
            px0, py0, px1, py1 = palette; y = (py0+py1)//2
            scale = max(18, min(34, int(ch*.030)))
            xs = (px0-4.95*scale, px0-3.95*scale, px0-2.45*scale)
            return [_clamp_point((x, y), client_rect) for x in xs]
        if canvas:
            x0, y0, x1, y1 = canvas; w=x1-x0
            y = min(b-12, y1 + max(18, int(ch*.04)))
            return [_clamp_point((x0+w*f,y), client_rect) for f in (.26,.29,.325)]
    return []


def _patch(image, client_rect, point, radius=15):
    l,t,_,_ = map(int, client_rect); x,y=map(int,point)
    x -= l; y -= t
    left=max(0,x-radius);top=max(0,y-radius);right=min(image.width,x+radius+1);bottom=min(image.height,y+radius+1)
    if right-left < 7 or bottom-top < 7:
        return None
    return image.crop((left,top,right,bottom)).convert('RGB')


def _control_score(patch):
    if patch is None:return 0.0
    w,h=patch.size;cx=w//2;cy=h//2
    center=patch.getpixel((cx,cy))
    corners=[patch.getpixel((1,1)),patch.getpixel((w-2,1)),patch.getpixel((1,h-2)),patch.getpixel((w-2,h-2))]
    ring=[]
    radius=max(3,min(w,h)//3)
    for dx,dy in ((radius,0),(-radius,0),(0,radius),(0,-radius),(radius//2,radius//2),(-radius//2,radius//2)):
        ring.append(patch.getpixel((max(0,min(w-1,cx+dx)),max(0,min(h-1,cy+dy)))))
    background=tuple(sum(p[i] for p in corners)//len(corners) for i in range(3))
    contrast=max([_rgb_distance(center,background)]+[_rgb_distance(p,background) for p in ring])
    diversity=max((_rgb_distance(a,b) for a in ring for b in ring),default=0.0)
    return min(100.0, contrast*.65 + diversity*.35)


def _selection_score(patch):
    if patch is None:return 0.0
    w,h=patch.size;cx=w//2;cy=h//2
    outer=[];inner=[]
    for radius,target in ((max(4,min(w,h)//2-3),outer),(max(2,min(w,h)//3),inner)):
        for dx,dy in ((radius,0),(-radius,0),(0,radius),(0,-radius)):
            target.append(patch.getpixel((max(0,min(w-1,cx+dx)),max(0,min(h-1,cy+dy)))))
    outer_luma=sum(sum(p)/3 for p in outer)/max(1,len(outer))
    inner_luma=sum(sum(p)/3 for p in inner)/max(1,len(inner))
    return abs(outer_luma-inner_luma)


def _nearest_index(sizes, brush_px):
    brush=max(1,float(brush_px or 1))
    return min(range(len(sizes)), key=lambda i: abs(float(sizes[i])-brush))


def _automatic_guard_px(sizes, requested, effective):
    """Reserve enough CanvasGuard inset for one safe automatic upshift."""
    base=max(1,int(effective));requested=max(1,int(requested))
    cap=max(base,requested*2)
    allowed=[int(v) for v in sizes if int(v)<=cap]
    return max(allowed) if allowed else base


def _requested_index(key, sizes, requested):
    if key in GARTIC_PROFILES:
        level=max(1,min(5,int(requested)))
        return level-1, level
    return _nearest_index(sizes,requested), int(requested)


@dataclass(frozen=True)
class BrowserBrushPlan:
    profile_key: str
    control_positions: tuple
    nominal_sizes: tuple
    target_index: int
    selected_index: int | None
    confidence: float
    target_position: tuple[int,int] | None
    requested_px: int
    effective_px: int
    safe_guard_px: int
    method: str

    def as_dict(self):
        controls_verified=(bool(self.target_position) and float(self.confidence)>=.58 and
                           len(self.control_positions)==len(self.nominal_sizes) and len(self.nominal_sizes)>1)
        verified_sizes=list(map(int,self.nominal_sizes)) if controls_verified else []
        is_gartic=self.profile_key in GARTIC_PROFILES
        levels=list(GARTIC_LEVELS) if is_gartic else []
        effective_index=None
        try:effective_index=list(map(int,self.nominal_sizes)).index(int(self.effective_px))
        except (ValueError,TypeError):pass
        effective_level=(effective_index+1) if is_gartic and effective_index is not None else None
        requested_level=max(1,min(5,int(self.requested_px))) if is_gartic else None
        return {
            'profile_key':self.profile_key,'control_positions':[list(p) for p in self.control_positions],
            'nominal_sizes':list(self.nominal_sizes),'verified_sizes':verified_sizes,
            'nominal_levels':levels,'verified_levels':levels if controls_verified and is_gartic else [],
            'requested_level':requested_level,'effective_level':effective_level,
            'requested_physical_px':int(self.nominal_sizes[self.target_index]) if self.nominal_sizes else int(self.requested_px),
            'dynamic_guard':bool(verified_sizes),'target_index':int(self.target_index),
            'selected_index':self.selected_index,'confidence':float(self.confidence),
            'target_position':list(self.target_position) if self.target_position else None,
            'requested_px':int(self.requested_px),'effective_px':int(self.effective_px),
            'safe_guard_px':int(self.safe_guard_px),'method':self.method,
        }


def plan_browser_brush_size(profile_key, screenshot, client_rect, *, canvas_box=None, palette_box=None, requested_px=3):
    key=str(profile_key or '').lower(); requested=max(1,int(round(float(requested_px or 3))))
    if key not in SUPPORTED:
        return BrowserBrushPlan(key,(),(),0,None,0.0,None,requested,requested,max(requested,4),'unsupported profile')
    policy=POLICIES[key];sizes=tuple(policy['sizes']);positions=tuple(_candidate_positions(key,client_rect,canvas_box,palette_box))
    target,requested=_requested_index(key,sizes,requested);safe_index=int(policy['safe_index'])
    if len(positions)!=len(sizes):
        safe=int(sizes[safe_index])
        return BrowserBrushPlan(key,positions,sizes,target,None,0.0,None,requested,safe,max(safe,12),'control geometry unavailable; safe fallback')
    screenshot=screenshot.convert('RGB')
    patches=[_patch(screenshot,client_rect,p) for p in positions]
    scores=[_control_score(p) for p in patches]
    good=sum(score>=12 for score in scores)
    confidence=max(0.0,min(1.0,(sum(min(60.0,s) for s in scores)/(max(1,len(scores))*60.0))*.70 + (good/len(scores))*.30))
    select_scores=[_selection_score(p) for p in patches]
    selected=None
    if select_scores:
        order=sorted(range(len(select_scores)),key=lambda i:select_scores[i],reverse=True)
        if select_scores[order[0]]>=12 and (len(order)==1 or select_scores[order[0]]-select_scores[order[1]]>=4):
            selected=order[0]
    target_position=positions[target] if confidence>=.58 else None
    if target_position is not None and isinstance(canvas_box,(tuple,list)) and len(canvas_box)==4:
        cx0,cy0,cx1,cy1=map(int,canvas_box);tx,ty=target_position
        if cx0-4 <= tx <= cx1+4 and cy0-4 <= ty <= cy1+4:
            target_position=None;confidence=min(confidence,.40)
    effective=int(sizes[target]) if target_position is not None else int(sizes[safe_index])
    physical_requested=int(sizes[target])
    safe_guard=(
        _automatic_guard_px(sizes,physical_requested,effective)
        if target_position is not None
        else max(effective,12)
    )
    method=('verified Gartic brush level 1-5 with calibrated physical footprint'
            if target_position and key in GARTIC_PROFILES else
            'verified profile-relative brush controls' if target_position else
            'visual confidence low; safe fallback')
    return BrowserBrushPlan(key,positions,sizes,target,selected,confidence,target_position,requested,effective,safe_guard,method)


def capture_control_patch(position, radius=18):
    from PIL import ImageGrab
    x,y=map(int,position);r=max(8,min(40,int(radius)))
    return ImageGrab.grab(bbox=(x-r,y-r,x+r+1,y+r+1),all_screens=True).convert('RGB')


def patch_change_score(before, after):
    if before is None or after is None or before.size!=after.size:return 0.0
    a=list(before.getdata());b=list(after.getdata())
    if not a:return 0.0
    changed=sum(1 for p,q in zip(a,b) if max(abs(int(p[i])-int(q[i])) for i in range(3))>=8)
    return 100.0*changed/len(a)
