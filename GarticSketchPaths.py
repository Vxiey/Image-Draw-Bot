"""Trace Gartic sketch contours with a lossless dense-region H/V fallback.

Thin/structural components keep the connected-contour tracer. Dense components
may be re-rasterized as horizontal or vertical continuous runs, but only when the
execution-cost model predicts a material runtime reduction. No pixels are
removed, no gaps are bridged, and all candidates are generated from the same
binary source mask.
"""
from __future__ import annotations

import math
import numpy as np

from AxisRegionPlanner import (horizontal_components, mask_horizontal_runs,
                               verticalize_horizontal_runs)


def _length(path):
    return sum(math.dist(a, b) for a, b in zip(path, path[1:]))


def _split_paths(paths, max_points):
    result = []
    for path in paths:
        path = tuple(path)
        if len(path) <= max_points:
            if path:
                result.append(path)
            continue
        for i in range(0, len(path) - 1, max_points - 1):
            part = tuple(path[i:i + max_points])
            if part:
                result.append(part)
    return result


def _trace_component(runs, cancelled, max_points):
    nodes = set()
    for ri, (x0, y, x1, _) in enumerate(runs):
        if ri % 128 == 0 and cancelled():
            raise InterruptedError()
        nodes.update((x, y) for x in range(x0, x1 + 1))
    graph = {}
    for i, p in enumerate(sorted(nodes, key=lambda p: (p[1], p[0]))):
        if i % 512 == 0 and cancelled():
            raise InterruptedError()
        x, y = p
        neighbors = []
        for dx, dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1)):
            q = (x + dx, y + dy)
            if q not in nodes:
                continue
            if dx and dy and ((x + dx, y) in nodes or (x, y + dy) in nodes):
                continue
            neighbors.append(q)
        graph[p] = neighbors

    visited = set()
    raw_paths = []

    def edge(a, b):
        return (a, b) if a < b else (b, a)

    def walk(start, next_point):
        path = [start]
        previous, current = start, next_point
        visited.add(edge(previous, current))
        while True:
            path.append(current)
            if len(path) % 256 == 0 and cancelled():
                raise InterruptedError()
            if len(graph[current]) != 2:
                break
            choices = [q for q in graph[current] if edge(current, q) not in visited]
            if not choices:
                break
            nxt = choices[0]
            visited.add(edge(current, nxt))
            previous, current = current, nxt
        return path

    for p in graph:
        if cancelled():
            raise InterruptedError()
        if not graph[p]:
            raw_paths.append([p])
        elif len(graph[p]) != 2:
            for q in graph[p]:
                if edge(p, q) not in visited:
                    raw_paths.append(walk(p, q))
    for p in graph:
        if cancelled():
            raise InterruptedError()
        for q in graph[p]:
            if edge(p, q) not in visited:
                raw_paths.append(walk(p, q))

    compressed = []
    for path in raw_paths:
        points = []
        for pt in path:
            points.append(pt)
            while len(points) >= 3:
                a, b, c = points[-3:]
                u = (b[0] - a[0], b[1] - a[1])
                v = (c[0] - b[0], c[1] - b[1])
                if u[0] * v[1] != u[1] * v[0] or u[0] * v[0] + u[1] * v[1] <= 0:
                    break
                points.pop(-2)
        compressed.append(tuple(points))
    compressed.sort(key=lambda path: -_length(path))
    return _split_paths(compressed, max_points), len(raw_paths), len(nodes)


def _axis_paths(horizontal_runs, axis, cancelled, max_points, *, vertical_runs=None):
    from ContinuousPaths import _horizontal_paths
    if axis == "horizontal":
        paths = _horizontal_paths(horizontal_runs, cancelled,
                                  max_rows_per_path=110,
                                  max_points_per_path=max(24, max_points))
    else:
        vertical = vertical_runs
        if vertical is None:
            vertical = verticalize_horizontal_runs(horizontal_runs, cancelled=cancelled)
        if vertical is None:
            return []
        transposed = [(y0, x, y1, x) for x, y0, _, y1 in vertical]
        raw = _horizontal_paths(transposed, cancelled,
                                max_rows_per_path=110,
                                max_points_per_path=max(24, max_points))
        paths = [tuple((y, x) for x, y in path) for path in raw]
    return _split_paths(paths, max_points)


def _candidate_cost(paths, model):
    if not paths:
        return 0.0
    fn = getattr(model, 'paths_seconds', None)
    if callable(fn):
        return float(fn(paths))
    total = 0.0
    cursor = None
    for path in paths:
        if not path:
            continue
        path_fn = getattr(model, 'path_seconds', None)
        if callable(path_fn):
            total += float(path_fn(path, cursor=cursor))
        else:
            total += float(model.path_cost(path, cursor=cursor).total_seconds)
        cursor = path[-1]
    return total


