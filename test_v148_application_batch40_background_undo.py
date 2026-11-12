"""Remove BG reuses its detached input snapshot as exact Undo state."""
from pathlib import Path
import queue
import threading
from types import MethodType
import unittest
from unittest.mock import patch

from PIL import Image

from BackgroundEdit import BackgroundEditResult
import DrawBot
import test_v148_ui_batch16_plan_status as fixture


class _AssetFixture(fixture.PlanStatusFixture):
    def image(self, _color):
        with Image.open(Path(__file__).with_name('golden-regression') / 'red-bananas-texture.png') as source:
            image = source.convert('RGBA')
        self.images.append(image)
        return image


class BackgroundUndoTransferTests(unittest.TestCase):
    def setUp(self):
        self.fixture = _AssetFixture('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.fixture.stack.enter_context(patch('DrawBot.log_error'))

    def app(self):
        app = self.fixture.app()
        app.events = queue.Queue()
        app.begin_worker = MethodType(DrawBot.DrawBotApp.begin_worker, app)
        return app

    def prepare(self, app):
        original = app.original
        snapshots = []
        copy = original.copy
        def capture_copy():
            image = copy()
            snapshots.append(image)
            self.fixture.images.append(image)
            return image
        with patch.object(original, 'copy', side_effect=capture_copy):
            self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
            worker = app.worker
            self.assertIsInstance(worker, threading.Thread)
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive())
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        self.assertEqual([kind for kind, _value in events], ['background_removed', 'done'])
        result = events[0][1]
        self.assertIsInstance(result, BackgroundEditResult)
        self.fixture.images.append(result.image)
        self.assertEqual(len(snapshots), 1)
        return original, snapshots[0], result, events

    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def deliver(self, app, events):
        for kind, payload in events:
            DrawBot.DrawBotApp._handle_event(app, kind, payload)

    def test_real_worker_transfers_its_exact_snapshot_without_a_second_ui_copy(self):
        app = self.app()
        before = app.original.tobytes(), dict(app.original.info)
        original, snapshot, result, events = self.prepare(app)
        self.assertFalse(result.metadata.get('no_op_reason'))
        self.assertIs(result.source, original)
        self.assertIs(result.undo_image, snapshot)
        self.assertIsNot(snapshot, original)
        self.assertEqual((snapshot.tobytes(), snapshot.info), before)
        with patch.object(original, 'copy', side_effect=AssertionError('Undo duplicated its source on Tk')):
            self.deliver(app, events)
        self.assertIs(app.original, result.image)
        self.assertIs(app.background_removal_original, snapshot)
        self.assertIsNone(app.activity)
        self.assertTrue(DrawBot.DrawBotApp.undo_background_removal(app))
        self.assertIs(app.original, snapshot)
        self.assertEqual((app.original.tobytes(), app.original.info), before)
        self.assertEqual((original.tobytes(), original.info), before)

    def test_stop_or_source_replacement_retires_both_unadopted_buffers(self):
        for failure in ('stop', 'source'):
            with self.subTest(failure=failure):
                app = self.app()
                original, snapshot, result, events = self.prepare(app)
                before = original.tobytes()
                if failure == 'stop':
                    app.stop.set()
                else:
                    app.original = self.fixture.image('replacement')
                current = app.original
                self.deliver(app, events)
                self.assertIs(app.original, current)
                self.assertIsNone(app.background_removal_original)
                self.assert_closed(snapshot)
                self.assert_closed(result.image)
                self.assertEqual(original.tobytes(), before)

    def test_second_edit_keeps_the_original_undo_and_releases_its_private_copy(self):
        app = self.app()
        original, snapshot, _first, first_events = self.prepare(app)
        self.deliver(app, first_events)
        self.assertIs(app.background_removal_original, snapshot)
        previous, second_snapshot, result, second_events = self.prepare(app)
        self.assertIsNone(result.undo_image)
        self.assert_closed(second_snapshot)
        self.deliver(app, second_events)
        self.assertIs(app.background_removal_original, snapshot)
        self.assertTrue(DrawBot.DrawBotApp.undo_background_removal(app))
        self.assertEqual(app.original.tobytes(), original.tobytes())
        previous.getpixel((0, 0))

    def test_publication_failure_closes_result_and_undo_snapshot_before_reporting_error(self):
        app = self.app()
        original = app.original
        copies = []
        copy = original.copy
        def capture_copy():
            result = copy()
            copies.append(result)
            self.fixture.images.append(result)
            return result
        events = []
        error = RuntimeError('cannot publish background image')
        def put(event):
            if event[0] == 'background_removed':
                events.append(event)
                raise error
            events.append(event)
        with patch.object(original, 'copy', side_effect=capture_copy), \
                patch.object(app.events, 'put', side_effect=put):
            self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
            app.worker.join(timeout=10)
            self.assertFalse(app.worker.is_alive())
        self.assertEqual(len(copies), 1)
        self.assert_closed(copies[0])
        result = events[0][1]
        self.assertIs(result.undo_image, copies[0])
        self.assert_closed(result.image)
        self.assertIsNone(app.background_removal_original)
        self.assertIs(app.original, original)
        original.getpixel((0, 0))
        self.assertIsNotNone(error.__traceback__)
        self.assertEqual([kind for kind, _ in events], ['background_removed', 'terminal_status', 'done'])


if __name__ == '__main__':
    unittest.main()
