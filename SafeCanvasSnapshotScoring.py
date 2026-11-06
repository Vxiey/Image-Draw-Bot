"""Step 13 — real-result verification from a safe final canvas snapshot.

This module contains only deterministic, local, read-only scoring helpers.  The
execution layer may pass a freshly captured canvas image, but this module never
writes image bytes, screenshots, crops, hashes or thumbnails to disk.  Returned
metadata is limited to compact numeric scores and trust/reason flags.
"""
from __future__ import annotations

from typing import Any, Callable
from numbers import Integral, Real
import math
import numpy as np
from PIL import Image

from AccuracyEvaluator import evaluate_preview, normalize_source

BACKGROUND_RGB = (255, 255, 255)
_SAFE_STATES = {"verified", "scored", "low-trust", "unavailable"}
MAX_COMPARISON_PIXELS = 4_000_000
MAX_COMPARISON_DIMENSION = 16_384


def validated_comparison_size(value) -> tuple[int, int]:
    try:
        width, height = value
    except (TypeError, ValueError) as error:
        raise ValueError('Comparison size must contain two positive integer dimensions.') from error
    if any(isinstance(v, bool) or not isinstance(v, Integral) or v <= 0 for v in (width, height)):
        raise ValueError('Comparison size must contain two positive integer dimensions.')
    width, height = int(width), int(height)
    if max(width, height) > MAX_COMPARISON_DIMENSION or width*height > MAX_COMPARISON_PIXELS:
        raise ValueError('Canvas comparison exceeds the bounded analysis size.')
    return width, height


def trusted_snapshot_evidence(meta: Any) -> bool:
    """Recognize legacy trust labels without overriding explicit negative evidence."""
    if not isinstance(meta, dict) or not meta:
        return False
    for key in ('available', 'trusted', 'geometry_ok'):
        if key in meta and meta[key] is not True:
            return False
    level = str(meta.get('feedback_trust') or '').strip().lower()
    if level and level not in ('high', 'medium'):
        return False
    if meta.get('trusted') is not True and level not in ('high', 'medium'):
        return False
    if 'blank_canvas' in meta and type(meta['blank_canvas']) is not bool:
        return False
    for key in ('confidence_percent', 'visual_accuracy_percent', 'actual_coverage_percent',
                'unexpected_ink_percent', 'perceptual_color_accuracy_percent',
                'actual_vs_simulated_visual_percent'):
        if key not in meta or meta[key] is None:
            continue
        value = meta[key]
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
        try:
            if not math.isfinite(value) or not 0 <= value <= 100:
                return False
        except (TypeError, OverflowError):
            return False
    return any(isinstance(meta.get(key), Real) and not isinstance(meta.get(key), bool)
               for key in ('visual_accuracy_percent', 'actual_coverage_percent'))


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _int_tuple2(value: Any, default: tuple[int, int]) -> tuple[int, int]:
    try:
        a, b = value
        return max(1, int(round(float(a)))), max(1, int(round(float(b))))
    except Exception:
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _rgb_array(image: Image.Image, size: tuple[int, int] | None = None) -> np.ndarray:
    if image.mode == 'RGB' and (size is None or image.size == tuple(size)):
        return np.asarray(image, dtype=np.int16)
    im = normalize_source(image, tuple(size) if size is not None else image.size)
    try:
        return np.asarray(im, dtype=np.int16)
    finally:
        im.close()


def _foreground_mask(image: Image.Image, *, background: tuple[int, int, int] = BACKGROUND_RGB,
                     threshold: int = 18) -> np.ndarray:
    arr = _rgb_array(image)
    bg = np.asarray(background, dtype=np.int16).reshape(1, 1, 3)
    return np.max(np.abs(arr - bg), axis=2) > int(threshold)


