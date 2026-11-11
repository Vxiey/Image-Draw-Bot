"""Preserve the real PNG failure when an owned RGBA conversion also fails to close.

All pixel data comes from the existing paint-tools-reference.png asset. Encoding,
disk I/O, cancellation checks and the worker are production implementations;
fault injection only observes PNG writes and fails an owned conversion's close.
"""
from contextlib import contextmanager, ExitStack
import errno
import hashlib
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import RecoveryImagePreparation as preparation
import SessionRecovery as recovery


ASSET = Path(__file__).resolve().parent / 'assets' / 'paint-tools-reference.png'


class RecoveryConversionCleanupTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(recovery, 'RECOVERY_DIR', self.directory))

    def source(self, mode='RGB'):
        with Image.open(ASSET) as existing:
            image = existing.copy() if existing.mode == mode else existing.convert(mode)
        self.addCleanup(image.close)
        return image

    @staticmethod
    def pixels(image):
        return image.mode, image.size, image.tobytes()

    @contextmanager
    def conversions(self, close_failure=None):
        owned = []
        original_convert = Image.Image.convert

        def convert(image, *args, **kwargs):
            converted = original_convert(image, *args, **kwargs)
            native_close = converted.close
            record = {'image': converted, 'close_calls': 0}
            owned.append(record)
            # Last-resort fixture cleanup runs after the ownership assertions,
            # so it cannot make a missing production close pass unnoticed.
            self.addCleanup(native_close)

            def close():
                record['close_calls'] += 1
                native_close()
                if close_failure is not None:
                    raise close_failure

            converted.close = close
            return converted

        with patch.object(Image.Image, 'convert', convert):
            yield owned

    @contextmanager
    def png_writes(self, *, after_write=None, write_failure=None):
        observed = {'successful_writes': 0, 'written_bytes': 0, 'errors': []}
        original_write = preparation._CancellableWriter.write

        def write(writer, value):
            try:
                written = original_write(writer, value)
                observed['successful_writes'] += 1
                observed['written_bytes'] += written
                if write_failure is not None:
                    raise write_failure
                if after_write is not None:
                    after_write(observed['successful_writes'])
                return written
            except BaseException as failure:
                observed['errors'].append(failure)
                raise

        with patch.object(preparation._CancellableWriter, 'write', write):
            yield observed

    def failure_from(self, operation):
        # unittest.assertRaises clears the traceback; retain it here to prove
        # cleanup happens while the original native/encoder frames stay alive.
        try:
            result = operation()
        except BaseException as failure:
            return failure
        if result is not None:
            result.close()
        self.fail('Failed recovery preparation returned a successful result.')

    def assert_owned_cleanup(self, owned, source, original):
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]['close_calls'], 1)
        with self.assertRaises(ValueError):
            owned[0]['image'].getpixel((0, 0))
        self.assertEqual(self.pixels(source), original)
        self.assertEqual(list(self.directory.iterdir()), [])

    def assert_primary(self, failure, observed, expected_type):
        self.assertEqual(len(observed['errors']), 1)
        primary = observed['errors'][0]
        self.assertIsInstance(primary, expected_type)
        self.assertIsNotNone(primary.__traceback__)
        self.assertIs(failure, primary)
        self.assertIsNotNone(failure.__traceback__)
        self.assertTrue(any('OSError' in note for note in failure.__notes__))

    def assert_prepared(self, source, prepared):
        self.addCleanup(prepared.close)
        self.assertTrue(prepared.path.is_file())
        self.assertEqual(prepared.path.parent, Path(prepared.directory.name))
        self.assertEqual(prepared.digest, hashlib.sha256(prepared.path.read_bytes()).hexdigest())
        expected = source.convert('RGBA')
        decoded = None
        try:
            decoded = Image.open(prepared.path)
            self.assertEqual(self.pixels(decoded), self.pixels(expected))
        finally:
            if decoded is not None:
                decoded.close()
            expected.close()
        path = prepared.path
        prepared.close()
        self.assertFalse(path.exists())
        self.assertFalse(Path(prepared.directory.name).exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_stop_during_real_png_write_preserves_interruption_over_close_failure(self):
        source = self.source()
        original = self.pixels(source)
        stopped = threading.Event()
        cleanup = OSError('converted close failed after releasing its core')
        with self.conversions(cleanup) as owned, self.png_writes(
                after_write=lambda count: stopped.set() if count == 1 else None) as observed:
            failure = self.failure_from(lambda: preparation.prepare_image(source, cancelled=stopped.is_set))
        self.assertTrue(stopped.is_set())
        self.assertEqual(observed['successful_writes'], 1)
        self.assertGreater(observed['written_bytes'], 0)
        self.assert_owned_cleanup(owned, source, original)
        self.assert_primary(failure, observed, InterruptedError)

    def test_real_png_write_failure_keeps_original_error_and_allows_a_clean_retry(self):
        source = self.source()
        original = self.pixels(source)
        primary = OSError(errno.ENOSPC, 'PNG write failed after a real disk write')
        with self.conversions(OSError('converted cleanup failed')) as owned, self.png_writes(
                write_failure=primary) as observed:
            failure = self.failure_from(lambda: preparation.prepare_image(source))
        self.assertEqual(observed['successful_writes'], 1)
        self.assertGreater(observed['written_bytes'], 0)
        self.assert_owned_cleanup(owned, source, original)
        self.assert_primary(failure, observed, OSError)
        self.assertIs(failure, primary)
        self.assertEqual(failure.errno, errno.ENOSPC)
        self.assert_prepared(source, preparation.prepare_image(source))
        self.assertEqual(self.pixels(source), original)

    def test_actual_png_byte_limit_keeps_validation_error_over_close_failure(self):
        source = self.source()
        original = self.pixels(source)
        # PNG's eight-byte signature really reaches disk; the next actual
        # writer call exercises the existing size guard rather than a stub.
        with patch.object(recovery, 'MAX_CACHED_IMAGE_BYTES', 8), self.conversions(
                OSError('converted cleanup failed')) as owned, self.png_writes() as observed:
            failure = self.failure_from(lambda: preparation.prepare_image(source))
        self.assertEqual(observed['successful_writes'], 1)
        self.assertEqual(observed['written_bytes'], 8)
        self.assert_owned_cleanup(owned, source, original)
        self.assert_primary(failure, observed, ValueError)
        self.assertEqual(str(failure), 'Cached image is too large.')

    def test_standalone_close_failure_is_reported_and_discards_the_encoded_png(self):
        source = self.source()
        original = self.pixels(source)
        cleanup = OSError('close alone failed after successful PNG encoding')
        with self.conversions(cleanup) as owned, self.png_writes() as observed:
            failure = self.failure_from(lambda: preparation.prepare_image(source))
        self.assertIs(failure, cleanup)
        self.assertIsNotNone(failure.__traceback__)
        self.assertEqual(observed['errors'], [])
        self.assertGreater(observed['written_bytes'], 8)
        self.assert_owned_cleanup(owned, source, original)

    def test_real_worker_cancel_notifies_once_and_preserves_interruption_and_snapshot_ownership(self):
        source = self.source()
        original = self.pixels(source)
        delivered = queue.Queue()
        job = preparation.RecoveryImageJob(source, delivered.put)
        snapshot = job._snapshot
        self.addCleanup(snapshot.close)
        entered, release = threading.Event(), threading.Event()

        def pause_after_first_write(count):
            if count == 1:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('The test did not release the real recovery encoder.')

        with self.conversions(OSError('worker conversion cleanup failed')) as owned, self.png_writes(
                after_write=pause_after_first_write) as observed:
            job.start()
            try:
                self.assertTrue(entered.wait(5), 'The real PNG writer did not reach disk.')
                self.assertTrue(job.is_alive())
                job.cancel()
            finally:
                release.set()
                job._thread.join(5)
            self.assertFalse(job._thread.is_alive(), 'The recovery encoder did not finish.')
            self.assertTrue(job.wait_idle(0))
            result, failure = job.take()
        self.assertIsNone(result)
        self.assertIs(delivered.get(timeout=1), job)
        self.assertTrue(delivered.empty())
        self.assertEqual(job.take(), (None, None))
        self.assertIsNone(job._snapshot)
        self.assertTrue(job._cancelled.is_set())
        with self.assertRaises(ValueError):
            snapshot.getpixel((0, 0))
        self.assert_owned_cleanup(owned, source, original)
        self.assert_primary(failure, observed, InterruptedError)

    def test_successful_rgb_conversion_preserves_pixels_digest_and_result_ownership(self):
        source = self.source('RGB')
        original = self.pixels(source)
        with self.conversions() as owned:
            prepared = preparation.prepare_image(source)
        self.addCleanup(prepared.close)
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]['close_calls'], 1)
        with self.assertRaises(ValueError):
            owned[0]['image'].getpixel((0, 0))
        self.assert_prepared(source, prepared)
        self.assertEqual(self.pixels(source), original)

    def test_successful_rgba_input_is_borrowed_without_conversion_or_premature_close(self):
        source = self.source('RGBA')
        original = self.pixels(source)
        with self.conversions() as owned:
            prepared = preparation.prepare_image(source)
        self.addCleanup(prepared.close)
        self.assertEqual(owned, [])
        self.assert_prepared(source, prepared)
        self.assertEqual(self.pixels(source), original)


if __name__ == '__main__':
    unittest.main()
