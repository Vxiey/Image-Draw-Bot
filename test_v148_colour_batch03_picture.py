"""Picture palette transaction tests use only fake input and window APIs."""
from queue import Queue
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import PictureCustomPalette as picture


CONTROLS={name:(10+index*10,20+index*10) for index,name in enumerate(
    ('OpenCustomColor','RedField','GreenField','BlueField','ConfirmColor','AddCustomColor'))}


class Mouse:
    def __init__(self,stop):self.stop=stop;self.events=[];self.point=(0,0);self.armed=False
    def arm_input(self):self.armed=True;self.events.append(('arm',self.stop.is_set()))
    def disarm_input(self):self.armed=False;self.events.append(('disarm',self.stop.is_set()))
    def move(self,x,y):self.point=(x,y);self.events.append(('move',self.stop.is_set()))
    def get_position(self):return self.point
    def click(self):self.events.append(('click',self.stop.is_set()))


class Keyboard:
    def __init__(self,stop,on_press=None):self.stop=stop;self.events=[];self.on_press=on_press
    def press_and_release(self,key):
        self.events.append((key,self.stop.is_set()))
        if self.on_press:self.on_press(key)
    def write(self,text,delay=0):self.events.append(('write:'+text,self.stop.is_set()))


class PictureTransactionTests(unittest.TestCase):
    def test_full_custom_budget_skips_unusable_edge_augmentation(self):
        import PictureCustomPaletteLegacy as legacy
        with patch.object(legacy,'load_cached_palette',return_value=None), \
             patch.object(legacy,'save_palette'), \
             patch.object(legacy,'_edge_detail_colors',side_effect=AssertionError('full palette cannot use details')):
            result=legacy.build_picture_palette(Image.new('RGB',(24,24),(40,60,80)),
                [(0,0,0)],max_colors=1)
        self.assertEqual(result.colors,((40,60,80),))

    def test_stop_during_move_wait_prevents_click_and_cleanup_keys(self):
        stop=threading.Event();mouse=Mouse(stop);keyboard=Keyboard(stop)
        with self.assertRaises(InterruptedError):
            picture.apply_custom_rgb_sequence(mouse,keyboard,CONTROLS,[(1,2,3)],
                cancelled=stop.is_set,wait=lambda _delay:stop.set())
        self.assertNotIn(('click',True),mouse.events)
        self.assertEqual(keyboard.events,[])
        self.assertFalse(mouse.armed)

    def test_focus_change_after_select_all_prevents_rgb_typing_and_cleanup(self):
        stop=threading.Event();mouse=Mouse(stop);owned=[True]
        keyboard=Keyboard(stop,on_press=lambda key:owned.__setitem__(0,False))
        checks=[]
        def guard(point,*,modal=False):
            checks.append((point,modal))
            if not owned[0]:raise InterruptedError('focus moved')
        with self.assertRaisesRegex(InterruptedError,'focus moved'):
            picture.apply_custom_rgb_sequence(mouse,keyboard,CONTROLS,[(1,2,3)],
                cancelled=stop.is_set,wait=lambda _:None,input_guard=guard)
        self.assertEqual(keyboard.events,[('ctrl+a',False)])
        self.assertTrue(any(modal for _,modal in checks))
        self.assertFalse(mouse.armed)

    def test_stop_from_ready_callback_prevents_numeric_input(self):
        stop=threading.Event();mouse=Mouse(stop);keyboard=Keyboard(stop)
        def ready():stop.set();return {}
        with self.assertRaises(InterruptedError):
            picture.apply_custom_rgb_sequence(mouse,keyboard,CONTROLS,[(1,2,3)],
                cancelled=stop.is_set,wait=lambda _:None,dialog_ready=ready)
        self.assertEqual(keyboard.events,[])
        self.assertFalse(mouse.armed)

    def test_owned_non_cancel_failure_can_cleanup_but_foreign_target_cannot(self):
        for owned in (True,False):
            stop=threading.Event();mouse=Mouse(stop);keyboard=Keyboard(stop);failed=[False]
            def guard(point,*,modal=False):
                if failed[0] and not owned:raise InterruptedError('foreign target')
            def ready():failed[0]=True;raise ValueError('not ready')
            with self.subTest(owned=owned),self.assertRaisesRegex(ValueError,'not ready'):
                picture.apply_custom_rgb_sequence(mouse,keyboard,CONTROLS,[(1,2,3)],
                    cancelled=stop.is_set,wait=lambda _:None,dialog_ready=ready,input_guard=guard)
            self.assertEqual(keyboard.events,[('esc',False)] if owned else [])
            self.assertFalse(mouse.armed)

    def test_production_fingerprint_failure_is_not_replaced_with_empty_context(self):
        import PictureCustomPaletteLegacy as legacy
        stop=Mock();stop.is_set.return_value=False;stop.wait.return_value=False
        variable=lambda value:SimpleNamespace(get=lambda:value)
        app=SimpleNamespace(activity=None,closing=False,game=variable('Microsoft Paint'),
            original=Image.new('RGB',(4,4),(1,2,3)),status=Mock(),stop=stop,
            events=Queue(),exact_color_limit=variable('8'),draw_quality=variable('High likeness'),
            color_fidelity=variable('Faithful'),calibration_path='unused-test-palette.json')
        app.begin_worker=lambda _kind,work:work()
        monitor=Mock();monitor.activate.return_value=True
        with patch.object(legacy,'_resolve_target',return_value=(42,(0,0,100,100))), \
             patch('ScreenGuard.WindowMonitor',return_value=monitor), \
             patch('TargetCapture.probe_handle_isolated',return_value={'handle':42,'client_rect':(0,0,100,100)}), \
             patch('ExactColorTools.numeric_rgb_available',return_value=True), \
             patch('ExactColorTools.resolved_controls',return_value=CONTROLS), \
             patch('ProfileStorage.calibration_context_fingerprint',side_effect=ValueError('unreadable calibration')), \
             patch.object(legacy,'build_picture_palette') as build:
            with self.assertRaisesRegex(ValueError,'unreadable calibration'):
                picture.start_picture_custom_palette(app)
            build.assert_not_called()


if __name__=='__main__':unittest.main()
