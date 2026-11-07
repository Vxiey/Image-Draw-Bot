import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from StabilityRC import safe_release_and_disarm
from WindowsMouse import WindowsMouse


class MouseCleanupTests(unittest.TestCase):
    def mouse(self):
        mouse = object.__new__(WindowsMouse)
        mouse.held = False
        mouse._input_armed = True
        mouse.buttons_down = lambda: ()
        mouse._send = Mock()
        return mouse

    def test_failed_release_remains_owned_for_the_disarm_cleanup_retry(self):
        mouse = self.mouse()
        mouse.held = True
        mouse._send.side_effect = [OSError('native input temporarily blocked'), None]
        errors = safe_release_and_disarm(mouse)
        self.assertEqual([kind for kind, _ in errors], ['release'])
        self.assertEqual([call.args for call in mouse._send.call_args_list], [(4,), (4,)])
        self.assertFalse(mouse.held)
        self.assertFalse(mouse.input_armed)

    def test_failed_disarm_keeps_cleanup_retryable_but_never_authorizes_input(self):
        mouse = self.mouse()
        mouse.held = True
        mouse._send.side_effect = [OSError('blocked'), None]
        with self.assertRaises(OSError):
            mouse.disarm_input()
        self.assertTrue(mouse.held)
        self.assertFalse(mouse.input_armed)
        with self.assertRaises(PermissionError):
            mouse.press()
        mouse.disarm_input()
        self.assertFalse(mouse.held)
        mouse.disarm_input()
        self.assertEqual(mouse._send.call_count, 2)

    def test_new_explicit_arm_first_cleans_its_own_pending_button(self):
        mouse = self.mouse()
        mouse.held = True
        mouse._input_armed = False
        mouse._send.side_effect = [OSError('blocked'), None]
        with self.assertRaises(OSError):
            mouse.arm_input()
        self.assertFalse(mouse.input_armed)
        mouse.arm_input()
        self.assertTrue(mouse.input_armed)
        self.assertFalse(mouse.held)
        self.assertEqual([call.args for call in mouse._send.call_args_list], [(4,), (4,)])

    def test_disarm_is_a_barrier_for_an_already_started_button_command(self):
        mouse = self.mouse()
        entered = threading.Event()
        continue_press = threading.Event()
        disarm_started = threading.Event()
        disarm_finished = threading.Event()
        errors = []
        events = []

        def buttons_down():
            entered.set()
            if not continue_press.wait(3):
                raise TimeoutError('test fixture did not release the press')
            return ()

        def press():
            try:
                mouse.press()
            except BaseException as error:
                errors.append(error)

        def disarm():
            disarm_started.set()
            try:
                mouse.disarm_input()
                events.append('disarmed')
            except BaseException as error:
                errors.append(error)
            finally:
                disarm_finished.set()

        mouse.buttons_down = buttons_down
        mouse._send = lambda flags: events.append(flags)
        worker = threading.Thread(target=press, daemon=True)
        stopper = threading.Thread(target=disarm, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            stopper.start()
            self.assertTrue(disarm_started.wait(3))
            self.assertFalse(disarm_finished.wait(.05), 'disarm returned during an authorized native command')
        finally:
            continue_press.set()
            worker.join(3)
            if stopper.ident is not None:
                stopper.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(events, [2, 4, 'disarmed'])
        self.assertFalse(mouse.held)
        self.assertFalse(mouse.input_armed)
        with self.assertRaises(PermissionError):
            mouse.press()

    def test_disarm_also_waits_for_inflight_cursor_movement(self):
        mouse = self.mouse()
        entered = threading.Event()
        continue_move = threading.Event()
        stopped = threading.Event()
        stop_started = threading.Event()
        errors = []
        events = []
        def move_cursor(x, y):
            entered.set()
            if not continue_move.wait(3):
                raise TimeoutError('fixture did not release cursor command')
            events.append('move')
            return 1
        mouse.api = SimpleNamespace(GetSystemMetrics=lambda i: {76: 0, 77: 0, 78: 200, 79: 200}[i],
                                    SetCursorPos=move_cursor)
        mouse.get_position = lambda: (10, 20)
        def move():
            try:
                mouse.move(10, 20)
            except BaseException as error:
                errors.append(error)
        def disarm():
            stop_started.set()
            mouse.disarm_input()
            events.append('disarmed')
            stopped.set()
        with patch('WindowsMouse.ctypes.set_last_error', create=True):
            worker = threading.Thread(target=move, daemon=True)
            stopper = threading.Thread(target=disarm, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                stopper.start()
                self.assertTrue(stop_started.wait(3))
                self.assertFalse(stopped.wait(.05))
            finally:
                continue_move.set()
                worker.join(3)
                if stopper.ident is not None:
                    stopper.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(events, ['move', 'disarmed'])
        self.assertFalse(mouse.input_armed)
        with self.assertRaises(PermissionError):
            mouse.move(10, 20)


if __name__ == '__main__':
    unittest.main()
