"""Advanced colour planning for Image Draw Bot v1.0.8.

The module is intentionally pure: it does not read the screen, click UI controls,
or depend on Tk.  It improves palette drawings in three ways:

* perceptual palette matching instead of plain RGB distance;
* optional two-colour layer/stipple passes for colours that a small Paint palette
  cannot represent directly;
* custom-colour prioritisation when users calibrate extra Paint colours.
"""
from __future__ import annotations

from functools import lru_cache
from math import sqrt
from typing import Iterable, Sequence

from Colors import allColors
from PlanningRowTasks import read_only_rgba, RgbaRowTasks
from ColorFidelity import (COLOR_FIDELITY_MODES, validate_color_fidelity, palette_match_cost,
                           mapping_pair_metrics, finalize_mapping_stats, rgb_to_oklab)

COLOR_RENDERING_MODES = ("RGB nearest", "Perceptual match", "Layered color mix")
COLOR_LAYER_MODES = ("Off", "Light shading", "Dual-color mix", "Full color mix")
CUSTOM_COLOR_WORKFLOWS = ("Calibrated palette", "Custom colors first", "Custom colors only", "Exact custom + palette fallback", "Adaptive exact (recommended)")

_BAYER_4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def validate_color_rendering(mode: str) -> str:
    if mode not in COLOR_RENDERING_MODES:
        raise ValueError("Color rendering must be RGB nearest, Perceptual match or Layered color mix.")
    return mode


def validate_color_layers(mode: str) -> str:
    if mode not in COLOR_LAYER_MODES:
        raise ValueError("Color layers must be Off, Light shading, Dual-color mix or Full color mix.")
    return mode


def validate_custom_color_workflow(mode: str) -> str:
    if mode not in CUSTOM_COLOR_WORKFLOWS:
        raise ValueError("Custom color workflow must be Calibrated palette, Custom colors first, Custom colors only or Exact custom + palette fallback.")
    return mode


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _visible_rgb(r: int, g: int, b: int, alpha: int) -> tuple[int, int, int]:
    if alpha >= 255:
        return int(r), int(g), int(b)
    if alpha <= 0:
        return 255, 255, 255
    return tuple(_clamp_channel((v * alpha + 255 * (255 - alpha)) / 255.0) for v in (r, g, b))


def _rgb_to_space(rgb: Sequence[int]) -> tuple[float, float, float, float]:
    """Return OKLab L/a/b plus chroma for compatibility with old helpers."""
    lab=rgb_to_oklab(tuple(max(0,min(255,int(v))) for v in rgb[:3]))
    chroma=sqrt(lab[1]*lab[1]+lab[2]*lab[2])
    return lab[0],lab[1],lab[2],chroma


def _perceptual_distance2(a: Sequence[int], b: Sequence[int]) -> float:
    al,aa,ab,_ac=_rgb_to_space(a);bl,ba,bb,_bc=_rgb_to_space(b)
    return (al-bl)*(al-bl)+(aa-ba)*(aa-ba)+(ab-bb)*(ab-bb)

def _rgb_distance2(a: Sequence[int], b: Sequence[int]) -> int:
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3))


def _is_custom_color(index: int, palette_names: Sequence[str]) -> bool:
    if index >= 18:
        return True
    name = palette_names[index] if index < len(palette_names) else ""
    default_names = {
        "Black", "Gray", "Blue", "White", "Light Gray", "Light Blue", "Green",
        "Brown", "Light Brown", "Light Green", "Red", "Orange", "Ugly Brown",
        "Purple", "Skin Color", "Yellow", "Pink", "Light Pink",
    }
    return name not in default_names


def _candidate_indices(palette_names: Sequence[str], custom_mode: str, palette_size: int | None = None) -> list[int]:
    validate_custom_color_workflow(custom_mode)
    total = len(palette_names) if palette_size is None else palette_size
    if custom_mode != "Custom colors only":
        return list(range(total))
    custom = [i for i in range(total) if _is_custom_color(i, palette_names)]
    return custom or list(range(total))


