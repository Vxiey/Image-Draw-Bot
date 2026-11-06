"""Deterministic native stroke-delivery policies for Image Draw Bot.

v1.0.75 splits browser delivery by game. The module controls only native input
spacing/timing; renderer geometry, CanvasGuard and target safety are unchanged.

RC2 Paint hotfix: Pixel Accurate drawings use non-coalesced SendInput movement
while the brush is held. Pen-up travel and UI controls remain on the compatible
cursor path. This prevents modern Paint from dropping dense SetCursorPos drag
updates while preserving the existing safety/compatibility behaviour elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class StrokeDeliveryPolicy:
    step_px: float
    min_path_delay: float
    press_settle: float
    release_settle: float
    drag_backend: str
    native_drag_reliability: bool
    label: str
    palette_click_delay: float = 0.24
    ui_control_delay: float = 0.20
    profile_key: str = 'generic'

    def as_dict(self) -> dict:
        return {
            'step_px': float(self.step_px),
            'min_path_delay': float(self.min_path_delay),
            'press_settle': float(self.press_settle),
            'release_settle': float(self.release_settle),
            'drag_backend': self.drag_backend,
            'native_drag_reliability': bool(self.native_drag_reliability),
            'label': self.label,
            'palette_click_delay': float(self.palette_click_delay),
            'ui_control_delay': float(self.ui_control_delay),
            'profile_key': self.profile_key,
        }


def _profile_key(options: dict) -> str:
    explicit = str(options.get('profile_key') or '').strip().lower()
    if explicit:
        return explicit
    name = str(options.get('profile_name') or '').strip().lower()
    mapping = {
        'microsoft paint': 'microsoft-paint',
        'gartic phone': 'gartic-phone',
        'skribbl.io': 'skribbl',
        'skribbl.io fast': 'skribbl-fast',
        'sketchheads': 'sketchheads',
        'sketchful.io': 'sketchful',
    }
    return mapping.get(name, name.replace(' ', '-'))


def _pixel_accurate_requested(options: dict) -> bool:
    """Return True only for the exact/full-resolution Paint execution path.

    The planner writes ``pixel_accurate=True`` into the final plan. The string
    fallback keeps older/recovered plans safe without promoting ordinary Paint
    drawings to the denser backend unexpectedly.
    """
    if bool(options.get('pixel_accurate')):
        return True
    quality = str(options.get('draw_quality') or '').strip().lower()
    return quality in {'pixel accurate', 'pixel-accurate'}


def resolve_stroke_delivery(options: dict | None, *, dry_run: bool = False) -> StrokeDeliveryPolicy:
    options = options or {}
    try:
        requested = float(options.get('stroke_step_px', 8) or 8)
    except (TypeError, ValueError, OverflowError):
        requested = 8.0
    if not math.isfinite(requested) or requested <= 0:
        requested = 8.0

    key = _profile_key(options)
    paint_profile = bool(options.get('paint_profile')) or key == 'microsoft-paint'
    requested_mode = str(options.get('paint_stroke_delivery') or 'Auto').strip().lower()

    if paint_profile and not dry_run:
        if requested_mode in ('reliable', 'dense', 'sendinput'):
            return StrokeDeliveryPolicy(
                step_px=min(requested, 3.0), min_path_delay=0.0030,
                press_settle=0.008, release_settle=0.005,
                drag_backend='sendinput', native_drag_reliability=True,
                label='Microsoft Paint reliable drag', palette_click_delay=.28,
                ui_control_delay=.22, profile_key=key)
        if requested_mode in ('compatible', 'compatibility', 'cursor'):
            return StrokeDeliveryPolicy(
                step_px=min(requested, 5.0), min_path_delay=0.0020,
                press_settle=0.006, release_settle=0.004,
                drag_backend='cursor', native_drag_reliability=False,
                label='Microsoft Paint compatibility drag', palette_click_delay=.28,
                ui_control_delay=.22, profile_key=key)

        # Auto remains compatibility-first for ordinary Paint drawings, but the
        # full-resolution Pixel Accurate engine can issue thousands of dense
        # held-drag updates. SetCursorPos can coalesce/drop those updates before
        # Paint consumes them, producing visibly dashed/incomplete strokes even
        # though the planner geometry is correct. During a held drag only,
        # WindowsMouse's sendinput backend emits absolute MOVE_NOCOALESCE events.
        # Pen-up moves still use SetCursorPos, so palette/tool/canvas safety is
        # unchanged and the reliable path is narrowly scoped to the failure mode.
        if _pixel_accurate_requested(options):
            return StrokeDeliveryPolicy(
                step_px=min(requested, 2.0), min_path_delay=0.0022,
                press_settle=0.006, release_settle=0.003,
                drag_backend='sendinput', native_drag_reliability=True,
                label='Microsoft Paint Pixel Accurate reliable drag',
                palette_click_delay=.28, ui_control_delay=.22, profile_key=key)

        # RC2 Paint-only line reliability hotfix. Modern Paint can drop short
        # or sharp SetCursorPos-held gestures even when Windows reports every
        # requested endpoint. Browser canvases do not use this branch. Auto now
        # uses non-coalesced SendInput for Paint's normal line/path renderers as
        # well as Pixel Accurate. Explicit Compatible remains an escape hatch.
        drawing_mode=str(options.get('drawing_mode') or options.get('mode') or '').strip().lower()
        line_sensitive=drawing_mode in {
            'shape paths','smart paths (recommended)','lines (fastest)','lines',
        }
        return StrokeDeliveryPolicy(
            step_px=min(requested, 2.0 if line_sensitive else 2.5),
            min_path_delay=(0.0032 if line_sensitive else 0.0030),
            press_settle=0.010, release_settle=0.006,
            drag_backend='sendinput', native_drag_reliability=True,
            label=('Microsoft Paint reliable line drag' if line_sensitive else 'Microsoft Paint reliable drag'),
            palette_click_delay=.28, ui_control_delay=.22, profile_key=key)

    # Dry run must remain click-free, but it should still follow the same cursor
    # density as the target browser so its timing/route sample is representative.
    # No press/release settle is necessary because no button event is sent.
    dry_scale = 0.0 if dry_run else 1.0

    if key == 'gartic-phone':
        # Gartic Phone's HTML5 canvas tolerates wide interpolation well, but its
        # palette/tool UI needs a little more settle time than Skribbl.
        return StrokeDeliveryPolicy(
            step_px=max(requested, 12.0), min_path_delay=.0007 * dry_scale,
            press_settle=.0045 * dry_scale, release_settle=.0030 * dry_scale,
            drag_backend='cursor', native_drag_reliability=False,
            label='Gartic Phone HTML5 input', palette_click_delay=.075,
            ui_control_delay=.085, profile_key=key)

    if key in ('skribbl', 'skribbl-fast'):
        # Skribbl's canvas is responsive and benefits most from fewer native
        # mouse events and short palette switching pauses.
        fast = key == 'skribbl-fast'
        return StrokeDeliveryPolicy(
            step_px=max(requested, 12.0 if fast else 10.0),
            min_path_delay=(.00045 if fast else .00065) * dry_scale,
            press_settle=(.0030 if fast else .0040) * dry_scale,
            release_settle=(.0020 if fast else .0025) * dry_scale,
            drag_backend='cursor', native_drag_reliability=False,
            label=('Skribbl Fast input' if fast else 'Skribbl quality input'),
            palette_click_delay=(.050 if fast else .060),
            ui_control_delay=(.060 if fast else .070), profile_key=key)

    if key == 'sketchheads':
        # SketchHeads has larger animated UI controls along the bottom, so keep
        # control clicks slightly more conservative while still accelerating the
        # actual canvas movement compared with the generic browser path.
        return StrokeDeliveryPolicy(
            step_px=max(requested, 8.0), min_path_delay=.0010 * dry_scale,
            press_settle=.0060 * dry_scale, release_settle=.0040 * dry_scale,
            drag_backend='cursor', native_drag_reliability=False,
            label='SketchHeads canvas input', palette_click_delay=.085,
            ui_control_delay=.095, profile_key=key)

    return StrokeDeliveryPolicy(
        step_px=requested, min_path_delay=0.0,
        press_settle=0.0, release_settle=0.0,
        drag_backend='cursor', native_drag_reliability=False,
        label='Standard drag', palette_click_delay=.24,
        ui_control_delay=.20, profile_key=key or 'generic')
