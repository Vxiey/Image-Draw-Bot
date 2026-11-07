"""Experimental smart canvas Drop-In support for browser drawing profiles.

This module intentionally keeps detection/validation separate from Tk UI code.
The feature is early-stage: it uses read-only screenshots to locate a likely
canvas, then DrawBot creates a temporary drag/drop overlay over the target
browser client area. Native drawing input remains guarded by the normal
CanvasGuard / Browser One-Click preflight chain.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

EXPERIMENTAL_WARNING = (
    'Experimental: Smart Canvas Drop is very early stage and may not work as '
    'planned on every Gartic/browser layout yet.'
)
MIN_CANVAS_CONFIDENCE = 0.68
DROP_EDGE_MARGIN_PX = 4

_PROFILE_TITLE_HINTS = {
    'gartic-phone': ('gartic',),
    'skribbl': ('skribbl',),
    'skribbl-fast': ('skribbl',),
    'sketchheads': ('sketchheads', 'sketch heads'),
    'sketchful': ('sketchful',),
}


@dataclass(frozen=True)
class SmartCanvasCandidate:
    handle: int
    rect: tuple[int, int, int, int]
    client_rect: tuple[int, int, int, int]
    dpi: int | None
    pid: int | None
    title: str
    canvas_box: tuple[int, int, int, int]
    canvas_confidence: float
    score: float

    def as_payload(self) -> dict:
        return {
            'target_meta': {
                'handle': int(self.handle),
                'rect': tuple(map(int, self.rect)),
                'client_rect': tuple(map(int, self.client_rect)),
                'dpi': self.dpi,
                'target_pid': self.pid,
                'title': self.title,
            },
            'canvas_box': tuple(map(int, self.canvas_box)),
            'canvas_confidence': float(self.canvas_confidence),
            'score': float(self.score),
            'experimental': True,
            'warning': EXPERIMENTAL_WARNING,
        }


def normalize_box(box: Sequence[int], *, name: str = 'box') -> tuple[int, int, int, int]:
    if not isinstance(box, (tuple, list)) or len(box) != 4:
        raise ValueError(f'{name} is unavailable.')
    try:l, t, r, b = map(int, box)
    except (ValueError,TypeError,OverflowError) as error:raise ValueError(f'{name} has invalid coordinates.') from error
    if not all(-(2**31)<=value<2**31 for value in (l,t,r,b)):
        raise ValueError(f'{name} is outside the screen coordinate range.')
    if r <= l or b <= t:
        raise ValueError(f'{name} has invalid geometry.')
    return l, t, r, b


def canvas_inside_client(canvas_box: Sequence[int], client_rect: Sequence[int]) -> bool:
    l, t, r, b = normalize_box(canvas_box, name='Canvas')
    cl, ct, cr, cb = normalize_box(client_rect, name='Target client')
    return cl <= l < r <= cr and ct <= t < b <= cb


def point_in_canvas(point: Sequence[int], canvas_box: Sequence[int], *, margin: int = DROP_EDGE_MARGIN_PX) -> bool:
    if not isinstance(point, (tuple, list)) or len(point) != 2:
        return False
    try:x, y = map(int, point)
    except (ValueError,TypeError,OverflowError):return False
    l, t, r, b = normalize_box(canvas_box, name='Canvas')
    safe = max(0, int(margin))
    # Avoid treating an uncertain anti-aliased edge as a valid drop location.
    if r - l <= safe * 2 or b - t <= safe * 2:
        return False
    return l + safe <= x < r - safe and t + safe <= y < b - safe


def overlay_geometry(client_rect: Sequence[int]) -> str:
    l, t, r, b = normalize_box(client_rect, name='Target client')
    return f'{r-l}x{b-t}{l:+d}{t:+d}'


def canvas_overlay_geometry(canvas_box: Sequence[int]) -> str:
    """Geometry for the canvas-only OS drop target overlay.

    Keeping the overlay constrained to the detected drawable canvas means a
    browser image is only accepted when it is actually released on the game
    canvas, while the rest of the browser remains untouched.
    """
    l, t, r, b = normalize_box(canvas_box, name='Canvas')
    return f'{r-l}x{b-t}{l:+d}{t:+d}'


def place_canvas_overlay(window, canvas_box: Sequence[int]) -> tuple[int, int, int, int]:
    """Show a verified overlay at absolute physical Windows coordinates.

    Negative Tk geometry offsets measure from the right/bottom screen edge.
    SetWindowPos instead accepts the detector's signed desktop coordinates.
    Keep the window visually hidden during realization and mapping because Tk
    may apply a pending geometry request when it first becomes visible.
    """
    import ctypes
    from ctypes import wintypes
    from CalibrationValidation import screen_rect
    from WindowsSystem import load_system_library

    rect = screen_rect(canvas_box, 'Canvas')
    left, top, right, bottom = rect
    width, height = right-left, bottom-top
    if max(width, height) >= 2**31:
        raise ValueError('The canvas overlay exceeds the native window size range.')
    window.withdraw()
    alpha = window.attributes('-alpha')
    window.attributes('-alpha', 0.0)
    try:
        window.geometry(f'{width}x{height}+0+0')
        window.update_idletasks()
        api = load_system_library('user32.dll', use_last_error=True)
        api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        api.GetAncestor.restype = wintypes.HWND
        api.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        api.SetWindowPos.restype = wintypes.BOOL
        api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        api.GetWindowRect.restype = wintypes.BOOL
        handle = api.GetAncestor(window.winfo_id(), 2)  # GA_ROOT
        if not handle:
            raise OSError('Could not read the canvas drop overlay window handle.')

        def position_and_verify():
            # SWP_NOZORDER | SWP_NOACTIVATE; the caller owns topmost/focus policy.
            if not api.SetWindowPos(handle, None, left, top, width, height, 0x0014):
                raise OSError('Could not position the canvas drop overlay.')
            actual = wintypes.RECT()
            if not api.GetWindowRect(handle, ctypes.byref(actual)):
                raise OSError('Could not verify the canvas drop overlay position.')
            if (actual.left, actual.top, actual.right, actual.bottom) != rect:
                raise OSError('The canvas drop overlay did not match the detected canvas.')

        position_and_verify()
        window.deiconify()
        window.update_idletasks()
        position_and_verify()
        window.attributes('-alpha', alpha)
        return rect
    except BaseException:
        # A failed/partially mapped overlay must never remain a visible drop
        # target. The caller can now destroy it and report the original error.
        try:
            window.withdraw()
        except Exception:
            pass
        raise


def canvas_relative_box(canvas_box: Sequence[int], client_rect: Sequence[int]) -> tuple[int, int, int, int]:
    if not canvas_inside_client(canvas_box, client_rect):
        raise ValueError('Detected canvas is outside the target browser client area.')
    l, t, r, b = normalize_box(canvas_box, name='Canvas')
    cl, ct, _, _ = normalize_box(client_rect, name='Target client')
    return l - cl, t - ct, r - cl, b - ct


def _title_bonus(profile_key: str, title: str) -> float:
    lowered = str(title or '').lower()
    hints = _PROFILE_TITLE_HINTS.get(str(profile_key or '').lower(), ())
    return 0.12 if any(hint in lowered for hint in hints) else 0.0


def score_candidate(profile_key: str, *, confidence: float, canvas_box: Sequence[int], client_rect: Sequence[int], title: str = '') -> float:
    confidence=float(confidence)
    if not math.isfinite(confidence) or not 0.0<=confidence<=1.0:return -1.0
    canvas = normalize_box(canvas_box, name='Canvas')
    client = normalize_box(client_rect, name='Target client')
    if not canvas_inside_client(canvas, client):
        return -1.0
    cw, ch = canvas[2] - canvas[0], canvas[3] - canvas[1]
    ww, wh = client[2] - client[0], client[3] - client[1]
    area_ratio = (cw * ch) / max(1.0, float(ww * wh))
    # Confidence dominates. Area is only a gentle tie-breaker so a huge panel
    # cannot beat a visually stronger canvas detector result.
    return float(confidence) + min(0.08, max(0.0, area_ratio) * 0.08) + _title_bonus(profile_key, title)


def choose_candidate(candidates: Iterable[SmartCanvasCandidate], *, ambiguity_gap: float = 0.035) -> SmartCanvasCandidate:
    gap=float(ambiguity_gap)
    if not math.isfinite(gap) or gap<0:raise ValueError('The canvas ambiguity margin must be finite and nonnegative.')
    valid=[]
    for candidate in candidates:
        try:
            confidence=float(candidate.canvas_confidence);score=float(candidate.score)
            if (not math.isfinite(confidence) or not math.isfinite(score) or
                    not MIN_CANVAS_CONFIDENCE<=confidence<=1 or score<0 or
                    type(candidate.handle) is not int or candidate.handle<=0 or
                    not canvas_inside_client(candidate.canvas_box,candidate.client_rect)):
                continue
        except (TypeError,ValueError,OverflowError):continue
        valid.append(candidate)
    ranked = sorted(valid, key=lambda c: (c.score, c.canvas_confidence), reverse=True)
    if not ranked:
        raise ValueError('Smart Canvas Drop could not find a supported drawable canvas. Bring the game window fully into view and try again.')
    best = ranked[0]
    if best.canvas_confidence < MIN_CANVAS_CONFIDENCE:
        raise ValueError(f'Smart Canvas Drop canvas confidence is too low ({best.canvas_confidence*100:.0f}%). Use manual canvas selection for now.')
    if len(ranked) > 1 and ranked[1].score >= best.score - gap:
        raise ValueError('Smart Canvas Drop found more than one plausible browser canvas. Keep only the intended game clearly visible or select its target manually first.')
    return best


def _capture_candidate(profile_key: str, meta: Mapping[str, object], *, cancelled=lambda:False) -> SmartCanvasCandidate:
    from ScreenGuard import _grab_rgb
    from BrowserAutoCalibration import detect_browser_canvas

    if cancelled():raise InterruptedError()
    client = normalize_box(meta.get('client_rect'), name='Target client')
    shot = _grab_rgb(client)
    try:detected = detect_browser_canvas(profile_key, shot, screen_origin=client[:2], cancelled=cancelled)
    finally:shot.close()
    canvas = detected.get('canvas_box')
    confidence = float(detected.get('canvas_confidence') or 0.0)
    if canvas is None:
        raise ValueError('No drawable canvas was detected in this browser window.')
    canvas = normalize_box(canvas, name='Canvas')
    if not canvas_inside_client(canvas, client):
        raise ValueError('Detected canvas is outside the browser client area.')
    score = score_candidate(profile_key, confidence=confidence, canvas_box=canvas, client_rect=client, title=str(meta.get('title') or ''))
    return SmartCanvasCandidate(
        handle=int(meta.get('handle') or 0), rect=normalize_box(meta.get('rect'), name='Target window'),
        client_rect=client, dpi=(int(meta['dpi']) if meta.get('dpi') is not None else None),
        pid=(int(meta['target_pid']) if meta.get('target_pid') is not None else int(meta['pid']) if meta.get('pid') is not None else None),
        title=str(meta.get('title') or ''), canvas_box=canvas,
        canvas_confidence=confidence, score=score,
    )


def discover_canvas_target(profile_key: str, *, preferred_handle: int | None = None, exclude_pid: int | None = None,
                           cancelled=lambda:False) -> dict:
    """Find a visible supported browser canvas without sending mouse input."""
    from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
    key = str(profile_key or '').lower()
    if key not in SUPPORTED_BROWSER_PROFILES:
        raise ValueError('Smart Canvas Drop currently supports Gartic Phone, Skribbl.io/Fast, SketchHeads and Sketchful.io.')
    if cancelled():raise InterruptedError()

    # Reuse an explicitly selected target first. This avoids choosing another
    # browser window when the user has already told Image Draw Bot which one to use.
    if preferred_handle:
        try:
            from TargetCapture import probe_handle_isolated
            meta = dict(probe_handle_isolated(int(preferred_handle), cancelled=cancelled))
            meta.setdefault('handle', int(preferred_handle))
            candidate = _capture_candidate(key, meta, cancelled=cancelled)
            if cancelled():raise InterruptedError()
            return choose_candidate([candidate]).as_payload()
        except InterruptedError:raise
        except Exception as error:
            raise ValueError('The selected browser canvas could not be verified. Select its drawing area again.') from error

    from BrowserOneClick import _enumerate_windows
    candidates = []
    for meta in _enumerate_windows(exclude_pid=exclude_pid):
        if cancelled():raise InterruptedError()
        try:
            candidate = _capture_candidate(key, meta, cancelled=cancelled)
            if candidate.canvas_confidence >= MIN_CANVAS_CONFIDENCE:
                candidates.append(candidate)
        except InterruptedError:raise
        except Exception:
            continue
    if cancelled():raise InterruptedError()
    return choose_candidate(candidates).as_payload()


def cursor_position() -> tuple[int, int] | None:
    """Best-effort current cursor position for DnD builds missing x_root/y_root."""
    try:
        import ctypes
        from ctypes import wintypes
        point = wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return int(point.x), int(point.y)
    except Exception:
        pass
    return None


def event_screen_point(event) -> tuple[int, int] | None:
    for x_name, y_name in (('x_root', 'y_root'), ('x', 'y')):
        try:
            x, y = int(getattr(event, x_name)), int(getattr(event, y_name))
            if x_name == 'x_root':
                return x, y
        except Exception:
            continue
    return cursor_position()
