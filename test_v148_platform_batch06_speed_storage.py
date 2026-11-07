"""Existing SS03/SS04 storage guarantees applied to learned real-speed data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import RealSpeedBudget as speed


class RealSpeedStorageCompletionTests(unittest.TestCase):
    def test_large_or_deeply_nested_file_falls_back_without_unbounded_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'speed.json'
            path.write_bytes(b' ' * (speed.MAX_SPEED_FILE_BYTES + 100))
            with patch.object(speed.json, 'loads', side_effect=AssertionError('oversized data cannot reach JSON parser')):
                self.assertEqual(speed.load_all(path), {'version': speed.VERSION, 'profiles': {}})
            path.write_text('[' * 2000 + '0' + ']' * 2000)
            self.assertEqual(speed.load_all(path), {'version': speed.VERSION, 'profiles': {}})

    def test_parallel_samples_for_two_profiles_keep_every_completed_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'speed.json'
            keys = ('gartic-phone', 'skribbl')
            def record(number):
                return speed.record_runtime_sample(keys[number % 2], 10, 1.0, path=path)
            with ThreadPoolExecutor(8) as workers:
                results = list(workers.map(record, range(64)))
            self.assertTrue(all(item['recorded'] for item in results))
            for key in keys:
                profile = speed.load_profile(key, path)
                self.assertEqual(profile['samples'], 32)
                self.assertEqual(profile['total_paths'], 320)
                self.assertEqual(profile['total_seconds'], 32.0)
                self.assertEqual(profile['paths_per_second'], 10.0)
            self.assertFalse(list(Path(temporary).glob('*.tmp')))

    def test_shared_json_and_schema_limits_reject_ambiguous_or_nonfinite_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'speed.json'
            invalid = ('{"version":true,"profiles":{}}',
                       '{"version":1,"version":1,"profiles":{}}',
                       '{"version":1,"profiles":{"gartic-phone":{"paths_per_second":NaN}}}',
                       '{"version":1,"profiles":{"skribbl":{"total_seconds":Infinity}}}',
                       '{"version":1,"profiles":' + '[' * 50 + '0' + ']' * 50 + '}')
            for raw in invalid:
                path.write_text(raw)
                with self.subTest(raw=raw):
                    self.assertEqual(speed.load_all(path), {'version': speed.VERSION, 'profiles': {}})

    def test_failed_publication_preserves_previous_measurements_and_releases_transaction(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'speed.json'
            speed.record_runtime_sample('gartic-phone', 10, 1.0, path=path)
            previous = path.read_bytes()
            with patch.object(speed, 'atomic_write_text', side_effect=PermissionError('synthetic write denial')):
                with self.assertRaises(PermissionError):
                    speed.record_runtime_sample('gartic-phone', 20, 2.0, path=path)
            self.assertEqual(path.read_bytes(), previous)
            speed.record_runtime_sample('gartic-phone', 30, 3.0, path=path)
            profile = speed.load_profile('gartic-phone', path)
            self.assertEqual(profile['samples'], 2)
            self.assertEqual(profile['total_paths'], 40)


if __name__ == '__main__':
    unittest.main()
