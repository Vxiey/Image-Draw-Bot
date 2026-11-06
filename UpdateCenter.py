"""User-triggered GitHub release checks and verified Windows installer updates."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Iterable
from urllib.parse import quote, unquote, urljoin, urlparse

from Version import APP_VERSION, BUILD_CHANNEL

GITHUB_REPOSITORY = "Vxiey/Image-Draw-Bot"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases?per_page=100"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPOSITORY}/releases"
_INSTALLER_HOSTS = frozenset({
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
})
_MAX_REDIRECTS = 5
_MAX_RELEASE_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_RELEASE_CHECK_SECONDS = 30
_DOWNLOAD_SPACE_RESERVE = 8 * 1024 * 1024

_STAGE_RANK = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2, "stable": 3, "final": 3}
_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:[-_.]?(?P<stage>alpha|a|beta|b|rc)(?:[-_.]?(?P<num>\d+))?)?$",
    re.IGNORECASE | re.ASCII,
)


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    stage_rank: int
    stage_number: int

    def key(self) -> tuple[int, int, int, int, int]:
        return (self.major, self.minor, self.patch, self.stage_rank, self.stage_number)


def normalize_tag(tag: object) -> str:
    text = str(tag or "").strip()
    return text[1:] if text[:1].lower() == "v" else text


def parse_version(value: object) -> ParsedVersion | None:
    text = normalize_tag(value)
    if len(text) > 128:
        return None
    match = _VERSION_RE.fullmatch(text)
    if not match:
        return None
    stage = (match.group("stage") or "stable").lower()
    return ParsedVersion(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        _STAGE_RANK.get(stage, 0),
        int(match.group("num") or 0),
    )


def is_newer_version(candidate: object, current: object = APP_VERSION) -> bool:
    candidate_version = parse_version(candidate)
    current_version = parse_version(current)
    if candidate_version is None or current_version is None:
        return False
    return candidate_version.key() > current_version.key()


def _release_allowed(release: dict, channel: str) -> bool:
    if not isinstance(release, dict) or bool(release.get("draft")):
        return False
    tag = normalize_tag(release.get("tag_name"))
    parsed = parse_version(tag)
    if parsed is None:
        return False
    channel = str(channel or "beta").lower()
    if channel == "stable":
        return not bool(release.get("prerelease")) and parsed.stage_rank >= _STAGE_RANK["stable"]
    if channel == "rc":
        return parsed.stage_rank >= _STAGE_RANK["rc"]
    if channel == "beta":
        return parsed.stage_rank >= _STAGE_RANK["beta"]
    return True


def select_best_release(releases: Iterable[dict], *, channel: str | None = None) -> dict | None:
    channel = BUILD_CHANNEL if channel is None else str(channel)
    candidates = [item for item in releases if _release_allowed(item, channel)]
    if not candidates:
        return None
    candidates.sort(key=lambda item: parse_version(item.get("tag_name")).key(), reverse=True)
    return candidates[0]


def _validate_https_url(url, hosts):
    """Validate a destination before any request, including every redirect hop."""
    try:
        if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
            raise ValueError("Invalid URL characters")
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in hosts
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError("Untrusted destination")
    except (TypeError, ValueError) as error:
        raise UpdateCheckError("Update request redirected to an unexpected destination.") from error


def _request_without_redirects(url, **options):
    import requests

    class NoRedirectsSession(requests.Session):
        def resolve_redirects(self, *args, **kwargs):
            # Requests normally drains a redirect body to prepare Response.next,
            # even with allow_redirects=False. Keep redirect bodies unread so our
            # destination checks and response limits run before consuming them.
            return iter(())

    with NoRedirectsSession() as session:
        return session.get(url, **options)


def _check_transfer_budget(cancelled, deadline):
    if cancelled():
        raise InterruptedError("Update cancelled.")
    if deadline is not None and time.monotonic() > deadline:
        raise UpdateCheckError("Update request timed out. Check the connection and try again.")


def _raise_rate_limit(response):
    status = getattr(response, "status_code", 200)
    headers = getattr(response, "headers", {})
    if status == 429 or (status == 403 and headers.get("X-RateLimit-Remaining") == "0"):
        retry = str(headers.get("Retry-After", ""))
        detail = f" Retry in {int(retry)} seconds." if re.fullmatch(r"[0-9]{1,7}", retry) else " Try again later."
        raise UpdateCheckError("GitHub's request limit was reached." + detail + " You can still open the Releases page.")


def _close_response(response):
    """A transport cleanup error must not replace cancellation or verification."""
    if response is None or not hasattr(response, 'close'):
        return
    try:
        response.close()
    except Exception as error:
        # Keep the successful verified result (or primary exception) intact.
        # Log only the exception class, never signed redirect URLs/headers.
        from CrashDiagnostics import log_error
        log_error(f'Update response cleanup failed: {type(error).__name__}', category='update-cleanup')


def _get_trusted_response(url, *, request_get, hosts, cancelled=lambda: False, deadline=None, **options):
    """Follow only validated HTTPS redirects and close every discarded response."""
    for hop in range(_MAX_REDIRECTS + 1):
        _validate_https_url(url, hosts)
        _check_transfer_budget(cancelled, deadline)
        try:
            response = request_get(url, allow_redirects=False, **options)
        except ValueError as error:
            # Requests may parse a Location header while preparing Response.next,
            # even when automatic redirects are disabled.
            raise UpdateCheckError("Update request has an invalid URL or redirect.") from error
        accepted = False
        try:
            _validate_https_url(getattr(response, "url", url), hosts)
            _check_transfer_budget(cancelled, deadline)
            _raise_rate_limit(response)
            response.raise_for_status()
            status = getattr(response, "status_code", 200)
            if status == 200:
                accepted = True
                return response
            if status not in (301, 302, 303, 307, 308):
                raise UpdateCheckError(f"Unexpected update response status: {status}.")
            if hop == _MAX_REDIRECTS:
                raise UpdateCheckError("Too many redirects while checking or downloading an update.")
            location = getattr(response, "headers", {}).get("Location")
            if not isinstance(location, str) or not location:
                raise UpdateCheckError("Update redirect has no destination.")
            # Validate the resolved URL on the next iteration, before requesting it.
            try:
                url = urljoin(url, location)
            except ValueError as error:
                raise UpdateCheckError("Update redirect has an invalid destination.") from error
        finally:
            if not accepted:
                _close_response(response)


def check_for_updates(*, request_get=None, timeout=(4, 8), cancelled=lambda: False) -> dict:
    """Check GitHub Releases after an explicit user action.

    ``request_get`` exists for deterministic unit tests. Production calls use
    a Requests session and send only a generic User-Agent/Accept header.
    """
    if request_get is None:
        request_get = _request_without_redirects
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ImageDrawBot/{APP_VERSION}",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    response = None
    deadline = time.monotonic() + _MAX_RELEASE_CHECK_SECONDS
    try:
        response = _get_trusted_response(
            GITHUB_RELEASES_API, request_get=request_get, hosts={"api.github.com"},
            headers=headers, timeout=timeout, stream=True,
            cancelled=cancelled, deadline=deadline,
        )
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            _check_transfer_budget(cancelled, deadline)
            if len(body) + len(chunk) > _MAX_RELEASE_RESPONSE_BYTES:
                raise UpdateCheckError("GitHub release metadata exceeds the allowed size.")
            body.extend(chunk)
        _check_transfer_budget(cancelled, deadline)
        releases = json.loads(body)
    except InterruptedError:
        raise
    except Exception as error:
        raise UpdateCheckError(f"Could not check GitHub Releases: {error}") from error
    finally:
        _close_response(response)
    if not isinstance(releases, list):
        raise UpdateCheckError("GitHub returned an unexpected releases response.")

    release = select_best_release(releases)
    if release is None:
        return {
            "current_version": APP_VERSION,
            "latest_version": "",
            "update_available": False,
            "release_url": GITHUB_RELEASES_PAGE,
            "release_name": "",
            "prerelease": False,
            "message": "No published Image Draw Bot release was found yet.",
        }

    latest = normalize_tag(release.get("tag_name"))
    available = is_newer_version(latest, APP_VERSION)
    # The page is always in this repository, even if response metadata contains
    # an unrelated/malformed html_url. The tag has already passed our parser.
    tag = str(release.get("tag_name") or "").strip()
    url = f"{GITHUB_RELEASES_PAGE}/tag/{quote(tag, safe='')}"
    name = str(release.get("name") or release.get("tag_name") or latest)[:160]
    message = f"Download version {latest}" if available else "You are on the latest version."
    return {
        "current_version": APP_VERSION,
        "latest_version": latest,
        "update_available": available,
        "release_url": url,
        "release_name": name,
        "prerelease": bool(release.get("prerelease")),
        "message": message,
        "installer": installer_asset(release),
    }


def installer_asset(release):
    """Return the verified Image Draw Bot installer for a release."""
    if not isinstance(release, dict):return None
    version=normalize_tag(release.get('tag_name'))
    if parse_version(version) is None:return None
    name=f'ImageDrawBot-{version}-Windows-x64-Setup.exe'
    assets=release.get('assets') or ()
    if not isinstance(assets, (list, tuple)):return None
    hits=[]
    for asset in assets:
        if not isinstance(asset,dict) or asset.get('name')!=name:continue
        if asset.get('state', 'uploaded') != 'uploaded':continue
        url=str(asset.get('browser_download_url') or '')
        try:parsed=urlparse(url)
        except ValueError:continue
        valid_path=f'/{GITHUB_REPOSITORY}/releases/download/{release["tag_name"]}/{name}'
        if parsed.scheme!='https' or parsed.netloc!='github.com' or unquote(parsed.path)!=valid_path or parsed.query or parsed.fragment:continue
        digest=str(asset.get('digest') or '')
        if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest):continue
        size=asset.get('size')
        if type(size) is not int or not 0<size<=2*1024**3:continue
        hits.append(dict(name=name,url=url,sha256=digest[7:].lower(),size=size,version=version))
    return hits[0] if len(hits)==1 else None


def _validated_installer_metadata(asset):
    if not isinstance(asset, dict) or not isinstance(asset.get('url'), str):
        raise UpdateCheckError('Invalid installer metadata.')
    try:
        tag=unquote(urlparse(asset['url']).path.split('/')[-2])
    except (ValueError, IndexError) as error:
        raise UpdateCheckError('Invalid installer URL.') from error
    candidate=dict(tag_name=tag,assets=[dict(
        name=asset.get('name'),browser_download_url=asset['url'],
        digest='sha256:'+str(asset.get('sha256','')),size=asset.get('size'),
    )])
    validated=installer_asset(candidate)
    if validated is None or validated!=asset:
        raise UpdateCheckError('Invalid installer metadata.')
    return validated


def download_installer(asset, *, directory=None, request_get=None, cancelled=lambda:False, progress=lambda done,total:None):
    """Stream to a unique staging file; publish only after size/hash validation."""
    import hashlib,os,shutil,tempfile
    from pathlib import Path
    asset=_validated_installer_metadata(asset)
    if request_get is None:
        request_get=_request_without_redirects
    if directory is None:
        from RuntimePaths import data_dir
        directory=data_dir()/'updates'
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    if cancelled():raise InterruptedError('Update cancelled.')
    required=asset['size']+_DOWNLOAD_SPACE_RESERVE
    if shutil.disk_usage(root).free < required:
        raise UpdateCheckError(f'Not enough free space to download the update. Free at least {(required+1024**2-1)//1024**2} MiB and try again.')
    fd,temp=tempfile.mkstemp(prefix='download-',suffix='.part',dir=root)
    path=Path(temp);response=None
    try:
        total=0;digest=hashlib.sha256();deadline=time.monotonic()+1800
        try:
            output = os.fdopen(fd, 'wb')
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        with output:
            response=_get_trusted_response(
                asset['url'],request_get=request_get,hosts=_INSTALLER_HOSTS,
                cancelled=cancelled,deadline=deadline,stream=True,timeout=(5,15),
                headers={'User-Agent':f'ImageDrawBot/{APP_VERSION}', 'Accept-Encoding':'identity'},
            )
            response_headers=getattr(response,'headers',{})
            if str(response_headers.get('Content-Encoding','identity')).strip().lower() not in ('','identity'):
                raise UpdateCheckError('Unexpected installer content encoding. Nothing was installed.')
            declared=response_headers.get('Content-Length')
            if declared is not None and (not re.fullmatch(r'[0-9]{1,20}',str(declared)) or int(declared)!=asset['size']):
                raise UpdateCheckError('Installer response size differs from its published size.')
            for chunk in response.iter_content(chunk_size=256*1024):
                _check_transfer_budget(cancelled,deadline)
                if not chunk:continue
                total+=len(chunk)
                if total>asset['size']:raise UpdateCheckError('Installer exceeds its published size.')
                digest.update(chunk);output.write(chunk);progress(total,asset['size'])
            output.flush();os.fsync(output.fileno())
        _check_transfer_budget(cancelled, deadline)
        if total!=asset['size'] or digest.hexdigest()!=asset['sha256']:
            raise UpdateCheckError('Installer checksum or size mismatch. Nothing was installed; try again.')
        with path.open('rb') as check:
            if check.read(2)!=b'MZ':raise UpdateCheckError('Downloaded file is not a Windows installer.')
        destination=path.with_suffix('.exe');path.replace(destination)
        return str(destination)
    finally:
        import sys
        failure = sys.exc_info()[1]
        try:
            _close_response(response)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                if failure is None:
                    raise
                failure.add_note(f'Update staging cleanup also failed: {type(error).__name__}.')


def installer_launch_args(path, *, executable=None):
    """Build updater arguments without touching the OS, for deterministic tests."""
    import sys
    from pathlib import Path
    target=Path(path)
    current=Path(executable or sys.executable)
    args=[str(target),'/SP-','/NORESTART']
    installed=(current.name.lower()=='imagedrawbot.exe' and any(current.parent.glob('unins*.exe')))
    if installed:
        args.extend([
            '/VERYSILENT',
            '/SUPPRESSMSGBOXES',
            '/CLOSEAPPLICATIONS',
            '/RELAUNCHIMAGEDRAWBOT',
            '/DIR='+str(current.parent),
        ])
    return args


def launch_installer(path, asset, *, executable=None, launcher=None, cancelled=lambda:False):
    """Recheck staged bytes and launch the verified Windows updater."""
    import hashlib,os,stat,subprocess
    from pathlib import Path
    if os.name!='nt':raise UpdateCheckError('Automatic installation requires Windows.')
    asset=_validated_installer_metadata(asset)
    if cancelled():raise InterruptedError('Update cancelled.')
    target=Path(path).resolve(strict=True)
    digest=hashlib.sha256()
    # Deny writes and deletion until CreateProcess has opened the verified EXE.
    # Hashing an ordinary shared file and closing it before launch leaves a
    # replace/modify window between verification and execution.
    with _open_locked_installer(target) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size!=asset['size']:
            raise UpdateCheckError('Installer changed after download; check for updates again.')
        if stream.read(2)!=b'MZ':raise UpdateCheckError('Invalid installer.')
        stream.seek(0)
        size=0
        for block in iter(lambda:stream.read(1024*1024),b''):
            if cancelled():raise InterruptedError('Update cancelled.')
            size+=len(block)
            if size>asset['size']:raise UpdateCheckError('Installer changed after download.')
            digest.update(block)
        if size!=asset['size'] or digest.hexdigest()!=asset['sha256']:
            raise UpdateCheckError('Installer changed after download; check for updates again.')
        args=installer_launch_args(target,executable=executable)
        if cancelled():raise InterruptedError('Update cancelled.')
        return (launcher or subprocess.Popen)(args)


def _open_locked_installer(path):
    """Return a Windows file stream whose handle denies writes and deletion."""
    import ctypes
    import msvcrt
    import os
    from WindowsSystem import load_system_library
    kernel=load_system_library('kernel32.dll',use_last_error=True)
    create=kernel.CreateFileW
    create.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,
                     ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    create.restype=ctypes.c_void_p
    handle=create(str(path),0x80000000,0x1,None,3,0x80,None)
    if handle in (None,ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
    except BaseException:
        close=kernel.CloseHandle
        close.argtypes=[ctypes.c_void_p]
        close.restype=ctypes.c_int
        close(handle)
        raise
    try:
        return os.fdopen(fd,'rb')
    except BaseException:
        os.close(fd)
        raise
