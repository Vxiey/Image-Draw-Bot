"""Step 23 — vendor-neutral real-workload acceleration for Image Draw Bot.

This module consumes the Step 22 per-machine benchmark profile and routes real
numeric work to the fastest measured backend *per workload*.  NVIDIA CUDA/CuPy,
AMD/Intel/NVIDIA OpenCL and deterministic NumPy are peers behind one API.

Safety/compatibility rules:
- CPU/NumPy is always available and is the authoritative fallback.
- A backend failure is quarantined only for that backend + workload for the
  current process.  One bad OpenCL kernel never disables unrelated work.
- Small jobs stay on CPU when the Step 22 crossover says transfers cost more.
- User images are never persisted by this module; arrays exist only in memory.
- No mouse, screen capture, network or telemetry is used here.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from contextlib import contextmanager
from functools import wraps
import math
import threading
from typing import Any, Callable, Sequence

import numpy as np

from GpuResourceCache import used_cuda_device

# Step 23 logical workloads reuse the closest Step 22 microbenchmark where the
# exact operation was not benchmarked independently.  This preserves the user's
# measured crossover/backend choice without inventing a synthetic score.
WORKLOAD_PROFILE_ALIAS = {
    "oklab": "oklab",
    "palette_match": "palette_match",
    "delta_e": "oklab",
    "quantization": "palette_match",
    "edge_map": "edge_map",
    "pixel_math": "bulk_matrix",
}

_LOCK = threading.RLock()
_HEALTH_LOCK = threading.RLock()
_FAILED: dict[tuple[str, str], str] = {}
_OPENCL_CACHE: dict[str, tuple[Any, Any, Any, Any]] = {}
_OPENCL_IN_USE: dict[int, int] = {}


class HardwareProfileObservation:
    """One lazily validated profile for a synchronous scoring operation.

    This owns no global cache and freezes no backend-health decision. Its
    operation owner must close it, including when a traceback is retained.
    Failed reads retain only their reason, never an exception or traceback.
    """
    __slots__ = ('_loaded', '_profile', '_unavailable', '_closed')

    def __init__(self):
        self._loaded = False
        self._profile = None
        self._unavailable = ''
        self._closed = False

    def _resolve(self):
        if self._closed:
            raise RuntimeError('Hardware profile observation is closed.')
        if not self._loaded:
            self._loaded = True
            try:
                from UniversalHardwareBenchmark import load_hardware_profile
                self._profile = load_hardware_profile() or {}
            except Exception as error:
                self._profile = {}
                self._unavailable = f'hardware profile unavailable: {type(error).__name__}: {error}'
        return self._profile, self._unavailable

    def close(self):
        self._profile = None
        self._unavailable = ''
        self._closed = True


ProfileInput = dict[str, Any] | HardwareProfileObservation | None


@dataclass(frozen=True)
class RouteInfo:
    workload: str
    profile_workload: str
    backend_id: str
    backend: str
    vendor: str
    device: str
    accelerated: bool
    pixels: int
    reason: str = ""
    fallback_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cancel(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise InterruptedError()


def _check_completed(function):
    """Withhold cancelled results without retaining their private array owners."""
    @wraps(function)
    def checked(*args, **kwargs):
        result = None
        try:
            result = function(*args, **kwargs)
            cancelled = kwargs.get('cancelled')
            if cancelled is not None:
                _cancel(cancelled)
            return result
        except BaseException as error:
            # A retained worker exception keeps its traceback alive. Clear only
            # our references; borrowed source arrays and contexts stay usable.
            result = args = kwargs = cancelled = None
            _release_failed_frames(error)
            raise
    return checked


def _release_failed_frames(error):
    """Release failed scopes, preserving exception identity and stack locations."""
    import traceback
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        traceback.clear_frames(current.__traceback__)
        pending.extend((current.__cause__, current.__context__))


def _run_accelerated(route, operation, cpu_fallback, cancelled):
    """Finish the native attempt's ownership before allocating CPU fallback."""
    try:
        return operation()
    except InterruptedError:
        raise
    except Exception as error:
        _release_failed_frames(error)
        fallback = _mark_failed(route, error)
    # Leave the native exception scope before CPU work. Stop must not start a
    # second heavy attempt merely because the first one failed concurrently.
    _cancel(cancelled)
    return cpu_fallback(fallback)


def _cpu_route(workload: str, pixels: int, reason: str = "CPU/NumPy fallback") -> RouteInfo:
    try:
        from UniversalHardwareBenchmark import cpu_name
        device = cpu_name()
    except Exception:
        device = "CPU"
    return RouteInfo(workload, WORKLOAD_PROFILE_ALIAS.get(workload, workload), "cpu:numpy",
                     "CPU/NumPy", "CPU", device, False, int(pixels), reason=reason)


