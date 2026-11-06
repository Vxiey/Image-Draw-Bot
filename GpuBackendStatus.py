"""Verified GPU/CPU analysis backend status for Image Draw Bot v1.0.119-beta.

The helper is local-only and cached. It distinguishes configured VRAM from an
actually usable CuPy/CUDA backend and performs a tiny one-time arithmetic probe
when CUDA is available so Auto mode can avoid advertising a backend that cannot
execute kernels.
"""
from __future__ import annotations

import time
from typing import Any

_CACHE: dict[tuple, dict[str, Any]] = {}


def verified_gpu_status(mode: str = "Auto", vram_budget: str = "Auto", performance: str = "Balanced",
                        *, pixels: int = 0, preview: bool = False) -> dict[str, Any]:
    requested = str(mode or "Auto")
    if preview:
        return {
            "requested_mode": requested,
            "gpu_detected": False,
            "cupy_available": False,
            "gpu_analysis_active": False,
            "selected_backend": "CPU",
            "fallback_reason": "preview cancellation policy",
            "benchmark": "skipped for preview",
        }
    key=(requested,str(vram_budget or "Auto"),str(performance or "Balanced"),int(pixels or 0)//160_000)
    # Auto has measured, per-workload crossovers and runtime quarantine state.
    # Re-resolve those inexpensive routes for the actual pixel count; the fixed
    # legacy CUDA threshold is not a valid cache bucket for them.
    cacheable=requested!="Auto"
    if cacheable and key in _CACHE:
        return dict(_CACHE[key])
    # Step 23: Auto is vendor-neutral. Report the same measured per-workload
    # routing that real image analysis will use instead of equating GPU with CUDA.
    if requested == "Auto":
        try:
            from UniversalGpuAcceleration import select_route
            from UniversalHardwareBenchmark import load_hardware_profile
            # Resolve one consistent current profile for all six routes rather
            # than reading and validating the same file six times per update.
            profile=load_hardware_profile() or {}
            routes={}
            for workload in ("oklab","palette_match","delta_e","quantization","edge_map","pixel_math"):
                routes[workload]=select_route(workload,pixels=max(1,int(pixels or 0)),gpu_mode="Auto",profile=profile).as_dict()
            accelerated=[r for r in routes.values() if r.get("accelerated")]
            primary=(accelerated[0] if accelerated else routes.get("pixel_math") or {})
            result={
                "requested_mode":requested,
                "gpu_detected":bool(accelerated),
                "gpu_device":str(primary.get("device") or ""),
                "driver_version":"",
                "cupy_available":any(str(r.get("backend_id","")).startswith("cuda:") for r in routes.values()),
                "opencl_available":any(str(r.get("backend_id","")).startswith("opencl:") for r in routes.values()),
                "gpu_analysis_active":bool(accelerated),
                "selected_backend":str(primary.get("backend") or "CPU/NumPy"),
                "selected_backend_id":str(primary.get("backend_id") or "cpu:numpy"),
                "fallback_reason":"" if accelerated else str(primary.get("reason") or "CPU is fastest for this workload size"),
                "benchmark":{"policy":"Step 22 per-workload crossover","routes":routes},
                "universal_routes":routes,
            }
            return result
        except Exception:
            # Legacy CUDA verifier below remains a safe fallback if the hardware
            # performance profile is unavailable/corrupt.
            pass
    try:
        from GpuAcceleration import acceleration_info, cuda_context
        info=acceleration_info(requested,vram_budget,performance)
        result={
            "requested_mode": requested,
            "gpu_detected": bool(info.hardware_detected or info.accelerated),
            "gpu_device": str(info.hardware_device or info.device or ""),
            "driver_version": str(info.driver_version or ""),
            "cupy_available": bool(info.accelerated),
            "gpu_analysis_active": False,
            "selected_backend": "CPU",
            "fallback_reason": str(info.reason or ""),
            "vram_total_mb": info.total_vram_mb,
            "vram_free_mb": info.free_vram_mb,
            "vram_budget_mb": info.vram_budget_mb,
            "benchmark": "not run",
        }
        if requested == "CPU":
            result["fallback_reason"] = "CPU mode selected"
        elif not info.accelerated:
            result["fallback_reason"] = str(info.reason or "CuPy/CUDA backend unavailable")
        elif int(pixels or 0) < 160_000:
            result["fallback_reason"] = "workload below GPU transfer threshold"
            result["benchmark"] = "not needed for small workload"
        else:
            ctx=cuda_context(requested,vram_budget,performance)
            if ctx is None:
                result["fallback_reason"] = "CUDA context unavailable after verification"
            else:
                cp,_ctx_info=ctx
                # Tiny one-time sanity/performance probe. This is deliberately
                # small: it verifies kernel execution, not a synthetic score war.
                started=time.perf_counter()
                arr=cp.arange(262144,dtype=cp.float32)
                out=arr*1.0001+0.25
                float(cp.asnumpy(out[-1:])[0])
                cp.cuda.Stream.null.synchronize()
                gpu_ms=(time.perf_counter()-started)*1000.0
                result["benchmark"]={"cuda_probe_ms":round(gpu_ms,3),"elements":262144}
                result["gpu_analysis_active"]=True
                result["selected_backend"]="GPU"
                result["fallback_reason"]=""
        if cacheable:_CACHE[key]=dict(result)
        return result
    except Exception as error:
        result={
            "requested_mode":requested,"gpu_detected":False,"cupy_available":False,
            "gpu_analysis_active":False,"selected_backend":"CPU",
            "fallback_reason":f"GPU verification failed: {type(error).__name__}: {error}",
            "benchmark":"failed",
        }
        if cacheable:_CACHE[key]=dict(result)
        return result
