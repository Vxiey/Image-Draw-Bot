"""Measured/calibrated draw-time estimates for Image Draw Bot.

The visible estimate is based on the actual final execution sequence whenever it
exists: ordered paths, colour changes, brush changes, Fill batches/clicks and
verification operations. Completed local runtime samples then correct that
cold-start operation model for the current profile/machine. No network telemetry
is used.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from CompletedDrawLearning import timing_sample_gate


@dataclass(frozen=True)
class DrawTimeEstimate:
    preview_seconds: float
    projected_seconds: float
    low_seconds: float
    high_seconds: float
    confidence: str
    multiplier: float
    is_projection: bool
    reason: str
    estimate_source: str = "operation timing model"
    measured_samples: int = 0
    calibration_ratio: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "preview_seconds": round(float(self.preview_seconds), 3),
            "projected_seconds": round(float(self.projected_seconds), 3),
            "low_seconds": round(float(self.low_seconds), 3),
            "high_seconds": round(float(self.high_seconds), 3),
            "confidence": self.confidence,
            "multiplier": round(float(self.multiplier), 4),
            "is_projection": bool(self.is_projection),
            "reason": self.reason,
            "estimate_source": self.estimate_source,
            "measured_samples": int(self.measured_samples),
            "calibration_ratio": round(float(self.calibration_ratio), 4),
            "preview_label": format_duration(self.preview_seconds),
            "projected_label": format_duration(self.projected_seconds),
            "range_label": format_range(self.low_seconds, self.high_seconds),
        }


def _area(value: Any) -> tuple[int, int] | None:
    try:
        w, h = int(value[0]), int(value[1])
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return w, h


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    rem = int(round(seconds - minutes * 60))
    if rem >= 60:
        minutes += 1
        rem -= 60
    if minutes < 60:
        return f"{minutes}m {rem:02d}s" if rem else f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins:02d}m" if mins else f"{hours}h"


def format_range(low_seconds: float, high_seconds: float) -> str:
    low = max(0.0, float(low_seconds or 0.0))
    high = max(low, float(high_seconds or low))
    if abs(high - low) < 1.0:
        return format_duration(high)
    return f"{format_duration(low)}–{format_duration(high)}"


def _projection_exponent(options: dict[str, Any], path_stats: dict[str, Any]) -> tuple[float, str]:
    quality = str(options.get("draw_quality") or "")
    mode = str(path_stats.get("mode") or options.get("drawing_mode") or "")
    if "Pixel Accurate" in quality or path_stats.get("pixelmap"):
        return 1.00, "pixel-accurate area scaling"
    if mode == "Shape paths" or path_stats.get("shape_model"):
        return 0.56, "component/path scaling"
    if path_stats.get("joined_strokes"):
        return 0.64, "continuous-path scaling"
    return 0.70, "stroke-density scaling"


def _local_calibration(options: dict[str, Any]) -> dict[str, Any]:
    try:
        from DrawTimeCalibration import correction_for
        return correction_for(options)
    except Exception:
        return {"learned": False, "samples": 0, "ratio": 1.0, "mape": None}


def _count_transitions(values, initial=None, *, count_first=True) -> int:
    count=0;previous=initial;have_previous=initial is not None
    for value in values:
        if value is None:continue
        if not have_previous:
            count += 1 if count_first else 0
            previous=value;have_previous=True;continue
        if value != previous:
            count+=1;previous=value
    return count


def _path_scale(plan: dict[str,Any], options: dict[str,Any]) -> tuple[float,float]:
    sx=sy=1.0
    image=plan.get("image")
    fitted=plan.get("fitted")
    try:
        iw,ih=map(int,image.size);fw,fh=map(int,fitted)
        if iw>0 and ih>0 and fw>0 and fh>0:sx=fw/iw;sy=fh/ih
    except Exception:
        pass
    try:sx=float(options.get("_hybrid_scale_x",sx) or sx)
    except Exception:pass
    try:sy=float(options.get("_hybrid_scale_y",sy) or sy)
    except Exception:pass
    return max(.001,sx),max(.001,sy)



def _sequence_operation_estimate(plan: dict[str,Any]) -> tuple[float,dict[str,Any]]:
    """Cost the exact final execution order with the planner's stateful cost model.

    The underlying ExecutionCostModel is deliberately forced to cold/unlearned
    calibration here. DrawTimeEstimate applies DrawTimeCalibration once, after the
    complete stroke + Fill + fixed-overhead estimate has been assembled.
    """
    sequence=[row for row in (plan.get("execution_sequence") or ()) if isinstance(row,dict)]
    if not sequence:
        return 0.0,{"used":False,"reason":"no final execution_sequence"}
    options=plan.get("options") if isinstance(plan.get("options"),dict) else {}
    model_options=dict(options)
    cold={"learned":False,"samples":0,"ratio":1.0,"mape":None,"operation_runtime":{}}
    model_options["_execution_cost_calibration_override"]=cold
    model_options["_hybrid_cost_calibration_override"]=cold

    image_size=None
    image=plan.get("image")
    try:image_size=tuple(map(int,image.size))
    except Exception:image_size=None
    if not image_size:
        image_size=_area(plan.get("plan_area") or options.get("_preview_area") or options.get("_target_area")) or (1,1)
    try:fitted=tuple(map(int,plan.get("fitted")))
    except Exception:fitted=None
    if not fitted:
        fitted=_area(plan.get("target_area") or options.get("_target_area") or plan.get("plan_area")) or image_size

    try:
        from ExecutionCostModel import build_cost_model as build_execution_cost_model
        model=build_execution_cost_model(model_options,image_size,fitted)
    except Exception as exc:
        return 0.0,{"used":False,"reason":f"execution cost model unavailable: {type(exc).__name__}"}

    try:initial_brush=max(1,int(options.get("brush_px",1) or 1))
    except Exception:initial_brush=1
    breakdown=model.sequence_cost(sequence,initial_brush=initial_brush)
    sequence_seconds=max(0.0,float(breakdown.total_seconds or 0.0))
    total=sequence_seconds

    path_rows=[];path_kinds=set();operation_counts={}
    for row in sequence:
        operation=str(row.get("operation_type") or ("dot" if len(row.get("path") or ())<=1 else "stroke"))
        if row.get("path"):
            path_rows.append(row);path_kinds.add(operation)
        operation_counts[operation]=operation_counts.get(operation,0)+1

    fill_regions=[row for row in (options.get("fill_regions") or plan.get("fill_regions") or ()) if isinstance(row,dict)]
    fill_meta={"fill_regions":0,"fill_color_batches":0,"total_seconds":0.0,
               "fill_contour_and_click_seconds":0.0,"fill_tool_switch_seconds":0.0}
    if fill_regions:
        try:
            from RegionFillEngine import estimate_fill_execution_seconds
            fill_meta=dict(estimate_fill_execution_seconds(fill_regions,image_size,fitted,model_options) or {})
        except Exception:
            fill_meta={"fill_regions":len(fill_regions),"fill_color_batches":0,
                       "total_seconds":len(fill_regions)*model.switch_cost("fill"),
                       "fill_contour_and_click_seconds":len(fill_regions)*model.switch_cost("fill"),
                       "fill_tool_switch_seconds":0.0,"fallback":True}
        total+=max(0.0,float(fill_meta.get("total_seconds") or 0.0))

    # Background Fill is a separate prelude and is not part of region Fill rows.
    background=options.get("background_fill_plan") or {}
    background_seconds=0.0;background_fill_actions=0;background_tool_changes=0;background_verifications=0
    if isinstance(background,dict) and background.get("enabled"):
        background_fill_actions=1;background_verifications=1
        tool_action_count=len(options.get("fill_tool_actions") or ())+len(options.get("fill_restore_actions") or ())
        if tool_action_count==0 and options.get("fill_tool_available"):tool_action_count=2
        background_tool_changes=tool_action_count
        background_seconds=(model.switch_cost("fill")+model.switch_cost("verification")+
                            background_tool_changes*model.switch_cost("tool_change"))
        total+=background_seconds

    deadline_meta=options.get("adaptive_deadline_meta") or {}
    fixed=deadline_meta.get("fixed_overhead") or {}
    outside_sequence=0.0
    for key in ("countdown_seconds","clear_seconds"):
        try:outside_sequence+=max(0.0,float(fixed.get(key,0.0) or 0.0))
        except Exception:pass
    total+=outside_sequence

    # Operation-level measured correction uses the same final counts, but is
    # applied later. Keep model averages here cold to prevent double learning.
    model_average_seconds={}
    path_seconds=(max(0.0,float(breakdown.drag_seconds))+max(0.0,float(breakdown.travel_seconds))+
                  max(0.0,float(breakdown.press_release_seconds))+max(0.0,float(breakdown.target_processing_seconds)))
    if path_rows:
        avg=path_seconds/max(1,len(path_rows))
        for kind in path_kinds:model_average_seconds[str(kind)]=avg
    palette_n=max(0,int(breakdown.palette_switches or 0))
    brush_n=max(0,int(breakdown.brush_switches or 0))
    tool_n=max(0,int(breakdown.tool_switches or 0))+background_tool_changes
    if palette_n:
        operation_counts["palette_change"]=palette_n
        model_average_seconds["palette_change"]=max(0.0,float(breakdown.palette_seconds))/palette_n
    if brush_n:
        operation_counts["tool_change"]=operation_counts.get("tool_change",0)+brush_n
        model_average_seconds["tool_change"]=max(0.0,float(breakdown.brush_seconds))/brush_n
    if tool_n:
        operation_counts["tool_change"]=operation_counts.get("tool_change",0)+tool_n
        prior=model_average_seconds.get("tool_change",0.0)
        direct=(max(0.0,float(breakdown.tool_seconds))+background_tool_changes*model.switch_cost("tool_change"))/max(1,tool_n)
        model_average_seconds["tool_change"]=max(prior,direct)
    fill_n=max(0,int(fill_meta.get("fill_regions") or 0))+background_fill_actions
    if fill_n:
        operation_counts["fill_action"]=fill_n
        fill_seconds=max(0.0,float(fill_meta.get("fill_contour_and_click_seconds") or 0.0))+background_fill_actions*model.switch_cost("fill")
        model_average_seconds["fill_action"]=fill_seconds/max(1,fill_n)
    verification_n=max(0,int(fill_meta.get("fill_regions") or 0))+background_verifications
    if verification_n:
        operation_counts["verification"]=verification_n
        model_average_seconds["verification"]=model.switch_cost("verification")

    modeled_operation_seconds=sum(max(0,int(operation_counts.get(kind,0) or 0))*max(0.0,float(avg or 0.0))
                                  for kind,avg in model_average_seconds.items())
    return total,{
        "used":True,"model":"stateful ExecutionCostModel + RegionFill batch model",
        "execution_cost_model":"ExecutionCostModel","execution_cost_calibration":"cold override; measured correction applied once",
        "path_count":len(path_rows),"stroke_sequence_paths":len(path_rows),
        "color_changes":palette_n,"brush_changes":brush_n,
        "fill_actions":fill_n,"fill_color_batches":int(fill_meta.get("fill_color_batches") or 0),
        "tool_changes":tool_n,"verification_actions":verification_n,
        "sequence_seconds":round(sequence_seconds,5),"fill_seconds":round(max(0.0,float(fill_meta.get("total_seconds") or 0.0)),5),
        "background_fill_seconds":round(background_seconds,5),"outside_sequence_seconds":round(outside_sequence,5),
        "operation_counts":{str(k):int(v) for k,v in operation_counts.items() if int(v)>0},
        "operation_model_average_seconds":{str(k):round(float(v),7) for k,v in model_average_seconds.items() if float(v)>0},
        "modeled_operation_seconds":round(modeled_operation_seconds,5),
        "breakdown":breakdown.as_dict(),"fill_breakdown":fill_meta,
    }

def _measured_throughput_floor(plan: dict[str, Any], seconds: float) -> tuple[float, int]:
    """Use only genuinely learned Real-Speed history, never fallback PPS guesses."""
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    key = str(options.get("profile_key") or "").lower()
    try:
        from RealSpeedBudget import load_profile
        stored = load_profile(key)
        if not stored or int(stored.get("samples") or 0) <= 0:
            return seconds, 0
        pps = float(stored.get("paths_per_second") or 0.0)
        if pps <= 0:
            return seconds, 0
        count = max(0, int(plan.get("count") or 0))
        overhead = max(0.0, float(plan.get("operation_overhead_seconds") or 0.0))
        measured = count / pps + overhead
        return max(seconds, measured), int(stored.get("samples") or 0)
    except Exception:
        return seconds, 0


_OPERATION_ALIASES={
    "dot":("dot","point","stroke","path"),
    "point":("point","dot","stroke","path"),
    "stroke":("stroke","path","drag","mouse_drag"),
    "short_stroke":("short_stroke","stroke","path","drag"),
    "long_stroke":("long_stroke","stroke","path","drag"),
    "outline":("outline","stroke","path","drag"),
    "palette_change":("palette_change","color_change"),
    "color_change":("color_change","palette_change"),
    "tool_change":("tool_change","brush_change"),
    "fill_action":("fill_action","fill","bucket_fill"),
    "verification":("verification","visual_verify"),
}


def _runtime_operation_item(runtime: dict[str,Any], kind: str):
    if not isinstance(runtime,dict):return None
    for key in _OPERATION_ALIASES.get(str(kind),(str(kind),)):
        item=runtime.get(key)
        if isinstance(item,dict):
            try:
                avg=max(0.0,float(item.get("average_seconds") or 0.0))
                if avg<=0:
                    count=max(0,int(item.get("count") or item.get("observations") or 0))
                    total=max(0.0,float(item.get("total_seconds") or 0.0))
                    avg=total/count if count else 0.0
                if avg>0 and math.isfinite(avg):return item,avg
            except Exception:pass
    return None


def _operation_calibration_adjustment(calibration: dict[str,Any], sequence_meta: dict[str,Any] | None) -> dict[str,Any]:
    meta=sequence_meta if isinstance(sequence_meta,dict) else {}
    counts=meta.get("operation_counts") or {}
    model_avg=meta.get("operation_model_average_seconds") or {}
    runtime=calibration.get("operation_runtime") or {}
    total_model=0.0;matched_model=0.0;matched_measured=0.0;matched_ops=0;sample_weight=0.0
    for kind,count_value in counts.items():
        try:
            count=max(0,int(count_value or 0));modeled=max(0.0,float(model_avg.get(str(kind),0.0) or 0.0))
        except Exception:continue
        if count<=0 or modeled<=0:continue
        modeled_seconds=modeled*count;total_model+=modeled_seconds
        found=_runtime_operation_item(runtime,str(kind))
        if found is None:continue
        item,measured_avg=found
        matched_model+=modeled_seconds;matched_measured+=measured_avg*count;matched_ops+=count
        try:op_samples=max(1,int(item.get("samples") or calibration.get("samples") or 1))
        except Exception:op_samples=1
        sample_weight+=modeled_seconds*op_samples
    if matched_model<=0 or total_model<=0:
        return {"used":False,"coverage_percent":0.0,"matched_operations":0,"raw_ratio":1.0,"applied_ratio":1.0,"confidence":0.0,"runtime_source":calibration.get("operation_runtime_source","none")}
    coverage=max(0.0,min(1.0,matched_model/total_model))
    avg_samples=sample_weight/matched_model
    sample_evidence=1.0-math.exp(-avg_samples/4.0)
    try:mape=max(0.0,min(2.0,float(calibration.get("mape") if calibration.get("mape") is not None else .12)))
    except Exception:mape=.12
    error_quality=max(.20,1.0-min(1.5,mape)/1.5)
    confidence=max(0.0,min(.94,coverage*sample_evidence*error_quality))
    raw_ratio=max(.45,min(2.50,matched_measured/matched_model))
    applied=1.0+confidence*(raw_ratio-1.0)
    return {
        "used":True,"coverage_percent":round(coverage*100.0,2),"matched_operations":int(matched_ops),
        "modeled_matched_seconds":round(matched_model,5),"measured_matched_seconds":round(matched_measured,5),
        "average_operation_samples":round(avg_samples,2),"raw_ratio":round(raw_ratio,5),
        "applied_ratio":round(max(.55,min(2.20,applied)),5),"confidence":round(confidence,5),
        "runtime_source":calibration.get("operation_runtime_source","unknown"),
    }


def _apply_measured_correction(plan: dict[str, Any], seconds: float, sequence_meta: dict[str,Any] | None=None) -> tuple[float, str, int, float, float | None, dict[str,Any]]:
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    base, speed_samples = _measured_throughput_floor(plan, seconds)
    cal = _local_calibration(options)
    operation_meta=_operation_calibration_adjustment(cal,sequence_meta)
    operation_ratio=max(.55,min(2.20,float(operation_meta.get("applied_ratio") or 1.0)))
    operation_confidence=max(0.0,min(.94,float(operation_meta.get("confidence") or 0.0)))
    base*=operation_ratio
    samples = int(cal.get("samples") or 0)
    ratio = max(.55,min(4.0,float(cal.get("ratio") or 1.0)))
    if samples <= 0:
        global_target=1.12 if speed_samples else 1.28
        source=(f"measured path throughput + cold-start guard ({speed_samples} sample{'s' if speed_samples != 1 else ''})"
                if speed_samples else "final operation sequence + conservative cold-start guard; waiting for 3 completed draws")
    elif samples == 1:
        global_target=max(1.18,ratio);source="final operation sequence + learning calibration (1/3 completed draws)"
    elif samples == 2:
        global_target=max(1.08,ratio);source="final operation sequence + learning calibration (2/3 completed draws)"
    else:
        global_target=ratio;source=f"final operation sequence + measured local calibration ({samples} completed draws)"
    # The completed-draw ratio contains the same operation timing error. Once
    # typed operations explain that error, only blend the residual ratio so the
    # evidence is not counted twice.
    residual_target=max(.60,min(2.20,global_target/max(.55,operation_ratio)))
    residual_weight=max(.06,1.0-operation_confidence)
    residual_factor=1.0+residual_weight*(residual_target-1.0)
    residual_factor=max(.70,min(1.80,residual_factor))
    corrected=base*residual_factor
    effective_ratio=operation_ratio*residual_factor
    if operation_meta.get("used"):
        source += f" + operation EMA ({operation_meta.get('coverage_percent',0):.0f}% model coverage)"
    mape = cal.get("mape")
    try:mape = float(mape) if mape is not None else None
    except Exception:mape = None
    return max(0.0, corrected), source, samples, effective_ratio, mape, operation_meta


def _range_for(seconds: float, *, projection: bool, samples: int, mape: float | None, operation_confidence: float=0.0) -> tuple[float, float, str]:
    seconds=max(0.0,float(seconds or 0.0));op_conf=max(0.0,min(.94,float(operation_confidence or 0.0)))
    if samples >= 5:
        spread=max(.035,min(.22,float(mape if mape is not None else .10)))*(1.0-.28*op_conf)
        spread=max(.035,spread)
        return max(0.0,seconds*(1-spread)), seconds*(1+spread), "high"
    if samples >= 3:
        spread=max(.055,min(.25,float(mape if mape is not None else .12)))*(1.0-.22*op_conf)
        spread=max(.05,spread)
        return max(0.0,seconds*(1-spread)),seconds*(1+spread),"measured"
    if samples == 2:
        spread=.13*(1.0-.12*op_conf);return seconds*(1-spread*.62),seconds*(1+spread),"learning"
    if samples == 1:
        spread=.18*(1.0-.08*op_conf);return seconds*(1-spread*.55),seconds*(1+spread),"learning"
    return seconds*(.88 if not projection else .82), seconds*(1.28 if not projection else 1.38), "cold-start"


def estimate_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Return visible estimate metadata from the plan that will actually execute."""
    options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
    path_stats = plan.get("path_stats") if isinstance(plan.get("path_stats"), dict) else {}
    legacy_seconds=max(0.0,float(plan.get("estimate") or 0.0))
    sequence_seconds,sequence_meta=_sequence_operation_estimate(plan)
    raw_preview_seconds=sequence_seconds if sequence_meta.get("used") and sequence_seconds>0 else legacy_seconds
    preview_area = _area(plan.get("preview_area") or options.get("_preview_area") or plan.get("plan_area"))
    target_area = _area(plan.get("target_area") or options.get("_target_area") or plan.get("plan_area") or preview_area)

    is_projection = bool(preview_area and target_area and tuple(preview_area) != tuple(target_area) and not plan.get("full_detail_preview"))
    reason = "native/full-detail final execution sequence" if sequence_meta.get("used") else "native/full-detail legacy operation plan"
    multiplier = 1.0;projected_raw = raw_preview_seconds
    if is_projection:
        p_area = max(1, preview_area[0] * preview_area[1]);t_area = max(1, target_area[0] * target_area[1])
        area_ratio = max(1.0, t_area / p_area);exponent, projection_reason = _projection_exponent(options, path_stats)
        multiplier = min(24.0, max(1.0, area_ratio ** exponent));projected_raw = raw_preview_seconds * multiplier
        projected_raw += 6.0 + min(60.0, float(len(plan.get("groups") or ())) * .22)
        reason=f"{projection_reason}; source={'final sequence' if sequence_meta.get('used') else 'legacy estimate'}"

    corrected, source, samples, ratio, mape, operation_calibration = _apply_measured_correction(plan, projected_raw, sequence_meta)
    low, high, confidence = _range_for(corrected, projection=is_projection, samples=samples, mape=mape,
                                       operation_confidence=float(operation_calibration.get("confidence") or 0.0))
    out=DrawTimeEstimate(
        preview_seconds=raw_preview_seconds,projected_seconds=corrected,low_seconds=low,high_seconds=high,
        confidence=confidence,multiplier=multiplier,is_projection=is_projection,reason=reason,
        estimate_source=source,measured_samples=samples,calibration_ratio=ratio,
    ).as_dict()
    out["sequence_model_used"]=bool(sequence_meta.get("used"))
    out["sequence_operation_model"]=sequence_meta
    out["operation_calibration"]=operation_calibration
    out["operation_calibration_coverage_percent"]=float(operation_calibration.get("coverage_percent") or 0.0)
    out["operation_calibration_ratio"]=float(operation_calibration.get("applied_ratio") or 1.0)
    out["operation_calibration_confidence"]=float(operation_calibration.get("confidence") or 0.0)
    out["legacy_planner_seconds"]=round(legacy_seconds,3)
    if sequence_meta.get("used"):
        out["legacy_vs_sequence_delta_seconds"]=round(raw_preview_seconds-legacy_seconds,3)
    return out


