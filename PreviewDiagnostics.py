"""Preview diagnostics for Image Draw Bot Step 10.

This module is intentionally read-only with respect to the renderer.  It builds
truthful diagnostic buffers from existing plan data and never changes palette
selection, path ordering, mouse input, or deadline behaviour.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable
from contextlib import closing
import math
import numpy as np
from PIL import Image, ImageDraw

from AccuracyEvaluator import normalize_source, _srgb_to_oklab
from RuntimePaths import is_finite_number


def _clamp_rgb(value) -> tuple[int, int, int]:
    try:
        r, g, b = value[:3]
        return tuple(max(0, min(255, int(round(v)))) for v in (r, g, b))
    except (TypeError, ValueError, OverflowError, IndexError):
        return (255, 255, 255)


def _draw_clipped_segment(draw, size, segment, color):
    """Clip raster samples, retaining the original line's slope and error phase.

    Bresenham's rounded minor coordinate can be evaluated at any major-axis
    index, so even enormous off-canvas endpoints require at most one canvas
    dimension of work. Independently clamping endpoints changes the raster.
    """
    w,h=size;x0,y0,x1,y1=segment
    if 0<=x0<w and 0<=x1<w and 0<=y0<h and 0<=y1<h:
        draw.line(segment,fill=color,width=1);return
    dx=abs(x1-x0);dy=abs(y1-y0);sx=1 if x1>=x0 else -1;sy=1 if y1>=y0 else -1
    if dx==0:
        low=max(0,min(y0,y1));high=min(h-1,max(y0,y1))
        if 0<=x0<w and low<=high:draw.line((x0,low,x0,high),fill=color)
        return
    if dy==0:
        low=max(0,min(x0,x1));high=min(w-1,max(x0,x1))
        if 0<=y0<h and low<=high:draw.line((low,y0,high,y0),fill=color)
        return
    points=[]
    if dx>=dy:
        lo=max(0,-x0 if sx>0 else x0-w+1);hi=min(dx,w-1-x0 if sx>0 else x0)
        for step in range(lo,hi+1):
            y=y0+sy*((2*step*dy+dx)//(2*dx))
            if 0<=y<h:points.append((x0+sx*step,y))
    else:
        lo=max(0,-y0 if sy>0 else y0-h+1);hi=min(dy,h-1-y0 if sy>0 else y0)
        for step in range(lo,hi+1):
            x=x0+sx*((2*step*dx+dy)//(2*dy))
            if 0<=x<w:points.append((x,y0+sy*step))
    if points:draw.point(points,fill=color)


def _render_quantized_target(source_size: tuple[int, int], groups, palette_rgb,
                            *, fill_regions=(), background_fill_plan=None,
                            color_order=None, explicit_target: Image.Image | None = None,
                            cancelled: Callable[[], bool] = lambda: False, _owned=None) -> Image.Image:
    """Render the palette/quantized target before physical brush simulation.

    The target uses one source pixel of width for planned raster runs.  It is
    therefore deliberately different from the simulated-final preview, which
    models brush width, execution paths, fills and later geometry decisions.
    """
    if cancelled():raise InterruptedError()
    w, h = max(1, int(source_size[0])), max(1, int(source_size[1]))
    if isinstance(explicit_target, Image.Image):
        rgb=normalize_source(explicit_target,explicit_target.size);_owned.append(rgb)
        result=rgb.resize((w,h),Image.Resampling.NEAREST);_owned.append(result)
        if cancelled():raise InterruptedError()
        return result

    palette = tuple(_clamp_rgb(c) for c in (palette_rgb if palette_rgb is not None else ()))
    bg = (255, 255, 255)
    meta = background_fill_plan or {}
    try:
        if meta.get('enabled') and meta.get('color_index') is not None:
            idx = int(meta.get('color_index'))
            if 0 <= idx < len(palette):
                bg = palette[idx]
    except (TypeError, ValueError):
        pass
    target = Image.new('RGB', (w, h), bg)
    _owned.append(target)
    draw = ImageDraw.Draw(target)

    # Accepted fills belong to the plan target even when their corresponding
    # scanline strokes were removed for execution-speed reasons.
    for region in fill_regions or ():
        if cancelled():
            raise InterruptedError()
        try:
            idx = int(region.get('color_index', -1))
            if not (0 <= idx < len(palette)):
                continue
            color = palette[idx]
            spans = region.get('row_spans') or ()
            if spans:
                for n,raw in enumerate(spans):
                    if n%512==0 and cancelled():raise InterruptedError()
                    y, x0, x1 = map(int, raw)
                    if 0 <= y < h and x0 <= x1 and x0 < w and x1 >= 0:
                        draw.line((max(0, x0), y, min(w - 1, x1), y), fill=color, width=1)
            else:
                x0, y0, x1, y1 = map(int, region.get('bbox'))
                if x0<=x1 and y0<=y1 and x0<w and y0<h and x1>=0 and y1>=0:
                    draw.rectangle((max(0, x0), max(0, y0), min(w - 1, x1), min(h - 1, y1)), fill=color)
        except (TypeError, ValueError, OverflowError, KeyError, IndexError):
            continue

    if color_order is None:
        order = range(len(groups or ()))
    else:
        seen = set()
        order = []
        for raw in color_order:
            try: idx = int(raw)
            except (TypeError, ValueError): continue
            if 0 <= idx < len(groups or ()) and idx not in seen:
                order.append(idx); seen.add(idx)
        order.extend(i for i in range(len(groups or ())) if i not in seen)

    for idx in order:
        if cancelled():
            raise InterruptedError()
        if idx >= len(palette):
            continue
        color = palette[idx]
        try:
            strokes = groups[idx]
        except Exception:
            continue
        for n, stroke in enumerate(strokes or ()):
            if n % 1024 == 0 and cancelled():
                raise InterruptedError()
            try:
                x0, y0, x1, y1 = map(int, stroke[:4])
            except (TypeError, ValueError, OverflowError, IndexError):
                continue
            _draw_clipped_segment(draw,(w,h),(x0,y0,x1,y1),color)
    if cancelled():raise InterruptedError()
    return target


def render_quantized_target(source_size,groups,palette_rgb,*,fill_regions=(),
                            background_fill_plan=None,color_order=None,explicit_target=None,
                            cancelled=lambda:False):
    arguments=locals().copy();owned=[];result=None
    try:
        result=_render_quantized_target(**arguments,_owned=owned)
        return result
    finally:
        for image in owned:
            if image is not result:image.close()


def _heat_ramp(values: np.ndarray) -> np.ndarray:
    """Continuous dark -> green -> amber -> red -> white diagnostic ramp."""
    x = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    out = np.zeros((*x.shape, 3), dtype=np.float32)
    # Piecewise stops. The heatmap is diagnostic only; metric values are kept in
    # metadata so users never have to infer numeric ΔE from colour alone.
    stops = (
        (0.00, (8, 15, 24)),
        (0.20, (34, 118, 85)),
        (0.45, (224, 177, 55)),
        (0.72, (228, 78, 65)),
        (1.00, (250, 245, 245)),
    )
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        mask = (x >= a) & (x <= b if b >= 1.0 else x < b)
        if not np.any(mask):
            continue
        t = np.clip((x[mask] - a) / max(1e-9, b - a), 0.0, 1.0)[:, None]
        va=np.asarray(ca,dtype=np.float32);vb=np.asarray(cb,dtype=np.float32)
        out[mask] = va + (vb - va) * t
    return np.clip(out, 0, 255).astype(np.uint8)


def render_delta_e_heatmap(source: Image.Image, simulated_final: Image.Image, *,
                           normalized_source: Image.Image | None = None,
                           full_error: float = 0.45,
                           cancelled: Callable[[], bool] = lambda: False,
                           gpu_mode: str = "Auto") -> tuple[Image.Image, dict[str, Any]]:
    """Return an OKLab ΔE-style heatmap plus numeric distribution metadata."""
    if cancelled():
        raise InterruptedError()
    if not is_finite_number(full_error) or full_error<=0:
        raise ValueError('Heatmap full-error scale must be finite and positive.')
    size = tuple(map(int, simulated_final.size))
    src_input=normalized_source if isinstance(normalized_source,Image.Image) and normalized_source.size==size else source
    with closing(normalize_source(src_input,size)) as src_img,closing(normalize_source(simulated_final,size)) as dst_img:
        src = np.asarray(src_img, dtype=np.float32) / 255.0
        dst = np.asarray(dst_img, dtype=np.float32) / 255.0
    try:
        from UniversalGpuAcceleration import perceptual_pair
        _src_lab, _dst_lab, delta, route = perceptual_pair(src, dst, gpu_mode=gpu_mode, cancelled=cancelled)
    except InterruptedError:
        raise
    except Exception as exc:
        src_lab = _srgb_to_oklab(src); dst_lab = _srgb_to_oklab(dst)
        delta = np.linalg.norm(src_lab - dst_lab, axis=2).astype(np.float32, copy=False)
        route = {'backend_id':'cpu:numpy','backend':'CPU/NumPy','fallback_reason':f'{type(exc).__name__}: {exc}'}
    if cancelled():
        raise InterruptedError()
    scaled = np.clip(delta / float(full_error), 0.0, 1.0)
    heat = Image.fromarray(_heat_ramp(scaled), 'RGB')
    if delta.size:
        mean=float(np.mean(delta,dtype=np.float64)); median=float(np.median(delta)); p95=float(np.percentile(delta,95)); maximum=float(np.max(delta))
        severe=float(np.mean(delta >= 0.20,dtype=np.float64)*100.0)
    else:
        mean=median=p95=maximum=severe=0.0
    return heat, {
        'space':'OKLab','metric':'euclidean OKLab distance','mean_delta_e_oklab':round(mean,5),
        'median_delta_e_oklab':round(median,5),'p95_delta_e_oklab':round(p95,5),
        'max_delta_e_oklab':round(maximum,5),'severe_error_pixels_percent':round(severe,2),
        'heatmap_full_error':float(full_error),'comparison_size':size,
        'acceleration_route':dict(route),
    }


def _state_label(item: Any, default='Unavailable') -> str:
    if not isinstance(item, dict):
        return default
    value=str(item.get('state') or '').strip().lower()
    return {'verified':'Verified','calibrated':'Calibrated','estimated':'Estimated','unavailable':'Unavailable'}.get(value, default)


def build_preview_diagnostics(options: dict, *, accuracy: dict | None = None,
                              delta_e: dict | None = None, draw_time: dict | None = None,
                              path_count: int = 0, source_count: int = 0,
                              performance_profile: dict | None = None) -> dict[str, Any]:
    """Build compact metadata shown below the preview and in benchmarks."""
    options=dict(options) if isinstance(options,dict) else {}
    calibration = options.get('calibration_state') if isinstance(options, dict) else {}
    calibration = calibration if isinstance(calibration, dict) else {}
    try:
        from CalibrationState import timing_state
        timing = timing_state(options)
    except Exception:
        timing = {'state':'estimated','samples':0,'ratio':1.0}
    palette = calibration.get('palette') or {}
    tools = calibration.get('tools') or {}
    exact = calibration.get('exact_color') or {}
    accuracy = accuracy or options.get('adaptive_accuracy_meta') or {}
    accuracy=accuracy if isinstance(accuracy,dict) else {}
    draw_time = draw_time if isinstance(draw_time,dict) else {}
    perf = performance_profile if isinstance(performance_profile,dict) else {}
    from PerformanceProfiler import dominant_phase
    dominant,_=dominant_phase({'timings':perf.get('timings') if isinstance(perf.get('timings'),dict) else {}})
    projected=draw_time.get('projected_seconds')
    projected=float(projected) if is_finite_number(projected) and projected>=0 else None
    tuner = options.get('auto_tuner_meta') if isinstance(options,dict) else {}
    tuner = tuner if isinstance(tuner,dict) else {}
    acceptance = options.get('auto_tuner_acceptance_meta') if isinstance(options,dict) else {}
    acceptance = acceptance if isinstance(acceptance,dict) else {}
    feedback = tuner.get('feedback_learning') if isinstance(tuner.get('feedback_learning'),dict) else {}
    post_draw = options.get('post_draw_accuracy_meta') if isinstance(options,dict) else {}
    post_draw = post_draw if isinstance(post_draw,dict) else {}
    correction = options.get('post_draw_correction_meta') if isinstance(options,dict) else {}
    correction = correction if isinstance(correction,dict) else {}
    try:
        from CorrectionHistory import load_correction_history
        correction_history = load_correction_history(options, limit=3)
        options['correction_history_meta']=correction_history
    except Exception:
        correction_history = {}
    try:
        from CorrectionReviewRecovery import build_correction_review_state
        correction_review = build_correction_review_state(options, can_snapshot=False, strict_safety_ready=False, full_start_unlocked=False)
    except Exception:
        correction_review = {}
    stability = options.get('release_stability_meta') if isinstance(options, dict) else {}
    stability = stability if isinstance(stability, dict) else {}
    detail_zoom = options.get('detail_zoom_meta') if isinstance(options, dict) else {}
    detail_zoom = detail_zoom if isinstance(detail_zoom, dict) else {}
    quick_sketch = options.get('quick_sketch_meta') if isinstance(options, dict) else {}
    quick_sketch = quick_sketch if isinstance(quick_sketch, dict) else {}
    hybrid = options.get('hybrid_renderer_meta') if isinstance(options, dict) else {}
    hybrid = hybrid if isinstance(hybrid, dict) else {}
    return {
        'calibration':{
            'profile_key':str(options.get('profile_key') or calibration.get('profile_key') or ''),
            'palette':_state_label(palette), 'tools':_state_label(tools),
            'exact_color':_state_label(exact), 'timing':_state_label(timing,'Estimated'),
            'timing_samples':int(timing.get('samples',0) or 0),
        },
        'accuracy':{k:accuracy.get(k) for k in (
            'visual_accuracy_percent','source_pixel_accuracy_percent','perceptual_color_accuracy_percent',
            'luminance_accuracy_percent','hue_accuracy_percent','edge_accuracy_percent','coverage_percent',
            'plan_execution_accuracy_percent') if accuracy.get(k) is not None},
        'real_result':{k:post_draw.get(k) for k in (
            'available','trusted','feedback_trust','scoring_state','confidence_percent','visual_accuracy_percent',
            'source_pixel_accuracy_percent','perceptual_color_accuracy_percent','actual_coverage_percent',
            'actual_vs_simulated_visual_percent','unexpected_ink_percent','blank_canvas','visual_gate_passed',
            'deadline_safe','summary') if post_draw.get(k) is not None},
        'post_draw_correction':{k:correction.get(k) for k in (
            'enabled','safe','reason','correction_paths','selected_correction_pixels','missing_pixels',
            'wrong_color_pixels','corrected_colors','estimated_seconds','executed_paths','executed_colors',
            'stopped_early','post_correction_visual_accuracy_percent','post_correction_actual_coverage_percent',
            'post_correction_trust','post_correction_confidence_percent','stores_image_data')
            if correction.get(k) is not None},
        'correction_review':dict(correction_review or {}),
        'correction_history':dict(correction_history or {}),
        'delta_e':dict(delta_e or {}),
        'performance':{
            'projected_draw_seconds':None if projected is None else round(projected,3),
            'draw_range':draw_time.get('range_label'), 'confidence':draw_time.get('confidence'),
            'estimate_source':draw_time.get('estimate_source'), 'measured_samples':int(draw_time.get('measured_samples',0) or 0),
            'planned_paths':int(path_count or 0),'source_strokes':int(source_count or 0),
            'planning_seconds':round(float(perf.get('total_planning',0) or 0),4) if isinstance(perf,dict) else 0.0,
            'slowest_planning_phase':dominant,
        },
        'auto_tuner':{
            'active':bool(tuner.get('active')), 'strategy':tuner.get('selected_strategy'),
            'renderer':tuner.get('renderer'), 'draw_quality':tuner.get('draw_quality'),
            'adaptive_detail':tuner.get('adaptive_detail'), 'planning_resolution':tuner.get('planning_resolution'),
            'speed_strategy':tuner.get('speed_strategy'), 'color_ceiling':tuner.get('color_ceiling'),
            'status':acceptance.get('status'), 'accepted':acceptance.get('accepted'),
            'visual_gate_percent':(acceptance.get('gates') or tuner.get('acceptance_gates') or {}).get('visual_accuracy_min_percent'),
            'deadline_gate_seconds':(acceptance.get('gates') or tuner.get('acceptance_gates') or {}).get('usable_deadline_seconds'),
            'schedule_headroom_seconds':acceptance.get('schedule_headroom_seconds'),
            'replan_attempt':acceptance.get('replan_attempt',tuner.get('replan_attempt',0)),
            'feedback_state':feedback.get('state'), 'feedback_active':bool(feedback.get('active')),
            'feedback_action':feedback.get('action'), 'feedback_samples':int(feedback.get('samples',0) or 0),
            'feedback_time_ratio':feedback.get('time_ratio_ema'),
            'feedback_deadline_pass_rate':feedback.get('deadline_pass_rate'),
            'feedback_acceptance_pass_rate':feedback.get('acceptance_pass_rate'),
            'feedback_result_visual_ema':feedback.get('result_visual_ema'),
        } if tuner.get('active') else {},
        'detail_zoom':{k:detail_zoom.get(k) for k in (
            'enabled','requested','factor','analysis_zoom','detail_paths_added','detail_pixels_added',
            'candidate_cells','accepted_cells','smallest_detail_brush_px','deadline_aware','path_cap',
            'target_app_zoomed','target_zoom_policy','reason') if detail_zoom.get(k) is not None},
        'hybrid_renderer':{k:hybrid.get(k) for k in (
            'enabled','engine','step','version','requested_mode','resolved_mode','base_renderer',
            'passes','deadline_seconds','analysis','semantic_ai_used','ocr_used','native_input_changed','safety_policy')
            if hybrid.get(k) is not None},
        'quick_sketch':{k:quick_sketch.get(k) for k in (
            'enabled','engine','style','fill_preference','fill_tool_available','color_cap',
            'active_colors_before','active_colors_after','fill_regions','fill_pixels','fill_coverage_percent',
            'fallback_scanline_regions','visible_contour_regions','visible_contour_segments',
            'micro_strokes_pruned','filled_source_runs_removed','source_runs','final_runs',
            'stroke_run_reduction_percent','deadline_aware','detail_zoom_handoff','safety_policy','reason')
            if quick_sketch.get(k) is not None},
        'release_stability': dict(stability or {}),
    }


def format_preview_diagnostics(meta: dict[str, Any]) -> str:
    if not isinstance(meta, dict):
        return 'Preview diagnostics unavailable.'
    cal=meta.get('calibration') or {};acc=meta.get('accuracy') or {};real=meta.get('real_result') or {};corr=meta.get('post_draw_correction') or {};review=meta.get('correction_review') or {};history=meta.get('correction_history') or {};de=meta.get('delta_e') or {};perf=meta.get('performance') or {};tuner=meta.get('auto_tuner') or {};detail_zoom=meta.get('detail_zoom') or {};quick_sketch=meta.get('quick_sketch') or {};stability=meta.get('release_stability') or {}
    cal_text=(f"Calibration: palette {cal.get('palette','Unavailable')} · tools {cal.get('tools','Unavailable')} · "
              f"exact {cal.get('exact_color','Unavailable')} · timing {cal.get('timing','Estimated')}"
              + (f" ({int(cal.get('timing_samples',0))} samples)" if int(cal.get('timing_samples',0) or 0) else ''))
    metric=[]
    for key,label in (('visual_accuracy_percent','Visual'),('perceptual_color_accuracy_percent','Color'),('luminance_accuracy_percent','Luma'),('edge_accuracy_percent','Edges'),('coverage_percent','Coverage'),('plan_execution_accuracy_percent','Plan')):
        if acc.get(key) is not None:
            metric.append(f"{label} {float(acc[key]):.1f}%")
    if de.get('mean_delta_e_oklab') is not None:
        metric.append(f"OKLab ΔE mean {float(de['mean_delta_e_oklab']):.3f}")
        metric.append(f"p95 {float(de.get('p95_delta_e_oklab',0)):.3f}")
    perf_text=''
    if perf.get('projected_draw_seconds'):
        try:
            from DrawTimeEstimate import format_duration
            perf_text=(f"Estimated real draw: {format_duration(float(perf['projected_draw_seconds']))}"
                       f" · {perf.get('confidence') or 'unknown'} confidence"
                       f" · {int(perf.get('planned_paths',0)):,} paths")
        except Exception:
            perf_text=f"Estimated draw: {float(perf['projected_draw_seconds']):.1f}s"
    lines=[cal_text]
    if tuner.get('active'):
        tune_bits=[str(tuner.get('status') or 'PENDING'), str(tuner.get('strategy') or 'Auto'),
                   str(tuner.get('draw_quality') or ''), str(tuner.get('speed_strategy') or '')]
        if tuner.get('color_ceiling') is not None: tune_bits.append(f"colors ≤{int(tuner.get('color_ceiling') or 0)}")
        if tuner.get('visual_gate_percent') is not None: tune_bits.append(f"visual gate ≥{float(tuner.get('visual_gate_percent')):.0f}%")
        if int(tuner.get('replan_attempt',0) or 0): tune_bits.append(f"rescue pass {int(tuner.get('replan_attempt'))}")
        feedback_samples=int(tuner.get('feedback_samples',0) or 0)
        if feedback_samples:
            feedback_text=f"feedback {tuner.get('feedback_state') or 'learning'} {feedback_samples} draws"
            if tuner.get('feedback_time_ratio') is not None:
                feedback_text+=f" ×{float(tuner.get('feedback_time_ratio')):.2f}"
            if tuner.get('feedback_action') not in (None,'','none'):
                feedback_text+=f" → {tuner.get('feedback_action')}"
            tune_bits.append(feedback_text)
        lines.append('Auto tuner: ' + ' · '.join(x for x in tune_bits if x))
    if real.get('available'):
        rr=[f"trust {real.get('feedback_trust','none')}"]
        if real.get('confidence_percent') is not None: rr.append(f"confidence {float(real.get('confidence_percent')):.0f}%")
        if real.get('visual_accuracy_percent') is not None: rr.append(f"actual Visual {float(real.get('visual_accuracy_percent')):.1f}%")
        if real.get('actual_coverage_percent') is not None: rr.append(f"actual Coverage {float(real.get('actual_coverage_percent')):.1f}%")
        if real.get('actual_vs_simulated_visual_percent') is not None: rr.append(f"actual vs simulated {float(real.get('actual_vs_simulated_visual_percent')):.1f}%")
        lines.append('Real result: ' + ' · '.join(rr))
    if corr:
        if corr.get('enabled'):
            bits=[f"{int(corr.get('executed_paths',corr.get('correction_paths',0)) or 0)}/{int(corr.get('correction_paths',0) or 0)} paths"]
            if corr.get('selected_correction_pixels') is not None: bits.append(f"{int(corr.get('selected_correction_pixels',0) or 0)} pixels")
            if corr.get('corrected_colors') is not None: bits.append(f"{int(corr.get('corrected_colors',0) or 0)} colors")
            if corr.get('post_correction_visual_accuracy_percent') is not None: bits.append(f"post Visual {float(corr.get('post_correction_visual_accuracy_percent')):.1f}%")
            if corr.get('stopped_early'): bits.append('stopped by deadline reserve')
            lines.append('Correction pass: ' + ' · '.join(bits))
        elif corr.get('reason'):
            lines.append('Correction pass: skipped · ' + str(corr.get('reason')))
    if review:
        try:
            title=str(review.get('title') or 'Review')
            action_bits=[]
            actions=review.get('actions') if isinstance(review.get('actions'),dict) else {}
            for key in ('retry_correction_only','rerun_result_verification','retry_full_drawing'):
                item=actions.get(key) if isinstance(actions.get(key),dict) else {}
                if item.get('enabled'):
                    action_bits.append(str(item.get('label') or key))
            suffix=(' · actions: '+', '.join(action_bits)) if action_bits else ''
            lines.append('Correction Review: '+title+suffix)
        except Exception:
            pass
    if history:
        try:
            summary=history.get('summary') if isinstance(history.get('summary'),dict) else {}
            if int(summary.get('entry_count',0) or 0):
                bits=[f"{int(summary.get('entry_count',0) or 0)} saved"]
                if summary.get('average_visual_delta') is not None:
                    bits.append(f"recent Visual {float(summary.get('average_visual_delta')):+.1f} pp")
                if summary.get('latest_state'):
                    bits.append(str(summary.get('latest_state')))
                lines.append('Correction History: '+' · '.join(bits))
        except Exception:
            pass
    if detail_zoom:
        try:
            if detail_zoom.get('enabled'):
                lines.append(
                    'Detail zoom: ' + str(detail_zoom.get('analysis_zoom') or f"{int(detail_zoom.get('factor',1) or 1)}x") +
                    f" · {int(detail_zoom.get('detail_paths_added',0) or 0)} paths" +
                    f" · {int(detail_zoom.get('detail_pixels_added',0) or 0)} pixels" +
                    f" · brush {int(detail_zoom.get('smallest_detail_brush_px',1) or 1)}px" +
                    (' · deadline-aware' if detail_zoom.get('deadline_aware') else '') +
                    ' · internal source zoom only')
            elif detail_zoom.get('requested') not in (None,'Off') and detail_zoom.get('reason'):
                lines.append('Detail zoom: skipped · ' + str(detail_zoom.get('reason')))
        except Exception:
            pass
    if quick_sketch:
        try:
            if quick_sketch.get('enabled'):
                bits=[str(quick_sketch.get('style') or 'Balanced')]
                after=quick_sketch.get('active_colors_after'); cap=quick_sketch.get('color_cap')
                if after is not None or cap is not None:
                    bits.append(f"{int(after or 0)}/{int(cap or 0)} colors")
                if quick_sketch.get('fill_tool_available'):
                    bits.append(f"{int(quick_sketch.get('fill_regions',0) or 0)} safe fills")
                    bits.append(f"{float(quick_sketch.get('fill_coverage_percent',0) or 0):.1f}% fill coverage")
                else:
                    bits.append('Fill unavailable → connected scanline fallback')
                bits.append(f"{int(quick_sketch.get('visible_contour_segments',0) or 0)} contour segments")
                fallback=int(quick_sketch.get('fallback_scanline_regions',0) or 0)
                if fallback:
                    bits.append(f"{fallback} scanline fallbacks")
                reduction=float(quick_sketch.get('stroke_run_reduction_percent',0) or 0)
                if reduction > 0:
                    bits.append(f"{reduction:.1f}% run reduction")
                lines.append('Quick Sketch: ' + ' · '.join(bits))
            elif quick_sketch.get('reason'):
                lines.append('Quick Sketch: fallback · ' + str(quick_sketch.get('reason')))
        except Exception:
            pass
    hybrid=meta.get('hybrid_renderer') or {}
    if hybrid.get('enabled'):
        try:
            mode=str(hybrid.get('resolved_mode') or '?')
            passes=hybrid.get('passes') if isinstance(hybrid.get('passes'),list) else []
            line='Hybrid 3.0: '+mode
            if passes: line+=' · '+' → '.join(str(x) for x in passes[:4])
            lines.append(line)
        except Exception:
            pass
    if stability:
        try:
            bits=[]
            memory=stability.get('preview_memory_limits') if isinstance(stability.get('preview_memory_limits'),dict) else {}
            attempt=stability.get('preview_attempt') if isinstance(stability.get('preview_attempt'),dict) else {}
            timeout=stability.get('preview_timeout') if isinstance(stability.get('preview_timeout'),dict) else {}
            if memory:
                bits.append('preview memory ' + ('reduced' if memory.get('reduced') else 'ok'))
            if attempt:
                bits.append(f"watchdog {float(attempt.get('timeout_seconds',0) or 0):.0f}s")
            if timeout.get('state') and timeout.get('state') != 'ok':
                bits.append(str(timeout.get('state')))
            if bits:
                lines.append('Release stability: ' + ' · '.join(bits))
        except Exception:
            pass
    if metric: lines.append('Accuracy: ' + ' · '.join(metric))
    if perf_text: lines.append(perf_text)
    return '\n'.join(lines)
