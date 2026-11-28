"""Verify a fully visible blank Paint document using its workspace and resize grips."""
import numpy as np


def _neutral_workspace(samples):
    colors = np.asarray(samples, dtype=np.int16)
    return (colors.ndim == 2 and colors.shape[1] == 3 and colors.shape[0] > 0
            and np.all(np.min(colors, axis=1) <= 246)
            and np.max(np.ptp(colors, axis=1)) <= 28
            and np.max(np.ptp(colors, axis=0)) <= 14)


def _single_span(profile):
    occupied = np.flatnonzero(profile)
    if not occupied.size or occupied[-1] - occupied[0] + 1 != occupied.size:
        return None
    return int(occupied[0]), int(occupied[-1] + 1)


def _grip_dimensions(along, across, midpoint, edge):
    length = _single_span(along)
    thickness = _single_span(across)
    if length is None or thickness is None:
        return None
    start, end = length
    inner, outer = thickness
    width, depth = end - start, outer - inner
    if not (3 <= width <= 72 and 2 <= depth <= 24 and .65 * depth <= width <= 14 * depth):
        return None
    if abs((start + end - 1) / 2 - midpoint) > max(3, width * .15):
        return None
    # A grip may straddle the frame or sit immediately outside it. Include a
    # small tolerance for reconstructing the frame from the reduced viewport.
    if inner > edge + 3 or outer < edge - 1:
        return None
    return width, depth


def _measure_grip(image, x, y, *, vertical, span, margin):
    box = ((x - margin, y - span, x + margin + 1, y + span + 1) if vertical else
           (x - span, y - margin, x + span + 1, y + margin + 1))
    with image.crop(box) as crop:
        strip = np.asarray(crop, dtype=np.int16)
    if not vertical:
        strip = strip.transpose(1, 0, 2)
    # Compare like depth positions across the edge. A continuous border or
    # drop shadow disappears, while a local grip remains visible.
    flank = max(4, span // 5)
    first = np.median(strip[:flank], axis=0)
    last = np.median(strip[-flank:], axis=0)
    if np.max(np.abs(first - last)) > 8:
        return None
    changed = np.max(np.abs(strip - (first + last) / 2), axis=2) >= 20
    return _grip_dimensions(changed.any(axis=1), changed.any(axis=0), span, margin)


def _matching_grips(right_grip, bottom_grip):
    return bool(right_grip and bottom_grip and all(
        abs(a - b) <= max(2, .25 * max(a, b)) for a, b in zip(right_grip, bottom_grip)))


def _square_corner(x_counts, y_counts, depth):
    xs = _single_span(x_counts)
    ys = _single_span(y_counts)
    if not xs or not ys:
        return False
    x0, x1 = xs
    y0, y1 = ys
    width, height = x1 - x0, y1 - y0
    if (max(x0, y0) > 3 or min(width, height) < max(2, depth * .4)
            or max(width, height) > depth * 1.5 + 1 or abs(width - height) > 2):
        return False
    return y_counts[y1 - 1] >= .6 * width and x_counts[x1 - 1] >= .6 * height


def _corner_has_grip(image, right, bottom, room, depth):
    # Two centred scrollbar thumbs can resemble the side grips. Require the
    # compact square resize mark in the workspace beyond the document corner.
    side = min(room, depth * 2 + 8)
    with image.crop((right, bottom, right + side, bottom + side)) as crop:
        pixels = np.asarray(crop, dtype=np.int16)
    workspace = np.median(pixels[-3:, -3:], axis=(0, 1))
    mark = np.max(np.abs(pixels - workspace), axis=2) >= 60
    return _square_corner(mark.sum(axis=0), mark.sum(axis=1), depth)


def verified_grip_depth(image, frame, cancelled):
    """Return the thickest matched resize grip in physical pixels, or zero."""
    left, top, right, bottom = frame
    width, height = right - left, bottom - top
    room = min(left, top, image.width - right - 1, image.height - bottom - 1)
    if room < 8:
        return 0
    distance = min(room, 18)
    samples = []
    for fraction in (.125, .25, .375, .625, .75, .875):
        if cancelled():
            raise InterruptedError()
        x = left + round(width * fraction)
        y = top + round(height * fraction)
        for point in ((x, top - distance), (x, bottom + distance),
                      (left - distance, y), (right + distance, y)):
            samples.append(image.getpixel(point))
    if not _neutral_workspace(samples):
        return 0
    depth = min(room, 24)
    right_grip = _measure_grip(image, right, (top + bottom) // 2, vertical=True,
                               span=min(90, height // 4), margin=depth)
    if cancelled():
        raise InterruptedError()
    if right_grip is None:
        return 0
    bottom_grip = _measure_grip(image, (left + right) // 2, bottom, vertical=False,
                                span=min(90, width // 4), margin=depth)
    if not _matching_grips(right_grip, bottom_grip):
        return 0
    grip_depth = max(right_grip[1], bottom_grip[1])
    return grip_depth if _corner_has_grip(image, right, bottom, room, grip_depth) else 0