def closest_palette_index(rgb: Sequence[int], *, color_rendering: str = "Perceptual match",
                          custom_mode: str = "Calibrated palette", color_fidelity: str = "Balanced") -> int:
    validate_color_rendering(color_rendering)
    palette = tuple(tuple(c.RGB) for c in allColors)
    names = tuple(c.name for c in allColors)
    validate_color_fidelity(color_fidelity)
    return _closest_palette_index_cached(tuple(map(int, rgb[:3])), palette, names, color_rendering, custom_mode, color_fidelity)


@lru_cache(maxsize=131072)
def _closest_palette_index_cached(rgb: tuple[int, int, int], palette: tuple[tuple[int, int, int], ...],
                                  names: tuple[str, ...], color_rendering: str, custom_mode: str,
                                  color_fidelity: str = "Balanced") -> int:
    if not palette:
        raise ValueError("No calibrated colours are available.")
    candidates = _candidate_indices(names, custom_mode, len(palette))
    validate_color_fidelity(color_fidelity)
    scores = [(palette_match_cost(rgb, palette[i], color_rendering=color_rendering, fidelity=color_fidelity), i) for i in candidates]
    best_score, best_index = min(scores, key=lambda item: (item[0], item[1]))
    if custom_mode == "Custom colors first":
        # If a custom swatch is visually almost as good, prefer it.  This lets a
        # user add skin/background custom colours without requiring exact source
        # matches or changing every old calibration.
        for score, index in sorted(scores, key=lambda item: (item[0], item[1])):
            if _is_custom_color(index, names) and score <= best_score * 1.06 + 0.0006:
                return index
    return best_index


def _mix(a: Sequence[int], b: Sequence[int], amount_b: float) -> tuple[int, int, int]:
    return tuple(_clamp_channel(a[i] * (1.0 - amount_b) + b[i] * amount_b) for i in range(3))


@lru_cache(maxsize=65536)
def _best_layer_cached(rgb: tuple[int, int, int], palette: tuple[tuple[int, int, int], ...], names: tuple[str, ...],
                       color_rendering: str, custom_mode: str, layer_mode: str,
                       color_fidelity: str = "Balanced") -> tuple[int, int | None, float, float]:
    """Return primary, secondary, secondary ratio, improvement."""
    if not palette:
        return 0, None, 0.0, 0.0
    validate_color_fidelity(color_fidelity)
    metric_mode = "Perceptual match" if color_rendering != "RGB nearest" else "RGB nearest"
    base = _closest_palette_index_cached(rgb, palette, names, metric_mode, custom_mode, color_fidelity)
    base_distance = palette_match_cost(rgb, palette[base], color_rendering=metric_mode, fidelity=color_fidelity)
    if layer_mode == "Off" or color_rendering == "RGB nearest" or len(palette) < 2:
        return base, None, 0.0, 0.0
    allowed = _candidate_indices(names, custom_mode, len(palette))
    max_candidates = 12 if layer_mode == "Light shading" else (18 if layer_mode == "Dual-color mix" else 26)
    ranked = sorted(allowed, key=lambda i: palette_match_cost(rgb, palette[i], color_rendering="Perceptual match", fidelity=color_fidelity))[:max_candidates]
    ratios = (0.25,) if layer_mode == "Light shading" else ((0.25, 0.50) if layer_mode == "Dual-color mix" else (0.20, 0.35, 0.50, 0.65))
    best = (base, None, 0.0, base_distance)
    # Different ordered pairs/ratios can produce byte-identical mixed RGB.
    # Keep their original order and strict tie rule, but score each resulting
    # colour only once for this source. At most 26 * 25 * 4 entries are possible;
    # no table entries survive in the cached winner or a failing traceback.
    mixed_costs = {}
    try:
        for primary in ranked:
            for secondary in ranked:
                if primary == secondary:
                    continue
                for ratio in ratios:
                    mixed = _mix(palette[primary], palette[secondary], ratio)
                    distance = mixed_costs.get(mixed)
                    if distance is None:
                        distance = palette_match_cost(rgb, mixed, color_rendering="Perceptual match", fidelity=color_fidelity)
                        mixed_costs[mixed] = distance
                    if distance < best[3]:
                        best = (primary, secondary, ratio, distance)
    finally:
        mixed_costs.clear()
    improvement = max(0.0, (base_distance - best[3]) / max(base_distance, 1e-9))
    threshold = {"Light shading": 0.20, "Dual-color mix": 0.14, "Full color mix": 0.10}[layer_mode]
    if best[1] is None or improvement < threshold:
        return base, None, 0.0, 0.0
    return best[0], best[1], best[2], improvement


