"""Fast visual verification after each color batch (v1.0.43).

This module is pure image analysis. It never reads the screen or sends input by
itself; the guarded execution layer supplies already-captured canvas snapshots.
The goal is quick fault detection, not pixel-perfect reconstruction.
"""
from __future__ import annotations

from math import hypot, isfinite, ceil
from typing import Iterable, Sequence
from PIL import Image

VISUAL_VERIFICATION_MODES = ("Auto", "Off", "Fast", "Balanced", "Strict")


def validate_visual_verification(value: str) -> str:
    if value not in VISUAL_VERIFICATION_MODES:
        raise ValueError("Visual verification must be Auto, Off, Fast, Balanced or Strict.")
    return value


def resolve_visual_verification(value: str, *, paint_profile: bool = True, dry_run: bool = False, test: bool = False) -> str:
    validate_visual_verification(value)
    if dry_run or test or not paint_profile:
        return "Off" if value == "Auto" else value
    if value == "Auto":
        return "Balanced"
    return value


def rgb_error(a: Sequence[int], b: Sequence[int]) -> int:
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def _mode_config(mode: str) -> dict:
    mode = validate_visual_verification(mode)
    if mode == "Fast":
        return dict(tolerance=72, min_match=0.45, max_outside=0.060, max_outside_samples=220, sample_limit=80)
    if mode == "Strict":
        return dict(tolerance=46, min_match=0.68, max_outside=0.018, max_outside_samples=55, sample_limit=180)
    # Balanced / Auto after resolution.
    return dict(tolerance=58, min_match=0.55, max_outside=0.035, max_outside_samples=120, sample_limit=130)


def _line_points(a, b, steps=None):
    x0, y0 = map(float, a[:2]); x1, y1 = map(float, b[:2])
    dist = max(abs(x1 - x0), abs(y1 - y0), 1.0)
    n = int(steps if steps is not None else max(2, min(16, round(dist) + 1)))
    if n <= 1:
        return [(round(x0), round(y0))]
    return [(round(x0 + (x1 - x0) * i / (n - 1)), round(y0 + (y1 - y0) * i / (n - 1))) for i in range(n)]


def _iter_item_source_points(item, smart_group: bool, per_item_limit: int = 8, cancelled=lambda: False):
    try:
        if smart_group:
            pts = (tuple(map(float, p[:2])) for p in item)
            first = next(pts, None)
            if first is None:
                return
            yield (round(first[0]), round(first[1]))
            a = first
            for number,b in enumerate(pts):
                if number%512==511 and cancelled():raise InterruptedError()
                if a == b:
                    continue
                yield from _line_points(a, b, max(2, min(per_item_limit, 1 + round(hypot(b[0]-a[0], b[1]-a[1])))))[1:]
                a = b
            return
        x0, y0, x1, y1 = map(float, item[:4])
        yield from _line_points((x0, y0), (x1, y1), max(2, min(per_item_limit, 1 + round(hypot(x1-x0, y1-y0)))))
    except (TypeError, ValueError, OverflowError, IndexError):
        return


def _item_source_points(item, smart_group: bool, per_item_limit: int = 8):
    return list(_iter_item_source_points(item, smart_group, per_item_limit))


