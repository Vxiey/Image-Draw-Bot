"""Keep the primary failure and previous checkpoint through synchronous cleanup.

Every raster comes from an existing repository PNG. These tests use the public
save_snapshot API, real Pillow encoding, real staging files and real readers.
Fault injection runs after actual I/O or native close; InterruptedError here is
an injected exception object, not a claim of cooperative cancellation support.
"""
from contextlib import contextmanager, ExitStack
import errno
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import RenderResume
import SessionRecovery as recovery


ASSET = Path(__file__).resolve().parent / 'assets' / 'paint-tools-reference.png'
PREVIOUS_ASSET = ASSET.with_name('image-draw-bot-icon.png')


class SynchronousRecoveryCleanupTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name, filename in (
                ('RECOVERY_DIR', ''), ('STATE_FILE', 'session-recovery.json'),
                ('IMAGE_FILE', 'last-image.png'), ('RENDER_FILE', 'render-resume.json')):
            self.stack.enter_context(patch.object(recovery, name, self.directory / filename))
        self.previous_source = self.source(asset=PREVIOUS_ASSET)
        recovery.save_snapshot(profile='Before', options={'quality': 'High detail'},
                               image=self.previous_source, saved_area=[(10, 20), (110, 120)])
        recovery.save_render_progress(RenderResume.new_progress({'image': self.previous_source}))
        self.progress = recovery.load_render_progress()
        self.assertIsNotNone(self.progress)
        self.remember_checkpoint()

    def source(self, mode='RGBA', *, asset=ASSET):
        with Image.open(asset) as existing:
            source = existing.copy() if existing.mode == mode else existing.convert(mode)
        self.addCleanup(source.close)
        return source

    @staticmethod
    def pixels(image):
        return image.mode, image.size, image.tobytes()

    def payloads(self):
        return {path.name: path.read_bytes() for path in self.directory.iterdir()
                if path.is_file() and path.suffix in ('.json', '.png')}

    def remember_checkpoint(self):
        self.previous = self.payloads()
        self.previous_digest = recovery.load_snapshot()['image_sha256']

    def install_legacy(self, *, with_state=True):
        # Copy an existing PNG byte-for-byte; legacy migration must not encode it.
        recovery.IMAGE_FILE.write_bytes(PREVIOUS_ASSET.read_bytes())
        if with_state:
            raw = json.loads(recovery.STATE_FILE.read_text(encoding='utf-8'))
            raw.update(schema=2, profile='Before', has_image=True)
            raw.pop('image_sha256', None)
            recovery.STATE_FILE.write_text(json.dumps(raw), encoding='utf-8')
            self.remember_checkpoint()
        else:
            recovery.STATE_FILE.unlink()

    def save(self, source=None):
        return recovery.save_snapshot(profile='After', options={'quality': 'Balanced'},
                                      image=source, clear_render_resume=True)

    def failure_from(self, operation):
        # assertRaises clears the traceback. Keep it to check the original error.
        try:
            operation()
        except BaseException as failure:
            return failure
        self.fail('The failed recovery save unexpectedly returned successfully.')

    def assert_previous_checkpoint(self, *, extra_image=False):
        current = self.payloads()
        for name, value in self.previous.items():
            self.assertEqual(current.get(name), value, name)
        if not extra_image:
            self.assertEqual(current, self.previous)
        state = recovery.load_snapshot()
        self.assertEqual(state['profile'], 'Before')
        self.assertEqual(state['image_sha256'], self.previous_digest)
        self.assertEqual(state['render_resume'], self.progress)
        restored = recovery.load_cached_image(expected_sha256=self.previous_digest)
        self.assertIsNotNone(restored)
        try:
            self.assertEqual(self.pixels(restored), self.pixels(self.previous_source))
        finally:
            restored.close()

    def staging(self):
        return list(self.directory.glob('.recovery-image-*.png.tmp'))

    def assert_notes(self, failure, *types):
        notes = getattr(failure, '__notes__', ())
        self.assertEqual(len(notes), len(types))
        for note, kind in zip(notes, types):
            self.assertIn(kind.__name__, note)

    def assert_primary(self, failure, primary, *secondary_types):
        self.assertIs(failure, primary)
        self.assertIsNotNone(failure.__traceback__)
        self.assert_notes(failure, *secondary_types)

    def close_hook(self, resource, failure):
        native_close = resource.close
        record = {'resource': resource, 'close_calls': 0}
        self.addCleanup(native_close)

        def close():
            record['close_calls'] += 1
            native_close()
            # A second native close is harmless; do not invent destructor errors
            # when old NamedTemporaryFile.__exit__ later runs its closer.
            if failure is not None and record['close_calls'] == 1:
                raise failure

        resource.close = close
        return record

    @contextmanager
    def conversions(self, close_failure=None):
        records = []
        native_convert = Image.Image.convert

        def convert(source, *args, **kwargs):
            converted = native_convert(source, *args, **kwargs)
            records.append(self.close_hook(converted, close_failure))
            return converted

        with patch.object(Image.Image, 'convert', convert):
            yield records

    @contextmanager
    def writers(self, *, write_failure=None, close_failure=None):
        records = []
        native_factory = recovery.tempfile.NamedTemporaryFile

        def factory(*args, **kwargs):
            stream = native_factory(*args, **kwargs)
            if kwargs.get('prefix') != '.recovery-image-':
                return stream
            record = self.close_hook(stream.file, close_failure)
            record.update(path=Path(stream.name), written_bytes=0, write_calls=0)
            records.append(record)
            native_write = stream.file.write

            def write(value):
                written = native_write(value)
                record['write_calls'] += 1
                record['written_bytes'] += written
                if write_failure is not None and record['write_calls'] == 1:
                    raise write_failure
                return written

            stream.file.write = write
            return stream

        with patch.object(recovery.tempfile, 'NamedTemporaryFile', factory):
            yield records

    @contextmanager
    def readers(self, kind, *, read_failure=None, close_failure=None):
        records = []
        native_open = Path.open

        def open_file(path, *args, **kwargs):
            stream = native_open(path, *args, **kwargs)
            mode = args[0] if args else kwargs.get('mode', 'r')
            selected = (path == recovery.IMAGE_FILE if kind == 'legacy' else
                        path.parent == self.directory and path.name.startswith('.recovery-image-'))
            if mode != 'rb' or not selected:
                return stream
            record = self.close_hook(stream, close_failure)
            record.update(path=path, read_bytes=0, read_calls=0)
            records.append(record)
            native_read = stream.read

            def read(*read_args, **read_kwargs):
                value = native_read(*read_args, **read_kwargs)
                record['read_calls'] += 1
                record['read_bytes'] += len(value)
                if read_failure is not None and record['read_calls'] == 1:
                    raise read_failure
                return value

            stream.read = read
            return stream

        with patch.object(Path, 'open', open_file):
            yield records

    @contextmanager
    def denied_staging_unlink(self, failure):
        attempted = []
        native_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if (path.parent == self.directory and path.name.startswith('.recovery-image-')
                    and path.name.endswith('.png.tmp')):
                attempted.append(path)
                raise failure
            return native_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', unlink):
            yield attempted

    def assert_stream_closed(self, records, *, operation):
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]['resource'].closed)
        self.assertGreaterEqual(records[0]['close_calls'], 1)
        self.assertGreater(records[0][operation + '_bytes'], 0)

    def assert_conversion_closed(self, records):
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['close_calls'], 1)
        with self.assertRaises(ValueError):
            records[0]['resource'].getpixel((0, 0))

    def assert_published(self, source):
        state = recovery.load_snapshot()
        self.assertEqual(state['profile'], 'After')
        self.assertIsNone(state['render_resume'])
        self.assertFalse(recovery.RENDER_FILE.exists())
        digest = state['image_sha256']
        self.assertNotEqual(digest, self.previous_digest)
        path = recovery._image_path(digest)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        expected = source.convert('RGBA')
        restored = recovery.load_cached_image(expected_sha256=digest)
        self.assertIsNotNone(restored)
        try:
            self.assertEqual(self.pixels(restored), self.pixels(expected))
        finally:
            expected.close()
            restored.close()
        self.assertEqual(self.staging(), [])

    def test_encode_failure_preserves_primary_when_owned_conversion_close_fails(self):
        source = self.source('RGB')
        original = self.pixels(source)
        primary = OSError(errno.ENOSPC, 'PNG write failed after real I/O')
        with self.conversions(RuntimeError('RGBA close failed')) as converted, self.writers(
                write_failure=primary) as output:
            failure = self.failure_from(lambda: self.save(source))
        self.assert_conversion_closed(converted)
        self.assert_stream_closed(output, operation='written')
        self.assertEqual(self.pixels(source), original)
        self.assert_previous_checkpoint()
        self.assertEqual(self.staging(), [])
        self.assert_primary(failure, primary, RuntimeError)
        self.assertEqual(failure.errno, errno.ENOSPC)

    def test_writer_close_does_not_replace_a_primary_png_write_failure(self):
        source = self.source()
        original = self.pixels(source)
        primary = OSError(errno.ENOSPC, 'PNG write failed after real I/O')
        with self.writers(write_failure=primary, close_failure=OSError('writer close failed')) as output:
            failure = self.failure_from(lambda: self.save(source))
        self.assert_stream_closed(output, operation='written')
        self.assertEqual(self.pixels(source), original)
        self.assert_previous_checkpoint()
        self.assertEqual(self.staging(), [])
        self.assert_primary(failure, primary, OSError)

    def test_legacy_reader_close_does_not_replace_a_real_copy_read_failure(self):
        self.install_legacy()
        primary = OSError(errno.EIO, 'legacy read failed after reading real bytes')
        with self.readers('legacy', read_failure=primary,
                          close_failure=OSError('legacy reader close failed')) as readers:
            failure = self.failure_from(self.save)
        self.assert_stream_closed(readers, operation='read')
        self.assertEqual(recovery.IMAGE_FILE.read_bytes(), PREVIOUS_ASSET.read_bytes())
        self.assert_previous_checkpoint()
        self.assertEqual(self.staging(), [])
        self.assert_primary(failure, primary, OSError)

    def test_actual_digest_byte_limit_survives_a_digest_reader_close_failure(self):
        source = self.source()
        with patch.object(recovery, 'MAX_CACHED_IMAGE_BYTES', 8), self.readers(
                'digest', close_failure=OSError('digest reader close failed')) as readers:
            failure = self.failure_from(lambda: self.save(source))
        self.assert_stream_closed(readers, operation='read')
        self.assertGreater(readers[0]['read_bytes'], 8)
        self.assert_previous_checkpoint()
        self.assertEqual(self.staging(), [])
        self.assertIsInstance(failure, ValueError)
        self.assertEqual(str(failure), 'Cached image is too large.')
        self.assertIsNotNone(failure.__traceback__)
        self.assert_notes(failure, OSError)

    def test_denied_staging_cleanup_keeps_checkpoint_and_retry_prunes_the_orphan(self):
        source = self.source()
        primary = OSError(errno.ENOSPC, 'PNG write failed after real I/O')
        with self.writers(write_failure=primary) as output, self.denied_staging_unlink(
                PermissionError('staging unlink denied')) as attempted:
            failure = self.failure_from(lambda: self.save(source))
        self.assert_stream_closed(output, operation='written')
        self.assertEqual(attempted, [output[0]['path']])
        self.assertEqual(self.staging(), attempted)
        self.assertGreater(attempted[0].stat().st_size, 0)
        self.assert_previous_checkpoint()
        # Retry uses the real publisher and its normal pruning after the fault
        # has ended. It must remove this observed orphan, not a fixture cleanup.
        self.assertEqual(self.save(source), recovery.STATE_FILE)
        self.assert_published(source)
        self.assertFalse(attempted[0].exists())
        self.assert_primary(failure, primary, PermissionError)

    def test_cleanup_chain_keeps_injected_interruption_and_all_secondary_diagnostics(self):
        source = self.source('RGB')
        original = self.pixels(source)
        primary = InterruptedError('injected encoder interruption, not a Stop callback')
        with self.conversions(RuntimeError('RGBA close failed')) as converted, self.writers(
                write_failure=primary, close_failure=OSError('writer close failed')) as output, \
                self.denied_staging_unlink(PermissionError('staging unlink denied')) as attempted:
            failure = self.failure_from(lambda: self.save(source))
        self.assert_conversion_closed(converted)
        self.assert_stream_closed(output, operation='written')
        self.assertEqual(attempted, [output[0]['path']])
        self.assertEqual(self.staging(), attempted)
        self.assertEqual(self.pixels(source), original)
        self.assert_previous_checkpoint()
        self.assert_primary(failure, primary, RuntimeError, OSError, PermissionError)

    def test_standalone_resource_close_failures_abort_before_state_publication(self):
        for kind in ('conversion', 'writer', 'legacy', 'digest'):
            with self.subTest(resource=kind):
                source = self.source('RGB' if kind == 'conversion' else 'RGBA')
                original = self.pixels(source)
                failure_to_raise = OSError(kind + ' close failed after native close')
                if kind == 'legacy':
                    self.install_legacy()
                    context = self.readers(kind, close_failure=failure_to_raise)
                elif kind == 'digest':
                    context = self.readers(kind, close_failure=failure_to_raise)
                elif kind == 'writer':
                    context = self.writers(close_failure=failure_to_raise)
                else:
                    context = self.conversions(failure_to_raise)
                with context as records:
                    failure = self.failure_from(lambda: self.save(None if kind == 'legacy' else source))
                if kind == 'conversion':
                    self.assert_conversion_closed(records)
                else:
                    self.assert_stream_closed(records, operation='written' if kind == 'writer' else 'read')
                self.assertEqual(self.pixels(source), original)
                self.assert_previous_checkpoint()
                self.assertEqual(self.staging(), [])
                self.assert_primary(failure, failure_to_raise)

    def test_standalone_staging_unlink_error_is_reported_before_checkpoint_publication(self):
        source = self.source()
        cleanup = PermissionError('directory access failed while checking the renamed staging path')
        with self.writers() as output, self.denied_staging_unlink(cleanup) as attempted:
            failure = self.failure_from(lambda: self.save(source))
        self.assert_stream_closed(output, operation='written')
        self.assertEqual(attempted, [output[0]['path']])
        # The image rename already succeeded; no session publication followed.
        self.assertFalse(attempted[0].exists())
        self.assert_previous_checkpoint(extra_image=True)
        extra = set(self.payloads()) - set(self.previous)
        self.assertEqual(len(extra), 1)
        published_png = self.directory / extra.pop()
        self.assertEqual(published_png, recovery._image_path(
            hashlib.sha256(published_png.read_bytes()).hexdigest()))
        self.assert_primary(failure, cleanup)

    def test_successful_rgb_and_rgba_saves_preserve_pixels_digest_and_borrowed_source(self):
        for mode in ('RGB', 'RGBA'):
            with self.subTest(mode=mode):
                source = self.source(mode)
                original = self.pixels(source)
                with self.conversions() as converted, self.writers() as output, self.readers('digest') as readers:
                    self.assertEqual(self.save(source), recovery.STATE_FILE)
                self.assert_stream_closed(output, operation='written')
                self.assert_stream_closed(readers, operation='read')
                if mode == 'RGB':
                    self.assert_conversion_closed(converted)
                else:
                    self.assertEqual(converted, [])
                self.assertEqual(self.pixels(source), original)
                self.assert_published(source)

    def test_successful_legacy_migration_copies_existing_png_without_reencoding(self):
        for with_state in (True, False):
            with self.subTest(legacy_state=with_state):
                self.install_legacy(with_state=with_state)
                raw = recovery.IMAGE_FILE.read_bytes()
                with self.conversions() as converted, self.writers() as output, self.readers('legacy') as readers:
                    self.assertEqual(self.save(), recovery.STATE_FILE)
                self.assertEqual(converted, [])
                self.assert_stream_closed(output, operation='written')
                self.assert_stream_closed(readers, operation='read')
                self.assertEqual(recovery.IMAGE_FILE.read_bytes(), raw)
                digest = hashlib.sha256(raw).hexdigest()
                self.assertEqual(recovery.load_snapshot()['image_sha256'], digest)
                self.assertEqual(recovery._image_path(digest).read_bytes(), raw)
                self.assert_published(self.previous_source)


if __name__ == '__main__':
    unittest.main()
