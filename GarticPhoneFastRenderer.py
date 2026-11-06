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
                   min_run: int = 2, keep_short: bool = False, return_coverage=False):
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
    retained_pixels = 0
    for y in sorted(rows):
        runs = sorted(rows[y])
        if not runs:
            continue
        sx, ex = runs[0]
        source_pixels = ex - sx + 1
        for nx1, nx2 in runs[1:]:
            if nx1 <= ex + max(0, int(gap_join)) + 1:
                source_pixels += max(0, nx2 - max(ex, nx1 - 1))
                ex = max(ex, nx2)
            else:
                if keep_short or ex - sx + 1 >= max(1, int(min_run)):
                    out.append((sx, y, ex, y))
                    retained_pixels += source_pixels
                sx, ex = nx1, nx2
                source_pixels = ex - sx + 1
        if keep_short or ex - sx + 1 >= max(1, int(min_run)):
            out.append((sx, y, ex, y))
            retained_pixels += source_pixels
    out.extend(passthrough)
    return (out, retained_pixels) if return_coverage else out


def _vertical_runs_from_rows(strokes: Sequence[Segment], *, gap_join: int = 0,
                             min_run: int = 2, keep_short: bool = False,
                             pixel_limit: int = 250_000, return_coverage=False):
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
            return (None, 0) if return_coverage else None
        for x in range(x1, x2 + 1):
            columns[x].append(y1)

    out: list[Segment] = []
    retained_pixels = 0
    join = max(0, int(gap_join))
    for x in sorted(columns):
        ys = sorted(set(columns[x]))
        if not ys:
            continue
        sy = ey = ys[0]
        source_pixels = 1
        for y in ys[1:]:
            if y <= ey + join + 1:
                ey = y
                source_pixels += 1
            else:
                if keep_short or ey - sy + 1 >= max(1, int(min_run)):
                    out.append((x, sy, x, ey))
                    retained_pixels += source_pixels
                sy = ey = y
                source_pixels = 1
        if keep_short or ey - sy + 1 >= max(1, int(min_run)):
            out.append((x, sy, x, ey))
            retained_pixels += source_pixels
    out.extend(passthrough)
    return (out, retained_pixels) if return_coverage else out


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
    """Reduce colour switches and retain coverage when choosing an orientation.

    Rare colours are remapped to the nearest retained calibrated swatch.  The
    darkest structural colour is always retained.  Each retained colour then
    chooses the orientation retaining the most original pixels, then the one
    requiring fewer mouse-down/up strokes and less pen distance.
    """
    validate_color_fidelity(color_fidelity)
    work = [list(map(tuple, group)) for group in groups]
    palette = [tuple(map(int, rgb[:3])) for rgb in palette_rgb]
    if len(palette) < len(work):
        palette.extend([(0, 0, 0)] * (len(work) - len(palette)))

    weights = [sum(_run_weight(s) for s in group) for group in work]
    # The caller has already applied skip_white. Any supplied white geometry
    # is deliberate ink (including repairs over a coloured background).
    active = [i for i, w in enumerate(weights) if w and i < len(palette)]
    white = [i for i in active if _is_white(palette[i])]
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
    white_anchor = max(white, key=lambda i: (color_metrics(tuple(palette[i]))[0], weights[i], -i)) if white else None

    # v1.0.123 anti-posterization: select the useful subset by tone/hue/spatial
    # coverage and visual gain per colour switch, retaining requested white
    # alongside the structural dark anchor within the same colour ceiling.
    selector_groups=[list(g) if i in active else [] for i,g in enumerate(work)]
    keep, mapping, palette_quality = select_adaptive_palette(
        selector_groups, palette, max_colors, fidelity=color_fidelity)
    if not keep:
        keep=[darkest]
        palette_quality={}
    anchors = [darkest] + ([white_anchor] if white_anchor is not None else [])
    keep = list(dict.fromkeys([*anchors, *map(int, keep)]))[:max_colors]
    # Rebuild after inserting anchors. White variants may reduce only to a
    # retained white swatch, never disappear or become dark paint.
    mapping, errors = _map_indices([i for i in active if i not in white], keep,
                                   palette, weights, color_fidelity)
    if white:
        white_mapping, white_errors = _map_indices(white, [i for i in keep if i in white],
                                                  palette, weights, color_fidelity)
        mapping.update(white_mapping)
        errors.extend(white_errors)
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
    horizontal_coverage: dict[str, int] = {}
    vertical_coverage: dict[str, int] = {}
    vertical_wins = 0
    for index in keep:
        keep_short = index == darkest or index in white
        join = 0 if index in white else gap_join
        horizontal, h_pixels = _coalesce_rows(mapped[index], gap_join=join,
                                    min_run=min_run, keep_short=keep_short, return_coverage=True)
        vertical, v_pixels = _vertical_runs_from_rows(mapped[index], gap_join=join,
                                            min_run=min_run, keep_short=keep_short,
                                            pixel_limit=vertical_pixel_limit, return_coverage=True)
        # Min-run pruning differs by orientation. Dropping the long coloured
        # line into many rejected dots must not make an empty candidate win on
        # cost. Count retained source pixels (not newly bridged gap pixels),
        # then choose the cheaper equally complete orientation. Passthrough
        # geometry is identical in both candidates and needs no extra scan.
        if vertical is not None and (-v_pixels, _orientation_cost(vertical)) < (-h_pixels, _orientation_cost(horizontal)):
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
        horizontal_coverage[str(index)] = h_pixels
        vertical_coverage[str(index)] = -1 if vertical is None else v_pixels

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
        'white_color_index': white_anchor,
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
        'horizontal_retained_pixels': horizontal_coverage,
        'vertical_retained_pixels': vertical_coverage,
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
