"""Create a privacy-conscious, shareable Image Draw Bot diagnostics ZIP."""
from __future__ import annotations

import hashlib
import importlib.metadata
from contextlib import contextmanager
from heapq import nsmallest, nlargest
import json
import math
import os
import platform
import stat
import sys
import time
import tempfile
import uuid
import zipfile
from pathlib import Path

from LocalSanitization import sanitize_text, safe_context
from RuntimePaths import data_dir
from SessionRecovery import diagnostics_summary
from Version import APP_VERSION, BUILD_CHANNEL, FILE_VERSION

DIAGNOSTICS_DIR = data_dir() / 'diagnostics'
MAX_LOG_CHARS = 500_000
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_SUMMARY_FILES = 100


def _check_cancelled(cancelled):
    if cancelled():
        raise InterruptedError('Diagnostics export cancelled.')


def _cancellable_items(items, cancelled):
    for item in items:
        _check_cancelled(cancelled)
        yield item
    _check_cancelled(cancelled)


def _regular_input(path: Path, base: Path) -> bool:
    """Collect local regular files, without following substituted links."""
    try:
        relative = path.relative_to(base)
        current = base
        for part in relative.parts:
            current = current / part
            metadata = current.lstat()
            if (stat.S_ISLNK(metadata.st_mode)
                    or getattr(metadata, 'st_reparse_tag', 0) in (0xA0000003, 0xA000000C)):
                return False
        return path.is_file() and path.resolve().is_relative_to(base.resolve())
    except InterruptedError:
        raise
    except (OSError, ValueError):
        return False


def _json_input(path: Path, base: Path, *, cancelled=lambda: False):
    _check_cancelled(cancelled)
    if not _regular_input(path, base):
        return None
    try:
        with path.open('rb') as stream:
            data = stream.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            return None
        _check_cancelled(cancelled)
        result = json.loads(data)
        _check_cancelled(cancelled)
        return data, result
    except InterruptedError:
        raise
    except (OSError, ValueError, UnicodeDecodeError, TypeError, RecursionError):
        return None


@contextmanager
def _atomic_archive(path: Path, *, cancelled=lambda: False):
    _check_cancelled(cancelled)
    descriptor, temporary = tempfile.mkstemp(prefix='.diagnostics-', suffix='.tmp', dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        archive = zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED)
        try:
            yield archive
        except BaseException as failure:
            try:
                archive.close()
            except Exception as error:
                failure.add_note(f'Diagnostics archive cleanup also failed: {type(error).__name__}.')
            raise
        else:
            archive.close()
        _check_cancelled(cancelled)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            failure = sys.exc_info()[1]
            try:
                temporary.unlink(missing_ok=True)
            except OSError as error:
                if failure is None:
                    raise
                failure.add_note(f'Diagnostics staging cleanup also failed: {type(error).__name__}.')


def _package_versions(issues=None, *, cancelled=lambda: False):
    result = {}
    for name in ('Pillow', 'requests', 'keyboard', 'tkinterdnd2', 'customtkinter', 'cupy-cuda12x', 'cupy'):
        _check_cancelled(cancelled)
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
        except InterruptedError:
            raise
        except (OSError, ValueError, TypeError) as error:
            # A broken optional distribution is itself useful diagnostic
            # evidence, not a reason to lose the application's readable logs.
            if issues is not None:
                issues.append({'section': 'package-version', 'package': name,
                               'error': type(error).__name__})
    _check_cancelled(cancelled)
    return result


