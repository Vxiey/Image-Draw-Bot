"""Preview attempts own real planner images until successful queue publication.

Source pixels come only from the shipped PNG. The planner, worker, deadlines,
queue and result adoption are real; native presentation and explicit allocation
failures are the controlled boundaries.
"""
from contextlib import ExitStack
from pathlib import Path
import queue
import threading
from types import MethodType
from unittest.mock import patch

from PIL import Image

import DrawBot
import ReleaseStabilityHardening as stability
from test_pixel_accurate_v1086 import opts
from test_v148_ui_batch16_plan_status import PlanStatusFixture


def plan_images(plan):
    """Inspect actual public result buffers independently of the owner's list."""
    values = list(plan.values()) + list(plan.get('ui_previews', {}).values())
    options = plan.get('options', {})
    values.extend(options.values())
    cache = options.get('_accuracy_normalized_source_cache')
    if isinstance(cache, dict):
        values.extend(cache.values())
    return list({id(value): value for value in values
                 if isinstance(value, Image.Image)}.values())


class PreviewAttemptOwnershipTests(PlanStatusFixture):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_schedule_poll'))
        self.stack.enter_context(patch('DrawBot.log_error'))
        self.actual_make_plan = DrawBot.make_plan

    def image(self, _color):
        # Override the inherited fixture's synthetic image allocator completely.
        with Image.open(Path(__file__).with_name('assets') / 'image-draw-bot-icon.png') as opened:
            image = opened.convert('RGBA')
        self.images.append(image)
        return image

    def close_images(self):
        values = self.images + [image for plan in self.plans for image in plan_images(plan)]
        for image in {id(value): value for value in values}.values():
            image.close()

    def app(self):
        app = super().app()
        app.events = queue.Queue()
        app.preview_after = None
        app.needs_plan = False
        app.drop_action_pending = None
        for name in ('begin_worker', '_handle_event', 'update_plan'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        app.options = lambda: opts(
            profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_current_color=True, draw_quality='High likeness',
            render_preset='Manual', unlimited_time=True, time_budget_mode='Unlimited',
            cpu_workers='1', detail_zoom='Off', _execution_cost_calibration_override={})
        return app

    def build(self, app, *, after_plan=None, before_plan=None, full_detail=False):
        plans, sources = [], []

        def observe(source, area, options, cancelled):
            if before_plan is not None:
                before_plan(plans)
            sources.append(source)
            self.images.append(source)
            result = self.actual_make_plan(source, area, options, cancelled)
            self.plans.append(result)
            plans.append(result)
            if after_plan is not None:
                after_plan(result, len(plans))
            return result

        with patch('DrawBot.make_plan', side_effect=observe):
            app.update_plan(user_initiated=True, full_detail=full_detail)
            worker = app.worker
            self.assertIsInstance(worker, threading.Thread)
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive(), 'The real preview worker must terminate')
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        self.assertEqual(events[-1], ('done', 'preview'))
        for source in sources:
            self.assert_closed_image(source)
        return plans, events

    def assert_closed_image(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def assert_closed_plan(self, plan, *, borrowed=()):
        images = plan_images(plan)
        self.assertGreater(len(images), 4, 'The actual plan must own several presentation buffers')
        for image in images:
            if not any(image is value for value in borrowed):
                self.assert_closed_image(image)

    def assert_live_plan(self, plan):
        images = plan_images(plan)
        self.assertGreater(len(images), 4)
        for image in images:
            image.getpixel((0, 0))

    def deliver(self, app, events):
        for event in events:
            app._handle_event(*event)
        self.assertIsNone(app.activity)

    def deadline(self, stack):
        now, guards = [0.0], []
        actual_guard = stability.PreviewAttemptGuard

        def create(*args, **kwargs):
            guard = actual_guard(*args, **kwargs, clock=lambda: now[0])
            guards.append(guard)
            return guard

        stack.enter_context(patch.object(stability, 'PreviewAttemptGuard', side_effect=create))
        return now, guards

    def test_published_normal_and_full_preview_stay_open_through_real_ui_adoption(self):
        for full_detail in (False, True):
            with self.subTest(full_detail=full_detail):
                app = self.app()
                source, pixels = app.original, app.original.tobytes()
                plans, events = self.build(app, full_detail=full_detail)
                self.assertEqual(len(plans), 1)
                self.assertEqual([kind for kind, _ in events], ['planned', 'done'])
                self.assertIs(events[0][1], plans[0])
                self.assert_live_plan(plans[0])
                before = [image.tobytes() for image in plan_images(plans[0])]
                self.deliver(app, events)
                self.assertIs(app.plan, plans[0])
                self.assertEqual([image.tobytes() for image in plan_images(app.plan)], before)
                self.assertIs(app.original, source)
                self.assertEqual(source.tobytes(), pixels)

    def test_expired_return_closes_first_plan_before_the_real_fallback_starts(self):
        app = self.app()
        pixels = app.original.tobytes()
        fallback_observations = []
        with ExitStack() as stack:
            now, guards = self.deadline(stack)

            def returned(_plan, count):
                if count == 1:
                    now[0] = guards[-1].deadline + 1.0

            def entering(plans):
                if plans:
                    states = []
                    for image in plan_images(plans[0]):
                        try:
                            image.getpixel((0, 0))
                        except ValueError:
                            states.append(True)
                        else:
                            states.append(False)
                    fallback_observations.append(states)

            plans, events = self.build(app, after_plan=returned, before_plan=entering)
        self.assertEqual(len(plans), 2)
        self.assertEqual(len(fallback_observations), 1)
        self.assertTrue(all(fallback_observations[0]), 'Rejected image cores overlap the fallback')
        self.assert_closed_plan(plans[0])
        self.assert_live_plan(plans[1])
        self.assertTrue(plans[1]['preview_fallback_used'])
        self.assertIs(events[0][1], plans[1])
        self.deliver(app, events)
        self.assertIs(app.plan, plans[1])
        self.assertEqual(app.original.tobytes(), pixels)

    def test_expired_full_preview_keeps_previous_ui_plan_and_publishes_no_replacement(self):
        app = self.app()
        previous = self.adopt_plan(app)
        previous_pixels = [image.tobytes() for image in plan_images(previous)]
        source_pixels = app.original.tobytes()
        with ExitStack() as stack:
            now, guards = self.deadline(stack)

            def expired(_plan, _count):
                now[0] = guards[-1].deadline + 1.0

            plans, events = self.build(app, after_plan=expired, full_detail=True)
        self.assertEqual(len(plans), 1)
        self.assertEqual([kind for kind, _ in events], ['preview_timeout', 'done'])
        self.assert_closed_plan(plans[0])
        self.deliver(app, events)
        self.assertIs(app.plan, previous)
        self.assertEqual([image.tobytes() for image in plan_images(previous)], previous_pixels)
        self.assertEqual(app.original.tobytes(), source_pixels)

    def test_stop_or_close_at_real_planner_return_releases_result_and_stop_can_retry(self):
        for closing in (False, True):
            with self.subTest(closing=closing):
                app = self.app()
                pixels = app.original.tobytes()

                def interrupted(_plan, _count):
                    if closing:
                        app.closing = True
                    else:
                        app.stop.set()

                plans, events = self.build(app, after_plan=interrupted)
                self.assertEqual(len(plans), 1)
                self.assertEqual([kind for kind, _ in events], ['status', 'done'])
                self.assert_closed_plan(plans[0])
                self.assertIsNone(app.plan)
                self.assertEqual(app.original.tobytes(), pixels)
                if not closing:
                    self.deliver(app, events)
                    self.assertEqual(app.status.get(), 'Stopped.')
                    retried, retry_events = self.build(app)
                    self.deliver(app, retry_events)
                    self.assertFalse(app.stop.is_set())
                    self.assertIs(app.plan, retried[0])
                    self.assert_live_plan(app.plan)

    def test_publication_failure_closes_all_images_and_retains_the_primary_exception(self):
        for error_type, close_fails in ((OSError, False), (MemoryError, False), (OSError, True)):
            with self.subTest(error_type=error_type.__name__, close_fails=close_fails):
                app = self.app()
                primary = error_type('controlled result publication failure')
                cleanup_failure = OSError('controlled secondary image close failure')
                closed = []

                class FailedPublication(queue.Queue):
                    def put(self, item, *args, **kwargs):
                        if item[0] == 'planned':
                            raise primary
                        return super().put(item, *args, **kwargs)

                app.events = FailedPublication()
                with ExitStack() as stack:
                    def returned(plan, _count):
                        if close_fails:
                            image = plan['preview']
                            actual_close = image.close

                            def close():
                                actual_close()
                                closed.append(image)
                                raise cleanup_failure

                            stack.enter_context(patch.object(image, 'close', side_effect=close))

                    plans, events = self.build(app, after_plan=returned)
                self.assertEqual([kind for kind, _ in events], ['terminal_status', 'done'])
                self.assertIn(str(primary), events[0][1][1])
                self.assertIsNotNone(primary.__traceback__)
                self.assert_closed_plan(plans[0])
                self.assertIsNone(app.plan)
                app.original.getpixel((0, 0))
                if close_fails:
                    self.assertEqual(closed, [plans[0]['preview']])
                    self.assertTrue(any('cleanup' in note.lower()
                                        for note in getattr(primary, '__notes__', ())))
                self.deliver(app, events)
                app.events = queue.Queue()
                retried, retry_events = self.build(app)
                self.deliver(app, retry_events)
                self.assertIs(app.plan, retried[0])
                self.assert_live_plan(app.plan)

    def test_timeout_cleanup_error_is_visible_and_does_not_leave_other_images_open(self):
        app = self.app()
        primary = OSError('controlled timeout retirement failure')
        with ExitStack() as stack:
            now, guards = self.deadline(stack)

            def expired(plan, _count):
                image = plan['preview']
                actual_close = image.close

                def close():
                    actual_close()
                    raise primary

                stack.enter_context(patch.object(image, 'close', side_effect=close))
                now[0] = guards[-1].deadline + 1.0

            plans, events = self.build(app, after_plan=expired)
        self.assertEqual(len(plans), 1, 'A failed retirement must not start another allocation')
        self.assertEqual([kind for kind, _ in events], ['terminal_status', 'done'])
        self.assertIn(str(primary), events[0][1][1])
        self.assertIsNotNone(primary.__traceback__)
        self.assert_closed_plan(plans[0])
        self.assertIsNone(app.plan)
        app.original.getpixel((0, 0))

    def test_failed_publication_preserves_borrowed_options_and_previous_ui_plan(self):
        app = self.app()
        previous = self.adopt_plan(app)
        old_pixels = [image.tobytes() for image in plan_images(previous)]
        borrowed = self.image(None)
        borrowed_pixels = borrowed.tobytes()
        actual_options = app.options
        app.options = lambda: dict(actual_options(), _accuracy_original_source=borrowed)
        primary = MemoryError('controlled publication exhaustion with borrowed accuracy input')

        class FailedPublication(queue.Queue):
            def put(self, item, *args, **kwargs):
                if item[0] == 'planned':
                    raise primary
                return super().put(item, *args, **kwargs)

        app.events = FailedPublication()
        plans, events = self.build(app)
        self.assertIs(plans[0]['options']['_accuracy_original_source'], borrowed)
        self.assert_closed_plan(plans[0], borrowed=(borrowed,))
        self.assertEqual([kind for kind, _ in events], ['terminal_status', 'done'])
        self.assertIsNotNone(primary.__traceback__)
        self.assertIs(app.plan, previous)
        self.assertEqual([image.tobytes() for image in plan_images(previous)], old_pixels)
        self.assertEqual(borrowed.tobytes(), borrowed_pixels)
        app.original.getpixel((0, 0))
