"""Automatic NVIDIA CUDA/CuPy bootstrap for Image Draw Bot source installs.

This module intentionally installs GPU packages only into Image Draw Bot's active
virtual environment. It never installs a system-wide CUDA Toolkit and never
requires administrator privileges. With CuPy's ``[ctk]`` extra, the matching
CUDA runtime/NVRTC/header wheels live inside the venv; an NVIDIA display driver
is still required.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable

from GpuHardware import best_nvidia_gpu
from GpuSetupRuntime import (SetupEnvironmentError, checked_requirements, pip_command,
                             pip_environment, process_failure, running_in_virtual_environment)

BASE = Path(__file__).resolve().parent
GPU_REQUIREMENTS = BASE / "requirements-gpu-nvidia.txt"
STATE_FILENAME = "gpu-setup-state.json"
CONFLICTING_CUPY_DISTS = (
    "cupy",
    "cupy-cuda11x",
    "cupy-cuda12x",
    "cupy-cuda13x",
)


@dataclass
class SetupResult:
    ok: bool
    status: str
    message: str
    gpu_name: str = ""
    driver_version: str = ""
    installed: bool = False
    smoke_output: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _run(command: list[str], *, timeout: float = 180.0, env=None,
         capture_stderr: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=BASE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if capture_stderr else subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_creationflags(),
        check=False,
        env=env,
    )


def requirements_sha256(path: Path = GPU_REQUIREMENTS) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _state_path() -> Path:
    # In source mode sys.prefix is the .venv directory. Keep state there so
    # deleting/recreating the venv also resets the GPU bootstrap state.
    return Path(sys.prefix) / STATE_FILENAME


def _write_state(result: SetupResult) -> None:
    if not running_in_virtual_environment():
        return
    payload = result.as_dict()
    payload.update({
        "timestamp": int(time.time()),
        "requirements_sha256": requirements_sha256(),
        "python": sys.executable,
    })
    try:
        _state_path().write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _read_pip_packages(python: str, *, env=None) -> set[str]:
    completed = _run(pip_command(python, "list", "--format=json"), timeout=45.0, env=env)
    if completed.returncode != 0:
        raise RuntimeError("pip could not inspect installed packages before GPU setup")
    try:
        rows = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("pip returned invalid installed-package information") from exc
    if not isinstance(rows, list):
        raise RuntimeError("pip returned invalid installed-package information")
    return {str(row.get("name") or "").lower() for row in rows if isinstance(row, dict)}


def conflicting_cupy_packages(installed: Iterable[str], *, desired: str = "cupy-cuda12x") -> list[str]:
    normalized = {str(name).lower() for name in installed}
    desired = desired.lower()
    return [name for name in CONFLICTING_CUPY_DISTS if name != desired and name in normalized]


def _desired_cupy_distribution(text: str | None = None) -> str:
    lines = (checked_requirements(GPU_REQUIREMENTS) if text is None else text).splitlines()
    for raw in lines:
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        if line.startswith("cupy-cuda13x"):
            return "cupy-cuda13x"
        if line.startswith("cupy-cuda12x"):
            return "cupy-cuda12x"
    raise SetupEnvironmentError("The GPU requirements file does not select a supported CuPy distribution.")


def _smoke_test(python: str) -> tuple[bool, str]:
    completed = _run([python, str(BASE / "GpuHardware.py"), "--cupy-smoke"], timeout=45.0)
    text = (completed.stdout or "").strip()
    return completed.returncode == 0, text


def _pip_install_backend(python: str, *, upgrade_pip: bool = True) -> tuple[bool, str]:
    with pip_environment(python, _run) as environment:
        desired = _desired_cupy_distribution(checked_requirements(GPU_REQUIREMENTS))
        return _install_backend(python, environment, desired, upgrade_pip=upgrade_pip)


def _install_backend(python: str, environment, desired: str, *, upgrade_pip: bool) -> tuple[bool, str]:
    output: list[str] = []
    if upgrade_pip:
        completed = _run(pip_command(python,
            "install", "--upgrade", "pip", "setuptools", "wheel",
            "--disable-pip-version-check", "--timeout", "30", "--retries", "2",
        ), timeout=240.0, env=environment.for_command("install"))
        output.append(completed.stdout or "")
        # A pip self-upgrade failure should not prevent trying the actual GPU
        # install with the already-installed pip.

    installed = _read_pip_packages(python, env=environment.for_command("list"))
    conflicts = conflicting_cupy_packages(installed, desired=desired)
    if conflicts:
        completed = _run(pip_command(python, "uninstall", "-y", *conflicts), timeout=120.0,
                         env=environment.for_command("uninstall"))
        output.append(completed.stdout or "")
        if completed.returncode != 0:
            return False, "\n".join(output).strip()

    completed = _run(pip_command(python,
        "install", "--upgrade", "--upgrade-strategy", "only-if-needed",
        "--disable-pip-version-check", "--timeout", "45", "--retries", "2",
        "-r", str(GPU_REQUIREMENTS),
    ), timeout=900.0, env=environment.for_command("install"))
    output.append(completed.stdout or "")
    return completed.returncode == 0, "\n".join(output).strip()


def ensure_gpu_backend(*, python: str | None = None, force: bool = False) -> SetupResult:
    python = str(python or sys.executable)
    gpu = best_nvidia_gpu(refresh=True)
    if gpu is None:
        result = SetupResult(True, "no-nvidia", "No NVIDIA GPU detected; CUDA setup skipped.")
        _write_state(result)
        return result

    try:
        ok, smoke = _smoke_test(python)
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = process_failure(exc)
        result = SetupResult(False, "probe-failed", f"CUDA validation could not run: {detail}. CPU fallback remains available.",
                             gpu.name, gpu.driver_version, False, detail)
        _write_state(result)
        return result
    if ok and not force:
        result = SetupResult(
            True, "ready", smoke or f"CUDA ready on {gpu.name}",
            gpu.name, gpu.driver_version, False, smoke,
        )
        _write_state(result)
        return result

    try:
        install_ok, install_output = _pip_install_backend(python)
    except SetupEnvironmentError as exc:
        result = SetupResult(False, "environment-not-verified", f"{exc} CPU fallback remains available.",
                             gpu.name, gpu.driver_version, False, str(exc))
        _write_state(result)
        return result
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        install_ok, install_output = False, process_failure(exc)
    if not install_ok:
        message = f"{gpu.name} detected, but automatic CUDA package installation failed. CPU fallback remains available."
        result = SetupResult(False, "install-failed", message, gpu.name, gpu.driver_version, True, install_output[-5000:])
        _write_state(result)
        return result

    try:
        ok, smoke = _smoke_test(python)
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok, smoke = False, process_failure(exc)
    if not ok:
        detail = smoke or "CUDA smoke test failed after package installation."
        result = SetupResult(
            False, "smoke-failed",
            f"{gpu.name} detected and GPU packages were installed, but CUDA validation failed: {detail} CPU fallback remains available.",
            gpu.name, gpu.driver_version, True, detail,
        )
        _write_state(result)
        return result

    result = SetupResult(
        True, "installed", smoke or f"CUDA ready on {gpu.name}",
        gpu.name, gpu.driver_version, True, smoke,
    )
    _write_state(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ensure Image Draw Bot NVIDIA CUDA acceleration is ready.")
    parser.add_argument("--ensure", action="store_true", help="Detect NVIDIA and install/repair the CUDA backend if needed")
    parser.add_argument("--force", action="store_true", help="Reinstall/update the GPU backend even when the smoke test already passes")
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON")
    parser.add_argument("--require-nvidia", action="store_true", help="Return a non-zero code if no NVIDIA GPU is present")
    args = parser.parse_args(argv)

    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        message = "GPU setup must run inside Image Draw Bot's .venv. Run Start.bat first."
        if args.json:
            print(json.dumps({"ok": False, "status": "venv-required", "message": message}, ensure_ascii=False))
        else:
            print(message)
        return 4

    result = ensure_gpu_backend(force=args.force)
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False))
    else:
        print(result.message)
    if result.status == "no-nvidia" and args.require_nvidia:
        return 2
    return 0 if result.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
