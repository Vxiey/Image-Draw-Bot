import json
import unittest
from pathlib import Path

from CorrectionReviewRecovery import (
    build_correction_review_state,
    contains_image_data,
    format_correction_review,
)
from PreviewDiagnostics import build_preview_diagnostics, format_preview_diagnostics


def trusted_post(**updates):
    meta = {
        'available': True,
        'trusted': True,
        'feedback_trust': 'high',
        'scoring_state': 'scored',
        'confidence_percent': 92.0,
        'visual_accuracy_percent': 78.0,
        'source_pixel_accuracy_percent': 80.0,
        'perceptual_color_accuracy_percent': 76.0,
        'actual_coverage_percent': 98.0,
        'actual_vs_simulated_visual_percent': 91.0,
        'unexpected_ink_percent': 0.0,
        'blank_canvas': False,
    }
    meta.update(updates)
    return meta


def gates(min_visual=76.0):
    return {'auto_tuner_acceptance_meta': {'gates': {'visual_accuracy_min_percent': float(min_visual)}}}


class Step15CorrectionReviewRecoveryTests(unittest.TestCase):
    def test_review_labels_estimate_separately_from_observed_result(self):
        options = {'post_draw_accuracy_meta': trusted_post(), 'post_draw_correction_meta': {
            'enabled': True, 'safe': True, 'selection_policy': 'quality_gain_per_second',
            'predicted_error_reduction_percent': 22.35, 'estimated_seconds': 3.2,
            'execution_seconds': 2.6, 'budget_seconds': 5, 'executed_paths': 2, 'correction_paths': 2}}
        review = format_correction_review(build_correction_review_state(options))
        self.assertIn('less color error in correctable pixels · 3.2 s', review)
        self.assertIn('execution 2.6 s', review)
        del options['post_draw_correction_meta']['predicted_error_reduction_percent']
        self.assertNotIn('Plan estimate', format_correction_review(build_correction_review_state(options)))

    def test_no_completed_result_is_safe_and_disabled(self):
        state = build_correction_review_state({}, can_snapshot=True, strict_safety_ready=True, full_start_unlocked=True)
        self.assertEqual(state['state'], 'no_result')
        self.assertFalse(state['actions']['retry_correction_only']['enabled'])
        self.assertFalse(state['stores_image_data'])
        self.assertFalse(contains_image_data(state))
        self.assertIn('No completed real drawing', format_correction_review(state))

    def test_completed_correction_pass_summarizes_without_image_data(self):
        opts = gates()
        opts.update({
            'post_draw_accuracy_meta': trusted_post(visual_accuracy_percent=80.0, actual_coverage_percent=98.5),
            'post_draw_correction_meta': {
                'enabled': True,
                'safe': True,
                'reason': 'post-draw correction completed',
                'correction_paths': 10,
                'executed_paths': 10,
                'selected_correction_pixels': 220,
                'corrected_colors': 2,
                'post_correction_visual_accuracy_percent': 84.0,
                'post_correction_actual_coverage_percent': 99.0,
                'post_correction_trust': 'high',
                'stores_image_data': False,
            },
        })
        state = build_correction_review_state(opts, can_snapshot=True, strict_safety_ready=True, full_start_unlocked=True)
        self.assertEqual(state['state'], 'corrected_pass')
        self.assertFalse(state['actions']['retry_correction_only']['enabled'])
        self.assertTrue(state['actions']['retry_full_drawing']['enabled'])
        text = format_correction_review(state)
        self.assertIn('Correction completed', text)
        self.assertIn('paths 10/10', text)
        self.assertIn('post Visual 84.0%', text)
        self.assertFalse(contains_image_data(state))
        payload = json.dumps(state).lower()
        self.assertNotIn('screenshot', payload)
        self.assertNotIn('thumbnail', payload)
        self.assertNotIn('crop', payload)
        self.assertNotIn('raw_pixels', payload)
        self.assertNotIn('pixel_array', payload)

    def test_partial_correction_requires_safety_chain_and_unlock(self):
        opts = gates(82.0)
        opts.update({
            'post_draw_accuracy_meta': trusted_post(visual_accuracy_percent=72.0, actual_coverage_percent=92.0),
            'post_draw_correction_meta': {
                'enabled': True,
                'safe': True,
                'reason': 'bounded by deadline reserve',
                'correction_paths': 20,
                'executed_paths': 5,
                'selected_correction_pixels': 450,
                'stopped_early': True,
                'stores_image_data': False,
            },
        })
        locked = build_correction_review_state(opts, can_snapshot=True, strict_safety_ready=False, full_start_unlocked=False)
        self.assertEqual(locked['state'], 'corrected_partial')
        self.assertFalse(locked['actions']['retry_correction_only']['enabled'])
        self.assertIn('safety chain', locked['actions']['retry_correction_only']['reason'])
        ready = build_correction_review_state(opts, can_snapshot=True, strict_safety_ready=True, full_start_unlocked=True)
        self.assertTrue(ready['actions']['retry_correction_only']['enabled'])
        self.assertTrue(ready['actions']['retry_correction_only']['native_input'])
        self.assertTrue(ready['actions']['retry_correction_only']['requires_safety_chain'])

    def test_low_trust_or_unexpected_ink_blocks_correction_only(self):
        opts = gates()
        opts['post_draw_accuracy_meta'] = trusted_post(feedback_trust='low', trusted=False)
        state = build_correction_review_state(opts, can_snapshot=True, strict_safety_ready=True, full_start_unlocked=True)
        self.assertEqual(state['state'], 'manual_review_required')
        self.assertFalse(state['actions']['retry_correction_only']['enabled'])
        opts['post_draw_accuracy_meta'] = trusted_post(unexpected_ink_percent=45.0)
        state2 = build_correction_review_state(opts, can_snapshot=True, strict_safety_ready=True, full_start_unlocked=True)
        self.assertEqual(state2['state'], 'manual_review_required')
        self.assertFalse(state2['actions']['retry_correction_only']['enabled'])

    def test_preview_diagnostics_includes_review_line(self):
        opts = gates(82.0)
        opts.update({
            'post_draw_accuracy_meta': trusted_post(visual_accuracy_percent=70.0, actual_coverage_percent=91.0),
            'post_draw_correction_meta': {
                'enabled': False,
                'safe': True,
                'reason': 'not enough deadline headroom for correction pass',
                'stores_image_data': False,
            },
        })
        meta = build_preview_diagnostics(opts)
        self.assertIn('correction_review', meta)
        text = format_preview_diagnostics(meta)
        self.assertIn('Correction Review:', text)
        self.assertIn('Correction skipped', text)

    def test_release_build_collects_step15_module_and_doc(self):
        source = Path('build_exe.py').read_text(encoding='utf-8')
        self.assertIn("'--hidden-import', 'CorrectionReviewRecovery'", source)
        self.assertIn('STEP-15-CORRECTION-REVIEW-RECOVERY-UI.md', source)
        self.assertTrue(Path('STEP-15-CORRECTION-REVIEW-RECOVERY-UI.md').is_file())

    def test_image_data_detector_allows_counts_but_blocks_artifacts(self):
        self.assertFalse(contains_image_data({'selected_correction_pixels': 42, 'actual_coverage_percent': 99.0}))
        self.assertTrue(contains_image_data({'safe': False, 'screenshot': 'not allowed'}))
        self.assertTrue(contains_image_data({'raw_pixels': [[1, 2, 3]]}))


if __name__ == '__main__':
    unittest.main()
