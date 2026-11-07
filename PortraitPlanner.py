"""Portrait-oriented monochrome stroke planning.

v1.0.3 adds structure-aware stroke selection.  Detail level controls the raw
amount of work; Draw quality controls how that budget is spent.  The planner remains deterministic; expensive preprocessing can use the optional CUDA backend while CPU fallback stays available.
"""
from __future__ import annotations

import math
import heapq
import weakref
from dataclasses import dataclass
from contextlib import closing
from typing import Callable, Iterable, Sequence

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from GpuAcceleration import (enhance_portrait as gpu_enhance_portrait, saliency as gpu_saliency, sobel as gpu_sobel,
                             resize_gray_advanced as gpu_resize_gray_advanced,
                             release_analysis_session as gpu_release_analysis_session,
                             acceleration_info as gpu_acceleration_info)


DRAW_QUALITY = ("Balanced", "High likeness", "Maximum likeness", "GPU enhanced", "Pixel Accurate")


class _OwnedImages:
    """Close surviving owned cores even when an exception retains its frame."""
    def __init__(self, original):
        self.original = original
        self.references = []

    def own(self, image):
        if image is not self.original:
            self.references.append(weakref.ref(image))
        return image

    def close_except(self, result=None):
        for reference in self.references:
            image = reference()
            if image is not None and image is not result:
                image.close()


@dataclass(frozen=True)
class PortraitStats:
    tone_strokes: int
    edge_strokes: int
    levels: int
    sample_size: tuple[int, int]
    priority_strokes: int = 0
    draw_quality: str = "Balanced"
    acceleration_backend: str = "CPU"
    acceleration_device: str = "CPU"
    gpu_accelerated: bool = False


def _quality_profile(draw_quality: str) -> dict:
    """Return tuning values for fidelity without changing the public detail scale."""
    if draw_quality == "Balanced":
        return {
            "sample_scale": 1.00, "local_contrast": .00, "tone_gamma": .90,
            "background_lift": 42, "edge_share": .36, "edge_threshold": 1.00,
            "edge_cell_scale": 2.0, "priority_fraction": .26,
            "centre_bias": .20, "structure_weight": .42, "dark_weight": .12,
            "max_run": None, "merge_gap": None, "threshold_boost": 0,
        }
    if draw_quality == "High likeness":
        return {
            "sample_scale": 1.18, "local_contrast": .27, "tone_gamma": .94,
            "background_lift": 48, "edge_share": .41, "edge_threshold": .90,
            "edge_cell_scale": 1.55, "priority_fraction": .67,
            "centre_bias": .32, "structure_weight": .72, "dark_weight": .20,
            "max_run": 24, "merge_gap": 1, "threshold_boost": 5,
        }
    if draw_quality == "Maximum likeness":
        return {
            "sample_scale": 1.34, "local_contrast": .42, "tone_gamma": .97,
            "background_lift": 54, "edge_share": .45, "edge_threshold": .82,
            "edge_cell_scale": 1.20, "priority_fraction": .82,
            "centre_bias": .40, "structure_weight": .92, "dark_weight": .25,
            "max_run": 16, "merge_gap": 0, "threshold_boost": 9,
        }
    if draw_quality in ("GPU enhanced", "Pixel Accurate"):
        return {
            "sample_scale": 2.25 if draw_quality == "GPU enhanced" else 3.0, "local_contrast": .52, "tone_gamma": .985,
            "background_lift": 58, "edge_share": .48, "edge_threshold": .76,
            "edge_cell_scale": 1.0, "priority_fraction": .88,
            "centre_bias": .44, "structure_weight": 1.02, "dark_weight": .28,
            "max_run": 13 if draw_quality == "GPU enhanced" else 8, "merge_gap": 0, "threshold_boost": 12,
        }
    raise ValueError("Draw quality must be Balanced, High likeness, Maximum likeness, GPU enhanced, or Pixel Accurate.")


