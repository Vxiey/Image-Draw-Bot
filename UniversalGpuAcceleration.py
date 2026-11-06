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
import math
import threading
from typing import Any, Callable, Sequence

import numpy as np

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
_FAILED: dict[tuple[str, str], str] = {}
_OPENCL_CACHE: dict[str, tuple[Any, Any, Any, Any]] = {}


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


def _cpu_route(workload: str, pixels: int, reason: str = "CPU/NumPy fallback") -> RouteInfo:
    try:
        from UniversalHardwareBenchmark import cpu_name
        device = cpu_name()
    except Exception:
        device = "CPU"
    return RouteInfo(workload, WORKLOAD_PROFILE_ALIAS.get(workload, workload), "cpu:numpy",
                     "CPU/NumPy", "CPU", device, False, int(pixels), reason=reason)


def select_route(workload: str, *, pixels: int, gpu_mode: str = "Auto",
                 profile: dict[str, Any] | None = None) -> RouteInfo:
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
        prof = profile if isinstance(profile, dict) else (load_hardware_profile() or {})
        pref = dict(preferred_backend(mapped, pixels=px, profile=prof) or {})
    except Exception as exc:
        return _cpu_route(logical, px, f"hardware profile unavailable: {type(exc).__name__}: {exc}")

    # Legacy forced CUDA mode: select the best measured CUDA score for this
    # workload even if Auto preferred OpenCL/CPU. If none is measured, the
    # existing CPU safety path wins rather than guessing a CUDA device.
    if mode == "NVIDIA CUDA":
        candidates = []
        for row in prof.get("scores_large", ()) if isinstance(prof, dict) else ():
            if not isinstance(row, dict):
                continue
            if str(row.get("workload")) != mapped or not str(row.get("backend_id", "")).startswith("cuda:"):
                continue
            if row.get("error"):
                continue
            candidates.append(row)
        if candidates:
            best = max(candidates, key=lambda r: float(r.get("throughput_mp_s", 0.0) or 0.0))
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
        _FAILED[(route.backend_id, route.workload)] = message
    reason=(f"{route.backend_id} hit transient memory pressure and fell back for this call: {message}" if transient_memory else
            f"{route.backend_id} failed safely: {message}")
    return _cpu_route(route.workload, route.pixels, reason)


def reset_runtime_backend_health() -> None:
    with _LOCK:
        _FAILED.clear()
        _OPENCL_CACHE.clear()


def backend_health_snapshot() -> dict[str, str]:
    return {f"{backend}|{workload}": reason for (backend, workload), reason in _FAILED.items()}


def _rgb01(array: np.ndarray) -> np.ndarray:
    a = np.asarray(array, dtype=np.float32)
    if a.size and float(np.nanmax(a)) > 1.5:
        a = a / 255.0
    return np.clip(a, 0.0, 1.0).astype(np.float32, copy=False)


def _oklab_cpu(rgb: np.ndarray) -> np.ndarray:
    c = _rgb01(rgb)
    linear = np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))
    r, g, b = linear[..., 0], linear[..., 1], linear[..., 2]
    l = np.cbrt(0.4122214708*r + 0.5363325363*g + 0.0514459929*b)
    m = np.cbrt(0.2119034982*r + 0.6806995451*g + 0.1073969566*b)
    s = np.cbrt(0.0883024619*r + 0.2817188376*g + 0.6299787005*b)
    return np.stack((
        0.2104542553*l + 0.7936177850*m - 0.0040720468*s,
        1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
        0.0259040371*l + 0.7827717662*m - 0.8086757660*s,
    ), axis=-1).astype(np.float32, copy=False)


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
    float gx=(x>0 && x<w-1)?fabs(src[y*w+xr]-src[y*w+xl])*0.5f:0.0f;
    float gy=(y>0 && y<h-1)?fabs(src[yd*w+x]-src[yu*w+x])*0.5f:0.0f;
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
            float hex=fmax(hue-45.0f,0.0f), hext=fmax(hue-85.0f,0.0f);
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
        import pyopencl as cl
        parts = backend_id.split(":")
        if len(parts) != 3 or parts[0] != "opencl":
            raise ValueError(f"invalid OpenCL backend id: {backend_id}")
        pidx, didx = int(parts[1]), int(parts[2])
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