def best_layer_for_rgb(rgb: Sequence[int], *, color_rendering: str = "Layered color mix",
                       color_layers: str = "Dual-color mix",
                       custom_mode: str = "Calibrated palette", color_fidelity: str = "Balanced") -> tuple[int, int | None, float, float]:
    validate_color_rendering(color_rendering); validate_color_layers(color_layers); validate_custom_color_workflow(custom_mode); validate_color_fidelity(color_fidelity)
    palette = tuple(tuple(c.RGB) for c in allColors)
    names = tuple(c.name for c in allColors)
    return _best_layer_cached(tuple(map(int, rgb[:3])), palette, names, color_rendering, custom_mode, color_layers, color_fidelity)


def _should_overlay(x: int, y: int, ratio: float, strength: str) -> bool:
    threshold = max(1, min(15, int(round(ratio * 16))))
    if strength == "Light shading":
        threshold = min(threshold, 5)
    return _BAYER_4[y & 3][x & 3] < threshold


def _stroke_weight(stroke: tuple[int, int, int, int]) -> int:
    x1, y1, x2, y2 = stroke
    return max(1, abs(int(x2) - int(x1)) + abs(int(y2) - int(y1)) + 1)


def _add_run(groups: list[list[tuple[int, int, int, int]]], index: int | None, start: int | None, y: int, end_x: int):
    if index is not None and start is not None and end_x >= start:
        groups[index].append((start, y, end_x, y))



def _merge_color_chunks(results, color_count: int):
    groups = [[] for _ in range(color_count)]
    overlay_groups = [[] for _ in range(color_count)]
    layered_pixels = 0
    unique_base = set()
    unique_overlay = set()
    white_skipped = 0
    for base, overlay, meta in results:
        for index, strokes in enumerate(base):
            groups[index].extend(strokes)
        for index, strokes in enumerate(overlay):
            overlay_groups[index].extend(strokes)
        layered_pixels += int(meta.get("layered_pixels", 0))
        unique_base.update(meta.get("unique_base", ()))
        unique_overlay.update(meta.get("unique_overlay", ()))
        white_skipped += int(meta.get("white_skipped", 0))
    return groups, overlay_groups, layered_pixels, unique_base, unique_overlay, white_skipped


def _color_rows_worker(args):
    (y0, width, raw, lines, skip_white, color_rendering, color_layers,
     custom_color_workflow, color_fidelity, palette, names) = args
    groups = [[] for _ in palette]
    overlay_groups = [[] for _ in palette]
    layered_pixels = 0
    unique_base = set()
    unique_overlay = set()
    white_skipped = 0
    height = len(raw) // max(1, width * 4)
    for local_y in range(height):
        y = y0 + local_y
        previous = None
        start = None
        overlay_previous = None
        overlay_start = None
        row_offset = local_y * width * 4
        for x in range(width + 1):
            base_index = None
            overlay_index = None
            if x < width:
                offset = row_offset + x * 4
                r, g, b, alpha = raw[offset], raw[offset + 1], raw[offset + 2], raw[offset + 3]
                source_rgb = _visible_rgb(r, g, b, alpha)
                if alpha <= 0 or (skip_white and min(source_rgb) >= 245):
                    white_skipped += 1
                else:
                    if color_rendering == "Layered color mix" or color_layers != "Off":
                        base_index, secondary, ratio, _improvement = _best_layer_cached(
                            tuple(map(int, source_rgb[:3])), palette, names, color_rendering,
                            custom_color_workflow, color_layers, color_fidelity)
                        if secondary is not None and _should_overlay(x, y, ratio, color_layers):
                            overlay_index = secondary
                            # The public plan is executed by colour, not in a
                            # global base-then-overlay order. Assign each Bayer
                            # pixel to exactly one colour so a later base batch
                            # cannot erase an earlier secondary stipple.
                            base_index = None
                    else:
                        base_index = _closest_palette_index_cached(
                            tuple(map(int, source_rgb[:3])), palette, names,
                            color_rendering, custom_color_workflow, color_fidelity)
                    if base_index is not None:
                        unique_base.add(base_index)
                    if overlay_index is not None:
                        unique_overlay.add(overlay_index); layered_pixels += 1
            if not lines:
                if base_index is not None:
                    groups[base_index].append((x, y, x, y))
                if overlay_index is not None:
                    overlay_groups[overlay_index].append((x, y, x, y))
            else:
                if base_index != previous:
                    _add_run(groups, previous, start, y, x - 1)
                    previous, start = base_index, x if base_index is not None else None
                if overlay_index != overlay_previous:
                    _add_run(overlay_groups, overlay_previous, overlay_start, y, x - 1)
                    overlay_previous, overlay_start = overlay_index, x if overlay_index is not None else None
    return groups, overlay_groups, {
        "layered_pixels": layered_pixels,
        "unique_base": tuple(sorted(i for i in unique_base if i is not None)),
        "unique_overlay": tuple(sorted(i for i in unique_overlay if i is not None)),
        "white_skipped": white_skipped,
    }




