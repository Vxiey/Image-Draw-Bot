"""Deterministic fast-path optimizer for the Skribbl.io Fast profile.

Inspired by classic Skribbl autodraw strategies: quantize to the calibrated game
palette, draw one colour at a time, and collapse adjacent raster pixels into long
horizontal runs.  This module is pure planning code: no mouse, network or GUI.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Sequence
from ColorFidelity import color_metrics, palette_match_cost, validate_color_fidelity
from AdaptivePaletteFidelity import select_adaptive_palette, _map_indices, palette_quality_metrics

Segment = tuple[int, int, int, int]


def _run_weight(seg: Segment) -> int:
    x1, y1, x2, y2 = map(int, seg)
    return max(1, abs(x2 - x1) + abs(y2 - y1) + 1)


def _distance2(a, b) -> int:
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3))


def _is_white(rgb) -> bool:
    try:
        return min(map(int, rgb[:3])) >= 245
    except Exception:
        return False


def _coalesce_rows(strokes: Sequence[Segment], *, gap_join: int = 1, min_run: int = 2,
                   keep_short: bool = False) -> list[Segment]:
    """Merge same-colour horizontal runs on each row and prune tiny fragments.

    ``gap_join`` may bridge a one-source-pixel gap after palette reduction.  This
    turns nearby fragments that now represent the same reduced colour into one
    mouse stroke instead of several press/release actions.
    """
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
                length = ex - sx + 1
                if keep_short or length >= max(1, int(min_run)):
                    out.append((sx, y, ex, y))
                sx, ex = nx1, nx2
        length = ex - sx + 1
        if keep_short or length >= max(1, int(min_run)):
            out.append((sx, y, ex, y))
    out.extend(passthrough)
    return out


def optimize_skribbl_groups(groups: Sequence[Sequence[Segment]], palette_rgb: Sequence[Sequence[int]], *,
                            max_colors: int = 6, gap_join: int = 1, min_run: int = 2,
                            color_fidelity: str = "Balanced") -> tuple[list[list[Segment]], dict]:
    """Aggressively reduce palette switches and stroke boundaries for Skribbl.

    The most-used calibrated colours are kept. Less-used colours are remapped to
    the nearest kept calibrated colour, preserving geometry while reducing colour
    changes.  Dark structure is explicitly retained when present.
    """
    validate_color_fidelity(color_fidelity)
    work = [list(map(tuple, group)) for group in groups]
    color_count = len(work)
    palette = [tuple(map(int, rgb[:3])) for rgb in palette_rgb]
    if len(palette) < color_count:
        palette.extend([(0, 0, 0)] * (color_count - len(palette)))

    weights = [sum(_run_weight(s) for s in group) for group in work]
    # skip_white belongs to source mapping. Supplied white groups are explicit
    # paint and must survive palette reduction just like the dark structure.
    active = [i for i, w in enumerate(weights) if w and i < len(palette)]
    white = [i for i in active if _is_white(palette[i])]
    before_colors = len(active)
    before_runs = sum(len(g) for g in work)
    if not active:
        return work, {
            'active_colors_before': 0, 'active_colors_after': 0,
            'runs_before': before_runs, 'runs_after': before_runs,
            'remapped_colors': 0, 'max_colors': int(max_colors),
        }

    max_colors = max(2, int(max_colors))
    darkest = min(active, key=lambda i: (color_metrics(tuple(palette[i]))[0], -weights[i], i))
    brightest = max(active, key=lambda i: (color_metrics(tuple(palette[i]))[0], weights[i], -i))
    white_anchor = max(white, key=lambda i: (color_metrics(tuple(palette[i]))[0], weights[i], -i)) if white else None
    anchors = [darkest] + ([white_anchor] if white_anchor is not None else [])
    selector_groups=[list(g) if i in active else [] for i,g in enumerate(work)]
    keep,mapping,palette_quality=select_adaptive_palette(selector_groups,palette,max_colors,fidelity=color_fidelity)
    if not keep:
        keep=[darkest];mapping={i:darkest for i in active};palette_quality={}
    if any(anchor not in keep for anchor in anchors):
        # Structural dark ink is a semantic geometry anchor for this fast path.
        # Preserve it even when its pixel weight is tiny, while keeping the same
        # max-colour budget. Drop the weakest non-dark retained swatch if needed.
        keep=list(map(int,keep))
        forced_dark = darkest not in keep
        for anchor in anchors:
            if anchor in keep:
                continue
            if len(keep) >= max_colors:
                removable=[i for i in keep if i not in anchors]
                if removable:
                    drop=min(removable,key=lambda i:(weights[i],i))
                    keep.remove(drop)
            keep.append(int(anchor))
        keep=list(dict.fromkeys(keep))
        palette_quality['forced_dark_structure']=forced_dark
    if white or palette_quality.get('forced_dark_structure'):
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

    result: list[list[Segment]] = [[] for _ in work]
    remapped = 0
    for index in active:
        target=int(mapping.get(index,index))
        if target!=index:remapped+=1
        result[target].extend(work[index])

    for index in keep:
        # Dark outlines/details may contain short but important fragments.
        keep_short = index == darkest or index in white
        result[index] = _coalesce_rows(result[index], gap_join=0 if index in white else gap_join,
                                      min_run=min_run, keep_short=keep_short)

    after_runs = sum(len(g) for g in result)
    after_colors = sum(bool(g) for g in result)
    return result, {
        'active': True,
        'strategy': 'fixed-palette color batches + horizontal run compression',
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
        'midtone_loss': bool(palette_quality.get('midtone_loss',False)),
        'anti_posterization': True,
        'region_aware_quantization': bool(palette_quality.get('region_aware_quantization',False)),
        'region_detail_anchor_indexes': tuple(palette_quality.get('region_detail_anchor_indexes',())),
        'region_detail_anchors_kept': tuple(palette_quality.get('region_detail_anchors_kept',())),
        'dark_structure_forced': bool(palette_quality.get('forced_dark_structure',False)),
    }
