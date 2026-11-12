"""Actual-source Fill batches and late Detail Zoom use affordable delivery."""
from contextlib import ExitStack, closing, contextmanager
import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveRegionHybrid as hybrid
import Colors
import DetailZoomPass as zoom
import DrawBot
from ExecutionCostModel import build_cost_model
import ExtraFast
from FillOptimizer import detect_fill_regions
from NativeBrushProjection import NativeBrushProjection
import RegionFillEngine as fill
from test_drawbot import NoWait
from test_v148_rendering_batch08_fill import fill_options
from test_v148_rendering_batch25_native_fill import NumericFillMouse
from test_v148_rendering_batch38_prepared_paths import close_plan
from test_v148_rendering_batch42_fidelity import standard_options


ROOT = Path(__file__).resolve().parent


@contextmanager
def fill_source():
    with Image.open(ROOT / 'golden-regression/dominant-hue-four-color.png') as original, \
            original.resize((192, 128), Image.Resampling.NEAREST) as source:
        yield source


def calibrated_fill_options(**changes):
    result = fill_options(draw_quality='Balanced', speed='Balanced', delay=.025,
        background_fill='Aggressive', adaptive_detail='Off', background_simplification='Off',
        fill_aggressiveness='Aggressive', cpu_workers='1', cpu_workers_resolved=1,
        resource_scheduler='Off', _preview_plan=False,
        _execution_cost_calibration_override={'samples':3, 'ratio':1.,
            'operation_runtime':{'tool_change':{'average_seconds':1.}}})
    result.update(changes)
    return result


def zoom_options(mode, **changes):
    result = standard_options(draw_quality='Maximum likeness', adaptive_detail='Off',
        detail_zoom=mode, time_budget_mode='Custom', unlimited_time=False,
        max_seconds=15, manual_max_seconds=15, delay=.02, adaptive_deadline_renderer=True,
        adaptive_color_verification=False, strict_color_verification=False, _preview_plan=False,
        _execution_cost_calibration_override={'samples':3, 'ratio':1.,
            'operation_runtime':{'dot':{'average_seconds':.4}}})
    result.update(changes)
    return result


class PaletteOwner(unittest.TestCase):
    def setUp(self):
        self.previous = list(Colors.allColors)
        Colors.reset_palette()

    def tearDown(self):
        Colors.allColors[:] = self.previous
        from PixelData import closest_color
        closest_color.cache_clear()