def select_route(workload: str, *, pixels: int, gpu_mode: str = "Auto",
                 profile: ProfileInput = None) -> RouteInfo:
    """Resolve the measured backend for one real workload.

    ``Auto`` obeys Step 22. ``CPU`` is an unconditional fallback. The legacy
    ``NVIDIA CUDA`` setting still force-prefers a usable CUDA device so existing
    user profiles retain their meaning.
    """
    logical = str(workload or "pixel_math")
    mapped = WORKLOAD_PROFILE_ALIAS.get(logical, logical)
    px = max(0, int(pixels or 0))
    mode = str(gpu_mode or "Auto")
    if mode == "CPU":
        return _cpu_route(logical, px, "CPU mode selected")

    try:
        from UniversalHardwareBenchmark import load_hardware_profile, preferred_backend
        if isinstance(profile, HardwareProfileObservation):
            prof, unavailable = profile._resolve()
            if unavailable:
                return _cpu_route(logical, px, unavailable)
        else:
            prof = profile if isinstance(profile, dict) else (load_hardware_profile() or {})
        pref = dict(preferred_backend(mapped, pixels=px, profile=prof) or {})
    except Exception as exc:
        return _cpu_route(logical, px, f"hardware profile unavailable: {type(exc).__name__}: {exc}")

    # Legacy forced CUDA mode: select the best measured CUDA score for this
    # workload even if Auto preferred OpenCL/CPU. If none is measured, the
    # existing CPU safety path wins rather than guessing a CUDA device.
    if mode == "NVIDIA CUDA":
        candidates = []
        rows = prof.get("scores_large", ())
        rows = rows if isinstance(rows, (list, tuple)) else ()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("workload")) != mapped or not str(row.get("backend_id", "")).startswith("cuda:"):
                continue
            if row.get("error"):
                continue
            try:
                rate = float(row.get("throughput_mp_s", 0.0))
                elapsed = float(row.get("elapsed_ms", 1.0))
                if not math.isfinite(rate) or rate <= 0 or not math.isfinite(elapsed) or elapsed <= 0:
                    continue
                _cuda_device_id(str(row['backend_id']))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            candidates.append((rate, row))
        if candidates:
            best = max(candidates, key=lambda item: item[0])[1]
            pref = {
                "backend_id": str(best.get("backend_id")), "backend": "CUDA/CuPy",
                "vendor": "NVIDIA", "device": str(best.get("device") or "NVIDIA CUDA GPU"),
                "reason": "NVIDIA CUDA explicitly requested",
            }
        else:
            return _cpu_route(logical, px, "NVIDIA CUDA requested but no verified CUDA benchmark is available")

    backend_id = str(pref.get("backend_id") or "cpu:numpy")
    if backend_id == "cpu:numpy":
        return _cpu_route(logical, px, str(pref.get("reason") or "CPU is fastest for this workload"))
    try:
        if backend_id.startswith('cuda:'):
            _cuda_device_id(backend_id)
        else:
            _opencl_device_ids(backend_id)
    except ValueError:
        return _cpu_route(logical, px, f'invalid measured backend id: {backend_id}')
    with _HEALTH_LOCK:
        failed = _FAILED.get((backend_id, logical)) or _FAILED.get((backend_id, mapped))
    if failed:
        return _cpu_route(logical, px, f"{backend_id} quarantined for {logical}: {failed}")
    return RouteInfo(
        logical, mapped, backend_id, str(pref.get("backend") or backend_id),
        str(pref.get("vendor") or "GPU"), str(pref.get("device") or "GPU"), True, px,
        reason=str(pref.get("reason") or "Step 22 measured preference"),
    )


def _mark_failed(route: RouteInfo, error: BaseException) -> RouteInfo:
    message = f"{type(error).__name__}: {error}"
    transient_memory=False
    try:
        from GpuAcceleration import is_gpu_memory_error
        transient_memory=is_gpu_memory_error(error)
    except Exception:
        transient_memory=isinstance(error,MemoryError) or 'out of memory' in str(error).lower()
    if route.backend_id != "cpu:numpy" and not transient_memory:
        with _HEALTH_LOCK:
            _FAILED[(route.backend_id, route.workload)] = message
    reason=(f"{route.backend_id} hit transient memory pressure and fell back for this call: {message}" if transient_memory else
            f"{route.backend_id} failed safely: {message}")
    return _cpu_route(route.workload, route.pixels, reason)


def reset_runtime_backend_health() -> None:
    with _HEALTH_LOCK:
        _FAILED.clear()
    with _LOCK:
        _OPENCL_CACHE.clear()


def backend_health_snapshot() -> dict[str, str]:
    with _HEALTH_LOCK:
        return {f"{backend}|{workload}": reason for (backend, workload), reason in _FAILED.items()}


def _rgb01(array: np.ndarray) -> np.ndarray:
    raw = np.asarray(array)
    a = np.asarray(raw, dtype=np.float32)
    if not np.all(np.isfinite(a)):
        raise ValueError('RGB channels must be finite')
    maximum = float(np.max(a)) if a.size else 0.0
    if np.issubdtype(raw.dtype, np.integer) or maximum > 1.5:
        a = a / 255.0
        maximum /= 255.0
    # These internal consumers only read normalized input. Borrow valid float
    # buffers instead of copying both full preview frames at every nested call.
    if not a.size or (maximum <= 1.0 and float(np.min(a)) >= 0.0):
        return a
    return np.clip(a, 0.0, 1.0).astype(np.float32, copy=False)


def _oklab_cpu(rgb: np.ndarray) -> np.ndarray:
    c = _rgb01(rgb)
    flat = c.reshape(-1, 3)
    result = np.empty(c.shape, dtype=np.float32)
    output = result.reshape(-1, 3)
    # Keep transfer/routing decisions for the complete workload, but bound the
    # CPU transform's linear-light and LMS scratch buffers. Arithmetic order is
    # identical to the dense formula, including each float32 intermediate.
    for start in range(0, len(flat), 65536):
        tile = flat[start:start+65536]
        linear = np.where(tile <= 0.04045, tile / 12.92, np.power((tile + 0.055) / 1.055, 2.4))
        r, g, b = linear[:, 0], linear[:, 1], linear[:, 2]
        l = np.cbrt(0.4122214708*r + 0.5363325363*g + 0.0514459929*b)
        m = np.cbrt(0.2119034982*r + 0.6806995451*g + 0.1073969566*b)
        s = np.cbrt(0.0883024619*r + 0.2817188376*g + 0.6299787005*b)
        out = output[start:start+65536]
        out[:, 0] = 0.2104542553*l + 0.7936177850*m - 0.0040720468*s
        out[:, 1] = 1.9779984951*l - 2.4285922050*m + 0.4505937099*s
        out[:, 2] = 0.0259040371*l + 0.7827717662*m - 0.8086757660*s
    return result


