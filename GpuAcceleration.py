"""Optional NVIDIA CUDA acceleration for Image Draw Bot portrait preprocessing.

v1.0.6 keeps the heavy analysis stage on CUDA where possible. CuPy launches
CUDA kernels on the selected NVIDIA device; fused RawKernels handle portrait
enhancement and saliency+Sobel work. A configurable CuPy memory-pool limit
controls how much VRAM Image Draw Bot may retain. CPU remains a safe fallback.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from functools import wraps
import math
import threading
import time
from typing import Any

import numpy as np
from PIL import Image

from GpuHardware import best_nvidia_gpu

ACCELERATION_MODES = ("Auto", "CPU", "NVIDIA CUDA")
VRAM_BUDGETS = ("Auto", "25%", "50%", "75%", "90%", "2 GB", "4 GB", "6 GB", "8 GB", "12 GB", "16 GB", "24 GB")
GPU_PERFORMANCE_MODES = ("Balanced", "High throughput", "Maximum")
MIN_GPU_PIXELS = 16_384
_MIB = 1024 * 1024
_GPU_LOCK = threading.RLock()


def _cancel(cancelled):
    if cancelled():raise InterruptedError()


def _cancellable(function):
    @wraps(function)
    def checked(*args, **kwargs):
        cancelled=kwargs.get("cancelled",lambda:False)
        _cancel(cancelled)
        result=None
        try:
            result=function(*args,**kwargs)
            _cancel(cancelled)
            return result
        except InterruptedError as error:
            # A late Stop must release a just-created image/session rather than
            # leaving it reachable from the cancellation traceback.
            for item in result if isinstance(result,tuple) else ():
                if isinstance(item,Image.Image):item.close()
                elif isinstance(item,GpuAnalysisSession):release_analysis_session(item)
            result=None
            import traceback
            traceback.clear_frames(error.__traceback__)
            raise
    return checked


@dataclass(frozen=True)
class AccelerationInfo:
    requested: str
    backend: str
    accelerated: bool
    device: str = "CPU"
    total_vram_mb: int | None = None
    free_vram_mb: int | None = None
    reason: str = ""
    vram_budget_mb: int | None = None
    pool_used_mb: int | None = None
    pool_cached_mb: int | None = None
    compute_capability: str = ""
    multiprocessors: int | None = None
    performance_mode: str = "Balanced"
    allocation_mode: str = "Adaptive"
    tile_rows: int | None = None
    workspace_estimate_mb: int | None = None
    cuda_execution: str = ""
    scaler: str = "CPU Lanczos"
    hardware_detected: bool = False
    hardware_device: str = ""
    driver_version: str = ""
    hardware_source: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GpuAnalysisSession:
    cp: Any
    cnd: Any
    arr: Any
    info: AccelerationInfo
    width: int
    height: int
    saliency_map: Any = None
    gx: Any = None
    gy: Any = None


_BACKEND_CACHE: tuple[str, Any, str, int | None, int | None, str, int | None] | None | bool = False
_BACKEND_DEVICE_ID: int | None = None
_DISABLED_REASON = ""
_KERNEL_CACHE: dict[str, Any] = {}


def validate_acceleration_mode(mode: str) -> str:
    if mode not in ACCELERATION_MODES:
        raise ValueError("GPU acceleration must be Auto, CPU, or NVIDIA CUDA.")
    return mode


def validate_vram_budget(value: str) -> str:
    if value not in VRAM_BUDGETS:
        raise ValueError("VRAM budget must be Auto, a supported percentage, or a supported GB value.")
    return value


def validate_gpu_performance(value: str) -> str:
    if value not in GPU_PERFORMANCE_MODES:
        raise ValueError("GPU performance must be Balanced, High throughput, or Maximum.")
    return value


def _decode_name(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "NVIDIA CUDA GPU")


def _prop(props: Any, *names: str, default=None):
    for name in names:
        if isinstance(props, dict) and name in props:
            return props[name]
        if hasattr(props, name):
            return getattr(props, name)
    return default


def _load_cupy():
    global _BACKEND_DEVICE_ID, _DISABLED_REASON
    _BACKEND_DEVICE_ID = None
    hardware = best_nvidia_gpu(refresh=True)
    try:
        import cupy as cp
        from cupyx.scipy import ndimage as cnd
        count = int(cp.cuda.runtime.getDeviceCount())
        if count < 1:
            raise RuntimeError("CuPy reported zero CUDA devices.")

        # Select the strongest visible NVIDIA CUDA device instead of relying on
        # whatever device happened to be current in the process. This matters on
        # systems with more than one NVIDIA adapter.
        best = None
        failures = []
        for device_id in range(count):
            try:
                with cp.cuda.Device(device_id):
                    props = cp.cuda.runtime.getDeviceProperties(device_id)
                    free_b, total_b = cp.cuda.runtime.memGetInfo()
                    candidate = (int(total_b), int(free_b), int(device_id), props)
                    if best is None or candidate[:2] > best[:2]:
                        best = candidate
            except InterruptedError:
                raise
            except Exception as exc:
                # A disconnected or unusable adapter must not hide another
                # healthy CUDA device in the same machine.
                failures.append(f"device {device_id}: {type(exc).__name__}: {exc}")
        if best is None:
            raise RuntimeError("No CUDA device could be initialized. " + "; ".join(failures))
        total_b, free_b, device_id, props = best
        cp.cuda.Device(device_id).use()
        device = _decode_name(_prop(props, "name"))
        major = int(_prop(props, "major", default=0) or 0)
        minor = int(_prop(props, "minor", default=0) or 0)
        capability = f"{major}.{minor}" if major else ""
        sms = int(_prop(props, "multiProcessorCount", "multi_processor_count", default=0) or 0) or None
        _BACKEND_DEVICE_ID = device_id
        _DISABLED_REASON = ""
        return ("CuPy CUDA", (cp, cnd), device, int(total_b // _MIB), int(free_b // _MIB), capability, sms)
    except InterruptedError:
        raise
    except Exception as exc:
        if hardware is not None:
            _DISABLED_REASON = (
                f"{hardware.name} detected via {hardware.source or 'Windows'}, but the CUDA/CuPy backend could not load: "
                f"{type(exc).__name__}: {exc}. Run Start.bat --update or Install-GPU-NVIDIA.bat."
            )
        else:
            _DISABLED_REASON = (
                f"No NVIDIA GPU was detected by nvidia-smi/Windows CIM and CuPy could not open CUDA: "
                f"{type(exc).__name__}: {exc}."
            )
        return None


def _resolve_backend(mode: str):
    global _BACKEND_CACHE
    validate_acceleration_mode(mode)
    if mode == "CPU":
        return None
    with _GPU_LOCK:
        if _BACKEND_CACHE is False:
            _BACKEND_CACHE = _load_cupy()
        backend = _BACKEND_CACHE
        if backend is not None and _BACKEND_DEVICE_ID is not None:
            cp, _ = backend[1]
            try:
                # CUDA's current device belongs to the calling thread. A
                # successful probe on the UI thread does not select that device
                # on later analysis/benchmark worker threads.
                cp.cuda.Device(_BACKEND_DEVICE_ID).use()
            except InterruptedError:
                raise
            except Exception as exc:
                _disable_backend(exc)
                return None
        return backend


def _fallback_info(mode: str, reason: str = "", performance: str = "Balanced") -> AccelerationInfo:
    hardware = best_nvidia_gpu() if mode != "CPU" else None
    if not reason and mode == "CPU":
        reason = "CPU mode selected."
    elif not reason:
        reason = _DISABLED_REASON or "Compatible NVIDIA CUDA backend was not available."
    device = hardware.name if hardware is not None else "CPU"
    return AccelerationInfo(
        mode, "CPU", False, device, reason=reason, performance_mode=performance,
        hardware_detected=hardware is not None, hardware_device=hardware.name if hardware else "",
        driver_version=hardware.driver_version if hardware else "", hardware_source=hardware.source if hardware else "",
    )


def reset_backend_cache() -> None:
    """Forget a previous failed/successful CUDA probe and detect again on next use."""
    global _BACKEND_CACHE, _BACKEND_DEVICE_ID, _DISABLED_REASON
    with _GPU_LOCK:
        _BACKEND_CACHE = False
        _BACKEND_DEVICE_ID = None
        _DISABLED_REASON = ""


def resolve_vram_budget_mb(setting: str, total_mb: int, free_mb: int) -> int:
    validate_vram_budget(setting)
    total_mb = max(0, int(total_mb))
    free_mb = max(0, min(total_mb, int(free_mb)))
    reserve = min(max(32, min(2048, round(total_mb * .08))), math.ceil(free_mb * .20))
    safe_free = max(0, free_mb - reserve)
    if setting == "Auto":
        requested = round(total_mb * .70)
    elif setting.endswith("%"):
        requested = round(total_mb * (int(setting[:-1]) / 100.0))
    else:
        requested = int(setting.split()[0]) * 1024
    return max(0, min(requested, safe_free))


def _pool_stats(cp) -> tuple[int, int]:
    try:
        pool = cp.get_default_memory_pool()
        return int(pool.used_bytes() // _MIB), int(pool.total_bytes() // _MIB)
    except Exception:
        return 0, 0


def _configure_memory_pool(cp, budget_mb: int) -> None:
    if int(budget_mb) <= 0:
        # CuPy interprets a zero limit as unlimited, not as an empty budget.
        raise MemoryError("No CUDA memory budget remains")
    pool = cp.get_default_memory_pool()
    try:
        pool.set_limit(size=int(budget_mb) * _MIB)
    except TypeError:
        pool.set_limit(int(budget_mb) * _MIB)


def cuda_context(mode: str = "Auto", vram_budget: str = "Auto", performance: str = "Balanced"):
    """Return the selected CuPy module plus configured AccelerationInfo.

    Public Block-D bridge for CUDA-only planners. It uses the same device
    selection and memory-pool budget as the rest of Image Draw Bot; callers must
    treat ``None`` as a normal CPU-fallback condition.
    """
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    backend=_resolve_backend(mode)
    if backend is None:return None
    _name,module,*_rest=backend
    cp,_cnd=module
    info=acceleration_info(mode,vram_budget,performance)
    if not info.accelerated:return None
    return cp,info


def acceleration_info(mode: str = "Auto", vram_budget: str = "Auto", performance: str = "Balanced") -> AccelerationInfo:
    validate_acceleration_mode(mode)
    validate_vram_budget(vram_budget)
    validate_gpu_performance(performance)
    backend = _resolve_backend(mode)
    if backend is None:
        return _fallback_info(mode, performance=performance)
    name, module, device, total_mb, free_mb, capability, sms = backend
    cp, _ = module
    try:
        free_b, total_b = cp.cuda.runtime.memGetInfo()
        total_mb, free_mb = int(total_b // _MIB), int(free_b // _MIB)
        used, cached = _pool_stats(cp)
        # memGetInfo excludes this process's retained pool. The configured limit
        # covers both its live arrays and reusable blocks, not only new driver
        # allocations; account for those bytes once.
        budget_mb = resolve_vram_budget_mb(vram_budget, total_mb, min(total_mb, free_mb + cached))
        if budget_mb <= used:
            raise MemoryError("No CUDA workspace remains after live allocations")
        with _GPU_LOCK:
            _configure_memory_pool(cp, budget_mb)
    except InterruptedError:
        raise
    except Exception as exc:
        return _fallback_info(mode, f"Could not configure the CUDA memory pool: {type(exc).__name__}: {exc}", performance)
    hardware = best_nvidia_gpu()
    return AccelerationInfo(mode, name, True, device, total_mb, free_mb, "", budget_mb,
                            used, cached, capability, sms, performance, "Adaptive", None, None,
                            "CuPy RawKernel FP32 (CUDA SMs/CUDA cores)", "CPU Lanczos",
                            hardware is not None, hardware.name if hardware else device,
                            hardware.driver_version if hardware else "", hardware.source if hardware else "CuPy")



def estimate_workspace_mb(width: int, height: int, arrays: int = 10, safety: float = 1.30) -> int:
    """Conservative FP32 workspace estimate used before allocating CUDA arrays."""
    pixels=max(1,int(width))*max(1,int(height))
    return max(1, int(math.ceil(pixels*4*max(1,int(arrays))*float(safety)/_MIB)))


def available_vram_mb(info: AccelerationInfo) -> int:
    """Additional usable pool space, preserving explicit zero/free constraints."""
    used = max(0, int(getattr(info, "pool_used_mb", None) or 0))
    cached = max(used, int(getattr(info, "pool_cached_mb", None) or 0))
    free = None if info.free_vram_mb is None else max(0, int(info.free_vram_mb))
    budget = info.vram_budget_mb
    if budget is None:
        return 0 if free is None else free + cached - used
    remaining = max(0, int(budget) - used)
    return remaining if free is None else min(remaining, free + cached - used)


def plan_vram_allocation(info: AccelerationInfo, width: int, height: int, arrays: int = 10,
                         overlap: int = 8) -> dict:
    """Choose full-frame or row-tiled CUDA processing within the selected pool budget.

    The planner never consumes the last part of the configured budget.  That
    headroom is important on Windows because the desktop compositor and the
    target drawing app may allocate VRAM while Image Draw Bot is analysing.
    """
    full_mb=estimate_workspace_mb(width,height,arrays)
    budget=available_vram_mb(info)
    usable=budget*.76
    if full_mb <= usable:
        return {"mode":"full","tile_rows":int(height),"workspace_mb":full_mb,"budget_mb":budget}
    # Bytes/row for the live arrays + safety.  Keep tiles large enough for CUDA
    # efficiency but small enough to leave transient-kernel allocation room.
    bytes_per_row=max(1,int(width))*4*max(1,int(arrays))*1.35
    rows=min(int(height),int((usable*_MIB)//max(1,bytes_per_row)))
    core=rows-2*max(0,int(overlap))
    if core < 1:
        raise MemoryError("CUDA budget cannot fit one working row and its overlap")
    return {"mode":"tiled","tile_rows":core,"workspace_mb":full_mb,"budget_mb":budget}


def _relieve_pool_pressure(cp, budget_mb: int) -> None:
    """Release cached CuPy blocks when the pool approaches its retention limit."""
    used,cached=_pool_stats(cp)
    if cached > max(96,int(budget_mb*.72)) and cached-used > 64:
        release_gpu_memory_cache(cp)


def release_gpu_memory_cache(cp) -> dict:
    """Synchronize and release retained GPU/pinned blocks before a bounded retry."""
    before_used,before_cached=_pool_stats(cp)
    try: cp.cuda.Stream.null.synchronize()
    except Exception: pass
    try: cp.get_default_memory_pool().free_all_blocks()
    except Exception: pass
    try: cp.get_default_pinned_memory_pool().free_all_blocks()
    except Exception: pass
    after_used,after_cached=_pool_stats(cp)
    return {
        'before_used_mb':int(before_used),'before_cached_mb':int(before_cached),
        'after_used_mb':int(after_used),'after_cached_mb':int(after_cached),
    }


def is_gpu_memory_error(error: BaseException) -> bool:
    """Recognise CUDA/OpenCL/host allocation failures without importing optional runtimes."""
    seen=set();current=error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name=type(current).__name__.lower();message=str(current or '').lower()
        if isinstance(current,MemoryError) or any(token in name for token in ('outofmemory','memoryallocation','memoryerror')):
            return True
        if any(token in message for token in (
            'out of memory','outofmemory','cuda_error_out_of_memory','memory allocation',
            'cl_mem_object_allocation_failure','cl_out_of_resources','failed to allocate',
            'cannot allocate memory','insufficient memory')):
            return True
        current=getattr(current,'__cause__',None) or getattr(current,'__context__',None)
    return False


def gpu_memory_recovery_steps(tile_rows: int, batch_size: int, *, max_retries: int=3) -> list[dict]:
    """Return deterministic progressively smaller CUDA work units after OOM."""
    rows=max(1,int(tile_rows or 1));batch=max(1,int(batch_size or 1));steps=[]
    retries=max(0,min(4,int(max_retries or 0)))
    for attempt in range(retries+1):
        steps.append({'attempt':attempt,'tile_rows':rows,'batch_size':batch})
        if rows>8: rows=max(8,rows//2)
        elif rows>1: rows=max(1,rows//2)
        if batch>256: batch=max(256,batch//2)
        elif batch>1: batch=max(1,batch//2)
    # Avoid pointless identical attempts when the original work unit is already tiny.
    out=[]
    for step in steps:
        if not out or (step['tile_rows'],step['batch_size']) != (out[-1]['tile_rows'],out[-1]['batch_size']):
            out.append(step)
    return out


def gpu_score_tile_rows(info: AccelerationInfo, width: int, height: int, *, bytes_per_pixel: int=64, share: float=.42) -> int:
    """Bound accuracy-score tiles to a conservative fraction of current free/budget VRAM."""
    width=max(1,int(width));height=max(1,int(height));bpp=max(8,int(bytes_per_pixel))
    budget=available_vram_mb(info)
    usable=budget*max(.10,min(.70,float(share)))
    rows=int((usable*_MIB)//max(1,width*bpp))
    if rows < 1:
        raise MemoryError("CUDA budget cannot fit one accuracy-scoring row")
    return max(1,min(height,1024,rows))


def _tile_ranges(height: int, core_rows: int, overlap: int):
    core_rows=max(1,int(core_rows)); overlap=max(0,int(overlap)); start=0
    while start < height:
        end=min(height,start+core_rows)
        read0=max(0,start-overlap); read1=min(height,end+overlap)
        yield start,end,read0,read1,start-read0,end-read0
        start=end


@_cancellable
def resize_gray_advanced(gray: Image.Image, size: tuple[int,int], mode: str="Auto",
                         vram_budget: str="Auto", performance: str="Balanced", *,
                         cancelled=lambda:False) -> tuple[Image.Image, AccelerationInfo]:
    """High-quality scaler with CUDA cubic resampling and safe CPU fallback.

    CUDA mode uses cubic spline resampling plus a restrained post-resize unsharp
    pass.  Very large sources are pre-reduced with Lanczos to cap transfer/VRAM
    use before the GPU stage; this avoids allocating a 20+ MP FP32 frame merely
    to produce a few-hundred-pixel planning image.
    """
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    target=(max(1,int(size[0])),max(1,int(size[1])))
    if gray.mode!="L": gray=gray.convert("L")
    if gray.size==target:
        return gray.copy(), acceleration_info(mode,vram_budget,performance)
    info=acceleration_info(mode,vram_budget,performance)
    if not info.accelerated or mode=="CPU":
        return gray.resize(target,Image.Resampling.LANCZOS), replace(info,scaler="CPU Lanczos")
    backend=_resolve_backend(mode)
    if backend is None:
        return gray.resize(target,Image.Resampling.LANCZOS), replace(info,scaler="CPU Lanczos")
    _,module,*_=backend; cp,cnd=module
    try:
        # Pre-reduce only when the source is far larger than the output.  This is
        # still high quality because the final GPU pass operates near target scale.
        work=gray
        ratio=max(gray.width/target[0],gray.height/target[1])
        if ratio>4.0:
            interim=(max(target[0],min(gray.width,target[0]*4)),max(target[1],min(gray.height,target[1]*4)))
            work=gray.resize(interim,Image.Resampling.LANCZOS)
        plan=plan_vram_allocation(info,work.width,work.height,arrays=5,overlap=4)
        if plan["mode"]!="full":
            return gray.resize(target,Image.Resampling.LANCZOS), replace(info,scaler="CPU Lanczos (GPU resize VRAM fallback)",tile_rows=plan["tile_rows"],workspace_estimate_mb=plan["workspace_mb"])
        with _GPU_LOCK:
            _relieve_pool_pressure(cp,int(info.vram_budget_mb or 256))
            arr=_upload_gray(cp,work,performance)
            zoom=(target[1]/work.height,target[0]/work.width)
            # Cubic spline interpolation gives better small facial/line detail
            # than bilinear scaling while remaining deterministic.
            out=cnd.zoom(arr,zoom=zoom,order=3,mode="nearest",prefilter=True)
            if out.shape!=(target[1],target[0]):
                out=out[:target[1],:target[0]]
                if out.shape!=(target[1],target[0]):
                    # Rare shape-rounding mismatch: finish safely on CPU.
                    host=cp.asnumpy(cp.clip(cp.rint(out),0,255).astype(cp.uint8))
                    tmp=Image.fromarray(host).resize(target,Image.Resampling.LANCZOS)
                    return tmp,replace(_refresh_info(info,cp),scaler="CUDA cubic + CPU final fit")
            blur=cnd.gaussian_filter(out,sigma=.62,mode="nearest")
            sharpened=cp.clip(out+(out-blur)*.20,0,255)
            host=cp.asnumpy(cp.rint(sharpened).astype(cp.uint8))
            info=replace(_refresh_info(info,cp),scaler="CUDA cubic + adaptive unsharp",tile_rows=target[1],workspace_estimate_mb=plan["workspace_mb"])
            del arr,out,blur,sharpened
        return Image.fromarray(host),info
    except InterruptedError:
        raise
    except Exception as exc:
        # Resizing is never allowed to disable the entire drawing workflow.
        return gray.resize(target,Image.Resampling.LANCZOS),replace(_fallback_info(mode,f"CUDA scaler fallback: {type(exc).__name__}: {exc}",performance),scaler="CPU Lanczos fallback")

def clear_gpu_cache(mode: str = "Auto") -> dict:
    backend = _resolve_backend(mode)
    if backend is None:
        return {"cleared": False, "reason": _DISABLED_REASON or "CUDA backend is not active."}
    _, module, *_ = backend
    cp, _ = module
    with _GPU_LOCK:
        before_used, before_cached = _pool_stats(cp)
        try:
            cp.cuda.Stream.null.synchronize()
        except Exception:
            pass
        cp.get_default_memory_pool().free_all_blocks()
        try:
            cp.get_default_pinned_memory_pool().free_all_blocks()
        except Exception:
            pass
        after_used, after_cached = _pool_stats(cp)
    return {"cleared": True, "before_used_mb": before_used, "before_cached_mb": before_cached,
            "after_used_mb": after_used, "after_cached_mb": after_cached}


def palette_indices_rgba(image: Image.Image, palette: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...],
                         candidate_indices: list[int] | tuple[int, ...], custom_flags: list[bool] | tuple[bool, ...],
                         *, color_rendering: str = "Perceptual match", custom_mode: str = "Calibrated palette",
                         color_fidelity: str = "Balanced",
                         skip_white: bool = True, mode: str = "Auto", vram_budget: str = "Auto",
                         performance: str = "High throughput") -> tuple[tuple[Any, Any] | None, AccelerationInfo]:
    """Return ``(indices, drawable_mask)`` computed on CUDA, or ``None`` on fallback.

    The CPU still converts the index map into exact horizontal runs afterwards;
    CUDA handles the expensive per-pixel palette distance search.  This is used
    only for single-layer colour planning so layered/dithered modes keep their
    exact CPU algorithm.
    """
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    from ColorFidelity import validate_color_fidelity
    validate_color_fidelity(color_fidelity)
    if mode == "CPU":
        return None, _fallback_info(mode, performance=performance)
    rgba = image.convert("RGBA")
    if rgba.width * rgba.height < MIN_GPU_PIXELS and performance == "Balanced":
        return None, _fallback_info(mode, "Image is small enough that CPU colour planning is faster.", performance)
    backend = _resolve_backend(mode)
    if backend is None:
        return None, _fallback_info(mode, performance=performance)
    name, module, *_ = backend
    cp, _ = module
    try:
        info = acceleration_info(mode, vram_budget, performance)
        if not info.accelerated:
            return None, info
        candidates = [int(i) for i in candidate_indices if 0 <= int(i) < len(palette)] or list(range(len(palette)))
        pal = [tuple(int(v) for v in palette[i][:3]) for i in candidates]
        custom = [bool(custom_flags[i]) if i < len(custom_flags) else False for i in candidates]
        plan = plan_vram_allocation(info, rgba.width, rgba.height, arrays=max(10, min(40, len(candidates) + 8)), overlap=0)
        import numpy as np
        source = np.frombuffer(rgba.tobytes(), dtype=np.uint8).reshape(rgba.height, rgba.width, 4)
        out_index = np.zeros((rgba.height, rgba.width), dtype=np.int16)
        out_mask = np.zeros((rgba.height, rgba.width), dtype=np.bool_)
        candidate_host = np.asarray(candidates, dtype=np.int16)
        with _GPU_LOCK:
            _relieve_pool_pressure(cp, int(info.vram_budget_mb or 256))
            candidate_gpu = cp.asarray(candidate_host)
            palette_gpu = cp.asarray(np.asarray(pal, dtype=np.float32))
            custom_gpu = cp.asarray(np.asarray(custom, dtype=np.bool_))
            for start, end, read0, read1, core0, core1 in _tile_ranges(rgba.height, plan["tile_rows"], 0):
                raw = cp.asarray(source[read0:read1], dtype=cp.float32)
                alpha = raw[..., 3:4]
                rgb = cp.where(alpha >= 255.0, raw[..., :3], (raw[..., :3] * alpha + 255.0 * (255.0 - alpha)) / 255.0)
                visible = alpha[..., 0] > 0.0
                if skip_white:
                    visible = visible & (cp.min(rgb, axis=2) < 245.0)
                def to_oklab(arr):
                    c = cp.clip(arr / 255.0, 0.0, 1.0)
                    lin = cp.where(c <= 0.04045, c / 12.92, cp.power((c + 0.055) / 1.055, 2.4))
                    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
                    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
                    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
                    ss = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
                    ll, mm, s3 = cp.cbrt(l), cp.cbrt(m), cp.cbrt(ss)
                    return cp.stack((
                        0.2104542553 * ll + 0.7936177850 * mm - 0.0040720468 * s3,
                        1.9779984951 * ll - 2.4285922050 * mm + 0.4505937099 * s3,
                        0.0259040371 * ll + 0.7827717662 * mm - 0.8086757660 * s3,
                    ), axis=-1)

                def oklab_chroma_hue(lab):
                    aa, bb = lab[..., 1], lab[..., 2]
                    chroma = cp.sqrt(aa * aa + bb * bb) * 100.0
                    hue = cp.mod(cp.degrees(cp.arctan2(bb, aa)), 360.0)
                    return chroma, hue

                src_ok = to_oklab(rgb)
                pal_ok = to_oklab(palette_gpu)
                if color_rendering == "RGB nearest":
                    rgb_diff = rgb[:, :, None, :] - palette_gpu[None, None, :, :]
                    dist = cp.sqrt(cp.sum(rgb_diff * rgb_diff, axis=3) / 3.0) / 255.0 * 100.0
                else:
                    ok_diff = src_ok[:, :, None, :] - pal_ok[None, None, :, :]
                    dist = cp.sqrt(cp.sum(ok_diff * ok_diff, axis=3)) * 100.0
                threshold = 0.0006
                if color_rendering != "RGB nearest" and color_fidelity in ("Balanced", "Faithful"):
                    src_L = src_ok[..., 0] * 100.0
                    pal_L = pal_ok[..., 0] * 100.0
                    light_error = cp.abs(src_L[:, :, None] - pal_L[None, None, :])
                    dark_loss = cp.maximum(src_L[:, :, None] - pal_L[None, None, :], 0.0)
                    src_chroma, src_hue = oklab_chroma_hue(src_ok)
                    pal_chroma, pal_hue = oklab_chroma_hue(pal_ok)
                    chroma_error = cp.abs(src_chroma[:, :, None] - pal_chroma[None, None, :])
                    hue_delta = cp.abs(src_hue[:, :, None] - pal_hue[None, None, :])
                    hue_error = cp.minimum(hue_delta, 360.0 - hue_delta)
                    hue_error = cp.where(cp.minimum(src_chroma[:, :, None], pal_chroma[None, None, :]) < 2.5, 0.0, hue_error)
                    bright_boost = 1.0 + cp.maximum(src_L - 52.0, 0.0)[:, :, None] / 80.0
                    vivid = src_chroma[:, :, None] >= 5.0
                    neutral_cut = cp.maximum(2.5, src_chroma[:, :, None] * 0.28)
                    neutral_loss = cp.where(vivid & (pal_chroma[None, None, :] < neutral_cut),
                                            src_chroma[:, :, None] - pal_chroma[None, None, :], 0.0)
                    hue_excess = cp.where(vivid, cp.maximum(hue_error - 45.0, 0.0), 0.0)
                    hue_extreme = cp.where(vivid, cp.maximum(hue_error - 85.0, 0.0), 0.0)
                    if color_fidelity == "Balanced":
                        family_penalty = neutral_loss * 0.18 + hue_excess * 0.035 + hue_extreme * 0.060
                        dist = dist + light_error * 0.10 + dark_loss * 0.24 * bright_boost + chroma_error * 0.055 + hue_error * 0.010 + family_penalty
                    else:
                        family_penalty = neutral_loss * 0.32 + hue_excess * 0.080 + hue_extreme * 0.120
                        dist = dist + light_error * 0.22 + dark_loss * 0.55 * bright_boost + chroma_error * 0.115 + hue_error * 0.026 + family_penalty
                best_pos = cp.argmin(dist, axis=2)
                best_score = cp.take_along_axis(dist, best_pos[..., None], axis=2)[..., 0]
                chosen = candidate_gpu[best_pos]
                if custom_mode == "Custom colors first" and bool(cp.any(custom_gpu).item()):
                    large = cp.full_like(dist, cp.inf)
                    custom_dist = cp.where(custom_gpu[None, None, :], dist, large)
                    custom_pos = cp.argmin(custom_dist, axis=2)
                    custom_score = cp.take_along_axis(custom_dist, custom_pos[..., None], axis=2)[..., 0]
                    custom_chosen = candidate_gpu[custom_pos]
                    chosen = cp.where(custom_score <= best_score * 1.06 + threshold, custom_chosen, chosen)
                host_index = cp.asnumpy(chosen).astype(np.int16, copy=False)
                host_mask = cp.asnumpy(visible).astype(np.bool_, copy=False)
                out_index[start:end] = host_index[core0:core1]
                out_mask[start:end] = host_mask[core0:core1]
                del raw, alpha, rgb, visible, dist, best_pos, best_score, chosen
            try:
                cp.cuda.Stream.null.synchronize()
            except Exception:
                pass
            used, cached = _pool_stats(cp)
        info = replace(_refresh_info(info, cp), allocation_mode="CUDA palette tiled" if plan["mode"] == "tiled" else "CUDA palette full",
                       tile_rows=plan["tile_rows"], workspace_estimate_mb=plan["workspace_mb"],
                       pool_used_mb=used, pool_cached_mb=cached,
                       cuda_execution=f"CuPy sRGB/OKLab palette fidelity kernels ({color_fidelity})")
        return (out_index, out_mask), info
    except Exception as exc:
        _disable_backend(exc)
        return None, _fallback_info(mode, f"{name} failed during CUDA colour planning: {type(exc).__name__}: {exc}", performance)


def _upload_gray(cp, gray: Image.Image, performance: str):
    import numpy as np
    raw = np.frombuffer(gray.tobytes(), dtype=np.uint8).reshape(gray.height, gray.width)
    if performance != "Balanced":
        try:
            pinned = cp.cuda.alloc_pinned_memory(raw.nbytes)
            pinned_view = np.frombuffer(pinned, dtype=np.uint8, count=raw.size).reshape(raw.shape)
            pinned_view[...] = raw
            return cp.asarray(pinned_view, dtype=cp.float32, blocking=True)
        except InterruptedError:
            raise
        except Exception:
            pass
    return cp.asarray(raw, dtype=cp.float32, blocking=True)


def _enough_memory(info: AccelerationInfo, width: int, height: int, arrays: int = 12) -> bool:
    if not info.accelerated:
        return False
    required_mb = width * height * 4 * max(1, arrays) * 1.40 / _MIB
    return required_mb < available_vram_mb(info) * .82


def _disable_backend(exc: Exception) -> None:
    global _BACKEND_CACHE, _BACKEND_DEVICE_ID, _DISABLED_REASON
    if isinstance(exc, InterruptedError):
        raise exc
    # An oversized task or temporary allocation pressure says nothing about a
    # smaller later task's ability to use this otherwise working driver.
    if is_gpu_memory_error(exc):
        return
    with _GPU_LOCK:
        _DISABLED_REASON = f"GPU runtime fallback: {type(exc).__name__}: {exc}"
        _BACKEND_CACHE = None
        _BACKEND_DEVICE_ID = None


def _launch_shape(pixel_count: int, performance: str) -> tuple[tuple[int], tuple[int]]:
    validate_gpu_performance(performance)
    threads = 128 if performance == "Balanced" else 256
    blocks = max(1, (int(pixel_count) + threads - 1) // threads)
    return (blocks,), (threads,)


def _kernels(cp):
    key = str(getattr(cp, "__version__", "cupy"))
    cached = _KERNEL_CACHE.get(key)
    if cached is not None:
        return cached
    enhance_src = r'''
    extern "C" __global__
    void portrait_enhance(const float* src, const float* blur, float* out,
                          int w, int h, float strength, float gamma,
                          int subject_focus, float background_lift) {
        int i = blockDim.x * blockIdx.x + threadIdx.x;
        int n = w * h;
        if (i >= n) return;
        int x = i % w;
        int y = i / w;
        float v = src[i] + (src[i] - blur[i]) * strength;
        v = fminf(255.0f, fmaxf(0.0f, v));
        float norm = v / 255.0f;
        v = 255.0f * powf(norm, gamma);
        if (subject_focus && w >= 24 && h >= 24) {
            float cx = (w - 1) * 0.5f, cy = (h - 1) * 0.5f;
            float sx = fmaxf(1.0f, w * 0.62f), sy = fmaxf(1.0f, h * 0.72f);
            float dx = (x - cx) / sx, dy = (y - cy) / sy;
            float radial = sqrtf(dx * dx + dy * dy);
            float amount = fminf(1.0f, fmaxf(0.0f, (radial - 0.42f) / 0.62f));
            v = fminf(255.0f, v + background_lift * amount);
        }
        out[i] = v;
    }
    '''
    analysis_src = r'''
    __device__ __forceinline__ float sample_clamped(const float* a, int x, int y, int w, int h) {
        if (x < 0) x = 0; else if (x >= w) x = w - 1;
        if (y < 0) y = 0; else if (y >= h) y = h - 1;
        return a[y * w + x];
    }
    extern "C" __global__
    void saliency_sobel(const float* src, const float* blur,
                        float* saliency, float* gx_out, float* gy_out,
                        int w, int h, int subject_focus,
                        float structure_weight, float dark_weight, float centre_bias) {
        int i = blockDim.x * blockIdx.x + threadIdx.x;
        int n = w * h;
        if (i >= n) return;
        int x = i % w;
        int y = i / w;
        float c = src[i];
        float l = sample_clamped(src, x-1, y, w, h);
        float r = sample_clamped(src, x+1, y, w, h);
        float u = sample_clamped(src, x, y-1, w, h);
        float d = sample_clamped(src, x, y+1, w, h);
        float gradient = fminf(1.0f, (fabsf(r-l) + fabsf(d-u)) / 190.0f);
        float local = fminf(1.0f, fabsf(c - blur[i]) / 42.0f);
        float darkness = (255.0f - c) / 255.0f;
        float centre = 0.0f;
        if (subject_focus) {
            float cx = (w - 1) * 0.5f, cy = (h - 1) * 0.5f;
            float radius = fmaxf(1.0f, sqrtf(cx*cx + cy*cy));
            float dx = x - cx, dy = y - cy;
            centre = fmaxf(0.0f, 1.0f - sqrtf(dx*dx + dy*dy) / radius);
        }
        saliency[i] = 1.0f + structure_weight * (0.72f*gradient + 0.28f*local)
                    + dark_weight*darkness + centre_bias*centre;
        float p00=sample_clamped(src,x-1,y-1,w,h), p10=sample_clamped(src,x,y-1,w,h), p20=sample_clamped(src,x+1,y-1,w,h);
        float p01=sample_clamped(src,x-1,y,w,h),   p21=sample_clamped(src,x+1,y,w,h);
        float p02=sample_clamped(src,x-1,y+1,w,h), p12=sample_clamped(src,x,y+1,w,h), p22=sample_clamped(src,x+1,y+1,w,h);
        gx_out[i]=(p20+2.0f*p21+p22)-(p00+2.0f*p01+p02);
        gy_out[i]=(p02+2.0f*p12+p22)-(p00+2.0f*p10+p20);
    }
    '''
    enhance = cp.RawKernel(enhance_src, "portrait_enhance", options=("--use_fast_math",))
    analysis = cp.RawKernel(analysis_src, "saliency_sobel", options=("--use_fast_math",))
    _KERNEL_CACHE[key] = (enhance, analysis)
    return enhance, analysis


def _refresh_info(info: AccelerationInfo, cp) -> AccelerationInfo:
    try:
        free_b, total_b = cp.cuda.runtime.memGetInfo()
        used, cached = _pool_stats(cp)
        return replace(info, total_vram_mb=int(total_b//_MIB), free_vram_mb=int(free_b//_MIB),
                       pool_used_mb=used, pool_cached_mb=cached)
    except InterruptedError:
        raise
    except Exception:
        return info


@_cancellable
def enhance_portrait(gray: Image.Image, strength: float, gamma: float,
                     subject_focus: bool, background_lift: float,
                     mode: str = "Auto", vram_budget: str = "Auto",
                     performance: str = "Balanced", *, cancelled=lambda:False) -> tuple[Image.Image | None, AccelerationInfo, GpuAnalysisSession | None]:
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    if mode == "CPU":
        return None, _fallback_info(mode, performance=performance), None
    if gray.width * gray.height < MIN_GPU_PIXELS and performance == "Balanced":
        return None, _fallback_info(mode, "Image is small enough that CPU processing avoids GPU transfer overhead.", performance), None
    backend = _resolve_backend(mode)
    if backend is None:
        return None, _fallback_info(mode, performance=performance), None
    name, module, *_ = backend
    cp, cnd = module
    try:
        info = acceleration_info(mode, vram_budget, performance)
        if not info.accelerated:
            return None, info, None
        plan = plan_vram_allocation(info, gray.width, gray.height, arrays=8, overlap=8)
        with _GPU_LOCK:
            _relieve_pool_pressure(cp, int(info.vram_budget_mb or 256))
            enhance_kernel, _ = _kernels(cp)
            if plan["mode"] == "full":
                arr = _upload_gray(cp, gray, performance)
                blur = cnd.gaussian_filter(arr, sigma=1.35, mode="nearest")
                out = cp.empty_like(arr)
                grid, block = _launch_shape(arr.size, performance)
                enhance_kernel(grid, block, (arr, blur, out, np.int32(gray.width), np.int32(gray.height),
                                              np.float32(strength), np.float32(gamma), np.int32(bool(subject_focus)), np.float32(background_lift)))
                host_u8 = cp.asnumpy(cp.clip(cp.rint(out), 0, 255).astype(cp.uint8))
                info = replace(_refresh_info(info, cp), tile_rows=gray.height, workspace_estimate_mb=plan["workspace_mb"])
                session = GpuAnalysisSession(cp, cnd, out, info, gray.width, gray.height)
                return Image.fromarray(host_u8), info, session
            # Low-VRAM path: process row tiles with overlap for Gaussian kernels.
            # The complete source/output never needs to reside in VRAM at once.
            source=np.frombuffer(gray.tobytes(),dtype=np.uint8).reshape(gray.height,gray.width)
            host_u8=np.empty_like(source)
            for start,end,read0,read1,core0,core1 in _tile_ranges(gray.height,plan["tile_rows"],8):
                _cancel(cancelled)
                tile=Image.fromarray(source[read0:read1])
                arr=_upload_gray(cp,tile,performance)
                blur=cnd.gaussian_filter(arr,sigma=1.35,mode="nearest")
                out=cp.empty_like(arr)
                grid,block=_launch_shape(arr.size,performance)
                # Kernel uses tile-local geometry. Subject-focus weighting is
                # disabled per tile to avoid moving its visual centre; the CPU
                # post-pass can still apply focus if needed.
                enhance_kernel(grid,block,(arr,blur,out,np.int32(tile.width),np.int32(tile.height),np.float32(strength),np.float32(gamma),np.int32(0),np.float32(background_lift)))
                tile_host=cp.asnumpy(cp.clip(cp.rint(out),0,255).astype(cp.uint8))
                host_u8[start:end]=tile_host[core0:core1]
                del arr,blur,out
            if subject_focus and gray.width>=24 and gray.height>=24:
                yy,xx=np.mgrid[0:gray.height,0:gray.width]
                cx=(gray.width-1)*.5;cy=(gray.height-1)*.5
                sx=max(1.0,gray.width*.62);sy=max(1.0,gray.height*.72)
                radial=np.sqrt(((xx-cx)/sx)**2+((yy-cy)/sy)**2)
                amount=np.clip((radial-.42)/.62,0.0,1.0)
                host_u8=np.clip(host_u8.astype(np.float32)+float(background_lift)*amount,0,255).astype(np.uint8)
            info=replace(_refresh_info(info,cp),tile_rows=plan["tile_rows"],workspace_estimate_mb=plan["workspace_mb"],allocation_mode="Adaptive tiled")
            return Image.fromarray(host_u8),info,None
    except Exception as exc:
        _disable_backend(exc)
        return None, _fallback_info(mode, f"{name} failed during fused portrait enhancement: {type(exc).__name__}: {exc}", performance), None


def local_contrast(gray: Image.Image, strength: float, mode: str = "Auto",
                   vram_budget: str = "Auto", performance: str = "Balanced") -> tuple[Image.Image | None, AccelerationInfo]:
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    if strength <= 0:
        return None, _fallback_info(mode, "Local contrast is disabled.", performance)
    result, info, _ = enhance_portrait(gray, strength, 1.0, False, 0.0, mode, vram_budget, performance)
    return result, info


def _session_analysis(session: GpuAnalysisSession, subject_focus: bool, profile: dict, performance: str):
    cp, cnd, arr = session.cp, session.cnd, session.arr
    if session.saliency_map is not None and session.gx is not None and session.gy is not None:
        return
    blur = cnd.gaussian_filter(arr, sigma=1.2, mode="nearest")
    sal = cp.empty_like(arr); gx = cp.empty_like(arr); gy = cp.empty_like(arr)
    _, analysis_kernel = _kernels(cp)
    grid, block = _launch_shape(arr.size, performance)
    analysis_kernel(grid, block, (arr, blur, sal, gx, gy, np.int32(session.width), np.int32(session.height),
                                  np.int32(bool(subject_focus)), np.float32(profile["structure_weight"]),
                                  np.float32(profile["dark_weight"]), np.float32(profile["centre_bias"])))
    session.saliency_map, session.gx, session.gy = sal, gx, gy


@_cancellable
def saliency(gray: Image.Image, subject_focus: bool, profile: dict, mode: str = "Auto",
             vram_budget: str = "Auto", performance: str = "Balanced",
             session: GpuAnalysisSession | None = None, *, cancelled=lambda:False) -> tuple[Any | None, AccelerationInfo]:
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    if mode == "CPU":
        return None, _fallback_info(mode, performance=performance)
    if session is None and gray.width * gray.height < MIN_GPU_PIXELS and performance == "Balanced":
        return None, _fallback_info(mode, "Image is small enough that CPU saliency is faster.", performance)
    backend = _resolve_backend(mode)
    if backend is None:
        return None, _fallback_info(mode, performance=performance)
    name, module, *_ = backend
    cp, cnd = module
    try:
        info = acceleration_info(mode, vram_budget, performance)
        if not info.accelerated:
            return None, info
        plan=plan_vram_allocation(info,gray.width,gray.height,arrays=9,overlap=4)
        with _GPU_LOCK:
            _relieve_pool_pressure(cp,int(info.vram_budget_mb or 256))
            if plan["mode"]=="full":
                if session is None or session.width != gray.width or session.height != gray.height:
                    arr = _upload_gray(cp, gray, performance)
                    session = GpuAnalysisSession(cp, cnd, arr, info, gray.width, gray.height)
                _session_analysis(session, subject_focus, profile, performance)
                host = cp.asnumpy(session.saliency_map).astype("float32", copy=False).ravel()
                info = replace(_refresh_info(info, cp),tile_rows=gray.height,workspace_estimate_mb=plan["workspace_mb"])
                session.info = info
                return host, info
            import numpy as np
            source=np.frombuffer(gray.tobytes(),dtype=np.uint8).reshape(gray.height,gray.width)
            host=np.empty((gray.height,gray.width),dtype=np.float32)
            _,analysis_kernel=_kernels(cp)
            for start,end,read0,read1,core0,core1 in _tile_ranges(gray.height,plan["tile_rows"],4):
                _cancel(cancelled)
                tile=Image.fromarray(source[read0:read1]); arr=_upload_gray(cp,tile,performance)
                blur=cnd.gaussian_filter(arr,sigma=1.2,mode="nearest"); sal=cp.empty_like(arr);gx=cp.empty_like(arr);gy=cp.empty_like(arr)
                grid,block=_launch_shape(arr.size,performance)
                analysis_kernel(grid,block,(arr,blur,sal,gx,gy,np.int32(tile.width),np.int32(tile.height),np.int32(0),np.float32(profile["structure_weight"]),np.float32(profile["dark_weight"]),np.float32(0.0)))
                h=cp.asnumpy(sal).astype("float32",copy=False);host[start:end]=h[core0:core1]
                del arr,blur,sal,gx,gy
            if subject_focus and float(profile.get("centre_bias",0)):
                yy,xx=np.mgrid[0:gray.height,0:gray.width]
                cx=(gray.width-1)*.5;cy=(gray.height-1)*.5;radius=max(1.0,(cx*cx+cy*cy)**.5)
                centre=np.clip(1.0-np.sqrt((xx-cx)**2+(yy-cy)**2)/radius,0.0,1.0)
                host += float(profile.get("centre_bias",0))*centre.astype(np.float32)
            info=replace(_refresh_info(info,cp),tile_rows=plan["tile_rows"],workspace_estimate_mb=plan["workspace_mb"],allocation_mode="Adaptive tiled")
            return host.ravel(),info
    except Exception as exc:
        _disable_backend(exc)
        return None, _fallback_info(mode, f"{name} failed during fused saliency/Sobel analysis: {type(exc).__name__}: {exc}", performance)


@_cancellable
def sobel(gray: Image.Image, mode: str = "Auto", vram_budget: str = "Auto",
          performance: str = "Balanced", session: GpuAnalysisSession | None = None,
          subject_focus: bool = False, profile: dict | None = None, *,
          cancelled=lambda:False) -> tuple[tuple[Any, Any] | None, AccelerationInfo]:
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    if mode == "CPU":
        return None, _fallback_info(mode, performance=performance)
    backend = _resolve_backend(mode)
    if backend is None:
        return None, _fallback_info(mode, performance=performance)
    name, module, *_ = backend
    cp, cnd = module
    try:
        info = acceleration_info(mode, vram_budget, performance)
        if not info.accelerated:
            return None, info
        plan=plan_vram_allocation(info,gray.width,gray.height,arrays=7,overlap=2)
        with _GPU_LOCK:
            _relieve_pool_pressure(cp,int(info.vram_budget_mb or 256))
            if plan["mode"]=="tiled":
                import numpy as np
                source=np.frombuffer(gray.tobytes(),dtype=np.uint8).reshape(gray.height,gray.width)
                gx_host=np.empty((gray.height,gray.width),dtype=np.float32);gy_host=np.empty_like(gx_host)
                for start,end,read0,read1,core0,core1 in _tile_ranges(gray.height,plan["tile_rows"],2):
                    _cancel(cancelled)
                    tile=Image.fromarray(source[read0:read1]);arr=_upload_gray(cp,tile,performance)
                    gx=cnd.sobel(arr,axis=1,mode="nearest");gy=cnd.sobel(arr,axis=0,mode="nearest")
                    gx_host[start:end]=cp.asnumpy(gx).astype("float32",copy=False)[core0:core1]
                    gy_host[start:end]=cp.asnumpy(gy).astype("float32",copy=False)[core0:core1]
                    del arr,gx,gy
                info=replace(_refresh_info(info,cp),tile_rows=plan["tile_rows"],workspace_estimate_mb=plan["workspace_mb"],allocation_mode="Adaptive tiled")
                return (gx_host.ravel(),gy_host.ravel()),info
            if session is not None and session.width == gray.width and session.height == gray.height:
                if session.gx is None or session.gy is None:
                    profile = profile or {"structure_weight": .42, "dark_weight": .12, "centre_bias": .20}
                    _session_analysis(session, subject_focus, profile, performance)
                gx_host = cp.asnumpy(session.gx).astype("float32", copy=False).ravel()
                gy_host = cp.asnumpy(session.gy).astype("float32", copy=False).ravel()
            else:
                arr = _upload_gray(cp, gray, performance)
                gx = cnd.sobel(arr, axis=1, mode="nearest")
                gy = cnd.sobel(arr, axis=0, mode="nearest")
                gx_host = cp.asnumpy(gx).astype("float32", copy=False).ravel()
                gy_host = cp.asnumpy(gy).astype("float32", copy=False).ravel()
            info = _refresh_info(info, cp)
        return (gx_host, gy_host), info
    except Exception as exc:
        _disable_backend(exc)
        return None, _fallback_info(mode, f"{name} failed during edge analysis: {type(exc).__name__}: {exc}", performance)


def release_analysis_session(session: GpuAnalysisSession | None, trim_cache: bool = True) -> None:
    """Drop live GPU analysis arrays and optionally trim cached VRAM blocks."""
    if session is None:return
    cp=session.cp
    with _GPU_LOCK:
        session.arr=None;session.saliency_map=None;session.gx=None;session.gy=None
        try:cp.cuda.Stream.null.synchronize()
        except Exception:pass
        if trim_cache:
            try:
                used,cached=_pool_stats(cp)
                budget=int(session.info.vram_budget_mb or 0)
                if cached-used>64 or (budget and cached>budget*.45):
                    cp.get_default_memory_pool().free_all_blocks()
                    try:cp.get_default_pinned_memory_pool().free_all_blocks()
                    except Exception:pass
            except Exception:pass


def _benchmark_image(size: int, *, cancelled=lambda: False) -> Image.Image:
    """Generate the deterministic stimulus in bounded vectorized row chunks."""
    pixels = np.empty((size, size), dtype=np.uint8)
    x = np.arange(size, dtype=np.uint32)[None, :]
    for start in range(0, size, 64):
        _cancel(cancelled)
        y = np.arange(start, min(size, start + 64), dtype=np.uint32)[:, None]
        pixels[start:start + 64] = (x * 17 + y * 31 + (x ^ y)) % 256
    _cancel(cancelled)
    return Image.fromarray(pixels)


@_cancellable
def benchmark(mode: str = "Auto", size: int = 1024, vram_budget: str = "Auto",
              performance: str = "High throughput", *, cancelled=lambda: False) -> dict:
    validate_acceleration_mode(mode); validate_vram_budget(vram_budget); validate_gpu_performance(performance)
    if mode != "CPU":
        reset_backend_cache()
    size = max(256, min(4096, int(size)))
    started = time.perf_counter()
    info = acceleration_info(mode, vram_budget, performance)
    _cancel(cancelled)
    if not info.accelerated:
        return {**info.as_dict(), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "size": size, "used_gpu": False, "throughput_mp_s": 0.0,
                "fused_kernels": False}
    image = _benchmark_image(size, cancelled=cancelled)
    profile = {"structure_weight": .92, "dark_weight": .25, "centre_bias": .40}
    start = time.perf_counter()
    enhanced = session = None
    used_gpu = False
    try:
        enhanced, info, session = enhance_portrait(image, .42, .97, True, 54,
                                                   mode, vram_budget, performance,
                                                   cancelled=cancelled)
        if enhanced is not None and info.accelerated:
            sal, info2 = saliency(enhanced, True, profile, mode, vram_budget,
                                  performance, session, cancelled=cancelled)
            edges, info3 = sobel(enhanced, mode, vram_budget, performance, session,
                                 True, profile, cancelled=cancelled)
            info = info3 if info3.accelerated else info2
            # Each analysis function already downloads its full output before
            # returning. No successful score is inferred from a no-op fallback.
            used_gpu = bool(sal is not None and edges is not None
                            and info2.accelerated and info3.accelerated)
        _cancel(cancelled)
        elapsed = (time.perf_counter() - start) * 1000.0
    finally:
        release_analysis_session(session, trim_cache=False)
        if enhanced is not None and enhanced is not image:
            enhanced.close()
        image.close()
    megapixels = (size * size) / 1_000_000.0
    throughput = megapixels / max(elapsed / 1000.0, 1e-9) if used_gpu else 0.0
    return {**info.as_dict(), "elapsed_ms": round(elapsed, 2), "size": size,
            "used_gpu": bool(used_gpu), "throughput_mp_s": round(throughput, 2),
            "fused_kernels": bool(used_gpu)}
