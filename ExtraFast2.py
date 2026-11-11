"""Extra Fast 2.0 execution policy.

The old Extra Fast preset mainly enabled conservative bucket fills. v2 keeps
those safe outline+fill substitutions, but also makes the normal fallback path
much cheaper by allowing longer *lossless* serpentine scanline paths. A
connector is still only permitted where adjacent same-colour runs overlap, so
speed comes from fewer mouse press/release boundaries rather than painting
across gaps.

The adaptive path policy evaluates a tiny bounded set of continuous-path limits.
Candidate selection is travel-aware: it simulates the same existing
``StrokeOptimizer`` stage used later by ``DrawBot.finish_plan`` and compares
ExecutionCostModel execution cost after that ordering. The selected proposal is
then checked once more as a complete plan after the normal target-path cap and
StrokeOptimizer. The unoptimized plan is returned so ``finish_plan`` remains the
single owner of real downstream ordering.

This module does not alter colors or remove details. Color choice remains the
responsibility of the color/accuracy pipeline.
"""
from __future__ import annotations

from typing import Any, Sequence
import math


_MAX_PREPARED_PATH_COSTS = 4096
_MAX_PREPARED_PATH_POINTS = 65536


class _PreparedPathCosts:
    """Bounded, operation-owned view of exact costs for immutable planner paths."""

    def __init__(self, model, cancelled):
        self._model = model
        self._cancelled = cancelled
        self._costs = {}
        self._points = 0
        self._enabled = True

    def __getattr__(self, name):
        return getattr(self._model, name)

    def path_seconds(self, path, *, cursor=None, brush_px=None):
        if self._cancelled():
            raise InterruptedError()
        prepared = None
        if self._enabled and len(path) <= _MAX_PREPARED_PATH_POINTS:
            try:
                # Direction and every intermediate point remain part of the key.
                # These internal paths already contain immutable coordinate tuples.
                key = (tuple(path), brush_px)
                prepared = self._costs.get(key)
                if prepared is None and (len(self._costs) < _MAX_PREPARED_PATH_COSTS
                        and self._points + len(path) <= _MAX_PREPARED_PATH_POINTS):
                    prepared = self._model.prepare_path_cost(
                        path, brush_px=brush_px, cancelled=self._cancelled)
                    self._costs[key] = prepared
                    self._points += len(path)
            except MemoryError:
                # This optional cache must not turn a runnable plan into an OOM.
                self._costs.clear()
                self._points = 0
                self._enabled = False
                prepared = None
                if self._cancelled():
                    raise InterruptedError()
        if prepared is None:
            seconds = self._model.path_seconds(path, cursor=cursor, brush_px=brush_px)
        else:
            seconds = prepared.seconds(cursor=cursor)
        if self._cancelled():
            raise InterruptedError()
        return seconds

    def paths_seconds(self, paths, *, cursor=None, brush_px=None):
        total = 0.0
        current = cursor
        for path in paths or ():
            if not path:
                continue
            total += self.path_seconds(path, cursor=current, brush_px=brush_px)
            current = tuple(map(int, path[-1]))
        return total

    def close(self):
        self._costs.clear()
        self._points = 0
        self._enabled = False
        self._model = self._cancelled = None


def path_limits(options: dict[str, Any]) -> tuple[int, int, str]:
    """Return bounded continuous-path limits for Extra Fast 2.0."""
    active = bool(options.get('time_budget_active')) and not (
        options.get('unlimited_time') or options.get('time_budget_mode') in ('Unlimited','Unlimited / Accuracy'))
    try:
        seconds = float(options.get('max_seconds', 180) or 180)
    except (TypeError, ValueError, OverflowError):
        seconds = 180.0
    if not math.isfinite(seconds) or seconds <= 0:
        seconds = 180.0
    if active and seconds <= 80:
        return 220, 900, 'critical-deadline'
    if active and seconds <= 150:
        return 180, 760, 'short-deadline'
    if active and seconds <= 300:
        return 140, 620, 'timed'
    return 110, 480, 'quality-speed'


