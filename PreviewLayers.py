"""Additional lightweight preview layers generated in the planning worker."""
from __future__ import annotations
from contextlib import ExitStack, closing
from PIL import Image, ImageDraw
import math


def _canvas_to_preview(point, fitted, preview_size):
    fw, fh = max(1.0, float(fitted[0])), max(1.0, float(fitted[1]))
    pw, ph = max(1.0, float(preview_size[0])), max(1.0, float(preview_size[1]))
    return (float(point[0]) * pw / fw, float(point[1]) * ph / fh)


def _visible(rgb):
    r, g, b = [max(0, min(255, int(v))) for v in rgb[:3]]
    lum = (r * 299 + g * 587 + b * 114) / 1000
    if lum < 80:
        # Keep hue but lift very dark strokes so they remain visible on the dark map.
        factor = (110 - lum) / 175
        r = round(r + (255 - r) * factor)
        g = round(g + (255 - g) * factor)
        b = round(b + (255 - b) * factor)
    return (r, g, b)


def build_auxiliary_previews(source, size, groups, palette_rgb, point, brush, options, cancelled=lambda: False,
                             *, include_color_map=True):
    """Build owned UI layers and release every incomplete/temporary bitmap.

    Final planning supplies its executed color map separately, so it can omit
    the source-color copy. The default retains the standalone helper's layers.
    The source image is borrowed and is never closed or changed here.
    """
    retained = set()
    with ExitStack() as owned:
        def keep(image):
            owned.callback(lambda: image.close() if id(image) not in retained else None)
            return image

        def draw(image):
            handle = ImageDraw.Draw(image)
            def release():
                # ImageDraw owns native core references independently of the
                # Image wrapper. A retained error traceback must not keep those
                # pixels alive after Image.close() has cleared the wrapper.
                handle.draw = handle.im = handle._image = None
            owned.callback(release)
            return handle

        result = _build_auxiliary_previews(source, size, groups, palette_rgb, point,
            brush, options, cancelled, include_color_map=include_color_map, own=keep, draw=draw)
        retained.update(map(id, result.values()))
        return result


