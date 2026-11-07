"""Only exact adjacent screen captures may share retained GIF storage."""
from contextlib import ExitStack
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence

from DrawBot import DrawBotApp
from ScreenRecording import append_recorded_frame, gif_durations, save_gif_atomic


class RecordingFrameRetentionTests(unittest.TestCase):
    def test_same_indexes_with_different_palette_or_transparency_are_not_equal(self):
        with ExitStack() as stack:
            red = stack.enter_context(Image.new('P', (3, 3), 0))
            red.putpalette([255, 0, 0] + [0] * 765)
            blue = stack.enter_context(Image.new('P', (3, 3), 0))
            blue.putpalette([0, 0, 255] + [0] * 765)
            transparent = stack.enter_context(red.copy()); transparent.info['transparency'] = 0
            changed = stack.enter_context(red.copy()); changed.putpixel((2, 2), 1)
            frames, durations = [red], [250]
            for image in (blue, transparent, changed):
                self.assertTrue(append_recorded_frame(frames, durations, image, 250))
            self.assertEqual(len(frames), 4)
            self.assertEqual(durations, [250] * 4)

    def test_repeated_frame_boundaries_keep_the_visible_gif_timeline(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            source = [stack.enter_context(Image.new('RGB', (3, 3), color))
                      for color in ['red'] * 20 + ['blue'] * 40 + ['red'] * 40]
            durations = [259.49] * 100
            frames, merged_durations = [], []
            for frame, duration in zip(source, durations):
                append_recorded_frame(frames, merged_durations, frame, duration)
            self.assertEqual(len(frames), 3)
            path, expected = Path(folder) / 'merged.gif', Path(folder) / 'reference.gif'
            save_gif_atomic(path, frames, merged_durations)
            source[0].save(expected, format='GIF', save_all=True, append_images=source[1:],
                           duration=gif_durations(durations), loop=0, optimize=False)
            def timeline(path):
                with Image.open(path) as image:
                    result=[]
                    for frame in ImageSequence.Iterator(image):
                        with frame.convert('RGB') as rgb:
                            result.append((frame.info['duration'], rgb.tobytes()))
                    return result
            self.assertEqual(timeline(path), timeline(expected))
            self.assertEqual(sum(duration for duration, _ in timeline(path)), 25_950)

    def actual_recording(self, path, *, fail_comparison=False):
        clock = SimpleNamespace(now=0.0, count=0)
        images=[]; observed={}
        class Stop:
            def is_set(self): return clock.count >= 100
            def wait(self, seconds): clock.now += seconds; return False
        def capture(area):
            clock.now += .25949; clock.count += 1
            return Image.new('RGB', (64, 40), 'red')
        quantize = Image.Image.quantize
        def quantized(frame, *args, **kwargs):
            image = quantize(frame, *args, **kwargs)
            images.append(image)
            return image
        def save(destination, frames, durations):
            observed['frames'] = len(frames)
            observed['duration'] = sum(durations)
            observed['retained_pixels'] = sum(frame.width * frame.height for frame in frames)
            for old in images[1:]:
                with self.assertRaises(ValueError): old.getpixel((0, 0))
            return save_gif_atomic(destination, frames, durations)
        jobs=[]
        app=SimpleNamespace(activity=None, closing=False,
            corners=[(0, 0), (64, 40)], area=lambda: (0, 0, 64, 40),
            stop=Stop(), events=queue.Queue(), begin_worker=lambda activity, work: jobs.append(work))
        with ExitStack() as stack:
            stack.enter_context(patch('DrawBot.filedialog.asksaveasfilename', return_value=str(path)))
            stack.enter_context(patch('DrawBot.time.monotonic', side_effect=lambda: clock.now))
            stack.enter_context(patch('DrawBot.grab_area', side_effect=capture))
            stack.enter_context(patch.object(Image.Image, 'quantize', new=quantized))
            stack.enter_context(patch('ScreenRecording.save_gif_atomic', side_effect=save))
            if fail_comparison:
                stack.enter_context(patch.object(Image.Image, 'tobytes', side_effect=OSError('comparison failed')))
            DrawBotApp.record_screen(app)
            if fail_comparison:
                with self.assertRaisesRegex(OSError, 'comparison failed'): jobs[0]()
            else: jobs[0]()
        for image in images:
            with self.assertRaises(ValueError): image.getpixel((0, 0))
        return observed

    def test_actual_capture_releases_duplicates_before_the_final_encoder_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'recording.gif'
            observed=self.actual_recording(path)
            self.assertEqual(observed['frames'], 1)
            self.assertEqual(observed['retained_pixels'], 64 * 40)
            self.assertAlmostEqual(observed['duration'], 25_949)
            with Image.open(path) as image:
                self.assertEqual(image.n_frames, 1)
                self.assertEqual(image.info['duration'], 25_950)

    def test_failed_comparison_closes_current_and_retained_images_without_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'recording.gif'; path.write_bytes(b'previous')
            self.actual_recording(path, fail_comparison=True)
            self.assertEqual(path.read_bytes(), b'previous')


if __name__ == '__main__':
    unittest.main()
