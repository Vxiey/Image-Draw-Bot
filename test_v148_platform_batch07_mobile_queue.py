"""Real PIL publication through the bounded, immutable-source mobile API."""
from contextlib import contextmanager
from io import BytesIO
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import MobilePreview as mobile
import MobilePreviewQueue as queue


class MobileQueueTests(unittest.TestCase):
    def server(self):
        server = mobile.MobilePreviewServer()
        server._server = Mock()
        server._token = 'test-session'
        self.addCleanup(server.stop)
        self.addCleanup(lambda: self.assertTrue(server._image_queue.wait_idle(5)))
        return server

    def image(self, color, size=(18, 12), mode='RGB'):
        image = Image.new(mode, size, color)
        self.addCleanup(image.close)
        return image

    def idle(self, server):
        self.assertTrue(server._image_queue.wait_idle(5), 'encoder did not finish')

    def pixel(self, server, name='preview'):
        with Image.open(BytesIO(server._images[name])) as image:
            return image.getpixel((0, 0))

    def assert_closed(self, images):
        for image in images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    @contextmanager
    def blocked_encoder(self):
        entered = threading.Event()
        resume = threading.Event()
        calls = []
        encode = mobile._image_png_bytes

        def blocked(image):
            calls.append((image, threading.get_ident()))
            if len(calls) == 1:
                entered.set()
                if not resume.wait(5):
                    raise TimeoutError('encoder test was not released')
            return encode(image)

        with patch.object(mobile, '_image_png_bytes', side_effect=blocked):
            try:
                yield entered, resume, calls
            finally:
                resume.set()

    def test_encoder_reads_owned_pixels_off_caller_thread_even_after_source_is_closed(self):
        server = self.server()
        source = self.image('red')
        with self.blocked_encoder() as (entered, resume, calls):
            self.assertTrue(server.queue_images(preview=source))
            self.assertTrue(entered.wait(3))
            self.assertIsNot(calls[0][0], source)
            self.assertNotEqual(calls[0][1], threading.get_ident())
            source.paste('blue', (0, 0, *source.size))
            source.close()
            resume.set()
            self.idle(server)
        self.assertEqual(self.pixel(server), (255, 0, 0))
        self.assert_closed([value for value, _ in calls])

    def test_unchanged_identity_skips_copy_and_png_but_sync_api_rereads_mutable_pixels(self):
        server = self.server()
        source = self.image('red')
        server.queue_images(preview=source)
        self.idle(server)
        first_revision = server.state().revision
        with patch.object(Image.Image, 'copy', side_effect=AssertionError('unexpected copy')), \
             patch.object(mobile, '_image_png_bytes', side_effect=AssertionError('unexpected PNG')):
            self.assertFalse(server.queue_images(preview=source))
        source.putpixel((0, 0), (0, 0, 255))
        server.update_images(preview=source)
        self.assertEqual(self.pixel(server), (0, 0, 255))
        self.assertEqual(server.state().revision, first_revision + 1)

    def test_replacing_only_plan_reuses_encoded_original_and_safety(self):
        server = self.server()
        original, first, second, safety = [self.image(color) for color in ('red', 'blue', 'green', 'yellow')]
        encode = mobile._image_png_bytes
        with patch.object(mobile, '_image_png_bytes', wraps=encode) as encoded:
            server.queue_images(original=original, preview=first, safety=safety)
            self.idle(server)
            original_bytes, safety_bytes = server._images['original'], server._images['safety']
            self.assertEqual(encoded.call_count, 3)
            server.queue_images(original=original, preview=second, safety=safety)
            self.idle(server)
            self.assertEqual(encoded.call_count, 4)
        self.assertIs(server._images['original'], original_bytes)
        self.assertIs(server._images['safety'], safety_bytes)
        self.assertEqual(self.pixel(server), (0, 128, 0))

    def test_latest_pending_replaces_old_snapshot_and_duplicate_active_request_is_skipped(self):
        server = self.server()
        sources = [self.image(color) for color in ('red', 'blue', 'green', 'yellow')]
        with self.blocked_encoder() as (entered, resume, calls):
            server.queue_images(preview=sources[0])
            self.assertTrue(entered.wait(3))
            self.assertFalse(server.queue_images(preview=sources[0]))
            replaced = []
            for source in sources[1:]:
                previous = server._image_queue._pending
                if previous is not None:
                    replaced.extend(previous.snapshots.values())
                server.queue_images(preview=source)
            self.assert_closed(replaced)
            self.assertIsNotNone(server._image_queue._active)
            self.assertIsNotNone(server._image_queue._pending)
            self.assertEqual(len(calls), 1)
            resume.set()
            self.idle(server)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.pixel(server), (255, 255, 0))
        self.assertEqual(server.state().revision, 1)

    def test_obsolete_pending_slot_is_closed_before_capturing_replacement(self):
        server = self.server()
        first, second, third = [self.image(color) for color in ('red', 'blue', 'green')]
        copy = Image.Image.copy
        with self.blocked_encoder() as (entered, resume, _):
            server.queue_images(preview=first)
            self.assertTrue(entered.wait(3))
            server.queue_images(preview=second)
            pending = list(server._image_queue._pending.snapshots.values())

            def checked_copy(image):
                if image is third:
                    self.assert_closed(pending)
                    self.assertIsNone(server._image_queue._pending)
                return copy(image)

            with patch.object(Image.Image, 'copy', checked_copy):
                server.queue_images(preview=third)
            resume.set()
            self.idle(server)
        self.assertEqual(self.pixel(server), (0, 128, 0))

    def test_new_submission_invalidates_active_publish_before_its_snapshot_finishes(self):
        server = self.server()
        first, second = self.image('red'), self.image('blue')
        copying, finish_copy = threading.Event(), threading.Event()
        copy = Image.Image.copy
        failures = []

        def slow_copy(image):
            if image is second:
                copying.set()
                if not finish_copy.wait(5):
                    raise TimeoutError('snapshot test was not released')
            return copy(image)

        def submit():
            try:
                server.queue_images(preview=second)
            except BaseException as error:
                failures.append(error)

        with self.blocked_encoder() as (entered, resume, _), patch.object(Image.Image, 'copy', slow_copy):
            server.queue_images(preview=first)
            self.assertTrue(entered.wait(3))
            submitter = threading.Thread(target=submit)
            submitter.start()
            try:
                self.assertTrue(copying.wait(3))
                resume.set()
                self.idle(server)
                self.assertEqual(server.state().revision, 0)
                self.assertIsNone(server._images['preview'])
            finally:
                finish_copy.set()
                submitter.join(5)
            self.assertFalse(submitter.is_alive())
            self.assertFalse(failures)
            self.idle(server)
        self.assertEqual(self.pixel(server), (0, 0, 255))

    def test_clear_all_views_publishes_immediately_and_cannot_be_undone_by_old_encoder(self):
        server = self.server()
        old, incoming = self.image('red'), self.image('blue')
        server.queue_images(original=old, preview=old)
        self.idle(server)
        with self.blocked_encoder() as (entered, resume, _):
            server.queue_images(preview=incoming)
            self.assertTrue(entered.wait(3))
            self.assertTrue(server.queue_images())
            self.assertEqual(server._images, dict.fromkeys(queue.VIEW_NAMES))
            cleared = server.state().revision
            resume.set()
            self.idle(server)
        self.assertEqual(server._images, dict.fromkeys(queue.VIEW_NAMES))
        self.assertEqual(server.state().revision, cleared)

    def test_cancel_preserves_last_frame_and_allows_retry_with_identical_source(self):
        server = self.server()
        previous, incoming = self.image('red'), self.image('blue')
        server.queue_images(preview=previous)
        self.idle(server)
        with self.blocked_encoder() as (entered, resume, _):
            server.queue_images(preview=incoming)
            self.assertTrue(entered.wait(3))
            server.cancel_updates()
            resume.set()
            self.idle(server)
        self.assertEqual(self.pixel(server), (255, 0, 0))
        self.assertTrue(server.queue_images(preview=incoming))
        self.idle(server)
        self.assertEqual(self.pixel(server), (0, 0, 255))

    def test_stop_during_capture_does_not_wait_for_copy_or_leak_owned_snapshot(self):
        server = self.server()
        source = self.image('red')
        copy = Image.Image.copy
        owned = []

        def stop_in_copy(image):
            snapshot = copy(image)
            owned.append(snapshot)
            server.stop()
            return snapshot

        with patch.object(Image.Image, 'copy', stop_in_copy), \
             patch.object(mobile, '_image_png_bytes') as encode:
            self.assertFalse(server.queue_images(preview=source))
        encode.assert_not_called()
        self.assert_closed(owned)
        self.assertEqual(server.state().revision, 0)
        self.assertFalse(server.running)

    def test_same_server_restart_uses_one_encoder_and_rejects_previous_session_frame(self):
        server = mobile.MobilePreviewServer()
        self.addCleanup(server.stop)
        first, second = self.image('red'), self.image('blue')
        with patch.object(mobile, 'local_ipv4_addresses', return_value=['127.0.0.1']):
            first_session = server.start()
            with self.blocked_encoder() as (entered, resume, calls):
                server.queue_images(preview=first)
                self.assertTrue(entered.wait(3))
                worker = server._image_queue._thread
                server.stop()
                second_session = server.start()
                self.assertNotEqual(second_session.token, first_session.token)
                self.assertTrue(server.queue_images(preview=second))
                self.assertIs(server._image_queue._thread, worker)
                self.assertEqual(server._images, dict.fromkeys(queue.VIEW_NAMES))
                resume.set()
                self.idle(server)
        self.assertEqual(len({identity for _, identity in calls}), 1)
        self.assertEqual(self.pixel(server), (0, 0, 255))
        self.assertEqual(server.state().revision, 1)

    def test_capture_failure_preserves_last_frame_closes_partial_and_retries(self):
        server = self.server()
        old, original, preview = [self.image(color) for color in ('red', 'blue', 'green')]
        server.queue_images(preview=old)
        self.idle(server)
        copy = Image.Image.copy
        owned = []

        def fail_preview(image):
            if image is preview:
                raise OSError('capture unavailable')
            snapshot = copy(image)
            owned.append(snapshot)
            return snapshot

        with patch.object(Image.Image, 'copy', fail_preview):
            with self.assertRaisesRegex(OSError, 'capture unavailable'):
                server.queue_images(original=original, preview=preview)
        self.assert_closed(owned)
        self.assertEqual(self.pixel(server), (255, 0, 0))
        self.assertTrue(server.queue_images(original=original, preview=preview))
        self.idle(server)
        self.assertEqual(self.pixel(server), (0, 128, 0))

    def test_thread_construction_and_start_failures_release_snapshots_and_allow_retry(self):
        for stage in ('constructor', 'start'):
            with self.subTest(stage=stage):
                server = self.server()
                source = self.image('red')
                copy = Image.Image.copy
                owned = []

                def capture(image):
                    snapshot = copy(image)
                    owned.append(snapshot)
                    return snapshot

                target = 'MobilePreviewQueue.threading.Thread' + ('.start' if stage == 'start' else '')
                with patch(target, side_effect=RuntimeError('thread unavailable')), \
                     patch.object(Image.Image, 'copy', capture):
                    with self.assertRaisesRegex(RuntimeError, 'thread unavailable'):
                        server.queue_images(preview=source)
                self.assert_closed(owned)
                self.assertIsNone(server._image_queue._thread)
                self.assertIsNone(server._image_queue._pending)
                self.assertTrue(server.queue_images(preview=source))
                self.idle(server)
                self.assertEqual(self.pixel(server), (255, 0, 0))

    def test_async_failure_is_private_closes_snapshots_and_same_input_can_retry(self):
        server = self.server()
        source = self.image('red')
        captured = []
        failures = []

        def failed(image):
            captured.append(image)
            try:
                raise OSError(r'C:\Users\PrivatePerson\secret.png password=sample-private')
            except OSError as error:
                failures.append(error)  # Retain traceback to verify explicit closure.
                raise

        with patch.object(mobile, '_image_png_bytes', side_effect=failed), \
             patch('CrashDiagnostics.log_event') as log:
            self.assertTrue(server.queue_images(preview=source))
            self.idle(server)
        self.assert_closed(captured)
        self.assertEqual(log.call_args.args, ('Mobile Preview background encoding failed: OSError.',))
        self.assertIsNone(server._images['preview'])
        self.assertTrue(server.queue_images(preview=source))
        self.idle(server)
        self.assertEqual(self.pixel(server), (255, 0, 0))

    def test_sync_update_supersedes_old_queue_work_without_late_overwrite(self):
        server = self.server()
        first, latest = self.image('red'), self.image('blue')
        with self.blocked_encoder() as (entered, resume, _):
            server.queue_images(preview=first)
            self.assertTrue(entered.wait(3))
            server.update_images(preview=latest)
            revision = server.state().revision
            resume.set()
            self.idle(server)
        self.assertEqual(self.pixel(server), (0, 0, 255))
        self.assertEqual(server.state().revision, revision)


if __name__ == '__main__':
    unittest.main()