def _groups_from_index_map(index_map, drawable_mask, palette_count: int, *, lines: bool, cancelled=lambda: False):
    groups = [[] for _ in range(palette_count)]
    height, width = index_map.shape
    unique_base = set()
    white_skipped = 0
    for y in range(height):
        if cancelled():
            raise InterruptedError()
        previous = None
        start = None
        for x in range(width + 1):
            color = None
            if x < width:
                if bool(drawable_mask[y, x]):
                    color = int(index_map[y, x])
                    unique_base.add(color)
                else:
                    white_skipped += 1
            if not lines:
                if color is not None:
                    groups[color].append((x, y, x, y))
            elif color != previous:
                _add_run(groups, previous, start, y, x - 1)
                previous, start = color, x if color is not None else None
    return groups, unique_base, white_skipped


def _gpu_color_strokes(rgb_image, *, lines, skip_white, color_rendering, color_layers,
                       custom_color_workflow, color_fidelity, gpu_mode, gpu_vram, gpu_performance,
                       cancelled=lambda: False):
    if color_layers != "Off" or color_rendering == "Layered color mix":
        return None
    # Step 23: Auto routes this real palette workload through the fastest
    # Step-22-measured CUDA/OpenCL/CPU backend while preserving Step 2 fidelity.
    if gpu_mode == "CPU":
        return None
    try:
        from UniversalGpuAcceleration import palette_indices_rgba, select_route
        # Preserve the established multi-core CPU planner when Step 22 measured
        # CPU as the best backend. Universal routing should replace that path
        # only when a verified GPU route actually wins for this image size.
        planned_route = select_route("palette_match", pixels=rgb_image.width * rgb_image.height, gpu_mode=gpu_mode)
        if not planned_route.accelerated:
            return None
        palette = tuple(tuple(c.RGB) for c in allColors)
        names = tuple(c.name for c in allColors)
        candidates = [i for i in _candidate_indices(names, custom_color_workflow) if i < len(palette)] or list(range(len(palette)))
        custom_flags = [_is_custom_color(i, names) for i in range(len(palette))]
        result, route = palette_indices_rgba(
            rgb_image, palette, candidates, custom_flags,
            color_rendering=color_rendering, custom_mode=custom_color_workflow,
            color_fidelity=color_fidelity, skip_white=skip_white, gpu_mode=gpu_mode,
            cancelled=cancelled)
        index_map, drawable_mask = result
        groups, unique_base, white_skipped = _groups_from_index_map(
            index_map, drawable_mask, len(palette), lines=lines, cancelled=cancelled)
        backend_id=str(route.get("backend_id") or "cpu:numpy")
        backend="universal-" + ("cpu" if backend_id=="cpu:numpy" else backend_id.split(':',1)[0])
        return groups, [[] for _ in palette], 0, tuple(sorted(unique_base)), tuple(), white_skipped, backend, 1, dict(route)
    except InterruptedError:
        raise
    except Exception:
        return None