# Detail values currently exposed by Image Draw Bot are 6, 8, 9 and 10.  The
# helpers accept the full 1..10 range so saved/future settings remain safe.
def portrait_sample_limit(detail: int, draw_quality: str = "Balanced") -> int:
    if not 1 <= int(detail) <= 10:
        raise ValueError("Detail must be between 1 and 10.")
    profile = _quality_profile(draw_quality)
    base = max(72, round(72 + (int(detail) - 5) * 40))
    return max(72, round(base * profile["sample_scale"]))


def _enhance_local_contrast(gray: Image.Image, strength: float, *, cancelled=lambda: False) -> Image.Image:
    """Small deterministic high-pass boost that preserves facial midtones.

    PIL's global Contrast control cannot distinguish a faint eye/nose edge from
    a flat wall.  This local pass increases only differences from a blurred
    neighbourhood and is deliberately bounded to avoid halos.
    """
    if strength <= 0:
        return gray
    import numpy as np
    with closing(gray.filter(ImageFilter.GaussianBlur(radius=1.35))) as blur:
        src = np.frombuffer(gray.tobytes(), dtype=np.uint8)
        low = np.frombuffer(blur.tobytes(), dtype=np.uint8)
    out = np.empty(src.shape, dtype=np.uint8)
    for start in range(0, len(src), 4096):
        if cancelled():
            raise InterruptedError()
        end = min(start + 4096, len(src))
        values = src[start:end].astype(np.float64)
        # float64 and ties-to-even preserve the original Python round formula.
        enhanced = values + (values - low[start:end]) * strength
        out[start:end] = np.clip(np.rint(enhanced), 0, 255).astype(np.uint8)
    if cancelled():
        raise InterruptedError()
    return Image.fromarray(out.reshape(gray.height, gray.width))


def _release_portrait_session(metadata: dict) -> None:
    session = metadata.pop("_gpu_session", None)
    if session is not None:
        try:
            gpu_release_analysis_session(session, trim_cache=True)
        except Exception as error:
            # Release is best effort after losing the final owner. Preserve the
            # original planning/cancellation exception if the driver is failing.
            metadata["gpu_session_cleanup_error"] = f"{type(error).__name__}: {error}"[:200]


def prepare_portrait_image(image: Image.Image, area: tuple[int, int], detail: int,
                           contrast: float = 1.0, subject_focus: bool = True,
                           draw_quality: str = "Balanced", gpu_mode: str = "Auto",
                           acceleration_meta: dict | None = None, gpu_vram: str = "Auto",
                           gpu_performance: str = "Balanced", preview_detail_mode: str | None = None,
                           preview_detail_meta: dict | None = None, cancelled=lambda: False) -> tuple[Image.Image, tuple[float, float]]:
    """Prepare a portrait and retain analysis arrays only for an explicit owner."""
    metadata = acceleration_meta if acceleration_meta is not None else {}
    completed = False
    result = None
    images = _OwnedImages(image)
    try:
        result = _prepare_portrait_image_impl(
            image, area, detail, contrast, subject_focus, draw_quality, gpu_mode,
            metadata, gpu_vram, gpu_performance, preview_detail_mode, preview_detail_meta, cancelled,
            _images=images)
        completed = True
        return result
    finally:
        images.close_except(result[0] if result is not None else None)
        if not completed or acceleration_meta is None:
            _release_portrait_session(metadata)


