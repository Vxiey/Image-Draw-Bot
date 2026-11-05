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
import sys
import zipfile
from typing import Iterable, Sequence

from Version import APP_NAME, APP_VERSION, BUILD_CHANNEL


ROOT_PREFIX = "Image-Draw-Bot"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
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
    "exact-colors-*.json", "app-tools-*.json", "paint-tools*.json",
    "draw-time-calibration*.json", "auto-tuner-feedback-*.json",
    "correction-history-*.json", "layout-fingerprints-v2*.json",
    "hardware-performance-profile-v1.json", "real-speed-profiles.json",
    "performance-auto-tuner-v1.json", "profiles.json",
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
    "build_release.py",
    "build_exe.py",
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
    return tuple(part for part in rel.parts if part not in ("", "."))


def _is_runtime_file(parts: tuple[str, ...]) -> bool:
    return len(parts) == 1 and any(fnmatchcase(parts[0], pattern) for pattern in RUNTIME_FILE_PATTERNS)


def is_forbidden_path(relative_path: str | PurePosixPath) -> bool:
    rel = PurePosixPath(relative_path)
    parts = _parts(rel)
    if _is_runtime_file(parts):
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return True
    name = parts[-1] if parts else ""
    if name in EXCLUDED_FILE_NAMES:
        return True
    if any(name.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    suffix = PurePosixPath(name).suffix
    if suffix in EXCLUDED_FILE_SUFFIXES:
        return True
    # Generated release/source archives should never be re-bundled into another release.
    if name.startswith(("Image-Draw-Bot-", "ImageDrawBot-")) and suffix in {".zip", ".exe"}:
        return True
    # One-shot integration/packaging helpers are repository maintenance state,
    # never source-release contents.
    if name.lower().endswith('_once.py'):
        return True
    if len(parts) >= 3 and parts[0] == '.github' and parts[1] == 'workflows' and 'once' in name.lower():
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
    if name.startswith(("Image-Draw-Bot-", "ImageDrawBot-")) and suffix in {'.zip','.exe'}:
        return True
    if name.lower().endswith('_once.py'):
        return True
    if len(parts) >= 3 and parts[0] == '.github' and parts[1] == 'workflows' and 'once' in name.lower():
        return True
    return False


def iter_release_files(root: Path) -> Iterable[Path]:
    root = root.resolve()
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root).as_posix() if current_path != root else ""
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIR_NAMES)
        for filename in sorted(files):
            path = current_path / filename
            rel = path.relative_to(root).as_posix()
            if rel_dir and any(part in EXCLUDED_DIR_NAMES for part in PurePosixPath(rel).parts[:-1]):
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
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_current = current_path.relative_to(root).as_posix() if current_path != root else ""
        original_dirs = list(dirs)
        dirs[:] = [
            dirname for dirname in dirs
            if dirname not in EXCLUDED_DIR_NAMES
            or (allow_output_dirs and dirname in OUTPUT_DIR_NAMES)
        ]
        for dirname in original_dirs:
            rel = PurePosixPath(rel_current, dirname).as_posix() if rel_current else dirname
            if dirname in EXCLUDED_DIR_NAMES:
                if dirname in NON_FATAL_EXCLUDED_DIR_NAMES:
                    continue
                if allow_output_dirs and dirname in OUTPUT_DIR_NAMES:
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
    destination = destination.resolve()
    report = validate_release_tree(root)
    if not report.ok:
        raise ValueError("Release tree is not clean: " + json.dumps(report.to_dict(), indent=2))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    files = tuple(iter_release_files(root))
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            rel = path.relative_to(root).as_posix()
            archive.write(path, PurePosixPath(ROOT_PREFIX, rel).as_posix())
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
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return destination


def write_release_manifest(root: Path, destination: Path, artifacts: Sequence[Path] = ()) -> Path:
    report = validate_release_tree(root, allow_output_dirs=True)
    payload = report.to_dict()
    payload["artifacts"] = [
        {"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size}
        for path in artifacts
        if path.is_file()
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