def _candidate_limits(rows: int, points: int, policy: str) -> tuple[tuple[int, int], ...]:
    """Return a tiny bounded search space for safe continuous-path lengths."""
    presets = {
        'critical-deadline': ((220, 900), (320, 1300)),
        'short-deadline': ((180, 760), (260, 1100)),
        'timed': ((140, 620), (210, 900)),
        'quality-speed': ((110, 480), (160, 720), (220, 960)),
    }
    requested = ((max(1, int(rows)), max(2, int(points))),) + tuple(presets.get(policy, ()))
    out = []
    for item in requested:
        normalized = (max(1, min(360, int(item[0]))), max(2, min(1400, int(item[1]))))
        if normalized not in out:
            out.append(normalized)
    return tuple(out)


def _travel_selection_enabled(options: dict[str, Any]) -> bool:
    value = options.get('extra_fast_travel_optimizer', 'Auto')
    if isinstance(value, bool):
        return value
    normalized = str(value or 'Auto').strip().lower()
    return normalized not in ('off', 'false', '0', 'disabled', 'legacy')


def build_meta(groups: Sequence[Sequence], execution_groups: Sequence[Sequence] | None,
               options: dict[str, Any], *, fill_regions=()) -> dict[str, Any]:
    source_runs = sum(len(g) for g in groups)
    scanline_paths = source_runs if execution_groups is None else sum(len(g) for g in execution_groups)
    rows, points, policy = path_limits(options)
    fill_regions = list(fill_regions or ())
    fill_pixels = sum(max(0, int(r.get('area_pixels', 0) or 0)) for r in fill_regions if isinstance(r, dict))
    return {
        'enabled': True,
        'engine': 'Extra Fast 2.0 hybrid region renderer',
        'strategy': 'OUTLINE_FILL -> CONNECTED_SCANLINES -> DETAIL',
        'color_pipeline_preserved': True,
        'source_runs_after_fill': int(source_runs),
        'connected_scanline_paths': int(scanline_paths),
        'scanline_boundaries_removed': max(0, int(source_runs - scanline_paths)),
        'scanline_boundary_reduction_percent': round((max(0, source_runs-scanline_paths)/max(1, source_runs))*100.0, 3),
        'fill_regions': len(fill_regions),
        'fill_pixels': int(fill_pixels),
        'max_rows_per_path': int(rows),
        'max_points_per_path': int(points),
        'path_policy': policy,
        'connector_rule': 'adjacent same-colour overlap only',
        'detail_protection': 'color/importance pipeline unchanged; no cross-gap shortcuts',
        'adaptive_path_policy': 'travel-aware bounded path lengths + per-region H/V alternatives; final downstream guard; baseline retained on regression',
    }


def _axis_candidate(group, edge_n, rows, points, cancelled):
    """Build one lossless candidate for both axis-aligned run directions."""
    from ContinuousPaths import _horizontal_paths, _segment_path
    candidate = [_segment_path(s) for s in group[:edge_n]]
    horizontal = []
    vertical = []
    other = []
    for x0, y0, x1, y1 in group[edge_n:]:
        if cancelled():
            raise InterruptedError()
        if y0 == y1:
            horizontal.append((x0, y0, x1, y1))
        elif x0 == x1:
            vertical.append((y0, x0, y1, x1))
        else:
            other.append(_segment_path((x0, y0, x1, y1)))
    candidate += _horizontal_paths(
        horizontal, cancelled,
        max_rows_per_path=rows, max_points_per_path=points,
    )
    joined_vertical = _horizontal_paths(
        vertical, cancelled,
        max_rows_per_path=rows, max_points_per_path=points,
    )
    candidate += [tuple((y, x) for x, y in path) for path in joined_vertical]
    candidate += other
    return candidate, len(horizontal), len(vertical), len(joined_vertical)


