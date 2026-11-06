"""Deterministic one-click calibration for supported browser drawing games.

v1.0.70 removes the normal need to capture every palette/tool position by hand.
The detector is read-only: it takes a screenshot of the already selected target
window, finds the visible palette and a conservative drawable canvas, then saves
anchored palette coordinates. It never sends mouse input.

Manual calibration remains a fallback for changed/unknown layouts.
"""
from __future__ import annotations
from CalibrationValidation import calibration_screenshot

from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Sequence

from CalibrationAnchors import make_anchor
from Colors import save_calibration
from PaletteMaps import PRESETS, detect_color_swatches, NoColorSwatchesError
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
        raise ValueError('Automatic palette detection could not find a stable color row.')
    # Deduplicate near-identical colors while keeping visual order.
    clean = []
    for item in best:
        if any(_rgb_distance(item[2], old[2]) < 6 for old in clean):
            continue
        clean.append(item)
    if len(clean) < 6:
        raise ValueError('Automatic palette row contained too few distinct colors.')
    return clean[:32]


def _near_white(rgb):
    r, g, b = map(int, rgb[:3])
    return min(r, g, b) >= 235 and max(r, g, b) - min(r, g, b) <= 24


def _largest_light_component(image, *, step: int = 4, min_ratio: float = .08, cancelled=lambda:False):
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
    for first in range(0,sh,64):
        if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
        with image.crop((0,first*step,w,min(h,(first+64)*step))) as strip:
            a=np.asarray(strip)[::step,::step]
            lo=a.min(axis=2);hi=a.max(axis=2)
            mask.extend(bytearray(row.tobytes()) for row in ((lo>=235)&((hi-lo)<=24)))
    best = None; best_area = 0
    min_area = max(40, int(sw * sh * min_ratio))
    for sy in range(sh):
        if sy%32==0 and cancelled():raise InterruptedError('Browser canvas scan cancelled.')
        for sx in range(sw):
            if not mask[sy][sx]:
                continue
            mask[sy][sx] = 0
            stack = [(sx, sy)]; left = right = sx; top = bottom = sy; area = 0
            while stack:
                x, y = stack.pop(); area += 1
                if area%4096==0 and cancelled():raise InterruptedError('Browser canvas scan cancelled.')
                left = min(left, x); right = max(right, x); top = min(top, y); bottom = max(bottom, y)
                for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if 0 <= nx < sw and 0 <= ny < sh and mask[ny][nx]:
                        mask[ny][nx] = 0; stack.append((nx,ny))
            if area >= min_area and area > best_area:
                best_area = area; best = (left*step, top*step, min(w,(right+1)*step), min(h,(bottom+1)*step))
    if best is None:
        return None, 0.0
    l,t,r,b = best
    box_area = max(1, (r-l)*(b-t))
    density = min(1.0, (best_area * step * step) / box_area)
    ratio = box_area / max(1, w*h)
    confidence = max(0.0, min(1.0, .55*density + .45*min(1.0, ratio/.45)))
    return best, confidence


def _canvas(profile_key: str, image, palette_local_positions, cancelled=lambda:False):
    if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
    w, h = image.size
    if profile_key == 'gartic-phone':
        from GarticEngineV2 import detect_gartic_canvas
        result = detect_gartic_canvas(image)
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
        box, confidence = _largest_light_component(image, step=3, min_ratio=.12,cancelled=cancelled)
        if box:
            l,t,r,b = box
            aspect = (r-l) / max(1, b-t)
            if 1.05 <= aspect <= 2.5 and (r-l) >= w*.35 and (b-t) >= h*.30:
                return box, min(1.0, confidence + .08)
        # A partly drawn canvas may no longer be one connected white region.
        # Skribbl keeps the color bar directly below the left edge of the canvas,
        # so use the *verified palette row* as a conservative structural fallback.
        if len(palette_local_positions) >= 12:
            xs=[p[0] for p in palette_local_positions];ys=[p[1] for p in palette_local_positions]
            left=max(0,min(xs));bottom=max(int(h*.45),min(ys)-int(h*.025))
            top=int(h*.18);right=min(w,int(left+w*.55))
            if right-left>=w*.35 and bottom-top>=h*.30:
                return (left,top,right,bottom), max(.74, confidence)
        return None, confidence
    if profile_key in ('sketchheads', 'sketchful'):
        # SketchHeads intentionally uses an almost full-page canvas with controls
        # overlaid at the top/bottom. Build a conservative safe rectangle from
        # the detected palette row rather than treating UI controls as drawable.
        palette_y = min((p[1] for p in palette_local_positions), default=int(h*.86))
        box = (int(w*.025), int(h*.13), int(w*.975), max(int(h*.55), palette_y-int(h*.065)))
        return box, .82 if palette_local_positions else .70
    return None, 0.0


