"""Optional vendor-neutral OpenCL bootstrap for Image Draw Bot Step 22.

AMD and Intel GPUs do not use Image Draw Bot's NVIDIA/CUDA bootstrap.  This helper
installs only the Python OpenCL binding inside Image Draw Bot's .venv when an
AMD/Intel adapter is detected.  The vendor graphics driver must already provide
an OpenCL runtime. Failure is non-fatal: CPU fallback always remains available.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from GpuHardware import detect_gpus
from GpuSetupRuntime import (SetupEnvironmentError, checked_requirements, pip_command,
                             pip_environment, process_failure, running_in_virtual_environment)

BASE = Path(__file__).resolve().parent
REQUIREMENTS = BASE / "requirements-gpu-universal.txt"
STATE_FILENAME = "gpu-universal-setup-state.json"


@dataclass
class SetupResult:
    ok: bool
    status: str
    message: str
    detected_vendors: tuple[str, ...] = ()
    installed: bool = False
    devices: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        value = asdict(self)
        value["detected_vendors"] = list(self.detected_vendors)
        value["devices"] = list(self.devices)
        return value


def _creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _run(command: list[str], timeout: float = 300.0, *, capture_stderr: bool = False,
         env=None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=BASE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE if capture_stderr else subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=_creationflags(), check=False, env=env)


def _state_path() -> Path:
    return Path(sys.prefix) / STATE_FILENAME


def _write_state(result: SetupResult) -> None:
    if not running_in_virtual_environment():
        return
    payload = result.as_dict(); payload["timestamp"] = int(time.time()); payload["python"] = sys.executable
    try:
        _state_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _target_vendors() -> tuple[str, ...]:
    vendors = sorted({gpu.vendor for gpu in detect_gpus(refresh=True) if gpu.vendor in ("AMD", "Intel")})
    return tuple(vendors)


def opencl_smoke_test() -> tuple[bool, tuple[str, ...], str]:
    try:
        import pyopencl as cl
        import numpy as np
        candidates = []
        for platform in cl.get_platforms():
            try:
                gpu_devices = platform.get_devices(device_type=cl.device_type.GPU)
            except Exception:
                continue
            for device in gpu_devices:
                try:
                    label = f"{str(getattr(device, 'vendor', '')).strip()} {str(getattr(device, 'name', '')).strip()}".strip()
                except Exception:
                    label = "OpenCL GPU"
                candidates.append((device, label or "OpenCL GPU"))
        if not candidates:
            return False, (), "PyOpenCL loaded, but the installed graphics driver exposed no OpenCL GPU devices."
        errors = []
        for device, label in candidates:
            ctx = queue = program = buf = None
            try:
                ctx = cl.Context(devices=[device])
                queue = cl.CommandQueue(ctx)
                program = cl.Program(ctx, '__kernel void probe(__global float* x){int i=get_global_id(0);x[i]=x[i]*2.0f+1.0f;}').build()
                host = np.arange(8, dtype=np.float32)
                expected = host * 2.0 + 1.0
                buf = cl.Buffer(ctx, cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR, hostbuf=host)
                program.probe(queue, (8,), None, buf)
                cl.enqueue_copy(queue, host, buf)
                queue.finish()
                if not np.array_equal(host, expected):
                    raise RuntimeError("OpenCL probe returned an unexpected result")
                # Report a validated device, not every enumerated adapter as
                # though it had completed the kernel successfully.
                return True, (label,), f"OpenCL ready on {label}"
            except Exception as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
            finally:
                # PyOpenCL releases these native resources when their last
                # Python references are dropped, including after a failed GPU.
                buf = program = queue = ctx = None
        return False, (), "No OpenCL GPU passed validation. " + "; ".join(errors[:3])
    except Exception as exc:
        return False, (), f"OpenCL/PyOpenCL smoke test failed: {type(exc).__name__}: {exc}"


def _smoke_test(python: str) -> tuple[bool, tuple[str, ...], str]:
    """Validate the selected interpreter, including after installing into it."""
    completed = _run([python, str(BASE / "AutoUniversalGpuSetup.py"), "--smoke-json"],
                     timeout=45.0, capture_stderr=True)
    try:
        payload = json.loads(completed.stdout or "")
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise ValueError("invalid result")
        devices = payload.get("devices", [])
        if not isinstance(devices, list) or not all(isinstance(device, str) for device in devices):
            raise ValueError("invalid devices")
        message = payload.get("message", "")
        if not isinstance(message, str):
            raise ValueError("invalid message")
    except (TypeError, ValueError):
        return False, (), "The selected Python returned invalid OpenCL validation output."
    return completed.returncode == 0 and payload["ok"], tuple(devices), message


def _pip_install_backend(python: str) -> subprocess.CompletedProcess[str]:
    with pip_environment(python, _run) as environment:
        checked_requirements(REQUIREMENTS)
        return _run(pip_command(python, "install", "--upgrade", "--upgrade-strategy", "only-if-needed",
                    "--disable-pip-version-check", "--timeout", "45", "--retries", "2", "-r", str(REQUIREMENTS)),
                    timeout=600.0, env=environment.for_command("install"))


def ensure_universal_gpu_backend(*, python: str | None = None, force: bool = False) -> SetupResult:
    python = str(python or sys.executable)
    vendors = _target_vendors()
    if not vendors:
        result=SetupResult(True,"not-needed","No AMD/Intel GPU detected; vendor-neutral OpenCL setup skipped.")
        _write_state(result); return result
    try:
        ok, devices, message = _smoke_test(python)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = SetupResult(False, "probe-failed", f"OpenCL validation could not run: {process_failure(exc)}. CPU fallback remains available.", vendors)
        _write_state(result); return result
    if ok and not force:
        result=SetupResult(True,"ready",message,vendors,False,devices); _write_state(result); return result
    try:
        completed = _pip_install_backend(python)
    except SetupEnvironmentError as exc:
        result = SetupResult(False, "environment-not-verified", f"{exc} CPU fallback remains available.", vendors)
        _write_state(result); return result
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = SetupResult(False, "install-failed", f"OpenCL installation could not finish: {process_failure(exc)}. CPU fallback remains available.", vendors)
        _write_state(result); return result
    if completed.returncode != 0:
        result=SetupResult(False,"install-failed",
                           f"{', '.join(vendors)} GPU detected, but the optional OpenCL Python backend could not be installed. CPU fallback remains available.",
                           vendors,True,())
        _write_state(result); return result
    try:
        ok, devices, message = _smoke_test(python)
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok, devices, message = False, (), process_failure(exc)
    if not ok:
        result=SetupResult(False,"smoke-failed",
                           f"OpenCL Python packages were installed, but the GPU driver backend is not usable: {message} CPU fallback remains available.",
                           vendors,True,devices)
        _write_state(result); return result
    result=SetupResult(True,"installed",message,vendors,True,devices); _write_state(result); return result


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Ensure Image Draw Bot AMD/Intel OpenCL benchmark backend is ready.")
    parser.add_argument("--ensure",action="store_true")
    parser.add_argument("--force",action="store_true")
    parser.add_argument("--json",action="store_true")
    parser.add_argument("--smoke-json", action="store_true", help="Run a read-only OpenCL readiness probe and emit JSON")
    args=parser.parse_args(argv)
    if args.smoke_json:
        ok, devices, message = opencl_smoke_test()
        print(json.dumps({"ok": ok, "devices": list(devices), "message": message}, ensure_ascii=False))
        return 0 if ok else 2
    if sys.prefix == getattr(sys,"base_prefix",sys.prefix):
        message="Universal GPU setup must run inside Image Draw Bot's .venv. Run Start.bat first."
        print(json.dumps({"ok":False,"status":"venv-required","message":message}) if args.json else message)
        return 4
    result=ensure_universal_gpu_backend(force=args.force)
    print(json.dumps(result.as_dict(),ensure_ascii=False) if args.json else result.message)
    return 0 if result.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
