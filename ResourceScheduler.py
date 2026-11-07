"""Adaptive phase scheduler for Image Draw Bot v1.0.44.

This module is pure planning logic: it never touches the mouse, screen or GUI.
It decides which resource profile each planning phase should use and stores a
small per-machine recommendation from the CPU/RAM benchmark.
"""
from __future__ import annotations

import json
import math
import os
import platform
import time
from pathlib import Path
from typing import Any

from RuntimePaths import atomic_write_text, data_dir, is_finite_number, read_json

RESOURCE_SCHEDULER_MODES = ("Auto", "Off", "Benchmark recommendations")
SCHEDULER_FILE = data_dir() / "resource-scheduler-v2.json"


def validate_resource_scheduler(value: str) -> str:
    if value not in RESOURCE_SCHEDULER_MODES:
        raise ValueError("Resource scheduler must be Auto, Off or Benchmark recommendations.")
    return value


def machine_signature(*, logical_cpus: int | None = None, ram_mb: int | None = None) -> str:
    cpus = max(1, int(logical_cpus or (os.cpu_count() or 1)))
    ram_bucket = "unknown" if ram_mb is None else str(max(1, int(ram_mb) // 1024)) + "GB"
    return f"{platform.system() or 'OS'}|{platform.machine() or 'machine'}|cpu{cpus}|ram{ram_bucket}"


def _safe_cap(logical_cpus: int, *, preview: bool = False) -> int:
    total = max(1, int(logical_cpus or 1))
    if total <= 2:
        return 1
    if preview:
        return max(1, min(4, total - 1))
    if total <= 4:
        return total - 1
    if total <= 8:
        return min(6, total - 1)
    if total <= 16:
        return min(10, total - 2)
    if total <= 24:
        return min(12, total - 3)
    # This is the important safety/performance guard: Auto never consumes all
    # 32+ logical CPUs because Tk, Paint and Windows input need headroom and many
    # image-planning tasks slow down beyond the memory/cache sweet spot.
    return min(16, total - 4)


def _requested_workers(requested: str, logical_cpus: int) -> int | None:
    total = max(1, int(logical_cpus or 1))
    if requested == "Auto":
        return None
    if requested == "All logical":
        return total
    try:
        return max(1, min(total, int(str(requested))))
    except (TypeError, ValueError):
        return None


def load_recommendation(path: Path | None = None, *, signature: str | None = None) -> dict[str, Any] | None:
    path = Path(path or SCHEDULER_FILE)
    try:
        data = read_json(path, max_bytes=256 * 1024)
    except (OSError, ValueError, TypeError):
        return None
    if not _valid_recommendation(data):
        return None
    if signature is None:
        from ResourceAllocation import logical_cpu_count
        signature = machine_signature(logical_cpus=logical_cpu_count(), ram_mb=data['ram_budget_mb'])
    sig = signature
    if data.get("machine_signature") != sig:
        return None
    return data


def _valid_recommendation(data):
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 2:
        return False
    for key in ('logical_cpus', 'recommended_workers', 'ram_budget_mb'):
        if type(data.get(key)) is not int or data[key] <= 0:
            return False
    if data['recommended_workers'] > data['logical_cpus'] or data.get('recommended_engine') not in ('Threads', 'Processes', 'Auto'):
        return False
    score = data.get('best_score')
    if not is_finite_number(score) or score < 0:
        return False
    return isinstance(data.get('scores'), list) and isinstance(data.get('machine_signature'), str)


def save_recommendation(result: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    path = Path(path or SCHEDULER_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "version": 2,
        "created_at": int(time.time()),
        "machine_signature": str(result.get("machine_signature") or machine_signature(
            logical_cpus=int(result.get("logical_cpus", os.cpu_count() or 1) or 1),
            ram_mb=result.get("ram_budget_mb"))),
        "logical_cpus": int(result.get("logical_cpus", os.cpu_count() or 1) or 1),
        "recommended_workers": int(result.get("recommended_workers", 1) or 1),
        "recommended_engine": str(result.get("recommended_engine", "Threads")),
        "best_score": float(result.get("best_score", 0.0) or 0.0),
        "scores": result.get("scores", []),
        "ram_budget_mb": int(result.get("ram_budget_mb", 0) or 0),
    }
    if not _valid_recommendation(clean):
        raise ValueError('Invalid resource scheduler recommendation.')
    atomic_write_text(path, json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False))
    return clean


def recommended_workers(allocation: dict[str, Any], *, mode: str = "Auto", preview: bool = False,
                        recommendation: dict[str, Any] | None = None) -> tuple[int, str]:
    validate_resource_scheduler(mode)
    logical = max(1, int(allocation.get("logical_cpus", os.cpu_count() or 1) or 1))
    requested = _requested_workers(str(allocation.get("cpu_workers", "Auto")), logical)
    if mode == "Off":
        # Old behaviour: respect ResourceAllocation's resolved value.
        return max(1, min(logical, int(allocation.get("cpu_workers_resolved", requested or 1) or 1))), "scheduler off"
    if requested is not None:
        if requested >= logical and logical >= 24:
            return max(1, logical - 2), "manual all-logical guarded for UI/input headroom"
        return requested, "manual worker setting"
    cap = _safe_cap(logical, preview=preview)
    rec = recommendation or load_recommendation(signature=machine_signature(logical_cpus=logical, ram_mb=allocation.get("ram_budget_mb")))
    if not isinstance(rec, dict) or type(rec.get('recommended_workers')) is not int or rec['recommended_workers'] <= 0:
        rec = None
    if mode == "Benchmark recommendations" and rec and int(rec.get("recommended_workers", 0) or 0) > 0:
        return max(1, min(cap, int(rec["recommended_workers"]))), "saved per-machine benchmark"
    if rec and int(rec.get("recommended_workers", 0) or 0) > 0:
        # Auto can use saved benchmark, but still keeps the UI/input headroom cap.
        return max(1, min(cap, int(rec["recommended_workers"]))), "auto + saved benchmark cap"
    return cap, "auto safe cap"


\
def memory_pressure_profile(allocation: dict[str, Any]) -> dict[str, Any]:
    budget=max(128,int(allocation.get('ram_budget_mb',512) or 512))
    available=allocation.get('available_ram_mb')
    try:available=int(available) if available is not None else None
    except (TypeError,ValueError,OverflowError):available=None
    if available is None:
        return {'known':False,'level':'unknown','available_ram_mb':None,'ram_budget_mb':budget,
                'worker_scale':1.0,'chunk_scale':1.0,'reason':'live available RAM unavailable'}
    ratio=available/max(1,budget)
    if available>=1536 and ratio>=1.35: level='normal';worker=1.0;chunk=1.0
    elif available>=1024 and ratio>=.95: level='elevated';worker=.80;chunk=.75
    elif available>=640 and ratio>=.55: level='high';worker=.55;chunk=.50
    else: level='critical';worker=.30;chunk=.30
    return {'known':True,'level':level,'available_ram_mb':max(0,available),'ram_budget_mb':budget,
            'available_to_budget_ratio':round(ratio,3),'worker_scale':worker,'chunk_scale':chunk,
            'reason':f'{level} RAM pressure: {max(0,available):,} MB available vs {budget:,} MB planning budget'}


def _apply_memory_pressure_workers(workers: int, pressure: dict[str,Any], *, enabled: bool=True) -> int:
    if not enabled or not pressure.get('known') or pressure.get('level')=='normal':return max(1,int(workers))
    scale=max(.20,min(1.0,float(pressure.get('worker_scale',1.0) or 1.0)))
    return max(1,min(int(workers),int(math.ceil(max(1,int(workers))*scale))))


def phase_workers(base_workers: int, phase: str, *, pixels: int, preview: bool = False) -> int:
    base = max(1, int(base_workers or 1))
    pixels = max(1, int(pixels or 1))
    if preview:
        if pixels < 60_000:
            return 1
        if pixels < 180_000:
            return max(1, min(2, base))
        return max(1, min(4, base))
    if phase == "color_analysis":
        return max(1, min(base, 8 if pixels < 800_000 else 12))
    if phase == "image_matrix":
        return max(1, min(base, 4))
    if phase == "shape_extraction":
        if pixels < 80_000:
            return 1
        if pixels < 260_000:
            return max(1, min(base, 4))
        return max(1, min(base, 12))
    if phase in ("importance_map", "region_scoring", "correction_scoring"):
        if pixels < 80_000:
            return 1
        return max(1, min(base, 4 if pixels < 500_000 else 8))
    if phase == "connected_components":
        if pixels < 100_000:
            return 1
        return max(1, min(base, 4 if pixels < 500_000 else 10))
    if phase == "path_optimization":
        return max(1, min(base, 4))
    return base


def choose_image_matrix_backend(*, gpu_mode: str, gpu_available: bool, pixels: int, preview: bool = False,
                                recommendation: dict[str, Any] | None = None) -> tuple[str, str]:
    requested = str(gpu_mode or "Auto")
    if requested == "CPU":
        return "CPU", "CPU mode selected"
    if preview:
        return "CPU", "preview stays CPU to keep UI cancellable"
    if not gpu_available:
        return "CPU", "CUDA unavailable or untested"
    if int(pixels or 0) < 160_000:
        return "CPU", "image too small for GPU transfer overhead"
    if recommendation and recommendation.get("gpu_matrix_backend") == "CPU":
        return "CPU", "saved benchmark prefers CPU for matrix work"
    return "GPU", "large matrix/resize work benefits from CUDA when available"


def _chunk_hint(height: int, width: int, workers: int, ram_mb: int) -> dict[str, int]:
    from ResourceAllocation import rows_per_chunk
    height=max(1,int(height or 1)); width=max(1,int(width or 1)); workers=max(1,int(workers or 1)); ram_mb=max(128,int(ram_mb or 512))
    rows = rows_per_chunk(height, width, workers=workers, ram_budget_mb=ram_mb)
    chunks = math.ceil(height / rows)
    return {"rows_per_chunk": int(rows), "chunks": int(chunks)}


def resolve_resource_schedule(allocation: dict[str, Any], *, mode: str = "Auto", area: tuple[int, int] | list[int] | None = None,
                              drawing_mode: str = "Smart paths (recommended)", gpu_mode: str = "Auto",
                              gpu_available: bool = False, preview: bool = False,
                              recommendation: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_resource_scheduler(mode)
    try:
        width, height = int(area[0]), int(area[1])  # type: ignore[index]
    except Exception:
        width = height = 1
    width=max(1,width); height=max(1,height); pixels=width*height
    base, reason = recommended_workers(allocation, mode=mode, preview=preview, recommendation=recommendation)
    pressure=memory_pressure_profile(allocation)
    pressure_enabled=(mode!='Off')
    adjusted_base=_apply_memory_pressure_workers(base,pressure,enabled=pressure_enabled)
    if adjusted_base<base:
        reason += f"; {pressure['reason']} reduced workers {base}→{adjusted_base}"
    base=adjusted_base
    ram_mb = int(allocation.get("ram_budget_mb", 512) or 512)
    engine = str(allocation.get("cpu_engine", "Auto"))
    if engine == "Auto":
        engine = "Threads"
    image_backend, image_reason = choose_image_matrix_backend(
        gpu_mode=gpu_mode, gpu_available=bool(gpu_available), pixels=pixels, preview=preview, recommendation=recommendation)
    phases = {}
    for phase in ("color_analysis", "image_matrix", "importance_map", "connected_components", "region_scoring", "shape_extraction", "path_optimization", "correction_scoring"):
        workers = phase_workers(base, phase, pixels=pixels, preview=preview)
        backend = "CPU/SIMD" if phase == "color_analysis" else (image_backend if phase == "image_matrix" else "CPU")
        phase_reason = {
            "color_analysis": "palette/color math stays CPU-cache friendly",
            "image_matrix": image_reason,
            "importance_map": "vector/edge importance scoring uses bounded CPU workers",
            "connected_components": "connected-region labeling scales only above the small-image threshold",
            "region_scoring": "region safety/value scoring is parallel only when workload is large enough",
            "shape_extraction": "parallel CPU chunks for region/shape extraction",
            "path_optimization": "path ordering is CPU-bound and capped to avoid overhead",
            "correction_scoring": "error/correction candidates use bounded workers",
        }[phase]
        phases[phase] = {"backend": backend, "workers": int(workers), "reason": phase_reason}
    chunks = _chunk_hint(height, width, phases["shape_extraction"]["workers"], ram_mb)
    if pressure_enabled and pressure.get('known') and pressure.get('level')!='normal':
        rows=max(1,int(chunks['rows_per_chunk']*float(pressure.get('chunk_scale',1.0) or 1.0)))
        chunks={'rows_per_chunk':rows,'chunks':int(math.ceil(height/max(1,rows)))}
    phases["shape_extraction"].update(chunks)
    # Pixel-accuracy correction/error scoring can use the same verified GPU path on large final workloads.
    if not preview and gpu_mode != 'CPU' and gpu_available and pixels>=160_000:
        phases['correction_scoring']['backend']='GPU/CPU fallback'
        phases['correction_scoring']['reason']='tiled GPU scoring with VRAM recovery; CPU remains authoritative fallback'
    return {
        "version": 2,
        "mode": mode,
        "logical_cpus": int(allocation.get("logical_cpus", os.cpu_count() or 1) or 1),
        "base_workers": int(base),
        "effective_cpu_workers": max(phases["color_analysis"]["workers"], phases["shape_extraction"]["workers"], phases["path_optimization"]["workers"]),
        "recommended_engine": engine,
        "ram_budget_mb": ram_mb,
        "pixels": int(pixels),
        "worker_reason": reason,
        "gpu_available": bool(gpu_available),
        "memory_pressure": pressure,
        "phases": phases,
    }


def _bench_once(workers: int, loops: int, *, cancelled=lambda: False) -> float:
    state=0x12345678 ^ workers
    total=0
    loops=max(1000,int(loops))
    started=time.perf_counter()
    # Single-process deterministic approximation.  It is intentionally quick;
    # the result is used for recommendations, not scientific benchmarking.
    for w in range(max(1,int(workers))):
        local=(state + w*2654435761) & 0xffffffff
        for i in range(loops):
            if i % 1024 == 0 and cancelled():
                raise InterruptedError('Scheduler benchmark cancelled.')
            local=(1664525*local + 1013904223 + i) & 0xffffffff
            total ^= ((local >> 7) * 2246822519) & 0xffffffff
    elapsed=max(time.perf_counter()-started,1e-9)
    return (workers*loops)/elapsed/1_000_000


def benchmark_scheduler(allocation: dict[str, Any], *, loops_per_worker: int = 28_000, save: bool = True,
                        path: Path | None = None, cancelled=lambda: False) -> dict[str, Any]:
    if cancelled():
        raise InterruptedError('Scheduler benchmark cancelled.')
    logical=max(1,int(allocation.get("logical_cpus",os.cpu_count() or 1) or 1))
    cap=_safe_cap(logical)
    candidates=[]
    for value in (1,2,4,6,8,10,12,16,24,32):
        if value<=min(logical,cap) and value not in candidates:
            candidates.append(value)
    if not candidates:
        candidates=[1]
    scores=[]
    for workers in candidates:
        if cancelled():
            raise InterruptedError('Scheduler benchmark cancelled.')
        score=_bench_once(workers, max(1000, int(loops_per_worker)//max(1,workers)),
                          cancelled=cancelled)
        # Penalize very high worker counts slightly to represent GUI/input headroom.
        headroom_penalty = 1.0 - min(0.18, max(0, workers - 8) * 0.012)
        adjusted = score * headroom_penalty
        scores.append({"workers": workers, "score": round(score, 3), "adjusted_score": round(adjusted, 3)})
    best=max(scores, key=lambda item:(item["adjusted_score"], -item["workers"]))
    result={
        "version": 2,
        "machine_signature": machine_signature(logical_cpus=logical, ram_mb=allocation.get("ram_budget_mb")),
        "logical_cpus": logical,
        "ram_budget_mb": int(allocation.get("ram_budget_mb",0) or 0),
        "recommended_workers": int(best["workers"]),
        "recommended_engine": "Threads" if str(allocation.get("cpu_engine","Auto"))=="Auto" else str(allocation.get("cpu_engine","Threads")),
        "best_score": float(best["adjusted_score"]),
        "scores": scores,
    }
    if cancelled():
        raise InterruptedError('Scheduler benchmark cancelled.')
    if save:
        save_recommendation(result,path=path)
    return result
