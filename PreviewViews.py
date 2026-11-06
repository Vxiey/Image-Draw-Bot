"""One image selection contract for the visible preview and PNG export.

Returned images are borrowed from the app/plan. Exporters take their own
snapshot; changing a view never mutates the underlying planning images.
"""

VIEW_SPECS = (
    ('Original', 'original_canvas', 'original', 'original'),
    ('Quantized target', 'quantized_target_canvas', 'quantized_target', 'quantized-target'),
    ('Simulated final', 'result_canvas', 'simulated_final', 'simulated-final'),
    ('ΔE heatmap', 'delta_e_canvas', 'delta_e', 'delta-e-heatmap'),
    ('Accuracy error', 'accuracy_error_canvas', 'accuracy_error', 'accuracy-error'),
    ('Coverage map', 'coverage_canvas', 'coverage', 'coverage-map'),
    ('Detail zoom', 'detail_zoom_canvas', 'detail_zoom', 'detail-zoom'),
    ('Safety map', 'safety_canvas', 'safety', 'safety-map'),
    ('Debug overlay', 'safety_debug_canvas', 'safety_debug', 'debug-overlay'),
    ('Stroke plan', 'stroke_canvas', 'stroke', 'stroke-plan'),
    ('Fill regions', 'fill_canvas', 'fill', 'fill-regions'),
    ('Color map', 'color_canvas', 'color', 'color-map'),
)


def view_images(app):
    plan = app.plan if isinstance(getattr(app, 'plan', None), dict) else {}
    layers = plan.get('ui_previews') or {}
    enabled = lambda attr: bool(getattr(getattr(app, attr, None), 'get', lambda: True)())
    images = {name: layers.get(key) for name, _, key, _ in VIEW_SPECS}
    images['Original'] = getattr(app, 'original', None)
    images['Simulated final'] = ((layers.get('simulated_final') or plan.get('preview'))
                                 if enabled('preview_show_background') else layers.get('stroke'))
    if not enabled('preview_show_fill'):
        images['Fill regions'] = None
    if not enabled('preview_show_strokes'):
        images['Stroke plan'] = None
    return images


def selected_export_view(app):
    selector = getattr(app, 'preview_tabs', None)
    name = selector.get() if selector is not None else 'Simulated final'
    # Older layouts used this title for the same final drawing view.
    if name == 'Drawing preview':
        name = 'Simulated final'
    specs = {label: filename for label, _, _, filename in VIEW_SPECS}
    if name not in specs:
        raise ValueError('Choose a preview view before exporting.')
    image = view_images(app).get(name)
    if image is None:
        raise ValueError(f'{name} is not available. Enable this layer or build a preview first.')
    return name, image, f'ImageDrawBot-{specs[name]}.png'
