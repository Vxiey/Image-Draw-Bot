"""Failure-injection and persistence regressions for the v1.0.148 storage batch."""
import concurrent.futures
import copy
import errno
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import AppTools
import AutoTunerFeedback as feedback
import CalibrationHealth
import CompletedDrawLearning
import CorrectionHistory
import DrawTimeCalibration as timing
import ExactColorTools
import PerformanceAutoTuner
import ProfileStorage
import ReleasePackage
import ReleaseState
import ResourceScheduler
import RuntimePaths
from CalibrationAnchors import make_anchor


def increment_file(path, count):
    path = Path(path)
    for _ in range(count):
        with RuntimePaths.file_transaction(path):
            value = RuntimePaths.read_json(path) if path.exists() else 0
            RuntimePaths.atomic_write_text(path, json.dumps(value + 1))


def feedback_plan(strategy='normal', post=None):
    return {'count': 10, 'estimate': 10, 'options': {
        'profile_key': 'test',
        'auto_tuner_meta': {'active': True, 'selected_strategy': strategy,
                            'source_features': {'source_kind': 'line art'}},
        'adaptive_accuracy_meta': {'visual_accuracy_percent': 90},
        'post_draw_accuracy_meta': post,
    }}


class StorageSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'state.json'

    def test_real_fsync_errors_preserve_existing_state_and_remove_staging(self):
        self.path.write_text('old', encoding='utf-8')
        for code in (errno.EIO, errno.ENOSPC, errno.EACCES):
            with self.subTest(code=code), patch('RuntimePaths.os.fsync', side_effect=OSError(code, 'injected')):
                with self.assertRaises(OSError):
                    RuntimePaths.atomic_write_text(self.path, 'new')
            self.assertEqual(self.path.read_text(), 'old')
            self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_unsupported_fsync_retains_atomic_replace_fallback(self):
        with patch('RuntimePaths.os.fsync', side_effect=OSError(errno.ENOTSUP, 'unsupported')):
            RuntimePaths.atomic_write_text(self.path, 'complete')
        self.assertEqual(self.path.read_text(), 'complete')

    def test_write_failure_also_removes_staging_before_flush(self):
        self.path.write_text('old')
        factory = RuntimePaths.tempfile.NamedTemporaryFile
        @contextmanager
        def failed_write(*args, **kwargs):
            with factory(*args, **kwargs) as stream:
                yield SimpleNamespace(name=stream.name, write=Mock(side_effect=OSError('write failed')))
        with patch('RuntimePaths.tempfile.NamedTemporaryFile', failed_write), self.assertRaises(OSError):
            RuntimePaths.atomic_write_text(self.path, 'new')
        self.assertEqual(self.path.read_text(), 'old')
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_shared_atomic_savers_do_not_replace_good_files_after_disk_failure(self):
        self.path.write_text('old')
        anchor = make_anchor((0, 0, 800, 600))
        savers = [
            lambda: AppTools.save_calibration('test', {'Brush': [2, 3]}, anchor=anchor, path=self.path),
            lambda: ExactColorTools.save('test', {'Eyedropper': [2, 3]}, anchor=anchor, path=self.path),
            lambda: PerformanceAutoTuner.save_tune_result({'version': 1}, self.path),
            lambda: ResourceScheduler.save_recommendation({'logical_cpus': 4, 'recommended_workers': 2,
                'ram_budget_mb': 512, 'best_score': 2, 'scores': []}, self.path),
        ]
        for save in savers:
            with self.subTest(save=save), patch('RuntimePaths.os.fsync', side_effect=OSError(errno.EIO, 'disk')):
                with self.assertRaises(OSError):
                    save()
            self.assertEqual(self.path.read_text(), 'old')
            self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_concurrent_tuner_saves_use_independent_staging_files(self):
        barrier = threading.Barrier(8)
        def save(number):
            barrier.wait(timeout=5)
            return PerformanceAutoTuner.save_tune_result({'version': 1, 'number': number,
                                                         'payload': list(range(200))}, self.path)
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            self.assertEqual(len(list(pool.map(save, range(8)))), 8)
        value = RuntimePaths.read_json(self.path)
        self.assertIn(value['number'], range(8))
        self.assertEqual(value['payload'], list(range(200)))
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_checksum_publish_preserves_previous_document_on_io_failure(self):
        artifact = self.root / 'app.zip'; artifact.write_bytes(b'artifact')
        self.path.write_text('previous checksums')
        with patch('RuntimePaths.os.replace', side_effect=OSError('sharing violation')):
            with self.assertRaises(OSError):
                ReleasePackage.write_checksum_file([artifact], self.path)
        self.assertEqual(self.path.read_text(), 'previous checksums')
        self.assertEqual(set(self.root.iterdir()), {artifact, self.path})

    def test_local_json_limits_reject_duplicate_nonfinite_and_nested_state(self):
        for content in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e309}', '[' * 40 + '0' + ']' * 40):
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                RuntimePaths.read_json(self.path)
        self.path.write_text('[0,1,2,3]')
        with self.assertRaises(ValueError):
            RuntimePaths.read_json(self.path, max_items=3)
        with self.assertRaises(ValueError):
            RuntimePaths.read_json(self.path, max_bytes=3)

    def test_json_reader_never_reads_more_than_limit_plus_one(self):
        import io
        class Stream(io.BytesIO):
            def read(self, size=-1):
                self.requested = size
                return super().read(size)
        stream = Stream(b' ' * 1000)
        with patch('RuntimePaths.Path.open', return_value=stream), self.assertRaises(ValueError):
            RuntimePaths.read_json(self.path, max_bytes=80)
        self.assertEqual(stream.requested, 81)

    def test_transaction_reentrancy_and_failure_release(self):
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            with RuntimePaths.file_transaction(self.path):
                with RuntimePaths.file_transaction(self.path):
                    raise RuntimeError('injected')
        increment_file(self.path, 1)
        self.assertEqual(RuntimePaths.read_json(self.path), 1)

    def test_transaction_rejects_invalid_timeout_before_creating_files(self):
        for timeout in (float('nan'), float('inf'), -1, True, 10**400):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                with RuntimePaths.file_transaction(self.path, timeout=timeout):
                    self.fail('Invalid duration acquired a lock')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unlock_failure_does_not_replace_original_operation_error(self):
        if os.name == 'nt':
            import msvcrt
            target = 'msvcrt.locking'; original = msvcrt.locking
            def injected(fd, mode, length):
                if mode == msvcrt.LK_UNLCK:
                    raise OSError('unlock failed')
                return original(fd, mode, length)
        else:
            import fcntl
            target = 'fcntl.flock'; original = fcntl.flock
            def injected(fd, mode):
                if mode == fcntl.LOCK_UN:
                    raise OSError('unlock failed')
                return original(fd, mode)
        with patch(target, injected), self.assertRaisesRegex(RuntimeError, 'original failure'):
            with RuntimePaths.file_transaction(self.path):
                raise RuntimeError('original failure')
        increment_file(self.path, 1)

    def test_transaction_timeout_does_not_break_owner(self):
        with RuntimePaths.file_transaction(self.path):
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                future = pool.submit(lambda: increment_with_timeout(self.path))
                self.assertTrue(future.result(timeout=3))
        increment_file(self.path, 1)

    def test_cross_process_transaction_preserves_every_increment(self):
        ctx = multiprocessing.get_context('spawn')
        processes = [ctx.Process(target=increment_file, args=(str(self.path), 6)) for _ in range(3)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(20)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(RuntimePaths.read_json(self.path), 18)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate(); process.join(5)

    def test_multilingual_profile_keys_fit_actual_filesystem_components(self):
        with patch('ProfileStorage.data_dir', return_value=self.root):
            paths = [ProfileStorage.profile_timing_file(character * 80) for character in ('漢', '𐐀', '界')]
            for path in paths:
                path.write_text('{}')
                self.assertLessEqual(len(path.name.encode('utf-8')), 255)
            self.assertEqual(len(set(paths)), 3)
            self.assertEqual(ProfileStorage.safe_profile_key('gartic-phone'), 'gartic-phone')

    def test_malformed_schema_returns_cold_learning_state(self):
        for version in (True, [], None, '1', 1.2):
            self.path.write_text(json.dumps({'version': version, 'profile_key': 'test', 'profiles': {}, 'contexts': {}, 'entries': []}))
            self.assertFalse(timing.correction_for({'profile_key': 'test'}, path=self.path)['learned'])
            self.assertEqual(feedback._load({'profile_key': 'test'}, self.path)[1]['contexts'], {})
            self.assertEqual(CorrectionHistory.load_correction_history({'profile_key': 'test'}, path=self.path)['entry_count'], 0)

    def test_release_state_oversize_falls_back_to_first_run(self):
        self.path.write_bytes(b' ' * 17000)
        with patch.object(ReleaseState, 'STATE_FILE', self.path):
            self.assertTrue(ReleaseState.should_show_welcome())

    def test_timing_corrupt_records_do_not_crash_estimator_or_prevent_relearning(self):
        options = {'profile_key': 'test'}
        for invalid in ({'samples': []}, {'samples': 5, 'ratio_ema': 'wrong'}, {'samples': 5, 'ratio_ema': 10**400},
                        {'samples': 5, 'ratio_ema': 1.2, 'operation_runtime_ema': []}):
            self.path.write_text(json.dumps({'version': 4, 'profiles': {timing._key(options): invalid}}))
            self.assertFalse(timing.correction_for(options, path=self.path)['learned'])
            self.assertEqual(timing.record_sample(options, 10, 12, path=self.path)['samples'], 1)

    def test_timing_concurrent_samples_and_failed_save_preserve_counts(self):
        options = {'profile_key': 'test'}
        barrier = threading.Barrier(8)
        def sample(_):
            barrier.wait(timeout=5)
            return timing.record_sample(options, 10, 12, path=self.path)
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(sample, range(8)))
        self.assertEqual(timing.correction_for(options, path=self.path)['samples'], 8)
        old = self.path.read_bytes()
        with patch('DrawTimeCalibration.atomic_write_text', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                timing.record_sample(options, 10, 12, path=self.path)
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(timing.record_sample(options, 10, 12, path=self.path)['samples'], 9)

    def test_timing_invalid_operation_values_are_not_persisted(self):
        result = timing.record_sample({'profile_key': 'test'}, 10, 12, path=self.path,
            operation_counts={'valid': 3, 'nan': float('nan'), 'fraction': 2.5},
            operation_runtime={'valid': {'count': 3, 'total_seconds': 1.5},
                'bad': {'count': 2, 'average_seconds': .3, 'last_average_seconds': 'bad'},
                'inf': {'count': 1, 'total_seconds': float('inf')}})
        self.assertEqual(result['last_operation_counts'], {'valid': 3})
        self.assertEqual(set(result['operation_runtime_ema']), {'valid'})
        self.assertEqual(result['operation_runtime_ema']['valid']['average_seconds'], .5)
        self.assertNotIn('NaN', self.path.read_text())

    def test_zero_error_history_is_preserved_in_timing_ema(self):
        options = {'profile_key': 'test'}
        timing.record_sample(options, 10, 10, path=self.path)
        second = timing.record_sample(options, 10, 20, path=self.path)
        self.assertAlmostEqual(second['mape_ema'], .5 * .42)

    def test_context_delimiters_cannot_merge_different_timing_or_feedback_policies(self):
        a = {'profile_key': 'test', 'mode': 'one|preset=two', 'render_preset': 'three'}
        b = {'profile_key': 'test', 'mode': 'one', 'render_preset': 'two|preset=three'}
        self.assertNotEqual(timing._key(a), timing._key(b))
        one = feedback._context_dimensions({}, 'a|budget=b', 'normal', 75)
        two = dict(one, source_kind='a', budget_class='b|budget=short-75-80')
        self.assertNotEqual(feedback._context_key(one), feedback._context_key(two))

    def test_invalid_snapshot_metric_uses_labeled_proxy_without_crash(self):
        for value in (None, float('nan'), float('inf'), 10**400, 101, {'pixels': [1]}):
            plan = feedback_plan(post={'available': True, 'trusted': True, 'feedback_trust': 'high',
                                       'visual_accuracy_percent': value})
            result = feedback.record_completed_feedback(plan, 11, completed_paths=10, path=self.path)
            self.assertEqual(result['result_source'], 'runtime delivery proxy')
            self.assertTrue(result['recorded'])

    def test_explicitly_untrusted_snapshot_cannot_override_delivery_proxy(self):
        for flag in (False, 'false', 0):
            plan = feedback_plan(post={'available': True, 'trusted': flag, 'feedback_trust': 'high',
                                       'visual_accuracy_percent': 99})
            result = feedback.record_completed_feedback(plan, 11, completed_paths=10, path=self.path)
            self.assertEqual(result['result_source'], 'runtime delivery proxy')

    def test_feedback_discards_corrupt_counters_and_bounds_context_database(self):
        plan = feedback_plan()
        first = feedback.record_completed_feedback(plan, 11, completed_paths=10, path=self.path)
        raw = RuntimePaths.read_json(self.path)
        raw['contexts'][first['context_key']]['samples'] = 'broken'
        self.path.write_text(json.dumps(raw))
        self.assertEqual(feedback.record_completed_feedback(plan, 11, completed_paths=10, path=self.path)['samples'], 1)
        with patch.object(feedback, 'MAX_CONTEXTS', 3):
            for number in range(6):
                feedback.record_completed_feedback(feedback_plan(str(number)), 11, completed_paths=10, path=self.path)
            stored = RuntimePaths.read_json(self.path)['contexts']
        self.assertEqual(len(stored), 3)
        self.assertEqual({item['strategy'] for item in stored.values()}, {'3', '4', '5'})

    def test_feedback_concurrent_updates_are_not_lost(self):
        barrier = threading.Barrier(6)
        def sample(_):
            barrier.wait(timeout=5)
            return feedback.record_completed_feedback(feedback_plan(), 11, completed_paths=10, path=self.path)
        with concurrent.futures.ThreadPoolExecutor(6) as pool:
            list(pool.map(sample, range(6)))
        self.assertEqual(next(iter(RuntimePaths.read_json(self.path)['contexts'].values()))['samples'], 6)

    def test_correction_zero_metrics_do_not_fall_back_to_positive_secondary_values(self):
        result = CorrectionHistory.compact_result_metrics({'visual_accuracy_percent': 0,
            'post_correction_visual_accuracy_percent': 90, 'actual_coverage_percent': 0,
            'post_correction_actual_coverage_percent': 99, 'confidence_percent': 0,
            'post_correction_confidence_percent': 85})
        self.assertEqual(result['visual_accuracy_percent'], 0)
        self.assertEqual(result['actual_coverage_percent'], 0)
        self.assertEqual(result['confidence_percent'], 0)

    def test_correction_concurrent_appends_are_not_lost(self):
        barrier = threading.Barrier(6)
        def record(number):
            barrier.wait(timeout=5)
            return CorrectionHistory.record_correction_history(feedback_plan(post={'available': False}),
                path=self.path, created_at=number + 1)
        with concurrent.futures.ThreadPoolExecutor(6) as pool:
            list(pool.map(record, range(6)))
        self.assertEqual(CorrectionHistory.load_correction_history({'profile_key': 'test'}, path=self.path)['entry_count'], 6)

    def test_transaction_sidecars_are_excluded_without_removing_shipped_fixtures(self):
        for name in ('auto-tuner-feedback-test.json.lock', 'draw-time-calibration-test.json.lock',
                     'verified-colors-microsoft-paint.json', 'verified-colors-microsoft-paint.json.lock'):
            self.assertTrue(ReleasePackage.is_forbidden_path(name))
            self.assertTrue(ReleasePackage.is_nonfatal_excluded_path(name))
            self.assertFalse(ReleasePackage.is_forbidden_path('docs/examples/' + name))
        self.assertFalse(ReleasePackage.is_forbidden_path('resource-scheduler-v2.json'))
        self.assertFalse(ReleasePackage.is_forbidden_path('tests/fixtures/verified-color-cache-v2.json'))

    def test_signing_link_preflight_stops_before_any_signature_is_changed(self):
        import CodeSigning
        target = self.root / 'outside.dll'; target.write_bytes(b'untouched')
        dist = self.root / 'dist'; dist.mkdir()
        (dist / 'ImageDrawBot.exe').write_bytes(b'app')
        try:
            (dist / 'linked.dll').symlink_to(target)
        except OSError as error:
            self.skipTest(f'Symbolic links are unavailable: {error}')
        with patch('CodeSigning.sign_file') as sign, patch('CodeSigning.verify') as verify:
            with self.assertRaises(CodeSigning.SigningError):
                CodeSigning.sign_distribution(dist, ('tool', 'AA' * 20))
        sign.assert_not_called(); verify.assert_not_called()
        self.assertEqual(target.read_bytes(), b'untouched')


def increment_with_timeout(path):
    try:
        with RuntimePaths.file_transaction(path, timeout=.03):
            return False
    except TimeoutError:
        return True


class CalibrationSafetyTests(unittest.TestCase):
    def data(self):
        return {'version': 2, 'profile': 'test', 'anchor': make_anchor((0, 0, 800, 600)),
                'controls': {'OpenCustomColor': [1, 2], 'ConfirmColor': [3, 4],
                             'RedField': [10, 20], 'GreenField': [30, 20], 'BlueField': [50, 20]}}

    def test_exact_control_schema_and_container_errors_are_controlled(self):
        for bad in (True, 1.9, None, '2', []):
            data = self.data(); data['version'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ExactColorTools.validate(data, 'test')
        for bad in ([], None, 'controls'):
            data = self.data(); data['controls'] = bad
            with self.assertRaises(ValueError):
                ExactColorTools.validate(data, 'test')
        data = {'version': True, 'profile': 'test', 'anchor': self.data()['anchor'], 'tools': {}}
        with self.assertRaises(ValueError):
            AppTools.validate_calibration(data)

    def test_exact_control_coordinates_and_usable_spectrum_geometry(self):
        for updates in ({'RedField': [10**12, 0]},
                        {'SpectrumTopLeft': [20, 20], 'SpectrumBottomRight': [20, 80]},
                        {'SpectrumTopLeft': [20, 20], 'SpectrumBottomRight': [10, 80]},
                        {'BrightnessTop': [10, 10], 'BrightnessBottom': [10, 10]}):
            data = self.data(); data['controls'].update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                ExactColorTools.validate(data, 'test')
        data = self.data(); data['controls'].update(BrightnessTop=[-20, 10], BrightnessBottom=[20, 10])
        self.assertIn('BrightnessTop', ExactColorTools.validate(data, 'test')['controls'])

    def test_custom_color_availability_reads_one_consistent_snapshot(self):
        with patch('ExactColorTools.load', return_value=self.data()) as load:
            self.assertTrue(ExactColorTools.custom_rgb_available('test'))
        self.assertEqual(load.call_count, 1)

    def test_health_invalid_evidence_cannot_become_verified(self):
        summary = {'palette': {'state': 'verified', 'available': True, 'count': 12,
                               'verification': {'confidence': .98}}}
        self.assertFalse(CalibrationHealth.summarize_calibration_health(summary).blocking)
        for invalid in (float('nan'), float('inf'), 10**400, -1, 'bad', []):
            changed = copy.deepcopy(summary)
            changed['palette']['verification']['confidence'] = invalid
            result = CalibrationHealth.summarize_calibration_health(changed)
            self.assertTrue(result.blocking)
            self.assertEqual(result.component_confidence['palette'], 0)
        summary['palette']['available'] = False
        self.assertTrue(CalibrationHealth.summarize_calibration_health(summary).blocking)

    def test_health_score_failure_is_reported_as_blocking(self):
        import CalibrationState
        with patch.object(CalibrationState, 'palette_state', return_value={}), \
             patch.object(CalibrationState, 'tool_state', return_value={}), \
             patch.object(CalibrationState, 'exact_color_state', return_value={}), \
             patch.object(CalibrationState, 'timing_state', return_value={}), \
             patch.object(CalibrationHealth, 'summarize_calibration_health', side_effect=ValueError('bad evidence')):
            result = CalibrationState.profile_calibration_summary('test', context_fingerprint='test')
        self.assertTrue(result['health']['blocking'])

    def test_trusted_completed_draw_requires_finite_score_and_coverage(self):
        valid = {'available': True, 'trusted': True, 'visual_accuracy_percent': 90, 'actual_coverage_percent': 98}
        self.assertTrue(CompletedDrawLearning.timing_sample_gate({'post_draw_accuracy_meta': valid},
                        completed_paths=10, planned_paths=10)['allowed'])
        for field, value in (('trusted', 'false'), ('available', 0), ('visual_accuracy_percent', None),
                             ('visual_accuracy_percent', float('nan')), ('actual_coverage_percent', 101),
                             ('actual_coverage_percent', True)):
            changed = dict(valid); changed[field] = value
            self.assertFalse(CompletedDrawLearning.timing_sample_gate({'post_draw_accuracy_meta': changed},
                             completed_paths=10, planned_paths=10)['allowed'])
        self.assertEqual(CompletedDrawLearning.timing_sample_gate({}, completed_paths=10, planned_paths=10)['confidence'], 'execution-only')


if __name__ == '__main__':
    unittest.main()
