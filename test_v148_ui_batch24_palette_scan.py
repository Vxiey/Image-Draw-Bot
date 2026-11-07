"""Actual palette scan work, GUI handoff, cancellation and image ownership."""
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from CalibrationAnchors import make_anchor
import GetColorPositions as capture
import PaletteMaps as maps
from PaletteScanWorker import PaletteScanJob
from test_v148_ui_batch06_calibration import Var, palette_app, finish_palette_scan


def swatches(mode='RGB'):
    image=Image.new('RGB',(80,40),(210,210,210))
    draw=ImageDraw.Draw(image)
    draw.rectangle((4,4,35,35),fill=(255,0,0))
    draw.rectangle((44,4,75,35),fill=(0,0,255))
    if mode=='RGB':return image
    try:return image.convert(mode)
    finally:image.close()


def closed(image):
    try:image.getpixel((0,0))
    except ValueError:return True
    return False


class MainThreadVar(Var):
    def __init__(self,value,owner):
        super().__init__(value);self.owner=owner
    def get(self):
        if threading.get_ident()!=self.owner:raise AssertionError('Tk input read by worker')
        return super().get()
    def set(self,value):
        if threading.get_ident()!=self.owner:raise AssertionError('Tk output written by worker')
        return super().set(value)


class PaletteScanFlowTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.images=[];self.apps=[];self.jobs=[];self.releases=[]
        self.addCleanup(self.release)

    def release(self):
        for gate in self.releases:gate.set()
        for app in self.apps:app._retire_scan()
        for job in self.jobs:
            job.retire()
            if job.thread is not None:job.thread.join(timeout=5)
        for image in self.images:image.close()

    def app(self):
        app=palette_app();app.on_close=None
        self.images.append(app.snapshot[1]);self.apps.append(app)
        owner=threading.get_ident()
        for name in ('status','detect_mode','rows','columns'):
            setattr(app,name,MainThreadVar(getattr(app,name).get(),owner))
        self.stack.enter_context(patch.object(capture.ImageTk,'PhotoImage',side_effect=lambda image,**kw:
            self.make_photo(image,kw,owner)))
        return app

    def make_photo(self,image,kwargs,owner):
        self.assertEqual(threading.get_ident(),owner)
        self.assertIsNotNone(kwargs.get('master'))
        image.getpixel((0,0))
        return object()

    def source(self,mode='RGB'):
        image=swatches(mode);self.images.append(image);return image

    def request(self,app,image):
        self.assertTrue(app.read_snapshot(((100,200,180,240),image),
            anchor=make_anchor((100,200,600,400)),anchor_handle=99))
        job=app._scan_job;self.jobs.append(job);return job

    def blocking(self):
        entered=threading.Event();release=threading.Event();self.releases.append(release)
        sources=[];threads=[];original=capture.detect_color_swatches
        def analyze(image,*args,**kwargs):
            sources.append(image);threads.append(threading.get_ident());entered.set()
            if not release.wait(5):raise AssertionError('Analysis test gate timed out.')
            return original(image,*args,**kwargs)
        self.stack.enter_context(patch.object(capture,'detect_color_swatches',side_effect=analyze))
        return entered,release,sources,threads

    def test_actual_new_crop_returns_before_analysis_and_adopts_only_on_gui_poll(self):
        app=self.app();previous=app.snapshot;old_state=(app.pending,app.rgbs,app.anchor,app.photo)
        source=self.source();entered,release,sources,threads=self.blocking()
        with patch('TargetCapture.capture_target_metadata_isolated',return_value={'handle':99,'client_rect':(100,200,600,400)}),\
             patch('RegionPicker.select_region',side_effect=lambda root,selected,error:selected((100,200,180,240),source)):
            app.start_scan()
        job=app._scan_job;self.assertIsNotNone(job);self.jobs.append(job)
        self.assertTrue(entered.wait(3));self.assertNotEqual(threads,[threading.get_ident()])
        self.assertEqual(sources,[source]);self.assertFalse(closed(source))
        self.assertIs(app.snapshot,previous)
        self.assertEqual((app.pending,app.rgbs,app.anchor,app.photo),old_state)
        # Repeated requests never close the currently owned worker source.
        self.assertFalse(app.read_snapshot(((100,200,180,240),source),anchor=make_anchor((100,200,600,400))))
        self.assertFalse(closed(source))
        extra=self.source();self.assertFalse(app.read_snapshot(((0,0,80,40),extra),anchor={}))
        self.assertTrue(closed(extra))
        with patch.object(capture,'save_calibration') as save,patch('RegionPicker.select_region') as select:
            app.save();app.undo();app.capture(0);app.capture_code(0);app.start_scan()
            save.assert_not_called();select.assert_not_called()
        release.set();job.thread.join(timeout=5)
        self.assertFalse(job.thread.is_alive());self.assertIs(app.snapshot,previous)
        finish_palette_scan(app)
        self.assertEqual(app.pending,[(119,219),(159,219)])
        self.assertEqual(app.rgbs,[(255,0,0),(0,0,255)])
        self.assertIs(app.snapshot[1],source);self.assertTrue(closed(previous[1]))
        self.assertEqual(app.anchor_handle,99);self.assertIsNone(app.map_names)
        self.assertIn('Review the detected colors',app.status.get())

    def test_close_during_rescan_releases_old_image_but_not_reading_worker_copy(self):
        app=self.app();old=app.snapshot[1];before=old.tobytes()
        entered,release,sources,_threads=self.blocking()
        self.assertTrue(app.read_snapshot());job=app._scan_job;self.jobs.append(job)
        self.assertTrue(entered.wait(3));private=sources[0]
        self.assertIsNot(private,old);self.assertEqual(private.tobytes(),before)
        app.close();app.close()
        self.assertTrue(closed(old));self.assertFalse(closed(private))
        app.root.destroy.assert_called_once_with()
        release.set();job.thread.join(timeout=5)
        self.assertFalse(job.thread.is_alive());self.assertTrue(closed(private))
        self.assertTrue(job.done);self.assertIsNone(job.take());self.assertIsNone(app.snapshot)
        app.preview.configure.assert_not_called()

    def test_completed_unadopted_result_and_stale_settings_are_disposed(self):
        for close_first in (True,False):
            with self.subTest(close_first=close_first):
                app=self.app();old=app.snapshot;source=self.source();previews=[]
                original=capture._analyze_palette_snapshot
                def observed(*args,**kwargs):
                    data,preview=original(*args,**kwargs);previews.append(preview);return data,preview
                with patch.object(capture,'_analyze_palette_snapshot',side_effect=observed):
                    job=self.request(app,source);job.thread.join(timeout=5)
                self.assertTrue(job.done);self.assertFalse(closed(source))
                self.assertFalse(closed(previews[0]));self.assertIs(app.snapshot,old)
                if close_first:
                    app.close();app._poll_scan(job)
                    self.assertIsNone(app.snapshot)
                else:
                    app.detect_mode.set('Grid');app.rows.set(1);app.columns.set(2)
                    finish_palette_scan(app)
                    self.assertIs(app.snapshot,old);self.assertFalse(closed(old[1]))
                    self.assertIn('settings or image changed',app.status.get())
                self.assertTrue(closed(source));self.assertTrue(closed(previews[0]))
                app.preview.configure.assert_not_called()
                self.assertIsNone(job.take())

    def test_start_and_poll_installation_failure_keep_draft_and_retire_transferred_crop(self):
        for phase in ('construct','start','after'):
            with self.subTest(phase=phase),ExitStack() as scope:
                app=self.app();old=app.snapshot;source=self.source()
                if phase=='construct':scope.enter_context(patch('PaletteScanWorker.PaletteScanJob',side_effect=MemoryError('mailbox allocation')))
                elif phase=='start':scope.enter_context(patch('PaletteScanWorker.threading.Thread.start',side_effect=RuntimeError('thread unavailable')))
                else:
                    entered,release,sources,_threads=self.blocking()
                    app.root.after.side_effect=RuntimeError('poll unavailable')
                self.assertFalse(app.read_snapshot(((0,0,80,40),source),anchor=make_anchor((0,0,600,400))))
                self.assertIs(app.snapshot,old);self.assertFalse(closed(old[1]))
                self.assertIsNone(app._scan_job)
                if phase=='after':
                    release.set()
                    # The worker's image remains privately owned until it exits;
                    # a failed GUI timer must not close that image underneath it.
                    deadline=time.monotonic()+3
                    while not closed(source) and time.monotonic()<deadline:time.sleep(.005)
                self.assertTrue(closed(source))
                self.assertIn('Could not scan',app.status.get())
                app.preview.configure.assert_not_called()

    def test_retained_scanner_error_closes_private_copy_and_keeps_old_draft(self):
        app=self.app();old=app.snapshot;seen=[];failure=MemoryError('analysis allocation')
        def fail(image,*args,**kwargs):seen.append(image);raise failure
        with patch.object(capture,'detect_color_swatches',side_effect=fail):
            self.assertTrue(app.read_snapshot());job=app._scan_job;self.jobs.append(job)
            finish_palette_scan(app)
        self.assertIs(app.snapshot,old);self.assertFalse(closed(old[1]))
        self.assertTrue(closed(seen[0]));self.assertIsNotNone(failure.__traceback__)
        self.assertIn('MemoryError: analysis allocation',app.status.get())
        self.assertIsNone(job._operation);self.assertIsNone(job._settings)
        self.assertIsNone(job.take());app.preview.configure.assert_not_called()

    def test_later_poll_failure_restores_reviewed_draft_and_allows_retry(self):
        app=self.app();old=app.snapshot;source=self.source()
        entered,release,sources,_threads=self.blocking()
        job=self.request(app,source);self.assertTrue(entered.wait(3))
        token=app._scan_after;app.root.after_cancel(token)
        app.refresh.reset_mock()
        app.root.after.side_effect=tk.TclError('later poll unavailable')
        app._poll_scan(job)
        self.assertIsNone(app._scan_job);self.assertIsNone(app._scan_after)
        self.assertIn('Could not scan',app.status.get())
        app.refresh.assert_called_once_with()
        self.assertIs(app.snapshot,old);self.assertFalse(closed(old[1]))
        self.assertFalse(closed(source));app.preview.configure.assert_not_called()
        release.set();job.thread.join(timeout=5)
        self.assertFalse(job.thread.is_alive());self.assertTrue(closed(source))
        app.root.after.side_effect=None
        replacement=self.source();self.request(app,replacement);finish_palette_scan(app)
        self.assertIs(app.snapshot[1],replacement)
        self.assertEqual(app.rgbs,[(255,0,0),(0,0,255)])

    def test_retained_grid_preview_error_releases_native_draw_aliases(self):
        app=self.app();old=app.snapshot;source=self.source()
        app.detect_mode.set('Grid');app.rows.set(1);app.columns.set(2)
        pens=[];images=[];failure=MemoryError('grid preview line allocation')
        original=ImageDraw.ImageDraw.line
        def fail(pen,*args,**kwargs):
            pens.append(pen);images.append(pen._image)
            original(pen,*args,**kwargs)
            raise failure
        with patch.object(ImageDraw.ImageDraw,'line',fail):
            self.request(app,source);finish_palette_scan(app)
        self.assertIsNotNone(failure.__traceback__);self.assertTrue(pens)
        for pen in pens:
            self.assertIsNone(pen.draw);self.assertIsNone(pen.im);self.assertIsNone(pen._image)
        self.assertTrue(all(closed(image) for image in images))
        self.assertTrue(closed(source));self.assertFalse(closed(old[1]))
        self.assertIs(app.snapshot,old);app.preview.configure.assert_not_called()
        self.assertIn('MemoryError: grid preview line allocation',app.status.get())

    def test_real_modes_preserve_colors_positions_preview_and_caller_owned_sources(self):
        preset=maps.Palette('fixture','fixture',('red','blue'),((255,0,0),(0,0,255)))
        changed=maps.Palette('fixture','fixture',('green','yellow'),((0,255,0),(255,255,0)))
        cases=(('auto','RGB',None,False),('auto','RGBA',None,False),
               ('preset','RGB',preset,False),('fallback','RGB',changed,False),
               ('paint-grid','RGB',None,True),('grid','RGB',None,False))
        for name,mode,reference,is_paint in cases:
            with self.subTest(mode=name,source_mode=mode):
                app=self.app();app.preset=reference;app.is_paint=is_paint
                source=self.source(mode);before=source.tobytes()
                if 'grid' in name:app.detect_mode.set('Grid');app.rows.set(1);app.columns.set(2)
                job=self.request(app,source);finish_palette_scan(app)
                expected=[(120,220),(160,220)] if 'grid' in name else [(119,219),(159,219)]
                self.assertEqual(app.pending,expected)
                self.assertEqual(app.rgbs,[(255,0,0),(0,0,255)])
                self.assertEqual(app.map_names,['red','blue'] if name=='preset' else None)
                self.assertEqual(app.map_indices,[0,1] if name=='preset' else None)
                self.assertEqual(source.tobytes(),before);self.assertIs(app.snapshot[1],source)
                self.assertIsNone(app._scan_job);self.assertTrue(job.done)


