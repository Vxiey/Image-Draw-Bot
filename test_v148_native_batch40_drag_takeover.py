"""User button input during an owned drag stops before the next cursor event."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from WindowsMouse import WindowsMouse


class DragTakeoverTests(unittest.TestCase):
    def mouse(self, buttons):
        mouse = object.__new__(WindowsMouse)
        mouse.held = True
        mouse._input_armed = True
        mouse.buttons_down = lambda: buttons
        events = []
        mouse.api = SimpleNamespace(
            GetSystemMetrics=lambda i: {76: 0, 77: 0, 78: 400, 79: 300}[i],
            SetCursorPos=lambda *point: events.append(('move', point)) or 1,
        )
        mouse.get_position = lambda: (20, 30)
        mouse._send = lambda flags: events.append(('button', flags))
        return mouse, events

    def test_conflicting_button_during_drag_never_sends_a_cursor_event(self):
        for button in ('right', 'middle', 'x1', 'x2'):
            with self.subTest(button=button):
                mouse, events = self.mouse(('left', button))
                with patch('WindowsMouse.ctypes.set_last_error', create=True):
                    with self.assertRaises(InterruptedError):
                        mouse.move(20, 30)
                self.assertEqual(events, [])
                self.assertTrue(mouse.held)
                mouse.release()
                self.assertEqual(events, [('button', 4)])
                self.assertFalse(mouse.held)

    def test_own_left_button_does_not_block_the_next_drag_move(self):
        mouse, events = self.mouse(('left',))
        with patch('WindowsMouse.ctypes.set_last_error', create=True):
            mouse.move(20, 30)
        self.assertEqual(events, [('move', (20, 30))])

    def test_lagging_left_button_observation_does_not_falsely_stop_an_owned_drag(self):
        mouse, events = self.mouse(())
        with patch('WindowsMouse.ctypes.set_last_error', create=True):
            mouse.move(20, 30)
        self.assertEqual(events, [('move', (20, 30))])

    def test_button_pressed_during_position_retry_stops_before_another_send(self):
        for backend in ('cursor', 'sendinput'):
            with self.subTest(backend=backend):
                mouse, events = self.mouse(('left',))
                mouse.drag_backend = backend
                mouse.position_attempts = 3
                mouse.position_retry_after = 1
                mouse.get_position = lambda: (0, 0)
                mouse.buttons_down = lambda: ('left', 'right') if events else ('left',)
                mouse._send_absolute_move = lambda *point: events.append(('move', point))
                with patch('WindowsMouse.ctypes.set_last_error', create=True), patch('WindowsMouse.time.sleep'):
                    with self.assertRaises(InterruptedError):
                        mouse.move(20, 30)
                self.assertEqual(events, [('move', (20, 30))])
                self.assertTrue(mouse.held)


if __name__ == '__main__':
    unittest.main()
