"""Deterministic fast-path optimizer for the Gartic Phone profile.

Inspired by classic Gartic Phone and Skribbl autodraw strategies: quantize to the
calibrated game palette, draw one colour at a time, collapse same-colour pixels
into long runs, and choose horizontal or vertical run orientation per colour.
This module is pure planning code: no mouse, network, browser or GUI access.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from ContinuousPaths import build_execution_paths
from GarticEngineV2 import stroke_graph_order
from ColorFidelity import palette_match_cost, color_metrics, validate_color_fidelity
from AdaptivePaletteFidelity import select_adaptive_palette, _map_indices, palette_quality_metrics

Segment = tuple[int, int, int, int]
Path = tuple[tuple[int, int], ...]


def _distance2(a, b) -> int:
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3))


def _run_weight(seg: Segment) -> int:
    x1, y1, x2, y2 = map(int, seg)
    return max(1, abs(x2 - x1) + abs(y2 - y1) + 1)


def _is_white(rgb) -> bool:
    try:
        return min(map(int, rgb[:3])) >= 245
    except Exception:
        return False


def _coalesce_rows(strokes: Sequence[Segment], *, gap_join: int = 1,
                   min_run: int = 2, keep_short: bool = False) -> list[Segment]:
    rows: dict[int, list[tuple[int, int]]] = defaultdict(list)
    passthrough: list[Segment] = []
    for stroke in strokes:
        x1, y1, x2, y2 = map(int, stroke)
        if y1 != y2:
            passthrough.append((x1, y1, x2, y2))
            continue
        if x2 < x1:
            x1, x2 = x2, x1
        rows[y1].append((x1, x2))

    out: list[Segment] = []
    for y in sorted(rows):
        runs = sorted(rows[y])
        if not runs:
            continue
        sx, ex = runs[0]
        for nx1, nx2 in runs[1:]:
            if nx1 <= ex + max(0, int(gap_join)) + 1:
                ex = max(ex, nx2)
            else:
                if keep_short or ex - sx + 1 >= max(1, int(min_run)):
                    out.append((sx, y, ex, y))
                sx, ex = nx1, nx2
        if keep_short or ex - sx + 1 >= max(1, int(min_run)):
            out.append((sx, y, ex, y))
    out.extend(passthrough)
    return out


def _vertical_runs_from_rows(strokes: Sequence[Segment], *, gap_join: int = 0,
                             min_run: int = 2, keep_short: bool = False,
                             pixel_limit: int = 250_000) -> list[Segment] | None:
    """Build vertical runs from horizontal raster coverage.

    Returns ``None`` when the source would require expanding an unexpectedly
    large pixel set.  That keeps the optimization bounded and lets the caller
    safely fall back to horizontal runs.
    """
    columns: dict[int, list[int]] = defaultdict(list)
    pixels = 0
    passthrough: list[Segment] = []
    for stroke in strokes:
        x1, y1, x2, y2 = map(int, stroke)
        if y1 != y2:
            passthrough.append((x1, y1, x2, y2))
            continue
        if x2 < x1:
            x1, x2 = x2, x1
        pixels += x2 - x1 + 1
        if pixels > max(1, int(pixel_limit)):
            return None
        for x in range(x1, x2 + 1):
            columns[x].append(y1)

    out: list[Segment] = []
    join = max(0, int(gap_join))
    for x in sorted(columns):
        ys = sorted(set(columns[x]))
        if not ys:
            continue
        sy = ey = ys[0]
        for y in ys[1:]:
            if y <= ey + join + 1:
                ey = y
            else:
                if keep_short or ey - sy + 1 >= max(1, int(min_run)):
                    out.append((x, sy, x, ey))
                sy = ey = y
        if keep_short or ey - sy + 1 >= max(1, int(min_run)):
            out.append((x, sy, x, ey))
    out.extend(passthrough)
    return out


def _orientation_cost(strokes: Sequence[Segment]) -> tuple[int, int]:
    """Prefer fewer press/release boundaries, then less total pen distance."""
    return (len(strokes), sum(_run_weight(s) for s in strokes))


def optimize_gartic_phone_groups(groups: Sequence[Sequence[Segment]],
                                 palette_rgb: Sequence[Sequence[int]], *,
                                 max_colors: int = 8, gap_join: int = 1,
                                 min_run: int = 2,
                                 vertical_pixel_limit: int = 250_000,
                                 color_fidelity: str = "Balanced"
                                 ) -> tuple[list[list[Segment]], dict]:
    """Reduce colour switches and choose the cheapest raster orientation.

    Rare colours are remapped to the nearest retained calibrated swatch.  The
    darkest structural colour is always retained.  Each retained colour then
    chooses horizontal or vertical runs based primarily on how many separate
    mouse-down/up strokes would be required.
    """
    validate_color_fidelity(color_fidelity)
    work = [list(map(tuple, group)) for group in groups]
    palette = [tuple(map(int, rgb[:3])) for rgb in palette_rgb]
    if len(palette) < len(work):
        palette.extend([(0, 0, 0)] * (len(work) - len(palette)))

    weights = [sum(_run_weight(s) for s in group) for group in work]
    active = [i for i, w in enumerate(weights)
              if w and i < len(palette) and not _is_white(palette[i])]
    before_colors = len(active)
    before_runs = sum(len(g) for g in work)
    if not active:
        return work, {
            'active': True,
            'strategy': 'Gartic fixed-palette dual-axis runs',
            'active_colors_before': 0,
            'active_colors_after': 0,
            'runs_before': before_runs,
            'runs_after': before_runs,
            'remapped_colors': 0,
            'orientations': {},
        }

    max_colors = max(2, int(max_colors))
    darkest = min(active, key=lambda i: (color_metrics(tuple(palette[i]))[0], -weights[i], i))
    brightest = max(active, key=lambda i: (color_metrics(tuple(palette[i]))[0], weights[i], -i))

    # v1.0.123 anti-posterization: select the useful subset by tone/hue/spatial
    # coverage and visual gain per colour switch. White is excluded from the
    # drawable candidate set exactly as before.
    selector_groups=[list(g) if i in active else [] for i,g in enumerate(work)]
    keep, mapping, palette_quality = select_adaptive_palette(
        selector_groups, palette, max_colors, fidelity=color_fidelity)
    if not keep:
        keep=[darkest]
        mapping={i:darkest for i in active}
        palette_quality={}
    else:
        # The fast game path may reduce many colours, but the darkest structural
        # swatch is a non-negotiable anchor for silhouettes/text.  Step 4/5
        # adaptive selection can legitimately choose higher-gain hue anchors; keep
        # this legacy invariant here so old Gartic/Skribbl structure tests and
        # user expectations remain stable.
        keep=list(dict.fromkeys([int(darkest), *[int(k) for k in keep if int(k) != int(darkest)]]))
        while len(keep) > max_colors:
            keep.pop()
        # Inserting the structural anchor can evict a previously retained
        # swatch. Rebuild every target so no group points at an omitted colour.
        mapping, errors = _map_indices(active, keep, palette, weights, color_fidelity)
        palette_quality = {**palette_quality, **palette_quality_metrics(
            active, keep, palette, weights, mapping, errors,
            fidelity=color_fidelity, max_colors=max_colors)}
        palette_quality['region_detail_anchors_kept'] = tuple(
            i for i in palette_quality.get('region_detail_anchor_indexes', ()) if i in keep)
    mapped: list[list[Segment]] = [[] for _ in work]
    remapped = 0
    for index in active:
        target = int(mapping.get(index,index))
        if target != index:
            remapped += 1
        mapped[target].extend(work[index])

    result: list[list[Segment]] = [[] for _ in work]
    orientations: dict[str, str] = {}
    horizontal_counts: dict[str, int] = {}
    vertical_counts: dict[str, int] = {}
    vertical_wins = 0
    for index in keep:
        keep_short = index == darkest
        horizontal = _coalesce_rows(mapped[index], gap_join=gap_join,
                                    min_run=min_run, keep_short=keep_short)
        vertical = _vertical_runs_from_rows(mapped[index], gap_join=gap_join,
                                            min_run=min_run, keep_short=keep_short,
                                            pixel_limit=vertical_pixel_limit)
        if vertical is not None and _orientation_cost(vertical) < _orientation_cost(horizontal):
            chosen = vertical
            orientation = 'vertical'
            vertical_wins += 1
        else:
            chosen = horizontal
            orientation = 'horizontal'
        result[index] = chosen
        orientations[str(index)] = orientation
        horizontal_counts[str(index)] = len(horizontal)
        vertical_counts[str(index)] = -1 if vertical is None else len(vertical)

    after_runs = sum(len(g) for g in result)
    after_colors = sum(bool(g) for g in result)
    return result, {
        'active': True,
        'strategy': 'fixed-palette color batches + dual-axis run compression',
        'active_colors_before': before_colors,
        'active_colors_after': after_colors,
        'max_colors': max_colors,
        'remapped_colors': remapped,
        'runs_before': before_runs,
        'runs_after': after_runs,
        'run_reduction': 0.0 if before_runs <= 0 else max(0.0, 1.0 - after_runs / before_runs),
        'gap_join': int(gap_join),
        'min_run': int(min_run),
        'darkest_color_index': int(darkest),
        'brightest_color_index': int(brightest),
        'color_fidelity': color_fidelity,
        'kept_color_indexes': tuple(map(int, keep)),
        'color_mapping': {str(k): int(v) for k, v in mapping.items()},
        'palette_coverage_percent': float(palette_quality.get('palette_coverage_percent',100.0)),
        'average_reduction_delta_e2000': float(palette_quality.get('average_reduction_delta_e2000',0.0)),
        'p95_reduction_delta_e2000': float(palette_quality.get('p95_reduction_delta_e2000',0.0)),
        'posterization_risk': str(palette_quality.get('posterization_risk','LOW')),
        'posterization_score': float(palette_quality.get('posterization_score',0.0)),
        'midtone_loss': bool(palette_quality.get('midtone_loss',False)),
        'visual_gain_per_color_switch': float(palette_quality.get('visual_gain_per_color_switch',0.0)),
        'anti_posterization': True,
        'region_aware_quantization': bool(palette_quality.get('region_aware_quantization',False)),
        'region_detail_anchor_indexes': tuple(palette_quality.get('region_detail_anchor_indexes',())),
        'region_detail_anchors_kept': tuple(palette_quality.get('region_detail_anchors_kept',())),
        'orientations': orientations,
        'horizontal_run_counts': horizontal_counts,
        'vertical_run_counts': vertical_counts,
        'vertical_wins': vertical_wins,
    }


def _transpose_segment(seg: Segment) -> Segment:
    x1, y1, x2, y2 = map(int, seg)
    return (y1, x1, y2, x2)


def _transpose_path(path: Sequence[tuple[int, int]]) -> Path:
    return tuple((int(y), int(x)) for x, y in path)


def build_gartic_execution_paths(groups: Sequence[Sequence[Segment]], orientations: dict[str, str], *,
                                 cancelled=lambda: False, stroke_graph: bool = True) -> list[list[Path]]:
    """Build continuous paths for either horizontal or vertical run groups.

    v1.0.66 adds a bounded StrokeGraph pass inside each colour batch. It may
    reorder and reverse existing paths, but it never adds a connector stroke.
    """
    out: list[list[Path]] = []
    for index, group in enumerate(groups):
        if cancelled():
            raise InterruptedError()
        orientation = str((orientations or {}).get(str(index), 'horizontal'))
        if orientation == 'vertical':
            transposed = [_transpose_segment(seg) for seg in group]
            paths = build_execution_paths([transposed], enabled=True, cancelled=cancelled)[0]
            paths = [_transpose_path(path) for path in paths]
        else:
            paths = build_execution_paths([group], enabled=True, cancelled=cancelled)[0]
        if stroke_graph:
            paths, _meta = stroke_graph_order(paths, allow_reverse=True, window=192, cancelled=cancelled)
        out.append(paths)
    return out
