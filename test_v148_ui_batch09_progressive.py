"""Renderer metadata, rather than unrelated default zeros, describes the plan."""
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot
import test_v148_ui_batch07_renderer as renderer_fixtures
from test_v148_ui_profiles_batch04 import studio_state_renderer


def summary_from_actual_workspace(plan):
    _app, scope = studio_state_renderer(plan=plan)
    scope['_apply_ui_state']()
    return scope['plan_metrics'].configure.call_args.kwargs['text']


class NoUiSequenceScan:
    def __iter__(self):
        raise AssertionError('The UI summary must not rescan execution geometry.')


class ActualPlanSummaryTests(unittest.TestCase):
    def plan_summary(self, *, pixel=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch('RuntimePaths.source_dir', return_value=Path(directory)))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
            app = renderer_fixtures.AdvertisedRendererTests().app()
            if pixel:
                app.render_style.set('Auto')
                app.draw_quality.set('Pixel Accurate')
                app.brush_px.set('1')
            source = Image.new('RGB', (40, 32), 'white')
            ImageDraw.Draw(source).rectangle((7, 6, 32, 25), fill=(220, 30, 30),
                                            outline='black', width=2)
            plan = None
            try:
                plan = DrawBot.make_plan(source, source.size, DrawBot.DrawBotApp.options(app))
                stats = dict(plan['path_stats'])
                phases = Counter(entry['phase'] for entry in plan['execution_sequence'])
                plan['execution_sequence'] = NoUiSequenceScan()
                return stats, phases, summary_from_actual_workspace(plan)
            finally:
                renderer_fixtures.close_images(plan)
                source.close()

    def test_real_sketch_fill_plan_reports_its_three_actual_passes(self):
        stats, phases, summary = self.plan_summary()
        self.assertEqual(set(phases), {'sketch', 'color_fill', 'reoutline'})
        expected = (f"Progressive: {phases['sketch']:,} sketch → "
                    f"{phases['color_fill']:,} color fill → {phases['reoutline']:,} re-outline")
        self.assertIn(expected, summary)
        self.assertEqual(stats['progressive_sketch_paths'], phases['sketch'])
        self.assertNotIn('forms →', summary)

    def test_real_pixel_accurate_plan_reports_fill_detail_and_cleanup_passes(self):
        stats, phases, summary = self.plan_summary(pixel=True)
        self.assertTrue(stats['progressive_enabled'])
        self.assertTrue(phases)
        self.assertIn('cleanup', phases)
        expected = 'Progressive: ' + ' → '.join(
            f"{stats[key]:,} {label}" for key, label in (
                ('progressive_fill_paths', 'fill'),
                ('progressive_mid_detail_paths', 'mid detail'),
                ('progressive_fine_detail_paths', 'fine detail'),
                ('progressive_cleanup_paths', 'cleanup')))
        self.assertIn(expected, summary)
        self.assertNotIn('forms →', summary)


class MetadataSummaryTests(unittest.TestCase):
    def summary(self, **stats):
        from ProgressiveSummary import progressive_summary
        return progressive_summary({'progressive_enabled': True, **stats})

    def test_legacy_and_hybrid_counts_keep_their_distinct_labels(self):
        counts = dict(progressive_foundation_paths=1200, progressive_contour_paths=4,
                      progressive_detail_paths=2)
        self.assertEqual(self.summary(progressive_mode='Auto', **counts),
                         'Progressive: 1,200 forms → 4 contours → 2 details')
        self.assertEqual(self.summary(progressive_mode='Adaptive Region Hybrid',
                                      progressive_correction_paths=0, **counts),
                         'Progressive: 1,200 foundation → 4 structure → 2 detail → 0 correction')

    def test_deadline_uses_the_whole_declared_order_without_invented_counts(self):
        summary = self.summary(progressive_mode='Deadline', progressive_foundation_paths=4,
            progressive_contour_paths=2, progressive_detail_paths=1,
            progressive_phase_order='major coverage -> structure -> important details -> accuracy -> correction')
        self.assertEqual(summary,
            'Progressive: major coverage → structure → important details → accuracy → correction')
        self.assertNotIn('0 ', summary)

    def test_pixel_correction_order_is_not_silently_truncated_to_four_passes(self):
        summary = self.summary(progressive_mode='On', progressive_fill_paths=5,
            progressive_mid_detail_paths=3, progressive_fine_detail_paths=2,
            progressive_cleanup_paths=1,
            progressive_phase_order='fill -> mid detail -> fine detail -> cleanup -> correction 1')
        self.assertEqual(summary,
            'Progressive: fill → mid detail → fine detail → cleanup → correction 1')

    def test_incomplete_or_invalid_counts_fall_back_to_declared_order(self):
        for value in (None, -1, True, '2', 1.5):
            with self.subTest(value=value):
                self.assertEqual(self.summary(progressive_mode='Sketch Fill',
                    progressive_sketch_paths=value, progressive_color_fill_paths=2,
                    progressive_reoutline_paths=1,
                    progressive_phase_order='Sketch -> Color Fill -> Re-outline'),
                    'Progressive: Sketch → Color Fill → Re-outline')
        self.assertEqual(self.summary(progressive_mode='Sketch Fill'), '')
        self.assertEqual(self.summary(progressive_mode='Future renderer',
            progressive_foundation_paths=1, progressive_contour_paths=2,
            progressive_detail_paths=3, progressive_phase_order='coverage -> edges'),
            'Progressive: coverage → edges')

    def test_disabled_or_missing_metadata_has_no_progressive_claim(self):
        from ProgressiveSummary import progressive_summary
        for stats in (None, {}, {'progressive_enabled': False,
                                'progressive_phase_order': 'one -> two'}):
            with self.subTest(stats=stats):
                self.assertEqual(progressive_summary(stats), '')


if __name__ == '__main__':
    unittest.main()
