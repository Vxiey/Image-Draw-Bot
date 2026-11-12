"""Concurrent DPI observations retain their own real ctypes pointer signature."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import sys
import threading
import unittest

import DpiSupport
from ScreenGuard import WindowMonitor


class ScalarFunction:
    def __init__(self,value):self.value=value
    def __call__(self,*_):return self.value


class NativeFunction:
    def __init__(self,owner,function):self.owner,self.function=owner,function
    @property
    def argtypes(self):return self.function.argtypes
    @argtypes.setter
    def argtypes(self,value):self.function.argtypes=value
    @property
    def restype(self):return self.function.restype
    @restype.setter
    def restype(self,value):
        self.function.restype=value
        if self.owner.block_ident==threading.get_ident() and self.owner.block_once:
            self.owner.block_once=False;self.owner.configured.set()
            if not self.owner.resume.wait(5):raise AssertionError('DPI interleave did not finish')
    def __call__(self,handle,pointer):
        # Real ctypes performs pointer validation. Only the OS data producer is
        # replaced, so incompatible concurrently rebound pointer types fail.
        try:result=self.function(handle,pointer)
        except BaseException as error:
            self.owner.errors.append(error);raise
        if result:
            info=pointer._obj
            for field,rect in (('rcMonitor',(-1920,-200,1920,1080)),('rcWork',(-1920,-200,1920,1040))):
                target=getattr(info,field)
                for name,value in zip(('left','top','right','bottom'),rect):setattr(target,name,value)
        return result


class DpiLibrary:
    def __init__(self):
        self.errors=[];self.lookups=0;self.configured=threading.Event();self.resume=threading.Event()
        self.block_ident=None;self.block_once=False
        self.prototype=ctypes.CFUNCTYPE(ctypes.c_int32,ctypes.c_void_p,ctypes.c_void_p)
        self.callback=self.prototype(lambda *_:1)
        self.address=ctypes.cast(self.callback,ctypes.c_void_p).value
        self.GetMonitorInfoW=self.bind();self.initial_types=tuple(self.GetMonitorInfoW.argtypes)
        self.MonitorFromWindow=ScalarFunction(2**40+7);self.GetDpiForWindow=ScalarFunction(144)
    def bind(self):return NativeFunction(self,self.prototype(self.address))
    def __getitem__(self,name):
        if name!='GetMonitorInfoW':raise AssertionError(name)
        self.lookups+=1;return self.bind()


class DpiObservationTests(unittest.TestCase):
    def test_overlapping_window_monitor_reads_keep_complete_native_geometry(self):
        provider=DpiLibrary();monitor=object.__new__(WindowMonitor);monitor.api=provider
        monitor._validate_handle=lambda _:None
        def first():
            provider.block_ident=threading.get_ident();provider.block_once=True
            return monitor.dpi_info(2**40+1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending=pool.submit(first)
            try:
                self.assertTrue(provider.configured.wait(5))
                second=pool.submit(monitor.dpi_info,2**40+2).result(timeout=5)
            finally:provider.resume.set()
            initial=pending.result(timeout=5)
        for result in (initial,second):
            self.assertEqual((result.dpi,result.scale),(144,1.5))
            self.assertEqual(result.monitor_rect,(-1920,-200,1920,1080))
            self.assertEqual(result.work_rect,(-1920,-200,1920,1040))
        self.assertFalse(provider.errors)
        self.assertEqual(provider.lookups,2)
        self.assertEqual(tuple(provider.GetMonitorInfoW.argtypes),provider.initial_types)

    def test_monitor_struct_uses_fixed_windows_layout_and_unavailable_provider_falls_back(self):
        self.assertEqual(ctypes.sizeof(DpiSupport._MonitorInfo),40)
        provider=DpiLibrary()
        self.assertEqual(DpiSupport.get_window_dpi_info(1,user32=provider).dpi,144)
        unavailable=type('Unavailable',(),{})()
        self.assertEqual(DpiSupport._monitor_info(unavailable,1),(None,None))
        self.assertEqual(DpiSupport._monitor_info(unavailable,None),(None,None))

    @unittest.skipUnless(sys.platform=='win32','Requires the real Windows monitor API')
    def test_live_windows_parallel_observations_keep_valid_monitor_rectangles(self):
        from WindowsSystem import load_system_library
        user32=load_system_library('user32',use_last_error=True)
        desktop=user32['GetDesktopWindow'];desktop.argtypes=[];desktop.restype=ctypes.c_void_p
        handle=desktop()
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda _:DpiSupport.get_window_dpi_info(handle,user32=user32),range(8)))
        for value in values:
            self.assertGreaterEqual(value.dpi,48);self.assertLessEqual(value.dpi,768)
            left,top,right,bottom=value.monitor_rect
            self.assertLess(left,right);self.assertLess(top,bottom)


if __name__=='__main__':unittest.main()
