"""Deterministic one-click calibration for supported browser drawing games.

v1.0.70 removes the normal need to capture every palette/tool position by hand.
The detector is read-only: it takes a screenshot of the already selected target
window, finds the visible palette and a conservative drawable canvas, then saves
anchored palette coordinates. It never sends mouse input.

Manual calibration remains a fallback for changed/unknown layouts.
"""
from __future__ import annotations
from CalibrationValidation import calibration_screenshot

from contextlib import nullcontext
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from statistics import median
from typing import Sequence

from CalibrationAnchors import make_anchor
from BrowserCanvasComponents import has_canvas_bounds, mask_components
from Colors import save_calibration
from PaletteMaps import PRESETS, detect_color_swatches, NoColorSwatchesError
from SketchfulPalette import find_sketchful_grid, recover_sketchful_black
from TargetCapabilities import auto_browser_profile_keys
from CalibrationValidation import (screen_rect, screen_point, contained_rect, screenshot_matches,
                                   finite_confidence, bounded_number, nonnegative_integer)

SUPPORTED_BROWSER_PROFILES = auto_browser_profile_keys()


@dataclass(frozen=True)
class BrowserCalibrationResult:
    profile_key: str
    palette_count: int
    palette_confidence: float
    canvas_box: tuple[int, int, int, int] | None
    canvas_confidence: float
    palette_box: tuple[int, int, int, int] | None
    method: str
    note: str

    @property
    def confidence(self) -> float:
        values = [self.palette_confidence]
        if self.canvas_box is not None:
            values.append(self.canvas_confidence)
        return min(values) if values else 0.0

    def as_dict(self) -> dict:
        return {
            'profile_key': self.profile_key,
            'palette_count': self.palette_count,
            'palette_confidence': self.palette_confidence,
            'canvas_box': self.canvas_box,
            'canvas_confidence': self.canvas_confidence,
            'palette_box': self.palette_box,
            'method': self.method,
            'note': self.note,
            'confidence': self.confidence,
        }


def _rect(rect: Sequence[int]) -> tuple[int, int, int, int]:
    l, t, r, b = screen_rect(rect, 'target client rectangle')
    if r - l < 200 or b - t < 120:
        raise ValueError('Target browser window is too small for automatic calibration.')
    return l, t, r, b


def _crop(image, box):
    l, t, r, b = map(int, box)
    w, h = image.size
    l = max(0, min(w - 1, l)); t = max(0, min(h - 1, t))
    r = max(l + 1, min(w, r)); b = max(t + 1, min(h, b))
    return image.crop((l, t, r, b)), (l, t, r, b)


def _roi(profile_key: str, w: int, h: int):
    """Conservative palette search areas, relative to target client screenshot."""
    if profile_key == 'gartic-phone':
        return (int(w * .06), int(h * .22), int(w * .34), int(h * .74))
    if profile_key in ('skribbl', 'skribbl-fast'):
        return (int(w * .10), int(h * .66), int(w * .43), int(h * .995))
    if profile_key in ('sketchheads', 'sketchful'):
        return (0, int(h * .72), w, h)
    return (0, int(h * .65), w, h)