def _prepare_portrait_image_impl(image: Image.Image, area: tuple[int, int], detail: int,
                           contrast: float = 1.0, subject_focus: bool = True,
                           draw_quality: str = "Balanced", gpu_mode: str = "Auto",
                           acceleration_meta: dict | None = None, gpu_vram: str = "Auto",
                           gpu_performance: str = "Balanced", preview_detail_mode: str | None = None,
                           preview_detail_meta: dict | None = None, cancelled=lambda: False,
                           *, _images: _OwnedImages) -> tuple[Image.Image, tuple[float, float]]:
    """Return an enhanced grayscale planning image and fitted physical size."""
    width, height = map(int, area)
    if width < 2 or height < 2:
        raise ValueError("Select a larger drawing area.")
    if not 1 <= int(detail) <= 10:
        raise ValueError("Detail must be between 1 and 10.")
    if not math.isfinite(float(contrast)) or not .5 <= float(contrast) <= 2.0:
        raise ValueError("Contrast must stay between 0.5 and 2.0.")
    profile = _quality_profile(draw_quality)
    if cancelled():
        raise InterruptedError()

    own = _images.own
    transposed = own(ImageOps.exif_transpose(image))
    source = own(transposed.convert("RGBA"))
    if transposed is not image:transposed.close()
    scale = min(width / source.width, height / source.height)
    fitted = (source.width * scale, source.height * scale)
    limit = portrait_sample_limit(int(detail), draw_quality)
    if draw_quality in ("GPU enhanced", "Pixel Accurate"):
        if gpu_performance == "High throughput":
            limit = round(limit * 1.15)
        elif gpu_performance == "Maximum":
            limit = round(limit * 1.35)
        # Use additional analysis resolution only when CUDA is actually active
        # and the configured pool has room. This makes high-VRAM NVIDIA cards
        # useful for complex images without penalising CPU fallback machines.
        try:
            gpu_info=gpu_acceleration_info(gpu_mode,gpu_vram,gpu_performance)
            budget=int(gpu_info.vram_budget_mb or 0) if gpu_info.accelerated else 0
            if budget>=12288:limit=round(limit*1.30)
            elif budget>=8192:limit=round(limit*1.20)
            elif budget>=4096:limit=round(limit*1.10)
            if acceleration_meta is not None:
                acceleration_meta.update(gpu_info.as_dict())
                acceleration_meta['vram_resolution_boost']=round(limit/portrait_sample_limit(int(detail),draw_quality),3)
        except InterruptedError:
            raise
        except Exception:
            pass
    sample_scale = min(limit / max(fitted), 1.0)
    size = tuple(max(1, round(v * sample_scale)) for v in fitted)
    if cancelled():
        raise InterruptedError()

    flat = own(Image.new("RGBA", source.size, "white"))
    flat.alpha_composite(source)
    source.close()
    source_gray = own(flat.convert("L"))
    flat.close()
    if cancelled():
        raise InterruptedError()
    # GPU enhanced (and high-throughput CUDA modes) use an adaptive cubic scaler
    # with restrained sharpening.  CPU/Lanczos remains the deterministic fallback.
    use_gpu_scaler = draw_quality in ("GPU enhanced", "Pixel Accurate") or gpu_performance in ("High throughput", "Maximum")
    if preview_detail_mode:
        from PreviewDetailEngine import detail_aware_resize_gray
        gray = own(detail_aware_resize_gray(source_gray, size, preview_detail_mode, cancelled=cancelled, metadata=preview_detail_meta))
        if acceleration_meta is not None:
            acceleration_meta["scaler"] = f"Detail-aware preview ({preview_detail_mode})"
    elif use_gpu_scaler:
        gray, scale_info = gpu_resize_gray_advanced(source_gray, size, gpu_mode, gpu_vram, gpu_performance,cancelled=cancelled)
        own(gray)
        if acceleration_meta is not None:
            acceleration_meta.update(scale_info.as_dict())
            acceleration_meta["scaler"] = scale_info.scaler
    else:
        gray = own(source_gray.resize(size, Image.Resampling.LANCZOS))
        if acceleration_meta is not None:
            acceleration_meta.setdefault("scaler", "CPU Lanczos")
    if gray is not source_gray:source_gray.close()
    if cancelled():
        raise InterruptedError()
    gray = own(ImageOps.autocontrast(gray, cutoff=1))
    if contrast != 1.0:
        gray = own(ImageEnhance.Contrast(gray).enhance(float(contrast)))
    gray = own(gray.filter(ImageFilter.UnsharpMask(radius=.75, percent=110, threshold=3)))
    if cancelled():
        raise InterruptedError()

    scaler_name=acceleration_meta.get("scaler","CPU Lanczos") if acceleration_meta is not None else (f"Detail-aware preview ({preview_detail_mode})" if preview_detail_mode else "CPU Lanczos")
    accelerated, accel_info, gpu_session = gpu_enhance_portrait(
        gray, profile["local_contrast"], profile["tone_gamma"], subject_focus,
        profile["background_lift"], gpu_mode, gpu_vram, gpu_performance,cancelled=cancelled)
    if accelerated is not None:own(accelerated)
    if acceleration_meta is not None:
        if gpu_session is not None:
            acceleration_meta["_gpu_session"] = gpu_session
        acceleration_meta.update(accel_info.as_dict())
        acceleration_meta["scaler"]=scaler_name
    if cancelled():
        raise InterruptedError()
    if accelerated is not None:
        gray = own(accelerated)
    else:
        gray = own(_enhance_local_contrast(gray, profile["local_contrast"], cancelled=cancelled))
        gamma = profile["tone_gamma"]
        gray = own(gray.point(lambda v: max(0, min(255, round(255 * ((v / 255) ** gamma))))))
        if subject_focus and gray.width >= 24 and gray.height >= 24:
            px = gray.load(); w, h = gray.size
            cx, cy = (w - 1) / 2, (h - 1) / 2
            sx, sy = max(1.0, w * .62), max(1.0, h * .72)
            lift = profile["background_lift"]
            for y in range(h):
                if cancelled():
                    raise InterruptedError()
                dy = (y - cy) / sy
                for x in range(w):
                    dx = (x - cx) / sx
                    radial = math.hypot(dx, dy)
                    amount = max(0.0, min(1.0, (radial - .42) / .62))
                    if amount:
                        px[x, y] = min(255, round(px[x, y] + lift * amount))
    if cancelled():
        raise InterruptedError()
    return gray, fitted

