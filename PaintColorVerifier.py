"""Perceptual Paint custom-color verification for Image Draw Bot v1.0.124-beta."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from ColorFidelity import color_metrics, delta_e2000
from CalibrationValidation import rgb_value

@dataclass(frozen=True)
class PaintColorVerificationResult:
    requested_rgb: tuple[int,int,int]
    detected_rgb: tuple[int,int,int]
    delta_e2000: float
    lightness_error: float
    saturation_error: float
    accepted: bool
    accepted_with_drift: bool
    retry_recommended: bool
    fallback_required: bool
    reason: str

    def as_dict(self):
        return {
            'requested_rgb':self.requested_rgb,'detected_rgb':self.detected_rgb,
            'delta_e2000':round(self.delta_e2000,3),'lightness_error':round(self.lightness_error,3),
            'saturation_error':round(self.saturation_error,3),'accepted':self.accepted,
            'accepted_with_drift':self.accepted_with_drift,'retry_recommended':self.retry_recommended,
            'fallback_required':self.fallback_required,'reason':self.reason,
        }


def verify_paint_color(requested: Sequence[int], detected: Sequence[int], *, context: str='modal') -> PaintColorVerificationResult:
    req=rgb_value(requested);det=rgb_value(detected)
    if context not in ('modal','rendered','selection'):
        raise ValueError('Unknown Paint color verification context.')
    de=float(delta_e2000(req,det));rL,rS,_,_=color_metrics(req);dL,dS,_,_=color_metrics(det)
    light=abs(rL-dL);sat=abs(rS-dS)
    if context=='rendered':
        exact,de_ok,light_ok=1.8,5.0,8.0
    elif context=='selection':
        exact,de_ok,light_ok=1.4,3.5,6.0
    else:
        exact,de_ok,light_ok=1.4,4.0,7.0
    accepted=de<=de_ok and light<=light_ok
    with_drift=accepted and de>exact
    retry=(not accepted) and de<=12.0 and light<=18.0
    fallback=(not accepted) and not retry
    if accepted and not with_drift:reason='perceptually exact'
    elif with_drift:reason='accepted with small perceptual drift'
    elif retry:reason='color is close enough to justify one retry'
    else:reason='color differs too much; use a verified fallback'
    return PaintColorVerificationResult(req,det,de,light,sat,accepted,with_drift,retry,fallback,reason)
