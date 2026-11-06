"""Picture-driven custom RGB palette preparation for Microsoft Paint.

This module is intentionally separate from the drawing engine.  It analyses the
currently loaded source image with Image Draw Bot's existing DynamicColors planner,
selects a bounded image palette and saves its RGB values with Paint's Add to
custom colors button through calibrated Edit colors controls, and persists the resulting picture palette for reuse.

The feature never paints on the canvas.  It is an explicit user action and raw
mouse input is armed only for the short UI-control sequence, then always disarmed.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from RuntimePaths import atomic_write_text, data_dir

SCHEMA = 4
PROFILE_KEY = "microsoft-paint"
DEFAULT_MAX_COLORS = 16
MAX_ANALYSIS_DIMENSION = 640
MAX_EDGE_SAMPLES = 24000
MAX_CACHE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PicturePalette:
    image_fingerprint: str
    calibration_fingerprint: str
    source_size: tuple[int, int]
    max_colors: int
    fidelity: str
    colors: tuple[tuple[int, int, int], ...]
    custom_colors: tuple[tuple[int, int, int], ...]
    palette_colors: tuple[tuple[int, int, int], ...]
    custom_coverages: tuple[float, ...]
    cache_hit: bool = False

    def as_dict(self) -> dict:
        return {
            "version": SCHEMA,
            "profile_key": PROFILE_KEY,
            "image_fingerprint": self.image_fingerprint,
            "calibration_fingerprint": self.calibration_fingerprint,
            "source_size": list(self.source_size),
            "max_colors": int(self.max_colors),
            "fidelity": self.fidelity,
            "colors": [list(c) for c in self.colors],
            "custom_colors": [list(c) for c in self.custom_colors],
            "palette_colors": [list(c) for c in self.palette_colors],
            "custom_coverages": [float(v) for v in self.custom_coverages],
            "cache_hit": bool(self.cache_hit),
        }


def _rgb(value: Sequence[int]) -> tuple[int, int, int]:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        raise ValueError("Invalid RGB value in picture palette.")
    out = tuple(max(0, min(255, int(value[i]))) for i in range(3))
    return out


def _visible_rgb(image):
    from ColorMatchingEngine import visible_rgb_image
    return visible_rgb_image(image)


def _analysis_image(image):
    from PIL import Image
    source = _visible_rgb(image)
    if max(source.size) <= MAX_ANALYSIS_DIMENSION:
        return source
    source.thumbnail((MAX_ANALYSIS_DIMENSION, MAX_ANALYSIS_DIMENSION), Image.Resampling.LANCZOS)
    return source


def image_fingerprint(image, *, cancelled=lambda: False) -> str:
    """Hash all visible pixels in bounded row strips, including small edits."""
    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    digest = hashlib.sha256()
    digest.update(f"{image.width}x{image.height}|RGB|".encode("ascii"))
    rows = max(1, min(128, 1024 * 1024 // max(1, image.width * 4)))
    for top in range(0, image.height, rows):
        if cancelled():
            raise InterruptedError('Picture custom palette cancelled.')
        strip = image.crop((0, top, image.width, min(image.height, top + rows)))
        digest.update(_visible_rgb(strip).tobytes())
    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    return digest.hexdigest()


def _cache_root() -> Path:
    return data_dir() / "picture-palettes"


def cache_path(image_fp: str, calibration_fp: str = "") -> Path:
    image_key = "".join(c for c in str(image_fp).lower() if c in "0123456789abcdef")[:24]
    calibration_key = hashlib.sha256(str(calibration_fp or "none").encode("utf-8")).hexdigest()[:12]
    if len(image_key) < 12:
        raise ValueError("Invalid picture palette image fingerprint.")
    return _cache_root() / f"{PROFILE_KEY}-{image_key}-{calibration_key}.json"


def _validate_payload(payload: dict, *, image_fp: str | None = None,
                      calibration_fp: str | None = None) -> dict:
    if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != SCHEMA:
        raise ValueError("Invalid picture custom palette cache.")
    payload = dict(payload)
    if payload.get("profile_key") != PROFILE_KEY:
        raise ValueError("Picture custom palette belongs to another profile.")
    if image_fp is not None and payload.get("image_fingerprint") != image_fp:
        raise ValueError("Picture custom palette belongs to another image.")
    if calibration_fp is not None and payload.get("calibration_fingerprint", "") != calibration_fp:
        raise ValueError("Picture custom palette was built for another Paint calibration.")
    size = payload.get("source_size")
    if not isinstance(size, (list, tuple)) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise ValueError("Invalid picture palette source size.")
    limit = payload.get('max_colors')
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError('Invalid picture palette color limit.')
    from ColorFidelity import validate_color_fidelity
    validate_color_fidelity(payload.get('fidelity'))
    for name in ("colors", "custom_colors", "palette_colors"):
        values = payload.get(name, [])
        if not isinstance(values, list) or len(values) > limit or (name == 'colors' and not values):
            raise ValueError(f"Invalid {name} in picture palette.")
        for value in values:
            if (not isinstance(value, (list, tuple)) or len(value) != 3 or
                    any(type(v) is not int or not 0 <= v <= 255 for v in value)):
                raise ValueError('Invalid RGB channels in picture palette cache.')
        clean = [tuple(value) for value in values]
        if len(set(clean)) != len(clean):
            raise ValueError(f'Duplicate colors in {name}.')
        payload[name] = [list(value) for value in clean]
    colors, custom, calibrated = (set(map(tuple, payload[name])) for name in
                                  ('colors', 'custom_colors', 'palette_colors'))
    if custom & calibrated or custom | calibrated != colors:
        raise ValueError('Picture palette color groups do not match the prepared colors.')
    coverages = payload.get("custom_coverages", [])
    if not isinstance(coverages, list) or len(coverages) != len(payload['custom_colors']):
        raise ValueError("Invalid picture palette coverage data.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not 0 <= v <= 1 or not math.isfinite(v) for v in coverages):
        raise ValueError('Picture palette coverage must be finite and between 0 and 1.')
    payload['custom_coverages'] = [float(v) for v in coverages]
    return payload


def load_cached_palette(image_fp: str, calibration_fp: str, *, max_colors: int,
                        fidelity: str) -> PicturePalette | None:
    try:
        path = cache_path(image_fp, calibration_fp)
        with path.open('rb') as stream:
            raw = stream.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return None
        payload = _validate_payload(json.loads(raw.decode('utf-8-sig')),
                                    image_fp=image_fp, calibration_fp=calibration_fp)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return None
    if int(payload["max_colors"]) != int(max_colors) or payload["fidelity"] != str(fidelity):
        return None
    return PicturePalette(
        image_fp, calibration_fp, tuple(map(int, payload["source_size"])), int(payload["max_colors"]),
        str(payload["fidelity"]), tuple(_rgb(v) for v in payload["colors"]),
        tuple(_rgb(v) for v in payload["custom_colors"]), tuple(_rgb(v) for v in payload["palette_colors"]),
        tuple(float(v) for v in payload.get("custom_coverages", [])), True,
    )


def save_palette(palette: PicturePalette) -> Path:
    payload = _validate_payload(palette.as_dict())
    payload["cache_hit"] = False
    payload["saved_at_utc"] = datetime.now(timezone.utc).isoformat()
    path = cache_path(palette.image_fingerprint, palette.calibration_fingerprint)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    return path


def _distance2(a: Sequence[int], b: Sequence[int]) -> int:
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3))


def _dedupe(colors: Iterable[Sequence[int]], *, threshold: int = 7) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    limit2 = int(threshold) ** 2 * 3
    for value in colors:
        rgb = _rgb(value)
        if any(_distance2(rgb, old) <= limit2 for old in out):
            continue
        out.append(rgb)
    return out


def _edge_detail_colors(image, count: int, *, cancelled=lambda: False) -> list[tuple[int, int, int]]:
    """Return a few colors sampled specifically from high-edge pixels.

    This does not replace the normal DynamicColors ranking.  It only gives tiny
    high-contrast details a chance to enter the prepared palette when coverage
    alone would put them below large flat regions.
    """
    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    if count <= 0:
        return []
    from contextlib import closing
    import numpy as np
    from PIL import Image
    with closing(_analysis_image(image)) as source:
        rgb = np.asarray(source, dtype=np.uint8)
        edge = np.zeros(rgb.shape[:2], dtype=np.uint8)
        # Both sides of a real color transition are evidence. A signed
        # Laplacian clipped dark accents away and treated the unchanged Pillow
        # filter border as an edge even for a completely uniform source.
        for axis in (0, 1):
            left = (slice(None, -1), slice(None)) if axis == 0 else (slice(None), slice(None, -1))
            right = (slice(1, None), slice(None)) if axis == 0 else (slice(None), slice(1, None))
            contrast = np.max(np.abs(rgb[right].astype(np.int16) - rgb[left].astype(np.int16)), axis=2).astype(np.uint8)
            np.maximum(edge[left], contrast, out=edge[left])
            np.maximum(edge[right], contrast, out=edge[right])
        indices = np.flatnonzero(edge.ravel() >= 32)
        if not len(indices):
            return []
        step = max(1, math.ceil(len(indices) / MAX_EDGE_SAMPLES))
        indices = indices[::step][:MAX_EDGE_SAMPLES]
        # Materialize RGB triples only for the bounded sample, in exactly the
        # same row-major order as the scalar pixel/edge zip used previously.
        pixels = rgb.reshape(-1, 3)[indices]
    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    with closing(Image.fromarray(pixels.reshape(1, -1, 3))) as sample:
        with closing(sample.quantize(colors=max(1, min(int(count), 16)),
                                     method=Image.Quantize.MEDIANCUT,
                                     dither=Image.Dither.NONE)) as quantized:
            pal = quantized.getpalette() or []
            ranked = sorted((quantized.getcolors() or []), reverse=True)
    result = []
    for _n, index in ranked:
        base = int(index) * 3
        if base + 2 < len(pal):
            result.append((int(pal[base]), int(pal[base + 1]), int(pal[base + 2])))
    return _dedupe(result)


def build_picture_palette(image, palette_rgb: Iterable[Sequence[int]], *, max_colors: int = DEFAULT_MAX_COLORS,
                          fidelity: str = "Faithful", calibration_fingerprint: str = "",
                          cancelled=lambda: False) -> PicturePalette:
    """Build a bounded picture-specific palette using the production color planner."""
    from ColorFidelity import delta_e2000
    from DynamicColors import build_dynamic_color_palette

    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    max_colors = max(1, min(32, int(max_colors)))
    fidelity = str(fidelity or "Faithful")
    image_fp = image_fingerprint(image, cancelled=cancelled)
    cached = load_cached_palette(image_fp, calibration_fingerprint, max_colors=max_colors, fidelity=fidelity)
    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    if cached is not None:
        return cached
    if cancelled():
        raise InterruptedError("Picture custom palette cancelled.")

    analysis = _analysis_image(image)
    fallback = tuple(_rgb(c) for c in palette_rgb)
    if not fallback:
        raise ValueError("No Paint palette colors are available. Read/calibrate the Paint palette first.")
    planned, selectors, meta = build_dynamic_color_palette(
        analysis, fallback, max_colors=max_colors, skip_white=False, lines=True,
        exact_available=True, color_fidelity=fidelity, profile_name="Microsoft Paint", source_palette=True,
        cancelled=cancelled,
    )
    if planned is None:
        raise InterruptedError("Picture custom palette cancelled.")
    planned = tuple(_rgb(c) for c in (planned or ()))
    selectors = tuple(selectors or ())
    coverages = tuple((meta or {}).get("coverage_priority") or ())

    custom: list[tuple[int, int, int]] = []
    custom_cov: list[float] = []
    palette_colors: list[tuple[int, int, int]] = []
    for index, selector in enumerate(selectors):
        if cancelled():
            raise InterruptedError("Picture custom palette cancelled.")
        coverage = float(coverages[index]) if index < len(coverages) else 0.0
        if selector.get("kind") == "custom":
            rgb = _rgb(selector.get("rgb", planned[index] if index < len(planned) else (0, 0, 0)))
            if rgb not in custom:
                custom.append(rgb); custom_cov.append(coverage)
        else:
            rgb = _rgb(planned[index] if index < len(planned) else selector.get("rgb", (0, 0, 0)))
            if rgb not in palette_colors:
                palette_colors.append(rgb)

    # Reserve up to a quarter of the custom budget for high-edge colors that are
    # materially different from the normal Paint palette.  This protects eyes,
    # thin contours and small isolated color fields without exploding color count.
    detail_budget = min(6, max(2, max_colors // 4))
    details=(_edge_detail_colors(analysis,detail_budget,cancelled=cancelled)
             if len(custom)<max_colors else ())
    for rgb in details:
        if len(custom) >= max_colors:
            break
        nearest = min(float(delta_e2000(rgb, p)) for p in fallback)
        if nearest < 2.0:
            continue
        if any(float(delta_e2000(rgb, old)) < 2.0 for old in custom):
            continue
        custom.append(rgb); custom_cov.append(0.0)

    custom = custom[:max_colors]
    custom_cov = custom_cov[:len(custom)]
    all_colors = _dedupe([*custom, *palette_colors], threshold=3)[:max_colors]
    from PicturePaletteRefinement import refine_picture_palette
    all_colors = refine_picture_palette(analysis, all_colors, max_colors, cancelled=cancelled)
    custom = list(all_colors)
    custom_cov = [0.0] * len(custom)
    palette_colors = []
    result = PicturePalette(
        image_fp, str(calibration_fingerprint or ""), tuple(map(int, image.size)), max_colors, fidelity,
        tuple(all_colors), tuple(custom), tuple(palette_colors), tuple(custom_cov), False,
    )
    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    try:
        save_palette(result)
    except OSError:
        # Persistence is an optional reuse optimization; the complete in-memory
        # palette remains usable if this machine's cache directory is read-only.
        pass
    if cancelled():
        raise InterruptedError('Picture custom palette cancelled.')
    return result


def apply_custom_rgb_sequence(mouse, keyboard_backend, controls: dict,
                              colors: Iterable[Sequence[int]], *, cancelled=lambda: False,
                              wait=time.sleep, progress=None, dialog_ready=None, dialog_closed=None,
                              color_ready=None, input_guard=None) -> int:
    """Keep direct legacy callers on the same bounded, guarded transaction."""
    from PictureCustomPalette import apply_custom_rgb_sequence as transaction
    return transaction(mouse,keyboard_backend,controls,colors,cancelled=cancelled,
                       wait=wait,progress=progress,dialog_ready=dialog_ready,
                       dialog_closed=dialog_closed,color_ready=color_ready,input_guard=input_guard)


def _resolve_max_colors(app) -> int:
    from DynamicColors import resolve_exact_color_limit
    setting = getattr(getattr(app, "exact_color_limit", None), "get", lambda: "Auto")()
    quality = getattr(getattr(app, "draw_quality", None), "get", lambda: "High likeness")()
    return max(1, min(24, int(resolve_exact_color_limit(setting, draw_quality=quality, preview=False))))


def _resolve_target(app, cancelled=lambda: False):
    target = getattr(app, "target_window", None)
    if target and len(target) >= 2:
        return int(target[0]), tuple(map(int, target[1]))
    from BrowserOneClick import _enumerate_windows
    from PaintPreparation import ensure_paint
    candidate = ensure_paint(_enumerate_windows, cancelled=cancelled,
                             wait=getattr(getattr(app, "stop", None), "wait", time.sleep))
    return int(candidate["handle"]), tuple(map(int, candidate["rect"]))


def start_picture_custom_palette(app) -> bool:
    """UI entry point for the Microsoft Paint picture-palette button."""
    if getattr(app, "activity", None) or getattr(app, "closing", False):
        return False
    profile = getattr(getattr(app, "game", None), "get", lambda: "")()
    if profile != "Microsoft Paint":
        app.status.set("Custom color palette for picture is available only for Microsoft Paint.")
        return False
    source = getattr(app, "original", None)
    if source is None:
        app.status.set("Load an image first, then build Custom color palette for picture.")
        return False
    try:
        single_color=bool(getattr(app,"paint_simple",None) and app.paint_simple.get())
    except Exception:
        single_color=False
    try:
        black_sketch=bool(getattr(app,"outline",None) and app.outline.get())
    except Exception:
        black_sketch=False
    try:
        eraser=bool(getattr(app,"paint_tool",None) and app.paint_tool.get()=="Eraser")
    except Exception:
        eraser=False
    if single_color or black_sketch or eraser:
        mode=("Single-color sketch/current ink" if single_color else ("Black contour sketch" if black_sketch else "Eraser"))
        app.status.set(f"{mode} does not need custom RGB colors. Edit colors will not be opened.")
        return False

    source_id = id(source)
    max_colors = _resolve_max_colors(app)
    fidelity = getattr(getattr(app, "color_fidelity", None), "get", lambda: "Faithful")()
    palette_path = getattr(app, "calibration_path", None)

    def work():
        if getattr(app, "stop", None) is not None and app.stop.is_set():
            raise InterruptedError("Picture custom palette cancelled.")
        # Resolve Paint and its RGB controls before fingerprinting the palette.
        # If this is the first run, the exact-color calibration file is created
        # below; the resulting fingerprint therefore stays reusable on later runs.
        handle, rect = _resolve_target(app, app.stop.is_set)
        from ScreenGuard import WindowMonitor
        monitor = WindowMonitor()
        target = (handle, rect)
        if not monitor.activate(target):
            raise ValueError("Windows could not activate Paint for picture custom palette preparation.")
        if app.stop.wait(0.20):
            raise InterruptedError("Picture custom palette cancelled.")
        from TargetCapture import probe_handle_isolated
        meta = probe_handle_isolated(handle, cancelled=app.stop.is_set)
        from ExactColorTools import numeric_rgb_available, resolved_controls, save as save_exact_colors
        if not numeric_rgb_available(PROFILE_KEY):
            # This is deliberately independent from full Paint canvas detection.
            # A clipped/zoomed canvas must not prevent exact RGB calibration.
            from PaintPreparation import calibrate_rgb_controls
            from CalibrationAnchors import make_anchor
            app.events.put(("status", "Custom color palette for picture: calibrating Paint Edit colors R/G/B controls…"))
            exact_controls = calibrate_rgb_controls(handle, cancelled=app.stop.is_set)
            meta = probe_handle_isolated(handle, cancelled=app.stop.is_set)
            save_exact_colors(PROFILE_KEY, exact_controls, anchor=make_anchor(tuple(meta["client_rect"])))
        controls = resolved_controls(PROFILE_KEY, tuple(meta["client_rect"]))
        from ProfileStorage import calibration_context_fingerprint
        calibration_fp = calibration_context_fingerprint(
            PROFILE_KEY, workflow="picture-custom-palette", palette_path=palette_path,
            extras=(f"colors:{max_colors}", f"fidelity:{fidelity}"),
        )
        from Colors import allColors
        fallback = tuple(tuple(c.RGB) for c in allColors)
        palette = build_picture_palette(
            source, fallback, max_colors=max_colors, fidelity=fidelity,
            calibration_fingerprint=calibration_fp, cancelled=app.stop.is_set,
        )
        if id(getattr(app, "original", None)) != source_id:
            raise InterruptedError("Source image changed while the picture palette was being prepared.")
        custom = tuple(palette.colors)
        if not custom:
            app.picture_custom_palette_state = dict(palette.as_dict(), image_id=source_id, prepared_count=0)
            app.events.put(("status", f"Picture palette saved: {len(palette.colors)} colors found; no entries were available to save."))
            return
        from WindowsMouse import WindowsMouse
        mouse = WindowsMouse()
        keyboard_backend = getattr(app, "keyboard", None)
        if keyboard_backend is None:
            import keyboard as keyboard_backend

        def dialog_ready():
            # A fixed 160 ms delay is not proof that XAML has opened its dialog.
            # Resolve fresh fields before allowing Ctrl+A or numeric input.
            from PaintPreparation import automation, rgb_controls, find_add_custom_color, center
            deadline = time.monotonic() + 8.0
            while True:
                if app.stop.is_set():
                    raise InterruptedError("Picture custom palette cancelled.")
                nodes = automation(handle, cancelled=app.stop.is_set)
                try:
                    fields = rgb_controls(nodes)
                    fields["AddCustomColor"] = center(find_add_custom_color(nodes))
                    return fields
                except ValueError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Paint RGB dialog is not ready. No RGB input was sent; keep Edit colors in RGB mode and retry.")
                app.stop.wait(.20)

        def color_ready(rgb):
            from PaintPreparation import automation, rgb_controls, find_add_custom_color, center
            nodes = automation(handle, cancelled=app.stop.is_set)
            fields = rgb_controls(nodes)
            for key, expected in zip(("RedField", "GreenField", "BlueField"), rgb):
                matches = [n for n in nodes if str(n.get("kind", "")).endswith("Edit")
                           and center(n) == fields[key]]
                if len(matches) != 1 or str(matches[0].get("value", "")) != str(expected):
                    raise ValueError("Paint did not accept the requested RGB values; this color was not added.")
            fields["AddCustomColor"] = center(find_add_custom_color(nodes))
            return fields

        def dialog_closed():
            # Foreground ownership alone does not prove the modal has closed.
            from PaintPreparation import close_edit_colors
            close_edit_colors(handle, accept=True, cancelled=app.stop.is_set, wait=app.stop.wait)
            if not monitor.activate(target):
                raise InterruptedError("Paint did not return to the document after Edit colors.")
            if app.stop.wait(.20):
                raise InterruptedError("Picture custom palette cancelled.")

        def progress(index, total, rgb):
            app.events.put(("status", f"Custom color palette for picture: RGB {rgb} · {index}/{total}"))

        def input_guard(point, *, modal=False):
            if app.stop.is_set():raise InterruptedError('Picture custom palette cancelled.')
            if modal:monitor.verify_modal(target,point)
            else:monitor.verify(target,point)

        completed = apply_custom_rgb_sequence(
            mouse, keyboard_backend, controls, custom,
            cancelled=app.stop.is_set, wait=app.stop.wait, progress=progress,
            dialog_ready=dialog_ready, dialog_closed=dialog_closed, color_ready=color_ready,
            input_guard=input_guard,
        )
        # Hard postcondition for the preparation action: never leave Edit colors
        # over the document when control returns to Image Draw Bot.
        from PaintPreparation import close_edit_colors
        close_edit_colors(handle,accept=True,cancelled=app.stop.is_set,wait=app.stop.wait)
        if not monitor.activate(target):
            raise InterruptedError("Paint could not be reactivated after picture custom palette preparation.")
        if app.stop.wait(.12):raise InterruptedError("Picture custom palette cancelled.")
        completed_state = dict(
            palette.as_dict(), image_id=source_id, prepared_count=completed,
            cache_file=str(cache_path(palette.image_fingerprint, palette.calibration_fingerprint)),
        )
        app.events.put(("picture_palette_complete", completed_state))
        # Seed only the method preference, never a fake verification result.
        # Runtime still performs its normal first-stroke color verification.
        try:
            from AdaptiveColor import rgb_key
            session = getattr(app, 'color_session_cache', None)
            if isinstance(session, dict):
                for rgb in custom:
                    session[rgb_key(rgb)] = {
                        'method':'numeric', 'confidence':0.0, 'actual':(), 'sample':None,
                        'prepared_picture_palette':True,
                    }
        except Exception:
            pass
        app.events.put((
            "status",
            f"Picture custom palette ready: {completed} custom RGB colors added with + to Paint Custom colors. Build preview to use this image RGB palette.",
        ))

    app.picture_custom_palette_state = None
    if hasattr(app, "_mark_plan_stale"):
        app._mark_plan_stale("Picture palette is changing. Build preview after preparation completes.")
    app.status.set(f"Building picture custom palette: analyzing image and preparing up to {max_colors} colors…")
    return bool(app.begin_worker("exact-color-calibration", work))
