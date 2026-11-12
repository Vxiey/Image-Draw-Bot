"""A native target cannot change process/thread while input owns its HWND."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ScreenGuard import GuardedMouse, WindowMonitor


class TargetIdentityTests(unittest.TestCase):
    def fixture(self):
        state = SimpleNamespace(pid=201, thread=301, foreground=10, valid=True)

        def process(handle, pointer):
            pointer._obj.value = state.pid
            return state.thread

        def rectangle(handle, pointer):
            value = pointer._obj
            value.left, value.top, value.right, value.bottom = 0, 0, 400, 300
            return 1

        monitor = object.__new__(WindowMonitor)
        monitor.api = SimpleNamespace(
            IsWindow=lambda handle: state.valid,
            IsWindowVisible=lambda handle: True,
            IsIconic=lambda handle: False,
            GetWindowThreadProcessId=process,
            GetWindowRect=rectangle,
            GetForegroundWindow=lambda: state.foreground,
            SetForegroundWindow=lambda handle: 1,
        )
        monitor.at = lambda point: state.foreground
        monitor.in_client_area = lambda handle, point: True
        events = []
        mouse = SimpleNamespace(
            get_position=lambda: (20, 20),
            move=lambda *point: events.append(('move', point)),
            arm_input=lambda: events.append(('armed',)),
            disarm_input=lambda: events.append(('disarmed',)),
        )
        guard = GuardedMouse(mouse, monitor, (10, (0, 0, 400, 300)))
        return state, monitor, guard, events

    def prepare(self, guard):
        guard.prepare_target(threading.Event(), lambda seconds: None, lambda *args: None)

    def test_same_target_moves_after_binding(self):
        state, monitor, guard, events = self.fixture()
        with patch('ScreenGuard.ctypes.set_last_error', create=True):
            self.prepare(guard)
            guard.move(20, 20)
            guard.move(20, 20)
        self.assertEqual(events, [('armed',), ('move', (20, 20)), ('move', (20, 20))])

    def test_recycled_handle_stops_before_moving_to_a_different_process(self):
        state, monitor, guard, events = self.fixture()
        with patch('ScreenGuard.ctypes.set_last_error', create=True):
            self.prepare(guard)
            state.pid += 1
            with self.assertRaisesRegex(InterruptedError, 'identity'):
                guard.move(20, 20)
        self.assertEqual(events, [('armed',)])

    def test_changed_owner_thread_stops_even_when_process_and_geometry_match(self):
        state, monitor, guard, events = self.fixture()
        with patch('ScreenGuard.ctypes.set_last_error', create=True):
            self.prepare(guard)
            state.thread += 1
            with self.assertRaisesRegex(InterruptedError, 'identity'):
                guard.move(20, 20)
        self.assertEqual(events, [('armed',)])

    def test_failed_identity_query_never_arms_input(self):
        for field in ('pid', 'thread'):
            with self.subTest(field=field):
                state, monitor, guard, events = self.fixture()
                setattr(state, field, 0)
                with patch('ScreenGuard.ctypes.set_last_error', create=True):
                    with self.assertRaises(InterruptedError):
                        self.prepare(guard)
                self.assertEqual(events, [])

    def test_target_replaced_during_activation_never_arms_input(self):
        state, monitor, guard, events = self.fixture()

        def activate(handle):
            state.pid += 1
            return 1

        monitor.api.SetForegroundWindow = activate
        with patch('ScreenGuard.ctypes.set_last_error', create=True):
            with self.assertRaisesRegex(InterruptedError, 'identity'):
                self.prepare(guard)
        self.assertEqual(events, [])

    def test_rearming_same_guard_cannot_replace_its_previous_owner(self):
        state, monitor, guard, events = self.fixture()
        with patch('ScreenGuard.ctypes.set_last_error', create=True):
            self.prepare(guard)
            guard.disarm_input()
            state.pid += 1
            with self.assertRaisesRegex(InterruptedError, 'identity'):
                self.prepare(guard)
        self.assertEqual(events, [('armed',), ('disarmed',)])


if __name__ == '__main__':
    unittest.main()
