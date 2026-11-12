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
from CalibrationValidation import (screen_rect, screen_point, contained_rect,
                                   point_in_rect, screenshot_matches, bounded_number,
                                   finite_confidence, nonnegative_integer)

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


def _valid_positions(points, client_rect):
    points = [tuple(map(int, point)) for point in points]
    if len(set(points)) != len(points) or any(not point_in_rect(p, client_rect) for p in points):
        return []
    return points


def conservative_brush_guard(profile_key, requested_px=3):
    """Bound an unknown selection by every size in the known profile ladder."""
    key = str(profile_key or '').lower()
    try:
        requested = max(1, round(bounded_number(requested_px, 'Brush size', minimum=1, maximum=10000)))
    except ValueError:
        requested = 3
    policy = POLICIES.get(key)
    if policy:
        return max(max(policy['sizes']), requested if key not in GARTIC_PROFILES else 1)
    return max(12, requested)


def _candidate_positions(profile_key, client_rect, canvas_box=None, palette_box=None):
    l, t, r, b = map(int, client_rect); cw, ch = r-l, b-t
    canvas = tuple(map(int, canvas_box)) if isinstance(canvas_box, (tuple, list)) and len(canvas_box) == 4 else None
    palette = tuple(map(int, palette_box)) if isinstance(palette_box, (tuple, list)) and len(palette_box) == 4 else None
    if profile_key in GARTIC_PROFILES and canvas:
        x0, y0, x1, y1 = canvas; w = x1-x0; h = y1-y0
        y = y1 + max(28, min(int(ch*.095), int(h*.17)))
        xs = [x0 + w*f for f in (.05, .118, .186, .254, .322)]
        return _valid_positions([(x, y) for x in xs], client_rect)
    if profile_key in ('skribbl', 'skribbl-fast') and canvas:
        x0, y0, x1, y1 = canvas; w = x1-x0
        y = y1 + max(18, min(34, int(ch*.045)))
        xs = [x0 + w*f for f in (.71, .785, .86, .935)]
        return _valid_positions([(x, y) for x in xs], client_rect)
    if profile_key == 'sketchheads':
        if palette:
            px0, py0, px1, py1 = palette; y = (py0+py1)//2
            scale = max(18, min(34, int(ch*.030)))
            xs = (px0-4.95*scale, px0-3.95*scale, px0-2.45*scale)
            return _valid_positions([(x, y) for x in xs], client_rect)
        if canvas:
            x0, y0, x1, y1 = canvas; w=x1-x0
            y = min(b-12, y1 + max(18, int(ch*.04)))
            return _valid_positions([(x0+w*f,y) for f in (.26,.29,.325)], client_rect)
    return []