def _detail_config(detail: int):
    detail = int(detail)
    if detail <= 6:
        return {"thresholds": (168, 108), "directions": ("h", "d1"),
                "spacing": 4, "edge_step": 3, "edge_threshold": 150,
                "edge_length": 3.2, "max_strokes": 1400}
    if detail <= 8:
        return {"thresholds": (185, 150, 115, 80), "directions": ("h", "h", "d1", "d2"),
                "spacing": 3, "edge_step": 2, "edge_threshold": 120,
                "edge_length": 4.2, "max_strokes": 3200}
    if detail == 9:
        return {"thresholds": (195, 165, 135, 105, 75), "directions": ("h", "v", "d1", "d2", "h"),
                "spacing": 2, "edge_step": 2, "edge_threshold": 95,
                "edge_length": 4.8, "max_strokes": 6000}
    return {"thresholds": (205, 178, 150, 122, 94, 68), "directions": ("h", "v", "d1", "d2", "h", "v"),
            "spacing": 2, "edge_step": 1, "edge_threshold": 78,
            "edge_length": 5.2, "max_strokes": 9000}


def _line_paths(width: int, height: int, direction: str, spacing: int,
                offset: int) -> Iterable[list[tuple[int, int]]]:
    """Yield scan paths for horizontal/vertical/diagonal hatching."""
    spacing = max(1, int(spacing)); offset %= spacing
    if direction == "h":
        for y in range(offset, height, spacing):
            yield [(x, y) for x in range(width)]
        return
    if direction == "v":
        for x in range(offset, width, spacing):
            yield [(x, y) for y in range(height)]
        return
    if direction == "d1":
        starts = [(x, 0) for x in range(width)] + [(0, y) for y in range(1, height)]
        for sx, sy in starts:
            if (sx + sy) % spacing != offset: continue
            path=[]; x,y=sx,sy
            while x < width and y < height:
                path.append((x,y)); x+=1; y+=1
            if path: yield path
        return
    if direction == "d2":
        starts = [(x, height-1) for x in range(width)] + [(0, y) for y in range(height-1)]
        for sx, sy in starts:
            if (sx + (height - 1 - sy)) % spacing != offset: continue
            path=[]; x,y=sx,sy
            while x < width and y >= 0:
                path.append((x,y)); x+=1; y-=1
            if path: yield path
        return
    raise ValueError(f"Unknown hatch direction: {direction}")


