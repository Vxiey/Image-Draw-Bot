"""Existing image ownership also covers an accepted worker stopped before task."""
from contextlib import ExitStack, closing
from pathlib import Path
import queue
import tempfile
from types import MethodType
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from DrawBot import DrawBotApp
from test_v148_application_batch04_settings import Value
from test_v148_application_batch14_browser_start import DeferredThread, NoWaitEvent, ScheduledRoot
from test_v148_ui_lifecycle_batch02 import ui_app


OPERATIONS = ('remove_image_background', 'save_png_copy', '_save_captured_png', 'export_preview')


class ImageWorkerCleanupTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('DrawBot.log_event', 'DrawBot.log_error', 'ScreenTaskWindow.ScreenTaskWindow'):
            self.stack.enter_context(patch(target))
        self.stack.enter_context(patch('DrawBot.threading.Thread', DeferredThread))
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))

    def fixture(self, operation):
        app = ui_app()
        app.original.close()
        app.original = Image.new('RGBA', (64, 48), 'white')
        ImageDraw.Draw(app.original).rectangle((20, 12, 43, 35), fill=(220, 30, 50, 255))
        self.addCleanup(app.original.close)
        preview = Image.new('RGB', (5, 4), (12, 23, 34))
        self.addCleanup(preview.close)
        app.plan = {'preview': preview}
        app.preview_tabs = Value('Simulated final')
        app.background_removal_original = None
        app.background_removal_meta = None
        app.events = queue.Queue()
        app.root = ScheduledRoot()
        app.stop = NoWaitEvent()
        app.worker = None
        app.begin_worker = MethodType(DrawBotApp.begin_worker, app)
        app.set_busy = lambda value: setattr(app, 'activity', value)
        captured = Image.new('RGB', (4, 3), (56, 67, 78))
        self.addCleanup(captured.close)
        source = captured if operation == '_save_captured_png' else (
            preview if operation == 'export_preview' else app.original)
        destination = self.folder / (operation + '.png')
        return app, source, captured, destination

    def enqueue(self, app, operation, source, captured, destination):
        copies = []
        real_copy = source.copy
        def copy():
            image = real_copy()
            copies.append(image)
            self.addCleanup(image.close)
            return image
        with patch.object(source, 'copy', side_effect=copy), \
                patch('DrawBot.filedialog.asksaveasfilename', return_value=str(destination)):
            method = getattr(DrawBotApp, operation)
            accepted = method(app, captured) if operation == '_save_captured_png' else method(app)
        self.assertTrue(accepted)
        self.assertEqual(len(copies), 1)
        self.assertIsNot(copies[0], source)
        self.assertEqual(copies[0].tobytes(), source.tobytes())
        self.assertTrue(app.worker.is_alive())
        return copies[0]

    def assert_closed(self, image):
        with self.assertRaises(ValueError): image.getpixel((0, 0))

    @staticmethod
    def events(app):
        result = []
        while not app.events.empty(): result.append(app.events.get_nowait())
        return result

    def test_all_four_actual_workers_release_their_copy_when_stop_skips_the_task(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                app, source, captured, destination = self.fixture(operation)
                destination.write_bytes(b'previous complete file')
                existing_files = set(self.folder.iterdir())
                original, plan = app.original, app.plan
                before = [image.tobytes() for image in (source, original, plan['preview'], captured)]
                snapshot = self.enqueue(app, operation, source, captured, destination)
                with patch('BackgroundRemoval.remove_background') as remove, \
                        patch.object(Image.Image, 'save') as encode:
                    app.stop.set()
                    app.worker.run()
                remove.assert_not_called(); encode.assert_not_called()
                self.assert_closed(snapshot)
                self.assertEqual([image.tobytes() for image in (source, original, plan['preview'], captured)], before)
                self.assertIs(app.original, original)
                self.assertIs(app.plan, plan)
                self.assertIsNone(app.background_removal_original)
                self.assertEqual(destination.read_bytes(), b'previous complete file')
                self.assertEqual(set(self.folder.iterdir()), existing_files)
                delivered = self.events(app)
                self.assertEqual([kind for kind, _ in delivered], ['status', 'done'])
                expected = {'remove_image_background': 'background-remove',
                            'export_preview': 'preview-export'}.get(operation, 'png-export')
                self.assertEqual(delivered[-1], ('done', expected))

    def test_actual_export_workers_keep_complete_files_and_borrowed_sources_after_cleanup(self):
        for operation in OPERATIONS[1:]:
            with self.subTest(operation=operation):
                app, source, captured, destination = self.fixture(operation)
                snapshot = self.enqueue(app, operation, source, captured, destination)
                expected = snapshot.tobytes()
                source.putpixel((0, 0), (1, 2, 3, 255) if source.mode == 'RGBA' else (1, 2, 3))
                app.worker.run()
                self.assert_closed(snapshot)
                with closing(Image.open(destination)) as saved:
                    self.assertEqual(saved.tobytes(), expected)
                self.assertEqual(source.getpixel((0, 0))[:3], (1, 2, 3))
                delivered = self.events(app)
                self.assertEqual(delivered[-1][0], 'done')
                self.assertEqual(delivered[0][0], 'status' if operation == 'export_preview' else 'png_saved')
                self.assertEqual(len(delivered), 2)

    def test_background_result_remains_live_through_actual_ui_adoption_after_cleanup(self):
        operation = 'remove_image_background'
        app, source, captured, destination = self.fixture(operation)
        before = source.tobytes()
        snapshot = self.enqueue(app, operation, source, captured, destination)
        app.worker.run()
        self.assert_closed(snapshot)
        delivered = self.events(app)
        self.assertEqual([kind for kind, _ in delivered], ['background_removed', 'done'])
        result = delivered[0][1]
        self.addCleanup(result.image.close)
        self.assertFalse(result.metadata.get('no_op_reason'))
        self.assertIs(app.original, source)
        self.assertEqual(result.image.getpixel((0, 0))[3], 0)
        self.assertEqual(result.image.getpixel((30, 20)), (220, 30, 50, 255))
        with patch.object(DrawBotApp, '_clear_render_resume'):
            DrawBotApp._handle_event(app, *delivered[0])
        self.addCleanup(app.background_removal_original.close)
        self.assertIs(app.original, result.image)
        self.assertEqual(app.background_removal_original.tobytes(), before)
        self.assertEqual(source.tobytes(), before)
        self.assertEqual(app.original.getpixel((30, 20)), (220, 30, 50, 255))


if __name__ == '__main__':
    unittest.main()
