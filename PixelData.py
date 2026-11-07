"""Pure image planning helpers; no mouse input or GUI on import."""
from dataclasses import dataclass
from functools import lru_cache
from Colors import allColors
from PlanningRowTasks import read_only_rgba, RgbaRowTasks


@dataclass
class PixelData:
    x: int
    y: int
    color: object

    def print(self):
        print(self.x, self.y, self.color)


@lru_cache(maxsize=65536)
def closest_color(rgb):
    return min(range(len(allColors)), key=lambda i: sum(
        (rgb[channel] - allColors[i].RGB[channel]) ** 2 for channel in range(3)))


def prepare_image(image, area, detail=9, *, sample_limit=None, max_pixels=None,
                  preview_detail_mode=None, preview_detail_meta=None, cancelled=lambda: False):
    from PIL import Image, ImageOps
    if cancelled():
        raise InterruptedError()
    if not 1 <= detail <= 10:
        raise ValueError("Detail must be between 1 and 10.")
    width, height = area
    if width < 2 or height < 2:
        raise ValueError("Select a larger drawing area.")
    source=image;owned=[];published=None
    try:
        # Imported images are normally already oriented RGBA. Pillow's no-op
        # exif_transpose and same-mode convert each copy the full raster; neither
        # copy is needed by these read-only resize consumers.
        image.load()
        if image.getexif().get(274,1) not in (None,1):
            image=ImageOps.exif_transpose(image)
            if image is not source:owned.append(image)
        if cancelled():raise InterruptedError()
        if image.mode!='RGBA':
            oriented=image
            image=oriented.convert('RGBA')
            if image is not source:owned.append(image)
            if oriented is not source:
                oriented.close();owned.remove(oriented)
        if cancelled():raise InterruptedError()
        scale = min(width / image.width, height / image.height)
        fitted = (image.width * scale, image.height * scale)
        samples = 200 / (11 - detail) if sample_limit is None else max(1.0, float(sample_limit))
        sample_scale = min(samples / max(fitted), 1.0)
        pixel_limit = None
        if max_pixels is not None:
            try:
                pixel_limit = max(1, int(max_pixels))
                pixel_scale = (pixel_limit / max(1.0, fitted[0] * fitted[1])) ** 0.5
                sample_scale = min(sample_scale, pixel_scale, 1.0)
            except (TypeError, ValueError, OverflowError):
                pass
        size = tuple(max(1, round(v * sample_scale)) for v in fitted)
        if pixel_limit is not None and size[0] * size[1] > pixel_limit:
            # Rounding both fitted dimensions upward can exceed the hard pixel
            # budget, including extremely thin panoramas with a minimum side of 1.
            if size[0] >= size[1]:
                size = (max(1, min(size[0], pixel_limit // size[1])), size[1])
            else:
                size = (size[0], max(1, min(size[1], pixel_limit // size[0])))
        if preview_detail_mode:
            from PreviewDetailEngine import detail_aware_resize
            result = detail_aware_resize(image, size, preview_detail_mode, cancelled=cancelled, metadata=preview_detail_meta)
        else:
            result = image.resize(size, Image.Resampling.LANCZOS)
        if result is not source:owned.append(result)
        if cancelled():raise InterruptedError()
        published=result
        return result, fitted
    finally:
        for private in reversed(owned):
            if private is not published:private.close()


def _nearest_palette_index(rgb, palette, cache):
    rgb = tuple(int(v) for v in rgb[:3])
    cached = cache.get(rgb)
    if cached is not None:
        return cached
    index = min(range(len(palette)), key=lambda i: sum((rgb[channel] - palette[i][channel]) ** 2 for channel in range(3)))
    if len(cache) < 32768:
        cache[rgb] = index
    return index


def _basic_rows_worker(args):
    y0, width, raw, lines, skip_white, palette = args
    groups = [[] for _ in palette]
    cache = {}
    height = len(raw) // max(1, width * 4)
    for local_y in range(height):
        y = y0 + local_y
        previous, start = None, 0
        row_offset = local_y * width * 4
        for x in range(width + 1):
            color = None
            if x < width:
                offset = row_offset + x * 4
                r, g, b, alpha = raw[offset], raw[offset + 1], raw[offset + 2], raw[offset + 3]
                if alpha:
                    if alpha >= 255:
                        rgb = (r, g, b)
                    else:
                        rgb = tuple(round((v * alpha + 255 * (255 - alpha)) / 255) for v in (r, g, b))
                    color = _nearest_palette_index(rgb, palette, cache)
                    if skip_white and min(palette[color]) >= 245:
                        color = None
            if not lines:
                if color is not None:
                    groups[color].append((x, y, x, y))
            elif color != previous:
                if previous is not None:
                    groups[previous].append((start, y, x - 1, y))
                start, previous = x, color
    return groups


def _merge_groups(chunks, color_count):
    groups = [[] for _ in range(color_count)]
    for chunk in chunks:
        for index, strokes in enumerate(chunk):
            groups[index].extend(strokes)
    return groups


def _parallel_basic_strokes(image, lines, skip_white, cancelled, cpu_workers, cpu_engine, ram_budget_mb, preview_plan):
    try:
        from ResourceAllocation import choose_parallel_backend, parallel_map, row_chunk_ranges
        workers = max(1, int(cpu_workers or 1))
        ram_mb = max(128, int(ram_budget_mb or 512))
        backend = choose_parallel_backend(cpu_engine or "Auto", width=image.width, height=image.height,
                                          workers=workers, ram_budget_mb=ram_mb, preview=bool(preview_plan))
        if backend == "serial":
            return None
        palette = tuple(tuple(c.RGB) for c in allColors)
        ranges = row_chunk_ranges(image.height, image.width, workers=workers, ram_budget_mb=ram_mb,
                                  bytes_per_pixel=16, min_rows=12, max_rows=256)
        if len(ranges) <= 1:
            return None
        with read_only_rgba(image) as rgba:
            tasks = RgbaRowTasks(rgba, ranges, (bool(lines), bool(skip_white), palette), cancelled=cancelled)
            chunks = parallel_map(_basic_rows_worker, tasks, backend=backend, workers=workers, cancelled=cancelled)
        if cancelled():
            return None
        return _merge_groups(chunks, len(palette))
    except InterruptedError:
        raise
    except Exception:
        # A failed optimization must never break the safe legacy planner.
        return None


def build_strokes(image, lines=True, skip_white=True, cancelled=lambda: False,
                  cpu_workers: int = 1, cpu_engine: str = "Auto", ram_budget_mb: int = 512,
                  preview_plan: bool = False):
    """Group horizontal runs by color; skipped pixels always break a run.

    v1.0.13 can split large planning images into CPU worker chunks.  The serial
    path remains the compatibility/safety fallback and is used by old tests and
    small images.
    """
    if cancelled():
        return None
    with read_only_rgba(image) as image:
        if cpu_workers and int(cpu_workers) > 1:
            parallel = _parallel_basic_strokes(image, lines, skip_white, cancelled, cpu_workers,
                                              cpu_engine, ram_budget_mb, preview_plan)
            if parallel is not None:
                return parallel
        groups = [[] for _ in allColors]
        pixels = image.load()
        for y in range(image.height):
            if cancelled():
                return None
            previous, start = None, 0
            for x in range(image.width + 1):
                color = None
                if x < image.width:
                    r, g, b, alpha = pixels[x, y]
                    if alpha:
                        rgb = tuple(round((v * alpha + 255 * (255 - alpha)) / 255)
                                    for v in (r, g, b))
                        color = closest_color(rgb)
                        if skip_white and min(allColors[color].RGB) >= 245:
                            color = None
                if not lines:
                    if color is not None:
                        groups[color].append((x, y, x, y))
                elif color != previous:
                    if previous is not None:
                        groups[previous].append((start, y, x - 1, y))
                    start, previous = x, color
        return groups


def monochrome_strokes(image, lines=True, cancelled=lambda:False,
                       cpu_workers: int = 1, cpu_engine: str = "Auto", ram_budget_mb: int = 512,
                       preview_plan: bool = False):
    """Single-color sketch without palette dependency; white/transparent gaps stay empty."""
    from PIL import Image
    source=image.convert('RGBA')
    flat=Image.new('RGBA',source.size,'white');flat.alpha_composite(source)
    gray=flat.convert('L');pixels=gray.load();strokes=[]
    # Monochrome portrait sketches are already generated by PortraitPlanner.  The
    # simple threshold planner stays serial because it is normally tiny and avoids
    # process startup for Paint one-colour masks.
    for y in range(gray.height):
        if cancelled():raise InterruptedError()
        start=None
        for x in range(gray.width+1):
            ink=x<gray.width and pixels[x,y]<180
            if not lines:
                if ink:strokes.append((x,y,x,y))
            elif ink and start is None:start=x
            elif not ink and start is not None:
                strokes.append((start,y,x-1,y));start=None
    return [strokes]
