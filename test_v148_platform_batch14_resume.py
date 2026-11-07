"""Resume follows actual batch occurrences and physical sequence brush widths."""
from collections import Counter
from contextlib import ExitStack, closing
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import DrawBot
import RenderResume as resume
from DeadlineScheduler import DeadlineScheduler, PANIC
from test_drawbot import NoWait
from test_v148_preview_execution_order import BLACK, BLUE, ORIGIN, NativeRasterMouse


class PlatformBatch14ResumeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=directory))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
        for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(name, return_value={}))

    def image(self):
        return self.stack.enter_context(closing(Image.new('RGB', (64, 64), 'white')))

    def plan(self, *, sequence=None, repeated=False):
        paths = [[((8, 12), (40, 12)), ((8, 24), (40, 24))], [((8, 36), (40, 36))]]
        options = dict(delay=0., speed='Fast', precision='Normal', human_mode='Off',
                       paint_current_color=False, strict_color_verification=False,
                       adaptive_color_verification=False, visual_verification_enabled=False,
                       visual_verification_resolved='Off', brush_px=1, color_order=[0, 1, 0] if repeated else [0, 1],
                       profile_key='gartic-phone', profile_name='Gartic Phone', unlimited_time=True,
                       time_budget_mode='Unlimited', _execution_cost_calibration_override={})
        if sequence is not None:
            paths = [[], []]
            for entry in sequence:
                if entry.get('path'):
                    paths[entry['color_index']].append(entry['path'])
            options.update(brush_px=5, canvas_guard_brush_px=5,
                           browser_brush_plan={'target_position': (35, 50), 'target_index': 1,
                               'effective_px': 5, 'nominal_sizes': [1, 5], 'verified_sizes': [1, 5],
                               'control_positions': [(15, 50), (35, 50)], 'confidence': .95, 'safe_guard_px': 5})
        groups = [[(*path[0], *path[-1]) for path in group] for group in paths]
        return dict(options=options, image=self.image(), fitted=(64, 64), groups=groups,
                    execution_groups=paths, execution_sequence=sequence or [],
                    count=sum(map(len, paths)), colors=(BLACK, BLUE),
                    color_selectors=({'kind': 'palette', 'palette_index': 0, 'rgb': BLACK},
                                     {'kind': 'palette', 'palette_index': 1, 'rgb': BLUE}),
                    path_stats={'stroke_optimizer_effective': 'Nearest'})

    def execute(self, plan, *, stop=None):
        surface = self.image()
        palette = [(10, 10), (20, 10)]
        controls = {(15, 50): 1, (35, 50): 5}
        mouse = NativeRasterMouse(surface, palette, plan['colors'], plan['options']['brush_px'], controls)
        checkpoints = []
        with patch('BrowserBrushSize.verify_brush_selection',
                   side_effect=lambda settings, index: mouse.brush == settings['nominal_sizes'][index]):
            self.mouse = mouse
            DrawBot.execute_plan(plan, (*ORIGIN, *surface.size), palette, mouse, stop or NoWait(), threading.Event(),
                                 lambda *event: None, checkpoint=lambda state: checkpoints.append(copy.deepcopy(state)),
                                 clock=lambda: 0.)
        self.assertFalse(mouse.held)
        return mouse, checkpoints

    def assert_one_thin_path(self, mouse, color):
        self.assertEqual(len(mouse.painted), 1)
        actual_color, width, points = mouse.painted[0]
        self.assertEqual((actual_color, width), (color, 1))
        self.assertEqual((points[0], points[-1]), ((8, 24), (40, 24)))
        self.assertTrue(all(y == 24 for _, y in points))
        self.assertEqual(mouse.surface.getpixel((24, 24)), color)
        self.assertEqual(mouse.surface.getpixel((24, 23)), (255, 255, 255))
        self.assertEqual(mouse.surface.getpixel((24, 25)), (255, 255, 255))

    @staticmethod
    def sequence():
        return [
            {'color_index': 0, 'path': ((8, 12), (40, 12)), 'brush_px': 1, 'phase': 'fine_detail'},
            {'color_index': 1, 'path': ((8, 24), (40, 24)), 'phase': 'cleanup'},
        ]

    def test_repeated_actual_batches_produce_valid_unique_completion_keys(self):
        plan = self.plan(repeated=True)
        mouse, checkpoints = self.execute(plan)
        self.assertEqual([color for color, _, _ in mouse.painted], [BLACK, BLACK, BLUE, BLACK, BLACK])
        state = json.loads(json.dumps(checkpoints[-1]))
        self.assertEqual((state['completed_count'], state['total_colors']), (3, 3))
        self.assertEqual(len(set(state['completed_keys'])), 3)
        self.assertEqual(state['completed_keys'][0], resume.batch_key(plan, 0))
        self.assertEqual(state['completed_keys'][2], resume.batch_key(plan, 0, occurrence=2))
        self.assertIsNotNone(resume.validate_progress(state))
        self.assertTrue(resume.resolve_resume(plan, state)['compatible'])

    def test_path_resume_in_second_occurrence_skips_only_that_occurrences_first_path(self):
        plan = self.plan(repeated=True)
        state = resume.checkpoint_before_path(plan, 3, 1, 2, ordered_items=plan['execution_groups'][0])
        self.assertEqual(state['active_batch_key'], resume.batch_key(plan, 0, occurrence=2))
        plan['options']['render_resume_state'] = json.loads(json.dumps(state))
        mouse, checkpoints = self.execute(plan)
        self.assert_one_thin_path(mouse, BLACK)
        self.assertEqual(checkpoints[-1]['completed_count'], 3)
        corrupt = dict(state, active_batch_key=resume.batch_key(plan, 0))
        self.assertFalse(resume.resolve_resume(plan, corrupt)['compatible'])

    def test_old_deduplicated_schedule_does_not_match_repeated_batches(self):
        ordinary = self.plan()
        repeated = self.plan(repeated=True)
        self.assertNotEqual(resume.plan_fingerprint(ordinary), resume.plan_fingerprint(repeated))
        old_state = resume.checkpoint_after_batch(ordinary, 2)
        self.assertFalse(resume.resolve_resume(repeated, old_state)['compatible'])
        corrupt = resume.checkpoint_after_batch(repeated, 3)
        corrupt['completed_keys'][2] = corrupt['completed_keys'][0]
        self.assertIsNone(resume.validate_progress(corrupt), 'duplicate-key corruption remains rejected')

    def test_native_resumed_path_keeps_width_inherited_from_completed_operation(self):
        plan = self.plan(sequence=self.sequence())
        original = copy.deepcopy(plan['execution_sequence'])
        first = plan['execution_sequence'][0]
        state = resume.checkpoint_sequence_progress(plan, {resume.sequence_entry_key(first): 1}, last_entry=first)
        plan['options']['render_resume_state'] = json.loads(json.dumps(state))
        mouse, checkpoints = self.execute(plan)
        self.assert_one_thin_path(mouse, BLUE)
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 2)
        self.assertEqual(plan['execution_sequence'], original)

    def test_raw_public_key_resumes_an_operation_at_the_initial_physical_width(self):
        sequence = self.sequence()
        sequence[0].pop('brush_px')
        plan = self.plan(sequence=sequence)
        original = copy.deepcopy(sequence)
        first = sequence[0]
        state = resume.checkpoint_sequence_progress(
            plan, {resume.sequence_entry_key(first): 1}, last_entry=first)
        resolved = resume.resolve_resume(plan, json.loads(json.dumps(state)))
        self.assertTrue(resolved['compatible'])
        self.assertEqual(resolved['sequence_completed_count'], 1)
        self.assertEqual(resolved['sequence_last_color_index'], 0)
        plan['options']['render_resume_state'] = state
        mouse, checkpoints = self.execute(plan)
        self.assertEqual([(color, width) for color, width, _ in mouse.painted], [(BLUE, 5)])
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 2)
        self.assertEqual(sequence, original)

    def test_raw_public_key_resumes_an_operation_with_inherited_physical_width(self):
        plan = self.plan(sequence=self.sequence())
        inherited = plan['execution_sequence'][1]
        state = resume.checkpoint_sequence_progress(
            plan, {resume.sequence_entry_key(inherited): 1}, last_entry=inherited)
        resolved = resume.resolve_resume(plan, state)
        self.assertTrue(resolved['compatible'])
        expected = resume.sequence_entry_key(dict(inherited, brush_px=1))
        self.assertEqual(resolved['sequence_completed_counts'], {expected: 1})
        plan['options']['render_resume_state'] = state
        mouse, _ = self.execute(plan)
        self.assertEqual([(color, width) for color, width, _ in mouse.painted], [(BLACK, 1)])

    def test_raw_public_duplicates_and_materialized_keys_keep_exact_occurrence_counts(self):
        repeated = {'color_index': 0, 'path': ((8, 12), (40, 12)), 'phase': 'details'}
        final = {'color_index': 1, 'path': ((8, 24), (40, 24)), 'brush_px': 1, 'phase': 'details'}
        plan = self.plan(sequence=[repeated, copy.deepcopy(repeated), final])
        completed = {resume.sequence_entry_key(repeated): 1, resume.sequence_entry_key(final): 1}
        state = resume.checkpoint_sequence_progress(plan, completed, last_entry=final)
        resolved = resume.resolve_resume(plan, state)
        self.assertTrue(resolved['compatible'])
        self.assertEqual(resolved['sequence_completed_count'], 2)
        self.assertEqual(resolved['sequence_remaining_count'], 1)
        plan['options']['render_resume_state'] = state
        mouse, checkpoints = self.execute(plan)
        self.assertEqual([(color, width) for color, width, _ in mouse.painted], [(BLACK, 5)])
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 3)

    def test_ambiguous_raw_duplicate_widths_require_materialized_public_keys(self):
        repeated = {'color_index': 0, 'path': ((8, 12), (40, 12)), 'phase': 'details'}
        switch = {'color_index': 1, 'path': ((8, 24), (40, 24)), 'brush_px': 1, 'phase': 'details'}
        plan = self.plan(sequence=[repeated, switch, copy.deepcopy(repeated)])
        raw_key = resume.sequence_entry_key(repeated)
        with self.assertRaisesRegex(ValueError, 'ambiguous.*brush'):
            resume.checkpoint_sequence_progress(plan, {raw_key: 1}, last_entry=repeated)
        operations = list(resume.execution_sequence_with_brushes(plan))
        self.assertEqual([entry['brush_px'] for entry in operations], [5, 1, 1])
        state = resume.checkpoint_sequence_progress(
            plan, {resume.sequence_entry_key(operations[0]): 1}, last_entry=operations[0])
        self.assertTrue(resume.resolve_resume(plan, state)['compatible'])
        plan['options']['render_resume_state'] = state
        mouse, _ = self.execute(plan)
        self.assertEqual([(color, width) for color, width, _ in mouse.painted], [(BLUE, 1), (BLACK, 1)])

    def test_empty_path_does_not_change_following_inherited_width(self):
        sequence = self.sequence()
        sequence.insert(1, {'color_index': 0, 'path': (), 'brush_px': 5})
        plan = self.plan(sequence=sequence)
        normalized = list(resume.execution_sequence_with_brushes(plan))
        self.assertEqual([entry['brush_px'] for entry in normalized], [1, 1])
        mouse, checkpoints = self.execute(plan)
        self.assertEqual([width for _, width, _ in mouse.painted], [1, 1])
        self.assertEqual(checkpoints[-1]['sequence_total'], 2)

    def test_explicit_sequence_without_drawable_rows_cannot_replay_legacy_groups(self):
        for sequence in ([{'color_index': 0, 'path': ()}], [{}],
                         [{'color_index': 'invalid', 'path': ((8, 12), (40, 12))}]):
            with self.subTest(sequence=sequence):
                plan = self.plan()
                plan['execution_sequence'] = copy.deepcopy(sequence)
                mouse, checkpoints = self.execute(plan)
                self.assertEqual(mouse.painted, [])
                self.assertEqual(mouse.actions, [('release',)])
                self.assertEqual(checkpoints, [])
                self.assertEqual(plan['execution_sequence'], sequence)
        # An actually absent/empty raw sequence still selects normal batches.
        mouse, _ = self.execute(self.plan())
        self.assertEqual(len(mouse.painted), 3)

    def test_actual_deadline_skip_preserves_intended_following_width(self):
        sequence = self.sequence()
        sequence[0].update(phase='accuracy', estimated_cost_seconds=.1, importance=.1)
        sequence[1].update(phase='structure', estimated_cost_seconds=.1, importance=1.)
        plan = self.plan(sequence=sequence)
        plan['options']['adaptive_deadline_meta'] = {'render_budget_seconds': 10.}
        mouse, checkpoints = self.execute(plan)
        self.assertEqual(plan['options']['deadline_runtime_meta']['skipped_paths'], 1)
        self.assert_one_thin_path(mouse, BLUE)
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 1)

    def test_real_replanner_reorders_materialized_widths_without_mutating_original(self):
        sequence = self.sequence()
        sequence.append({'color_index': 0, 'path': ((8, 36), (40, 36)), 'brush_px': 5})
        for entry, importance in zip(sequence, (.2, .3, .9)):
            entry.update(phase='structure', importance=importance, estimated_cost_seconds=.1)
        plan = self.plan(sequence=sequence)
        original = copy.deepcopy(sequence)
        operations = list(resume.execution_sequence_with_brushes(plan))
        scheduler = DeadlineScheduler(operations, start_time=0., budget_seconds=10., clock=lambda: 0.)
        scheduler.mode = PANIC
        reordered = scheduler.replan_remaining(operations, force=True)
        self.assertNotEqual(reordered, operations)
        self.assertEqual([entry['brush_px'] for entry in reordered], [5, 1, 1])
        state = resume.checkpoint_sequence_progress(plan, Counter({resume.sequence_entry_key(operations[0]): 1}))
        changed = dict(plan, execution_sequence=reordered)
        self.assertTrue(resume.resolve_resume(changed, state)['compatible'])
        changed['options'] = dict(plan['options'], render_resume_state=state)
        mouse, _ = self.execute(changed)
        self.assertEqual([width for _, width, _ in mouse.painted], [5, 1])
        self.assertEqual(sequence, original)

    def test_raw_reorder_that_changes_inheritance_rejects_old_checkpoint(self):
        plan = self.plan(sequence=self.sequence())
        first = plan['execution_sequence'][0]
        state = resume.checkpoint_sequence_progress(plan, {resume.sequence_entry_key(first): 1})
        changed = dict(plan, execution_sequence=list(reversed(plan['execution_sequence'])))
        self.assertFalse(resume.resolve_resume(changed, state)['compatible'])

    def test_legacy_implicit_catalog_rejects_but_fully_explicit_catalog_is_compatible(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                sequence = self.sequence()
                if explicit:
                    sequence[1]['brush_px'] = 1
                plan = self.plan(sequence=sequence)
                # The old catalogue hashed raw rows without their inherited width.
                with patch.object(resume, 'execution_sequence_with_brushes', return_value=iter(sequence)):
                    state = resume.checkpoint_sequence_progress(plan, {resume.sequence_entry_key(sequence[0]): 1})
                self.assertEqual(resume.resolve_resume(plan, state)['compatible'], explicit)

    def test_stop_during_actual_materialization_cannot_reach_canvas_input(self):
        stop = NoWait()
        class InterruptedSequence(list):
            def __iter__(self):
                for index, item in enumerate(super().__iter__()):
                    if index == 100:
                        stop.stopped = True
                    yield item
        sequence = self.sequence()
        plan = self.plan(sequence=sequence)
        plan['execution_sequence'] = InterruptedSequence(sequence * 300)
        with self.assertRaisesRegex(InterruptedError, 'sequence preparation cancelled'):
            self.execute(plan, stop=stop)
        self.assertEqual(self.mouse.painted, [])
        self.assertFalse(self.mouse.held)
        # Rows before the polling boundary do not authorize input. Mouse-up is
        # still mandatory cleanup, including when preparation itself stops.
        self.assertEqual(self.mouse.actions, [('release',)])

    def test_execution_iteration_has_no_resume_serialization_limit(self):
        class LargeDeclaredSequence(list):
            def __len__(self):
                return resume.MAX_SEQUENCE_OPERATIONS + 1
        plan = self.plan(sequence=self.sequence())
        plan['execution_sequence'] = LargeDeclaredSequence(plan['execution_sequence'])
        self.assertEqual(len(list(resume.execution_sequence_with_brushes(plan))), 2)
        with self.assertRaisesRegex(ValueError, 'resume limit'):
            resume.checkpoint_sequence_progress(plan, {})

    def test_final_materialization_stop_is_checked_below_the_polling_interval(self):
        plan = self.plan(sequence=self.sequence())
        calls = iter((False, True))
        with self.assertRaises(InterruptedError):
            list(resume.execution_sequence_with_brushes(plan, cancelled=lambda: next(calls)))


if __name__ == '__main__':
    unittest.main()
