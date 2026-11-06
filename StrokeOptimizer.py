"""Geometry-safe path optimizer for Image Draw Bot.

The optimizer only changes execution order/direction and may merge paths whose
endpoints are exactly identical. It never invents a connector across unpainted
space, so the visible geometry is preserved.

``Smart merge + 2-opt`` extends the established nearest-neighbour route with a
small bounded 2-opt pass. The pass reverses both the route slice and each path
inside it, preserving every drawn segment while changing only pen-up order.
"""
from __future__ import annotations

import math
from itertools import islice
from typing import Sequence

Point = tuple[int, int]
Path = tuple[Point, ...]

STROKE_OPTIMIZER_MODES = ('Auto', 'Off', 'Travel only', 'Smart merge', 'Smart merge + 2-opt')


def validate_stroke_optimizer(mode: str) -> str:
    if mode not in STROKE_OPTIMIZER_MODES:
        raise ValueError('Choose a valid stroke optimizer mode.')
    return mode


def resolve_stroke_optimizer(mode: str, *, drawing_mode: str | None = None) -> str:
    validate_stroke_optimizer(mode)
    if mode != 'Auto':
        return mode
    if drawing_mode in ('Smart paths (recommended)', 'Shape paths'):
        return 'Smart merge'
    return 'Travel only'


def _distance(a: Point, b: Point) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _reverse(path: Path) -> Path:
    return tuple(reversed(path))


def pen_up_distance(paths: Sequence[Path]) -> float:
    total = 0.0
    previous = None
    for path in paths:
        if not path:
            continue
        if previous is not None:
            total += _distance(previous, path[0])
        previous = path[-1]
    return total


def _clean_path(path) -> Path:
    cleaned = []
    for point in path:
        p = (int(point[0]), int(point[1]))
        if not cleaned or cleaned[-1] != p:
            cleaned.append(p)
    return tuple(cleaned)


def _nearest_order(paths: Sequence[Path], *, speed: str = 'Balanced', allow_reverse: bool = True,
                   cancelled=lambda: False) -> list[Path]:
    """Adaptive bounded nearest-neighbour ordering."""
    from SpeedOptimizer import normalize_speed
    speed = normalize_speed(speed or 'Balanced')
    remaining = [_clean_path(p) for p in paths if p]
    original = remaining
    if len(remaining) < 3:
        return remaining
    if speed == 'Safe':
        window = 28
    elif speed == 'Fast':
        window = 160
    else:
        window = 96
    if len(remaining) > 12000:
        window = min(window, 72)
    elif len(remaining) < 500:
        window = min(len(remaining), max(window, 128))

    output: list[Path] = []
    source = iter(remaining)
    first = next(source)
    output.append(first)
    cursor = first[-1]
    # Only the bounded search window needs arbitrary-index removal. Keeping
    # every future path in that list makes an already ordered route quadratic
    # because each pop(0) shifts the entire remaining job.
    remaining = list(islice(source, window))

    while remaining:
        if cancelled():
            raise InterruptedError()
        limit = min(window, len(remaining))
        best_i = 0
        best_reverse = False
        best_cost = float('inf')
        for i in range(limit):
            path = remaining[i]
            d0 = _distance(cursor, path[0])
            d1 = _distance(cursor, path[-1]) if allow_reverse and len(path) > 1 else float('inf')
            reverse = d1 < d0
            cost = d1 if reverse else d0
            cost += i * 1e-5
            if cost < best_cost:
                best_i, best_reverse, best_cost = i, reverse, cost
                if best_cost <= 1e-9:
                    break
        chosen = remaining.pop(best_i)
        if best_reverse:
            chosen = _reverse(chosen)
        output.append(chosen)
        cursor = chosen[-1]
        following = next(source, None)
        if following is not None:
            remaining.append(following)
    # A local greedy choice can make the eventual pen-up route longer. Ordering
    # changes no drawing work, so keep it only when the complete route improves.
    return output if pen_up_distance(output) <= pen_up_distance(original) + 1e-9 else original


def _two_opt_budget(speed: str, path_count: int) -> tuple[int, int]:
    """Return a bounded pass count and local search window.

    The search is intentionally small: it is a planner refinement, not a global
    TSP solver. Very large jobs reduce their budget to protect preview/draw-start
    latency.
    """
    from SpeedOptimizer import normalize_speed
    speed = normalize_speed(speed or 'Balanced')
    if path_count < 4:
        return 0, 0
    if speed == 'Safe':
        passes, window = 8, 12
    elif speed == 'Fast':
        passes, window = 24, 36
    else:
        passes, window = 16, 24
    if path_count > 12000:
        passes, window = min(passes, 6), min(window, 12)
    elif path_count > 4000:
        passes, window = min(passes, 10), min(window, 18)
    elif path_count > 1200:
        passes, window = min(passes, 12), min(window, 24)
    return passes, window


