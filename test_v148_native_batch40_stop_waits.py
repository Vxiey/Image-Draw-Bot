"""Stop interrupts native verification waits and still releases owned input."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ScreenGuard import GuardedMouse


class _CancelOnWait(threading.Event):
    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self.set()
        return True


class NativeStopWaitTests(unittest.TestCase):
    def guard(self):
        actions = []
        samples = []
        mouse = SimpleNamespace(get_position=lambda: (20, 20), arm_input=lambda: None,
            press=lambda: actions.append('press'), release=lambda: actions.append('release'))
        monitor = SimpleNamespace(activate=lambda target: True, active=lambda target: True,
            verify=lambda *args: None,
            colors_near=lambda *args: samples.append(args) or [(255, 255, 255)])
        guard = GuardedMouse(mouse, monitor, (10, (0, 0, 400, 300)))
        stop = _CancelOnWait()
        guard.prepare_target(stop, lambda seconds: None, lambda *args: None)
        return guard, stop, actions, samples

    def test_ink_and_fill_stop_inside_settle_without_sampling_again(self):
        for operation in ('ink', 'fill'):
            with self.subTest(operation=operation):
                guard, stop, actions, samples = self.guard()
                with patch('ScreenGuard.time.sleep') as ordinary_sleep:
                    with self.assertRaises(InterruptedError):
                        if operation == 'ink':
                            guard.inspect_ink_segment((20, 20), (20, 20), (0, 0, 0))
                        else:
                            guard.verify_fill((20, 20), (0, 0, 0))
                ordinary_sleep.assert_not_called()
                self.assertEqual(len(stop.waits), 1)
                self.assertEqual(len(samples), 1)
                self.assertEqual(actions, [])

    def test_stop_during_click_settle_releases_the_pressed_button(self):
        guard, stop, actions, samples = self.guard()
        with patch('ScreenGuard.time.sleep') as ordinary_sleep:
            with self.assertRaises(InterruptedError):
                guard.click()
        ordinary_sleep.assert_not_called()
        self.assertEqual(stop.waits, [.015])
        self.assertEqual(actions, ['press', 'release'])

    def test_stop_before_click_sends_no_input(self):
        guard, stop, actions, samples = self.guard()
        stop.set()
        with self.assertRaises(InterruptedError):
            guard.click()
        self.assertEqual(actions, [])
        self.assertEqual(stop.waits, [])

    def test_stop_during_overlay_retry_never_revalidates_or_clicks(self):
        guard, stop, actions, samples = self.guard()
        checks = []
        def covered(*args):
            checks.append(args)
            raise InterruptedError('Stopped: another window covers the click position.')
        guard.monitor.verify = covered
        with patch('ScreenGuard.time.sleep') as ordinary_sleep:
            with self.assertRaisesRegex(InterruptedError, 'cancelled'):
                guard.click()
        ordinary_sleep.assert_not_called()
        self.assertEqual(len(checks), 1)
        self.assertEqual(actions, [])
        self.assertEqual(stop.waits, [.08])

    def test_legacy_is_set_only_token_remains_supported_and_checked_after_wait(self):
        guard, _, actions, _ = self.guard()
        cancelled = [False]
        token = SimpleNamespace(is_set=lambda: cancelled[0])
        guard.prepare_target(token, lambda seconds: None, lambda *args: None)
        with patch('ScreenGuard.time.sleep', side_effect=lambda seconds: cancelled.__setitem__(0, True)):
            with self.assertRaises(InterruptedError):
                guard.click()
        self.assertEqual(actions, ['press', 'release'])


if __name__ == '__main__':
    unittest.main()
