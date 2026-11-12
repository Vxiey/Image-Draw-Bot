"""Real browser timing follows the same effective delivery context as ETA."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import DrawBot
import DrawTimeCalibration as calibration
import DrawTimeEstimate as eta
import RealSpeedBudget as speed
from test_drawbot import Mouse
from test_v148_application_batch06_learning import AdvancingWait, Clock
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_transparency import standard_options


ASSET = Path(__file__).with_name('assets') / 'image-draw-bot-icon.png'


def options(**changes):
    result = standard_options(profile_key='sketchful', profile_name='Sketchful.io',
        speed='Fast', delay=.02, precision='Normal', stroke_step_px=8, brush_px=1,
        cpu_workers='1', planning_watchdog='Off', human_mode='Off',
        strict_color_verification=False, adaptive_color_verification=False,
        visual_verification_enabled=False, visual_verification_resolved='Off',
        stroke_delivery_verification='Off', canvas_edge_verification='Off',
        _execution_cost_calibration_override={})
    result.update(changes)
    return result


class DeliverySpeedTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path = self.directory / 'real-speed.json'
        self.read_profile = speed.load_profile
        self.stack.enter_context(patch.object(speed, 'load_profile', new=self.load))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.stack.enter_context(patch('DrawBot.log_event'))

    def load(self, key, path=None, **kwargs):
        return self.read_profile(key, self.path if path is None else path, **kwargs)

    def record(self, settings=None, *, key='sketchful', paths=100, seconds=20):
        result = speed.record_runtime_sample(key, paths, seconds,
            path=self.path, options=settings)
        self.assertTrue(result['recorded'], result)
        return result

    def plan(self):
        with Image.open(ASSET) as decoded:
            with decoded.convert('RGBA') as rgba:
                source = rgba.resize((32, 24), Image.Resampling.LANCZOS)
        self.stack.callback(source.close)
        plan = DrawBot.make_plan(source, source.size, options())
        self.stack.callback(close_plan, plan, source)
        self.assertGreater(plan['count'], 3)
        return plan

    def test_old_profile_only_history_stays_readable_but_cannot_bind_itself(self):
        old = self.record(paths=100, seconds=2)
        before = self.path.read_bytes()
        self.assertEqual(self.load('sketchful')['paths_per_second'], 50.)
        self.assertTrue(speed.recommend_budget('sketchful', 120, path=self.path).learned)
        self.assertIsNone(self.load('sketchful', options=options()))
        self.assertFalse(speed.recommend_budget('sketchful', 120,
            path=self.path, options=options()).learned)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(speed.load_all(self.path)['profiles']['sketchful']['samples'], old['samples'])
        self.assertFalse(speed.record_runtime_sample('microsoft-paint', 100, 20,
            path=self.path, options=dict(options(), profile_key='microsoft-paint'))['recorded'])
        self.assertEqual(self.path.read_bytes(), before)
        # Explicitly proven compatible legacy evidence may migrate, and the
        # first bound write must retain the very history its reader accepted.
        database = speed.load_all(self.path)
        database['profiles']['sketchful']['delivery_signature'] = calibration._delivery_signature(options())
        speed.save_all(database, self.path)
        annotated = dict(database['profiles']['sketchful'])
        self.assertEqual(self.load('sketchful', options=options()), annotated)
        self.assertEqual(self.record(options())['samples'], annotated['samples'] + 1)
        self.assertEqual(speed.load_all(self.path)['profiles']['sketchful'], annotated)

    def test_effective_wait_density_and_precision_partition_samples_but_aliases_share(self):
        base = options()
        first = self.record(base)
        self.assertEqual(first['delivery_signature'], calibration._delivery_signature(base))
        variations = (dict(base, speed='Safe'), dict(base, delay=.08),
                      dict(base, stroke_step_px=4), dict(base, precision='Ultra'))
        signatures = {first['delivery_signature']}
        for changed in variations:
            with self.subTest(changes={key: value for key, value in changed.items() if value != base.get(key)}):
                self.assertIsNone(self.load('sketchful', options=changed))
                recorded = self.record(changed, paths=60, seconds=30)
                self.assertEqual(recorded['samples'], 1)
                signatures.add(recorded['delivery_signature'])
                self.assertEqual(self.load('sketchful', options=base)['paths_per_second'], 5.)
        self.assertEqual(len(signatures), 5)
        equivalent = dict(base, speed='Snabb', preview_plan=True, color_fidelity='Maximum')
        self.assertEqual(self.load('sketchful', options=equivalent)['samples'], 1)
        self.assertEqual(self.record(equivalent)['samples'], 2)
        self.assertEqual(self.load('sketchful', options=base)['samples'], 2)
        self.assertIsNone(self.load('sketchful'))

    def test_public_budget_and_visible_eta_use_only_matching_resolved_options(self):
        self.record(paths=600, seconds=10)  # Old unbound fast evidence stays intact.
        plan = self.plan()
        settings = dict(plan['options'], time_budget_active=True, preview_plan=False,
            target_stroke_count='Auto', target_stroke_count_resolved=800,
            time_budget_seconds=120, deadline_total_seconds=120,
            profile_engine='Manual settings')
        self.assertFalse(speed.apply_budget_policy(settings, path=self.path)['real_speed_budget_meta']['learned'])
        initial = eta.estimate_from_plan(plan)
        self.assertNotIn('measured path throughput', initial['estimate_source'])
        legacy = speed.load_all(self.path)['profiles']['sketchful']
        self.record(plan['options'], paths=30, seconds=150)
        accepted = speed.apply_budget_policy(settings, path=self.path)
        self.assertTrue(accepted['real_speed_budget_meta']['learned'])
        self.assertEqual(accepted['target_stroke_count_reason'], 'real-speed-budget')
        self.assertEqual(accepted['target_stroke_count_resolved'],
            speed.recommend_budget('sketchful', 120, static_cap=800,
                path=self.path, options=settings).path_cap)
        learned = eta.estimate_from_plan(plan)
        self.assertIn('measured path throughput', learned['estimate_source'])
        # preview_seconds retains the uncalibrated sequence model; the visible
        # projected estimate receives measured correction even at native size.
        self.assertEqual(learned['preview_seconds'], initial['preview_seconds'])
        self.assertGreaterEqual(learned['projected_seconds'], plan['count'] / .2)
        changed = dict(settings, delay=.08)
        fallback = speed.apply_budget_policy(changed, path=self.path)
        fresh = speed.apply_budget_policy(changed, path=self.directory / 'empty.json')
        self.assertEqual(fallback, fresh)
        other_plan = dict(plan, options=dict(plan['options'], delay=.08))
        self.assertNotIn('measured path throughput', eta.estimate_from_plan(other_plan)['estimate_source'])
        self.assertEqual(speed.load_all(self.path)['profiles']['sketchful'], legacy)

    def test_actual_completed_executor_records_its_final_delivery_context(self):
        legacy = self.record(paths=100, seconds=2)
        plan = self.plan()
        clock = Clock()
        writer = speed.record_runtime_sample
        seen = []

        def publish(*args, **kwargs):
            seen.append((args, kwargs))
            return writer(*args, **kwargs, path=self.path)

        with ExitStack() as local:
            local.enter_context(patch.object(speed, 'record_runtime_sample', new=publish))
            local.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
            for name in ('DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing',
                         'AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                local.enter_context(patch(name, return_value={}))
            mouse = Mouse()
            DrawBot.execute_plan(plan, (100, 100, *plan['fitted']),
                [(10, 10 + index * 2) for index in range(len(plan['colors']))],
                mouse, AdvancingWait(clock), threading.Event(), lambda *_: None, clock=clock)
        self.assertTrue(any(action[0] == 'press' for action in mouse.actions))
        self.assertEqual(len(seen), 1)
        self.assertIn('options', seen[0][1])
        self.assertIs(seen[0][1]['options'], plan['options'])
        self.assertEqual(seen[0][0][1], plan['options']['runtime_path_counts']['sent'])
        self.assertGreaterEqual(seen[0][0][1], 3)
        stored = self.load('sketchful', options=plan['options'])
        self.assertEqual(stored['samples'], 1)
        self.assertEqual(stored['delivery_signature'], calibration._delivery_signature(plan['options']))
        self.assertEqual(stored['last_paths'], plan['options']['runtime_path_counts']['sent'])
        self.assertEqual(self.load('sketchful')['samples'], legacy['samples'])
        self.assertEqual(self.load('sketchful')['paths_per_second'], legacy['paths_per_second'])

    def test_reset_removes_all_selected_delivery_contexts_and_preserves_other_profiles(self):
        self.record()
        self.record(options())
        self.record(options(delay=.08))
        self.record(key='gartic-phone')
        self.record(dict(options(), profile_key='gartic-phone', profile_name='Gartic Phone'), key='gartic-phone')
        before = speed.load_all(self.path)['profiles']
        with speed.profile_reset_changes('sketchful', path=self.path) as changes:
            self.assertEqual(set(changes), {self.path})
            after = json.loads(changes[self.path])['profiles']
            self.assertEqual(after, {key: value for key, value in before.items()
                                      if key == 'gartic-phone' or key.startswith('gartic-phone|')})
            self.assertEqual(speed.load_all(self.path)['profiles'], before)

    def test_bound_context_eviction_keeps_recent_evidence_and_every_legacy_row(self):
        self.record()
        self.record(key='gartic-phone')
        legacy = dict(speed.load_all(self.path)['profiles'])
        contexts = [options(delay=value) for value in (.02, .04, .06)]
        with patch.object(speed, 'MAX_DELIVERY_CONTEXTS', 2):
            for index, settings in enumerate(contexts):
                with patch.object(speed.time, 'time', return_value=float(index + 1)):
                    self.record(settings)
        self.assertIsNone(self.load('sketchful', options=contexts[0]))
        self.assertIsNotNone(self.load('sketchful', options=contexts[1]))
        self.assertIsNotNone(self.load('sketchful', options=contexts[2]))
        current = speed.load_all(self.path)['profiles']
        for key, value in legacy.items():
            self.assertEqual(current[key], value)
        self.assertEqual(len(current), len(legacy) + 2)

    def test_storage_limit_cannot_publish_an_unreadable_file_or_delete_legacy_history(self):
        self.record()
        before = self.path.read_bytes()
        with patch.object(speed, 'MAX_SPEED_FILE_BYTES', len(before) + 8):
            with self.assertRaisesRegex(ValueError, 'storage limit'):
                self.record(options())
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
