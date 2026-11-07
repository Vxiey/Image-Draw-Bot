"""Time-aware exact-colour budgeting for Image Draw Bot Step 6.

Composes Step 5's image-complexity recommendation with the active drawing
budget.  It does not alter palette extraction, renderer geometry or stroke
ordering.  Explicit numeric colour limits remain authoritative because callers
only invoke this helper for ``Exact color count = Auto``.

The cost model prefers locally measured runtime operation timings when they are
available.  Before calibration it falls back to the target profile's native
palette/custom-colour timing plus a conservative estimate of the path
fragmentation caused by each additional colour.
"""
from __future__ import annotations

import math
from typing import Any

from StrokeDelivery import resolve_stroke_delivery
from TimeBudgetEngine import resolve_budget


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _runtime_average(item: Any) -> float | None:
    if not isinstance(item, dict):
        return None
    average = _finite(item.get('average_seconds'), 0.0)
    if average > 0.0:
        return average
    count = max(0, int(_finite(item.get('count'), 0)))
    total = _finite(item.get('total_seconds'), 0.0)
    if count <= 0 or total <= 0.0:
        return None
    average = total / float(count)
    return average if math.isfinite(average) and average > 0 else None


def _load_calibration(options: dict[str, Any]) -> dict[str, Any]:
    override = options.get('_time_color_calibration_override')
    if isinstance(override, dict):
        return dict(override)
    try:
        from DrawTimeCalibration import correction_for
        return correction_for(options)
    except Exception:
        return {'learned': False, 'samples': 0, 'operation_runtime': {}}


def _resolved_budget(options: dict[str, Any]) -> dict[str, Any]:
    """Use the already-resolved DrawBot budget when present, otherwise resolve it."""
    mode = str(options.get('time_budget_mode') or 'Manual')
    if mode in ('Unlimited', 'Unlimited / Accuracy') or bool(options.get('unlimited_time')):
        return {
            'mode': mode, 'active': False, 'unlimited': True,
            'total_seconds': None, 'reserve_seconds': 0.0,
            'render_budget_seconds': None, 'source': 'unlimited accuracy mode',
        }

    # make_plan runs _ensure_time_budget_options before Step 6. Reuse those
    # exact values so colour budgeting cannot disagree with the deadline engine.
    if bool(options.get('time_budget_active')) and options.get('deadline_render_budget_seconds') is not None:
        return {
            'mode': mode, 'active': True, 'unlimited': False,
            'total_seconds': options.get('deadline_total_seconds', options.get('deadline_game_time_seconds')),
            'reserve_seconds': _finite(options.get('deadline_safety_reserve_seconds'), 0.0),
            'render_budget_seconds': _finite(options.get('deadline_render_budget_seconds'), options.get('time_budget_seconds', 0.0)),
            'hard_stop_seconds': options.get('deadline_hard_stop_seconds'),
            'source': str(options.get('deadline_budget_source') or 'resolved Image Draw Bot deadline'),
        }

    manual = options.get('manual_max_seconds', options.get('max_seconds', 180))
    reserve = options.get('deadline_safety_reserve', 'Auto')
    try:
        return resolve_budget(mode, manual, reserve)
    except (TypeError, ValueError):
        return {
            'mode': mode, 'active': False, 'unlimited': False,
            'total_seconds': _finite(manual, 180.0), 'reserve_seconds': 0.0,
            'render_budget_seconds': _finite(manual, 180.0), 'source': 'legacy/manual fallback',
        }


def _profile_fallback_seconds_per_path(profile_key: str) -> float:
    key = str(profile_key or '').lower()
    if key == 'microsoft-paint':
        return 0.040
    if key == 'gartic-phone':
        return 0.018
    if key in ('skribbl', 'skribbl-fast'):
        return 0.016 if key == 'skribbl' else 0.013
    if key in ('sketchheads', 'sketchful'):
        return 0.018
    return 0.030


