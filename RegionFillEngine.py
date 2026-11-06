"""Region Fill Engine for Image Draw Bot v1.0.119-beta.

This module deliberately builds on Image Draw Bot's existing conservative connected-
component/bucket-fill detector. It adds a second safety/cost layer and produces a
shared plan that preview and final execution can consume without guessing again.

The engine never sends input. It only plans. Runtime CanvasGuard and fill leak
verification remain authoritative during execution.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import ceil, hypot, isfinite
from numbers import Integral, Real
from typing import Any, Iterable

from FillOptimizer import detect_fill_regions
from SpeedOptimizer import normalize_speed, phase_delay
from StrokeDelivery import resolve_stroke_delivery

AGGRESSIVENESS = ("Safe", "Balanced", "Aggressive")
QUALITY_PRESETS = ("Fast", "Balanced", "High Quality", "Pixel Accurate")
_UNSET_MODEL = object()


def _region_evidence(region):
    values=[]
    for key in ('safety_score','bbox_density'):
        value=region.get(key)
        try:valid=not isinstance(value,bool) and isinstance(value,Real) and isfinite(value) and 0<=value<=1
        except (TypeError,ValueError,OverflowError):valid=False
        if not valid:return None
        values.append(float(value))
    for key in ('area_pixels','perimeter_pixels'):
        value=region.get(key)
        if isinstance(value,bool) or not isinstance(value,Integral) or not 0<value<2**63:return None
        values.append(int(value))
    return tuple(values)


def _cost_model(options,image_size,fitted):
    try:
        from ExecutionCostModel import build_cost_model
        return build_cost_model(options,image_size,fitted)
    except InterruptedError:
        raise
    except Exception:
        return None


def _finite_cost(value, *, positive=False):
    try:
        if isinstance(value,bool) or not isinstance(value,Real) or not isfinite(value):return None
        return float(value) if (value>0 if positive else value>=0) else None
    except (TypeError,ValueError,OverflowError):
        return None


@dataclass(frozen=True)
class RegionDecision:
    region_id: int
    accepted: bool
    render_method: str
    fill_confidence: float
    leak_risk: float
    thin_neck_score: float
    stroke_cost_seconds: float
    fill_cost_seconds: float
    estimated_time_saved_seconds: float
    visual_error_cost: float
    seconds_saved_per_visual_error: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_quality(options: dict[str, Any]) -> str:
    if str(options.get("draw_quality") or "") == "Pixel Accurate":
        return "Pixel Accurate"
    if str(options.get("render_preset") or "") == "Extra fast" or normalize_speed(options.get("speed", "Balanced")) == "Fast":
        return "Fast"
    if str(options.get("draw_quality") or "") in ("Maximum likeness", "GPU enhanced"):
        return "High Quality"
    return "Balanced"


def _resolve_detector_mode(aggressiveness: str, quality: str) -> str:
    value = str(aggressiveness or "Balanced")
    if value not in AGGRESSIVENESS:
        value = "Balanced"
    if quality == "High Quality" and value == "Aggressive":
        return "Balanced"
    if quality == "Pixel Accurate":
        return "Conservative"
    return {"Safe": "Conservative", "Balanced": "Balanced", "Aggressive": "Aggressive"}[value]


def _candidate_cap(options: dict[str, Any], aggressiveness: str) -> int:
    # Bound memory/runtime while allowing far more fill regions than the legacy
    # 12-region cap. RAM budget may be supplied by ResourceAllocation.
    base = {"Safe": 128, "Balanced": 256, "Aggressive": 512}.get(aggressiveness, 256)
    try:
        ram = int(options.get("ram_budget_mb") or 512)
    except Exception:
        ram = 512
    if ram < 512:
        base = min(base, 96)
    elif ram < 1024:
        base = min(base, 192)
    return max(24, min(768, base))


def _span_widths(region: dict[str, Any]) -> list[int]:
    out = []
    for raw in region.get("row_spans") or ():
        try:
            _y, left, right = map(int, raw)
        except Exception:
            continue
        out.append(max(1, right - left + 1))
    return out


def _thin_neck_score(region: dict[str, Any], brush_px: int) -> float:
    widths = sorted(_span_widths(region))
    if not widths:
        return 1.0
    # A single one-pixel tip should not condemn a huge otherwise-safe component;
    # use the lower decile as a robust neck estimate.
    sample = widths[min(len(widths) - 1, max(0, int(len(widths) * .10)))]
    critical = max(2.0, float(brush_px) * 1.35)
    if sample >= critical * 2.25:
        return 0.0
    if sample <= critical:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (sample - critical) / (critical * 1.25)))



def _span_contains(region: dict[str, Any], x: int, y: int) -> bool:
    """True only when a source pixel is part of the connected fill component."""
    x = int(x); y = int(y)
    for raw in region.get("row_spans") or ():
        try:
            sy, left, right = map(int, raw)
        except Exception:
            continue
        if sy == y and left <= x <= right:
            return True
    return False


def _diagonal_seal_paths(region: dict[str, Any], *, max_paths: int = 96) -> tuple[list[tuple[tuple[int, int], tuple[int, int]]], int, int]:
    """Return inside-only bridges for one-pixel diagonal contour corners."""
    raw_points = region.get("contour") or ()
    points = []
    for raw in raw_points:
        try:
            points.append((int(raw[0]), int(raw[1])))
        except Exception:
            continue
    if len(points) < 2:
        return [], 0, 0
    pairs = list(zip(points, points[1:]))
    if points[-1] != points[0]:
        pairs.append((points[-1], points[0]))
    paths = []
    seen = set()
    total = 0
    unresolved = 0
    for a, b in pairs:
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        if abs(dx) != 1 or abs(dy) != 1:
            continue
        total += 1
        candidates = ((b[0], a[1]), (a[0], b[1]))
        bridge = next((c for c in candidates if _span_contains(region, c[0], c[1])), None)
        start = a if _span_contains(region, a[0], a[1]) else (b if _span_contains(region, b[0], b[1]) else None)
        if bridge is None or start is None or len(paths) >= max(1, int(max_paths)):
            unresolved += 1
            continue
        key = (start, bridge)
        if key in seen or start == bridge:
            continue
        seen.add(key)
        paths.append(key)
    return paths, total, unresolved


def _fill_escape_prediction(region: dict[str, Any], *, brush_px: int, aggressiveness: str, quality: str) -> tuple[float, list, str]:
    """Predict contour leakage without weakening existing hard safety gates."""
    evidence=_region_evidence(region)
    if evidence is None:return 1.0,[],"invalid region safety evidence"
    safety,density,_area,_perimeter=evidence
    thin = _thin_neck_score(region, brush_px)
    seals, total_diag, unresolved = _diagonal_seal_paths(region)
    unresolved_ratio = (unresolved / max(1, total_diag)) if total_diag else 0.0
    diagonal_pressure = min(1.0, total_diag / max(8.0, float(len(region.get("contour") or ())) * .35)) if total_diag else 0.0
    risk = (1.0 - safety) * .46 + thin * .26 + (1.0 - density) * .08 + diagonal_pressure * .08 + unresolved_ratio * .32
    risk = max(0.0, min(1.0, risk))
    limit = {"Safe": .20, "Balanced": .32, "Aggressive": .42}.get(aggressiveness, .32)
    if quality == "High Quality":
        limit = min(limit, .26)
    elif quality == "Pixel Accurate":
        limit = min(limit, .12)
    if unresolved:
        return risk, [], f"unsealed diagonal contour corner ({unresolved})"
    if risk > limit:
        return risk, [], f"fill escape risk {risk:.2f} > {limit:.2f}"
    if seals:
        return risk, seals, "sealed"
    return risk, [], "safe"



def _seal_cost_seconds(paths, options: dict[str, Any], image_size: tuple[int, int], fitted: tuple[int, int], *, cost_model=_UNSET_MODEL) -> float:
    if not paths:
        return 0.0
    try:
        model=_cost_model(options,image_size,fitted) if cost_model is _UNSET_MODEL else cost_model
        normalized=[]
        for raw_path in paths:
            pts=[]
            for raw in raw_path or ():
                try:pts.append((int(raw[0]),int(raw[1])))
                except Exception:continue
            if pts:normalized.append(tuple(pts))
        if normalized:
            return max(0.0,float(model.paths_seconds(normalized)))
    except InterruptedError:
        raise
    except Exception:
        pass
    delivery = resolve_stroke_delivery(options, dry_run=False)
    speed_name = normalize_speed(options.get("speed", "Balanced"))
    delay = float(options.get("delay", 0.0) or 0.0)
    path_delay = max(float(delivery.min_path_delay), float(phase_delay(delay, speed_name, "path")))
    travel_delay = max(.002, float(phase_delay(delay, speed_name, "travel")))
    boundary_delay = max(.004, float(phase_delay(delay, speed_name, "boundary")))
    step = max(1.0, float(delivery.step_px))
    iw, ih = max(1, int(image_size[0])), max(1, int(image_size[1]))
    fw, fh = max(1, int(fitted[0])), max(1, int(fitted[1]))
    sx, sy = fw / iw, fh / ih
    total=0.0
    for raw_path in paths:
        pts=[]
        for raw in raw_path or ():
            try:pts.append((int(raw[0]),int(raw[1])))
            except Exception:continue
        if len(pts)<2:continue
        length=sum(hypot((b[0]-a[0])*sx,(b[1]-a[1])*sy) for a,b in zip(pts,pts[1:]))
        moves=max(1,int(ceil(length/step)))
        total += travel_delay + moves*path_delay + delivery.press_settle + delivery.release_settle + boundary_delay
    return max(0.0,total)


def _risk(region: dict[str, Any], *, aggressiveness: str, quality: str, brush_px: int) -> tuple[float, float, str]:
    evidence=_region_evidence(region)
    if evidence is None:return 1.0,0.0,"invalid region safety evidence"
    safety,density,area,perimeter=evidence
    contour = region.get("contour") or ()
    vertices = max(1, len(contour) - 1)
    thin = _thin_neck_score(region, brush_px)
    shape_pressure = min(1.0, perimeter / max(8.0, area ** .5 * 14.0))
    vertex_pressure = min(1.0, vertices / 160.0)
    low_density = max(0.0, 1.0 - density)

    # Detector has already hard-rejected holes, open/ambiguous contours and edge
    # touching components. This score is a second conservative layer.
    risk = (
        (1.0 - safety) * .46
        + thin * .24
        + shape_pressure * .12
        + vertex_pressure * .10
        + low_density * .08
    )
    if quality == "High Quality":
        risk *= 1.08
    elif quality == "Fast":
        risk *= .94
    risk = max(0.0, min(1.0, risk))
    confidence = 1.0 - risk

    limits = {"Safe": .14, "Balanced": .24, "Aggressive": .34}
    limit = limits.get(aggressiveness, .24)
    if quality == "High Quality":
        limit = min(limit, .20)
    if quality == "Pixel Accurate":
        limit = min(limit, .10)

    # Hard blockers stay hard regardless of aggressiveness.
    if not contour or len(contour) < 5:
        return 1.0, 0.0, "missing closed contour"
    if thin >= .98 and min(_span_widths(region) or [0]) <= max(1, brush_px):
        return 1.0, 0.0, "thin-neck hard blocker"
    if risk > limit:
        return risk, confidence, f"leak risk {risk:.2f} > {limit:.2f}"
    return risk, confidence, "safe"



def _legacy_region_cost(region: dict[str, Any], options: dict[str, Any], image_size: tuple[int, int], fitted: tuple[int, int]) -> tuple[float, float]:
    """Deterministic emergency fallback with no learned timing dependency."""
    delivery = resolve_stroke_delivery(options, dry_run=False)
    speed_name = normalize_speed(options.get("speed", "Balanced"))
    delay = float(options.get("delay", 0.0) or 0.0)
    path_delay = max(float(delivery.min_path_delay), float(phase_delay(delay, speed_name, "path")))
    travel_delay = max(.002, float(phase_delay(delay, speed_name, "travel")))
    boundary_delay = max(.004, float(phase_delay(delay, speed_name, "boundary")))
    step = max(1.0, float(delivery.step_px))
    iw, ih = max(1, int(image_size[0])), max(1, int(image_size[1]))
    fw, fh = max(1, int(fitted[0])), max(1, int(fitted[1]))
    sx, sy = fw / iw, fh / ih
    stroke_cost = 0.0
    for raw in region.get("row_spans") or ():
        try:_y, left, right = map(int, raw)
        except Exception:continue
        length = max(0.0, (right-left) * sx)
        moves = max(1, int(ceil(length / step)))
        stroke_cost += travel_delay + moves*path_delay + delivery.press_settle + delivery.release_settle + boundary_delay
    perimeter = max(1.0, float(region.get("perimeter_pixels", 1) or 1))
    scaled_perimeter = perimeter * ((sx+sy)*.5)
    contour_moves = max(4, int(ceil(scaled_perimeter / step)))
    fill_cost = travel_delay + contour_moves*path_delay + delivery.press_settle + delivery.release_settle + boundary_delay
    fill_cost += max(.08, delivery.ui_control_delay*.45) + .24
    return max(.001, stroke_cost), max(.001, fill_cost)


def _region_cost(region: dict[str, Any], options: dict[str, Any], image_size: tuple[int, int], fitted: tuple[int, int], *, cost_model=_UNSET_MODEL) -> tuple[float, float]:
    """Compare connected scanlines with Outline + Fill using shared execution cost.

    Safety is decided elsewhere.  This function only answers the performance
    question with the same stateful cursor/drag/switch model used by Adaptive
    Region Hybrid and the visible ETA.  The pre-rc18 formula remains a bounded
    fallback if the shared model cannot cost an unusual region.
    """
    try:
        model=_cost_model(options,image_size,fitted) if cost_model is _UNSET_MODEL else cost_model
        color=max(0,int(region.get("color_index",0) or 0))
        brush=max(1,int(options.get("brush_px",1) or 1))
        stroke_sequence=[]
        for serial,raw in enumerate(region.get("row_spans") or ()):
            try:y,left,right=map(int,raw)
            except Exception:continue
            path=((left,y),) if left==right else ((left,y),(right,y))
            stroke_sequence.append({"color_index":color,"brush_px":brush,"path":path,
                                    "operation_type":"dot" if len(path)==1 else "stroke",
                                    "local_serial":serial})
        stroke_cost=model.sequence_cost(stroke_sequence,initial_color=color,initial_brush=brush).total_seconds

        contour=[]
        for raw in region.get("contour") or ():
            try:contour.append((int(raw[0]),int(raw[1])))
            except Exception:continue
        if contour and len(contour)>1 and contour[0]!=contour[-1]:contour.append(contour[0])
        contour_sequence=[]
        if contour:
            contour_sequence=[{"color_index":color,"brush_px":brush,"path":tuple(contour),
                               "operation_type":"outline"}]
        contour_cost=model.sequence_cost(contour_sequence,initial_color=color,initial_brush=brush).total_seconds
        # One tool switch is deliberately kept batchable, matching the previous
        # RegionFillEngine contract. estimate_fill_execution_seconds removes that
        # per-region share and adds the real calibrated Fill/restore controls once
        # per colour batch.
        fill_cost=(contour_cost+model.switch_cost("tool_change")+
                   model.switch_cost("fill")+model.switch_cost("verification"))
        if stroke_cost>0 and fill_cost>0:
            return max(.001,float(stroke_cost)),max(.001,float(fill_cost))
    except InterruptedError:
        raise
    except Exception:
        pass
    return _legacy_region_cost(region,options,image_size,fitted)


def _batchable_tool_cost(options: dict[str, Any], *, cost_model=_UNSET_MODEL) -> float:
    """Per-region tool-switch share already embedded in the Fill candidate cost."""
    try:
        # Switch cost is independent of geometry; 1x1 keeps this helper cheap.
        model=_cost_model(options,(1,1),(1,1)) if cost_model is _UNSET_MODEL else cost_model
        return max(0.0,float(model.switch_cost("tool_change")))
    except InterruptedError:
        raise
    except Exception:
        delivery=resolve_stroke_delivery(options,dry_run=False)
        return max(.08,float(delivery.ui_control_delay)*.45)

def _region_cost_components(region: dict[str, Any], options: dict[str, Any], image_size: tuple[int, int], fitted: tuple[int, int], *, cost_model=_UNSET_MODEL, seal_cost=None) -> tuple[float, float, float, float]:
    model=_cost_model(options,image_size,fitted) if cost_model is _UNSET_MODEL else cost_model
    stroke_cost, fill_cost = _region_cost(region, options, image_size, fitted, cost_model=model)
    if seal_cost is None:seal_cost = _seal_cost_seconds(region.get("fill_seal_paths") or (), options, image_size, fitted, cost_model=model)
    fill_cost += seal_cost
    batchable = max(0.0, min(_batchable_tool_cost(options,cost_model=model), fill_cost * .50))
    fill_core = max(.001, fill_cost - batchable)
    return stroke_cost, fill_cost, fill_core, batchable


def _decision_fill_cost(fill_cost: float, fill_core: float, options: dict[str, Any]) -> float:
    # Extra Fast performs the authoritative same-colour batch check after this
    # safety/value gate. Do not reject a candidate because the same shareable
    # tool switch was charged once per region before batching.
    return fill_core if options.get("extra_fast") else fill_cost


def build_region_fill_plan(image, fitted: tuple[int, int], options: dict[str, Any], *, safe_margin_px: int = 0, cancelled=lambda: False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return accepted region dictionaries plus planner metadata.

    Pixel Accurate is intentionally protected in this first Region Fill Engine
    release. Its exact simulator currently models strokes, not a bucket-fill
    operation, so the engine refuses to substitute fill until exact fill
    simulation can prove pixel equivalence. This preserves the invariant that
    preview/final/error-map geometry cannot diverge.
    """
    quality = _resolve_quality(options)
    aggressiveness = str(options.get("fill_aggressiveness") or "Balanced")
    if aggressiveness not in AGGRESSIVENESS:
        aggressiveness = "Balanced"

    if quality == "Pixel Accurate":
        return [], {
            "enabled": True,
            "quality_preset": quality,
            "fill_aggressiveness": "Safe",
            "pixel_accurate_protected": True,
            "reason": "Pixel Accurate keeps the exact stroke simulator until bucket-fill simulation can prove exact equivalence.",
            "total_regions": 0,
            "fill_safe_regions": 0,
            "fill_actions": 0,
            "outline_paths": 0,
            "fallback_stroke_regions": 0,
            "fill_coverage_percent": 0.0,
            "estimated_time_saved_seconds": 0.0,
        }

    detector_mode = _resolve_detector_mode(aggressiveness, quality)
    cap = _candidate_cap(options, aggressiveness)
    regions, base_meta = detect_fill_regions(
        image,
        detector_mode,
        engine=options.get("fill_engine", "Auto"),
        max_regions=cap,
        cancelled=cancelled,
        return_meta=True,
        safe_margin_px=safe_margin_px,
    )
    decisions: list[RegionDecision] = []
    accepted: list[dict[str, Any]] = []
    rejected_cost = 0
    rejected_safety = 0
    brush_px = max(1, int(options.get("brush_px", 1) or 1))
    min_saving_ratio = {"Safe": .10, "Balanced": .04, "Aggressive": 0.0}[aggressiveness]
    deadline_active=bool(options.get("time_budget_active"))
    deadline_seconds=float(options.get("max_seconds",180) or 180)
    value_threshold={"Safe":2.0,"Balanced":1.0,"Aggressive":.35}[aggressiveness] if deadline_active and deadline_seconds<=90 else {"Safe":3.0,"Balanced":1.5,"Aggressive":.55}[aggressiveness]
    absolute_saving_floor=.08 if deadline_active and deadline_seconds<=90 else .12
    model=_cost_model(options,image.size,fitted)

    for idx, item in enumerate(regions):
        if cancelled():
            raise InterruptedError()
        region = item.as_dict() if hasattr(item, "as_dict") else dict(item)
        risk, confidence, safety_reason = _risk(
            region, aggressiveness=aggressiveness, quality=quality, brush_px=brush_px
        )
        escape_risk, seal_paths, escape_reason = _fill_escape_prediction(
            region, brush_px=brush_px, aggressiveness=aggressiveness, quality=quality)
        if seal_paths:
            region["fill_seal_paths"] = [tuple(path) for path in seal_paths]
        seal_cost = _seal_cost_seconds(seal_paths, options, image.size, fitted,cost_model=model)
        if safety_reason=="invalid region safety evidence":
            stroke_cost=fill_cost=fill_core=batchable=0.0
        else:
            stroke_cost, fill_cost, fill_core, batchable = _region_cost_components(region, options, image.size, fitted,cost_model=model,seal_cost=seal_cost)
        decision_fill_cost = _decision_fill_cost(fill_cost, fill_core, options)
        saving = max(0.0, stroke_cost - decision_fill_cost)
        thin_score=_thin_neck_score(region, brush_px)
        visual_error=max(.005,min(1.0,risk*.62 + thin_score*.20 + (1.0-confidence)*.18))
        seconds_per_error=saving/max(.01,visual_error)
        cost_ok = decision_fill_cost <= stroke_cost * (1.0 - min_saving_ratio)
        value_ok = saving >= absolute_saving_floor and seconds_per_error >= value_threshold
        safety_ok = safety_reason == "safe" and escape_reason in ("safe", "sealed")
        accepted_here = bool(safety_ok and cost_ok and value_ok)
        reason = "safe and high time-saved/visual-error value"
        if not safety_ok:
            rejected_safety += 1
            reason = safety_reason if safety_reason != "safe" else escape_reason
        elif not cost_ok:
            rejected_cost += 1
            reason = "stroke/run renderer is cheaper"
        elif not value_ok:
            rejected_cost += 1
            reason = f"fill saves too little for visual risk ({seconds_per_error:.2f}s/error)"

        decision = RegionDecision(
            region_id=idx,
            accepted=accepted_here,
            render_method="OUTLINE_FILL" if accepted_here else "HORIZONTAL_RUNS",
            fill_confidence=confidence,
            leak_risk=risk,
            thin_neck_score=thin_score,
            stroke_cost_seconds=stroke_cost,
            fill_cost_seconds=fill_cost,
            estimated_time_saved_seconds=saving if accepted_here else 0.0,
            visual_error_cost=visual_error,
            seconds_saved_per_visual_error=seconds_per_error,
            reason=reason,
        )
        decisions.append(decision)
        if accepted_here:
            region.update({
                "region_fill_id": idx,
                "render_method": "OUTLINE_FILL",
                "fill_confidence": round(confidence, 5),
                "leak_risk": round(risk, 5),
                "thin_neck_score": round(decision.thin_neck_score, 5),
                "stroke_cost_seconds": round(stroke_cost, 5),
                "fill_cost_seconds": round(fill_cost, 5),
                "fill_core_cost_seconds": round(fill_core, 5),
                "fill_batchable_overhead_seconds": round(batchable, 5),
                "estimated_time_saved_seconds": round(saving, 5),
                "visual_error_cost": round(visual_error, 6),
                "seconds_saved_per_visual_error": round(seconds_per_error, 4),
                "fill_escape_risk": round(escape_risk, 5),
                "fill_seal_count": len(seal_paths),
                "fill_seal_cost_seconds": round(seal_cost, 5),
                "fill_strategy": "OUTLINE_SEAL_FILL" if seal_paths else "OUTLINE_FILL",
                "outline_simplification": "exact-collinear",
            })
            accepted.append(region)

    area = max(1, int(image.size[0]) * int(image.size[1]))
    accepted_pixels = sum(max(0, int(r.get("area_pixels", 0) or 0)) for r in accepted)
    saved_strokes = sum(max(0, int(r.get("estimated_saved_strokes", 0) or 0)) for r in accepted)
    total_time_saved = sum(float(r.get("estimated_time_saved_seconds", 0.0) or 0.0) for r in accepted)
    fill_colors = len({int(r.get("color_index", -1)) for r in accepted if int(r.get("color_index", -1)) >= 0})
    total_regions = int(base_meta.get("total_components", 0) or 0)
    fallback = max(0, total_regions - len(accepted))

    meta = dict(base_meta)
    meta.update({
        "enabled": True,
        "engine_name": "Region Fill Engine",
        "quality_preset": quality,
        "fill_aggressiveness": aggressiveness,
        "detector_mode": detector_mode,
        "candidate_cap": cap,
        "total_regions": total_regions,
        "fill_safe_regions": len(accepted),
        "fill_actions": len(accepted),
        "outline_paths": len(accepted),
        "fallback_stroke_regions": fallback,
        "rejected_by_cost": rejected_cost,
        "rejected_by_safety": rejected_safety,
        "fill_coverage_percent": round(accepted_pixels / area * 100.0, 3),
        "estimated_saved_strokes": saved_strokes,
        "estimated_time_saved_seconds": round(total_time_saved, 3),
        "fill_value_policy": "seconds_saved_per_visual_error",
        "fill_value_threshold": value_threshold,
        "fill_absolute_saving_floor_seconds": absolute_saving_floor,
        "average_seconds_saved_per_visual_error": round(sum(float(r.get("seconds_saved_per_visual_error",0) or 0) for r in accepted)/max(1,len(accepted)),3),
        "hybrid_cost_model": model.as_dict() if model is not None else {"source":"legacy RegionFill formula on model error"},
        "fill_color_batches": fill_colors,
        "fill_sealed_regions": sum(1 for r in accepted if r.get("fill_seal_count")),
        "fill_seal_paths": sum(int(r.get("fill_seal_count", 0) or 0) for r in accepted),
        "fill_escape_prediction": "diagonal-corner preseal v1",
        "outline_simplification": "exact-collinear only",
        "region_merging": "disabled here; existing palette/grouping policy remains authoritative",
        "pixel_accurate_protected": False,
        "extra_fast_batch_aware_costing": bool(options.get("extra_fast")),
        "decisions": [d.as_dict() for d in decisions[:80]],
        "decision_count": len(decisions),
    })
    return accepted, meta



