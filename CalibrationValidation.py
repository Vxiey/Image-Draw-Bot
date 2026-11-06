"""Pure validation at the calibration-to-screen-coordinate boundary."""
from __future__ import annotations

import math
from numbers import Integral, Real
from contextlib import contextmanager

LONG_MIN = -(2 ** 31)
LONG_MAX = 2 ** 31 - 1


def screen_point(value, label='screen point'):
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(isinstance(v, bool) or not isinstance(v, Integral) or
                not LONG_MIN <= v <= LONG_MAX for v in value)):
        raise ValueError(f'Invalid {label}; recalibrate using integer screen coordinates.')
    return tuple(int(v) for v in value)


def screen_rect(value, label='client rectangle', *, min_side=1):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'Invalid {label}.')
    left, top = screen_point(value[:2], label)
    right, bottom = screen_point(value[2:], label)
    if isinstance(min_side, bool) or not isinstance(min_side, Integral) or min_side < 1:
        raise ValueError('Minimum rectangle size must be a positive integer.')
    if right - left < min_side or bottom - top < min_side:
        raise ValueError(f'Invalid or too small {label}.')
    return left, top, right, bottom


def point_in_rect(point, rect):
    x, y = screen_point(point)
    left, top, right, bottom = screen_rect(rect)
    return left <= x < right and top <= y < bottom


def contained_rect(value, client, label='canvas rectangle', *, min_side=1):
    box = screen_rect(value, label, min_side=min_side)
    left, top, right, bottom = screen_rect(client)
    if not (left <= box[0] < box[2] <= right and top <= box[1] < box[3] <= bottom):
        raise ValueError(f'{label} is outside the target client area.')
    return box


def screenshot_matches(image, client):
    left, top, right, bottom = screen_rect(client)
    if getattr(image, 'size', None) != (right-left, bottom-top):
        raise ValueError('Target screenshot dimensions do not match the current client rectangle.')
    return image


@contextmanager
def calibration_screenshot(screenshot, client):
    """Use caller-owned images; close only captures/conversions created here."""
    client=screen_rect(client)
    width,height=client[2]-client[0],client[3]-client[1]
    if max(width,height)>32768 or width*height>64_000_000:
        raise ValueError('The calibration screenshot area is too large.')
    captured=None;rgb=None
    try:
        if screenshot is None:
            from PIL import ImageGrab
            captured=ImageGrab.grab(bbox=client,all_screens=True)
            screenshot=captured
        screenshot_matches(screenshot,client)
        rgb=screenshot if getattr(screenshot,'mode',None)=='RGB' else screenshot.convert('RGB')
        yield rgb
    finally:
        if rgb is not None and rgb is not screenshot:rgb.close()
        if captured is not None:captured.close()


def finite_confidence(value, *, default=0.0):
    """Invalid optional confidence is absence of evidence, never certainty."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return float(default)
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return float(default)
    return max(0.0, min(1.0, number)) if math.isfinite(number) else float(default)


def bounded_number(value, label, *, minimum=0.0, maximum=1.0):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{label} must be a finite number between {minimum} and {maximum}.')
    try:
        number = float(value)
    except (ValueError, OverflowError):
        number = float('nan')
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f'{label} must be a finite number between {minimum} and {maximum}.')
    return number


def nonnegative_integer(value, label, *, maximum=LONG_MAX):
    if isinstance(value, bool) or not isinstance(value, Integral) or not 0 <= value <= maximum:
        raise ValueError(f'{label} must be an integer between 0 and {maximum}.')
    return int(value)


def rgb_value(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3 or
            any(isinstance(v, bool) or not isinstance(v, Integral) or not 0 <= v <= 255 for v in value)):
        raise ValueError('RGB must contain three integer channels from 0 to 255.')
    return tuple(int(v) for v in value)
