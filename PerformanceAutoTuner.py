"""Local performance auto tuner for Image Draw Bot v1.0.60-beta.

The tuner benchmarks planning resources only. It never arms mouse input and it
never contacts a network service. Results are stored locally in app data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from RuntimePaths import atomic_write_text, data_dir, is_finite_number, read_json
from ResourceAllocation import available_ram_mb, logical_cpu_count, resolve_allocation
from ResourceScheduler import benchmark_scheduler
from UniversalHardwareBenchmark import (run_universal_hardware_benchmark, load_hardware_profile,
                                        format_hardware_summary as format_universal_hardware_summary)

TUNER_VERSION = 1
TUNER_FILE = data_dir() / "performance-auto-tuner-v1.json"


def _benchmark_payload(value):
    """Keep optional driver results JSON-safe before recommendation or storage."""
    if not isinstance(value, dict):
        raise ValueError('Benchmark result must be an object.')
    try:
        text = json.dumps(value, allow_nan=False)
        if len(text) > 4 * 1024 * 1024:
            raise ValueError('Benchmark result is too large.')
        return json.loads(text)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError('Benchmark result contains invalid metadata.') from error


def _positive_integer(value):
    return value if type(value) is int and 0 < value <= 1_000_000_000 else None


def _nonnegative_number(value, default=0.0):
    return float(value) if is_finite_number(value) and value >= 0 else default


@dataclass(frozen=True)
class TuneRecommendation:
    cpu_workers: str
    cpu_workers_effective: int
    cpu_engine: str
    ram_budget: str
    ram_custom_mb: str
    planning_resolution: str
    resource_scheduler: str
    gpu_mode: str
    gpu_vram: str
    gpu_performance: str
    gpu_available: bool
    gpu_detected: bool
    gpu_device: str
    gpu_driver_version: str
    gpu_reason: str
    cpu_score: float
    gpu_throughput_mp_s: float
    logical_cpus: int
    available_ram_mb: int | None
    reason: str
    hardware_profile_signature: str = ""
    universal_gpu_detected: bool = False
    primary_compute_backend: str = "CPU/NumPy"
    primary_compute_vendor: str = "CPU"
    primary_compute_device: str = "CPU"
    safe_gpu_memory_mb: int | None = None
    hardware_tile_size: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ram_recommendation(available_mb: int | None) -> tuple[str, str, int]:
    """Return UI setting, custom value and resolved budget.

    Leave substantial memory for Windows, the target app and preview images.
    """
    if available_mb is None:
        return "2 GB", "2048", 2048
    if available_mb < 128:
        raise ValueError('Less than 128 MB of RAM is available for planning.')
    if available_mb < 512:
        return 'Custom', str(int(available_mb)), int(available_mb)
    avail = max(512, int(available_mb))
    target = max(512, min(12288, int(avail * 0.35)))
    # Keep at least 2 GiB of currently available memory unreserved when possible.
    target = min(target, max(512, avail - 2048))
    fixed = (
        (512, "512 MB"), (1024, "1 GB"), (2048, "2 GB"), (4096, "4 GB"),
        (8192, "8 GB"), (12288, "12 GB"), (16384, "16 GB"),
    )
    # Prefer a fixed UI value when it is within 12.5% of the target.
    nearest_mb, nearest_label = min(fixed, key=lambda item: abs(item[0] - target))
    if abs(nearest_mb - target) <= max(256, int(target * 0.125)) and nearest_mb <= max(512, avail - 1024):
        return nearest_label, str(nearest_mb), nearest_mb
    return "Custom", str(target), target


def _vram_recommendation(total_mb: int | None, free_mb: int | None) -> str:
    if not _positive_integer(total_mb) or not _positive_integer(free_mb) or free_mb > total_mb:
        return "Auto"
    total, free = int(total_mb), int(free_mb)
    # Use percentages so the setting remains sane after driver/desktop changes.
    if total >= 12288 and free >= int(total * 0.80):
        return "75%"
    if total >= 6144 and free >= int(total * 0.65):
        return "50%"
    return "Auto"


def _planning_resolution(workers: int, ram_mb: int, gpu_ok: bool, gpu_mp_s: float) -> str:
    workers = max(1, int(workers))
    ram_mb = max(128, int(ram_mb))
    if gpu_ok and gpu_mp_s >= 6.0 and workers >= 12 and ram_mb >= 8192:
        return "Extreme"
    if workers >= 10 and ram_mb >= 6144:
        return "Ultra"
    if workers >= 6 and ram_mb >= 3072:
        return "High"
    return "Standard"


def _reason_text(*, workers: int, ram_mb: int, gpu_ok: bool, planning: str) -> str:
    gpu = "CUDA enabled" if gpu_ok else "CPU fallback"
    return f"{workers} benchmark-selected planning workers, {ram_mb:,} MB RAM budget, {gpu}, {planning} planning."


def build_recommendation(*, scheduler_result: dict[str, Any], available_mb: int | None,
                         gpu_result: dict[str, Any] | None = None,
                         hardware_result: dict[str, Any] | None = None) -> TuneRecommendation:
    scheduler_result = scheduler_result if isinstance(scheduler_result, dict) else {}
    logical = _positive_integer(scheduler_result.get('logical_cpus')) or logical_cpu_count()
    workers = min(logical, _positive_integer(scheduler_result.get('recommended_workers')) or 1)
    ram_setting, ram_custom, ram_mb = _ram_recommendation(available_mb)
    try: gpu = _benchmark_payload(gpu_result or {})
    except ValueError: gpu = {}
    gpu_mp_s = _nonnegative_number(gpu.get('throughput_mp_s'))
    gpu_ok = gpu.get('used_gpu') is True and gpu.get('accelerated', True) is True and gpu_mp_s > 0
    gpu_detected = gpu.get('hardware_detected') is True or gpu_ok
    try: hardware = _benchmark_payload(hardware_result or {})
    except ValueError: hardware = {}
    adapters = hardware.get('detected_gpus')
    detected_adapters = [item for item in adapters if isinstance(item, dict)] if isinstance(adapters, list) else []
    primary = hardware.get('primary_backend')
    primary = primary if isinstance(primary, dict) else {}
    universal_gpu_detected = bool(detected_adapters)
    primary_backend = str(primary.get("backend") or "CPU/NumPy")
    primary_vendor = str(primary.get("vendor") or "CPU")
    primary_device = str(primary.get("device") or "CPU")
    safe_gpu_memory = primary.get("safe_memory_budget_mb")
    hardware_tile = primary.get("tile_size")
    gpu_mode = "NVIDIA CUDA" if gpu_ok else "CPU"
    gpu_vram = _vram_recommendation(gpu.get("total_vram_mb"), gpu.get("free_vram_mb")) if gpu_ok else "Auto"
    gpu_perf = "High throughput" if gpu_ok else "Balanced"
    planning = _planning_resolution(workers, ram_mb, gpu_ok, gpu_mp_s)
    return TuneRecommendation(
        cpu_workers="Auto",
        cpu_workers_effective=workers,
        cpu_engine="Threads",
        ram_budget=ram_setting,
        ram_custom_mb=ram_custom,
        planning_resolution=planning,
        resource_scheduler="Benchmark recommendations",
        gpu_mode=gpu_mode,
        gpu_vram=gpu_vram,
        gpu_performance=gpu_perf,
        gpu_available=gpu_ok,
        gpu_detected=gpu_detected,
        gpu_device=str(gpu.get("hardware_device") or gpu.get("device") or ("CPU" if not gpu_detected else "NVIDIA GPU")),
        gpu_driver_version=str(gpu.get("driver_version") or ""),
        gpu_reason=str(gpu.get("reason") or ""),
        cpu_score=_nonnegative_number(scheduler_result.get('best_score')),
        gpu_throughput_mp_s=gpu_mp_s,
        logical_cpus=logical,
        available_ram_mb=available_mb,
        reason=_reason_text(workers=workers, ram_mb=ram_mb, gpu_ok=gpu_ok, planning=planning) +
               (f" Hardware benchmark prefers {primary_backend} on {primary_device}." if hardware else ""),
        hardware_profile_signature=str(hardware.get("hardware_signature") or ""),
        universal_gpu_detected=universal_gpu_detected,
        primary_compute_backend=primary_backend,
        primary_compute_vendor=primary_vendor,
        primary_compute_device=primary_device,
        safe_gpu_memory_mb=_positive_integer(safe_gpu_memory),
        hardware_tile_size=_positive_integer(hardware_tile),
    )


def run_auto_tune(*, gpu_benchmark: Callable[..., dict[str, Any]] | None = None,
                  save: bool = True, path: Path | None = None,
                  scheduler_loops: int = 56_000, gpu_size: int = 768) -> dict[str, Any]:
    """Benchmark the machine and return a safe planning recommendation.

    gpu_benchmark is injected by DrawBot to keep this module testable on systems
    without CUDA/CuPy.
    """
    started = time.perf_counter()
    logical = logical_cpu_count()
    available = available_ram_mb()
    allocation = resolve_allocation("Auto", "Threads", "Auto", "4096")
    scheduler = benchmark_scheduler(allocation, loops_per_worker=max(8_000, int(scheduler_loops)), save=save)

    gpu_result: dict[str, Any] = {}
    gpu_error = ""
    if gpu_benchmark is not None:
        try:
            gpu_result = _benchmark_payload(gpu_benchmark("Auto", max(256, int(gpu_size)), "Auto", "High throughput") or {})
        except InterruptedError:
            raise
        except Exception as exc:  # CUDA is optional; fail safely to CPU.
            gpu_error = f"{type(exc).__name__}: {exc}"
            gpu_result = {"used_gpu": False, "accelerated": False, "device": "CPU", "reason": gpu_error}

    hardware_result: dict[str, Any] = {}
    hardware_error = ""
    try:
        hardware_result = _benchmark_payload(run_universal_hardware_benchmark(
            save=save, small_size=128, large_size=max(256, min(768, int(gpu_size))), repeats=2, refresh_hardware=True))
    except InterruptedError:
        raise
    except Exception as exc:
        # The tuner must remain fully usable on CPU if an optional GPU runtime
        # or vendor driver misbehaves.
        hardware_error = f"{type(exc).__name__}: {exc}"
        try:
            hardware_result = _benchmark_payload(load_hardware_profile(validate_current=True) or {})
        except InterruptedError:
            raise
        except Exception:
            hardware_result = {}

    recommendation = build_recommendation(
        scheduler_result=scheduler,
        available_mb=available,
        gpu_result=gpu_result,
        hardware_result=hardware_result,
    )
    result: dict[str, Any] = {
        "version": TUNER_VERSION,
        "created_at": int(time.time()),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "recommendation": recommendation.as_dict(),
        "cpu_scores": scheduler.get("scores", []),
        "gpu_result": gpu_result,
        "gpu_error": gpu_error,
        "hardware_profile": hardware_result,
        "hardware_error": hardware_error,
    }
    if save:
        save_tune_result(result, path=path)
    return result


def save_tune_result(result: dict[str, Any], path: Path | None = None) -> Path:
    target = Path(path or TUNER_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return target


def load_tune_result(path: Path | None = None) -> dict[str, Any] | None:
    target = Path(path or TUNER_FILE)
    try:
        value = read_json(target)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != TUNER_VERSION:
        return None
    if not isinstance(value.get("recommendation"), dict):
        return None
    rec = value['recommendation']
    logical = rec.get('logical_cpus')
    workers = rec.get('cpu_workers_effective')
    if type(logical) is not int or type(workers) is not int or not 1 <= workers <= logical:
        return None
    if 'gpu_available' in rec and type(rec['gpu_available']) is not bool:
        return None
    elapsed = value.get('elapsed_ms', 0.0)
    if not is_finite_number(elapsed) or elapsed < 0:
        return None
    from ResourceAllocation import CPU_ENGINE_MODES, CPU_WORKER_CHOICES, PLANNING_RESOLUTION_MODES, RAM_BUDGETS
    for key, choices in (('cpu_engine', CPU_ENGINE_MODES), ('cpu_workers', CPU_WORKER_CHOICES),
                         ('planning_resolution', PLANNING_RESOLUTION_MODES), ('ram_budget', RAM_BUDGETS)):
        if key in rec and rec[key] not in choices:
            return None
    return value


def format_tune_summary(result: dict[str, Any]) -> str:
    rec = dict(result.get("recommendation") or {})
    if rec.get("gpu_available"):
        renderer_gpu = str(rec.get("gpu_device") or "NVIDIA CUDA GPU")
    elif rec.get("gpu_detected"):
        renderer_gpu = f"{rec.get('gpu_device') or 'NVIDIA GPU'} detected · CUDA backend unavailable"
    else:
        renderer_gpu = "CPU renderer fallback"
    compute = str(rec.get("primary_compute_backend") or "CPU/NumPy")
    compute_device = str(rec.get("primary_compute_device") or "CPU")
    universal = f"{compute} on {compute_device}" if compute != "CPU/NumPy" else "CPU/NumPy"
    return (
        f"CPU {int(rec.get('cpu_workers_effective', 1) or 1)}/{int(rec.get('logical_cpus', 1) or 1)} workers · "
        f"RAM {rec.get('ram_budget', 'Auto')} · current renderer {renderer_gpu} · measured compute {universal} · "
        f"Planner {rec.get('planning_resolution', 'Standard')} · {float(result.get('elapsed_ms', 0.0) or 0.0):.0f} ms"
    )
