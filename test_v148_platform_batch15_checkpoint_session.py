"""One execution owns its checkpoint proof; only completed bits change."""
from collections import Counter
from contextlib import closing
import copy
import json
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import DrawBot
import RenderResume as resume
from DeadlineScheduler import DeadlineScheduler, PANIC
from test_drawbot import NoWait
import test_v148_detail_zoom_verification as visual_fixtures
import test_v148_platform_batch14_resume as execution_fixtures


class SequenceCheckpointSessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = execution_fixtures.PlatformBatch14ResumeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def plan(self, count=101):
        sequence = [dict(color_index=index % 2,
                         path=((8, 8 + index % 48), (40, 8 + index % 48)),
                         brush_px=1, phase='details') for index in range(count)]
        return self.fixture.plan(sequence=sequence)

    def session(self, plan, **kwargs):
        return resume.SequenceCheckpointSession(plan, **kwargs)

    def test_actual_executor_builds_one_context_for_all_periodic_checkpoints(self):
        plan = self.plan()
        original = copy.deepcopy(plan['execution_sequence'])
        with patch.object(resume, 'plan_fingerprint', wraps=resume.plan_fingerprint) as fingerprint, \
             patch.object(resume, 'sequence_entry_key', wraps=resume.sequence_entry_key) as keys:
            mouse, checkpoints = self.fixture.execute(plan)
        self.assertEqual([item['sequence_completed_count'] for item in checkpoints], [25, 50, 75, 100, 101])
        self.assertEqual(len(mouse.painted), 101)
        self.assertEqual(fingerprint.call_count, 1, 'unchanged image/context is proved once for this execution')
        self.assertEqual(keys.call_count, 202, 'one catalogue key plus one actual completion key per operation')
        self.assertEqual(plan['execution_sequence'], original)
        for state in checkpoints:
            completed = state['sequence_completed_count']
            expected = resume.checkpoint_sequence_progress(plan,
                Counter(map(resume.sequence_entry_key, original[:completed])), last_entry=original[completed - 1])
            self.assertEqual(state, expected)
            self.assertTrue(resume.resolve_resume(plan, json.loads(json.dumps(state)))['compatible'])

    def test_stop_after_checkpoint_saves_the_same_approved_work_without_rescanning(self):
        plan = self.plan()
        stop = NoWait()
        checkpoints = []
        execute = DrawBot.execute_plan
        def stop_after_checkpoint(*args, **kwargs):
            original = kwargs['checkpoint']
            def publish(state):
                checkpoints.append(copy.deepcopy(state))
                original(state)
                stop.stopped = True
            kwargs['checkpoint'] = publish
            return execute(*args, **kwargs)
        with patch.object(DrawBot, 'execute_plan', side_effect=stop_after_checkpoint), \
             patch.object(resume, 'plan_fingerprint', wraps=resume.plan_fingerprint) as fingerprint, \
             patch.object(resume, 'sequence_entry_key', wraps=resume.sequence_entry_key) as keys:
            with self.assertRaises(InterruptedError):
                self.fixture.execute(plan, stop=stop)
        self.assertEqual(len(self.fixture.mouse.painted), 25)
        self.assertFalse(self.fixture.mouse.held)
        self.assertEqual([state['sequence_completed_count'] for state in checkpoints], [25, 25])
        self.assertEqual(checkpoints[0], checkpoints[1])
        self.assertEqual(fingerprint.call_count, 1)
        self.assertEqual(keys.call_count, 126)

    def test_snapshots_match_public_schema_and_duplicate_occurrence_bit_order(self):
        plan = self.plan(17)
        sequence = plan['execution_sequence']
        sequence[4] = dict(sequence[0])
        sequence[11] = dict(sequence[0])
        session = self.session(plan)
        completed = Counter()
        self.assertEqual(session.snapshot(prelude_complete=False),
                         resume.checkpoint_sequence_progress(plan, {}, prelude_complete=False))
        for number in (11, 16, 0, 8, 4, 2, 6):
            entry = sequence[number]
            key = resume.sequence_entry_key(entry)
            completed[key] += 1
            session.complete(key)
            self.assertEqual(dict(session.completed_counts), dict(completed))
            state = session.snapshot(last_entry=entry)
            self.assertEqual(state, resume.checkpoint_sequence_progress(plan, completed, last_entry=entry))
            self.assertEqual(resume.validate_progress(state)['sequence_completed_count'], sum(completed.values()))
        with self.assertRaises(ValueError):
            session.snapshot(prelude_complete=False)
        with self.assertRaises(ValueError):
            session.snapshot(prelude_complete=1)
        before = session.snapshot()
        for bad_key in ('f' * 20, resume.sequence_entry_key(sequence[0])):
            with self.assertRaises(ValueError):
                session.complete(bad_key)
        self.assertEqual(session.snapshot(), before)
        with self.assertRaises(TypeError):
            session.completed_counts['f' * 20] = 1

    def test_seeded_resume_and_real_replan_keep_effective_width_identity(self):
        sequence = self.fixture.sequence()
        sequence.append({'color_index': 0, 'path': ((8, 36), (40, 36)), 'brush_px': 5})
        for entry, importance in zip(sequence, (.2, .3, .9)):
            entry.update(phase='structure', importance=importance, estimated_cost_seconds=.1)
        plan = self.fixture.plan(sequence=sequence)
        operations = list(resume.execution_sequence_with_brushes(plan))
        completed = Counter({resume.sequence_entry_key(operations[0]): 1})
        state = resume.checkpoint_sequence_progress(plan, completed, last_entry=operations[0])
        verified = resume.resolve_resume(plan, state)
        self.assertTrue(verified['compatible'])
        session = self.session(plan, completed_counts=verified['sequence_completed_counts'])
        scheduler = DeadlineScheduler(operations, start_time=0., budget_seconds=10., clock=lambda: 0.)
        scheduler.mode = PANIC
        reordered = scheduler.replan_remaining(operations, force=True)
        self.assertEqual([entry['brush_px'] for entry in reordered], [5, 1, 1])
        for entry in reordered:
            key = resume.sequence_entry_key(entry)
            if completed[key]:
                continue
            session.complete(key)
            completed[key] += 1
            saved = session.snapshot(last_entry=entry)
            self.assertEqual(saved, resume.checkpoint_sequence_progress(plan, completed, last_entry=entry))
            self.assertTrue(resume.resolve_resume(dict(plan, execution_sequence=reordered), saved)['compatible'])

    def test_seeded_duplicate_prefixes_preserve_adjacent_and_partial_bitmap_bytes(self):
        plan = self.plan(3)
        first, second, third = plan['execution_sequence']
        plan['execution_sequence'] = [first] * 17 + [second] * 17 + [third] * 13
        keys = [resume.sequence_entry_key(entry) for entry in (first, second, third)]
        for first_count in (0, 1, 7, 8, 9, 17):
            for second_count in (0, 1, 7, 8, 9, 17):
                with self.subTest(counts=(first_count, second_count)):
                    counts = {keys[0]: first_count, keys[1]: second_count, keys[2]: 9}
                    session = self.session(plan, completed_counts=counts)
                    self.assertEqual(session.snapshot(), resume.checkpoint_sequence_progress(plan, counts))
                    session.complete(keys[2])
                    counts[keys[2]] += 1
                    self.assertEqual(session.snapshot(), resume.checkpoint_sequence_progress(plan, counts))
        for invalid in ({keys[0]: 18}, {keys[0]: -1}, {keys[0]: True}, {'f' * 20: 1}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.session(plan, completed_counts=invalid)

    def test_snapshot_never_reopens_source_or_rebuilds_proof_and_is_independently_owned(self):
        plan = self.plan(19)
        session = self.session(plan)
        key = resume.sequence_entry_key(plan['execution_sequence'][0])
        expected = resume.checkpoint_sequence_progress(plan, {key: 1})
        with patch.object(resume, 'plan_fingerprint', side_effect=AssertionError('source rehashed')), \
             patch.object(resume, '_sequence_catalog', side_effect=AssertionError('catalog rebuilt')), \
             patch.object(resume, 'sequence_entry_key', side_effect=AssertionError('operation rehashed')):
            session.complete(key)
            first = session.snapshot()
            self.assertEqual(first, expected)
            first['completed_keys'].append('bad')
            first['sequence_completed_bits'] = 'bad'
            self.assertEqual(session.snapshot(), expected)
        plan['image'].putpixel((63, 63), (20, 30, 40))
        self.assertFalse(resume.resolve_resume(plan, session.snapshot())['compatible'])
        fresh = self.session(plan)
        fresh.complete(key)
        self.assertNotEqual(fresh.snapshot()['plan_fingerprint'], expected['plan_fingerprint'])
        self.assertTrue(resume.resolve_resume(plan, fresh.snapshot())['compatible'])

    def test_catalog_initialization_cancels_before_input(self):
        plan = self.plan(601)
        stop = NoWait()
        original = resume.sequence_entry_key
        count = 0
        def interrupt(entry):
            nonlocal count
            count += 1
            if count == 70:
                stop.stopped = True
            return original(entry)
        with patch.object(resume, 'sequence_entry_key', side_effect=interrupt):
            with self.assertRaises(InterruptedError):
                self.fixture.execute(plan, stop=stop)
        self.assertLessEqual(count, 256)
        self.assertEqual(self.fixture.mouse.actions, [('release',)])

    def test_context_hash_cancellation_closes_owned_strips_and_preserves_source(self):
        plan = self.plan(5)
        source = self.fixture.stack.enter_context(closing(Image.new('RGB', (1024, 1024), 'white')))
        plan['image'] = source
        cancelled = threading.Event()
        owned = []
        crop = Image.Image.crop
        def first_strip(image, *args, **kwargs):
            strip = crop(image, *args, **kwargs)
            owned.append(strip)
            cancelled.set()
            return strip
        with patch.object(Image.Image, 'crop', first_strip):
            with self.assertRaises(InterruptedError):
                self.session(plan, cancelled=cancelled.is_set)
        self.assertEqual(len(owned), 1)
        with self.assertRaises(ValueError):
            owned[0].getpixel((0, 0))
        self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))

    def test_base_metadata_pass_cancels_a_large_repeated_color_order(self):
        plan = self.plan(5)
        cancelled = threading.Event()
        class RepeatedOrder(list):
            passes = 0
            reads_after_stop = 0
            def __iter__(self):
                self.passes += 1
                for number, item in enumerate(super().__iter__()):
                    # Fingerprinting is already cancellable. Interrupt the
                    # separate base-metadata pass after that proof finishes.
                    if self.passes == 2 and number == 70:
                        cancelled.set()
                    if cancelled.is_set():
                        self.reads_after_stop += 1
                    yield item
        order = RepeatedOrder([0, 1] * 2500)
        plan['options']['color_order'] = order
        with self.assertRaises(InterruptedError):
            self.session(plan, cancelled=cancelled.is_set)
        self.assertEqual(order.passes, 2)
        self.assertLessEqual(order.reads_after_stop, 256)

    def test_resume_limit_does_not_become_a_new_execution_limit(self):
        plan = self.plan(51)
        with patch.object(resume, 'MAX_SEQUENCE_OPERATIONS', 10):
            with self.assertRaisesRegex(ValueError, 'resume limit'):
                self.session(plan)
            mouse, checkpoints = self.fixture.execute(plan)
        self.assertEqual(len(mouse.painted), 51)
        self.assertEqual(checkpoints, [])

    def test_actual_resumed_deadline_skip_never_sets_an_unexecuted_bit(self):
        sequence = self.fixture.sequence()
        sequence[0].update(phase='structure', estimated_cost_seconds=.1, importance=1.)
        sequence[1].update(phase='accuracy', estimated_cost_seconds=.1, importance=.1)
        sequence.append(dict(color_index=0, path=((8, 36), (40, 36)), phase='structure',
                             estimated_cost_seconds=.1, importance=1.))
        plan = self.fixture.plan(sequence=sequence)
        operations = list(resume.execution_sequence_with_brushes(plan))
        first_key = resume.sequence_entry_key(operations[0])
        plan['options']['render_resume_state'] = resume.checkpoint_sequence_progress(plan, {first_key: 1})
        plan['options']['adaptive_deadline_meta'] = {'render_budget_seconds': 10.}
        sessions = []
        original = resume.SequenceCheckpointSession
        def capture(*args, **kwargs):
            session = original(*args, **kwargs)
            sessions.append(session)
            return session
        with patch.object(resume, 'SequenceCheckpointSession', side_effect=capture), \
             patch.object(resume, 'plan_fingerprint', wraps=resume.plan_fingerprint) as fingerprint:
            mouse, checkpoints = self.fixture.execute(plan)
        self.assertEqual(fingerprint.call_count, 2, 'one resume validation plus one fresh execution proof')
        self.assertEqual(len(mouse.painted), 1)
        self.assertEqual(mouse.painted[0][1], 1)
        self.assertEqual(plan['options']['deadline_runtime_meta']['skipped_paths'], 1)
        expected = {first_key: 1, resume.sequence_entry_key(operations[2]): 1}
        self.assertEqual(dict(sessions[0].completed_counts), expected)
        self.assertEqual(checkpoints[-1]['sequence_completed_count'], 2)
        self.assertEqual(checkpoints[-1], resume.checkpoint_sequence_progress(plan, expected, last_entry=operations[2]))

    def test_checkpoint_initialization_failure_disables_only_recovery_for_this_run(self):
        plan = self.plan(51)
        with patch.object(resume, 'SequenceCheckpointSession', side_effect=OSError('source read failed')) as setup:
            mouse, checkpoints = self.fixture.execute(plan)
        setup.assert_called_once()
        self.assertEqual(len(mouse.painted), 51)
        self.assertEqual(plan['options']['runtime_path_counts']['sent'], 51)
        self.assertEqual(checkpoints, [])

    def test_dry_run_and_execution_without_checkpoint_callback_build_no_session(self):
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                execute = DrawBot.execute_plan
                def invoke(*args, **kwargs):
                    if dry_run:
                        kwargs['dry_run'] = True
                    else:
                        kwargs['checkpoint'] = None
                    return execute(*args, **kwargs)
                with patch.object(DrawBot, 'execute_plan', side_effect=invoke), \
                     patch.object(resume, 'SequenceCheckpointSession') as setup:
                    mouse, checkpoints = self.fixture.execute(self.plan(5))
                setup.assert_not_called()
                self.assertEqual(checkpoints, [])
                if dry_run:
                    self.assertFalse(any(action[0] in ('click', 'press', 'release') for action in mouse.actions))
                else:
                    self.assertEqual(len(mouse.painted), 5)

    def test_visual_verification_failure_never_marks_pending_paths_complete(self):
        fixture = visual_fixtures.DetailSequenceVerificationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = resume.SequenceCheckpointSession
        for first_failure in (True, False):
            with self.subTest(first_failure=first_failure):
                sessions = []
                def capture(*args, **kwargs):
                    session = original(*args, **kwargs)
                    sessions.append(session)
                    return session
                plan = fixture.plan(paths_in_first_batch=30 if first_failure else 2)
                with patch.object(resume, 'SequenceCheckpointSession', side_effect=capture):
                    with self.assertRaisesRegex(InterruptedError, 'Visual verification stopped'):
                        fixture.execute(plan, fixture.snapshots(bad_first=first_failure, bad_detail=not first_failure))
                self.assertEqual(len(sessions), 1)
                expected = 0 if first_failure else 3
                self.assertEqual(sum(sessions[0].completed_counts.values()), expected)
                self.assertEqual(sessions[0].snapshot()['sequence_completed_count'], expected)
                self.assertEqual([state['sequence_completed_count'] for state in fixture.checkpoints],
                                 [] if first_failure else [2, 3])


if __name__ == '__main__':
    unittest.main()