def _patch(image, client_rect, point, radius=15):
    l,t,_,_ = map(int, client_rect); x,y=map(int,point)
    x -= l; y -= t
    left=x-radius;top=y-radius;right=x+radius+1;bottom=y+radius+1
    if not (0<=left<right<=image.width and 0<=top<bottom<=image.height):
        return None
    patch = image.crop((left,top,right,bottom))
    if patch.mode == 'RGB':
        return patch
    try:
        return patch.convert('RGB')
    finally:
        patch.close()


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
    center=patch.getpixel((cx,cy))
    corners=[patch.getpixel(p) for p in ((1,1),(w-2,1),(1,h-2),(w-2,h-2))]
    background=tuple(sum(p[i] for p in corners)/4 for i in range(3))
    bg_luma=sum(background)/3;center_luma=sum(center)/3;best=0.0
    for radius in range(3,min(w,h)//2):
        supported=[]
        for dx,dy in ((radius,0),(-radius,0),(0,radius),(0,-radius)):
            color=patch.getpixel((cx+dx,cy+dy));luma=sum(color)/3
            # Crossing from an ordinary dark circle into its light background
            # is not a selected rim. Require a distinct highlight on three sides.
            bright=luma-bg_luma>=8 and luma-center_luma>=20
            chromatic=max(color)-min(color)>=60 and _rgb_distance(color,background)>=40 and _rgb_distance(color,center)>=30
            if bright or chromatic:supported.append(_rgb_distance(color,center))
        if len(supported)>=3:best=max(best,sum(supported)/len(supported))
    return best


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
    verified_indices: tuple[int, ...] = ()
    client_rect: tuple | None = None

    def as_dict(self):
        controls_verified=(bool(self.target_position) and float(self.confidence)>=.58 and
                           len(self.control_positions)==len(self.nominal_sizes) and len(self.nominal_sizes)>1)
        verified_indices=[i for i in self.verified_indices if 0 <= i < len(self.nominal_sizes)] if controls_verified else []
        verified_sizes=[int(self.nominal_sizes[i]) for i in verified_indices]
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
            'nominal_levels':levels,'verified_levels':[i+1 for i in verified_indices] if is_gartic else [],
            'verified_indices':verified_indices,
            'client_rect':list(self.client_rect) if self.client_rect is not None else None,
            'requested_level':requested_level,'effective_level':effective_level,
            'requested_physical_px':int(self.nominal_sizes[self.target_index]) if self.nominal_sizes else int(self.requested_px),
            'dynamic_guard':bool(verified_sizes),'target_index':int(self.target_index),
            'selected_index':self.selected_index,'confidence':float(self.confidence),
            'target_position':list(self.target_position) if self.target_position else None,
            'requested_px':int(self.requested_px),'effective_px':int(self.effective_px),
            'safe_guard_px':int(self.safe_guard_px),'method':self.method,
        }


def plan_browser_brush_size(profile_key, screenshot, client_rect, *, canvas_box=None, palette_box=None, requested_px=3):
    key=str(profile_key or '').lower()
    requested=max(1,int(round(bounded_number(requested_px, 'Brush size', minimum=1, maximum=10000))))
    if key not in SUPPORTED:
        return BrowserBrushPlan(key,(),(),0,None,0.0,None,requested,requested,max(requested,4),'unsupported profile')
    policy=POLICIES[key];sizes=tuple(policy['sizes'])
    client_rect=screen_rect(client_rect)
    if canvas_box is not None: canvas_box=contained_rect(canvas_box,client_rect)
    if palette_box is not None: palette_box=contained_rect(palette_box,client_rect,'palette rectangle')
    screenshot_matches(screenshot,client_rect)
    positions=tuple(_candidate_positions(key,client_rect,canvas_box,palette_box))
    target,requested=_requested_index(key,sizes,requested);safe_index=int(policy['safe_index'])
    if len(positions)!=len(sizes):
        safe=int(sizes[safe_index])
        return BrowserBrushPlan(key,positions,sizes,target,None,0.0,None,requested,safe,conservative_brush_guard(key,requested),'control geometry unavailable; current size unverified')
    # Only these complete 31x31 control patches are inspected. Converting the
    # entire window duplicated a large screenshot on every brush preflight.
    # Crop before mode conversion and retain each private patch until both
    # independent visual scores have been measured.
    patches = []
    try:
        for point in positions:
            patches.append(_patch(screenshot,client_rect,point))
        scores=[_control_score(p) for p in patches]
        select_scores=[_selection_score(p) for p in patches]
    finally:
        for patch in patches:
            if patch is not None:
                patch.close()
    good=sum(score>=12 for score in scores)
    confidence=max(0.0,min(1.0,(sum(min(60.0,s) for s in scores)/(max(1,len(scores))*60.0))*.70 + (good/len(scores))*.30))
    selected=None
    if select_scores:
        order=sorted(range(len(select_scores)),key=lambda i:select_scores[i],reverse=True)
        if select_scores[order[0]]>=12 and (len(order)==1 or select_scores[order[0]]-select_scores[order[1]]>=4):
            selected=order[0]
    verified_indices=tuple(i for i,score in enumerate(scores) if score>=12)
    if selected not in verified_indices: selected=None
    target_position=positions[target] if confidence>=.58 and target in verified_indices else None
    if target_position is not None and isinstance(canvas_box,(tuple,list)) and len(canvas_box)==4:
        cx0,cy0,cx1,cy1=map(int,canvas_box);tx,ty=target_position
        if cx0-4 <= tx <= cx1+4 and cy0-4 <= ty <= cy1+4:
            target_position=None;confidence=min(confidence,.40)
    effective=int(sizes[target]) if target_position is not None else int(sizes[safe_index])
    physical_requested=int(sizes[target])
    safe_guard=(
        _automatic_guard_px(sizes,physical_requested,effective)
        if target_position is not None
        else conservative_brush_guard(key,requested)
    )
    method=('verified Gartic brush level 1-5 with calibrated physical footprint'
            if target_position and key in GARTIC_PROFILES else
            'verified profile-relative brush controls' if target_position else
            'visual confidence low; safe fallback')
    return BrowserBrushPlan(key,positions,sizes,target,selected,confidence,target_position,requested,effective,safe_guard,method,verified_indices,client_rect)


