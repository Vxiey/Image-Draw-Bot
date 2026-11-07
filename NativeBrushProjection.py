"""Physical-pixel geometry for a downsampled regional drawing plan.

Paths remain in their original integer source coordinates.  The separately
verified brush width always means native screen pixels, including when the
planning image is smaller than its fitted drawing area.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np

from Precision import CanvasTransform


def _check(cancelled):
    if cancelled():
        raise InterruptedError()


@dataclass(frozen=True)
class NativeBrushROI:
    target: np.ndarray
    source_origin: tuple[int, int]
    native_origin: tuple[int, int]
    x_centers: np.ndarray
    y_centers: np.ndarray
    scale_x: float
    scale_y: float

    def source_centers(self, native_mask):
        """Read only centers reachable by the unchanged source-integer paths."""
        height, width = native_mask.shape
        valid_x = (self.x_centers >= 0) & (self.x_centers < width)
        valid_y = (self.y_centers >= 0) & (self.y_centers < height)
        result = np.zeros((len(self.y_centers), len(self.x_centers)), dtype=np.bool_)
        xs, ys = np.flatnonzero(valid_x), np.flatnonzero(valid_y)
        if xs.size and ys.size:
            result[np.ix_(ys, xs)] = native_mask[np.ix_(self.y_centers[ys], self.x_centers[xs])]
        return result

    def native_path(self, local_path):
        return tuple((int(self.x_centers[int(x)]), int(self.y_centers[int(y)]))
                     for x, y in local_path)


class NativeBrushProjection:
    """Exact CanvasTransform plus nearest-source labels on the whole canvas.

    Only axis-sized arrays are retained.  A candidate ROI and each simulation
    tile must independently fit the existing planner's pixel allowance.
    """

    def __init__(self, source_size, fitted, options, *, cancelled=lambda: False):
        from PreviewSafety import _canvas_size, _target_area

        _check(cancelled)
        self.source_size = tuple(map(int, source_size))
        self.fitted = tuple(map(float, fitted))
        self.canvas_size = _canvas_size(options, fitted)
        raw_origin = tuple(map(float, _target_area(options, self.canvas_size)[:2]))
        if not all(math.isfinite(v) and v == int(v) for v in raw_origin):
            raise ValueError('Physical brush projection needs integer screen coordinates.')
        self.origin = tuple(map(int, raw_origin))
        if min(self.source_size) < 1 or min(self.fitted) <= 0:
            raise ValueError('Physical brush projection needs positive dimensions.')
        self.offset = tuple((canvas - fit) / 2 for canvas, fit in zip(self.canvas_size, self.fitted))
        if min(self.offset) < 0:
            raise ValueError('Fitted image exceeds its physical canvas.')
        # Use the already resolved planning cap; direct helper callers retain
        # the established Standard maximum instead of an unbounded allocation.
        self.pixel_limit = max(1, int(options.get('planner_max_pixels') or 75000))
        if max(*self.canvas_size, *self.source_size) > self.pixel_limit:
            raise ValueError('Physical brush projection axis exceeds the planning pixel allowance.')
        self.transform = CanvasTransform(*self.source_size, self.fitted,
            self.origin[0] + self.offset[0], self.origin[1] + self.offset[1])
        self.scale_x = self.fitted[0] / self.source_size[0]
        self.scale_y = self.fitted[1] / self.source_size[1]
        self.x_source = self._source_axis(0, cancelled)
        self.y_source = self._source_axis(1, cancelled)
        self.x_centers = self._center_axis(0, cancelled)
        self.y_centers = self._center_axis(1, cancelled)
        _check(cancelled)

    @classmethod
    def for_scaled_plan(cls, source_size, fitted, options, *, cancelled=lambda: False):
        if all(abs(float(fit) - int(source)) <= 1e-10 for source, fit in zip(source_size, fitted)):
            from PreviewSafety import _canvas_size, _target_area
            canvas=_canvas_size(options,fitted)
            origin=tuple(map(float,_target_area(options,canvas)[:2]))
            # Even an integral letterbox can receive real brush spill outside
            # the fitted source. Only a truly coincident canvas/source grid
            # can reuse the old source-sized simulation without omitting it.
            if (tuple(canvas)==tuple(map(int,source_size))
                    and all(math.isfinite(value) and value==int(value) for value in origin)):
                return None
        return cls(source_size, fitted, options, cancelled=cancelled)

    def _source_axis(self, axis, cancelled):
        count = self.canvas_size[axis]
        source = self.source_size[axis]
        # Invert pixel cells, not a previously rounded fitted/source quotient.
        # At 216/200, for example, 135/(216/200) rounds below 125 and drops an
        # entire row. Treat the actual finite geometry values as exact rationals
        # and floor one integer quotient. No epsilon changes nearby boundaries.
        slope = Fraction(source, 1) / Fraction(self.fitted[axis])
        intercept = (Fraction(1, 2) - Fraction(self.offset[axis])) * slope
        denominator = math.lcm(slope.denominator, intercept.denominator)
        step = slope.numerator * (denominator // slope.denominator)
        start_value = intercept.numerator * (denominator // intercept.denominator)
        limit = np.iinfo(np.int64).max
        vectorized = (max(abs(step), abs(start_value), denominator,
                          abs(step) * max(0, count - 1) + abs(start_value)) <= limit)
        values = np.empty(count, dtype=np.int64)
        for start in range(0, count, 4096):
            _check(cancelled)
            # Canvas-local pixel centers give the same nearest-source cells
            # independent of the desktop origin. Reachable centers below still
            # use native signed half-pixel rounding, exactly like execution.
            end = min(count, start + 4096)
            if vectorized:
                coords = np.arange(start, end, dtype=np.int64)
                values[start:end] = np.clip((coords * step + start_value) // denominator, -1, source)
            else:
                for position in range(start, end):
                    if position % 256 == 0:
                        _check(cancelled)
                    cell = (position * step + start_value) // denominator
                    values[position] = max(-1, min(source, cell))
        return values

    def _center_axis(self, axis, cancelled):
        values = np.empty(self.source_size[axis], dtype=np.int64)
        for position in range(len(values)):
            if position % 256 == 0:
                _check(cancelled)
            point = self.transform.point(position if axis == 0 else 0,
                                         position if axis == 1 else 0)
            values[position] = point[axis] - self.origin[axis]
        return values

    def component_roi(self, component_map, component_id, bbox, *, cancelled=lambda: False):
        _check(cancelled)
        x0, y0, x1, y1 = map(int, bbox)
        left, right = np.searchsorted(self.x_source, (x0, x1 + 1), side='left')
        top, bottom = np.searchsorted(self.y_source, (y0, y1 + 1), side='left')
        width, height = int(right - left), int(bottom - top)
        if width < 1 or height < 1:
            return None, 'component has no native target pixels'
        if width * height > self.pixel_limit:
            return None, f'native ROI {width}x{height} exceeds planning pixel allowance {self.pixel_limit}'
        target = np.empty((height, width), dtype=np.bool_)
        xs = self.x_source[left:right]
        for row in range(0, height, 64):
            _check(cancelled)
            ys = self.y_source[top + row:min(bottom, top + row + 64)]
            target[row:row + len(ys)] = component_map[np.ix_(ys, xs)] == component_id
        return NativeBrushROI(target, (x0, y0), (int(left), int(top)),
            self.x_centers[x0:x1 + 1] - left, self.y_centers[y0:y1 + 1] - top,
            self.scale_x, self.scale_y), ''

    def native_path(self, source_path, *, cancelled=lambda: False):
        points = []
        for number, (x, y) in enumerate(source_path):
            if number % 256 == 0:
                _check(cancelled)
            sx, sy = self.transform.point(x, y)
            points.append((sx - self.origin[0], sy - self.origin[1]))
        return tuple(points)

    def source_rectangle(self, x0, y0, x1, y1):
        left, right = np.searchsorted(self.x_source, (x0, x1 + 1), side='left')
        top, bottom = np.searchsorted(self.y_source, (y0, y1 + 1), side='left')
        return int(left), int(top), int(right - 1), int(bottom - 1)

    def tiles(self, *, cancelled=lambda: False):
        width, height = self.canvas_size
        tile_width = min(width, 1024, self.pixel_limit)
        tile_height = max(1, min(128, self.pixel_limit // tile_width))
        for top in range(0, height, tile_height):
            for left in range(0, width, tile_width):
                _check(cancelled)
                yield left, top, min(width, left + tile_width), min(height, top + tile_height)

    def as_meta(self):
        return {'coordinate_space': 'physical canvas pixels before CanvasGuard',
            'source_size': self.source_size, 'canvas_size': self.canvas_size,
            'fitted': self.fitted, 'screen_origin': self.origin,
            'scale_x': self.scale_x, 'scale_y': self.scale_y,
            'pixel_allowance': self.pixel_limit, 'brush_width_units': 'native screen pixels'}