_OPENCL_SOURCE = r"""
inline float ds_linear(float c) {
    return c <= 0.04045f ? c / 12.92f : pow((c + 0.055f) / 1.055f, 2.4f);
}
inline float4 ds_oklab(float3 c) {
    float r=ds_linear(clamp(c.x,0.0f,1.0f));
    float g=ds_linear(clamp(c.y,0.0f,1.0f));
    float b=ds_linear(clamp(c.z,0.0f,1.0f));
    float l=cbrt(0.4122214708f*r + 0.5363325363f*g + 0.0514459929f*b);
    float m=cbrt(0.2119034982f*r + 0.6806995451f*g + 0.1073969566f*b);
    float s=cbrt(0.0883024619f*r + 0.2817188376f*g + 0.6299787005f*b);
    return (float4)(0.2104542553f*l + 0.7936177850f*m - 0.0040720468f*s,
                    1.9779984951f*l - 2.4285922050f*m + 0.4505937099f*s,
                    0.0259040371f*l + 0.7827717662f*m - 0.8086757660f*s, 1.0f);
}
inline float ds_hue(float a, float b) {
    float h=atan2(b,a)*57.29577951308232f; return h<0.0f?h+360.0f:h;
}
__kernel void ds_oklab_kernel(__global const float4 *src, __global float4 *dst, const int n) {
    int i=get_global_id(0); if(i>=n)return; dst[i]=ds_oklab(src[i].xyz);
}
__kernel void ds_delta_kernel(__global const float4 *a, __global const float4 *b,
                              __global float *out, const int n) {
    int i=get_global_id(0); if(i>=n)return; float3 d=a[i].xyz-b[i].xyz;
    out[i]=sqrt(dot(d,d));
}
__kernel void ds_pairwise_lab(__global const float4 *lab, __global float *out, const int n) {
    int i=get_global_id(0); int total=n*n; if(i>=total)return; int a=i/n; int b=i-a*n;
    float3 d=lab[a].xyz-lab[b].xyz; out[i]=sqrt(dot(d,d))*100.0f;
}
__kernel void ds_edge_kernel(__global const float *src, __global float *dst, const int w, const int h) {
    int i=get_global_id(0); int n=w*h; if(i>=n)return; int x=i%w; int y=i/w;
    int xl=max(0,x-1),xr=min(w-1,x+1),yu=max(0,y-1),yd=min(h-1,y+1);
    float gx=(w>1)?(src[y*w+xr]-src[y*w+xl])/(float)(xr-xl):0.0f;
    float gy=(h>1)?(src[yd*w+x]-src[yu*w+x])/(float)(yd-yu):0.0f;
    dst[i]=sqrt(gx*gx+gy*gy);
}
__kernel void ds_absdiff_kernel(__global const float4 *a, __global const float4 *b,
                                __global float *out, const int n) {
    int i=get_global_id(0); if(i>=n)return; float3 d=fabs(a[i].xyz-b[i].xyz);
    out[i]=(d.x+d.y+d.z)/3.0f;
}
__kernel void ds_palette_kernel(
    __global const float4 *rgba, __global const float4 *pal_rgb,
    __global const float4 *pal_lab, __global const short *candidate_ids,
    __global const uchar *custom_flags, __global short *out_idx,
    __global uchar *out_visible, const int n, const int count,
    const int perceptual, const int fidelity, const int custom_first, const int skip_white)
{
    int i=get_global_id(0); if(i>=n)return; float4 raw=rgba[i];
    float alpha=clamp(raw.w,0.0f,255.0f);
    float3 rgb=(alpha>=254.999f)?raw.xyz:(raw.xyz*alpha + (float3)(255.0f)*(255.0f-alpha))/255.0f;
    uchar visible=(uchar)(alpha>0.0f && (!skip_white || fmin(rgb.x,fmin(rgb.y,rgb.z))<245.0f));
    out_visible[i]=visible;
    float4 src_lab=ds_oklab(clamp(rgb/255.0f,0.0f,1.0f));
    float srcL=src_lab.x*100.0f;
    float srcC=hypot(src_lab.y,src_lab.z)*100.0f;
    float srcH=ds_hue(src_lab.y,src_lab.z);
    float best=3.4e38f, best_custom=3.4e38f; short best_id=0,best_custom_id=0;
    for(int p=0;p<count;p++){
        float dist;
        if(perceptual){
            float3 d=src_lab.xyz-pal_lab[p].xyz; dist=sqrt(dot(d,d))*100.0f;
        } else {
            float3 d=rgb-pal_rgb[p].xyz; dist=sqrt(dot(d,d)/3.0f)/255.0f*100.0f;
        }
        if(perceptual && fidelity>0){
            float palL=pal_lab[p].x*100.0f;
            float palC=hypot(pal_lab[p].y,pal_lab[p].z)*100.0f;
            float palH=ds_hue(pal_lab[p].y,pal_lab[p].z);
            float light=fabs(srcL-palL), dark=fmax(srcL-palL,0.0f), chroma=fabs(srcC-palC);
            float hd=fabs(srcH-palH); float hue=fmin(hd,360.0f-hd);
            if(fmin(srcC,palC)<2.5f)hue=0.0f;
            float bright=1.0f+fmax(srcL-52.0f,0.0f)/80.0f;
            float neutral_cut=fmax(2.5f,srcC*0.28f);
            float neutral=(srcC>=5.0f && palC<neutral_cut)?srcC-palC:0.0f;
            float hex=(srcC>=5.0f)?fmax(hue-45.0f,0.0f):0.0f;
            float hext=(srcC>=5.0f)?fmax(hue-85.0f,0.0f):0.0f;
            if(fidelity==1){
                float family=neutral*0.18f+hex*0.035f+hext*0.060f;
                dist+=light*0.10f+dark*0.24f*bright+chroma*0.055f+hue*0.010f+family;
            } else {
                float family=neutral*0.32f+hex*0.080f+hext*0.120f;
                dist+=light*0.22f+dark*0.55f*bright+chroma*0.115f+hue*0.026f+family;
            }
        }
        if(dist<best){best=dist;best_id=candidate_ids[p];}
        if(custom_flags[p] && dist<best_custom){best_custom=dist;best_custom_id=candidate_ids[p];}
    }
    if(custom_first && best_custom<3.0e38f && best_custom<=best*1.06f+0.0006f)best_id=best_custom_id;
    out_idx[i]=best_id;
}
"""


