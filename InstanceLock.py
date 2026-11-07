"""One app per Windows user session. OS releases the mutex after a crash."""
import ctypes
from ctypes import wintypes
from WindowsSystem import load_system_library


class InstanceLock:
    def __init__(self):
        self.api=load_system_library('kernel32',use_last_error=True)
        self.api.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        self.api.CreateMutexW.restype=wintypes.HANDLE
        self.api.CloseHandle.argtypes=[wintypes.HANDLE]
        self.handle=self.api.CreateMutexW(None,False,'Local\\ImageDrawBot.SingleInstance')
        if not self.handle:raise OSError('Could not create the instance lock.')
        self.already_running=ctypes.get_last_error()==183

    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None
