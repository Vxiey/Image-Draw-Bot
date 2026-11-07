"""The final draw plan has both an executor and a queued UI consumer."""
import threading
from types import MethodType
from unittest.mock import Mock, patch
import unittest

from PIL import Image

import DrawBot
from AutoSketchBudget import _trial_images
from PlanningWatchdog import build_planning_attempts
import test_v148_application_batch15_preflight as preflight_fixture
from test_v148_application_batch14_browser_start import REAL_THREAD
from test_v148_application_batch04_settings import Value
from test_pixel_accurate_v1086 import opts
from test_drawbot import Mouse
from test_v148_rendering_batch06_canvas import close_plan


class FinalDrawingPlanAdoptionTests(unittest.TestCase):
    def setUp(self):
        preflight_fixture.DrawPreflightStopTests.setUp(self)
        app = self.app
        app.keyboard = None
        app.game = Value('Microsoft Paint')
        app.plan = None
        app.shutdown_complete = False
        app.cancel = MethodType(DrawBot.DrawBotApp.cancel, app)
        app._sync_mobile_preview = Mock()
        app.draw_time_text = Value('No current estimate')
        app.preview_diagnostics_text = Value('No current diagnostics')
        app.options = lambda: opts(
            profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_current_color=True, render_preset='Manual', planning_watchdog='Off',
            unlimited_time=True, time_budget_mode='Unlimited', cpu_workers='1', cpu_workers_resolved=1,
            detail_zoom='Off', _execution_cost_calibration_override={})
        self.planning.side_effect = build_planning_attempts
        self.plans = []
        self.execution_entered = threading.Event()
        self.execution_continue = threading.Event()
        self.execution_reads = []
        self.execution_failures = []
        self.runner = None
        self.stack.enter_context(patch('SessionRecovery.clear_render_progress'))
        for name in ('_close_smart_drop_overlay', '_disarm_manual_drop_in'):
            self.stack.enter_context(patch.object(DrawBot.DrawBotApp, name))
        real_make_plan = DrawBot.make_plan
        self.real_execute_plan = DrawBot.execute_plan

        def make_plan(*args, **kwargs):
            plan = real_make_plan(*args, **kwargs)
            self.plans.append(plan)
            return plan

        self.make_plan = self.stack.enter_context(patch('DrawBot.make_plan', side_effect=make_plan))
        self.execute = self.stack.enter_context(patch('DrawBot.execute_plan', side_effect=self.execute_boundary))
        self.addCleanup(self.cleanup_execution)

    def cleanup_execution(self):
        self.execution_continue.set()
        if self.runner is not None:
            self.runner.join(5)
        for plan in self.plans:
            close_plan(plan, self.app.original)

    @staticmethod
    def image_bytes(plan):
        # Deduplicate aliases exactly as production ownership must do, but
        # inspect every renderer-owned field, including accuracy/extra views.
        images = {id(image): image for image in _trial_images(plan)}
        return {key: (image.mode, image.size, image.tobytes()) for key, image in images.items()}

    def execute_boundary(self, plan, *args, **kwargs):
        try:
            self.execution_reads.append(self.image_bytes(plan))
            self.execution_entered.set()
            if not self.execution_continue.wait(5):
                raise AssertionError('The test did not release the executor boundary')
            self.execution_reads.append(self.image_bytes(plan))
        except BaseException as error:
            self.execution_failures.append(error)
            raise

    def start_drawing(self):
        DrawBot.DrawBotApp.draw(self.app, user_initiated=True, paint_prepared=True)
        self.assertIsNotNone(self.app.worker)
        # The app's real begin_worker wrapper runs on a real thread. Its native
        # input boundary is held while this main thread consumes the UI event.
        self.runner = REAL_THREAD(target=self.app.worker.run, daemon=True)
        self.runner.start()
        self.assertTrue(self.execution_entered.wait(5), list(self.app.events.queue))
        self.assertEqual(len(self.plans), 1)
        self.assertGreater(self.plans[0]['count'], 0)
        self.assertIn('_accuracy_original_source', self.plans[0]['options'])
        return self.plans[0]

    def deliver_plan(self):
        while not self.app.events.empty():
            kind, value = self.app.events.get_nowait()
            DrawBot.DrawBotApp._handle_event(self.app, kind, value)
            if kind == 'planned':
                self.assertIs(value, self.plans[0])
                return
        self.fail('The final drawing plan was not published to the UI')

    def finish_execution(self):
        self.execution_continue.set()
        self.runner.join(5)
        self.assertFalse(self.runner.is_alive())
        self.assertFalse(self.execution_failures)
        self.assertEqual(len(self.execution_reads), 2)
        self.assertEqual(self.execution_reads[0], self.execution_reads[1])

    def retained_preview(self):
        image = Image.new('RGB', (2, 2), 'blue')
        self.addCleanup(image.close)
        old = {'image': image, 'preview': image, 'count': 1, 'estimate': 99,
               'preview_generation': self.app.preview_generation, 'options': {}}
        self.app.plan = old
        return old

    def assert_plan_closed(self, plan):
        for image in _trial_images(plan):
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    def test_final_plan_is_adopted_while_executor_still_reads_its_images(self):
        plan = self.start_drawing()
        self.deliver_plan()
        self.assertTrue(self.app.plan is plan, 'The final plan was not adopted')
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.assertIn('draw time', self.app.draw_time_text.get().lower())
        self.app.show_previews.assert_called_once()
        self.app._sync_mobile_preview.assert_called_once()
        self.finish_execution()
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])

    def test_final_plan_replaces_an_existing_accepted_preview(self):
        self.retained_preview()
        plan = self.start_drawing()
        self.deliver_plan()
        self.assertTrue(self.app.plan is plan, 'The final plan did not replace the accepted preview')
        self.finish_execution()
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])

    def test_stop_rejects_pending_ui_adoption_without_closing_active_plan(self):
        old = self.retained_preview()
        plan = self.start_drawing()
        DrawBot.DrawBotApp.cancel(self.app)
        self.deliver_plan()
        self.assertIs(self.app.plan, old)
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.assertEqual(self.app.status.get(), 'Stopping…')
        self.app.show_previews.assert_not_called()
        self.finish_execution()
        self.assert_plan_closed(plan)
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))

    def test_stale_generation_rejects_pending_ui_adoption_without_closing_active_plan(self):
        old = self.retained_preview()
        plan = self.start_drawing()
        self.app.preview_generation += 1
        self.deliver_plan()
        self.assertIs(self.app.plan, old)
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.app.show_previews.assert_not_called()
        self.finish_execution()
        self.assert_plan_closed(plan)
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))

    def test_completed_executor_keeps_its_queued_plan_alive_until_ui_adopts_it(self):
        plan = self.start_drawing()
        self.finish_execution()
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.deliver_plan()
        self.assertTrue(self.app.plan is plan, 'The completed final plan was not adopted')
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])

    def test_stop_after_executor_exit_releases_only_the_rejected_plan(self):
        old = self.retained_preview()
        plan = self.start_drawing()
        self.finish_execution()
        DrawBot.DrawBotApp.cancel(self.app)
        self.deliver_plan()
        self.assertIs(self.app.plan, old)
        self.assert_plan_closed(plan)
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))

    def test_clear_drawing_waits_for_executor_before_releasing_the_rejected_plan(self):
        old = self.retained_preview()
        plan = self.start_drawing()
        self.app.root.deiconify = Mock()
        DrawBot.DrawBotApp.clear_cached_drawing(self.app)
        self.assertIs(self.app.pending_clear_drawing, False)
        self.deliver_plan()
        self.assertIs(self.app.plan, old)
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))
        self.finish_execution()
        self.assert_plan_closed(plan)
        while not self.app.events.empty():
            DrawBot.DrawBotApp._handle_event(self.app, *self.app.events.get_nowait())
        # Complete the real deferred Clear route; only local disk is replaced.
        with patch('SessionRecovery.clear_snapshot'), \
                patch('SessionRecovery.STATE_FILE') as state, \
                patch('SessionRecovery.RENDER_FILE') as render, \
                patch('SessionRecovery.IMAGE_FILE') as source:
            for path in (state, render, source):
                path.exists.return_value = False
            self.app.root.run(next(iter(self.app.root.jobs)))
        self.assertIsNone(self.app.pending_clear_drawing)
        self.assertIsNone(self.app.plan)
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))

    def test_stop_after_planning_before_publication_releases_plan_without_queue_drain(self):
        old = self.retained_preview()
        ready = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        make_plan = self.make_plan.side_effect

        def wait_before_return(*args, **kwargs):
            plan = make_plan(*args, **kwargs)
            ready.set()
            if not release.wait(5):
                raise AssertionError('The test did not release completed planning')
            return plan

        self.make_plan.side_effect = wait_before_return
        mouse = Mouse()
        self.guarded.return_value = mouse
        self.execute.side_effect = lambda *a, **kw: self.real_execute_plan(*a, clock=lambda: 0., **kw)
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda s: s.as_dict()))
        DrawBot.DrawBotApp.draw(self.app, user_initiated=True, paint_prepared=True)
        self.runner = REAL_THREAD(target=self.app.worker.run, daemon=True)
        self.runner.start()
        self.assertTrue(ready.wait(5))
        self.assertFalse(any(kind == 'planned' for kind, _ in self.app.events.queue))
        DrawBot.DrawBotApp.cancel(self.app)
        release.set()
        self.runner.join(5)
        self.assertFalse(self.runner.is_alive())
        self.assertEqual(len(self.plans), 1)
        self.assert_plan_closed(self.plans[0])
        self.assertFalse(any(action[0] != 'release' for action in mouse.actions))
        self.assertIs(self.app.plan, old)
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))

    def test_close_without_draining_planned_releases_images_only_after_executor_exit(self):
        old = self.retained_preview()
        plan = self.start_drawing()
        DrawBot.DrawBotApp.close(self.app)
        self.assertTrue(self.app.closing)
        self.assertFalse(self.app.shutdown_complete)
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.finish_execution()
        self.assert_plan_closed(plan)
        self.assertTrue(any(kind == 'planned' and value is plan for kind, value in self.app.events.queue))
        self.assertIs(self.app.plan, old)
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))

    def test_failed_publication_releases_every_real_plan_image_with_live_traceback(self):
        old = self.retained_preview()
        publish = self.app.events.put
        failure = MemoryError('injected final-plan publication failure')

        def reject_plan(event, *args, **kwargs):
            if event[0] == 'planned':
                raise failure
            return publish(event, *args, **kwargs)

        with patch.object(self.app.events, 'put', side_effect=reject_plan):
            DrawBot.DrawBotApp.draw(self.app, user_initiated=True, paint_prepared=True)
            self.app.worker.run()
        self.assertIsNotNone(failure.__traceback__)
        self.assertEqual(len(self.plans), 1)
        self.assert_plan_closed(self.plans[0])
        self.execute.assert_not_called()
        self.assertIs(self.app.plan, old)
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))

    def test_poll_contained_invalid_result_rejects_owner_without_closing_active_images(self):
        old = self.retained_preview()
        plan = self.start_drawing()
        del plan['count']
        self.app.needs_plan = False
        self.app._handle_event = MethodType(DrawBot.DrawBotApp._handle_event, self.app)
        with patch.object(DrawBot.DrawBotApp, '_schedule_poll'):
            for _ in range(10):
                DrawBot.DrawBotApp.poll(self.app)
                if self.app.events.empty():
                    break
        self.assertTrue(self.app.events.empty())
        self.assertIn('UI event error contained', self.app.status.get())
        self.assertIs(self.app.plan, old)
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.app.show_previews.assert_not_called()
        self.finish_execution()
        self.assert_plan_closed(plan)
        self.assertEqual(old['preview'].getpixel((0, 0)), (0, 0, 255))

    def test_real_executor_can_score_the_final_canvas_after_ui_consumes_its_plan(self):
        # Interleave inside the real executor's OS screenshot boundary, after
        # native paths but before scoring reads source/preview/quantized pixels.
        case = self

        class SnapshotMouse(Mouse):
            def snapshot_canvas(self, area):
                if not case.execution_entered.is_set():
                    case.execution_reads.append(case.image_bytes(case.plans[0]))
                    case.execution_entered.set()
                    if not case.execution_continue.wait(5):
                        raise AssertionError('The test did not release final-canvas capture')
                return Image.new('RGB', tuple(map(int, area[2:])), 'black')

        mouse = SnapshotMouse()
        self.guarded.return_value = mouse
        original_options = self.app.options
        self.app.options = lambda: dict(
            original_options(), canvas_edge_verification='Off',
            strict_color_verification=False, adaptive_color_verification=False,
            visual_verification_enabled=False, visual_verification_resolved='Off',
            post_draw_correction_pass='Off')
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda s: s.as_dict()))
        for target in ('SessionRecovery.save_render_progress', 'RealSpeedBudget.record_runtime_sample',
                       'DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing',
                       'AutoTunerFeedback.record_completed_feedback', 'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(target, return_value={}))

        def execute(*args, **kwargs):
            try:
                return self.real_execute_plan(*args, clock=lambda: 0., **kwargs)
            except BaseException as error:
                self.execution_failures.append(error)
                raise

        self.execute.side_effect = execute
        plan = self.start_drawing()
        self.deliver_plan()
        self.execution_continue.set()
        self.runner.join(5)
        self.assertFalse(self.runner.is_alive())
        self.assertFalse(self.execution_failures)
        accuracy = plan['options'].get('post_draw_accuracy_meta') or {}
        self.assertTrue(accuracy.get('available'), accuracy)
        self.assertTrue(self.app.plan is plan, 'The real executor plan was not adopted')
        self.assertEqual(self.image_bytes(plan), self.execution_reads[0])
        self.assertEqual(plan['options']['runtime_path_counts']['sent'], plan['count'])
        self.assertTrue(any(action[0] == 'press' for action in mouse.actions))
        self.assertFalse(mouse.held)


if __name__ == '__main__':
    unittest.main()
