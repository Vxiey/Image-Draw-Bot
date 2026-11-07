"""Cache retention/revalidation through the public installer downloader."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import InstallerCache as cache
import UpdateCenter as update
from test_installer_updates import Response


def asset(data, version='99.0.0'):
    name = f'ImageDrawBot-{version}-Windows-x64-Setup.exe'
    return update.installer_asset({'tag_name': 'v' + version, 'assets': [{
        'name': name, 'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest(),
        'browser_download_url': f'https://github.com/Vxiey/Image-Draw-Bot/releases/download/v{version}/{name}',
    }]})


class VerifiedInstallerCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = b'MZ' + b'synthetic, never executed\n' * 512

    def download(self, data=None, **options):
        data = self.data if data is None else data
        options.setdefault('request_get', lambda *args, **kwargs: Response(data))
        return Path(update.download_installer(asset(data), directory=self.root, **options))

    def test_repeated_requests_reuse_one_fully_verified_file_without_network_or_free_space(self):
        first = self.download()
        request = Mock(side_effect=AssertionError('cache hit must not request the network'))
        progress = []
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            second = self.download(request_get=request, progress=lambda *args: progress.append(args))
            third = self.download(request_get=request)
        self.assertEqual((second, third), (first, first))
        self.assertEqual(first.read_bytes(), self.data)
        self.assertEqual(progress, [(len(self.data), len(self.data))])
        self.assertEqual(list(first.parent.glob('*.exe')), [first])
        request.assert_not_called()

    def test_same_size_corruption_is_rehashed_and_replaced_only_after_valid_download(self):
        path = self.download()
        broken = self.data[:-1] + b'!'
        path.write_bytes(broken)
        with self.assertRaises(update.UpdateCheckError):
            self.download(request_get=lambda *args, **kwargs: Response(broken))
        self.assertEqual(path.read_bytes(), broken)
        calls = []
        restored = self.download(request_get=lambda *args, **kwargs: (calls.append(1) or Response(self.data)))
        self.assertEqual(restored, path)
        self.assertEqual(path.read_bytes(), self.data)
        self.assertEqual(calls, [1])
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_missing_cached_file_is_downloaded_again(self):
        path = self.download()
        path.unlink()
        self.assertEqual(self.download(), path)
        self.assertEqual(path.read_bytes(), self.data)

    def test_stop_during_cached_hash_or_completion_preserves_verified_file(self):
        path = self.download()
        request = Mock(side_effect=AssertionError('cancelled cache reuse cannot request network'))
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] >= 4
        with self.assertRaises(InterruptedError):
            self.download(request_get=request, cancelled=cancelled)
        stop = threading.Event()
        with self.assertRaises(InterruptedError):
            self.download(request_get=request, cancelled=stop.is_set, progress=lambda *args: stop.set())
        self.assertEqual(path.read_bytes(), self.data)
        request.assert_not_called()

    def test_retention_only_removes_owned_installers_and_preserves_loose_downloads(self):
        loose = self.root / 'download-legacy.exe'
        loose.write_bytes(b'keep legacy download')
        first = self.download()
        unknown = first.parent / 'user-notes.txt'
        unknown.write_text('user owned')
        os.utime(first, (1, 1))
        second = self.download(self.data + b'2')
        third = self.download(self.data + b'3')
        self.assertFalse(first.exists())
        self.assertEqual(set(third.parent.glob('*.exe')), {second, third})
        self.assertEqual(loose.read_bytes(), b'keep legacy download')
        self.assertEqual(unknown.read_text(), 'user owned')

    def test_busy_eviction_is_deferred_without_losing_the_new_verified_download(self):
        first = self.download()
        os.utime(first, (1, 1))
        self.download(self.data + b'2')
        unlink = Path.unlink
        def blocked(path, *args, **kwargs):
            if path == first:
                raise PermissionError('synthetic running installer lock')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', blocked), patch.object(cache, '_cleanup_note') as logged:
            third = self.download(self.data + b'3')
        self.assertTrue(first.exists())
        self.assertEqual(third.read_bytes(), self.data + b'3')
        logged.assert_called_once()
        self.assertEqual(self.download(self.data + b'3'), third)
        self.assertFalse(first.exists())

    def test_unmarked_directory_and_linked_cache_are_not_adopted_or_pruned(self):
        directory = self.root / cache.CACHE_DIRECTORY
        directory.mkdir()
        unknown = directory / ('ImageDrawBot-' + '0' * 64 + '.exe')
        unknown.write_bytes(b'not a managed cache file')
        with self.assertRaisesRegex(OSError, 'ownership'):
            self.download()
        self.assertEqual(unknown.read_bytes(), b'not a managed cache file')
        with tempfile.TemporaryDirectory() as separate:
            other = Path(separate)
            unknown.unlink()
            (directory / 'ownership.txt.lock').unlink()
            directory.rmdir()
            try:
                directory.symlink_to(other, target_is_directory=True)
            except OSError as error:
                self.skipTest(f'Test symlinks unavailable: {error}')
            with self.assertRaisesRegex(OSError, 'unexpected link'):
                self.download()
            self.assertEqual(list(other.iterdir()), [])

    def test_concurrent_completed_downloads_publish_one_matching_cache_file(self):
        barrier = threading.Barrier(4)
        def get(*args, **kwargs):
            barrier.wait(3)
            return Response(self.data)
        with ThreadPoolExecutor(4) as workers:
            paths = list(workers.map(lambda _: self.download(request_get=get), range(4)))
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual(paths[0].read_bytes(), self.data)
        self.assertEqual(list(paths[0].parent.glob('*.exe')), [paths[0]])
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_retention_inventory_failure_cannot_invalidate_a_verified_download(self):
        first = self.download()
        iterator = Path.iterdir
        def denied(path):
            if path == first.parent:
                raise PermissionError('synthetic cache enumeration denial')
            return iterator(path)
        with patch.object(Path, 'iterdir', denied), patch.object(cache, '_cleanup_note') as logged:
            second = self.download(self.data + b'2')
        self.assertEqual(second.read_bytes(), self.data + b'2')
        self.assertEqual(first.read_bytes(), self.data)
        logged.assert_called_once()


if __name__ == '__main__':
    unittest.main()