def _build_auxiliary_previews(source, size, groups, palette_rgb, point, brush, options, cancelled,
                              *, include_color_map, own, draw):
    """Create Stroke plan, Fill regions and Color map images.

    Called from the background planning worker; no Tk or screen APIs are used.
    """
    w, h = map(int, size)
    if w < 1 or h < 1:
        raise ValueError("Preview size must be positive.")
    if cancelled():
        raise InterruptedError()

    stroke = own(Image.new("RGB", (w, h), (15, 20, 29)))
    sd = draw(stroke)
    line_width = max(1, min(4, int(brush)))
    safety_groups = options.get("_preview_safety_groups") or None
    if safety_groups:
        safety_meta = options.get("preview_safety_meta") or {}
        guard_meta = safety_meta.get("canvas_guard") or {}
        area = guard_meta.get("area") or (0, 0, w, h)
        fitted_local = safety_meta.get('fitted_size') or ((int(area[2]), int(area[3])) if isinstance(area, (tuple, list)) and len(area) == 4 else (w, h))
        image_offset = safety_meta.get('image_offset') or (0, 0)
        fitted_width, fitted_height = max(1.0, float(fitted_local[0])), max(1.0, float(fitted_local[1]))
        def mapped(point):
            # Keep the original operation order: multiplying by a precomputed
            # ratio can put an exact pixel boundary just below its integer.
            return ((float(point[0])-image_offset[0]) * w / fitted_width,
                    (float(point[1])-image_offset[1]) * h / fitted_height)
        total_segments = sum(max(1, len(path) - 1) for paths in safety_groups for path in paths)
        max_segments = int(options.get("_preview_stroke_map_limit", 12000)) if options.get("_preview_plan") else 24000
        stride = 1 if options.get('_full_detail_preview') else max(1, math.ceil(total_segments / max(1, max_segments)))
        counter = 0
        for index, paths in enumerate(safety_groups):
            if not paths:
                continue
            color = _visible(palette_rgb[index] if index < len(palette_rgb) else (225, 235, 245))
            for path in paths:
                if cancelled():
                    raise InterruptedError()
                if len(path) == 1:
                    counter += 1
                    if counter % stride:
                        continue
                    x, y = mapped(path[0])
                    sd.ellipse((x-line_width, y-line_width, x+line_width, y+line_width), fill=color)
                    continue
                for offset in range(1, len(path)):
                    counter += 1
                    if counter % 256 == 0 and cancelled():
                        raise InterruptedError()
                    if counter % stride:
                        continue
                    a, b = mapped(path[offset - 1]), mapped(path[offset])
                    sd.line((*a, *b), fill=color, width=line_width)
    else:
        total_segments = sum(len(strokes) for strokes in groups)
        # The stroke-map tab is a UI aid, not the executable drawing plan.  Sampling
        # very large plans keeps live previews responsive and prevents shutdown from
        # waiting behind tens of thousands of Canvas-like drawing operations.
        max_segments = int(options.get("_preview_stroke_map_limit", 12000)) if options.get("_preview_plan") else 24000
        stride = 1 if options.get('_full_detail_preview') else max(1, math.ceil(total_segments / max(1, max_segments)))
        counter = 0
        for index, strokes in enumerate(groups):
            if not strokes:
                continue
            color = _visible(palette_rgb[index] if index < len(palette_rgb) else (225, 235, 245))
            for x1, y1, x2, y2 in strokes:
                if cancelled():
                    raise InterruptedError()
                counter += 1
                if counter % stride:
                    continue
                p1, p2 = point(x1, y1), point(x2, y2)
                sd.line((*p1, *p2), fill=color, width=line_width)

    if cancelled():
        raise InterruptedError()
    def bounded_source(resampling):
        with ExitStack() as temporary:
            resized = (source if source.size == (w, h) else
                       temporary.enter_context(closing(source.resize((w, h), resampling))))
            small = temporary.enter_context(closing(resized.convert("RGBA")))
            background = temporary.enter_context(closing(Image.new("RGBA", (w, h), "white")))
            background.alpha_composite(small)
            return own(background.convert("RGB"))
    src = bounded_source(Image.Resampling.LANCZOS)
    # v1.0.120: preview layers must preserve source sRGB tone. The old 0.68
    # brightness multiplier made the Fill Regions preview look artificially
    # dark/dull even when the executable palette plan was correct.
    fill = own(src.convert("RGBA"))
    if not (include_color_map and source.size == (w, h)):
        src.close()
    overlay = own(Image.new("RGBA", (w, h), (0, 0, 0, 0)))
    od = draw(overlay)
    fill_meta = options.get("background_fill_plan") or {}
    if fill_meta.get("enabled") and w >= 3 and h >= 3:
        color_index = fill_meta.get("color_index")
        base = palette_rgb[int(color_index)] if isinstance(color_index, int) and 0 <= color_index < len(palette_rgb) else (90, 180, 145)
        od.rectangle((1, 1, w - 2, h - 2), outline=(*_visible(base), 230), width=max(2, line_width))
    for region in options.get("fill_regions", []) or []:
        if cancelled():
            raise InterruptedError()
        try:
            x0, y0, x1, y1 = map(int, region["bbox"])
            p0, p1 = point(x0, y0), point(x1, y1)
            color_index = int(region.get("color_index", -1))
            rgb = palette_rgb[color_index] if 0 <= color_index < len(palette_rgb) else (152, 237, 206)
            od.rectangle((p0[0], p0[1], p1[0], p1[1]), fill=(*rgb, 68), outline=(*_visible(rgb), 240), width=max(2, line_width))
        except (KeyError, TypeError, ValueError, IndexError, OverflowError):
            continue
    with closing(Image.alpha_composite(fill, overlay)) as composite:
        completed_fill = own(composite.convert("RGB"))
    fill.close()
    overlay.close()

    result = {"stroke": stroke, "fill": completed_fill}
    if include_color_map:
        result["color"] = src if source.size == (w, h) else bounded_source(Image.Resampling.NEAREST)
    if cancelled():
        raise InterruptedError()
    return result