def _opencl_context(backend_id: str):
    with _LOCK:
        if backend_id in _OPENCL_CACHE:
            return _OPENCL_CACHE[backend_id]
        pidx, didx = _opencl_device_ids(backend_id)
        import pyopencl as cl
        platforms = list(cl.get_platforms())
        platform = platforms[pidx]
        devices = list(platform.get_devices(device_type=cl.device_type.GPU))
        device = devices[didx]
        ctx = cl.Context(devices=[device])
        queue = cl.CommandQueue(ctx)
        program = cl.Program(ctx, _OPENCL_SOURCE).build(options=[])
        value = (cl, ctx, queue, program)
        _OPENCL_CACHE[backend_id] = value
        return value


@contextmanager
def _opencl_session(backend_id: str):
    """Keep a cached context borrowed until this operation releases its work."""
    with _LOCK:
        value = _opencl_context(backend_id)
        identity = id(value)
        _OPENCL_IN_USE[identity] = _OPENCL_IN_USE.get(identity, 0) + 1
    try:
        yield value
    finally:
        with _LOCK:
            remaining = _OPENCL_IN_USE[identity] - 1
            if remaining:
                _OPENCL_IN_USE[identity] = remaining
            else:
                _OPENCL_IN_USE.pop(identity)


def clear_idle_opencl_cache(*, cancelled=lambda: False):
    """Drop only this module's idle cache references; never release native objects."""
    _cancel(cancelled)
    # A native context build holds this lock. Cache maintenance need not wait
    # for it, and must not interrupt or release the operation that owns it.
    if not _LOCK.acquire(blocking=False):
        return {'opencl_entries': 0, 'opencl_busy': 1}
    removed = []
    busy = 0
    value = None
    try:
        for key in list(_OPENCL_CACHE):
            _cancel(cancelled)
            value = _OPENCL_CACHE[key]
            if _OPENCL_IN_USE.get(id(value), 0):
                busy += 1
            else:
                removed.append(_OPENCL_CACHE.pop(key))
    finally:
        _LOCK.release()
        count = len(removed)
        # Destructors run outside our cache lock, including after Stop. Any
        # independent owner keeps its context/queue/program alive normally.
        removed.clear()
        value = None
    _cancel(cancelled)
    return {'opencl_entries': count, 'opencl_busy': busy}


def _backend_indices(backend_id: str, kind: str, count: int) -> tuple[int, ...]:
    parts = str(backend_id).split(':')
    if len(parts) != count + 1 or parts[0] != kind or any(
        not part.isascii() or not part.isdecimal() for part in parts[1:]
    ):
        raise ValueError(f'invalid {kind} backend id: {backend_id}')
    return tuple(map(int, parts[1:]))


def _cuda_device_id(backend_id: str) -> int:
    return _backend_indices(backend_id, 'cuda', 1)[0]


def _opencl_device_ids(backend_id: str) -> tuple[int, int]:
    return _backend_indices(backend_id, 'opencl', 2)


def _float4_host(rgb: np.ndarray, *, alpha: np.ndarray | None = None, scale255: bool = False) -> np.ndarray:
    a = np.asarray(rgb, dtype=np.float32).reshape(-1, 3)
    if not scale255:
        a = _rgb01(a)
    out = np.ones((a.shape[0], 4), dtype=np.float32)
    out[:, :3] = a
    if alpha is not None:
        out[:, 3] = np.asarray(alpha, dtype=np.float32).reshape(-1)
    elif scale255:
        out[:, 3] = 255.0
    return out


