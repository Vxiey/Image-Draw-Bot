"""Accepted image edits hand automatic previews to the idle UI exactly once."""
from contextlib import ExitStack
from pathlib import Path
import queue
import tempfile
import threading
from types import MethodType
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import DrawBot
from AccuracyEvaluator import normalize_source
from DropInStart import DROP_IN_ACTION
from test_pixel_accurate_v1086 import opts
from test_v148_application_batch04_settings import Value
from test_v148_application_batch14_browser_start import setup_payload
from test_v148_ui_batch16_plan_status import PlanStatusFixture


REAL_THREAD = threading.Thread


class ScheduledRoot:
    """Only the Tk scheduler is replaced; controller callbacks remain real."""
    def __init__(self):
        self.jobs = {}
        self.history = {}
        self.number = 0
        self.deiconify = Mock()

    def after(self, delay, callback):
        self.number += 1
        token = self.number
        self.jobs[token] = (delay, callback)
        self.history[token] = callback
        return token

    def after_cancel(self, token):
        self.jobs.pop(token, None)

    def run(self, token):
        return self.jobs.pop(token)[1]()

    def run_next(self):
        return self.run(min(self.jobs, key=lambda token: (self.jobs[token][0], token)))


class AutoPreviewHandoffTests(PlanStatusFixture):
    def setUp(self):
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        # Native window visibility and the recurring Tk poll are boundaries;
        # workers, queue consumption, editing and public planning are real.
        self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_schedule_poll'))
        self.planner = self.stack.enter_context(patch('DrawBot.make_plan', wraps=DrawBot.make_plan))

    def app(self, mode='Auto full'):
        app = super().app()
        app.root = ScheduledRoot()
        app.events = queue.Queue()
        app.mouse = Mock()
        app.preview_mode.set(mode)
        app.draw_quality.set('High likeness')
        app.needs_plan = False
        app.preview_after = None
        app.drop_action_pending = None
        app.calibration_path = self.directory / 'calibration.json'
        app.refresh_runtime_safety_ui = Mock()
        app.refresh_correction_review_ui = Mock()
        for name in ('browser_one_click_text', 'browser_auto_text', 'one_click_setup_text'):
            setattr(app, name, Value(''))
        for name in ('begin_worker', 'load_source', '_handle_event', 'update_plan',
                     '_run_pending_drop_in_start'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        app.options = lambda: opts(
            profile_name=app.game.get(), profile_key='microsoft-paint',
            paint_current_color=True, draw_quality='High likeness',
            render_preset='Manual', unlimited_time=True, time_budget_mode='Unlimited',
            cpu_workers='1', detail_zoom='Off', _execution_cost_calibration_override={})
        return app

    def source(self, app):
        image = Image.new('RGBA', (32, 24), 'white')
        ImageDraw.Draw(image).rectangle((8, 6, 23, 17), fill=(24, 73, 159, 255))
        self.images.append(image)
        app.original = image
        return image

    def take_worker_events(self, app, expected):
        worker = app.worker
        self.assertIsInstance(worker, threading.Thread)
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), 'The actual worker must finish within its fixture bound')
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        self.assertEqual([kind for kind, _ in events], [expected, 'done'])
        value = events[0][1]
        if expected == 'planned':
            self.plans.append(value)
        elif expected == 'background_removed':
            self.images.append(value.image)
        elif expected in ('loaded', 'upscaled', 'pasted'):
            self.images.append(value[0])
        return events

    def start_edit(self, app, route, *, action=None, force=False):
        original = self.source(app)
        if route == 'load':
            path = self.directory / ('source-' + str(len(self.apps)) + '.png')
            original.save(path)
            app.original = self.image('red')
            self.assertTrue(app.load_source(str(path), path.name, action=action,
                                            one_click_force=force))
            kind = 'loaded'
        elif route == 'background':
            self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
            kind = 'background_removed'
        elif route == 'upscale':
            self.assertTrue(DrawBot.DrawBotApp._start_upscale(app, original, 2, 'Pixel art'))
            kind = 'upscaled'
        else:
            with patch('PIL.ImageGrab.grabclipboard', return_value=original):
                self.assertTrue(DrawBot.DrawBotApp.paste_image(app))
            kind = 'pasted'
        return self.take_worker_events(app, kind)

    def deliver(self, app, *events):
        for event in events:
            app.events.put(event)
        DrawBot.DrawBotApp.poll(app)
        self.assertNotIn('UI event error contained:', app.status.get())

    def assert_preview(self, app):
        token = app.preview_after
        self.assertIn(token, app.root.jobs, 'Accepted automatic source must queue a preview when idle')
        self.assertIsNone(app.activity)
        before = self.planner.call_count
        accepted = app.original
        pixels = accepted.tobytes()
        app.root.run(token)
        self.assertEqual(app.activity, 'preview')
        events = self.take_worker_events(app, 'planned')
        self.assertIsNone(app.plan, 'The planning worker must publish before UI adoption')
        self.deliver(app, *events)
        self.assertIs(app.plan, events[0][1])
        self.assertEqual(self.planner.call_count, before + 1)
        self.assertIs(app.original, accepted)
        self.assertEqual(accepted.tobytes(), pixels)
        plan = app.plan
        self.assertEqual(plan['target_area'], app.area()[2:])
        self.assertEqual(plan['preview'].size, app.area()[2:])
        self.assertGreater(plan['count'], 0)
        with normalize_source(accepted, plan['preview'].size) as expected:
            self.assertEqual(plan['ui_previews']['original_normalized'].tobytes(), expected.tobytes())
        self.assertFalse(app.needs_plan)
        self.assertFalse(app.root.jobs)
        DrawBot.DrawBotApp.poll(app)
        self.assertFalse(app.root.jobs, 'A completed source handoff must not requeue itself')
        return plan

    def test_file_load_hands_both_automatic_modes_to_real_planning_after_done(self):
        for mode in ('Auto light', 'Auto full'):
            with self.subTest(mode=mode):
                app = self.app(mode)
                events = self.start_edit(app, 'load')
                self.deliver(app, events[0])
                self.assertEqual(app.activity, 'load')
                self.assertEqual(app.original.getpixel((12, 10)), (24, 73, 159, 255))
                self.assertTrue(app.needs_plan)
                self.assertFalse(app.root.jobs)
                self.deliver(app, events[1])
                self.assert_preview(app)

    def test_background_removal_hands_changed_alpha_to_real_preview_after_done(self):
        app = self.app()
        events = self.start_edit(app, 'background')
        self.deliver(app, events[0])
        self.images.append(app.background_removal_original)
        self.assertEqual(app.activity, 'background-remove')
        self.assertEqual(app.original.getpixel((0, 0))[3], 0)
        self.assertEqual(app.original.getpixel((12, 10)), (24, 73, 159, 255))
        self.assertTrue(app.needs_plan)
        self.assertFalse(app.root.jobs)
        self.deliver(app, events[1])
        self.assert_preview(app)

    def test_upscale_and_its_real_undo_each_preview_the_new_accepted_pixels(self):
        app = self.app()
        events = self.start_edit(app, 'upscale')
        original = app.original
        self.deliver(app, events[0])
        self.assertEqual(app.activity, 'upscale')
        self.assertEqual(app.original.size, (64, 48))
        self.assertEqual(app.original.getpixel((24, 20)), (24, 73, 159, 255))
        self.assertTrue(app.needs_plan)
        self.assertFalse(app.root.jobs)
        self.deliver(app, events[1])
        self.assert_preview(app)
        DrawBot.DrawBotApp.undo_upscale(app)
        self.assertIs(app.original, original)
        DrawBot.DrawBotApp.poll(app)
        self.assert_preview(app)

    def test_manual_source_edits_and_bitmap_handoff_remain_manual(self):
        for route in ('load', 'background', 'upscale', 'bitmap'):
            with self.subTest(route=route):
                app = self.app('Manual')
                events = self.start_edit(app, route)
                self.deliver(app, events[0])
                self.assertFalse(app.root.jobs)
                self.deliver(app, events[1])
                self.assertIsNone(app.activity)
                self.assertFalse(app.needs_plan)
                self.assertFalse(app.root.jobs)
                self.assertIsNone(app.plan)
                if app.background_removal_original is not None:
                    self.images.append(app.background_removal_original)
        self.planner.assert_not_called()

    def test_noop_background_preserves_existing_plan_and_queues_nothing(self):
        app = self.app()
        source = app.original
        plan = self.adopt_plan(app)
        calls = self.planner.call_count
        self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
        events = self.take_worker_events(app, 'background_removed')
        self.assertTrue(events[0][1].metadata.get('no_op_reason'))
        self.deliver(app, *events)
        self.assertIs(app.original, source)
        self.assertIs(app.plan, plan)
        self.assertFalse(app.root.jobs)
        self.assertFalse(app.needs_plan)
        self.assertEqual(self.planner.call_count, calls)

    def test_stop_before_source_adoption_closes_candidate_without_queueing_preview(self):
        for route in ('load', 'background', 'upscale'):
            with self.subTest(route=route):
                app = self.app()
                events = self.start_edit(app, route)
                source = app.original
                candidate = events[0][1].image if route == 'background' else events[0][1][0]
                DrawBot.DrawBotApp._request_stop(app)
                self.deliver(app, *events)
                self.assertIs(app.original, source)
                with self.assertRaises(ValueError):
                    candidate.getpixel((0, 0))
                self.assertFalse(app.needs_plan)
                self.assertFalse(app.root.jobs)
        self.planner.assert_not_called()

    def test_escape_after_adoption_before_done_does_not_restart_work(self):
        for route in ('load', 'background', 'upscale', 'bitmap'):
            with self.subTest(route=route):
                app = self.app()
                events = self.start_edit(app, route)
                self.deliver(app, events[0])
                accepted = app.original
                pixels = accepted.tobytes()
                if app.background_removal_original is not None:
                    self.images.append(app.background_removal_original)
                DrawBot.DrawBotApp._request_stop(app)
                self.deliver(app, events[1])
                self.assertTrue(app.stop.is_set())
                self.assertFalse(app.needs_plan)
                self.assertFalse(app.root.jobs)
                self.assertIs(app.original, accepted)
                self.assertEqual(accepted.tobytes(), pixels)
        self.planner.assert_not_called()

    def test_escape_after_idle_scheduling_cannot_be_cleared_by_automatic_worker(self):
        app = self.app()
        events = self.start_edit(app, 'bitmap')
        self.deliver(app, *events)
        token = app.preview_after
        self.assertIn(token, app.root.jobs)
        DrawBot.DrawBotApp._request_stop(app)
        app.root.run(token)
        self.assertTrue(app.stop.is_set())
        self.assertIsNone(app.activity)
        self.assertIsNone(app.worker)
        self.planner.assert_not_called()

    def test_escape_during_automatic_options_handoff_keeps_stop_and_releases_snapshot(self):
        app = self.app()
        events = self.start_edit(app, 'bitmap')
        self.deliver(app, *events)
        options = app.options

        def stop_in_options():
            result = options()
            DrawBot.DrawBotApp._request_stop(app)
            return result

        copies = []
        original_copy = Image.Image.copy

        def record_copy(image):
            copied = original_copy(image)
            if image is app.original:
                copies.append(copied)
            return copied

        app.options = stop_in_options
        with patch.object(Image.Image, 'copy', record_copy):
            app.root.run(app.preview_after)
        self.assertTrue(app.stop.is_set())
        self.assertIsNone(app.activity)
        self.assertIsNone(app.worker)
        self.assertEqual(len(copies), 1)
        self.assertEqual(app.status.get(), 'Stopped.')
        with self.assertRaises(ValueError):
            copies[0].getpixel((0, 0))
        self.assertFalse(app.root.jobs)
        self.planner.assert_not_called()

    def test_explicit_build_preview_still_accepts_new_work_after_stop(self):
        app = self.app('Manual')
        self.source(app)
        DrawBot.DrawBotApp._request_stop(app)
        app.update_plan(user_initiated=True, reason='user-button')
        self.assertFalse(app.stop.is_set())
        self.assertEqual(app.activity, 'preview')
        events = self.take_worker_events(app, 'planned')
        self.deliver(app, *events)
        self.assertIs(app.plan, events[0][1])
        self.assertGreater(app.plan['count'], 0)
        self.assertEqual(self.planner.call_count, 1)
        self.assertFalse(app.root.jobs)

    def test_stop_before_accepted_preview_task_releases_its_private_snapshot(self):
        app = self.app('Manual')
        source = self.source(app)
        gate = threading.Event()
        copies = []
        copy = source.copy

        def snapshot():
            result = copy()
            copies.append(result)
            self.images.append(result)
            return result

        def thread(*, target, **kwargs):
            def delayed():
                if not gate.wait(timeout=3):
                    app.stop.set()
                target()
            return REAL_THREAD(target=delayed, **kwargs)

        with patch.object(source, 'copy', side_effect=snapshot), \
                patch('DrawBot.threading.Thread', side_effect=thread):
            app.update_plan(user_initiated=True, reason='user-button')
        worker = app.worker
        self.assertTrue(worker.is_alive())
        self.assertEqual(app.activity, 'preview')
        self.assertEqual(len(copies), 1)
        DrawBot.DrawBotApp._request_stop(app)
        gate.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.planner.assert_not_called()
        with self.assertRaises(ValueError):
            copies[0].getpixel((0, 0))
        self.assertEqual(source.getpixel((12, 10)), (24, 73, 159, 255))
        DrawBot.DrawBotApp.poll(app)
        self.assertIsNone(app.activity)
        self.assertFalse(app.root.jobs)

    def test_public_preview_plan_owns_images_after_private_snapshot_is_released(self):
        app = self.app('Manual')
        source = self.source(app)
        pixels = source.tobytes()
        app.update_plan(user_initiated=True, reason='user-button')
        events = self.take_worker_events(app, 'planned')
        snapshot = self.planner.call_args.args[0]
        self.images.append(snapshot)
        self.assertIsNot(snapshot, source)
        with self.assertRaises(ValueError):
            snapshot.getpixel((0, 0))
        self.deliver(app, *events)
        self.assertIs(app.plan, events[0][1])
        self.assertEqual(app.plan['options']['_accuracy_original_source'].tobytes(), pixels)
        self.assertIsNot(app.plan['image'], snapshot)
        self.assertIsNot(app.plan['preview'], snapshot)
        self.assertGreater(app.plan['image'].getpixel((12, 10))[3], 0)
        app.plan['preview'].getpixel((12, 10))
        self.assertEqual(source.tobytes(), pixels)

    def test_preview_planning_failure_releases_snapshot_with_retained_traceback(self):
        app = self.app('Manual')
        self.source(app)
        failure = ValueError('injected planner failure')
        self.planner.side_effect = failure
        app.update_plan(user_initiated=True, reason='user-button')
        worker = app.worker
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        snapshot = self.planner.call_args.args[0]
        self.images.append(snapshot)
        self.assertIsNotNone(failure.__traceback__)
        with self.assertRaises(ValueError):
            snapshot.getpixel((0, 0))
        DrawBot.DrawBotApp.poll(app)
        self.assertIsNone(app.activity)
        self.assertIsNone(app.plan)
        self.assertFalse(app.root.jobs)

    def test_cancel_after_adoption_or_scheduling_revokes_automatic_request(self):
        for idle in (False, True):
            with self.subTest(idle=idle):
                app = self.app()
                events = self.start_edit(app, 'load')
                self.deliver(app, events[0])
                if idle:
                    self.deliver(app, events[1])
                DrawBot.DrawBotApp.cancel(app)
                if not idle:
                    self.deliver(app, events[1])
                self.assertFalse(app.needs_plan)
                self.assertFalse(app.root.jobs)
                self.assertTrue(app.stop.is_set())
        self.planner.assert_not_called()

    def start_at_drawing_boundary(self, app, *, user_initiated):
        # This is the native drawing boundary; keep the actual worker acceptance
        # that cancels an unstarted automatic preview.
        self.assertTrue(user_initiated)
        self.assertIsNone(app.activity)
        return app.begin_worker('draw', lambda: None)

    def browser(self, app):
        app.game.set('Gartic Phone')
        app._active_profile_name = 'Gartic Phone'
        app._palette_preflight_ready = lambda: True
        app._paint_tool_preflight_ready = lambda: True
        app._refresh_target_for_draw = lambda: app.target_client_rect

    def test_real_file_drop_in_starts_before_queued_preview_after_loader_done(self):
        app = self.app()
        self.browser(app)
        app.manual_drop_in_start = Value(True)
        app.manual_drop_in_armed_until = float('inf')
        events = self.start_edit(app, 'load', action=DROP_IN_ACTION)
        self.deliver(app, events[0])
        self.assertFalse(app.root.jobs)
        self.assertEqual(app.drop_action_pending, DROP_IN_ACTION)
        self.deliver(app, events[1])
        self.assertEqual(sorted(delay for delay, _ in app.root.jobs.values()), [60, 900])
        with patch.object(DrawBot.DrawBotApp, 'draw', side_effect=self.start_at_drawing_boundary) as draw:
            self.assertTrue(app.root.run_next())
        draw.assert_called_once_with(app, user_initiated=True)
        self.assertEqual(app.activity, 'draw')
        self.assertFalse(app.root.jobs)
        self.assertIsNone(app.drop_action_pending)
        app.worker.join(timeout=3)
        self.assertFalse(app.worker.is_alive())
        self.planner.assert_not_called()

    def test_browser_one_click_owns_setup_and_start_before_automatic_preview(self):
        for force in (False, True):
            with self.subTest(force=force), ExitStack() as local:
                app = self.app()
                self.browser(app)
                app.browser_one_click_enabled.set(not force)
                local.enter_context(patch('BrowserOneClick.one_click_setup',
                                          side_effect=lambda *a, **kw: setup_payload()))
                events = self.start_edit(app, 'load', force=force)
                self.deliver(app, events[0])
                request = app.browser_one_click_request
                self.assertIs(request['image'], app.original)
                self.assertEqual([delay for delay, _ in app.root.jobs.values()], [40])
                self.deliver(app, events[1])
                self.assertEqual(sorted(delay for delay, _ in app.root.jobs.values()), [40, 900])
                self.assertTrue(app.root.run_next())
                self.assertEqual(app.activity, 'browser-one-click-setup')
                self.assertNotIn(app.preview_after, app.root.jobs)
                setup = self.take_worker_events(app, 'browser_one_click_setup_complete')
                self.deliver(app, *setup)
                self.assertEqual(request['phase'], 'finish')
                with patch.object(DrawBot.DrawBotApp, 'draw', side_effect=self.start_at_drawing_boundary) as draw:
                    self.assertTrue(app.root.run_next())
                draw.assert_called_once_with(app, user_initiated=True)
                self.assertEqual(app.activity, 'draw')
                self.assertIsNone(app.browser_one_click_request)
                self.assertFalse(app.root.jobs)
                app.worker.join(timeout=3)
                self.assertFalse(app.worker.is_alive())
        self.planner.assert_not_called()


if __name__ == '__main__':
    import unittest
    unittest.main()
