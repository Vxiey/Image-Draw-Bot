"""Keep Paint's prepared image RGB palette attached to every rendering path."""
from __future__ import annotations


def active_picture_palette(app):
    """Return only a complete palette belonging to the currently loaded image."""
    if getattr(getattr(app, 'game', None), 'get', lambda: '')() != 'Microsoft Paint':
        return ()
    state = getattr(app, 'picture_custom_palette_state', None)
    if not isinstance(state, dict) or state.get('profile_key') != 'microsoft-paint':
        return ()
    if state.get('image_id') != id(getattr(app, 'original', None)):
        return ()
    colors = state.get('colors') or ()
    if not colors or state.get('prepared_count') != len(colors):
        return ()
    return validate_colors(colors)


def validate_colors(colors):
    if not 1 <= len(colors) <= 32:
        raise ValueError('Invalid picture palette color count.')
    result = []
    for color in colors:
        if len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
            raise ValueError('Invalid picture palette RGB channels.')
        result.append(tuple(color))
    return tuple(result)


def resolve_paint_plan_palette(original, fallback, options, cancelled=lambda: False):
    """Resolve one RGB order for the PixelMap, simulation and runtime selectors."""
    fallback = tuple(tuple(c) for c in fallback)
    paint = options.get('profile_name') == 'Microsoft Paint' or options.get('profile_key') == 'microsoft-paint'
    if not paint or any(options.get(k) for k in ('outline', 'paint_current_color', 'erase_mode')):
        return fallback, (), {}
    prepared = options.get('picture_palette_rgb') or ()
    if prepared and not options.get('exact_color_available'):
        raise ValueError('Picture palette needs Paint RGB controls. Recalibrate before building or drawing; standard colors were not substituted.')
    workflow = options.get('custom_color_workflow', 'Calibrated palette')
    if not prepared and (not options.get('exact_color_available') or workflow not in ('Adaptive exact (recommended)', 'Exact custom + palette fallback')):
        return fallback, (), {}
    if prepared:
        colors = validate_colors(prepared)
        source = 'prepared-picture-palette'
    else:
        from DynamicColors import resolve_exact_color_limit
        from PictureCustomPalette import build_picture_palette
        limit = resolve_exact_color_limit(options.get('exact_color_limit', 'Auto'),
                                          draw_quality=options.get('draw_quality', 'High likeness'), preview=False)
        palette = build_picture_palette(original, fallback, max_colors=limit,
                                        fidelity=options.get('color_fidelity', 'Faithful'),
                                        calibration_fingerprint=options.get('calibration_fingerprint', ''),
                                        cancelled=cancelled)
        colors = validate_colors(palette.colors)
        source = 'image-rgb-palette'
    from ColorFidelity import delta_e2000
    selectors = tuple({
        'kind': 'custom', 'rgb': rgb, 'source_rgb': rgb, 'prefer_numeric': True,
        'require_exact': True,
        'fallback_palette_index': min(range(len(fallback)), key=lambda i: delta_e2000(rgb, fallback[i])),
    } for rgb in colors)
    return colors, selectors, {'source': source, 'colors': len(colors), 'shared_preview_runtime': True}


def build_prepared_color_strokes(image, palette, selectors, options, *, skip_white, cancelled=lambda: False):
    """Use the same measured palette mapping as Pixel Accurate for color runs."""
    from types import SimpleNamespace
    from PixelAccuratePlanner import exact_palette_map, groups_from_pixel_map
    indices, drawable, _rgb, route = exact_palette_map(
        image, palette, color_rendering=options.get('color_rendering', 'Perceptual match'),
        color_fidelity='Exact', skip_white=skip_white,
        gpu_mode=options.get('gpu_mode', 'Auto'), gpu_vram=options.get('gpu_vram', 'Auto'),
        gpu_performance=options.get('gpu_performance', 'High throughput'), cancelled=cancelled)
    pixel_map = SimpleNamespace(height=image.height, palette_index=indices, drawable_mask=drawable)
    groups = groups_from_pixel_map(pixel_map, len(palette), lines=options.get('lines', True), cancelled=cancelled)
    return groups, palette, selectors, {
        'mode': 'prepared-picture-palette', 'color_rendering': options.get('color_rendering', 'Perceptual match'),
        'color_layers': 'Off', 'active_colors': sum(bool(g) for g in groups),
        'custom_exact_colors': sum(bool(g) for g in groups), 'palette_fallback_colors': 0,
        'exact_available': True, 'palette_route': route,
    }