@_check_completed
def oklab_array(rgb: np.ndarray, *, gpu_mode: str = "Auto", profile: ProfileInput = None,
                cancelled: Callable[[], bool] = lambda: False) -> tuple[np.ndarray, dict[str, Any]]:
    _cancel(cancelled)
    arr = np.asarray(rgb)
    if arr.ndim < 2 or arr.shape[-1] != 3:
        raise ValueError("OKLab input must end in RGB channels")
    arr = _rgb01(arr)
    shape = arr.shape
    pixels = int(np.prod(shape[:-1]))
    route = select_route("oklab", pixels=pixels, gpu_mode=gpu_mode, profile=profile)
    if not route.accelerated:
        return _oklab_cpu(arr), route.as_dict()
    def accelerated():
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with used_cuda_device(cp, _cuda_device_id(route.backend_id)):
                c = cp.asarray(_rgb01(arr), dtype=cp.float32)
                linear = cp.where(c <= 0.04045, c/12.92, cp.power((c+0.055)/1.055, 2.4))
                r,g,b=linear[...,0],linear[...,1],linear[...,2]
                l=cp.cbrt(0.4122214708*r+0.5363325363*g+0.0514459929*b)
                m=cp.cbrt(0.2119034982*r+0.6806995451*g+0.1073969566*b)
                s=cp.cbrt(0.0883024619*r+0.2817188376*g+0.6299787005*b)
                out=cp.stack((0.2104542553*l+0.7936177850*m-0.0040720468*s,
                              1.9779984951*l-2.4285922050*m+0.4505937099*s,
                              0.0259040371*l+0.7827717662*m-0.8086757660*s),axis=-1)
                cp.cuda.Stream.null.synchronize(); host=cp.asnumpy(out).astype(np.float32,copy=False)
            return host, route.as_dict()
        if route.backend_id.startswith("opencl:"):
            with _opencl_session(route.backend_id) as (cl, ctx, queue, program):
                mf=cl.mem_flags
                host4=_float4_host(arr)
                src=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=host4)
                dst=cl.Buffer(ctx,mf.WRITE_ONLY,host4.nbytes)
                program.ds_oklab_kernel(queue,(pixels,),None,src,dst,np.int32(pixels))
                sink=np.empty_like(host4);cl.enqueue_copy(queue,sink,dst);queue.finish()
                return sink[:,:3].reshape(shape).astype(np.float32,copy=False),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    return _run_accelerated(route, accelerated,
        lambda fallback: (_oklab_cpu(arr), fallback.as_dict()), cancelled)


@_check_completed
def perceptual_pair(src_rgb: np.ndarray, dst_rgb: np.ndarray, *, gpu_mode: str = "Auto",
                    profile: ProfileInput = None,
                    cancelled: Callable[[], bool] = lambda: False) -> tuple[np.ndarray,np.ndarray,np.ndarray,dict[str,Any]]:
    """Convert two RGB arrays to OKLab and calculate real per-pixel ΔE.

    The conversion + ΔE remain on the selected GPU until final host results are
    copied back, avoiding three independent transfers in accuracy diagnostics.
    """
    _cancel(cancelled)
    src=_rgb01(src_rgb);dst=_rgb01(dst_rgb)
    if src.shape!=dst.shape or src.ndim < 1 or src.shape[-1]!=3:
        raise ValueError("perceptual_pair requires matching RGB arrays")
    pixels=int(np.prod(src.shape[:-1])); route=select_route("delta_e",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    def cpu(fallback):
        sl=_oklab_cpu(src);dl=_oklab_cpu(dst);de=np.linalg.norm(sl-dl,axis=-1).astype(np.float32,copy=False)
        return sl,dl,de,fallback.as_dict()
    if not route.accelerated:
        return cpu(route)
    def accelerated():
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with used_cuda_device(cp, _cuda_device_id(route.backend_id)):
                a=cp.asarray(_rgb01(src),dtype=cp.float32);b=cp.asarray(_rgb01(dst),dtype=cp.float32)
                def lab(c):
                    lin=cp.where(c<=0.04045,c/12.92,cp.power((c+0.055)/1.055,2.4));r,g,bb=lin[...,0],lin[...,1],lin[...,2]
                    l=cp.cbrt(0.4122214708*r+0.5363325363*g+0.0514459929*bb);m=cp.cbrt(0.2119034982*r+0.6806995451*g+0.1073969566*bb);s=cp.cbrt(0.0883024619*r+0.2817188376*g+0.6299787005*bb)
                    return cp.stack((0.2104542553*l+0.7936177850*m-0.0040720468*s,1.9779984951*l-2.4285922050*m+0.4505937099*s,0.0259040371*l+0.7827717662*m-0.8086757660*s),axis=-1)
                sl=lab(a);dl=lab(b);de=cp.sqrt(cp.sum((sl-dl)*(sl-dl),axis=-1,dtype=cp.float32))
                cp.cuda.Stream.null.synchronize(); hs=cp.asnumpy(sl).astype(np.float32,copy=False);hd=cp.asnumpy(dl).astype(np.float32,copy=False);he=cp.asnumpy(de).astype(np.float32,copy=False)
            return hs,hd,he,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            with _opencl_session(route.backend_id) as (cl, ctx, queue, program):
                mf=cl.mem_flags
                a4=_float4_host(src);b4=_float4_host(dst)
                ba=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=a4);bb=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=b4)
                la=cl.Buffer(ctx,mf.READ_WRITE,a4.nbytes);lb=cl.Buffer(ctx,mf.READ_WRITE,b4.nbytes);bd=cl.Buffer(ctx,mf.WRITE_ONLY,pixels*4)
                program.ds_oklab_kernel(queue,(pixels,),None,ba,la,np.int32(pixels));program.ds_oklab_kernel(queue,(pixels,),None,bb,lb,np.int32(pixels));program.ds_delta_kernel(queue,(pixels,),None,la,lb,bd,np.int32(pixels))
                sa=np.empty_like(a4);sb=np.empty_like(b4);de=np.empty((pixels,),dtype=np.float32)
                cl.enqueue_copy(queue,sa,la);cl.enqueue_copy(queue,sb,lb);cl.enqueue_copy(queue,de,bd);queue.finish()
                target=src.shape
                return sa[:,:3].reshape(target),sb[:,:3].reshape(target),de.reshape(target[:-1]),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    return _run_accelerated(route, accelerated, cpu, cancelled)


