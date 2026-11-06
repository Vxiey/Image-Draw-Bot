"""Step 22 — universal hardware benchmark and adaptive performance profile.

The benchmark is local-only and vendor-neutral.  It detects NVIDIA, AMD and
Intel adapters independently from compute libraries, benchmarks CPU/NumPy and
any usable CUDA/OpenCL devices, then stores a compact per-machine profile.

This module does not move the mouse, capture the screen, access the network or
store user images.  It benchmarks synthetic numeric arrays only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from importlib import metadata
import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from GpuHardware import GpuDevice, detect_gpus
from ResourceAllocation import available_ram_mb, logical_cpu_count
from RuntimePaths import atomic_binary_writer, data_dir, is_finite_number, read_json
from ImageGradients import luminance_edges
from WindowsSystem import load_system_library

PROFILE_VERSION = 2
PROFILE_FILE = data_dir() / "hardware-performance-profile-v1.json"
WORKLOADS = ("oklab", "palette_match", "edge_map", "bulk_matrix")
GPU_SPEEDUP_MARGIN = 1.12
SMALL_GPU_SPEEDUP_MARGIN = 1.08


@dataclass(frozen=True)
class BackendScore:
    backend_id: str
    backend: str
    vendor: str
    device: str
    workload: str
    size: int
    pixels: int
    elapsed_ms: float
    throughput_mp_s: float
    total_memory_mb: int | None = None
    free_memory_mb: int | None = None
    integrated: bool | None = None
    compute_units: int | None = None
    runtime: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _total_ram_mb() -> int | None:
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX(); stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            memory_status = load_system_library("kernel32.dll").GlobalMemoryStatusEx
            memory_status.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
            memory_status.restype = ctypes.c_int32
            if memory_status(ctypes.byref(stat)):
                return max(0, int(stat.ullTotalPhys // (1024 * 1024)))
        except Exception:
            return None
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return max(0, int((pages * page_size) // (1024 * 1024)))
    except (AttributeError, OSError, ValueError):
        return None


def cpu_name() -> str:
    identifier = str(os.environ.get("PROCESSOR_IDENTIFIER", "") or "").strip()
    if identifier:
        return identifier
    # platform.processor() uses WMI on Windows. Do not query it eagerly when
    # the standard process environment already supplies the CPU description.
    for probe in (platform.processor, platform.machine):
        try:
            value = str(probe() or "").strip()
        except (OSError, RuntimeError):
            continue
        if value:
            return value
    return "Unknown CPU"


def runtime_versions() -> dict[str, str]:
    """Read installed versions without initializing optional GPU libraries."""
    result = {"python": platform.python_version(), "numpy": str(np.__version__)}

    def installed_version(*distributions: str) -> str:
        for distribution in distributions:
            try:
                value = metadata.version(distribution)
            except (metadata.PackageNotFoundError, OSError, ValueError):
                continue
            if value:
                return str(value)
        return ""

    result["cupy"] = installed_version("cupy", "cupy-cuda13x", "cupy-cuda12x", "cupy-cuda11x")
    result["pyopencl"] = installed_version("pyopencl")
    # Frozen distributions can omit metadata; already-loaded modules are an
    # acceptable fallback, but probing versions must not import them itself.
    for name, attribute in (("cupy", "__version__"), ("pyopencl", "VERSION_TEXT")):
        if not result[name]:
            module = sys.modules.get(name)
            result[name] = str(getattr(module, attribute, "") or "unavailable")
    for distribution in ("nvidia-cuda-runtime-cu12", "nvidia-cuda-runtime-cu13"):
        value = installed_version(distribution)
        if value:
            result[distribution] = value
    return result


def hardware_snapshot(*, refresh: bool = False) -> dict[str, Any]:
    gpus = detect_gpus(refresh=refresh)
    total_ram = _total_ram_mb()
    payload = {
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "cpu": cpu_name(),
        "logical_cpus": logical_cpu_count(),
        "total_ram_mb": total_ram,
        "available_ram_mb": available_ram_mb(),
        "gpus": [gpu.as_dict() for gpu in gpus],
        "runtime_versions": runtime_versions(),
    }
    stable = {
        "platform": payload["platform"],
        "cpu": payload["cpu"],
        "logical_cpus": payload["logical_cpus"],
        # RAM changes should invalidate, but ignore tiny reporting jitter.
        "total_ram_256mb": None if total_ram is None else int(round(total_ram / 256.0) * 256),
        "gpus": [
            {
                "vendor": gpu.vendor,
                "name": gpu.name,
                "memory_total_mb": gpu.memory_total_mb,
                "driver_version": gpu.driver_version,
                "bus_id": gpu.bus_id,
                "pnp_device_id": gpu.pnp_device_id,
            }
            for gpu in gpus
        ],
        "runtime_versions": payload["runtime_versions"],
    }
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["hardware_signature"] = hashlib.sha256(encoded).hexdigest()[:24]
    return payload


def _srgb_to_oklab_np(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float32)
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    r, g, b = linear[..., 0], linear[..., 1], linear[..., 2]
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return np.stack((
        0.2104542553*l + 0.7936177850*m - 0.0040720468*s,
        1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
        0.0259040371*l + 0.7827717662*m - 0.8086757660*s,
    ), axis=-1).astype(np.float32, copy=False)


def _synthetic_rgb(size: int) -> np.ndarray:
    size = max(32, int(size))
    y, x = np.mgrid[0:size, 0:size]
    r = ((x * 13 + y * 3) % 256).astype(np.float32) / 255.0
    g = ((x * 5 + y * 17 + (x ^ y)) % 256).astype(np.float32) / 255.0
    b = ((x * 23 + y * 7 + (x * y) % 31) % 256).astype(np.float32) / 255.0
    return np.stack((r, g, b), axis=-1)


def _cancel(cancelled):
    if cancelled():
        raise InterruptedError()


def _benchmark_parameters(size, repeats):
    from numbers import Integral
    if (isinstance(size, bool) or not isinstance(size, Integral)
            or isinstance(repeats, bool) or not isinstance(repeats, Integral)):
        raise ValueError("Benchmark size and repetitions must be integers")
    return max(32, min(1024, int(size))), max(1, min(5, int(repeats)))


def _verify_output(workload, value, expected):
    actual = np.asarray(value)
    if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
        raise RuntimeError(f"{workload} returned invalid benchmark output")
    correct = (np.array_equal(actual, expected) if workload == "palette_match"
               else np.allclose(actual, expected, rtol=2e-4, atol=2e-5))
    if not correct:
        raise RuntimeError(f"{workload} failed the CPU-reference validation")


def _time_best(function: Callable[[], Any], repeats: int, *, cancelled=lambda: False,
               expected=None, workload="") -> float:
    timings: list[float] = []
    for _ in range(max(1, int(repeats))):
        _cancel(cancelled)
        started = time.perf_counter()
        value = function()
        # Touch a scalar so lazy views are not benchmarked accidentally.
        if isinstance(value, np.ndarray) and value.size:
            float(value.reshape(-1)[-1])
        timings.append(max(time.perf_counter() - started, 1e-9))
        _cancel(cancelled)
        if expected is not None:
            _verify_output(workload, value, expected)
    return min(timings)


def _cpu_workloads(rgb):
    flat = rgb.reshape(-1, 3)
    palette = _synthetic_rgb(4).reshape(-1, 3)[:16]
    gray = (rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722).astype(np.float32)

    def oklab():
        return _srgb_to_oklab_np(rgb)

    def palette_match():
        best = np.full((flat.shape[0],), np.inf, dtype=np.float32)
        indices = np.zeros((flat.shape[0],), dtype=np.int16)
        for idx, color in enumerate(palette):
            delta = flat - color
            dist = np.sum(delta * delta, axis=1)
            mask = dist < best
            best[mask] = dist[mask]
            indices[mask] = idx
        return indices

    def edge_map():
        return luminance_edges(gray)

    def bulk_matrix():
        x = rgb
        return ((x * 0.731 + 0.117) * (1.0 - x * 0.213) + np.sqrt(x + 0.001)).astype(np.float32)

    return {"oklab": oklab, "palette_match": palette_match, "edge_map": edge_map, "bulk_matrix": bulk_matrix}


def benchmark_cpu(*, size: int = 512, repeats: int = 2, cancelled=lambda: False) -> list[BackendScore]:
    _cancel(cancelled)
    size,repeats=_benchmark_parameters(size,repeats)
    functions=_cpu_workloads(_synthetic_rgb(size))
    pixels=size*size
    device=cpu_name()
    results: list[BackendScore] = []
    for workload, function in functions.items():
        _cancel(cancelled)
        function()  # Warm allocator/library paths outside the measured repeats.
        elapsed = _time_best(function, repeats, cancelled=cancelled)
        results.append(BackendScore(
            "cpu:numpy", "CPU/NumPy", "CPU", device, workload, size, pixels,
            round(elapsed * 1000.0, 3), round((pixels / 1_000_000.0) / elapsed, 3),
            runtime=f"NumPy {np.__version__}",
        ))
    return results


def _cupy_props(cp, device_id: int) -> tuple[str, int | None, int | None, int | None]:
    with cp.cuda.Device(device_id):
        props = cp.cuda.runtime.getDeviceProperties(device_id)
        raw_name = props.get("name") if isinstance(props, dict) else getattr(props, "name", b"CUDA GPU")
        if isinstance(raw_name, bytes):
            name = raw_name.decode("utf-8", "replace")
        else:
            name = str(raw_name or "CUDA GPU")
        free_b, total_b = cp.cuda.runtime.memGetInfo()
        sms = props.get("multiProcessorCount", props.get("multi_processor_count", 0)) if isinstance(props, dict) else 0
        return name, int(total_b // (1024 * 1024)), int(free_b // (1024 * 1024)), int(sms or 0) or None


def _release_workload_frames(error: BaseException) -> None:
    """A retained driver/cancellation traceback must not retain device buffers."""
    import traceback
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        traceback.clear_frames(error.__traceback__)
        error = error.__cause__ or error.__context__


def benchmark_cuda(*, size: int = 512, repeats: int = 2, cancelled=lambda: False) -> list[BackendScore]:
    _cancel(cancelled)
    size,repeats=_benchmark_parameters(size,repeats)
    try:
        import cupy as cp
        count = int(cp.cuda.runtime.getDeviceCount())
    except InterruptedError:
        raise
    except Exception:
        return []
    host_rgb = _synthetic_rgb(size)
    host_palette = _synthetic_rgb(4).reshape(-1, 3)[:16]
    host_gray = (host_rgb[..., 0] * .2126 + host_rgb[..., 1] * .7152 + host_rgb[..., 2] * .0722).astype(np.float32)
    references = _cpu_workloads(host_rgb)
    pixels = int(size * size)
    all_results: list[BackendScore] = []

    for device_id in range(max(0, count)):
        _cancel(cancelled)
        try:
            name, total_mb, free_mb, sms = _cupy_props(cp, device_id)
            with cp.cuda.Device(device_id):
                def sync(value):
                    # Blocking whole-result download measures usable host output
                    # on the current stream, rather than a single scalar sample.
                    return cp.asnumpy(value)

                def oklab():
                    rgb = cp.asarray(host_rgb)
                    linear = cp.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
                    r, g, b = linear[..., 0], linear[..., 1], linear[..., 2]
                    l = cp.cbrt(0.4122214708*r + 0.5363325363*g + 0.0514459929*b)
                    m = cp.cbrt(0.2119034982*r + 0.6806995451*g + 0.1073969566*b)
                    s = cp.cbrt(0.0883024619*r + 0.2817188376*g + 0.6299787005*b)
                    out = cp.stack((0.2104542553*l + 0.7936177850*m - 0.0040720468*s,
                                    1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
                                    0.0259040371*l + 0.7827717662*m - 0.8086757660*s), axis=-1)
                    return sync(out)

                def palette_match():
                    flat = cp.asarray(host_rgb).reshape(-1, 3)
                    palette = cp.asarray(host_palette)
                    best = cp.full((flat.shape[0],), cp.inf, dtype=cp.float32)
                    indices = cp.zeros((flat.shape[0],), dtype=cp.int16)
                    for idx in range(int(palette.shape[0])):
                        _cancel(cancelled)
                        delta = flat - palette[idx]
                        dist = cp.sum(delta * delta, axis=1)
                        mask = dist < best
                        best = cp.where(mask, dist, best)
                        indices = cp.where(mask, idx, indices)
                    return sync(indices)

                def edge_map():
                    gray = cp.asarray(host_gray)
                    return sync(luminance_edges(gray,xp=cp))

                def bulk_matrix():
                    rgb = cp.asarray(host_rgb)
                    out = ((rgb * 0.731 + 0.117) * (1.0 - rgb * 0.213) + cp.sqrt(rgb + 0.001)).astype(cp.float32)
                    return sync(out)

                functions = {"oklab": oklab, "palette_match": palette_match, "edge_map": edge_map, "bulk_matrix": bulk_matrix}
                for workload, function in functions.items():
                    _cancel(cancelled)
                    expected = references[workload]()
                    _verify_output(workload,function(),expected)
                    elapsed = _time_best(function,repeats,cancelled=cancelled,expected=expected,workload=workload)
                    all_results.append(BackendScore(
                        f"cuda:{device_id}", "CUDA/CuPy", "NVIDIA", name, workload, size, pixels,
                        round(elapsed * 1000.0, 3), round((pixels / 1_000_000.0) / elapsed, 3),
                        total_mb, free_mb, False, sms, f"CuPy {getattr(cp, '__version__', 'unknown')}",
                    ))
        except InterruptedError as exc:
            _release_workload_frames(exc)
            raise
        except Exception as exc:
            _release_workload_frames(exc)
            all_results.append(BackendScore(
                f"cuda:{device_id}", "CUDA/CuPy", "NVIDIA", f"CUDA device {device_id}", "probe", size, pixels,
                0.0, 0.0, error=f"{type(exc).__name__}: {exc}",
            ))
        finally:
            # Completed frames, including ones retained by a propagated error,
            # no longer keep their arrays live when the pool is trimmed.
            try:
                with cp.cuda.Device(device_id):
                    cp.get_default_memory_pool().free_all_blocks()
            except Exception:
                pass
    return all_results


_OPENCL_SOURCE = r"""
inline float imagedrawbot_srgb_linear(float c) {
    return c <= 0.04045f ? c / 12.92f : pow((c + 0.055f) / 1.055f, 2.4f);
}
__kernel void imagedrawbot_oklabish(__global const float4 *src, __global float4 *dst, const int n) {
    int i=get_global_id(0); if(i>=n) return; float4 x=src[i];
    float r=imagedrawbot_srgb_linear(x.x), g=imagedrawbot_srgb_linear(x.y), b=imagedrawbot_srgb_linear(x.z);
    float l=cbrt(0.4122214708f*r + 0.5363325363f*g + 0.0514459929f*b);
    float m=cbrt(0.2119034982f*r + 0.6806995451f*g + 0.1073969566f*b);
    float ss=cbrt(0.0883024619f*r + 0.2817188376f*g + 0.6299787005f*b);
    dst[i]=(float4)(0.2104542553f*l + 0.7936177850f*m - 0.0040720468f*ss,
                    1.9779984951f*l - 2.4285922050f*m + 0.4505937099f*ss,
                    0.0259040371f*l + 0.7827717662f*m - 0.8086757660f*ss, 1.0f);
}
__kernel void imagedrawbot_palette(__global const float4 *src, __global const float4 *pal,
                                 __global ushort *out, const int n, const int count) {
    int i=get_global_id(0); if(i>=n) return; float4 x=src[i]; float best=3.4e38f; ushort best_i=0;
    for(int p=0;p<count;p++){float4 d=x-pal[p]; float dist=d.x*d.x+d.y*d.y+d.z*d.z;
        if(dist<best){best=dist;best_i=(ushort)p;}}
    out[i]=best_i;
}
__kernel void imagedrawbot_edge(__global const float *src, __global float *dst, const int w, const int h) {
    int i=get_global_id(0); int n=w*h; if(i>=n) return; int x=i%w; int y=i/w;
    int xl=max(0,x-1), xr=min(w-1,x+1), yu=max(0,y-1), yd=min(h-1,y+1);
    float gx=(w>1)?(src[y*w+xr]-src[y*w+xl])/(float)(xr-xl):0.0f;
    float gy=(h>1)?(src[yd*w+x]-src[yu*w+x])/(float)(yd-yu):0.0f; dst[i]=sqrt(gx*gx+gy*gy);
}
__kernel void imagedrawbot_bulk(__global const float4 *src, __global float4 *dst, const int n) {
    int i=get_global_id(0); if(i>=n) return; float4 x=src[i];
    dst[i]=(x*0.731f+0.117f)*(1.0f-x*0.213f)+sqrt(x+0.001f);
}
"""


def _opencl_vendor(value: str) -> str:
    text = str(value or "").lower()
    if "nvidia" in text:
        return "NVIDIA"
    if "advanced micro devices" in text or "amd" in text or "radeon" in text:
        return "AMD"
    if "intel" in text:
        return "Intel"
    return "Unknown"


def benchmark_opencl(*, size: int = 512, repeats: int = 2, cancelled=lambda: False) -> list[BackendScore]:
    _cancel(cancelled)
    size,repeats=_benchmark_parameters(size,repeats)
    try:
        import pyopencl as cl
    except InterruptedError:
        raise
    except Exception:
        return []
    host_rgb3 = _synthetic_rgb(size).astype(np.float32)
    host_rgb4 = np.ones((size * size, 4), dtype=np.float32)
    host_rgb4[:, :3] = host_rgb3.reshape(-1, 3)
    host_palette4 = np.ones((16, 4), dtype=np.float32)
    host_palette4[:, :3] = _synthetic_rgb(4).reshape(-1, 3)[:16]
    host_gray = (host_rgb3[..., 0] * 0.2126 + host_rgb3[..., 1] * 0.7152 + host_rgb3[..., 2] * 0.0722).astype(np.float32).reshape(-1)
    pixels = int(size * size)
    references = _cpu_workloads(host_rgb3)
    results: list[BackendScore] = []
    try:
        platforms = list(cl.get_platforms())
    except InterruptedError:
        raise
    except Exception:
        return []
    for pidx, cl_platform in enumerate(platforms):
        _cancel(cancelled)
        try:
            devices = list(cl_platform.get_devices(device_type=cl.device_type.GPU))
        except InterruptedError:
            raise
        except Exception:
            continue
        for didx, device in enumerate(devices):
            _cancel(cancelled)
            backend_id = f"opencl:{pidx}:{didx}"
            name=f"OpenCL GPU {didx}";vendor="Unknown";total_mb=compute_units=None;integrated=False;runtime=""
            ctx=queue=program=src4=dst4=pal=idx_out=gray=edge_out=specs=execute=None
            try:
                vendor = _opencl_vendor(f"{getattr(device, 'vendor', '')} {getattr(device, 'name', '')}")
                name = str(getattr(device, "name", name)).strip()
                total_mb = int(getattr(device, "global_mem_size", 0) or 0) // (1024 * 1024) or None
                compute_units = int(getattr(device, "max_compute_units", 0) or 0) or None
                integrated = bool(getattr(device, "host_unified_memory", False))
                runtime = f"OpenCL {getattr(device, 'version', '')} · {getattr(device, 'driver_version', '')}".strip(" ·")
                ctx = cl.Context(devices=[device])
                queue = cl.CommandQueue(ctx)
                program = cl.Program(ctx, _OPENCL_SOURCE).build(options=[])
                mf = cl.mem_flags
                src4 = cl.Buffer(ctx, mf.READ_ONLY, host_rgb4.nbytes)
                dst4 = cl.Buffer(ctx, mf.WRITE_ONLY, host_rgb4.nbytes)
                pal = cl.Buffer(ctx, mf.READ_ONLY, host_palette4.nbytes)
                idx_out = cl.Buffer(ctx, mf.WRITE_ONLY, pixels * np.dtype(np.uint16).itemsize)
                gray = cl.Buffer(ctx, mf.READ_ONLY, host_gray.nbytes)
                edge_out = cl.Buffer(ctx, mf.WRITE_ONLY, host_gray.nbytes)
                sink4 = np.empty_like(host_rgb4)
                sink_idx = np.empty((pixels,), dtype=np.uint16)
                sink_gray = np.empty_like(host_gray)

                specs = {
                    "oklab": (program.imagedrawbot_oklabish,dst4,sink4,(src4,dst4,np.int32(pixels)),((src4,host_rgb4),)),
                    "palette_match": (program.imagedrawbot_palette,idx_out,sink_idx,(src4,pal,idx_out,np.int32(pixels),np.int32(16)),((src4,host_rgb4),(pal,host_palette4))),
                    "edge_map": (program.imagedrawbot_edge,edge_out,sink_gray,(gray,edge_out,np.int32(size),np.int32(size)),((gray,host_gray),)),
                    "bulk_matrix": (program.imagedrawbot_bulk,dst4,sink4,(src4,dst4,np.int32(pixels)),((src4,host_rgb4),)),
                }
                for workload in WORKLOADS:
                    _cancel(cancelled)
                    expected=references[workload]()
                    kernel,output_buffer,sink,args,uploads=specs[workload]
                    def execute():
                        for buffer,host in uploads:
                            cl.enqueue_copy(queue,buffer,host,is_blocking=False)
                        kernel(queue,(pixels,),None,*args)
                        cl.enqueue_copy(queue,sink,output_buffer)
                        queue.finish()
                        values=sink[:,:3] if sink.ndim==2 else sink
                        return values.reshape(expected.shape)
                    _verify_output(workload,execute(),expected)
                    elapsed=_time_best(execute,repeats,cancelled=cancelled,expected=expected,workload=workload)
                    results.append(BackendScore(
                        backend_id, "OpenCL", vendor, name, workload, size, pixels,
                        round(elapsed*1000.0,3), round((pixels/1_000_000.0)/elapsed,3),
                        total_mb, None, integrated, compute_units, runtime,
                    ))
            except InterruptedError as exc:
                _release_workload_frames(exc)
                raise
            except Exception as exc:
                _release_workload_frames(exc)
                results.append(BackendScore(
                    backend_id, "OpenCL", vendor, name, "probe", size, pixels, 0.0, 0.0,
                    total_mb, None, integrated, compute_units, runtime, f"{type(exc).__name__}: {exc}",
                ))
            finally:
                # Release every device's own buffers before probing another.
                ctx=queue=program=src4=dst4=pal=idx_out=gray=edge_out=specs=execute=None
                kernel=output_buffer=args=uploads=None
    return results


def _scores_by_workload(scores: list[BackendScore]) -> dict[str, list[BackendScore]]:
    grouped: dict[str, list[BackendScore]] = {workload: [] for workload in WORKLOADS}
    for score in scores:
        try:
            valid = (math.isfinite(score.throughput_mp_s) and score.throughput_mp_s > 0
                     and math.isfinite(score.elapsed_ms) and score.elapsed_ms >= 0)
        except (TypeError, ValueError, OverflowError):
            valid = False
        if score.workload in grouped and not score.error and valid:
            grouped[score.workload].append(score)
    return grouped


def _safe_gpu_budget_mb(score: BackendScore) -> int | None:
    try:
        total = int(score.total_memory_mb or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if total < 256:
        return None
    if score.integrated:
        budget = min(4096, int(total * 0.20))
    else:
        reserve = min(total // 4, max(768, min(2048, int(total * 0.10))))
        budget = min(int(total * 0.68), total - reserve)
    # A large card may already be occupied by another application. A measured
    # free-memory value, including zero, is stricter than total VRAM capacity.
    if score.free_memory_mb is not None:
        try:
            free = int(score.free_memory_mb)
        except (TypeError, ValueError, OverflowError):
            free = -1
        if free >= 0:
            budget = min(budget, int(free * 0.80))
    return max(0, budget)


def _tile_from_budget(memory_mb: int | None) -> int:
    if not memory_mb:
        return 768
    if memory_mb >= 8192:
        return 3072
    if memory_mb >= 4096:
        return 2048
    if memory_mb >= 2048:
        return 1536
    if memory_mb >= 1024:
        return 1024
    return 768


def build_preferences(*, small_scores: list[BackendScore], large_scores: list[BackendScore]) -> dict[str, Any]:
    small = _scores_by_workload(small_scores)
    large = _scores_by_workload(large_scores)
    workload_preferences: dict[str, Any] = {}
    gpu_wins: list[BackendScore] = []
    for workload in WORKLOADS:
        cpu_large = next((s for s in large.get(workload, []) if s.backend_id == "cpu:numpy"), None)
        candidates = [s for s in large.get(workload, []) if s.backend_id != "cpu:numpy"]
        best_gpu = max(candidates, key=lambda s: s.throughput_mp_s, default=None)
        cpu_rate = float(cpu_large.throughput_mp_s if cpu_large else 0.0)
        selected = cpu_large
        reason = "CPU is fastest or no usable GPU compute backend is available"
        min_pixels = 0
        speedup = 1.0
        if best_gpu and cpu_rate > 0:
            speedup = best_gpu.throughput_mp_s / cpu_rate
            if speedup >= GPU_SPEEDUP_MARGIN:
                selected = best_gpu
                gpu_wins.append(best_gpu)
                small_cpu = next((s for s in small.get(workload, []) if s.backend_id == "cpu:numpy"), None)
                small_gpu = next((s for s in small.get(workload, []) if s.backend_id == best_gpu.backend_id), None)
                small_speedup = (small_gpu.throughput_mp_s / small_cpu.throughput_mp_s) if small_cpu and small_gpu and small_cpu.throughput_mp_s else 0.0
                min_pixels = int(small_gpu.pixels if small_speedup >= SMALL_GPU_SPEEDUP_MARGIN else max(120_000, small_gpu.pixels * 4 if small_gpu else 160_000))
                reason = f"{best_gpu.backend} on {best_gpu.device} is {speedup:.2f}× CPU for large {workload} batches"
        if selected is None:
            selected = BackendScore("cpu:numpy", "CPU/NumPy", "CPU", cpu_name(), workload, 0, 0, 0.0, 0.0)
        workload_preferences[workload] = {
            "backend_id": selected.backend_id,
            "backend": selected.backend,
            "vendor": selected.vendor,
            "device": selected.device,
            "large_throughput_mp_s": float(selected.throughput_mp_s),
            "speedup_vs_cpu": round(speedup if selected.backend_id != "cpu:numpy" else 1.0, 3),
            "min_pixels": int(min_pixels),
            "reason": reason,
        }
    if gpu_wins:
        counts: dict[str, int] = {}
        for score in gpu_wins:
            counts[score.backend_id] = counts.get(score.backend_id, 0) + 1
        primary_id = max(counts, key=lambda key: (counts[key], max(s.throughput_mp_s for s in gpu_wins if s.backend_id == key)))
        primary = max((s for s in gpu_wins if s.backend_id == primary_id), key=lambda s: s.throughput_mp_s)
        safe_mem = _safe_gpu_budget_mb(primary)
        primary_backend = {
            "backend_id": primary.backend_id,
            "backend": primary.backend,
            "vendor": primary.vendor,
            "device": primary.device,
            "total_memory_mb": primary.total_memory_mb,
            "safe_memory_budget_mb": safe_mem,
            "integrated": primary.integrated,
            "compute_units": primary.compute_units,
            "tile_size": _tile_from_budget(safe_mem),
        }
    else:
        primary_backend = {
            "backend_id": "cpu:numpy", "backend": "CPU/NumPy", "vendor": "CPU", "device": cpu_name(),
            "total_memory_mb": None, "safe_memory_budget_mb": None, "integrated": None,
            "compute_units": None, "tile_size": 768,
        }
    return {"workloads": workload_preferences, "primary_backend": primary_backend}


def _detected_backend_notes(snapshot: dict[str, Any], scores: list[BackendScore]) -> list[dict[str, Any]]:
    score_devices = {(score.vendor, score.device) for score in scores if score.backend_id != "cpu:numpy" and not score.error}
    notes=[]
    for raw in snapshot.get("gpus", []):
        if not isinstance(raw, dict):
            continue
        vendor=str(raw.get("vendor") or "Unknown")
        name=str(raw.get("name") or "GPU")
        usable=any(vendor == sv and (name.lower() in sn.lower() or sn.lower() in name.lower()) for sv,sn in score_devices)
        notes.append({
            "vendor":vendor,"name":name,"memory_total_mb":raw.get("memory_total_mb"),
            "driver_version":str(raw.get("driver_version") or ""),"compute_benchmarked":bool(usable),
            "note":"compute backend benchmarked" if usable else "adapter detected; optional CUDA/OpenCL compute runtime not usable in this environment",
        })
    return notes


def run_universal_hardware_benchmark(*, save: bool = True, path: Path | None = None,
                                     small_size: int = 128, large_size: int = 512,
                                     repeats: int = 2, refresh_hardware: bool = True,
                                     cancelled=lambda: False) -> dict[str, Any]:
    """Run bounded CPU + usable GPU microbenchmarks and save a per-machine profile."""
    started=time.perf_counter()
    _cancel(cancelled)
    small_size,repeats=_benchmark_parameters(small_size,repeats)
    large_size,_=_benchmark_parameters(large_size,repeats)
    small_size=max(64,min(256,small_size))
    large_size=max(256,large_size)
    snapshot=hardware_snapshot(refresh=refresh_hardware)

    small_scores=benchmark_cpu(size=small_size,repeats=repeats,cancelled=cancelled)
    large_scores=benchmark_cpu(size=large_size,repeats=repeats,cancelled=cancelled)
    # CUDA and OpenCL are independent. On NVIDIA systems both may be available;
    # the profile keeps the faster backend per workload instead of assuming one.
    small_scores.extend(benchmark_cuda(size=small_size,repeats=repeats,cancelled=cancelled))
    large_scores.extend(benchmark_cuda(size=large_size,repeats=repeats,cancelled=cancelled))
    small_scores.extend(benchmark_opencl(size=small_size,repeats=repeats,cancelled=cancelled))
    large_scores.extend(benchmark_opencl(size=large_size,repeats=repeats,cancelled=cancelled))
    _cancel(cancelled)

    preferences=build_preferences(small_scores=small_scores,large_scores=large_scores)
    primary=dict(preferences.get("primary_backend") or {})
    cpu_large=[s for s in large_scores if s.backend_id=="cpu:numpy" and s.workload in WORKLOADS]
    cpu_composite=statistics.fmean([s.throughput_mp_s for s in cpu_large]) if cpu_large else 0.0
    result={
        "version":PROFILE_VERSION,
        "created_at":int(time.time()),
        "elapsed_ms":round((time.perf_counter()-started)*1000.0,1),
        "hardware_signature":snapshot.get("hardware_signature"),
        "hardware":snapshot,
        "detected_gpus":_detected_backend_notes(snapshot,small_scores+large_scores),
        "small_size":small_size,"large_size":large_size,
        "scores_small":[s.as_dict() for s in small_scores],
        "scores_large":[s.as_dict() for s in large_scores],
        "workload_preferences":preferences.get("workloads",{}),
        "primary_backend":primary,
        "cpu_composite_mp_s":round(float(cpu_composite),3),
        "cpu_fallback_available":True,
        "privacy":{"network":False,"screen_capture":False,"mouse_input":False,"image_storage":False,"synthetic_arrays_only":True},
    }
    if save:
        save_hardware_profile(result,path=path,cancelled=cancelled)
    return result


def save_hardware_profile(result: dict[str, Any], *, path: Path | None = None,
                           cancelled=lambda: False) -> Path:
    target=Path(path or PROFILE_FILE)
    payload=dict(result)
    payload["version"]=PROFILE_VERSION
    if not _profile_structure_valid(payload):
        raise ValueError("Invalid hardware performance profile")
    encoded=json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8")
    if len(encoded)>4*1024*1024:
        raise ValueError("Hardware performance profile exceeds its read limit")
    with atomic_binary_writer(target,cancelled=cancelled) as stream:
        stream.write(encoded)
    return target


def load_hardware_profile(*, path: Path | None = None, validate_current: bool = True) -> dict[str, Any] | None:
    target=Path(path or PROFILE_FILE)
    payload = _read_profile(target)
    if not _current_profile_version(payload) or not _profile_structure_valid(payload):
        return None
    if validate_current:
        try:
            current=hardware_snapshot(refresh=False).get("hardware_signature")
        except InterruptedError:
            raise
        except Exception:
            return None
        if not current or str(payload.get("hardware_signature") or "")!=str(current):
            return None
    return payload


def profile_needs_benchmark(*, path: Path | None = None) -> tuple[bool,str]:
    target=Path(path or PROFILE_FILE)
    raw = _read_profile(target)
    if raw is None:
        return True,"no saved hardware profile"
    if not _current_profile_version(raw) or not _profile_structure_valid(raw):
        return True,"hardware profile version changed"
    try:
        current=hardware_snapshot(refresh=True).get("hardware_signature")
    except InterruptedError:
        raise
    except Exception:
        return True,"current hardware could not be verified"
    if str(raw.get("hardware_signature") or "")!=str(current or ""):
        return True,"CPU/GPU/RAM/driver/compute-runtime signature changed"
    return False,"saved hardware profile matches this machine"


def _read_profile(path: Path) -> dict[str, Any] | None:
    try:
        payload = read_json(path)
    except (OSError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _current_profile_version(payload: dict[str, Any] | None) -> bool:
    value = payload.get("version") if payload else None
    return type(value) is int and value == PROFILE_VERSION


def _profile_structure_valid(payload) -> bool:
    if not isinstance(payload,dict):return False
    pending=[(payload,0)];count=0
    while pending:
        value,depth=pending.pop();count+=1
        if depth>32 or count>100000:return False
        if isinstance(value,dict):
            if not all(isinstance(key,str) for key in value):return False
            children=value.values()
        elif isinstance(value,list):children=value
        elif value is None or type(value) in (str,bool):continue
        elif is_finite_number(value):continue
        else:return False
        if len(pending)+count+len(children)>100000:return False
        pending.extend((child,depth+1) for child in children)
    for key in ("hardware","primary_backend","workload_preferences"):
        if key in payload and not isinstance(payload[key],dict):return False
    for key in ("scores_small","scores_large","detected_gpus"):
        if key in payload and (not isinstance(payload[key],list)
                               or not all(isinstance(item,dict) for item in payload[key])):return False
    for key in ("elapsed_ms","created_at","cpu_composite_mp_s"):
        if key in payload and (not is_finite_number(payload[key]) or payload[key]<0):return False
    primary=payload.get("primary_backend",{})
    for key in ("safe_memory_budget_mb","total_memory_mb","tile_size","compute_units"):
        value=primary.get(key)
        if value is not None and (type(value) is not int or not is_finite_number(value) or value<0):return False
    return True


def preferred_backend(workload: str, *, pixels: int, profile: dict[str,Any] | None = None) -> dict[str,Any]:
    def cpu(reason: str) -> dict[str, Any]:
        return {"backend_id": "cpu:numpy", "backend": "CPU/NumPy", "vendor": "CPU",
                "device": cpu_name(), "reason": reason}

    if profile is None:
        profile = load_hardware_profile() or {}
    if not isinstance(profile, dict):
        return cpu("invalid benchmark preference")
    preferences = profile.get("workload_preferences")
    if not isinstance(preferences, dict):
        return cpu("no benchmark preference")
    item = preferences.get(str(workload))
    if not isinstance(item, dict) or not isinstance(item.get("backend_id"), str) or not item["backend_id"]:
        return cpu("no benchmark preference")
    try:
        minimum = int(item.get("min_pixels", 0) or 0)
        count = int(pixels or 0)
    except (TypeError, ValueError, OverflowError):
        return cpu("invalid benchmark crossover threshold")
    if minimum < 0 or count < 0:
        return cpu("invalid benchmark crossover threshold")
    if item["backend_id"] != "cpu:numpy" and count < minimum:
        return cpu("workload below measured GPU crossover threshold")
    return dict(item)


def format_hardware_summary(result: dict[str, Any]) -> str:
    result=result if isinstance(result,dict) else {}
    hardware=result.get("hardware") if isinstance(result.get("hardware"),dict) else {}
    gpus=result.get("detected_gpus") if isinstance(result.get("detected_gpus"),list) else []
    primary=result.get("primary_backend") if isinstance(result.get("primary_backend"),dict) else {}
    gpu_text="No GPU compute backend"
    if gpus:
        names=[]
        for item in gpus:
            if not isinstance(item,dict): continue
            marker="✓" if item.get("compute_benchmarked") else "detected"
            names.append(f"{item.get('vendor','GPU')} {item.get('name','GPU')} ({marker})")
        gpu_text="; ".join(names[:3])
    primary_text=f"{primary.get('backend','CPU/NumPy')} · {primary.get('device',cpu_name())}"
    safe=primary.get("safe_memory_budget_mb")
    memory=f" · safe GPU memory {int(safe):,} MB" if is_finite_number(safe) and safe>0 else ""
    elapsed=result.get("elapsed_ms",0)
    elapsed=elapsed if is_finite_number(elapsed) and elapsed>=0 else 0
    return (
        f"CPU {hardware.get('logical_cpus',logical_cpu_count())} logical · RAM {hardware.get('total_ram_mb') or '?'} MB · "
        f"GPUs: {gpu_text} · preferred compute: {primary_text}{memory} · "
        f"{elapsed:.0f} ms"
    )
