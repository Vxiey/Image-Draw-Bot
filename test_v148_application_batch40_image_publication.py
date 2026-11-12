"""Real image operations retain ownership until their result is accepted."""
from contextlib import ExitStack
from pathlib import Path
import queue
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import BackgroundRemoval
import DrawBot
import ImageUpscale


class _CountdownEvent(threading.Event):
    def wait(self, timeout=None):
        # Screen capture's three-second presentation countdown is not the
        # behavior under test; the real worker and cancellation flag remain.
        return self.is_set()


class ImagePublicationTests(unittest.TestCase):
    def image(self):
        path = Path(__file__).with_name('assets') / 'image-draw-bot-icon.png'
        with Image.open(path) as source:
            result = source.convert('RGBA')
        self.addCleanup(result.close)
        return result

    def app(self):
        app = SimpleNamespace(activity=None, closing=False, pending_clear_drawing=None,
            profile_change_after=None, profile_change_in_progress=False,
            original=self.image(), stop=_CountdownEvent(), events=queue.Queue(),
            root=None, status=Mock(), corners=[(0, 0), (40, 30)],
            preview_after=None, preview_render_after=None, worker=None)
        app.begin_worker = MethodType(DrawBot.DrawBotApp.begin_worker, app)
        app.set_busy = lambda value: setattr(app, 'activity', value)
        app.area = lambda: (0, 0, 40, 30)
        return app

    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def run_operation(self, operation, failure):
        app = self.app()
        borrowed = app.original
        before = borrowed.tobytes()
        results = []
        retained_error = RuntimeError('result publication failed')
        result_kind = {'background': 'background_removed', 'upscale': 'upscaled', 'capture': 'screen'}[operation]
        put = app.events.put

        def queue_result(event):
            if event[0] == result_kind and failure == 'queue':
                raise retained_error
            return put(event)

        def observe_result(result):
            image = result.image if operation == 'background' else result
            results.append(image)
            self.addCleanup(image.close)
            if failure == 'stop':
                app.stop.set()
            if failure == 'closing':
                app.closing = True
            return result

        with ExitStack() as stack:
            stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
            stack.enter_context(patch('DrawBot.log_error'))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch.object(app.events, 'put', new=queue_result))
            if operation == 'background':
                actual = BackgroundRemoval.remove_background
                stack.enter_context(patch.object(BackgroundRemoval, 'remove_background',
                    side_effect=lambda *args, **kwargs: observe_result(actual(*args, **kwargs))))
                self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
            elif operation == 'upscale':
                actual = ImageUpscale.upscale_image
                stack.enter_context(patch.object(ImageUpscale, 'upscale_image',
                    side_effect=lambda *args, **kwargs: observe_result(actual(*args, **kwargs))))
                self.assertTrue(DrawBot.DrawBotApp._start_upscale(app, borrowed, 2, 'Pixel art'))
            else:
                # Native capture is replaced only at the OS boundary with the
                # repository's real Paint reference, never a synthetic motif.
                def capture(_area):
                    with Image.open(Path(__file__).with_name('assets') / 'paint-tools-reference.png') as source:
                        return observe_result(source.convert('RGB'))
                stack.enter_context(patch('DrawBot.grab_area', side_effect=capture))
                DrawBot.DrawBotApp.capture_screen(app)
            worker = app.worker
            self.assertIsInstance(worker, threading.Thread)
            worker.join(timeout=20)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIs(app.original, borrowed)
        self.assertEqual(borrowed.tobytes(), before)
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        for kind, value in events:
            if kind == 'background_removed':
                from BackgroundEdit import BackgroundEditResult
                if isinstance(value, BackgroundEditResult):
                    self.addCleanup(value.release)
        self.assertEqual(events[-1][0], 'done')
        if failure:
            self.assert_closed(results[0])
            self.assertNotIn(result_kind, [kind for kind, _ in events])
            if failure == 'queue':
                self.assertIsNotNone(retained_error.__traceback__)
                self.assertIn('publication failed', next(value[1] for kind, value in events if kind == 'terminal_status'))
        else:
            results[0].getpixel((0, 0))
            self.assertEqual(sum(kind == result_kind for kind, _ in events), 1)

    def test_unpublished_background_upscale_and_capture_results_close_on_queue_failure(self):
        for operation in ('background', 'upscale', 'capture'):
            with self.subTest(operation=operation):
                self.run_operation(operation, 'queue')

    def test_late_stop_and_shutdown_close_unpublished_image_results(self):
        for operation in ('background', 'upscale', 'capture'):
            for failure in ('stop', 'closing'):
                with self.subTest(operation=operation, failure=failure):
                    self.run_operation(operation, failure)

    def test_successful_publication_keeps_result_images_live(self):
        for operation in ('background', 'upscale', 'capture'):
            with self.subTest(operation=operation):
                self.run_operation(operation, None)

    def test_cleanup_failure_does_not_replace_publication_error(self):
        app = self.app()
        result = self.image()
        original = RuntimeError('the actual queue error')
        with patch.object(app.events, 'put', side_effect=original), \
                patch.object(result, 'close', side_effect=OSError('cleanup failed')):
            with self.assertRaises(RuntimeError) as caught:
                DrawBot.DrawBotApp._publish_image_result(app, 'screen', result, result)
        self.assertIs(caught.exception, original)
        self.assertTrue(any('cleanup' in note for note in original.__notes__))

    def test_snapshot_closes_if_feedback_fails_before_worker_start(self):
        for operation in ('remove_image_background', 'save_png_copy'):
            with self.subTest(operation=operation):
                app = self.app()
                copies = []
                copy = app.original.copy
                def capture_copy():
                    result = copy()
                    copies.append(result)
                    self.addCleanup(result.close)
                    return result
                with patch.object(app.original, 'copy', side_effect=capture_copy), \
                        patch.object(app.status, 'set', side_effect=RuntimeError('feedback unavailable')), \
                        patch('DrawBot.filedialog.asksaveasfilename', return_value='unused.png'):
                    with self.assertRaisesRegex(RuntimeError, 'feedback unavailable'):
                        getattr(DrawBot.DrawBotApp, operation)(app)
                self.assertEqual(len(copies), 1)
                self.assert_closed(copies[0])
                self.assertIsNone(app.worker)
                app.original.getpixel((0, 0))

    def test_background_startup_cleanup_preserves_the_primary_exception(self):
        for phase in ('feedback', 'thread-start'):
            with self.subTest(phase=phase):
                app = self.app()
                original = app.original
                before = original.tobytes()
                snapshot = original.copy()
                close = snapshot.close
                self.addCleanup(close)
                failure = RuntimeError('the actual startup failure')

                def close_then_fail():
                    close()
                    raise OSError('snapshot cleanup also failed')

                with ExitStack() as stack:
                    stack.enter_context(patch.object(original, 'copy', return_value=snapshot))
                    closed = stack.enter_context(patch.object(snapshot, 'close', side_effect=close_then_fail))
                    stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
                    stack.enter_context(patch('DrawBot.log_event'))
                    stack.enter_context(patch('DrawBot.log_error'))
                    if phase == 'feedback':
                        stack.enter_context(patch.object(app.status, 'set', side_effect=failure))
                    else:
                        stack.enter_context(patch('DrawBot.threading.Thread.start', side_effect=failure))
                    with self.assertRaises(RuntimeError) as caught:
                        DrawBot.DrawBotApp.remove_image_background(app)
                    closed.assert_called_once_with()
                self.assertIs(caught.exception, failure)
                self.assertTrue(any('cleanup' in note for note in failure.__notes__))
                self.assert_closed(snapshot)
                self.assertIsNone(app.worker)
                self.assertIs(app.original, original)
                self.assertEqual(original.tobytes(), before)

    def test_preview_snapshot_closes_if_feedback_fails_before_worker_start(self):
        import test_v148_ui_batch39_preview_ownership as fixture
        harness = fixture.PreviewAttemptOwnershipTests('runTest')
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        app = harness.app()
        copies = []
        copy = app.original.copy
        def capture_copy():
            result = copy()
            copies.append(result)
            self.addCleanup(result.close)
            return result
        with patch.object(app.original, 'copy', side_effect=capture_copy), \
                patch.object(app.status, 'set', side_effect=RuntimeError('preview feedback unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'preview feedback unavailable'):
                app.update_plan(user_initiated=True)
        self.assertEqual(len(copies), 1)
        self.assert_closed(copies[0])
        self.assertIsNone(app.worker)
        app.original.getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