def _cuda_device_id(backend_id: str) -> int:
    parts = str(backend_id).split(":", 1)
    return int(parts[1]) if len(parts) == 2 else 0


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


def oklab_array(rgb: np.ndarray, *, gpu_mode: str = "Auto", profile: dict[str, Any] | None = None,
                cancelled: Callable[[], bool] = lambda: False) -> tuple[np.ndarray, dict[str, Any]]:
    _cancel(cancelled)
    arr = np.asarray(rgb, dtype=np.float32)
    if arr.ndim < 2 or arr.shape[-1] != 3:
        raise ValueError("OKLab input must end in RGB channels")
    shape = arr.shape
    pixels = int(np.prod(shape[:-1]))
    route = select_route("oklab", pixels=pixels, gpu_mode=gpu_mode, profile=profile)
    if not route.accelerated:
        return _oklab_cpu(arr), route.as_dict()
    try:
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with cp.cuda.Device(_cuda_device_id(route.backend_id)):
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
            cl,ctx,queue,program=_opencl_context(route.backend_id); mf=cl.mem_flags
            host4=_float4_host(arr)
            src=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=host4)
            dst=cl.Buffer(ctx,mf.WRITE_ONLY,host4.nbytes)
            program.ds_oklab_kernel(queue,(pixels,),None,src,dst,np.int32(pixels))
            sink=np.empty_like(host4);cl.enqueue_copy(queue,sink,dst);queue.finish()
            return sink[:,:3].reshape(shape).astype(np.float32,copy=False),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    except InterruptedError:
        raise
    except Exception as exc:
        fallback=_mark_failed(route,exc)
        return _oklab_cpu(arr),fallback.as_dict()


