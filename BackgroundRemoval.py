"""High-quality, local background removal for Image Draw Bot.

The fast path keeps the original dependency-light border-connected remover for
plain studio-like backgrounds. Complex photos use a local BiRefNet-lite ONNX
model to predict a soft foreground alpha matte. The model is downloaded once
on demand into Image Draw Bot's writable data directory and all later runs are
offline.

Why the hybrid design:
* Plain backgrounds are faster and often more exact with the deterministic
  border flood-fill than with neural inference.
* Real photos need semantic foreground segmentation; colour similarity alone
  can leak through skin, clothing, reflections and structured backgrounds.
* A soft alpha matte preserves hair and anti-aliased edges better than a hard
  binary cutout.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
from math import sqrt
import os
from pathlib import Path
import threading
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageStat

from RuntimePaths import data_dir

MODES = ("Auto", "AI", "Light background", "Dark background", "Corner color")
STRENGTHS = ("Conservative", "Balanced", "Aggressive")

_MODEL_NAME = "BiRefNet general lite"
_MODEL_FILENAME = "birefnet-general-lite.onnx"
_MODEL_URL = (
    "https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/"
    "BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"
)
_MODEL_SHA256 = "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"
_MODEL_MIN_BYTES = 200_000_000
_MODEL_MAX_BYTES = 260_000_000
_MODEL_INPUT_SIZE = 1024
_MODEL_LOCK = threading.Lock()


def validate_mode(value: Any) -> str:
    value = str(value or "Auto")
    if value not in MODES:
        raise ValueError("Invalid background removal mode.")
    return value


def validate_strength(value: Any) -> str:
    value = str(value or "Balanced")
    if value not in STRENGTHS:
        raise ValueError("Invalid background removal strength.")
    return value


def _distance(a, b) -> float:
    dr = float(a[0]) - b[0]
    dg = float(a[1]) - b[1]
    db = float(a[2]) - b[2]
    return sqrt(.30 * dr * dr + .59 * dg * dg + .11 * db * db)


def _luma(p) -> float:
    return .2126 * p[0] + .7152 * p[1] + .0722 * p[2]


def _median(samples):
    if not samples:
        return (255, 255, 255)
    return tuple(sorted(int(p[c]) for p in samples)[len(samples) // 2] for c in range(3))


def _edge_samples(rgb: Image.Image):
    w, h = rgb.size
    step = max(1, min(w, h) // 96)
    out = []
    for x in range(0, w, step):
        out.extend((rgb.getpixel((x, 0)), rgb.getpixel((x, h - 1))))
    for y in range(step, h - 1, step):
        out.extend((rgb.getpixel((0, y)), rgb.getpixel((w - 1, y))))
    return [tuple(map(int, p[:3])) for p in out]


def _corners(rgb: Image.Image):
    w, h = rgb.size
    r = max(1, min(12, min(w, h) // 20))
    out = []
    for box in ((0, 0, r, r), (w - r, 0, w, r), (0, h - r, r, h), (w - r, h - r, w, h)):
        mean = ImageStat.Stat(rgb.crop(box)).mean[:3]
        out.append(tuple(int(round(v)) for v in mean))
    return out


def _reference(rgb: Image.Image, mode: str):
    edge = _edge_samples(rgb)
    corners = _corners(rgb)
    ref = _median(corners)
    if mode == "Light background":
        ref = _median([p for p in edge if _luma(p) >= 190] or edge)
    elif mode == "Dark background":
        ref = _median([p for p in edge if _luma(p) <= 65] or edge)
    distances = sorted(_distance(p, ref) for p in edge)
    p75 = distances[int(.75 * (len(distances) - 1))] if distances else 0.0
    p90 = distances[int(.90 * (len(distances) - 1))] if distances else 0.0
    corner_spread = max((_distance(p, _median(corners)) for p in corners), default=0.0)
    return ref, p75, p90, corner_spread


def _threshold(strength, ref, spread) -> float:
    value = {"Conservative": 18.0, "Balanced": 28.0, "Aggressive": 42.0}[strength]
    value += min(12.0, max(0.0, spread - 5.0) * .35)
    if _luma(ref) >= 238 or _luma(ref) <= 18:
        value += 5
    return max(10.0, min(58.0, value))


def _match(p, ref, limit, mode) -> bool:
    if _distance(p, ref) > limit:
        return False
    if mode == "Light background" and _luma(p) < 150:
        return False
    if mode == "Dark background" and _luma(p) > 105:
        return False
    return True


def _connected_mask(rgb, ref, limit, mode, cancelled):
    w, h = rgb.size
    pix = rgb.load()
    seen = bytearray(w * h)
    mask = bytearray(w * h)
    q = deque()

    def add(x, y):
        i = y * w + x
        if seen[i]:
            return
        seen[i] = 1
        if _match(pix[x, y], ref, limit, mode):
            mask[i] = 1
            q.append(i)

    for x in range(w):
        add(x, 0)
        add(x, h - 1)
    for y in range(1, h - 1):
        add(0, y)
        add(w - 1, y)
    count = 0
    while q:
        i = q.popleft()
        y, x = divmod(i, w)
        count += 1
        if count % 4096 == 0 and cancelled():
            raise InterruptedError()
        if x:
            add(x - 1, y)
        if x + 1 < w:
            add(x + 1, y)
        if y:
            add(x, y - 1)
        if y + 1 < h:
            add(x, y + 1)
    return mask, count


def _simple_background(spread75: float, spread90: float, corner_spread: float) -> bool:
    # The colour flood-fill is excellent on a genuinely plain background, but
    # dangerous on photographs where a similar colour can form a path into the
    # subject. Requiring both corner agreement and a quiet border keeps it out
    # of those cases.
    return corner_spread <= 22.0 and spread75 <= 18.0 and spread90 <= 34.0


def _model_paths() -> tuple[Path, Path]:
    root = data_dir() / "models" / "background-removal"
    root.mkdir(parents=True, exist_ok=True)
    model = root / _MODEL_FILENAME
    return model, root / (_MODEL_FILENAME + ".sha256-ok")


def _sha256(path: Path, cancelled: Callable[[], bool]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            if cancelled():
                raise InterruptedError()
            chunk = stream.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _model_is_valid(path: Path, marker: Path, cancelled: Callable[[], bool]) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if not (_MODEL_MIN_BYTES <= size <= _MODEL_MAX_BYTES):
        return False
    try:
        if marker.read_text(encoding="ascii").strip().lower() == _MODEL_SHA256:
            return True
    except OSError:
        pass
    if _sha256(path, cancelled).lower() != _MODEL_SHA256:
        return False
    try:
        marker.write_text(_MODEL_SHA256 + "\n", encoding="ascii")
    except OSError:
        pass
    return True


def _ensure_model(cancelled: Callable[[], bool]) -> tuple[Path, bool]:
    model, marker = _model_paths()
    if _model_is_valid(model, marker, cancelled):
        return model, False

    with _MODEL_LOCK:
        if _model_is_valid(model, marker, cancelled):
            return model, False
        if cancelled():
            raise InterruptedError()

        # requests is already part of Image Draw Bot. Importing it lazily keeps
        # BackgroundRemoval import cheap for users who never press Remove BG.
        import requests

        partial = model.with_suffix(model.suffix + ".part")
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        written = 0
        try:
            with requests.get(
                _MODEL_URL,
                stream=True,
                allow_redirects=True,
                timeout=(8, 45),
                headers={"User-Agent": "ImageDrawBot-background-removal"},
            ) as response:
                response.raise_for_status()
                length = response.headers.get("Content-Length")
                if length:
                    expected = int(length)
                    if not (_MODEL_MIN_BYTES <= expected <= _MODEL_MAX_BYTES):
                        raise RuntimeError(f"Unexpected {_MODEL_NAME} download size: {expected} bytes")
                with partial.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if cancelled():
                            raise InterruptedError()
                        if not chunk:
                            continue
                        stream.write(chunk)
                        written += len(chunk)
                        if written > _MODEL_MAX_BYTES:
                            raise RuntimeError("Background-removal model download exceeded its safety limit.")
            if not (_MODEL_MIN_BYTES <= written <= _MODEL_MAX_BYTES):
                raise RuntimeError(f"Incomplete {_MODEL_NAME} download: {written} bytes")
            if _sha256(partial, cancelled).lower() != _MODEL_SHA256:
                raise RuntimeError("Background-removal model checksum did not match the official BiRefNet release.")
            os.replace(partial, model)
            try:
                marker.write_text(_MODEL_SHA256 + "\n", encoding="ascii")
            except OSError:
                pass
            return model, True
        finally:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass


def _choose_ort_providers(ort) -> list[str]:
    available = set(ort.get_available_providers())
    ordered = [
        provider for provider in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
        if provider in available
    ]
    return ordered or list(available)


def _run_birefnet_mask(rgb: Image.Image, cancelled: Callable[[], bool]):
    """Return a full-resolution L alpha mask and inference metadata."""
    if cancelled():
        raise InterruptedError()
    model_path, downloaded = _ensure_model(cancelled)
    if cancelled():
        raise InterruptedError()

    try:
        import onnxruntime as ort
    except Exception as exc:
        raise RuntimeError("ONNX Runtime is unavailable. Reinstall/update Image Draw Bot.") from exc

    options = ort.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = max(1, min(8, int(os.cpu_count() or 1)))
    try:
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    except Exception:
        pass

    providers = _choose_ort_providers(ort)
    try:
        session = ort.InferenceSession(str(model_path), sess_options=options, providers=providers)
    except Exception:
        # A locally installed GPU provider can be present but unusable because of
        # a driver/CUDA mismatch. Background removal must still work on CPU.
        if "CPUExecutionProvider" not in providers:
            raise
        session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        providers = ["CPUExecutionProvider"]

    if cancelled():
        raise InterruptedError()
    side = _MODEL_INPUT_SIZE
    resized = rgb.resize((side, side), Image.Resampling.LANCZOS)
    array = np.asarray(resized, dtype=np.float32) / 255.0
    mean = np.asarray((.485, .456, .406), dtype=np.float32)
    std = np.asarray((.229, .224, .225), dtype=np.float32)
    array = (array - mean) / std
    tensor = np.transpose(array, (2, 0, 1))[None, ...].astype(np.float32, copy=False)

    input_name = session.get_inputs()[0].name
    raw = session.run(None, {input_name: tensor})[0]
    if cancelled():
        raise InterruptedError()
    logits = np.asarray(raw, dtype=np.float32)
    logits = np.squeeze(logits)
    if logits.ndim != 2:
        raise RuntimeError(f"Unexpected {_MODEL_NAME} output shape: {tuple(np.shape(raw))}")
    pred = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
    lo = float(np.min(pred))
    hi = float(np.max(pred))
    if hi - lo > 1e-6:
        pred = (pred - lo) / (hi - lo)
    mask = Image.fromarray(np.clip(pred * 255.0 + .5, 0, 255).astype(np.uint8), mode="L")
    mask = mask.resize(rgb.size, Image.Resampling.LANCZOS)
    active = session.get_providers()
    provider = active[0] if active else (providers[0] if providers else "unknown")
    del session
    return mask, {"model": _MODEL_NAME, "provider": provider, "model_downloaded": bool(downloaded)}


def _shape_ai_alpha(mask: Image.Image, strength: str, feather_px: float) -> Image.Image:
    alpha = np.asarray(mask, dtype=np.float32) / 255.0
    gamma = {"Conservative": .78, "Balanced": 1.0, "Aggressive": 1.28}[strength]
    alpha = np.power(np.clip(alpha, 0.0, 1.0), gamma)
    bg_cut = {"Conservative": .010, "Balanced": .025, "Aggressive": .055}[strength]
    fg_cut = {"Conservative": .992, "Balanced": .986, "Aggressive": .980}[strength]
    alpha[alpha <= bg_cut] = 0.0
    alpha[alpha >= fg_cut] = 1.0
    out = Image.fromarray(np.clip(alpha * 255.0 + .5, 0, 255).astype(np.uint8), mode="L")
    # BiRefNet already predicts a soft matte. Only user-requested extra feather
    # above the historical default gets a tiny blur; default .6 must not wash out
    # hair, eyelashes or antialiased contours.
    if float(feather_px or 0.0) > .8:
        out = out.filter(ImageFilter.GaussianBlur(radius=min(.45, (float(feather_px) - .8) * .25)))
    return out


def _combine_alpha(predicted: Image.Image, old_alpha: bytes, size: tuple[int, int]) -> Image.Image:
    pred = np.frombuffer(predicted.tobytes(), dtype=np.uint8).astype(np.uint16)
    old = np.frombuffer(old_alpha, dtype=np.uint8).astype(np.uint16)
    combined = ((pred * old + 127) // 255).astype(np.uint8)
    return Image.frombytes("L", size, combined.tobytes())


def _classical_alpha(source: Image.Image, rgb: Image.Image, *, mode: str, strength: str,
                     feather_px: float, cancelled: Callable[[], bool], ref, spread):
    w, h = source.size
    total = max(1, w * h)
    old_alpha = source.getchannel("A").tobytes()
    limit = _threshold(strength, ref, spread)
    mask, count = _connected_mask(rgb, ref, limit, mode, cancelled)
    if count / total > .985:
        return None, mask, count, limit, "candidate background exceeded 98.5%; original preserved"
    alpha = bytearray(old_alpha)
    for i, bg in enumerate(mask):
        if bg:
            alpha[i] = 0
    alpha_img = Image.frombytes("L", (w, h), bytes(alpha))
    if any(mask) and feather_px:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=max(.1, min(1.2, float(feather_px)))))
        softened = bytearray(alpha_img.tobytes())
        for i, bg in enumerate(mask):
            if bg:
                softened[i] = 0
        alpha_img = Image.frombytes("L", (w, h), bytes(softened))
    return alpha_img, mask, count, limit, None


@dataclass(frozen=True)
class BackgroundRemovalResult:
    image: Image.Image
    metadata: dict


def remove_background(image: Image.Image, *, mode="Auto", strength="Balanced", feather_px=.6,
                      cancelled: Callable[[], bool] = lambda: False) -> BackgroundRemovalResult:
    mode = validate_mode(mode)
    strength = validate_strength(strength)
    source = ImageOps.exif_transpose(image).convert("RGBA")
    w, h = source.size
    total = max(1, w * h)
    source_alpha = source.getchannel("A")
    old_alpha = source_alpha.tobytes()
    before = sum(1 for a in old_alpha if a > 8)
    if cancelled():
        raise InterruptedError()

    # A file that is already substantially transparent has already gone through
    # a cutout workflow. Re-segmenting it can only destroy detail.
    existing_transparency = 1.0 - (before / total)
    if existing_transparency >= .20:
        bbox = source_alpha.getbbox()
        return BackgroundRemovalResult(source, {
            "mode": mode,
            "strength": strength,
            "removed_pixels": 0,
            "removed_percent": 0.0,
            "estimated_work_reduction_percent": 0.0,
            "drawable_after_percent": round(100.0 * before / total, 2),
            "foreground_bbox": list(bbox) if bbox else None,
            "no_op_reason": "image already contains substantial transparency; original alpha preserved",
            "method": "existing alpha preserved",
        })

    rgb = source.convert("RGB")
    ref, spread75, spread90, corner_spread = _reference(rgb, mode)
    simple = _simple_background(spread75, spread90, corner_spread)
    use_ai = mode == "AI" or (mode == "Auto" and not simple)
    fallback_reason = None
    inference_meta = {}
    no_op = None
    threshold = None

    if use_ai:
        try:
            mask, inference_meta = _run_birefnet_mask(rgb, cancelled)
            alpha_img = _shape_ai_alpha(mask, strength, feather_px)
            alpha_img = _combine_alpha(alpha_img, old_alpha, (w, h))
            method = "BiRefNet general lite ONNX soft alpha matte"
        except InterruptedError:
            raise
        except Exception as exc:
            # Never replace a complex photo with a destructive colour guess just
            # because the model/network/runtime failed. Only fall back when the
            # border statistics say the deterministic path is actually safe.
            fallback_reason = f"AI unavailable: {type(exc).__name__}: {exc}"
            if simple:
                alpha_img, _mask, _count, threshold, no_op = _classical_alpha(
                    source,
                    rgb,
                    mode="Corner color" if mode == "AI" else mode,
                    strength=strength,
                    feather_px=feather_px,
                    cancelled=cancelled,
                    ref=ref,
                    spread=spread75,
                )
                method = "border-connected fallback"
                if alpha_img is None:
                    alpha_img = source_alpha
            else:
                alpha_img = source_alpha
                no_op = "complex background needs the local AI model; original preserved because AI was unavailable"
                method = "fail-closed original preserved"
    else:
        alpha_img, _mask, _count, threshold, no_op = _classical_alpha(
            source,
            rgb,
            mode=mode,
            strength=strength,
            feather_px=feather_px,
            cancelled=cancelled,
            ref=ref,
            spread=spread75,
        )
        method = "border-connected background to transparent alpha"
        if alpha_img is None:
            alpha_img = source_alpha

    if cancelled():
        raise InterruptedError()
    alpha_bytes = alpha_img.tobytes()
    after = sum(1 for a in alpha_bytes if a > 8)

    # Neural segmentation can fail catastrophically on unusual inputs. Preserve
    # the source instead of returning an empty image or a mask that claims the
    # whole image is foreground.
    if use_ai and method.startswith("BiRefNet"):
        foreground_fraction = after / total
        if foreground_fraction < .002:
            alpha_img = source_alpha
            alpha_bytes = old_alpha
            after = before
            no_op = "AI foreground was below 0.2%; original preserved by safety guard"
            method = "AI safety guard preserved original"
        elif foreground_fraction > .995:
            alpha_img = source_alpha
            alpha_bytes = old_alpha
            after = before
            no_op = "AI found no meaningful removable background; original preserved"
            method = "AI no-op preserved original"

    result = source.copy()
    result.putalpha(alpha_img)
    removed = max(0, before - after)
    reduction = 100.0 * removed / max(1, before)
    bbox = alpha_img.getbbox()
    metadata = {
        "mode": mode,
        "strength": strength,
        "reference_rgb": list(ref),
        "threshold": round(threshold, 2) if threshold is not None else None,
        "border_spread_p75": round(spread75, 2),
        "border_spread_p90": round(spread90, 2),
        "corner_spread": round(corner_spread, 2),
        "auto_strategy": "AI" if use_ai else "fast plain-background",
        "removed_pixels": removed,
        "removed_percent": round(100.0 * removed / total, 2),
        "estimated_work_reduction_percent": round(reduction, 2),
        "drawable_after_percent": round(100.0 * after / total, 2),
        "foreground_bbox": list(bbox) if bbox else None,
        "no_op_reason": no_op,
        "fallback_reason": fallback_reason,
        "method": method,
        "edge_policy": "soft alpha matte; preserve fine detail",
    }
    metadata.update(inference_meta)
    return BackgroundRemovalResult(result, metadata)


def png_export_ready(image: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(image).convert("RGBA")
