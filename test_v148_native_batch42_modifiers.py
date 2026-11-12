"""Physical modifier keys must not change an authorized native mouse gesture."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from WindowsMouse import WindowsMouse


class NativeBoundary:
    def __init__(self):
        self.down=set();self.events=[];self.position=(20,30)

    def GetAsyncKeyState(self,key):
        return 0x8000 if key in self.down else 0

    def GetSystemMetrics(self,key):
        return {76:-400,77:-300,78:800,79:600}[key]

    def SetCursorPos(self,x,y):
        self.events.append(('move',x,y));self.position=(x,y)
        return 1

    def SendInput(self,count,pointer,size):
        event=pointer._obj.mi
        self.events.append(('input',event.dwFlags,event.dx,event.dy))
        return 1


class ModifierOwnershipTests(unittest.TestCase):
    def mouse(self):
        api=NativeBoundary();mouse=object.__new__(WindowsMouse)
        mouse.api=api;mouse.held=False;mouse._input_armed=True
        mouse.get_position=lambda:api.position
        self.enterContext(patch('WindowsMouse.ctypes.set_last_error',create=True))
        return mouse,api

    def test_each_modifier_blocks_arm_and_press_without_releasing_user_keys(self):
        for key in (0x10,0x11,0x12,0x5B,0x5C):
            for action in ('arm_input','press'):
                with self.subTest(key=key,action=action):
                    mouse,api=self.mouse();api.down.add(key)
                    with self.assertRaisesRegex(InterruptedError,'keyboard modifiers'):
                        getattr(mouse,action)()
                    self.assertEqual(api.events,[])
                    self.assertEqual(api.down,{key})
                    self.assertFalse(mouse.held)
                    if action=='arm_input':self.assertFalse(mouse.input_armed)

    def test_modifier_takeover_blocks_both_drag_backends_but_allows_owned_leftup(self):
        for backend in ('cursor','sendinput'):
            with self.subTest(backend=backend):
                mouse,api=self.mouse();mouse.press();mouse.drag_backend=backend
                api.down.update((0x01,0x10))
                with self.assertRaisesRegex(InterruptedError,'Shift'):
                    mouse.move(-20,40)
                mouse.disarm_input()
                self.assertEqual([row[1] for row in api.events],[2,4])
                self.assertFalse(mouse.held);self.assertFalse(mouse.input_armed)
                self.assertIn(0x10,api.down)

    def test_modifier_arriving_during_retry_prevents_the_next_native_send(self):
        for backend in ('cursor','sendinput'):
            with self.subTest(backend=backend):
                mouse,api=self.mouse();mouse.held=True;mouse.drag_backend=backend
                mouse.position_attempts=3;mouse.position_retry_after=1
                mouse.get_position=lambda:(0,0)
                def settle(_):api.down.add(0x11)
                with patch('WindowsMouse.time.sleep',side_effect=settle):
                    with self.assertRaisesRegex(InterruptedError,'Ctrl'):
                        mouse.move(20,30)
                self.assertEqual(len(api.events),1)
                self.assertTrue(mouse.held)
                mouse.release()
                self.assertEqual(api.events[-1][1],4)

    def test_releasing_the_modifier_requires_an_explicit_new_arm_and_keeps_normal_input(self):
        mouse,api=self.mouse();api.down.add(0x12)
        with self.assertRaises(InterruptedError):mouse.arm_input()
        api.down.clear()
        with self.assertRaises(PermissionError):mouse.press()
        mouse.arm_input();mouse.move(-20,40);mouse.press();mouse.release()
        self.assertEqual(api.events[0],('move',-20,40))
        self.assertEqual([row[1] for row in api.events[1:]],[2,4])

    def test_modifier_takeover_also_blocks_real_keyboard_and_modal_write_guards(self):
        from ScreenGuard import GuardedMouse
        rectangle=(0,0,100,100)
        monitor=SimpleNamespace(verify=lambda *_:None,verify_modal=lambda *_:None,
                                rectangle=lambda _:rectangle)
        for point in (None,(20,30)):
            for key in (0x10,0x11,0x12,0x5B,0x5C):
                with self.subTest(point=point,key=key):
                    mouse,api=self.mouse()
                    guard=GuardedMouse(mouse,monitor,(42,rectangle))
                    guard.check_keyboard(modal_point=point)
                    api.down.add(key)
                    with self.assertRaisesRegex(InterruptedError,'keyboard modifiers'):
                        guard.check_keyboard(modal_point=point)
                    self.assertEqual(api.events,[])
                    self.assertEqual(api.down,{key})


if __name__=='__main__':unittest.main()
