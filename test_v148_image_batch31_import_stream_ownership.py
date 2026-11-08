"""Local import owns its suspended file iterator; generic consumers borrow theirs."""
from contextlib import ExitStack, contextmanager
from io import BytesIO
from pathlib import Path
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import ImageImport as imports


class _SourceReader:
    def __init__(self, stream, observer):
        self.stream = stream
        self.observer = observer
        self.descriptor = stream.fileno()
        self.read_sizes = []
        self.returned_bytes = 0

    def read(self, amount=-1):
        self.read_sizes.append(amount)
        if self.observer.before_read is not None:
            self.observer.before_read(self)
        data = self.stream.read(amount)
        self.returned_bytes += len(data)
        if data and self.observer.after_read is not None:
            self.observer.after_read(self)
        return data

    def close(self):
        was_open = not self.stream.closed
        self.stream.close()
        if was_open and self.observer.close_error is not None:
            raise self.observer.close_error

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        self.close()


class _SnapshotWriter:
    def __init__(self, stream, observer):
        self.stream = stream
        self.observer = observer

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def write(self, data):
        if self.observer.write_error is not None:
            # A real partial write precedes the injected storage/allocation
            # failure. The importer must retain this exact exception.
            self.stream.write(data[:3])
            raise self.observer.write_error
        return self.stream.write(data)

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *error):
        return self.stream.__exit__(*error)


class StreamObservation:
    """Observe real descriptors/spools without replacing the import iterator."""
    def __init__(self, *, after_read=None, before_read=None, write_error=None,
                 close_error=None):
        self.after_read = after_read
        self.before_read = before_read
        self.write_error = write_error
        self.close_error = close_error
        self.sources = []
        self.snapshots = []

    @contextmanager
    def observe(self):
        actual_fdopen = imports.os.fdopen
        actual_spool = imports.tempfile.SpooledTemporaryFile

        def fdopen(descriptor, *args, **kwargs):
            stream = actual_fdopen(descriptor, *args, **kwargs)
            if (args[0] if args else kwargs.get('mode')) != 'rb':
                return stream
            source = _SourceReader(stream, self)
            self.sources.append(source)
            return source

        def spool(*args, **kwargs):
            stream = actual_spool(*args, **kwargs)
            self.snapshots.append(stream)
            return _SnapshotWriter(stream, self)

        with patch.object(imports.os, 'fdopen', side_effect=fdopen), \
                patch.object(imports.tempfile, 'SpooledTemporaryFile', side_effect=spool):
            yield self

    def states(self):
        values = []
        for source in self.sources:
            try:
                os.fstat(source.descriptor)
                descriptor_open = True
            except OSError:
                descriptor_open = False
            values.append(dict(stream_closed=source.stream.closed,
                               descriptor_open=descriptor_open,
                               read_sizes=list(source.read_sizes),
                               returned_bytes=source.returned_bytes))
        return dict(sources=values,
                    snapshots_closed=[value.closed for value in self.snapshots])

    def cleanup(self):
        # Test cleanup comes after the retained-error assertions. This keeps a
        # red historical run from leaving handles open in its test process.
        for source in self.sources:
            source.stream.close()
        for snapshot in self.snapshots:
            snapshot.close()


def write_source(path, mode='RGBA'):
    image = Image.new(mode, (11, 7))
    if mode == 'P':
        image.putpalette([12, 34, 56, 150, 60, 20] + [0] * 762)
        image.info['transparency'] = bytes((0, 193))
    for y in range(image.height):
        for x in range(image.width):
            color = (x * 17 % 256, y * 31 % 256, (x * 13 + y * 19) % 256)
            image.putpixel((x, y), (color + ((x * 37 + y * 23) % 256,)
                                  if mode == 'RGBA' else (x + y) % 2
                                  if mode == 'P' else color))
    with image:
        with image.convert('RGBA') as reference:
            expected = reference.tobytes()
        image.save(path, format='PNG')
    return expected


def retain_error(call):
    """Do not use assertRaises: its context removes the exception traceback."""
    try:
        call()
    except BaseException as error:
        return error
    raise AssertionError('The failure boundary was not reached.')


class ImportStreamOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='import-stream-test-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / 'source.png'
        self.expected = write_source(self.path)

    def observer(self, **kwargs):
        observer = StreamObservation(**kwargs)
        self.addCleanup(observer.cleanup)
        return observer

    def assert_released(self, observer):
        self.assertEqual(len(observer.sources), 1)
        self.assertEqual(len(observer.snapshots), 1)
        state = observer.states()
        self.assertTrue(state['snapshots_closed'][0], state)
        self.assertTrue(state['sources'][0]['stream_closed'], state)
        self.assertFalse(state['sources'][0]['descriptor_open'], state)

    def test_actual_import_and_application_loader_close_local_file_on_post_read_stop(self):
        import DrawBot
        for loader in (imports.read_image, DrawBot.load_image):
            with self.subTest(loader=loader.__module__ + '.' + loader.__name__):
                stop = threading.Event()
                observer = self.observer(after_read=lambda _reader: stop.set())
                with self.path.open('rb') as borrowed, observer.observe(), \
                        patch.object(imports.Image, 'open') as decode:
                    error = retain_error(lambda: loader(self.path, stop.is_set))
                    self.assertIsInstance(error, InterruptedError)
                    self.assertEqual(str(error), 'Image import cancelled.')
                    self.assertIsNotNone(error.__traceback__)
                    decode.assert_not_called()
                    self.assertFalse(borrowed.closed)
                    self.assertEqual(borrowed.read(8), b'\x89PNG\r\n\x1a\n')
                    self.assertGreater(observer.sources[0].returned_bytes, 0)
                    self.assert_released(observer)

    def test_retained_partial_write_failure_closes_source_without_replacing_exception(self):
        failure = MemoryError('snapshot allocation failed after a real partial write')
        observer = self.observer(write_error=failure)
        with observer.observe(), patch.object(imports.Image, 'open') as decode:
            error = retain_error(lambda: imports.read_image(self.path))
            self.assertIs(error, failure)
            self.assertIsNotNone(error.__traceback__)
            decode.assert_not_called()
            self.assert_released(observer)

    def test_actual_growth_overflow_closes_suspended_source_at_limit_plus_one(self):
        limit = self.path.stat().st_size + 20
        grown = False

        def grow(_reader):
            nonlocal grown
            if not grown:
                grown = True
                with self.path.open('ab') as output:
                    output.write(b'actual later file growth' * 20)

        observer = self.observer(before_read=grow)
        with observer.observe(), patch.object(imports.Image, 'open') as decode:
            error = retain_error(lambda: imports.read_image(self.path, max_source_bytes=limit))
            self.assertIsInstance(error, ValueError)
            self.assertIn('file-size limit', str(error))
            self.assertIsNotNone(error.__traceback__)
            decode.assert_not_called()
            self.assertEqual(observer.sources[0].returned_bytes, limit + 1)
            self.assert_released(observer)

    def test_secondary_source_close_failure_preserves_primary_write_error(self):
        failure = OSError('destination write failed')
        observer = self.observer(write_error=failure,
                                 close_error=OSError('local close reported a failure'))
        with observer.observe():
            error = retain_error(lambda: imports.read_image(self.path))
            self.assertIs(error, failure)
            self.assertIsNotNone(error.__traceback__)
            self.assert_released(observer)
            self.assertTrue(any('cleanup' in text.lower()
                                for text in getattr(error, '__notes__', ())))

    def test_success_returns_exact_owned_pixels_and_leaves_independent_reader_open(self):
        for mode in ('RGB', 'RGBA', 'P'):
            with self.subTest(mode=mode):
                expected = write_source(self.path, mode)
                observer = self.observer()
                with self.path.open('rb') as borrowed, observer.observe():
                    borrowed.read(3)
                    result = imports.read_image(self.path)
                    self.addCleanup(result.close)
                    self.assertEqual(result.mode, 'RGBA')
                    self.assertEqual(result.size, (11, 7))
                    self.assertEqual(result.tobytes(), expected)
                    self.assertEqual(result.info['draw_studio_format'], 'PNG')
                    self.assertFalse(borrowed.closed)
                    self.assertEqual(borrowed.tell(), 3)
                    self.assert_released(observer)

    def test_exhaustion_close_error_remains_a_real_import_failure(self):
        observer = self.observer(close_error=OSError('local source close failed'))
        with observer.observe(), patch.object(imports.Image, 'open') as decode:
            error = retain_error(lambda: imports.read_image(self.path))
            self.assertIsInstance(error, ValueError)
            self.assertIn('Could not access the selected image', str(error))
            self.assertIsInstance(error.__cause__, OSError)
            decode.assert_not_called()
            self.assert_released(observer)

    def test_generic_chunk_consumer_never_closes_a_borrowed_iterator_or_destination(self):
        class Borrowed:
            def __init__(self):
                self.parts = iter((b'first', b'second'))
                self.closed = False

            def __iter__(self):
                return self

            def __next__(self):
                return next(self.parts)

            def close(self):
                self.closed = True

        for stopped in (False, True):
            with self.subTest(stopped=stopped), BytesIO() as destination:
                chunks = Borrowed()
                if stopped:
                    error = retain_error(lambda: imports._write_chunks(
                        destination, chunks, 100, lambda: True))
                    self.assertIsInstance(error, InterruptedError)
                    self.assertEqual(next(chunks), b'second')
                    self.assertEqual(destination.getvalue(), b'')
                else:
                    self.assertEqual(imports._write_chunks(
                        destination, chunks, 100, lambda: False), 11)
                    self.assertEqual(destination.getvalue(), b'firstsecond')
                self.assertFalse(chunks.closed)
                self.assertFalse(destination.closed)


if __name__ == '__main__':
    unittest.main()