class FillBatchAdmissionTests(PaletteOwner):
    def candidates(self, source):
        regions, metadata = detect_fill_regions(source, 'Aggressive', engine='Closed regions v2',
            return_meta=True, safe_margin_px=1)
        return [region.as_dict() for region in regions], metadata

    def test_complete_learned_switch_is_removed_before_actual_batch_controls_are_added(self):
        with fill_source() as source:
            candidates, _ = self.candidates(source)
            self.assertTrue(candidates)
            options = calibrated_fill_options(_execution_cost_calibration_override={'samples':3,
                'ratio':1., 'operation_runtime':{'tool_change':{'average_seconds':5.}}})
            model = build_cost_model(options, source.size, source.size)
            _stroke, total, core, share = fill._region_cost_components(candidates[0], options,
                source.size, source.size, cost_model=model)
            self.assertGreater(share, total * .5)
            self.assertEqual(share, 5.)
            self.assertAlmostEqual(core + share, total)
            self.assertEqual(fill.fill_tool_batch_cost(options, cost_model=model), 10.)
            preview = dict(options, fill_tool_actions=[], fill_restore_actions=[])
            self.assertEqual(fill.fill_tool_batch_cost(preview, cost_model=model), 10.)

    def test_actual_detected_batch_falls_back_when_two_controls_erase_the_saving(self):
        with fill_source() as source:
            candidates, detector = self.candidates(source)
            before = copy.deepcopy(candidates)
            options = calibrated_fill_options()
            accepted, _ = fill.evaluate_region_candidates(candidates, source.size, source.size,
                options, base_meta=detector)
            chosen, metadata = ExtraFast.select_fast_regions(accepted, source.size, source.size, options)
            rejected_batch = [row for row in accepted if row['color_index'] == 3]
            self.assertEqual(len(rejected_batch), 4)
            scan = sum(row['stroke_cost_seconds'] for row in rejected_batch)
            complete = sum(row['fill_core_cost_seconds'] for row in rejected_batch) + 2.
            self.assertGreater(complete, scan)
            self.assertEqual({row['color_index'] for row in chosen}, {0})
            self.assertEqual(len(chosen), 4)
            self.assertEqual(metadata['batch_rejected_regions'], 4)
            self.assertEqual(candidates, before)
            estimate = fill.estimate_fill_execution_seconds(chosen, source.size, source.size, options)
            self.assertEqual(estimate['fill_tool_switch_seconds'], 2.)
            self.assertAlmostEqual(estimate['total_seconds'],
                sum(row['fill_core_cost_seconds'] for row in chosen) + 2., places=4)

    def test_public_hybrid_reproves_surviving_batches_and_keeps_exact_native_coverage(self):
        real_map = hybrid.pixel_map_from_groups
        references = []
        def observed_map(*args, **kwargs):
            mapped = real_map(*args, **kwargs)
            references.append(mapped)
            return mapped
        with fill_source() as source, ExitStack() as owned:
            before = source.tobytes()
            directory = Path(owned.enter_context(tempfile.TemporaryDirectory()))
            owned.enter_context(patch('ProfileStorage.data_dir', return_value=directory))
            owned.enter_context(patch('RuntimePaths.data_dir', return_value=directory))
            owned.enter_context(patch.object(hybrid, 'pixel_map_from_groups', new=observed_map))
            owned.enter_context(patch('DrawBot.log_event'))
            owned.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
            for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                owned.enter_context(patch(name, return_value={}))
            options = calibrated_fill_options(corners=((100, 100), (292, 228)))
            plan = DrawBot.make_plan(source, source.size, options)
            owned.callback(close_plan, plan, source)
            regions = plan['options']['fill_regions']
            self.assertEqual({row['color_index'] for row in regions}, {0})
            self.assertEqual(len(regions), 4)
            metadata = plan['options']['region_fill_meta']
            self.assertEqual(metadata['fill_batch_admission']['cost_filtered_regions'], 4)
            self.assertGreater(metadata['stateful_fill_simulation']['batch_revalidation_passes'], 1)
            self.assertEqual(metadata['stateful_fill_simulation']['accepted_regions'], len(regions))
            palette = [(40 + index * 3, 10) for index in range(len(plan['colors']))]
            mouse = NumericFillMouse(source.size, (100, 100), palette)
            DrawBot.execute_plan(plan, (100, 100, *source.size), palette, mouse, NoWait(),
                threading.Event(), lambda *_args: None, clock=lambda: 0)
            projection = NativeBrushProjection(plan['image'].size, plan['fitted'], plan['options'])
            target = references[0].palette_index[np.ix_(projection.y_source, projection.x_source)]
            drawable = references[0].drawable_mask[np.ix_(projection.y_source, projection.x_source)]
            # The source-grid quality score is before CanvasGuard. Its real
            # native executor deliberately leaves the 3 px safety inset empty;
            # compare every physical pixel, including that unpainted border.
            left, top, right, bottom = plan['options']['canvas_guard_meta']['safe_bounds']
            safe = np.zeros_like(drawable)
            safe[top-100:bottom-100+1, left-100:right-100+1] = True
            expected = np.full_like(target, -1)
            expected[drawable & safe] = target[drawable & safe]
            np.testing.assert_array_equal(mouse.surface, expected)
            self.assertEqual(np.count_nonzero(drawable & ~safe), 1884)
            quality = plan['options']['adaptive_hybrid_meta']['quality']
            self.assertEqual(quality['missing_pixels'], 0)
            self.assertEqual(quality['wrong_color_pixels'], 0)
            self.assertEqual(plan['options']['runtime_safety_report']['fills']['better_fill_clicks'], 4)
            self.assertFalse(mouse.held)
            self.assertEqual(source.tobytes(), before)

    def test_stop_after_cost_rejection_cannot_publish_an_unproven_fill_subset(self):
        real = ExtraFast.select_fast_regions
        stopped = False
        changes = []
        def select(regions, *args, **kwargs):
            nonlocal stopped
            selected, metadata = real(regions, *args, **kwargs)
            changes.append((len(regions), len(selected)))
            if len(selected) < len(regions):
                stopped = True
            return selected, metadata
        with fill_source() as source, patch.object(ExtraFast, 'select_fast_regions', new=select):
            before = source.tobytes()
            with self.assertRaises(InterruptedError):
                DrawBot.make_plan(source, source.size, calibrated_fill_options(), cancelled=lambda: stopped)
            self.assertIn((8, 4), changes)
            self.assertEqual(source.tobytes(), before)


