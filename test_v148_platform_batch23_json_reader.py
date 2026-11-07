"""Local JSON input grows with actual bytes, retaining every bounded-read rule."""
from contextlib import ExitStack, closing, contextmanager
import gc
import io
import json
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

import DrawBot
import DrawTimeCalibration as timing
import RealSpeedBudget as speed
import ResourceScheduler as scheduler
import RuntimePaths as runtime
import SessionRecovery as recovery
from RenderResume import checkpoint_after_batch
from test_render_resume_v1042 import simple_plan
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch21_calibration_scope import (
    public_environment, public_options, public_source, seed_public_contexts)
from benchmark_v148_rendering_batch21_calibration import comparable


CHUNK_BYTES = 64 * 1024


class ConsumerFixture:
    """Real production files/consumers; all setup stays outside measurements."""
    def __enter__(self):
        self.stack = ExitStack()
        try:
            self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
            self.source = self.stack.enter_context(closing(public_source()))
            self.stack.enter_context(public_environment(self.directory))
            contexts = {}
            for name in ('paint_pixel', 'paint_fill', 'paint_dynamic'):
                contexts.update(seed_public_contexts(self.source, public_options(name)))
            self.pixel = next(settings for settings in contexts.values()
                              if settings.get('draw_quality') == 'Pixel Accurate')
            self.timing_path = timing._resolved_path(self.pixel, None)
            self.speed_path = self.directory / 'speed.json'
            self.scheduler_path = self.directory / 'scheduler.json'
            for _ in range(3):
                result = speed.record_runtime_sample('gartic-phone', 50, 10., colors=3, path=self.speed_path)
                if not result.get('recorded'):
                    raise AssertionError(result)
            scheduler.save_recommendation(dict(logical_cpus=8, recommended_workers=4,
                recommended_engine='Threads', ram_budget_mb=2048, best_score=2.5,
                scores=[], machine_signature='controlled-reader-fixture'), self.scheduler_path)
            self.recovery_directory = self.directory / 'recovery'
            for name, value in (
                    ('RECOVERY_DIR', self.recovery_directory),
                    ('STATE_FILE', self.recovery_directory / 'session-recovery.json'),
                    ('RENDER_FILE', self.recovery_directory / 'render-resume.json'),
                    ('IMAGE_FILE', self.recovery_directory / 'last-image.png')):
                self.stack.enter_context(patch.object(recovery, name, value))
            base = simple_plan()
            try:
                progress = checkpoint_after_batch(base, 2)
            finally:
                close_plan(base, self.source)
            recovery.save_snapshot(profile='Microsoft Paint',
                options={'color_workflow': 'Finish color first'}, saved_area=[(1, 2), (30, 40)])
            recovery.save_render_progress(progress)
            self.state_path, self.render_path = recovery.STATE_FILE, recovery.RENDER_FILE
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        self.stack.close()

    def cases(self):
        return {
            'timing_correction': (lambda: timing.correction_for(self.pixel), [self.timing_path]),
            'real_speed_profile': (lambda: speed.load_profile('gartic-phone', self.speed_path), [self.speed_path]),
            'scheduler_recommendation': (lambda: scheduler.load_recommendation(self.scheduler_path,
                signature='controlled-reader-fixture'), [self.scheduler_path]),
            'render_progress': (recovery.load_render_progress, [self.render_path]),
            'full_recovery_snapshot': (recovery.load_snapshot, [self.state_path, self.render_path]),
            'public_paint_pixel_plan': (lambda: DrawBot.make_plan(self.source, self.source.size,
                public_options('paint_pixel')), [self.timing_path]),
        }

    def close_result(self, name, value):
        if name == 'public_paint_pixel_plan' and value is not None:
            close_plan(value, self.source)


