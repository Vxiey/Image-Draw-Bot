"""Actual Stop-and-save recording uses the existing atomic publication policy."""
from contextlib import ExitStack
import errno
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence

import DrawBot
import ScreenRecording
from test_v148_ui_batch25_worker_handoff import WorkerHandoffFixture


class GifPublicationTests(WorkerHandoffFixture):
    def setUp(self):
        super().setUp()
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.destination = self.directory / 'recording.gif'
        self.unrelated = self.directory / 'recording.gif.tmp'
        self.unrelated.write_bytes(b'unrelated user file')

    def previous_recording(self):
        with Image.new('RGB', (6, 4), 'yellow') as image:
            image.save(self.destination, format='GIF', duration=250, optimize=False)
        return self.destination.read_bytes()

    def decode(self, path):
        with Image.open(path) as image:
            frames = []
            for frame in ImageSequence.Iterator(image):
                with frame.convert('RGB') as rgb:
                    frames.append((frame.info['duration'], rgb.size, rgb.tobytes()))
            return frames

    def reference_recording(self):
        path = self.directory / 'reference.gif'
        with ExitStack() as stack:
            frames = []
            for color in ('red', 'blue', 'green'):
                source = stack.enter_context(Image.new('RGB', (6, 4), color))
                frames.append(stack.enter_context(source.quantize(colors=128)))
            frames[0].save(path, format='GIF', save_all=True, append_images=frames[1:],
                           duration=[260, 260, 260], loop=0, optimize=False)
        return path

    def record(self):
        """Keep the real controller, Thread, Stop, handler, recorder and encoder."""
        app = self.app()
        clock = SimpleNamespace(now=0.0, count=0)
        raw, quantized, encodes = [], [], []
        original_quantize = Image.Image.quantize
        original_save = Image.Image.save

        def capture(area):
            self.assertEqual(area, tuple(app.area()))
            color = ('red', 'blue', 'green')[clock.count]
            clock.count += 1
            clock.now += .25949
            image = Image.new('RGB', (6, 4), color)
            raw.append(image)
            if clock.count == 3:
                DrawBot.DrawBotApp._request_stop(app)
            return image

        def quantize(source, *args, **kwargs):
            image = original_quantize(source, *args, **kwargs)
            quantized.append(image)
            return image

        def save(source, *args, **kwargs):
            encodes.append(source)
            return original_save(source, *args, **kwargs)

        def wait(seconds):
            clock.now += seconds
            return app.stop.is_set()

        with ExitStack() as stack:
            stack.enter_context(patch('DrawBot.filedialog.asksaveasfilename',
                                      return_value=str(self.destination)))
            stack.enter_context(patch('DrawBot.grab_area', side_effect=capture))
            stack.enter_context(patch('DrawBot.time.monotonic', side_effect=lambda: clock.now))
            stack.enter_context(patch.object(app.stop, 'wait', side_effect=wait))
            stack.enter_context(patch.object(Image.Image, 'quantize', new=quantize))
            stack.enter_context(patch.object(Image.Image, 'save', new=save))
            self.assertTrue(DrawBot.DrawBotApp.record_screen(app))
            events = self.finish(app)
        self.assertEqual(clock.count, 3)
        self.assertTrue(app.stop.is_set())
        self.assertIsNone(app.activity)
        self.assertEqual(app.root.visibility, 'normal')
        self.assertEqual(len(raw), 3)
        self.assertEqual(len(quantized), 3)
        self.assertEqual(len(encodes), 1)
        for image in (*raw, *quantized):
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))
        self.assertEqual(sum(kind == 'done' for kind, _value in events), 1)
        self.assertEqual(self.unrelated.read_bytes(), b'unrelated user file')
        self.assertFalse(list(self.directory.glob('.recording.gif.*.tmp')))
        return app, events

    def assert_saved(self, app, events):
        expected = ('terminal_status', ('record', 'Recording saved: recording.gif'))
        self.assertIn(expected, events)
        self.assertEqual(app.status.get(), 'Recording saved: recording.gif')
        reference = self.reference_recording()
        self.assertEqual(self.destination.read_bytes(), reference.read_bytes())
        self.assertEqual(self.decode(self.destination), self.decode(reference))
        self.assertEqual([duration for duration, _size, _data in self.decode(self.destination)],
                         [260, 260, 260])

    def test_actual_stop_finished_recording_retries_sharing_without_reencoding(self):
        actual_replace = os.replace
        for code in (32, 33):
            with self.subTest(winerror=code):
                previous = self.previous_recording()
                attempts = []
                error = OSError('transient native sharing failure')
                error.winerror = code

                def replace(source, destination):
                    attempts.append((Path(source), Path(destination)))
                    self.assertEqual(self.destination.read_bytes(), previous)
                    if len(attempts) == 1:
                        raise error
                    return actual_replace(source, destination)

                with patch('RuntimePaths.sys.platform', 'win32'), \
                     patch('RuntimePaths.time.sleep') as sleep, \
                     patch('RuntimePaths.os.replace', side_effect=replace):
                    app, events = self.record()
                self.assert_saved(app, events)
                self.assertEqual(len(attempts), 2)
                self.assertEqual(attempts[0], attempts[1])
                sleep.assert_called_once_with(.01)

    def test_actual_stop_finished_recording_supports_unsyncable_destinations(self):
        for code in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP):
            with self.subTest(errno=code):
                self.previous_recording()
                error = OSError(code, 'sync is not supported by this destination')
                with patch('RuntimePaths.os.fsync', side_effect=error) as sync:
                    app, events = self.record()
                self.assert_saved(app, events)
                sync.assert_called_once()

    def test_permanent_errors_keep_old_recording_and_close_all_worker_images(self):
        for boundary in ('encoding', 'flush', 'publication'):
            with self.subTest(boundary=boundary):
                previous = self.previous_recording()
                error = OSError(errno.ENOSPC, 'controlled permanent recording failure')
                with ExitStack() as stack:
                    if boundary == 'encoding':
                        def partial(_image, stream, *args, **kwargs):
                            stream.write(b'incomplete GIF')
                            raise error
                        stack.enter_context(patch.object(Image.Image, 'save', new=partial))
                    elif boundary == 'flush':
                        stack.enter_context(patch('RuntimePaths.os.fsync', side_effect=error))
                    else:
                        stack.enter_context(patch('RuntimePaths.os.replace', side_effect=error))
                    app, events = self.record()
                self.assertEqual(self.destination.read_bytes(), previous)
                self.assertFalse(any(kind == 'terminal_status' and 'Recording saved:' in str(value)
                                     for kind, value in events))
                self.assertIn('controlled permanent recording failure', app.status.get())

    def test_public_writer_preserves_input_ownership_and_primary_error(self):
        previous = self.previous_recording()
        with Image.new('P', (4, 3), 2) as frame:
            error = OSError(errno.EIO, 'primary GIF flush failure')
            owned = []
            unlink = Path.unlink

            def failed_cleanup(path, *args, **kwargs):
                if path.parent == self.directory and path.name.startswith('.recording.gif.'):
                    owned.append(path)
                    raise PermissionError('secondary cleanup failure')
                return unlink(path, *args, **kwargs)

            try:
                with patch('RuntimePaths.os.fsync', side_effect=error), \
                     patch.object(Path, 'unlink', new=failed_cleanup):
                    with self.assertRaises(OSError) as caught:
                        ScreenRecording.save_gif_atomic(self.destination, [frame], [250])
                self.assertIs(caught.exception, error)
                self.assertEqual(self.destination.read_bytes(), previous)
                self.assertEqual(frame.getpixel((0, 0)), 2)
                self.assertEqual(len(owned), 1)
            finally:
                for path in owned:
                    path.unlink(missing_ok=True)
            self.assertIsNone(ScreenRecording.save_gif_atomic(self.destination, [frame], [250]))
            self.assertEqual(frame.getpixel((0, 0)), 2)
        self.assertFalse(list(self.directory.glob('.recording.gif.*.tmp')))
        self.assertEqual(self.unrelated.read_bytes(), b'unrelated user file')


if __name__ == '__main__':
    unittest.main(verbosity=2)