def detect_browser_setup(profile_key: str, image, *, screen_origin=(0,0),cancelled=lambda:False):
    if cancelled():raise InterruptedError('Browser setup cancelled.')
    profile_key = str(profile_key or '').lower()
    if profile_key not in SUPPORTED_BROWSER_PROFILES:
        raise ValueError('Automatic browser calibration is not available for this profile.')
    screen_origin=screen_point(screen_origin,'screen origin')
    image = image if image.mode=='RGB' else image.convert('RGB')
    w, h = image.size
    if w<200 or h<120:raise ValueError('Target browser window is too small for automatic calibration.')
    roi = _roi(profile_key, w, h)
    ox, oy = int(screen_origin[0]) + roi[0], int(screen_origin[1]) + roi[1]
    if (roi[2]-roi[0])*(roi[3]-roi[1]) <= 1_000_000:
        with image.crop(roi) as palette_image:
            positions, rgbs, stats = detect_color_swatches(palette_image, (ox, oy), max_colors=96,cancelled=cancelled)
    else:
        # v1.0.115: 144-DPI/4K browser windows can make the normal relative
        # palette ROI exceed PaletteMaps' deliberate 1M-pixel safety bound.
        # Keep that bound and scan the ROI in bounded overlapping tiles instead.
        positions, rgbs, stats = _palette_scan_tiles(image, roi, screen_origin,cancelled=cancelled)
    if cancelled():raise InterruptedError('Browser setup cancelled.')

    names = None
    method = 'visual swatch row'
    palette_confidence = 0.0
    preset = PRESETS.get(profile_key)
    if preset is not None:
        matches = _match_preset(positions, rgbs, preset)
        if profile_key=='gartic-phone':
            matches=_verify_gartic_grid(image,matches,preset,screen_origin)
        required = 18 if profile_key.startswith('skribbl') else 36
        if len(matches) < required:
            raise ValueError(f'Automatic {profile_key} palette detection found only {len(matches)} verified colors; {required} are required for a safe match.')
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

    local_palette_positions = [(x-int(screen_origin[0]), y-int(screen_origin[1])) for x,y in positions]
    canvas_local, canvas_confidence = _canvas(profile_key, image, local_palette_positions,cancelled=cancelled)
    canvas_abs = None
    if canvas_local is not None:
        l,t,r,b = canvas_local
        canvas_abs = (l+int(screen_origin[0]), t+int(screen_origin[1]), r+int(screen_origin[0]), b+int(screen_origin[1]))

    px = [p[0] for p in positions]; py = [p[1] for p in positions]
    palette_box = (min(px), min(py), max(px)+1, max(py)+1) if positions else None
    if cancelled():raise InterruptedError('Browser setup cancelled.')
    return {
        'positions': positions,
        'rgbs': rgbs,
        'names': names,
        'canvas_box': canvas_abs,
        'canvas_confidence': canvas_confidence,
        'palette_confidence': palette_confidence,
        'palette_box': palette_box,
        'method': method,
        'stats': stats,
    }


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
    """Read-only canvas detection without requiring a colour palette."""
    profile_key=str(profile_key or '').lower()
    if profile_key not in SUPPORTED_BROWSER_PROFILES:
        raise ValueError('Automatic canvas detection is not available for this profile.')
    screen_origin=screen_point(screen_origin,'screen origin')
    box,confidence=_canvas(profile_key,image if image.mode=='RGB' else image.convert('RGB'),[],cancelled=cancelled)
    if box is not None:
        l,t,r,b=box;ox,oy=map(int,screen_origin);box=(l+ox,t+oy,r+ox,b+oy)
    if cancelled():raise InterruptedError('Browser canvas scan cancelled.')
    return {'canvas_box':box,'canvas_confidence':float(confidence)}


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