def _bounded_two_opt(paths: Sequence[Path], *, speed: str = 'Balanced',
                     allow_reverse: bool = True, cancelled=lambda: False) -> tuple[list[Path], dict]:
    """Apply bounded 2-opt without changing drawn geometry.

    A 2-opt move reverses a contiguous route slice and reverses every path inside
    that slice. Internal pen-up distances are therefore unchanged; only the two
    route boundary edges change. The move is accepted only for a strict travel
    reduction. If path direction may not be reversed, the pass is disabled.
    """
    route = [_clean_path(path) for path in paths if path]
    before = pen_up_distance(route)
    max_passes, window = _two_opt_budget(speed, len(route))
    if not allow_reverse or max_passes <= 0:
        return route, {
            'optimizer_two_opt_iterations': 0,
            'optimizer_two_opt_improvements': 0,
            'optimizer_two_opt_evaluations': 0,
            'optimizer_two_opt_before': before,
            'optimizer_two_opt_after': before,
        }

    improvements = 0
    evaluations = 0
    iterations = 0
    n = len(route)

    for _ in range(max_passes):
        if cancelled():
            raise InterruptedError()
        iterations += 1
        best_gain = 1e-9
        best_pair = None

        for i in range(0, n - 1):
            if cancelled():
                raise InterruptedError()
            previous = route[i - 1][-1] if i > 0 else None
            old_first = route[i][0]
            max_j = min(n - 1, i + window)
            for j in range(i + 1, max_j + 1):
                following = route[j + 1][0] if j + 1 < n else None
                old_cost = 0.0
                new_cost = 0.0
                if previous is not None:
                    old_cost += _distance(previous, old_first)
                    new_cost += _distance(previous, route[j][-1])
                if following is not None:
                    old_cost += _distance(route[j][-1], following)
                    new_cost += _distance(route[i][0], following)
                evaluations += 1
                gain = old_cost - new_cost
                if gain > best_gain:
                    best_gain = gain
                    best_pair = (i, j)

        if best_pair is None:
            break
        i, j = best_pair
        route[i:j + 1] = [_reverse(path) for path in reversed(route[i:j + 1])]
        improvements += 1

    after = pen_up_distance(route)
    # Defensive guard: floating-point/local-delta mistakes must never make the
    # real route worse. Revert to the supplied route if the full metric regresses.
    if after > before + 1e-9:
        route = [_clean_path(path) for path in paths if path]
        after = before
        improvements = 0

    return route, {
        'optimizer_two_opt_iterations': iterations,
        'optimizer_two_opt_improvements': improvements,
        'optimizer_two_opt_evaluations': evaluations,
        'optimizer_two_opt_before': before,
        'optimizer_two_opt_after': after,
    }


def _merge_exact_neighbors(paths: Sequence[Path], *, allow_reverse: bool = True) -> tuple[list[Path], int]:
    """Merge adjacent paths only when their endpoints are identical."""
    merged: list[Path] = []
    joins = 0
    for path in paths:
        path = _clean_path(path)
        if not path:
            continue
        if not merged:
            merged.append(path)
            continue
        previous = merged[-1]
        if previous[-1] == path[0]:
            merged[-1] = previous + path[1:]
            joins += 1
        elif allow_reverse and len(path) > 1 and previous[-1] == path[-1]:
            rev = _reverse(path)
            merged[-1] = previous + rev[1:]
            joins += 1
        else:
            merged.append(path)
    return merged, joins


def _merge_exact_graph(paths: Sequence[Path], cancelled=lambda: False, *,
                       allow_reverse: bool = True) -> tuple[list[Path], int]:
    """Build safe chains from paths that share exact endpoints anywhere in a group."""
    paths = [_clean_path(p) for p in paths if p]
    endpoint_map: dict[Point, list[int]] = {}
    for i, path in enumerate(paths):
        if i % 512 == 0 and cancelled():
            raise InterruptedError()
        endpoint_map.setdefault(path[0], []).append(i)
        if allow_reverse and path[-1] != path[0]:
            endpoint_map.setdefault(path[-1], []).append(i)
    used: set[int] = set()
    chains: list[Path] = []
    joins = 0
    endpoint_positions: dict[Point, int] = {}

    for seed in range(len(paths)):
        if seed in used:
            continue
        if cancelled():
            raise InterruptedError()
        used.add(seed)
        chain = list(paths[seed])
        while True:
            if cancelled():
                raise InterruptedError()
            endpoint = chain[-1]
            candidates = endpoint_map.get(endpoint, ())
            position = endpoint_positions.get(endpoint, 0)
            while position < len(candidates) and candidates[position] in used:
                position += 1
            endpoint_positions[endpoint] = position + 1
            if position >= len(candidates):
                break
            candidate = candidates[position]
            path = paths[candidate]
            if path[0] == endpoint:
                oriented = path
            elif allow_reverse and path[-1] == endpoint:
                oriented = _reverse(path)
            else:
                break
            used.add(candidate)
            chain.extend(oriented[1:])
            joins += 1
        chains.append(tuple(chain))
    return chains, joins