def capture_control_patch(position, radius=18):
    from ScreenGuard import _grab_rgb
    x,y=map(int,position);r=max(8,min(40,int(radius)))
    return _grab_rgb((x-r,y-r,x+r+1,y+r+1))


def verify_brush_selection(plan_dict, target_index) -> bool:
    """Recheck the current, unique selection in one fresh read-only row capture.

    A click or a changed hover pixel is not a selected-state observation. This
    uses the same bounded visual evidence as planning, with all buffers owned
    by this call released before returning.
    """
    raw=rgb=None;patches=[]
    try:
        if not isinstance(plan_dict,dict) or bounded_number(plan_dict.get('confidence'),'Brush confidence')<.58:return False
        key=str(plan_dict.get('profile_key') or '').lower()
        if key not in POLICIES:return False
        positions=plan_dict.get('control_positions');sizes=plan_dict.get('nominal_sizes')
        if not isinstance(positions,(tuple,list)) or not isinstance(sizes,(tuple,list)) or len(positions)!=len(sizes) or len(sizes)!=len(POLICIES[key]['sizes']):return False
        if any(isinstance(size,bool) or not isinstance(size,int) for size in sizes) or tuple(sizes)!=tuple(POLICIES[key]['sizes']):return False
        positions=[screen_point(p,'brush control') for p in positions]
        if len(set(positions))!=len(positions):return False
        wanted=nonnegative_integer(target_index,'Brush index',maximum=len(positions)-1)
        verified=plan_dict.get('verified_indices')
        if verified is not None:
            if not isinstance(verified,(tuple,list)) or any(isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(positions) for i in verified) or len(set(verified))!=len(verified) or wanted not in verified:return False
        left=min(p[0] for p in positions)-15;top=min(p[1] for p in positions)-15
        right=max(p[0] for p in positions)+16;bottom=max(p[1] for p in positions)+16
        if (right-left)*(bottom-top)>1_000_000:return False
        box=screen_rect((left,top,right,bottom),'brush capture')
        if plan_dict.get('client_rect') is not None:contained_rect(box,plan_dict['client_rect'],'brush capture')
        from PIL import ImageGrab
        raw=ImageGrab.grab(bbox=box,all_screens=True)
        if raw.size!=(right-left,bottom-top):return False
        rgb=raw if raw.mode=='RGB' else raw.convert('RGB')
        patches=[_patch(rgb,box,p) for p in positions]
        if _control_score(patches[wanted])<12:return False
        scores=[_selection_score(patch) if _control_score(patch)>=12 else 0.0 for patch in patches]
        order=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)
        return bool(order[0]==wanted and scores[wanted]>=12 and scores[wanted]-scores[order[1]]>=4)
    except (OSError,ValueError,TypeError,ArithmeticError,IndexError,AttributeError):
        return False
    finally:
        for patch in patches:
            if patch is not None:patch.close()
        if rgb is not None and rgb is not raw:rgb.close()
        if raw is not None:raw.close()


def patch_change_score(before, after):
    if before is None or after is None or before.size!=after.size:return 0.0
    a=list(before.getdata());b=list(after.getdata())
    if not a:return 0.0
    changed=sum(1 for p,q in zip(a,b) if max(abs(int(p[i])-int(q[i])) for i in range(3))>=8)
    return 100.0*changed/len(a)
