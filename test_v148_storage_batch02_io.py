import errno
import json
import multiprocessing
import os
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import threading
import unittest
from unittest.mock import patch

import RuntimePaths as paths
import TargetCapture as target


def _concurrent_publication_probe(directory, writer_kind, fail_second, result_queue):
    """Force different logical transactions to collide with publication paths."""
    root = Path(directory)
    stripe = lambda path: hash(paths._path_lock_key(path)) % len(paths._FILE_LOCKS)
    history_a = root / 'history-a.json'
    latest_a = next(root / f'latest-a-{i}.json' for i in range(10000)
                    if stripe(root / f'latest-a-{i}.json') != stripe(history_a))
    history_b = next(root / f'history-b-{i}.json' for i in range(10000)
                     if stripe(root / f'history-b-{i}.json') == stripe(latest_a))
    latest_b = next(root / f'latest-b-{i}.json' for i in range(10000)
                    if stripe(root / f'latest-b-{i}.json') == stripe(history_a))
    second_a = root / 'second-a.json'
    for path in (latest_a, second_a, latest_b):
        path.write_text('old', encoding='utf-8')
    a_publishing = threading.Event()
    b_has_transaction = threading.Event()
    errors = []
    replace = paths._replace_with_retry

    def controlled_replace(source, destination):
        if threading.current_thread().name == 'writer-a' and Path(source).suffix == '.import':
            if Path(destination) == latest_a:
                a_publishing.set()
                if not b_has_transaction.wait(3):
                    raise AssertionError('second writer did not acquire its logical transaction')
            elif fail_second and Path(destination) == second_a:
                raise OSError(errno.ENOSPC, 'injected second-file publication failure')
        replace(source, destination)

    def writer_a():
        try:
            with paths.file_transaction(history_a):
                try:
                    paths.replace_text_files({latest_a: 'new', second_a: 'new'})
                except paths.FileSetTransactionError:
                    if not fail_second:
                        raise
                else:
                    if fail_second:
                        raise AssertionError('injected publication failure was lost')
        except BaseException as error:
            errors.append(f'writer-a: {type(error).__name__}: {error}')

    def writer_b():
        try:
            if not a_publishing.wait(3):
                raise AssertionError('first writer did not reach publication')
            with paths.file_transaction(history_b):
                b_has_transaction.set()
                if writer_kind == 'ordinary':
                    paths.atomic_write_text(latest_b, 'other writer')
                else:
                    paths.replace_text_files({latest_b: 'other writer'})
        except BaseException as error:
            errors.append(f'writer-b: {type(error).__name__}: {error}')

    with patch.object(paths, '_replace_with_retry', side_effect=controlled_replace):
        threads = [threading.Thread(target=writer_a, name='writer-a', daemon=True),
                   threading.Thread(target=writer_b, name='writer-b', daemon=True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        result_queue.put({
            'alive': [thread.name for thread in threads if thread.is_alive()],
            'errors': errors,
            'first': latest_a.read_text(encoding='utf-8'),
            'second': second_a.read_text(encoding='utf-8'),
            'other': latest_b.read_text(encoding='utf-8'),
            'staging': [path.name for path in root.iterdir()
                        if path.suffix in ('.tmp', '.backup', '.import')],
        })


class StorageIOBatch02Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'state.json'

    @staticmethod
    def windows_error(code):
        error = PermissionError(errno.EACCES, 'injected Windows sharing failure')
        error.winerror = code
        return error

    def test_windows_transient_sharing_failures_retry_the_same_atomic_publication(self):
        replace = os.replace
        for code in (5, 32, 33):
            with self.subTest(code=code):
                self.path.write_text('old')
                attempts = []
                def publish(source, destination):
                    attempts.append((source, destination))
                    if len(attempts) == 1:
                        self.assertEqual(self.path.read_text(), 'old')
                        raise self.windows_error(code)
                    replace(source, destination)
                with patch.object(paths.sys, 'platform', 'win32'), \
                     patch.object(paths.os, 'replace', side_effect=publish), \
                     patch.object(paths.time, 'sleep') as delay:
                    paths.atomic_write_text(self.path, 'complete new content')
                self.assertEqual(attempts[0], attempts[1])
                self.assertEqual(self.path.read_text(), 'complete new content')
                self.assertEqual(list(self.root.iterdir()), [self.path])
                delay.assert_called_once_with(.01)

    def test_permanent_windows_denial_still_raises_and_preserves_the_destination(self):
        self.path.write_text('old')
        with patch.object(paths.sys, 'platform', 'win32'), \
             patch.object(paths.os, 'replace', side_effect=self.windows_error(5)) as replace, \
             patch.object(paths.time, 'sleep') as delay:
            with self.assertRaises(PermissionError):
                paths.atomic_write_text(self.path, 'new')
        self.assertEqual(replace.call_count, 10)
        self.assertAlmostEqual(sum(call.args[0] for call in delay.call_args_list), .65)
        self.assertEqual(self.path.read_text(), 'old')
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_nonsharing_errors_are_not_retried(self):
        for platform, error in (('linux', self.windows_error(5)),
                                ('win32', OSError(errno.ENOSPC, 'disk full')),
                                ('win32', PermissionError(errno.EACCES, 'not a native sharing status'))):
            with self.subTest(platform=platform, error=error), \
                 patch.object(paths.sys, 'platform', platform), \
                 patch.object(paths.os, 'replace', side_effect=error) as replace, \
                 patch.object(paths.time, 'sleep') as delay:
                with self.assertRaises(OSError):
                    paths.atomic_write_text(self.path, 'new')
                replace.assert_called_once()
                delay.assert_not_called()
            self.assertEqual(list(self.root.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'requires native Windows sharing semantics')
    def test_native_windows_reader_can_release_destination_during_retry(self):
        import concurrent.futures
        import threading
        self.path.write_text('old')
        replace = os.replace
        denied = threading.Event()
        def publish(source, destination):
            try:
                replace(source, destination)
            except OSError:
                denied.set()
                raise
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            with self.path.open('rb') as reader, patch.object(paths.os, 'replace', side_effect=publish):
                future = pool.submit(paths.atomic_write_text, self.path, 'new')
                self.assertTrue(denied.wait(2), 'reader did not produce the expected sharing conflict')
            future.result(timeout=3)
        self.assertEqual(self.path.read_text(), 'new')

    def test_target_helper_log_redacts_before_bounding_and_keeps_protocol_usable(self):
        payload = dict(ok=True, handle=11, rect=[0, 0, 10, 10], client_rect=[0, 0, 10, 10])
        secret = 'SYNTHETIC_SECRET'
        output = ('x' * 100000 + '\nhttps://example.invalid/image?signature=' + secret
                  + '\nAuthorization: Bearer ' + secret)
        result = CompletedProcess(['fake'], 0, json.dumps(payload), output)
        with patch.object(target, 'BASE', self.root), patch.object(target.subprocess, 'run', return_value=result):
            self.assertEqual(target._run(['fake'])['handle'], 11)
        log = (self.root / 'logs/ImageDrawBot-target-probe.log').read_text()
        self.assertNotIn(secret, log)
        self.assertIn('<redacted>', log)
        self.assertLessEqual(len(log), target.MAX_HELPER_LOG_CHARS)
        self.assertIn('truncated', log)

    def test_file_set_keyboard_interruption_rolls_back_the_prior_pair(self):
        other = self.path.with_name('second.json')
        self.path.write_text('first old')
        other.write_text('second old')
        original = os.replace
        def interrupt_second(source, destination):
            if Path(destination) == other and Path(source).suffix == '.import':
                raise KeyboardInterrupt('cancel staging publish')
            return original(source, destination)
        with patch.object(paths.os, 'replace', side_effect=interrupt_second):
            with self.assertRaises(KeyboardInterrupt):
                paths.replace_text_files({self.path: 'first new', other: 'second new'})
        self.assertEqual(self.path.read_text(), 'first old')
        self.assertEqual(other.read_text(), 'second old')
        self.assertEqual(set(self.path.parent.iterdir()), {self.path, other})

    def test_file_set_alias_destinations_are_rejected_before_mutation(self):
        self.path.write_text('old')
        alias = self.path.parent / 'sub' / '..' / self.path.name
        with self.assertRaises(ValueError):
            paths.replace_text_files({self.path: 'new', alias: 'conflicting'})
        self.assertEqual(self.path.read_text(), 'old')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_publication_never_inverts_logical_lock_order_even_during_rollback(self):
        context = multiprocessing.get_context('spawn')
        for writer_kind in ('ordinary', 'file_set'):
            for fail_second in (False, True):
                with self.subTest(writer=writer_kind, rollback=fail_second), \
                     tempfile.TemporaryDirectory() as directory:
                    result_queue = context.Queue()
                    child = context.Process(target=_concurrent_publication_probe,
                                            args=(directory, writer_kind, fail_second, result_queue))
                    child.start()
                    try:
                        child.join(12)
                        self.assertFalse(child.is_alive(), 'publication probe exceeded its process deadline')
                        self.assertEqual(child.exitcode, 0)
                        result = result_queue.get(timeout=2)
                        self.assertEqual(result['alive'], [], result)
                        self.assertEqual(result['errors'], [], result)
                        self.assertEqual(result['first'], 'old' if fail_second else 'new')
                        self.assertEqual(result['second'], 'old' if fail_second else 'new')
                        self.assertEqual(result['other'], 'other writer')
                        self.assertEqual(result['staging'], [])
                    finally:
                        if child.is_alive():
                            child.terminate()
                            child.join(3)
                        child.close()
                        result_queue.close()
                        result_queue.join_thread()

    def test_target_deadline_and_area_fail_before_a_helper_is_started(self):
        with patch.object(target.subprocess, 'run') as launch:
            for invalid in (None, True, 0, -1, float('inf'), float('nan'), 10 ** 400):
                with self.subTest(timeout=type(invalid).__name__):
                    with self.assertRaises(ValueError):
                        target._run(['helper'], timeout=invalid)
            for area in ((1, 2, 0, 4), (1, 2, 3, -4), (1.5, 2, 3, 4),
                         (True, 2, 3, 4), (2 ** 31 - 1, 2, 3, 4), (1, 2, 3)):
                with self.subTest(area=area):
                    with self.assertRaises(ValueError):
                        target.capture_target_metadata_isolated(area)
            for pid in (0, -1, True, 2 ** 32, '42'):
                with self.assertRaises(ValueError):
                    target.capture_target_metadata_isolated((1, 2, 3, 4), exclude_pid=pid)
            launch.assert_not_called()

    def test_deep_or_extreme_json_is_a_controlled_invalid_helper_response(self):
        for raw in ('[' * 1500 + '0' + ']' * 1500, '{"handle":' + '9' * 5000 + '}'):
            result = CompletedProcess(['helper'], 0, raw, '')
            with patch.object(target, 'BASE', self.path.parent), \
                 patch.object(target.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(OSError, 'no valid response'):
                    target._run(['helper'])


if __name__ == '__main__':
    unittest.main()
