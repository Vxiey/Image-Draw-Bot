"""Owned, bounded cache of already verified installer downloads.

No cache entry authorizes execution: launch_installer still hashes the file
while its Windows handle denies writes and deletion. Older loose downloads and
anything outside this explicitly marked directory are never retired here.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat

from RuntimePaths import atomic_write_text, file_transaction

CACHE_DIRECTORY = 'verified-installers-v1'
MAX_CACHED_INSTALLERS = 2
_OWNER_NAME = 'ownership.txt'
_OWNER_TEXT = 'Image Draw Bot verified installer cache, version 1.\n'
_INSTALLER_NAME = re.compile(r'ImageDrawBot-[0-9a-f]{64}\.exe', re.ASCII)


def _unlinked_metadata(path):
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(value.st_mode) or getattr(value, 'st_reparse_tag', 0):
        raise OSError('The local installer cache contains an unexpected link.')
    return value


@contextmanager
def _owned_cache(root, *, create=False, check=lambda: None):
    cache = Path(root) / CACHE_DIRECTORY
    metadata = _unlinked_metadata(cache)
    if metadata is None:
        if not create:
            yield None
            return
        cache.mkdir(mode=0o700, exist_ok=True)
        metadata = _unlinked_metadata(cache)
    if metadata is None or not stat.S_ISDIR(metadata.st_mode):
        raise OSError('The local installer cache is not a directory.')
    marker = cache / _OWNER_NAME
    lock = _unlinked_metadata(marker.with_name(marker.name + '.lock'))
    if lock is not None and not stat.S_ISREG(lock.st_mode):
        raise OSError('The local installer cache lock is invalid.')
    with file_transaction(marker):
        check()
        marker_info = _unlinked_metadata(marker)
        if marker_info is None:
            # Claim only a newly created/empty directory. Existing unmarked
            # user files must not become our eviction candidates.
            if not create or any(path.name != marker.name + '.lock' for path in cache.iterdir()):
                raise OSError('The local installer cache has no valid ownership marker.')
            atomic_write_text(marker, _OWNER_TEXT)
            marker_info = marker.stat()
        if (not stat.S_ISREG(marker_info.st_mode)
                or marker_info.st_size != len(_OWNER_TEXT.encode('utf-8'))):
            raise OSError('The local installer cache ownership marker is invalid.')
        with marker.open('rb') as stream:
            if stream.read(len(_OWNER_TEXT) + 1) != _OWNER_TEXT.encode('utf-8'):
                raise OSError('The local installer cache ownership marker is invalid.')
        yield cache


def _matches(path, asset, check):
    metadata = _unlinked_metadata(path)
    if (metadata is None or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size != asset['size']):
        return False
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size != asset['size']:
                return False
            if stream.read(2) != b'MZ':
                return False
            stream.seek(0)
            while True:
                check()
                block = stream.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > asset['size']:
                    return False
                digest.update(block)
    except (FileNotFoundError, PermissionError):
        return False
    check()
    return total == asset['size'] and digest.hexdigest() == asset['sha256']


def _cleanup_note(error):
    from CrashDiagnostics import log_error
    log_error(f'Installer cache maintenance failed: {type(error).__name__}', category='update-cache')


def _retain(cache, current, check):
    """Retain the current and most recently used previous owned installer.

    Windows can keep an installer executable locked while it runs. A failed
    eviction is retried on the next cache use, never forced or made executable.
    """
    try:
        os.utime(current, None)
    except OSError as error:
        _cleanup_note(error)
    candidates = []
    try:
        for path in cache.iterdir():
            check()
            if path == current or _INSTALLER_NAME.fullmatch(path.name) is None:
                continue
            try:
                metadata = _unlinked_metadata(path)
                if metadata is not None and stat.S_ISREG(metadata.st_mode):
                    candidates.append((metadata.st_mtime_ns, path.name, path))
            except OSError as error:
                _cleanup_note(error)
    except InterruptedError:
        raise
    except OSError as error:
        _cleanup_note(error)
        return
    candidates.sort(reverse=True)
    for _, _, path in candidates[max(0, MAX_CACHED_INSTALLERS - 1):]:
        check()
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            _cleanup_note(error)


def find_verified_installer(root, asset, *, check=lambda: None):
    with _owned_cache(root, check=check) as cache:
        if cache is None:
            return None
        path = cache / f'ImageDrawBot-{asset["sha256"]}.exe'
        if not _matches(path, asset, check):
            return None
        _retain(cache, path, check)
        return path


def publish_verified_installer(root, staging, asset, *, check=lambda: None):
    # The caller has finished downloading, fsyncing and verifying the staging
    # file. Cooperating publications and evictions share this stable lock.
    with _owned_cache(root, create=True, check=check) as cache:
        path = cache / f'ImageDrawBot-{asset["sha256"]}.exe'
        if not _matches(path, asset, check):
            metadata = _unlinked_metadata(path)
            if metadata is not None and not stat.S_ISREG(metadata.st_mode):
                raise OSError('The local installer cache entry is not a regular file.')
            check()
            os.replace(staging, path)
        _retain(cache, path, check)
        check()
        return path
