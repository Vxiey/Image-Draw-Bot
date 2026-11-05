"""Create a privacy-conscious, shareable Image Draw Bot diagnostics ZIP."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
import uuid
import zipfile
from pathlib import Path

from LocalSanitization import sanitize_text, safe_context
from RuntimePaths import data_dir
from SessionRecovery import diagnostics_summary
from Version import APP_VERSION, BUILD_CHANNEL, FILE_VERSION

DIAGNOSTICS_DIR = data_dir() / 'diagnostics'
MAX_LOG_CHARS = 500_000


def _package_versions():
    result = {}
    for name in ('Pillow', 'requests', 'keyboard', 'tkinterdnd2', 'customtkinter', 'cupy-cuda12x', 'cupy'):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return result


def _memory_total_mb():
    try:
        if os.name == 'nt':
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),
                          ('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),
                          ('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),
                          ('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),
                          ('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
            status=MEMORYSTATUSEX();status.dwLength=ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys // (1024*1024))
        pages=os.sysconf('SC_PHYS_PAGES'); page_size=os.sysconf('SC_PAGE_SIZE')
        return int(pages*page_size//(1024*1024))
    except Exception:
        return None


def _technical_info(context=None):
    info = {
        'app':'Image Draw Bot', 'app_version':APP_VERSION, 'file_version':FILE_VERSION,
        'channel':BUILD_CHANNEL, 'created_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'platform':platform.platform(), 'python':platform.python_version(),
        'architecture':platform.machine(), 'cpu_logical':os.cpu_count(),
        'ram_total_mb':_memory_total_mb(), 'frozen':bool(getattr(sys,'frozen',False)),
        'packages':_package_versions(), 'recovery':diagnostics_summary(),
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
    return info


def _read_text(path: Path, limit=MAX_LOG_CHARS):
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
    except OSError:
        return None
    text=sanitize_text(data.decode('utf-8',errors='replace'))
    if len(text)>limit:
        omitted=True
        text=text[-limit:]
    return ('[older content omitted]\n' if omitted else '')+text


def _settings_summary():
    result={}
    base=data_dir()
    for path in sorted(base.glob('settings*.json')):
        try:
            raw=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError):
            continue
        if not isinstance(raw,dict):continue
        # Screen coordinates and any future path/url-like fields are intentionally removed.
        raw.pop('corners',None)
        result[path.name]=safe_context(raw)
    return result


def _calibration_summary():
    result={}
    base=data_dir()
    for path in sorted(base.glob('calibration*.json')):
        try:
            data=path.read_bytes()
            raw=json.loads(data.decode('utf-8'))
        except (OSError,ValueError,UnicodeDecodeError,TypeError):
            continue
        summary={'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}
        if isinstance(raw,dict):
            colors=raw.get('colors')
            summary['version']=raw.get('version')
            summary['color_count']=len(colors) if isinstance(colors,list) else None
            summary['has_anchor']=bool(raw.get('anchor') or raw.get('client_rect'))
        result[path.name]=summary
    return result


def create_diagnostics_package(context=None) -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S')
    path=DIAGNOSTICS_DIR/f'ImageDrawBot-Diagnostics-{stamp}-{uuid.uuid4().hex[:8]}.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('system.json',json.dumps(_technical_info(context),indent=2,ensure_ascii=False))
        archive.writestr('settings-summary.json',json.dumps(_settings_summary(),indent=2,ensure_ascii=False))
        archive.writestr('calibration-summary.json',json.dumps(_calibration_summary(),indent=2,ensure_ascii=False))
        archive.writestr('README.txt',
            'Image Draw Bot diagnostics package.\n\n'
            'Privacy: source images, the local recovery image cache, clipboard contents and raw palette/tool screen coordinates are not included. '
            'Logs are sanitized for user-home paths and credential-like strings.\n')
        log_dir=data_dir()/'logs'
        for name in ('ImageDrawBot-session.log','ImageDrawBot-session.log.1','ImageDrawBot-crash.log','ImageDrawBot-crash.log.1',
                     'ImageDrawBot-target-probe.log','ImageDrawBot-mouse-probe.log'):
            text=_read_text(log_dir/name)
            if text:
                archive.writestr(f'logs/{name}',text)
        dumps=Path(os.environ.get('LOCALAPPDATA',str(data_dir())))/'ImageDrawBot'/'dumps'
        inventory=[]
        if dumps.is_dir():
            candidates=[]
            for dump in dumps.glob('*.dmp'):
                try:
                    stat=dump.stat();candidates.append((stat.st_mtime,dump.name,stat.st_size))
                except OSError:continue
            inventory=[{'name':name,'bytes':size} for _,name,size in sorted(candidates,reverse=True)[:5]]
        archive.writestr('dump-files.json',json.dumps({'files':inventory,'memory_dumps_included':False},indent=2))
    return path


def main():
    try:
        path=create_diagnostics_package()
        print(f'Diagnostics ZIP: {path}')
        if os.name=='nt':os.startfile(str(path.parent))
        return 0
    except Exception as error:
        print(f'Could not collect diagnostics: {error}')
        if getattr(sys,'frozen',False):
            from tkinter import messagebox
            messagebox.showerror('Diagnostics failed',str(error))
        return 1

if __name__=='__main__':raise SystemExit(main())