@_check_completed
def edge_magnitude(luminance: np.ndarray, *, gpu_mode: str = "Auto", profile: ProfileInput = None,
                   cancelled: Callable[[], bool] = lambda: False) -> tuple[np.ndarray,dict[str,Any]]:
    _cancel(cancelled)
    lum=np.asarray(luminance,dtype=np.float32)
    if lum.ndim!=2: raise ValueError("edge_magnitude requires a 2D luminance array")
    if not np.all(np.isfinite(lum)): raise ValueError("luminance must be finite")
    from ImageGradients import luminance_edges
    h,w=lum.shape;pixels=int(h*w);route=select_route("edge_map",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    def cpu():
        return luminance_edges(lum)
    if not pixels:return cpu(),_cpu_route("edge_map",0,"Empty luminance grid").as_dict()
    if not route.accelerated:return cpu(),route.as_dict()
    def accelerated():
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with used_cuda_device(cp, _cuda_device_id(route.backend_id)):
                x=cp.asarray(lum,dtype=cp.float32);out=luminance_edges(x,xp=cp);cp.cuda.Stream.null.synchronize();host=cp.asnumpy(out).astype(np.float32,copy=False)
            return host,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            with _opencl_session(route.backend_id) as (cl, ctx, queue, program):
                mf=cl.mem_flags
                flat=np.ascontiguousarray(lum.reshape(-1),dtype=np.float32);src=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=flat);dst=cl.Buffer(ctx,mf.WRITE_ONLY,flat.nbytes);program.ds_edge_kernel(queue,(pixels,),None,src,dst,np.int32(w),np.int32(h));sink=np.empty_like(flat);cl.enqueue_copy(queue,sink,dst);queue.finish();return sink.reshape(h,w),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    return _run_accelerated(route, accelerated,
        lambda fallback: (cpu(), fallback.as_dict()), cancelled)


@_check_completed
def pixel_channel_error(src_rgb: np.ndarray, dst_rgb: np.ndarray, *, gpu_mode: str = "Auto",
                        profile: ProfileInput = None,
                        cancelled: Callable[[],bool]=lambda:False) -> tuple[np.ndarray,dict[str,Any]]:
    _cancel(cancelled)
    a=_rgb01(src_rgb);b=_rgb01(dst_rgb)
    if a.shape!=b.shape or a.ndim < 1 or a.shape[-1]!=3:raise ValueError("pixel_channel_error requires matching RGB arrays")
    pixels=int(np.prod(a.shape[:-1]));route=select_route("pixel_math",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    if not route.accelerated:return np.mean(np.abs(a-b),axis=-1,dtype=np.float32),route.as_dict()
    def accelerated():
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with used_cuda_device(cp, _cuda_device_id(route.backend_id)):
                aa=cp.asarray(a);bb=cp.asarray(b);out=cp.mean(cp.abs(aa-bb),axis=-1,dtype=cp.float32);cp.cuda.Stream.null.synchronize();host=cp.asnumpy(out).astype(np.float32,copy=False)
            return host,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            with _opencl_session(route.backend_id) as (cl, ctx, queue, program):
                mf=cl.mem_flags;a4=_float4_host(a);b4=_float4_host(b);ba=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=a4);bb=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=b4);bo=cl.Buffer(ctx,mf.WRITE_ONLY,pixels*4);program.ds_absdiff_kernel(queue,(pixels,),None,ba,bb,bo,np.int32(pixels));sink=np.empty((pixels,),dtype=np.float32);cl.enqueue_copy(queue,sink,bo);queue.finish();return sink.reshape(a.shape[:-1]),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    return _run_accelerated(route, accelerated,
        lambda fallback: (np.mean(np.abs(a-b),axis=-1,dtype=np.float32), fallback.as_dict()), cancelled)


def _palette_features(lab):
    return (lab[...,0]*100.0,
            np.hypot(lab[...,1],lab[...,2])*100.0,
            np.mod(np.degrees(np.arctan2(lab[...,2],lab[...,1])),360.0))


def _squared_color_distances(source, palette):
    """Accumulate three channels without a pixel-by-palette-by-RGB cube."""
    delta=source[...,0,None]-palette[...,0]
    distance=delta*delta
    for channel in (1,2):
        delta=source[...,channel,None]-palette[...,channel]
        distance+=delta*delta
    return distance


def _palette_cost_cpu(rgb: np.ndarray, palette: np.ndarray, *, perceptual: bool, fidelity: str,
                      src_lab=None, pal_lab=None, src_features=None, pal_features=None) -> np.ndarray:
    src=np.asarray(rgb,dtype=np.float32);pal=np.asarray(palette,dtype=np.float32)
    if not perceptual:
        return np.sqrt(_squared_color_distances(src,pal)/3.0,dtype=np.float32)/255.0*100.0
    src_lab=_oklab_cpu(src / 255.0) if src_lab is None else src_lab
    pal_lab=_oklab_cpu(pal / 255.0) if pal_lab is None else pal_lab
    dist=np.sqrt(_squared_color_distances(src_lab,pal_lab),dtype=np.float32)*100.0
    if fidelity in ("Balanced","Faithful"):
        srcL,srcC,srcH=_palette_features(src_lab) if src_features is None else src_features
        palL,palC,palH=_palette_features(pal_lab) if pal_features is None else pal_features
        light=np.abs(srcL[...,None]-palL);dark=np.maximum(srcL[...,None]-palL,0.0)
        chroma=np.abs(srcC[...,None]-palC);hd=np.abs(srcH[...,None]-palH);hue=np.minimum(hd,360.0-hd);hue=np.where(np.minimum(srcC[...,None],palC)<2.5,0.0,hue)
        bright=1.0+np.maximum(srcL-52.0,0.0)[...,None]/80.0
        vivid=srcC[...,None]>=5.0
        neutral_cut=np.maximum(2.5,srcC[...,None]*.28)
        neutral=np.where(vivid&(palC<neutral_cut),srcC[...,None]-palC,0.0)
        hex=np.where(vivid,np.maximum(hue-45.0,0.0),0.0)
        hext=np.where(vivid,np.maximum(hue-85.0,0.0),0.0)
        if fidelity=="Balanced":dist+=light*.10+dark*.24*bright+chroma*.055+hue*.010+neutral*.18+hex*.035+hext*.060
        else:dist+=light*.22+dark*.55*bright+chroma*.115+hue*.026+neutral*.32+hex*.080+hext*.120
    return dist.astype(np.float32,copy=False)


