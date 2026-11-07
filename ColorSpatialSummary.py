"""Bounded spatial summaries of color strokes without per-stroke records."""
from __future__ import annotations

from math import hypot, isfinite, sqrt


def midpoint_color_cells(groups, active, grid: int, *, legacy_sqrt_mass=False):
    """Accumulate midpoint mass in a small grid using two streaming passes.

    Reusable stroke sequences are borrowed. One-shot iterators are materialized
    once so their historical support is retained. The persistent summary holds
    at most ``grid * grid * len(active)`` weights instead of a second record and
    two coordinate lists for every source stroke.
    """
    selected = []
    for index in active:
        group = groups[index]
        iterator = iter(group)
        selected.append((index, tuple(iterator) if iterator is group else group))

    def coordinates():
        for index, group in selected:
            for stroke in group:
                try:
                    x1, y1, x2, y2 = map(float, stroke)
                    x = (x1 + x2) * .5
                    y = (y1 + y2) * .5
                    # Validate the same record in both passes. The previous
                    # regional implementation skipped an overflowing squared
                    # length before allowing its midpoint into the bounds.
                    length = (sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) if legacy_sqrt_mass
                              else hypot(x2 - x1, y2 - y1))
                    if not (isfinite(x) and isfinite(y) and isfinite(length)):
                        continue
                except (TypeError, ValueError, ArithmeticError):
                    continue
                yield index, x, y, max(1.0, length)

    xmin = ymin = float('inf')
    xmax = ymax = float('-inf')
    for _index, x, y, _mass in coordinates():
        if x < xmin:
            xmin = x
        if x > xmax:
            xmax = x
        if y < ymin:
            ymin = y
        if y > ymax:
            ymax = y
    if xmin == float('inf'):
        return {}

    width = max(1.0, xmax - xmin)
    height = max(1.0, ymax - ymin)
    cells = {}
    for index, x, y, mass in coordinates():
        column = min(grid - 1, max(0, int((x - xmin) / width * grid)))
        row = min(grid - 1, max(0, int((y - ymin) / height * grid)))
        bucket = cells.setdefault((column, row), {})
        bucket[index] = bucket.get(index, 0.0) + mass
    return cells
