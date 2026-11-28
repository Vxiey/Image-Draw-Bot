"""Four-connected screen-mask components in sampled browser coordinates."""

_BINARY = bytes([0] + [1] * 255)


def has_canvas_bounds(box, size):
    """Require at least two observed edges to distinguish a surface from the page."""
    left, top, right, bottom = box
    width, height = size
    return sum((left > 0, top > 0, right < width, bottom < height)) >= 2


def mask_components(mask, *, min_area, limit=48, cancelled=lambda: False):
    """Return (half-open bounds, pixel count), largest first with scan-order ties."""
    if cancelled():
        raise InterruptedError()
    if not len(mask) or not len(mask[0]):
        return []
    width = len(mask[0])
    remaining = []
    for row in mask:
        if cancelled():
            raise InterruptedError()
        remaining.append(bytearray(row).translate(_BINARY))
    height = len(remaining)
    clear = bytes(width)

    def take_span(y, x):
        row = remaining[y]
        left = row.rfind(0, 0, x) + 1
        right = row.find(0, x)
        if right < 0:
            right = width
        row[left:right] = clear[:right-left]
        return y, left, right

    found = []
    runs = 0
    for sy, seed_row in enumerate(remaining):
        if cancelled():
            raise InterruptedError()
        seed = seed_row.find(1)
        while seed >= 0:
            first = take_span(sy, seed)
            stack = [first]
            top = bottom = sy
            left, right = first[1:]
            area = 0
            while stack:
                if runs % 256 == 0 and cancelled():
                    raise InterruptedError()
                runs += 1
                y, x0, x1 = stack.pop()
                area += x1 - x0
                left, right = min(left, x0), max(right, x1)
                top, bottom = min(top, y), max(bottom, y)
                for neighbor in (y - 1, y + 1):
                    if not 0 <= neighbor < height:
                        continue
                    row = remaining[neighbor]
                    x = row.find(1, x0, x1)
                    while x >= 0:
                        span = take_span(neighbor, x)
                        stack.append(span)
                        x = row.find(1, span[2], x1)
            if area >= min_area:
                found.append(((left, top, right, bottom + 1), area))
            seed = seed_row.find(1, first[2])
    found.sort(key=lambda item: item[1], reverse=True)
    return found[:max(1, int(limit))]