class DetailZoomDeliveryTests(PaletteOwner):
    def test_shorter_legacy_diagnostic_groups_do_not_disable_real_detail_paths(self):
        with Image.open(ROOT / 'golden-regression/small-detail-preservation.png') as source, ExitStack() as owned:
            options = zoom_options('Off', time_budget_mode='Unlimited', unlimited_time=True)
            plan = DrawBot.make_plan(source, (96, 64), options)
            owned.callback(close_plan, plan, source)
            settings = dict(plan['options'], detail_zoom='4x')
            groups, _execution, sequence, metadata = zoom.add_detail_zoom_pass(source, plan['image'],
                plan['colors'], [], plan['execution_groups'], plan['execution_sequence'], settings,
                fitted=plan['fitted'])
            self.assertEqual(groups, [])
            self.assertTrue(metadata['enabled'])
            self.assertTrue(any(row.get('detail_zoom') for row in sequence))

    def test_late_optional_detail_fits_real_cost_without_changing_the_base_sequence(self):
        with Image.open(ROOT / 'golden-regression/small-detail-preservation.png') as source, ExitStack() as owned:
            before = source.tobytes()
            off = DrawBot.make_plan(source, (96, 64), zoom_options('Off'))
            owned.callback(close_plan, off, source)
            actual = DrawBot.make_plan(source, (96, 64), zoom_options('4x'))
            owned.callback(close_plan, actual, source)
            base = [row for row in actual['execution_sequence'] if not row.get('detail_zoom')]
            details = [row for row in actual['execution_sequence'] if row.get('detail_zoom')]
            self.assertEqual(base, off['execution_sequence'])
            self.assertTrue(details)
            self.assertLess(len(details), 16)
            metadata = actual['options']['detail_zoom_meta']
            budget = metadata['execution_budget']
            self.assertEqual(budget['proposed_paths'], 16)
            self.assertEqual(budget['admitted_paths'], len(details))
            model = build_cost_model(actual['options'], actual['image'].size, actual['fitted'])
            cost = model.sequence_cost(actual['execution_sequence'], initial_brush=1,
                include_color_verification=True)
            self.assertLessEqual(model.risk_adjusted_seconds(cost.total_seconds) + budget['fixed_overhead_seconds'],
                                 budget['render_budget_seconds'] + 1e-9)
            self.assertEqual(source.tobytes(), before)

    def test_exhausted_budget_keeps_base_objects_and_unlimited_keeps_all_proposals(self):
        with Image.open(ROOT / 'golden-regression/small-detail-preservation.png') as source, ExitStack() as owned:
            plan = DrawBot.make_plan(source, (96, 64), zoom_options('4x',
                time_budget_mode='Unlimited', unlimited_time=True))
            owned.callback(close_plan, plan, source)
            self.assertNotIn('execution_budget', plan['options']['detail_zoom_meta'])
            sequence = plan['execution_sequence']
            base = [row for row in sequence if not row.get('detail_zoom')]
            proposals = [row for row in sequence if row.get('detail_zoom')]
            self.assertTrue(proposals)
            before = copy.deepcopy((base, proposals))
            settings = dict(plan['options'], time_budget_active=True, unlimited_time=False,
                deadline_render_budget_seconds=1.)
            selected, metadata = zoom._fit_zoom_delivery(base, proposals, settings, plan['image'].size,
                plan['fitted'], lambda: False)
            self.assertEqual(selected, [])
            self.assertEqual(metadata['sequence_budget_seconds'], 0.)
            self.assertEqual((base, proposals), before)
            selected, metadata = zoom._fit_zoom_delivery(base, proposals, dict(settings, unlimited_time=True),
                plan['image'].size, plan['fitted'], lambda: False)
            self.assertIs(selected, proposals)
            self.assertIsNone(metadata)

    def test_preceding_fill_controls_and_color_selections_consume_optional_budget(self):
        with fill_source() as source, ExitStack() as owned:
            plan = DrawBot.make_plan(source, source.size, calibrated_fill_options())
            owned.callback(close_plan, plan, source)
            options = dict(plan['options'], time_budget_active=True, unlimited_time=False,
                deadline_render_budget_seconds=600.)
            model = build_cost_model(options, plan['image'].size, plan['fitted'])
            regions = options['fill_regions']
            expected = model.fixed_overhead(active_colors=0).total_seconds
            expected += fill.estimate_fill_execution_seconds(regions, plan['image'].size,
                plan['fitted'], options, cost_model=model)['total_seconds']
            expected += sum(sum(model.color_selection_cost(color)) for color in {row['color_index'] for row in regions})
            selected, metadata = zoom._fit_zoom_delivery(plan['execution_sequence'], [], options,
                plan['image'].size, plan['fitted'], lambda: False)
            self.assertEqual(selected, [])
            self.assertAlmostEqual(metadata['fixed_overhead_seconds'], expected)


if __name__ == '__main__':
    unittest.main()
