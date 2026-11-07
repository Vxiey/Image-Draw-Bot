"""Dominant hue preservation for Image Draw Bot Step 3.

Pure planning helpers used by both source-derived exact colour reduction and
browser/game palette reduction.  The policy protects large chromatic families
before spending palette slots on extra shades or small texture colours.

No UI, mouse, filesystem, network or renderer behaviour lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Iterable, Sequence

from ColorFidelity import oklab_metrics

RGB = tuple[int, int, int]

# Representative OKLab hue centres.  These are intentionally broader than the
# previous 30-degree bins: neighbouring shades of one semantic colour family
# should share one protected slot instead of competing with each other.
_FAMILY_CENTRES = (
    ("red", 25.0),
    ("orange", 58.0),
    ("yellow", 108.0),
    ("green", 148.0),
    ("cyan", 195.0),
    ("blue", 260.0),
    ("purple", 295.0),
    ("magenta", 330.0),
)


def _rgb(values: Sequence[int | float]) -> RGB:
    vals=list(values[:3])
    while len(vals)<3: vals.append(0)
    return tuple(max(0,min(255,int(round(float(v))))) for v in vals)  # type: ignore[return-value]


def _circular_distance(a: float, b: float) -> float:
    d=abs(float(a)-float(b))%360.0
    return min(d,360.0-d)


def _threshold(value):
    try:
        valid=not isinstance(value,bool) and isinstance(value,Real) and math.isfinite(value) and value>=0
    except OverflowError:
        valid=False
    if not valid:
        raise ValueError('Hue chroma threshold must be finite and nonnegative.')
    return float(value)


def _family(chroma, hue, threshold):
    if chroma < threshold:
        return None
    return min(_FAMILY_CENTRES,key=lambda item:(_circular_distance(hue,item[1]),item[1]))[0]


def _cap(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError('Hue family limit must be a nonnegative integer.')
    return int(value)


def dominant_hue_family(rgb: Sequence[int], *, chroma_threshold: float=4.5) -> str | None:
    """Return a broad OKLab hue family, or None for near-neutral colours."""
    threshold=_threshold(chroma_threshold)
    _L,C,H=oklab_metrics(_rgb(rgb))
    return _family(C,H,threshold)


@dataclass(frozen=True)
class HueFamilySummary:
    family: str
    weight: float
    coverage: float
    representative_index: int
    representative_rgb: RGB
    representative_chroma: float


def _coverage_threshold(fidelity: str) -> float:
    # "Large main colours" are deliberately based on total visible mass, not
    # only chromatic mass.  This prevents a tiny saturated accent from stealing
    # a protected slot in an otherwise neutral image.
    return {
        "Fast": .085,
        "Balanced": .055,
        "Faithful": .035,
        "Exact": .025,
    }.get(str(fidelity or "Faithful"),.035)


def summarize_hue_families(colors: Sequence[Sequence[int]], weights: Sequence[float], *,
                           fidelity: str="Faithful", max_families: int | None=None,
                           chroma_threshold: float=4.5) -> list[HueFamilySummary]:
    """Summarise dominant chromatic families by weighted visible coverage.

    A family receives at most one representative: the colour with the strongest
    combination of area and chroma.  Families below the fidelity-dependent
    coverage floor are treated as texture/accent colours rather than guaranteed
    palette anchors.
    """
    cap=_cap(max_families)
    chroma_threshold=_threshold(chroma_threshold)
    if len(colors)!=len(weights):
        raise ValueError('Every hue color needs one matching weight.')
    total=0.0
    for value in weights:
        try:
            if isinstance(value,bool) or not isinstance(value,Real) or not math.isfinite(value) or value<0:
                raise ValueError('Hue weights must be finite and nonnegative.')
            total+=float(value)
        except OverflowError as error:
            raise ValueError('Hue weight exceeds the supported numeric range.') from error
    if not math.isfinite(total):
        raise ValueError('Combined hue weight exceeds the supported numeric range.')
    if cap==0 or total==0:
        return []
    buckets: dict[str,dict] = {}
    for i,(rgb,w) in enumerate(zip(colors,weights)):
        weight=max(0.0,float(w))
        if weight<=0: continue
        color=_rgb(rgb)
        _L,C,H=oklab_metrics(color)
        family=_family(C,H,chroma_threshold)
        if family is None: continue
        row=buckets.setdefault(family,{'weight':0.0,'best':None,'best_key':None})
        row['weight']+=weight
        key=(weight*(1.0+min(40.0,C)/160.0),weight,C,-i)
        if row['best_key'] is None or key>row['best_key']:
            row['best_key']=key
            row['best']=(i,weight,C,color)
    threshold=_coverage_threshold(fidelity)
    summaries=[]
    for family,row in buckets.items():
        coverage=float(row['weight'])/total
        if coverage+1e-12 < threshold:
            continue
        # Area dominates. Chroma only breaks close calls so a vivid family
        # representative is preferred over a muddy shade with similar mass.
        i,w,C,rgb=row['best']
        summaries.append(HueFamilySummary(family,float(row['weight']),coverage,int(i),rgb,float(C)))
    summaries.sort(key=lambda s:(-s.weight,-s.representative_chroma,s.representative_index,s.family))
    if cap is not None:
        summaries=summaries[:cap]
    return summaries


def dominant_hue_anchors(colors: Sequence[Sequence[int]], weights: Sequence[float], cap: int, *,
                         fidelity: str="Faithful") -> tuple[list[int],dict]:
    """Return palette indices that must be reserved before shade/detail slots."""
    cap=_cap(cap)
    summaries=summarize_hue_families(colors,weights,fidelity=fidelity,max_families=cap)
    anchors=[s.representative_index for s in summaries]
    return anchors,{
        'dominant_hue_families':tuple(s.family for s in summaries),
        'dominant_hue_coverage':{s.family:round(s.coverage,5) for s in summaries},
        'dominant_hue_anchor_indexes':tuple(anchors),
        'dominant_hue_preservation':bool(summaries),
    }


def protected_hue_families(colors: Sequence[Sequence[int]], weights: Sequence[float], cap: int, *,
                           fidelity: str="Faithful") -> tuple[str,...]:
    return tuple(s.family for s in summarize_hue_families(colors,weights,fidelity=fidelity,max_families=_cap(cap)))
