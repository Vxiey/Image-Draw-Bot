"""Canvas drops use the positioned overlay and its still-live bounded consent."""
from contextlib import ExitStack
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DrawBot import DrawBotApp


class Overlay:
    def __init__(self,root):self.actions=[];self.callbacks={};self.destroyed=False
    def withdraw(self):self.actions.append('withdraw')
    def title(self,*args):pass
    def overrideredirect(self,*args):pass
    def attributes(self,*args):pass
    def focus_force(self):pass
    def bind(self,*args):pass
    def drop_target_register(self,*args):self.actions.append('register')
    def dnd_bind(self,name,callback):self.callbacks[name]=callback
    def destroy(self):self.destroyed=True


class DndWrapper:pass


class CanvasOverlayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(sys.modules,{'tkinterdnd2':SimpleNamespace(
            DND_FILES='files',DND_TEXT='text',TkinterDnD=SimpleNamespace(DnDWrapper=DndWrapper))}))
        self.stack.enter_context(patch('DrawBot.tk.Toplevel',Overlay))
        self.stack.enter_context(patch('DrawBot.tk.Canvas',return_value=Mock()))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.now=[10.]
        self.stack.enter_context(patch('DrawBot.time.monotonic',side_effect=lambda:self.now[0]))
        def place(window,box):window.actions.append('place');return tuple(box)
        self.place=self.stack.enter_context(patch('SmartDropInCanvas.place_canvas_overlay',side_effect=place))
        root=Mock();root.tk.splitlist.return_value=();root.after.return_value='expiry'
        self.app=SimpleNamespace(root=root,closing=False,activity=None,stop=threading.Event(),
            smart_drop_overlay=None,smart_drop_timeout_after=None,status=Mock(),smart_drop_in_text=Mock(),
            _expire_smart_drop_overlay=Mock(),_invalidate_target_lock=Mock(),color_session_cache={},
            area_text=Mock(),load_source=Mock(return_value=True),corners=[])
        self.box=(-1200,-500,-600,-100)
        payload={'canvas_box':self.box,'canvas_confidence':.9,'target_meta':{
            'handle':10,'rect':(-1300,-550,-500,-50),'client_rect':(-1300,-550,-500,-50),'dpi':96}}
        self.assertTrue(DrawBotApp._show_smart_drop_overlay(self.app,payload))
        self.overlay=self.app.smart_drop_overlay

    def event(self,x=-1100,y=-400):
        return SimpleNamespace(x_root=x,y_root=y,data='https://example.com/picture.png')

    def test_verified_absolute_placement_precedes_drop_registration(self):
        self.place.assert_called_once_with(self.overlay,self.box)
        self.assertEqual(self.overlay.actions,['withdraw','place','register'])

    def test_edge_or_outside_drop_never_imports_or_changes_target(self):
        for x,y in ((-1200,-400),(-1197,-400),(-601,-200),(-1000,-101),(-1300,-400)):
            event=self.event(x,y)
            self.assertEqual(self.overlay.callbacks['<<DropPosition>>'](event),'none')
            self.assertEqual(self.overlay.callbacks['<<Drop>>'](event),'none')
        self.app.load_source.assert_not_called();self.app._invalidate_target_lock.assert_not_called()
        self.assertEqual(self.app.corners,[])

    def test_valid_interior_drop_consumes_the_overlay_once(self):
        event=self.event()
        self.assertEqual(self.overlay.callbacks['<<DropPosition>>'](event),'copy')
        drop=self.overlay.callbacks['<<Drop>>']
        self.assertEqual(drop(event),'copy');self.assertTrue(self.overlay.destroyed)
        self.assertEqual(drop(event),'none')
        self.app.load_source.assert_called_once_with('https://example.com/picture.png','Dropped web image',
                                                    action=None,one_click_force=True)
        self.assertEqual(self.app.corners,[(-1200,-500),(-600,-100)])

    def test_expired_cancelled_busy_and_replaced_overlay_callbacks_cannot_start_import(self):
        drop=self.overlay.callbacks['<<Drop>>'];event=self.event()
        self.now[0]=70.;self.assertEqual(drop(event),'none');self.now[0]=10.
        self.app.stop.set();self.assertEqual(drop(event),'none');self.app.stop.clear()
        self.app.activity='draw';self.assertEqual(drop(event),'none');self.app.activity=None
        self.app.closing=True;self.assertEqual(drop(event),'none');self.app.closing=False
        self.app.smart_drop_overlay=object();self.assertEqual(drop(event),'none')
        self.app.load_source.assert_not_called();self.app._invalidate_target_lock.assert_not_called()


if __name__=='__main__':unittest.main()
