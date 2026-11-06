"""Preview-time CanvasGuard/Edge Behavior mirroring for Image Draw Bot v1.0.56.

Smart Preview Safety is deterministic and UI-only: it replays the same
CanvasGuard + EdgeBehavior path filtering used by execute_plan(), but in the
preview canvas coordinate space.  The generated preview therefore shows the
paths that can actually be drawn: clipped paths, skipped unsafe edge paths and
adaptive/outline edge-follow paths.  No AI/ML/OCR is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

from CanvasGuard import CanvasGuard, CanvasSafetyStop, normalize_canvas_anchors
from EdgeBehavior import apply_edge_behavior, resolve_edge_behavior
from SafetyDebugOverlay import record_debug_event, summarize_debug
from Precision import CanvasTransform

Point = tuple[int, int]
Path = tuple[Point, ...]


@dataclass
class PreviewSafetyPlan:
    groups: list[list[Path]]
    mode: str
    meta: dict = field(default_factory=dict)
    sequence: list[dict] | None = None

    def as_dict(self) -> dict:
        return deepcopy(self.meta)


def _preview_polygon_options(options: dict, fitted: Sequence[int | float]) -> tuple[object | None, str | None, tuple]:
    """Return polygon/space/anchors translated for preview-local coordinates."""
    polygon = options.get('canvas_polygon') or options.get('canvas_safe_polygon')
    space = options.get('canvas_polygon_space') or options.get('canvas_coordinate_space')
    anchor_space = options.get('canvas_anchor_space') or space
    anchors = options.get('canvas_anchors') or ()
    fitted_area = (0, 0, int(round(float(fitted[0]))), int(round(float(fitted[1]))))

    # Normalized and area-relative data is already independent of the real window.
    if polygon and str(space or 'auto').strip().lower() in ('normalized', 'relative', 'area', 'auto'):
        return polygon, space, normalize_canvas_anchors(anchors, area=fitted_area, coordinate_space=anchor_space)

    # Absolute/screen polygons can appear when a future detector writes screen
    # geometry.  Convert via target_area -> local normalized -> current fitted.
    target_area = options.get('_target_screen_area') or options.get('target_area') or options.get('_target_area')
    corners = options.get('corners')
    if (not isinstance(target_area, (list, tuple)) or len(target_area) != 4) and isinstance(corners, (list, tuple)) and len(corners) == 2:
        x0, y0 = corners[0]
        x1, y1 = corners[1]
        target_area = (min(x0, x1), min(y0, y1), abs(x1-x0), abs(y1-y0))
    preview_area = options.get('_preview_area') or fitted_area
    try:
        if polygon and target_area and str(space or '').strip().lower() in ('screen', 'absolute'):
            tx, ty, tw, th = [float(v) for v in target_area]
            fw, fh = float(fitted[0]), float(fitted[1])
            converted = []
            for raw in polygon:  # type: ignore[union-attr]
                sx, sy = float(raw[0]), float(raw[1])
                nx = 0.0 if tw <= 0 else (sx - tx) / tw
                ny = 0.0 if th <= 0 else (sy - ty) / th
                converted.append((nx * fw, ny * fh))
            converted_anchors = normalize_canvas_anchors(anchors, area=tuple(target_area), coordinate_space=anchor_space)
            # Re-normalize anchor centers from real target area into preview local area.
            anchor_dicts = []
            for anchor in converted_anchors:
                cx = 0.0 if tw <= 0 else (anchor.center[0] - tx) / tw * fw
                cy = 0.0 if th <= 0 else (anchor.center[1] - ty) / th * fh
                tip = None
                if anchor.tip is not None:
                    tip = ((anchor.tip[0] - tx) / tw * fw if tw > 0 else 0.0,
                           (anchor.tip[1] - ty) / th * fh if th > 0 else 0.0)
                anchor_dicts.append({'kind': anchor.kind, 'center': (cx, cy), 'tip': tip,
                                     'confidence': anchor.confidence, 'orientation': anchor.orientation})
            return tuple(converted), 'area', normalize_canvas_anchors(anchor_dicts, area=fitted_area, coordinate_space='area')
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    if anchors:
        try:
            return polygon, space, normalize_canvas_anchors(anchors, area=fitted_area, coordinate_space=anchor_space)
        except (TypeError, ValueError):
            return polygon, space, ()
    return polygon, space, ()


def preview_canvas_guard(options: dict, fitted: Sequence[int | float]) -> CanvasGuard:
    area = (0, 0, int(round(float(fitted[0]))), int(round(float(fitted[1]))))
    polygon, space, anchors = _preview_polygon_options(options, fitted)
    confidence = 1.0
    anchor_meta = options.get('canvas_anchor_meta')
    if isinstance(anchor_meta, dict):
        try:
            confidence = float(anchor_meta.get('confidence', 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
    return CanvasGuard.from_area_or_polygon(
        area,
        polygon=polygon,
        coordinate_space=space,
        brush_px=options.get('brush_px', 3),
        edge_margin_px=2,
        anchors=anchors,
        confidence=confidence,
    )


def build_preview_safety_plan(
    image_size: Sequence[int | float],
    fitted: Sequence[int | float],
    groups,
    execution_groups,
    options: dict,
    cancelled=lambda: False,
    *,
    execution_sequence=None,
) -> PreviewSafetyPlan:
    """Replay execution path safety in preview-local canvas coordinates."""
    if cancelled():
        raise InterruptedError()
    width, height = int(image_size[0]), int(image_size[1])
    guard = preview_canvas_guard(options, fitted)
    transform = CanvasTransform(width, height, fitted)
    edge_mode = resolve_edge_behavior(
        options.get('edge_behavior', 'Hard Clip'),
        profile_name=options.get('profile_name'),
        drawing_mode=options.get('drawing_mode'),
        outline=bool(options.get('outline')),
    )
    source_groups = execution_groups if execution_groups is not None else groups
    safe_groups: list[list[Path]] = [[] for _ in (source_groups or [])]
    safe_sequence = [] if execution_sequence is not None else None
    guards = {max(1, int(options.get('brush_px', 3))): guard}
    used_brushes = set()
    meta = {
        'active': True,
        'mode': edge_mode,
        'source': ('execution_sequence' if execution_sequence is not None else
                   'execution_groups' if execution_groups is not None else 'legacy_groups'),
        'paths_in': 0,
        'drawable_subpaths': 0,
        'output_points': 0,
        'hard_clip': 0,
        'hard_skip': 0,
        'adaptive_boundary': 0,
        'preserve_outline_boundary': 0,
        'safe_skip': 0,
        'source_outside_canvas': 0,
        'stopped': False,
        'canvas_guard': guard.model.as_dict(),
    }
    def source_paths():
        if execution_sequence is not None:
            from AdaptiveBrushEngine import brush_for_entry
            current_brush=max(1,int(options.get('brush_px',3)))
            for entry in execution_sequence:
                path=entry.get('path') or ()
                if not path:continue
                index = entry['color_index']
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(safe_groups):
                    raise ValueError('Invalid sequence palette index.')
                current_brush=brush_for_entry(entry,current_brush)
                yield index, path, current_brush
        else:
            for index, items in enumerate(source_groups or []):
                for item in items:
                    yield index, item, max(1, int(options.get('brush_px', 3)))

    for path_index, (color_index, item, physical_brush) in enumerate(source_paths(), 1):
        if cancelled():
            raise InterruptedError()
        meta['paths_in'] += 1
        if execution_groups is not None or execution_sequence is not None:
            raw_canvas_points = []
            for number, (x, y) in enumerate(item):
                if number % 512 == 0 and cancelled():
                    raise InterruptedError()
                raw_canvas_points.append(transform.point(x, y))
        else:
            x1, y1, x2, y2 = item
            raw_canvas_points = [transform.point(x1, y1), transform.point(x2, y2)]
        if physical_brush not in guards:
            guards[physical_brush] = preview_canvas_guard(dict(options, brush_px=physical_brush), fitted)
        used_brushes.add(physical_brush)
        try:
            result = apply_edge_behavior(
                guards[physical_brush], raw_canvas_points,
                behavior=edge_mode,
                profile_name=options.get('profile_name'),
                drawing_mode=options.get('drawing_mode'),
                outline=bool(options.get('outline')),
                context='preview stroke', cancelled=cancelled,
            )
        except CanvasSafetyStop as error:
            meta['source_outside_canvas'] += 1
            meta['stopped'] = True
            record_debug_event(meta, path_index, color_index, raw_canvas_points, exception=error)
            continue
        meta[result.strategy] = int(meta.get(result.strategy, 0)) + 1
        record_debug_event(meta, path_index, color_index, raw_canvas_points, result)
        for subpath in result.subpaths:
            if len(subpath) >= 1:
                path = tuple(subpath)
                safe_groups[color_index].append(path)
                if safe_sequence is not None:
                    safe_sequence.append({'color_index': color_index, 'path': path, 'brush_px': physical_brush})
                meta['drawable_subpaths'] += 1
                meta['output_points'] += len(subpath)
    skipped = int(meta.get('hard_skip', 0)) + int(meta.get('safe_skip', 0)) + int(meta.get('source_outside_canvas', 0))
    adapted = int(meta.get('adaptive_boundary', 0)) + int(meta.get('preserve_outline_boundary', 0))
    meta['skipped_total'] = skipped
    meta['adapted_total'] = adapted
    meta['changed_total'] = skipped + adapted
    meta['clipped_or_guarded'] = int(meta.get('hard_clip', 0)) + adapted
    meta['safety_debug'] = summarize_debug(meta)
    if safe_sequence is not None:
        meta['execution_sequence_rendered'] = True
        meta['canvas_guards_by_brush'] = {str(width): guards[width].model.as_dict() for width in sorted(used_brushes)}
        if used_brushes:
            meta['canvas_guard'] = guards[min(used_brushes)].model.as_dict()
    if cancelled():
        raise InterruptedError()
    return PreviewSafetyPlan(safe_groups, edge_mode, meta, safe_sequence)


def canvas_to_preview(point: Sequence[int | float], fitted: Sequence[int | float], preview_size: Sequence[int | float]) -> tuple[float, float]:
    fw, fh = max(1.0, float(fitted[0])), max(1.0, float(fitted[1]))
    pw, ph = max(1.0, float(preview_size[0])), max(1.0, float(preview_size[1]))
    return (float(point[0]) * pw / fw, float(point[1]) * ph / fh)


def draw_safe_paths(draw: ImageDraw.ImageDraw, safety_plan: PreviewSafetyPlan, fitted, preview_size, palette_rgb, brush: int, cancelled=lambda: False) -> tuple[int, int]:
    if cancelled():
        raise InterruptedError()
    path_count = 0
    dot_count = 0
    def render_paths():
        if safety_plan.sequence is not None:
            scale = float(preview_size[0]) / float(fitted[0])
            for entry in safety_plan.sequence:
                yield entry['color_index'], entry['path'], max(1, round(entry['brush_px'] * scale))
        else:
            for index, paths in enumerate(safety_plan.groups):
                for path in paths:
                    yield index, path, max(1, int(brush))

    for index, path, width in render_paths():
        color = palette_rgb[index] if index < len(palette_rgb) else (0, 0, 0)
        if cancelled():
            raise InterruptedError()
        if not path:
            continue
        mapped = []
        for number, p in enumerate(path):
            if number % 512 == 0 and cancelled():
                raise InterruptedError()
            mapped.append(canvas_to_preview(p, fitted, preview_size))
        def cap(point):
            x, y = point
            if width == 1:
                draw.point((x, y), fill=color)
            else:
                before, after = (width - 1) // 2, width // 2
                draw.ellipse((x - before, y - before, x + after, y + after), fill=color)
        if len(mapped) == 1:
            cap(mapped[0])
            dot_count += 1
            path_count += 1
            continue
        draw.line([coord for p in mapped for coord in p], fill=color, width=width, joint='curve')
        for p in (mapped[0], mapped[-1]):cap(p)
        path_count += 1
    if cancelled():raise InterruptedError()
    return path_count, dot_count


def draw_safe_sequence(draw, image_size, fitted, preview_size, sequence, palette_rgb,
                       options, cancelled=lambda: False):
    """Replay ordered passes with each entry's physical brush and CanvasGuard.

    Reuse a guard per brush width; paths stay in sequence order instead of being
    regrouped by colour, which would erase late recovered details.
    """
    plan = build_preview_safety_plan(image_size, fitted, [[] for _ in palette_rgb], None,
                                    options, cancelled, execution_sequence=sequence)
    return draw_safe_paths(draw, plan, fitted, preview_size, palette_rgb, 1, cancelled)


def render_preview_safety_map(source: Image.Image, preview_size, safety_plan: PreviewSafetyPlan, palette_rgb, brush: int, cancelled=lambda: False) -> Image.Image:
    if cancelled():
        raise InterruptedError()
    w, h = int(preview_size[0]), int(preview_size[1])
    base = Image.new('RGB', (max(1, w), max(1, h)), (15, 20, 29))
    draw = ImageDraw.Draw(base)
    guard_meta = safety_plan.meta.get('canvas_guard') or {}
    polygon = guard_meta.get('polygon') or ()
    safe_polygon = guard_meta.get('safe_polygon') or ()
    fitted = guard_meta.get('area') or (0, 0, w, h)
    if len(fitted) == 4:
        fitted_size = (max(1, int(fitted[2])), max(1, int(fitted[3])))
    else:
        fitted_size = preview_size

    def mapped_poly(poly):
        out = []
        for p in poly:
            try:
                out.append(canvas_to_preview(p, fitted_size, preview_size))
            except (TypeError, ValueError):
                continue
        return out

    outer = mapped_poly(polygon)
    inner = mapped_poly(safe_polygon)
    if len(outer) >= 2:
        draw.line([coord for p in outer + outer[:1] for coord in p], fill=(220, 87, 87), width=2)
    if len(inner) >= 2:
        draw.line([coord for p in inner + inner[:1] for coord in p], fill=(98, 226, 146), width=2)
    for other in (safety_plan.meta.get('canvas_guards_by_brush') or {}).values():
        other_polygon = other.get('safe_polygon') or ()
        if other_polygon == safe_polygon:
            continue
        boundary = mapped_poly(other_polygon)
        if len(boundary) >= 2:
            draw.line([coord for p in boundary + boundary[:1] for coord in p], fill=(73, 147, 106), width=1)

    # Draw the executable preview paths.  Use a slightly brighter visible palette
    # against the dark safety map without changing the actual drawing preview.
    visible_palette = []
    for rgb in palette_rgb:
        r, g, b = [max(0, min(255, int(v))) for v in rgb[:3]]
        if r * 0.299 + g * 0.587 + b * 0.114 < 95:
            r = min(255, r + 95); g = min(255, g + 95); b = min(255, b + 95)
        visible_palette.append((r, g, b))
    draw_safe_paths(draw, safety_plan, fitted_size, preview_size, tuple(visible_palette), max(1, min(4, int(brush))), cancelled=cancelled)

    skipped = int(safety_plan.meta.get('skipped_total', 0) or 0)
    adapted = int(safety_plan.meta.get('adapted_total', 0) or 0)
    text = f"Safety preview: {safety_plan.mode} · draw {int(safety_plan.meta.get('drawable_subpaths', 0))} · skip {skipped} · edge-follow {adapted}"
    if w >= 32 and h >= 32:
        draw.rectangle((8, 8, min(w - 8, 8 + len(text) * 6 + 14), 30), fill=(15, 20, 29))
        draw.text((14, 13), text, fill=(230, 237, 245))
    if safety_plan.meta.get('stopped') and w >= 32 and h >= 59:
        warn = 'Plan has source points outside the selected canvas polygon; real drawing will stop before input.'
        draw.rectangle((8, 34, min(w - 8, 8 + len(warn) * 6 + 14), 57), fill=(52, 24, 24))
        draw.text((14, 39), warn, fill=(255, 210, 210))
    return base