def evaluate_region_candidates(regions, image_size: tuple[int, int], fitted: tuple[int, int], options: dict[str, Any], *,
                               base_meta: dict[str, Any] | None = None, cancelled=lambda: False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply Region Fill Engine safety/value policy to pre-detected regions.

    Extra Fast 2.0 uses this for Dynamic/Adaptive Exact groups whose color indexes
    belong to the plan-local palette.  Geometry detection is separate, but the
    same leak-risk, thin-neck and wall-clock value policy remains authoritative.
    """
    quality=_resolve_quality(options)
    aggressiveness=str(options.get('fill_aggressiveness') or 'Balanced')
    if aggressiveness not in AGGRESSIVENESS:aggressiveness='Balanced'
    if quality=='Pixel Accurate':
        return [],{'enabled':True,'quality_preset':quality,'fill_aggressiveness':'Safe','pixel_accurate_protected':True,
                   'reason':'Pixel Accurate keeps exact stroke simulation.','total_regions':0,'fill_safe_regions':0,
                   'fill_actions':0,'outline_paths':0,'fallback_stroke_regions':0,'fill_coverage_percent':0.0,
                   'estimated_time_saved_seconds':0.0}
    base_meta=dict(base_meta or {})
    decisions=[];accepted=[];rejected_cost=0;rejected_safety=0
    brush_px=max(1,int(options.get('brush_px',1) or 1))
    min_saving_ratio={'Safe':.10,'Balanced':.04,'Aggressive':0.0}[aggressiveness]
    deadline_active=bool(options.get('time_budget_active'))
    deadline_seconds=float(options.get('max_seconds',180) or 180)
    value_threshold=({'Safe':2.0,'Balanced':1.0,'Aggressive':.35} if deadline_active and deadline_seconds<=90 else {'Safe':3.0,'Balanced':1.5,'Aggressive':.55})[aggressiveness]
    absolute_saving_floor=.08 if deadline_active and deadline_seconds<=90 else .12
    model=_cost_model(options,image_size,fitted)
    for idx,item in enumerate(regions or ()):
        if cancelled():raise InterruptedError()
        region=item.as_dict() if hasattr(item,'as_dict') else dict(item)
        risk,confidence,safety_reason=_risk(region,aggressiveness=aggressiveness,quality=quality,brush_px=brush_px)
        escape_risk,seal_paths,escape_reason=_fill_escape_prediction(region,brush_px=brush_px,aggressiveness=aggressiveness,quality=quality)
        if seal_paths:region['fill_seal_paths']=[tuple(path) for path in seal_paths]
        seal_cost=_seal_cost_seconds(seal_paths,options,image_size,fitted,cost_model=model)
        if safety_reason=='invalid region safety evidence':
            stroke_cost=fill_cost=fill_core=batchable=0.0
        else:
            stroke_cost,fill_cost,fill_core,batchable=_region_cost_components(region,options,image_size,fitted,cost_model=model,seal_cost=seal_cost)
        decision_fill_cost=_decision_fill_cost(fill_cost,fill_core,options)
        saving=max(0.0,stroke_cost-decision_fill_cost);thin_score=_thin_neck_score(region,brush_px)
        visual_error=max(.005,min(1.0,risk*.62+thin_score*.20+(1.0-confidence)*.18))
        seconds_per_error=saving/max(.01,visual_error)
        cost_ok=decision_fill_cost<=stroke_cost*(1.0-min_saving_ratio)
        value_ok=saving>=absolute_saving_floor and seconds_per_error>=value_threshold
        safety_ok=safety_reason=='safe' and escape_reason in ('safe','sealed');accepted_here=bool(safety_ok and cost_ok and value_ok)
        reason='safe and high time-saved/visual-error value'
        if not safety_ok:rejected_safety+=1;reason=safety_reason if safety_reason!='safe' else escape_reason
        elif not cost_ok:rejected_cost+=1;reason='stroke/run renderer is cheaper'
        elif not value_ok:rejected_cost+=1;reason=f'fill saves too little for visual risk ({seconds_per_error:.2f}s/error)'
        decision=RegionDecision(idx,accepted_here,'OUTLINE_FILL' if accepted_here else 'CONNECTED_SCANLINES',confidence,risk,thin_score,
                                stroke_cost,fill_cost,saving if accepted_here else 0.0,visual_error,seconds_per_error,reason)
        decisions.append(decision)
        if accepted_here:
            region.update({'region_fill_id':idx,'render_method':'OUTLINE_FILL','fill_confidence':round(confidence,5),
                           'leak_risk':round(risk,5),'thin_neck_score':round(thin_score,5),
                           'stroke_cost_seconds':round(stroke_cost,5),'fill_cost_seconds':round(fill_cost,5),
                           'fill_core_cost_seconds':round(fill_core,5),'fill_batchable_overhead_seconds':round(batchable,5),
                           'estimated_time_saved_seconds':round(saving,5),'visual_error_cost':round(visual_error,6),
                           'seconds_saved_per_visual_error':round(seconds_per_error,4),'fill_escape_risk':round(escape_risk,5),
                           'fill_seal_count':len(seal_paths),'fill_seal_cost_seconds':round(seal_cost,5),
                           'fill_strategy':'OUTLINE_SEAL_FILL' if seal_paths else 'OUTLINE_FILL','outline_simplification':'exact-collinear'})
            accepted.append(region)
    area=max(1,int(image_size[0])*int(image_size[1]));accepted_pixels=sum(max(0,int(r.get('area_pixels',0) or 0)) for r in accepted)
    saved_strokes=sum(max(0,int(r.get('estimated_saved_strokes',0) or 0)) for r in accepted)
    total_time_saved=sum(float(r.get('estimated_time_saved_seconds',0) or 0) for r in accepted)
    total_regions=int(base_meta.get('total_components',len(regions or ())) or 0);fallback=max(0,total_regions-len(accepted))
    meta=dict(base_meta);meta.update({'enabled':True,'engine_name':'Region Fill Engine / Extra Fast 2.0','quality_preset':quality,
        'fill_aggressiveness':aggressiveness,'total_regions':total_regions,'fill_safe_regions':len(accepted),'fill_actions':len(accepted),
        'outline_paths':len(accepted),'fallback_stroke_regions':fallback,'rejected_by_cost':rejected_cost,'rejected_by_safety':rejected_safety,
        'fill_coverage_percent':round(accepted_pixels/area*100.0,3),'estimated_saved_strokes':saved_strokes,
        'estimated_time_saved_seconds':round(total_time_saved,3),'fill_value_policy':'seconds_saved_per_visual_error',
        'fill_value_threshold':value_threshold,'fill_absolute_saving_floor_seconds':absolute_saving_floor,
        'fill_color_batches':len({int(r.get('color_index',-1)) for r in accepted if int(r.get('color_index',-1))>=0}),
        'fill_sealed_regions':sum(1 for r in accepted if r.get('fill_seal_count')),
        'fill_seal_paths':sum(int(r.get('fill_seal_count',0) or 0) for r in accepted),'fill_escape_prediction':'diagonal-corner preseal v1',
        'outline_simplification':'exact-collinear only','pixel_accurate_protected':False,
        'fallback_render_method':'CONNECTED_SCANLINES','extra_fast_batch_aware_costing':bool(options.get('extra_fast')),
        'execution_cost_model':'ExecutionCostModel stateful v2','execution_cost_fallback':'legacy RegionFill formula on model error',
        'decisions':[d.as_dict() for d in decisions[:80]],'decision_count':len(decisions)})
    return accepted,meta

def enrich_region_stats(meta: dict[str, Any] | None, *, source_strokes: int, final_paths: int) -> dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    out = dict(meta)
    saved = max(0, int(out.get("estimated_saved_strokes", 0) or 0))
    source = max(0, int(source_strokes or 0))
    out["stroke_reduction_percent"] = round((saved / max(1, source + saved)) * 100.0, 3) if saved else 0.0
    out["source_strokes_after_fill"] = source
    out["final_execution_paths"] = max(0, int(final_paths or 0))
    return out


def estimate_fill_execution_seconds(regions: Iterable[dict[str, Any]], image_size: tuple[int, int], fitted: tuple[int, int], options: dict[str, Any]) -> dict[str, Any]:
    """Batch-aware Fill estimate using the same configured delays as execution."""
    rows = [dict(r) for r in (regions or ())]
    delivery = resolve_stroke_delivery(options, dry_run=False)
    fill_seconds = 0.0
    removed_per_region_switch = 0.0
    model=_cost_model(options,image_size,fitted)
    inferred_batchable = _batchable_tool_cost(options,cost_model=model)
    for region in rows:
        stored_core = _finite_cost(region.get("fill_core_cost_seconds"),positive=True)
        stored_batchable = _finite_cost(region.get("fill_batchable_overhead_seconds",0.0))
        if stored_core is not None and stored_batchable is not None:
            fill_seconds += stored_core
            removed_per_region_switch += stored_batchable
            continue
        stored = _finite_cost(region.get("fill_cost_seconds"),positive=True)
        if stored is not None:
            batchable = max(0.0, min(inferred_batchable, stored * .50))
            fill_seconds += max(0.0, stored - batchable)
            removed_per_region_switch += batchable
            continue
        _stroke, _total, core, batchable = _region_cost_components(region, options, image_size, fitted,cost_model=model)
        fill_seconds += core
        removed_per_region_switch += batchable
    colors = {int(r.get("color_index", -1)) for r in rows if int(r.get("color_index", -1)) >= 0}
    tool_actions = len(options.get("fill_tool_actions") or ()) + len(options.get("fill_restore_actions") or ())
    # Preview planning intentionally does not resolve screen-coordinate tool
    # actions. If calibration says Fill is available, model the final Fill +
    # restore switch pair without inventing coordinates.
    if tool_actions == 0 and options.get("fill_tool_available"):
        tool_actions = 2
    tool_switch_seconds = len(colors) * tool_actions * max(.02, float(delivery.ui_control_delay))
    return {
        "fill_regions": len(rows),
        "fill_color_batches": len(colors),
        "fill_contour_and_click_seconds": round(fill_seconds, 4),
        "fill_tool_switch_seconds": round(tool_switch_seconds, 4),
        "per_region_tool_switch_seconds_removed": round(removed_per_region_switch, 4),
        "batch_aware": True,
        "total_seconds": round(fill_seconds + tool_switch_seconds, 4),
    }
