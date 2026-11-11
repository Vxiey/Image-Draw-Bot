"""Adaptive exact-colour count selection for Image Draw Bot Step 5.

This module decides how many colours are *worth keeping* when the user selects
``Exact color count = Auto``.  The recommendation is image-complexity aware and
keeps Step 3/4 protections in mind, but deliberately does not consume the
renderer time budget yet.  Explicit numeric limits remain authoritative.

Pure deterministic planning code: no UI, mouse, browser, filesystem or network
access.  Analysis is performed on a bounded downsample so preview/final planning
can share the same recommendation without a noticeable full-resolution cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack
from math import log2
from typing import Sequence

import numpy as np
from PIL import Image

from ColorMatchingEngine import visible_rgb_image
from ColorFidelity import oklab_metrics, rgb_to_oklab
from DominantHuePreservation import summarize_hue_families
from ImageOwnership import close_image, closing_image

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class AdaptiveColorCountResult:
    recommended: int
    minimum: int
    ceiling: int
    complexity_score: float
    color_entropy: float
    edge_density: float
    tone_bins: int
    dominant_hue_families: tuple[str, ...]
    significant_color_buckets: int
    candidate_color_buckets: int
    weighted_error: float
    marginal_gain: float
    stop_reason: str
    sample_size: tuple[int, int]

    def as_dict(self) -> dict:
        return {
            'active': True,
            'policy': 'image-complexity-v1',
            'recommended_colors': int(self.recommended),
            'minimum_colors': int(self.minimum),
            'ceiling_colors': int(self.ceiling),
            'complexity_score': round(float(self.complexity_score), 4),
            'color_entropy': round(float(self.color_entropy), 4),
            'edge_density': round(float(self.edge_density), 4),
            'tone_bins': int(self.tone_bins),
            'dominant_hue_families': tuple(self.dominant_hue_families),
            'significant_color_buckets': int(self.significant_color_buckets),
            'candidate_color_buckets': int(self.candidate_color_buckets),
            'estimated_weighted_oklab_error': round(float(self.weighted_error), 3),
            'marginal_visual_gain': round(float(self.marginal_gain), 3),
            'stop_reason': str(self.stop_reason),
            'sample_size': tuple(map(int, self.sample_size)),
            'time_budget_applied': False,
        }


def _bounded_sample(image: Image.Image, max_side: int = 176, *, cancelled=lambda: False) -> Image.Image:
    """Keep opaque-import preparation to one source-size channel at a time.

    Pillow resizes each original channel with its own complete BOX operation;
    no private filter/pass order is reproduced here. Transparency still uses
    the original full-resolution composite before any resampling.
    """
    if cancelled():raise InterruptedError('Adaptive color count cancelled.')
    w, h = image.size
    result = None
    try:
        if max(w, h) <= max_side:
            result = visible_rgb_image(image)
        else:
            scale = float(max_side) / float(max(w, h))
            size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
            # BOX is deterministic and preserves coverage better than a
            # sharpening resampler for this statistics-only pass.
            if image.mode == 'RGB' and 'transparency' not in image.info:
                result = image.resize(size, Image.Resampling.BOX)
            elif image.mode == 'L' and 'transparency' not in image.info:
                with closing_image(image.resize(size, Image.Resampling.BOX)) as reduced:
                    if cancelled():raise InterruptedError('Adaptive color count cancelled.')
                    result = reduced.convert('RGB')
            elif image.mode == 'RGBA' and image.getextrema()[3] == (255, 255):
                with ExitStack() as owned:
                    channels = []
                    for name in ('R', 'G', 'B'):
                        if cancelled():raise InterruptedError('Adaptive color count cancelled.')
                        with closing_image(image.getchannel(name)) as channel:
                            if cancelled():raise InterruptedError('Adaptive color count cancelled.')
                            reduced = owned.enter_context(closing_image(channel.resize(size, Image.Resampling.BOX)))
                        channels.append(reduced)
                        if cancelled():raise InterruptedError('Adaptive color count cancelled.')
                    result = Image.merge('RGB', channels)
                    result.info.update(image.info)
            else:
                with closing_image(visible_rgb_image(image)) as visible:
                    if cancelled():raise InterruptedError('Adaptive color count cancelled.')
                    result = visible.resize(size, Image.Resampling.BOX)
        if cancelled():raise InterruptedError('Adaptive color count cancelled.')
        return result
    except BaseException as failure:
        if result is not None:close_image(result, failure)
        raise


def _quantized_candidates(sample: Image.Image, max_candidates: int) -> tuple[list[RGB], list[float]]:
    colors = max(2, min(64, int(max_candidates)))
    with closing_image(sample.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)) as q:
        counts = q.getcolors() or []
        pal = q.getpalette() or []
    total = max(1, sample.width * sample.height)
    rows: list[tuple[RGB, float]] = []
    for count, index in counts:
        base = int(index) * 3
        if base + 2 >= len(pal) or int(count) <= 0:
            continue
        rgb = (int(pal[base]), int(pal[base + 1]), int(pal[base + 2]))
        rows.append((rgb, float(count) / float(total)))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return [r[0] for r in rows], [r[1] for r in rows]


def _entropy(weights: Sequence[float]) -> float:
    vals = [max(0.0, float(w)) for w in weights if float(w) > 0.0]
    if len(vals) <= 1:
        return 0.0
    total = sum(vals) or 1.0
    raw = -sum((w / total) * log2(w / total) for w in vals)
    return max(0.0, min(1.0, raw / max(1e-9, log2(len(vals)))))


def _edge_density(sample: Image.Image) -> float:
    a = np.asarray(sample, dtype=np.float32) / 255.0
    if a.size == 0:
        return 0.0
    lum = a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722
    hits = 0
    total = 0
    if lum.shape[1] > 1:
        d = np.abs(lum[:, 1:] - lum[:, :-1])
        hits += int(np.count_nonzero(d >= .065)); total += int(d.size)
    if lum.shape[0] > 1:
        d = np.abs(lum[1:, :] - lum[:-1, :])
        hits += int(np.count_nonzero(d >= .065)); total += int(d.size)
    return 0.0 if total <= 0 else max(0.0, min(1.0, float(hits) / float(total)))


def _tone_bin(rgb: RGB) -> int:
    L, _C, _H = oklab_metrics(rgb)
    return min(5, max(0, int(float(L) // (100.0 / 6.0))))


def _quality_bounds(ceiling: int, fidelity: str) -> tuple[int, int]:
    cap = max(2, int(ceiling))
    name = str(fidelity or 'Faithful')
    floors = {'Fast': 4, 'Balanced': 5, 'Faithful': 6, 'Exact': 8}
    floor = min(cap, floors.get(name, 6))
    return max(2, floor), cap


def _distance_matrix(colors: Sequence[RGB], *, cancelled=lambda: False) -> np.ndarray:
    if cancelled():
        raise InterruptedError('Adaptive color count cancelled.')
    if not colors:
        return np.zeros((0,0),dtype=np.float32)
    # Step 23 routes quantization-distance work through the Step 22 palette
    # benchmark. <=64 candidate matrices normally remain on CPU because transfer
    # overhead is larger; unusually large reducers can use the measured GPU.
    try:
        from UniversalGpuAcceleration import pairwise_oklab_distance
        matrix, _route = pairwise_oklab_distance(colors, gpu_mode='Auto', cancelled=cancelled)
        if cancelled():
            raise InterruptedError('Adaptive color count cancelled.')
        return np.asarray(matrix,dtype=np.float32)
    except InterruptedError:
        raise
    except Exception:
        if cancelled():
            raise InterruptedError('Adaptive color count cancelled.')
        labs=np.asarray([rgb_to_oklab(tuple(map(int,c[:3]))) for c in colors],dtype=np.float32)
        diff=labs[:,None,:]-labs[None,:,:]
        result=(np.sqrt(np.sum(diff*diff,axis=2,dtype=np.float32))*100.0).astype(np.float32,copy=False)
        if cancelled():
            raise InterruptedError('Adaptive color count cancelled.')
        return result


def _greedy_error_curve(colors: Sequence[RGB], weights: Sequence[float], ceiling: int,
                        fidelity: str, *, cancelled=lambda: False) -> tuple[list[tuple[int, float, float]], list[int]]:
    """Return (count,error,marginal_gain) rows and deterministic retained indexes.

    Pairwise OKLab distances are computed once into a tiny <=64x64 float matrix.
    Adding a colour then becomes a vectorized minimum update instead of repeatedly
    converting the same RGB values inside nested Python loops.
    """
    if cancelled():
        raise InterruptedError('Adaptive color count cancelled.')
    if not colors:
        return [(1, 0.0, 0.0)], [0]
    cap = max(1, min(int(ceiling), len(colors)))
    w=np.asarray([max(0.0,float(v)) for v in weights],dtype=np.float64)
    if float(w.sum())<=0.0:
        w[:]=1.0
    w/=float(w.sum())
    dist=_distance_matrix(colors, cancelled=cancelled)
    ranked = sorted(range(len(colors)), key=lambda i: (-float(weights[i]), i))
    hue_summaries = summarize_hue_families(colors, weights, fidelity=fidelity, max_families=cap)
    keep: list[int] = []

    def add(i: int) -> None:
        if i not in keep and 0 <= i < len(colors) and len(keep) < cap:
            keep.append(i)

    add(ranked[0])
    for summary in hue_summaries:
        candidates = [i for i, rgb in enumerate(colors) if getattr(summary, 'family', None) == _family(rgb)]
        if candidates:
            add(max(candidates, key=lambda i: (weights[i], -i)))
    add(min(range(len(colors)), key=lambda i: (oklab_metrics(colors[i])[0], -weights[i], i)))
    add(max(range(len(colors)), key=lambda i: (oklab_metrics(colors[i])[0], weights[i], -i)))

    current=np.min(dist[:,keep],axis=1) if keep else np.full(len(colors),100.0,dtype=np.float32)
    curve: list[tuple[int, float, float]] = []
    previous = None
    while len(keep) <= cap:
        if cancelled():
            raise InterruptedError('Adaptive color count cancelled.')
        error=float(np.dot(current.astype(np.float64,copy=False),w))
        gain = 0.0 if previous is None else max(0.0, previous - error)
        curve.append((len(keep), error, gain))
        previous = error
        if len(keep) >= cap:
            break
        best=None
        for candidate in ranked:
            if cancelled():
                raise InterruptedError('Adaptive color count cancelled.')
            if candidate in keep:
                continue
            trial=np.minimum(current,dist[:,candidate])
            trial_error=float(np.dot(trial.astype(np.float64,copy=False),w))
            improvement=error-trial_error
            key=(improvement,float(weights[candidate]),-candidate)
            if best is None or key>best[0]:
                best=(key,candidate,trial)
        if best is None:
            break
        add(best[1]); current=best[2]
    if cancelled():
        raise InterruptedError('Adaptive color count cancelled.')
    return curve, keep

def _family(rgb: RGB) -> str | None:
    # Avoid importing the whole Step-3 module twice in callers while retaining
    # its authoritative hue-family classifier.
    from DominantHuePreservation import dominant_hue_family
    return dominant_hue_family(rgb)


def recommend_adaptive_color_count(image: Image.Image, *, ceiling: int,
                                   fidelity: str = 'Faithful', preview: bool = False,
                                   cancelled=lambda: False) -> tuple[int, dict]:
    """Recommend an Auto exact-colour count from bounded image statistics.

    ``ceiling`` is still determined by the existing Draw Quality policy.  Step 5
    only decides how much of that ceiling the image deserves.  No deadline/time
    budget is applied in this step; the metadata states that explicitly so a
    later time-aware stage can compose with this recommendation cleanly.
    """
    if cancelled():
        raise InterruptedError()
    floor, cap = _quality_bounds(ceiling, fidelity)
    candidate_cap = min(64, max(cap * 2, 16))
    with closing_image(_bounded_sample(image, cancelled=cancelled)) as sample:
        sample_size = sample.size
        if cancelled():
            raise InterruptedError()
        colors, weights = _quantized_candidates(sample, candidate_cap)
        if cancelled():
            raise InterruptedError('Adaptive color count cancelled.')
        edge = _edge_density(sample) if colors else 0.0
        if cancelled():
            raise InterruptedError('Adaptive color count cancelled.')
    if not colors:
        result = AdaptiveColorCountResult(
            recommended=floor, minimum=floor, ceiling=cap, complexity_score=0.0,
            color_entropy=0.0, edge_density=0.0, tone_bins=1,
            dominant_hue_families=(), significant_color_buckets=1,
            candidate_color_buckets=0, weighted_error=0.0, marginal_gain=0.0,
            stop_reason='empty-or-unmeasurable-source', sample_size=sample_size)
        return floor, result.as_dict()

    # Tiny quantizer buckets are treated as texture/noise for complexity scoring,
    # but they remain available to the final Step-4 reducer if the recommendation
    # is high enough.
    sig = [i for i, w in enumerate(weights) if w >= .0035]
    if not sig:
        sig = [0]
    sig_colors = [colors[i] for i in sig]
    sig_weights = [weights[i] for i in sig]
    sw_total = sum(sig_weights) or 1.0
    sig_weights = [w / sw_total for w in sig_weights]

    entropy = _entropy(sig_weights)
    tones = len({_tone_bin(rgb) for rgb in sig_colors})
    hue_summaries = summarize_hue_families(sig_colors, sig_weights, fidelity=fidelity, max_families=cap)
    hue_names = tuple(s.family for s in hue_summaries)

    effective_floor=min(floor,max(2,len(sig_colors)))

    # Diversity grows rapidly from 2 -> ~12 useful buckets, then saturates.  Edge
    # density matters, but less than actual colour/tone diversity so line art does
    # not accidentally request a photographic palette.
    diversity = min(1.0, max(0.0, (len(sig_colors) - 1) / 18.0))
    tone_score = min(1.0, max(0.0, (tones - 1) / 5.0))
    hue_score = min(1.0, len(hue_names) / 5.0)
    complexity = max(0.0, min(1.0,
        .38 * entropy + .28 * diversity + .15 * tone_score + .11 * hue_score + .08 * edge))

    curve, _keep = _greedy_error_curve(sig_colors, sig_weights, cap, fidelity, cancelled=cancelled)
    by_count = {count: (error, gain) for count, error, gain in curve}
    available_counts = sorted(by_count)
    max_available = max(available_counts) if available_counts else 1

    # Fidelity controls how much residual OKLab error is acceptable.  The
    # marginal-gain threshold stops extra shades that barely improve the image.
    error_target = {'Fast': 8.0, 'Balanced': 5.8, 'Faithful': 4.3, 'Exact': 3.2}.get(str(fidelity), 4.3)
    gain_target = {'Fast': .80, 'Balanced': .58, 'Faithful': .42, 'Exact': .28}.get(str(fidelity), .42)

    # Complexity supplies a soft target inside the existing quality ceiling.
    soft = int(round(effective_floor + (cap - effective_floor) * (complexity ** .82)))
    soft = max(effective_floor, min(cap, soft))
    # Dominant hues + light/dark structure must fit even when the global score is
    # low.  This composes with Step 3 rather than undoing its guaranteed slots.
    structural_floor = min(cap, len(sig_colors), max(effective_floor, len(hue_names) + (2 if tones >= 3 else 1)))
    target = max(soft, structural_floor)

    chosen = min(cap, max_available)
    reason = 'quality-ceiling'
    last_gain = 0.0
    last_error = by_count.get(chosen, (0.0, 0.0))[0]
    # Pick the first count at/above the soft structural target where either the
    # perceptual error is already good or the next colour has little value.
    for count in available_counts:
        if count < target:
            continue
        error, gain = by_count[count]
        last_gain = gain; last_error = error
        next_rows = [c for c in available_counts if c > count]
        next_gain = by_count[next_rows[0]][1] if next_rows else 0.0
        if error <= error_target:
            chosen = count; reason = 'perceptual-error-target'; break
        if next_gain <= gain_target and count >= structural_floor:
            chosen = count; reason = 'diminishing-visual-return'; break

    # When the sample has fewer meaningful colour buckets than the quality cap,
    # asking for more colours can only split quantizer noise.
    chosen = min(chosen, max(2, len(sig_colors)))
    chosen = max(structural_floor, chosen)
    chosen = max(2, min(cap, chosen))
    if len(sig_colors) <= chosen:
        reason = 'source-color-complexity-satisfied'

    error, gain = by_count.get(min(chosen, max_available), (last_error, last_gain))
    result = AdaptiveColorCountResult(
        recommended=chosen, minimum=effective_floor, ceiling=cap, complexity_score=complexity,
        color_entropy=entropy, edge_density=edge, tone_bins=tones,
        dominant_hue_families=hue_names, significant_color_buckets=len(sig_colors),
        candidate_color_buckets=len(colors), weighted_error=error, marginal_gain=gain,
        stop_reason=reason, sample_size=sample_size)
    if cancelled():
        raise InterruptedError('Adaptive color count cancelled.')
    return chosen, result.as_dict()
