import json
import math
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import CompletedDrawingAnalysis as completed
import RuntimePaths
import RuntimeSafetyReport as safety


class RuntimeReportsBatch02Tests(unittest.TestCase):
    def test_same_timestamp_sessions_publish_distinct_report_pairs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(safety, '_stamp', return_value='same-time'):
            first = safety.RuntimeSafetySession().save(Path(tmp))
            second = safety.RuntimeSafetySession().save(Path(tmp))
            self.assertNotEqual(first['json_path'], second['json_path'])
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 2)
            self.assertEqual(len(list(Path(tmp).glob('*.txt'))), 2)

    def test_concurrent_repeated_save_is_idempotent_and_returns_detached_payload(self):
        session = safety.RuntimeSafetySession()
        with tempfile.TemporaryDirectory() as tmp:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: session.save(Path(tmp)), range(8)))
            self.assertEqual(len({row['json_path'] for row in results}), 1)
            self.assertEqual(len({row['finished_utc'] for row in results}), 1)
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 1)
            results[0]['counts']['drawn'] = 123
            self.assertEqual(session.save(Path(tmp))['counts']['drawn'], 0)

    def test_report_text_publish_failure_rolls_back_json(self):
        replace = RuntimePaths._replace_with_retry
        failed = [False]
        def fail_text(source, target):
            if str(source).endswith('.import') and str(target).endswith('.txt') and not failed[0]:
                failed[0] = True; raise PermissionError('text locked')
            return replace(source, target)
        session = safety.RuntimeSafetySession()
        with tempfile.TemporaryDirectory() as tmp, patch.object(RuntimePaths, '_replace_with_retry', side_effect=fail_text):
            result = safety.safe_save(session, Path(tmp))
            self.assertIn('save_error', result)
            self.assertFalse(session._saved)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_latest_report_skips_oversized_and_invalid_counters(self):
        valid = {'schema': 1, 'mode': 'drawing', 'completed': True, 'counts': {'drawn': 2}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, payload in enumerate((valid, {**valid, 'counts': {'drawn': 'NaN'}}, {**valid, 'completed': 'false'})):
                path = root / f'ImageDrawBot-Safety-{index}.json'
                path.write_text(json.dumps(payload), encoding='utf-8'); os.utime(path, (index+1, index+1))
            large = root / 'ImageDrawBot-Safety-oversized.json'
            large.write_text(json.dumps({**valid, 'padding': 'x'*(600*1024)}), encoding='utf-8')
            result = safety.latest_report(root)
            self.assertEqual(result['counts']['drawn'], 2)
            self.assertTrue(result['json_path'].endswith('Safety-0.json'))
            self.assertNotIn('PASS', safety.compact_summary({**valid, 'completed': 'false'}))

    def test_secondary_serialization_failure_preserves_fill_evidence(self):
        session = safety.RuntimeSafetySession(planned_paths='invalid')
        session.counts['drawn'] = 3; session.fill_counts['better_fill_completed'] = 2
        with tempfile.TemporaryDirectory() as tmp:
            result = safety.safe_save(session, Path(tmp))
        self.assertIn('save_error', result)
        self.assertEqual(result['counts']['drawn'], 3)
        self.assertEqual(result['fills']['better_fill_completed'], 2)


class CompletedReportsBatch02Tests(unittest.TestCase):
    def test_unknown_prediction_stays_unavailable(self):
        result = completed.build_completed_drawing_report({'options': {}, 'estimate': math.nan}, 10)
        for key in ('predicted_seconds', 'eta_error_seconds', 'eta_error_percent_of_actual', 'efficiency_score_0_100'):
            self.assertIsNone(result[key])
        self.assertNotIn('eta_model', {row['code'] for row in result['recommendations']})

    def test_missing_or_contradictory_quality_does_not_recommend_more_speed(self):
        for post in ({}, {'available': True, 'trusted': False, 'feedback_trust': 'high',
                          'visual_accuracy_percent': 99, 'actual_coverage_percent': 100},
                     {'available': True, 'trusted': True, 'feedback_trust': 'high', 'visual_accuracy_percent': 99}):
            options = {'post_draw_accuracy_meta': post,
                       'adaptive_brush_meta': {'image_brush_demand': {'classification': 'flat-shape'}}}
            result = completed.build_completed_drawing_report({'options': options, 'estimate': 20}, 20)
            codes = {row['code'] for row in result['recommendations']}
            self.assertIn('verify_result', codes)
            self.assertNotIn('safe_speed_headroom', codes)
            self.assertNotIn('safe_fill_opportunity', codes)
            if not result['accuracy'].get('trusted'):
                self.assertIsNone(result['efficiency_score_0_100'])

    def test_completed_evidence_requires_real_positive_elapsed_and_integer_count(self):
        for elapsed in (math.nan, math.inf, -1, 0, True, 10**400):
            with self.subTest(elapsed=str(elapsed)[:12]), self.assertRaises(ValueError):
                completed.build_completed_drawing_report({}, elapsed)
        for count in (-1, True, 2.5):
            with self.assertRaises(ValueError):
                completed.build_completed_drawing_report({}, 10, completed_paths=count)

    def test_history_is_size_bounded_and_schema_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            valid = {'version': 1, 'actual_seconds': 1}
            path.write_text(json.dumps([valid, {'version': True, 'actual_seconds': 2},
                                        {'version': 1, 'actual_seconds': -3}, {}]), encoding='utf-8')
            self.assertEqual(completed._load_history(path), [valid])
            path.write_text(json.dumps([{**valid, 'padding': 'x'*(3*1024*1024)}]), encoding='utf-8')
            self.assertEqual(completed._load_history(path), [])

    def test_concurrent_completions_do_not_lose_history_rows(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(completed, '_report_dir', return_value=Path(tmp)):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda seconds: completed.record_completed_drawing({'options': {}}, seconds), range(1, 9)))
            rows = json.loads((Path(tmp) / 'history.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(row['actual_seconds'] for row in rows), list(range(1, 9)))
            latest = json.loads((Path(tmp) / 'latest.json').read_text(encoding='utf-8'))
            self.assertEqual(latest, rows[-1])

    def test_history_publish_failure_restores_all_old_report_files(self):
        replace = RuntimePaths._replace_with_retry; failed = [False]
        def fail_history(source, target):
            if str(source).endswith('.import') and Path(target).name == 'history.json' and not failed[0]:
                failed[0] = True; raise PermissionError('history locked')
            return replace(source, target)
        with tempfile.TemporaryDirectory() as tmp, patch.object(completed, '_report_dir', return_value=Path(tmp)):
            plan = {'options': {}}
            completed.record_completed_drawing(plan, 5)
            old_meta = plan['options']['completed_drawing_analysis_meta']
            names = ('latest.json', 'latest.txt', 'history.json')
            before = {name: (Path(tmp) / name).read_bytes() for name in names}
            with patch.object(RuntimePaths, '_replace_with_retry', side_effect=fail_history):
                with self.assertRaises(OSError):completed.record_completed_drawing(plan, 7)
            self.assertEqual({name: (Path(tmp) / name).read_bytes() for name in names}, before)
            self.assertIs(plan['options']['completed_drawing_analysis_meta'], old_meta)
            self.assertFalse(list(Path(tmp).glob('*.backup')))
            self.assertFalse(list(Path(tmp).glob('*.import')))


if __name__ == '__main__':
    unittest.main()
