"""Image-aware opacity planning for Gartic targets.

Gartic exposes a continuous opacity control while the five brush controls are
separate. This module keeps opacity planning read-only and fail-closed: it may
produce a click target only when the slider-like toolbar structure is visible in
the already verified browser/canvas screenshot. Low confidence means 100% ink
and no opacity input.

The planner intentionally prefers opaque ink for flat fills, outlines, Pixel
Accurate and high-edge images. Reduced opacity is reserved for smooth tonal or
shaded images where blending can improve likeness. The final real-canvas score
remains authoritative and can be used by CompletedDrawingAnalysis afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

from PIL import Image, ImageFilter, ImageStat

SUPPORTED = frozenset({"gartic-phone", "gartic-io"})
OPACITY_LEVELS = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _metrics(image: Image.Image | None) -> tuple[float, float, float]:
    """Return edge density, color complexity and smooth tonal variation."""
    if not isinstance(image, Image.Image):
        return .5, .5, .0
    rgb = image.convert("RGB")
    w = max(32, min(160, rgb.width)); h = max(32, min(160, rgb.height))
    sample = rgb.resize((w, h), Image.Resampling.BILINEAR)
    gray = sample.convert("L")
    edge = float(ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]) / 255.0
    palette_source = rgb.resize((w, h), Image.Resampling.NEAREST)
    palette = palette_source.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    used = sum(1 for value in palette.histogram() if value)
    color = min(1.0, used / 32.0)
    stat = ImageStat.Stat(gray)
    std = float(stat.stddev[0] if stat.stddev else 0.0) / 96.0
    # Smooth tonal content: meaningful luminance variation but not dominated by
    # hard edges. This tends to identify photos/soft shading rather than logos.
    smooth_tone = _clamp(std * (1.0 - min(1.0, edge * 2.4)), 0.0, 1.0)
    return _clamp(edge, 0.0, 1.0), _clamp(color, 0.0, 1.0), smooth_tone


def validate_opacity(value: Any) -> str:
    text = str(value if value is not None else "Auto").strip()
    if text.casefold() == "auto":
        return "Auto"
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        number = int(text)
    except (TypeError, ValueError) as error:
        raise ValueError("Gartic opacity must be Auto or 10–100% in 10% steps.") from error
    if number not in OPACITY_LEVELS:
        raise ValueError("Gartic opacity must be Auto or 10–100% in 10% steps.")
    return f"{number}%"


def choose_opacity_percent(image: Image.Image | None, *, requested: Any = "Auto",
                           draw_quality: str = "", render_style: str = "",
                           drawing_mode: str = "", outline: bool = False,
                           source_kind: str = "") -> dict[str, Any]:
    request = validate_opacity(requested)
    edge, color, smooth = _metrics(image)
    if request != "Auto":
        selected = int(request.rstrip("%"))
        return {
            "requested": request, "selected_percent": selected,
            "automatic": False, "edge_density": round(edge, 4),
            "color_complexity": round(color, 4), "smooth_tone_score": round(smooth, 4),
            "reason": "manual Gartic opacity",
        }

    quality = str(draw_quality or "")
    style = str(render_style or "")
    mode = str(drawing_mode or "")
    kind = str(source_kind or "").casefold()

    if outline or "Pixel Accurate" in quality or "line" in kind:
        selected = 100
        reason = "hard edges/Pixel Accurate require opaque ink"
    elif style in ("Quick Sketch", "Sketch + Color Fill") and edge < .22:
        selected = 30 if smooth >= .34 else 50
        reason = "sketch-style smooth source benefits from lighter construction ink"
    elif style == "Portrait / shaded" or "photo" in kind or "texture" in kind:
        if smooth >= .62 and edge <= .18:
            selected = 30
            reason = "smooth shaded/photo source: 30% preserves tonal layering"
        elif smooth >= .42 and edge <= .26:
            selected = 50
            reason = "shaded source: 50% balances layering and structure"
        else:
            selected = 70
            reason = "detailed shaded source: keep stronger structure at 70%"
    elif color <= .18:
        selected = 100
        reason = "few-color/flat-shape source is more accurate with opaque ink"
    elif smooth >= .72 and edge <= .12 and color >= .45:
        selected = 30
        reason = "very smooth tonal image: lower opacity can approximate gradients"
    elif smooth >= .48 and edge <= .20:
        selected = 60
        reason = "moderate tonal image: partial opacity can reduce harsh banding"
    else:
        selected = 100
        reason = "flat/detail-heavy source is more accurate with opaque ink"

    # 10% is intentionally rare because repeated semi-transparent strokes are
    # highly target/background dependent. It is allowed for manual use and only
    # selected automatically for an exceptionally smooth sketch layer.
    if style in ("Quick Sketch", "Sketch + Color Fill") and smooth >= .88 and edge <= .07:
        selected = 10
        reason = "exceptionally smooth sketch source: very light construction layer"

    return {
        "requested": "Auto", "selected_percent": int(selected), "automatic": True,
        "edge_density": round(edge, 4), "color_complexity": round(color, 4),
        "smooth_tone_score": round(smooth, 4), "reason": reason,
        "drawing_mode": mode, "render_style": style,
    }


def _screen_crop(screenshot: Image.Image, client_rect, box):
    cl, ct, _, _ = map(int, client_rect)
    l, t, r, b = map(int, box)
    local = (max(0, l-cl), max(0, t-ct), min(screenshot.width, r-cl), min(screenshot.height, b-ct))
    if local[2] <= local[0] or local[3] <= local[1]:
        return None
    return screenshot.convert("RGB").crop(local)


def _slider_geometry(client_rect, canvas_box) -> tuple[tuple[int, int], tuple[int, int], int]:
    l, t, r, b = map(int, client_rect)
    x0, y0, x1, y1 = map(int, canvas_box)
    w, h = max(1, x1-x0), max(1, y1-y0)
    ch = max(1, b-t)
    y = y1 + max(28, min(int(ch*.095), int(h*.17)))
    # Current Gartic toolbar: five discrete brush circles occupy the left side;
    # the opacity track follows them. Coordinates remain canvas-relative and are
    # accepted only after visual track verification below.
    start = (x0 + int(w*.47), y)
    end = (x0 + int(w*.91), y)
    return start, end, y


def _slider_confidence(screenshot: Image.Image, client_rect, start, end) -> float:
    sx, sy = map(int, start); ex, ey = map(int, end)
    if ex-sx < 60 or abs(ey-sy) > 3:
        return 0.0
    radius = 13
    crop = _screen_crop(screenshot, client_rect, (sx-radius, sy-radius, ex+radius+1, sy+radius+1))
    if crop is None or crop.width < 60 or crop.height < 15:
        return 0.0
    gray = crop.convert("L")
    arr = list(gray.getdata())
    if not arr:
        return 0.0
    overall_std = float(ImageStat.Stat(gray).stddev[0])
    cy = gray.height // 2
    center = [gray.getpixel((x, cy)) for x in range(4, gray.width-4)]
    above_y = max(1, cy-8); below_y = min(gray.height-2, cy+8)
    surroundings = [(gray.getpixel((x, above_y)) + gray.getpixel((x, below_y))) / 2.0
                    for x in range(4, gray.width-4)]
    line_contrast = sum(abs(float(a)-float(b)) for a, b in zip(center, surroundings)) / max(1, len(center))
    # A slider track plus handle normally has both a long horizontal contrast and
    # some local diversity. Thresholds are deliberately conservative because a
    # false click is worse than falling back to 100%.
    confidence = _clamp((line_contrast-3.0)/18.0, 0.0, 1.0) * .70 + _clamp((overall_std-5.0)/35.0, 0.0, 1.0) * .30
    return _clamp(confidence, 0.0, 1.0)


@dataclass(frozen=True)
class GarticOpacityPlan:
    profile_key: str
    requested: str
    selected_percent: int
    target_position: tuple[int, int] | None
    track_start: tuple[int, int] | None
    track_end: tuple[int, int] | None
    confidence: float
    reason: str
    automatic: bool
    image_metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "requested": self.requested,
            "selected_percent": int(self.selected_percent),
            "target_position": list(self.target_position) if self.target_position else None,
            "track_start": list(self.track_start) if self.track_start else None,
            "track_end": list(self.track_end) if self.track_end else None,
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
            "automatic": bool(self.automatic),
            "image_metrics": dict(self.image_metrics),
        }


def plan_gartic_opacity(profile_key: str, screenshot: Image.Image | None, client_rect, *,
                        canvas_box=None, source_image: Image.Image | None = None,
                        requested: Any = "Auto", draw_quality: str = "",
                        render_style: str = "", drawing_mode: str = "",
                        outline: bool = False, source_kind: str = "") -> GarticOpacityPlan:
    key = str(profile_key or "").lower()
    decision = choose_opacity_percent(source_image, requested=requested, draw_quality=draw_quality,
                                      render_style=render_style, drawing_mode=drawing_mode,
                                      outline=outline, source_kind=source_kind)
    selected = int(decision["selected_percent"])
    request = str(decision["requested"])
    metrics = {k:v for k,v in decision.items() if k not in ("requested", "selected_percent", "reason", "automatic")}
    if key not in SUPPORTED:
        return GarticOpacityPlan(key, request, selected, None, None, None, 0.0,
                                 "unsupported opacity target", bool(decision["automatic"]), metrics)
    if selected >= 100:
        # 100% is the fail-safe default. No UI click is necessary unless a future
        # runtime has evidence the target was left at a different opacity.
        return GarticOpacityPlan(key, request, 100, None, None, None, 1.0,
                                 str(decision["reason"]), bool(decision["automatic"]), metrics)
    if not isinstance(screenshot, Image.Image) or not (isinstance(canvas_box, (tuple, list)) and len(canvas_box) == 4):
        return GarticOpacityPlan(key, request, 100, None, None, None, 0.0,
                                 str(decision["reason"]) + "; slider geometry unavailable, fail-safe 100%",
                                 bool(decision["automatic"]), metrics)
    start, end, y = _slider_geometry(client_rect, canvas_box)
    confidence = _slider_confidence(screenshot, client_rect, start, end)
    if confidence < .58:
        return GarticOpacityPlan(key, request, 100, None, start, end, confidence,
                                 str(decision["reason"]) + "; opacity slider not visually verified, fail-safe 100%",
                                 bool(decision["automatic"]), metrics)
    # Gartic's track is treated as 0..100; our public choices are 10..100.
    ratio = _clamp(selected / 100.0, .10, 1.0)
    x = int(round(start[0] + (end[0]-start[0]) * ratio))
    target = (x, int(y))
    return GarticOpacityPlan(key, request, selected, target, start, end, confidence,
                             str(decision["reason"]), bool(decision["automatic"]), metrics)
