"""A real Auto rescue must rebuild geometry for its new planning image."""
from contextlib import ExitStack, closing
import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from AutoDrawing import resolve_drawing
import DrawBot
import EndToEndAutoTuner
from EndToEndAutoTuner import evaluate_plan_acceptance, propose_rescue_options
from Precision import CanvasTransform
from test_pixel_accurate_v1086 import opts
from test_step11_end_to_end_auto_tuner_v10135 import texture_image
from test_v148_rendering_batch06_canvas import close_plan


AREA = (96, 64)


def settings():
    return opts(
        render_preset='Auto', draw_quality='High likeness', planning_resolution='Standard',
        exact_color_limit='Auto', profile_name='Microsoft Paint', profile_key='microsoft-paint',
        paint_profile=True, custom_color_workflow='Adaptive exact (recommended)',
        exact_color_available=True, time_budget_mode='Custom', unlimited_time=False,
        max_seconds=60, manual_max_seconds=60, fill_tool_available=False,
        resource_scheduler='Off', _execution_cost_calibration_override={},
    )


def native_color_raster(plan):
    """Independent Pillow oracle for this no-Fill, one-pixel Paint fixture.

    Apply the actual source-to-fitted transform before drawing each centerline;
    never resize a planner mask to pretend the old source grid was rebuilt.
    """
    if plan['options'].get('fill_regions'):
        raise AssertionError('This oracle fixture must not contain native Fill.')
    offset = tuple((canvas - fit) / 2 for canvas, fit in zip(AREA, plan['fitted']))
    transform = CanvasTransform(*plan['image'].size, plan['fitted'], *offset)
    brush = int(plan['options'].get('brush_px', 1))
    with closing(Image.new('I', AREA, -1)) as raster:
        draw = ImageDraw.Draw(raster)
        for entry in plan['execution_sequence']:
            brush = int(entry.get('brush_px', brush))
            if brush != 1:
                raise AssertionError('This Paint fixture must use its actual fixed one-pixel brush.')
            path = [transform.point(*point) for point in entry['path']]
            if len(path) == 1:
                draw.point(path[0], fill=entry['color_index'])
            elif path:
                draw.line(path, fill=entry['color_index'], width=1)
        return np.asarray(raster).copy()


class AutoRescueOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        # Isolate learned data only. Policy, acceptance, planning, cost and
        # finalization remain the actual public implementations.
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.stack.enter_context(patch('AutoTunerFeedback._resolved_path', return_value=directory / 'feedback.json'))
        self.stack.enter_context(patch('DrawBot.log_event'))
        with closing(texture_image()) as texture:
            self.source = self.stack.enter_context(closing(texture.resize((48, 32))))
        self.requested = settings()
        # The clean oracle starts from real resolved configuration *before*
        # any renderer can attach compiled geometry, palettes or image caches.
        self.clean_policy = resolve_drawing(self.source, dict(self.requested, _planning_canvas_size=AREA))
        with patch('DrawBot._finalize_auto_tuned_plan', side_effect=lambda plan, *args, **kwargs: plan):
            self.first = self.keep(DrawBot.make_plan(self.source, AREA, self.requested))
        self.acceptance = evaluate_plan_acceptance(self.first)
        self.assertEqual(self.acceptance['status'], 'BELOW_QUALITY_GATE')
        self.assertTrue(self.acceptance['deadline_gate_passed'])
        self.assertGreater(self.acceptance['schedule_headroom_seconds'], 15)
        self.assertEqual(self.acceptance['source_kind'], 'photo / texture')
        self.assertEqual(self.first['image'].size, (67, 45))
        self.assertTrue(self.first['options']['adaptive_hybrid_active'])

    def keep(self, plan):
        self.stack.callback(close_plan, plan, self.source)
        return plan

    def image_state(self, plan=None):
        plan = self.first if plan is None else plan
        images = {id(value): value for value in (
            self.source, *plan.values(), *plan['options'].values(),
            *plan.get('ui_previews', {}).values(),
        ) if isinstance(value, Image.Image)}
        return [(image, image.mode, image.size, image.tobytes()) for image in images.values()]

    def assert_images_unchanged(self, saved):
        for image, mode, size, pixels in saved:
            self.assertEqual(image.mode, mode)
            self.assertEqual(image.size, size)
            self.assertEqual(image.tobytes(), pixels)

    def test_actual_finalizer_matches_fresh_policy_replan_raster_coverage_and_cost(self):
        # This reference is not produced by stripping the same key tuple as
        # production. It never received a completed plan's derived options.
        reference_input = propose_rescue_options(
            dict(self.first, options=self.clean_policy), self.acceptance)
        self.assertEqual(reference_input['auto_tuner_meta']['selected_strategy'], 'quality-rescue')
        reference = self.keep(DrawBot.make_plan(self.source, AREA, reference_input))
        reference_acceptance = evaluate_plan_acceptance(reference)
        self.assertEqual(reference_acceptance['status'], 'PASS')
        original_sequence = copy.deepcopy(self.first['execution_sequence'])
        original_images = self.image_state()
        actual_make = DrawBot.make_plan
        with patch.object(DrawBot, 'make_plan', wraps=actual_make) as replanned:
            actual = self.keep(DrawBot._finalize_auto_tuned_plan(self.first, self.source, AREA))
        self.assertGreaterEqual(replanned.call_count, 1)
        self.assertIsNot(actual, self.first)
        self.assertEqual(actual['image'].size, AREA)
        self.assertEqual(reference['image'].size, AREA)
        self.assertEqual(actual['colors'], reference['colors'])
        actual_raster, reference_raster = native_color_raster(actual), native_color_raster(reference)
        differences = int(np.count_nonzero(actual_raster != reference_raster))
        self.assertEqual(differences, 0, (
            f'Actual rescue reused {len(actual["execution_sequence"])} paths; '
            f'fresh-policy replan has {len(reference["execution_sequence"])} paths. '
            f'{differences} physical canvas pixels differ after changing '
            f'{self.first["image"].size} to {actual["image"].size}.'
        ))
        self.assertEqual(actual['execution_sequence'], reference['execution_sequence'])
        self.assertNotEqual(actual['execution_sequence'], original_sequence)
        self.assertEqual(actual['execution_groups'], reference['execution_groups'])
        np.testing.assert_array_equal(np.asarray(actual['ui_previews']['coverage']),
                                      np.asarray(reference['ui_previews']['coverage']))
        np.testing.assert_array_equal(np.asarray(actual['preview']), np.asarray(reference['preview']))
        for name in ('sequence_seconds', 'path_count', 'color_changes', 'custom_color_changes'):
            self.assertAlmostEqual(actual['draw_time_estimate']['sequence_operation_model'][name],
                                   reference['draw_time_estimate']['sequence_operation_model'][name], places=5)
        self.assertEqual(actual['auto_tuner_acceptance'], evaluate_plan_acceptance(actual))
        self.assertEqual(actual['auto_tuner_acceptance'], reference_acceptance)
        self.assertEqual(actual['options']['auto_tuner_acceptance_meta'], reference_acceptance)
        self.assertEqual(actual['auto_tuner_acceptance']['replan_attempt'], 1)
        self.assertIsNone(propose_rescue_options(actual))
        self.assertEqual(self.first['execution_sequence'], original_sequence)
        self.assert_images_unchanged(original_images)

    def test_public_auto_entry_assesses_the_returned_wrapper_and_rescues_only_once(self):
        # No finalizer/renderer replacement: this is the application entry that
        # previously returned the unassessed outer 67x45/301-path plan.
        offered = []

        def observe_proposal(plan, acceptance=None):
            proposal = propose_rescue_options(plan, acceptance)
            if proposal is not None:
                offered.append((proposal['_auto_tuner_replan_attempt'],
                                proposal['auto_tuner_meta']['selected_strategy']))
            return proposal

        with patch.object(EndToEndAutoTuner, 'propose_rescue_options', side_effect=observe_proposal):
            actual = self.keep(DrawBot.make_plan(self.source, AREA, settings()))
        self.assertEqual(offered, [(1, 'quality-rescue')])
        self.assertEqual(actual['image'].size, AREA)
        self.assertNotEqual(actual['execution_sequence'], self.first['execution_sequence'])
        evaluated = evaluate_plan_acceptance(actual)
        self.assertEqual(evaluated['status'], 'PASS')
        self.assertEqual(actual.get('auto_tuner_acceptance'), evaluated)
        self.assertEqual(actual['options'].get('auto_tuner_acceptance_meta'), evaluated)
        self.assertEqual(evaluated['replan_attempt'], 1)
        self.assertEqual(len(actual['options']['_auto_tuner_attempt_history']), 1)
        self.assertIsNone(propose_rescue_options(actual))

    def test_actual_rescue_keeps_prepared_palette_calibration_actions_and_safety_inputs(self):
        controls = {
            'picture_palette_rgb': ((0, 0, 0), (255, 255, 255)),
            'calibration_fingerprint': 'fixture-owned-calibration',
            'calibration_state': {'profile_key': 'microsoft-paint', 'fingerprint': 'fixture-owned-calibration'},
            'target_canvas_area': (101, 103, *AREA), 'corners': ((101, 103), (197, 167)),
            'strict_color_verification': True, 'adaptive_color_verification': True,
            'canvas_guard_enabled': True, 'strict_runtime_safety': True,
            'tool_actions': [('tool', (20, 25))],
            'fill_tool_actions': [('tool', (32, 25))],
            'fill_restore_actions': [('tool', (20, 25))],
        }
        unchanged_controls = copy.deepcopy(controls)
        requested = dict(settings(), **controls)
        with patch('DrawBot._finalize_auto_tuned_plan', side_effect=lambda plan, *args, **kwargs: plan):
            first = self.keep(DrawBot.make_plan(self.source, AREA, requested))
        acceptance = evaluate_plan_acceptance(first)
        self.assertEqual(acceptance['status'], 'BELOW_QUALITY_GATE')
        images = self.image_state(first)
        proposal = propose_rescue_options(first, acceptance)
        self.assertIsNotNone(proposal)
        for name, value in controls.items():
            self.assertEqual(proposal[name], value, name)
        result = self.keep(DrawBot._finalize_auto_tuned_plan(first, self.source, AREA))
        self.assertIsNot(result, first)
        self.assertEqual(result['colors'], controls['picture_palette_rgb'])
        self.assertEqual(tuple(selector['rgb'] for selector in result['color_selectors']),
                         controls['picture_palette_rgb'])
        for name, value in controls.items():
            self.assertEqual(result['options'][name], value, name)
        self.assertEqual(result['options']['_execution_cost_calibration_override'], {})
        self.assertEqual(result['auto_tuner_acceptance'], evaluate_plan_acceptance(result))
        self.assertEqual(result['auto_tuner_acceptance']['gates'], acceptance['gates'])
        self.assertEqual(result['options']['_auto_tuner_replan_attempt'], 1)
        self.assertIsNone(propose_rescue_options(result))
        self.assertEqual(controls, unchanged_controls)
        self.assert_images_unchanged(images)

    def test_real_browser_pixel_rescue_drops_the_previous_regional_owner(self):
        requested = dict(settings(), profile_name='Gartic Phone', profile_key='gartic-phone',
            paint_profile=False, max_seconds=20, manual_max_seconds=20,
            custom_color_workflow='Calibrated palette', exact_color_available=False)
        with patch('DrawBot._finalize_auto_tuned_plan', side_effect=lambda plan, *args, **kwargs: plan):
            first = self.keep(DrawBot.make_plan(self.source, AREA, requested))
        acceptance = evaluate_plan_acceptance(first)
        self.assertEqual(acceptance['status'], 'BELOW_QUALITY_GATE')
        proposal = propose_rescue_options(first, acceptance)
        self.assertEqual(proposal['auto_tuner_meta']['selected_strategy'], 'quality-rescue-pixel-accurate')
        images = self.image_state(first)
        first_sequence = copy.deepcopy(first['execution_sequence'])
        replacement = self.keep(DrawBot._finalize_auto_tuned_plan(first, self.source, AREA))
        options = replacement['options']
        self.assertTrue(options['pixel_accurate'])
        self.assertFalse(options.get('adaptive_hybrid_active'))
        self.assertFalse('_adaptive_hybrid_execution_sequence' in options)
        self.assertFalse('adaptive_hybrid_meta' in options)
        self.assertFalse('adaptive_hybrid_meta' in replacement)
        self.assertEqual(replacement['execution_sequence'], options['_pixel_execution_sequence'])
        self.assertEqual(replacement['execution_groups'], options['_pixel_execution_groups'])
        self.assertEqual(replacement['auto_tuner_acceptance'], evaluate_plan_acceptance(replacement))
        self.assertEqual(options['_auto_tuner_replan_attempt'], 1)
        self.assertIsNone(propose_rescue_options(replacement))
        self.assertEqual(first['execution_sequence'], first_sequence)
        self.assert_images_unchanged(images)

    def test_proposal_preserves_policy_history_and_first_plan_owned_resources(self):
        images = self.image_state()
        sequence = copy.deepcopy(self.first['execution_sequence'])
        groups = copy.deepcopy(self.first['execution_groups'])
        original_tuner = copy.deepcopy(self.first['options']['auto_tuner_meta'])
        rescue = propose_rescue_options(self.first, self.acceptance)
        self.assertEqual(rescue['auto_tuner_meta']['selected_strategy'], 'quality-rescue')
        self.assertEqual(rescue['draw_quality'], 'High likeness')
        self.assertEqual(rescue['planning_resolution'], 'High')
        self.assertEqual(rescue['quality'], 'Maximum detail')
        self.assertEqual(rescue['_auto_tuner_replan_attempt'], 1)
        self.assertTrue(rescue['_auto_tuner_resolved'])
        self.assertTrue(rescue['auto_engine_resolved'])
        self.assertEqual(rescue['auto_tuner_meta']['acceptance_gates'], original_tuner['acceptance_gates'])
        self.assertEqual(rescue['_execution_cost_calibration_override'], {})
        self.assertEqual(rescue['custom_color_workflow'], 'Adaptive exact (recommended)')
        self.assertEqual(rescue['profile_key'], 'microsoft-paint')
        self.assertTrue(rescue['paint_profile'])
        self.assertEqual(len(rescue['_auto_tuner_attempt_history']), 1)
        for name, value in rescue['_auto_tuner_attempt_history'][0].items():
            self.assertEqual(value, self.acceptance[name])
        self.assertNotIn('_auto_tuner_replan_attempt', self.first['options'])
        self.assertNotIn('_auto_tuner_attempt_history', self.first['options'])
        self.assertEqual(self.first['options']['auto_tuner_meta'], original_tuner)
        self.assertEqual(self.first['execution_sequence'], sequence)
        self.assertEqual(self.first['execution_groups'], groups)
        self.assert_images_unchanged(images)
        # A producer's previous local-coordinate geometry is not user input.
        for name in ('_adaptive_hybrid_execution_groups', '_adaptive_hybrid_execution_sequence',
                     '_adaptive_hybrid_inner', 'adaptive_hybrid_active'):
            self.assertFalse(name in rescue, f'Rescue retained derived renderer output: {name}')

    def test_failed_real_rescue_attempt_returns_the_usable_first_plan(self):
        images = self.image_state()
        sequence = copy.deepcopy(self.first['execution_sequence'])
        groups = copy.deepcopy(self.first['execution_groups'])
        actual_make = DrawBot.make_plan

        def failed_plan(original, area, options, cancelled=lambda: False):
            # Failure occurs in a real second public plan, after its entry
            # boundary, without forging the first pass's acceptance decision.
            with patch('AutoDrawing.resolve_drawing', side_effect=OSError('synthetic planner read failure')):
                return actual_make(original, area, options, cancelled)

        with patch.object(DrawBot, 'make_plan', side_effect=failed_plan) as attempted:
            result = DrawBot._finalize_auto_tuned_plan(self.first, self.source, AREA)
        attempted.assert_called_once()
        self.assertIs(result, self.first)
        self.assertEqual(result['execution_sequence'], sequence)
        self.assertEqual(result['execution_groups'], groups)
        self.assertEqual(result['auto_tuner_acceptance']['status'], 'BELOW_QUALITY_GATE')
        self.assert_images_unchanged(images)

    def test_stop_at_actual_second_plan_entry_propagates_and_preserves_first_plan(self):
        images = self.image_state()
        sequence = copy.deepcopy(self.first['execution_sequence'])
        stop = threading.Event()
        actual_make = DrawBot.make_plan

        def stopped_plan(original, area, options, cancelled=lambda: False):
            self.assertFalse(cancelled())
            stop.set()
            return actual_make(original, area, options, cancelled)

        with patch.object(DrawBot, 'make_plan', side_effect=stopped_plan) as attempted:
            with self.assertRaises(InterruptedError):
                DrawBot._finalize_auto_tuned_plan(self.first, self.source, AREA, stop.is_set)
        attempted.assert_called_once()
        self.assertEqual(self.first['execution_sequence'], sequence)
        self.assert_images_unchanged(images)


if __name__ == '__main__':
    unittest.main()
