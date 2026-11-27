import json
import tempfile
import unittest
from pathlib import Path

from CorrectionHistory import (
    build_history_entry,
    contains_image_data,
    format_correction_history,
    load_correction_history,
    record_correction_history,
    reset_profile_history,
)
from CorrectionReviewRecovery import build_correction_review_state, format_correction_review
from PreviewDiagnostics import build_preview_diagnostics, format_preview_diagnostics


def base_plan(**updates):
    options = {
        'profile_key': 'microsoft-paint',
        'profile_name': 'Microsoft Paint',
        'paint_tool': 'Pencil',
        'brush_px': 1,
        'custom_color_workflow': 'Adaptive exact',
        'auto_tuner_meta': {
            'active': True,
            'renderer': 'Extra Fast 2.0',
            'selected_strategy': 'deadline-hybrid',
            'usable_budget_seconds': 80.0,
            'acceptance_gates': {'visual_accuracy_min_percent': 76.0},
        },
        'auto_tuner_acceptance_meta': {
            'usable_deadline_seconds': 72.0,
            'gates': {'visual_accuracy_min_percent': 76.0},
        },
        'post_draw_before_correction_accuracy_meta': {
            'available': True,
            'trusted': True,
            'feedback_trust': 'high',
            'confidence_percent': 91.0,
            'visual_accuracy_percent': 71.5,
            'source_pixel_accuracy_percent': 73.0,
            'perceptual_color_accuracy_percent': 70.0,
            'actual_coverage_percent': 84.0,
            'actual_vs_simulated_visual_percent': 88.0,
        },
        'post_draw_accuracy_meta': {
            'available': True,
            'trusted': True,
            'feedback_trust': 'high',
            'confidence_percent': 93.0,
            'visual_accuracy_percent': 82.0,
            'source_pixel_accuracy_percent': 83.0,
            'perceptual_color_accuracy_percent': 80.0,
            'actual_coverage_percent': 96.0,
            'actual_vs_simulated_visual_percent': 91.0,
        },
        'post_draw_correction_meta': {
            'enabled': True,
            'safe': True,
            'reason': 'Visual Accuracy below gate',
            'correction_paths': 20,
            'executed_paths': 18,
            'executed_colors': 2,
            'selected_correction_pixels': 360,
            'missing_pixels': 120,
            'wrong_color_pixels': 240,
            'post_correction_visual_accuracy_percent': 82.0,
            'post_correction_actual_coverage_percent': 96.0,
            'post_correction_trust': 'high',
            'post_correction_confidence_percent': 93.0,
            'stores_image_data': False,
        },
    }
    options.update(updates)
    return {'count': 180, 'options': options}


