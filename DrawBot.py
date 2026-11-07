"""Image Draw Bot: English desktop UI, image preview and cancellable drawing."""
import json
import math
import queue
import threading
import time
import weakref
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from io import BytesIO
from contextlib import ExitStack, closing
from itertools import pairwise, islice
from pathlib import Path
from urllib.parse import urlparse
from WorkerEventQueue import WorkerEventQueue
from WorkerPlanOwnership import WorkerPlanPublication
from UpdateRequest import UpdateRequest
from RuntimeSafetyView import RuntimeSafetyView, capture_runtime_report
from ResultRecheck import ResultRecheckRequest, ResultRecheckResult, recheck_result

from Colors import allColors, enable_dpi_awareness, DATA_DIR, load_calibration, reset_palette, CALIBRATION_FILE, normalize_rgb
from ProfileStorage import profile_palette_file, profile_settings_file, calibration_context_fingerprint
from PixelData import closest_color, prepare_image, build_strokes
from PortraitPlanner import prepare_portrait_image, portrait_strokes
from GpuAcceleration import (ACCELERATION_MODES, VRAM_BUDGETS, GPU_PERFORMANCE_MODES,
                             acceleration_info, benchmark as gpu_benchmark,
                             clear_gpu_cache as gpu_clear_cache,
                             validate_acceleration_mode, validate_vram_budget, validate_gpu_performance)
from FillOptimizer import (detect_background, detect_fill_regions, remove_filled_region_strokes, simplify_background,
                           FILL_ENGINES, validate_background_fill, validate_background_simplification, validate_fill_engine)
from SafeFillMask import (filter_fill_regions_by_source_mask, filter_fill_regions_by_runtime_mask,
                          source_fill_margin_px)
from ColorGrouping import COLOR_GROUPING_MODES, group_palette_strokes, validate_color_grouping
from AdvancedColor import (COLOR_RENDERING_MODES, COLOR_LAYER_MODES, CUSTOM_COLOR_WORKFLOWS,
                           build_color_strokes, validate_color_rendering, validate_color_layers,
                           validate_custom_color_workflow)
from ColorFidelity import COLOR_FIDELITY_MODES, validate_color_fidelity
from SmartTools import TOOL_STRATEGIES, choose_paint_tool, validate_tool_strategy
from Precision import CanvasTransform, precision_path, precision_path_count, validate_precision
from HumanMode import HUMAN_MODES, HumanCadence, human_overhead_seconds, humanize_strokes, stable_seed, validate_human_mode
from SpeedOptimizer import (SPEED_PROFILES, base_delay as speed_base_delay, estimated_motion_seconds,
                            normalize_speed, optimize_strokes, phase_delay, profile as speed_profile)
from StrokeDelivery import resolve_stroke_delivery, interpolation_step, brush_switch_delays
from SkribblFastRenderer import optimize_skribbl_groups
from GarticPhoneFastRenderer import optimize_gartic_phone_groups, build_gartic_execution_paths
from GarticEngineV2 import choose_runtime_profile
from ContinuousPaths import (SMART_PATH_MODE, SHAPE_PATH_MODE, LEGACY_LINE_MODE, DOT_MODE, DRAWING_MODES,
                             build_execution_paths, order_paths, stats as continuous_path_stats)
from StrokeOptimizer import (STROKE_OPTIMIZER_MODES, optimize_execution_groups,
                             resolve_stroke_optimizer, validate_stroke_optimizer)
from AdaptiveDetail import (ADAPTIVE_DETAIL_MODES, apply_adaptive_detail, prune_flat_micro_strokes,
                            validate_adaptive_detail)
from QuickSketchFillContour import (QUICK_SKETCH_RENDER_STYLE, QUICK_SKETCH_STYLES, QUICK_SKETCH_FILL_PREFERENCES,
                                      apply_quick_sketch_policy, build_quick_sketch_geometry, is_quick_sketch,
                                      validate_quick_sketch_style, validate_fill_preference)
from HybridRenderer3 import (HYBRID_RENDER_STYLE, HYBRID_MODES, apply_hybrid_policy,
                             is_hybrid_renderer, validate_hybrid_mode)
from SketchFillRenderer import (SKETCH_FILL_RENDER_STYLE, build_sketch_fill_plan, is_sketch_fill,
                                _PlanImageOwner, _current_plan_image_owner, _own_color_plan_image)
from VisualVerification import (VISUAL_VERIFICATION_MODES, resolve_visual_verification,
                                validate_visual_verification, planned_batch_points,
                                planned_batch_boxes, compare_batch_snapshot, summarize_result)
from ShapePaths import (STROKE_CAPS, SHAPE_ORDERS, SHAPE_MODEL_MODES, build_shape_execution_paths,
                        validate_shape_order, validate_stroke_cap, validate_shape_model)
from TimeBudget import (TIME_BUDGET_MODES, TARGET_STROKE_COUNTS, apply_target_path_cap,
                        resolve_time_budget_seconds, resolve_target_stroke_count,
                        validate_time_budget_mode, validate_target_stroke_count,
                        parse_custom_stroke_count)
from ProgressiveRenderer import (PROGRESSIVE_RENDERING_MODES, build_progressive_sequence,
                                progressive_enabled, validate_progressive_rendering)
from PlanningWatchdog import (PLANNING_WATCHDOG_MODES, build_planning_attempts,
                              validate_planning_watchdog)
from ResourceAllocation import (CPU_WORKER_CHOICES, CPU_ENGINE_MODES, RAM_BUDGETS, PLANNING_RESOLUTION_MODES,
                                resolve_allocation, resolve_planning_limits, benchmark_allocation,
                                validate_cpu_workers, validate_cpu_engine,
                                validate_ram_budget, validate_planning_resolution, parse_custom_ram_mb)
from ResourceScheduler import (RESOURCE_SCHEDULER_MODES, benchmark_scheduler,
                               load_recommendation as load_resource_recommendation,
                               machine_signature as resource_machine_signature,
                               resolve_resource_schedule, validate_resource_scheduler)
from PerformanceProfiler import (begin as profiler_begin, start as profiler_start, stop as profiler_stop,
                                 finalize as profiler_finalize, format_profile as format_performance_profile,
                                 dominant_phase as profiler_dominant_phase)
from DynamicColors import (EXACT_COLOR_LIMITS, validate_exact_color_limit, resolve_exact_color_limit, build_dynamic_color_strokes)
from AdaptiveColorCount import recommend_adaptive_color_count
from TimeAwareColorBudget import apply_time_aware_color_budget
from ExactColorTools import (custom_rgb_available, eyedropper_available, spectrum_available, numeric_rgb_available,
                             resolve_image_custom_color_workflow,
                             resolved_controls as resolve_exact_color_controls)

from GameProfiles import PROFILES, profile_defaults, profile_ui
from ProfileEngine import (PROFILE_ENGINE_MODES, policy_summary, resolve_profile_policy, validate_profile_engine)
from FastDryRun import sample_plan as sample_dry_run_plan, DRY_RUN_EXECUTION_SECONDS, DryRunBudgetComplete
from DropInStart import DROP_IN_ACTION, DROP_IN_ARM_SECONDS, action_for_import, can_arm as can_arm_drop_in, normalize_action as normalize_drop_in_action
from DropInSynchronization import (
    IDLE as DROP_SYNC_IDLE, AUTO_SETUP_RUNNING as DROP_SYNC_AUTO_SETUP,
    AUTO_RECALIBRATING as DROP_SYNC_AUTO_RECALIBRATING,
    VISUAL_PREFLIGHT_RUNNING as DROP_SYNC_VISUAL_PREFLIGHT,
    READY_TO_DRAW as DROP_SYNC_READY, DRAW_PENDING as DROP_SYNC_PENDING,
    DRAWING as DROP_SYNC_DRAWING, PENDING_TIMEOUT_SECONDS as DROP_SYNC_TIMEOUT_SECONDS,
    make_request as make_pending_drop_in_request, request_expired as pending_drop_in_expired,
    should_wait as drop_in_should_wait, target_fingerprint as drop_in_target_fingerprint,
    target_matches as pending_drop_in_target_matches,
)
from CanvasGuard import CanvasGuard, FinalMouseGuard, normalize_canvas_anchors, CanvasSafetyStop
from AnchorTransform import rebase_canvas_area, transform_points, area_inside_client
from EdgeDetection import verify_canvas_edges_from_capture
from EdgeBehavior import (EDGE_BEHAVIOR_MODES, apply_edge_behavior, resolve_edge_behavior,
                          validate_edge_behavior)
from PreviewSafety import (build_preview_safety_plan, draw_safe_paths,
                           render_preview_safety_map)
from PreviewDetailEngine import (PREVIEW_DETAIL_MODES, validate_preview_detail_mode)
from SafetyDebugOverlay import render_safety_debug_overlay
from RuntimeSafetyReport import (RuntimeSafetySession, safe_save as save_runtime_safety_report,
                                 latest_report as load_latest_runtime_safety_report, REPORT_DIR as RUNTIME_SAFETY_REPORT_DIR)
from RuntimePaths import atomic_write_text, data_dir
from PerformanceAutoTuner import run_auto_tune, load_tune_result, format_tune_summary
from UniversalHardwareBenchmark import (format_hardware_summary as format_universal_hardware_summary,
                                        profile_needs_benchmark)
from Version import APP_VERSION, BUILD_CHANNEL
from VersionHistory import read_version_history
from MobilePreview import MobilePreviewServer
from CrashDiagnostics import (install as install_crash_diagnostics, begin_run_marker,
                              log_event, log_error, previous_run_unclean, clean_exit)

install_crash_diagnostics()

BASE = DATA_DIR
SETTINGS = BASE / 'settings.json'
QUALITY = {'Quick sketch': 6, 'Balanced': 8, 'High detail': 9, 'Maximum detail': 10}
SPEED = {name: speed_base_delay(name) for name in SPEED_PROFILES}
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_SOURCE_PIXELS = 25_000_000
MAX_CAPTURE_PIXELS = 40_000_000
# v1.0.11: the live UI preview is intentionally lighter than the final
# Start Drawing plan. The final plan is still generated at full selected canvas
# size immediately before mouse input is armed.
PREVIEW_MAX_PIXELS = 320_000
PREVIEW_MAX_DIMENSION = 760
PREVIEW_PLAN_TIMEOUT_SECONDS = 14.0
PREVIEW_FALLBACK_TIMEOUT_SECONDS = 6.0
PREVIEW_MODES = ('Manual', 'Auto light', 'Auto full')
COLOR_WORKFLOWS = ('Finish color first', 'Progressive passes')
_RECOVERY_IMAGE_UNSET=object()


def _validated_setup_payload(payload, *, require_canvas=False):
    """Validate a complete window/canvas update before changing any UI state."""
    from CalibrationValidation import screen_rect,contained_rect,finite_confidence
    if not isinstance(payload,dict) or not isinstance(payload.get('target_meta'),dict):
        raise ValueError('Automatic setup returned no verified target window.')
    meta=dict(payload['target_meta'])
    handle=meta.get('handle')
    if type(handle) is not int or not 0<handle<2**64:
        raise ValueError('Automatic setup returned an invalid target handle.')
    meta['rect']=screen_rect(meta.get('rect'),'target window')
    meta['client_rect']=contained_rect(meta.get('client_rect'),meta['rect'],'target client')
    confidence=finite_confidence(payload.get('canvas_confidence',payload.get('confidence',0)))
    canvas=None
    if payload.get('canvas_box') is not None and confidence>=.70:
        canvas=contained_rect(payload['canvas_box'],meta['client_rect'],'detected canvas',min_side=10)
    if require_canvas and canvas is None:
        raise ValueError('Automatic setup could not verify a drawable canvas. Select the drawing area again.')
    return meta,canvas


def apply_profile_defaults(app, profile_name):
    """Apply safe profile defaults before profile-specific saved settings are read."""
    values=profile_defaults(profile_name)
    for name,value in values.items():
        var=getattr(app,name,None)
        setter=getattr(var,'set',None)
        if setter is not None:
            setter(value)


def validate_preview_mode(value):
    if value not in PREVIEW_MODES:
        raise ValueError('Choose a valid preview mode.')
    return value


def preview_safe_options(options, mode='Manual', *, fallback=False):
    """Return a cancellable, bounded planner configuration for UI previews.

    Automatic/lightweight preview is intentionally a bounded approximation of the
    final plan. Explicit Manual / Auto full Build preview requests are routed to
    ``full_preview_options`` instead, preserving final planner geometry while the
    resource policy stays UI-safe and cancellable.
    """
    out=dict(options)
    requested_resolution=str(out.get('planning_resolution','Auto'))
    requested_color=str(out.get('color_rendering','Perceptual match'))
    requested_layers=str(out.get('color_layers','Off'))
    out['_preview_safe_pipeline']=True
    out['_preview_requested_planning_resolution']=requested_resolution
    out['_preview_requested_color_rendering']=requested_color
    out['_preview_requested_color_layers']=requested_layers

    # v1.0.119: previews stay bounded/cancellable, but Auto is no longer forced
    # to one logical CPU. ResourceScheduler caps preview work at 1-4 workers
    # depending on image size. Auto light/fallback remain single-worker.
    if fallback or mode=='Auto light':
        out['cpu_workers']='1'
        out['cpu_workers_resolved']=1
    else:
        requested_workers=str(out.get('cpu_workers') or 'Auto')
        if requested_workers == 'Auto':
            out['cpu_workers']='Auto'
        else:
            # Manual allocations remain respected for final drawing, but a UI
            # preview is intentionally capped at four workers so cancellation
            # and Tk/input latency stay responsive. ResourceScheduler may choose
            # fewer workers again for smaller preview workloads.
            try:
                preview_worker_cap=max(1,min(4,int(requested_workers)))
                out['cpu_workers']=str(preview_worker_cap)
                out['cpu_workers_resolved']=preview_worker_cap
            except (TypeError,ValueError):
                out['cpu_workers']='Auto'
        # Auto retains the machine allocation; make_plan replaces it with the
        # workload-specific preview schedule (1-4 workers).
    out['cpu_engine']='Threads'
    out['_preview_requested_gpu_mode']=str(out.get('gpu_mode') or 'Auto')
    out['gpu_mode']='CPU'
    out['gpu_preview_fallback_reason']='Preview image-matrix work stays CPU to keep cancellation latency bounded; final planning re-evaluates CUDA.'
    out['gpu_performance']='Balanced'

    # Auto light is deliberately tiny. Manual/Auto full may use High internally,
    # but Ultra/Extreme are final-plan settings and are unsafe for a live preview.
    if fallback or mode=='Auto light':
        effective_resolution='Standard'
    elif requested_resolution in ('High','Ultra','Extreme'):
        effective_resolution='High'
    else:
        effective_resolution='Standard' if requested_resolution=='Auto' else requested_resolution
    out['planning_resolution']=effective_resolution

    # Layer mixing is the most expensive preview color path and can spend a long
    # time inside one row before a cancellation check.  Preview the base palette
    # perceptually; final drawing still uses the user's requested layer mode.
    out['color_layers']='Off'
    if requested_color=='Layered color mix':
        out['color_rendering']='Perceptual match'
    if fallback:
        out['color_rendering']='RGB nearest'
        out['draw_quality']='Balanced' if out.get('draw_quality') in ('GPU enhanced','Pixel Accurate') else out.get('draw_quality','Balanced')
        out['background_fill']='Off'
        out['background_simplification']='Strong'
        out['preview_detail_level']='Balanced'
        out['target_stroke_count']='800'
        out['target_stroke_count_resolved']=800
        out['max_stroke_cap']='1000' if out.get('drawing_mode')=='Shape paths' else out.get('max_stroke_cap','Auto')
    else:
        preview_detail=str(out.get('preview_detail_level') or 'Detailed')
        if mode=='Auto light':
            preview_detail='Balanced'
            out['preview_detail_level']=preview_detail
        cap=800 if mode=='Auto light' else 1600
        current=out.get('target_stroke_count_resolved')
        try:
            out['target_stroke_count_resolved']=min(int(current),cap) if current is not None else cap
        except (TypeError,ValueError):
            out['target_stroke_count_resolved']=cap
    return out



def uses_paint_color(app):
    # Legacy name retained for saved profiles and callers; current ink works in all apps.
    return bool(hasattr(app,'paint_simple') and app.paint_simple.get())


def uses_paint_eraser(app):
    return (hasattr(app,'game') and app.game.get()=='Microsoft Paint'
            and hasattr(app,'paint_tool') and app.paint_tool.get()=='Eraser')


def bypasses_palette(app):
    return uses_paint_color(app) or uses_paint_eraser(app)


def runtime_palette_guard_colors(profile_key, palette_positions, colors):
    """Return the palette map that ScreenGuard should verify before input.

    Supported browser games already run Browser Visual Preflight immediately
    before planning/input. Their swatches can contain selection borders, hover
    states and browser antialiasing, so applying Paint's strict per-pixel palette
    guard afterwards can false-stop a valid Gartic/Skribbl/SketchHeads session.
    Paint and generic calibrated apps retain the strict legacy guard.
    """
    try:
        from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
        if str(profile_key or '').lower() in SUPPORTED_BROWSER_PROFILES:
            return {}
    except Exception:
        pass
    return dict(zip(tuple(palette_positions or ()), [tuple(c.RGB) for c in colors]))


def FindClosestRGB(rgb):
    return closest_color(normalize_rgb(rgb))


def load_image(source, cancelled=lambda: False):
    from ImageImport import read_image
    return read_image(source,cancelled,max_download_bytes=MAX_DOWNLOAD_BYTES,
                      max_source_bytes=MAX_SOURCE_BYTES,max_source_pixels=MAX_SOURCE_PIXELS)


def grab_area(area):
    from ScreenGuard import _grab_rgb
    x, y, w, h = map(int, area)
    if w < 1 or h < 1:
        raise ValueError('The capture area is empty.')
    if w * h > MAX_CAPTURE_PIXELS:
        raise ValueError('The selected drawing area is too large to capture safely. Select a smaller canvas.')
    return _grab_rgb((x, y, x + w, y + h))



def preview_area_for(area, *, max_pixels=PREVIEW_MAX_PIXELS, max_dimension=PREVIEW_MAX_DIMENSION):
    """Return a safe live-preview canvas size for a selected drawing area.

    The drawing worker still generates the final plan at the real Paint canvas
    size.  This function keeps automatic UI previews responsive on large Paint
    selections and with expensive colour/fill/GPU-enhanced settings.
    """
    try:
        width, height = [max(1, int(round(v))) for v in area[:2]]
    except (TypeError, ValueError, IndexError, OverflowError) as error:
        raise ValueError('Preview area must contain width and height.') from error
    try:
        max_pixels=int(max_pixels);max_dimension=int(max_dimension)
    except (TypeError,ValueError,OverflowError) as error:
        raise ValueError('Preview limits must be positive integers.') from error
    if max_pixels<1 or max_dimension<1:raise ValueError('Preview limits must be positive integers.')
    pixels = width * height
    scale = min(1.0, max_dimension / max(width, height), (max_pixels / max(1, pixels)) ** 0.5)
    if scale >= 1:
        return width, height
    pw,ph=max(1,int(width*scale)),max(1,int(height*scale))
    if pw*ph>max_pixels:
        if pw>=ph:pw=max(1,max_pixels//ph)
        else:ph=max(1,max_pixels//pw)
    return pw,ph


def is_preview_plan(options):
    return bool(options.get('_preview_plan'))


def _resource_log_text(options):
    """Compact resource summary for diagnostics; never touches the GUI."""
    try:
        return (
            f"planning={options.get('planning_resolution', 'Auto')} "
            f"cpu={options.get('cpu_workers_resolved', options.get('cpu_workers', '?'))}/"
            f"{options.get('logical_cpus', '?')} "
            f"engine={options.get('cpu_engine', 'Auto')} "
            f"ram={options.get('ram_budget_mb', options.get('ram_budget', '?'))}MB "
            f"gpu={options.get('gpu_mode', 'Auto')}"
            + (f"(requested={options.get('_preview_requested_gpu_mode')} reason=preview-safe) " if options.get('_preview_requested_gpu_mode') and options.get('_preview_requested_gpu_mode')!=options.get('gpu_mode') else " ")
            + f"vram={options.get('gpu_vram', 'Auto')} "
            + (f"gpu_active={bool((options.get('gpu_backend_status') or {}).get('gpu_analysis_active'))} "
               f"gpu_reason={(options.get('gpu_backend_status') or {}).get('fallback_reason','')!r} " if options.get('gpu_backend_status') else "")
            + f"perf={options.get('gpu_performance', 'Balanced')}"
        )
    except Exception:
        return 'resource-summary-unavailable'



def _ensure_time_budget_options(options):
    """Resolve Step 2 budget controls for both GUI and direct test calls."""
    options = dict(options)
    if options.get('unlimited_time') or options.get('time_budget_mode') in ('Unlimited','Unlimited / Accuracy'):
        _mode=options.get('time_budget_mode') if options.get('time_budget_mode') in ('Unlimited','Unlimited / Accuracy') else 'Unlimited'
        options.update(unlimited_time=True,time_budget_mode=_mode,time_budget_active=False,max_seconds=3600,time_budget_seconds=3600,target_stroke_count_resolved=None,deadline_total_seconds=None,deadline_game_time_seconds=None,deadline_hard_stop_seconds=None,deadline_render_budget_seconds=None,deadline_safety_reserve_seconds=0.0)
        options.pop('gartic_timer_deadline',None)
        return options
    pixel_accurate = str(options.get('draw_quality') or '') == 'Pixel Accurate'
    if pixel_accurate:
        # Block D may honor an explicit timer progressively, but it never lets
        # the legacy speed policy reduce source resolution/colours/components.
        options['target_stroke_count']='Auto'
        options['target_stroke_count_resolved']=None
        options.pop('real_speed_budget_meta',None)
    time_budget_mode = options.get('time_budget_mode', 'Manual')
    manual_limit = options.get('manual_max_seconds', options.get('max_seconds', 180))
    try:
        from TimeBudget import resolve_time_budget_details
        budget_details = resolve_time_budget_details(time_budget_mode, manual_limit, options.get('deadline_safety_reserve','Auto'))
        effective_limit, time_budget_active = resolve_time_budget_seconds(time_budget_mode, manual_limit)
        # Use the exact reserve selected by the user when it differs from Auto.
        if budget_details.get('active'):
            effective_limit=max(1,int(round(float(budget_details.get('render_budget_seconds') or effective_limit))))
        target_cap, target_meta = resolve_target_stroke_count(
            options.get('target_stroke_count', 'Auto'), options.get('target_stroke_custom', '2500'),
            time_budget_mode=time_budget_mode, effective_time_seconds=effective_limit,
            speed=options.get('speed', 'Balanced'),
            drawing_mode=options.get('drawing_mode', SMART_PATH_MODE),
            preview=is_preview_plan(options))
        options.update(target_meta)
        options['max_seconds'] = effective_limit
        options['manual_max_seconds'] = int(manual_limit)
        options['time_budget_mode'] = time_budget_mode
        options['time_budget_seconds'] = effective_limit
        options['time_budget_active'] = time_budget_active
        options['deadline_total_seconds'] = budget_details.get('total_seconds')
        options['deadline_game_time_seconds'] = budget_details.get('total_seconds')
        options['deadline_render_budget_seconds'] = budget_details.get('render_budget_seconds')
        options['deadline_hard_stop_seconds'] = budget_details.get('hard_stop_seconds', budget_details.get('total_seconds'))
        options['deadline_safety_reserve_seconds'] = float(budget_details.get('reserve_seconds') or 0.0)
        options['deadline_budget_source'] = budget_details.get('source')
        options['target_stroke_count_resolved'] = None if pixel_accurate else target_cap
        # v1.0.77: browser preset budgets learn from completed real execution
        # throughput instead of relying only on the original static path-rate.
        if time_budget_active and not is_preview_plan(options) and not pixel_accurate:
            try:
                from RealSpeedBudget import apply_budget_policy
                options=apply_budget_policy(options)
            except Exception as error:
                log_event(f'Real-Speed Time Budget fallback to static policy: {error!r}')
    except ValueError:
        # The UI normally validates before this point. Direct legacy callers keep
        # their old max_seconds behaviour instead of failing inside planning.
        options.setdefault('time_budget_mode', 'Manual')
        options.setdefault('time_budget_seconds', int(options.get('max_seconds', 180)))
        options.setdefault('time_budget_active', False)
        options.setdefault('target_stroke_count', 'Auto')
        options.setdefault('target_stroke_count_resolved', None)
        options.setdefault('target_stroke_count_reason', 'legacy')
    return options

def _plan_log_text(plan):
    options = plan.get('options', {}) if isinstance(plan, dict) else {}
    advanced = options.get('advanced_color_meta') or {}
    portrait = options.get('portrait_stats') or {}
    backend = advanced.get('acceleration_backend') or portrait.get('acceleration_backend') or advanced.get('cpu_backend') or 'CPU'
    device = advanced.get('acceleration_device') or portrait.get('acceleration_device') or ''
    extra = f" {device}" if device else ''
    try:
        source = int(plan.get('source_count', plan.get('count', 0)) or 0)
        execution = int(plan.get('count', 0) or 0)
        raw_estimate = float(plan.get('estimate', 0.0) or 0.0)
        _deadline_log=(options.get('adaptive_deadline_meta') or {})
        estimate = float(_deadline_log.get('effective_estimated_seconds', raw_estimate) or raw_estimate)
    except Exception:
        source, execution, estimate, raw_estimate = 0, 0, 0.0, 0.0
    path_stats = plan.get('path_stats') or {} if isinstance(plan, dict) else {}
    shape_bits = ''
    if path_stats.get('mode') == 'Shape paths':
        shape_bits = (
            f" shape_components={path_stats.get('shape_components', 0)}"
            f" shape_model={path_stats.get('shape_model', 'Auto')}"
            f" skipped_tiny={path_stats.get('skipped_tiny_details', 0)}"
            f" skipped_cap={path_stats.get('skipped_due_cap', 0)}"
            f" cap={path_stats.get('max_stroke_cap_resolved', path_stats.get('max_stroke_cap', '?'))}"
        )
    if path_stats.get('progressive_enabled'):
        shape_bits += (
            f" progressive={path_stats.get('progressive_phase_order', 'enabled')}"
            f" foundation={path_stats.get('progressive_foundation_paths', 0)}"
            f" contours={path_stats.get('progressive_contour_paths', 0)}"
            f" details={path_stats.get('progressive_detail_paths', 0)}"
        )
    attempt_bits = ''
    if options.get('planning_attempt_name'):
        attempt_bits = f" watchdog_attempt={options.get('planning_attempt_name')} level={options.get('planning_watchdog_fallback_level',0)}"
    target_bits = ''
    if options.get('time_budget_active') or options.get('target_stroke_count') not in (None, 'Auto'):
        target_bits = (
            f" time_budget={options.get('time_budget_mode', 'Manual')}:{options.get('time_budget_seconds', options.get('max_seconds', '?'))}s"
            f" target={options.get('target_stroke_count_resolved', options.get('target_stroke_count', '?'))}"
            f" target_skipped={path_stats.get('target_skipped_paths', 0)}"
        )
    policy_meta=options.get('profile_policy_meta') or {}
    policy_bits=''
    if policy_meta:
        policy_bits=(f" profile_policy={policy_meta.get('policy','?')}"
                     f" policy_mode={policy_meta.get('mode','Auto')}"
                     f" policy_changes={int(policy_meta.get('changed_count',0) or 0)}")
    turbo_meta=options.get('skribbl_fast_meta') or {}
    gartic_palette_meta=options.get('gartic_phone_fast_meta') or {}
    budget_meta=options.get('real_speed_budget_meta') or {}
    real_speed_bits=(f" real_speed={float(budget_meta.get('paths_per_second',0) or 0):.2f}pps"
                     f" learned={bool(budget_meta.get('learned'))} cap={budget_meta.get('path_cap','?')} colors={budget_meta.get('max_colors','?')}") if budget_meta else ''
    turbo_bits=''
    if turbo_meta.get('active'):
        turbo_bits=(f" skribbl_turbo=on colors={int(turbo_meta.get('active_colors_after',0) or 0)}"
                    f" runs={int(turbo_meta.get('runs_before',0) or 0)}->{int(turbo_meta.get('runs_after',0) or 0)}")
    if gartic_palette_meta.get('active'):
        turbo_bits+=(f" palette_colors={int(gartic_palette_meta.get('active_colors_after',0) or 0)}"
                     f" palette_coverage={float(gartic_palette_meta.get('palette_coverage_percent',100.0) or 100.0):.1f}%"
                     f" p95DE00={float(gartic_palette_meta.get('p95_reduction_delta_e2000',0.0) or 0.0):.1f}"
                     f" posterization={gartic_palette_meta.get('posterization_risk','LOW')}"
                     f" midtone_loss={bool(gartic_palette_meta.get('midtone_loss',False))}")
    performance = plan.get('performance_profile') if isinstance(plan, dict) else None
    profiler_bits = f" profiler=[{format_performance_profile(performance, compact=True)}]" if performance else ''
    optimizer_bits = ''
    if path_stats.get('stroke_optimizer_effective') not in (None,'Off'):
        optimizer_bits = (f" optimizer={path_stats.get('stroke_optimizer_effective')}"
                          f" merged={int(path_stats.get('optimizer_merged_paths',0) or 0)}"
                          f" travel_reduction={float(path_stats.get('optimizer_travel_reduction',0) or 0)*100:.0f}%")
    pixel_meta=options.get('pixel_map_meta') or {}
    pixel_bits=''
    if pixel_meta:
        pixel_bits=(f" pixelmap={int(pixel_meta.get('width',0))}x{int(pixel_meta.get('height',0))}"
                    f" protected={float(pixel_meta.get('protected_percent',0) or 0):.1f}%"
                    f" palette={pixel_meta.get('palette_backend','?')}"
                    f" edges={pixel_meta.get('edge_backend','?')}"
                    f" contours={float(pixel_meta.get('contour_percent',0) or 0):.1f}%"
                    f" shadow_detail={float(pixel_meta.get('shadow_detail_percent',0) or 0):.1f}%"
                    f" micro_detail={float(pixel_meta.get('micro_detail_percent',0) or 0):.1f}%")
    pixel_stroke=options.get('pixel_stroke_meta') or {}
    if pixel_stroke:
        orient=pixel_stroke.get('orientation_counts') or {}
        pixel_bits+=(f" regions={int(pixel_stroke.get('component_count',0) or 0)}"
                     f" local_runs=H{int(orient.get('horizontal',0) or 0)}/V{int(orient.get('vertical',0) or 0)}"
                     f" passes={int(pixel_stroke.get('fill_paths',0) or 0)}/"
                     f"{int(pixel_stroke.get('mid_detail_paths',0) or 0)}/"
                     f"{int(pixel_stroke.get('fine_detail_paths',0) or 0)}/"
                     f"{int(pixel_stroke.get('cleanup_paths',0) or 0)}"
                     f" contour_regions={int(pixel_stroke.get('contour_components',0) or 0)}"
                     f" shadow_regions={int(pixel_stroke.get('shadow_components',0) or 0)}"
                     f" shadow_detail_regions={int(pixel_stroke.get('shadow_detail_components',0) or 0)}"
                     f" merge_fallbacks={int(pixel_stroke.get('safe_merge_fallbacks',0) or 0)}")
    pixel_accuracy=options.get('pixel_accuracy_meta') or {}
    if pixel_accuracy:
        pixel_bits+=(f" accuracy={float(pixel_accuracy.get('final_accuracy_percent',0) or 0):.2f}%"
                     f" coverage={float(pixel_accuracy.get('coverage_percent',0) or 0):.2f}%"
                     f" edge_accuracy={float(pixel_accuracy.get('edge_accuracy_percent',0) or 0):.2f}%"
                     f" corrections={int(pixel_accuracy.get('correction_paths_added',0) or 0)}"
                     f" errors={int(pixel_accuracy.get('final_error_pixels',0) or 0)}"
                     f" sim={pixel_accuracy.get('simulation_backend','?')}")
        prog=pixel_accuracy.get('progressive_time_budget') or {}
        if prog.get('active'):
            pixel_bits+=(f" progressive_budget={int(prog.get('base_path_budget',0) or 0)}/"
                         f"{int(prog.get('path_budget',0) or 0)}"
                         f" omitted={int(prog.get('paths_omitted',0) or 0)}")
    detail_meta=options.get('adaptive_detail_meta') or {}
    detail_bits=''
    if detail_meta.get('adaptive_detail_effective') not in (None,'Off'):
        detail_bits=(f" adaptive_detail={detail_meta.get('adaptive_detail_effective')}"
                     f" complexity={float(detail_meta.get('adaptive_detail_complexity',0) or 0):.2f}"
                     f" protected={float(detail_meta.get('adaptive_detail_protected_percent',0) or 0):.0f}%"
                     f" pruned_micro={int(detail_meta.get('adaptive_detail_pruned_micro_strokes',0) or 0)}")
    preview_detail=options.get('preview_detail_meta') or {}
    if preview_detail:
        detail_bits+=(f" preview_detail={preview_detail.get('preview_detail_mode','?')}"
                     f" micro_recovered={float(preview_detail.get('preview_detail_recovered_percent',0) or 0):.1f}%"
                     f" oversample={int(preview_detail.get('preview_detail_oversample',1) or 1)}x")
    detail_zoom_meta=options.get('detail_zoom_meta') or {}
    if detail_zoom_meta.get('enabled'):
        detail_bits+=(f" detail_zoom={detail_zoom_meta.get('analysis_zoom','?')}"
                     f" zoom_paths={int(detail_zoom_meta.get('detail_paths_added',0) or 0)}"
                     f" zoom_pixels={int(detail_zoom_meta.get('detail_pixels_added',0) or 0)}"
                     f" detail_brush={int(detail_zoom_meta.get('smallest_detail_brush_px',options.get('brush_px',1)) or 1)}px")
    deadline_meta=options.get('adaptive_deadline_meta') or {}
    deadline_bits=''
    if deadline_meta.get('enabled'):
        deadline_bits=(f" deadline={deadline_meta.get('mode','?')}"
                       f" game_time={float(deadline_meta.get('total_seconds',0) or 0):.1f}s"
                       f" budget={float(deadline_meta.get('render_budget_seconds',0) or 0):.1f}s"
                       f" reserve={float(deadline_meta.get('reserve_seconds',0) or 0):.1f}s"
                       f" hard_stop={float(deadline_meta.get('hard_stop_seconds',deadline_meta.get('total_seconds',0)) or 0):.1f}s"
                       f" status={deadline_meta.get('budget_status','?')}"
                       f" paths={int(deadline_meta.get('source_paths',0) or 0)}->{int(deadline_meta.get('selected_paths',0) or 0)}"
                       f" retained={float(deadline_meta.get('quality_retained_percent',0) or 0):.1f}%"
                       f" timing={deadline_meta.get('operation_timing_model','model')}"
                       f" cold={float((deadline_meta.get('calibration') or {}).get('cost_multiplier',1.0) or 1.0):.2f}x")
    color_meta=options.get('advanced_color_meta') or {}
    color_diag=color_meta.get('color_fidelity_diagnostics') or {}
    color_bits=''
    if color_meta:
        _adaptive_count=color_meta.get('adaptive_color_count') or {}
        if _adaptive_count.get('active'):
            _image_colors=int(_adaptive_count.get('image_recommended_colors',_adaptive_count.get('recommended_colors',0)) or 0)
            _final_colors=int(_adaptive_count.get('recommended_colors',0) or 0)
            _time_colors=(f"->{_final_colors} time_color_budget={float(_adaptive_count.get('render_budget_seconds',0) or 0):.1f}s"
                          f" color_cost={float(_adaptive_count.get('estimated_marginal_color_seconds',0) or 0):.3f}s"
                          f" cost_source={_adaptive_count.get('direct_color_change_source','?')}") if _adaptive_count.get('time_budget_applied') else ''
            _adaptive_count_bits=(f" auto_colors={_image_colors}{_time_colors}/{int(_adaptive_count.get('ceiling_colors',0) or 0)}"
                                  f" color_complexity={float(_adaptive_count.get('complexity_score',0) or 0):.2f}"
                                  f" color_stop={_adaptive_count.get('stop_reason','?')}")
        else:
            _adaptive_count_bits=''
        _named_rows=color_meta.get('named_color_mappings') or ()
        _named_top=_named_rows[0] if _named_rows and isinstance(_named_rows[0],dict) else {}
        _named_bits=(f" named_top={_named_top.get('source_name')}->{_named_top.get('mapped_name')}"
                     if _named_top.get('source_name') and _named_top.get('mapped_name') else '')
        color_bits=(f" color_fidelity={color_meta.get('color_fidelity',options.get('color_fidelity','?'))}"
                    f" rating={color_diag.get('color_fidelity_rating','?')}"
                    f" lightness_drift={float(color_diag.get('lightness_drift',0) or 0):+.1f}"
                    f" luminance_drift={float(color_diag.get('luminance_drift_percent',0) or 0):+.1f}%"
                    f" saturation_drift={float(color_diag.get('saturation_drift',0) or 0):+.1f}"
                    f" hue_drift={float(color_diag.get('hue_drift',0) or 0):.1f}"
                    f" deltaE2000={float(color_diag.get('average_delta_e2000',0) or 0):.1f}"
                    f" deltaE76={float(color_diag.get('average_delta_e76',0) or 0):.1f}"
                    f" dark_bias={bool(color_diag.get('dark_bias_detected',False))}" + _named_bits + _adaptive_count_bits)
    extra_fast_v2_meta=options.get('extra_fast_v2_meta') or {}
    extra_fast_bits=''
    if extra_fast_v2_meta.get('enabled'):
        extra_fast_bits=(f" extra_fast2=hybrid fill_regions={int(extra_fast_v2_meta.get('fill_regions',0) or 0)}"
                         f" scan_paths={int(extra_fast_v2_meta.get('connected_scanline_paths',0) or 0)}"
                         f" boundaries_removed={int(extra_fast_v2_meta.get('scanline_boundaries_removed',0) or 0)}"
                         f" reduction={float(extra_fast_v2_meta.get('scanline_boundary_reduction_percent',0) or 0):.1f}%"
                         f" policy={extra_fast_v2_meta.get('path_policy','?')} color_pipeline=preserved")
    quick_meta=options.get('quick_sketch_meta') or {}
    quick_bits=''
    if quick_meta.get('enabled'):
        quick_bits=(f" quick_sketch={quick_meta.get('style','?')}"
                    f" colors={int(quick_meta.get('active_colors_after',0) or 0)}/{int(quick_meta.get('color_cap',0) or 0)}"
                    f" fills={int(quick_meta.get('fill_regions',0) or 0)}"
                    f" fill_cov={float(quick_meta.get('fill_coverage_percent',0) or 0):.1f}%"
                    f" fallback={int(quick_meta.get('fallback_scanline_regions',0) or 0)}"
                    f" contours={int(quick_meta.get('visible_contour_segments',0) or 0)}"
                    f" micro_pruned={int(quick_meta.get('micro_strokes_pruned',0) or 0)}"
                    f" reduction={float(quick_meta.get('stroke_run_reduction_percent',0) or 0):.1f}%")
    sketch_fill_meta=options.get('sketch_fill_meta') or {}
    sketch_fill_bits=''
    if sketch_fill_meta.get('enabled'):
        sketch_fill_bits=(f" sketch_fill=on sketch={int(sketch_fill_meta.get('sketch_paths',0) or 0)}"
                          f" fill={int(sketch_fill_meta.get('color_fill_paths',0) or 0)}"
                          f" reoutline={int(sketch_fill_meta.get('reoutline_paths',0) or 0)}"
                          f" fill_method={sketch_fill_meta.get('fill_method','?')}")
    region_meta=options.get('region_fill_meta') or {}
    region_bits=''
    if region_meta.get('enabled'):
        region_bits=(f" region_fill={region_meta.get('quality_preset','?')}/{region_meta.get('fill_aggressiveness','?')}"
                     f" regions={int(region_meta.get('total_regions',0) or 0)}"
                     f" safe={int(region_meta.get('fill_safe_regions',0) or 0)}"
                     f" fills={int(region_meta.get('fill_actions',0) or 0)}"
                     f" fill_coverage={float(region_meta.get('fill_coverage_percent',0) or 0):.1f}%"
                     f" stroke_reduction={float(region_meta.get('stroke_reduction_percent',0) or 0):.1f}%"
                     f" saved_time={float(region_meta.get('estimated_time_saved_seconds',0) or 0):.1f}s")
        if region_meta.get('pixel_accurate_protected'):
            region_bits+=' exact_pixel_protected=true'
    return (
        f"source_strokes={source} execution_paths={execution} estimate={estimate:.1f}s" + (f" raw_model={raw_estimate:.1f}s" if abs(estimate-raw_estimate)>.05 else "") + f"{shape_bits}{target_bits}{attempt_bits}{optimizer_bits}{detail_bits}{pixel_bits}{color_bits}{quick_bits}{sketch_fill_bits}{region_bits}{extra_fast_bits}{deadline_bits}{policy_bits}{real_speed_bits}{turbo_bits}{profiler_bits} "
        f"effective_resolution={options.get('planning_resolution_effective', options.get('planning_resolution', 'Standard'))} "
        f"sample_limit={options.get('planner_sample_limit', '?')} "
        f"max_pixels={options.get('planner_max_pixels', '?')} "
        f"backend={backend}{extra} "
        f"{_resource_log_text(options)}"
    )

def _finalize_auto_tuned_plan(plan, original, area, cancelled=lambda: False):
    """Attach Step 11 acceptance metadata and perform at most one rescue replan."""
    try:
        from EndToEndAutoTuner import evaluate_plan_acceptance, propose_rescue_options
        opts=plan.get('options') if isinstance(plan,dict) else None
        tuner=opts.get('auto_tuner_meta') if isinstance(opts,dict) else None
        if not isinstance(tuner,dict) or not tuner.get('active'):
            return plan
        acceptance=evaluate_plan_acceptance(plan)
        opts['auto_tuner_acceptance_meta']=acceptance
        plan['auto_tuner_acceptance']=acceptance
        try:
            from PreviewDiagnostics import build_preview_diagnostics
            _diag=build_preview_diagnostics(
                opts,accuracy=opts.get('adaptive_accuracy_meta') or {},
                delta_e=opts.get('preview_delta_e_meta') or {},draw_time=plan.get('draw_time_estimate') or {},
                path_count=int(plan.get('count',0) or 0),source_count=int(plan.get('source_count',0) or 0),
                performance_profile=plan.get('performance_profile') or {})
            opts['preview_diagnostics_meta']=_diag;plan['preview_diagnostics']=_diag
        except Exception as _step11_diag_error:
            log_event(f'Step 11 preview diagnostics refresh skipped: {_step11_diag_error!r}')
        rescue=propose_rescue_options(plan,acceptance)
        if rescue is None:
            return plan
        log_event(
            'Step 11 bounded replan: '
            f"status={acceptance.get('status')} strategy={tuner.get('selected_strategy')} -> "
            f"{(rescue.get('auto_tuner_meta') or {}).get('selected_strategy')} "
            f"projected={acceptance.get('projected_draw_seconds')} usable={acceptance.get('usable_deadline_seconds')} "
            f"visual={acceptance.get('visual_accuracy_percent')}."
        )
        return make_plan(original,area,rescue,cancelled)
    except InterruptedError:
        raise
    except Exception as error:
        # Step 11 is an optimization/acceptance layer. It may never invalidate an
        # otherwise safe plan if diagnostics are unavailable.
        log_event(f'Step 11 acceptance evaluation skipped safely: {error!r}')
        return plan


def make_plan(original, area, options, cancelled=lambda: False):
    from DrawTimeCalibration import planning_calibration_scope
    with planning_calibration_scope():
        return _make_plan(original, area, options, cancelled)


def _make_plan(original, area, options, cancelled=lambda: False):
    from PIL import Image, ImageEnhance, ImageDraw, ImageFilter, ImageOps
    from AutoDrawing import resolve_drawing
    if cancelled():raise InterruptedError('Planning cancelled.')
    options=dict(options,_planning_canvas_size=tuple(area))
    # v1.0.131: Sketch + Auto Fill owns an explicit Paint-only phase order.
    # Route it before AutoDrawing so Auto cannot replace the user's selected
    # renderer. The recursive colour sub-plan is marked _sketch_fill_inner.
    if is_sketch_fill(options):
        return build_sketch_fill_plan(original,area,options,make_plan,finish_plan,cancelled,
                                      _finalize=_finalize_auto_tuned_plan)
    # Step 29: Hybrid Renderer 3.0 resolves specialised deterministic policy
    # before the generic AutoDrawing selector. It only changes renderer/planner
    # fields; CanvasGuard, calibration and input authorisation remain separate.
    if is_hybrid_renderer(options):
        options=apply_hybrid_policy(original,options,cancelled=cancelled)
    options=resolve_drawing(original,options,cancelled=cancelled)
    # v1.0.125 Step 1: retain an untouched source object for source-relative
    # preview accuracy. Downstream preprocessing/contrast/palette stages must not
    # overwrite the reference used by AccuracyEvaluator.
    if not isinstance(options.get('_accuracy_original_source'), Image.Image):
        options['_accuracy_original_source']=_own_color_plan_image(original.copy())
    # Sketch wins over stale/restored subject settings before any colour policy.
    if options.get('outline'):
        options = dict(options, subject_focus='Off')
    options = _ensure_time_budget_options(options)
    if options.get('subject_focus', 'Off') != 'Off':
        if options.get('outline') or options.get('paint_current_color') or options.get('erase_mode'):
            raise ValueError('Subject focus needs full colour drawing. Turn off Outline, Eraser and current-colour-only mode.')
        options['draw_quality'] = 'Pixel Accurate'
    # Extra Fast quality fix: the old route built connected scanlines and then
    # applied a generic path-count cap, which could discard most of a portrait
    # (for example 653 candidate paths -> 182 kept). Adaptive Region Hybrid
    # instead chooses exact connected components, verified H/V geometry, Fill
    # and physically verified browser brush sizes under the real time model.
    # Its component scheduler owns the deadline, so important structure is not
    # destroyed later by an unrelated per-path cap.
    if (options.get('extra_fast') and options.get('extra_fast_v2')
            and not options.get('_adaptive_hybrid_inner')
            # Pixel Art and Subject focus already selected an exact component
            # renderer. Wrapping its finished plan in another regional planner
            # discarded that new sequence while publishing its diagnostics.
            and options.get('draw_quality') != 'Pixel Accurate'
            and not (options.get('paint_current_color') or options.get('outline') or options.get('erase_mode'))
            # A legacy/manual profile can claim Fill capability without carrying
            # executable tool actions. Preserve the proven ExtraFast2 Fill route
            # for that incomplete metadata case; regional hybrid owns all no-Fill
            # runs (the user's failing Gartic case) and fully calibrated Fill runs.
            and (not options.get('fill_tool_available') or bool(options.get('fill_tool_actions')))):
        from AdaptiveRegionHybrid import build_adaptive_hybrid_plan
        plan=build_adaptive_hybrid_plan(original,area,options,make_plan,finish_plan,cancelled)
        # The wrapper changes geometry and cost after its inner color planner
        # returns. Acceptance and a bounded rescue must use this actual result.
        return _finalize_auto_tuned_plan(plan,original,area,cancelled)
    if options.get('outline') and options.get('sketch_detail')=='Auto':
        from AutoSketchBudget import choose_sketch
        return choose_sketch(original,area,options,make_plan,finish_plan,cancelled)
    profiler_begin(options)
    try:
        if 'cpu_workers_resolved' not in options or 'ram_budget_mb' not in options:
            options.update(resolve_allocation(options.get('cpu_workers', 'Auto'),
                                              options.get('cpu_engine', 'Auto'),
                                              options.get('ram_budget', 'Auto'),
                                              options.get('ram_custom_mb', '2048')))
    except ValueError:
        options.update({'cpu_workers':'1','cpu_workers_resolved':1,'cpu_engine':'Auto',
                        'ram_budget':'512 MB','ram_budget_mb':512,
                        'logical_cpus':1,'available_ram_mb':None})
    try:
        from GpuBackendStatus import verified_gpu_status
        _pixels=max(1,int(area[0]))*max(1,int(area[1]))
        _preview=is_preview_plan(options)
        _gpu_requested=options.get('_preview_requested_gpu_mode',options.get('gpu_mode','Auto'))
        _gpu_status=verified_gpu_status(_gpu_requested,options.get('gpu_vram','Auto'),options.get('gpu_performance','Balanced'),pixels=_pixels,preview=_preview)
        options['gpu_backend_status']=_gpu_status
        _existing_schedule=options.get('resource_scheduler_plan') or {}
        _must_reschedule=(not _existing_schedule or bool(_existing_schedule.get('gpu_available'))!=bool(_gpu_status.get('gpu_analysis_active')) or
                          bool(_existing_schedule.get('preview',False))!=bool(_preview))
        if _must_reschedule:
            schedule=resolve_resource_schedule(
                options, mode=options.get('resource_scheduler','Auto'), area=area,
                drawing_mode=options.get('drawing_mode', SMART_PATH_MODE),
                gpu_mode=options.get('gpu_mode','Auto'),
                gpu_available=bool(_gpu_status.get('gpu_analysis_active')),
                preview=_preview)
            schedule['preview']=bool(_preview)
            options['resource_scheduler_plan']=schedule
        else:
            schedule=_existing_schedule
        if options.get('resource_scheduler','Auto')!='Off':
            options['cpu_workers_resolved']=int(schedule.get('effective_cpu_workers',options.get('cpu_workers_resolved',1)) or 1)
            options['cpu_engine']=schedule.get('recommended_engine',options.get('cpu_engine','Auto'))
    except (ValueError,TypeError,KeyError):
        options['resource_scheduler_plan']={'version':2,'mode':'Off','phases':{},'reason':'scheduler unavailable'}

    try:
        planning_limits = resolve_planning_limits(options.get('detail', 8), area,
            planning_resolution=options.get('planning_resolution', 'Auto'),
            cpu_workers=options.get('cpu_workers_resolved', 1),
            ram_budget_mb=options.get('ram_budget_mb', 512),
            preview=is_preview_plan(options))
    except ValueError:
        planning_limits = resolve_planning_limits(options.get('detail', 8), area,
            planning_resolution='Standard', cpu_workers=1, ram_budget_mb=512, preview=is_preview_plan(options))
    options.update(planning_limits)
    if str(options.get('draw_quality') or '') == 'Pixel Accurate':
        # Step 26: full target-raster analysis before any lossy simplification.
        target_w=max(1,int(area[0]));target_h=max(1,int(area[1]))
        options['planner_sample_limit']=max(target_w,target_h)
        options['planner_max_pixels']=target_w*target_h
    from DetailFidelityPlanner import apply_detail_fidelity_policy
    options,step26_meta=apply_detail_fidelity_policy(options)
    options['detail_fidelity_meta']=step26_meta
    # Step 25: Quick Sketch is a renderer policy layered on the existing safe
    # color/fill/deadline engines. Auto Tuner may select it, or the user can
    # choose it explicitly. Safety/calibration fields are never weakened here.
    if is_quick_sketch(options):
        options = apply_quick_sketch_policy(options)
    render_style = options.get('render_style', 'Auto')

    # Auto uses the portrait renderer for single-colour Paint sketches because
    # photographs lose most facial tone when reduced to one binary threshold.
    # Palette drawings keep the faster colour-run planner unless Portrait is
    # explicitly selected.
    portrait_mode = render_style == 'Portrait / shaded' or (
        render_style == 'Auto' and options.get('paint_current_color') and not options.get('erase_mode'))
    if portrait_mode and options.get('paint_current_color') and not options.get('outline'):
        draw_quality = options.get('draw_quality', 'High likeness')
        gpu_mode = options.get('gpu_mode', 'Auto')
        gpu_vram = options.get('gpu_vram', 'Auto')
        gpu_performance = options.get('gpu_performance', 'Balanced')
        acceleration_meta = {}
        _prof_pre = profiler_start(options, 'preprocessing')
        preview_detail_meta={}
        preview_detail_mode=options.get('preview_detail_level','Detailed') if is_preview_plan(options) and not options.get('_full_detail_preview') else None
        gray, fitted = prepare_portrait_image(original, area, options['detail'], options['contrast'], options.get('portrait_focus',True), draw_quality,
                                               gpu_mode=gpu_mode, acceleration_meta=acceleration_meta, gpu_vram=gpu_vram, gpu_performance=gpu_performance,
                                               preview_detail_mode=preview_detail_mode,preview_detail_meta=preview_detail_meta,cancelled=cancelled)
        if preview_detail_meta:options['preview_detail_meta']=preview_detail_meta
        profiler_stop(options, 'preprocessing', _prof_pre)
        # Fit portrait complexity to the configured time limit.  This avoids the
        # previous situation where High/Balanced previews looked good but Start
        # drawing immediately rejected them for exceeding the default 180 s.
        speed_name = normalize_speed(options.get('speed', 'Balanced'))
        seconds_per_stroke = {'Safe': .18, 'Balanced': .12, 'Fast': .08}[speed_name] + options['delay'] * 2.0
        unlimited=bool(options.get('unlimited_time'))
        time_budget = None if unlimited else max(1, int(options.get('max_seconds', 180) / seconds_per_stroke * .90))
        _prof_color = profiler_start(options, 'color_planning')
        groups, stats = portrait_strokes(gray, options['detail'], options['lines'], cancelled,
                                         include_edges=True, max_strokes=time_budget,
                                         draw_quality=draw_quality, subject_focus=options.get('portrait_focus', True),
                                         gpu_mode=gpu_mode, acceleration_meta=acceleration_meta, gpu_vram=gpu_vram, gpu_performance=gpu_performance)
        profiler_stop(options, 'color_planning', _prof_color)
        plan_options = dict(options)
        # Paint produces continuous brush lines between cursor positions; a
        # slightly larger interpolation step makes shaded portraits practical
        # without changing the generated stroke geometry.
        plan_options['stroke_step_px'] = 12
        plan_options['portrait_stats'] = {
            'tone_strokes': stats.tone_strokes, 'edge_strokes': stats.edge_strokes,
            'levels': stats.levels, 'sample_size': stats.sample_size,
            'priority_strokes': stats.priority_strokes, 'draw_quality': stats.draw_quality,
            'acceleration_backend': stats.acceleration_backend, 'acceleration_device': stats.acceleration_device,
            'gpu_accelerated': stats.gpu_accelerated, 'gpu_requested': gpu_mode,
            'gpu_vram': gpu_vram, 'gpu_performance': gpu_performance,
            'vram_budget_mb': acceleration_meta.get('vram_budget_mb'),
            'pool_used_mb': acceleration_meta.get('pool_used_mb'), 'pool_cached_mb': acceleration_meta.get('pool_cached_mb'),
            'compute_capability': acceleration_meta.get('compute_capability',''), 'multiprocessors': acceleration_meta.get('multiprocessors'),
            'allocation_mode': acceleration_meta.get('allocation_mode','Adaptive'), 'tile_rows': acceleration_meta.get('tile_rows'),
            'workspace_estimate_mb': acceleration_meta.get('workspace_estimate_mb'), 'cuda_execution': acceleration_meta.get('cuda_execution',''),
            'scaler': acceleration_meta.get('scaler','CPU Lanczos'),
            'acceleration_reason': str(acceleration_meta.get('reason',''))[:240]}
        plan = finish_plan(gray.convert('RGBA'), fitted, groups, plan_options, cancelled)
        # The estimator also accounts for physical line length, so a count-only
        # budget can still be too slow on a large Paint canvas.  Thin the edge
        # and tone sets evenly (never just truncate the top of the image) until
        # the planned run fits with a small safety margin.
        target_seconds = max(5.0, options.get('max_seconds', 180) * .92)
        for _ in range(0 if unlimited else 3):
            if plan['estimate'] <= target_seconds or plan['count'] <= 1:
                break
            ratio = max(.12, min(.95, target_seconds / max(plan['estimate'], .001) * .92))
            strokes = plan['groups'][0]
            edge_count = int(plan_options['portrait_stats']['edge_strokes'])
            edges, tones = strokes[:edge_count], strokes[edge_count:]
            def evenly_sample(items, wanted):
                if wanted >= len(items): return list(items)
                if wanted <= 0: return []
                return [items[min(len(items)-1, int((i + .5) * len(items) / wanted))] for i in range(wanted)]
            edge_keep = min(len(edges), max(1, int(len(edges) * ratio))) if edges else 0
            tone_keep = min(len(tones), max(1, int(len(tones) * ratio))) if tones else 0
            edges = evenly_sample(edges, edge_keep)
            tones = evenly_sample(tones, tone_keep)
            plan_options = dict(plan_options)
            plan_options['portrait_stats'] = dict(plan_options['portrait_stats'],
                edge_strokes=len(edges), tone_strokes=len(tones),
                priority_strokes=min(int(plan_options['portrait_stats'].get('priority_strokes', 0)), len(tones)),
                time_fitted=True)
            plan = finish_plan(gray.convert('RGBA'), fitted, [edges + tones], plan_options, cancelled)
        return _finalize_auto_tuned_plan(plan,original,area,cancelled)

    if options.get('outline'):
        if options.get('erase_mode'):raise ValueError('Black sketch requires Pencil or Brush, not Eraser.')
        from SketchPlanner import contour_image,black_index
        from PixelData import monochrome_strokes
        _prof_pre=profiler_start(options,'preprocessing')
        preview_detail_meta={}
        preview_detail_mode=options.get('preview_detail_level','Detailed') if is_preview_plan(options) and not options.get('_full_detail_preview') else None
        image,fitted=prepare_image(original,area,10,sample_limit=min(720,max(area)),max_pixels=518400,
                                   preview_detail_mode=preview_detail_mode,preview_detail_meta=preview_detail_meta,cancelled=cancelled)
        if preview_detail_meta:options['preview_detail_meta']=preview_detail_meta
        _sketch2_meta=None
        if str(options.get('profile_key') or '').lower()=='microsoft-paint' or str(options.get('profile_name') or '')=='Microsoft Paint':
            from Sketch2Planner import contour_image_v2
            _detail=options.get('sketch_detail','Detailed');_detail='Balanced' if _detail=='Auto' else _detail
            image,_sketch2_meta=contour_image_v2(image,cancelled,detail=_detail)
        else:
            # Browser/Gartic path intentionally stays on the established legacy
            # contour raster and GarticSketchPaths route.
            image=contour_image(image,cancelled,detail=options.get('sketch_detail','Detailed'))
        profiler_stop(options,'preprocessing',_prof_pre)
        ink=monochrome_strokes(image,True,cancelled)[0]
        plan_options=dict(options)
        if _sketch2_meta is not None:plan_options['sketch2_meta']=dict(_sketch2_meta)
        plan_options.update(black_sketch=True,skip_white=True,background_fill='Off',fill_regions=[],
            fill_tool_actions=[],background_simplification='Off',adaptive_detail='Off',
            color_layers='Off',custom_color_workflow='Off',color_selectors=(),
            drawing_mode=SMART_PATH_MODE,smart_paths=True,lines=True,stroke_optimizer='Travel only',
            target_stroke_count_resolved=None,color_workflow='Finish color first',progressive_rendering='Off')
        plan_options.pop('background_fill_plan',None)
        plan_options.pop('real_speed_budget_meta',None)
        plan_options.pop('plan_palette_rgb',None)
        if options.get('paint_current_color'):
            groups=[ink]
        else:
            groups=[[] for _ in allColors]
            if ink:groups[black_index(tuple(c.RGB for c in allColors))]=ink
        if options.get('profile_key') in ('gartic-phone','gartic-io') or options.get('profile_name') in ('Gartic Phone','Gartic.io'):
            from GarticSketchPaths import trace_contours
            paths,sketch_meta=trace_contours(image,cancelled)
            execution=[[] for _ in groups]
            index=0 if options.get('paint_current_color') else black_index(tuple(c.RGB for c in allColors)) if ink else 0
            if execution:execution[index]=paths
            plan_options['sketch_execution_groups']=execution
            plan_options['gartic_sketch_meta']=sketch_meta
            plan_options['stroke_optimizer']='Off'
        return _finalize_auto_tuned_plan(finish_plan(image,fitted,groups,plan_options,cancelled),original,area,cancelled)

    _prof_pre = profiler_start(options, 'preprocessing')
    preview_detail_meta={}
    preview_detail_mode=options.get('preview_detail_level','Detailed') if is_preview_plan(options) and not options.get('_full_detail_preview') else None
    image, fitted = prepare_image(original, area, options['detail'], sample_limit=options.get('planner_sample_limit'), max_pixels=options.get('planner_max_pixels'),
                                  preview_detail_mode=preview_detail_mode,preview_detail_meta=preview_detail_meta,cancelled=cancelled)
    if preview_detail_meta:options['preview_detail_meta']=preview_detail_meta
    from VisibleContrast import enhance_contrast
    with closing(image) as prepared_source:
        image = _own_color_plan_image(enhance_contrast(prepared_source, options['contrast'], cancelled=cancelled))
    profiler_stop(options, 'preprocessing', _prof_pre)
    if options.get('paint_current_color'):
        from PixelData import monochrome_strokes
        _prof_color = profiler_start(options, 'color_planning')
        groups=monochrome_strokes(image,options['lines'],cancelled,
                                  cpu_workers=options.get('cpu_workers_resolved',1),
                                  cpu_engine=options.get('cpu_engine','Auto'),
                                  ram_budget_mb=options.get('ram_budget_mb',512),
                                  preview_plan=is_preview_plan(options))
        profiler_stop(options, 'color_planning', _prof_color)
        return _finalize_auto_tuned_plan(finish_plan(image,fitted,groups,options,cancelled),original,area,cancelled)

    # Paint image RGB must be resolved before Pixel Accurate's early return.
    # A prepared palette also fixes the RGB order used by non-pixel planners.
    picture_plan_colors=tuple(c.RGB for c in allColors)
    picture_selectors=();picture_palette_meta={}
    if str(options.get('draw_quality') or '')=='Pixel Accurate' or options.get('picture_palette_rgb'):
        resolution=resolve_image_custom_color_workflow(
            options.get('profile_name'),options.get('profile_key'),
            options.get('custom_color_workflow','Calibrated palette'),
            render_preset=options.get('render_preset','Auto'))
        if resolution.get('available') and 'exact_color_actions' not in options:
            options['exact_color_available']=True
        if resolution.get('auto_promoted'):
            options['custom_color_workflow']=resolution['workflow']
        from PicturePalettePlanning import resolve_paint_plan_palette
        picture_plan_colors,picture_selectors,picture_palette_meta=resolve_paint_plan_palette(
            original,picture_plan_colors,options,cancelled)

    # v1.0.86 Block A: Pixel Accurate Planner. Build a full-resolution PixelMap
    # before any background simplification, adaptive pruning, reduced palette or
    # browser turbo policy can remove source information. Horizontal same-colour
    # runs are lossless compression of the pixel map, not geometric simplification.
    if str(options.get('draw_quality') or '') == 'Pixel Accurate' and not options.get('outline'):
        from PixelAccuratePlanner import build_pixel_map
        from PixelStrokeEngine import build_pixel_stroke_plan
        # Block B prices the actual selector workflow while ordering components;
        # attach the resolved palette and native Pixel spacing before its
        # cost model is constructed, not only after the schedule is chosen.
        options=dict(options,color_selectors=picture_selectors,pixel_accurate=True)
        _prof_color = profiler_start(options, 'color_planning')
        pixel_map=build_pixel_map(
            image, picture_plan_colors,
            color_rendering=options.get('color_rendering','Perceptual match'),
            color_fidelity='Exact' if picture_selectors else options.get('color_fidelity','Faithful'),
            skip_white=bool(options.get('skip_white',True)),
            gpu_mode=options.get('gpu_mode','Auto'),
            gpu_vram=options.get('gpu_vram','Auto'),
            gpu_performance=options.get('gpu_performance','High throughput'),
            cancelled=cancelled)
        options["_hybrid_scale_x"]=float(fitted[0])/max(1,pixel_map.width)
        options["_hybrid_scale_y"]=float(fitted[1])/max(1,pixel_map.height)
        from SubjectFocus import focused_stroke_plan
        from PixelRegionTopology import PixelRegionTopology
        _pixel_topology=None
        if options.get('subject_focus','Off')=='Off' and bool(options.get('lines',True)):
            try:
                _pixel_topology=PixelRegionTopology(pixel_map)
            except MemoryError:
                if cancelled():raise InterruptedError()
        native_subject_accuracy=None
        try:
            pixel_map,stroke_plan=focused_stroke_plan(
                pixel_map,image,len(picture_plan_colors),options.get('subject_focus','Off'),options.get('subject_region'),lines=bool(options.get('lines',True)),
                cpu_workers=int(options.get('cpu_workers_resolved',1) or 1),options=options,cancelled=cancelled,
                _region_topology=_pixel_topology)
            from AdaptiveBrushEngine import assign_adaptive_brushes
            adaptive_brush=assign_adaptive_brushes(
                stroke_plan['execution_sequence'],profile_key=str(options.get('profile_key') or ''),
                default_brush_px=max(1,int(options.get('brush_px',1) or 1)),
                browser_brush_plan=options.get('browser_brush_plan'))
            stroke_plan['execution_sequence']=adaptive_brush['execution_sequence']
            stroke_plan['metadata']=dict(stroke_plan.get('metadata') or {})
            stroke_plan['metadata']['adaptive_brush']=adaptive_brush['metadata']
            subject_brush_meta=None
            subject_projection=None
            if options.get('subject_focus')=='Subject only':
                from SubjectFocus import clip_subject_brush_sequence
                from NativeBrushProjection import NativeBrushProjection
                subject_projection=NativeBrushProjection.for_scaled_plan(
                    (pixel_map.width,pixel_map.height),fitted,options,cancelled=cancelled)
                stroke_plan['execution_sequence'],subject_brush_meta=clip_subject_brush_sequence(
                    stroke_plan['execution_sequence'],pixel_map.drawable_mask,
                    default_brush_px=max(1,int(options.get('brush_px') or 1)),
                    projection=subject_projection,cancelled=cancelled)
                stroke_plan['metadata']['subject_brush_mask']=subject_brush_meta
                stroke_plan['metadata']['execution_paths']=subject_brush_meta['retained_paths']
                adaptive_brush['metadata']=dict(adaptive_brush['metadata'],
                    **{key:subject_brush_meta[key] for key in ('used_brush_sizes','brush_path_counts',
                        'brush_reason_counts','planned_brush_switches')},
                    geometry_changed=bool(subject_brush_meta['trimmed_source_paths']),subject_mask_constrained=True)
                stroke_plan['metadata']['adaptive_brush']=adaptive_brush['metadata']
            # v1.0.89 Block D: preserve the full Block-B plan, then optionally fit
            # execution to a user timer by phase/importance only. CUDA performs the
            # expensive brush simulation when available; corrections stay inside the
            # same progressive path budget.
            from PixelAccuracyEngine import (PixelScoreContext, refine_with_corrections, execution_groups_from_sequence,
                                             render_coverage_map, render_error_map, progressive_time_budget,
                                             progressive_accuracy_checkpoints)
            progressive_budget=progressive_time_budget(
                stroke_plan['execution_sequence'],active=bool(options.get('time_budget_active')),
                seconds=int(options.get('time_budget_seconds') or options.get('max_seconds') or 600),
                profile_key=str(options.get('profile_key') or ''),
                correction_reserve_ratio=(0 if options.get('subject_focus','Off')!='Off' else .12))
            base_sequence=progressive_budget['execution_sequence']
            if subject_projection is not None:
                from SubjectFocus import evaluate_native_subject_plan
                native_subject_accuracy=evaluate_native_subject_plan(
                    pixel_map,base_sequence,picture_plan_colors,subject_projection,
                    brush_px=max(1,int(options.get('brush_px',1) or 1)),
                    gpu_mode=options.get('gpu_mode','Auto'),gpu_vram=options.get('gpu_vram','Auto'),
                    gpu_performance=options.get('gpu_performance','High throughput'),cancelled=cancelled)
                # Evaluation uses native pixels; execution keeps its source
                # coordinates so CanvasTransform applies the physical mapping once.
                accuracy_plan={'execution_sequence':base_sequence,
                               'metadata':native_subject_accuracy['metadata']}
            else:
                _pixel_score_context=PixelScoreContext(pixel_map)
                accuracy_plan=refine_with_corrections(
                    pixel_map,base_sequence,picture_plan_colors,
                    brush_px=max(1,int(options.get('brush_px',1) or 1)),max_passes=(0 if options.get('subject_focus','Off')!='Off' else 2),
                    correction_brush_px=int(adaptive_brush['metadata'].get('detail_brush_px',options.get('brush_px',1)) or 1),
                    max_total_paths=(progressive_budget.get('path_budget') if progressive_budget.get('active') else None),
                    gpu_mode=options.get('gpu_mode','Auto'),gpu_vram=options.get('gpu_vram','Auto'),
                    gpu_performance=options.get('gpu_performance','High throughput'),cancelled=cancelled,
                    score_context=_pixel_score_context,_region_topology=_pixel_topology)
            if _pixel_topology is not None:_pixel_topology.close()
            stroke_plan['execution_sequence']=accuracy_plan['execution_sequence']
            stroke_plan['execution_groups']=execution_groups_from_sequence(
                stroke_plan['execution_sequence'],len(picture_plan_colors))
            groups=stroke_plan['groups']
            plan_options=dict(options)
            plan_options['pixel_accurate']=True
            plan_options['color_selectors']=picture_selectors
            plan_options['picture_palette_meta']=picture_palette_meta
            plan_options['pixel_map_meta']=pixel_map.as_meta()
            plan_options['plan_palette_rgb']=picture_plan_colors
            # Preserve a distinct quantized-target object for diagnostics/accuracy
            # separation. This is not used to choose colors or alter stroke planning.
            try:
                import numpy as np
                _pal_np=np.asarray(plan_options['plan_palette_rgb'],dtype=np.uint8)
                _idx=np.asarray(pixel_map.palette_index,dtype=np.int32)
                _drawable=np.asarray(pixel_map.drawable_mask,dtype=bool)
                _target_rgb=np.full((pixel_map.height,pixel_map.width,3),255,dtype=np.uint8)
                if _pal_np.ndim==2 and len(_pal_np):
                    _safe_idx=np.clip(_idx,0,len(_pal_np)-1)
                    _target_rgb[_drawable]=_pal_np[_safe_idx[_drawable]]
                    plan_options['_accuracy_quantized_target']=_own_color_plan_image(Image.fromarray(_target_rgb,'RGB'))
                    plan_options['_accuracy_quantized_target_available']=True
            except Exception:
                plan_options['_accuracy_quantized_target_available']=False
            plan_options['adaptive_detail_effective']='Off'
            plan_options['adaptive_detail_meta']={
                'adaptive_detail_requested':'Off','adaptive_detail_effective':'Off',
                'adaptive_detail_pruned_micro_strokes':0,'adaptive_detail_pruned_micro_pixels':0,
                'protected_pixels':int(pixel_map.as_meta().get('protected_pixels',0))}
            plan_options['background_simplification_meta']={
                'requested':'Off','effective':'Off','pixel_accurate_bypass':True}
            plan_options['advanced_color_meta']={
                'mode':'pixel-accurate-map','backend':pixel_map.metadata.get('palette_backend','cpu-numpy'),
                'edge_backend':pixel_map.metadata.get('edge_backend','cpu-numpy'),
                'full_resolution':True,'destructive_simplification':False}
            # v1.0.87 Block B supplies exact component-aware execution paths and a
            # four-pass sequence. These runtime-only fields are consumed by
            # finish_plan; they never enter saved settings or mouse calibration.
            plan_options['_pixel_execution_groups']=stroke_plan['execution_groups']
            plan_options['_pixel_execution_sequence']=stroke_plan['execution_sequence']
            plan_options['pixel_stroke_meta']=stroke_plan['metadata']
            plan_options['pixel_stroke_engine']='Block B + C + D + Shadow/Contour + Adaptive Brush v2'
            if native_subject_accuracy is not None:
                checkpoints=native_subject_accuracy['checkpoints']
            else:
                checkpoints=progressive_accuracy_checkpoints(
                    pixel_map,stroke_plan['execution_sequence'],picture_plan_colors,
                    brush_px=max(1,int(options.get('brush_px',1) or 1)),cancelled=cancelled,
                    score_context=_pixel_score_context)
                del _pixel_score_context
            accuracy_meta=dict(accuracy_plan['metadata'])
            if subject_brush_meta is not None:
                accuracy_meta['subject_brush_mask']=dict(subject_brush_meta,
                    missing_subject_pixels=int(accuracy_meta.get('missing_pixels',0)),
                    subject_coverage_percent=float(accuracy_meta.get('coverage_percent',0)))
            accuracy_meta['progressive_time_budget']={k:v for k,v in progressive_budget.items() if k!='execution_sequence'}
            accuracy_meta['accuracy_checkpoints']=checkpoints
            accuracy_meta['block_d']=True
            if options.get('subject_focus','Off')!='Off':
                accuracy_meta['automatic_corrections']=False
                accuracy_meta['correction_note']='Subject focus preserves the available brush width; Subject only clips its footprint to the selection. Correction passes are disabled to avoid restoring intentionally omitted background.'
            accuracy_meta['adaptive_brush']=adaptive_brush['metadata']
            accuracy_meta['draw_motor']='Adaptive Brush Draw Motor v2'
            plan_options['pixel_accuracy_meta']=accuracy_meta
            if native_subject_accuracy is not None:
                plan_options['_pixel_coverage_preview']=native_subject_accuracy['coverage_preview']
                plan_options['_pixel_error_preview']=native_subject_accuracy['error_preview']
            else:
                plan_options['_pixel_coverage_preview']=_own_color_plan_image(render_coverage_map(pixel_map,accuracy_plan['simulation']))
                plan_options['_pixel_error_preview']=_own_color_plan_image(render_error_map(pixel_map,accuracy_plan['simulation']))
            plan_options['color_workflow']='Progressive passes'
            plan_options['progressive_rendering']='On'
            plan_options['target_stroke_count_resolved']=None
            plan_options['stroke_optimizer']='Travel only'
            plan_options['color_grouping']='Accurate'
            plan_options.pop('real_speed_budget_meta',None)
            if bool(options.get('use_region_fill_engine',True)):
                plan_options['region_fill_meta']={
                    'enabled':True,'engine_name':'Region Fill Engine','quality_preset':'Pixel Accurate',
                    'fill_aggressiveness':'Safe','pixel_accurate_protected':True,
                    'reason':'Exact Pixel Accurate stroke simulation preserved; bucket substitution is disabled until the simulator can prove exact fill equivalence.',
                    'total_regions':int(stroke_plan.get('metadata',{}).get('component_count',0) or 0),
                    'fill_safe_regions':0,'fill_actions':0,'outline_paths':0,
                    'fallback_stroke_regions':int(stroke_plan.get('metadata',{}).get('component_count',0) or 0),
                    'fill_coverage_percent':0.0,'stroke_reduction_percent':0.0,'estimated_time_saved_seconds':0.0}
            profiler_stop(plan_options,'color_planning',_prof_color)
            return _finalize_auto_tuned_plan(finish_plan(image,fitted,groups,plan_options,cancelled),original,area,cancelled)
        except BaseException as failure:
            # These native diagnostics are owned by this in-progress plan.
            # A failed finish/finalization must not retain their pixel cores
            # through a worker exception traceback. Successful plans retain them.
            if native_subject_accuracy is not None:
                for key in ('coverage_preview','error_preview'):
                    try:native_subject_accuracy[key].close()
                    except Exception as cleanup_error:
                        failure.add_note(f'Subject diagnostic cleanup also failed: {type(cleanup_error).__name__}.')
            raise
        finally:
            if _pixel_topology is not None:_pixel_topology.close()

    plan_options=dict(options)
    _prof_color = profiler_start(plan_options, 'color_planning')
    # RGB is already composited on white for matching and smoothing. Retain
    # only the zero-alpha drawable mask afterwards; restoring partial alpha
    # would composite those visible colours a second time and wash them out.
    with closing(image.getchannel('A')) as alpha:
        source_has_transparency = alpha.getextrema()[0] == 0
        with closing(image) as rgba_source, closing(Image.new('RGBA',image.size,'white')) as backdrop:
            backdrop.alpha_composite(rgba_source)
            palette_image=backdrop.convert('RGB')

        adaptive_mask=None
        adaptive_stats=None
        adaptive_mode=options.get('adaptive_detail','Auto')
        if adaptive_mode!='Off' and not options.get('outline'):
            with closing(palette_image), closing(palette_image.convert('RGBA')) as adaptive_source:
                adaptive_rgba,adaptive_mask,adaptive_stats=apply_adaptive_detail(
                    adaptive_source,adaptive_mode,
                    subject_focus=bool(options.get('portrait_focus',False)),
                    drawing_mode=options.get('drawing_mode'),preview=is_preview_plan(options),cancelled=cancelled)
                _own_color_plan_image(adaptive_mask)
            with closing(adaptive_rgba):palette_image=adaptive_rgba.convert('RGB')
            plan_options['adaptive_detail_meta']=adaptive_stats.as_dict()
            plan_options['adaptive_detail_effective']=adaptive_stats.effective_mode
        elif adaptive_mode=='Off':
            plan_options['adaptive_detail_meta']={'adaptive_detail_requested':'Off','adaptive_detail_effective':'Off',
                                                 'adaptive_detail_pruned_micro_strokes':0,'adaptive_detail_pruned_micro_pixels':0}
            plan_options['adaptive_detail_effective']='Off'

        simplification_mode=options.get('background_simplification','Balanced')
        with closing(palette_image) as unsimplified:
            palette_image,simplification=simplify_background(unsimplified,simplification_mode,cancelled=cancelled)
        plan_options['background_simplification_meta']=simplification.as_dict()
        with closing(palette_image):
            image=_own_color_plan_image(palette_image.convert('RGBA'))
        if source_has_transparency:
            with closing(alpha.point([0]+[255]*255)) as drawable_alpha:
                image.putalpha(drawable_alpha)
    plan_options['source_transparency_meta']={'zero_alpha_excluded':source_has_transparency}
    if source_has_transparency:
        plan_options.pop('background_fill_plan',None)
        plan_options.pop('fill_regions',None)

    fill_plan=None;fill_regions=[]
    fill_mode=options.get('background_fill','Balanced')
    safe_fill_margin=source_fill_margin_px(options.get('brush_px',3),2,image.size)
    plan_options['safe_fill_mask_margin_px']=safe_fill_margin
    region_fill_enabled=bool(options.get('use_region_fill_engine',fill_mode!='Off'))
    if (fill_mode!='Off' or region_fill_enabled) and options.get('fill_tool_available') and not options.get('outline'):
        fill_plan=detect_background(image,fill_mode,safe_margin_px=safe_fill_margin) if fill_mode!='Off' and not source_has_transparency else None
        if options.get('extra_fast'):
            # Extra fast only fills bounded interior regions, never the whole canvas.
            fill_plan=None
        if fill_plan is not None and fill_plan.enabled:
            bg_dict=fill_plan.as_dict();bg_dict['safe_fill_mask']=True;bg_dict['safe_fill_margin_px']=safe_fill_margin
            plan_options['background_fill_plan']=bg_dict
        # v1.0.117 Region Fill Engine: keep the existing conservative connected-
        # component detector as the topology authority, then add leak-risk and
        # wall-clock cost analysis. Unsafe or slower regions automatically remain
        # in the normal stroke/run renderer. Preview and final execution consume
        # the exact same accepted region dictionaries.
        if region_fill_enabled:
            from RegionFillEngine import build_region_fill_plan
            fill_region_dicts,fill_region_meta=build_region_fill_plan(
                image,fitted,options,safe_margin_px=safe_fill_margin,cancelled=cancelled)
            plan_options['region_fill_meta']=dict(fill_region_meta)
        else:
            fill_regions,fill_region_meta=detect_fill_regions(
                image,fill_mode,engine=options.get('fill_engine','Auto'),
                cancelled=cancelled,return_meta=True,safe_margin_px=safe_fill_margin)
            fill_region_dicts=[region.as_dict() for region in fill_regions]
        fill_region_dicts,safe_fill_meta=filter_fill_regions_by_source_mask(
            fill_region_dicts,image.size,margin_px=safe_fill_margin)
        if source_has_transparency:
            from SafeFillMask import filter_fill_regions_by_source_alpha
            fill_region_dicts,safe_fill_meta=filter_fill_regions_by_source_alpha(
                fill_region_dicts,image,metadata=safe_fill_meta,cancelled=cancelled)
        if options.get('extra_fast'):
            from ExtraFast import select_fast_regions
            fill_region_dicts,fast_meta=select_fast_regions(fill_region_dicts,image.size,fitted,options,cancelled)
            plan_options['extra_fast_meta']=fast_meta
        fill_region_meta=dict(fill_region_meta);fill_region_meta['safe_fill_mask']=safe_fill_meta
        fill_region_meta['accepted_regions']=len(fill_region_dicts)
        fill_region_meta['fallback_scanline_regions']=int(fill_region_meta.get('fallback_scanline_regions',0))+int(safe_fill_meta.get('rejected_regions',0))
        if isinstance(plan_options.get('region_fill_meta'),dict):
            rmeta=dict(plan_options['region_fill_meta'])
            rejected_runtime=int(safe_fill_meta.get('rejected_regions',0) or 0)
            rmeta['fill_safe_regions']=len(fill_region_dicts)
            rmeta['fill_actions']=len(fill_region_dicts)
            rmeta['outline_paths']=len(fill_region_dicts)
            rmeta['source_mask_rejections']=rejected_runtime
            rmeta['fallback_stroke_regions']=int(rmeta.get('fallback_stroke_regions',0) or 0)+rejected_runtime
            plan_options['region_fill_meta']=rmeta
        plan_options['fill_engine_meta']=fill_region_meta
        if fill_region_dicts:
            plan_options['fill_regions']=fill_region_dicts

    # A non-white Fill can cover white/highlight holes, so white correction
    # strokes are kept whenever any bucket operation is planned.
    planner_skip_white=options['skip_white']
    needs_white_correction=(fill_plan is not None and fill_plan.enabled) or any(float(region.get('bbox_density',1.0)) < .9999 for region in (plan_options.get('fill_regions') or []))
    if needs_white_correction:
        planner_skip_white=False
    color_rendering=options.get('color_rendering','Perceptual match')
    color_fidelity=options.get('color_fidelity','Faithful')
    color_layers=options.get('color_layers','Off')
    custom_color_workflow=options.get('custom_color_workflow','Calibrated palette')
    # Paint-only: an older saved profile may still say Calibrated palette even
    # though Edit colors was calibrated later. Auto presets now discover that
    # capability from profile-local calibration and use image-driven Adaptive
    # exact planning. Manual preset deliberately preserves palette-only intent.
    custom_resolution=resolve_image_custom_color_workflow(
        options.get('profile_name'), options.get('profile_key'), custom_color_workflow,
        render_preset=options.get('render_preset','Auto'))
    custom_color_workflow=custom_resolution['workflow']
    if custom_resolution.get('available'):
        plan_options['exact_color_available']=True
    if custom_resolution.get('auto_promoted'):
        plan_options['custom_color_workflow']=custom_color_workflow
        plan_options['custom_color_auto_meta']=dict(custom_resolution)
    dynamic_exact=bool(picture_selectors) or (custom_color_workflow in ('Exact custom + palette fallback','Adaptive exact (recommended)'))
    if dynamic_exact:
        # Exact-color planning is bounded: cluster the image into a useful number
        # of colors. Each cluster uses exact RGB when calibrated; otherwise it
        # *always* resolves to the nearest actually calibrated palette swatch.
        exact_limit_setting=str(options.get('exact_color_limit','Auto'))
        if exact_limit_setting=='Auto':
            # Step 5: Auto is now image-complexity aware.  The existing Draw
            # Quality resolver remains the hard ceiling; Step 5 only decides how
            # much of that ceiling the current image actually deserves.  Preview
            # and final planning intentionally share the same recommendation so
            # the preview does not silently use the old 8-color approximation.
            color_count_ceiling=resolve_exact_color_limit(
                'Auto',draw_quality=options.get('draw_quality','High likeness'),preview=False)
            try:
                _profile_color_ceiling=int(options.get('exact_color_limit_profile_ceiling'))
            except (TypeError,ValueError):
                _profile_color_ceiling=None
            if _profile_color_ceiling is not None:
                color_count_ceiling=max(2,_profile_color_ceiling)
            color_count_source=options.get('_accuracy_original_source') if hasattr(options.get('_accuracy_original_source'), 'size') else original
            limit,adaptive_color_count_meta=recommend_adaptive_color_count(
                color_count_source,ceiling=color_count_ceiling,fidelity=str(color_fidelity or 'Faithful'),
                preview=is_preview_plan(options),cancelled=cancelled)
            # Step 6: compose the image-driven Step 5 recommendation with the
            # *usable* active deadline and real/measured color-switch cost.
            # Numeric user limits bypass this path entirely.
            limit,adaptive_color_count_meta=apply_time_aware_color_budget(
                limit,adaptive_color_count_meta,options,preview=is_preview_plan(options))
        else:
            limit=resolve_exact_color_limit(
                exact_limit_setting,draw_quality=options.get('draw_quality','High likeness'),preview=is_preview_plan(options))
            adaptive_color_count_meta={
                'active':False,'policy':'manual','requested':exact_limit_setting,
                'recommended_colors':int(limit),'ceiling_colors':int(limit),
                'time_budget_applied':False,'stop_reason':'explicit-user-limit',
            }
        plan_options['exact_color_limit_resolved']=int(limit)
        plan_options['adaptive_color_count_meta']=dict(adaptive_color_count_meta)
        if picture_selectors:
            from PicturePalettePlanning import build_prepared_color_strokes
            groups,plan_colors,selectors,color_render_meta=build_prepared_color_strokes(
                image,picture_plan_colors,picture_selectors,options,skip_white=planner_skip_white,cancelled=cancelled)
            plan_options['picture_palette_meta']=picture_palette_meta
            limit=len(picture_plan_colors)
            plan_options['exact_color_limit_resolved']=limit
            adaptive_color_count_meta={'active':False,'policy':'prepared-picture-palette','recommended_colors':limit}
        else:
            groups,plan_colors,selectors,color_render_meta=build_dynamic_color_strokes(
                image,tuple(c.RGB for c in allColors),max_colors=limit,skip_white=planner_skip_white,
                lines=options['lines'],exact_available=bool(plan_options.get('exact_color_available')),
                color_fidelity=str(options.get('color_fidelity','Faithful')),profile_name=str(options.get('profile_name') or ''),
                protected_mask=adaptive_mask,cancelled=cancelled)
        if groups is None:raise InterruptedError()
        if adaptive_mask is not None and options.get('lines',True):
            groups,prune_meta=prune_flat_micro_strokes(groups,adaptive_mask,
                plan_options.get('adaptive_detail_effective','Off'),cancelled=cancelled)
            meta=dict(plan_options.get('adaptive_detail_meta') or {});meta.update(prune_meta);plan_options['adaptive_detail_meta']=meta
        plan_options['plan_palette_rgb']=tuple(plan_colors)
        plan_options['color_selectors']=tuple(selectors)
        color_render_meta=dict(color_render_meta or {})
        color_render_meta['adaptive_color_count']=dict(adaptive_color_count_meta)
        color_render_meta['requested_exact_color_limit']=exact_limit_setting
        color_render_meta['resolved_exact_color_limit']=int(limit)
        plan_options['advanced_color_meta']=color_render_meta
        # Quick Sketch/Extra Fast can safely recover outline+Fill even for
        # Dynamic/Adaptive Exact colors because region indexes refer to the
        # plan-local palette. Quick Sketch additionally adds a simplified dark
        # visible contour after the safe Fill pass.
        plan_options.pop('background_fill_plan',None)
        if is_quick_sketch(plan_options):
            try:
                groups,_quick_regions,_quick_meta=build_quick_sketch_geometry(
                    image.size,groups,plan_colors,fitted,plan_options,cancelled=cancelled)
                plan_options['fill_regions']=list(_quick_regions)
                plan_options['quick_sketch_meta']=dict(_quick_meta or {})
                _qregion=dict((_quick_meta or {}).get('fill_safety') or {})
                _qregion.update({
                    'enabled':True,'engine_name':'Quick Sketch Fill + Contour',
                    'quality_preset':'Quick Sketch','fill_aggressiveness':plan_options.get('fill_aggressiveness','Balanced'),
                    'fill_safe_regions':len(_quick_regions),'fill_actions':len(_quick_regions),
                    'outline_paths':len(_quick_regions),'fill_coverage_percent':float((_quick_meta or {}).get('fill_coverage_percent',0) or 0),
                    'fallback_stroke_regions':int((_quick_meta or {}).get('fallback_scanline_regions',0) or 0),
                    'fallback_render_method':'CONNECTED_SCANLINES'})
                plan_options['region_fill_meta']=_qregion
                plan_options['fill_engine_meta']=dict((_quick_meta or {}).get('fill_detector') or {})
            except InterruptedError:
                raise
            except Exception as _quick_error:
                log_event(f'Quick Sketch dynamic fill fallback to connected scanlines: {_quick_error!r}')
                plan_options['fill_regions']=[]
                plan_options['quick_sketch_meta']={'enabled':True,'engine':'Quick Sketch Fill + Contour','fill_regions':0,'reason':str(_quick_error),'fallback_scanline_regions':1}
        elif options.get('extra_fast') and options.get('fill_tool_available') and options.get('lines',True):
            try:
                from FillOptimizer import detect_fill_regions_from_groups
                from RegionFillEngine import evaluate_region_candidates
                from ExtraFast import select_fast_regions
                _dyn_candidates,_dyn_base=detect_fill_regions_from_groups(
                    groups,plan_colors,image.size,'Balanced',engine=options.get('fill_engine','Closed regions v2'),
                    max_regions=384,cancelled=cancelled,return_meta=True,safe_margin_px=safe_fill_margin)
                _dyn_regions,_dyn_meta=evaluate_region_candidates(
                    _dyn_candidates,image.size,fitted,options,base_meta=_dyn_base,cancelled=cancelled)
                _dyn_regions,_dyn_mask=filter_fill_regions_by_source_mask(
                    _dyn_regions,image.size,margin_px=safe_fill_margin)
                if source_has_transparency:
                    from SafeFillMask import filter_fill_regions_by_source_alpha
                    _dyn_regions,_dyn_mask=filter_fill_regions_by_source_alpha(
                        _dyn_regions,image,metadata=_dyn_mask,cancelled=cancelled)
                _dyn_regions,_dyn_fast=select_fast_regions(
                    _dyn_regions,image.size,fitted,options,cancelled)
                _dyn_meta=dict(_dyn_meta);_dyn_meta.update({
                    'dynamic_exact_supported':True,'plan_local_color_indexes':True,
                    'fill_safe_regions':len(_dyn_regions),'fill_actions':len(_dyn_regions),'outline_paths':len(_dyn_regions),
                    'source_mask_rejections':int(_dyn_mask.get('rejected_regions',0) or 0) if isinstance(_dyn_mask,dict) else 0,
                    'fallback_render_method':'CONNECTED_SCANLINES'})
                plan_options['region_fill_meta']=_dyn_meta
                plan_options['extra_fast_meta']=dict(_dyn_fast)
                plan_options['fill_engine_meta']=dict(_dyn_base)
                plan_options['fill_regions']=list(_dyn_regions)
                if _dyn_regions:
                    groups=remove_filled_region_strokes(groups,_dyn_regions)
                if options.get('skip_white'):
                    # planner_skip_white may have been disabled earlier because a
                    # Fill was anticipated. Keep only local white repair inside
                    # accepted fill bounds; never scanline-paint the whole white
                    # background in Extra Fast 2.0.
                    from FillOptimizer import restrict_white_corrections
                    groups=restrict_white_corrections(groups,tuple(plan_colors),_dyn_regions)
            except InterruptedError:
                raise
            except Exception as _dynamic_fill_error:
                log_event(f'Extra Fast 2.0 dynamic fill fallback to connected scanlines: {_dynamic_fill_error!r}')
                plan_options['fill_regions']=[]
                plan_options['region_fill_meta']={'enabled':True,'engine_name':'Extra Fast 2.0','fill_safe_regions':0,'fill_actions':0,
                    'outline_paths':0,'fill_coverage_percent':0.0,'estimated_time_saved_seconds':0.0,
                    'fallback_render_method':'CONNECTED_SCANLINES','reason':str(_dynamic_fill_error)}
        else:
            plan_options['fill_regions']=[]
            if isinstance(plan_options.get('region_fill_meta'),dict):
                rmeta=dict(plan_options['region_fill_meta'])
                rmeta.update({'fill_safe_regions':0,'fill_actions':0,'outline_paths':0,
                              'fill_coverage_percent':0.0,'stroke_reduction_percent':0.0,
                              'estimated_time_saved_seconds':0.0,
                              'reason':'Region Fill disabled for mixed dynamic/custom RGB selector plans outside Extra Fast 2.0.'})
                plan_options['region_fill_meta']=rmeta
        grouping_mode=options.get('color_grouping','Smart')
        if bool(plan_options.get('exact_color_available')) and grouping_mode=='Reduced palette':
            # Exact custom RGB means exact: do not silently merge two selected
            # custom colors just because the speed profile requested reduction.
            grouping_mode='Smart'
        groups,color_order,color_meta=group_palette_strokes(groups,tuple(plan_colors),grouping_mode,color_fidelity=str(options.get('color_fidelity','Faithful')))
        color_meta=dict(color_meta);color_meta['requested_mode']=options.get('color_grouping','Smart')
        plan_options['color_order']=color_order;plan_options['color_grouping_meta']=color_meta
        profiler_stop(plan_options,'color_planning',_prof_color)
        return _finalize_auto_tuned_plan(finish_plan(image,fitted,groups,plan_options,cancelled),original,area,cancelled)
    if color_rendering=='RGB nearest' and color_fidelity=='Fast' and color_layers=='Off' and custom_color_workflow=='Calibrated palette' and options.get('gpu_mode','CPU')=='CPU':
        groups = build_strokes(image, options['lines'], planner_skip_white, cancelled,
                                cpu_workers=options.get('cpu_workers_resolved',1),
                                cpu_engine=options.get('cpu_engine','Auto'),
                                ram_budget_mb=options.get('ram_budget_mb',512),
                                preview_plan=is_preview_plan(options))
        color_render_meta={'color_rendering':'RGB nearest','color_fidelity':'Fast','color_layers':'Off','custom_color_workflow':'Calibrated palette','layered_pixels':0,'base_colors':sum(bool(g) for g in groups) if groups else 0,'overlay_colors':0,'cpu_backend':'parallel' if options.get('cpu_workers_resolved',1)>1 else 'serial','cpu_chunks':0}
    else:
        groups, color_render_meta = build_color_strokes(
            image, lines=options['lines'], skip_white=planner_skip_white,
            color_rendering=color_rendering, color_layers=color_layers,
            custom_color_workflow=custom_color_workflow, color_fidelity=color_fidelity, cancelled=cancelled,
            cpu_workers=options.get('cpu_workers_resolved',1),
            cpu_engine=options.get('cpu_engine','Auto'),
            ram_budget_mb=options.get('ram_budget_mb',512),
            preview_plan=is_preview_plan(options),
            gpu_mode=options.get('gpu_mode','CPU'),
            gpu_vram=options.get('gpu_vram','Auto'),
            gpu_performance=options.get('gpu_performance','Balanced'))
    if groups is None:
        raise InterruptedError()
    if options['skip_white'] and needs_white_correction and not (fill_plan is not None and fill_plan.enabled):
        from FillOptimizer import restrict_white_corrections
        groups=restrict_white_corrections(groups,tuple(c.RGB for c in allColors),plan_options.get('fill_regions') or [])

    # v1.0.77: under a measured browser time budget, deliberately merge rare
    # colors before path building. This preserves the darkest structural color
    # and reduces expensive palette switches. Dedicated Gartic/Skribbl Turbo
    # may reduce further afterwards.
    real_speed_color_meta=None
    if (not is_quick_sketch(plan_options)) and options.get('real_speed_max_colors') and str(options.get('profile_key') or '') in ('gartic-phone','skribbl','skribbl-fast','sketchheads','sketchful'):
        try:
            from RealSpeedBudget import reduce_palette_groups
            groups,real_speed_color_meta=reduce_palette_groups(groups,tuple(c.RGB for c in allColors),int(options.get('real_speed_max_colors')),color_fidelity=str(options.get('color_fidelity','Faithful')))
            plan_options['real_speed_color_meta']=real_speed_color_meta
        except Exception as error:
            log_event(f'Real-Speed palette reduction skipped: {error!r}')
    if adaptive_mask is not None and options.get('lines',True):
        groups,prune_meta=prune_flat_micro_strokes(groups,adaptive_mask,
            plan_options.get('adaptive_detail_effective','Off'),cancelled=cancelled)
        meta=dict(plan_options.get('adaptive_detail_meta') or {});meta.update(prune_meta);plan_options['adaptive_detail_meta']=meta

    _quick_sketch_active=is_quick_sketch(plan_options)
    if _quick_sketch_active:
        try:
            _fixed_palette=tuple(c.RGB for c in allColors)
            groups,_quick_regions,_quick_meta=build_quick_sketch_geometry(
                image.size,groups,_fixed_palette,fitted,plan_options,cancelled=cancelled)
            plan_options['fill_regions']=list(_quick_regions)
            plan_options['quick_sketch_meta']=dict(_quick_meta or {})
            _qregion=dict((_quick_meta or {}).get('fill_safety') or {})
            _qregion.update({
                'enabled':True,'engine_name':'Quick Sketch Fill + Contour',
                'quality_preset':'Quick Sketch','fill_aggressiveness':plan_options.get('fill_aggressiveness','Balanced'),
                'fill_safe_regions':len(_quick_regions),'fill_actions':len(_quick_regions),
                'outline_paths':len(_quick_regions),'fill_coverage_percent':float((_quick_meta or {}).get('fill_coverage_percent',0) or 0),
                'fallback_stroke_regions':int((_quick_meta or {}).get('fallback_scanline_regions',0) or 0),
                'fallback_render_method':'CONNECTED_SCANLINES'})
            plan_options['region_fill_meta']=_qregion
            plan_options['fill_engine_meta']=dict((_quick_meta or {}).get('fill_detector') or {})
            plan_options.pop('background_fill_plan',None)
        except InterruptedError:
            raise
        except Exception as _quick_error:
            log_event(f'Quick Sketch fixed-palette fallback to connected scanlines: {_quick_error!r}')
            plan_options['fill_regions']=[]
            plan_options['quick_sketch_meta']={'enabled':True,'engine':'Quick Sketch Fill + Contour','fill_regions':0,'reason':str(_quick_error),'fallback_scanline_regions':1}

    # v1.0.64: Skribbl Fast gets a dedicated fixed-palette run compressor.
    # It mirrors the classic fast autodraw strategy: one calibrated colour batch
    # at a time, long horizontal runs instead of pixel-sized strokes, and no
    # custom-colour modal workflow. Paint and all other profiles are untouched.
    if (not _quick_sketch_active and str(options.get('profile_name') or '') == 'Skribbl.io Fast' and options.get('lines', True) and str(options.get('profile_engine') or 'Auto') != 'Manual settings'):
        groups, skribbl_fast_meta = optimize_skribbl_groups(
            groups, tuple(c.RGB for c in allColors),
            max_colors=int(options.get('skribbl_fast_max_colors', 6) or 6),
            gap_join=0 if source_has_transparency else int(options.get('skribbl_fast_gap_join', 1) or 1),
            min_run=int(options.get('skribbl_fast_min_run', 2) or 2),
            color_fidelity=str(options.get('color_fidelity','Balanced')))
        plan_options['skribbl_fast_meta'] = skribbl_fast_meta
        plan_options['skribbl_fast_direct_paths'] = True
        # Browser canvases tolerate wider cursor interpolation than Paint. This
        # cuts native move events substantially while keeping exact endpoints.
        plan_options['stroke_step_px'] = max(float(plan_options.get('stroke_step_px', 8) or 8), 12.0)

    # v1.0.65: Gartic Phone gets the same fixed-palette batching idea but
    # with a dual-axis raster optimizer. The classic Gartic bot uses vertical
    # column runs while Skribbl-style bots use horizontal rows; choosing the
    # cheaper orientation per colour reduces press/release boundaries further.
    if (not _quick_sketch_active and str(options.get('profile_name') or '') == 'Gartic Phone' and options.get('lines', True) and str(options.get('profile_engine') or 'Auto') != 'Manual settings'):
        runtime_profile = choose_runtime_profile(
            options.get('time_left_seconds'),
            canvas_size=plan_options.get('area') or fitted,
            requested_speed=options.get('speed', 'Fast'))
        groups, gartic_fast_meta = optimize_gartic_phone_groups(
            groups, tuple(c.RGB for c in allColors),
            max_colors=int(options.get('gartic_phone_max_colors', runtime_profile.max_colors) or runtime_profile.max_colors),
            gap_join=0 if source_has_transparency else int(options.get('gartic_phone_gap_join', 1) or 1),
            min_run=int(options.get('gartic_phone_min_run', 2) or 2),
            color_fidelity=str(options.get('color_fidelity','Faithful')))
        gartic_fast_meta = dict(gartic_fast_meta)
        gartic_fast_meta['engine_v2_runtime'] = runtime_profile.as_options()
        plan_options['gartic_phone_fast_meta'] = gartic_fast_meta
        plan_options['gartic_phone_direct_paths'] = True
        plan_options['target_stroke_count_resolved'] = min(
            int(plan_options.get('target_stroke_count_resolved') or runtime_profile.max_paths),
            runtime_profile.max_paths)
        # Gartic Phone is an HTML5 canvas. Engine v2 uses fewer browser events
        # than Paint while keeping exact endpoints. Time-critical profiles widen
        # interpolation automatically.
        plan_options['stroke_step_px'] = max(float(plan_options.get('stroke_step_px', 8) or 8), runtime_profile.stroke_step_px)

    plan_options['advanced_color_meta']=color_render_meta
    if fill_plan is not None and fill_plan.enabled and fill_plan.color_index is not None:
        idx=int(fill_plan.color_index)
        if 0<=idx<len(groups):
            groups[idx]=[]
    if plan_options.get('fill_regions'):
        groups=remove_filled_region_strokes(groups,plan_options.get('fill_regions') or [])

    # Smart color grouping never changes RGB by default: it schedules large
    # color masses first and small detail colors later. Reduced palette is the
    # only mode allowed to merge very close, rare palette colors.
    grouping_mode = options.get('color_grouping','Smart')
    # Gartic Phone Turbo has already performed its deliberate palette reduction.
    # A second merge here could move vertical runs into a group whose orientation
    # metadata says horizontal, so keep the post-Turbo stage scheduling-only.
    if plan_options.get('gartic_phone_direct_paths'):
        grouping_mode = 'Smart'
    groups,color_order,color_meta=group_palette_strokes(
        groups,tuple(c.RGB for c in allColors),grouping_mode,color_fidelity=str(options.get('color_fidelity','Faithful')))
    if plan_options.get('gartic_phone_direct_paths'):
        color_meta=dict(color_meta);color_meta['requested_mode']=options.get('color_grouping','Smart');color_meta['turbo_reduced']=True
    plan_options['color_order']=color_order
    plan_options['color_grouping_meta']=color_meta
    profiler_stop(plan_options, 'color_planning', _prof_color)
    return _finalize_auto_tuned_plan(finish_plan(image,fitted,groups,plan_options,cancelled),original,area,cancelled)


def finish_plan(image,fitted,groups,options,cancelled=lambda: False):
    # Presentation allocations have a separate lifetime from the caller's
    # prepared image/geometry. In Sketch Fill the outer scope additionally owns
    # the unpublished colour plan, including a full auto-tuner/rescue result.
    owner=_PlanImageOwner()
    color_owner=_current_plan_image_owner()
    if color_owner is not None:color_owner.capture({'image':image,'options':options})
    plan=failure=None
    try:
        plan=_finish_plan(image,fitted,groups,options,cancelled,owner)
        if color_owner is not None:color_owner.capture(plan)
        return plan
    except BaseException as error:
        failure=error
        raise
    finally:
        owner.close(plan,failure)
        plan=failure=color_owner=None


def _finish_plan(image,fitted,groups,options,cancelled,owner):
    from PIL import Image,ImageDraw
    defer_presentation=bool(options.pop('_sketch_fill_defer_presentation',False))
    tuner=options.get('auto_tuner_meta')
    defer_presentation=(defer_presentation and bool(options.get('_sketch_fill_inner'))
                        and not options.get('sketch_fill_active')
                        and not options.get('_adaptive_hybrid_inner')
                        and not options.get('adaptive_hybrid_active')
                        and str(options.get('detail_zoom') or 'Off')=='Off'
                        and not (isinstance(tuner,dict) and tuner.get('active')))
    _prof_preview = profiler_start(options, 'preview_rendering')
    # Model physical brush width and the same centered coordinates used for drawing.
    scale=1 if options.get('_full_detail_preview') else min(1,1600/max(fitted))
    size=tuple(max(1,round(v*scale)) for v in fitted)
    if options.get('erase_mode'):
        palette_rgb=((190,198,210),)  # preview-only erase mask color
    else:
        palette_rgb=((0,0,0),) if options.get('paint_current_color') else tuple(options.get('plan_palette_rgb') or tuple(c.RGB for c in allColors))
    fill_meta=options.get('background_fill_plan') or {}
    preview_bg='white'
    if fill_meta.get('enabled') and fill_meta.get('color_index') is not None:
        try:preview_bg=palette_rgb[int(fill_meta['color_index'])]
        except (IndexError,TypeError,ValueError):preview_bg='white'
    preview=owner.own(Image.new('RGB',size,preview_bg));draw=owner.drawing(ImageDraw.Draw(preview))
    # Step 10: preserve a palette/quantized target independently from physical
    # brush simulation so the preview can show Original → Target → Final.
    try:
        from PreviewDiagnostics import render_quantized_target
        if not defer_presentation:
            _explicit_target=options.get('_accuracy_quantized_target')
            _quantized_source=owner.own(render_quantized_target(
                image.size,groups,palette_rgb,fill_regions=options.get('fill_regions') or (),
                background_fill_plan=fill_meta,color_order=options.get('color_order'),
                explicit_target=_explicit_target if isinstance(_explicit_target,Image.Image) else None,
                cancelled=cancelled))
            with closing(_quantized_source):
                options['_preview_quantized_target']=owner.own(_quantized_source.resize(size,Image.Resampling.NEAREST))
            options['_accuracy_quantized_target_available']=True
    except InterruptedError:
        raise
    except Exception as _diag_target_error:
        options['_accuracy_quantized_target_available']=False
        log_event(f'Quantized-target diagnostic skipped safely: {_diag_target_error!r}')
    brush=max(1,round(options.get('brush_px',3)*scale))
    transform=CanvasTransform(image.width,image.height,(fitted[0]*scale,fitted[1]*scale))
    execution_transform=CanvasTransform(image.width,image.height,fitted)
    def point(x,y):return transform.float_point(x,y)
    # Show planned safe interior fills in the preview before the remaining
    # detail strokes are layered on top.  Extra Fast 2.0 renders the exact
    # source row spans for irregular connected regions instead of painting the
    # whole bounding box, keeping Step 1 source-relative accuracy truthful.
    def draw_preview_fills():
        for region in options.get('fill_regions',[]) or []:
            try:
                index=int(region['color_index']);color=palette_rgb[index]
                spans=region.get('row_spans') or ()
                if spans:
                    for raw in spans:
                        y,x0,x1=map(int,raw)
                        p0=point(x0,y);p1=point(x1,y)
                        draw.line((p0[0],p0[1],p1[0],p1[1]),fill=color,width=max(1,round(scale)))
                else:
                    x0,y0,x1,y1=map(int,region['bbox']);p0=point(x0,y0);p1=point(x1,y1)
                    draw.rectangle((p0[0],p0[1],p1[0],p1[1]),fill=color)
            except (KeyError,TypeError,ValueError,IndexError):
                continue
    draw_preview_fills()

    profiler_stop(options, 'preview_rendering', _prof_preview)
    drawing_mode=options.get('drawing_mode')
    if drawing_mode is None:
        # Backwards-compatible plans/tests that only provide the legacy ``lines``
        # flag keep the old execution model exactly.
        drawing_mode=LEGACY_LINE_MODE if options.get('lines',True) else DOT_MODE
    shape_enabled=drawing_mode==SHAPE_PATH_MODE and bool(options.get('lines',True))
    smart_enabled=drawing_mode==SMART_PATH_MODE and bool(options.get('lines',True))
    edge_count=None
    if smart_enabled and options.get('portrait_stats'):
        try:edge_count=int(options['portrait_stats'].get('edge_strokes',0))
        except (TypeError,ValueError,AttributeError):edge_count=0
    _prof_shape = profiler_start(options, 'shape_extraction')
    pixel_prebuilt = options.get('_pixel_execution_groups')
    sketch_fill_prebuilt = options.get('_sketch_fill_execution_groups')
    adaptive_hybrid_prebuilt = options.get('_adaptive_hybrid_execution_groups')
    if pixel_prebuilt is not None:
        # v1.0.87 Block B: the component-aware Pixel Stroke Engine already
        # produced geometry-safe local paths. Do not feed them back through the
        # generic line/shape compressors, which could discard its region/phase
        # boundaries.
        execution_groups=[list(paths) for paths in pixel_prebuilt]
        path_meta=continuous_path_stats(groups,execution_groups)
        path_meta=dict(path_meta)
        stroke_meta=dict(options.get('pixel_stroke_meta') or {})
        path_meta.update({
            'mode':'Pixel Accurate component paths',
            'pixel_component_engine':True,
            'pixel_component_count':int(stroke_meta.get('component_count',0) or 0),
            'pixel_fill_paths':int(stroke_meta.get('fill_paths',0) or 0),
            'pixel_mid_detail_paths':int(stroke_meta.get('mid_detail_paths',0) or 0),
            'pixel_fine_detail_paths':int(stroke_meta.get('fine_detail_paths',0) or 0),
            'pixel_cleanup_paths':int(stroke_meta.get('cleanup_paths',0) or 0),
            'pixel_safe_merge_fallbacks':int(stroke_meta.get('safe_merge_fallbacks',0) or 0),
            'pixel_accuracy_percent':float((options.get('pixel_accuracy_meta') or {}).get('final_accuracy_percent',0) or 0),
            'pixel_coverage_percent':float((options.get('pixel_accuracy_meta') or {}).get('coverage_percent',0) or 0),
            'pixel_error_pixels':int((options.get('pixel_accuracy_meta') or {}).get('final_error_pixels',0) or 0),
            'pixel_correction_paths':int((options.get('pixel_accuracy_meta') or {}).get('correction_paths_added',0) or 0),
            'stroke_optimizer_requested':options.get('stroke_optimizer','Travel only'),
            'stroke_optimizer_effective':'Component-safe scheduler',
            'optimizer_merged_paths':max(0,int(stroke_meta.get('source_horizontal_runs',0) or 0)-sum(len(g) for g in execution_groups)),
            'optimizer_travel_reduction':0.0,
        })
    elif sketch_fill_prebuilt is not None:
        execution_groups=[list(paths) for paths in sketch_fill_prebuilt]
        path_meta=dict(continuous_path_stats(groups,execution_groups))
        path_meta.update(options.get('sketch_fill_meta') or {})
        path_meta['mode']='Sketch + Auto Fill'
        path_meta['sketch_fill']=True
        path_meta['stroke_optimizer_requested']='Off'
        path_meta['stroke_optimizer_effective']='Sketch Fill phase scheduler'
    elif adaptive_hybrid_prebuilt is not None:
        execution_groups=[list(paths) for paths in adaptive_hybrid_prebuilt]
        path_meta=dict(continuous_path_stats(groups,execution_groups))
        _ah=dict(options.get('adaptive_hybrid_meta') or {})
        _schedule=dict(_ah.get('schedule') or {})
        path_meta.update({
            'mode':'Extra Fast adaptive regions',
            'extra_fast_v2':True,
            'adaptive_hybrid':True,
            'adaptive_hybrid_components':int(_ah.get('components',0) or 0),
            'adaptive_hybrid_selected_components':int(_schedule.get('selected_components',0) or 0),
            'adaptive_hybrid_dropped_components':int(_schedule.get('dropped_components',0) or 0),
            'adaptive_hybrid_pixel_accuracy_score':float((_ah.get('quality') or {}).get('pixel_accuracy_score',0) or 0),
            'stroke_optimizer_requested':options.get('stroke_optimizer','Off'),
            'stroke_optimizer_effective':'Adaptive Region scheduler',
        })
    elif options.get('sketch_execution_groups') is not None:
        execution_groups=[list(paths) for paths in options['sketch_execution_groups']]
        path_meta=dict(continuous_path_stats(groups,execution_groups))
        path_meta.update(options.get('gartic_sketch_meta') or {})
        path_meta['mode']='Gartic connected contours'
    elif options.get('skribbl_fast_direct_paths'):
        # Join overlapping adjacent same-colour runs under one mouse-down. The
        # connectors remain inside already-planned colour pixels, so this is both
        # faster and deterministic rather than a blind diagonal shortcut.
        execution_groups=build_execution_paths(groups,enabled=True,
                                                 portrait_edge_count=None,cancelled=cancelled)
        path_meta=continuous_path_stats(groups,execution_groups)
        path_meta=dict(path_meta)
        turbo_meta=dict(options.get('skribbl_fast_meta') or {})
        path_meta.update({
            'mode':'Skribbl turbo runs',
            'skribbl_fast':True,
            'skribbl_active_colors':turbo_meta.get('active_colors_after',0),
            'skribbl_runs_before':turbo_meta.get('runs_before',0),
            'skribbl_runs_after':turbo_meta.get('runs_after',0),
        })
    elif options.get('gartic_phone_direct_paths'):
        turbo_meta=dict(options.get('gartic_phone_fast_meta') or {})
        execution_groups=build_gartic_execution_paths(
            groups, turbo_meta.get('orientations') or {}, cancelled=cancelled)
        path_meta=continuous_path_stats(groups,execution_groups)
        path_meta=dict(path_meta)
        path_meta.update({
            'mode':'Gartic Phone Engine v2 runs',
            'gartic_phone_fast':True,
            'gartic_engine_v2':True,
            'gartic_active_colors':turbo_meta.get('active_colors_after',0),
            'gartic_runs_before':turbo_meta.get('runs_before',0),
            'gartic_runs_after':turbo_meta.get('runs_after',0),
            'gartic_vertical_wins':turbo_meta.get('vertical_wins',0),
            'palette_coverage_percent':turbo_meta.get('palette_coverage_percent',100.0),
            'posterization_risk':turbo_meta.get('posterization_risk','LOW'),
            'p95_reduction_delta_e2000':turbo_meta.get('p95_reduction_delta_e2000',0.0),
            'midtone_loss':turbo_meta.get('midtone_loss',False),
        })
    elif shape_enabled:
        execution_groups,path_meta=build_shape_execution_paths(
            groups, brush_px=int(options.get('brush_px',3) or 3),
            order=options.get('shape_order','Fill first'),
            stroke_cap=options.get('max_stroke_cap','Auto'),
            shape_model=options.get('shape_model','Auto'),
            preview=is_preview_plan(options), cancelled=cancelled)
    else:
        if options.get('extra_fast') and smart_enabled:
            from ExtraFast2 import build_fast_paths, build_meta as build_extra_fast_v2_meta
            execution_groups,_ef_path_meta=build_fast_paths(
                groups,dict(options,_hybrid_scale_x=fitted[0]/max(1,image.width),
                            _hybrid_scale_y=fitted[1]/max(1,image.height)),
                portrait_edge_count=edge_count,cancelled=cancelled)
            path_meta=continuous_path_stats(groups,execution_groups)
            _ef_meta=build_extra_fast_v2_meta(groups,execution_groups,options,fill_regions=options.get('fill_regions') or ())
            _ef_meta.update(_ef_path_meta)
            options['extra_fast_v2_meta']=_ef_meta
            path_meta=dict(path_meta);path_meta.update({
                'mode':'Extra Fast 2.0 connected regions',
                'extra_fast_v2':True,
                'extra_fast_scanline_boundaries_removed':int(_ef_meta.get('scanline_boundaries_removed',0) or 0),
                'extra_fast_scanline_boundary_reduction_percent':float(_ef_meta.get('scanline_boundary_reduction_percent',0) or 0),
                'extra_fast_fill_regions':int(_ef_meta.get('fill_regions',0) or 0),
                'extra_fast_color_pipeline_preserved':True,
            })
        else:
            execution_groups=build_execution_paths(groups,enabled=smart_enabled,
                                                     portrait_edge_count=edge_count,cancelled=cancelled)
            path_meta=continuous_path_stats(groups,execution_groups)
    profiler_stop(options, 'shape_extraction', _prof_shape)

    _prof_paths = profiler_start(options, 'path_optimization')
    if execution_groups is not None:
        if pixel_prebuilt is not None or sketch_fill_prebuilt is not None or adaptive_hybrid_prebuilt is not None:
            # Pixel Accurate, Sketch+Fill and Adaptive Region Hybrid already own
            # geometry/phase/deadline order. Keep every selected path; no generic
            # cap/optimizer may discard or reorder their safe regional plan.
            # PixelStrokeEngine. Keep every path; only attach target metadata so
            # logs stay compatible with the legacy planner.
            path_meta.update({
                'target_before_paths':sum(len(g) for g in execution_groups),
                'target_after_paths':sum(len(g) for g in execution_groups),
                'target_skipped_paths':0,
                'target_cap_applied':False,
            })
        else:
            target_cap = options.get('target_stroke_count_resolved')
            execution_groups, target_meta = apply_target_path_cap(execution_groups, target_cap, prioritize_structure=bool(options.get('real_speed_structure_priority')))
            if path_meta.get('path_phase_hints'):
                # Target-cap can remove paths after ShapePaths has produced phase hints.
                # Rebuild hints heuristically later if their shape no longer matches.
                pass
            if target_meta.get('target_skipped_paths'):
                path_meta = dict(path_meta)
                path_meta.update(target_meta)
                path_meta['execution_paths'] = target_meta['target_after_paths']
                path_meta['joined_strokes'] = max(0, int(path_meta.get('source_strokes', 0)) - int(path_meta['execution_paths']))
                raw = int(path_meta.get('source_strokes', 0) or 0)
                path_meta['compression_ratio'] = 0.0 if raw <= 0 else max(0.0, min(1.0, 1.0 - int(path_meta['execution_paths']) / raw))
            else:
                path_meta = dict(path_meta)
                path_meta.update(target_meta)

            # v1.0.37: optimize final execution paths during planning so preview,
            # estimates and real execution all use exactly the same path order.
            phase_hints = path_meta.get('path_phase_hints')
            try:
                optimized_groups, optimized_hints, optimizer_meta = optimize_execution_groups(
                    execution_groups, mode=options.get('stroke_optimizer','Auto'),
                    drawing_mode=drawing_mode, speed=normalize_speed(options.get('speed','Balanced')),
                    phase_hints=phase_hints, cancelled=cancelled)
                execution_groups = optimized_groups
                path_meta.update(optimizer_meta)
                path_meta['execution_paths'] = sum(len(g) for g in execution_groups)
                raw = int(path_meta.get('source_strokes', 0) or 0)
                path_meta['joined_strokes'] = max(0, raw - int(path_meta['execution_paths']))
                path_meta['compression_ratio'] = 0.0 if raw <= 0 else max(0.0, min(1.0, 1.0-int(path_meta['execution_paths'])/raw))
                if optimized_hints is not None and any(optimized_hints):
                    path_meta['path_phase_hints'] = optimized_hints
            except ValueError:
                path_meta.update({'stroke_optimizer_effective':'Off','optimizer_error':'invalid setting'})

    # v1.0.118 Adaptive Deadline Renderer.  It operates on the final geometry-safe
    # paths before preview rendering, so preview and mouse execution share the exact
    # same deadline-specific plan. Pixel Accurate already has its own exact
    # progressive budget and is deliberately left untouched here.
    deadline_sequence=None
    if execution_groups is not None and pixel_prebuilt is None and sketch_fill_prebuilt is None and adaptive_hybrid_prebuilt is None:
        try:
            from AdaptiveDeadlineRenderer import adapt_execution_plan
            execution_groups,deadline_sequence,deadline_meta,importance_map = adapt_execution_plan(
                image,fitted,execution_groups,options,cancelled=cancelled)
            options['adaptive_deadline_meta']=deadline_meta
            if importance_map is not None:
                options['_visual_importance_map']=importance_map
            if deadline_meta.get('enabled'):
                before=int(path_meta.get('execution_paths',sum(len(g) for g in execution_groups)) or 0)
                after=sum(len(g) for g in execution_groups)
                path_meta=dict(path_meta)
                path_meta.update({
                    'deadline_renderer':True,'deadline_before_paths':before,
                    'deadline_after_paths':after,'deadline_dropped_paths':max(0,before-after),
                    'execution_paths':after,
                    'deadline_quality_retained_percent':float(deadline_meta.get('quality_retained_percent',100) or 100),
                })
        except InterruptedError:
            raise
        except Exception as error:
            log_event(f'Adaptive Deadline Renderer fallback to existing plan: {error!r}')
            options['adaptive_deadline_meta']={'enabled':False,'reason':str(error)}
    elif pixel_prebuilt is not None and options.get('time_budget_active'):
        options['adaptive_deadline_meta']={'enabled':False,'reason':'Pixel Accurate uses the exact progressive PixelMap budget.'}
    elif adaptive_hybrid_prebuilt is not None and options.get('time_budget_active'):
        options['adaptive_deadline_meta']={'enabled':False,'reason':'Adaptive Region Hybrid already scheduled whole components against the real execution budget.'}

    execution_sequence=[]
    if execution_groups is not None:
        sketch_fill_sequence=options.get('_sketch_fill_execution_sequence') if sketch_fill_prebuilt is not None else None
        pixel_sequence=options.get('_pixel_execution_sequence') if pixel_prebuilt is not None else None
        adaptive_hybrid_sequence=options.get('_adaptive_hybrid_execution_sequence') if adaptive_hybrid_prebuilt is not None else None
        if sketch_fill_sequence is not None:
            execution_sequence=[dict(entry) for entry in sketch_fill_sequence]
            _sf=options.get('sketch_fill_meta') or {}
            path_meta.update({
                'progressive_enabled':True,'progressive_sequence_paths':len(execution_sequence),
                'progressive_sketch_paths':int(_sf.get('sketch_paths',0) or 0),
                'progressive_color_fill_paths':int(_sf.get('color_fill_paths',0) or 0),
                'progressive_reoutline_paths':int(_sf.get('reoutline_paths',0) or 0),
                'progressive_phase_order':'Sketch -> Color Fill -> Re-outline',
                'progressive_mode':'Sketch Fill','color_workflow':'Sketch then fill',
            })
        elif pixel_sequence is not None:
            execution_sequence=[dict(entry) for entry in pixel_sequence]
            stroke_meta=dict(options.get('pixel_stroke_meta') or {})
            path_meta.update({
                'progressive_enabled':True,
                'progressive_sequence_paths':len(execution_sequence),
                'progressive_fill_paths':int(stroke_meta.get('fill_paths',0) or 0),
                'progressive_mid_detail_paths':int(stroke_meta.get('mid_detail_paths',0) or 0),
                'progressive_fine_detail_paths':int(stroke_meta.get('fine_detail_paths',0) or 0),
                'progressive_cleanup_paths':int(stroke_meta.get('cleanup_paths',0) or 0),
                'progressive_phase_order':('fill -> mid detail -> fine detail -> cleanup' +
                    ''.join(f" -> correction {i}" for i in range(1,int((options.get('pixel_accuracy_meta') or {}).get('correction_passes_accepted',0) or 0)+1))),
                'progressive_mode':'On',
                'color_workflow':'Progressive passes',
            })
        elif adaptive_hybrid_sequence is not None:
            execution_sequence=[dict(entry) for entry in adaptive_hybrid_sequence]
            _ah=options.get('adaptive_hybrid_meta') or {}
            _schedule=(_ah.get('schedule') or {}) if isinstance(_ah,dict) else {}
            _phase_counts={}
            for _entry in execution_sequence:
                _phase=str(_entry.get('phase') or 'structure')
                _phase_counts[_phase]=_phase_counts.get(_phase,0)+1
            path_meta.update({
                'progressive_enabled':True,
                'progressive_sequence_paths':len(execution_sequence),
                'progressive_foundation_paths':int(_phase_counts.get('foundation',0)),
                'progressive_contour_paths':int(_phase_counts.get('structure',0)),
                'progressive_detail_paths':int(_phase_counts.get('detail',0)),
                'progressive_correction_paths':int(_phase_counts.get('correction',0)),
                'progressive_phase_order':'foundation -> structure -> detail -> correction',
                'progressive_mode':'Adaptive Region Hybrid',
                'color_workflow':'Regional deadline passes',
                'target_before_paths':len(execution_sequence),
                'target_after_paths':len(execution_sequence),
                'target_skipped_paths':0,
                'target_cap_applied':False,
                'regional_deadline_selected_components':int(_schedule.get('selected_components',0) or 0),
                'regional_deadline_dropped_components':int(_schedule.get('dropped_components',0) or 0),
            })
        elif deadline_sequence is not None:
            execution_sequence=[dict(entry) for entry in deadline_sequence]
            phase_counts=(options.get('adaptive_deadline_meta') or {}).get('phase_counts') or {}
            path_meta.update({
                'progressive_enabled':True,
                'progressive_sequence_paths':len(execution_sequence),
                'progressive_foundation_paths':int(phase_counts.get('major_coverage',0) or 0),
                'progressive_contour_paths':int(phase_counts.get('structure',0) or 0),
                'progressive_detail_paths':int(phase_counts.get('important_details',0) or 0),
                'progressive_phase_order':'major coverage -> structure -> important details -> accuracy -> correction',
                'progressive_mode':'Deadline',
                'color_workflow':'Adaptive deadline passes',
            })
        else:
            progressive_mode=options.get('progressive_rendering','Auto')
            color_workflow=options.get('color_workflow','Finish color first')
            enabled=(color_workflow=='Progressive passes' and progressive_enabled(progressive_mode, drawing_mode=drawing_mode, time_budget_active=bool(options.get('time_budget_active'))))
            phase_hints=path_meta.get('path_phase_hints')
            try:
                if phase_hints and sum(len(x) for x in phase_hints)==sum(len(x) for x in execution_groups):
                    hint_arg=phase_hints
                else:
                    hint_arg=None
                execution_sequence,progressive_meta=build_progressive_sequence(execution_groups, phase_hints=hint_arg, enabled=enabled)
                path_meta.update(progressive_meta)
                path_meta['progressive_mode']=progressive_mode
                path_meta['color_workflow']=color_workflow
                if color_workflow=='Finish color first':path_meta['progressive_suppressed_by_color_batching']=True
            except ValueError:
                path_meta.update({'progressive_enabled':False,'progressive_mode':progressive_mode})

    # Step 24: Adaptive Detail Zoom revisits the untouched source at a bounded
    # 2x/4x analysis density and appends only high-value micro-detail paths.
    # This is internal source zoom only: it never changes Paint/browser page zoom
    # or target coordinates, so CanvasGuard and calibration remain valid.
    try:
        from DetailZoomPass import add_detail_zoom_pass
        _detail_source=options.get('_accuracy_original_source')
        if isinstance(_detail_source,Image.Image):
            groups,execution_groups,execution_sequence,_detail_zoom_meta=add_detail_zoom_pass(
                _detail_source,image,palette_rgb,groups,execution_groups,execution_sequence,options,cancelled=cancelled)
            options['detail_zoom_meta']=dict(_detail_zoom_meta or {})
            if options['detail_zoom_meta'].get('enabled'):
                _added=int(options['detail_zoom_meta'].get('detail_paths_added',0) or 0)
                _active=[int(i) for i in (options['detail_zoom_meta'].get('active_color_indices') or ())]
                _order=[];_seen=set()
                for _raw in list(options.get('color_order') or ()) + _active:
                    try:_idx=int(_raw)
                    except (TypeError,ValueError):continue
                    if 0<=_idx<len(groups) and _idx not in _seen:
                        _order.append(_idx);_seen.add(_idx)
                if _order:options['color_order']=_order
                path_meta=dict(path_meta)
                path_meta['detail_zoom_enabled']=True
                path_meta['detail_zoom_factor']=int(options['detail_zoom_meta'].get('factor',1) or 1)
                path_meta['detail_zoom_paths_added']=_added
                path_meta['detail_zoom_pixels_added']=int(options['detail_zoom_meta'].get('detail_pixels_added',0) or 0)
                path_meta['execution_paths']=sum(len(g) for g in execution_groups) if execution_groups is not None else int(path_meta.get('execution_paths',0) or 0)
                path_meta['progressive_sequence_paths']=len(execution_sequence) if execution_sequence else int(path_meta.get('progressive_sequence_paths',0) or 0)
                # Refresh the target diagnostic after the detail pass; otherwise
                # Quantized Target would describe the pre-zoom plan while the
                # simulated final contains the recovered details.
                try:
                    from PreviewDiagnostics import render_quantized_target
                    _zoom_target=render_quantized_target(
                        image.size,groups,palette_rgb,fill_regions=options.get('fill_regions') or (),
                        background_fill_plan=fill_meta,color_order=options.get('color_order'),
                        execution_sequence=execution_sequence or None,cancelled=cancelled)
                    with closing(_zoom_target):
                        _zoom_resized=owner.own(_zoom_target.resize(size,Image.Resampling.NEAREST))
                    _old_target=options.get('_preview_quantized_target')
                    options['_preview_quantized_target']=_zoom_resized
                    if isinstance(_old_target,Image.Image):_old_target.close()
                    options['_accuracy_quantized_target_available']=True
                except InterruptedError:
                    raise
                except Exception as _zoom_target_error:
                    log_event(f'Detail Zoom target diagnostic refresh skipped: {_zoom_target_error!r}')
        else:
            options['detail_zoom_meta']={'enabled':False,'requested':options.get('detail_zoom','Auto'),'reason':'original source unavailable','target_app_zoomed':False}
    except InterruptedError:
        raise
    except Exception as _detail_zoom_error:
        options['detail_zoom_meta']={'enabled':False,'requested':options.get('detail_zoom','Auto'),'reason':str(_detail_zoom_error),'target_app_zoomed':False}
        log_event(f'Adaptive Detail Zoom skipped safely: {_detail_zoom_error!r}')

    profiler_stop(options, 'path_optimization', _prof_paths)
    _prof_preview = profiler_start(options, 'preview_rendering')
    path_moves_total=0;dot_count=0
    precision=options.get('precision','High')
    speed_name=normalize_speed(options.get('speed','Balanced'))
    estimate_delivery=resolve_stroke_delivery(options, dry_run=bool(options.get('dry_run_sampled',False)))
    def estimate_step(physical_brush):
        return interpolation_step(estimate_delivery.step_px,physical_brush,
                                  pixel_accurate=bool(options.get('pixel_accurate')))
    preview_safety=None
    try:
        # Every final pass order belongs to the preview, including progressive
        # scheduling and Pixel corrections when Detail Zoom is disabled.
        preview_safety=build_preview_safety_plan(image.size,fitted,groups,execution_groups,options,cancelled,
                                                execution_sequence=execution_sequence or None)
        options['preview_safety_meta']=preview_safety.as_dict()
        options['_preview_safety_groups']=preview_safety.groups
        if options.get('subject_focus')=='Subject only':
            from SubjectFocus import render_native_subject_preview
            _native_preview=owner.own(render_native_subject_preview(preview_safety,fitted,size,palette_rgb,cancelled=cancelled))
            try:_native_draw=owner.drawing(ImageDraw.Draw(_native_preview))
            except BaseException:
                _native_preview.close()
                raise
            # The old ImageDraw also owns the native image core. Release all
            # its references before replacing the preview with physical ink.
            draw.draw=None;draw.im=None;draw._image=None
            preview.close()
            preview,draw=_native_preview,_native_draw
        else:
            draw_safe_paths(draw,preview_safety,fitted,size,palette_rgb,brush,cancelled)
        if preview_safety.sequence is not None:
            priced_paths=((entry['path'],entry['brush_px']) for entry in preview_safety.sequence)
        else:
            priced_paths=((path,max(1,int(options.get('brush_px',3))))
                          for paths in preview_safety.groups for path in paths)
        for path,physical_brush in priced_paths:
            if len(path)==1:
                dot_count+=1
                continue
            for a,b in zip(path,path[1:]):
                if a!=b:path_moves_total+=precision_path_count(a,b,precision,estimate_step(physical_brush))
    except InterruptedError:
        raise
    except Exception as error:
        # Preview Safety is a mirror/visualization layer.  A failure here must not
        # invalidate the final CanvasGuard path, so old unguarded preview drawing
        # remains a fallback and the warning is surfaced in plan metadata.
        log_event(f'Smart Preview Safety fallback: {error!r}')
        options['preview_safety_meta']={'active':False,'reason':str(error)}
        # A failed renderer may have left partial guarded ink on the bitmap.
        # Rebuild the fill prelude, then replay the same final schedule without
        # allowing a display-only failure to change actual drawing behavior.
        draw.rectangle((0,0,size[0]-1,size[1]-1),fill=preview_bg)
        draw_preview_fills()
        path_moves_total=dot_count=0
        def fallback_paths():
            physical_brush=max(1,int(options.get('brush_px',3)))
            if execution_sequence:
                from AdaptiveBrushEngine import brush_for_entry
                for entry in execution_sequence:
                    path=entry.get('path') or ()
                    if not path:continue
                    physical_brush=brush_for_entry(entry,physical_brush)
                    yield int(entry['color_index']),path,physical_brush
            else:
                order=options.get('color_order') or range(len(groups))
                for raw in order:
                    index=int(raw)
                    if not 0<=index<len(groups):continue
                    if execution_groups is not None and index<len(execution_groups):
                        for path in execution_groups[index]:yield index,path,physical_brush
                    else:
                        for x1,y1,x2,y2 in groups[index]:
                            path=((x1,y1),) if (x1,y1)==(x2,y2) else ((x1,y1),(x2,y2))
                            yield index,path,physical_brush
        for index,path,physical_brush in fallback_paths():
            if cancelled():raise InterruptedError()
            if not path:continue
            mapped=[]
            for number,(x,y) in enumerate(path):
                if number%512==0 and cancelled():raise InterruptedError()
                mapped.append(point(x,y))
            width=max(1,round(physical_brush*scale))
            if len(mapped)>1:
                draw.line([coord for p in mapped for coord in p],fill=palette_rgb[index],width=width,joint='curve')
            else:dot_count+=1
            for x,y in (mapped[0],mapped[-1]):
                if width==1:draw.point((x,y),fill=palette_rgb[index])
                else:
                    before,after=(width-1)//2,width//2
                    draw.ellipse((x-before,y-before,x+after,y+after),fill=palette_rgb[index])
            for (x1,y1),(x2,y2) in zip(path,path[1:]):
                if (x1,y1)!=(x2,y2):
                    path_moves_total+=precision_path_count(execution_transform.point(x1,y1),execution_transform.point(x2,y2),precision,estimate_step(physical_brush))

    if options.get('sketch_fill_active') and execution_sequence:
        try:
            from SketchFillRenderer import render_sequence_preview
            _sf_preview=owner.own(render_sequence_preview(image.size,size,execution_sequence,palette_rgb,brush,cancelled=cancelled))
            draw.draw=draw.im=draw._image=None
            preview.close()
            preview=_sf_preview
        except InterruptedError:
            raise
        except Exception as _sf_preview_error:
            log_event(f'Sketch Fill sequence preview fallback: {_sf_preview_error!r}')
    if options.get('adaptive_hybrid_active') and execution_sequence:
        try:
            from AdaptiveRegionHybrid import render_adaptive_preview
            preview=owner.own(render_adaptive_preview(image.size,size,execution_sequence,palette_rgb,options.get('fill_regions') or (),
                cancelled=cancelled,fitted=fitted,options=options))
        except InterruptedError:
            raise
        except Exception as _ah_preview_error:
            log_event(f'Adaptive Region simulated-final preview fallback: {_ah_preview_error!r}')
    profiler_stop(options, 'preview_rendering', _prof_preview)
    if defer_presentation:
        # Geometry, native brush projection, cancellation and PreviewSafety ran
        # above exactly as for a standalone colour plan. Only the published
        # composite needs targets, UI maps, source accuracy and a final ETA.
        if cancelled():raise InterruptedError()
        return {'image':image,'fitted':fitted,'groups':groups,'execution_groups':execution_groups,
                'execution_sequence':execution_sequence,'count':path_meta['execution_paths'],
                'source_count':path_meta['source_strokes'],'path_stats':path_meta,'options':options,
                'colors':palette_rgb,'color_selectors':tuple(options.get('color_selectors') or ())}
    _prof_estimate = profiler_start(options, 'execution_estimate')
    count=path_meta['execution_paths']
    retained_groups=execution_groups if execution_groups is not None else groups
    colors=sum(bool(g) for g in retained_groups)
    motion=estimated_motion_seconds(path_moves_total,count,dot_count,options['delay'],speed_name)
    base_path_delay=phase_delay(options['delay'],speed_name,'path')
    if estimate_delivery.min_path_delay > base_path_delay:
        motion += path_moves_total * (estimate_delivery.min_path_delay-base_path_delay)
    motion += count * (estimate_delivery.press_settle+estimate_delivery.release_settle)
    # Palette and tool-control clicks keep their real configured settle times.
    # v1.0.117 also counts Region Fill contour travel/tool switching instead of
    # pretending every bucket region costs a flat 0.48 s. That flat shortcut was
    # a major source of optimistic estimates on complex fills.
    fill_regions=options.get('fill_regions',[]) or []
    fill_color_indexes={int(r.get('color_index',-1)) for r in fill_regions if isinstance(r,dict) and int(r.get('color_index',-1))>=0}
    active_stroke_indexes={i for i,g in enumerate(retained_groups) if g}
    # Charge controls that the retained plan actually uses. Unused custom
    # colours must not consume the drawing budget; progressive phase changes
    # explicitly reselect their colour even when its index is unchanged.
    from ExecutionCostModel import build_cost_model
    timing_options=dict(options)
    # This raw summary is later calibrated once by DrawTimeEstimate. Keep
    # per-operation learning out of the cold summary as well as its final ETA.
    timing_options['_execution_cost_calibration_override']={}
    timing_model=build_cost_model(timing_options,image.size,fitted)
    selection_counts={i:1 for i in active_stroke_indexes}
    sequence_timing=None
    if execution_sequence:
        if cancelled():raise InterruptedError()
        sequence_timing=timing_model.sequence_cost(execution_sequence,
            initial_brush=max(1,int(options.get('brush_px') or 1)),include_color_verification=True,
            include_geometry=False,cancelled=cancelled)
        selection_counts={}
    if options.get('fill_tool_actions') or options.get('fill_tool_available'):
        for index in fill_color_indexes:
            selection_counts[index]=selection_counts.get(index,0)+1
        if fill_meta.get('enabled') and fill_meta.get('color_index') is not None:
            index=int(fill_meta['color_index'])
            selection_counts[index]=selection_counts.get(index,0)+1
    palette_seconds=sum(times*timing_model.color_selection_cost(index)[0]
                        for index,times in selection_counts.items())
    custom_color_seconds=sum(times*timing_model.color_selection_cost(index)[1]
                             for index,times in selection_counts.items())
    if sequence_timing is not None:
        palette_seconds+=sequence_timing.palette_seconds
        custom_color_seconds+=sequence_timing.custom_color_seconds

    fill_seconds=0.0;fill_timing_meta={}
    if fill_regions:
        try:
            from RegionFillEngine import estimate_fill_execution_seconds
            fill_timing_meta=estimate_fill_execution_seconds(fill_regions,image.size,fitted,timing_options,
                                                           use_cached_cost=False)
            fill_seconds=float(fill_timing_meta.get('total_seconds',0.0) or 0.0)
        except Exception:
            # Legacy fallback remains operation-count based if a custom/old plan
            # does not expose Region Fill timing metadata.
            fill_seconds=len(fill_regions)*.48
    if fill_meta.get('enabled'):
        bg_tool_switches=len(options.get('fill_tool_actions') or ())+len(options.get('fill_restore_actions') or ())
        fill_seconds += .34 + bg_tool_switches*estimate_delivery.ui_control_delay
    if options.get('extra_fast_meta') and not fill_timing_meta:
        fill_seconds=max(fill_seconds,float(options['extra_fast_meta'].get('fill_estimated_seconds',0.0) or 0.0))

    tool_seconds=len(options.get('tool_actions') or ())*estimate_delivery.ui_control_delay
    clear_seconds=max(0.0,float(options.get('canvas_clear_estimate_seconds',0.0) or 0.0))
    verification_seconds=0.0
    if options.get('adaptive_color_verification') and not options.get('paint_current_color'):
        verification_seconds += (sequence_timing.verification_seconds if sequence_timing is not None
                                 else colors*(estimate_delivery.palette_click_delay+.14))
    if (options.get('visual_verification_enabled') and not options.get('paint_current_color')
            and str(options.get('visual_verification_resolved') or options.get('visual_verification','Auto'))!='Off'):
        if not execution_sequence:
            verification_seconds += colors*.08
        elif (options.get('detail_zoom_meta') or {}).get('sequence_created_for_detail_pass'):
            # Runtime batches these materialized Detail Zoom paths by their
            # colour, detail-pass identity and brush. Ordinary progressive
            # passes explicitly skip this visual batch check.
            previous_batch=None
            for entry in execution_sequence:
                if cancelled():raise InterruptedError()
                key=(int(entry['color_index']),bool(entry.get('detail_zoom')),entry.get('brush_px'))
                if key!=previous_batch:verification_seconds+=.08
                previous_batch=key
    brush_seconds=sequence_timing.brush_seconds if sequence_timing is not None else 0.0
    operation_overhead=palette_seconds+fill_seconds+tool_seconds+clear_seconds+custom_color_seconds+verification_seconds+brush_seconds
    estimate=3+motion+operation_overhead+count*.0015
    estimate += human_overhead_seconds(count, options.get('human_mode','Off'))
    options['fill_timing_meta']=fill_timing_meta
    options['operation_timing_meta']={
        'countdown_seconds':3.0,'palette_seconds':round(palette_seconds,4),
        'fill_seconds':round(fill_seconds,4),'tool_seconds':round(tool_seconds,4),
        'brush_seconds':round(brush_seconds,4),
        'canvas_clear_seconds':round(clear_seconds,4),'custom_color_seconds':round(custom_color_seconds,4),
        'verification_seconds':round(verification_seconds,4),'motion_seconds':round(motion,4),
        'path_bookkeeping_seconds':round(count*.0015,4),
        'operation_overhead_seconds':round(operation_overhead,4)}
    profiler_stop(options, 'execution_estimate', _prof_estimate)
    _prof_preview = profiler_start(options, 'preview_rendering')
    try:
        from PreviewLayers import build_auxiliary_previews
        ui_previews=build_auxiliary_previews(image,size,groups,palette_rgb,point,brush,options,cancelled,include_color_map=False)
        for _layer in ui_previews.values():owner.own(_layer)
        # Color map represents the executed palette, not a second 20-colour quantization.
        ui_previews['color']=preview
        for _key,_option_key in (('coverage','_pixel_coverage_preview'),('accuracy_error','_pixel_error_preview')):
            _im=options.get(_option_key)
            if isinstance(_im,Image.Image):
                _full_canvas=((options.get('pixel_accuracy_meta') or {}).get('coverage_coordinate_space')=='full physical canvas'
                    or (_key=='coverage' and (options.get('adaptive_hybrid_meta') or {}).get('coverage_coordinate_space')=='full physical canvas'))
                # Physical coverage includes letterboxes; fitting it back to
                # the source aspect can distort or hide real native spill.
                ui_previews[_key]=owner.own(_im.copy() if _full_canvas else _im.resize(size,Image.Resampling.NEAREST))
        if preview_safety is not None:
            ui_previews['safety']=owner.own(render_preview_safety_map(image,size,preview_safety,palette_rgb,brush,cancelled))
            ui_previews['safety_debug']=owner.own(render_safety_debug_overlay(size,preview_safety,palette_rgb,brush,cancelled))
    except InterruptedError:
        raise
    except Exception as error:
        # Auxiliary maps are UI-only. A preview-map failure must never invalidate
        # a drawing plan or stop the safe CPU/GPU drawing pipeline.
        log_event(f'Auxiliary preview maps skipped: {error!r}')
        ui_previews={'color':preview}
    # Step 10 core diagnostic stages must survive an optional auxiliary-layer
    # failure. They are derived from already available in-memory plan buffers.
    _quantized_preview=options.get('_preview_quantized_target')
    if isinstance(_quantized_preview,Image.Image):
        ui_previews['quantized_target']=_quantized_preview
    ui_previews['simulated_final']=preview
    if options.get('sketch_fill_active') and execution_sequence:
        try:
            from SketchFillRenderer import build_phase_previews
            _phase_previews=build_phase_previews(image.size,size,execution_sequence,palette_rgb,brush,cancelled=cancelled)
            for _layer in _phase_previews.values():owner.own(_layer)
            ui_previews.update(_phase_previews)
        except InterruptedError:
            raise
        except Exception as _sf_layers_error:
            log_event(f'Sketch Fill phase previews skipped safely: {_sf_layers_error!r}')
    try:
        from DetailZoomPass import render_detail_zoom_preview
        _zoom_overlay=owner.own(render_detail_zoom_preview(size,options.get('detail_zoom_meta') or {}))
        if isinstance(_zoom_overlay,Image.Image) and (options.get('detail_zoom_meta') or {}).get('enabled'):
            ui_previews['detail_zoom']=_zoom_overlay
    except Exception as _detail_preview_error:
        log_event(f'Detail Zoom preview overlay skipped safely: {_detail_preview_error!r}')
    profiler_stop(options, 'preview_rendering', _prof_preview)
    performance_profile = profiler_finalize(options)
    # v1.0.125 Step 1: source-relative accuracy is measured against the untouched
    # input image, never against the already quantized/planned target. Internal
    # PixelAccuracyEngine correctness remains a separate Plan Execution metric.
    try:
        from AccuracyEvaluator import evaluate_preview, normalize_source
        _accuracy_source=options.get('_accuracy_original_source')
        if not isinstance(_accuracy_source,Image.Image):
            _accuracy_source=owner.own(image.copy())
            options['_accuracy_original_source']=_accuracy_source
        _cache=options.get('_accuracy_normalized_source_cache')
        _normalized=None
        if isinstance(_cache,dict) and tuple(_cache.get('size') or ())==tuple(size) and _cache.get('source') is _accuracy_source and isinstance(_cache.get('image'),Image.Image):
            _normalized=_cache['image']
        if _normalized is None:
            _normalized=owner.own(normalize_source(_accuracy_source,size))
            options['_accuracy_normalized_source_cache']={'size':tuple(size),'image':_normalized,'source':_accuracy_source}

        _plan_accuracy=options.get('pixel_accuracy_meta') or {}
        _coverage=_plan_accuracy.get('coverage_percent') if isinstance(_plan_accuracy,dict) else None
        _plan_exec=None
        if isinstance(_plan_accuracy,dict):
            _plan_exec=_plan_accuracy.get('final_plan_execution_accuracy_percent',
                         _plan_accuracy.get('plan_execution_accuracy_percent',
                         _plan_accuracy.get('final_accuracy_percent')))
        _source_meta=evaluate_preview(
            _accuracy_source,preview,options.get('_visual_importance_map'),
            normalized_source=_normalized,coverage_percent=_coverage,
            plan_execution_accuracy_percent=_plan_exec,cancelled=cancelled,
            return_error_map=True,return_delta_e_heatmap=True,
            gpu_mode=str(options.get('gpu_mode') or 'Auto'))
        _source_error=owner.own(_source_meta.pop('_error_map_image',None))
        _delta_e_heatmap=owner.own(_source_meta.pop('_delta_e_heatmap_image',None))
        options['preview_delta_e_meta']=dict(_source_meta.get('delta_e_oklab') or {})
        options['adaptive_accuracy_meta']=_source_meta
        options['accuracy_buffer_meta']={
            'original_source':True,'normalized_source':True,
            'quantized_target':bool(options.get('_accuracy_quantized_target_available',False)),
            'simulated_final':True,'comparison_size':tuple(size)}
        ui_previews['original_normalized']=_normalized
        if isinstance(_source_error,Image.Image):
            ui_previews['accuracy_error']=_source_error
        if isinstance(_delta_e_heatmap,Image.Image):
            ui_previews['delta_e']=_delta_e_heatmap
        if options.get('_visual_importance_map') is not None:
            from VisualImportanceMap import render_importance_preview
            with closing(render_importance_preview(options['_visual_importance_map'])) as _importance_source:
                _imp_preview=owner.own(_importance_source.resize(size,Image.Resampling.BILINEAR))
            ui_previews['importance']=_imp_preview
    except InterruptedError:
        raise
    except Exception as error:
        log_event(f'Source-relative accuracy evaluation skipped: {error!r}')
    if isinstance(options.get('region_fill_meta'),dict):
        try:
            from RegionFillEngine import enrich_region_stats
            options['region_fill_meta']=enrich_region_stats(
                options['region_fill_meta'],source_strokes=path_meta['source_strokes'],final_paths=count)
        except Exception as error:
            log_event(f'Region Fill stats enrichment skipped: {error!r}')
    plan={'image':image,'fitted':fitted,'groups':groups,'execution_groups':execution_groups,'execution_sequence':execution_sequence,
          'preview':preview,'ui_previews':ui_previews,'count':count,'source_count':path_meta['source_strokes'],
          'path_stats':path_meta,'estimate':estimate,'raw_execution_estimate_seconds':estimate,
          'operation_overhead_seconds':float(options.get('operation_timing_meta',{}).get('operation_overhead_seconds',0.0) or 0.0),
          'options':options,'colors':palette_rgb,'color_selectors':tuple(options.get('color_selectors') or ()), 'performance_profile':performance_profile,
          'plan_area':tuple(map(int,size))}
    try:
        from DrawTimeEstimate import attach_draw_time_estimate
        attach_draw_time_estimate(plan)
    except Exception as error:
        log_event(f'Draw time estimate metadata skipped: {error!r}')
    try:
        from PreviewDiagnostics import build_preview_diagnostics
        _diag=build_preview_diagnostics(
            options,accuracy=options.get('adaptive_accuracy_meta') or {},
            delta_e=options.get('preview_delta_e_meta') or {},draw_time=plan.get('draw_time_estimate') or {},
            path_count=count,source_count=path_meta.get('source_strokes',0),performance_profile=performance_profile)
        options['preview_diagnostics_meta']=_diag
        plan['preview_diagnostics']=_diag
    except Exception as error:
        log_event(f'Preview diagnostics metadata skipped safely: {error!r}')
    return plan


def make_test_plan(area,options):
    from PIL import Image
    options=dict(options,_planning_canvas_size=tuple(area))
    if options.get('paint_current_color'):
        return finish_plan(Image.new('RGBA',(80,60)),(min(area[0],180),min(area[1],135)),[[(10,20,65,20)]],options)
    groups=[[] for c in allColors]
    if options.get('outline'):
        from SketchPlanner import black_index
        groups[black_index(tuple(c.RGB for c in allColors))]=[(10,20,65,20)]
    else:
        for row,index in enumerate(range(min(3,len(allColors)))):groups[index]=[(10,10+row*20,65,10+row*20)]
    return finish_plan(Image.new('RGBA',(80,60)),(min(area[0],180),min(area[1],135)),groups,options)


def execute_plan(plan, area, palette, mouse, stop, paused, report, clock=time.monotonic, dry_run=False, keyboard=None, checkpoint=None):
    """Only this function produces mouse input. Pause is at a stroke boundary.

    When dry_run=True the same path is simulated with cursor moves only.
    No native click, press or release call is made.
    """
    # Real drawing uses a hard deadline from function entry. Fast Dry run is
    # different: its 12-second budget applies only to the actual cursor
    # simulation after target activation/countdown, not to preflight/setup time.
    deadline_box=[None if dry_run or plan['options'].get('unlimited_time') else clock()+plan['options'].get('max_seconds',180)]
    if not dry_run and not plan['options'].get('unlimited_time') and plan['options'].get('gartic_timer_deadline') is not None:
        deadline_box[0]=min(deadline_box[0],float(plan['options']['gartic_timer_deadline']))
    done=0
    progress_total=max(0,int(plan.get('count') or 0))
    progress_resumed=0
    progress_last=None
    sent_paths=0
    guard_skipped_paths=0
    speed_measure_started=None
    speed_measure_completed=False
    execution_measure_started=None
    execution_measure_completed_at=None
    runtime_operation_stats={}
    paused_seconds=0.0
    pause_started_at=None
    timer_tick=None
    execution_pause_count=0
    def note_runtime_operation(kind, elapsed, count=1):
        if dry_run:return
        key=str(kind or 'operation')
        item=runtime_operation_stats.setdefault(key,{'count':0,'total_seconds':0.0})
        item['count']+=max(1,int(count or 1))
        item['total_seconds']+=max(0.0,float(elapsed or 0.0))
    def wait(seconds):
        deadline=deadline_box[0]
        if deadline is not None and clock()>=deadline:
            if dry_run:
                raise DryRunBudgetComplete('Dry run time budget completed normally.')
            raise InterruptedError('Time limit reached. Drawing stopped; check the result in the target application.')
        timeout=max(0.0,float(seconds))
        if deadline is not None:
            timeout=min(timeout,max(0.0,deadline-clock()))
        if stop.wait(timeout):
            raise InterruptedError()
        if deadline is not None and clock()>=deadline:
            if dry_run:
                raise DryRunBudgetComplete('Dry run time budget completed normally.')
            raise InterruptedError('Time limit reached. No automatic restart.')
        if timer_tick is not None:
            timer_tick()
            if stop.is_set():raise InterruptedError()
    def guard_keyboard(modal_point=None):
        wait(0)
        check=getattr(mouse,'check_keyboard',None)
        if callable(check):check(modal_point=modal_point)
        elif callable(getattr(mouse,'check',None)):mouse.check()
    exact_color_samples={}
    color_session_cache=plan['options'].setdefault('color_session_cache',{})
    if plan['options'].get('profile_name')=='Microsoft Paint' and isinstance(color_session_cache,dict):
        try:
            from ColorCache import load_cache
            for _key,_entry in load_cache(plan['options'].get('profile_key','microsoft-paint'), context_fingerprint=plan['options'].get('calibration_fingerprint'), workflow=plan['options'].get('custom_color_workflow','')).items():
                if not isinstance(_entry,dict) or not _entry.get('verified'):
                    continue
                color_session_cache.setdefault(str(_key),{
                    'method':str(_entry.get('method') or 'numeric'),
                    'confidence':float(_entry.get('confidence',0) or 0),
                    'actual':tuple(_entry.get('created_rgb') or ()),
                    'sample':None,
                    'persistent_verified':True,
                })
        except Exception as cache_error:
            log_event(f'Verified Paint color cache load skipped: {cache_error!r}')
    from AdaptiveColor import method_candidates,method_label,rgb_key,probe_item,confidence_text
    from RenderResume import (resolve_resume, checkpoint_after_batch, checkpoint_before_path,
                              checkpoint_after_path, SequenceCheckpointSession, items_fingerprint,
                              sequence_entry_key, execution_sequence_with_brushes)
    resume_info=resolve_resume(plan,(plan.get('options') or {}).get('render_resume_state'))
    resume_completed=int(resume_info.get('completed_count',0)) if resume_info.get('compatible') else 0
    resume_path_level=bool(resume_info.get('compatible') and resume_info.get('path_level'))
    resume_sequence_level=bool(resume_info.get('compatible') and resume_info.get('sequence_level'))
    resume_skip_prelude=bool(resume_info.get('compatible') and resume_info.get('prelude_complete'))
    correction_only_retry=plan['options'].get('correction_only_retry') is True
    skip_canvas_prelude=resume_skip_prelude or correction_only_retry
    if resume_info.get('compatible') and (resume_completed or resume_path_level or resume_sequence_level):
        if resume_sequence_level:
            report('status',f'Render resume verified: {int(resume_info.get("sequence_completed_count",0)):,}/{int(resume_info.get("sequence_total",0)):,} final sequence operations already completed ({float(resume_info.get("sequence_coverage_percent",0.0)):.1f}% execution coverage). Normal target recalibration/preflight still runs before resuming.')
        elif resume_path_level:
            report('status',f'Render resume verified: {resume_completed}/{resume_info.get("total_colors",0)} colors complete · color {resume_info.get("active_color_number")} resumes at path {int(resume_info.get("next_path_index",0))+1}/{resume_info.get("active_path_count",0)} after normal browser recalibration/preflight.')
        else:
            report('status',f'Render resume verified: {resume_completed}/{resume_info.get("total_colors",0)} colors already completed. Continuing from color {resume_completed+1}.')
    elif (plan.get('options') or {}).get('render_resume_state') and not dry_run:
        report('status',f'Render resume checkpoint was not compatible with this final plan ({resume_info.get("reason","changed plan")}). Starting safely from color 1.')

    def select(index, method=None):
        """Select one planned color and return the method actually used."""
        if plan['options'].get('paint_current_color'):return 'current-tool'
        if stop.is_set():raise InterruptedError()
        selectors=plan.get('color_selectors') or ()
        selector=selectors[index] if index < len(selectors) else {'kind':'palette','palette_index':index}
        selector_kind=str(selector.get('kind') or 'palette')
        fallback=int(selector.get('fallback_palette_index',selector.get('palette_index',index if index < len(palette) else 0)))
        fallback=max(0,min(len(palette)-1,fallback)) if palette else 0
        planned_rgb=(plan.get('colors') or ((0,0,0),))[index] if index < len(plan.get('colors') or ()) else (0,0,0)
        rgb=tuple(map(int,selector.get('source_rgb') or selector.get('rgb') or planned_rgb))
        actions=plan['options'].get('exact_color_actions') or {}

        # v1.0.124: a standard Paint palette selector is allowed to recover via
        # calibrated numeric RGB/spectrum after verification proves that the
        # palette click selected the wrong color. Previously select(...,'numeric')
        # returned here and clicked the same stale palette coordinate again.
        if selector_kind!='custom' and (method is None or method=='palette'):
            palette_index=int(selector.get('palette_index',fallback));palette_index=max(0,min(len(palette)-1,palette_index))
            mouse.move(*palette[palette_index]); wait(max(delay,.025))
            if dry_run:
                report('status','Dry run: palette move simulated. No click was sent.');wait(max(delay,.05));return 'palette'
            mouse.click(); wait(max(delay,stroke_delivery.palette_click_delay))
            # Optional v1.0.124 foreground-swatch check. This separates a wrong
            # palette/control selection from a later stroke-delivery problem.
            active_point=actions.get('ActiveColorPreview')
            if plan['options'].get('profile_name')=='Microsoft Paint' and active_point and hasattr(mouse,'calibrated_modal_color'):
                try:
                    from PaintColorVerifier import verify_paint_color
                    active_rgb=tuple(map(int,mouse.calibrated_modal_color(active_point)))
                    active_result=verify_paint_color(rgb,active_rgb,context='selection')
                    log_event(f'Paint active swatch after palette click: expected={rgb} actual={active_rgb} deltaE2000={active_result.delta_e2000:.2f} accepted={active_result.accepted}.')
                    if active_result.accepted:
                        report('status',f'Paint Color 1 swatch verified before stroke: RGB {active_rgb} (DeltaE2000 {active_result.delta_e2000:.2f}).')
                        return 'palette'
                    numeric_ready_now=all(name in actions for name in ('OpenCustomColor','ConfirmColor','RedField','GreenField','BlueField')) and keyboard is not None
                    spectrum_ready_now=all(name in actions for name in ('OpenCustomColor','ConfirmColor','SpectrumTopLeft','SpectrumBottomRight'))
                    if numeric_ready_now:
                        report('status',f'Paint palette selected {active_rgb} instead of {rgb}; switching to exact R/G/B before any stroke is drawn.')
                        return select(index,'numeric')
                    if spectrum_ready_now:
                        report('status',f'Paint palette selected {active_rgb} instead of {rgb}; switching to calibrated custom spectrum before any stroke is drawn.')
                        return select(index,'spectrum')
                    report('status',f'Paint Color 1 swatch mismatch ({active_rgb} vs {rgb}); no exact controls are available, so canvas verification will decide whether drawing may continue.')
                except InterruptedError:
                    raise
                except Exception as swatch_error:
                    log_event(f'Paint active swatch verification unavailable: {swatch_error!r}')
            return 'palette'
        if selector_kind!='custom' and method not in ('numeric','spectrum','eyedropper'):
            method='palette'
        if selector_kind!='custom' and plan['options'].get('profile_name')!='Microsoft Paint':
            method='palette'
        numeric_required=('RedField','GreenField','BlueField')
        spectrum_required=('SpectrumTopLeft','SpectrumBottomRight')
        base_required=('OpenCustomColor','ConfirmColor')
        numeric_ready=all(name in actions for name in base_required+numeric_required) and keyboard is not None
        spectrum_ready=all(name in actions for name in base_required+spectrum_required)
        cache=color_session_cache.get(rgb_key(rgb),{}) if isinstance(color_session_cache,dict) else {}
        if method is None:
            cached_sample=cache.get('sample') if isinstance(cache,dict) else None
            candidates=method_candidates(selector,actions,has_sample=(rgb in exact_color_samples or bool(cached_sample)),
                                          keyboard_available=keyboard is not None,cached_method=cache.get('method'))
            method=candidates[0] if candidates else 'palette'

        def nearest_palette(reason=''):
            if selector.get('require_exact') and not dry_run:
                raise ValueError(f'Paint could not select picture RGB {rgb}: {reason}. Stopped without substituting a standard palette color.')
            if not dry_run and hasattr(mouse,'reset_tracking'):mouse.reset_tracking()
            mouse.move(*palette[fallback]);wait(max(delay,.025))
            if not dry_run:mouse.click();wait(max(delay,stroke_delivery.palette_click_delay))
            else:wait(max(delay,.05))
            suffix=f' ({reason})' if reason else ''
            report('status',f'Nearest calibrated palette fallback selected for RGB {rgb}{suffix}.')
            return 'palette'

        if method=='palette':
            return nearest_palette('adaptive color fallback')

        if method=='eyedropper':
            sample=exact_color_samples.get(rgb) or (tuple(cache.get('sample')) if isinstance(cache,dict) and cache.get('sample') else None)
            if sample is None or 'Eyedropper' not in actions:
                return nearest_palette('eyedropper sample unavailable')
            if dry_run:
                mouse.move(*actions['Eyedropper']);wait(.04);mouse.move(*sample);wait(.04)
                report('status',f'Dry run: eyedropper reuse of exact RGB {rgb} simulated. No clicks were sent.');return 'eyedropper'
            mouse.move(*actions['Eyedropper']);wait(.04);mouse.click();wait(.18)
            mouse.move(*sample);wait(.04);mouse.click();wait(.20)
            for _kind,_position in plan['options'].get('tool_actions',[]):
                mouse.move(*_position);wait(.03);mouse.click();wait(.16)
            report('status',f'Exact RGB {rgb} re-selected with calibrated eyedropper.');return 'eyedropper'

        if not all(name in actions for name in base_required):
            return nearest_palette('custom-color controls incomplete')

        if dry_run:
            mouse.move(*actions['OpenCustomColor']);wait(max(delay,.03))
            if method=='spectrum' and spectrum_ready:
                for name in spectrum_required:mouse.move(*actions[name]);wait(max(delay,.03))
                if 'BrightnessTop' in actions and 'BrightnessBottom' in actions:
                    mouse.move(*actions['BrightnessTop']);wait(.03);mouse.move(*actions['BrightnessBottom']);wait(.03)
                mouse.move(*actions['ConfirmColor']);wait(.03)
                report('status',f'Dry run: Smart custom palette for RGB {rgb} simulated. No clicks or typing were sent.');return 'spectrum'
            if method=='numeric' and numeric_ready:
                for name in numeric_required:mouse.move(*actions[name]);wait(max(delay,.03))
                mouse.move(*actions['ConfirmColor']);wait(.03)
                report('status',f'Dry run: exact numeric RGB {rgb} controls simulated. No clicks or typing were sent.');return 'numeric'
            return nearest_palette('requested exact method unavailable')

        try:
            mouse.move(*actions['OpenCustomColor']);wait(.04);mouse.click();wait(.30)

            def modal_preview():
                if 'SelectedColorPreview' not in actions or not hasattr(mouse,'calibrated_modal_color'):
                    return None,None
                value=tuple(map(int,mouse.calibrated_modal_color(actions['SelectedColorPreview'])))
                # v1.0.122: validate the actual displayed Paint color in a
                # perceptual space rather than accepting a rough weighted-RGB
                # approximation. The final canvas stroke is still verified too.
                from PaintColorVerifier import verify_paint_color
                result=verify_paint_color(rgb,value,context='modal')
                return value,float(result.delta_e2000)

            def type_numeric_rgb():
                for name,value in zip(numeric_required,rgb):
                    if hasattr(mouse,'calibrated_modal_click'):mouse.calibrated_modal_click(actions[name])
                    else:mouse.move(*actions[name]);mouse.click()
                    wait(.05);guard_keyboard(actions[name]);keyboard.press_and_release('ctrl+a')
                    wait(.02);guard_keyboard(actions[name]);keyboard.write(str(value),delay=.01);wait(.05)
                wait(.10)
                return modal_preview()

            def choose_spectrum_rgb():
                spectrum_point,seen,error=mouse.calibrated_modal_nearest_color_rect(
                    actions['SpectrumTopLeft'],actions['SpectrumBottomRight'],rgb)
                mouse.calibrated_modal_click(spectrum_point);wait(.16)
                slider_used=False
                if ('BrightnessTop' in actions and 'BrightnessBottom' in actions and
                        hasattr(mouse,'calibrated_modal_nearest_color_line')):
                    slider_point,_slider_seen,_slider_error=mouse.calibrated_modal_nearest_color_line(
                        actions['BrightnessTop'],actions['BrightnessBottom'],rgb)
                    mouse.calibrated_modal_click(slider_point);wait(.16);slider_used=True
                    spectrum_point,seen,error=mouse.calibrated_modal_nearest_color_rect(
                        actions['SpectrumTopLeft'],actions['SpectrumBottomRight'],rgb)
                    mouse.calibrated_modal_click(spectrum_point);wait(.14)
                preview_rgb,preview_error=modal_preview()
                accepted_error=preview_error if preview_error is not None else float(error)
                return tuple(seen),float(accepted_error),bool(slider_used),preview_rgb

            selected_method=None;selection_detail=''
            # Numeric RGB is safest for v1.0.109 image-sampled selectors.  If a
            # calibrated preview swatch proves the typed result is wrong, retry
            # the fields once and then use the visual spectrum rather than ever
            # confirming a known-wrong custom color.
            if method=='numeric' and numeric_ready:
                preview_rgb,preview_error=type_numeric_rgb()
                if preview_error is not None and preview_error>4.0:
                    report('status',f'Exact RGB preview check saw {preview_rgb} instead of {rgb}; re-entering R/G/B once before accepting the color.')
                    preview_rgb,preview_error=type_numeric_rgb()
                if preview_error is None or preview_error<=4.0:
                    selected_method='numeric';selection_detail=(f'preview {preview_rgb}, error {preview_error:.1f}' if preview_rgb is not None else 'numeric fields')
                elif spectrum_ready and hasattr(mouse,'calibrated_modal_nearest_color_rect'):
                    seen,spectrum_error,slider_used,spectrum_preview=choose_spectrum_rgb()
                    if spectrum_error<=10.0:
                        selected_method='spectrum';selection_detail=f'numeric preview rejected; spectrum {spectrum_preview or seen}, error {spectrum_error:.1f}'+(' + brightness scale' if slider_used else '')

            elif method=='spectrum' and spectrum_ready and hasattr(mouse,'calibrated_modal_nearest_color_rect'):
                seen,spectrum_error,slider_used,spectrum_preview=choose_spectrum_rgb()
                if spectrum_error<=10.0 or spectrum_preview is None:
                    selected_method='spectrum';selection_detail=f'preview {spectrum_preview}' if spectrum_preview is not None else f'nearest visible {seen}'
                    selection_detail+=f', estimated error {spectrum_error:.1f}'+(' + brightness scale' if slider_used else '')
                elif numeric_ready:
                    report('status',f'Custom spectrum preview was too far from RGB {rgb} ({spectrum_preview}, error {spectrum_error:.1f}); switching to exact R/G/B fields before OK.')
                    preview_rgb,preview_error=type_numeric_rgb()
                    if preview_error is not None and preview_error>4.0:
                        preview_rgb,preview_error=type_numeric_rgb()
                    if preview_error is None or preview_error<=4.0:
                        selected_method='numeric';selection_detail=(f'spectrum rejected; numeric preview {preview_rgb}, error {preview_error:.1f}' if preview_rgb is not None else 'spectrum rejected; numeric fields')

            if selected_method is not None:
                mouse.calibrated_modal_click(actions['ConfirmColor']);wait(.32)
                active_selection_note=''
                if actions.get('ActiveColorPreview') and hasattr(mouse,'calibrated_modal_color'):
                    try:
                        from PaintColorVerifier import verify_paint_color
                        active_rgb=tuple(map(int,mouse.calibrated_modal_color(actions['ActiveColorPreview'])))
                        active_v=verify_paint_color(rgb,active_rgb,context='selection')
                        active_selection_note=f' · active Color 1 {active_rgb}, DeltaE2000 {active_v.delta_e2000:.2f}'
                        log_event(f'Paint active swatch after exact selection: expected={rgb} actual={active_rgb} deltaE2000={active_v.delta_e2000:.2f} accepted={active_v.accepted}.')
                        if not active_v.accepted:
                            report('status',f'Exact color dialog closed, but Paint Color 1 reads {active_rgb} instead of {rgb}. The separate canvas probe will verify/recover before the full batch.')
                    except InterruptedError:
                        raise
                    except Exception as swatch_error:
                        log_event(f'Paint active swatch post-confirm check skipped: {swatch_error!r}')
                if hasattr(mouse,'reset_tracking'):mouse.reset_tracking()
                selector_stats=[]
                for key,label in (('source_mean_rgb','mean'),('source_median_rgb','median'),('source_dominant_rgb','dominant')):
                    if selector.get(key) is not None:selector_stats.append(f'{label}={tuple(selector[key])}')
                source_note=(' · source '+', '.join(selector_stats)) if selector_stats else ''
                report('status',f'Image RGB {rgb} selected with {method_label(selected_method)} ({selection_detail}).{source_note}{active_selection_note} Selection verification completed; canvas stroke verification follows separately.')
                log_event(f'Paint color selection verified before stroke: rgb={rgb} method={selected_method} detail={selection_detail}.')
                return selected_method

            # A calibrated preview explicitly showed the wrong colour. Cancel the
            # modal instead of clicking OK, then use the known calibrated palette
            # fallback. The subsequent canvas probe can still try another method.
            if keyboard is not None:
                try:guard_keyboard(actions.get('ConfirmColor'));keyboard.press_and_release('esc');wait(.12)
                except InterruptedError:raise
                except Exception:pass
            if hasattr(mouse,'reset_tracking'):mouse.reset_tracking()
            return nearest_palette(f'{method_label(method)} could not prove RGB {rgb} before OK')
        except InterruptedError:
            raise
        except Exception as error:
            if keyboard is not None:
                try:guard_keyboard(actions.get('ConfirmColor'));keyboard.press_and_release('esc');wait(.12)
                except InterruptedError:raise
                except Exception:pass
            if hasattr(mouse,'reset_tracking'):mouse.reset_tracking()
            return nearest_palette(f'{method_label(method)} error: {error}')

    delay = plan['options']['delay']
    speed_name=normalize_speed(plan['options'].get('speed','Balanced'))
    speed_cfg=speed_profile(speed_name)
    travel_delay=phase_delay(delay,speed_name,'travel')
    path_delay=phase_delay(delay,speed_name,'path')
    boundary_delay=phase_delay(delay,speed_name,'boundary')
    stroke_delivery=resolve_stroke_delivery(plan.get('options') or {}, dry_run=dry_run)
    stroke_step_px=stroke_delivery.step_px
    effective_path_delay=max(path_delay, stroke_delivery.min_path_delay)
    plan['options']['stroke_delivery_meta']=stroke_delivery.as_dict()
    # v1.0.78: browser canvases get per-stroke delivery confirmation.  The
    # verifier is read-only; a suspected miss can replay only the affected
    # stroke once with denser/slower input.  CanvasGuard remains authoritative.
    from StrokeDeliveryVerification import (
        StrokeDeliveryVerificationError, inspect_delivery as inspect_stroke_delivery,
        resolve_policy as resolve_delivery_verification, retry_parameters as delivery_retry_parameters)
    delivery_verify_policy=resolve_delivery_verification(plan.get('options') or {},dry_run=dry_run)
    delivery_verify_meta=plan['options'].setdefault('stroke_delivery_verification_meta',{
        'enabled':bool(delivery_verify_policy.enabled),'profile_key':delivery_verify_policy.profile_key,
        'retry_cap':int(delivery_verify_policy.retry_cap),'checked':0,'passed':0,'suspected':0,
        'retried':0,'recovered':0,'failed':0,'skipped':0})
    delivery_verify_meta.update({'enabled':bool(delivery_verify_policy.enabled),'profile_key':delivery_verify_policy.profile_key,
                                 'retry_cap':int(delivery_verify_policy.retry_cap)})
    progress_every=max(1,int(speed_cfg['progress_every']))
    width, height = plan['image'].size
    fw, fh = plan['fitted']
    left, top = area[0] + (area[2]-fw)/2, area[1] + (area[3]-fh)/2
    transform=CanvasTransform(width,height,(fw,fh),left,top)
    canvas_polygon=plan['options'].get('canvas_polygon') or plan['options'].get('canvas_safe_polygon')
    canvas_polygon_space=plan['options'].get('canvas_polygon_space') or plan['options'].get('canvas_coordinate_space')
    canvas_anchor_space=plan['options'].get('canvas_anchor_space') or canvas_polygon_space
    canvas_anchors=normalize_canvas_anchors(plan['options'].get('canvas_anchors') or (), area=area, coordinate_space=canvas_anchor_space)
    _browser_guard_plan=plan['options'].get('browser_brush_plan') or {}
    _initial_guard_brush=plan['options'].get('canvas_guard_brush_px',plan['options'].get('brush_px',3))
    if _browser_guard_plan:
        from BrowserBrushSize import conservative_brush_guard
        _initial_guard_brush=max(_initial_guard_brush,conservative_brush_guard(
            _browser_guard_plan.get('profile_key') or plan['options'].get('profile_key'),
            plan['options'].get('brush_px',3)))
    _verified_execution_brush=None
    canvas_guard=CanvasGuard.from_area_or_polygon(area, polygon=canvas_polygon, coordinate_space=canvas_polygon_space,
                                                  brush_px=_initial_guard_brush, edge_margin_px=2, anchors=canvas_anchors,
                                                  confidence=float((plan['options'].get('canvas_anchor_meta') or {}).get('confidence',1.0)) if isinstance(plan['options'].get('canvas_anchor_meta'),dict) else 1.0)
    draw_mouse=FinalMouseGuard(mouse, canvas_guard)
    plan['options']['canvas_guard_meta']=canvas_guard.model.as_dict()
    def install_brush_guard(brush_px):
        nonlocal canvas_guard
        replacement=CanvasGuard.from_area_or_polygon(
            area, polygon=canvas_polygon, coordinate_space=canvas_polygon_space,
            brush_px=brush_px, edge_margin_px=2, anchors=canvas_anchors,
            confidence=float((plan['options'].get('canvas_anchor_meta') or {}).get('confidence',1.0)) if isinstance(plan['options'].get('canvas_anchor_meta'),dict) else 1.0)
        canvas_guard=replacement
        draw_mouse.set_canvas_guard(canvas_guard)
        plan['options']['canvas_guard_meta']=canvas_guard.model.as_dict()
    plan['options'].setdefault('canvas_edge_verification', 'Auto')
    plan['options'].setdefault('canvas_edge_margin_px', 24)
    plan['options'].setdefault('canvas_edge_tolerance_px', 4)
    plan['options'].setdefault('canvas_edge_search_px', 24)
    runtime_edge_mode=resolve_edge_behavior(plan['options'].get('edge_behavior','Hard Clip'),
                                            profile_name=plan['options'].get('profile_name'),
                                            drawing_mode=plan['options'].get('drawing_mode'),
                                            outline=bool(plan['options'].get('outline')))
    runtime_safety=RuntimeSafetySession(
        dry_run=bool(dry_run),
        profile_name=str(plan['options'].get('profile_name') or ''),
        edge_behavior=runtime_edge_mode,
        planned_paths=int(plan.get('count') or 0),
    )

    def verify_canvas_edges_before_input():
        mode = str(plan['options'].get('canvas_edge_verification', 'Auto') or 'Auto').strip().lower()
        if mode in ('off', 'disabled', 'false', '0'):
            plan['options']['canvas_edge_meta'] = {'ok': True, 'active': False, 'reason': 'disabled'}
            return
        try:
            if hasattr(mouse, 'snapshot_canvas_with_margin'):
                capture = mouse.snapshot_canvas_with_margin(area, margin=plan['options'].get('canvas_edge_margin_px', 24))
            else:
                plan['options']['canvas_edge_meta'] = {'ok': True, 'active': False, 'reason': 'expanded snapshot unavailable'}
                report('status', 'Edge verification skipped: expanded screenshot unavailable; Canvas Guard remains active.')
                return
            result = verify_canvas_edges_from_capture(
                capture,
                tolerance_px=plan['options'].get('canvas_edge_tolerance_px', 4),
                search_px=plan['options'].get('canvas_edge_search_px', 24),
            )
            meta = result.as_dict(); meta['active'] = True
            plan['options']['canvas_edge_meta'] = meta
            report('status', result.describe())
            if not result.ok:
                raise InterruptedError(result.stop_message())
        except InterruptedError:
            raise
        except Exception as error:
            # Read-only edge detection must not become a new crash source. When
            # the screenshot backend is unavailable, CanvasGuard/FinalMouseGuard
            # still enforce hard coordinate safety.
            plan['options']['canvas_edge_meta'] = {'ok': True, 'active': False, 'reason': str(error)}
            report('status', f'Edge verification fallback: {error}. Canvas Guard remains active.')

    transform_meta=plan['options'].get('canvas_anchor_transform_meta')
    if isinstance(transform_meta,dict) and transform_meta.get('method'):
        report('status', canvas_guard.describe() +
               f" · transform={transform_meta.get('method')} dx={transform_meta.get('dx',0)} dy={transform_meta.get('dy',0)} sx={transform_meta.get('sx',1)} sy={transform_meta.get('sy',1)}")
    else:
        report('status', canvas_guard.describe())
    def point(x, y):
        return canvas_guard.protect_point(transform.point(x,y), 'planned canvas coordinate')

    def capture_post_draw_accuracy(actual_elapsed=None):
        """Read-only Step 13 final-canvas real-result scoring.

        The screenshot is processed only in memory and discarded immediately;
        only compact metrics, trust flags and reason strings are retained for
        profile-local Auto Tuner feedback.
        """
        from PIL import Image
        tuner=plan['options'].get('auto_tuner_meta') or {}
        if dry_run or not hasattr(mouse,'snapshot_canvas'):
            return None
        source=plan['options'].get('_accuracy_original_source')
        if not isinstance(source,Image.Image):
            return None
        snapshot=None
        try:
            snapshot=mouse.snapshot_canvas(area)
            if not isinstance(snapshot,Image.Image) or snapshot.width<=0 or snapshot.height<=0:
                return None
            compare_size=tuple(map(int,getattr(plan.get('preview'),'size',(max(1,int(fw)),max(1,int(fh))))))
            acceptance=plan['options'].get('auto_tuner_acceptance_meta') or {}
            gates=acceptance.get('gates') if isinstance(acceptance.get('gates'),dict) else {}
            usable=acceptance.get('usable_deadline_seconds')
            visual_gate=gates.get('visual_accuracy_min_percent')
            layers=plan.get('ui_previews') if isinstance(plan.get('ui_previews'),dict) else {}
            from SafeCanvasSnapshotScoring import score_final_canvas_snapshot
            meta=score_final_canvas_snapshot(
                snapshot=snapshot, original_source=source, area=area, fitted=(fw,fh),
                comparison_size=compare_size, simulated_final=plan.get('preview'),
                quantized_target=layers.get('quantized_target'),
                profile_key=str(plan['options'].get('profile_key') or ''),
                gpu_mode=plan['options'].get('gpu_mode','Auto'),
                actual_elapsed_seconds=actual_elapsed, usable_deadline_seconds=usable,
                visual_gate_percent=visual_gate,cancelled=stop.is_set)
            plan['options']['post_draw_accuracy_meta']=meta
            if meta.get('available'):
                trust=meta.get('feedback_trust','none')
                visual=meta.get('visual_accuracy_percent')
                sim=meta.get('actual_vs_simulated_visual_percent')
                cov=meta.get('actual_coverage_percent')
                report('status',f"Drawing Accuracy Score {float(visual or 0):.1f}/100 · trust {trust} · coverage {float(cov or 0):.1f}% · actual vs simulated {float(sim or 0):.1f}%.")
            return meta
        except InterruptedError:
            raise
        except Exception as error:
            plan['options']['post_draw_accuracy_meta']={'available':False,'feedback_trust':'none','reason':str(error)[:240],'capture_pixels_persisted':False,'image_pixels_persisted':False}
            log_event(f'Step 13 post-draw snapshot scoring skipped safely: {error!r}')
            return None
        finally:
            if isinstance(snapshot,Image.Image):snapshot.close()

    def click_ui_control(position, label, settle=None):
        if stop.is_set():raise InterruptedError()
        if settle is None: settle=stroke_delivery.ui_control_delay
        mouse.move(*position);wait(max(delay,.025))
        if dry_run:
            wait(max(settle,delay))
            report('status',f'Dry run: {label} target verified. No click was sent.')
            return
        mouse.click();wait(max(settle,delay))
        report('status',f'{label} selected. Preparing the first stroke…')
    def draw_segment(start,end):
        """Draw one exact segment for a safe fill perimeter."""
        start=draw_mouse.move_point(start, 'fill perimeter start');wait(max(travel_delay,.012))
        if start==end:
            if not dry_run:draw_mouse.click('fill perimeter dot')
            wait(max(boundary_delay,.008));return
        if dry_run:
            for path_point in precision_path(start,end,plan['options'].get('precision','High'),plan['options'].get('stroke_step_px',8)):
                draw_mouse.move_point(path_point, 'fill perimeter path');wait(max(path_delay,.004))
        else:
            try:
                draw_mouse.press('fill perimeter press')
                for path_point in precision_path(start,end,plan['options'].get('precision','High'),plan['options'].get('stroke_step_px',8)):
                    draw_mouse.move_point(path_point, 'fill perimeter path');wait(max(path_delay,.004))
            finally:
                draw_mouse.release()
        wait(max(boundary_delay,.008))
    def draw_clear_segment(start,end):
        """Erase one already-clipped screen-space segment inside CanvasGuard."""
        start=draw_mouse.move_point(start, 'automatic canvas clear start');wait(max(travel_delay,.010))
        if start==end:
            if not dry_run:draw_mouse.click('automatic canvas clear dot')
            wait(max(boundary_delay,.006));return
        if dry_run:
            for path_point in precision_path(start,end,plan['options'].get('precision','High'),plan['options'].get('stroke_step_px',8)):
                draw_mouse.move_point(path_point, 'automatic canvas clear path');wait(max(path_delay,.003))
        else:
            try:
                draw_mouse.press('automatic canvas clear press')
                for path_point in precision_path(start,end,plan['options'].get('precision','High'),plan['options'].get('stroke_step_px',8)):
                    draw_mouse.move_point(path_point, 'automatic canvas clear path');wait(max(path_delay,.003))
            finally:
                draw_mouse.release()
        wait(max(boundary_delay,.006))

    def draw_closed_contour(points):
        """Draw a closed region perimeter with one continuous mouse-down gesture.

        Better Fill uses the component's traced pixel-center boundary instead of
        assuming an axis-aligned rectangle. Keeping the perimeter in one press
        avoids tiny gaps at corners that could let Paint's bucket leak outside.
        """
        pts=[tuple(map(float,p)) for p in points or ()]
        if len(pts)<2:return
        screen=[point(x,y) for x,y in pts]
        if screen[-1]!=screen[0]:screen.append(screen[0])
        screen[0]=draw_mouse.move_point(screen[0], 'closed fill contour start');wait(max(travel_delay,.012))
        if dry_run:
            for a,b in zip(screen,screen[1:]):
                for path_point in precision_path(a,b,plan['options'].get('precision','High'),plan['options'].get('stroke_step_px',8)):
                    draw_mouse.move_point(path_point, 'fill perimeter path');wait(max(path_delay,.004))
        else:
            try:
                draw_mouse.press('closed fill contour press')
                for a,b in zip(screen,screen[1:]):
                    for path_point in precision_path(a,b,plan['options'].get('precision','High'),plan['options'].get('stroke_step_px',8)):
                        draw_mouse.move_point(path_point, 'closed fill contour path');wait(max(path_delay,.004))
            finally:
                draw_mouse.release()
        wait(max(boundary_delay,.010))
    visual_previous_snapshot=None
    try:
        if (resume_sequence_level and resume_info.get('sequence_total',0)>0
                and resume_info.get('sequence_remaining_count')==0):
            # A verified complete sequence is already finished. Do not activate
            # the target, repeat its setup/input, or launch a new correction or
            # learning pass. Keep the normal Stop and release/disarm contract.
            wait(0)
            runtime_safety.mark_completed()
            report('progress',(int(resume_info['sequence_total']),int(resume_info['sequence_total'])))
            report('status','Render resume finished: all sequence operations are already complete. No new drawing input was sent.')
            return
        # Materialize this final schedule once, before input. Display progress
        # includes verified earlier work; runtime/learning counters below keep
        # measuring only operations performed by this invocation.
        prepared_execution_sequence=list(execution_sequence_with_brushes(plan,cancelled=stop.is_set))
        has_execution_sequence=bool(plan.get('execution_sequence'))
        sequence_completed_counts=(
            {str(k):max(0,int(v or 0)) for k,v in dict(resume_info.get('sequence_completed_counts') or {}).items()}
            if has_execution_sequence and resume_sequence_level else {})
        sequence_checkpoint_session=None
        # Freeze the exact effective context before target preparation/input.
        # A session stores only canonical proof and completion bits; periodic
        # and Stop checkpoints must not rescan the image or geometry.
        plan['options']['edge_behavior_resolved']=runtime_edge_mode
        if has_execution_sequence and checkpoint is not None and not dry_run:
            try:
                sequence_checkpoint_session=SequenceCheckpointSession(
                    dict(plan,execution_sequence=prepared_execution_sequence),
                    completed_counts=sequence_completed_counts,cancelled=stop.is_set)
                sequence_completed_counts=sequence_checkpoint_session.completed_counts
            except InterruptedError:raise
            except Exception as checkpoint_error:
                # Resume support has its own capacity limit. Failure to prepare
                # recovery must not introduce a lower drawing-operation limit.
                checkpoint=None
                log_event(f'Sequence recovery disabled for this execution: {checkpoint_error!r}')
        if has_execution_sequence:
            progress_total=len(prepared_execution_sequence)
            if resume_sequence_level:
                progress_resumed=min(progress_total,int(resume_info.get('sequence_completed_count',0)))
        else:
            _groups=plan['groups'];_execution_groups=plan.get('execution_groups')
            _order=plan['options'].get('color_order') or range(len(_groups))
            _counts=[]
            for _number,_raw in enumerate(_order):
                if _number%256==0 and stop.is_set():raise InterruptedError()
                _index=int(_raw)
                if not 0<=_index<len(_groups):continue
                _paths=_execution_groups[_index] if _execution_groups is not None and _index<len(_execution_groups) else None
                if _groups[_index] or _paths:
                    _counts.append(len(_paths) if _paths is not None else len(_groups[_index]))
            progress_total=sum(_counts)
            progress_resumed=sum(_counts[:resume_completed])
        def report_execution_progress(*,force=False):
            nonlocal progress_last
            shown=min(progress_total,progress_resumed+done)
            value=(shown,progress_total)
            if value!=progress_last and (force or done%progress_every==0 or shown==progress_total):
                report('progress',value)
                progress_last=value
                # Include initial/final resume reports in the same input gate.
                wait(0)
        if progress_resumed:
            report_execution_progress(force=True)
        precision=plan['options'].get('precision','High')
        if hasattr(mouse,'configure_precision'):mouse.configure_precision(precision)
        if hasattr(mouse,'configure_drag_backend'):mouse.configure_drag_backend(stroke_delivery.drag_backend)
        if hasattr(mouse,'prepare_target'):mouse.prepare_target(stop,wait,report)
        verify_canvas_edges_before_input()
        mode_label='Dry run' if dry_run else 'Starting'
        for second in (3, 2, 1):
            report('status', f'{mode_label} in {second}… Switch to the drawing application. Esc stops.')
            wait(1)
        # Validate every palette point before the first native move/click. This
        # catches stale Paint layout calibration without drawing a wrong stroke.
        if hasattr(mouse,'verify_palette_layout'):mouse.verify_palette_layout()
        # v1.0.117 measured estimate calibration starts after the explicit 3-2-1
        # handoff, but before brush/tool setup, canvas clear, region fills and
        # normal strokes. This matches what the UI calls final draw time.
        execution_measure_started=clock()
        _draw_timer_last=[execution_measure_started]
        try:_planned_draw_seconds=max(0.0,float((plan.get('draw_time_estimate') or {}).get('projected_seconds') or plan.get('estimate') or 0.0))
        except Exception:_planned_draw_seconds=0.0
        def report_draw_timer(*,force=False,completed=False):
            if dry_run or execution_measure_started is None:return
            now=clock()
            if not force and now-_draw_timer_last[0]<.50:return
            _draw_timer_last[0]=now
            elapsed=max(0.0,now-execution_measure_started)
            pause_total=paused_seconds+(max(0.0,now-pause_started_at) if pause_started_at is not None else 0.0)
            active_elapsed=max(0.0,elapsed-pause_total)
            session_paths=max(0,progress_total-progress_resumed)
            total_paths=max(1,session_paths)
            planned_remaining=(_planned_draw_seconds*session_paths/progress_total
                               if progress_resumed and progress_total else _planned_draw_seconds)
            if completed:
                predicted=elapsed;remaining=0.0
            else:
                path_projection=(active_elapsed*total_paths/max(1,done)) if done>0 else 0.0
                if path_projection>0:
                    weight=min(.65,max(.15,done/total_paths))
                    predicted_active=max(active_elapsed,((planned_remaining*(1.0-weight)+path_projection*weight) if planned_remaining>0 else path_projection))
                else:
                    predicted_active=max(active_elapsed,planned_remaining)
                remaining=max(0.0,predicted_active-active_elapsed)
                predicted=elapsed+remaining
            report('draw_timer',{'elapsed_seconds':elapsed,'remaining_seconds':remaining,
                                  'predicted_total_seconds':predicted,'done':min(progress_total,progress_resumed+done),'total':progress_total,
                                  'session_done':int(done),'session_total':session_paths,'resumed_paths':progress_resumed,
                                  'active_elapsed_seconds':active_elapsed,'paused_seconds':pause_total,
                                  'state':'completed' if completed else ('paused' if pause_started_at is not None else 'running')})
            # The initial and post-path reports also run outside wait(). A
            # callback may cancel or cross the deadline, including on the last
            # path; that must not turn into a false completed result.
            if not completed:
                if stop.is_set():raise InterruptedError()
                if deadline_box[0] is not None and clock()>=deadline_box[0]:
                    raise InterruptedError('Time limit reached. No automatic restart.')
            return True
        timer_tick=None if dry_run else report_draw_timer
        report_draw_timer(force=True)
        if (plan['options'].get('paint_profile') or stroke_delivery.profile_key in ('gartic-phone','skribbl','skribbl-fast','sketchheads')) and not dry_run:
            report('status',f'{stroke_delivery.label}: <= {stroke_delivery.step_px:.0f}px interpolation, {stroke_delivery.min_path_delay*1000:.2f}ms path floor, palette settle={stroke_delivery.palette_click_delay*1000:.0f}ms, backend={stroke_delivery.drag_backend}.')
        opacity_plan=plan['options'].get('gartic_opacity_plan') or {}
        if opacity_plan and not resume_skip_prelude:
            opacity_target=opacity_plan.get('target_position')
            if opacity_target:
                _opacity_started=clock();_opacity_percent=int(opacity_plan.get('selected_percent',100) or 100)
                click_ui_control(tuple(map(int,opacity_target)),f'Gartic opacity {_opacity_percent}%')
                _opacity_seconds=max(0.0,clock()-_opacity_started)
                note_runtime_operation('opacity_change',_opacity_seconds)
                plan['options']['gartic_opacity_runtime_meta']={'applied':not dry_run,'simulated':bool(dry_run),'percent':_opacity_percent,'seconds':round(_opacity_seconds,5)}
            else:
                plan['options']['gartic_opacity_runtime_meta']={'applied':False,'percent':None,'seconds':0.0,'reason':'current opacity is unknown; slider not verified'}
        brush_plan=plan['options'].get('browser_brush_plan') or {}
        if brush_plan and not resume_skip_prelude:
            target=brush_plan.get('target_position')
            if target:
                target=tuple(map(int,target))
                wanted=int(brush_plan.get('target_index',0) or 0)
                if dry_run:
                    mouse.move(*target);wait(max(.02,stroke_delivery.ui_control_delay*.45))
                    plan['options']['browser_brush_runtime']={'clicked':False,'verified':False,'simulated':True,'effective_px':None}
                    report('status',f"Dry run: automatic browser brush target {brush_plan.get('effective_px','?')} px visited. No selection change was sent.")
                else:
                    from BrowserBrushSize import verify_brush_selection
                    verified=verify_brush_selection(brush_plan,wanted)
                    clicked=not verified
                    if clicked:
                        mouse.move(*target);wait(max(.02,stroke_delivery.ui_control_delay*.35));mouse.click();wait(stroke_delivery.ui_control_delay)
                        verified=verify_brush_selection(brush_plan,wanted)
                    wait(0)
                    effective=int(brush_plan['nominal_sizes'][wanted]) if verified else None
                    plan['options']['browser_brush_runtime']={'clicked':clicked,'verified':verified,'effective_px':effective}
                    if verified:
                        _verified_execution_brush=effective
                        install_brush_guard(effective)
                        report('status',f"Automatic brush size applied and visually verified: ~{brush_plan.get('effective_px','?')} px.")
                    else:
                        report('status',f"Brush selection could not be visually confirmed. Using {_initial_guard_brush} px CanvasGuard fallback.")
            else:
                report('status',f"Automatic brush-size detection was not confident enough to click. Safe CanvasGuard fallback={brush_plan.get('safe_guard_px','?')} px; current browser brush is left untouched.")

        # v1.0.114: optional destructive clear prelude.  It can only run after
        # target activation, CanvasGuard setup and the explicit Start/Dry Run
        # action. Small Test never clears. A compatible render resume skips it
        # so already-finished color batches are not erased.
        clear_enabled=bool(plan['options'].get('auto_clear_canvas'))
        clear_strategy=str(plan['options'].get('canvas_clear_strategy') or 'off')
        if clear_enabled and correction_only_retry:
            report('status','Automatic canvas clear skipped for correction-only retry.')
        elif clear_enabled and resume_skip_prelude:
            report('status','Automatic canvas clear skipped because this is a compatible render resume.')
        elif clear_enabled and plan['options'].get('test_run'):
            report('status','Automatic canvas clear skipped for Small Test.')
        elif clear_enabled:
            if clear_strategy in ('off','pending','unavailable'):
                reason=str(plan['options'].get('canvas_clear_reason') or 'No safe clear method is available.')
                raise InterruptedError('Automatic canvas clear is enabled but cannot run safely. '+reason)
            if clear_strategy=='paint-shortcut':
                if keyboard is None:
                    raise InterruptedError('Automatic Paint canvas clear needs the keyboard backend.')
                if dry_run:
                    report('status','Dry run: Paint Select All → Delete → Esc clear sequence verified logically. No keys were sent.')
                else:
                    report('status','Clearing Microsoft Paint canvas automatically…')
                    guard_keyboard();keyboard.press_and_release('ctrl+a');wait(.08)
                    guard_keyboard();keyboard.press_and_release('delete');wait(.18)
                    guard_keyboard();keyboard.press_and_release('esc');wait(.10)
                    report('status','Microsoft Paint canvas cleared. Starting the new drawing…')
            elif clear_strategy=='native-clear':
                actions=plan['options'].get('canvas_clear_actions') or ()
                if not actions:
                    raise InterruptedError('Automatic canvas clear is enabled, but the calibrated Clear canvas button is missing.')
                for _kind,position in actions:
                    click_ui_control(position,'Clear canvas',.30)
                if dry_run:
                    report('status','Dry run: calibrated Clear canvas control verified. No click was sent.')
                else:
                    report('status','Canvas cleared with the calibrated Clear canvas control.')
            elif clear_strategy=='eraser-sweep':
                actions=plan['options'].get('canvas_clear_actions') or ()
                restore=plan['options'].get('canvas_clear_restore_actions') or ()
                if not actions or not restore:
                    raise InterruptedError('Automatic Eraser clear needs both calibrated Eraser and Brush controls.')
                for _kind,position in actions:
                    click_ui_control(position,'Eraser tool for automatic canvas clear',.22)
                from CanvasClear import eraser_row_spacing
                sx0,sy0,sx1,sy1=canvas_guard.model.safe_bounds
                spacing=eraser_row_spacing(plan['options'].get('brush_px',3))
                rows=list(range(int(sy0),int(sy1)+1,max(1,int(spacing))))
                if not rows or rows[-1]!=int(sy1):rows.append(int(sy1))
                if dry_run and len(rows)>3:
                    rows=[rows[0],rows[len(rows)//2],rows[-1]]
                cleared_segments=0
                for row_index,sy in enumerate(rows):
                    left_to_right=(row_index%2==0)
                    start=(sx0,sy) if left_to_right else (sx1,sy)
                    end=(sx1,sy) if left_to_right else (sx0,sy)
                    pieces=canvas_guard.clip_segment_to_safe(start,end,'automatic eraser sweep')
                    for a,b in pieces:
                        draw_clear_segment(a,b);cleared_segments+=1
                for _kind,position in restore:
                    click_ui_control(position,'Brush restore after automatic canvas clear',.22)
                plan['options']['canvas_clear_runtime']={'strategy':'eraser-sweep','rows':len(rows),'segments':cleared_segments,'spacing_px':spacing,'dry_run':bool(dry_run)}
                if dry_run:
                    report('status',f'Dry run: Eraser sweep sampled {len(rows)} safe row(s); no erase click/drag was sent.')
                else:
                    report('status',f'Automatic Eraser sweep cleared the canvas in {len(rows)} pass(es). Brush restored.')
            else:
                raise InterruptedError(f'Unknown automatic canvas-clear strategy: {clear_strategy}.')
            plan['options']['canvas_clear_runtime']=dict(plan['options'].get('canvas_clear_runtime') or {},strategy=clear_strategy,completed=(not dry_run),dry_run=bool(dry_run))
        if dry_run:
            # The bounded timer starts here so the user gets the advertised full
            # cursor-simulation window; target activation and the 3-second
            # countdown do not consume the route-validation budget.
            deadline_box[0]=clock()+float(plan['options'].get('max_seconds',DRY_RUN_EXECUTION_SECONDS))
            report('status',f'Dry run cursor simulation started. Up to {float(plan["options"].get("max_seconds",DRY_RUN_EXECUTION_SECONDS)):.0f}s; reaching this budget is a normal PASS, not an error.')
        # Tool selection is performed only after the explicit Start/Test action,
        # after the target window is active and the guarded mouse is armed.
        labels={'tool':'Paint tool','brush-menu':'Brushes menu','brush-preset':'Brush preset','opacity':'100% brush opacity',
                'fill':'Fill tool','brush':'Brush tool','eraser':'Eraser tool'}
        fill_meta=plan['options'].get('background_fill_plan') or {}
        if fill_meta.get('enabled') and plan['options'].get('fill_tool_actions') and not skip_canvas_prelude:
            runtime_safety.note_fill('background_fill_planned')
            bg_index=int(fill_meta['color_index'])
            # Choose color first, then the Fill tool. Some browser drawing apps
            # switch back to the brush when a color swatch is clicked.
            select(bg_index)
            for kind,position in plan['options'].get('fill_tool_actions',[]):
                click_ui_control(position,labels.get(kind,'Fill tool'),.24)
            seed=fill_meta.get('seed_pixel',(1,1));seed_point=transform.point(int(seed[0]),int(seed[1]))
            if not canvas_guard.safe.contains_safe(seed_point):
                raise InterruptedError('Safe Fill Mask stopped Background Fill before clicking because the seed is outside the brush-inset safe canvas.')
            seed_point=draw_mouse.move_point(seed_point, 'background fill seed');wait(max(travel_delay,.03))
            if not dry_run:
                draw_mouse.click('background fill click');runtime_safety.note_fill('background_fill_clicks');wait(max(.34,delay))
                try:
                    if hasattr(mouse,'verify_fill'):
                        mouse.verify_fill(seed_point,plan['colors'][bg_index])
                    elif hasattr(mouse,'verify_ink'):
                        mouse.verify_ink(seed_point,plan['colors'][bg_index])
                except InterruptedError as error:
                    raise InterruptedError(f'Background Fill did not render the expected color. {error}') from error
                report('status',f"Background filled first ({fill_meta.get('image_coverage',0)*100:.0f}% source coverage). Restoring the drawing tool…")
            else:
                runtime_safety.note_fill('background_fill_simulated')
                wait(max(.12,delay));report('status','Dry run: background Fill seed verified. No click was sent.')
            for kind,position in plan['options'].get('fill_restore_actions',[]):
                settle=.28 if kind in ('brush-menu','brush-preset') else (.20 if kind in ('tool','brush') else .22)
                click_ui_control(position,labels.get(kind,'Drawing tool'),settle)
        else:
            for kind,position in plan['options'].get('tool_actions',[]):
                settle=.28 if kind in ('brush-menu','brush-preset') else (.20 if kind=='tool' else .22)
                click_ui_control(position,labels.get(kind,'Paint control'),settle)
        # v1.0.41 Better Fill: accepted interior components may be irregular,
        # hole-free closed regions. Snapshot guard pixels *before* drawing the
        # perimeter, draw the traced contour continuously, bucket-fill the safe
        # interior seed, then verify both fill color and outside guards. Any
        # component rejected by planning remains as normal scanline strokes.
        fill_regions=plan['options'].get('fill_regions',[]) or []
        if fill_regions and plan['options'].get('fill_tool_actions') and not skip_canvas_prelude:
            runtime_fill_mask=filter_fill_regions_by_runtime_mask(fill_regions,(width,height),transform,canvas_guard)
            plan['options']['runtime_safe_fill_mask_meta']=runtime_fill_mask.as_dict()
            if runtime_fill_mask.rejected_regions:
                raise InterruptedError('Safe Fill Mask stopped Better Fill before clicking because a planned fill seed, span or contour was outside the brush-inset safe canvas.')
            fill_regions=list(runtime_fill_mask.accepted_regions)
            runtime_safety.note_fill('better_fill_regions', len(fill_regions))
            by_color={}
            for region in fill_regions:
                try:by_color.setdefault(int(region['color_index']),[]).append(region)
                except (KeyError,TypeError,ValueError):continue
            for region_color,items in by_color.items():
                select(region_color)
                guarded=[]
                for region in items:
                    x0,y0,x1,y1=map(int,region['bbox'])
                    probes=[]
                    for raw in region.get('guard_pixels',()) or ():
                        try:
                            sx,sy=map(int,raw)
                            if 0<=sx<width and 0<=sy<height:probes.append(point(sx,sy))
                        except (TypeError,ValueError):pass
                    if not probes:
                        cx,cy=(x0+x1)//2,(y0+y1)//2
                        for sx,sy in ((x0-2,cy),(x1+2,cy),(cx,y0-2),(cx,y1+2)):
                            if 0<=sx<width and 0<=sy<height:probes.append(point(sx,sy))
                    before=mouse.snapshot_colors(probes) if probes and hasattr(mouse,'snapshot_colors') else None
                    for _seal_path in region.get('fill_seal_paths',()) or ():
                        try:_seal_points=[point(int(raw[0]),int(raw[1])) for raw in _seal_path]
                        except (TypeError,ValueError,IndexError):continue
                        for _seal_a,_seal_b in zip(_seal_points,_seal_points[1:]):
                            draw_segment(_seal_a,_seal_b)
                    contour=region.get('contour') or ()
                    if contour:
                        draw_closed_contour(contour)
                    else:
                        # Legacy v1.0.7 plans remain compatible.
                        corners=[point(x0,y0),point(x1,y0),point(x1,y1),point(x0,y1)]
                        for a,b in zip(corners,corners[1:]+corners[:1]):draw_segment(a,b)
                    guarded.append((region,probes,before))
                for kind,position in plan['options'].get('fill_tool_actions',[]):
                    click_ui_control(position,labels.get(kind,'Fill tool'),.22)
                for region,probes,before in guarded:
                    seed=region.get('seed_pixel',(1,1));seed_point=point(int(seed[0]),int(seed[1]))
                    draw_mouse.move_point(seed_point, 'better fill seed');wait(max(travel_delay,.02))
                    expected=plan['colors'][region_color]
                    if dry_run:
                        runtime_safety.note_fill('better_fill_simulated')
                        wait(max(.08,delay))
                    else:
                        draw_mouse.click('better fill click');runtime_safety.note_fill('better_fill_clicks');wait(max(.24,delay))
                        if hasattr(mouse,'verify_fill'):mouse.verify_fill(seed_point,expected)
                        if probes and before is not None and hasattr(mouse,'verify_unchanged'):
                            try:mouse.verify_unchanged(probes,before)
                            except InterruptedError as error:
                                raise InterruptedError('Better Fill detected color outside the protected region. The fill was stopped to prevent a canvas flood.') from error
                for kind,position in plan['options'].get('fill_restore_actions',[]):
                    settle=.28 if kind in ('brush-menu','brush-preset') else (.20 if kind in ('tool','brush') else .22)
                    click_ui_control(position,labels.get(kind,'Drawing tool'),settle)
                strategies={str(r.get('strategy','rectangle')) for r in items}
                report('status',f'Better Fill completed {len(items)} safe region(s) for one grouped color ({", ".join(sorted(strategies))}). Continuing with detail strokes…')
        done = 0
        speed_measure_started=clock()
        human_mode=plan['options'].get('human_mode','Off')
        human_seed=stable_seed(plan['groups'],human_mode)
        cadence=HumanCadence(human_mode,human_seed)
        verified_colors=set()
        visual_mode=plan['options'].get('visual_verification_resolved') or resolve_visual_verification(
            plan['options'].get('visual_verification','Off'),
            paint_profile=bool(plan['options'].get('visual_verification_enabled',False)),
            dry_run=dry_run,test=False)
        edge_mode=runtime_edge_mode
        plan['options'].setdefault('edge_behavior_meta',{'active':True,'mode':edge_mode,'hard_clip':0,'hard_skip':0,'adaptive_boundary':0,'preserve_outline_boundary':0,'safe_skip':0})
        resume_input_generation=0
        restored_input_generation=0

        def pause_guard():
            nonlocal paused_seconds,pause_started_at,resume_input_generation,execution_pause_count
            if not paused.is_set():
                return False
            resume_input_generation+=1
            execution_pause_count+=1
            verified_colors.clear()
            exact_color_samples.clear()
            for cached_color in (color_session_cache.values() if isinstance(color_session_cache,dict) else ()):
                if isinstance(cached_color,dict):cached_color.pop('sample',None)
            pause_started=clock()
            pause_started_at=pause_started
            try:
                if not dry_run:mouse.release()
                if hasattr(mouse,'reset_tracking'):mouse.reset_tracking()
                report('status', 'Paused. The mouse is free. Press F6 or Resume to continue.')
                while paused.is_set():
                    wait(.05)
                for second in (3, 2, 1):
                    report('status', f'Resuming in {second}… Switch to the drawing application.')
                    wait(1)
                return True
            finally:
                paused_seconds+=max(0.0,clock()-pause_started)
                pause_started_at=None

        def draw_path_item(index,item,smart_group=True,verify_color=True,verification_mode='strict',count_progress=True,slow_probe=False,screen_points=None):
            nonlocal done,sent_paths,guard_skipped_paths,restored_input_generation,_verified_execution_brush
            if stop.is_set():
                raise InterruptedError()
            pause_guard()
            if restored_input_generation!=resume_input_generation:
                # A pause explicitly frees the mouse. The user may have changed
                # the selected colour/tool; cached brush and ink evidence no
                # longer authorizes assuming the previous target state.
                for kind,position in plan['options'].get('tool_actions',()):
                    click_ui_control(position,labels.get(kind,'drawing tool'),.22)
                _verified_execution_brush=None
                install_brush_guard(_initial_guard_brush)
                switch_execution_brush(current_execution_brush)
                selected_method=select(index)
                restored_input_generation=resume_input_generation
                if plan['options'].get('adaptive_color_verification',False) and verification_mode!='adaptive':
                    verify_color_batch(index,item,smart_group,selected_method,0,0)
                else:
                    verify_color=bool(verify_color or plan['options'].get('strict_color_verification',True))
            if screen_points is not None:
                # Internal verification probes may already be derived from a
                # guarded physical subpath. Reapply the same guard below.
                raw_canvas_points=list(screen_points)
            elif smart_group:
                raw_canvas_points=[transform.point(x,y) for x,y in item]
            else:
                stroke=item
                raw_canvas_points=[transform.point(*stroke[:2]),transform.point(*stroke[2:])]
            try:
                edge_result=apply_edge_behavior(canvas_guard, raw_canvas_points, behavior=edge_mode,
                                                profile_name=plan['options'].get('profile_name'),
                                                drawing_mode=plan['options'].get('drawing_mode'),
                                                outline=bool(plan['options'].get('outline')),
                                                context='normal stroke',cancelled=stop.is_set)
            except CanvasSafetyStop as error:
                runtime_safety.note_blocked(error, reason='CanvasGuard blocked a planned stroke outside the selected canvas polygon.')
                raise
            runtime_safety.note_edge_result(edge_result, raw_canvas_points)
            edge_meta=plan['options'].setdefault('edge_behavior_meta',{'active':True,'mode':edge_mode})
            edge_meta['mode']=edge_mode
            edge_meta[edge_result.strategy]=int(edge_meta.get(edge_result.strategy,0))+1
            edge_meta['last']=edge_result.as_dict()
            clipped_subpaths=edge_result.subpaths
            if not clipped_subpaths:
                if count_progress:
                    done += 1
                    guard_skipped_paths += 1
                    if done % progress_every == 0 or progress_resumed+done == progress_total:
                        report_execution_progress()
                        report_draw_timer()
                return {'matched': False, 'skipped': True, 'available':False, 'reason': 'outside safe canvas'}
            if (not dry_run and verification_mode!='adaptive' and index not in verified_colors
                    and plan['options'].get('adaptive_color_verification',False)
                    and not plan['options'].get('paint_current_color')):
                raise InterruptedError('Color verification needs a drawable probe before painting this path. Adjust the canvas boundary or brush width, then retry.')
            # Longest actually drawable segment is the most useful read-only
            # delivery probe. Short dots are deliberately excluded because a
            # one-pixel sample cannot distinguish a missed event reliably.
            from StrokeProbeGeometry import representative_segment
            delivery_start,delivery_end=representative_segment(clipped_subpaths,cancelled=stop.is_set)

            def deliver_current_stroke(*, retry=False):
                retry_cfg=(delivery_retry_parameters(delivery_verify_policy,stroke_step_px,effective_path_delay) if retry else None)
                step_px=(retry_cfg['step_px'] if retry_cfg else stroke_step_px)
                step_px=interpolation_step(step_px,current_execution_brush,
                    pixel_accurate=bool(plan['options'].get('pixel_accurate')))
                path_delay_now=(retry_cfg['path_delay'] if retry_cfg else effective_path_delay)
                press_settle_now=(retry_cfg['press_settle'] if retry_cfg else stroke_delivery.press_settle)
                release_settle_now=(retry_cfg['release_settle'] if retry_cfg else stroke_delivery.release_settle)
                if slow_probe:
                    step_px=min(float(step_px),2.0);path_delay_now=max(path_delay_now,.02)
                    press_settle_now=max(press_settle_now,.08);release_settle_now=max(release_settle_now,.05)
                for subpath_index,subpath in enumerate(clipped_subpaths):
                    sub_start=draw_mouse.move_point(subpath[0], 'stroke clipped retry start' if retry else 'stroke clipped start'); wait(cadence.movement_delay(travel_delay,0,1))
                    if len(subpath)==1 or all(p==sub_start for p in islice(subpath,1,None)):
                        if not dry_run:draw_mouse.click('stroke clipped retry dot' if retry else 'stroke clipped dot')
                        continue
                    if dry_run:
                        for segment_index,(segment_start,segment_end) in enumerate(pairwise(subpath)):
                            if segment_start==segment_end:continue
                            path_points=precision_path(segment_start,segment_end,precision,step_px)
                            for path_index,path_point in enumerate(path_points):
                                draw_mouse.move_point(path_point, 'stroke clipped path');wait(max(stroke_delivery.min_path_delay, cadence.movement_delay(path_delay_now,path_index,len(path_points))))
                    else:
                        try:
                            draw_mouse.press('stroke clipped retry press' if retry else 'stroke clipped press')
                            if press_settle_now:wait(press_settle_now)
                            for segment_index,(segment_start,segment_end) in enumerate(pairwise(subpath)):
                                if segment_start==segment_end:continue
                                path_points=precision_path(segment_start,segment_end,precision,step_px)
                                for path_index,path_point in enumerate(path_points):
                                    draw_mouse.move_point(path_point, 'stroke clipped retry path' if retry else 'stroke clipped path');wait(max(stroke_delivery.min_path_delay, cadence.movement_delay(path_delay_now,path_index,len(path_points))))
                        finally:
                            try:
                                if release_settle_now:wait(release_settle_now)
                            finally:
                                draw_mouse.release()

            deliver_current_stroke(retry=False)
            wait(cadence.movement_delay(boundary_delay,0,1))

            # HTML5 canvas delivery can occasionally drop a mouse-down/move
            # sequence even though Windows accepted the cursor events. Confirm
            # the just-drawn stroke and retry only that path once when needed.
            if delivery_verify_policy.enabled and not dry_run:
                delivery_result=inspect_stroke_delivery(mouse,delivery_start,delivery_end,plan['colors'][index],
                                                       current_execution_brush,delivery_verify_policy)
                if delivery_result.get('checked'):
                    delivery_verify_meta['checked']=int(delivery_verify_meta.get('checked',0))+1
                    if delivery_result.get('matched'):
                        delivery_verify_meta['passed']=int(delivery_verify_meta.get('passed',0))+1
                    else:
                        delivery_verify_meta['suspected']=int(delivery_verify_meta.get('suspected',0))+1
                        recovered=False
                        for retry_no in range(1,int(delivery_verify_policy.retry_cap)+1):
                            delivery_verify_meta['retried']=int(delivery_verify_meta.get('retried',0))+1
                            report('status',f'Stroke delivery check: suspected missed/partial browser stroke. Retrying only this stroke ({retry_no}/{delivery_verify_policy.retry_cap}) with safer spacing.')
                            deliver_current_stroke(retry=True)
                            wait(delivery_verify_policy.verify_settle)
                            retry_result=inspect_stroke_delivery(mouse,delivery_start,delivery_end,plan['colors'][index],
                                                                current_execution_brush,delivery_verify_policy)
                            if retry_result.get('matched'):
                                recovered=True
                                delivery_verify_meta['recovered']=int(delivery_verify_meta.get('recovered',0))+1
                                report('status','Stroke delivery check recovered the suspected browser stroke with one bounded retry.')
                                break
                            delivery_result=retry_result
                        if not recovered:
                            delivery_verify_meta['failed']=int(delivery_verify_meta.get('failed',0))+1
                            actual=tuple(delivery_result.get('actual') or ())
                            raise StrokeDeliveryVerificationError(
                                f'Stroke delivery verification failed after {delivery_verify_policy.retry_cap} retry. '
                                f'Expected RGB {tuple(plan["colors"][index])}; closest rendered RGB was {actual}. '
                                'The failed path was not marked complete, so Smart Recovery can resume from it safely.')
                else:
                    delivery_verify_meta['skipped']=int(delivery_verify_meta.get('skipped',0))+1

            verification=None
            if (not dry_run) and verify_color and not plan['options'].get('paint_current_color'):
                wait(.12)
                verify_start,verify_end=delivery_start,delivery_end
                if verification_mode=='adaptive' and hasattr(mouse,'inspect_ink_segment'):
                    verification=mouse.inspect_ink_segment(verify_start,verify_end,plan['colors'][index],current_execution_brush,
                                                           plan['options'].get('color_verification_tolerance',48))
                    if not isinstance(verification,dict) or verification.get('matched') is not True:
                        return verification
                else:
                    try:
                        if hasattr(mouse,'verify_ink_segment'):
                            mouse.verify_ink_segment(verify_start,verify_end,plan['colors'][index],current_execution_brush)
                        elif hasattr(mouse,'verify_ink'):
                            mouse.verify_ink(tuple(round((verify_start[i]+verify_end[i])/2) for i in (0,1)),plan['colors'][index])
                        elif verification_mode=='adaptive':
                            raise InterruptedError('The input backend cannot verify the rendered ink.')
                    except InterruptedError as error:
                        selected_tool=plan['options'].get('paint_tool','Use current tool')
                        speed_hint=(' Fast mode can outrun some drawing applications; retry Balanced or Safe if the tool calibration is correct.'
                                    if speed_name=='Fast' else '')
                        if selected_tool=='Use current tool':
                            raise InterruptedError(
                                f'{error} Image Draw Bot is set to Use current tool, so it cannot force Paint to use solid ink. '
                                'Choose Auto (recommended) or Pencil in Image Draw Bot, calibrate Pencil, then retry.'+speed_hint
                            ) from error
                        raise InterruptedError(
                            f'{error} Automatic Paint tool selection was enabled. Recalibrate Paint tools because the saved tool position may no longer match this Paint version or window layout.'+speed_hint
                        ) from error
                    verification={'matched':True,'expected':tuple(plan['colors'][index]),'actual':tuple(plan['colors'][index]),'error':0,'confidence':100.0,'sample_count':0}
                # Adaptive probes still have a caller-side perceptual gate.
                # Only that gate may approve the color or publish its cache.
                if verification_mode!='adaptive':verified_colors.add(index)

            if not dry_run:
                selectors=plan.get('color_selectors') or ()
                if verification_mode!='adaptive' and index < len(selectors) and selectors[index].get('kind')=='custom' and (verification is None or verification.get('matched')):
                    rgb=tuple(map(int,selectors[index].get('rgb',(0,0,0))))
                    if rgb not in exact_color_samples:
                        a,b=delivery_start,delivery_end
                        exact_color_samples[rgb]=(round((a[0]+b[0])/2),round((a[1]+b[1])/2))
            if count_progress:
                done += 1
                if not dry_run:sent_paths += 1
                natural_pause=cadence.boundary_pause(done)
                if natural_pause:wait(natural_pause)
                report_execution_progress()
                report_draw_timer()
            return verification

        def verify_color_batch(index,item,smart_group,selected_method,color_number,total_colors):
            """Paint one tiny overwrite-safe probe and auto-recover selector errors."""
            if dry_run or plan['options'].get('paint_current_color') or not plan['options'].get('adaptive_color_verification',False):
                return selected_method
            probe=probe_item(item,smart_group,plan['options'].get('color_probe_source_span',4))
            selectors=plan.get('color_selectors') or ()
            selector=selectors[index] if index<len(selectors) else {'kind':'palette','palette_index':index}
            actions=plan['options'].get('exact_color_actions') or {}
            rgb=tuple(map(int,plan['colors'][index]))
            cache=color_session_cache.get(rgb_key(rgb),{}) if isinstance(color_session_cache,dict) else {}
            methods=method_candidates(selector,actions,has_sample=(rgb in exact_color_samples or bool(cache.get('sample'))),
                                      keyboard_available=keyboard is not None,cached_method=cache.get('method'),
                                      allow_exact_palette_recovery=(plan['options'].get('profile_name')=='Microsoft Paint'))
            ordered=[]
            for candidate in (selected_method,)+tuple(methods):
                if candidate and candidate not in ordered:ordered.append(candidate)
            paint_retry=(plan['options'].get('profile_name')=='Microsoft Paint' and
                         plan['options'].get('effective_paint_tool',plan['options'].get('paint_tool'))=='Pencil' and
                         bool(plan['options'].get('tool_actions')) and ordered==['palette'])
            if paint_retry:ordered.append('palette')
            last=None;screen_probe=None
            for attempt,method in enumerate(ordered,1):
                if paint_retry and attempt==2:
                    for kind,position in plan['options']['tool_actions']:
                        click_ui_control(position,labels.get(kind,'Pencil'),.22)
                    report('status','Retrying the same small probe once with calibrated Pencil and slower input. Colour tolerance is unchanged.')
                actual_method=selected_method if attempt==1 else select(index,method)
                if attempt>1:
                    report('status',f'Color {color_number}/{total_colors} · RGB {rgb}: retry {attempt}/{len(ordered)} with {method_label(actual_method)}.')
                result=draw_path_item(index,probe,smart_group=smart_group,verify_color=True,verification_mode='adaptive',count_progress=False,slow_probe=bool(paint_retry and attempt==2),screen_points=screen_probe)
                if isinstance(result,dict) and result.get('skipped') is True and screen_probe is None:
                    # A short source probe may lie entirely outside the inset
                    # even though its full scanline crosses the safe canvas.
                    # Derive a short segment from the same guarded full path;
                    # never widen the boundary to obtain verification pixels.
                    raw=([transform.point(x,y) for x,y in item] if smart_group else
                         [transform.point(*item[:2]),transform.point(*item[2:])])
                    drawable=apply_edge_behavior(canvas_guard,raw,behavior=edge_mode,
                        profile_name=plan['options'].get('profile_name'),
                        drawing_mode=plan['options'].get('drawing_mode'),
                        outline=bool(plan['options'].get('outline')),
                        context='normal stroke',cancelled=stop.is_set).subpaths
                    if drawable:
                        span=float(plan['options'].get('color_probe_source_span',4))*max(fw/width,fh/height)
                        screen_probe=probe_item(drawable[0],True,span)
                        result=draw_path_item(index,probe,smart_group=smart_group,verify_color=True,
                            verification_mode='adaptive',count_progress=False,
                            slow_probe=bool(paint_retry and attempt==2),screen_points=screen_probe)
                if isinstance(result,dict) and result.get('skipped') is True:
                    # Nothing was painted or sampled. Keep this color pending;
                    # the next drawable path must run its own real probe.
                    report('color_plan',{'current':color_number,'total':total_colors,'rgb':rgb,
                        'method':method_label(actual_method),'matched':False,'available':False,
                        'confidence':0.0,'actual':(),'reason':'No drawable color probe in this path.'})
                    return actual_method
                last=result if isinstance(result,dict) and result else {
                    'matched':False,'available':False,'confidence':0.0,'actual':(),
                    'reason':'Rendered color evidence was unavailable.'}
                if plan['options'].get('profile_name')=='Microsoft Paint' and last.get('actual'):
                    try:
                        from PaintColorVerifier import verify_paint_color
                        pv=verify_paint_color(rgb,last.get('actual'),context='rendered')
                        last=dict(last);last['delta_e2000']=pv.delta_e2000
                        if last.get('matched') and not pv.accepted:
                            last['matched']=False
                            last['reason']=f'Perceptual Paint verification rejected the rendered color (DeltaE2000 {pv.delta_e2000:.2f}, L* error {pv.lightness_error:.2f}).'
                    except Exception:
                        pass
                log_event(f'Colour probe {attempt}/{len(ordered)}: method={actual_method} expected={rgb} actual={last.get("actual")} matched={last.get("matched")} deltaE2000={float(last.get("delta_e2000",0) or 0):.2f} reason={last.get("reason","")}.')
                report('color_plan',{'current':color_number,'total':total_colors,'rgb':rgb,'method':method_label(actual_method),
                                     'confidence':float(last.get('confidence',0)),'actual':tuple(last.get('actual') or ()),'matched':bool(last.get('matched'))})
                if last.get('matched'):
                    verified_colors.add(index)
                    if isinstance(color_session_cache,dict):
                        color_session_cache[rgb_key(rgb)]={'method':actual_method,'confidence':float(last.get('confidence',0)),
                                                          'actual':tuple(last.get('actual') or ()),
                                                          'sample':tuple(exact_color_samples.get(rgb)) if rgb in exact_color_samples else None}
                    if plan['options'].get('profile_name')=='Microsoft Paint' and actual_method in ('numeric','spectrum','eyedropper'):
                        try:
                            from ColorCache import put_verified
                            from ColorFidelity import delta_e2000
                            actual_rgb=tuple(last.get('actual') or rgb)
                            put_verified(plan['options'].get('profile_key','microsoft-paint'),rgb,actual_rgb,
                                         delta_e2000=delta_e2000(rgb,actual_rgb),method=actual_method,
                                         confidence=float(last.get('confidence',0)),
                                         context_fingerprint=plan['options'].get('calibration_fingerprint'),
                                         workflow=plan['options'].get('custom_color_workflow',''))
                        except Exception as cache_error:
                            log_event(f'Verified Paint color cache skipped: {cache_error!r}')
                    report('status',f'Color {color_number}/{total_colors} · RGB {rgb}: {method_label(actual_method)} verified at {confidence_text(last)}. Painting the full color batch now.')
                    return actual_method
                report('status',f'Color {color_number}/{total_colors} · RGB {rgb}: {method_label(actual_method)} rendered {tuple(last.get("actual") or ())} ({float(last.get("confidence",0)):.0f}% match). Trying the next safe color method.')
            selected_tool=plan['options'].get('paint_tool','Use current tool')
            actual=tuple((last or {}).get('actual') or ())
            confidence=float((last or {}).get('confidence',0))
            raise InterruptedError(
                f'Stopped on color batch {color_number}/{total_colors}: RGB {rgb} could not be verified after adaptive recovery. '
                f'Closest rendered RGB was {actual} ({confidence:.0f}% match). Previously completed color batches remain painted. '
                f'{(last or {}).get("reason","")} This is a verification stop, not a crash. '
                + ('Run Auto Paint calibration and retry. If this color is outside the normal Paint palette, run Custom color palette for picture so Image Draw Bot can calibrate and select the image RGB colors.' if selected_tool!='Use current tool' else 'Verify the current Paint tool and selected color, then retry.'))

        def begin_visual_verification(total_colors):
            nonlocal visual_previous_snapshot
            if (not dry_run) and plan['options'].get('visual_verification_enabled',False) and visual_mode!='Off' and hasattr(mouse,'snapshot_canvas'):
                try:
                    visual_previous_snapshot=mouse.snapshot_canvas(area)
                    report('visual_verification',{'current':0,'total':total_colors,'ok':True,'confidence':100.0,'summary':'baseline snapshot captured'})
                except InterruptedError:
                    raise
                except Exception as error:
                    plan['options']['visual_verification_enabled']=False
                    report('visual_verification',{'current':0,'total':total_colors,'ok':False,'checked':False,'available':False,'confidence':0.0,'summary':f'visual baseline unavailable: {error}'})

        def visual_verify_color_batch(index, ordered_items, smart_group, color_number, total_colors, *, brush_px=None):
            nonlocal visual_previous_snapshot
            if dry_run or not plan['options'].get('visual_verification_enabled',False) or visual_mode=='Off':
                return None
            if not hasattr(mouse,'snapshot_canvas'):
                return {'current':color_number,'total':total_colors,'ok':False,'checked':False,'available':False,'confidence':0.0,'summary':'not checked: snapshot unavailable on this mouse backend'}
            sample_limit={'Fast':80,'Balanced':130,'Strict':180}.get(visual_mode,130)
            if brush_px is None:brush_px=plan['options'].get('brush_px',1)
            expected=plan['colors'][index]
            planned_points=planned_batch_points(ordered_items,smart_group=smart_group,transform=point,sample_limit=sample_limit,cancelled=stop.is_set)
            expected_boxes=planned_batch_boxes(ordered_items,smart_group=smart_group,transform=point,brush_px=brush_px,cancelled=stop.is_set)
            wait(.08)
            current=mouse.snapshot_canvas(area)
            try:
                result=compare_batch_snapshot(current,visual_previous_snapshot,area,expected,planned_points,expected_boxes,brush_px=brush_px,mode=visual_mode,cancelled=stop.is_set)
            except BaseException:
                current.close()
                raise
            if visual_previous_snapshot is not None and visual_previous_snapshot is not current:
                visual_previous_snapshot.close()
            visual_previous_snapshot=current
            summary=summarize_result(result)
            payload=dict(result);payload.update({'current':color_number,'total':total_colors,'rgb':tuple(map(int,expected)),'summary':summary})
            _visual_meta=plan['options'].setdefault('visual_verification_runtime_meta',{
                'batches':0,'passed_batches':0,'failed_batches':0,'sampled_points':0,'matched_points':0,
                'confidence_total':0.0,'outside_change_samples':0})
            _visual_meta['batches']=int(_visual_meta.get('batches',0) or 0)+1
            _visual_meta['passed_batches']=int(_visual_meta.get('passed_batches',0) or 0)+(1 if result.get('ok') else 0)
            _visual_meta['failed_batches']=int(_visual_meta.get('failed_batches',0) or 0)+(0 if result.get('ok') else 1)
            _visual_meta['sampled_points']=int(_visual_meta.get('sampled_points',0) or 0)+int(result.get('sampled_points',0) or 0)
            _visual_meta['matched_points']=int(_visual_meta.get('matched_points',0) or 0)+int(result.get('matched_points',0) or 0)
            _visual_meta['confidence_total']=float(_visual_meta.get('confidence_total',0) or 0)+float(result.get('confidence',0) or 0)
            _visual_meta['outside_change_samples']=int(_visual_meta.get('outside_change_samples',0) or 0)+int(result.get('changed_outside_samples',0) or 0)
            _visual_meta['average_confidence']=round(float(_visual_meta['confidence_total'])/max(1,int(_visual_meta['batches'])),2)
            _visual_meta['match_rate']=round(float(_visual_meta['matched_points'])/max(1,int(_visual_meta['sampled_points'])),4)
            if not result.get('ok'):
                report('visual_verification',payload)
                raise InterruptedError(
                    f'Visual verification stopped after color batch {color_number}/{total_colors}. {summary}. '
                    'The canvas may have a wrong color, missed region, leaked fill or misplaced stroke. '
                    'Previously completed render checkpoint data remains available; inspect the canvas before resuming.')
            return payload

        def publish_correction_review():
            try:
                from CorrectionReviewRecovery import build_correction_review_state
                review=build_correction_review_state(plan.get('options') or {}, can_snapshot=hasattr(mouse,'snapshot_canvas'),
                                                     strict_safety_ready=True, full_start_unlocked=False)
                plan['options']['correction_review_meta']=review
                report('correction_review',review)
                return review
            except Exception as review_error:
                log_event(f'Step 15 correction review refresh skipped safely: {review_error!r}')
                return {}

        def run_post_draw_correction_pass(initial_meta, actual_elapsed):
            """Step 14: one bounded safe correction pass after real-result scoring."""
            if dry_run or stop.is_set() or not hasattr(mouse,'snapshot_canvas'):
                return None
            if bool(plan['options'].get('_post_draw_correction_ran')):
                return None
            snapshot=None
            try:
                from PIL import Image
                source=plan['options'].get('_accuracy_original_source')
                if not isinstance(source,Image.Image):
                    return None
                acceptance=plan['options'].get('auto_tuner_acceptance_meta') or {}
                gates=acceptance.get('gates') if isinstance(acceptance.get('gates'),dict) else {}
                usable=acceptance.get('usable_deadline_seconds')
                visual_gate=gates.get('visual_accuracy_min_percent')
                elapsed=max(.001,float(actual_elapsed or 0.0))
                if usable is None and not plan['options'].get('unlimited_time'):
                    usable=plan['options'].get('max_seconds')
                if usable is not None and float(usable)-elapsed < 1.25:
                    plan['options']['post_draw_correction_meta']={'enabled':False,'safe':True,'reason':'not enough deadline headroom for correction pass','stores_image_data':False}
                    publish_correction_review()
                    return None
                snapshot=mouse.snapshot_canvas(area)
                compare_size=tuple(map(int,getattr(plan.get('image'),'size',plan.get('plan_area') or (max(1,int(fw)),max(1,int(fh))))))
                layers=plan.get('ui_previews') if isinstance(plan.get('ui_previews'),dict) else {}
                # Convert Step 10 preview-sized diagnostic layers back to planning
                # coordinates before extracting correction strokes.
                simulated=plan.get('preview')
                quantized=layers.get('quantized_target')
                from PostDrawCorrectionPass import build_post_draw_correction_plan, compact_correction_meta
                try:
                    from CorrectionHistory import compact_result_metrics
                    if isinstance(initial_meta, dict) and not plan['options'].get('post_draw_before_correction_accuracy_meta'):
                        plan['options']['post_draw_before_correction_accuracy_meta'] = compact_result_metrics(initial_meta)
                except Exception as history_error:
                    log_event(f'Step 16 before-correction metric capture skipped safely: {history_error!r}')
                estimate=plan.get('draw_time_estimate') if isinstance(plan.get('draw_time_estimate'),dict) else {}
                per_path=None
                try:
                    if correction_only_retry:
                        per_path=plan['options'].get('post_draw_correction_reference_seconds_per_path')
                    else:
                        projected=float(estimate.get('projected_seconds') or plan.get('estimate') or 0)
                        per_path=projected/max(1,int(plan.get('count') or 1))
                except Exception:
                    per_path=None
                correction=build_post_draw_correction_plan(
                    original_source=source, palette_rgb=plan.get('colors') or (),
                    post_draw_meta=initial_meta if isinstance(initial_meta,dict) else plan['options'].get('post_draw_accuracy_meta'),
                    snapshot=snapshot, area=area, fitted=(fw,fh), comparison_size=compare_size,
                    simulated_final=simulated, quantized_target=quantized, options={**plan['options'], 'brush_px':current_execution_brush},
                    usable_deadline_seconds=None if usable is None else float(usable), elapsed_seconds=elapsed,
                    visual_gate_percent=visual_gate, estimated_seconds_per_path=per_path,
                    max_paths=int(plan['options'].get('post_draw_correction_max_paths',120) or 120),
                    max_pixels=int(plan['options'].get('post_draw_correction_max_pixels',6000) or 6000),
                    max_area_fraction=float(plan['options'].get('post_draw_correction_max_area_fraction',0.10) or 0.10),
                    cancelled=lambda: stop.is_set())
                compact=compact_correction_meta(correction)
                plan['options']['post_draw_correction_meta']=compact
                publish_correction_review()
                if not correction.get('enabled') or not correction.get('safe'):
                    if correction.get('reason'):
                        report('status',f"Post-draw correction skipped: {correction.get('reason')}")
                    return compact
                execution_groups=correction.get('execution_groups') or []
                color_order=[int(i) for i in (correction.get('color_order') or range(len(execution_groups))) if 0<=int(i)<len(execution_groups) and execution_groups[int(i)]]
                if not color_order:
                    compact['enabled']=False;compact['reason']='no executable correction paths'
                    plan['options']['post_draw_correction_meta']=compact
                    publish_correction_review()
                    return compact
                report('status',f"Post-draw correction pass: {int(correction.get('correction_paths',0))} bounded path(s), {int(correction.get('selected_correction_pixels',0))} pixel(s), no image data saved.")
                executed=0;executed_color_indices=set();selected_index=None;selected_method=None;stopped_early=False
                for index in color_order:
                    if stop.is_set():
                        stopped_early=True;break
                    # Keep deadline reserve strict: correction is opportunistic and
                    # must never consume the app/game safety margin.
                    if usable is not None and clock()-execution_measure_started >= max(0.0,float(usable)-0.45):
                        stopped_early=True;break
                    pause_guard()
                    if selected_index!=index:
                        selected_method=select(index,selected_method);selected_index=index
                    for item in execution_groups[index]:
                        if stop.is_set():
                            stopped_early=True;break
                        if usable is not None and clock()-execution_measure_started >= max(0.0,float(usable)-0.45):
                            stopped_early=True;break
                        adaptive=plan['options'].get('adaptive_color_verification',False)
                        if index not in verified_colors and adaptive:
                            selected_method=verify_color_batch(index,item,True,selected_method,len(executed_color_indices)+1,len(color_order))
                        correction_result=draw_path_item(index,item,smart_group=True,
                            verify_color=(index not in verified_colors and not adaptive and plan['options'].get('strict_color_verification',True)),
                            count_progress=False)
                        if not (isinstance(correction_result,dict) and correction_result.get('skipped') is True):
                            executed+=1;executed_color_indices.add(index)
                    if stopped_early:
                        break
                executed_colors=len(executed_color_indices)
                compact.update({'executed_paths':executed,'executed_colors':executed_colors,'stopped_early':bool(stopped_early)})
                plan['options']['post_draw_correction_meta']=compact
                publish_correction_review()
                plan['options']['_post_draw_correction_ran']=True
                report('status',f"Post-draw correction completed: {executed}/{int(correction.get('correction_paths',0))} path(s) across {executed_colors} color(s).")
                # Re-score after correction.  The new metrics replace the first
                # snapshot for Auto Tuner feedback, but only compact numbers are kept.
                try:
                    final_elapsed=max(.001,clock()-execution_measure_started)
                    final_meta=capture_post_draw_accuracy(final_elapsed)
                    if isinstance(final_meta,dict):
                        compact['post_correction_visual_accuracy_percent']=final_meta.get('visual_accuracy_percent')
                        compact['post_correction_actual_coverage_percent']=final_meta.get('actual_coverage_percent')
                        compact['post_correction_trust']=final_meta.get('feedback_trust')
                        compact['post_correction_confidence_percent']=final_meta.get('confidence_percent')
                        plan['options']['post_draw_correction_meta']=compact
                        publish_correction_review()
                except InterruptedError:
                    raise
                except Exception as score_error:
                    log_event(f'Step 14 post-correction scoring skipped safely: {score_error!r}')
                return compact
            except InterruptedError:
                raise
            except Exception as error:
                meta={'enabled':False,'safe':True,'reason':str(error)[:240],'stores_image_data':False,'capture_pixels_persisted':False,'image_pixels_persisted':False}
                plan['options']['post_draw_correction_meta']=meta
                publish_correction_review()
                log_event(f'Step 14 post-draw correction skipped safely: {error!r}')
                return meta
            finally:
                if snapshot is not None and isinstance(snapshot,Image.Image):snapshot.close()

        def checkpoint_recoverable_path(error, *, color_number, path_index, ordered_items):
            """Persist only the first not-completed path for a transient browser stop."""
            if dry_run or checkpoint is None:
                return False
            try:
                from SmartRecovery import classify_interruption
                decision=classify_interruption(error,str(plan['options'].get('profile_key') or ''))
            except Exception:
                return False
            plan['options']['smart_recovery_last_decision']=decision.as_dict()
            if not decision.recoverable:
                return False
            progress=checkpoint_before_path(plan,color_number,path_index,len(ordered_items),ordered_items=ordered_items,prelude_complete=True)
            checkpoint(progress)
            plan['options']['smart_recovery_checkpoint']=progress
            report('status',
                   f'Smart Recovery saved color {color_number}/{progress.get("total_colors",0)} · next safe path {path_index+1}/{len(ordered_items)}. '
                   'No automatic mouse restart will occur. Press Start again; browser Auto-Recalibration + Visual Preflight will run before resuming.')
            return True

        current_execution_brush=_verified_execution_brush or max(1,int(plan['options'].get('brush_px',1) or 1))
        def switch_execution_brush(wanted_px):
            """Switch only between verified controls and atomically install its brush-specific CanvasGuard."""
            nonlocal current_execution_brush, _verified_execution_brush
            wanted=max(1,int(wanted_px or current_execution_brush))
            brush_plan=plan['options'].get('browser_brush_plan') or {}
            if wanted==current_execution_brush and (not brush_plan or dry_run or wanted==_verified_execution_brush):return False
            try:
                positions=[tuple(map(int,p)) for p in (brush_plan.get('control_positions') or ())]
                sizes=[max(1,int(v)) for v in (brush_plan.get('nominal_sizes') or ())]
                confidence=float(brush_plan.get('confidence',0) or 0)
            except (TypeError,ValueError):
                return False
            if not brush_plan.get('target_position') or confidence<.58 or len(positions)!=len(sizes) or not sizes:
                return False
            index=min(range(len(sizes)),key=lambda i:abs(sizes[i]-wanted))
            effective=int(sizes[index]);position=positions[index]
            verified_sizes=[]
            try:verified_sizes=[max(1,int(v)) for v in (brush_plan.get('verified_sizes') or ())]
            except (TypeError,ValueError):verified_sizes=[]
            # New rc4 plans prove every usable control independently, so safety is
            # enforced by a fresh CanvasGuard for the *actual* brush. Legacy plans
            # keep the old global-guard ceiling.
            if verified_sizes:
                if effective not in verified_sizes:return False
            elif effective>max(1,int(plan['options'].get('canvas_guard_brush_px',current_execution_brush) or current_execution_brush)):
                return False
            # A previously verified brush no longer justifies its narrower
            # inset once another selection is attempted.
            install_brush_guard(_initial_guard_brush)
            move_settle,click_settle=brush_switch_delays(stroke_delivery)
            mouse.move(*position);wait(move_settle)
            if not dry_run:
                mouse.click();wait(click_settle)
                from BrowserBrushSize import verify_brush_selection
                if not verify_brush_selection(brush_plan,index):
                    _verified_execution_brush=None
                    raise InterruptedError('Browser brush selection could not be verified. Drawing stopped before the next canvas stroke.')
                wait(0)
                _verified_execution_brush=effective
                install_brush_guard(effective)
            current_execution_brush=effective
            plan['options'].setdefault('adaptive_brush_runtime_meta',{'switches':0,'sizes':[],'brush_aware_canvasguard':not dry_run,'simulated':bool(dry_run)})
            runtime_meta=plan['options']['adaptive_brush_runtime_meta']
            runtime_meta['switches']=int(runtime_meta.get('switches',0))+1
            if effective not in runtime_meta.setdefault('sizes',[]):runtime_meta['sizes'].append(effective)
            report('status',f'Adaptive brush: {effective}px selected for the current detail pass.')
            return True

        execution_sequence=prepared_execution_sequence
        sequence_new_completed=0
        sequence_last_entry=None
        if execution_sequence and resume_sequence_level:
            _skip=dict(sequence_completed_counts);_remaining=[];_skipped=0
            for _entry in execution_sequence:
                _entry_key=sequence_entry_key(_entry)
                if _skip.get(_entry_key,0)>0:
                    _skip[_entry_key]-=1;_skipped+=1
                else:_remaining.append(_entry)
            execution_sequence=_remaining
            report('status',f'Sequence resume: skipped {_skipped:,} verified completed operation(s); {len(execution_sequence):,} remain. Dynamic Replanner may safely reorder only the remaining work.')
        if has_execution_sequence:
            # Detail Zoom can materialize a formerly colour-batched plan only
            # to put its extra strokes last. That representation change must
            # retain the original configured after-batch visual safety check.
            sequence_visual=bool((plan['options'].get('detail_zoom_meta') or {}).get('sequence_created_for_detail_pass')
                                and plan['options'].get('visual_verification_enabled',False)
                                and visual_mode!='Off' and not dry_run)
            def sequence_visual_key(entry):
                brush=entry.get('brush_px')
                return (int(entry['color_index']),bool(entry.get('detail_zoom')),
                        int(brush) if brush is not None else None)
            sequence_visual_total=0
            sequence_visual_previous_key=None
            if sequence_visual:
                for entry in execution_sequence:
                    try:key=sequence_visual_key(entry)
                    except (KeyError,TypeError,ValueError,OverflowError):continue
                    if key!=sequence_visual_previous_key:
                        sequence_visual_total+=1;sequence_visual_previous_key=key
                begin_visual_verification(sequence_visual_total)
                sequence_visual=bool(plan['options'].get('visual_verification_enabled',False))
            elif plan['options'].get('visual_verification_enabled',False) and visual_mode!='Off' and not dry_run:
                report('visual_verification',{'current':0,'total':0,'ok':True,'confidence':0.0,'summary':'skipped for progressive passes'})
            sequence_visual_pending=[]
            sequence_visual_batch_key=None
            sequence_visual_brush=current_execution_brush
            sequence_visual_number=0
            def finish_sequence_visual_batch():
                nonlocal sequence_visual_number,sequence_new_completed,sequence_last_entry
                if not sequence_visual_pending:return
                sequence_visual_number+=1
                result=visual_verify_color_batch(sequence_visual_batch_key[0],
                    [item for _,item in sequence_visual_pending],True,sequence_visual_number,
                    sequence_visual_total,brush_px=sequence_visual_brush)
                if result:report('visual_verification',result)
                # Preserve the prior verified checkpoint if this batch fails.
                # Pending paths are added only after the same verification
                # contract as the original colour-batched execution succeeds.
                for completed_entry,_ in sequence_visual_pending:
                    key=sequence_entry_key(completed_entry)
                    if sequence_checkpoint_session is not None:sequence_checkpoint_session.complete(key)
                    else:sequence_completed_counts[key]=int(sequence_completed_counts.get(key,0))+1
                    sequence_new_completed+=1;sequence_last_entry=completed_entry
                sequence_visual_pending.clear()
                if checkpoint is not None and sequence_completed_counts:
                    try:checkpoint(sequence_checkpoint_session.snapshot(prelude_complete=True,last_entry=sequence_last_entry))
                    except Exception as checkpoint_error:log_event(f'Verified detail sequence checkpoint skipped: {checkpoint_error!r}')
            current_color=None
            current_phase=None
            phases_present=[]
            for _entry in execution_sequence:
                _phase=str(_entry.get('phase','details'))
                if _phase not in phases_present:phases_present.append(_phase)
            pixel_four_pass=any(p in phases_present for p in ('fill','mid_detail','fine_detail','cleanup'))
            deadline_pass=any(p in phases_present for p in ('major_coverage','structure','important_details','accuracy','correction'))
            sketch_fill_pass=any(p in phases_present for p in ('sketch','color_fill','reoutline'))
            deadline_scheduler=None
            deadline_panic_reported=False
            deadline_catchup_reported=False
            deadline_last_telemetry=0.0
            if deadline_pass and not dry_run:
                try:
                    from DeadlineScheduler import DeadlineScheduler
                    _budget=(plan['options'].get('adaptive_deadline_meta') or {}).get('render_budget_seconds')
                    _start=(deadline_box[0]-float(_budget)) if deadline_box[0] is not None and _budget else clock()
                    deadline_scheduler=DeadlineScheduler(execution_sequence,start_time=_start,budget_seconds=_budget,clock=clock)
                except Exception as _deadline_error:
                    log_event(f'Deadline runtime scheduler disabled: {_deadline_error!r}')
            if pixel_four_pass:
                base_phases=['fill','mid_detail','fine_detail','cleanup']
                correction_phases=[p for p in phases_present if p.startswith('correction_')]
                ordered_phases=base_phases+correction_phases
                phase_numbers={p:i+1 for i,p in enumerate(ordered_phases)}
                phase_names={'fill':'large fills','mid_detail':'mid detail','fine_detail':'fine detail','cleanup':'protected cleanup'}
                for p in correction_phases:
                    try:n=int(p.rsplit('_',1)[1])
                    except (ValueError,IndexError):n=1
                    phase_names[p]=f'accuracy correction {n}'
                phase_total=len(ordered_phases)
            elif sketch_fill_pass:
                _sf_order=[p for p in ('sketch','color_fill','reoutline') if p in phases_present]
                phase_numbers={p:i+1 for i,p in enumerate(_sf_order)}
                phase_names={'sketch':'Sketch 2.0 contours','color_fill':'color fill','reoutline':'final re-outline'}
                phase_total=max(1,len(_sf_order))
            elif deadline_pass:
                _deadline_order=['major_coverage','structure','important_details','accuracy','correction']
                _deadline_present=[p for p in _deadline_order if p in phases_present]
                phase_numbers={p:i+1 for i,p in enumerate(_deadline_present)}
                phase_names={'major_coverage':'major coverage','structure':'silhouettes and structure',
                             'important_details':'important details','accuracy':'accuracy improvements',
                             'correction':'targeted corrections'}
                phase_total=max(1,len(_deadline_present))
            else:
                phase_numbers={'foundation':1,'contour':2,'details':3}
                phase_names={'foundation':'large forms','contour':'important contours','details':'small details'}
                phase_total=3
            for _execution_index, entry in enumerate(execution_sequence):
                if stop.is_set():
                    if checkpoint is not None and not dry_run and sequence_completed_counts:
                        try:checkpoint(sequence_checkpoint_session.snapshot(prelude_complete=True,last_entry=sequence_last_entry))
                        except Exception as checkpoint_error:log_event(f'Sequence stop checkpoint skipped: {checkpoint_error!r}')
                    raise InterruptedError()
                pause_guard()
                if deadline_scheduler is not None:
                    _pause_before_entry=paused_seconds
                    decision=deadline_scheduler.before(entry)
                    if decision.mode=='CATCH_UP' and not deadline_catchup_reported:
                        deadline_catchup_reported=True
                        report('status','Deadline Catch-up: live drawing speed says the plan is tightening. Switching to coverage-first scheduling and trimming low-value detail/cleanup.')
                    if decision.panic and not deadline_panic_reported:
                        deadline_panic_reported=True
                        report('status','Deadline Panic Mode: measured runtime no longer safely fits. Switching to structure-first scheduling; accuracy/cleanup work is dropped before the safety reserve.')
                    _now=clock()
                    if _now-deadline_last_telemetry>=.75:
                        deadline_last_telemetry=_now
                        report('deadline_telemetry',deadline_scheduler.telemetry())
                    if not decision.execute:
                        continue
                try:
                    index=int(entry['color_index'])
                    item=tuple(entry['path'])
                except (KeyError,TypeError,ValueError):
                    continue
                phase=str(entry.get('phase','details'))
                entry_brush=max(1,int(entry.get('brush_px',current_execution_brush) or current_execution_brush))
                if sequence_visual:
                    entry_visual_key=sequence_visual_key(entry)
                    if sequence_visual_pending and entry_visual_key!=sequence_visual_batch_key:
                        finish_sequence_visual_batch()
                        wait(0)
                _tool_started=clock()
                _tool_switched=switch_execution_brush(entry_brush)
                if _tool_switched:
                    note_runtime_operation('tool_change',clock()-_tool_started)
                    current_color=None
                if phase!=current_phase:
                    current_phase=phase
                    number=phase_numbers.get(phase,phase_total)
                    report('status',f'Progressive pass {number}/{phase_total}: drawing {phase_names.get(phase,phase)} while preserving the PixelMap geometry.')
                    current_color=None
                if current_color!=index:
                    pause_guard()
                    _select_started=clock()
                    selected_method=select(index); current_color=index
                    note_runtime_operation('palette_change' if selected_method=='palette' else 'color_change',clock()-_select_started)
                if index not in verified_colors and plan['options'].get('adaptive_color_verification',False):
                    _verify_started=clock()
                    selected_method=verify_color_batch(index,item,True,selected_method,1,1)
                    note_runtime_operation('verification',clock()-_verify_started)
                if sequence_visual and not sequence_visual_pending:
                    sequence_visual_batch_key=entry_visual_key
                    sequence_visual_brush=current_execution_brush
                _path_started=clock()
                _pause_before_path=paused_seconds
                try:
                    path_result=draw_path_item(index,item,smart_group=True,verify_color=(index not in verified_colors and not plan['options'].get('adaptive_color_verification',False) and plan['options'].get('strict_color_verification',True)))
                except BaseException as error:
                    if checkpoint is not None and not dry_run:
                        try:
                            from SmartRecovery import classify_interruption
                            _decision=classify_interruption(error,str(plan['options'].get('profile_key') or ''))
                            plan['options']['smart_recovery_last_decision']=_decision.as_dict()
                            if _decision.recoverable:
                                _progress=sequence_checkpoint_session.snapshot(prelude_complete=True,last_entry=sequence_last_entry)
                                checkpoint(_progress);plan['options']['smart_recovery_checkpoint']=_progress
                                report('status',f'Smart Recovery saved {int(_progress.get("sequence_completed_count",0)):,}/{int(_progress.get("sequence_total",0)):,} completed sequence operations. Press Start again; target recalibration + visual preflight will run before resume.')
                        except Exception as checkpoint_error:log_event(f'Sequence Smart Recovery checkpoint skipped: {checkpoint_error!r}')
                    raise
                if not (isinstance(path_result,dict) and path_result.get('skipped') is True):
                    note_runtime_operation(entry.get('operation_type','stroke'),max(0.0,clock()-_path_started-(paused_seconds-_pause_before_path)))
                if sequence_visual:
                    sequence_visual_pending.append((entry,item))
                else:
                    _entry_key=sequence_entry_key(entry)
                    if sequence_checkpoint_session is not None:sequence_checkpoint_session.complete(_entry_key)
                    else:sequence_completed_counts[_entry_key]=int(sequence_completed_counts.get(_entry_key,0))+1
                    sequence_new_completed+=1;sequence_last_entry=entry
                if not sequence_visual and checkpoint is not None and not dry_run and sequence_new_completed%25==0:
                    try:checkpoint(sequence_checkpoint_session.snapshot(prelude_complete=True,last_entry=entry))
                    except Exception as checkpoint_error:log_event(f'Sequence recovery checkpoint skipped: {checkpoint_error!r}')
                if deadline_scheduler is not None:
                    deadline_scheduler.after(entry,excluded_seconds=paused_seconds-_pause_before_entry)
                    if deadline_scheduler.replan_in_place(execution_sequence,_execution_index+1):
                        report('status',f'Dynamic Replanner: {deadline_scheduler.mode} reordered remaining safe paths without changing geometry.')
                    _now=clock()
                    if _now-deadline_last_telemetry>=.75:
                        deadline_last_telemetry=_now
                        report('deadline_telemetry',deadline_scheduler.telemetry())
            if sequence_visual:
                finish_sequence_visual_batch()
                wait(0)
            if deadline_scheduler is not None:
                plan['options']['deadline_runtime_meta']=deadline_scheduler.meta()
                report('deadline_telemetry',deadline_scheduler.telemetry())
                if deadline_scheduler.skipped:
                    report('status',f'Deadline scheduler skipped {deadline_scheduler.skipped:,} low-value path(s); catch-up activations={deadline_scheduler.catch_up_activations}; panic activations={deadline_scheduler.panic_activations}.')
            if checkpoint is not None and not dry_run and sequence_completed_counts:
                try:checkpoint(sequence_checkpoint_session.snapshot(prelude_complete=True,last_entry=sequence_last_entry))
                except Exception as checkpoint_error:log_event(f'Final sequence checkpoint skipped: {checkpoint_error!r}')
        else:
            color_order=plan['options'].get('color_order') or list(range(len(plan['groups'])))
            execution_groups=plan.get('execution_groups')
            active_order=[int(i) for i in color_order if 0<=int(i)<len(plan['groups']) and (plan['groups'][int(i)] or (execution_groups is not None and int(i)<len(execution_groups) and execution_groups[int(i)]))]
            begin_visual_verification(len(active_order))
            for color_number,index in enumerate(active_order,1):
                if color_number <= resume_completed:
                    try:rgb_done=tuple(map(int,plan['colors'][int(index)]))
                    except Exception:rgb_done=('?', '?', '?')
                    report('color_plan',{'current':color_number,'total':len(active_order),'rgb':rgb_done,'method':'checkpoint','confidence':100.0,'actual':rgb_done,'matched':True,'completed':True,'resumed':True})
                    continue
                if not (0<=int(index)<len(plan['groups'])):continue
                index=int(index);strokes=plan['groups'][index]
                paths=(execution_groups[index] if execution_groups is not None and index<len(execution_groups) else None)
                if paths is not None:
                    if not paths:continue
                    # Smart paths keep the exact same planned pixels but group safe,
                    # overlapping same-colour rows under one mouse-down.  Ordering is
                    # path-aware instead of feeding polylines to the legacy 4-point
                    # stroke optimizer.
                    if plan['options'].get('gartic_sketch_meta') or plan.get('path_stats',{}).get('stroke_optimizer_effective') not in (None,'Off'):
                        ordered_items=list(paths)
                    else:
                        ordered_items=order_paths(paths,speed_name,allow_reverse=True)
                    smart_group=True
                else:
                    if not strokes:continue
                    speed_ordered=optimize_strokes(strokes,speed_name,allow_reverse=True)
                    ordered_items=humanize_strokes(speed_ordered,human_mode,human_seed + index * 1009)
                    smart_group=False
                try:rgb_label=tuple(map(int,plan['colors'][index]))
                except Exception:rgb_label=('?', '?', '?')
                report('status',f'Color {color_number}/{len(active_order)} · RGB {rgb_label}: finishing {len(ordered_items):,} path(s) before switching to the next color.')
                selected = False
                selected_method=None
                if ordered_items:
                    pause_guard()
                    selected_method=select(index);selected=True
                resume_path_start=0
                if resume_path_level and color_number==int(resume_info.get('active_color_number',0)):
                    expected_fp=str(resume_info.get('active_items_fingerprint') or '')
                    actual_fp=items_fingerprint(ordered_items)
                    expected_count=int(resume_info.get('active_path_count',0) or 0)
                    if expected_fp==actual_fp and expected_count==len(ordered_items):
                        resume_path_start=max(0,min(int(resume_info.get('next_path_index',0) or 0),len(ordered_items)))
                        if resume_path_start:
                            progress_resumed+=resume_path_start
                            report_execution_progress(force=True)
                            report_draw_timer(force=True)
                            report('status',f'Smart Recovery: skipping {resume_path_start} already-completed path(s) in color {color_number}; resuming at path {resume_path_start+1}/{len(ordered_items)}.')
                    else:
                        report('status','Smart Recovery path ordering changed after replanning. No path-level skip was applied; restarting only the current color batch safely.')
                for path_index,item in enumerate(ordered_items):
                    if path_index < resume_path_start:
                        continue
                    if pause_guard():
                        selected = False
                    if not selected:
                        selected_method=select(index,selected_method); selected = True
                    try:
                        if index not in verified_colors and plan['options'].get('adaptive_color_verification',False):
                            selected_method=verify_color_batch(index,item,smart_group,selected_method,color_number,len(active_order))
                        draw_path_item(index,item,smart_group=smart_group,verify_color=(index not in verified_colors and not plan['options'].get('adaptive_color_verification',False) and plan['options'].get('strict_color_verification',True)))
                    except BaseException as error:
                        checkpoint_recoverable_path(error,color_number=color_number,path_index=path_index,ordered_items=ordered_items)
                        raise
                    # A lightweight periodic path checkpoint also improves crash
                    # resilience without writing a file for every stroke.
                    if checkpoint is not None and not dry_run and (path_index+1)<len(ordered_items) and (path_index+1)%25==0:
                        try:
                            progress=checkpoint_after_path(plan,color_number,path_index,len(ordered_items),ordered_items=ordered_items,prelude_complete=True)
                            checkpoint(progress)
                        except Exception as checkpoint_error:
                            log_event(f'Path-level recovery checkpoint skipped: {checkpoint_error!r}')
                visual_result=visual_verify_color_batch(index,ordered_items,smart_group,color_number,len(active_order))
                color_confirmed=(index in verified_colors or not plan['options'].get('adaptive_color_verification',False))
                report('color_plan',{'current':color_number,'total':len(active_order),'rgb':rgb_label,'method':method_label(selected_method),'confidence':100.0 if color_confirmed else 0.0,'actual':rgb_label if color_confirmed else (),'matched':color_confirmed,'completed':True})
                if visual_result:
                    report('visual_verification',visual_result)
                if not dry_run and checkpoint is not None:
                    progress=checkpoint_after_batch(plan,color_number,prelude_complete=True)
                    checkpoint(progress)
        report_execution_progress(force=True)
        execution_measure_completed_at=clock()
        if (not dry_run) and execution_measure_started is not None:
            _initial_elapsed=max(.001,execution_measure_completed_at-execution_measure_started)
            _initial_post_meta=capture_post_draw_accuracy(_initial_elapsed)
            _correction_meta=run_post_draw_correction_pass(_initial_post_meta,_initial_elapsed)
            if isinstance(_correction_meta,dict) and int(_correction_meta.get('executed_paths',0) or 0)>0:
                execution_measure_completed_at=clock()
        actual_draw_seconds=None
        if (not dry_run) and execution_measure_started is not None:
            actual_draw_seconds=max(.001,(execution_measure_completed_at or clock())-execution_measure_started)
            plan['options']['actual_draw_seconds']=round(actual_draw_seconds,4)
            report_draw_timer(force=True,completed=True)
            report('draw_time_actual',{'seconds':actual_draw_seconds,'paths':int(sent_paths),
                                       'processed_paths':int(done),'guard_skipped_paths':int(guard_skipped_paths),
                                       'correction_paths':int((plan['options'].get('post_draw_correction_meta') or {}).get('executed_paths',0) or 0)})
        runtime_safety.mark_completed()
        speed_measure_completed=True
        correction_only_retry=bool(plan['options'].get('correction_only_retry'))
        if dry_run:
            report('status', f'Dry run finished: {done:,} planned cursor paths simulated. No clicks, presses or releases were sent.')
        elif correction_only_retry:
            _corr=plan['options'].get('post_draw_correction_meta') if isinstance(plan.get('options'),dict) else {}
            _corr=_corr if isinstance(_corr,dict) else {}
            _executed=int(_corr.get('executed_paths',0) or 0)
            _planned=int(_corr.get('correction_paths',0) or 0)
            report('status', f'Correction-only retry finished: {_executed}/{_planned} correction path(s) sent. Also verify the final result in the target application.')
        else:
            try:
                from DrawTimeEstimate import format_duration
                _actual_label=format_duration(actual_draw_seconds or 0.0)
            except Exception:
                _actual_label=f'{float(actual_draw_seconds or 0.0):.1f}s'
            _skipped_label=f' · {guard_skipped_paths:,} path(s) skipped by the canvas boundary' if guard_skipped_paths else ''
            report('status', f'Finished locally: {sent_paths:,} brush strokes sent{_skipped_label} · total draw time {_actual_label}. Also verify the final result in the target application.')
    except DryRunBudgetComplete:
        # Reaching the configured Fast Dry run budget is the expected end of a
        # bounded safety sample. It must not invalidate an otherwise clean run.
        runtime_safety.mark_completed()
        plan['options']['dry_run_budget_complete']=True
        report('status',f'Dry run PASS: time budget completed normally after {done:,} safe cursor path(s). No clicks, presses or releases were sent.')
    except BaseException as error:
        runtime_safety.mark_stopped(error)
        raise
    finally:
        # Release input before diagnostics: report/disk failures must never
        # prevent mouse-up or disarming after an interrupted operation.
        from StabilityRC import safe_release_and_disarm
        safe_release_and_disarm(mouse,dry_run=dry_run,logger=log_event)
        if visual_previous_snapshot is not None:
            try:visual_previous_snapshot.close()
            except Exception as close_error:log_event(f'Visual snapshot cleanup failed: {close_error!r}')
        try:
            runtime_payload=save_runtime_safety_report(runtime_safety)
        except Exception as report_error:
            runtime_payload=runtime_safety.as_dict()
            runtime_payload['save_error']=str(report_error)
        plan['options']['runtime_safety_report']=runtime_payload
        plan['options']['runtime_path_counts']={'processed':done,'sent':sent_paths,'guard_skipped':guard_skipped_paths}
        plan['options']['execution_pause_seconds']=round(paused_seconds,6)
        plan['options']['execution_pause_count']=execution_pause_count
        runtime_counts=runtime_payload.get('counts') or {}
        runtime_report_path=runtime_payload.get('text_path') or runtime_payload.get('json_path')
        runtime_report_name=Path(runtime_report_path).name if runtime_report_path else 'report save failed'
        log_event(
            f"Runtime safety report: drawn={int(runtime_counts.get('drawn',0))} clipped={int(runtime_counts.get('clipped',0))} "
            f"skipped={int(runtime_counts.get('skipped',0))} edge_follow={int(runtime_counts.get('edge_follow',0))} "
            f"blocked={int(runtime_counts.get('blocked',0))} stopped={int(runtime_counts.get('stopped',0))} file={runtime_report_name!r}.")
        plan['options']['runtime_operation_timing']={}
        if runtime_operation_stats:
            _ops={}
            for _kind,_item in runtime_operation_stats.items():
                _count=max(1,int(_item.get('count',0) or 0));_total=max(0.0,float(_item.get('total_seconds',0) or 0.0))
                _ops[_kind]={'count':_count,'total_seconds':round(_total,5),'average_seconds':round(_total/_count,6)}
            plan['options']['runtime_operation_timing']=_ops
        if (not dry_run) and (not plan['options'].get('correction_only_retry')) and speed_measure_completed and speed_measure_started is not None:
            try:
                from RealSpeedBudget import record_runtime_sample
                from CompletedDrawLearning import paused_learning_reason
                elapsed=max(.001,(execution_measure_completed_at or clock())-speed_measure_started)
                pause_reason=paused_learning_reason(plan['options'])
                speed_meta=({'recorded':False,'reason':pause_reason} if pause_reason else record_runtime_sample(
                    str(plan['options'].get('profile_key') or ''),sent_paths,elapsed,
                    colors=sum(bool(g) for g in (plan.get('execution_groups') or plan.get('groups') or [])),
                    test_run=bool(plan['options'].get('test_run',False))))
                plan['options']['real_speed_runtime_meta']=speed_meta
                if speed_meta.get('recorded'):
                    log_event(f"Real-Speed sample saved: profile={speed_meta.get('profile_key')} paths={sent_paths} elapsed={elapsed:.3f}s pps={float(speed_meta.get('last_sample_pps',0)):.2f} learned={float(speed_meta.get('paths_per_second',0)):.2f}.")
            except Exception as speed_error:
                log_event(f'Real-Speed sample save skipped: {speed_error!r}')
        if (not dry_run) and (not plan['options'].get('correction_only_retry')) and speed_measure_completed and execution_measure_started is not None:
            try:
                from DrawTimeEstimate import record_completed_draw
                actual_elapsed=max(.001,(execution_measure_completed_at or clock())-execution_measure_started)
                calibration_meta=record_completed_draw(plan,actual_elapsed,completed_paths=sent_paths)
                plan['options']['draw_time_runtime_calibration']=calibration_meta
                if calibration_meta.get('recorded'):
                    log_event(
                        f"Draw-time calibration saved: predicted={float(calibration_meta.get('last_predicted_seconds',0)):.2f}s "
                        f"actual={float(calibration_meta.get('last_actual_seconds',0)):.2f}s "
                        f"ratio={float(calibration_meta.get('ratio_ema',1)):.3f} samples={int(calibration_meta.get('samples',0))}.")
            except Exception as estimate_error:
                log_event(f'Draw-time calibration save skipped: {estimate_error!r}')
        if (not dry_run) and (not plan['options'].get('correction_only_retry')) and speed_measure_completed and execution_measure_started is not None:
            try:
                from CompletedDrawingAnalysis import record_completed_drawing
                _actual_analysis=max(.001,(execution_measure_completed_at or clock())-execution_measure_started)
                analysis_meta=record_completed_drawing(plan,_actual_analysis,completed_paths=sent_paths)
                plan['options']['completed_drawing_analysis_meta']=analysis_meta
                _score=analysis_meta.get('drawing_accuracy_score_0_100')
                _score_label='unavailable' if _score is None else f'{float(_score):.1f}/100'
                log_event(f"Completed Drawing Analysis saved: accuracy={_score_label} efficiency={analysis_meta.get('efficiency_score_0_100')} recommendations={len(analysis_meta.get('recommendations') or ())} file={analysis_meta.get('latest_json_path')}.")
            except Exception as analysis_error:
                log_event(f'Completed Drawing Analysis save skipped: {analysis_error!r}')
        if (not dry_run) and (not plan['options'].get('correction_only_retry')) and speed_measure_completed and execution_measure_started is not None:
            try:
                from AutoTunerFeedback import record_completed_feedback
                _actual_feedback=max(.001,(execution_measure_completed_at or clock())-execution_measure_started)
                feedback_meta=record_completed_feedback(plan,_actual_feedback,completed_paths=sent_paths)
                plan['options']['auto_tuner_feedback_runtime_meta']=feedback_meta
                if feedback_meta.get('recorded'):
                    log_event(
                        f"Auto Tuner feedback saved: profile={feedback_meta.get('profile_key')} "
                        f"strategy={feedback_meta.get('strategy')} samples={int(feedback_meta.get('samples',0))} "
                        f"predicted={float(feedback_meta.get('predicted_seconds',0)):.2f}s actual={float(feedback_meta.get('actual_seconds',0)):.2f}s "
                        f"result={feedback_meta.get('result_visual_percent')} ({feedback_meta.get('result_source')}).")
            except Exception as feedback_error:
                log_event(f'Auto Tuner feedback save skipped: {feedback_error!r}')
        if (not dry_run) and speed_measure_completed and execution_measure_started is not None:
            try:
                from CorrectionHistory import record_correction_history
                _actual_history=max(.001,(execution_measure_completed_at or clock())-execution_measure_started)
                history_meta=record_correction_history(plan,actual_seconds=_actual_history)
                plan['options']['correction_history_meta']=history_meta
                if history_meta.get('recorded'):
                    latest=history_meta.get('latest') if isinstance(history_meta.get('latest'),dict) else {}
                    log_event(
                        f"Correction history saved: profile={history_meta.get('profile_key')} state={history_meta.get('state')} "
                        f"before={latest.get('before_visual_accuracy_percent')} after={latest.get('after_visual_accuracy_percent')} "
                        f"entries={int(history_meta.get('entries',0) or 0)}.")
            except Exception as history_error:
                log_event(f'Correction history save skipped: {history_error!r}')


class DrawBotApp:
    def __init__(self, root, mouse_backend=None, keyboard_backend=None):
        if mouse_backend is None:
            from WindowsMouse import WindowsMouse
            mouse_backend=WindowsMouse()
        if keyboard_backend is None:
            import keyboard as keyboard_backend
        self.root, self.mouse, self.keyboard = root, mouse_backend, keyboard_backend
        self.events = WorkerEventQueue()
        self.stop, self.paused = threading.Event(), threading.Event()
        self.worker = None
        self.activity = None
        self.corners = []
        self.target_window = None
        self.target_client_rect = None
        self.target_dpi = None
        self.original = self.plan = None
        self.background_removal_original = None
        self.background_removal_meta = None
        self.color_session_cache = {}
        self.pending_render_resume = None
        self.canvas_anchor_detection = None
        self.browser_drawing_region = None
        self.small_test_passed = False
        self.capture_job = None
        self.mouse_probe_process = None
        self.closing = False
        self.controls = []
        self.photos = []
        self.hotkeys = []
        self.preview_after = None
        # Monotonic generation protects the UI from late preview worker results.
        self.preview_generation = 0
        self._draw_plan_publication = None
        # Preview rendering has its own debounce job. Keeping this separate from
        # preview generation prevents Canvas <Configure> storms from recursively
        # re-entering Tk while widgets are still laying themselves out.
        self.preview_render_after = None
        self.preview_rendering = False
        self.preview_dirty_reason = ''
        # Full drawing requires a separate safety-unlock button plus a
        # separate Start Drawing click. A single accidental click can never start
        # mouse movement. Test drawing remains one explicit action.
        self.full_draw_armed_until = 0.0
        self.draw_arm_after = None
        # Step 1 safety gate: full drawing requires a recent no-click preflight pass.
        self.safety_preflight_passed = False
        self.safety_preflight_signature = None
        self.safety_preflight_valid_until = 0.0
        # Step 5 safety gate: optional-to-run by button, required before full Start.
        # It reuses the final plan and target geometry but suppresses every click,
        # press and release so users can verify the route before real drawing.
        self.dry_run_passed = False
        self.dry_run_signature = None
        self.dry_run_valid_until = 0.0
        # Step 6 safety gate: after setup is known-good, lock target geometry and
        # calibration relative to the target client area.  Preflight, dry run and
        # real drawing must fail if the window, DPI, selected canvas or palette
        # layout changes after this point.
        self.target_lock_passed = False
        self.target_lock_fingerprint = None
        self.target_lock_signature = None
        self.profile_change_after = None
        self.profile_change_in_progress = False
        self.paint_config_after = None
        self.app_tool_window = None
        self.poll_after = None
        # Step 10 crash-safe local recovery. Checkpoints never persist armed safety state.
        self.recovery_checkpoint_after = None
        self.recovery_image_pending = False
        self.hotkeys_removed = False
        self.shutdown_complete = False
        self.needs_plan = False
        self.drop_action_pending = None
        # v1.0.67: Manual Drop-In Start is a one-shot user arm.  It lets
        # browser/game profiles start drawing after the next image import/drop,
        # but it is never persisted and it is disabled for Paint's strict chain.
        self.manual_drop_in_start = tk.BooleanVar(value=False)
        self.manual_drop_in_armed_until = 0.0
        self.manual_drop_in_after = None
        # v1.0.73: Drop-In requests may wait for read-only browser setup.
        # Nothing here is persisted. Latest image wins and target/profile changes
        # cancel the pending authorization before any native input is armed.
        self.pending_drop_in_import = None
        self.pending_drop_in_after = None
        self.drop_in_start_context = None
        self.drop_in_sync_phase = DROP_SYNC_IDLE
        self.browser_auto_calibration_success = False
        # v1.0.111: experimental Smart Canvas Drop uses a temporary DnD overlay
        # over the detected browser client so a file can be dropped on the actual
        # Gartic/Skribbl/etc canvas. This state is session-only and never persisted.
        self.smart_drop_overlay = None
        self.smart_drop_pending_payload = None
        self.smart_drop_generation = 0
        self.smart_drop_timeout_after = None
        # v1.0.121: a drop directly on the detected game canvas is its own
        # one-shot authorization to run Browser One-Click after the image has
        # been imported. It is never persisted and never applies to Paint.
        self.browser_one_click_force = False
        # v1.0.80: persistent-in-session browser One-Click authorization. It is
        # never enabled for Paint and does not bypass read-only setup/preflight.
        self.browser_one_click_enabled = tk.BooleanVar(value=True)
        # v1.0.114: optional destructive prelude.  It is persisted per profile,
        # but never runs for Small Test, never sends input during Dry Run and is
        # skipped for compatible render-resume checkpoints.
        self.auto_clear_canvas = tk.BooleanVar(value=False)
        self.canvas_clear_text = tk.StringVar(value='Auto clear is off. Enable it to clear the target canvas before full drawing.')
        self.browser_one_click_pending = False
        self.browser_one_click_source_label = ''
        self.browser_one_click_after = None
        self.browser_one_click_after_ticket = None
        self.browser_one_click_request = None
        self.browser_one_click_worker_request = None
        # v1.0.69: Mobile Preview is opt-in and local-network only. The HTTP
        # server is not created/bound until the user explicitly starts it.
        self.mobile_preview_server = None
        self.mobile_preview_after = None
        self.mobile_preview_ticket = None
        self.mobile_preview_discovery = None
        self.mobile_preview_request = None
        root.title('Image Draw Bot')
        try:
            import customtkinter as ctk
            if isinstance(root,ctk.CTk):root.configure(fg_color='#edf2f5')
            else:root.configure(bg='#edf2f5')
        except (ImportError,AttributeError,tk.TclError):
            root.configure(bg='#edf2f5')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('TFrame', background='#edf2f5')
        style.configure('TLabel', background='#edf2f5', foreground='#18303d')
        style.configure('TLabelframe', background='#edf2f5')
        style.configure('TLabelframe.Label', background='#edf2f5', foreground='#087e8b', font=('Segoe UI', 11, 'bold'))
        style.configure('TButton', padding=(10, 7))
        style.configure('Stop.TButton', background='#fbe9e7', foreground='#a52a21', padding=(18,10))
        style.configure('Muted.TLabel', foreground='#526771')
        style.configure('Accent.TButton', background='#087e8b', foreground='white', font=('Segoe UI', 11, 'bold'))
        style.map('Accent.TButton', background=[('active', '#096575'), ('disabled', '#a0b2bb')])
        from GameProfiles import load_custom_profiles
        load_custom_profiles(DATA_DIR/'profiles.json')
        self.game=tk.StringVar(value='Other drawing app')
        self._active_profile_name=self.game.get()
        self.profile_hint=tk.StringVar()
        self.calibration_path=profile_palette_file('generic')
        self.settings_path=profile_settings_file('generic')
        # Compatibility variable only. Window drops are import-only; direct
        # preview-canvas drops may one-shot start a ready non-Paint target.
        self.drop_mode=tk.StringVar(value='Show image')
        self.paint_simple=tk.BooleanVar(value=False)
        self.paint_tool=tk.StringVar(value='Auto (recommended)')
        self.guess_pattern=tk.StringVar()
        self.guess_length=tk.StringVar()
        self.guess_result=tk.StringVar(value='Enter a length or known letters.')
        from WordGuesser import DEFAULT_WORDS,load_words
        self.guess_words=DEFAULT_WORDS
        if (DATA_DIR/'guess-words.txt').exists():
            try:self.guess_words=load_words(DATA_DIR/'guess-words.txt')
            except (OSError,ValueError):pass
        self.word_source=tk.StringVar(value=f'{len(self.guess_words)} words · you can import a custom list')
        self.url = tk.StringVar()
        self.file_label = tk.StringVar(value='No image selected')
        self.drop_in_text = tk.StringVar(value='Drop-In Start is off. Arm it after target canvas and palette are ready.')
        self.smart_drop_in_text = tk.StringVar(value='Arm the game canvas, then drag an image from Google Images/Chrome/Edge directly onto it.')
        self.quality = tk.StringVar(value='Balanced')
        self.speed = tk.StringVar(value='Balanced')
        self.precision = tk.StringVar(value='High')
        self.mode = tk.StringVar(value=SMART_PATH_MODE)
        self.shape_order = tk.StringVar(value='Fill first')
        self.shape_model = tk.StringVar(value='Auto')
        self.max_stroke_cap = tk.StringVar(value='Auto')
        self.progressive_rendering = tk.StringVar(value='Auto')
        self.planning_watchdog = tk.StringVar(value='Auto')
        self.time_budget_mode = tk.StringVar(value='Manual')
        self.adaptive_deadline_renderer = tk.BooleanVar(value=True)
        self.deadline_safety_reserve = tk.StringVar(value='Auto')
        self.target_stroke_count = tk.StringVar(value='Auto')
        self.target_stroke_custom = tk.StringVar(value='2500')
        self.render_preset = tk.StringVar(value='Auto')
        self.drawing_style = tk.StringVar(value='Auto')
        self.sketch_detail = tk.StringVar(value='Auto')
        self.read_gartic_timer = tk.BooleanVar(value=True)
        self.render_style = tk.StringVar(value='Auto')
        self.draw_quality = tk.StringVar(value='High likeness')
        self.human_mode = tk.StringVar(value='Off')
        self.gpu_mode = tk.StringVar(value='Auto')
        self.gpu_vram = tk.StringVar(value='Auto')
        self.gpu_performance = tk.StringVar(value='High throughput')
        self.cpu_workers = tk.StringVar(value='Auto')
        self.cpu_engine = tk.StringVar(value='Auto')
        self.ram_budget = tk.StringVar(value='Auto')
        self.ram_custom_mb = tk.StringVar(value='4096')
        self.planning_resolution = tk.StringVar(value='High')
        self.resource_scheduler = tk.StringVar(value='Auto')
        self.profile_engine = tk.StringVar(value='Auto')
        self.edge_behavior = tk.StringVar(value='Auto')
        self.background_fill = tk.StringVar(value='Balanced')
        self.fill_engine = tk.StringVar(value='Auto')
        self.use_region_fill_engine = tk.BooleanVar(value=True)
        self.fill_aggressiveness = tk.StringVar(value='Balanced')
        self.background_simplification = tk.StringVar(value='Balanced')
        self.color_grouping = tk.StringVar(value='Smart')
        self.color_workflow = tk.StringVar(value='Finish color first')
        self.stroke_optimizer = tk.StringVar(value='Auto')
        self.adaptive_detail = tk.StringVar(value='Auto')
        self.detail_zoom = tk.StringVar(value='Auto')
        self.quick_sketch_style = tk.StringVar(value='Balanced')
        self.quick_sketch_fill_preference = tk.StringVar(value='Safe Fill First')
        self.hybrid_mode = tk.StringVar(value='Auto Hybrid')
        self.visual_verification = tk.StringVar(value='Auto')
        self.color_rendering = tk.StringVar(value='Perceptual match')
        self.color_fidelity = tk.StringVar(value='Faithful')
        self.color_layers = tk.StringVar(value='Off')
        self.custom_color_workflow = tk.StringVar(value='Calibrated palette')
        self.exact_color_limit = tk.StringVar(value='Auto')
        self.exact_color_text = tk.StringVar(value='Smart custom palette is optional. If unavailable, nearest calibrated palette color is used.')
        self.color_plan_text = tk.StringVar(value='Color verification: waiting for drawing.')
        self.draw_time_text = tk.StringVar(value='Estimated draw time appears after Build preview.')
        self.draw_live_time_text = tk.StringVar(value='Drawing timer: starts when drawing begins.')
        self.total_draw_time_text = tk.StringVar(value='Total draw time: —')
        self.preview_diagnostics_text = tk.StringVar(value='Preview diagnostics appear after Build preview.')
        self.correction_review_text = tk.StringVar(value='Correction Review: no completed real drawing yet.')
        self.correction_review_meta = {}
        self.correction_history_meta = {}
        self.benchmark_suite_text = tk.StringVar(value='Benchmark suite has not been run on this profile.')
        self.runtime_safety_summary = tk.StringVar(value='No runtime safety report yet. Run Fast Dry run or Start drawing.')
        self.runtime_safety_detail = tk.StringVar(value='Local-only safety reports are saved after each execution.')
        self.update_summary = tk.StringVar(value='Check for updates finds and downloads a newer release, then opens its installer.')
        self.update_detail = tk.StringVar(value=f'Current: {APP_VERSION} · Updates start only when you press Check for updates.')
        self.auto_tune_summary = tk.StringVar(value='Universal Hardware Auto Benchmark has not been run on this machine yet.')
        self.auto_tune_detail = tk.StringVar(value='Benchmarks CPU/RAM plus NVIDIA, AMD and Intel GPU backends locally. CPU fallback is always available.')
        self.hardware_benchmark_running = False
        self.mobile_preview_status = tk.StringVar(value='Mobile Preview is off · local network only.')
        self.mobile_preview_url = tk.StringVar(value='')
        self.latest_release_url = 'https://github.com/Vxiey/Image-Draw-Bot/releases'
        self.update_request = None
        self.preview_mode = tk.StringVar(value='Manual')
        self.preview_detail_level = tk.StringVar(value='Detailed')
        self.tool_strategy = tk.StringVar(value='Auto')
        self.app_tool_text = tk.StringVar(value='Optional app tools are not calibrated.')
        self.browser_auto_text = tk.StringVar(value='Browser Auto Setup is waiting for a supported game profile and target canvas.')
        self.browser_one_click_text = tk.StringVar(value='One-Click: choose a supported browser game and add an image. Canvas, palette, brush and preflight run automatically.')
        self.one_click_setup_text = tk.StringVar(value='One-click Setup: select Microsoft Paint or a supported browser game to auto-detect and independently verify canvas + palette.')
        self.one_click_setup_verify_pending = None
        self.one_click_setup_verify_payload = None
        self.one_click_setup_after = None
        self.subject_focus = tk.StringVar(value='Off')
        self.subject_region = None
        self.subject_hint = tk.StringVar(value='Auto: simple background or transparent PNG. Mark busy photos.')
        self.portrait_focus = tk.BooleanVar(value=True)
        self.skip_white = tk.BooleanVar(value=True)
        self.contrast = tk.DoubleVar(value=1.0)
        self.outline = tk.BooleanVar(value=False)
        self.brush_px = tk.StringVar(value='Auto')
        self.gartic_opacity = tk.StringVar(value='Auto')
        self.max_seconds = tk.StringVar(value='180')
        self.area_text = tk.StringVar(value='Drawing area not selected')
        self.palette_text = tk.StringVar(value='Colors need calibration')
        self.paint_tool_text = tk.StringVar(value='Paint tool auto-selection not calibrated')
        self.target_lock_text = tk.StringVar(value='Setup is not locked yet')
        self.status = tk.StringVar(value='Start by selecting an image in step 1.')
        # Replace Tkinter's default callback exception printer. In a recursion
        # failure the default traceback formatter can itself recurse and escape
        # mainloop; keeping reporting bounded leaves the GUI alive and logs it.
        root.report_callback_exception=self.report_tk_callback_exception
        self.summary = tk.StringVar(value='Press Build preview when you want a preview. Start Drawing always builds the final plan manually.')
        self.next_step=tk.StringVar(value='1. Select an image to begin.')
        self.setup_wizard_text=tk.StringVar(value='Setup wizard: load an image to begin.')
        self.palette_ready=False
        self.saved_area = None
        from ProfileIsolation import capture_defaults
        capture_defaults(self)
        self.read_settings()
        from StudioUI import build_ui
        build_ui(self,QUALITY,SPEED)
        from ProfileIsolation import restore_extra
        try:restore_extra(self,{'profile_extras':getattr(self,'_loaded_profile_extras',{})})
        except (OSError,ValueError,tk.TclError):pass
        self.refresh_runtime_safety_ui()
        self.refresh_auto_tuner_ui()
        # Step 22: first-run / hardware-change benchmark is deferred so startup
        # remains responsive. It never applies manual setting changes automatically.
        try:self.root.after(6000,self.maybe_auto_hardware_benchmark)
        except Exception:pass
        self.refresh_beginner_setup_wizard()
        self.profile_hint.set(PROFILES[self.game.get()][2])
        try:
            self.hotkeys.append(self.keyboard.add_hotkey('esc',self._request_stop))
            self.hotkeys.append(self.keyboard.add_hotkey('f6',lambda:self.events.put(('toggle_pause',None))))
            quick=lambda:self.events.put(('quick_start',None))
            try:
                self.hotkeys.append(self.keyboard.add_hotkey('f1',quick,suppress=True))
            except TypeError:
                self.hotkeys.append(self.keyboard.add_hotkey('f1',quick))
        except Exception as error:
            self.status.set(f'Global hotkeys are unavailable: {error}. Use the buttons in the window.')
        root.bind('<Control-v>',self.paste_shortcut)
        if hasattr(root,'drop_target_register'):
            try:
                from tkinterdnd2 import DND_FILES
                try:
                    from tkinterdnd2 import DND_TEXT
                except ImportError:
                    DND_TEXT='DND_Text'
                dnd_types=(DND_FILES,DND_TEXT)
                # v1.0.121: File Explorer drops arrive as files, while Chrome/
                # Edge image drags can arrive as URL/text. Accept both. Window
                # drops remain import-only; preview-canvas drops may auto-start.
                root.drop_target_register(*dnd_types)
                root.dnd_bind('<<Drop>>',lambda event:self.drop_image(event,drop_to_draw=False))
                canvas_targets=tuple(
                    target for target in (
                        getattr(self,'original_canvas',None),getattr(self,'result_canvas',None),
                        getattr(self,'detail_zoom_canvas',None),
                        getattr(self,'safety_canvas',None),getattr(self,'safety_debug_canvas',None),
                        getattr(self,'stroke_canvas',None),getattr(self,'fill_canvas',None),
                        getattr(self,'color_canvas',None)) if target is not None)
                for target in canvas_targets:
                    target.drop_target_register(*dnd_types)
                    target.dnd_bind('<<Drop>>',lambda event:self.drop_image(event,drop_to_draw=True))
                    target.dnd_bind('<<DropEnter>>',lambda event,target=target:(target.configure(bg='#254237'),'copy')[1])
                    target.dnd_bind('<<DropLeave>>',lambda event,target=target:(target.configure(bg='#131a25'),'copy')[1])
            except (ImportError,RuntimeError,tk.TclError) as error:
                log_event(f'Drag and drop unavailable: {error!r}')
                self.status.set('Drag and drop could not be enabled. Use Select image or Ctrl+V.')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh_palette()
        self.refresh_tool_calibration()
        self.refresh_app_tool_calibration()
        self.set_busy(None)
        DrawBotApp._schedule_poll(self)
        unclean = previous_run_unclean()
        if unclean:
            # Recovery is offered before crash reporting so two modal dialogs cannot overlap.
            root.after(900, self.offer_safe_session_recovery)
        else:
            try:
                from ReleaseState import should_show_welcome
                if should_show_welcome():
                    root.after(650, self.show_welcome)
            except Exception as error:
                log_event(f'First-run welcome state ignored: {error!r}')

    def _recovery_option_snapshot(self):
        """Return only primitive configuration values; never safety/arming state."""
        from SessionRecovery import RECOVERABLE_OPTION_KEYS
        names=sorted(RECOVERABLE_OPTION_KEYS)
        out={}
        for name in names:
            var=getattr(self,name,None)
            getter=getattr(var,'get',None)
            if not getter:continue
            try:value=getter()
            except Exception:continue
            if isinstance(value,bool) or type(value) in (int,float) or isinstance(value,str):out[name]=value
        # Preview mode is intentionally not checkpointed: recovery always returns to Manual.
        return out

    def _save_recovery_checkpoint(self, *, include_image=False, prepared_image=None):
        if self.closing or self.shutdown_complete or getattr(self,'_suppress_recovery',False):return
        try:
            from SessionRecovery import save_snapshot
            # A pending menu selection has not loaded its profile settings yet.
            profile=getattr(self,'_active_profile_name',None) or (self.game.get() if hasattr(self,'game') else '')
            area=self.saved_area or (self.corners if len(self.corners)==2 else None)
            # An image-specific subject rectangle cannot be attached to an
            # older cached raster after a failed or delayed image checkpoint.
            cached_source=getattr(self,'_recovery_source_ref',lambda:None)()
            include_image=bool(include_image or self.original is not cached_source)
            image=self.original if include_image else None
            subject_selection={'mode':getattr(getattr(self,'subject_focus',None),'get',lambda:'Off')(),
                               'region':getattr(self,'subject_region',None)} if self.original is not None else None
            target_lock=getattr(self,'target_lock_fingerprint',None) if getattr(self,'target_lock_passed',False) else None
            arguments=dict(profile=profile,options=DrawBotApp._recovery_option_snapshot(self),saved_area=area,
                image=image if prepared_image is None else None,
                clear_render_resume=bool(include_image and prepared_image is None),
                target_lock=target_lock,subject_selection=subject_selection)
            if prepared_image is not None:arguments['prepared_image']=prepared_image
            # Image adoption already clears the old resume checkpoint. A later
            # encoded PNG must not clear progress from a draw begun since then.
            save_snapshot(**arguments)
            if image is not None:self._recovery_source_ref=weakref.ref(image)
            log_event(f'Recovery checkpoint saved. image_cached={bool(include_image and self.original is not None)} target_lock_hint={bool(target_lock)}.')
            return True
        except Exception as error:
            log_event(f'Recovery checkpoint skipped: {error!r}')
            return False

    def _queue_recovery_checkpoint(self, *, include_image=False):
        if self.closing or self.shutdown_complete or getattr(self,'_suppress_recovery',False):return False
        job=getattr(self,'_recovery_image_job',None)
        if job is not None and not job.is_alive():
            if DrawBotApp._finish_recovery_image_job(self,job):include_image=False
            job=getattr(self,'_recovery_image_job',None)
        if job is not None:
            # Keep one private snapshot, and remember only that the latest UI
            # state needs a checkpoint. Never queue more full-resolution copies.
            self._recovery_save_pending=True
            if job.source() is not self.original:
                try:job.cancel()
                except OSError as error:log_event(f'Recovery staging cleanup delayed: {error!r}')
            return True
        cached_source=getattr(self,'_recovery_source_ref',lambda:None)()
        if self.original is None or not (include_image or self.original is not cached_source):
            return DrawBotApp._save_recovery_checkpoint(self,include_image=include_image)
        try:
            from RecoveryImagePreparation import RecoveryImageJob
            job=RecoveryImageJob(self.original,lambda completed:self.events.put(('recovery_image_prepared',completed)))
            self._recovery_image_job=job
            self._recovery_save_pending=False
            job.start()
            return True
        except Exception as error:
            self._recovery_image_job=None
            log_event(f'Recovery image preparation skipped: {error!r}')
            return False

    def _finish_recovery_image_job(self,job):
        if job is not getattr(self,'_recovery_image_job',None):
            try:job.cancel()
            except OSError as error:log_event(f'Recovery staging cleanup delayed: {error!r}')
            return False
        if job.is_alive():return False
        self._recovery_image_job=None
        prepared,error=job.take()
        saved=False
        try:
            if error is not None and not isinstance(error,InterruptedError):
                log_event(f'Recovery image preparation skipped: {error!r}')
            elif (prepared is not None and not self.closing and not self.shutdown_complete
                    and not getattr(self,'_suppress_recovery',False) and self.original is not None
                    and job.source() is self.original):
                saved=bool(DrawBotApp._save_recovery_checkpoint(self,include_image=True,prepared_image=prepared))
        finally:
            if prepared is not None:
                try:prepared.close()
                except OSError as cleanup_error:log_event(f'Recovery staging cleanup delayed: {cleanup_error!r}')
        pending=bool(getattr(self,'_recovery_save_pending',False))
        self._recovery_save_pending=False
        if pending and not saved and not self.closing and not getattr(self,'_suppress_recovery',False):
            DrawBotApp._schedule_recovery_checkpoint(self,delay=20)
        return saved

    def _cancel_recovery_image_job(self):
        self._recovery_save_pending=False
        job=getattr(self,'_recovery_image_job',None)
        if job is not None:
            try:job.cancel()
            except OSError as error:log_event(f'Recovery staging cleanup delayed: {error!r}')
        return job

    def _schedule_recovery_checkpoint(self, *, include_image=False, delay=250):
        if self.closing or self.shutdown_complete:return
        self.recovery_image_pending=bool(getattr(self,'recovery_image_pending',False) or include_image)
        DrawBotApp._cancel_after_attr(self,'recovery_checkpoint_after')
        def run():
            self.recovery_checkpoint_after=None
            with_image=bool(self.recovery_image_pending);self.recovery_image_pending=False
            DrawBotApp._queue_recovery_checkpoint(self,include_image=with_image)
        try:self.recovery_checkpoint_after=self.root.after(max(20,int(delay)),run)
        except (tk.TclError,RuntimeError,AttributeError):self.recovery_checkpoint_after=None

    def _clear_render_resume(self, reason='setup changed'):
        self.pending_render_resume=None
        try:
            from SessionRecovery import clear_render_progress
            clear_render_progress()
        except Exception as error:
            log_event(f'Render resume clear skipped: {error!r}')
        try:self.color_plan_text.set('Color verification: waiting for drawing.')
        except (tk.TclError,AttributeError):pass
        log_event(f'Render resume checkpoint cleared: {reason}.')

    def _apply_recovery_snapshot(self, state, *, recovered_image=_RECOVERY_IMAGE_UNSET):
        """Restore local work only; every input safety gate remains reset/disarmed."""
        from SessionRecovery import load_cached_image
        DrawBotApp._cancel_browser_one_click(self,'safe session recovery')
        DrawBotApp._disarm_full_draw(self,'safe session recovery',update_text=True)
        try:
            if hasattr(self.mouse,'disarm_input'):self.mouse.disarm_input()
        except OSError:pass
        profile=str(state.get('profile') or '')
        if profile in PROFILES and profile!=self.game.get():
            self.game.set(profile)
            self._apply_profile_change(profile)
        options=state.get('options') if isinstance(state,dict) else {}
        if isinstance(options,dict) and options:
            from SettingsValidation import validated_settings, settings_application
            restored=validated_settings(dict(options,preview_mode='Manual'))
            with settings_application(self):
                DrawBotApp._apply_settings_data(self,restored)
        # Manual preview is a hard recovery invariant.
        self.preview_mode.set('Manual')
        area=state.get('saved_area') if isinstance(state,dict) else None
        self.saved_area=[tuple(map(int,p)) for p in area] if isinstance(area,list) and len(area)==2 else None
        image=(load_cached_image(expected_sha256=state.get('image_sha256')) if state.get('has_image') is True else None) if recovered_image is _RECOVERY_IMAGE_UNSET else recovered_image
        if image is not None:
            self.original=image;self.plan=None;self.file_label.set('Recovered local image')
            DrawBotApp._clear_source_time_feedback(self)
            self._recovery_source_ref=weakref.ref(image)
        self.subject_region=None
        subject_mode='Off'
        if image is not None:
            from SessionRecovery import clean_subject_selection
            selection=clean_subject_selection(state.get('subject_selection'),state.get('image_sha256'))
            if selection is not None:
                self.subject_region=tuple(selection['region']) if selection['region'] is not None else None
                subject_mode=selection['mode']
        if hasattr(self,'subject_focus'):self.subject_focus.set(subject_mode)
        if hasattr(self,'subject_hint'):
            self.subject_hint.set('Recovered marked rectangle. Build preview to check.' if self.subject_region is not None else 'Auto: simple background or transparent PNG. Mark busy photos.')
        resume=state.get('render_resume') if isinstance(state,dict) else None
        self.pending_render_resume=resume if isinstance(resume,dict) else None
        if self.pending_render_resume:
            completed=int(self.pending_render_resume.get('completed_count',0));total=int(self.pending_render_resume.get('total_colors',0))
            if self.pending_render_resume.get('path_level'):
                color_no=int(self.pending_render_resume.get('active_color_number',completed+1) or completed+1)
                path_no=int(self.pending_render_resume.get('next_path_index',0) or 0)+1
                path_total=int(self.pending_render_resume.get('active_path_count',0) or 0)
                self.color_plan_text.set(f'Smart Recovery: {completed}/{total} colors complete · color {color_no} path {path_no}/{path_total} pending · DISARMED')
            else:
                self.color_plan_text.set(f'Render resume: {completed}/{total} colors completed · next color {completed+1 if completed < total else "done"} · DISARMED')
        # Never restore a live target or any passed/armed gate.
        self.corners=[];self.target_window=None;self.target_client_rect=None;self.target_dpi=None
        self.browser_drawing_region=None
        self.small_test_passed=False
        self.target_lock_passed=False;self.target_lock_fingerprint=None;self.target_lock_signature=None
        self.safety_preflight_passed=False;self.safety_preflight_signature=None;self.safety_preflight_valid_until=0.0
        self.dry_run_passed=False;self.dry_run_signature=None;self.dry_run_valid_until=0.0
        DrawBotApp._refresh_target_lock_text(self)
        self.area_text.set('Recovered area is only a suggestion. Re-select or explicitly reuse it, then run the full safety chain.')
        self._mark_plan_stale('Safe session recovered. Preview is Manual. Re-select target and rerun Small test → Lock setup → Preflight → Dry run before Start.')
        self.show_previews();self.set_busy(None)
        if self.pending_render_resume:
            completed=int(self.pending_render_resume.get('completed_count',0));total=int(self.pending_render_resume.get('total_colors',0))
            self.status.set(f'Safe session recovered DISARMED · {completed}/{total} colors completed. Rebuild the same setup and safety chain to continue from color {completed+1}.')
        else:
            self.status.set('Safe session recovered DISARMED. No target lock, preflight, dry run or drawing authorization was restored.')
        log_event('Safe session recovery applied. All native input gates reset/disarmed.')

    def offer_safe_session_recovery(self):
        if self.closing or self.activity:return
        try:
            from SessionRecovery import load_snapshot,clear_snapshot
            state=load_snapshot()
        except Exception as error:
            log_event(f'Recovery snapshot could not be read: {error!r}');state=None
        if state:
            text=('Image Draw Bot did not close normally and a local recovery checkpoint is available.\n\n'
                  'Recover the image/settings from the checkpoint? Drawing will remain completely DISARMED: target lock, small test, preflight, dry run and Start authorization are never restored.')
            if messagebox.askyesno('Safe session recovery',text,parent=self.root):
                if self.closing or self.activity:
                    return
                self.status.set('Loading the local recovery image…')
                def work():
                    from SessionRecovery import load_cached_image
                    image=load_cached_image(expected_sha256=state.get('image_sha256'),cancelled=self.stop.is_set) if state.get('has_image') is True else None
                    if self.stop.is_set():
                        if image is not None:image.close()
                        raise InterruptedError('Recovery loading cancelled.')
                    self.events.put(('recovery_loaded',(state,image)))
                self.begin_worker('recovery-load',work)
                return
            else:
                if self.closing or self.activity:return
                job=DrawBotApp._cancel_recovery_image_job(self)
                if job is not None and job.is_alive():
                    DrawBotApp.clear_recovery_snapshot(self)
                    return
                try:
                    clear_snapshot()
                except Exception as error:
                    log_event(f'Recovery declined; local checkpoint cleanup failed: {error!r}')
                    self.status.set('Recovery declined. Local recovery data could not be fully cleared.')
                    messagebox.showwarning('Recovery cleanup incomplete',
                        f'The session was not restored, but some local recovery data may remain: {error}',parent=self.root)
                    return
                log_event('User declined safe session recovery; local checkpoint cleared.')
        if previous_run_unclean():
            self.status.set('Previous session ended unexpectedly. Recovery/logs remain local; no data is sent anywhere.')

    def clear_image(self):
        DrawBotApp._request_clear_drawing(self,True)

    def clear_cached_drawing(self):
        DrawBotApp._request_clear_drawing(self,False)

    def _request_clear_drawing(self,remove_image):
        if self.closing:return
        DrawBotApp._runtime_safety_view(self).clear()
        DrawBotApp.refresh_runtime_safety_ui(self)
        pending=getattr(self,'recovery_loaded_pending',None)
        if pending is not None:
            DrawBotApp._discard_worker_result(self,'recovery_loaded',pending)
            self.recovery_loaded_pending=None
        previous=getattr(self,'pending_clear_drawing',None)
        self.pending_clear_drawing=bool(remove_image or previous)
        if previous is None:self._clear_worker=getattr(self,'worker',None)
        self._suppress_recovery=True
        DrawBotApp._cancel_recovery_image_job(self)
        self.cancel()
        for name in ('preview_after','preview_render_after','recovery_checkpoint_after','paint_config_after'):
            DrawBotApp._cancel_after_attr(self,name)
        self.status.set('Stopping the previous operation and clearing its cached drawing…')
        DrawBotApp._finish_clear_drawing(self)

    def _finish_clear_drawing(self):
        if self.closing or getattr(self,'pending_clear_drawing',None) is None:return
        worker=getattr(self,'_clear_worker',None)
        recovery_job=getattr(self,'_recovery_image_job',None)
        if self.activity or (worker is not None and worker.is_alive()) or (recovery_job is not None and recovery_job.is_alive()):
            self.root.after(50,lambda:DrawBotApp._finish_clear_drawing(self));return
        remove_image=getattr(self,'pending_clear_drawing',False)
        self.plan=None;self.pending_render_resume=None;self.needs_plan=False
        DrawBotApp._clear_plan_feedback(self)
        self.small_test_passed=False
        self.color_session_cache.clear()
        if remove_image:
            self.original=None;self.subject_region=None;self.upscale_original=None
            DrawBotApp._clear_source_time_feedback(self)
            self.background_removal_original=None;self.background_removal_meta=None
            self.file_label.set('No image loaded');self.url.set('')
        error=None
        try:
            from SessionRecovery import clear_snapshot,STATE_FILE,RENDER_FILE,IMAGE_FILE
            clear_snapshot()
            if any(path.exists() for path in (STATE_FILE,RENDER_FILE,IMAGE_FILE)):
                raise OSError('Some recovery files could not be deleted.')
        except Exception as exc:error=str(exc)
        self.pending_clear_drawing=None;self._clear_worker=None
        self.progress['value']=0;self.set_busy(None)
        self.summary.set('Image cleared. Add a new image.' if remove_image else 'Cached drawing cleared. Build a new preview or start again.')
        self.status.set(('Local cache could not be fully cleared: '+error) if error else ('Image and cached drawing cleared.' if remove_image else 'Cached drawing cleared; source image kept.'))
        self.show_previews();self._sync_mobile_preview()
        try:self.root.deiconify()
        except tk.TclError:pass

    def auto_setup_gartic_full(self):
        if self.activity or self.closing:return
        if self.game.get()!='Gartic Phone':
            self.status.set('Choose Gartic Phone for full automatic setup.');return
        self.cancel() # disarm any pending automatic start; setup never draws
        self.browser_drawing_region=None  # This explicit command chooses the full detected canvas.
        profile=self.game.get();path=Path(self.calibration_path)
        self.browser_auto_calibration_success=False
        _preferred_handle=(self.target_window[0] if getattr(self,'target_window',None) else None)
        _preferred_monitor=None
        try:
            _preferred_monitor=getattr(self,'target_dpi_info',{}).get('monitor_rect') if isinstance(getattr(self,'target_dpi_info',None),dict) else None
        except Exception:
            _preferred_monitor=None
        def work():
            import os
            from BrowserOneClick import discover_browser_target
            from BrowserAutoCalibration import auto_calibrate_browser
            candidate=discover_browser_target('gartic-phone',exclude_pid=os.getpid(),preferred_handle=_preferred_handle,preferred_monitor_rect=_preferred_monitor,cancelled=self.stop.is_set)
            with closing(candidate.screenshot):
                if self.stop.is_set():raise InterruptedError()
                meta={'handle':candidate.handle,'rect':candidate.rect,'client_rect':candidate.client_rect,'dpi':candidate.dpi}
                result=auto_calibrate_browser('gartic-phone',meta,path,screenshot=candidate.screenshot,cancelled=self.stop.is_set)
                from LayoutFingerprintV2 import record_from_calibration_file
                fingerprint=record_from_calibration_file('gartic-phone',meta,result.canvas_box,path,method='Full Gartic grid setup')
                payload=result.as_dict();payload.update(target_meta=meta,profile_name=profile,layout_fingerprint_meta=fingerprint)
                self.events.put(('browser_auto_calibration_complete',payload))
        self.begin_worker('browser-auto-calibration',work)

    def clear_recovery_snapshot(self):
        if self.closing:return
        if self.activity:
            self.status.set('Stop the current operation before clearing recovery data.');return
        DrawBotApp._cancel_after_attr(self,'recovery_checkpoint_after')
        self.recovery_image_pending=False
        job=DrawBotApp._cancel_recovery_image_job(self)
        if job is not None and job.is_alive():
            previous_suppression=bool(getattr(self,'_suppress_recovery',False))
            self._recovery_clear_previous_suppression=previous_suppression
            self._suppress_recovery=True
            self.status.set('Stopping recovery image preparation and clearing the local checkpoint…')
            def work():
                error=None
                try:
                    while not job.wait_idle(.05):
                        if self.stop.is_set():raise InterruptedError('Recovery clearing cancelled.')
                    if self.stop.is_set():raise InterruptedError('Recovery clearing cancelled.')
                    from SessionRecovery import clear_snapshot
                    clear_snapshot()
                except Exception as failure:error=str(failure)
                self.events.put(('recovery_clear_complete',(error,previous_suppression)))
            try:
                started=self.begin_worker('recovery-clear',work)
            except BaseException:
                self._suppress_recovery=previous_suppression
                self._recovery_clear_previous_suppression=None
                raise
            if not started:
                self._suppress_recovery=previous_suppression
                self._recovery_clear_previous_suppression=None
            return
        try:
            from SessionRecovery import clear_snapshot
            clear_snapshot()
            self._suppress_recovery=True
            self.pending_render_resume=None
            self.status.set('Local safe-recovery checkpoint cleared.')
            log_event('Recovery checkpoint cleared by user.')
        except Exception as error:self.status.set(f'Could not clear recovery checkpoint: {error}')

    def report_tk_callback_exception(self,exc_type,value,tb):
        import traceback
        try:
            if issubclass(exc_type,RecursionError):
                detail=f'{exc_type.__name__}: {value}'
            else:
                detail=''.join(traceback.format_exception(exc_type,value,tb,limit=30))
        except Exception:
            detail=f'{getattr(exc_type,"__name__",exc_type)}: {value}'
        log_event(f'Tk callback exception (contained)\n{detail}')
        # Do not synchronously mutate traced Tk variables from inside Tk's own
        # exception callback. That was another path into the recursion loop.
        try:
            self.root.after(25, lambda: self.status.set(f'UI error contained: {value}. See ImageDrawBot-session.log.') if not self.closing else None)
        except (tk.TclError,AttributeError,RuntimeError):
            pass

    def button(self,parent,text,command,**kwargs):
        button=ttk.Button(parent,text=text,command=command,**kwargs)
        self.controls.append((button,'normal'))
        return button

    def _cancel_after_attr(self, name):
        """Cancel a stored Tk after token without letting shutdown races escape."""
        token=getattr(self,name,None)
        if token is None:
            return False
        setattr(self,name,None)
        try:
            self.root.after_cancel(token)
            return True
        except (tk.TclError,ValueError,RuntimeError,AttributeError):
            return False

    def _schedule_poll(self):
        if getattr(self,'shutdown_complete',False):
            return
        DrawBotApp._cancel_after_attr(self,'poll_after')
        try:
            self.poll_after=self.root.after(50,self.poll)
        except (tk.TclError,RuntimeError,AttributeError):
            self.poll_after=None

    @staticmethod
    def _safe_widget_configure(widget, **kwargs):
        try:
            widget.configure(**kwargs)
            return True
        except (tk.TclError,RuntimeError,AttributeError):
            return False

    def _paint_tool_preflight_ready(self):
        """Cheap UI-only readiness check; no window access and no mouse input."""
        if self.game.get()!='Microsoft Paint':return True
        selected=self.paint_tool.get()
        if selected=='Use current tool':return True
        try:
            from PaintTools import load_tool_calibration
            data=load_tool_calibration()
            if data.get('version') not in (2,3):return False
            opacity=data.get('opacity_100') is not None
            if selected=='Auto (recommended)':
                return (data.get('tools',{}).get('Pencil') is not None or
                        (opacity and data.get('brush_menu') is not None and data.get('brush_preset') is not None))
            if selected=='Pencil':return data.get('tools',{}).get('Pencil') is not None
            if selected=='Brush':return opacity and data.get('brush_menu') is not None and data.get('brush_preset') is not None
            if selected=='Eraser':return data.get('tools',{}).get('Eraser') is not None
        except (OSError,ValueError,TypeError):
            return False
        return False


    def _palette_preflight_ready(self):
        """Cheap UI-only palette readiness; full validation still runs in draw()."""
        return bool(self.palette_ready or bypasses_palette(self))

    def _current_safety_signature(self):
        """Fingerprint the critical setup without doing any native input."""
        try: profile=self.game.get()
        except Exception: profile=''
        try: paint_tool=self.paint_tool.get()
        except Exception: paint_tool=''
        target=getattr(self,'target_window',None)
        handle=(target[0] if target else None)
        rect=(tuple(target[1]) if target and len(target)>1 else None)
        image=getattr(self,'original',None)
        image_sig=(id(image), getattr(image,'size',None)) if image is not None else None
        return (profile,paint_tool,tuple(tuple(p) for p in getattr(self,'corners',())),
                handle,rect,bool(self._palette_preflight_ready()),image_sig,
                bool(getattr(self,'small_test_passed',False)))

    def _safety_preflight_valid(self):
        if not bool(getattr(self,'safety_preflight_passed',False)):
            return False
        if time.monotonic() > float(getattr(self,'safety_preflight_valid_until',0.0) or 0.0):
            return False
        return getattr(self,'safety_preflight_signature',None) == DrawBotApp._current_safety_signature(self)

    def _invalidate_safety_preflight(self, reason='setup changed', *, disarm=True):
        was_valid=DrawBotApp._safety_preflight_valid(self)
        self.safety_preflight_passed=False
        self.safety_preflight_signature=None
        self.safety_preflight_valid_until=0.0
        self.dry_run_passed=False
        self.dry_run_signature=None
        self.dry_run_valid_until=0.0
        if disarm:
            DrawBotApp._disarm_full_draw(self, reason, update_text=True)
        if reason and was_valid:
            log_event(f'Safety preflight invalidated: {reason}.')

    def _dry_run_valid(self):
        if not bool(getattr(self,'dry_run_passed',False)):
            return False
        if time.monotonic() > float(getattr(self,'dry_run_valid_until',0.0) or 0.0):
            return False
        return getattr(self,'dry_run_signature',None) == DrawBotApp._current_safety_signature(self)

    def _invalidate_dry_run(self, reason='setup changed', *, disarm=True):
        was_valid=DrawBotApp._dry_run_valid(self)
        self.dry_run_passed=False
        self.dry_run_signature=None
        self.dry_run_valid_until=0.0
        if disarm:
            DrawBotApp._disarm_full_draw(self, reason, update_text=True)
        if reason and was_valid:
            log_event(f'Dry run invalidated: {reason}.')

    @staticmethod
    def _target_lock_signature_from(fingerprint):
        try:
            return json.dumps(fingerprint, sort_keys=True, separators=(',', ':'))
        except (TypeError, ValueError):
            return ''

    def _build_target_lock_fingerprint(self, *, current_client_rect=None, current_target_rect=None, current_dpi=None):
        if getattr(self, 'target_window', None) is None:
            raise ValueError('Select the drawing area again before locking setup.')
        if len(getattr(self, 'corners', ())) != 2:
            raise ValueError('Select the drawing area before locking setup.')
        client = tuple(map(int, current_client_rect or getattr(self, 'target_client_rect', None) or self.target_window[1]))
        rect = tuple(map(int, current_target_rect or self.target_window[1]))
        dpi = current_dpi if current_dpi is not None else getattr(self, 'target_dpi', None)
        profile = self.game.get() if hasattr(self, 'game') else ''
        paint_tool = self.paint_tool.get() if hasattr(self, 'paint_tool') else ''
        paint_simple = bool(self.paint_simple.get()) if hasattr(self, 'paint_simple') else False
        x, y, w, h = self.area()
        area_rel = [int(x - client[0]), int(y - client[1]), int(w), int(h)]
        corners_rel = [[int(px - client[0]), int(py - client[1])] for px, py in self.corners]
        palette_required = not bypasses_palette(self)
        palette = []
        if palette_required:
            for color in allColors:
                palette.append({
                    'name': str(getattr(color, 'name', '')),
                    'rgb': [int(v) for v in getattr(color, 'RGB', (0, 0, 0))],
                    'rel': [int(color.x - client[0]), int(color.y - client[1])],
                })
        tool_actions = []
        if profile == 'Microsoft Paint' and paint_tool != 'Use current tool':
            try:
                from PaintTools import build_tool_actions
                for kind, position in build_tool_actions(paint_tool, current_client_rect=client):
                    tool_actions.append({'kind': str(kind), 'rel': [int(position[0] - client[0]), int(position[1] - client[1])]})
            except (OSError, ValueError, TypeError) as error:
                # The caller will surface this as a setup-lock/preflight failure.
                raise ValueError(f'Paint tool calibration changed or is unavailable: {error}') from error
        exact_controls=[]
        try:
            if getattr(getattr(self,'custom_color_workflow',None),'get',lambda:'' )()=='Exact custom + palette fallback':
                key=PROFILES[profile][0]
                for name,pos in sorted(resolve_exact_color_controls(key,client).items()):
                    exact_controls.append({'name':name,'rel':[int(pos[0]-client[0]),int(pos[1]-client[1])]})
        except (OSError,ValueError,KeyError,TypeError):
            exact_controls=[]
        image = getattr(self, 'original', None)
        image_size = list(getattr(image, 'size', ())) if image is not None else None
        return {
            'version': 1,
            'profile': profile,
            'paint_tool': paint_tool,
            'paint_single_color': paint_simple,
            'target_handle': int(self.target_window[0]),
            'target_rect': [int(v) for v in rect],
            'target_client_rect': [int(v) for v in client],
            'target_dpi': (int(dpi) if dpi is not None else None),
            'drawing_area_rel': area_rel,
            'corners_rel': corners_rel,
            'image_size': image_size,
            'palette_required': palette_required,
            'palette': palette,
            'tool_actions': tool_actions,
            'exact_color_controls': exact_controls,
        }

    def _target_lock_valid(self):
        if not bool(getattr(self, 'target_lock_passed', False)):
            return False
        stored = getattr(self, 'target_lock_signature', None)
        if not stored:
            return False
        try:
            current = DrawBotApp._build_target_lock_fingerprint(self)
        except Exception:
            return False
        return stored == DrawBotApp._target_lock_signature_from(current)

    def _refresh_target_lock_text(self):
        locked = DrawBotApp._target_lock_valid(self)
        text = 'Unlock setup' if locked else 'Lock setup'
        for name in ('target_lock_button', 'target_lock_secondary'):
            widget = getattr(self, name, None)
            if widget is not None:
                DrawBotApp._safe_widget_configure(widget, text=text)
        target_text = getattr(self, 'target_lock_text', None)
        if target_text is not None:
            try:
                target_text.set('✓ Setup locked to current target window, DPI, drawing area and palette.' if locked else 'Setup not locked. Run small test, then Lock setup.')
            except (tk.TclError, RuntimeError):
                pass

    def _invalidate_target_lock(self, reason='setup changed', *, disarm=True):
        was_valid = DrawBotApp._target_lock_valid(self)
        self.target_lock_passed = False
        self.target_lock_fingerprint = None
        self.target_lock_signature = None
        cache=getattr(self,'color_session_cache',None)
        if isinstance(cache,dict):cache.clear()
        if disarm:
            DrawBotApp._invalidate_safety_preflight(self, reason, disarm=True)
        DrawBotApp._refresh_target_lock_text(self)
        if reason and was_valid:
            log_event(f'Target/setup lock invalidated: {reason}.')

    def _verify_target_lock(self):
        if not bool(getattr(self, 'target_lock_passed', False)) or not getattr(self, 'target_lock_signature', None):
            raise ValueError('Lock setup first. Full drawing is blocked until target window, DPI, area and palette are fingerprinted.')
        if getattr(self, 'target_window', None) is None:
            DrawBotApp._invalidate_target_lock(self, 'target window missing')
            raise ValueError('The target window is no longer locked. Select drawing area and Lock setup again.')
        try:
            DrawBotApp._refresh_target_for_draw(self, update_target_lock=True)
        except (OSError, ValueError, InterruptedError) as error:
            DrawBotApp._invalidate_target_lock(self, 'target anchor transform failed')
            raise ValueError(f'Target Lock failed: {error}') from error
        from TargetCapture import probe_handle_isolated
        handle = int(self.target_window[0])
        meta = probe_handle_isolated(handle)
        stored = getattr(self, 'target_lock_fingerprint', None) or {}
        expected_rect = tuple(stored.get('target_rect') or ())
        expected_client = tuple(stored.get('target_client_rect') or ())
        expected_dpi = stored.get('target_dpi')
        current_rect = tuple(meta['rect']); current_client = tuple(meta['client_rect']); current_dpi = meta.get('dpi')
        if expected_rect and current_rect != expected_rect:
            DrawBotApp._invalidate_target_lock(self, 'target window rectangle changed')
            raise ValueError('Target Lock failed: the target window moved or changed size. Select the drawing area and Lock setup again. No mouse input was sent.')
        if expected_client and current_client != expected_client:
            DrawBotApp._invalidate_target_lock(self, 'target client rectangle changed')
            raise ValueError('Target Lock failed: the target drawing window layout changed. Re-select the canvas and Lock setup again. No mouse input was sent.')
        if expected_dpi is not None and current_dpi is not None and int(current_dpi) != int(expected_dpi):
            DrawBotApp._invalidate_target_lock(self, 'target DPI changed')
            raise ValueError(f'Target Lock failed: DPI changed from {expected_dpi} to {current_dpi}. Select the drawing area and Lock setup again. No mouse input was sent.')
        paint_profile = self.game.get() == 'Microsoft Paint'
        if not bypasses_palette(self):
            load_calibration(self.calibration_path, current_client_rect=current_client, require_anchor=paint_profile, profile_key=PROFILES[self.game.get()][0])
        current = DrawBotApp._build_target_lock_fingerprint(self, current_client_rect=current_client, current_target_rect=current_rect, current_dpi=current_dpi)
        current_signature = DrawBotApp._target_lock_signature_from(current)
        if current_signature != getattr(self, 'target_lock_signature', None):
            DrawBotApp._invalidate_target_lock(self, 'target fingerprint mismatch')
            raise ValueError('Target Lock failed: drawing area, palette layout, Paint tool calibration or source image changed. Lock setup again before drawing. No mouse input was sent.')
        return True

    def _make_live_target_check(self, *, interval=0.35):
        """Return a low-cost monitor used by GuardedMouse during execution.

        Step 6 verifies the fingerprint before planning. Step 7 keeps checking
        the locked target while the cursor is moving so a window move, DPI change,
        canvas reflow or stale calibration cannot continue silently mid-drawing.
        The callback is throttled to keep fast paths responsive; GuardedMouse
        still performs its normal foreground/point checks on every movement.
        """
        if not getattr(self, 'target_lock_fingerprint', None):
            return None
        stored=dict(self.target_lock_fingerprint)
        expected_signature=getattr(self, 'target_lock_signature', None)
        expected_handle=int(stored.get('target_handle', self.target_window[0] if self.target_window else 0))
        expected_rect=tuple(stored.get('target_rect') or ())
        expected_client=tuple(stored.get('target_client_rect') or ())
        expected_dpi=stored.get('target_dpi')
        expected_area_rel=tuple(stored.get('drawing_area_rel') or ())
        check_state={'next':0.0,'last_log':0.0,'count':0}

        def fail(reason, message):
            try:
                DrawBotApp._invalidate_target_lock(self, reason, disarm=True)
            except Exception:
                pass
            log_event(f'Live target monitor stopped drawing: {reason}.')
            raise InterruptedError(message)

        def live_check(monitor, target, point=None):
            now=time.monotonic()
            if now < check_state['next']:
                return True
            check_state['next']=now+float(interval)
            check_state['count']+=1
            if not bool(getattr(self, 'target_lock_passed', False)) or getattr(self, 'target_lock_signature', None) != expected_signature:
                fail('setup lock changed during drawing', 'Stopped: setup lock changed during drawing. No automatic restart.')
            handle=int(target[0])
            if handle != expected_handle:
                fail('target handle changed during drawing', 'Stopped: the drawing target handle changed. Select the drawing area and Lock setup again.')
            try:
                rect=tuple(monitor.rectangle(handle))
                client=tuple(monitor.client_rectangle(handle))
                dpi=monitor.dpi(handle)
            except InterruptedError as error:
                fail('target became unavailable during drawing', str(error))
            if expected_rect and rect != expected_rect:
                fail('target window rectangle changed during drawing', 'Stopped: target window moved or changed size during drawing. Re-select the canvas and Lock setup again.')
            if expected_client and client != expected_client:
                fail('target client rectangle changed during drawing', 'Stopped: target client/layout changed during drawing. Re-select the canvas and Lock setup again.')
            if expected_dpi is not None and dpi is not None and int(dpi) != int(expected_dpi):
                fail('target DPI changed during drawing', f'Stopped: target DPI changed from {expected_dpi} to {dpi} during drawing. Re-select the canvas and Lock setup again.')
            if expected_area_rel and len(expected_area_rel)==4:
                try:
                    x,y,w,h=self.area()
                    area_rel=(int(x-client[0]),int(y-client[1]),int(w),int(h))
                except Exception:
                    fail('drawing area unavailable during drawing', 'Stopped: drawing area could not be validated during drawing.')
                if area_rel != expected_area_rel:
                    fail('drawing area changed during drawing', 'Stopped: selected canvas no longer matches the locked setup. Lock setup again before drawing.')
            # Rebuild the fingerprint against live in-process geometry. This catches
            # changed image/profile/palette/tool calibration state even when the
            # native window still reports the same rectangle.
            try:
                current=DrawBotApp._build_target_lock_fingerprint(self, current_client_rect=client, current_target_rect=rect, current_dpi=dpi)
                signature=DrawBotApp._target_lock_signature_from(current)
            except Exception as error:
                fail('target fingerprint could not be rebuilt during drawing', f'Stopped: setup fingerprint could not be validated during drawing: {error}')
            if signature != expected_signature:
                fail('target fingerprint mismatch during drawing', 'Stopped: target/palette/tool fingerprint changed during drawing. Lock setup again before continuing.')
            if now-check_state['last_log']>=10.0:
                check_state['last_log']=now
                log_event(f'Live target monitor OK: checks={check_state["count"]} handle={handle} rect={rect} client={client} dpi={dpi}.')
            return True

        return live_check

    def lock_setup(self):
        if self.activity or self.closing:
            return False
        if DrawBotApp._target_lock_valid(self):
            return DrawBotApp.unlock_setup(self)
        ready, message = DrawBotApp._start_guard_ready(self, require_image=True)
        if not ready:
            DrawBotApp._invalidate_target_lock(self, 'lock prerequisites incomplete')
            self.status.set(message)
            try:self.summary.set(message + ' Run the small test successfully, then press Lock setup.')
            except (tk.TclError, AttributeError):pass
            log_event(f'Target/setup lock blocked: {message}')
            return False
        try:
            current_client = self._refresh_target_for_draw()
            paint_profile = self.game.get() == 'Microsoft Paint'
            if not bypasses_palette(self):
                load_calibration(self.calibration_path, current_client_rect=current_client, require_anchor=paint_profile, profile_key=PROFILES[self.game.get()][0])
            fingerprint = DrawBotApp._build_target_lock_fingerprint(self, current_client_rect=current_client, current_target_rect=self.target_window[1], current_dpi=self.target_dpi)
        except (OSError, ValueError, InterruptedError) as error:
            DrawBotApp._invalidate_target_lock(self, 'lock failed')
            self.status.set(f'Lock setup failed: {error}')
            try:self.summary.set('Setup remains unlocked. Fix the target window, drawing area, palette or tool calibration, then run Lock setup again.')
            except (tk.TclError, AttributeError):pass
            log_event(f'Target/setup lock failed: {error!r}')
            return False
        DrawBotApp._invalidate_safety_preflight(self, 'new target lock created', disarm=True)
        self.target_lock_passed = True
        self.target_lock_fingerprint = fingerprint
        self.target_lock_signature = DrawBotApp._target_lock_signature_from(fingerprint)
        DrawBotApp._refresh_target_lock_text(self)
        self.status.set('Setup locked. Window, DPI, drawing area and palette/tool layout must stay unchanged. Next: Safety preflight.')
        try:self.summary.set('Target Lock PASS: setup fingerprint saved. If Paint/browser moves, resizes, changes DPI, or palette/tool positions change, full drawing will stop before any mouse input.')
        except (tk.TclError, AttributeError):pass
        log_event('Target/setup lock passed. Fingerprint saved for target window, DPI, drawing area, palette and tools.')
        self.set_busy(None)
        return True

    def unlock_setup(self):
        DrawBotApp._invalidate_target_lock(self, 'setup manually unlocked', disarm=True)
        self.status.set('Setup unlocked. Any previous preflight/dry run/unlock is cleared. Change settings or lock setup again before full drawing.')
        try:self.summary.set('Setup lock cleared. Full drawing is locked until Small test → Lock setup → Safety preflight → Dry run → Unlock → Start is completed again.')
        except (tk.TclError, AttributeError):pass
        log_event('Target/setup lock manually cleared.')
        self.set_busy(None)
        return True


    def _strict_safety_required(self):
        # Diagnostic gates remain available, but no profile requires them.
        return False

    def _automatic_paint_preparation(self):
        """Only Auto may replace Paint's selected tool and calibration at Start."""
        profile=getattr(getattr(self,'game',None),'get',lambda:None)()
        selected=getattr(getattr(self,'paint_tool',None),'get',lambda:'Auto (recommended)')()
        return profile=='Microsoft Paint' and selected=='Auto (recommended)'

    def _browser_drawing_region(self, *, require_verified=False):
        region=getattr(self,'browser_drawing_region',None)
        if region is None:return None
        from BrowserDrawingRegion import BrowserDrawingRegion
        if not isinstance(region,BrowserDrawingRegion):
            raise ValueError('Select the drawing area again to bind its browser window.')
        target=getattr(self,'target_window',None)
        if not target:raise ValueError('Select the drawing area again to bind its browser window.')
        meta={'handle':target[0],'client_rect':getattr(self,'target_client_rect',None),
              'dpi':getattr(self,'target_dpi',None)}
        region.require_current(PROFILES.get(self.game.get(),('',))[0],meta,self.corners,
                               verified=require_verified)
        return region

    def _start_guard_ready(self, *, require_image=True):
        """Return basic setup readiness without moving or clicking the mouse."""
        if require_image and self.original is None:
            return False, 'Start locked: load, paste, or drop an image first.'
        if len(self.corners) != 2:
            return False, 'Start locked: select the drawing area first.'
        if getattr(self,'target_window',None) is None:
            return False, 'Start locked: the target window is not locked. Select the drawing area again.'
        try:DrawBotApp._browser_drawing_region(self,require_verified=True)
        except ValueError as error:return False, 'Start locked: '+str(error)
        if not self._palette_preflight_ready():
            return False, 'Start locked: read the color palette first, or enable a Paint mode that intentionally bypasses palette clicks.'
        if not self._paint_tool_preflight_ready():
            return False, 'Start locked: calibrate Paint tools first. Auto mode needs Pencil, or Brush plus 100% opacity.'
        if DrawBotApp._strict_safety_required(self) and not bool(getattr(self,'small_test_passed',False)):
            return False, 'Start locked: run Draw small test successfully before a full Paint drawing.'
        return True, 'Basic setup ready.'

    def run_safety_preflight(self):
        """Explicit no-click gate before Unlock full drawing becomes available."""
        if self.activity or self.closing:
            return
        ready,message=DrawBotApp._start_guard_ready(self,require_image=True)
        if not ready:
            DrawBotApp._invalidate_safety_preflight(self,'preflight prerequisites incomplete')
            self.status.set(message)
            try:self.summary.set(message + ' Complete the checklist, then run Safety preflight again.')
            except (tk.TclError,AttributeError):pass
            log_event(f'Safety preflight blocked: {message}')
            return False
        if not DrawBotApp._target_lock_valid(self):
            DrawBotApp._invalidate_safety_preflight(self,'target lock missing before preflight')
            self.status.set('Safety preflight locked: press Lock setup first. The lock fingerprints target window, DPI, drawing area and palette.')
            try:self.summary.set('Target Lock is required before Safety preflight. Run the small test, press Lock setup, then run Safety preflight.')
            except (tk.TclError,AttributeError):pass
            log_event('Blocked Safety preflight because Target Lock was not valid.')
            return False
        self.status.set('Running safety preflight… No mouse input will be sent.')
        log_event('Safety preflight started. Mouse input remains DISARMED.')
        try:
            DrawBotApp._verify_target_lock(self)
            self._refresh_target_for_draw()
            ready,message=DrawBotApp._start_guard_ready(self,require_image=True)
            if not ready:raise ValueError(message.replace('Start locked: ','',1))
            self.safety_preflight_passed=True
            self.safety_preflight_signature=DrawBotApp._current_safety_signature(self)
            self.safety_preflight_valid_until=time.monotonic()+60.0
            DrawBotApp._disarm_full_draw(self,'preflight passed; waiting for explicit unlock',update_text=True)
            self.status.set('Safety preflight passed for 60 seconds. Now run Dry run, then Unlock full drawing and Start Drawing.')
            try:self.summary.set('Safety preflight PASS: image, target window, drawing area, palette/tools and small test are valid. No mouse input was sent. Next: run Dry run.')
            except (tk.TclError,AttributeError):pass
            log_event('Safety preflight passed. Valid for 60 seconds or until setup changes.')
            self.set_busy(None)
            return True
        except (OSError,ValueError,InterruptedError) as error:
            DrawBotApp._invalidate_safety_preflight(self,'preflight failed')
            self.status.set(f'Safety preflight failed: {error}')
            try:self.summary.set('Full drawing remains locked. Fix the reported setup problem and run Safety preflight again.')
            except (tk.TclError,AttributeError):pass
            log_event(f'Safety preflight failed: {error!r}')
            self.set_busy(None)
            return False

    def _full_draw_unlocked(self):
        return time.monotonic() <= float(getattr(self, 'full_draw_armed_until', 0.0) or 0.0)

    def _refresh_start_buttons_text(self):
        if getattr(self,'closing',False):
            return
        unlocked = DrawBotApp._full_draw_unlocked(self)
        start_text = ('▶️  Prepare Paint & draw' if DrawBotApp._automatic_paint_preparation(self) else
                      ('▶️  Start Drawing' if unlocked else '🔒  Start locked'))
        unlock_text = '✓  Unlocked for 12s' if unlocked else '🔓  Unlock full drawing'
        for name in ('start', 'start_secondary'):
            widget = getattr(self, name, None)
            if widget is not None:
                DrawBotApp._safe_widget_configure(widget, text=start_text)
        for name in ('start_unlock', 'start_unlock_secondary'):
            widget = getattr(self, name, None)
            if widget is not None:
                DrawBotApp._safe_widget_configure(widget, text=unlock_text)

    def _disarm_full_draw(self, reason='', update_text=True):
        was_unlocked = DrawBotApp._full_draw_unlocked(self)
        self.full_draw_armed_until = 0.0
        DrawBotApp._cancel_after_attr(self, 'draw_arm_after')
        if reason and was_unlocked:
            log_event(f'Full drawing safety lock reset: {reason}.')
        if update_text:
            DrawBotApp._refresh_start_buttons_text(self)

    def _expire_full_draw_arm(self):
        self.draw_arm_after = None
        if DrawBotApp._full_draw_unlocked(self):
            return
        self.full_draw_armed_until = 0.0
        DrawBotApp._refresh_start_buttons_text(self)
        if not self.activity and not self.closing:
            try:self.status.set('Full drawing safety unlock expired. Press Unlock full drawing again when everything is ready.')
            except tk.TclError:pass

    def _manual_drop_in_armed(self):
        var=getattr(self,'manual_drop_in_start',None)
        get=getattr(var,'get',None)
        if get is None or not bool(get()):
            return False
        return time.monotonic() <= float(getattr(self,'manual_drop_in_armed_until',0.0) or 0.0)

    def _refresh_manual_drop_in_ui(self):
        armed=DrawBotApp._manual_drop_in_armed(self)
        text='⚡  Drop-In armed' if armed else '⚡  Arm Drop-In Start'
        widget=getattr(self,'drop_in_button',None)
        if widget is not None:
            DrawBotApp._safe_widget_configure(widget,text=text)
        detail=getattr(self,'drop_in_text',None)
        if detail is not None:
            try:
                if armed:
                    remaining=max(0,int(float(getattr(self,'manual_drop_in_armed_until',0.0) or 0.0)-time.monotonic()))
                    detail.set(f'Drop-In Start armed for the next image import/drop · {remaining}s left · browser/game profiles only.')
                else:
                    detail.set('Drop-In Start is off. Arm it after target canvas and palette are ready.')
            except (tk.TclError,RuntimeError):
                pass

    def _disarm_manual_drop_in(self, reason=''):
        self.drop_action_pending=None
        self.pending_drop_in_import=None
        self.drop_in_start_context=None
        DrawBotApp._cancel_after_attr(self,'pending_drop_in_after')
        self.drop_in_sync_phase=DROP_SYNC_IDLE
        var=getattr(self,'manual_drop_in_start',None)
        if getattr(var,'set',None) is not None:
            try:var.set(False)
            except (tk.TclError,RuntimeError):pass
        self.manual_drop_in_armed_until=0.0
        DrawBotApp._cancel_after_attr(self,'manual_drop_in_after')
        DrawBotApp._refresh_manual_drop_in_ui(self)
        if reason:
            log_event(f'Manual Drop-In Start disarmed: {reason}.')

    def _expire_manual_drop_in(self):
        self.manual_drop_in_after=None
        if DrawBotApp._manual_drop_in_armed(self):
            DrawBotApp._refresh_manual_drop_in_ui(self)
            try:self.manual_drop_in_after=self.root.after(1000,self._expire_manual_drop_in)
            except (tk.TclError,RuntimeError,AttributeError):self.manual_drop_in_after=None
            return
        DrawBotApp._disarm_manual_drop_in(self,'arm timeout')
        if not self.activity and not self.closing:
            try:self.status.set('Drop-In Start expired. Arm it again before importing the next image.')
            except (tk.TclError,RuntimeError):pass

    def arm_manual_drop_in(self):
        """Arm a one-shot browser/game image import that starts drawing after load."""
        if self.activity or self.closing:
            return
        ready,message=DrawBotApp._start_guard_ready(self,require_image=False)
        if self.game.get()=='Gartic Phone' and not ready:
            callback=getattr(self,'arm_smart_canvas_drop',None)
            if callable(callback):
                self.status.set('Drop-In Start: detecting the Gartic canvas so you can drop a Google/Chrome image directly on it…')
                log_event('Gartic Drop-In requested before setup was ready; starting read-only Smart Canvas discovery.')
                return bool(callback())
        ok,explanation=can_arm_drop_in(self.game.get(),ready=ready,message=message)
        if not ok:
            DrawBotApp._disarm_manual_drop_in(self,'arm rejected')
            self.status.set(explanation)
            try:self.summary.set(explanation + ' This mode is one-shot and never persists between sessions.')
            except (tk.TclError,AttributeError):pass
            log_event(explanation)
            return False
        try:
            self._refresh_target_for_draw()
        except (OSError,ValueError,InterruptedError) as error:
            DrawBotApp._disarm_manual_drop_in(self,'target verification failed before arm')
            self.status.set(f'Drop-In Start blocked: {error}')
            log_event(f'Drop-In Start blocked by target verification: {error!r}')
            return False
        self.manual_drop_in_start.set(True)
        self.manual_drop_in_armed_until=time.monotonic()+DROP_IN_ARM_SECONDS
        DrawBotApp._cancel_after_attr(self,'manual_drop_in_after')
        try:self.manual_drop_in_after=self.root.after(1000,self._expire_manual_drop_in)
        except (tk.TclError,RuntimeError,AttributeError):self.manual_drop_in_after=None
        DrawBotApp._refresh_manual_drop_in_ui(self)
        self.status.set('Drop-In Start armed. Drop/select/paste/load the next image and Image Draw Bot will start drawing on the current canvas.')
        try:self.summary.set('Manual Drop-In Start is armed for one image import. It still uses CanvasGuard and target checks before mouse input. Paint keeps the full safety chain and is not auto-started.')
        except (tk.TclError,AttributeError):pass
        log_event('Manual Drop-In Start armed for next image import.')
        # Gartic users expect to drag from Google Images directly onto the game.
        # Reuse Smart Canvas Drop automatically so the temporary OS drop target
        # sits exactly over the detected canvas while this one-shot arm is live.
        if self.game.get()=='Gartic Phone':
            callback=getattr(self,'arm_smart_canvas_drop',None)
            if callable(callback):
                try:self.root.after(25,callback)
                except (tk.TclError,RuntimeError,AttributeError):pass
        return True

    def _drop_in_fingerprint(self):
        return drop_in_target_fingerprint(
            self.game.get(), getattr(self,'target_window',None),
            getattr(self,'target_client_rect',None), getattr(self,'target_dpi',None))

    def _drop_in_wait_description(self):
        phase=getattr(self,'drop_in_sync_phase',DROP_SYNC_IDLE)
        if getattr(self,'activity',None)=='browser-auto-calibration' or phase==DROP_SYNC_AUTO_SETUP:
            return 'Auto Setup'
        if phase==DROP_SYNC_VISUAL_PREFLIGHT:
            return 'Visual Preflight'
        if phase==DROP_SYNC_AUTO_RECALIBRATING:
            return 'Auto-Recalibration'
        return 'browser setup'

    def _schedule_drop_in_sync_tick(self, delay=120):
        DrawBotApp._cancel_after_attr(self,'pending_drop_in_after')
        if self.closing:return False
        try:self.pending_drop_in_after=self.root.after(max(20,int(delay)),self._drop_in_sync_tick)
        except (tk.TclError,RuntimeError,AttributeError):self.pending_drop_in_after=None;return False
        return True

    def _drop_in_sync_tick(self):
        self.pending_drop_in_after=None
        if self.closing:return False
        request=getattr(self,'pending_drop_in_import',None)
        if request is not None:
            if pending_drop_in_expired(request):
                self.pending_drop_in_import=None
                DrawBotApp._disarm_manual_drop_in(self,'pending setup wait timeout')
                try:self.status.set('Drop-In expired: browser setup did not complete within 30 seconds. The queued image was not started.')
                except Exception:pass
                log_event('Drop-In synchronization expired while waiting for browser setup.')
                return False
            if not pending_drop_in_target_matches(request,DrawBotApp._drop_in_fingerprint(self)):
                self.pending_drop_in_import=None
                DrawBotApp._disarm_manual_drop_in(self,'target changed while waiting')
                try:self.status.set('Drop-In cancelled: target changed while waiting for browser setup.')
                except Exception:pass
                log_event('Drop-In synchronization cancelled because target/profile/DPI changed while waiting.')
                return False
            if not drop_in_should_wait(activity=getattr(self,'activity',None),phase=getattr(self,'drop_in_sync_phase',None)):
                return DrawBotApp._resume_pending_drop_in_import(self)
            DrawBotApp._schedule_drop_in_sync_tick(self,120)
            return True
        if normalize_drop_in_action(getattr(self,'drop_action_pending',None))==DROP_IN_ACTION:
            if drop_in_should_wait(activity=getattr(self,'activity',None),phase=getattr(self,'drop_in_sync_phase',None)):
                self.drop_in_sync_phase=DROP_SYNC_PENDING
                DrawBotApp._schedule_drop_in_sync_tick(self,120)
                return True
            return DrawBotApp._run_pending_drop_in_start(self)
        return False

    def _queue_pending_drop_in_import(self, source, label, action):
        action=normalize_drop_in_action(action)
        if action!=DROP_IN_ACTION or not DrawBotApp._manual_drop_in_armed(self):return False
        previous=getattr(self,'pending_drop_in_import',None)
        wait=DrawBotApp._drop_in_wait_description(self)
        active_phase=getattr(self,'drop_in_sync_phase',DROP_SYNC_IDLE)
        request=make_pending_drop_in_request(
            source,label,action,DrawBotApp._drop_in_fingerprint(self),previous=previous,
            timeout_seconds=DROP_SYNC_TIMEOUT_SECONDS)
        self.pending_drop_in_import=request
        self.drop_in_start_context=request
        # Hold the explicit one-shot authorization while the read-only setup is
        # allowed to finish. It still expires quickly and is never persisted.
        self.manual_drop_in_armed_until=max(float(getattr(self,'manual_drop_in_armed_until',0.0) or 0.0),request.deadline+1.0)
        if not drop_in_should_wait(activity=getattr(self,'activity',None),phase=active_phase):
            self.drop_in_sync_phase=DROP_SYNC_PENDING
        if previous is None:
            text=f'Drop-In queued. Waiting for {wait} to finish before loading the image…'
            log_event(f'Drop-In image queued during {wait}: {label!r}.')
        else:
            text=f'Drop-In updated: latest image wins. Waiting for {wait} to finish…'
            log_event(f'Drop-In pending image replaced: old={previous.label!r} new={label!r} sequence={request.sequence}.')
        try:self.status.set(text);self.drop_in_text.set(text)
        except Exception:pass
        DrawBotApp._schedule_drop_in_sync_tick(self,120)
        return True

    def _resume_pending_drop_in_import(self):
        request=getattr(self,'pending_drop_in_import',None)
        if request is None:return False
        if pending_drop_in_expired(request):
            self.pending_drop_in_import=None
            DrawBotApp._disarm_manual_drop_in(self,'pending setup wait timeout')
            try:self.status.set('Drop-In expired: browser setup did not complete in time.')
            except Exception:pass
            return False
        if not pending_drop_in_target_matches(request,DrawBotApp._drop_in_fingerprint(self)):
            self.pending_drop_in_import=None
            DrawBotApp._disarm_manual_drop_in(self,'target changed while waiting')
            try:self.status.set('Drop-In cancelled: target changed while waiting for setup.')
            except Exception:pass
            return False
        if self.activity or self.closing or drop_in_should_wait(activity=self.activity,phase=getattr(self,'drop_in_sync_phase',None)):
            DrawBotApp._schedule_drop_in_sync_tick(self,120);return True
        self.pending_drop_in_import=None
        self.drop_in_start_context=request
        self.drop_in_sync_phase=DROP_SYNC_READY
        try:self.status.set(f'Browser setup ready. Loading queued Drop-In image: {request.label}')
        except Exception:pass
        log_event(f'Drop-In synchronization resuming queued image after setup: {request.label!r}.')
        return bool(DrawBotApp.load_source(self,request.source,request.label,action=request.action,_from_sync=True))

    def _queue_drop_in_start(self, action, *, source_label='image'):
        action=normalize_drop_in_action(action)
        if action is None:
            if getattr(self,'drop_action_pending',None)==DROP_IN_ACTION:self.drop_action_pending=None
            return False
        if not DrawBotApp._manual_drop_in_armed(self):
            self.drop_action_pending=None
            log_event(f'Manual Drop-In Start ignored for {source_label!r}: arm expired or disabled.')
            return False
        if getattr(self,'drop_in_start_context',None) is None:
            self.drop_in_start_context=make_pending_drop_in_request(
                None,source_label,DROP_IN_ACTION,DrawBotApp._drop_in_fingerprint(self),
                timeout_seconds=DROP_SYNC_TIMEOUT_SECONDS)
        self.drop_action_pending=DROP_IN_ACTION
        self.drop_in_sync_phase=DROP_SYNC_PENDING
        log_event(f'Manual Drop-In Start queued after image import: {source_label!r}.')
        return True

    def _schedule_pending_drop_in_start(self):
        if normalize_drop_in_action(getattr(self,'drop_action_pending',None)) != DROP_IN_ACTION:
            return False
        try:self.root.after(60,self._run_pending_drop_in_start)
        except (tk.TclError,RuntimeError,AttributeError):self._run_pending_drop_in_start()
        return True

    def _run_pending_drop_in_start(self):
        if normalize_drop_in_action(getattr(self,'drop_action_pending',None)) != DROP_IN_ACTION:
            return False
        if self.closing:return False
        stop=getattr(self,'stop',None)
        if stop is not None and stop.is_set():
            DrawBotApp._disarm_manual_drop_in(self,'cancelled before queued drawing')
            self.status.set('Drop-In cancelled. The image remains loaded.')
            return False
        context=getattr(self,'drop_in_start_context',None)
        if context is not None:
            if pending_drop_in_expired(context):
                DrawBotApp._disarm_manual_drop_in(self,'pending draw timeout')
                self.status.set('Drop-In expired while waiting for browser setup. The image remains loaded.')
                log_event('Drop-In draw request expired before setup became ready.')
                return False
            if not pending_drop_in_target_matches(context,DrawBotApp._drop_in_fingerprint(self)):
                DrawBotApp._disarm_manual_drop_in(self,'target changed while waiting')
                self.status.set('Drop-In cancelled: target changed while waiting. The image remains loaded.')
                log_event('Drop-In draw request cancelled because target/profile/DPI changed while waiting.')
                return False
        if drop_in_should_wait(activity=getattr(self,'activity',None),phase=getattr(self,'drop_in_sync_phase',None)):
            wait=DrawBotApp._drop_in_wait_description(self)
            self.status.set(f'Drop-In ready with image loaded. Waiting for {wait} to finish…')
            log_event(f'Drop-In draw request waiting for {wait}.')
            DrawBotApp._schedule_drop_in_sync_tick(self,120)
            return True
        if self.activity:
            # Never piggyback a one-shot authorization onto unrelated work such
            # as an active drawing/recording. Only read-only browser setup waits.
            self.status.set(f'Drop-In cannot start while {self.activity} is active.')
            log_event(f'Drop-In draw request not started because non-waitable activity={self.activity!r}.')
            DrawBotApp._disarm_manual_drop_in(self,'unrelated work interrupted queued drawing')
            return False
        if not DrawBotApp._manual_drop_in_armed(self):
            self.status.set('Drop-In Start did not run because the arm expired before the image finished loading.')
            log_event('Manual Drop-In Start skipped: arm expired before load completed.')
            self.drop_action_pending=None
            return False
        if DrawBotApp._strict_safety_required(self):
            DrawBotApp._disarm_manual_drop_in(self,'strict Paint profile')
            self.status.set('Drop-In Start is blocked for Microsoft Paint. Use the full Paint safety chain before Start Drawing.')
            log_event('Manual Drop-In Start blocked for Microsoft Paint.')
            return False
        ready,message=DrawBotApp._start_guard_ready(self,require_image=True)
        if not ready:
            # Browser setup can still be converging after the image loader has
            # finished. Keep the explicit request alive for the bounded sync
            # window instead of rejecting it immediately.
            try:
                from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
                profile_key=PROFILES.get(self.game.get(),('',))[0]
            except Exception:
                profile_key=''
            if profile_key in SUPPORTED_BROWSER_PROFILES and context is not None and not pending_drop_in_expired(context):
                self.drop_in_sync_phase=DROP_SYNC_PENDING
                self.status.set('Drop-In waiting for browser setup readiness…')
                log_event(f'Drop-In start guard not ready yet; retaining pending request: {message}')
                DrawBotApp._schedule_drop_in_sync_tick(self,150)
                return True
            DrawBotApp._disarm_manual_drop_in(self,'start guard failed after image load')
            self.status.set('Drop-In Start blocked: '+message.replace('Start locked: ','',1))
            log_event(f'Manual Drop-In Start blocked after load: {message}')
            return False
        try:
            self._refresh_target_for_draw()
        except (OSError,ValueError,InterruptedError) as error:
            DrawBotApp._disarm_manual_drop_in(self,'target verification failed after image load')
            self.status.set(f'Drop-In Start blocked: {error}')
            log_event(f'Manual Drop-In Start target verification failed after load: {error!r}')
            return False
        # _refresh_target_for_draw may apply a safe auto-recalibration. Require
        # the same target/profile identity captured when the user dropped the
        # image; geometry changes inside that target are allowed.
        if context is not None:
            current=DrawBotApp._drop_in_fingerprint(self)
            same_identity=pending_drop_in_target_matches(context,current)
            if not same_identity:
                DrawBotApp._disarm_manual_drop_in(self,'target identity changed after verification')
                self.status.set('Drop-In cancelled: the selected browser/profile changed before drawing.')
                return False
        if stop is not None and stop.is_set():
            DrawBotApp._disarm_manual_drop_in(self,'cancelled during target verification')
            self.status.set('Drop-In cancelled. The image remains loaded.')
            return False
        self.drop_action_pending=None
        self.drop_in_sync_phase=DROP_SYNC_READY
        # Preserve authorization only long enough to enter draw(); then revoke it
        # before planning/native input as the one-shot action has been consumed.
        DrawBotApp._disarm_manual_drop_in(self,'image accepted')
        self.status.set('Drop-In Start accepted. Building final drawing plan now…')
        log_event('Manual Drop-In Start accepted after synchronized image import. Starting drawing with explicit drop-in authorization.')
        return DrawBotApp.draw(self,user_initiated=True)


    def _correction_review_context(self):
        strict = False
        try:
            strict = DrawBotApp._strict_safety_required(self)
        except Exception:
            strict = False
        try:
            strict_ready = bool(DrawBotApp._target_lock_valid(self) and DrawBotApp._safety_preflight_valid(self) and (DrawBotApp._dry_run_valid(self) if strict else True))
        except Exception:
            strict_ready = False
        try:
            unlocked = bool(DrawBotApp._full_draw_unlocked(self))
        except Exception:
            unlocked = False
        # Capture belongs to GuardedMouse, not the raw WindowsMouse backend.
        can_snapshot = bool(getattr(self, 'mouse', None) is not None and
                            getattr(self, 'target_window', None) and len(getattr(self, 'corners', ())) == 2)
        return can_snapshot, strict_ready, unlocked

    def refresh_correction_review_ui(self):
        """Refresh the Step 15 post-draw correction/recovery card."""
        try:
            from CorrectionReviewRecovery import build_correction_review_state, format_correction_review
            opts = (self.plan or {}).get('options', {}) if isinstance(getattr(self, 'plan', None), dict) else {}
            can_snapshot, strict_ready, unlocked = DrawBotApp._correction_review_context(self)
            state = build_correction_review_state(opts, can_snapshot=can_snapshot,
                                                  strict_safety_ready=strict_ready,
                                                  full_start_unlocked=unlocked)
            self.correction_review_meta = state
            if hasattr(self, 'correction_review_text'):
                text = format_correction_review(state)
                # Sidebar cards are small. Keep the main review dialog verbose,
                # but keep this label readable.
                lines = text.splitlines()
                self.correction_review_text.set('\n'.join(lines[:5]))
            actions = state.get('actions') if isinstance(state, dict) else {}
            for attr, key in (('correction_retry_button', 'retry_correction_only'),
                              ('correction_full_retry_button', 'retry_full_drawing'),
                              ('correction_review_button', 'rerun_result_verification'),
                              ('result_recheck_button', 'rerun_result_verification')):
                widget = getattr(self, attr, None)
                if widget is None:
                    continue
                item = actions.get(key) if isinstance(actions, dict) and isinstance(actions.get(key), dict) else {}
                enabled = bool(item.get('enabled')) if attr != 'correction_review_button' else bool(opts)
                DrawBotApp._safe_widget_configure(widget, state='normal' if (enabled and not self.activity) else 'disabled')
            try:
                history = state.get('history') if isinstance(state, dict) else {}
                summary = history.get('summary') if isinstance(history, dict) and isinstance(history.get('summary'), dict) else {}
                widget = getattr(self, 'correction_history_button', None)
                if widget is not None:
                    DrawBotApp._safe_widget_configure(widget, state='normal' if (int(summary.get('entry_count', 0) or 0) > 0 and not self.activity) else 'disabled')
            except Exception:
                pass
            return state
        except Exception as error:
            try:
                if hasattr(self, 'correction_review_text'):
                    self.correction_review_text.set(f'Correction Review unavailable: {error}')
            except Exception:
                pass
            return {}

    def show_correction_review(self):
        if self.activity or self.closing:
            return
        try:
            from CorrectionReviewRecovery import format_correction_review
            state = DrawBotApp.refresh_correction_review_ui(self)
            messagebox.showinfo('Correction Review', format_correction_review(state), parent=self.root)
        except Exception as error:
            self.status.set(f'Correction Review unavailable: {error}')

    def show_correction_history(self):
        if self.activity or self.closing:
            return
        try:
            from CorrectionHistory import load_correction_history, format_correction_history
            opts = (self.plan or {}).get('options', {}) if isinstance(getattr(self, 'plan', None), dict) else {'profile_key': PROFILES[self.game.get()][0]}
            history = load_correction_history(opts, limit=8)
            self.correction_history_meta = history
            messagebox.showinfo('Correction History', format_correction_history(history), parent=self.root)
        except Exception as error:
            self.status.set(f'Correction History unavailable: {error}')

    def _result_recheck_current(self, request):
        """Read only plain controller state; this also runs on the worker."""
        if (not isinstance(request, ResultRecheckRequest) or
                request is not getattr(self, 'result_recheck_request', None) or
                self.activity != 'result-recheck' or self.closing or self.stop.is_set() or
                getattr(self, 'pending_clear_drawing', None) is not None or
                getattr(self, 'profile_change_after', None) is not None or
                getattr(self, 'profile_change_in_progress', False)):
            return False
        try:
            profile = self._active_profile_name
            return request.matches(plan=self.plan, source=self.original,
                profile_name=profile, profile_key=PROFILES[profile][0],
                target=self.target_window, area=self.area(),
                client_rect=getattr(self, 'target_client_rect', ()),
                dpi=getattr(self, 'target_dpi', None))
        except (AttributeError, KeyError, TypeError, ValueError):
            return False

    def _finish_result_recheck(self, request=None):
        request = request if request is not None else getattr(self, 'result_recheck_request', None)
        if isinstance(request, ResultRecheckRequest):
            request.cancel()
            request.release()
            if request is getattr(self, 'result_recheck_request', None):
                self.result_recheck_request = None

    def recheck_drawing_result(self):
        """Observe the current canvas without arming or sending native input."""
        if not DrawBotApp._profile_action_ready(self):
            return False
        state = DrawBotApp.refresh_correction_review_ui(self)
        action = (state.get('actions') or {}).get('rerun_result_verification') or {}
        if not action.get('enabled'):
            self.status.set('Result re-check unavailable: ' + str(action.get('reason') or 'complete a drawing first.'))
            return False
        DrawBotApp._finish_result_recheck(self)
        # Clear a previous operation's Stop exactly once, before this request
        # and its monitor/thread constructors acquire cancellation ownership.
        self.stop.clear()
        request = None
        accepted = False
        try:
            profile = self._active_profile_name
            key = PROFILES[profile][0]
            options = self.plan.get('options') or {}
            if (options.get('profile_key', key) != key or
                    options.get('profile_name', profile) != profile):
                raise ValueError('The retained drawing belongs to another profile. Draw again before re-checking.')
            request = ResultRecheckRequest(self.plan, self.original, profile, key,
                self.target_window, self.area(), getattr(self, 'target_client_rect', ()),
                getattr(self, 'target_dpi', None))
            self.result_recheck_request = request
            from ScreenGuard import GuardedMouse, WindowMonitor
            guarded = GuardedMouse(self.mouse, WindowMonitor(), request.target)
            self.status.set('Checking the current result. Keep the target visible; no mouse input will be sent.')
            def work():
                result = recheck_result(request, guarded, self.stop,
                    lambda seconds: self.stop.wait(seconds),
                    lambda message: self.events.put(('result_recheck_status', (request, message))),
                    current=lambda: DrawBotApp._result_recheck_current(self, request))
                self.events.put(('result_recheck_complete', result))
            accepted = bool(self.begin_worker('result-recheck', work, reset_stop=False))
            return accepted
        except (OSError, ValueError, RuntimeError, AttributeError, KeyError, TypeError) as error:
            self.status.set(f'Result re-check could not start: {error}')
            return False
        finally:
            if not accepted:
                DrawBotApp._finish_result_recheck(self, request)

    def retry_full_after_review(self):
        """User-visible full retry entry point that never bypasses safety gates."""
        if self.activity or self.closing:
            return
        if not isinstance(getattr(self, 'plan', None), dict):
            self.status.set('Full retry unavailable: build or run a drawing plan first.')
            return
        ready, message = DrawBotApp._start_guard_ready(self, require_image=True)
        if not ready:
            self.status.set('Full retry locked: ' + message.replace('Start locked: ', '', 1))
            return
        strict = DrawBotApp._strict_safety_required(self)
        if strict:
            if not DrawBotApp._target_lock_valid(self):
                self.status.set('Full retry locked: press Lock setup first.')
                return
            if not DrawBotApp._safety_preflight_valid(self):
                self.status.set('Full retry locked: run Safety preflight first.')
                return
            if not DrawBotApp._dry_run_valid(self):
                self.status.set('Full retry locked: run Fast Dry run first.')
                return
        if not DrawBotApp._full_draw_unlocked(self):
            self.status.set('Full retry ready: press Unlock full drawing, then Full retry or Start Drawing within 12 seconds.')
            return
        self.status.set('Starting full retry with current image/settings. Existing safety gates remain active.')
        return DrawBotApp.start_full_drawing(self)

    def retry_post_draw_correction(self):
        """Run only a new bounded post-draw correction pass from a fresh snapshot.

        This is a real native-input action, so it requires the same visible target,
        palette/tool readiness, Target Lock, Safety preflight and Unlock state as a
        full draw.  It reuses the existing plan and source image; it does not
        rebuild/restart the whole drawing.
        """
        if not DrawBotApp._profile_action_ready(self):
            return
        if not isinstance(getattr(self, 'plan', None), dict):
            self.status.set('Correction-only retry unavailable: no completed plan exists yet.')
            return
        state = DrawBotApp.refresh_correction_review_ui(self)
        action = ((state.get('actions') or {}).get('retry_correction_only') or {}) if isinstance(state, dict) else {}
        if not action.get('enabled'):
            self.status.set('Correction-only retry locked: ' + str(action.get('reason') or 'current review state does not allow a safe correction-only retry.'))
            return
        ready, message = DrawBotApp._start_guard_ready(self, require_image=True)
        if not ready:
            self.status.set('Correction-only retry locked: ' + message.replace('Start locked: ', '', 1))
            return
        strict = DrawBotApp._strict_safety_required(self)
        if strict:
            if not DrawBotApp._target_lock_valid(self):
                self.status.set('Correction-only retry locked: press Lock setup first.')
                return
            try:
                DrawBotApp._verify_target_lock(self)
            except (OSError, ValueError, InterruptedError) as error:
                self.status.set(f'Correction-only retry locked: {error}')
                return
            if not DrawBotApp._safety_preflight_valid(self):
                self.status.set('Correction-only retry locked: run Safety preflight first.')
                return
            if not DrawBotApp._dry_run_valid(self):
                self.status.set('Correction-only retry locked: run Fast Dry run first.')
                return
        if not DrawBotApp._full_draw_unlocked(self):
            self.status.set('Correction-only retry ready: press Unlock full drawing first. Correction-only still sends native input.')
            return
        # This explicit retry owns Esc from preflight through worker startup.
        self.stop.clear()
        try:
            current_client = self._refresh_target_for_draw()
            profile_key = PROFILES[self.game.get()][0]
            paint_profile = self.game.get() == 'Microsoft Paint'
            if not bypasses_palette(self):
                load_calibration(self.calibration_path, current_client_rect=current_client,
                                 require_anchor=paint_profile, profile_key=profile_key)
            current_client = DrawBotApp._run_browser_visual_preflight(self, current_client, reason='correction-only retry')
            area = self.area()
            palette = () if bypasses_palette(self) else tuple((c.x, c.y) for c in allColors)
            from ScreenGuard import GuardedMouse, WindowMonitor
            runtime_palette_guard = runtime_palette_guard_colors(profile_key, palette, allColors)
            guarded = GuardedMouse(self.mouse, WindowMonitor(), self.target_window, runtime_palette_guard,
                                   live_target_check=self._make_live_target_check() if (strict and DrawBotApp._target_lock_valid(self)) else None)
        except (OSError, ValueError, InterruptedError) as error:
            self.status.set(f'Correction-only retry preflight stopped: {error}')
            return
        base_plan = self.plan
        from CorrectionReviewRecovery import build_correction_retry_plan
        retry_plan=build_correction_retry_plan(base_plan)
        self._disarm_full_draw('correction-only retry accepted', update_text=True)
        self.paused.clear(); self.progress['value'] = 0; self.save_settings()
        runtime_request=DrawBotApp._begin_runtime_safety_request(self,'correction-only retry')
        def work():
            self.events.put(('status', 'Correction-only retry starting. Fresh read-only snapshot will be scored before any patch strokes.'))
            retry_plan['options'].pop('runtime_safety_report',None)
            try:
                execute_plan(retry_plan, area, palette, guarded, self.stop, self.paused,
                             lambda k, v: self.events.put((k, v)), dry_run=False, keyboard=self.keyboard,
                             checkpoint=None)
            finally:
                DrawBotApp._publish_runtime_safety_report(self,runtime_request,retry_plan['options'])
            try:
                base_plan['options']['post_draw_before_correction_accuracy_meta'] = retry_plan['options'].get('post_draw_before_correction_accuracy_meta')
                base_plan['options']['post_draw_accuracy_meta'] = retry_plan['options'].get('post_draw_accuracy_meta', base_plan.get('options', {}).get('post_draw_accuracy_meta'))
                base_plan['options']['post_draw_correction_meta'] = retry_plan['options'].get('post_draw_correction_meta', base_plan.get('options', {}).get('post_draw_correction_meta'))
                base_plan['options']['correction_review_meta'] = retry_plan['options'].get('correction_review_meta', base_plan.get('options', {}).get('correction_review_meta'))
                base_plan['options']['correction_history_meta'] = retry_plan['options'].get('correction_history_meta', base_plan.get('options', {}).get('correction_history_meta'))
            except Exception:
                pass
            self.events.put(('correction_review', (base_plan.get('options') or {}).get('correction_review_meta') or {}))
        accepted=False
        try:
            accepted=bool(self.begin_worker('draw',work,reset_stop=False))
        finally:
            if not accepted:
                DrawBotApp._runtime_safety_view(self).finish(runtime_request)
                DrawBotApp.refresh_runtime_safety_ui(self)
        if accepted:
            try:self.root.iconify()
            except tk.TclError:pass

    def run_dry_run(self):
        """Simulate the final plan with cursor moves only. No clicks are sent."""
        if self.activity or self.closing:
            return
        ready,message=DrawBotApp._start_guard_ready(self,require_image=True)
        if not ready:
            DrawBotApp._invalidate_dry_run(self,'dry run prerequisites incomplete')
            self.status.set(message)
            try:self.summary.set(message + ' Fix the setup checklist, run Safety preflight, then run Dry run.')
            except (tk.TclError,AttributeError):pass
            log_event(f'Dry run blocked: {message}')
            return
        if not DrawBotApp._target_lock_valid(self):
            DrawBotApp._invalidate_dry_run(self,'target lock missing before dry run')
            self.status.set('Dry run locked: Lock setup first, then run Safety preflight again.')
            try:self.summary.set('Target Lock must be current before Dry run. This prevents moving through an old canvas or palette layout.')
            except (tk.TclError,AttributeError):pass
            log_event('Blocked dry run because Target Lock was not valid.')
            return
        try:
            DrawBotApp._verify_target_lock(self)
        except (OSError,ValueError,InterruptedError) as error:
            DrawBotApp._invalidate_dry_run(self,'target lock failed before dry run')
            self.status.set(f'Dry run locked: {error}')
            log_event(f'Blocked dry run because Target Lock verification failed: {error!r}')
            return
        if not DrawBotApp._safety_preflight_valid(self):
            DrawBotApp._invalidate_dry_run(self,'safety preflight missing before dry run')
            self.status.set('Dry run locked: run Safety preflight first. The dry run uses the same validated setup but sends no clicks.')
            try:self.summary.set('Safety gate active: Dry run requires a current Safety preflight pass. Full drawing stays locked.')
            except (tk.TclError,AttributeError):pass
            log_event('Blocked dry run because Safety preflight was not valid.')
            return
        self.status.set('Starting fast Dry run. It samples the calibrated route for up to 12 seconds and sends no clicks.')
        log_event('Fast calibrated Dry run requested after valid Safety preflight. Native clicks remain disabled; planning and cursor simulation are time-bounded.')
        return DrawBotApp.draw(self,dry_run=True,user_initiated=True)

    def unlock_full_drawing(self):
        """Separate explicit safety unlock. This never starts drawing."""
        if self.activity or self.closing:
            return
        ready, message = self._start_guard_ready(require_image=True)
        if not ready:
            self._disarm_full_draw('unlock preflight not ready')
            self.status.set(message)
            try:self.summary.set(message + ' Fix the setup checklist first, then press Unlock full drawing. Start Drawing remains locked.')
            except (tk.TclError,AttributeError):pass
            log_event(message)
            return
        if not DrawBotApp._strict_safety_required(self):
            self.full_draw_armed_until = time.monotonic() + 12.0
            DrawBotApp._refresh_start_buttons_text(self)
            try:self.draw_arm_after=self.root.after(12_500, self._expire_full_draw_arm)
            except (tk.TclError,RuntimeError,AttributeError):self.draw_arm_after=None
            self.status.set('Profile setup ready. Full drawing unlocked for 12 seconds. Press Start Drawing. Small test / Lock / Preflight / Dry run are optional diagnostics for this profile.')
            log_event('Non-Paint profile safety-unlocked with simplified flow. Optional diagnostic gates were not required.')
            return True
        if not DrawBotApp._target_lock_valid(self):
            self._disarm_full_draw('target lock missing or expired')
            self.status.set('Unlock blocked: press Lock setup first, then Safety preflight and Dry run again.')
            try:self.summary.set('Target Lock must be current before Unlock full drawing.')
            except (tk.TclError,AttributeError):pass
            log_event('Blocked unlock because Target Lock was not valid.')
            return
        try:
            DrawBotApp._verify_target_lock(self)
        except (OSError,ValueError,InterruptedError) as error:
            self._disarm_full_draw('target lock failed before unlock')
            self.status.set(f'Unlock blocked: {error}')
            log_event(f'Blocked unlock because Target Lock verification failed: {error!r}')
            return
        if not DrawBotApp._safety_preflight_valid(self):
            self._disarm_full_draw('safety preflight missing or expired')
            self.status.set('Unlock blocked: run Safety preflight first. A pass is valid for 60 seconds or until setup changes.')
            try:self.summary.set('Failsafe active: Safety preflight must pass before Unlock full drawing becomes available.')
            except (tk.TclError,AttributeError):pass
            log_event('Blocked unlock because Safety preflight was not valid.')
            return
        if not DrawBotApp._dry_run_valid(self):
            self._disarm_full_draw('dry run missing or expired')
            self.status.set('Unlock blocked: run Fast Dry run first. It checks representative calibrated routes with mouse movement only and no clicks.')
            try:self.summary.set('Failsafe active: Dry run must pass before Unlock full drawing becomes available.')
            except (tk.TclError,AttributeError):pass
            log_event('Blocked unlock because Dry run was not valid.')
            return
        self.full_draw_armed_until = time.monotonic() + 12.0
        DrawBotApp._refresh_start_buttons_text(self)
        try:self.draw_arm_after=self.root.after(12_500, self._expire_full_draw_arm)
        except (tk.TclError,RuntimeError,AttributeError):self.draw_arm_after=None
        test_note = '' if self.small_test_passed else ' Small test has not passed yet; run Draw small test first for the safest path.'
        self.status.set('Full drawing unlocked for 12 seconds. Now press the separate Start Drawing button. Stop/Esc cancels.' + test_note)
        try:self.summary.set('Safety lock passed: image, area, palette/tools and target setup are ready. The next click on Start Drawing begins final planning before any mouse input.' + test_note)
        except (tk.TclError,AttributeError):pass
        log_event('Full drawing safety-unlocked by explicit button or shortcut activation. Waiting for Start Drawing.')

    def start_full_drawing(self):
        """Start is separate from unlock and refuses to run while locked."""
        if self.activity or self.closing:
            return
        if DrawBotApp._automatic_paint_preparation(self):
            if self.original is None:
                self.status.set('Load an image first. Paint will be prepared automatically when you start.');return False
            return self.auto_calibrate_paint_tools(start_after=True)
        ready, message = self._start_guard_ready(require_image=True)
        if not ready:
            self._disarm_full_draw('start preflight not ready')
            self.status.set(message)
            try:self.summary.set(message + ' Start Drawing cannot run until setup is complete and the safety unlock is pressed.')
            except (tk.TclError,AttributeError):pass
            log_event(message)
            return
        if not DrawBotApp._strict_safety_required(self):
            if not DrawBotApp._full_draw_unlocked(self):
                self.status.set('Start Drawing is locked. Press Unlock full drawing first, then Start Drawing within 12 seconds.')
                log_event('Blocked manual Start Drawing because explicit unlock was not active.')
                return
            self._disarm_full_draw('start accepted', update_text=True)
            log_event('Manual Start Drawing accepted after setup checks and explicit unlock.')
            return DrawBotApp.draw(self,user_initiated=True)
        if not DrawBotApp._target_lock_valid(self):
            self._disarm_full_draw('target lock invalid before start')
            self.status.set('Start Drawing is locked: Target Lock expired or setup changed. Lock setup again, then rerun Safety preflight and Dry run.')
            log_event('Blocked Start Drawing because Target Lock was invalid.')
            return
        try:
            DrawBotApp._verify_target_lock(self)
        except (OSError,ValueError,InterruptedError) as error:
            self._disarm_full_draw('target lock failed before start')
            self.status.set(f'Start Drawing is locked: {error}')
            log_event(f'Blocked Start Drawing because Target Lock verification failed: {error!r}')
            return
        if not DrawBotApp._safety_preflight_valid(self):
            self._disarm_full_draw('safety preflight invalid before start')
            self.status.set('Start Drawing is locked: Safety preflight expired or setup changed. Run Safety preflight again.')
            log_event('Blocked Start Drawing because Safety preflight was invalid.')
            return
        if not DrawBotApp._dry_run_valid(self):
            self._disarm_full_draw('dry run invalid before start')
            self.status.set('Start Drawing is locked: Dry run expired or setup changed. Run Dry run again.')
            log_event('Blocked Start Drawing because Dry run was invalid.')
            return
        if not DrawBotApp._full_draw_unlocked(self):
            self.status.set('Start Drawing is locked. Press Unlock full drawing first, then Start Drawing within 12 seconds.')
            try:self.summary.set('Failsafe active: full drawing requires two different controls. This prevents accidental starts before image, area, palette and tool setup are finished.')
            except (tk.TclError,AttributeError):pass
            log_event('Blocked Start Drawing because safety unlock was not active.')
            return
        self._disarm_full_draw('start accepted', update_text=True)
        log_event('Full drawing Start button accepted after separate safety unlock.')
        return DrawBotApp.draw(self,user_initiated=True)

    def confirm_start_drawing(self):
        """Backward compatible alias: old UI/tests route here, but it is now locked."""
        return DrawBotApp.start_full_drawing(self)

    def set_busy(self,activity):
        self.activity=activity
        from ProfileIsolation import update_visibility
        update_visibility(self,PROFILES.get(self.game.get(),('generic',))[0])
        for widget,state in list(self.controls):
            self._safe_widget_configure(widget,state='disabled' if activity else state)
        if hasattr(self,'pause_button'):
            self._safe_widget_configure(self.pause_button,state='normal' if activity=='draw' else 'disabled',text='⏸  Pause · F6')
        if hasattr(self,'paint_check'):
            paint_enabled=(not activity and self.game.get()=='Microsoft Paint')
            self._safe_widget_configure(self.paint_check,state='disabled' if activity else 'normal')
            if hasattr(self,'paint_tool_menu'):
                self._safe_widget_configure(self.paint_tool_menu,state='normal' if paint_enabled else 'disabled')
            if hasattr(self,'paint_tool_button'):
                self._safe_widget_configure(self.paint_tool_button,state='normal' if paint_enabled else 'disabled')
            if hasattr(self,'paint_auto_button'):
                self._safe_widget_configure(self.paint_auto_button,state='normal' if paint_enabled else 'disabled')
        if hasattr(self,'app_tool_button'):
            generic_enabled=(not activity and self.game.get()!='Microsoft Paint')
            self._safe_widget_configure(self.app_tool_button,state='normal' if generic_enabled else 'disabled')
        if hasattr(self,'browser_auto_button'):
            try:
                from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
                key=PROFILES.get(self.game.get(),('',))[0]
                auto_enabled=(not activity and key in SUPPORTED_BROWSER_PROFILES)
            except Exception:
                auto_enabled=False
            self._safe_widget_configure(self.browser_auto_button,state='normal' if auto_enabled else 'disabled')
        if not activity and not self.closing:
            tool_ready=self._paint_tool_preflight_ready()
            palette_ready=self._palette_preflight_ready()
            strict=DrawBotApp._strict_safety_required(self)
            basic_ready=(self.original is not None and len(self.corners)==2 and self.target_window is not None and palette_ready and tool_ready)
            ready=basic_ready and (bool(getattr(self,'small_test_passed',False)) if strict else True)
            target_lock_valid=ready and DrawBotApp._target_lock_valid(self)
            preflight_valid=target_lock_valid and DrawBotApp._safety_preflight_valid(self)
            dry_run_valid=preflight_valid and DrawBotApp._dry_run_valid(self)
            unlocked=(dry_run_valid if strict else basic_ready) and DrawBotApp._full_draw_unlocked(self)
            if DrawBotApp._automatic_paint_preparation(self):unlocked=self.original is not None
            if hasattr(self,'start'):
                self._safe_widget_configure(self.start,state='normal' if unlocked else 'disabled')
            if hasattr(self,'start_secondary'):
                self._safe_widget_configure(self.start_secondary,state='normal' if unlocked else 'disabled')
            if hasattr(self,'target_lock_button'):
                self._safe_widget_configure(self.target_lock_button,state='normal' if ready else 'disabled')
            if hasattr(self,'target_lock_secondary'):
                self._safe_widget_configure(self.target_lock_secondary,state='normal' if ready else 'disabled')
            if hasattr(self,'safety_preflight_button'):
                self._safe_widget_configure(self.safety_preflight_button,state='normal' if target_lock_valid else 'disabled')
            if hasattr(self,'safety_preflight_secondary'):
                self._safe_widget_configure(self.safety_preflight_secondary,state='normal' if target_lock_valid else 'disabled')
            if hasattr(self,'dry_run_button'):
                self._safe_widget_configure(self.dry_run_button,state='normal' if preflight_valid else 'disabled')
            if hasattr(self,'dry_run_secondary'):
                self._safe_widget_configure(self.dry_run_secondary,state='normal' if preflight_valid else 'disabled')
            unlock_ready=dry_run_valid if strict else basic_ready
            if hasattr(self,'start_unlock'):
                self._safe_widget_configure(self.start_unlock,state='normal' if unlock_ready else 'disabled')
            if hasattr(self,'start_unlock_secondary'):
                self._safe_widget_configure(self.start_unlock_secondary,state='normal' if unlock_ready else 'disabled')
            if not ready:self._invalidate_target_lock('setup changed',disarm=True)
            DrawBotApp._refresh_target_lock_text(self)
            DrawBotApp._refresh_start_buttons_text(self)
            if self.original is None:self.next_step.set('Select an image or drag an image file here.')
            elif DrawBotApp._automatic_paint_preparation(self):self.next_step.set('Press Prepare Paint & draw. Canvas, tools and RGB colors are calibrated automatically.')
            elif len(self.corners)!=2:self.next_step.set('Press Select drawing area and mark only the drawable canvas.')
            elif not palette_ready:self.next_step.set('Read the color palette for the selected profile, or use a supported mode that intentionally bypasses palette clicks.')
            elif not tool_ready:self.next_step.set('Calibrate Paint tools. Auto mode needs Pencil, or Brush + 100% opacity.')
            elif strict and not getattr(self,'small_test_passed',False):self.next_step.set('Run Draw small test successfully before full Paint drawing.')
            elif strict and not target_lock_valid:self.next_step.set('Press Lock setup. Target window, DPI, drawing area and palette will be fingerprinted.')
            elif strict and not preflight_valid:self.next_step.set('Run Safety preflight. It sends no mouse input.')
            elif strict and not dry_run_valid:self.next_step.set('Run Fast Dry run. It samples representative calibrated routes for up to 12 seconds; reaching the budget normally counts as PASS when no safety error occurs.')
            elif not unlocked:self.next_step.set(('Dry run passed. ' if strict else '')+'Press Unlock full drawing, then Start Drawing within 12 seconds.')
            else:self.next_step.set('Unlocked. Press Start Drawing to begin real drawing.')
            if hasattr(self,'reuse'):
                self._safe_widget_configure(self.reuse,state='normal' if self.saved_area else 'disabled')
            if hasattr(self,'refresh_correction_review_ui'):
                try:self.refresh_correction_review_ui()
                except (tk.TclError,RuntimeError,AttributeError):pass
        if hasattr(self,'refresh_ui_state'):
            try:self.refresh_ui_state()
            except (tk.TclError,RuntimeError,AttributeError):pass

    def add_profile(self):
        if not DrawBotApp._profile_action_ready(self):return False
        from tkinter import simpledialog
        from GameProfiles import add_custom_profile
        name=simpledialog.askstring('New application profile','What is the drawing application called?',parent=self.root)
        # The modal dialog pumps Tk events; a hotkey may have started work or
        # queued a profile change while it was open.
        if not name or not DrawBotApp._profile_action_ready(self):return False
        try:
            add_custom_profile(name,DATA_DIR/'profiles.json')
            self.profile_selector.configure(values=list(PROFILES))
            self.game.set(name.strip());self.change_profile()
        except (OSError,ValueError) as error:messagebox.showerror('Could not create profile',str(error))

    def test_mouse(self):
        """Run the no-click mouse test in a separate Python process.

        A bad native Win32 call can terminate a process without raising a normal
        Python exception. Keeping the probe out-of-process lets the GUI survive
        that failure and report the helper exit code/log to the user.
        """
        if self.activity:return
        if len(self.corners)!=2 or self.target_window is None:
            self.status.set('Select the drawing area first.');return
        import json
        import subprocess
        import sys

        x,y,w,h=self.area()
        handle,rect=self.target_window
        try:handle_value=int(handle)
        except (TypeError,ValueError):
            handle_value=getattr(handle,'value',None)
        if not handle_value:
            self.status.set('The target window handle is invalid. Select the drawing area again.');return

        log_event(f'Isolated mouse test requested. area={(x,y,w,h)} target={(handle_value,rect)!r}')
        self.root.iconify()

        def work():
            from RuntimePaths import helper_command
            command=helper_command(
                'mouse',
                '--handle', str(handle_value),
                '--rect', *map(str,rect),
                '--area', str(x),str(y),str(w),str(h),
            )
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            self.events.put(('status','Protected mouse test is running in a separate process. No clicks will be performed. Switch to the target application.'))
            started=time.monotonic()
            process=None
            output=''
            try:
                process=subprocess.Popen(
                    command,cwd=BASE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                    text=True,encoding='utf-8',errors='replace',creationflags=creationflags)
                self.mouse_probe_process=process
                interruption=None
                while True:
                    try:
                        output=process.communicate(timeout=.10)[0] or ''
                        break
                    except subprocess.TimeoutExpired:
                        if self.stop.is_set():interruption='Mouse test cancelled.'
                        elif time.monotonic()-started>35:interruption='The mouse test exceeded 35 seconds and was stopped.'
                        if interruption:
                            process.kill()
                            output=process.communicate(timeout=5)[0] or ''
                            break
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                        try:output=process.communicate(timeout=5)[0] or output
                        except subprocess.TimeoutExpired:pass
                    for stream in (process.stdout,process.stderr):
                        if stream is not None:stream.close()
                self.mouse_probe_process=None

            probe_log=BASE/'logs'/'ImageDrawBot-mouse-probe.log'
            try:
                probe_log.parent.mkdir(parents=True,exist_ok=True)
                probe_log.write_text(
                    f'Command: {command!r}\nExit: {process.returncode if process else "not-started"}\n\n{output}',
                    encoding='utf-8')
            except OSError:
                pass
            log_event(f'Isolated mouse probe exit={process.returncode if process else None}. Output={output!r}')

            if interruption:raise InterruptedError(interruption)

            messages=[]
            for line in output.splitlines():
                try:
                    payload=json.loads(line)
                    if isinstance(payload,dict):messages.append(payload)
                except (json.JSONDecodeError,TypeError):
                    continue
            error_text=next((m.get('value') for m in reversed(messages) if m.get('type')=='error'),None)
            result=next((m.get('value') for m in reversed(messages) if m.get('type')=='result'),None)
            code=process.returncode if process else -1
            if code!=0:
                unsigned=code & 0xffffffff
                code_text=f'{code} / 0x{unsigned:08X}'
                if unsigned==0xC0000005:
                    hint=' Windows reported 0xC0000005 (access violation/native crash). Enable crash dumps and run the test again.'
                else:
                    hint=''
                raise RuntimeError(f'{error_text or "The isolated mouse process exited unexpectedly."} Exit code: {code_text}.{hint} Log: {probe_log.name}')
            if not isinstance(result,dict) or not result.get('ok'):
                raise RuntimeError(f'The mouse test returned no valid result. See {probe_log.name}.')
            positions=result.get('positions') or []
            log_event(f'Isolated mouse test success. positions={positions!r} diagnostics={result.get("diagnostics")!r}')
            self.events.put(('status','Protected mouse test completed: the pointer moved without clicking. Next step: Draw a small test.'))

        try:
            if not self.begin_worker('mouse-test',work):self.root.deiconify()
        except Exception as error:
            self.root.deiconify()
            log_event(f'Mouse test could not start: {error!r}')
            self.status.set(f'Mouse test could not start: {error}')

    def paint_mode_changed(self):
        if uses_paint_color(self) and self.game.get()!='Microsoft Paint':
            self.outline.set(True)
            self.subject_focus.set('Off')
            self.brush_px.set('1')
            self.status.set('Single-color sketch: select black and a thin pencil in the game. No palette calibration is required.')
        self._schedule_paint_configuration_refresh()

    def paint_tool_changed(self,*args):
        self._schedule_paint_configuration_refresh()

    def _schedule_paint_configuration_refresh(self):
        # CTk callbacks can run while the widget is still drawing itself. Queue
        # palette/preview changes instead of mutating layout/state synchronously.
        if self.activity or self.closing:return
        if self.paint_config_after is not None:
            try:self.root.after_cancel(self.paint_config_after)
            except (tk.TclError,ValueError):pass
        try:self.paint_config_after=self.root.after_idle(self._apply_paint_configuration_refresh)
        except tk.TclError:self.paint_config_after=None

    def _apply_paint_configuration_refresh(self):
        self.paint_config_after=None
        if self.activity or self.closing:return
        self.refresh_palette();self.set_busy(None);self.plan=None;self.small_test_passed=False;self.options_changed()

    def _browser_one_click_supported(self):
        try:
            from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
            return PROFILES.get(self.game.get(),('',))[0] in SUPPORTED_BROWSER_PROFILES and self.game.get()!='Microsoft Paint'
        except Exception:
            return False

    def _browser_one_click_active(self):
        try:return bool(self.browser_one_click_enabled.get()) and DrawBotApp._browser_one_click_supported(self)
        except Exception:return False

    def _browser_one_click_authorized(self):
        """Persistent switch OR one-shot game-canvas drop authorization."""
        try:
            return DrawBotApp._browser_one_click_supported(self) and (
                DrawBotApp._browser_one_click_active(self) or bool(getattr(self,'browser_one_click_force',False)))
        except Exception:return False

    def _cancel_browser_one_click(self, reason='', *, request=None):
        """Revoke an owned deferred start, even if another worker clears Stop."""
        current=getattr(self,'browser_one_click_request',None)
        if request is not None and current is not request:return False
        if isinstance(current,dict):
            current['cancelled'].set()
            pending=getattr(self,'one_click_setup_verify_pending',None)
            if isinstance(pending,dict) and pending.get('_browser_request') is current:
                DrawBotApp._cancel_after_attr(self,'one_click_setup_after')
                self.one_click_setup_verify_pending=None
                self.one_click_setup_verify_payload=None
        had_request=current is not None or bool(getattr(self,'browser_one_click_pending',False))
        self.browser_one_click_request=None
        self.browser_one_click_pending=False
        self.browser_one_click_force=False
        self.browser_one_click_after_ticket=None
        DrawBotApp._cancel_after_attr(self,'browser_one_click_after')
        if had_request and reason:log_event(f'Browser One-Click request revoked: {reason}.')
        return had_request

    def _new_browser_one_click_request(self, *, force=False, auto_start=True):
        DrawBotApp._cancel_browser_one_click(self,'replaced by a new request')
        profile_name=self.game.get()
        request={
            'image':self.original, 'profile_name':profile_name,
            'profile_key':PROFILES.get(profile_name,('',))[0],
            'force':bool(force), 'auto_start':bool(auto_start),
            'cancelled':threading.Event(), 'phase':'queued' if auto_start else 'setup',
        }
        self.browser_one_click_request=request
        self.browser_one_click_force=bool(force)
        return request

    def _browser_one_click_request_current(self, request):
        """UI-thread identity check; workers use only the captured cancel event."""
        if not isinstance(request,dict) or request is not getattr(self,'browser_one_click_request',None):return False
        if request['cancelled'].is_set() or getattr(self,'closing',False):return False
        stop=getattr(self,'stop',None)
        if stop is not None and stop.is_set():return False
        if (getattr(self,'pending_clear_drawing',None) is not None or
                getattr(self,'profile_change_after',None) is not None or
                getattr(self,'profile_change_in_progress',False)):return False
        if self.original is not request['image']:return False
        profile_name=self.game.get()
        if (profile_name!=request['profile_name'] or
                PROFILES.get(profile_name,('',))[0]!=request['profile_key']):return False
        return not request['auto_start'] or request['force'] or DrawBotApp._browser_one_click_active(self)

    def _schedule_browser_one_click(self, request, *, finish=False, delay=40):
        if not DrawBotApp._browser_one_click_request_current(self,request):
            DrawBotApp._cancel_browser_one_click(self,'request context changed',request=request)
            return False
        DrawBotApp._cancel_after_attr(self,'browser_one_click_after')
        ticket=object();self.browser_one_click_after_ticket=ticket
        def run():
            # after_cancel can race with an already dispatched callback. An old
            # callback must neither start nor clear a newer request's Tk token.
            if getattr(self,'browser_one_click_after_ticket',None) is not ticket:return False
            self.browser_one_click_after=None;self.browser_one_click_after_ticket=None
            callback=DrawBotApp._finish_browser_one_click if finish else DrawBotApp._run_browser_one_click
            return callback(self,request)
        try:self.browser_one_click_after=self.root.after(delay,run)
        except (tk.TclError,RuntimeError,AttributeError,ValueError):
            DrawBotApp._cancel_browser_one_click(self,'callback could not be scheduled',request=request)
            return False
        return True

    def _queue_browser_one_click_after_import(self, label='image', *, force=False):
        if self.original is None or not DrawBotApp._browser_one_click_supported(self):return False
        if not force and not DrawBotApp._browser_one_click_active(self):return False
        request=DrawBotApp._new_browser_one_click_request(self,force=force)
        self.browser_one_click_pending=True;self.browser_one_click_source_label=str(label)
        try:
            suffix=' · canvas-drop one-shot' if request['force'] else ''
            self.browser_one_click_text.set('One-Click queued'+suffix+' · waiting for image loader/setup to become idle…')
        except Exception:pass
        log_event(
            f'Browser One-Click queued after image import: profile={self.game.get()!r} label={label!r} '
            f'force={bool(getattr(self,"browser_one_click_force",False))}.')
        return DrawBotApp._schedule_browser_one_click(self,request)

    def _run_browser_one_click(self, request=None):
        if request is None:request=getattr(self,'browser_one_click_request',None)
        if not DrawBotApp._browser_one_click_request_current(self,request):
            DrawBotApp._cancel_browser_one_click(self,'request context changed',request=request)
            return False
        if request['phase']!='queued' or not request['auto_start']:return False
        if self.activity:
            return DrawBotApp._schedule_browser_one_click(self,request,delay=80)
        profile_name=request['profile_name'];profile_key=request['profile_key']
        try:drawing_region=DrawBotApp._browser_drawing_region(self)
        except ValueError as error:
            self.status.set(str(error))
            DrawBotApp._cancel_browser_one_click(self,'drawing region needs selection',request=request)
            return False
        if drawing_region is not None:
            drawing_region=drawing_region.without_verification()
            self.browser_drawing_region=drawing_region
        current_handle=(self.target_window[0] if getattr(self,'target_window',None) else None)
        palette_path=Path(self.calibration_path)
        self.browser_one_click_pending=False
        request['phase']='setup';self.browser_one_click_worker_request=request
        self.drop_in_sync_phase=DROP_SYNC_AUTO_SETUP
        self.browser_auto_calibration_success=False
        force=request['force']
        self.status.set('Canvas-drop verification: checking game window, canvas and palette…' if force else 'One-Click: finding/verifying the game window, canvas and palette…')
        try:self.browser_one_click_text.set(('Canvas-drop one-shot verification' if force else 'One-Click setup')+' running · read-only browser scan · no mouse input.')
        except Exception:pass
        def work():
            from BrowserOneClick import one_click_setup
            cancelled=lambda:request['cancelled'].is_set() or self.stop.is_set()
            if cancelled():raise InterruptedError('One-Click request cancelled.')
            payload=one_click_setup(profile_name,profile_key,palette_path,current_handle=current_handle,
                                    cancelled=cancelled,verify_canvas=drawing_region is not None)
            if cancelled():raise InterruptedError('One-Click request cancelled.')
            payload['_browser_drawing_region']=drawing_region
            payload['one_click_force']=force
            payload['_browser_request']=request
            self.events.put(('browser_one_click_setup_complete',payload))
        try:started=bool(self.begin_worker('browser-one-click-setup',work))
        except Exception:
            self.browser_one_click_worker_request=None
            DrawBotApp._cancel_browser_one_click(self,'worker could not start',request=request)
            raise
        if not started:
            self.browser_one_click_worker_request=None
            DrawBotApp._cancel_browser_one_click(self,'worker refused the request',request=request)
        return started

    def _finish_browser_one_click(self, request=None):
        if request is None:request=getattr(self,'browser_one_click_request',None)
        if not DrawBotApp._browser_one_click_request_current(self,request) or self.activity:
            DrawBotApp._cancel_browser_one_click(self,'start context changed',request=request)
            return False
        if request['phase']!='finish' or not request['auto_start']:return False
        force=request['force']
        ready,message=DrawBotApp._start_guard_ready(self,require_image=True)
        if not ready:
            self.status.set('Canvas drop blocked safely: '+message.replace('Start locked: ','',1) if force else 'One-Click blocked safely: '+message.replace('Start locked: ','',1))
            try:self.browser_one_click_text.set(('Canvas drop blocked · ' if force else 'One-Click blocked · ')+message.replace('Start locked: ','',1))
            except Exception:pass
            DrawBotApp._cancel_browser_one_click(self,'preflight requirements changed',request=request)
            return False
        self.status.set('Canvas image verified. Building the drawing plan and starting…' if force else 'One-Click setup ready. Running visual preflight and starting drawing…')
        log_event(('Game Canvas Drop one-shot setup ready' if force else 'Browser One-Click setup ready')+'; entering normal draw preflight. CanvasGuard remains mandatory.')
        # Consume the one-shot authorization before native input begins. draw()
        # still performs Auto-Recalibration, Browser Visual Preflight and brush
        # checks before arming any mouse input.
        DrawBotApp._cancel_browser_one_click(self,'start authorization consumed',request=request)
        return DrawBotApp.draw(self,user_initiated=True)

    def auto_calibrate_browser_profile(self, *, automatic=False):
        """Read-only one-click palette/canvas setup for supported browser games.

        The already selected target window is activated for a short screenshot,
        but no mouse move/click/press/release is generated. Manual capture remains
        available only as a fallback when the visual layout cannot be verified.
        """
        if self.activity or self.closing:
            return False
        profile_name=self.game.get()
        profile_key=PROFILES.get(profile_name,('',))[0]
        try:
            from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
        except Exception as error:
            self.status.set(f'Browser Auto Setup is unavailable: {error}')
            return False
        if profile_key not in SUPPORTED_BROWSER_PROFILES:
            if not automatic:self.status.set('Browser Auto Setup is available for Gartic Phone, Skribbl.io/Fast, SketchHeads and Sketchful.io.')
            return False
        target=getattr(self,'target_window',None)
        if not target:
            if not automatic:self.status.set('Select/confirm the target canvas once. Image Draw Bot will auto-detect the palette immediately afterwards.')
            return False
        try:drawing_region=DrawBotApp._browser_drawing_region(self)
        except ValueError as error:
            self.status.set(str(error));return False
        if drawing_region is not None:
            drawing_region=drawing_region.without_verification()
            self.browser_drawing_region=drawing_region
        # begin_worker owns the busy state. Setting it before begin_worker used to
        # make the worker reject itself as already busy.
        self.stop.clear();self.drop_in_sync_phase=DROP_SYNC_AUTO_SETUP
        self.browser_auto_calibration_success=False
        self.browser_auto_text.set('Auto setup: scanning the selected browser window… no mouse input.')
        log_event(f'Browser Auto Setup started: profile={profile_name!r} key={profile_key!r}. Mouse input remains DISARMED.')
        palette_path=Path(self.calibration_path)
        handle=int(target[0]);expected_rect=tuple(target[1])
        def work():
            import time as _time
            from ScreenGuard import WindowMonitor
            from TargetCapture import probe_handle_isolated
            from BrowserAutoCalibration import auto_calibrate_browser
            from LayoutFingerprintV2 import try_restore, record_from_calibration_file
            monitor=WindowMonitor()
            current_rect=monitor.rectangle(handle)
            if current_rect!=expected_rect:
                raise InterruptedError('Target browser moved or changed size before automatic calibration. Select the canvas again.')
            if not monitor.activate((handle,expected_rect)):
                raise InterruptedError('Windows could not activate the selected browser for automatic calibration.')
            if self.stop.wait(.20):raise InterruptedError()
            meta=probe_handle_isolated(handle,cancelled=self.stop.is_set)
            # v1.0.76: try a previously verified layout first. One screenshot is
            # shared by the cache verifier and the full detector on cache miss.
            from ScreenGuard import _grab_rgb
            with closing(_grab_rgb(tuple(meta['client_rect']))) as screenshot:
                cached=try_restore(profile_key,meta,palette_path,screenshot=screenshot,cancelled=self.stop.is_set)
                if cached.hit:
                    payload=cached.as_dict()
                    payload.update({
                        'palette_confidence':cached.confidence, 'canvas_confidence':max(.90,cached.confidence),
                        'method':'Layout Fingerprint v2 cache',
                        'note':'Verified local layout fingerprint restored without full palette detection.',
                        'target_meta':meta, 'profile_name':profile_name,
                        'layout_fingerprint_meta':cached.as_dict(),
                        '_browser_drawing_region':drawing_region,
                    })
                    if drawing_region is not None:
                        from BrowserAutoCalibration import detect_browser_canvas
                        live=detect_browser_canvas(profile_key,screenshot,screen_origin=tuple(meta['client_rect'])[:2],cancelled=self.stop.is_set)
                        payload.update(canvas_box=live['canvas_box'],canvas_confidence=live['canvas_confidence'])
                    self.events.put(('browser_auto_calibration_complete',payload))
                    return
                result=auto_calibrate_browser(profile_key,meta,palette_path,screenshot=screenshot,cancelled=self.stop.is_set)
                try:
                    fingerprint=record_from_calibration_file(profile_key,meta,result.canvas_box,palette_path,method=result.method) if result.canvas_box else None
                except Exception as error:
                    fingerprint={'saved':False,'reason':str(error)}
                payload=result.as_dict();payload['target_meta']=meta;payload['profile_name']=profile_name
                payload['layout_fingerprint_meta']=fingerprint
                payload['_browser_drawing_region']=drawing_region
                self.events.put(('browser_auto_calibration_complete',payload))
        started=self.begin_worker('browser-auto-calibration',work)
        if not started and self.drop_in_sync_phase==DROP_SYNC_AUTO_SETUP:
            self.drop_in_sync_phase=DROP_SYNC_IDLE
        return started

    def run_one_click_setup_verify(self):
        """Step 27.5: setup + independent live verification without drawing."""
        if self.activity or self.closing:return False
        from OneClickSetupVerification import setup_mode
        profile_name=self.game.get();profile_key=PROFILES.get(profile_name,('',))[0]
        mode=setup_mode(profile_key)
        if mode=='manual':
            self.one_click_setup_text.set('One-click Setup is unavailable for this target. Use the existing manual canvas/palette calibration controls.')
            self.status.set('This target does not have a verified One-click Setup detector. Manual calibration remains available.')
            return False
        DrawBotApp._cancel_browser_one_click(self,'read-only Setup + Verify selected')
        mouse=getattr(self,'mouse',None)
        if hasattr(mouse,'disarm_input'):
            try:mouse.disarm_input()
            except (OSError,RuntimeError):pass
        DrawBotApp._disarm_manual_drop_in(self,'Step 27.5 One-click Setup')
        DrawBotApp._disarm_full_draw(self,'Step 27.5 One-click Setup',update_text=True)
        DrawBotApp._cancel_after_attr(self,'one_click_setup_after')
        self.one_click_setup_verify_pending={'profile_name':profile_name,'profile_key':profile_key,'mode':mode}
        self.one_click_setup_verify_payload=None
        self.one_click_setup_text.set('One-click Setup running · read-only target/canvas/palette scan · no drawing input.')
        self.status.set(f'One-click Setup: preparing {profile_name}… No mouse or keyboard input will be sent.')
        if mode=='paint':
            started=bool(self.auto_calibrate_paint_tools(one_click_verify=True))
            if not started:self.one_click_setup_verify_pending=None
            return started
        try:drawing_region=DrawBotApp._browser_drawing_region(self)
        except ValueError as error:
            self.one_click_setup_verify_pending=None
            self.status.set(str(error));return False
        if drawing_region is not None:
            drawing_region=drawing_region.without_verification()
            self.browser_drawing_region=drawing_region
        current_handle=(self.target_window[0] if getattr(self,'target_window',None) else None)
        palette_path=Path(self.calibration_path)
        request=DrawBotApp._new_browser_one_click_request(self,auto_start=False)
        self.one_click_setup_verify_pending['_browser_request']=request
        self.browser_one_click_worker_request=request
        def work():
            try:
                from BrowserOneClick import one_click_setup
                cancelled=lambda:request['cancelled'].is_set() or self.stop.is_set()
                if cancelled():raise InterruptedError('One-click Setup cancelled.')
                payload=one_click_setup(profile_name,profile_key,palette_path,current_handle=current_handle,
                                        cancelled=cancelled,verify_canvas=drawing_region is not None)
                payload['_browser_drawing_region']=drawing_region
                if cancelled():raise InterruptedError('One-click Setup cancelled.')
                payload['one_click_setup_verify_only']=True
                payload['_browser_request']=request
                self.events.put(('browser_one_click_setup_complete',payload))
            except InterruptedError:raise
            except Exception as error:
                self.events.put(('one_click_setup_verification_complete',{
                    'passed':False,'profile_key':profile_key,'mode':'browser','confidence':0.0,
                    'canvas_ok':False,'palette_ok':False,'palette_verified':0,'palette_tested':0,
                    'tool_ok':False,'reasons':[str(error)],'error':str(error),'profile_name':profile_name,
                    '_browser_request':request,'_browser_drawing_region':drawing_region,
                }))
        try:started=bool(self.begin_worker('browser-one-click-setup',work))
        except Exception:
            self.browser_one_click_worker_request=None
            DrawBotApp._cancel_browser_one_click(self,'verification worker could not start',request=request)
            raise
        if not started:
            self.browser_one_click_worker_request=None
            DrawBotApp._cancel_browser_one_click(self,'verification worker refused the request',request=request)
        return started

    def _queue_one_click_setup_verification(self, setup_payload):
        pending=getattr(self,'one_click_setup_verify_pending',None)
        if not isinstance(pending,dict):return False
        request=pending.get('_browser_request')
        if request is not None and not DrawBotApp._browser_one_click_request_current(self,request):
            DrawBotApp._cancel_browser_one_click(self,'verification context changed',request=request)
            return False
        if pending.get('profile_name')!=self.game.get():
            self.one_click_setup_verify_pending=None;self.one_click_setup_verify_payload=None
            return False
        self.one_click_setup_verify_payload=dict(setup_payload or {})
        DrawBotApp._cancel_after_attr(self,'one_click_setup_after')
        try:self.one_click_setup_after=self.root.after(80,lambda:DrawBotApp._start_one_click_setup_verification(self,pending))
        except (tk.TclError,RuntimeError):self.one_click_setup_after=None;return False
        self.one_click_setup_text.set('Initial setup found. Running an independent live canvas/palette verification pass…')
        return True

    def _start_one_click_setup_verification(self, pending=None):
        current=getattr(self,'one_click_setup_verify_pending',None)
        if pending is None:pending=current
        if pending is not current:return False
        self.one_click_setup_after=None
        payload=getattr(self,'one_click_setup_verify_payload',None)
        if not isinstance(pending,dict) or not isinstance(payload,dict) or self.closing:return False
        request=pending.get('_browser_request')
        if request is not None and not DrawBotApp._browser_one_click_request_current(self,request):
            DrawBotApp._cancel_browser_one_click(self,'verification context changed',request=request)
            return False
        if pending.get('profile_name')!=self.game.get():
            self.one_click_setup_verify_pending=None;self.one_click_setup_verify_payload=None
            return False
        if self.activity:
            try:self.one_click_setup_after=self.root.after(80,lambda:DrawBotApp._start_one_click_setup_verification(self,pending))
            except (tk.TclError,RuntimeError):self.one_click_setup_after=None
            return True
        profile_name=str(pending['profile_name']);profile_key=str(pending['profile_key']);mode=str(pending['mode'])
        drawing_region=payload.get('_browser_drawing_region') if mode=='browser' else None
        if mode=='browser' and drawing_region is not getattr(self,'browser_drawing_region',None):
            DrawBotApp._cancel_browser_one_click(self,'verification drawing region changed',request=request)
            return False
        meta=dict(payload.get('target_meta') or {});canvas=payload.get('canvas_box')
        if not meta.get('handle') or not meta.get('rect') or not meta.get('client_rect') or not isinstance(canvas,(list,tuple)) or len(canvas)!=4:
            self.events.put(('one_click_setup_verification_complete',{
                'passed':False,'profile_key':profile_key,'mode':mode,'confidence':0.0,'canvas_ok':False,
                'palette_ok':False,'palette_verified':0,'palette_tested':0,'tool_ok':False,
                'reasons':['setup did not return complete target/canvas metadata'],'profile_name':profile_name,
                '_browser_request':request,'_browser_drawing_region':drawing_region,
            }))
            return False
        palette_path=Path(self.calibration_path)
        if request is not None:request['phase']='verifying'
        def work():
            try:
                cancelled=lambda:self.stop.is_set() or (request is not None and request['cancelled'].is_set())
                if cancelled():raise InterruptedError('One-click Setup verification cancelled.')
                from ScreenGuard import WindowMonitor, _grab_rgb
                monitor=WindowMonitor();handle=int(meta['handle']);target=(handle,tuple(meta['rect']))
                if not monitor.activate(target):raise ValueError('Windows could not activate the verified target for the second read-only check.')
                if self.stop.wait(.18) or cancelled():raise InterruptedError('One-click Setup verification cancelled.')
                current_rect=tuple(monitor.rectangle(handle));client=tuple(monitor.client_rectangle(handle));dpi=monitor.dpi(handle)
                live_meta=dict(meta);live_meta.update({'handle':handle,'rect':current_rect,'client_rect':client,'dpi':dpi})
                from OneClickSetupVerification import verify_browser_live,verify_paint_live
                with closing(_grab_rgb(client)) as shot:
                    if cancelled():raise InterruptedError('One-click Setup verification cancelled.')
                    result=(verify_browser_live(profile_key,live_meta,canvas,palette_path,screenshot=shot,drawing_region=drawing_region)
                            if mode=='browser' else verify_paint_live(live_meta,canvas,palette_path,screenshot=shot))
                if cancelled():raise InterruptedError('One-click Setup verification cancelled.')
                out=result.as_dict();out['profile_name']=profile_name;out['target_meta']=live_meta
                out['_browser_request']=request;out['_browser_drawing_region']=drawing_region
                self.events.put(('one_click_setup_verification_complete',out))
            except InterruptedError:raise
            except Exception as error:
                self.events.put(('one_click_setup_verification_complete',{
                    'passed':False,'profile_key':profile_key,'mode':mode,'confidence':0.0,'canvas_ok':False,
                    'palette_ok':False,'palette_verified':0,'palette_tested':0,'tool_ok':False,
                    'reasons':[str(error)],'error':str(error),'profile_name':profile_name,
                    '_browser_request':request,'_browser_drawing_region':drawing_region,
                }))
        return bool(self.begin_worker('one-click-verify',work))

    def auto_calibrate_paint_tools(self, *, one_click_verify=False, start_after=False):
        """Prepare Paint and calibrate its palette/RGB controls before drawing."""
        if self.activity:return False
        if self.game.get()!='Microsoft Paint':
            self.status.set('Automatic Paint calibration is available only for the Microsoft Paint profile.');return False
        palette_path=Path(self.calibration_path)
        request={'image':self.original} if start_after else None
        self.paint_start_request=request
        # Snapshot the render policy on the UI thread. Tk variables must not be
        # read from the worker. Black contour sketch, Single-color sketch/current
        # ink and Eraser do not need exact RGB and must never open Edit colors.
        try:
            _black_contour_sketch=bool(self.outline.get())
        except Exception:
            _black_contour_sketch=False
        _skip_exact_rgb=bool(bypasses_palette(self) or _black_contour_sketch)
        _paint_brush_meta=None
        try:
            _paint_brush_raw=str(getattr(getattr(self,'brush_px',None),'get',lambda:'1')()).strip()
            if _paint_brush_raw.casefold()=='auto':
                from AutoBrushWidth import resolve_brush_width
                _target_size=None
                try:
                    if len(self.corners)==2:
                        _area=self.area();_target_size=(int(_area[2]),int(_area[3]))
                except Exception:
                    _target_size=None
                _decision=resolve_brush_width(
                    self.original,target_size=_target_size,
                    draw_quality=getattr(getattr(self,'draw_quality',None),'get',lambda:'High likeness')(),
                    render_preset=getattr(getattr(self,'render_preset',None),'get',lambda:'Auto')(),
                    render_style=getattr(getattr(self,'render_style',None),'get',lambda:'Auto')(),
                    outline=_black_contour_sketch,
                    subject_focus=getattr(getattr(self,'subject_focus',None),'get',lambda:'Off')(),
                    profile_key='microsoft-paint',speed=normalize_speed(self.speed.get()),quality=self.quality.get())
                _paint_brush_px=int(_decision.brush_px);_paint_brush_meta=_decision.as_dict()
            else:
                _paint_brush_px=int(_paint_brush_raw)
                if not 1<=_paint_brush_px<=50:raise ValueError('out of range')
        except (TypeError,ValueError,tk.TclError):
            self.paint_start_request=None
            self.status.set('Brush width must be Auto or 1–50 px before Paint preparation can start.')
            return False
        # Snapshot an explicit user-selected canvas on the UI thread. Paint's
        # pale document border can be visually ambiguous, but a manual selection
        # is already the user's hard CanvasGuard boundary and should not be
        # discarded by a later automatic border guess.
        selected_canvas_state=None
        try:
            if len(self.corners)==2 and self.target_window is not None and self.target_client_rect is not None:
                selected_canvas_state={
                    'handle':int(self.target_window[0]),
                    'client_rect':tuple(map(int,self.target_client_rect)),
                    'corners':tuple(tuple(map(int,p)) for p in self.corners),
                }
        except (TypeError,ValueError,OverflowError):
            selected_canvas_state=None
        def work():
            try:
                from TargetCapture import probe_handle_isolated
                from PaintFullCalibration import choose_paint_window,detect_setup,save_setup,resolve_manual_canvas_override
                from BrowserOneClick import _enumerate_windows
                from ScreenGuard import WindowMonitor
                from PIL import ImageGrab
                from PaintPreparation import ensure_paint,prepare_tool_controls,calibrate_rgb_controls
                candidate=ensure_paint(_enumerate_windows,cancelled=self.stop.is_set,wait=self.stop.wait)
                target=(int(candidate['handle']),tuple(candidate['rect']))
                monitor=WindowMonitor()
                if not monitor.activate(target):
                    raise ValueError('Could not activate Paint. Bring it into view and retry.')
                if self.stop.wait(.35):raise InterruptedError()
                meta=probe_handle_isolated(int(candidate['handle']),cancelled=self.stop.is_set)
                prepare_tool_controls(int(candidate['handle']),brush_px=_paint_brush_px,cancelled=self.stop.is_set)
                exact_controls=None
                exact_reused=False
                if not _skip_exact_rgb:
                    # Do not reopen Edit colors on every Paint start. A valid
                    # profile-scoped numeric calibration is resolved against the
                    # current client geometry and reused. Only first-time/stale
                    # setups need to open the dialog.
                    try:
                        from ExactColorTools import numeric_rgb_available,resolved_controls
                        if numeric_rgb_available('microsoft-paint'):
                            exact_controls=resolved_controls('microsoft-paint',tuple(meta['client_rect']))
                            required=('OpenCustomColor','ConfirmColor','RedField','GreenField','BlueField')
                            if not all(name in exact_controls for name in required):
                                exact_controls=None
                            else:
                                exact_reused=True
                    except (OSError,ValueError,TypeError):
                        exact_controls=None
                    if exact_controls is None:
                        exact_controls=calibrate_rgb_controls(int(candidate['handle']),cancelled=self.stop.is_set)
                        if not monitor.activate(target):
                            raise ValueError('Paint Edit colors closed, but Paint could not be reactivated. Bring Paint into view and retry.')
                        if self.stop.wait(.15):raise InterruptedError()
                        meta=probe_handle_isolated(int(candidate['handle']),cancelled=self.stop.is_set)
                rect=tuple(meta['client_rect'])
                manual_canvas=None
                if selected_canvas_state is not None:
                    manual_canvas=resolve_manual_canvas_override(
                        selected_canvas_state['corners'],selected_canvas_state['handle'],
                        selected_canvas_state['client_rect'],int(candidate['handle']),rect)
                # Exact RGB controls are independent from canvas detection. Save
                # them as soon as Edit colors has been identified, so a clipped
                # Paint canvas can fall back to manual area selection without
                # losing working custom-color calibration.
                if exact_controls is not None and not exact_reused:
                    from ExactColorTools import save as save_exact_colors
                    from CalibrationAnchors import make_anchor
                    save_exact_colors('microsoft-paint',exact_controls,anchor=make_anchor(rect))
                with closing(ImageGrab.grab(bbox=rect,all_screens=True)) as shot:
                    if shot.size!=(rect[2]-rect[0],rect[3]-rect[1]):raise ValueError('Paint window changed size. Try again.')
                    result=detect_setup(shot,screen_origin=rect[:2],cancelled=self.stop.is_set,canvas_box_override=manual_canvas)
                if self.stop.is_set():raise InterruptedError()
                fresh=probe_handle_isolated(int(candidate['handle']),cancelled=self.stop.is_set)
                if tuple(fresh['client_rect'])!=rect:raise ValueError('Paint moved during calibration. Try again.')
                result=save_setup(result,meta,palette_path)
                result['manual_canvas_reused']=manual_canvas is not None
                result['exact_colors_ready']=bool(_skip_exact_rgb or exact_controls is not None)
                result['exact_colors_bypassed']=bool(_skip_exact_rgb)
                result['exact_colors_reused']=bool(exact_reused)
                result['prepared_brush_px']=int(_paint_brush_px)
                result['brush_px_requested']=_paint_brush_raw
                result['auto_brush_width_meta']=dict(_paint_brush_meta or {})
                result['start_request']=request
                self.events.put(('paint_auto_calibration_complete',result))
            except InterruptedError:
                self.paint_start_request=None
                raise
            except Exception as error:
                self.paint_start_request=None
                if one_click_verify:
                    self.events.put(('one_click_setup_verification_complete',{
                        'passed':False,'profile_key':'microsoft-paint','mode':'paint','confidence':0.0,
                        'canvas_ok':False,'palette_ok':False,'palette_verified':0,'palette_tested':0,
                        'tool_ok':False,'reasons':[str(error)],'error':str(error),'profile_name':'Microsoft Paint',
                    }))
                    return
                raise
        self.status.set(f'Preparing Paint: pencil, {_paint_brush_px} px, canvas, palette and RGB color controls…')
        started=bool(self.begin_worker('paint-auto-calibration',work))
        if not started:self.paint_start_request=None
        return started

    def _resume_prepared_paint(self,request):
        if (request is None or getattr(self,'paint_start_request',None) is not request
                or self.closing or self.stop.is_set() or not DrawBotApp._automatic_paint_preparation(self)
                or self.original is not request['image']):
            if getattr(self,'paint_start_request',None) is request:self.paint_start_request=None
            return False
        if self.activity:
            self.root.after(50,lambda:DrawBotApp._resume_prepared_paint(self,request))
            return False
        self.paint_start_request=None
        prepared=request.get('prepared_options')
        if prepared is not None:
            requested=getattr(getattr(self,'brush_px',None),'get',lambda:None)()
            if str(requested).casefold()!=str(prepared['brush_px_requested']).casefold():
                self.status.set('Paint brush settings changed after preparation. Press Start again to prepare the new width.')
                return False
            return DrawBotApp.draw(self,user_initiated=True,paint_prepared=True,paint_prepared_options=prepared)
        return DrawBotApp.draw(self,user_initiated=True,paint_prepared=True)


    def calibrate_paint_tools(self):
        if not DrawBotApp._profile_action_ready(self):return
        if self.game.get()!='Microsoft Paint':
            self.status.set('Paint tool calibration is available only for the Microsoft Paint profile.');return
        from PaintToolCalibration import PaintToolCalibrationApp
        import customtkinter as ctk
        from UiCompatibility import scoped_toplevel
        from ScreenTaskWindow import ScreenTaskWindow
        window=visibility=None
        def closed():
            try:self.refresh_tool_calibration()
            finally:
                try:self.set_busy(None)
                finally:
                    self.activity=None
                    if visibility is not None:visibility.restore()
            self.status.set('Paint tool calibration closed.')
        try:
            self.set_busy('tool-calibration')
            window=scoped_toplevel(self.root)
            self.paint_tool_window=window
            visibility=ScreenTaskWindow(self.root)
            visibility.hide()
            PaintToolCalibrationApp(window,on_close=closed)
        except Exception:
            try:
                if window is not None:window.destroy()
            except Exception as error:
                log_error(f'Paint tool dialog cleanup failed: {error!r}',category='calibration',exc_info=True)
            try:self.set_busy(None)
            except Exception as error:
                log_error(f'Paint tool dialog UI reset failed: {error!r}',category='calibration',exc_info=True)
            finally:
                self.activity=None
                if visibility is not None:visibility.restore()
            raise

    def calibrate_app_tools(self):
        if not DrawBotApp._profile_action_ready(self):return
        if self.game.get()=='Microsoft Paint':
            self.status.set('Use Calibrate Paint tools for Microsoft Paint.');return
        from AppToolCalibration import AppToolCalibrationApp
        import customtkinter as ctk
        from UiCompatibility import scoped_toplevel
        profile_key=PROFILES[self.game.get()][0]
        from ScreenTaskWindow import ScreenTaskWindow
        window=visibility=None
        def closed():
            try:self.refresh_app_tool_calibration()
            finally:
                try:self.set_busy(None)
                finally:
                    self.activity=None
                    if visibility is not None:visibility.restore()
            self.status.set('Application tool calibration closed.')
        try:
            self.set_busy('tool-calibration')
            window=scoped_toplevel(self.root)
            self.app_tool_window=window
            visibility=ScreenTaskWindow(self.root)
            visibility.hide()
            AppToolCalibrationApp(window,profile_key,self.game.get(),on_close=closed)
        except Exception:
            try:
                if window is not None:window.destroy()
            except Exception as error:
                log_error(f'Application tool dialog cleanup failed: {error!r}',category='calibration',exc_info=True)
            try:self.set_busy(None)
            except Exception as error:
                log_error(f'Application tool dialog UI reset failed: {error!r}',category='calibration',exc_info=True)
            finally:
                self.activity=None
                if visibility is not None:visibility.restore()
            raise

    def refresh_app_tool_calibration(self):
        if not hasattr(self,'app_tool_text'):return
        if self.game.get()=='Microsoft Paint':
            self.app_tool_text.set('Paint Fill is captured in Calibrate Paint tools. Automatic canvas clear uses Paint Select All/Delete and needs no extra calibration.')
            DrawBotApp.refresh_canvas_clear_status(self)
            return
        try:
            from AppTools import load_calibration, capability
            key=PROFILES[self.game.get()][0]
            try:
                from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
            except Exception:
                SUPPORTED_BROWSER_PROFILES=frozenset()
            if key in SUPPORTED_BROWSER_PROFILES:
                try:
                    data=load_calibration(key);tools=data.get('tools',{})
                    saved=[name for name in ('Brush','Fill','Eraser','Clear') if name in tools]
                except (OSError,ValueError,TypeError):
                    saved=[]
                extra=(' Calibrated: '+', '.join(saved)+'.') if saved else ''
                self.app_tool_text.set('✓ Normal browser drawing needs no manual tool calibration. Clear/Brush/Eraser capture is optional for automatic canvas clearing.'+extra)
                DrawBotApp.refresh_canvas_clear_status(self)
                return
            data=load_calibration(key);tools=data.get('tools',{})
            saved=[name for name in ('Brush','Fill','Eraser','Clear') if name in tools]
            cap=capability(key)
            if not saved:raise ValueError('No application tools captured.')
            ready='✓ Background Fill ready · ' if 'Brush' in tools and 'Fill' in tools else '✓ '
            self.app_tool_text.set(ready+', '.join(saved)+'. '+cap.get('note',''))
        except (OSError,ValueError,TypeError):
            self.app_tool_text.set('Optional Brush/Fill/Eraser/Clear controls are not calibrated for this application.')
        DrawBotApp.refresh_canvas_clear_status(self)

    def refresh_canvas_clear_status(self):
        if not hasattr(self,'canvas_clear_text') or not hasattr(self,'auto_clear_canvas'):
            return
        if not bool(self.auto_clear_canvas.get()):
            self.canvas_clear_text.set('Auto clear is off. The existing canvas is left untouched before drawing.')
            return
        if self.game.get()=='Microsoft Paint':
            self.canvas_clear_text.set('Auto clear ON · Paint uses Select All → Delete → Esc before a full drawing. Small Test, Dry Run and resume never erase.')
            return
        try:
            from AppTools import load_calibration
            key=PROFILES[self.game.get()][0]
            tools=load_calibration(key).get('tools',{})
        except (OSError,ValueError,TypeError,KeyError):
            tools={}
        if tools.get('Clear') is not None:
            self.canvas_clear_text.set('Auto clear ON · uses your anchored Clear canvas button before a full drawing.')
        elif tools.get('Eraser') is not None and tools.get('Brush') is not None:
            self.canvas_clear_text.set('Auto clear ON · no Clear button saved, so Image Draw Bot will use a CanvasGuard-bounded Eraser sweep and restore Brush.')
        else:
            self.canvas_clear_text.set('Auto clear ON · calibrate Clear canvas, or both Brush + Eraser, before full drawing.')

    def canvas_clear_changed(self):
        DrawBotApp.refresh_canvas_clear_status(self)
        self.options_changed()

    def change_profile(self,event=None):
        if self.closing:return
        if self.activity or getattr(self,'profile_change_in_progress',False):
            if not getattr(self,'profile_change_in_progress',False):
                self.game.set(getattr(self,'_active_profile_name','Other drawing app'))
            return
        selected=self.game.get()
        if selected==getattr(self,'_active_profile_name',None):
            DrawBotApp._cancel_after_attr(self,'profile_change_after')
            self.profile_change_ticket=None
            return
        if selected not in PROFILES:
            self.game.set(getattr(self,'_active_profile_name','Other drawing app'))
            self.status.set('Unknown drawing application profile.')
            return
        if self.save_settings() is False:
            self.game.set(getattr(self,'_active_profile_name','Other drawing app'))
            DrawBotApp._cancel_after_attr(self,'profile_change_after')
            self.status.set('Profile change stopped because the current settings could not be saved.')
            return
        DrawBotApp._cancel_browser_one_click(self,'profile changed')
        DrawBotApp._disarm_manual_drop_in(self,'profile changed')
        DrawBotApp._clear_render_resume(self,'profile changed by user')
        # Profile changes are configuration-only. Explicitly lock native input
        # before doing anything else, even though this path contains no move/click.
        mouse=getattr(self,'mouse',None)
        if hasattr(mouse,'disarm_input'):
            try:mouse.disarm_input()
            except OSError:pass
        if self.profile_change_after is not None:
            try:self.root.after_cancel(self.profile_change_after)
            except (tk.TclError,ValueError):pass
        ticket=object();self.profile_change_ticket=ticket
        try:self.profile_change_after=self.root.after_idle(lambda value=selected:self._apply_profile_change(value,ticket=ticket))
        except tk.TclError:
            self.profile_change_after=None;self.profile_change_ticket=None
            self.game.set(getattr(self,'_active_profile_name','Other drawing app'))

    def _apply_profile_change(self,selected,*,ticket=None):
        if ticket is not None and getattr(self,'profile_change_ticket',None) is not ticket:return
        self.profile_change_after=None
        self.profile_change_ticket=None
        if self.closing:return
        if self.activity or self.profile_change_in_progress:
            if not self.profile_change_in_progress and selected==self.game.get():
                self.game.set(getattr(self,'_active_profile_name','Other drawing app'))
            return
        # Ignore a stale queued selection if the user changed the menu again.
        if selected != self.game.get() or selected not in PROFILES:
            return
        self.profile_change_in_progress=True
        try:
            DrawBotApp._close_smart_drop_overlay(self,'profile changed')
            DrawBotApp._cancel_browser_one_click(self,'profile applied')
            DrawBotApp._disarm_manual_drop_in(self,'profile applied')
            self.smart_drop_pending_payload=None
            self.smart_drop_generation=int(getattr(self,'smart_drop_generation',0))+1
            from ProfileIsolation import reset_settings
            reset_settings(self)
            self.picture_custom_palette_state=None
            key,accent,hint=PROFILES[selected]
            log_event(f'Applying drawing profile {selected!r}. Mouse input remains DISARMED.')
            self.calibration_path=profile_palette_file(key)
            self.settings_path=profile_settings_file(key)
            # A profile change is configuration only.  It must never capture a
            # target, activate another window, move the pointer or click.
            self.corners=[];self.saved_area=None;self.canvas_anchor_detection=None;self.target_window=None;self.target_client_rect=None;self.target_dpi=None;self.plan=None;self.small_test_passed=False;self.color_session_cache.clear()
            self.browser_drawing_region=None
            self.mode.set(SMART_PATH_MODE);self.shape_order.set('Fill first');self.shape_model.set('Auto');self.max_stroke_cap.set('Auto');self.progressive_rendering.set('Auto');self.planning_watchdog.set('Auto');self.time_budget_mode.set('Manual');self.adaptive_deadline_renderer.set(True);self.deadline_safety_reserve.set('Auto');self.target_stroke_count.set('Auto');self.target_stroke_custom.set('2500');self.render_style.set('Auto');self.draw_quality.set('High likeness');self.human_mode.set('Off');self.gpu_mode.set('Auto');self.gpu_vram.set('Auto');self.gpu_performance.set('High throughput');self.cpu_workers.set('Auto');self.cpu_engine.set('Auto');self.ram_budget.set('Auto');self.ram_custom_mb.set('4096');self.planning_resolution.set('High');self.profile_engine.set('Auto');self.edge_behavior.set('Auto');self.background_fill.set('Conservative');self.fill_engine.set('Auto');self.background_simplification.set('Balanced');self.color_grouping.set('Smart');self.color_workflow.set('Finish color first');self.stroke_optimizer.set('Auto');self.adaptive_detail.set('Auto');self.detail_zoom.set('Auto');self.quick_sketch_style.set('Balanced');self.quick_sketch_fill_preference.set('Safe Fill First');self.hybrid_mode.set('Auto Hybrid');self.color_rendering.set('Perceptual match');self.color_fidelity.set('Faithful');self.color_layers.set('Off');self.custom_color_workflow.set('Exact custom + palette fallback');self.exact_color_limit.set('Auto');self.preview_mode.set('Manual');self.auto_clear_canvas.set(False);self.tool_strategy.set('Auto');self.portrait_focus.set(True)
            self.quality.set('Balanced');self.speed.set('Balanced');self.precision.set('High')
            apply_profile_defaults(self,selected)
            # The Paint switch is always present in the layout; only its enabled
            # state changes.  This avoids a CTkScrollableFrame geometry loop.
            try:self.paint_check.configure(state='normal')
            except (tk.TclError,AttributeError):pass
            self.read_settings()
            # Profile-level saved settings from older builds may contain Auto preview.
            # Switching profile is a configuration action, so v1.0.16 forces Manual
            # after settings are loaded and cancels any queued preview worker.
            self.preview_mode.set('Manual')
            DrawBotApp._cancel_after_attr(self,'preview_after')
            self.refresh_palette();self.refresh_tool_calibration();self.refresh_app_tool_calibration();self.refresh_exact_color_status()
            self.area_text.set('Select the drawing area for the chosen application.')
            try:
                from AppTools import capability
                tool_note=capability(key).get('note','')
            except Exception:
                tool_note=''
            ui=profile_ui(selected)
            profile_tip=ui.get('tip','')
            self.profile_hint.set(hint + (f' {profile_tip}' if profile_tip else '') + (f' Tool model: {tool_note}' if tool_note else ''))
            self.root.title(f'Image Draw Bot · {selected}')
            self.status.set('Profile changed. Preview stayed Manual and mouse input is locked until you explicitly arm drawing.')
            self.set_busy(None)
            # Profile changes are never allowed to start preview planning. They only
            # invalidate the old plan and redraw the placeholder/original image.
            self._mark_plan_stale('Profile changed. Preview was not rebuilt. Press Build preview manually when ready.')
            self.show_previews();self._schedule_recovery_checkpoint(delay=300)
            self._active_profile_name=selected
        finally:
            self.profile_change_in_progress=False

    def read_settings(self):
        from RuntimePaths import read_json
        from SettingsValidation import validated_settings, settings_application
        from StabilityRC import UnsupportedSettingsSchema
        # A transient read failure must not revoke protection learned from a
        # newer schema. Only a verified supported document or confirmed removal
        # of this same path allows it to be replaced by the current writer.
        self._settings_protected_path=getattr(self,'_settings_protected_path',None)
        try:
            data=validated_settings(read_json(self.settings_path,max_bytes=256*1024,max_depth=16))
            with settings_application(self):
                DrawBotApp._apply_settings_data(self,data)
            self._loaded_profile_extras=data.get('profile_extras',{})
            if self._settings_protected_path==Path(self.settings_path):
                self._settings_protected_path=None
            return True
        except UnsupportedSettingsSchema as error:
            self._settings_protected_path=Path(self.settings_path)
            log_event(f'Settings preserved for {self.settings_path.name}: {error!r}')
            return False
        except FileNotFoundError as error:
            if self._settings_protected_path==Path(self.settings_path):
                self._settings_protected_path=None
            log_event(f'Settings unavailable for {self.settings_path.name}: {error!r}')
            return False
        except (OSError,ValueError,TypeError,AttributeError,OverflowError,RuntimeError,tk.TclError) as error:
            log_event(f'Settings ignored for {self.settings_path.name}: {error!r}')
            return False

    def _apply_settings_data(self,data):
        def _set(name,value):
            if name in data or name in ('human_mode','drop_mode'):
                getattr(self,name).set(value)
        quality = {'Snabb skiss':'Quick sketch','Balanserad':'Balanced','Hög detalj':'High detail','Max detalj':'Maximum detail'}.get(data.get('quality'), data.get('quality'))
        if quality in QUALITY:_set('quality',quality)
        try:
            speed=normalize_speed(data.get('speed','Balanced'))
            _set('speed',speed)
        except ValueError:
            pass
        precision=data.get('precision','High')
        if hasattr(self,'precision') and precision in ('Normal','High','Ultra'):_set('precision',precision)
        if data.get('mode') in DRAWING_MODES:_set('mode',data['mode'])
        elif data.get('mode') == 'Linjer (snabbast)': _set('mode','Lines (fastest)')
        elif data.get('mode') == 'Punkter': _set('mode','Dots')
        shape_order=data.get('shape_order','Fill first')
        if hasattr(self,'shape_order') and shape_order in SHAPE_ORDERS:_set('shape_order',shape_order)
        shape_model=data.get('shape_model','Auto')
        if hasattr(self,'shape_model') and shape_model in SHAPE_MODEL_MODES:_set('shape_model',shape_model)
        max_stroke_cap=data.get('max_stroke_cap','Auto')
        if hasattr(self,'max_stroke_cap') and max_stroke_cap in STROKE_CAPS:_set('max_stroke_cap',max_stroke_cap)
        progressive_rendering=data.get('progressive_rendering','Auto')
        if hasattr(self,'progressive_rendering') and progressive_rendering in PROGRESSIVE_RENDERING_MODES:_set('progressive_rendering',progressive_rendering)
        planning_watchdog=data.get('planning_watchdog','Auto')
        if hasattr(self,'planning_watchdog') and planning_watchdog in PLANNING_WATCHDOG_MODES:_set('planning_watchdog',planning_watchdog)
        time_budget_mode=data.get('time_budget_mode','Manual')
        if hasattr(self,'time_budget_mode') and time_budget_mode in TIME_BUDGET_MODES:_set('time_budget_mode',time_budget_mode)
        if hasattr(self,'adaptive_deadline_renderer') and type(data.get('adaptive_deadline_renderer')) is bool:
            _set('adaptive_deadline_renderer',data['adaptive_deadline_renderer'])
        reserve=str(data.get('deadline_safety_reserve','Auto'))
        if hasattr(self,'deadline_safety_reserve') and reserve in ('Auto','Off','3','5','7','8','10','12','15','20','25'):
            _set('deadline_safety_reserve',reserve)
        target_stroke_count=data.get('target_stroke_count','Auto')
        if hasattr(self,'target_stroke_count') and target_stroke_count in TARGET_STROKE_COUNTS:_set('target_stroke_count',target_stroke_count)
        if hasattr(self,'target_stroke_custom') and data.get('target_stroke_custom') is not None:
            try:_set('target_stroke_custom',str(parse_custom_stroke_count(data.get('target_stroke_custom'))))
            except ValueError:pass
        render_style=data.get('render_style','Auto')
        if hasattr(self,'render_style') and render_style in ('Auto','Portrait / shaded','Standard / pixel',QUICK_SKETCH_RENDER_STYLE,SKETCH_FILL_RENDER_STYLE,HYBRID_RENDER_STYLE):_set('render_style',render_style)
        draw_quality=data.get('draw_quality','High likeness')
        if hasattr(self,'draw_quality') and draw_quality in ('Balanced','High likeness','Maximum likeness','GPU enhanced','Pixel Accurate'):_set('draw_quality',draw_quality)
        human_mode='Off'  # Ignore humanization saved by earlier versions.
        if hasattr(self,'human_mode') and human_mode in HUMAN_MODES:_set('human_mode',human_mode)
        gpu_mode=data.get('gpu_mode','Auto')
        if hasattr(self,'gpu_mode') and gpu_mode in ACCELERATION_MODES:_set('gpu_mode',gpu_mode)
        gpu_vram=data.get('gpu_vram','Auto')
        if hasattr(self,'gpu_vram') and gpu_vram in VRAM_BUDGETS:_set('gpu_vram',gpu_vram)
        gpu_performance=data.get('gpu_performance','High throughput')
        if hasattr(self,'gpu_performance') and gpu_performance in GPU_PERFORMANCE_MODES:_set('gpu_performance',gpu_performance)
        cpu_workers=data.get('cpu_workers','Auto')
        if hasattr(self,'cpu_workers') and cpu_workers in CPU_WORKER_CHOICES:_set('cpu_workers',cpu_workers)
        cpu_engine=data.get('cpu_engine','Auto')
        if hasattr(self,'cpu_engine') and cpu_engine in CPU_ENGINE_MODES:_set('cpu_engine',cpu_engine)
        ram_budget=data.get('ram_budget','Auto')
        if hasattr(self,'ram_budget') and ram_budget in RAM_BUDGETS:_set('ram_budget',ram_budget)
        custom_ram=data.get('ram_custom_mb','4096')
        if hasattr(self,'ram_custom_mb'):
            try:_set('ram_custom_mb',str(parse_custom_ram_mb(custom_ram)))
            except ValueError:pass
        planning_resolution=data.get('planning_resolution','High')
        if hasattr(self,'planning_resolution') and planning_resolution in PLANNING_RESOLUTION_MODES:_set('planning_resolution',planning_resolution)
        resource_scheduler=data.get('resource_scheduler','Auto')
        if hasattr(self,'resource_scheduler') and resource_scheduler in RESOURCE_SCHEDULER_MODES:_set('resource_scheduler',resource_scheduler)
        profile_engine=data.get('profile_engine','Auto')
        if hasattr(self,'profile_engine') and profile_engine in PROFILE_ENGINE_MODES:_set('profile_engine',profile_engine)
        edge_behavior=data.get('edge_behavior','Auto')
        if hasattr(self,'edge_behavior') and edge_behavior in EDGE_BEHAVIOR_MODES:_set('edge_behavior',edge_behavior)
        background_fill=data.get('background_fill','Balanced')
        if background_fill=='Auto': background_fill='Balanced'
        if hasattr(self,'background_fill') and background_fill in ('Off','Conservative','Balanced','Aggressive'):_set('background_fill',background_fill)
        fill_engine=data.get('fill_engine','Auto')
        if hasattr(self,'fill_engine') and fill_engine in FILL_ENGINES:_set('fill_engine',fill_engine)
        if hasattr(self,'use_region_fill_engine') and type(data.get('use_region_fill_engine')) is bool:
            _set('use_region_fill_engine',data['use_region_fill_engine'])
        fill_aggressiveness=data.get('fill_aggressiveness','Balanced')
        if hasattr(self,'fill_aggressiveness') and fill_aggressiveness in ('Safe','Balanced','Aggressive'):
            _set('fill_aggressiveness',fill_aggressiveness)
        background_simplification=data.get('background_simplification','Balanced')
        if hasattr(self,'background_simplification') and background_simplification in ('Off','Conservative','Balanced','Strong'):_set('background_simplification',background_simplification)
        color_grouping=data.get('color_grouping','Smart')
        if hasattr(self,'color_grouping') and color_grouping in COLOR_GROUPING_MODES:_set('color_grouping',color_grouping)
        color_workflow=data.get('color_workflow','Finish color first')
        if hasattr(self,'color_workflow') and color_workflow in COLOR_WORKFLOWS:_set('color_workflow',color_workflow)
        stroke_optimizer=data.get('stroke_optimizer','Auto')
        if hasattr(self,'stroke_optimizer') and stroke_optimizer in STROKE_OPTIMIZER_MODES:_set('stroke_optimizer',stroke_optimizer)
        adaptive_detail=data.get('adaptive_detail','Auto')
        if hasattr(self,'adaptive_detail') and adaptive_detail in ADAPTIVE_DETAIL_MODES:_set('adaptive_detail',adaptive_detail)
        detail_zoom=data.get('detail_zoom','Auto')
        if hasattr(self,'detail_zoom') and detail_zoom in ('Auto','Off','2x','4x'):_set('detail_zoom',detail_zoom)
        quick_sketch_style=data.get('quick_sketch_style','Balanced')
        if hasattr(self,'quick_sketch_style') and quick_sketch_style in QUICK_SKETCH_STYLES:_set('quick_sketch_style',quick_sketch_style)
        quick_sketch_fill_preference=data.get('quick_sketch_fill_preference','Safe Fill First')
        if hasattr(self,'quick_sketch_fill_preference') and quick_sketch_fill_preference in QUICK_SKETCH_FILL_PREFERENCES:_set('quick_sketch_fill_preference',quick_sketch_fill_preference)
        hybrid_mode=data.get('hybrid_mode','Auto Hybrid')
        if hasattr(self,'hybrid_mode') and hybrid_mode in HYBRID_MODES:_set('hybrid_mode',hybrid_mode)
        visual_verification=data.get('visual_verification','Auto')
        if hasattr(self,'visual_verification') and visual_verification in VISUAL_VERIFICATION_MODES:_set('visual_verification',visual_verification)
        color_rendering=data.get('color_rendering','Perceptual match')
        if hasattr(self,'color_rendering') and color_rendering in COLOR_RENDERING_MODES:_set('color_rendering',color_rendering)
        color_fidelity=data.get('color_fidelity','Faithful')
        if hasattr(self,'color_fidelity') and color_fidelity in COLOR_FIDELITY_MODES:_set('color_fidelity',color_fidelity)
        color_layers=data.get('color_layers','Off')
        if hasattr(self,'color_layers') and color_layers in COLOR_LAYER_MODES:_set('color_layers',color_layers)
        custom_color_workflow=data.get('custom_color_workflow','Calibrated palette')
        if hasattr(self,'custom_color_workflow') and custom_color_workflow in CUSTOM_COLOR_WORKFLOWS:_set('custom_color_workflow',custom_color_workflow)
        exact_color_limit=data.get('exact_color_limit','Auto')
        if hasattr(self,'exact_color_limit') and str(exact_color_limit) in EXACT_COLOR_LIMITS:_set('exact_color_limit',str(exact_color_limit))
        preview_mode=data.get('preview_mode','Manual')
        if hasattr(self,'preview_mode') and preview_mode in PREVIEW_MODES:_set('preview_mode',preview_mode)
        preview_detail_level=data.get('preview_detail_level','Detailed')
        if hasattr(self,'preview_detail_level') and preview_detail_level in PREVIEW_DETAIL_MODES:_set('preview_detail_level',preview_detail_level)
        if hasattr(self,'auto_clear_canvas') and type(data.get('auto_clear_canvas')) is bool:_set('auto_clear_canvas',data['auto_clear_canvas'])
        tool_strategy=data.get('tool_strategy','Auto')
        if hasattr(self,'tool_strategy') and tool_strategy in TOOL_STRATEGIES:_set('tool_strategy',tool_strategy)
        if hasattr(self,'portrait_focus') and type(data.get('portrait_focus')) is bool:_set('portrait_focus',data['portrait_focus'])
        if type(data.get('skip_white')) is bool:_set('skip_white',data['skip_white'])
        if hasattr(self,'render_preset'):_set('render_preset',data.get('render_preset') if data.get('render_preset') in ('Auto','Manual','Masterpiece','Extra fast') else 'Auto')
        if hasattr(self,'drawing_style'):
            from DrawingStyleProfiles import DRAWING_STYLES
            _set('drawing_style',data.get('drawing_style') if data.get('drawing_style') in DRAWING_STYLES else 'Auto')
        if hasattr(self,'read_gartic_timer'):_set('read_gartic_timer',data.get('read_gartic_timer',True) is not False)
        if type(data.get('outline')) is bool:_set('outline',data['outline'])
        if hasattr(self,'sketch_detail'):_set('sketch_detail',data.get('sketch_detail') if data.get('sketch_detail') in ('Auto','Simple','Balanced','Detailed') else 'Auto')
        value=data.get('contrast',1)
        if isinstance(value,(float,int)) and math.isfinite(value) and .5<=value<=2:_set('contrast',value)
        raw_brush=data.get('brush_px','Auto')
        if isinstance(raw_brush,str) and raw_brush.strip().casefold()=='auto':
            _set('brush_px','Auto')
        elif type(raw_brush) is int and 1<=raw_brush<=50:
            _set('brush_px',str(raw_brush))
        elif isinstance(raw_brush,str) and raw_brush.isdecimal() and 1<=int(raw_brush)<=50:
            _set('brush_px',str(int(raw_brush)))
        opacity=data.get('gartic_opacity','Auto')
        if hasattr(self,'gartic_opacity') and opacity in ('Auto','100%','90%','80%','70%','60%','50%','40%','30%','20%','10%'):
            _set('gartic_opacity',opacity)
        raw_limit=data.get('max_seconds')
        if type(raw_limit) is int and 5<=raw_limit<=3600:_set('max_seconds',str(raw_limit))
        elif isinstance(raw_limit,str) and raw_limit.isdecimal() and 5<=int(raw_limit)<=3600:_set('max_seconds',str(int(raw_limit)))
        if hasattr(self,'paint_simple') and type(data.get('paint_simple')) is bool:_set('paint_simple',data['paint_simple'])
        if hasattr(self,'paint_tool') and data.get('paint_tool') in ('Auto (recommended)','Use current tool','Brush','Pencil','Eraser'):
            _set('paint_tool',data['paint_tool'])
        if hasattr(self,'drop_mode'):
            # Retire the old automatic-drop drawing mode safely.
            _set('drop_mode','Show image')
        corners=data.get('corners')
        if isinstance(corners,list) and len(corners)==2 and all(isinstance(p,list) and len(p)==2 and all(type(n) is int for n in p) for p in corners):self.saved_area=corners
        from ProfileIsolation import restore_extra
        restore_extra(self,data)
        anchors=data.get('canvas_anchor_detection')
        if isinstance(anchors,dict):self.canvas_anchor_detection=anchors

    def save_settings(self):
        if getattr(self,'profile_change_in_progress',False):return False
        if getattr(self,'_settings_protected_path',None)==Path(self.settings_path):
            if not self.closing:
                self.status.set('These settings use an unsupported format. Reset this profile explicitly to replace them.')
            return False
        try:
            data=DrawBotApp._settings_data(self)
            atomic_write_text(self.settings_path,json.dumps(data,ensure_ascii=False,allow_nan=False))
            return True
        except (OSError,ValueError,TypeError,OverflowError,RuntimeError,tk.TclError) as error:
            log_event(f'Settings save failed for {self.settings_path.name}: {error!r}')
            if not self.closing:
                self.status.set('Settings could not be saved. Check the values and make sure the folder is writable.')
            return False

    def _settings_data(self):
        data={'settings_schema':2,'quality':self.quality.get(),'speed':self.speed.get(),'precision':getattr(getattr(self,'precision',None),'get',lambda:'High')(),'mode':self.mode.get(),'shape_order':getattr(getattr(self,'shape_order',None),'get',lambda:'Fill first')(),'shape_model':getattr(getattr(self,'shape_model',None),'get',lambda:'Auto')(),'max_stroke_cap':getattr(getattr(self,'max_stroke_cap',None),'get',lambda:'Auto')(),'progressive_rendering':getattr(getattr(self,'progressive_rendering',None),'get',lambda:'Auto')(),'planning_watchdog':getattr(getattr(self,'planning_watchdog',None),'get',lambda:'Auto')(),'time_budget_mode':getattr(getattr(self,'time_budget_mode',None),'get',lambda:'Manual')(),'adaptive_deadline_renderer':bool(getattr(getattr(self,'adaptive_deadline_renderer',None),'get',lambda:True)()),'deadline_safety_reserve':getattr(getattr(self,'deadline_safety_reserve',None),'get',lambda:'Auto')(),'target_stroke_count':getattr(getattr(self,'target_stroke_count',None),'get',lambda:'Auto')(),'target_stroke_custom':getattr(getattr(self,'target_stroke_custom',None),'get',lambda:'2500')(),'drawing_style':getattr(getattr(self,'drawing_style',None),'get',lambda:'Auto')(),'render_style':getattr(getattr(self,'render_style',None),'get',lambda:'Auto')(),'draw_quality':getattr(getattr(self,'draw_quality',None),'get',lambda:'High likeness')(),'human_mode':'Off','gpu_mode':getattr(getattr(self,'gpu_mode',None),'get',lambda:'Auto')(),'gpu_vram':getattr(getattr(self,'gpu_vram',None),'get',lambda:'Auto')(),'gpu_performance':getattr(getattr(self,'gpu_performance',None),'get',lambda:'High throughput')(),'cpu_workers':getattr(getattr(self,'cpu_workers',None),'get',lambda:'Auto')(),'cpu_engine':getattr(getattr(self,'cpu_engine',None),'get',lambda:'Auto')(),'ram_budget':getattr(getattr(self,'ram_budget',None),'get',lambda:'Auto')(),'ram_custom_mb':getattr(getattr(self,'ram_custom_mb',None),'get',lambda:'4096')(),'planning_resolution':getattr(getattr(self,'planning_resolution',None),'get',lambda:'High')(),'resource_scheduler':getattr(getattr(self,'resource_scheduler',None),'get',lambda:'Auto')(),'profile_engine':getattr(getattr(self,'profile_engine',None),'get',lambda:'Auto')(),'edge_behavior':getattr(getattr(self,'edge_behavior',None),'get',lambda:'Auto')(),'background_fill':getattr(getattr(self,'background_fill',None),'get',lambda:'Balanced')(),'fill_engine':getattr(getattr(self,'fill_engine',None),'get',lambda:'Auto')(),'use_region_fill_engine':bool(getattr(getattr(self,'use_region_fill_engine',None),'get',lambda:True)()),'fill_aggressiveness':getattr(getattr(self,'fill_aggressiveness',None),'get',lambda:'Balanced')(),'background_simplification':getattr(getattr(self,'background_simplification',None),'get',lambda:'Balanced')(),'color_grouping':getattr(getattr(self,'color_grouping',None),'get',lambda:'Smart')(),'color_workflow':getattr(getattr(self,'color_workflow',None),'get',lambda:'Finish color first')(),'stroke_optimizer':getattr(getattr(self,'stroke_optimizer',None),'get',lambda:'Auto')(),'adaptive_detail':getattr(getattr(self,'adaptive_detail',None),'get',lambda:'Auto')(),'detail_zoom':getattr(getattr(self,'detail_zoom',None),'get',lambda:'Auto')(),'quick_sketch_style':getattr(getattr(self,'quick_sketch_style',None),'get',lambda:'Balanced')(),'quick_sketch_fill_preference':getattr(getattr(self,'quick_sketch_fill_preference',None),'get',lambda:'Safe Fill First')(),'hybrid_mode':getattr(getattr(self,'hybrid_mode',None),'get',lambda:'Auto Hybrid')(),'visual_verification':getattr(getattr(self,'visual_verification',None),'get',lambda:'Auto')(),'color_rendering':getattr(getattr(self,'color_rendering',None),'get',lambda:'Perceptual match')(),'color_fidelity':getattr(getattr(self,'color_fidelity',None),'get',lambda:'Faithful')(),'color_layers':getattr(getattr(self,'color_layers',None),'get',lambda:'Off')(),'custom_color_workflow':getattr(getattr(self,'custom_color_workflow',None),'get',lambda:'Calibrated palette')(),'exact_color_limit':getattr(getattr(self,'exact_color_limit',None),'get',lambda:'Auto')(),'preview_mode':getattr(getattr(self,'preview_mode',None),'get',lambda:'Manual')(),'preview_detail_level':getattr(getattr(self,'preview_detail_level',None),'get',lambda:'Detailed')(),'auto_clear_canvas':bool(getattr(getattr(self,'auto_clear_canvas',None),'get',lambda:False)()),'tool_strategy':getattr(getattr(self,'tool_strategy',None),'get',lambda:'Auto')(),'portrait_focus':getattr(getattr(self,'portrait_focus',None),'get',lambda:True)(),'skip_white':self.skip_white.get(),'contrast':self.contrast.get(),'corners':self.corners or self.saved_area,'outline':self.outline.get(),'brush_px':self.brush_px.get(),'max_seconds':self.max_seconds.get()}
        if getattr(self,'canvas_anchor_detection',None):data['canvas_anchor_detection']=self.canvas_anchor_detection
        if hasattr(self,'render_preset'):data['render_preset']=self.render_preset.get()
        if hasattr(self,'drawing_style'):data['drawing_style']=self.drawing_style.get()
        if hasattr(self,'read_gartic_timer'):data['read_gartic_timer']=self.read_gartic_timer.get()
        if hasattr(self,'sketch_detail'):data['sketch_detail']=self.sketch_detail.get()
        if hasattr(self,'paint_simple'):data['paint_simple']=self.paint_simple.get()
        if hasattr(self,'paint_tool'):data['paint_tool']=self.paint_tool.get()
        from ProfileIsolation import extra_settings
        data['profile_extras']=extra_settings(self)
        if hasattr(self,'gartic_opacity'):data['gartic_opacity']=self.gartic_opacity.get()
        return data

    def options(self):
        if getattr(getattr(self,'render_preset',None),'get',lambda:'Manual')()=='Masterpiece':
            self.time_budget_mode.set('Unlimited')
        if uses_paint_color(self) and self.game.get()!='Microsoft Paint':
            self.outline.set(True)
            self.subject_focus.set('Off')
        brush_raw=str(self.brush_px.get()).strip()
        brush_auto=brush_raw.casefold()=='auto'
        try:
            brush=None if brush_auto else int(brush_raw)
        except (TypeError,ValueError,tk.TclError) as error:
            raise ValueError('Brush width must be Auto or a whole number.') from error
        _profile_key_for_brush=PROFILES[self.game.get()][0]
        _brush_limit=5 if _profile_key_for_brush in ('gartic-phone','gartic-io') else 50
        if brush is not None and not 1<=brush<=_brush_limit:
            _label='Gartic level 1–5' if _brush_limit==5 else '1–50 px'
            raise ValueError(f'Brush width: Auto or {_label}.')
        auto_brush_width_meta=None
        quality=self.quality.get();speed=normalize_speed(self.speed.get());precision=self.precision.get();mode=self.mode.get();shape_order=getattr(getattr(self,'shape_order',None),'get',lambda:'Fill first')();shape_model=getattr(getattr(self,'shape_model',None),'get',lambda:'Auto')();max_stroke_cap=getattr(getattr(self,'max_stroke_cap',None),'get',lambda:'Auto')();progressive_rendering=getattr(getattr(self,'progressive_rendering',None),'get',lambda:'Auto')();planning_watchdog=getattr(getattr(self,'planning_watchdog',None),'get',lambda:'Auto')();time_budget_mode=getattr(getattr(self,'time_budget_mode',None),'get',lambda:'Manual')();target_stroke_count=getattr(getattr(self,'target_stroke_count',None),'get',lambda:'Auto')();target_stroke_custom=getattr(getattr(self,'target_stroke_custom',None),'get',lambda:'2500')();render_style=self.render_style.get();draw_quality=getattr(getattr(self,'draw_quality',None),'get',lambda:'High likeness')();human_mode='Off';gpu_mode=getattr(getattr(self,'gpu_mode',None),'get',lambda:'Auto')();gpu_vram=getattr(getattr(self,'gpu_vram',None),'get',lambda:'Auto')();gpu_performance=getattr(getattr(self,'gpu_performance',None),'get',lambda:'High throughput')();cpu_workers=getattr(getattr(self,'cpu_workers',None),'get',lambda:'Auto')();cpu_engine=getattr(getattr(self,'cpu_engine',None),'get',lambda:'Auto')();ram_budget=getattr(getattr(self,'ram_budget',None),'get',lambda:'Auto')();ram_custom_mb=getattr(getattr(self,'ram_custom_mb',None),'get',lambda:'4096')();planning_resolution=getattr(getattr(self,'planning_resolution',None),'get',lambda:'High')();resource_scheduler=getattr(getattr(self,'resource_scheduler',None),'get',lambda:'Auto')();profile_engine=getattr(getattr(self,'profile_engine',None),'get',lambda:'Manual settings')();edge_behavior=getattr(getattr(self,'edge_behavior',None),'get',lambda:'Auto')();background_fill=getattr(getattr(self,'background_fill',None),'get',lambda:'Balanced')();fill_engine=getattr(getattr(self,'fill_engine',None),'get',lambda:'Auto')();background_simplification=getattr(getattr(self,'background_simplification',None),'get',lambda:'Balanced')();color_grouping=getattr(getattr(self,'color_grouping',None),'get',lambda:'Smart')();color_workflow=getattr(getattr(self,'color_workflow',None),'get',lambda:'Finish color first')();stroke_optimizer=getattr(getattr(self,'stroke_optimizer',None),'get',lambda:'Auto')();adaptive_detail=getattr(getattr(self,'adaptive_detail',None),'get',lambda:'Auto')();detail_zoom=getattr(getattr(self,'detail_zoom',None),'get',lambda:'Auto')();quick_sketch_style=getattr(getattr(self,'quick_sketch_style',None),'get',lambda:'Balanced')();quick_sketch_fill_preference=getattr(getattr(self,'quick_sketch_fill_preference',None),'get',lambda:'Safe Fill First')();hybrid_mode=getattr(getattr(self,'hybrid_mode',None),'get',lambda:'Auto Hybrid')();visual_verification=getattr(getattr(self,'visual_verification',None),'get',lambda:'Auto')();color_rendering=getattr(getattr(self,'color_rendering',None),'get',lambda:'Perceptual match')();color_fidelity=getattr(getattr(self,'color_fidelity',None),'get',lambda:'Faithful')();color_layers=getattr(getattr(self,'color_layers',None),'get',lambda:'Off')();custom_color_workflow=getattr(getattr(self,'custom_color_workflow',None),'get',lambda:'Calibrated palette')();exact_color_limit=getattr(getattr(self,'exact_color_limit',None),'get',lambda:'Auto')();preview_mode=getattr(getattr(self,'preview_mode',None),'get',lambda:'Manual')();preview_detail_level=getattr(getattr(self,'preview_detail_level',None),'get',lambda:'Detailed')();tool_strategy=getattr(getattr(self,'tool_strategy',None),'get',lambda:'Auto')()
        use_region_fill_engine=bool(getattr(getattr(self,'use_region_fill_engine',None),'get',lambda:True)())
        adaptive_deadline_renderer=bool(getattr(getattr(self,'adaptive_deadline_renderer',None),'get',lambda:True)())
        deadline_safety_reserve=getattr(getattr(self,'deadline_safety_reserve',None),'get',lambda:'Auto')()
        fill_aggressiveness=getattr(getattr(self,'fill_aggressiveness',None),'get',lambda:'Balanced')()
        if fill_aggressiveness not in ('Safe','Balanced','Aggressive'):
            raise ValueError('Fill aggressiveness must be Safe, Balanced or Aggressive.')
        validate_profile_engine(profile_engine)
        _requested_policy={
            'mode':mode,'shape_order':shape_order,'shape_model':shape_model,'max_stroke_cap':max_stroke_cap,
            'progressive_rendering':progressive_rendering,'planning_watchdog':planning_watchdog,
            'time_budget_mode':time_budget_mode,'target_stroke_count':target_stroke_count,'target_stroke_custom':target_stroke_custom,
            'render_style':render_style,'draw_quality':draw_quality,'quality':quality,'speed':speed,'precision':precision,
            'planning_resolution':planning_resolution,'resource_scheduler':resource_scheduler,
            'background_fill':background_fill,'fill_engine':fill_engine,'use_region_fill_engine':use_region_fill_engine,'fill_aggressiveness':fill_aggressiveness,'background_simplification':background_simplification,
            'color_grouping':color_grouping,'color_workflow':color_workflow,'stroke_optimizer':stroke_optimizer,
            'adaptive_detail':adaptive_detail,'quick_sketch_style':quick_sketch_style,'quick_sketch_fill_preference':quick_sketch_fill_preference,'hybrid_mode':hybrid_mode,'visual_verification':visual_verification,'color_rendering':color_rendering,'color_fidelity':color_fidelity,
            'color_layers':color_layers,'custom_color_workflow':custom_color_workflow,'exact_color_limit':exact_color_limit,
            'tool_strategy':tool_strategy,'edge_behavior':edge_behavior,
        }
        _effective_policy,profile_policy_meta=resolve_profile_policy(self.game.get(),_requested_policy,mode=profile_engine)
        profile_polish_meta={}
        try:
            from ProfilePolish import apply_profile_polish
            _effective_policy['profile_engine']=profile_engine
            _effective_policy, profile_polish_meta = apply_profile_polish(self.game.get(), _effective_policy)
        except Exception as _profile_polish_error:
            log_event(f'Profile polish pre-resolution skipped: {_profile_polish_error!r}')
        mode=_effective_policy['mode'];shape_order=_effective_policy['shape_order'];shape_model=_effective_policy['shape_model'];max_stroke_cap=_effective_policy['max_stroke_cap']
        progressive_rendering=_effective_policy['progressive_rendering'];planning_watchdog=_effective_policy['planning_watchdog']
        time_budget_mode=_effective_policy['time_budget_mode'];target_stroke_count=_effective_policy['target_stroke_count'];target_stroke_custom=_effective_policy['target_stroke_custom']
        render_style=_effective_policy['render_style'];draw_quality=_effective_policy['draw_quality'];quality=_effective_policy['quality'];speed=normalize_speed(_effective_policy['speed']);precision=_effective_policy['precision']
        planning_resolution=_effective_policy['planning_resolution'];resource_scheduler=_effective_policy['resource_scheduler']
        background_fill=_effective_policy['background_fill'];fill_engine=_effective_policy['fill_engine'];background_simplification=_effective_policy['background_simplification']
        color_grouping=_effective_policy['color_grouping'];color_workflow=_effective_policy['color_workflow'];stroke_optimizer=_effective_policy['stroke_optimizer']
        adaptive_detail=_effective_policy['adaptive_detail'];quick_sketch_style=_effective_policy.get('quick_sketch_style',quick_sketch_style);quick_sketch_fill_preference=_effective_policy.get('quick_sketch_fill_preference',quick_sketch_fill_preference);hybrid_mode=_effective_policy.get('hybrid_mode',hybrid_mode);visual_verification=_effective_policy['visual_verification'];color_rendering=_effective_policy['color_rendering'];color_fidelity=_effective_policy.get('color_fidelity',color_fidelity)
        color_layers=_effective_policy['color_layers'];custom_color_workflow=_effective_policy['custom_color_workflow'];exact_color_limit=_effective_policy['exact_color_limit'];tool_strategy=_effective_policy['tool_strategy'];edge_behavior=_effective_policy.get('edge_behavior','Auto')
        if quality not in QUALITY:
            raise ValueError('Choose a valid detail level.')
        validate_precision(precision)
        if mode not in DRAWING_MODES:
            raise ValueError('Choose a valid drawing mode.')
        validate_shape_order(shape_order)
        validate_shape_model(shape_model)
        validate_stroke_cap(max_stroke_cap)
        validate_progressive_rendering(progressive_rendering)
        validate_planning_watchdog(planning_watchdog)
        validate_time_budget_mode(time_budget_mode)
        # The numeric control belongs to Manual/Custom. Fixed presets and
        # Unlimited must not depend on stale text in that inactive control.
        manual_budget=time_budget_mode in ('Manual','Custom')
        try:
            limit=int(self.max_seconds.get())
        except (TypeError,ValueError) as error:
            if manual_budget:
                raise ValueError('Time limit must be a whole number.') from error
            limit=180
        if not 5<=limit<=3600:
            if manual_budget:
                raise ValueError('Time limit: 5–3600 seconds.')
            limit=180
        validate_target_stroke_count(target_stroke_count)
        if render_style not in ('Auto','Portrait / shaded','Standard / pixel',QUICK_SKETCH_RENDER_STYLE,SKETCH_FILL_RENDER_STYLE,HYBRID_RENDER_STYLE):
            raise ValueError('Choose a valid rendering style.')
        validate_quick_sketch_style(quick_sketch_style)
        validate_fill_preference(quick_sketch_fill_preference)
        validate_hybrid_mode(hybrid_mode)
        if draw_quality not in ('Balanced','High likeness','Maximum likeness','GPU enhanced','Pixel Accurate'):
            raise ValueError('Choose a valid draw quality.')
        validate_human_mode(human_mode)
        validate_acceleration_mode(gpu_mode)
        validate_vram_budget(gpu_vram)
        validate_gpu_performance(gpu_performance)
        validate_cpu_workers(cpu_workers)
        validate_cpu_engine(cpu_engine)
        validate_ram_budget(ram_budget)
        validate_planning_resolution(planning_resolution)
        validate_resource_scheduler(resource_scheduler)
        allocation=resolve_allocation(cpu_workers,cpu_engine,ram_budget,ram_custom_mb)
        try:
            area_size=(self.area()[2],self.area()[3]) if len(self.corners)==2 else None
        except Exception:
            area_size=None
        # Validate against this operation's resolved RAM policy as well as its
        # usable CPU capacity. The loader's default retains the saved RAM bucket.
        recommendation=(load_resource_recommendation(signature=resource_machine_signature(
            logical_cpus=allocation['logical_cpus'], ram_mb=allocation['ram_budget_mb']))
            if resource_scheduler!='Off' else None)
        scheduler_plan=resolve_resource_schedule(
            allocation, mode=resource_scheduler, area=area_size, drawing_mode=mode,
            gpu_mode=gpu_mode, gpu_available=(gpu_mode!='CPU' and draw_quality in ('GPU enhanced','Pixel Accurate')),
            preview=False, recommendation=recommendation)
        allocation=dict(allocation)
        allocation['resource_scheduler']=resource_scheduler
        allocation['resource_scheduler_plan']=scheduler_plan
        allocation['cpu_workers_resolved']=int(scheduler_plan.get('effective_cpu_workers',allocation.get('cpu_workers_resolved',1)) or 1)
        allocation['cpu_engine']=scheduler_plan.get('recommended_engine',allocation.get('cpu_engine','Auto'))
        validate_background_fill(background_fill)
        validate_fill_engine(fill_engine)
        validate_background_simplification(background_simplification)
        validate_color_grouping(color_grouping)
        if color_workflow not in COLOR_WORKFLOWS:raise ValueError('Choose a valid color workflow.')
        validate_stroke_optimizer(stroke_optimizer)
        validate_adaptive_detail(adaptive_detail)
        from DetailZoomPass import validate_detail_zoom_mode
        validate_detail_zoom_mode(detail_zoom)
        validate_visual_verification(visual_verification)
        validate_color_rendering(color_rendering)
        validate_color_fidelity(color_fidelity)
        validate_color_layers(color_layers)
        validate_custom_color_workflow(custom_color_workflow)
        validate_exact_color_limit(exact_color_limit)
        validate_preview_mode(preview_mode)
        validate_preview_detail_mode(preview_detail_level)
        validate_tool_strategy(tool_strategy)
        validate_edge_behavior(edge_behavior)
        paint_profile=self.game.get()=='Microsoft Paint'
        if brush is None:
            from AutoBrushWidth import resolve_brush_width
            _auto_brush=resolve_brush_width(
                getattr(self,'original',None),target_size=area_size,draw_quality=draw_quality,
                render_preset=getattr(getattr(self,'render_preset',None),'get',lambda:'Auto')(),
                render_style=render_style,outline=bool(self.outline.get()),
                subject_focus=self.subject_focus.get() if hasattr(self,'subject_focus') else 'Off',
                profile_key=PROFILES[self.game.get()][0],speed=speed,quality=quality)
            brush=int(_auto_brush.brush_px);auto_brush_width_meta=_auto_brush.as_dict()
        selected_tool=self.paint_tool.get() if paint_profile else 'Use current tool'
        if selected_tool not in ('Auto (recommended)','Use current tool','Brush','Pencil','Eraser'):
            raise ValueError('Choose a valid Paint drawing tool.')
        erase_mode=paint_profile and selected_tool=='Eraser'
        fill_available=False
        if (background_fill!='Off' or use_region_fill_engine) and not bypasses_palette(self):
            try:
                if paint_profile and selected_tool not in ('Use current tool','Eraser'):
                    from PaintTools import load_tool_calibration
                    tool_data=load_tool_calibration()
                    fill_available=(tool_data.get('tools',{}).get('Fill') is not None and self._paint_tool_preflight_ready())
                elif not paint_profile:
                    profile_key_for_fill=PROFILES[self.game.get()][0]
                    from AppTools import load_calibration
                    app_data=load_calibration(profile_key_for_fill)
                    fill_available=all(name in app_data.get('tools',{}) for name in ('Brush','Fill'))
            except (OSError,ValueError,TypeError,AttributeError):
                fill_available=False
            if (not fill_available) and (not paint_profile):
                try:
                    from BrowserToolLayout import SUPPORTED as AUTO_BROWSER_TOOL_PROFILES
                    fill_available=(PROFILES[self.game.get()][0] in AUTO_BROWSER_TOOL_PROFILES)
                except Exception:
                    fill_available=False
        effective_paint_tool=selected_tool
        if paint_profile and selected_tool=='Auto (recommended)':
            try:
                from PaintTools import load_tool_calibration
                tool_data=load_tool_calibration()
            except (OSError,ValueError,TypeError):
                tool_data={}
            portrait_hint=(render_style=='Portrait / shaded' or (render_style=='Auto' and self.paint_simple.get()))
            effective_paint_tool=choose_paint_tool(selected_tool,tool_strategy,tool_data,portrait=portrait_hint,brush_px=brush)
        contrast=float(self.contrast.get())
        if not math.isfinite(contrast) or not .5<=contrast<=2:
            raise ValueError('Contrast must stay between 0.5 and 2.0.')
        from TimeBudget import resolve_time_budget_details
        budget_details=resolve_time_budget_details(time_budget_mode,limit,deadline_safety_reserve)
        effective_limit=(3600 if budget_details.get('unlimited') else
                         max(1,int(round(float(budget_details['render_budget_seconds'])))))
        time_budget_active=bool(budget_details['active'])
        target_cap, target_meta = resolve_target_stroke_count(
            target_stroke_count, target_stroke_custom,
            time_budget_mode=time_budget_mode, effective_time_seconds=effective_limit,
            speed=speed, drawing_mode=mode, preview=False)
        anchor_options={}
        anchor_detection=getattr(self,'canvas_anchor_detection',None)
        if isinstance(anchor_detection,dict):
            polygon=anchor_detection.get('canvas_polygon')
            anchors=anchor_detection.get('canvas_anchors')
            if polygon:
                anchor_options['canvas_polygon']=polygon
                anchor_options['canvas_polygon_space']=anchor_detection.get('canvas_polygon_space','normalized')
            if anchors:
                anchor_options['canvas_anchors']=anchors
                anchor_options['canvas_anchor_space']=anchor_detection.get('canvas_anchor_space','normalized')
                anchor_options['canvas_anchor_meta']=anchor_detection.get('canvas_anchor_meta',{})
        transform_meta=getattr(self,'canvas_anchor_transform_meta',None)
        if isinstance(transform_meta,dict):
            anchor_options['canvas_anchor_transform_meta']=dict(transform_meta)
        profile_key=PROFILES[self.game.get()][0]
        # Unit tests and lightweight headless option probes may construct a
        # DrawBotApp-shaped object without __init__.  Fall back to the active
        # profile's isolated calibration file instead of requiring the UI-owned
        # calibration_path attribute.
        calibration_path=Path(getattr(self,'calibration_path',profile_palette_file(profile_key)))
        calibration_fingerprint=calibration_context_fingerprint(profile_key,workflow=custom_color_workflow,palette_path=calibration_path,
            extras=(f'paint-tool:{effective_paint_tool}',f'brush:{brush}'))
        try:
            from CalibrationState import profile_calibration_summary
            from PaletteMaps import PRESETS
            calibration_state=profile_calibration_summary(profile_key,palette_path=calibration_path,
                preset_available=bool(PRESETS.get(profile_key)),workflow=custom_color_workflow,
                context_fingerprint=calibration_fingerprint)
        except Exception:
            calibration_state={'profile_key':profile_key,'fingerprint':calibration_fingerprint}
        if profile_polish_meta:
            from ProfilePolish import profile_release_warnings
            profile_polish_meta['warnings']=list(profile_release_warnings(self.game.get(),calibration_state))
        result={'detail':QUALITY[quality],'delay':SPEED[speed],'speed':speed,'precision':precision,'profile_name':self.game.get(),'profile_key':profile_key,'paint_profile':bool(paint_profile),'calibration_fingerprint':calibration_fingerprint,'calibration_state':calibration_state,
                'lines':mode!=DOT_MODE,'drawing_mode':mode,'smart_paths':mode==SMART_PATH_MODE,'shape_order':shape_order,'shape_model':shape_model,'max_stroke_cap':max_stroke_cap,'progressive_rendering':progressive_rendering,'planning_watchdog':planning_watchdog,'planning_timeout_seconds':45 if mode==SHAPE_PATH_MODE else 75,'drawing_style':getattr(getattr(self,'drawing_style',None),'get',lambda:'Auto')(),'render_style':render_style,'draw_quality':draw_quality,'human_mode':human_mode,'gpu_mode':gpu_mode,'gpu_vram':gpu_vram,'gpu_performance':gpu_performance,'cpu_workers':cpu_workers,'cpu_engine':cpu_engine,'ram_budget':ram_budget,'ram_custom_mb':ram_custom_mb,'planning_resolution':planning_resolution,'resource_scheduler':resource_scheduler,'profile_engine':profile_engine,'profile_policy_meta':profile_policy_meta,'profile_polish_meta':profile_polish_meta,**allocation,'background_fill':background_fill,'fill_engine':fill_engine,'background_simplification':background_simplification,'color_grouping':color_grouping,'color_workflow':color_workflow,'stroke_optimizer':stroke_optimizer,'stroke_optimizer_resolved':resolve_stroke_optimizer(stroke_optimizer,drawing_mode=mode),'adaptive_detail':adaptive_detail,'detail_zoom':detail_zoom,'quick_sketch_style':quick_sketch_style,'quick_sketch_fill_preference':quick_sketch_fill_preference,'hybrid_mode':hybrid_mode,'visual_verification':visual_verification,'visual_verification_resolved':resolve_visual_verification(visual_verification,paint_profile=paint_profile,dry_run=False,test=False),'color_rendering':color_rendering,'color_fidelity':color_fidelity,'color_layers':color_layers,'custom_color_workflow':custom_color_workflow,'exact_color_limit':exact_color_limit,'exact_color_limit_resolved':resolve_exact_color_limit(exact_color_limit,draw_quality=draw_quality,preview=False),'exact_color_available':custom_rgb_available(PROFILES[self.game.get()][0]),'preview_mode':preview_mode,'preview_detail_level':preview_detail_level,'auto_clear_canvas':bool(getattr(getattr(self,'auto_clear_canvas',None),'get',lambda:False)()),'canvas_clear_strategy':'pending','canvas_clear_actions':[],'canvas_clear_restore_actions':[],'canvas_clear_estimate_seconds':0.0,'tool_strategy':tool_strategy,'subject_focus':self.subject_focus.get() if hasattr(self,'subject_focus') else 'Off','subject_region':getattr(self,'subject_region',None),'portrait_focus':bool(self.portrait_focus.get()),'skip_white':bool(self.skip_white.get()),'contrast':contrast,'outline':bool(self.outline.get()),'sketch_detail':getattr(getattr(self,'sketch_detail',None),'get',lambda:'Auto')(),'brush_px':brush,'brush_px_requested':brush_raw,'auto_brush_width_meta':auto_brush_width_meta,'gartic_opacity':getattr(getattr(self,'gartic_opacity',None),'get',lambda:'Auto')(),'canvas_edge_verification':'Auto','canvas_edge_margin_px':24,'canvas_edge_tolerance_px':4,'canvas_edge_search_px':24,'edge_behavior':edge_behavior,'edge_behavior_resolved':resolve_edge_behavior(edge_behavior, profile_name=self.game.get(), drawing_mode=mode, outline=bool(self.outline.get())),'max_seconds':effective_limit,'manual_max_seconds':limit,'time_budget_mode':time_budget_mode,'time_budget_seconds':effective_limit,'time_budget_active':time_budget_active,'adaptive_deadline_renderer':adaptive_deadline_renderer,'deadline_safety_reserve':deadline_safety_reserve,'target_stroke_count':target_stroke_count,'target_stroke_custom':target_stroke_custom,'target_stroke_count_resolved':target_cap,**target_meta,
                **anchor_options,
                'render_preset':getattr(getattr(self,'render_preset',None),'get',lambda:'Manual')(),'unlimited_time':bool(budget_details.get('unlimited')),
                'read_gartic_timer':bool(getattr(getattr(self,'read_gartic_timer',None),'get',lambda:True)()),
                'paint_current_color':uses_paint_color(self) or erase_mode,'erase_mode':erase_mode,
                'adaptive_color_verification':bool(paint_profile and not erase_mode),'strict_color_verification':bool(paint_profile and not erase_mode),'visual_verification_enabled':bool(paint_profile and not erase_mode and resolve_visual_verification(visual_verification,paint_profile=paint_profile,dry_run=False,test=False)!='Off'),'color_verification_tolerance':48,'color_probe_source_span':4,
                'color_session_cache':getattr(self,'color_session_cache',{}),
                'render_resume_state':getattr(self,'pending_render_resume',None),
                'paint_tool':selected_tool,'effective_paint_tool':effective_paint_tool,'tool_actions':[],'fill_tool_available':fill_available,'fill_tool_actions':[],'fill_restore_actions':[]}
        result['use_region_fill_engine']=use_region_fill_engine
        result['fill_aggressiveness']=fill_aggressiveness
        if 'exact_color_limit_profile_ceiling' in _effective_policy:
            result['exact_color_limit_profile_ceiling']=_effective_policy['exact_color_limit_profile_ceiling']
        from PicturePalettePlanning import active_picture_palette
        prepared=active_picture_palette(self)
        if (prepared and not result.get('paint_current_color') and not result.get('outline') and
                result['custom_color_workflow'] in ('Adaptive exact (recommended)', 'Exact custom + palette fallback')):
            result['picture_palette_rgb']=prepared
        return result

    def area(self):
        (x1,y1),(x2,y2)=self.corners
        return min(x1,x2),min(y1,y2),abs(x2-x1),abs(y2-y1)

    def refresh_tool_calibration(self):
        if not hasattr(self,'paint_tool_text'):return
        if self.game.get()!='Microsoft Paint':
            self.paint_tool_text.set('Automatic tool selection is available for Microsoft Paint.')
            return
        try:
            from PaintTools import load_tool_calibration
            data=load_tool_calibration()
            if data.get('version') not in (2,3):
                raise ValueError('Legacy calibration')
            tools=[name for name in ('Pencil','Fill','Eraser') if name in data.get('tools',{})]
            if data.get('brush_menu') and data.get('brush_preset'):tools.insert(0,'Brush')
            if not tools:raise ValueError('No Paint tools have been captured.')
            opacity=' · Brush 100% opacity saved' if data.get('opacity_100') is not None else ' · Brush opacity not calibrated'
            auto_ready=('Pencil' in data.get('tools',{}) or
                        (data.get('opacity_100') is not None and data.get('brush_menu') and data.get('brush_preset')))
            prefix='✓ Auto ready · ' if auto_ready else '✓ '
            auto_meta=data.get('auto') or {}
            auto_note=(f' · visual auto {float(auto_meta.get("confidence",0))*100:.0f}%' if auto_meta else '')
            self.paint_tool_text.set(prefix+', '.join(tools)+opacity+auto_note)
        except (OSError,ValueError):
            self.paint_tool_text.set('Paint tools need calibration. Use Calibrate Paint tools.')

    def refresh_palette(self):
        reset_palette()
        if bypasses_palette(self):
            self.palette_ready=False
            if uses_paint_eraser(self):
                self.palette_text.set('Eraser mode does not use the color palette. The source image is treated as an erase mask.')
            else:
                self.palette_text.set('No palette required. Select black and a thin pencil in the target app/game before Start. Preview is shown in black; the selected ink is used.')
            return
        try:
            profile_key=PROFILES[self.game.get()][0]
            load_calibration(self.calibration_path,profile_key=profile_key)
            self.palette_ready=True
            try:
                from Colors import calibration_metadata
                meta=calibration_metadata(self.calibration_path,profile_key=profile_key)
                state=str(meta.get('state') or 'calibrated').lower()
                label={'verified':'Palette verified','calibrated':'Palette calibrated','estimated':'Palette estimated'}.get(state,'Palette ready')
                detail=''
                verification=meta.get('verification') or {}
                if state=='verified' and isinstance(verification,dict) and isinstance(verification.get('confidence'),(int,float)):
                    detail=f" · {float(verification['confidence'])*100:.0f}%"
                self.palette_text.set(f'✓ {label} · {int(meta.get("count") or len(allColors))} colors{detail}')
            except Exception:
                self.palette_text.set('✓ Palette calibrated')
        except (OSError,ValueError):
            reset_palette()
            from PaletteMaps import PRESETS
            from Colors import Color
            preset=PRESETS.get(PROFILES[self.game.get()][0])
            if preset:
                allColors.clear()
                for name,rgb in zip(preset.names,preset.colors):Color(name,*rgb)
                closest_color.cache_clear()
            self.palette_ready=False
            self.palette_text.set(f'Estimated palette · {len(preset.colors)} preset colors · verify/select the palette area.' if preset else 'Calibration unavailable · read the color grid or capture colors manually.')

    def _close_smart_drop_overlay(self, reason=''):
        DrawBotApp._cancel_after_attr(self,'smart_drop_timeout_after')
        overlay=getattr(self,'smart_drop_overlay',None)
        self.smart_drop_overlay=None
        if overlay is not None:
            try:overlay.destroy()
            except (tk.TclError,RuntimeError):pass
        if reason:
            log_event(f'Game Canvas Drop overlay closed: {reason}.')

    def _expire_smart_drop_overlay(self):
        self.smart_drop_timeout_after=None
        if getattr(self,'smart_drop_overlay',None) is None:return False
        DrawBotApp._close_smart_drop_overlay(self,'60-second arm timeout')
        try:
            self.status.set('Game Canvas Drop expired. Press Arm game canvas drop and drag the image again.')
            self.smart_drop_in_text.set('Canvas drop is idle. Arm it when you are ready to drag an image onto the game canvas.')
        except Exception:pass
        return True

    def arm_smart_canvas_drop(self):
        """Arm a canvas-only OS drop target over a detected browser game canvas."""
        if self.activity or self.closing:return False
        try:
            from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
            profile_key=PROFILES.get(self.game.get(),('',))[0]
            if profile_key not in SUPPORTED_BROWSER_PROFILES:
                self.status.set('Game Canvas Drop supports Gartic Phone, Skribbl.io/Fast, SketchHeads and Sketchful.io.')
                self.smart_drop_in_text.set('Choose a supported browser drawing profile first.')
                return False
            if not hasattr(self.root,'drop_target_register'):
                self.status.set('Game Canvas Drop needs tkinterdnd2. Use Select image or Ctrl+V instead.')
                return False
            DrawBotApp._close_smart_drop_overlay(self,'re-arm')
            self.smart_drop_pending_payload=None
            self.smart_drop_generation=int(getattr(self,'smart_drop_generation',0))+1
            generation=self.smart_drop_generation
            self.smart_drop_in_text.set('Detecting the real drawable canvas. No mouse input is sent.')
            self.status.set('Game Canvas Drop: detecting the target canvas…')
            preferred=(self.target_window[0] if getattr(self,'target_window',None) else None)
            def work():
                import os
                from SmartDropInCanvas import discover_canvas_target
                payload=discover_canvas_target(profile_key,preferred_handle=preferred,exclude_pid=os.getpid(),cancelled=self.stop.is_set)
                if self.stop.is_set():raise InterruptedError('Game Canvas Drop detection cancelled.')
                payload['profile_name']=self.game.get();payload['profile_key']=profile_key;payload['generation']=generation
                self.events.put(('smart_drop_canvas_ready',payload))
            return bool(self.begin_worker('smart-drop-detect',work))
        except Exception as error:
            self.status.set(f'Game Canvas Drop could not start: {error}')
            return False

    def _show_smart_drop_overlay(self,payload):
        """Open a temporary drop target exactly over the detected game canvas.

        The overlay accepts both normal image files and browser image drags
        (URL/text/HTML payloads). A valid drop is explicit one-shot permission
        to import the image and run Browser One-Click, even when the persistent
        One-Click switch is off. Paint is never eligible for this path.
        """
        if self.closing:return False
        from SmartDropInCanvas import place_canvas_overlay, event_screen_point, point_in_canvas
        meta=dict((payload or {}).get('target_meta') or {})
        canvas_box=tuple(map(int,(payload or {}).get('canvas_box') or ()))
        client_rect=tuple(map(int,meta.get('client_rect') or ()))
        if len(canvas_box)!=4 or len(client_rect)!=4:
            raise ValueError('Game Canvas Drop lost its detected canvas geometry.')
        DrawBotApp._close_smart_drop_overlay(self,'replace')
        try:
            from tkinterdnd2 import DND_FILES,TkinterDnD
            try:
                from tkinterdnd2 import DND_TEXT
            except ImportError:
                DND_TEXT='DND_Text'
            class SmartDropOverlay(tk.Toplevel,TkinterDnD.DnDWrapper):
                pass
            overlay=SmartDropOverlay(self.root)
            self.smart_drop_overlay=overlay
            overlay.withdraw()
            overlay.title('Image Draw Bot — Game Canvas Drop')
            overlay.overrideredirect(True)
            # Important: the OS drop target exists only over the actual drawable
            # canvas, not over chat/toolbars/browser chrome.
            try:overlay.attributes('-topmost',True)
            except tk.TclError:pass
            try:overlay.attributes('-alpha',0.34)
            except tk.TclError:pass
            try:overlay.attributes('-toolwindow',True)
            except tk.TclError:pass
            place_canvas_overlay(overlay,canvas_box)
            l,t,r,b=canvas_box;w=r-l;h=b-t
            expires_at=time.monotonic()+60.0
            board=tk.Canvas(overlay,bg='#123b2f',highlightthickness=0,cursor='plus')
            board.pack(fill='both',expand=True)
            frame=board.create_rectangle(2,2,max(3,w-3),max(3,h-3),outline='#48f0a2',width=5)
            board.create_text(w//2,h//2-24,text='DROP IMAGE HERE',fill='white',font=('Segoe UI',18,'bold'))
            board.create_text(w//2,h//2+10,text='Google Images / Chrome / Edge / image file',fill='#d7ffe9',font=('Segoe UI',10,'bold'))
            board.create_text(w//2,h//2+34,text='Release = import → verify → start drawing',fill='#d7ffe9',font=('Segoe UI',10))
            board.create_text(10,10,anchor='nw',text='Esc = cancel · expires after 60 s',fill='white',font=('Segoe UI',9,'bold'))

            def position(_event):
                if (self.closing or self.activity or self.smart_drop_overlay is not overlay
                        or time.monotonic()>=expires_at or not point_in_canvas(event_screen_point(_event),canvas_box)):
                    return 'none'
                try:board.itemconfigure(frame,outline='#7bffc1',width=7)
                except tk.TclError:pass
                try:self.smart_drop_in_text.set('Image detected over the game canvas — release to import and start drawing.')
                except Exception:pass
                return 'copy'

            def dropped(event):
                if (self.closing or self.activity or self.smart_drop_overlay is not overlay
                        or time.monotonic()>=expires_at or self.stop.is_set()):
                    return 'none'
                try:
                    point=event_screen_point(event)
                    if not point_in_canvas(point,canvas_box):
                        raise ValueError('Release the image inside the highlighted canvas, away from its edge.')
                    try:split_items=self.root.tk.splitlist(event.data)
                    except Exception:split_items=()
                    from CanvasDropPayload import parse_canvas_drop
                    dropped_source=parse_canvas_drop(event.data,split_items=split_items)
                    DrawBotApp._close_smart_drop_overlay(self,'image accepted')
                    # Lock the exact detector result for the import. One-Click
                    # re-verifies canvas/palette again before native input.
                    self._invalidate_target_lock('Game Canvas Drop changed the target canvas',disarm=True)
                    self.corners=[(l,t),(r,b)];self.saved_area=[(l,t),(r,b)];self.canvas_anchor_detection=None
                    self.browser_drawing_region=None  # The user dropped on this newly highlighted full canvas.
                    self.target_window=(int(meta['handle']),tuple(map(int,meta['rect'])))
                    self.target_client_rect=tuple(map(int,meta['client_rect']));self.target_dpi=meta.get('dpi')
                    self.small_test_passed=False;self.color_session_cache.clear();self.browser_auto_calibration_success=False
                    confidence=float((payload or {}).get('canvas_confidence',0) or 0)
                    self.area_text.set(f'✓ Canvas Drop target {w} × {h} px · confidence {confidence*100:.0f}%')
                    self.smart_drop_in_text.set('Image accepted on the game canvas. Loading it, then re-verifying canvas/palette before auto-start.')
                    log_event(
                        f'Game Canvas Drop accepted kind={dropped_source.kind!r} label={dropped_source.label!r} '
                        f'point={point!r} canvas={canvas_box!r} confidence={confidence:.3f}.')
                    loaded=self.load_source(
                        dropped_source.source,dropped_source.label,action=None,one_click_force=True)
                    if loaded is False:
                        raise ValueError('The image could not be queued because Image Draw Bot is busy.')
                    self.status.set('Canvas image accepted. Loading → browser verification → automatic drawing start.')
                    return 'copy'
                except Exception as error:
                    self.status.set(f'Game Canvas Drop failed safely: {error}')
                    self.smart_drop_in_text.set('Drop failed. Drag the image itself from Google/Chrome or use a local PNG/JPG/WEBP/BMP.')
                    log_event(f'Game Canvas Drop failed safely: {error!r}')
                    return 'none'

            overlay.drop_target_register(DND_FILES,DND_TEXT)
            overlay.dnd_bind('<<DropPosition>>',position)
            overlay.dnd_bind('<<DropEnter>>',position)
            overlay.dnd_bind('<<Drop>>',dropped)
            overlay.dnd_bind('<<DropLeave>>',lambda _e:(board.itemconfigure(frame,outline='#48f0a2',width=5),'copy')[1])
            overlay.bind('<Escape>',lambda _e:(DrawBotApp._close_smart_drop_overlay(self,'Esc'),self.status.set('Game Canvas Drop cancelled.')))
            try:overlay.focus_force()
            except tk.TclError:pass
            self.status.set('Game Canvas Drop armed for 60 s. Drag an image from Google Images/Chrome/Edge and release it directly on the highlighted game canvas.')
            self.smart_drop_in_text.set('Canvas is listening for one image drop. A valid drop will auto-start the supported browser drawing flow.')
            DrawBotApp._cancel_after_attr(self,'smart_drop_timeout_after')
            try:self.smart_drop_timeout_after=self.root.after(60_000,self._expire_smart_drop_overlay)
            except (tk.TclError,RuntimeError):self.smart_drop_timeout_after=None
            log_event(f'Game Canvas Drop overlay opened: canvas={canvas_box!r} confidence={float((payload or {}).get("canvas_confidence",0) or 0):.3f}.')
            return True
        except Exception:
            DrawBotApp._close_smart_drop_overlay(self,'overlay creation failed')
            raise

    def drop_image(self,event,drop_to_draw=False):
        """Import a local file or browser-dragged image/URL.

        Normal window drops remain import-only. Dropping on one of Image Draw Bot's
        preview canvases is a stronger gesture and may auto-start a supported
        browser target. Dropping on the dedicated game-canvas overlay always
        uses the separate one-shot Browser One-Click path.
        """
        for name in ('original_canvas','result_canvas','quantized_target_canvas','delta_e_canvas','detail_zoom_canvas','safety_canvas','safety_debug_canvas','stroke_canvas','fill_canvas','color_canvas','coverage_canvas','accuracy_error_canvas'):
            canvas=getattr(self,name,None)
            if canvas is not None:
                try:canvas.configure(bg='#131a25')
                except tk.TclError:pass
        if self.activity or self.closing:return 'none'
        try:
            try:split_items=self.root.tk.splitlist(event.data)
            except Exception:split_items=()
            from CanvasDropPayload import parse_canvas_drop
            dropped=parse_canvas_drop(event.data,split_items=split_items)
            action=action_for_import(armed=DrawBotApp._manual_drop_in_armed(self))
            one_click_force=False
            if drop_to_draw and action is None:
                if DrawBotApp._browser_one_click_supported(self):
                    # A direct preview-canvas drop is explicit one-shot
                    # authorization for the browser verification/start flow.
                    one_click_force=True
                    self.status.set('Canvas drop accepted. Image Draw Bot will verify the browser canvas/palette and start drawing when safe.')
                    log_event(f'Direct Image Draw Bot canvas drop authorized Browser One-Click: kind={dropped.kind!r}.')
                elif self.game.get()!='Microsoft Paint':
                    if DrawBotApp.arm_manual_drop_in(self):
                        action=DROP_IN_ACTION
                        log_event('Direct canvas drop armed one-shot Drop-In Start.')
                    else:
                        log_event('Direct canvas drop imported without auto-start because target setup was not ready.')
            if one_click_force:
                loaded=self.load_source(dropped.source,dropped.label,action=action,one_click_force=True)
            else:
                loaded=self.load_source(dropped.source,dropped.label,action=action)
            if loaded is False:
                raise ValueError('The image could not be queued because Image Draw Bot is busy.')
        except (ValueError,tk.TclError,OSError) as error:
            self.status.set(str(error));return 'none'
        return 'copy'

    def update_guesses(self):
        if not hasattr(self,'guess_list') or getattr(self,'closing',False):return
        from WordGuesser import find_candidates
        from WordHelperResults import results_for
        results=results_for(self)
        try:
            matches=find_candidates(self.guess_words,self.guess_pattern.get(),self.guess_length.get())
        except ValueError as error:
            return results.set_error(str(error))
        return results.set_matches(matches)

    def import_words(self):
        if self.activity:return
        path=filedialog.askopenfilename(filetypes=[('Word list','*.txt')])
        if not path:return
        try:
            from WordGuesser import MAX_WORD_LIST_BYTES,load_words
            words=load_words(Path(path))
            text='\n'.join(words)+'\n'
            if len(text.encode('utf-8'))>MAX_WORD_LIST_BYTES:
                raise ValueError('The normalized word list can be at most 2 MB.')
            atomic_write_text(DATA_DIR/'guess-words.txt',text)
            self.guess_words=words
            self.word_source.set(f'{len(self.guess_words)} words · {Path(path).name}')
            self.update_guesses()
        except (OSError,ValueError) as error:self.guess_result.set(str(error))

    def copy_guess(self):
        selection=self.guess_list.curselection()
        if selection:
            self.root.clipboard_clear();self.root.clipboard_append(self.guess_list.get(selection[0]));self.status.set('Word copied.')

    def open_file(self):
        if self.activity or self.closing or getattr(self,'pending_clear_drawing',None) is not None:return
        from CanvasDropPayload import IMAGE_FILE_PATTERNS
        path=filedialog.askopenfilename(filetypes=[('Images',IMAGE_FILE_PATTERNS),('All files','*.*')])
        if path:
            self.load_source(path,Path(path).name,action=action_for_import(armed=DrawBotApp._manual_drop_in_armed(self)))

    def remove_image_background(self):
        if self.closing:return False
        if self.activity:
            self.status.set('Finish or stop the current operation before removing the background.')
            return False
        if self.original is None:
            self.status.set('Load an image before removing its background.')
            return False
        source=self.original.copy()
        self.status.set('Removing border-connected background…')
        log_event(f'Background removal requested: size={source.size}.')
        def work():
            from BackgroundRemoval import remove_background
            with closing(source):
                result=remove_background(source,mode='Auto',strength='Balanced',cancelled=self.stop.is_set)
            if self.stop.is_set():
                result.image.close()
                raise InterruptedError()
            self.events.put(('background_removed',result))
        started=False
        try:
            started=bool(self.begin_worker('background-remove',work,cleanup=source.close))
            return started
        finally:
            if not started:source.close()

    def undo_background_removal(self):
        if self.activity or self.closing:return False
        from ImageFormatInfo import image_label
        previous=self.background_removal_original
        if previous is None:
            self.status.set('No background-removal change to undo.')
            return False
        DrawBotApp._cancel_browser_one_click(self,'background removal undone')
        self.original=previous;self.background_removal_original=None;self.background_removal_meta=None
        DrawBotApp._clear_source_time_feedback(self)
        self.plan=None;DrawBotApp._clear_render_resume(self,'background removal undone')
        self.file_label.set(image_label(self.original,'Background removal undone'))
        self._mark_plan_stale('Background removal undone. Build preview to update ETA.')
        self.show_previews();self._schedule_recovery_checkpoint(include_image=True,delay=40)
        self._maybe_auto_preview(delay=500,reason='background-removal-undo')
        log_event('Background removal undone.')
        return True

    def save_png_copy(self):
        if self.closing:return False
        if self.activity:
            self.status.set('Finish or stop the current operation before exporting PNG.')
            return False
        if self.original is None:
            self.status.set('Load an image before exporting PNG.')
            return False
        source=self.original
        path=filedialog.asksaveasfilename(title='Save PNG',defaultextension='.png',
            filetypes=[('PNG image','*.png')])
        if not path:return False
        if self.closing or self.activity or self.original is not source:return False
        snapshot=source.copy();self.status.set('Saving PNG…')
        def work():
            from BackgroundRemoval import png_export_ready
            from RuntimePaths import atomic_binary_writer
            with closing(snapshot):
                if self.stop.is_set():raise InterruptedError()
                with closing(png_export_ready(snapshot)) as ready:
                    with atomic_binary_writer(Path(path),cancelled=self.stop.is_set) as stream:
                        ready.save(stream,format='PNG',optimize=True)
            self.events.put(('png_saved',path))
        started=False
        try:
            started=bool(self.begin_worker('png-export',work,cleanup=snapshot.close))
            return started
        finally:
            if not started:snapshot.close()

    def upscale_dialog(self):
        if self.activity or self.closing: return
        if self.original is None:
            self.status.set('Load an image before upscaling.')
            return
        import customtkinter as ctk
        from UiCompatibility import scoped_toplevel
        from UiKeyboardNavigation import KeyboardButton,KeyboardOptionMenu
        from ImageUpscale import suggested_factor,upscale_size
        DrawBotApp._cancel_browser_one_click(self,'image editing')
        DrawBotApp._disarm_manual_drop_in(self,'image editing')
        source=self.original
        dialog=scoped_toplevel(self.root)
        dialog.title('Upscale image')
        dialog.transient(self.root)
        suggested=suggested_factor(source.size)
        factor=tk.StringVar(value='4×' if suggested==4 else '2×')
        method=tk.StringVar(value='Smooth')
        hint=tk.StringVar()
        ctk.CTkLabel(dialog,text=f'Image: {source.width} × {source.height}\n'+(f'Suggested: {suggested}×' if suggested>1 else 'Already reasonably large; upscaling may not help.')).pack(padx=24,pady=14)
        def update(*args):
            try:
                size=upscale_size(source.size,int(factor.get()[0]))
                hint.set(f'Result: {size[0]} × {size[1]} · {size[0]*size[1]/1e6:.1f} MP')
                apply_button.configure(state='normal')
            except ValueError as error:
                hint.set(str(error));apply_button.configure(state='disabled')
        factor_menu=KeyboardOptionMenu(dialog,variable=factor,values=['2×','4×'],command=update)
        factor_menu.pack(pady=5)
        method_menu=KeyboardOptionMenu(dialog,variable=method,values=['Smooth','Pixel art'])
        method_menu.pack(pady=5)
        ctk.CTkLabel(dialog,textvariable=hint,wraplength=380).pack(padx=24,pady=8)
        ctk.CTkLabel(dialog,text='Smooth: photos and illustrations. Pixel art: sharp blocks.\nNo AI: missing detail cannot be recovered.\nDrawing size is still controlled by your selected canvas.',wraplength=380).pack(padx=24,pady=8)
        def apply():
            scale=int(factor.get()[0]);selected_method=method.get()
            dialog.destroy()
            DrawBotApp._start_upscale(self,source,scale,selected_method)
        apply_button=KeyboardButton(dialog,text='Upscale image',command=apply)
        apply_button.pack(pady=(8,16))
        update()
        def dismiss(event=None):
            dialog.destroy()
            return 'break'
        dialog.bind('<Escape>',dismiss)
        # Selectors consume Escape locally for their popups. When the selector
        # itself has focus, Escape still dismisses this editing dialog.
        for selector in (factor_menu,method_menu):
            tk.Misc.bind(selector,'<KeyPress-Escape>',dismiss,add='+')
        dialog.wait_visibility();dialog.grab_set()

    def _start_upscale(self,source,scale,method):
        if self.closing or self.activity or self.original is not source:
            if not self.closing:self.status.set('Image or operation changed. Open Upscale again when ready.')
            return False
        from ImageUpscale import upscale_image
        def work():
            result=upscale_image(source,scale,method,self.stop.is_set)
            if self.stop.is_set():
                result.close()
                raise InterruptedError()
            self.events.put(('upscaled',(result,source)))
        return bool(self.begin_worker('upscale',work))

    def undo_upscale(self):
        if self.activity or self.closing: return
        previous=getattr(self,'upscale_original',None)
        if previous is None:
            self.status.set('No upscaling to undo for this image.')
            return
        DrawBotApp._cancel_browser_one_click(self,'undo upscaling')
        DrawBotApp._disarm_manual_drop_in(self,'undo upscaling')
        DrawBotApp._handle_event(self,'upscaled',(previous,None))

    def paste_shortcut(self,event=None):
        # Text fields retain native paste; elsewhere Ctrl+V imports an image.
        if event:
            widget=getattr(event,'widget',None)
            if isinstance(widget,str):
                try:widget=self.root.nametowidget(widget)
                except (KeyError,tk.TclError):return
            if isinstance(widget,ttk.Combobox):
                try:
                    if not widget.instate(['readonly']) or widget.instate(['disabled']):return
                except (tk.TclError,RuntimeError):return
                self.paste_image()
                return 'break'
            if isinstance(widget,(tk.Entry,ttk.Entry,ttk.Combobox,tk.Text,tk.Spinbox,ttk.Spinbox)):
                return
        self.paste_image()
        return 'break'

    def paste_image(self):
        if not DrawBotApp._profile_action_ready(self):return
        from PIL import Image,ImageGrab
        try:
            content=ImageGrab.grabclipboard()
            if isinstance(content,Image.Image):
                if content.width*content.height>25_000_000:
                    raise ValueError('The image is too large. Choose an image up to 25 megapixels.')
                action=action_for_import(armed=DrawBotApp._manual_drop_in_armed(self))
                return DrawBotApp._queue_clipboard_bitmap(self,content,action)
            elif isinstance(content,list) and content:
                from CanvasDropPayload import parse_canvas_drop
                source=parse_canvas_drop('',split_items=content)
                self.load_source(source.source,source.label,action=action_for_import(armed=DrawBotApp._manual_drop_in_armed(self)))
            else:
                from ClipboardImport import parse_text_source
                source=parse_text_source(self.root.clipboard_get())
                if source.kind=='url':
                    self.url.set(source.source);self.fetch_url()
                else:
                    self.load_source(source.source,source.label,
                        action=action_for_import(armed=DrawBotApp._manual_drop_in_armed(self)))
        except (OSError,ValueError,tk.TclError) as error:
            self.status.set(f'Could not paste. Copy an image first. {error}')

    def _queue_clipboard_bitmap(self,content,action):
        if not DrawBotApp._profile_action_ready(self):return False
        self.status.set('Preparing clipboard image…')
        def work():
            from ClipboardImport import prepare_bitmap
            prepared=prepare_bitmap(content,cancelled=self.stop.is_set)
            try:
                if self.stop.is_set():raise InterruptedError()
                self.events.put(('pasted',(prepared,action)))
            except BaseException:
                prepared.close()
                raise
        return bool(self.begin_worker('load',work))

    def capture_screen(self):
        if not DrawBotApp._profile_action_ready(self):return False
        if len(self.corners)!=2:
            self.status.set('Select the drawing area first.');return
        area=self.area()
        def work():
            for second in (3,2,1):
                self.events.put(('status',f'Capturing the drawing area in {second} s. Move this window aside.'))
                if self.stop.wait(1):raise InterruptedError()
            self.events.put(('screen',grab_area(area)))
        self.begin_worker('screen',work)

    def display_screen(self,image):
        if self.closing:
            image.close();return False
        from PIL import ImageTk
        try:
            window=tk.Toplevel(self.root)
        except BaseException:
            image.close();raise
        window.title('Captured drawing area')
        window.bind('<Destroy>',lambda event:image.close() if event.widget is window else None,add='+')
        try:
            with closing(image.copy()) as view:
                view.thumbnail((800,480))
                photo=ImageTk.PhotoImage(view)
        except BaseException:
            try:window.destroy()
            except (tk.TclError,RuntimeError):pass
            image.close()
            raise
        label=ttk.Label(window,image=photo);label.image=photo;label.pack(padx=12,pady=12)
        ttk.Label(window,text='Check that the correct drawing area is selected. This is a screenshot, not automatic application recognition.').pack(padx=12)
        def use():
            if not DrawBotApp._profile_action_ready(self):return False
            DrawBotApp._cancel_browser_one_click(self,'source replaced by screen image')
            self._suppress_recovery=False;self.original=image.convert('RGBA');self.plan=None;self.file_label.set('Image from screen')
            DrawBotApp._clear_source_time_feedback(self)
            self.subject_region=None;self.upscale_original=None
            self.background_removal_original=None;self.background_removal_meta=None
            if hasattr(self,'subject_hint'):self.subject_hint.set('Auto: simple background or transparent PNG. Mark busy photos.')
            DrawBotApp._clear_render_resume(self,'new screen image')
            window.destroy();self._mark_plan_stale('Screen image captured. Press Build preview when ready.');self.show_previews();self._schedule_recovery_checkpoint(include_image=True,delay=40);self._maybe_auto_preview(delay=900, reason='screen-image')
        def save():
            return DrawBotApp._save_captured_png(self,image)
        ttk.Button(window,text='Use as source image',command=use).pack(side='left',padx=12,pady=12)
        ttk.Button(window,text='Save screenshot',command=save).pack(side='left',padx=12)
        ttk.Button(window,text='Close',command=window.destroy).pack(side='right',padx=12)

    def _save_captured_png(self,image):
        if not DrawBotApp._profile_action_ready(self):return False
        path=filedialog.asksaveasfilename(defaultextension='.png',filetypes=[('PNG','*.png')])
        if not path or not DrawBotApp._profile_action_ready(self):return False
        try:snapshot=image.copy()
        except (ValueError,OSError):
            self.status.set('The captured image is no longer available. Capture the area again.');return False
        def work():
            from RuntimePaths import atomic_binary_writer
            with closing(snapshot):
                with atomic_binary_writer(Path(path),cancelled=self.stop.is_set) as stream:
                    snapshot.save(stream,format='PNG')
            self.events.put(('png_saved',path))
        started=False
        try:
            started=bool(self.begin_worker('png-export',work,cleanup=snapshot.close))
            return started
        finally:
            if not started:snapshot.close()

    def record_screen(self):
        if not DrawBotApp._profile_action_ready(self):return False
        if len(self.corners)!=2:
            self.status.set('Select the drawing area first.');return
        area=tuple(self.area())
        profile=getattr(self,'_active_profile_name',None)
        path=filedialog.asksaveasfilename(defaultextension='.gif',filetypes=[('Animated GIF','*.gif')],initialfile='ImageDrawBot-recording.gif')
        if not path:return
        if (not DrawBotApp._profile_action_ready(self) or
                getattr(self,'_active_profile_name',None)!=profile or
                len(self.corners)!=2 or tuple(self.area())!=area):return False
        def work():
            for second in (3,2,1):
                self.events.put(('status',f'Recording starts in {second} s. Move this window away from the drawing area.'))
                if self.stop.wait(1):raise InterruptedError()
            frames=[];durations=[]
            try:
                started=time.monotonic()
                for index in range(120):
                    if self.stop.is_set() or time.monotonic()-started>=30:break
                    tick=time.monotonic()
                    frame=grab_area(area)
                    try:
                        frame.thumbnail((800,500))
                        captured=frame.quantize(colors=128)
                    finally:
                        frame.close()
                    try:
                        self.events.put(('status',f'● RECORDING {time.monotonic()-started:.0f}/30 s • STOP/Esc ends and saves the GIF'))
                        self.stop.wait(max(0,.25-(time.monotonic()-tick)))
                        duration=max(20,(time.monotonic()-tick)*1000)
                        from ScreenRecording import append_recorded_frame
                        if append_recorded_frame(frames,durations,captured,duration):captured=None
                    finally:
                        if captured is not None:captured.close()
                if not frames:raise InterruptedError()
                self.events.put(('status','Saving recording…'))
                from ScreenRecording import save_gif_atomic
                destination=Path(path)
                save_gif_atomic(destination,frames,durations)
            finally:
                for frame in frames:frame.close()
            self.events.put(('terminal_status',('record',f'Recording saved: {destination.name}')))
        return bool(self.begin_worker('record',work))

    def paste_url(self):
        try:self.url.set(self.root.clipboard_get().strip())
        except tk.TclError:self.status.set('The clipboard does not contain text. Copy an image URL first.')

    def fetch_url(self):
        source=self.url.get().strip()
        from CanvasDropPayload import _is_http_url
        if not _is_http_url(source):
            self.status.set('Paste an image URL beginning with https:// and click Load.');return
        self.load_source(source,'Image from URL',action=action_for_import(armed=DrawBotApp._manual_drop_in_armed(self)))

    def _profile_action_ready(self):
        """Do not snapshot or act on a partially selected profile context."""
        return not (self.activity or self.closing or
                    getattr(self,'pending_clear_drawing',None) is not None or
                    getattr(self,'profile_change_after',None) is not None or
                    getattr(self,'profile_change_in_progress',False))

    def begin_worker(self,activity,task,*,reset_stop=True,cleanup=None):
        """Run one task; optional resource cleanup also runs if Stop skips it.

        Cleanup runs on the worker and must not touch Tk. The caller still owns
        its resources when this returns False or raises during thread startup.
        """
        if not DrawBotApp._profile_action_ready(self):
            log_event(f'Worker {activity} not started: busy={self.activity!r} closing={self.closing!r}.')
            return False
        if not reset_stop and self.stop.is_set():
            log_event(f'Worker {activity} not started: its preflight was stopped.')
            return False
        # Accept the new request before native preparation. An Esc received
        # during window construction/hiding belongs to this operation and must
        # survive the handoff, just like callers with their own preflight.
        if reset_stop:self.stop.clear()
        if activity != 'result-recheck':
            DrawBotApp._finish_result_recheck(self)
        recheck_worker_request = (getattr(self, 'result_recheck_request', None)
                                  if activity == 'result-recheck' else None)
        request=getattr(self,'browser_one_click_request',None)
        browser_worker_request=None
        if (activity=='browser-one-click-setup' and isinstance(request,dict) and
                request is getattr(self,'browser_one_click_worker_request',None) and
                request['phase']=='setup' and not request['cancelled'].is_set()):
            browser_worker_request=request
        elif not (activity=='one-click-verify' and isinstance(request,dict) and
                  not request['auto_start'] and request['phase']=='verifying' and
                  not request['cancelled'].is_set()):
            DrawBotApp._cancel_browser_one_click(self,'another operation started')
        DrawBotApp._cancel_after_attr(self,'preview_after')
        DrawBotApp._cancel_after_attr(self,'preview_render_after')
        from ScreenTaskWindow import ScreenTaskWindow, SCREEN_ACTIVITIES
        screen_window=ScreenTaskWindow(getattr(self,'root',None))
        def work():
            started=time.monotonic()
            try:
                if activity in SCREEN_ACTIVITIES and self.stop.wait(.30):raise InterruptedError()
                if self.stop.is_set():raise InterruptedError()
                task()
            except InterruptedError as error:
                if activity=='draw':
                    _state=getattr(self,'start_state_machine',None)
                    if _state is not None and getattr(_state,'state',None) not in ('COMPLETED','ABORTED'):
                        try:_state.transition('ABORTED',str(error) or 'drawing interrupted')
                        except Exception:pass
                log_event(f'Worker {activity} interrupted after {time.monotonic()-started:.3f} s: {error!r}')
                self.events.put(('status',str(error) or 'Cancelled. No automatic restart.'))
            except Exception as error:
                if activity=='draw':
                    _state=getattr(self,'start_state_machine',None)
                    if _state is not None and getattr(_state,'state',None) not in ('COMPLETED','ABORTED'):
                        try:_state.transition('ABORTED',str(error))
                        except Exception:pass
                log_error(f'Worker {activity} failed after {time.monotonic()-started:.3f} s: {error!r}',
                          category=f'worker:{activity}', exc_info=True)
                self.events.put(('terminal_status',(activity,f'Operation failed: {error}')))
            else:
                log_event(f'Worker {activity} finished in {time.monotonic()-started:.3f} s.')
            finally:
                if cleanup is not None:
                    try:cleanup()
                    except Exception as cleanup_error:
                        log_event(f'Worker {activity} resource cleanup failed: {cleanup_error!r}')
                completion=(activity,browser_worker_request) if browser_worker_request is not None else activity
                if recheck_worker_request is not None:completion=(activity,recheck_worker_request)
                self.events.put(('done',completion))
        try:
            if activity in SCREEN_ACTIVITIES:screen_window.hide()
            self.screen_task_window=screen_window
            self._worker_terminal_status=None
            self.set_busy(activity)
            log_event(f'Worker {activity} started.')
            self.worker=threading.Thread(target=work,daemon=True,name=f'imagedrawbot-{activity}')
            self.worker.start()
        except Exception as error:
            self.worker=None
            DrawBotApp._request_stop(self)
            try:self.set_busy(None)
            except Exception as cleanup_error:
                log_event(f'Worker startup UI cleanup failed: {cleanup_error!r}')
            self.activity=None
            try:screen_window.restore()
            except Exception as cleanup_error:
                log_event(f'Worker startup window restoration failed: {cleanup_error!r}')
            log_error(f'Worker {activity} could not start: {error!r}', category='worker-start', exc_info=True)
            raise
        return True

    def load_source(self,source,label,action=None,_from_sync=False,one_click_force=False):
        action=normalize_drop_in_action(action) if action is not None else None
        if (not _from_sync and action==DROP_IN_ACTION and
                drop_in_should_wait(activity=getattr(self,'activity',None),phase=getattr(self,'drop_in_sync_phase',None))):
            return DrawBotApp._queue_pending_drop_in_import(self,source,label,action)
        if not DrawBotApp._profile_action_ready(self):
            log_event(f'Image load deferred/rejected: label={label!r} busy={self.activity!r} closing={self.closing!r}.')
            if action==DROP_IN_ACTION and not _from_sync:
                return DrawBotApp._queue_pending_drop_in_import(self,source,label,action) if drop_in_should_wait(activity=self.activity,phase=getattr(self,'drop_in_sync_phase',None)) else False
            return False
        self.status.set('Loading image…')
        log_event(f'Image load requested: {label!r}.')
        def work():
            image=load_image(source,self.stop.is_set)
            try:
                if self.stop.is_set():raise InterruptedError()
                log_event(f'Image loaded: size={image.size} label={label!r}.')
                self.events.put(('loaded',(image,label,action,bool(one_click_force))))
            except BaseException:
                # The decoder transfers its owned result only after enqueue.
                # A late Stop or publication failure still belongs to us.
                image.close()
                raise
        return bool(self.begin_worker('load',work))

    def _auto_preview_enabled(self):
        return getattr(getattr(self,'preview_mode',None),'get',lambda:'Manual')() != 'Manual'

    def _clear_source_time_feedback(self):
        """Retire the old source's timer display after accepting a replacement."""
        if getattr(self,'closing',False) or getattr(self,'activity',None) in ('draw','dry-run'):return
        for name,text in (
                ('draw_live_time_text','Drawing timer: starts when drawing begins.'),
                ('total_draw_time_text','Total draw time: —')):
            try:getattr(self,name).set(text)
            except (tk.TclError,AttributeError):pass

    def _clear_plan_feedback(self):
        """Invalidate projections and diagnostics, leaving runtime timers alone."""
        if self.closing:return
        for name,text in (
                ('draw_time_text','Estimated draw time appears after Build preview.'),
                ('preview_diagnostics_text','Preview diagnostics appear after Build preview.')):
            try:getattr(self,name).set(text)
            except (tk.TclError,AttributeError):pass

    def _mark_plan_stale(self, message='Settings changed. Press Build preview or Start Drawing when ready.'):
        DrawBotApp._cancel_after_attr(self,'preview_after')
        self.preview_generation=int(getattr(self,'preview_generation',0))+1
        self.needs_plan=False
        self.plan=None
        DrawBotApp._clear_plan_feedback(self)
        self.preview_dirty_reason=message
        self.small_test_passed=False
        DrawBotApp._invalidate_target_lock(self,'plan/setup became stale',disarm=True)
        if not self.closing:
            try:self.summary.set(message)
            except tk.TclError:pass
            if hasattr(self,'schedule_previews'):
                try:self.schedule_previews(delay=30)
                except (tk.TclError,RuntimeError,AttributeError):pass
            DrawBotApp._sync_mobile_preview(self)

    def _maybe_auto_preview(self, delay=900, reason='settings'):
        if self.activity or self.closing or self.original is None:
            return False
        stop=getattr(self,'stop',None)
        if stop is not None and stop.is_set():return False
        if reason == 'profile-change':
            log_event('Preview auto-start blocked after profile-change. Build preview is manual after profile switches.')
            return False
        if not self._auto_preview_enabled():
            # Manual mode is a hard lock: no queued preview callback is left behind.
            DrawBotApp._cancel_after_attr(self,'preview_after')
            log_event(f'Preview auto-start blocked by Manual mode. reason={reason!r}')
            return False
        DrawBotApp._cancel_after_attr(self,'preview_after')
        try:self.preview_after=self.root.after(delay,lambda:self.update_plan(user_initiated=False,reason=reason))
        except (tk.TclError,RuntimeError):self.preview_after=None;return False
        log_event(f'Auto preview scheduled: reason={reason!r} delay={delay}ms.')
        return True

    def reset_draw_time_calibration(self):
        if self.closing:return False
        if not DrawBotApp._profile_action_ready(self):
            self.status.set('Finish the current operation or profile change before resetting learned draw timing.')
            return False
        try:
            from DrawTimeCalibration import reset_profile
            opts=self.options()
            plan_options=(self.plan or {}).get('options') if isinstance(getattr(self,'plan',None),dict) else None
            if (isinstance(plan_options,dict) and plan_options.get('profile_key')
                    and plan_options.get('profile_key')==opts.get('profile_key')):
                # Planning resolves Auto style/tool/brush policy. Learning uses
                # that actual context, which can differ from raw UI options.
                opts=plan_options
            result=reset_profile(opts)
            self._mark_plan_stale('Learned timing reset. Build preview to recalculate this drawing with the default timing model.')
            self.draw_time_text.set('Learned draw timing reset for this profile. The next estimate will use the operation model until a real drawing completes.')
            log_event(f"Draw-time calibration reset: key={result.get('key')} existed={result.get('reset')}.")
            return True
        except Exception as error:
            self.status.set(f'Could not reset learned timing: {error}')
            return False

    def render_preset_changed(self,*args):
        if self.render_preset.get()=='Masterpiece':
            if self.time_budget_mode.get()!='Unlimited':self._before_master_time=self.time_budget_mode.get()
            self.time_budget_mode.set('Unlimited')
            self.status.set('Masterpiece uses unlimited drawing time. This cannot extend a game round.')
        elif hasattr(self,'_before_master_time'):
            if self.time_budget_mode.get()=='Unlimited':self.time_budget_mode.set(self._before_master_time)
            del self._before_master_time
        self.options_changed()

    def sketch_mode_changed(self):
        if self.activity or self.closing:return
        if self.outline.get():
            self.subject_focus.set('Off')
            self.render_style.set('Standard / pixel')
            self.brush_px.set('1')
            self.status.set('Black contour sketch enabled. Use a thin black pencil. Build preview before Start; no colour fills will be drawn.')
        elif self.game.get()!='Microsoft Paint' and uses_paint_color(self):
            # Current ink outside Paint requires contours. An explicit Off
            # choice must end that dependency before options normalizes it.
            self.paint_simple.set(False)
            self.status.set('Colour drawing restored. Verify the palette before Start.')
            self._schedule_paint_configuration_refresh()
            return
        self.options_changed()

    def subject_focus_changed(self, *args):
        if self.outline.get() and self.subject_focus.get() != 'Off':
            self.subject_focus.set('Off')
            self.status.set('Black contour sketch is active. Turn it off before enabling Subject focus.')
            self.options_changed()
            return
        if self.subject_focus.get() != 'Off':
            self.draw_quality.set('Pixel Accurate')
            self.status.set('Subject focus uses Pixel Accurate with the selected brush width. Match the target brush and check Coverage preview for details too narrow to draw before Start.')
        self.options_changed()

    def mark_subject(self):
        if self.activity or self.closing: return
        if self.original is None:
            self.status.set('Load an image first, then click Mark subject.')
            return
        from SubjectSelector import select_subject
        source=self.original
        def selected(region):
            if self.closing:return
            if self.activity or self.original is not source:
                self.status.set('Subject selection discarded because the image or operation changed. Mark the current image again.')
                return
            self.subject_region=region
            self.subject_hint.set('Marked rectangle: everything inside is included. Build preview to check.')
            if self.subject_focus.get()=='Off': self.subject_focus.set('Subject first')
            self.subject_focus_changed()
        select_subject(self.root,self.original,selected)

    def preview_subject(self):
        if self.activity or self.closing: return
        if self.original is None:
            self.status.set('Load an image first.')
            return
        from SubjectSelector import show_mask
        show_mask(self.root,self.original,self.subject_region)

    def reset_subject(self):
        if self.activity or self.closing: return
        self.subject_region=None
        self.subject_hint.set('Auto: simple background or transparent PNG. Mark busy photos.')
        self.options_changed()

    def options_changed(self,*args):
        if self.activity or self.closing or getattr(self,'profile_change_in_progress',False):return
        DrawBotApp._cancel_browser_one_click(self,'drawing settings changed')
        self._mark_plan_stale('Settings changed. Press Build preview to refresh the preview. Start Drawing builds the final plan manually.')
        if hasattr(self,'recovery_checkpoint_after'):
            DrawBotApp._schedule_recovery_checkpoint(self,delay=300)
        self._maybe_auto_preview(delay=1000, reason='settings-change')
        from NumericEntryCommit import sync_numeric_commits
        sync_numeric_commits(self)

    def request_preview(self):
        if self.original is None:
            self.status.set('Load an image before building a preview.')
            return None
        try:mode=validate_preview_mode(str(self.preview_mode.get()))
        except Exception:mode='Manual'
        # Manual / Auto full button presses are explicit and may spend more time
        # to mirror final Draw geometry. Auto light remains the opt-in fast approximation.
        return self.update_plan(user_initiated=True, reason='build-preview-button',full_detail=(mode!='Auto light'))

    def request_full_preview(self):
        return self.update_plan(user_initiated=True,reason='full-detail-preview',full_detail=True)

    def update_plan(self, user_initiated=False, reason='automatic',full_detail=False):
        self.preview_after=None
        if not DrawBotApp._profile_action_ready(self):
            return
        stop=getattr(self,'stop',None)
        if not user_initiated and stop is not None and stop.is_set():return
        self.preview_generation=int(getattr(self,'preview_generation',0))+1
        generation=self.preview_generation
        if self.original is None:
            if user_initiated:self.status.set('Load an image before building a preview.')
            return
        if not user_initiated and not self._auto_preview_enabled():
            log_event(f'Preview planning blocked in Manual mode. reason={reason!r}')
            return
        # A new explicit request can follow an earlier Stop, but any Esc
        # arriving during options/source preparation belongs to this request.
        # Clear the old signal here, never again at the worker handoff.
        if user_initiated:self.stop.clear()
        target_area=self.area()[2:] if len(self.corners)==2 else (640,400)
        preview_area=preview_area_for(target_area)
        try:
            # Preview generation is pure image planning. It must not require or
            # resolve screen-coordinate tool calibration. Tool actions are built
            # only inside an explicit Start/Test preflight.
            options=self.options()
        except ValueError as error:
            self.status.set(str(error));return
        detail_level=str(options.get('preview_detail_level') or 'Detailed')
        max_pixels,max_dimension={
            'Fast':(240_000,680),'Balanced':(320_000,760),
            'Detailed':(430_000,900),'Micro detail':(620_000,1080),
        }.get(detail_level,(430_000,900))
        try:
            from ReleaseStabilityHardening import apply_preview_memory_limits
            _limits=apply_preview_memory_limits(max_pixels,max_dimension,memory_budget_mb=options.get('ram_budget_mb'))
            max_pixels,max_dimension=_limits.resolved_pixels,_limits.resolved_dimension
            options=dict(options)
            options.setdefault('release_stability_meta',{})['preview_memory_limits']=_limits.as_options_meta()
        except Exception as _stability_error:
            log_event(f'Preview stopped by its memory guard: {_stability_error!r}')
            self.status.set(f'Preview cannot fit the selected memory budget: {_stability_error}')
            return
        preview_area=preview_area_for(target_area,max_pixels=max_pixels,max_dimension=max_dimension)
        preview_options=dict(options)
        preview_options['_preview_plan']=True
        preview_options['_target_area']=tuple(map(int,target_area))
        preview_options['_preview_area']=tuple(map(int,preview_area))
        # v1.0.30: Preview has its own bounded/cancellable planning pipeline.
        # Final drawing still receives the exact CPU/GPU/Extreme/color-layer settings.
        mode=getattr(getattr(self,'preview_mode',None),'get',lambda:'Manual')()
        preview_options['_preview_mode']=mode
        preview_options['max_seconds']=min(int(preview_options.get('max_seconds',180)),90 if user_initiated else 60)
        if mode=='Auto light' and preview_options.get('draw_quality') in ('GPU enhanced','Pixel Accurate'):
            preview_options['_final_draw_quality']=self.draw_quality.get()
            preview_options['draw_quality']='High likeness'
        try:
            preview_target, preview_target_meta = resolve_target_stroke_count(
                preview_options.get('target_stroke_count','Auto'),
                preview_options.get('target_stroke_custom','2500'),
                time_budget_mode=preview_options.get('time_budget_mode','Manual'),
                effective_time_seconds=int(preview_options.get('max_seconds',90)),
                speed=preview_options.get('speed','Balanced'),
                drawing_mode=preview_options.get('drawing_mode',SMART_PATH_MODE),
                preview=True)
            preview_options.update(preview_target_meta)
            preview_options['target_stroke_count_resolved']=preview_target
        except ValueError:
            preview_options['target_stroke_count_resolved']=1200 if mode=='Auto light' else None
        preview_options=preview_safe_options(preview_options,mode)
        if full_detail:
            from PreviewQuality import full_preview_options
            try:
                preview_options=full_preview_options(options,target_area)
            except ValueError as error:
                self.status.set(str(error));return
            preview_area=tuple(map(int,target_area))
        try:original=self.original.copy()
        except MemoryError:
            self.status.set('Not enough memory to build preview. Close other images or use a smaller source.');return
        def work():
            started=time.monotonic()
            requested=(preview_options.get('_preview_requested_planning_resolution'),
                       preview_options.get('_preview_requested_color_rendering'),
                       preview_options.get('_preview_requested_color_layers'))
            log_event(
                f'Preview planning started: reason={reason} mode={preview_options.get("_preview_mode")} '
                f'target={tuple(map(int,target_area))} preview={preview_area} quality={preview_options.get("draw_quality")} '
                f'color={preview_options.get("color_rendering")}/{preview_options.get("color_fidelity","Faithful")} safe_pipeline={not full_detail} requested_planning={requested[0]} '
                f'requested_color={requested[1]} requested_layers={requested[2]} {_resource_log_text(preview_options)}')

            def run_attempt(attempt_options, timeout):
                try:
                    from ReleaseStabilityHardening import PreviewAttemptGuard, merge_stability_meta, classify_preview_timeout
                    guard=PreviewAttemptGuard(timeout_seconds=float(timeout),external_cancelled=lambda:self.stop.is_set() or self.closing,label='preview planning')
                    merge_stability_meta(attempt_options, preview_attempt=guard.meta())
                    def preview_cancelled():
                        return guard.cancelled()
                    result=make_plan(original,preview_area,attempt_options,preview_cancelled)
                    if guard.cancelled():
                        merge_stability_meta(attempt_options, preview_attempt=guard.meta(), preview_timeout=classify_preview_timeout(float(timeout),timeout_seconds=float(timeout)))
                        return None
                    merge_stability_meta(attempt_options, preview_attempt=guard.meta())
                    return result
                except InterruptedError:
                    if self.stop.is_set() or self.closing:
                        raise
                    return None

            plan=run_attempt(preview_options,60 if full_detail else PREVIEW_PLAN_TIMEOUT_SECONDS)
            used_fallback=False
            if plan is None and not full_detail and not self.stop.is_set() and not self.closing:
                used_fallback=True
                fallback=preview_safe_options(preview_options,mode,fallback=True)
                fallback['_preview_plan']=True
                fallback['_preview_mode']=mode
                fallback['_target_area']=tuple(map(int,target_area))
                fallback['_preview_area']=tuple(map(int,preview_area))
                log_event(
                    f'Preview safe attempt exceeded {PREVIEW_PLAN_TIMEOUT_SECONDS:.0f}s; retrying fast fallback '
                    f'for up to {PREVIEW_FALLBACK_TIMEOUT_SECONDS:.0f}s. No mouse input is armed.')
                plan=run_attempt(fallback,PREVIEW_FALLBACK_TIMEOUT_SECONDS)
            if plan is None:
                if self.stop.is_set() or self.closing:
                    raise InterruptedError()
                elapsed=time.monotonic()-started
                log_event(f'Preview planning abandoned safely after {elapsed:.1f}s. target={tuple(map(int,target_area))} preview={preview_area}')
                self.events.put(('preview_timeout',(tuple(map(int,target_area)),preview_area)))
                return
            plan['target_area']=tuple(map(int,target_area))
            plan['preview_area']=tuple(map(int,preview_area))
            plan['preview_safe_pipeline']=not full_detail
            plan['full_detail_preview']=bool(full_detail)
            plan['preview_fallback_used']=bool(used_fallback)
            plan['preview_generation']=generation
            try:
                from DrawTimeEstimate import attach_draw_time_estimate
                # This worker exclusively owns the completed plan until the
                # queued result is adopted. Transfer this exact final estimate
                # once; Tk need not rescan every path and reload calibration.
                plan['_preview_time_estimate_ready']=attach_draw_time_estimate(plan)
            except Exception as error:
                log_event(f'Preview draw time projection skipped: {error!r}')
            plan['preview_elapsed_seconds']=round(time.monotonic()-started,3)
            log_event(f'Preview planning finished in {plan["preview_elapsed_seconds"]:.3f} s fallback={used_fallback}: {_plan_log_text(plan)}.')
            self.events.put(('planned',plan))
        # Historic v1.0.10 status string kept for release-test visibility: Planning optimized preview.
        self.status.set('Building preview…' if user_initiated else 'Planning lightweight auto preview…')
        started=False
        try:
            # Both automatic and explicit work preserve Esc received during
            # options/snapshot preparation or native worker setup.
            started=bool(self.begin_worker('preview',work,reset_stop=False,cleanup=original.close))
        finally:
            if not started:
                original.close()
                if self.stop.is_set() and not self.closing:self.status.set('Stopped.')

    def schedule_previews(self,event=None,delay=45):
        """Coalesce resize events before redrawing preview canvases.

        Tk can emit nested <Configure> events while a widget hierarchy is still
        settling. Drawing synchronously inside that callback caused a real
        RecursionError on Windows. Scheduling one render after the burst breaks
        that call chain and also avoids doing dozens of redundant redraws.
        """
        if self.closing:
            return
        DrawBotApp._cancel_after_attr(self,'preview_render_after')
        try:self.preview_render_after=self.root.after(delay,self._run_scheduled_previews)
        except (tk.TclError,RuntimeError):self.preview_render_after=None

    def _run_scheduled_previews(self):
        self.preview_render_after=None
        if not self.closing:self.show_previews()

    def show_previews(self):
        # Never re-enter a Tk canvas render. A synchronous <Configure> callback
        # can otherwise nest show_previews() until Python exhausts its stack.
        if self.closing or getattr(self,'preview_rendering',False):
            return
        self.preview_rendering=True
        try:
            from PIL import Image,ImageTk
            from PreviewNavigation import clear_viewport
            from PreviewBitmapCache import clear_bitmap,photo_for
            from PreviewViews import VIEW_SPECS,view_images
            photos=[]
            images=view_images(self);pairs=[]
            _shown_plan=self.plan if isinstance(getattr(self,'plan',None),dict) else {}
            _sketch_metrics=((_shown_plan.get('options') or {}).get('sketch_fill_meta') or {})
            for name,attr,_,_ in VIEW_SPECS:
                canvas=getattr(self,attr,None)
                if canvas is not None:pairs.append((canvas,images[name]))
            for canvas,im in pairs:
                try:
                    if not canvas.winfo_exists():
                        clear_bitmap(canvas);continue
                    if im is None:
                        clear_viewport(canvas);clear_bitmap(canvas)
                    if not canvas.winfo_ismapped():
                        canvas.delete('all');clear_bitmap(canvas)
                        continue
                    canvas.delete('all')
                    w,h=max(1,canvas.winfo_width()),max(1,canvas.winfo_height())
                    if im is None:
                        is_original=canvas is self.original_canvas
                        if is_original:
                            title='Drop your image here';hint='PNG, JPG, WEBP · drop on canvas to auto-start when setup is ready'
                        elif canvas is getattr(self,'quantized_target_canvas',None):
                            title='Quantized target';hint='Palette-mapped target before physical brush/execution simulation.'
                        elif canvas is getattr(self,'delta_e_canvas',None):
                            title='ΔE heatmap';hint='OKLab color distance from the original source. Dark = low error; bright = high error.'
                        elif canvas is getattr(self,'detail_zoom_canvas',None):
                            title='Detail zoom';hint='Build a preview with Detail zoom Auto/2x/4x. Boxes show source regions re-analyzed for micro-details; target app zoom is never changed.'
                        elif canvas is getattr(self,'safety_canvas',None):
                            title='Safety map';hint='CanvasGuard/Edge Behavior clipped, skipped and edge-follow paths will appear here.'
                        elif canvas is getattr(self,'safety_debug_canvas',None):
                            title='Safety debug overlay';hint='Exact drawn, clipped, skipped and edge-follow reasons will appear here.'
                        elif (canvas is getattr(self,'coverage_canvas',None)
                                and _sketch_metrics.get('pixel_metrics_status')=='not_calculated'):
                            title='Coverage not calculated'
                            hint='Final Sketch + Auto Fill coverage and plan-execution accuracy are not calculated. Simulated final, source-relative Accuracy error and ΔE still describe the final sequence.'
                        elif canvas in (getattr(self,'coverage_canvas',None),getattr(self,'accuracy_error_canvas',None)):
                            title='Available with Pixel Accurate'
                            hint='Choose Masterpiece for colour drawing, then build preview. This metric is not calculated for sketch mode.'
                        elif canvas is getattr(self,'stroke_canvas',None):
                            title='Stroke plan';hint='Planned brush paths will appear here.'
                        elif canvas is getattr(self,'fill_canvas',None):
                            title='Fill regions';hint='Safe Auto Fill regions will appear here.'
                        elif canvas is getattr(self,'color_canvas',None):
                            title='Color map';hint='A simplified source color map will appear here.'
                        elif canvas is getattr(self,'coverage_canvas',None):
                            title='Coverage map';hint='Pixel Accurate shows target coverage, missing pixels and brush spill here.'
                        elif canvas is getattr(self,'accuracy_error_canvas',None):
                            title='Accuracy error';hint='Source-relative error heatmap: highlights perceptual color, luminance and edge differences from the original image.'
                        else:
                            if self.original is None:
                                title='Drawing preview';hint='Select an image to generate a preview.'
                            else:
                                title='Preview not built';hint=getattr(self,'preview_dirty_reason','Press Build preview manually.') or 'Press Build preview manually.'
                        if w>250 and h>160:
                            cx,cy=w/2,h/2-45
                            canvas.create_oval(cx-25,cy-25,cx+25,cy+25,fill='#253d36',outline='')
                            canvas.create_line(cx,cy+11,cx,cy-10,fill='#98edce',width=2)
                            canvas.create_line(cx-7,cy-3,cx,cy-10,cx+7,cy-3,fill='#98edce',width=2)
                        canvas.create_text(w/2,h/2+2,text=title,fill='#f0f4fb',font=('Segoe UI',19,'bold'),justify='center',width=max(100,w-30))
                        canvas.create_text(w/2,h/2+38,text=hint,fill='#a6b2c5',font=('Segoe UI',11),justify='center',width=max(100,w-30))
                        continue
                    from PreviewNavigation import record_viewport
                    zoom=float(getattr(getattr(self,'preview_zoom',None),'get',lambda:0)())
                    viewport_size=(max(1,w-16),max(1,h-16))
                    pan=getattr(canvas,'_preview_pan',(0,0))
                    photo=photo_for(canvas,im,viewport_size,zoom,pan,make_photo=ImageTk.PhotoImage)
                    photos.append(photo);canvas.create_image(w/2,h/2,image=photo)
                    canvas._preview_photo=photo
                    record_viewport(canvas,im.size,viewport_size,zoom,pan)
                except (ValueError,TypeError,MemoryError,OverflowError,OSError,RuntimeError) as error:
                    clear_viewport(canvas);clear_bitmap(canvas)
                    log_event(f'Preview render failed safely: {type(error).__name__}: {error}')
                    try:
                        canvas.create_text(max(1,canvas.winfo_width())/2,max(1,canvas.winfo_height())/2,text='This view could not be rendered. Try Fit or rebuild preview.',fill='#f0f4fb',width=280)
                    except tk.TclError:
                        pass  # The canvas may have been destroyed during rendering.
                except tk.TclError as error:
                    clear_bitmap(canvas)
                    # A canvas can disappear while the application is closing or a
                    # tab is being rebuilt. That should not terminate the GUI.
                    log_event(f'Preview canvas redraw skipped after TclError: {error}')
            self.photos=photos
        finally:
            self.preview_rendering=False
        DrawBotApp._sync_mobile_preview(self)

    def _sync_mobile_preview(self):
        """Coalesce accepted source/plan changes on the image-owning Tk thread."""
        server=getattr(self,'mobile_preview_server',None)
        if self.closing or server is None or not server.running:return False
        if getattr(self,'mobile_preview_after',None) is not None:return False
        ticket=object();self.mobile_preview_ticket=ticket
        try:
            self.mobile_preview_after=self.root.after_idle(
                lambda:DrawBotApp._publish_mobile_preview(self,server,ticket))
            return True
        except (tk.TclError,RuntimeError):
            self.mobile_preview_ticket=None;self.mobile_preview_after=None
            return False

    def _publish_mobile_preview(self,server,ticket):
        if getattr(self,'mobile_preview_ticket',None) is not ticket:return False
        self.mobile_preview_ticket=None;self.mobile_preview_after=None
        if self.closing or server is not getattr(self,'mobile_preview_server',None) or not server.running:
            return False
        try:
            from PreviewViews import view_images
            views=view_images(self)
            return server.queue_images(original=views['Original'],preview=views['Simulated final'],
                                       safety=views['Safety map'])
        except Exception as error:
            log_event(f'Mobile Preview refresh failed safely: {type(error).__name__}')
            return False

    def _copy_mobile_preview_url(self):
        value=getattr(self,'mobile_preview_url',None)
        url=str(value.get() or '') if value is not None else ''
        if not url:
            self.status.set('Start Mobile Preview first.')
            return
        try:
            self.root.clipboard_clear();self.root.clipboard_append(url);self.root.update_idletasks()
            self.status.set('Mobile Preview address copied. Open it on a phone connected to the same Wi-Fi/LAN.')
        except tk.TclError as error:
            self.status.set(f'Could not copy Mobile Preview address: {error}')

    def stop_mobile_preview(self, *, quiet=False):
        DrawBotApp._cancel_mobile_preview_discovery(self)
        DrawBotApp._cancel_after_attr(self,'mobile_preview_after')
        self.mobile_preview_ticket=None
        from MobilePreviewDialog import close_mobile_preview_dialog
        close_mobile_preview_dialog(self)
        server=getattr(self,'mobile_preview_server',None)
        if server is not None:
            try:server.stop()
            except Exception as error:log_event(f'Mobile Preview stop failed safely: {error!r}')
        # Reuse one encoder owner on a later explicit restart. A Pillow native
        # encode may still be finishing; new server instances would multiply it.
        try:self.mobile_preview_url.set('')
        except (tk.TclError,AttributeError):pass
        try:self.mobile_preview_status.set('Mobile Preview is off · local network only.')
        except (tk.TclError,AttributeError):pass
        if not quiet and not self.closing:
            self.status.set('Mobile Preview stopped. The local preview address is no longer available.')
        log_event('Mobile Preview stopped.')

    def _cancel_mobile_preview_discovery(self, *, retire=False):
        """Release GUI-owned context on Tk; the resolver itself never joins."""
        request=getattr(self,'mobile_preview_request',None)
        if request is not None:request['cancel'].set()
        self.mobile_preview_request=None
        discovery=getattr(self,'mobile_preview_discovery',None)
        if discovery is not None:
            if retire:discovery.retire()
            else:discovery.cancel()
        if not getattr(self,'closing',False):
            server=getattr(self,'mobile_preview_server',None)
            status=getattr(self,'mobile_preview_status',None)
            if status is not None:
                status.set('Mobile Preview LIVE · same Wi-Fi/LAN required · auto-refresh 1s'
                    if server is not None and server.running else 'Mobile Preview is off · local network only.')

    def _mobile_preview_request_current(self,request,*,session=None,check_panel=True):
        if (request is None or self.closing or request is not getattr(self,'mobile_preview_request',None)
                or request['cancel'].is_set() or request['server'] is not getattr(self,'mobile_preview_server',None)):
            return False
        expected=request['session'] if session is None else session
        if request['server'].session_identity()!=expected:return False
        if not check_panel:return True
        panel=request['panel']
        return panel is None or (not panel.closed and getattr(self,'_mobile_preview_dialog',None) is panel)

    def _poll_mobile_preview_discovery(self):
        discovery=getattr(self,'mobile_preview_discovery',None)
        if discovery is None:return False
        request=getattr(self,'mobile_preview_request',None)
        if self.closing:
            DrawBotApp._cancel_mobile_preview_discovery(self,retire=True)
            return False
        if request is not None and not DrawBotApp._mobile_preview_request_current(self,request):
            DrawBotApp._cancel_mobile_preview_discovery(self)
        outcome=discovery.take()
        if outcome is None:return False
        ticket,kind,value=outcome
        request=getattr(self,'mobile_preview_request',None)
        if (request is None or request['cancel'] is not ticket
                or not DrawBotApp._mobile_preview_request_current(self,request)):
            return False
        if kind=='error':
            self.mobile_preview_request=None
            message=f'Could not refresh Mobile Preview addresses: {value}'
            self.mobile_preview_status.set(message)
            if not self.activity:self.status.set(message)
            log_event(message)
            return False
        server=request['server'];session=request['session'];started=False
        def discard_unadopted():
            current=getattr(self,'mobile_preview_request',None)
            adopted_elsewhere=(current is not None and current is not request and
                current['server'] is server and current['session']==session and not current['cancel'].is_set())
            if started and server.session_identity()==session and not adopted_elsewhere:
                server.stop()
        try:
            if not server.running:
                state=server.start(addresses=value);started=True
                log_event(f'Mobile Preview started locally on port {state.port}. No cloud service or telemetry is used.')
            else:
                state=server.refresh_addresses(addresses=value)
            session=(request['session'][0],state.port,state.token)
            if not state.running or not DrawBotApp._mobile_preview_request_current(self,request,session=session):
                discard_unadopted()
                if request is getattr(self,'mobile_preview_request',None):
                    DrawBotApp._cancel_mobile_preview_discovery(self)
                return False
            urls=server.urls()
            url=urls[0] if urls else f'http://127.0.0.1:{server.port}/{server.token}/'
            self.mobile_preview_url.set(url)
            self.mobile_preview_status.set('Mobile Preview LIVE · same Wi-Fi/LAN required · auto-refresh 1s')
            from MobilePreviewDialog import show_mobile_preview_dialog
            window=show_mobile_preview_dialog(self,server,url)
            if not DrawBotApp._mobile_preview_request_current(self,request,session=session):
                if request is getattr(self,'mobile_preview_request',None):
                    self.stop_mobile_preview(quiet=True)
                else:discard_unadopted()
                return False
            DrawBotApp._sync_mobile_preview(self)
            if window is not None and not self.activity:
                self.status.set('Mobile Preview is live. Open the local address on a phone connected to the same network.')
            return window
        except Exception as error:
            if DrawBotApp._mobile_preview_request_current(self,request,session=session,check_panel=False):
                self.stop_mobile_preview(quiet=True)
                message=f'Could not start Mobile Preview: {error}'
                self.mobile_preview_status.set(message)
                if not self.activity:self.status.set(message)
                log_event(f'Mobile Preview start failed safely: {error!r}')
            else:discard_unadopted()
            return False
        finally:
            if request is getattr(self,'mobile_preview_request',None):self.mobile_preview_request=None

    def show_mobile_preview(self):
        """Queue opt-in LAN discovery without blocking or borrowing drawing work."""
        if self.closing:return
        try:
            server=getattr(self,'mobile_preview_server',None)
            if server is None:
                server=MobilePreviewServer();self.mobile_preview_server=server
            discovery=getattr(self,'mobile_preview_discovery',None)
            if discovery is None:
                from MobilePreviewDiscovery import MobilePreviewDiscovery
                discovery=MobilePreviewDiscovery();self.mobile_preview_discovery=discovery
            previous=getattr(self,'mobile_preview_request',None)
            if previous is not None:previous['cancel'].set()
            panel=getattr(self,'_mobile_preview_dialog',None)
            if panel is not None and not panel.current():panel=None
            request=dict(cancel=threading.Event(),server=server,
                session=server.session_identity(),panel=panel)
            self.mobile_preview_request=request
            discovery.submit(request['cancel'])
            if request['cancel'].is_set():return
            self.mobile_preview_status.set('Finding local Mobile Preview addresses…')
            if not self.activity:self.status.set('Finding local Mobile Preview addresses… You can keep using Image Draw Bot.')
            return panel.window if panel is not None else None
        except Exception as error:
            DrawBotApp._cancel_mobile_preview_discovery(self)
            message=f'Could not start Mobile Preview: {error}'
            self.mobile_preview_status.set(message)
            if not self.activity:self.status.set(message)
            log_event(f'Mobile Preview discovery failed safely: {error!r}')

    def export_preview(self):
        if self.activity or self.closing:return False
        from PreviewViews import selected_export_view
        try:name,source,filename=selected_export_view(self)
        except (ValueError,tk.TclError) as error:
            self.status.set(str(error));return False
        path=filedialog.asksaveasfilename(title=f'Export {name}',defaultextension='.png',
            filetypes=[('PNG image','*.png')],initialfile=filename)
        if not path:return False
        if self.closing or self.activity:return False
        try:current_name,current_source,_=selected_export_view(self)
        except (ValueError,tk.TclError):return False
        if current_name!=name or current_source is not source:
            self.status.set('The preview changed. Select Export again to save the current view.');return False
        snapshot=source.copy()
        def work():
            from RuntimePaths import atomic_binary_writer
            with closing(snapshot):
                with atomic_binary_writer(Path(path),cancelled=self.stop.is_set) as stream:
                    snapshot.save(stream,format='PNG')
            self.events.put(('status',f'{name} saved as PNG.'))
        started=False
        try:
            started=bool(self.begin_worker('preview-export',work,cleanup=snapshot.close))
            return started
        finally:
            if not started:snapshot.close()

    def reuse_area(self):
        if not DrawBotApp._profile_action_ready(self) or not self.saved_area:return False
        previous=(self.corners,self.canvas_anchor_detection,self.target_window,
                  self.target_client_rect,getattr(self,'target_dpi',None))
        try:
            self.corners=[tuple(p) for p in self.saved_area]
            if min(self.area()[2:])<10:
                raise ValueError('The saved area is too small. Select a new one.')
            self.capture_target()
        except (OSError,ValueError,AttributeError,InterruptedError) as error:
            (self.corners,self.canvas_anchor_detection,self.target_window,
             self.target_client_rect,self.target_dpi)=previous
            self.status.set(str(error));return False
        self.area_text.set(f'✓ {self.area()[2]} × {self.area()[3]} px. Make sure the target application remains in the same position.')
        self.small_test_passed=False
        self._mark_plan_stale('Drawing area restored. Press Build preview or Safety preflight / Dry run when ready.')
        self.set_busy(None);self._maybe_auto_preview(delay=900, reason='reuse-area')
        return True

    def set_boundary(self):
        if not DrawBotApp._profile_action_ready(self):return
        from RegionPicker import select_region
        DrawBotApp._cancel_after_attr(self,'capture_job')
        self.stop.clear();self.set_busy('capture')
        log_event('Drawing-area selection started.')
        def apply_selected(box,image):
            left,top,right,bottom=map(int,box)
            width,height=right-left,bottom-top
            log_event(f'Drawing-area selected: box={(left,top,right,bottom)} size={(width,height)}')
            if width < 10 or height < 10:
                raise ValueError('The drawing area is too small. Select at least 10 × 10 pixels.')
            if width > 20000 or height > 20000:
                raise ValueError('The drawing area is unexpectedly large. Check Windows display scaling and select it again.')
            old=self.corners;old_anchor=self.canvas_anchor_detection;old_target=self.target_window;old_client=self.target_client_rect;old_dpi=self.target_dpi
            self.corners=[(left,top),(right,bottom)]
            try:
                from CanvasAnchorDetection import detect_canvas_anchors
                detected=detect_canvas_anchors(image)
                self.canvas_anchor_detection=detected.as_options()
                log_event(f'Canvas anchors detected: corners={detected.corner_count}/4 triangles={detected.triangle_count}/{detected.expected_triangles} confidence={detected.confidence:.3f}.')
            except Exception as anchor_error:
                self.canvas_anchor_detection=None
                log_event(f'Canvas anchor detection skipped; rectangle fallback remains active: {anchor_error!r}')
            try:
                self.capture_target()
                log_event(f'Drawing-area target captured safely: {self.target_window!r}')
            except Exception:
                self.corners=old;self.canvas_anchor_detection=old_anchor;self.target_window=old_target;self.target_client_rect=old_client;self.target_dpi=old_dpi
                raise
            self.saved_area=[tuple(p) for p in self.corners]
            self.small_test_passed=False;self.color_session_cache.clear()
            
            anchor_meta=(self.canvas_anchor_detection or {}).get('canvas_anchor_meta',{}) if isinstance(self.canvas_anchor_detection,dict) else {}
            tri_count=int(anchor_meta.get('triangle_count',0) or 0) if isinstance(anchor_meta,dict) else 0
            area_suffix=f'anchors 4/4 corners, {tri_count}/6 triangles'
            if self.game.get()=='Gartic Phone':
                try:
                    from GarticPhoneLayout import assess_canvas_size
                    from GarticEngineV2 import detect_gartic_canvas
                    gartic_layout=assess_canvas_size(width,height)
                    detected_canvas=detect_gartic_canvas(image,cancelled=self.stop.is_set)
                    if gartic_layout['likely']:
                        area_suffix += f" · Gartic canvas ✓ {gartic_layout['aspect']:.2f}:1"
                        log_event(f"Gartic Phone Engine v2 canvas geometry matched reference: aspect={gartic_layout['aspect']:.3f} confidence={gartic_layout['confidence']:.3f} detector={detected_canvas.confidence:.3f}.")
                    else:
                        area_suffix += f" · check Gartic canvas ({gartic_layout['aspect']:.2f}:1)"
                        log_event(f"Gartic Phone Engine v2 canvas geometry warning: selected aspect={gartic_layout['aspect']:.3f}, reference={gartic_layout['reference_aspect']:.3f}, detector={detected_canvas.confidence:.3f}.")
                except InterruptedError:
                    raise
                except Exception as layout_error:
                    log_event(f'Gartic Phone layout check skipped: {layout_error!r}')
            self.area_text.set(f'✓ {width} × {height} px · {area_suffix}')
            self.save_settings();self._schedule_recovery_checkpoint(delay=100);self.set_busy(None)
            # RegionPicker restores the main window immediately after this callback.
            # Do not auto-build a heavy plan in Manual mode; configuration must
            # never feel like drawing/planning has started by itself.
            self._mark_plan_stale('Drawing area saved. Press Build preview or Safety preflight / Dry run when ready.')
            self._maybe_auto_preview(delay=900, reason='area-selected')
            self.show_previews()
            self.status.set('Drawing area saved and target window locked. Preview is manual by default.')
            try:
                from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
                profile_key=PROFILES.get(self.game.get(),('',))[0]
                if profile_key in SUPPORTED_BROWSER_PROFILES:
                    self.browser_auto_text.set('Canvas selected · automatic browser palette setup will start now.')
                    selected_corners=tuple(self.corners)
                    job=[None]
                    def auto_setup():
                        if getattr(self,'capture_job',None)!=job[0]:return
                        self.capture_job=None
                        if (self.closing or self.activity or self.stop.is_set()
                                or tuple(self.corners)!=selected_corners
                                or PROFILES.get(self.game.get(),('',))[0]!=profile_key):return
                        self.auto_calibrate_browser_profile(automatic=True)
                    job[0]=self.root.after(450,auto_setup)
                    self.capture_job=job[0]
            except Exception as auto_error:
                log_event(f'Browser Auto Setup scheduling skipped: {auto_error!r}')
        def selected(box,image):
            try:
                if self.closing or self.stop.is_set():raise InterruptedError('Selection cancelled.')
                apply_selected(box,image)
            finally:
                # RegionPicker transfers the delivered crop to its consumer.
                # This path analyses it synchronously and retains no raster.
                image.close()
        def failed(message):
            log_event(f'Drawing-area selection failed/aborted: {message}')
            if not self.closing:self.set_busy(None);self.status.set(message)
        select_region(self.root,selected,failed,cancelled=lambda:self.closing or self.stop.is_set())

    def refresh_exact_color_status(self):
        try:
            key=PROFILES[self.game.get()][0]
            custom=custom_rgb_available(key);eye=eyedropper_available(key);spectrum=spectrum_available(key);numeric=numeric_rgb_available(key)
            if custom:
                modes=[]
                if spectrum:modes.append('visual color scale')
                if numeric:modes.append('numeric RGB')
                self.exact_color_text.set('✓ Smart custom palette calibrated: '+ ' + '.join(modes) + '. In Adaptive exact mode, Image Draw Bot uses the normal Paint palette when it is close enough and automatically opens Edit colors only for image colors that need a better match.' + (' Eyedropper reuse is also calibrated.' if eye else ''))
            elif eye:
                self.exact_color_text.set('Eyedropper is calibrated, but no exact color scale/RGB selector is complete. Nearest calibrated palette fallback remains active.')
            else:
                self.exact_color_text.set('Optional: calibrate the custom color spectrum/scale. Image Draw Bot can click the nearest visible point for each requested RGB; normal palette fallback always remains available.')
        except Exception:
            self.exact_color_text.set('Smart custom palette setup unavailable; nearest calibrated palette fallback remains active.')

    def calibrate_exact_colors(self):
        if not DrawBotApp._profile_action_ready(self):return
        from RuntimePaths import helper_command
        import subprocess
        key=PROFILES[self.game.get()][0];log=BASE/'logs'/'ImageDrawBot-exact-color-calibration.log';log.parent.mkdir(parents=True,exist_ok=True)
        command=helper_command('exactcolor','--profile',key,'--log',str(log))
        self.status.set('Opening isolated smart custom palette calibration. Main drawing input remains DISARMED.')
        def work():
            started=time.monotonic()
            try:
                proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
                while True:
                    try:
                        output,_=proc.communicate(timeout=.10);code=proc.returncode;break
                    except subprocess.TimeoutExpired:
                        if self.stop.is_set():
                            proc.kill();proc.communicate();raise InterruptedError('Custom colour calibration cancelled.')
            except InterruptedError:raise
            except Exception as error:code=-1;output=repr(error)
            self.events.put(('exact_color_calibration_complete',{'code':code,'output':output[-1200:],'elapsed':time.monotonic()-started}))
        self.begin_worker('exact-color-calibration',work)

    def calibrate(self):
        """Open palette calibration in a protected helper process.

        The palette picker touches Tk image objects, screen capture and Win32 mouse/window
        APIs.  A native/GUI failure there must never terminate the main Image Draw Bot UI.
        """
        if not DrawBotApp._profile_action_ready(self):return
        import subprocess
        profile_key=PROFILES[self.game.get()][0]
        palette_log=BASE/'logs'/'ImageDrawBot-palette-calibration.log'
        log_event(f'Isolated color calibration requested: profile={profile_key!r}. Mouse input remains DISARMED.')
        def work():
            from RuntimePaths import helper_command
            command=helper_command('palette','--path',str(self.calibration_path),'--profile',profile_key,'--log',str(palette_log))
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            process=None;output=''
            started=time.monotonic()
            try:
                process=subprocess.Popen(command,cwd=BASE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                         text=True,encoding='utf-8',errors='replace',creationflags=creationflags)
                self.palette_probe_process=process
                self.events.put(('status','🎨 Color calibration is open in a protected process. Main Image Draw Bot will stay safe if the calibration window fails.'))
                while True:
                    try:
                        output=process.communicate(timeout=.10)[0] or ''
                        break
                    except subprocess.TimeoutExpired:
                        if self.stop.is_set():
                            process.kill();process.communicate()
                            raise InterruptedError('Color calibration cancelled.')
            finally:
                self.palette_probe_process=None
            code=process.returncode if process else -1
            launcher_log=BASE/'logs'/'ImageDrawBot-palette-launcher.log'
            try:
                launcher_log.parent.mkdir(parents=True,exist_ok=True)
                launcher_log.write_text(f'Command: {command!r}\nExit: {code}\nElapsed: {time.monotonic()-started:.3f}s\n\n{output}',encoding='utf-8')
            except OSError:pass
            log_event(f'Isolated color calibration exited code={code} after {time.monotonic()-started:.3f}s.')
            self.events.put(('palette_calibration_complete',{'code':code,'output':output[-1600:],'log':str(palette_log)}))
        self.begin_worker('calibration',work)

    def _browser_layout_state(self, *, client_rect=None, dpi=None):
        """Return client-relative browser canvas/palette geometry for change detection."""
        try:
            from BrowserAutoRecalibration import make_layout_state
            client=tuple(client_rect or getattr(self,'target_client_rect',None) or ())
            if len(client)!=4 or len(getattr(self,'corners',()))!=2:
                return None
            x,y,w,h=self.area();canvas=(x,y,x+w,y+h)
            palette=[(int(c.x),int(c.y)) for c in allColors] if bool(getattr(self,'palette_ready',False)) else []
            return make_layout_state(client, dpi if dpi is not None else getattr(self,'target_dpi',None), canvas, palette)
        except (ValueError,TypeError,AttributeError):
            return None

    def _auto_recalibrate_browser_from_meta(self, meta, *, reason='pre-input verification'):
        previous=getattr(self,'drop_in_sync_phase',DROP_SYNC_IDLE)
        self.drop_in_sync_phase=DROP_SYNC_AUTO_RECALIBRATING
        try:
            return DrawBotApp._auto_recalibrate_browser_from_meta_impl(self,meta,reason=reason)
        except Exception as error:
            from BrowserDrawingRegion import BrowserDrawingRegion
            region=getattr(self,'browser_drawing_region',None)
            if isinstance(region,BrowserDrawingRegion):self.browser_drawing_region=region.without_verification()
            if getattr(self,'pending_drop_in_import',None) is not None or normalize_drop_in_action(getattr(self,'drop_action_pending',None))==DROP_IN_ACTION:
                DrawBotApp._disarm_manual_drop_in(self,'browser auto-recalibration failed while Drop-In was waiting')
                try:self.status.set(f'Drop-In blocked: Auto-Recalibration failed: {error}')
                except Exception:pass
            raise
        finally:
            if getattr(self,'drop_in_sync_phase',None)==DROP_SYNC_AUTO_RECALIBRATING:
                self.drop_in_sync_phase=previous if previous!=DROP_SYNC_PENDING else DROP_SYNC_PENDING
            if getattr(self,'pending_drop_in_import',None) is not None or normalize_drop_in_action(getattr(self,'drop_action_pending',None))==DROP_IN_ACTION:
                DrawBotApp._schedule_drop_in_sync_tick(self,40)

    def _auto_recalibrate_browser_from_meta_impl(self, meta, *, reason='pre-input verification'):
        """Read-only rescan of supported browser games before any native input.

        Unlike the old Anchor Transform path, browser layouts may reflow while the
        outer Chrome client rectangle stays identical (browser zoom is the common
        case).  Therefore supported browser profiles are visually re-detected and
        their anchored palette is rewritten before coordinates can be armed.
        """
        try:
            from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES, auto_calibrate_browser
            from BrowserAutoRecalibration import compare_layout_states
            profile_name=self.game.get();profile_key=PROFILES.get(profile_name,('',))[0]
        except Exception as error:
            raise ValueError(f'Browser Auto-Recalibration is unavailable: {error}') from error
        if profile_key not in SUPPORTED_BROWSER_PROFILES:
            return False
        drawing_region=DrawBotApp._browser_drawing_region(self)
        client=tuple(meta.get('client_rect') or ())
        if len(client)!=4:
            raise ValueError('Browser Auto-Recalibration could not read the browser client rectangle.')
        before=DrawBotApp._browser_layout_state(self)
        # The scan must see the browser itself, not Image Draw Bot or another window
        # covering it. Activating the existing target changes no canvas content and
        # sends no mouse/keyboard events.
        try:
            from ScreenGuard import WindowMonitor
            monitor=WindowMonitor();handle=int(meta['handle']);rect=tuple(meta['rect'])
            if not monitor.activate((handle,rect)):
                raise ValueError('Windows could not activate the selected browser for read-only auto-recalibration.')
            time.sleep(.18)
            rect=tuple(monitor.rectangle(handle));client=tuple(monitor.client_rectangle(handle));dpi=monitor.dpi(handle)
            meta=dict(meta);meta.update({'handle':handle,'rect':rect,'client_rect':client,'dpi':dpi})
        except InterruptedError as error:
            raise ValueError(f'Browser Auto-Recalibration could not verify the target browser: {error}') from error
        if drawing_region is not None:drawing_region.drawing_box(profile_key,meta)
        if uses_paint_color(self):
            from ScreenGuard import _grab_rgb
            from BrowserAutoCalibration import detect_browser_canvas
            with closing(_grab_rgb(client)) as shot:
                detected=detect_browser_canvas(profile_key,shot,screen_origin=client[:2],cancelled=self.stop.is_set)
            canvas=detected['canvas_box']
            if canvas is None or detected['canvas_confidence']<.70:
                raise ValueError('Single-color sketch could not verify the game canvas. Show a blank drawing canvas and select the area again.')
            l,t,r,b=map(int,canvas)
            if r-l<40 or b-t<40 or not (client[0]<=l<r<=client[2] and client[1]<=t<b<=client[3]):
                raise ValueError('Detected sketch canvas is outside the browser or too small.')
            if drawing_region is not None:
                drawing_region=drawing_region.with_canvas(profile_key,meta,canvas)
                l,t,r,b=drawing_region.drawing_box(profile_key,meta)
            self.corners=[(l,t),(r,b)];self.saved_area=list(self.corners)
            self.target_window=(handle,tuple(meta['rect']))
            self.target_client_rect=client;self.target_dpi=meta.get('dpi')
            self.browser_drawing_region=drawing_region
            if drawing_region is None:self.canvas_anchor_detection=None
            self.color_session_cache.clear()
            log_event('Single-color browser canvas verified without palette calibration or input.')
            return True
        # v1.0.76: reuse an already verified client-size/DPI/zoom-layout
        # fingerprint before running the heavier full palette/canvas detector.
        # Cache verification samples only saved palette control points and emits
        # no input. Browser Visual Preflight still runs before real drawing.
        from LayoutFingerprintV2 import try_restore, record_from_calibration_file
        from ScreenGuard import _grab_rgb
        with closing(_grab_rgb(client)) as screenshot:
            cached=try_restore(profile_key,meta,Path(self.calibration_path),screenshot=screenshot,cancelled=self.stop.is_set)
            cache_hit=bool(cached.hit);cache_refresh_meta=None
            retry_meta={'attempts':0,'retries':0,'errors':(), 'delays':()}
            if cache_hit:
                from BrowserAutoCalibration import detect_browser_canvas
                from BrowserAutoRecalibration import evaluate_cached_canvas
                live_canvas=detect_browser_canvas(profile_key,screenshot,screen_origin=(client[0],client[1]),cancelled=self.stop.is_set)
                cache_refresh_meta=evaluate_cached_canvas(cached.canvas_box,live_canvas.get('canvas_box'),live_canvas.get('canvas_confidence',0.0))
                if cache_refresh_meta.action=='full':
                    cache_hit=False
                else:
                    refreshed_canvas=(live_canvas.get('canvas_box') if cache_refresh_meta.action=='canvas-only' else cached.canvas_box)
                    class _CachedResult:
                        canvas_box=refreshed_canvas
                        canvas_confidence=float(live_canvas.get('canvas_confidence') or max(.90,cached.confidence))
                        palette_count=cached.palette_count
                        confidence=cached.confidence
                        method=('Layout Fingerprint v2 cache + canvas-only refresh' if cache_refresh_meta.action=='canvas-only' else 'Layout Fingerprint v2 cache')
                    result=_CachedResult()
                    if cache_refresh_meta.action=='canvas-only' and refreshed_canvas:
                        try:record_from_calibration_file(profile_key,meta,refreshed_canvas,Path(self.calibration_path),method=result.method)
                        except Exception as fingerprint_error:log_event(f'rc13 canvas-only fingerprint refresh skipped: {fingerprint_error!r}')
            if not cache_hit:
                from BrowserAutoRecalibration import calibrate_browser_with_retry
                result,retry_meta=calibrate_browser_with_retry(
                    profile_key,meta,Path(self.calibration_path),screenshot=screenshot,
                    recapture=lambda:_grab_rgb(client),
                    cancelled=self.stop.is_set)
                try:
                    if result.canvas_box:
                        record_from_calibration_file(profile_key,meta,result.canvas_box,Path(self.calibration_path),method=result.method)
                except Exception as fingerprint_error:
                    log_event(f'Layout Fingerprint v2 save skipped: {fingerprint_error!r}')
        canvas=result.canvas_box
        if not isinstance(canvas,(tuple,list)) or len(canvas)!=4 or float(result.canvas_confidence)<.70:
            raise ValueError(
                f'Browser Auto-Recalibration could not verify the canvas safely '
                f'(confidence {float(result.canvas_confidence)*100:.0f}%). No mouse input was sent.')
        l,t,r,b=map(int,canvas)
        if r-l<40 or b-t<40:
            raise ValueError('Browser Auto-Recalibration detected an implausibly small canvas. No mouse input was sent.')
        # Validate containment before mutating the live setup.
        if not (client[0] <= l < r <= client[2] and client[1] <= t < b <= client[3]):
            raise ValueError('Browser Auto-Recalibration detected a canvas outside the browser client area. No mouse input was sent.')

        if drawing_region is not None:
            drawing_region=drawing_region.with_canvas(profile_key,meta,canvas)
            l,t,r,b=drawing_region.drawing_box(profile_key,meta)
        self.corners=[(l,t),(r,b)];self.saved_area=[(l,t),(r,b)]
        self.target_window=(int(meta['handle']),tuple(meta['rect']))
        self.target_client_rect=client;self.target_dpi=meta.get('dpi')
        self.browser_drawing_region=drawing_region
        if drawing_region is None:self.canvas_anchor_detection=None
        self.color_session_cache.clear()
        DrawBotApp.refresh_palette(self)
        if not bool(getattr(self,'palette_ready',False)):
            raise ValueError('Browser Auto-Recalibration saved the palette but it could not be reloaded safely. No mouse input was sent.')
        after=DrawBotApp._browser_layout_state(self,client_rect=client,dpi=meta.get('dpi'))
        delta=compare_layout_states(before,after,tolerance_px=4)
        from BrowserAutoRecalibration import plan_recalibration
        recalibration_plan=plan_recalibration(delta,palette_confidence=float(result.confidence),
                                              canvas_confidence=float(result.canvas_confidence))
        self.canvas_anchor_transform_meta={
            'method':'browser-visual-recalibration','changed':bool(delta.changed),
            'reason':delta.reason,'max_palette_shift':int(delta.max_palette_shift),
            'max_canvas_shift':int(delta.max_canvas_shift),
            'confidence':float(result.confidence),
            'canvas_confidence':float(result.canvas_confidence),
            'recalibration_plan':recalibration_plan.as_dict(),
            'cache_refresh':cache_refresh_meta.as_dict() if cache_refresh_meta is not None else None,
            'retry_meta':dict(retry_meta),
        }
        if delta.changed:
            # A new final plan will use the new geometry. Old safety simulations
            # are deliberately not carried across a real browser reflow.
            DrawBotApp._invalidate_safety_preflight(self,'browser layout auto-recalibrated',disarm=True)
            try:self.browser_auto_text.set(f'✓ Auto-recalibrated · {result.palette_count} colors · {delta.reason}.')
            except Exception:pass
            try:self.status.set(f'Browser layout changed ({delta.reason}). Auto-recalibration passed; no manual calibration needed.')
            except Exception:pass
            log_event(
                f'Browser Auto-Recalibration applied: profile={profile_name!r} reason={reason!r} '
                f'change={delta.reason!r} colors={result.palette_count} confidence={result.confidence:.3f} cache_hit={cache_hit} '
                f'canvas={tuple(canvas)!r}.')
        else:
            log_event(
                f'Browser Auto-Recalibration verified unchanged layout: profile={profile_name!r} '
                f'reason={reason!r} colors={result.palette_count} confidence={result.confidence:.3f} cache_hit={cache_hit}.')
        try:self.save_settings()
        except Exception:pass
        return bool(delta.changed)

    def _run_browser_visual_preflight(self, current_client, *, reason='before drawing'):
        previous=getattr(self,'drop_in_sync_phase',DROP_SYNC_IDLE)
        self.drop_in_sync_phase=DROP_SYNC_VISUAL_PREFLIGHT
        try:
            return DrawBotApp._run_browser_visual_preflight_impl(self,current_client,reason=reason)
        except Exception as error:
            from BrowserDrawingRegion import BrowserDrawingRegion
            region=getattr(self,'browser_drawing_region',None)
            if isinstance(region,BrowserDrawingRegion):self.browser_drawing_region=region.without_verification()
            if getattr(self,'pending_drop_in_import',None) is not None or normalize_drop_in_action(getattr(self,'drop_action_pending',None))==DROP_IN_ACTION:
                DrawBotApp._disarm_manual_drop_in(self,'browser visual preflight failed while Drop-In was waiting')
                try:self.status.set(f'Drop-In blocked: Visual Preflight failed: {error}')
                except Exception:pass
            raise
        finally:
            if getattr(self,'drop_in_sync_phase',None)==DROP_SYNC_VISUAL_PREFLIGHT:
                self.drop_in_sync_phase=previous if previous!=DROP_SYNC_PENDING else DROP_SYNC_PENDING
            if getattr(self,'pending_drop_in_import',None) is not None or normalize_drop_in_action(getattr(self,'drop_action_pending',None))==DROP_IN_ACTION:
                DrawBotApp._schedule_drop_in_sync_tick(self,40)

    def _run_browser_visual_preflight_impl(self, current_client, *, reason='before drawing'):
        """Read-only final browser check immediately before planning/input.

        Auto-Recalibration already refreshes geometry. Visual Preflight then
        independently verifies that the expected canvas and representative
        palette swatches are still visible at those coordinates. A mismatch gets
        one automatic re-scan/recalibration retry; persistent mismatch blocks
        drawing before native mouse input is armed.
        """
        try:
            from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
            from BrowserVisualPreflight import verify_browser_visual_preflight
            profile_name=self.game.get();profile_key=PROFILES.get(profile_name,('',))[0]
        except Exception as error:
            raise ValueError(f'Browser Visual Preflight is unavailable: {error}') from error
        if profile_key not in SUPPORTED_BROWSER_PROFILES:
            return current_client

        def verify(client):
            x,y,w,h=self.area();canvas=(x,y,x+w,y+h)
            palette_entries=[((int(c.x),int(c.y)),tuple(c.RGB)) for c in allColors]
            meta={
                'handle':int(self.target_window[0]),
                'rect':tuple(self.target_window[1]),
                'client_rect':tuple(client),
                'dpi':getattr(self,'target_dpi',None),
            }
            drawing_region=DrawBotApp._browser_drawing_region(self,require_verified=True)
            if drawing_region is not None:canvas=drawing_region.expected_canvas(profile_key,meta)
            if uses_paint_color(self):
                result=verify_browser_visual_preflight(profile_key,meta,canvas,(),require_palette=False)
            else:
                result=verify_browser_visual_preflight(profile_key,meta,canvas,palette_entries)
            if result.passed and drawing_region is not None:
                # Verify the full canvas independently, then retain the user's
                # hard region only if it fits this fresh detection as well.
                self.browser_drawing_region=drawing_region.with_canvas(profile_key,meta,result.detected_canvas)
            return result

        result=verify(current_client)
        if not result.passed:
            log_event(
                f'Browser Visual Preflight initial mismatch: profile={profile_name!r} reason={result.reason!r} '
                f'canvas_ok={result.canvas_ok} palette={result.palette_verified}/{result.palette_tested} '
                f'confidence={result.confidence:.3f}. Retrying read-only Auto-Recalibration.')
            from TargetCapture import probe_handle_isolated
            meta=probe_handle_isolated(int(self.target_window[0]))
            DrawBotApp._auto_recalibrate_browser_from_meta(self,meta,reason='visual preflight recovery')
            current_client=tuple(getattr(self,'target_client_rect',None) or meta.get('client_rect') or ())
            if len(current_client)!=4:
                raise ValueError('Browser Visual Preflight recovery could not read the browser client rectangle. No mouse input was sent.')
            if not bypasses_palette(self):
                load_calibration(self.calibration_path,current_client_rect=current_client,require_anchor=False,profile_key=PROFILES[self.game.get()][0])
            result=verify(current_client)

        if not result.passed:
            try:self.browser_auto_text.set(
                f'Visual preflight blocked · canvas={"OK" if result.canvas_ok else "FAIL"} · '
                f'palette={result.palette_verified}/{result.palette_tested}.')
            except Exception:pass
            raise ValueError(
                f'Browser Visual Preflight failed after automatic recalibration: {result.reason}. '
                'The page, canvas or palette does not match the calibrated browser layout. No mouse input was sent.')

        try:self.browser_auto_text.set(
            f'✓ Visual preflight PASS · canvas verified · palette {result.palette_verified}/{result.palette_tested} · '
            f'confidence {result.confidence*100:.0f}%.')
        except Exception:pass
        log_event(
            f'Browser Visual Preflight passed: profile={profile_name!r} reason={reason!r} '
            f'canvas_ok={result.canvas_ok} palette={result.palette_verified}/{result.palette_tested} '
            f'confidence={result.confidence:.3f} max_palette_error={result.max_palette_error:.1f}.')
        return current_client

    def capture_target(self):
        # WindowFromPoint/GetWindowRect/GetClientRect are native Win32 calls. Run
        # them outside the GUI process so an access violation cannot close it.
        import os
        from TargetCapture import capture_target_metadata_isolated
        meta=capture_target_metadata_isolated(self.area(),exclude_pid=os.getpid())
        from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
        from BrowserDrawingRegion import BrowserDrawingRegion
        profile_key=PROFILES.get(self.game.get(),('',))[0]
        region=None
        if profile_key in SUPPORTED_BROWSER_PROFILES:
            x,y,w,h=self.area()
            region=BrowserDrawingRegion.capture(profile_key,meta,(x,y,x+w,y+h))
        self.browser_drawing_region=region
        self.target_window=(meta['handle'],meta['rect'])
        self.target_client_rect=meta['client_rect']
        self.target_dpi=meta.get('dpi')
        if self.target_dpi:
            source=meta.get('dpi_source') or 'Windows'
            monitor=meta.get('monitor_rect')
            log_event(
                f'Target DPI captured automatically: {self.target_dpi} ({self.target_dpi/96:.2f}x scale) '
                f'source={source} monitor={monitor}.')

    def _carry_safety_signatures_after_rebase(self, old_signature):
        """Keep preflight/dry-run valid after a mathematically safe target rebase."""
        try:
            new_signature=DrawBotApp._current_safety_signature(self)
            if bool(getattr(self,'safety_preflight_passed',False)) and getattr(self,'safety_preflight_signature',None)==old_signature:
                self.safety_preflight_signature=new_signature
            if bool(getattr(self,'dry_run_passed',False)) and getattr(self,'dry_run_signature',None)==old_signature:
                self.dry_run_signature=new_signature
        except Exception:
            # Do not fail drawing because a UI-only validity cache could not be carried.
            pass

    def _refresh_target_for_draw(self, *, update_target_lock=True):
        """Refresh/rebase target geometry before any input is armed.

        v1.0.50: same-size window movement is rebased through Anchor Transform.
        Very small client-size changes can also be rebased with the saved
        corner/triangle anchors. Supported browser profiles are different:
        Gartic/Skribbl/SketchHeads are visually re-scanned before input so Chrome
        zoom, resize and DPI/layout reflow can auto-recalibrate safely.
        """
        if self.target_window is None:raise ValueError('Select the drawing area again to lock the correct window.')
        from TargetCapture import probe_handle_isolated
        handle=self.target_window[0];meta=probe_handle_isolated(handle)
        current=tuple(meta['client_rect'])
        current_dpi=meta.get('dpi')
        selected_dpi=getattr(self,'target_dpi',None)
        if current_dpi is not None:
            log_event(
                f'Target DPI refresh: detected={current_dpi} scale={current_dpi/96:.2f}x '
                f'source={meta.get("dpi_source") or "Windows"} monitor={meta.get("monitor_rect")}.')
        try:
            from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
            profile_key=PROFILES.get(self.game.get(),('',))[0]
            browser_profile=profile_key in SUPPORTED_BROWSER_PROFILES
        except Exception:
            browser_profile=False
        if browser_profile:
            # Browser zoom can reflow canvas/palette without changing the Chrome
            # window/client rectangle at all. Always perform a visual read-only
            # verification before coordinates can be armed.
            DrawBotApp._auto_recalibrate_browser_from_meta(self,meta,reason='pre-input target refresh')
            current=tuple(self.target_client_rect);current_dpi=getattr(self,'target_dpi',current_dpi)
            selected_dpi=current_dpi
            old=current
        else:
            if selected_dpi is not None and current_dpi is not None and current_dpi!=selected_dpi:
                raise ValueError(
                    f'The target DPI changed from {selected_dpi} to {current_dpi}. Paint likely moved to a display with different scaling. '
                    'Select the drawing area again so physical pixel coordinates can be recalibrated. No mouse input was sent.')
            old=tuple(self.target_client_rect) if self.target_client_rect is not None else current
        old_size=(old[2]-old[0],old[3]-old[1]);new_size=(current[2]-current[0],current[3]-current[1])
        old_area=self.area()
        try:old_safety_signature=DrawBotApp._current_safety_signature(self)
        except Exception:old_safety_signature=None
        moved_or_scaled=(old!=current)
        if not browser_profile:
            self.canvas_anchor_transform_meta=None
        if moved_or_scaled:
            try:
                rebased_area,transform=rebase_canvas_area(
                    old_area, old, current, getattr(self,'canvas_anchor_detection',None),
                    max_scale_delta=0.025, max_size_delta_px=32)
            except ValueError as error:
                raise ValueError(
                    f'The target window changed size from {old_size[0]}×{old_size[1]} to {new_size[0]}×{new_size[1]}. '
                    f'Anchor Transform could not safely rebase the canvas: {error} Select the drawing area again. No mouse input was sent.') from error
            if not area_inside_client(rebased_area,current,margin=0):
                raise ValueError('Anchor Transform would place the drawing area outside the target client area. Select the drawing area again. No mouse input was sent.')
            x,y,w,h=rebased_area
            self.corners=[(int(x),int(y)),(int(x+w),int(y+h))]
            self.saved_area=[tuple(p) for p in self.corners]
            self.canvas_anchor_transform_meta=transform.as_dict()
            log_event(
                f'Anchor Transform rebased drawing area: method={transform.method} dx={transform.dx:.2f} dy={transform.dy:.2f} '
                f'sx={transform.sx:.6f} sy={transform.sy:.6f} anchors={transform.used_anchors} triangles={transform.used_triangles}.')
        self.target_client_rect=current
        self.target_dpi=current_dpi if current_dpi is not None else selected_dpi
        self.target_window=(handle,tuple(meta['rect']))
        x,y,w,h=self.area()
        if not (current[0]<=x and current[1]<=y and x+w<=current[2] and y+h<=current[3]):
            raise ValueError('The drawing area is no longer fully inside the target client area. Select it again.')
        if update_target_lock and bool(getattr(self,'target_lock_passed',False)) and getattr(self,'target_lock_fingerprint',None):
            try:
                fingerprint=DrawBotApp._build_target_lock_fingerprint(self,current_client_rect=current,current_target_rect=self.target_window[1],current_dpi=self.target_dpi)
                self.target_lock_fingerprint=fingerprint
                self.target_lock_signature=DrawBotApp._target_lock_signature_from(fingerprint)
                DrawBotApp._carry_safety_signatures_after_rebase(self, old_safety_signature)
                if moved_or_scaled:
                    log_event('Target/setup lock fingerprint rebased after safe Anchor Transform.')
            except Exception as error:
                raise ValueError(f'Anchor Transform rebased the canvas, but the target lock could not be refreshed: {error}') from error
        return current

    def draw(self,test=False,dry_run=False,user_initiated=False,paint_prepared=False,paint_prepared_options=None):
        # Loading, dropping, profile switching and background callbacks must
        # never arm the mouse. Only explicit UI controls pass this flag.
        if not user_initiated:
            log_event('Blocked non-user-initiated drawing request.')
            self.status.set('Drawing did not start. Use Unlock full drawing, then Start Drawing, or run Draw small test explicitly.')
            return
        if self.activity or self.closing:return
        if (not test and not dry_run and not paint_prepared
                and DrawBotApp._automatic_paint_preparation(self)):
            if self.original is None:
                self.status.set('Load an image before starting Paint.');return False
            return self.auto_calibrate_paint_tools(start_after=True)
        DrawBotApp._cancel_after_attr(self,'preview_after')
        DrawBotApp._cancel_after_attr(self,'preview_render_after')
        if not test and not dry_run:DrawBotApp._disarm_full_draw(self,'drawing started', update_text=True)
        action_label = 'small test' if test else ('dry run' if dry_run else 'drawing')
        log_event(f'User initiated {action_label}.')
        start_state=None
        if not test and not dry_run:
            from StartDrawingState import StartDrawingStateMachine
            start_state=StartDrawingStateMachine(logger=log_event)
            self.start_state_machine=start_state
        if len(self.corners)!=2:
            log_event('Drawing blocked: no drawing area selected.')
            if start_state:start_state.transition('ABORTED','drawing area not selected')
            self.status.set('Select the drawing area first.');return
        if self.original is None and not test:
            log_event('Drawing blocked: no source image loaded.')
            if start_state:start_state.transition('ABORTED','source image not loaded')
            self.status.set('Load or paste an image before pressing Start Drawing.')
            try:self.summary.set('No image loaded. Choose an image, paste with Ctrl+V, or drag a file into Image Draw Bot first.')
            except (tk.TclError,AttributeError):pass
            return
        # Accept a fresh explicit start here, before any synchronous preflight.
        # The worker must preserve Esc received during the checks or handoff.
        self.stop.clear()
        try:
            if start_state:start_state.transition('PREFLIGHT','validating target, palette, canvas and calibrated tools')
            if not test and DrawBotApp._strict_safety_required(self):
                DrawBotApp._verify_target_lock(self)
            paint_profile=self.game.get()=='Microsoft Paint'
            current_client=self._refresh_target_for_draw()
            if not bypasses_palette(self):
                load_calibration(self.calibration_path,current_client_rect=current_client,require_anchor=paint_profile,profile_key=PROFILES[self.game.get()][0])
            current_client=DrawBotApp._run_browser_visual_preflight(self,current_client,reason=action_label)
            if self.stop.is_set() or self.closing:raise InterruptedError('Drawing start cancelled.')
            area=self.area()
            palette=() if bypasses_palette(self) else tuple((c.x,c.y) for c in allColors)
            if min(area[2:])<10:raise ValueError('Select a larger drawing area.')
            if any(area[0]<=x<=area[0]+area[2] and area[1]<=y<=area[1]+area[3] for x,y in palette):
                raise ValueError('The color palette overlaps the drawing area. Select only the canvas.')
            options=self.options()
            profile_key=PROFILES[self.game.get()][0]
            detection_canvas=(area[0],area[1],area[0]+area[2],area[1]+area[3])
            drawing_region=DrawBotApp._browser_drawing_region(self,require_verified=True)
            if drawing_region is not None:
                detection_canvas=drawing_region.expected_canvas(profile_key,{
                    'handle':self.target_window[0],'client_rect':current_client,
                    'dpi':getattr(self,'target_dpi',None)})
            limited_browser_region=(drawing_region is not None and
                detection_canvas!=(area[0],area[1],area[0]+area[2],area[1]+area[3]))
            if paint_prepared_options is not None:
                if not isinstance(paint_prepared_options,dict):
                    raise ValueError('Prepared Paint brush settings are invalid. Prepare Paint again.')
                prepared_width=paint_prepared_options.get('brush_px')
                if (not paint_profile or not paint_prepared or type(prepared_width) is not int
                        or not 1<=prepared_width<=50):
                    raise ValueError('Prepared Paint brush width is invalid. Prepare Paint again.')
                # Auto may resolve differently after discovering a new canvas.
                # This run must model the width actually selected by preparation.
                options=dict(options,brush_px=prepared_width,canvas_guard_brush_px=prepared_width,
                    brush_px_requested=paint_prepared_options['brush_px_requested'],
                    auto_brush_width_meta=dict(paint_prepared_options.get('auto_brush_width_meta') or {}))
            # v1.0.74: browser brush size is detected read-only from the already
            # verified layout. Only a visually plausible control row produces a
            # click target; otherwise execution leaves the website untouched and
            # uses a conservative CanvasGuard brush inset.
            from ScreenGuard import _grab_rgb
            with ExitStack() as capture_scope:
                shot=None
                try:
                    from BrowserBrushSize import SUPPORTED as BRUSH_PROFILES,plan_browser_brush_size
                    if profile_key in BRUSH_PROFILES:
                        shot=capture_scope.enter_context(closing(_grab_rgb(tuple(current_client))))
                        pal_box=None
                        if palette:
                            xs=[p[0] for p in palette];ys=[p[1] for p in palette]
                            pal_box=(min(xs),min(ys),max(xs)+1,max(ys)+1)
                        x,y,w,h=area
                        brush_plan=plan_browser_brush_size(profile_key,shot,tuple(current_client),
                            canvas_box=detection_canvas,palette_box=pal_box,requested_px=options.get('brush_px',3))
                        options['browser_brush_plan']=brush_plan.as_dict()
                        options['brush_px']=int(brush_plan.effective_px)
                        options['canvas_guard_brush_px']=int(brush_plan.safe_guard_px)
                        _brush_meta=options['browser_brush_plan']
                        _level_note=(f" level={_brush_meta.get('effective_level')}" if _brush_meta.get('effective_level') else '')
                        log_event(f"Automatic browser brush preflight: profile={profile_key} requested={brush_plan.requested_px}{_level_note} physical={brush_plan.effective_px}px target={brush_plan.target_position!r} selected={brush_plan.selected_index!r} confidence={brush_plan.confidence:.3f} guard={brush_plan.safe_guard_px}px.")
                        if profile_key in ('gartic-phone','gartic-io'):
                            from GarticOpacity import plan_gartic_opacity
                            opacity_plan=plan_gartic_opacity(profile_key,shot,tuple(current_client),
                                canvas_box=detection_canvas,source_image=self.original,
                                requested=options.get('gartic_opacity','Auto'),draw_quality=options.get('draw_quality',''),
                                render_style=options.get('render_style',''),drawing_mode=options.get('drawing_mode',''),
                                outline=bool(options.get('outline')))
                            options['gartic_opacity_plan']=opacity_plan.as_dict()
                            options['gartic_opacity_percent']=int(opacity_plan.selected_percent)
                            log_event(f"Gartic opacity preflight: requested={opacity_plan.requested} selected={opacity_plan.selected_percent}% confidence={opacity_plan.confidence:.3f} target={opacity_plan.target_position!r} reason={opacity_plan.reason}.")
                except InterruptedError:raise
                except Exception as brush_error:
                    # Brush automation is an optimization/convenience layer. A
                    # detector failure must not invent clicks; keep the current brush
                    # and enlarge only the safety inset.
                    from BrowserBrushSize import conservative_brush_guard
                    options['canvas_guard_brush_px']=conservative_brush_guard(profile_key,options.get('brush_px',3))
                    options['browser_brush_plan']={'profile_key':profile_key,'target_position':None,'safe_guard_px':options['canvas_guard_brush_px'],'method':str(brush_error)}
                    log_event(f'Automatic browser brush detection fell back safely: {brush_error!r}.')
                try:
                    from BrowserToolLayout import SUPPORTED as TOOL_PROFILES,plan_browser_tools
                    if profile_key in TOOL_PROFILES:
                        tool_shot=shot
                        if tool_shot is None:
                            tool_shot=capture_scope.enter_context(closing(_grab_rgb(tuple(current_client))))
                        tool_pal_box=None
                        if palette:
                            xs=[p[0] for p in palette];ys=[p[1] for p in palette]
                            tool_pal_box=(min(xs),min(ys),max(xs)+1,max(ys)+1)
                        x,y,w,h=area
                        tool_plan=plan_browser_tools(profile_key,tool_shot,tuple(current_client),
                            canvas_box=detection_canvas,palette_box=tool_pal_box)
                        options['browser_tool_plan']=tool_plan.as_dict()
                        log_event(f"Automatic browser tools preflight: profile={profile_key} tools={sorted((tool_plan.tools or {}).keys())} confidence={tool_plan.confidence:.3f} method={tool_plan.method!r}.")
                except InterruptedError:raise
                except Exception as tool_error:
                    options['browser_tool_plan']={'tools':{},'confidence':0.0,'tool_scores':{},'method':str(tool_error)}
                    log_event(f'Automatic browser tool detection fell back safely: {tool_error!r}.')
            # Paint-only real preflight: resolve stale palette-only saved
            # settings against the *actual* profile calibration before planning.
            # This is what lets Image Draw Bot open Edit colors automatically when
            # the current image reaches a useful custom RGB batch.
            custom_resolution=resolve_image_custom_color_workflow(
                self.game.get(), profile_key, options.get('custom_color_workflow','Calibrated palette'),
                render_preset=options.get('render_preset','Auto'))
            if custom_resolution.get('auto_promoted'):
                options['custom_color_workflow']=custom_resolution['workflow']
                options['custom_color_auto_meta']=dict(custom_resolution)
                log_event('Microsoft Paint custom-color workflow auto-promoted from calibrated palette to Adaptive exact for this image.')
            if options.get('custom_color_workflow') in ('Exact custom + palette fallback','Adaptive exact (recommended)'):
                try:
                    exact_actions=resolve_exact_color_controls(profile_key,current_client)
                    base=('OpenCustomColor','ConfirmColor')
                    spectrum=('SpectrumTopLeft','SpectrumBottomRight')
                    numeric=('RedField','GreenField','BlueField')
                    spectrum_ready=all(name in exact_actions for name in base+spectrum)
                    numeric_ready=all(name in exact_actions for name in base+numeric)
                    options['exact_color_actions']=exact_actions
                    # v1.0.108: a calibrated Paint color spectrum is a complete
                    # custom-color selector by itself. v1.0.107 accidentally
                    # required numeric R/G/B fields here, so spectrum-only setups
                    # were displayed as calibrated but disabled for real drawing.
                    options['exact_color_available']=bool(spectrum_ready or numeric_ready)
                    options['exact_color_capabilities']={'spectrum':bool(spectrum_ready),'numeric':bool(numeric_ready)}
                except (OSError,ValueError,TypeError):
                    options['exact_color_actions']={}
                    options['exact_color_available']=False
            log_event(f"Draw preflight options resolved: area={area} source={getattr(self.original, 'size', None)} profile={self.game.get()!r} paint_profile={paint_profile!r} palette_points={len(palette)} {_resource_log_text(options)}.")
            # Real tool actions were previously built only for preview planning,
            # leaving real drawing with an empty action list. Resolve them here.
            auto_browser_tool_plan=options.get('browser_tool_plan') or {}
            if paint_profile and options.get('effective_paint_tool',options.get('paint_tool'))!='Use current tool':
                from PaintTools import build_tool_actions
                options['tool_actions']=build_tool_actions(options.get('effective_paint_tool',options['paint_tool']),current_client_rect=current_client)
                for kind,position in options['tool_actions']:
                    x,y=position
                    if area[0]<=x<=area[0]+area[2] and area[1]<=y<=area[1]+area[3]:
                        raise ValueError(f'The calibrated Paint {kind} control overlaps the drawing area. Recalibrate Paint tools.')
            elif not paint_profile:
                try:
                    from BrowserToolLayout import build_browser_tool_action
                    options['tool_actions']=[build_browser_tool_action(auto_browser_tool_plan,'Brush')]
                except (OSError,ValueError):
                    pass
            options['fill_tool_actions']=[];options['fill_restore_actions']=[]
            options['fill_unavailable_reason']=''
            if (options.get('background_fill')!='Off' or options.get('use_region_fill_engine')) and not bypasses_palette(self):
                if paint_profile and options.get('paint_tool') not in ('Use current tool','Eraser'):
                    try:
                        from PaintTools import build_tool_actions
                        options['fill_tool_actions']=build_tool_actions('Fill',current_client_rect=current_client)
                        options['fill_restore_actions']=list(options.get('tool_actions',[]))
                    except (OSError,ValueError) as error:
                        options['fill_unavailable_reason']=str(error)
                elif not paint_profile:
                    try:
                        from AppTools import build_tool_action
                        profile_key=PROFILES[self.game.get()][0]
                        options['fill_tool_actions']=[build_tool_action(profile_key,'Fill',current_client)]
                        options['fill_restore_actions']=[build_tool_action(profile_key,'Brush',current_client)]
                    except (OSError,ValueError) as error:
                        options['fill_unavailable_reason']=str(error)
                        try:
                            from BrowserToolLayout import build_browser_tool_action
                            options['fill_tool_actions']=[build_browser_tool_action(auto_browser_tool_plan,'Fill')]
                            options['fill_restore_actions']=[build_browser_tool_action(auto_browser_tool_plan,'Brush')]
                            options['fill_unavailable_reason']=''
                        except (OSError,ValueError):
                            pass
                options['fill_tool_available']=bool(options.get('fill_tool_actions') and options.get('fill_restore_actions'))
                for kind,position in options.get('fill_tool_actions',[])+options.get('fill_restore_actions',[]):
                    x,y=position
                    if area[0]<=x<=area[0]+area[2] and area[1]<=y<=area[1]+area[3]:
                        raise ValueError(f'The calibrated {kind} control overlaps the drawing area. Recalibrate application tools.')
            if limited_browser_region:
                # A bucket seed inside a region does not constrain host flood
                # fill. Keep the existing stroke fallback for this hard bound.
                options['fill_tool_available']=False
                options['fill_tool_actions']=[];options['fill_restore_actions']=[]
                options['fill_unavailable_reason']='A selected browser subregion uses brush strokes; native Fill can escape into the full canvas.'
            # v1.0.114 Automatic Canvas Clear.  Resolution happens only inside
            # explicit Start/Dry Run preflight, never during preview planning.
            options['canvas_clear_actions']=[];options['canvas_clear_restore_actions']=[]
            options['canvas_clear_strategy']='off';options['canvas_clear_reason']='';options['canvas_clear_estimate_seconds']=0.0
            if options.get('auto_clear_canvas') and not test:
                if limited_browser_region:
                    raise ValueError('Auto clear cannot safely preserve a selected browser subregion: '
                                     'native Clear affects the full canvas and the Eraser width is not verified. '
                                     'Disable Auto clear or select the full canvas.')
                from CanvasClear import resolve_clear_strategy
                tool_data={}
                if not paint_profile:
                    try:
                        from AppTools import load_calibration as load_app_tool_calibration
                        tool_data=load_app_tool_calibration(profile_key)
                    except (OSError,ValueError,TypeError):
                        tool_data={'tools':{}}
                    merged_tools=dict(tool_data.get('tools',{}) or {})
                    for tool_name,tool_position in (auto_browser_tool_plan.get('tools') or {}).items():
                        merged_tools.setdefault(tool_name,tool_position)
                    tool_data={'tools':merged_tools}
                clear_strategy=resolve_clear_strategy(
                    paint_profile=paint_profile,
                    tools=tool_data.get('tools',{}),
                    keyboard_available=(getattr(self,'keyboard',None) is not None),
                    canvas_size=(area[2],area[3]),
                    brush_px=options.get('canvas_guard_brush_px',options.get('brush_px',3)))
                options['canvas_clear_strategy']=clear_strategy.strategy
                options['canvas_clear_reason']=clear_strategy.reason
                options['canvas_clear_estimate_seconds']=float(clear_strategy.estimated_seconds)
                if clear_strategy.strategy in ('native-clear','eraser-sweep'):
                    try:
                        from AppTools import build_tool_action
                        if clear_strategy.strategy=='native-clear':
                            options['canvas_clear_actions']=[build_tool_action(profile_key,'Clear',current_client)]
                        else:
                            options['canvas_clear_actions']=[build_tool_action(profile_key,'Eraser',current_client)]
                            options['canvas_clear_restore_actions']=[build_tool_action(profile_key,'Brush',current_client)]
                    except (OSError,ValueError):
                        from BrowserToolLayout import build_browser_tool_action
                        if clear_strategy.strategy=='native-clear':
                            options['canvas_clear_actions']=[build_browser_tool_action(auto_browser_tool_plan,'Clear')]
                        else:
                            options['canvas_clear_actions']=[build_browser_tool_action(auto_browser_tool_plan,'Eraser')]
                            options['canvas_clear_restore_actions']=[build_browser_tool_action(auto_browser_tool_plan,'Brush')]
                    for kind,position in options['canvas_clear_actions']+options['canvas_clear_restore_actions']:
                        px,py=position
                        if area[0]<=px<=area[0]+area[2] and area[1]<=py<=area[1]+area[3]:
                            raise ValueError(f'The calibrated {kind} control overlaps the drawing area. Recalibrate application tools.')
                log_event(f"Automatic canvas clear preflight: enabled=True strategy={clear_strategy.strategy!r} reason={clear_strategy.reason!r} estimate={clear_strategy.estimated_seconds:.2f}s.")
            if self.stop.is_set() or self.closing:raise InterruptedError('Drawing start cancelled.')
        except (OSError,ValueError,InterruptedError) as error:
            if start_state and start_state.state!='ABORTED':start_state.transition('ABORTED',f'preflight stopped: {error}')
            self.status.set(f'Preflight stopped: {error}');return
        from ScreenGuard import GuardedMouse,WindowMonitor
        runtime_palette_guard=runtime_palette_guard_colors(profile_key,palette,allColors)
        if palette and not runtime_palette_guard:
            log_event(f"Runtime palette guard delegated to Browser Visual Preflight: profile={profile_key!r} swatches={len(palette)}.")
        guarded=GuardedMouse(self.mouse,WindowMonitor(),self.target_window,runtime_palette_guard,live_target_check=self._make_live_target_check() if (not test and DrawBotApp._strict_safety_required(self) and DrawBotApp._target_lock_valid(self)) else None)
        if test:
            if options.get('erase_mode'):
                prompt='This erases one short line in the selected drawing area. Put a visible mark under the test area first so you can confirm the Eraser works. Continue?'
            else:
                prompt='This draws up to three lines in the selected drawing area. Use an empty test canvas. Continue?'
            if not messagebox.askokcancel('Drawing test',prompt):return
        self.paused.clear();self.progress['value']=0;self.save_settings()
        if self.stop.is_set() or self.closing:
            if start_state:start_state.transition('ABORTED','drawing start cancelled before snapshot')
            self.status.set('Drawing start cancelled. No automatic restart.')
            return False
        # A small test does not plan from the loaded image. For a real plan,
        # keep one private snapshot only through the last planning attempt.
        original=self.original.copy() if self.original is not None and not test else None
        self.preview_generation=int(getattr(self,'preview_generation',0))+1
        generation=self.preview_generation
        publication=WorkerPlanPublication(lambda plan:DrawBotApp._release_plan_images(self,plan))
        self._draw_plan_publication=publication
        runtime_request=DrawBotApp._begin_runtime_safety_request(self,action_label)
        def release_source_snapshot(retained_plan=None,*,transfer=False):
            nonlocal original
            snapshot=original
            if snapshot is None:return
            if retained_plan is not None:
                from AutoSketchBudget import _trial_images
                # A planner may transfer its input into an owned image field.
                # The final plan's publication owner then keeps it alive for
                # execution and releases it if UI publication is rejected.
                if any(image is snapshot for image in _trial_images(retained_plan)):
                    if transfer:original=None
                    return
            original=None
            snapshot.close()
        def release_worker_images():
            try:publication.finish()
            finally:release_source_snapshot()
        def work():
            started=time.monotonic()
            if start_state:start_state.set_block_reason('building/validating final render plan before mouse input')
            if not test and not dry_run and profile_key=='gartic-phone' and options.get('read_gartic_timer') and not options.get('unlimited_time'):
                from GarticTimer import observe_timer,apply_timer_budget
                from PIL import ImageGrab
                # Give the UI's queued minimization time to finish; no input is armed.
                if self.stop.wait(.35):raise InterruptedError()
                monitor=WindowMonitor()
                if not monitor.activate(self.target_window):raise ValueError('Show the Gartic window to read its timer.')
                def timer_capture():
                    if not monitor.active(self.target_window):raise ValueError('Gartic must stay visible while reading the timer.')
                    if tuple(monitor.client_rectangle(self.target_window[0]))!=tuple(current_client):
                        raise ValueError('Gartic changed size while reading the timer. Select the area again.')
                    from ScreenGuard import _grab_rgb
                    return _grab_rgb(tuple(current_client))
                local_canvas=(area[0]-current_client[0],area[1]-current_client[1],area[0]+area[2]-current_client[0],area[1]+area[3]-current_client[1])
                reading=observe_timer(timer_capture,local_canvas,self.stop,lambda msg:self.events.put(('status',msg)))
                options.update(apply_timer_budget(options,reading))
                log_event(f"Gartic timer measured: approximate={reading['estimated_seconds']:.1f}s safe={reading['safe_seconds']:.1f}s observed={reading['observed_seconds']:.1f}s box={reading['box']}.")
                self.events.put(('status',f"Gartic timer: approximately {reading['estimated_seconds']:.0f}s left; planning with {options['max_seconds']:.0f}s conservative budget."))
            if dry_run:
                self.events.put(('status','Building dry-run plan… No clicks will be sent during this test.'))
            else:
                self.events.put(('status','Building final drawing plan… CPU/GPU/RAM allocation is used here before mouse input starts.'))
            log_event(f"Final planning started: area={area[2:]} source={getattr(original, 'size', None)} test={test!r} dry_run={dry_run!r} watchdog={options.get('planning_watchdog','Auto')} {_resource_log_text(options)}.")
            attempts=build_planning_attempts(options,test=test,preview=False,dry_run=dry_run)
            plan=None
            last_timeout=None
            for attempt in attempts:
                if self.stop.is_set() or self.closing:
                    raise InterruptedError()
                attempt_started=time.monotonic()
                attempt_deadline=(None if attempt.timeout_seconds is None else
                                  attempt_started+float(attempt.timeout_seconds))
                planning_done=threading.Event()
                self.events.put(('status',f'Final planning attempt {attempt.index}/{attempt.total}: {attempt.name}. No mouse input is armed.'))
                timeout_label='disabled' if attempt.timeout_seconds is None else f'{attempt.timeout_seconds:.1f}s'
                log_event(f"Final planning attempt {attempt.index}/{attempt.total} started: name={attempt.name!r} area={area[2:]} source={getattr(original, 'size', None)} test={test!r} timeout={timeout_label} {_resource_log_text(attempt.options)}.")
                def heartbeat(attempt=attempt, attempt_started=attempt_started, attempt_deadline=attempt_deadline, planning_done=planning_done):
                    while not planning_done.wait(5.0):
                        if self.stop.is_set() or self.closing:
                            return
                        elapsed=time.monotonic()-attempt_started
                        remaining=None if attempt_deadline is None else max(0.0,attempt_deadline-time.monotonic())
                        timeout_note=('automatic timeout disabled' if remaining is None else
                                      f'{"fallback" if attempt.index<attempt.total else "timeout"} in {remaining:.0f}s')
                        self.events.put(('status',f'Final planning {attempt.index}/{attempt.total}: {elapsed:.0f}s elapsed, {timeout_note}. No mouse input has been armed yet.'))
                        log_event(f'Final planning watchdog heartbeat: attempt={attempt.index}/{attempt.total} name={attempt.name!r} elapsed={elapsed:.1f}s remaining={remaining!r} mode={attempt.options.get("drawing_mode")} resolution={attempt.options.get("planning_resolution")} cpu={attempt.options.get("cpu_workers_resolved")} engine={attempt.options.get("cpu_engine")} target={attempt.options.get("target_stroke_count_resolved")}.')
                        if start_state and start_state.stalled(2.0):
                            _watch=start_state.watchdog_text(2.0)
                            log_event(f'Start Drawing watchdog: {_watch}')
                            self.events.put(('status',f'Start Drawing: {_watch}'))
                threading.Thread(target=heartbeat,daemon=True,name=f'imagedrawbot-plan-watchdog-{attempt.index}').start()
                def attempt_cancelled(deadline=attempt_deadline):
                    return self.stop.is_set() or self.closing or (deadline is not None and time.monotonic() >= deadline)
                try:
                    plan=make_test_plan(area[2:],attempt.options) if test else make_plan(original,area[2:],attempt.options,attempt_cancelled)
                    planning_done.set()
                    elapsed=time.monotonic()-attempt_started
                    if attempt.fallback:
                        self.events.put(('status',f'Watchdog fallback succeeded with {attempt.name} in {elapsed:.1f}s. Mouse input is still not armed until execution starts.'))
                    log_event(f"Final planning attempt {attempt.index}/{attempt.total} finished in {elapsed:.3f} s: {_plan_log_text(plan)}.")
                    break
                except InterruptedError:
                    planning_done.set()
                    if self.stop.is_set() or self.closing:
                        raise
                    if attempt_deadline is not None and time.monotonic() >= attempt_deadline:
                        last_timeout=attempt
                        log_event(f'Final planning attempt {attempt.index}/{attempt.total} timed out before mouse input was armed. name={attempt.name!r}.')
                        if attempt.index < attempt.total:
                            self.events.put(('status',f'{attempt.name} took too long. Retrying with safer fallback settings…'))
                            continue
                        raise ValueError('Planning watchdog stopped all attempts before mouse input. Try Planning resolution Standard, Target stroke count 1000–2500, CPU engine Threads, and Color layers Off.')
                    raise
                finally:
                    planning_done.set()
            if plan is None:
                label=last_timeout.name if last_timeout else 'no attempt'
                log_event(f'Final planning failed before mouse input was armed. last={label!r}.')
                raise ValueError('Final planning did not produce a plan. Lower planning resolution or use a smaller target stroke count.')
            publication.own(plan)
            release_source_snapshot(plan,transfer=True)
            if not test and not dry_run and plan.get('options',{}).get('auto_clear_canvas'):
                add_clear=True
                try:
                    from RenderResume import resolve_resume as _resolve_clear_resume
                    _clear_resume=_resolve_clear_resume(plan,(plan.get('options') or {}).get('render_resume_state'))
                    add_clear=not bool(_clear_resume.get('compatible') and _clear_resume.get('prelude_complete'))
                except Exception:
                    add_clear=True
                if add_clear:
                    clear_seconds=max(0.0,float(plan.get('options',{}).get('canvas_clear_estimate_seconds',0.0) or 0.0))
                    if clear_seconds:
                        plan['estimate']=float(plan.get('estimate',0.0) or 0.0)+clear_seconds
                        plan['options']['canvas_clear_estimate_included']=True
                        log_event(f'Automatic canvas clear added {clear_seconds:.2f}s to final draw-time estimate.')
            if dry_run:
                original_count=int(plan.get('count') or 0)
                plan=sample_dry_run_plan(plan, execution_seconds=DRY_RUN_EXECUTION_SECONDS)
                publication.own(plan)
                dm=plan.get('options') or {}
                self.events.put(('status',f"Fast Dry run: sampling up to {int(dm.get('dry_run_sample_paths',plan.get('count',0))):,} representative paths from {original_count:,}. Cursor test budget {DRY_RUN_EXECUTION_SECONDS:.0f}s. Reaching the budget is a normal PASS if no safety check fails. No clicks."))
                log_event(f"Dry-run route sampled: paths={dm.get('dry_run_sample_paths',plan.get('count'))}/{dm.get('dry_run_total_paths',original_count)} colors={dm.get('dry_run_sample_colors','n/a')}/{dm.get('dry_run_total_colors','n/a')} max_seconds={DRY_RUN_EXECUTION_SECONDS}.")
            log_event(f"Final planning finished in {time.monotonic()-started:.3f} s total using attempt={plan.get('options',{}).get('planning_attempt_name','Primary settings')!r}: {_plan_log_text(plan)}.")
            if start_state:start_state.transition('PLAN_READY','final deadline-aware plan built and validated')
            plan['preview_generation']=generation
            publication.publish(self.events)
            if not plan['count'] and not (plan['options'].get('background_fill_plan') or {}).get('enabled') and not plan['options'].get('fill_regions'):
                log_event('Final planning produced no drawable strokes or fills.')
                raise ValueError('No brush strokes or safe Fill regions were found. Choose a darker image for simple Paint sketch mode, or check the color settings.')
            if plan['options'].get('gartic_timer_deadline') is not None and plan['estimate']>plan['options']['gartic_timer_deadline']-time.monotonic():
                raise ValueError('Gartic timer is too close to expiry after planning. Start again in the next round.')
            _deadline_meta=plan.get('options',{}).get('adaptive_deadline_meta') or {}
            _effective_execution_estimate=float(_deadline_meta.get('effective_estimated_seconds',plan.get('estimate',0.0)) or plan.get('estimate',0.0) or 0.0)
            if not plan['options'].get('unlimited_time') and _effective_execution_estimate>options['max_seconds']:
                log_event(f"Drawing blocked by time limit: effective_estimate={_effective_execution_estimate:.1f}s raw={float(plan.get('estimate',0) or 0):.1f}s limit={options['max_seconds']:.1f}s.")
                raise ValueError('Conservative estimated drawing time exceeds the safe render budget. Lower quality or increase the time limit.')
            log_event(f"Guarded mouse execution starting: count={plan['count']} effective_estimate={_effective_execution_estimate:.1f}s raw_estimate={float(plan.get('estimate',0) or 0):.1f}s dry_run={dry_run!r}.")
            if start_state:
                start_state.transition('INPUT_ARMED','guarded input owner ready; entering execution')
                start_state.transition('DRAWING','mouse execution active')
            plan['options']['test_run']=bool(test)
            if test:
                plan['options']['visual_verification_enabled']=False
            def persist_checkpoint(payload):
                from SessionRecovery import save_render_progress
                save_render_progress(payload)
                self.events.put(('render_checkpoint',payload))
            plan['options'].pop('runtime_safety_report',None)
            try:
                execute_plan(plan,area,palette,guarded,self.stop,self.paused,lambda k,v:self.events.put((k,v)),dry_run=dry_run,keyboard=self.keyboard,
                             checkpoint=(None if (dry_run or test) else persist_checkpoint))
            finally:
                DrawBotApp._publish_runtime_safety_report(self,runtime_request,plan['options'])
            if start_state and not self.stop.is_set():start_state.transition('COMPLETED','render execution completed')
            if not dry_run and not test and not self.stop.is_set():
                try:
                    from SessionRecovery import clear_render_progress
                    clear_render_progress()
                    self.events.put(('render_resume_cleared',None))
                except Exception as error:log_event(f'Could not clear completed render resume state: {error!r}')
            log_event(f"Guarded mouse execution finished in {time.monotonic()-started:.3f} s total dry_run={dry_run!r}.")
            if dry_run and not self.stop.is_set():
                self.events.put(('dry_run_passed',True))
            if test and not self.stop.is_set():
                self.events.put(('test_passed',True))
        try:
            accepted=self.begin_worker('dry-run' if dry_run else 'draw',work,
                reset_stop=False,cleanup=release_worker_images)
        except BaseException:
            release_worker_images()
            self._draw_plan_publication=None
            DrawBotApp._runtime_safety_view(self).finish(runtime_request)
            DrawBotApp.refresh_runtime_safety_ui(self)
            raise
        if accepted:
            if not dry_run and not test:self.drop_in_sync_phase=DROP_SYNC_DRAWING
            try:self.root.iconify()
            except tk.TclError:pass
        else:
            release_worker_images()
            self._draw_plan_publication=None
            DrawBotApp._runtime_safety_view(self).finish(runtime_request)
            DrawBotApp.refresh_runtime_safety_ui(self)
            if self.stop.is_set():
                if start_state:start_state.transition('ABORTED','drawing start cancelled before worker handoff')
                self.status.set('Drawing start cancelled. No automatic restart.')

    def quick_start_hotkey(self):
        """F1 Quick Start: same setup guards as the buttons, without unsafe bypasses."""
        if self.activity or self.closing:return False
        now=time.monotonic();last=float(getattr(self,'quick_start_last_monotonic',0.0) or 0.0)
        if now-last<.70:return False
        self.quick_start_last_monotonic=now
        if DrawBotApp._automatic_paint_preparation(self):
            log_event('F1 Quick Start requested for Paint; using Prepare Paint & draw flow.')
            return DrawBotApp.start_full_drawing(self)
        ready,message=DrawBotApp._start_guard_ready(self,require_image=True)
        if not ready:
            self.status.set('F1 Quick Start blocked: '+message.replace('Start locked: ','',1))
            log_event('F1 Quick Start blocked: '+message)
            return False
        if not DrawBotApp._full_draw_unlocked(self):
            if not DrawBotApp.unlock_full_drawing(self):return False
        log_event('F1 Quick Start accepted after normal setup guards.')
        return DrawBotApp.start_full_drawing(self)

    def toggle_pause(self):
        if self.activity!='draw':return
        if self.paused.is_set():
            self.paused.clear();self.pause_button.configure(text='Pause · F6')
        else:
            self.paused.set();self.pause_button.configure(text='Resume · F6')
            self.status.set('Pausing after the current brush stroke. Wait until the status says Paused before moving the mouse.')

    def _request_stop(self):
        """Keyboard-thread-safe Stop: no Tk calls or resettable update token."""
        mobile=getattr(self,'mobile_preview_request',None)
        if mobile is not None:mobile['cancel'].set()
        discovery=getattr(self,'mobile_preview_discovery',None)
        if discovery is not None:discovery.cancel()
        request=getattr(self,'update_request',None)
        if isinstance(request,UpdateRequest):request.cancel()
        recheck=getattr(self,'result_recheck_request',None)
        if isinstance(recheck,ResultRecheckRequest):recheck.cancel()
        # Publish the reusable global signal only after the request has its
        # permanent cancellation; another worker may clear Stop immediately.
        self.stop.set()

    def cancel(self):
        DrawBotApp._request_stop(self)
        self.paint_start_request=None
        # Emergency stop also revokes native mouse permission immediately.
        DrawBotApp._close_smart_drop_overlay(self,'cancel/stop pressed')
        self.smart_drop_pending_payload=None
        self.smart_drop_generation=int(getattr(self,'smart_drop_generation',0))+1
        self.preview_generation=int(getattr(self,'preview_generation',0))+1
        publication=getattr(self,'_draw_plan_publication',None)
        if publication is not None:publication.reject()
        mouse=getattr(self,'mouse',None)
        if hasattr(mouse,'disarm_input'):
            try:mouse.disarm_input()
            except (OSError,RuntimeError):pass
        self.drop_action_pending=None
        DrawBotApp._disarm_manual_drop_in(self,'cancel/stop pressed')
        self.needs_plan=False
        DrawBotApp._disarm_full_draw(self,'cancel/stop pressed')
        DrawBotApp._cancel_after_attr(self,'preview_after')
        DrawBotApp._cancel_after_attr(self,'preview_render_after')
        DrawBotApp._cancel_browser_one_click(self,'Stop pressed')
        self.paused.clear()
        process=getattr(self,'mouse_probe_process',None)
        if process is not None:
            try:
                if process.poll() is None:process.terminate()
            except (OSError,AttributeError):pass
        palette_process=getattr(self,'palette_probe_process',None)
        if palette_process is not None:
            try:
                if palette_process.poll() is None:palette_process.terminate()
            except (OSError,AttributeError):pass
        if DrawBotApp._cancel_after_attr(self,'capture_job') and not getattr(self,'closing',False):
            self.set_busy(None)
        if not getattr(self,'closing',False):
            try:self.status.set('Stopping…' if self.activity else 'Stopped.')
            except tk.TclError:pass

    def launch_diagnostic_tool(self,filename,message):
        if self.activity:return
        import os,sys
        try:
            if sys.platform!='win32' or not hasattr(os,'startfile'):
                raise OSError('Diagnostic tools require Windows.')
            from RuntimePaths import resource_path
            path=resource_path(filename)
            if not path.is_file():raise OSError(f'{filename} is missing.')
            # Give Windows a literal file path. Building a CMD /c start command
            # interprets metacharacters such as & in otherwise valid directories.
            os.startfile(str(path),'open',cwd=str(path.parent))
            self.status.set(message)
        except (OSError,NotImplementedError) as error:
            self.status.set(f'Could not start {filename}: {error}')

    def _diagnostics_context(self):
        """Return bounded non-sensitive state for a local diagnostics ZIP."""
        def safe_get(variable, default=''):
            try:return variable.get()
            except Exception:return default
        profile_name=getattr(self,'_active_profile_name',None) or safe_get(self.game)
        return {
            'profile': profile_name, 'profile_key': PROFILES.get(profile_name,('',))[0],
            'activity': str(self.activity or 'idle'),
            'quality': safe_get(self.quality), 'speed': safe_get(self.speed),
            'precision': safe_get(self.precision), 'render_style': safe_get(self.render_style),
            'draw_quality': safe_get(self.draw_quality), 'human_mode': safe_get(self.human_mode),
            'gpu_mode': safe_get(self.gpu_mode), 'gpu_vram': safe_get(self.gpu_vram),
            'gpu_performance': safe_get(self.gpu_performance),
            'background_fill': safe_get(self.background_fill), 'fill_engine': safe_get(getattr(self,'fill_engine',None),'Auto'),
            'background_simplification': safe_get(self.background_simplification),
            'color_grouping': safe_get(self.color_grouping), 'color_workflow': safe_get(getattr(self,'color_workflow',None)),
            'stroke_optimizer': safe_get(getattr(self,'stroke_optimizer',None)), 'adaptive_detail': safe_get(getattr(self,'adaptive_detail',None)),
            'detail_zoom': safe_get(getattr(self,'detail_zoom',None),'Auto'), 'quick_sketch_style': safe_get(getattr(self,'quick_sketch_style',None),'Balanced'),
            'quick_sketch_fill_preference': safe_get(getattr(self,'quick_sketch_fill_preference',None),'Safe Fill First'),
            'hybrid_mode': safe_get(getattr(self,'hybrid_mode',None),'Auto Hybrid'),
            'visual_verification': safe_get(getattr(self,'visual_verification',None)),
            'color_rendering': safe_get(self.color_rendering), 'color_fidelity': safe_get(self.color_fidelity), 'color_layers': safe_get(self.color_layers),
            'custom_color_workflow': safe_get(self.custom_color_workflow), 'tool_strategy': safe_get(self.tool_strategy),
            'cpu_workers': safe_get(getattr(self,'cpu_workers',None)), 'cpu_engine': safe_get(getattr(self,'cpu_engine',None)),
            'ram_budget': safe_get(getattr(self,'ram_budget',None)), 'resource_scheduler': safe_get(getattr(self,'resource_scheduler',None),'Auto'),
            'drawing_mode': safe_get(self.mode), 'shape_model': safe_get(getattr(self,'shape_model',None)),
            'time_budget_mode': safe_get(getattr(self,'time_budget_mode',None)),
            'target_stroke_count': safe_get(getattr(self,'target_stroke_count',None)),
            'paint_single_color': bool(safe_get(self.paint_simple, False)), 'paint_tool': safe_get(self.paint_tool),
            'brush_px': safe_get(self.brush_px), 'time_limit_seconds': safe_get(self.max_seconds),
            'palette_ready': bool(self.palette_ready), 'drawing_area_selected': len(self.corners) == 2,
            'target_lock_valid': bool(DrawBotApp._target_lock_valid(self)),
        }

    # Backward-compatible alias for older tests/plugins; no network reporting remains.
    def _report_context(self):
        return self._diagnostics_context()

    def _runtime_safety_view(self):
        view=getattr(self,'_runtime_safety_report_view',None)
        if view is None:
            view=RuntimeSafetyView()
            self._runtime_safety_report_view=view
        return view

    def _begin_runtime_safety_request(self,label):
        request=DrawBotApp._runtime_safety_view(self).begin(label)
        DrawBotApp.refresh_runtime_safety_ui(self)
        return request

    def _publish_runtime_safety_report(self,request,options):
        # This worker-side envelope owns no plan/image references. Publication
        # failure must not replace the executor's original exception.
        try:
            result=capture_runtime_report(request,options)
            self.events.put(('runtime_safety_complete',result))
        except Exception as error:
            log_event(f'Runtime safety UI publication skipped: {error!r}')

    def refresh_runtime_safety_ui(self):
        if (getattr(self,'closing',False) or not hasattr(self,'runtime_safety_summary')
                or not hasattr(self,'runtime_safety_detail')):
            return
        try:
            view=DrawBotApp._runtime_safety_view(self)
            payload=view.current_or_history(load_latest_runtime_safety_report)
            summary,detail=view.presentation(payload,stopped=bool(getattr(self,'stop',None) and self.stop.is_set()))
            self.runtime_safety_summary.set(summary)
            self.runtime_safety_detail.set(detail)
        except Exception as error:
            self.runtime_safety_summary.set('Safety report status unavailable.')
            self.runtime_safety_detail.set(str(error)[:180])

    def open_safety_reports_folder(self):
        try:
            import os
            RUNTIME_SAFETY_REPORT_DIR.mkdir(parents=True,exist_ok=True)
            if hasattr(os,'startfile'): os.startfile(RUNTIME_SAFETY_REPORT_DIR)
            else: self.status.set(f'Safety reports: {RUNTIME_SAFETY_REPORT_DIR}')
        except OSError as error:
            self.status.set(f'Could not open safety reports folder: {error}')

    def open_latest_safety_report(self):
        if getattr(self,'closing',False):return
        view=DrawBotApp._runtime_safety_view(self)
        payload=view.current_or_history(load_latest_runtime_safety_report)
        if not payload:
            self.status.set('No current runtime safety report is available.' if view.local else
                            'No runtime safety report exists yet. Run Fast Dry run or Start drawing first.')
            return
        destination=payload.get('text_path') or payload.get('json_path')
        if not destination:
            self.status.set('The current runtime safety report was not saved. Its results remain visible in the safety card.')
            return
        path=Path(destination)
        if not path.is_file():
            self.status.set('The latest safety report file could not be found.');return
        try:
            import os
            if hasattr(os,'startfile'): os.startfile(path)
            else:self.status.set(f'Latest safety report: {path}')
        except OSError as error:self.status.set(f'Could not open safety report: {error}')

    def _update_request_current(self,request,*,phase=None):
        if not isinstance(request,UpdateRequest):return False
        if (self.closing or self.stop.is_set() or
                getattr(self,'update_request',None) is not request):
            request.cancel()
            return False
        return not request.is_cancelled() and (phase is None or request.phase==phase)

    def check_for_updates(self):
        if not DrawBotApp._profile_action_ready(self):
            self.status.set('Stop the current operation before checking for updates.');return False
        # This explicit new action may follow an earlier Stop. Any later Esc is
        # also recorded on the private request, before a worker can reuse Stop.
        previous=getattr(self,'update_request',None)
        if isinstance(previous,UpdateRequest):previous.cancel()
        self.stop.clear()
        request=UpdateRequest();self.update_request=request
        def cancelled():
            return not DrawBotApp._update_request_current(self,request)
        def work():
            from UpdateCenter import check_for_updates,download_installer
            if cancelled():raise InterruptedError('Update cancelled.')
            try:
                result=check_for_updates(cancelled=cancelled)
                if result.get('update_available'):
                    asset=result.get('installer')
                    if asset:
                        previous_percent=[-1]
                        def progress(done,total):
                            if cancelled():raise InterruptedError('Update cancelled.')
                            percent=round(done*100/total)
                            if percent!=previous_percent[0]:
                                previous_percent[0]=percent
                                self.events.put(('update_progress',(request,f'Downloading {asset["version"]}: {percent}%')))
                        result['installer_path']=download_installer(asset,cancelled=cancelled,progress=progress)
                    else:result['message']='A newer release exists, but its verified Windows installer is not available yet. Try again later or open Releases.'
            except InterruptedError:raise
            except Exception as error:result={'error':str(error),'message':'Update failed. Nothing was installed. Try again.'}
            if cancelled():raise InterruptedError('Update cancelled.')
            result['request']=request
            self.events.put(('update_check_complete',result))
        started=False
        try:
            if hasattr(self,'show_tools'):self.show_tools()
            self.update_summary.set('Checking GitHub Releases…')
            self.update_detail.set('A newer Windows release will be downloaded, verified and opened in the installer.')
            self.status.set('Checking Image Draw Bot releases on GitHub…')
            started=bool(self.begin_worker('update-check',work,reset_stop=False))
            return started
        finally:
            if not started:request.cancel()

    def _install_checked_update(self,payload):
        request=payload.get('request') if isinstance(payload,dict) else None
        if not DrawBotApp._update_request_current(self,request,phase='ready'):
            return False
        if self.activity:
            self.root.after(100,lambda:DrawBotApp._install_checked_update(self,payload));return False
        try:
            if self.save_settings() is False:
                raise OSError('Current settings could not be saved. Nothing was installed.')
        except Exception as error:
            if DrawBotApp._update_request_current(self,request,phase='ready'):
                self.update_summary.set(f'Could not save settings before update: {error}')
            return False
        # Settings publication can take time. Esc during it must survive the
        # worker handoff, and repeated callbacks may claim installation once.
        if (not DrawBotApp._update_request_current(self,request,phase='ready') or
                not request.begin_install()):
            return False
        def cancelled():
            return not DrawBotApp._update_request_current(self,request,phase='installing')
        def work():
            from UpdateCenter import launch_installer
            if cancelled():raise InterruptedError('Update cancelled.')
            launch_installer(payload['installer_path'],payload['installer'],cancelled=cancelled)
            # The process has really started. A later Stop cannot undo it, so
            # deliver the existing close-for-update handoff exactly once.
            if request.mark_started():self.events.put(('update_installer_started',request))
        started=False
        try:
            self.update_summary.set('Verifying installer and starting the update…')
            started=bool(self.begin_worker('update-install',work,reset_stop=False))
            return started
        finally:
            if not started:request.cancel()

    def open_latest_release_page(self):
        import webbrowser
        url=str(getattr(self,'latest_release_url','') or 'https://github.com/Vxiey/Image-Draw-Bot/releases')
        if not url.startswith('https://github.com/Vxiey/Image-Draw-Bot/'):
            url='https://github.com/Vxiey/Image-Draw-Bot/releases'
        try:
            opened=webbrowser.open(url,new=2)
            if not opened:self.status.set(f'Releases: {url}')
        except Exception as error:
            self.status.set(f'Could not open GitHub Releases: {error}')

    def collect_diagnostics(self):
        if self.activity:
            self.status.set('Stop the current operation before creating diagnostics.');return
        self.status.set('Creating sanitized diagnostics package…')
        context=self._diagnostics_context()
        def work():
            from DiagnosticsPackage import create_diagnostics_package
            path=create_diagnostics_package(context,cancelled=self.stop.is_set)
            if self.stop.is_set():raise InterruptedError('Diagnostics export cancelled.')
            self.events.put(('diagnostics_ready',str(path)))
        self.begin_worker('diagnostics',work)

    def enable_crash_dumps(self):
        self.launch_diagnostic_tool('Enable-Crash-Dumps.bat','Windows .dmp configuration opened. Follow the instructions in the window.')

    def open_app_data_folder(self):
        try:
            import os
            folder=data_dir();folder.mkdir(parents=True,exist_ok=True)
            if hasattr(os,'startfile'):
                os.startfile(folder)
            else:
                self.status.set(f'App data: {folder}')
        except OSError as error:
            self.status.set(f'Could not open app data folder: {error}')

    def maybe_auto_hardware_benchmark(self):
        """Run Step 22 automatically on first launch or after hardware/runtime changes.

        The signature check itself runs off the Tk thread because Windows CIM and
        GPU runtime discovery can take a moment. Manual settings are never changed
        by this automatic pass; only the local per-machine recommendation is saved.
        """
        if self.activity or self.closing or getattr(self, 'hardware_benchmark_running', False):
            return
        def check():
            try:
                needed, reason = profile_needs_benchmark()
                self.events.put(('hardware_profile_check', {'needed': bool(needed), 'reason': str(reason)}))
            except Exception as error:
                self.events.put(('hardware_profile_check', {'needed': False, 'reason': f'Hardware profile check failed safely: {error}'}))
        threading.Thread(target=check, daemon=True, name='hardware-profile-check').start()

    def refresh_auto_tuner_ui(self):
        try:
            result=load_tune_result()
        except Exception as error:
            result=None
            log_event(f'Could not read performance auto tuner result: {error!r}')
        if not result:
            self.auto_tune_summary.set('Universal Hardware Auto Benchmark has not been run on this machine yet.')
            self.auto_tune_detail.set('Benchmarks CPU/RAM plus NVIDIA, AMD and Intel GPU backends locally. CPU fallback is always available.')
            return
        try:
            self.auto_tune_summary.set(format_tune_summary(result))
            rec=dict(result.get('recommendation') or {})
            hardware=dict(result.get('hardware_profile') or {})
            detail=str(rec.get('reason') or 'Saved local recommendation is ready.')
            if hardware:
                detail += ' ' + format_universal_hardware_summary(hardware)
            self.auto_tune_detail.set(detail)
        except Exception as error:
            self.auto_tune_summary.set('Saved tuner result could not be displayed.')
            self.auto_tune_detail.set(str(error))

    def run_performance_auto_tuner(self, apply=False, automatic=False):
        if self.closing or (automatic and self.stop.is_set()):return False
        if self.activity:
            self.status.set('Stop the current operation before running the Universal Hardware Auto Benchmark.')
            return
        if getattr(self, 'hardware_benchmark_running', False):
            self.status.set('Universal Hardware Auto Benchmark is already running.')
            return
        self.hardware_benchmark_running = True
        self.status.set('Universal Hardware Auto Benchmark: testing CPU/RAM plus NVIDIA, AMD and Intel compute backends locally…')
        self.auto_tune_summary.set('Benchmark running…')
        self.auto_tune_detail.set('Testing safe worker counts, RAM headroom, CUDA and OpenCL where the installed GPU driver supports them.')
        def work():
            try:
                result=run_auto_tune(gpu_benchmark=gpu_benchmark, save=True,cancelled=self.stop.is_set)
                if self.stop.is_set():raise InterruptedError()
                self.events.put(('performance_auto_tune_complete',{'result':result,'apply':bool(apply),'automatic':bool(automatic)}))
            except InterruptedError:
                self.events.put(('performance_auto_tune_complete',{'cancelled':True}))
            except Exception as error:
                self.events.put(('performance_auto_tune_complete',{'error':f'{type(error).__name__}: {error}','apply':False}))
        started=False
        try:
            started=bool(self.begin_worker('performance-auto-tuner',work))
            return started
        finally:
            if not started:self.hardware_benchmark_running=False

    def apply_performance_tune(self, result=None, *, _from_benchmark=False):
        # Only the completed benchmark's handler may apply while its tracked
        # worker still awaits done. The visible Apply button requires idle UI.
        if _from_benchmark:
            ready=(self.activity=='performance-auto-tuner' and not self.closing and
                   not self.stop.is_set() and
                   getattr(self,'pending_clear_drawing',None) is None and
                   getattr(self,'profile_change_after',None) is None and
                   not getattr(self,'profile_change_in_progress',False))
        else:
            ready=DrawBotApp._profile_action_ready(self)
        if not ready:return False
        previous={}
        transition=getattr(self,'profile_change_in_progress',False)
        try:
            payload=result if result is not None else load_tune_result()
            if not payload:
                self.status.set('No saved Universal Hardware Auto Benchmark recommendation is available yet.')
                return False
            rec=dict(payload.get('recommendation') or {})
            defaults={'cpu_workers':'Auto','cpu_engine':'Threads','ram_budget':'Auto',
                      'ram_custom_mb':'4096','planning_resolution':'High',
                      'resource_scheduler':'Benchmark recommendations','gpu_mode':'CPU',
                      'gpu_vram':'Auto','gpu_performance':'Balanced'}
            proposed={name:str(rec.get(name) or default) for name,default in defaults.items()}
            workers=int(rec.get('cpu_workers_effective',1) or 1)
            previous={name:getattr(self,name).get() for name in proposed}
            changed=any(previous[name]!=value for name,value in proposed.items())
            # One accepted settings transaction, without intermediate trace
            # callbacks invalidating the plan or scheduling work during rollback.
            self.profile_change_in_progress=True
            try:
                for name,value in proposed.items():getattr(self,name).set(value)
            finally:
                self.profile_change_in_progress=transition
            if self.save_settings() is False:
                raise OSError('The recommendation could not be saved; current settings were restored.')
        except (tk.TclError, ValueError, TypeError, OSError, RuntimeError) as error:
            self.profile_change_in_progress=True
            try:
                for name,value in previous.items():
                    try:getattr(self,name).set(value)
                    except (tk.TclError,RuntimeError) as restore_error:
                        log_event(f'Hardware recommendation rollback failed for {name}: {restore_error!r}')
            finally:
                self.profile_change_in_progress=transition
            self.status.set(f'Could not apply hardware benchmark recommendation: {error}')
            return False
        if changed:
            DrawBotApp._cancel_browser_one_click(self,'hardware recommendation applied')
            DrawBotApp._mark_plan_stale(self,'Hardware planning settings changed. Build preview or Start Drawing to use the saved recommendation.')
            if hasattr(self,'recovery_checkpoint_after'):
                DrawBotApp._schedule_recovery_checkpoint(self,delay=300)
            from NumericEntryCommit import sync_numeric_commits
            sync_numeric_commits(self)
        self.refresh_auto_tuner_ui()
        self.status.set(f'Hardware profile applied: {workers} benchmark-selected planning workers · RAM {self.ram_budget.get()} · current renderer {self.gpu_mode.get()} · {self.planning_resolution.get()} planning.')
        return True

    def test_gpu_acceleration(self):
        if self.closing:return False
        if self.activity:
            self.status.set('Stop the current operation before testing GPU acceleration.')
            return
        requested=self.gpu_mode.get(); vram=self.gpu_vram.get(); performance=self.gpu_performance.get()
        self.status.set('Testing the selected real compute backend with a local synthetic workload…')
        def work():
            try:
                if requested == 'NVIDIA CUDA':
                    result=gpu_benchmark(requested,1024,vram,performance,cancelled=self.stop.is_set)
                    if result.get('used_gpu'):
                        cc=f" · CC {result.get('compute_capability')}" if result.get('compute_capability') else ''
                        sms=f" · {result.get('multiprocessors')} SMs" if result.get('multiprocessors') else ''
                        message=(f"CUDA ready: {result.get('device')}{cc}{sms} · {result.get('throughput_mp_s')} MP/s · "
                                 f"{result.get('elapsed_ms')} ms · VRAM budget {result.get('vram_budget_mb')} MB. CPU fallback remains available.")
                    else:
                        message=(f"CUDA unavailable; CPU fallback active. {result.get('reason') or 'No verified NVIDIA CUDA backend.'}")
                else:
                    import numpy as _np
                    from UniversalGpuAcceleration import perceptual_pair, edge_magnitude, palette_indices_rgba
                    from PIL import Image as _Image
                    n=512
                    yy,xx=_np.mgrid[0:n,0:n]
                    rgb=_np.stack(((xx*13+yy*3)%256,(xx*5+yy*17)%256,(xx*23+yy*7)%256),axis=-1).astype(_np.uint8)
                    src=rgb.astype(_np.float32)/255.0; dst=_np.roll(src,1,axis=1)
                    _sl,_dl,_de,de_route=perceptual_pair(src,dst,gpu_mode=requested,cancelled=self.stop.is_set)
                    _edge,edge_route=edge_magnitude(src[...,1],gpu_mode=requested,cancelled=self.stop.is_set)
                    palette=((0,0,0),(255,255,255),(255,0,0),(0,255,0),(0,0,255),(255,255,0))
                    with closing(_Image.fromarray(_np.dstack((rgb,_np.full((n,n),255,dtype=_np.uint8))))) as rgba:
                        (_idx,_mask),pal_route=palette_indices_rgba(rgba,palette,range(len(palette)),[False]*len(palette),gpu_mode=requested,cancelled=self.stop.is_set)
                    routes=[de_route,edge_route,pal_route]
                    names=[]
                    for route in routes:
                        label=f"{route.get('backend','CPU/NumPy')} · {route.get('device','CPU')}"
                        if label not in names:names.append(label)
                    message=('Step 23 compute test ready: '+ ' | '.join(names) +
                             '. OKLab/ΔE, edge and palette workloads all completed; each retains CPU fallback.')
                if self.stop.is_set():raise InterruptedError('Compute test cancelled.')
                self.events.put(('status',message))
            except InterruptedError:
                raise
            except Exception as error:
                self.events.put(('status',f'Compute test failed safely; CPU fallback remains available: {error}'))
        return self.begin_worker('gpu-benchmark',work)

    def test_resource_allocation(self):
        if self.closing:return False
        if self.activity:
            self.status.set('Stop the current operation before testing resource allocation.')
            return
        try:
            requested=(self.cpu_workers.get(),self.cpu_engine.get(),self.ram_budget.get(),self.ram_custom_mb.get())
            allocation=resolve_allocation(*requested)
            available=allocation.get('available_ram_mb')
            available_text=f" · available RAM ~{available:,} MB" if isinstance(available,int) else ""
            self.status.set(
                f"Resource allocation ready: CPU {allocation['cpu_workers_resolved']} / {allocation['logical_cpus']} logical threads · "
                f"engine {allocation['cpu_engine']} · RAM budget {allocation['ram_budget_mb']:,} MB{available_text}. "
                "Running a short CPU worker benchmark…"
            )
        except Exception as error:
            self.status.set(f'Resource allocation setting is invalid: {error}')
            return
        def work():
            try:
                result=benchmark_allocation(*requested,cancelled=self.stop.is_set)
                schedule=benchmark_scheduler(result,cancelled=self.stop.is_set)
                if self.stop.is_set():raise InterruptedError('CPU/RAM test cancelled.')
                self.events.put(('status',
                    f"CPU/RAM test complete: {result['benchmark_tasks']} task(s) on {result['benchmark_backend']} · "
                    f"{result['benchmark_score']} Mloops/s · {result['benchmark_elapsed_ms']} ms · "
                    f"Resource Scheduler saved recommendation: {schedule['recommended_workers']} worker(s) · "
                    f"RAM budget {result['ram_budget_mb']:,} MB. Use Universal Hardware Auto Benchmark to compare NVIDIA/AMD/Intel compute backends."))
            except InterruptedError:
                raise
            except Exception as error:
                self.events.put(('status',f'CPU/RAM benchmark failed safely: {error}'))
        return self.begin_worker('resource-benchmark',work)

    def run_performance_benchmark(self):
        """Benchmark the current planning pipeline without arming mouse input."""
        if not DrawBotApp._profile_action_ready(self):
            if self.activity and not self.closing:
                self.status.set('Stop the current operation before running the performance benchmark.')
            return False
        self.stop.clear()
        try:
            options=self.options()
        except ValueError as error:
            self.status.set(str(error));return False
        if self.stop.is_set() or self.closing:return False
        original=None
        started=False
        def release_original():
            nonlocal original
            snapshot=original;original=None
            if snapshot is not None:snapshot.close()
        try:
            original=self.original.copy() if self.original is not None else None
            if original is None:
                from PIL import Image,ImageDraw
                original=Image.new('RGBA',(640,480),'white')
                pen=ImageDraw.Draw(original)
                try:
                    pen.rectangle((45,45,595,435),fill=(235,235,245,255))
                    pen.ellipse((120,70,520,430),fill=(70,130,210,255))
                    pen.rectangle((230,160,410,390),fill=(235,90,70,255))
                    pen.line((90,400,550,90),fill=(20,20,20,255),width=9)
                finally:
                    # A retained startup/paint traceback must not keep a second
                    # owner of the synthetic source's native pixel storage.
                    pen.draw=None;pen.im=None;pen._image=None
            else:
                original.thumbnail((640,480))
            target=(800,450)
            self.status.set('Running planner benchmark… No mouse input can be armed by this test.')
            def work():
                plan=None
                try:
                    begin=time.monotonic()
                    plan=make_plan(original,target,dict(options),self.stop.is_set)
                    elapsed=time.monotonic()-begin
                    if self.stop.is_set():raise InterruptedError()
                    profile=plan.get('performance_profile') or {}
                    phase,phase_seconds=profiler_dominant_phase(profile)
                    phase_name=(phase or 'unknown').replace('_',' ')
                    source=max(1,int(plan.get('source_count',0) or 0))
                    throughput=source/max(elapsed,.001)
                    benchmark_options=plan.get('options') or {}
                    advanced=benchmark_options.get('advanced_color_meta') or {}
                    portrait=benchmark_options.get('portrait_stats') or {}
                    backend=advanced.get('acceleration_backend') or portrait.get('acceleration_backend') or advanced.get('cpu_backend') or 'CPU'
                    device=advanced.get('acceleration_device') or portrait.get('acceleration_device') or ''
                    backend_text=f"{backend}{' · '+str(device) if device else ''}"
                    text=(f"Planner benchmark: {elapsed:.2f}s total · {throughput:,.0f} source strokes/s · backend {backend_text} · "
                          f"slowest phase: {phase_name} {phase_seconds:.2f}s. "
                          f"{format_performance_profile(profile, compact=True)}")
                    log_event('Performance benchmark complete: '+text)
                    self.events.put(('status',text))
                    self.events.put(('performance_benchmark',{'text':text,'profile':profile,'elapsed':elapsed,'source':source,'count':plan.get('count',0)}))
                except InterruptedError:
                    raise
                except Exception as error:
                    if self.stop.is_set():raise InterruptedError() from None
                    self.events.put(('status',f'Performance benchmark failed safely: {error}'))
                finally:
                    DrawBotApp._release_plan_images(self,plan)
            started=bool(self.begin_worker('performance-benchmark',work,reset_stop=False,cleanup=release_original))
            return started
        finally:
            if not started:release_original()

    def run_benchmark_suite(self):
        """Run deterministic preview/accuracy/deadline benchmarks without mouse input."""
        if not DrawBotApp._profile_action_ready(self):
            if self.activity and not self.closing:
                self.status.set('Stop the current operation before running the benchmark suite.')
            return False
        self.stop.clear()
        try:
            options=self.options()
        except ValueError as error:
            self.status.set(str(error));return False
        if self.stop.is_set() or self.closing:return False
        self.status.set('Running Step 10 benchmark suite locally… No mouse input, screen capture, network or telemetry.')
        self.benchmark_suite_text.set('Benchmark suite running…')
        def work():
            try:
                from BenchmarkSuite import run as run_suite, format_result
                result=run_suite(make_plan,dict(options),cancelled=self.stop.is_set)
                if self.stop.is_set():raise InterruptedError()
                text=format_result(result)
                log_event('Step 10 benchmark suite complete: '+text.replace('\n',' | '))
                self.events.put(('benchmark_suite',{'text':text,'result':result}))
            except InterruptedError:
                raise
            except Exception as error:
                if self.stop.is_set():raise InterruptedError() from None
                self.events.put(('benchmark_suite',{'text':f'Benchmark suite failed safely: {error}','result':{'error':str(error)}}))
        return bool(self.begin_worker('benchmark-suite',work,reset_stop=False))

    def run_golden_image_regression(self):
        """Run Step 17 golden-image regression tests without mouse/screen input."""
        if not DrawBotApp._profile_action_ready(self):
            if self.activity and not self.closing:
                self.status.set('Stop the current operation before running golden image regression.')
            return False
        self.stop.clear()
        try:
            options=self.options()
        except ValueError as error:
            self.status.set(str(error));return False
        if self.stop.is_set() or self.closing:return False
        self.status.set('Running Step 17 golden-image regression locally… No mouse input, screen capture, network or telemetry.')
        try:self.benchmark_suite_text.set('Golden image regression running…')
        except (tk.TclError,AttributeError):pass
        def work():
            try:
                from GoldenImageRegression import run as run_golden, format_result, ensure_local_golden_images
                ensure_local_golden_images(overwrite=False,cancelled=self.stop.is_set)
                if self.stop.is_set():raise InterruptedError()
                result=run_golden(make_plan,dict(options),cancelled=self.stop.is_set)
                if self.stop.is_set():raise InterruptedError()
                text=format_result(result)
                log_event('Step 17 golden image regression complete: '+text.replace('\n',' | '))
                self.events.put(('golden_regression',{'text':text,'result':result}))
            except InterruptedError:
                raise
            except Exception as error:
                if self.stop.is_set():raise InterruptedError() from None
                self.events.put(('golden_regression',{'text':f'Golden image regression failed safely: {error}','result':{'error':str(error)}}))
        return bool(self.begin_worker('golden-regression',work,reset_stop=False))

    def clear_gpu_cache(self):
        if not self._profile_action_ready():
            return False
        self.stop.clear()
        mode = self.gpu_mode.get()
        self.status.set('Clearing unused GPU caches…')
        def work():
            result = gpu_clear_cache(mode, cancelled=self.stop.is_set)
            if self.stop.is_set():
                raise InterruptedError()
            if result.get('cleared'):
                before = result.get('before_free_bytes', 0) / (1024 * 1024)
                after = result.get('after_free_bytes', 0) / (1024 * 1024)
                text = (f"GPU cache cleanup finished. Unused CUDA pool: {before:.2f} MB → {after:.2f} MB; "
                        f"{len(result.get('cuda_devices', ()))} device(s), "
                        f"{result.get('pinned_pools', 0)} pinned pool(s), "
                        f"{result.get('opencl_entries', 0)} OpenCL cache entry/entries cleared.")
            else:
                text = result.get('reason') or 'No previously used GPU caches are available.'
            if result.get('opencl_busy'):
                text += ' Active OpenCL resources were kept.'
            if result.get('errors'):
                text += ' Some resources could not be cleared: ' + '; '.join(result['errors'][:3])
            self.events.put(('status', text))
        return bool(self.begin_worker('gpu-cache', work, reset_stop=False))

    def run_self_test(self):
        """Run Image Draw Bot's built-in self-test out of process.

        Developer tooling must never block Tk's main loop, so the result is
        returned through the existing worker-event queue.
        """
        if self.activity or self.closing:return
        import subprocess,sys
        def work():
            try:
                if getattr(sys,'frozen',False):
                    command=[sys.executable,'--self-test']
                else:
                    command=[sys.executable,str(Path(__file__).resolve()),'--self-test']
                result=subprocess.run(command,capture_output=True,text=True,timeout=90,check=False)
                output=(result.stdout or result.stderr or '').strip().splitlines()
                tail=output[-1] if output else 'No output.'
                if result.returncode==0:
                    self.events.put(('status',f'Self-test passed. {tail}'))
                else:
                    self.events.put(('status',f'Operation failed: self-test exited with code {result.returncode}. {tail}'))
            except (OSError,subprocess.SubprocessError) as error:
                self.events.put(('status',f'Operation failed: self-test could not run: {error}'))
        self.begin_worker('self-test',work)

    def show_version_history(self):
        import customtkinter as ctk
        from UiCompatibility import scoped_toplevel
        window=scoped_toplevel(self.root)
        window.title('Image Draw Bot version history')
        from WorkspaceLayout import fit_window
        fit_window(window,preferred=(850,680),minimum=(720,520));window.transient(self.root)
        window.configure(fg_color='#101319')
        card=ctk.CTkFrame(window,fg_color='#1a202b',corner_radius=18)
        card.pack(fill='both',expand=True,padx=18,pady=18)
        ctk.CTkLabel(card,text='Version history',font=('Segoe UI',24,'bold'),text_color='#f0f4fb').pack(anchor='w',padx=22,pady=(18,4))
        ctk.CTkLabel(card,text='Local packaged release timeline. No network request is made.',font=('Segoe UI',12),text_color='#a6b2c5').pack(anchor='w',padx=22,pady=(0,12))
        box=ctk.CTkTextbox(card,wrap='word',font=('Consolas',11),fg_color='#101319',text_color='#dbe5f4',corner_radius=12)
        box.pack(fill='both',expand=True,padx=22,pady=(0,14))
        box.insert('1.0',read_version_history())
        box.configure(state='disabled')
        row=ctk.CTkFrame(card,fg_color='transparent');row.pack(fill='x',padx=22,pady=(0,16))
        ctk.CTkButton(row,text='Close',command=window.destroy,fg_color='#98edce',hover_color='#b2f6de',text_color='#15382d').pack(side='right')

    def show_about(self):
        import customtkinter as ctk
        from UiCompatibility import scoped_toplevel
        from RuntimePaths import is_frozen
        window=scoped_toplevel(self.root)
        window.title('About Image Draw Bot')
        from WorkspaceLayout import fit_window
        fit_window(window,preferred=(610,500),minimum=(480,400));window.transient(self.root)
        window.configure(fg_color='#101319')
        card=ctk.CTkFrame(window,fg_color='#1a202b',corner_radius=18)
        card.pack(fill='both',expand=True,padx=22,pady=22)
        ctk.CTkLabel(card,text='D',width=58,height=58,corner_radius=16,fg_color='#315c50',font=('Segoe UI',28,'bold'),text_color='#f0f4fb').pack(anchor='w',padx=24,pady=(24,10))
        ctk.CTkLabel(card,text='Image Draw Bot',font=('Segoe UI',26,'bold'),text_color='#f0f4fb').pack(anchor='w',padx=24)
        ctk.CTkLabel(card,text=f'{APP_VERSION} · {BUILD_CHANNEL.capitalize()} channel',font=('Segoe UI',13),text_color='#98edce').pack(anchor='w',padx=24,pady=(2,14))
        try:
            gpu=acceleration_info(self.gpu_mode.get(),self.gpu_vram.get(),self.gpu_performance.get())
            gpu_text=(f'{gpu.backend} · {gpu.device} · CC {gpu.compute_capability or "?"} · '
                      f'{gpu.multiprocessors or "?"} SMs · VRAM budget {gpu.vram_budget_mb or 0} MB · {gpu.cuda_execution or "CUDA"}'
                      if gpu.accelerated else 'CPU fallback')
        except Exception:
            gpu_text='CPU fallback'
        try:
            allocation=resolve_allocation(self.cpu_workers.get(),self.cpu_engine.get(),self.ram_budget.get(),self.ram_custom_mb.get())
            resource_text=f"CPU planning: {allocation['cpu_workers_resolved']} / {allocation['logical_cpus']} logical threads · {allocation['cpu_engine']} · RAM {allocation['ram_budget_mb']} MB"
        except Exception:
            resource_text='CPU planning: default allocation'
        details=(f'Build: {"Windows EXE" if is_frozen() else "Python source"}\n'
                 'Diagnostics: local only · no telemetry / report upload\n'
                 f'Image analysis: {gpu_text}\n'
                 f'{resource_text}\n'
                 f'App data: {data_dir()}\n\n'
                 'Mouse automation is intentionally disarmed until you explicitly start a test or drawing. '
                 'Normal Microsoft Paint use does not require administrator rights.')
        ctk.CTkLabel(card,text=details,font=('Segoe UI',12),text_color='#a6b2c5',justify='left',anchor='w',wraplength=520).pack(fill='x',padx=24,pady=(0,18))
        row=ctk.CTkFrame(card,fg_color='transparent');row.pack(fill='x',padx=24,pady=(0,22))
        ctk.CTkButton(row,text='Open app data',command=self.open_app_data_folder,fg_color='#252e3e',hover_color='#36445b').pack(side='left')
        ctk.CTkButton(row,text='How to use',command=self.help,fg_color='#252e3e',hover_color='#36445b').pack(side='left',padx=8)
        ctk.CTkButton(row,text='Version history',command=self.show_version_history,fg_color='#252e3e',hover_color='#36445b').pack(side='left')
        ctk.CTkButton(row,text='Close',command=window.destroy,fg_color='#98edce',hover_color='#b2f6de',text_color='#15382d').pack(side='right')


    def _beginner_setup_steps(self):
        """Build the Step 20 user-facing setup checklist without native input."""
        try: profile=self.game.get()
        except Exception: profile='Other drawing app'
        try:
            palette_ready=bool(getattr(self,'palette_ready',False) or bypasses_palette(self))
        except Exception:
            palette_ready=bool(getattr(self,'palette_ready',False))
        try: tool_ready=bool(self._paint_tool_preflight_ready())
        except Exception: tool_ready=False
        try: area_ready=len(getattr(self,'corners',()))==2
        except Exception: area_ready=False
        try: locked=bool(self._target_lock_valid())
        except Exception: locked=False
        try: preflight=bool(self._safety_preflight_valid())
        except Exception: preflight=False
        try: dryrun=bool(self._dry_run_valid())
        except Exception: dryrun=False
        try: unlocked=bool(self._full_draw_unlocked())
        except Exception: unlocked=False
        from BeginnerSetupWizard import build_setup_wizard
        return build_setup_wizard(profile_name=profile,image_loaded=self.original is not None,
                                  tools_ready=tool_ready,palette_ready=palette_ready,area_ready=area_ready,
                                  small_test_passed=bool(getattr(self,'small_test_passed',False)),
                                  target_locked=locked,preflight_passed=preflight,dry_run_passed=dryrun,
                                  full_draw_unlocked=unlocked,activity=getattr(self,'activity',None),
                                  prepare_on_start=DrawBotApp._automatic_paint_preparation(self))

    def refresh_beginner_setup_wizard(self):
        """Refresh the compact setup-wizard status line."""
        try:
            from BeginnerSetupWizard import format_setup_status
            self.setup_wizard_text.set(format_setup_status(DrawBotApp._beginner_setup_steps(self)))
        except Exception as error:
            try:self.setup_wizard_text.set(f'Setup wizard unavailable: {error}')
            except Exception:pass

    def show_beginner_setup_wizard(self):
        """Open the Step 20 beginner setup wizard dialog."""
        if self.closing:return
        import customtkinter as ctk
        from UiCompatibility import scoped_toplevel
        from BeginnerSetupWizard import format_wizard_dialog
        from ProfilePolish import profile_release_warnings
        steps=DrawBotApp._beginner_setup_steps(self)
        try:cal_state=self.options().get('calibration_state')
        except Exception:cal_state={}
        text=format_wizard_dialog(steps,profile_warnings=profile_release_warnings(self.game.get(),cal_state))
        window=scoped_toplevel(self.root)
        window.title('Beginner setup wizard')
        from WorkspaceLayout import fit_window
        fit_window(window,preferred=(760,680),minimum=(640,520));window.transient(self.root)
        window.configure(fg_color='#101319')
        card=ctk.CTkFrame(window,fg_color='#1a202b',corner_radius=18)
        card.pack(fill='both',expand=True,padx=18,pady=18)
        ctk.CTkLabel(card,text='Beginner setup wizard',font=('Segoe UI',24,'bold'),text_color='#f0f4fb').pack(anchor='w',padx=22,pady=(18,4))
        ctk.CTkLabel(card,text='Shows what is missing before Start. No mouse input, screenshot or network request is used.',font=('Segoe UI',12),text_color='#a6b2c5').pack(anchor='w',padx=22,pady=(0,12))
        box=ctk.CTkTextbox(card,wrap='word',font=('Consolas',11),fg_color='#101319',text_color='#dbe5f4',corner_radius=12)
        box.pack(fill='both',expand=True,padx=22,pady=(0,14))
        box.insert('1.0',text);box.configure(state='disabled')
        row=ctk.CTkFrame(card,fg_color='transparent');row.pack(fill='x',padx=22,pady=(0,16))
        ctk.CTkButton(row,text='Build preview',command=lambda:(window.destroy(),self.request_preview()),fg_color='#252e3e',hover_color='#36445b').pack(side='left')
        ctk.CTkButton(row,text='Close',command=window.destroy,fg_color='#98edce',hover_color='#b2f6de',text_color='#15382d').pack(side='right')

    def show_welcome(self):
        if self.closing or self.activity:return
        from GettingStarted import show_guide
        show_guide(self)

    def help(self):
        self.show_welcome()

    def _release_plan_images(self,plan):
        """Release plan images while preserving the current UI's image owners."""
        from AutoSketchBudget import _release_trial
        retained={name:getattr(self,name,None) for name in
                  ('original','upscale_original','background_removal_original')}
        _release_trial(plan,retained['original'],retained,getattr(self,'plan',None))

    def _discard_worker_result(self,kind,value):
        """Release rejected worker-owned images while retaining live UI owners."""
        if kind=='result_recheck_complete' and isinstance(value,ResultRecheckResult):
            value.request.release()
            return
        if kind=='recovery_image_prepared':
            try:value.cancel()
            except OSError as error:log_event(f'Recovery staging cleanup delayed: {error!r}')
            if value is getattr(self,'_recovery_image_job',None):self._recovery_image_job=None
            return
        from PIL import Image
        retained={name:getattr(self,name,None) for name in
                  ('original','upscale_original','background_removal_original')}
        if kind=='planned':
            publication=getattr(self,'_draw_plan_publication',None)
            if publication is not None and publication.reject(value):return
            DrawBotApp._release_plan_images(self,value)
            return
        candidate=None
        if kind in ('loaded','pasted','upscaled') and isinstance(value,(list,tuple)) and value:
            candidate=value[0]
        elif kind=='recovery_loaded' and isinstance(value,(list,tuple)) and len(value)==2:
            candidate=value[1]
        elif kind=='background_removed':candidate=getattr(value,'image',None)
        elif kind=='screen':candidate=value
        if isinstance(candidate,Image.Image) and all(candidate is not image for image in retained.values()):
            candidate.close()

    def _handle_event(self,kind,value):
        recheck_done_request=None
        if (kind=='done' and isinstance(value,tuple) and len(value)==2 and value[0]=='result-recheck'):
            _,recheck_done_request=value
            if recheck_done_request is not getattr(self,'result_recheck_request',None):
                if isinstance(recheck_done_request,ResultRecheckRequest):recheck_done_request.release()
                return
            value='result-recheck'
        elif kind=='done' and value=='result-recheck':
            # A re-check completion always carries its private worker identity.
            return
        browser_done_request=None
        if (kind=='done' and isinstance(value,tuple) and len(value)==2 and
                value[0]=='browser-one-click-setup'):
            _,browser_done_request=value
            if browser_done_request is not getattr(self,'browser_one_click_worker_request',None):
                log_event('Ignored Browser One-Click completion from an older worker.')
                return
            value='browser-one-click-setup'
        elif (kind=='done' and value=='browser-one-click-setup' and
                getattr(self,'browser_one_click_worker_request',None) is not None):
            log_event('Ignored Browser One-Click completion without its worker identity.')
            return
        if getattr(self,'pending_clear_drawing',None) is not None:
            if kind=='done':
                if recheck_done_request is not None:DrawBotApp._finish_result_recheck(self,recheck_done_request)
                if browser_done_request is not None:self.browser_one_click_worker_request=None
                if value=='performance-auto-tuner':self.hardware_benchmark_running=False
                if value=='recovery-clear':self._recovery_clear_previous_suppression=None
                self.activity=None;self.worker=None
                if value in ('draw','dry-run'):self._draw_plan_publication=None
                screen_window=getattr(self,'screen_task_window',None)
                if screen_window is not None:screen_window.restore()
            else:DrawBotApp._discard_worker_result(self,kind,value)
            return
        stop=getattr(self,'stop',None)
        if stop is not None and stop.is_set() and kind in ('status','progress','deadline_telemetry'):
            # Status already queued by a worker must not undo the user's Stop.
            # The matching completion event below confirms when it has exited.
            return
        if (stop is not None and stop.is_set() and kind=='draw_timer'
                and isinstance(value,dict) and value.get('state')!='completed'):
            return
        if (stop is not None and stop.is_set() and kind in
                ('loaded','pasted','planned','background_removed','screen','recovery_loaded','paint_auto_calibration_complete',
                 'browser_one_click_setup_complete','browser_auto_calibration_complete',
                 'one_click_setup_verification_complete','picture_palette_complete',
                 'performance_benchmark','benchmark_suite','golden_regression')):
            log_event(f'Ignored cancelled worker result: {kind}.')
            DrawBotApp._discard_worker_result(self,kind,value)
            return
        if kind=='status':
            self.status.set(str(value))
        elif kind=='terminal_status':
            activity,message=value
            if activity==self.activity:
                self._worker_terminal_status=(activity,str(message))
                if not self.stop.is_set() and not self.closing:self.status.set(str(message))
        elif kind=='runtime_safety_complete':
            # A current STOPPED report must survive the shared Stop filter.
            # Clear/new-run identity and closing still reject older evidence.
            if not getattr(self,'closing',False):
                view=DrawBotApp._runtime_safety_view(self)
                if view.accept(value):DrawBotApp.refresh_runtime_safety_ui(self)
        elif kind=='recovery_image_prepared':
            DrawBotApp._finish_recovery_image_job(self,value)
        elif kind=='recovery_clear_complete':
            error,previous_suppression=value
            self._recovery_clear_previous_suppression=None
            if self.closing:return
            if error is None:
                self._suppress_recovery=True
                self.pending_render_resume=None
                self.status.set('Local safe-recovery checkpoint cleared.')
                log_event('Recovery checkpoint cleared by user.')
            else:
                self._suppress_recovery=previous_suppression
                self.status.set(f'Could not clear recovery checkpoint: {error}')
        elif kind=='recovery_loaded':
            self.recovery_loaded_pending=value
        elif kind=='paint_auto_calibration_complete':
            if self.game.get()!='Microsoft Paint':return
            meta,canvas=_validated_setup_payload(value,require_canvas=True);l,t,r,b=canvas
            prepared_width=value.get('prepared_brush_px',1)
            if type(prepared_width) is not int or not 1<=prepared_width<=50:
                raise ValueError('Prepared Paint brush width is invalid. Prepare Paint again.')
            brush_requested=('Auto' if str(value.get('brush_px_requested','')).casefold()=='auto'
                             else str(prepared_width))
            self.corners=[(l,t),(r,b)];self.saved_area=list(self.corners);self.canvas_anchor_detection=None
            self.target_window=(int(meta['handle']),tuple(meta['rect']))
            self.target_client_rect=tuple(meta['client_rect']);self.target_dpi=meta.get('dpi')
            self.paint_tool.set('Auto (recommended)');self.brush_px.set(brush_requested)
            self.area_text.set(f'✓ Paint canvas {r-l} × {b-t} px')
            self.color_session_cache.clear();self.refresh_palette();self.refresh_tool_calibration()
            self._mark_plan_stale('Paint setup changed. Build preview when ready.')
            self._invalidate_target_lock('Paint auto calibration changed',disarm=True)
            self.small_test_passed=False
            self.save_settings()
            self.custom_color_workflow.set('Adaptive exact (recommended)')
            self.refresh_exact_color_status()
            self.save_settings()
            self.one_click_setup_verify_pending=None;self.one_click_setup_verify_payload=None
            self.one_click_setup_text.set(f'Paint ready: canvas, pencil, {prepared_width} px, palette and RGB controls calibrated.')
            self.status.set('Paint ready. Colors are calibrated automatically before each drawing; no test or preview is required.')
            request=value.get('start_request')
            if request is not None:
                request['prepared_options']={
                    'brush_px':prepared_width,'brush_px_requested':brush_requested,
                    'auto_brush_width_meta':dict(value.get('auto_brush_width_meta') or {}),
                }
                self.root.after(50,lambda:DrawBotApp._resume_prepared_paint(self,request))
        elif kind=='update_progress':
            if not isinstance(value,tuple) or len(value)!=2:return
            request,text=value
            if DrawBotApp._update_request_current(self,request,phase='checking'):
                self.update_summary.set(str(text))
        elif kind=='update_installer_started':
            if (not isinstance(value,UpdateRequest) or
                    getattr(self,'update_request',None) is not value or not value.consume_started()):
                return
            self.update_request=None
            self.status.set('Installer started. Closing Image Draw Bot to complete the update.')
            self.close()
        elif kind=='update_check_complete':
            payload=value if isinstance(value,dict) else {}
            request=payload.get('request')
            if not DrawBotApp._update_request_current(self,request,phase='checking'):return
            if not (request.ready() if payload.get('installer_path') else request.finish_check()):return
            action=getattr(self,'update_download_button',None)
            if action is not None:
                action.configure(text='Open GitHub Releases')
            if payload.get('error'):
                self.update_summary.set('Could not check for updates. Try again.')
                self.update_detail.set(str(payload['error']))
                self.status.set('Update check failed. Check your connection and try again.')
                return
            self.latest_release_url=str(payload.get('release_url') or 'https://github.com/Vxiey/Image-Draw-Bot/releases')
            self.update_summary.set(str(payload.get('message') or 'Update check completed.'))
            latest=str(payload.get('latest_version') or 'No release found')
            release_name=str(payload.get('release_name') or '').strip()
            extra=f' · {release_name}' if release_name and release_name not in latest else ''
            self.update_detail.set(f'Current: {APP_VERSION} · Latest: {latest}{extra} · Updates from official GitHub Releases.')
            if payload.get('installer_path'):
                self.update_summary.set(f'Version {latest} downloaded and SHA-256 verified. Opening installer…')
                self.root.after(100,lambda:DrawBotApp._install_checked_update(self,payload))
            elif payload.get('update_available'):
                self.status.set(str(payload.get('message') or f'Image Draw Bot {latest} is available.'))
            else:
                self.status.set(str(payload.get('message') or 'Update check completed.'))
        elif kind=='hardware_profile_check':
            payload=value if isinstance(value,dict) else {}
            if payload.get('needed') and not self.activity and not self.closing:
                reason=str(payload.get('reason') or 'hardware profile missing or stale')
                self.auto_tune_detail.set(f'Automatic Step 22 benchmark required: {reason}. Running locally now…')
                self.run_performance_auto_tuner(apply=False,automatic=True)
            elif payload.get('reason'):
                log_event('Step 22 hardware profile check: '+str(payload.get('reason')))
        elif kind=='performance_auto_tune_complete':
            self.hardware_benchmark_running = False
            payload=value if isinstance(value,dict) else {}
            if self.stop.is_set() or payload.get('cancelled'):
                self.auto_tune_summary.set('Universal Hardware Auto Benchmark cancelled.')
                self.auto_tune_detail.set('No new recommendation was applied.')
                self.status.set('Hardware benchmark cancelled.')
                return
            error=str(payload.get('error') or '')
            if error:
                self.auto_tune_summary.set('Universal Hardware Auto Benchmark failed safely.')
                self.auto_tune_detail.set(error)
                self.status.set(f'Universal Hardware Auto Benchmark failed safely: {error}')
            else:
                result=dict(payload.get('result') or {})
                self.auto_tune_summary.set(format_tune_summary(result))
                rec=dict(result.get('recommendation') or {})
                hardware=dict(result.get('hardware_profile') or {})
                detail=str(rec.get('reason') or 'Local recommendation ready.')
                if hardware:
                    detail += ' ' + format_universal_hardware_summary(hardware)
                self.auto_tune_detail.set(detail)
                if payload.get('apply'):
                    self.apply_performance_tune(result,_from_benchmark=True)
                elif payload.get('automatic'):
                    self.status.set('Automatic hardware benchmark complete. The local adaptive profile is ready; manual settings were not changed.')
                else:
                    self.status.set('Universal Hardware Auto Benchmark complete. Review the recommendation or press Apply saved recommendation.')
        elif kind=='screen':
            self.display_screen(value)
        elif kind=='toggle_pause':
            self.toggle_pause()
        elif kind=='quick_start':
            self.quick_start_hotkey()
        elif kind=='picture_palette_complete':
            from PicturePalettePlanning import active_picture_palette
            if self.game.get()!='Microsoft Paint' or value.get('image_id')!=id(self.original):return
            self.picture_custom_palette_state=dict(value)
            if not active_picture_palette(self):return
            self.custom_color_workflow.set('Adaptive exact (recommended)')
            self.refresh_exact_color_status()
            self._mark_plan_stale('Picture colors changed. Build preview to use the saved image RGB palette.')
            self.save_settings()
            self.show_previews()
        elif kind=='exact_color_calibration_complete':
            code=int((value or {}).get('code',-1));self.refresh_exact_color_status();self.color_session_cache.clear()
            self._mark_plan_stale('Exact color controls changed. Press Build preview manually when ready.')
            self._invalidate_target_lock('exact color calibration changed',disarm=True)
            if code==0:
                self.status.set('Smart custom palette calibration closed. Visual scale / exact RGB will be used when calibrated; nearest palette fallback is always available.')
                log_event('Exact color calibration helper completed successfully.')
            else:
                self.status.set(f'Exact color calibration failed safely in helper process (exit {code}). Main Image Draw Bot stayed open; nearest palette fallback remains active.')
                log_event(f'Exact color calibration helper failed safely: exit={code}.')
        elif kind=='smart_drop_canvas_ready':
            payload=value if isinstance(value,dict) else {}
            if int(payload.get('generation',-1))!=int(getattr(self,'smart_drop_generation',0)):
                log_event('Ignored stale Smart Canvas Drop detection result after cancel/re-arm/profile change.')
            else:
                self.smart_drop_pending_payload=payload
                confidence=float(payload.get('canvas_confidence',0) or 0)
                try:self.smart_drop_in_text.set(f'Canvas detected at {confidence*100:.0f}% confidence. Arming the drop target directly over it…')
                except Exception:pass
                log_event(f'Game Canvas Drop detection ready: canvas={payload.get("canvas_box")!r} confidence={confidence:.3f}.')
        elif kind=='browser_one_click_setup_complete':
            payload=value if isinstance(value,dict) else {}
            request=payload.get('_browser_request')
            if not DrawBotApp._browser_one_click_request_current(self,request):
                if request is not None:DrawBotApp._cancel_browser_one_click(self,'setup context changed',request=request)
                log_event('Ignored Browser One-Click setup result without its current image/profile request.')
                return
            if request['phase']!='setup':return
            profile_name=str(payload.get('profile_name') or request['profile_name'])
            if profile_name!=request['profile_name']:
                DrawBotApp._cancel_browser_one_click(self,'setup returned a different profile',request=request)
                return
            force=request['force']
            if payload.get('_browser_drawing_region') is not getattr(self,'browser_drawing_region',None):
                DrawBotApp._cancel_browser_one_click(self,'drawing region changed',request=request)
                return
            self.browser_auto_calibration_success=False
            meta,canvas=_validated_setup_payload(payload,require_canvas=True)
            drawing_region=DrawBotApp._browser_drawing_region(self)
            if drawing_region is not None:
                drawing_region=drawing_region.with_canvas(PROFILES[profile_name][0],meta,canvas)
                canvas=drawing_region.drawing_box(PROFILES[profile_name][0],meta)
            # Preserve only this image's one-shot permission until its owned
            # finish callback consumes it. A global switch cannot replace it.
            self.browser_one_click_force=force
            if canvas is not None:
                l,t,r,b=map(int,canvas);self.corners=[(l,t),(r,b)];self.saved_area=[(l,t),(r,b)]
                self.browser_drawing_region=drawing_region
                if drawing_region is None:self.canvas_anchor_detection=None
                self.area_text.set(f'✓ Selected region {r-l} × {b-t} px · inside verified canvas' if drawing_region is not None else
                                   (f'✓ Canvas Drop verified {r-l} × {b-t} px' if force else f'✓ One-Click canvas {r-l} × {b-t} px'))
            if meta.get('handle') and meta.get('rect') and meta.get('client_rect'):
                self.target_window=(int(meta['handle']),tuple(meta['rect']));self.target_client_rect=tuple(meta['client_rect']);self.target_dpi=meta.get('dpi')
            self.color_session_cache.clear();self.refresh_palette();self.small_test_passed=False
            self._mark_plan_stale('Game Canvas Drop refreshed canvas/palette.' if force else 'Browser One-Click refreshed canvas/palette.')
            count=int(payload.get('palette_count',0) or 0);confidence=float(payload.get('confidence',0) or 0)
            request['phase']='ready'
            self.browser_auto_calibration_success=True;self.drop_in_sync_phase=DROP_SYNC_READY
            self.browser_auto_text.set(f'✓ Canvas-drop verification · {count} colors · confidence {confidence*100:.0f}%' if force else f'✓ One-Click auto setup · {count} colors · confidence {confidence*100:.0f}%')
            self.browser_one_click_text.set(('✓ Canvas image verified · starting drawing…' if force else '✓ One-Click setup ready · visual preflight + auto brush will run before drawing.')
                                            if request['auto_start'] else 'Initial setup found · independent read-only verification pending.')
            log_event(f'Browser One-Click setup completed: profile={profile_name!r} colors={count} confidence={confidence:.3f} canvas={canvas!r} force={force}.')
            pending=getattr(self,'one_click_setup_verify_pending',None)
            if not request['auto_start'] and isinstance(pending,dict) and pending.get('_browser_request') is request:
                DrawBotApp._queue_one_click_setup_verification(self,dict(payload,_browser_drawing_region=drawing_region))
        elif kind=='one_click_setup_verification_complete':
            payload=value if isinstance(value,dict) else {}
            request=payload.get('_browser_request')
            if str(payload.get('mode'))=='browser':
                if payload.get('_browser_drawing_region') is not getattr(self,'browser_drawing_region',None):
                    DrawBotApp._cancel_browser_one_click(self,'verification drawing region changed',request=request)
                    return
                if (not DrawBotApp._browser_one_click_request_current(self,request) or request['auto_start']):
                    if request is not None:DrawBotApp._cancel_browser_one_click(self,'verification context changed',request=request)
                    log_event('Ignored Browser One-click verification result from an older request.')
                    return
            profile_name=str(payload.get('profile_name') or self.game.get())
            pending=getattr(self,'one_click_setup_verify_pending',None)
            if profile_name!=self.game.get() or (isinstance(pending,dict) and pending.get('profile_name')!=profile_name):
                log_event('Ignored stale Step 27.5 One-click Setup verification result after profile change.')
            else:
                from OneClickSetupVerification import format_verification
                passed=bool(payload.get('passed'));self.one_click_setup_text.set(format_verification(payload))
                if passed:
                    confidence=float(payload.get('confidence',0) or 0)
                    if str(payload.get('mode'))=='browser':self.browser_auto_calibration_success=True
                    self.status.set(f'✓ One-click Setup verified for {profile_name}: live canvas + palette checks passed at {confidence*100:.0f}% confidence. No drawing input was sent.')
                    log_event(f'Step 27.5 One-click Setup PASS: profile={profile_name!r} mode={payload.get("mode")!r} confidence={confidence:.3f} canvas={payload.get("canvas_ok")} palette={payload.get("palette_verified")}/{payload.get("palette_tested")} tools={payload.get("tool_ok")}.')
                else:
                    if str(payload.get('mode'))=='browser':
                        self.browser_auto_calibration_success=False
                        region=payload.get('_browser_drawing_region')
                        if region is not None:self.browser_drawing_region=region.without_verification()
                    reason='; '.join(str(x) for x in (payload.get('reasons') or ())) or str(payload.get('error') or 'verification failed')
                    DrawBotApp._invalidate_target_lock(self,'Step 27.5 verification failed',disarm=True)
                    DrawBotApp._invalidate_safety_preflight(self,'Step 27.5 verification failed',disarm=True)
                    self.status.set(f'One-click Setup blocked safely: {reason} Use manual calibration if the target layout changed.')
                    log_event(f'Step 27.5 One-click Setup BLOCKED: profile={profile_name!r} reason={reason!r}. No drawing input was sent.')
            self.one_click_setup_verify_pending=None;self.one_click_setup_verify_payload=None
            if request is not None:DrawBotApp._cancel_browser_one_click(self,'read-only verification finished',request=request)
        elif kind=='browser_auto_calibration_complete':
            payload=value if isinstance(value,dict) else {}
            if payload.get('_browser_drawing_region') is not getattr(self,'browser_drawing_region',None):
                log_event('Ignored Browser Auto Setup result for a replaced drawing-region selection.')
                return
            profile_name=str(payload.get('profile_name') or self.game.get())
            if profile_name!=self.game.get():
                log_event('Ignored stale Browser Auto Setup result after profile change.')
            else:
                self.browser_auto_calibration_success=False
                meta,canvas=_validated_setup_payload(payload)
                drawing_region=DrawBotApp._browser_drawing_region(self)
                if drawing_region is not None:
                    try:
                        drawing_region=(drawing_region.with_canvas(PROFILES[profile_name][0],meta,canvas)
                                        if canvas is not None else drawing_region.without_verification())
                        l,t,r,b=drawing_region.drawing_box(PROFILES[profile_name][0],meta)
                    except ValueError as error:
                        self.browser_drawing_region=drawing_region.without_verification()
                        self.browser_auto_text.set('Drawing region blocked · '+str(error))
                        self.status.set(str(error));return
                    self.browser_drawing_region=drawing_region
                    self.corners=[(l,t),(r,b)];self.saved_area=list(self.corners)
                    self.area_text.set(f'✓ Selected region {r-l} × {b-t} px · inside verified canvas' if canvas is not None else
                                       f'Selected region {r-l} × {b-t} px · canvas not yet verified')
                else:
                    self.corners=[];self.saved_area=[];self.canvas_anchor_detection=None
                    if canvas is not None:
                        l,t,r,b=map(int,canvas)
                        if r-l>=10 and b-t>=10:
                            self.corners=[(l,t),(r,b)];self.saved_area=[(l,t),(r,b)]
                            self.area_text.set(f'✓ Auto canvas {r-l} × {b-t} px · confidence {float(payload.get("canvas_confidence",0))*100:.0f}%')
                    else:
                        self.area_text.set('Select drawing area: automatic setup verified the palette only.')
                if meta.get('handle') and meta.get('rect') and meta.get('client_rect'):
                    self.target_window=(int(meta['handle']),tuple(meta['rect']))
                    self.target_client_rect=tuple(meta['client_rect']);self.target_dpi=meta.get('dpi')
                self.color_session_cache.clear();self.refresh_palette();self.small_test_passed=False
                self._mark_plan_stale('Browser Auto Setup changed canvas/palette. Build preview when ready.')
                self._invalidate_target_lock('browser auto calibration changed',disarm=True)
                count=int(payload.get('palette_count',0) or 0);confidence=float(payload.get('confidence',0) or 0)
                self.browser_auto_text.set(f'✓ Auto setup ready · {count} colors · confidence {confidence*100:.0f}% · manual calibration not required.')
                self.status.set(f'✓ {profile_name} Auto Setup ready: {count} verified colors. Add/drop the image and draw.')
                if canvas is None:
                    if drawing_region is not None:
                        from BrowserDrawingRegion import UNVERIFIED_REGION_MESSAGE
                        self.browser_auto_text.set(f'Palette ready · {count} colors · selected region is unverified.')
                        self.status.set(UNVERIFIED_REGION_MESSAGE)
                    else:
                        self.browser_auto_text.set(f'Palette ready · {count} colors · select the drawing area manually.')
                        self.status.set(f'{profile_name} palette calibrated. Select the drawing area before starting.')
                try:self.save_settings()
                except Exception:pass
                try:self.root.deiconify();self.root.lift()
                except tk.TclError:pass
                self.browser_auto_calibration_success=canvas is not None
                self.drop_in_sync_phase=DROP_SYNC_READY if canvas is not None else DROP_SYNC_IDLE
                fingerprint_meta=payload.get('layout_fingerprint_meta') or {}
                cache_hit=bool(isinstance(fingerprint_meta,dict) and fingerprint_meta.get('hit'))
                log_event(f'Browser Auto Setup completed: profile={profile_name!r} colors={count} confidence={confidence:.3f} canvas={canvas!r} layout_fingerprint_cache_hit={cache_hit}.')
        elif kind=='palette_calibration_complete':
            payload=value if isinstance(value,dict) else {};self.color_session_cache.clear()
            code=int(payload.get('code',-1))
            self.refresh_palette()
            self._mark_plan_stale('Color calibration changed. Press Build preview manually when ready.')
            self._invalidate_target_lock('color calibration changed',disarm=True)
            if code==0:
                if self.palette_ready:
                    self.status.set('✓ Color calibration saved and loaded. Preview remains Manual.')
                    log_event('Color calibration completed successfully and palette reloaded.')
                else:
                    self.status.set('Color calibration closed without a saved/valid palette. Read colors again before full drawing.')
                    log_event('Color calibration helper closed normally without a valid saved palette.')
            else:
                unsigned=code & 0xffffffff
                crash_hint=(' Native Windows access violation (0xC0000005).' if unsigned==0xC0000005 else '')
                self.status.set(f'Color calibration failed safely in its helper process (exit {code} / 0x{unsigned:08X}). Main Image Draw Bot stayed open.{crash_hint} Check the palette calibration log.')
                log_event(f'Color calibration helper failed safely: exit={code} / 0x{unsigned:08X}.')
        elif kind=='diagnostics_ready':
            if self.closing or (stop is not None and stop.is_set()):return
            path=Path(str(value))
            self.status.set(f'Diagnostics package created: {path.name}')
            messagebox.showinfo('Diagnostics created',f'Privacy-safe diagnostics ZIP created at:\n{path}\n\nSource/recovery images are not included.',parent=self.root)
        elif kind=='test_passed':
            self.small_test_passed=bool(value)
            DrawBotApp._invalidate_target_lock(self,'small test result changed',disarm=True)
            DrawBotApp._invalidate_safety_preflight(self,'small test result changed',disarm=True)
            DrawBotApp._invalidate_dry_run(self,'small test result changed',disarm=True)
            if self.small_test_passed:
                self.status.set('Small drawing test passed. Next press Lock setup; full drawing is still locked.')
        elif kind=='dry_run_passed':
            self.dry_run_passed=bool(value)
            if self.dry_run_passed:
                self.dry_run_signature=DrawBotApp._current_safety_signature(self)
                self.dry_run_valid_until=time.monotonic()+180.0
                DrawBotApp._disarm_full_draw(self,'dry run passed; waiting for explicit unlock',update_text=True)
                self.status.set('Fast Dry run passed for 3 minutes. Now press Unlock full drawing, then Start Drawing.')
                try:self.summary.set('Dry run PASS: representative calibrated routes were sampled within the time limit without clicks, presses or releases. Full drawing is still locked until Unlock + Start.')
                except (tk.TclError,AttributeError):pass
                log_event('Fast Dry run passed. Valid for 180 seconds or until the safety signature changes.')
        elif kind=='render_checkpoint':
            data=value if isinstance(value,dict) else {}
            self.pending_render_resume=dict(data) if data else None
            if self.pending_render_resume:
                completed=int(data.get('completed_count',0));total=int(data.get('total_colors',0));next_color=int(data.get('next_color',0))
                if data.get('path_level'):
                    color_no=int(data.get('active_color_number',next_color) or next_color)
                    path_no=int(data.get('next_path_index',0) or 0)+1;path_total=int(data.get('active_path_count',0) or 0)
                    self.color_plan_text.set(f'Smart Recovery checkpoint: {completed}/{total} colors complete · color {color_no} path {path_no}/{path_total} next')
                else:
                    self.color_plan_text.set(f'Render checkpoint: {completed}/{total} colors completed' + (f' · next color {next_color}' if next_color else ' · complete'))
        elif kind=='render_resume_cleared':
            self.pending_render_resume=None
        elif kind=='color_plan':
            data=value if isinstance(value,dict) else {}
            try:
                current=int(data.get('current',0));total=int(data.get('total',0));rgb=tuple(data.get('rgb') or ())
                method=str(data.get('method','Color selector'));confidence=float(data.get('confidence',0));matched=bool(data.get('matched'))
                if data.get('completed'):
                    self.color_plan_text.set(f'Color plan: {current}/{total} complete · RGB {rgb} · {method}')
                else:
                    verdict='verified' if matched else 'recovering'
                    self.color_plan_text.set(f'Color plan: {current}/{total} · RGB {rgb} · {method} · {confidence:.0f}% · {verdict}')
            except Exception:
                self.color_plan_text.set('Color verification status updated.')
        elif kind=='visual_verification':
            data=value if isinstance(value,dict) else {}
            try:
                current=int(data.get('current',0));total=int(data.get('total',0));ok=bool(data.get('ok',False));confidence=float(data.get('confidence',0));summary=str(data.get('summary','visual check'))
                verdict='OK' if ok else 'warning'
                self.color_plan_text.set(f'Visual verification: {current}/{total} · {confidence:.0f}% · {verdict} · {summary}')
            except Exception:
                self.color_plan_text.set('Visual verification status updated.')
        elif kind=='progress':
            done,total=value
            done=max(0,int(done));total=max(0,int(total))
            self.progress['value']=0 if total==0 else min(100,done*100/total)
            if total and not self.paused.is_set():
                if self.activity=='dry-run':
                    self.status.set(f'Dry run: {done:,} / {total:,} cursor paths simulated • no clicks • Esc stops')
                else:
                    self.status.set(f'Drawing: {done:,} / {total:,} brush strokes • Esc stops • F6 pauses')
        elif kind=='draw_timer':
            data=value if isinstance(value,dict) else {}
            try:
                from DrawTimeEstimate import format_duration
                elapsed=max(0.0,float(data.get('elapsed_seconds',0) or 0))
                remaining=max(0.0,float(data.get('remaining_seconds',0) or 0))
                predicted=max(elapsed,float(data.get('predicted_total_seconds',elapsed) or elapsed))
                if str(data.get('state') or '')=='completed':
                    self.draw_live_time_text.set(f'Drawing timer: {format_duration(elapsed)} elapsed · complete')
                else:
                    paused_note=' · paused' if data.get('state')=='paused' else ''
                    self.draw_live_time_text.set(f'Drawing timer: {format_duration(elapsed)} elapsed{paused_note} · ≈ {format_duration(remaining)} remaining · ≈ {format_duration(predicted)} total')
                    self.total_draw_time_text.set('Total draw time: paused…' if paused_note else 'Total draw time: drawing…')
            except (TypeError,ValueError,tk.TclError,AttributeError):
                pass
        elif kind=='draw_time_actual':
            data=value if isinstance(value,dict) else {}
            try:
                from DrawTimeEstimate import format_duration
                seconds=max(0.0,float(data.get('seconds',0) or 0))
                self.total_draw_time_text.set(f'Total draw time: {format_duration(seconds)}')
                self.draw_live_time_text.set(f'Drawing timer: completed in {format_duration(seconds)}')
            except (TypeError,ValueError,tk.TclError,AttributeError):
                pass
        elif kind=='upscaled':
            if value[1] is not None and (self.stop.is_set() or self.original is not value[1]):
                DrawBotApp._discard_worker_result(self,kind,value)
                return
            DrawBotApp._cancel_browser_one_click(self,'source image resized')
            self._suppress_recovery=False
            self.original,previous=value
            DrawBotApp._clear_source_time_feedback(self)
            self.upscale_original=previous
            # Undo belongs to the most recent edit type. A background-removal
            # snapshot from before this resize must not discard the resize.
            self.background_removal_original=None;self.background_removal_meta=None
            self.color_session_cache.clear()
            DrawBotApp._clear_render_resume(self,'image resampled')
            from ImageFormatInfo import image_label
            self.file_label.set(image_label(self.original,'Upscaled image' if previous is not None else 'Original restored'))
            self._mark_plan_stale('Image updated. Build preview to check the result before Start.')
            self.status.set('Image updated. Build preview to check the result before Start.')
            self.show_previews()
            self._schedule_recovery_checkpoint(include_image=True,delay=40)
            self.needs_plan=True
        elif kind=='background_removed':
            from ImageFormatInfo import image_label
            result=value
            image=getattr(result,'image',None);meta=getattr(result,'metadata',{}) or {}
            if image is None:
                self.status.set('Background removal returned no image. Original preserved.')
            else:
                reason=meta.get('no_op_reason')
                if reason:
                    self.background_removal_meta=dict(meta)
                    if image is not self.original:image.close()
                    self.status.set(f'Background remover kept the original: {reason}.')
                    return
                prepared=image if image.mode=='RGBA' else image.convert('RGBA')
                DrawBotApp._cancel_browser_one_click(self,'source background changed')
                if self.background_removal_original is None:
                    self.background_removal_original=self.original.copy()
                self.original=prepared;self.background_removal_meta=dict(meta);self.plan=None
                DrawBotApp._clear_source_time_feedback(self)
                self.upscale_original=None
                DrawBotApp._clear_render_resume(self,'background removed')
                self.file_label.set(image_label(self.original,'Background removed PNG'))
                reduction=float(meta.get('estimated_work_reduction_percent',0) or 0)
                removed=float(meta.get('removed_percent',0) or 0)
                self.status.set(f'Background removed: {removed:.1f}% of image area transparent; drawable pixel work reduced about {reduction:.1f}%. Build preview for real ETA.')
                log_event(f"Background removal complete: removed={removed:.2f}% work_reduction={reduction:.2f}% ref={meta.get('reference_rgb')} threshold={meta.get('threshold')} bbox={meta.get('foreground_bbox')}.")
                self._mark_plan_stale('Background changed. Build preview to recalculate strokes and ETA.')
                self.show_previews();self._schedule_recovery_checkpoint(include_image=True,delay=40)
                self.needs_plan=True
        elif kind=='png_saved':
            self.status.set(f'PNG saved: {value}')
            log_event(f'PNG export saved: {value!r}.')
        elif kind=='pasted':
            DrawBotApp._cancel_browser_one_click(self,'source replaced by pasted image')
            self._suppress_recovery=False;self.original,action=value;self.plan=None
            DrawBotApp._clear_source_time_feedback(self)
            self.upscale_original=None
            self.background_removal_original=None;self.background_removal_meta=None
            self.subject_region=None
            if hasattr(self,'subject_hint'):self.subject_hint.set('Auto: simple background or transparent PNG. Mark busy photos.')
            DrawBotApp._clear_render_resume(self,'new pasted image')
            from ImageFormatInfo import image_label
            self.file_label.set(image_label(self.original,'Pasted image'))
            self._mark_plan_stale('Image pasted. Press Build preview when ready.')
            self.show_previews();self._schedule_recovery_checkpoint(include_image=True,delay=40)
            # Publication occurs while the tracked loader still owns the UI.
            # poll consumes this only after its matching done event; cancel()
            # clears the request and Manual still locks automatic previews.
            self.needs_plan=True
            # done(load) schedules an accepted Drop-In only after the loader
            # releases the UI, exactly like file/URL imports.
            queued=DrawBotApp._queue_drop_in_start(self,action,source_label='pasted image')
            if not queued and action is None:
                DrawBotApp._queue_browser_one_click_after_import(self,'pasted image')
        elif kind=='loaded':
            DrawBotApp._cancel_browser_one_click(self,'source image replaced')
            self._suppress_recovery=False
            self.background_removal_original=None;self.background_removal_meta=None
            self.upscale_original=None
            self.subject_region=None
            if hasattr(self,'subject_hint'): self.subject_hint.set('Auto: simple background or transparent PNG. Mark busy photos.')
            if isinstance(value,(tuple,list)) and len(value)>=4:
                self.original,label,_action,_one_click_force=value[:4]
            else:
                self.original,label,_action=value;_one_click_force=False
            self.color_session_cache.clear();DrawBotApp._clear_render_resume(self,'new image loaded')
            from ImageFormatInfo import image_label
            self.file_label.set(image_label(self.original,str(label)))
            self._mark_plan_stale('Image loaded. Preview was not rebuilt automatically in Manual mode.')
            try:self.draw_time_text.set('Estimated draw time appears after Build preview.')
            except (tk.TclError,AttributeError):pass
            DrawBotApp._clear_source_time_feedback(self)
            DrawBotApp._queue_drop_in_start(self,_action,source_label=str(label))
            if normalize_drop_in_action(_action)!=DROP_IN_ACTION:
                DrawBotApp._queue_browser_one_click_after_import(self,str(label),force=bool(_one_click_force))
            if bool(_one_click_force):
                self.status.set('Game-canvas image loaded. Verifying browser canvas/palette, then drawing will start automatically.')
            elif normalize_drop_in_action(_action)==DROP_IN_ACTION and self.drop_action_pending==DROP_IN_ACTION:
                self.status.set('Image loaded through Drop-In Start. Drawing will start after the loader finishes if the canvas setup is still valid.')
            else:
                self.status.set('Image loaded. Press Build preview when you want a preview, or continue setup and Safety preflight / Dry run when ready.')
            self.show_previews();self._sync_mobile_preview();self._schedule_recovery_checkpoint(include_image=True,delay=40)
            # Like pasted bitmaps and edits, release the loader before poll
            # schedules automatic planning. Explicit drawing continuations win.
            self.needs_plan=True
        elif kind=='preview_timeout':
            target,preview=value
            self.summary.set('Preview calculation exceeded its time limit. The previous preview is retained. Try the normal Build preview or a smaller drawing area.')
            try:self.draw_time_text.set('Preview timed out before an estimate could be updated.')
            except (tk.TclError,AttributeError):pass
            self.status.set('Preview took too long, so it was cancelled safely. You can still press Start drawing to generate the final plan.')
        elif kind=='planned':
            try:
                if not isinstance(value,dict) or 'preview' not in value or 'count' not in value or 'estimate' not in value:
                    raise ValueError('The preview worker returned an invalid plan.')
                current=int(value.get('preview_generation',-1))==int(getattr(self,'preview_generation',0))
            except (TypeError,ValueError,OverflowError):
                DrawBotApp._discard_worker_result(self,kind,value)
                raise
            if not current:
                log_event(f"Ignored stale preview result generation={value.get('preview_generation')} current={getattr(self,'preview_generation',0)}.")
                DrawBotApp._discard_worker_result(self,kind,value)
                return
            publication=getattr(self,'_draw_plan_publication',None)
            if publication is not None and publication.owns(value) and not publication.adopt(value):
                return
            self.plan=value
            self.preview_dirty_reason=''
            self._sync_mobile_preview()
            estimate=max(0,float(value['estimate']));unit=f'{estimate/60:.1f} min' if estimate>=60 else f'{estimate:.0f} s'
            try:
                from DrawTimeEstimate import attach_draw_time_estimate, status_line
                prepared=value.pop('_preview_time_estimate_ready',None)
                time_meta=value.get('draw_time_estimate')
                if not isinstance(time_meta,dict) or prepared is not time_meta:
                    # Legacy/manual producers, failed preparation and replaced
                    # metadata retain the existing fresh-calculation path.
                    time_meta=attach_draw_time_estimate(value)
                time_status=status_line(value)
            except Exception:
                time_meta={'projected_seconds':estimate,'projected_label':unit,'range_label':unit,'confidence':'unknown','is_projection':False}
                time_status=f'Estimated draw time: about {unit}.'
            try:self.draw_time_text.set(time_status)
            except (tk.TclError,AttributeError):pass
            stats=value.get('options',{}).get('portrait_stats')
            portrait_note=(f" • portrait: {int(stats['edge_strokes']):,} contour + {int(stats['tone_strokes']):,} shading • {stats.get('draw_quality','High likeness')}" if stats else '')
            brush_px=int(value.get('options',{}).get('brush_px',3))
            brush_tip=(' Portrait tip: 1–2 px usually preserves facial detail better.' if stats and brush_px > 2 else '')
            priority_tip=(f" {int(stats.get('priority_strokes',0)):,} strokes were structure-prioritized." if stats and stats.get('priority_strokes') else '')
            time_tip=(' Detail was fitted to your time limit.' if stats and stats.get('time_fitted') else '')
            precision=value.get('options',{}).get('precision','High')
            human_mode=value.get('options',{}).get('human_mode','Off')
            human_note=(f' • Human: {human_mode}' if human_mode!='Off' else '')
            gpu_status=value.get('options',{}).get('gpu_backend_status') or {}
            if stats and stats.get('gpu_accelerated'):
                budget=stats.get('vram_budget_mb'); perf=stats.get('gpu_performance','')
                memory=(f' · VRAM {int(budget):,} MB' if isinstance(budget,(int,float)) else '')
                scaler=stats.get('scaler','');allocation=stats.get('allocation_mode','')
                gpu_note=f" • {stats.get('acceleration_backend','CUDA')}: {stats.get('acceleration_device','GPU')}{memory}" + (f' · {perf}' if perf else '') + (f' · {allocation}' if allocation else '') + (f' · {scaler}' if scaler else '')
            elif gpu_status:
                if gpu_status.get('gpu_analysis_active'):
                    gpu_note=f" • GPU verified: {gpu_status.get('gpu_device','CUDA')} · CuPy active"
                else:
                    reason=str(gpu_status.get('fallback_reason') or 'CPU selected')
                    detected='detected' if gpu_status.get('gpu_detected') else 'not detected'
                    gpu_note=f" • Analysis: CPU · GPU {detected} · {reason}"
            elif stats:
                gpu_note=' • Analysis: CPU'
            else:
                gpu_note=''
            fill_meta=value.get('options',{}).get('background_fill_plan') or {}
            region_count=len(value.get('options',{}).get('fill_regions',[]) or [])
            if fill_meta.get('enabled'):
                fill_note=f" • Base Fill: {fill_meta.get('image_coverage',0)*100:.0f}% background"
            elif value.get('options',{}).get('background_fill')!='Off' and value.get('options',{}).get('fill_unavailable_reason'):
                fill_note=' • Auto Fill unavailable (calibrate Fill + drawing tool)'
            else:
                fill_note=''
            if region_count:fill_note+=f' • {region_count} safe region fill' + ('s' if region_count!=1 else '')
            region_meta=value.get('options',{}).get('region_fill_meta') or {}
            if region_meta.get('enabled'):
                if region_meta.get('pixel_accurate_protected'):
                    fill_note+=' • Region Fill: Pixel Accurate protected (no bucket substitution)'
                else:
                    fill_note+=(f" • Region Fill: {int(region_meta.get('fill_safe_regions',0) or 0)}/{int(region_meta.get('total_regions',0) or 0)} safe"
                               f" · coverage {float(region_meta.get('fill_coverage_percent',0) or 0):.0f}%"
                               f" · strokes -{float(region_meta.get('stroke_reduction_percent',0) or 0):.0f}%"
                               f" · save ≈{float(region_meta.get('estimated_time_saved_seconds',0) or 0):.0f}s")
            simplify=value.get('options',{}).get('background_simplification_meta') or {}
            simplify_note=(f" • background simplified {simplify.get('coverage',0)*100:.0f}%" if simplify.get('enabled') and simplify.get('changed_pixels') else '')
            grouping=value.get('options',{}).get('color_grouping_meta') or {}
            grouping_note=(f" • colors: {grouping.get('active_colors',0)} grouped" if grouping else '')
            advanced=value.get('options',{}).get('advanced_color_meta') or {}
            if advanced and advanced.get('color_rendering'):
                layer_bits=f" + {advanced.get('color_layers')}" if advanced.get('color_layers')!='Off' else ''
                color_note=f" • color: {advanced.get('color_rendering')}{layer_bits}"
                if advanced.get('layered_pixels'):
                    color_note += f" ({int(advanced.get('layered_pixels',0)):,} layered px)"
            else:
                color_note=''
            adaptive_count=(advanced.get('adaptive_color_count') or {}) if isinstance(advanced,dict) else {}
            if adaptive_count.get('active'):
                _image_colors=int(adaptive_count.get('image_recommended_colors',adaptive_count.get('recommended_colors',0)) or 0)
                _final_colors=int(adaptive_count.get('recommended_colors',0) or 0)
                if adaptive_count.get('time_budget_applied'):
                    color_note+=(f" · Auto colors {_image_colors}->{_final_colors}/{int(adaptive_count.get('ceiling_colors',0) or 0)}"
                                f" · {float(adaptive_count.get('render_budget_seconds',0) or 0):.0f}s time-aware"
                                f" · ~{float(adaptive_count.get('estimated_marginal_color_seconds',0) or 0):.2f}s/color")
                else:
                    color_note+=(f" · Auto colors {_final_colors}/{int(adaptive_count.get('ceiling_colors',0) or 0)}")
                color_note+=(f" · complexity {float(adaptive_count.get('complexity_score',0) or 0):.2f}")
            color_diag=(advanced.get('color_fidelity_diagnostics') or {}) if isinstance(advanced,dict) else {}
            if color_diag.get('mapped_pixels'):
                color_note+=(f" · {color_diag.get('color_fidelity_rating','?')}"
                            f" · ΔE00 {float(color_diag.get('average_delta_e2000',0) or 0):.1f}"
                            f" · luminance {float(color_diag.get('luminance_drift_percent',0) or 0):+.0f}%")
                if color_diag.get('dark_bias_detected'):
                    color_note+=' · dark-bias warning'
                _named_rows=advanced.get('named_color_mappings') or ()
                _named_top=_named_rows[0] if _named_rows and isinstance(_named_rows[0],dict) else {}
                if _named_top.get('source_name') and _named_top.get('mapped_name'):
                    color_note+=(f" · {_named_top['source_name']}→{_named_top['mapped_name']}")
            path_stats=value.get('path_stats') or {}
            path_note=''
            if path_stats.get('mode') == 'Shape paths':
                skipped=int(path_stats.get('skipped_tiny_details',0) or 0)+int(path_stats.get('skipped_due_cap',0) or 0)
                skipped_note=f" · skipped {skipped:,} tiny/over-cap details" if skipped else ''
                cap=path_stats.get('max_stroke_cap_resolved')
                cap_note=f" · cap {int(cap):,}" if isinstance(cap,int) else ''
                progressive_note=''
                if path_stats.get('progressive_enabled'):
                    progressive_note=(f" · progressive: {int(path_stats.get('progressive_foundation_paths',0)):,} forms → "
                                      f"{int(path_stats.get('progressive_contour_paths',0)):,} contours → "
                                      f"{int(path_stats.get('progressive_detail_paths',0)):,} details")
                path_note=(f" • Shape paths: {int(path_stats.get('source_strokes',0)):,} source runs → "
                           f"{int(path_stats.get('execution_paths',value['count'])):,} optimized paths "
                           f"({path_stats.get('compression_ratio',0)*100:.0f}% fewer boundaries)"
                           f" · {path_stats.get('shape_order','Fill first')} · {path_stats.get('shape_model','Auto')}{cap_note}{skipped_note}{progressive_note}")
            elif path_stats.get('joined_strokes'):
                path_note=(f" • Smart paths: {int(path_stats.get('source_strokes',0)):,} source runs → "
                           f"{int(path_stats.get('execution_paths',value['count'])):,} continuous strokes "
                           f"({path_stats.get('compression_ratio',0)*100:.0f}% fewer boundaries)")
            optimizer_note=''
            if path_stats.get('stroke_optimizer_effective') not in (None,'Off'):
                optimizer_note=(f" • Stroke optimizer: {path_stats.get('stroke_optimizer_effective')}"
                                f" · merged {int(path_stats.get('optimizer_merged_paths',0) or 0):,} paths"
                                f" · pen-up travel -{float(path_stats.get('optimizer_travel_reduction',0) or 0)*100:.0f}%")
            opts=value.get('options',{})
            detail_meta=opts.get('adaptive_detail_meta') or {}
            adaptive_note=''
            if detail_meta.get('adaptive_detail_effective') not in (None,'Off'):
                adaptive_note=(f" • Adaptive detail: {detail_meta.get('adaptive_detail_effective')}"
                               f" · protected {float(detail_meta.get('adaptive_detail_protected_percent',0) or 0):.0f}%"
                               f" · simplified {100-float(detail_meta.get('adaptive_detail_protected_percent',0) or 0):.0f}%"
                               f" · pruned {int(detail_meta.get('adaptive_detail_pruned_micro_strokes',0) or 0):,} micro-strokes")
            cpu_backend=(advanced.get('cpu_backend') or ('parallel' if int(opts.get('cpu_workers_resolved',1) or 1)>1 else 'serial'))
            schedule=opts.get('resource_scheduler_plan') or {}
            phase= (schedule.get('phases') or {}).get('shape_extraction') or {}
            scheduler_suffix=(f" · scheduler {schedule.get('mode')} · shape {phase.get('workers')}w/{phase.get('chunks')} chunks" if schedule else '')
            resource_note=(f" • resources: CPU {int(opts.get('cpu_workers_resolved',1) or 1)}/{int(opts.get('logical_cpus',1) or 1)} · {opts.get('cpu_engine','Auto')}"
                           f" · RAM {int(opts.get('ram_budget_mb',0) or 0):,} MB"
                           + (f" · {cpu_backend}" if cpu_backend else '') + scheduler_suffix)
            budget_note=' • Full detail · target resolution' if value.get('full_detail_preview') else ''
            if opts.get('unlimited_time'):budget_note+=' • Unlimited time'
            auto_engine=opts.get('auto_drawing_meta') or {}
            if auto_engine:budget_note+=f" • {auto_engine['preset']}: {auto_engine['image_kind']} → {auto_engine['engine']}"
            _auto_tuner=opts.get('auto_tuner_meta') or {}
            _auto_accept=opts.get('auto_tuner_acceptance_meta') or {}
            if isinstance(_auto_tuner,dict) and _auto_tuner.get('active'):
                _status=str(_auto_accept.get('status') or 'PENDING')
                _gate=(_auto_accept.get('gates') or _auto_tuner.get('acceptance_gates') or {}).get('visual_accuracy_min_percent')
                _cap=int(_auto_tuner.get('color_ceiling',0) or 0)
                budget_note+=(f" • Auto tuner: {_status} · {_auto_tuner.get('selected_strategy','Auto')}"
                              f" · {_auto_tuner.get('speed_strategy','?')} · colors ≤{_cap}"
                              + (f" · visual gate ≥{float(_gate):.0f}%" if _gate is not None else ''))
                if int(_auto_accept.get('replan_attempt',0) or 0):
                    budget_note+=f" · rescue pass {int(_auto_accept.get('replan_attempt'))}"
                _feedback=_auto_tuner.get('feedback_learning') if isinstance(_auto_tuner.get('feedback_learning'),dict) else {}
                if int(_feedback.get('samples',0) or 0):
                    budget_note+=f" · feedback {int(_feedback.get('samples',0))} draws"
                    if _feedback.get('time_ratio_ema') is not None:
                        budget_note+=f" ×{float(_feedback.get('time_ratio_ema')):.2f}"
                    if _feedback.get('action') not in (None,'','none'):
                        budget_note+=f" → {_feedback.get('action')}"
            timer_meta=opts.get('gartic_timer_meta') or {}
            if timer_meta:
                budget_note+=f" • timer read ≈{timer_meta['estimated_seconds']:.0f}s (before planning)"
            auto_sketch=opts.get('sketch_auto_meta') or {}
            if auto_sketch:
                budget_note+=f" • Auto sketch: {auto_sketch['selected_detail']} · {auto_sketch['estimated_seconds']:.1f}s · omitted {auto_sketch['paths_omitted']} paths"
            if opts.get('time_budget_active'):
                _game=opts.get('deadline_total_seconds')
                _render=opts.get('deadline_render_budget_seconds',opts.get('time_budget_seconds',opts.get('max_seconds',0)))
                _reserve=opts.get('deadline_safety_reserve_seconds',0)
                budget_note+=f" • budget: {opts.get('time_budget_mode')} · game {float(_game or 0):.0f}s → render {float(_render or 0):.0f}s · reserve {float(_reserve or 0):.0f}s"
            if path_stats.get('progressive_enabled') and path_stats.get('mode') != 'Shape paths':
                budget_note += f" • progressive: {path_stats.get('progressive_phase_order','large forms → contours → details')}"
            if opts.get('target_stroke_count_resolved') is not None:
                skipped=int(path_stats.get('target_skipped_paths',0) or 0)
                reason=opts.get('target_stroke_count_reason','')
                budget_note += f" • target: {int(opts.get('target_stroke_count_resolved')):,} strokes" + (f" · skipped {skipped:,}" if skipped else '') + (f" · {reason}" if reason and reason!='explicit' else '')
            watchdog_note=''
            if opts.get('planning_attempt_name'):
                level=int(opts.get('planning_watchdog_fallback_level',0) or 0)
                watchdog_note=f" • watchdog: {opts.get('planning_attempt_name')}" + (f" · fallback level {level}" if level else '')
            preview_safety_note=''
            safety_meta=opts.get('preview_safety_meta') or {}
            if isinstance(safety_meta,dict) and safety_meta.get('active'):
                preview_safety_note=(f" • preview safety: {safety_meta.get('mode','CanvasGuard')}"
                                     f" · draw {int(safety_meta.get('drawable_subpaths',0) or 0):,}"
                                     f" · skip {int(safety_meta.get('skipped_total',0) or 0):,}"
                                     f" · edge-follow {int(safety_meta.get('adapted_total',0) or 0):,}")
                debug_meta=safety_meta.get('safety_debug') if isinstance(safety_meta.get('safety_debug'),dict) else {}
                if debug_meta:
                    preview_safety_note+=(f" · debug clipped {int(debug_meta.get('clipped',0) or 0):,}"
                                          f"/blocked {int(debug_meta.get('blocked',0) or 0):,}")
                if safety_meta.get('stopped'):
                    preview_safety_note+=' · source outside canvas warning'
            accuracy_note=''
            source_accuracy=opts.get('adaptive_accuracy_meta') or {}
            plan_accuracy=opts.get('pixel_accuracy_meta') or {}
            if source_accuracy:
                accuracy_note=(f" • visual accuracy: {float(source_accuracy.get('visual_accuracy_percent',0) or 0):.2f}%"
                               f" · source pixels {float(source_accuracy.get('source_pixel_accuracy_percent',source_accuracy.get('raw_pixel_accuracy_percent',0)) or 0):.2f}%"
                               f" · perceptual {float(source_accuracy.get('perceptual_color_accuracy_percent',0) or 0):.2f}%"
                               f" · luminance {float(source_accuracy.get('luminance_accuracy_percent',0) or 0):.2f}%"
                               f" · hue {float(source_accuracy.get('hue_accuracy_percent',0) or 0):.2f}%"
                               f" · edges {float(source_accuracy.get('edge_accuracy_percent',0) or 0):.2f}%")
                if source_accuracy.get('coverage_percent') is not None:
                    accuracy_note+=f" · coverage {float(source_accuracy.get('coverage_percent') or 0):.2f}%"
                if source_accuracy.get('plan_execution_accuracy_percent') is not None:
                    accuracy_note+=f" · plan execution {float(source_accuracy.get('plan_execution_accuracy_percent') or 0):.2f}%"
                if source_accuracy.get('plan_source_divergence_note'):
                    accuracy_note+=" · plan/source divergence"
            elif plan_accuracy:
                # Source-relative metrics unavailable: label the legacy score
                # truthfully instead of presenting it as source pixel accuracy.
                accuracy_note=(f" • plan execution: {float(plan_accuracy.get('final_plan_execution_accuracy_percent',plan_accuracy.get('final_accuracy_percent',0)) or 0):.2f}%"
                               f" · coverage {float(plan_accuracy.get('coverage_percent',0) or 0):.2f}%")
            if plan_accuracy:
                accuracy_note+=(f" · plan errors {int(plan_accuracy.get('final_error_pixels',0) or 0):,}"
                                f" · corrections {int(plan_accuracy.get('correction_paths_added',0) or 0):,}")
                if plan_accuracy.get('unrepairable_background_pixels',0):
                    accuracy_note+=f" · {int(plan_accuracy['unrepairable_background_pixels']):,} spill pixels need a white palette color"
            planner_note=''
            if opts.get('planning_resolution_effective'):
                sample=f"{opts.get('planner_sample_limit')} px" if opts.get('planner_sample_limit') else ''
                pixels=f"{int(opts.get('planner_max_pixels',0)):,} px budget" if opts.get('planner_max_pixels') else ''
                pieces=' · '.join(x for x in (sample,pixels) if x)
                planner_note=f" • planning: {opts.get('planning_resolution_effective')}" + (f" · {pieces}" if pieces else '')
            preview_note=''
            if opts.get('_preview_plan'):
                ta=value.get('target_area') or opts.get('_target_area')
                pa=value.get('preview_area') or opts.get('_preview_area')
                elapsed=value.get('preview_elapsed_seconds')
                preview_note=' Safe preview is optimized and cancellable; the final full-size plan is rebuilt with your selected CPU/GPU/quality settings when you press Start Drawing.'
                if value.get('preview_fallback_used'):
                    preview_note+=' Fast fallback was used because the accurate preview attempt exceeded its time limit.'
                elif opts.get('_preview_safe_pipeline'):
                    requested=opts.get('_preview_requested_planning_resolution')
                    effective=opts.get('planning_resolution_effective',opts.get('planning_resolution'))
                    if requested and effective and requested!=effective:
                        preview_note+=f' Preview planning was capped from {requested} to {effective} for UI stability.'
                if ta and pa and tuple(ta)!=tuple(pa):
                    preview_note+=f' Preview canvas: {pa[0]}×{pa[1]} from target {ta[0]}×{ta[1]}.'
                if isinstance(elapsed,(int,float)):
                    preview_note+=f' Preview planned in {elapsed:.1f}s.'
            perf=value.get('performance_profile') or {}
            perf_note=(f"\nProfiler: {format_performance_profile(perf, compact=True)}" if perf else '')
            shown_unit=time_meta.get('projected_label') or unit
            measured_samples=int(time_meta.get('measured_samples',0) or 0)
            estimate_source=str(time_meta.get('estimate_source') or 'operation timing model')
            if measured_samples:
                estimate_intro=f"Measured-calibrated draw time: about {shown_unit} ({time_meta.get('range_label')}, {time_meta.get('confidence')} confidence)"
            elif time_meta.get('is_projection'):
                estimate_intro=f"Estimated final draw time: about {shown_unit} ({time_meta.get('range_label')}, {time_meta.get('confidence')} confidence)"
            else:
                estimate_intro=f"Estimated draw time: about {shown_unit}"
            estimate_note=f" • timing source: {estimate_source}"
            self.status.set(f'{estimate_intro}. Build preview complete.')
            self.summary.set(f"{estimate_intro}{estimate_note} • preview-plan estimate {unit} • {int(value['count']):,} brush strokes{portrait_note} • {precision} precision{human_note}{gpu_note}{fill_note}{simplify_note}{grouping_note}{color_note}{path_note}{optimizer_note}{adaptive_note}{budget_note}{accuracy_note}{planner_note}{watchdog_note}{preview_safety_note}{resource_note}\nBrush: {brush_px} px. Set the same width in the target application.{brush_tip}{priority_tip}{time_tip}{preview_note}{perf_note}")
            try:
                from PreviewDiagnostics import build_preview_diagnostics,format_preview_diagnostics
                _diag=value.get('preview_diagnostics') or build_preview_diagnostics(
                    opts,accuracy=source_accuracy,delta_e=opts.get('preview_delta_e_meta') or {},
                    draw_time=time_meta,path_count=int(value.get('count',0) or 0),
                    source_count=int(value.get('source_count',0) or 0),performance_profile=perf)
                value['preview_diagnostics']=_diag;opts['preview_diagnostics_meta']=_diag
                self.preview_diagnostics_text.set(format_preview_diagnostics(_diag))
            except Exception as _diag_ui_error:
                self.preview_diagnostics_text.set(f'Preview diagnostics unavailable: {_diag_ui_error}')
            self.show_previews()
        elif kind=='deadline_telemetry':
            if isinstance(value,dict):
                mode=str(value.get('mode') or 'NORMAL')
                elapsed=float(value.get('elapsed_seconds',0) or 0)
                left=value.get('remaining_budget_seconds')
                predicted=float(value.get('predicted_finish_seconds',0) or 0)
                delta=value.get('schedule_delta_seconds')
                ops=float(value.get('operations_per_second',0) or 0)
                phase=str(value.get('current_phase') or 'planning')
                skipped=int(value.get('skipped_low_value',0) or 0)
                coverage=float(value.get('structural_coverage_percent',0) or 0)
                multiplier=float(value.get('runtime_cost_multiplier',1.0) or 1.0)
                samples=int(value.get('runtime_samples',0) or 0)
                strategy=str(value.get('strategy') or 'planned-quality')
                left_text='∞' if left is None else f'{float(left):.1f}s'
                delta_text='n/a' if delta is None else f'{float(delta):+.1f}s'
                live_text=(f'live ×{multiplier:.2f} ({samples} samples)' if samples else 'uncalibrated estimate')
                interval=value.get('prediction_interval') or {}
                if interval:
                    live_text+=f" · remaining estimate {float(interval.get('lower_seconds',0)):.1f}–{float(interval.get('upper_seconds',0)):.1f}s"
                self.status.set(f'{mode} · {strategy} · elapsed {elapsed:.1f}s · budget left {left_text} · predicted finish {predicted:.1f}s · schedule {delta_text} · {ops:.1f} ops/s · {live_text} · {phase} · structure sent {coverage:.0f}% · skipped {skipped}')
        elif kind=='performance_benchmark':
            if isinstance(value,dict):
                text=str(value.get('text','Performance benchmark complete.'))
                self.status.set(text)
                try:self.summary.set('Performance benchmark (planning only; no mouse input):\n'+text)
                except (tk.TclError,AttributeError):pass
        elif kind=='benchmark_suite':
            if isinstance(value,dict):
                text=str(value.get('text','Benchmark suite complete.'))
                self.status.set(text.split('\n',1)[0])
                try:self.benchmark_suite_text.set(text)
                except (tk.TclError,AttributeError):pass
                try:self.summary.set('Step 10 benchmark suite (local planning/preview only; no mouse input):\n'+text)
                except (tk.TclError,AttributeError):pass
        elif kind=='golden_regression':
            if isinstance(value,dict):
                text=str(value.get('text','Golden image regression complete.'))
                self.status.set(text.split('\n',1)[0])
                try:self.benchmark_suite_text.set(text)
                except (tk.TclError,AttributeError):pass
                try:self.summary.set('Step 17 golden image regression (local synthetic fixtures only; no mouse/screen/network):\n'+text)
                except (tk.TclError,AttributeError):pass
        elif kind=='result_recheck_status':
            request,message=value
            if DrawBotApp._result_recheck_current(self,request):self.status.set(str(message))
        elif kind=='result_recheck_complete':
            if not isinstance(value,ResultRecheckResult):return
            request=value.request
            try:
                if not DrawBotApp._result_recheck_current(self,request):return
                from copy import deepcopy
                options=request.plan['options']
                options['post_draw_accuracy_meta']=deepcopy(value.metrics)
                # A new observation is not a new correction and must not prefer
                # an inherited correction's older post_* score or gain.
                for name in ('post_draw_before_correction_accuracy_meta','pre_correction_accuracy_meta',
                             'post_draw_correction_meta','correction_review_meta','correction_history_meta'):
                    options.pop(name,None)
                if value.history:options['correction_history_meta']=deepcopy(value.history)
                self.correction_history_meta=deepcopy(value.history)
                DrawBotApp.refresh_correction_review_ui(self)
                message=('Result re-check complete. ' if value.metrics.get('available') else 'Result re-check unavailable. ')
                message+=str(value.metrics.get('summary') or value.metrics.get('reason') or 'Fresh read-only result metrics are in Correction Review.')
                if value.history_error:message+=' History could not be saved: '+value.history_error
                self.status.set(message)
            finally:
                request.release()
        elif kind=='correction_review':
            try:
                from CorrectionReviewRecovery import format_correction_review
                state=value if isinstance(value,dict) else DrawBotApp.refresh_correction_review_ui(self)
                self.correction_review_meta=state
                if hasattr(self,'correction_review_text'):
                    self.correction_review_text.set('\n'.join(format_correction_review(state).splitlines()[:5]))
            except Exception as _review_error:
                try:self.correction_review_text.set(f'Correction Review unavailable: {_review_error}')
                except Exception:pass
        elif kind=='done':
            # Ignore a stale completion event if a future operation somehow owns
            # the UI already. This makes the queue fail closed instead of enabling
            # controls for the wrong worker.
            from StabilityRC import current_completion
            if current_completion(self.activity,value):
                finished=self.activity
                if recheck_done_request is not None:DrawBotApp._finish_result_recheck(self,recheck_done_request)
                if finished in ('draw','dry-run'):self._draw_plan_publication=None
                if browser_done_request is not None:self.browser_one_click_worker_request=None
                if finished=='recovery-clear':
                    previous=getattr(self,'_recovery_clear_previous_suppression',None)
                    self._recovery_clear_previous_suppression=None
                    if previous is not None:self._suppress_recovery=previous
                if finished=='performance-auto-tuner':
                    self.hardware_benchmark_running=False
                    if self.stop.is_set():
                        self.auto_tune_summary.set('Universal Hardware Auto Benchmark cancelled.')
                        self.auto_tune_detail.set('No new recommendation was applied.')
                screen_window=getattr(self,'screen_task_window',None)
                if screen_window is not None:screen_window.restore()
                self.set_busy(None)
                self.worker=None
                if self.stop.is_set() and not self.closing:
                    terminal=getattr(self,'_worker_terminal_status',None)
                    self.status.set(terminal[1] if terminal and terminal[0]==finished else 'Stopped.')
                self._worker_terminal_status=None
                if finished=='recovery-load':
                    pending=getattr(self,'recovery_loaded_pending',None)
                    self.recovery_loaded_pending=None
                    if pending is not None:
                        if self.closing or self.stop.is_set():
                            DrawBotApp._discard_worker_result(self,'recovery_loaded',pending)
                        else:
                            state,image=pending
                            try:DrawBotApp._apply_recovery_snapshot(self,state,recovered_image=image)
                            except Exception as error:
                                DrawBotApp._discard_worker_result(self,'recovery_loaded',pending)
                                log_event(f'Safe session recovery failed: {error!r}')
                                self.status.set(f'The local session could not be fully restored: {error}')
                if finished in ('draw','dry-run','mouse-test') and not self.closing:
                    try:self.root.deiconify()
                    except tk.TclError:pass
                if finished in ('draw','dry-run') and not self.closing:
                    view=DrawBotApp._runtime_safety_view(self)
                    view.finish(view.request)
                    self.refresh_runtime_safety_ui()
                    try:self.refresh_correction_review_ui()
                    except Exception:pass
                    if getattr(self,'drop_in_sync_phase',None)==DROP_SYNC_DRAWING:self.drop_in_sync_phase=DROP_SYNC_READY
                if finished=='smart-drop-detect' and not self.closing:
                    payload=getattr(self,'smart_drop_pending_payload',None)
                    self.smart_drop_pending_payload=None
                    if payload:
                        try:DrawBotApp._show_smart_drop_overlay(self,payload)
                        except Exception as error:
                            self.status.set(f'Game Canvas Drop could not open its canvas listener: {error}')
                            try:self.smart_drop_in_text.set('Canvas drop listener failed. Use normal target selection or drag the image into Image Draw Bot instead.')
                            except Exception:pass
                            log_event(f'Game Canvas Drop overlay failed: {error!r}')
                if finished=='load' and not self.closing:
                    DrawBotApp._schedule_pending_drop_in_start(self)
                if finished=='browser-one-click-setup' and not self.closing:
                    request=browser_done_request
                    if (DrawBotApp._browser_one_click_request_current(self,request) and
                            request['phase']=='ready' and request['auto_start']):
                        request['phase']='finish'
                        DrawBotApp._schedule_browser_one_click(self,request,finish=True)
                    elif (request is not None and request is getattr(self,'browser_one_click_request',None) and
                          request['phase']!='ready'):
                        force=request['force']
                        DrawBotApp._cancel_browser_one_click(self,'setup did not finish successfully',request=request)
                        self.drop_in_sync_phase=DROP_SYNC_IDLE
                        try:self.browser_one_click_text.set(('Canvas-drop verification failed safely. The image is loaded, but drawing was not started.' if force else 'One-Click setup failed safely. Bring the game window into view or use Auto setup browser manually.'))
                        except Exception:pass
                if finished=='browser-auto-calibration' and not self.closing:
                    if bool(getattr(self,'browser_auto_calibration_success',False)):
                        if getattr(self,'drop_in_sync_phase',None)==DROP_SYNC_AUTO_SETUP:self.drop_in_sync_phase=DROP_SYNC_READY
                        DrawBotApp._schedule_drop_in_sync_tick(self,40)
                    else:
                        if getattr(self,'pending_drop_in_import',None) is not None or normalize_drop_in_action(getattr(self,'drop_action_pending',None))==DROP_IN_ACTION:
                            DrawBotApp._disarm_manual_drop_in(self,'browser auto setup failed while Drop-In was waiting')
                            try:self.status.set('Drop-In blocked: Browser Auto Setup did not complete successfully. No drawing was started.')
                            except Exception:pass
                        self.drop_in_sync_phase=DROP_SYNC_IDLE
        else:
            log_event(f'Ignored unknown UI event: {kind!r}')

    def _remove_hotkeys(self):
        if self.hotkeys_removed:return
        self.hotkeys_removed=True
        for hotkey in list(self.hotkeys):
            try:self.keyboard.remove_hotkey(hotkey)
            except Exception as error:log_event(f'Hotkey cleanup skipped: {error!r}')
        self.hotkeys.clear()

    def _finish_shutdown(self):
        if self.shutdown_complete or getattr(self,'_shutdown_finishing',False):return
        job=DrawBotApp._cancel_recovery_image_job(self)
        if job is not None and job.is_alive():
            if getattr(self,'recovery_shutdown_after',None) is None:
                def retry():
                    self.recovery_shutdown_after=None
                    DrawBotApp._finish_shutdown(self)
                try:self.recovery_shutdown_after=self.root.after(50,retry)
                except (tk.TclError,RuntimeError):
                    log_event('Shutdown could not schedule recovery cleanup; its cancelled worker retains local cleanup ownership.')
            return
        self._recovery_image_job=None
        DrawBotApp._cancel_after_attr(self,'recovery_shutdown_after')
        self._shutdown_finishing=True
        try:
            DrawBotApp._finish_result_recheck(self)
            DrawBotApp._cancel_after_attr(self,'poll_after')
            DrawBotApp._cancel_after_attr(self,'recovery_checkpoint_after')
            self._remove_hotkeys()
            DrawBotApp._cancel_mobile_preview_discovery(self,retire=True)
            self.stop_mobile_preview(quiet=True)
            try:
                self.root.destroy()
            except (tk.TclError,RuntimeError) as error:
                from AppBranding import _already_destroyed_tcl_error
                if not (isinstance(error,tk.TclError) and _already_destroyed_tcl_error(error)):
                    log_error(f'Window shutdown failed and remains retryable: {error!r}',
                              category='shutdown',exc_info=True)
                    try:self.status.set('Could not close the window. Close again to retry; recovery data is preserved.')
                    except (tk.TclError,RuntimeError,AttributeError):pass
                    return
            # Native destruction can invoke converging Close/Destroy callbacks.
            # The in-progress guard prevents recursion; success and recovery
            # deletion belong only to the completed outer destruction.
            self.shutdown_complete=True
            try:
                from SessionRecovery import clear_snapshot
                clear_snapshot()
                log_event('Clean shutdown: recovery checkpoint cleared.')
            except Exception as error:log_event(f'Could not clear recovery checkpoint on clean shutdown: {error!r}')
            clean_exit()
        finally:
            self._shutdown_finishing=False

    def poll(self):
        self.poll_after=None
        DrawBotApp._poll_mobile_preview_discovery(self)
        processed=0
        started=time.monotonic()
        while processed<250 and (processed==0 or time.monotonic()-started<.015):
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            processed+=1
            try:self._handle_event(kind,value)
            except Exception as error:
                import traceback
                log_event(f'UI event {kind!r} was contained: {error!r}\n{traceback.format_exc()}')
                if not self.closing:
                    try:self.status.set(f'UI event error contained: {error}')
                    except tk.TclError:pass
        if self.stop.is_set():
            self.drop_action_pending=None
            # A stop event may remain set until the next worker starts. Do not
            # repeatedly disarm/log the already-idle Drop-In state on every Tk
            # poll tick; one transition is enough.
            has_drop_state = (
                DrawBotApp._manual_drop_in_armed(self) or
                getattr(self,'pending_drop_in_import',None) is not None or
                getattr(self,'drop_in_start_context',None) is not None or
                getattr(self,'drop_in_sync_phase',DROP_SYNC_IDLE) != DROP_SYNC_IDLE
            )
            if has_drop_state:
                DrawBotApp._disarm_manual_drop_in(self,'stop requested')
        elif normalize_drop_in_action(getattr(self,'drop_action_pending',None)) is None:
            self.drop_action_pending=None
        # RC2 fallback: if Tk dropped/cancelled the original after() callback,
        # a queued One-Click request is re-scheduled as soon as the UI is idle.
        if (getattr(self,'browser_one_click_pending',False) and not self.activity and
                not self.closing and getattr(self,'browser_one_click_after',None) is None):
            DrawBotApp._schedule_browser_one_click(self,getattr(self,'browser_one_click_request',None))
        if self.needs_plan and not self.activity and not self.closing:
            self.needs_plan=False
            if hasattr(self,'_maybe_auto_preview'):
                self._maybe_auto_preview(delay=900, reason='queued-plan')
            elif hasattr(self,'update_plan'):
                self.update_plan()
        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self._finish_shutdown();return
        DrawBotApp._schedule_poll(self)

    def close(self):
        if self.shutdown_complete:return
        if self.closing:
            # Keep a failed native teardown retryable without re-saving settings
            # or restarting workers that were already stopped for this close.
            if self.worker is None or not self.worker.is_alive():self._finish_shutdown()
            return
        DrawBotApp._close_smart_drop_overlay(self,'application shutdown')
        self.smart_drop_pending_payload=None
        self.smart_drop_generation=int(getattr(self,'smart_drop_generation',0))+1
        self.closing=True
        DrawBotApp._cancel_mobile_preview_discovery(self,retire=True)
        DrawBotApp._runtime_safety_view(self).clear()
        DrawBotApp._cancel_recovery_image_job(self)
        log_event('Shutdown requested.')
        try:self.save_settings()
        except Exception as error:log_event(f'Settings save during shutdown failed: {error!r}')
        self.cancel()
        DrawBotApp._cancel_after_attr(self,'profile_change_after')
        DrawBotApp._cancel_after_attr(self,'paint_config_after')
        try:self.set_busy('closing')
        except (tk.TclError,RuntimeError):pass
        for name in ('calibration_window','paint_tool_window','app_tool_window'):
            window=getattr(self,name,None)
            if window is None:continue
            try:
                if window.winfo_exists():window.destroy()
            except (tk.TclError,RuntimeError,AttributeError):pass
        if self.worker is None or not self.worker.is_alive():
            self._finish_shutdown()


def create_root():
    """Create one CustomTkinter-native root with optional TkDND support.

    CustomTkinter widgets are most stable when their toplevel is CTk rather than
    a plain tkinter.Tk. TkinterDnD's wrapper can be mixed into CTk so drag/drop
    remains available without replacing the CTk root implementation.
    """
    from AppBranding import configure_root, set_windows_app_id
    from UiCompatibility import scoped_window_class
    set_windows_app_id()
    try:
        import customtkinter as ctk
        try:
            from UiCompatibility import patch_customtkinter_scroll_guard
            patch_customtkinter_scroll_guard()
        except Exception as error:
            log_event(f'CustomTkinter scroll compatibility patch skipped: {error!r}')
    except ImportError:
        ctk=None
    if ctk is not None:
        owned_ctk=scoped_window_class(ctk.CTk)
        try:
            from tkinterdnd2 import TkinterDnD
        except ImportError:
            return configure_root(owned_ctk())
        class ImageDrawBotRoot(owned_ctk,TkinterDnD.DnDWrapper):
            pass
        root=ImageDrawBotRoot()
        try:
            root.TkdndVersion=TkinterDnD._require(root)
        except (ImportError,RuntimeError,tk.TclError):
            # The native extension failed after Tk was created. Dispose that
            # interpreter/window before creating a clean non-DnD fallback.
            # A real teardown failure remains visible instead of orphaning it.
            root.destroy()
            root=owned_ctk()
        return configure_root(root)

    try:
        from tkinterdnd2 import TkinterDnD
        return configure_root(scoped_window_class(TkinterDnD.Tk)())
    except (ImportError,RuntimeError,tk.TclError):
        return configure_root(scoped_window_class(tk.Tk)())


def main():
    enable_dpi_awareness()
    from InstanceLock import InstanceLock
    lock=InstanceLock()
    root=create_root()
    if lock.already_running:
        root.withdraw();messagebox.showinfo('Image Draw Bot is already open','Close the other instance first.');root.destroy();lock.close();return
    begin_run_marker()
    try:
        DrawBotApp(root)
    except Exception as error:
        messagebox.showerror('Image Draw Bot could not start',str(error))
        root.destroy();lock.close();raise
    try:root.mainloop()
    finally:lock.close()


def self_test(gui=False):
    # Windows CI runs these modes without hooks, clicks, capture or network.
    import os
    from PIL import Image
    if os.name == 'nt':
        # Exercise the native ABI in source, frozen and installed builds. A
        # headless machine may have no hardware adapters; API failures must
        # still fail this gate instead of being hidden by the CPU fallback.
        from WindowsGpuDiscovery import enumerate_adapters
        enumerate_adapters()
    plan=make_plan(Image.new('RGBA',(8,4),'black'),(80,40),
                   dict(detail=10,delay=.01,lines=True,skip_white=True,contrast=1,outline=False))
    assert plan['count']>0
    if gui:
        class NoInput:
            def add_hotkey(self,*args):return len(args)
            def remove_hotkey(self,*args):pass
            def get_position(self):return (0,0)
        root=create_root()
        try:
            app=DrawBotApp(root,NoInput(),NoInput())
            assert hasattr(root,'drop_target_register')
            app.original=Image.new('RGBA',(120,80),'orange');app.plan=plan
            app.workspace_layout.select('Workspace')
            root.update_idletasks();root.update();app.show_previews();root.update_idletasks()
            assert app.start.winfo_ismapped()
            assert app.original_canvas.winfo_width()>100
            assert app.activity is None
        finally:root.destroy()


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    import sys
    if '--collect-diagnostics' in sys.argv:
        from DiagnosticsPackage import main as collect_main
        raise SystemExit(collect_main())
    if '--configure-crash-dumps' in sys.argv:
        from CrashDumpConfig import main as dump_config_main
        raise SystemExit(dump_config_main(sys.argv[sys.argv.index('--configure-crash-dumps')+1:]))
    if '--internal-mouse-probe' in sys.argv:
        from MouseProbe import main as mouse_probe_main
        args=[arg for arg in sys.argv[1:] if arg!='--internal-mouse-probe']
        raise SystemExit(mouse_probe_main(args))
    if '--internal-target-probe' in sys.argv:
        from TargetProbe import main as target_probe_main
        args=[arg for arg in sys.argv[1:] if arg!='--internal-target-probe']
        raise SystemExit(target_probe_main(args))
    if '--internal-palette-calibration' in sys.argv:
        from GetColorPositions import main as palette_calibration_main
        args=[arg for arg in sys.argv[1:] if arg!='--internal-palette-calibration']
        raise SystemExit(palette_calibration_main(args))
    if '--internal-exact-color-calibration' in sys.argv:
        from ExactColorCalibration import main as exact_color_main
        args=[arg for arg in sys.argv[1:] if arg!='--internal-exact-color-calibration']
        raise SystemExit(exact_color_main(args))
    if '--gpu-info' in sys.argv:
        try:
            info=acceleration_info('Auto')
            print(json.dumps(info.as_dict(),ensure_ascii=False));sys.exit(0)
        except Exception as error:
            print(json.dumps({'backend':'CPU','accelerated':False,'reason':str(error)},ensure_ascii=False));sys.exit(0)
    if '--self-test' in sys.argv or '--smoke-test' in sys.argv:
        try:self_test(gui='--smoke-test' in sys.argv)
        except Exception:
            import traceback
            (DATA_DIR/'smoke-test-error.log').write_text(traceback.format_exc(),encoding='utf-8')
            sys.exit(1)
        sys.exit(0)
    main()