class PaletteScanCancellationTests(unittest.TestCase):
    def test_scanners_check_stop_and_release_only_owned_rgb_conversion(self):
        with swatches('RGBA') as image:
            before=image.tobytes();preset=maps.Palette('fixture','fixture',('red','blue'),((255,0,0),(0,0,255)))
            operations=(lambda stop:maps.detect_preset(image,preset,cancelled=stop),
                        lambda stop:maps.sample_grid(image,1,2,cancelled=stop),
                        lambda stop:maps.sample_paint_grid(image,1,2,cancelled=stop),
                        lambda stop:maps.detect_color_swatches(image,cancelled=stop))
            for operation in operations:
                with self.subTest(operation=operation),patch.object(Image.Image,'convert',side_effect=AssertionError('cancel before conversion')):
                    with self.assertRaises(InterruptedError):operation(lambda:True)
                copies=[];original=Image.Image.convert
                def convert(source,*args,**kwargs):
                    out=original(source,*args,**kwargs)
                    if source is image:copies.append(out)
                    return out
                calls=0
                def later():
                    nonlocal calls
                    calls+=1;return calls>=2
                with patch.object(Image.Image,'convert',convert),self.assertRaises(InterruptedError):operation(later)
                self.assertTrue(copies);self.assertTrue(all(closed(item) for item in copies))
                self.assertEqual(image.tobytes(),before)
            with Image.new('RGB',(180,180),'white') as large:
                calls=0
                def inner():
                    nonlocal calls
                    calls+=1;return calls>=3
                with self.assertRaises(InterruptedError):
                    maps.detect_preset(large,maps.Palette('x','x',('white',),((255,255,255),)),cancelled=inner)
                self.assertEqual(calls,3)
                self.assertFalse(closed(large))

    def test_publish_retire_race_disposes_every_pure_image_without_gui_callback(self):
        for moment in ('before-start','before-publish','after-publish'):
            with self.subTest(moment=moment):
                source=swatches();preview=[];staged=threading.Event();release=threading.Event()
                settings=dict(box=(0,0,80,40),mode='Auto detect',preset=None,rows=None,columns=None,is_paint=False,max_colors=64)
                def analyze(*args):
                    values,image=capture._analyze_palette_snapshot(*args);preview.append(image);return values,image
                job=PaletteScanJob(source,analyze,settings)
                publish=job._publish
                def held(outcome):
                    staged.set()
                    if not release.wait(3):raise AssertionError('Publish test gate timed out.')
                    publish(outcome)
                if moment=='before-start':job.retire();job.start()
                elif moment=='before-publish':
                    job._publish=held;job.start();self.assertTrue(staged.wait(3));job.retire();release.set()
                else:
                    job.start();job.thread.join(timeout=3);self.assertTrue(job.done);job.retire()
                job.thread.join(timeout=3);self.assertFalse(job.thread.is_alive());job.retire()
                self.assertTrue(closed(source));self.assertTrue(all(closed(item) for item in preview))
                self.assertIsNone(job.take());self.assertTrue(job.done)