def _parallel_color_strokes(rgb_image, *, lines, skip_white, color_rendering, color_layers,
                            custom_color_workflow, color_fidelity, cancelled, cpu_workers, cpu_engine,
                            ram_budget_mb, preview_plan):
    try:
        from ResourceAllocation import choose_parallel_backend, parallel_map, row_chunk_ranges
        workers = max(1, int(cpu_workers or 1))
        ram_mb = max(128, int(ram_budget_mb or 512))
        backend = choose_parallel_backend(cpu_engine or "Auto", width=rgb_image.width,
                                          height=rgb_image.height, workers=workers,
                                          ram_budget_mb=ram_mb, preview=bool(preview_plan))
        if backend == "serial":
            return None
        palette = tuple(tuple(c.RGB) for c in allColors)
        names = tuple(c.name for c in allColors)
        ranges = row_chunk_ranges(rgb_image.height, rgb_image.width, workers=workers,
                                  ram_budget_mb=ram_mb,
                                  bytes_per_pixel=96 if (color_rendering == "Layered color mix" or color_layers != "Off") else 40,
                                  min_rows=8, max_rows=192)
        if len(ranges) <= 1:
            return None
        tasks = RgbaRowTasks(rgb_image, ranges,
            (bool(lines), bool(skip_white), color_rendering, color_layers,
             custom_color_workflow, color_fidelity, palette, names), cancelled=cancelled)
        chunks = parallel_map(_color_rows_worker, tasks, backend=backend, workers=workers, cancelled=cancelled)
        if cancelled():
            return None
        return _merge_color_chunks(chunks, len(palette)) + (backend, len(tasks))
    except InterruptedError:
        raise
    except Exception:
        # Fall back to the old serial implementation. Planning must remain safe
        # even on Python installations where process spawning is restricted.
        return None


