"""Four-connected screen-mask components in sampled browser coordinates."""

from BinaryMaskComponents import mask_components


def has_canvas_bounds(box, size):
    """Require at least two observed edges to distinguish a surface from the page."""
    left, top, right, bottom = box
    width, height = size
    return sum((left > 0, top > 0, right < width, bottom < height)) >= 2
