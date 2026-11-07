"""Bounded image analysis and cleanup for the timer and isolated mouse probe."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import GarticTimer
from MouseProbe import run_probe
import test_gartic_timer_v10101 as timer_fixtures
from test_mouse_probe import FakeMouse, FakeMonitor, FakeStop


class TimerAnalysisTests(unittest.TestCase):
    def test_ring_converts_only_its_local_crop(self):
        frame = timer_fixtures.TimerTests().frame(.5)
        sizes = []
        original = Image.Image.convert
        def convert(image, *args, **kwargs):
            sizes.append(image.size)
            return original(image, *args, **kwargs)
        with patch.object(Image.Image, 'convert', autospec=True, side_effect=convert):
            result = GarticTimer.read_ring(frame, (200, 30, 281, 111))
        self.assertAlmostEqual(result['fraction'], .5, delta=.03)
        self.assertEqual(sizes, [(81, 81)])
        self.assertEqual(frame.size, (320, 240))

    def test_portrait_detection_is_bounded_in_both_dimensions(self):
        frame = Image.new('RGB', (100, 4000), 'white')
        shapes = []
        def components(mask, cancelled):
            shapes.append(mask.shape)
            return []
        with patch('GarticTimer._components', side_effect=components), self.assertRaises(ValueError):
            GarticTimer.find_timer(frame)
        self.assertLessEqual(max(shapes[0]), 960)

    def test_component_search_observes_cancellation_during_rows(self):
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] == 2
        with self.assertRaises(InterruptedError):
            GarticTimer._components(np.zeros((500, 100), dtype=bool), cancelled)
        self.assertEqual(calls[0], 2)

    def test_observation_timestamp_precedes_expensive_analysis(self):
        now = [100.0]
        acquired = []
        frames = []
        stop = SimpleNamespace(is_set=lambda: False, wait=lambda _: False)
        def capture():
            acquired.append(now[0]); now[0] += .2
            frame = Image.new('RGB', (5, 5)); frames.append(frame)
            return frame
        def read(*_):
            now[0] += 1
            return {'fraction': .5}
        with patch('GarticTimer.find_timer', return_value={'box': (0, 0, 5, 5)}), \
             patch('GarticTimer.read_ring', side_effect=read), \
             patch('GarticTimer.estimate_remaining', return_value={}) as estimate:
            GarticTimer.observe_timer(capture, None, stop, clock=lambda: now[0])
        self.assertEqual([row[0] for row in estimate.call_args.args[0]], acquired)
        for frame in frames:
            with self.assertRaises(ValueError):frame.getpixel((0, 0))

    def test_failed_observation_releases_capture(self):
        frame = Image.new('RGB', (5, 5))
        with patch('GarticTimer.find_timer', side_effect=ValueError('no timer')):
            with self.assertRaises(ValueError):
                GarticTimer.observe_timer(lambda: frame, None, threading.Event())
        with self.assertRaises(ValueError):frame.getpixel((0, 0))

    def test_cancel_after_final_observation_does_not_return_a_budget(self):
        stop = threading.Event()
        count = [0]
        def report(_):
            count[0] += 1
            if count[0] == 7:stop.set()
        stop.wait = lambda _: False
        with patch('GarticTimer.find_timer', return_value={'box': (0, 0, 5, 5)}), \
             patch('GarticTimer.read_ring', return_value={'fraction': .5}), \
             patch('GarticTimer.estimate_remaining') as estimate:
            with self.assertRaises(InterruptedError):
                GarticTimer.observe_timer(lambda: Image.new('RGB', (5, 5)), None, stop, report)
        estimate.assert_not_called()

    def test_malformed_timer_geometry_and_rows_fail_as_validation_errors(self):
        frame = Image.new('RGB', (20, 20))
        for box in ((0, 0, float('nan'), 10), (10, 10, 5, 5), (-1, 0, 10, 10)):
            with self.subTest(box=box), self.assertRaises(ValueError):
                GarticTimer.read_ring(frame, box)
        for rows in ([1, 2, 3, 4], [(1,), (2,), (3,), (4,) ]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                GarticTimer.estimate_remaining(rows)


class ProbeLifecycleTests(unittest.TestCase):
    def test_invalid_area_never_activates_or_arms_target(self):
        mouse = FakeMouse(); monitor = FakeMonitor()
        monitor.activate = Mock()
        with self.assertRaises(ValueError):
            run_probe((10, (0, 0, 500, 500)), (0, 0, 2, 2), mouse, monitor)
        monitor.activate.assert_not_called()
        self.assertEqual(mouse.moves, [])

    def test_reporting_failure_after_activation_still_disarms(self):
        mouse = FakeMouse(); mouse.arm_input = Mock(); mouse.disarm_input = Mock()
        report = Mock(side_effect=[None, OSError('broken output pipe')])
        with self.assertRaises(OSError):
            run_probe((10, (0, 0, 500, 500)), (10, 10, 100, 100), mouse, FakeMonitor(),
                      FakeStop(), wait=lambda _: None, report=report)
        mouse.arm_input.assert_called_once()
        mouse.disarm_input.assert_called_once()

    def test_probe_does_not_report_success_for_unobserved_movement(self):
        mouse = FakeMouse(); mouse.move = Mock()
        with self.assertRaisesRegex(OSError, 'Windows reported'):
            run_probe((10, (0, 0, 500, 500)), (10, 10, 100, 100), mouse, FakeMonitor(),
                      FakeStop(), wait=lambda _: None)


if __name__ == '__main__':
    unittest.main()
