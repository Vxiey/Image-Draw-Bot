"""Vendor-neutral GPU hardware discovery for Image Draw Bot.

Step 22 expands the original NVIDIA-only probe so the hardware auto tuner can
see NVIDIA, AMD and Intel adapters without assuming CUDA == GPU.  Discovery is
kept independent from optional compute packages: a GPU can be reported even
when CUDA/OpenCL is not installed.  Existing NVIDIA helper APIs remain for
backwards compatibility with the CUDA renderer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
from typing import Iterable

from WindowsGpuDiscovery import enumerate_adapters as _windows_adapters
from WindowsSystem import program_files_directories, system_directory


@dataclass(frozen=True)
class NvidiaGpu:
    # Keep field order stable: older tests/callers construct this positionally.
    index: int | None
    name: str
    memory_total_mb: int | None = None
    driver_version: str = ""
    bus_id: str = ""
    source: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GpuDevice:
    index: int | None
    name: str
    memory_total_mb: int | None = None
    driver_version: str = ""
    bus_id: str = ""
    source: str = ""
    vendor: str = "Unknown"
    vendor_id: str = ""
    pnp_device_id: str = ""
    video_processor: str = ""
    integrated: bool | None = None

    def as_dict(self) -> dict:
        return asdict(self)


_CACHE: tuple[NvidiaGpu, ...] | None = None
_ALL_CACHE: tuple[GpuDevice, ...] | None = None
_CACHE_LOCK = threading.RLock()


def _creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _run(command: list[str], timeout: float = 3.0) -> str:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_creationflags(),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or f"exit {completed.returncode}").strip())
    return completed.stdout.strip()


def _nvidia_smi_candidates() -> Iterable[str]:
    if os.name != "nt":
        found = shutil.which("nvidia-smi")
        if found:
            yield found
        return

    # Resolve trusted OS/vendor install locations through Windows APIs. PATH,
    # the current directory, and environment-overridden Windows/Program Files
    # paths must not choose the executable used for this background probe.
    candidates = []
    try:
        candidates.append(system_directory() / "nvidia-smi.exe")
    except OSError:
        pass
    try:
        candidates.extend(path / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"
                          for path in program_files_directories())
    except OSError:
        pass
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).replace("/", "\\").casefold()
        try:
            available = candidate.is_file()
        except OSError:
            available = False
        if key not in seen and available:
            seen.add(key)
            yield str(candidate)


def _parse_int(value: object) -> int | None:
    try:
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            number = float(text)
            return int(number) if math.isfinite(number) and number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def _smi_text(value: str) -> str:
    text = value.strip()
    return "" if text.casefold() in {"n/a", "[n/a]", "not supported", "[not supported]"} else text


def _vendor_from_text(*values: object) -> tuple[str, str]:
    text = " ".join(str(value or "") for value in values).lower()
    if "ven_10de" in text or "nvidia" in text or "geforce" in text or "quadro" in text:
        return "NVIDIA", "10DE"
    if "ven_1002" in text or "advanced micro devices" in text or "radeon" in text or re.search(r"\bamd\b", text):
        return "AMD", "1002"
    if "ven_8086" in text or "intel" in text or "arc(tm)" in text:
        return "Intel", "8086"
    return "Unknown", ""


def _detect_with_nvidia_smi() -> list[NvidiaGpu]:
    for executable in _nvidia_smi_candidates():
        try:
            output = _run([
                executable,
                "--query-gpu=index,name,memory.total,driver_version,pci.bus_id",
                "--format=csv,noheader,nounits",
            ])
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            continue
        result: list[NvidiaGpu] = []
        try:
            for parts in csv.reader(io.StringIO(output), skipinitialspace=True, strict=True):
                if len(parts) != 5:
                    continue
                raw_index, name, raw_memory, driver, bus = map(_smi_text, parts)
                index, memory = _parse_int(raw_index), _parse_int(raw_memory)
                if index is None or index < 0 or not name:
                    continue
                memory = memory if memory is not None and memory > 0 else None
                result.append(NvidiaGpu(index, name, memory, driver, bus, "nvidia-smi"))
        except csv.Error:
            # Keep any complete rows read before malformed diagnostic output.
            pass
        if result:
            return result
    return []


def _detect_all_with_windows() -> list[GpuDevice]:
    """Best-effort native display discovery, independent of compute runtimes."""
    if os.name != "nt":
        return []
    try:
        adapters = _windows_adapters()
    except (OSError, AttributeError):
        return []
    result: list[GpuDevice] = []
    vendors = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}
    for adapter in adapters:
        name = adapter.name
        vendor = vendors.get(adapter.vendor_id)
        if vendor is None:
            vendor, _ = _vendor_from_text(name)
        vendor_id = f"{adapter.vendor_id:04X}" if adapter.vendor_id else ""
        memory_mb = adapter.dedicated_video_memory // (1024 * 1024) or None
        integrated: bool | None = None
        lower = re.sub(r"\([^)]*\)", " ", name.lower())
        lower = " ".join(lower.split())
        if vendor == "Intel":
            integrated = not (re.search(r"\barc\s+(?:pro\s+)?[ab]\d", lower)
                              or any(token in lower for token in ("max graphics", "data center gpu")))
        elif any(token in lower for token in ("integrated", "apu", "vega 7", "vega 8")):
            integrated = True
        # DXGI does not expose PCI bus or PNP instance IDs. Keep those fields
        # empty instead of treating a boot-local LUID as a persistent bus ID.
        result.append(GpuDevice(
            adapter.index, name, memory_mb, adapter.driver_version,
            "", "Windows DXGI", vendor, vendor_id, "", "", bool(integrated) if integrated is not None else None,
        ))
    return result


def _detect_with_windows() -> list[NvidiaGpu]:
    # A DXGI ordinal is not a CUDA device index. Preserve the unknown-index
    # contract of the old Windows fallback for CUDA-specific callers.
    return [NvidiaGpu(None, gpu.name, gpu.memory_total_mb, gpu.driver_version, "", gpu.source)
            for gpu in _detect_all_with_windows() if gpu.vendor == "NVIDIA"]


def _detect_all_with_lspci() -> list[GpuDevice]:
    """Best-effort non-Windows discovery used by tests/development builds."""
    if os.name == "nt":
        return []
    executable = shutil.which("lspci")
    if not executable:
        return []
    try:
        output = _run([executable, "-nn"], timeout=3.0)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return []
    result: list[GpuDevice] = []
    for line in output.splitlines():
        low = line.lower()
        if not any(token in low for token in ("vga compatible controller", "3d controller", "display controller")):
            continue
        vendor, vendor_id = _vendor_from_text(line)
        name = line.split(": ", 1)[-1].strip()
        bus_id = line.split(" ", 1)[0].strip()
        result.append(GpuDevice(len(result), name, None, "", bus_id, "lspci", vendor, vendor_id))
    return result


def _cached_nvidia_gpus(*, refresh: bool, windows_fallback: list[GpuDevice] | None = None) -> tuple[NvidiaGpu, ...]:
    global _CACHE, _ALL_CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    found = _detect_with_nvidia_smi()
    if not found:
        if windows_fallback is None:
            found = _detect_with_windows()
        else:
            found = [NvidiaGpu(None, gpu.name, gpu.memory_total_mb, gpu.driver_version, "", gpu.source)
                     for gpu in windows_fallback if gpu.vendor == "NVIDIA"]
    found.sort(key=lambda gpu: (gpu.index is None, gpu.index if gpu.index is not None else 9999,
                                -(gpu.memory_total_mb or 0), gpu.name.lower()))
    _CACHE = tuple(found)
    # A direct NVIDIA refresh must not leave detect_gpus() returning an older
    # merged snapshot. detect_gpus() publishes its new snapshot after this call.
    _ALL_CACHE = None
    return _CACHE


def detect_nvidia_gpus(*, refresh: bool = False) -> tuple[NvidiaGpu, ...]:
    with _CACHE_LOCK:
        return _cached_nvidia_gpus(refresh=refresh)


def _norm_device_name(name: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", str(name or "").lower())
    for token in ("nvidia", "geforce", "amd", "radeon", "intel", "graphics", "gpu", "corporation"):
        text = text.replace(token, " ")
    return " ".join(text.split())


def _merge_devices(generic: list[GpuDevice], nvidia: tuple[NvidiaGpu, ...]) -> list[GpuDevice]:
    merged = list(generic)
    used: set[int] = set()
    for ngpu in nvidia:
        best_index = None
        nname = _norm_device_name(ngpu.name)
        for idx, device in enumerate(merged):
            if idx in used or device.vendor != "NVIDIA":
                continue
            dname = _norm_device_name(device.name)
            # A model prefix is not an identity: RTX 4080 and RTX 4080 SUPER,
            # for example, must never exchange their memory/driver metadata.
            if nname and dname and nname.replace(" ", "") == dname.replace(" ", ""):
                best_index = idx
                break
        original = merged[best_index] if best_index is not None else None
        replacement = GpuDevice(
            ngpu.index if ngpu.index is not None else (original.index if original else None),
            ngpu.name, ngpu.memory_total_mb or (original.memory_total_mb if original else None),
            ngpu.driver_version or (original.driver_version if original else ""),
            ngpu.bus_id or (original.bus_id if original else ""), ngpu.source, "NVIDIA", "10DE",
            original.pnp_device_id if original else "",
            original.video_processor if original else "",
            original.integrated if original else False,
        )
        if best_index is None:
            merged.append(replacement)
        else:
            used.add(best_index)
            merged[best_index] = replacement
    # De-duplicate repeated discovery rows while preserving separate adapters.
    unique: list[GpuDevice] = []
    keys: set[tuple] = set()
    for device in merged:
        key = (device.vendor, _norm_device_name(device.name), device.bus_id or device.pnp_device_id or device.index)
        if key in keys:
            continue
        keys.add(key)
        unique.append(device)
    return unique


def detect_gpus(*, refresh: bool = False) -> tuple[GpuDevice, ...]:
    """Detect NVIDIA, AMD and Intel display adapters without compute dependencies."""
    global _ALL_CACHE
    with _CACHE_LOCK:
        if _ALL_CACHE is not None and not refresh:
            return _ALL_CACHE
        windows = os.name == "nt"
        generic = _detect_all_with_windows() if windows else _detect_all_with_lspci()
        nvidia = _cached_nvidia_gpus(refresh=refresh, windows_fallback=generic if windows else None)
        found = _merge_devices(generic, nvidia)
        vendor_rank = {"NVIDIA": 0, "AMD": 1, "Intel": 2, "Unknown": 9}
        found.sort(key=lambda gpu: (
            vendor_rank.get(gpu.vendor, 8),
            gpu.integrated is True,
            -(gpu.memory_total_mb or 0),
            gpu.index if gpu.index is not None else 9999,
            gpu.name.lower(),
        ))
        _ALL_CACHE = tuple(found)
        return _ALL_CACHE


def best_nvidia_gpu(*, refresh: bool = False) -> NvidiaGpu | None:
    gpus = detect_nvidia_gpus(refresh=refresh)
    if not gpus:
        return None
    return max(gpus, key=lambda gpu: (gpu.memory_total_mb or 0, -(gpu.index or 0)))


def best_gpu(*, refresh: bool = False) -> GpuDevice | None:
    gpus = detect_gpus(refresh=refresh)
    if not gpus:
        return None
    # Discovery cannot know actual compute speed; prefer dedicated/high-memory
    # hardware only as a display default. Step 22 benchmark chooses real backends.
    return max(gpus, key=lambda gpu: (gpu.integrated is not True, gpu.memory_total_mb or 0,
                                      gpu.vendor != "Unknown", -(gpu.index or 0)))


def hardware_summary(*, refresh: bool = False) -> str:
    """Legacy NVIDIA summary used by the CUDA-specific tools."""
    gpu = best_nvidia_gpu(refresh=refresh)
    if gpu is None:
        return "No NVIDIA GPU detected"
    memory = f" · {gpu.memory_total_mb:,} MB VRAM" if gpu.memory_total_mb else ""
    driver = f" · driver {gpu.driver_version}" if gpu.driver_version else ""
    return f"{gpu.name}{memory}{driver} · detected via {gpu.source or 'Windows'}"


def universal_hardware_summary(*, refresh: bool = False) -> str:
    gpus = detect_gpus(refresh=refresh)
    if not gpus:
        return "No discrete/integrated GPU adapter detected; CPU fallback available"
    parts = []
    for gpu in gpus:
        memory = f" {gpu.memory_total_mb:,} MB" if gpu.memory_total_mb else ""
        parts.append(f"{gpu.vendor} {gpu.name}{memory}".strip())
    return " · ".join(parts)


def cupy_smoke_test() -> tuple[bool, str]:
    """Run a tiny real CUDA kernel so missing runtime/header issues are caught."""
    gpu = best_nvidia_gpu(refresh=True)
    if gpu is None:
        return False, "No NVIDIA GPU detected"
    try:
        import cupy as cp
        count = int(cp.cuda.runtime.getDeviceCount())
        if count < 1:
            return False, f"{gpu.name} detected, but CuPy reports no CUDA devices"
        target = gpu.index if gpu.index is not None and 0 <= gpu.index < count else 0
        with cp.cuda.Device(int(target)):
            kernel = cp.RawKernel(
                'extern "C" __global__ void imagedrawbot_probe(float* x){int i=blockDim.x*blockIdx.x+threadIdx.x;if(i<32)x[i]=x[i]*2.0f+1.0f;}',
                "imagedrawbot_probe",
            )
            arr = cp.arange(32, dtype=cp.float32)
            kernel((1,), (32,), (arr,))
            cp.cuda.Stream.null.synchronize()
            if float(cp.asnumpy(arr)[3]) != 7.0:
                return False, "CUDA probe returned an unexpected result"
        return True, f"CUDA ready on {gpu.name}"
    except Exception as exc:
        return False, f"{gpu.name} detected, but CUDA/CuPy smoke test failed: {type(exc).__name__}: {exc}"


def _main(argv: list[str]) -> int:
    if "--cupy-smoke" in argv:
        ok, message = cupy_smoke_test()
        print(message)
        return 0 if ok else 2
    if "--all" in argv or "--json" in argv:
        gpus = detect_gpus(refresh=True)
        if "--json" in argv:
            print(json.dumps([gpu.as_dict() for gpu in gpus], ensure_ascii=False))
        elif gpus:
            print(universal_hardware_summary())
        elif "--quiet" not in argv:
            print("No GPU adapter detected")
        return 0 if gpus else 1
    gpus = detect_nvidia_gpus(refresh=True)
    if gpus:
        print(hardware_summary())
    elif "--quiet" not in argv:
        print("No NVIDIA GPU detected")
    return 0 if gpus else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
