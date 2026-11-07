"""Source-relative preview accuracy metrics for Image Draw Bot.

The renderer has two different correctness questions:

* Did execution reproduce the internal drawing plan? (plan execution accuracy)
* Does the final simulated drawing still resemble the original source image?

This module answers the second question.  It deliberately does not alter palette
selection, stroke planning or renderer behaviour.
"""
from __future__ import annotations

from contextlib import ExitStack, closing
from typing import Any, Callable
import math
import numpy as np
from PIL import Image

# Centralized Step-1 weights. Missing optional metrics (for example coverage on
# a legacy plan) are removed and the remaining weights are normalized.
VISUAL_ACCURACY_WEIGHTS = {
    'perceptual_color_accuracy_percent': 0.40,
    'luminance_accuracy_percent': 0.20,
    'edge_accuracy_percent': 0.25,
    'coverage_percent': 0.15,
}

_OKLAB_PERCEPTUAL_FULL_ERROR = 0.45
_NEUTRAL_CHROMA_THRESHOLD = 0.025


def normalize_source(source: Image.Image, size: tuple[int, int], *, background=(255, 255, 255)) -> Image.Image:
    """Return one RGB source buffer normalized to the preview/target size.

    Alpha is flattened only for evaluation. The caller's original image is not
    modified. LANCZOS is intentionally used once at the comparison boundary.
    """
    if source.mode == 'RGB' and 'transparency' not in source.info:
        return source.resize(tuple(size), Image.Resampling.LANCZOS) if source.size != tuple(size) else source.copy()
    with ExitStack() as owned:
        rgba = owned.enter_context(closing(source.convert('RGBA')))
        if rgba.size != tuple(size):
            rgba = owned.enter_context(closing(rgba.resize(tuple(size), Image.Resampling.LANCZOS)))
        if rgba.getextrema()[3] == (255, 255):
            return rgba.convert('RGB')
        base = owned.enter_context(closing(Image.new('RGBA', rgba.size, tuple(background[:3]) + (255,))))
        base.alpha_composite(rgba)
        return base.convert('RGB')


def _srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """Vectorized sRGB [0,1] -> OKLab, returned as float32 HxWx3."""
    c = np.asarray(rgb, dtype=np.float32)
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = linear[..., 0], linear[..., 1], linear[..., 2]

    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

    # Values can be microscopically negative after matrix multiplication.
    l_ = np.cbrt(l)
    m_ = np.cbrt(m)
    s_ = np.cbrt(s)

    out = np.empty_like(c, dtype=np.float32)
    out[..., 0] = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    out[..., 1] = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    out[..., 2] = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return out


def _edge_from_luminance(lum: np.ndarray) -> np.ndarray:
    from ImageGradients import luminance_edges
    return luminance_edges(np.asarray(lum, dtype=np.float32))


