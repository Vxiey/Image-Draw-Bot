"""Existing modal/profile safety contracts also cover capture/record tools."""
from types import SimpleNamespace
from contextlib import closing
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp


class CaptureEntryStateTests(unittest.TestCase):
    def app(self):
        app = SimpleNamespace(activity=None, closing=False, _active_profile_name='Paint',
            corners=[(0, 0), (100, 80)], status=Mock(), begin_worker=Mock(return_value=True))
        app.area = lambda: (*app.corners[0], *app.corners[1])
        return app

    def test_busy_closing_clear_and_profile_transition_never_open_record_dialog_or_capture(self):
        for method in ('record_screen', 'capture_screen'):
            for field, value in (('activity', 'draw'), ('closing', True),
                    ('pending_clear_drawing', False), ('profile_change_after', 1),
                    ('profile_change_in_progress', True)):
                with self.subTest(method=method, field=field):
                    app = self.app(); setattr(app, field, value)
                    with patch('DrawBot.filedialog.asksaveasfilename') as dialog:
                        self.assertFalse(getattr(DrawBotApp, method)(app))
                    dialog.assert_not_called()
                    app.begin_worker.assert_not_called()
                    app.status.set.assert_not_called()

    def test_record_dialog_rechecks_context_before_scheduling_capture(self):
        changes = (
            lambda app: setattr(app, 'activity', 'load'),
            lambda app: setattr(app, 'closing', True),
            lambda app: setattr(app, 'profile_change_after', 1),
            lambda app: setattr(app, '_active_profile_name', 'Gartic'),
            lambda app: setattr(app, 'corners', []),
            lambda app: app.corners.__setitem__(1, (120, 90)),
        )
        for change in changes:
            app = self.app()
            def answer(**kwargs):
                change(app)
                return 'unused-recording.gif'
            with self.subTest(change=change), patch('DrawBot.filedialog.asksaveasfilename', side_effect=answer):
                self.assertFalse(DrawBotApp.record_screen(app))
            app.begin_worker.assert_not_called()

    def test_stable_recording_schedules_once_and_propagates_worker_rejection(self):
        for accepted in (False, True):
            app = self.app(); app.begin_worker.return_value = accepted
            with patch('DrawBot.filedialog.asksaveasfilename', return_value='unused-recording.gif'):
                self.assertEqual(DrawBotApp.record_screen(app), accepted)
            app.begin_worker.assert_called_once()
            self.assertEqual(app.begin_worker.call_args.args[0], 'record')
            self.assertTrue(callable(app.begin_worker.call_args.args[1]))


class CaptureExportOwnershipTests(unittest.TestCase):
    def app(self):
        jobs = []
        app = SimpleNamespace(activity=None, closing=False, status=Mock(), root=object(),
            stop=threading.Event(), events=queue.Queue(), jobs=jobs)
        def begin(activity, work, *, reset_stop=True, cleanup=None):
            self.assertIs(reset_stop, False)
            jobs.append(work)
            return True
        app.begin_worker = Mock(side_effect=begin)
        return app

    def test_png_encoding_waits_for_worker_and_owns_snapshot_after_capture_closes(self):
        app = self.app()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'capture.png'
            image = Image.new('RGB', (30, 20), 'red')
            with patch('DrawBot.filedialog.asksaveasfilename', return_value=str(path)):
                self.assertTrue(DrawBotApp._save_captured_png(app, image))
            self.assertFalse(path.exists())
            image.putpixel((0, 0), (0, 0, 255)); image.close()
            app.jobs[0]()
            with closing(Image.open(path)) as saved:
                self.assertEqual(saved.format, 'PNG')
                self.assertEqual(saved.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(app.events.get_nowait(), ('png_saved', str(path)))

    def test_cancel_or_partial_encoder_failure_preserves_existing_file_and_closes_snapshot(self):
        for failure in ('stop', 'encoder'):
            app = self.app()
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder, \
                    closing(Image.new('RGB', (30, 20), 'red')) as image:
                path = Path(folder) / 'capture.png'; path.write_bytes(b'previous complete file')
                copied = []
                copy = Image.Image.copy
                def snapshot(source):
                    result = copy(source); copied.append(result); return result
                with patch('DrawBot.filedialog.asksaveasfilename', return_value=str(path)), \
                        patch.object(Image.Image, 'copy', new=snapshot):
                    self.assertTrue(DrawBotApp._save_captured_png(app, image))
                if failure == 'stop':
                    app.stop.set()
                    with self.assertRaises(InterruptedError): app.jobs[0]()
                else:
                    def fail(_source, stream, **kwargs):
                        stream.write(b'incomplete PNG')
                        raise OSError('controlled encoder failure')
                    with patch.object(Image.Image, 'save', new=fail):
                        with self.assertRaisesRegex(OSError, 'encoder failure'): app.jobs[0]()
                self.assertEqual(path.read_bytes(), b'previous complete file')
                self.assertEqual(list(Path(folder).iterdir()), [path])
                self.assertTrue(app.events.empty())
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
                with self.assertRaises(ValueError): copied[0].getpixel((0, 0))

    def test_modal_change_or_closed_capture_never_starts_export(self):
        for state in ('closing', 'busy', 'pending', 'closed-image'):
            app = self.app()
            with self.subTest(state=state), closing(Image.new('RGB', (30, 20), 'red')) as image:
                def answer(**kwargs):
                    if state == 'closing': app.closing = True
                    elif state == 'busy': app.activity = 'draw'
                    elif state == 'pending': app.profile_change_after = 1
                    else: image.close()
                    return 'unused.png'
                with patch('DrawBot.filedialog.asksaveasfilename', side_effect=answer):
                    self.assertFalse(DrawBotApp._save_captured_png(app, image))
                app.begin_worker.assert_not_called()

    def test_capture_window_owns_original_and_releases_its_thumbnail(self):
        app = self.app()
        callbacks = {}
        window = Mock()
        window.bind.side_effect = lambda event, callback, **kwargs: callbacks.__setitem__(event, callback)
        window.destroy.side_effect = lambda: callbacks['<Destroy>'](SimpleNamespace(widget=window))
        thumbnails = []
        image = Image.new('RGB', (1600, 960), 'red')
        def photo(view):
            thumbnails.append(view)
            self.assertEqual(view.size, (800, 480))
            return object()
        with patch('DrawBot.tk.Toplevel', return_value=window), \
                patch('DrawBot.ttk.Label'), patch('DrawBot.ttk.Button'), \
                patch('PIL.ImageTk.PhotoImage', side_effect=photo):
            DrawBotApp.display_screen(app, image)
        with self.assertRaises(ValueError): thumbnails[0].getpixel((0, 0))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        callbacks['<Destroy>'](SimpleNamespace(widget=object()))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        window.destroy()
        with self.assertRaises(ValueError): image.getpixel((0, 0))

    def test_capture_upload_failure_or_shutdown_closes_worker_owned_image(self):
        for closing_app in (False, True):
            app = self.app(); app.closing = closing_app
            image = Image.new('RGB', (30, 20), 'red')
            with self.subTest(closing=closing_app), patch('DrawBot.tk.Toplevel') as top, \
                    patch('PIL.ImageTk.PhotoImage', side_effect=OSError('controlled upload failure')):
                if closing_app:
                    self.assertFalse(DrawBotApp.display_screen(app, image))
                    top.assert_not_called()
                else:
                    with self.assertRaisesRegex(OSError, 'upload failure'):
                        DrawBotApp.display_screen(app, image)
                    top.return_value.destroy.assert_called_once()
            with self.assertRaises(ValueError): image.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