def _color_share(render_seconds: float) -> float:
    """Fraction of usable drawing time allowed to be consumed by colour complexity."""
    seconds = max(1.0, float(render_seconds))
    if seconds <= 30:
        return .11
    if seconds <= 55:
        return .14
    if seconds <= 80:
        return .17
    if seconds <= 140:
        return .20
    if seconds <= 300:
        return .23
    return .25


def _structural_floor(step5_count: int, meta: dict[str, Any]) -> int:
    minimum = max(2, int(_finite(meta.get('minimum_colors'), 2)))
    hue_count = len(tuple(meta.get('dominant_hue_families') or ()))
    tones = max(1, int(_finite(meta.get('tone_bins'), 1)))
    significant = max(2, int(_finite(meta.get('significant_color_buckets'), step5_count)))
    tone_allowance = 2 if tones >= 3 else 1
    floor = max(minimum, hue_count + tone_allowance)
    return max(2, min(int(step5_count), significant, floor))


def _fragmentation_paths_per_extra_color(meta: dict[str, Any]) -> float:
    complexity = max(0.0, min(1.0, _finite(meta.get('complexity_score'), 0.5)))
    edge = max(0.0, min(1.0, _finite(meta.get('edge_density'), 0.15)))
    entropy = max(0.0, min(1.0, _finite(meta.get('color_entropy'), 0.5)))
    buckets = max(2.0, _finite(meta.get('significant_color_buckets'), 8.0))
    bucket_factor = min(1.0, max(0.0, (buckets - 2.0) / 30.0))
    # Extra colours split connected runs/regions. This is deliberately modest:
    # the actual renderer still owns path-count budgeting later in the pipeline.
    return 2.0 + 8.0 * complexity + 8.0 * edge + 4.0 * entropy + 4.0 * bucket_factor