def perceptual_pair(src_rgb: np.ndarray, dst_rgb: np.ndarray, *, gpu_mode: str = "Auto",
                    profile: dict[str, Any] | None = None,
                    cancelled: Callable[[], bool] = lambda: False) -> tuple[np.ndarray,np.ndarray,np.ndarray,dict[str,Any]]:
    """Convert two RGB arrays to OKLab and calculate real per-pixel ΔE.

    The conversion + ΔE remain on the selected GPU until final host results are
    copied back, avoiding three independent transfers in accuracy diagnostics.
    """
    _cancel(cancelled)
    src=np.asarray(src_rgb,dtype=np.float32);dst=np.asarray(dst_rgb,dtype=np.float32)
    if src.shape!=dst.shape or src.shape[-1]!=3:
        raise ValueError("perceptual_pair requires matching RGB arrays")
    pixels=int(np.prod(src.shape[:-1])); route=select_route("delta_e",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    if not route.accelerated:
        sl=_oklab_cpu(src);dl=_oklab_cpu(dst);de=np.linalg.norm(sl-dl,axis=-1).astype(np.float32,copy=False)
        return sl,dl,de,route.as_dict()
    try:
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with cp.cuda.Device(_cuda_device_id(route.backend_id)):
                a=cp.asarray(_rgb01(src),dtype=cp.float32);b=cp.asarray(_rgb01(dst),dtype=cp.float32)
                def lab(c):
                    lin=cp.where(c<=0.04045,c/12.92,cp.power((c+0.055)/1.055,2.4));r,g,bb=lin[...,0],lin[...,1],lin[...,2]
                    l=cp.cbrt(0.4122214708*r+0.5363325363*g+0.0514459929*bb);m=cp.cbrt(0.2119034982*r+0.6806995451*g+0.1073969566*bb);s=cp.cbrt(0.0883024619*r+0.2817188376*g+0.6299787005*bb)
                    return cp.stack((0.2104542553*l+0.7936177850*m-0.0040720468*s,1.9779984951*l-2.4285922050*m+0.4505937099*s,0.0259040371*l+0.7827717662*m-0.8086757660*s),axis=-1)
                sl=lab(a);dl=lab(b);de=cp.sqrt(cp.sum((sl-dl)*(sl-dl),axis=-1,dtype=cp.float32))
                cp.cuda.Stream.null.synchronize(); hs=cp.asnumpy(sl).astype(np.float32,copy=False);hd=cp.asnumpy(dl).astype(np.float32,copy=False);he=cp.asnumpy(de).astype(np.float32,copy=False)
            return hs,hd,he,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            cl,ctx,queue,program=_opencl_context(route.backend_id);mf=cl.mem_flags
            a4=_float4_host(src);b4=_float4_host(dst)
            ba=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=a4);bb=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=b4)
            la=cl.Buffer(ctx,mf.READ_WRITE,a4.nbytes);lb=cl.Buffer(ctx,mf.READ_WRITE,b4.nbytes);bd=cl.Buffer(ctx,mf.WRITE_ONLY,pixels*4)
            program.ds_oklab_kernel(queue,(pixels,),None,ba,la,np.int32(pixels));program.ds_oklab_kernel(queue,(pixels,),None,bb,lb,np.int32(pixels));program.ds_delta_kernel(queue,(pixels,),None,la,lb,bd,np.int32(pixels))
            sa=np.empty_like(a4);sb=np.empty_like(b4);de=np.empty((pixels,),dtype=np.float32)
            cl.enqueue_copy(queue,sa,la);cl.enqueue_copy(queue,sb,lb);cl.enqueue_copy(queue,de,bd);queue.finish()
            target=src.shape
            return sa[:,:3].reshape(target),sb[:,:3].reshape(target),de.reshape(target[:-1]),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    except Exception as exc:
        fallback=_mark_failed(route,exc);sl=_oklab_cpu(src);dl=_oklab_cpu(dst);de=np.linalg.norm(sl-dl,axis=-1).astype(np.float32,copy=False)
        return sl,dl,de,fallback.as_dict()


def edge_magnitude(luminance: np.ndarray, *, gpu_mode: str = "Auto", profile: dict[str, Any] | None = None,
                   cancelled: Callable[[], bool] = lambda: False) -> tuple[np.ndarray,dict[str,Any]]:
    _cancel(cancelled)
    lum=np.asarray(luminance,dtype=np.float32)
    if lum.ndim!=2: raise ValueError("edge_magnitude requires a 2D luminance array")
    h,w=lum.shape;pixels=int(h*w);route=select_route("edge_map",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    def cpu():
        gx=np.zeros_like(lum);gy=np.zeros_like(lum);gx[:,1:-1]=np.abs(lum[:,2:]-lum[:,:-2])*.5;gy[1:-1,:]=np.abs(lum[2:,:]-lum[:-2,:])*.5
        return np.sqrt(gx*gx+gy*gy,dtype=np.float32)
    if not route.accelerated:return cpu(),route.as_dict()
    try:
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with cp.cuda.Device(_cuda_device_id(route.backend_id)):
                x=cp.asarray(lum,dtype=cp.float32);gx=cp.zeros_like(x);gy=cp.zeros_like(x);gx[:,1:-1]=cp.abs(x[:,2:]-x[:,:-2])*.5;gy[1:-1,:]=cp.abs(x[2:,:]-x[:-2,:])*.5;out=cp.sqrt(gx*gx+gy*gy);cp.cuda.Stream.null.synchronize();host=cp.asnumpy(out).astype(np.float32,copy=False)
            return host,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            cl,ctx,queue,program=_opencl_context(route.backend_id);mf=cl.mem_flags
            flat=np.ascontiguousarray(lum.reshape(-1),dtype=np.float32);src=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=flat);dst=cl.Buffer(ctx,mf.WRITE_ONLY,flat.nbytes);program.ds_edge_kernel(queue,(pixels,),None,src,dst,np.int32(w),np.int32(h));sink=np.empty_like(flat);cl.enqueue_copy(queue,sink,dst);queue.finish();return sink.reshape(h,w),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    except Exception as exc:
        fallback=_mark_failed(route,exc);return cpu(),fallback.as_dict()


