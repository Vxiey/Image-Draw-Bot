"""Adaptive local-detail planning for Image Draw Bot v1.0.38.

Pure image helpers only: no UI, mouse input, screen capture or native calls.
The engine protects high-contrast edges/local structure while simplifying flat
texture before color planning.  It can also remove tiny horizontal runs only in
areas classified as low detail.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

ADAPTIVE_DETAIL_MODES = (
    "Off",
    "Auto",
    "Preserve detail",
    "Balanced",
    "Strong simplify",
)


@dataclass(frozen=True)
class AdaptiveDetailStats:
    requested_mode: str
    effective_mode: str
    complexity_score: float
    protected_pixels: int
    flat_pixels: int
    total_pixels: int
    protected_percent: float
    smoothing_kernel: int
    detail_threshold: int
    pruned_micro_strokes: int = 0
    pruned_micro_pixels: int = 0

    def as_dict(self) -> dict:
        return {
            "adaptive_detail_requested": self.requested_mode,
            "adaptive_detail_effective": self.effective_mode,
            "adaptive_detail_complexity": round(float(self.complexity_score), 4),
            "adaptive_detail_protected_pixels": int(self.protected_pixels),
            "adaptive_detail_flat_pixels": int(self.flat_pixels),
            "adaptive_detail_total_pixels": int(self.total_pixels),
            "adaptive_detail_protected_percent": round(float(self.protected_percent), 2),
            "adaptive_detail_smoothing_kernel": int(self.smoothing_kernel),
            "adaptive_detail_threshold": int(self.detail_threshold),
            "adaptive_detail_pruned_micro_strokes": int(self.pruned_micro_strokes),
            "adaptive_detail_pruned_micro_pixels": int(self.pruned_micro_pixels),
        }


def validate_adaptive_detail(mode: str) -> str:
    if mode not in ADAPTIVE_DETAIL_MODES:
        raise ValueError("Adaptive detail must be Off, Auto, Preserve detail, Balanced or Strong simplify.")
    return mode


def _complexity_from_detail(detail) -> float:
    hist = detail.histogram()
    total = max(1, sum(hist))
    # Emphasise visually relevant local changes instead of isolated noise.
    weighted = sum(i * count for i, count in enumerate(hist)) / (255.0 * total)
    strong = sum(hist[48:]) / total
    return max(0.0, min(1.0, weighted * 0.65 + strong * 0.35))


def resolve_adaptive_detail(mode: str, *, complexity_score: float | None = None,
                            drawing_mode: str | None = None, preview: bool = False) -> str:
    validate_adaptive_detail(mode)
    if mode != "Auto":
        return mode
    score = 0.25 if complexity_score is None else max(0.0, min(1.0, float(complexity_score)))
    # Very detailed images retain more source structure; simple/noisy images can
    # be simplified more aggressively without harming important contours.
    if score >= 0.36:
        effective = "Preserve detail"
    elif score <= 0.12:
        effective = "Strong simplify"
    else:
        effective = "Balanced"
    # Preview should remain representative, not more destructive than final.
    if preview and effective == "Strong simplify":
        effective = "Balanced"
    return effective


def _settings(effective_mode: str) -> tuple[int, int, int, int]:
    """Return threshold, dilation kernel, smoothing kernel, micro-run length."""
    if effective_mode == "Preserve detail":
        return 20, 5, 3, 1
    if effective_mode == "Strong simplify":
        return 42, 3, 5, 4
    if effective_mode == "Balanced":
        return 30, 3, 3, 2
    return 255, 1, 1, 0


def _detail_signal(rgb):
    from PIL import ImageChops, ImageFilter
    gray = rgb.convert("L")
    # A local luminance range is stable on flat colours/gradients yet spikes on
    # object borders, thin lines, text-like marks and facial features.  Unlike
    # FIND_EDGES it does not create a strong response across a uniformly bright
    # region.
    local_hi = gray.filter(ImageFilter.MaxFilter(5))
    local_lo = gray.filter(ImageFilter.MinFilter(5))
    return ImageChops.subtract(local_hi, local_lo)


def apply_adaptive_detail(image, mode: str = "Auto", *, subject_focus: bool = False,
                          drawing_mode: str | None = None, preview: bool = False,
                          cancelled=lambda: False):
    """Return (processed_rgba, protected_mask_L, stats).

    The protected mask is 255 around detail that should not be simplified and 0
    in flat regions.  Alpha is preserved exactly.
    """
    from PIL import Image, ImageFilter, ImageChops, ImageDraw

    validate_adaptive_detail(mode)
    if cancelled():
        raise InterruptedError()
    source = image.convert("RGBA")
    if mode == "Off" or source.width < 4 or source.height < 4:
        total = source.width * source.height
        mask = Image.new("L", source.size, 255)
        stats = AdaptiveDetailStats(mode, "Off", 0.0, total, 0, total, 100.0, 1, 255)
        if cancelled():
            raise InterruptedError()
        return source, mask, stats
    if cancelled():
        raise InterruptedError()

    alpha = source.getchannel("A")
    flat = Image.new("RGBA", source.size, "white")
    flat.alpha_composite(source)
    rgb = flat.convert("RGB")
    signal = _detail_signal(rgb)
    complexity = _complexity_from_detail(signal)
    effective = resolve_adaptive_detail(mode, complexity_score=complexity,
                                        drawing_mode=drawing_mode, preview=preview)
    threshold, dilation, smooth_kernel, _micro = _settings(effective)
    protected = signal.point(lambda v: 255 if v >= threshold else 0)
    if dilation > 1:
        protected = protected.filter(ImageFilter.MaxFilter(dilation))

    # A centered subject is already an explicit user preference elsewhere in the
    # app. Protect its core a little more so smooth backgrounds can be simplified
    # without softening a face/object in the middle.
    if subject_focus and source.width >= 12 and source.height >= 12:
        focus = Image.new("L", source.size, 0)
        d = ImageDraw.Draw(focus)
        mx = max(2, round(source.width * 0.17))
        my = max(2, round(source.height * 0.12))
        d.ellipse((mx, my, source.width - 1 - mx, source.height - 1 - my), fill=96)
        protected = ImageChops.lighter(protected, focus)

    if cancelled():
        raise InterruptedError()

    if smooth_kernel <= 1:
        simplified = rgb
    elif effective == "Strong simplify":
        # Median removes isolated texture/noise while a light local resample makes
        # large flat gradients cheaper to quantize. Protected detail is restored.
        simplified = rgb.filter(ImageFilter.MedianFilter(smooth_kernel))
        w2, h2 = max(1, source.width // 2), max(1, source.height // 2)
        simplified = simplified.resize((w2, h2), Image.Resampling.BILINEAR).resize(source.size, Image.Resampling.BILINEAR)
    else:
        simplified = rgb.filter(ImageFilter.MedianFilter(smooth_kernel))

    # Use the soft 96-valued focus area as a blend instead of a hard mask; hard
    # detail edges remain 255 and are copied exactly from the source.
    processed_rgb = Image.composite(rgb, simplified, protected)
    processed = processed_rgb.convert("RGBA")
    processed.putalpha(alpha)

    hist = protected.histogram()
    # Any nonzero protection contributes; 255 pixels are hard-protected.
    protected_pixels = sum(hist[1:])
    total = max(1, source.width * source.height)
    stats = AdaptiveDetailStats(
        mode, effective, complexity, protected_pixels, total - protected_pixels,
        total, protected_pixels * 100.0 / total, smooth_kernel, threshold,
    )
    if cancelled():
        raise InterruptedError()
    return processed, protected, stats


def prune_flat_micro_strokes(groups: Sequence[Sequence[tuple[int, int, int, int]]], protected_mask,
                              mode: str, *, cancelled=lambda: False):
    """Remove only very short horizontal runs in unprotected/flat regions.

    Returns (new_groups, {pruning stats}).  It never removes a run that touches a
    protected pixel, so contours/high-local-contrast structure survives.
    """
    validate_adaptive_detail(mode)
    effective = mode
    if mode == "Auto":
        # apply_adaptive_detail resolves Auto before callers reach here; use the
        # conservative default if this helper is invoked directly.
        effective = "Balanced"
    _threshold, _dilation, _smooth, max_micro = _settings(effective)
    if effective == "Off" or max_micro <= 0 or protected_mask is None:
        return [list(g) for g in groups], {"adaptive_detail_pruned_micro_strokes": 0, "adaptive_detail_pruned_micro_pixels": 0}

    pix = protected_mask.load()
    width, height = protected_mask.size
    out = []
    removed = 0
    removed_pixels = 0
    for group in groups:
        kept = []
        for stroke in group:
            if cancelled():
                raise InterruptedError()
            x1, y1, x2, y2 = map(int, stroke)
            length = max(abs(x2 - x1), abs(y2 - y1)) + 1
            remove = False
            if length <= max_micro:
                # Check every raster pixel of these at-most-four-pixel runs.
                # Endpoint/midpoint sampling misses the third pixel of a run
                # of length four and can erase protected thin detail.
                x, y = x1, y1
                dx, dy = abs(x2 - x1), -abs(y2 - y1)
                sx, sy = (1 if x1 < x2 else -1), (1 if y1 < y2 else -1)
                error = dx + dy
                remove = True
                while True:
                    if not (0 <= x < width and 0 <= y < height and pix[x, y] < 64):
                        remove = False
                        break
                    if (x, y) == (x2, y2):
                        break
                    twice = 2 * error
                    if twice >= dy:
                        error += dy; x += sx
                    if twice <= dx:
                        error += dx; y += sy
            if remove:
                removed += 1
                removed_pixels += length
            else:
                kept.append(stroke)
        out.append(kept)
    return out, {
        "adaptive_detail_pruned_micro_strokes": removed,
        "adaptive_detail_pruned_micro_pixels": removed_pixels,
    }
