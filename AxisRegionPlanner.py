"""Lossless axis analysis shared by Extra Fast and browser sketch planning.

The helpers in this module never invent pixels: they only decompose horizontal
raster runs into connected regions and optionally re-rasterize those exact pixels
as vertical runs. Callers remain responsible for deciding whether a candidate is
actually faster for the current target/profile.
"""
from __future__ import annotations

from typing import Sequence
import numpy as np

Segment = tuple[int, int, int, int]


def _norm_horizontal(stroke: Sequence[int]) -> Segment:
    x0, y0, x1, y1 = map(int, stroke)
    if y0 != y1:
        raise ValueError("axis-region analysis requires horizontal source runs")
    if x1 < x0:
        x0, x1 = x1, x0
    return x0, y0, x1, y0


def _bbox(runs: Sequence[Segment]) -> tuple[int, int, int, int]:
    return (
        min(r[0] for r in runs), min(r[1] for r in runs),
        max(r[2] for r in runs), max(r[1] for r in runs),
    )


def horizontal_components(strokes: Sequence[Sequence[int]], *, adjacency: int = 0,
                          cancelled=lambda: False) -> list[dict]:
    """Split horizontal runs into connected components without changing pixels.

    ``adjacency=0`` means rows must overlap at an x coordinate, which is the safe
    connector rule used by Extra Fast. ``adjacency=1`` also groups diagonal
    neighbours and is useful for classifying sketch components; it does *not*
    permit any diagonal gap bridge in the produced execution paths.
    """
    runs = [_norm_horizontal(s) for s in strokes]
    count = len(runs)
    if not count:
        return []
    adjacency = max(0, int(adjacency))
    parent = list(range(count))
    rank = [0] * count

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    rows: dict[int, list[tuple[int, int, int]]] = {}
    for i, (x0, y, x1, _) in enumerate(runs):
        if i % 512 == 0 and cancelled():
            raise InterruptedError()
        rows.setdefault(y, []).append((x0, x1, i))
    for items in rows.values():
        items.sort(key=lambda item: (item[0], item[1], item[2]))

    # Same-row overlaps are unusual for planner output, but treating them as one
    # region makes the helper robust to pre-merged/custom run sources.
    for _y, items in rows.items():
        if cancelled():
            raise InterruptedError()
        left = items[0]
        for right in items[1:]:
            if right[0] <= left[1] + 1:
                union(left[2], right[2])
                if right[1] > left[1]:
                    left = right
            else:
                left = right

    for y in sorted(rows):
        if cancelled():
            raise InterruptedError()
        previous = rows.get(y - 1)
        current = rows[y]
        if not previous:
            continue
        i = j = 0
        while i < len(previous) and j < len(current):
            a0, a1, ai = previous[i]
            b0, b1, bi = current[j]
            if a1 + adjacency < b0:
                i += 1
                continue
            if b1 + adjacency < a0:
                j += 1
                continue
            union(ai, bi)
            if a1 < b1:
                i += 1
            elif b1 < a1:
                j += 1
            else:
                i += 1
                j += 1

    buckets: dict[int, list[int]] = {}
    for i in range(count):
        buckets.setdefault(find(i), []).append(i)

    # Overlapping custom runs describe the same pixels, even when source run
    # indices must remain distinct. Count their union in each already-sorted row.
    pixel_counts: dict[int, int] = {}
    for items in rows.values():
        previous_end = None
        for x0, x1, index in items:
            root = find(index)
            start = x0 if previous_end is None else max(x0, previous_end + 1)
            pixel_counts[root] = pixel_counts.get(root, 0) + max(0, x1 - start + 1)
            previous_end = x1 if previous_end is None else max(previous_end, x1)

    out = []
    for root, indices in buckets.items():
        indices.sort()
        component_runs = tuple(runs[i] for i in indices)
        x0, y0, x1, y1 = _bbox(component_runs)
        pixels = pixel_counts[root]
        out.append({
            "indices": tuple(indices),
            "runs": component_runs,
            "bbox": (x0, y0, x1, y1),
            "width": x1 - x0 + 1,
            "height": y1 - y0 + 1,
            "pixels": int(pixels),
        })
    out.sort(key=lambda item: item["indices"][0])
    return out


def verticalize_horizontal_runs(strokes: Sequence[Sequence[int]], *,
                                cancelled=lambda: False,
                                max_area: int = 1_048_576) -> tuple[Segment, ...] | None:
    """Return exact vertical runs for the same pixels, or ``None`` if too costly."""
    if not strokes:
        return tuple()
    runs = [_norm_horizontal(s) for s in strokes]
    x0, y0, x1, y1 = _bbox(runs)
    width, height = x1 - x0 + 1, y1 - y0 + 1
    if width <= 0 or height <= 0 or width * height > max(1, int(max_area)):
        return None
    mask = np.zeros((height + 2, width), dtype=np.int8)
    for i, (left, y, right, _) in enumerate(runs):
        if i % 256 == 0 and cancelled():
            raise InterruptedError()
        mask[y - y0 + 1, left - x0:right - x0 + 1] = 1
    result: list[Segment] = []
    # Process a few columns together. Transposition makes nonzero return the
    # exact previous x-major/y-major order without two NumPy calls per column,
    # and avoids retaining a second full-area transition raster.
    for start_x in range(0, width, 64):
        if cancelled():
            raise InterruptedError()
        transitions = np.diff(mask[:, start_x:start_x + 64], axis=0).T
        columns, starts = np.nonzero(transitions == 1)
        _, ends = np.nonzero(transitions == -1)
        result.extend((int(x + start_x + x0), int(a + y0),
                       int(x + start_x + x0), int(b - 1 + y0))
                      for x, a, b in zip(columns, starts, ends))
    return tuple(result)


