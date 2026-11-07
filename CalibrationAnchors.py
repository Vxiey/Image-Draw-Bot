"""Coordinate anchoring for Paint/UI calibration points.

Calibration screen coordinates are only valid while a window remains at the
same desktop position.  Store the target client rectangle at calibration time,
then translate points when the same-size window is moved.  A resized client is
rejected before native input because Paint can reflow its toolbar/palette.
"""
from __future__ import annotations

_LONG_MIN = -(2 ** 31)
_LONG_MAX = 2 ** 31 - 1

def _coordinate(value):
    return type(value) is int and _LONG_MIN <= value <= _LONG_MAX

def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(_coordinate(v) for v in value):
        raise ValueError('Invalid calibrated screen position. Recalibrate.')
    return tuple(value)

def _rect(value, label='client rectangle'):
    if not isinstance(value, (list, tuple)) or len(value) != 4 or not all(_coordinate(v) for v in value):
        raise ValueError(f'Invalid calibration {label}. Recalibrate.')
    left, top, right, bottom = value
    if right <= left or bottom <= top:
        raise ValueError(f'Invalid calibration {label}. Recalibrate.')
    return (left, top, right, bottom)


def make_anchor(client_rect):
    rect = _rect(client_rect)
    return {'version': 1, 'client_rect': list(rect)}


def validate_anchor(anchor):
    if not isinstance(anchor, dict) or type(anchor.get('version')) is not int or anchor['version'] != 1:
        raise ValueError('Calibration is not anchored to a target window. Recalibrate.')
    rect = _rect(anchor.get('client_rect'))
    return {'version': 1, 'client_rect': list(rect)}


def client_size(client_rect):
    left, top, right, bottom = _rect(client_rect)
    return (right-left, bottom-top)


def ensure_same_layout(anchor, current_client_rect, tolerance=3):
    """Return translation delta when layout size is unchanged.

    Translation is safe: controls move with the window. Resizing is not safe
    because Paint can reflow/collapse toolbar controls and sliders.
    """
    if type(tolerance) is not int or tolerance < 0:
        raise ValueError('Calibration layout tolerance must be a non-negative integer.')
    clean = validate_anchor(anchor)
    old = tuple(clean['client_rect'])
    current = _rect(current_client_rect, 'current client rectangle')
    old_size = client_size(old); new_size = client_size(current)
    if max(abs(old_size[i]-new_size[i]) for i in (0,1)) > int(tolerance):
        raise ValueError(
            f'The target application layout changed size from {old_size[0]}×{old_size[1]} to '
            f'{new_size[0]}×{new_size[1]}. Recalibrate colors/tools for the current window size before drawing.')
    return current[0]-old[0], current[1]-old[1]


def resolve_point(point, anchor, current_client_rect):
    point = _point(point)
    dx, dy = ensure_same_layout(anchor, current_client_rect)
    return _point((point[0]+dx, point[1]+dy))


def resolve_points(points, anchor, current_client_rect):
    dx, dy = ensure_same_layout(anchor, current_client_rect)
    result=[]
    for point in points:
        point = _point(point)
        result.append(_point((point[0]+dx, point[1]+dy)))
    return result
