"""Actual capture-dialog preview callbacks, using existing screenshots/art."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp


ASSETS = Path(__file__).parent / 'assets'


class CapturePreviewTests(unittest.TestCase):
    def image(self, name='image-draw-bot-app-screenshot.png', mode='RGB', small=False):
        with Image.open(ASSETS / name) as opened:
            result = opened.convert(mode)
        if small:
            previous = result
            result = previous.resize((63, 37), Image.Resampling.NEAREST)
            previous.close()
        self.addCleanup(result.close)
        return result

    def app(self):
        jobs = []
        app = SimpleNamespace(activity=None, closing=False, root=object(), original=None,
            status=Mock(), file_label=Mock(), stop=threading.Event(), events=queue.Queue(),
            show_previews=Mock(), _mark_plan_stale=Mock(),
            _schedule_recovery_checkpoint=Mock(), _maybe_auto_preview=Mock())
        def begin(_activity, task, **_kwargs):
            jobs.append(task)
            return True
        app.begin_worker = begin
        return app, jobs

    def display(self, app, source, photo):
        callbacks, buttons = {}, {}
        window = Mock()
        window.bind.side_effect = lambda event, callback, **kwargs: callbacks.__setitem__(event, callback)
        window.destroy.side_effect = lambda: callbacks['<Destroy>'](SimpleNamespace(widget=window))
        self.addCleanup(window.destroy)
        def button(_parent, **options):
            buttons[options['text']] = options['command']
            return Mock()
        with patch('DrawBot.tk.Toplevel', return_value=window), patch('DrawBot.ttk.Label'), \
                patch('DrawBot.ttk.Button', side_effect=button), \
                patch('PIL.ImageTk.PhotoImage', new=photo):
            DrawBotApp.display_screen(app, source)
        return window, buttons

    def test_real_dialog_matches_thumbnail_pixels_without_full_capture_copy(self):
        cases = [('screen-RGB', self.image()),
                 ('screen-RGBA', self.image(mode='RGBA')),
                 ('alpha-RGBA', self.image('image-draw-bot-icon.png', mode='RGBA')),
                 ('small-RGB', self.image(small=True)),
                 ('small-RGBA', self.image('image-draw-bot-icon.png', mode='RGBA', small=True))]
        keyed = self.image()
        keyed.info['transparency'] = keyed.getpixel((0, 0))
        cases.append(('color-key-RGB', keyed))
        copy = Image.Image.copy
        for name, source in cases:
            with self.subTest(case=name):
                before = source.tobytes(), deepcopy(source.info)
                with closing(source.copy()) as previous:
                    previous.thumbnail((800, 480))
                    expected = previous.mode, previous.size, previous.tobytes(), deepcopy(previous.info)
                copied, previews = [], []
                def tracked_copy(image):
                    if image is source:
                        copied.append(image.width * image.height * max(4, len(image.getbands())))
                    return copy(image)
                def photo(view):
                    previews.append(view)
                    self.assertEqual((view.mode, view.size, view.tobytes(), view.info), expected)
                    return object()
                app, _jobs = self.app()
                with patch.object(Image.Image, 'copy', tracked_copy):
                    self.display(app, source, photo)
                self.assertEqual((source.tobytes(), source.info), before)
                self.assertEqual(len(copied), int(source.size == expected[1]),
                                 'Only an identity-size owned display result needs a source copy')
                self.assertEqual(len(previews), 1)
                with self.assertRaises(ValueError):
                    previews[0].getpixel((0, 0))

    def test_use_and_save_callbacks_keep_the_original_full_resolution_capture(self):
        source = self.image()
        expected_size, expected_pixels = source.size, source.tobytes()
        with closing(source.convert('RGBA')) as rgba:
            expected_rgba = rgba.tobytes()
        app, jobs = self.app()
        window, buttons = self.display(app, source, lambda _view: object())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.png'
            with patch('DrawBot.filedialog.asksaveasfilename', return_value=str(path)):
                self.assertTrue(buttons['Save screenshot']())
            self.assertEqual(len(jobs), 1)
            jobs.pop()()
            with Image.open(path) as saved:
                self.assertEqual((saved.mode, saved.size, saved.tobytes()),
                                 ('RGB', expected_size, expected_pixels))
        with patch('SessionRecovery.clear_render_progress'):
            buttons['Use as source image']()
        self.addCleanup(app.original.close)
        self.assertEqual((app.original.mode, app.original.size, app.original.tobytes()),
                         ('RGBA', expected_size, expected_rgba))
        self.assertIsNot(app.original, source)
        window.destroy.assert_called_once()
        with self.assertRaises(ValueError):
            source.getpixel((0, 0))

    def test_photo_failure_closes_bounded_view_and_dialog_owned_source_with_traceback_retained(self):
        source = self.image()
        app, _jobs = self.app()
        views = []
        error = OSError('injected Tk bitmap upload failure')
        retained = None
        def photo(view):
            views.append(view)
            raise error
        try:
            self.display(app, source, photo)
        except OSError as failure:
            retained = failure
        self.assertIs(retained, error)
        self.assertEqual(len(views), 1)
        self.assertLessEqual(views[0].width, 800)
        self.assertLessEqual(views[0].height, 480)
        for image in (*views, source):
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
