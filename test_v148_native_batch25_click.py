"""A native click owns its press/pause/release as one input transaction."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ScreenGuard import GuardedMouse
from WindowsMouse import WindowsMouse


class NativeClickOwnershipTests(unittest.TestCase):
    def mouse(self):
        mouse = object.__new__(WindowsMouse)
        mouse._native_input_lock = threading.RLock()
        mouse._input_armed = True
        mouse.held = False
        mouse.buttons_down = lambda: ('left',) if mouse.held else ()
        events = []
        mouse._send = lambda flags: events.append((threading.current_thread().name, flags))
        self.addCleanup(mouse.disarm_input)
        return mouse, events

    def click_operation(self, mouse, kind):
        if kind == 'native':
            return mouse.click
        position = [(20, 20)]
        mouse.get_position = lambda: position[0]
        mouse.move = lambda x, y: position.__setitem__(0, (x, y))
        rectangle = (0, 0, 500, 500)

        def verify(target, point):
            self.assertEqual(target, (10, rectangle))
            self.assertTrue(0 <= point[0] < 500 and 0 <= point[1] < 500)

        monitor = SimpleNamespace(rectangle=lambda _: rectangle, verify=verify,
                                  verify_modal=verify)
        guarded = GuardedMouse(mouse, monitor, (10, rectangle))
        if kind == 'modal':
            return lambda: guarded.calibrated_modal_click((30, 30))
        return guarded.click

    def run_thread(self, name, operation, errors):
        def run():
            try:
                operation()
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(name=name, target=run, daemon=True)
        thread.start()
        return thread

    def test_old_click_cleanup_cannot_release_a_newly_rearmed_drag(self):
        for kind in ('native', 'guarded', 'modal'):
            with self.subTest(kind=kind):
                self.assert_click_blocks_rearm(kind)

    def assert_click_blocks_rearm(self, kind):
        mouse, events = self.mouse()
        click = self.click_operation(mouse, kind)
        in_pause = threading.Event()
        finish_click = threading.Event()
        stop_started = threading.Event()
        new_drag_ready = threading.Event()
        errors = []

        def pause(_seconds):
            in_pause.set()
            if not finish_click.wait(3):
                raise TimeoutError('The test did not finish the first click.')

        def stop_and_start_new_drag():
            stop_started.set()
            mouse.disarm_input()
            mouse.arm_input()
            mouse.press()
            new_drag_ready.set()

        with patch('WindowsMouse.time.sleep', new=pause):
            first = self.run_thread('first-click', click, errors)
            second = None
            try:
                self.assertTrue(in_pause.wait(3))
                second = self.run_thread('new-drag', stop_and_start_new_drag, errors)
                self.assertTrue(stop_started.wait(3))
                escaped_barrier = new_drag_ready.wait(.1)
            finally:
                finish_click.set()
                first.join(3)
                if second is not None:
                    second.join(3)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(new_drag_ready.is_set())
        self.assertFalse(escaped_barrier, 'Disarm returned before the previous click finished.')
        self.assertTrue(mouse.held, 'The old click released the newly authorized drag.')
        self.assertTrue(mouse.input_armed)
        self.assertEqual(events, [('first-click', 2), ('first-click', 4), ('new-drag', 2)])

    def test_two_clicks_do_not_mistake_each_other_for_a_physical_button(self):
        for kind in ('native', 'guarded', 'modal'):
            with self.subTest(kind=kind):
                self.assert_clicks_are_serialized(kind)

    def assert_clicks_are_serialized(self, kind):
        mouse, events = self.mouse()
        click = self.click_operation(mouse, kind)
        first_paused = threading.Event()
        finish_first = threading.Event()
        second_started = threading.Event()
        errors = []

        def pause(_seconds):
            if threading.current_thread().name == 'first-click':
                first_paused.set()
                if not finish_first.wait(3):
                    raise TimeoutError('The first click was not released.')

        def second_click():
            second_started.set()
            click()

        with patch('WindowsMouse.time.sleep', new=pause):
            first = self.run_thread('first-click', click, errors)
            second = None
            try:
                self.assertTrue(first_paused.wait(3))
                second = self.run_thread('second-click', second_click, errors)
                self.assertTrue(second_started.wait(3))
                second.join(.1)
            finally:
                finish_first.set()
                first.join(3)
                if second is not None:
                    second.join(3)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(events, [('first-click', 2), ('first-click', 4),
                                  ('second-click', 2), ('second-click', 4)])
        self.assertFalse(mouse.held)

    def test_failed_click_release_retains_owner_and_unlocks_for_cleanup(self):
        mouse, events = self.mouse()
        fail_up = [True]

        def native(flags):
            events.append(flags)
            if flags == 4 and fail_up[0]:
                fail_up[0] = False
                raise OSError('The native release was rejected once.')

        mouse._send = native
        with patch('WindowsMouse.time.sleep', return_value=None):
            with self.assertRaisesRegex(OSError, 'rejected once'):
                mouse.click()
        self.assertTrue(mouse.held)
        self.assertFalse(mouse.input_armed)
        errors = []
        cleanup = self.run_thread('cleanup', mouse.disarm_input, errors)
        cleanup.join(3)
        self.assertFalse(cleanup.is_alive(), 'A failed click retained its transaction lock.')
        self.assertEqual(errors, [])
        self.assertEqual(events, [2, 4, 4])
        self.assertFalse(mouse.held)
        self.assertFalse(mouse.input_armed)


if __name__ == '__main__':
    unittest.main()
