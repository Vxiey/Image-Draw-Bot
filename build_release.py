"""Create and validate a release-grade Windows package for Image Draw Bot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from Version import APP_VERSION, FILE_VERSION, BUILD_CHANNEL
from ReleaseCandidateHardening import run_source_release_gate, validate_windows_release
from RuntimePaths import _replace_with_retry, atomic_write_text

BASE = Path(__file__).resolve().parent
DIST = BASE / "dist" / "ImageDrawBot"
RELEASE = BASE / "release"


def run(command: list[str], *, cwd: Path = BASE) -> None:
    print("+", " ".join(map(str, command)))
    subprocess.run(command, cwd=cwd, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_pe_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open('rb') as stream:
        return stream.read(2) == b'MZ'


def zip_onedir(destination: Path) -> None:
    destination = Path(destination)
    def regular(path, directory=False):
        info = path.lstat()
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected(info.st_mode) or getattr(info, 'st_reparse_tag', 0) in (0xA0000003, 0xA000000C):
            raise ValueError(f'Release distribution contains a link or non-regular entry: {path.name}')
    def walk_error(error):
        raise error
    regular(DIST, directory=True)
    files = []
    for current, directories, names in os.walk(DIST, followlinks=False, onerror=walk_error):
        for name in directories:
            regular(Path(current) / name, directory=True)
        for name in names:
            path = Path(current) / name
            regular(path)
            files.append(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.runtime-release-', suffix='.tmp', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(files):
                relative = Path("ImageDrawBot") / path.relative_to(DIST)
                info = zipfile.ZipInfo(relative.as_posix(), (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = archive.compresslevel
                with path.open('rb') as source, archive.open(info, 'w', force_zip64=True) as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        with zipfile.ZipFile(temporary, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                raise ValueError(f"Release ZIP failed integrity at {bad}")
        _replace_with_retry(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def find_iscc() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    found = shutil.which("iscc") or shutil.which("ISCC.exe")
    if found:
        candidates.insert(0, Path(found))
    return next((path for path in candidates if path.is_file()), None)


def _clean_current_release_outputs(*, keep=()) -> None:
    RELEASE.mkdir(exist_ok=True)
    for pattern in (f"ImageDrawBot-{APP_VERSION}-*",):
        for path in RELEASE.glob(pattern):
            if path.is_file() and path.name not in keep:
                path.unlink()


def _write_manifest(artifacts: list[dict], *, signed=False) -> Path:
    path=RELEASE / f"ImageDrawBot-{APP_VERSION}-manifest.json"
    payload={
        "schema":1,
        "app":"Image Draw Bot",
        "version":APP_VERSION,
        "file_version":FILE_VERSION,
        "channel":BUILD_CHANNEL,
        "architecture":"windows-x64",
        "unsigned":not signed,
        "artifacts":artifacts,
    }
    atomic_write_text(path, json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+"\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signed", action="store_true", help="Require provisioned Authenticode signing; fail on any signing error")
    parser.add_argument("--installer", action="store_true", help="Also build the Inno Setup installer")
    parser.add_argument("--skip-tests", action="store_true", help="Skip duplicate tests only when CI already ran the complete gate")
    parser.add_argument("--gpu", action="store_true", help="Bundle optional NVIDIA CUDA/CuPy acceleration")
    args = parser.parse_args()
    if args.installer and args.gpu:
        parser.error("The CUDA release ships as a ZIP. Build the standard installer separately without --gpu.")
    signing=None
    if args.signed:
        from CodeSigning import signing_configuration,validate_certificate
        signing=signing_configuration()
        validate_certificate(signing)
    if sys.platform != "win32":
        raise SystemExit("Release EXEs must be built on Windows. Use the GitHub Actions release workflow or Build-Release.bat.")
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or later is required for the security-fixed Pillow 13 dependency.")
    github_ref=os.environ.get('GITHUB_REF_NAME','').strip()
    github_ref_type=os.environ.get('GITHUB_REF_TYPE','').strip()
    if github_ref_type == 'tag' and github_ref and github_ref != f'v{APP_VERSION}':
        raise SystemExit(f'Git tag {github_ref!r} does not match Version.py ({APP_VERSION}). Expected tag v{APP_VERSION}.')

    report=run_source_release_gate(BASE,soak_cycles=5000)
    print('RC source gate: PASS', report.as_dict())
    # Failed dependency/build steps must not erase previously completed assets.
    # The ZIP writer validates its staging file before replacing the old ZIP.
    RELEASE.mkdir(exist_ok=True)

    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "--upgrade", "--upgrade-strategy", "eager", "-r", str(BASE / "requirements.txt")])

    if not args.skip_tests:
        run([sys.executable, "-m", "unittest", "discover", "-v"])
        run([sys.executable, "DrawBot.py", "--self-test"])

    run([sys.executable, "build_exe.py"] + (["--gpu"] if args.gpu else []))
    exe = DIST / "ImageDrawBot.exe"
    if not is_pe_executable(exe):
        raise SystemExit("Release build did not produce a valid ImageDrawBot.exe.")
    run([str(exe), "--self-test"], cwd=DIST)

    if signing:
        from CodeSigning import sign_distribution
        sign_distribution(DIST,signing)

    suffix = "-CUDA" if args.gpu else ""
    zip_path = RELEASE / f"ImageDrawBot-{APP_VERSION}-Windows-x64{suffix}.zip"
    zip_onedir(zip_path)
    artifacts=[{"name":zip_path.name,"type":"windows-zip","sha256":sha256(zip_path),"bytes":zip_path.stat().st_size}]
    hash_rows = [f"{artifacts[-1]['sha256']}  {zip_path.name}"]

    if args.installer:
        iscc = find_iscc()
        if iscc is None:
            raise SystemExit("Inno Setup 6 was not found. Install it or run without --installer.")
        signing_args=[]
        if signing:
            from CodeSigning import inno_arguments
            signing_args=inno_arguments(signing)
        run([str(iscc), f"/DMyAppVersion={APP_VERSION}", *signing_args, str(BASE / "installer" / "ImageDrawBot.iss")])
        setup = RELEASE / f"ImageDrawBot-{APP_VERSION}-Windows-x64-Setup.exe"
        if not is_pe_executable(setup):
            raise SystemExit("Installer build did not produce the expected Setup.exe.")
        if signing:
            from CodeSigning import verify
            if not verify(setup,signing):raise SystemExit("Installer signature verification failed.")
        digest=sha256(setup)
        hash_rows.append(f"{digest}  {setup.name}")
        artifacts.append({"name":setup.name,"type":"inno-setup","sha256":digest,"bytes":setup.stat().st_size})

    checksum = RELEASE / f"ImageDrawBot-{APP_VERSION}-SHA256.txt"
    atomic_write_text(checksum, "\n".join(hash_rows) + "\n")
    manifest=_write_manifest(artifacts,signed=bool(signing))

    validate_windows_release(RELEASE,app_version=APP_VERSION,require_installer=args.installer,gpu=args.gpu)
    _clean_current_release_outputs(keep={item['name'] for item in artifacts} | {checksum.name, manifest.name})
    print("RC Windows artifact gate: PASS")
    print("\nRelease artifacts:")
    for row in hash_rows:
        print(" ", row)
    print(" ", checksum)
    print(" ", manifest)
    print("\nAuthenticode signatures verified." if signing else "\nUnsigned build: a trusted signing certificate is not configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
