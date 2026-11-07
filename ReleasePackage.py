"""Release packaging helpers for Image Draw Bot.

This module validates the source tree, creates deterministic source archives and
writes checksum/manifest files.  It is intentionally local-only: no network,
no GitHub API calls and no user-runtime logs or screenshots are included.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path, PurePosixPath
import argparse
from fnmatch import fnmatchcase
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from typing import Iterable, Sequence

from Version import APP_NAME, APP_VERSION, BUILD_CHANNEL
from RuntimePaths import atomic_write_text


ROOT_PREFIX = "Image-Draw-Bot"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".hypothesis",
    ".mypy_cache",
    ".ruff_cache",
    ".build-venv",
    ".venv",
    "venv",
    "build",
    "dist",
    "release",
    "logs",
    "safety-reports",
    "diagnostics",
    "reports",
    "crash-dumps",
    "completed-drawings",
    "picture-palettes",
    "recovery",
    "updates",
}

EXCLUDED_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".dmp",
    ".log",
    ".spec",
}

EXCLUDED_FILE_NAMES = {
    ".coverage",
    "coverage.xml",
    "desktop.ini",
    "Thumbs.db",
}

# Source runs store these beside the application. They contain local paths,
# calibration/history or recovery state and must never enter a source release.
# Match only the source root so documented examples remain distributable.
RUNTIME_FILE_PATTERNS = (
    "settings*.json", "calibration*.json", "release-state.json",
    "session-recovery*.json", "session-recovery*.png", "render-resume*.json",
    "exact-colors-*.json", "verified-colors-*.json", "app-tools-*.json", "paint-tools*.json",
    "draw-time-calibration*.json", "auto-tuner-feedback-*.json",
    "correction-history-*.json", "layout-fingerprints-v2*.json",
    "hardware-performance-profile-v1.json", "real-speed-profiles.json",
    "performance-auto-tuner-v1.json", "profiles.json",
    "verification.txt",
)

OUTPUT_DIR_NAMES = {"build", "dist", "release"}
NON_FATAL_EXCLUDED_DIR_NAMES = set(EXCLUDED_DIR_NAMES)

EXCLUDED_PREFIXES = (
    "ImageDrawBot-Safety-",
    "ImageDrawBot-crash",
    "ImageDrawBot-session",
    "ImageDrawBot-target-probe",
    "ImageDrawBot-mouse-probe",
)

# Completed v1.0.145 integration jobs remain in git as history. Exclude only
# their known repository-root paths, keeping current tooling and doc examples.
_HISTORICAL_INTEGRATION_RCS = (4, 5, *range(13, 24))
HISTORICAL_INTEGRATION_PATHS = frozenset(
    {f".github/workflows/implement-rc{rc}.yml" for rc in _HISTORICAL_INTEGRATION_RCS}
    | {f".github/implement-rc{rc}-trigger" for rc in _HISTORICAL_INTEGRATION_RCS}
    | {f".github/scripts/implement_rc{rc}.py" for rc in _HISTORICAL_INTEGRATION_RCS if rc != 4}
    | {
        ".github/scripts/fix_rc19_class_indent.py",
        ".github/scripts/fix_rc20_test.py",
        ".github/scripts/migrate_rc16_tests.py",
        ".github/scripts/migrate_rc17_tests.py",
        ".github/scripts/run_rc21_retry.py",
    }
)

REQUIRED_RELEASE_FILES = (
    "README.md",
    "README-INDEX.md",
    "VERSION-HISTORY.md",
    "RELEASE-CHECKLIST.md",
    "GITHUB-RELEASE-TEMPLATE.md",
    "STEP-21-BUILD-PUBLISHER-GITHUB-RELEASE.md",
    "STEP-22-UNIVERSAL-HARDWARE-AUTO-BENCHMARK.md",
    "RELEASE-NOTES-Step22-Universal-Hardware-Auto-Benchmark.md",
    "UniversalHardwareBenchmark.py",
    "AutoUniversalGpuSetup.py",
    "requirements-gpu-universal.txt",
    "Install-GPU-Universal.bat",
    "ROADMAP-STEP22-PLUS.md",
    "Build-Release.bat",
    "BuildEnvironment.py",
    "ReleasePublication.py",
    "build_release.py",
    "build_exe.py",
    "Start.bat",
    "SourceStartup.py",
    "ClipboardImport.py",
    "WordHelperResults.py",
    "ProgressiveSummary.py",
    "NumericEntryCommit.py",
    "RecoveryImagePreparation.py",
    "NativeBrushProjection.py",
    "GpuSetupRuntime.py",
    "ReleaseIdentity.py",
    "Version.py",
    "version_info.txt",
    "requirements.txt",
    "requirements-build.txt",
    ".github/workflows/build-windows.yml",
)


@dataclass(frozen=True)
class ReleaseTreeReport:
    app_name: str
    app_version: str
    build_channel: str
    files: int
    missing_required: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_required and not self.forbidden_paths

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parts(rel: PurePosixPath) -> tuple[str, ...]:
    return tuple(part.casefold() for part in rel.parts if part not in ("", "."))


def _is_runtime_file(parts: tuple[str, ...]) -> bool:
    if len(parts) != 1:
        return False
    name = parts[0].removesuffix('.lock')
    return any(fnmatchcase(name, pattern) for pattern in RUNTIME_FILE_PATTERNS)


def _is_integration_maintenance_file(parts: tuple[str, ...]) -> bool:
    if "/".join(parts) in HISTORICAL_INTEGRATION_PATHS:
        return True
    name = parts[-1] if parts else ""
    return name.endswith('_once.py') or (
        len(parts) >= 3 and parts[0] == '.github' and parts[1] == 'workflows' and 'once' in name
    )


def is_forbidden_path(relative_path: str | PurePosixPath) -> bool:
    rel = PurePosixPath(relative_path)
    parts = _parts(rel)
    if _is_runtime_file(parts):
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return True
    name = parts[-1] if parts else ""
    if name in {item.casefold() for item in EXCLUDED_FILE_NAMES}:
        return True
    if any(name.startswith(prefix.casefold()) for prefix in EXCLUDED_PREFIXES):
        return True
    suffix = PurePosixPath(name).suffix
    if suffix in EXCLUDED_FILE_SUFFIXES:
        return True
    # Generated release/source archives should never be re-bundled into another release.
    if name.startswith(("image-draw-bot-", "imagedrawbot-")) and suffix in {".zip", ".exe"}:
        return True
    # One-shot integration/packaging helpers are repository maintenance state,
    # never source-release contents.
    if _is_integration_maintenance_file(parts):
        return True
    return False


def is_nonfatal_excluded_path(relative_path: str | PurePosixPath) -> bool:
    rel=PurePosixPath(relative_path)
    parts=_parts(rel); name=parts[-1] if parts else ''
    if _is_runtime_file(parts):
        return True
    suffix=PurePosixPath(name).suffix.lower()
    if any(part in NON_FATAL_EXCLUDED_DIR_NAMES for part in parts):
        return True
    if name.startswith(("image-draw-bot-", "imagedrawbot-")) and suffix in {'.zip','.exe'}:
        return True
    if _is_integration_maintenance_file(parts):
        return True
    return False


def _is_link(path: Path) -> bool:
    # st_reparse_tag also covers junctions on Python 3.11, which predates
    # Path.is_junction(). Ordinary cloud-file reparse points are not links.
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_reparse_tag', 0) in (0xA0000003, 0xA000000C)


def _walk_error(error):
    # os.walk otherwise skips unreadable subdirectories silently. A successful
    # source release must account for every included subtree, including assets
    # that are not individually listed in REQUIRED_RELEASE_FILES.
    raise error


def iter_release_files(root: Path) -> Iterable[Path]:
    root = root.resolve()
    for current, dirs, files in os.walk(root, onerror=_walk_error):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root).as_posix() if current_path != root else ""
        dirs[:] = sorted(d for d in dirs if d.casefold() not in EXCLUDED_DIR_NAMES
                         and not _is_link(current_path / d))
        for filename in sorted(files):
            path = current_path / filename
            if _is_link(path) or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel_dir and any(part.casefold() in EXCLUDED_DIR_NAMES for part in PurePosixPath(rel).parts[:-1]):
                continue
            if is_forbidden_path(rel):
                continue
            yield path


def validate_release_tree(root: Path, *, allow_output_dirs: bool = False) -> ReleaseTreeReport:
    root = root.resolve()
    release_files = tuple(iter_release_files(root))
    release_set = {path.relative_to(root).as_posix() for path in release_files}
    missing = tuple(item for item in REQUIRED_RELEASE_FILES if item not in release_set)

    forbidden: list[str] = []
    for current, dirs, files in os.walk(root, onerror=_walk_error):
        current_path = Path(current)
        rel_current = current_path.relative_to(root).as_posix() if current_path != root else ""
        original_dirs = list(dirs)
        dirs[:] = [
            dirname for dirname in dirs
            if not _is_link(current_path / dirname)
            and (dirname.casefold() not in EXCLUDED_DIR_NAMES
                 or (allow_output_dirs and dirname.casefold() in OUTPUT_DIR_NAMES))
        ]
        for dirname in original_dirs:
            rel = PurePosixPath(rel_current, dirname).as_posix() if rel_current else dirname
            if dirname.casefold() in EXCLUDED_DIR_NAMES:
                if dirname.casefold() in NON_FATAL_EXCLUDED_DIR_NAMES:
                    continue
                if allow_output_dirs and dirname.casefold() in OUTPUT_DIR_NAMES:
                    continue
                forbidden.append(rel + "/")
        for filename in files:
            rel = PurePosixPath(rel_current, filename).as_posix() if rel_current else filename
            if is_forbidden_path(rel):
                if is_nonfatal_excluded_path(rel):
                    continue
                forbidden.append(rel)
    warnings: list[str] = []
    if not (root / "golden-regression" / "manifest.json").is_file():
        warnings.append("Golden regression manifest is missing; v1.0.141 tests cannot be audited from the release tree.")
    if not (root / "docs" / "PUBLISHING.md").is_file():
        warnings.append("docs/PUBLISHING.md is missing; GitHub publishing instructions are incomplete.")
    return ReleaseTreeReport(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        build_channel=BUILD_CHANNEL,
        files=len(release_files),
        missing_required=missing,
        forbidden_paths=tuple(sorted(forbidden)),
        warnings=tuple(warnings),
    )


def create_source_archive(root: Path, destination: Path) -> dict[str, object]:
    root = root.resolve()
    destination = destination.parent.resolve() / destination.name
    report = validate_release_tree(root)
    if not report.ok:
        raise ValueError("Release tree is not clean: " + json.dumps(report.to_dict(), indent=2))
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = tuple(path for path in iter_release_files(root) if path != destination)
    descriptor, temporary = tempfile.mkstemp(prefix='.source-release-', suffix='.tmp', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                rel = path.relative_to(root).as_posix()
                # Source content, ordering, timestamp and permissions determine
                # the ZIP, not the checkout's mtime/time zone or local umask.
                info = zipfile.ZipInfo(PurePosixPath(ROOT_PREFIX, rel).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = archive.compresslevel  # ZipInfo spelling supported by Python 3.11/3.12.
                with path.open('rb') as source, archive.open(info, 'w', force_zip64=True) as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "name": destination.name,
        "path": str(destination),
        "sha256": sha256(destination),
        "files": len(files),
        "bytes": destination.stat().st_size,
    }


def write_checksum_file(paths: Sequence[Path], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [f"{sha256(path)}  {path.name}" for path in paths]
    atomic_write_text(destination, "\n".join(rows) + "\n")
    return destination


def write_release_manifest(root: Path, destination: Path, artifacts: Sequence[Path] = ()) -> Path:
    report = validate_release_tree(root, allow_output_dirs=True)
    payload = report.to_dict()
    records = []
    names = set()
    for artifact in artifacts:
        path = Path(artifact)
        if not path.is_file() or _is_link(path):
            raise ValueError(f'Release artifact is missing or linked: {path.name}')
        if path.name.casefold() in names:
            raise ValueError(f'Release artifacts have duplicate names: {path.name}')
        names.add(path.name.casefold())
        records.append({'name': path.name, 'sha256': sha256(path), 'bytes': path.stat().st_size})
    payload['artifacts'] = records
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(destination, json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or package an Image Draw Bot source release.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--check", action="store_true", help="Validate the release tree and print JSON.")
    parser.add_argument("--source-zip", default="", help="Create a clean source ZIP at this path.")
    parser.add_argument("--manifest", default="", help="Write a release manifest JSON at this path.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    artifacts: list[Path] = []
    if args.source_zip:
        artifacts.append(Path(create_source_archive(root, Path(args.source_zip))["path"]))
    if args.manifest:
        write_release_manifest(root, Path(args.manifest), artifacts=artifacts)
    if args.check or not (args.source_zip or args.manifest):
        report = validate_release_tree(root)
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0 if report.ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
