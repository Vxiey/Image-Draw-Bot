"""Step 27.5 — unified one-click setup verification for Image Draw Bot.

The module is deliberately read-only.  It validates the selected target,
canvas, saved verified palette and tool state, then performs an independent
visual verification pass.  It never sends mouse or keyboard input.
"""
from __future__ import annotations
from CalibrationValidation import calibration_screenshot

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence
from CalibrationValidation import (screen_rect, screen_point, contained_rect, point_in_rect,
                                   finite_confidence, screenshot_matches)
from RuntimePaths import read_json

SETUP_SCHEMA = 1
MIN_CANVAS_SIDE = 40
PAINT_PROFILE = 'microsoft-paint'


@dataclass(frozen=True)
class SetupVerificationResult:
    passed: bool
    profile_key: str
    mode: str
    confidence: float
    canvas_ok: bool
    palette_ok: bool
    palette_verified: int
    palette_tested: int
    tool_ok: bool
    reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        return '; '.join(self.reasons) if self.reasons else 'setup verification passed'

    def as_dict(self) -> dict:
        return {
            'schema': SETUP_SCHEMA,
            'passed': self.passed,
            'profile_key': self.profile_key,
            'mode': self.mode,
            'confidence': self.confidence,
            'canvas_ok': self.canvas_ok,
            'palette_ok': self.palette_ok,
            'palette_verified': self.palette_verified,
            'palette_tested': self.palette_tested,
            'tool_ok': self.tool_ok,
            'reasons': list(self.reasons),
        }


def setup_mode(profile_key: str) -> str:
    from TargetCapabilities import capability_for_key
    mode=capability_for_key(profile_key).setup_mode
    if mode=='paint-auto':return 'paint'
    if mode=='browser-auto':return 'browser'
    return 'manual'


def _box(value: Sequence[int], label: str) -> tuple[int,int,int,int]:
    return screen_rect(value,label)


def validate_canvas(client_rect, canvas_box, *, min_side: int = MIN_CANVAS_SIDE) -> tuple[int,int,int,int]:
    return contained_rect(canvas_box,client_rect,'Detected canvas',min_side=min_side)


def canvas_shift(expected, detected) -> int:
    a=_box(expected,'Expected canvas');b=_box(detected,'Detected canvas')
    return max(abs(x-y) for x,y in zip(a,b))


def load_verified_palette(path, profile_key: str):
    from Colors import validate_calibration
    path=Path(path)
    data=read_json(path,max_bytes=256*1024,max_items=10000)
    if not isinstance(data,dict) or data.get('profile')!=profile_key:
        raise ValueError('Verified palette belongs to another profile or has no profile owner.')
    rows=validate_calibration(data,profile_key=profile_key)
    state=str(data.get('state') or 'calibrated').strip().lower()
    if state!='verified':
        raise ValueError(f'Palette is not screen-verified (state={state}).')
    verification=data.get('verification') if isinstance(data.get('verification'),dict) else {}
    confidence=finite_confidence(verification.get('confidence'))
    return data,rows,confidence


def _live_palette_rows(data,rows,client,*,require_anchor=False):
    from CalibrationAnchors import resolve_point,validate_anchor
    anchor=data.get('anchor')
    if anchor is not None:anchor=validate_anchor(anchor)
    elif require_anchor:raise ValueError('Paint palette must be anchored to the target window.')
    result=[]
    for row in rows:
        point=screen_point(row['position'],'palette position')
        if anchor is not None:point=resolve_point(point,anchor,client)
        if not point_in_rect(point,client):raise ValueError('Palette position is outside the current target client.')
        result.append((point,tuple(row['rgb'])))
    return result


