"""Classify execution interruptions for safe path-level browser recovery.

Smart Recovery never authorizes native input and never restarts a drawing by
itself.  It only decides whether the current not-yet-completed path may be
checkpointed so the next explicit Start can run normal browser recalibration /
visual preflight and resume safely.
"""
from __future__ import annotations

from dataclasses import dataclass

from TargetCapabilities import auto_browser_profile_keys

SUPPORTED_BROWSER_PROFILES = auto_browser_profile_keys()


@dataclass(frozen=True)
class RecoveryDecision:
    recoverable: bool
    reason: str
    requires_recalibration: bool = True
    full_stop: bool = False

    def as_dict(self):
        return {
            'recoverable': bool(self.recoverable),
            'reason': self.reason,
            'requires_recalibration': bool(self.requires_recalibration),
            'full_stop': bool(self.full_stop),
        }


def classify_interruption(error: BaseException, profile_key: str) -> RecoveryDecision:
    key=str(profile_key or '').strip().lower()
    if key not in SUPPORTED_BROWSER_PROFILES:
        return RecoveryDecision(False,'non-browser profile',False,True)
    text=str(error or '').strip().lower()
    name=error.__class__.__name__.lower()

    if isinstance(error, (KeyboardInterrupt, SystemExit)) or 'time limit reached' in text:
        return RecoveryDecision(False,'explicit/time-budget stop',False,False)

    # Hard safety/geometry failures must never become an automatic "just resume"
    # condition.  The normal target/canvas safety workflow must be completed.
    hard_tokens=(
        'canvasguard','canvas safety','outside the selected canvas','target window moved',
        'target window geometry changed','drawing area','dpi changed','client area changed',
        'canvas moved','canvas changed','target changed','select the drawing area again','title bar/window border',
    )
    from CanvasGuard import CanvasSafetyStop
    if isinstance(error, CanvasSafetyStop) or any(token in text for token in hard_tokens):
        return RecoveryDecision(False,'canvas/target safety changed',True,True)

    if 'target window no longer exists' in text or 'target window is not visible' in text:
        return RecoveryDecision(True,'target temporarily unavailable',True,True)

    # A bounded Stroke Delivery Verification failure means the current path was
    # deliberately *not* marked complete.  It is safe to retry that exact path
    # after the next read-only browser recalibration/preflight.
    if 'strokedeliveryverificationerror' in name or 'stroke delivery verification failed' in text:
        return RecoveryDecision(True,'stroke delivery could not be confirmed',True,False)

    transient_tokens=(
        'mouse was moved manually',
        'another window covers the click position',
        'wrong window is active',
        'target application is not active',
        'foreground window',
        'temporarily covered',
    )
    if any(token in text for token in transient_tokens):
        return RecoveryDecision(True,'transient input/foreground interruption',True,False)

    # Explicit stop/time limits are not silently resumable.  The user may still
    # keep the older completed-color checkpoint, but no in-flight path is marked.
    if 'time limit reached' in text or isinstance(error, KeyboardInterrupt):
        return RecoveryDecision(False,'explicit/time-budget stop',False,False)
    return RecoveryDecision(False,'unclassified interruption',False,False)
