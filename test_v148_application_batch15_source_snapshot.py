"""Release the private drawing source when planning hands off its own images."""
import unittest
from unittest.mock import patch

import DrawBot
from PlanningWatchdog import PlanningAttempt, build_planning_attempts
import test_v148_application_batch15_preflight as preflight_fixture
from test_pixel_accurate_v1086 import opts
from test_v148_application_batch04_settings import Value
from test_v148_rendering_batch06_canvas import close_plan


class DrawingSourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        # Reuse the actual draw/begin_worker fixture without inheriting its tests.
        preflight_fixture.DrawPreflightStopTests.setUp(self)
        self.app.keyboard = None
        old_options = self.app.options
        self.app.options = lambda: dict(old_options(), planning_watchdog='Off')
        self.planning.side_effect = build_planning_attempts
        self.snapshots = []
        self.plans = []
        real_copy = self.app.original.copy
        def snapshot(*args, **kwargs):
            copied = real_copy(*args, **kwargs)
            self.snapshots.append(copied)
            self.addCleanup(copied.close)
            return copied
        self.copy = self.stack.enter_context(patch.object(self.app.original, 'copy', side_effect=snapshot))
        self.real_make_plan = DrawBot.make_plan
        self.make_plan = self.stack.enter_context(patch('DrawBot.make_plan', side_effect=self.make_owned_plan))
        self.execute = self.stack.enter_context(patch('DrawBot.execute_plan'))
        self.stack.enter_context(patch('SessionRecovery.clear_render_progress'))

    def make_owned_plan(self, image, area, options, cancelled):
        self.assertFalse(cancelled())
        result = image.resize((2, 2))
        self.addCleanup(result.close)
        plan = {'image': result, 'options': options, 'count': 1, 'estimate': .1,
                'groups': [[(0, 0, 1, 0)]]}
        self.plans.append(plan)
        return plan

    def run_draw(self, **kwargs):
        preflight_fixture.DrawPreflightStopTests.run_draw(self, **kwargs)

    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_private_source_is_closed_before_execution_and_published_plan_stays_alive(self):
        observed = []
        def execute(plan, *args, **kwargs):
            try:
                self.snapshots[0].getpixel((0, 0))
            except ValueError:
                closed = True
            else:
                closed = False
            observed.append((closed, plan['image'].getpixel((0, 0))))
        self.execute.side_effect = execute
        self.run_draw()
        self.assertEqual(observed, [(True, (255, 0, 0, 255))])
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(self.plans[0]['image'].getpixel((0, 0)), (255, 0, 0, 255))

    def test_stop_before_worker_task_releases_already_accepted_snapshot(self):
        DrawBot.DrawBotApp.draw(self.app, user_initiated=True)
        self.assertEqual(len(self.snapshots), 1)
        self.app.stop.set()
        self.app.worker.run()
        self.make_plan.assert_not_called()
        self.assert_closed(self.snapshots[0])

    def test_rejected_small_test_dialog_takes_no_source_snapshot(self):
        with patch('DrawBot.messagebox.askokcancel', return_value=False):
            self.run_draw(test=True)
        self.copy.assert_not_called()
        self.assertIsNone(self.app.worker)

    def test_planning_failure_closes_source_with_retained_exception_traceback(self):
        failure = ValueError('injected planner failure')
        self.make_plan.side_effect = failure
        self.run_draw()
        self.assertIsNotNone(failure.__traceback__)
        self.assertEqual(len(self.snapshots), 1)
        self.assert_closed(self.snapshots[0])
        self.execute.assert_not_called()
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))

    def test_failed_native_thread_start_closes_the_callers_snapshot(self):
        with patch.object(preflight_fixture.DeferredThread, 'start', side_effect=RuntimeError('thread startup')):
            with self.assertRaisesRegex(RuntimeError, 'thread startup'):
                DrawBot.DrawBotApp.draw(self.app, user_initiated=True)
        self.assertEqual(len(self.snapshots), 1)
        self.assert_closed(self.snapshots[0])
        self.make_plan.assert_not_called()

    def test_declined_worker_closes_the_snapshot(self):
        self.app.begin_worker = lambda *args, **kwargs: False
        self.run_draw()
        self.assertEqual(len(self.snapshots), 1)
        self.assert_closed(self.snapshots[0])
        self.make_plan.assert_not_called()

    def test_small_test_never_copies_the_unrelated_loaded_image(self):
        def test_plan(area, options):
            return {'options': options, 'count': 1, 'estimate': .1, 'groups': [[(0, 0, 1, 0)]]}
        with patch('DrawBot.messagebox.askokcancel', return_value=True), \
                patch('DrawBot.make_test_plan', side_effect=test_plan):
            self.run_draw(test=True)
        self.copy.assert_not_called()
        self.make_plan.assert_not_called()
        self.execute.assert_called_once()

    def test_a_planner_transferring_its_input_to_the_plan_keeps_that_image_alive(self):
        def transfer(image, area, options, cancelled):
            return {'image': image, 'options': options, 'count': 1, 'estimate': .1,
                    'groups': [[(0, 0, 1, 0)]]}
        self.make_plan.side_effect = transfer
        self.run_draw()
        self.execute.assert_called_once()
        returned = self.execute.call_args.args[0]
        self.assertIs(returned['image'], self.snapshots[0])
        self.assertEqual(returned['image'].getpixel((0, 0)), (255, 0, 0, 255))
        self.assertIsNot(returned['image'], self.app.original)

    def test_watchdog_retry_keeps_the_same_source_until_final_plan_then_releases_it(self):
        options = self.app.options()
        self.planning.side_effect = None
        self.planning.return_value = [
            PlanningAttempt(1, 2, 'expired', options, 0),
            PlanningAttempt(2, 2, 'fallback', options, None, True)]
        attempts = []
        def retry(image, area, options, cancelled):
            attempts.append(image)
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
            if len(attempts) == 1:
                raise InterruptedError('primary exceeded its watchdog')
            return self.make_owned_plan(image, area, options, cancelled)
        self.make_plan.side_effect = retry
        self.run_draw()
        self.assertEqual(len(attempts), 2)
        self.assertIs(attempts[0], attempts[1])
        self.assert_closed(attempts[0])
        self.execute.assert_called_once()

    def test_failed_plan_publication_does_not_transfer_or_leak_a_source_alias(self):
        def transfer(image, area, options, cancelled):
            return {'image': image, 'options': options, 'count': 1, 'estimate': .1,
                    'groups': [[(0, 0, 1, 0)]]}
        self.make_plan.side_effect = transfer
        put = self.app.events.put
        failure = MemoryError('injected event publication failure')
        def reject_plan(event, *args, **kwargs):
            if event[0] == 'planned':
                raise failure
            return put(event, *args, **kwargs)
        with patch.object(self.app.events, 'put', side_effect=reject_plan):
            self.run_draw()
        self.assertIsNotNone(failure.__traceback__)
        self.assert_closed(self.snapshots[0])
        self.execute.assert_not_called()

    def test_real_public_planner_retains_live_independent_images_after_source_release(self):
        self.app.game = Value('Microsoft Paint')
        self.app.options = lambda: opts(profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_current_color=True, render_preset='Manual', planning_watchdog='Off',
            unlimited_time=True, time_budget_mode='Unlimited', cpu_workers_resolved=1,
            detail_zoom='Off', _execution_cost_calibration_override={})
        real_plans = []
        def plan(image, area, options, cancelled):
            result = self.real_make_plan(image, area, options, cancelled)
            real_plans.append(result)
            self.addCleanup(close_plan, result, self.app.original)
            return result
        self.make_plan.side_effect = plan
        self.run_draw(paint_prepared=True)
        self.execute.assert_called_once()
        self.assert_closed(self.snapshots[0])
        self.assertTrue(real_plans[0]['count'])
        from AutoSketchBudget import _trial_images
        for image in _trial_images(real_plans[0]):
            image.getpixel((0, 0))
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))


if __name__ == '__main__':
    unittest.main()
