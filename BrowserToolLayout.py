"""Automatic browser drawing-tool layout inference for supported web profiles.

Control points are derived only from an already verified browser client/canvas
layout and visually scored before any click is allowed. Low confidence returns
no actions, preserving Image Draw Bot's no-guessed-click safety rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from CalibrationValidation import (screen_rect, screen_point, contained_rect,
                                   point_in_rect, screenshot_matches, finite_confidence)

SUPPORTED = frozenset({'gartic-phone', 'gartic-io'})


def _rgb_distance(a, b):
    return sqrt(sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)))


def _clamp_point(point, rect):
    x, y = map(int, point); l, t, r, b = map(int, rect)
    return max(l, min(r - 1, x)), max(t, min(b - 1, y))


def _inside(point, box, margin=0):
    x, y = map(int, point); l, t, r, b = map(int, box)
    return l - margin <= x <= r + margin and t - margin <= y <= b + margin


def _patch(image, client_rect, point, radius=16):
    if image is None:
        return None
    l, t, _, _ = map(int, client_rect); x, y = map(int, point)
    x -= l; y -= t
    left=x-radius; top=y-radius
    right=x+radius+1; bottom=y+radius+1
    if not (0<=left<right<=image.width and 0<=top<bottom<=image.height):
        return None
    return image.crop((left,top,right,bottom)).convert('RGB')


def _control_score(patch):
    if patch is None:
        return 0.0
    w,h=patch.size; cx=w//2; cy=h//2
    center=patch.getpixel((cx,cy))
    corners=[patch.getpixel((1,1)),patch.getpixel((w-2,1)),patch.getpixel((1,h-2)),patch.getpixel((w-2,h-2))]
    ring=[]; radius=max(3,min(w,h)//3)
    for dx,dy in ((radius,0),(-radius,0),(0,radius),(0,-radius),(radius//2,radius//2),(-radius//2,radius//2)):
        ring.append(patch.getpixel((max(0,min(w-1,cx+dx)),max(0,min(h-1,cy+dy)))))
    background=tuple(sum(p[i] for p in corners)//len(corners) for i in range(3))
    contrast=max([_rgb_distance(center,background)]+[_rgb_distance(p,background) for p in ring])
    diversity=max((_rgb_distance(a,b) for a in ring for b in ring),default=0.0)
    if contrast < 8 and diversity < 8:
        return 0.0  # A uniform dark toolbar is not evidence of a button.
    darkness=max(0.0,255.0-sum(center)/3.0)
    return min(100.0,contrast*.55+diversity*.20+darkness*.25)


def _gartic_candidates(client_rect, canvas_box):
    l,t,r,b=map(int,client_rect); x0,y0,x1,y1=map(int,canvas_box)
    w,h=max(1,x1-x0),max(1,y1-y0); cw,ch=max(1,r-l),max(1,b-t)
    top_gap=max(22,min(int(ch*.055),int(h*.14)))
    right_gap=max(26,min(int(cw*.055),int(w*.18)))
    row=max(26,min(int(h*.115),int(ch*.090)))
    positions={
        'Brush':(x0+int(w*.060),y0-top_gap),
        'Eraser':(x1-int(w*.060),y0-top_gap),
        'Fill':(x1+right_gap,y0+int(row*1.15)),
        'Clear':(x1+right_gap,y0+int(row*2.20)),
    }
    return {name:point for name,point in positions.items() if point_in_rect(point,client_rect)}


def _candidates(profile_key, client_rect, canvas_box=None, palette_box=None):
    if not (isinstance(canvas_box,(tuple,list)) and len(canvas_box)==4):
        return {}
    if str(profile_key or '').lower() in SUPPORTED:
        return _gartic_candidates(client_rect,canvas_box)
    return {}


@dataclass(frozen=True)
class BrowserToolPlan:
    profile_key: str
    tools: dict
    confidence: float
    tool_scores: dict
    method: str
    client_rect: tuple | None = None

    def as_dict(self):
        return {
            'profile_key':self.profile_key,
            'tools':{str(name):[int(pos[0]),int(pos[1])] for name,pos in (self.tools or {}).items()},
            'confidence':float(self.confidence),
            'tool_scores':{str(name):float(score) for name,score in (self.tool_scores or {}).items()},
            'method':str(self.method),
            'client_rect':list(self.client_rect) if self.client_rect is not None else None,
        }


def plan_browser_tools(profile_key, screenshot, client_rect, *, canvas_box=None, palette_box=None):
    key=str(profile_key or '').lower()
    if key not in SUPPORTED:
        return BrowserToolPlan(key,{},0.0,{},'unsupported profile')
    client_rect=screen_rect(client_rect)
    if canvas_box is not None: canvas_box=contained_rect(canvas_box,client_rect)
    if palette_box is not None: palette_box=contained_rect(palette_box,client_rect,'palette rectangle')
    if screenshot is None:
        return BrowserToolPlan(key,{},0.0,{},'tool screenshot unavailable',client_rect)
    screenshot_matches(screenshot,client_rect)
    positions=_candidates(key,client_rect,canvas_box=canvas_box,palette_box=palette_box)
    if not positions:
        return BrowserToolPlan(key,{},0.0,{},'tool geometry unavailable')
    scores={}; valid={}
    for tool,point in positions.items():
        if isinstance(canvas_box,(tuple,list)) and len(canvas_box)==4 and _inside(point,canvas_box,margin=4):
            continue
        score=_control_score(_patch(screenshot,client_rect,point)); scores[tool]=score
        if score>=8.0:
            valid[tool]=tuple(map(int,point))
    if not scores:
        return BrowserToolPlan(key,{},0.0,{},'candidate tools overlapped the canvas')
    avg=sum(min(40.0,float(v)) for v in scores.values())/(max(1,len(scores))*40.0)
    coverage=len(valid)/4
    confidence=max(0.0,min(1.0,avg*.70+coverage*.30))
    if 'Brush' not in valid:
        confidence=min(confidence,.35)
    method='verified canvas-relative browser tool layout' if confidence>=.58 and valid else 'browser tool layout confidence low'
    if confidence<.58:
        valid={}
    return BrowserToolPlan(key,valid,confidence,scores,method,client_rect)


def build_browser_tool_action(plan, tool: str):
    if not isinstance(plan,dict):
        raise ValueError('Automatic browser tool layout is unavailable.')
    if tool not in ('Brush','Eraser','Fill','Clear'):
        raise ValueError('Unknown automatic browser drawing tool.')
    tools=plan.get('tools') or {}
    if not isinstance(tools,dict):raise ValueError('Automatic browser tool positions are invalid.')
    position=tools.get(tool)
    confidence=finite_confidence(plan.get('confidence'))
    if not position or confidence<.58:
        raise ValueError(f'Automatic browser {tool} tool detection is not confident enough yet.')
    x,y=screen_point(position,'browser tool')
    if plan.get('client_rect') is not None and not point_in_rect((x,y),plan['client_rect']):
        raise ValueError('Automatic browser tool position is outside its verified client.')
    return tool.lower(),(x,y)
