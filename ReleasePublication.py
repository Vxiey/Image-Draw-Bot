"""Publish a locally validated release set with exception rollback.

The files in a release are related; replacing its ZIP before compiling the
installer leaves old checksums pointing at new bytes when compilation fails.
This transaction starts only after every candidate has passed the release gate.
It does not promise crash-atomic publication across multiple filesystem names.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import stat
import tempfile

from RuntimePaths import _replace_with_retry, file_transaction


def _regular_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_reparse_tag', 0):
        raise ValueError('Release publication encountered a linked or non-regular artifact.')


def publish_release(staging, destination, names, *, obsolete=()):
    """Move only the selected candidate set; restore originals on move errors.

    Old assets stay in a private backup until every new file is installed.
    A rollback failure deliberately retains those backups and reports where
    they can be recovered. Memory use is independent of artifact file sizes.
    """
    staging, destination = Path(staging), Path(destination)
    selected = tuple(names)
    retired = tuple(obsolete)
    all_names = selected + retired
    if (any(not isinstance(name, str) or not name or name in ('.', '..')
            or '/' in name or '\\' in name or ':' in name for name in all_names)
            or len({name.casefold() for name in all_names}) != len(all_names)):
        raise ValueError('Release publication requires distinct artifact basenames.')
    for name in selected:
        _regular_file(staging/name)
    destination.mkdir(parents=True, exist_ok=True)
    with file_transaction(destination/'.release-publication'):
        previous = []
        for name in all_names:
            try:
                _regular_file(destination/name)
            except FileNotFoundError:
                continue
            previous.append(name)
        backup = Path(tempfile.mkdtemp(prefix='.release-backup-', dir=destination))
        backed_up = []
        installed = []
        try:
            for name in previous:
                _replace_with_retry(destination/name, backup/name)
                backed_up.append(name)
            for name in selected:
                _replace_with_retry(staging/name, destination/name)
                installed.append(name)
        except BaseException as error:
            rollback_errors = []
            for name in reversed(installed):
                if name in backed_up:
                    continue  # Restore its original by atomic replacement below.
                try:
                    (destination/name).unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
            for name in reversed(backed_up):
                try:
                    _replace_with_retry(backup/name, destination/name)
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                error.add_note(f'Release rollback needs manual recovery from: {backup}')
            else:
                try:
                    backup.rmdir()
                except OSError as cleanup_error:
                    error.add_note(f'Release backup cleanup also failed: {type(cleanup_error).__name__}.')
            raise
        else:
            # Cleanup is after the commit point. It cannot turn a complete
            # validated release into a rollback that has lost some originals.
            try:
                shutil.rmtree(backup)
            except OSError:
                print(f'Release published; temporary backup cleanup can be retried at: {backup}')