@unittest.skipUnless(sys.platform=='win32' or bool(os.environ.get('DISPLAY')),'Native Tk display required')
class NativePaletteScanTests(unittest.TestCase):
    def isolated(self):
        if os.environ.get('IDB_PALETTE_SCAN_CASE')==self._testMethodName:return False
        env=dict(os.environ,IDB_PALETTE_SCAN_CASE=self._testMethodName)
        result=subprocess.run([sys.executable,'-X','faulthandler','-m','unittest','-v',
            f'{__name__}.{type(self).__name__}.{self._testMethodName}'],cwd=Path(__file__).resolve().parent,
            env=env,text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for text in ('invalid command name','Tcl_AsyncDelete','Exception ignored in'):
            self.assertNotIn(text,result.stderr)
        return True

    def surface(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=tk.Tk()
        def dispose_root():
            try:root.destroy()
            except tk.TclError:pass
        self.addCleanup(dispose_root)
        with patch('WindowsMouse.WindowsMouse',return_value=object()):
            app=capture.CalibrationApp(root,path=Path(directory.name)/'palette.json',profile='generic')
        self.addCleanup(app.close)
        return root,app

    def test_native_heartbeat_and_preview_adoption_stay_on_gui_thread(self):
        if self.isolated():return
        root,app=self.surface();main=threading.get_ident();events=[];threads=[];gate=threading.Event()
        source=swatches();self.addCleanup(source.close);original=capture.detect_color_swatches
        def analyze(*args,**kwargs):
            threads.append(threading.get_ident());events.append('analysis')
            if not gate.wait(3):raise AssertionError('Tk did not remain responsive.')
            return original(*args,**kwargs)
        def heartbeat():events.append('heartbeat');gate.set()
        root.after(0,heartbeat)
        with patch.object(capture,'detect_color_swatches',side_effect=analyze):
            self.assertTrue(app.read_snapshot(((0,0,80,40),source),anchor=make_anchor((0,0,600,400)),anchor_handle=42))
            job=app._scan_job
            self.assertEqual(str(app.auto.cget('state')),'disabled')
            self.assertEqual(str(app.close_button.cget('state')),'normal')
            deadline=time.monotonic()+5
            while app._scan_job is not None and time.monotonic()<deadline:
                root.update();time.sleep(.005)
        self.assertIsNone(app._scan_job);self.assertTrue(job.done)
        self.assertEqual(len(threads),1);self.assertNotEqual(threads[0],main)
        self.assertIn('heartbeat',events);self.assertIs(app.snapshot[1],source)
        self.assertEqual(app.pending,[(19,19),(59,19)])
        self.assertEqual(app.rgbs,[(255,0,0),(0,0,255)])
        self.assertEqual(str(app.auto.cget('state')),'normal')
        self.assertTrue(app.photo.width()>0);self.assertIs(app.photo.tk,root.tk)
        app.close()

    def test_native_cancel_closes_dialog_while_analysis_owns_only_private_pixels(self):
        if self.isolated():return
        root,app=self.surface();source=swatches();self.addCleanup(source.close)
        entered=threading.Event();release=threading.Event();private=[];original=capture.detect_color_swatches
        self.addCleanup(release.set)
        def analyze(image,*args,**kwargs):
            private.append(image);entered.set()
            if not release.wait(3):raise AssertionError('Native cancellation test gate timed out.')
            return original(image,*args,**kwargs)
        with patch.object(capture,'detect_color_swatches',side_effect=analyze):
            self.assertTrue(app.read_snapshot(((0,0,80,40),source),anchor=make_anchor((0,0,600,400)),anchor_handle=42))
            job=app._scan_job;self.assertTrue(entered.wait(3))
            app.close_button.invoke()
            self.assertTrue(app.closed);self.assertIsNone(app._scan_job)
            self.assertFalse(closed(source))
            release.set();job.thread.join(timeout=5)
            self.assertFalse(job.thread.is_alive());self.assertTrue(closed(source))
            self.assertIsNone(job.take());self.assertIsNone(app.snapshot)
            self.assertEqual(private,[source])


if __name__=='__main__':unittest.main()