def _memory_total_mb():
    try:
        if os.name == 'nt':
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_=[('dwLength',ctypes.c_uint32),('dwMemoryLoad',ctypes.c_uint32),
                          ('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),
                          ('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),
                          ('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),
                          ('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
            status=MEMORYSTATUSEX();status.dwLength=ctypes.sizeof(status)
            from WindowsSystem import load_system_library
            memory_status=load_system_library('kernel32').GlobalMemoryStatusEx
            memory_status.argtypes=[ctypes.POINTER(MEMORYSTATUSEX)]
            memory_status.restype=ctypes.c_int
            if memory_status(ctypes.byref(status)):
                return int(status.ullTotalPhys // (1024*1024))
        pages=os.sysconf('SC_PHYS_PAGES'); page_size=os.sysconf('SC_PAGE_SIZE')
        return int(pages*page_size//(1024*1024))
    except InterruptedError:
        raise
    except Exception:
        return None


def _technical_info(context=None, *, cancelled=lambda: False):
    _check_cancelled(cancelled)
    collection_issues = []
    packages = _package_versions(collection_issues, cancelled=cancelled)
    _check_cancelled(cancelled)
    info = {
        'app':'Image Draw Bot', 'app_version':APP_VERSION, 'file_version':FILE_VERSION,
        'channel':BUILD_CHANNEL, 'created_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'platform':platform.platform(), 'python':platform.python_version(),
        'architecture':platform.machine(), 'cpu_logical':os.cpu_count(),
        'ram_total_mb':_memory_total_mb(), 'frozen':bool(getattr(sys,'frozen',False)),
        'packages':packages, 'recovery':diagnostics_summary(),
        'collection_issues':collection_issues,
        'privacy': {
            'source_images_included': False,
            'cached_recovery_image_included': False,
            'clipboard_included': False,
            'credentials_redacted': True,
        },
    }
    if isinstance(context, dict):
        info['app_context']=safe_context(context)
    info['gpu']={'probe_skipped':True,'reason':'Diagnostics collection must not initialize a potentially failing CUDA driver.'}
    _check_cancelled(cancelled)
    return info


def _read_text(path: Path, limit=MAX_LOG_CHARS, *, cancelled=lambda: False):
    _check_cancelled(cancelled)
    if limit <= 0:
        return ''
    omitted = False
    try:
        with path.open('rb') as stream:
            stream.seek(0,2)
            length=stream.tell()
            start=max(0,length-limit*4)
            if start:
                omitted = True
                stream.seek(start-1)
                at_line_start=stream.read(1)==b'\n'
            else:
                stream.seek(0)
                at_line_start=True
            data=stream.read(limit*4)
            if not at_line_start:
                # A cut URL/header can leave an unrecognizable secret tail.
                # Discard the partial line within the already bounded buffer;
                # if it has no newline, none of that line is safe to export.
                newline=data.find(b'\n')
                data=data[newline+1:] if newline>=0 else b''
    except InterruptedError:
        raise
    except OSError:
        return None
    _check_cancelled(cancelled)
    text=sanitize_text(data.decode('utf-8',errors='replace'))
    if len(text)>limit:
        omitted=True
        text=text[-limit:]
    _check_cancelled(cancelled)
    return ('[older content omitted]\n' if omitted else '')+text


def _summary_profile_key(context):
    value = context.get('profile_key') if isinstance(context, dict) else None
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        return None
    from ProfileStorage import safe_profile_key
    try:
        return safe_profile_key(value)
    except UnicodeError:
        return None


def _summary_paths(base, kind, profile_key, cancelled):
    preferred = None
    if profile_key:
        preferred = base / (f'{kind}.json' if profile_key == 'generic' else f'{kind}-{profile_key}.json')
    candidates = _cancellable_items(base.glob(f'{kind}*.json'), cancelled)
    # Reserve the first candidate for the active profile without increasing
    # the cap or retaining all paths. Ordinary standalone selection preserves
    # its existing lexical order. Every selected input still passes link/read
    # validation before it receives an opaque archive label.
    key = (lambda path: (path != preferred, path)) if preferred is not None else None
    return nsmallest(MAX_SUMMARY_FILES, candidates, key=key), preferred


def _settings_summary(*, profile_key=None, selection=None, cancelled=lambda: False):
    _check_cancelled(cancelled)
    result={}
    base=data_dir()
    paths, preferred = _summary_paths(base, 'settings', profile_key, cancelled)
    for path in paths:
        loaded = _json_input(path, base, cancelled=cancelled)
        if loaded is None:
            continue
        _, raw = loaded
        if not isinstance(raw,dict):continue
        # Screen coordinates and any future path/url-like fields are intentionally removed.
        raw.pop('corners',None)
        # Filenames can contain the same local credentials as settings values.
        # Opaque labels also preserve separate records when redaction would
        # collapse two secret-bearing names to the same dictionary key.
        label = f'settings-{len(result)+1:03d}.json'
        result[label] = safe_context(raw)
        if selection is not None and path == preferred:
            selection['settings'] = label
    _check_cancelled(cancelled)
    return result


def _calibration_summary(*, profile_key=None, selection=None, cancelled=lambda: False):
    _check_cancelled(cancelled)
    result={}
    base=data_dir()
    paths, preferred = _summary_paths(base, 'calibration', profile_key, cancelled)
    for path in paths:
        loaded = _json_input(path, base, cancelled=cancelled)
        if loaded is None:
            continue
        data, raw = loaded
        summary={'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}
        if isinstance(raw,dict):
            colors=raw.get('colors')
            version = raw.get('version')
            if isinstance(version, str):
                version = sanitize_text(version)[:200]
            elif type(version) not in (int, float) or (isinstance(version, float) and not math.isfinite(version)):
                version = None
            summary['version']=version
            summary['color_count']=len(colors) if isinstance(colors,list) else None
            summary['has_anchor']=bool(raw.get('anchor') or raw.get('client_rect'))
        label = f'calibration-{len(result)+1:03d}.json'
        result[label] = summary
        if selection is not None and path == preferred:
            selection['calibration'] = label
    _check_cancelled(cancelled)
    return result


def create_diagnostics_package(context=None, *, cancelled=lambda: False) -> Path:
    """Collect a bounded local export, checking Stop between files/sections."""
    _check_cancelled(cancelled)
    DIAGNOSTICS_DIR.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S')
    path=DIAGNOSTICS_DIR/f'ImageDrawBot-Diagnostics-{stamp}-{uuid.uuid4().hex[:8]}.zip'
    profile_key = _summary_profile_key(context)
    selection = {'active_profile_requested': profile_key is not None,
                 'settings': None, 'calibration': None, 'candidate_limit_per_kind': MAX_SUMMARY_FILES}
    with _atomic_archive(path, cancelled=cancelled) as archive:
        # JSON escapes also represent an isolated surrogate from a damaged
        # local record without making UTF-8 ZIP serialization fail.
        archive.writestr('system.json',json.dumps(_technical_info(context,cancelled=cancelled),indent=2,ensure_ascii=True))
        _check_cancelled(cancelled)
        archive.writestr('settings-summary.json',json.dumps(_settings_summary(
            profile_key=profile_key, selection=selection, cancelled=cancelled),indent=2,ensure_ascii=True))
        _check_cancelled(cancelled)
        archive.writestr('calibration-summary.json',json.dumps(_calibration_summary(
            profile_key=profile_key, selection=selection, cancelled=cancelled),indent=2,ensure_ascii=True))
        _check_cancelled(cancelled)
        archive.writestr('profile-summary-selection.json',json.dumps(selection,indent=2,ensure_ascii=True))
        _check_cancelled(cancelled)
        archive.writestr('README.txt',
            'Image Draw Bot diagnostics package.\n\n'
            'profile-summary-selection.json identifies the active profile by opaque keys in the settings/calibration summaries, when its files were available. '
            'Privacy: source images, the local recovery image cache, clipboard contents and raw palette/tool screen coordinates are not included. '
            'Logs are sanitized for user-home paths and credential-like strings.\n')
        log_dir=data_dir()/'logs'
        for name in ('ImageDrawBot-session.log','ImageDrawBot-session.log.1','ImageDrawBot-crash.log','ImageDrawBot-crash.log.1',
                     'ImageDrawBot-debug-errors.log','ImageDrawBot-debug-errors.log.1',
                     'ImageDrawBot-target-probe.log','ImageDrawBot-mouse-probe.log'):
            _check_cancelled(cancelled)
            if not _regular_input(log_dir/name, data_dir()):
                continue
            text=_read_text(log_dir/name,cancelled=cancelled)
            if text:
                archive.writestr(f'logs/{name}',text)
        from CrashDumpConfig import user_dump_folder
        dumps=user_dump_folder()
        def dump_candidates():
            for dump in _cancellable_items(dumps.glob('*.dmp'),cancelled):
                try:
                    info=dump.stat()
                except InterruptedError:raise
                except OSError:continue
                if stat.S_ISREG(info.st_mode):
                    yield (info.st_mtime, dump.name, info.st_size)
        inventory = [{'name':sanitize_text(name),'bytes':size}
                     for _,name,size in nlargest(5, dump_candidates())] if dumps.is_dir() else []
        archive.writestr('dump-files.json',json.dumps({'files':inventory,'memory_dumps_included':False},indent=2))
        _check_cancelled(cancelled)
    return path


def main(*, cancelled=lambda: False):
    try:
        path=create_diagnostics_package(cancelled=cancelled)
        _check_cancelled(cancelled)
    except InterruptedError:
        raise
    except Exception as error:
        print(f'Could not collect diagnostics: {error}')
        if getattr(sys,'frozen',False):
            from tkinter import messagebox
            messagebox.showerror('Diagnostics failed',str(error))
        return 1
    print(f'Diagnostics ZIP: {path}')
    if os.name=='nt':
        _check_cancelled(cancelled)
        try:
            os.startfile(str(path.parent))
        except (OSError, NotImplementedError):
            _check_cancelled(cancelled)
            print('The ZIP was saved successfully. Its folder could not be opened automatically; use the path above.')
            if getattr(sys,'frozen',False):
                # The windowed helper has no console in which to read that
                # path. Give it the same concrete result as the GUI workflow.
                try:
                    from tkinter import messagebox
                    messagebox.showinfo('Diagnostics saved',f'Your diagnostics ZIP was saved at:\n{path}\n\nIts folder could not be opened automatically.')
                except Exception:
                    pass
    return 0

if __name__=='__main__':raise SystemExit(main())
