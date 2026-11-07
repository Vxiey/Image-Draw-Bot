"""Bounded row-interval canvas for actual contour-and-bucket footprints.

The initially unpainted canvas is implicit. Only nonempty horizontal color
intervals are retained, so a large homogeneous bucket needs one record per row
instead of a full native-resolution image. This is the same discrete square
brush/four-neighbor model as the existing Fill proof, not an antialiasing model.
"""
from __future__ import annotations

from contextlib import closing

from PixelMapValidation import validate_color_index


class _SpanCanvas:
    def __init__(self, size, max_spans, cancelled):
        self.width, self.height = map(int, size)
        self.max_spans = max(1, int(max_spans))
        self.cancelled = cancelled
        self.rows = {}
        self.spans = 0

    def check(self):
        if self.cancelled():
            raise InterruptedError()

    def close(self):
        self.rows.clear()
        self.spans = 0
        self.cancelled = None

    def color_at(self, x, y):
        for left, right, color in self.rows.get(y, ()):
            if left > x:
                break
            if x <= right:
                return color
        return -1

    def paint_span(self, y, left, right, color):
        self.check()
        old = self.rows.get(y, ())
        result = []
        inserted = False
        def append(a, b, ink):
            if result and result[-1][1] + 1 == a and result[-1][2] == ink:
                result[-1] = (result[-1][0], b, ink)
            else:
                result.append((a, b, ink))
        try:
            for number, (a, b, ink) in enumerate(old):
                if number % 256 == 0:
                    self.check()
                if b < left:
                    append(a, b, ink)
                    continue
                if a > right:
                    if not inserted:
                        append(left, right, color)
                        inserted = True
                    append(a, b, ink)
                    continue
                if a < left:
                    append(a, left - 1, ink)
                if not inserted:
                    append(left, right, color)
                    inserted = True
                if b > right:
                    append(right + 1, b, ink)
            if not inserted:
                append(left, right, color)
            count = self.spans - len(old) + len(result)
            if count > self.max_spans:
                raise MemoryError('Native Fill row intervals exceed the planning allowance')
            self.rows[y] = result
            self.spans = count
        finally:
            old = result = None

    def paint_rectangle(self, bounds, color):
        left, top, right, bottom = bounds
        for y in range(top, bottom + 1):
            self.paint_span(y, left, right, color)

    def matching_spans(self, y, color, left, right):
        """Return complete same-color row runs intersecting the incoming span."""
        result = []
        try:
            cursor = 0
            for number, (a, b, ink) in enumerate(self.rows.get(y, ())):
                if number % 256 == 0:
                    self.check()
                if color == -1 and cursor < a and cursor <= right and a - 1 >= left:
                    result.append((cursor, a - 1))
                if ink == color and a <= right and b >= left:
                    result.append((a, b))
                cursor = b + 1
                if cursor > right:
                    break
            else:
                if color == -1 and cursor < self.width and cursor <= right:
                    result.append((cursor, self.width - 1))
            return result
        finally:
            result = None

    def flood(self, seed, color):
        self.check()
        x, y = seed
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        previous = self.color_at(x, y)
        if previous == color:
            return
        pending = [(y, x, x)]
        matches = None
        try:
            while pending:
                self.check()
                y, left, right = pending.pop()
                matches = self.matching_spans(y, previous, left, right)
                for a, b in matches:
                    self.paint_span(y, a, b, color)
                    if y:
                        pending.append((y - 1, a, b))
                    if y + 1 < self.height:
                        pending.append((y + 1, a, b))
                    if len(pending) > self.max_spans * 2:
                        raise MemoryError('Native Fill frontier exceeds the planning allowance')
                    yield a, y, b, y
        finally:
            pending.clear()
            matches = None


def native_fill_rectangles(projection, regions, brush, path_rectangles, *, cancelled):
    """Replay actual color-batched contours/seals and bucket seeds as rectangles.

    Row-span-only diagnostic inputs retain their historical analytic contract;
    executable regions with a bbox/contour use the actual native operation.
    """
    if cancelled():
        raise InterruptedError()
    batches = {}
    ordered = []
    state = None
    try:
        for number, region in enumerate(regions or ()):
            if cancelled():
                raise InterruptedError()
            if number >= projection.pixel_limit:
                raise MemoryError('Native Fill region count exceeds the planning allowance')
            color = validate_color_index(region.get('color_index'))
            batches.setdefault(color, []).append(region)
            ordered.append((color, region))
        if not batches:
            return
        if not any(region.get('contour') or region.get('bbox') for _, region in ordered):
            for color, region in ordered:
                for y, left, right in region.get('row_spans') or ():
                    if cancelled():
                        raise InterruptedError()
                    left, right = sorted((int(left), int(right)))
                    bounds = projection.source_rectangle(left, int(y), right, int(y))
                    if bounds[0] <= bounds[2] and bounds[1] <= bounds[3]:
                        yield color, bounds
            return
        state = _SpanCanvas(projection.canvas_size, min(65536, projection.pixel_limit), cancelled)
        width, height = projection.canvas_size
        def mapped(path, integral=False):
            out = []
            try:
                for number, (x, y) in enumerate(path):
                    if number % 128 == 0:
                        state.check()
                    if integral:
                        x, y = int(x), int(y)
                    nx, ny = projection.transform.point(x, y)
                    out.append((nx - projection.origin[0], ny - projection.origin[1]))
                return tuple(out)
            finally:
                out.clear()
        for color, batch in batches.items():
            # The real executor draws every contour of one color before
            # selecting its Fill tool and visiting that color's bucket seeds.
            for region in batch:
                state.check()
                if not region.get('contour') and not region.get('bbox'):
                    for y, left, right in region.get('row_spans') or ():
                        left, right = sorted((int(left), int(right)))
                        bounds = projection.source_rectangle(left, int(y), right, int(y))
                        if bounds[0] <= bounds[2] and bounds[1] <= bounds[3]:
                            state.paint_rectangle(bounds, color)
                            yield color, bounds
                    continue
                for seal in region.get('fill_seal_paths') or ():
                    path = mapped(seal, integral=True)
                    # Execution draws seal segments, so an isolated point is
                    # not an operation and must not become an artificial wall.
                    if len(path) < 2:
                        continue
                    for bounds in path_rectangles(path, brush, width, height, cancelled=cancelled):
                        state.paint_rectangle(bounds, color)
                        yield color, bounds
                contour = region.get('contour') or ()
                if not contour:
                    x0, y0, x1, y1 = map(int, region['bbox'])
                    contour = ((x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0))
                contour = tuple(contour)
                if len(contour) < 2:
                    continue
                if contour and contour[-1] != contour[0]:
                    contour += (contour[0],)
                path = mapped(contour)
                for bounds in path_rectangles(path, brush, width, height, cancelled=cancelled):
                    state.paint_rectangle(bounds, color)
                    yield color, bounds
            for region in batch:
                if not region.get('contour') and not region.get('bbox'):
                    continue
                seed, = mapped((region['seed_pixel'],), integral=True)
                with closing(state.flood(seed, color)) as flood:
                    for bounds in flood:
                        yield color, bounds
        state.check()
    finally:
        if state is not None:
            state.close()
        batches.clear()
        ordered.clear()
        batch = path = contour = None