def _palette_scan_tiles(image, roi, screen_origin=(0, 0), *, max_pixels: int = 900_000, cancelled=lambda:False):
    """Scan a large palette ROI in bounded strips and merge duplicate swatches.

    High-DPI/4K browser clients can make the *relative* palette ROI exceed the
    one-million-pixel guard in :func:`detect_color_swatches`.  The detector's
    memory/CPU bound remains intact: this helper never sends it a crop larger
    than ``max_pixels``.  Gartic palettes are tall and left-side aligned, so we
    split horizontally first and use a small overlap to avoid cutting a swatch.
    No mouse input is generated.
    """
    if cancelled():raise InterruptedError('Browser palette scan cancelled.')
    max_pixels=nonnegative_integer(max_pixels,'Palette tile budget',maximum=1_000_000)
    if max_pixels<64:raise ValueError('Palette tiles need a budget of at least 64 pixels.')
    l, t, r, b = contained_rect(roi,(0,0,image.width,image.height),'palette search area',min_side=8)
    width, height = max(1, r-l), max(1, b-t)
    if width < 8 or height < 8:
        raise ValueError('Automatic palette search area is too small.')

    def starts(length: int, size: int, overlap: int):
        if length <= size:
            return [0]
        step = max(8, size-overlap)
        values = list(range(0, max(1, length-size+1), step))
        last = length-size
        if not values or values[-1] != last:
            values.append(last)
        return sorted(set(values))

    # Prefer full-height vertical strips. If the ROI is extremely tall, cap the
    # height too. Every individual detector call therefore remains bounded.
    tile_h = min(height, max(8, min(1200, max_pixels // max(8, min(width, 1200)))))
    tile_w = min(width, max(8, max_pixels // max(8, tile_h)))
    while tile_w * tile_h > max_pixels:
        if tile_w >= tile_h:
            tile_w -= 1
        else:
            tile_h -= 1
    overlap = 48
    xs = starts(width, tile_w, min(overlap, max(0, tile_w//4)))
    ys = starts(height, tile_h, min(overlap, max(0, tile_h//4)))

    merged = []
    total_rejected = 0
    tile_count = 0
    for y0 in ys:
        for x0 in xs:
            if cancelled():raise InterruptedError('Browser palette scan cancelled.')
            crop_box = (l+x0, t+y0, l+x0+tile_w, t+y0+tile_h)
            tile, actual = _crop(image, crop_box)
            ox = int(screen_origin[0]) + actual[0]
            oy = int(screen_origin[1]) + actual[1]
            try:
                positions, rgbs, stats = detect_color_swatches(tile, (ox, oy), max_colors=96,cancelled=cancelled)
            except NoColorSwatchesError:
                positions,rgbs,stats=[],[],{}
            finally:
                tile.close()
            tile_count += 1
            total_rejected += int(stats.get('rejected', 0))
            for pos, rgb in zip(positions, rgbs):
                # Overlapping strips can report the same component twice. Keep
                # one copy when both RGB and click position are effectively the same.
                if any(tuple(rgb) == tuple(old_rgb) and
                       abs(int(pos[0])-int(old_pos[0])) <= 6 and
                       abs(int(pos[1])-int(old_pos[1])) <= 6
                       for old_pos, old_rgb in merged):
                    continue
                merged.append((tuple(map(int, pos)), tuple(map(int, rgb))))

    positions = [item[0] for item in merged]
    rgbs = [item[1] for item in merged]
    if not positions:raise NoColorSwatchesError('No solid color swatches were found in the palette search area.')
    stats = {
        'found': len(positions),
        'rejected': total_rejected,
        'tiles': tile_count,
        'roi_pixels': width*height,
        'max_tile_pixels': tile_w*tile_h,
        'bounded_scan': True,
    }
    return positions, rgbs, stats


def _rgb_distance(a, b) -> float:
    return sqrt(sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)))


def _match_preset(positions, rgbs, preset, *, tolerance: float = 18.0):
    matches = []
    used = set()
    for name, expected in zip(preset.names, preset.colors):
        candidates = [(float(_rgb_distance(rgb, expected)), i)
                      for i, rgb in enumerate(rgbs) if i not in used]
        if not candidates:
            continue
        distance, index = min(candidates)
        if distance <= tolerance:
            used.add(index)
            matches.append((name, tuple(map(int, positions[index])), tuple(map(int, rgbs[index])), distance))
    return matches


class _UnverifiedPalette(ValueError):
    """Swatches were visible but did not identify the target's palette."""


def _row_cluster(positions, rgbs, *, image_width: int, image_height: int):
    """Choose the longest compact horizontal swatch row from a lower toolbar."""
    items = [(int(x), int(y), tuple(map(int, rgb))) for (x, y), rgb in zip(positions, rgbs)]
    # Extremely bright colors are often toolbar backgrounds rather than useful
    # palette swatches. Keep one white-ish swatch at most after the row is chosen.
    if not items:
        return []
    tolerance = max(8, int(image_height * .035))
    best = []
    tested_rows = set()
    for seed in items:
        if seed[1] in tested_rows:continue
        tested_rows.add(seed[1])
        row = [item for item in items if abs(item[1] - seed[1]) <= tolerance]
        row.sort(key=lambda item: item[0])
        if len(row) < 5:
            continue
        # v1.0.75: toolbar icons/brush-size circles can sit on the same Y row
        # as the palette (notably SketchHeads). Keep the longest *contiguous*
        # swatch run instead of absorbing distant UI controls into the palette.
        gaps=[row[i+1][0]-row[i][0] for i in range(len(row)-1) if row[i+1][0]>row[i][0]]
        if gaps:
            ordered=sorted(gaps);core=ordered[:max(1,(len(ordered)*2)//3)]
            base=sum(core)/len(core);gap_limit=max(14.0,base*1.60)
            segments=[];current=[row[0]]
            for previous,item in zip(row,row[1:]):
                if item[0]-previous[0] <= gap_limit:
                    current.append(item)
                else:
                    segments.append(current);current=[item]
            segments.append(current)
            row=max(segments,key=lambda segment:(len(segment),segment[-1][0]-segment[0][0] if len(segment)>1 else 0))
        if len(row) < 5:
            continue
        span = row[-1][0] - row[0][0]
        score = len(row) * 10000 + span
        old_span = (best[-1][0] - best[0][0]) if len(best) > 1 else 0
        old_score = len(best) * 10000 + old_span
        if score > old_score:
            best = row
    if len(best) < 6:
        raise _UnverifiedPalette('Automatic palette detection could not find a stable color row.')
    # Deduplicate near-identical colors while keeping visual order.
    clean = []
    for item in best:
        if any(_rgb_distance(item[2], old[2]) < 6 for old in clean):
            continue
        clean.append(item)
    if len(clean) < 6:
        raise _UnverifiedPalette('Automatic palette row contained too few distinct colors.')
    return clean[:32]


def _near_white(rgb):
    r, g, b = map(int, rgb[:3])
    return min(r, g, b) >= 235 and max(r, g, b) - min(r, g, b) <= 24


def _largest_light_component(image, *, step: int = 4, min_ratio: float = .08, accept=None, cancelled=lambda:False):
    """Return a large near-white component box, or None instead of guessing."""
    if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
    step=nonnegative_integer(step,'Canvas sampling step',maximum=10000)
    if not step:raise ValueError('Canvas sampling step must be positive.')
    min_ratio=bounded_number(min_ratio,'Canvas minimum area ratio')
    image = image if image.mode=='RGB' else image.convert('RGB')
    w, h = image.size
    sw, sh = (w + step - 1) // step, (h + step - 1) // step
    # Vectorize bounded strips rather than calling Pillow getpixel for every
    # sample or allocating a second full-resolution screenshot array.
    import numpy as np
    mask=[]
    strip_rows = max(1, min(64, 524_288 // max(1, w * step)))
    for first in range(0,sh,strip_rows):
        if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
        with image.crop((0,first*step,w,min(h,(first+strip_rows)*step))) as strip:
            a=np.asarray(strip)[::step,::step]
            red, green, blue = a.transpose(2, 0, 1)
            # With all byte channels >=235, their spread is at most 20.
            white = (red >= 235) & (green >= 235) & (blue >= 235)
            mask.extend(bytearray(row.tobytes()) for row in white)
    min_area = max(40, int(sw * sh * min_ratio))
    for (left,top,right,bottom), area in mask_components(mask,min_area=min_area,cancelled=cancelled):
        box = (left*step, top*step, min(w,right*step), min(h,bottom*step))
        if accept is not None and not accept(box):
            continue
        box_area = (box[2]-box[0]) * (box[3]-box[1])
        density = min(1.0, (area * step * step) / box_area)
        ratio = box_area / max(1, w*h)
        confidence = max(0.0, min(1.0, .55*density + .45*min(1.0, ratio/.45)))
        return box, confidence
    return None, 0.0


def _observed_frame(image, candidate, radius, cancelled):
    """Localize four unambiguous straight edges near a proposed half-open box."""
    import numpy as np
    left, top, right, bottom = candidate
    sides = ((left, top, bottom, True, True), (top, left, right, False, True),
             (right, top, bottom, True, False), (bottom, left, right, False, False))
    found = []
    for expected, start, end, vertical, low_side in sides:
        extent = image.width if vertical else image.height
        lo, hi = max(1, expected - radius), min(extent - 1, expected + radius)
        if lo > hi or end - start < 20:
            return None
        votes = np.zeros(hi - lo + 1, dtype=np.uint8)
        # Sample the middle 80% of each edge, avoiding corners and resize grips.
        for i in range(17):
            if cancelled():
                raise InterruptedError('Browser canvas scan cancelled.')
            p = start + (end - start - 1) * (i + 2) // 20
            strip = (lo - 1, p, hi + 1, p + 1) if vertical else (p, lo - 1, p + 1, hi + 1)
            with image.crop(strip) as line:
                pixels = np.asarray(line, dtype=np.int16).reshape(-1, 3)
                votes += np.max(np.abs(np.diff(pixels, axis=0)), axis=1) >= 24
        supported = np.flatnonzero(votes >= 14)
        if not len(supported) or supported[-1] - supported[0] > 4:
            return None
        # If a narrow border produces two transitions, keep the interior one.
        found.append(lo + int(supported[-1] if low_side else supported[0]))
    return tuple(found)


def _skribbl_palette_frame(image, positions, cancelled):
    """Find an occupied board above two rows of verified Skribbl palette colors."""
    if len(positions) < 18:
        return None
    w, h = image.size
    top_row = min(y for x, y in positions)
    bottom_row = max(y for x, y in positions)
    jitter = max(2, round(h*.004))
    if not 2*jitter < bottom_row-top_row <= h*.09:
        return None
    upper = [x for x, y in positions if y-top_row <= jitter]
    lower = [x for x, y in positions if bottom_row-y <= jitter]
    if min(len(upper), len(lower)) < 6 or len(upper) + len(lower) != len(positions):
        return None
    # Matching columns support a two-row toolbar rather than unrelated patches
    # of preset colors somewhere within the palette search area.
    if sum(any(abs(x-other) <= jitter for other in lower) for x in upper) < 6:
        return None
    left = min(min(upper), min(lower))
    hint = (left, int(h*.18), min(w, left+int(w*.55)), max(int(h*.45), top_row-int(h*.025)))
    frame = _observed_frame(image, hint, min(96, max(12, round(w*.05))), cancelled)
    if frame:
        l, t, r, b = frame
        if (l <= left <= l + w*.06 and max(max(upper), max(lower)) < r and b < top_row
                and r-l >= w*.35 and b-t >= h*.30 and 1.05 <= (r-l)/(b-t) <= 2.5):
            return frame
    return None


def _canvas(profile_key: str, image, palette_local_positions, cancelled=lambda:False, *, side_grid=False):
    if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
    w, h = image.size
    if profile_key == 'gartic-phone':
        from GarticEngineV2 import detect_gartic_canvas
        result = detect_gartic_canvas(image,cancelled=cancelled)
        if result.found and result.box:
            # White connected components can include paper decoration. Apply the
            # execution edge check now, before planning, and only shrink.
            from EdgeDetection import verify_canvas_edges
            l, t, r, b = map(int, result.box)
            for _ in range(3):
                edges = verify_canvas_edges(image, (l, t, r-l, b-t))
                if edges.ok:
                    return (l, t, r, b), float(result.confidence)
                for side in edges.failed_sides:
                    if side.side == 'left': l += side.offset_px
                    elif side.side == 'right': r += side.offset_px
                    elif side.side == 'top': t += side.offset_px
                    elif side.side == 'bottom': b += side.offset_px
                if r-l < 200 or b-t < 120:
                    break
            return None, 0.0
        return None, float(result.confidence)
    if profile_key in ('skribbl', 'skribbl-fast'):
        def plausible(box):
            l,t,r,b = box
            return (has_canvas_bounds(box, (w, h)) and 1.05 <= (r-l)/(b-t) <= 2.5
                    and r-l >= w*.35 and b-t >= h*.30)
        step = 3
        box, confidence = _largest_light_component(image, step=step, min_ratio=.12,
                                                   accept=plausible, cancelled=cancelled)
        if box:
            # The bounding box covers entire sampled cells. Only the first
            # pixel of the final cell was observed inside the surface.
            l, t, r, b = box
            verified = (l, t, (r-1)//step*step + 1, (b-1)//step*step + 1)
            return verified, min(1.0, confidence + .08)
    # A verified palette can locate the search area for an occupied board.
    # Scan it lazily so the common blank Skribbl path needs no extra capture.
    if palette_local_positions is None:
        try:
            palette = _detect_palette(profile_key, image, (0, 0), cancelled)
        except (NoColorSwatchesError, _UnverifiedPalette):
            return None, 0.0
        palette_local_positions = palette['positions']
        side_grid = palette['side_grid']
    if not palette_local_positions:
        return None, 0.0
    if profile_key in ('skribbl', 'skribbl-fast'):
        frame = _skribbl_palette_frame(image, palette_local_positions, cancelled)
        return (frame, .82) if frame else (None, 0.0)
    if profile_key in ('sketchheads', 'sketchful'):
        columns = sorted({x for x, y in palette_local_positions})
        if len(columns) < 6:
            return None, 0.0
        palette_top = min(y for x, y in palette_local_positions)
        if side_grid:
            # The right-hand three-row grid borders a roughly 4:3 board. Its
            # leftmost color sits about one swatch pitch from the paper edge.
            # The grid establishes search bounds, never the returned rectangle.
            palette_right = max(columns)
            pitch = (palette_right - columns[0]) / 12
            def left_of_grid(box):
                l, t, r, b = box
                return (0 < columns[0]-r < 2.5*pitch and t < palette_top < b
                        and r-l >= w*.35 and b-t >= h*.40 and 1.15 <= (r-l)/(b-t) <= 1.55)
            box, _ = _largest_light_component(image, step=3, min_ratio=.12,
                                              accept=left_of_grid, cancelled=cancelled)
            frame = _observed_frame(image, box, 5, cancelled) if box else None
            return (frame, .90) if frame else (None, 0.0)
        # Exclude overlaid toolbars. Allow half a swatch pitch above the first
        # color center, so the clearance follows the actual controls and zoom.
        swatch_radius = median(b-a for a, b in zip(columns, columns[1:])) / 2
        def near_palette(box):
            l, t, r, b = box
            return (has_canvas_bounds(box, (w, h)) and l <= columns[0] < columns[-1] <= r
                    and palette_top - h*.18 <= b <= palette_top - swatch_radius + 3
                    and r-l >= w*.45 and b-t >= h*.35)
        box, _ = _largest_light_component(image, step=3, min_ratio=.12,
                                          accept=near_palette, cancelled=cancelled)
        frame = _observed_frame(image, box, 4, cancelled) if box else None
        if frame and frame[3] <= palette_top - swatch_radius:
            return frame, .82
    return None, 0.0


def _scan_palette_roi(image, roi, screen_origin, cancelled):
    ox, oy = int(screen_origin[0]) + roi[0], int(screen_origin[1]) + roi[1]
    if (roi[2]-roi[0])*(roi[3]-roi[1]) <= 1_000_000:
        with image.crop(roi) as palette_image:
            return detect_color_swatches(palette_image, (ox, oy), max_colors=96, cancelled=cancelled)
    return _palette_scan_tiles(image, roi, screen_origin, cancelled=cancelled)


def _sketchful_palette(image, origin, cancelled):
    w, h = image.size
    # Scan near a plausible paper edge first. Most of the wider right-hand
    # search area can be a patterned page background in a large browser window.
    def board_shape(box):
        l, t, r, b = box
        return r-l >= w*.35 and b-t >= h*.40 and 1.15 <= (r-l)/(b-t) <= 1.55
    paper, _ = _largest_light_component(image, step=3, min_ratio=.12, accept=board_shape, cancelled=cancelled)
    rois = []
    if paper:
        l, t, r, b = paper
        roi = (r, t+int((b-t)*.20), min(w, r+int((r-l)*.32)), t+int((b-t)*.36))
        if roi[2]-roi[0] >= 8 and roi[3]-roi[1] >= 8:
            rois.append(roi)
    # A changed layout or heavily painted board can still expose a valid grid.
    rois.append((int(w*.64), int(h*.10), w, int(h*.65)))
    for roi in rois:
        try:
            positions, rgbs, stats = _scan_palette_roi(image, roi, origin, cancelled)
        except NoColorSwatchesError:
            continue
        grid = find_sketchful_grid(positions, rgbs)
        if grid:
            return grid, stats
    return None


def _detect_palette(profile_key, image, screen_origin, cancelled):
    w, h = image.size
    if w<200 or h<120:raise ValueError('Target browser window is too small for automatic calibration.')
    side_palette = _sketchful_palette(image, screen_origin, cancelled) if profile_key == 'sketchful' else None
    if side_palette is None:
        positions, rgbs, stats = _scan_palette_roi(image, _roi(profile_key, w, h), screen_origin, cancelled)
    if cancelled():raise InterruptedError('Browser setup cancelled.')

    names = None
    method = 'visual swatch row'
    palette_confidence = 0.0
    preset = PRESETS.get(profile_key)
    if side_palette is not None:
        grid, stats = side_palette
        cells, centers, ys, pitch = grid
        recover_sketchful_black(image, cells, centers, ys, pitch, screen_origin)
        ordered = sorted(cells.items())
        names = [f'R{row+1}C{column+1}' for (row, column), cell in ordered]
        positions = [(x, y) for index, (x, y, rgb) in ordered]
        rgbs = [rgb for index, (x, y, rgb) in ordered]
        palette_confidence = len(cells) / 39
        method = 'Sketchful right-hand color grid + screen verification'
    elif preset is not None:
        matches = _match_preset(positions, rgbs, preset)
        if profile_key=='gartic-phone':
            matches=_verify_gartic_grid(image,matches,preset,screen_origin)
        required = 18 if profile_key.startswith('skribbl') else 36
        if len(matches) < required:
            raise _UnverifiedPalette(f'Automatic {profile_key} palette detection found only {len(matches)} verified colors; {required} are required for a safe match.')
        names = [m[0] for m in matches]
        positions = [m[1] for m in matches]
        rgbs = [m[2] for m in matches]
        mean_error = sum(m[3] for m in matches) / max(1, len(matches))
        coverage = len(matches) / len(preset.colors)
        palette_confidence = max(0.0, min(1.0, .65*coverage + .35*max(0.0, 1.0-mean_error/18.0)))
        method = f'{profile_key} preset + screen verification'
    else:
        # Positions above are absolute; convert to client-local for clustering.
        local_positions = [(x-int(screen_origin[0]), y-int(screen_origin[1])) for x,y in positions]
        row = _row_cluster(local_positions, rgbs, image_width=w, image_height=h)
        positions = [(x+int(screen_origin[0]), y+int(screen_origin[1])) for x,y,_ in row]
        rgbs = [rgb for _,_,rgb in row]
        names = [f'Auto color {i+1}' for i in range(len(row))]
        palette_confidence = min(.96, .62 + len(row)*.02)
        method = 'toolbar row geometry + solid swatches'

    px = [p[0] for p in positions]; py = [p[1] for p in positions]
    palette_box = (min(px), min(py), max(px)+1, max(py)+1) if positions else None
    if cancelled():raise InterruptedError('Browser setup cancelled.')
    return {
        'positions': positions,
        'rgbs': rgbs,
        'names': names,
        'palette_confidence': palette_confidence,
        'palette_box': palette_box,
        'method': method,
        'stats': stats,
        'side_grid': side_palette is not None,
    }


def _canvas_result(box, confidence, origin):
    if box is not None:
        l, t, r, b = box
        x, y = origin
        box = (x+l, y+t, x+r, y+b)
    return {'canvas_box': box, 'canvas_confidence': confidence}


def detect_browser_setup(profile_key: str, image, *, screen_origin=(0,0),cancelled=lambda:False):
    if cancelled():raise InterruptedError('Browser setup cancelled.')
    profile_key = str(profile_key or '').lower()
    if profile_key not in SUPPORTED_BROWSER_PROFILES:
        raise ValueError('Automatic browser calibration is not available for this profile.')
    screen_origin = screen_point(screen_origin, 'screen origin')
    with (nullcontext(image) if image.mode == 'RGB' else image.convert('RGB')) as rgb:
        palette = _detect_palette(profile_key, rgb, screen_origin, cancelled)
        ox, oy = screen_origin
        positions = [(x-ox, y-oy) for x, y in palette['positions']]
        box, confidence = _canvas(profile_key, rgb, positions, cancelled=cancelled, side_grid=palette.pop('side_grid'))
    if cancelled():raise InterruptedError('Browser setup cancelled.')
    return {**palette, **_canvas_result(box, confidence, screen_origin)}


def auto_calibrate_browser(profile_key: str, target_metadata: dict, palette_path: Path, *, screenshot=None,
                           min_confidence: float = .68,cancelled=lambda:False) -> BrowserCalibrationResult:
    if cancelled():raise InterruptedError('Browser calibration cancelled.')
    min_confidence=bounded_number(min_confidence,'Palette confidence threshold')
    profile_key = str(profile_key or '').lower()
    if profile_key not in SUPPORTED_BROWSER_PROFILES:
        raise ValueError('Automatic browser calibration is not available for this profile.')
    client_rect = _rect(target_metadata.get('client_rect'))
    left, top, right, bottom = client_rect
    with calibration_screenshot(screenshot,client_rect) as screenshot:
        detected = detect_browser_setup(profile_key, screenshot, screen_origin=(left, top),cancelled=cancelled)
        palette_confidence = finite_confidence(detected['palette_confidence'])
        if palette_confidence < float(min_confidence):
            raise ValueError(f'Palette confidence is too low ({palette_confidence*100:.0f}%). Manual fallback is safer for this layout.')
        if cancelled():raise InterruptedError('Browser calibration cancelled.')
        save_calibration(detected['positions'], detected['rgbs'], Path(palette_path),
                         names=detected['names'], anchor=make_anchor(client_rect), profile_key=profile_key,
                         state='verified', verification={'method':str(detected['method']),
                         'confidence':palette_confidence, 'source':'browser-screen-verification'})
        return BrowserCalibrationResult(
            profile_key=profile_key,
            palette_count=len(detected['positions']),
            palette_confidence=palette_confidence,
            canvas_box=detected['canvas_box'],
            canvas_confidence=float(detected['canvas_confidence']),
            palette_box=detected['palette_box'],
            method=str(detected['method']),
            note='Read-only automatic setup. No mouse input was generated.',
        )


def detect_browser_canvas(profile_key, image, *, screen_origin=(0,0),cancelled=lambda:False):
    """Return only geometry supported by this profile's visible landmarks."""
    profile_key=str(profile_key or '').lower()
    if profile_key not in SUPPORTED_BROWSER_PROFILES:
        raise ValueError('Automatic canvas detection is not available for this profile.')
    screen_origin=screen_point(screen_origin,'screen origin')
    if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
    if image.width < 200 or image.height < 120:
        return _canvas_result(None, 0.0, screen_origin)
    with (nullcontext(image) if image.mode == 'RGB' else image.convert('RGB')) as rgb:
        box, confidence = _canvas(profile_key, rgb, None, cancelled=cancelled)
    if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
    return _canvas_result(box, confidence, screen_origin)


def _verify_gartic_grid(image,matches,preset,origin):
    """Anchor every swatch to the 6x12 grid, excluding the selected-colour panel."""
    import re
    import numpy as np
    rows={};cols={}
    for name,(x,y),rgb,error in matches:
        m=re.fullmatch(r'R(\d+)C(\d+)',name)
        if not m:continue
        row,col=map(int,m.groups());rows.setdefault(row,[]).append(y);cols.setdefault(col,[]).append(x)
    if len(rows)<8 or len(cols)!=6:return matches
    xs={i:float(np.median(v)) for i,v in cols.items()};ys={i:float(np.median(v)) for i,v in rows.items()}
    # Infer missing rows from the verified lattice; screen samples still decide.
    row_ids=sorted(ys);steps=[(ys[b]-ys[a])/(b-a) for a,b in zip(row_ids,row_ids[1:])]
    step=float(np.median(steps));ystart=float(np.median([ys[i]-(i-1)*step for i in ys]))
    xsteps=np.diff([xs[i] for i in sorted(xs)])
    if step<4 or np.any(xsteps<4) or max(xsteps)>min(xsteps)*1.3:return matches
    result=[];ox,oy=origin
    for name,expected in zip(preset.names,preset.colors):
        m=re.fullmatch(r'R(\d+)C(\d+)',name)
        if not m:continue
        row,col=map(int,m.groups());x=round(xs[col]);y=round(ystart+(row-1)*step)
        lx,ly=x-int(ox),y-int(oy)
        if lx<2 or ly<2 or lx>=image.width-2 or ly>=image.height-2:continue
        rgb=tuple(map(int,np.median(np.asarray(image.crop((lx-2,ly-2,lx+3,ly+3))).reshape(-1,3),axis=0)))
        error=_rgb_distance(rgb,expected)
        if error<=18:result.append((name,(x,y),rgb,error))
    if len(result)<36:raise ValueError('Gartic palette grid could not be verified safely. Show the whole palette.')
    return result
