"""Shared process checks for optional source-install GPU package setup."""
from __future__ import annotations

import json
import os
import subprocess
import sys


class SetupEnvironmentError(RuntimeError):
    """The selected interpreter could not be verified as a virtual environment."""


_ENVIRONMENT_PROBE = (
    "import json,sys; "
    "print(json.dumps({'prefix':sys.prefix,'base_prefix':getattr(sys,'base_prefix',sys.prefix),"
    "'real_prefix':getattr(sys,'real_prefix',None),'frozen':bool(getattr(sys,'frozen',False))}))"
)


def process_failure(exc: BaseException) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"the process timed out after {exc.timeout} seconds"
    return f"{type(exc).__name__}: {exc}"


def running_in_virtual_environment() -> bool:
    return (not getattr(sys, "frozen", False)
            and (sys.prefix != getattr(sys, "base_prefix", sys.prefix)
                 or bool(getattr(sys, "real_prefix", None))))


def require_virtual_environment(python: str, runner) -> None:
    """Check the actual target before any pip upgrade/uninstall/install action.

    Checking only this process's sys.prefix is insufficient when a caller passes
    another interpreter. -I also prevents PYTHONHOME/PYTHONPATH overrides from
    changing the target's prefix during this fixed, read-only probe.
    """
    try:
        completed = runner([python, "-I", "-c", _ENVIRONMENT_PROBE], timeout=30.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupEnvironmentError(f"Could not verify the target Python: {process_failure(exc)}.") from exc
    if completed.returncode != 0:
        raise SetupEnvironmentError("The target Python could not report its virtual-environment configuration.")
    try:
        payload = json.loads(completed.stdout or "")
    except (TypeError, ValueError) as exc:
        raise SetupEnvironmentError("The target Python returned invalid environment information.") from exc
    if not isinstance(payload, dict) or payload.get("frozen") is not False:
        raise SetupEnvironmentError("GPU packages can only be installed into a source Python virtual environment.")
    prefix = payload.get("prefix")
    base = payload.get("real_prefix") or payload.get("base_prefix")
    if (not isinstance(prefix, str) or not isinstance(base, str)
            or not os.path.isabs(prefix) or not os.path.isabs(base)
            or os.path.normcase(os.path.normpath(prefix)) == os.path.normcase(os.path.normpath(base))):
        raise SetupEnvironmentError("GPU setup requires a virtual-environment Python; a system Python is not an install target.")
