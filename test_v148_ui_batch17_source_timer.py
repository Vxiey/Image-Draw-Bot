"""Completed drawing readouts follow accepted source changes consistently."""
from contextlib import ExitStack
from pathlib import Path
import queue
import tempfile
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from DrawBot import DrawBotApp
from test_v148_ui_batch16_plan_status import PlanStatusFixture


RESET_TIME = ('Drawing timer: starts when drawing begins.', 'Total draw time: —')


class SourceTimerTests(PlanStatusFixture):
    def app(self):
        app = super().app()
        app.events = queue.Queue()
        app.mouse = Mock()
        app.refresh_runtime_safety_ui = Mock()
        app.refresh_correction_review_ui = Mock()
        for name in ('begin_worker', 'load_source', 'fetch_url'):
            setattr(app, name, MethodType(getattr(DrawBotApp, name), app))
        return app

    def visible_time(self, app):
        return tuple(app.readouts[name].visible_text()
                     for name in ('draw_live_side', 'total_draw_side'))

    def completed(self, app, seconds=37.2):
        DrawBotApp._handle_event(app, 'draw_time_actual', {'seconds': seconds})
        return self.visible_time(app)

    def worker_events(self, app, expected_kind):
        worker = app.worker
        self.assertIsNotNone(worker)
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        self.assertEqual([kind for kind, _ in events], [expected_kind, 'done'])
        kind, value = events[0]
        image = (value.image if kind == 'background_removed' else
                 value[1] if kind == 'recovery_loaded' else value[0])
        if image is not None:
            self.images.append(image)
        return events

    @staticmethod
    def adopt(app, events):
        for kind, value in events:
            DrawBotApp._handle_event(app, kind, value)

    def background_source(self, app):
        source = Image.new('RGBA', (32, 24), 'white')
        self.images.append(source)
        ImageDraw.Draw(source).rectangle((8, 6, 23, 17), fill='blue')
        app.original = source
        return source

    def recovery_events(self, app, image):
        state = {'profile': app.game.get(), 'options': {}, 'has_image': image is not None}
        with patch('SessionRecovery.load_snapshot', return_value=state), \
                patch('SessionRecovery.load_cached_image', return_value=image), \
                patch('DrawBot.messagebox.askyesno', return_value=True), \
                patch('DrawBot.previous_run_unclean', return_value=False):
            DrawBotApp.offer_safe_session_recovery(app)
            return self.worker_events(app, 'recovery_loaded')

    def screen_buttons(self, app, captured):
        callbacks, buttons = {}, {}
        window = Mock()
        window.bind.side_effect = lambda event, callback, **kwargs: callbacks.__setitem__(event, callback)
        window.destroy.side_effect = lambda: callbacks['<Destroy>'](SimpleNamespace(widget=window))
        self.addCleanup(window.destroy)

        def button(_window, **options):
            buttons[options['text']] = options['command']
            return Mock()

        with patch('DrawBot.tk.Toplevel', return_value=window), \
                patch('DrawBot.ttk.Label'), patch('DrawBot.ttk.Button', side_effect=button), \
                patch('PIL.ImageTk.PhotoImage', return_value=object()):
            DrawBotApp.display_screen(app, captured)
        return buttons

    def clear(self, app, *, remove_image):
        with ExitStack() as stack:
            stack.enter_context(patch('SessionRecovery.clear_snapshot'))
            for name in ('STATE_FILE', 'RENDER_FILE', 'IMAGE_FILE'):
                stack.enter_context(patch('SessionRecovery.' + name)).exists.return_value = False
            (DrawBotApp.clear_image if remove_image else DrawBotApp.clear_cached_drawing)(app)

    def test_real_file_and_bitmap_workers_reset_the_same_bound_readouts_on_adoption(self):
        for route in ('file', 'bitmap'):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as directory:
                app = self.app()
                self.adopt_plan(app)
                old, before = app.original, self.visible_time(app)
                source = self.image((12, 34, 56, 78))
                if route == 'file':
                    path = Path(directory) / 'new source.png'
                    source.save(path)
                    self.assertTrue(app.load_source(str(path), path.name))
                else:
                    with patch('PIL.ImageGrab.grabclipboard', return_value=source):
                        self.assertTrue(DrawBotApp.paste_image(app))
                events = self.worker_events(app, 'loaded' if route == 'file' else 'pasted')
                self.assertIs(app.original, old, 'The worker must not adopt its own result')
                self.assertEqual(self.visible_time(app), before)
                self.adopt(app, events)
                self.assertEqual(app.original.tobytes(), source.tobytes())
                self.assertIsNone(app.activity)
                self.assertEqual(self.visible_time(app), RESET_TIME)
                self.assertFalse(app.root.jobs, 'Manual mode must not schedule replacement work')

    def test_real_resampling_and_undo_both_retire_the_replaced_sources_completed_time(self):
        app = self.app()
        self.adopt_plan(app)
        old, before = app.original, self.visible_time(app)
        self.assertTrue(DrawBotApp._start_upscale(app, old, 2, 'Pixel art'))
        events = self.worker_events(app, 'upscaled')
        self.assertIs(app.original, old)
        self.assertEqual(self.visible_time(app), before)
        self.adopt(app, events)
        self.assertEqual(app.original.size, (16, 12))
        self.assertEqual(app.original.getpixel((0, 0)), old.getpixel((0, 0)))
        with self.subTest(phase='upscale'):
            self.assertEqual(self.visible_time(app), RESET_TIME)
        self.completed(app, 91.5)
        DrawBotApp.undo_upscale(app)
        self.assertIs(app.original, old)
        with self.subTest(phase='undo'):
            self.assertEqual(self.visible_time(app), RESET_TIME)

    def test_actual_background_removal_and_undo_reset_only_after_pixel_adoption(self):
        app = self.app()
        source = self.background_source(app)
        self.adopt_plan(app)
        before = self.visible_time(app)
        self.assertTrue(DrawBotApp.remove_image_background(app))
        events = self.worker_events(app, 'background_removed')
        self.assertIs(app.original, source)
        self.assertEqual(self.visible_time(app), before)
        self.assertFalse(events[0][1].metadata.get('no_op_reason'))
        self.adopt(app, events)
        self.images.append(app.background_removal_original)
        self.assertEqual(app.original.getpixel((0, 0))[3], 0)
        self.assertEqual(app.original.getpixel((16, 12)), (0, 0, 255, 255))
        with self.subTest(phase='remove'):
            self.assertEqual(self.visible_time(app), RESET_TIME)
        self.completed(app, 91.5)
        self.assertTrue(DrawBotApp.undo_background_removal(app))
        self.images.append(app.original)
        self.assertEqual(app.original.tobytes(), source.tobytes())
        with self.subTest(phase='undo'):
            self.assertEqual(self.visible_time(app), RESET_TIME)

    def test_actual_noop_background_result_preserves_source_plan_and_completed_time(self):
        app = self.app()
        plan = self.adopt_plan(app)
        source, before = app.original, self.visible_time(app)
        self.assertTrue(DrawBotApp.remove_image_background(app))
        events = self.worker_events(app, 'background_removed')
        self.assertTrue(events[0][1].metadata.get('no_op_reason'))
        self.adopt(app, events)
        self.assertIs(app.original, source)
        self.assertIs(app.plan, plan)
        self.assertEqual(self.visible_time(app), before)

    def test_screen_use_button_resets_time_after_acceptance_and_keeps_capture_pixels(self):
        app = self.app()
        self.adopt_plan(app)
        old, before = app.original, self.visible_time(app)
        capture = self.image((4, 8, 12, 255))
        pixels = capture.tobytes()
        buttons = self.screen_buttons(app, capture)
        self.assertIs(app.original, old)
        self.assertEqual(self.visible_time(app), before)
        buttons['Use as source image']()
        self.images.append(app.original)
        self.assertEqual(app.original.tobytes(), pixels)
        self.assertEqual(self.visible_time(app), RESET_TIME)
        with self.assertRaises(ValueError):
            capture.getpixel((0, 0))

    def test_busy_screen_button_retains_the_live_source_and_its_timer(self):
        app = self.app()
        self.adopt_plan(app)
        old = app.original
        buttons = self.screen_buttons(app, self.image('blue'))
        app.activity = 'draw'
        DrawBotApp._handle_event(app, 'draw_timer', dict(state='paused', elapsed_seconds=4,
            remaining_seconds=6, predicted_total_seconds=10))
        before = self.visible_time(app)
        self.assertFalse(buttons['Use as source image']())
        self.assertIs(app.original, old)
        self.assertEqual(self.visible_time(app), before)

    def test_recovery_done_resets_time_only_when_a_recovered_image_is_adopted(self):
        for with_image in (False, True):
            with self.subTest(with_image=with_image):
                app = self.app()
                self.adopt_plan(app)
                old, before = app.original, self.visible_time(app)
                image = self.image('blue') if with_image else None
                events = self.recovery_events(app, image)
                DrawBotApp._handle_event(app, *events[0])
                self.assertIs(app.original, old, 'Recovery adoption waits for worker done')
                self.assertEqual(self.visible_time(app), before)
                DrawBotApp._handle_event(app, *events[1])
                self.assertIs(app.original, image if with_image else old)
                self.assertEqual(self.visible_time(app), RESET_TIME if with_image else before)
                self.assertFalse(app.target_lock_passed)
                self.assertEqual(app.preview_mode.get(), 'Manual')

    def test_clear_image_resets_completed_time_but_cached_plan_clear_keeps_it(self):
        for remove_image in (False, True):
            with self.subTest(remove_image=remove_image):
                app = self.app()
                self.adopt_plan(app)
                old, before = app.original, self.visible_time(app)
                self.clear(app, remove_image=remove_image)
                self.assertIs(app.original, None if remove_image else old)
                self.assertEqual(self.visible_time(app), RESET_TIME if remove_image else before)

    def test_pending_image_clear_keeps_active_clock_until_worker_ownership_ends(self):
        app = self.app()
        self.adopt_plan(app)
        source = app.original
        app.activity = 'draw'
        worker = Mock()
        worker.is_alive.return_value = True
        app.worker = worker
        DrawBotApp._handle_event(app, 'draw_timer', dict(state='paused', elapsed_seconds=125,
            remaining_seconds=3, predicted_total_seconds=128))
        before = self.visible_time(app)
        self.clear(app, remove_image=True)
        self.assertIs(app.original, source)
        self.assertEqual(self.visible_time(app), before)
        DrawBotApp._handle_event(app, 'draw_time_actual', {'seconds': 130})
        self.assertEqual(self.visible_time(app), before, 'Pending clear rejects worker results')
        DrawBotApp._handle_event(app, 'done', 'draw')
        self.assertIs(app.original, source, 'A done event does not prove thread exit')
        self.assertEqual(self.visible_time(app), before)
        worker.is_alive.return_value = False
        self.clear(app, remove_image=True)
        self.assertIsNone(app.original)
        self.assertEqual(self.visible_time(app), RESET_TIME)

    def test_stop_before_result_consumption_keeps_current_source_and_completed_time(self):
        for route in ('bitmap', 'upscale', 'background', 'recovery'):
            with self.subTest(route=route):
                app = self.app()
                if route == 'background':
                    self.background_source(app)
                self.adopt_plan(app)
                old, before = app.original, self.visible_time(app)
                if route == 'bitmap':
                    with patch('PIL.ImageGrab.grabclipboard', return_value=self.image('blue')):
                        self.assertTrue(DrawBotApp.paste_image(app))
                    events = self.worker_events(app, 'pasted')
                elif route == 'upscale':
                    self.assertTrue(DrawBotApp._start_upscale(app, old, 2, 'Pixel art'))
                    events = self.worker_events(app, 'upscaled')
                elif route == 'background':
                    self.assertTrue(DrawBotApp.remove_image_background(app))
                    events = self.worker_events(app, 'background_removed')
                else:
                    events = self.recovery_events(app, self.image('blue'))
                DrawBotApp.cancel(app)
                self.adopt(app, events)
                self.assertIs(app.original, old)
                self.assertEqual(self.visible_time(app), before)

    def test_rejected_stale_resampling_and_busy_entrypoints_do_not_erase_time(self):
        app = self.app()
        self.adopt_plan(app)
        old, before = app.original, self.visible_time(app)
        stale, replacement = self.image('green'), self.image('blue')
        DrawBotApp._handle_event(app, 'upscaled', (replacement, stale))
        self.assertIs(app.original, old)
        self.assertEqual(self.visible_time(app), before)
        with self.assertRaises(ValueError):
            replacement.getpixel((0, 0))
        app.activity = 'draw'
        with patch('PIL.ImageGrab.grabclipboard') as clipboard:
            self.assertFalse(DrawBotApp.paste_image(app))
        clipboard.assert_not_called()
        self.assertFalse(app.load_source('unused.png', 'unused'))
        self.assertFalse(DrawBotApp._start_upscale(app, old, 2, 'Pixel art'))
        self.assertFalse(DrawBotApp.remove_image_background(app))
        self.assertFalse(DrawBotApp.undo_background_removal(app))
        DrawBotApp.undo_upscale(app)
        self.assertEqual(self.visible_time(app), before)

    def test_settings_and_existing_running_paused_completed_timer_transitions_are_preserved(self):
        app = self.app()
        self.adopt_plan(app)
        before = self.visible_time(app)
        DrawBotApp.options_changed(app)
        self.assertEqual(self.visible_time(app), before)
        app.activity = 'draw'
        for state in ('drawing', 'paused'):
            DrawBotApp._handle_event(app, 'draw_timer', dict(state=state, elapsed_seconds=12,
                remaining_seconds=8, predicted_total_seconds=20))
            live = self.visible_time(app)
            self.assertIn('12s elapsed', live[0])
            self.assertEqual(live[1], f'Total draw time: {state}…')
            DrawBotApp.options_changed(app)
            app._mark_plan_stale('Unchanged source; setup invalidated')
            self.assertEqual(self.visible_time(app), live)
        DrawBotApp._handle_event(app, 'draw_timer', dict(state='completed', elapsed_seconds=20))
        self.assertEqual(self.visible_time(app)[0], 'Drawing timer: 20s elapsed · complete')
        self.completed(app, 20)
        self.assertEqual(self.visible_time(app), ('Drawing timer: completed in 20s',
                                                 'Total draw time: 20s'))