def pixel_channel_error(src_rgb: np.ndarray, dst_rgb: np.ndarray, *, gpu_mode: str = "Auto",
                        profile: dict[str,Any] | None=None,
                        cancelled: Callable[[],bool]=lambda:False) -> tuple[np.ndarray,dict[str,Any]]:
    _cancel(cancelled)
    a=_rgb01(src_rgb);b=_rgb01(dst_rgb)
    if a.shape!=b.shape or a.shape[-1]!=3:raise ValueError("pixel_channel_error requires matching RGB arrays")
    pixels=int(np.prod(a.shape[:-1]));route=select_route("pixel_math",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    if not route.accelerated:return np.mean(np.abs(a-b),axis=-1,dtype=np.float32),route.as_dict()
    try:
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with cp.cuda.Device(_cuda_device_id(route.backend_id)):
                aa=cp.asarray(a);bb=cp.asarray(b);out=cp.mean(cp.abs(aa-bb),axis=-1,dtype=cp.float32);cp.cuda.Stream.null.synchronize();host=cp.asnumpy(out).astype(np.float32,copy=False)
            return host,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            cl,ctx,queue,program=_opencl_context(route.backend_id);mf=cl.mem_flags;a4=_float4_host(a);b4=_float4_host(b);ba=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=a4);bb=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=b4);bo=cl.Buffer(ctx,mf.WRITE_ONLY,pixels*4);program.ds_absdiff_kernel(queue,(pixels,),None,ba,bb,bo,np.int32(pixels));sink=np.empty((pixels,),dtype=np.float32);cl.enqueue_copy(queue,sink,bo);queue.finish();return sink.reshape(a.shape[:-1]),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    except Exception as exc:
        fallback=_mark_failed(route,exc);return np.mean(np.abs(a-b),axis=-1,dtype=np.float32),fallback.as_dict()


def _palette_cost_cpu(rgb: np.ndarray, palette: np.ndarray, *, perceptual: bool, fidelity: str) -> np.ndarray:
    src=np.asarray(rgb,dtype=np.float32);pal=np.asarray(palette,dtype=np.float32)
    if not perceptual:
        diff=src[...,None,:]-pal;return np.sqrt(np.sum(diff*diff,axis=-1,dtype=np.float32)/3.0,dtype=np.float32)/255.0*100.0
    src_lab=_oklab_cpu(src / 255.0);pal_lab=_oklab_cpu(pal / 255.0)
    diff=src_lab[...,None,:]-pal_lab;dist=np.sqrt(np.sum(diff*diff,axis=-1,dtype=np.float32),dtype=np.float32)*100.0
    if fidelity in ("Balanced","Faithful"):
        srcL=src_lab[...,0]*100.0;palL=pal_lab[...,0]*100.0;light=np.abs(srcL[...,None]-palL);dark=np.maximum(srcL[...,None]-palL,0.0)
        srcC=np.hypot(src_lab[...,1],src_lab[...,2])*100.0;palC=np.hypot(pal_lab[...,1],pal_lab[...,2])*100.0
        srcH=np.mod(np.degrees(np.arctan2(src_lab[...,2],src_lab[...,1])),360.0);palH=np.mod(np.degrees(np.arctan2(pal_lab[...,2],pal_lab[...,1])),360.0)
        chroma=np.abs(srcC[...,None]-palC);hd=np.abs(srcH[...,None]-palH);hue=np.minimum(hd,360.0-hd);hue=np.where(np.minimum(srcC[...,None],palC)<2.5,0.0,hue)
        bright=1.0+np.maximum(srcL-52.0,0.0)[...,None]/80.0;neutral_cut=np.maximum(2.5,srcC[...,None]*.28);neutral=np.where((srcC[...,None]>=5.0)&(palC<neutral_cut),srcC[...,None]-palC,0.0);hex=np.maximum(hue-45.0,0.0);hext=np.maximum(hue-85.0,0.0)
        if fidelity=="Balanced":dist+=light*.10+dark*.24*bright+chroma*.055+hue*.010+neutral*.18+hex*.035+hext*.060
        else:dist+=light*.22+dark*.55*bright+chroma*.115+hue*.026+neutral*.32+hex*.080+hext*.120
    return dist.astype(np.float32,copy=False)