def _marginal_costs(options: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    delivery = resolve_stroke_delivery(options, dry_run=False)
    calibration = _load_calibration(options)
    operation_runtime = calibration.get('operation_runtime') if isinstance(calibration, dict) else {}
    operation_runtime = operation_runtime if isinstance(operation_runtime, dict) else {}

    custom_available = bool(options.get('exact_color_available'))
    selector_kind = 'custom' if custom_available else 'palette'
    measured_key = 'color_change' if custom_available else 'palette_change'
    measured = _runtime_average(operation_runtime.get(measured_key))

    verification = 0.0
    if bool(options.get('adaptive_color_verification')):
        verification += float(delivery.palette_click_delay) + .14
    if bool(options.get('visual_verification_enabled')):
        verification += .08

    if measured is not None:
        direct = measured + verification
        direct_source = f'measured {measured_key}'
    else:
        direct = float(delivery.palette_click_delay)
        if custom_available:
            # Keep this aligned with DrawBot/AdaptiveDeadlineRenderer's current
            # custom RGB selector model until a real sample replaces it.
            direct += .78
        direct += verification
        direct_source = 'profile timing model'

    measured_path = _finite(calibration.get('seconds_per_completed_path') if isinstance(calibration, dict) else None, 0.0)
    if measured_path > 0.0:
        seconds_per_path = max(.001, min(2.0, measured_path))
        path_source = 'measured completed paths'
    else:
        seconds_per_path = _profile_fallback_seconds_per_path(delivery.profile_key)
        path_source = 'profile path model'

    frag_paths = _fragmentation_paths_per_extra_color(meta)
    frag_seconds = frag_paths * seconds_per_path
    marginal = max(.001, direct + frag_seconds)
    return {
        'direct_color_change_seconds': direct,
        'direct_color_change_source': direct_source,
        'selector_kind': selector_kind,
        'profile_key': delivery.profile_key or 'generic',
        'palette_click_delay_seconds': float(delivery.palette_click_delay),
        'seconds_per_path': seconds_per_path,
        'seconds_per_path_source': path_source,
        'calibration_samples': int(_finite(calibration.get('samples') if isinstance(calibration, dict) else 0, 0)),
        'estimated_fragmentation_paths_per_extra_color': frag_paths,
        'estimated_fragmentation_seconds_per_extra_color': frag_seconds,
        'estimated_marginal_color_seconds': marginal,
    }


def apply_time_aware_color_budget(step5_count: int, step5_meta: dict[str, Any] | None,
                                  options: dict[str, Any] | None, *, preview: bool = False) -> tuple[int, dict[str, Any]]:
    """Return Step 5's recommendation adjusted for the active usable deadline.

    ``step5_count`` is never increased. Manual/Unlimited modes return it
    unchanged. The structural hue/tone floor is preserved even when its cost is
    larger than the nominal colour-complexity share of a very short timer.
    """
    options = dict(options or {})
    meta = dict(step5_meta or {})
    base = max(2, int(step5_count or meta.get('recommended_colors') or 2))
    ceiling = max(base, int(_finite(meta.get('ceiling_colors'), base)))
    floor = _structural_floor(base, meta)
    budget = _resolved_budget(options)

    common = {
        'time_budget_applied': False,
        'time_aware': False,
        'image_recommended_colors': base,
        'recommended_colors': base,
        'time_color_floor': floor,
        'time_color_ceiling': base,
        'color_budget_limited': False,
        'time_budget_mode': str(budget.get('mode') or options.get('time_budget_mode') or 'Manual'),
        'time_budget_source': str(budget.get('source') or ''),
        'timer_total_seconds': budget.get('total_seconds'),
        'render_budget_seconds': budget.get('render_budget_seconds'),
        'preview': bool(preview),
    }
    meta.update(common)

    if not bool(budget.get('active')) or budget.get('render_budget_seconds') is None:
        meta['time_color_reason'] = 'No active deadline; Step 5 image-complexity recommendation preserved.'
        return base, meta

    render_seconds = max(1.0, _finite(budget.get('render_budget_seconds'), 1.0))
    costs = _marginal_costs(options, meta)
    share = _color_share(render_seconds)
    allowance = render_seconds * share
    marginal = max(.001, float(costs['estimated_marginal_color_seconds']))

    # The protected structural floor is non-negotiable. Additional colours are
    # admitted only while their predicted selector + fragmentation cost fits the
    # colour-complexity allowance.
    floor_cost = float(floor) * marginal
    if base <= floor:
        chosen = base
    else:
        extra_allowance = max(0.0, allowance - floor_cost)
        extras = int(math.floor((extra_allowance + 1e-9) / marginal))
        chosen = min(base, floor + max(0, extras))
        chosen = max(floor, chosen)

    estimated_overhead = chosen * marginal
    meta.update(costs)
    meta.update({
        'time_budget_applied': True,
        'time_aware': True,
        'recommended_colors': int(chosen),
        'ceiling_colors': int(ceiling),
        'time_color_floor': int(floor),
        'time_color_ceiling': int(base),
        'color_budget_limited': bool(chosen < base),
        'color_time_share_percent': round(share * 100.0, 2),
        'base_color_overhead_budget_seconds': round(allowance, 4),
        'color_overhead_budget_seconds': round(max(allowance, floor_cost), 4),
        'estimated_color_overhead_seconds': round(estimated_overhead, 4),
        'estimated_marginal_color_seconds': round(marginal, 6),
        'direct_color_change_seconds': round(float(costs['direct_color_change_seconds']), 6),
        'palette_click_delay_seconds': round(float(costs['palette_click_delay_seconds']), 6),
        'seconds_per_path': round(float(costs['seconds_per_path']), 6),
        'estimated_fragmentation_paths_per_extra_color': round(float(costs['estimated_fragmentation_paths_per_extra_color']), 3),
        'estimated_fragmentation_seconds_per_extra_color': round(float(costs['estimated_fragmentation_seconds_per_extra_color']), 6),
        'time_color_reason': (
            f"Active {common['time_budget_mode']} budget: {base} image-recommended -> {chosen} time-aware colors; "
            f"protected floor {floor}, usable render {render_seconds:.1f}s, marginal color cost ~{marginal:.3f}s."
        ),
    })
    return int(chosen), meta