def _mask_stats(expected: np.ndarray, actual: np.ndarray) -> dict[str, float | int]:
    expected = np.asarray(expected, dtype=bool)
    actual = np.asarray(actual, dtype=bool)
    expected_count = int(np.count_nonzero(expected))
    actual_count = int(np.count_nonzero(actual))
    overlap = int(np.count_nonzero(expected & actual))
    unexpected = int(np.count_nonzero(actual & ~expected))
    missed = int(np.count_nonzero(expected & ~actual))
    return {
        "expected_foreground_pixels": expected_count,
        "actual_foreground_pixels": actual_count,
        "foreground_overlap_pixels": overlap,
        "missed_foreground_pixels": missed,
        "unexpected_foreground_pixels": unexpected,
        "actual_coverage_percent": 100.0 if expected_count <= 0 else round(overlap * 100.0 / expected_count, 3),
        "unexpected_ink_percent": 0.0 if actual_count <= 0 else round(unexpected * 100.0 / actual_count, 3),
        "blank_canvas": bool(actual_count <= max(2, expected.size // 2500)),
    }


def _trust_from_scores(*, profile_key: str, visual: float | None, simulated_match: float | None,
                       actual_coverage: float | None, unexpected_ink: float | None,
                       expected_foreground: int, blank_canvas: bool,
                       geometry_ok: bool, deadline_safe: bool | None,
                       source_size_ok: bool) -> tuple[str, float, list[str]]:
    reasons: list[str] = []
    confidence = 100.0

    if not geometry_ok:
        reasons.append("capture-geometry-uncertain")
        confidence -= 35.0
    if not source_size_ok:
        reasons.append("source-size-normalized")
        confidence -= 6.0
    if expected_foreground > 0 and blank_canvas:
        reasons.append("blank-or-nearly-blank-canvas")
        confidence -= 55.0
    if actual_coverage is not None and actual_coverage < 55.0 and expected_foreground > 0:
        reasons.append("low-actual-coverage")
        confidence -= 25.0
    if unexpected_ink is not None and unexpected_ink > 35.0:
        reasons.append("unexpected-ink-outside-plan")
        confidence -= 18.0
    if simulated_match is not None and simulated_match < 62.0:
        reasons.append("actual-canvas-differs-from-simulated-final")
        confidence -= 22.0
    if visual is not None and visual < 45.0:
        reasons.append("very-low-source-visual-accuracy")
        confidence -= 10.0
    if deadline_safe is False:
        reasons.append("deadline-ended-tight-or-over-budget")
        confidence -= 12.0

    confidence = _clamp(confidence, 0.0, 100.0)
    if confidence >= 82.0 and not reasons:
        return "high", confidence, reasons
    if confidence >= 68.0 and "blank-or-nearly-blank-canvas" not in reasons:
        return "medium", confidence, reasons
    if confidence >= 35.0:
        return "low", confidence, reasons
    return "none", confidence, reasons


def crop_fitted_canvas(snapshot: Image.Image, *, area: tuple[int, int, int, int],
                       fitted: tuple[float, float]) -> tuple[Image.Image, dict[str, Any]]:
    """Crop the actually drawn fitted frame from a full selected-canvas capture.

    ``area`` is the selected canvas rectangle in screen coordinates as
    ``(left, top, width, height)``.  ``snapshot`` is expected to be a read-only
    capture of that selected canvas.  DPI/window scaling is handled by measuring
    snapshot pixels relative to the selected area.
    """
    if not isinstance(snapshot, Image.Image):
        raise TypeError("snapshot must be a PIL Image")
    if snapshot.width < 2 or snapshot.height < 2:
        raise ValueError("snapshot image is too small")
    try:
        ax, ay, aw, ah = map(float, area)
        fw, fh = map(float, fitted)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('Snapshot canvas geometry must be finite and positive.') from error
    if (not all(math.isfinite(v) for v in (ax, ay, aw, ah, fw, fh))
            or min(aw, ah, fw, fh) <= 0 or fw > aw or fh > ah):
        raise ValueError('Snapshot canvas geometry must be finite, positive, and fit the selected area.')
    scale_x = float(snapshot.width) / aw
    scale_y = float(snapshot.height) / ah
    inset_x = (aw - fw) * 0.5
    inset_y = (ah - fh) * 0.5
    x0 = max(0, int(round(inset_x * scale_x)))
    y0 = max(0, int(round(inset_y * scale_y)))
    x1 = min(snapshot.width, int(round((inset_x + fw) * scale_x)))
    y1 = min(snapshot.height, int(round((inset_y + fh) * scale_y)))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("fitted canvas crop is empty")
    geometry_ok = (x1 - x0) >= 2 and (y1 - y0) >= 2 and 0.25 <= scale_x / max(1e-9, scale_y) <= 4.0
    meta = {
        "crop_box": (int(x0), int(y0), int(x1), int(y1)),
        "capture_size": (int(snapshot.width), int(snapshot.height)),
        "drawn_crop_size": (int(x1 - x0), int(y1 - y0)),
        "selected_area_size": (int(round(aw)), int(round(ah))),
        "fitted_size": (int(round(fw)), int(round(fh))),
        "scale_x": round(scale_x, 5),
        "scale_y": round(scale_y, 5),
        "geometry_ok": bool(geometry_ok),
    }
    cropped = snapshot.crop((x0, y0, x1, y1))
    try:
        return cropped.convert('RGB'), meta
    finally:
        cropped.close()


def score_final_canvas_snapshot(*, snapshot: Image.Image, original_source: Image.Image,
                                area: tuple[int, int, int, int], fitted: tuple[float, float],
                                comparison_size: tuple[int, int] | None = None,
                                simulated_final: Image.Image | None = None,
                                quantized_target: Image.Image | None = None,
                                profile_key: str = "",
                                actual_elapsed_seconds: float | None = None,
                                usable_deadline_seconds: float | None = None,
                                visual_gate_percent: float | None = None,
                                background: tuple[int, int, int] = BACKGROUND_RGB,
                                cancelled: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """Score a finished real drawing from a temporary canvas snapshot.

    The caller owns the screenshot/crop lifetime.  This function returns only
    numeric metrics and reason strings; it never stores or returns images.
    """
    if cancelled():
        raise InterruptedError()
    if not isinstance(original_source, Image.Image):
        return {"available": False, "trusted": False, "feedback_trust": "none", "scoring_state": "unavailable", "reason": "missing original source", "capture_pixels_persisted": False}
    owned = []
    def own(image):
        owned.append(image)
        return image
    try:
        if comparison_size is None:
            if isinstance(simulated_final, Image.Image):
                comparison_size = simulated_final.size
            else:
                comparison_size = original_source.size
        comparison_size = validated_comparison_size(comparison_size)
        crop, geometry = crop_fitted_canvas(snapshot, area=tuple(area), fitted=tuple(fitted))
        own(crop)
        if cancelled():
            raise InterruptedError()
        actual = own(crop.resize(comparison_size, Image.Resampling.LANCZOS))
        source_norm = own(normalize_source(original_source, comparison_size, background=background))
        source_size_ok = bool(getattr(source_norm, "size", None) == comparison_size)

        expected_image = simulated_final if isinstance(simulated_final, Image.Image) else source_norm
        expected_norm = (own(normalize_source(expected_image, comparison_size, background=background))
                         if expected_image is not source_norm else source_norm)
        expected_mask = _foreground_mask(expected_norm, background=background)
        actual_mask = _foreground_mask(actual, background=background)
        mask = _mask_stats(expected_mask, actual_mask)
        actual_coverage = float(mask["actual_coverage_percent"])

        source_metrics = evaluate_preview(source_norm, actual, coverage_percent=actual_coverage,
                                          return_error_map=False, return_delta_e_heatmap=False, cancelled=cancelled)
        simulated_match = None
        simulated_metrics: dict[str, Any] = {}
        if isinstance(simulated_final, Image.Image):
            simulated_metrics = evaluate_preview(expected_norm, actual, coverage_percent=actual_coverage,
                                                 return_error_map=False, return_delta_e_heatmap=False, cancelled=cancelled)
            simulated_match = _float(simulated_metrics.get("visual_accuracy_percent"), None)
        target_match = None
        if isinstance(quantized_target, Image.Image):
            target_norm = (expected_norm if quantized_target is expected_image else
                           own(normalize_source(quantized_target, comparison_size, background=background)))
            target_metrics = evaluate_preview(target_norm, actual, coverage_percent=actual_coverage,
                                              return_error_map=False, return_delta_e_heatmap=False, cancelled=cancelled)
            target_match = _float(target_metrics.get("visual_accuracy_percent"), None)
        else:
            target_metrics = None

        elapsed = _float(actual_elapsed_seconds, None)
        usable = _float(usable_deadline_seconds, None)
        deadline_safe = None if usable is None or elapsed is None else elapsed <= usable - 0.25
        visual = _float(source_metrics.get("visual_accuracy_percent"), None)
        if visual is None or not 0 <= visual <= 100:
            raise ValueError('Final canvas scoring did not produce valid visual evidence.')
        gate = _float(visual_gate_percent, None)
        gate_passed = None if gate is None or visual is None else visual + 1e-9 >= gate
        trust, confidence, reasons = _trust_from_scores(
            profile_key=str(profile_key or ""), visual=visual, simulated_match=simulated_match,
            actual_coverage=actual_coverage, unexpected_ink=_float(mask.get("unexpected_ink_percent"), 0.0),
            expected_foreground=int(mask.get("expected_foreground_pixels") or 0),
            blank_canvas=bool(mask.get("blank_canvas")), geometry_ok=bool(geometry.get("geometry_ok")),
            deadline_safe=deadline_safe, source_size_ok=source_size_ok)
        trusted = trust in ("high", "medium")
        state = "verified" if trusted else ("low-trust" if trust == "low" else "unavailable")
        delta = source_metrics.get("delta_e_oklab") if isinstance(source_metrics.get("delta_e_oklab"), dict) else {}
        meta: dict[str, Any] = {
            "available": True,
            "trusted": bool(trusted),
            "feedback_trust": trust,
            "scoring_state": state if state in _SAFE_STATES else "low-trust",
            "confidence_percent": round(confidence, 2),
            "reasons": tuple(reasons),
            "evidence": "safe read-only final canvas snapshot",
            "method": "actual final canvas snapshot vs original source; local in-memory OKLab evaluation; no image pixels persisted",
            "capture_pixels_persisted": False,
            "image_pixels_persisted": False,
            "stores_image_data": False,
            "privacy": "Only compact metrics and trust flags are kept; canvas/source pixels, screenshots, crops, hashes and thumbnails are discarded.",
            "comparison_size": tuple(map(int, comparison_size)),
            "capture_size": tuple(map(int, geometry["capture_size"])),
            "drawn_crop_size": tuple(map(int, geometry["drawn_crop_size"])),
            "selected_area_size": tuple(map(int, geometry["selected_area_size"])),
            "fitted_size": tuple(map(int, geometry["fitted_size"])),
            "geometry_ok": bool(geometry.get("geometry_ok")),
            "actual_coverage_percent": round(actual_coverage, 2),
            "unexpected_ink_percent": round(float(mask.get("unexpected_ink_percent") or 0.0), 2),
            "expected_foreground_pixels": int(mask.get("expected_foreground_pixels") or 0),
            "actual_foreground_pixels": int(mask.get("actual_foreground_pixels") or 0),
            "blank_canvas": bool(mask.get("blank_canvas")),
            "visual_accuracy_percent": source_metrics.get("visual_accuracy_percent"),
            "source_pixel_accuracy_percent": source_metrics.get("source_pixel_accuracy_percent"),
            "perceptual_color_accuracy_percent": source_metrics.get("perceptual_color_accuracy_percent"),
            "luminance_accuracy_percent": source_metrics.get("luminance_accuracy_percent"),
            "hue_accuracy_percent": source_metrics.get("hue_accuracy_percent"),
            "edge_accuracy_percent": source_metrics.get("edge_accuracy_percent"),
            "delta_e_oklab": {
                "mean_delta_e_oklab": delta.get("mean_delta_e_oklab"),
                "p95_delta_e_oklab": delta.get("p95_delta_e_oklab"),
                "max_delta_e_oklab": delta.get("max_delta_e_oklab"),
                "severe_error_pixels_percent": delta.get("severe_error_pixels_percent"),
            },
            "actual_vs_simulated_visual_percent": None if simulated_match is None else round(float(simulated_match), 2),
            "actual_vs_simulated_source_pixel_percent": None if not simulated_metrics else simulated_metrics.get("source_pixel_accuracy_percent"),
            "actual_vs_quantized_target_visual_percent": None if target_match is None else round(float(target_match), 2),
            "visual_gate_percent": None if gate is None else round(gate, 2),
            "visual_gate_passed": gate_passed,
            "deadline_safe": deadline_safe,
            "actual_elapsed_seconds": None if elapsed is None else round(elapsed, 3),
            "usable_deadline_seconds": None if usable is None else round(usable, 3),
        }
        if not reasons and trusted:
            meta["summary"] = "Real result verified from final canvas snapshot."
        elif trust == "low":
            meta["summary"] = "Real result snapshot scored with low trust: " + ", ".join(reasons[:3])
        elif not trusted:
            meta["summary"] = "Real result snapshot was not trusted: " + ", ".join(reasons[:3])
        else:
            meta["summary"] = "Real result verified with notes: " + ", ".join(reasons[:3])
        if cancelled():
            raise InterruptedError()
        return meta
    except InterruptedError:
        raise
    except Exception as error:
        return {
            "available": False,
            "trusted": False,
            "feedback_trust": "none",
            "scoring_state": "unavailable",
            "reason": str(error)[:240],
            "capture_pixels_persisted": False,
            "image_pixels_persisted": False,
            "stores_image_data": False,
            "privacy": "No screenshot or image pixels were saved.",
        }
    finally:
        for image in reversed(owned):
            image.close()