def build_color_strokes(image, *, lines: bool = True, skip_white: bool = True,
                        color_rendering: str = "Perceptual match",
                        color_layers: str = "Off",
                        custom_color_workflow: str = "Calibrated palette",
                        color_fidelity: str = "Balanced",
                        cancelled=lambda: False, cpu_workers: int = 1,
                        cpu_engine: str = "Auto", ram_budget_mb: int = 512,
                        preview_plan: bool = False, gpu_mode: str = "CPU",
                        gpu_vram: str = "Auto", gpu_performance: str = "Balanced"):
    """Build palette stroke groups and return ``(groups, metadata)``.

    ``color_layers`` adds a second stipple/short-run layer only when a mixed
    pair is perceptually closer than any single calibrated colour.  v1.0.13 can
    split large images over CPU workers; serial planning remains the fallback.
    """
    validate_color_rendering(color_rendering)
    validate_color_layers(color_layers)
    validate_custom_color_workflow(custom_color_workflow)
    validate_color_fidelity(color_fidelity)
    if cancelled():
        return None, {"cancelled": True}
    if color_rendering == "Layered color mix" and color_layers == "Off":
        color_layers = "Dual-color mix"
    with read_only_rgba(image) as rgb_image:
        palette = tuple(tuple(c.RGB) for c in allColors)
        names = tuple(c.name for c in allColors)

        gpu_meta = None
        try:
            parallel = _gpu_color_strokes(
                rgb_image, lines=lines, skip_white=skip_white,
                color_rendering=color_rendering, color_layers=color_layers,
                custom_color_workflow=custom_color_workflow, color_fidelity=color_fidelity, gpu_mode=gpu_mode,
                gpu_vram=gpu_vram, gpu_performance=gpu_performance, cancelled=cancelled)
        except InterruptedError:
            return None, {"cancelled": True}
        if parallel is None and cpu_workers and int(cpu_workers) > 1:
            parallel = _parallel_color_strokes(
                rgb_image, lines=lines, skip_white=skip_white,
                color_rendering=color_rendering, color_layers=color_layers,
                custom_color_workflow=custom_color_workflow, color_fidelity=color_fidelity, cancelled=cancelled,
                cpu_workers=cpu_workers, cpu_engine=cpu_engine,
                ram_budget_mb=ram_budget_mb, preview_plan=preview_plan)
        if parallel is not None:
            if len(parallel) == 9:
                groups, overlay_groups, layered_pixels, unique_base, unique_overlay, white_skipped, backend, chunks, gpu_meta = parallel
            else:
                groups, overlay_groups, layered_pixels, unique_base, unique_overlay, white_skipped, backend, chunks = parallel
        else:
            pixels = rgb_image.load()
            groups = [[] for _ in palette]
            overlay_groups = [[] for _ in palette]
            layered_pixels = 0
            unique_base = set()
            unique_overlay = set()
            white_skipped = 0
            backend = "serial"
            chunks = 1
            for y in range(rgb_image.height):
                if cancelled():
                    return None, {"cancelled": True}
                previous = None
                start = None
                overlay_previous = None
                overlay_start = None
                for x in range(rgb_image.width + 1):
                    base_index = None
                    overlay_index = None
                    if x < rgb_image.width:
                        r, g, b, alpha = pixels[x, y]
                        source_rgb = _visible_rgb(r, g, b, alpha)
                        if alpha <= 0 or (skip_white and min(source_rgb) >= 245):
                            white_skipped += 1
                        else:
                            if color_rendering == "Layered color mix" or color_layers != "Off":
                                base_index, secondary, ratio, _improvement = _best_layer_cached(
                                    source_rgb, palette, names, color_rendering,
                                    custom_color_workflow, color_layers, color_fidelity)
                                if secondary is not None and _should_overlay(x, y, ratio, color_layers):
                                    overlay_index = secondary
                                    base_index = None
                            else:
                                base_index = _closest_palette_index_cached(
                                    source_rgb, palette, names, color_rendering,
                                    custom_color_workflow, color_fidelity)
                            if base_index is not None:
                                unique_base.add(base_index)
                            if overlay_index is not None:
                                unique_overlay.add(overlay_index); layered_pixels += 1
                    if not lines:
                        if base_index is not None:
                            groups[base_index].append((x, y, x, y))
                        if overlay_index is not None:
                            overlay_groups[overlay_index].append((x, y, x, y))
                    else:
                        if base_index != previous:
                            _add_run(groups, previous, start, y, x - 1)
                            previous, start = base_index, x if base_index is not None else None
                        if overlay_index != overlay_previous:
                            _add_run(overlay_groups, overlay_previous, overlay_start, y, x - 1)
                            overlay_previous, overlay_start = overlay_index, x if overlay_index is not None else None
        if cancelled():
            return None, {"cancelled": True}
        for index, strokes in enumerate(overlay_groups):
            groups[index].extend(strokes)
        meta = {
            "color_rendering": color_rendering,
            "color_layers": color_layers,
            "custom_color_workflow": custom_color_workflow,
            "color_fidelity": color_fidelity,
            "layered_pixels": layered_pixels,
            "base_colors": len(unique_base),
            "overlay_colors": len(unique_overlay),
            "white_skipped": white_skipped,
            "stroke_weight": sum(_stroke_weight(stroke) for group in groups for stroke in group),
            "cpu_backend": backend,
            "cpu_chunks": chunks,
            "gpu_color_meta": gpu_meta or {},
        }
        try:
            meta["color_fidelity_diagnostics"]=_sample_mapping_diagnostics(
                rgb_image,color_rendering=color_rendering,custom_color_workflow=custom_color_workflow,
                color_fidelity=color_fidelity,skip_white=skip_white,color_layers=color_layers,
                palette=palette,names=names)
        except Exception:
            meta["color_fidelity_diagnostics"]={"dark_bias_detected":False}
        if cancelled():
            return None, {"cancelled": True}
        return groups, meta



