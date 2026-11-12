"""A bounded dry run preserves physical brush state from a saved real plan."""
import copy
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan
from FastDryRun import sample_plan
from RenderResume import execution_sequence_with_brushes


class DrySampleBrushStateTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name('golden-regression') / 'small-detail-preservation.png'
        with Image.open(path) as source:
            self.image = source.resize((96, 64), Image.Resampling.NEAREST)
        self.addCleanup(self.image.close)
        palette = ((255, 255, 255), (0, 0, 0), (255, 0, 0), (0, 0, 255),
                   (255, 204, 64), (54, 160, 92), (70, 145, 225), (128, 128, 128))
        pixels = build_pixel_map(self.image, palette, gpu_mode='CPU', skip_white=True)
        options = dict(profile_key='generic', brush_px=1, speed='Fast', precision='High',
                       delay=0, paint_current_color=True, human_mode='Off',
                       _execution_cost_calibration_override={'samples': 0, 'ratio': 1})
        built = build_pixel_stroke_plan(pixels, len(palette), options=options, cpu_workers=1)
        self.paths = [entry['path'] for entry in built['execution_sequence'][:5]]
        self.assertEqual(len(self.paths), 5)
        self.plan = dict(built, image=self.image, fitted=self.image.size, colors=palette,
                         options=options, color_selectors=())

    def saved_sequence(self):
        # The saved sequence format permits omitted widths after an explicit
        # change. Geometry comes from the committed source's actual planner.
        sequence = [dict(color_index=0, path=self.paths[0], brush_px=1),
                    dict(color_index=1, path=self.paths[1], brush_px=8),
                    dict(color_index=2, path=self.paths[2]),
                    dict(color_index=0, path=self.paths[3], brush_px=2)]
        sequence.append(sequence[2])  # Same object; a different inherited width.
        self.plan.update(execution_sequence=sequence, count=len(sequence))
        return sequence

    def test_skipped_color_changes_do_not_change_sampled_brushes_or_mutate_entries(self):
        sequence = self.saved_sequence()
        before = copy.deepcopy(sequence)
        expected = [entry for entry in execution_sequence_with_brushes(self.plan)
                    if entry['color_index'] in (0, 2)]
        sampled = sample_plan(self.plan, max_colors=2, max_paths=4)
        actual = list(execution_sequence_with_brushes(sampled))
        self.assertEqual(actual, expected)
        self.assertEqual([entry['brush_px'] for entry in actual], [1, 8, 2, 2])
        self.assertEqual(sequence, before)
        self.assertIs(sequence[2], sequence[4])
        for entry in sampled['execution_sequence']:
            self.assertFalse(any(entry is original for original in sequence))

    def test_discarded_path_with_same_color_still_supplies_its_brush(self):
        sequence = self.saved_sequence()[:3]
        for entry in sequence:
            entry['color_index'] = 0
        self.plan['execution_sequence'] = sequence
        expected = list(execution_sequence_with_brushes(self.plan))
        sampled = sample_plan(self.plan, max_colors=1, max_paths=2)
        self.assertEqual(list(execution_sequence_with_brushes(sampled)),
                         [expected[0], expected[-1]])
        self.assertEqual(sampled['count'], 2)

    def test_non_drawable_rows_cannot_change_inherited_native_brush_state(self):
        for invalid in ('missing', None, 'not-a-color', float('inf')):
            with self.subTest(color=invalid):
                sequence = self.saved_sequence()
                if invalid == 'missing':
                    sequence[1].pop('color_index')
                else:
                    sequence[1]['color_index'] = invalid
                before = copy.deepcopy(sequence)
                expected = list(execution_sequence_with_brushes(self.plan))
                sampled = sample_plan(self.plan)
                self.assertEqual(list(execution_sequence_with_brushes(sampled)), expected)
                self.assertEqual([entry['brush_px'] for entry in expected], [1, 1, 2, 2])
                self.assertEqual(sampled['count'], len(expected))
                self.assertEqual(sequence, before)

    def test_zero_sample_cannot_revive_full_legacy_groups_in_real_executor(self):
        from DrawBot import execute_plan
        from test_dry_run_budget_v1061 import Clock, Stop, Mouse
        self.saved_sequence()
        self.plan['groups'] = [[(*path[0], *path[-1]) for path in self.paths]]
        self.plan['execution_groups'] = [list(self.paths)]
        for limit in ({'max_paths': 0}, {'max_colors': 0}):
            with self.subTest(limit=limit):
                sampled = sample_plan(self.plan, **limit)
                clock, mouse, events = Clock(), Mouse(), []
                with patch('DrawBot.log_event'), patch('DrawBot.save_runtime_safety_report',
                                                      side_effect=lambda state: state.as_dict()):
                    execute_plan(sampled, (100, 100, 96, 64), [], mouse, Stop(clock),
                                 threading.Event(), lambda *event: events.append(event),
                                 clock=clock, dry_run=True)
                self.assertEqual(sampled['options']['runtime_path_counts']['processed'], 0)
                self.assertFalse(any(action[0] in ('press', 'click') for action in mouse.actions))
                self.assertFalse(any(any(group) for group in sampled['groups']))
                self.assertTrue(any(self.plan['groups']))

    def test_stop_during_original_state_scan_never_publishes_a_partial_sample(self):
        sequence = self.saved_sequence()
        self.plan['execution_sequence'] = sequence * 200
        before = copy.deepcopy(sequence)
        checks = [0]
        def stopped():
            checks[0] += 1
            return checks[0] == 3
        with self.assertRaises(InterruptedError):
            sample_plan(self.plan, cancelled=stopped)
        self.assertEqual(checks[0], 3)
        self.assertEqual(sequence, before)


if __name__ == '__main__':
    unittest.main()
