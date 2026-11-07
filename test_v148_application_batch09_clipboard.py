"""Bitmap normalization stays off Tk, with explicit result ownership and Stop."""
from contextlib import ExitStack, closing
import queue
import threading
from types import MethodType
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import ClipboardImport
from DrawBot import DrawBotApp
from test_v148_ui_lifecycle_batch02 import ui_app


class ClipboardWorkerTests(unittest.TestCase):
    def app(self, *, native_worker=False):
        app=ui_app()
        self.addCleanup(app.original.close)
        app.events=queue.Queue();app.plan={'previous':'plan'}
        app.set_busy=lambda activity:setattr(app,'activity',activity)
        if native_worker:
            app.begin_worker=MethodType(DrawBotApp.begin_worker,app)
        else:
            app.begin_worker=Mock(return_value=True)
        return app

    def guards(self, stack):
        stack.enter_context(patch('DrawBot.log_event'))
        for name in ('_clear_render_resume','_queue_drop_in_start',
                     '_queue_browser_one_click_after_import','_manual_drop_in_armed'):
            stack.enter_context(patch.object(DrawBotApp,name,return_value=False))

    def assert_closed(self,image):
        with self.assertRaises(ValueError):image.getpixel((0,0))

    def test_actual_loader_thread_normalizes_then_main_thread_adopts_owned_pixels(self):
        app=self.app(native_worker=True);old=app.original
        main_thread=threading.get_ident();normalizer_threads=[];ui_threads=[]
        app.status.set.side_effect=lambda _value:ui_threads.append(threading.get_ident())
        with ExitStack() as stack:
            self.guards(stack)
            source=stack.enter_context(closing(Image.new('RGB',(3,2))))
            source.putdata([(10,20,30),(40,50,60),(70,80,90),(100,110,120),(130,140,150),(160,170,180)])
            source.getexif()[274]=6
            source.info['draw_studio_format']='untrusted clipboard hint'
            before=source.tobytes();information=dict(source.info)
            expected=stack.enter_context(closing(source.transpose(Image.Transpose.ROTATE_270).convert('RGBA')))
            real=ClipboardImport.prepare_bitmap
            def prepare(*args,**kwargs):
                normalizer_threads.append(threading.get_ident())
                return real(*args,**kwargs)
            stack.enter_context(patch.object(ClipboardImport,'prepare_bitmap',side_effect=prepare))
            stack.enter_context(patch('PIL.ImageGrab.grabclipboard',return_value=source))
            self.assertTrue(DrawBotApp.paste_image(app))
            worker=app.worker;worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(app.activity,'load')
            self.assertIs(app.original,old)
            self.assertEqual(len(normalizer_threads),1)
            self.assertNotEqual(normalizer_threads[0],main_thread)
            self.assertTrue(all(thread==main_thread for thread in ui_threads))
            kind,payload=app.events.get_nowait()
            self.assertEqual(kind,'pasted')
            self.assertEqual(app.events.get_nowait(),('done','load'))
            self.assertTrue(app.events.empty())
            prepared=payload[0];self.addCleanup(prepared.close)
            self.assertEqual(prepared.size,(2,3))
            self.assertEqual(prepared.tobytes(),expected.tobytes())
            self.assertNotIn(274,prepared.getexif())
            self.assertNotIn('draw_studio_format',prepared.info)
            DrawBotApp._handle_event(app,kind,payload)
            self.assertIs(app.original,prepared)
            self.assertIsNone(app.plan)
            self.assertTrue(app.needs_plan)
            self.assertEqual(source.tobytes(),before)
            self.assertEqual(source.info,information)

    def test_live_profile_guards_and_refused_worker_preserve_original_without_normalizing(self):
        for field,value in (('activity','draw'),('closing',True),('pending_clear_drawing',object()),
                            ('profile_change_after','ticket'),('profile_change_in_progress',True)):
            app=self.app();setattr(app,field,value)
            with self.subTest(field=field),patch('PIL.ImageGrab.grabclipboard') as grab:
                DrawBotApp.paste_image(app)
            grab.assert_not_called();app.begin_worker.assert_not_called()
        app=self.app();old=app.original;app.begin_worker.return_value=False
        with closing(Image.new('RGBA',(4,3),'blue')) as source,ExitStack() as stack:
            self.guards(stack)
            stack.enter_context(patch('PIL.ImageGrab.grabclipboard',return_value=source))
            prepare=stack.enter_context(patch.object(ClipboardImport,'prepare_bitmap'))
            self.assertFalse(DrawBotApp.paste_image(app))
            prepare.assert_not_called();self.assertIs(app.original,old)
            self.assertEqual(source.getpixel((0,0)),(0,0,255,255))
            self.assertTrue(app.events.empty())

    def test_stop_before_normalization_never_allocates_or_publishes_a_result(self):
        app=self.app()
        with closing(Image.new('RGB',(4,3),'blue')) as source,patch.object(
                ClipboardImport.ImageOps,'exif_transpose') as orient:
            self.assertTrue(DrawBotApp._queue_clipboard_bitmap(app,source,None))
            app.stop.set()
            with self.assertRaises(InterruptedError):app.begin_worker.call_args.args[1]()
            orient.assert_not_called();self.assertTrue(app.events.empty())
            self.assertEqual(source.getpixel((0,0)),(0,0,255))

    def test_preparation_failure_and_stop_after_orientation_close_only_owned_images(self):
        for failure in ('stop','profile'):
            with self.subTest(failure=failure),closing(Image.new('RGBA',(3,2),(1,2,3,4))) as source:
                source.info['icc_profile']=b'invalid profile'
                owned=[];stopped=threading.Event()
                def orient(image):
                    result=image.copy();owned.append(result)
                    if failure=='stop':stopped.set()
                    return result
                with patch.object(ClipboardImport.ImageOps,'exif_transpose',side_effect=orient):
                    with self.assertRaises(InterruptedError if failure=='stop' else ValueError):
                        ClipboardImport.prepare_bitmap(source,stopped.is_set)
                self.assertEqual(len(owned),1);self.assert_closed(owned[0])
                self.assertEqual(source.getpixel((0,0)),(1,2,3,4))
                self.assertEqual(source.info['icc_profile'],b'invalid profile')

    def test_stop_after_preparation_and_queue_failure_close_unpublished_result(self):
        for failure in ('stop','queue'):
            app=self.app();old=app.original
            with self.subTest(failure=failure),closing(Image.new('RGBA',(3,2),'blue')) as source:
                prepared=source.copy()
                def prepare(*args,**kwargs):
                    if failure=='stop':app.stop.set()
                    return prepared
                if failure=='queue':app.events.put=Mock(side_effect=RuntimeError('controlled queue failure'))
                with patch.object(ClipboardImport,'prepare_bitmap',side_effect=prepare):
                    DrawBotApp._queue_clipboard_bitmap(app,source,None)
                    with self.assertRaises(InterruptedError if failure=='stop' else RuntimeError):
                        app.begin_worker.call_args.args[1]()
                self.assert_closed(prepared);self.assertIs(app.original,old)
                self.assertEqual(source.getpixel((0,0)),(0,0,255,255))

    def test_queued_stop_or_clear_result_is_discarded_without_editing_previous_ui(self):
        for failure in ('stop','clear'):
            app=self.app();old=app.original;previous_plan=app.plan
            with self.subTest(failure=failure),closing(Image.new('RGBA',(3,2),'blue')) as source:
                DrawBotApp._queue_clipboard_bitmap(app,source,None)
                app.begin_worker.call_args.args[1]()
                kind,payload=app.events.get_nowait();prepared=payload[0]
                if failure=='stop':app.stop.set()
                else:app.pending_clear_drawing=object()
                with patch('DrawBot.log_event'):
                    DrawBotApp._handle_event(app,kind,payload)
                self.assert_closed(prepared);self.assertIs(app.original,old)
                self.assertIs(app.plan,previous_plan)
                app._mark_plan_stale.assert_not_called();app.show_previews.assert_not_called()
                self.assertEqual(source.getpixel((0,0)),(0,0,255,255))


if __name__=='__main__':unittest.main()
