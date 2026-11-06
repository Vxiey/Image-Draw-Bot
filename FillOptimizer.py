"""Safe large-area planning for palette drawings.

v1.0.7 keeps Paint's bucket tool conservative.  A blank-canvas base fill is
allowed only for a strongly connected background.  Interior fill regions are
limited to large, safe connected components; Image Draw Bot draws a
closed perimeter before clicking Fill so a failed/ambiguous segmentation cannot
silently flood an unrelated part of the canvas.  v1.0.52 adds a brush-inset
source mask so planned fills too close to the canvas edge fall back to normal
strokes instead of bucket Fill.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, asdict
from math import sqrt

from Colors import allColors
from PixelData import closest_color
from SafeFillMask import choose_safe_background_seed, source_fill_margin_px

# ``Auto`` remains accepted for settings written by v1.0.6 and maps to Balanced.
BACKGROUND_FILL_MODES = ("Auto", "Off", "Conservative", "Balanced", "Aggressive")
BACKGROUND_SIMPLIFICATION_MODES = ("Off", "Conservative", "Balanced", "Strong")
FILL_ENGINES = ("Auto", "Safe rectangles", "Closed regions v2")


@dataclass(frozen=True)
class BackgroundFillPlan:
    enabled: bool
    color_index: int | None = None
    rgb: tuple[int, int, int] | None = None
    border_confidence: float = 0.0
    image_coverage: float = 0.0
    seed_pixel: tuple[int, int] = (1, 1)
    reason: str = ""
    mode: str = "Balanced"

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class FillRegionPlan:
    color_index: int
    rgb: tuple[int, int, int]
    bbox: tuple[int, int, int, int]
    seed_pixel: tuple[int, int]
    area_pixels: int
    bbox_density: float
    estimated_saved_strokes: int
    # v1.0.39 Better Fill metadata. Defaults keep v1.0.7 callers compatible.
    strategy: str = "rectangle"
    contour: tuple[tuple[float, float], ...] = ()
    row_spans: tuple[tuple[int, int, int], ...] = ()
    guard_pixels: tuple[tuple[int, int], ...] = ()
    perimeter_pixels: int = 0
    scanline_runs: int = 0
    safety_score: float = 1.0

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class BackgroundSimplification:
    enabled: bool
    rgb: tuple[int, int, int] | None = None
    color_index: int | None = None
    changed_pixels: int = 0
    coverage: float = 0.0
    border_confidence: float = 0.0
    reason: str = ""

    def as_dict(self):
        return asdict(self)


def _normalize_fill_mode(mode: str) -> str:
    if mode == "Auto":
        return "Balanced"
    return mode


def validate_background_fill(mode: str) -> str:
    if mode not in BACKGROUND_FILL_MODES:
        raise ValueError("Auto Fill must be Off, Conservative, Balanced or Aggressive.")
    return mode


def validate_background_simplification(mode: str) -> str:
    if mode not in BACKGROUND_SIMPLIFICATION_MODES:
        raise ValueError("Background simplification must be Off, Conservative, Balanced or Strong.")
    return mode


def validate_fill_engine(engine: str) -> str:
    if engine not in FILL_ENGINES:
        raise ValueError("Fill engine must be Auto, Safe rectangles or Closed regions v2.")
    return engine


def resolve_fill_engine(engine: str, mode: str = "Balanced") -> str:
    validate_fill_engine(engine)
    if _normalize_fill_mode(mode) == "Off":
        return "Off"
    return "Closed regions v2" if engine == "Auto" else engine


def _quantize(rgb, step=24):
    return tuple(max(0, min(255, round(int(v) / step) * step)) for v in rgb[:3])


def _border_samples(rgb):
    w, h = rgb.size
    px = rgb.load(); samples = []
    for x in range(w):
        samples.append(_quantize(px[x, 0])); samples.append(_quantize(px[x, h - 1]))
    for y in range(1, h - 1):
        samples.append(_quantize(px[0, y])); samples.append(_quantize(px[w - 1, y]))
    return samples


def _dominant_border(rgb):
    border = _border_samples(rgb)
    winner, count = Counter(border).most_common(1)[0]
    return winner, count / max(1, len(border))


def _distance2(a, b):
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3))


def simplify_background(image, mode="Balanced"):
    """Simplify only a border-connected background to one calibrated color.

    The flood starts at matching border pixels and therefore does not rewrite a
    similarly colored island enclosed inside the subject.  This is deliberately
    done before palette stroke extraction so it reduces noisy JPEG/gradient runs
    and makes a later base Fill both safer and much cheaper.
    """
    validate_background_simplification(mode)
    rgb = image.convert("RGB")
    if mode == "Off":
        return rgb, BackgroundSimplification(False, reason="Background simplification is disabled.")
    w, h = rgb.size
    if w < 8 or h < 8:
        return rgb, BackgroundSimplification(False, reason="Image is too small for background simplification.")
    winner, confidence = _dominant_border(rgb)
    cfg = {
        "Conservative": (.78, 26, .16),
        "Balanced": (.62, 38, .12),
        "Strong": (.48, 54, .08),
    }[mode]
    min_conf, tolerance, min_coverage = cfg
    if confidence < min_conf:
        return rgb, BackgroundSimplification(False, border_confidence=confidence,
                                             reason="Border colors are too mixed to simplify safely.")
    try:
        index = int(closest_color(winner)); mapped = tuple(map(int, allColors[index].RGB))
    except Exception:
        return rgb, BackgroundSimplification(False, border_confidence=confidence,
                                             reason="No calibrated palette color matches the background.")

    px = rgb.load(); tol2 = tolerance * tolerance
    visited = bytearray(w * h); queue = deque()
    def push(x, y):
        pos = y * w + x
        if not visited[pos] and _distance2(px[x, y], winner) <= tol2:
            visited[pos] = 1; queue.append((x, y))
    for x in range(w):
        push(x, 0); push(x, h - 1)
    for y in range(1, h - 1):
        push(0, y); push(w - 1, y)
    points = []
    while queue:
        x, y = queue.popleft(); points.append((x, y))
        if x: push(x - 1, y)
        if x + 1 < w: push(x + 1, y)
        if y: push(x, y - 1)
        if y + 1 < h: push(x, y + 1)
    coverage = len(points) / max(1, w * h)
    if coverage < min_coverage:
        return rgb, BackgroundSimplification(False, mapped, index, 0, coverage, confidence,
                                             "Connected background coverage is too small to simplify.")
    out = rgb.copy(); out_px = out.load(); changed = 0
    for x, y in points:
        if tuple(out_px[x, y]) != mapped:
            out_px[x, y] = mapped; changed += 1
    return out, BackgroundSimplification(True, mapped, index, changed, coverage, confidence,
                                         "Border-connected background simplified to one calibrated palette color.")


def detect_background(image, mode="Balanced", *, min_border=None, min_coverage=None, safe_margin_px=0) -> BackgroundFillPlan:
    validate_background_fill(mode)
    normalized = _normalize_fill_mode(mode)
    if normalized == "Off":
        return BackgroundFillPlan(False, reason="Auto Fill is disabled.", mode=normalized)
    rgb = image.convert("RGB"); w, h = rgb.size
    if w < 8 or h < 8:
        return BackgroundFillPlan(False, reason="Image is too small for safe background detection.", mode=normalized)
    cfg = {
        "Conservative": (.78, .34, 28),
        "Balanced": (.64, .25, 36),
        "Aggressive": (.50, .18, 48),
    }[normalized]
    if min_border is None: min_border = cfg[0]
    if min_coverage is None: min_coverage = cfg[1]
    winner, confidence = _dominant_border(rgb)
    if confidence < min_border:
        return BackgroundFillPlan(False, border_confidence=confidence,
                                  reason="Border colors are too mixed for a safe automatic fill.", mode=normalized)
    px = rgb.load(); tol2 = cfg[2] * cfg[2]; total = w * h; hit = 0
    for y in range(h):
        for x in range(w):
            if _distance2(px[x, y], winner) <= tol2:
                hit += 1
    coverage = hit / max(1, total)
    if coverage < min_coverage:
        return BackgroundFillPlan(False, border_confidence=confidence, image_coverage=coverage,
                                  reason="The border color does not cover enough of the image to use Fill safely.", mode=normalized)
    try:
        index = int(closest_color(winner)); mapped = tuple(map(int, allColors[index].RGB))
        if min(mapped) >= 242:
            return BackgroundFillPlan(False, border_confidence=confidence, image_coverage=coverage,
                                      reason="The detected background is already effectively white; no Fill pass is needed.", mode=normalized)
    except Exception:
        return BackgroundFillPlan(False, border_confidence=confidence, image_coverage=coverage,
                                  reason="No calibrated palette color matches the detected background.", mode=normalized)
    margin = max(1, int(round(float(safe_margin_px)))) if safe_margin_px else 1
    margin = min(margin, max(1, (min(w, h) - 3) // 2))
    candidates = choose_safe_background_seed(
        [(margin, margin), (w - 1 - margin, margin), (margin, h - 1 - margin),
         (w - 1 - margin, h - 1 - margin), (w // 2, h // 2)],
        (w, h), margin)
    seed = min(candidates, key=lambda p: _distance2(px[p[0], p[1]], winner))
    return BackgroundFillPlan(True, index, mapped, confidence, coverage, seed,
                              "Dominant border/background color is suitable for a base Fill pass.", normalized)


def _palette_labels(image):
    rgb = image.convert("RGB"); w, h = rgb.size; px = rgb.load()
    return rgb, w, h, [int(closest_color(tuple(px[x, y]))) for y in range(h) for x in range(w)]


def _component_row_spans(points, w):
    rows = defaultdict(list)
    for pos in points:
        rows[pos // w].append(pos % w)
    spans = []
    for y in sorted(rows):
        xs = sorted(rows[y]); left = right = xs[0]
        for x in xs[1:]:
            if x == right + 1:
                right = x
            else:
                spans.append((y, left, right)); left = right = x
        spans.append((y, left, right))
    return tuple(spans)


def _simplify_closed_loop(loop):
    """Remove collinear grid vertices while keeping a closed polygon."""
    if len(loop) < 5:
        return tuple(loop)
    pts = list(loop[:-1])
    changed = True
    while changed and len(pts) >= 4:
        changed = False; out = []; n = len(pts)
        for i, cur in enumerate(pts):
            prev = pts[(i - 1) % n]; nxt = pts[(i + 1) % n]
            if (prev[0] == cur[0] == nxt[0]) or (prev[1] == cur[1] == nxt[1]):
                changed = True; continue
            out.append(cur)
        pts = out
    if not pts:
        return ()
    pts.append(pts[0])
    return tuple(pts)


def _trace_component_contours(points, w, h):
    """Trace exact cell-edge contours for one 4-connected palette component.

    Ambiguous self-touching grid vertices are rejected instead of guessed. That
    keeps bucket Fill conservative: an unsafe shape simply retains its original
    scanline strokes.
    """
    cells = {(pos % w, pos // w) for pos in points}
    edges = []
    for x, y in cells:
        if (x, y - 1) not in cells: edges.append(((x, y), (x + 1, y)))
        if (x + 1, y) not in cells: edges.append(((x + 1, y), (x + 1, y + 1)))
        if (x, y + 1) not in cells: edges.append(((x + 1, y + 1), (x, y + 1)))
        if (x - 1, y) not in cells: edges.append(((x, y + 1), (x, y)))
    outgoing = defaultdict(list); incoming = defaultdict(int)
    for a, b in edges:
        outgoing[a].append(b); incoming[b] += 1
    vertices = set(outgoing) | set(incoming)
    if any(len(outgoing.get(v, ())) != 1 or incoming.get(v, 0) != 1 for v in vertices):
        return (), "ambiguous boundary"
    remaining = set(edges); loops = []
    while remaining:
        a, b = next(iter(remaining)); loop = [a]; cur = a; nxt = b
        guard = 0
        while True:
            edge = (cur, nxt)
            if edge not in remaining:
                return (), "open boundary"
            remaining.remove(edge); loop.append(nxt); guard += 1
            if nxt == loop[0]: break
            cur = nxt
            choices = outgoing.get(cur, ())
            if len(choices) != 1 or guard > len(edges) + 2:
                return (), "open boundary"
            nxt = choices[0]
        simplified = _simplify_closed_loop(loop)
        if len(simplified) < 5:
            return (), "degenerate boundary"
        loops.append(simplified)
    return tuple(loops), ""


def _loop_perimeter(loop):
    return int(round(sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(loop, loop[1:]))))


def _interior_seed(points, w, h, cx, cy):
    cells = {(pos % w, pos // w) for pos in points}
    interior = [(x, y) for x, y in cells
                if x > 0 and y > 0 and x + 1 < w and y + 1 < h
                and (x - 1, y) in cells and (x + 1, y) in cells
                and (x, y - 1) in cells and (x, y + 1) in cells]
    if not interior:
        return None
    return min(interior, key=lambda p: abs(p[0] - cx) + abs(p[1] - cy))


def _outside_guard_pixels(points, w, h, limit=8):
    cells = {(pos % w, pos // w) for pos in points}; candidates = []
    # Two pixels outside the component so the contour stroke itself should not
    # alter the guard sample. These are checked after Fill to catch leakage.
    for x, y in cells:
        for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
            n1 = (x + dx, y + dy); n2 = (x + 2*dx, y + 2*dy)
            if n1 in cells or n2 in cells: continue
            if 0 <= n2[0] < w and 0 <= n2[1] < h:
                candidates.append(n2)
    if not candidates: return ()
    unique = sorted(set(candidates), key=lambda p: (p[1], p[0]))
    if len(unique) <= limit: return tuple(unique)
    step = (len(unique) - 1) / max(1, limit - 1)
    return tuple(unique[round(i * step)] for i in range(limit))


def _rectangle_contour(x0, y0, x1, y1):
    # Grid-edge perimeter, closed explicitly.
    return ((x0, y0), (x1 + 1, y0), (x1 + 1, y1 + 1), (x0, y1 + 1), (x0, y0))


def _component_to_region(color, points, w, h, mode, engine, safe_margin_px=0, rgb_override=None):
    normalized = _normalize_fill_mode(mode)
    x_values = [p % w for p in points]; y_values = [p // w for p in points]
    x0, x1 = min(x_values), max(x_values); y0, y1 = min(y_values), max(y_values)
    if x0 == 0 or y0 == 0 or x1 == w - 1 or y1 == h - 1:
        return None, "border"
    safe_margin = max(0, int(round(float(safe_margin_px or 0))))
    if safe_margin:
        safe_margin = min(safe_margin, max(0, (min(w, h) - 3) // 2))
        if x0 < safe_margin or y0 < safe_margin or x1 > w - 1 - safe_margin or y1 > h - 1 - safe_margin:
            return None, "outside safe fill mask"
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    area = len(points); density = area / max(1, bw * bh)
    spans = _component_row_spans(points, w); run_count = len(spans)
    if engine == "Safe rectangles":
        cfg = {"Conservative": (70, .997, 10), "Balanced": (42, .990, 7), "Aggressive": (24, .970, 5)}[normalized]
        min_area, min_density, min_saved = cfg
        if area < min_area or bw < 5 or bh < 5: return None, "small"
        if density < min_density: return None, "not rectangular"
        estimated_saved = max(0, run_count - 4)
        if estimated_saved < min_saved: return None, "low savings"
        seed = _interior_seed(points, w, h, (x0+x1)//2, (y0+y1)//2)
        if seed is None: return None, "no interior seed"
        contour = _rectangle_contour(x0, y0, x1, y1)
        perimeter = _loop_perimeter(contour)
        score = min(1.0, density * .7 + min(1.0, area / 500.0) * .3)
        _rgb=tuple(map(int,rgb_override)) if rgb_override is not None else tuple(map(int, allColors[color].RGB))
        return FillRegionPlan(color, _rgb, (x0,y0,x1,y1), seed,
                              area, density, estimated_saved, "rectangle", contour, spans,
                              _outside_guard_pixels(points,w,h), perimeter, run_count, score), ""

    cfg = {
        "Conservative": (110, 56, 12, 8.0),
        "Balanced": (64, 96, 8, 12.0),
        "Aggressive": (36, 180, 4, 20.0),
    }[normalized]
    min_area, max_vertices, min_saved, max_shape_ratio = cfg
    if area < min_area or bw < 4 or bh < 4: return None, "small"
    loops, why = _trace_component_contours(points, w, h)
    if not loops: return None, why or "untraceable"
    if len(loops) != 1: return None, "holes"
    contour = loops[0]; vertices = len(contour) - 1; perimeter = _loop_perimeter(contour)
    if vertices > max_vertices: return None, "complex contour"
    shape_ratio = perimeter / max(1.0, sqrt(area))
    if shape_ratio > max_shape_ratio: return None, "high perimeter"
    seed = _interior_seed(points, w, h, (x0+x1)//2, (y0+y1)//2)
    if seed is None: return None, "no interior seed"
    # One continuous contour plus one Fill click replaces the source scanline runs.
    estimated_saved = max(0, run_count - 1)
    if estimated_saved < min_saved: return None, "low savings"
    complexity_factor = max(0.0, 1.0 - (vertices / max(1, max_vertices)))
    shape_factor = max(0.0, 1.0 - (shape_ratio / max_shape_ratio))
    size_factor = min(1.0, area / max(1.0, min_area * 5.0))
    score = max(0.0, min(1.0, .45*complexity_factor + .35*shape_factor + .20*size_factor))
    _rgb=tuple(map(int,rgb_override)) if rgb_override is not None else tuple(map(int, allColors[color].RGB))
    return FillRegionPlan(color, _rgb, (x0,y0,x1,y1), seed,
                          area, density, estimated_saved, "closed-contour", contour, spans,
                          _outside_guard_pixels(points,w,h), perimeter, run_count, score), ""


def detect_fill_regions(image, mode="Balanced", *, engine="Auto", max_regions=12,
                        cancelled=lambda: False, return_meta=False, safe_margin_px=0):
    """Find interior regions that can be safely contour-closed then bucket-filled.

    v1.0.39 accepts non-rectangular, hole-free 4-connected components when the
    contour is unambiguous and economical. Unsafe/complex components are not
    modified: their original scanline strokes remain as the automatic fallback.
    """
    validate_background_fill(mode); validate_fill_engine(engine)
    normalized = _normalize_fill_mode(mode); resolved = resolve_fill_engine(engine, mode)
    safe_margin = max(0, int(round(float(safe_margin_px or 0))))
    if safe_margin:
        safe_margin = min(safe_margin, max(1, (min(image.size) - 3) // 2))
    empty_meta = {"engine": resolved, "accepted_regions": 0, "contour_regions": 0,
                  "rectangle_regions": 0, "fallback_scanline_regions": 0,
                  "estimated_saved_strokes": 0, "safe_fill_mask_margin_px": safe_margin, "rejected": {},
                  "total_components": 0, "interior_components": 0, "candidate_regions": 0}
    if normalized == "Off": return ([], empty_meta) if return_meta else []
    rgb, w, h, labels = _palette_labels(image)
    seen = bytearray(w * h); candidates = []; rejected = Counter(); fallback = 0; total_components = 0; interior_components = 0
    # Candidate-size threshold is intentionally lower than the final acceptance
    # threshold so metadata can report useful scanline fallbacks.
    floor = {"Conservative": 70, "Balanced": 36, "Aggressive": 20}[normalized]
    for start in range(w * h):
        if seen[start]: continue
        if cancelled(): raise InterruptedError()
        color = labels[start]; queue = [start]; seen[start] = 1; points = []
        touches_border = False
        while queue:
            pos = queue.pop(); x, y = pos % w, pos // w; points.append(pos)
            if len(points)%1024==0 and cancelled(): raise InterruptedError()
            touches_border = touches_border or x == 0 or y == 0 or x == w-1 or y == h-1
            for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if 0 <= nx < w and 0 <= ny < h:
                    n = ny*w + nx
                    if not seen[n] and labels[n] == color:
                        seen[n] = 1; queue.append(n)
        total_components += 1
        if not touches_border:
            interior_components += 1
        if touches_border or len(points) < floor:
            continue
        region, why = _component_to_region(color, points, w, h, normalized, resolved, safe_margin_px=safe_margin)
        if region is None:
            fallback += 1; rejected[why or "unsafe"] += 1
            continue
        candidates.append(region)
    candidates.sort(key=lambda r: (r.estimated_saved_strokes, r.area_pixels, r.safety_score), reverse=True)
    accepted = candidates[:max_regions]
    # Candidates beyond the cap stay as scanline strokes too.
    fallback += max(0, len(candidates) - len(accepted))
    meta = {"engine": resolved, "accepted_regions": len(accepted),
            "contour_regions": sum(r.strategy == "closed-contour" for r in accepted),
            "rectangle_regions": sum(r.strategy == "rectangle" for r in accepted),
            "fallback_scanline_regions": fallback,
            "estimated_saved_strokes": sum(r.estimated_saved_strokes for r in accepted),
            "safe_fill_mask_margin_px": safe_margin,
            "rejected": dict(rejected),
            "total_components": total_components,
            "interior_components": interior_components,
            "candidate_regions": len(candidates)}
    return (accepted, meta) if return_meta else accepted



def detect_fill_regions_from_groups(groups, palette_rgb, image_size, mode="Balanced", *, engine="Auto", max_regions=256,
                                    cancelled=lambda: False, return_meta=False, safe_margin_px=0):
    """Find safe connected fill candidates from already-quantized stroke groups.

    Unlike :func:`detect_fill_regions`, this keeps the group's own color index.
    That makes it safe for Adaptive Exact/custom RGB plans where index N refers
    to ``plan_colors[N]`` rather than the fixed global Paint palette.  Only
    pixels explicitly present in ``groups`` participate; skipped background is
    never invented.
    """
    validate_background_fill(mode); validate_fill_engine(engine)
    normalized=_normalize_fill_mode(mode);resolved=resolve_fill_engine(engine,mode)
    if normalized == "Off":
        meta={"engine":resolved,"accepted_regions":0,"contour_regions":0,"rectangle_regions":0,
              "fallback_scanline_regions":0,"estimated_saved_strokes":0,"rejected":{},
              "total_components":0,"interior_components":0,"candidate_regions":0,
              "source":"quantized execution groups","dynamic_palette_indexes":True}
        return ([],meta) if return_meta else []
    w,h=max(1,int(image_size[0])),max(1,int(image_size[1]))
    safe_margin=max(0,int(round(float(safe_margin_px or 0))))
    labels=[-1]*(w*h)
    for color,group in enumerate(groups or ()):
        if cancelled():raise InterruptedError()
        for raw in group or ():
            try:x0,y0,x1,y1=map(int,raw)
            except Exception:continue
            if y0==y1 and 0<=y0<h:
                lo,hi=sorted((x0,x1));lo=max(0,lo);hi=min(w-1,hi)
                if lo<=hi:
                    base=y0*w
                    labels[base+lo:base+hi+1]=[color]*(hi-lo+1)
            elif x0==x1 and 0<=x0<w:
                lo,hi=sorted((y0,y1));lo=max(0,lo);hi=min(h-1,hi)
                for y in range(lo,hi+1):labels[y*w+x0]=color
            elif x0!=x1 and y0!=y1:
                from RasterGeometry import clipped_bresenham
                for point_number,(x,y) in enumerate(clipped_bresenham((x0,y0),(x1,y1),w,h)):
                    if point_number%256==0 and cancelled():raise InterruptedError()
                    labels[y*w+x]=color
    seen=bytearray(w*h);candidates=[];rejected=Counter();fallback=0;total_components=0;interior_components=0
    floor={"Conservative":70,"Balanced":36,"Aggressive":20}[normalized]
    for start,color in enumerate(labels):
        if color<0 or seen[start]:continue
        if cancelled():raise InterruptedError()
        stack=[start];seen[start]=1;points=[];touches_border=False
        while stack:
            pos=stack.pop();x,y=pos%w,pos//w;points.append(pos)
            if len(points)%1024==0 and cancelled():raise InterruptedError()
            touches_border=touches_border or x==0 or y==0 or x==w-1 or y==h-1
            for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if 0<=nx<w and 0<=ny<h:
                    n=ny*w+nx
                    if not seen[n] and labels[n]==color:
                        seen[n]=1;stack.append(n)
        total_components+=1
        if not touches_border:interior_components+=1
        if touches_border or len(points)<floor:continue
        rgb=palette_rgb[color] if 0<=color<len(palette_rgb) else (0,0,0)
        region,why=_component_to_region(color,points,w,h,normalized,resolved,safe_margin_px=safe_margin,rgb_override=rgb)
        if region is None:
            fallback+=1;rejected[why or 'unsafe']+=1;continue
        candidates.append(region)
    candidates.sort(key=lambda r:(r.estimated_saved_strokes,r.area_pixels,r.safety_score),reverse=True)
    accepted=candidates[:max_regions];fallback+=max(0,len(candidates)-len(accepted))
    meta={"engine":resolved,"accepted_regions":len(accepted),
          "contour_regions":sum(r.strategy=="closed-contour" for r in accepted),
          "rectangle_regions":sum(r.strategy=="rectangle" for r in accepted),
          "fallback_scanline_regions":fallback,"estimated_saved_strokes":sum(r.estimated_saved_strokes for r in accepted),
          "safe_fill_mask_margin_px":safe_margin,"rejected":dict(rejected),"total_components":total_components,
          "interior_components":interior_components,"candidate_regions":len(candidates),
          "source":"quantized execution groups","dynamic_palette_indexes":True}
    return (accepted,meta) if return_meta else accepted

def _region_spans(region):
    if isinstance(region, dict):
        spans = region.get("row_spans") or ()
        if spans: return tuple((int(y), int(x0), int(x1)) for y,x0,x1 in spans)
        x0,y0,x1,y1 = region.get("bbox", (0,0,-1,-1))
        return tuple((y,int(x0),int(x1)) for y in range(int(y0),int(y1)+1))
    spans = getattr(region, "row_spans", ()) or ()
    if spans: return tuple((int(y), int(x0), int(x1)) for y,x0,x1 in spans)
    x0,y0,x1,y1 = region.bbox
    return tuple((y,x0,x1) for y in range(y0,y1+1))


def remove_filled_region_strokes(groups, regions):
    """Remove only source pixels covered by accepted fill regions.

    v1.0.39 uses exact per-row spans for irregular shapes; legacy rectangle
    plans without spans keep the old bbox behavior.
    """
    output = [list(group) for group in groups]
    by_color = defaultdict(lambda: defaultdict(list))
    for region in regions:
        color_index = region.get('color_index') if isinstance(region, dict) else region.color_index
        for y, left, right in _region_spans(region):
            by_color[int(color_index)][int(y)].append((int(left),int(right)))
    for index, rows in by_color.items():
        if not (0 <= index < len(output)): continue
        result = []
        for x1,y1,x2,y2 in output[index]:
            if y1 != y2 or y1 not in rows:
                result.append((x1,y1,x2,y2)); continue
            segments = [(min(x1,x2), max(x1,x2))]
            for bx0,bx1 in rows[y1]:
                next_segments=[]
                for left,right in segments:
                    if right < bx0 or left > bx1:
                        next_segments.append((left,right)); continue
                    if left < bx0: next_segments.append((left,bx0-1))
                    if right > bx1: next_segments.append((bx1+1,right))
                segments=next_segments
            for left,right in segments:
                if left <= right: result.append((left,y1,right,y1))
        output[index]=result
    return output


def restrict_white_corrections(groups, palette_rgb, regions):
    """Retain white repair only inside interior fill bounds, not the whole canvas."""
    bounds=[tuple(map(int,r['bbox'])) for r in regions]
    result=[list(g) for g in groups]
    for color,rgb in enumerate(palette_rgb):
        if min(rgb)<245:continue
        kept=[]
        for ax,ay,bx,by in result[color]:
            # Raster planning produces horizontal runs (or point runs) here.
            if ay!=by:
                kept.append((ax,ay,bx,by));continue
            lo,hi=sorted((ax,bx));intervals=[]
            for x0,y0,x1,y1 in bounds:
                left,right=max(lo,x0),min(hi,x1)
                if y0<=ay<=y1 and left<=right:intervals.append((left,right))
            merged=[]
            for left,right in sorted(intervals):
                if merged and left<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(right,merged[-1][1]))
                else:merged.append((left,right))
            kept.extend((left,ay,right,ay) for left,right in merged)
        result[color]=kept
    return result
