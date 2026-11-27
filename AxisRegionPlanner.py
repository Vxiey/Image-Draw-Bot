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


def _normalized_runs(strokes, cancelled) -> list[Segment]:
    if cancelled():
        raise InterruptedError()
    runs = []
    for count, stroke in enumerate(strokes, 1):
        runs.append(_norm_horizontal(stroke))
        if count % 512 == 0 and cancelled():
            raise InterruptedError()
    return runs


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
    return _horizontal_components(_normalized_runs(strokes, cancelled), adjacency, cancelled)


def _horizontal_components(runs: list[Segment], adjacency: int, cancelled) -> list[dict]:
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
    # Buckets and their members were inserted in source-index order.
    for root, indices in buckets.items():
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
    return out


def verticalize_horizontal_runs(strokes: Sequence[Sequence[int]], *,
                                cancelled=lambda: False,
                                max_area: int = 1_048_576,
                                max_runs: int | None = None) -> tuple[Segment, ...] | None:
    """Return exact vertical runs for the same pixels, or ``None`` if too costly."""
    runs = _normalized_runs(strokes, cancelled)
    if not runs:
        return tuple()
    return _verticalize_runs(runs, _bbox(runs), cancelled, max_area, max_runs)


def _verticalize_runs(runs, bbox, cancelled, max_area, max_runs):
    x0, y0, x1, y1 = bbox
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
        if max_runs is not None and len(result) + len(starts) > max_runs:
            return None
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
        if cancelled():
            raise InterruptedError()
        return []
    try:
        runs = _normalized_runs(strokes, cancelled)
    except ValueError:
        return []
    components = _horizontal_components(runs, adjacency=0, cancelled=cancelled)
    eligible = []
    for comp in components:
        if cancelled():
            raise InterruptedError()
        if len(comp["runs"]) < 3 or comp["width"] < 2 or comp["height"] < 2:
            continue
        original_n = len(comp["runs"])
        aspect = comp["height"] / max(1.0, float(comp["width"]))
        # A connected region occupies every column of its bounding box. Tall
        # regions may expand modestly; other regions need a 20% reduction.
        # Use these existing acceptance limits before allocating vertical runs.
        max_vertical = (original_n + max(4, original_n // 4) if aspect >= 1.25
                        else original_n * 4 // 5)
        if comp["width"] > max_vertical:
            continue
        vertical = _verticalize_runs(comp["runs"], comp["bbox"], cancelled, max_area, max_vertical)
        if vertical is None or not vertical:
            continue
        vertical_n = len(vertical)
        gain = original_n - vertical_n
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

    # Each chosen component spans at least two connected rows, so replacing it
    # introduces a vertical segment unique to that component. Every variant
    # above replaces a different set of components and is therefore distinct.
    return variants


def mask_horizontal_runs(mask, *, cancelled=lambda: False) -> list[Segment]:
    """Convert a 2-D boolean mask to exact horizontal runs."""
    if cancelled():
        raise InterruptedError()
    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("mask must be two-dimensional")
    runs: list[Segment] = []
    height, width = arr.shape
    if not arr.size:
        return runs
    # One boundary at each end of every run, including ink touching a row
    # edge. Limit the temporary boundary map and indices to a tile of rows.
    stride = width + 1
    tile_height = min(height, 64, max(1, 65_536 // stride))
    edges = np.empty((tile_height, stride), dtype=bool)
    for y in range(0, height, tile_height):
        if cancelled():
            raise InterruptedError()
        rows = arr[y:y + tile_height]
        tile = edges[:len(rows)]
        tile[:, 0] = rows[:, 0]
        tile[:, -1] = rows[:, -1]
        np.not_equal(rows[:, 1:], rows[:, :-1], out=tile[:, 1:-1])
        bounds = np.flatnonzero(tile)
        row_offsets, starts = np.divmod(bounds[::2], stride)
        ends = bounds[1::2] % stride - 1
        # Share the row coordinate among its strokes, including y > 256.
        tile_rows = list(range(y, y + len(rows)))
        ys = [tile_rows[index] for index in row_offsets.tolist()]
        runs.extend(zip(starts.tolist(), ys, ends.tolist(), ys))
    return runs
