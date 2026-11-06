"""Opt-in Windows LocalDumps configuration, with scoped backup and restoration."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from RuntimePaths import atomic_write_text
from WindowsSystem import load_system_library

REG_BASE = r'SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps'
VALUE_NAMES = ('DumpFolder', 'DumpCount', 'DumpType')
EXECUTABLE_NAMES = ('ImageDrawBot.exe', 'python.exe', 'pythonw.exe')
MAX_BACKUP_BYTES = 1024 * 1024


def _validate_backup(state, reg):
    """Validate every restoration record before making any registry changes."""
    if not isinstance(state, dict) or any(name not in EXECUTABLE_NAMES for name in state):
        raise ValueError('Invalid LocalDumps backup executable; no changes made.')
    for saved in state.values():
        if not isinstance(saved, dict) or set(saved) != {'original', 'written'}:
            raise ValueError('Invalid LocalDumps backup record; no changes made.')
        for label in ('original', 'written'):
            values = saved[label]
            if not isinstance(values, dict) or set(values) - set(VALUE_NAMES):
                raise ValueError('Invalid LocalDumps backup values; no changes made.')
            if label == 'written' and set(values) != set(VALUE_NAMES):
                raise ValueError('Incomplete LocalDumps backup; no changes made.')
            for name, pair in values.items():
                if not isinstance(pair, list) or len(pair) != 2 or type(pair[1]) is not int:
                    raise ValueError('Invalid LocalDumps registry value; no changes made.')
                value, kind = pair
                if name == 'DumpFolder':
                    valid = (kind in (reg.REG_SZ, reg.REG_EXPAND_SZ) and isinstance(value, str)
                             and bool(value) and len(value) <= 32767 and '\x00' not in value)
                else:
                    valid = kind == reg.REG_DWORD and type(value) is int and 0 <= value <= 0xffffffff
                if not valid:
                    raise ValueError('Invalid LocalDumps registry type; no changes made.')
        if (saved['written']['DumpCount'] != [5, reg.REG_DWORD]
                or saved['written']['DumpType'] != [1, reg.REG_DWORD]
                or saved['written']['DumpFolder'][1] != reg.REG_EXPAND_SZ):
            raise ValueError('Unrecognized LocalDumps saved configuration; no changes made.')
    return state


def restore_values(current, written, original):
    """Restore only values still matching ours; retain later external changes."""
    result=dict(current)
    for name, value in written.items():
        if result.get(name) == value:
            if name in original:result[name]=original[name]
            else:result.pop(name,None)
    return result


def configure(action, include_python=False):
    if action not in ('enable', 'disable'):
        raise ValueError('Choose enable or disable.')
    if sys.platform != 'win32':raise OSError('Windows is required for native .dmp files.')
    import ctypes
    import winreg as reg
    is_admin = load_system_library('shell32').IsUserAnAdmin
    is_admin.argtypes = []
    is_admin.restype = ctypes.c_int
    if not is_admin():
        raise PermissionError('Right-click this BAT file and choose Run as administrator once. Start Image Draw Bot normally afterwards.')
    folder=Path(os.environ['LOCALAPPDATA'])/'ImageDrawBot'/'dumps'
    folder.mkdir(parents=True,exist_ok=True)
    backup=folder/'localdumps-backup.json'
    access=reg.KEY_READ|reg.KEY_WRITE|reg.KEY_WOW64_64KEY
    state = {}
    if backup.exists():
        with backup.open('rb') as stream:
            content = stream.read(MAX_BACKUP_BYTES + 1)
        if len(content) > MAX_BACKUP_BYTES:
            raise ValueError('LocalDumps backup is too large; no changes made.')
        state = json.loads(content)
    _validate_backup(state, reg)
    def read_values(name):
        try:
            with reg.OpenKey(reg.HKEY_LOCAL_MACHINE,REG_BASE+'\\'+name,0,access) as key:
                values={}
                for value_name in VALUE_NAMES:
                    try:value,kind=reg.QueryValueEx(key,value_name);values[value_name]=[value,kind]
                    except FileNotFoundError:pass
                return values
        except FileNotFoundError:return {}
    def write_values(name,values):
        with reg.CreateKeyEx(reg.HKEY_LOCAL_MACHINE,REG_BASE+'\\'+name,0,access) as key:
            for value_name in VALUE_NAMES:
                if value_name in values:
                    value,kind=values[value_name];reg.SetValueEx(key,value_name,0,kind,value)
                else:
                    try:reg.DeleteValue(key,value_name)
                    except FileNotFoundError:pass
    if action=='enable':
        names=['ImageDrawBot.exe'] + (['python.exe','pythonw.exe'] if include_python else [])
        existing = {name: read_values(name) for name in names}
        for name in names:
            if name in state and existing[name] != state[name]['written']:
                raise RuntimeError(f'{name}: settings changed since last setup. Disable/inspect the saved configuration first.')
        written={'DumpFolder':[str(folder),reg.REG_EXPAND_SZ],
                 'DumpCount':[5,reg.REG_DWORD],'DumpType':[1,reg.REG_DWORD]}
        planned = dict(state)
        for name in names:
            if name not in planned:
                planned[name] = {'original': existing[name], 'written': written}
        _validate_backup(planned, reg)
        for name in names:
            if name in state:
                continue
            state[name] = planned[name]
            # Persist undo information BEFORE touching the registry.
            atomic_write_text(backup,json.dumps(state,indent=2))
            write_values(name,written)
        return f'LocalDumps configured: {", ".join(names)}\nDump folder: {folder}\nMini dumps remain local; share them only when needed.'
    if action=='disable':
        for name, saved in list(state.items()):
            current=read_values(name)
            restored=restore_values(current,saved['written'],saved['original'])
            write_values(name,restored)
            # Keep the key itself: other tools may store additional values there.
            del state[name]
            atomic_write_text(backup,json.dumps(state,indent=2))
        return 'Image Draw Bot dump settings restored. Existing dump files were kept.'
    raise ValueError('Choose enable or disable.')


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('enable','disable'))
    parser.add_argument('--include-python',action='store_true')
    args=parser.parse_args(argv)
    if args.include_python:
        print('Source mode: this also configures crash dumps for other processes named python.exe/pythonw.exe.')
    try:
        message=configure(args.action,args.include_python);code=0
    except Exception as error:
        message=f'Dump configuration failed: {error}';code=1
    print(message)
    if getattr(sys,'frozen',False):
        from tkinter import messagebox
        (messagebox.showerror if code else messagebox.showinfo)('Crash dump setup',message)
    return code

if __name__=='__main__':raise SystemExit(main())
