"""Component-aware lossless stroke planner for Image Draw Bot v1.0.90-beta.

Block B consumes the full-resolution PixelMap from v1.0.86 and turns it into
safe execution paths without changing palette assignments.  It labels exact
4-connected colour regions, chooses horizontal/vertical raster runs locally per
component, verifies every merged connector against the component mask, schedules
components on CPU, and emits four quality-first passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

import numpy as np

from ContinuousPaths import order_paths
from PixelAccuratePlanner import PixelMap, groups_from_pixel_map, validated_pixel_indices

Point = tuple[int, int]
Segment = tuple[int, int, int, int]
Path = tuple[Point, ...]

PHASES = ("fill", "mid_detail", "fine_detail", "cleanup")
PHASE_LABELS = {
    "fill": "large fills",
    "mid_detail": "mid detail",
    "fine_detail": "fine detail",
    "cleanup": "protected cleanup",
}


@dataclass
class _Run:
    rid: int
    y: int
    x0: int
    x1: int
    color: int


@dataclass
class Component:
    component_id: int
    color_index: int
    area: int = 0
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    importance_mean: float = 0.0
    importance_max: float = 0.0
    edge_mean: float = 0.0
    contour_mean: float = 0.0
    shadow_mean: float = 0.0
    shadow_detail_mean: float = 0.0
    render_role: str = "base"
    protected_pixels: int = 0
    horizontal_runs: list[Segment] = field(default_factory=list)
    vertical_runs: list[Segment] = field(default_factory=list)
    orientation: str = "horizontal"
    phase: str = "mid_detail"
    paths: list[Path] = field(default_factory=list)
    safe_merge_fallbacks: int = 0

    @property
    def width(self) -> int:
        return int(self.bbox[2] - self.bbox[0] + 1)

    @property
    def height(self) -> int:
        return int(self.bbox[3] - self.bbox[1] + 1)

    @property
    def protected_ratio(self) -> float:
        return 0.0 if self.area <= 0 else float(self.protected_pixels) / float(self.area)

    def meta(self) -> dict:
        return {
            "component_id": self.component_id,
            "color_index": self.color_index,
            "area": self.area,
            "bbox": self.bbox,
            "importance_mean": round(float(self.importance_mean), 5),
            "importance_max": round(float(self.importance_max), 5),
            "edge_mean": round(float(self.edge_mean), 5),
            "contour_mean": round(float(self.contour_mean), 5),
            "shadow_mean": round(float(self.shadow_mean), 5),
            "shadow_detail_mean": round(float(self.shadow_detail_mean), 5),
            "render_role": self.render_role,
            "protected_pixels": self.protected_pixels,
            "protected_ratio": round(self.protected_ratio, 5),
            "horizontal_runs": len(self.horizontal_runs),
            "vertical_runs": len(self.vertical_runs),
            "orientation": self.orientation,
            "phase": self.phase,
            "paths": len(self.paths),
            "safe_merge_fallbacks": self.safe_merge_fallbacks,
        }


class _UnionFind:
    def __init__(self) -> None:
        self.parent: list[int] = []
        self.rank: list[int] = []

    def add(self) -> int:
        i = len(self.parent)
        self.parent.append(i); self.rank.append(0)
        return i

    def find(self, x: int) -> int:
        parent = self.parent
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def _row_runs(pixel_map: PixelMap, cancelled=lambda: False) -> tuple[list[_Run], list[list[int]], _UnionFind]:
    idx, mask = validated_pixel_indices(pixel_map, cancelled=cancelled)
    h, w = idx.shape
    uf = _UnionFind()
    runs: list[_Run] = []
    rows: list[list[int]] = []
    previous_by_color: dict[int, list[int]] = {}

    for y in range(h):
        if cancelled():
            raise InterruptedError()
        row_ids: list[int] = []
        current_by_color: dict[int, list[int]] = {}
        values = np.full(w, -1, dtype=np.int16)
        values[mask[y]] = idx[y][mask[y]]
        boundaries = np.r_[0, np.flatnonzero(values[1:] != values[:-1]) + 1, w]
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            color = int(values[start]) if start < w else -1
            if color < 0:
                continue
            x0, x1 = int(start), int(end) - 1
            rid = uf.add()
            runs.append(_Run(rid, y, x0, x1, color))
            row_ids.append(rid)
            current_by_color.setdefault(color, []).append(rid)

        # Exact 4-connectivity: same colour runs on neighbouring rows are joined
        # only when their x intervals overlap.  This never bridges a blank pixel.
        for color, current in current_by_color.items():
            previous = previous_by_color.get(color, ())
            i = j = 0
            while i < len(previous) and j < len(current):
                a = runs[previous[i]]; b = runs[current[j]]
                if a.x1 < b.x0:
                    i += 1
                elif b.x1 < a.x0:
                    j += 1
                else:
                    uf.union(a.rid, b.rid)
                    if a.x1 <= b.x1:
                        i += 1
                    if b.x1 <= a.x1:
                        j += 1
        previous_by_color = current_by_color
        rows.append(row_ids)
    return runs, rows, uf


def _vertical_run_chunk(component_map: np.ndarray, x0: int, x1: int, cancelled=lambda: False) -> list[tuple[int, Segment]]:
    h,_w=component_map.shape;out=[]
    for x in range(int(x0),int(x1)):
        if cancelled():raise InterruptedError()
        values=component_map[:,x]
        boundaries=np.r_[0,np.flatnonzero(values[1:] != values[:-1])+1,h]
        for start,end in zip(boundaries[:-1],boundaries[1:]):
            cid=int(values[start]) if start<h else -1
            if cid>=0:out.append((cid,(x,int(start),x,int(end)-1)))
    return out


def _row_component_statistics(pixel_map: PixelMap, y: int, row_runs, *, cancelled):
    """Reduce all runs in one row together, including gaps between runs.

    Alternating start/end boundaries let reduceat cover exactly each drawable
    interval. The unused inter-run reductions are discarded. One padded value
    handles a run ending at the right edge without a special final interval.
    """
    planes = (pixel_map.importance_map, pixel_map.edge_map,
              pixel_map.contour_map if pixel_map.contour_map is not None else pixel_map.edge_map,
              pixel_map.shadow_map, pixel_map.shadow_detail_map)
    if len(row_runs) < 8:
        # Solid rows and sparse dots have too few runs to amortize full-row
        # padding. Keep their original small slice reductions instead.
        if cancelled():raise InterruptedError()
        slices = [slice(run.x0, run.x1 + 1) for run in row_runs]
        sums = [[0.0] * len(slices) if plane is None else
                [float(np.sum(plane[y, sl], dtype=np.float64)) for sl in slices]
                for plane in planes]
        maxima = [float(np.max(pixel_map.importance_map[y, sl])) for sl in slices]
        counts = [int(np.count_nonzero(pixel_map.protected_mask[y, sl])) for sl in slices]
        return sums, maxima, counts
    def boundaries():
        for index, run in enumerate(row_runs):
            if index % 128 == 0 and cancelled():raise InterruptedError()
            yield run.x0
            yield run.x1 + 1
    bounds = np.fromiter(boundaries(), dtype=np.intp, count=len(row_runs) * 2)
    cache = {}
    sums = []
    for plane in planes:
        if cancelled():raise InterruptedError()
        key = id(plane)
        if key not in cache:
            if plane is None:
                cache[key] = np.zeros(len(row_runs), dtype=np.float64)
            else:
                values = np.empty(pixel_map.width + 1, dtype=np.float64)
                values[:-1] = plane[y]
                values[-1] = 0
                cache[key] = np.add.reduceat(values, bounds)[::2]
        sums.append(cache[key])
    values = np.empty(pixel_map.width + 1, dtype=np.float64)
    values[:-1] = pixel_map.importance_map[y]
    values[-1] = 0
    maxima = np.maximum.reduceat(values, bounds)[::2]
    protected = np.empty(pixel_map.width + 1, dtype=np.int64)
    # Preserve count_nonzero semantics for supported numeric masks as well
    # as the Boolean masks produced by the application.
    protected[:-1] = np.asarray(pixel_map.protected_mask[y], dtype=np.bool_)
    protected[-1] = 0
    counts = np.add.reduceat(protected, bounds)[::2]
    return sums, maxima, counts


def connected_components(pixel_map: PixelMap, *, cpu_workers: int = 1, include_vertical_runs: bool = True,
                         cancelled=lambda: False) -> tuple[list[Component], np.ndarray, dict]:
    """Label lossless same-palette 4-connected regions using run union-find."""
    runs, rows, uf = _row_runs(pixel_map, cancelled)
    h, w = pixel_map.height, pixel_map.width
    component_map = np.full((h, w), -1, dtype=np.int32)
    root_to_component: dict[int, int] = {}
    components: list[Component] = []
    for y, row_ids in enumerate(rows):
        if cancelled():raise InterruptedError()
        if not row_ids:continue
        row_runs = [runs[index] for index in row_ids]
        sums, maxima, protected = _row_component_statistics(pixel_map, y, row_runs, cancelled=cancelled)
        for run_index,run in enumerate(row_runs):
            if run_index%128==0 and cancelled():raise InterruptedError()
            root = uf.find(run.rid)
            cid = root_to_component.get(root)
            if cid is None:
                cid = len(components)
                root_to_component[root] = cid
                components.append(Component(cid, run.color, bbox=(run.x0, run.y, run.x1, run.y)))
            comp = components[cid]
            comp.area += run.x1 - run.x0 + 1
            x0, y0, x1, y1 = comp.bbox
            comp.bbox = (min(x0, run.x0), min(y0, run.y), max(x1, run.x1), max(y1, run.y))
            comp.horizontal_runs.append((run.x0, run.y, run.x1, run.y))
            # These fields hold sums until the component is complete; avoid a
            # second Python dictionary and five boxed sums per component.
            comp.importance_mean += float(sums[0][run_index])
            comp.edge_mean += float(sums[1][run_index])
            comp.contour_mean += float(sums[2][run_index])
            comp.shadow_mean += float(sums[3][run_index])
            comp.shadow_detail_mean += float(sums[4][run_index])
            comp.importance_max = max(comp.importance_max, float(maxima[run_index]))
            comp.protected_pixels += int(protected[run_index])
            component_map[run.y, run.x0:run.x1+1] = cid

    for comp in components:
        if comp.area:
            comp.importance_mean /= comp.area
            comp.edge_mean /= comp.area
            comp.contour_mean /= comp.area
            comp.shadow_mean /= comp.area
            comp.shadow_detail_mean /= comp.area

    # Build exact vertical runs. Block D parallelizes independent column chunks
    # while preserving deterministic x-order when merging the results.
    vertical_lists: list[list[Segment]] = [[] for _ in components]
    workers=max(1,int(cpu_workers or 1))
    vertical_backend="cpu-serial-columns"
    if not include_vertical_runs:
        vertical_backend="not-requested"
    elif workers>1 and w>=64:
        chunk=max(16,math.ceil(w/min(workers,16)))
        ranges=[(x,min(w,x+chunk)) for x in range(0,w,chunk)]
        with ThreadPoolExecutor(max_workers=min(workers,len(ranges))) as pool:
            futures=[pool.submit(_vertical_run_chunk,component_map,a,b,cancelled) for a,b in ranges]
            chunks=[f.result() for f in futures]
        if cancelled():raise InterruptedError()
        for chunk_items in chunks:
            for cid,segment in chunk_items:vertical_lists[cid].append(segment)
        vertical_backend="cpu-parallel-column-chunks"
    else:
        for cid,segment in _vertical_run_chunk(component_map,0,w,cancelled):vertical_lists[cid].append(segment)
    for comp in components:comp.vertical_runs=vertical_lists[comp.component_id]

    return components, component_map, {
        "component_count": len(components),
        "source_runs": len(runs),
        "component_label_backend": "cpu-run-union-find",
        "component_connectivity": 4,
        "vertical_run_backend": vertical_backend,
        "vertical_run_workers": workers if vertical_backend.startswith("cpu-parallel") else 1,
    }


def _choose_orientation(comp: Component) -> str:
    h_cost = len(comp.horizontal_runs)
    v_cost = len(comp.vertical_runs)
    # Protected thin structures prefer the long geometric axis when its path
    # count is within 20% of the cheaper alternative; this avoids fragmenting an
    # eyebrow/edge just to save one press/release.
    if comp.protected_pixels and min(comp.width, comp.height) <= 3:
        preferred = "horizontal" if comp.width >= comp.height else "vertical"
        preferred_cost = h_cost if preferred == "horizontal" else v_cost
        cheapest = max(1, min(h_cost, v_cost))
        if preferred_cost <= math.ceil(cheapest * 1.20):
            return preferred
    if v_cost < h_cost:
        return "vertical"
    if h_cost < v_cost:
        return "horizontal"
    return "horizontal" if comp.width >= comp.height else "vertical"




@dataclass
class _ActiveRasterPath:
    points: list[Point]
    last_y: int
    x0: int
    x1: int
    rows: int = 1


def _append_point(points: list[Point], point: Point) -> None:
    point=(int(point[0]),int(point[1]))
    if not points or points[-1] != point:
        points.append(point)


def _lossless_attachment_points(state: _ActiveRasterPath, run: Segment) -> list[Point]:
    x0,y,x1,_=run
    if x1<x0:x0,x1=x1,x0
    lo,hi=max(state.x0,x0),min(state.x1,x1)
    if lo>hi or y!=state.last_y+1:
        raise ValueError('Runs are not safely adjacent.')
    end_x=state.points[-1][0]
    connector=min(hi,max(lo,end_x))
    points=[state.points[-1]]
    _append_point(points,(connector,state.last_y))
    _append_point(points,(connector,y))
    # Sweep the complete new run.  Crucially, do not collinear-compress a
    # backtrack such as 0->2->1: the turning point represents real source pixels.
    if x0!=x1:
        if connector==x0:
            _append_point(points,(x1,y))
        elif connector==x1:
            _append_point(points,(x0,y))
        elif abs(connector-x0)<=abs(x1-connector):
            _append_point(points,(x0,y));_append_point(points,(x1,y))
        else:
            _append_point(points,(x1,y));_append_point(points,(x0,y))
    return points[1:]


def _attach_lossless(state: _ActiveRasterPath, run: Segment) -> None:
    state.points.extend(_lossless_attachment_points(state,run))
    x0,y,x1,_=run
    x0,x1=sorted((x0,x1))
    state.last_y=y;state.x0=x0;state.x1=x1;state.rows+=1


def _merge_horizontal_runs_lossless(runs: Sequence[Segment], *, cancelled=lambda: False,
                                    max_rows_per_path: int = 96, max_points_per_path: int = 480) -> list[Path]:
    if max_points_per_path < 2 or max_rows_per_path < 1:
        raise ValueError("Path limits require at least two points and one row.")
    rows: dict[int,list[Segment]]={}
    passthrough: list[Path]=[]
    for stroke in runs:
        if cancelled():raise InterruptedError()
        x0,y0,x1,y1=map(int,stroke)
        if y0!=y1:
            passthrough.append(((x0,y0),) if (x0,y0)==(x1,y1) else ((x0,y0),(x1,y1)))
            continue
        if x1<x0:x0,x1=x1,x0
        rows.setdefault(y0,[]).append((x0,y0,x1,y0))
    completed: list[Path]=[]
    active: list[_ActiveRasterPath]=[]
    for y in sorted(rows):
        if cancelled():raise InterruptedError()
        fresh=[]
        for st in active:
            if st.last_y==y-1:fresh.append(st)
            else:completed.append(tuple(st.points))
        active=fresh
        used=set();next_active=[]
        for run in sorted(rows[y],key=lambda r:(r[0],r[2])):
            x0,_,x1,_=run
            candidates=[]
            for i,st in enumerate(active):
                if i in used or st.rows>=max_rows_per_path or len(st.points)>=max_points_per_path:continue
                lo,hi=max(st.x0,x0),min(st.x1,x1)
                if lo<=hi:
                    if len(st.points)+len(_lossless_attachment_points(st,run))>max_points_per_path:continue
                    connector=min(hi,max(lo,st.points[-1][0]))
                    candidates.append((-(hi-lo+1),abs(connector-st.points[-1][0]),i,st))
            if candidates:
                _,_,i,st=min(candidates,key=lambda v:(v[0],v[1],v[2]))
                used.add(i);_attach_lossless(st,run);next_active.append(st)
            else:
                pts=[(x0,y)]
                if x1!=x0:pts.append((x1,y))
                next_active.append(_ActiveRasterPath(pts,y,x0,x1))
        for i,st in enumerate(active):
            if i not in used:completed.append(tuple(st.points))
        active=next_active
    completed.extend(tuple(st.points) for st in active)
    completed.extend(passthrough)
    return [p for p in completed if p]

def _transpose_segments(segments: Sequence[Segment]) -> list[Segment]:
    return [(y0, x0, y1, x1) for x0, y0, x1, y1 in segments]


def _transpose_paths(paths: Sequence[Path]) -> list[Path]:
    return [tuple((int(y), int(x)) for x, y in path) for path in paths]


def _segment_inside_component(a: Point, b: Point, component_map: np.ndarray, cid: int) -> bool:
    x0, y0 = map(int, a); x1, y1 = map(int, b)
    h, w = component_map.shape
    if not (0 <= x0 < w and 0 <= x1 < w and 0 <= y0 < h and 0 <= y1 < h):
        return False
    if x0 != x1 and y0 != y1:
        return False
    if x0 == x1:
        lo, hi = sorted((y0, y1))
        return bool(np.all(component_map[lo:hi + 1, x0] == cid))
    lo, hi = sorted((x0, x1))
    return bool(np.all(component_map[y0, lo:hi + 1] == cid))


def _path_inside_component(path: Path, component_map: np.ndarray, cid: int) -> bool:
    if not path:
        return False
    if len(path) == 1:
        x, y = path[0]
        return 0 <= y < component_map.shape[0] and 0 <= x < component_map.shape[1] and int(component_map[y, x]) == cid
    return all(_segment_inside_component(a, b, component_map, cid) for a, b in zip(path, path[1:]))




def _paths_exact_component_coverage(paths: Sequence[Path], component_map: np.ndarray, comp: Component, *, cancelled=lambda: False) -> bool:
    x0, y0, x1, y1 = comp.bbox
    target = component_map[y0:y1 + 1, x0:x1 + 1] == comp.component_id
    covered = np.zeros(target.shape, dtype=np.bool_)
    for path in paths:
        if cancelled():raise InterruptedError()
        if not path:
            continue
        if len(path) == 1:
            x, y = path[0]
            if not (x0 <= x <= x1 and y0 <= y <= y1) or int(component_map[y, x]) != comp.component_id:
                return False
            covered[y - y0, x - x0] = True
            continue
        for a, b in zip(path, path[1:]):
            if not _segment_inside_component(a, b, component_map, comp.component_id):
                return False
            ax, ay = a; bx, by = b
            if ax == bx:
                lo, hi = sorted((ay, by)); covered[lo - y0:hi - y0 + 1, ax - x0] = True
            else:
                lo, hi = sorted((ax, bx)); covered[ay - y0, lo - x0:hi - x0 + 1] = True
    return bool(np.array_equal(covered, target))

def _individual_run_paths(runs: Sequence[Segment]) -> list[Path]:
    out: list[Path] = []
    for x0, y0, x1, y1 in runs:
        out.append(((x0, y0),) if (x0, y0) == (x1, y1) else ((x0, y0), (x1, y1)))
    return out


def _candidate_paths(comp: Component, orientation: str, component_map: np.ndarray, *, cancelled=lambda: False):
    source_runs=comp.horizontal_runs if orientation=="horizontal" else comp.vertical_runs
    if orientation=="horizontal":
        paths=_merge_horizontal_runs_lossless(source_runs,cancelled=cancelled)
    else:
        paths=_transpose_paths(_merge_horizontal_runs_lossless(_transpose_segments(source_runs),cancelled=cancelled))
    # Coverage verification already checks every segment stays inside the component.
    exact=_paths_exact_component_coverage(paths,component_map,comp,cancelled=cancelled)
    return paths,source_runs,exact


def _bounded_axis_paths(paths, cost_model, max_seconds, *, cancelled=lambda: False):
    """Split exact axis-aligned geometry into short mouse-up boundaries.

    Only active deadline plans use this. Shared endpoints preserve coverage;
    paths are never joined across a hole or moved outside their component.
    """
    if cost_model is None or max_seconds is None:
        return paths
    out=[]
    fixed=max(cost_model.path_fixed_seconds,cost_model.learned_path_floor_seconds)
    available=max(cost_model.draw_seconds_per_px*max(cost_model.scale_x,cost_model.scale_y),
                  float(max_seconds)-fixed)
    for path in paths:
        if cancelled():raise InterruptedError()
        if len(path)<2:
            out.append(path);continue
        current=[path[0]];used=0.0
        for end in path[1:]:
            x,y=current[-1];ex,ey=end
            if x!=ex and y!=ey:
                raise ValueError('Deadline splitting requires exact axis-aligned paths.')
            scale=cost_model.scale_x if y==ey else cost_model.scale_y
            per_pixel=max(1e-12,cost_model.draw_seconds_per_px*scale)
            left=abs(ex-x)+abs(ey-y)
            while left:
                if cancelled():raise InterruptedError()
                steps=int((available-used+1e-12)/per_pixel)
                if steps<1 and len(current)>1:
                    out.append(tuple(current));current=[current[-1]];used=0.0;continue
                take=min(left,max(1,steps))
                x+=take*(1 if ex>x else -1 if ex<x else 0)
                y+=take*(1 if ey>y else -1 if ey<y else 0)
                current.append((x,y));used+=take*per_pixel;left-=take
        if current:out.append(tuple(current))
    return out


def build_component_paths(comp: Component, component_map: np.ndarray, *, cost_model=None, max_path_seconds=None, cancelled=lambda: False) -> tuple[list[Path], dict]:
    """Build safe H/V candidates and choose by calibrated time when available."""
    legacy_orientation=_choose_orientation(comp)
    candidate_meta={}
    if cost_model is None:
        comp.orientation=legacy_orientation
        paths,source_runs,exact_coverage=_candidate_paths(comp,comp.orientation,component_map,cancelled=cancelled)
    else:
        choices=[]
        for orientation in ("horizontal","vertical"):
            paths0,runs0,exact0=_candidate_paths(comp,orientation,component_map,cancelled=cancelled)
            if exact0:
                paths0=_bounded_axis_paths(paths0,cost_model,max_path_seconds,cancelled=cancelled)
                ordered=order_paths(paths0,"Balanced",allow_reverse=True)
                ordered_cost = float(cost_model.paths_seconds(ordered))
                original_cost = float(cost_model.paths_seconds(paths0))
                if ordered_cost <= original_cost:
                    paths0=ordered
                    cost = ordered_cost
                else:
                    cost = original_cost
            else:
                cost = float("inf")
            candidate_meta[orientation]={"safe":bool(exact0),"paths":len(paths0),"estimated_seconds":None if not math.isfinite(cost) else round(cost,6)}
            if exact0:choices.append((cost,orientation,paths0,runs0))
        if choices:
            choices.sort(key=lambda item:(item[0],0 if item[1]==legacy_orientation else 1,item[1]))
            # Protected very-thin structures keep the legacy long-axis choice if
            # its real predicted cost is within 6%; this avoids fragmentation for
            # a negligible timing win.
            best=choices[0]
            legacy=next((x for x in choices if x[1]==legacy_orientation),None)
            if comp.protected_pixels and min(comp.width,comp.height)<=3 and legacy and legacy[0]<=best[0]*1.06:
                best=legacy
            _cost,comp.orientation,paths,source_runs=best;exact_coverage=True
        else:
            comp.orientation=legacy_orientation
            paths,source_runs,exact_coverage=_candidate_paths(comp,comp.orientation,component_map,cancelled=cancelled)
    if not exact_coverage:
        paths=_individual_run_paths(source_runs);comp.safe_merge_fallbacks+=1
    if cost_model is None:
        paths=order_paths(paths,"Balanced",allow_reverse=True)
    comp.paths=list(paths)
    return comp.paths,{
        "orientation":comp.orientation,"source_runs":len(source_runs),"execution_paths":len(comp.paths),
        "safe_verified":bool(exact_coverage),"fallback":not bool(exact_coverage),
        "selection":"calibrated-time" if cost_model is not None else "legacy-run-count",
        "candidates":candidate_meta,
    }


def classify_render_role(comp: Component) -> str:
    """Describe why a component is visually important without changing pixels."""
    if comp.contour_mean >= .50 or comp.edge_mean >= .58:
        return "contour"
    if comp.shadow_detail_mean >= .43:
        return "shadow_detail"
    if comp.shadow_mean >= .44:
        return "shadow"
    if comp.importance_mean >= .50:
        return "detail"
    return "base"


def classify_component(comp: Component, total_drawable: int) -> str:
    """Assign one quality-first pass without deleting or duplicating pixels."""
    total_drawable = max(1, int(total_drawable))
    protected_ratio = comp.protected_ratio
    thin = min(comp.width, comp.height) <= 2
    comp.render_role = classify_render_role(comp)

    # Strong contours and small shadow transitions are intentionally deferred to
    # the detail/post-processing half of the render so they sit on top visually.
    if comp.protected_pixels and (comp.area <= 196 or protected_ratio >= .22 or comp.importance_mean >= .56):
        return "cleanup"
    if comp.render_role in ("contour", "shadow_detail"):
        return "fine_detail"
    if comp.render_role == "shadow":
        return "mid_detail"
    if comp.area >= max(64, int(total_drawable * .0025)) and comp.edge_mean < .34 and protected_ratio < .08:
        return "fill"
    if thin or comp.area <= max(18, int(total_drawable * .00020)) or comp.edge_mean >= .52 or comp.importance_mean >= .50:
        return "fine_detail"
    return "mid_detail"


def _priority(comp: Component) -> float:
    if comp.phase == "fill":
        return comp.area * 1.0 + comp.importance_mean * 20.0
    if comp.phase == "mid_detail":
        return comp.area * .20 + comp.importance_mean * 120.0 + comp.edge_mean * 50.0
    if comp.phase == "fine_detail":
        role_bonus = 80.0 if comp.render_role == "contour" else (60.0 if comp.render_role == "shadow_detail" else 0.0)
        return (comp.importance_mean * 180.0 + comp.edge_mean * 80.0 + comp.contour_mean * 90.0 +
                comp.shadow_detail_mean * 70.0 + min(comp.area, 80) * .15 + role_bonus)
    role_bonus = 120.0 if comp.render_role == "contour" else (90.0 if comp.render_role == "shadow_detail" else 0.0)
    return (comp.importance_max * 220.0 + comp.protected_ratio * 160.0 + comp.edge_mean * 50.0 +
            comp.contour_mean * 110.0 + comp.shadow_detail_mean * 90.0 + role_bonus)


def _component_entry_point(comp: Component) -> Point:
    if comp.paths and comp.paths[0]:
        return comp.paths[0][0]
    return (comp.bbox[0], comp.bbox[1])


def schedule_components(components: Sequence[Component], palette_count: int, *, cost_model=None, cancelled=lambda: False) -> tuple[list[list[Path]], list[dict], dict]:
    """CPU bounded component scheduler: phase first, then quality/travel/color cost."""
    execution_groups: list[list[Path]] = [[] for _ in range(int(palette_count))]
    sequence: list[dict] = []
    phase_counts = {phase: 0 for phase in PHASES}
    component_counts = {phase: 0 for phase in PHASES}
    cursor: Point | None = None
    current_color: int | None = None
    serial = 0
    # Geometry is immutable while scheduling. Only entry travel and colour cost
    # change; do not walk every point again for all 72 candidates at each step.
    intrinsic = ({c.component_id: float(cost_model.paths_seconds(c.paths))
                  for c in components if c.paths} if cost_model is not None else {})
    estimated_total = 0.0

    for phase in PHASES:
        remaining = sorted((c for c in components if c.phase == phase and c.paths), key=lambda c: (-_priority(c), c.component_id))
        while remaining:
            if cancelled():
                raise InterruptedError()
            window_n = min(72, len(remaining))
            best_i = 0; best_cost = float("inf")
            for i in range(window_n):
                comp = remaining[i]
                start = _component_entry_point(comp)
                if cost_model is None:
                    travel = 0.0 if cursor is None else math.hypot(start[0] - cursor[0], start[1] - cursor[1])
                    color_penalty = 0.0 if current_color in (None, comp.color_index) else 18.0
                    priority_credit = min(30.0, _priority(comp) * .025)
                    cost = travel + color_penalty - priority_credit + i * 1e-6
                else:
                    seconds=intrinsic[comp.component_id]
                    if cursor is not None and comp.paths and comp.paths[0]:
                        first=comp.paths[0]
                        # paths_seconds() already includes the first path's base
                        # travel/settle term. Add only the real stateful entry delta.
                        moved=float(cost_model.path_seconds(first,cursor=cursor))
                        base=float(cost_model.path_seconds(first,cursor=None))
                        seconds+=max(0.0,moved-base)
                    if current_color not in (None,comp.color_index):
                        seconds+=float(cost_model.color_change_seconds)
                    # Keep the multi-pass contract, but within each phase choose
                    # the component with highest visual value per millisecond.
                    value=max(.001,float(_priority(comp)))
                    cost=(seconds/max(.001,value))+i*1e-9
                if cost < best_cost:
                    best_i, best_cost = i, cost
            comp = remaining.pop(best_i)
            component_counts[phase] += 1
            for path in comp.paths:
                execution_groups[comp.color_index].append(path)
                sequence.append({
                    "color_index": int(comp.color_index),
                    "path": tuple(path),
                    "phase": phase,
                    "phase_label": PHASE_LABELS[phase],
                    "component_id": int(comp.component_id),
                    "orientation": comp.orientation,
                    "importance": round(float(comp.importance_max),6),
                    "protected": bool(comp.protected_pixels),
                    "component_area": int(comp.area),
                    "component_width": int(comp.width),
                    "component_height": int(comp.height),
                    "edge_mean": round(float(comp.edge_mean),6),
                    "contour_mean": round(float(comp.contour_mean),6),
                    "shadow_mean": round(float(comp.shadow_mean),6),
                    "shadow_detail_mean": round(float(comp.shadow_detail_mean),6),
                    "render_role": comp.render_role,
                    "post_process_priority": bool(comp.phase == "cleanup" and comp.render_role in ("contour", "shadow_detail", "detail")),
                    "serial": serial,
                })
                serial += 1
                phase_counts[phase] += 1
                if path:
                    cursor = path[-1]
            current_color = comp.color_index

    if cost_model is not None:
        try:
            _initial_brush=max(1,int(getattr(cost_model,'options',{}).get('brush_px',1) or 1))
            estimated_total=float(cost_model.sequence_cost(
                sequence,initial_brush=_initial_brush).total_seconds)
        except Exception:
            # The geometry/order remains valid even if diagnostics cannot be costed.
            estimated_total=sum(float(cost_model.paths_seconds(c.paths)) for c in components if c.paths)

    return execution_groups, sequence, {
        "scheduler_backend": "cpu-component-bounded-nearest",
        "scheduler_window": 72,
        "multi_pass": True,
        "pass_order": "fill -> mid detail -> fine detail -> cleanup",
        "phase_path_counts": phase_counts,
        "phase_component_counts": component_counts,
        "scheduled_paths": len(sequence),
        "cost_aware": bool(cost_model is not None),
        "cost_policy": "ExecutionCostModel stateful v3" if cost_model is not None else "legacy geometry scheduler",
        "cost_model": cost_model.as_dict() if cost_model is not None else None,
        "estimated_execution_seconds": round(estimated_total,4) if cost_model is not None else None,
        "scheduled_color_switches": sum(1 for a,b in zip(sequence,sequence[1:]) if a["color_index"]!=b["color_index"]),
    }


def build_pixel_stroke_plan(pixel_map: PixelMap, palette_count: int, *, lines: bool = True,
                            cpu_workers: int = 1, options=None, cancelled=lambda: False) -> dict:
    """Build Block B component paths while preserving every drawable PixelMap pixel."""
    started=time.perf_counter()
    groups = groups_from_pixel_map(pixel_map, palette_count, lines=lines, cancelled=cancelled)
    groups_done=time.perf_counter()
    cost_model=None
    if isinstance(options,dict) and str(options.get("adaptive_hybrid_cost","Auto")) != "Off":
        try:
            from ExecutionCostModel import build_cost_model
            # DrawBot already provides exact _hybrid_scale_x/y for Pixel Accurate.
            # Direct tests that do not have a target canvas remain source-space 1:1.
            cost_model=build_cost_model(options,(pixel_map.width,pixel_map.height),
                                        (pixel_map.width,pixel_map.height))
        except Exception:
            cost_model=None
    if not lines:
        # Dot mode is already exactly lossless and has no meaningful local run
        # orientation. Keep a deterministic four-pass-free fallback.
        execution_groups = [[((x0, y0),) for x0, y0, _x1, _y1 in group] for group in groups]
        sequence = [
            {"color_index": ci, "path": path, "phase": "fine_detail", "phase_label": PHASE_LABELS["fine_detail"], "component_id": -1, "orientation": "dot", "serial": n}
            for n, (ci, path) in enumerate((ci, p) for ci, ps in enumerate(execution_groups) for p in ps)
        ]
        return {"groups": groups, "execution_groups": execution_groups, "execution_sequence": sequence,
                "metadata": {"engine": "Pixel Stroke Engine Block B", "component_count": 0, "scheduled_paths": len(sequence), "dot_mode": True}}

    components, component_map, component_meta = connected_components(pixel_map, cpu_workers=cpu_workers, cancelled=cancelled)
    components_done=time.perf_counter()
    total_drawable = int(np.count_nonzero(pixel_map.drawable_mask))
    orientation_counts = {"horizontal": 0, "vertical": 0}
    safe_fallbacks = 0
    protected_components = 0
    role_counts = {"base": 0, "shadow": 0, "shadow_detail": 0, "contour": 0, "detail": 0}

    for comp in components:
        comp.phase=classify_component(comp,total_drawable)
        role_counts[comp.render_role] = role_counts.get(comp.render_role, 0) + 1
        if comp.protected_pixels:protected_components+=1
    max_path_seconds=None
    if cost_model is not None and options.get('time_budget_active') and not options.get('unlimited_time'):
        budget=float(options.get('deadline_render_budget_seconds') or options.get('max_seconds') or 180)
        max_path_seconds=max(.25,min(1.0,budget*.025))
    workers=max(1,int(cpu_workers or 1));parallel_paths=workers>1 and len(components)>=16
    if parallel_paths:
        def _build(comp):
            return comp.component_id,build_component_paths(comp,component_map,cost_model=cost_model,max_path_seconds=max_path_seconds,cancelled=cancelled)
        with ThreadPoolExecutor(max_workers=min(workers,16)) as pool:
            batch_size=min(workers,16)*2
            for start in range(0,len(components),batch_size):
                if cancelled():raise InterruptedError()
                # Consume immediately; comp.paths owns the result.
                for _ in pool.map(_build,components[start:start+batch_size]):
                    if cancelled():raise InterruptedError()
    else:
        for comp in components:
            if cancelled():raise InterruptedError()
            build_component_paths(comp,component_map,cost_model=cost_model,max_path_seconds=max_path_seconds,cancelled=cancelled)
    for comp in components:
        orientation_counts[comp.orientation]+=1;safe_fallbacks+=comp.safe_merge_fallbacks

    paths_done=time.perf_counter()
    execution_groups, sequence, scheduler_meta = schedule_components(components, palette_count, cost_model=cost_model, cancelled=cancelled)
    scheduled_done=time.perf_counter()
    phase_counts = scheduler_meta["phase_path_counts"]
    metadata = {
        "engine": "Pixel Stroke Engine Block B",
        "planning_stage_seconds": {
            "source_runs": groups_done-started,
            "components": components_done-groups_done,
            "candidate_paths": paths_done-components_done,
            "scheduling": scheduled_done-paths_done,
        },
        "deadline_path_target_seconds": max_path_seconds,
        "lossless_source": True,
        "connected_regions": True,
        "local_orientation": True,
        "safe_component_merge": True,
        "protected_component_count": protected_components,
        "safe_merge_fallbacks": safe_fallbacks,
        "orientation_counts": orientation_counts,
        "source_horizontal_runs": sum(len(g) for g in groups),
        "execution_paths": sum(len(g) for g in execution_groups),
        "fill_paths": int(phase_counts.get("fill", 0)),
        "mid_detail_paths": int(phase_counts.get("mid_detail", 0)),
        "fine_detail_paths": int(phase_counts.get("fine_detail", 0)),
        "cleanup_paths": int(phase_counts.get("cleanup", 0)),
        "render_role_counts": role_counts,
        "contour_components": int(role_counts.get("contour", 0)),
        "shadow_components": int(role_counts.get("shadow", 0)),
        "shadow_detail_components": int(role_counts.get("shadow_detail", 0)),
        "post_processing": "cleanup pass prioritizes protected contours and shadow details",
        "component_path_backend": "cpu-parallel-components" if parallel_paths else "cpu-serial-components",
        "component_path_workers": min(workers,16) if parallel_paths else 1,
        **component_meta,
        **scheduler_meta,
    }
    # Keep a bounded diagnostic sample; full component lists can be huge on photos.
    metadata["component_sample"] = [c.meta() for c in sorted(components, key=lambda c: (-_priority(c), c.component_id))[:24]]
    return {
        "groups": groups,
        "execution_groups": execution_groups,
        "execution_sequence": sequence,
        "metadata": metadata,
    }
