"""Adaptive local-detail planning for Image Draw Bot v1.0.38.

Pure image helpers only: no UI, mouse input, screen capture or native calls.
The engine protects high-contrast edges/local structure while simplifying flat
texture before color planning.  It can also remove tiny horizontal runs only in
areas classified as low detail.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack, closing
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
    # Equal-luminance colours can still form a distinct edge or a tiny mark.
    # Inspect the largest local channel range so red/green and blue/orange
    # detail survives smoothing. Uniform colours and grayscale retain their
    # original range; RGB is already composited against the visible background.
    with ExitStack() as owned:
        local_hi = owned.enter_context(closing(rgb.filter(ImageFilter.MaxFilter(5))))
        local_lo = owned.enter_context(closing(rgb.filter(ImageFilter.MinFilter(5))))
        ranges = owned.enter_context(closing(ImageChops.subtract(local_hi, local_lo)))
        red, green, blue = [owned.enter_context(closing(channel)) for channel in ranges.split()]
        first = owned.enter_context(closing(ImageChops.lighter(red, green)))
        return ImageChops.lighter(first, blue)


def _restore_source_alpha(source, visible_rgb, processed_rgb, cancelled):
    """Apply a visible-colour change once while preserving source alpha.

    Filtering is performed against white, where transparent pixels have their
    actual visible colour. Reattaching alpha to that flattened RGB would blend
    white a second time. Transfer only the visible delta back to the original
    unassociated channels; unchanged and hard-protected pixels stay exact.
    """
    import numpy as np
    from PIL import Image

    rgba = np.array(source, dtype=np.uint8, copy=True)
    before = np.asarray(visible_rgb, dtype=np.uint8)
    after = np.asarray(processed_rgb, dtype=np.uint8)
    for y in range(0, source.height, 128):
        if cancelled():
            raise InterruptedError()
        rows = rgba[y:y + 128]
        alpha = rows[..., 3:4].astype(np.int32)
        delta = after[y:y + 128].astype(np.int32) - before[y:y + 128]
        numerator = delta * 255
        adjustment = np.sign(numerator) * ((np.abs(numerator) + alpha // 2) // np.maximum(alpha, 1))
        adjustment[rows[..., 3] == 0] = 0
        rows[..., :3] = np.clip(rows[..., :3].astype(np.int32) + adjustment, 0, 255).astype(np.uint8)
    if cancelled():
        raise InterruptedError()
    return Image.fromarray(rgba)


def apply_adaptive_detail(image, mode: str = "Auto", *, subject_focus: bool = False,
                          drawing_mode: str | None = None, preview: bool = False,
                          cancelled=lambda: False):
    """Return (processed_rgba, protected_mask_L, stats).

    The protected mask is 255 around detail that should not be simplified and 0
    in flat regions. Alpha is preserved exactly. Only returned images escape the
    explicit temporary owner, including when a retained error interrupts work.
    """
    from PIL import Image, ImageFilter, ImageChops, ImageDraw

    validate_adaptive_detail(mode)
    if cancelled():
        raise InterruptedError()
    published = set()
    with ExitStack() as owned:
        def close_unpublished(value):
            if id(value) not in published:
                value.close()

        def keep(value):
            owned.callback(close_unpublished, value)
            return value

        source = keep(image.convert("RGBA"))
        if mode == "Off" or source.width < 4 or source.height < 4:
            total = source.width * source.height
            mask = keep(Image.new("L", source.size, 255))
            stats = AdaptiveDetailStats(mode, "Off", 0.0, total, 0, total, 100.0, 1, 255)
            if cancelled():
                raise InterruptedError()
            published.update((id(source), id(mask)))
            return source, mask, stats
        if cancelled():
            raise InterruptedError()

        alpha = keep(source.getchannel("A"))
        opaque = alpha.getextrema() == (255, 255)
        alpha.close()
        flat = keep(Image.new("RGBA", source.size, "white"))
        flat.alpha_composite(source)
        rgb = keep(flat.convert("RGB"))
        flat.close()
        signal = keep(_detail_signal(rgb))
        complexity = _complexity_from_detail(signal)
        effective = resolve_adaptive_detail(mode, complexity_score=complexity,
                                            drawing_mode=drawing_mode, preview=preview)
        threshold, dilation, smooth_kernel, _micro = _settings(effective)
        protected = keep(signal.point(lambda v: 255 if v >= threshold else 0))
        signal.close()
        if dilation > 1:
            previous = protected
            protected = keep(previous.filter(ImageFilter.MaxFilter(dilation)))
            previous.close()

        # Soft focus complements hard local edge protection.
        if subject_focus and source.width >= 12 and source.height >= 12:
            focus = keep(Image.new("L", source.size, 0))
            draw = ImageDraw.Draw(focus)
            try:
                mx = max(2, round(source.width * 0.17))
                my = max(2, round(source.height * 0.12))
                draw.ellipse((mx, my, source.width - 1 - mx, source.height - 1 - my), fill=96)
            finally:
                draw = None
            previous = protected
            protected = keep(ImageChops.lighter(previous, focus))
            previous.close()
            focus.close()

        if cancelled():
            raise InterruptedError()

        if smooth_kernel <= 1:
            simplified = rgb
        elif effective == "Strong simplify":
            simplified = keep(rgb.filter(ImageFilter.MedianFilter(smooth_kernel)))
            w2, h2 = max(1, source.width // 2), max(1, source.height // 2)
            reduced = keep(simplified.resize((w2, h2), Image.Resampling.BILINEAR))
            simplified.close()
            simplified = keep(reduced.resize(source.size, Image.Resampling.BILINEAR))
            reduced.close()
        else:
            simplified = keep(rgb.filter(ImageFilter.MedianFilter(smooth_kernel)))

        processed_rgb = keep(Image.composite(rgb, simplified, protected))
        if simplified is not rgb:
            simplified.close()
        if opaque:
            processed = keep(processed_rgb.convert("RGBA"))
        else:
            processed = keep(_restore_source_alpha(source, rgb, processed_rgb, cancelled))
        processed_rgb.close()
        rgb.close()

        hist = protected.histogram()
        protected_pixels = sum(hist[1:])
        total = max(1, source.width * source.height)
        stats = AdaptiveDetailStats(
            mode, effective, complexity, protected_pixels, total - protected_pixels,
            total, protected_pixels * 100.0 / total, smooth_kernel, threshold,
        )
        if cancelled():
            raise InterruptedError()
        published.update((id(processed), id(protected)))
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
