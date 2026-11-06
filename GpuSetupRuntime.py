"""Shared process checks for optional source-install GPU package setup."""
from __future__ import annotations

import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
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


_RELOCATION_OPTIONS = frozenset(("target", "prefix", "root", "user", "python"))
_CONFIG_SELECTORS = frozenset(("PIP_GLOBAL", "PIP_SITE"))


class PipPolicy:
    def __init__(self, environment: dict[str, str], configuration: dict[str, dict[str, str]]):
        self.environment = environment
        self.configuration = configuration

    def for_command(self, command: str) -> dict[str, str]:
        options = dict(self.configuration.get("global", {}))
        options.update(self.configuration.get(command, {}))
        environment = {"PIP_" + key.upper().replace("-", "_"): value for key, value in options.items()}
        # Explicit environment policy takes precedence over configuration files.
        environment.update(self.environment)
        # A custom INI alone would still inherit global/site settings. devnull
        # is pip's documented way to disable all original config files; retain
        # their safe snapshot as per-command environment options instead.
        environment["PIP_CONFIG_FILE"] = os.devnull
        return environment


def pip_command(python: str, *arguments: str) -> list[str]:
    """Use this interpreter's pip without current-directory/PYTHONPATH imports."""
    return [python, "-I", "-m", "pip", "--require-virtualenv", "--no-input", *arguments]


@contextmanager
def pip_environment(python: str, runner):
    """Freeze pip policy while keeping every package operation inside its venv.

    A verified sys.prefix alone does not constrain pip's target/prefix/root/user
    or --python overrides. Keep the user's proxy, CA, index and ordinary pip
    policy, but omit those package-relocation settings from this transaction's
    private configuration snapshot. The original configuration is never edited.
    """
    require_virtual_environment(python, runner)
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() not in _CONFIG_SELECTORS
        and not key.upper().startswith("PYTHON")
        and not (key.upper().startswith("PIP_")
                 and key[4:].lower().replace("_", "-") in _RELOCATION_OPTIONS)
    }
    # pip's documented --python option re-invokes its runner without preserving
    # the parent's -I flag. Remove every inherited Python startup override,
    # including PYTHONINSPECT, and explicitly keep that child away from user
    # site packages and a prepended current/script directory. Ordinary proxy,
    # certificate and pip policy remain in the independent snapshot below.
    environment.update(PYTHONNOUSERSITE="1", PYTHONSAFEPATH="1")
    # An explicit command-line --python also overrides a configured interpreter
    # during the read-only snapshot query, before that configuration is filtered.
    reply = runner(pip_command(python, "--python", python, "config", "list"),
                   timeout=30.0, env=environment, capture_stderr=True)
    if reply.returncode != 0:
        raise SetupEnvironmentError("Could not inspect pip configuration safely; no packages were changed.")
    output = reply.stdout or ""
    if not isinstance(output, str) or len(output) > 1024 * 1024:
        raise SetupEnvironmentError("The selected pip returned invalid configuration information.")
    configuration: dict[str, dict[str, str]] = {}
    try:
        for line in output.splitlines():
            if not line.strip():
                continue
            key, separator, raw = line.partition("=")
            section, dot, option = key.partition(".")
            if not separator or not dot or not section or not option:
                raise ValueError("invalid configuration row")
            value = ast.literal_eval(raw)
            if not isinstance(value, str):
                raise ValueError("invalid configuration value")
            option = option.lower().replace("_", "-")
            if section == ":env:" or option in _RELOCATION_OPTIONS:
                continue
            configuration.setdefault(section, {})[option] = value
    except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
        # Configuration can contain credentials. Never echo the raw rows.
        raise SetupEnvironmentError("The selected pip returned invalid configuration information.") from exc
    yield PipPolicy(environment, configuration)


def checked_requirements(path: Path) -> str:
    """Read the shipped requirement before any existing package is modified."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("requirements file is too large")
        text = raw.decode("utf-8")
        if not any(line.strip() and not line.lstrip().startswith("#") for line in text.splitlines()):
            raise ValueError("requirements file is empty")
        return text
    except (OSError, ValueError, UnicodeError) as exc:
        raise SetupEnvironmentError("The GPU requirements file is missing or invalid; no packages were changed.") from exc