def _vertical_alternative(group, edge_n, cancelled):
    """Build one exact mixed H/V source candidate from connected regions.

    The old implementation only re-rasterized an entire colour group when its
    global bounding box was at least twice as tall as wide. That misses common
    images where one colour contains both a wide region and a separate tall
    region. Split the horizontal body into connected regions instead, keep wide
    regions horizontal, and re-rasterize only promising regions vertically.

    This helper still does not choose the execution winner: ``build_fast_paths``
    runs the candidate through the same ExecutionCostModel and full downstream
    regression guard as every other Extra Fast proposal.
    """
    from AxisRegionPlanner import regional_axis_variants

    body = list(group[edge_n:])
    variants = regional_axis_variants(body, cancelled=cancelled)
    if not variants:
        return None
    # Prefer the exact mixed representation with the largest raw boundary
    # reduction. The real execution-cost comparison below remains authoritative.
    candidate, _meta = min(
        variants,
        key=lambda item: (
            int(item[1].get('raw_run_delta', 0) or 0),
            -int(item[1].get('reoriented_regions', 0) or 0),
        ),
    )
    return list(group[:edge_n]) + list(candidate)


def _intrinsic_cost(paths, model) -> float:
    return sum(float(model.path_seconds(path)) for path in paths if path)


def _sequence_cost(model, paths) -> float:
    """Compatibility-safe sequence cost for real models and lightweight test doubles."""
    fn=getattr(model, 'paths_seconds', None)
    if callable(fn):
        return float(fn(paths))
    return sum(float(model.path_seconds(path)) for path in paths if path)


def _ordered_group_cost(paths, options, model, cancelled) -> tuple[float, dict[str, Any]]:
    """Model one color group after the same current StrokeOptimizer ordering."""
    from SpeedOptimizer import normalize_speed
    from StrokeOptimizer import optimize_path_group

    try:
        ordered, meta = optimize_path_group(
            paths,
            mode=options.get('stroke_optimizer', 'Auto'),
            drawing_mode=options.get('drawing_mode'),
            speed=normalize_speed(options.get('speed', 'Balanced')),
            cancelled=cancelled,
        )
    except ValueError:
        ordered = [tuple(path) for path in paths if path]
        meta = {'stroke_optimizer_effective': 'Off', 'optimizer_error': 'invalid setting'}
    return _sequence_cost(model, ordered), dict(meta)


def _downstream_plan_cost(groups, options, model, cancelled) -> tuple[float, dict[str, Any]]:
    """Evaluate the complete proposal after the real downstream cap + ordering."""
    from SpeedOptimizer import normalize_speed
    from StrokeOptimizer import optimize_execution_groups
    from TimeBudget import apply_target_path_cap

    cap = options.get('target_stroke_count_resolved')
    capped, cap_meta = apply_target_path_cap(
        groups,
        cap,
        prioritize_structure=bool(options.get('real_speed_structure_priority')),
    )
    try:
        ordered, _hints, optimizer_meta = optimize_execution_groups(
            capped,
            mode=options.get('stroke_optimizer', 'Auto'),
            drawing_mode=options.get('drawing_mode'),
            speed=normalize_speed(options.get('speed', 'Balanced')),
            phase_hints=getattr(capped, 'phase_hints', None),
            cancelled=cancelled,
        )
    except ValueError:
        ordered = [[tuple(path) for path in group if path] for group in capped]
        optimizer_meta = {'stroke_optimizer_effective': 'Off', 'optimizer_error': 'invalid setting'}

    path_seconds = sum(_sequence_cost(model, group) for group in ordered)
    color_groups = sum(1 for group in ordered if group)
    color_seconds = color_groups * float(getattr(model, 'color_change_seconds', 0.0) or 0.0)
    total = path_seconds + color_seconds
    meta = {
        'modeled_path_seconds': path_seconds,
        'modeled_color_seconds': color_seconds,
        'modeled_total_seconds': total,
        'nonempty_color_groups': color_groups,
        'target_cap_applied': bool(cap_meta.get('target_skipped_paths')),
        'target_skipped_paths': int(cap_meta.get('target_skipped_paths', 0) or 0),
        'protected_prefix_before': int(cap_meta.get('protected_prefix_before', 0) or 0),
        'protected_prefix_after': int(cap_meta.get('protected_prefix_after', 0) or 0),
        'semantic_hints_preserved': bool(cap_meta.get('semantic_hints_preserved')),
        'stroke_optimizer_effective': optimizer_meta.get('stroke_optimizer_effective', 'Off'),
    }
    return total, meta