def palette_indices_rgba(image, palette: Sequence[Sequence[int]], candidate_indices: Sequence[int], custom_flags: Sequence[bool], *,
                         color_rendering: str="Perceptual match", custom_mode: str="Calibrated palette",
                         color_fidelity: str="Balanced", skip_white: bool=True, gpu_mode: str="Auto",
                         profile: dict[str,Any] | None=None, cancelled: Callable[[],bool]=lambda:False) -> tuple[tuple[np.ndarray,np.ndarray],dict[str,Any]]:
    """Map real RGBA image pixels to palette indexes through the measured backend.

    Unlike the legacy CUDA helper this function always returns a result: when GPU
    is not profitable/usable it runs the same deterministic NumPy cost model.
    """
    from PIL import Image
    _cancel(cancelled)
    if not len(palette):
        raise ValueError("palette must contain at least one color")
    if len(palette) > 32768:
        raise ValueError("palette exceeds the int16 index range")
    rgba=image.convert("RGBA") if isinstance(image,Image.Image) else Image.fromarray(np.asarray(image,dtype=np.uint8),"RGBA")
    raw=np.asarray(rgba,dtype=np.uint8);h,w=raw.shape[:2];pixels=h*w
    candidates=[int(i) for i in candidate_indices if 0<=int(i)<len(palette)] or list(range(len(palette)))
    pal=np.asarray([tuple(map(int,palette[i][:3])) for i in candidates],dtype=np.float32)
    ids=np.asarray(candidates,dtype=np.int16);custom=np.asarray([bool(custom_flags[i]) if i<len(custom_flags) else False for i in candidates],dtype=np.uint8)
    alpha=raw[...,3].astype(np.float32);rgb=np.where(alpha[...,None]>=255.0,raw[...,:3].astype(np.float32),(raw[...,:3].astype(np.float32)*alpha[...,None]+255.0*(255.0-alpha[...,None]))/255.0)
    visible=alpha>0.0
    if skip_white:visible&=np.min(rgb,axis=2)<245.0
    route=select_route("palette_match",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    perceptual=color_rendering!="RGB nearest"; fidelity=2 if color_fidelity=="Faithful" else (1 if color_fidelity=="Balanced" else 0); custom_first=custom_mode=="Custom colors first" and bool(np.any(custom))
    def cpu():
        # Bound both dimensions: even a one-row panorama or a large custom
        # palette must never allocate a full pixel x palette distance cube.
        flat = rgb.reshape(-1, 3)
        out = np.empty(pixels, dtype=np.int16)
        for start in range(0, pixels, 4096):
            _cancel(cancelled)
            end = min(pixels, start + 4096)
            best = np.full(end-start, np.inf, dtype=np.float32)
            custom_best = np.full_like(best, np.inf)
            chosen = np.full(end-start, ids[0], dtype=np.int16)
            custom_chosen = chosen.copy()
            for p0 in range(0, len(ids), 32):
                _cancel(cancelled)
                p1 = min(len(ids), p0+32)
                dist = _palette_cost_cpu(flat[start:end], pal[p0:p1],
                                         perceptual=perceptual, fidelity=color_fidelity)
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
    try:
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with cp.cuda.Device(_cuda_device_id(route.backend_id)):
                from CudaPalette import match
                out = match(
                    cp, rgb, pal, _oklab_cpu(pal / 255.0), ids, custom,
                    perceptual=perceptual, fidelity=fidelity,
                    custom_first=custom_first, cancelled=cancelled)
            return (out,visible.astype(np.bool_,copy=False)),route.as_dict()
        if route.backend_id.startswith("opencl:"):
            cl,ctx,queue,program=_opencl_context(route.backend_id);mf=cl.mem_flags
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
    except InterruptedError:raise
    except Exception as exc:
        fallback=_mark_failed(route,exc);result=cpu();return result,fallback.as_dict()


def pairwise_oklab_distance(colors: Sequence[Sequence[int]], *, gpu_mode: str="Auto", profile: dict[str,Any] | None=None,
                            cancelled: Callable[[],bool]=lambda:False) -> tuple[np.ndarray,dict[str,Any]]:
    """Deterministic quantization distance matrix routed by Step 22.

    Typical <=64-colour reducer work correctly stays on CPU because it is below
    the measured GPU crossover. The routing is still real: unusually large
    quantization candidate sets can use the measured GPU backend.
    """
    # This API receives palette RGB bytes, including palettes whose largest
    # channel is only 1. Normalize by that contract rather than inferring the
    # scale from the darkest/brightest color currently present.
    arr=np.asarray([tuple(map(int,c[:3])) for c in colors],dtype=np.float32)/255.0
    n=len(arr);pixels=n*n;route=select_route("quantization",pixels=pixels,gpu_mode=gpu_mode,profile=profile)
    _cancel(cancelled)
    # Avoid making tiny matrices slower by forcing a GPU; select_route normally
    # already returns CPU below the measured crossover.
    if not route.accelerated:
        lab=_oklab_cpu(arr);d=lab[:,None,:]-lab[None,:,:];return (np.sqrt(np.sum(d*d,axis=2,dtype=np.float32))*100.0).astype(np.float32,copy=False),route.as_dict()
    try:
        if route.backend_id.startswith("cuda:"):
            import cupy as cp
            with cp.cuda.Device(_cuda_device_id(route.backend_id)):
                c=cp.asarray(_rgb01(arr),dtype=cp.float32);lin=cp.where(c<=0.04045,c/12.92,cp.power((c+0.055)/1.055,2.4));r,g,b=lin[:,0],lin[:,1],lin[:,2];l=cp.cbrt(.4122214708*r+.5363325363*g+.0514459929*b);m=cp.cbrt(.2119034982*r+.6806995451*g+.1073969566*b);ss=cp.cbrt(.0883024619*r+.2817188376*g+.6299787005*b);lab=cp.stack((.2104542553*l+.7936177850*m-.0040720468*ss,1.9779984951*l-2.4285922050*m+.4505937099*ss,.0259040371*l+.7827717662*m-.8086757660*ss),axis=1);d=lab[:,None,:]-lab[None,:,:];out=cp.sqrt(cp.sum(d*d,axis=2,dtype=cp.float32))*100.0;cp.cuda.Stream.null.synchronize();host=cp.asnumpy(out).astype(np.float32,copy=False)
            return host,route.as_dict()
        if route.backend_id.startswith("opencl:"):
            cl,ctx,queue,program=_opencl_context(route.backend_id);mf=cl.mem_flags;host4=_float4_host(arr);src=cl.Buffer(ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=host4);lab=cl.Buffer(ctx,mf.READ_WRITE,host4.nbytes);outb=cl.Buffer(ctx,mf.WRITE_ONLY,n*n*4);program.ds_oklab_kernel(queue,(n,),None,src,lab,np.int32(n));program.ds_pairwise_lab(queue,(n*n,),None,lab,outb,np.int32(n));sink=np.empty((n*n,),dtype=np.float32);cl.enqueue_copy(queue,sink,outb);queue.finish();return sink.reshape(n,n),route.as_dict()
        raise RuntimeError(f"unsupported backend {route.backend_id}")
    except Exception as exc:
        fallback=_mark_failed(route,exc);lab=_oklab_cpu(arr);d=lab[:,None,:]-lab[None,:,:];return (np.sqrt(np.sum(d*d,axis=2,dtype=np.float32))*100.0).astype(np.float32,copy=False),fallback.as_dict()