def planned_batch_points(items, *, smart_group: bool, transform, sample_limit: int = 130,
                         cancelled=lambda: False):
    """Return deterministic screen-space sample points for one planned batch."""
    if type(sample_limit) is not int or sample_limit < 0:
        raise ValueError('Visual sample limit must be a non-negative integer.')
    if cancelled():
        raise InterruptedError()
    if sample_limit == 0:
        return []
    # Deterministic streaming decimation keeps both the beginning and the end
    # represented without materializing every probe in a long color batch.
    raw = []
    stride = 1
    count = 0
    last = None
    for index,item in enumerate(items or ()):
        if index%512==0 and cancelled():raise InterruptedError()
        for point in _iter_item_source_points(item, smart_group, 9, cancelled):
            if count % 512 == 0 and cancelled():
                raise InterruptedError()
            last = (count, point)
            if count % stride == 0:
                raw.append(last)
                if len(raw) > sample_limit * 2:
                    stride *= 2
                    raw = [entry for entry in raw if entry[0] % stride == 0]
            count += 1
    if not raw:
        return []
    if last is not None and raw[-1][0] != last[0]:
        raw.append(last)
    if len(raw) > sample_limit:
        raw = ([raw[len(raw)//2]] if sample_limit == 1 else
               [raw[i*(len(raw)-1)//(sample_limit-1)] for i in range(sample_limit)])
    result = []
    seen = set()
    for _, (x, y) in raw:
        px, py = transform(int(x), int(y))
        point = (int(round(px)), int(round(py)))
        if point not in seen:
            result.append(point); seen.add(point)
    if cancelled():
        raise InterruptedError()
    return result


def planned_batch_boxes(items, *, smart_group: bool, transform, brush_px: int = 1, pad_extra: int = 8,
                        cancelled=lambda: False):
    """Return padded screen-space bounding boxes for expected changed regions."""
    boxes = []
    pad = max(4, int(round(max(1, int(brush_px)) / 2)) + int(pad_extra))
    for index,item in enumerate(items or ()):
        if index%512==0 and cancelled():raise InterruptedError()
        bounds = None
        for number, (x, y) in enumerate(_iter_item_source_points(item, smart_group, 16, cancelled)):
            if number % 512 == 0 and cancelled():
                raise InterruptedError()
            sx, sy = transform(int(x), int(y))
            sx, sy = int(round(sx)), int(round(sy))
            if bounds is None:
                bounds = [sx, sy, sx, sy]
            else:
                bounds = [min(bounds[0], sx), min(bounds[1], sy), max(bounds[2], sx), max(bounds[3], sy)]
        if bounds is not None:
            boxes.append((bounds[0]-pad, bounds[1]-pad, bounds[2]+pad, bounds[3]+pad))
    if cancelled():
        raise InterruptedError()
    return merge_boxes(boxes)


def merge_boxes(boxes, *, max_boxes: int = 80):
    """Merge only rectangular unions; never mark the gaps between strokes safe.

    ``max_boxes`` is retained for caller compatibility. Exact row intervals in
    the verifier make a lossy all-enclosing fallback unnecessary.
    """
    normalized = []
    for raw in boxes or ():
        try:
            x0, y0, x1, y1 = map(int, raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if x0 <= x1 and y0 <= y1:
            normalized.append((x0, y0, x1, y1))
    def pass_axis(values, transpose=False):
        if transpose:
            values = [(y0, x0, y1, x1) for x0, y0, x1, y1 in values]
        result = []
        for x0, y0, x1, y1 in sorted(values, key=lambda b: (b[1], b[3], b[0], b[2])):
            if result and result[-1][1] == y0 and result[-1][3] == y1 and x0 <= result[-1][2]:
                a0, _, a1, _ = result[-1]
                result[-1] = (a0, y0, max(a1, x1), y1)
            else:
                result.append((x0, y0, x1, y1))
        return [(y0, x0, y1, x1) for x0, y0, x1, y1 in result] if transpose else result
    return pass_axis(pass_axis(normalized), True)


def _contains(point, boxes):
    x, y = point
    for x0, y0, x1, y1 in boxes:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def _snapshot_xy(point, area, size=None):
    x, y = map(float, point); ax, ay, w, h = map(float, area)
    if size is None:
        return int(x-ax), int(y-ay)
    return (round((x-ax+.5)*size[0]/w-.5), round((y-ay+.5)*size[1]/h-.5))


def _near_colors(image, sx, sy, radius):
    w, h = image.size
    rx, ry = radius if isinstance(radius, tuple) else (radius, radius)
    values = []
    for y in range(max(0, sy-ry), min(h, sy+ry+1)):
        for x in range(max(0, sx-rx), min(w, sx+rx+1)):
            values.append(tuple(map(int, image.getpixel((x, y))[:3])))
    return values


def compare_batch_snapshot(after, before, area, expected_rgb, planned_points, expected_boxes, *, brush_px: int = 1, mode: str = "Balanced",
                           cancelled=lambda: False):
    """Compare one canvas snapshot against the expected effects of a color batch."""
    if cancelled():
        raise InterruptedError()
    if mode == "Off":
        return {'ok': True, 'mode': 'Off', 'issues': [], 'confidence': 100.0}
    cfg = _mode_config(mode)
    def unavailable(reason):
        return {'ok': False, 'available': False, 'mode': mode, 'issues': [reason], 'confidence': 0.0,
                'sampled_points': 0, 'matched_points': 0, 'match_rate': 0.0}
    if not isinstance(after, Image.Image) or min(after.size) <= 0:
        return unavailable('invalid-canvas-snapshot')
    if before is not None and (not isinstance(before, Image.Image) or before.size != after.size):
        return unavailable('baseline-snapshot-geometry-mismatch')
    try:
        area = tuple(map(float, area))
        expected = tuple(map(int, expected_rgb))
        brush = float(brush_px)
        if (len(area) != 4 or not all(isfinite(v) for v in area) or area[2] <= 0 or area[3] <= 0
                or len(expected) != 3 or any(not 0 <= v <= 255 for v in expected)
                or not isfinite(brush) or brush <= 0):
            return unavailable('invalid-verification-geometry-or-color')
    except (TypeError, ValueError, OverflowError):
        return unavailable('invalid-verification-geometry-or-color')
    after_rgb = after.convert('RGB')
    before_rgb = None
    try:
        before_rgb = before.convert('RGB') if before is not None else None
        return _compare_rgb_snapshot(after_rgb, before_rgb, area, expected, planned_points, expected_boxes,
                                     brush, mode, cfg, cancelled)
    finally:
        after_rgb.close()
        if before_rgb is not None:
            before_rgb.close()


def _compare_rgb_snapshot(after, before, area, expected, planned_points, expected_boxes, brush, mode, cfg, cancelled):
    base_radius = max(1, min(5, int(round(brush / 2)) + 1))
    radius = (max(1, ceil(base_radius*after.width/area[2])), max(1, ceil(base_radius*after.height/area[3])))
    matched = 0; sampled = 0; best_error = 999; best_color = None
    for number, point in enumerate(planned_points or []):
        if number % 32 == 0 and cancelled():
            raise InterruptedError()
        sx, sy = _snapshot_xy(point, area, after.size)
        if not (0 <= sx < after.width and 0 <= sy < after.height):
            continue
        sampled += 1
        colors = _near_colors(after, sx, sy, radius)
        if not colors:
            continue
        err, color = min((rgb_error(c, expected), c) for c in colors)
        if err <= cfg['tolerance']:
            matched += 1
        if err < best_error:
            best_error, best_color = err, color
    match_rate = matched / sampled if sampled else 0.0

    changed_outside = 0; changed_total = 0; grid_samples = 0
    if before is not None:
        # bounded grid; this detects large fills/strokes outside the planned batch.
        target = max(1, int(cfg['max_outside_samples']) * 9)
        columns = min(after.width, target, max(1, int((target*after.width/after.height)**.5)))
        rows = min(after.height, max(1, target//columns))
        xs = [i*(after.width-1)//max(1, columns-1) for i in range(columns)]
        ys = [i*(after.height-1)//max(1, rows-1) for i in range(rows)]
        boxes = merge_boxes(expected_boxes)
        after_pixels, before_pixels = after.load(), before.load()
        for y in ys:
            if cancelled():
                raise InterruptedError()
            sy = area[1]+(y+.5)*area[3]/after.height-.5
            intervals = sorted((x0, x1) for x0, y0, x1, y1 in boxes if y0 <= sy <= y1)
            interval_index = 0
            for x in xs:
                grid_samples += 1
                a = after_pixels[x,y]; b = before_pixels[x,y]
                if rgb_error(a, b) > 42:
                    changed_total += 1
                    sx = area[0]+(x+.5)*area[2]/after.width-.5
                    while interval_index < len(intervals) and intervals[interval_index][1] < sx:
                        interval_index += 1
                    contained = interval_index < len(intervals) and intervals[interval_index][0] <= sx <= intervals[interval_index][1]
                    if not contained:
                        changed_outside += 1
    outside_rate = changed_outside / grid_samples if grid_samples else 0.0
    issues = []
    if not sampled:
        issues.append('no-valid-planned-probes')
    elif match_rate < cfg['min_match']:
        issues.append('missed-region-or-wrong-color')
    if changed_outside > cfg['max_outside_samples'] or outside_rate > cfg['max_outside']:
        issues.append('outside-change-possible-fill-leak-or-wrong-place')
    confidence = max(0.0, min(100.0, match_rate * 100.0 - outside_rate * 240.0))
    if cancelled():
        raise InterruptedError()
    return {
        'ok': not issues,
        'available': bool(sampled),
        'mode': mode,
        'issues': issues,
        'expected': expected,
        'sampled_points': sampled,
        'matched_points': matched,
        'match_rate': match_rate,
        'best_error': int(best_error if best_error != 999 else 0),
        'best_color': best_color or expected,
        'changed_total_samples': changed_total,
        'changed_outside_samples': changed_outside,
        'outside_grid_samples': grid_samples,
        'outside_change_rate': outside_rate,
        'confidence': confidence,
    }


def summarize_result(result) -> str:
    if not result or result.get('mode') == 'Off':
        return 'visual verification off'
    issues = result.get('issues') or []
    if not issues:
        return (f"visual OK · {result.get('matched_points',0)}/{result.get('sampled_points',0)} planned probes matched · "
                f"outside changes {result.get('changed_outside_samples',0)}")
    return (f"visual warning: {', '.join(issues)} · {result.get('matched_points',0)}/{result.get('sampled_points',0)} probes matched · "
            f"outside changes {result.get('changed_outside_samples',0)} · closest {result.get('best_color')}")