def build_fast_paths(groups, options, *, portrait_edge_count=None, cancelled=lambda: False):
    """Choose a bounded lossless path plan using downstream-aware cost."""
    from ContinuousPaths import build_execution_paths
    from ExecutionCostModel import build_cost_model

    rows, points, policy = path_limits(options)
    limits = _candidate_limits(rows, points, policy)
    baseline = build_execution_paths(
        groups,
        enabled=True,
        portrait_edge_count=portrait_edge_count,
        max_rows_per_path=rows,
        max_points_per_path=points,
        cancelled=cancelled,
    )
    # The DrawBot call supplies exact source->target scale overrides. Direct
    # tests/benchmarks intentionally default to source-space 1:1.
    model = build_cost_model(options,(1,1),(1,1))
    travel_aware = _travel_selection_enabled(options)
    prepared = None
    if (callable(getattr(model, 'prepare_path_cost', None))
            and callable(getattr(model, 'paths_seconds', None))):
        try:
            prepared = _PreparedPathCosts(model, cancelled)
        except MemoryError:
            if cancelled():
                raise InterruptedError()
    try:
        return _choose_fast_paths(groups, options, baseline, prepared or model,
            rows, points, policy, limits, travel_aware,
            portrait_edge_count, cancelled)
    finally:
        if prepared is not None:
            prepared.close()


