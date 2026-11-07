"""Decode real GIFs and compare their clock with the capture timeline."""
from contextlib import ExitStack
import math
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence

from DrawBot import DrawBotApp
from ScreenRecording import gif_durations, save_gif_atomic


class RecordingClockTests(unittest.TestCase):
    def decode(self, path):
        with Image.open(path) as gif:
            return [(frame.info['duration'], frame.convert('RGB').getpixel((0, 0)))
                    for frame in ImageSequence.Iterator(gif)]

    def test_real_gif_preserves_total_capture_time_and_every_frame_colour(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            frames = [stack.enter_context(Image.new('RGB', (3, 3), 'red' if i % 2 else 'blue'))
                      for i in range(100)]
            durations = [259] * 100
            path = Path(folder) / 'recording.gif'
            save_gif_atomic(path, frames, durations)
            decoded = self.decode(path)
            self.assertEqual(len(decoded), 100)
            self.assertEqual(sum(duration for duration, _ in decoded), 25_900)
            self.assertEqual([rgb for _, rgb in decoded], [frame.getpixel((0, 0)) for frame in frames])
            self.assertEqual(durations, [259] * 100)
            for index in range(1, 101):
                self.assertLessEqual(abs(sum(duration for duration, _ in decoded[:index]) - index * 259), 5)

    def test_each_prefix_retains_the_clock_for_fractional_and_half_tick_delays(self):
        source = [20, 25, 250.49, 259.9, 300.125, 247.7] * 20
        encoded = gif_durations(source)
        self.assertTrue(all(value >= 20 and value % 10 == 0 for value in encoded))
        for count in range(1, len(source) + 1):
            self.assertLessEqual(abs(sum(encoded[:count]) - math.fsum(source[:count])), 5.000001)
        self.assertEqual(gif_durations([25, 655350, 25]), [30, 655350, 20])

    def test_pillow_merging_identical_frames_keeps_the_same_total_clock(self):
        with tempfile.TemporaryDirectory() as folder, Image.new('RGB', (3, 3), 'red') as image:
            path = Path(folder) / 'still.gif'
            save_gif_atomic(path, [image] * 100, [259] * 100)
            decoded = self.decode(path)
            self.assertEqual(len(decoded), 1)
            self.assertEqual(decoded[0], (25_900, (255, 0, 0)))

    def test_invalid_timing_cannot_replace_an_existing_recording(self):
        with tempfile.TemporaryDirectory() as folder, Image.new('RGB', (3, 3), 'red') as image:
            path = Path(folder) / 'recording.gif'
            path.write_bytes(b'previous recording')
            for duration in (float('nan'), float('inf'), -20, 0, True, '250', 10**400):
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    save_gif_atomic(path, [image], [duration])
                self.assertEqual(path.read_bytes(), b'previous recording')
                self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_actual_screen_recording_keeps_submillisecond_capture_timing(self):
        clock = SimpleNamespace(now=0.0, captures=0)
        class Stop:
            def is_set(self): return clock.captures >= 100
            def wait(self, seconds): clock.now += seconds; return False
        def capture(area):
            clock.now += .25949
            clock.captures += 1
            return Image.new('RGB', (3, 3), 'red' if clock.captures % 2 else 'blue')
        jobs = []
        app = SimpleNamespace(activity=None, closing=False,
                              corners=[(0, 0), (10, 10)], area=lambda: (0, 0, 10, 10),
                              stop=Stop(), events=queue.Queue(),
                              begin_worker=lambda activity, work: jobs.append(work))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recording.gif'
            with patch('DrawBot.filedialog.asksaveasfilename', return_value=str(path)), \
                    patch('DrawBot.time.monotonic', side_effect=lambda: clock.now), \
                    patch('DrawBot.grab_area', side_effect=capture):
                DrawBotApp.record_screen(app)
                self.assertEqual(len(jobs), 1)
                jobs[0]()
            decoded = self.decode(path)
        self.assertEqual(len(decoded), 100)
        self.assertEqual(sum(duration for duration, _ in decoded), 25_950)
        self.assertLessEqual(abs(25_949 - sum(duration for duration, _ in decoded)), 5)


if __name__ == '__main__':
    unittest.main()
