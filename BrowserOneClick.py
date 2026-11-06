"""Browser One-Click orchestration for Image Draw Bot v1.0.80.

Normal browser flow: choose a supported game, import/drop an image, then Draw
Studio discovers or reuses the matching browser window, auto-calibrates canvas
and palette read-only, and hands control back to DrawBot for visual preflight,
automatic brush-size selection and explicit one-click drawing authorization.

This module never sends mouse or keyboard input.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Iterable

from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES, detect_browser_setup, auto_calibrate_browser
from DpiSupport import get_window_dpi_info
from CalibrationValidation import (screen_rect, contained_rect, finite_confidence,
                                   bounded_number, nonnegative_integer, screenshot_matches)
from WindowsSystem import load_system_library

MIN_WINDOW_W = 620
MIN_WINDOW_H = 420
MIN_CONFIDENCE = .70
UNIQUE_MARGIN = .045


@dataclass(frozen=True)
class Candidate:
    handle: int
    rect: tuple[int, int, int, int]
    client_rect: tuple[int, int, int, int]
    dpi: int
    pid: int
    title: str
    confidence: float
    palette_count: int
    canvas_box: tuple[int, int, int, int] | None
    screenshot: object | None = None

    @property
    def area(self):
        l,t,r,b=self.client_rect
        return max(0,r-l)*max(0,b-t)


def _value(item, name, default=None):
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _rect_overlap_ratio(a, b) -> float:
    try:
        al,at,ar,ab=map(float,a); bl,bt,br,bb=map(float,b)
    except Exception:
        return 0.0
    iw=max(0.0,min(ar,br)-max(al,bl)); ih=max(0.0,min(ab,bb)-max(at,bt))
    inter=iw*ih
    aa=max(1.0,(ar-al)*(ab-at)); ba=max(1.0,(br-bl)*(bb-bt))
    return max(0.0,min(1.0,inter/max(aa,ba)))


def candidate_score(item, *, preferred_handle=None, foreground_handle=None,
                    preferred_monitor_rect=None, previous_canvas_box=None) -> float:
    """Score a browser candidate using visual evidence plus safe local context.

    Context never overrides a low-confidence visual match. It only breaks ties
    between two already plausible game windows, which avoids forcing the user to
    close unrelated browser windows during Auto Setup.
    """
    confidence=finite_confidence(_value(item,'confidence',0.0))
    count=nonnegative_integer(_value(item,'palette_count',0), 'Palette count', maximum=96)
    canvas=_value(item,'canvas_box',None)
    handle=int(_value(item,'handle',0) or 0)
    rect=_value(item,'client_rect',None) or _value(item,'rect',None)
    palette_bonus=min(.10,count/720.0)
    canvas_bonus=.05 if canvas else 0.0
    context_bonus=0.0
    if preferred_handle and handle==int(preferred_handle):
        context_bonus += .18
    if foreground_handle and handle==int(foreground_handle):
        context_bonus += .12
    if preferred_monitor_rect and rect:
        context_bonus += .035*_rect_overlap_ratio(rect,preferred_monitor_rect)
    if previous_canvas_box and canvas:
        # Browser detector canvas boxes are client/screen rectangles depending on
        # caller. Ratio only contributes a small tie-break bonus.
        context_bonus += .045*_rect_overlap_ratio(canvas,previous_canvas_box)
    return confidence+palette_bonus+canvas_bonus+context_bonus


def choose_unique_candidate(candidates: Iterable, *, min_confidence: float=MIN_CONFIDENCE,
                            margin: float=UNIQUE_MARGIN, preferred_handle=None,
                            foreground_handle=None, preferred_monitor_rect=None,
                            previous_canvas_box=None):
    threshold=bounded_number(min_confidence,'Browser match threshold')
    margin=bounded_number(margin,'Browser ambiguity margin')
    values=[]
    for candidate in candidates:
        # Context is a tie-breaker among visually plausible candidates. An
        # unrelated preferred window must not hide a different valid match.
        try:
            if bounded_number(_value(candidate,'confidence',0.0),'Browser match confidence')<threshold:continue
            nonnegative_integer(_value(candidate,'palette_count',0), 'Palette count', maximum=96)
            raw_handle=_value(candidate,'handle',None)
            if raw_handle is not None:
                handle=nonnegative_integer(raw_handle, 'Window handle', maximum=(1<<64)-1)
                if not handle:continue
        except ValueError:
            continue
        values.append(candidate)
    if not values:
        raise ValueError('No visible browser window matched the selected drawing game with sufficient confidence.')
    score=lambda c:candidate_score(c,preferred_handle=preferred_handle,foreground_handle=foreground_handle,
                                   preferred_monitor_rect=preferred_monitor_rect,previous_canvas_box=previous_canvas_box)
    values.sort(key=lambda c:(score(c), _value(c,'area',0)), reverse=True)
    best=values[0]
    if len(values)>1 and score(best)-score(values[1]) < float(margin):
        raise ValueError('More than one browser window still matches the selected game almost equally. Focus the intended game window or select its canvas once.')
    return best


def _foreground_window_handle():
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32=load_system_library('user32.dll')
        user32.GetForegroundWindow.argtypes=[]
        user32.GetForegroundWindow.restype=wintypes.HWND
        value=user32.GetForegroundWindow()
        return int(value) if value else None
    except Exception:
        return None

def _enumerate_windows(exclude_pid=None):
    """Yield visible top-level Windows candidates. Imported lazily for portability."""
    import ctypes
    from ctypes import wintypes
    user32=load_system_library('user32.dll',use_last_error=True)
    EnumWindowsProc=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.EnumWindows.argtypes=[EnumWindowsProc,wintypes.LPARAM];user32.EnumWindows.restype=wintypes.BOOL
    user32.IsWindowVisible.argtypes=[wintypes.HWND];user32.IsWindowVisible.restype=wintypes.BOOL
    user32.IsIconic.argtypes=[wintypes.HWND];user32.IsIconic.restype=wintypes.BOOL
    user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)];user32.GetWindowRect.restype=wintypes.BOOL
    user32.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)];user32.GetClientRect.restype=wintypes.BOOL
    user32.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)];user32.ClientToScreen.restype=wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)];user32.GetWindowThreadProcessId.restype=wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes=[wintypes.HWND];user32.GetWindowTextLengthW.restype=ctypes.c_int
    user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int];user32.GetWindowTextW.restype=ctypes.c_int
    try:
        user32.GetDpiForWindow.argtypes=[wintypes.HWND];user32.GetDpiForWindow.restype=wintypes.UINT
    except AttributeError:pass
    excluded={int(exclude_pid or os.getpid())}
    out=[]
    @EnumWindowsProc
    def callback(hwnd,_):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):return True
            pid=wintypes.DWORD()
            if not user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid)) or not pid.value:return True
            if int(pid.value) in excluded:return True
            cr=wintypes.RECT();origin=wintypes.POINT(0,0);wr=wintypes.RECT()
            if not user32.GetClientRect(hwnd,ctypes.byref(cr)) or not user32.ClientToScreen(hwnd,ctypes.byref(origin)) or not user32.GetWindowRect(hwnd,ctypes.byref(wr)):return True
            client=(origin.x,origin.y,origin.x+(cr.right-cr.left),origin.y+(cr.bottom-cr.top))
            if client[2]-client[0] < MIN_WINDOW_W or client[3]-client[1] < MIN_WINDOW_H:return True
            n=max(0,min(32767,int(user32.GetWindowTextLengthW(hwnd))));buf=ctypes.create_unicode_buffer(n+1);user32.GetWindowTextW(hwnd,buf,n+1)
            dpi_info=get_window_dpi_info(hwnd,user32=user32)
            out.append({'handle':int(hwnd),'rect':(wr.left,wr.top,wr.right,wr.bottom),'client_rect':client,
                        'dpi':int(dpi_info.dpi),'dpi_source':dpi_info.source,'dpi_scale':dpi_info.scale,
                        'monitor_rect':dpi_info.monitor_rect,'pid':int(pid.value),'title':buf.value})
        except Exception:pass
        return True
    if not user32.EnumWindows(callback,0):
        raise OSError('Windows could not enumerate visible application windows.')
    out.sort(key=lambda m:(m['client_rect'][2]-m['client_rect'][0])*(m['client_rect'][3]-m['client_rect'][1]),reverse=True)
    return out[:18]


def discover_browser_target(profile_key: str, *, exclude_pid=None, preferred_handle=None, preferred_monitor_rect=None, previous_canvas_box=None, cancelled=lambda:False):
    key=str(profile_key or '').lower()
    if key not in SUPPORTED_BROWSER_PROFILES:
        raise ValueError('Browser One-Click is not available for this profile.')
    from PIL import ImageGrab
    if cancelled():raise InterruptedError('Browser discovery cancelled.')
    context=dict(preferred_handle=preferred_handle,foreground_handle=_foreground_window_handle(),
                 preferred_monitor_rect=preferred_monitor_rect,previous_canvas_box=previous_canvas_box)
    detected=[];best_shot=None;best_rank=None
    try:
        for meta in _enumerate_windows(exclude_pid=exclude_pid):
            if cancelled():raise InterruptedError('Browser discovery cancelled.')
            shot=None
            try:
                client=screen_rect(meta['client_rect'])
                raw=ImageGrab.grab(bbox=client,all_screens=True)
                try:shot=raw.convert('RGB')
                finally:raw.close()
                screenshot_matches(shot,client)
                result=detect_browser_setup(key,shot,screen_origin=client[:2],cancelled=cancelled)
                canvas=contained_rect(result.get('canvas_box'),client)
                palette_conf=finite_confidence(result.get('palette_confidence'))
                canvas_conf=finite_confidence(result.get('canvas_confidence'))
                confidence=.64*palette_conf+.36*canvas_conf
                if min(palette_conf,canvas_conf)<.68 or confidence<MIN_CONFIDENCE:continue
                candidate=Candidate(meta['handle'],meta['rect'],client,meta['dpi'],meta['pid'],meta['title'],confidence,len(result.get('positions') or ()),canvas)
                detected.append(candidate)
                rank=(candidate_score(candidate,**context),candidate.area)
                if best_rank is None or rank>best_rank:
                    if best_shot is not None:best_shot.close()
                    best_shot,shot=shot,None
                    best_rank=rank
            except InterruptedError:
                raise
            except Exception:
                continue
            finally:
                if shot is not None:shot.close()
        if cancelled():raise InterruptedError('Browser discovery cancelled.')
        chosen=choose_unique_candidate(detected,**context)
        result=replace(chosen,screenshot=best_shot)
        best_shot=None
        return result
    finally:
        if best_shot is not None:best_shot.close()


def one_click_setup(profile_name: str, profile_key: str, palette_path: Path, *, current_handle=None, exclude_pid=None, cancelled=lambda:False):
    """Return a BrowserAutoCalibration-compatible payload for one-click setup."""
    from PIL import ImageGrab
    from TargetCapture import probe_handle_isolated
    from LayoutFingerprintV2 import try_restore, record_from_calibration_file
    key=str(profile_key or '').lower()
    if key not in SUPPORTED_BROWSER_PROFILES:raise ValueError('Browser One-Click is not available for this profile.')
    if cancelled():raise InterruptedError('Browser setup cancelled.')
    if current_handle:
        handle=nonnegative_integer(current_handle,'Window handle',maximum=(1<<64)-1)
        meta=probe_handle_isolated(handle,cancelled=cancelled)
        client=screen_rect(meta['client_rect'])
        screenshot=ImageGrab.grab(bbox=client,all_screens=True)
    else:
        candidate=discover_browser_target(key,exclude_pid=exclude_pid,cancelled=cancelled)
        meta={'handle':candidate.handle,'rect':candidate.rect,'client_rect':candidate.client_rect,'target_pid':candidate.pid,'dpi':candidate.dpi}
        screenshot=candidate.screenshot
    try:
        cached=try_restore(key,meta,Path(palette_path),screenshot=screenshot,cancelled=cancelled)
        if cancelled():raise InterruptedError('Browser setup cancelled.')
        if cached.hit:
            payload=cached.as_dict();payload.update({'palette_confidence':cached.confidence,'canvas_confidence':cached.confidence,'method':'Layout Fingerprint v2 cache','note':'One-Click restored sampled palette points; canvas still requires live preflight.','target_meta':meta,'profile_name':profile_name,'layout_fingerprint_meta':cached.as_dict(),'one_click':True})
            return payload
        from BrowserAutoRecalibration import calibrate_browser_with_retry
        result,retry_meta=calibrate_browser_with_retry(
            key,meta,Path(palette_path),screenshot=screenshot,cancelled=cancelled,
            recapture=lambda:ImageGrab.grab(bbox=tuple(meta['client_rect']),all_screens=True))
        if cancelled():raise InterruptedError('Browser setup cancelled.')
        try:fingerprint=record_from_calibration_file(key,meta,result.canvas_box,Path(palette_path),method='Browser One-Click / '+result.method) if result.canvas_box else None
        except Exception as error:fingerprint={'saved':False,'reason':str(error)}
        if cancelled():raise InterruptedError('Browser setup cancelled.')
        payload=result.as_dict();payload.update({'target_meta':meta,'profile_name':profile_name,'layout_fingerprint_meta':fingerprint,'one_click':True,'recalibration_retry_meta':retry_meta})
        return payload
    finally:
        if screenshot is not None:screenshot.close()