def _choose_fast_paths(groups, options, baseline, model, rows, points, policy,
                       limits, travel_aware, portrait_edge_count, cancelled):
    from ContinuousPaths import execution_groups_with_portrait_semantics
    from ExecutionCostModel import EXECUTION_MODEL_VERSION

    proposed = []
    duplicate_candidates_skipped = 0
    reoriented_groups = set()
    selected_rows = []
    intrinsic_before = 0.0
    intrinsic_proposed = 0.0
    local_ordered_before = 0.0
    local_ordered_proposed = 0.0

    for index, group in enumerate(groups):
        if cancelled():
            raise InterruptedError()
        group = list(group)
        edge_n = (
            max(0, min(len(group), int(portrait_edge_count)))
            if index == 0 and portrait_edge_count is not None else 0
        )
        original = list(baseline[index])
        original_intrinsic = _intrinsic_cost(original, model)
        if travel_aware:
            original_selection_cost, _ = _ordered_group_cost(original, options, model, cancelled)
        else:
            original_selection_cost = original_intrinsic

        # Local to this group and invocation: no image/profile state is retained.
        cost_cache = {tuple(tuple(path) for path in original):
                      (original_intrinsic, original_selection_cost)}
        best = original
        best_intrinsic = original_intrinsic
        best_selection_cost = original_selection_cost
        best_limit = (rows, points)
        best_h = best_v = best_vpaths = 0

        for candidate_rows, candidate_points in limits:
            if cancelled():
                raise InterruptedError()
            candidate, h_runs, v_runs, v_paths = _axis_candidate(
                group, edge_n, candidate_rows, candidate_points, cancelled,
            )
            if len(candidate) > len(original):
                continue
            key = tuple(tuple(path) for path in candidate)
            if key in cost_cache:
                candidate_intrinsic, candidate_selection_cost = cost_cache[key]
                duplicate_candidates_skipped += 1
            else:
                candidate_intrinsic = _intrinsic_cost(candidate, model)
                if travel_aware:
                    candidate_selection_cost, _ = _ordered_group_cost(
                        candidate, options, model, cancelled,
                    )
                else:
                    candidate_selection_cost = candidate_intrinsic
                cost_cache[key] = (candidate_intrinsic, candidate_selection_cost)

            strictly_better = candidate_selection_cost < best_selection_cost - 1e-9
            equal_cost_fewer_paths = (
                len(candidate) < len(best)
                and candidate_selection_cost <= best_selection_cost + 1e-9
            )
            if strictly_better or equal_cost_fewer_paths:
                best = candidate
                best_intrinsic = candidate_intrinsic
                best_selection_cost = candidate_selection_cost
                best_limit = (candidate_rows, candidate_points)
                best_h, best_v, best_vpaths = h_runs, v_runs, v_paths

        alternate = _vertical_alternative(group, edge_n, cancelled)
        if alternate is not None:
            candidate, h_runs, v_runs, v_paths = _axis_candidate(
                alternate, edge_n, rows, points, cancelled)
            if len(candidate) <= len(original):
                candidate_intrinsic = _intrinsic_cost(candidate, model)
                if travel_aware:
                    candidate_selection_cost, _ = _ordered_group_cost(
                        candidate, options, model, cancelled)
                else:
                    candidate_selection_cost = candidate_intrinsic
                if (candidate_selection_cost < best_selection_cost - 1e-9 or
                    (len(candidate) < len(best) and candidate_selection_cost <= best_selection_cost + 1e-9)):
                    best = candidate
                    best_intrinsic = candidate_intrinsic
                    best_selection_cost = candidate_selection_cost
                    best_limit = (rows, points)
                    best_h, best_v, best_vpaths = h_runs, v_runs, v_paths
                    reoriented_groups.add(index)

        proposed.append(best)
        selected_rows.append((best_limit, best_h, best_v, best_vpaths, best is not original))
        intrinsic_before += original_intrinsic
        intrinsic_proposed += best_intrinsic
        local_ordered_before += original_selection_cost
        local_ordered_proposed += best_selection_cost

    baseline_downstream = proposal_downstream = None
    baseline_downstream_meta: dict[str, Any] = {}
    proposal_downstream_meta: dict[str, Any] = {}
    downstream_accepted = True

    unchanged = not any(changed for _limit, _h, _v, _vpaths, changed in selected_rows)
    semantic_proposed = (baseline if unchanged else
                         execution_groups_with_portrait_semantics(proposed, portrait_edge_count))
    if travel_aware:
        baseline_downstream, baseline_downstream_meta = _downstream_plan_cost(
            baseline, options, model, cancelled,
        )
        if cancelled():
            raise InterruptedError()
        if unchanged:
            # Every group retained its original paths and semantic barriers.
            # Capping, reordering and pricing that same plan twice cannot
            # change the final guard; retain its one complete evaluation.
            proposal_downstream = baseline_downstream
            proposal_downstream_meta = baseline_downstream_meta
        else:
            proposal_downstream, proposal_downstream_meta = _downstream_plan_cost(
                semantic_proposed, options, model, cancelled,
            )
        no_more_paths = sum(map(len, proposed)) <= sum(map(len, baseline))
        downstream_accepted = bool(
            no_more_paths and proposal_downstream <= baseline_downstream + 1e-9
        )

    if not downstream_accepted:
        result = baseline
        selected_rows = [((rows, points), 0, 0, 0, False) for _ in baseline]
        intrinsic_after = intrinsic_before
        local_ordered_after = local_ordered_before
    else:
        result = semantic_proposed
        intrinsic_after = intrinsic_proposed
        local_ordered_after = local_ordered_proposed

    vertical_runs = 0
    vertical_paths = 0
    vertical_colors = 0
    horizontal_runs = 0
    horizontal_colors = 0
    adaptive_colors = 0
    selected_limits: dict[tuple[int, int], int] = {}

    for best_limit, best_h, best_v, best_vpaths, changed in selected_rows:
        selected_limits[best_limit] = selected_limits.get(best_limit, 0) + 1
        if changed:
            adaptive_colors += 1
            if best_v:
                vertical_colors += 1
                vertical_runs += best_v
                vertical_paths += best_vpaths
            if best_h and best_limit != (rows, points):
                horizontal_colors += 1
                horizontal_runs += best_h

    dominant_limit = (
        max(selected_limits.items(), key=lambda item: (item[1], item[0]))[0]
        if selected_limits else (rows, points)
    )

    ordered_before = baseline_downstream if baseline_downstream is not None else local_ordered_before
    if downstream_accepted:
        ordered_after = proposal_downstream if proposal_downstream is not None else local_ordered_proposed
    else:
        ordered_after = ordered_before

    return result, dict(
        path_policy=policy,
        duplicate_candidate_evaluations_skipped=duplicate_candidates_skipped,
        lossless_axis_reoriented_colors=len(reoriented_groups) if downstream_accepted else 0,
        vertical_runs_joined=vertical_runs,
        vertical_paths=vertical_paths,
        vertical_colors_improved=vertical_colors,
        horizontal_runs_rebatched=horizontal_runs,
        horizontal_colors_improved=horizontal_colors,
        adaptive_colors_improved=adaptive_colors,
        intrinsic_cost_before_seconds=round(intrinsic_before, 6),
        intrinsic_cost_after_seconds=round(intrinsic_after, 6),
        intrinsic_cost_saved_seconds=round(intrinsic_before-intrinsic_after, 6),
        ordered_cost_before_seconds=round(float(ordered_before), 6),
        ordered_cost_after_seconds=round(float(ordered_after), 6),
        ordered_cost_saved_seconds=round(max(0.0, float(ordered_before)-float(ordered_after)), 6),
        travel_aware_selection_enabled=travel_aware,
        downstream_plan_accepted=bool(downstream_accepted),
        downstream_target_cap_applied=bool(
            baseline_downstream_meta.get('target_cap_applied')
            or proposal_downstream_meta.get('target_cap_applied')
        ),
        downstream_semantic_hints_preserved=bool(
            baseline_downstream_meta.get('semantic_hints_preserved')
            or proposal_downstream_meta.get('semantic_hints_preserved')
        ),
        downstream_protected_prefix_before=max(
            int(baseline_downstream_meta.get('protected_prefix_before',0) or 0),
            int(proposal_downstream_meta.get('protected_prefix_before',0) or 0),
        ),
        downstream_protected_prefix_after=max(
            int(baseline_downstream_meta.get('protected_prefix_after',0) or 0),
            int(proposal_downstream_meta.get('protected_prefix_after',0) or 0),
        ),
        downstream_optimizer_effective=(
            proposal_downstream_meta.get('stroke_optimizer_effective')
            or baseline_downstream_meta.get('stroke_optimizer_effective')
            or 'Off'
        ),
        candidate_path_limits=[list(item) for item in limits],
        dominant_selected_path_limit=list(dominant_limit),
        selected_path_limit_histogram={
            f'{r}x{p}': count for (r, p), count in sorted(selected_limits.items())
        },
        execution_cost_model=f'ExecutionCostModel stateful v{EXECUTION_MODEL_VERSION}',
        execution_scale=[round(float(getattr(model,'scale_x',1.0)),6),round(float(getattr(model,'scale_y',1.0)),6)],
        cost_scope=(
            'post-target-cap + current StrokeOptimizer through ExecutionCostModel; intra-color travel + color selection; '
            'constant fill/tool/verification terms cancel between path candidates'
            if travel_aware else
            'legacy intrinsic path cost; travel-aware selection disabled'
        ),
        safety_rule=(
            'same source runs; overlap-only axis connectors; no added path count; '
            'complete baseline fallback on downstream cost regression'
        ),
    )
