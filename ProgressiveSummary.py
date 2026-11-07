"""Constant-size presentation of renderer-supplied progressive metadata."""
from collections.abc import Mapping
from numbers import Integral


_LEGACY = (
    ('progressive_foundation_paths', 'forms'),
    ('progressive_contour_paths', 'contours'),
    ('progressive_detail_paths', 'details'),
)
_SKETCH = (
    ('progressive_sketch_paths', 'sketch'),
    ('progressive_color_fill_paths', 'color fill'),
    ('progressive_reoutline_paths', 're-outline'),
)
_PIXEL = (
    ('progressive_fill_paths', 'fill'),
    ('progressive_mid_detail_paths', 'mid detail'),
    ('progressive_fine_detail_paths', 'fine detail'),
    ('progressive_cleanup_paths', 'cleanup'),
)
_HYBRID = (
    ('progressive_foundation_paths', 'foundation'),
    ('progressive_contour_paths', 'structure'),
    ('progressive_detail_paths', 'detail'),
    ('progressive_correction_paths', 'correction'),
)


def progressive_summary(stats) -> str:
    """Describe known passes or the declared order without scanning geometry.

    Missing counters are unknown, not zero. An extended phase order (for
    example Pixel Accurate correction passes) takes precedence over a shorter
    known counter schema so the displayed sequence is never truncated.
    """
    if not isinstance(stats, Mapping) or not stats.get('progressive_enabled'):
        return ''
    raw_order = stats.get('progressive_phase_order')
    phases = (tuple(part.strip() for part in raw_order.replace('->', '→').split('→')
                    if part.strip()) if isinstance(raw_order, str) else ())
    order = ' → '.join(phases)
    mode = stats.get('progressive_mode')
    if mode == 'Sketch Fill':
        fields, expected = _SKETCH, ('sketch', 'color fill', 're-outline')
    elif mode == 'Adaptive Region Hybrid':
        fields, expected = _HYBRID, ('foundation', 'structure', 'detail', 'correction')
    elif mode == 'Deadline':
        fields, expected = (), ()
    elif any(key in stats for key, _label in _PIXEL):
        fields, expected = _PIXEL, ('fill', 'mid detail', 'fine detail', 'cleanup')
    elif mode in (None, '', 'Auto', 'On', 'Off'):
        fields, expected = _LEGACY, ('large forms', 'important contours', 'details')
    else:
        fields, expected = (), ()

    values = [stats.get(key) for key, _label in fields]
    complete = bool(fields) and all(isinstance(value, Integral)
                                   and not isinstance(value, bool) and value >= 0
                                   for value in values)
    known_order = not phases or tuple(part.casefold() for part in phases) == expected
    if complete and known_order:
        text = ' → '.join(f'{int(value):,} {label}'
                          for value, (_key, label) in zip(values, fields))
    else:
        text = order
    return f'Progressive: {text}' if text else ''