def verify_browser_live(profile_key: str, target_meta: dict, canvas_box, palette_path, *, screenshot=None, drawing_region=None) -> SetupVerificationResult:
    profile_key=str(profile_key or '').lower()
    if setup_mode(profile_key)!='browser':
        raise ValueError('Browser one-click verification is unavailable for this profile.')
    client=_box((target_meta or {}).get('client_rect'),'Browser client')
    canvas=validate_canvas(client,canvas_box)
    data,rows,saved_confidence=load_verified_palette(palette_path,profile_key)
    entries=_live_palette_rows(data,rows,client)
    from BrowserVisualPreflight import verify_browser_visual_preflight
    visual=verify_browser_visual_preflight(profile_key,target_meta,canvas,entries,screenshot=screenshot,require_palette=True)
    reasons=[]
    if not visual.canvas_ok:reasons.append('canvas visual verification failed')
    if visual.palette_tested<3:reasons.append('too few palette swatches could be verified')
    if visual.palette_verified < (visual.palette_tested if visual.palette_tested<=4 else max(3,(visual.palette_tested*4+4)//5)):
        reasons.append(f'palette verification matched only {visual.palette_verified}/{visual.palette_tested}')
    reasons.extend(str(x) for x in visual.reasons if str(x) not in reasons)
    palette_ok=visual.palette_tested>=3 and visual.palette_verified >= (visual.palette_tested if visual.palette_tested<=4 else max(3,(visual.palette_tested*4+4)//5))
    confidence=min(finite_confidence(visual.confidence),saved_confidence)
    if confidence<.68:reasons.append('saved or live calibration confidence is too low')
    region_ok=True
    if drawing_region is not None:
        try:drawing_region.with_canvas(profile_key,target_meta,visual.detected_canvas)
        except ValueError as error:
            region_ok=False;reasons.append(str(error))
    canvas_ok=bool(visual.canvas_ok and region_ok)
    passed=bool(visual.passed and canvas_ok and palette_ok and confidence>=.68)
    return SetupVerificationResult(passed,profile_key,'browser',confidence,canvas_ok,bool(palette_ok),int(visual.palette_verified),int(visual.palette_tested),True,tuple(reasons))


def verify_paint_live(target_meta: dict, canvas_box, palette_path, *, tool_path=None, screenshot=None) -> SetupVerificationResult:
    profile_key=PAINT_PROFILE
    client=_box((target_meta or {}).get('client_rect'),'Paint client')
    canvas=validate_canvas(client,canvas_box)
    data,rows,saved_confidence=load_verified_palette(palette_path,profile_key)
    entries=_live_palette_rows(data,rows,client,require_anchor=True)
    reasons=[]
    palette_ok=len(rows)==20
    if not palette_ok:reasons.append(f'Paint palette contains {len(rows)} colors instead of 20')
    from PaintTools import load_tool_calibration, TOOL_FILE
    tools=load_tool_calibration(tool_path or TOOL_FILE)
    from CalibrationAnchors import resolve_point,validate_anchor
    direct=tools.get('tools') if isinstance(tools,dict) else {}
    tool_ok=bool(isinstance(direct,dict) and tools.get('version') in (2,3) and direct.get('Pencil') is not None and direct.get('Fill') is not None)
    resolved_tools={}
    if tool_ok:
        try:
            anchor=validate_anchor(tools.get('anchor'))
            resolved_tools={name:resolve_point(direct[name],anchor,client) for name in ('Pencil','Fill')}
            tool_ok=all(point_in_rect(point,client) for point in resolved_tools.values())
        except ValueError:tool_ok=False
    if not tool_ok:reasons.append('Paint Pencil and Fill are not both verified')
    with calibration_screenshot(screenshot,client) as screenshot:
        from PaintFullCalibration import detect_setup
        detected=detect_setup(screenshot,screen_origin=client[:2])
        detected_canvas=validate_canvas(client,detected.get('canvas_box'))
        shift=canvas_shift(canvas,detected_canvas)
        canvas_ok=shift<=6 and float(detected.get('confidence',0) or 0)>=.85
        if not canvas_ok:reasons.append(f'Paint canvas changed by {shift}px or confidence is too low')
        live_palette=int(detected.get('palette_count',0) or 0)
        live_entries=list(zip(detected.get('positions') or (),detected.get('rgbs') or ()))
        matched=set()
        for point,rgb in entries:
            for index,(live_point,live_rgb) in enumerate(live_entries):
                if index not in matched and max(abs(a-b) for a,b in zip(point,live_point))<=6 and max(abs(a-b) for a,b in zip(rgb,live_rgb))<=18:
                    matched.add(index);break
        palette_ok=bool(palette_ok and live_palette==20 and len(live_entries)==20 and len(matched)==20)
        if len(matched)!=20:reasons.append(f'saved Paint positions/RGB matched only {len(matched)}/20 live colors')
        if live_palette!=20:reasons.append(f'live Paint palette verification found {live_palette}/20 colors')
        live_tools=detected.get('tools') or {}
        tool_ok=bool(tool_ok and all(name in live_tools and max(abs(a-b) for a,b in zip(point,live_tools[name]))<=6 for name,point in resolved_tools.items()))
        if not tool_ok and 'Paint Pencil and Fill are not both verified' not in reasons:reasons.append('saved Paint tools do not match the current verified ribbon')
        live_conf=finite_confidence(detected.get('confidence'))
        confidence=min(live_conf,saved_confidence)
        if confidence<.85:reasons.append('saved or live calibration confidence is too low')
        passed=bool(canvas_ok and palette_ok and tool_ok and confidence>=.85)
        return SetupVerificationResult(passed,profile_key,'paint',confidence,canvas_ok,palette_ok,len(matched),20,tool_ok,tuple(reasons))


def format_verification(result: SetupVerificationResult | dict) -> str:
    data=result.as_dict() if isinstance(result,SetupVerificationResult) else dict(result or {})
    passed=bool(data.get('passed'))
    canvas='OK' if data.get('canvas_ok') else 'FAIL'
    palette=f"{int(data.get('palette_verified',0) or 0)}/{int(data.get('palette_tested',0) or 0)}"
    tools='OK' if data.get('tool_ok') else 'FAIL'
    confidence=float(data.get('confidence',0) or 0)
    prefix='✓ One-click Setup verified' if passed else 'One-click Setup blocked'
    return f'{prefix} · canvas {canvas} · palette {palette} · tools {tools} · confidence {confidence*100:.0f}%'