def _importance_weights(importance, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    if importance is None:
        imp = np.full((size[1], size[0]), 0.5, dtype=np.float32)
    else:
        raw = np.asarray(importance, dtype=np.float32)
        if raw.ndim != 2 or not raw.size or not np.all(np.isfinite(raw)):
            raise ValueError('importance map must be a nonempty finite 2D array')
        imp = np.clip(raw, 0.0, 1.0)
        if imp.shape != (size[1], size[0]):
            with closing(Image.fromarray(imp)) as imp_img, closing(imp_img.resize(tuple(size), Image.Resampling.BILINEAR)) as resized:
                imp = np.asarray(resized, dtype=np.float32)
    return imp, (0.25 + 0.75 * imp).astype(np.float32, copy=False)


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    denom = float(np.sum(weights, dtype=np.float64))
    if denom <= 1e-12:
        return float(np.mean(values, dtype=np.float64))
    return float(np.sum(values * weights, dtype=np.float64) / denom)


def _error_preview(perceptual_error: np.ndarray, luminance_error: np.ndarray,
                   edge_error: np.ndarray, importance: np.ndarray) -> Image.Image:
    """Source-relative heat map. Low error is dark/green, high error red/white."""
    p = np.clip(perceptual_error / _OKLAB_PERCEPTUAL_FULL_ERROR, 0.0, 1.0)
    l = np.clip(luminance_error, 0.0, 1.0)
    e = np.clip(edge_error, 0.0, 1.0)
    combined = np.clip(0.55 * p + 0.20 * l + 0.25 * e, 0.0, 1.0)
    # Important pixels get slightly more visual emphasis without changing metrics.
    combined = np.clip(combined * (0.85 + 0.15 * np.clip(importance, 0.0, 1.0)), 0.0, 1.0)

    out = np.empty((*combined.shape, 3), dtype=np.uint8)
    # Continuous dark-green -> amber -> red/near-white diagnostic ramp.
    low = combined <= 0.5
    t0 = np.where(low, combined * 2.0, 0.0)
    t1 = np.where(low, 0.0, (combined - 0.5) * 2.0)
    out[..., 0] = np.where(low, 30 + 190 * t0, 220 + 35 * t1).astype(np.uint8)
    out[..., 1] = np.where(low, 105 + 55 * t0, 160 - 130 * t1).astype(np.uint8)
    out[..., 2] = np.where(low, 72 - 30 * t0, 42 + 120 * t1).astype(np.uint8)
    return Image.fromarray(out, 'RGB')




def _delta_e_preview(delta: np.ndarray, full_error: float = _OKLAB_PERCEPTUAL_FULL_ERROR) -> Image.Image:
    """Render a standalone OKLab distance heatmap without recomputing OKLab."""
    x=np.clip(np.asarray(delta,dtype=np.float32)/max(1e-6,float(full_error)),0.0,1.0)
    out=np.zeros((*x.shape,3),dtype=np.uint8)
    # dark -> green -> amber -> red -> near-white
    stops=((0.00,(8,15,24)),(0.20,(34,118,85)),(0.45,(224,177,55)),(0.72,(228,78,65)),(1.00,(250,245,245)))
    for (a,ca),(b,cb) in zip(stops,stops[1:]):
        mask=(x>=a)&(x< b if b<1.0 else x<=b)
        if not np.any(mask):continue
        t=((x[mask]-a)/max(1e-9,b-a))[:,None]
        va=np.asarray(ca,dtype=np.float32);vb=np.asarray(cb,dtype=np.float32)
        out[mask]=np.clip(va+(vb-va)*t,0,255).astype(np.uint8)
    return Image.fromarray(out,'RGB')


def _delta_e_summary(delta: np.ndarray) -> dict[str, float | str | tuple[int,int]]:
    d=np.asarray(delta,dtype=np.float32)
    if d.size:
        mean=float(np.mean(d,dtype=np.float64));median=float(np.median(d));p95=float(np.percentile(d,95));maximum=float(np.max(d));severe=float(np.mean(d>=0.20,dtype=np.float64)*100.0)
    else:
        mean=median=p95=maximum=severe=0.0
    return {'space':'OKLab','metric':'euclidean OKLab distance',
            'mean_delta_e_oklab':round(mean,5),'median_delta_e_oklab':round(median,5),
            'p95_delta_e_oklab':round(p95,5),'max_delta_e_oklab':round(maximum,5),
            'severe_error_pixels_percent':round(severe,2)}

def evaluate_preview(source: Image.Image, preview: Image.Image, importance=None, *,
                     normalized_source: Image.Image | None = None,
                     coverage_percent: float | None = None,
                     plan_execution_accuracy_percent: float | None = None,
                     cancelled: Callable[[], bool] = lambda: False,
                     return_error_map: bool = False,
                     return_delta_e_heatmap: bool = False,
                     gpu_mode: str = "Auto", _profile_observation=None) -> dict[str, Any]:
    """Compare the final simulated preview directly with the original source.

    ``coverage_percent`` and ``plan_execution_accuracy_percent`` are accepted
    from the execution simulator because they describe plan execution, not source
    similarity. They are kept separate from the source-relative calculations.
    """
    if cancelled():
        raise InterruptedError()
    observation = _profile_observation
    owned = observation is None
    if owned:
        try:
            from UniversalGpuAcceleration import HardwareProfileObservation
            observation = HardwareProfileObservation()
        except Exception:
            # The numeric stages retain their existing import/CPU fallback.
            observation = None
    try:
        return _evaluate_preview(source, preview, importance,
            normalized_source=normalized_source, coverage_percent=coverage_percent,
            plan_execution_accuracy_percent=plan_execution_accuracy_percent,
            cancelled=cancelled, return_error_map=return_error_map,
            return_delta_e_heatmap=return_delta_e_heatmap, gpu_mode=gpu_mode,
            profile=observation)
    finally:
        if owned and observation is not None:
            observation.close()


def _evaluate_preview(source, preview, importance, *, normalized_source,
                      coverage_percent, plan_execution_accuracy_percent,
                      cancelled, return_error_map, return_delta_e_heatmap,
                      gpu_mode, profile):
    def percentage(value, name):
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f'{name} must be finite')
        return max(0.0, min(100.0, value))
    coverage_percent = percentage(coverage_percent, 'coverage_percent')
    plan_execution_accuracy_percent = percentage(plan_execution_accuracy_percent, 'plan_execution_accuracy_percent')
    size = tuple(map(int, preview.size))
    if min(size) < 1:
        raise ValueError('preview must have positive dimensions')
    source_buffer = normalized_source if isinstance(normalized_source, Image.Image) and normalized_source.size == size else source
    with closing(normalize_source(source_buffer, size)) as src_img, closing(normalize_source(preview, size)) as dst_img:
        src = np.asarray(src_img, dtype=np.float32) / 255.0
        dst = np.asarray(dst_img, dtype=np.float32) / 255.0
    if src.shape != dst.shape:
        raise ValueError('normalized source and preview must have identical dimensions')

    # Source Pixel Accuracy: direct channel similarity. This intentionally is not
    # literal exact-match percentage, which would make tiny antialias differences
    # look catastrophic.
    try:
        from UniversalGpuAcceleration import pixel_channel_error, perceptual_pair
        channel_error, pixel_route = pixel_channel_error(src, dst, gpu_mode=gpu_mode,
                                                        profile=profile, cancelled=cancelled)
    except InterruptedError:
        raise
    except Exception as exc:
        channel_error = np.mean(np.abs(src - dst), axis=2, dtype=np.float32)
        pixel_route = {"backend_id":"cpu:numpy","backend":"CPU/NumPy","fallback_reason":f"{type(exc).__name__}: {exc}"}
    source_pixel_similarity = np.clip(1.0 - channel_error, 0.0, 1.0)
    source_pixel_accuracy = float(np.mean(source_pixel_similarity, dtype=np.float64))
    del channel_error, source_pixel_similarity

    if cancelled():
        raise InterruptedError()
    try:
        src_lab, dst_lab, lab_delta, perceptual_route = perceptual_pair(src, dst, gpu_mode=gpu_mode,
                                                                     profile=profile, cancelled=cancelled)
    except InterruptedError:
        raise
    except Exception as exc:
        src_lab = _srgb_to_oklab(src); dst_lab = _srgb_to_oklab(dst)
        lab_delta = np.linalg.norm(src_lab - dst_lab, axis=2).astype(np.float32, copy=False)
        perceptual_route = {"backend_id":"cpu:numpy","backend":"CPU/NumPy","fallback_reason":f"{type(exc).__name__}: {exc}"}
    del src, dst
    perceptual_similarity = np.clip(1.0 - lab_delta / _OKLAB_PERCEPTUAL_FULL_ERROR, 0.0, 1.0)
    perceptual_accuracy = float(np.mean(perceptual_similarity, dtype=np.float64))

    luminance_error = np.abs(src_lab[..., 0] - dst_lab[..., 0]).astype(np.float32, copy=False)
    luminance_similarity = np.clip(1.0 - luminance_error, 0.0, 1.0)
    luminance_accuracy = float(np.mean(luminance_similarity, dtype=np.float64))
    del luminance_similarity
    if not return_error_map:
        del luminance_error

    src_chroma = np.hypot(src_lab[..., 1], src_lab[..., 2])
    dst_chroma = np.hypot(dst_lab[..., 1], dst_lab[..., 2])
    chromatic = src_chroma >= _NEUTRAL_CHROMA_THRESHOLD
    if np.any(chromatic):
        src_hue = np.arctan2(src_lab[..., 2], src_lab[..., 1])
        dst_hue = np.arctan2(dst_lab[..., 2], dst_lab[..., 1])
        hue_delta = np.abs(np.arctan2(np.sin(src_hue - dst_hue), np.cos(src_hue - dst_hue)))
        hue_similarity = np.clip(1.0 - hue_delta / math.pi, 0.0, 1.0).astype(np.float32, copy=False)
        # Mapping a genuinely chromatic source to a near-neutral result has no
        # meaningful hue preservation and therefore scores zero for that pixel.
        hue_similarity = np.where(chromatic & (dst_chroma < _NEUTRAL_CHROMA_THRESHOLD), 0.0, hue_similarity)
        hue_accuracy = float(np.mean(hue_similarity[chromatic], dtype=np.float64))
        hue_pixels = int(np.count_nonzero(chromatic))
        del src_hue, dst_hue, hue_delta, hue_similarity
    else:
        hue_accuracy = 1.0
        hue_pixels = 0
    del src_chroma, dst_chroma, chromatic

    try:
        from UniversalGpuAcceleration import edge_magnitude
        src_edge, edge_route = edge_magnitude(src_lab[..., 0], gpu_mode=gpu_mode,
                                              profile=profile, cancelled=cancelled)
        dst_edge, edge_route_dst = edge_magnitude(dst_lab[..., 0], gpu_mode=gpu_mode,
                                                profile=profile, cancelled=cancelled)
    except InterruptedError:
        raise
    except Exception as exc:
        src_edge = _edge_from_luminance(src_lab[..., 0]); dst_edge = _edge_from_luminance(dst_lab[..., 0])
        edge_route = {"backend_id":"cpu:numpy","backend":"CPU/NumPy","fallback_reason":f"{type(exc).__name__}: {exc}"}
        edge_route_dst = dict(edge_route)
    del src_lab, dst_lab
    edge_denom = np.maximum(0.04, src_edge + dst_edge)
    edge_error = np.clip(np.abs(src_edge - dst_edge) / edge_denom, 0.0, 1.0).astype(np.float32, copy=False)
    edge_similarity = 1.0 - edge_error
    edge_threshold = max(0.02, float(np.percentile(src_edge, 70.0))) if src_edge.size else 0.02
    # Missing source contours and spurious new contours are both errors.
    # Restricting the mask to source edges alone gave a perfect score to a
    # drawing that preserved those edges but added unrelated shapes elsewhere.
    edge_mask = np.maximum(src_edge, dst_edge) >= edge_threshold
    edge_accuracy = float(np.mean(edge_similarity[edge_mask], dtype=np.float64)) if np.any(edge_mask) else float(np.mean(edge_similarity, dtype=np.float64))
    del src_edge, dst_edge, edge_denom, edge_similarity, edge_mask
    if not return_error_map:
        del edge_error

    imp, weights = _importance_weights(importance, size)
    important_mask = imp >= 0.62
    important_accuracy = (_weighted_mean(perceptual_similarity[important_mask], weights[important_mask])
                          if np.any(important_mask) else _weighted_mean(perceptual_similarity, weights))
    del perceptual_similarity, weights, important_mask

    metric_values = {
        'perceptual_color_accuracy_percent': perceptual_accuracy * 100.0,
        'luminance_accuracy_percent': luminance_accuracy * 100.0,
        'edge_accuracy_percent': edge_accuracy * 100.0,
    }
    if coverage_percent is not None:
        metric_values['coverage_percent'] = max(0.0, min(100.0, float(coverage_percent)))

    active_weight = 0.0
    visual_total = 0.0
    for key, weight in VISUAL_ACCURACY_WEIGHTS.items():
        if key not in metric_values:
            continue
        active_weight += float(weight)
        visual_total += float(weight) * float(metric_values[key])
    visual_accuracy = visual_total / max(1e-9, active_weight)

    result: dict[str, Any] = {
        # Backwards-compatible alias retained for existing plugins/tests. UI must
        # use the explicit source name below.
        'raw_pixel_accuracy_percent': round(source_pixel_accuracy * 100.0, 2),
        'source_pixel_accuracy_percent': round(source_pixel_accuracy * 100.0, 2),
        'perceptual_color_accuracy_percent': round(perceptual_accuracy * 100.0, 2),
        'luminance_accuracy_percent': round(luminance_accuracy * 100.0, 2),
        'hue_accuracy_percent': round(hue_accuracy * 100.0, 2),
        'hue_evaluation_pixels': hue_pixels,
        'edge_accuracy_percent': round(edge_accuracy * 100.0, 2),
        'important_feature_accuracy_percent': round(important_accuracy * 100.0, 2),
        'visual_accuracy_percent': round(visual_accuracy, 2),
        'method': 'final simulated drawing vs original source; sRGB/OKLab source-relative evaluation',
        'visual_accuracy_weights': dict(VISUAL_ACCURACY_WEIGHTS),
        'normalized_source_size': size,
        'delta_e_oklab': _delta_e_summary(lab_delta),
        'acceleration_routes': {
            'pixel_math': dict(pixel_route),
            'delta_e_oklab': dict(perceptual_route),
            'edge_source': dict(edge_route),
            'edge_final': dict(edge_route_dst),
        },
    }
    if coverage_percent is not None:
        result['coverage_percent'] = round(metric_values['coverage_percent'], 2)
    if plan_execution_accuracy_percent is not None:
        result['plan_execution_accuracy_percent'] = round(max(0.0, min(100.0, float(plan_execution_accuracy_percent))), 2)
    if plan_execution_accuracy_percent is not None and float(plan_execution_accuracy_percent) >= 99.95 and perceptual_accuracy < 0.80:
        result['plan_source_divergence_note'] = 'The drawing matches its plan, but the plan differs from the source.'
    if cancelled():
        raise InterruptedError()
    try:
        if return_error_map:
            result['_error_map_image'] = _error_preview(lab_delta, luminance_error, edge_error, imp)
        if return_delta_e_heatmap:
            result['_delta_e_heatmap_image'] = _delta_e_preview(lab_delta)
        if cancelled():
            raise InterruptedError()
        return result
    except BaseException:
        for name in ('_error_map_image', '_delta_e_heatmap_image'):
            image = result.get(name)
            if image is not None:
                image.close()
        raise