def _runs(path: Sequence[tuple[int, int]], pixels, threshold: int,
          min_run: int = 2, merge_gap: int = 1,
          max_run: int | None = None) -> list[tuple[int, int, int, int]]:
    """Compress dark pixels on a scan path into brush strokes.

    High-fidelity modes cap very long runs.  A single long black line can erase
    a small highlight or facial boundary that existed in the source; shorter
    segments preserve those local transitions while the global stroke budget
    still prevents runaway complexity.
    """
    result: list[tuple[int, int, int, int]] = []

    def emit(start: int | None, end: int | None):
        if start is None or end is None or end - start + 1 < min_run:
            return
        if not max_run or end - start + 1 <= max_run:
            x1,y1=path[start]; x2,y2=path[end]; result.append((x1,y1,x2,y2)); return
        total=end-start+1
        segments=max(1,math.ceil(total/max_run))
        base=total//segments; extra=total%segments; pos=start
        for index in range(segments):
            segment_length=base+(1 if index<extra else 0)
            seg_end=pos+segment_length-1
            if segment_length>=min_run:
                x1,y1=path[pos]; x2,y2=path[seg_end]; result.append((x1,y1,x2,y2))
            pos=seg_end+1

    start=None; last_ink=None; gap=0
    for index,(x,y) in enumerate(path):
        ink=pixels[x,y] < threshold
        if ink:
            if start is None:start=index
            last_ink=index; gap=0
        elif start is not None:
            gap+=1
            if gap > merge_gap:
                emit(start,last_ink); start=last_ink=None; gap=0
    emit(start,last_ink)
    return result


def _saliency_map(gray: Image.Image, subject_focus: bool, profile: dict,
                  gpu_mode: str = "Auto", acceleration_meta: dict | None = None,
                  gpu_vram: str = "Auto", gpu_performance: str = "Balanced", *,
                  cancelled=lambda: False) -> list[float]:
    """Structure score used only to choose among already valid hatch strokes."""
    session = acceleration_meta.get("_gpu_session") if acceleration_meta else None
    accelerated, accel_info = gpu_saliency(gray, subject_focus, profile, gpu_mode, gpu_vram, gpu_performance, session,cancelled=cancelled)
    if acceleration_meta is not None and (accel_info.accelerated or not acceleration_meta.get("accelerated")):
        acceleration_meta.update(accel_info.as_dict())
    if cancelled():
        raise InterruptedError()
    if accelerated is not None:
        return accelerated
    px=gray.load(); w,h=gray.size
    blur=gray.filter(ImageFilter.GaussianBlur(radius=1.2)); bp=blur.load()
    cx,cy=(w-1)/2,(h-1)/2; radius=max(1.0,math.hypot(cx,cy))
    scores=[1.0]*(w*h)
    for y in range(h):
        if cancelled():
            raise InterruptedError()
        ym=max(0,y-1); yp=min(h-1,y+1)
        for x in range(w):
            xm=max(0,x-1); xp=min(w-1,x+1)
            gx=abs(px[xp,y]-px[xm,y]); gy=abs(px[x,yp]-px[x,ym])
            gradient=min(1.0,(gx+gy)/190.0)
            local=min(1.0,abs(px[x,y]-bp[x,y])/42.0)
            darkness=(255-px[x,y])/255.0
            centre=0.0
            if subject_focus:
                centre=max(0.0,1.0-math.hypot(x-cx,y-cy)/radius)
            scores[y*w+x]=(1.0 + profile["structure_weight"]*(.72*gradient+.28*local)
                             + profile["dark_weight"]*darkness
                             + profile["centre_bias"]*centre)
    return scores


def _stroke_score(stroke: tuple[int,int,int,int], saliency: Sequence[float], pixels,
                  width: int, height: int) -> float:
    x1,y1,x2,y2=stroke
    values=[]; darkness=[]
    for t in (0.0,.25,.5,.75,1.0):
        x=max(0,min(width-1,round(x1+(x2-x1)*t)))
        y=max(0,min(height-1,round(y1+(y2-y1)*t)))
        values.append(saliency[y*width+x]); darkness.append((255-pixels[x,y])/255.0)
    length=math.hypot(x2-x1,y2-y1)
    # Prefer structurally rich regions but mildly reward useful, non-trivial runs.
    return sum(values)/len(values) + .12*sum(darkness)/len(darkness) + min(.10,length/120.0)


