"""Per-stroke delivery verification for browser drawing canvases.

The verifier is deliberately conservative: it never creates input itself.  It
only inspects the just-rendered stroke and tells DrawBot whether one bounded
retry is warranted.  CanvasGuard/FinalMouseGuard remain authoritative for every
retry.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from TargetCapabilities import auto_browser_profile_keys

SUPPORTED_BROWSER_PROFILES = auto_browser_profile_keys()


class StrokeDeliveryVerificationError(InterruptedError):
    """A browser stroke could not be confirmed after the bounded retry cap."""


@dataclass(frozen=True)
class DeliveryVerificationPolicy:
    profile_key: str
    enabled: bool
    retry_cap: int
    tolerance: int
    min_length_px: float
    verify_settle: float
    retry_step_scale: float
    retry_min_delay: float
    retry_press_settle: float
    retry_release_settle: float

    def as_dict(self) -> dict:
        return {
            'profile_key': self.profile_key,
            'enabled': bool(self.enabled),
            'retry_cap': int(self.retry_cap),
            'tolerance': int(self.tolerance),
            'min_length_px': float(self.min_length_px),
            'verify_settle': float(self.verify_settle),
            'retry_step_scale': float(self.retry_step_scale),
            'retry_min_delay': float(self.retry_min_delay),
            'retry_press_settle': float(self.retry_press_settle),
            'retry_release_settle': float(self.retry_release_settle),
        }


def resolve_policy(options: dict | None, *, dry_run: bool = False) -> DeliveryVerificationPolicy:
    options = options or {}
    key = str(options.get('profile_key') or '').strip().lower()
    supported = key in SUPPORTED_BROWSER_PROFILES
    explicitly_disabled = str(options.get('stroke_delivery_verification', 'Auto')).strip().lower() in {
        'off', 'disabled', 'false', '0'
    }
    enabled = supported and not dry_run and not explicitly_disabled

    # HTML5 canvases may anti-alias differently per game.  These tolerances are
    # intentionally wider than Paint's exact-color verifier because the goal is
    # delivery confirmation, not palette calibration.
    tolerance = {
        'gartic-phone': 86,
        'skribbl': 82,
        'skribbl-fast': 88,
        'sketchheads': 94,
        'sketchful': 90,
    }.get(key, 84)
    min_length = 5.0 if key != 'sketchheads' else 6.0
    return DeliveryVerificationPolicy(
        profile_key=key,
        enabled=enabled,
        retry_cap=1,
        tolerance=tolerance,
        min_length_px=min_length,
        verify_settle=.018,
        retry_step_scale=.50,
        retry_min_delay=.0022 if key == 'skribbl-fast' else .0028,
        retry_press_settle=.007,
        retry_release_settle=.005,
    )


def path_length(start, end) -> float:
    try:
        return math.hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1]))
    except Exception:
        return 0.0


def inspect_delivery(mouse, start, end, expected, brush_px: int, policy: DeliveryVerificationPolicy) -> dict:
    """Inspect one delivered stroke without sending any native input.

    Unsupported/fake mouse backends return a benign skipped result so unit
    tests, dry-run backends and non-Windows environments do not become new
    failure sources.
    """
    if not policy.enabled:
        return {'supported': False, 'checked': False, 'matched': True, 'reason': 'disabled'}
    if path_length(start, end) < policy.min_length_px:
        return {'supported': True, 'checked': False, 'matched': True, 'reason': 'stroke too short for reliable visual delivery check'}
    inspector = getattr(mouse, 'inspect_ink_coverage', None)
    if not callable(inspector):
        inspector = getattr(mouse, 'inspect_ink_segment', None)
    if not callable(inspector):
        return {'supported': False, 'checked': False, 'matched': True, 'reason': 'screen ink inspection unavailable'}
    result = inspector(start, end, expected, brush_px, policy.tolerance)
    if not isinstance(result, dict):
        return {'supported': True, 'checked': True, 'matched': False, 'reason': 'invalid verifier response'}
    payload = dict(result)
    payload['supported'] = True
    payload['checked'] = True
    payload['matched'] = payload.get('matched') is True
    if type(result.get('matched')) is not bool:
        payload['reason'] = 'invalid verifier response: matched must be a boolean'
    return payload


def retry_parameters(policy: DeliveryVerificationPolicy, base_step_px: float, base_delay: float) -> dict:
    """Return a denser/slower one-stroke retry policy."""
    try:
        base = float(base_step_px)
        delay = float(base_delay)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('Retry spacing and delay must be finite and non-negative.') from error
    if not math.isfinite(base) or base <= 0 or not math.isfinite(delay) or delay < 0:
        raise ValueError('Retry spacing and delay must be finite and non-negative.')
    step = min(base, max(min(2.0, base), base * policy.retry_step_scale))
    return {
        'step_px': step,
        'path_delay': max(delay, policy.retry_min_delay),
        'press_settle': policy.retry_press_settle,
        'release_settle': policy.retry_release_settle,
    }