def optimize_path_group(paths: Sequence[Path], *, mode: str = 'Auto', drawing_mode: str | None = None,
                        speed: str = 'Balanced', allow_reverse: bool = True,
                        cancelled=lambda: False) -> tuple[list[Path], dict]:
    requested = mode
    effective = resolve_stroke_optimizer(mode, drawing_mode=drawing_mode)
    original = [_clean_path(p) for p in paths if p]
    before_distance = pen_up_distance(original)
    two_opt_meta = {
        'optimizer_two_opt_iterations': 0,
        'optimizer_two_opt_improvements': 0,
        'optimizer_two_opt_evaluations': 0,
        'optimizer_two_opt_before': before_distance,
        'optimizer_two_opt_after': before_distance,
    }

    if effective == 'Off' or len(original) < 2:
        result = original
        joins = 0
    else:
        joins = 0
        working = original
        smart_merge = effective in ('Smart merge', 'Smart merge + 2-opt')
        if smart_merge:
            working, joins = _merge_exact_graph(working, cancelled=cancelled, allow_reverse=allow_reverse)
        result = _nearest_order(
            working, speed=speed, allow_reverse=allow_reverse, cancelled=cancelled,
        )
        if smart_merge:
            result, joins2 = _merge_exact_neighbors(result, allow_reverse=allow_reverse)
            joins += joins2
        if effective == 'Smart merge + 2-opt':
            result, two_opt_meta = _bounded_two_opt(
                result, speed=speed, allow_reverse=allow_reverse, cancelled=cancelled,
            )
            # A route improvement can make exact endpoints adjacent. Merge only
            # those zero-gap boundaries; no connector is invented.
            result, joins2 = _merge_exact_neighbors(result, allow_reverse=allow_reverse)
            joins += joins2

    after_distance = pen_up_distance(result)
    return result, {
        'stroke_optimizer_requested': requested,
        'stroke_optimizer_effective': effective,
        'optimizer_before_paths': len(original),
        'optimizer_after_paths': len(result),
        'optimizer_merged_paths': max(0, len(original) - len(result)),
        'optimizer_exact_joins': joins,
        'optimizer_pen_up_before': before_distance,
        'optimizer_pen_up_after': after_distance,
        'optimizer_travel_reduction': 0.0 if before_distance <= 0 else max(0.0, min(1.0, 1.0-after_distance/before_distance)),
        **two_opt_meta,
    }


def optimize_execution_groups(groups: Sequence[Sequence[Path]], *, mode: str = 'Auto', drawing_mode: str | None = None,
                              speed: str = 'Balanced', phase_hints=None, cancelled=lambda: False):
    """Optimize every color group, preserving progressive phase boundaries."""
    optimized = []
    rebuilt_hints = [] if phase_hints is not None else None
    totals = {
        'optimizer_before_paths': 0,
        'optimizer_after_paths': 0,
        'optimizer_merged_paths': 0,
        'optimizer_exact_joins': 0,
        'optimizer_pen_up_before': 0.0,
        'optimizer_pen_up_after': 0.0,
        'optimizer_two_opt_iterations': 0,
        'optimizer_two_opt_improvements': 0,
        'optimizer_two_opt_evaluations': 0,
        'optimizer_two_opt_before': 0.0,
        'optimizer_two_opt_after': 0.0,
    }
    requested = mode
    effective = resolve_stroke_optimizer(mode, drawing_mode=drawing_mode)

    for gi, group in enumerate(groups):
        if cancelled():
            raise InterruptedError()
        group = list(group)
        hints = None
        if phase_hints is not None and gi < len(phase_hints) and len(phase_hints[gi]) == len(group):
            hints = list(phase_hints[gi])
        if hints:
            out = []
            out_hints = []
            # Keep phase order stable. 2-opt is therefore unable to cross any
            # explicit foundation/detail/tool/semantic boundary supplied here.
            start = 0
            while start < len(group):
                phase = hints[start]
                end = start + 1
                while end < len(group) and hints[end] == phase:
                    end += 1
                part, meta = optimize_path_group(
                    group[start:end], mode=mode, drawing_mode=drawing_mode,
                    speed=speed, cancelled=cancelled,
                )
                out.extend(part)
                out_hints.extend([phase] * len(part))
                for key in totals:
                    totals[key] += meta[key]
                start = end
            optimized.append(out)
            rebuilt_hints.append(out_hints)
        else:
            out, meta = optimize_path_group(
                group, mode=mode, drawing_mode=drawing_mode,
                speed=speed, cancelled=cancelled,
            )
            optimized.append(out)
            if rebuilt_hints is not None:
                rebuilt_hints.append([])
            for key in totals:
                totals[key] += meta[key]

    before = totals['optimizer_pen_up_before']
    after = totals['optimizer_pen_up_after']
    totals.update({
        'stroke_optimizer_requested': requested,
        'stroke_optimizer_effective': effective,
        'optimizer_travel_reduction': 0.0 if before <= 0 else max(0.0, min(1.0, 1.0-after/before)),
    })
    return optimized, rebuilt_hints, totals