def _layered_sample_coordinates(width: int, height: int, sample_limit: int):
    """Sample whole Bayer cells, so a regular stride cannot select one phase.

    Small images are measured completely. Larger images use evenly spaced
    four-by-four cells, including both ends of the image. Partial edge cells
    contribute only their real pixels; the total work stays within the budget.
    """
    limit = max(0, int(sample_limit))
    if width <= 0 or height <= 0 or limit <= 0:
        return
    if width * height <= limit:
        for y in range(height):
            for x in range(width):
                yield x, y
        return
    columns = (width + 3) // 4
    cell_count = columns * ((height + 3) // 4)
    cell_pixels = min(4, width) * min(4, height)
    selected = min(cell_count, max(1, limit // cell_pixels))
    remaining = limit
    for slot in range(selected):
        cell = ((cell_count - 1) // 2 if selected == 1
                else slot * (cell_count - 1) // (selected - 1))
        left, top = (cell % columns) * 4, (cell // columns) * 4
        for y in range(top, min(top + 4, height)):
            for x in range(left, min(left + 4, width)):
                yield x, y
                remaining -= 1
                if remaining <= 0:
                    return


def _sample_mapping_diagnostics(rgb_image, *, color_rendering: str, custom_color_workflow: str,
                                color_fidelity: str, skip_white: bool, sample_limit: int = 768,
                                color_layers: str = "Off", palette=None, names=None) -> dict:
    """Measure the palette pixels the planner will actually emit, not a mix RGB."""
    palette = tuple(tuple(c.RGB) for c in allColors) if palette is None else palette
    names = tuple(c.name for c in allColors) if names is None else names
    if not palette:
        return finalize_mapping_stats({"mapped_pixels": 0})
    if color_rendering == "Layered color mix" and color_layers == "Off":
        color_layers = "Dual-color mix"
    layered = color_rendering != "RGB nearest" and color_layers != "Off"
    pixels = rgb_image.load(); total=max(1, rgb_image.width * rgb_image.height)
    stride=max(1, int((total / max(1, int(sample_limit))) ** 0.5))
    coordinates = (_layered_sample_coordinates(rgb_image.width, rgb_image.height, sample_limit)
                   if layered else ((x, y) for y in range(0, rgb_image.height, stride)
                                    for x in range(0, rgb_image.width, stride)))
    stats={
        "mapped_pixels":0,"source_lightness_sum":0.0,"mapped_lightness_sum":0.0,
        "source_saturation_sum":0.0,"mapped_saturation_sum":0.0,
        "source_luminance_sum":0.0,"mapped_luminance_sum":0.0,
        "delta_e_sum":0.0,"delta_e_max":0.0,"delta_e2000_sum":0.0,"delta_e2000_max":0.0,
        "delta_e_oklab_sum":0.0,"delta_e_oklab_max":0.0,"hue_error_sum":0.0,
    }
    for x, y in coordinates:
        r,g,b,a=pixels[x,y]; src=_visible_rgb(r,g,b,a)
        if a <= 0 or (skip_white and min(src) >= 245):
            continue
        if layered:
            idx, secondary, ratio, _improvement = _best_layer_cached(
                src, palette, names, color_rendering, custom_color_workflow,
                color_layers, color_fidelity)
            if secondary is not None and _should_overlay(x, y, ratio, color_layers):
                idx = secondary
        else:
            idx=_closest_palette_index_cached(src,palette,names,color_rendering,custom_color_workflow,color_fidelity)
        pair=mapping_pair_metrics(src,palette[idx])
        stats["mapped_pixels"]+=1
        stats["source_lightness_sum"]+=pair["source_lightness"];stats["mapped_lightness_sum"]+=pair["mapped_lightness"]
        stats["source_saturation_sum"]+=pair["source_saturation"];stats["mapped_saturation_sum"]+=pair["mapped_saturation"]
        stats["source_luminance_sum"]+=pair["source_luminance"];stats["mapped_luminance_sum"]+=pair["mapped_luminance"]
        stats["delta_e_sum"]+=pair["delta_e76"];stats["delta_e_max"]=max(stats["delta_e_max"],pair["delta_e76"])
        stats["delta_e2000_sum"]+=pair["delta_e2000"];stats["delta_e2000_max"]=max(stats["delta_e2000_max"],pair["delta_e2000"])
        stats["delta_e_oklab_sum"]+=pair["delta_e_oklab"];stats["delta_e_oklab_max"]=max(stats["delta_e_oklab_max"],pair["delta_e_oklab"])
        stats["hue_error_sum"]+=pair.get("hue_error",0.0)
        if stats["mapped_pixels"] >= sample_limit:
            return finalize_mapping_stats(stats)
    return finalize_mapping_stats(stats)

def suggested_color_workflow(calibrated_count: int, image_mode: str = "RGB") -> str:
    """Small helper for UI/docs/tests."""
    if calibrated_count >= 32:
        return "Layered color mix with Custom colors first"
    if calibrated_count >= 24:
        return "Perceptual match with Custom colors first"
    return "Perceptual match with Calibrated palette"