class Step16CorrectionHistoryTests(unittest.TestCase):
    def test_budget_history_distinguishes_planned_gain_from_measured_outcome(self):
        plan = base_plan()
        corr = plan['options']['post_draw_correction_meta']
        corr.update(budget_seconds=5, estimated_seconds=3.25, execution_seconds=4.5,
                    predicted_error_reduction_percent=27.5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            self.assertTrue(record_correction_history(plan, path=path)['recorded'])
            history = load_correction_history(plan['options'], path=path)
        row = history['entries'][0]
        self.assertEqual(row['execution_seconds'], 4.5)
        self.assertEqual(row['estimated_seconds'], 3.25)
        self.assertEqual(row['visual_accuracy_delta'], 10.5)
        text = format_correction_history(history)
        self.assertIn('correction budget 5s', text)
        self.assertIn('input 4.50s', text)
        self.assertIn('predicted candidate error reduction 27.5%', text)

        del corr['post_correction_visual_accuracy_percent'], corr['post_correction_actual_coverage_percent']
        for executed in (0, 1):
            corr['executed_paths'] = executed
            entry = build_history_entry(plan)
            self.assertEqual(entry['after'], {})
            self.assertNotIn('visual_accuracy_delta', entry['delta'])

    def test_build_entry_contains_before_after_delta_without_image_data(self):
        entry = build_history_entry(base_plan(), actual_seconds=63.2, created_at=123.0)
        self.assertEqual(entry['state'], 'corrected-partial')
        self.assertEqual(entry['before']['visual_accuracy_percent'], 71.5)
        self.assertEqual(entry['after']['visual_accuracy_percent'], 82.0)
        self.assertAlmostEqual(entry['delta']['visual_accuracy_delta'], 10.5)
        self.assertAlmostEqual(entry['delta']['actual_coverage_delta'], 12.0)
        self.assertFalse(entry['stores_image_data'])
        self.assertFalse(contains_image_data(entry))
        payload = json.dumps(entry).lower()
        self.assertNotIn('screenshot', payload)
        self.assertNotIn('thumbnail', payload)
        self.assertNotIn('raw_pixels', payload)
        self.assertNotIn('image_bytes', payload)

    def test_record_and_load_profile_isolated_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'correction-history-microsoft-paint.json'
            result = record_correction_history(base_plan(), actual_seconds=63.2, path=path, created_at=123.0)
            self.assertTrue(result['recorded'])
            loaded = load_correction_history(base_plan()['options'], path=path, limit=5)
            self.assertEqual(loaded['entry_count'], 1)
            self.assertEqual(loaded['entries'][0]['before_visual_accuracy_percent'], 71.5)
            self.assertEqual(loaded['entries'][0]['after_visual_accuracy_percent'], 82.0)
            self.assertIn('Visual 71.5% → 82.0%', format_correction_history(loaded))
            other = base_plan(profile_key='gartic-phone')
            loaded_other = load_correction_history(other['options'], path=Path(tmp) / 'correction-history-gartic-phone.json')
            self.assertEqual(loaded_other['entry_count'], 0)

    def test_bounded_history_keeps_latest_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            for i in range(35):
                plan = base_plan()
                plan['options']['post_draw_before_correction_accuracy_meta']['visual_accuracy_percent'] = 60.0 + i
                plan['options']['post_draw_correction_meta']['post_correction_visual_accuracy_percent'] = 61.0 + i
                record_correction_history(plan, actual_seconds=20 + i, path=path, created_at=1000 + i)
            loaded = load_correction_history(base_plan()['options'], path=path, limit=40)
            self.assertEqual(loaded['entry_count'], 30)
            self.assertEqual(loaded['entries'][0]['before_visual_accuracy_percent'], 65.0)

    def test_review_and_preview_include_history_summary(self):
        plan = base_plan()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            recorded = record_correction_history(plan, actual_seconds=63.2, path=path, created_at=123.0)
            plan['options']['correction_history_meta'] = load_correction_history(plan['options'], path=path, limit=3)
            state = build_correction_review_state(plan['options'])
            text = format_correction_review(state)
            self.assertIn('History:', text)
            self.assertIn('saved', text)
            meta = build_preview_diagnostics(plan['options'])
            meta['correction_history'] = plan['options']['correction_history_meta']
            preview_text = format_preview_diagnostics(meta)
            self.assertIn('Correction History:', preview_text)
            self.assertTrue(recorded['recorded'])

    def test_skips_dry_run_and_blocks_unsafe_keys(self):
        plan = base_plan(dry_run_sampled=True)
        with tempfile.TemporaryDirectory() as tmp:
            result = record_correction_history(plan, path=Path(tmp) / 'history.json')
            self.assertFalse(result['recorded'])
        self.assertFalse(contains_image_data({'source_pixel_accuracy_percent': 99.0, 'selected_correction_pixels': 10}))
        self.assertTrue(contains_image_data({'screenshot': 'blocked'}))
        self.assertTrue(contains_image_data({'image_hash': 'blocked'}))

    def test_release_build_collects_step16_module_and_doc(self):
        source = Path('build_exe.py').read_text(encoding='utf-8')
        self.assertIn("'--hidden-import', 'CorrectionHistory'", source)
        self.assertIn('STEP-16-CORRECTION-HISTORY-BEFORE-AFTER.md', source)
        self.assertTrue(Path('STEP-16-CORRECTION-HISTORY-BEFORE-AFTER.md').is_file())


if __name__ == '__main__':
    unittest.main()