def _evenly_sample(items, wanted):
    if wanted >= len(items): return list(items)
    if wanted <= 0 or not items: return []
    return [items[min(len(items)-1,int((i+.5)*len(items)/wanted))] for i in range(wanted)]


def _select_tone_candidates(candidates, wanted, saliency, pixels, width, height,
                            priority_fraction: float, *, cancelled=lambda: False):
    """Blend high-value detail selection with spatially even coverage."""
    if wanted <= 0 or not candidates:return [],0
    wanted=min(wanted,len(candidates))
    priority_n=min(wanted,max(0,round(wanted*priority_fraction)))
    def scores():
        for index, stroke in enumerate(candidates):
            if index % 128 == 0 and cancelled():raise InterruptedError()
            yield (_stroke_score(stroke,saliency,pixels,width,height),index,stroke)
    # A heap reduces both sorting work and retained records for a small cap;
    # selecting most candidates is faster with one stable full sort.
    score_key=lambda item:(item[0],-item[1])
    if priority_n >= max(1, len(candidates) // 4):
        priority=sorted(scores(),key=score_key,reverse=True)[:priority_n]
    else:
        priority=heapq.nlargest(priority_n,scores(),key=score_key)
    selected_indices={i for _,i,_ in priority}
    rest_count=len(candidates)-priority_n
    coverage_count=wanted-priority_n
    coverage=[];rest_index=0
    if coverage_count:
        next_position=min(rest_count-1,int(.5*rest_count/coverage_count))
        for index,stroke in enumerate(candidates):
            if index % 128 == 0 and cancelled():raise InterruptedError()
            if index in selected_indices:continue
            if rest_index == next_position:
                coverage.append(stroke)
                if len(coverage) == coverage_count:break
                next_position=min(rest_count-1,int((len(coverage)+.5)*rest_count/coverage_count))
            rest_index+=1
    if cancelled():raise InterruptedError()
    # Priority strokes are intentionally drawn first so an interrupted portrait
    # keeps more identity-bearing structure than a scan-order prefix.
    return [stroke for _,_,stroke in priority]+coverage,priority_n


def _edge_strokes(gray: Image.Image, detail: int, cancelled: Callable[[], bool],
                  draw_quality: str = "Balanced", subject_focus: bool = True,
                  gpu_mode: str = "Auto", acceleration_meta: dict | None = None,
                  gpu_vram: str = "Auto", gpu_performance: str = "Balanced") -> list[tuple[int,int,int,int]]:
    """Create contour strokes, strongest and most useful edges first."""
    cfg=_detail_config(detail); profile=_quality_profile(draw_quality)
    px=gray.load(); w,h=gray.size; step=cfg["edge_step"]
    session = acceleration_meta.get("_gpu_session") if acceleration_meta else None
    accelerated_sobel, accel_info = gpu_sobel(gray, gpu_mode, gpu_vram, gpu_performance, session, subject_focus, profile,cancelled=cancelled)
    if acceleration_meta is not None and (accel_info.accelerated or not acceleration_meta.get("accelerated")):
        acceleration_meta.update(accel_info.as_dict())
    gx_flat=gy_flat=None
    if accelerated_sobel is not None:
        gx_flat,gy_flat=accelerated_sobel
    threshold=cfg["edge_threshold"]*profile["edge_threshold"]
    base_len=cfg["edge_length"]
    occupied={}
    cell=max(1,round(step*profile["edge_cell_scale"]))
    cx,cy=(w-1)/2,(h-1)/2; max_radius=max(1.0,math.hypot(cx,cy))
    for y in range(1,h-1,step):
        if cancelled():raise InterruptedError()
        for x in range(1,w-1,step):
            if gx_flat is not None:
                index=y*w+x;gx=gx_flat[index];gy=gy_flat[index]
            else:
                gx=((px[x+1,y-1]+2*px[x+1,y]+px[x+1,y+1])-(px[x-1,y-1]+2*px[x-1,y]+px[x-1,y+1]))
                gy=((px[x-1,y+1]+2*px[x,y+1]+px[x+1,y+1])-(px[x-1,y-1]+2*px[x,y-1]+px[x+1,y-1]))
            mag=abs(gx)+abs(gy)
            if mag < threshold:continue
            length=math.hypot(gx,gy)
            if length<=0:continue
            half=min(base_len*1.35,base_len*(.65+mag/650.0))/2
            tx,ty=-gy/length*half,gx/length*half
            x1=max(0,min(w-1,round(x-tx)));y1=max(0,min(h-1,round(y-ty)))
            x2=max(0,min(w-1,round(x+tx)));y2=max(0,min(h-1,round(y+ty)))
            if (x1,y1)==(x2,y2):continue
            radial=math.hypot(x-cx,y-cy)/max_radius
            centre=(1.0-min(1.0,radial)) if subject_focus else 0.0
            darkness=(255-px[x,y])/255.0
            score=mag*(1.0+profile["centre_bias"]*centre+.16*darkness)
            key=(x//cell,y//cell); stroke=(x1,y1,x2,y2)
            previous=occupied.get(key)
            if previous is None or score>previous[0]:occupied[key]=(score,stroke)
    candidates=list(occupied.values());candidates.sort(key=lambda item:item[0],reverse=True)
    return [stroke for _,stroke in candidates]


def _dot_strokes(gray: Image.Image, detail: int, cancelled: Callable[[], bool],
                 max_strokes: int | None = None) -> list[tuple[int,int,int,int]]:
    """Ordered-dither portrait mode for users who explicitly choose Dots."""
    bayer=((0,8,2,10),(12,4,14,6),(3,11,1,9),(15,7,13,5))
    px=gray.load();w,h=gray.size;step=2 if detail<=8 else 1;strokes=[]
    if max_strokes == 0:return strokes
    for y in range(0,h,step):
        if cancelled():raise InterruptedError()
        for x in range(0,w,step):
            darkness=255-px[x,y];threshold=(bayer[y%4][x%4]+.5)/16*255
            if darkness>threshold:
                strokes.append((x,y,x,y))
                if max_strokes is not None and len(strokes)>=max_strokes:
                    if cancelled():raise InterruptedError()
                    return strokes
    return strokes


def portrait_strokes(gray: Image.Image, detail: int = 8, lines: bool = True,
                     cancelled: Callable[[], bool] = lambda: False,
                     include_edges: bool = True, max_strokes: int | None = None,
                     draw_quality: str = "Balanced",
                     subject_focus: bool = True, gpu_mode: str = "Auto",
                     acceleration_meta: dict | None = None, gpu_vram: str = "Auto",
                     gpu_performance: str = "Balanced") -> tuple[list[list[tuple[int,int,int,int]]], PortraitStats]:
    """Build portrait strokes and release analysis arrays on every exit path."""
    converted = None
    try:
        if cancelled():
            raise InterruptedError()
        if gray.mode != "L":
            converted = gray.convert("L")
            gray = converted
        return _portrait_strokes_impl(
            gray, detail, lines, cancelled, include_edges, max_strokes,
            draw_quality, subject_focus, gpu_mode, acceleration_meta, gpu_vram, gpu_performance)
    finally:
        if converted is not None:converted.close()
        if acceleration_meta is not None:
            _release_portrait_session(acceleration_meta)


def _portrait_strokes_impl(gray: Image.Image, detail: int = 8, lines: bool = True,
                     cancelled: Callable[[], bool] = lambda: False,
                     include_edges: bool = True, max_strokes: int | None = None,
                     draw_quality: str = "Balanced",
                     subject_focus: bool = True, gpu_mode: str = "Auto",
                     acceleration_meta: dict | None = None, gpu_vram: str = "Auto",
                     gpu_performance: str = "Balanced") -> tuple[list[list[tuple[int,int,int,int]]], PortraitStats]:
    """Build one black stroke group that approximates grayscale by density."""
    profile=_quality_profile(draw_quality);cfg=dict(_detail_config(detail))
    if max_strokes is not None:
        from numbers import Integral
        if isinstance(max_strokes,bool) or not isinstance(max_strokes,Integral) or max_strokes<0:
            raise ValueError("max_strokes must be a nonnegative integer")
        cfg["max_strokes"]=min(cfg["max_strokes"],int(max_strokes))
    if not lines:
        dots=_dot_strokes(gray,detail,cancelled,max_strokes=cfg["max_strokes"])
        meta=acceleration_meta or {}
        return [dots],PortraitStats(len(dots),0,1,gray.size,0,draw_quality,
                                    str(meta.get("backend","CPU")),str(meta.get("device","CPU")),bool(meta.get("accelerated",False)))

    px=gray.load();w,h=gray.size;total_budget=cfg["max_strokes"]
    edge_budget=round(total_budget*(profile["edge_share"] if include_edges else 0))
    tone_budget=total_budget-edge_budget
    saliency=_saliency_map(gray,subject_focus,profile,gpu_mode,acceleration_meta,gpu_vram,gpu_performance,
                           cancelled=cancelled)

    layer_candidates=[]
    for layer,(threshold,direction) in enumerate(zip(cfg["thresholds"],cfg["directions"])):
        if cancelled():raise InterruptedError()
        threshold=min(252,threshold+profile["threshold_boost"])
        spacing=cfg["spacing"]+(1 if layer==0 and detail<=8 else 0);offset=layer%spacing
        merge_gap=(1 if detail<=8 else 2) if profile["merge_gap"] is None else profile["merge_gap"]
        candidates=[]
        for path in _line_paths(w,h,direction,spacing,offset):
            if cancelled():
                raise InterruptedError()
            candidates.extend(_runs(path,px,threshold,min_run=2 if detail>=8 else 3,
                                    merge_gap=merge_gap,max_run=profile["max_run"]))
        layer_candidates.append(candidates)

    count_layers=max(1,len(layer_candidates));weights=[1.0+.18*i for i in range(count_layers)]
    weight_total=sum(weights);allocations=[int(tone_budget*wgt/weight_total) for wgt in weights]
    while sum(allocations)<tone_budget:allocations[-1]+=1

    selected_layers=[];priority_total=0;unused=0
    for candidates,allocation in zip(layer_candidates,allocations):
        take=min(len(candidates),allocation)
        selected,priority=_select_tone_candidates(candidates,take,saliency,px,w,h,profile["priority_fraction"],cancelled=cancelled)
        selected_layers.append(selected);priority_total+=priority;unused+=allocation-len(selected)

    # Sparse bright layers can leave budget unused. Reallocate to darker layers,
    # where eyes/hair/deep contours usually provide more useful information.
    if unused:
        for idx in reversed(range(len(layer_candidates))):
            if unused<=0:break
            existing=set(selected_layers[idx])
            remaining=[s for s in layer_candidates[idx] if s not in existing]
            extra,priority=_select_tone_candidates(remaining,min(unused,len(remaining)),saliency,px,w,h,profile["priority_fraction"],cancelled=cancelled)
            selected_layers[idx].extend(extra);priority_total+=priority;unused-=len(extra)

    # Darkest tonal layers first improves partial drawings and preserves small
    # identity details before broad mid-tone hatching consumes time.
    tone=[]
    for selected in reversed(selected_layers):tone.extend(selected)

    edges=[]
    if include_edges and edge_budget:
        edges=_edge_strokes(gray,detail,cancelled,draw_quality,subject_focus,gpu_mode,acceleration_meta,gpu_vram,gpu_performance)[:edge_budget]

    strokes=edges+tone
    meta=acceleration_meta or {}
    result=PortraitStats(len(tone),len(edges),len(cfg["thresholds"]),gray.size,
                         priority_total,draw_quality,str(meta.get("backend","CPU")),
                         str(meta.get("device","CPU")),bool(meta.get("accelerated",False)))
    if cancelled():
        raise InterruptedError()
    return [strokes],result