def attach_draw_time_estimate(plan: dict[str, Any]) -> dict[str, Any]:
    meta = estimate_from_plan(plan)
    plan["draw_time_estimate"] = meta
    return meta


def record_completed_draw(plan: dict[str, Any], actual_seconds: float, *, completed_paths: int = 0) -> dict[str, Any]:
    """Teach the local estimate from one clean, completed real draw."""
    try:
        from DrawTimeCalibration import record_sample
        options = plan.get("options") if isinstance(plan.get("options"), dict) else {}
        gate=timing_sample_gate(options, completed_paths=completed_paths, planned_paths=int(plan.get("count") or 0))
        if not gate.get("allowed"):
            return {"recorded": False, "reason": gate.get("reason", "timing sample rejected"), "sample_gate": gate}
        predicted_meta=plan.get("draw_time_estimate") or estimate_from_plan(plan)
        predicted = max(0.0, float(predicted_meta.get("preview_seconds") or plan.get("raw_execution_estimate_seconds") or plan.get("estimate") or 0.0))
        fill_actions = len(options.get("fill_regions") or ()) + (1 if (options.get("background_fill_plan") or {}).get("enabled") else 0)
        operation_counts=(options.get('adaptive_deadline_meta') or {}).get('operation_counts') or {}
        operation_runtime=options.get('runtime_operation_timing') or {}
        result=record_sample(options, predicted, actual_seconds, completed_paths=completed_paths, fill_actions=fill_actions,
                             operation_counts=operation_counts, operation_runtime=operation_runtime)
        if isinstance(result,dict):
            result["sample_gate"]=gate
        return result
    except Exception as error:
        return {"recorded": False, "reason": str(error)}


def status_line(plan: dict[str, Any]) -> str:
    meta = plan.get("draw_time_estimate") or estimate_from_plan(plan)
    prefix = "Estimated final draw time" if meta.get("is_projection") else "Estimated draw time"
    label = meta.get("projected_label") or format_duration(meta.get("projected_seconds", 0))
    source = str(meta.get("estimate_source") or "")
    if meta.get("is_projection"):
        return f"{prefix}: about {label} ({meta.get('range_label')}, {meta.get('confidence')} confidence; {source})."
    if int(meta.get("measured_samples") or 0) > 0:
        return f"{prefix}: about {label} ({meta.get('range_label')}, {meta.get('confidence')} confidence; {source})."
    return f"{prefix}: about {label} ({source})."
