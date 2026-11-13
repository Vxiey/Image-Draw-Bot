"""Release Candidate Hardening for Image Draw Bot.

This module contains deterministic, non-interactive release gates.  It does not
move the mouse, activate target windows, download updates, or change user
settings.  It verifies release metadata, repository/update wiring, lifecycle
cleanup invariants and packaged Windows artifacts before a release is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import zipfile
from typing import Iterable

EXPECTED_REPOSITORY = "Vxiey/Image-Draw-Bot"
RELEASE_GATE_SCHEMA = 1
DEFAULT_SOAK_CYCLES = 5000
FORBIDDEN_ARCHIVE_SUFFIXES = (".log", ".dmp", ".pyc", ".pyo", ".tmp")


class ReleaseGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseGateReport:
    version: str
    file_version: str
    channel: str
    repository: str
    soak_cycles: int
    checks: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "schema": RELEASE_GATE_SCHEMA,
            "version": self.version,
            "file_version": self.file_version,
            "channel": self.channel,
            "repository": self.repository,
            "soak_cycles": self.soak_cycles,
            "checks": list(self.checks),
            "passed": True,
        }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseGateError(f"Required release file is unavailable: {path}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_tuple(file_version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(file_version).strip())
    if not match:
        raise ReleaseGateError(f"Invalid FILE_VERSION: {file_version!r}")
    return tuple(map(int, match.groups()))


def _assert_contains(text: str, token: str, label: str, errors: list[str]) -> None:
    if token not in text:
        errors.append(f"{label}: missing {token!r}")


def find_one_shot_source_files(root: Path) -> list[str]:
    """Return temporary integration/patch files that must never ship from main."""
    from ReleasePackage import EXCLUDED_DIR_NAMES, _is_link
    root = Path(root)
    found: list[str] = []
    def walk_error(error):
        raise ReleaseGateError('The included source tree could not be fully inspected.') from error
    for current, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
        current = Path(current)
        # Private builders/output trees are not source-release contents. Inspect
        # neither their dependency filenames nor their potentially huge trees.
        directories[:] = [name for name in directories if name.casefold() not in EXCLUDED_DIR_NAMES
                           and not _is_link(current / name)]
        relative_directory = current.relative_to(root).as_posix().casefold()
        in_workflows = (relative_directory == '.github/workflows'
                        or relative_directory.startswith('.github/workflows/'))
        for filename in filenames:
            base = filename.casefold()
            temporary = (base.endswith('_once.py') or
                         (in_workflows and base.endswith(('.yml', '.yaml'))
                          and re.search(r'(?:^|[-_])once(?:[-_.]|$)', base)))
            if temporary:
                path = current / filename
                if path.is_file():
                    found.append(path.relative_to(root).as_posix())
    return sorted(set(found))


def collect_source_gate_errors(root: Path, *, app_version: str, file_version: str,
                               channel: str, expected_repository: str = EXPECTED_REPOSITORY) -> list[str]:
    """Return release-blocking source metadata/configuration errors."""
    root = Path(root)
    errors: list[str] = []
    version_info = _read(root / "version_info.txt")
    installer = _read(root / "installer" / "ImageDrawBot.iss")
    updater = _read(root / "UpdateCenter.py")
    build_release = _read(root / "build_release.py")
    workflow = _read(root / ".github" / "workflows" / "build-windows.yml")
    if not (root / 'ReleaseIdentity.py').is_file():
        errors.append('release identity: ReleaseIdentity.py is missing')

    one_shot_files = find_one_shot_source_files(root)
    if one_shot_files:
        errors.append("source tree: temporary one-shot files are present: " + ", ".join(one_shot_files[:12]))

    major, minor, patch = _version_tuple(file_version)
    base_version = app_version.split('-', 1)[0]
    if base_version != file_version:
        errors.append('Version.py: APP_VERSION base must match FILE_VERSION.')
    _assert_contains(version_info, f"filevers=({major},{minor},{patch},0)", "version_info", errors)
    _assert_contains(version_info, f"prodvers=({major},{minor},{patch},0)", "version_info", errors)
    _assert_contains(version_info, f"StringStruct('FileVersion', '{file_version}')", "version_info", errors)
    _assert_contains(version_info, f"StringStruct('ProductVersion', '{file_version}')", "version_info", errors)

    _assert_contains(installer, f'#define MyAppVersion "{app_version}"', "installer", errors)
    _assert_contains(installer, f'VersionInfoVersion={major}.{minor}.{patch}.0', 'installer', errors)
    _assert_contains(installer, "AppId={{6A4AD303-4F16-4ED7-A9AF-5B912352D83E}", "installer", errors)
    _assert_contains(installer, "PrivilegesRequired=lowest", "installer", errors)

    _assert_contains(updater, f'GITHUB_REPOSITORY = "{expected_repository}"', "UpdateCenter", errors)
    if "yesverynice12/Image-Draw-Bot" in updater:
        errors.append("UpdateCenter: stale legacy GitHub repository is still configured")

    _assert_contains(build_release, "run_source_release_gate", "build_release", errors)
    _assert_contains(build_release, "validate_windows_release", "build_release", errors)
    _assert_contains(workflow, "ReleaseCandidateHardening.py --source-gate", "build-windows workflow", errors)
    _assert_contains(workflow, "Validate silent installer round-trip", "build-windows workflow", errors)
    release_notes_name = f"RELEASE-NOTES-v{app_version}.md"
    release_notes = root / release_notes_name
    if not release_notes.is_file():
        errors.append(f"release notes: missing {release_notes_name!r}")
    else:
        try:
            if not release_notes.read_text(encoding="utf-8").strip():
                errors.append(f"release notes: {release_notes_name!r} is empty")
        except OSError:
            errors.append(f"release notes: unable to read {release_notes_name!r}")

    # The workflow may either pin the current release-note file explicitly or
    # derive it from Version.APP_VERSION. The dynamic form avoids a release-gate
    # regression every time an rc/beta version advances. Keep the wiring strict:
    # the workflow must still pass the resolved path to gh via --notes-file.
    _assert_contains(workflow, "--notes-file $notes", "build-windows workflow", errors)
    static_notes = release_notes_name in workflow
    dynamic_notes = (
        'RELEASE-NOTES-v$version.md' in workflow
        and 'from Version import APP_VERSION; print(APP_VERSION)' in workflow
    )
    if not (static_notes or dynamic_notes):
        errors.append(
            "build-windows workflow: release-notes path is not tied to APP_VERSION "
            f"({release_notes_name!r})"
        )

    if re.fullmatch(r"\d+\.\d+\.\d+-rc\d+", app_version):
        expected_channel='rc'
    elif re.fullmatch(r"\d+\.\d+\.\d+-beta", app_version):
        expected_channel='beta'
    elif re.fullmatch(r"\d+\.\d+\.\d+", app_version):
        expected_channel='stable'
    else:
        expected_channel=None;errors.append(f"Version.py: APP_VERSION has unsupported release format: {app_version!r}")
    if expected_channel is not None and channel != expected_channel:
        errors.append(f"Version.py: APP_VERSION {app_version!r} requires BUILD_CHANNEL={expected_channel!r}, got {channel!r}")

    return errors


def run_lifecycle_soak(cycles: int = DEFAULT_SOAK_CYCLES) -> dict:
    """Stress the pure start/stop authorization lifecycle without native input."""
    from StabilityRC import run_start_stop_model, safe_release_and_disarm

    cycles = max(1, int(cycles))
    state = run_start_stop_model(cycles)
    if state.get("activity") is not None or state.get("armed") or state.get("pending"):
        raise ReleaseGateError(f"Lifecycle soak ended in unsafe state: {state!r}")

    class MouseModel:
        def __init__(self):
            self.releases = 0
            self.disarms = 0
        def release(self):
            self.releases += 1
        def disarm_input(self):
            self.disarms += 1

    mouse = MouseModel()
    for _ in range(min(cycles, 10000)):
        errors = safe_release_and_disarm(mouse)
        if errors:
            raise ReleaseGateError(f"Cleanup soak returned errors: {errors!r}")
    if mouse.releases != min(cycles, 10000) or mouse.disarms != min(cycles, 10000):
        raise ReleaseGateError("Cleanup soak did not release/disarm every iteration")
    return {"cycles": cycles, "final_state": state, "cleanup_cycles": min(cycles, 10000)}


def run_profile_isolation_soak(cycles: int = 1000) -> dict:
    """Verify built-in profile storage keys remain stable and unique repeatedly."""
    from GameProfiles import PROFILES
    from ProfileStorage import safe_profile_key

    cycles = max(1, int(cycles))
    pairs = [(name, safe_profile_key(data[0])) for name, data in PROFILES.items()]
    keys = [key for _, key in pairs]
    if len(keys) != len(set(keys)):
        raise ReleaseGateError("Built-in profile storage keys are not unique")
    baseline = tuple(pairs)
    for _ in range(cycles):
        current = tuple((name, safe_profile_key(PROFILES[name][0])) for name, _ in baseline)
        if current != baseline:
            raise ReleaseGateError("Profile storage identity changed during isolation soak")
    return {"cycles": cycles, "profiles": len(baseline), "unique_keys": len(set(keys))}


def run_source_release_gate(root: Path, *, app_version: str | None = None,
                            file_version: str | None = None, channel: str | None = None,
                            expected_repository: str = EXPECTED_REPOSITORY,
                            soak_cycles: int = DEFAULT_SOAK_CYCLES) -> ReleaseGateReport:
    """Run all non-interactive source gates and raise on the first release blocker set."""
    if app_version is None or file_version is None or channel is None:
        from Version import APP_VERSION, FILE_VERSION, BUILD_CHANNEL
        app_version = APP_VERSION if app_version is None else app_version
        file_version = FILE_VERSION if file_version is None else file_version
        channel = BUILD_CHANNEL if channel is None else channel

    errors = collect_source_gate_errors(
        Path(root), app_version=str(app_version), file_version=str(file_version),
        channel=str(channel), expected_repository=expected_repository,
    )
    if errors:
        raise ReleaseGateError("Release source gate failed:\n- " + "\n- ".join(errors))
    run_lifecycle_soak(soak_cycles)
    run_profile_isolation_soak(max(100, min(2000, soak_cycles // 2)))
    return ReleaseGateReport(
        str(app_version), str(file_version), str(channel), expected_repository,
        int(soak_cycles),
        ("version-metadata", "installer-metadata", "update-repository", "workflow-gates",
         "source-one-shot-hygiene", "lifecycle-soak", "profile-isolation-soak"),
    )


def _forbidden_archive_name(name: str) -> bool:
    lowered = name.lower().replace("\\", "/")
    base = lowered.rsplit("/", 1)[-1]
    # Documentation used to recursively include obsolete source releases.
    # Reject both the old flattened and the corrected docs/ runtime layout.
    if "/history/archives/" in lowered:
        return True
    # Windows releases are x64. The upstream TkinterDnD2 hook selects the
    # matching native extension; collecting the entire package defeats it.
    tkdnd_marker = "/tkinterdnd2/tkdnd/"
    if tkdnd_marker in lowered:
        platform_dir = lowered.split(tkdnd_marker, 1)[1].split("/", 1)[0]
        if platform_dir not in {"win-x64", "win-x64-tcl9"}:
            return True
    if lowered.endswith(FORBIDDEN_ARCHIVE_SUFFIXES):
        return True
    if "/__pycache__/" in lowered or "/.git/" in lowered or "/safety-reports/" in lowered:
        return True
    if base.startswith("test_") and base.endswith(".py"):
        return True
    if base.endswith("_once.py") or ("/.github/workflows/" in lowered and "once" in base):
        return True
    return False


def _safe_windows_parts(name: str) -> tuple[str, ...]:
    """Validate names before any extractor can reinterpret them on Windows."""
    if not isinstance(name, str) or not name or any(ord(char) < 32 for char in name):
        raise ReleaseGateError('Unsafe Windows artifact path.')
    parts = tuple(name.replace('\\', '/').rstrip('/').split('/'))
    reserved = re.compile(r'(?i)(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)')
    if any(not part or part in ('.', '..') or part.endswith((' ', '.'))
           or re.search(r'[<>:"|?*]', part) or reserved.match(part) for part in parts):
        raise ReleaseGateError(f'Unsafe Windows artifact path: {name!r}')
    return parts


def _artifact_basename(name: str) -> str:
    parts = _safe_windows_parts(name)
    if len(parts) != 1 or '/' in name or '\\' in name:
        raise ReleaseGateError(f'Artifact name must be a basename: {name!r}')
    return name


def _validate_zip_entries(entries: list[zipfile.ZipInfo]) -> None:
    names = set()
    files = set()
    parents = set()
    for entry in entries:
        parts = _safe_windows_parts(entry.orig_filename)
        if parts[0] != 'ImageDrawBot':
            raise ReleaseGateError(f'Windows ZIP entry is outside ImageDrawBot/: {entry.filename!r}')
        identity = '/'.join(parts).casefold()
        if identity in names:
            raise ReleaseGateError(f'Duplicate Windows ZIP path: {entry.filename!r}')
        names.add(identity)
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ReleaseGateError(f'Windows ZIP contains a link or special file: {entry.filename!r}')
        if not entry.filename.replace('\\', '/').endswith('/'):
            files.add(identity)
        parents.update('/'.join(parts[:index]).casefold() for index in range(1, len(parts)))
    if files & parents:
        raise ReleaseGateError('Windows ZIP has a file/directory path collision.')


def validate_windows_zip(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ReleaseGateError(f"Windows ZIP is missing: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        _validate_zip_entries(archive.infolist())
        names = archive.namelist()
        exe_name = next((name for name in names if name.replace("\\", "/") == "ImageDrawBot/ImageDrawBot.exe"), None)
        if not exe_name:
            raise ReleaseGateError("Windows ZIP is missing ImageDrawBot/ImageDrawBot.exe")
        leaked = [name for name in names if _forbidden_archive_name(name)]
        if leaked:
            raise ReleaseGateError("Runtime/source-only files leaked into Windows ZIP: " + ", ".join(leaked[:8]))
        with archive.open(exe_name) as executable:
            if executable.read(2) != b"MZ":
                raise ReleaseGateError("Packaged ImageDrawBot.exe is not a PE executable")
        bad = archive.testzip()
        if bad:
            raise ReleaseGateError(f"Windows ZIP integrity failed at {bad}")
    return {"path": str(path), "sha256": _sha256(path), "entries": len(names), "integrity": "PASS"}


def validate_installer(path: Path, *, app_version: str) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ReleaseGateError(f"Installer is missing: {path}")
    with path.open('rb') as executable:
        if executable.read(2) != b"MZ":
            raise ReleaseGateError("Installer is not a PE executable")
    if app_version not in path.name:
        raise ReleaseGateError(f"Installer filename does not contain {app_version}: {path.name}")
    return {"path": str(path), "sha256": _sha256(path), "size": path.stat().st_size}


def verify_checksum_file(path: Path, *, base_dir: Path | None = None,
                         expected_files: Iterable[str] | None = None) -> dict:
    path = Path(path)
    base = Path(base_dir) if base_dir is not None else path.parent
    rows = []
    seen = set()
    for raw in _read(path).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s{2}(.+)", raw)
        if not match:
            raise ReleaseGateError(f"Malformed checksum row: {raw!r}")
        expected, name = match.groups()
        _artifact_basename(name)
        if name.casefold() in seen:
            raise ReleaseGateError(f'Duplicate checksum target: {name}')
        seen.add(name.casefold())
        target = base / name
        if target.is_symlink() or not target.is_file():
            raise ReleaseGateError(f"Checksum target is missing: {name}")
        actual = _sha256(target)
        if actual.lower() != expected.lower():
            raise ReleaseGateError(f"Checksum mismatch for {name}")
        rows.append(name)
    if not rows:
        raise ReleaseGateError("Checksum file is empty")
    if expected_files is not None and set(rows) != set(expected_files):
        raise ReleaseGateError('Checksum file does not cover exactly the expected release artifacts.')
    return {"verified": len(rows), "files": rows}


def validate_manifest(path: Path, *, app_version: str, expected_files: Iterable[str],
                      file_version: str | None = None, channel: str | None = None,
                      base_dir: Path | None = None) -> dict:
    path = Path(path)
    try:
        data = json.loads(_read(path))
    except json.JSONDecodeError as error:
        raise ReleaseGateError("Release manifest is not valid JSON") from error
    if not isinstance(data, dict):
        raise ReleaseGateError('Release manifest must be a JSON object.')
    if type(data.get('schema')) is not int or data.get("schema") != RELEASE_GATE_SCHEMA or data.get("version") != app_version:
        raise ReleaseGateError("Release manifest metadata does not match this build")
    if file_version is not None and data.get("file_version") != file_version:
        raise ReleaseGateError("Release manifest file_version does not match Version.py")
    if channel is not None and data.get("channel") != channel:
        raise ReleaseGateError("Release manifest channel does not match Version.py")
    if data.get("architecture") != "windows-x64":
        raise ReleaseGateError("Release manifest architecture must be windows-x64")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseGateError("Release manifest artifacts are invalid")
    rows = {}
    seen = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ReleaseGateError('Release manifest artifact rows must be objects.')
        name = _artifact_basename(item.get('name'))
        if name.casefold() in seen:
            raise ReleaseGateError(f'Duplicate release manifest artifact: {name}')
        seen.add(name.casefold())
        rows[name] = item
    expected_files = tuple(expected_files)
    for name in expected_files:
        _artifact_basename(name)
    missing = set(expected_files) - set(rows)
    if missing:
        raise ReleaseGateError("Release manifest is missing artifacts: " + ", ".join(sorted(missing)))
    if set(rows) != set(expected_files):
        raise ReleaseGateError('Release manifest contains unexpected artifacts.')
    base = Path(base_dir) if base_dir is not None else path.parent
    for name in expected_files:
        item = rows[name]
        target = base / name
        if target.is_symlink() or not target.is_file():
            raise ReleaseGateError(f"Release manifest target is missing: {name}")
        digest = str(item.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != _sha256(target):
            raise ReleaseGateError(f"Release manifest SHA-256 mismatch for {name}")
        declared_bytes = item.get('bytes')
        if type(declared_bytes) is not int or declared_bytes <= 0:
            raise ReleaseGateError(f"Release manifest byte size is invalid for {name}")
        if declared_bytes != target.stat().st_size:
            raise ReleaseGateError(f"Release manifest byte size mismatch for {name}")
    return data


def validate_windows_release(release_dir: Path, *, app_version: str | None = None,
                             require_installer: bool = True, gpu: bool = False) -> dict:
    if gpu and require_installer:
        raise ReleaseGateError("CUDA releases are ZIP-only and cannot require an installer.")
    from Version import APP_VERSION, FILE_VERSION, BUILD_CHANNEL
    app_version = APP_VERSION if app_version is None else str(app_version)
    release = Path(release_dir)
    suffix = "-CUDA" if gpu else ""
    zip_path = release / f"ImageDrawBot-{app_version}-Windows-x64{suffix}.zip"
    setup_path = release / f"ImageDrawBot-{app_version}-Windows-x64-Setup.exe"
    checksum_path = release / f"ImageDrawBot-{app_version}-SHA256.txt"
    manifest_path = release / f"ImageDrawBot-{app_version}-manifest.json"

    result = {"zip": validate_windows_zip(zip_path)}
    expected = [zip_path.name]
    if require_installer:
        result["installer"] = validate_installer(setup_path, app_version=app_version)
        expected.append(setup_path.name)
    result["checksums"] = verify_checksum_file(checksum_path, base_dir=release, expected_files=expected)
    result["manifest"] = validate_manifest(manifest_path, app_version=app_version, expected_files=expected,
                                           file_version=FILE_VERSION, channel=BUILD_CHANNEL, base_dir=release)
    return result


def validate_release_scope(root: Path) -> dict:
    """Publication-only gate; normal candidate builds may remain incomplete."""
    from Version import APP_VERSION
    path = Path(root) / 'docs' / 'v148-improvements.json'
    try:
        with path.open('rb') as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('registry exceeds limit')
        data = json.loads(raw)
    except (OSError, ValueError, RecursionError) as error:
        raise ReleaseGateError('Cannot verify the release scope registry.') from error
    if not isinstance(data, dict) or data.get('version') != APP_VERSION:
        raise ReleaseGateError('Release scope version does not match the application.')
    # The owner set 900 distinct groups for v1.0.148. Lowering a JSON target
    # must not silently bypass the agreed publication requirement.
    if APP_VERSION != '1.0.148' or type(data.get('target')) is not int or data['target'] != 900:
        raise ReleaseGateError('Release scope requires the reviewed 900-group v1.0.148 target.')
    rows = data.get('improvements')
    if not isinstance(rows, list):
        raise ReleaseGateError('Release scope entries are missing.')
    ids = []
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('id')) is not int
                or not isinstance(row.get('description'), str) or not row['description'].strip()
                or not isinstance(row.get('ledger'), str) or not row['ledger'].strip()):
            raise ReleaseGateError('Release scope contains malformed evidence entries.')
        ids.append(row['id'])
    if (type(data.get('implemented')) is not int or data['implemented'] != len(rows)
            or sorted(ids) != list(range(1, 901))):
        raise ReleaseGateError(f'Release scope incomplete or inconsistent: {len(rows)}/900 groups; publication blocked.')
    return {'version': APP_VERSION, 'target': 900, 'implemented': 900, 'passed': True}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Image Draw Bot release-candidate gates")
    parser.add_argument("--source-gate", action="store_true")
    parser.add_argument("--scope-gate", action="store_true", help="Require completed 900-group scope before publication")
    parser.add_argument("--release-dir")
    parser.add_argument("--gpu", action="store_true", help="Validate the optional CUDA ZIP release instead of the standard installer release")
    parser.add_argument("--soak-cycles", type=int, default=DEFAULT_SOAK_CYCLES)
    args = parser.parse_args(argv)
    if args.gpu and not args.release_dir:
        parser.error("--gpu requires --release-dir")
    if args.scope_gate:
        print(json.dumps(validate_release_scope(Path(__file__).resolve().parent), indent=2, sort_keys=True))
    if args.source_gate:
        report = run_source_release_gate(Path(__file__).resolve().parent, soak_cycles=args.soak_cycles)
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    if args.release_dir:
        print(json.dumps(validate_windows_release(Path(args.release_dir),require_installer=not args.gpu,gpu=args.gpu), indent=2, sort_keys=True))
    if not args.source_gate and not args.release_dir and not args.scope_gate:
        parser.error("choose --source-gate, --scope-gate and/or --release-dir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
