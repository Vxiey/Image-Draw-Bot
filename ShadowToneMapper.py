"""Shadow-tone helpers that avoid muddy/crushed dark mappings."""
from __future__ import annotations
from typing import Sequence
from ExactColorEngine import candidate_cost
from ColorFidelity import color_metrics


def shadow_candidate_cost(source: Sequence[int], candidate: Sequence[int], *, importance: float=0.0) -> float:
    cost=candidate_cost(source,candidate,fidelity='Faithful',importance=importance,shadow=True)
    sL,_,_,_=color_metrics(tuple(source[:3]));dL,_,_,_=color_metrics(tuple(candidate[:3]))
    # Extra floor: a non-black shadow should not collapse to near-black unless it is
    # actually a close perceptual match.
    crush=max(0.0,20.0-dL)*0.18 if sL>24.0 else 0.0
    separation=max(0.0,(sL-dL)-28.0)*0.20
    return cost+crush+separation