@contextmanager
def file_reads(paths, *, short_read=None, fail_on=None, error_type=OSError, after_read=None):
    """Wrap actual regular files; track requested/returned bytes and ownership."""
    paths = {Path(path) for path in paths}
    opened_files, reads = [], []
    original_open = Path.open
    class Stream:
        def __init__(self, stream, path):
            self.stream, self.path, self.calls = stream, path, 0
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, size=-1):
            self.calls += 1
            if self.calls == fail_on:
                raise error_type('controlled file read failure')
            result = self.stream.read(min(size, short_read) if short_read is not None else size)
            reads.append(dict(path=self.path, requested=size, returned=len(result)))
            if after_read is not None:
                after_read(self.path, self.calls, size, result)
            return result
        def __getattr__(self, name):
            return getattr(self.stream, name)
    def opened(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if Path(path) in paths and args == ('rb',):
            opened_files.append(stream)
            return Stream(stream, Path(path))
        return stream
    with patch.object(Path, 'open', new=opened):
        yield reads, opened_files


class BoundedJsonReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'state.json'

    def test_actual_consumers_no_longer_request_the_whole_budget_for_small_files(self):
        with ConsumerFixture() as fixture:
            for name, (call, paths) in fixture.cases().items():
                with self.subTest(name=name):
                    expected = call()
                    try:
                        frozen = comparable(expected)
                    finally:
                        fixture.close_result(name, expected)
                    file_bytes = {path: path.read_bytes() for path in paths}
                    with file_reads(paths) as (reads, handles):
                        actual = call()
                    try:
                        self.assertEqual(comparable(actual), frozen)
                        self.assertTrue(reads)
                        self.assertLessEqual(max(row['requested'] for row in reads), CHUNK_BYTES,
                            'Real consumers must reserve a block, not their 256 KiB–8 MiB file allowance.')
                        for path in paths:
                            self.assertEqual(sum(row['returned'] for row in reads if row['path'] == path),
                                             len(file_bytes[path]))
                        self.assertTrue(all(stream.closed for stream in handles))
                        self.assertEqual({path: path.read_bytes() for path in paths}, file_bytes)
                    finally:
                        fixture.close_result(name, actual)

    def test_small_regular_file_allocation_is_independent_of_its_eight_megabyte_allowance(self):
        self.path.write_text(json.dumps({'text': 'valid state ' * 300}), encoding='utf-8')
        expected = runtime.read_json(self.path)
        gc.collect()
        tracemalloc.start()
        try:
            actual = runtime.read_json(self.path, max_bytes=8 * 1024 * 1024)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(actual, expected)
        self.assertLess(peak, 256 * 1024,
                        'A few KiB of JSON must not reserve an 8 MiB read buffer.')

    def test_exact_byte_limits_and_one_byte_sentinel_remain_authoritative(self):
        for limit in (0, 1, 7, CHUNK_BYTES - 1, CHUNK_BYTES, CHUNK_BYTES + 1, 2 * CHUNK_BYTES):
            for extra in (0, 1):
                with self.subTest(limit=limit, extra=extra):
                    content = (b'0' + b' ' * max(0, limit + extra - 1)) if limit + extra else b''
                    self.path.write_bytes(content)
                    with file_reads([self.path]) as (reads, handles):
                        if len(content) > limit:
                            with self.assertRaisesRegex(ValueError, 'supported file size'):
                                runtime.read_json(self.path, max_bytes=limit)
                        elif not content:
                            with self.assertRaises(json.JSONDecodeError):
                                runtime.read_json(self.path, max_bytes=limit)
                        else:
                            self.assertEqual(runtime.read_json(self.path, max_bytes=limit), 0)
                    total = 0
                    for row in reads:
                        self.assertGreater(row['requested'], 0)
                        self.assertLessEqual(row['requested'], min(CHUNK_BYTES, limit + 1 - total))
                        total += row['returned']
                    self.assertLessEqual(total, limit + 1)
                    self.assertEqual(total, len(content))
                    self.assertTrue(all(handle.closed for handle in handles))

    def test_positive_short_reads_continue_to_eof_without_accepting_a_valid_prefix(self):
        content = json.dumps({'message': 'short reads é🐈 ' * 60}, ensure_ascii=False).encode('utf-8')
        self.path.write_bytes(content)
        expected = json.loads(content)
        with file_reads([self.path], short_read=7) as (reads, handles):
            self.assertEqual(runtime.read_json(self.path, max_bytes=len(content)), expected)
        self.assertGreater(len(reads), 100)
        self.assertEqual(sum(row['returned'] for row in reads), len(content))
        self.assertEqual(reads[-1]['returned'], 0)
        self.assertTrue(all(handle.closed for handle in handles))
        self.path.write_bytes(b'0 trailing invalid JSON')
        with file_reads([self.path], short_read=1), self.assertRaises(json.JSONDecodeError):
            runtime.read_json(self.path)

    def test_short_reads_never_exceed_the_cumulative_overflow_sentinel(self):
        self.path.write_bytes(b'0' + b' ' * 500)
        with file_reads([self.path], short_read=3) as (reads, handles), \
                self.assertRaisesRegex(ValueError, 'supported file size'):
            runtime.read_json(self.path, max_bytes=80)
        total = 0
        for row in reads:
            self.assertLessEqual(row['requested'], 81 - total)
            total += row['returned']
        self.assertEqual(total, 81)
        self.assertTrue(all(handle.closed for handle in handles))

    def test_invalid_limit_types_and_native_index_bounds_do_not_allow_unbounded_reads(self):
        self.path.write_bytes(b'0')
        for limit, kind in ((1.0, TypeError), ('1', TypeError), (None, TypeError),
                            (sys.maxsize, OverflowError), (-sys.maxsize - 3, OverflowError),
                            (-5, ValueError), (-2, ValueError), (-1, ValueError)):
            with self.subTest(limit=limit), file_reads([self.path]) as (reads, handles), \
                    self.assertRaises(kind):
                runtime.read_json(self.path, max_bytes=limit)
            self.assertFalse(reads)
            self.assertTrue(all(handle.closed for handle in handles))

    def test_bom_and_multibyte_utf8_cross_block_boundaries_before_one_decode(self):
        for bom in (b'', b'\xef\xbb\xbf'):
            for text in ('é', '漢', '🐈'):
                with self.subTest(bom=bool(bom), text=text):
                    padding = CHUNK_BYTES - len(bom) - len(b'{"text":"') - 1
                    value = {'text': 'a' * padding + text + '\\"tail'}
                    encoded = bom + json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                    self.path.write_bytes(encoded)
                    self.assertEqual(runtime.read_json(self.path, max_bytes=len(encoded)), value)
                    with file_reads([self.path], short_read=5):
                        self.assertEqual(runtime.read_json(self.path, max_bytes=len(encoded)), value)

    def test_invalid_unicode_duplicate_nonfinite_depth_and_nodes_keep_existing_errors(self):
        samples = (
            (b'"' + b'a' * CHUNK_BYTES + b'\xc3"', {}, UnicodeDecodeError),
            (b'\xff\xfe{\x00}\x00', {}, UnicodeDecodeError),
            (b'{"a":1,"a":2}', {}, ValueError),
            (b'{"a":NaN}', {}, ValueError),
            (b'{"a":1e309}', {}, ValueError),
            (('[' * 40 + '0' + ']' * 40).encode(), {}, ValueError),
            (b'[0,1,2,3]', {'max_items': 4}, ValueError),
            (b'{"nested":[0]}', {'max_depth': 1}, ValueError),
        )
        for content, kwargs, kind in samples:
            with self.subTest(kind=kind, kwargs=kwargs):
                self.path.write_bytes(content)
                with file_reads([self.path]) as (_reads, handles), self.assertRaises(kind):
                    runtime.read_json(self.path, **kwargs)
                self.assertTrue(all(handle.closed for handle in handles))
        self.path.write_bytes(b'[0,1,2,3]')
        self.assertEqual(runtime.read_json(self.path, max_items=5, max_depth=1), [0, 1, 2, 3])

    def test_growth_past_the_limit_is_seen_without_stat_or_seek(self):
        initial = b'0' + b' ' * (CHUNK_BYTES - 1)
        self.path.write_bytes(initial)
        appended = []
        def grow(path, count, requested, returned):
            if count == 1:
                with path.open('ab') as stream:
                    stream.write(b' ' * CHUNK_BYTES)
                appended.append(True)
        with file_reads([self.path], after_read=grow) as (reads, handles), \
                patch.object(Path, 'stat', side_effect=AssertionError('The read limit must not depend on stat')), \
                self.assertRaisesRegex(ValueError, 'supported file size'):
            runtime.read_json(self.path, max_bytes=CHUNK_BYTES + 10)
        self.assertTrue(appended)
        self.assertEqual(sum(row['returned'] for row in reads), CHUNK_BYTES + 11)
        self.assertTrue(all(handle.closed for handle in handles))

    def test_mid_read_truncation_does_not_return_a_partial_json_value(self):
        content = b'{"text":"' + b'x' * (3 * CHUNK_BYTES) + b'"}'
        self.path.write_bytes(content)
        def truncate(path, count, requested, returned):
            if count == 1:
                with path.open('r+b') as stream:
                    stream.truncate(CHUNK_BYTES)
        with file_reads([self.path], after_read=truncate) as (_reads, handles), \
                self.assertRaises(json.JSONDecodeError):
            runtime.read_json(self.path)
        self.assertTrue(all(handle.closed for handle in handles))

    def test_open_file_and_accumulator_close_on_retained_io_stop_and_allocation_errors(self):
        self.path.write_bytes(b'"' + b'x' * (3 * CHUNK_BYTES) + b'"')
        class TrackingBuffer(io.BytesIO):
            pass
        for kind in (OSError, InterruptedError, MemoryError):
            buffers, retained = [], None
            def create_buffer():
                buffer = TrackingBuffer()
                buffers.append(buffer)
                return buffer
            with self.subTest(kind=kind), patch.object(runtime, 'BytesIO', side_effect=create_buffer), \
                    file_reads([self.path], fail_on=3, error_type=kind) as (_reads, handles):
                try:
                    runtime.read_json(self.path)
                except kind as error:
                    retained = error
            self.assertIsNotNone(retained)
            self.assertTrue(handles)
            self.assertTrue(buffers)
            self.assertTrue(all(handle.closed for handle in handles))
            self.assertTrue(all(buffer.closed for buffer in buffers))
            with self.assertRaises(ValueError):
                buffers[0].getvalue()
            frame = retained.__traceback__
            while frame is not None:
                if frame.tb_frame.f_code.co_name == '_read_json_bytes':
                    for name in ('first', 'block', 'buffer', 'stream'):
                        self.assertIsNone(frame.tb_frame.f_locals[name])
                frame = frame.tb_next

    def test_accumulator_append_allocation_failure_closes_owned_buffer_before_unwind(self):
        self.path.write_bytes(b'"' + b'x' * (3 * CHUNK_BYTES) + b'"')
        for failure_call in (1, 2):
            buffers, retained = [], None
            class FailingBuffer(io.BytesIO):
                calls = 0
                def write(self, data):
                    self.calls += 1
                    if self.calls == failure_call:
                        raise MemoryError('controlled accumulator append failure')
                    return super().write(data)
            def create_buffer():
                buffer = FailingBuffer()
                buffers.append(buffer)
                return buffer
            with self.subTest(failure_call=failure_call), \
                    patch.object(runtime, 'BytesIO', side_effect=create_buffer), \
                    file_reads([self.path]) as (_reads, handles):
                try:
                    runtime.read_json(self.path)
                except MemoryError as error:
                    retained = error
            self.assertIsNotNone(retained)
            self.assertTrue(buffers)
            self.assertTrue(all(handle.closed for handle in handles))
            self.assertTrue(all(buffer.closed for buffer in buffers))

    def test_missing_permission_and_malformed_files_keep_real_consumer_fallbacks(self):
        with ConsumerFixture() as fixture:
            fixture.timing_path.write_bytes(b'\xffinvalid utf8')
            self.assertFalse(timing.correction_for(fixture.pixel)['learned'])
            fixture.scheduler_path.write_bytes(b'{"version":2,"version":2}')
            self.assertIsNone(scheduler.load_recommendation(fixture.scheduler_path, signature='controlled-reader-fixture'))
            fixture.render_path.write_bytes(b'\xff')
            recovered = recovery.load_snapshot()
            self.assertEqual(recovered['profile'], 'Microsoft Paint')
            self.assertIsNone(recovered['render_resume'])
            fixture.state_path.unlink()
            self.assertIsNone(recovery.load_snapshot())
            with patch.object(Path, 'open', side_effect=PermissionError('unreadable')):
                self.assertFalse(timing.correction_for(fixture.pixel)['learned'])
                self.assertIsNone(recovery.load_snapshot())


if __name__ == '__main__':
    unittest.main()