def regional_axis_variants(strokes: Sequence[Sequence[int]], *, cancelled=lambda: False,
                           max_regions: int = 8, max_area: int = 1_048_576) -> list[tuple[list[Segment], dict]]:
    """Build a bounded set of exact mixed H/V source-run candidates.

    The function intentionally does not choose a winner. Extra Fast evaluates the
    returned candidates with its real downstream ExecutionCostModel. A few
    single-region alternatives catch travel wins, while one cumulative candidate
    combines regions whose vertical representation is no larger in raw runs.
    """
    if len(strokes) < 6:
        return []
    try:
        runs = [_norm_horizontal(s) for s in strokes]
    except ValueError:
        return []
    components = horizontal_components(runs, adjacency=0, cancelled=cancelled)
    eligible = []
    for comp in components:
        if cancelled():
            raise InterruptedError()
        if len(comp["runs"]) < 3 or comp["width"] < 2 or comp["height"] < 2:
            continue
        vertical = verticalize_horizontal_runs(comp["runs"], cancelled=cancelled, max_area=max_area)
        if vertical is None or not vertical:
            continue
        original_n = len(comp["runs"])
        vertical_n = len(vertical)
        # Keep planning work bounded. A modestly larger raw representation can
        # still win after continuous-path joining/travel ordering, but huge
        # expansions cannot plausibly help Extra Fast.
        if vertical_n > original_n + max(4, int(original_n * .25)):
            continue
        gain = original_n - vertical_n
        aspect = comp["height"] / max(1.0, float(comp["width"]))
        # Preserve the established horizontal baseline for near-square/wide
        # regions unless vertical rasterization removes a meaningful number of
        # source-run boundaries. This avoids axis churn for a 60x59 rectangle
        # merely because vertical happens to contain one fewer raw run, while
        # still allowing tall regions and genuinely cheaper irregular regions.
        clearly_vertical = aspect >= 1.25
        meaningful_reduction = vertical_n * 5 <= original_n * 4
        if not clearly_vertical and not meaningful_reduction:
            continue
        eligible.append((gain, aspect, comp, vertical))
    if not eligible:
        return []

    eligible.sort(key=lambda item: (item[0], item[1], item[2]["pixels"]), reverse=True)
    eligible = eligible[:max(1, int(max_regions))]
    variants: list[tuple[list[Segment], dict]] = []

    def assemble(replacements: dict[int, tuple[Segment, ...]]) -> list[Segment]:
        parts = []
        for ci, comp in enumerate(components):
            parts.extend(replacements.get(ci, comp["runs"]))
        return parts

    component_index = {id(comp): i for i, comp in enumerate(components)}
    # A few single-region probes let the real cost model find wins that raw run
    # counts alone cannot see (for example lower pen-up travel).
    for _gain, aspect, comp, vertical in eligible[:4]:
        ci = component_index[id(comp)]
        variants.append((assemble({ci: vertical}), {
            "kind": "single-region",
            "reoriented_regions": 1,
            "raw_run_delta": int(len(vertical) - len(comp["runs"])),
            "component_bbox": list(comp["bbox"]),
            "component_aspect": round(float(aspect), 4),
        }))

    replacements = {}
    raw_delta = 0
    for _gain, _aspect, comp, vertical in eligible:
        if len(vertical) <= len(comp["runs"]):
            ci = component_index[id(comp)]
            replacements[ci] = vertical
            raw_delta += len(vertical) - len(comp["runs"])
    if len(replacements) >= 2:
        variants.append((assemble(replacements), {
            "kind": "mixed-regions",
            "reoriented_regions": len(replacements),
            "raw_run_delta": int(raw_delta),
        }))

    # Deduplicate equivalent run sets while preserving the cheap-first order.
    seen = set()
    unique = []
    for candidate, meta in variants:
        key = tuple(candidate)
        if key in seen or key == tuple(runs):
            continue
        seen.add(key)
        unique.append((candidate, meta))
    return unique


def mask_horizontal_runs(mask, *, cancelled=lambda: False) -> list[Segment]:
    """Convert a 2-D boolean mask to exact horizontal runs."""
    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("mask must be two-dimensional")
    runs: list[Segment] = []
    for y in range(arr.shape[0]):
        if y % 128 == 0 and cancelled():
            raise InterruptedError()
        xs = np.flatnonzero(arr[y])
        if xs.size == 0:
            continue
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts = np.r_[0, breaks + 1]
        ends = np.r_[breaks, xs.size - 1]
        runs.extend((int(xs[a]), int(y), int(xs[b]), int(y)) for a, b in zip(starts, ends))
    return runs
