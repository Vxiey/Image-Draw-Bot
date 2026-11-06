"""Budget controls follow the selected effective policy before planning/input."""
from contextlib import ExitStack, closing
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import DrawBot
from TimeBudget import TIME_BUDGET_MODES
from TimeBudgetEngine import resolve_budget
from test_precision_v102 import Value
import test_v148_ui_batch07_renderer as renderer_fixtures


class EffectiveBudgetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.root))
        self.stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
        self.stack.enter_context(patch('DrawBot.log_event'))

    def app(self, profile='Microsoft Paint', mode='Manual', manual='180'):
        app = renderer_fixtures.AdvertisedRendererTests().app(profile)
        app.render_style.set('Standard / pixel')
        app.time_budget_mode = Value(mode)
        app.max_seconds.set(manual)
        return app

    def test_fixed_and_unlimited_budgets_ignore_invalid_inactive_manual_text(self):
        modes = [mode for mode in TIME_BUDGET_MODES if mode not in ('Manual', 'Custom')]
        for mode in modes:
            for manual in ('', 'not a number', '4', '3601'):
                with self.subTest(mode=mode, manual=manual):
                    app = self.app(mode=mode, manual=manual)
                    options = DrawBot.DrawBotApp.options(app)
                    expected = resolve_budget(mode, 180)
                    self.assertEqual(options['time_budget_mode'], mode)
                    self.assertEqual(options['max_seconds'],
                        3600 if expected['unlimited'] else round(expected['render_budget_seconds']))
                    self.assertEqual(options['manual_max_seconds'], 180)
                    self.assertEqual(app.max_seconds.get(), manual)

    def test_manual_custom_and_unknown_modes_keep_explicit_validation(self):
        for mode in ('Manual', 'Custom'):
            for manual in ('', 'not a number', '2.5', '4', '3601'):
                with self.subTest(mode=mode, manual=manual), self.assertRaisesRegex(ValueError, 'Time limit'):
                    DrawBot.DrawBotApp.options(self.app(mode=mode, manual=manual))
            for manual in ('5', '180', '3600'):
                with self.subTest(mode=mode, manual=manual):
                    options = DrawBot.DrawBotApp.options(self.app(mode=mode, manual=manual))
                    self.assertEqual(options['manual_max_seconds'], int(manual))
        with self.assertRaisesRegex(ValueError, 'valid time budget'):
            DrawBot.DrawBotApp.options(self.app(mode='Unknown budget', manual='180'))
        app = self.app(mode='Unlimited', manual='')
        app.brush_px.set('0')
        with self.assertRaisesRegex(ValueError, 'Brush width'):
            DrawBot.DrawBotApp.options(app)

    def test_validation_uses_effective_automatic_profile_budget(self):
        app = self.app('Gartic Phone', 'Manual', '')
        app.profile_engine.set('Auto')
        options = DrawBot.DrawBotApp.options(app)
        self.assertEqual(options['time_budget_mode'], 'Gartic Phone Fast')
        self.assertEqual(options['max_seconds'], 67)
        # Conversely Paint Auto resolves a requested fixed preset to Manual.
        app = self.app('Microsoft Paint', 'Skribbl 60', '')
        app.profile_engine.set('Auto')
        with self.assertRaisesRegex(ValueError, 'Time limit'):
            DrawBot.DrawBotApp.options(app)

    def test_options_and_target_cap_use_the_selected_safety_reserve(self):
        from TimeBudget import resolve_target_stroke_count
        for mode in ('Custom', 'Skribbl 60', 'Gartic Phone Fast', '60 sec', 'Manual', 'Unlimited / Accuracy'):
            for reserve in ('Auto', 'Off', '3', '10', '25'):
                with self.subTest(mode=mode, reserve=reserve):
                    app = self.app('Other drawing app', mode, '180')
                    app.deadline_safety_reserve = Value(reserve)
                    options = DrawBot.DrawBotApp.options(app)
                    expected = resolve_budget(mode, 180, reserve)
                    seconds = 3600 if expected['unlimited'] else round(expected['render_budget_seconds'])
                    self.assertEqual(options['max_seconds'], seconds)
                    self.assertEqual(options['time_budget_seconds'], seconds)
                    target, _ = resolve_target_stroke_count('Auto', '2500', time_budget_mode=mode,
                        effective_time_seconds=seconds, speed=options['speed'], drawing_mode=options['drawing_mode'])
                    self.assertEqual(options['target_stroke_count_resolved'], target)

    def test_actual_draw_guard_accepts_a_plan_inside_the_explicit_reserve_budget(self):
        jobs = []
        owned = []
        app = self.app('Other drawing app', 'Skribbl 60')
        app.deadline_safety_reserve = Value('Off')
        app.planning_watchdog = Value('Off')
        with ExitStack() as context:
            app.original = context.enter_context(closing(Image.new('RGB', (20, 20), 'red')))
            app.activity = None; app.closing = False
            app.corners = [(0, 0), (20, 20)]; app.area = lambda: (0, 0, 20, 20)
            app.preview_after = None; app.preview_render_after = None
            app.status = Mock(); app.summary = Mock(); app.root = Mock(); app.mouse = Mock()
            app.target_window = (1, (0, 0, 100, 100))
            app._refresh_target_for_draw = lambda: (0, 0, 100, 100)
            app.stop = threading.Event(); app.paused = threading.Event()
            app.events = queue.Queue(); app.progress = {}; app.save_settings = lambda: True
            app.calibration_path = self.root / 'palette.json'; app.keyboard = None
            app.options = lambda: DrawBot.DrawBotApp.options(app)
            app.begin_worker = lambda activity, work: jobs.append(work) or True
            def plan(image, area, options, cancelled):
                owned.append(image)
                resolved = DrawBot._ensure_time_budget_options(options)
                self.assertEqual(resolved['max_seconds'], 60)
                return {'options': resolved, 'count': 1, 'estimate': 56.0,
                        'groups': [[(2, 2, 4, 2)]]}
            context.enter_context(patch('DrawBot.load_calibration'))
            context.enter_context(patch('DrawBot.allColors', [SimpleNamespace(x=80, y=80, RGB=(0, 0, 0))]))
            context.enter_context(patch.object(DrawBot.DrawBotApp, '_disarm_full_draw'))
            context.enter_context(patch.object(DrawBot.DrawBotApp, '_strict_safety_required', return_value=False))
            context.enter_context(patch.object(DrawBot.DrawBotApp, '_run_browser_visual_preflight', return_value=(0, 0, 100, 100)))
            context.enter_context(patch('ScreenGuard.GuardedMouse'))
            context.enter_context(patch('ScreenGuard.WindowMonitor'))
            context.enter_context(patch('DrawBot.make_plan', side_effect=plan))
            context.enter_context(patch('SessionRecovery.clear_render_progress'))
            execute = context.enter_context(patch('DrawBot.execute_plan'))
            try:
                DrawBot.DrawBotApp.draw(app, user_initiated=True)
                self.assertEqual(len(jobs), 1, app.status.set.call_args)
                jobs[0]()
                execute.assert_called_once()
                self.assertEqual(app.start_state_machine.state, 'COMPLETED')
            finally:
                for image in owned:
                    image.close()

    def test_gartic_draw_worker_preserves_both_unlimited_spellings_before_timer_observation(self):
        class ReachedPlanner(RuntimeError):
            pass
        for mode, expected_observations in (('Unlimited', 0), ('Unlimited / Accuracy', 0), ('Manual', 1)):
            with self.subTest(mode=mode), ExitStack() as context:
                jobs = []
                captured = []
                app = self.app('Gartic Phone', mode)
                app.original = context.enter_context(closing(Image.new('RGB', (20, 20), 'red')))
                app.activity = None; app.closing = False
                app.corners = [(0, 0), (20, 20)]; app.area = lambda: (0, 0, 20, 20)
                app.preview_after = None; app.preview_render_after = None
                app.status = Mock(); app.summary = Mock(); app.root = Mock(); app.mouse = Mock()
                app.target_window = (1, (0, 0, 100, 100))
                app._refresh_target_for_draw = lambda: (0, 0, 100, 100)
                app.stop = threading.Event(); app.paused = threading.Event()
                app.stop.wait = lambda seconds: False
                app.events = queue.Queue(); app.progress = {}; app.save_settings = lambda: True
                app.calibration_path = self.root / 'palette.json'; app.keyboard = None
                app.options = lambda: DrawBot.DrawBotApp.options(app)
                app.begin_worker = lambda activity, work: jobs.append(work) or True
                app.read_gartic_timer = Value(True)
                app.planning_watchdog = Value('Off')
                def capture(**kwargs):
                    image = Image.new('RGB', (100, 100), 'white')
                    captured.append(image)
                    return image
                observed = []
                owned = []
                def planner(image, area, options, cancelled):
                    owned.append(image)
                    observed.append(DrawBot._ensure_time_budget_options(options))
                    raise ReachedPlanner()
                context.enter_context(patch('DrawBot.load_calibration'))
                context.enter_context(patch('DrawBot.allColors', [SimpleNamespace(x=80, y=80, RGB=(0, 0, 0))]))
                context.enter_context(patch.object(DrawBot.DrawBotApp, '_disarm_full_draw'))
                context.enter_context(patch.object(DrawBot.DrawBotApp, '_strict_safety_required', return_value=False))
                context.enter_context(patch.object(DrawBot.DrawBotApp, '_run_browser_visual_preflight', return_value=(0, 0, 100, 100)))
                context.enter_context(patch('ScreenGuard.GuardedMouse'))
                context.enter_context(patch('ScreenGuard.WindowMonitor'))
                context.enter_context(patch('PIL.ImageGrab.grab', side_effect=capture))
                context.enter_context(patch.object(DrawBot.time, 'monotonic', return_value=100.0))
                timer = context.enter_context(patch('GarticTimer.observe_timer', return_value={
                    'deadline': 200.0, 'estimated_seconds': 100.0, 'safe_seconds': 100.0,
                    'observed_seconds': 6.0, 'box': (0, 0, 10, 10)}))
                # apply_timer_budget's default clock is bound at import time.
                from GarticTimer import apply_timer_budget
                context.enter_context(patch('GarticTimer.apply_timer_budget',
                    side_effect=lambda options, reading: apply_timer_budget(options, reading, clock=lambda: 100.0)))
                context.enter_context(patch('DrawBot.make_plan', side_effect=planner))
                execute = context.enter_context(patch('DrawBot.execute_plan'))
                try:
                    DrawBot.DrawBotApp.draw(app, user_initiated=True)
                    self.assertEqual(len(jobs), 1, app.status.set.call_args)
                    with self.assertRaises(ReachedPlanner):
                        jobs[0]()
                    self.assertEqual(timer.call_count, expected_observations)
                    self.assertEqual(observed[0]['time_budget_mode'], mode)
                    self.assertEqual(observed[0]['unlimited_time'], not expected_observations)
                    execute.assert_not_called()
                finally:
                    for image in captured + owned:
                        image.close()


if __name__ == '__main__':
    unittest.main()