def _rgba_visible_rgb(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Composite once into one owned RGB buffer, retaining the exact cost input."""
    alpha = raw[..., 3]
    rgb = raw[..., :3].astype(np.float32)
    visible = alpha > 0
    if not np.all(alpha == 255):
        opacity = alpha.astype(np.float32)
        rgb *= opacity[..., None]
        rgb += (255.0 * (255.0 - opacity))[..., None]
        rgb /= 255.0
    return rgb, visible


@_check_completed
def palette_indices_rgba(image, palette: Sequence[Sequence[int]], candidate_indices: Sequence[int], custom_flags: Sequence[bool], *,
                         color_rendering: str="Perceptual match", custom_mode: str="Calibrated palette",
                         color_fidelity: str="Balanced", skip_white: bool=True, gpu_mode: str="Auto",
                         profile: ProfileInput = None, cancelled: Callable[[],bool]=lambda:False) -> tuple[tuple[np.ndarray,np.ndarray],dict[str,Any]]:
    """Map real RGBA image pixels to palette indexes through the measured backend.

    Unlike the legacy CUDA helper this function always returns a result: when GPU
    is not profitable/usable it runs the same deterministic NumPy cost model.
    """
    from PIL import Image
    _cancel(cancelled)
    from PixelMapValidation import validate_palette_count, validate_color_index
    count = validate_palette_count(len(palette))
    rgba=image.convert("RGBA") if isinstance(image,Image.Image) else Image.fromarray(np.asarray(image,dtype=np.uint8),"RGBA")
    try:
        raw=np.asarray(rgba,dtype=np.uint8)
    finally:
        rgba.close()
    h,w=raw.shape[:2];pixels=h*w
    candidates=list(dict.fromkeys(validate_color_index(i,palette_count=count) for i in candidate_indices)) or list(range(count))
    pal=np.asarray([tuple(map(int,palette[i][:3])) for i in candidates],dtype=np.float32)
    ids=np.asarray(candidates,dtype=np.int16);custom=np.asarray([bool(custom_flags[i]) if i<len(custom_flags) else False for i in candidates],dtype=np.uint8)
    rgb,visible=_rgba_visible_rgb(raw)
    if skip_white:visible&=np.min(rgb,axis=2)<245.0
    route=select_route("palette_match",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    perceptual=color_rendering!="RGB nearest"; fidelity=2 if color_fidelity=="Faithful" else (1 if color_fidelity=="Balanced" else 0); custom_first=custom_mode=="Custom colors first" and bool(np.any(custom))
    def cpu():
        # Bound both dimensions: even a one-row panorama or a large custom
        # palette must never allocate a full pixel x palette distance cube.
        flat = rgb.reshape(-1, 3)
        out = np.empty(pixels, dtype=np.int16)
        palette_lab = _oklab_cpu(pal / 255.0) if perceptual else None
        palette_features = _palette_features(palette_lab) if perceptual and color_fidelity in ('Balanced','Faithful') else None
        for start in range(0, pixels, 4096):
            _cancel(cancelled)
            end = min(pixels, start + 4096)
            source_lab = _oklab_cpu(flat[start:end] / 255.0) if perceptual else None
            source_features = _palette_features(source_lab) if palette_features is not None else None
            best = np.full(end-start, np.inf, dtype=np.float32)
            custom_best = np.full_like(best, np.inf)
            chosen = np.full(end-start, ids[0], dtype=np.int16)
            custom_chosen = chosen.copy()
            for p0 in range(0, len(ids), 32):
                _cancel(cancelled)
                p1 = min(len(ids), p0+32)
                dist = _palette_cost_cpu(flat[start:end], pal[p0:p1],
                                         perceptual=perceptual, fidelity=color_fidelity,
                                         src_lab=source_lab,
                                         pal_lab=None if palette_lab is None else palette_lab[p0:p1],
                                         src_features=source_features,
                                         pal_features=None if palette_features is None else tuple(a[p0:p1] for a in palette_features))
                pos = np.argmin(dist, axis=1)
                score = dist[np.arange(end-start), pos]
                better = score < best
                chosen[better] = ids[p0+pos[better]]
                best = np.minimum(best, score)
                if custom_first:
                    dist[:, ~custom[p0:p1].astype(bool)] = np.inf
                    pos = np.argmin(dist, axis=1)
                    score = dist[np.arange(end-start), pos]
                    better = score < custom_best
                    custom_chosen[better] = ids[p0+pos[better]]
                    custom_best = np.minimum(custom_best, score)
            if custom_first:
                chosen = np.where(custom_best <= best*1.06+0.0006, custom_chosen, chosen)
            out[start:end] = chosen
        return out.reshape(h,w), visible.astype(np.bool_,copy=False)
    if not route.accelerated:
        result=cpu();return result,route.as_dict()
    def accelerated():
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with used_cuda_device(cp, _cuda_device_id(route.backend_id)):
                from CudaPalette import match
                out = match(
                    cp, rgb, pal, _oklab_cpu(pal / 255.0), ids, custom,
                    perceptual=perceptual, fidelity=fidelity,
                    custom_first=custom_first, cancelled=cancelled)
            return (out,visible.astype(np.bool_,copy=False)),route.as_dict()
        if route.backend_id.startswith("opencl:"):
            with _opencl_session(route.backend_id) as (cl, ctx, queue, program):
                mf=cl.mem_flags
                # Reuse bounded buffers on AMD/Intel/NVIDIA OpenCL as well.
                chunk = min(262144, max(1, 8_000_000 // len(candidates)))
                pal4=np.ones((len(candidates),4),dtype=np.float32);pal4[:,:3]=pal
                pl4=np.ones_like(pal4);pl4[:,:3]=_oklab_cpu(pal / 255.0)
                bp=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=pal4)
                bl=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=pl4)
                bi=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=ids)
                bc=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=custom)
                br=cl.Buffer(ctx,mf.READ_ONLY,chunk*16)
                bo=cl.Buffer(ctx,mf.WRITE_ONLY,chunk*2)
                bm=cl.Buffer(ctx,mf.WRITE_ONLY,chunk)
                oi=np.empty(pixels,dtype=np.int16);om=np.empty(pixels,dtype=np.uint8)
                flat=raw.reshape(-1,4)
                for start in range(0,pixels,chunk):
                    _cancel(cancelled)
                    end=min(pixels,start+chunk);n=end-start
                    tile=np.ascontiguousarray(flat[start:end],dtype=np.float32)
                    cl.enqueue_copy(queue,br,tile,is_blocking=True)
                    program.ds_palette_kernel(queue,(n,),None,br,bp,bl,bi,bc,bo,bm,
                        np.int32(n),np.int32(len(candidates)),np.int32(perceptual),
                        np.int32(fidelity),np.int32(custom_first),np.int32(skip_white))
                    cl.enqueue_copy(queue,oi[start:end],bo,is_blocking=True)
                    cl.enqueue_copy(queue,om[start:end],bm,is_blocking=True)
                return (oi.reshape(h,w),om.reshape(h,w).astype(np.bool_)),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    return _run_accelerated(route, accelerated,
        lambda fallback: (cpu(), fallback.as_dict()), cancelled)


def _pairwise_lab_distance(lab, *, xp=np, cancelled=lambda: False):
    """Keep scratch space bounded independently of the required N×N output."""
    count = len(lab)
    output = np.empty((count, count), dtype=np.float32)
    rows = max(1, min(256, 1_048_576 // max(1, count)))
    for start in range(0, count, rows):
        _cancel(cancelled)
        end = min(count, start + rows)
        distance = _squared_color_distances(lab[start:end], lab)
        distance = xp.sqrt(distance) * 100.0
        output[start:end] = distance if xp is np else xp.asnumpy(distance)
    _cancel(cancelled)
    return output


@_check_completed
def pairwise_oklab_distance(colors: Sequence[Sequence[int]], *, gpu_mode: str="Auto", profile: ProfileInput = None,
                            cancelled: Callable[[],bool]=lambda:False) -> tuple[np.ndarray,dict[str,Any]]:
    """Deterministic quantization distance matrix routed by Step 22.

    Typical <=64-colour reducer work correctly stays on CPU because it is below
    the measured GPU crossover. The routing is still real: unusually large
    quantization candidate sets can use the measured GPU backend.
    """
    # This API receives palette RGB bytes, including palettes whose largest
    # channel is only 1. Normalize by that contract rather than inferring the
    # scale from the darkest/brightest color currently present.
    _cancel(cancelled)
    if not len(colors):
        return np.empty((0,0),dtype=np.float32), _cpu_route('quantization',0,'Empty palette').as_dict()
    arr=np.asarray([tuple(map(int,c[:3])) for c in colors],dtype=np.float32)/255.0
    n=len(arr);pixels=n*n;route=select_route("quantization",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    _cancel(cancelled)
    # Avoid making tiny matrices slower by forcing a GPU; select_route normally
    # already returns CPU below the measured crossover.
    if not route.accelerated:
        return _pairwise_lab_distance(_oklab_cpu(arr),cancelled=cancelled),route.as_dict()
    def accelerated():
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with used_cuda_device(cp, _cuda_device_id(route.backend_id)):
                c=cp.asarray(_rgb01(arr),dtype=cp.float32);lin=cp.where(c<=0.04045,c/12.92,cp.power((c+0.055)/1.055,2.4));r,g,b=lin[:,0],lin[:,1],lin[:,2];l=cp.cbrt(.4122214708*r+.5363325363*g+.0514459929*b);m=cp.cbrt(.2119034982*r+.6806995451*g+.1073969566*b);ss=cp.cbrt(.0883024619*r+.2817188376*g+.6299787005*b);lab=cp.stack((.2104542553*l+.7936177850*m-.0040720468*ss,1.9779984951*l-2.4285922050*m+.4505937099*ss,.0259040371*l+.7827717662*m-.8086757660*ss),axis=1)
                host=_pairwise_lab_distance(lab,xp=cp,cancelled=cancelled)
            return host,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            with _opencl_session(route.backend_id) as (cl, ctx, queue, program):
                mf=cl.mem_flags;host4=_float4_host(arr);src=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=host4);lab=cl.Buffer(ctx,mf.READ_WRITE,host4.nbytes);outb=cl.Buffer(ctx,mf.WRITE_ONLY,n*n*4);program.ds_oklab_kernel(queue,(n,),None,src,lab,np.int32(n));program.ds_pairwise_lab(queue,(n*n,),None,lab,outb,np.int32(n));sink=np.empty((n*n,),dtype=np.float32);cl.enqueue_copy(queue,sink,outb);queue.finish();return sink.reshape(n,n),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    return _run_accelerated(route, accelerated,
        lambda fallback: (_pairwise_lab_distance(_oklab_cpu(arr),cancelled=cancelled), fallback.as_dict()), cancelled)