def trace_contours(image, cancelled=lambda:False, max_points=160, options=None):
    if max_points < 3:
        raise ValueError('max_points must be at least 3')
    if cancelled():
        raise InterruptedError()
    mask = np.asarray(image.convert('L')) < 128
    runs = mask_horizontal_runs(mask, cancelled=cancelled)
    if not runs:
        return [], {'engine':'Gartic connected contours','ink_pixels':0,'contours':0,
                    'execution_paths':0,'path_points':0,'priority':'long contours first',
                    'gap_bridges':0,'dropped_components':0,'axis_candidates_evaluated':0,
                    'axis_components':0}

    components = horizontal_components(runs, adjacency=1, cancelled=cancelled)
    contour_output = []
    axis_output = []
    contour_count = 0
    ink_pixels = 0
    axis_candidates = 0
    axis_components = 0
    horizontal_components_used = 0
    vertical_components_used = 0
    modeled_saved = 0.0
    dense_shortcuts = 0
    model = None

    for component in components:
        if cancelled():
            raise InterruptedError()
        comp_runs = list(component['runs'])
        node_count = int(component['pixels'])
        ink_pixels += node_count

        vertical_runs = None
        avg_h = avg_v = 0.0
        dense_candidate = node_count >= 24 and component['width'] >= 2 and component['height'] >= 2
        if dense_candidate:
            vertical_runs = verticalize_horizontal_runs(comp_runs, cancelled=cancelled)
            if vertical_runs:
                avg_h = node_count / max(1, len(comp_runs))
                avg_v = node_count / max(1, len(vertical_runs))
                dense_candidate = min(avg_h, avg_v) >= 2.0
            else:
                dense_candidate = False

        h_paths = v_paths = []
        if dense_candidate:
            if model is None:
                from ExecutionCostModel import build_cost_model
                model = build_cost_model(dict(options or {}), image.size, image.size)
            h_paths = _axis_paths(comp_runs, 'horizontal', cancelled, max_points)
            v_paths = _axis_paths(comp_runs, 'vertical', cancelled, max_points, vertical_runs=vertical_runs)
            axis_candidates += int(bool(h_paths)) + int(bool(v_paths))

        very_dense = dense_candidate and node_count >= 64 and min(avg_h, avg_v) >= 3.0
        if very_dense and (h_paths or v_paths):
            choices = []
            if h_paths:
                choices.append(('horizontal', h_paths, _candidate_cost(h_paths, model)))
            if v_paths:
                choices.append(('vertical', v_paths, _candidate_cost(v_paths, model)))
            kind, best_paths, _best_cost = min(choices, key=lambda item: (item[2], len(item[1])))
            axis_components += 1
            dense_shortcuts += 1
            if kind == 'horizontal':
                horizontal_components_used += 1
            else:
                vertical_components_used += 1
            axis_output.extend(best_paths)
            continue

        contour_paths, raw_count, _traced_nodes = _trace_component(comp_runs, cancelled, max_points)
        contour_count += raw_count
        if not dense_candidate:
            contour_output.extend(contour_paths)
            continue

        contour_cost = _candidate_cost(contour_paths, model)
        choices = [('contour', contour_paths, contour_cost)]
        if h_paths:
            choices.append(('horizontal', h_paths, _candidate_cost(h_paths, model)))
        if v_paths:
            choices.append(('vertical', v_paths, _candidate_cost(v_paths, model)))
        kind, best_paths, best_cost = min(choices, key=lambda item: (item[2], len(item[1])))
        required_gain = max(.002, contour_cost * .015)
        if kind != 'contour' and best_cost <= contour_cost - required_gain:
            axis_components += 1
            modeled_saved += contour_cost - best_cost
            if kind == 'horizontal':
                horizontal_components_used += 1
            else:
                vertical_components_used += 1
            axis_output.extend(best_paths)
        else:
            contour_output.extend(contour_paths)

    contour_output.sort(key=lambda path: -_length(path))
    result = contour_output + axis_output
    return result, {
        'engine': ('Gartic contour + adaptive dense H/V' if axis_components else 'Gartic connected contours'),
        'ink_pixels': ink_pixels,
        'contours': contour_count,
        'execution_paths': len(result),
        'path_points': sum(map(len, result)),
        'priority': 'long contours first; dense H/V fallback second',
        'gap_bridges': 0,
        'dropped_components': 0,
        'axis_candidates_evaluated': axis_candidates,
        'axis_components': axis_components,
        'horizontal_axis_components': horizontal_components_used,
        'vertical_axis_components': vertical_components_used,
        'modeled_axis_seconds_saved': round(modeled_saved, 6),
        'dense_axis_shortcuts': dense_shortcuts,
        'axis_rule': 'lossless source-mask runs; 1.5% minimum modeled runtime gain',
    }
