"""CPU/GPU/RAM resource allocation helpers for Image Draw Bot v1.0.13.

The drawing cursor itself is deliberately single-stream: a target application can
only receive one mouse path at a time.  This module controls the heavy planning
phase around that safety boundary: CPU worker count, thread/process strategy,
RAM chunking and runtime library thread hints.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from collections import deque
import math
import os
import sys
from typing import Callable, Iterable, Sequence, TypeVar
from pathlib import Path

CPU_WORKER_CHOICES = ("Auto", "1", "2", "4", "6", "8", "12", "16", "24", "32", "All logical")
CPU_ENGINE_MODES = ("Auto", "Threads", "Processes")
RAM_BUDGETS = ("Auto", "512 MB", "1 GB", "2 GB", "4 GB", "8 GB", "12 GB", "16 GB", "Custom")
PLANNING_RESOLUTION_MODES = ("Auto", "Standard", "High", "Ultra", "Extreme")

_T = TypeVar("_T")
_U = TypeVar("_U")
_MIB = 1024 * 1024
_PROBE = object()


def logical_cpu_count() -> int:
    try:
        probe = getattr(os, 'process_cpu_count', None)
        if probe is not None and (count := probe()) is not None:
            return max(1, int(count))
        affinity = getattr(os, 'sched_getaffinity', None)
        if affinity is not None:
            return max(1, len(affinity(0)))
    except (OSError, ValueError, TypeError):
        pass
    return max(1, int(os.cpu_count() or 1))


def available_ram_mb() -> int | None:
    """Best-effort available RAM in MiB without adding dependencies."""
    if sys.platform == "win32":
        try:
            from WindowsSystem import physical_memory_bytes
            _total, available = physical_memory_bytes()
            return available // _MIB
        except Exception:
            return None
    if sys.platform.startswith('linux'):
        try:
            with Path('/proc/meminfo').open('r', encoding='ascii') as stream:
                for line in stream:
                    fields = line.split()
                    if len(fields) == 3 and fields[0] == 'MemAvailable:' and fields[2] == 'kB':
                        return max(0, int(fields[1]) // 1024)
        except (OSError, ValueError, UnicodeError):
            pass
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return max(0, int((pages * page_size) // _MIB))
    except (AttributeError, OSError, ValueError):
        return None


def validate_cpu_workers(value: str) -> str:
    if value not in CPU_WORKER_CHOICES:
        raise ValueError("CPU workers must be Auto, a supported number, or All logical.")
    return value


def validate_cpu_engine(value: str) -> str:
    if value not in CPU_ENGINE_MODES:
        raise ValueError("CPU engine must be Auto, Threads, or Processes.")
    return value


def validate_ram_budget(value: str) -> str:
    if value not in RAM_BUDGETS:
        raise ValueError("RAM budget must be Auto, a supported size, or Custom.")
    return value


def validate_planning_resolution(value: str) -> str:
    if value not in PLANNING_RESOLUTION_MODES:
        raise ValueError("Planning resolution must be Auto, Standard, High, Ultra, or Extreme.")
    return value


def parse_custom_ram_mb(value: str | int | None) -> int:
    try:
        mb = int(str(value or "").strip())
    except (TypeError, ValueError):
        raise ValueError("Custom RAM budget must be a whole number in MB.") from None
    if not 128 <= mb <= 65536:
        raise ValueError("Custom RAM budget must be 128–65536 MB.")
    return mb


def resolve_cpu_workers(value: str = "Auto", *, logical_cpus: int | None = None) -> int:
    validate_cpu_workers(value)
    total = logical_cpu_count() if logical_cpus is None else max(1, int(logical_cpus))
    if value == "Auto":
        # Safe default for a GUI app: enough workers to use the CPU, but not 31+
        # Windows worker processes/threads that can starve Tk, Paint and input.
        # Users can still choose All logical when they intentionally want it.
        if total <= 4:
            return max(1, total - 1 if total > 1 else 1)
        return max(2, min(8, total - 2))
    if value == "All logical":
        return total
    return max(1, min(int(value), total))


def resolve_ram_budget_mb(value: str = "Auto", custom_mb: str | int | None = None, *, available_mb=_PROBE) -> int:
    validate_ram_budget(value)
    available = available_ram_mb() if available_mb is _PROBE else available_mb
    if available is not None and available < 128:
        raise ValueError('Less than 128 MB of RAM is available. Free memory before planning an image.')
    if value == "Custom":
        requested = parse_custom_ram_mb(custom_mb)
    elif value == "Auto":
        if available is None:
            requested = 2048
        else:
            requested = max(512, min(8192, int(available * 0.35)))
    elif value.endswith("MB"):
        requested = int(value.split()[0])
    else:
        requested = int(value.split()[0]) * 1024
    if available is not None:
        # Never reserve the last chunk of system RAM for planning. Users can pick
        # Custom when they intentionally want a tighter/larger cap.
        safe = max(128, available - 512)
        requested = min(requested, safe)
    return max(128, int(requested))


def configure_runtime(cpu_workers: int) -> None:
    """Apply thread-count hints for numeric libraries used by Pillow/CuPy stacks."""
    workers = max(1, int(cpu_workers))
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[key] = str(workers)
    os.environ.setdefault("PYTHONHASHSEED", "0")


def resolve_allocation(cpu_workers: str = "Auto", cpu_engine: str = "Auto",
                       ram_budget: str = "Auto", custom_ram_mb: str | int | None = None) -> dict:
    validate_cpu_engine(cpu_engine)
    logical = logical_cpu_count()
    available = available_ram_mb()
    workers = resolve_cpu_workers(cpu_workers, logical_cpus=logical)
    ram_mb = resolve_ram_budget_mb(ram_budget, custom_ram_mb, available_mb=available)
    configure_runtime(workers)
    return {
        "cpu_workers": cpu_workers, "cpu_workers_resolved": workers,
        "cpu_engine": cpu_engine, "ram_budget": ram_budget,
        "ram_budget_mb": ram_mb, "available_ram_mb": available,
        "logical_cpus": logical,
    }


def row_chunk_ranges(height: int, width: int, *, workers: int, ram_budget_mb: int,
                     bytes_per_pixel: int = 64, min_rows: int = 8, max_rows: int = 256) -> list[tuple[int, int]]:
    height = max(0, int(height)); width = max(1, int(width))
    if height == 0:
        return []
    rows = rows_per_chunk(height, width, workers=workers, ram_budget_mb=ram_budget_mb,
                          bytes_per_pixel=bytes_per_pixel, min_rows=min_rows, max_rows=max_rows)
    return [(start, min(height, start + rows)) for start in range(0, height, rows)]


def rows_per_chunk(height: int, width: int, *, workers: int, ram_budget_mb: int,
                   bytes_per_pixel: int = 64, min_rows: int = 8, max_rows: int = 256) -> int:
    height = max(1, int(height)); width = max(1, int(width))
    workers = max(1, int(workers)); ram_budget_mb = max(128, int(ram_budget_mb))
    # Keep several waves of tasks queued so CPU workers do not starve. The RAM
    # budget still caps chunk size for very wide images and layered colour modes.
    per_task_budget = max(1, (ram_budget_mb * _MIB) // max(2, workers * 4))
    memory_rows = per_task_budget // (width * max(8, int(bytes_per_pixel)))
    if memory_rows < 1:
        raise ValueError('One image row exceeds the per-worker memory budget. Reduce workers or image width.')
    rows = max(1, min(max(1, int(max_rows)), memory_rows))
    # Avoid a single oversized final chunk by targeting at least worker*2 chunks
    # for medium/large plans.
    target_chunks = max(1, workers * 2)
    if height // rows < target_chunks:
        rows = min(rows, max(max(1, int(min_rows)), math.ceil(height / target_chunks)))
    return rows


def choose_parallel_backend(engine: str, *, width: int, height: int, workers: int,
                            ram_budget_mb: int, preview: bool = False) -> str:
    validate_cpu_engine(engine)
    pixels = max(1, int(width)) * max(1, int(height))
    if workers <= 1 or pixels < 48_000:
        return "serial"
    if engine == "Threads":
        return "threads"
    if engine == "Processes":
        return "processes"
    # Auto must stay GUI-safe. Windows ProcessPool startup from the drawing
    # worker can look like a freeze and can ignore cancellation until spawn/import
    # completes. Processes remain available only when the user explicitly chooses
    # CPU engine = Processes.
    return "threads"



def _legacy_sample_limit(detail: int) -> float:
    return 200.0 / (11 - max(1, min(10, int(detail))))


def resolve_planning_limits(detail: int, area: tuple[int, int] | list[int] | None, *,
                            planning_resolution: str = "Auto", cpu_workers: int = 1,
                            ram_budget_mb: int = 512, preview: bool = False) -> dict:
    """Return image-planning resolution caps driven by CPU/RAM settings.

    Older Image Draw Bot builds always capped planning to roughly 40-200 pixels on
    the long edge depending on detail.  That is fast, but it gives modern CPUs
    and GPUs almost nothing to do.  This helper keeps Standard identical while
    letting High/Ultra/Extreme build larger source plans when the user allocates
    more CPU workers and RAM.
    """
    validate_planning_resolution(planning_resolution)
    width = height = 1
    try:
        width, height = int(area[0]), int(area[1])  # type: ignore[index]
    except Exception:
        pass
    width = max(1, width); height = max(1, height)
    workers = max(1, int(cpu_workers or 1))
    ram_mb = max(128, int(ram_budget_mb or 512))
    legacy = _legacy_sample_limit(detail)
    mode = planning_resolution
    if mode == "Auto":
        if preview:
            mode = "Standard"
        elif workers >= 12 and ram_mb >= 8192:
            mode = "Ultra"
        elif workers >= 6 and ram_mb >= 4096:
            mode = "High"
        else:
            mode = "Standard"
    multipliers = {"Standard": 1.0, "High": 2.25, "Ultra": 3.5, "Extreme": 5.25}
    hard_dims = {"Standard": int(round(legacy)), "High": 480, "Ultra": 760, "Extreme": 1100}
    hard_pixels = {"Standard": 75_000, "High": 220_000, "Ultra": 520_000, "Extreme": 1_100_000}
    if preview:
        # Manual/Auto preview must stay responsive even when final planning is
        # configured for a heavy high-resolution pass.
        hard_dims = {"Standard": int(round(legacy)), "High": 340, "Ultra": 440, "Extreme": 560}
        hard_pixels = {"Standard": 60_000, "High": 130_000, "Ultra": 220_000, "Extreme": 330_000}
    ram_pixels = max(25_000, int((ram_mb * _MIB) / 96))
    worker_pixels = max(25_000, workers * 95_000)
    max_pixels = min(width * height, hard_pixels[mode], ram_pixels, worker_pixels)
    if mode == "Standard":
        sample_limit = legacy
    else:
        sample_limit = min(max(width, height), max(8.0, legacy * multipliers[mode], float(hard_dims[mode])))
    # For very wide/large targets, max_pixels is the real cap.  sample_limit keeps
    # smaller canvases from being upscaled beyond the selected drawing area.
    return {
        "planning_resolution": planning_resolution,
        "planning_resolution_effective": mode,
        "planner_legacy_sample_limit": int(round(legacy)),
        "planner_sample_limit": int(round(sample_limit)),
        "planner_max_pixels": int(max_pixels),
        "planner_preview": bool(preview),
    }


def _resource_benchmark_worker(task: tuple[int, int]) -> int:
    task_id, loops = task
    state = (task_id + 1) * 2654435761 & 0xffffffff
    total = 0
    for i in range(max(1, int(loops))):
        state = (1664525 * state + 1013904223 + i) & 0xffffffff
        total ^= ((state >> 7) * 2246822519) & 0xffffffff
    return total


def benchmark_allocation(cpu_workers: str = "Auto", cpu_engine: str = "Auto",
                         ram_budget: str = "Auto", custom_ram_mb: str | int | None = None,
                         *, loops_per_worker: int = 220_000,
                         cancelled: Callable[[], bool] | None = None) -> dict:
    """Run a short deterministic CPU scheduling test for the selected allocation."""
    if cancelled is not None and cancelled():
        raise InterruptedError('Resource benchmark cancelled.')
    allocation = resolve_allocation(cpu_workers, cpu_engine, ram_budget, custom_ram_mb)
    workers = max(1, int(allocation["cpu_workers_resolved"]))
    backend = choose_parallel_backend(allocation["cpu_engine"], width=900, height=900,
                                      workers=workers, ram_budget_mb=allocation["ram_budget_mb"],
                                      preview=False)
    started = __import__("time").perf_counter()
    tasks = [(i, loops_per_worker) for i in range(workers)]
    results = parallel_map(_resource_benchmark_worker, tasks, backend=backend, workers=workers,
                           cancelled=cancelled)
    elapsed = max(__import__("time").perf_counter() - started, 1e-9)
    checksum = 0
    for value in results:
        checksum ^= int(value)
    if cancelled is not None and cancelled():
        raise InterruptedError('Resource benchmark cancelled.')
    return {**allocation, "benchmark_backend": backend, "benchmark_elapsed_ms": round(elapsed * 1000, 1),
            "benchmark_tasks": len(tasks), "benchmark_score": round((loops_per_worker * len(tasks)) / elapsed / 1_000_000, 2),
            "benchmark_checksum": checksum}


def parallel_map(function: Callable[[_T], _U], tasks: Sequence[_T], *, backend: str, workers: int,
                 cancelled: Callable[[], bool] | None = None) -> list[_U]:
    """Ordered, bounded submission with cooperative cancellation while waiting.

    Queued work is cancelled promptly; already-running tasks finish during
    executor shutdown. This does not attempt to kill native worker threads.
    """
    def check_cancelled():
        if cancelled is not None and cancelled():
            raise InterruptedError('Parallel planning cancelled.')
    check_cancelled()
    if backend == "serial" or workers <= 1 or len(tasks) <= 1:
        result = []
        for task in tasks:
            check_cancelled()
            result.append(function(task))
            check_cancelled()
        return result
    executor_cls = ProcessPoolExecutor if backend == "processes" else ThreadPoolExecutor
    workers = min(len(tasks), max(1, int(workers)))
    if backend == 'processes' and sys.platform == 'win32':
        workers = min(workers, 61)
    pending = deque()
    iterator = iter(tasks)
    result = []
    current = None
    with executor_cls(max_workers=workers) as executor:
        try:
            for _ in range(workers * 2):
                check_cancelled()
                try:
                    task = next(iterator)
                except StopIteration:
                    break
                pending.append(executor.submit(function, task))
            while pending:
                check_cancelled()
                current = pending.popleft()
                if cancelled is None:
                    value = current.result()
                else:
                    while True:
                        check_cancelled()
                        try:
                            value = current.result(timeout=.05)
                            break
                        except TimeoutError:
                            # A worker can itself raise TimeoutError; do not
                            # mistake it for a wait timeout. A successful task
                            # can also finish between result() timing out and
                            # done(): collect that result instead of promoting
                            # the expired poll into an operation failure.
                            if current.done():
                                value = current.result()
                                break
                current = None
                check_cancelled()
                result.append(value)
                try:
                    task = next(iterator)
                except StopIteration:
                    continue
                pending.append(executor.submit(function, task))
        finally:
            if current is not None and cancelled is not None:
                current.cancel()
            for future in pending:
                future.cancel()
    return result
